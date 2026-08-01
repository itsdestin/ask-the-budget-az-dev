"""Diff two agent-eval run directories into a markdown report.

Guardrails (spec §5): refuse to compare runs against different corpus
counts (the numbers would measure the corpus, not the change), and label
single-run comparisons as stochastic noise rather than celebrating them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Metrics where UP is better; everything else in the table is
# informational. Direction matters for the ▲/▼ glyphs only.
_HIGHER_IS_BETTER = {
    "key_fact_rate_mean", "first_attempt_cite_rate", "retrieval_efficiency_mean",
    "refusal_correct_rate", "cached_tokens_mean",
}
_LOWER_IS_BETTER = {
    "steps_mean", "retrieve_calls_mean", "input_tokens_mean", "output_tokens_mean",
    "total_cost_usd", "cost_mean_usd", "wall_p50_ms", "wall_p95_ms",
    "retrieves_after_sufficient_mean", "errors", "false_refusals",
    "narration_hit_queries", "token_leaks", "internal_vocab_queries",
}
_JUDGE_METRICS = ("claim_coverage_precision_mean", "claim_coverage_recall_mean",
                  "holistic_mean")


def load_run(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    judge = None
    judge_path = run_dir / "judge.json"
    if judge_path.exists():
        judge = json.loads(judge_path.read_text(encoding="utf-8"))
    return {"name": run_dir.name, "manifest": manifest, "scores": scores, "judge": judge}


def corpus_counts_differ(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["manifest"].get("corpus_counts") != b["manifest"].get("corpus_counts")


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _delta_row(key: str, av: Any, bv: Any) -> str:
    arrow = ""
    if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
        diff = bv - av
        if diff:
            better = ((diff > 0 and key in _HIGHER_IS_BETTER)
                      or (diff < 0 and key in _LOWER_IS_BETTER))
            arrow = f" {'▲' if better else '▼'}" if (key in _HIGHER_IS_BETTER or key in _LOWER_IS_BETTER) else ""
        delta = f"{diff:+.4g}"
    else:
        delta = "—"
    return f"| {key} | {_fmt(av)} | {_fmt(bv)} | {delta}{arrow} |"


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    am, bm = baseline["manifest"], candidate["manifest"]
    asum, bsum = baseline["scores"]["summary"], candidate["scores"]["summary"]
    lines = [f"# Agent-eval compare — {baseline['name']} → {candidate['name']}", ""]
    lines += ["## What differed", "",
              "| | baseline | candidate |", "|---|---|---|"]
    for key in ("git_sha", "subset", "repeats", "prompt_sha256", "tier_models", "note"):
        lines.append(f"| {key} | {_fmt(am.get(key))} | {_fmt(bm.get(key))} |")
    # WHY: model outputs are stochastic, so a single run vs single run
    # comparison can look like a regression (or improvement) that is
    # really just sampling noise. Surface that loudly rather than let a
    # reader act on a delta that repeats=3 would show is within scatter.
    if am.get("repeats", 1) == 1 or bm.get("repeats", 1) == 1:
        lines += ["", "> ⚠ At least one side is a **single run**: model outputs are "
                  "stochastic, so small deltas here are noise, not signal. "
                  "Re-run with --repeats 3 before acting on a borderline delta."]
    lines += ["", "## Mechanical metrics", "",
              "| metric | baseline | candidate | Δ |", "|---|---|---|---|"]
    for key in sorted(set(asum) | set(bsum)):
        lines.append(_delta_row(key, asum.get(key), bsum.get(key)))
    aj, bj = baseline.get("judge"), candidate.get("judge")
    if aj and bj:
        lines += ["", "## Judge metrics", "",
                  "| metric | baseline | candidate | Δ |", "|---|---|---|---|"]
        for key in _JUDGE_METRICS:
            lines.append(_delta_row(key, aj["summary"].get(key), bj["summary"].get(key)))
    elif aj or bj:
        # WHY: comparing a judged run against an unjudged one would silently
        # drop the judge section with no explanation — looks like the judge
        # never ran on either side. Say explicitly that only one side has it.
        lines += ["", "> Judge metrics omitted: only one run was judged."]
    # Per-query transitions — regressions by name, not just moved means.
    a_by_id = {r["query_id"]: r for r in baseline["scores"]["per_query"]}
    b_by_id = {r["query_id"]: r for r in candidate["scores"]["per_query"]}
    regressed = [qid for qid in a_by_id.keys() & b_by_id.keys()
                 if (a_by_id[qid].get("key_fact_rate") or 0) > (b_by_id[qid].get("key_fact_rate") or 0)]
    if regressed:
        lines += ["", "## Per-query regressions (key-fact rate fell)", ""]
        lines += [f"- {qid}: {_fmt(a_by_id[qid].get('key_fact_rate'))} → "
                  f"{_fmt(b_by_id[qid].get('key_fact_rate'))}" for qid in sorted(regressed)]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--force", action="store_true",
                        help="compare despite differing corpus counts")
    args = parser.parse_args()

    a, b = load_run(args.baseline), load_run(args.candidate)
    # WHY: the corpus is still growing (see STATUS.md backfill). Comparing
    # two runs taken against different corpus sizes produces a delta that
    # measures the corpus, not the change under test — refuse by default.
    if corpus_counts_differ(a, b) and not args.force:
        print("REFUSING: corpus counts differ between runs — the delta would "
              "measure the corpus, not your change. Use --force to override.",
              file=sys.stderr)
        print(f"  baseline:  {a['manifest'].get('corpus_counts')}", file=sys.stderr)
        print(f"  candidate: {b['manifest'].get('corpus_counts')}", file=sys.stderr)
        return 2
    md = compare(a, b)
    out = args.out or (args.candidate.parent / f"compare-{a['name']}-vs-{b['name']}.md")
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
