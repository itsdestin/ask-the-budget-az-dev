"""The system prompt is the product's single largest quality lever.

These tests are not about wording — they are about the ways the prompt
has actually gone wrong before, and the ways it now CAN go wrong:

* Two different refusal thresholds reaching the model at once (that
  really happened: 0.30 in a tool description, 0.65 in stale comments,
  1.9 in the prompt). The number is injected from
  `harness.constants` in exactly one direction, so a stale literal in
  the template is a test failure, not a mystery.
* Environment assumptions that were true under Claude Code + MCP and
  are false now. An open-weight model told to "not call ToolSearch"
  learns that a tool named ToolSearch exists.
* A template that ships broken. It is packaged data; a missing or
  half-rendered file must say so in English.
* Marketing language Core Invariant 5 forbids.
"""
from __future__ import annotations

import re
import threading

import pytest

from harness.constants import (
    FIRST_CALL_TOP_K_CAP,
    INTENT_TOP_K,
    REFUSAL_THRESHOLD,
    TIER_BUDGETS,
)
from harness.prompt import (
    PromptTemplateError,
    build_system_prompt,
    reset_template_cache,
)

CORPORA = ("budget", "fiscal_notes")
TIERS = tuple(TIER_BUDGETS)


@pytest.fixture(autouse=True)
def _clean_cache():
    # The template is cached process-wide; a test that repoints the path
    # must not leave the next one reading its stub.
    reset_template_cache()
    yield
    reset_template_cache()


def every_rendering() -> list[str]:
    return [
        build_system_prompt(corpus=corpus, tier=tier)
        for corpus in CORPORA
        for tier in TIERS
    ]


# ---------------------------------------------------------------------------
# It renders at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", CORPORA)
@pytest.mark.parametrize("tier", TIERS)
def test_every_corpus_and_tier_renders(corpus, tier):
    prompt = build_system_prompt(corpus=corpus, tier=tier)
    assert len(prompt) > 5_000
    assert prompt.startswith("#")


@pytest.mark.parametrize("corpus", CORPORA)
@pytest.mark.parametrize("tier", TIERS)
def test_no_placeholder_or_block_marker_survives(corpus, tier):
    # A leftover `{{…}}` is the failure mode where the model is told to
    # refuse below "{{REFUSAL_THRESHOLD}}" and refuses at nothing.
    prompt = build_system_prompt(corpus=corpus, tier=tier)
    assert "{{" not in prompt
    assert "}}" not in prompt


def test_the_wire_and_table_corpus_names_render_the_same_prompt():
    # session.py passes the wire name; a Task 8 wiring change that passed
    # the LanceDB table name instead must not silently fall through to
    # the other corpus's scope paragraph.
    assert build_system_prompt(corpus="budget", tier="standard") == build_system_prompt(
        corpus="budget_chunks", tier="standard"
    )
    assert build_system_prompt(
        corpus="fiscal_notes", tier="standard"
    ) == build_system_prompt(corpus="fiscal_note_chunks", tier="standard")


def test_an_unknown_corpus_is_a_loud_programming_error():
    # Better a failed turn with a readable message than a fiscal-note
    # conversation quietly answering as if it searched budget books.
    with pytest.raises(ValueError, match="Unknown corpus"):
        build_system_prompt(corpus="minutes", tier="standard")


def test_an_unknown_tier_degrades_to_the_default_tier():
    # settings.json accepts arbitrary tier names (harness/tools.py makes
    # the same choice for the same reason): a typo must get the cheap
    # posture, never a dead conversation.
    assert build_system_prompt(corpus="budget", tier="stnadard") == build_system_prompt(
        corpus="budget", tier="standard"
    )


# ---------------------------------------------------------------------------
# One threshold, injected
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", CORPORA)
def test_exactly_one_threshold_value_reaches_the_model(corpus):
    prompt = build_system_prompt(corpus=corpus, tier="standard")

    scored_lines = [line for line in prompt.splitlines() if "top_score" in line]
    assert scored_lines, "the prompt no longer tells the model what to compare"
    numbers = {n for line in scored_lines for n in re.findall(r"\d+\.\d+", line)}
    assert numbers == {str(REFUSAL_THRESHOLD)}

    # And nowhere else in the document either. The `$`/digit lookbehind
    # skips dollar figures in the domain primer ($3.1B, $16.56B).
    assert set(re.findall(r"(?<![\d.$])\d\.\d+(?!\d)", prompt)) == {
        str(REFUSAL_THRESHOLD)
    }


@pytest.mark.parametrize("corpus", CORPORA)
def test_no_retired_threshold_survives_anywhere(corpus):
    # 0.65 was Voyage-scale; 0.30 was the tool description's copy. Both
    # are meaningless against raw cross-encoder logits.
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    for stale in ("0.30", "0.65", "0.60", "between 0 and 1"):
        assert stale not in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_retrieval_sizing_numbers_come_from_constants(corpus):
    prompt = build_system_prompt(corpus=corpus, tier="deep_research")
    assert f"{FIRST_CALL_TOP_K_CAP} passages" in prompt
    for intent, top_k in INTENT_TOP_K.items():
        assert f"top_k {top_k}" in prompt, intent


# ---------------------------------------------------------------------------
# No environment assumptions from the retired architecture
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "banned",
    [
        "Claude Code",
        "Claude",
        "Anthropic",
        "MCP",
        "ToolSearch",
        "session_died",
        ".mcp.json",
        "alwaysLoad",
        "CLAUDE.md",
        "sidecar",
        "Bash",
        "Grep",
        "WebSearch",
    ],
)
def test_no_retired_environment_vocabulary(banned):
    # Naming a tool the model does not have is worse than saying nothing:
    # it teaches the model the tool exists.
    for prompt in every_rendering():
        assert banned not in prompt


@pytest.mark.parametrize("path", ["data/system-prompt-context.md", "docs/superpowers"])
def test_no_repo_file_paths_are_offered_as_a_place_to_look(path):
    # The model-callable surface has no filesystem access (Invariant 7),
    # so a file path is an instruction it cannot follow.
    for prompt in every_rendering():
        assert path not in prompt


@pytest.mark.parametrize("banned", ["hallucination-free", "grounded", "Grounded"])
def test_no_banned_marketing_language(banned):
    # Core Invariant 5.
    for prompt in every_rendering():
        assert banned not in prompt


# ---------------------------------------------------------------------------
# The primer travels inline
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_domain_primer_is_inlined_not_referenced(corpus):
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    # Distinctive phrases from data/system-prompt-context.md. Both
    # corpora get the primer: fiscal years, JLBC-vs-OSPB roles and the
    # reconciliation traps are Arizona knowledge, not budget-book
    # knowledge.
    for phrase in (
        "Urban Revenue Sharing",
        "balance forward",
        "Rainy Day Fund",
        "Joint Legislative Budget Committee",
        "July 1",
    ):
        assert phrase in prompt


def test_expenditure_authority_is_defined_and_not_offered_as_all_funds():
    """A live answer presented an agency's Expenditure Authority total as
    if it were an all-funds budget, then proposed to fix it by summing
    GF + Other Funds + EA — which is ALSO wrong, because it drops Other
    Non-Appropriated and Federal Funds. Verified against the corpus: for
    ADE FY 2025, appropriated + EA is $8,505,643,300 while
    TOTAL - ALL SOURCES is $10,954,802,400, so hand-summing loses $2.4B.
    The prompt must carry the statutory definition AND the published
    total line, or the model reconstructs the same error."""
    # Collapse whitespace: the prompt is hand-wrapped markdown, so a
    # phrase can straddle a line break. Asserting on the raw string would
    # pin the WRAPPING, and a reflow would fail as a content regression.
    prompt = " ".join(build_system_prompt(corpus="budget",
                                          tier="standard").split())
    # The statutory definition, so EA is never read as "all funds".
    assert "continuously appropriated monies" in prompt
    # The published total, so the model quotes it instead of adding rows.
    assert "TOTAL - ALL SOURCES" in prompt
    assert "SUBTOTAL - Appropriated Funds" in prompt
    # The ranking-basis rule — "biggest by budget" is ambiguous and the
    # answer differs enormously by basis at federally-funded agencies.
    assert "Never hand-sum columns to make a total" in prompt


# ---------------------------------------------------------------------------
# Corpus scope
# ---------------------------------------------------------------------------


def test_the_budget_prompt_carries_the_budget_document_machinery():
    prompt = build_system_prompt(corpus="budget", tier="standard")
    for phrase in (
        "Baseline Book",
        "Appropriations Report",
        "Annual Financial Report",
        "agency:axs",  # the canonical-id cheat sheet
        "Actual column",  # the 3-year table structure
    ):
        assert phrase in prompt


def test_the_fiscal_notes_prompt_carries_the_triage_framing():
    prompt = build_system_prompt(corpus="fiscal_notes", tier="standard")
    for phrase in ("fiscal note", "bill", "sponsor"):
        assert phrase in prompt.lower()


def test_budget_document_mechanics_do_not_leak_into_fiscal_notes():
    # A fiscal-note conversation told to pick between `approps-per-agency`
    # and `baseline-per-agency` would filter itself to zero results.
    prompt = build_system_prompt(corpus="fiscal_notes", tier="standard")
    for budget_only in (
        "baseline-per-agency",
        "approps-per-agency",
        "governors-budget",
        "3-year structure",
    ):
        assert budget_only not in prompt


def test_the_fiscal_note_doc_type_is_not_offered_to_budget_conversations():
    assert "fiscal-note" not in build_system_prompt(corpus="budget", tier="standard")


def test_fiscal_notes_are_never_routed_to_budget_documents():
    # THE bug this file exists to catch. The role paragraph tells a
    # fiscal-note conversation it cannot answer from budget books — so
    # nothing later may tell it to ask the analyst WHICH budget book was
    # meant, or offer to pull an appropriations history it does not hold.
    prompt = build_system_prompt(corpus="fiscal_notes", tier="standard")
    for budget_routing in (
        "ask which document",
        "Lifecycle disambiguation rule",
        "lifecycle qualifier",
        "appropriations history",
        "Legislature's planning forecast",
    ):
        assert budget_routing not in prompt


def test_the_budget_prompt_keeps_the_lifecycle_disambiguation():
    # The other half of the same rule: stripping it for fiscal notes must
    # not strip it where it is the single most useful disambiguation the
    # primer teaches.
    prompt = build_system_prompt(corpus="budget", tier="standard")
    assert "ask which document" in prompt
    assert "Lifecycle disambiguation rule" in prompt
    assert "appropriations history" in prompt


def test_the_editorial_refusal_offers_facts_this_corpus_actually_has():
    notes = build_system_prompt(corpus="fiscal_notes", tier="standard")
    # It still refuses the policy question and still offers facts — just
    # facts that exist here.
    assert "policy judgment" in notes
    assert "prior fiscal notes" in notes


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_refusal_wording_is_a_complete_sentence(corpus):
    # Regression: a bracketed instruction was spliced into a sentence
    # stem, so a model following it literally emitted "What I do have
    # JLBC baseline books for FY 2026."
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    assert "The corpus currently covers" in prompt
    assert "What I do have [" not in prompt


def test_the_budget_hygiene_example_is_the_original_one():
    # This ✓ example is corpus-specific and its neighbors are already
    # corpus-gated; replacing it with a vaguer shared one lost the
    # "name publishers and fiscal years" demonstration.
    prompt = build_system_prompt(corpus="budget", tier="standard")
    assert "The corpus currently covers JLBC documents for FY 2025-FY 2027" in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_no_results_sentinel_is_explained(corpus):
    # `NO_RESULTS_TOP_SCORE` is -1e9 and reaches the model verbatim. A
    # model that has never been told that reads it as a catastrophe.
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    assert "very large negative" in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_filter_values_example_matches_what_the_tool_returns(corpus):
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    # The agency dimension carries a real name when the catalog is
    # available; the prose says so, so the example must show it.
    assert '"name"' in prompt
    # And the catalog is read live on every call — a concurrent ingest
    # can change it mid-conversation.
    assert "rarely changes" in prompt
    assert "doesn't change mid-conversation" not in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_citation_discipline_is_corpus_independent(corpus):
    # Trimming budget-only guidance must never trim the contract that
    # makes an answer auditable (Core Invariants 1-3).
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    for phrase in (
        "cite_batch",
        "claim_span",
        "MUST call `retrieve()`",
        "Refusal",
    ):
        assert phrase in prompt


# ---------------------------------------------------------------------------
# Tier awareness
# ---------------------------------------------------------------------------


def test_the_two_tiers_render_different_postures():
    standard = build_system_prompt(corpus="budget", tier="standard")
    deep = build_system_prompt(corpus="budget", tier="deep_research")
    assert standard != deep
    assert "Standard" in standard and "Deep Research" in deep


def test_each_tier_states_its_own_step_budget():
    for tier, budget in TIER_BUDGETS.items():
        prompt = build_system_prompt(corpus="budget", tier=tier)
        assert f"{budget['max_steps']} tool" in prompt


def test_standard_warns_that_deep_dive_is_ignored():
    # The executor silently drops `deep_dive` on Standard and says so in
    # the tool result. Without this, the model reads that note as a
    # failure and re-asks.
    standard = build_system_prompt(corpus="budget", tier="standard")
    assert "deep_dive" in standard
    assert "ignored" in standard


def test_deep_research_permits_deep_dive():
    deep = build_system_prompt(corpus="budget", tier="deep_research")
    assert "deep_dive" in deep


# ---------------------------------------------------------------------------
# The prompt and the tool schemas describe the same tools
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", CORPORA)
def test_every_real_tool_is_documented_and_no_invented_one_is(corpus):
    from harness.tools import TOOL_NAMES

    prompt = build_system_prompt(corpus=corpus, tier="standard")
    for name in TOOL_NAMES:
        assert f"`{name}(" in prompt or f"`{name}`" in prompt, name
    # Tools that existed in the retired prompt and no longer do.
    for gone in ("Read(", "Glob(", "WebFetch("):
        assert gone not in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_create_document_guidance_is_present_and_bounded(corpus):
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    assert "create_document" in prompt
    # It must say what the renderer can actually do, or the model writes
    # blockquotes and footnotes that arrive as flat paragraphs.
    assert "pipe table" in prompt


# ---------------------------------------------------------------------------
# Packaging
# ---------------------------------------------------------------------------


def test_a_missing_template_fails_with_an_actionable_message(tmp_path, monkeypatch):
    import harness.prompt as prompt_module

    monkeypatch.setattr(prompt_module, "TEMPLATE_PATH", tmp_path / "gone.md")
    reset_template_cache()
    with pytest.raises(PromptTemplateError) as err:
        build_system_prompt(corpus="budget", tier="standard")
    message = str(err.value)
    assert "gone.md" in message
    assert "reinstall" in message.lower()


def _stub_template(tmp_path, monkeypatch, text: str):
    import harness.prompt as prompt_module

    path = tmp_path / "system-prompt.md"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setattr(prompt_module, "TEMPLATE_PATH", path)
    reset_template_cache()
    return path


def test_a_mistyped_block_keyword_points_at_the_line_that_is_wrong(
    tmp_path, monkeypatch
):
    # Without this, the strict marker regex simply doesn't match, the
    # line survives as literal text, and the error lands on the CLOSING
    # line — sending the author to inspect the one line that is correct.
    _stub_template(tmp_path, monkeypatch, "# T\n{{#when corpuz=budget}}\nx\n{{/when}}\n")
    with pytest.raises(PromptTemplateError) as err:
        build_system_prompt(corpus="budget", tier="standard")
    assert ":2:" in str(err.value)
    assert "corpuz" in str(err.value)


def test_an_unknown_block_value_is_rejected_rather_than_dropped(tmp_path, monkeypatch):
    # `{{#when corpus=budgets}}` matches the marker syntax fine and would
    # silently delete its block from every rendering.
    _stub_template(tmp_path, monkeypatch, "# T\n{{#when corpus=budgets}}\nx\n{{/when}}\n")
    with pytest.raises(PromptTemplateError, match="budgets"):
        build_system_prompt(corpus="budget", tier="standard")


def test_a_fenced_block_marker_is_documentation_not_a_directive(
    tmp_path, monkeypatch
):
    # Someone documenting the block syntax inside a fenced example must
    # not have their example silently EXECUTED — one rendering would
    # swallow the sample block and the other would swallow the marker
    # lines, with no `{{` left behind for any other test to catch.
    fenced = "# T\n```\n{{#when corpus=budget}}\nexample\n{{/when}}\n```\n"
    _stub_template(tmp_path, monkeypatch, fenced)
    for corpus in CORPORA:
        rendered = build_system_prompt(corpus=corpus, tier="standard")
        assert "{{#when corpus=budget}}" in rendered
        assert "{{/when}}" in rendered
        assert "example" in rendered


def test_a_real_block_still_works_after_a_fenced_example(tmp_path, monkeypatch):
    # The fence tracking must close again — a template that documents the
    # syntax and then USES it has to keep working.
    _stub_template(
        tmp_path,
        monkeypatch,
        "# T\n```\n{{#when corpus=budget}}\n```\n"
        "{{#when corpus=budget}}\nreal\n{{/when}}\n",
    )
    assert "real" in build_system_prompt(corpus="budget", tier="standard")
    assert "real" not in build_system_prompt(corpus="fiscal_notes", tier="standard")


def test_an_unbalanced_code_fence_is_rejected(tmp_path, monkeypatch):
    # Every marker after an unclosed fence would be treated as prose.
    _stub_template(tmp_path, monkeypatch, "# T\n```\nopened and never closed\n")
    with pytest.raises(PromptTemplateError, match="fence"):
        build_system_prompt(corpus="budget", tier="standard")


def test_a_malformed_close_marker_points_at_its_own_line(tmp_path, monkeypatch):
    # Mirror of the open-marker guard: without it, `{{ /when}}` is prose
    # and the error blames the OPENING line, which is correct.
    _stub_template(
        tmp_path, monkeypatch, "# T\n{{#when corpus=budget}}\nx\n{{ /when}}\n"
    )
    with pytest.raises(PromptTemplateError) as err:
        build_system_prompt(corpus="budget", tier="standard")
    assert ":4:" in str(err.value)


def test_an_unclosed_block_is_rejected(tmp_path, monkeypatch):
    _stub_template(tmp_path, monkeypatch, "# T\n{{#when tier=standard}}\nx\n")
    with pytest.raises(PromptTemplateError, match="unclosed"):
        build_system_prompt(corpus="budget", tier="standard")


def test_the_template_is_read_from_disk_once(monkeypatch):
    import harness.prompt as prompt_module

    reads = {"n": 0}
    real = prompt_module._read_template

    def counted(path):
        reads["n"] += 1
        return real(path)

    monkeypatch.setattr(prompt_module, "_read_template", counted)
    reset_template_cache()
    for _ in range(4):
        build_system_prompt(corpus="budget", tier="standard")
        build_system_prompt(corpus="fiscal_notes", tier="deep_research")
    # ~900 lines re-read on every turn of every conversation otherwise.
    assert reads["n"] == 1


def test_concurrent_builds_read_the_template_once(monkeypatch):
    # Turns run in a threadpool, so several conversations can hit a cold
    # cache at the same moment. The lock has to cover read AND store; a
    # refactor that moves the read outside it would read N times and,
    # worse, could publish a half-built cache entry.
    import time
    from concurrent.futures import ThreadPoolExecutor

    import harness.prompt as prompt_module

    counter = {"n": 0}
    counter_lock = threading.Lock()
    real = prompt_module._read_template

    def slow_counted(path):
        with counter_lock:
            counter["n"] += 1
        time.sleep(0.05)  # widen the window a racy implementation needs
        return real(path)

    monkeypatch.setattr(prompt_module, "_read_template", slow_counted)
    reset_template_cache()

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(
                lambda _: build_system_prompt(corpus="budget", tier="standard"),
                range(8),
            )
        )

    assert counter["n"] == 1
    assert len(set(results)) == 1


# ---------------------------------------------------------------------------
# Recency and fiscal years (S21)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_recency_section_is_present_on_both_corpora(corpus):
    # S21 layer 1 (query years become a filter) applies to BOTH corpora,
    # so the guidance cannot be inside a budget-only block.
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    assert "**Recency and fiscal years:**" in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_model_is_told_about_the_inferred_year_echo(corpus):
    # harness/tools.py puts this key on the response only when the parse
    # fired; a model that has never been told the key exists reads a
    # silently narrowed result set as the whole corpus.
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    assert "inferred_fiscal_years" in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_adjacent_year_widening_is_explained(corpus):
    # Otherwise a FY 2019 query returning an FY 2020 document reads as a
    # filter bug, and the model may discard a correct passage.
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    flat = " ".join(prompt.split())
    assert "years immediately either side of it" in flat
    assert "enacted in the next year's budget bill" in flat


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_prompt_does_not_promise_recency_ordering(corpus):
    """RECENCY_BOOST_PER_YEAR ships at 0.0: recency has ZERO influence on
    ordering today. Describing a tiebreaker that is switched off would
    lead the model to quote the top passage as "current" without reading
    its fiscal_year. When plan Task 6 turns the weight on, this sentence
    is part of that change — see the plan's Task 6 checklist."""
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    flat = " ".join(prompt.split())
    assert "nothing sorts them by recency" in flat
    for overclaim in (
        "sorted by recency",
        "newest first",
        "most recent first",
        "always returns the latest",
    ):
        assert overclaim not in prompt


@pytest.mark.parametrize("corpus", CORPORA)
def test_the_model_is_warned_that_bill_numbers_can_look_like_years(corpus):
    """Arizona House bills are numbered from 2001 up. The parser rejects
    the designated forms ("HB 2019"), but a bare four-digit number in
    query text is read as a year, and the model is the only one who knows
    what it meant."""
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    flat = " ".join(prompt.split())
    assert "mistaken for a year" in flat
    assert "`inferred_fiscal_years` you did not intend" in flat


@pytest.mark.parametrize("corpus", CORPORA)
def test_multi_year_questions_are_steered_to_one_search_per_year(corpus):
    prompt = build_system_prompt(corpus=corpus, tier="standard")
    assert "one search per year" in " ".join(prompt.split())


# ---------------------------------------------------------------------------
# The corpus map (spec N1/N2)
# ---------------------------------------------------------------------------


def test_corpus_map_renders_when_supplied():
    out = build_system_prompt(
        corpus="budget", tier="standard", corpus_map="| MAPMARKER | FY2005–FY2026 | 9 |"
    )
    assert "MAPMARKER" in out
    assert "{{CORPUS_MAP}}" not in out


def test_corpus_map_falls_back_when_absent():
    from harness.prompt import CORPUS_MAP_FALLBACK

    out = build_system_prompt(corpus="budget", tier="standard")
    assert CORPUS_MAP_FALLBACK in out
    assert "{{CORPUS_MAP}}" not in out


def test_an_empty_map_string_also_falls_back():
    """`build_corpus_map` returns None, but a caller that stringifies a
    degraded read would hand over "" — and an empty section under the
    "what this corpus contains" heading reads as "it contains nothing"."""
    from harness.prompt import CORPUS_MAP_FALLBACK

    out = build_system_prompt(corpus="budget", tier="standard", corpus_map="")
    assert CORPUS_MAP_FALLBACK in out


@pytest.mark.parametrize("corpus", CORPORA)
def test_both_corpora_carry_the_map_section(corpus):
    out = build_system_prompt(corpus=corpus, tier="standard", corpus_map="NOTEMAP")
    assert "NOTEMAP" in out


def test_prompt_py_does_not_import_the_map_builder_or_the_store():
    """Spec N2: the CALLER builds the map. `harness/prompt.py` must stay
    cheap to import — pulling `store` in would drag LanceDB and the ONNX
    models into any process that only wanted a string."""
    import ast
    from pathlib import Path

    source = Path(__file__).resolve().parent.parent / "harness" / "prompt.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    imported: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    for module in imported:
        root = module.split(".")[0]
        assert root not in {"store", "retrieval", "ingest", "lancedb"}, module
        assert module != "harness.corpus_map"
