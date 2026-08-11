"""HTTP 客户端封装：会话复用、超时、指数退避重试、404 静默、GBK 回退。

对齐 Rust 版 src-tauri/src/crawler/http.rs 的 SafeRequest 语义。
"""

from __future__ import annotations

import logging
import random
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

log = logging.getLogger("newspaper")


class HttpSession:
    """带重试与编码回退的 GET 请求封装（线程安全：requests.Session 并发可用）。"""

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
        fast_mode: bool = False,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.fast_mode = fast_mode
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        # 连接超时固定 5s（对齐 Rust connect_timeout）
        self.connect_timeout = 5.0

    def get(self, url: str, silent_404: bool = False) -> Optional[requests.Response]:
        """GET 请求；全部失败返回 None。404 且 silent_404 时静默返回 None。"""
        for attempt in range(self.max_retries):
            try:
                resp = self.session.get(url, timeout=(self.connect_timeout, self.timeout))
            except requests.RequestException as exc:  # 连接错误/超时等
                if attempt + 1 < self.max_retries:
                    wait = _backoff_secs(attempt)
                    log.warning("请求异常: %s, %.1fs 后重试...", exc, wait)
                    time.sleep(wait)
                    continue
                log.error("请求失败 [%s]: %s", url, exc)
                return None

            status = resp.status_code
            if status == 200:
                return resp
            if status == 404 and silent_404:
                return None
            if attempt + 1 < self.max_retries:
                wait = _backoff_secs(attempt)
                if not (silent_404 and status == 404):
                    log.warning("HTTP %s [%s], %.1fs 后重试...", status, url, wait)
                time.sleep(wait)
                continue
            return None
        return None

    def get_text(self, url: str, silent_404: bool = False) -> Optional[str]:
        """获取页面文本；优先 utf-8，失败回退 gbk。"""
        resp = self.get(url, silent_404=silent_404)
        if resp is None:
            return None
        return _decode(resp)

    def get_soup(self, url: str, silent_404: bool = False) -> Optional[BeautifulSoup]:
        """获取并解析 HTML；请求失败返回 None。"""
        html = self.get_text(url, silent_404=silent_404)
        if html is None:
            return None
        return BeautifulSoup(html, "html.parser")

    def close(self) -> None:
        self.session.close()


def _decode(resp: requests.Response) -> str:
    """解码响应正文：优先 utf-8，失败回退 gbk（旧版页面多为 GBK 编码）。"""
    raw = resp.content
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("gbk", errors="replace")


def _backoff_secs(attempt: int) -> float:
    """2^n + 随机抖动。"""
    return 2 ** attempt + random.random()
