"""Post-rerank recency bonus for the budget corpus (spec S21, layer 3).

The problem this exists for: the S20 backfill puts ~20 structurally
near-identical editions of every per-agency page into the corpus. Asked
"what is the AHCCCS provider rate increase" with no year, a reranker
that scores on text similarity alone has no reason to prefer FY 2027's
page over FY 2009's — they read almost the same. Without a tiebreaker,
the newest edition is buried by fifteen older copies of itself.

Three deliberate constraints, all from S21:

1. **Soft, not a filter.** Every year stays visible and discoverable.
   Destin chose a bonus over default-filtering on 2026-07-31.
2. **Budget corpus only.** Fiscal-note triage deliberately seeks similar
   notes regardless of age — "have we written a note like this before?"
   is a question about the whole back catalogue.
3. **Never when a year filter is active.** If the analyst named a year,
   layer 1 already narrowed the set and a recency preference inside that
   set would fight the thing they asked for.

Ships OFF. RECENCY_BOOST_PER_YEAR is 0.0 until
`eval/calibrate_recency.py` recommends a weight against a backfilled
corpus (plan Task 6). Merging the machinery ahead of the backfill is the
point: the weight is one calibrated number, not a code change.

KNOWN INTERACTION, do not rediscover: boosted scores become
`RetrievalResult.top_score`, and `top_score` is what the refusal
threshold is compared against. Raising the weight shifts that
distribution downward, so `harness.constants.REFUSAL_THRESHOLD` must be
recalibrated in the same change.
"""
from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from typing import Iterator, Sequence

from retrieval.types import RetrievedChunk

# Score subtracted per fiscal year OLDER than the newest edition in the
# result set, measured on the same raw cross-encoder logit scale as the
# reranker's own output (roughly -10..10). 0.0 = disabled.
#
# It is a penalty on age, not a bonus on newness: the newest chunk gets
# exactly 0 and everything else moves down. Nothing is ever scored above
# what the reranker gave it — which is also why `top_score` can only
# fall when this is switched on, and why REFUSAL_THRESHOLD has to be
# recalibrated at the same time.
#
# WHY 0.0 until calibrated: picking a weight requires a corpus containing
# the old editions it is meant to demote, and that corpus does not exist
# until the S20 backfill runs. A guessed weight would either do nothing
# or quietly outrank relevance. See eval/calibrate_recency.py.
RECENCY_BOOST_PER_YEAR = 0.0


@contextmanager
def recency_weight(weight: float) -> Iterator[None]:
    """Temporarily override the module-level weight.

    Exists for `eval/calibrate_recency.py`, which sweeps weights by
    driving the real `retrieve()` — it has no other seam to inject
    through, and a bare global assignment would leak the last swept
    weight into whatever ran next in the same process.
    """
    global RECENCY_BOOST_PER_YEAR
    previous = RECENCY_BOOST_PER_YEAR
    RECENCY_BOOST_PER_YEAR = weight
    try:
        yield
    finally:
        RECENCY_BOOST_PER_YEAR = previous


def anchor_fiscal_year(chunks: Sequence[RetrievedChunk]) -> int | None:
    """The newest fiscal year in this result set, or None if none is dated.

    Corpus-relative on purpose, NOT the wall-clock year: the corpus's
    newest edition is routinely a year or two ahead of (or behind) the
    calendar, and anchoring on today's date would apply a blanket
    penalty to every chunk in the set — which changes nothing about the
    ordering but does move `top_score`, and `top_score` is the refusal
    signal.
    """
    dated = [c.fiscal_year for c in chunks if c.fiscal_year is not None]
    return max(dated) if dated else None


def apply_recency_boost(
    chunks: Sequence[RetrievedChunk],
    *,
    anchor_fy: int | None,
    weight: float | None = None,
) -> list[RetrievedChunk]:
    """Apply the per-year recency adjustment to each score and re-sort.

    Mechanically a PENALTY on age, not a bonus on newness: the term is
    `weight * (chunk.fiscal_year - anchor_fy)` — zero at the
    anchor and increasingly negative going back, so nothing is ever
    inflated above what the reranker actually scored. Chunks with no
    fiscal_year take the same penalty as the OLDEST dated chunk in the
    set: "we don't know how old this is" must not be rewarded as "this
    is current".

    `weight` defaults to the module-level RECENCY_BOOST_PER_YEAR, read at
    CALL time so `recency_weight()` works.

    At weight 0.0 (the shipped default) this returns the input order and
    the input scores untouched — it does not even re-sort, because
    re-sorting would reshuffle equal-scored chunks through the chunk_id
    tiebreak and that is not a no-op. Same when nothing in the set is
    dated: there is no meaningful ordering to impose.
    """
    if weight is None:
        weight = RECENCY_BOOST_PER_YEAR

    if not chunks or weight == 0.0 or anchor_fy is None:
        return list(chunks)

    dated = [c.fiscal_year for c in chunks if c.fiscal_year is not None]
    oldest = min(dated) if dated else anchor_fy

    boosted = [
        replace(
            chunk,
            score=chunk.score
            + weight * ((chunk.fiscal_year if chunk.fiscal_year is not None else oldest) - anchor_fy),
        )
        for chunk in chunks
    ]
    # chunk_id tiebreak so a re-run of the same query returns the same
    # order — without it, equal-scored chunks would depend on the fused
    # pool's incidental ordering.
    boosted.sort(key=lambda c: (-c.score, c.chunk_id))
    return boosted
