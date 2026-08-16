"""Compose `{Name} — FY {year} {Book}` (spec I5) and settle supplier
disagreements (spec I1).

4,950 documents already use this format; this makes the minority match the
majority rather than re-titling the majority.

The uniqueness rule is not decoration. Measured 2026-08-16: 77 documents in
30 groups have a parent agency and one of its sub-programmes in the same
book and year (`doa` with `doa-apf`; `des` with `desage`, `desdd`, …). If
both compose from the same agency name they become two indistinguishable
rows — a NEW defect manufactured by the fix, which the duplicate-title
metric would then report as a failure.
"""
from __future__ import annotations

from identity.compose import compose_title, resolve_supplier_disagreement


def test_the_house_format():
    assert compose_title(
        name="Board of Barbers", fiscal_year=2005, book="Appropriations Report"
    ) == "Board of Barbers — FY 2005 Appropriations Report"


def test_a_decorated_name_is_stripped_before_composing():
    assert compose_title(
        name="• General Fund Revenue ......400",
        fiscal_year=2027,
        book="Appropriations Report",
    ) == "General Fund Revenue — FY 2027 Appropriations Report"


def test_a_corrupt_name_refuses_rather_than_guessing():
    import pytest

    with pytest.raises(ValueError) as e:
        compose_title(
            name="Osteopathic Examiners, Arizona ...  342  Board of...",
            fiscal_year=2026,
            book="Appropriations Report",
        )
    assert "dot leaders" in str(e.value)


def test_a_distinguisher_is_appended_when_one_is_supplied():
    """The sub-programme case: parent and child in the same book and year."""
    assert compose_title(
        name="Administration, Arizona Department of",
        fiscal_year=2016,
        book="Appropriations Report",
        distinguisher="Automation Projects Fund",
    ) == (
        "Administration, Arizona Department of (Automation Projects Fund) "
        "— FY 2016 Appropriations Report"
    )


def test_the_stamp_beats_the_supplier_when_they_disagree():
    chosen, note = resolve_supplier_disagreement(
        supplied="Agriculture, Arizona Department of",
        stamp_name="Board of Barbers",
        doc_text="Board of Barbers  Executive Director: Mario J. Herrera",
    )
    assert chosen == "Board of Barbers"
    assert note is not None and "Agriculture" in note


def test_agreement_records_nothing():
    chosen, note = resolve_supplier_disagreement(
        supplied="Board of Barbers",
        stamp_name="Board of Barbers",
        doc_text="Board of Barbers  Executive Director: Mario J. Herrera",
    )
    assert chosen == "Board of Barbers"
    assert note is None


def test_an_UNCORROBORATED_stamp_does_not_overrule_the_supplier():
    """I1: one witness is never sufficient. If the document's own text does
    not back the stamp, there is no second witness and nothing is repaired."""
    chosen, note = resolve_supplier_disagreement(
        supplied="Agriculture, Arizona Department of",
        stamp_name="Osteopathic Examiners",
        doc_text="General Fund revenue collections exceeded forecast.",
    )
    assert chosen == "Agriculture, Arizona Department of"
    assert note is not None and "not corroborated" in note
