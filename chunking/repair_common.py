"""Helpers shared by the corpus-surgery repair passes (`chunking/repair_section_paths.py`
and `chunking/repair_tables.py`): one copy each, imported by both. Moved out of
`repair_section_paths.py` rather than duplicated -- both passes write JSON
reversal records, build the same `chunk_id IN (...)` predicate, need every
column's name to avoid silently nulling one they don't touch, and snapshot
the corpus the same way before writing. A second, drifted copy of any of
these would be the kind of thing that only shows up mid-write on the share.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Protocol


class ChunkStoreLike(Protocol):
    def scan(self, name: str, columns: list[str], *, where: str | None = ...,
             limit: int | None = ...) -> list[dict[str, Any]]: ...
    def upsert_chunks(self, name: str, rows: Iterable[dict[str, Any]]) -> None: ...
    def build_fts_index(self, name: str) -> None: ...
    def optimize(self, name: str, *, retention: Any = ...) -> None: ...


class EmbedderLike(Protocol):
    def embed_batch(self, texts: list[str], *, input_type: str = ...) -> list[list[float]]: ...


def reversal_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


_ALL_COLUMNS_CACHE: list[str] | None = None


def all_columns() -> list[str]:
    """Every column, read from the schema rather than typed out -- a
    hand-maintained list silently drops a column added later, and a dropped
    column is written as null on every row this pass touches."""
    global _ALL_COLUMNS_CACHE
    if _ALL_COLUMNS_CACHE is None:
        from store.schema import chunk_schema
        _ALL_COLUMNS_CACHE = [f.name for f in chunk_schema(dim=1)]
    return _ALL_COLUMNS_CACHE


def in_list(chunk_ids: Iterable[str]) -> str:
    """`chunk_id IN ('a', 'b', ...)`, every literal through `sql_str`.

    Never build this predicate by hand: LanceDB filters are SQL STRINGS with
    no parameter binding, so an id carrying an apostrophe would either break
    the parse or rewrite the predicate (`store/chunk_store.py::sql_str`).
    """
    from store.chunk_store import sql_str
    return "chunk_id IN (" + ", ".join(sql_str(c) for c in chunk_ids) + ")"


def atomic_write_json(path: Path, payload: Any) -> None:
    """tmp + replace, through the share's retry (`store/fs.py`).

    `Path.replace` is an unconditional POSIX rename. This record is written
    to the shared drive, where another PC's open handle turns a rename into a
    sharing violation and `replace_with_retry` -- the one implementation the
    job files, documents.json and the ingest lock all go through -- waits it
    out and cleans up the `.tmp` if it never clears. `ensure_ascii=False`
    keeps a section heading's real characters readable to whoever may have to
    replay this file by hand.
    """
    from store.fs import replace_with_retry

    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    replace_with_retry(tmp, path)


def default_snapshot_and_verify() -> str | None:
    """Wraps `identity.relabel._default_snapshot_and_verify` -- the S17
    snapshot-then-CRC-check that every corpus-surgery pass on this project
    uses as its default undo path (see that function's own docstring for
    why `zipfile.testzip()` and not just a returned name). Wrapped here
    rather than imported directly at each call site so `chunking.repair_tables`
    does not need to know that the canonical implementation still lives in
    `identity/relabel.py`.

    Imported lazily so importing this module never touches the real data dir.
    """
    from identity.relabel import _default_snapshot_and_verify
    return _default_snapshot_and_verify()
