"""Core package of the newspaper downloader."""

from importlib.metadata import PackageNotFoundError, version

from .base import BaseCrawler, SiteCrawler
from .http import HttpSession
from .models import (
    Article,
    ArticleRef,
    CrawlOptions,
    CrawlStats,
    Edition,
    OutputFormat,
)

try:  # Single source of truth for the version: pyproject.toml.
    __version__ = version("newspaper-crawler")
except PackageNotFoundError:  # Running from source without an installed dist.
    __version__ = "3.2.0"

__all__ = [
    "Article",
    "ArticleRef",
    "BaseCrawler",
    "CrawlOptions",
    "CrawlStats",
    "Edition",
    "HttpSession",
    "OutputFormat",
    "SiteCrawler",
]
