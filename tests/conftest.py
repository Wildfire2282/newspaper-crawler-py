"""Shared test fixtures.

The downloader persists preferences and its run ledger to a project-level file. Tests
must never read or write the real one in the repository root, so every test gets its
own state file by pointing ``CRAWLER_STATE`` at ``tmp_path`` (see
``newspaper_crawler.state``). The CLI caches its store in a module global, which is
reset before each test for the same reason.
"""

import pytest

from newspaper_crawler import cli, state


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Give each test a private state file and a fresh CLI store."""
    monkeypatch.setenv(state.ENV_STATE_PATH, str(tmp_path / "state.json"))
    monkeypatch.setattr(cli, "_store", None)
    yield tmp_path / "state.json"
