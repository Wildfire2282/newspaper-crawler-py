"""站点注册表测试：按 id / 名称 / 别名查找。"""

import pytest

from newspaper_crawler.registry import all_sites, find_crawler, lookup


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


def test_find_crawler_is_alias_of_lookup():
    assert find_crawler("rmrb") is lookup("rmrb")
