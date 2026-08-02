"""Sweep `retrieval.agency_boost.MATCH_PENALTY` and report recall at each weight.

WHY a direct sweep rather than the trace-and-replay `eval/sweep_recency.py`
uses: the match penalty is applied AFTER the recency boost and only to the
chunks a query's WEAK matches select, so a replayed pool would have to
reproduce both the boost ordering and the per-query parser output to stay
faithful. Re-running retrieval per weight costs about a minute a step and
removes the question. The grid here is small on purpose.

WHY the grid must be passed explicitly, and this is not a style preference:
`sweep_recency` derives its grid from the observed score spread, and on
2026-08-02 that produced 13 steps of 0.585 — so 0.70 and 0.85 were never
tested and the smallest grid point clearing the target won by default. That
is how RECENCY_BOOST_PER_YEAR shipped at 2.064 when 0.85 was free. Always
name the weights.

Usage:
    JLBC_DATA_DIR=... .venv/bin/python -m eval.sweep_match_penalty \
        --weights 0,0.25,0.5,1,2,4
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import retrieval.agency_boost as agency_boost
from eval.run_eval import load_queries, run_one_query
from eval.scoring import aggregate_metrics
from harness.constants import REFUSAL_THRESHOLD

DEFAULT_QUERIES = "eval/queries.yaml"


def sweep(weights: list[float], queries_path: str) -> list[dict]:
    queries = load_queries(queries_path)
    rows: list[dict] = []

    for weight in weights:
        # The pipeline reads this module global at call time (mirroring
        # recency_weight()), so assigning it here is what a real deployment
        # at that weight would do — no seam is bypassed.
        agency_boost.MATCH_PENALTY = weight

        per_query = [
            run_one_query(q, refusal_threshold=REFUSAL_THRESHOLD) for q in queries
        ]
        metrics = aggregate_metrics(per_query)

        # The s-* block is what the weak path actually moves; the whole-set
        # number is reported beside it so a gain there that costs the rest of
        # the set cannot hide.
        shorthand = [p for p in per_query if p.id.startswith("s-")]
        shorthand_pass = sum(1 for p in shorthand if p.status == "pass")

        rows.append(
            {
                "weight": weight,
                "recall_at_5": metrics.recall_at_5,
                "recall_at_15": metrics.recall_at_15,
                "recall_at_20": metrics.recall_at_20,
                "refusal_precision": metrics.refusal_precision,
                "shorthand_pass": f"{shorthand_pass}/{len(shorthand)}",
                # top_score drives REFUSAL_THRESHOLD, and a penalty can only
                # lower it — so this column is the early warning that the
                # threshold needs re-calibrating with the weight.
                "max_top_score": max(
                    (p.top_score for p in per_query if p.top_score is not None),
                    default=None,
                ),
            }
        )
        print(
            f"  weight {weight:<6} recall@5 {metrics.recall_at_5:.4f}  "
            f"recall@15 {metrics.recall_at_15:.4f}  "
            f"recall@20 {metrics.recall_at_20:.4f}  "
            f"refusal_prec {metrics.refusal_precision:.2f}  "
            f"shorthand {rows[-1]['shorthand_pass']}",
            flush=True,
        )

    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--weights",
        required=True,
        help="EXPLICIT comma-separated grid. Required — see the module docstring.",
    )
    ap.add_argument("--queries", default=DEFAULT_QUERIES)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    weights = [float(w) for w in args.weights.split(",") if w.strip()]
    print(f"Sweeping MATCH_PENALTY over {weights}")
    rows = sweep(weights, args.queries)

    if args.out:
        Path(args.out).write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
        print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
