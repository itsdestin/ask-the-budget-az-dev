"""How many table chunks OUTSIDE the operating-table scope have no
detectable year header, and how many of THOSE are actual continuations
(the predecessor chunk in the same document carries a header) rather than
a different, complete, single-year table that never had one? Spec §5 rule
5: the continuation-header borrow is built only if the true-continuation
population justifies a live store read on every search.

Read-only. Run (as a module, not a bare file path — see the WHY comment
on that in docs/superpowers/investigations/2026-09-01-headerless-tables-count.md
"Deviation from the sketch": `python <path>` puts scripts/ itself on
sys.path instead of the repo root, and this repo has no installed package
to fall back on, so a bare-path run cannot find chunking.table_text):

    JLBC_DATA_DIR=data/insight-data uv run python -m scripts.count_headerless_tables
"""
from __future__ import annotations

import re
from collections import Counter

from chunking.table_text import OPERATING_TABLE_DOC_TYPES, find_header, has_ladder_marker
from store.chunk_store import ChunkStore

# WHY this shape: ingest/lance_writer.py mints chunk_id as
# f"{doc_id}-{idx:04d}" — a doc_id followed by a hyphen and a zero-padded
# 4-digit index. Matching the LAST such group (not just any 4 digits)
# means a doc_id that itself happens to end in 4 digits still splits at
# the real boundary, since re.match anchors the whole string and the
# index group is always exactly 4 digits with nothing after it.
_CHUNK_ID_RE = re.compile(r"^(.*)-(\d{4})$")


def _parse_chunk_id(chunk_id: str) -> tuple[str, int] | None:
    m = _CHUNK_ID_RE.match(chunk_id)
    return (m.group(1), int(m.group(2))) if m else None


def _table_rows(text: str) -> list[list[str]]:
    return [line.split("\t") for line in (text or "").split("\n") if "\t" in line]


def _typical_row_width(table_rows: list[list[str]]) -> int | None:
    """The MOST COMMON cell-count among a chunk's tab-split rows.

    WHY this and not something fancier: it's a cheap stand-in for "how
    many columns does this table have," reusing only what find_header
    already computes (the tab split), with no new parsing. It is not
    exact — a table with a ragged row here or there (an empty trailing
    cell one row and not the next) can have more than one common width —
    but the review that asked for this (2026-09-01, after the first cut of
    this script under-counted true continuations) found it a reasonable
    net to hand-read against: of the chunks it flags, roughly 15-25% read
    as genuine continuations by eye. It is a FILTER for a human to read,
    not a verdict on its own.
    """
    if not table_rows:
        return None
    return Counter(len(r) for r in table_rows).most_common(1)[0][0]


def main() -> int:
    # WHY create=False: this is a read-only measurement over the live
    # corpus, run alongside a real office install on the same share.
    # ChunkStore(create=False) raises rather than materialising a
    # directory if the pointer is ever wrong (store/chunk_store.py's own
    # WHY comment on that flag) — a probe must never write.
    store = ChunkStore(create=False)
    rows = store.scan(
        "budget_chunks", ["chunk_id", "doc_type", "fiscal_year", "text"],
        where="is_table = true",
    )
    # Keyed lookup for the adjacency check below. Built from the SAME rows
    # (is_table = true only), so a predecessor found here is automatically
    # known to be a table chunk — no second store call needed.
    by_id = {r["chunk_id"]: r for r in rows}

    in_scope = out_scope = 0
    headerless_out: list[dict] = []
    for r in rows:
        text = r["text"] or ""
        table_rows = _table_rows(text)
        has_header = find_header(table_rows) is not None
        scoped = r["doc_type"] in OPERATING_TABLE_DOC_TYPES and has_ladder_marker(text)
        if scoped:
            in_scope += 1
        else:
            out_scope += 1
            if not has_header and table_rows:
                headerless_out.append(r)
    by_doc_type = Counter(r["doc_type"] for r in headerless_out)

    # (a) Adjacency: does the chunk immediately BEFORE this one in the same
    # document (index-1) exist and carry a detected header? This is the
    # direct test for "is this chunk a continuation" — a continuation's
    # header, if it has one at all, lives on the fragment before it.
    pred_headed: list[tuple[dict, dict]] = []
    pred_headed_by_type = Counter()
    for r in headerless_out:
        parsed = _parse_chunk_id(r["chunk_id"])
        if not parsed or parsed[1] == 0:
            continue
        doc_id, idx = parsed
        pred = by_id.get(f"{doc_id}-{idx - 1:04d}")
        if pred is None:
            continue
        if find_header(_table_rows(pred["text"] or "")) is not None:
            pred_headed.append((r, pred))
            pred_headed_by_type[r["doc_type"]] += 1

    # (b) Of those, does the CURRENT chunk's typical row width match the
    # WIDTH OF THE PREDECESSOR'S HEADER ROW ITSELF (its raw tab-split cell
    # count — not the count of labels in find_header's `labels` dict,
    # which only counts columns from the first year cell rightward and
    # can omit a leading blank cell that sits over the row-label column)?
    # A genuine continuation's data rows should be exactly as wide as the
    # header row they'd line up under; a same-width match on an unrelated
    # table is possible by coincidence, which is why this narrows the set
    # for hand-reading rather than being trusted on its own.
    width_matched: list[dict] = []
    width_matched_by_type = Counter()
    for r, pred in pred_headed:
        pred_rows = _table_rows(pred["text"] or "")
        pred_header = find_header(pred_rows)
        header_row_idx = pred_header.rows[0]
        pred_header_width = (
            len(pred_rows[header_row_idx]) if header_row_idx < len(pred_rows) else None
        )
        cur_width = _typical_row_width(_table_rows(r["text"] or ""))
        if cur_width is not None and cur_width == pred_header_width:
            width_matched.append(r)
            width_matched_by_type[r["doc_type"]] += 1

    print(f"table chunks: {len(rows)}  in-scope: {in_scope}  out-of-scope: {out_scope}")
    print(f"out-of-scope with tab rows and NO header: {len(headerless_out)}")
    for doc_type, n in by_doc_type.most_common():
        print(f"  {doc_type:24s} {n}")
    print()
    print(f"...of those, predecessor chunk (idx-1, same doc_id) is a table WITH a header: {len(pred_headed)}")
    for doc_type, n in pred_headed_by_type.most_common():
        print(f"  {doc_type:24s} {n}")
    print()
    print(f"...of those, current chunk's row width matches the predecessor's header-row width: {len(width_matched)}")
    for doc_type, n in width_matched_by_type.most_common():
        print(f"  {doc_type:24s} {n}")
    print()
    print("width-matched chunk_ids, for hand-reading:")
    for r in width_matched:
        print(f"  {r['chunk_id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
