"""util 模块测试：日期解析、星期、抓取选项构造。"""

from datetime import date

import pytest

from newspaper_crawler.models import OutputFormat
from newspaper_crawler.util import (
    make_crawl_options,
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
    d = date(2026, 9, 10)  # 星期四
    assert weekday_cn(d) == "周四"
    assert weekday_cn_full(d) == "星期四"


def test_make_crawl_options_normal_mode(tmp_path):
    opts, workers = make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
        output_dir=tmp_path,
        output_format=OutputFormat.TXT,
        workers=4,
        fast=False,
    )
    assert workers == 4
    assert opts.output_format is OutputFormat.TXT
    assert opts.article_delay == (0.1, 0.3)
    assert opts.day_delay == 0.5
    assert opts.skip_existing is True


def test_make_crawl_options_fast_mode_raises_workers(tmp_path):
    opts, workers = make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
        output_dir=tmp_path,
        workers=3,
        fast=True,
    )
    assert workers == 10  # max(10, 3)
    assert opts.max_workers == 10
    assert opts.article_delay == (0.01, 0.05)
    assert opts.day_delay == 0.1


def test_make_crawl_options_fast_mode_keeps_large_workers(tmp_path):
    _, workers = make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 3),
        output_dir=tmp_path,
        workers=20,
        fast=True,
    )
    assert workers == 20
