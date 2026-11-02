"""Planning a resume: which ledger entries are still worth re-running.

A resume is ledger-driven, so ``crawl``/``plan --resume`` and the interactive menu all
need the same answer from the same rules. This module is that single answer: the CLI
and the menu only render it and run it.

Entries whose site no longer resolves are reported and dropped - keeping them would
rewrite the same unusable ledger and block every later resume.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .models import OutputFormat
from .registry import lookup
from .state import DayRecord, StateStore


@dataclass(slots=True)
class ResumePlan:
    """Resumable ledger entries plus the settings the interrupted run recorded.

    Contract: ``days`` may be empty (every site in the ledger is gone), in which case
    ``keys`` / ``start`` / ``end`` / ``days_by_site`` are meaningless; callers must
    check ``days`` first and report ``unknown``.
    """

    days: list[DayRecord]
    unknown: list[str]
    output_dir: Path
    fmt: OutputFormat

    @property
    def keys(self) -> list[str]:
        return sorted({d.site for d in self.days})

    @property
    def start(self) -> date:
        return min(d.date for d in self.days)

    @property
    def end(self) -> date:
        return max(d.date for d in self.days)

    @property
    def days_by_site(self) -> dict[str, set[str]]:
        """Per-site ISO date allow-list for the scheduler."""
        return resume_days(self.days)


def resume_days(open_days: list[DayRecord]) -> dict[str, set[str]]:
    """Group ledger entries into the scheduler's per-site day allow-list."""
    grouped: dict[str, set[str]] = {}
    for entry in open_days:
        grouped.setdefault(entry.site, set()).add(entry.date.isoformat())
    return grouped


def plan_resume(store: StateStore) -> ResumePlan | None:
    """Return the work left over by the last run, or None when there is none."""
    run = store.last_run
    if run is None:
        return None
    open_days = run.open_days()
    if not open_days:
        return None
    usable = [d for d in open_days if lookup(d.site) is not None]
    unknown = sorted({d.site for d in open_days} - {d.site for d in usable})
    return ResumePlan(
        days=usable,
        unknown=unknown,
        output_dir=Path(run.output_dir),
        fmt=OutputFormat.parse(run.fmt),
    )
