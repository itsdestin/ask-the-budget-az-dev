"""Compare-tool tests. The guardrails ARE the feature: refusing
cross-corpus comparisons and labeling single-run noise (spec §5)."""
from __future__ import annotations

import json
import sys

import pytest

from eval.compare_agent_runs import (
    compare,
    corpus_counts_differ,
    load_run,
    query_sets_differ,
)


def write_run(tmp_path, name, *, counts=None, repeats=1, kf=0.8, cites=1.0,
              judge_precision=None, queries_sha="qs-1"):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({
        "timestamp": name, "git_sha": name[:7], "subset": "smoke",
        "repeats": repeats, "queries": ["aq-001"], "queries_sha256": queries_sha,
        "tier_models": {"standard": "test/model"},
        "provider": "openrouter", "base_url": "x", "api_key_set": True,
        "prompt_sha256": "abc", "corpus_counts": counts or {"budget_chunks": 100},
        "note": ""}), encoding="utf-8")
    (d / "scores.json").write_text(json.dumps({
        "summary": {"n": 1, "errors": 0, "key_fact_rate_mean": kf,
                    "cite_pass_rate": cites, "steps_mean": 4.0,
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
    md = compare(_run({"cite_pass_rate": 0.9}), _run({"cite_pass_rate": 0.5}))
    row = _row_for(md, "cite_pass_rate")
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


def test_arrow_lower_is_better_retries_per_citation():
    # Finding 5's new metric has to carry a direction, or it renders bare.
    md = compare(_run({"retries_per_citation": 0.4}), _run({"retries_per_citation": 0.1}))
    row = _row_for(md, "retries_per_citation")
    assert "▲" in row and "▼" not in row


def test_arrow_unclassified_metric_renders_with_no_arrow():
    # "n" is in neither direction set — the omission must stay deliberate
    # (an informational metric with no better/worse sense) rather than an
    # accident that a later refactor papers over with a default arrow.
    md = compare(_run({"n": 10}), _run({"n": 12}))
    row = _row_for(md, "n")
    assert "▲" not in row
    assert "▼" not in row


# --- Finding 2: query-set guard -----------------------------------------
#
# Verified before the fix: a 1-query smoke run compared against a fabricated
# 3-query "full" run produced a clean report showing key_fact_rate_mean
# 0 → 0.9 ▲ with no warning anywhere. The worse case is two `full` runs where
# a query's key_facts were EDITED in between — the manifests were then
# byte-identical and the entire delta was authoring drift.

def test_query_sets_differ_detects_an_edited_query_set(tmp_path):
    a = load_run(write_run(tmp_path, "runA", queries_sha="aaa"))
    b = load_run(write_run(tmp_path, "runB", queries_sha="bbb"))
    assert query_sets_differ(a, b) is True
    c = load_run(write_run(tmp_path, "runC", queries_sha="aaa"))
    assert query_sets_differ(a, c) is False


def test_a_manifest_with_no_hash_trips_the_guard_against_one_that_has_it(tmp_path):
    """A run recorded before hashing existed carries no queries_sha256. That
    is 'unknown', not 'the same' — the operator decides with --force."""
    old = load_run(write_run(tmp_path, "runOld"))
    old["manifest"].pop("queries_sha256")
    new = load_run(write_run(tmp_path, "runNew", queries_sha="aaa"))
    assert query_sets_differ(old, new) is True
    # Two equally-old runs agree (both unknown) and must not trip it.
    other_old = load_run(write_run(tmp_path, "runOld2"))
    other_old["manifest"].pop("queries_sha256")
    assert query_sets_differ(old, other_old) is False


def test_cli_refuses_a_mismatched_query_set_and_force_overrides(tmp_path, capsys):
    from eval.compare_agent_runs import main

    a = write_run(tmp_path, "runA", queries_sha="aaa")
    b = write_run(tmp_path, "runB", queries_sha="bbb")
    argv = sys.argv
    try:
        sys.argv = ["compare_agent_runs.py", str(a), str(b)]
        assert main() == 2
        err = capsys.readouterr().err
        assert "REFUSING" in err and "query set" in err.lower()

        sys.argv = ["compare_agent_runs.py", str(a), str(b), "--force"]
        assert main() == 0
    finally:
        sys.argv = argv
    # A forced report must carry the reason it needed forcing.
    report = next(tmp_path.glob("compare-*.md")).read_text(encoding="utf-8")
    assert "DIFFERENT query sets" in report
    assert "authoring drift" in report


def test_report_shows_the_query_hash_in_what_differed(tmp_path):
    a = load_run(write_run(tmp_path, "runA", queries_sha="aaa"))
    b = load_run(write_run(tmp_path, "runB", queries_sha="aaa"))
    assert "queries_sha256" in compare(a, b)


# --- Finding 4: population-dependent means get no arrow ------------------

def test_no_arrow_when_the_retrieves_after_sufficient_population_moved():
    """A retrieval improvement can raise this mean (more queries reach
    sufficiency, including slow ones), so a ▼ would report an improvement as
    a regression. When the denominator moved, withhold the verdict."""
    md = compare(
        _run({"retrieves_after_sufficient_mean": 0.5, "retrieves_after_sufficient_n": 5}),
        _run({"retrieves_after_sufficient_mean": 1.2, "retrieves_after_sufficient_n": 20}))
    row = _row_for(md, "retrieves_after_sufficient_mean")
    assert "▲" not in row and "▼" not in row
    assert "different denominators" in md


def test_arrow_kept_when_the_population_is_unchanged():
    md = compare(
        _run({"retrieves_after_sufficient_mean": 1.2, "retrieves_after_sufficient_n": 20}),
        _run({"retrieves_after_sufficient_mean": 0.5, "retrieves_after_sufficient_n": 20}))
    row = _row_for(md, "retrieves_after_sufficient_mean")
    assert "▲" in row  # fewer wasted searches over the same population
    assert "different denominators" not in md


# --- Finding 1 (fix-batch review): total_cost_usd is population-dependent
# on cost_missing_queries, the same shape as Finding 4's population-dependent
# means above --------------------------------------------------------------

def test_no_arrow_when_cost_missing_queries_population_moved():
    """The reviewer's exact repro: a run that crashes 10 queries sums $0 for
    each of them despite real spend, so total_cost_usd can DROP purely
    because more queries broke. A ▲ here would render a regression as a cost
    improvement. When cost_missing_queries moved, withhold the verdict."""
    md = compare(
        _run({"total_cost_usd": 1.2, "cost_missing_queries": 0}),
        _run({"total_cost_usd": 0.81, "cost_missing_queries": 10}))
    row = _row_for(md, "total_cost_usd")
    assert "▲" not in row and "▼" not in row
    # "cost_missing_queries" alone is too weak a check -- it is also the name
    # of its own row in the metrics table, present in every report regardless
    # of whether the population moved. The footnote's distinguishing phrase is
    # what proves the withholding fired.
    assert "crashed silently" in md


def test_arrow_kept_when_cost_missing_queries_unchanged():
    md = compare(
        _run({"total_cost_usd": 1.2, "cost_missing_queries": 2}),
        _run({"total_cost_usd": 0.81, "cost_missing_queries": 2}))
    row = _row_for(md, "total_cost_usd")
    assert "▲" in row  # genuine cost reduction, same population
    assert "crashed silently" not in md


def _add_judge(run_dir, model, precision=0.5):
    (run_dir / "judge.json").write_text(json.dumps({
        "judge_model": model, "judge_prompt_sha256": "s",
        "summary": {"claim_coverage_precision_mean": precision},
        "per_query": []}), encoding="utf-8")


def test_judge_metrics_are_withheld_when_the_judge_model_differs(tmp_path):
    """Judge results are not comparable across judge models. Measured
    2026-08-02 on one identical set of 31 answers: claude-sonnet-5 and
    deepseek-v4-flash-0731 found 135 vs 113 load-bearing claims, which
    moves claim_coverage_precision for reasons that have nothing to do
    with the agent under test. The corpus and query-set guards exist to
    stop exactly this class of false conclusion; the judge needs one too.
    """
    a = write_run(tmp_path, "runA")
    b = write_run(tmp_path, "runB")
    _add_judge(a, "anthropic/claude-sonnet-5", 0.53)
    _add_judge(b, "z-ai/glm-5.2", 0.58)
    md = compare(load_run(a), load_run(b))
    assert "different judge" in md.lower()
    # The misleading delta must NOT be presented as an improvement.
    assert "claim_coverage_precision_mean | 0.53 | 0.58" not in md


def test_judge_metrics_compare_normally_when_the_judge_matches(tmp_path):
    a = write_run(tmp_path, "runA")
    b = write_run(tmp_path, "runB")
    _add_judge(a, "z-ai/glm-5.2", 0.50)
    _add_judge(b, "z-ai/glm-5.2", 0.60)
    md = compare(load_run(a), load_run(b))
    assert "claim_coverage_precision_mean" in md
    assert "different judge" not in md.lower()
