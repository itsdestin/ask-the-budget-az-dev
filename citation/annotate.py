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

# A tag binds leftward to the closest preceding figure, across the
# qualifier that figure carries.
#
# The first rule here allowed only whitespace, punctuation and a scale
# word, on the theory that a tag welded to the digits is the safe case.
# It is — and it is not how a model writes. Observed live: every one of
# "$12.49B (Mar 2020) [[c18]]", "$16.83B (Jun 2022) [[c3]]" and
# "$1,574.1 million in FY 2026 [[c22]]" was DISCARDED, because a model
# tags the end of the noun phrase, not the end of the number. Those
# figures then fell through to the untagged fallback and mostly went
# uncited — the model had named its source and the system threw it away.
#
# What actually protects against binding to the wrong figure is
# "closest PRECEDING figure", not the narrow charset: a tag after several
# figures takes the last one, which is the one it follows. So the gap
# rule only has to stop a bind reaching across a boundary the writer
# clearly intended — a sentence end, a line break, or a table cell wall.
_BIND_MAX_GAP = 80
# Anything that ends the thought the figure was part of.
_BIND_BOUNDARY_RE = re.compile(r"[.!?](?:\s|$)|[\n\r|]")


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
        if len(gap) <= _BIND_MAX_GAP and not _BIND_BOUNDARY_RE.search(gap):
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
    fallback_chunk_ids: list[str] | None = None,
) -> dict[str, Any]:
    """`chunks` may span the whole conversation; `fallback_chunk_ids`
    narrows the UNTAGGED search to a subset of it (in practice, this
    turn's retrieves).

    The two pools differ because the two paths carry different evidence.
    A tag names ONE chunk, so pool size cannot affect its verdict — a
    conversation-wide pool costs nothing and is what lets a model cite a
    passage it read two questions ago. The fallback has only the value
    itself, so every extra document is another chance to coincide.
    Measured over the 31-query baseline: merging 8 turns' pools took the
    untagged false-link rate on rounded billions from 0.28% to 2.50%,
    approaching the 3.7% of the authority-ranking design this replaced.
    """
    figures = extract_figures(answer)
    bound = _bind_tags(answer, figures, tags or [])
    aliases = alias_map or {}
    # None means "the whole pool" — the single-turn case, and every
    # caller that has no turn/conversation distinction to make.
    fallback_ids = (None if fallback_chunk_ids is None
                    else [c for c in fallback_chunk_ids if c in chunks])

    records: list[dict[str, Any]] = []
    linked_figs: list[Figure] = []
    linked_indices: list[int] = []

    for i, fig in enumerate(figures):
        # Resolve the model's claim against the chunks it has been sent.
        # An alias that is unknown, or points at a chunk that has fallen
        # out of context, is dropped — never redirected — so a stale tag
        # degrades to the fallback rather than verifying against the wrong
        # text (spec §5).
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
            # Narrowed to `fallback_ids`: with only the value as evidence,
            # every extra document in scope is another chance to coincide.
            pool_hits = find_in_chunks(fig, chunks, restrict_to=fallback_ids)
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
        # An AMBIGUOUS figure has no near miss: the value is sitting in the
        # pool exactly, in more than one document, so nearest_value returns
        # the figure itself at distance 0.0 and the chip would read "appears
        # in 2 different documents" beside "nearest source value ... differs
        # by 0.0%". Those are two different failures — not-found versus
        # too-many-found — and only the ambiguity sentence is true here.
        if record["ambiguity_count"]:
            continue
        # Near-miss (spec A6): scoped to the chunk the model NAMED when
        # there was a tag — "you said c3; c3's nearest value is X" is the
        # actionable sentence.
        nm = nearest_value(fig, chunks,
                           restrict_to=record["attested_chunk_ids"]
                           or fallback_ids)
        if nm is not None:
            record["near_miss"] = asdict(nm)

    _number_citations(records)
    return {"figures": records}


def _number_citations(records: list[dict[str, Any]]) -> None:
    """Give a display number to CITATIONS only, in reading order.

    An unverified figure is not a citation — nothing was sourced — so
    numbering it alongside real ones makes the sequence meaningless to a
    reader: a table came back numbered 13,14,…,20 struck through with a
    single live 21. Unverified figures get `index: None` and the UI draws
    no chip for them.

    Numbering happens LAST because a figure's verdict is not final until
    the derived pass has run; `derived_from` is remapped through the same
    table so "computed from [2] and [5]" keeps pointing at the chips the
    analyst can actually see.
    """
    renumber: dict[int, int] = {}
    nxt = 1
    for record in records:
        if record["verdict"] in ("linked", "derived"):
            renumber[record["index"]] = nxt
            record["index"] = nxt
            nxt += 1
        else:
            record["index"] = None
    for record in records:
        if record["derived_from"]:
            # Every input is a LINKED figure and therefore numbered, but
            # drop anything unmapped rather than emit a dangling pointer.
            record["derived_from"] = [renumber[i] for i in
                                      record["derived_from"] if i in renumber]
