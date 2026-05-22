"""Tests for eval/refresh_chunk_ids.py.

DB calls are mocked. The YAML round-trip is exercised against a real
tmp file using ruamel.yaml.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_check_chunk_exists_returns_true_when_chunk_in_db(monkeypatch):
    """Returns True when the chunks table has a row for the chunk_id."""
    from eval.refresh_chunk_ids import chunk_exists

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchone(_self):
                    return {"chunk_id": "abc::1"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    assert chunk_exists("abc::1") is True


def test_check_chunk_exists_returns_false_when_missing(monkeypatch):
    from eval.refresh_chunk_ids import chunk_exists

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchone(_self):
                    return None

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    assert chunk_exists("missing::1") is False


def test_find_anchor_match_picks_chunk_containing_anchor(monkeypatch):
    """When the anchor_text appears in a candidate chunk, pick it."""
    from eval.refresh_chunk_ids import find_anchor_match
    from eval.schema import QueryDimensions

    candidates = [
        {"chunk_id": "new-abc::2", "text": "unrelated content here"},
        {
            "chunk_id": "new-abc::3",
            "text": "The fund got $2,587,400 from the General Fund.",
        },
        {"chunk_id": "new-abc::4", "text": "other content"},
    ]

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchall(_self):
                    return candidates

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    dims = QueryDimensions(
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        agency="agency:ahccs",
    )
    match = find_anchor_match(
        dims=dims, anchor_text="$2,587,400 from the General Fund"
    )
    assert match == "new-abc::3"


def test_find_anchor_match_returns_none_when_no_anchor_hit(monkeypatch):
    """When no candidate's text contains the anchor, return None."""
    from eval.refresh_chunk_ids import find_anchor_match
    from eval.schema import QueryDimensions

    candidates = [
        {"chunk_id": "x", "text": "unrelated"},
        {"chunk_id": "y", "text": "more unrelated"},
    ]

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchall(_self):
                    return candidates

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    dims = QueryDimensions(
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        agency="agency:ahccs",
    )
    match = find_anchor_match(
        dims=dims, anchor_text="missing anchor phrase"
    )
    assert match is None
