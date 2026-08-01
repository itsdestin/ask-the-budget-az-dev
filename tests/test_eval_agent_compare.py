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


def test_compare_report_has_a_legend_for_the_arrows():
    # Finding 1: "+0.01 ▼" reads as self-contradictory unless the report
    # states, near the tables, that the glyphs mean better/worse rather
    # than up/down. Pin that the explanation is actually present.
    md = compare(_run({"total_cost_usd": 0.01}), _run({"total_cost_usd": 0.02}))
    assert "improvement" in md.lower()
    assert "regression" in md.lower()


# --- Finding 2: nothing pinned the ▲/▼ direction itself. A future edit that
# inverted the better/worse boolean would pass every test above (they only
# check the delta value and the noise-warning text) while emitting a
# backwards arrow on every regression report. These five tests construct
# `compare()`'s dict input directly (its documented shape, not a file on
# disk) so each one isolates a single metric in a single quadrant. ---

def _run(summary: dict) -> dict:
    """Minimal baseline/candidate dict in the shape `compare()` consumes.
    repeats=3 keeps the single-run noise banner out of the report so it
    can't be mistaken for part of an arrow assertion."""
    return {"name": "r", "manifest": {"repeats": 3},
            "scores": {"summary": summary, "per_query": []}, "judge": None}


def _row_for(md: str, key: str) -> str:
    """The one metrics-table row for `key` — isolating the row (not just
    scanning the whole report) is what makes each assertion pin ONE
    quadrant instead of being satisfiable by an arrow anywhere in the doc."""
    for line in md.splitlines():
        if line.startswith(f"| {key} |"):
            return line
    raise AssertionError(f"no row for {key!r} in report:\n{md}")


def test_arrow_higher_is_better_metric_that_rose_is_improvement():
    md = compare(_run({"key_fact_rate_mean": 0.5}), _run({"key_fact_rate_mean": 0.8}))
    row = _row_for(md, "key_fact_rate_mean")
    assert "▲" in row
    assert "▼" not in row


def test_arrow_higher_is_better_metric_that_fell_is_regression():
    md = compare(_run({"first_attempt_cite_rate": 0.9}), _run({"first_attempt_cite_rate": 0.5}))
    row = _row_for(md, "first_attempt_cite_rate")
    assert "▼" in row
    assert "▲" not in row


def test_arrow_lower_is_better_metric_that_fell_is_improvement():
    # total_cost_usd DROPPING is the improvement case even though the
    # delta is negative — this is the exact quadrant Finding 1 was about.
    md = compare(_run({"total_cost_usd": 0.05}), _run({"total_cost_usd": 0.01}))
    row = _row_for(md, "total_cost_usd")
    assert "▲" in row
    assert "▼" not in row


def test_arrow_lower_is_better_metric_that_rose_is_regression():
    md = compare(_run({"steps_mean": 4.0}), _run({"steps_mean": 6.0}))
    row = _row_for(md, "steps_mean")
    assert "▼" in row
    assert "▲" not in row


def test_arrow_unclassified_metric_renders_with_no_arrow():
    # "n" is in neither direction set — the omission must stay deliberate
    # (an informational metric with no better/worse sense) rather than an
    # accident that a later refactor papers over with a default arrow.
    md = compare(_run({"n": 10}), _run({"n": 12}))
    row = _row_for(md, "n")
    assert "▲" not in row
    assert "▼" not in row
