"""Structural invariants for the committed query set.

Why: the query set is the eval's measuring stick. These tests make the
authoring contract (shape quotas, subset sizes, refusal hygiene)
machine-checked so a future edit can't quietly unbalance it.
"""
from __future__ import annotations

import re
from collections import Counter

from eval.agent_schema import QUERY_SETS, load_agent_queries
from eval.agent_scoring import currency_values, fact_matches

QUERIES = load_agent_queries("eval/agent_queries.yaml")


def test_size_and_unique_ids():
    assert len(QUERIES) >= 28
    assert len({q.id for q in QUERIES}) == len(QUERIES)


def test_shape_quotas():
    shapes = Counter(q.shape for q in QUERIES)
    assert shapes["lookup"] >= 8
    assert shapes["comparison"] >= 5
    assert shapes["analyze"] >= 4
    assert shapes["memo"] >= 1
    assert shapes["refusal"] >= 4
    assert shapes["historical"] >= 3


def test_every_query_is_budget_corpus():
    # WHY: scope correction from the project owner, 2026-08-01 -- "the plans
    # assumption about historical budget books was not wrong. the final app
    # will use only historical budget books. this eval set should NOT utilize
    # the fiscal note path, we are solely evaluating budget queries." This
    # assertion replaced a fiscal-notes >= 4 quota. A metric averaged across
    # two corpora answers no question about either, so a single fiscal-note
    # query re-admitted here would silently contaminate every aggregate the
    # scorer reports. If a fiscal-note agent eval is ever wanted it belongs
    # in its own file with its own results prefix, exactly as Layer 1 does.
    offenders = [q.id for q in QUERIES if q.corpus != "budget"]
    assert not offenders, f"non-budget queries in a budget-only set: {offenders}"


def test_every_query_has_an_explicit_set():
    from eval.agent_schema import AgentQuery as _AQ
    for q in QUERIES:
        assert q.set in QUERY_SETS, f"{q.id}: unknown set {q.set}"
    # the retired mechanism must not survive in the schema at all
    assert "subsets" not in _AQ.model_fields


def test_set_sizes():
    counts = Counter(q.set for q in QUERIES)
    assert counts["quick"] >= 20          # target ~25; floor not target (flex)
    assert counts["deep"] == 3
    assert counts["refusal"] == 5
    # multi has a floor of 0 until Task 10 authors them; assert presence only
    assert counts["multi"] >= 0


def test_deep_queries_carry_at_least_one_key_fact():
    # The vacuous-pass hole: with 0 facts the headline's "passes key facts"
    # bar is trivially true and a Deep query counts as accurate on a citation
    # alone. agent_scoring returns key_fact_rate=None at total_facts==0.
    for q in QUERIES:
        if q.set == "deep":
            assert q.key_facts, f"{q.id}: deep queries must carry >=1 key fact"


def test_multi_queries_pin_correct_response_docs():
    for q in QUERIES:
        if q.set == "multi":
            assert q.correct_response_docs, f"{q.id}: multi set requires correct_response_docs"
            assert all(d.strip() for d in q.correct_response_docs)


def test_standard_tier_is_not_polluted_by_deep():
    # Port of the old Finding-1 guard, restated for sets, made TWO-DIRECTIONAL:
    # a deep-research-tier query must appear in `set: deep` AND ONLY there.
    # The one-directional version let cm-university-funding-dr sit in `quick`
    # on tier: deep_research (Task 9 review, Critical) — cheap --sets quick
    # runs would have spent ~44x Standard cost routing it to the Deep model.
    # Selection is by `set`, but the session factory routes by `tier`, so the
    # ONLY safe state is a tier/value bijection for deep_research.
    dr_tiered = [q.id for q in QUERIES if q.tier == "deep_research"]
    assert dr_tiered, "expected at least one deep_research-tier query"
    for qid in dr_tiered:
        q = next(q for q in QUERIES if q.id == qid)
        assert q.set == "deep", (
            f"{qid}: deep_research tier outside `set: deep` ({q.set}) — it "
            f"would run on the Deep model in cheap runs and refuse to start "
            f"on a Standard-only install (Finding-1 class).")


def test_refusal_queries_have_no_key_facts():
    for q in QUERIES:
        if q.shape == "refusal":
            assert q.should_refuse and not q.key_facts
        else:
            assert not q.should_refuse


def test_answer_queries_have_key_facts_and_notes():
    for q in QUERIES:
        if q.shape not in ("refusal", "memo"):
            assert q.key_facts, f"{q.id} has no key facts"
        assert q.judge_notes, f"{q.id} has no judge notes"


# --- the crash class the file header warns about, made machine-checkable ---
#
# WHY these three exist (2026-08-01 review, Finding 2): the YAML header spends
# a paragraph on the trap that JLBC writes every reduction as `$(2.5) million`,
# which `currency_values` parses to an EMPTY set, and that an unparseable
# currency fact makes `fact_matches` RAISE ValueError rather than return False.
# Nothing machine-checked it. A reviewer appended a query carrying
# `kind: currency, value: "$(2.5) million"` and every one of the seven
# assertions above passed while `fact_matches` raised at run time.
#
# The failure that buys is the worst-shaped one this file can produce: the
# scorer crashes PART WAY THROUGH a run, after the OpenRouter calls have been
# paid for and the transcripts written, and the only diagnosis on offer is a
# ValueError from deep inside scoring. These assertions move that discovery to
# the pre-merge test run, where it costs nothing.
#
# Verified to actually catch it before being relied on: with a probe query
# carrying `value: "$(2.5) million"` and `value: "unclosed ( group"` appended
# to the YAML, test_every_currency_fact_parses and
# test_every_regex_fact_compiles both FAIL and the other seven still pass.


def test_every_currency_fact_parses():
    """No kind=currency fact may parse to an empty set."""
    for q in QUERIES:
        for f in q.key_facts:
            if f.kind != "currency":
                continue
            assert currency_values(f.value), (
                f"{q.id}: currency fact {f.value!r} parses to NO amounts, so "
                f"fact_matches() raises ValueError at scoring time. "
                f"eval.agent_scoring needs a '$' or a scale word adjacent to "
                f"the digits — parenthesized negatives and bare counts do not "
                f"qualify. Use kind=regex for those."
            )


def test_every_regex_fact_compiles():
    """No kind=regex fact may be an uncompilable pattern."""
    for q in QUERIES:
        for f in q.key_facts:
            if f.kind != "regex":
                continue
            try:
                re.compile(f.value)
            except re.error as exc:  # pragma: no cover - assertion carries it
                raise AssertionError(
                    f"{q.id}: regex fact {f.value!r} does not compile ({exc}); "
                    f"fact_matches() would raise at scoring time."
                ) from exc


def test_no_fact_raises_when_scored_against_arbitrary_text():
    """End-to-end guard on the two above: scoring must never raise.

    The two assertions above check the known causes; this one checks the
    PROPERTY they exist to protect, so a future third cause (a new fact
    kind, a regex that compiles but explodes on a real input) is caught by
    the same run rather than by a crashed eval.
    """
    samples = [
        "",
        "   ",
        "no numbers here at all",
        "The FY 2026 total was $1,600,697,200 (2.5) million and 100% of ADM.",
        "$",
        "Empowerment Scholarships 822,030,600 $(102,214,900) 1,677 pupils",
    ]
    for q in QUERIES:
        for f in q.key_facts:
            for text in samples:
                fact_matches(f, text)  # must not raise
