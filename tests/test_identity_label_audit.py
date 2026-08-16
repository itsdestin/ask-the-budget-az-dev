"""Per-agency label error rates, and a simulator that writes nothing.

This is the instrument the label fix is calibrated on. It exists because the
alternative -- change the matcher, re-label, then look -- writes 83,016 rows
before anyone knows whether the change helped.

The per-agency split is the load-bearing part. A single corpus-wide number
cannot distinguish "fixed the osteopathic defect" from "unlabelled half of
Corrections", and those have opposite value.
"""
from __future__ import annotations

from identity.label_audit import audit_labels


def _mentions(text: str, name: str) -> bool:
    """Test double for the corroboration rule — substring, deliberately dumb,
    so these specs measure the AUDIT and not the rule Task 3 calibrates."""
    return name.lower() in text.lower()


def test_a_document_no_chunk_of_which_mentions_its_label_is_an_error():
    a = audit_labels(
        chunks_by_doc={"d1": ["General Fund revenue collections"]},
        stamps_by_doc={"d1": ["agency:ost"]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        mentions=_mentions,
    )
    assert a.per_agency["agency:ost"].unmentioned == 1
    assert a.per_agency["agency:ost"].rate == 1.0
    assert a.total_unmentioned == 1


def test_a_mention_in_ANY_chunk_clears_the_document():
    """Per DOCUMENT, over all its chunks. A per-chunk metric counts the
    FOOTNOTES page of a correct document as an error and can never reach 0."""
    a = audit_labels(
        chunks_by_doc={"d1": ["FOOTNOTES", "The Osteopathic Examiners board"]},
        stamps_by_doc={"d1": ["agency:ost"]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        mentions=_mentions,
    )
    assert a.per_agency["agency:ost"].unmentioned == 0


def test_a_clean_agency_and_a_poisoned_one_are_reported_separately():
    a = audit_labels(
        chunks_by_doc={
            "d1": ["General Fund revenue"],
            "d2": ["Department of Corrections operates the prisons"],
        },
        stamps_by_doc={"d1": ["agency:ost"], "d2": ["agency:adc"]},
        agency_names={
            "agency:ost": "Osteopathic Examiners",
            "agency:adc": "Department of Corrections",
        },
        mentions=_mentions,
    )
    assert a.per_agency["agency:ost"].rate == 1.0
    assert a.per_agency["agency:adc"].rate == 0.0


def test_an_agency_with_no_documents_is_absent_rather_than_zero_over_zero():
    a = audit_labels(
        chunks_by_doc={"d1": ["anything"]},
        stamps_by_doc={"d1": ["agency:ost"]},
        agency_names={"agency:ost": "Osteopathic", "agency:xyz": "Unused"},
        mentions=_mentions,
    )
    assert "agency:xyz" not in a.per_agency


def test_the_simulator_writes_nothing_and_reports_what_WOULD_change():
    """Calibration must be free and reversible. The simulator takes a
    resolver callable so a task can compare today's matcher against a
    candidate without touching the corpus."""
    from identity.label_audit import simulate

    rows = [
        {"chunk_id": "d1-0001", "doc_id": "d1", "text": "Board of Barbers",
         "section_path": [], "is_table": False, "source_url": None,
         "agency_canonical_ids": ["agency:ost"]},
    ]
    out = simulate(
        rows=rows,
        agency_names={"agency:bar": "Barbers, Board of"},
        resolver=lambda **kw: ["agency:bar"],
    )
    assert out == {"d1-0001": ["agency:bar"]}
    # the input row is untouched
    assert rows[0]["agency_canonical_ids"] == ["agency:ost"]
