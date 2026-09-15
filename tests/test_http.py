"""http tests: retry config, connection pool, response cap and get() semantics (offline)."""

import codecs
import logging

import requests

from newspaper_crawler.http import (
    DEFAULT_MAX_BYTES,
    DEFAULT_POOL_CONNECTIONS,
    RETRY_STATUSES,
    HttpSession,
    _decode,
)
from newspaper_crawler.util import configure_logging


class _Resp:
    def __init__(
        self,
        status_code: int,
        content: bytes = b"",
        headers: dict | None = None,
        apparent_encoding: str | None = None,
    ):
        self.status_code = status_code
        self.content = content
        self.headers = headers or {}
        self.apparent_encoding = apparent_encoding
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_adapter_uses_configured_retries():
    http = HttpSession(max_retries=4)
    retry = http.session.get_adapter("http://example.com").max_retries
    assert retry.total == 4
    assert retry.connect == 4
    assert retry.read == 4
    assert retry.status == 4
    assert retry.backoff_factor == 1.0
    assert set(retry.status_forcelist) == set(RETRY_STATUSES)
    assert retry.allowed_methods == frozenset({"GET"})
    http.close()


def test_get_returns_response_on_200(monkeypatch):
    http = HttpSession()
    monkeypatch.setattr(http.session, "get", lambda *a, **k: _Resp(200))
    assert http.get("http://example.com").status_code == 200


def test_get_returns_none_on_non_200(monkeypatch):
    http = HttpSession()
    monkeypatch.setattr(http.session, "get", lambda *a, **k: _Resp(403))
    assert http.get("http://example.com") is None


def test_get_returns_none_on_404(monkeypatch):
    http = HttpSession()
    monkeypatch.setattr(http.session, "get", lambda *a, **k: _Resp(404))
    assert http.get("http://example.com") is None
    assert http.get("http://example.com", silent_404=True) is None


def test_get_returns_none_when_retries_exhausted(monkeypatch):
    http = HttpSession()

    def boom(*args, **kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(http.session, "get", boom)
    assert http.get("http://example.com") is None


def test_get_text_decodes_utf8_then_gbk(monkeypatch):
    http = HttpSession()
    monkeypatch.setattr(
        http.session, "get", lambda *a, **k: _Resp(200, "中文".encode())
    )
    assert http.get_text("http://example.com") == "中文"

    monkeypatch.setattr(
        http.session, "get", lambda *a, **k: _Resp(200, "中文".encode("gbk"))
    )
    assert http.get_text("http://example.com") == "中文"


def test_get_soup_parses_html(monkeypatch):
    http = HttpSession()
    monkeypatch.setattr(
        http.session, "get", lambda *a, **k: _Resp(200, b"<html><p>hi</p></html>")
    )
    soup = http.get_soup("http://example.com")
    assert soup is not None
    assert soup.p.get_text() == "hi"


def test_configure_logging_routes_urllib3():
    configure_logging(verbose=True)
    assert logging.getLogger("urllib3").level == logging.DEBUG
    configure_logging(verbose=False)
    assert logging.getLogger("urllib3").level == logging.WARNING


def test_adapter_pool_size_matches_concurrency_budget():
    http = HttpSession(pool_maxsize=20)
    adapter = http.session.get_adapter("http://example.com")
    assert adapter._pool_maxsize == 20  # argument honored; avoids pool discard churn
    assert adapter._pool_connections == DEFAULT_POOL_CONNECTIONS
    http.close()


# ---------------------------------------------------------------- response size cap


def test_get_skips_oversized_response_by_content_length(monkeypatch):
    http = HttpSession()
    resp = _Resp(200, headers={"Content-Length": str(DEFAULT_MAX_BYTES + 1)})
    monkeypatch.setattr(http.session, "get", lambda *a, **k: resp)

    assert http.get("http://example.com") is None
    assert resp.closed is True  # connection released without reading the body


def test_get_allows_response_at_the_limit(monkeypatch):
    http = HttpSession()
    resp = _Resp(200, headers={"Content-Length": str(DEFAULT_MAX_BYTES)})
    monkeypatch.setattr(http.session, "get", lambda *a, **k: resp)

    assert http.get("http://example.com") is resp


def test_get_ignores_unparseable_content_length(monkeypatch):
    http = HttpSession()
    resp = _Resp(200, headers={"Content-Length": "chunked"})
    monkeypatch.setattr(http.session, "get", lambda *a, **k: resp)

    assert http.get("http://example.com") is resp


# ---------------------------------------------------------------- decode fallback chain


def test_decode_strips_utf8_bom():
    assert _decode(_Resp(200, codecs.BOM_UTF8 + "中文".encode())) == "中文"


def test_decode_handles_utf16_bom():
    assert _decode(_Resp(200, "中文".encode("utf-16"))) == "中文"


def test_decode_falls_back_to_apparent_encoding():
    # b"\xff\xff" is neither valid utf-8 nor valid GBK (0xFF is not a lead byte),
    # so decoding must fall through to apparent_encoding.
    resp = _Resp(200, b"\xff\xff", apparent_encoding="latin-1")
    assert _decode(resp) == "ÿÿ"
