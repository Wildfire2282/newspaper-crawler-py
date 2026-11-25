"""Site parser tests: offline HTML snippets covering each site's new/old system paths."""

from datetime import date
from typing import Optional

import pytest

from newspaper_crawler.base import EmptyIndexError
from newspaper_crawler.models import ArticleRef
from newspaper_crawler.sites import dzrb, gmrb, jjrb, rmlt, rmrb, rmrbhwb, rmzk, zgjjzk


class _FakeHttp:
    """Return page bodies by URL (missing URL -> None) and record every requested URL,
    so tests can assert on de-duplication and page discovery.
    """

    concurrency = 8  # fetch_texts reads the per-host budget from the session

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get_text(self, url: str, silent_404: bool = False) -> Optional[str]:
        self.calls.append(url)
        return self.pages.get(url)


def _page(url: str, html: str) -> tuple[str, str]:
    return url, html


# ---------------------------------------------------------------- People's Daily (new)


def test_rmrb_new_editions_and_article():
    d = date(2026, 9, 10)
    layout = f"{rmrb.BASE_URL}/pc/layout/202609/10/node_01.html"
    article = f"{rmrb.BASE_URL}/pc/layout/202609/10/content_100.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><body>
                      <a href="node_01.html">01版：要闻</a>
                      <a href="content_100.html">主标题甲</a>
                    </body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>页面标题</title></head><body>
                      <div class="article">
                        <h3>引题</h3>
                        <h1>主标题甲</h1>
                        <h2>副标题乙</h2>
                        <p class="sec">本报记者张三 《人民日报》</p>
                      </div>
                      <div id="ozoom"><p>第一段</p><p>第二段</p></div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = rmrb.RenminCrawler()
    editions = site.get_editions(http, d)
    assert len(editions) == 1
    assert (editions[0].num, editions[0].name) == (1, "要闻")
    assert [a.url for a in editions[0].articles] == [article]

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "主标题甲"
    assert art.yinti == "引题"
    assert art.subtitle == "副标题乙"
    assert art.author == "本报记者张三"
    assert art.paragraphs == ["第一段", "第二段"]


# ---------------------------------------------------------------- People's Daily (old)


def test_rmrb_old_editions_and_article():
    d = date(2024, 11, 30)
    layout = f"{rmrb.BASE_URL}/html/2024-11/30/nbs.D110000renmrb_01.htm"
    article = f"{rmrb.BASE_URL}/html/2024-11/30/nw.D110000renmrb_20241130_1-01.htm"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><head><title>第01版:要闻_人民日报</title></head><body>
                      <a href="nw.D110000renmrb_20241130_1-01.htm">标题一<br>副题</a>
                    </body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head>
                      <meta name="description" content="老文章标题">
                    </head><body>
                      <div class="text_c"><p>段落一</p><p>段落二</p></div>
                      <span class="lai">本报记者李四</span>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = rmrb.RenminCrawler()
    editions = site.get_editions(http, d)
    assert len(editions) == 1
    assert editions[0].name == "要闻"
    assert editions[0].articles[0].title == "标题一 副题"  # <br> → 空格

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "老文章标题"
    assert art.author == "本报记者李四"
    assert art.paragraphs == ["段落一", "段落二"]


# ---------------------------------------------------------------- People's Tribune


def test_rmlt_layout_editions_and_article():
    d = date(2026, 8, 17)
    layout = f"{rmlt.BASE_URL}/pc/layout/202608/17/node_01.html"
    article = f"{rmlt.BASE_URL}/pc/content/202608/17/content_30185900.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><body><div class="news">
                      <h1><img src="ling.gif" />习近平新时代中国特色社会主义思想研究</h1>
                      <ul id="01">
                        <li><a href="../../../content/202608/17/content_30185900.html">
                          从学理层面深刻领会习近平党建思想的重大意义
                        </a></li>
                      </ul>
                      <h1>特别策划</h1>
                      <ul id="02">
                        <li><a href="../../../content/202608/17/content_30185901.html">标题乙</a></li>
                      </ul>
                    </div></body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>页面标题-人民网</title></head><body>
                      <div class="article">
                        <h3>引题</h3>
                        <h1><p>从学理层面深刻领会习近平党建思想的重大意义</p></h1>
                        <h2>副标题乙</h2>
                        <p class="sec">原中央党史研究室主任 欧阳淞
                          <span class="date">《人民论坛》（2026年08月17日 第 01版）</span>
                        </p>
                      </div>
                      <div id="ozoom"><p>第一段</p><p>第二段</p></div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = rmlt.RenminLuntanCrawler()
    editions = site.get_editions(http, d)
    assert [(e.num, e.name) for e in editions] == [
        (1, "习近平新时代中国特色社会主义思想研究"),
        (2, "特别策划"),
    ]
    assert editions[0].articles[0].url == article
    assert editions[1].articles[0].title == "标题乙"

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "从学理层面深刻领会习近平党建思想的重大意义"
    assert art.yinti == "引题"
    assert art.subtitle == "副标题乙"
    assert art.author == "原中央党史研究室主任 欧阳淞"
    assert art.paragraphs == ["第一段", "第二段"]
    assert len(http.calls) == 2  # 整个合刊只需一次版面请求


def test_rmlt_edition_name_drops_a_page_number_prefix():
    d = date(2026, 8, 17)
    layout = f"{rmlt.BASE_URL}/pc/layout/202608/17/node_01.html"
    http = _FakeHttp(
        {
            layout: '<div class="news"><h1>02版：特别策划</h1><ul id="02">'
            '<li><a href="../../../content/202608/17/content_2.html">稿件</a></li>'
            "</ul></div>"
        }
    )

    editions = rmlt.RenminLuntanCrawler().get_editions(http, d)

    assert editions[0].name == "特别策划"


# ---------------------------------------------------------------- People's Weekly


def test_rmzk_layout_editions_and_article():
    d = date(2026, 11, 6)
    layout = f"{rmzk.BASE_URL}/pc/layout/202611/06/node_01.html"
    article = f"{rmzk.BASE_URL}/pc/content/202611/06/content_30191064.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><body><div class="news">
                      <h1><img src="ling.gif" />学习路上</h1>
                      <ul id="01">
                        <li><a href="../../../content/202611/06/content_30191064.html">
                          新闻日历
                        </a></li>
                      </ul>
                      <h1><img src="ling.gif" />学习贯彻习近平党建思想</h1>
                      <ul id="02">
                        <li><a href="../../../content/202611/06/content_30191067.html">
                          坚持健全上下贯通、执行有力的组织体系
                        </a></li>
                      </ul>
                    </div></body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>新闻日历-人民网</title></head><body>
                      <div class="article">
                        <h3></h3>
                        <h1><p> 新闻日历 </p></h1>
                        <h2></h2>
                        <p class="sec">
                          <span class="date">《人民周刊》（2026年11月06日 第 01版）</span>
                        </p>
                      </div>
                      <div id="ozoom"><p>第一段</p><p>第二段</p></div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = rmzk.RenminZhoukanCrawler()
    editions = site.get_editions(http, d)
    assert [(e.num, e.name) for e in editions] == [
        (1, "学习路上"),
        (2, "学习贯彻习近平党建思想"),
    ]
    assert editions[0].articles[0].url == article

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "新闻日历"
    assert art.author == ""  # the sec line holds only the date
    assert art.paragraphs == ["第一段", "第二段"]


# ---------------------------------------------------------------- China Economic Weekly


def test_zgjjzk_layout_editions_and_article():
    d = date(2026, 9, 15)
    layout = f"{zgjjzk.BASE_URL}/pc/layout/202609/15/node_01.html"
    article = f"{zgjjzk.BASE_URL}/pc/content/202609/15/content_30191719.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><body><div class="news">
                      <h1><img src="ling.gif" />封面故事</h1>
                      <ul id="01">
                        <li><a href="../../../content/202609/15/content_30191719.html">
                          拓宽服务消费新场景
                        </a></li>
                      </ul>
                    </div></body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>拓宽服务消费新场景-人民网</title></head><body>
                      <div class="article">
                        <h3></h3>
                        <h1><p> 拓宽服务消费新场景 </p></h1>
                        <h2></h2>
                        <p class="sec">本刊评论员
                          <span class="date">《中国经济周刊》（2026年09月15日 第 01版）</span>
                        </p>
                      </div>
                      <div id="ozoom"><p>段一</p><p>段二</p></div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = zgjjzk.JingjiZhoukanCrawler()
    editions = site.get_editions(http, d)
    assert [(e.num, e.name) for e in editions] == [(1, "封面故事")]

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "拓宽服务消费新场景"
    assert art.author == "本刊评论员"
    assert art.paragraphs == ["段一", "段二"]


# ---------------------------------------------------------------- People's Daily Overseas Edition


def test_rmrbhwb_node_editions_and_article():
    d = date(2026, 11, 25)
    base = f"{rmrbhwb.BASE_URL}/pc/layout/202611/25"
    page1 = f"{base}/node_01.html"
    page2 = f"{base}/node_02.html"
    article = f"{rmrbhwb.BASE_URL}/pc/content/202611/25/content_30193023.html"
    article2 = f"{rmrbhwb.BASE_URL}/pc/content/202611/25/content_30193029.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    page1,
                    """
                    <html><body>
                      <div class="swiper-slide">
                        <a id="pageLink" href="node_01.html">01版：要闻</a>
                      </div>
                      <div class="swiper-slide">
                        <a id="pageLink" href="node_02.html">02版：要闻</a>
                      </div>
                      <div class="news"><ul class="news-list">
                        <li><a href="../../../content/202611/25/content_30193023.html">
                          “以党章为根本”
                        </a></li>
                      </ul></div>
                      <div class="down">
                        <a href="../../../content/202611/25/content_30193023.html">
                          第01版：要闻 PDF下载
                        </a>
                      </div>
                    </body></html>
                    """,
                ),
                _page(
                    page2,
                    """
                    <html><body><div class="news"><ul class="news-list">
                      <li><a href="../../../content/202611/25/content_30193029.html">
                        首个中外联合飞行乘组今日出征太空
                      </a></li>
                    </ul></div></body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>“以党章为根本”-人民网</title></head><body>
                      <div class="article">
                        <h3><p> 微观察 </p></h3>
                        <h1><p> “以党章为根本” </p></h1>
                        <h2></h2>
                        <p class="sec">本报记者  张  洋
                          <span class="date">《人民日报海外版》（2026年11月25日 第 01 版）</span>
                        </p>
                      </div>
                      <div id="ozoom"><p>第一段</p><p>第二段</p></div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = rmrbhwb.RenminHaiwaibanCrawler()
    editions = site.get_editions(http, d)
    assert [(e.num, e.name) for e in editions] == [(1, "要闻"), (2, "要闻")]
    # The "PDF下载" anchor points at the same content URL; it must not duplicate.
    assert [a.url for a in editions[0].articles] == [article]
    assert [a.url for a in editions[1].articles] == [article2]
    assert http.calls.count(page1) == 1  # navigation and edition 1 share one request

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "“以党章为根本”"
    assert art.yinti == "微观察"
    assert art.subtitle == ""
    assert art.author == "本报记者 张 洋"
    assert art.paragraphs == ["第一段", "第二段"]


# ---------------------------------------------------------------- Guangming Daily (new)


def test_gmrb_new_editions_and_article():
    d = date(2026, 1, 5)
    layout = f"{gmrb.BASE_URL}/gmrb/html/layout/202601/05/node_01.html"
    article = f"{gmrb.BASE_URL}/gmrb/html/layout/202601/05/content_1.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><body>
                      <div class="m-type">要闻</div>
                      <div class="m-title-list"><div class="m-list-wrap"><ul>
                        <li><a href="content_1.html"><p>光明标题甲</p></a></li>
                      </ul></div></div>
                    </body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>光明标题甲-光明网</title></head><body>
                      <div class="m-article-main"><p>段落A</p><p>段落B</p></div>
                      <div class="m-article-info">光明日报记者王五</div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = gmrb.GuangmingCrawler()
    editions = site.get_editions(http, d)
    assert len(editions) == 1
    assert (editions[0].num, editions[0].name) == (1, "要闻")
    assert editions[0].articles[0].url == article

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "光明标题甲"  # 去掉 "-光明网" 后缀
    assert art.author == "光明日报记者王五"
    assert art.paragraphs == ["段落A", "段落B"]


# ---------------------------------------------------------------- Guangming Daily (old)


def test_gmrb_old_editions_and_article():
    d = date(2025, 12, 31)
    layout = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nbs.D110000gmrb_01.htm"
    article = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nw.D110000gmrb_20251231_1-01.htm"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><head><title>第01版:要闻_光明日报</title></head><body>
                      <a href="nw.D110000gmrb_20251231_1-01.htm">光明旧标题</a>
                    </body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head>
                      <meta name="description" content="光明旧文章标题">
                    </head><body>
                      <div class="text_c"><p>旧段落</p></div>
                      <span class="lai">光明日报记者赵六</span>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = gmrb.GuangmingCrawler()
    editions = site.get_editions(http, d)
    assert len(editions) == 1
    assert editions[0].name == "要闻"
    assert editions[0].articles[0].url == article

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "光明旧文章标题"
    assert art.author == "光明日报记者赵六"
    assert art.paragraphs == ["旧段落"]


# ---------------------------------------------------------------- Economic Daily


def test_jjrb_editions_and_article():
    d = date(2026, 9, 10)
    layout = f"{jjrb.BASE_URL}/layout/202609/10/node_01.html"
    article = f"{jjrb.BASE_URL}/content/202609/10/content_55.html"
    http = _FakeHttp(
        dict(
            [
                _page(
                    layout,
                    """
                    <html><body>
                      <ul id="layoutlist">
                        <li><a href="node_01.html">第01版：要闻</a></li>
                      </ul>
                      <ul id="articlelist">
                        <li><a href="content_55.html"><p>经济标题甲</p></a></li>
                      </ul>
                    </body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>页面标题</title></head><body>
                      <h2 id="Title"><p>经济主标题</p></h2>
                      <div id="SubTitle"><p>经济副题</p></div>
                      <div id="Author">经济日报记者孙七</div>
                      <div id="ozoom"><p>段一</p><p>段二</p></div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = jjrb.JingjiCrawler()
    editions = site.get_editions(http, d)
    assert len(editions) == 1
    assert (editions[0].num, editions[0].name) == (1, "要闻")
    ref = editions[0].articles[0]
    assert ref.url == article

    art = site.fetch_article(http, ref, d)
    assert art is not None
    assert art.title == "经济主标题"
    assert art.subtitle == "经济副题"
    assert art.author == "经济日报记者孙七"
    assert art.paragraphs == ["段一", "段二"]


# ---------------------------------------------------------------- Dazhong Daily


def test_dzrb_editions_and_article():
    d = date(2026, 9, 10)
    index = f"{dzrb.BASE_URL}/content/20260910/PageArticleIndexWZ.htm"
    article = f"{dzrb.BASE_URL}/content/20260910/content_1.htm"
    http = _FakeHttp(
        dict(
            [
                _page(
                    index,
                    """
                    <html><body>
                      <table><tr><td class="font_bai">[01]: 要闻</td></tr></table>
                      <div id="partTitleDiv1">
                        <a href="content_1.htm">大众标题甲</a>
                      </div>
                    </body></html>
                    """,
                ),
                _page(
                    article,
                    """
                    <html><head><title>页面标题</title></head><body>
                      <h2 class="yinti"><span>大众引题</span></h2>
                      <h1 class="biaoti">大众主标题</h1>
                      <h2 class="futi"><span>大众副题</span></h2>
                      <div id="author">大众记者周八</div>
                      <div class="imagedesc">图片说明</div>
                      <div id="contenttext">第一段<br>第二段</div>
                    </body></html>
                    """,
                ),
            ]
        )
    )

    site = dzrb.DazhongCrawler()
    editions = site.get_editions(http, d)
    assert len(editions) == 1
    assert (editions[0].num, editions[0].name) == (1, "要闻")
    assert editions[0].articles[0].url == article

    art = site.fetch_article(http, editions[0].articles[0], d)
    assert art is not None
    assert art.title == "大众主标题"
    assert art.yinti == "大众引题"
    assert art.subtitle == "大众副题"
    assert art.author == "大众记者周八"
    assert art.image_desc == "图片说明"
    assert art.paragraphs == ["第一段", "第二段"]


def test_sites_return_empty_when_index_missing():
    """All registered sites return an empty list when the index page is unreachable."""
    http = _FakeHttp({})
    d = date(2026, 9, 10)
    for site in (
        rmrb.RenminCrawler(),
        rmlt.RenminLuntanCrawler(),
        rmzk.RenminZhoukanCrawler(),
        rmrbhwb.RenminHaiwaibanCrawler(),
        zgjjzk.JingjiZhoukanCrawler(),
        gmrb.GuangmingCrawler(),
        jjrb.JingjiCrawler(),
        dzrb.DazhongCrawler(),
    ):
        assert site.get_editions(http, d) == []


def test_sites_raise_empty_index_when_structure_unrecognized():
    """A retrieved-but-unrecognized page (site redesign) must raise EmptyIndexError
    rather than silently returning an empty list.
    """
    d = date(2026, 9, 10)
    changed = "<html><body><p>改版了</p></body></html>"
    cases = [
        (
            rmrb.RenminCrawler(),
            {f"{rmrb.BASE_URL}/pc/layout/202609/10/node_01.html": changed},
        ),
        (
            rmlt.RenminLuntanCrawler(),
            {f"{rmlt.BASE_URL}/pc/layout/202609/10/node_01.html": changed},
        ),
        (
            rmzk.RenminZhoukanCrawler(),
            {f"{rmzk.BASE_URL}/pc/layout/202609/10/node_01.html": changed},
        ),
        (
            zgjjzk.JingjiZhoukanCrawler(),
            {f"{zgjjzk.BASE_URL}/pc/layout/202609/10/node_01.html": changed},
        ),
        (
            rmrbhwb.RenminHaiwaibanCrawler(),
            {f"{rmrbhwb.BASE_URL}/pc/layout/202609/10/node_01.html": changed},
        ),
        (
            gmrb.GuangmingCrawler(),
            {f"{gmrb.BASE_URL}/gmrb/html/layout/202609/10/node_01.html": changed},
        ),
        (
            jjrb.JingjiCrawler(),
            {f"{jjrb.BASE_URL}/layout/202609/10/node_01.html": changed},
        ),
        (
            dzrb.DazhongCrawler(),
            {f"{dzrb.BASE_URL}/content/20260910/PageArticleIndexWZ.htm": changed},
        ),
    ]
    for site, pages in cases:
        with pytest.raises(EmptyIndexError):
            site.get_editions(_FakeHttp(pages), d)


def test_gmrb_old_article_title_treats_br_as_space():
    d = date(2025, 12, 31)
    layout = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nbs.D110000gmrb_01.htm"
    http = _FakeHttp(
        {
            layout: "<title>第01版:要闻_光明日报</title>"
            '<a href="nw.D110000gmrb_x-01.htm">主标题<br>副标题</a>'
        }
    )

    editions = gmrb.GuangmingCrawler().get_editions(http, d)

    assert editions[0].articles[0].title == "主标题 副标题"


# ---------------------------------------------------------------- request de-dup / discovery


def test_rmrb_new_does_not_refetch_layout_page_one():
    d = date(2026, 9, 10)
    layout = f"{rmrb.BASE_URL}/pc/layout/202609/10/node_01.html"
    http = _FakeHttp(
        {
            layout: '<a href="node_01.html">01版：要闻</a>'
            '<a href="content_9.html">稿件</a>'
        }
    )

    editions = rmrb.RenminCrawler().get_editions(http, d)

    assert [e.num for e in editions] == [1]
    assert http.calls.count(layout) == 1  # 导航解析与版面抓取共用同一份页面


def test_jjrb_does_not_refetch_layout_page_one():
    d = date(2026, 9, 10)
    layout = f"{jjrb.BASE_URL}/layout/202609/10/node_01.html"
    http = _FakeHttp(
        {
            layout: '<ul id="layoutlist"><li><a href="node_01.html">第01版：要闻</a></li></ul>'
            '<ul id="articlelist"><li><a href="content_9.html"><p>稿件</p></a></li></ul>'
        }
    )

    editions = jjrb.JingjiCrawler().get_editions(http, d)

    assert [e.num for e in editions] == [1]
    assert http.calls.count(layout) == 1


def _gmrb_new_page(num: int, name: str, title: str) -> str:
    return (
        f'<div class="m-type">{name}</div>'
        f'<div class="m-title-list"><div class="m-list-wrap"><ul>'
        f'<li><a href="content_{num}.html"><p>{title}</p></a></li></ul></div></div>'
    )


def test_gmrb_new_fetches_only_pages_found_in_nav():
    d = date(2026, 1, 5)
    base = f"{gmrb.BASE_URL}/gmrb/html/layout/202601/05"
    pages = {
        f"{base}/node_01.html": _gmrb_new_page(1, "要闻", "标题一")
        + '<a href="node_02.html">02版</a><a href="node_03.html">03版</a>',
        f"{base}/node_02.html": _gmrb_new_page(2, "经济", "标题二"),
        f"{base}/node_03.html": _gmrb_new_page(3, "文化", "标题三"),
    }
    http = _FakeHttp(pages)

    editions = gmrb.GuangmingCrawler().get_editions(http, d)

    assert [e.num for e in editions] == [1, 2, 3]
    assert len(http.calls) == 3  # 只抓发现到的 3 个版面，未盲探 2..20


def test_gmrb_old_falls_back_to_probing_without_nav_links():
    d = date(2025, 12, 31)
    layout1 = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nbs.D110000gmrb_01.htm"
    http = _FakeHttp(
        {
            layout1: "<title>第01版:要闻_光明日报</title>"
            '<a href="nw.D110000gmrb_x-01.htm">稿件</a>'
        }
    )

    editions = gmrb.GuangmingCrawler().get_editions(http, d)

    assert [e.num for e in editions] == [1]
    assert len(http.calls) == 20  # 无导航时回退为第 1 版 + 顺序探测 2..20
    assert f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nbs.D110000gmrb_20.htm" in http.calls


def test_rmrb_old_fetches_only_pages_found_in_nav():
    d = date(2024, 11, 30)
    layout1 = f"{rmrb.BASE_URL}/html/2024-11/30/nbs.D110000renmrb_01.htm"
    layout2 = f"{rmrb.BASE_URL}/html/2024-11/30/nbs.D110000renmrb_02.htm"
    page1 = (
        "<title>第01版:要闻_人民日报</title>"
        '<a href="nbs.D110000renmrb_02.htm">02版</a>'
        '<a href="nw.D110000renmrb_20241130_1-01.htm">稿一</a>'
    )
    page2 = (
        "<title>第02版:经济_人民日报</title>"
        '<a href="nw.D110000renmrb_20241130_2-02.htm">稿二</a>'
    )
    http = _FakeHttp({layout1: page1, layout2: page2})

    editions = rmrb.RenminCrawler().get_editions(http, d)

    assert [e.num for e in editions] == [1, 2]
    assert len(http.calls) == 2  # 只抓第 1、2 版，未盲探 3..20


# ---------------------------------------------------------------- edition names
# Live pages: the old People's Daily <title> is "人民日报-人民网" (no page info), and
# the new Guangming .m-type is "01版:头版". A parsed name must not repeat the label that
# edition_label already adds ("第01版 · 第01版" / "第01版 · 01版:头版" are wrong).


def test_rmrb_old_edition_name_comes_from_the_page_banner():
    d = date(2024, 11, 30)
    layout = f"{rmrb.BASE_URL}/html/2024-11/30/nbs.D110000renmrb_01.htm"
    http = _FakeHttp(
        {
            layout: "<title>人民日报-人民网</title>"
            '<p class="left ban">第01版:要闻</p>'
            '<a href="nw.D110000renmrb_20241130_1-01.htm">稿件</a>'
        }
    )

    editions = rmrb.RenminCrawler().get_editions(http, d)

    assert editions[0].name == "要闻"


def test_rmrb_old_edition_name_is_empty_when_the_page_has_none():
    d = date(2024, 11, 30)
    layout = f"{rmrb.BASE_URL}/html/2024-11/30/nbs.D110000renmrb_01.htm"
    http = _FakeHttp(
        {
            layout: "<title>人民日报-人民网</title>"
            '<a href="nw.D110000renmrb_20241130_1-01.htm">稿件</a>'
        }
    )

    editions = rmrb.RenminCrawler().get_editions(http, d)

    # Blank, not "第01版": the label already adds that, and would print it twice.
    assert editions[0].name == ""


def test_gmrb_new_edition_name_drops_the_number_prefix():
    d = date(2026, 1, 5)
    layout = f"{gmrb.BASE_URL}/gmrb/html/layout/202601/05/node_01.html"
    http = _FakeHttp(
        {
            layout: '<div class="m-type"><span>01版:</span><span>头版</span></div>'
            '<div class="m-title-list"><div class="m-list-wrap"><ul>'
            '<li><a href="content_1.html"><p>标题一</p></a></li></ul></div></div>'
        }
    )

    editions = gmrb.GuangmingCrawler().get_editions(http, d)

    assert editions[0].name == "头版"


def test_dzrb_article_without_contenttext_has_no_body():
    """Page furniture must not be mistaken for body text on an unknown template."""
    d = date(2026, 9, 10)
    article = f"{dzrb.BASE_URL}/content/20260910/content_2.htm"
    http = _FakeHttp(
        {
            article: '<h1 class="biaoti">图片报道</h1>'
            '<div id="nav"><p>首页</p><p>版权声明</p></div>'
        }
    )

    art = dzrb.DazhongCrawler().fetch_article(
        http, ArticleRef(title="图片报道", url=article), d
    )

    assert art is not None
    assert art.paragraphs == []


# ---------------------------------------------------------------- Legacy shared parser
# rmrb and gmrb old-system article pages share one parser (sites/legacy.py); these
# tests pin its per-site knobs through each site's fetch_article.


def test_legacy_meta_title_c_c_body_and_author():
    """Meta description wins as the title, .c_c carries the body, and each site's
    author selector works; rmrb keeps the "-人民网" suffix, gmrb strips its own.
    """
    d_rmrb = date(2024, 11, 30)
    rmrb_url = f"{rmrb.BASE_URL}/html/2024-11/30/nw.D110000renmrb_20241130_1-02.htm"
    d_gmrb = date(2025, 12, 31)
    gmrb_url = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nw.D110000gmrb_20251231_1-02.htm"
    http = _FakeHttp(
        {
            rmrb_url: '<meta name="description" content="标题甲-人民网">'
            '<div class="c_c"><p>正文一</p></div>'
            '<span class="author">本报记者某某</span>',
            gmrb_url: '<meta name="description" content="标题乙-光明网">'
            '<div class="c_c"><p>正文二</p></div>'
            '<span class="lai">光明日报记者某某</span>',
        }
    )

    art_rmrb = rmrb.RenminCrawler().fetch_article(
        http, ArticleRef(title="原标题甲", url=rmrb_url), d_rmrb
    )
    art_gmrb = gmrb.GuangmingCrawler().fetch_article(
        http, ArticleRef(title="原标题乙", url=gmrb_url), d_gmrb
    )

    assert art_rmrb is not None
    assert art_rmrb.title == "标题甲-人民网"  # rmrb 不去除站名后缀
    assert art_rmrb.author == "本报记者某某"  # .author 命中 rmrb 的选择器
    assert art_rmrb.paragraphs == ["正文一"]

    assert art_gmrb is not None
    assert art_gmrb.title == "标题乙"  # gmrb 去除 "-光明网" 后缀
    assert art_gmrb.author == "光明日报记者某某"
    assert art_gmrb.paragraphs == ["正文二"]


def test_legacy_title_only_fallback_without_body():
    """No meta description, no usable <title>, no body container: the reference
    title survives and the article has no paragraphs.
    """
    d_rmrb = date(2024, 11, 30)
    rmrb_url = f"{rmrb.BASE_URL}/html/2024-11/30/nw.D110000renmrb_20241130_1-03.htm"
    d_gmrb = date(2025, 12, 31)
    gmrb_url = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nw.D110000gmrb_20251231_1-03.htm"
    http = _FakeHttp(
        {
            rmrb_url: "<html><body><p>导航文字</p></body></html>",
            gmrb_url: "<html><body><p>导航文字</p></body></html>",
        }
    )

    art_rmrb = rmrb.RenminCrawler().fetch_article(
        http, ArticleRef(title="仅标题甲", url=rmrb_url), d_rmrb
    )
    art_gmrb = gmrb.GuangmingCrawler().fetch_article(
        http, ArticleRef(title="仅标题乙", url=gmrb_url), d_gmrb
    )

    assert art_rmrb is not None
    assert art_rmrb.title == "仅标题甲"
    assert art_rmrb.author == ""
    assert art_rmrb.paragraphs == []

    assert art_gmrb is not None
    assert art_gmrb.title == "仅标题乙"
    assert art_gmrb.author == ""
    assert art_gmrb.paragraphs == []


def test_legacy_gmrb_author_citation_only_becomes_empty():
    """Live gmrb 2025-12-31 pages put only `作者：\n《光明日报》（ 2025年12月31日 01版）`
    in `.lai`; that is a citation, not a byline, so the author is empty.
    """
    d = date(2025, 12, 31)
    url = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nw.D110000gmrb_20251231_1-05.htm"
    http = _FakeHttp(
        {
            url: '<meta name="description" content="无署名标题">'
            '<div class="text_c"><p>段落一</p><p>段落二</p></div>'
            '<span class="lai">作者：\n《光明日报》（ 2025年12月31日 01版）</span>'
        }
    )

    art = gmrb.GuangmingCrawler().fetch_article(
        http, ArticleRef(title="原标题", url=url), d
    )

    assert art is not None
    assert art.author == ""
    assert art.paragraphs == ["段落一", "段落二"]


def test_legacy_gmrb_author_keeps_real_byline_before_citation():
    """`作者：张三\n《光明日报》（…）` yields just the name."""
    d = date(2025, 12, 31)
    url = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nw.D110000gmrb_20251231_1-06.htm"
    http = _FakeHttp(
        {
            url: '<meta name="description" content="署名标题">'
            '<div class="text_c"><p>段落一</p></div>'
            '<span class="lai">作者：张三\n《光明日报》（ 2025年12月31日 02版）</span>'
        }
    )

    art = gmrb.GuangmingCrawler().fetch_article(
        http, ArticleRef(title="原标题", url=url), d
    )

    assert art is not None
    assert art.author == "张三"
    assert art.paragraphs == ["段落一"]


def test_legacy_rmrb_author_without_prefix_is_unchanged():
    """`本报记者李四` carries no `作者：` prefix or citation, so it passes through."""
    d = date(2024, 11, 30)
    url = f"{rmrb.BASE_URL}/html/2024-11/30/nw.D110000renmrb_20241130_1-06.htm"
    http = _FakeHttp(
        {
            url: '<meta name="description" content="记者署名标题">'
            '<div class="text_c"><p>段落一</p></div>'
            '<span class="lai">本报记者李四</span>'
        }
    )

    art = rmrb.RenminCrawler().fetch_article(
        http, ArticleRef(title="原标题", url=url), d
    )

    assert art is not None
    assert art.author == "本报记者李四"
    assert art.paragraphs == ["段落一"]


def test_legacy_normal_article_still_parses():
    """The deeper container fallbacks (#ozoom for rmrb, .content for gmrb) keep
    yielding full articles through the shared parser.
    """
    d_rmrb = date(2024, 11, 30)
    rmrb_url = f"{rmrb.BASE_URL}/html/2024-11/30/nw.D110000renmrb_20241130_1-04.htm"
    d_gmrb = date(2025, 12, 31)
    gmrb_url = f"{gmrb.BASE_URL}/gmrb/html/2025-12/31/nw.D110000gmrb_20251231_1-04.htm"
    http = _FakeHttp(
        {
            rmrb_url: '<meta name="description" content="常规标题">'
            '<div id="ozoom"><p>第一段</p><p>第二段</p></div>'
            '<span class="lai">本报记者某某</span>',
            gmrb_url: '<meta name="description" content="常规标题">'
            '<div class="content"><p>段一</p><p>段二</p></div>'
            '<span class="lai">光明日报记者某某</span>',
        }
    )

    art_rmrb = rmrb.RenminCrawler().fetch_article(
        http, ArticleRef(title="常规标题", url=rmrb_url), d_rmrb
    )
    art_gmrb = gmrb.GuangmingCrawler().fetch_article(
        http, ArticleRef(title="常规标题", url=gmrb_url), d_gmrb
    )

    assert art_rmrb is not None
    assert art_rmrb.title == "常规标题"
    assert art_rmrb.author == "本报记者某某"
    assert art_rmrb.paragraphs == ["第一段", "第二段"]

    assert art_gmrb is not None
    assert art_gmrb.title == "常规标题"
    assert art_gmrb.author == "光明日报记者某某"
    assert art_gmrb.paragraphs == ["段一", "段二"]
