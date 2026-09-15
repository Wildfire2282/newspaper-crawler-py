"""scheduler tests: per-day flow, skip, empty day, failure counters, multi-site fan-out."""

import threading
from datetime import date

import pytest

from newspaper_crawler import scheduler
from newspaper_crawler.base import EmptyIndexError, SiteCrawler
from newspaper_crawler.models import (
    Article,
    ArticleRef,
    CrawlOptions,
    Edition,
    OutputFormat,
)
from newspaper_crawler.scheduler import run_multi, run_site

D1 = date(2026, 9, 10)
D2 = date(2026, 9, 11)


class _DummyHttp:
    def close(self) -> None:
        pass


class _Site(SiteCrawler):
    crawler_id = "fake"
    name = "测试报"
    base_url = "http://example.com"

    def __init__(self, editions_fn, fetch=None, editions_error=False, name="测试报"):
        self._editions_fn = editions_fn
        self._fetch = fetch or (
            lambda aref: Article(title=aref.title, paragraphs=["p"])
        )
        self._editions_error = editions_error
        self.name = name

    def get_editions(self, http, d):
        if self._editions_error:
            raise RuntimeError("版面炸了")
        return self._editions_fn()

    def fetch_article(self, http, aref, d):
        return self._fetch(aref)


def _one_edition() -> list[Edition]:
    return [Edition(num=1, name="要闻", articles=[ArticleRef(title="甲", url="u1")])]


def _opts(tmp_path, start=D1, end=D1, **kw) -> CrawlOptions:
    base = dict(
        output_format=OutputFormat.MD,
        max_workers=1,
        article_delay=(0.0, 0.0),
        day_delay=0.0,
        skip_existing=True,
    )
    base.update(kw)
    return CrawlOptions(start_date=start, end_date=end, output_dir=tmp_path, **base)


@pytest.fixture
def no_network(monkeypatch):
    monkeypatch.setattr(scheduler, "HttpSession", _DummyHttp)


# ---------------------------------------------------------------- run_site


def test_run_site_writes_file_and_reports_done(tmp_path, no_network):
    site = _Site(_one_edition)
    events = []
    stats = run_site(site, _opts(tmp_path), events.append)

    target = site.day_filepath(D1, tmp_path, "md")
    assert target.exists()
    assert "甲" in target.read_text(encoding="utf-8")
    assert stats.days_success == 1
    assert stats.total_articles == 1

    done = [e for e in events if e.kind == "day_done"]
    assert len(done) == 1
    assert done[0].path == target
    assert [e.kind for e in events][0] == "site_start"
    assert events[-1].kind == "site_done"


def test_run_site_skips_existing_file(tmp_path, no_network):
    target = tmp_path / "测试报" / "2026" / "09" / "2026-09-10.md"
    target.parent.mkdir(parents=True)
    target.write_text("旧内容", encoding="utf-8")

    site = _Site(_one_edition)
    events = []
    stats = run_site(site, _opts(tmp_path), events.append)

    assert stats.days_skipped == 1
    assert stats.days_success == 0
    assert target.read_text(encoding="utf-8") == "旧内容"
    assert "day_skip" in [e.kind for e in events]
    assert "day_done" not in [e.kind for e in events]


def test_run_site_reports_empty_day(tmp_path, no_network):
    site = _Site(list)
    events = []
    stats = run_site(site, _opts(tmp_path), events.append)

    assert stats.days_empty == 1
    assert stats.days_attempted == 1
    assert "day_empty" in [e.kind for e in events]


def test_run_site_warns_when_index_structure_changed(tmp_path, no_network):
    """Index page present but unrecognizable: count as empty, but warn loudly."""

    def changed():
        raise EmptyIndexError("版面导航为空")

    site = _Site(changed)
    events = []
    stats = run_site(site, _opts(tmp_path), events.append)

    assert stats.days_empty == 1
    assert stats.days_attempted == 1
    assert stats.total_errors == 0  # a structure change is not a runtime error

    warns = [e for e in events if e.kind == "log" and e.level == "warn"]
    assert len(warns) == 1
    assert "索引页结构疑似已变化" in warns[0].message
    assert warns[0].date == D1


def test_run_site_counts_editions_error(tmp_path, no_network):
    site = _Site(_one_edition, editions_error=True)
    events = []
    stats = run_site(site, _opts(tmp_path), events.append)

    assert stats.days_attempted == 1
    assert stats.total_errors == 1
    errors = [e for e in events if e.kind == "day_error"]
    assert len(errors) == 1
    assert "抓取失败" in errors[0].message


def test_run_site_counts_write_error_and_does_not_report_file(
    tmp_path, no_network, monkeypatch
):
    def boom(path, content):
        raise OSError("磁盘满")

    monkeypatch.setattr(scheduler, "atomic_write", boom)

    site = _Site(_one_edition)
    events = []
    stats = run_site(site, _opts(tmp_path), events.append)

    assert stats.days_success == 0
    assert stats.days_attempted == 1
    assert stats.total_errors == 1
    assert "day_done" not in [e.kind for e in events]
    err = [e for e in events if e.kind == "day_error"][0]
    assert "写入失败" in err.message
    assert err.path is None


def test_run_site_sleeps_between_days(tmp_path, no_network, monkeypatch):
    slept = []
    monkeypatch.setattr(scheduler.time, "sleep", slept.append)

    site = _Site(_one_edition)
    run_site(site, _opts(tmp_path, start=D1, end=D2, day_delay=0.5), lambda ev: None)

    assert slept == [0.5]  # once, between the two days only


# ---------------------------------------------------------------- run_multi


def test_run_multi_merges_stats_and_finishes(tmp_path, no_network, monkeypatch):
    site = _Site(_one_edition)
    monkeypatch.setattr(scheduler, "lookup", lambda k: site if k == "fake" else None)

    events = []
    stats = run_multi(["fake", "nope"], _opts(tmp_path), events.append)

    assert stats.days_success == 1
    kinds = [e.kind for e in events]
    assert "finished" in kinds
    warns = [e for e in events if e.kind == "log" and e.level == "warn"]
    assert len(warns) == 1
    finished = [e for e in events if e.kind == "finished"][0]
    assert "尝试 1 天" in finished.message


def test_run_multi_continues_when_site_raises(tmp_path, monkeypatch):
    def boom(site, opts, on_event):
        raise RuntimeError("整体失败")

    monkeypatch.setattr(scheduler, "run_site", boom)
    monkeypatch.setattr(scheduler, "lookup", lambda k: _Site(_one_edition))

    events = []
    stats = run_multi(["fake"], _opts(tmp_path), events.append)

    assert stats.total_errors == 0
    assert any(e.kind == "log" and e.level == "error" for e in events)
    assert events[-1].kind == "finished"


def test_run_multi_merges_two_sites(tmp_path, no_network, monkeypatch):
    sites = {
        "a": _Site(_one_edition, name="甲报"),
        "b": _Site(_one_edition, name="乙报"),
    }
    monkeypatch.setattr(scheduler, "lookup", sites.get)

    stats = run_multi(["a", "b"], _opts(tmp_path), lambda ev: None)

    assert stats.days_success == 2
    assert (tmp_path / "甲报" / "2026" / "09" / "2026-09-10.md").exists()
    assert (tmp_path / "乙报" / "2026" / "09" / "2026-09-10.md").exists()


def test_run_multi_runs_sites_in_parallel(tmp_path, no_network, monkeypatch):
    """Both sites must be running at once: a serial run would trip the barrier."""
    barrier = threading.Barrier(2)

    def editions():
        barrier.wait(timeout=5)
        return _one_edition()

    sites = {"a": _Site(editions, name="甲报"), "b": _Site(editions, name="乙报")}
    monkeypatch.setattr(scheduler, "lookup", sites.get)

    stats = run_multi(["a", "b"], _opts(tmp_path), lambda ev: None)

    assert stats.days_success == 2


def test_run_multi_site_workers_one_is_serial(tmp_path, no_network, monkeypatch):
    sites = {
        "a": _Site(_one_edition, name="甲报"),
        "b": _Site(_one_edition, name="乙报"),
    }
    monkeypatch.setattr(scheduler, "lookup", sites.get)

    stats = run_multi(["a", "b"], _opts(tmp_path), lambda ev: None, max_site_workers=1)

    assert stats.days_success == 2


# ---------------------------------------------------------------- ledger hook


def test_on_day_reports_each_outcome_once(tmp_path, no_network):
    site = _Site(_one_edition)
    calls = []
    run_site(
        site,
        _opts(tmp_path, start=D1, end=D2),
        lambda ev: None,
        lambda *args: calls.append(args),
    )

    assert [c[0] for c in calls] == ["fake", "fake"]  # the crawler id, not the name
    assert [c[1] for c in calls] == [D1, D2]
    assert [c[2] for c in calls] == ["done", "done"]
    assert calls[0][3] == site.day_filepath(D1, tmp_path, "md")
    assert all(c[4] is None for c in calls)


def test_on_day_reports_skip_empty_and_failure(tmp_path, no_network):
    existing = tmp_path / "测试报" / "2026" / "09" / "2026-09-10.md"
    existing.parent.mkdir(parents=True)
    existing.write_text("旧内容", encoding="utf-8")

    calls = []
    run_site(
        _Site(_one_edition),
        _opts(tmp_path),
        lambda ev: None,
        lambda *args: calls.append(args),
    )
    assert calls[0][2] == "skipped"
    assert calls[0][3] == existing

    # A fresh directory: the previous file must not turn this into another skip.
    empty_dir = tmp_path / "empty"
    calls = []
    run_site(
        _Site(list),
        _opts(empty_dir),
        lambda ev: None,
        lambda *args: calls.append(args),
    )
    assert calls[0][2] == "empty"

    failed_dir = tmp_path / "failed"
    calls = []
    run_site(
        _Site(_one_edition, editions_error=True),
        _opts(failed_dir),
        lambda ev: None,
        lambda *args: calls.append(args),
    )
    assert calls[0][2] == "failed"
    assert "版面炸了" in calls[0][4]


def test_on_day_is_optional(tmp_path, no_network):
    stats = run_site(_Site(_one_edition), _opts(tmp_path), lambda ev: None)

    assert stats.days_success == 1


def test_day_allow_list_restricts_the_crawl(tmp_path, no_network):
    site = _Site(_one_edition)
    calls = []
    stats = run_site(
        site,
        _opts(tmp_path, start=D1, end=D2),
        lambda ev: None,
        lambda *args: calls.append(args),
        days={"2026-09-11"},
    )

    assert stats.days_success == 1
    assert [c[1] for c in calls] == [D2]
    assert site.day_filepath(D1, tmp_path, "md").exists() is False
    assert site.day_filepath(D2, tmp_path, "md").exists() is True


def test_run_multi_groups_the_allow_list_per_site(tmp_path, no_network, monkeypatch):
    # The ledger is keyed by crawler id, so the two sites need distinct ids.
    sites = {"a": _Site(_one_edition, name="甲报"), "b": _Site(_one_edition, name="乙报")}
    sites["a"].crawler_id, sites["b"].crawler_id = "a", "b"
    monkeypatch.setattr(scheduler, "lookup", sites.get)

    calls = []
    stats = run_multi(
        ["a", "b"],
        _opts(tmp_path, start=D1, end=D2),
        lambda ev: None,
        on_day=lambda *args: calls.append(args),
        days_by_site={"a": {"2026-09-10"}},
    )

    assert stats.days_success == 3  # one day for a, both for b
    assert sorted((c[0], c[1]) for c in calls) == [
        ("a", D1),
        ("b", D1),
        ("b", D2),
    ]
