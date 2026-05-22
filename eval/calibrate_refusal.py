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

DEFAULT_THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


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

        table.append(
            {
                "threshold": threshold,
                "refusal_precision": refusal_precision,
                "retrieval_passes": retrieval_passes,
                "retrieval_pass_rate": retrieval_pass_rate,
                "combined_score": (refusal_precision + retrieval_pass_rate) / 2,
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
        f"  {'threshold':>10}  {'refusal_precision':>18}  "
        f"{'retrieval_pass_rate':>20}  {'combined':>10}"
    )
    for row in table:
        print(
            f"  {row['threshold']:>10.2f}  "
            f"{row['refusal_precision']:>18.2f}  "
            f"{row['retrieval_pass_rate']:>20.2f}  "
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
        f"Justified by: {result_path} (refusal_precision="
        f"{pick['refusal_precision']:.2f}, retrieval_pass_rate="
        f"{pick['retrieval_pass_rate']:.2f})"
    )


if __name__ == "__main__":
    main()
