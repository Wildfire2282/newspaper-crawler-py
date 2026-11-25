"""People's Daily Overseas Edition (人民日报海外版) crawler.

Base URL: https://paper.people.com.cn/rmrbhwb

Unlike the magazines, this daily puts one edition per layout page. The page
navigation lists every edition ("NN版：NAME") and each page's ``div.news`` holds
that edition's articles.

Layout:  {base}/pc/layout/YYYYMM/DD/node_NN.html
Article: {base}/pc/content/YYYYMM/DD/content_{id}.html
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..base import SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from .people_pc import fetch_pc_article, get_node_editions

BASE_URL = "https://paper.people.com.cn/rmrbhwb"


class RenminHaiwaibanCrawler(SiteCrawler):
    """People's Daily Overseas Edition crawler."""

    crawler_id = "rmrbhwb"
    name = "人民日报海外版"
    base_url = BASE_URL
    aliases = ["hwb", "海外版"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        return get_node_editions(http, BASE_URL, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        # The date argument is ignored (one article template serves every issue).
        return fetch_pc_article(http, aref)
