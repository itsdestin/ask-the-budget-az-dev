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


def test_refresh_yaml_round_trips_and_updates_chunk_id(tmp_path, monkeypatch):
    """Full refresh against a sample yaml: stale chunk_id is replaced
    with an anchor match, the YAML is written back preserving structure."""
    from eval.refresh_chunk_ids import refresh_queries_file

    # Sample YAML with a stale chunk_id.
    yaml_text = """\
- id: q-001
  query: "What was AHCCCS FY26 GF appropriation?"
  type: lookup
  expected_chunks:
    - chunk_id: "stale-chunk::1"
      dimensions:
        publisher: jlbc
        doc_type: baseline-per-agency
        fiscal_year: 2026
        agency: "agency:ahccs"
      anchor_text: "$2,587,400"
  expected_refusal: false
  synthesized_by: claude-opus-4-7
  synthesized_at: "2026-05-20T18:00Z"
"""
    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text(yaml_text)

    # Mock DB: stale-chunk::1 doesn't exist; one candidate matches anchor.
    import eval.refresh_chunk_ids as refresh

    def fake_chunk_exists(chunk_id):
        return chunk_id != "stale-chunk::1"

    def fake_find_anchor_match(dims, anchor_text):
        if anchor_text == "$2,587,400":
            return "new-chunk::5"
        return None

    def fake_find_cosine_match(dims, query_text):
        return None  # not reached

    monkeypatch.setattr(refresh, "chunk_exists", fake_chunk_exists)
    monkeypatch.setattr(refresh, "find_anchor_match", fake_find_anchor_match)
    monkeypatch.setattr(refresh, "find_cosine_match", fake_find_cosine_match)

    summary = refresh_queries_file(str(queries_path))
    assert summary["refreshed"] == 1
    assert summary["manual_review"] == 0
    assert summary["unchanged"] == 0

    # Re-read the YAML and confirm the chunk_id was updated in place.
    from ruamel.yaml import YAML
    yaml = YAML()
    with open(queries_path) as f:
        updated = yaml.load(f)
    assert updated[0]["expected_chunks"][0]["chunk_id"] == "new-chunk::5"


def test_refresh_flags_manual_review_when_no_match(tmp_path, monkeypatch):
    """When neither anchor nor cosine finds a match, the query is left
    untouched and counted as manual_review."""
    from eval.refresh_chunk_ids import refresh_queries_file

    yaml_text = """\
- id: q-001
  query: "x"
  type: lookup
  expected_chunks:
    - chunk_id: "stale::1"
      dimensions:
        publisher: jlbc
        doc_type: baseline-per-agency
        fiscal_year: 2026
        agency: "agency:gone"
      anchor_text: "missing"
  expected_refusal: false
"""
    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text(yaml_text)

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "chunk_exists", lambda cid: False)
    monkeypatch.setattr(refresh, "find_anchor_match", lambda *a: None)
    monkeypatch.setattr(refresh, "find_cosine_match", lambda *a: None)

    summary = refresh_queries_file(str(queries_path))
    assert summary["manual_review"] == 1
    assert summary["refreshed"] == 0

    # The YAML was not modified.
    from ruamel.yaml import YAML
    yaml = YAML()
    with open(queries_path) as f:
        unchanged = yaml.load(f)
    assert unchanged[0]["expected_chunks"][0]["chunk_id"] == "stale::1"
