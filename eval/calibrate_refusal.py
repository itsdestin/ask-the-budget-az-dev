"""Refusal threshold calibration.

Reads the most recent eval result file, sweeps candidate thresholds,
computes precision/recall for each, recommends the threshold that
maximizes the combined score.

The recommended threshold is a SUGGESTION. **The runtime threshold is
`REFUSAL_THRESHOLD` in `harness/constants.py`** — one Python constant,
currently 1.9 on the local L-12 reranker's logit scale. Change it there
and nowhere else.

This docstring used to send operators to `mcp-server/system-prompt.md`.
That file is deleted, and the advice was already wrong before it was:
Plan 4 made harness/constants.py the single source precisely because
three contradictory numbers (1.9 in the prompt, 0.65 and 0.30 in stale
tool descriptions) had all reached the model at once. `harness/prompt.py`
renders the constant into the prompt, so editing prose can no longer
change behaviour — and an operator who edits prose expecting it to will
see no effect and no error.

Scale note for anyone reading old results: 1.9 is a raw cross-encoder
logit (roughly -10..10). The 0.65 and 0.30 figures in pre-2026-07-30
material were on Voyage rerank-2.5's 0..1 scale and do not transfer.

Invocation:
    uv run python -m eval.calibrate_refusal
    uv run python -m eval.calibrate_refusal --result eval/results/specific.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Post-Plan-1 the scores are raw cross-encoder logits (roughly -10..10,
# negatives normal), not Voyage's 0..1 — so a fixed grid goes stale the
# moment the model changes. Instead the sweep derives its range from the
# scores actually present in the result file being calibrated: min..max
# of top_score in 25 even steps. This survived one scale change already
# (Voyage 0.30-grid → 0.50-0.95 reality, 2026-05-22); deriving from data
# means it survives the next one too.
SWEEP_STEPS = 25

# Scores at or below this are the pipeline's "found nothing at all"
# sentinel (NO_RESULTS_TOP_SCORE = -1e9) or the eval's crashed-retrieve
# marker — not real model output. They must not stretch the sweep range.
_SENTINEL_FLOOR = -1e8


def thresholds_from_scores(per_query: list[dict]) -> list[float]:
    """Derive sweep thresholds from the observed top_score distribution,
    excluding sentinel values."""
    scores = sorted(
        p["top_score"] for p in per_query if p["top_score"] > _SENTINEL_FLOOR
    )
    if not scores:
        raise ValueError(
            "No real top_scores in this result file (every query hit the "
            "no-results sentinel) — nothing to calibrate against."
        )
    lo, hi = scores[0], scores[-1]
    if lo == hi:
        return [round(lo, 2)]
    step = (hi - lo) / SWEEP_STEPS
    return [round(lo + i * step, 2) for i in range(SWEEP_STEPS + 1)]


def compute_sweep(
    result_path: str, thresholds: list[float] | None = None
) -> list[dict]:
    """For each candidate threshold, recompute refusal_precision and
    retrieval_pass_rate from the result file's per_query data.

    Thresholds default to a data-derived grid (thresholds_from_scores);
    pass an explicit list to pin specific candidates."""
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    per_query = data["per_query"]
    if thresholds is None:
        thresholds = thresholds_from_scores(per_query)
    refusal_queries = [p for p in per_query if p["type"] == "refusal"]
    retrieval_queries = [p for p in per_query if p["type"] != "refusal"]
    total_refusal = len(refusal_queries)
    total_retrieval = len(retrieval_queries)

    table: list[dict] = []
    for threshold in thresholds:
        # Refusal precision: of queries the threshold would cause to
        # refuse, how many were expected to refuse?
        would_refuse_correct = sum(
            1
            for p in refusal_queries
            if p["top_score"] < threshold
        )
        would_refuse_incorrect = sum(
            1
            for p in retrieval_queries
            if p["top_score"] < threshold
        )
        would_refuse_total = would_refuse_correct + would_refuse_incorrect
        # Precision: of queries the threshold would cause to refuse, what
        # share were correct refusals? Denominator is would_refuse_total
        # (NOT total_refusal — that would be recall).
        if would_refuse_total == 0:
            refusal_precision = 0.0
        else:
            refusal_precision = would_refuse_correct / would_refuse_total

        # Recall: of all queries that SHOULD have been refused, how
        # many actually scored below the threshold? Without this,
        # combined_score is biased toward "don't false-refuse" and
        # silently allows "refuse-too-little" to be hidden — which
        # is exactly the failure mode we caught when reviewing the
        # first real eval run (threshold 0.60 had precision 1.00 but
        # caught only 1 of 5 refusals).
        if total_refusal == 0:
            refusal_recall = 0.0
        else:
            refusal_recall = would_refuse_correct / total_refusal

        # Retrieval pass rate: of retrieval queries, how many still
        # have top_score >= threshold (i.e., we DIDN'T accidentally
        # refuse them)?
        retrieval_passes = sum(
            1
            for p in retrieval_queries
            if p["top_score"] >= threshold
        )
        retrieval_pass_rate = (
            retrieval_passes / total_retrieval if total_retrieval else 0.0
        )

        # Three-way average: precision + recall + retrieval_pass_rate.
        # Equal-weighted because none of these three should be sacrificed
        # for the others — high precision with low recall is dangerous
        # (most refusals leak through); high recall with low pass rate
        # is also bad (we'd refuse legitimate questions). Future work
        # could use F1 for precision/recall and weight against pass rate
        # separately; equal-average is the honest v1.
        combined_score = (
            refusal_precision + refusal_recall + retrieval_pass_rate
        ) / 3

        table.append(
            {
                "threshold": threshold,
                "refusal_precision": refusal_precision,
                "refusal_recall": refusal_recall,
                "retrieval_passes": retrieval_passes,
                "retrieval_pass_rate": retrieval_pass_rate,
                "combined_score": combined_score,
            }
        )
    return table


def recommend_threshold(table: list[dict]) -> dict:
    """Pick the row with the highest combined_score (ties broken by
    lower threshold — prefer being less restrictive).

    If a row doesn't carry a precomputed `combined_score`, derive it
    from `refusal_precision` and `retrieval_pass_rate` so callers can
    feed in hand-built tables (as the unit test does)."""
    def combined(r: dict) -> float:
        if "combined_score" in r:
            return r["combined_score"]
        return (r["refusal_precision"] + r["retrieval_pass_rate"]) / 2

    return max(
        table,
        key=lambda r: (combined(r), -r["threshold"]),
    )


def find_latest_result(results_dir: Path = Path("eval/results")) -> Path:
    files = sorted(results_dir.glob("*.json"), reverse=True)
    if not files:
        raise FileNotFoundError(
            f"No eval result files in {results_dir}; run "
            "`uv run python -m eval.run_eval` first."
        )
    return files[0]


def main() -> None:
    # Windows-friendly: same stdout reconfigure as the runner.
    import sys
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Sweep refusal thresholds; recommend best"
    )
    parser.add_argument(
        "--result", default=None,
        help="Path to specific eval result JSON. Default: latest in eval/results/",
    )
    args = parser.parse_args()

    if args.result:
        result_path = args.result
    else:
        result_path = str(find_latest_result())

    print(f"Loading {result_path}...")
    table = compute_sweep(result_path)
    print(
        f"\nSweeping candidate thresholds against {result_path}:\n"
    )
    print(
        f"  {'threshold':>10}  {'precision':>10}  {'recall':>10}  "
        f"{'pass_rate':>10}  {'combined':>10}"
    )
    for row in table:
        print(
            f"  {row['threshold']:>10.2f}  "
            f"{row['refusal_precision']:>10.2f}  "
            f"{row['refusal_recall']:>10.2f}  "
            f"{row['retrieval_pass_rate']:>10.2f}  "
            f"{row['combined_score']:>10.2f}"
        )

    pick = recommend_threshold(table)
    print(
        f"\nRecommended threshold: {pick['threshold']:.2f}"
    )
    print(
        "To apply: edit the `top_score < <threshold>` references in "
        "mcp-server/system-prompt.md (the `refusal_no_retrieval` "
        "section + the rules table) to use the new value, then re-run "
        "the dogfood tests."
    )
    print(
        f"Justified by: {result_path}"
    )
    print(
        f"  refusal_precision={pick['refusal_precision']:.2f} "
        f"refusal_recall={pick['refusal_recall']:.2f} "
        f"retrieval_pass_rate={pick['retrieval_pass_rate']:.2f}"
    )
    # Count refusal queries from the source data for the explanation.
    with open(result_path, encoding="utf-8") as f:
        _data = json.load(f)
    _refusal_count = sum(1 for p in _data["per_query"] if p["type"] == "refusal")

    print(
        f"  → Of {_refusal_count} refusal queries in the eval set, "
        f"this threshold would correctly refuse "
        f"{pick['refusal_recall'] * 100:.0f}% of them. The rest still "
        f"pass through and would be answered by Claude — addressing those "
        f"belongs in a query-classifier or faithfulness-verifier layer, "
        f"not the retrieval threshold."
    )


if __name__ == "__main__":
    main()
