"""Guangming Daily crawler.

Base URL: https://epaper.gmw.cn/gmrb

Two upstream systems, selected by date:
- new (d >= 2026-01-01): /gmrb/html/layout/YYYYMM/DD/node_NN.html
- old (d <= 2025-12-31): /gmrb/html/YYYY-MM/DD/nbs.D110000gmrb_NN.htm

Mirrors Rust src-tauri/src/crawler/gmrb.rs.
"""

from __future__ import annotations

import html as html_module
import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from ..base import EmptyIndexError, SiteCrawler, fetch_texts
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import (
    clean_title,
    join_url,
    make_soup,
    meta_content,
    page_numbers_from_links,
)

BASE_URL = "https://epaper.gmw.cn"
SWITCH_DATE = date(2026, 1, 1)

# Page name inside the old system's <title>, e.g. "第01版:要闻_光明日报".
RE_OLD_EDITION_NAME = re.compile(r"第\d+版[:：](.+?)(?:_|$)")
# Old-system article link marker.
NW_HREF = "nw.D110000gmrb"
# Layout page links, new and old; used to discover the real edition set.
RE_NEW_PAGE_HREF = re.compile(r"node_(\d+)\.html")
RE_OLD_PAGE_HREF = re.compile(r"nbs\.D110000gmrb_(\d+)\.htm")
# Title cleanup inside an anchor: <br> becomes a space, then remaining tags are dropped.
RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_TAG = re.compile(r"<[^>]+>")

# Page-count ceiling; consulted only when the navigation links reveal no page numbers.
MAX_PAGES = 20


def _detect(d: date) -> str:
    """Return "new" for d >= 2026-01-01, else "old"."""
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


def _new_page_refs(soup: BeautifulSoup, page_url: str) -> list[ArticleRef]:
    """New-system layout page: the first <a> under each
    .m-title-list .m-list-wrap li is one article.
    """
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

    soup = make_soup(html)
    name_el = soup.select_one(".m-type")
    if name_el is None:
        raise EmptyIndexError("新版版面页缺少 .m-type 版面名")
    name = name_el.get_text().strip()

    refs = _new_page_refs(soup, url1)
    if not refs:
        raise EmptyIndexError("新版第 1 版页未解析出任何文章")
    editions = [Edition(num=1, name=name, articles=refs)]

    # Remaining layout pages share node_01's directory: <dir>/node_NN.html.
    # Page numbers are discovered from the page-1 links when possible; otherwise fall
    # back to probing 2..MAX_PAGES.
    url_base = url1.rsplit("/", 1)[0]
    pages = [
        p for p in page_numbers_from_links(soup, RE_NEW_PAGE_HREF, MAX_PAGES) if p >= 2
    ]
    if not pages:
        pages = list(range(2, MAX_PAGES + 1))

    cache: dict[str, str] = {url1: html}
    page_urls = [f"{url_base}/node_{p:02d}.html" for p in pages]
    bodies = fetch_texts(http, page_urls, silent_404=True, cache=cache)
    for p, page_url, body in zip(pages, page_urls, bodies):
        if body is None:
            continue
        doc = make_soup(body)
        name_el = doc.select_one(".m-type")
        page_name = name_el.get_text().strip() if name_el is not None else ""
        arts = _new_page_refs(doc, page_url)
        if arts:
            editions.append(Edition(num=p, name=page_name, articles=arts))

    editions.sort(key=lambda e: e.num)
    return editions


def _old_page_items(
    soup: BeautifulSoup, page_url: str, page_num: int
) -> tuple[str, list[ArticleRef]]:
    """Old-system layout page -> (page name, article references).

    Page name comes from <title> (第N版:版名), defaulting to 第{page_num:02d}版 when
    absent (mirrors Rust). Articles are the anchors whose href contains
    nw.D110000gmrb; an anchor's title is its text with <br> turned into a space.
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
        # <br> becomes a space, then tags are stripped and entities unescaped; this
        # avoids rebuilding a parse tree for every anchor.
        title = html_module.unescape(RE_TAG.sub("", RE_BR.sub(" ", str(a)))).strip()
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

    soup = make_soup(html)
    name, refs = _old_page_items(soup, url1, 1)
    if not refs:
        raise EmptyIndexError("旧版第 1 版页未解析出任何文章")
    editions = [Edition(num=1, name=name, articles=refs)]

    # Remaining page numbers come from the page-1 links when discoverable; otherwise
    # fall back to probing 2..MAX_PAGES.
    pages = [
        p for p in page_numbers_from_links(soup, RE_OLD_PAGE_HREF, MAX_PAGES) if p >= 2
    ]
    if not pages:
        pages = list(range(2, MAX_PAGES + 1))

    urls = [_old_layout_url(d, p) for p in pages]
    bodies = fetch_texts(http, urls, silent_404=True)
    for p, url, body in zip(pages, urls, bodies):
        if body is None:
            continue
        doc = make_soup(body)
        page_name, arts = _old_page_items(doc, url, p)
        if arts:
            editions.append(Edition(num=p, name=page_name, articles=arts))

    editions.sort(key=lambda e: e.num)
    return editions


def _fetch_new_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)

    t = doc.find("title")
    title = t.get_text().strip() if t is not None else ""
    if not title or title == "光明日报":
        title = r.title
    else:
        title = clean_title(title)

    paragraphs = [p.get_text().strip() for p in doc.select(".m-article-main p")]
    paragraphs = [s for s in paragraphs if s]

    info = doc.select_one(".m-article-info")
    author = info.get_text().strip() if info is not None else ""
    return Article(title=title, author=author, paragraphs=paragraphs, url=r.url)


def _fetch_old_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)

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
    """Guangming Daily crawler."""

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
