"""Non-interactive CLI (script- and agent-facing).

Contract:
- results go to stdout, progress and logs to stderr;
- exit codes: 0 success / 1 runtime error / 2 usage error / 130 interrupted;
- with ``--json``, stdout is exactly one JSON object and rich output degrades to
  plain text.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.table import Table

from . import __version__ as VERSION
from .base import SiteCrawler
from .models import OutputFormat
from .registry import all_sites, lookup
from .scheduler import ProgressEvent, run_multi
from .state import (
    DONE,
    EMPTY,
    FAILED,
    PENDING,
    SKIPPED,
    Preferences,
    StateStore,
    resume_days,
    resume_plan,
)
from .util import configure_logging, make_crawl_options, parse_date

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_USAGE = 2
EXIT_INTERRUPTED = 130


# ---------------------------------------------------------------- argument parsing


def _parse_date_arg(text: str) -> date:
    """argparse type: parse YYYY-MM-DD / YYYYMMDD; a bad value is a usage error."""
    try:
        return parse_date(text)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _add_download_args(parser: argparse.ArgumentParser) -> None:
    """Shared plan/crawl arguments.

    The flags here default to ``argparse.SUPPRESS``; the effective defaults are
    installed by :func:`_set_download_defaults` once the state store is loaded. A flag
    the user did not type must stay distinguishable from an explicit one, because its
    value may come from the previous run's preferences.
    """
    parser.add_argument(
        "--sites",
        default=argparse.SUPPRESS,
        help="站点 id/名称/别名，逗号分隔（默认 all）",
    )
    parser.add_argument(
        "--start",
        type=_parse_date_arg,
        default=argparse.SUPPRESS,
        help="起始日期 YYYY-MM-DD 或 YYYYMMDD（默认 7 天前，或上次使用的值）",
    )
    parser.add_argument(
        "--end",
        type=_parse_date_arg,
        default=argparse.SUPPRESS,
        help="结束日期 YYYY-MM-DD 或 YYYYMMDD（默认今天，或上次使用的值）",
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=argparse.SUPPRESS,
        help="输出目录（默认 ./downloads；相对路径相对当前工作目录）",
    )
    parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=["md", "txt"],
        default=argparse.SUPPRESS,
        help="输出格式（默认 md，或上次使用的值）",
    )
    parser.add_argument(
        "--site-workers",
        dest="site_workers",
        type=int,
        default=argparse.SUPPRESS,
        help="并发站点数（不同站点互不影响请求频率，默认 4）",
    )


def _set_download_defaults(prefs: Preferences) -> None:
    """Install the effective defaults for the flags the user left out.

    This is the single place the documented CLI defaults live. Applying the defaults
    to the ``plan``/``crawl`` subparsers (rather than the root parser) keeps a flag the
    user never typed present only where it means something: ``sites`` and ``runs``
    still reject ``--start``/``-o``.
    """
    values = dict(
        sites=_prefs_sites(prefs.site_keys),
        start=prefs.start_date,
        end=prefs.end_date,
        output_dir=prefs.output_dir,
        fmt=prefs.output_format,
        site_workers=prefs.site_workers,
    )
    for subparser in _DOWNLOAD_SUBPARSERS:
        subparser.set_defaults(**values)


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    """Preserve epilog line breaks and indentation (examples, field lists)."""


def _add_help_flag(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-h", "--help", action="help", help="显示帮助信息并退出")


def _localize(parser: argparse.ArgumentParser) -> None:
    """Rename argparse's options group heading.

    Note: touches the private ``_optionals`` attribute; no public API exists for it,
    but the attribute has been stable across CPython releases.
    """
    parser._optionals.title = "选项"


def _subparser(sub, name: str, summary: str, epilog: str) -> argparse.ArgumentParser:
    """Build a subcommand parser with the shared help wiring (Chinese help + epilog)."""
    parser = sub.add_parser(
        name,
        help=summary,
        epilog=epilog,
        formatter_class=_HelpFormatter,
        add_help=False,
    )
    _add_help_flag(parser)
    _localize(parser)
    return parser


_IO_AND_EXIT = """\
输出与退出码:
  结果写 stdout，进度与日志写 stderr；--json 时 stdout 为单个 JSON 对象。
  0    成功（含「当日无报纸」这类正常空结果）
  1    运行期错误（抓取失败、站点无法识别等）
  2    用法或参数错误
  130  被 Ctrl+C 中断"""

_MAIN_EPILOG = f"""\
无参数且处于终端时进入交互式菜单。偏好与运行账本存于当前目录的
.newspaper-crawler.json，未显式给出的参数会沿用其中的上次取值。

示例:
  crawler sites --json
  crawler plan  --sites rmrb --start 2026-09-01 --end 2026-09-03 --json
  crawler crawl --sites rmrb,gmrb --start 2026-09-01 --end 2026-09-03
  crawler crawl --sites 人民 --fast          # 站点可用 ID / 名称 / 别名
  crawler runs --json                        # 运行历史与未完成日期
  crawler crawl --resume                     # 续跑上次未完成的日期

{_IO_AND_EXIT}"""

_SITES_EPILOG = """\
列出站点 ID、名称与别名，供 --sites 参数使用。

示例:
  crawler sites
  crawler sites --json"""

_PLAN_EPILOG = """\
不联网、不写盘：按输出目录中已存在的文件或上次运行的账本，判断每个「站点 × 日期」
将抓取还是跳过。

示例:
  crawler plan --sites rmrb --start 2026-09-01 --end 2026-09-03
  crawler plan --sites all --json
  crawler plan --resume --json                  # 只预演上次未完成的日期

--resume:
  只处理上次运行中仍为 pending（中断）或 failed（失败）的日期；无账本时为用法错误。

--json 输出字段:
  sites / unknown_sites / start_date / end_date / output_dir / format
  days     [{site, date, path, exists, action}]，action 为 fetch 或 skip
  summary  {"fetch": N, "skip": N}"""

_CRAWL_EPILOG = """\
示例:
  crawler crawl                                    # 全部站点，最近 7 天
  crawler crawl --sites rmrb --start 20260901 --end 20260903
  crawler crawl --sites all -o ~/paper -f txt --workers 8 --fast
  crawler crawl --sites all --site-workers 1       # 站点改为串行（调试用）
  crawler crawl --resume                           # 只重跑上次未完成的日期
  crawler crawl --sites nope --json                # 站点无法识别 → 退出码 1

站点调度:
  多个站点默认并行（不同站点是不同主机，互不影响对方请求频率）；
  --site-workers 控制并行站点数，--workers 控制单站点内部的文章并发数。

状态持久化:
  偏好与运行账本存于当前目录的 .newspaper-crawler.json（可用 CRAWLER_STATE 覆盖路径）。
  未显式给出的参数沿用该文件中的上次取值；--resume 则按账本只重跑 pending/failed
  的日期，用 crawler runs 查看历史。

--json 输出字段:
  ok              是否全部成功（无错误且无未识别站点）
  sites           实际抓取的站点 ID
  unknown_sites   无法识别的站点输入
  output_dir      输出目录（绝对路径）
  start_date / end_date / format / elapsed_secs
  resumed         是否续传模式
  stats           days_attempted / days_success / days_skipped / days_empty /
                  total_editions / total_articles / total_errors
  files           本次写入的文件路径
  skipped         因已存在而跳过的文件路径
  errors          [{"site": ..., "date": ..., "message": ...}]
  warnings        同上格式；含无法识别的站点、索引页结构疑似变化等（不影响 ok）"""

_RUNS_EPILOG = """\
列出本目录账本中的运行历史，以及上次运行仍未完成的日期。

示例:
  crawler runs
  crawler runs --json

--json 输出字段:
  last_run    {run_id, started_at, output_dir, format, stats, summary}
  open_days   [{site, date, status, path, error}]，status 为 pending 或 failed
  history     [{run_id, started_at, sites, summary}]，最近 20 条
  state_file  账本文件路径"""

# The subcommands whose omitted flags take their value from the stored preferences.
# Filled in by build_parser; see _set_download_defaults.
_DOWNLOAD_SUBPARSERS: list[argparse.ArgumentParser] = []


def build_parser() -> argparse.ArgumentParser:
    """Build the full argument parser.

    Note:
        The ``plan``/``crawl`` flags that may fall back to a stored preference keep
        ``argparse.SUPPRESS`` as their default until :func:`_set_download_defaults`
        runs, so parsing with this parser directly leaves them unset. Use
        :func:`build_parser_with_defaults` unless you want exactly that.
    """
    parser = argparse.ArgumentParser(
        prog="crawler",
        description="报刊下载器：下载人民日报/光明日报/经济日报/大众日报电子版",
        epilog=_MAIN_EPILOG,
        formatter_class=_HelpFormatter,
        add_help=False,
    )
    _add_help_flag(parser)
    _localize(parser)
    parser.add_argument(
        "--version",
        action="version",
        version=f"报刊下载器 v{VERSION}",
        help="显示版本号并退出",
    )
    sub = parser.add_subparsers(dest="command", title="子命令")
    _DOWNLOAD_SUBPARSERS.clear()

    p_sites = _subparser(sub, "sites", "列出可用站点", _SITES_EPILOG)
    p_sites.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_sites.set_defaults(func=cmd_sites)

    p_plan = _subparser(
        sub, "plan", "预演：列出将抓取/跳过的日期（不联网、不写盘）", _PLAN_EPILOG
    )
    _add_download_args(p_plan)
    _DOWNLOAD_SUBPARSERS.append(p_plan)
    p_plan.add_argument(
        "--resume", action="store_true", help="只预演上次未完成的日期（pending/failed）"
    )
    p_plan.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_plan.set_defaults(func=cmd_plan)

    p_crawl = _subparser(sub, "crawl", "执行下载", _CRAWL_EPILOG)
    _add_download_args(p_crawl)
    _DOWNLOAD_SUBPARSERS.append(p_crawl)
    p_crawl.add_argument(
        "--workers", type=int, default=5, help="单站点并发线程数（默认 5）"
    )
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
    p_crawl.add_argument(
        "--resume", action="store_true", help="按账本只重跑上次未完成的日期"
    )
    p_crawl.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    p_crawl.add_argument("-q", "--quiet", action="store_true", help="不输出进度")
    p_crawl.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")
    p_crawl.add_argument(
        "-y", "--yes", action="store_true", help="兼容占位（非交互模式不会询问）"
    )
    p_crawl.set_defaults(func=cmd_crawl)

    p_runs = _subparser(sub, "runs", "查看运行历史与未完成日期", _RUNS_EPILOG)
    p_runs.add_argument("--json", action="store_true", help="以 JSON 输出")
    p_runs.set_defaults(func=cmd_runs)

    _subparser(sub, "interactive", "进入交互式菜单", "").set_defaults(
        func=cmd_interactive
    )

    return parser


# ---------------------------------------------------------------- shared helpers


def _split_tokens(text: str) -> list[str]:
    """Split on comma, full-width comma or space; empty items are dropped."""
    return [p for p in text.replace("，", ",").replace(" ", ",").split(",") if p]


def _resolve_sites(spec: str) -> tuple[list[SiteCrawler], list[str]]:
    """Resolve ``--sites`` into (crawler instances, unrecognized raw tokens).

    Order of the input is preserved and duplicates are collapsed by crawler id.
    """
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
    """Resolve the output directory; relative paths are relative to the CWD.

    ``None`` defaults to ``./downloads`` in the CWD rather than the package location,
    so the default stays correct when installed as a console script.
    """
    if text is None:
        return Path.cwd() / "downloads"
    path = Path(text).expanduser()
    return path if path.is_absolute() else Path.cwd() / path


def _output_format(fmt: str) -> OutputFormat:
    return OutputFormat.TXT if fmt == "txt" else OutputFormat.MD


def _emit_json(obj: dict) -> None:
    print(json.dumps(obj, ensure_ascii=False, indent=2))


# Set once per process by the entry point; every subcommand reads it through the
# module global so that tests and library callers can substitute their own store.
_store: Optional[StateStore] = None


def _get_store() -> StateStore:
    global _store
    if _store is None:
        _store = StateStore()
    return _store


_STATUS_CN = {
    DONE: "完成",
    SKIPPED: "跳过",
    EMPTY: "无报",
    FAILED: "失败",
    PENDING: "待抓",
}


def _site_name(key: str) -> str:
    """Display name of a stored site key (falls back to the key itself)."""
    site = lookup(key)
    return site.name if site else key


class _Settings:
    """Fully resolved crawl settings: explicit CLI values over stored preferences."""

    def __init__(
        self,
        sites: list[SiteCrawler],
        unknown: list[str],
        start: date,
        end: date,
        output_dir: Path,
        fmt: OutputFormat,
    ):
        self.sites = sites
        self.unknown = unknown
        self.start = start
        self.end = end
        self.output_dir = output_dir
        self.fmt = fmt

    @property
    def keys(self) -> list[str]:
        return [s.crawler_id for s in self.sites]


def _resolve_settings(args: argparse.Namespace, store: StateStore) -> _Settings:
    """Turn parsed arguments into concrete settings.

    The parser already folded the stored preferences into the defaults
    (:func:`_set_download_defaults`), so an explicitly typed flag has simply overwritten
    the corresponding attribute and no special-casing is needed here.
    """
    sites, unknown = _resolve_sites(args.sites)
    return _Settings(
        sites=sites,
        unknown=unknown,
        start=args.start,
        end=args.end,
        output_dir=_resolve_output_dir(args.output_dir),
        fmt=_output_format(args.fmt),
    )


def _prefs_sites(keys: list[str]) -> str:
    """Render stored site keys as a ``--sites`` value (empty list means all sites)."""
    return ",".join(keys) if keys else "all"


def _update_preferences(
    store: StateStore,
    sites: list[SiteCrawler],
    start: date,
    end: date,
    output_dir: Path,
    fmt: OutputFormat,
    max_workers: int,
    fast: bool,
    skip_existing: bool,
    site_workers: int,
) -> None:
    """Persist what the run actually used, so the next run defaults to it."""
    store.save_preferences(
        site_keys=[s.crawler_id for s in sites],
        start_date=start,
        end_date=end,
        output_dir=str(output_dir),
        output_format=fmt.ext(),
        max_workers=max_workers,
        fast_mode=fast,
        skip_existing=skip_existing,
        site_workers=site_workers,
    )


def _make_on_day(store: StateStore):
    """Ledger hook for the scheduler: persist one day's outcome, never raise.

    The scheduler runs this from several site threads; the store serializes its own
    writes. A failure to persist must not abort a crawl that is otherwise working, so
    errors are logged and swallowed.
    """

    def on_day(site, day, status, path, error) -> None:
        with contextlib.suppress(OSError):
            store.record_day(site, day, status, path=path, error=error)

    return on_day


class _Progress:
    """Scheduler event handler: prints progress lines and collects JSON payload data.

    Invariant: warnings and errors are kept apart. A warning (e.g. unrecognized site,
    suspected site redesign) does not affect ``ok``; only a day_error does.
    """

    def __init__(self, console: Console | None):
        self.console = console
        self.files: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def __call__(self, ev: ProgressEvent) -> None:
        if ev.path is not None:
            if ev.kind == "day_done":
                self.files.append(str(ev.path))
            elif ev.kind == "day_skip":
                self.skipped.append(str(ev.path))
        if ev.kind == "day_error":
            self.errors.append(self._entry(ev))
        elif ev.kind == "log" and ev.level == "error":
            self.errors.append({"site": ev.site, "date": None, "message": ev.message})
        elif ev.kind == "log" and ev.level == "warn":
            self.warnings.append(self._entry(ev))
        if self.console is not None:
            self.console.print(ev.message)

    @staticmethod
    def _entry(ev: ProgressEvent) -> dict:
        return {
            "site": ev.site,
            "date": ev.date.isoformat() if ev.date else None,
            "message": ev.message,
        }


# ---------------------------------------------------------------- subcommands


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
    store = _get_store()
    resumed = resume_plan(store) if args.resume else None
    if args.resume and resumed is None:
        print("错误：没有可续传的任务。", file=sys.stderr)
        return EXIT_ERROR

    if resumed is not None:
        # Resume mode is ledger-driven: the work is exactly the open (site, date)
        # pairs, so the days are listed as-is instead of re-walking a date range.
        open_days, output_dir, fmt_name = resumed
        fmt = _output_format(fmt_name)
        resolved = [(d, lookup(d.site)) for d in open_days]
        unknown = sorted({d.site for d, site in resolved if site is None})
        days = []
        for entry, site in resolved:
            if site is None:
                continue
            path = site.day_filepath(entry.date, output_dir, fmt.ext())
            days.append(
                {
                    "site": site.name,
                    "date": entry.date.isoformat(),
                    "path": str(path),
                    "exists": path.exists(),
                    "status": entry.status,
                    "action": "skip" if path.exists() else "fetch",
                }
            )
        keys = sorted({d.site for d, site in resolved if site is not None})
        start, end = min(d.date for d in open_days), max(d.date for d in open_days)
        site_names = "、".join(_site_name(k) for k in keys) or "（无）"
    else:
        settings = _resolve_settings(args, store)
        keys, unknown = settings.keys, settings.unknown
        output_dir, fmt, start, end = (
            settings.output_dir,
            settings.fmt,
            settings.start,
            settings.end,
        )
        days = []
        for site in settings.sites:
            current = settings.start
            while current <= settings.end:
                path = site.day_filepath(current, settings.output_dir, settings.fmt.ext())
                days.append(
                    {
                        "site": site.name,
                        "date": current.isoformat(),
                        "path": str(path),
                        "exists": path.exists(),
                        "status": None,
                        "action": "skip" if path.exists() else "fetch",
                    }
                )
                current += timedelta(days=1)
        site_names = "、".join(s.name for s in settings.sites) or "（无）"

    fetch = sum(1 for d in days if d["action"] == "fetch")
    skip = len(days) - fetch
    result = {
        "sites": keys,
        "unknown_sites": unknown,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "output_dir": str(output_dir),
        "format": fmt.ext(),
        "resumed": bool(args.resume),
        "days": days,
        "summary": {"fetch": fetch, "skip": skip},
    }
    if args.json:
        _emit_json(result)
    else:
        console = Console()
        console.print(
            f"站点：{site_names}\n"
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
    store = _get_store()
    resumed = resume_plan(store) if args.resume else None
    if args.resume and resumed is None:
        print("错误：没有可续传的任务。", file=sys.stderr)
        return EXIT_ERROR

    if resumed is not None:
        open_days, output_dir, fmt_name = resumed
        keys = sorted({d.site for d in open_days})
        sites = [s for s in (lookup(k) for k in keys) if s is not None]
        dates = [d.date for d in open_days]
        unknown: list[str] = []
        start, end = min(dates), max(dates)
        fmt = _output_format(fmt_name)
    else:
        settings = _resolve_settings(args, store)
        sites, unknown = settings.sites, settings.unknown
        keys = settings.keys
        output_dir, fmt = settings.output_dir, settings.fmt
        start, end = settings.start, settings.end

    opts = make_crawl_options(
        start=start,
        end=end,
        output_dir=output_dir,
        output_format=fmt,
        workers=args.workers,
        fast=args.fast,
        skip_existing=args.skip_existing,
    )
    workers = opts.max_workers
    site_workers = max(1, args.site_workers or store.preferences.site_workers)

    console = (
        None
        if args.quiet
        else Console(stderr=True, no_color=args.json, highlight=False)
    )
    progress = _Progress(console)

    if console is not None:
        names = "、".join(s.name for s in sites) or "（无）"
        console.print(
            f"站点：{names} · 日期：{start} ~ {end} · "
            f"输出：{output_dir} · 格式：{fmt.ext()} · "
            f"并发：{site_workers} 站点 × {workers} 线程 · "
            f"快速模式：{'开' if args.fast else '关'} · "
            f"断点续传：{'开' if args.skip_existing else '关'}"
            + (" · 模式：续传上次未完成" if resumed is not None else "")
        )
    if unknown:
        print(f"警告：无法识别的站点：{'、'.join(unknown)}", file=sys.stderr)

    # The ledger is written before the crawl starts, so an interruption still leaves
    # the remaining days recorded as pending.
    if resumed is not None:
        store.start_run(keys, start, end, output_dir, fmt.ext(), days=open_days)
        days_by_site = resume_days(open_days)
    else:
        store.start_run(keys, start, end, output_dir, fmt.ext())
        days_by_site = None

    started = time.monotonic()
    stats = run_multi(
        keys,
        opts,
        on_event=progress,
        max_site_workers=site_workers,
        on_day=_make_on_day(store),
        days_by_site=days_by_site,
    )
    elapsed = time.monotonic() - started

    store.finish_run(stats.as_dict())
    if resumed is None:
        _update_preferences(
            store,
            sites,
            start,
            end,
            output_dir,
            fmt,
            workers,
            args.fast,
            args.skip_existing,
            site_workers,
        )

    ok = not unknown and not progress.errors
    result = {
        "ok": ok,
        "sites": keys,
        "unknown_sites": unknown,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "output_dir": str(output_dir),
        "format": fmt.ext(),
        "elapsed_secs": round(elapsed, 1),
        "resumed": resumed is not None,
        "stats": stats.as_dict(),
        "files": progress.files,
        "skipped": progress.skipped,
        "errors": progress.errors,
        "warnings": progress.warnings,
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


def cmd_runs(args: argparse.Namespace) -> int:
    store = _get_store()
    last = store.last_run
    open_days = store.open_days()
    result = {
        "state_file": str(store.path),
        "last_run": (
            {
                "run_id": last.run_id,
                "started_at": last.started_at,
                "output_dir": last.output_dir,
                "format": last.fmt,
                "stats": last.stats,
                "summary": StateStore.summary(last),
            }
            if last is not None
            else None
        ),
        "open_days": [
            {
                "site": d.site,
                "date": d.date.isoformat(),
                "status": d.status,
                "path": d.path,
                "error": d.error,
            }
            for d in open_days
        ],
        "open_count": len(open_days),
        "history": store.history,
    }
    if args.json:
        _emit_json(result)
        return EXIT_OK

    console = Console()
    if last is None:
        console.print(f"暂无运行记录（账本：{store.path}）")
        return EXIT_OK

    summary = StateStore.summary(last)
    console.print(
        f"最近一次运行：{last.run_id}（{last.started_at}）\n"
        f"输出目录：{last.output_dir} · 格式：{last.fmt}\n"
        + " · ".join(f"{_STATUS_CN[k]} {v}" for k, v in summary.items())
    )
    if open_days:
        table = Table(title=f"未完成 {len(open_days)} 天", header_style="bold yellow")
        table.add_column("站点", style="bold")
        table.add_column("日期")
        table.add_column("状态")
        table.add_column("说明", style="dim")
        for d in open_days:
            table.add_row(
                _site_name(d.site),
                d.date.isoformat(),
                _STATUS_CN.get(d.status, d.status),
                d.error or d.path or "",
            )
        console.print(table)
        console.print("用 crawler crawl --resume 续跑这些日期。")

    if store.history:
        history = Table(title="运行历史", header_style="bold cyan")
        history.add_column("运行 ID", style="bold")
        history.add_column("开始时间")
        history.add_column("站点", style="dim")
        history.add_column("结果")
        for item in store.history:
            counts = item.get("summary") or {}
            history.add_row(
                str(item.get("run_id", "")),
                str(item.get("started_at", "")),
                "、".join(_site_name(str(s)) for s in item.get("sites") or []),
                " · ".join(f"{_STATUS_CN.get(k, k)} {v}" for k, v in counts.items()),
            )
        console.print(history)
    return EXIT_OK


def cmd_interactive(args: argparse.Namespace) -> int:
    from . import tui

    return tui.run()


# ---------------------------------------------------------------- entry points


def build_parser_with_defaults(
    prefs: Optional[Preferences] = None,
) -> argparse.ArgumentParser:
    """Build a parser whose omitted download flags fall back to ``prefs``.

    Args:
        prefs: defaults to the stored preferences of the working directory.
    """
    parser = build_parser()
    _set_download_defaults(prefs if prefs is not None else StateStore().preferences)
    return parser


def _run_subcommand(argv: list[str]) -> int:
    parser = build_parser()
    store = _get_store()
    # Flags the user left out take their value from the previous run; installing the
    # defaults before parsing keeps a single resolution point for both subcommands.
    _set_download_defaults(store.preferences)
    args = parser.parse_args(argv)
    if not getattr(args, "command", None):
        parser.print_usage(sys.stderr)
        print(
            "错误：非交互模式请指定子命令"
            "（crawl / sites / plan / runs / interactive）。",
            file=sys.stderr,
        )
        return EXIT_USAGE
    if hasattr(args, "start") and not args.resume:
        settings = _resolve_settings(args, store)
        if settings.end < settings.start:
            print("错误：--end 不能早于 --start。", file=sys.stderr)
            return EXIT_USAGE
    return args.func(args)


def main(argv: list[str] | None = None) -> int:
    """Single entry point: TUI when invoked with no args on a TTY, else subcommands."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv and sys.stdin.isatty() and sys.stdout.isatty():
        from . import tui

        return tui.run()
    try:
        return _run_subcommand(argv)
    except KeyboardInterrupt:
        print("\n已中断。", file=sys.stderr)
        return EXIT_INTERRUPTED
