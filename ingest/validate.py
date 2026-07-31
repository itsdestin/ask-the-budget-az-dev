"""Post-ingest sanity checks on one freshly-written document.

The Postgres-era equivalent (`db/validate.py`) validated the whole corpus
after a batch load, from a terminal, with a human reading the table. Neither
of those holds now: ingest is one document at a time, triggered by a
colleague who will never open a terminal.

So this is per-document and **advisory**. A document that fails a check is
still `live` and still searchable — the findings ride along on the job
record so they're visible on the queue page. That's deliberate: an
80%-agency-stamped document is degraded, not wrong, and refusing to ingest
it would leave the analyst with nothing at all. Only things that make a
document unusable (no chunks, no text) are worth shouting about, and those
show up here as findings too rather than as a silent success.

The checks themselves are ported from `db/validate.py` and MANIFEST.md's
definition-of-done, restricted to the ones that are meaningful for a single
document. Dropped on purpose: FK-integrity checks (LanceDB has no agencies
or funds table to join against — the catalog IS the source, so a
non-catalog id can't be produced by the stamper) and corpus-wide row counts.
"""
from __future__ import annotations

from store.chunk_store import ChunkStore, sql_str

# Doc types that are ABOUT one agency, so nearly every chunk should carry a
# canonical id. The 0.90 floor is MANIFEST.md's definition of done; the Phase
# 1a slice closed at 91.3%.
PER_AGENCY_DOC_TYPES = frozenset({"baseline-per-agency", "approps-per-agency"})
AGENCY_STAMP_FLOOR = 0.90

# A chunk this small is almost always a stray page number or a header
# fragment the chunker failed to merge — it can match a query and then tell
# the reader nothing.
MIN_TOKENS = 3

_COLUMNS = [
    "chunk_id", "text", "page", "source_anchor", "bbox",
    "agency_canonical_ids", "token_count", "doc_type", "is_table",
]


def validate_doc(store: ChunkStore, table: str, doc_id: str) -> list[str]:
    """Return human-readable findings for one document. Empty means clean."""
    rows = store.scan(table, _COLUMNS, where=f"doc_id = {sql_str(doc_id)}")
    if not rows:
        return [
            "No passages were written for this document — it is not searchable. "
            "The source may be a scanned image with no extractable text."
        ]

    findings: list[str] = []
    total = len(rows)

    empty = sum(1 for r in rows if not (r.get("text") or "").strip())
    if empty:
        findings.append(f"{empty} of {total} passages have no text.")

    unlocatable = sum(
        1 for r in rows if r.get("page") is None and not r.get("source_anchor")
    )
    if unlocatable:
        findings.append(
            f"{unlocatable} of {total} passages can't be located in the source "
            "document, so citations to them won't open the right page."
        )

    # PDF chunks without a bbox still cite the right page; the viewer just
    # can't highlight. Worth reporting, not worth alarming about.
    no_bbox = sum(1 for r in rows if r.get("page") is not None and not r.get("bbox"))
    if no_bbox:
        findings.append(
            f"{no_bbox} of {total} passages have no position on the page, so "
            "citations will open the page without highlighting the text."
        )

    tiny = sum(1 for r in rows if (r.get("token_count") or 0) < MIN_TOKENS)
    if tiny:
        findings.append(
            f"{tiny} of {total} passages are only a few words long — usually "
            "page numbers or headers the splitter didn't merge."
        )

    doc_type = rows[0].get("doc_type") or ""
    if doc_type in PER_AGENCY_DOC_TYPES:
        stamped = sum(1 for r in rows if list(r.get("agency_canonical_ids") or []))
        rate = stamped / total
        if rate < AGENCY_STAMP_FLOOR:
            findings.append(
                f"Only {rate:.0%} of passages were matched to an agency "
                f"(expected at least {AGENCY_STAMP_FLOOR:.0%}). Filtering this "
                "document by agency will miss most of it."
            )

    return findings
