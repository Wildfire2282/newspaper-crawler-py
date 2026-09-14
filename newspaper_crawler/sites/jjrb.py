"""经济日报爬虫。

网址: http://paper.ce.cn/pc

版面页: {base}/layout/YYYYMM/DD/node_NN.html
文章页: {base}/content/YYYYMM/DD/content_{cid}.html

逐条对齐 Rust 版 src-tauri/src/crawler/jjrb.rs。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from ..base import SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition

BASE_URL = "http://paper.ce.cn/pc"

RE_NODE = re.compile(r"node_(\d+)\.html")
RE_CONTENT = re.compile(r"content_(\d+)\.html")


def _edition_url(d: date, page: int) -> str:
    return (
        f"{BASE_URL}/layout/{d.year:04d}{d.month:02d}/{d.day:02d}/node_{page:02d}.html"
    )


def _article_url(d: date, cid: str) -> str:
    """文章页 URL，cid 为捕获到的原始字符串（不做补零，与 Rust 版一致）。"""
    return (
        f"{BASE_URL}/content/{d.year:04d}{d.month:02d}/{d.day:02d}/content_{cid}.html"
    )


def _fetch_texts(
    http: HttpSession, urls: list[str], silent_404: bool
) -> list[Optional[str]]:
    """并发抓取一批页面，按 urls 顺序返回（失败项为 None）。"""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(urls))) as pool:
        return list(pool.map(lambda u: http.get_text(u, silent_404=silent_404), urls))


def _get_editions(http: HttpSession, d: date) -> list[Edition]:
    url1 = _edition_url(d, 1)
    html = http.get_text(url1, silent_404=True)
    if html is None:
        return []

    # 第 1 步：从版面导航（ul#layoutlist）收集版面号与版名
    doc = BeautifulSoup(html, "html.parser")
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
        return []

    # 第 2 步：并发抓取各版面页（Rust 版此处 silent_404=False）
    urls = [_edition_url(d, node) for node, _ in edition_refs]
    bodies = _fetch_texts(http, urls, silent_404=False)
    results = [
        (node, name, body)
        for (node, name), body in zip(edition_refs, bodies)
        if body is not None
    ]
    results.sort(key=lambda x: x[0])

    # 第 3 步：从版面页收集文章引用
    editions: list[Edition] = []
    for node, name, body in results:
        edoc = BeautifulSoup(body, "html.parser")
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
        # 与 Rust 版一致：版面页成功抓取即加入（即使无文章）
        editions.append(Edition(num=node, name=name, articles=articles))
    return editions


def _fetch_article(http: HttpSession, r: ArticleRef, d: date) -> Optional[Article]:
    html = http.get_text(r.url, silent_404=False)
    if html is None:
        return None
    doc = BeautifulSoup(html, "html.parser")

    # 标题：h2#Title（优先内部 <p>）→ <title> → 引用标题
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

    # 副题：div#SubTitle（优先内部 <p>）
    subtitle = ""
    sub = doc.select_one("div#SubTitle")
    if sub is not None:
        p = sub.find("p")
        subtitle = p.get_text().strip() if p is not None else sub.get_text().strip()

    author_el = doc.select_one("div#Author")
    author = author_el.get_text().strip() if author_el is not None else ""

    # 正文：founder-content 或 div#ozoom 内 <p>
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
    """经济日报站点爬虫。"""

    crawler_id = "jjrb"
    name = "经济日报"
    base_url = BASE_URL
    aliases = ["经济", "jingji"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        return _get_editions(http, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        # Rust 版忽略日期参数（仅新老系统切换的站点需要）
        return _fetch_article(http, aref, d)
