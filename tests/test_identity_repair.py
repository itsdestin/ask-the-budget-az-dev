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


def test_the_ata_case_still_repairs():
    """Pin the ONE class the audit found correct in the first dry run:
    `jlbc-approps-fy2011-ata` is titled after the wrong office
    ("Administrative Hearings, Office of") but is genuinely stamped AND
    corroborated as the Automobile Theft Authority. Every fix below this
    point exists to stop the pass over-firing — this test exists to make
    sure none of them also stopped it from firing where it should."""
    docs = {
        "jlbc-approps-fy2011-ata": {
            "title": "Administrative Hearings, Office of — FY 2011 Appropriations Report",
            "fiscal_year": 2011,
            "source_url": "https://www.azjlbc.gov/11ar/ata.pdf",
        },
    }
    chunks = {
        "jlbc-approps-fy2011-ata": [
            "Automobile Theft Authority  Director: R. Halliday",
        ],
    }
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={"agency:ata": "Automobile Theft Authority"},
        stamps_by_doc={"jlbc-approps-fy2011-ata": ["agency:ata"]},
        dry_run=True,
    )
    changed = {c["doc_id"]: c for c in result.changes}
    assert set(changed) == {"jlbc-approps-fy2011-ata"}
    assert changed["jlbc-approps-fy2011-ata"]["after"] == (
        "Automobile Theft Authority — FY 2011 Appropriations Report"
    )


def test_fix1_fiscal_notes_are_never_touched():
    """The dry run that motivated this correction rewrote 1,862 fiscal
    notes — their titles are built from the bill number and the note's own
    heading, not from any of the three suppliers this module distrusts.
    A fiscal note whose title would OBVIOUSLY be rewritten under the old
    (unfiltered) rules — wrong format, a disagreeing and corroborated
    stamp — must come through completely untouched, and the exclusion
    count must say why."""
    docs = {
        "legislature-fiscal-note-fy2006-hb2819-77": {
            "title": "Fiscal Note - HB 2819: adult probation; county responsibility",
            "fiscal_year": 2006,
            "doc_type": "fiscal-note",
        },
    }
    chunks = {
        "legislature-fiscal-note-fy2006-hb2819-77": [
            "Board of Barbers  Executive Director: M. Herrera",
        ],
    }
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={"agency:bar": "Board of Barbers"},
        stamps_by_doc={"legislature-fiscal-note-fy2006-hb2819-77": ["agency:bar"]},
        dry_run=True,
    )
    assert result.changes == []
    assert result.skipped == []
    assert result.fiscal_notes_excluded == 1


def test_fix3_an_already_correct_title_is_never_touched_by_a_siblings_collision():
    """`jlbc-approps-fy2016-doa` is already correctly titled and its stamp
    agrees — nothing about it needs to change. `jlbc-approps-fy2016-doa-apf`
    is wrongly titled and its repaired name WOULD collide with doa's title
    (the parent/sub-programme shape, 77 real pairs). Before this fix, an
    already-correct document swept into a collision like this could still
    gain a spurious distinguisher (the measured `jlbc-baseline-fy2023-oah`
    shape: "Administrative Hearings, Office of" -> "... (oah)" though its
    title needed no repair at all). `doa` must not appear in EITHER
    `changes` or `skipped` — nothing here is worth explaining to a human,
    because nothing happened."""
    docs = {
        "jlbc-approps-fy2016-doa": {
            "title": "Administration, Arizona Department of — FY 2016 Appropriations Report",
            "fiscal_year": 2016,
            "source_url": "https://www.azjlbc.gov/16ar/doa.pdf",
        },
        "jlbc-approps-fy2016-doa-apf": {
            "title": "ADOA - Automation Projects Fund",
            "fiscal_year": 2016,
            "source_url": "https://www.azjlbc.gov/16ar/doa-apf.pdf",
        },
    }
    chunks = {
        "jlbc-approps-fy2016-doa": ["Arizona Department of Administration"],
        "jlbc-approps-fy2016-doa-apf": ["Arizona Department of Administration"],
    }
    stamps = {
        "jlbc-approps-fy2016-doa": ["agency:doa"],
        "jlbc-approps-fy2016-doa-apf": ["agency:doa"],
    }
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={"agency:doa": "Administration, Arizona Department of"},
        stamps_by_doc=stamps, dry_run=True,
    )
    changed_ids = {c["doc_id"] for c in result.changes}
    skipped_ids = {s["doc_id"] for s in result.skipped}
    assert "jlbc-approps-fy2016-doa" not in changed_ids
    assert "jlbc-approps-fy2016-doa" not in skipped_ids
    assert changed_ids == {"jlbc-approps-fy2016-doa-apf"}
    apf = next(c for c in result.changes if c["doc_id"] == "jlbc-approps-fy2016-doa-apf")
    assert apf["after"] == (
        "Administration, Arizona Department of (doa-apf) "
        "— FY 2016 Appropriations Report"
    )


def test_fix4_a_book_section_is_never_named_from_its_table_of_agencies():
    """`jlbc-baseline-fy2020-531` is a real shape: a bare page-number slug
    (a "LONG TERM GENERAL FUND ESTIMATES" section, not any one agency's
    pages) whose chunk text is a table listing several different agencies.
    Before this fix, `stamps[0]` picked one of them arbitrarily and renamed
    706 such documents to an agency they are not. Title has no ' — FY YYYY
    <book>' suffix yet (so fix #3's already-correct guard cannot short-
    circuit this case) — the pass must still refuse to name it from the
    stamp, and must leave the ENTIRE document untouched rather than
    reformat around a name it cannot trust."""
    docs = {
        "jlbc-baseline-fy2020-531": {
            "title": "LONG TERM GENERAL FUND ESTIMATES",
            "fiscal_year": 2020,
            "source_url": "https://www.azjlbc.gov/20baseline/531.pdf",
        },
    }
    chunks = {
        "jlbc-baseline-fy2020-531": [
            "Governor, Office of the   12,345,000\n"
            "Agriculture, Arizona Department of   6,789,000\n"
            "Board of Barbers   150,000",
        ],
    }
    stamps = {
        "jlbc-baseline-fy2020-531": ["agency:gov", "agency:agr", "agency:bar"],
    }
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={
            "agency:gov": "Governor, Office of the",
            "agency:agr": "Agriculture, Arizona Department of",
            "agency:bar": "Board of Barbers",
        },
        stamps_by_doc=stamps, dry_run=True,
    )
    assert result.changes == []
    assert len(result.skipped) == 1
    assert result.skipped[0]["doc_id"] == "jlbc-baseline-fy2020-531"
    assert "section" in result.skipped[0]["reason"]


def test_fix4_ambiguous_multi_stamp_agency_document_is_also_vetoed():
    """The general form of fix #4, not tied to a section slug: an ordinary
    agency-slugged document that happens to carry more than one CORROBORATED
    stamp is equally an arbitrary pick and must be refused the same way."""
    docs = {
        "jlbc-approps-fy2019-xyz": {
            "title": "Some Cross-Reference Page",
            "fiscal_year": 2019,
            "source_url": "https://www.azjlbc.gov/19ar/xyz.pdf",
        },
    }
    chunks = {
        "jlbc-approps-fy2019-xyz": [
            "Board of Barbers and Agriculture, Arizona Department of both "
            "reference this fund.",
        ],
    }
    stamps = {"jlbc-approps-fy2019-xyz": ["agency:bar", "agency:agr"]}
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={
            "agency:bar": "Board of Barbers",
            "agency:agr": "Agriculture, Arizona Department of",
        },
        stamps_by_doc=stamps, dry_run=True,
    )
    assert result.changes == []
    assert len(result.skipped) == 1
    assert "arbitrary pick" in result.skipped[0]["reason"]


def test_fix5_a_distinguisher_is_never_added_without_a_real_collision():
    """A document composing to a name nobody else in its (book, fiscal_year)
    shares must come through BARE — no parenthetical doc_id tail. Regression
    for the measured defect: 1,843 titles got a distinguisher appended with
    no collision at all (`jlbc-baseline-fy2023-oah` -> "... (oah)")."""
    docs = {
        "jlbc-baseline-fy2023-oah": {
            "title": "Some Wrong Name",
            "fiscal_year": 2023,
            "source_url": "https://www.azjlbc.gov/23baseline/oah.pdf",
        },
    }
    chunks = {
        "jlbc-baseline-fy2023-oah": [
            "Administrative Hearings, Office of  Director: J. Smith",
        ],
    }
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={"agency:oah": "Administrative Hearings, Office of"},
        stamps_by_doc={"jlbc-baseline-fy2023-oah": ["agency:oah"]},
        dry_run=True,
    )
    changed = {c["doc_id"]: c for c in result.changes}
    assert changed["jlbc-baseline-fy2023-oah"]["after"] == (
        "Administrative Hearings, Office of — FY 2023 Baseline"
    )
    assert "(oah)" not in changed["jlbc-baseline-fy2023-oah"]["after"]


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
