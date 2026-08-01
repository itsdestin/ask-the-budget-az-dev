"""Chronological-order metric for the S21 recency boost (Phase D).

WHY THIS EXISTS. The standing eval measures one thing: "is the right
chunk somewhere in the top K". That is a question about *membership*,
and it cannot express Destin's acceptance criterion for the recency
work, which is a question about *order*:

    for a simple inquiry — just an agency name, no year, no topic —
    results should feel like they come back in roughly chronological
    order, newest first.

Measured at weight 0.0 on 2026-08-01, fiscal years in rank order:

    Department of Corrections -> 2025 2026 2027 2025 2025 2027 2027 2026 2024 2024
    AHCCCS                    -> 2025 2023 2024 2023 2024 2025 2025 2026 2024 2025

Recall is 100% on both of those and they still read as unordered. So the
sweep needs a number recall cannot give it.

THE METRIC: `newest_first_rate`.

    Of every pair of returned results where one document is newer than
    the other, what fraction came back with the newer one listed first?

    100% = perfectly newest-first.  50% = the ranking carries no year
    signal at all.  0% = exactly backwards.

Four properties, each chosen against a specific failure of the obvious
alternatives:

1. **Ties are excluded from the denominator, not counted as misses.**
   Many chunks share a fiscal year — twenty near-identical editions of
   one per-agency page is the shape the S20 backfill creates, and two
   passages from the SAME edition are not mis-ordered relative to each
   other. A metric that charged for ties would have its ceiling set by
   how many distinct years a query happened to return, so the number
   would move when the corpus grew rather than when ranking changed.

2. **All pairs, not adjacent pairs.** One FY2005 document parked at
   rank 2 sits ahead of everything after it. Adjacent-pair counting
   charges that once; pair counting charges it once per document it
   jumped, which is what it actually costs the analyst.

3. **Undated chunks are skipped, never assumed.** `apply_recency_boost`
   deliberately penalises an undated chunk as if it were the oldest —
   that is a ranking POLICY ("we don't know how old this is" must not
   be rewarded as "this is current"). A measurement must not make the
   same assumption, because it would then be scoring its own guess.

4. **Higher is better and 50% is the reference point**, so one figure
   is readable without a statistics background. (Formally this is the
   probability of concordance — Kendall's tau-b rescaled from [-1, 1]
   to [0, 1] with tied pairs dropped. Spearman was the other candidate;
   it was rejected because "-0.82" is not a number a non-developer can
   act on, and its tie correction quietly changes what the denominator
   means.)

THE COMPANION FIGURE: `mean_fiscal_year_at_k`. Ordering alone is not
sufficient — the list 2010, 2009, 2008 scores a perfect 100% and is
useless to an analyst asking about an agency today. The mean fiscal year
of the top 5 says how recent the top of the list actually is. Read the
two together: the rate says "well ordered", the mean says "and recent".
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Sequence

# A `newest_first_rate` of exactly this is the no-information point: as
# many pairs came back newest-first as came back oldest-first. Printed
# beside every score so 50% is never read as "half right".
CHANCE_RATE = 0.5

# Fiscal-year stamp inside a chunk_id, e.g. `jlbc-baseline-fy2026-adc-0001`.
# Anchored on the literal `-fy` so a slug that merely contains four digits
# (a bill number, a page id) cannot be mistaken for an edition.
_FY_IN_CHUNK_ID = re.compile(r"-fy(\d{4})(?:-|$)")

# How deep "the top of the list" goes for the companion figure. 5 because
# that is what fits on a screen without scrolling — the criterion is about
# what the analyst SEES first.
TOP_OF_LIST_K = 5


def _get(chunk: Any, key: str) -> Any:
    """Read a field off either a RetrievedChunk dataclass or a plain dict.

    Both shapes reach this module: retrieval returns dataclasses, and
    `run_eval` normalises them to dicts before scoring. Supporting one
    would mean the metric only ever ran on one of the two paths.
    """
    if isinstance(chunk, dict):
        return chunk.get(key)
    return getattr(chunk, key, None)


def fiscal_year_of(chunk: Any) -> int | None:
    """The document fiscal year for one retrieved chunk, or None.

    Metadata first, chunk_id second. The fallback is not decorative: a
    small number of ingested chunks carry a null `fiscal_year` while
    their chunk_id still names the edition, and dropping those rows
    would understate how much of a result list is actually dated.
    """
    year = _get(chunk, "fiscal_year")
    if isinstance(year, int):
        return year

    chunk_id = _get(chunk, "chunk_id")
    if isinstance(chunk_id, str):
        match = _FY_IN_CHUNK_ID.search(chunk_id)
        if match:
            return int(match.group(1))
    return None


def fiscal_years_of(chunks: Iterable[Any]) -> list[int | None]:
    """Fiscal years in RANK ORDER — position in this list is the rank."""
    return [fiscal_year_of(c) for c in chunks]


def newest_first_rate(years: Sequence[int | None]) -> float | None:
    """Fraction of comparable result pairs that came back newest-first.

    None when nothing is comparable: fewer than two dated results, or
    every dated result sharing one year. That is "no evidence", and it
    is deliberately NOT 1.0 — a query that returned twenty copies of a
    single edition would otherwise inflate the average as though it had
    ordered them well.

    See the module docstring for why ties are dropped and why every
    pair is counted rather than only adjacent ones.
    """
    dated = [y for y in years if y is not None]

    concordant = 0
    discordant = 0
    for i in range(len(dated)):
        for j in range(i + 1, len(dated)):
            if dated[i] > dated[j]:
                concordant += 1
            elif dated[i] < dated[j]:
                discordant += 1
            # equal -> tied, contributes to neither side

    comparable = concordant + discordant
    if comparable == 0:
        return None
    return concordant / comparable


def mean_fiscal_year_at_k(
    years: Sequence[int | None], k: int = TOP_OF_LIST_K
) -> float | None:
    """Average fiscal year of the first `k` results. None if none dated.

    Higher is better, same as the rate. This is the figure that catches
    a perfectly-ordered list of uniformly ancient documents.
    """
    dated = [y for y in years[:k] if y is not None]
    if not dated:
        return None
    return statistics.fmean(dated)


@dataclass(frozen=True)
class OrderReport:
    """One query's chronological-order measurement.

    `fiscal_years` is kept alongside the scores on purpose. Destin's own
    baseline was written as a list of years in rank order, and a bare
    percentage is not something a non-developer can sanity-check — the
    year list is what makes the number auditable by eye.
    """

    query_id: str
    query: str
    fiscal_years: list[int | None] = field(default_factory=list)
    newest_first_rate: float | None = None
    mean_fiscal_year_at_5: float | None = None


def order_report(query_id: str, query: str, chunks: Iterable[Any]) -> OrderReport:
    """Measure one query's result list."""
    years = fiscal_years_of(chunks)
    return OrderReport(
        query_id=query_id,
        query=query,
        fiscal_years=years,
        newest_first_rate=newest_first_rate(years),
        mean_fiscal_year_at_5=mean_fiscal_year_at_k(years),
    )


def mean_rate(reports: Iterable[OrderReport]) -> float | None:
    """Average `newest_first_rate` across queries, ignoring undefined ones.

    Unweighted per QUERY, not pooled over all pairs: pooling would let a
    query that happened to return many distinct editions dominate the
    figure, and every query in the set represents one analyst asking one
    question.
    """
    rates = [r.newest_first_rate for r in reports if r.newest_first_rate is not None]
    return statistics.fmean(rates) if rates else None


def mean_vintage(reports: Iterable[OrderReport]) -> float | None:
    """Average `mean_fiscal_year_at_5` across queries, ignoring undefined."""
    vintages = [
        r.mean_fiscal_year_at_5 for r in reports if r.mean_fiscal_year_at_5 is not None
    ]
    return statistics.fmean(vintages) if vintages else None


def interpret_rate(rate: float | None) -> str:
    """Plain-English gloss for one rate. Read aloud to a non-developer."""
    if rate is None:
        return "not measurable (no two results with different years)"
    if rate >= 0.90:
        return "reads as newest-first"
    if rate >= 0.75:
        return "mostly newest-first, with visible exceptions"
    if rate > 0.60:
        return "leans newest-first but reads as mixed"
    if rate >= 0.40:
        return "no year ordering — this is what chance looks like"
    return "leans OLDEST-first"
