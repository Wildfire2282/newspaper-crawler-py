"""Atomic file writes: write to a temp sibling, then ``os.replace``; retry 3x."""

from __future__ import annotations

import os
import time
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """Write UTF-8 text atomically, creating parent directories.

    Invariant: the destination is either absent or complete; a reader never observes
    a partially written file.

    Raises:
        OSError: the temp file could not be written, or ``os.replace`` failed on all
            3 attempts. The temp file is removed in both cases.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Per-process temp name: two runs writing the same day must not interleave into
    # one temp file and then publish a mixed document.
    tmp = path.with_suffix(f"{path.suffix}.{os.getpid()}.tmp")
    try:
        tmp.write_text(content, encoding="utf-8")
    except OSError:
        tmp.unlink(missing_ok=True)
        raise
    for i in range(3):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if i == 2:
                tmp.unlink(missing_ok=True)
                raise
            # Windows may refuse the replace while the destination is open.
            time.sleep(0.1 * (i + 1))
