"""公共工具：URL 拼接、文本清理、HTML 元信息提取、星期中文名、日期解析、运行配置。

对齐 Rust 版 src-tauri/src/crawler/util.rs 与 progress.rs 的 weekday_cn。
"""

from __future__ import annotations

import logging
import re
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from .models import CrawlOptions, OutputFormat

RE_SITE_SUFFIX = re.compile(
    r"[-—]\s*?(光明日报|光明网|经济日报|大众日报|人民日报|人民网).*$"
)


def join_url(base: str, href: str) -> str:
    """拼接 URL（与 Rust 版 util::join_url 语义一致）。"""
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def clean_title(title: str) -> str:
    """去除标题中的报纸后缀，如 “某某某-光明网”。"""
    return RE_SITE_SUFFIX.sub("", title.strip()).strip()


def meta_content(soup: BeautifulSoup, name: str) -> str:
    """提取 <meta name=xxx content=...> 的 content 值。"""
    tag = soup.find("meta", attrs={"name": name})
    if tag is not None:
        content = tag.get("content")
        if content:
            return str(content).strip()
    return ""


WEEKDAY_CN_SHORT = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_CN_FULL = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def weekday_cn(d: date) -> str:
    """短格式星期（日志/进度用）：周一..周日。"""
    return WEEKDAY_CN_SHORT[d.weekday()]


def weekday_cn_full(d: date) -> str:
    """完整格式星期（Markdown 标题用）：星期一..星期日。"""
    return WEEKDAY_CN_FULL[d.weekday()]


def parse_date(text: str) -> date:
    """解析日期，支持 YYYYMMDD 与 YYYY-MM-DD 两种格式。"""
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {text!r}")


def project_root() -> Path:
    """项目根目录（源码运行时即 crawler.py 所在目录）。"""
    return Path(__file__).resolve().parent.parent


def make_crawl_options(
    start: date,
    end: date,
    output_dir: Path,
    output_format: OutputFormat = OutputFormat.MD,
    workers: int = 5,
    fast: bool = False,
    skip_existing: bool = True,
) -> tuple[CrawlOptions, int]:
    """构建 CrawlOptions，并把「快速模式」折算进延迟与并发，返回 (opts, 实际并发数)。"""
    if fast:
        article_delay, day_delay, workers = (0.01, 0.05), 0.1, max(10, workers)
    else:
        article_delay, day_delay = (0.1, 0.3), 0.5
    opts = CrawlOptions(
        start_date=start,
        end_date=end,
        output_dir=Path(output_dir),
        output_format=output_format,
        max_workers=workers,
        article_delay=article_delay,
        day_delay=day_delay,
        skip_existing=skip_existing,
    )
    return opts, workers


def configure_logging(verbose: bool = False) -> None:
    """把 "newspaper" logger 的输出统一到 stderr（默认 WARNING，verbose 时 DEBUG）。"""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger = logging.getLogger("newspaper")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.propagate = False
