"""tui tests: event rendering, site-selection parsing, preference persistence."""

from datetime import date, timedelta

from newspaper_crawler import tui
from newspaper_crawler.models import CrawlStats
from newspaper_crawler.scheduler import ProgressEvent
from newspaper_crawler.state import (
    DONE,
    FAILED,
    SKIPPED,
    Preferences,
    StateStore,
    default_preferences,
)


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


def test_state_from_preferences_overrides_every_default():
    prefs = Preferences(
        site_keys=["rmrb"],
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        output_dir="/tmp/paper",
        output_format="txt",
        max_workers=9,
        fast_mode=True,
        skip_existing=False,
    )

    state = tui.state_from_preferences(prefs)

    assert state["site_keys"] == ["rmrb"]
    assert state["start_date"] == date(2026, 9, 1)
    assert state["end_date"] == date(2026, 9, 3)
    assert state["output_format"] == "txt"
    assert state["max_workers"] == 9
    assert state["fast_mode"] is True
    assert state["skip_existing"] is False
    assert str(state["output_dir"]) == "/tmp/paper"


def test_state_from_defaults_matches_default_state(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    state = tui.state_from_preferences(default_preferences())

    assert state["output_dir"] == tmp_path / "downloads"
    assert state["output_format"] == "md"
    assert state["start_date"] == date.today() - timedelta(days=6)
    assert state["end_date"] == date.today()


def test_state_from_preferences_resolves_a_relative_output_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    state = tui.state_from_preferences(Preferences(output_dir="out"))

    assert state["output_dir"] == tmp_path / "out"


def _answer(monkeypatch, *, asks=(), confirms=()):
    """Feed queued answers to the menu prompts."""
    ask_queue, confirm_queue = list(asks), list(confirms)
    monkeypatch.setattr(tui, "ask", lambda *a, **k: ask_queue.pop(0))
    monkeypatch.setattr(tui, "confirm", lambda *a, **k: confirm_queue.pop(0))


def test_choose_dates_and_format_are_persisted(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    state = tui.default_state()

    _answer(monkeypatch, asks=["2026-09-01", "2026-09-03", "txt"])
    tui.choose_dates(state, store)
    tui.choose_format(state, store)

    saved = StateStore(tmp_path).preferences
    assert saved.start_date == date(2026, 9, 1)
    assert saved.end_date == date(2026, 9, 3)
    assert saved.output_format == "txt"


def test_choose_dates_keeps_the_range_on_invalid_input(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    state = tui.default_state()
    before = (state["start_date"], state["end_date"])

    _answer(monkeypatch, asks=["不是日期", "也不是"])
    tui.choose_dates(state, store)

    assert (state["start_date"], state["end_date"]) == before
    assert StateStore(tmp_path).preferences.start_date == before[0]


def test_choose_advanced_persists_workers_and_toggles(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    state = tui.default_state()

    _answer(monkeypatch, asks=["8"], confirms=[True, False])
    tui.choose_advanced(state, store)

    saved = StateStore(tmp_path).preferences
    assert saved.max_workers == 8
    assert saved.fast_mode is True
    assert saved.skip_existing is False


def test_choose_sites_persists_the_selection(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    state = tui.default_state()

    _answer(monkeypatch, asks=["1"])
    tui.choose_sites(state, store)

    assert state["site_keys"] == ["rmrb"]
    assert StateStore(tmp_path).preferences.site_keys == ["rmrb"]


def test_menu_functions_work_without_a_store(monkeypatch):
    state = tui.default_state()
    _answer(monkeypatch, asks=["txt", "5"], confirms=[False, True])

    tui.choose_format(state, None)
    tui.choose_advanced(state, None)
    tui.save_preferences(state, None)  # a missing store means "do not persist"

    assert state["output_format"] == "txt"
    assert state["max_workers"] == 5


# ---------------------------------------------------------------- resume flow


def test_start_download_offers_to_resume_open_days(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("rmrb", date(2026, 9, 1), FAILED)

    seen: dict = {}

    def fake_run_multi(keys, opts, on_event, on_day=None, days_by_site=None, **kwargs):
        seen.update(keys=keys, start=opts.start_date, end=opts.end_date)
        on_day("rmrb", date(2026, 9, 1), DONE, tmp_path / "a.md", None)
        return CrawlStats(days_attempted=1, days_success=1)

    monkeypatch.setattr(tui, "run_multi", fake_run_multi)
    _answer(monkeypatch, confirms=[True])  # accept the resume prompt

    tui.start_download(tui.default_state(), store)

    assert seen == {"keys": ["rmrb"], "start": date(2026, 9, 1), "end": date(2026, 9, 1)}
    assert StateStore(tmp_path).open_days() == []


def test_start_download_skips_the_resume_prompt_when_nothing_is_open(tmp_path, monkeypatch):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")
    store.record_day("rmrb", date(2026, 9, 1), SKIPPED)

    prompts: list[str] = []
    monkeypatch.setattr(tui, "ask", lambda *a, **k: "7")
    monkeypatch.setattr(tui, "confirm", lambda *a, **k: prompts.append(a[0]) or True)

    tui.start_download(tui.default_state(), store)

    assert prompts == ["确认开始下载？"]  # no resume offer

