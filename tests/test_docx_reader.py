"""Tests for chunking/readers/docx_reader.py."""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.readers.docx_reader import DocxReader, parse_bill_body, parse_bill_heading
from chunking.readers.types import (
    DocxParagraph,
    ExtractedDocument,
    Section,
)

FIXTURE_SB1735 = Path(__file__).parent / "fixtures" / "docx-sb1735-sample.json"


def test_docx_reader_returns_extracted_document():
    doc = DocxReader().read(FIXTURE_SB1735)
    assert isinstance(doc, ExtractedDocument)
    assert doc.extractor == "python-docx"
    # DOCX has no pages — uniform shape leaves it empty
    assert doc.pages == []


def test_docx_reader_detects_part_1_agency_sections():
    """Part 1 agency tables: Normal-style heading with all-caps department name."""
    doc = DocxReader().read(FIXTURE_SB1735)
    part_1 = [s for s in doc.sections if s.style == "Normal"]
    assert len(part_1) == 2
    headings = {s.heading_text for s in part_1}
    assert "DEPARTMENT OF CORRECTIONS" in headings
    assert "ARIZONA HEALTH CARE COST CONTAINMENT SYSTEM" in headings


def test_docx_reader_part_1_section_carries_line_items_as_body():
    doc = DocxReader().read(FIXTURE_SB1735)
    adc = next(s for s in doc.sections if s.heading_text == "DEPARTMENT OF CORRECTIONS")
    # Two body paragraphs (P 06-1 line items), each with a tab-split cells field
    assert len(adc.body_blocks) == 2
    body0 = adc.body_blocks[0]
    assert isinstance(body0, DocxParagraph)
    assert body0.style == "P 06-1"
    assert body0.cells == ["Operating Lump Sum", "11,005,600"]


def test_docx_reader_detects_real_bill_part_1_with_sec_prefix():
    """Real-bill Part-1 dept headings use `Sec. NN.  <ALL-CAPS NAME>`, not bare
    ALL-CAPS as the synthetic fixture had. WS6 integration finding 2026-05-06:
    SB 1735 has 90+ such headings (numbered or unnumbered Sec.), peppered with
    NBSP whitespace. Without this case the entire bill body collapses into one
    section and agency-stamping rate drops to 1/49.
    """
    from chunking.readers.docx_reader import DocxReader as _Reader

    reader = _Reader()
    cases = [
        # Numbered Sec. with regular spaces
        ("Normal", "Sec. 31.  STATE DEPARTMENT OF CORRECTIONS"),
        # Unnumbered Sec. (blank number — appears in bills where the renumber
        # pass hasn't run) with regular spaces
        ("Normal", "Sec.   ARIZONA HEALTH CARE COST CONTAINMENT SYSTEM"),
        # NBSP variant — Word writes \xa0 between Sec. and the number
        ("Normal", "Sec.\xa031.\xa0\xa0STATE DEPARTMENT OF CORRECTIONS"),
        # Apostrophe in dept name (Governor's Office of Equal Opportunity)
        ("Normal", "Sec.   GOVERNOR'S OFFICE OF EQUAL OPPORTUNITY"),
    ]
    for style, text in cases:
        assert reader._is_section_heading(style, text), (
            f"expected heading-detection on real-bill shape: ({style!r}, {text!r})"
        )

    # Negative cases — body text that LOOKS Sec.-ish but isn't a Part-1 heading
    non_headings = [
        # Lowercase body sentence — not a heading
        ("Normal", "Some lower case body text describing appropriations."),
        # Sec.-prefixed but body is mixed-case (this is a Part-2 SEC heading
        # rendered on Normal style — the SEC-style branch should catch it via
        # explicit style, not content; we intentionally don't claim it as Part-1)
        ("Normal", "Sec. 18. Supplemental appropriation; Department of Corrections; FY 2026"),
    ]
    for style, text in non_headings:
        assert not reader._is_section_heading(style, text), (
            f"expected NOT-a-heading: ({style!r}, {text!r})"
        )


def test_docx_reader_detects_part_2_provisions():
    """Part 2 provisions: SEC 06-18 / SEC 06-19 / etc."""
    doc = DocxReader().read(FIXTURE_SB1735)
    sec_06_18 = [s for s in doc.sections if s.style == "SEC 06-18"]
    assert len(sec_06_18) == 2
    sec_06_19 = [s for s in doc.sections if s.style == "SEC 06-19"]
    assert len(sec_06_19) == 1


def test_docx_reader_section_carries_paragraph_id():
    doc = DocxReader().read(FIXTURE_SB1735)
    sec18s = [s for s in doc.sections if s.style == "SEC 06-18"]
    assert sec18s[0].heading_paragraph_id == "p:00A14B06"


def test_docx_reader_section_body_runs_until_next_section():
    doc = DocxReader().read(FIXTURE_SB1735)
    sec18s = [s for s in doc.sections if s.style == "SEC 06-18"]
    # First SEC 06-18 has one body paragraph (Normal style follow-up); second
    # SEC 06-18 also has one body paragraph; SEC 06-19 has one body paragraph.
    assert len(sec18s[0].body_blocks) == 1
    body = sec18s[0].body_blocks[0]
    assert isinstance(body, DocxParagraph)
    assert "An additional $500,000" in body.text


def test_docx_reader_section_parsed_heading_for_sec_06_18():
    doc = DocxReader().read(FIXTURE_SB1735)
    sec18s = [s for s in doc.sections if s.style == "SEC 06-18"]
    parsed = sec18s[0].parsed_heading
    # cross-doc-relationships §9: <action>; <target>; <fiscal_year>; ...
    assert parsed["action"] == "Supplemental appropriation"
    assert parsed["target"] == "Department of Corrections"
    assert parsed["fiscal_year"] == 2026
    assert "building renewal" in parsed["modifiers"]


def test_docx_reader_section_ars_refs_captured_across_heading_and_body():
    doc = DocxReader().read(FIXTURE_SB1735)
    sec18s = [s for s in doc.sections if s.style == "SEC 06-18"]
    refs = sec18s[0].ars_refs
    # The heading + body together cite "section 41-792.01" twice — dedupe to one
    assert refs == ["41-792.01"]


def test_docx_reader_captures_multiple_distinct_ars_refs():
    doc = DocxReader().read(FIXTURE_SB1735)
    # The second SEC 06-18 cites BOTH 35-1 and 36-2901 in its body.
    sec18s = [s for s in doc.sections if s.style == "SEC 06-18"]
    refs = sec18s[1].ars_refs
    assert "35-1" in refs
    assert "36-2901" in refs


# --- module-level utilities --------------------------------------------------


def test_parse_bill_heading_supplemental_appropriation():
    parsed = parse_bill_heading(
        "Sec. 18. Supplemental appropriation; Department of Corrections; FY 2026; building renewal; section 41-792.01."
    )
    assert parsed["action"] == "Supplemental appropriation"
    assert parsed["target"] == "Department of Corrections"
    assert parsed["fiscal_year"] == 2026
    assert "building renewal" in parsed["modifiers"]
    assert "section 41-792.01" in parsed["modifiers"]


def test_parse_bill_heading_appropriation_reduction():
    parsed = parse_bill_heading(
        "Sec. 19. Appropriation reduction; Arizona Health Care Cost Containment System; FY 2026; restoration."
    )
    assert parsed["action"] == "Appropriation reduction"
    assert parsed["target"] == "Arizona Health Care Cost Containment System"
    assert parsed["fiscal_year"] == 2026


def test_parse_bill_heading_unknown_action_falls_through():
    """Unknown action types preserve original heading text and mark action='other'."""
    parsed = parse_bill_heading(
        "Sec. 99. Some heading without standard action prefix; agency."
    )
    assert parsed["action"] == "other"
    assert "Some heading without standard action prefix" in parsed["original"]


def test_parse_bill_heading_missing_fiscal_year():
    parsed = parse_bill_heading("Sec. 5. Appropriation; Department of X.")
    assert parsed["action"] == "Appropriation"
    assert parsed["fiscal_year"] is None


def test_parse_bill_body_extracts_ars_refs():
    refs = parse_bill_body(
        "An additional $500,000 is appropriated to the department for FY 2026 "
        "for building renewal pursuant to section 41-792.01, A.R.S., and "
        "subject to section 36-2901.01, A.R.S."
    )
    assert refs == ["41-792.01", "36-2901.01"]


def test_parse_bill_body_dedupes_repeated_refs():
    refs = parse_bill_body(
        "Pursuant to section 35-142, A.R.S. See also section 35-142, A.R.S."
    )
    assert refs == ["35-142"]


def test_parse_bill_body_handles_no_refs():
    refs = parse_bill_body("No statute citation in this paragraph.")
    assert refs == []
