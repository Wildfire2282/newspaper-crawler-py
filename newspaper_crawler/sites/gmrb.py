"""光明日报爬虫。

网址: https://epaper.gmw.cn/gmrb

2026 年 1 月 1 日起新版系统（/gmrb/html/layout/YYYYMM/DD/node_NN.html）
2025 年及以前旧版系统（/gmrb/html/YYYY-MM/DD/nbs.D110000gmrb_NN.htm）

逐条对齐 Rust 版 src-tauri/src/crawler/gmrb.rs。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup, Tag

from ..base import SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import clean_title, join_url, meta_content

BASE_URL = "https://epaper.gmw.cn"
SWITCH_DATE = date(2026, 1, 1)

# 旧版 <title> 中的版名，如 "第01版:要闻_光明日报"
RE_OLD_EDITION_NAME = re.compile(r"第\d+版[:：](.+?)(?:_|$)")
# 旧版文章链接特征
NW_HREF = "nw.D110000gmrb"

# 版面页范围 1..20（Rust 版遍历 2..21 作为 2..=20）
MAX_PAGES = 20


def _detect(d: date) -> str:
    """2026-01-01 起为新版系统。"""
    return "new" if d >= SWITCH_DATE else "old"


def _new_layout_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/gmrb/html/layout/{d.year:04d}{d.month:02d}/{d.day:02d}"
        f"/node_{page:02d}.html"
    )


def _old_layout_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/gmrb/html/{d.year:04d}-{d.month:02d}/{d.day:02d}"
        f"/nbs.D110000gmrb_{page:02d}.htm"
    )


def _fetch_texts(
    http: HttpSession, urls: list[str], silent_404: bool
) -> list[Optional[str]]:
    """并发抓取一批页面，按 urls 顺序返回（失败项为 None）。"""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        return list(pool.map(lambda u: http.get_text(u, silent_404=silent_404), urls))


def _new_page_refs(soup: BeautifulSoup, page_url: str) -> list[ArticleRef]:
    """新版版面页：.m-title-list .m-list-wrap li 内第一个 <a> 即文章。"""
    refs: list[ArticleRef] = []
    for li in soup.select(".m-title-list .m-list-wrap li"):
        a = li.find("a")
        if a is None:
            continue
        href = a.get("href", "")
        if not href:
            continue
        p = a.find("p")
        title = p.get_text().strip() if p is not None else a.get_text().strip()
        if title:
            refs.append(ArticleRef(title=title, url=join_url(page_url, href)))
    return refs


def _get_new_editions(http: HttpSession, d: date) -> list[Edition]:
    url1 = _new_layout_url(d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    soup = BeautifulSoup(html, "html.parser")
    name_el = soup.select_one(".m-type")
    if name_el is None:
        return []
    name = name_el.get_text().strip()

    refs = _new_page_refs(soup, url1)
    if not refs:
        return []
    editions = [Edition(num=1, name=name, articles=refs)]

    # 其余版面页与 node_01 同目录：<目录>/node_NN.html
    url_base = url1.rsplit("/", 1)[0]
    page_urls = [f"{url_base}/node_{p:02d}.html" for p in range(2, MAX_PAGES + 1)]
    bodies = _fetch_texts(http, page_urls, silent_404=True)
    for p, page_url, body in zip(range(2, MAX_PAGES + 1), page_urls, bodies):
        if body is None:
            continue
        doc = BeautifulSoup(body, "html.parser")
        name_el = doc.select_one(".m-type")
        page_name = name_el.get_text().strip() if name_el is not None else ""
        arts = _new_page_refs(doc, page_url)
        if arts:
            editions.append(Edition(num=p, name=page_name, articles=arts))

    editions.sort(key=lambda e: e.num)
    return editions


def _old_page_items(soup: BeautifulSoup, page_url: str, page_num: int) -> tuple[str, list[ArticleRef]]:
    """旧版版面页：返回 (版名, 文章引用列表)。

    版名取自 <title>（第N版:版名 格式），取不到时默认 第{page_num:02d}版（对齐 Rust）；
    文章为 href 含 nw.D110000gmrb 的 <a>，<a> 内 <br> 替换为空格后取纯文本。
    """
    name = f"第{page_num:02d}版"
    t = soup.find("title")
    if t is not None:
        m = RE_OLD_EDITION_NAME.search(t.get_text().strip())
        if m:
            name = m.group(1).strip()

    refs: list[ArticleRef] = []
    for a in soup.select(f'a[href*="{NW_HREF}"]'):
        href = a.get("href", "")
        if not href or NW_HREF not in href:
            continue
        # 复制 <a> 的 HTML 再替换 <br>，避免改动原文档
        clone = BeautifulSoup(str(a), "html.parser")
        for br in clone.find_all("br"):
            br.replace_with(" ")
        title = clone.get_text().strip()
        if not title:
            continue
        url = href if href.startswith("http") else join_url(page_url, href)
        refs.append(ArticleRef(title=title, url=url))
    return name, refs


def _get_old_editions(http: HttpSession, d: date) -> list[Edition]:
    url1 = _old_layout_url(d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    soup = BeautifulSoup(html, "html.parser")
    name, refs = _old_page_items(soup, url1, 1)
    if not refs:
        return []
    editions = [Edition(num=1, name=name, articles=refs)]

    urls = [_old_layout_url(d, p) for p in range(2, MAX_PAGES + 1)]
    bodies = _fetch_texts(http, urls, silent_404=True)
    for p, url, body in zip(range(2, MAX_PAGES + 1), urls, bodies):
        if body is None:
            continue
        doc = BeautifulSoup(body, "html.parser")
        page_name, arts = _old_page_items(doc, url, p)
        if arts:
            editions.append(Edition(num=p, name=page_name, articles=arts))

    editions.sort(key=lambda e: e.num)
    return editions


def _fetch_new_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = BeautifulSoup(html, "html.parser")

    t = doc.find("title")
    title = t.get_text().strip() if t is not None else ""
    if not title or title == "光明日报":
        title = r.title
    else:
        title = clean_title(title)

    paragraphs = [
        p.get_text().strip() for p in doc.select(".m-article-main p")
    ]
    paragraphs = [s for s in paragraphs if s]

    info = doc.select_one(".m-article-info")
    author = info.get_text().strip() if info is not None else ""
    return Article(title=title, author=author, paragraphs=paragraphs, url=r.url)


def _fetch_old_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = BeautifulSoup(html, "html.parser")

    title = r.title
    desc = meta_content(doc, "description")
    if len(desc.encode("utf-8")) > 5:
        title = desc
    if title == r.title:
        t = doc.find("title")
        if t is not None:
            s = t.get_text().strip()
            if len(s.encode("utf-8")) > 5:
                title = s
    title = clean_title(title)

    container = (
        doc.select_one(".text_c")
        or doc.select_one(".c_c")
        or doc.select_one(".content")
    )
    paragraphs: list[str] = []
    if container is not None:
        paragraphs = [p.get_text().strip() for p in container.find_all("p")]
        paragraphs = [s for s in paragraphs if s]

    lai = doc.select_one(".lai")
    author = lai.get_text().strip() if lai is not None else ""
    return Article(title=title, author=author, paragraphs=paragraphs, url=r.url)


class GuangmingCrawler(SiteCrawler):
    """光明日报站点爬虫。"""

    crawler_id = "gmrb"
    name = "光明日报"
    base_url = BASE_URL
    aliases = ["光明", "guangming"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        if _detect(d) == "new":
            return _get_new_editions(http, d)
        return _get_old_editions(http, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        if _detect(d) == "new":
            return _fetch_new_article(http, aref)
        return _fetch_old_article(http, aref)
