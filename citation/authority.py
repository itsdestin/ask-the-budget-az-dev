"""Order candidate sources the way an analyst would.

The same figure legitimately appears in several editions of the same
material — a Baseline projection, the enacted Appropriations Report, then
the audited AFR. This encodes the document lifecycle the system prompt
already teaches, so the primary citation is the most trustworthy edition
and the rest are shown as corroboration.
"""
from __future__ import annotations

from typing import Any

from citation.matching import SourceHit

# Lower number = more authoritative. Audited actuals beat what was
# enacted, which beats what was projected, which beats what was proposed.
# Every doc_type the live corpus serves is listed here — pinned by
# test_every_doc_type_the_live_corpus_serves_has_an_authority, because an
# omission demotes a whole publisher silently rather than loudly.
_AUTHORITY = {
    "afr": 0,
    "approps-per-agency": 1,
    "approps-agency-pdf": 1,
    "budget-bill": 2,
    "baseline-per-agency": 3,
    "detailed-list-pdf": 4,
    "topic-pdf": 4,
    "s-pdf": 4,
    "bh-pdf": 4,
    "bd-pdf": 4,
    "governors-budget": 5,
}
# An unrecognised doc_type sorts last but is never discarded — a new
# publisher type should degrade to "least authoritative", not vanish.
_UNKNOWN = 99


def rank_hits(
    hits: list[SourceHit],
    meta: dict[str, dict[str, Any]],
    *,
    prefer_fiscal_year: int | None = None,
) -> list[SourceHit]:
    def key(h: SourceHit) -> tuple[int, int]:
        info = meta.get(h.chunk_id) or {}
        authority = _AUTHORITY.get(info.get("doc_type"), _UNKNOWN)
        # Fiscal year breaks ties WITHIN an authority level only; it must
        # never promote a proposal over an audited figure.
        fy_rank = 0
        if prefer_fiscal_year is not None:
            fy_rank = 0 if info.get("fiscal_year") == prefer_fiscal_year else 1
        return (authority, fy_rank)

    # sorted() is stable, so equal-authority hits keep their input order.
    return sorted(hits, key=key)
