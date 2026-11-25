"""formatter tests: Markdown/plain structure and anchor de-duplication."""

from datetime import date

from newspaper_crawler.formatter import (
    Formatter,
    anchors,
    count_full,
    edition_label,
    md_anchor,
)
from newspaper_crawler.models import Article, ArticleRef, Edition

D = date(2026, 9, 10)


def _editions() -> list[Edition]:
    return [
        Edition(
            num=1,
            name="要闻",
            articles=[
                Article(title="标题甲", paragraphs=["第一段"], author="记者甲"),
                Article(title="标题甲", paragraphs=["第二段"]),  # duplicate on purpose
                ArticleRef(title="未抓取", url="http://example.com/a"),
            ],
        ),
        Edition(num=2, name="", articles=[]),
    ]


def test_markdown_header_and_toc():
    md = Formatter("人民日报", "http://paper.people.com.cn/rmrb").markdown(
        D, _editions()
    )
    assert "# 人民日报 · 2026年09月10日（星期四）" in md
    assert "共 2 版 2 篇" in md
    assert "## 版面目录" in md
    assert "第01版 · 要闻" in md
    assert "第02版" in md
    assert "> *本版无文章内容*" in md


def test_markdown_duplicate_titles_get_unique_anchors():
    md = Formatter("人民日报", "http://paper.people.com.cn/rmrb").markdown(
        D, _editions()
    )
    assert "标题甲" in md
    assert "标题甲-1" in md


def test_markdown_empty_editions():
    md = Formatter("人民日报", "http://paper.people.com.cn/rmrb").markdown(D, [])
    assert "该日无报纸或无法访问" in md
    assert "共 0 版" not in md


def test_plain_format():
    txt = Formatter("人民日报", "http://paper.people.com.cn/rmrb").plain(D, _editions())
    assert txt.startswith("人民日报\n2026年09月10日")
    assert "【第01版 · 要闻】" in txt
    assert "■ 标题甲" in txt
    assert "记者甲" in txt
    assert "    第一段" in txt


def test_plain_empty_editions():
    txt = Formatter("人民日报", "http://paper.people.com.cn/rmrb").plain(D, [])
    assert "该日无报纸或无法访问" in txt


def test_unfetched_article_keeps_its_section_and_toc_anchor():
    md = Formatter("人民日报", "http://paper.people.com.cn/rmrb").markdown(
        D, _editions()
    )
    # The TOC links to #未抓取, so the body must contain that heading,
    # otherwise a failed fetch leaves a dangling link and no trace of the title.
    assert "  - [未抓取](#未抓取)" in md
    assert "### 未抓取" in md
    assert "（正文获取失败）" in md


def test_plain_reports_empty_body_article():
    editions = [Edition(num=1, name="要闻", articles=[Article(title="T", paragraphs=[])])]

    txt = Formatter("人民日报", "http://example.com").plain(D, editions)

    assert "■ T" in txt
    assert "（正文获取失败）" in txt


def test_plain_reports_empty_body_image_only_article():
    editions = [
        Edition(
            num=1,
            name="要闻",
            articles=[Article(title="图", image_desc="图片说明", paragraphs=[])],
        )
    ]

    txt = Formatter("人民日报", "http://example.com").plain(D, editions)

    assert "[图] 图片说明" in txt
    assert "（正文获取失败）" in txt


def test_plain_normal_article_has_no_failure_marker():
    editions = [
        Edition(num=1, name="要闻", articles=[Article(title="T", paragraphs=["第一段", "第二段"])])
    ]

    txt = Formatter("人民日报", "http://example.com").plain(D, editions)

    assert "    第一段" in txt
    assert "    第二段" in txt
    assert "（正文获取失败）" not in txt
    assert txt.endswith("  ----------------------------------------\n\n\n")


def test_plain_reports_unfetched_article():
    txt = Formatter("人民日报", "http://paper.people.com.cn/rmrb").plain(D, _editions())
    assert "■ 未抓取" in txt
    assert "（正文获取失败）" in txt


def test_count_full_counts_only_fetched_articles():
    assert count_full(_editions()) == 2


def test_anchors_structure_and_dedup():
    ed_anchors, art_anchors = anchors(_editions())
    assert ed_anchors == ["第01版-要闻", "第02版"]
    assert art_anchors[0][:2] == ["标题甲", "标题甲-1"]


def test_md_anchor_rules():
    assert md_anchor("Hello World") == "hello-world"
    assert md_anchor("") == "section"
    assert md_anchor("！！！") == "section"


def test_anchors_dedupe_editions_not_just_articles():
    """Two editions with the same label (e.g. a repeated nav entry) need distinct ids."""
    editions = [
        Edition(num=1, name="要闻", articles=[]),
        Edition(num=1, name="要闻", articles=[]),
    ]

    ed_anchors, _ = anchors(editions)

    assert ed_anchors == ["第01版-要闻", "第01版-要闻-1"]


def test_empty_title_anchor_matches_its_heading():
    """An untitled article's TOC link must point at its 「（无标题）」 heading.

    The heading text is 「（无标题）」, whose anchor slug is ``无标题``; keying the
    anchor off the md_anchor fallback (``section``) would emit a dangling link.
    """
    for item in (ArticleRef(title="", url="http://example.com/a"), Article(title="", paragraphs=["p"])):
        editions = [Edition(num=1, name="要闻", articles=[item])]
        md = Formatter("人民日报", "http://example.com").markdown(D, editions)
        assert "  - [（无标题）](#无标题)" in md
        assert "### （无标题）" in md
        assert "#section" not in md


def test_plain_reports_empty_title():
    editions = [
        Edition(num=1, name="要闻", articles=[ArticleRef(title="", url="http://example.com/a")])
    ]

    txt = Formatter("人民日报", "http://example.com").plain(D, editions)

    assert "■ （无标题）" in txt


def test_edition_label_strips_repeated_page_prefix():
    """Sources repeat the page number inside the name; the label must not."""
    assert edition_label(Edition(num=1, name="第01版：要闻", articles=[])) == "第01版 · 要闻"
    assert edition_label(Edition(num=1, name="第01版", articles=[])) == "第01版"
    assert edition_label(Edition(num=2, name="", articles=[])) == "第02版"


def test_markdown_toc_escapes_brackets_in_link_text():
    """Unescaped [ ] would nest a link inside link text and break the TOC entry."""
    editions = [
        Edition(
            num=1,
            name="第01版：要闻[特]",
            articles=[Article(title="标题[注]", paragraphs=["正文"])],
        )
    ]

    md = Formatter("人民日报", "http://example.com").markdown(D, editions)

    # TOC link text is escaped...
    assert "- **[第01版 · 要闻\\[特\\]](#第01版-要闻特)**（1篇）" in md
    assert "  - [标题\\[注\\]](#标题注)" in md
    # ...while headings stay raw and no nested unescaped bracket remains.
    assert "## 第01版 · 要闻[特]" in md
    assert "### 标题[注]" in md
    assert "  - [标题[注]](#标题注)" not in md


def test_markdown_normal_labels_and_titles_unchanged():
    """Bracket-free input keeps byte-identical TOC lines."""
    md = Formatter("人民日报", "http://paper.people.com.cn/rmrb").markdown(
        D, _editions()
    )

    assert "- **[第01版 · 要闻](#第01版-要闻)**（3篇）" in md
    assert "  - [标题甲](#标题甲)" in md
    assert "  - [未抓取](#未抓取)" in md
    assert "\\[" not in md
