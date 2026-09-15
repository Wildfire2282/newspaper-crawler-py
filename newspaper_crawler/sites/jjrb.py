"""Economic Daily crawler.

Base URL: http://paper.ce.cn/pc

Layout page: {base}/layout/YYYYMM/DD/node_NN.html
Article page: {base}/content/YYYYMM/DD/content_{cid}.html

Mirrors Rust src-tauri/src/crawler/jjrb.rs.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..base import EmptyIndexError, SiteCrawler, fetch_texts
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import make_soup

BASE_URL = "http://paper.ce.cn/pc"

RE_NODE = re.compile(r"node_(\d+)\.html")
RE_CONTENT = re.compile(r"content_(\d+)\.html")


def _edition_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/layout/{d.year:04d}{d.month:02d}/{d.day:02d}/node_{page:02d}.html"
    )


def _article_url(d: date, cid: str) -> str:
    """Article page URL. ``cid`` is the raw captured string, never zero-padded
    (mirrors Rust).
    """
    return (
        f"{BASE_URL}/content/{d.year:04d}{d.month:02d}/{d.day:02d}/content_{cid}.html"
    )


def _get_editions(http: HttpSession, d: date) -> list[Edition]:
    url1 = _edition_url(d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    # Step 1: collect page numbers and names from the layout navigation
    # (ul#layoutlist).
    doc = make_soup(html)
    edition_refs: list[tuple[int, str]] = []
    ul = doc.select_one("ul#layoutlist")
    if ul is not None:
        for li in ul.find_all("li"):
            a = li.find("a")
            if a is None:
                continue
            href = a.get("href", "")
            m = RE_NODE.search(href)
            if not m:
                continue
            node_num = int(m.group(1)) if m.group(1).isdigit() else 0
            if node_num == 0:
                continue
            raw = a.get_text().strip()
            if "：" in raw:
                name = raw[raw.index("：") + 1 :]
            elif ":" in raw:
                name = raw[raw.index(":") + 1 :]
            else:
                name = raw
            edition_refs.append((node_num, name))
    if not edition_refs:
        raise EmptyIndexError("第 1 版页未解析出任何版面导航")

    # Step 2: fetch the layout pages concurrently. Page 1 was already fetched while
    # parsing the navigation, so serve it from the cache.
    cache: dict[str, str] = {url1: html}
    urls = [_edition_url(d, node) for node, _ in edition_refs]
    bodies = fetch_texts(http, urls, silent_404=False, cache=cache)
    results = [
        (node, name, body)
        for (node, name), body in zip(edition_refs, bodies)
        if body is not None
    ]
    results.sort(key=lambda x: x[0])

    # Step 3: collect article references from each layout page.
    editions: list[Edition] = []
    for node, name, body in results:
        edoc = make_soup(body)
        articles: list[ArticleRef] = []
        art_ul = edoc.select_one("ul#articlelist, ul.newsList")
        if art_ul is not None:
            for li in art_ul.find_all("li"):
                a = li.find("a")
                if a is None:
                    continue
                href = a.get("href", "")
                m = RE_CONTENT.search(href)
                if not m:
                    continue
                cid = m.group(1)
                p = a.find("p")
                title = p.get_text().strip() if p is not None else a.get_text().strip()
                if title:
                    articles.append(
                        ArticleRef(
                            title=title,
                            url=_article_url(d, cid),
                            extra={"content_id": cid},
                        )
                    )
        # Mirrors Rust: a successfully fetched layout page is kept even with no articles.
        editions.append(Edition(num=node, name=name, articles=articles))
    return editions


def _fetch_article(http: HttpSession, r: ArticleRef, d: date) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)

    # Title: h2#Title (prefer its inner <p>) -> <title> -> reference title.
    title = ""
    h2 = doc.select_one("h2#Title")
    if h2 is not None:
        p = h2.find("p")
        title = p.get_text().strip() if p is not None else h2.get_text().strip()
    if not title:
        t = doc.find("title")
        if t is not None:
            title = t.get_text().strip()
    if not title:
        title = r.title

    # Subtitle: div#SubTitle (prefer its inner <p>).
    subtitle = ""
    sub = doc.select_one("div#SubTitle")
    if sub is not None:
        p = sub.find("p")
        subtitle = p.get_text().strip() if p is not None else sub.get_text().strip()

    author_el = doc.select_one("div#Author")
    author = author_el.get_text().strip() if author_el is not None else ""

    # Body: <p> elements inside founder-content, else inside div#ozoom.
    container = doc.select_one("founder-content") or doc.select_one("div#ozoom")
    paragraphs: list[str] = []
    if container is not None:
        paragraphs = [p.get_text().strip() for p in container.find_all("p")]
        paragraphs = [s for s in paragraphs if s]

    return Article(
        title=title,
        subtitle=subtitle,
        author=author,
        paragraphs=paragraphs,
        url=r.url,
    )


class JingjiCrawler(SiteCrawler):
    """Economic Daily crawler."""

    crawler_id = "jjrb"
    name = "经济日报"
    base_url = BASE_URL
    aliases = ["经济", "jingji"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        return _get_editions(http, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        # The date argument is ignored (only sites with a system switch need it).
        return _fetch_article(http, aref, d)
