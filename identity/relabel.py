"""Re-label the corpus: apply the fixed agency matcher to every stored chunk
(spec I2).

Tasks 2-4 fixed the MATCHER (`chunking/entity_stamper.py`'s fuzzy-match
scorer switched from `token_set_ratio` to `token_sort_ratio` — see that
file's WHY comment) and `identity/label_audit.py` measured what it does
against the live corpus: wrong labels corpus-wide 962 -> 139, the
Osteopathic Examiners defect (67.8% of its 992 documents) gone entirely,
94.1% of labels retained unchanged. **None of that takes effect until the
STORED rows are rewritten** — nothing on any read path re-runs the matcher,
it only reads whatever `agency_canonical_ids` is already sitting in
`budget_chunks`. This module is what applies the fix: it re-resolves every
row's labels and writes back only the ones that actually changed.

## Order of operations, and why it is not symmetric between the two modes

    dry_run=True:  scan -> resolve -> report (no lock, no snapshot, no write)
    dry_run=False: LOCK -> snapshot+verify -> scan -> resolve -> write
                    (batched) -> verify nothing was lost -> reversal record

A dry run never calls `store.upsert_chunks` -- it is a READER, and
`store/chunk_store.py`'s own module docstring says readers need no lock
("any number of reader processes; writers are externally serialized").
Requiring the lock for a dry run too would block a real ingest for no
reason during what is meant to be a cheap, repeatable "what would change"
report (Step 5 of the plan runs it against the live corpus by hand, more
than once, before anyone approves an apply).

Applying is a different animal: `upsert_chunks` is a delete-then-add across
two separate LanceDB commits (`store/chunk_store.py`'s own docstring calls
this out explicitly), so a crash between them would leave those chunk_ids
missing from the corpus. That is what makes this pass operationally an
INGEST rather than an edit, and why it takes `ingest.lock.IngestLock` and a
verified `store.backup.snapshot()` first, exactly like `ingest/worker.py`'s
write phase does.

## The three traps this module exists to name in code, not just in prose

1. **`vector` is invisible to every convenient reader.** `_ALL_COLUMNS`
   below is built from the real schema (`store/schema.py`) precisely so it
   can never silently drift out of sync with it, and it is passed to every
   `store.scan()` call this module makes. See the constant's own comment.
2. **`upsert_chunks` is two commits, not one.** See `_write_changed_rows`.
3. **A row count matching before and after proves nothing about which rows
   survived.** See `_verify_nothing_was_lost` -- it checks the id SETS are
   equal and diffs every non-agency column on every row this pass touched.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import types
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from ingest.lock import IngestLock
from store.schema import chunk_schema

# Every stored column, `vector` included, in schema order. Derived from the
# schema itself rather than hand-copied -- TRAP 1 (module docstring):
# `store/chunk_store.py`'s `_columns` attribute is built as "every field
# except vector" (line 107 there), because every SEARCH consumer only ever
# wants to look at the columns, never the 768-float embedding they were
# matched by. `get_by_ids`, `vector_search` and `fts_search` all use that
# projected list. `scan()` is the one method that returns exactly the
# columns it is asked for -- so a caller (this one) that forgot to ask for
# `vector` would get rows missing a required field, and every one of those
# rows would then go straight into `upsert_chunks`, which does a real
# delete-then-add: the OLD row (with its vector) is gone the moment the
# delete lands, and the ADD would be writing the corpus's own vector index
# out from under 83,016 rows. `dim=1` below is deliberate -- the dimension
# only sizes the vector column's fixed-length list TYPE, never its NAME, so
# any value produces the identical column list; using an obviously-wrong
# one is a reminder that this call is name-only.
_ALL_COLUMNS = [f.name for f in chunk_schema(dim=1)]

DEFAULT_BATCH_SIZE = 4000
# How often to print a "still working" line while resolving. 83,016 rows
# through rapidfuzz is not instant, and CLAUDE.md is explicit that a silent
# multi-minute pass is indistinguishable from a hang.
_PROGRESS_EVERY = 5000
# Bound on how many UNCHANGED rows get a full column-by-column diff in the
# post-write verification. Every CHANGED row is always checked in full --
# this cap only limits the extra defensive check over rows nothing should
# have touched at all (see `_verify_nothing_was_lost`).
_UNCHANGED_SAMPLE_SIZE = 200


class ChunkStoreLike(Protocol):
    """The two `store.chunk_store.ChunkStore` methods this pass calls."""

    def scan(
        self, table: str, columns: list[str], *, where: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def upsert_chunks(self, table: str, rows: Iterable[dict[str, Any]]) -> None: ...


class EntityStamperLike(Protocol):
    """The one `chunking.entity_stamper.EntityStamper` method this pass calls."""

    def resolve_all(self, chunk: Any, *, source_url: str | None = None) -> list[str]: ...


@dataclass
class RelabelResult:
    changed: int
    chunk_count_before: int
    chunk_count_after: int
    reversal: list[dict[str, Any]] = field(default_factory=list)
    scanned: int = 0
    snapshot_name: str | None = None
    reversal_path: Path | None = None


def _default_progress(message: str) -> None:
    print(f"identity.relabel: {message}", file=sys.stderr, flush=True)


def _row_to_chunk_like(row: Mapping[str, Any]) -> Any:
    """A bare object carrying only the four fields
    `EntityStamper.resolve_all` reads (`chunking/entity_stamper.py`):
    `agency_canonical_id`, `section_path`, `text`, `is_table`.

    `agency_canonical_id` is forced to `None`. `resolve_all` (and the
    `stamp()` method it shares logic with) treat a set scalar as "already
    decided" and pass it straight through unresolved -- correct behaviour
    for fresh ingest, where a chunk that already carries an id got there
    from a URL-slug match the caller trusts more than a re-derivation. This
    pass exists BECAUSE the stored answer might be wrong, so it must never
    hand the resolver its own old answer to rubber-stamp.
    """
    return types.SimpleNamespace(
        agency_canonical_id=None,
        section_path=list(row.get("section_path") or []),
        text=row.get("text") or "",
        is_table=bool(row.get("is_table")),
    )


def _compute_changes(
    rows: list[dict[str, Any]],
    stamper: EntityStamperLike,
    source_url_by_doc: Mapping[str, str],
    progress: Callable[[str], None],
) -> list[tuple[dict[str, Any], list[str], list[str]]]:
    """Every row whose freshly-resolved labels differ from what is stored.

    Returns `(row, old_labels, new_labels)` triples. Comparison is a plain
    list `!=` -- order matters, because `resolve_all` pins the scalar
    (single-agency) answer first for a table chunk (D2), so a re-ordering is
    itself evidence the OLD write picked a different primary agency, not
    cosmetic noise to ignore.
    """
    changes: list[tuple[dict[str, Any], list[str], list[str]]] = []
    total = len(rows)
    for i, row in enumerate(rows, start=1):
        chunk_like = _row_to_chunk_like(row)
        url = source_url_by_doc.get(row["doc_id"])
        new_labels = list(stamper.resolve_all(chunk_like, source_url=url))
        old_labels = list(row.get("agency_canonical_ids") or [])
        if new_labels != old_labels:
            changes.append((row, old_labels, new_labels))
        if i % _PROGRESS_EVERY == 0:
            progress(f"resolved {i}/{total} rows ({len(changes)} changed so far)")
    progress(f"resolved {total}/{total} rows -- {len(changes)} changed")
    return changes


def _write_changed_rows(
    store: ChunkStoreLike,
    table: str,
    changes: list[tuple[dict[str, Any], list[str], list[str]]],
    batch_size: int,
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Write only the changed rows, a few thousand at a time.

    TRAP 2 (module docstring): `upsert_chunks` deletes the batch's chunk_ids
    and then adds the replacements, as two separate LanceDB commits. Batching
    is what bounds the blast radius of a crash landing between them to ONE
    batch instead of all 83,016 rows, and the progress line after each batch
    is what turns "did this hang or is it just slow" from a guess into a
    fact -- this can run for minutes over the live corpus.
    """
    total = len(changes)
    if total == 0:
        return []
    written: list[dict[str, Any]] = []
    total_batches = math.ceil(total / batch_size)
    for batch_num, start in enumerate(range(0, total, batch_size), start=1):
        batch = changes[start:start + batch_size]
        # A shallow copy is enough: only `agency_canonical_ids` is replaced
        # here, and every other column's VALUE (including the `section_path`
        # / `bbox` lists and the `vector` list) is passed through untouched
        # rather than rebuilt, so there is nothing to accidentally mutate.
        rows_to_write = []
        for row, _old_labels, new_labels in batch:
            new_row = dict(row)
            new_row["agency_canonical_ids"] = new_labels
            rows_to_write.append(new_row)
        store.upsert_chunks(table, rows_to_write)
        written.extend(rows_to_write)
        progress(
            f"wrote batch {batch_num}/{total_batches} "
            f"({min(start + batch_size, total)}/{total} changed rows written)"
        )
    return written


def _verify_nothing_was_lost(
    store: ChunkStoreLike,
    table: str,
    before_rows: list[dict[str, Any]],
    changed_ids: set[str],
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    """TRAP 3 (module docstring): re-read the corpus after writing and prove
    two separate things, because a matching ROW COUNT proves neither of
    them:

    1. The id SETS are identical -- nothing vanished, nothing appeared,
       under whatever the real chunk_id churn happened to be.
    2. Every column OTHER than `agency_canonical_ids` is byte-identical to
       what was there before, for every row this pass touched (a bug that
       silently dropped `doc_type` or `fiscal_year` while rewriting a row
       would otherwise be invisible -- the count and even the id set would
       both still match). A bounded sample of the untouched rows gets the
       same check, purely as a second line of defence against the write
       path touching something it was never given.

    Raises `RuntimeError` rather than returning a verdict: there is no
    correct way to "continue" past a corpus that lost rows, and a caller
    that ignored a returned boolean is exactly how this kind of bug reaches
    production.
    """
    after_rows = store.scan(table, _ALL_COLUMNS)
    before_by_id = {r["chunk_id"]: r for r in before_rows}
    after_by_id = {r["chunk_id"]: r for r in after_rows}

    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    if before_ids != after_ids:
        missing = before_ids - after_ids
        extra = after_ids - before_ids
        raise RuntimeError(
            "identity.relabel: the corpus lost or gained chunk_ids while "
            f"writing -- {len(missing)} missing, {len(extra)} unexpected. "
            "Restore from the snapshot this pass just took before "
            "investigating further; do not re-run relabel against a corpus "
            "in this state."
        )

    def _diff_row(chunk_id: str) -> str | None:
        before, after = before_by_id[chunk_id], after_by_id[chunk_id]
        for col in _ALL_COLUMNS:
            if col == "agency_canonical_ids":
                continue
            if before.get(col) != after.get(col):
                return col
        return None

    for chunk_id in changed_ids:
        bad_col = _diff_row(chunk_id)
        if bad_col is not None:
            raise RuntimeError(
                f"identity.relabel: chunk {chunk_id!r} lost column "
                f"{bad_col!r} while its labels were being rewritten. "
                "Restore from the snapshot this pass just took."
            )

    # Bounded, deterministic sample of rows nothing was supposed to touch.
    unchanged_ids = sorted(before_ids - changed_ids)[:_UNCHANGED_SAMPLE_SIZE]
    for chunk_id in unchanged_ids:
        bad_col = _diff_row(chunk_id)
        if bad_col is not None:
            raise RuntimeError(
                f"identity.relabel: chunk {chunk_id!r} was never supposed "
                f"to change but its {bad_col!r} column drifted anyway. "
                "Restore from the snapshot this pass just took."
            )

    progress(
        f"verified {len(after_ids)} chunk_ids intact "
        f"({len(changed_ids)} changed rows checked in full, "
        f"{len(unchanged_ids)} untouched rows sampled)"
    )
    return after_rows


def _default_snapshot_and_verify() -> str | None:
    """Take an S17 corpus snapshot and confirm the archive is actually
    readable before trusting it as this pass's undo path.

    `store.backup.snapshot()` writes to a `.part` file and only renames it
    into place on success, so a NAME being returned already rules out a
    truncated write -- but says nothing about whether the archive survived
    intact afterwards (a flaky share, a disk error). `zipfile.testzip()`
    reads every member's CRC and returns the first bad one, or `None` if the
    whole archive checks out; that is the one cheap operation that actually
    proves the snapshot is restorable, rather than merely present.

    Imported lazily so importing this module never touches the real data
    dir -- only calling this function (the default only when `dry_run=False`
    and no caller override was passed) does.
    """
    from store.backup import backups_dir, snapshot

    name = snapshot()
    if name is None:
        return None  # no corpus on disk yet -- nothing to protect
    path = backups_dir() / name
    if not path.is_file():
        raise RuntimeError(
            f"identity.relabel: store.backup.snapshot() reported {name!r} "
            f"but {path} does not exist"
        )
    with zipfile.ZipFile(path) as zf:
        bad_member = zf.testzip()
    if bad_member is not None:
        raise RuntimeError(
            f"identity.relabel: corpus snapshot {name!r} is corrupt at "
            f"member {bad_member!r} -- refusing to relabel without a "
            "verified restore point"
        )
    return name


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def relabel_corpus(
    *,
    store: ChunkStoreLike,
    stamper: EntityStamperLike,
    source_url_by_doc: Mapping[str, str] | None = None,
    table: str = "budget_chunks",
    dry_run: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock: IngestLock | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> RelabelResult:
    """Re-resolve every row's agency labels; write back only what changed.

    `dry_run=True` (the default) never acquires `lock`, never snapshots, and
    never writes -- see the module docstring for why that asymmetry with
    `dry_run=False` is deliberate, not an oversight.

    `lock`, `snapshot_and_verify` and `reversal_dir` all default to the real
    things (`ingest.lock.IngestLock()`, `store.backup.snapshot()` + a
    zip-integrity check, `store.config.data_dir()`) and are only ever
    constructed lazily, inside the `dry_run=False` branch -- so calling this
    with `dry_run=True` and no overrides touches neither the real data dir
    nor the real corpus, which is what lets Step 5 of the plan be re-run by
    hand against the live corpus as many times as needed before anyone
    approves an apply.
    """
    source_url_by_doc = source_url_by_doc or {}
    progress = progress or _default_progress

    if dry_run:
        before_rows = store.scan(table, _ALL_COLUMNS)
        changes = _compute_changes(before_rows, stamper, source_url_by_doc, progress)
        reversal = [
            {
                "doc_id": row["doc_id"], "chunk_id": row["chunk_id"],
                "before": old, "after": new,
            }
            for row, old, new in changes
        ]
        return RelabelResult(
            changed=len(changes),
            chunk_count_before=len(before_rows),
            chunk_count_after=len(before_rows),
            reversal=reversal,
            scanned=len(before_rows),
        )

    # --- apply: lock -> snapshot+verify -> scan -> resolve -> write -> verify -> reversal ---
    if lock is None:
        lock = IngestLock()

    with lock:
        lock.heartbeat()
        progress("acquired the ingest lock -- taking a corpus snapshot")
        snapshot_name = (snapshot_and_verify or _default_snapshot_and_verify)()
        lock.heartbeat()

        before_rows = store.scan(table, _ALL_COLUMNS)
        progress(f"scanned {len(before_rows)} rows from {table!r}")
        changes = _compute_changes(before_rows, stamper, source_url_by_doc, progress)
        lock.heartbeat()

        # The return value isn't consulted below on purpose: the
        # authoritative post-write state is whatever `_verify_nothing_was_lost`
        # re-reads FROM THE STORE, not what this pass merely intended to send
        # (see TRAP 3 in the module docstring -- intent is not proof).
        _write_changed_rows(store, table, changes, batch_size, progress)
        lock.heartbeat()

        changed_ids = {row["chunk_id"] for row, _old, _new in changes}
        after_rows = _verify_nothing_was_lost(
            store, table, before_rows, changed_ids, progress,
        )

        reversal = [
            {
                "doc_id": row["doc_id"], "chunk_id": row["chunk_id"],
                "before": old, "after": new,
            }
            for row, old, new in changes
        ]
        if reversal_dir is None:
            from store.config import data_dir as _resolve_data_dir

            reversal_dir = _resolve_data_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        reversal_path = reversal_dir / f"label-reversal-{stamp}.json"
        _atomic_write_json(reversal_path, {
            "table": table,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot_name,
            "scanned": len(before_rows),
            "changed": len(changes),
            "changes": reversal,
        })
        progress(f"reversal record written: {reversal_path}")

        return RelabelResult(
            changed=len(changes),
            chunk_count_before=len(before_rows),
            chunk_count_after=len(after_rows),
            reversal=reversal,
            scanned=len(before_rows),
            snapshot_name=snapshot_name,
            reversal_path=reversal_path,
        )


def _load_live_store_and_stamper() -> tuple[ChunkStoreLike, EntityStamperLike, dict[str, str]]:
    """Assemble real collaborators from the live corpus. I/O only -- never
    imported at module scope, so importing `identity.relabel` (as every test
    in this suite does) can never open a real LanceDB table or load the
    fuzzy-match catalog just by being imported.
    """
    from chunking.entity_stamper import EntityStamper
    from store.chunk_store import ChunkStore
    from store.documents import load_documents

    store = ChunkStore()
    stamper = EntityStamper.from_default_paths()
    source_url_by_doc = {
        doc_id: meta.get("source_url")
        for doc_id, meta in load_documents().items()
        if isinstance(meta, dict) and meta.get("source_url")
    }
    return store, stamper, source_url_by_doc


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m identity.relabel --dry-run | --apply`."""
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="compute and report proposed changes; write nothing",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help="lock the corpus, snapshot it, and rewrite the changed rows",
    )
    ap.add_argument("--table", default="budget_chunks",
                     help="corpus table to relabel (default: budget_chunks)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--out", type=Path, default=None,
                     help="also dump {changed, reversal} as JSON to this path")
    ap.add_argument("--data-dir", type=Path, default=None,
                     help="override JLBC_DATA_DIR for this run")
    args = ap.parse_args(argv)

    if args.data_dir is not None:
        os.environ["JLBC_DATA_DIR"] = str(args.data_dir)

    store, stamper, source_url_by_doc = _load_live_store_and_stamper()
    result = relabel_corpus(
        store=store, stamper=stamper, source_url_by_doc=source_url_by_doc,
        table=args.table, dry_run=not args.apply, batch_size=args.batch_size,
    )

    print(f"scanned: {result.scanned}")
    print(f"changed: {result.changed}")
    print(f"chunk_count_before: {result.chunk_count_before}")
    print(f"chunk_count_after: {result.chunk_count_after}")
    if result.reversal_path is not None:
        print(f"reversal record: {result.reversal_path}")

    if args.out is not None:
        _atomic_write_json(args.out, {
            "table": args.table,
            "dry_run": not args.apply,
            "scanned": result.scanned,
            "changed": result.changed,
            "chunk_count_before": result.chunk_count_before,
            "chunk_count_after": result.chunk_count_after,
            "reversal": result.reversal,
        })
        print(f"written: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
