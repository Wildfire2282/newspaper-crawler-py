"""公共工具：URL 拼接、文本清理、HTML 元信息提取、星期中文名。

对齐 Rust 版 src-tauri/src/crawler/util.rs 与 progress.rs 的 weekday_cn。
"""

from __future__ import annotations

import re
from datetime import date
from urllib.parse import urljoin

from bs4 import BeautifulSoup

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
