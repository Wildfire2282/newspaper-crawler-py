"""Global site registry.

Mirrors Rust src-tauri/src/crawler/registry.rs.

Contract:
- ``all_sites()`` returns crawlers sorted by site name.
- ``lookup()`` resolves a key by id / name / alias, case-insensitively, then by
  bidirectional prefix match, then by substring containment.
"""

from __future__ import annotations

from typing import Optional

from .base import SiteCrawler
from .sites.dzrb import DazhongCrawler
from .sites.gmrb import GuangmingCrawler
from .sites.jjrb import JingjiCrawler
from .sites.rmrb import RenminCrawler

_SITES: list[SiteCrawler] = [
    RenminCrawler(),
    GuangmingCrawler(),
    JingjiCrawler(),
    DazhongCrawler(),
]


def _build_map() -> dict[str, SiteCrawler]:
    """Build key (id | name | alias) -> crawler; runs once at import."""
    m: dict[str, SiteCrawler] = {}
    for s in _SITES:
        m[s.crawler_id] = s
        m[s.name] = s
        for alias in s.aliases or []:
            m[alias] = s
    return m


_MAP = _build_map()


def all_sites() -> list[SiteCrawler]:
    """Return every crawler, sorted by site name."""
    return sorted(_SITES, key=lambda s: s.name)


def lookup(key: str) -> Optional[SiteCrawler]:
    """Resolve a site key by id / name / alias.

    Match order: case-insensitive exact -> bidirectional prefix -> substring.
    Returns None for an empty key or when no rule matches.
    """
    if not key:
        return None
    if key in _MAP:
        return _MAP[key]
    lower = key.lower()
    for k, v in _MAP.items():
        if k.lower() == lower:
            return v
    # Bidirectional prefix match (mirrors registry.rs).
    for k, v in _MAP.items():
        kl = k.lower()
        if kl.startswith(lower) or lower.startswith(kl):
            return v
    for k, v in _MAP.items():
        if lower in k.lower():
            return v
    return None
