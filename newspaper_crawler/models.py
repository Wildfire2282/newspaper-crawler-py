"""统一数据模型（对齐 Rust 版 src-tauri/src/crawler/model.rs）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from pathlib import Path
from typing import Union


class OutputFormat(str, Enum):
    """输出格式。"""

    MD = "md"
    TXT = "txt"

    def ext(self) -> str:
        return self.value


@dataclass
class ArticleRef:
    """文章引用（仅含 URL 与标题，抓取正文前的轻量结构）。"""

    title: str = ""
    url: str = ""
    extra: dict = field(default_factory=dict)


@dataclass
class Article:
    """文章（统一抓取结果）。"""

    title: str = ""
    yinti: str = ""  # 引题 / 肩题
    subtitle: str = ""  # 副题
    author: str = ""
    paragraphs: list = field(default_factory=list)  # list[str]
    image_desc: str = ""
    url: str = ""
    extra: dict = field(default_factory=dict)


# 版面文章条目：引用（未抓取）或完整文章
ArticleOrRef = Union[ArticleRef, Article]


def art_title(item: ArticleOrRef) -> str:
    """统一取条目标题。"""
    return item.title


def is_full(item: ArticleOrRef) -> bool:
    """是否已抓取为完整文章。"""
    return isinstance(item, Article)


@dataclass
class Edition:
    """版面。"""

    num: int = 0
    name: str = ""
    articles: list = field(default_factory=list)  # list[ArticleOrRef]


@dataclass
class CrawlStats:
    """单日/站点统计。"""

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
        """转为可 JSON 序列化的字典。"""
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


@dataclass
class CrawlOptions:
    """抓取配置（对齐 Rust 版 base.rs CrawlOptions）。"""

    start_date: date
    end_date: date
    output_dir: Path
    output_format: OutputFormat = OutputFormat.MD
    max_workers: int = 5
    article_delay: tuple = (0.1, 0.3)  # (min, max) 秒
    day_delay: float = 0.5
    skip_existing: bool = True
