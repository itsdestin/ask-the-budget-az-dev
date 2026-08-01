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
    "key_fact_rate_mean", "cite_pass_rate", "first_try_cite_rate",
    "retrieval_efficiency_mean", "refusal_correct_rate", "cached_tokens_mean",
}
_LOWER_IS_BETTER = {
    "steps_mean", "retrieve_calls_mean", "input_tokens_mean", "output_tokens_mean",
    "total_cost_usd", "cost_mean_usd", "wall_p50_ms", "wall_p95_ms",
    "retrieves_after_sufficient_mean", "retries_per_citation", "errors",
    "false_refusals", "narration_hit_queries", "token_leaks",
    "internal_vocab_queries", "cost_missing_queries",
}
# Metrics whose value is taken over a population the run itself decides, keyed
# to the summary field that reports that population's size. When the two runs
# disagree on the population, the delta compares two different denominators, so
# the better/worse arrow is withheld and a footnote says why (2026-08 review,
# Finding 4).
#
# total_cost_usd is keyed on cost_missing_queries (2026-08 review, Finding 1
# in the follow-up batch): a query that CRASHES contributes $0 to the sum
# while having really spent money on the steps that ran before the crash (see
# agent_scoring.py's WHY on total_cost_usd), so a run that crashes more
# queries reports a SMALLER total_cost_usd — a regression that breaks 10 of
# 31 queries would otherwise render as "cost improved ▲". Reproduced: a
# baseline/candidate pair with cost_missing_queries 0→10 and total_cost_usd
# 1.2→0.81 rendered a green ▲ before this entry existed.
#
# Deliberately NOT extended to cost_mean_usd, steps_mean, or the other *_mean
# metrics even though they are equally population-dependent on `errors` (a
# crashed row is excluded from every ok_rows-only mean in agent_scoring.py):
# `errors` already carries its own visible ▼ on the same table, so a reader
# comparing two runs already sees the crash count move. total_cost_usd is
# different because it does NOT exclude crashed rows — it sums ALL of them —
# so the failure mode is a sum silently under-counting and INVERTING
# direction, not a mean silently changing denominator. Suppressing arrows on
# every errors-adjacent mean would strip arrows off most of this report for a
# case that's already visible elsewhere; total_cost_usd is the one metric
# where the invisibility is real and the direction can flip.
_POPULATION_DEPENDENT = {
    "retrieves_after_sufficient_mean": "retrieves_after_sufficient_n",
    "total_cost_usd": "cost_missing_queries",
}

# Per-metric explanation of WHY its population can move, keyed the same as
# _POPULATION_DEPENDENT. Not one shared template: retrieves_after_sufficient_mean
# is a MEAN with a shrinking denominator ("different denominators" is literally
# true of it), but total_cost_usd is a SUM across every row — the population
# moving means queries dropped out of the sum entirely with their real spend
# uncounted, not that a mean's denominator shrank. Reusing the mean's wording
# for a sum would be its own small dishonesty in the report.
_POPULATION_DEPENDENT_NOTES = {
    "retrieves_after_sufficient_mean": (
        "is averaged over only the queries that produced a value, and that "
        "population MOVED between these runs ({pop}). The two means have "
        "different denominators, so no better/worse arrow is shown — the Δ "
        "is not a like-for-like comparison."
    ),
    "total_cost_usd": (
        "sums every row's cost, but a query that CRASHED before its terminal "
        "frame produced no usage at all, so the money it already spent is "
        "invisible here and counted as $0 (see agent_scoring.py). The count "
        "of such queries MOVED between these runs ({pop}), so a lower total "
        "can mean 'more queries crashed silently', not 'cheaper' — no "
        "better/worse arrow is shown. `ledger.jsonl` is the real spend record."
    ),
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


def query_sets_differ(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """Did the two runs ask the same questions, with the same key facts?

    WHY a content hash and not the manifest's `queries` id list (2026-08
    review, Finding 2): the id list catches a run that dropped or added a
    query, but it is byte-identical for the case that matters more — two
    `full` runs where somebody EDITED a query's key_facts in between. The
    whole reported delta is then authoring drift, and nothing on the report
    says so. Same reasoning, and the same refuse-unless---force behavior, as
    the corpus-count guard beside it: a delta is only meaningful when you know
    what differed.

    A manifest written before hashing existed carries no `queries_sha256`;
    that reads as unknown, and unknown != a known hash, so such a run trips
    the guard and the operator makes the call with --force.
    """
    return a["manifest"].get("queries_sha256") != b["manifest"].get("queries_sha256")


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _delta_row(key: str, av: Any, bv: Any, *, arrow_ok: bool = True) -> str:
    arrow = ""
    if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
        diff = bv - av
        if diff and arrow_ok:
            better = ((diff > 0 and key in _HIGHER_IS_BETTER)
                      or (diff < 0 and key in _LOWER_IS_BETTER))
            arrow = f" {'▲' if better else '▼'}" if (key in _HIGHER_IS_BETTER or key in _LOWER_IS_BETTER) else ""
        delta = f"{diff:+.4g}"
        if not arrow_ok:
            delta += " ⚠"
    else:
        delta = "—"
    return f"| {key} | {_fmt(av)} | {_fmt(bv)} | {delta}{arrow} |"


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    am, bm = baseline["manifest"], candidate["manifest"]
    asum, bsum = baseline["scores"]["summary"], candidate["scores"]["summary"]
    lines = [f"# Agent-eval compare — {baseline['name']} → {candidate['name']}", ""]
    lines += ["## What differed", "",
              "| | baseline | candidate |", "|---|---|---|"]
    for key in ("git_sha", "subset", "repeats", "prompt_sha256",
                "queries_sha256", "tier_models", "note"):
        lines.append(f"| {key} | {_fmt(am.get(key))} | {_fmt(bm.get(key))} |")
    # WHY this banner exists even though main() refuses by default: --force
    # gets used, and a forced report must carry the reason it needed forcing
    # into the artifact somebody reads later. Same shape as the noise warning.
    if query_sets_differ(baseline, candidate):
        lines += ["", "> ⚠ **The two runs used DIFFERENT query sets** "
                  "(`queries_sha256` differs — a question, a key fact, or the "
                  "set's membership changed between them). Some or all of the "
                  "delta below is authoring drift, not a change in the system "
                  "under test."]
    # WHY: model outputs are stochastic, so a single run vs single run
    # comparison can look like a regression (or improvement) that is
    # really just sampling noise. Surface that loudly rather than let a
    # reader act on a delta that repeats=3 would show is within scatter.
    if am.get("repeats", 1) == 1 or bm.get("repeats", 1) == 1:
        lines += ["", "> ⚠ At least one side is a **single run**: model outputs are "
                  "stochastic, so small deltas here are noise, not signal. "
                  "Re-run with --repeats 3 before acting on a borderline delta."]
    # WHY: ▲/▼ encode "better/worse", not "value rose/fell" — e.g. a cost
    # increase is correctly ▼ even though the delta is positive. Without this
    # line a skimming reader sees "+0.01 ▼" and reads it as self-contradictory.
    # One line, placed right above the first table that uses the glyphs.
    lines += ["", "## Mechanical metrics", "",
              "> ▲ = improvement, ▼ = regression — the direction that's "
              "*better* for that metric, not the sign of the Δ.",
              "", "| metric | baseline | candidate | Δ |", "|---|---|---|---|"]
    population_moved = []
    for key in sorted(set(asum) | set(bsum)):
        pop_key = _POPULATION_DEPENDENT.get(key)
        arrow_ok = True
        if pop_key is not None and asum.get(pop_key) != bsum.get(pop_key):
            arrow_ok = False
            population_moved.append((key, pop_key))
        lines.append(_delta_row(key, asum.get(key), bsum.get(key), arrow_ok=arrow_ok))
    for key, pop_key in population_moved:
        pop = f"{pop_key}: {_fmt(asum.get(pop_key))} → {_fmt(bsum.get(pop_key))}"
        note = _POPULATION_DEPENDENT_NOTES[key].format(pop=pop)
        lines += ["", f"> ⚠ `{key}` {note}"]
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
                        help="compare despite differing corpus counts or query sets")
    args = parser.parse_args()

    a, b = load_run(args.baseline), load_run(args.candidate)
    # WHY this guard reads exactly like the corpus one below it (2026-08
    # review, Finding 2): they are the same idea — refuse a delta whose cause
    # is something other than the change under test. Two guards that behaved
    # differently would invite a reader to think one of them is advisory.
    if query_sets_differ(a, b) and not args.force:
        print("REFUSING: the two runs used different query sets — the delta "
              "would measure the questions, not your change. Use --force to "
              "override (the report will say so).", file=sys.stderr)
        print(f"  baseline:  queries_sha256={a['manifest'].get('queries_sha256')} "
              f"({len(a['manifest'].get('queries') or [])} queries)", file=sys.stderr)
        print(f"  candidate: queries_sha256={b['manifest'].get('queries_sha256')} "
              f"({len(b['manifest'].get('queries') or [])} queries)", file=sys.stderr)
        return 2
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
