"""Scheduler: per-day crawl loop, skip-existing, atomic writes, multi-site fan-out.

Mirrors the message formats of Rust src-tauri/src/crawler/scheduler.rs and
commands/crawl.rs.
"""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, Optional

from .base import BaseCrawler, EmptyIndexError, SiteCrawler
from .formatter import Formatter, count_full
from .http import HttpSession
from .models import CrawlOptions, CrawlStats
from .registry import lookup
from .storage import atomic_write
from .util import weekday_cn

log = logging.getLogger("newspaper")


@dataclass(slots=True)
class ProgressEvent:
    """Structured progress event; UI layers render ``message`` and read the fields.

    Contract: ``kind`` is the discriminator; which fields carry data depends on it
    (see the per-field comments). ``message`` is always a complete, display-ready
    line, so renderers must not prefix ``site`` again.
    """

    kind: str  # site_start|site_done|day_start|day_skip|day_empty|day_error|day_done|log|finished
    site: str = ""
    date: Optional[date] = None
    weekday: str = ""
    editions: int = 0
    articles: int = 0
    errors: int = 0
    level: str = "info"  # severity, only meaningful for kind == "log"
    message: str = ""
    path: Optional[Path] = None  # target file, set by day_skip/day_done
    stats: Optional[CrawlStats] = None  # set by site_done/finished
    elapsed_secs: float = 0.0  # set by finished


EventFn = Callable[[ProgressEvent], None]


def run_site(site: SiteCrawler, opts: CrawlOptions, on_event: EventFn) -> CrawlStats:
    """Crawl every day in opts' range for one site.

    Returns:
        Counters for this site. Per-day failures (edition fetch error or write error)
        are recorded as day_error and never abort the remaining days.

    Side effects: writes one output file per day with editions, and closes the
    HttpSession it owns. Emits site_start/day_*/site_done events.
    """
    stats = CrawlStats()
    site_name = site.name
    formatter = Formatter(site.name, site.base_url)
    http = HttpSession()

    def emit(kind: str, **fields) -> None:
        on_event(ProgressEvent(kind=kind, site=site_name, **fields))

    def crawl_one_day(current: date) -> None:
        weekday = weekday_cn(current)
        filepath = site.day_filepath(current, opts.output_dir, opts.output_format.ext())

        if opts.skip_existing and filepath.exists():
            stats.days_skipped += 1
            emit(
                "day_skip",
                date=current,
                weekday=weekday,
                path=filepath,
                message=f"[{site_name}] {current}({weekday}) 跳过（文件已存在）",
            )
            return

        emit(
            "day_start",
            date=current,
            weekday=weekday,
            message=f"[{site_name}] {current}({weekday}) 开始",
        )

        try:
            editions, err_count = BaseCrawler.crawl_day(
                site,
                http,
                current,
                max_workers=opts.max_workers,
                article_delay=opts.article_delay,
            )
        except EmptyIndexError as exc:
            # Index page present but unrecognizable -> likely a site redesign.
            # Count as an empty day, but warn: silence here would hide the breakage.
            stats.days_attempted += 1
            stats.days_empty += 1
            emit(
                "log",
                level="warn",
                date=current,
                message=(
                    f"[{site_name}] {current}({weekday}) 无报纸"
                    f"（索引页结构疑似已变化：{exc}）"
                ),
            )
            return
        except Exception as exc:  # Edition-fetch failure; other days continue.
            log.error("抓取 %s %s 失败: %s", site_name, current, exc)
            stats.days_attempted += 1
            stats.total_errors += 1
            emit(
                "day_error",
                date=current,
                message=f"[{site_name}] {current} 抓取失败: {exc}",
            )
            return

        if not editions:
            stats.days_attempted += 1
            stats.days_empty += 1
            emit(
                "day_empty",
                date=current,
                weekday=weekday,
                message=f"[{site_name}] {current}({weekday}) 无报纸",
            )
            return

        total_editions = len(editions)
        total_articles = count_full(editions)
        if opts.output_format.ext() == "txt":
            content = formatter.plain(current, editions)
        else:
            content = formatter.markdown(current, editions)

        try:
            atomic_write(filepath, content)
        except OSError as exc:
            log.error("写入文件失败 [%s]: %s", filepath, exc)
            stats.days_attempted += 1
            stats.total_errors += 1
            emit(
                "day_error",
                date=current,
                message=f"[{site_name}] {current} 写入失败: {exc}",
            )
            return

        stats.days_attempted += 1
        stats.days_success += 1
        stats.total_editions += total_editions
        stats.total_articles += total_articles
        stats.total_errors += err_count
        extra = f" · {err_count} 错误" if err_count > 0 else ""
        emit(
            "day_done",
            date=current,
            weekday=weekday,
            editions=total_editions,
            articles=total_articles,
            errors=err_count,
            path=filepath,
            message=(
                f"[{site_name}] {current}({weekday}) 完成 "
                f"{total_editions} 版 {total_articles} 篇{extra}"
            ),
        )

    emit("site_start", message=f"[{site_name}] 任务开始")
    try:
        current = opts.start_date
        while current <= opts.end_date:
            crawl_one_day(current)
            current += timedelta(days=1)
            if current <= opts.end_date and opts.day_delay > 0:
                time.sleep(opts.day_delay)
    finally:
        http.close()

    emit("site_done", stats=stats, message=f"[{site_name}] 任务结束")
    return stats


def run_multi(
    site_keys: list[str],
    opts: CrawlOptions,
    on_event: EventFn,
    max_site_workers: int = 4,
) -> CrawlStats:
    """Crawl several sites concurrently and merge their counters.

    Sites map to distinct hosts, so running them in parallel does not raise the
    request rate seen by any single host: each site keeps its own serial day loop and
    bounded article concurrency (opts.max_workers).

    Args:
        max_site_workers: upper bound on concurrently running sites, clamped to
            ``len(site_keys)``.

    Note:
        ``on_event`` is invoked under a lock, so handlers may assume they are never
        called concurrently and need no synchronization of their own. A site that
        fails outright does not abort the others.
    """
    started = time.monotonic()
    merged = CrawlStats()
    lock = threading.Lock()

    def emit(event: ProgressEvent) -> None:
        with lock:
            on_event(event)

    def crawl_one(key: str) -> Optional[CrawlStats]:
        site = lookup(key)
        if site is None:
            emit(
                ProgressEvent(
                    kind="log",
                    level="warn",
                    site=key,
                    message=f"[{key}] warn 未找到站点: {key}，已跳过",
                )
            )
            return None
        try:
            return run_site(site, opts, emit)
        except Exception as exc:  # One failing site must not abort the others.
            log.error("站点 %s 运行失败: %s", site.name, exc)
            emit(
                ProgressEvent(
                    kind="log",
                    level="error",
                    site=site.name,
                    message=f"[{site.name}] error 运行失败: {exc}",
                )
            )
            return None

    if site_keys:
        workers = max(1, min(max_site_workers, len(site_keys)))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            for stats in pool.map(crawl_one, site_keys):
                if stats is not None:
                    merged.merge(stats)

    elapsed = time.monotonic() - started
    emit(
        ProgressEvent(
            kind="finished",
            stats=merged,
            elapsed_secs=elapsed,
            message=f"全部完成 · 耗时 {elapsed:.1f}s · {merged}",
        )
    )
    return merged
