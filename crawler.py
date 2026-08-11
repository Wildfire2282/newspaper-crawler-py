#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""报刊下载器 · 交互式命令行版

重构自 Wildfire2282/newspaper-crawler（Tauri/Rust 桌面版），
支持人民日报 / 光明日报 / 经济日报 / 大众日报 电子报按日期批量下载。

用法：
    python crawler.py             # 进入交互式菜单
    python crawler.py --help      # 查看帮助
    python crawler.py --version   # 显示版本
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

# 确保可直接以 `python crawler.py` 运行（脚本所在目录加入模块搜索路径）
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

try:
    from newspaper_crawler import __version__ as VERSION
except Exception:  # 极端情况下回退
    VERSION = "3.1.0"

console = Console()


class _InputClosed(Exception):
    """stdin 关闭（Ctrl+D / 管道结束）时抛出，用于优雅退出。"""


def ask(prompt: str, **kwargs):
    """安全的 Prompt.ask：EOF 时抛 _InputClosed。"""
    try:
        return Prompt.ask(prompt, **kwargs)
    except EOFError:
        raise _InputClosed


def confirm(prompt: str, **kwargs):
    """安全的 Confirm.ask：EOF 时抛 _InputClosed。"""
    try:
        return Confirm.ask(prompt, **kwargs)
    except EOFError:
        raise _InputClosed


# ---------------------------------------------------------------- 参数解析

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="crawler",
        description="报刊下载器：交互式批量下载人民日报/光明日报/经济日报/大众日报电子版",
    )
    parser.add_argument(
        "--version", action="store_true", help="显示版本号后退出"
    )
    return parser


# ---------------------------------------------------------------- 通用工具

def parse_date(text: str) -> date:
    """解析日期，支持 YYYYMMDD 与 YYYY-MM-DD 两种格式。"""
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {text!r}")


def _all_site_keys() -> list:
    """从注册表取全部站点 id（惰性导入，避免启动时依赖站点模块）。"""
    from newspaper_crawler.registry import all_sites

    return [s.crawler_id for s in all_sites()]


def _parse_site_selection(answer: str, count: int) -> list:
    """解析站点多选输入：'all' 全选；逗号/空格分隔编号。"""
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


# ---------------------------------------------------------------- 交互函数

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
    """初始配置：最近 7 天、全站点、默认输出 ./downloads。"""
    today = date.today()
    return {
        "site_keys": [],              # 空 = 全选（进入选择菜单时填充）
        "start_date": today - timedelta(days=6),
        "end_date": today,
        "output_dir": _SCRIPT_DIR / "downloads",
        "output_format": "md",        # md | txt
        "max_workers": 5,
        "fast_mode": False,
        "skip_existing": True,
    }


def choose_sites(state: dict) -> None:
    """菜单 1：选择报纸（多选，默认全选）。"""
    from newspaper_crawler.registry import all_sites

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
        table.add_row(str(i), site.crawler_id, site.name, " / ".join(site.aliases))
    console.print(table)

    current_idx = [i for i, s in enumerate(sites, 1) if s.crawler_id in state["site_keys"]]
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


def choose_dates(state: dict) -> None:
    """菜单 2：设置日期范围。"""
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
        console.print("[yellow]提示：结束日期晚于今天，今天可能还没有当日电子报[/yellow]")
    console.print(f"[green]日期范围：{start} ~ {end}[/green]")


def choose_output_dir(state: dict) -> None:
    """菜单 3：设置输出目录。"""
    answer = ask(
        "输出目录（支持 ~；留空保持当前）",
        default=str(state["output_dir"]),
    ).strip()
    if answer:
        path = Path(os.path.expanduser(answer))
        if not path.is_absolute():
            path = _SCRIPT_DIR / path
        state["output_dir"] = path
    console.print(f"[green]输出目录：{state['output_dir']}[/green]")


def choose_format(state: dict) -> None:
    """菜单 4：输出格式。"""
    fmt = ask(
        "输出格式", choices=["md", "txt"], default=state["output_format"]
    )
    state["output_format"] = fmt
    console.print(f"[green]输出格式：{fmt}[/green]")


def choose_advanced(state: dict) -> None:
    """菜单 5：高级选项（并发/快速模式/断点续传）。"""
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


# ---------------------------------------------------------------- 事件处理

def handle_event(ev) -> None:
    """处理调度器进度事件，输出一行彩色日志。"""
    kind = ev.kind
    site = ev.site
    if kind == "site_start":
        console.print(f"[cyan][{site}] 任务开始[/cyan]")
    elif kind == "day_start":
        console.print(f"[cyan][{site}] {ev.date}({ev.weekday}) 开始[/cyan]")
    elif kind == "day_skip":
        console.print(f"[yellow][{site}] {ev.date}({ev.weekday}) 跳过（文件已存在）[/yellow]")
    elif kind == "day_empty":
        console.print(f"[yellow][{site}] {ev.date}({ev.weekday}) 无报纸[/yellow]")
    elif kind == "day_error":
        console.print(f"[red][{site}] {ev.date} 错误：{ev.message}[/red]")
    elif kind == "day_done":
        extra = f" · {ev.errors} 错误" if ev.errors > 0 else ""
        console.print(
            f"[green][{site}] {ev.date}({ev.weekday}) 完成 {ev.editions} 版 "
            f"{ev.articles} 篇{extra}[/green]"
        )
    elif kind == "site_done":
        console.print(f"[cyan][{site}] 任务结束[/cyan]")
    elif kind == "log":
        color = {"warn": "yellow", "error": "red"}.get(ev.level, "cyan")
        console.print(f"[{color}][{site}] {ev.message}[/{color}]")
    elif kind == "finished":
        console.print(
            f"[bold green]全部完成 · 耗时 {ev.elapsed_secs:.1f}s · {ev.stats}[/bold green]"
        )


# ---------------------------------------------------------------- 下载流程

def start_download(state: dict) -> None:
    """菜单 6：按当前配置开始批量下载。"""
    from newspaper_crawler.models import CrawlOptions, OutputFormat
    from newspaper_crawler.registry import lookup
    from newspaper_crawler.scheduler import run_multi

    site_keys = state["site_keys"] or _all_site_keys()
    if not site_keys:
        console.print("[red]请先选择报纸（菜单 1）[/red]")
        return

    site_names = []
    for key in site_keys:
        site = lookup(key)
        site_names.append(site.name if site else key)

    fmt = OutputFormat.TXT if state["output_format"] == "txt" else OutputFormat.MD
    if state["fast_mode"]:
        article_delay, day_delay, workers = (0.01, 0.05), 0.1, max(10, state["max_workers"])
    else:
        article_delay, day_delay, workers = (0.1, 0.3), 0.5, state["max_workers"]

    opts = CrawlOptions(
        start_date=state["start_date"],
        end_date=state["end_date"],
        output_dir=state["output_dir"],
        output_format=fmt,
        max_workers=workers,
        article_delay=article_delay,
        day_delay=day_delay,
        skip_existing=state["skip_existing"],
    )

    summary = (
        f"报纸：{'、'.join(site_names)}\n"
        f"日期：{state['start_date']} ~ {state['end_date']}\n"
        f"输出目录：{state['output_dir']}\n"
        f"格式：{state['output_format']} · 并发：{workers} · "
        f"快速模式：{'开' if state['fast_mode'] else '关'} · "
        f"断点续传：{'开' if state['skip_existing'] else '关'}"
    )
    console.print(Panel(summary, title="下载配置", border_style="green"))
    if not confirm("确认开始下载？", default=True):
        return

    console.rule("[bold cyan]开始下载[/bold cyan]")
    try:
        run_multi(site_keys, opts, on_event=handle_event)
    except KeyboardInterrupt:
        # run_multi 为同步调用，无法在回调中取消线程池；
        # 已按日原子写入的文件全部保留，剩余日期可下次续传。
        console.print(
            "\n[yellow]已中断下载。已抓取并写入的文件均已保存，"
            "未完成的日期可在下次运行（开启断点续传）时继续。[/yellow]"
        )
        return
    console.print(f"[green]文件保存在：{state['output_dir']}[/green]")


# ---------------------------------------------------------------- 主流程

def main_loop(state: dict) -> None:
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
            choice = ask(
                "请选择", choices=[str(i) for i in range(1, 8)], default="6"
            )
        except _InputClosed:
            console.print("\n[dim]输入已结束，退出。[/dim]")
            break
        if choice == "1":
            choose_sites(state)
        elif choice == "2":
            choose_dates(state)
        elif choice == "3":
            choose_output_dir(state)
        elif choice == "4":
            choose_format(state)
        elif choice == "5":
            choose_advanced(state)
        elif choice == "6":
            start_download(state)
        elif choice == "7":
            console.print("[dim]再见！[/dim]")
            break


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if args.version:
        console.print(f"报刊下载器 v{VERSION}")
        return 0
    try:
        print_banner()
        main_loop(default_state())
    except KeyboardInterrupt:
        console.print("\n[yellow]已退出。[/yellow]")
    except _InputClosed:
        console.print("\n[dim]输入已结束，退出。[/dim]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
