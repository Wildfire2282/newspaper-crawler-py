"""HTTP 客户端封装：会话复用、超时、指数退避重试、404 静默、GBK 回退。

重试交给 urllib3 的 ``Retry``（经 ``HTTPAdapter`` 挂载）：连接/读取错误与
可重试状态码按指数退避重试，并遵循 ``Retry-After`` 响应头。
对齐 Rust 版 src-tauri/src/crawler/http.rs 的 SafeRequest 语义。
"""

from __future__ import annotations

import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# 值得重试的状态码（其余状态码重试无意义，直接返回 None）
RETRY_STATUSES = (429, 500, 502, 503, 504)

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
        adapter = self._build_adapter()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _build_adapter(self) -> HTTPAdapter:
        """构造带退避重试的适配器（退避 1s、2s、4s…，对齐原 2^n 实现）。"""
        retry = Retry(
            total=self.max_retries,
            connect=self.max_retries,
            read=self.max_retries,
            status=self.max_retries,
            backoff_factor=1.0,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            raise_on_status=False,  # 耗尽重试后返回响应，交由 get() 判定
        )
        return HTTPAdapter(max_retries=retry)

    def get(self, url: str, silent_404: bool = False) -> Optional[requests.Response]:
        """GET 请求；非 200 或请求失败返回 None。404 且 silent_404 时不记日志。"""
        try:
            resp = self.session.get(url, timeout=(self.connect_timeout, self.timeout))
        except requests.RequestException as exc:  # 重试耗尽后的连接/读取错误
            log.error("请求失败 [%s]: %s", url, exc)
            return None

        if resp.status_code == 200:
            return resp
        if not (silent_404 and resp.status_code == 404):
            log.warning("HTTP %s [%s]", resp.status_code, url)
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
