"""Structural invariants for the committed query set.

Why: the query set is the eval's measuring stick. These tests make the
authoring contract (shape quotas, subset sizes, refusal hygiene)
machine-checked so a future edit can't quietly unbalance it.
"""
from __future__ import annotations

from collections import Counter

from eval.agent_schema import load_agent_queries

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


def test_corpus_coverage():
    assert sum(1 for q in QUERIES if q.corpus == "fiscal_notes") >= 4


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
