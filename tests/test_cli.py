"""CLI 测试：参数解析、JSON 输出、退出码、模式判别。"""

import json
import sys
from datetime import date, timedelta

import pytest

from newspaper_crawler import tui
from newspaper_crawler.cli import (
    EXIT_ERROR,
    EXIT_OK,
    EXIT_USAGE,
    _resolve_output_dir,
    _resolve_sites,
    build_parser,
    main,
)


class _Stdin:
    def __init__(self, tty: bool):
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


# ---------------------------------------------------------------- 参数解析


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


# ---------------------------------------------------------------- 工具函数


def test_resolve_sites_all_and_aliases():
    sites, unknown = _resolve_sites("all")
    # 按站点中文名排序
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


# ---------------------------------------------------------------- 模式判别


def test_no_args_non_tty_is_usage_error(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", _Stdin(False))
    assert main([]) == EXIT_USAGE
    assert "请指定子命令" in capsys.readouterr().err


def test_no_args_tty_enters_tui(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _Stdin(True))
    monkeypatch.setattr(sys, "stdout", _Stdin(True))
    monkeypatch.setattr(tui, "run", lambda: EXIT_OK)
    assert main([]) == EXIT_OK


# ---------------------------------------------------------------- 子命令


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
