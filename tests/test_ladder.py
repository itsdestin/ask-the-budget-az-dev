"""Tests for ingest/ladder.py — the ordered extraction attempts (spec T7).

`ladder_for` is deliberately dumb: it consults the registry for the
DECLARED preference, applies inspection's one rule (no text layer -> OCR),
and otherwise never reorders anything. The interesting failure modes are
therefore about what it does NOT do -- reorder, special-case a doc_type,
or invent a rung the chunker can't read -- which is why several tests below
check the registry and reader side of the seam directly rather than trusting
`ladder_for`'s own opinion of itself.
"""
from __future__ import annotations

from ingest.inspection import SourceInspection
from ingest.ladder import ladder_for

TEXT = SourceInspection("pdf", 100, has_text_layer=True)
SCANNED = SourceInspection("pdf", 100, has_text_layer=False)
UNKNOWN = SourceInspection("pdf", None, has_text_layer=None)
DOCX = SourceInspection("docx", None, has_text_layer=True)
SCANNED_DOCX = SourceInspection("docx", None, has_text_layer=False)


def test_an_odl_first_pdf_gets_the_full_ladder():
    assert ladder_for("afr", "pdf", TEXT) == [
        "opendataloader", "mineru", "mineru-ocr",
    ]


def test_a_mineru_first_pdf_starts_below_opendataloader():
    """The declared preference sets the starting rung; nothing above it runs."""
    assert ladder_for("baseline-per-agency", "pdf", TEXT) == [
        "mineru", "mineru-ocr",
    ]


def test_a_pdf_with_no_text_layer_goes_straight_to_ocr():
    assert ladder_for("afr", "pdf", SCANNED) == ["mineru-ocr"]


def test_an_inspection_failure_gets_the_full_ladder_not_ocr_only():
    """None means inspection could not tell -- e.g. `import fitz` failing in
    a broken install, not a positive scan finding -- and must fall through
    to the full ladder exactly like TEXT does. `has_text_layer` is `bool |
    None`, and None is falsy in Python, so a version of this check written
    as `if not inspection.has_text_layer` would treat "we don't know" the
    same as "it's a scan" and route every uninspectable PDF to the slowest
    rung with no signal anywhere that inspection had actually failed."""
    assert ladder_for("afr", "pdf", UNKNOWN) == [
        "opendataloader", "mineru", "mineru-ocr",
    ]


def test_a_mineru_first_pdf_with_no_text_layer_also_goes_straight_to_ocr():
    """Inspection's rule overrides the declared preference too -- it is not
    only a truncation of the ODL-first ladder. If the scan check were
    written as `if preferred == "opendataloader" and not has_text_layer`,
    a scanned baseline-per-agency page would silently start on plain
    `mineru`, which cannot read a scan either, and burn the same hours
    OCR exists to avoid."""
    assert ladder_for("baseline-per-agency", "pdf", SCANNED) == ["mineru-ocr"]


def test_docx_has_no_ladder():
    """The structure is in the file and there is no second tool to try."""
    assert ladder_for("budget-bill", "docx", DOCX) == ["python-docx"]


def test_docx_ignores_the_text_layer_rule():
    """The OCR rung is PDF-only -- there is no OCR extractor for DOCX, so a
    DOCX with no text layer still gets its one declared rung rather than an
    empty ladder or a rung the dispatcher can't run."""
    assert ladder_for("budget-bill", "docx", SCANNED_DOCX) == ["python-docx"]


def test_the_first_rung_matches_todays_shipped_routing():
    """The safety net for the whole change.

    EVERY (doc_type, format) pair the registry knows must still START on the
    extractor it uses today, for any file that has a text layer. A different
    first rung means different chunk text, different chunk_ids, and broken
    eval ground truth on the next re-ingest.

    Note there is no per-type special-casing here: with tagging removed from
    inspection, one inspection value covers every PDF type, which is itself
    evidence the rule that needed the special case was not carrying weight.
    """
    from ingest.dispatcher import EXTRACTOR_REGISTRY, pick_extractor

    for (doc_type, fmt) in EXTRACTOR_REGISTRY:
        inspection = TEXT if fmt == "pdf" else DOCX
        assert ladder_for(doc_type, fmt, inspection)[0] == pick_extractor(doc_type, fmt).name


def test_every_rung_can_actually_be_chunked():
    """The seam that a review caught and this plan originally missed.

    A rung name is used TWICE: once to extract, and once to choose the
    reader that parses that extractor's output. A rung the chunker has no
    reader for cannot complete, and would surface as a confusing failure
    days into execution rather than here.

    The rung list is DERIVED, not hardcoded. A prior version wrote out
    ("opendataloader", "mineru", "mineru-ocr", "python-docx") by hand, and a
    reviewer proved that stays green even when a bogus "pdfplumber" rung is
    added to `_PDF_LADDER` -- nothing tied the two lists together, so the
    one test meant to catch an unreadable rung couldn't see it. Deriving
    from `_PDF_LADDER` plus the registered extractor names is what makes
    that mutation visible here.
    """
    from ingest.dispatcher import _EXTRACTOR_CLASSES
    from ingest.ladder import _PDF_LADDER
    from chunking.builder import _READER_REGISTRY

    rungs = set(_PDF_LADDER) | set(_EXTRACTOR_CLASSES)
    for rung in rungs:
        assert rung in _READER_REGISTRY


def test_an_unknown_combination_has_no_ladder():
    assert ladder_for("budget-bill", "pdf", TEXT) == []


def test_ladder_never_reorders_the_pdf_cost_sequence():
    """Whatever the starting rung, the SUFFIX must stay in the fixed cost
    order (opendataloader, mineru, mineru-ocr) with mineru-ocr always last.
    A ladder that dropped this guarantee could route a document into an
    infinite-cost loop or skip a legitimately cheaper fallback."""
    for doc_type, fmt in (("afr", "pdf"), ("baseline-per-agency", "pdf")):
        rungs = ladder_for(doc_type, fmt, TEXT)
        assert rungs[-1] == "mineru-ocr"
        assert rungs == sorted(
            rungs, key=["opendataloader", "mineru", "mineru-ocr"].index
        )


def test_ladder_for_returns_a_fresh_list_each_call():
    """`_PDF_LADDER` is a shared module-level tuple; the returned list must
    not be a view onto it (or onto anything else callers could mutate and
    corrupt for every later call)."""
    first = ladder_for("afr", "pdf", TEXT)
    first.append("mutated")
    second = ladder_for("afr", "pdf", TEXT)
    assert second == ["opendataloader", "mineru", "mineru-ocr"]
