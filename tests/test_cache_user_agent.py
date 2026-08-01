"""The download fetcher must identify itself as a browser.

Regression guard for a real failure on 2026-08-01: all four Annual Financial
Reports failed to ingest with `HTTPError: 403 Forbidden` from gao.az.gov,
because `requests` sends `python-requests/x.y` by default and that host's WAF
rejects it. Every AFR lives on that host, and the AFR is the top of the
accuracy hierarchy the system prompt tells the model to trust.

This is a cheap test for an expensive-to-diagnose failure: a 403 on a download
surfaces to a non-technical uploader as "the document failed", with nothing
pointing at a missing header.
"""
from __future__ import annotations

import ingest.cache as cache


def test_default_fetcher_sends_a_user_agent(monkeypatch):
    seen: dict = {}

    class _Response:
        content = b"%PDF-1.4 fake"

        def raise_for_status(self) -> None:
            return None

    def fake_get(url, **kwargs):
        seen["url"] = url
        seen["headers"] = kwargs.get("headers") or {}
        return _Response()

    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    assert cache._default_fetcher("https://gao.az.gov/x.pdf") == b"%PDF-1.4 fake"

    ua = seen["headers"].get("User-Agent", "")
    assert ua, "no User-Agent sent — gao.az.gov 403s the requests default"
    # The specific requirement, not merely "some UA": gao.az.gov rejects a
    # descriptive agent string too (measured), so this must look like a browser.
    assert "Mozilla/5.0" in ua
    assert "python-requests" not in ua
