"""Dazhong Daily crawler.

Base URL: https://paper.dzwww.com/dzrb

A single index page (PageArticleIndexWZ.htm) carries every edition and article link.

Mirrors Rust src-tauri/src/crawler/dzrb.rs.
"""

from __future__ import annotations

import html as html_module
import re
from datetime import date
from typing import Optional

from ..base import EmptyIndexError, SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import join_url, make_soup

BASE_URL = "https://paper.dzwww.com/dzrb"

RE_ED = re.compile(r"\[(\d+)\]:\s*(.*)")
RE_BR = re.compile(r"<br\s*/?>", re.IGNORECASE)
RE_TAG = re.compile(r"<[^>]+>")


def _index_url(d: date) -> str:
    return (
        f"{BASE_URL}/content/{d.year:04d}{d.month:02d}{d.day:02d}"
        f"/PageArticleIndexWZ.htm"
    )


def _get_editions(http: HttpSession, d: date) -> list[Edition]:
    url = _index_url(d)
    html = http.get_text(url, silent_404=True)
    if html is None:
        return []

    doc = make_soup(html)
    editions: list[Edition] = []
    for cell in doc.select("td.font_bai"):
        text = cell.get_text().strip()
        m = RE_ED.search(text)
        if not m:
            continue
        page_num = int(m.group(1)) if m.group(1).isdigit() else 0
        if page_num == 0:
            continue
        name = m.group(2).strip()

        # An edition's articles live in the div with id=partTitleDiv{page_num}.
        div = doc.find(id=f"partTitleDiv{page_num}")
        articles: list[ArticleRef] = []
        if div is not None:
            for a in div.find_all("a", href=True):
                href = a["href"]
                title = a.get_text().strip()
                if href and title and href.endswith(".htm"):
                    articles.append(ArticleRef(title=title, url=join_url(url, href)))
        editions.append(Edition(num=page_num, name=name, articles=articles))
    if not editions:
        raise EmptyIndexError("索引页未解析出任何版面（td.font_bai 无匹配）")
    return editions


def _fetch_article(http: HttpSession, r: ArticleRef, d: date) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = make_soup(html)

    yinti_el = doc.select_one("h2.yinti span")
    yinti = yinti_el.get_text().strip() if yinti_el is not None else ""

    biaoti_el = doc.select_one("h1.biaoti")
    title = biaoti_el.get_text().strip() if biaoti_el is not None else r.title

    futi_el = doc.select_one("h2.futi span")
    futi = futi_el.get_text().strip() if futi_el is not None else ""

    author_el = doc.select_one("#author")
    author = author_el.get_text().strip() if author_el is not None else ""

    img_el = doc.select_one(".imagedesc")
    image_desc = img_el.get_text().strip() if img_el is not None else ""

    # Body: split #contenttext's HTML on <br>, then strip tags and unescape entities.
    paragraphs: list[str] = []
    content = doc.select_one("#contenttext")
    if content is not None:
        raw = str(content)
        for part in RE_BR.split(raw):
            t = html_module.unescape(RE_TAG.sub("", part)).strip()
            if t:
                paragraphs.append(t)

    # Fallback: the non-empty text of every <p> on the page.
    if not paragraphs:
        paragraphs = [p.get_text().strip() for p in doc.find_all("p")]
        paragraphs = [s for s in paragraphs if s]

    return Article(
        title=title,
        yinti=yinti,
        subtitle=futi,
        author=author,
        paragraphs=paragraphs,
        image_desc=image_desc,
        url=r.url,
    )


class DazhongCrawler(SiteCrawler):
    """Dazhong Daily crawler."""

    crawler_id = "dzrb"
    name = "大众日报"
    base_url = BASE_URL
    aliases = ["大众", "dazhong"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        return _get_editions(http, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        # The date argument is ignored (only sites with a system switch need it).
        return _fetch_article(http, aref, d)
