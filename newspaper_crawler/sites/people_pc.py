"""Shared parsers for People's Daily "pc" e-paper sites.

Five crawlers on paper.people.com.cn share this template family:

- magazine layout (rmlt / rmzk / zgjjzk): ``node_01`` already lists every edition
  as ``div.news h1`` (edition name) followed by ``ul#NN`` with that edition's
  article links, so one layout request discovers the whole issue.
- newspaper layout (rmrbhwb, and rmrb from 2024-12-01): one edition per
  ``node_NN.html``; the page navigation carries "NN版：NAME" for every edition of
  the issue.

Both layouts serve the same article page: ``div.article`` (h3 引题, h1 标题,
h2 副标题, p.sec 作者 + span.date) and ``div#ozoom`` body paragraphs.

Layout:  {base}/pc/layout/YYYYMM/DD/node_NN.html
Article: {base}/pc/content/YYYYMM/DD/content_{id}.html
"""

from __future__ import annotations

import re
from datetime import date
from typing import Optional

from ..base import EmptyIndexError, fetch_texts
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import clean_title, join_url, make_soup

RE_NODE_HREF = re.compile(r"node_(\d+)\.html")
RE_EDITION_TEXT = re.compile(r"(\d+)版[：:](.+)")
RE_CONTENT_HREF = re.compile(r"content_\d+\.html")
RE_UL_ID = re.compile(r"\d+")
# The magazine h1 carries only the edition name, but tolerate a page-number
# prefix in case the template adds one later ("02版：特别策划").
RE_EDITION_PREFIX = re.compile(r"^(?:第)?\d+版\s*(?:[：:]\s*)?")


def layout_url(base_url: str, d: date, page: int) -> str:
    """URL of one layout page for ``d``."""
    return (
        f"{base_url}/pc/layout/{d.year:04d}{d.month:02d}/{d.day:02d}"
        f"/node_{page:02d}.html"
    )


def _edition_num(raw_id: object, fallback: int) -> int:
    """Edition number from a list's id ("01"); ``fallback`` when absent."""
    m = RE_UL_ID.fullmatch(str(raw_id).strip()) if raw_id is not None else None
    return int(m.group(0)) if m else fallback


def _article_refs_in(container, base: str) -> list[ArticleRef]:
    """Article references from anchors under one edition's list."""
    refs: list[ArticleRef] = []
    for a in container.find_all("a", href=True):
        href = str(a.get("href", ""))
        title = a.get_text().strip()
        if href and title and RE_CONTENT_HREF.search(href):
            refs.append(ArticleRef(title=title, url=join_url(base, href)))
    return refs


def get_magazine_editions(http: HttpSession, base_url: str, d: date) -> list[Edition]:
    """Parse a one-page multi-edition issue (rmlt / rmzk / zgjjzk)."""
    url = layout_url(base_url, d, 1)
    html = http.get_text(url, silent_404=True)
    if html is None:
        return []

    doc = make_soup(html)
    news = doc.select_one("div.news")
    editions: list[Edition] = []
    if news is not None:
        for h1 in news.find_all("h1"):
            articles_ul = h1.find_next_sibling("ul")
            if articles_ul is None:
                continue
            num = _edition_num(articles_ul.get("id"), len(editions) + 1)
            name = RE_EDITION_PREFIX.sub("", h1.get_text().strip()).strip()
            editions.append(
                Edition(num=num, name=name, articles=_article_refs_in(articles_ul, url))
            )
    if not editions:
        raise EmptyIndexError("版面页未解析出任何版面（div.news h1/ul 无匹配）")

    editions.sort(key=lambda e: e.num)
    return editions


def get_node_editions(http: HttpSession, base_url: str, d: date) -> list[Edition]:
    """Parse an issue with one ``node_NN.html`` per edition (rmrbhwb)."""
    url1 = layout_url(base_url, d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    # Step 1: collect (page number, page name) from the layout navigation,
    # de-duplicated by page number, first occurrence wins.
    doc = make_soup(html)
    edition_refs: list[tuple[int, str]] = []
    seen: set[int] = set()
    for a in doc.find_all("a"):
        href = str(a.get("href", ""))
        if not RE_NODE_HREF.search(href):
            continue
        m = RE_EDITION_TEXT.search(a.get_text().strip())
        if not m:
            continue
        num = int(m.group(1)) if m.group(1).isdigit() else 0
        if num == 0 or num in seen:
            continue
        seen.add(num)
        edition_refs.append((num, m.group(2).strip()))
    if not edition_refs:
        raise EmptyIndexError("版面页未解析出任何版面导航")

    # Step 2: fetch the layout pages concurrently. Page 1 was already fetched
    # above, so serve it from the cache rather than requesting it twice.
    cache: dict[str, str] = {url1: html}
    urls = [layout_url(base_url, d, num) for num, _ in edition_refs]
    bodies = fetch_texts(http, urls, silent_404=False, cache=cache)
    results = [
        (num, name, body)
        for (num, name), body in zip(edition_refs, bodies)
        if body is not None
    ]
    results.sort(key=lambda item: item[0])

    # Step 3: collect article references from each layout page. Scope to the
    # div.news article list: the page also carries a "PDF下载" anchor pointing at
    # the same content URL, which must not become a duplicate article.
    editions: list[Edition] = []
    for num, name, body in results:
        edoc = make_soup(body)
        news = edoc.select_one("div.news")
        # The real template nests links in div.news > ul > li. A reduced page
        # without that container still exposes its content anchors directly; only
        # then fall back to the whole page. Scoping when div.news exists keeps its
        # "PDF下载" mirrors from duplicating real articles.
        anchors = (
            news.select("ul li a[href]")
            if news is not None
            else edoc.find_all("a", href=True)
        )
        articles: list[ArticleRef] = []
        for a in anchors:
            href = str(a.get("href", ""))
            title = a.get_text().strip()
            if href and title and RE_CONTENT_HREF.search(href):
                articles.append(
                    ArticleRef(
                        title=title, url=join_url(layout_url(base_url, d, num), href)
                    )
                )
        # A successfully fetched layout page is kept even with no articles.
        editions.append(Edition(num=num, name=name, articles=articles))
    return editions


def fetch_pc_article(http: HttpSession, r: ArticleRef) -> Optional[Article]:
    """Fetch and parse one article from the shared "pc" template."""
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)

    yinti = ""
    title = ""
    subtitle = ""
    author = ""
    article_div = doc.select_one("div.article")
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
            # The sec line is "author" plus a date span; keep only the author.
            date_span = sec.find("span", class_="date")
            if date_span is not None:
                date_span.extract()
            author = " ".join(sec.get_text().split())
            # Some pages leave the publication citation in the same line without
            # a date span; the byline is everything before "《".
            if "《" in author:
                author = author[: author.index("《")].strip()

    # Title fallback chain: h1 -> <title> -> reference title, then strip a
    # "-人民网"-style suffix.
    if not title:
        t = doc.find("title")
        if t is not None:
            title = t.get_text().strip()
    if not title:
        title = r.title
    title = clean_title(title)

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
