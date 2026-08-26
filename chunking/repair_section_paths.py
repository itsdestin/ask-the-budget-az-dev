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

# What share of that sample may legitimately be gone between the plan scan and
# the under-lock baseline read. WHY a floor exists at all: `_untouched_baseline`
# DROPS rows it cannot re-read, so a read that comes back empty leaves an empty
# sample and the second half of G-T3 becomes a no-op that PASSES -- a silent
# loss of the only in-process check that a delete landed on the right ids.
# WHY a tenth: the sample is 200 rows read twice, minutes apart, under the
# ingest lock. One or two rows vanishing in that window is somebody's
# concurrent re-ingest and is exactly what the drop is for; more than 20 of 200
# is not that coincidence -- it is the read itself having stopped working (a
# predicate that no longer matches, a projection change, a store answering []).
# The line itself is `_missing_tolerance`, which puts a FLOOR of one row under
# the fraction -- see its docstring for why a bare tenth was wrong on a small
# sample.
UNCHANGED_SAMPLE_MISSING_LIMIT = 0.10


def _missing_tolerance(sample_size: int) -> float:
    """How many sampled rows may be gone before this pass refuses.

    WHY a floor of one and not a bare `UNCHANGED_SAMPLE_MISSING_LIMIT *
    sample_size`: on a sample of 1-9 rows a tenth is less than one, so ANY
    single row lost aborted the run -- refusing the exact benign case the
    drop exists for (a document this pass never touches, re-ingested during
    the tens of minutes of planning) purely because the sample was small.
    That shape is reachable on a `--only` run over a couple of documents and
    on every small test corpus.

    The live 200-row sample is unaffected: `max(1, 20.0)` is 20, so 20 of 200
    is still tolerated and 21 still refuses.
    """
    return max(1.0, UNCHANGED_SAMPLE_MISSING_LIMIT * sample_size)


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
    """`chunk_id IN ('a', 'b', ...)`, every literal through `sql_str`.

    Never build this predicate by hand: LanceDB filters are SQL STRINGS with
    no parameter binding, so an id carrying an apostrophe would either break
    the parse or rewrite the predicate (`store/chunk_store.py::sql_str`).
    """
    from store.chunk_store import sql_str
    return "chunk_id IN (" + ", ".join(sql_str(c) for c in chunk_ids) + ")"


@dataclass
class _WriteState:
    """What an operator needs told once ANY row has moved.

    Every failure raised after the first `upsert_chunks` is re-raised through
    `hint()`. A bare "text did not land" says nothing about the two questions
    the person reading it actually has -- is the corpus half-written, and is
    search consistent with what is now in it -- nor which of the two restore
    points to reach for. The sentence is composed AFTER the index rebuild in
    `repair_section_paths`'s `finally`, so `index_rebuilt` reports what really
    happened rather than what was true at the moment the error was raised.

    `rebuild_error` carries the exception the index rebuild itself raised, when
    it did. Without it the hint would say "was NOT rebuilt" and leave the
    operator with no idea WHY, on the one failure where the next step is to fix
    the share and re-run `build_fts_index` by hand rather than restore anything.

    WHY `batches_attempted` exists and `rows_written` cannot stand in for it:
    `rows_written` is assigned only AFTER `upsert_chunks` RETURNS, and that
    call is a delete commit followed by a SEPARATE add commit -- "CAUTION: the
    delete and the add are two separate commits, so this is NOT atomic -- an
    interruption between them leaves those chunk_ids deleted"
    (`store/chunk_store.py`, the comment above `tbl.delete`). So a batch whose
    add half fails has taken up to `batch_size` rows OUT of the corpus while
    `rows_written` is still 0. Reading that 0 as "nothing moved" produced two
    dangerous outputs: a hint telling the operator the corpus was unchanged and
    that both restore points could be DELETED, and a skipped index rebuild.
    `batches_attempted` is recorded BEFORE the call, so "unchanged" is claimed
    only when no write was ever started.

    `optimize_error` is kept apart from `rebuild_error` because the two mean
    opposite things to whoever reads them. `build_fts_index` is what makes
    re-added rows visible to BM25; `optimize` only prunes old table versions.
    Reporting a failed `optimize` as "the index was NOT rebuilt" (which one
    shared flag did) sends an operator hunting a search-correctness problem
    that does not exist, and towards a restore that would throw away a
    perfectly good write.

    `verified` records that `_verify_nothing_was_lost` RETURNED -- every
    written row re-read and compared column by column against what was sent.
    It is what `remedy()` reads to decide whether a restore is the right move
    at all: on a verified corpus, rolling back would discard a correct write
    plus every upload since, to fix an index or a version prune. It cannot be
    inferred from the counters, because a batch counter reaching its total
    says the write finished, not that anybody checked what landed.
    """

    snapshot: str | None
    reversal_path: Path
    rows_written: int = 0
    batches_written: int = 0
    batches_attempted: int = 0
    ids_in_flight: int = 0
    index_rebuilt: bool = False
    verified: bool = False
    rebuild_error: BaseException | None = None
    optimize_error: BaseException | None = None

    def _snapshot_phrase(self) -> str:
        """The snapshot named ONE way, empty-corpus fallback included.

        It was spelled three ways across the terminating messages -- `the
        snapshot at X`, `(no snapshot -- the corpus was empty)` and `(none --
        the corpus was empty)`. To an operator comparing two error messages
        from the same run those read as different artefacts, which is the last
        thing to be guessing at while deciding whether to restore.
        """
        if self.snapshot:
            return f"the snapshot at {self.snapshot}"
        return "no snapshot was taken (the corpus was empty when this pass started)"

    def _restore_offered(self) -> bool:
        """Is the message being composed going to point at a restore point?

        True only once a write has been ATTEMPTED and the rows have NOT been
        verified -- which is exactly the set of paths on which `remedy()` names
        a snapshot or the reversal record as the next step.
        """
        return bool(self.batches_attempted) and not self.verified

    def _index_phrase(self) -> str:
        if self.index_rebuilt:
            phrase = "WAS rebuilt over them"
            if self.optimize_error is not None:
                # NEVER "NOT rebuilt" on this path: the index really was
                # rebuilt, so keyword search sees every written row and there
                # is nothing to restore. All that failed is the pruning of old
                # table versions, which costs disk and nothing else.
                phrase += (
                    f"; optimize failed: {self.optimize_error} -- old versions were "
                    "not pruned, search is correct"
                )
                # WHY the "re-run optimize" clause is dropped whenever a
                # restore is being offered: the operator would be handed two
                # remedies in one breath -- put the corpus back, and also run a
                # maintenance command on it -- and beside a possible restore
                # the version prune is noise. Pruning old versions is only ever
                # the next step once the rows are known good, which is the one
                # case `_restore_offered()` is false.
                if not self._restore_offered():
                    phrase += "; re-run optimize by hand"
            return phrase
        phrase = "was NOT rebuilt"
        if self.rebuild_error is not None:
            phrase += f" (the rebuild was attempted and FAILED: {self.rebuild_error})"
        return phrase

    def state_sentence(self) -> str:
        """What is in the corpus, and what search knows about it.

        Split out of `hint()` so the two callers that must NOT offer a restore
        -- the clean-write rebuild failure and the clean-write optimize failure
        -- can state the same facts and then give their own remedy.
        """
        if self.batches_written < self.batches_attempted:
            # The attempted-but-unconfirmed batch. See the class docstring:
            # `upsert_chunks` deletes and adds in two commits, so a batch that
            # raised may have committed the delete alone.
            state = (
                f"{self.rows_written} row(s) in {self.batches_written} batch(es) are "
                f"ALREADY written and batch {self.batches_attempted} FAILED PART-WAY: "
                "its delete and its add are two separate commits, so that batch's "
                f"{self.ids_in_flight} row(s) may now be DELETED from the corpus with "
                "no replacement. The corpus is NOT known to be unchanged"
            )
        else:
            state = (
                f"{self.rows_written} row(s) in {self.batches_written} batch(es) are "
                "ALREADY written"
            )
        return f"{state} and the full-text index {self._index_phrase()}"

    def remedy(self) -> str:
        """What to DO about the state `state_sentence()` describes.

        Every terminating message in this module is now `state_sentence()`
        (which carries the index phrase) plus this. Split out because the three
        raise sites each hand-wrote their own artefact-naming prose and had
        already drifted -- two spellings of the empty-snapshot fallback, and
        two different orders for naming the snapshot and the reversal record.

        🔴 The branch that matters is the half-committed batch, and it is the
        one `hint()` used to get WRONG. `upsert_chunks` deletes the batch's
        chunk_ids and adds the replacements in a SECOND commit
        (`store/chunk_store.py`, the CAUTION comment above `tbl.delete`), so a
        batch that raised may have committed the delete alone and up to
        `ids_in_flight` rows are simply GONE. **The reversal record cannot put
        a deleted row back.** `_plan_corpus` writes one entry per chunk_id
        holding `before`/`after` `section_path` and `text` and NOTHING else --
        no `vector`, no `agency_canonical_ids`, no `fund_mentions`, none of the
        ~30 other columns `store/schema.py` defines -- so replaying it can set
        values on rows that still exist and cannot recreate one that does not.
        Offering "restore from X or replay Y" there (which `hint()` did) hands
        the operator two options of which one silently cannot work, on the one
        failure path that has actually lost data.
        """
        if not self.batches_attempted:
            # WHY this branch does not offer the snapshot: restoring it rolls
            # the whole corpus back to the moment this pass started, discarding
            # every upload since -- an enormous, silent loss to undo a write
            # that never happened. No `upsert_chunks` was ever CALLED, so
            # nothing moved and there is nothing to undo.
            #
            # WHY it no longer says the two artefacts "can be deleted": that
            # was a destructive instruction resting on a premise the old
            # `rows_written` test got wrong (see the class docstring). Litter
            # on the share is cheap; a deleted snapshot is not recoverable.
            return (
                f"{self._snapshot_phrase()} and the reversal record at "
                f"{self.reversal_path} are unneeded but harmless. Leave them in place."
            )
        if self.verified:
            # Every written row was re-read and compared column by column
            # against what was sent, so the corpus is correct and a restore
            # would discard a good write plus every upload since it -- to fix
            # an index rebuild or a version prune. Both artefacts are still
            # NAMED, as facts an operator may want later, never as the
            # instruction.
            return (
                "The rows are correct and verified, so do NOT roll the corpus back. "
                f"{self._snapshot_phrase()} and the reversal record at "
                f"{self.reversal_path} are still in place if the rows ever do need "
                "undoing."
            )
        if self.batches_written < self.batches_attempted:
            # Rows may be DELETED. See the docstring above: the reversal record
            # carries two fields per chunk_id and cannot recreate a row, so the
            # snapshot is the sole recovery and must be named as such.
            return (
                f"{self._snapshot_phrase()} is the ONLY way to bring deleted rows "
                f"back; the reversal record at {self.reversal_path} carries a "
                "before/after section_path and text per chunk_id and nothing else "
                "(no vector, no agency or fund stamps, no other column), so replaying "
                "it restores values on rows that still exist and CANNOT recreate a "
                "row that the failed batch removed."
            )
        # Every attempted batch RETURNED, so nothing was deleted without a
        # replacement and the two artefacts really are alternatives: the
        # reversal record puts the four columns back row by row, the snapshot
        # puts the whole table back.
        return f"Restore from {self._snapshot_phrase()} or replay {self.reversal_path}."

    def hint(self) -> str:
        if not self.batches_attempted:
            return (
                "No write was ever attempted, so the corpus is unchanged -- there is "
                f"nothing to undo; {self.remedy()}"
            )
        return f"{self.state_sentence()}. {self.remedy()}"


def _write_changed_rows(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    embedder: EmbedderLike,
    batch_size: int,
    progress: Callable[[str], None],
    state: _WriteState,
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
                # NOT "nothing is written": this check runs before THIS
                # batch's upsert but after every earlier batch's, so the
                # honest scope is "batch N and everything after it". How
                # much did land is in `state.hint()`, appended by the
                # caller once the index rebuild has or has not run.
                raise RuntimeError(
                    f"{change.chunk_id}: its text is no longer what the plan was built "
                    "on -- the corpus moved under the plan (a re-ingest between planning "
                    f"and writing). Batch {batch_num} and every batch after it is NOT "
                    "written; re-run the dry run"
                )
            new_row = dict(row)
            new_row["section_path"] = list(change.new_path)
            new_row["text"] = change.new_text
            new_row["token_count"] = count_tokens(change.new_text)
            pending.append(new_row)
        if len(pending) != len(ids):
            # `len(rows)` and `len(pending)` answer different questions --
            # how many rows came back, and how many of those the plan still
            # recognises. Reporting `pending` as "what the store returned"
            # (the first version) hides the case where the store answered in
            # full and the ids no longer match the plan.
            raise RuntimeError(
                f"batch {batch_num}: asked for {len(ids)} rows, the store returned "
                f"{len(rows)}, of which {len(pending)} matched the plan -- rows vanished "
                f"under the plan. Batch {batch_num} and every batch after it is NOT "
                "written; re-run the dry run"
            )
        # input_type="document" is the embedder's default, but it is stated
        # here because it is not a formality (ingest/worker.py::_embed): the
        # model is asymmetric, and a passage embedded with the QUERY
        # instruction quietly degrades every future search against it.
        vectors = embedder.embed_batch([r["text"] for r in pending], input_type="document")
        for row, vector in zip(pending, vectors):
            row["vector"] = vector
        # WHY the ATTEMPT is recorded before the call and not only its success
        # after it: `upsert_chunks` deletes this batch's chunk_ids and adds the
        # replacements in a second, separate commit (`store/chunk_store.py`'s
        # CAUTION comment), so a failure between the two leaves these rows
        # DELETED. A counter incremented only on return reports "no rows were
        # written" over a corpus that just lost `len(pending)` rows -- and the
        # hint built on it told the operator to delete both restore points and
        # skipped the index rebuild.
        state.batches_attempted = batch_num
        state.ids_in_flight = len(pending)
        store.upsert_chunks(table, pending)
        written.extend(pending)
        state.rows_written = len(written)
        state.batches_written = batch_num
        progress(f"wrote batch {batch_num}/{total_batches} ({len(written)}/{len(changes)} rows)")
    return written


def _list_len(value: Any) -> int:
    """Length of a list column, whatever container the store handed back."""
    normalised = _norm(value)
    return len(normalised) if isinstance(normalised, list) else 0


def _passthrough_mismatch(now: Mapping[str, Any], sent: Mapping[str, Any]) -> str | None:
    """The first column that came back different from what was sent, or None.

    WHY compare against what was SENT rather than against the pre-write row:
    four columns are supposed to differ, and every other column is passed
    through by value (`_write_changed_rows` copies the fetched row and
    replaces four keys) -- so the dict handed to `upsert_chunks` IS the
    expected post-write row, `token_count` included.

    WHY it exists at all: the first version of this verifier re-read every
    column and then checked only `section_path`, `text` and that the vector
    was non-empty. A write path that dropped `agency_canonical_ids` or
    `fund_mentions` would have passed it in silence, which is exactly the
    loss spec G-T3 exists to refuse -- and `upsert_chunks` deletes then adds,
    so the row COUNT would have matched either way.

    `vector` is compared by LENGTH only: it round-trips through Arrow
    float32, so the values that come back are not bit-for-bit the Python
    floats that went in and an equality test would fail on every correct
    write.
    """
    for col in _all_columns():
        if col == "vector":
            if _list_len(now.get(col)) != _list_len(sent.get(col)):
                return col
            continue
        if _norm(now.get(col)) != _norm(sent.get(col)):
            return col
    return None


def _untouched_sample_ids(
    before_by_id: Mapping[str, Mapping[str, Any]], changed_ids: set[str]
) -> list[str]:
    """WHICH rows the untouched sample watches -- deterministic, and taken
    from the plan-time scan so it does not depend on when the lock was won."""
    return sorted(set(before_by_id) - changed_ids)[:UNCHANGED_SAMPLE_SIZE]


def _untouched_baseline(
    store: ChunkStoreLike,
    table: str,
    before_by_id: Mapping[str, Mapping[str, Any]],
    changed_ids: set[str],
    batch_size: int,
    progress: Callable[[str], None],
) -> dict[str, Mapping[str, Any]]:
    """Re-read the untouched sample UNDER THE LOCK, before the first write.

    WHY not just keep the plan-time rows (what the first version did):
    planning reads ~4,500 documents' extractor JSON off the share and takes
    tens of minutes, and ingest may be running on somebody's PC throughout.
    An untouched document legitimately re-ingested inside that window would
    have failed the post-write comparison and told the operator to restore a
    snapshot over a write that was entirely correct. Reading the baseline
    lock-to-lock means every difference the sample sees really was caused by
    this pass.

    The sample ids still come from the plan-time scan, so WHICH rows are
    watched is deterministic and does not depend on when the lock was won.
    """
    untouched = _untouched_sample_ids(before_by_id, changed_ids)
    if not untouched and len(before_by_id) > len(changed_ids):
        # The sample SHOULD have existed: the plan scan saw more ids than the
        # change set holds, so at least one of them is a row this pass never
        # touches. An empty sample makes every later comparison iterate
        # nothing, so spec G-T3's untouched-row half reports success having
        # compared zero rows -- the same silent no-op the EMPTY-read branch
        # below refuses, arriving from the other side.
        #
        # WHY this cannot fire through today's `_untouched_sample_ids` (and is
        # here anyway): a set difference that empties out implies the change
        # set covers every scanned id, which makes the count test false. It is
        # a tripwire on the DERIVATION, which is the part a later edit breaks
        # -- and the failure it would cause is invisible, because the check it
        # disables still passes.
        raise RuntimeError(
            f"the untouched-row sample is EMPTY even though the plan scan saw "
            f"{len(before_by_id)} rows against a change set of {len(changed_ids)} -- "
            "rows this pass never touches exist but none was sampled, and an empty "
            "sample would make spec G-T3's untouched-row check pass without comparing "
            "anything. Nothing has been written; re-run the dry run"
        )
    baseline: dict[str, Mapping[str, Any]] = {}
    for start in range(0, len(untouched), batch_size):
        ids = untouched[start:start + batch_size]
        for row in store.scan(table, PLAN_COLUMNS, where=_in_list(ids)):
            baseline[str(row["chunk_id"])] = row
    missing = len(untouched) - len(baseline)
    if missing:
        # A sample that has emptied itself is not a passing check, it is an
        # absent one: every later comparison iterates `sorted(baseline)`, so
        # zero rows means zero assertions and G-T3's second half reports
        # success having looked at nothing. Same for a read that lost most of
        # the sample. Refused HERE, before the first `upsert_chunks`, so the
        # corpus is still untouched and the operator can re-run the dry run
        # rather than reason about a half-written table. See
        # `UNCHANGED_SAMPLE_MISSING_LIMIT` for why the line is a tenth.
        if untouched and not baseline:
            raise RuntimeError(
                f"the untouched-row sample came back EMPTY: all {len(untouched)} rows "
                "this pass was never going to touch could not be re-read under the "
                "lock. That is not a concurrent re-ingest, it is the read itself "
                "failing -- and an empty sample would make spec G-T3's untouched-row "
                "check pass without comparing anything. Nothing has been written; "
                "re-run the dry run"
            )
        # `_missing_tolerance` and not a bare fraction: on a sample of fewer
        # than ten rows a tenth is under one row, so a single benign
        # concurrent re-ingest -- the exact case the drop below exists for --
        # aborted the run. One row is always tolerated; 21 of the live 200
        # still refuses.
        if missing > _missing_tolerance(len(untouched)):
            raise RuntimeError(
                f"{missing} of {len(untouched)} sampled untouched rows could not be "
                f"re-read under the lock, over the "
                f"{_missing_tolerance(len(untouched)):.4g} this pass tolerates as a "
                "concurrent re-ingest -- far likelier that the sample read stopped "
                "working than that this many rows really vanished. Nothing has been "
                "written; re-run the dry run"
            )
        # Under the line: already gone before this pass wrote anything, so not
        # ours. Keeping them in the sample would make this write answer for
        # somebody else's re-ingest.
        progress(
            f"{missing} of {len(untouched)} sampled untouched rows were already gone "
            "before the first write; dropped from the sample"
        )
    return baseline


def _verify_nothing_was_lost(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    written: list[dict[str, Any]],
    untouched_baseline: Mapping[str, Mapping[str, Any]],
    batch_size: int,
    progress: Callable[[str], None],
) -> None:
    """Re-read every changed row and confirm it is exactly what was sent --
    the four intended columns moved and NOTHING else did; then re-read the
    untouched sample and confirm it still reads as it did when the lock was
    taken. A matching ROW COUNT proves neither -- `upsert_chunks` deletes
    then adds, so a lost column and a lost value both leave the count
    identical (`identity/relabel.py`'s trap 3). The untouched sample is the
    half of spec G-T3 that catches a delete landing on the wrong ids."""
    expected = {c.chunk_id: c for c in changes}
    # What was actually handed to the store, which is the authority on what
    # every pass-through column should read back as.
    sent_by_id = {str(r["chunk_id"]): r for r in written}
    seen = 0
    ordered = sorted(expected)
    for start in range(0, len(ordered), batch_size):
        ids = ordered[start:start + batch_size]
        for row in store.scan(table, _all_columns(), where=_in_list(ids)):
            change = expected.get(str(row.get("chunk_id")))
            if change is None:
                continue
            seen += 1
            if _norm(row.get("section_path") or []) != change.new_path:
                raise RuntimeError(f"{change.chunk_id}: section_path did not land")
            if str(row.get("text")) != change.new_text:
                raise RuntimeError(f"{change.chunk_id}: text did not land")
            if not _norm(row.get("vector")):
                raise RuntimeError(f"{change.chunk_id}: vector is empty after the write")
            sent = sent_by_id.get(change.chunk_id)
            if sent is None:
                raise RuntimeError(
                    f"{change.chunk_id}: is in the corpus as a changed row but was never "
                    "in the batch this pass wrote"
                )
            lost = _passthrough_mismatch(row, sent)
            if lost is not None:
                raise RuntimeError(
                    f"{change.chunk_id}: column {lost!r} is not what was written -- this "
                    "pass sends every column but section_path/text/token_count/vector "
                    "through by value, so any other column differing means the write "
                    "lost it (spec G-T3)"
                )
    if seen != len(expected):
        raise RuntimeError(f"verified {seen} rows, expected {len(expected)}")

    # ~200 rows (in practice one document's worth) that this pass was never
    # supposed to touch, read again now and compared with the copy taken
    # after the lock. An in-process smoke check that the delete landed on the
    # right ids, not a spread; the corpus-wide comparison of every untouched
    # column is Task 7 Step 4 (on the copy) and Task 8 Step 4 (live).
    sampled = sorted(untouched_baseline)
    after: dict[str, Mapping[str, Any]] = {}
    for start in range(0, len(sampled), batch_size):
        ids = sampled[start:start + batch_size]
        for row in store.scan(table, PLAN_COLUMNS, where=_in_list(ids)):
            after[str(row["chunk_id"])] = row
    for chunk_id in sampled:
        before, now = untouched_baseline[chunk_id], after.get(chunk_id)
        if now is None:
            raise RuntimeError(
                f"{chunk_id}: was never supposed to change and is GONE after the write"
            )
        for col in ("text", "section_path", "is_table", "doc_id"):
            if _norm(now.get(col)) != _norm(before.get(col)):
                raise RuntimeError(
                    f"{chunk_id}: was never supposed to change but its {col!r} changed "
                    "during the write"
                )
    progress(f"verified {seen} changed rows in full, {len(sampled)} untouched rows sampled")


def _atomic_write_json(path: Path, payload: Any) -> None:
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

    Note for any caller that wants to tell one failure from another: EVERY
    failure after the first write is ATTEMPTED is re-raised as a `RuntimeError`
    carrying `_WriteState.hint()`, with the real exception on `__cause__` (and,
    when the index rebuild or the optimize also failed, that exception one
    further down the `__cause__` chain). That includes a `KeyboardInterrupt` --
    raised inside the write, or inside the rebuild -- which is caught, reported
    with the state of the corpus, and chained rather than allowed to reach the
    terminal bare. So a future CLI wanting distinct exit codes must read
    `__cause__`, not the type of what it caught, and must not assume a Ctrl-C
    arrives as `KeyboardInterrupt`.
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

        # The reversal record goes in AFTER the snapshot and BEFORE the first
        # row moves -- `identity/relabel.py`'s order, and the reason is the
        # failure it protects against. It is computed at PLAN time, so
        # nothing about it needs the write to have happened; writing it last
        # (the first version) meant that a crash, a lost share or a killed
        # process anywhere in the write left the corpus half-rewritten with
        # no row-level undo at all -- only a whole-corpus snapshot restore,
        # which also throws away every upload since. Both paths are printed
        # before any row moves so an operator has them in scrollback even if
        # the process dies without ever returning.
        stamp = _reversal_stamp()
        reversal_path = Path(reversal_dir) / f"section-path-reversal-{table}-{stamp}.json"
        # Announced before AND confirmed after: the first line used to be the
        # only one, so it printed the path of a file that might never have been
        # written (an unreachable share raises inside `_atomic_write_json`), and
        # an operator reading scrollback could not tell a promised record from a
        # real one -- on exactly the artefact a row-level undo depends on.
        progress(f"writing reversal record to {reversal_path}")
        _atomic_write_json(
            reversal_path,
            {"table": table, "snapshot": snapshot, "rows": result.reversal},
        )
        progress(f"reversal record written: {reversal_path}")

        changed_ids = {c.chunk_id for c in changes}
        untouched_baseline = _untouched_baseline(
            store, table, before_by_id, changed_ids, batch_size, progress
        )

        state = _WriteState(snapshot=snapshot, reversal_path=reversal_path)
        failure: BaseException | None = None
        try:
            written = _write_changed_rows(
                store, table, changes, embedder, batch_size, progress, state
            )
            _verify_nothing_was_lost(
                store, table, changes, written, untouched_baseline, batch_size, progress
            )
            # Set only once the verifier has RETURNED. Everything downstream
            # that decides "is a restore the right move?" reads this, so it
            # must mean "somebody checked what landed", never "the loop
            # finished".
            state.verified = True
        except BaseException as exc:  # noqa: BLE001 -- re-raised below, enriched
            # WHY BaseException and not Exception, on the OUTER handler as
            # well as the rebuild's: this block is the 30-60 minute embed and
            # write, which is both when an operator is most likely to press
            # Ctrl-C and the ONLY phase that can leave rows deleted
            # (`upsert_chunks` is a delete commit then a separate add commit).
            # Under `except Exception` a KeyboardInterrupt skipped the hint
            # entirely -- so the interrupt reached the terminal with no row
            # count, no "rows may be DELETED", and neither restore point --
            # while the `finally` still rebuilt the index and any
            # `rebuild_error`/`optimize_error` it recorded was dropped on the
            # floor. The interrupt is not swallowed: the `raise RuntimeError(
            # ...) from failure` below still terminates the run and keeps it on
            # `__cause__`.
            failure = exc
        finally:
            # Re-added rows are invisible to BM25 until the index is rebuilt
            # -- the ingest contract funds/unstamp.py had to learn the hard
            # way. WHY it runs on the failure path too: once any batch has
            # landed, the rows exist and search must be consistent with them.
            # Leaving the index un-rebuilt while the rows are already written
            # (the first version, which skipped the rebuild whenever
            # verification raised) means every analyst's keyword search
            # silently misses those passages until somebody notices -- a
            # worse state than the one that raised. The rebuild is idempotent
            # and does not write chunk data.
            #
            # WHY the rebuild has a try/except of its own: an exception raised
            # inside a `finally` REPLACES whatever was propagating. The first
            # version let `build_fts_index` raise straight out, which on the
            # failure path destroyed the original failure and its hint outright
            # -- the operator saw an FTS error and never learned that
            # verification had failed, how many rows had landed, or either
            # restore path. It is recorded instead, and re-raised below in a
            # form that keeps both.
            #
            # WHY this gates on `batches_attempted` and not `rows_written`:
            # a batch that raised between its delete commit and its add commit
            # has already removed rows from the table while `rows_written` is
            # still 0, and skipping the rebuild there leaves the index
            # describing rows that no longer exist. The attempt is what makes
            # the index stale, not the return value.
            if state.batches_attempted:
                try:
                    store.build_fts_index(table)
                    # WHY the flag is set HERE and not after `optimize`: the
                    # index IS rebuilt the moment this call returns. Setting it
                    # after both calls meant an `optimize` failure -- which
                    # only leaves old table versions unpruned -- was reported
                    # as "the index was NOT rebuilt", i.e. as keyword search
                    # missing every written row, pointing an operator at a
                    # restore that would discard a correct write.
                    state.index_rebuilt = True
                except BaseException as rebuild_exc:  # noqa: BLE001 -- re-raised below
                    # WHY BaseException and not Exception: a Ctrl-C landing
                    # inside the rebuild is not an `Exception`, so it escaped
                    # this handler, escaped the `finally`, and REPLACED the
                    # propagating verification failure and its hint -- the
                    # exact loss this try/except was added to stop, on the one
                    # interruption an operator produces deliberately. It is
                    # recorded and chained into the raise below, so the run
                    # still terminates and the interrupt is still on the
                    # `__cause__` chain rather than swallowed.
                    state.rebuild_error = rebuild_exc
                    progress(
                        f"FULL-TEXT INDEX REBUILD FAILED: {rebuild_exc} -- the rows are "
                        "written and keyword search will MISS them until it is rebuilt"
                    )
                else:
                    try:
                        store.optimize(table)
                        progress("full-text index rebuilt and table optimized")
                    except BaseException as optimize_exc:  # noqa: BLE001 -- re-raised
                        # Recorded as its OWN fact. Same BaseException reason
                        # as above, and the wording never says "NOT rebuilt":
                        # search is correct, only the version pruning failed.
                        state.optimize_error = optimize_exc
                        progress(
                            "the full-text index WAS rebuilt; optimize FAILED: "
                            f"{optimize_exc} -- old versions were not pruned, search "
                            "is correct; re-run optimize by hand"
                        )
        if failure is not None:
            # Composed HERE, after the `finally`, so it can state whether the
            # index really was rebuilt rather than what was true when the
            # error was raised. Every failure past this point reaches the
            # operator carrying both restore points and how much landed.
            # Both failures survive, in the order the operator needs them:
            # the RuntimeError says what went wrong with the WRITE, its
            # `__cause__` is that original failure, and ITS `__cause__` is
            # the index error the hint also names in prose. Chaining the
            # second error onto the original (rather than raising it) is
            # what stops the second failure eating the first. `rebuild_error`
            # first because it is the one that costs search correctness.
            secondary = state.rebuild_error or state.optimize_error
            if secondary is not None:
                failure.__cause__ = secondary
            raise RuntimeError(f"{failure} -- {state.hint()}") from failure
        if state.rebuild_error is not None:
            # The write and the verification both passed and the rebuild did
            # not. Nothing else raises here, so the first version let the bare
            # exception escape with no hint at all -- 10,200 rows live behind a
            # stale BM25 index, which is the most dangerous state this module
            # can produce, and no count, no "NOT rebuilt", no restore paths.
            #
            # WHY the artefact prose is `state.remedy()` and not written out
            # here: on THIS path every row was written and then verified column
            # by column, so the corpus is correct and a restore would roll back
            # a good write plus every upload since, to fix an index --
            # `remedy()`'s `verified` branch is exactly that sentence, and it
            # is shared with the optimize path below rather than typed twice
            # (the two copies had already drifted on how they spelled the
            # empty-snapshot fallback). What stays here is the only part that
            # is specific to a rebuild failure: which command to re-run.
            raise RuntimeError(
                "the full-text index rebuild failed AFTER the rows were written "
                f"-- {state.state_sentence()}. {state.remedy()} Fix whatever the "
                f"rebuild could not reach and re-run build_fts_index on {table} by "
                "hand."
            ) from state.rebuild_error
        if state.optimize_error is not None:
            # The rows landed, verified, and the index WAS rebuilt -- only the
            # version pruning failed. It still has to reach the operator (a
            # bare escape would carry no context at all), but it must never
            # read as a search problem or invite a restore: the corpus and the
            # index are both correct and the only cost is disk.
            raise RuntimeError(
                "the table optimize failed after a clean, verified write "
                f"-- {state.state_sentence()}. {state.remedy()} Nothing needs "
                f"restoring and search is correct; re-run optimize on {table} by hand "
                "to prune the old table versions."
            ) from state.optimize_error

    return result
