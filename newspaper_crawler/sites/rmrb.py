"""人民日报爬虫。

网址: http://paper.people.com.cn/rmrb

- 2024 年 12 月 1 日起新版系统（/pc/layout/YYYYMM/DD/node_NN.html）
- 2024 年 11 月 30 日及以前旧版系统（/html/YYYY-MM/DD/nbs.D110000renmrb_NN.htm）

逐条对齐 Rust 版 src-tauri/src/crawler/rmrb.rs。
"""

from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from typing import Optional

from bs4 import BeautifulSoup

from ..base import SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from ..util import join_url, meta_content

BASE_URL = "http://paper.people.com.cn/rmrb"
SWITCH_DATE = date(2024, 12, 1)

RE_NODE_HREF = re.compile(r"node_\d+\.html")
RE_ED_TEXT = re.compile(r"(\d+)版[：:](.+)")
RE_CONTENT_HREF = re.compile(r"content_\d+\.html")
RE_TITLE_SUFFIX = re.compile(r"[-—].*?(人民日报|人民网).*$")
RE_OLD_ED = re.compile(r"第\d+版[:：](.+?)(?:_|$)")


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


def _fetch_texts(
    http: HttpSession, urls: list[str], silent_404: bool
) -> list[Optional[str]]:
    """并发抓取一批页面，按 urls 顺序返回（失败项为 None，对齐 Rust FuturesUnordered 容错）。"""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=min(16, len(urls))) as pool:
        return list(pool.map(lambda u: http.get_text(u, silent_404=silent_404), urls))


def _old_article_refs(
    soup: BeautifulSoup, base: str
) -> list[ArticleRef]:
    """旧版版面页：收集 href 含 nw.D110000renmrb 的 <a>。

    标题 = 把 <a> 内所有 <br> 替换为空格后的纯文本（对齐 Rust 的 br→空格再取 text）。
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
    """解析单个旧版版面页；无文章时返回 None。"""
    doc = BeautifulSoup(html, "html.parser")
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

    # 第 1 步：从版面导航页收集 (版号, 版名)，按版号去重（保持首次出现顺序）
    doc = BeautifulSoup(html, "html.parser")
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
        return []

    # 第 2 步：并发抓取各版面页（Rust 版此处 silent_404=False）
    urls = [_new_layout_url(d, num) for num, _ in edition_refs]
    bodies = _fetch_texts(http, urls, silent_404=False)
    results = [
        (num, name, body)
        for (num, name), body in zip(edition_refs, bodies)
        if body is not None
    ]
    results.sort(key=lambda x: x[0])

    # 第 3 步：从版面页收集文章引用
    editions: list[Edition] = []
    for num, name, body in results:
        edoc = BeautifulSoup(body, "html.parser")
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
        return []
    editions: list[Edition] = [first]

    # 第 2~20 版并发抓取（silent_404=True）
    pages = list(range(2, 21))
    urls = [_old_layout_url(d, p) for p in pages]
    bodies = _fetch_texts(http, urls, silent_404=True)
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
    doc = BeautifulSoup(html, "html.parser")
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

    # 标题回退：h1 → <title> → 引用标题，最后去掉 "-人民日报" 类后缀
    if not title:
        t = doc.find("title")
        if t is not None:
            title = t.get_text().strip()
    if not title:
        title = r.title
    title = RE_TITLE_SUFFIX.sub("", title).strip()

    # 正文：div#ozoom 内所有 <p>
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
    doc = BeautifulSoup(html, "html.parser")

    # 标题：meta description（>5 字符）→ <title>（>5 字符）→ 引用标题
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

    # 正文容器依次尝试 .text_c / .c_c / #ozoom / .content
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
    """人民日报站点爬虫（2024-12-01 起新老系统自动切换）。"""

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
