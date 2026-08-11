"""原子写入：写临时文件后 os.replace，Windows 下重试 3 次。

对齐 Rust 版 src-tauri/src/crawler/storage.rs。
"""

from __future__ import annotations

import os
import time
from pathlib import Path


def atomic_write(path: Path, content: str) -> None:
    """原子写入文本文件（UTF-8）。父目录自动创建。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    for i in range(3):
        try:
            os.replace(tmp, path)
            return
        except OSError:
            if i == 2:
                tmp.unlink(missing_ok=True)
                raise
            time.sleep(0.1 * (i + 1))
