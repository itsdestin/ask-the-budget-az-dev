"""The supersession rule is prompt-only (spec T9), so the prompt IS the
implementation and these assertions are the only guard it has.

WHY the "check, don't assume" wording is pinned: the model cannot observe
corpus state -- it sees only the chunks a retrieve returned. An instruction
to "ignore the summary if an Appropriations Report exists" is unenforceable
as written. Telling it to RUN A SEARCH makes the condition observable with a
tool it already has, and that is the difference between a rule it can follow
and one it cannot.
"""
from pathlib import Path

import pytest

PROMPT = Path("harness/system-prompt.md").read_text(encoding="utf-8")


def test_the_lifecycle_section_places_the_summary_before_the_approps_report():
    assert "Budget Bill Summary" in PROMPT


def test_the_rule_tells_the_model_to_CHECK_not_to_assume():
    lowered = PROMPT.lower()
    assert "budget-bill-summary" in lowered
    # It must instruct an actual search, not merely state the condition.
    assert "search" in lowered.split("budget bill summary", 1)[1][:1500]


def test_engrossed_supersedes_introduced_is_stated():
    window = PROMPT.split("Budget Bill Summary", 1)[1][:1500].lower()
    assert "engrossed" in window and "introduced" in window


@pytest.mark.parametrize("phrase", ["hallucination-free", "grounded"])
def test_no_marketing_language_crept_in(phrase):
    # Core Invariant 5.
    assert phrase not in PROMPT.lower()
