"""非交互命令行接口（面向脚本与 agent）。

约定：
- 结果写 stdout，进度写 stderr；
- 退出码 0 成功 / 1 运行期错误 / 2 用法错误 / 130 中断；
- ``--json`` 时 stdout 为单个 JSON 对象，rich 降级为纯文本。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

from rich.console import Console
from rich.table import Table

from . import __version__ as VERSION
from .base import SiteCrawler
from .models import OutputFormat
from .registry import all_sites, lookup
from .scheduler import ProgressEvent, run_multi
from .util import configure_logging, make_crawl_options, parse_date, project_root

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


# ---------------------------------------------------------------- 参数解析


def _parse_date_arg(text: str) -> date:
    """argparse 用：把 YYYY-MM-DD / YYYYMMDD 解析为 date，失败即用法错误。"""
    try:
        return parse_date(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _add_download_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--sites", default="all", help="站点 id/名称/别名，逗号分隔（默认 all）"
    )
    parser.add_argument(
        "--start",
        type=_parse_date_arg,
        default=date.today() - timedelta(days=6),
        help="起始日期 YYYY-MM-DD 或 YYYYMMDD（默认 7 天前）",
    )
    parser.add_argument(
        "--end",
        type=_parse_date_arg,
        default=date.today(),
        help="结束日期 YYYY-MM-DD 或 YYYYMMDD（默认今天）",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=None,
        help="输出目录（默认 <项目目录>/downloads；相对路径相对当前工作目录）",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=["md", "txt"],
        default="md",
        help="输出格式（默认 md）",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawler",
        description="报刊下载器：下载人民日报/光明日报/经济日报/大众日报电子版",
    )
    parser.add_argument("--version", action="version", version=f"报刊下载器 v{VERSION}")
    sub = parser.add_subparsers(dest="command", metavar="命令")

    p_sites = sub.add_parser("sites", help="列出可用站点")
    p_sites.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_sites.set_defaults(func=cmd_sites)

    p_plan = sub.add_parser(
        "plan", help="预演：列出将抓取/跳过的日期（不联网、不写盘）"
    )
    _add_download_args(p_plan)
    p_plan.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_plan.set_defaults(func=cmd_plan)

    p_crawl = sub.add_parser("crawl", help="执行下载")
    _add_download_args(p_crawl)
    p_crawl.add_argument("--workers", type=int, default=5, help="并发线程数（默认 5）")
    p_crawl.add_argument(
        "--fast", action="store_true", help="快速模式（降低延迟、加大并发）"
    )
    p_crawl.add_argument(
        "--skip-existing",
        dest="skip_existing",
        action="store_true",
        default=True,
        help="跳过已下载日期（默认开启）",
    )
    p_crawl.add_argument(
        "--no-skip-existing",
        dest="skip_existing",
        action="store_false",
        help="不跳过已下载日期，重新抓取",
    )
    p_crawl.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_crawl.add_argument("-q", "--quiet", action="store_true", help="不输出进度")
    p_crawl.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    p_crawl.add_argument(
        "-y", "--yes", action="store_true", help="兼容占位（非交互模式不会询问）"
    )
    p_crawl.set_defaults(func=cmd_crawl)

    p_interactive = sub.add_parser("interactive", help="进入交互式菜单")
    p_interactive.set_defaults(func=cmd_interactive)

    return parser


# ---------------------------------------------------------------- 通用工具


def _split_tokens(text: str) -> list[str]:
    """按逗号/中文逗号/空格切分（忽略空项）。"""
    return [p for p in text.replace("，", ",").replace(" ", ",").split(",") if p]


def _resolve_sites(spec: str) -> tuple[list[SiteCrawler], list[str]]:
    """把 --sites 规格解析为 (站点实例列表, 无法识别的原始输入)。"""
    if spec.strip().lower() in ("", "all"):
        return all_sites(), []
    sites: list[SiteCrawler] = []
    unknown: list[str] = []
    seen: set[str] = set()
    for token in _split_tokens(spec):
        site = lookup(token)
        if site is None:
            unknown.append(token)
        elif site.crawler_id not in seen:
            seen.add(site.crawler_id)
            sites.append(site)
    return sites, unknown


def _resolve_output_dir(text: str | None) -> Path:
    """默认输出目录为项目下 downloads；显式相对路径按当前工作目录解析。"""
    if text is None:
        return project_root() / "downloads"
    path = Path(text).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _output_format(fmt: str) -> OutputFormat:
    return OutputFormat.TXT if fmt == "txt" else OutputFormat.MD


def _emit_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


class _Progress:
    """调度事件处理器：输出进度行，并收集 JSON 结果所需的结构化数据。"""

    def __init__(self, console: Console | None):
        self.console = console
        self.files: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[dict] = []

    def __call__(self, ev: ProgressEvent) -> None:
        if ev.path is not None:
            if ev.kind == "day_done":
                self.files.append(str(ev.path))
            elif ev.kind == "day_skip":
                self.skipped.append(str(ev.path))
        if ev.kind == "day_error":
            self.errors.append(
                {
                    "site": ev.site,
                    "date": ev.date.isoformat() if ev.date else None,
                    "message": ev.message,
                }
            )
        elif ev.kind == "log" and ev.level == "error":
            self.errors.append({"site": ev.site, "date": None, "message": ev.message})
        if self.console is not None:
            self.console.print(ev.message)


# ---------------------------------------------------------------- 子命令


def cmd_sites(args: argparse.Namespace) -> int:
    sites = all_sites()
    if args.json:
        _emit_json(
            {
                "sites": [
                    {
                        "id": s.crawler_id,
                        "name": s.name,
                        "aliases": list(s.aliases or []),
                        "base_url": s.base_url,
                    }
                    for s in sites
                ]
            }
        )
        return EXIT_OK

    table = Table(title="可用站点", header_style="bold cyan")
    table.add_column("ID", style="bold")
    table.add_column("名称", style="green")
    table.add_column("别名", style="dim")
    table.add_column("主页", style="dim")
    for s in sites:
        table.add_row(s.crawler_id, s.name, " / ".join(s.aliases or []), s.base_url)
    Console().print(table)
    return EXIT_OK


def cmd_plan(args: argparse.Namespace) -> int:
    sites, unknown = _resolve_sites(args.sites)
    output_dir = _resolve_output_dir(args.output_dir)
    fmt = _output_format(args.fmt)

    days = []
    for site in sites:
        current = args.start
        while current <= args.end:
            path = site.day_filepath(current, output_dir, fmt.ext())
            exists = path.exists()
            days.append(
                {
                    "site": site.name,
                    "date": current.isoformat(),
                    "path": str(path),
                    "exists": exists,
                    "action": "skip" if exists else "fetch",
                }
            )
            current += timedelta(days=1)

    fetch = sum(1 for d in days if d["action"] == "fetch")
    skip = len(days) - fetch
    result = {
        "sites": [s.crawler_id for s in sites],
        "unknown_sites": unknown,
        "start_date": args.start.isoformat(),
        "end_date": args.end.isoformat(),
        "output_dir": str(output_dir),
        "format": fmt.ext(),
        "days": days,
        "summary": {"fetch": fetch, "skip": skip},
    }
    if args.json:
        _emit_json(result)
    else:
        console = Console()
        names = "、".join(s.name for s in sites) or "（无）"
        console.print(
            f"站点：{names}\n"
            f"日期：{result['start_date']} ~ {result['end_date']}\n"
            f"输出目录：{output_dir}\n"
            f"将抓取 {fetch} 天 · 将跳过 {skip} 天"
        )
        for item in days:
            if item["action"] == "fetch":
                console.print(
                    f"  fetch  {item['date']}  {item['site']}  {item['path']}"
                )

    if unknown:
        print(f"错误：无法识别的站点：{'、'.join(unknown)}", file=sys.stderr)
        return EXIT_ERROR
    return EXIT_OK


def cmd_crawl(args: argparse.Namespace) -> int:
    configure_logging(args.verbose)
    sites, unknown = _resolve_sites(args.sites)
    keys = [s.crawler_id for s in sites]
    output_dir = _resolve_output_dir(args.output_dir)
    fmt = _output_format(args.fmt)
    opts, workers = make_crawl_options(
        start=args.start,
        end=args.end,
        output_dir=output_dir,
        output_format=fmt,
        workers=args.workers,
        fast=args.fast,
        skip_existing=args.skip_existing,
    )

    console = (
        None
        if args.quiet
        else Console(stderr=True, no_color=args.json, highlight=False)
    )
    progress = _Progress(console)

    if console is not None:
        names = "、".join(s.name for s in sites) or "（无）"
        console.print(
            f"站点：{names} · 日期：{args.start} ~ {args.end} · "
            f"输出：{output_dir} · 格式：{fmt.ext()} · 并发：{workers} · "
            f"快速模式：{'开' if args.fast else '关'} · "
            f"断点续传：{'开' if args.skip_existing else '关'}"
        )
    if unknown:
        print(f"警告：无法识别的站点：{'、'.join(unknown)}", file=sys.stderr)

    started = time.monotonic()
    stats = run_multi(keys, opts, on_event=progress)
    elapsed = time.monotonic() - started

    ok = not unknown and not progress.errors
    result = {
        "ok": ok,
        "sites": keys,
        "unknown_sites": unknown,
        "start_date": args.start.isoformat(),
        "end_date": args.end.isoformat(),
        "output_dir": str(output_dir),
        "format": fmt.ext(),
        "elapsed_secs": round(elapsed, 1),
        "stats": stats.as_dict(),
        "files": progress.files,
        "skipped": progress.skipped,
        "errors": progress.errors,
    }
    if args.json:
        _emit_json(result)
    else:
        out = Console()
        out.print(f"完成 · {stats}")
        out.print(f"输出目录：{output_dir}")
        if progress.files:
            out.print(f"本次写入 {len(progress.files)} 个文件")
    return EXIT_OK if ok else EXIT_ERROR


def cmd_interactive(args: argparse.Namespace) -> int:
    from . import tui

    return tui.run()


# ---------------------------------------------------------------- 入口


def _run_subcommand(argv: list[str]) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        print(
            "错误：非交互模式请指定子命令（crawl / sites / plan / interactive）。",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if hasattr(args, "start") and args.end < args.start:
        print("错误：--end 不能早于 --start。", file=sys.stderr)
        return EXIT_USAGE
    return args.func(args)


def main(argv: list[str] | None = None) -> int:
    """统一入口：无参数且处于终端时进入交互菜单，否则走子命令。"""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv and sys.stdin.isatty() and sys.stdout.isatty():
        from . import tui

        return tui.run()
    try:
        return _run_subcommand(argv)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return EXIT_INTERRUPTED
