"""Assemble the annotation: what every figure in an answer is backed by.

The webapp renders it as chips; the eval judge renders it as inline
markers. One representation, two consumers, so what the analyst sees and
what the eval grades cannot drift apart.

Linking policy (spec A2/A3): a model tag is verified against the named
chunk only; an untagged figure links only when exactly ONE document in
the turn's pool contains the value. Nothing here ranks candidate
documents — the authority tie-break was the mechanism behind the
wrong-doc defect (memo §5.1) and is deleted, not demoted.
"""
from __future__ import annotations

import re
from dataclasses import asdict
from typing import Any

from citation.figures import Figure, extract_figures
from citation.markers import Tag
from citation.matching import find_in_chunks, nearest_value
from citation.reconcile import reconcile

# A tag binds leftward across at most a scale word and punctuation:
# "$8,287.7 million [[c3]]" binds; a tag a clause away does not — better
# an untagged figure (which still gets the fallback) than a tag bound to
# the wrong number.
_BIND_MAX_GAP = 24
_BIND_GAP_RE = re.compile(
    r"^\s*(?:million|billion|thousand|[MBK])?[\s.,;:)%*_—-]*$",
    re.IGNORECASE)


def _bind_tags(answer: str, figures: list[Figure],
               tags: list[Tag]) -> dict[int, list[str]]:
    """figure position -> the aliases the model attached to it."""
    bound: dict[int, list[str]] = {}
    for tag in tags:
        best: int | None = None
        for i, fig in enumerate(figures):
            if fig.end <= tag.at and (best is None
                                      or fig.end > figures[best].end):
                best = i
        if best is None:
            continue
        gap = answer[figures[best].end:tag.at]
        if len(gap) <= _BIND_MAX_GAP and _BIND_GAP_RE.match(gap):
            bound.setdefault(best, []).extend(tag.aliases)
    return bound


def _hit_dict(hit, meta: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """One source record, carrying enough to OPEN it (doc_id, pages, bbox
    — a chunk_id alone leaves the viewer on "Couldn't open source PDF").
    Chunk TEXT stays absent: it would ship a chunk body per figure."""
    info = meta.get(hit.chunk_id) or {}
    return {"chunk_id": hit.chunk_id, "source_text": hit.source_text,
            "start": hit.start, "end": hit.end,
            "doc_id": info.get("doc_id"), "doc_type": info.get("doc_type"),
            "doc_title": info.get("doc_title"),
            "publisher": info.get("publisher"),
            "fiscal_year": info.get("fiscal_year"),
            "page_start": info.get("page_start"),
            "page_end": info.get("page_end"), "bbox": info.get("bbox")}


def annotate_answer(
    answer: str,
    chunks: dict[str, str],
    meta: dict[str, dict[str, Any]],
    *,
    tags: list[Tag] | None = None,
    alias_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    figures = extract_figures(answer)
    bound = _bind_tags(answer, figures, tags or [])
    aliases = alias_map or {}

    records: list[dict[str, Any]] = []
    linked_figs: list[Figure] = []
    linked_indices: list[int] = []

    for i, fig in enumerate(figures):
        # Resolve the model's claim to in-turn chunks. An alias that is
        # unknown or points at a chunk not retrieved THIS turn is dropped
        # — never redirected — so a stale tag degrades to the fallback
        # instead of verifying against the wrong text (spec §5).
        attested = [aliases[a] for a in bound.get(i, [])
                    if a in aliases and aliases[a] in chunks]
        record: dict[str, Any] = {
            "text": fig.text, "start": fig.start, "end": fig.end,
            "index": i + 1, "verdict": "unverified",
            "primary": None, "additional": [], "derived_from": [],
            "attested_chunk_ids": attested, "link_basis": None,
            "ambiguity_count": None, "near_miss": None, "operation": None,
        }

        # Tag path: floor 2, because the tag is independent evidence and
        # a round "$1,000,000" (one written significant digit) must still
        # verify inside the ONE chunk the model named. The pool-wide
        # fallback below keeps the strict floor — there the value is the
        # only evidence.
        hits = (find_in_chunks(fig, chunks, restrict_to=attested,
                               min_significant_digits=2)
                if attested else [])
        if hits:
            record["verdict"] = "linked"
            record["link_basis"] = "tag"
        else:
            # Fallback — also runs when a tag failed to verify, because
            # the value may genuinely live in one other document (R2).
            pool_hits = find_in_chunks(fig, chunks)
            docs = {(meta.get(h.chunk_id) or {}).get("doc_id")
                    for h in pool_hits}
            if pool_hits and len(docs) == 1:
                hits = pool_hits
                record["verdict"] = "linked"
                record["link_basis"] = "unambiguous-fallback"
            elif len(docs) > 1:
                record["ambiguity_count"] = len(docs)

        if record["verdict"] == "linked":
            record["primary"] = _hit_dict(hits[0], meta)
            record["additional"] = [_hit_dict(h, meta) for h in hits[1:]]
            linked_figs.append(fig)
            linked_indices.append(i + 1)
        records.append(record)

    # Derived pass — after linking so a sourced figure can never be
    # misexplained as arithmetic (the §5.3 identity trap).
    for record, fig in zip(records, figures):
        if record["verdict"] != "unverified":
            continue
        derivation = reconcile(fig, linked_figs)
        if derivation is not None:
            record["verdict"] = "derived"
            record["operation"] = derivation.operation
            # linked_indices translates a position in `linked_figs` back
            # to the figure's reading-order index, which is what the
            # analyst sees on the page. Reporting the raw position would
            # point the chip at whichever figure sits at that number.
            record["derived_from"] = [linked_indices[j]
                                      for j in derivation.inputs]
            continue
        # Near-miss (spec A6): scoped to the chunk the model NAMED when
        # there was a tag — "you said c3; c3's nearest value is X" is the
        # actionable sentence.
        nm = nearest_value(fig, chunks,
                           restrict_to=record["attested_chunk_ids"] or None)
        if nm is not None:
            record["near_miss"] = asdict(nm)

    return {"figures": records}
