"""User preferences: the last-used menu/CLI choices.

Contract:
- defaults come from :func:`default_preferences`;
- loading never raises: every unusable stored field keeps its default
  (see :meth:`Preferences.from_dict`);
- ``output_dir`` is an absolute POSIX string in memory and is written back in a
  CWD-relative form when possible, so the file stays portable.

The file format (ledger + preferences) is owned by :mod:`newspaper_crawler.state`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from .models import OutputFormat
from .util import parse_date


def default_preferences() -> "Preferences":
    """Defaults matching the interactive menu: last 7 days, all sites, ./downloads."""
    today = date.today()
    return Preferences(
        site_keys=[],
        start_date=today - timedelta(days=6),
        end_date=today,
        output_dir="downloads",
    )


def as_path(value: str, cwd: Path) -> Path:
    """Resolve a stored or typed directory: expand ``~``, then relative -> ``cwd``."""
    path = Path(value).expanduser()
    return path if path.is_absolute() else cwd / path


def _relative_output_dir(value: str, cwd: Path) -> str:
    """Store a CWD-relative form when possible, so the file stays portable."""
    path = as_path(value, cwd)
    try:
        return path.relative_to(cwd).as_posix()
    except ValueError:
        return path.as_posix()


def _bool(value: Any, fallback: bool) -> bool:
    return value if isinstance(value, bool) else fallback


def _int(value: Any, fallback: int) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else fallback


def _str(value: Any, fallback: str) -> str:
    return value if isinstance(value, str) and value else fallback


@dataclass
class Preferences:
    """Last-used menu/CLI choices, applied as the defaults of the next run."""

    site_keys: list[str] = field(default_factory=list)
    start_date: date = field(default_factory=date.today)
    end_date: date = field(default_factory=date.today)
    output_dir: str = "downloads"
    output_format: str = "md"
    max_workers: int = 5
    fast_mode: bool = False
    skip_existing: bool = True
    site_workers: int = 4

    def fields(self) -> dict[str, Any]:
        """Every writable field as a Python value, for ``StateStore.save_preferences``.

        One list, not a hand-maintained copy: a field added here is persisted by the
        menu and the CLI alike.
        """
        return {
            "site_keys": list(self.site_keys),
            "start_date": self.start_date,
            "end_date": self.end_date,
            "output_dir": self.output_dir,
            "output_format": self.output_format,
            "max_workers": self.max_workers,
            "fast_mode": self.fast_mode,
            "skip_existing": self.skip_existing,
            "site_workers": self.site_workers,
        }

    def output_path(self, cwd: Path) -> Path:
        """``output_dir`` as a path, resolving a relative value against ``cwd``."""
        return as_path(self.output_dir, cwd)

    def to_dict(self, cwd: Path) -> dict:
        return {
            "site_keys": list(self.site_keys),
            "start_date": self.start_date.isoformat(),
            "end_date": self.end_date.isoformat(),
            "output_dir": _relative_output_dir(self.output_dir, cwd),
            "output_format": self.output_format,
            "max_workers": self.max_workers,
            "fast_mode": self.fast_mode,
            "skip_existing": self.skip_existing,
            "site_workers": self.site_workers,
        }

    @classmethod
    def from_dict(cls, raw: dict, cwd: Path) -> "Preferences":
        """Build preferences, keeping the default for every unusable field.

        Args:
            raw: the ``preferences`` object as stored.
            cwd: base for resolving a relative ``output_dir``.
        """
        base = default_preferences()
        try:
            start = parse_date(str(raw["start_date"]))
            end = parse_date(str(raw["end_date"]))
            if end < start:
                raise ValueError("end < start")
        except (KeyError, ValueError):
            start, end = base.start_date, base.end_date

        out = _str(raw.get("output_dir"), base.output_dir)
        path = as_path(out, cwd)

        workers = _int(raw.get("max_workers"), base.max_workers)
        site_workers = _int(raw.get("site_workers"), base.site_workers)
        keys = raw.get("site_keys")
        fmt = _str(raw.get("output_format"), base.output_format)
        return cls(
            site_keys=[str(k) for k in keys] if isinstance(keys, list) else [],
            start_date=start,
            end_date=end,
            output_dir=path.as_posix(),
            # The value becomes an argparse default, so it must be a real choice.
            output_format=OutputFormat.parse(fmt).ext(),
            max_workers=max(1, workers),
            fast_mode=_bool(raw.get("fast_mode"), base.fast_mode),
            skip_existing=_bool(raw.get("skip_existing"), base.skip_existing),
            site_workers=max(1, site_workers),
        )


