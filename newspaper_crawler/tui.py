"""Interactive terminal UI (rich menus).

The interactive flow was moved here verbatim from the original ``crawler.py``;
behavior is unchanged apart from preference persistence: menu choices are written to
the project state file as they are made, and re-applied the next time the menu opens.
"""

from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from . import __version__ as VERSION
from .models import OutputFormat
from .registry import all_sites, lookup
from .scheduler import run_multi
from .state import Preferences, StateStore, resume_days, resume_plan
from .util import configure_logging, make_crawl_options, parse_date

console = Console()


class _InputClosed(Exception):
    """Raised when stdin is closed (Ctrl+D / end of pipe); callers exit gracefully."""


def ask(prompt: str, **kwargs):
    """Prompt.ask wrapper: raises _InputClosed instead of EOFError."""
    try:
        return Prompt.ask(prompt, **kwargs)
    except EOFError:
        raise _InputClosed from None


def confirm(prompt: str, **kwargs):
    """Confirm.ask wrapper: raises _InputClosed instead of EOFError."""
    try:
        return Confirm.ask(prompt, **kwargs)
    except EOFError:
        raise _InputClosed from None


def _parse_site_selection(answer: str, count: int) -> list:
    """Parse a multi-select answer into 1-based indexes.

    Accepts "all" (every index) or comma/space-separated numbers; out-of-range and
    non-numeric tokens are reported and dropped. Returns a sorted, de-duplicated list.
    """
    answer = answer.strip().lower()
    if answer == "all":
        return list(range(1, count + 1))
    parts = [p for p in answer.replace("，", ",").replace(" ", ",").split(",") if p]
    idxs = []
    for p in parts:
        if p.isdigit() and 1 <= int(p) <= count:
            idxs.append(int(p))
        else:
            console.print(f"[yellow]忽略无效输入：{p}[/yellow]")
    return sorted(set(idxs))


# ---------------------------------------------------------------- menus


def print_banner() -> None:
    banner = Panel(
        Text.assemble(
            ("报刊下载器 · 电子报批量下载\n", "bold cyan"),
            ("人民日报 / 光明日报 / 经济日报 / 大众日报\n", "dim"),
            (f"v{VERSION} · 交互式命令行版", "italic"),
        ),
        border_style="cyan",
        title="📰",
    )
    console.print(banner)


def default_state() -> dict:
    """Initial state: last 7 days, all sites, ``./downloads``."""
    today = date.today()
    return {
        "site_keys": [],  # empty == all sites; filled in by the site menu
        "start_date": today - timedelta(days=6),
        "end_date": today,
        "output_dir": Path.cwd() / "downloads",
        "output_format": "md",  # md | txt
        "max_workers": 5,
        "fast_mode": False,
        "skip_existing": True,
    }


def state_from_preferences(prefs: Preferences) -> dict:
    """Build the menu state from stored preferences (falling back to the defaults).

    A relative stored ``output_dir`` is resolved against the working directory, the same
    rule the output-dir menu applies, so the menu always shows one absolute path.
    """
    output_dir = Path(os.path.expanduser(prefs.output_dir))
    if not output_dir.is_absolute():
        output_dir = Path.cwd() / output_dir
    state = default_state()
    state.update(
        site_keys=list(prefs.site_keys),
        start_date=prefs.start_date,
        end_date=prefs.end_date,
        output_dir=output_dir,
        output_format=prefs.output_format,
        max_workers=prefs.max_workers,
        fast_mode=prefs.fast_mode,
        skip_existing=prefs.skip_existing,
    )
    return state


def _prefs_from_state(state: dict) -> dict:
    """The persistable slice of the menu state, keyed by preference field name."""
    return {
        "site_keys": list(state["site_keys"]),
        "start_date": state["start_date"],
        "end_date": state["end_date"],
        "output_dir": str(state["output_dir"]),
        "output_format": state["output_format"],
        "max_workers": state["max_workers"],
        "fast_mode": state["fast_mode"],
        "skip_existing": state["skip_existing"],
    }


def save_preferences(state: dict, store: Optional[StateStore]) -> None:
    """Persist the current menu state; a missing store means no persistence."""
    if store is not None:
        store.save_preferences(**_prefs_from_state(state))


def choose_sites(state: dict, store: Optional[StateStore] = None) -> None:
    """Menu 1: pick newspapers (multi-select, defaults to all)."""
    sites = all_sites()
    if not sites:
        console.print("[red]未找到可用站点（站点模块加载失败）[/red]")
        return

    table = Table(title="可选报纸", header_style="bold cyan")
    table.add_column("编号", justify="right", style="cyan")
    table.add_column("ID", style="bold")
    table.add_column("名称", style="green")
    table.add_column("别名", style="dim")
    for i, site in enumerate(sites, 1):
        table.add_row(
            str(i), site.crawler_id, site.name, " / ".join(site.aliases or [])
        )
    console.print(table)

    current_idx = [
        i for i, s in enumerate(sites, 1) if s.crawler_id in state["site_keys"]
    ]
    default_hint = (
        "，".join(str(i) for i in current_idx)
        if current_idx
        else "，".join(str(i) for i in range(1, len(sites) + 1))
    )
    answer = ask(
        "请选择站点编号（逗号/空格分隔；all=全选；留空=保持当前）",
        default=default_hint,
    )
    selected = _parse_site_selection(answer, len(sites))
    if not selected:
        console.print("[yellow]未选择任何站点，保持原选择[/yellow]")
        return
    state["site_keys"] = [sites[i - 1].crawler_id for i in selected]
    names = [s.name for i, s in enumerate(sites, 1) if i in selected]
    console.print(f"[green]已选：{'、'.join(names)}[/green]")
    save_preferences(state, store)


def choose_dates(state: dict, store: Optional[StateStore] = None) -> None:
    """Menu 2: set the date range. Keeps the previous range on invalid input."""
    console.print(
        Panel(
            f"当前范围：[bold]{state['start_date']} ~ {state['end_date']}[/bold]",
            title="日期范围",
            border_style="cyan",
        )
    )
    old_start, old_end = state["start_date"], state["end_date"]

    start_s = ask(
        "起始日期（YYYY-MM-DD 或 YYYYMMDD，留空保持）",
        default=old_start.isoformat(),
    )
    end_s = ask(
        "结束日期（YYYY-MM-DD 或 YYYYMMDD，留空保持）",
        default=old_end.isoformat(),
    )
    try:
        start = parse_date(start_s)
        end = parse_date(end_s)
    except ValueError as exc:
        console.print(f"[red]{exc}，已保持原范围[/red]")
        return

    if end < start:
        console.print("[red]结束日期不能早于起始日期，已保持原范围[/red]")
        return
    state["start_date"], state["end_date"] = start, end
    if end > date.today():
        console.print(
            "[yellow]提示：结束日期晚于今天，今天可能还没有当日电子报[/yellow]"
        )
    console.print(f"[green]日期范围：{start} ~ {end}[/green]")
    save_preferences(state, store)


def choose_output_dir(state: dict, store: Optional[StateStore] = None) -> None:
    """Menu 3: set the output directory (``~`` expanded, relative to the CWD)."""
    answer = ask(
        "输出目录（支持 ~；留空保持当前）",
        default=str(state["output_dir"]),
    ).strip()
    if answer:
        path = Path(os.path.expanduser(answer))
        if not path.is_absolute():
            path = Path.cwd() / path
        state["output_dir"] = path
    console.print(f"[green]输出目录：{state['output_dir']}[/green]")
    save_preferences(state, store)


def choose_format(state: dict, store: Optional[StateStore] = None) -> None:
    """Menu 4: set the output format."""
    fmt = ask("输出格式", choices=["md", "txt"], default=state["output_format"])
    state["output_format"] = fmt
    console.print(f"[green]输出格式：{fmt}[/green]")
    save_preferences(state, store)


def choose_advanced(state: dict, store: Optional[StateStore] = None) -> None:
    """Menu 5: article concurrency, fast mode, skip-existing."""
    console.print(Panel("高级选项", border_style="cyan"))

    workers = ask("并发线程数", default=str(state["max_workers"]))
    try:
        state["max_workers"] = max(1, int(workers))
    except ValueError:
        console.print("[yellow]并发数无效，保持原值[/yellow]")

    state["fast_mode"] = confirm(
        "快速模式（降低延迟、加大并发，谨慎使用）", default=state["fast_mode"]
    )
    state["skip_existing"] = confirm(
        "断点续传（已下载日期自动跳过）", default=state["skip_existing"]
    )
    console.print(
        f"[green]并发 {state['max_workers']} · 快速模式 {'开' if state['fast_mode'] else '关'} · "
        f"断点续传 {'开' if state['skip_existing'] else '关'}[/green]"
    )
    save_preferences(state, store)


# ---------------------------------------------------------------- event rendering


_KIND_COLOR = {
    "site_start": "cyan",
    "day_start": "cyan",
    "day_skip": "yellow",
    "day_empty": "yellow",
    "day_error": "red",
    "day_done": "green",
    "site_done": "cyan",
    "finished": "bold green",
}


def handle_event(ev) -> None:
    """Colour-code the scheduler message by event kind.

    Renders ``ev.message`` verbatim: the message is already complete, so prefixing it
    with the site name here would duplicate it.
    """
    if not ev.message:
        return
    if ev.kind == "log":
        color = {"warn": "yellow", "error": "red"}.get(ev.level, "cyan")
    else:
        color = _KIND_COLOR.get(ev.kind, "cyan")
    console.print(f"[{color}]{ev.message}[/{color}]")


# ---------------------------------------------------------------- download flow


def start_download(state: dict, store: Optional[StateStore] = None) -> None:
    """Menu 6: run the crawl with the current state.

    When the ledger holds days left open by an earlier run, the user is offered a
    resume instead. Either way every (site, date) outcome is written to the ledger as
    it happens, so an interruption loses at most the day in flight.
    """
    if store is not None and _offer_resume(state, store):
        return

    site_keys = state["site_keys"] or [s.crawler_id for s in all_sites()]
    if not site_keys:
        console.print("[red]请先选择报纸（菜单 1）[/red]")
        return

    site_names = []
    for key in site_keys:
        site = lookup(key)
        site_names.append(site.name if site else key)

    fmt = OutputFormat.TXT if state["output_format"] == "txt" else OutputFormat.MD
    opts = make_crawl_options(
        start=state["start_date"],
        end=state["end_date"],
        output_dir=state["output_dir"],
        output_format=fmt,
        workers=state["max_workers"],
        fast=state["fast_mode"],
        skip_existing=state["skip_existing"],
    )

    summary = (
        f"报纸：{'、'.join(site_names)}\n"
        f"日期：{state['start_date']} ~ {state['end_date']}\n"
        f"输出目录：{state['output_dir']}\n"
        f"格式：{state['output_format']} · 并发：{opts.max_workers} · "
        f"快速模式：{'开' if state['fast_mode'] else '关'} · "
        f"断点续传：{'开' if state['skip_existing'] else '关'}"
    )
    console.print(Panel(summary, title="下载配置", border_style="green"))
    if not confirm("确认开始下载？", default=True):
        return

    save_preferences(state, store)
    run_crawl(state, store, site_keys, opts)


def _offer_resume(state: dict, store: StateStore) -> bool:
    """Offer to continue the days a previous run left open.

    Returns:
        True when a resume was offered and either started or abandoned by the user, so
        the caller must not go on to a fresh run. False when there is nothing to resume
        or the user declined, in which case the normal flow continues.
    """
    open_days = store.open_days()
    if not open_days:
        return False
    if not confirm(
        f"发现上次未完成的 {len(open_days)} 天，继续这些日期？"
        "（否=按当前设置开始新任务）",
        default=True,
    ):
        return False

    planned = _resume_options(open_days, store)
    if planned is None:  # The ledger references sites that no longer exist.
        return True
    site_keys, opts, days_by_site = planned
    run_crawl(state, store, site_keys, opts, days_by_site=days_by_site)
    return True


def _resume_options(open_days, store: StateStore):
    """Build the crawl options for the ledger's open days, or None when unusable."""
    planned = resume_plan(store)
    if planned is None:
        return None
    _, output_dir, fmt_name = planned
    keys = sorted({d.site for d in open_days})
    missing = [k for k in keys if lookup(k) is None]
    if missing:
        console.print(f"[red]账本中的站点已不可用：{'、'.join(missing)}[/red]")
        return None
    fmt = OutputFormat.TXT if fmt_name == "txt" else OutputFormat.MD
    dates = [d.date for d in open_days]
    opts = make_crawl_options(
        start=min(dates),
        end=max(dates),
        output_dir=output_dir,
        output_format=fmt,
        workers=store.preferences.max_workers,
        fast=store.preferences.fast_mode,
        skip_existing=store.preferences.skip_existing,
    )
    return keys, opts, resume_days(open_days)


def run_crawl(
    state: dict,
    store: Optional[StateStore],
    site_keys: list[str],
    opts,
    days_by_site=None,
) -> None:
    """Run one crawl, keeping the ledger in sync for the duration.

    ``days_by_site`` marks a resume: the ledger is rebuilt around exactly those
    (site, date) entries, so completing or failing them closes them out.
    """
    if store is not None:
        store.start_run(
            site_keys,
            opts.start_date,
            opts.end_date,
            opts.output_dir,
            opts.output_format.ext(),
            days=store.open_days() if days_by_site else None,
        )

    console.rule("[bold cyan]开始下载[/bold cyan]")
    try:
        stats = run_multi(
            site_keys,
            opts,
            on_event=handle_event,
            on_day=_on_day(store),
            days_by_site=days_by_site,
        )
    except KeyboardInterrupt:
        # run_multi is synchronous, so the pool cannot be cancelled from a callback.
        # Days already finished are in the ledger; the rest stay pending.
        if store is not None:
            store.finish_run({})
        console.print(
            "\n[yellow]已中断下载。已抓取并写入的文件均已保存，"
            "未完成的日期已记入账本，下次进入本菜单会提示继续。[/yellow]"
        )
        return
    if store is not None:
        store.finish_run(stats.as_dict())
    console.print(f"[green]文件保存在：{state['output_dir']}[/green]")


def _on_day(store: Optional[StateStore]):
    """Ledger hook for the scheduler, or None when persistence is off."""
    if store is None:
        return None

    def on_day(site, day, status, path, error) -> None:
        store.record_day(site, day, status, path=path, error=error)

    return on_day


# ---------------------------------------------------------------- main flow


def main_loop(state: dict, store: Optional[StateStore] = None) -> None:
    while True:
        menu = Panel(
            "\n".join(
                [
                    "[1] 选择报纸",
                    "[2] 设置日期范围",
                    "[3] 设置输出目录",
                    "[4] 设置输出格式",
                    "[5] 高级选项",
                    "[6] 开始下载",
                    "[7] 退出",
                ]
            ),
            title="主菜单",
            border_style="cyan",
        )
        console.print()
        console.print(menu)
        try:
            choice = ask("请选择", choices=[str(i) for i in range(1, 8)], default="6")
        except _InputClosed:
            console.print("\n[dim]输入已结束，退出。[/dim]")
            break
        if choice == "1":
            choose_sites(state, store)
        elif choice == "2":
            choose_dates(state, store)
        elif choice == "3":
            choose_output_dir(state, store)
        elif choice == "4":
            choose_format(state, store)
        elif choice == "5":
            choose_advanced(state, store)
        elif choice == "6":
            start_download(state, store)
        elif choice == "7":
            console.print("[dim]再见！[/dim]")
            break


def run() -> int:
    """Enter the interactive menu. Always returns 0 (Ctrl+C and EOF are handled).

    Menu choices from the previous session are restored from the project state file
    and saved again as they change, so the menu reopens where it was left off.
    """
    configure_logging()
    try:
        store = StateStore()
    except OSError as exc:  # An unreadable state file must not block the menu.
        console.print(f"[yellow]状态文件不可用（{exc}），本次不保存设置[/yellow]")
        store = None
    try:
        print_banner()
        state = state_from_preferences(store.preferences) if store else default_state()
        main_loop(state, store)
    except KeyboardInterrupt:
        console.print("\n[yellow]已退出。[/yellow]")
    except _InputClosed:
        console.print("\n[dim]输入已结束，退出。[/dim]")
    return 0
