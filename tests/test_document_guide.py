"""The guidance the model gets when it writes a document.

These are CONTENT guards as much as code guards. Two rules in the guide
text would be silently costly to lose, so each has a test naming the
consequence — see the two tests at the bottom of this file.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import guides
from harness.prompt import build_system_prompt
from harness.tools import TOOLS, ToolExecutor

# Both corpora render the same create_document section (it sits outside
# every `{{#when corpus=…}}` block), so a pointer that only survives in
# one of them is a defect the single-corpus form would hide.
CORPORA = ("budget", "fiscal_notes")


def _executor() -> ToolExecutor:
    return ToolExecutor("conv-1", "budget", "standard")


def _schema(name: str) -> dict:
    return next(t for t in TOOLS if t["function"]["name"] == name)


def _flat(text: str) -> str:
    """Whitespace-normalized lowercase, for matching prose that wraps.

    Every content assertion below goes through this. The Task 1 review
    found the plan's literal `"as the source writes"` never matched
    because the guide wraps mid-phrase; the same hazard applies to the
    system prompt, which is hard-wrapped at ~70 columns.
    """
    return " ".join(text.lower().split())


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


# ---------------------------------------------------------------------------
# Task 2 — the tool, and the two pointers that make it discoverable
# ---------------------------------------------------------------------------


def test_the_tool_is_registered_and_takes_an_optional_report_type():
    params = _schema("document_guide")["function"]["parameters"]
    assert params["properties"]["report_type"]["enum"] == list(guides.REPORT_TYPES)
    # Optional on purpose: the handler falls back to the default, so a
    # required argument would only convert a harmless guess into a failed
    # call the model has to spend a round-trip recovering from.
    assert not params.get("required")
    # Every sibling schema in harness/tools.py closes the object; an open
    # one lets a hallucinated argument through unremarked.
    assert params["additionalProperties"] is False


def test_calling_it_returns_the_guide_for_that_type():
    result = json.loads(
        _executor().execute("document_guide", {"report_type": "comparison"})
    )
    assert result["ok"] is True
    assert result["report_type"] == "comparison"
    assert "The table" in result["guide"]
    assert "Forbidden phrases" in result["guide"]


def test_calling_it_with_no_arguments_returns_the_default():
    result = json.loads(_executor().execute("document_guide", {}))
    assert result["ok"] is True
    assert result["report_type"] == guides.DEFAULT_TYPE


def test_an_unknown_type_reports_the_type_it_actually_used():
    """Reporting the REQUESTED type back would tell the model it got
    comparison guidance when it got the default."""
    result = json.loads(
        _executor().execute("document_guide", {"report_type": "fiscal-note"})
    )
    assert result["report_type"] == guides.DEFAULT_TYPE
    assert result["guide"] == guides.guide_for(guides.DEFAULT_TYPE)


def test_a_malformed_report_type_still_returns_guidance():
    """Models emit `null` and stray types routinely. `_opt_str` swallows a
    wrong type by design (see its docstring), so the tool must not be the
    place a decorative argument costs the analyst their document."""
    for bad in (None, 7, ["comparison"], "  "):
        result = json.loads(
            _executor().execute("document_guide", {"report_type": bad})
        )
        assert result["ok"] is True
        assert result["report_type"] == guides.DEFAULT_TYPE


def test_the_tool_is_dispatchable_by_its_registered_name():
    """The registry and the dispatch table are two separate lists in
    harness/tools.py. A tool present in one and absent from the other
    advertises itself to the model and then answers 'there is no tool
    named document_guide' — which reads to the model as a system fault."""
    for name in (t["function"]["name"] for t in TOOLS):
        result = json.loads(_executor().execute(name, {}))
        assert "There is no tool named" not in result.get("error", "")


def test_create_document_points_at_the_guide():
    """Spec G9. Nothing enforces the call, so the description is one of
    only two things making the tool discoverable — if it stops mentioning
    it, the feature silently stops being used."""
    assert "document_guide" in _schema("create_document")["function"]["description"]


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_system_prompt_tells_the_model_to_call_it_before_writing(corpus):
    """Spec G9, the other half — and the one that actually drives the
    behaviour, because the prompt is what the model reads before it
    decides to write anything.

    Verified by mutation: deleting the `document_guide` paragraph from
    the `create_document` section of harness/system-prompt.md turns this
    red. A test asserting only the tool-list line would NOT — the name
    appears there too, and a bare name in a list is not an instruction.
    """
    prompt = _flat(build_system_prompt(corpus=corpus, tier="standard"))
    assert "call `document_guide` before you write it" in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_prompt_repeats_the_source_precision_rule_for_answers(corpus):
    """🔴 Spec G5, restated in the prompt on purpose.

    The guide states the answer-versus-document split, but the guide is
    only read on turns that write a document. The rule it protects —
    figures in the ANSWER keep source precision — applies to EVERY turn,
    and `citation/matching.py` refuses an untagged figure below 4 written
    significant digits. If this paragraph goes, the model starts rounding
    in chat and untagged citation coverage falls with nothing failing.
    """
    prompt = _flat(build_system_prompt(corpus=corpus, tier="standard"))
    assert "exactly as the source writes them" in prompt
    assert "$6,043,200" in prompt
