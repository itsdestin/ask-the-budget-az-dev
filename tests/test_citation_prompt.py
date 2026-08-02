"""The prompt must stop asking the model to cite figures.

The system links figures now. Leaving the old instruction in place would
pay for citation round-trips whose results are discarded, and would
re-introduce the quote-not-found failures the linker exists to remove.
"""
from __future__ import annotations

from harness.prompt import build_system_prompt

PROMPT = build_system_prompt(corpus="budget", tier="standard")


def test_prompt_tells_the_model_figures_are_linked_automatically():
    lowered = PROMPT.lower()
    assert "automatically" in lowered
    assert "figure" in lowered or "number" in lowered


def test_prompt_still_asks_for_prose_citations():
    # cite() survives, scoped to non-numeric claims.
    assert "cite(" in PROMPT or "`cite`" in PROMPT


def test_prompt_does_not_ask_the_model_to_quote_table_rows():
    # Table rows do not exist as contiguous text in extracted chunks, so
    # any instruction to quote one produces a guaranteed failure.
    lowered = PROMPT.lower()
    assert "quote the table row" not in lowered
    assert "quote the row" not in lowered
