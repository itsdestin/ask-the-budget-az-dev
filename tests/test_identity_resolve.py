"""ONE title ladder for every surface (spec I12).

Three ladders exist today and they disagree:

| rung | search results | browse listing | AI Mode |
|---|---|---|---|
| 1 | website index title | never consulted | never consulted |
| 2 | sidecar, GATED on ingested_at | sidecar, ungated | sidecar, ungated |
| 3 | humanised doc_id | humanised doc_id | humanised doc_id |

The website index is a HARVEST of somebody else's page and is the supplier
that produced 218 wrong names, so it is demoted below the corpus's own
record. The `ingested_at` gate is dropped with it: it existed only to keep
migration-era titles from beating the index, and measured against the live
corpus it would swap 375 real agency names ("JLBC FY2025 — African-American
Affairs, Arizona Commission of") for doc-id slugs.
"""
from __future__ import annotations

import json

import pytest

from store.documents import reset_documents_cache
from identity.resolve import resolve_title, resolve_titles


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_documents_cache()
    yield tmp_path
    reset_documents_cache()


def _write(data_dir, payload):
    (data_dir / "documents.json").write_text(json.dumps(payload), encoding="utf-8")
    reset_documents_cache()


def test_the_sidecar_title_wins(data_dir):
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "ingested_at": "2026-08-16T00:00:00+00:00",
    }})
    assert resolve_title("jlbc-approps-fy2005-bar") == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_a_migration_era_title_with_no_ingested_at_is_STILL_used(data_dir):
    """375 live documents lack `ingested_at` and most of their titles are
    fine. The old search-page gate would replace this with a doc-id slug."""
    _write(data_dir, {"jlbc-approps-fy2025-aam": {
        "title": "JLBC FY2025 — African-American Affairs, Arizona Commission of",
    }})
    assert resolve_title("jlbc-approps-fy2025-aam") == (
        "JLBC FY2025 — African-American Affairs, Arizona Commission of"
    )


def test_a_missing_document_falls_back_to_the_humanised_doc_id(data_dir):
    """`jlbc` is a registered acronym in `store.documents._SLUG_ACRONYMS`, so
    the humanizer renders it "JLBC", not "Jlbc" — verified against the real
    (unmodifiable) implementation rather than transcribed from the brief."""
    _write(data_dir, {})
    assert resolve_title("jlbc-approps-fy2005-bar") == "JLBC Approps FY 2005 Bar"


def test_a_blank_title_falls_back_rather_than_rendering_empty(data_dir):
    _write(data_dir, {"jlbc-approps-fy2005-bar": {"title": "   "}})
    assert resolve_title("jlbc-approps-fy2005-bar") == "JLBC Approps FY 2005 Bar"


def test_resolve_titles_reads_the_sidecar_ONCE_and_agrees_with_the_singular(data_dir, monkeypatch):
    """Twenty search rows must not re-parse and re-deepcopy the whole map."""
    _write(data_dir, {
        "a": {"title": "Alpha — FY 2026 Baseline"},
        "b": {"title": "Beta — FY 2026 Baseline"},
    })
    import store.documents as docs_mod

    calls = {"n": 0}
    real = docs_mod._load_cached

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(docs_mod, "_load_cached", counting)
    out = resolve_titles(["a", "b"])
    assert out == {"a": "Alpha — FY 2026 Baseline", "b": "Beta — FY 2026 Baseline"}
    assert calls["n"] == 1
    assert out["a"] == resolve_title("a")
