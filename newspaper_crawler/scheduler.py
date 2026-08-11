"""调度器：逐日爬取、跳过已有、原子写入、多站点编排。

对齐 Rust 版 src-tauri/src/crawler/scheduler.rs 与 commands/crawl.rs 的消息格式。
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Callable, Optional

from .base import BaseCrawler, SiteCrawler
from .formatter import Formatter
from .http import HttpSession
from .models import CrawlOptions, CrawlStats, Edition, is_full
from .registry import lookup
from .storage import atomic_write
from .util import weekday_cn

log = logging.getLogger("newspaper")


@dataclass
class ProgressEvent:
    """进度事件（kind 见字段注释）。UI 模块依赖此结构。"""

    kind: str  # site_start|site_done|day_start|day_skip|day_empty|day_error|day_done|log|finished
    site: str = ""
    date: Optional[date] = None
    weekday: str = ""
    editions: int = 0
    articles: int = 0
    errors: int = 0
    level: str = "info"  # log 事件用
    message: str = ""
    stats: Optional[CrawlStats] = None  # site_done/finished 用
    elapsed_secs: float = 0.0  # finished 用


EventFn = Callable[[ProgressEvent], None]


def count_full_articles(editions: list[Edition]) -> int:
    """统计已抓取为完整文章的篇数。"""
    return sum(1 for ed in editions for item in ed.articles if is_full(item))


def run_site(site: SiteCrawler, opts: CrawlOptions, on_event: EventFn) -> CrawlStats:
    """爬取单个站点在日期范围内的全部日报，返回统计。

    逐日循环（含起止日期）；已有文件且 skip_existing 时跳过；
    当日有版面则格式化并原子写入，统计并发出 day_done 事件。
    """
    stats = CrawlStats()
    site_name = site.name
    formatter = Formatter(site.name, site.base_url)
    http = HttpSession(fast_mode=getattr(opts, "fast_mode", False))

    on_event(ProgressEvent(kind="site_start", site=site_name, message=f"[{site_name}] 任务开始"))

    try:
        current = opts.start_date
        last = opts.end_date
        while current <= last:
            weekday = weekday_cn(current)
            filepath = site.day_filepath(
                current, opts.output_dir, opts.output_format.ext()
            )

            if opts.skip_existing and filepath.exists():
                stats.days_skipped += 1
                on_event(
                    ProgressEvent(
                        kind="day_skip",
                        site=site_name,
                        date=current,
                        weekday=weekday,
                        message=f"[{site_name}] {current}({weekday}) 跳过",
                    )
                )
                current += timedelta(days=1)
                if current <= last and opts.day_delay > 0:
                    time.sleep(opts.day_delay)
                continue

            on_event(
                ProgressEvent(
                    kind="day_start",
                    site=site_name,
                    date=current,
                    weekday=weekday,
                    message=f"[{site_name}] {current}({weekday}) 开始",
                )
            )

            try:
                editions, err_count = BaseCrawler.crawl_day(
                    site,
                    http,
                    current,
                    max_workers=opts.max_workers,
                    article_delay=opts.article_delay,
                )
            except Exception as exc:  # 版面获取失败等整体异常
                log.error("抓取 %s %s 失败: %s", site_name, current, exc)
                stats.days_attempted += 1
                stats.total_errors += 1
                on_event(
                    ProgressEvent(
                        kind="day_error",
                        site=site_name,
                        date=current,
                        message=f"[{site_name}] {current} 错误: {exc}",
                    )
                )
                current += timedelta(days=1)
                if current <= last and opts.day_delay > 0:
                    time.sleep(opts.day_delay)
                continue

            if editions:
                total_articles = count_full_articles(editions)
                total_editions = len(editions)
                if opts.output_format.ext() == "txt":
                    content = formatter.plain(current, editions)
                else:
                    content = formatter.markdown(current, editions)
                try:
                    atomic_write(filepath, content)
                except OSError as exc:
                    log.error("写入文件失败 [%s]: %s", filepath, exc)
                    on_event(
                        ProgressEvent(
                            kind="log",
                            level="error",
                            site=site_name,
                            message=f"[{site_name}] error 写入失败: {exc}",
                        )
                    )
                stats.days_attempted += 1
                stats.days_success += 1
                stats.total_editions += total_editions
                stats.total_articles += total_articles
                stats.total_errors += err_count
                extra = f" · {err_count} 错误" if err_count > 0 else ""
                on_event(
                    ProgressEvent(
                        kind="day_done",
                        site=site_name,
                        date=current,
                        weekday=weekday,
                        editions=total_editions,
                        articles=total_articles,
                        errors=err_count,
                        message=(
                            f"[{site_name}] {current}({weekday}) 完成 "
                            f"{total_editions} 版 {total_articles} 篇{extra}"
                        ),
                    )
                )
            else:
                stats.days_attempted += 1
                stats.days_empty += 1
                on_event(
                    ProgressEvent(
                        kind="day_empty",
                        site=site_name,
                        date=current,
                        weekday=weekday,
                        message=f"[{site_name}] {current}({weekday}) 无报纸",
                    )
                )

            current += timedelta(days=1)
            if current <= last and opts.day_delay > 0:
                time.sleep(opts.day_delay)
    finally:
        http.close()

    on_event(
        ProgressEvent(
            kind="site_done",
            site=site_name,
            stats=stats,
            message=f"[{site_name}] 任务结束",
        )
    )
    return stats


def run_multi(
    site_keys: list[str], opts: CrawlOptions, on_event: EventFn
) -> CrawlStats:
    """按站点 key 依次爬取多个站点（串行），合并统计，最后发 finished 事件。"""
    started = time.monotonic()
    merged = CrawlStats()

    for key in site_keys:
        site = lookup(key)
        if site is None:
            on_event(
                ProgressEvent(
                    kind="log",
                    level="warn",
                    site=key,
                    message=f"[{key}] warn 未找到站点: {key}，已跳过",
                )
            )
            continue
        try:
            stats = run_site(site, opts, on_event)
            merged.merge(stats)
        except Exception as exc:  # 单个站点整体异常不中断其他站点
            log.error("站点 %s 运行失败: %s", site.name, exc)
            on_event(
                ProgressEvent(
                    kind="log",
                    level="error",
                    site=site.name,
                    message=f"[{site.name}] error 运行失败: {exc}",
                )
            )

    elapsed = time.monotonic() - started
    on_event(
        ProgressEvent(
            kind="finished",
            stats=merged,
            elapsed_secs=elapsed,
            message=(
                f"全部完成 · 耗时 {elapsed:.1f}s · 文章 {merged.total_articles} · "
                f"错误 {merged.total_errors}"
            ),
        )
    )
    return merged
