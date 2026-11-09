"""The project state file: stored preferences (see :mod:`newspaper_crawler.prefs`)
plus the run ledger.

Contract:
- one file per working directory: ``./.newspaper-crawler.json`` (JSON, version 1);
- the file is written through :func:`newspaper_crawler.storage.atomic_write`, so a
  reader either sees the previous content or the complete new one;
- loading never raises: a missing or corrupt file - or one whose ``version`` is not
  supported - falls back to defaults and is preserved next to it as ``.bak``, because
  a state file must never block the downloader from running.

The per-day ledger is what makes ``crawl --resume`` precise: ``pending`` /
``failed`` entries are the work left over from an interrupted or failing run, while
``done`` / ``skipped`` / ``empty`` are terminal for that run.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Optional

from .prefs import Preferences, default_preferences
from .storage import atomic_write
from .util import parse_date

log = logging.getLogger("newspaper")

STATE_FILENAME = ".newspaper-crawler.json"
STATE_VERSION = 1
HISTORY_LIMIT = 20
# Overrides the state location: a directory, or the file itself.
ENV_STATE_PATH = "CRAWLER_STATE"

# Status of one (site, date) pair inside a run.
PENDING = "pending"
DONE = "done"
SKIPPED = "skipped"
EMPTY = "empty"
FAILED = "failed"

OPEN_STATUSES = (PENDING, FAILED)


def _state_path(cwd: Optional[Path]) -> Path:
    """Resolve the state file.

    An explicit ``cwd`` (library/test use) always wins. Otherwise the process
    looks in the working directory, unless ``CRAWLER_STATE`` overrides it with a
    directory or a file path.
    """
    if cwd is not None:
        return cwd / STATE_FILENAME
    override = os.environ.get(ENV_STATE_PATH)
    if not override:
        return Path.cwd() / STATE_FILENAME
    path = Path(override).expanduser()
    if path.is_dir() or override.endswith(("/", os.sep)):
        return path / STATE_FILENAME
    return path


@dataclass
class DayRecord:
    """One (site, date) entry of a run ledger."""

    site: str
    date: date
    status: str = PENDING
    path: Optional[str] = None
    error: Optional[str] = None
    updated_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "site": self.site,
            "date": self.date.isoformat(),
            "status": self.status,
            "path": self.path,
            "error": self.error,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "DayRecord":
        return cls(
            site=str(raw.get("site", "")),
            date=parse_date(str(raw.get("date", ""))),
            status=str(raw.get("status", PENDING)),
            path=raw.get("path"),
            error=raw.get("error"),
            updated_at=raw.get("updated_at"),
        )


@dataclass
class RunRecord:
    """Ledger of the most recent crawl: what was asked for and how each day went."""

    run_id: str
    started_at: str
    output_dir: str
    fmt: str
    days: list[DayRecord] = field(default_factory=list)
    stats: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "started_at": self.started_at,
            "output_dir": self.output_dir,
            "format": self.fmt,
            "days": [d.to_dict() for d in self.days],
            "stats": self.stats,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> "RunRecord":
        days: list[DayRecord] = []
        for item in raw.get("days") or []:
            if not isinstance(item, dict):
                # A hand-edited or foreign file may hold anything here; a ledger entry
                # it cannot describe must not abort loading the rest.
                continue
            try:
                days.append(DayRecord.from_dict(item))
            except ValueError:  # Unparsable date: drop the entry, keep the rest.
                continue
        return cls(
            run_id=str(raw.get("run_id", "")),
            started_at=str(raw.get("started_at", "")),
            output_dir=str(raw.get("output_dir", "")),
            fmt=str(raw.get("format", "md")),
            days=days,
            stats=raw.get("stats") or {},
        )

    def open_days(self) -> list[DayRecord]:
        """Entries still worth retrying: ``pending`` (interrupted) and ``failed``."""
        return [d for d in self.days if d.status in OPEN_STATUSES]


class StateStore:
    """Read/write access to the project state file; safe for concurrent callers.

    A single instance is shared by the whole run: the interactive menu rewrites the
    preferences, while the scheduler threads report day outcomes through
    :meth:`record_day`. Every mutation is serialized by a lock and immediately
    persisted, so an interrupted process leaves a usable ledger behind.
    """

    def __init__(self, cwd: Optional[Path] = None):
        self.cwd = Path.cwd() if cwd is None else Path(cwd)
        self.path = _state_path(cwd)
        self.preferences = default_preferences()
        self.last_run: Optional[RunRecord] = None
        self.history: list[dict] = []
        self._lock = threading.RLock()
        self._load()

    # ------------------------------------------------------------------ loading

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError("顶层不是对象")
            version = raw.get("version", STATE_VERSION)
            if version != STATE_VERSION:
                # Parsing an unknown layout as v1 and then rewriting it in v1 shape
                # would silently drop whatever that other version stored.
                raise ValueError(f"状态文件版本 {version!r} 不受支持")
            prefs = raw.get("preferences")
            if isinstance(prefs, dict):
                self.preferences = Preferences.from_dict(prefs, self.cwd)
            last = raw.get("last_run")
            if isinstance(last, dict):
                self.last_run = RunRecord.from_dict(last)
            history = raw.get("history")
            if isinstance(history, list):
                self.history = [h for h in history if isinstance(h, dict)]
        except (OSError, ValueError) as exc:
            log.warning("状态文件无法读取（%s），已备份为 %s.bak", exc, self.path.name)
            # A failed backup must not stop the downloader either.
            with contextlib.suppress(OSError):
                self.path.replace(self.path.with_suffix(self.path.suffix + ".bak"))

    # ------------------------------------------------------------------ saving

    def to_dict(self) -> dict:
        return {
            "version": STATE_VERSION,
            "preferences": self.preferences.to_dict(self.cwd),
            "last_run": self.last_run.to_dict() if self.last_run else None,
            "history": self.history,
        }

    def save(self) -> None:
        """Persist the whole state atomically; last write wins."""
        with self._lock:
            atomic_write(
                self.path,
                json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            )

    def save_preferences(self, **fields: Any) -> None:
        """Update one or more preference fields and persist immediately."""
        with self._lock:
            for name, value in fields.items():
                setattr(self.preferences, name, value)
            self.save()

    # ------------------------------------------------------------------ ledger

    def start_run(
        self,
        sites: list[str],
        start: date,
        end: date,
        output_dir: Path,
        fmt: str,
        days: Optional[list[DayRecord]] = None,
    ) -> RunRecord:
        """Create and persist a new ledger, replacing the previous ``last_run``.

        Args:
            days: pre-built entries, e.g. the open days of a resumed run. When
                omitted, every (site, date) of the range starts as ``pending``.
        """
        with self._lock:
            if days is None:
                days = [
                    DayRecord(site=key, date=current)
                    for key in sites
                    for current in _date_range(start, end)
                ]
            now = datetime.now()
            # Microsecond resolution: two runs started within the same second (e.g. a
            # quick crawl followed by --resume) must not share a run_id in the ledger.
            self.last_run = RunRecord(
                run_id=now.strftime("%Y%m%dT%H%M%S.%f"),
                started_at=now.isoformat(timespec="seconds"),
                output_dir=str(output_dir),
                fmt=fmt,
                days=days,
            )
            self.save()
            return self.last_run

    def record_day(
        self,
        site: str,
        day: date,
        status: str,
        path: Optional[Path] = None,
        error: Optional[str] = None,
    ) -> None:
        """Record one day's outcome and persist; called from scheduler threads.

        A (site, date) absent from the ledger is appended, so a resumed run that
        discovers new work still ends up with a complete ledger.
        """
        with self._lock:
            if self.last_run is None:
                return
            entry = self._find(site, day)
            if entry is None:
                entry = DayRecord(site=site, date=day)
                self.last_run.days.append(entry)
            entry.status = status
            entry.path = str(path) if path is not None else None
            entry.error = error
            entry.updated_at = datetime.now().isoformat(timespec="seconds")
            self.save()

    def finish_run(self, stats: dict) -> None:
        """Attach the merged counters and append a history summary entry."""
        with self._lock:
            if self.last_run is None:
                return
            self.last_run.stats = stats
            self.history.insert(
                0,
                {
                    "run_id": self.last_run.run_id,
                    "started_at": self.last_run.started_at,
                    "output_dir": self.last_run.output_dir,
                    "format": self.last_run.fmt,
                    "sites": sorted({d.site for d in self.last_run.days}),
                    "summary": self.summary(self.last_run),
                },
            )
            del self.history[HISTORY_LIMIT:]
            self.save()

    def day_hook(self) -> Callable[..., None]:
        """Scheduler ``on_day`` callback: persist one outcome, never raise.

        The scheduler calls this from several site threads; writes are serialized
        here. Losing a ledger update must not abort a crawl that is otherwise
        working, so write errors are swallowed.
        """

        def on_day(site, day, status, path=None, error=None) -> None:
            with contextlib.suppress(OSError):
                self.record_day(site, day, status, path=path, error=error)

        return on_day

    def open_days(self) -> list[DayRecord]:
        """Entries of ``last_run`` still worth retrying (empty when there is none)."""
        with self._lock:
            return self.last_run.open_days() if self.last_run else []

    @staticmethod
    def summary(run: RunRecord) -> dict[str, int]:
        """Count entries per status, in a stable key order."""
        counts = {status: 0 for status in (DONE, FAILED, SKIPPED, EMPTY, PENDING)}
        for entry in run.days:
            counts[entry.status] = counts.get(entry.status, 0) + 1
        return counts

    def _find(self, site: str, day: date) -> Optional[DayRecord]:
        for entry in self.last_run.days if self.last_run else []:
            if entry.site == site and entry.date == day:
                return entry
        return None


def _date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    current = start
    while current <= end:
        days.append(current)
        current += timedelta(days=1)
    return days
