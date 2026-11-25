"""People's Daily crawler.

Base URL: http://paper.people.com.cn/rmrb

Two upstream systems, selected by date:
- new (d >= 2024-12-01): the shared People's Daily "pc" template implemented in
  :mod:`newspaper_crawler.sites.people_pc` (one ``node_NN.html`` per edition).
- old (d <= 2024-11-30): /html/YYYY-MM/DD/nbs.D110000renmrb_NN.htm
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from ..base import EmptyIndexError, SiteCrawler, fetch_texts
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import join_url, make_soup, page_numbers_from_links
from .legacy import fetch_legacy_article
from .people_pc import fetch_pc_article, get_node_editions

BASE_URL = "http://paper.people.com.cn/rmrb"
SWITCH_DATE = date(2024, 12, 1)

RE_OLD_ED = re.compile(r"第\d+版[:：](.+?)(?:_|$)")
RE_OLD_PAGE_HREF = re.compile(r"nbs\.D110000renmrb_(\d+)\.htm")

# Page-count ceiling (the old system has at most 20 pages). Consulted only as a
# fallback when the navigation links reveal no page numbers.
MAX_PAGES = 20


def _old_layout_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/html/{d.year:04d}-{d.month:02d}/{d.day:02d}"
        f"/nbs.D110000renmrb_{page:02d}.htm"
    )


def _old_article_refs(soup: BeautifulSoup, base: str) -> list[ArticleRef]:
    """Old-system layout page: collect anchors whose href contains nw.D110000renmrb.

    Title = the anchor text with every <br> replaced by a space.

    Note: mutates the matched anchors in place.
    """
    refs: list[ArticleRef] = []
    for a in soup.select('a[href*="nw.D110000renmrb"]'):
        href = a.get("href", "")
        if "nw.D110000renmrb" not in href:
            continue
        for br in a.find_all("br"):
            br.replace_with(" ")
        title = a.get_text().strip()
        if not href or not title:
            continue
        refs.append(ArticleRef(title=title, url=join_url(base, href)))
    return refs


def _parse_old_edition(d: date, page: int, html: str) -> Optional[Edition]:
    """Parse one old-system layout page; None when it yields no article."""
    doc = make_soup(html)
    # The page banner ("第01版:要闻") carries the edition name; <title> is just
    # "人民日报-人民网" on this system. Empty name = "第NN版" alone, no duplicate label.
    name = ""
    for el in (doc.select_one("p.ban"), doc.find("title")):
        if el is None:
            continue
        m = RE_OLD_ED.search(el.get_text().strip())
        if m:
            name = m.group(1).strip()
            break
    refs = _old_article_refs(doc, _old_layout_url(d, page))
    if not refs:
        return None
    return Edition(num=page, name=name, articles=refs)


def _get_old_editions(http: HttpSession, d: date) -> list[Edition]:
    url1 = _old_layout_url(d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    first = _parse_old_edition(d, 1, html)
    if first is None:
        raise EmptyIndexError("旧版第 1 版页未解析出任何文章")
    editions: list[Edition] = [first]

    # Remaining page numbers come from the navigation links when discoverable;
    # otherwise fall back to probing 2..MAX_PAGES.
    doc = make_soup(html)
    pages = [
        p for p in page_numbers_from_links(doc, RE_OLD_PAGE_HREF, MAX_PAGES) if p >= 2
    ]
    if not pages:
        pages = list(range(2, MAX_PAGES + 1))

    urls = [_old_layout_url(d, p) for p in pages]
    bodies = fetch_texts(http, urls, silent_404=True)
    for p, body in zip(pages, bodies):
        if body is None:
            continue
        ed = _parse_old_edition(d, p, body)
        if ed is not None:
            editions.append(ed)
    editions.sort(key=lambda e: e.num)
    return editions


def _fetch_old_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    return fetch_legacy_article(
        http,
        r,
        containers=(".text_c", ".c_c", "#ozoom", ".content"),
        author_selector=".lai, .author",
        clean_site_suffix=False,
    )


class RenminCrawler(SiteCrawler):
    """People's Daily crawler; switches new/old system at 2024-12-01."""

    crawler_id = "rmrb"
    name = "人民日报"
    base_url = BASE_URL
    aliases = ["人民", "renmin", "people"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        if d >= SWITCH_DATE:
            return get_node_editions(http, BASE_URL, d)
        return _get_old_editions(http, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        if d >= SWITCH_DATE:
            return fetch_pc_article(http, aref)
        return _fetch_old_article(http, aref)
