"""tui tests: event rendering, site-selection parsing, preference persistence."""

from datetime import date, timedelta
from pathlib import Path

from newspaper_crawler import tui
from newspaper_crawler.models import CrawlStats
from newspaper_crawler.prefs import Preferences
from newspaper_crawler.scheduler import ProgressEvent
from newspaper_crawler.state import DONE, FAILED, SKIPPED, StateStore


def test_handle_event_renders_message_once(capsys):
    ev = ProgressEvent(
        kind="day_error",
        site="人民日报",
        date=date(2026, 9, 10),
        message="[人民日报] 2026-09-10 抓取失败: boom",
    )
    tui.handle_event(ev)
    out = capsys.readouterr().out
    assert "人民日报" in out
    assert out.count("人民日报") == 1  # renderer must not re-prefix the site name
    assert "抓取失败" in out


def test_handle_event_uses_stats_in_finished_message(capsys):
    stats = CrawlStats(days_attempted=1, days_success=1, total_articles=3)
    ev = ProgressEvent(
        kind="finished", stats=stats, message=f"全部完成 · 耗时 1.2s · {stats}"
    )
    tui.handle_event(ev)
    out = capsys.readouterr().out
    assert "尝试 1 天" in out
    assert "3 篇" in out


def test_handle_event_ignores_empty_message(capsys):
    tui.handle_event(ProgressEvent(kind="day_done"))
    assert capsys.readouterr().out == ""


def test_parse_site_selection_all_and_indexes():
    assert tui._parse_site_selection("all", 4) == [1, 2, 3, 4]
    assert tui._parse_site_selection("1，3", 4) == [1, 3]
    assert tui._parse_site_selection("2 2 1", 4) == [1, 2]


# ---------------------------------------------------------------- preferences


def test_default_preferences_are_the_menu_start(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    prefs = tui.default_preferences()

    assert prefs.output_path(tmp_path) == tmp_path / "downloads"
    assert prefs.output_format == "md"
    assert prefs.start_date == date.today() - timedelta(days=6)
    assert prefs.end_date == date.today()


def test_output_path_resolves_relative_values(tmp_path):
    assert Preferences(output_dir="out").output_path(tmp_path) == tmp_path / "out"
    absolute = (tmp_path / "abs").as_posix()
    assert Preferences(output_dir=absolute).output_path(tmp_path) == tmp_path / "abs"


def _answer(monkeypatch, *, asks=(), confirms=()):
    """Feed queued answers to the menu prompts."""
    ask_queue, confirm_queue = list(asks), list(confirms)
    monkeypatch.setattr(tui, "ask", lambda *a, **k: ask_queue.pop(0))
    monkeypatch.setattr(tui, "confirm", lambda *a, **k: confirm_queue.pop(0))


def test_choose_dates_and_format_are_persisted(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    state = tui.default_preferences()

    _answer(monkeypatch, asks=["2026-09-01", "2026-09-03", "txt"])
    tui.choose_dates(state, store)
    tui.choose_format(state, store)

    saved = StateStore(tmp_path).preferences
    assert saved.start_date == date(2026, 9, 1)
    assert saved.end_date == date(2026, 9, 3)
    assert saved.output_format == "txt"


def test_choose_dates_keeps_the_range_on_invalid_input(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    prefs = tui.default_preferences()
    before = (prefs.start_date, prefs.end_date)

    _answer(monkeypatch, asks=["不是日期", "也不是"])
    tui.choose_dates(prefs, store)

    assert (prefs.start_date, prefs.end_date) == before
    assert StateStore(tmp_path).preferences.start_date == before[0]


def test_choose_advanced_persists_workers_and_toggles(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    state = tui.default_preferences()

    _answer(monkeypatch, asks=["8"], confirms=[True, False])
    tui.choose_advanced(state, store)

    saved = StateStore(tmp_path).preferences
    assert saved.max_workers == 8
    assert saved.fast_mode is True
    assert saved.skip_existing is False


def test_choose_sites_persists_the_selection(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    prefs = tui.default_preferences()

    _answer(monkeypatch, asks=["1"])
    tui.choose_sites(prefs, store)

    assert prefs.site_keys == ["rmrb"]
    assert StateStore(tmp_path).preferences.site_keys == ["rmrb"]


def test_menu_functions_work_without_a_store(monkeypatch):
    prefs = tui.default_preferences()
    _answer(monkeypatch, asks=["txt", "5"], confirms=[False, True])

    tui.choose_format(prefs, None)
    tui.choose_advanced(prefs, None)
    tui.save_preferences(prefs, None)  # a missing store means "do not persist"

    assert prefs.output_format == "txt"
    assert prefs.max_workers == 5


# ---------------------------------------------------------------- resume flow


def test_start_download_offers_to_resume_open_days(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("rmrb", date(2026, 9, 1), FAILED)

    seen: dict = {}

    def fake_run_multi(keys, opts, on_event, on_day=None, days_by_site=None, **kwargs):
        seen.update(
            keys=keys,
            start=opts.start_date,
            end=opts.end_date,
            days_by_site=days_by_site,
        )
        on_day("rmrb", date(2026, 9, 1), DONE, tmp_path / "a.md", None)
        return CrawlStats(days_attempted=1, days_success=1)

    monkeypatch.setattr(tui, "run_multi", fake_run_multi)
    _answer(monkeypatch, confirms=[True])  # accept the resume prompt

    tui.start_download(tui.default_preferences(), store)

    assert seen == {
        "keys": ["rmrb"],
        "start": date(2026, 9, 1),
        "end": date(2026, 9, 1),
        # the allow-list is what keeps a resume from re-walking the whole range
        "days_by_site": {"rmrb": {"2026-09-01"}},
    }
    assert StateStore(tmp_path).open_days() == []


def test_start_download_skips_the_resume_prompt_when_nothing_is_open(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("rmrb", date(2026, 9, 1), SKIPPED)

    prompts: list[str] = []
    ran: list[list[str]] = []
    monkeypatch.setattr(tui, "ask", lambda *a, **k: "7")
    monkeypatch.setattr(tui, "confirm", lambda *a, **k: prompts.append(a[0]) or True)
    # Without this fake the test would crawl the real newspapers for the last 7 days.
    monkeypatch.setattr(
        tui,
        "run_multi",
        lambda keys, opts, **kw: ran.append(keys) or CrawlStats(),
    )

    tui.start_download(tui.default_preferences(), store)

    assert prompts == ["确认开始下载？"]  # no resume offer
    assert len(ran) == 1  # proceeded to a fresh run instead





def test_run_crawl_closes_the_ledger_on_interrupt(tmp_path, monkeypatch, capsys):
    store = StateStore(tmp_path)
    opts = tui.make_crawl_options(
        start=date(2026, 9, 1),
        end=date(2026, 9, 1),
        output_dir=tmp_path,
        workers=1,
    )

    def interrupted(keys, opts, on_event, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(tui, "run_multi", interrupted)
    tui.run_crawl(store, ["rmrb"], opts)

    assert "已中断" in capsys.readouterr().out
    assert store.last_run is not None
    assert store.last_run.stats == {}
    assert store.history[0]["run_id"] == store.last_run.run_id
    assert [d.status for d in store.open_days()] == ["pending"]


def test_start_download_runs_fresh_when_the_resume_offer_is_declined(
    tmp_path, monkeypatch
):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("rmrb", date(2026, 9, 1), FAILED)

    prompts: list[str] = []
    answers = iter([False, True])  # decline the resume, accept the fresh run

    def confirm(prompt, **kwargs):
        prompts.append(prompt)
        return next(answers)

    ran: list[list[str]] = []
    monkeypatch.setattr(tui, "confirm", confirm)
    monkeypatch.setattr(
        tui, "run_multi", lambda keys, opts, **kw: ran.append(keys) or CrawlStats()
    )

    tui.start_download(tui.default_preferences(), store)

    assert prompts[0].startswith("发现上次未完成的 1 天")
    assert prompts[-1] == "确认开始下载？"
    assert ran == [["rmrb", "gmrb", "dzrb", "jjrb"]]  # a fresh run over all sites


def test_handle_event_keeps_bracketed_site_keys(capsys):
    """A bracketed ASCII key must be printed as-is, not parsed as rich markup."""
    tui.handle_event(
        ProgressEvent(
            kind="log", level="warn", site="rmrb", message="[rmrb] 未找到站点，已跳过"
        )
    )

    assert "[rmrb] 未找到站点，已跳过" in capsys.readouterr().out




def test_resuming_a_ledger_with_a_vanished_site_clears_it(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.start_run(["gone", "rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("gone", date(2026, 9, 1), FAILED)
    store.record_day("rmrb", date(2026, 9, 1), FAILED)

    def fake_run_multi(keys, opts, on_event, on_day=None, days_by_site=None, **kw):
        on_day("rmrb", date(2026, 9, 1), DONE, tmp_path / "a.md", None)
        return CrawlStats(days_attempted=1, days_success=1)

    monkeypatch.setattr(tui, "run_multi", fake_run_multi)
    monkeypatch.setattr(tui, "confirm", lambda *a, **k: True)

    tui.start_download(tui.default_preferences(), store)

    reloaded = StateStore(tmp_path)
    assert [d.site for d in reloaded.last_run.days] == ["rmrb"]  # gone is not rewritten
    assert reloaded.open_days() == []  # so the next resume is not blocked


def test_resume_offer_counts_only_resumable_days(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.start_run(["gone", "rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("gone", date(2026, 9, 1), FAILED)
    store.record_day("rmrb", date(2026, 9, 1), FAILED)

    prompts: list[str] = []
    monkeypatch.setattr(
        tui, "confirm", lambda prompt, **k: prompts.append(prompt) or False
    )
    monkeypatch.setattr(tui, "run_multi", lambda *a, **k: CrawlStats())

    tui.start_download(tui.default_preferences(), store)

    assert prompts[0].startswith("发现上次未完成的 1 天")  # not 2: one site vanished


def test_resume_offer_falls_back_to_a_fresh_run_when_nothing_is_resumable(
    tmp_path, monkeypatch
):
    store = StateStore(tmp_path)
    store.start_run(["gone"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("gone", date(2026, 9, 1), FAILED)

    prompts: list[str] = []
    monkeypatch.setattr(
        tui, "confirm", lambda prompt, **k: prompts.append(prompt) or True
    )
    ran: list[list[str]] = []
    monkeypatch.setattr(
        tui, "run_multi", lambda keys, opts, **k: ran.append(keys) or CrawlStats()
    )

    tui.start_download(tui.default_preferences(), store)

    # Not a dead end: the user gets the normal fresh-run flow instead of the menu.
    assert prompts == ["确认开始下载？"]
    assert ran == [["rmrb", "gmrb", "dzrb", "jjrb"]]


def test_menu_save_persists_every_field(tmp_path):
    store = StateStore(tmp_path)
    prefs = tui.default_preferences()
    prefs.site_workers = 7  # the dict-based menu used to drop this one

    tui.save_preferences(prefs, store)

    assert StateStore(tmp_path).preferences.site_workers == 7


def test_choose_output_dir_normalizes_and_persists(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    store = StateStore(tmp_path)
    prefs = tui.default_preferences()
    _answer(monkeypatch, asks=["out/子目录"])

    tui.choose_output_dir(prefs, store)

    assert Path(prefs.output_dir).is_absolute()
    assert Path(prefs.output_dir) == tmp_path / "out" / "子目录"
    assert StateStore(tmp_path).preferences.output_path(tmp_path) == Path(
        prefs.output_dir
    )
