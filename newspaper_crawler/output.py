"""Terminal output shared by the CLI and the interactive menu.

Both front ends face the same problems - redirected streams, legacy Windows consoles,
a non-UTF-8 locale, scheduler events that must be printed and collected - so the
solutions live here instead of in each entry point.
"""

from __future__ import annotations

import json
import sys

from rich.console import Console

from .scheduler import ProgressEvent


def make_console(*, stderr: bool = False, markup: bool = False, **kwargs) -> Console:
    """Console that is safe when the stream is a pipe, a file or a legacy locale.

    Args:
        stderr: write to stderr instead of stdout.
        markup: parse rich markup in the printed text. The CLI leaves it off because
            its text embeds site keys and paths inside square brackets; the menu turns
            it on and escapes runtime values itself.
        kwargs: forwarded to :class:`rich.console.Console`.

    Note:
        ``legacy_windows`` is disabled for non-terminals on purpose: rich's legacy
        Windows renderer writes through the console handle, which raises OSError
        instead of printing when the output has been redirected.
    """
    stream = sys.stderr if stderr else sys.stdout
    return Console(
        stderr=stderr,
        markup=markup,
        legacy_windows=None if stream.isatty() else False,
        **kwargs,
    )


def force_utf8_output() -> None:
    """Make stdout/stderr UTF-8 when the system picked a legacy locale.

    Windows defaults redirected output to the OEM/ANSI code page (cp936, cp1252, ...);
    every command prints Chinese immediately, so without this the first line dies with
    UnicodeEncodeError on any non-Chinese locale.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower()
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding not in ("utf-8", "utf8") and reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def emit_json(obj: dict) -> None:
    """Write one JSON document to stdout."""
    print(json.dumps(obj, ensure_ascii=False, indent=2))


class Progress:
    """Scheduler event handler: prints progress lines and collects JSON payload data.

    Invariant: warnings and errors are kept apart. A warning (e.g. unrecognized site,
    suspected site redesign) does not affect ``ok``; only a day_error does.
    """

    def __init__(self, console: Console | None):
        self.console = console
        self.files: list[str] = []
        self.skipped: list[str] = []
        self.errors: list[dict] = []
        self.warnings: list[dict] = []

    def __call__(self, ev: ProgressEvent) -> None:
        if ev.path is not None:
            if ev.kind == "day_done":
                self.files.append(str(ev.path))
            elif ev.kind == "day_skip":
                self.skipped.append(str(ev.path))
        if ev.kind == "day_error":
            self.errors.append(self._entry(ev))
        elif ev.kind == "log" and ev.level == "error":
            self.errors.append({"site": ev.site, "date": None, "message": ev.message})
        elif ev.kind == "log" and ev.level == "warn":
            self.warnings.append(self._entry(ev))
        if self.console is not None:
            self.console.print(ev.message)

    @staticmethod
    def _entry(ev: ProgressEvent) -> dict:
        return {
            "site": ev.site,
            "date": ev.date.isoformat() if ev.date else None,
            "message": ev.message,
        }
