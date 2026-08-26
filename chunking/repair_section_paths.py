"""Repair `section_path` on table chunks already in the corpus (spec §3).

**A surgical rewrite, NOT a re-ingest, and that is not a preference.**
`identity/merge_agencies.py` merged nine duplicate agency ids out of the
corpus on 2026-08-16 by rewriting rows; `samples/entity-catalog.yaml` still
contains all nine and `chunking/entity_stamper.py` still resolves to them
(verified live 2026-08-26: `Child Safety, Department of` -> `agency:cs`,
`Water Infrastructure Finance Authority` -> `agency:wif`). Re-chunking a
document therefore re-derives the split ids and silently undoes part of that
repair. This pass rewrites four columns and re-derives nothing.

Written: `section_path`, `text`, `token_count`, `vector`.
Untouched: everything else, `agency_canonical_ids` and `fund_mentions` in
particular (spec G-T3 verifies it).

The write shape is `identity/relabel.py`'s and `funds/unstamp.py`'s, and the
traps their docstrings name apply here unchanged -- `upsert_chunks` is two
LanceDB commits, a matching row count proves nothing, and re-added rows are
invisible to BM25 until `build_fts_index` runs.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from chunking.builders._tokens import count_tokens
from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.odl_reader import ODLReader
from ingest.extract_dirs import resolve_extract_dir

# Planning reads these columns only. The `vector` column is 768 float32s on
# every one of 83,016 rows -- projecting it for a scan that only needs to
# decide WHICH rows change would pull ~255 MB off the share for nothing. The
# apply path re-scans a changed document with every column.
PLAN_COLUMNS = ["chunk_id", "doc_id", "text", "section_path", "is_table"]

DEFAULT_BATCH_SIZE = 2000

# G-T3: how many rows this pass was NOT supposed to touch get re-read after
# the write and compared to their pre-write values (identity/relabel.py's
# `_UNCHANGED_SAMPLE_SIZE`; spec G-T3 says 200 per table).
UNCHANGED_SAMPLE_SIZE = 200


class ChunkStoreLike(Protocol):
    def scan(self, name: str, columns: list[str], *, where: str | None = ...,
             limit: int | None = ...) -> list[dict[str, Any]]: ...
    def upsert_chunks(self, name: str, rows: Iterable[dict[str, Any]]) -> None: ...
    def build_fts_index(self, name: str) -> None: ...
    def optimize(self, name: str, *, retention: Any = ...) -> None: ...


class EmbedderLike(Protocol):
    def embed_batch(self, texts: list[str], *, input_type: str = ...) -> list[list[float]]: ...


@dataclass(frozen=True)
class RowChange:
    chunk_id: str
    doc_id: str
    old_path: list[str]
    new_path: list[str]
    old_text: str
    new_text: str


@dataclass
class RepairResult:
    changed: int = 0
    scanned: int = 0
    documents_planned: int = 0
    documents_skipped: dict[str, str] = field(default_factory=dict)
    # doc_id -> {"tables", "changed", "relabelled", "to_blank"}: the per-
    # document old-vs-new the spec's predictions are stated in.
    per_document: dict[str, dict[str, int]] = field(default_factory=dict)
    reversal: list[dict[str, Any]] = field(default_factory=list)


def _chunk_index(row: Mapping[str, Any]) -> int:
    """The positional index a chunk_id encodes (`{doc_id}-{idx:04d}`)."""
    return int(str(row["chunk_id"]).rsplit("-", 1)[1])


def _read_sidecar(root: Path) -> dict[str, Any]:
    """`documents.json`, or {} when the data dir has none (a test's tmp root).
    Read ONCE per run -- 7,574 entries is nothing; re-reading it per
    document across the share would not be."""
    try:
        raw = json.loads((root / "documents.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _default_progress(message: str) -> None:
    print(message, flush=True)


def _reversal_stamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")


def _body(text: str, section_path: list[str]) -> str:
    """Everything after the heading line.

    `table_chunk._build_text` writes the joined section path as line 0 ONLY
    when the path is non-empty, so a chunk stored with an empty path has no
    heading line to strip.
    """
    if not section_path:
        return text
    head, sep, rest = text.partition("\n")
    return rest if sep else ""


def _compose(body: str, section_path: list[str]) -> str:
    """Inverse of `_body`, and it must match `_build_text` exactly.

    An empty path emits NO heading line -- not an empty one. G-T6 asserts
    this pass's output is byte-identical to a real `chunk_doc` run, and a
    stray leading newline is the way that fails.
    """
    return f"{' > '.join(section_path)}\n{body}" if section_path else body


def plan_document(
    doc_id: str, rows: list[Mapping[str, Any]], root: Path, *, method: str | None = None
) -> tuple[list[RowChange], str | None]:
    """Which of this document's table rows change, or why it cannot be planned.

    The mapping from stored chunk to extracted table is positional:
    `chunk_doc` emits table chunks FIRST, in `doc.tables` order, so table
    *n* is `{doc_id}-{n:04d}`. That is a hypothesis about what was ingested,
    not a fact about what is on disk now -- so it is GATED, not trusted
    (spec §3.2): the table count must match, and every line of the stored
    text below line 0 must match the rebuilt table's, or the whole document
    is skipped and named.

    `method` is the sidecar's `extraction.method` for this document (None for
    everything ingested before Plan B) -- it picks WHICH reading on disk is
    the one the corpus holds. See `ingest/extract_dirs.py` for why that must
    never be guessed from folder names.
    """
    found = resolve_extract_dir(doc_id, root, method=method)
    if found is None:
        return [], "no cached extractor output"
    directory, extractor = found
    reader = ODLReader() if "opendataloader" in extractor.lower() else MinerUReader()
    try:
        doc = reader.read(directory)
    except (OSError, ValueError) as exc:
        return [], f"extractor output unreadable: {exc}"

    try:
        table_rows = sorted((r for r in rows if r.get("is_table")), key=_chunk_index)
    except (IndexError, ValueError):
        # A chunk_id lacking a numeric `-NNNN` suffix must not abort the
        # whole corpus-wide run -- the document is skipped and NAMED, per
        # this module's own rule (see the docstring above). Find the
        # offending row by re-trying `_chunk_index` one row at a time,
        # rather than teaching `_chunk_index` itself to return a sentinel
        # that would silently mis-sort.
        bad_id: Any = "?"
        for row in rows:
            if not row.get("is_table"):
                continue
            try:
                _chunk_index(row)
            except (IndexError, ValueError):
                bad_id = row["chunk_id"]
                break
        return [], f"malformed chunk_id: {bad_id!r}"
    if len(table_rows) != len(doc.tables):
        return [], (
            f"table count mismatch: corpus has {len(table_rows)}, "
            f"extractor output has {len(doc.tables)}"
        )

    changes: list[RowChange] = []
    for row, table in zip(table_rows, doc.tables):
        old_path = list(row.get("section_path") or [])
        new_path = doc.owner_path(table)
        stored_body = _body(str(row["text"]), old_path)
        rebuilt_body = _body(_build_text(table, new_path), new_path)
        if stored_body != rebuilt_body:
            return [], (
                f"body mismatch on {row['chunk_id']}: the extractor output on "
                "disk no longer matches what was ingested"
            )
        if old_path == new_path:
            continue
        changes.append(
            RowChange(
                chunk_id=str(row["chunk_id"]),
                doc_id=doc_id,
                old_path=old_path,
                new_path=new_path,
                old_text=str(row["text"]),
                new_text=_compose(stored_body, new_path),
            )
        )
    return changes, None


def _plan_corpus(
    store: ChunkStoreLike,
    root: Path,
    table: str,
    progress: Callable[[str], None],
    only: set[str] | None = None,
) -> tuple[list[RowChange], RepairResult, dict[str, Mapping[str, Any]]]:
    """Plan every document; also return the pre-write rows by chunk_id, which
    the apply path's untouched-row sample (G-T3) compares against."""
    rows = store.scan(table, PLAN_COLUMNS)
    before_by_id = {str(r["chunk_id"]): r for r in rows}
    by_doc: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_doc.setdefault(str(row["doc_id"]), []).append(row)
    if only is not None:
        by_doc = {d: r for d, r in by_doc.items() if d in only}
    progress(f"scanned {len(rows)} rows across {len(by_doc)} documents")

    sidecar = _read_sidecar(root)
    result = RepairResult(scanned=len(rows))
    changes: list[RowChange] = []
    for index, (doc_id, doc_rows) in enumerate(sorted(by_doc.items()), start=1):
        entry = sidecar.get(doc_id) or {}
        if entry.get("source_format") == "docx":
            # A DOCX bill is one chunk per Section with no Table blocks and no
            # page-N.json output; counting it as "no cached extractor output"
            # would inflate that figure and hide a real gap behind a known one.
            result.documents_skipped[doc_id] = (
                "docx document: section chunks, no tables, nothing to repair"
            )
            continue
        method = (entry.get("extraction") or {}).get("method")
        doc_changes, skipped = plan_document(doc_id, doc_rows, root, method=method)
        if skipped is not None:
            result.documents_skipped[doc_id] = skipped
            continue
        result.documents_planned += 1
        changes.extend(doc_changes)
        result.per_document[doc_id] = {
            "tables": sum(1 for r in doc_rows if r.get("is_table")),
            "changed": len(doc_changes),
            "relabelled": sum(1 for c in doc_changes if c.new_path),
            "to_blank": sum(1 for c in doc_changes if not c.new_path),
        }
        if index % 500 == 0:
            progress(f"planned {index}/{len(by_doc)} documents, {len(changes)} rows so far")
    result.changed = len(changes)
    result.reversal = [
        {
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "before": {"section_path": c.old_path, "text": c.old_text},
            "after": {"section_path": c.new_path, "text": c.new_text},
        }
        for c in changes
    ]
    return changes, result, before_by_id


_ALL_COLUMNS_CACHE: list[str] | None = None


def _all_columns() -> list[str]:
    """Every column, read from the schema rather than typed out -- a
    hand-maintained list silently drops a column added later, and a dropped
    column is written as null on every row this pass touches."""
    global _ALL_COLUMNS_CACHE
    if _ALL_COLUMNS_CACHE is None:
        from store.schema import chunk_schema
        _ALL_COLUMNS_CACHE = [f.name for f in chunk_schema(dim=1)]
    return _ALL_COLUMNS_CACHE


def _norm(value: Any) -> Any:
    """Lance hands list columns back as lists or arrays depending on the
    path; compare by value, not by container type."""
    return list(value) if isinstance(value, (list, tuple)) or hasattr(value, "tolist") else value


def _in_list(chunk_ids: Iterable[str]) -> str:
    from store.chunk_store import sql_str
    return "chunk_id IN (" + ", ".join(sql_str(c) for c in chunk_ids) + ")"


def _write_changed_rows(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    embedder: EmbedderLike,
    batch_size: int,
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Fetch the changed rows in full, rewrite four columns, embed, write.

    Fetched by chunk_id list per batch -- ~5 scans for ~10,200 rows -- not
    one `doc_id = ...` scan per document, which would be ~4,500 filtered
    scans over the share for the same rows.

    Batched because `upsert_chunks` deletes the batch's chunk_ids and then
    adds the replacements as two separate LanceDB commits: batching bounds a
    crash landing between them to one batch instead of the whole corpus.

    Compare-and-swap per row: the plan was computed BEFORE the lock, so
    each row's current `text` must still be the `old_text` the plan was
    built on. A document re-ingested in between keeps its chunk_ids and
    changes its text; without this check the planned line-0 edit would be
    written over a fresh ingest.
    """
    by_id = {c.chunk_id: c for c in changes}
    ordered = sorted(by_id)
    written: list[dict[str, Any]] = []
    total_batches = math.ceil(len(ordered) / batch_size) if ordered else 0
    for batch_num, start in enumerate(range(0, len(ordered), batch_size), start=1):
        ids = ordered[start:start + batch_size]
        rows = store.scan(table, _all_columns(), where=_in_list(ids))
        pending: list[dict[str, Any]] = []
        for row in rows:
            change = by_id.get(str(row.get("chunk_id")))
            if change is None:
                continue
            if str(row.get("text")) != change.old_text:
                raise RuntimeError(
                    f"{change.chunk_id}: its text is no longer what the plan was built "
                    "on -- the corpus moved under the plan (a re-ingest between planning "
                    "and writing). Nothing from this batch on is written; re-run the dry run"
                )
            new_row = dict(row)
            new_row["section_path"] = list(change.new_path)
            new_row["text"] = change.new_text
            new_row["token_count"] = count_tokens(change.new_text)
            pending.append(new_row)
        if len(pending) != len(ids):
            raise RuntimeError(
                f"batch {batch_num}: asked for {len(ids)} rows, the store returned "
                f"{len(pending)} -- rows vanished under the plan; re-run the dry run"
            )
        # input_type="document" is the embedder's default, but it is stated
        # here because it is not a formality (ingest/worker.py::_embed): the
        # model is asymmetric, and a passage embedded with the QUERY
        # instruction quietly degrades every future search against it.
        vectors = embedder.embed_batch([r["text"] for r in pending], input_type="document")
        for row, vector in zip(pending, vectors):
            row["vector"] = vector
        store.upsert_chunks(table, pending)
        written.extend(pending)
        progress(f"wrote batch {batch_num}/{total_batches} ({len(written)}/{len(changes)} rows)")
    return written


def _verify_nothing_was_lost(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    before_by_id: Mapping[str, Mapping[str, Any]],
    progress: Callable[[str], None],
) -> None:
    """Re-read every changed row and confirm exactly the four intended
    columns moved; then re-read a bounded sample of rows this pass was NEVER
    supposed to touch and confirm they still read as they did before the
    write. A matching ROW COUNT proves nothing -- `upsert_chunks` deletes
    then adds, so a lost column and a lost value both leave the count
    identical (`identity/relabel.py`'s trap 3). The untouched sample is the
    half of spec G-T3 that catches a delete landing on the wrong ids."""
    expected = {c.chunk_id: c for c in changes}
    seen = 0
    ordered = sorted(expected)
    for start in range(0, len(ordered), DEFAULT_BATCH_SIZE):
        ids = ordered[start:start + DEFAULT_BATCH_SIZE]
        for row in store.scan(table, _all_columns(), where=_in_list(ids)):
            change = expected.get(str(row.get("chunk_id")))
            if change is None:
                continue
            seen += 1
            if list(row.get("section_path") or []) != change.new_path:
                raise RuntimeError(f"{change.chunk_id}: section_path did not land")
            if str(row.get("text")) != change.new_text:
                raise RuntimeError(f"{change.chunk_id}: text did not land")
            if not row.get("vector"):
                raise RuntimeError(f"{change.chunk_id}: vector is empty after the write")
    if seen != len(expected):
        raise RuntimeError(f"verified {seen} rows, expected {len(expected)}")

    # The first UNCHANGED_SAMPLE_SIZE untouched ids in sort order -- in
    # practice ~200 rows of ONE document, the shape identity/relabel.py uses.
    # This is an in-process smoke check that the delete landed on the right
    # ids, not a spread; the corpus-wide comparison of every untouched column
    # is Task 7 Step 4 (on the copy) and Task 8 Step 4 (live).
    untouched = sorted(set(before_by_id) - set(expected))[:UNCHANGED_SAMPLE_SIZE]
    after = {str(r["chunk_id"]): r for r in store.scan(table, PLAN_COLUMNS, where=_in_list(untouched))} if untouched else {}
    for chunk_id in untouched:
        before, now = before_by_id[chunk_id], after.get(chunk_id)
        if now is None:
            raise RuntimeError(f"{chunk_id}: was never supposed to change and is GONE after the write")
        for col in ("text", "section_path", "is_table", "doc_id"):
            if _norm(now.get(col)) != _norm(before.get(col)):
                raise RuntimeError(
                    f"{chunk_id}: was never supposed to change but its {col!r} drifted; "
                    "restore from the snapshot this pass just took"
                )
    progress(f"verified {seen} changed rows in full, {len(untouched)} untouched rows sampled")


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


def repair_section_paths(
    *,
    store: ChunkStoreLike,
    embedder: EmbedderLike,
    root: Path,
    table: str = "budget_chunks",
    dry_run: bool = True,
    only: set[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock: Any | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> RepairResult:
    """Recompute every table chunk's `section_path`; write back what changed.

    `dry_run=True` (the default) takes no lock, snapshots nothing and writes
    nothing -- the same asymmetry `identity/relabel.py` documents, and what
    lets Task 6 be re-run by hand against the live corpus as often as anyone
    wants before an apply is approved.
    """
    progress = progress or _default_progress
    changes, result, before_by_id = _plan_corpus(store, root, table, progress, only)
    if dry_run:
        progress(f"DRY RUN: {result.changed} rows would change; nothing written")
        return result

    if lock is None:
        from ingest.lock import IngestLock
        lock = IngestLock()
    if snapshot_and_verify is None:
        from identity.relabel import _default_snapshot_and_verify
        snapshot_and_verify = _default_snapshot_and_verify
    if reversal_dir is None:
        from store.config import data_dir
        reversal_dir = data_dir()

    # BEFORE the lock and BEFORE the snapshot: a snapshot zips the whole
    # corpus under the lock and takes minutes; spending that on a no-op is
    # the kind of thing an operator learns to skip, and then skips it once
    # when it mattered.
    if not changes:
        progress("nothing to change; no lock, no snapshot, no write, no index rebuild")
        return result

    # `IngestLock.acquire()` runs its own heartbeat thread through the whole
    # 30-60 minute embed; nothing here beats it by hand.
    with lock:
        snapshot = snapshot_and_verify()
        progress(f"snapshot: {snapshot}")
        _write_changed_rows(store, table, changes, embedder, batch_size, progress)
        _verify_nothing_was_lost(store, table, changes, before_by_id, progress)
        # Re-added rows are invisible to BM25 until the index is rebuilt --
        # the ingest contract funds/unstamp.py had to learn the hard way.
        store.build_fts_index(table)
        store.optimize(table)
        progress("full-text index rebuilt and table optimized")

    stamp = _reversal_stamp()
    path = Path(reversal_dir) / f"section-path-reversal-{table}-{stamp}.json"
    _atomic_write_json(path, {"table": table, "snapshot": snapshot, "rows": result.reversal})
    progress(f"reversal record: {path}")
    return result
