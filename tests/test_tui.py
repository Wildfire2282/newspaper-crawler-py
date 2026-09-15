"""tui tests: event rendering (no duplicated prefix) and site-selection parsing."""

from datetime import date

from newspaper_crawler import tui
from newspaper_crawler.models import CrawlStats
from newspaper_crawler.scheduler import ProgressEvent


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
