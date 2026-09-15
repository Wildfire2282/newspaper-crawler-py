"""Shared helpers: URL joining, title cleanup, meta extraction, weekday names, date
parsing and crawl-option construction.

Mirrors Rust src-tauri/src/crawler/util.rs and progress.rs (weekday_cn).
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

# Parser pinned to html.parser; lxml is deliberately NOT used.
# libxml2 normalizes markup against the HTML content model and relocates <p> out of
# <h2> (<h2><p>T</p></h2> becomes <h2></h2><p>T</p>). 经济日报 titles are exactly that
# non-conforming shape ("h2#Title contains <p>"), so lxml silently drops them and
# falls back to the page <title>.
# Regression guard: tests/test_util.py::test_lxml_relocates_p_out_of_heading.
PARSER = "html.parser"


def make_soup(markup: str) -> BeautifulSoup:
    """Single HTML parse entry point; the parser choice lives here."""
    return BeautifulSoup(markup, PARSER)


def join_url(base: str, href: str) -> str:
    """Join a possibly-relative href onto base (mirrors Rust util::join_url)."""
    if href.startswith(("http://", "https://")):
        return href
    return urljoin(base, href)


def clean_title(title: str) -> str:
    """Strip a trailing newspaper suffix, e.g. "标题-光明网" -> "标题"."""
    return RE_SITE_SUFFIX.sub("", title.strip()).strip()


def meta_content(soup: BeautifulSoup, name: str) -> str:
    """Return the content of <meta name=NAME>, or "" when absent or empty."""
    tag = soup.find("meta", attrs={"name": name})
    if tag is not None:
        content = tag.get("content")
        if content:
            return str(content).strip()
    return ""


def page_numbers_from_links(
    soup: BeautifulSoup, pattern: re.Pattern[str], maximum: int
) -> list[int]:
    """Collect edition numbers referenced by the page's <a href> links.

    Args:
        pattern: regex whose group(1) is the page number.
        maximum: inclusive upper bound; larger numbers are ignored.

    Returns:
        Sorted, de-duplicated page numbers within 1..maximum.

    Rationale: deriving the real edition set from navigation links avoids probing
    2..N blindly, which spends one request per edition that does not exist.
    """
    nums: set[int] = set()
    for a in soup.find_all("a", href=True):
        m = pattern.search(str(a["href"]))
        if m and m.group(1).isdigit():
            num = int(m.group(1))
            if 1 <= num <= maximum:
                nums.add(num)
    return sorted(nums)


WEEKDAY_CN_SHORT = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
WEEKDAY_CN_FULL = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]


def weekday_cn(d: date) -> str:
    """Short weekday name for logs/progress, e.g. 周一."""
    return WEEKDAY_CN_SHORT[d.weekday()]


def weekday_cn_full(d: date) -> str:
    """Full weekday name for Markdown headings, e.g. 星期一."""
    return WEEKDAY_CN_FULL[d.weekday()]


def parse_date(text: str) -> date:
    """Parse YYYYMMDD or YYYY-MM-DD.

    Raises:
        ValueError: the text matches neither format.
    """
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"无法解析日期: {text!r}")


def make_crawl_options(
    start: date,
    end: date,
    output_dir: Path,
    output_format: OutputFormat = OutputFormat.MD,
    workers: int = 5,
    fast: bool = False,
    skip_existing: bool = True,
) -> CrawlOptions:
    """Build CrawlOptions, folding "fast mode" into delays and concurrency.

    Fast mode: article delay (0.01, 0.05)s, day delay 0.1s, workers raised to >= 10.
    Normal mode: article delay (0.1, 0.3)s, day delay 0.5s, workers unchanged.
    """
    if fast:
        article_delay, day_delay, workers = (0.01, 0.05), 0.1, max(10, workers)
    else:
        article_delay, day_delay = (0.1, 0.3), 0.5
    return CrawlOptions(
        start_date=start,
        end_date=end,
        output_dir=Path(output_dir),
        output_format=output_format,
        max_workers=workers,
        article_delay=article_delay,
        day_delay=day_delay,
        skip_existing=skip_existing,
    )


def configure_logging(verbose: bool = False) -> None:
    """Route the "newspaper" logger to stderr (WARNING default, DEBUG if verbose)."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("[%(levelname)s] %(message)s"))
    logger = logging.getLogger("newspaper")
    logger.handlers = [handler]
    logger.setLevel(logging.DEBUG if verbose else logging.WARNING)
    logger.propagate = False
    # Retries happen inside urllib3; surface its logs only when verbose.
    logging.getLogger("urllib3").setLevel(logging.DEBUG if verbose else logging.WARNING)
