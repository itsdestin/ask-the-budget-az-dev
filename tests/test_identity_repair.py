"""Repair stored titles — a documents.json edit, nothing more (spec I7).

The title is NOT a chunk column: `store/schema.py` carries doc_id,
agency_canonical_ids, fiscal_year, doc_type, publisher, section_path and
the fund fields, and `title` lives only in `documents.json`. So this pass
takes no ingest lock, needs no snapshot, never calls `upsert_chunks`, and
cannot lose a chunk_id. Those hazards belong to the re-stamp and the
doc_id rename (Unit C).
"""
from __future__ import annotations

import json

from identity.repair import repair_titles

_DOCS = {
    "jlbc-approps-fy2005-bar": {
        "title": "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
        "fiscal_year": 2005,
        "source_url": "https://www.azjlbc.gov/05app/bar.pdf",
    },
    "jlbc-approps-fy2005-agr": {
        "title": "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
        "fiscal_year": 2005,
        "source_url": "https://www.azjlbc.gov/05app/agr.pdf",
    },
}
_CHUNKS = {
    "jlbc-approps-fy2005-bar": ["Board of Barbers  Executive Director: M. Herrera"],
    "jlbc-approps-fy2005-agr": ["Arizona Department of Agriculture  Director: M. Smith"],
}
_NAMES = {"agency:bar": "Board of Barbers",
          "agency:agr": "Agriculture, Arizona Department of"}
_STAMPS = {"jlbc-approps-fy2005-bar": ["agency:bar"],
           "jlbc-approps-fy2005-agr": ["agency:agr"]}


def test_the_wrong_title_is_repaired_and_the_right_one_is_left_alone():
    result = repair_titles(
        documents=_DOCS, chunks_by_doc=_CHUNKS,
        agency_names=_NAMES, stamps_by_doc=_STAMPS, dry_run=True,
    )
    changed = {c["doc_id"]: c for c in result.changes}
    assert set(changed) == {"jlbc-approps-fy2005-bar"}
    assert changed["jlbc-approps-fy2005-bar"]["after"] == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_every_change_carries_a_reversal_record(tmp_path):
    """Spec I8 — an analyst who disputes a name can see why it changed, and
    the whole pass reverses without restoring a snapshot."""
    result = repair_titles(
        documents=_DOCS, chunks_by_doc=_CHUNKS,
        agency_names=_NAMES, stamps_by_doc=_STAMPS, dry_run=True,
    )
    c = result.changes[0]
    assert set(c) >= {"doc_id", "field", "before", "after", "reason"}
    assert c["field"] == "title"
    assert c["before"] != c["after"]
    assert "witness" in c["reason"] or "stamp wins" in c["reason"]


def test_a_repair_never_creates_a_duplicate_title():
    """Two sub-programme documents of one agency in one book and year.
    Composing both from the agency name would make them indistinguishable —
    77 real documents are in this shape."""
    docs = {
        "jlbc-approps-fy2016-doa": {
            "title": "ADOA", "fiscal_year": 2016,
            "source_url": "https://www.azjlbc.gov/16ar/doa.pdf"},
        "jlbc-approps-fy2016-doa-apf": {
            "title": "ADOA - Automation Projects Fund", "fiscal_year": 2016,
            "source_url": "https://www.azjlbc.gov/16ar/doa-apf.pdf"},
    }
    chunks = {
        "jlbc-approps-fy2016-doa": ["Arizona Department of Administration"],
        "jlbc-approps-fy2016-doa-apf": ["Arizona Department of Administration"],
    }
    stamps = {"jlbc-approps-fy2016-doa": ["agency:doa"],
              "jlbc-approps-fy2016-doa-apf": ["agency:doa"]}
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={"agency:doa": "Administration, Arizona Department of"},
        stamps_by_doc=stamps, dry_run=True,
    )
    after = {c["doc_id"]: c["after"] for c in result.changes}
    for doc_id, meta in docs.items():
        after.setdefault(doc_id, meta["title"])
    assert len(set(after.values())) == 2, after


def test_an_uncorroborated_stamp_is_SKIPPED_not_repaired():
    docs = {"governor-governors-budget-fy2026": {
        "title": "FY 2026 State Agency Detail — Arizona Executive Budget",
        "fiscal_year": 2026, "source_url": "https://azgovernor.gov/x.pdf"}}
    result = repair_titles(
        documents=docs,
        chunks_by_doc={"governor-governors-budget-fy2026": ["General Fund revenue"]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        stamps_by_doc={"governor-governors-budget-fy2026": ["agency:ost"]},
        dry_run=True,
    )
    assert result.changes == []
    assert result.skipped and "not corroborated" in result.skipped[0]["reason"]


def test_writing_is_atomic_and_only_touches_the_title(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    from store.documents import reset_documents_cache

    path = tmp_path / "documents.json"
    path.write_text(json.dumps(_DOCS), encoding="utf-8")
    reset_documents_cache()

    repair_titles(
        documents=_DOCS, chunks_by_doc=_CHUNKS,
        agency_names=_NAMES, stamps_by_doc=_STAMPS, dry_run=False,
    )
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["jlbc-approps-fy2005-bar"]["title"] == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )
    assert written["jlbc-approps-fy2005-bar"]["source_url"] == (
        "https://www.azjlbc.gov/05app/bar.pdf"
    )
    assert not list(tmp_path.glob("*.tmp"))
    reset_documents_cache()
