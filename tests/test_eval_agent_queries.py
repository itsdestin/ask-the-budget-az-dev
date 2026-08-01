"""Structural invariants for the committed query set.

Why: the query set is the eval's measuring stick. These tests make the
authoring contract (shape quotas, subset sizes, refusal hygiene)
machine-checked so a future edit can't quietly unbalance it.
"""
from __future__ import annotations

import re
from collections import Counter

from eval.agent_schema import load_agent_queries
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


def test_smoke_subset_is_small_and_diverse():
    smoke = [q for q in QUERIES if "smoke" in q.subsets]
    assert 8 <= len(smoke) <= 12
    assert len({q.shape for q in smoke}) >= 4
    assert all(q.tier == "standard" for q in smoke)


def test_dr_probe_subset():
    probe = [q for q in QUERIES if "dr-probe" in q.subsets]
    assert len(probe) == 4
    assert all(q.tier == "deep_research" for q in probe)


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
