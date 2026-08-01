"""Compare-tool tests. The guardrails ARE the feature: refusing
cross-corpus comparisons and labeling single-run noise (spec §5)."""
from __future__ import annotations

import json

import pytest

from eval.compare_agent_runs import compare, corpus_counts_differ, load_run


def write_run(tmp_path, name, *, counts=None, repeats=1, kf=0.8, cites=1.0,
              judge_precision=None):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({
        "timestamp": name, "git_sha": name[:7], "subset": "smoke",
        "repeats": repeats, "queries": ["aq-001"],
        "tier_models": {"standard": "test/model"},
        "provider": "openrouter", "base_url": "x", "api_key_set": True,
        "prompt_sha256": "abc", "corpus_counts": counts or {"budget_chunks": 100},
        "note": ""}), encoding="utf-8")
    (d / "scores.json").write_text(json.dumps({
        "summary": {"n": 1, "errors": 0, "key_fact_rate_mean": kf,
                    "first_attempt_cite_rate": cites, "steps_mean": 4.0,
                    "total_cost_usd": 0.01},
        "per_query": [{"query_id": "aq-001", "ok": True, "key_fact_rate": kf}],
        "skipped": []}), encoding="utf-8")
    if judge_precision is not None:
        (d / "judge.json").write_text(json.dumps({
            "judge_model": "j", "judge_prompt_sha256": "s",
            "summary": {"claim_coverage_precision_mean": judge_precision},
            "per_query": []}), encoding="utf-8")
    return d


def test_load_run(tmp_path):
    run = load_run(write_run(tmp_path, "runA", judge_precision=0.9))
    assert run["manifest"]["subset"] == "smoke"
    assert run["scores"]["summary"]["n"] == 1
    assert run["judge"]["summary"]["claim_coverage_precision_mean"] == 0.9


def test_corpus_guard(tmp_path):
    a = load_run(write_run(tmp_path, "runA", counts={"budget_chunks": 100}))
    b = load_run(write_run(tmp_path, "runB", counts={"budget_chunks": 999}))
    assert corpus_counts_differ(a, b) is True
    c = load_run(write_run(tmp_path, "runC", counts={"budget_chunks": 100}))
    assert corpus_counts_differ(a, c) is False


def test_compare_markdown_contains_deltas_and_noise_warning(tmp_path):
    a = load_run(write_run(tmp_path, "runA", kf=0.8, cites=0.5))
    b = load_run(write_run(tmp_path, "runB", kf=0.9, cites=0.75))
    md = compare(a, b)
    assert "key_fact_rate_mean" in md
    assert "+0.1" in md or "0.10" in md  # the delta is shown
    assert "single run" in md.lower()    # repeats==1 noise warning


def test_compare_includes_judge_when_both_have_it(tmp_path):
    a = load_run(write_run(tmp_path, "runA", judge_precision=0.6))
    b = load_run(write_run(tmp_path, "runB", judge_precision=0.8))
    md = compare(a, b)
    assert "claim_coverage_precision_mean" in md


def test_compare_skips_judge_when_one_side_missing(tmp_path):
    a = load_run(write_run(tmp_path, "runA"))
    b = load_run(write_run(tmp_path, "runB", judge_precision=0.8))
    md = compare(a, b)
    assert "judge" in md.lower() and "only one run" in md.lower()
