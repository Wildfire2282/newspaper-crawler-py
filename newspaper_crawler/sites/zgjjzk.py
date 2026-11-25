"""China Economic Weekly (中国经济周刊) crawler.

Base URL: https://paper.people.com.cn/zgjjzk

The magazine shares the People's Daily "pc" template with 人民论坛: the first
layout page already lists every edition (``h1`` name + ``ul#NN`` article links),
so one layout request discovers the whole issue.

Layout:  {base}/pc/layout/YYYYMM/DD/node_NN.html
Article: {base}/pc/content/YYYYMM/DD/content_{id}.html

It is a semimonthly magazine; non-publication dates 404 and map to an empty day.
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from ..base import SiteCrawler
from ..http import HttpSession
from ..models import Article, ArticleRef, Edition
from .people_pc import fetch_pc_article, get_magazine_editions

BASE_URL = "https://paper.people.com.cn/zgjjzk"


class JingjiZhoukanCrawler(SiteCrawler):
    """China Economic Weekly crawler."""

    crawler_id = "zgjjzk"
    name = "中国经济周刊"
    base_url = BASE_URL
    aliases = ["jjzk"]

    def get_editions(self, http: HttpSession, d: date) -> list[Edition]:
        return get_magazine_editions(http, BASE_URL, d)

    def fetch_article(
        self, http: HttpSession, aref: ArticleRef, d: date
    ) -> Optional[Article]:
        # The date argument is ignored (one article template serves every issue).
        return fetch_pc_article(http, aref)
