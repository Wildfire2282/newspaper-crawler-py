"""全局站点注册表。

对齐 Rust 版 src-tauri/src/crawler/registry.rs：
- all_sites() 按名称排序
- lookup(key) 支持 id / 名称 / 别名，忽略大小写，双向 starts_with 前缀与包含模糊匹配
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


def _registry_map() -> dict[str, SiteCrawler]:
    """构造 key（id/名称/别名）→ 站点实例 的映射。"""
    m: dict[str, SiteCrawler] = {}
    for s in _SITES:
        m[s.crawler_id] = s
        m[s.name] = s
        for alias in s.aliases:
            m[alias] = s
    return m


def all_sites() -> list[SiteCrawler]:
    """返回全部站点，按名称排序。"""
    return sorted(_SITES, key=lambda s: s.name)


def lookup(key: str) -> Optional[SiteCrawler]:
    """按 id / 名称 / 别名查找站点；先精确（忽略大小写），再双向前缀，再包含。"""
    if not key:
        return None
    m = _registry_map()
    if key in m:
        return m[key]
    lower = key.lower()
    # 忽略大小写的精确匹配
    for k, v in m.items():
        if k.lower() == lower:
            return v
    # 双向 starts_with 前缀匹配（对照 registry.rs）
    for k, v in m.items():
        kl = k.lower()
        if kl.startswith(lower) or lower.startswith(kl):
            return v
    # 包含匹配
    for k, v in m.items():
        if lower in k.lower():
            return v
    return None


def find_crawler(key: str) -> Optional[SiteCrawler]:
    """lookup 的别名（对齐 registry.rs 的 find_crawler）。"""
    return lookup(key)
