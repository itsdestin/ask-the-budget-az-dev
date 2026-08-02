"""Assemble the annotation: the one artifact describing what every figure
in an answer is backed by.

The webapp renders it as chips; the eval judge renders it as inline
markers. One representation, two consumers, so what the analyst sees and
what the eval grades cannot drift apart.
"""
from __future__ import annotations

from typing import Any

from citation.authority import rank_hits
from citation.figures import Figure, extract_figures
from citation.matching import find_in_chunks
from citation.reconcile import reconcile


def _hit_dict(hit) -> dict[str, Any]:
    return {"chunk_id": hit.chunk_id, "source_text": hit.source_text,
            "start": hit.start, "end": hit.end}


def annotate_answer(
    answer: str,
    chunks: dict[str, str],
    meta: dict[str, dict[str, Any]],
    *,
    prefer_fiscal_year: int | None = None,
) -> dict[str, Any]:
    figures = extract_figures(answer)
    records: list[dict[str, Any]] = []
    linked_figs: list[Figure] = []
    linked_indices: list[int] = []

    # Pass 1 — link what can be located in a source.
    for i, fig in enumerate(figures, start=1):
        hits = find_in_chunks(fig, chunks)
        record: dict[str, Any] = {
            "text": fig.text, "start": fig.start, "end": fig.end,
            "index": i, "verdict": "unverified",
            "primary": None, "additional": [], "derived_from": [],
        }
        if hits:
            ranked = rank_hits(hits, meta, prefer_fiscal_year=prefer_fiscal_year)
            record["verdict"] = "linked"
            record["primary"] = _hit_dict(ranked[0])
            # Outranked sources are corroboration, shown on demand.
            record["additional"] = [_hit_dict(h) for h in ranked[1:]]
            linked_figs.append(fig)
            linked_indices.append(i)
        records.append(record)

    # Pass 2 — explain the leftovers as arithmetic over what was linked.
    # Runs second because a derivation can only reference linked figures.
    for record, fig in zip(records, figures):
        if record["verdict"] != "unverified":
            continue
        derivation = reconcile(fig, linked_figs)
        if derivation is not None:
            record["verdict"] = "derived"
            # linked_indices translates a position in `linked_figs` back to
            # the figure's reading-order index, which is what the analyst
            # sees on the page. Reporting the raw position would point the
            # chip at whichever figure happens to sit at that number.
            record["derived_from"] = [linked_indices[j] for j in derivation.inputs]

    return {"figures": records}
