"""util tests: date parsing, weekday names, crawl-option construction, parser choice."""

from datetime import date
from importlib.util import find_spec

import pytest
from bs4 import BeautifulSoup

from newspaper_crawler import util
from newspaper_crawler.models import OutputFormat
from newspaper_crawler.util import (
    make_crawl_options,
    make_soup,
    parse_date,
    weekday_cn,
    weekday_cn_full,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2026-09-10", date(2026, 9, 10)),
        ("20260910", date(2026, 9, 10)),
        ("  2026-09-10  ", date(2026, 9, 10)),
        ("2026-01-01", date(2026, 1, 1)),
    ],
)
def test_parse_date_accepts_both_formats(text, expected):
    assert parse_date(text) == expected


@pytest.mark.parametrize("text", ["2026-13-99", "not-a-date", "", "2026/09/10"])
def test_parse_date_rejects_invalid(text):
    with pytest.raises(ValueError):
        parse_date(text)


def test_weekday_helpers():
    d = date(2026, 9, 10)  # Thursday
    assert weekday_cn(d) == "周四"
    assert weekday_cn_full(d) == "星期四"


def test_make_crawl_options_normal_mode(tmp_path):
    opts = make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
        output_dir=tmp_path,
        output_format=OutputFormat.TXT,
        workers=4,
        fast=False,
    )
    assert opts.max_workers == 4
    assert opts.output_format is OutputFormat.TXT
    assert opts.article_delay == (0.1, 0.3)
    assert opts.day_delay == 0.5
    assert opts.skip_existing is True


def test_make_crawl_options_fast_mode_raises_workers(tmp_path):
    opts = make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
        output_dir=tmp_path,
        workers=3,
        fast=True,
    )
    assert opts.max_workers == 10  # max(10, 3)
    assert opts.article_delay == (0.01, 0.05)
    assert opts.day_delay == 0.1


def test_make_crawl_options_fast_mode_keeps_large_workers(tmp_path):
    opts = make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
        output_dir=tmp_path,
        workers=20,
        fast=True,
    )
    assert opts.max_workers == 20


# ---------------------------------------------------------------- HTML parser


def test_default_parser_is_html_parser():
    """The parser is pinned; see the next test for why lxml is not used."""
    assert util.PARSER == "html.parser"


def test_make_soup_parses_markup():
    soup = make_soup("<html><body><p>正文</p></body></html>")
    assert soup.p.get_text() == "正文"


def test_lxml_relocates_p_out_of_heading():
    """Documents why lxml is not enabled: libxml2 moves <p> out of <h2> per the
    content model, which would silently drop 经济日报 titles.
    """
    markup = '<h2 id="Title"><p>经济主标题</p></h2>'

    permissive = BeautifulSoup(markup, "html.parser").select_one("h2#Title")
    assert permissive is not None
    assert permissive.get_text() == "经济主标题"

    if find_spec("lxml") is not None:  # skip the comparison when lxml is absent
        strict = BeautifulSoup(markup, "lxml").select_one("h2#Title")
        assert strict is not None
        assert strict.get_text() == ""  # <p> was relocated outside the <h2>
