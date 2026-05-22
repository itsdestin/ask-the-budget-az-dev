"""Refusal threshold calibration.

Reads the most recent eval result file, sweeps candidate thresholds,
computes precision/recall for each, recommends the threshold that
maximizes the combined score.

The recommended threshold is a SUGGESTION. The runtime threshold is
currently embedded in the MCP system prompt at
`mcp-server/system-prompt.md` (lines mentioning `refusal_no_retrieval
— top_score < 0.30`, with a second reference in the rules table).
Updating it means editing those prompt lines, NOT flipping a Python
constant. The original Phase 1b plan envisioned a constant in
retrieval/pipeline.py named REFUSAL_RERANKER_THRESHOLD; that was
never built and the prompt holds the value instead.

Invocation:
    uv run python -m eval.calibrate_refusal
    uv run python -m eval.calibrate_refusal --result eval/results/specific.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

# Sweep spans the observed Voyage rerank-2.5 score distribution. The
# original 0.10-0.40 window (from the plan) was entirely below the
# corpus's actual top_scores (~0.50-0.95), so every threshold tied
# at 0% refusal precision. Widening to 0.10-0.90 in 0.05 steps
# surfaces meaningful tradeoffs.
DEFAULT_THRESHOLDS = [round(0.10 + i * 0.05, 2) for i in range(17)]


def compute_sweep(
    result_path: str, thresholds: list[float] = DEFAULT_THRESHOLDS
) -> list[dict]:
    """For each candidate threshold, recompute refusal_precision and
    retrieval_pass_rate from the result file's per_query data."""
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    per_query = data["per_query"]
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
        "To apply: edit the `top_score < 0.30` references in "
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
