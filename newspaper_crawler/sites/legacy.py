"""Shared parser for the legacy nbs.D110000* e-paper article pages."""
from __future__ import annotations

from typing import Optional

from ..http import HttpSession
from ..models import Article, ArticleRef
from ..util import clean_title, make_soup, meta_content


def _clean_author(text: str) -> str:
    """Normalize a legacy `.lai` block: drop the `作者：` prefix and the trailing
    `《报纸》（日期 版次）` citation, so only a real byline survives.
    """
    s = " ".join(text.split())
    for prefix in ("作者：", "作者:"):
        if s.startswith(prefix):
            s = s[len(prefix) :].strip()
            break
    if "《" in s:
        s = s.split("《", 1)[0].strip()
    return s


def fetch_legacy_article(
    http: HttpSession,
    r: ArticleRef,
    *,
    containers: tuple[str, ...],
    author_selector: str,
    clean_site_suffix: bool,
) -> Optional[Article]:
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
    if clean_site_suffix:
        title = clean_title(title)

    # Body container, tried in order.
    container = None
    for selector in containers:
        container = doc.select_one(selector)
        if container is not None:
            break
    paragraphs: list[str] = []
    if container is not None:
        paragraphs = [p.get_text().strip() for p in container.find_all("p")]
        paragraphs = [s for s in paragraphs if s]

    lai = doc.select_one(author_selector)
    author = _clean_author(lai.get_text()) if lai is not None else ""

    return Article(title=title, author=author, paragraphs=paragraphs, url=r.url)
