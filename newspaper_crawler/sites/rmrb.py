"""People's Daily crawler.

Base URL: http://paper.people.com.cn/rmrb

Two upstream systems, selected by date:
- new (d >= 2024-12-01): /pc/layout/YYYYMM/DD/node_NN.html
- old (d <= 2024-11-30): /html/YYYY-MM/DD/nbs.D110000renmrb_NN.htm

Mirrors Rust src-tauri/src/crawler/rmrb.rs.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from ..base import EmptyIndexError, SiteCrawler, fetch_texts
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import join_url, make_soup, meta_content, page_numbers_from_links

BASE_URL = "http://paper.people.com.cn/rmrb"
SWITCH_DATE = date(2024, 12, 1)

RE_NODE_HREF = re.compile(r"node_(\d+)\.html")
RE_ED_TEXT = re.compile(r"(\d+)版[：:](.+)")
RE_CONTENT_HREF = re.compile(r"content_\d+\.html")
RE_TITLE_SUFFIX = re.compile(r"[-—].*?(人民日报|人民网).*$")
RE_OLD_ED = re.compile(r"第\d+版[:：](.+?)(?:_|$)")
RE_OLD_PAGE_HREF = re.compile(r"nbs\.D110000renmrb_(\d+)\.htm")

# Page-count ceiling (the old system has at most 20 pages). Consulted only as a
# fallback when the navigation links reveal no page numbers.
MAX_PAGES = 20


def _new_layout_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/pc/layout/{d.year:04d}{d.month:02d}/{d.day:02d}"
        f"/node_{page:02d}.html"
    )


def _old_layout_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/html/{d.year:04d}-{d.month:02d}/{d.day:02d}"
        f"/nbs.D110000renmrb_{page:02d}.htm"
    )


def _old_article_refs(soup: BeautifulSoup, base: str) -> list[ArticleRef]:
    """Old-system layout page: collect anchors whose href contains nw.D110000renmrb.

    Title = the anchor text with every <br> replaced by a space (mirrors the Rust
    br-to-space-then-text behavior).

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
    name = f"第{page:02d}版"
    t = doc.find("title")
    if t is not None:
        m = RE_OLD_ED.search(t.get_text().strip())
        if m:
            name = m.group(1).strip()
    refs = _old_article_refs(doc, _old_layout_url(d, page))
    if not refs:
        return None
    return Edition(num=page, name=name, articles=refs)


def _get_new_editions(http: HttpSession, d: date) -> list[Edition]:
    url1 = _new_layout_url(d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    # Step 1: collect (page number, page name) from the layout navigation,
    # de-duplicated by page number, first occurrence wins.
    doc = make_soup(html)
    edition_refs: list[tuple[int, str]] = []
    seen: set[int] = set()
    for a in doc.find_all("a"):
        href = a.get("href", "")
        if not RE_NODE_HREF.search(href):
            continue
        m = RE_ED_TEXT.search(a.get_text().strip())
        if not m:
            continue
        num = int(m.group(1)) if m.group(1).isdigit() else 0
        if num == 0 or num in seen:
            continue
        seen.add(num)
        edition_refs.append((num, m.group(2).strip()))
    if not edition_refs:
        raise EmptyIndexError("新版版面页未解析出任何版面导航")

    # Step 2: fetch the layout pages concurrently. Page 1 was already fetched above,
    # so serve it from the cache rather than requesting it twice.
    cache: dict[str, str] = {url1: html}
    urls = [_new_layout_url(d, num) for num, _ in edition_refs]
    bodies = fetch_texts(http, urls, silent_404=False, max_workers=16, cache=cache)
    results = [
        (num, name, body)
        for (num, name), body in zip(edition_refs, bodies)
        if body is not None
    ]
    results.sort(key=lambda x: x[0])

    # Step 3: collect article references from each layout page.
    editions: list[Edition] = []
    for num, name, body in results:
        edoc = make_soup(body)
        articles: list[ArticleRef] = []
        base = _new_layout_url(d, num)
        for a in edoc.find_all("a"):
            href = a.get("href", "")
            if not RE_CONTENT_HREF.search(href):
                continue
            title = a.get_text().strip()
            if href and title:
                articles.append(ArticleRef(title=title, url=join_url(base, href)))
        editions.append(Edition(num=num, name=name, articles=articles))
    return editions


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
    bodies = fetch_texts(http, urls, silent_404=True, max_workers=16)
    for p, body in zip(pages, bodies):
        if body is None:
            continue
        ed = _parse_old_edition(d, p, body)
        if ed is not None:
            editions.append(ed)
    editions.sort(key=lambda e: e.num)
    return editions


def _fetch_new_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)
    article_div = doc.select_one("div.article")

    yinti = ""
    title = ""
    subtitle = ""
    author = ""
    if article_div is not None:
        h3 = article_div.find("h3")
        if h3 is not None:
            yinti = h3.get_text().strip()
        h1 = article_div.find("h1")
        if h1 is not None:
            title = h1.get_text().strip()
        h2 = article_div.find("h2")
        if h2 is not None:
            subtitle = h2.get_text().strip()
        sec = article_div.find("p", class_="sec")
        if sec is not None:
            s = sec.get_text().strip()
            if "《人民日报》" in s:
                author = s[: s.index("《人民日报》")].strip()
            elif "《" in s:
                author = s[: s.index("《")].strip()
            else:
                author = s

    # Title fallback chain: h1 -> <title> -> reference title, then strip a
    # "-人民日报"-style suffix.
    if not title:
        t = doc.find("title")
        if t is not None:
            title = t.get_text().strip()
    if not title:
        title = r.title
    title = RE_TITLE_SUFFIX.sub("", title).strip()

    # Body: every <p> inside div#ozoom.
    paragraphs: list[str] = []
    ozoom = doc.select_one("div#ozoom")
    if ozoom is not None:
        paragraphs = [p.get_text().strip() for p in ozoom.find_all("p")]
        paragraphs = [s for s in paragraphs if s]

    return Article(
        title=title,
        yinti=yinti,
        subtitle=subtitle,
        author=author,
        paragraphs=paragraphs,
        url=r.url,
    )


def _fetch_old_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)

    # Title: meta description (>5 bytes) -> <title> (>5 bytes) -> reference title.
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

    # Body container, tried in order.
    container = (
        doc.select_one(".text_c")
        or doc.select_one(".c_c")
        or doc.select_one("#ozoom")
        or doc.select_one(".content")
    )
    paragraphs: list[str] = []
    if container is not None:
        paragraphs = [p.get_text().strip() for p in container.find_all("p")]
        paragraphs = [s for s in paragraphs if s]

    lai = doc.select_one(".lai, .author")
    author = lai.get_text().strip() if lai is not None else ""

    return Article(title=title, author=author, paragraphs=paragraphs, url=r.url)


class RenminCrawler(SiteCrawler):
    """People's Daily crawler; switches new/old system at 2024-12-01."""

    crawler_id = "rmrb"
    name = "人民日报"
    base_url = BASE_URL
    aliases = ["人民", "renmin", "people"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        if d >= SWITCH_DATE:
            return _get_new_editions(http, d)
        return _get_old_editions(http, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        if d >= SWITCH_DATE:
            return _fetch_new_article(http, aref)
        return _fetch_old_article(http, aref)
