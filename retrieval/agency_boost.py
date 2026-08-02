"""Post-rerank weak-match penalty for agency / doc-type inferences (spec Q4).

The problem this exists for: an analyst types "DEMA vehicle fleet" and the
query parser resolves "DEMA" to an agency — but not confidently enough to turn
it into a hard filter (the acronym is ambiguous, or the alias was drafted
rather than reviewed). A hard filter on a wrong guess sends the query
confidently to the wrong agency and shows a blank page; doing nothing at all
lets a Governor's-budget chunk that merely mentions the words out-rank the
actual DEMA page. So a WEAK match becomes a soft ranking preference instead:
chunks that don't match the inference are nudged down, and everything stays
visible and discoverable.

This module is a deliberate mirror of `retrieval/recency.py` — same penalty
shape, same chunk_id tiebreak on re-sort, same no-op-at-zero behaviour
(including NOT re-sorting at zero). If you change one, look at the other.

═══════════════════════════════════════════════════════════════════════════
THE SAFETY-CRITICAL PROPERTY — a PENALTY on non-matching chunks, NEVER a
bonus on matching ones.
═══════════════════════════════════════════════════════════════════════════

The adjusted scores become `RetrievalResult.top_score`, and `top_score` is
what `harness.constants.REFUSAL_THRESHOLD` is compared against. A bonus-shaped
adjustment would push `top_score` UP on exactly the queries the parser fired
on — which silently weakens refusal, i.e. the system starts answering
questions it should refuse (Invariant 3 failing with no visible symptom).

Shaped as a penalty, `top_score` can only ever FALL, and the only failure mode
is refusing slightly more often, which is visible and recoverable.

This coupling is not theoretical: it forced `RECENCY_BOOST_PER_YEAR` and
`REFUSAL_THRESHOLD` to be re-calibrated together on 2026-08-02 (0.85 / 1.46),
and the direction was counter-intuitive — LOWERING the recency weight RAISED
`top_score`, so the threshold had to go UP. Any change to the weight below
must re-run `eval/calibrate_refusal.py` in the same change.
"""
from __future__ import annotations

from dataclasses import replace
from typing import Sequence

from retrieval.types import RetrievedChunk

# Score subtracted from every chunk that does NOT match the weakly-inferred
# agency / doc type, measured on the same raw cross-encoder logit scale as the
# reranker's own output (roughly -10..10). Matching chunks are left exactly as
# the reranker scored them — nothing is ever inflated.
#
# CALIBRATED 2026-08-02 against the completed FY2005-2027 corpus, with an
# EXPLICIT weight grid (eval/sweep_match_penalty.py refuses to run without
# one — the derived grid in sweep_recency stepped 0.585 and is how
# RECENCY_BOOST_PER_YEAR shipped at 2.064 when 0.85 was free).
#
# Whole-set recall@5 over the 47-query eval set:
#
#     0.0   0.25   0.5    1.0    2.0    2.5    3.0    3.5
#   .8095  .8333 .8571  .8571  .8571  .8571  .8571  .8333
#                 └──────── plateau ────────┘   cliff ┘
#
# WHY 2.0 AND NOT 3.0, the largest weight that costs nothing — because that
# rule is not the right one here. It was right for recency, where every step
# up bought measurably better chronological ordering, so the largest safe
# weight was the best weight. This penalty buys NOTHING past 2.0 on either
# instrument: recall@5 is identical at 2.0/2.5/3.0, and navigational
# precision@5 (eval/navigational_check.py) is identical too — agency 0.867 /
# doc-type 0.867 at both 2.0 and 3.0. Given a tie on every measurement, the
# smaller weight wins: it intervenes less, and it sits 1.5 from the measured
# cliff instead of 0.5.
#
# REFUSAL_THRESHOLD did NOT move with it, and the reason is worth knowing
# rather than assuming it never will: `max_top_score` was 8.6779 at EVERY
# weight from 0.0 to 4.0, because a penalty only lowers NON-matching chunks
# and the best chunk on these queries always matched. That is a property of
# this query set, not a guarantee — a query whose top chunk does not match the
# inference will see top_score fall. Re-run eval/calibrate_refusal.py if this
# weight changes. tests/test_recency.py pins the pair.
MATCH_PENALTY = 2.0


def _matches(
    chunk: RetrievedChunk,
    agency_ids: Sequence[str],
    doc_types: Sequence[str],
) -> bool:
    """True when the chunk satisfies BOTH criteria. An empty criterion list
    means "nothing was inferred on this dimension", which every chunk
    satisfies.

    An UNSTAMPED chunk (no `agency_canonical_ids` at all) counts as
    non-matching. ~20% of the corpus carries no agency stamp, and treating
    "we don't know whose page this is" as "it matches" is what let a
    Governor's-budget chunk out-rank the real answer to an agency question.
    Falling back to "unknown = matches" would hand the benefit of the doubt to
    precisely the chunks that carry the least evidence.
    """
    agency_ok = not agency_ids or bool(set(chunk.agency_canonical_ids) & set(agency_ids))
    type_ok = not doc_types or chunk.doc_type in doc_types
    return agency_ok and type_ok


def apply_match_penalty(
    chunks: Sequence[RetrievedChunk],
    *,
    agency_ids: Sequence[str],
    doc_types: Sequence[str],
    weight: float | None = None,
) -> list[RetrievedChunk]:
    """Penalise chunks that miss the weakly-inferred agency / doc type, re-sort.

    Mechanically a PENALTY: a matching chunk keeps its reranker score exactly,
    a non-matching one loses `weight`. Nothing is ever scored above what the
    reranker gave it — see the module docstring for why that is load-bearing
    rather than stylistic.

    `weight` defaults to the module-level MATCH_PENALTY, read at CALL time so
    a future calibration sweep can override the global the way
    `recency_weight()` does for the recency boost.

    At weight 0.0 (the shipped default) this returns the input order and the
    input scores untouched — it does not even re-sort, because re-sorting
    would reshuffle equal-scored chunks through the chunk_id tiebreak and that
    is not a no-op. Same when nothing was inferred on either dimension: every
    chunk matches, so the penalty would be a uniform 0 that only churns the
    sort order while still moving nothing.
    """
    if weight is None:
        weight = MATCH_PENALTY

    if not chunks or weight == 0.0 or (not agency_ids and not doc_types):
        return list(chunks)

    penalised = [
        replace(chunk, score=chunk.score - (0.0 if _matches(chunk, agency_ids, doc_types) else weight))
        for chunk in chunks
    ]
    # chunk_id tiebreak so a re-run of the same query returns the same order —
    # without it, equal-scored chunks would depend on the fused pool's
    # incidental ordering. Same rule as retrieval/recency.py.
    penalised.sort(key=lambda c: (-c.score, c.chunk_id))
    return penalised
