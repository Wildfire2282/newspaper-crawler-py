"""Unified data models (mirrors Rust src-tauri/src/crawler/model.rs)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Any, TypeGuard, Union


class OutputFormat(str, Enum):
    """Output file format."""

    MD = "md"
    TXT = "txt"

    def ext(self) -> str:
        return self.value


@dataclass(slots=True)
class ArticleRef:
    """Lightweight article reference: title and URL only, before the body is fetched."""

    title: str = ""
    url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class Article:
    """Article body: the unified fetch result."""

    title: str = ""
    yinti: str = ""  # kicker: lead-in line above the main headline
    subtitle: str = ""  # subhead
    author: str = ""
    paragraphs: list[str] = field(default_factory=list)
    image_desc: str = ""
    url: str = ""
    extra: dict[str, Any] = field(default_factory=dict)


# Edition entry: either an unfetched reference or a fully fetched article.
ArticleOrRef = Union[ArticleRef, Article]


def art_title(item: ArticleOrRef) -> str:
    """Return the entry title; both union members expose ``title``."""
    return item.title


def is_full(item: ArticleOrRef) -> TypeGuard[Article]:
    """True if the entry holds a fetched Article; narrows the type for callers."""
    return isinstance(item, Article)


@dataclass(slots=True)
class Edition:
    """One newspaper edition (a single page)."""

    num: int = 0
    name: str = ""
    articles: list[ArticleOrRef] = field(default_factory=list)


@dataclass(slots=True)
class CrawlStats:
    """Counters for one run, merged across sites and days."""

    days_attempted: int = 0
    days_success: int = 0
    days_skipped: int = 0
    days_empty: int = 0
    total_editions: int = 0
    total_articles: int = 0
    total_errors: int = 0

    def merge(self, other: "CrawlStats") -> None:
        self.days_attempted += other.days_attempted
        self.days_success += other.days_success
        self.days_skipped += other.days_skipped
        self.days_empty += other.days_empty
        self.total_editions += other.total_editions
        self.total_articles += other.total_articles
        self.total_errors += other.total_errors

    def as_dict(self) -> dict:
        """Return a JSON-serializable snapshot of the counters."""
        return {
            "days_attempted": self.days_attempted,
            "days_success": self.days_success,
            "days_skipped": self.days_skipped,
            "days_empty": self.days_empty,
            "total_editions": self.total_editions,
            "total_articles": self.total_articles,
            "total_errors": self.total_errors,
        }

    def __str__(self) -> str:
        return (
            f"尝试 {self.days_attempted} 天 · 成功 {self.days_success} · "
            f"跳过 {self.days_skipped} · 无报 {self.days_empty} · "
            f"共 {self.total_editions} 版 {self.total_articles} 篇 · "
            f"错误 {self.total_errors}"
        )


@dataclass(slots=True)
class CrawlOptions:
    """Crawl configuration (mirrors Rust base.rs CrawlOptions)."""

    start_date: date
    end_date: date
    output_dir: Path
    output_format: OutputFormat = OutputFormat.MD
    max_workers: int = 5
    article_delay: tuple[float, float] = (0.1, 0.3)  # (min, max) seconds
    day_delay: float = 0.5
    skip_existing: bool = True
