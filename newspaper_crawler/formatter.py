"""Markdown / 纯文本格式化。

对齐 Rust 版 src-tauri/src/crawler/format.rs 的 Formatter。
"""

from __future__ import annotations

import re
from datetime import date

from .models import Article, Edition, art_title, is_full
from .util import weekday_cn_full

RE_ANCHOR = re.compile(r"[^\w\s\u4e00-\u9fff-]")
RE_SPACE = re.compile(r"\s+")

SEPARATOR = "=" * 60
DIVIDER = "  ----------------------------------------"


class Formatter:
    """站点输出格式化器：生成 Markdown 或纯文本日报文件。"""

    def __init__(self, name: str, base_url: str):
        self.name = name
        self.base_url = base_url

    # ------------------------------------------------------------------ #
    # Markdown
    # ------------------------------------------------------------------ #
    def markdown(self, d: date, editions: list[Edition]) -> str:
        total_editions = len(editions)
        total_articles = count_full(editions)
        out = self._md_header(d, total_editions, total_articles)
        if not editions:
            out += "> 该日无报纸或无法访问\n"
            return out

        ed_anchors, art_anchors = anchors(editions)
        for line in self._md_toc(editions, ed_anchors, art_anchors):
            out += line

        for ed in editions:
            out += f"## {edition_label(ed)}\n\n"
            if not ed.articles:
                out += "> *本版无文章内容*\n\n---\n\n"
                continue
            for art in ed.articles:
                if is_full(art):
                    for line in md_article(art):
                        out += line
        return out

    def _md_header(self, d: date, total_editions: int, total_articles: int) -> str:
        weekday = weekday_cn_full(d)
        s = f"# {self.name} · {d.year:04d}年{d.month:02d}月{d.day:02d}日（{weekday}）\n\n"
        s += f"> 来源：[{self.name}电子版]({self.base_url})"
        if total_editions > 0:
            s += f" · 共 {total_editions} 版 {total_articles} 篇"
        s += "\n\n---\n\n"
        return s

    def _md_toc(
        self,
        editions: list[Edition],
        ed_anchors: list[str],
        art_anchors: list[list[str]],
    ) -> list[str]:
        lines = ["## 版面目录\n\n"]
        for ed, ed_anchor, arts in zip(editions, ed_anchors, art_anchors):
            label = edition_label(ed)
            count = len(ed.articles)
            count_str = f"（{count}篇）" if count > 0 else ""
            lines.append(f"- **[{label}](#{ed_anchor})**{count_str}\n")
            for art, art_anchor in zip(ed.articles, arts):
                title = art_title(art)
                if not title:
                    lines.append(f"  - [（无标题）](#{art_anchor})\n")
                else:
                    lines.append(f"  - [{title}](#{art_anchor})\n")
        lines.append("\n---\n\n")
        return lines

    # ------------------------------------------------------------------ #
    # 纯文本
    # ------------------------------------------------------------------ #
    def plain(self, d: date, editions: list[Edition]) -> str:
        out = f"{self.name}\n{d.year:04d}年{d.month:02d}月{d.day:02d}日\n\n"
        out += SEPARATOR + "\n\n"
        if not editions:
            out += "该日无报纸或无法访问\n"
            return out
        for ed in editions:
            out += f"【{edition_label(ed)}】\n\n"
            if not ed.articles:
                out += "  (本版无文章内容)\n\n"
                continue
            for art in ed.articles:
                if not is_full(art):
                    continue
                a: Article = art
                if a.yinti:
                    out += f"  [{a.yinti}]\n"
                out += f"  ■ {a.title}\n"
                if a.subtitle:
                    out += f"    [{a.subtitle}]\n"
                if a.author:
                    out += f"    {a.author}\n"
                if a.image_desc:
                    out += f"    [图] {a.image_desc}\n"
                out += "\n"
                for p in a.paragraphs:
                    p = p.strip()
                    if p:
                        out += f"    {p}\n\n"
                out += DIVIDER + "\n\n"
            out += "\n"
        return out


# ---------------------------------------------------------------------- #
# 辅助函数
# ---------------------------------------------------------------------- #
def count_full(editions: list[Edition]) -> int:
    """统计已抓取为完整文章的篇数。"""
    return sum(1 for ed in editions for item in ed.articles if is_full(item))


def edition_label(ed: Edition) -> str:
    """版面标题：第NN版（· 版名）。"""
    if not ed.name:
        return f"第{ed.num:02d}版"
    return f"第{ed.num:02d}版 · {ed.name}"


def anchors(
    editions: list[Edition],
) -> tuple[list[str], list[list[str]]]:
    """生成版面与文章的 Markdown 锚点（重复标题追加 -1、-2…）。"""
    ed_out: list[str] = []
    art_out: list[list[str]] = []
    seen_ed: dict[str, int] = {}
    seen_art: dict[str, int] = {}
    for ed in editions:
        label = edition_label(ed)
        a = md_anchor(label)
        n = seen_ed.get(a, 0)
        ed_out.append(a if n == 0 else f"{a}-{n}")
        seen_ed[a] = n + 1

        arts: list[str] = []
        for item in ed.articles:
            title = art_title(item)
            key = "section" if not title else title
            a = md_anchor(key)
            n = seen_art.get(a, 0)
            arts.append(a if n == 0 else f"{a}-{n}")
            seen_art[a] = n + 1
        art_out.append(arts)
    return ed_out, art_out


def md_anchor(text: str) -> str:
    """转 Markdown 锚点：小写、去特殊字符、空白转 -。"""
    lower = text.lower()
    s = RE_ANCHOR.sub("", lower)
    s = RE_SPACE.sub("-", s).strip("-")
    return s if s else "section"


def md_article(a: Article) -> list[str]:
    """单篇文章的 Markdown 行列表。"""
    lines: list[str] = []
    if a.yinti:
        lines.append(f"*{a.yinti}*\n\n")
    title = a.title if a.title else "（无标题）"
    lines.append(f"### {title}\n\n")
    if a.subtitle:
        lines.append(f"**{a.subtitle}**\n\n")
    meta: list[str] = []
    if a.author:
        meta.append(a.author)
    if a.url:
        meta.append(f"[原文]({a.url})")
    if meta:
        lines.append(f"> {' · '.join(meta)}\n\n")
    if a.image_desc:
        lines.append(f"[图] {a.image_desc}\n\n")
    if not a.paragraphs:
        lines.append("> *（内容获取失败）*\n\n")
    else:
        for p in a.paragraphs:
            p = p.strip()
            if p:
                lines.append(f"　　{p}\n\n")
    lines.append("---\n\n")
    return lines
