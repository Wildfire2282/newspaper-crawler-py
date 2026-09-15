"""base tests: fetch_texts concurrency/caching and BaseCrawler.crawl_day error semantics."""

from datetime import date

from newspaper_crawler import base
from newspaper_crawler.base import BaseCrawler, SiteCrawler, fetch_texts
from newspaper_crawler.models import Article, ArticleRef, Edition, is_full

D = date(2026, 9, 10)


class _FakeHttp:
    """Implements only get_text, the sole HTTP method site parsers use.

    Returns pages by URL (missing URL -> None) and records every requested URL.
    """

    def __init__(self, pages: dict[str, str]):
        self.pages = pages
        self.calls: list[str] = []

    def get_text(self, url: str, silent_404: bool = False):
        self.calls.append(url)
        return self.pages.get(url)


class _Site(SiteCrawler):
    crawler_id = "fake"
    name = "测试报"
    base_url = "http://example.com"

    def __init__(self, editions: list[Edition], fetch):
        self._editions = editions
        self._fetch = fetch
        self.fetched: list[str] = []

    def get_editions(self, http, d):
        return list(self._editions)

    def fetch_article(self, http, aref, d):
        self.fetched.append(aref.title)
        return self._fetch(aref)


def _editions() -> list[Edition]:
    return [
        Edition(
            num=1,
            name="要闻",
            articles=[
                ArticleRef(title="甲", url="u1"),
                ArticleRef(title="乙", url="u2"),
            ],
        )
    ]


# ---------------------------------------------------------------- fetch_texts


def test_fetch_texts_preserves_order_and_maps_failures_to_none():
    http = _FakeHttp({"a": "A", "c": "C"})
    assert fetch_texts(http, ["a", "b", "c"], silent_404=True) == ["A", None, "C"]


def test_fetch_texts_empty_urls_returns_empty():
    assert fetch_texts(_FakeHttp({}), [], silent_404=False) == []


def test_fetch_texts_uses_cache_and_skips_cached_urls():
    http = _FakeHttp({"a": "A"})
    cache = {"b": "B"}

    assert fetch_texts(http, ["a", "b"], silent_404=True, cache=cache) == ["A", "B"]
    assert cache == {"b": "B", "a": "A"}
    assert http.calls == ["a"]

    # Cached URLs must not be requested again: an http returning nothing (pages
    # already in the cache) still yields the same result.
    http2 = _FakeHttp({})
    assert fetch_texts(http2, ["a", "b"], silent_404=True, cache=cache) == ["A", "B"]
    assert http2.calls == []


def test_fetch_texts_dedupes_duplicate_urls():
    calls: list[str] = []

    class _CountingHttp:
        def get_text(self, url, silent_404=False):
            calls.append(url)
            return "X"

    result = fetch_texts(_CountingHttp(), ["a", "a", "b"], silent_404=False)
    assert result == ["X", "X", "X"]
    assert sorted(calls) == ["a", "b"]


# ---------------------------------------------------------------- crawl_day


def test_crawl_day_serial_replaces_refs_and_counts_failures():
    def fetch(aref):
        return (
            Article(title=aref.title, paragraphs=["正文"])
            if aref.title == "甲"
            else None
        )

    site = _Site(_editions(), fetch)
    result, errors = BaseCrawler.crawl_day(
        site, object(), D, max_workers=1, article_delay=(0.0, 0.0)
    )

    assert errors == 1
    assert is_full(result[0].articles[0])
    assert result[0].articles[0].title == "甲"
    assert not is_full(result[0].articles[1])
    assert site.fetched == ["甲", "乙"]


def test_crawl_day_concurrent_replaces_refs():
    site = _Site(_editions(), lambda aref: Article(title=aref.title))
    result, errors = BaseCrawler.crawl_day(site, object(), D, max_workers=4)

    assert errors == 0
    assert [a.title for a in result[0].articles] == ["甲", "乙"]


def test_crawl_day_counts_exception_as_error_and_continues():
    def fetch(aref):
        if aref.title == "甲":
            raise RuntimeError("网络炸了")
        return Article(title=aref.title)

    site = _Site(_editions(), fetch)
    result, errors = BaseCrawler.crawl_day(
        site, object(), D, max_workers=1, article_delay=(0.0, 0.0)
    )

    assert errors == 1
    assert not is_full(result[0].articles[0])
    assert is_full(result[0].articles[1])


def test_crawl_day_returns_early_without_editions():
    site = _Site([], lambda aref: Article(title=aref.title))
    result, errors = BaseCrawler.crawl_day(site, object(), D)
    assert result == []
    assert errors == 0
    assert site.fetched == []


def test_crawl_day_without_refs_skips_fetching():
    eds = [Edition(num=1, name="要闻", articles=[Article(title="已成稿")])]
    site = _Site(eds, lambda aref: Article(title=aref.title))
    result, errors = BaseCrawler.crawl_day(site, object(), D)

    assert errors == 0
    assert site.fetched == []
    assert is_full(result[0].articles[0])


def test_crawl_day_serial_sleeps_between_articles(monkeypatch):
    slept = []
    monkeypatch.setattr(base.time, "sleep", slept.append)

    site = _Site(_editions(), lambda aref: Article(title=aref.title))
    BaseCrawler.crawl_day(site, object(), D, max_workers=1, article_delay=(0.1, 0.2))

    assert len(slept) == 2  # one delay per article in serial mode
