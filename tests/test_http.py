"""HTTP 客户端测试：重试配置与 get() 的返回语义（不联网）。"""

import logging

import requests

from newspaper_crawler.http import RETRY_STATUSES, HttpSession
from newspaper_crawler.util import configure_logging


class _Resp:
    def __init__(self, status_code: int, content: bytes = b""):
        self.status_code = status_code
        self.content = content


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
