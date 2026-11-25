"""People's Tribune (人民论坛) crawler.

Base URL: https://paper.people.com.cn/rmlt

The magazine shares the People's Daily "pc" template, but its first layout page
already lists every edition: each ``h1`` names an edition and the ``ul`` immediately
after it holds that edition's article links. One layout request is therefore enough
to discover the whole issue.

Layout:  {base}/pc/layout/YYYYMM/DD/node_NN.html
Article: {base}/pc/content/YYYYMM/DD/content_{id}.html
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..base import SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from .people_pc import fetch_pc_article, get_magazine_editions

BASE_URL = "https://paper.people.com.cn/rmlt"


class RenminLuntanCrawler(SiteCrawler):
    """People's Tribune crawler (the magazine, not the newspaper)."""

    crawler_id = "rmlt"
    name = "人民论坛"
    base_url = BASE_URL
    aliases = ["论坛", "luntan"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        return get_magazine_editions(http, BASE_URL, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        # The date argument is ignored (one article template serves every issue).
        return fetch_pc_article(http, aref)
