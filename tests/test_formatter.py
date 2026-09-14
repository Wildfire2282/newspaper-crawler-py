"""格式化测试：Markdown / 纯文本结构与锚点去重。"""

from datetime import date

from newspaper_crawler.formatter import Formatter, anchors, count_full, md_anchor
from newspaper_crawler.models import Article, ArticleRef, Edition

D = date(2026, 9, 10)


def _editions() -> list[Edition]:
    return [
        Edition(
            num=1,
            name="要闻",
            articles=[
                Article(title="标题甲", paragraphs=["第一段"], author="记者甲"),
                Article(title="标题甲", paragraphs=["第二段"]),  # 故意重名
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
