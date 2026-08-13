"""The guidance the model gets when it writes a document.

These are CONTENT guards as much as code guards. Two rules in the guide
text would be silently costly to lose, so each has a test naming the
consequence — see the two tests at the bottom of this file.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from harness import guides


def test_every_report_type_has_a_guide():
    for report_type in guides.REPORT_TYPES:
        text = guides.guide_for(report_type)
        assert text.strip(), f"{report_type} guide is empty"


def test_every_guide_file_is_present_on_disk():
    """A missing type file must FAIL, not degrade silently.

    `guides._read` degrades to "" so a packaging slip costs advice rather
    than the turn — which means `guide_for("comparison")` still returns the
    shared block and still reads as non-empty. Without this test, a dropped
    type file would pass the whole suite. Checked on disk, because that is
    the only place the absence is visible.
    """
    for name in (*guides.REPORT_TYPES, "shared"):
        path = Path(guides.__file__).with_name("guides") / f"{name}.md"
        assert path.is_file(), f"{path} is missing"
        assert path.read_text(encoding="utf-8").strip(), f"{path} is empty"


def test_the_shared_style_block_is_included_in_every_type():
    for report_type in guides.REPORT_TYPES:
        assert "Forbidden phrases" in guides.guide_for(report_type)


@pytest.mark.parametrize("bad", ["", "  ", "fiscal-note", "MEMO", None])
def test_an_unknown_type_falls_back_rather_than_failing(bad):
    """A model that guesses a type name should get useful guidance, not a
    failed call it has to spend a round-trip recovering from."""
    assert guides.guide_for(bad) == guides.guide_for(guides.DEFAULT_TYPE)


def test_there_is_no_fiscal_note_type():
    """Spec G2. A fiscal note is a legally-shaped product with an official
    template and a source sign-off gate; Destin's own skill does that job.
    A lookalike built from corpus retrieval could be mistaken for one."""
    assert "fiscal-note" not in guides.REPORT_TYPES


def test_the_answer_versus_document_number_split_is_stated():
    """🔴 THE GUARD THAT MATTERS MOST (spec G5).

    Rounding belongs to the DOCUMENT body only. Documents carry no
    citation chips; chat answers do, and `citation/matching.py` refuses an
    untagged figure below 4 written significant digits outright. If this
    split is ever dropped from the guide, the model rounds in answers too
    and untagged citation coverage falls with NO error anywhere — no test
    fails, no log line, nothing visible until someone re-measures.

    Verified by mutation: deleting the "Rounding applies IN THE DOCUMENT"
    section from shared.md turns this red.

    Whitespace is normalized before matching — CORRECTED FROM THE PLAN,
    whose literal `"as the source writes"` never appeared because the
    guide wraps between "the source" and "writes them". A content guard
    must not break when someone reflows a paragraph in a Markdown file.
    """
    text = " ".join(guides.guide_for("research-memo").lower().split())
    assert "in the answer" in text and "in the document" in text
    assert "as the source writes" in text


def test_no_guide_recommends_numbered_lists():
    """`memo/markdown.py` renders `1)` as an unstyled plain paragraph —
    pinned by tests/test_jlbc_memo.py. The fiscal-note skill mandates
    numbered items, so borrowing its list convention would produce
    visibly broken documents.

    🔴 CORRECTED FROM THE PLAN, which asserted `"numbered list" not in
    text.lower()`. That is unsatisfiable beside the rule it protects — the
    guide states "Use bullets, never numbered lists", and the plan's
    assertion forbids the phrase rather than the practice. Worse, it was
    BACKWARDS as a guard: deleting the rule from the guide would have made
    it PASS. It now asserts the prohibition is present, which is what
    actually has to survive, and separately that no guide demonstrates a
    numbered item.
    """
    for report_type in guides.REPORT_TYPES:
        text = guides.guide_for(report_type)
        assert "bullets, never numbered lists" in text.lower()
        assert "1)" not in text


def test_the_number_rules_match_the_conventions_reference():
    """Pinned against docs/reference/jlbc-document-conventions.md so the
    guide and the reference cannot drift apart."""
    reference = (
        Path(__file__).resolve().parents[1]
        / "docs" / "reference" / "jlbc-document-conventions.md"
    ).read_text(encoding="utf-8")
    shared = guides.guide_for(guides.DEFAULT_TYPE)
    for rule in ("$6.0 million", "$400,000", "FY 2026", "one-time"):
        assert rule in reference, f"{rule} missing from the reference"
        assert rule in shared, f"{rule} missing from the guide"
