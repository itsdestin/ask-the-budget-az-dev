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


def _doc(title, url=None, fy=2005, book="Appropriations Report"):
    return {"title": title, "source_url": url, "fiscal_year": fy, "book": book}


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
