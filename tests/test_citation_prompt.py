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


def test_prompt_bans_announcing_that_citations_were_registered():
    # Observed in a browser 2026-08-02: the model closed an answer with
    # "All citations are now registered. The answer above covers ADOT's
    # FY 2024 enacted appropriations..." The hygiene section already banned
    # "All cites now anchored" — the model simply used different words, so
    # the rule needed to name the BEHAVIOUR, not just three phrasings.
    lowered = PROMPT.lower()
    assert "registered" in lowered
    # And the general form: no closing status paragraph about the answer.
    assert "status" in lowered or "recap" in lowered


def test_prompt_teaches_the_marker_and_the_alias():
    # A concrete example, not just prose: the model reproduces the shape
    # it was shown, and `[[c3]]` is the shape the marker parser accepts.
    assert "[[c3]]" in PROMPT
    assert "alias" in PROMPT.lower()
    # The model must know tags are invisible and verified — otherwise it
    # narrates them, and output-hygiene bans that.
    lowered = PROMPT.lower()
    assert "never mention" in lowered or "invisible" in lowered


def test_prompt_still_bans_citing_figures_via_cite():
    assert "Do not cite dollar figures" in PROMPT


def test_prompt_tells_the_model_not_to_announce_the_automatic_linking():
    # A model told "figures are linked automatically" may helpfully report
    # that it happened. It is UI behaviour; the analyst can see it.
    section = PROMPT.lower()
    assert "do not announce" in section or "never announce" in section
