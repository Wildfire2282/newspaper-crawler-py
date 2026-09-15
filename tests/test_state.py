"""state tests: defaults, corrupt-file recovery, preference round-trip, ledger flow."""

import json
from datetime import date, timedelta
from pathlib import Path

from newspaper_crawler.state import (
    DONE,
    EMPTY,
    FAILED,
    PENDING,
    SKIPPED,
    STATE_FILENAME,
    StateStore,
    default_preferences,
    resume_days,
    resume_plan,
)


def test_missing_file_yields_defaults(tmp_path):
    store = StateStore(tmp_path)

    assert store.path == tmp_path / STATE_FILENAME
    assert not store.path.exists()
    assert store.last_run is None
    assert store.history == []
    assert store.open_days() == []
    assert store.preferences == default_preferences()


def test_corrupt_file_is_backed_up_and_defaults_are_used(tmp_path):
    target = tmp_path / STATE_FILENAME
    target.write_text("{ 不是 JSON", encoding="utf-8")

    store = StateStore(tmp_path)

    assert store.preferences == default_preferences()
    assert not target.exists()  # replaced by the default on the next save
    assert (tmp_path / (STATE_FILENAME + ".bak")).read_text(
        encoding="utf-8"
    ) == "{ 不是 JSON"


def test_preferences_round_trip_with_relative_output_dir(tmp_path):
    store = StateStore(tmp_path)
    store.save_preferences(
        site_keys=["rmrb", "gmrb"],
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        output_dir=str(tmp_path / "out"),  # inside the state dir -> stored relative
        output_format="txt",
        max_workers=8,
        fast_mode=True,
        skip_existing=False,
        site_workers=2,
    )

    raw = json.loads(store.path.read_text(encoding="utf-8"))
    assert raw["version"] == 1
    assert raw["preferences"]["output_dir"] == "out"
    assert raw["preferences"]["start_date"] == "2026-09-01"

    reloaded = StateStore(tmp_path).preferences
    assert reloaded.site_keys == ["rmrb", "gmrb"]
    assert reloaded.start_date == date(2026, 9, 1)
    assert reloaded.end_date == date(2026, 9, 3)
    assert reloaded.output_dir == str(tmp_path / "out")
    assert reloaded.output_format == "txt"
    assert reloaded.max_workers == 8
    assert reloaded.fast_mode is True
    assert reloaded.skip_existing is False
    assert reloaded.site_workers == 2


def test_preferences_keep_absolute_output_dir_outside_cwd(tmp_path):
    outside = Path(tmp_path.anchor) / "not-under-the-project"
    store = StateStore(tmp_path)
    store.save_preferences(output_dir=str(outside))

    assert json.loads(store.path.read_text(encoding="utf-8"))["preferences"][
        "output_dir"
    ] == outside.as_posix()
    assert StateStore(tmp_path).preferences.output_dir == str(outside)


def test_invalid_preference_fields_fall_back_to_defaults(tmp_path):
    (tmp_path / STATE_FILENAME).write_text(
        json.dumps(
            {
                "version": 1,
                "preferences": {
                    "start_date": "不是日期",
                    "end_date": "2026-09-01",
                    "max_workers": 0,
                    "skip_existing": "yes",
                },
            }
        ),
        encoding="utf-8",
    )

    prefs = StateStore(tmp_path).preferences

    assert prefs.start_date == default_preferences().start_date
    assert prefs.end_date == default_preferences().end_date
    assert prefs.max_workers == 1  # clamped, never zero
    assert prefs.skip_existing is True  # a non-bool is ignored
    assert prefs.output_dir == str(tmp_path / "downloads")


def test_preferences_reject_reversed_range(tmp_path):
    (tmp_path / STATE_FILENAME).write_text(
        json.dumps(
            {
                "preferences": {
                    "start_date": "2026-09-05",
                    "end_date": "2026-09-01",
                }
            }
        ),
        encoding="utf-8",
    )

    assert StateStore(tmp_path).preferences.start_date == (
        default_preferences().start_date
    )


def test_record_day_updates_entry_and_creates_missing_one(tmp_path):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], date(2026, 9, 1), date(2026, 9, 1), tmp_path, "md")

    assert store.last_run is not None
    assert [d.status for d in store.last_run.days] == [PENDING]
    assert [d.date.isoformat() for d in store.open_days()] == ["2026-09-01"]

    store.record_day("rmrb", date(2026, 9, 1), DONE, path=tmp_path / "a.md")

    entry = store.last_run.days[0]
    assert entry.status == DONE
    assert entry.path == str(tmp_path / "a.md")
    assert entry.updated_at is not None
    assert store.open_days() == []

    # A day that was not part of the run is appended rather than dropped.
    store.record_day("gmrb", date(2026, 9, 2), FAILED, error="炸了")
    assert len(store.last_run.days) == 2

    reloaded = StateStore(tmp_path)
    assert [(d.site, d.status) for d in reloaded.last_run.days] == [
        ("rmrb", DONE),
        ("gmrb", FAILED),
    ]
    assert [d.site for d in reloaded.open_days()] == ["gmrb"]


def test_open_days_cover_pending_and_failed_only(tmp_path):
    store = StateStore(tmp_path)
    store.start_run(
        ["rmrb"],
        date(2026, 9, 1),
        date(2026, 9, 4),
        tmp_path,
        "md",
    )
    for day, status in zip(
        (date(2026, 9, 1), date(2026, 9, 2), date(2026, 9, 3), date(2026, 9, 4)),
        (DONE, FAILED, SKIPPED, EMPTY),
        strict=True,
    ):
        store.record_day("rmrb", day, status)

    assert [d.date.isoformat() for d in store.open_days()] == ["2026-09-02"]
    assert StateStore.summary(store.last_run) == {
        DONE: 1,
        FAILED: 1,
        SKIPPED: 1,
        EMPTY: 1,
        PENDING: 0,
    }


def test_record_day_without_a_run_is_a_no_op(tmp_path):
    store = StateStore(tmp_path)
    store.record_day("rmrb", date(2026, 9, 1), DONE)

    assert store.last_run is None
    assert not store.path.exists()


def test_finish_run_appends_history_most_recent_first(tmp_path):
    store = StateStore(tmp_path)
    for run in (date(2026, 9, 1), date(2026, 9, 2)):
        store.start_run(["rmrb"], run, run, tmp_path, "md")
        store.record_day("rmrb", run, DONE)
        store.finish_run({"days_success": 1})

    reloaded = StateStore(tmp_path)
    assert [h["run_id"] for h in reloaded.history][:2] == [
        store.history[0]["run_id"],
        store.history[1]["run_id"],
    ]
    assert reloaded.history[0]["sites"] == ["rmrb"]
    assert reloaded.history[0]["summary"][DONE] == 1


def test_history_is_capped(tmp_path):
    store = StateStore(tmp_path)
    for i in range(25):
        day = date(2026, 1, 1) + timedelta(days=i)
        store.start_run(["rmrb"], day, day, tmp_path, "md")
        store.record_day("rmrb", day, DONE)
        store.finish_run({})

    assert len(store.history) == 20


def test_resume_plan_and_days(tmp_path):
    store = StateStore(tmp_path)
    assert resume_plan(store) is None

    store.start_run(
        ["rmrb", "gmrb"], date(2026, 9, 1), date(2026, 9, 2), tmp_path, "md"
    )
    store.record_day("rmrb", date(2026, 9, 1), DONE)
    store.record_day("rmrb", date(2026, 9, 2), FAILED)
    store.record_day("gmrb", date(2026, 9, 1), DONE)
    store.record_day("gmrb", date(2026, 9, 2), PENDING)

    planned = resume_plan(store)
    assert planned is not None
    open_days, output_dir, fmt = planned
    assert output_dir == tmp_path
    assert fmt == "md"
    assert resume_days(open_days) == {
        "rmrb": {"2026-09-02"},
        "gmrb": {"2026-09-02"},
    }

    store.start_run(["rmrb"], date(2026, 9, 3), date(2026, 9, 3), tmp_path, "txt")
    store.record_day("rmrb", date(2026, 9, 3), DONE)
    assert resume_plan(store) is None  # a finished run offers nothing to resume


def test_start_run_builds_entries_for_the_whole_range(tmp_path):
    store = StateStore(tmp_path)
    run = store.start_run(
        ["rmrb", "gmrb"], date(2026, 9, 1), date(2026, 9, 3), tmp_path, "md"
    )

    assert len(run.days) == 6
    assert {d.site for d in run.days} == {"rmrb", "gmrb"}
    assert run.output_dir == str(tmp_path)
    assert run.fmt == "md"


def test_store_uses_provided_working_directory(tmp_path):
    cwd = tmp_path / "project"
    cwd.mkdir()
    store = StateStore(cwd)

    assert store.cwd == cwd
    assert store.path == cwd / STATE_FILENAME


def test_preferences_default_dates_cover_the_last_seven_days():
    prefs = default_preferences()
    today = date.today()

    assert prefs.end_date == today
    assert prefs.start_date == today - timedelta(days=6)
    assert not Path(prefs.output_dir).is_absolute()  # relative to the working dir
    assert prefs.output_dir == "downloads"
