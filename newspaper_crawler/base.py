"""Site crawler ABC and concurrent fetch helpers.

Mirrors the Rust implementation (src-tauri/src/crawler/base.rs: SiteCrawler trait
and BaseCrawler).
"""

from __future__ import annotations

import logging
import random
import time
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

from .http import HttpSession
from .models import Article, ArticleRef, Edition

log = logging.getLogger("newspaper")


class EmptyIndexError(Exception):
    """Index page was retrieved but yielded zero editions.

    Contract: raised only when the index page WAS fetched and its structure could
    not be parsed. Signals an upstream site redesign, as opposed to a genuine
    no-paper day (empty list, index unreachable). Without this distinction a
    redesign would be silently reported as "no paper".
    """


def fetch_texts(
    http: HttpSession,
    urls: list[str],
    silent_404: bool,
    max_workers: int = 8,
    cache: Optional[dict[str, str]] = None,
) -> list[Optional[str]]:
    """Fetch pages concurrently and return results positionally aligned with urls.

    Args:
        cache: optional url -> body map. URLs already present are not requested;
            successful fetches are written back. Lets callers avoid re-requesting a
            page already retrieved for an earlier purpose (e.g. layout page 1 read
            first for navigation parsing, then again as an edition page).

    Returns:
        One entry per url, same order; failed fetches map to None. Duplicate urls
        within ``urls`` are requested at most once.
    """
    if not urls:
        return []
    if cache is None:
        cache = {}
    pending = list(dict.fromkeys(u for u in urls if u not in cache))
    if pending:
        with ThreadPoolExecutor(max_workers=min(max_workers, len(pending))) as pool:
            fetched = pool.map(
                lambda u: http.get_text(u, silent_404=silent_404), pending
            )
            for url, body in zip(pending, fetched):
                if body is not None:
                    cache[url] = body
    return [cache.get(u) for u in urls]


class SiteCrawler(ABC):
    """Per-site crawler interface. Subclasses implement get_editions/fetch_article."""

    crawler_id: str = ""
    name: str = ""
    base_url: str = ""
    aliases: Optional[list[str]] = None

    @abstractmethod
    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        """Return the editions published on ``d``.

        Returns:
            Editions in ascending page order. Empty list when no paper was published
            on ``d`` or the index page could not be reached.

        Raises:
            EmptyIndexError: index page retrieved but its structure was not
                recognized, so the scheduler can distinguish "no paper" from a
                broken parser instead of reporting both as "no paper".
        """

    @abstractmethod
    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        """Return the full article body, or None if the fetch/parse failed."""

    def day_filepath(self, d: date, output_dir: Path, ext: str) -> Path:
        """Path of one day's output: <output_dir>/<name>/<year>/<MM>/<date>.<ext>."""
        return (
            Path(output_dir)
            / self.name
            / str(d.year)
            / f"{d.month:02d}"
            / f"{d.isoformat()}.{ext}"
        )


class BaseCrawler:
    """Populate Edition articles with full bodies, serially or concurrently."""

    @staticmethod
    def crawl_day(
        site: SiteCrawler,
        http: HttpSession,
        d: date,
        max_workers: int = 5,
        article_delay: tuple[float, float] = (0.1, 0.3),
    ) -> tuple[list[Edition], int]:
        """Fetch every article body for one day.

        Returns:
            (editions, errors). Each ArticleRef is replaced in place by an Article
            when its fetch succeeded; ``errors`` counts fetches that returned None or
            raised.

        Note:
            Concurrent mode (max_workers > 1) applies no inter-request delay, matching
            the Rust implementation: per-host request rate is bounded by
            ``max_workers`` alone. ``article_delay`` is honored only in serial mode.
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

        errors = 0

        def work(ed_idx: int, art_idx: int, aref: ArticleRef):
            try:
                return ed_idx, art_idx, site.fetch_article(http, aref, d)
            except Exception as exc:  # One failing article must not abort the day.
                log.warning("抓取文章出错 [%s]: %s", aref.title, exc)
                return ed_idx, art_idx, None

        def apply(result) -> None:
            nonlocal errors
            ed_idx, art_idx, article = result
            if article is not None:
                editions[ed_idx].articles[art_idx] = article
            else:
                errors += 1

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


def _sleep_article(delay: tuple[float, float]) -> None:
    """Sleep for a uniform random value in ``delay``; serial mode only."""
    lo, hi = delay
    if hi > 0:
        time.sleep(random.uniform(lo, hi))
