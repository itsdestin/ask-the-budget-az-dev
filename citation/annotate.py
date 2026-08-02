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


def _hit_dict(hit, meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One source record, carrying enough to OPEN it.

    `chunk_id` alone is not enough: the PDF viewer needs `doc_id` and
    `page_start` or it renders "Couldn't open source PDF", which is what
    every figure chip did before this. The locator fields ride on the
    annotation so it is self-describing — the eval judge and any later
    audit read the same record the UI does.

    Chunk TEXT is deliberately absent. It would multiply the annotation by
    a chunk body per figure, and the highlighter searches `source_text`
    first anyway.
    """
    info = meta.get(hit.chunk_id) or {}
    return {"chunk_id": hit.chunk_id, "source_text": hit.source_text,
            "start": hit.start, "end": hit.end,
            "doc_id": info.get("doc_id"),
            "doc_type": info.get("doc_type"),
            "doc_title": info.get("doc_title"),
            "publisher": info.get("publisher"),
            "fiscal_year": info.get("fiscal_year"),
            "page_start": info.get("page_start"),
            "page_end": info.get("page_end"),
            "bbox": info.get("bbox")}


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
            record["primary"] = _hit_dict(ranked[0], meta)
            # Outranked sources are corroboration, shown on demand.
            record["additional"] = [_hit_dict(h, meta) for h in ranked[1:]]
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
