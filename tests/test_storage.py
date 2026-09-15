"""storage tests: atomic write, parent creation, temp-file cleanup on failure."""

from pathlib import Path

import pytest

from newspaper_crawler import storage
from newspaper_crawler.storage import atomic_write


def test_atomic_write_creates_parents_and_file(tmp_path):
    target = tmp_path / "a" / "b" / "2026-09-10.md"
    atomic_write(target, "内容")
    assert target.read_text(encoding="utf-8") == "内容"
    assert not (target.parent / "2026-09-10.md.tmp").exists()


def test_atomic_write_overwrites_existing(tmp_path):
    target = tmp_path / "x.md"
    atomic_write(target, "one")
    atomic_write(target, "two")
    assert target.read_text(encoding="utf-8") == "two"
    assert list(tmp_path.iterdir()) == [target]


def test_atomic_write_cleans_tmp_and_reraises_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "x.md"
    calls = []

    def boom(src, dst):
        calls.append((src, dst))
        raise OSError("locked")

    monkeypatch.setattr(storage.os, "replace", boom)
    monkeypatch.setattr(storage.time, "sleep", lambda *_: None)

    with pytest.raises(OSError):
        atomic_write(target, "data")

    assert len(calls) == 3  # exactly 3 attempts before giving up
    assert not (tmp_path / "x.md.tmp").exists()
    assert not target.exists()


def test_atomic_write_cleans_tmp_when_write_fails(tmp_path, monkeypatch):
    target = tmp_path / "x.md"

    def boom(self, *args, **kwargs):
        raise OSError("no space left")

    monkeypatch.setattr(Path, "write_text", boom)

    with pytest.raises(OSError):
        atomic_write(target, "data")

    assert not (tmp_path / "x.md.tmp").exists()
    assert not target.exists()
