"""registry tests: lookup by id / name / alias."""

import pytest

from newspaper_crawler.registry import all_sites, display_name, lookup


def test_all_sites_sorted_by_name():
    names = [s.name for s in all_sites()]
    assert names == sorted(names)
    assert set(names) == {"人民日报", "光明日报", "经济日报", "大众日报"}


@pytest.mark.parametrize(
    ("key", "expected_id"),
    [
        ("rmrb", "rmrb"),
        ("RMRB", "rmrb"),
        ("人民日报", "rmrb"),
        ("人民", "rmrb"),
        ("renmin", "rmrb"),
        ("gmrb", "gmrb"),
        ("光明日报", "gmrb"),
        ("jjrb", "jjrb"),
        ("dzrb", "dzrb"),
    ],
)
def test_lookup_by_id_name_alias(key, expected_id):
    site = lookup(key)
    assert site is not None
    assert site.crawler_id == expected_id


@pytest.mark.parametrize("key", ["nope", "不存在", ""])
def test_lookup_unknown_returns_none(key):
    assert lookup(key) is None


def test_lookup_accepts_prefix_and_substring():
    """Documented match order: exact, then prefix, then substring."""
    assert lookup("人").crawler_id == "rmrb"  # prefix
    assert lookup("光").crawler_id == "gmrb"
    assert lookup("民日报").crawler_id == "rmrb"  # substring


def test_display_name_falls_back_to_the_key():
    assert display_name("rmrb") == "人民日报"
    assert display_name("gone") == "gone"  # unknown key shows as-is
