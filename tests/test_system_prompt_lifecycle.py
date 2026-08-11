"""The supersession rule is prompt-only (spec T9), so the prompt IS the
implementation and these assertions are the only guard it has.

WHY the "check, don't assume" wording is pinned: the model cannot observe
corpus state -- it sees only the chunks a retrieve returned. An instruction
to "ignore the summary if an Appropriations Report exists" is unenforceable
as written. Telling it to RUN A SEARCH makes the condition observable with a
tool it already has, and that is the difference between a rule it can follow
and one it cannot.
"""
import re
from pathlib import Path

import pytest

PROMPT = Path("harness/system-prompt.md").read_text(encoding="utf-8")


def test_the_lifecycle_section_places_the_summary_before_the_approps_report():
    # Table row 3 (In progress / budget-bill-summary) must precede row 4
    # (Enactment / approps-per-agency) -- an earlier version of this test
    # only checked substring PRESENCE, which would pass even if the text
    # were moved to the very end of the document. Anchoring on the
    # `budget-bill-summary` row and the (unique, one-occurrence) Enactment
    # row makes the assertion actually about ORDER, matching the test's
    # own name.
    summary_idx = PROMPT.index("`budget-bill-summary`")
    enactment_row_idx = PROMPT.index("4. Enactment")
    assert summary_idx < enactment_row_idx


def test_the_rule_tells_the_model_to_CHECK_not_to_assume():
    lowered = PROMPT.lower()
    assert "budget-bill-summary" in lowered
    # It must instruct an actual search, not merely state the condition.
    window = lowered.split("budget bill summary", 1)[1][:1500]
    assert "search" in window
    # A doc_type-only search is not enough to prove the fiscal year's
    # Approps Report has landed -- the doc_type has many PRIOR-year
    # editions in the corpus, so a query that omits fiscal_year would
    # find one almost every time and wrongly conclude the current year's
    # report exists. Pin the filter, not just the presence of "search".
    #
    # WHY this is checked against approps_check_bullet, not the wider
    # `window`: the Engrossed-supersedes-Introduced bullet a few lines
    # below independently mentions its OWN `fiscal_year` filter, for an
    # unrelated search. `assert "fiscal_year" in window` is satisfied by
    # either bullet's mention, so it stayed green when a reviewer reverted
    # ONLY this (the Approps-check) bullet back to a doc_type-only filter
    # -- the exact Critical regression this pin exists to catch. Slicing
    # up to the Engrossed bullet's own name -- a phrase that carries that
    # bullet's meaning, not incidental wording -- isolates the
    # Approps-check bullet specifically. Whitespace is collapsed first so
    # a harmless line-wrap reflow of the surrounding prose can't shift
    # where that anchor falls and break this pin for no reason.
    normalized = re.sub(r"\s+", " ", window)
    approps_check_bullet = normalized[
        : normalized.index("engrossed supersedes introduced")
    ]
    assert "fiscal_year" in approps_check_bullet


def test_engrossed_supersedes_introduced_is_stated():
    window = PROMPT.split("Budget Bill Summary", 1)[1][:1500].lower()
    assert "engrossed" in window and "introduced" in window


@pytest.mark.parametrize("phrase", ["hallucination-free", "grounded"])
def test_no_marketing_language_crept_in(phrase):
    # Core Invariant 5.
    assert phrase not in PROMPT.lower()
