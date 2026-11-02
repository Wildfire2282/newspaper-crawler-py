"""resume planning tests: what ``--resume`` will re-run, shared by CLI and menu."""

from datetime import date

from newspaper_crawler.resume import plan_resume, resume_days
from newspaper_crawler.state import DONE, FAILED, PENDING, StateStore

D1 = date(2026, 9, 1)
D2 = date(2026, 9, 2)


def _run(store: StateStore, tmp_path, sites=("rmrb", "gmrb")) -> None:
    store.start_run(list(sites), D1, D2, tmp_path, "md")


def test_no_ledger_and_finished_run_offer_nothing(tmp_path):
    store = StateStore(tmp_path)
    assert plan_resume(store) is None

    _run(store, tmp_path)
    store.record_day("rmrb", D1, DONE)
    store.record_day("rmrb", D2, DONE)
    store.record_day("gmrb", D1, DONE)
    store.record_day("gmrb", D2, DONE)

    assert plan_resume(store) is None  # a finished run is not resumable


def test_plan_carries_the_recorded_settings(tmp_path):
    store = StateStore(tmp_path)
    store.start_run(["rmrb"], D1, D2, tmp_path, "txt")
    store.record_day("rmrb", D1, DONE)
    store.record_day("rmrb", D2, FAILED)

    plan = plan_resume(store)

    assert plan is not None
    assert plan.output_dir == tmp_path  # the run's directory, not the preference
    assert plan.fmt.ext() == "txt"
    assert plan.keys == ["rmrb"]
    assert (plan.start, plan.end) == (D2, D2)  # only the open day
    assert plan.days_by_site == {"rmrb": {"2026-09-02"}}
    assert plan.unknown == []


def test_pending_and_failed_are_resumed_done_is_not(tmp_path):
    store = StateStore(tmp_path)
    _run(store, tmp_path)
    store.record_day("rmrb", D1, DONE)
    store.record_day("rmrb", D2, FAILED)
    store.record_day("gmrb", D1, PENDING)
    store.record_day("gmrb", D2, DONE)

    plan = plan_resume(store)

    assert plan is not None
    assert {(d.site, d.date) for d in plan.days} == {("rmrb", D2), ("gmrb", D1)}
    assert plan.days_by_site == {"rmrb": {"2026-09-02"}, "gmrb": {"2026-09-01"}}


def test_unresolvable_sites_are_reported_and_dropped(tmp_path):
    store = StateStore(tmp_path)
    _run(store, tmp_path, sites=("gone", "rmrb"))
    store.record_day("gone", D1, FAILED)
    store.record_day("rmrb", D1, FAILED)
    store.record_day("rmrb", D2, FAILED)

    plan = plan_resume(store)

    assert plan is not None
    assert plan.unknown == ["gone"]
    assert plan.keys == ["rmrb"]
    assert {d.site for d in plan.days} == {"rmrb"}
    assert len(plan.days) == 2  # both open days of the surviving site


def test_plan_with_no_usable_days_keeps_the_unknown_list(tmp_path):
    store = StateStore(tmp_path)
    _run(store, tmp_path, sites=("gone",))
    store.record_day("gone", D1, FAILED)

    plan = plan_resume(store)

    assert plan is not None
    assert plan.days == []  # callers must check before touching start/end
    assert plan.unknown == ["gone"]


def test_resume_days_groups_entries_per_site(tmp_path):
    store = StateStore(tmp_path)
    _run(store, tmp_path)
    store.record_day("rmrb", D1, DONE)
    store.record_day("rmrb", D2, FAILED)
    store.record_day("gmrb", D2, FAILED)

    assert resume_days(store.open_days()) == {
        "rmrb": {"2026-09-02"},
        "gmrb": {"2026-09-01", "2026-09-02"},
    }
