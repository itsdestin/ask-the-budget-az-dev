"""Tests for ingest/validate.py — the advisory post-ingest gate."""
from __future__ import annotations

import pytest

from ingest.validate import AGENCY_STAMP_FLOOR, validate_doc
from store.chunk_store import ChunkStore


def _row(cid: str, **over):
    base = dict(
        chunk_id=cid, doc_id="doc-1", text="appropriation text",
        section_path=["A"], page=1, bbox=[1.0, 2.0, 3.0, 4.0],
        source_anchor='{"page": 1}', agency_canonical_ids=["agency:axs"],
        fund_canonical_id=None, fund_mentions=[], fiscal_year=2027,
        doc_type="baseline-per-agency", is_table=False, table_html=None,
        token_count=42, publisher="jlbc", vector=[1.0] + [0.0] * 7,
    )
    base.update(over)
    return base


@pytest.fixture()
def store(tmp_path):
    return ChunkStore(root=tmp_path, dim=8)


def _write(store, rows):
    store.upsert_chunks("budget_chunks", rows)


def test_a_clean_document_has_no_findings(store):
    _write(store, [_row(f"c{i}") for i in range(10)])
    assert validate_doc(store, "budget_chunks", "doc-1") == []


def test_a_document_with_no_passages_is_reported(store):
    findings = validate_doc(store, "budget_chunks", "doc-1")
    assert findings and "not searchable" in findings[0]


def test_empty_text_is_reported(store):
    _write(store, [_row("c0", text="   "), _row("c1")])
    findings = validate_doc(store, "budget_chunks", "doc-1")
    assert any("no text" in f for f in findings)


def test_unlocatable_passages_are_reported(store):
    _write(store, [_row("c0", page=None, source_anchor=None, bbox=None), _row("c1")])
    findings = validate_doc(store, "budget_chunks", "doc-1")
    assert any("can't be located" in f for f in findings)


def test_missing_bbox_is_reported_separately_from_unlocatable(store):
    """A page-only chunk cites correctly; it just can't be highlighted."""
    _write(store, [_row("c0", bbox=None), _row("c1")])
    findings = validate_doc(store, "budget_chunks", "doc-1")
    assert any("without highlighting" in f for f in findings)
    assert not any("can't be located" in f for f in findings)


def test_tiny_passages_are_reported(store):
    _write(store, [_row("c0", token_count=1), _row("c1")])
    findings = validate_doc(store, "budget_chunks", "doc-1")
    assert any("few words long" in f for f in findings)


def test_low_agency_stamping_is_reported_for_per_agency_docs(store):
    rows = [_row(f"c{i}") for i in range(10)]
    for row in rows[:5]:
        row["agency_canonical_ids"] = []
    _write(store, rows)
    findings = validate_doc(store, "budget_chunks", "doc-1")
    assert any(f"{AGENCY_STAMP_FLOOR:.0%}" in f for f in findings)


def test_stamping_is_not_checked_for_cross_cutting_doc_types(store):
    """A statewide summary section is not about one agency; holding it to the
    per-agency floor would cry wolf on every correctly-ingested one."""
    rows = [_row(f"c{i}", doc_type="s-pdf", agency_canonical_ids=[])
            for i in range(10)]
    _write(store, rows)
    assert validate_doc(store, "budget_chunks", "doc-1") == []


def test_findings_do_not_leak_across_documents(store):
    _write(store, [_row("c0"), _row("other", doc_id="doc-2", text="  ")])
    assert validate_doc(store, "budget_chunks", "doc-1") == []
