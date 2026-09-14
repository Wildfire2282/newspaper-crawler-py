"""报刊下载器 Python 版核心包。

重构自 https://github.com/Wildfire2282/newspaper-crawler (Tauri/Rust)，
提供多站点电子报批量下载的纯 Python 实现。
"""

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

try:  # 版本号单一来源：pyproject.toml
    __version__ = version("newspaper-crawler")
except PackageNotFoundError:  # 未安装（直接运行源码）时回退
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
