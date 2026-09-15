"""GET client: session reuse, timeouts, exponential-backoff retries, silent 404s and
charset fallback.

Retries are delegated to urllib3 ``Retry`` mounted through ``HTTPAdapter``: connect
and read errors plus retryable status codes back off exponentially and honor the
``Retry-After`` header.

Mirrors Rust src-tauri/src/crawler/http.rs (SafeRequest).
"""

from __future__ import annotations

import codecs
import logging
from typing import Optional

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .util import make_soup

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_RETRIES = 3
# Per-page response cap: keeps an oversized or hostile page from exhausting memory.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
# Pool sized to the maximum concurrency in use: an undersized pool discards and
# re-handshakes connections under load (slower for us, costlier for the server).
DEFAULT_POOL_CONNECTIONS = 8
DEFAULT_POOL_MAXSIZE = 16
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)

# Retryable status codes; every other non-200 status is terminal.
RETRY_STATUSES = (429, 500, 502, 503, 504)

log = logging.getLogger("newspaper")


class HttpSession:
    """GET wrapper with retry, response-size cap and charset fallback.

    Threading: safe to share across worker threads. After construction the session
    mutates no per-request state (one static User-Agent header, no cookies), which is
    what makes concurrent ``Session.get`` calls safe here; urllib3's pool is
    thread-safe. This class imposes no request pacing, so per-host request rate is
    bounded solely by the caller's worker count.
    """

    def __init__(
        self,
        timeout: float = DEFAULT_TIMEOUT,
        max_retries: int = DEFAULT_MAX_RETRIES,
        user_agent: str = DEFAULT_USER_AGENT,
        pool_maxsize: int = DEFAULT_POOL_MAXSIZE,
        max_bytes: int = DEFAULT_MAX_BYTES,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.pool_maxsize = pool_maxsize
        self.max_bytes = max_bytes
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": user_agent})
        # Connect timeout fixed at 5s (mirrors Rust connect_timeout); the second
        # element of the timeout tuple is the read timeout, i.e. ``self.timeout``.
        self.connect_timeout = 5.0
        adapter = self._build_adapter()
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)

    def _build_adapter(self) -> HTTPAdapter:
        """Adapter applying backoff retries (1s, 2s, 4s, ...) and the sized pool."""
        retry = Retry(
            total=self.max_retries,
            connect=self.max_retries,
            read=self.max_retries,
            status=self.max_retries,
            backoff_factor=1.0,
            status_forcelist=RETRY_STATUSES,
            allowed_methods=frozenset({"GET"}),
            respect_retry_after_header=True,
            # After retries are exhausted, hand the response back and let get() judge it.
            raise_on_status=False,
        )
        return HTTPAdapter(
            max_retries=retry,
            pool_connections=DEFAULT_POOL_CONNECTIONS,
            pool_maxsize=self.pool_maxsize,
        )

    def get(self, url: str, silent_404: bool = False) -> Optional[requests.Response]:
        """GET ``url``.

        Returns:
            The response only for HTTP 200. None for any other status, for a transport
            error after retries are exhausted, or for a body exceeding ``max_bytes``
            (in which case the connection is released without reading the body).

        Args:
            silent_404: suppress the warning log for HTTP 404.
        """
        try:
            resp = self.session.get(url, timeout=(self.connect_timeout, self.timeout))
        except requests.RequestException as exc:  # Raised only after retries exhausted.
            log.error("请求失败 [%s]: %s", url, exc)
            return None

        if resp.status_code == 200:
            length = resp.headers.get("Content-Length")
            if length is not None and length.isdigit() and int(length) > self.max_bytes:
                log.warning(
                    "响应体过大（%s 字节 > 上限 %s），已跳过 [%s]",
                    length,
                    self.max_bytes,
                    url,
                )
                resp.close()
                return None
            return resp
        if not (silent_404 and resp.status_code == 404):
            log.warning("HTTP %s [%s]", resp.status_code, url)
        return None

    def get_text(self, url: str, silent_404: bool = False) -> Optional[str]:
        """Return the decoded body, or None if the request failed."""
        resp = self.get(url, silent_404=silent_404)
        if resp is None:
            return None
        return _decode(resp)

    def get_soup(self, url: str, silent_404: bool = False) -> Optional[BeautifulSoup]:
        """Return the parsed HTML, or None if the request failed."""
        html = self.get_text(url, silent_404=silent_404)
        if html is None:
            return None
        return make_soup(html)

    def close(self) -> None:
        self.session.close()


def _decode(resp: requests.Response) -> str:
    """Decode a response body, trying in order: BOM, utf-8, gbk, content sniffing.

    Legacy pages are predominantly GBK; ``apparent_encoding`` is the last resort for
    pages that are neither, avoiding silent mojibake. This function never raises.
    """
    raw = resp.content
    if raw.startswith(codecs.BOM_UTF8):
        return raw.decode("utf-8-sig")
    if raw.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        # "utf-16" derives byte order from the BOM and consumes it.
        return raw.decode("utf-16")
    for encoding in ("utf-8", "gbk"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode(resp.apparent_encoding or "utf-8", errors="replace")
