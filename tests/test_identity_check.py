"""The instrument whose ABSENCE let all six defects ship (spec I13).

Runs against injected fixtures, never a real LanceDB directory — the suite
must survive a fresh clone. The real-corpus run is a manual eval step.

Two properties are pinned because getting either wrong makes the number
meaningless:
  * the stamping metric is per DOCUMENT, over all its chunks — a per-chunk
    version reports the boilerplate page of a correct document as an error
    and can never reach zero;
  * the check never reports how many names were produced.
"""
from __future__ import annotations

from eval.identity_check import check_corpus


def _doc(title, url=None, fy=2005, book="Appropriations Report", doc_type=None):
    return {"title": title, "source_url": url, "fiscal_year": fy, "book": book,
            "doc_type": doc_type}


def test_a_title_names_a_different_agency_than_the_text_is_counted():
    report = check_corpus(
        documents={"jlbc-approps-fy2005-bar": _doc(
            "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
            "https://www.azjlbc.gov/05app/bar.pdf",
        )},
        chunks_by_doc={"jlbc-approps-fy2005-bar": [
            "Board of Barbers  Executive Director: Mario J. Herrera",
        ]},
        agency_names={"agency:agr": "Agriculture, Arizona Department of",
                      "agency:bar": "Board of Barbers"},
        stamps_by_doc={"jlbc-approps-fy2005-bar": ["agency:bar"]},
    )
    assert report.title_names_wrong_agency == 1


def test_a_boilerplate_chunk_does_NOT_make_a_correct_document_a_mis_stamp():
    """The document mentions its agency SOMEWHERE. A per-chunk metric would
    count its FOOTNOTES page as an error; this one must not."""
    report = check_corpus(
        documents={"jlbc-approps-fy2026-ost": _doc(
            "Osteopathic Examiners — FY 2026 Appropriations Report",
            "https://www.azjlbc.gov/26ar/ost.pdf",
        )},
        chunks_by_doc={"jlbc-approps-fy2026-ost": [
            "FOOTNOTES",
            "The Board of Osteopathic Examiners licenses physicians.",
        ]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        stamps_by_doc={"jlbc-approps-fy2026-ost": ["agency:ost"]},
    )
    assert report.documents_never_mentioning_stamp == 0


def test_a_document_no_chunk_of_which_mentions_its_stamp_is_counted():
    report = check_corpus(
        documents={"governor-governors-budget-fy2026": _doc("Executive Budget")},
        chunks_by_doc={"governor-governors-budget-fy2026": [
            "General Fund revenue collections exceeded forecast.",
        ]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        stamps_by_doc={"governor-governors-budget-fy2026": ["agency:ost"]},
    )
    assert report.documents_never_mentioning_stamp == 1


def test_titles_outside_the_format_are_counted():
    report = check_corpus(
        documents={
            "a": _doc("Medical Board, Arizona"),
            "b": _doc("JLBC FY2025 — Agriculture, Arizona Department of"),
            "c": _doc("Agriculture, Arizona Department of — FY 2005 Appropriations Report"),
        },
        chunks_by_doc={"a": [""], "b": [""], "c": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.titles_outside_format == 2


def test_duplicate_titles_are_counted_as_a_CROSS_CHECK_not_a_second_proof():
    report = check_corpus(
        documents={
            "jlbc-approps-fy2005-agr": _doc("Agriculture — FY 2005 Appropriations Report"),
            "jlbc-approps-fy2005-bar": _doc("Agriculture — FY 2005 Appropriations Report"),
        },
        chunks_by_doc={"jlbc-approps-fy2005-agr": [""], "jlbc-approps-fy2005-bar": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.duplicate_titles == 2


def test_a_slug_title_is_REPORTED_and_never_counted_as_a_failure():
    report = check_corpus(
        documents={"jlbc-approps-fy2005-axsacute": _doc(
            "AXSACUTE — FY 2005 Appropriations Report")},
        chunks_by_doc={"jlbc-approps-fy2005-axsacute": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.uninformative_titles == 1
    assert report.titles_outside_format == 0
    assert report.validator_failures == 0


def test_a_fiscal_note_document_is_excluded_from_the_budget_metrics():
    """Fiscal notes are out of scope for I13 (spec + identity/validator.py
    docstring) — their titles are a deliberate app feature
    ('Fiscal Note - HB 2172: <strike>...</strike> (NOW: ...)'), not a naming
    defect, and none of the three suppliers this module distrusts apply to
    them. Measured 2026-08-16: including them inflated titles_outside_format
    2627 -> 523 budget-only and duplicate_titles 376 -> 218 budget-only
    (audit: 218, exact)."""
    fiscal_note_title = (
        "Fiscal Note - HB 2172: <strike>technology transfer</strike> "
        "(NOW: solar device; tax credit)"
    )
    report = check_corpus(
        documents={
            "fn-hb2172": _doc(fiscal_note_title, doc_type="fiscal-note"),
        },
        chunks_by_doc={"fn-hb2172": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.titles_outside_format == 0
    assert report.uninformative_titles == 0
    assert report.validator_failures == 0
    assert report.duplicate_titles == 0
    assert report.fiscal_notes_excluded == 1


def test_a_document_mentioning_only_a_SHORT_shared_word_of_its_agency_still_counts_as_not_mentioning_it():
    """agency:ost measured 2026-08-16: "any distinctive word" let ordinary
    shared words like "medicine" or "surgery" pass a document that never
    actually discusses the Board of Osteopathic Examiners — 142 mis-stamps
    found corpus-wide vs the audit's 721 for this one agency alone.

    UPDATED 2026-08-16 (Task 3 recalibration): "longest word" itself was
    then measured and rejected too — for "Highway Safety, Governor's Office
    of" the longest word is "governor", present on nearly every budget
    document, so an unrelated page could pass. `mentions_agency` now
    requires a MAJORITY (>= half, minimum 1) of an agency's distinctive
    words of >= 3 characters — see its docstring for the full three-way
    comparison and why a fourth rule shipped. `agency:ost` has FOUR
    distinctive words {osteopathic, examiners, medicine, surgery}, so a
    majority needs 2; mentioning only ONE of them ("surgery") is still a
    minority and must still count as not mentioning the stamp. (Mentioning
    two of the four — exactly half — now legitimately corroborates; that
    boundary is exercised directly in `tests/test_identity_validator.py`,
    not duplicated here.)"""
    report = check_corpus(
        documents={"jlbc-approps-fy2026-x": _doc(
            "Some Other Title — FY 2026 Appropriations Report")},
        chunks_by_doc={"jlbc-approps-fy2026-x": [
            "General surgery funding increased this year.",
        ]},
        agency_names={
            "agency:ost": "Osteopathic Examiners in Medicine and Surgery, "
                          "Arizona Board of",
        },
        stamps_by_doc={"jlbc-approps-fy2026-x": ["agency:ost"]},
    )
    assert report.documents_never_mentioning_stamp == 1


def test_the_wrong_agency_rule_does_NOT_fire_when_the_stamp_is_uncorroborated():
    """Corroboration is `mentions_agency` (Task 3, 2026-08-16: majority of an
    agency's >= 3-character distinctive words, minimum 1 — see its
    docstring). `agency:ban` ("Financial Institutions, Department of") has
    exactly TWO distinctive words {financial, institutions}, so for THIS
    agency a majority is just one word — mentioning "financial" alone WOULD
    now corroborate it (a real, measured, and accepted property of the
    majority rule for two-word names; see `mentions_agency`'s docstring).
    So this fixture mentions NEITHER word, to test what it always meant to
    test: a title differing from a genuinely uncorroborated stamp (zero
    matching words, not one) must not be flagged as a wrong-agency defect —
    an uncorroborated stamp is a stamping problem (separate, later work; see
    the KNOWN false-positive comment in the source), not evidence the TITLE
    is wrong."""
    report = check_corpus(
        documents={"jlbc-approps-fy2005-x": _doc(
            "Agriculture, Arizona Department of — FY 2005 Appropriations Report")},
        chunks_by_doc={"jlbc-approps-fy2005-x": [
            "This page references appropriations matters only, nothing else.",
        ]},
        agency_names={
            "agency:ban": "Financial Institutions, Department of",
            "agency:agr": "Agriculture, Arizona Department of",
        },
        stamps_by_doc={"jlbc-approps-fy2005-x": ["agency:ban"]},
    )
    assert report.title_names_wrong_agency == 0


def test_a_section_document_is_excluded_from_the_wrong_agency_metric_and_counted_separately():
    """`jlbc-baseline-fy2021-491`, real doc_id: a bare page-number slug (a
    summary chapter, not any one agency's pages) titled "General Fund
    Revenue — FY 2021 Baseline". Its chunk text genuinely corroborates two
    OTHER agencies (Board of Barbers, Dept. of Agriculture — a summary
    chapter necessarily mentions many), and "revenue" happens to be the
    Department of Revenue's longest distinctive word — exactly the shape
    that, before this fix, flagged the document as naming the wrong
    agency. A chapter that names no agency of its own cannot be "wrong"
    about which agency it names. `is_section_document` uses the identical
    slug rule `identity.repair` already vetoes stamp-composition on (both
    call the one shared `identity.validator.is_section_document`), so the
    two modules can never disagree about what counts as a section."""
    report = check_corpus(
        documents={"jlbc-baseline-fy2021-491": _doc(
            "General Fund Revenue — FY 2021 Baseline",
            "https://www.azjlbc.gov/21baseline/491.pdf", fy=2021, book="Baseline",
        )},
        chunks_by_doc={"jlbc-baseline-fy2021-491": [
            "Board of Barbers   150,000\n"
            "Agriculture, Arizona Department of   6,789,000",
        ]},
        agency_names={
            "agency:bar": "Board of Barbers",
            "agency:agr": "Agriculture, Arizona Department of",
            "agency:dor": "Revenue, Arizona Department of",
        },
        stamps_by_doc={"jlbc-baseline-fy2021-491": ["agency:bar", "agency:agr"]},
    )
    assert report.title_names_wrong_agency == 0
    assert report.section_documents == 1


def test_the_report_never_carries_a_production_count():
    """Gate on the ERROR rate, never coverage — spec I13, and the specific
    lesson the citation work paid for."""
    report = check_corpus(
        documents={"a": _doc("Alpha — FY 2026 Baseline")},
        chunks_by_doc={"a": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    fields = report.as_dict().keys()
    assert not any(
        k for k in fields
        if "produced" in k or "coverage" in k or "linked" in k
    )
