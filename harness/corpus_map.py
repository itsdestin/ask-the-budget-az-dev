"""Builds the corpus-inventory string the system prompt carries (spec N1).

WHY the model needs this: it cannot see the corpus. Before this map it
discovered "there is no FY2020 AFR" by searching, getting weak results, and
retrying — wasted rounds, or a confident answer from the wrong edition. The
Layer 2 post-backfill measurement is the evidence: `key_fact_rate` 0.66 with
74% of missed facts NEVER RETRIEVED in any round, which more rounds of the
same search could not have fixed. The map states coverage once, so the model
filters right on the first call and refuses honestly when coverage really
does end.

Family comes from source_url via `store.book_family`, NEVER from doc_id:
the doc_id prefix parses for all 647 book sections and is WRONG for 21 of
them (the `make_doc_id` collision class). A map built from doc_id would
claim editions that do not exist — and the guidance line below then
instructs the model to assert that falsehood, which is the harmful
direction.

Deliberately cheap to import (a json-reading `store.documents` plus the leaf
family rule): `session.py` builds this once per conversation, on the request
path.
"""
from __future__ import annotations

from typing import Any, Mapping

from ingest.section_types import SECTION_DOC_TYPES
from store.book_family import section_of

# Same two spellings `harness/prompt.py` accepts (wire name and LanceDB table
# name), for the same reason: callers hold one or the other depending on
# which layer they came from, and making them convert first is a trap.
_CORPUS_ALIASES = {
    "budget": "budget",
    "budget_chunks": "budget",
    "fiscal_notes": "fiscal_notes",
    "fiscal_note_chunks": "fiscal_notes",
}

_GUIDANCE = (
    "If this table shows no edition for a year or document type, tell the "
    "analyst the corpus does not hold it — do not search repeatedly for "
    "material that does not exist."
)

# Labels an analyst would recognise, for the doc_types that carry a whole
# publisher's output. Anything not listed here falls through to the raw
# `publisher — doc_type` form below, on purpose.
_PLAIN_LABELS = {
    "baseline-per-agency": "JLBC — Baseline (per-agency pages)",
    "approps-per-agency": "JLBC — Appropriations Report (per-agency pages)",
    "afr": "AGAO — Annual Financial Report",
    "governors-budget": "Governor — Executive Budget",
    "budget-bill": "Legislature — Budget bill",
}

_FISCAL_NOTE_DOC_TYPE = "fiscal-note"
_FISCAL_NOTE_LABEL = "Legislature — Fiscal notes"

# Beyond this many missing years, name the count instead of listing them: a
# 12-item "missing" list is longer than the row it annotates and stops being
# readable, which defeats the point of a table the model reads every turn.
_MAX_NAMED_GAPS = 4


def _cell(value: Any) -> str:
    """One markdown table cell.

    The pipe replacement is not defensive habit: the raw fallback label is
    built from corpus-supplied `publisher` / `doc_type` strings, so a pipe
    arriving there would split the row and silently shift every later column
    — the document count would then render as the year range.
    """
    return str(value).replace("|", "/")


def _label(doc: Mapping[str, Any]) -> str:
    doc_type = doc.get("doc_type") or "unknown"
    if doc_type in _PLAIN_LABELS:
        return _PLAIN_LABELS[doc_type]
    if doc_type in SECTION_DOC_TYPES:
        family = section_of(doc_type, doc.get("source_url"))
        if family:
            return f"JLBC — {family} (book sections)"
        # NOT dropped. A document missing from the map is worse than one
        # filed vaguely: the guidance line above would then have the model
        # deny material the corpus actually holds.
        return "JLBC — book sections (unclassified)"
    return f"{_cell(doc.get('publisher') or 'unknown')} — {_cell(doc_type)}"


def _year_phrase(years: list[Any]) -> str:
    """Coverage for one group, as a phrase the model can act on.

    Gaps are named because a gap is exactly what the model must not guess
    at — "FY2012–FY2027" with FY2013 silently absent is a promise the
    corpus cannot keep.
    """
    present = sorted({y for y in years if isinstance(y, int) and not isinstance(y, bool)})
    if not present:
        return "year unknown"
    if len(present) == 1:
        return f"FY{present[0]} only"
    lo, hi = present[0], present[-1]
    span = hi - lo + 1
    missing = sorted(set(range(lo, hi + 1)) - set(present))
    if not missing:
        return f"FY{lo}–FY{hi}"
    if len(missing) <= _MAX_NAMED_GAPS:
        return f"FY{lo}–FY{hi} (missing {', '.join(f'FY{y}' for y in missing)})"
    return f"FY{lo}–FY{hi} ({len(present)} of {span} years)"


def build_corpus_map(
    corpus: str, *, documents: Mapping[str, Mapping[str, Any]] | None = None
) -> str | None:
    """The inventory table for one corpus, or None when there is nothing to say.

    None (rather than an empty table) is the contract: the caller renders the
    prompt's fallback sentence instead, because a table with headings and no
    rows reads to the model as "this corpus is empty" — a statement the
    guidance line would then have it repeat to an analyst.

    `documents` is injected by tests and by any caller that already holds the
    sidecar; the default reads it through `store.documents`.
    """
    resolved = _CORPUS_ALIASES.get(corpus)
    if resolved is None:
        raise ValueError(
            f"Unknown corpus {corpus!r}. Valid names: {', '.join(sorted(_CORPUS_ALIASES))}."
        )
    if documents is None:
        # Imported here, not at module scope, so a test injecting documents
        # never touches the sidecar reader (or its process-wide cache).
        from store.documents import load_documents

        documents = load_documents()

    wanted_notes = resolved == "fiscal_notes"
    years_by_label: dict[str, list[Any]] = {}
    counts: dict[str, int] = {}
    for doc in documents.values():
        is_note = doc.get("doc_type") == _FISCAL_NOTE_DOC_TYPE
        if is_note != wanted_notes:
            continue
        label = _FISCAL_NOTE_LABEL if is_note else _label(doc)
        years_by_label.setdefault(label, []).append(doc.get("fiscal_year"))
        counts[label] = counts.get(label, 0) + 1
    if not years_by_label:
        return None

    lines = ["| Collection | Years in corpus | Docs |", "|---|---|---|"]
    # Sorted by label so the string is a pure function of the sidecar's
    # CONTENT, not its key order — the map is the S22 cacheable prefix, and
    # a reordering would be a silent ~10x cache miss for the whole office.
    for label in sorted(years_by_label):
        lines.append(
            f"| {label} | {_year_phrase(years_by_label[label])} | {counts[label]} |"
        )
    lines.append("")
    lines.append(_GUIDANCE)
    return "\n".join(lines)
