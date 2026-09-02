"""How many table chunks OUTSIDE the operating-table scope have no
detectable year header? Spec §5 rule 5: the continuation-header borrow is
built only if this number justifies a live store read on every search.

Read-only. Run (as a module, not a bare file path — see the WHY comment
on that in docs/superpowers/investigations/2026-09-01-headerless-tables-count.md
"Deviation from the sketch": `python <path>` puts scripts/ itself on
sys.path instead of the repo root, and this repo has no installed package
to fall back on, so a bare-path run cannot find chunking.table_text):

    JLBC_DATA_DIR=data/insight-data uv run python -m scripts.count_headerless_tables
"""
from __future__ import annotations

from collections import Counter

from chunking.table_text import OPERATING_TABLE_DOC_TYPES, find_header, has_ladder_marker
from store.chunk_store import ChunkStore


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
    in_scope = out_scope = 0
    headerless_out = Counter()
    for r in rows:
        text = r["text"] or ""
        table_rows = [line.split("\t") for line in text.split("\n") if "\t" in line]
        has_header = find_header(table_rows) is not None
        scoped = r["doc_type"] in OPERATING_TABLE_DOC_TYPES and has_ladder_marker(text)
        if scoped:
            in_scope += 1
        else:
            out_scope += 1
            if not has_header and table_rows:
                headerless_out[r["doc_type"]] += 1
    print(f"table chunks: {len(rows)}  in-scope: {in_scope}  out-of-scope: {out_scope}")
    print(f"out-of-scope with tab rows and NO header: {sum(headerless_out.values())}")
    for doc_type, n in headerless_out.most_common():
        print(f"  {doc_type:24s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
