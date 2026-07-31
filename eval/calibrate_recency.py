"""Recency-weight calibration sweep (spec S21 layer 3, plan Task 4).

Sibling of `eval/calibrate_refusal.py`: sweeps a candidate range for
`retrieval.recency.RECENCY_BOOST_PER_YEAR` and recommends the MINIMAL
weight that does the job, rather than the largest one that still passes.

Three query sets, three different jobs:

  current     eval/queries.yaml — the 34-query regression set that gates
              G1 today. The boost is not allowed to buy anything at its
              expense.
  no_year     the entries in eval/queries_historical.yaml that name NO
              fiscal year, whose ground truth is the NEWEST edition's
              chunk. This is the set the boost exists to rescue: after
              the S20 backfill, twenty near-identical editions of the
              same per-agency page compete for one query and the newest
              has no inherent advantage.
  historical  the entries that DO name a year. S21 layer 1 hard-filters
              those and layer 3 is skipped, so their recall must be
              INVARIANT across the whole sweep. A moving number here
              means the skip rule is broken, and the sweep refuses to
              recommend that weight.

The split between `no_year` and `historical` is made by the same parser
retrieval itself uses (`retrieval.query_year.parse_query_years`), so the
sweep's idea of "this one is year-filtered" cannot drift from the
pipeline's.

Invocation (after the S20 backfill — see the header of
eval/queries_historical.yaml for why it can't run before then):

    uv run python -m eval.calibrate_recency
    uv run python -m eval.calibrate_recency --queries eval/queries_historical.yaml

AFTERWARDS: re-run `eval/calibrate_refusal.py`. A non-zero boost moves
`top_score`, and `top_score` is what `harness.constants.REFUSAL_THRESHOLD`
is compared against.
"""
from __future__ import annotations

import argparse
import statistics
import sys
from typing import Any

# Imported as a MODULE, not by name: every retrieval in this script —
# the probe below and `run_one_query`'s — goes through `run_eval.retrieve`,
# so there is exactly one seam for tests to replace. Binding
# `from eval.run_eval import retrieve` here would create a second one and
# a test could patch the wrong half of the sweep.
from eval import run_eval
from eval.schema import EvalQuery, EvalSummary, PerQueryResult
from eval.scoring import aggregate_metrics
from retrieval.query_year import parse_query_years
from retrieval.recency import recency_weight

# Gate G1 as amended 2026-07-30 (see STATUS.md, Plan 1): recall@15 >= 90%
# and recall@20 >= 95%. Duplicated as constants here rather than imported
# because nothing in the codebase owns them yet — eval/run_eval.py prints
# them as literals in its Markdown too.
G1_RECALL_AT_15 = 0.90
G1_RECALL_AT_20 = 0.95

# Sweep resolution. 12 steps over the derived range; the grid always
# includes 0.0 so "off" is measured alongside every candidate.
GRID_STEPS = 12

# The grid's ceiling is the observed score spread divided by this.
#
# WHY 5: the boost is per YEAR, so at `spread / 5` a five-year gap is
# worth the entire within-query score spread — enough to reorder any
# result set the reranker produces. Anything above that is not a
# tiebreaker any more, it is a date sort with relevance as the
# tiebreaker, which is not what S21 asked for.
SPREAD_DIVISOR = 5


class EmptyQuerySetError(RuntimeError):
    """Raised when the calibration file has no usable queries."""


def split_by_named_year(
    queries: list[EvalQuery],
) -> tuple[list[EvalQuery], list[EvalQuery]]:
    """Split into (no_year, historical) using retrieval's own year parser."""
    no_year = [q for q in queries if not parse_query_years(q.query)]
    historical = [q for q in queries if parse_query_years(q.query)]
    return no_year, historical


def load_calibration_sets(path: str) -> tuple[list[EvalQuery], list[EvalQuery]]:
    """Load and split the calibration query file.

    Raises EmptyQuerySetError with the reason when the file is still the
    committed placeholder — a sweep over zero queries would otherwise
    print a confident recommendation of 0.0 backed by no measurement.
    """
    queries = run_eval.load_queries(path)
    if not queries:
        raise EmptyQuerySetError(
            f"{path} contains no queries. It ships empty on purpose: its "
            "ground truth must be real chunk_ids from the historical "
            "editions, and those arrive with the S20 backfill "
            "(PROMPT-z13-backfill.md). Author the entries described in "
            "that file's header first, then re-run this sweep."
        )
    no_year, historical = split_by_named_year(queries)
    if not no_year:
        raise EmptyQuerySetError(
            f"{path} has no year-free queries. The recency boost only "
            "ever fires on queries that name NO fiscal year, so a set "
            "made entirely of explicit-year queries measures nothing "
            "the sweep can act on."
        )
    return no_year, historical


def median_score_spread(queries: list[EvalQuery], *, corpus: str = "budget") -> float:
    """Median within-query reranker-score spread, at the current weight.

    Within-query, not across queries: the boost competes against the gap
    between the chunks returned for ONE query, so that gap is the scale
    a candidate weight has to be measured on. A cross-query spread would
    mostly measure how differently-answerable the questions are.
    """
    spreads: list[float] = []
    for query in queries:
        request = run_eval.RetrievalRequest(
            query=query.query,
            top_k=run_eval.DEFAULT_TOP_K,
            corpus=run_eval.CORPUS_TABLES[corpus],
        )
        scores = run_eval.retrieve(request).reranker_scores
        if len(scores) >= 2:
            spreads.append(max(scores) - min(scores))
    return statistics.median(spreads) if spreads else 0.0


def weights_from_spread(spread: float, steps: int = GRID_STEPS) -> list[float]:
    """Ascending candidate weights, 0.0 .. spread / SPREAD_DIVISOR.

    Ascending matters: `recommend_weight` returns the FIRST row that
    clears the bars, and "first" is only "minimal" on a sorted grid.
    """
    ceiling = spread / SPREAD_DIVISOR
    if ceiling <= 0:
        return [0.0]
    return [round(ceiling * i / steps, 4) for i in range(steps + 1)]


def _score_set(
    queries: list[EvalQuery], *, threshold: float, corpus: str
) -> EvalSummary | None:
    """Run one query set through the normal eval scoring at the weight
    currently installed. None for an empty set."""
    if not queries:
        return None
    per_query: list[PerQueryResult] = [
        run_eval.run_one_query(q, threshold, corpus=corpus) for q in queries
    ]
    return aggregate_metrics(per_query)


def sweep_weights(
    *,
    current: list[EvalQuery],
    no_year: list[EvalQuery],
    historical: list[EvalQuery],
    weights: list[float],
    threshold: float = run_eval.DEFAULT_REFUSAL_THRESHOLD,
    corpus: str = "budget",
) -> list[dict[str, Any]]:
    """Run all three sets at every candidate weight.

    The weight reaches retrieval through `recency_weight()`, which sets
    the module global the pipeline reads at call time and restores it
    afterwards — including when a step raises, so a crashed sweep can't
    leave a stray weight installed in a long-running process.
    """
    table: list[dict[str, Any]] = []
    historical_baseline: float | None = None

    for weight in weights:
        with recency_weight(weight):
            current_summary = _score_set(
                current, threshold=threshold, corpus=corpus
            )
            no_year_summary = _score_set(
                no_year, threshold=threshold, corpus=corpus
            )
            historical_summary = _score_set(
                historical, threshold=threshold, corpus=corpus
            )

        historical_at_15 = (
            historical_summary.recall_at_15 if historical_summary else None
        )
        if historical_baseline is None:
            historical_baseline = historical_at_15

        table.append(
            {
                "weight": weight,
                "current_recall_at_15": (
                    current_summary.recall_at_15 if current_summary else None
                ),
                "current_recall_at_20": (
                    current_summary.recall_at_20 if current_summary else None
                ),
                "no_year_recall_at_15": (
                    no_year_summary.recall_at_15 if no_year_summary else None
                ),
                "no_year_recall_at_20": (
                    no_year_summary.recall_at_20 if no_year_summary else None
                ),
                "historical_recall_at_15": historical_at_15,
                # Layer 1 filters these, so layer 3 never runs on them.
                # A False here is a bug in the skip rule, not a tuning
                # result, and it disqualifies the weight.
                "historical_invariant": historical_at_15 == historical_baseline,
            }
        )
    return table


def _clears(value: float | None, bar: float) -> bool:
    """A set that wasn't run (None) can't fail a bar it was never measured
    against — treat it as satisfied so a partial sweep still recommends."""
    return value is None or value >= bar


def recommend_weight(table: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The smallest weight where the current AND no-year sets both clear
    G1, and the historical set stayed invariant.

    Returns None when nothing qualifies. Deliberately NOT "the least-bad
    row": a recommendation that doesn't clear the bars would be read as a
    pass, and the operator needs to see that the sweep found nothing.
    """
    for row in table:
        if not row.get("historical_invariant", True):
            continue
        if not _clears(row["current_recall_at_15"], G1_RECALL_AT_15):
            continue
        if not _clears(row["current_recall_at_20"], G1_RECALL_AT_20):
            continue
        if not _clears(row["no_year_recall_at_15"], G1_RECALL_AT_15):
            continue
        if not _clears(row["no_year_recall_at_20"], G1_RECALL_AT_20):
            continue
        return row
    return None


def _fmt(value: float | None) -> str:
    return "—" if value is None else f"{value:.2%}"


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Sweep the S21 recency-boost weight; recommend the minimum"
    )
    parser.add_argument(
        "--queries", default="eval/queries_historical.yaml",
        help="Calibration set (no-year + explicit-year queries)",
    )
    parser.add_argument(
        "--current-queries", default="eval/queries.yaml",
        help="The standing regression set the boost must not damage",
    )
    parser.add_argument(
        "--threshold", type=float,
        default=run_eval.DEFAULT_REFUSAL_THRESHOLD,
        help="Refusal threshold to score against",
    )
    args = parser.parse_args()

    try:
        no_year, historical = load_calibration_sets(args.queries)
    except EmptyQuerySetError as exc:
        print(f"Cannot calibrate yet:\n\n  {exc}\n")
        raise SystemExit(1)

    current = run_eval.load_queries(args.current_queries)
    print(
        f"Loaded {len(current)} current, {len(no_year)} no-year, "
        f"{len(historical)} historical queries."
    )

    print("Probing the within-query score spread...")
    spread = median_score_spread(no_year)
    weights = weights_from_spread(spread)
    print(
        f"Median spread {spread:.2f} -> sweeping {len(weights)} weights "
        f"from {weights[0]} to {weights[-1]}.\n"
    )

    table = sweep_weights(
        current=current,
        no_year=no_year,
        historical=historical,
        weights=weights,
        threshold=args.threshold,
    )

    print(
        f"  {'weight':>8}  {'current@15':>11}  {'current@20':>11}  "
        f"{'no-year@15':>11}  {'hist@15':>9}  {'hist inv':>9}"
    )
    for row in table:
        print(
            f"  {row['weight']:>8.4f}  "
            f"{_fmt(row['current_recall_at_15']):>11}  "
            f"{_fmt(row['current_recall_at_20']):>11}  "
            f"{_fmt(row['no_year_recall_at_15']):>11}  "
            f"{_fmt(row['historical_recall_at_15']):>9}  "
            f"{'yes' if row['historical_invariant'] else 'NO':>9}"
        )

    pick = recommend_weight(table)
    if pick is None:
        print(
            "\nNo weight cleared both G1 bars "
            f"(recall@15 >= {G1_RECALL_AT_15:.0%}, "
            f"recall@20 >= {G1_RECALL_AT_20:.0%}) on the current AND "
            "no-year sets. Do NOT pick the least-bad row — read the table "
            "and decide what it is telling you about the corpus."
        )
        raise SystemExit(2)

    print(f"\nRecommended RECENCY_BOOST_PER_YEAR: {pick['weight']}")
    print(
        "To apply: set RECENCY_BOOST_PER_YEAR in retrieval/recency.py, then "
        "re-run eval/calibrate_refusal.py — a non-zero boost moves top_score, "
        "which is what REFUSAL_THRESHOLD in harness/constants.py is compared "
        "against."
    )


if __name__ == "__main__":
    main()
