"""站点爬虫抽象基类与并发抓取工具。

对齐 Rust 版 src-tauri/src/crawler/base.rs 的 SiteCrawler trait 与 BaseCrawler。
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Callable, Optional

from .http import HttpSession
from .models import Article, ArticleRef, Edition

log = logging.getLogger("newspaper")

ProgressFn = Callable[[int, int], None]  # (done, total)


class SiteCrawler(ABC):
    """站点爬虫接口。子类实现 get_editions / fetch_article。"""

    crawler_id: str = ""
    name: str = ""
    base_url: str = ""
    aliases: Optional[list] = None

    @abstractmethod
    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        """获取指定日期的版面列表；无报纸/访问失败返回空列表。"""

    @abstractmethod
    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        """抓取单篇文章正文；失败返回 None。"""

    def day_filepath(self, d: date, output_dir: Path, ext: str) -> Path:
        """当日文件路径：<输出目录>/<站名>/<年>/<月>/<YYYY-MM-DD>.<ext>"""
        return (
            Path(output_dir)
            / self.name
            / str(d.year)
            / f"{d.month:02d}"
            / f"{d.isoformat()}.{ext}"
        )


class BaseCrawler:
    """给 Edition 列表填充正文（串行/并发）。"""

    @staticmethod
    def crawl_day(
        site: SiteCrawler,
        http: HttpSession,
        d: date,
        max_workers: int = 5,
        article_delay: tuple = (0.1, 0.3),
        on_progress: Optional[ProgressFn] = None,
    ) -> tuple[list[Edition], int]:
        """抓取一天内所有文章正文，返回 (editions, errors)。

        editions 中引用条目原地替换为完整文章；抓取失败/返回 None 计入 errors。
        并发模式（max_workers>1）不做请求间延迟，与 Rust 版行为一致。
        """
        editions = site.get_editions(http, d)
        if not editions:
            return editions, 0

        tasks: list[tuple[int, int, ArticleRef]] = []
        for eidx, ed in enumerate(editions):
            for aidx, item in enumerate(ed.articles):
                if isinstance(item, ArticleRef):
                    tasks.append((eidx, aidx, item))
        if not tasks:
            return editions, 0

        total = len(tasks)
        done = 0
        errors = 0

        def work(ed_idx: int, art_idx: int, aref: ArticleRef):
            try:
                return ed_idx, art_idx, site.fetch_article(http, aref, d)
            except Exception as exc:  # 单篇文章异常不中断整日
                log.warning("抓取文章出错 [%s]: %s", aref.title, exc)
                return ed_idx, art_idx, None

        def apply(result) -> None:
            nonlocal errors, done
            ed_idx, art_idx, article = result
            if article is not None:
                editions[ed_idx].articles[art_idx] = article
            else:
                errors += 1
            done += 1
            if on_progress is not None:
                on_progress(done, total)

        if max_workers <= 1:
            for task in tasks:
                apply(work(*task))
                _sleep_article(article_delay)
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futures = [pool.submit(work, *t) for t in tasks]
                for fut in as_completed(futures):
                    apply(fut.result())

        return editions, errors


def _sleep_article(delay: tuple) -> None:
    """文章间随机延迟（仅串行模式使用，与 Rust 版一致）。"""
    lo, hi = delay
    if hi > 0:
        time.sleep(random.uniform(lo, hi))
