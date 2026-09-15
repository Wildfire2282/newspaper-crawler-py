"""CLI tests: argument parsing, JSON output, exit codes, mode selection."""

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

from newspaper_crawler import tui
from newspaper_crawler.cli import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    _Progress,
    _resolve_output_dir,
    _resolve_sites,
    build_parser,
    main,
)
from newspaper_crawler.models import CrawlStats
from newspaper_crawler.scheduler import ProgressEvent


class _Stdin:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# ---------------------------------------------------------------- argument parsing


def test_crawl_defaults():
    args = build_parser().parse_args(["crawl"])
    assert args.sites == "all"
    assert args.fmt == "md"
    assert args.workers == 5
    assert args.skip_existing is True
    assert args.start == date.today() - timedelta(days=6)
    assert args.end == date.today()


def test_crawl_no_skip_existing_flag():
    args = build_parser().parse_args(["crawl", "--no-skip-existing"])
    assert args.skip_existing is False


def test_crawl_site_workers_default_and_override():
    assert build_parser().parse_args(["crawl"]).site_workers == 4
    assert build_parser().parse_args(["crawl", "--site-workers", "1"]).site_workers == 1


def test_format_choice_and_dates():
    args = build_parser().parse_args(
        ["crawl", "-f", "txt", "--start", "20260901", "--end", "2026-09-03"]
    )
    assert args.fmt == "txt"
    assert args.start == date(2026, 9, 1)
    assert args.end == date(2026, 9, 3)


def test_sites_has_no_download_args():
    args = build_parser().parse_args(["sites"])
    assert not hasattr(args, "start")
    assert args.json is False


def test_version_exits_zero():
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_invalid_date_exits_two():
    with pytest.raises(SystemExit) as exc:
        main(["plan", "--start", "2026-13-99"])
    assert exc.value.code == 2


# ---------------------------------------------------------------- helpers


def test_resolve_sites_all_and_aliases():
    sites, unknown = _resolve_sites("all")
    # Sorted by the Chinese site name.
    assert [s.crawler_id for s in sites] == ["rmrb", "gmrb", "dzrb", "jjrb"]
    assert unknown == []

    sites, unknown = _resolve_sites("rmrb, 光明")
    assert [s.crawler_id for s in sites] == ["rmrb", "gmrb"]
    assert unknown == []


def test_resolve_sites_dedupes_and_reports_unknown():
    sites, unknown = _resolve_sites("rmrb,RMRB,人民,nope")
    assert [s.crawler_id for s in sites] == ["rmrb"]
    assert unknown == ["nope"]


def test_resolve_output_dir_default_and_relative(tmp_path, monkeypatch):
    default = _resolve_output_dir(None)
    assert default.name == "downloads"

    monkeypatch.chdir(tmp_path)
    assert _resolve_output_dir("out") == tmp_path / "out"
    assert _resolve_output_dir(str(tmp_path / "abs")) == tmp_path / "abs"


# ---------------------------------------------------------------- mode selection


def test_no_args_non_tty_is_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Stdin(False))
    assert main([]) == EXIT_USAGE
    assert "请指定子命令" in capsys.readouterr().err


def test_no_args_tty_enters_tui(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin(True))
    monkeypatch.setattr(sys, "stdout", _Stdin(True))
    monkeypatch.setattr(tui, "run", lambda: EXIT_OK)
    assert main([]) == EXIT_OK


# ---------------------------------------------------------------- subcommands


def test_sites_json(capsys):
    assert main(["sites", "--json"]) == EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    ids = {s["id"] for s in payload["sites"]}
    assert ids == {"rmrb", "gmrb", "jjrb", "dzrb"}
    assert all(
        "name" in s and "aliases" in s and "base_url" in s for s in payload["sites"]
    )


def test_plan_json_marks_missing_days_for_fetch(tmp_path, capsys):
    assert (
        main(
            [
                "plan",
                "--sites",
                "rmrb",
                "--start",
                "2026-09-01",
                "--end",
                "2026-09-02",
                "-o",
                str(tmp_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["sites"] == ["rmrb"]
    assert payload["summary"] == {"fetch": 2, "skip": 0}
    assert payload["days"][0]["action"] == "fetch"
    assert payload["days"][0]["path"].endswith("人民日报/2026/09/2026-09-01.md")


def test_plan_marks_existing_file_as_skip(tmp_path, capsys):
    target = tmp_path / "人民日报" / "2026" / "09" / "2026-09-01.md"
    target.parent.mkdir(parents=True)
    target.write_text("x", encoding="utf-8")

    assert (
        main(
            [
                "plan",
                "--sites",
                "rmrb",
                "--start",
                "2026-09-01",
                "--end",
                "2026-09-01",
                "-o",
                str(tmp_path),
                "--json",
            ]
        )
        == EXIT_OK
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["summary"] == {"fetch": 0, "skip": 1}
    assert payload["days"][0]["exists"] is True


def test_plan_unknown_site_returns_error(tmp_path, capsys):
    assert (
        main(["plan", "--sites", "nope", "-o", str(tmp_path), "--json"]) == EXIT_ERROR
    )
    payload = json.loads(capsys.readouterr().out)
    assert payload["unknown_sites"] == ["nope"]


def test_crawl_unknown_site_returns_error_without_network(capsys):
    code = main(["crawl", "--sites", "nope", "--json", "--quiet"])
    assert code == EXIT_ERROR
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["unknown_sites"] == ["nope"]
    assert payload["stats"]["days_attempted"] == 0


# ---------------------------------------------------------------- self-documenting help
# ``--help`` is this project's canonical documentation; these tests keep it from
# being changed silently.


def _help(capsys, args):
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 0
    return capsys.readouterr().out


def test_main_help_lists_commands_examples_and_exit_codes(capsys):
    out = _help(capsys, ["--help"])
    for token in ["sites", "plan", "crawl", "interactive", "示例", "退出码", "--json"]:
        assert token in out, f"顶层帮助缺少: {token}"
    for code in ["0", "1", "2", "130"]:
        assert code in out


def test_subcommand_help_documents_params_and_json_fields(capsys):
    crawl = _help(capsys, ["crawl", "--help"])
    for token in ["--workers", "--fast", "stats", "files", "errors", "output_dir"]:
        assert token in crawl, f"crawl 帮助缺少: {token}"

    plan = _help(capsys, ["plan", "--help"])
    for token in ["--sites", "days", "summary"]:
        assert token in plan, f"plan 帮助缺少: {token}"

    sites = _help(capsys, ["sites", "--help"])
    assert "--json" in sites


def test_help_examples_are_runnable_commands(capsys):
    """Every example in the help must start with a real crawler subcommand."""
    out = _help(capsys, ["--help"])
    examples = [
        ln.strip() for ln in out.splitlines() if ln.strip().startswith("crawler ")
    ]
    assert examples
    for line in examples:
        command = line.split("#")[0].split()[1]
        assert command in {"sites", "plan", "crawl", "interactive"}


# ---------------------------------------------------------------- progress collection


def test_progress_collects_files_skipped_and_errors():
    progress = _Progress(None)
    progress(
        ProgressEvent(
            kind="day_done", site="人民日报", path=Path("/out/a.md"), message="m"
        )
    )
    progress(
        ProgressEvent(
            kind="day_skip", site="人民日报", path=Path("/out/b.md"), message="m"
        )
    )
    progress(
        ProgressEvent(
            kind="day_error", site="人民日报", date=date(2026, 9, 1), message="e"
        )
    )
    progress(ProgressEvent(kind="log", level="error", site="人民日报", message="x"))

    assert progress.files == ["/out/a.md"]
    assert progress.skipped == ["/out/b.md"]
    assert progress.errors == [
        {"site": "人民日报", "date": "2026-09-01", "message": "e"},
        {"site": "人民日报", "date": None, "message": "x"},
    ]
    assert progress.warnings == []


def test_progress_collects_warnings_separately_from_errors():
    progress = _Progress(None)
    progress(
        ProgressEvent(
            kind="log",
            level="warn",
            site="人民日报",
            date=date(2026, 9, 1),
            message="索引页结构疑似已变化",
        )
    )

    assert progress.errors == []  # warnings are not errors and do not affect ok
    assert progress.warnings == [
        {"site": "人民日报", "date": "2026-09-01", "message": "索引页结构疑似已变化"}
    ]


def test_crawl_json_includes_scheduler_warnings(monkeypatch, tmp_path, capsys):
    def fake_run_multi(keys, opts, on_event, max_site_workers=4):
        on_event(
            ProgressEvent(
                kind="log",
                level="warn",
                site="人民日报",
                date=date(2026, 9, 1),
                message="索引页结构疑似已变化",
            )
        )
        return CrawlStats(days_attempted=1, days_empty=1)

    monkeypatch.setattr("newspaper_crawler.cli.run_multi", fake_run_multi)

    code = main(
        [
            "crawl",
            "--sites",
            "rmrb",
            "--start",
            "2026-09-01",
            "--end",
            "2026-09-01",
            "-o",
            str(tmp_path),
            "--json",
            "--quiet",
        ]
    )

    payload = json.loads(capsys.readouterr().out)
    assert code == EXIT_OK  # warnings must not affect ok
    assert payload["ok"] is True
    assert payload["warnings"] == [
        {"site": "人民日报", "date": "2026-09-01", "message": "索引页结构疑似已变化"}
    ]


# ---------------------------------------------------------------- plain-text output


def test_sites_table_output(capsys):
    assert main(["sites"]) == EXIT_OK
    out = capsys.readouterr().out
    assert "可用站点" in out
    assert "人民日报" in out


def test_plan_text_output_lists_fetch_days(tmp_path, capsys):
    code = main(
        [
            "plan",
            "--sites",
            "rmrb",
            "--start",
            "2026-09-01",
            "--end",
            "2026-09-01",
            "-o",
            str(tmp_path),
        ]
    )
    assert code == EXIT_OK
    out = capsys.readouterr().out
    assert "将抓取 1 天" in out
    assert "fetch  2026-09-01" in out


def test_crawl_text_output_reports_completion(capsys):
    code = main(["crawl", "--sites", "nope"])
    captured = capsys.readouterr()
    assert code == EXIT_ERROR
    assert "完成 ·" in captured.out
    assert "无法识别的站点" in captured.err
