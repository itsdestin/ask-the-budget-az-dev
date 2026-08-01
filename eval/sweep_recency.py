"""Phase D recency sweep — three metrics at every candidate weight (S21).

WHY A SIBLING OF `eval/calibrate_recency.py` RATHER THAN AN EDIT TO IT.
That module answers one question — "what is the MINIMAL weight that
restores no-year recall without damaging the standing set?" — and it is
built tightly around that question: one calibration file which it splits
by the year parser, and a deliberate hard failure when that file is
empty, so nobody can read a confident 0.0 recommendation off a sweep
that measured nothing. Both of those are correct and are pinned by
tests in `tests/test_calibrate_recency.py`.

Phase D asks a different question. Destin's acceptance criterion is not
about recall at all:

    for a simple inquiry — just an agency name, no year, no topic —
    results should feel like they come back in roughly chronological
    order, newest first.

That needs (a) a third metric recall cannot express, `eval/chronological.py`,
(b) a third query file, and (c) the OPPOSITE of the hard-fail rule —
two of the three files are authored by a separate session and may not
exist yet, so absence has to degrade to a blank column. Retrofitting
that would have inverted `calibrate_recency`'s central behaviour and
changed its CLI contract. This module reuses its query splitting and its
G1 constants (`split_by_named_year`, `G1_RECALL_AT_*`, `GRID_STEPS`) so
the two tools cannot disagree about the things they share. It does NOT
reuse the weight-grid ceiling — see SPREAD_CEILING_MULTIPLIER for the
measurement that forced a wider one.

TRACE-AND-REPLAY, AND WHY IT IS SAFE. Nothing upstream of the recency
boost depends on the weight: `pipeline.retrieve` filters, runs BM25 +
dense, fuses, reranks the WHOLE fused pool, and only then applies the
boost and trims. So the sweep retrieves each query once, keeps the
reranked pool, and re-applies the real `apply_recency_boost` at each
candidate weight offline. A 13-weight sweep costs one pass of retrieval
instead of thirteen — which is the difference between minutes and most
of an hour on a shared machine.

The cost of that trick is a second copy of the pipeline's tail, which is
precisely the kind of thing that drifts silently. Two defences:
`tests/test_sweep_recency.py` pins the replay against the real
`apply_recency_boost` and the real skip rules, and `--verify N` re-runs
N queries through the ACTUAL pipeline under `recency_weight()` and
diffs the result order. A mismatch there means the pipeline changed and
the replay has to be brought back into line.

BUDGET CORPUS ONLY. S21 gives the fiscal-note corpus layer 1 and no
recency boost — coordinator triage deliberately seeks similar notes at
any age. There is no `--corpus` flag because there is nothing to sweep
over there.

AFTERWARDS: whatever weight is chosen, re-run `eval/calibrate_refusal.py`.
A non-zero boost lowers `top_score`, and `top_score` is what
`harness.constants.REFUSAL_THRESHOLD` is compared against.
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

from ruamel.yaml import YAML

from eval import run_eval
from eval.calibrate_recency import (
    G1_RECALL_AT_15,
    G1_RECALL_AT_20,
    GRID_STEPS,
    split_by_named_year,
)
from eval.chronological import (
    CHANCE_RATE,
    OrderReport,
    interpret_rate,
    mean_rate,
    mean_vintage,
    order_report,
)
from eval.schema import EvalQuery, PerQueryResult
from eval.scoring import aggregate_metrics
from retrieval import query_year
from retrieval.pipeline import FUSED_TOP_K, NO_RESULTS_TOP_SCORE, RetrievalResult
from retrieval.query_year import parse_query_years
from retrieval.recency import anchor_fiscal_year, apply_recency_boost, recency_weight

# Capture depth. Must be the full fused pool: the boost can only reorder
# chunks it can see, and the FY2027 edition sitting at rank 19 is the
# exact thing S21 exists to lift. Asking for the eval's usual top_k would
# throw that tail away before the sweep ever saw it, and every weight
# would look weaker than it is.
POOL_TOP_K = FUSED_TOP_K

# How far down the list the chronological metric looks. 10 to match the
# baseline Destin read by eye ("2025, 2026, 2027, 2025, ..."); the
# criterion is about the run of results a person actually scans.
ORDER_TOP_K = 10

# The budget corpus table. Hardcoded — see the module docstring.
BUDGET_CORPUS = "budget"


@dataclass(frozen=True)
class Trace:
    """One query's reranked pool, captured once and replayed many times.

    `boost_applies` mirrors the pipeline's own guard: the boost runs only
    on the budget corpus and only when no fiscal-year filter is active.
    A query that named a year was hard-filtered by S21 layer 1, so layer
    3 is skipped and its results must be identical at every weight.
    """

    query_id: str
    query: str
    pool: list[Any] = field(default_factory=list)
    inferred_fiscal_years: list[int] = field(default_factory=list)
    boost_applies: bool = True
    latency_ms: int = 0
    error: str | None = None


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def capture_traces(
    queries: Sequence[tuple[str, str]],
    *,
    corpus: str = BUDGET_CORPUS,
    progress: bool = False,
) -> list[Trace]:
    """Retrieve each (id, query) once at weight 0.0 and keep the pool.

    Weight 0.0 explicitly rather than "whatever is installed": at 0.0
    `apply_recency_boost` returns the input untouched WITHOUT re-sorting,
    so the captured pool is the reranker's own order. Capturing under a
    non-zero weight would bake one boost into the baseline and every
    later replay would apply a second one on top.
    """
    traces: list[Trace] = []
    for index, (query_id, text) in enumerate(queries, start=1):
        start = time.monotonic()
        try:
            with recency_weight(0.0):
                request = run_eval.RetrievalRequest(
                    query=text,
                    top_k=POOL_TOP_K,
                    corpus=run_eval.CORPUS_TABLES[corpus],
                )
                result = run_eval.retrieve(request)
            elapsed = int((time.monotonic() - start) * 1000)
            inferred = list(result.inferred_fiscal_years)
            traces.append(
                Trace(
                    query_id=query_id,
                    query=text,
                    pool=list(result.chunks),
                    inferred_fiscal_years=inferred,
                    # Same condition pipeline.retrieve uses. `inferred` is
                    # non-empty exactly when layer 1 installed a year filter.
                    boost_applies=(corpus == BUDGET_CORPUS and not inferred),
                    latency_ms=elapsed,
                )
            )
        except Exception as exc:  # noqa: BLE001
            # One malformed query must not abort the sweep before a single
            # row prints — STATUS.md #47, an apostrophe used to crash the
            # BM25 parser on 14 of 34 queries.
            elapsed = int((time.monotonic() - start) * 1000)
            traces.append(
                Trace(
                    query_id=query_id,
                    query=text,
                    pool=[],
                    latency_ms=elapsed,
                    error=f"{type(exc).__name__}: {exc}",
                )
            )
        if progress:
            mark = "!" if traces[-1].error else "."
            print(mark, end="", flush=True)
            if index % 50 == 0:
                print(f" {index}", flush=True)
    if progress:
        print(flush=True)
    return traces


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


def replay(trace: Trace, *, weight: float, top_k: int) -> RetrievalResult:
    """Re-derive what `retrieve()` would have returned at `weight`.

    Boost the whole captured pool, THEN trim — the same order the
    pipeline uses, and the reason capture keeps the full pool.
    """
    chunks = list(trace.pool)
    if trace.boost_applies and chunks:
        chunks = apply_recency_boost(
            chunks, anchor_fy=anchor_fiscal_year(chunks), weight=weight
        )
    chunks = chunks[:top_k]
    return RetrievalResult(
        chunks=chunks,
        # A capture that crashed has no pool; it keeps the no-results
        # sentinel so it reads as a failure at every weight rather than
        # as a confident empty answer (which would inflate refusal
        # metrics — see run_eval.run_one_query for the same reasoning).
        top_score=chunks[0].score if chunks else NO_RESULTS_TOP_SCORE,
        reranker_scores=[c.score for c in chunks],
        inferred_fiscal_years=list(trace.inferred_fiscal_years),
    )


@contextmanager
def _replaying(traces: Sequence[Trace], weight: float) -> Iterator[None]:
    """Install a replay function over `run_eval.retrieve` for one weight.

    WHY monkeypatch rather than a parallel scoring path: `run_one_query`
    owns the lookup / comparison / refusal dispatch and the crash
    handling. Reimplementing that here would give the sweep a second
    definition of "pass", and the sweep's numbers would stop being
    comparable with `eval/run_eval.py`'s. `run_eval.retrieve` is already
    the codebase's designated seam (see calibrate_recency's import note).
    """
    by_query = {t.query: t for t in traces}
    original = run_eval.retrieve

    def replayed(req, **_kwargs):
        trace = by_query.get(req.query)
        if trace is None:
            # Should not happen; failing loudly beats silently scoring a
            # query against somebody else's pool.
            raise KeyError(f"no captured trace for query: {req.query!r}")
        return replay(trace, weight=weight, top_k=req.top_k)

    run_eval.retrieve = replayed
    try:
        yield
    finally:
        run_eval.retrieve = original


def measure_order(
    traces: Sequence[Trace], *, weight: float, top_k: int = ORDER_TOP_K
) -> list[OrderReport]:
    """Chronological-order reports for the order-query set at one weight."""
    return [
        order_report(
            t.query_id, t.query, replay(t, weight=weight, top_k=top_k).chunks
        )
        for t in traces
    ]


# ---------------------------------------------------------------------------
# Loading the order-query set (schema owned by another session)
# ---------------------------------------------------------------------------

# Keys an authoring session might plausibly use for the question text.
_QUERY_TEXT_KEYS = ("query", "text", "q", "question", "prompt")
_QUERY_ID_KEYS = ("id", "name", "slug")


def load_order_queries(path: str) -> tuple[list[tuple[str, str]], str]:
    """Load the chronological-order query set. Returns (queries, note).

    Deliberately tolerant. This file is authored by a separate session
    and its exact schema is that session's to choose, so the loader
    accepts a bare list of strings, a list of `{id, query, ...}` records
    (the standard `eval/queries.yaml` shape), or either of those wrapped
    under a top-level key. Ground truth is not required — the metric
    scores ORDER, so a question with no expected chunk is still a
    perfectly good measurement.

    Absence and emptiness are reported in `note`, never raised: two of
    the sweep's three sets may legitimately not exist yet, and a crash
    would take the other two down with them.
    """
    file = Path(path)
    if not file.exists():
        return [], f"not found: {path} — its column will be blank"

    yaml = YAML(typ="safe")
    try:
        raw = yaml.load(file.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return [], f"could not parse {path}: {type(exc).__name__}: {exc}"

    if isinstance(raw, dict):
        # Wrapped shape: take the first list-valued key.
        raw = next((v for v in raw.values() if isinstance(v, list)), None)
    if not raw:
        return [], f"empty: {path} — its column will be blank"

    queries: list[tuple[str, str]] = []
    for index, item in enumerate(raw, start=1):
        if isinstance(item, str):
            queries.append((f"r-{index:03d}", item))
            continue
        if not isinstance(item, dict):
            continue
        text = next(
            (item[k] for k in _QUERY_TEXT_KEYS if isinstance(item.get(k), str)), None
        )
        if not text:
            continue
        query_id = next(
            (item[k] for k in _QUERY_ID_KEYS if isinstance(item.get(k), str)),
            f"r-{index:03d}",
        )
        queries.append((query_id, text))

    if not queries:
        return [], f"no usable entries in {path} — its column will be blank"
    return queries, f"{len(queries)} queries from {path}"


# ---------------------------------------------------------------------------
# Coverage: does the recall set actually exercise the boost at all?
# ---------------------------------------------------------------------------


def boost_coverage(queries: Sequence[EvalQuery]) -> tuple[int, int]:
    """(queries that exercise the boost, total) for a recall set.

    A query exercises layer 3 only if it names NO fiscal year (otherwise
    layer 1 hard-filters it and the boost is skipped) AND has ground
    truth to recall (a refusal query has no chunk, so its recall is not
    measured at any weight).

    WHY this is computed and printed rather than left implicit: measured
    2026-08-01, 32 of the 34 queries in eval/queries.yaml name a year and
    the other 2 are refusal queries. The set is STRUCTURALLY BLIND to the
    recency boost — its recall is flat across the entire sweep, and a
    reader who did not know that would take the flat column as proof the
    weight is safe. It is proof of nothing.
    """
    exercising = sum(
        1
        for q in queries
        if not parse_query_years(q.query) and q.expected_chunks
    )
    return exercising, len(queries)


def strip_years(query: str) -> str:
    """Remove the fiscal-year tokens `parse_query_years` would act on.

    WHY the private regexes from `retrieval.query_year` rather than a
    fresh pattern: a second dialect of "what counts as a year" would
    strip a different set of tokens than the filter recognises, and the
    proxy would then be measuring queries that are still year-filtered
    while claiming they are not. Reusing the originals makes drift
    impossible, and the assertion below catches it if it happens anyway.
    """
    spans: list[tuple[int, int]] = []
    for match in query_year._FOUR_DIGIT.finditer(query):
        year = int(match.group(1))
        if not (
            query_year.MIN_PLAUSIBLE_YEAR <= year <= query_year.MAX_PLAUSIBLE_YEAR
        ):
            continue
        if query_year._YEAR_LOOKALIKE_PREFIX.search(query[: match.start(1)]):
            continue
        spans.append(match.span())
    for match in query_year._TWO_DIGIT.finditer(query):
        if query_year._expand_two_digit(int(match.group(1))) is not None:
            spans.append(match.span())

    if not spans:
        return query

    pieces: list[str] = []
    cursor = 0
    for start, end in sorted(spans):
        if start < cursor:
            continue
        pieces.append(query[cursor:start])
        cursor = end
    pieces.append(query[cursor:])
    cleaned = re.sub(r"\s{2,}", " ", "".join(pieces)).strip(" ,")

    if parse_query_years(cleaned):
        raise ValueError(
            f"strip_years left a parseable year in {cleaned!r} (from {query!r})"
        )
    return cleaned


def year_stripped_proxy(queries: Sequence[EvalQuery]) -> list[EvalQuery]:
    """Derive a boost-exercising recall set from year-named queries.

    THE PROXY, AND ITS LIMIT. `eval/queries_historical.yaml` — the set
    that would properly measure what a recency boost costs — is authored
    elsewhere and may not exist. In its absence this takes each
    explicit-year query, removes the year, and keeps the ORIGINAL ground
    truth. The result is a question with no year whose correct answer
    lives in a specific, often old, edition: exactly the population a
    recency boost is most likely to bury.

    Read the number as an UPPER BOUND on the cost, not as the cost. A
    real analyst typing "DES caseworker funding" with no year usually
    does want the newest edition, so some of the demotions this reports
    are the feature working rather than a regression. It measures how
    hard the boost pushes old ground truth down, which is the quantity
    that matters, and leaves the judgement to the reader.

    Refusal queries are dropped: they carry no chunk to recall.

    COMPARISON queries are dropped too, and for a sharper reason. Their
    years are load-bearing grammar, not a filter hint — stripping
    "between the FY 2026 and FY 2027 Baselines" leaves "between the and
    Baselines", which is not a question a person would ask and is not a
    question the retriever can answer. Measured 2026-08-01: all three
    comparison queries in the derived set produced that shape, and two
    of them registered as recall IMPROVEMENTS at higher weights, which
    is noise from a broken sentence being scored at all.
    """
    proxy: list[EvalQuery] = []
    for query in queries:
        if query.type in ("refusal", "comparison") or not query.expected_chunks:
            continue
        stripped = strip_years(query.query)
        if not stripped or stripped == query.query:
            continue
        proxy.append(query.model_copy(update={"query": stripped}))
    return proxy


def ground_truth_years(queries: Sequence[EvalQuery]) -> dict[int, int]:
    """{fiscal_year: count} over a set's expected chunks.

    WHY it is printed: measured 2026-08-01, every ground-truth chunk in
    eval/queries.yaml is FY2025-2027 — the set was authored before the
    S20 backfill put twenty older editions in the corpus. A recency boost
    HELPS a recent target, so a proxy built from those queries understates
    the harm to old ones and can even show recall improving. The reader
    has to see the vintage of the ground truth to read the proxy column
    correctly.
    """
    counts: dict[int, int] = {}
    for query in queries:
        for expected in query.expected_chunks:
            year = expected.dimensions.fiscal_year
            counts[year] = counts.get(year, 0) + 1
    return dict(sorted(counts.items()))


def load_eval_set(path: str) -> tuple[list[EvalQuery], str]:
    """Load a standard eval query file, tolerating absence and emptiness."""
    file = Path(path)
    if not file.exists():
        return [], f"not found: {path} — its column will be blank"
    try:
        queries = run_eval.load_queries(path)
    except Exception as exc:  # noqa: BLE001
        return [], f"could not parse {path}: {type(exc).__name__}: {exc}"
    if not queries:
        return [], f"empty: {path} — its column will be blank"
    return queries, f"{len(queries)} queries from {path}"


# ---------------------------------------------------------------------------
# The sweep
# ---------------------------------------------------------------------------


def _score_set(
    queries: Sequence[EvalQuery], *, threshold: float
) -> tuple[Any | None, dict[str, int | None]]:
    """Run one eval set through the ordinary scoring at the installed weight.

    Returns (EvalSummary or None, {query_id: rank or None}). Per-query
    RANK rather than pass/fail: pass/fail is measured at top-20, and a
    weight that shoves a ground-truth chunk from rank 2 to rank 18 costs
    the analyst real ground while leaving pass/fail untouched. The report
    has to be able to name that.
    """
    if not queries:
        return None, {}
    per_query: list[PerQueryResult] = [
        run_eval.run_one_query(q, threshold, corpus=BUDGET_CORPUS) for q in queries
    ]
    return aggregate_metrics(per_query), {
        # A refusal-type query has no rank; its pass/fail is folded in as
        # a sentinel rank so a refusal that stops passing still shows up.
        p.id: (p.rank if p.type != "refusal" else (1 if p.status == "pass" else None))
        for p in per_query
    }


# The rank cutoff regressions are judged at. G1's gating metric is
# recall@15, and retrieve() returns 15 chunks to the model, so falling
# past 15 is the point at which a chunk stops being read at all.
REGRESSION_K = 15

# The second cutoff. recall@5 is the tracked-but-ungated metric and it is
# what a person scanning the search page actually sees, so a chunk falling
# from rank 3 to rank 12 is a real cost even though recall@15 never moves.
# Measured 2026-08-01: on the year-stripped proxy, recall@15 is flat across
# the entire sweep while recall@5 swings 58.6%-82.8%. Reporting only the
# @15 cutoff would have shown that weight as free.
REGRESSION_K_TIGHT = 5


def _transitions(
    baseline: dict[str, int | None],
    current: dict[str, int | None],
    *,
    k: int = REGRESSION_K,
) -> tuple[list[str], list[str]]:
    """(regressions, recoveries) between two {query_id: rank} maps.

    A regression is a ground-truth chunk that WAS inside the top `k` and
    no longer is — which includes falling out of the returned set
    altogether.
    """

    def inside(rank: int | None) -> bool:
        return rank is not None and rank <= k

    regressions = sorted(
        qid
        for qid, rank in current.items()
        if inside(baseline.get(qid)) and not inside(rank)
    )
    recoveries = sorted(
        qid
        for qid, rank in current.items()
        if not inside(baseline.get(qid)) and inside(rank)
    )
    return regressions, recoveries


def sweep(
    *,
    current: Sequence[EvalQuery],
    historical: Sequence[EvalQuery],
    order_queries: Sequence[tuple[str, str]],
    weights: Sequence[float],
    proxy: Sequence[EvalQuery] = (),
    threshold: float = run_eval.DEFAULT_REFUSAL_THRESHOLD,
    order_top_k: int = ORDER_TOP_K,
    progress: bool = False,
) -> list[dict[str, Any]]:
    """Measure all three sets at every candidate weight.

    Retrieval happens ONCE per query, up front; every weight after that
    is arithmetic over the captured pools. See the module docstring.

    `proxy` is the optional year-stripped derived set — see
    `year_stripped_proxy` for what its numbers do and do not mean.
    """
    recall_queries = list(current) + list(historical) + list(proxy)
    if progress and recall_queries:
        print(f"Capturing {len(recall_queries)} recall queries", end=" ", flush=True)
    recall_traces = capture_traces(
        [(q.id, q.query) for q in recall_queries], progress=progress
    )
    if progress and order_queries:
        print(f"Capturing {len(order_queries)} order queries", end=" ", flush=True)
    order_traces = capture_traces(list(order_queries), progress=progress)

    rows: list[dict[str, Any]] = []
    baseline_current: dict[str, int | None] = {}
    baseline_historical: dict[str, int | None] = {}
    baseline_proxy: dict[str, int | None] = {}
    historical_baseline_recall: float | None = None

    for step, weight in enumerate(weights):
        with _replaying(recall_traces, weight):
            current_summary, current_status = _score_set(current, threshold=threshold)
            historical_summary, historical_status = _score_set(
                historical, threshold=threshold
            )
            proxy_summary, proxy_status = _score_set(proxy, threshold=threshold)

        order_reports = measure_order(order_traces, weight=weight, top_k=order_top_k)

        if step == 0:
            baseline_current = current_status
            baseline_historical = historical_status
            baseline_proxy = proxy_status
            historical_baseline_recall = (
                historical_summary.recall_at_15 if historical_summary else None
            )

        current_regressions, current_recoveries = _transitions(
            baseline_current, current_status
        )
        historical_regressions, _ = _transitions(baseline_historical, historical_status)
        proxy_regressions, proxy_recoveries = _transitions(baseline_proxy, proxy_status)
        current_regressions_5, _ = _transitions(
            baseline_current, current_status, k=REGRESSION_K_TIGHT
        )
        proxy_regressions_5, proxy_recoveries_5 = _transitions(
            baseline_proxy, proxy_status, k=REGRESSION_K_TIGHT
        )
        historical_at_15 = (
            historical_summary.recall_at_15 if historical_summary else None
        )

        rows.append(
            {
                "weight": weight,
                "current_recall_at_5": (
                    current_summary.recall_at_5 if current_summary else None
                ),
                "current_recall_at_15": (
                    current_summary.recall_at_15 if current_summary else None
                ),
                "current_recall_at_20": (
                    current_summary.recall_at_20 if current_summary else None
                ),
                "current_refusal_precision": (
                    current_summary.refusal_precision if current_summary else None
                ),
                "current_regressions": current_regressions,
                "current_recoveries": current_recoveries,
                "historical_recall_at_15": historical_at_15,
                "historical_recall_at_20": (
                    historical_summary.recall_at_20 if historical_summary else None
                ),
                "historical_regressions": historical_regressions,
                # Explicit-year queries are hard-filtered by S21 layer 1, so
                # layer 3 never touches them. Movement here is a broken skip
                # rule, not a tuning result, and it disqualifies the weight.
                "historical_invariant": historical_at_15 == historical_baseline_recall,
                # Derived set — an UPPER BOUND on the cost, not the cost.
                # See year_stripped_proxy().
                "proxy_recall_at_5": (
                    proxy_summary.recall_at_5 if proxy_summary else None
                ),
                "proxy_recall_at_15": (
                    proxy_summary.recall_at_15 if proxy_summary else None
                ),
                "proxy_regressions": proxy_regressions,
                "proxy_recoveries": proxy_recoveries,
                "current_regressions_at_5": current_regressions_5,
                "proxy_regressions_at_5": proxy_regressions_5,
                "proxy_recoveries_at_5": proxy_recoveries_5,
                "order_rate": mean_rate(order_reports),
                "order_vintage": mean_vintage(order_reports),
                "order_reports": order_reports,
            }
        )
    return rows


# Ceiling of the default weight grid, as a multiple of the median
# within-query score spread.
#
# WHY this tool does NOT reuse calibrate_recency's `spread / 5` ceiling:
# that ceiling is right for its question ("the minimal weight that
# restores recall"), where anything stronger than a tiebreaker is out of
# scope by definition. Chronological ORDER is a different quantity and it
# does not arrive until the weight is comparable to the spread itself.
# Measured 2026-08-01 on a spread of ~5.5: the order rate is 69.9% at
# weight 1.0 and does not reach 90% until weight 4.0. A grid stopping at
# spread/5 = 1.1 would have reported "no weight qualifies" every time
# while never testing the range where the answer lives. 1.5x the spread
# covers the whole curve including saturation.
SPREAD_CEILING_MULTIPLIER = 1.5


def order_weight_grid(spread: float, steps: int = GRID_STEPS) -> list[float]:
    """Ascending candidate weights, 0.0 .. spread * SPREAD_CEILING_MULTIPLIER.

    Ascending because `recommend` returns the FIRST qualifying row, and
    "first" only means "minimal" on a sorted grid. De-duplicated so a
    narrow spread does not print the same candidate three times and look
    like a wider sweep than it is.
    """
    ceiling = spread * SPREAD_CEILING_MULTIPLIER
    if ceiling <= 0:
        return [0.0]
    grid: list[float] = []
    for i in range(steps + 1):
        candidate = round(ceiling * i / steps, 4)
        if not grid or candidate != grid[-1]:
            grid.append(candidate)
    return grid


def median_pool_spread(traces: Sequence[Trace]) -> float:
    """Median within-query reranker-score spread across captured pools.

    Within-query, not across queries: the boost competes against the gap
    between the chunks returned for ONE question, and that gap is the
    scale a candidate weight has to be measured on. Read off the captured
    pools rather than re-retrieving, which is what `calibrate_recency`'s
    equivalent probe has to do.
    """
    spreads = [
        max(c.score for c in t.pool) - min(c.score for c in t.pool)
        for t in traces
        if len(t.pool) >= 2
    ]
    return statistics.median(spreads) if spreads else 0.0


# ---------------------------------------------------------------------------
# Replay verification
# ---------------------------------------------------------------------------


def verify_replay(
    traces: Sequence[Trace], *, weight: float, sample: int
) -> list[tuple[str, bool, str]]:
    """Re-run `sample` queries through the REAL pipeline and diff the order.

    The sweep's speed comes from re-deriving the boost outside the
    pipeline. This is the check that the re-derivation still matches what
    the pipeline does — the one failure mode the unit tests cannot catch,
    because they replace the pipeline with a fake.
    """
    results: list[tuple[str, bool, str]] = []
    for trace in [t for t in traces if not t.error][:sample]:
        expected = [c.chunk_id for c in replay(trace, weight=weight, top_k=POOL_TOP_K)
                    .chunks]
        with recency_weight(weight):
            request = run_eval.RetrievalRequest(
                query=trace.query,
                top_k=POOL_TOP_K,
                corpus=run_eval.CORPUS_TABLES[BUDGET_CORPUS],
            )
            actual = [c.chunk_id for c in run_eval.retrieve(request).chunks]
        ok = expected == actual
        detail = "identical" if ok else f"replay {expected[:3]} vs live {actual[:3]}"
        results.append((trace.query, ok, detail))
    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value:.1%}"


def _fy(value: float | None) -> str:
    return "—" if value is None else f"{value:.1f}"


def format_table(rows: Sequence[dict[str, Any]]) -> str:
    """The at-a-glance trade-off table."""
    lines = [
        f"  {'weight':>7} | {'cur@5':>7} {'cur@15':>7} {'cur@20':>7} {'refuse':>7} "
        f"| {'hist@15':>8} {'inv':>4} | {'prx@5':>7} {'prx@15':>7} "
        f"| {'ORDER':>7} {'vintage':>8} | regressions",
        f"  {'-' * 7}-+-{'-' * 7}-{'-' * 7}-{'-' * 7}-{'-' * 7}-+-"
        f"{'-' * 8}-{'-' * 4}-+-{'-' * 7}-{'-' * 7}-+-{'-' * 7}-{'-' * 8}-+---------",
    ]
    for row in rows:
        regressions = (
            row["current_regressions"]
            + row["historical_regressions"]
            + [f"~{q}" for q in row["proxy_regressions"]]
        )
        shown = ", ".join(regressions[:4]) + (
            f" (+{len(regressions) - 4})" if len(regressions) > 4 else ""
        )
        lines.append(
            f"  {row['weight']:>7.3f} | "
            f"{_pct(row['current_recall_at_5']):>7} "
            f"{_pct(row['current_recall_at_15']):>7} "
            f"{_pct(row['current_recall_at_20']):>7} "
            f"{_pct(row['current_refusal_precision']):>7} | "
            f"{_pct(row['historical_recall_at_15']):>8} "
            f"{('yes' if row['historical_invariant'] else 'NO!'):>4} | "
            f"{_pct(row['proxy_recall_at_5']):>7} "
            f"{_pct(row['proxy_recall_at_15']):>7} | "
            f"{_pct(row['order_rate']):>7} "
            f"{_fy(row['order_vintage']):>8} | "
            f"{shown if regressions else '—'}"
        )
    return "\n".join(lines)


def recommend(
    rows: Sequence[dict[str, Any]], *, order_target: float = 0.90
) -> tuple[dict[str, Any] | None, str]:
    """Smallest weight that reaches the order target without paying for it.

    Three bars, all of which must hold:
      * current-set recall stays at or above its weight-0.0 value AND
        clears G1 (recall@15 >= 90%, recall@20 >= 95%);
      * the explicit-year historical set is unmoved (layer 1 owns those);
      * the chronological-order rate reaches `order_target`.

    The year-stripped proxy is deliberately NOT a gate. It is a derived
    set whose ground truth is arguably wrong by construction (see
    `year_stripped_proxy`), so letting it veto a weight would give a
    guess the authority of a measurement. It is reported beside the
    recommendation instead, which is where a human can weigh it.

    Returns (row or None, reasoning). Deliberately NOT "the least-bad
    row" — a recommendation that misses a bar reads as a pass, and the
    operator has to be able to see that nothing qualified.
    """
    if not rows:
        return None, "no rows"

    baseline = rows[0]
    base_15 = baseline["current_recall_at_15"]
    base_20 = baseline["current_recall_at_20"]

    for row in rows:
        if not row["historical_invariant"]:
            continue
        if row["current_regressions"]:
            continue
        cur15, cur20 = row["current_recall_at_15"], row["current_recall_at_20"]
        if cur15 is not None:
            if base_15 is not None and cur15 < base_15:
                continue
            if cur15 < G1_RECALL_AT_15:
                continue
        if cur20 is not None:
            if base_20 is not None and cur20 < base_20:
                continue
            if cur20 < G1_RECALL_AT_20:
                continue
        if row["order_rate"] is None:
            continue
        if row["order_rate"] < order_target:
            continue
        return row, (
            f"smallest weight reaching {order_target:.0%} chronological order "
            "with no current-set regression and the explicit-year set unmoved"
        )

    return None, (
        f"no weight reached {order_target:.0%} chronological order without "
        "costing current-set recall or moving the explicit-year set"
    )


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def _json_safe(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for row in rows:
        payload = {k: v for k, v in row.items() if k != "order_reports"}
        payload["order_reports"] = [
            {
                "query_id": r.query_id,
                "query": r.query,
                "fiscal_years": r.fiscal_years,
                "newest_first_rate": r.newest_first_rate,
                "mean_fiscal_year_at_5": r.mean_fiscal_year_at_5,
            }
            for r in row["order_reports"]
        ]
        return_row = payload
        out.append(return_row)
    return out


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass

    parser = argparse.ArgumentParser(
        description="Sweep the S21 recency weight against recall AND order"
    )
    parser.add_argument("--current-queries", default="eval/queries.yaml")
    parser.add_argument("--historical-queries", default="eval/queries_historical.yaml")
    parser.add_argument("--order-queries", default="eval/queries_recency.yaml")
    parser.add_argument(
        "--order-query", action="append", default=[],
        help="Ad-hoc order query, repeatable. Appended to --order-queries.",
    )
    parser.add_argument(
        "--weights", default=None,
        help="Explicit comma-separated grid, e.g. '0,0.05,0.1'",
    )
    parser.add_argument("--steps", type=int, default=GRID_STEPS)
    parser.add_argument("--order-top-k", type=int, default=ORDER_TOP_K)
    parser.add_argument(
        "--threshold", type=float, default=run_eval.DEFAULT_REFUSAL_THRESHOLD
    )
    parser.add_argument(
        "--order-target", type=float, default=0.90,
        help="Chronological-order rate the recommendation aims for",
    )
    parser.add_argument(
        "--verify", type=int, default=3,
        help="Queries to re-run through the real pipeline to check the replay",
    )
    parser.add_argument(
        "--no-proxy", action="store_true",
        help=(
            "Skip the year-stripped proxy set. Only do this once "
            "eval/queries_historical.yaml exists — without either, nothing "
            "in the sweep measures what the boost costs recall."
        ),
    )
    parser.add_argument("--results-dir", default="eval/results")
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    started = time.monotonic()

    current, current_note = load_eval_set(args.current_queries)
    historical_all, historical_note = load_eval_set(args.historical_queries)
    order_queries, order_note = load_order_queries(args.order_queries)
    order_queries = list(order_queries) + [
        (f"cli-{i:03d}", q) for i, q in enumerate(args.order_query, start=1)
    ]

    # The historical file mixes explicit-year and no-year entries; split it
    # with the SAME parser retrieval uses so the sweep's idea of "this one
    # was year-filtered" can never disagree with the pipeline's.
    no_year, historical = split_by_named_year(list(historical_all))

    print(f"current set:    {current_note}")
    print(f"historical set: {historical_note}")
    if historical_all:
        print(
            f"                split -> {len(historical)} explicit-year, "
            f"{len(no_year)} no-year"
        )
    print(f"order set:      {order_note}")
    if args.order_query:
        print(f"                + {len(args.order_query)} ad-hoc from --order-query")
    print()

    if not (current or historical or order_queries):
        print("Nothing to measure. Point at least one query set at real queries.")
        raise SystemExit(1)

    # The no-year half of the historical set measures the same thing the
    # order set does but with chunk-level ground truth, so it is folded
    # into the current set's recall column rather than dropped.
    current_plus = list(current) + list(no_year)

    exercising, total = boost_coverage(current_plus)
    print(
        f"Boost coverage: {exercising} of {total} recall queries name no year "
        "and carry ground truth,\n                so only those can move at all "
        "when the weight changes."
    )
    if exercising == 0:
        print(
            "  ** WARNING: NOTHING in the recall set exercises the recency "
            "boost. **\n"
            "  A flat recall column below is NOT evidence the weight is safe — "
            "it is\n  evidence the set never runs the code path. Author "
            "eval/queries_historical.yaml\n  (no-year entries with real ground "
            "truth) before treating recall as a gate."
        )

    proxy: list[EvalQuery] = []
    if not args.no_proxy:
        proxy = year_stripped_proxy(current_plus)
        if proxy:
            years = ground_truth_years(proxy)
            spread = ", ".join(f"FY{y}x{n}" for y, n in years.items())
            print(
                f"  Year-stripped proxy: {len(proxy)} derived queries "
                "(prx@ columns).\n  Upper bound on the cost, not the cost — "
                "see year_stripped_proxy()."
            )
            print(f"  Its ground truth is {spread}.")
            if years and min(years) >= 2025:
                print(
                    "  ** Every target is recent, so the boost HELPS this set. "
                    "It cannot\n     measure harm to an old target — nothing in "
                    "the sweep can, until\n     eval/queries_historical.yaml "
                    "carries pre-2025 ground truth. **"
                )
    print()

    if args.weights:
        weights = [float(w) for w in args.weights.split(",") if w.strip()]
    else:
        print("Probing the within-query score spread...")
        probe_queries = order_queries or [(q.id, q.query) for q in current_plus]
        spread = median_pool_spread(capture_traces(probe_queries[:12]))
        weights = order_weight_grid(spread, steps=args.steps)
        print(
            f"Median spread {spread:.2f} -> {len(weights)} weights, "
            f"{weights[0]} .. {weights[-1]}\n"
        )

    rows = sweep(
        current=current_plus,
        historical=historical,
        order_queries=order_queries,
        weights=weights,
        proxy=proxy,
        threshold=args.threshold,
        order_top_k=args.order_top_k,
        progress=True,
    )

    print()
    print(format_table(rows))
    print(
        f"\n  ORDER = share of comparable result pairs returned newest-first. "
        f"{CHANCE_RATE:.0%} = no year ordering at all; 100% = perfectly "
        "newest-first.\n  vintage = mean fiscal year of the top "
        f"{args.order_top_k // 2 or 5} results (higher = more recent)."
    )

    pick, reasoning = recommend(rows, order_target=args.order_target)
    if pick is None:
        print(f"\nNo recommendation: {reasoning}.")
        print(
            "  Read the table and decide what it is telling you. Do NOT pick "
            "the least-bad row — that would read as a pass."
        )
    else:
        print(f"\nRecommended RECENCY_BOOST_PER_YEAR: {pick['weight']}")
        print(f"  ({reasoning})")
        print(
            f"  order {_pct(pick['order_rate'])} — "
            f"{interpret_rate(pick['order_rate'])}"
        )
        baseline = rows[0]
        print(
            f"  refusal precision {_pct(baseline['current_refusal_precision'])} -> "
            f"{_pct(pick['current_refusal_precision'])} "
            "(the boost lowers top_score — recalibrate REFUSAL_THRESHOLD)"
        )
        if proxy:
            print(
                f"  year-stripped proxy: recall@5 "
                f"{_pct(baseline['proxy_recall_at_5'])} -> "
                f"{_pct(pick['proxy_recall_at_5'])}, recall@15 "
                f"{_pct(baseline['proxy_recall_at_15'])} -> "
                f"{_pct(pick['proxy_recall_at_15'])}"
            )
            for label, key in (
                (f"demoted past rank {REGRESSION_K_TIGHT}", "proxy_regressions_at_5"),
                (f"demoted past rank {REGRESSION_K}", "proxy_regressions"),
                (f"promoted into rank {REGRESSION_K_TIGHT}", "proxy_recoveries_at_5"),
            ):
                if pick[key]:
                    print(f"    {label}: {', '.join(pick[key])}")
        if pick["current_regressions_at_5"]:
            print(
                f"  current set demoted past rank {REGRESSION_K_TIGHT}: "
                f"{', '.join(pick['current_regressions_at_5'])}"
            )

    # Verify the replay against the real pipeline at the weight that matters.
    verify_at = pick["weight"] if pick else (weights[-1] if weights else 0.0)
    if args.verify > 0 and (current_plus or order_queries):
        print(f"\nVerifying the replay against the real pipeline at {verify_at}...")
        probe = capture_traces(
            (order_queries or [(q.id, q.query) for q in current_plus])[: args.verify]
        )
        for query, ok, detail in verify_replay(
            probe, weight=verify_at, sample=args.verify
        ):
            print(f"  {'OK ' if ok else 'MISMATCH'} {query[:50]!r}: {detail}")

    elapsed = time.monotonic() - started
    print(f"\nWall clock: {elapsed / 60:.1f} min")

    if not args.no_write:
        results_dir = Path(args.results_dir)
        results_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        path = results_dir / f"recency-sweep-{stamp}-{_git_sha()}.json"
        path.write_text(
            json.dumps(
                {
                    "timestamp": stamp,
                    "git_sha": _git_sha(),
                    "order_top_k": args.order_top_k,
                    "threshold": args.threshold,
                    "notes": {
                        "current": current_note,
                        "historical": historical_note,
                        "order": order_note,
                    },
                    # The order set may be ad-hoc (--order-query) while the
                    # real file is still being authored, so record exactly
                    # what was measured rather than only its filename.
                    "order_queries": [
                        {"id": qid, "query": text} for qid, text in order_queries
                    ],
                    "weights": list(weights),
                    "recommendation": pick["weight"] if pick else None,
                    "reasoning": reasoning,
                    "elapsed_s": round(elapsed, 1),
                    "rows": _json_safe(rows),
                },
                indent=2,
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        print(f"Wrote {path}")

    print(
        "\nWhatever weight is chosen, re-run eval/calibrate_refusal.py — a "
        "non-zero boost lowers top_score, which is what REFUSAL_THRESHOLD in "
        "harness/constants.py is compared against."
    )


if __name__ == "__main__":
    main()
