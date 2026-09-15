"""Site parser tests: offline HTML snippets covering each site's new/old system paths."""

from datetime import date
from typing import Optional

import pytest

from newspaper_crawler.base import EmptyIndexError
from newspaper_crawler.sites import dzrb, gmrb, jjrb, rmrb


class _FakeHttp:
    """Return page bodies by URL (missing URL -> None) and record every requested URL,
    so tests can assert on de-duplication and page discovery.
    """

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
    assert ref.extra == {"content_id": "55"}

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
    """All four sites return an empty list when the index page is unreachable."""
    http = _FakeHttp({})
    d = date(2026, 9, 10)
    for site in (
        rmrb.RenminCrawler(),
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
