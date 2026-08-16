"""Rename the doc_ids whose own family (approps/baseline) contradicts their
own `source_url` (spec I10).

`ingest/driver.py::make_doc_id` mints a JLBC book document's id as
`jlbc-{family}-fy{year}-{tail}`, where `family` is which BOOK the document
came out of ("approps" or "baseline"). The `make_doc_id(family=...)` fix
(2026-07-31) makes every NEW document correct by construction, but 22
LEGACY documents were minted before that fix and disagree with their own
source URL -- e.g. `jlbc-approps-fy2022-473` lives at
`https://www.azjlbc.gov/22baseline/473.pdf`. That is latent today (nothing
reads the mismatch), but a write is an upsert, so on a full corpus rebuild a
colliding doc_id would silently REPLACE a document -- the exact failure
`make_doc_id(family=...)` exists to prevent, just arriving from the other
direction (the id, not the mint site).

## The derivation IS the check

Nothing in this module hard-codes the 22 -- `derive_renames` recomputes them
from scratch on every run, by comparing each `jlbc-approps-*` /
`jlbc-baseline-*` doc_id's own family prefix against the family its
`source_url` names. The URL-directory convention it reads
(`azjlbc.gov/<YY>baseline/`, `<YY>book<N>/`, `<YY>ar/`, `<YY>app/`) is the
SAME evidence `store/book_family.py::section_of` already uses and already
verified corpus-wide (647/647 URLs parse, 0 disagree with the document's own
title) -- reused here as the same regex, mirrored rather than imported,
because that module's `_BOOK_DIR`/`_FAMILY` are private to a different
question (which BOOK a SECTION belongs to) and this module must not import
`store.chunk_store` at module scope (see below).

Verified against the live corpus 2026-08-16: exactly 22 mismatches, matching
spec I10's count (FY2022 x5, FY2023 x3, FY2024 x4, FY2025 x2, FY2026 x3,
FY2027 x4, plus one reverse case -- a BASELINE id whose url says AR), and
zero rename targets collide with an existing doc_id.

## Order of operations -- mirrors identity/relabel.py deliberately

    dry_run=True:  derive -> collision-check -> scan -> report (no lock, no
                    snapshot, no write)
    dry_run=False: derive -> collision-check -> LOCK -> snapshot+verify ->
                    scan -> precompute every new row -> per-document
                    delete+add -> verify -> reversal record ->
                    documents.json rewrite

A dry run never calls `store.upsert_chunks` or `store.delete_doc` -- same
reasoning as `identity/relabel.py`'s own module docstring: a reader needs no
lock, and Step 5 of the plan runs this against the live corpus by hand, more
than once, before anyone approves an apply.

`chunking/builder.py:149` mints `chunk_id = f"{doc_id}-{idx:04d}"` for every
chunk, so once a document's doc_id is renamed, EVERY one of its chunk_ids
must be renamed too -- `doc_id` is a chunk COLUMN as well as the
`documents.json` key (`_ALL_COLUMNS` below, mirroring relabel.py's own
trap-1 comment, is what makes `vector` survive the round-trip). Renaming a
document is therefore a full delete-then-add of its chunk rows, exactly like
`ingest/lance_writer.py`'s write phase -- operationally an ingest, hence the
lock and the snapshot.

## Why delete_doc, not upsert_chunks alone

`upsert_chunks` deletes by the INCOMING rows' own chunk_id and then adds
them. Handed a batch of already-renamed rows, that deletes anything already
sitting under the NEW chunk_ids (nothing -- `find_collisions` already proved
that) and adds the new rows, leaving the OLD, wrongly-labelled rows sitting
in the table untouched. `store.delete_doc(table, old_doc_id)` is what
actually removes them, called once per renamed document immediately before
that document's new rows are added -- mirroring the exact
delete_doc-then-upsert_chunks shape `ingest/lance_writer.py` already uses
for every ordinary re-ingest.

## Two real threats: the crossword, and the vanished document

`find_collisions` must be run and must be EMPTY before any write happens.
Two shapes were checked for: (1) an ordinary collision -- some other,
unrelated document already sits at the id this rename would produce, which
would silently vanish under the incoming `upsert_chunks`; and (2) a genuine
two-way SWAP, where document A's target is document B's own current id and
vice versa -- not a real conflict, since both old ids vacate during the
same pass, and flagging it would refuse a rename that is actually safe. See
`find_collisions`'s own docstring for how the two are told apart.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import zipfile
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from ingest.lock import IngestLock
from store.schema import chunk_schema

# Every stored column, `vector` included, in schema order -- derived from
# the schema itself, not hand-copied. Mirrors `identity/relabel.py`'s
# `_ALL_COLUMNS` and exists for the identical reason: `store/chunk_store.py`
# projects `vector` away in every convenient reader (`get_by_ids`,
# `vector_search`, `fts_search`), so only an explicit `scan(..., columns=)`
# call gets it back, and a renamed row written without it would silently
# corrupt the corpus's own vector index. `dim=1` is deliberate -- the
# dimension only sizes the column's fixed-length TYPE, never its NAME.
_ALL_COLUMNS = [f.name for f in chunk_schema(dim=1)]

# Bound on how many UNCHANGED rows get a full column-by-column diff in the
# post-write verification -- mirrors relabel.py's identical constant and
# reasoning. Every RENAMED row is always checked in full.
_UNCHANGED_SAMPLE_SIZE = 200

# JLBC's own azjlbc.gov directory convention. Mirrors `store/book_family.py`
# `_BOOK_DIR` / `_FAMILY` exactly (that module's docstring records the
# corpus-wide verification: 647/647 URLs parse, 0 disagree with the
# document's own title) -- duplicated rather than imported, because
# `store.book_family` answers a different question (which book is a SECTION
# part of, gated on doc_type) and importing it would be reaching across
# modules for two module-private names to serve a use that module was never
# written for. A regex this small is cheaper to keep in lockstep by comment
# than to couple two unrelated call sites to one private implementation.
_BOOK_DIR = re.compile(r"azjlbc\.gov/\d{2}(baseline|book\d*|ar|app)\b", re.I)
_URL_FAMILY = {"baseline": "baseline", "book": "baseline", "ar": "approps", "app": "approps"}

# The two JLBC report families a doc_id's own prefix can name. Mirrors
# `ingest/driver.py`'s `_JLBC_FAMILIES` / doc_id shape
# (`jlbc-{family}-fy{year}-{tail}`) -- that module is the mint site and this
# one is the repair of what it minted wrong before the 2026-07-31 fix.
_ID_FAMILY_PREFIX = {"approps": "jlbc-approps-", "baseline": "jlbc-baseline-"}


def _default_progress(message: str) -> None:
    print(f"identity.rename_docs: {message}", file=sys.stderr, flush=True)


def _atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


class ChunkStoreLike(Protocol):
    """The `store.chunk_store.ChunkStore` methods this pass calls."""

    def scan(
        self, table: str, columns: list[str], *, where: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...

    def delete_doc(self, table: str, doc_id: str) -> None: ...

    def upsert_chunks(self, table: str, rows: Iterable[dict[str, Any]]) -> None: ...

    def get_by_ids(self, table: str, chunk_ids: list[str]) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class RenameEntry:
    """One document whose own doc_id family disagrees with its source_url."""

    old_doc_id: str
    new_doc_id: str
    old_family: str
    new_family: str
    source_url: str


@dataclass
class RenameResult:
    renamed_docs: int
    changed_chunks: int
    chunk_count_before: int
    chunk_count_after: int
    # Every field a document/chunk record carries pre-mutation, so a
    # controller (or the eval re-point step) can read this straight out of
    # a dry run without touching the corpus a second time.
    doc_renames: list[dict[str, Any]] = field(default_factory=list)
    chunk_id_pairs: list[dict[str, str]] = field(default_factory=list)
    scanned: int = 0
    snapshot_name: str | None = None
    reversal_path: Path | None = None


def _url_family(source_url: str) -> str | None:
    m = _BOOK_DIR.search(source_url or "")
    if not m:
        return None
    key = re.sub(r"\d+$", "", m.group(1).lower())  # "book1"/"book2" -> "book"
    return _URL_FAMILY.get(key)


def derive_renames(documents: Mapping[str, Mapping[str, Any]]) -> list[RenameEntry]:
    """Every `jlbc-approps-*` / `jlbc-baseline-*` document whose own doc_id
    family disagrees with the family its `source_url` names.

    No id is hard-coded anywhere in this function -- it is the derivation
    itself that IS the check (spec I10). A document with no `source_url`, or
    a `source_url` this pass cannot place on the azjlbc.gov book-directory
    convention, is left alone rather than guessed at: absence of evidence is
    not evidence the id is wrong.
    """
    renames: list[RenameEntry] = []
    for doc_id, meta in documents.items():
        id_family = next(
            (fam for fam, prefix in _ID_FAMILY_PREFIX.items()
             if doc_id.startswith(prefix)),
            None,
        )
        if id_family is None:
            continue  # not a JLBC book document at all -- out of scope
        source_url = str((meta or {}).get("source_url") or "")
        url_family = _url_family(source_url)
        if url_family is None or url_family == id_family:
            continue  # no usable evidence, or the id already agrees
        old_prefix = _ID_FAMILY_PREFIX[id_family]
        new_prefix = _ID_FAMILY_PREFIX[url_family]
        new_doc_id = new_prefix + doc_id[len(old_prefix):]
        renames.append(RenameEntry(
            old_doc_id=doc_id, new_doc_id=new_doc_id,
            old_family=id_family, new_family=url_family,
            source_url=source_url,
        ))
    return sorted(renames, key=lambda r: r.old_doc_id)


def find_collisions(
    renames: Iterable[RenameEntry], documents: Mapping[str, Any],
) -> list[str]:
    """New doc_ids that already belong to some OTHER, non-renamed document.

    Must be empty before any write happens (spec I10: "Verify no rename
    target collides with an existing doc_id before writing anything").

    A new_doc_id that is itself another rename's OLD id is NOT a collision
    -- that id vacates during this same pass (the two-way-swap case; see the
    module docstring). Excluding it here is what tells a real conflict
    apart from a document that merely happens to be trading places with
    another renamed document.
    """
    renamed_olds = {r.old_doc_id for r in renames}
    return sorted({
        r.new_doc_id for r in renames
        if r.new_doc_id in documents and r.new_doc_id not in renamed_olds
    })


def apply_doc_id_renames(
    documents: Mapping[str, Mapping[str, Any]],
    renames: Iterable[RenameEntry],
) -> dict[str, dict[str, Any]]:
    """New `documents.json` contents with the renamed keys swapped, every
    field of each record preserved verbatim. Pure -- the caller decides
    whether and when to write it (`store.config.write_documents_sidecar`)."""
    updated = {doc_id: deepcopy(dict(meta or {})) for doc_id, meta in documents.items()}
    for entry in renames:
        if entry.old_doc_id in updated:
            updated[entry.new_doc_id] = updated.pop(entry.old_doc_id)
    return updated


def _rename_chunk_id(chunk_id: str, old_doc_id: str, new_doc_id: str) -> str:
    """`chunking/builder.py:149` mints `chunk_id = f"{doc_id}-{idx:04d}"`
    unconditionally, so every real chunk_id starts with its own doc_id plus
    a hyphen. Renaming is therefore a pure prefix substitution with the
    ordinal untouched -- e.g. `jlbc-baseline-fy2026-crr-0013` ->
    `jlbc-approps-fy2026-crr-0013`.

    Raises rather than guessing when that invariant does not hold: a row
    whose chunk_id does NOT start with its own doc_id already disagrees with
    itself before this pass touched it, and blindly string-replacing could
    corrupt an unrelated substring elsewhere in the id.
    """
    prefix = old_doc_id + "-"
    if not chunk_id.startswith(prefix):
        raise ValueError(
            f"chunk_id {chunk_id!r} does not start with its own doc_id "
            f"{old_doc_id!r} plus '-' -- refusing to guess how to rename it. "
            "This means the row's doc_id and chunk_id already disagreed "
            "before this pass touched it; investigate that row directly."
        )
    return new_doc_id + chunk_id[len(old_doc_id):]


def _default_snapshot_and_verify() -> str | None:
    """Take an S17 corpus snapshot and confirm the archive is actually
    readable before trusting it as this pass's undo path. Identical logic to
    `identity/relabel.py::_default_snapshot_and_verify` -- see that
    function's docstring for the full reasoning (`testzip()` is the one
    cheap operation that proves restorability rather than mere presence).

    Imported lazily so importing this module never touches the real data
    dir -- only calling this function (the default, only when `dry_run=False`
    and no caller override was passed) does.
    """
    from store.backup import backups_dir, snapshot

    name = snapshot()
    if name is None:
        return None  # no corpus on disk yet -- nothing to protect
    path = backups_dir() / name
    if not path.is_file():
        raise RuntimeError(
            f"identity.rename_docs: store.backup.snapshot() reported {name!r} "
            f"but {path} does not exist"
        )
    with zipfile.ZipFile(path) as zf:
        bad_member = zf.testzip()
    if bad_member is not None:
        raise RuntimeError(
            f"identity.rename_docs: corpus snapshot {name!r} is corrupt at "
            f"member {bad_member!r} -- refusing to rename without a "
            "verified restore point"
        )
    return name


def _verify_rename(
    store: ChunkStoreLike,
    table: str,
    before_rows: list[dict[str, Any]],
    id_map: dict[str, str],
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Re-read the corpus after writing and prove two things a matching row
    count cannot: the id set is EXACTLY the before set with the renamed ids
    swapped for their new names (nothing else vanished or appeared), and
    every renamed row's OTHER columns -- everything but doc_id/chunk_id --
    are byte-identical to what was there before the rename. A bounded
    sample of untouched rows gets the same column check, as a second line
    of defence against the write path touching something it was never
    given. Mirrors `identity/relabel.py::_verify_nothing_was_lost`.
    """
    after_rows = store.scan(table, _ALL_COLUMNS)
    before_by_id = {r["chunk_id"]: r for r in before_rows}
    after_by_id = {r["chunk_id"]: r for r in after_rows}

    before_ids = set(before_by_id)
    after_ids = set(after_by_id)
    expected_ids = (before_ids - set(id_map)) | set(id_map.values())
    if after_ids != expected_ids:
        missing = expected_ids - after_ids
        extra = after_ids - expected_ids
        raise RuntimeError(
            "identity.rename_docs: the corpus does not hold the expected "
            f"chunk_id set after the rename -- {len(missing)} missing, "
            f"{len(extra)} unexpected. Restore from the snapshot this pass "
            "just took before investigating further; do not re-run this "
            "pass against a corpus in this state."
        )

    def _diff_row(before: dict[str, Any], after: dict[str, Any]) -> str | None:
        for col in _ALL_COLUMNS:
            if col in ("doc_id", "chunk_id"):
                continue
            if before.get(col) != after.get(col):
                return col
        return None

    for old_id, new_id in id_map.items():
        bad_col = _diff_row(before_by_id[old_id], after_by_id[new_id])
        if bad_col is not None:
            raise RuntimeError(
                f"identity.rename_docs: chunk {old_id!r} (now {new_id!r}) "
                f"lost column {bad_col!r} during the rename. Restore from "
                "the snapshot this pass just took."
            )

    unchanged_ids = sorted(before_ids - set(id_map))[:_UNCHANGED_SAMPLE_SIZE]
    for chunk_id in unchanged_ids:
        after = after_by_id.get(chunk_id)
        if after is None:
            raise RuntimeError(
                f"identity.rename_docs: chunk {chunk_id!r} was never "
                "supposed to change but disappeared entirely. Restore from "
                "the snapshot this pass just took."
            )
        bad_col = _diff_row(before_by_id[chunk_id], after)
        if bad_col is not None:
            raise RuntimeError(
                f"identity.rename_docs: chunk {chunk_id!r} was never "
                f"supposed to change but its {bad_col!r} column drifted "
                "anyway. Restore from the snapshot this pass just took."
            )

    progress(
        f"verified {len(after_ids)} chunk_ids intact "
        f"({len(id_map)} renamed rows checked in full, "
        f"{len(unchanged_ids)} untouched rows sampled)"
    )
    return after_rows


def verify_anchor_text(
    store: ChunkStoreLike, table: str, chunk_id: str, anchor_text: str,
) -> bool:
    """True iff `chunk_id` exists in `table` and its stored text contains
    `anchor_text` verbatim.

    This is the surviving repair path for a stale eval `chunk_id`:
    `eval/refresh_chunk_ids.py` was deleted with the Postgres tooling and
    nothing replaces it (STATUS.md), so `anchor_text` -- recorded for every
    `eval/queries.yaml` entry precisely for this situation -- is what a
    human runs BY HAND before trusting a re-pointed eval entry. Spec I10:
    "[the anchor text] either still appears at the new chunk_id or the
    re-point is wrong and the run fails loudly."
    """
    rows = store.get_by_ids(table, [chunk_id])
    if not rows:
        return False
    return anchor_text in (rows[0].get("text") or "")


def rename_corpus(
    *,
    store: ChunkStoreLike,
    documents: Mapping[str, Mapping[str, Any]],
    table: str = "budget_chunks",
    dry_run: bool = True,
    lock: IngestLock | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> RenameResult:
    """Rename every document whose own doc_id family disagrees with its
    source_url, and every one of its chunk rows with it.

    `dry_run=True` (the default) never acquires `lock`, never snapshots, and
    never writes -- same asymmetry as `identity/relabel.py::relabel_corpus`,
    for the same reason: Step 5 of the plan runs this against the live
    corpus by hand, more than once, before anyone approves an apply.

    Collisions are checked BEFORE any lock is taken or row is scanned (spec
    I10: verify first) and raise in BOTH modes -- a dry run that hid a
    collision behind a clean-looking report would be worse than no report at
    all.
    """
    progress = progress or _default_progress
    renames = derive_renames(documents)
    collisions = find_collisions(renames, documents)
    if collisions:
        raise RuntimeError(
            f"identity.rename_docs: {len(collisions)} doc_id collision(s) "
            "found -- rename target(s) already belong to a DIFFERENT, "
            f"non-renamed document; refusing to write anything: {collisions}"
        )

    doc_renames_payload = [
        {"old_doc_id": r.old_doc_id, "new_doc_id": r.new_doc_id,
         "old_family": r.old_family, "new_family": r.new_family,
         "source_url": r.source_url}
        for r in renames
    ]

    if not renames:
        return RenameResult(
            renamed_docs=0, changed_chunks=0,
            chunk_count_before=0, chunk_count_after=0,
        )

    rename_by_old_doc = {r.old_doc_id: r for r in renames}

    if dry_run:
        before_rows = store.scan(table, _ALL_COLUMNS)
        matched = [r for r in before_rows if r["doc_id"] in rename_by_old_doc]
        id_pairs = [
            {
                "old_chunk_id": row["chunk_id"],
                "new_chunk_id": _rename_chunk_id(
                    row["chunk_id"], row["doc_id"],
                    rename_by_old_doc[row["doc_id"]].new_doc_id,
                ),
                "old_doc_id": row["doc_id"],
                "new_doc_id": rename_by_old_doc[row["doc_id"]].new_doc_id,
            }
            for row in matched
        ]
        return RenameResult(
            renamed_docs=len(renames), changed_chunks=len(matched),
            chunk_count_before=len(before_rows), chunk_count_after=len(before_rows),
            doc_renames=doc_renames_payload, chunk_id_pairs=id_pairs,
            scanned=len(before_rows),
        )

    # --- apply: lock -> snapshot+verify -> scan -> precompute -> write -> verify -> reversal ---
    if lock is None:
        lock = IngestLock()

    with lock:
        lock.heartbeat()
        progress("acquired the ingest lock -- taking a corpus snapshot")
        snapshot_name = (snapshot_and_verify or _default_snapshot_and_verify)()
        lock.heartbeat()

        before_rows = store.scan(table, _ALL_COLUMNS)
        progress(f"scanned {len(before_rows)} rows from {table!r}")
        matched_by_doc: dict[str, list[dict[str, Any]]] = {}
        for row in before_rows:
            entry = rename_by_old_doc.get(row["doc_id"])
            if entry is not None:
                matched_by_doc.setdefault(entry.old_doc_id, []).append(row)
        total_matched = sum(len(v) for v in matched_by_doc.values())
        progress(
            f"{total_matched} chunk rows across {len(renames)} documents "
            "need renaming"
        )
        lock.heartbeat()

        # Precompute EVERY new row and id pair up front, before any delete
        # or add lands -- so a malformed row (a chunk_id that does not
        # start with its own doc_id, see `_rename_chunk_id`) aborts with
        # ZERO corpus mutation beyond the snapshot already taken, rather
        # than leaving some documents renamed and others half-deleted.
        new_rows_by_doc: dict[str, list[dict[str, Any]]] = {}
        id_pairs: list[dict[str, str]] = []
        for entry in renames:
            rows = matched_by_doc.get(entry.old_doc_id, [])
            new_rows = []
            for row in rows:
                new_chunk_id = _rename_chunk_id(
                    row["chunk_id"], entry.old_doc_id, entry.new_doc_id,
                )
                new_row = dict(row)
                new_row["doc_id"] = entry.new_doc_id
                new_row["chunk_id"] = new_chunk_id
                new_rows.append(new_row)
                id_pairs.append({
                    "old_chunk_id": row["chunk_id"], "new_chunk_id": new_chunk_id,
                    "old_doc_id": entry.old_doc_id, "new_doc_id": entry.new_doc_id,
                })
            new_rows_by_doc[entry.old_doc_id] = new_rows

        # Per-document delete-then-add, mirroring
        # `ingest/lance_writer.py`'s write phase exactly. WHY per document
        # rather than one big delete-then-one-big-add: only ~22 documents
        # are ever renamed at once, so bounding an interruption's blast
        # radius to ONE document (its delete_doc already ran, its
        # upsert_chunks has not) is cheap and precise, rather than deleting
        # every renamed document's old rows up front and hoping nothing
        # interrupts before any of the adds land.
        for i, entry in enumerate(renames, start=1):
            new_rows = new_rows_by_doc[entry.old_doc_id]
            store.delete_doc(table, entry.old_doc_id)
            if new_rows:
                store.upsert_chunks(table, new_rows)
            progress(
                f"renamed {i}/{len(renames)}: {entry.old_doc_id} -> "
                f"{entry.new_doc_id} ({len(new_rows)} chunks)"
            )
            lock.heartbeat()

        id_map = {p["old_chunk_id"]: p["new_chunk_id"] for p in id_pairs}
        after_rows = _verify_rename(store, table, before_rows, id_map, progress)

        updated_documents = apply_doc_id_renames(documents, renames)
        from store.config import write_documents_sidecar

        write_documents_sidecar(updated_documents)
        progress(f"documents.json rewritten with {len(renames)} renamed key(s)")

        if reversal_dir is None:
            from store.config import data_dir as _resolve_data_dir

            reversal_dir = _resolve_data_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        reversal_path = reversal_dir / f"doc-rename-reversal-{stamp}.json"
        _atomic_write_json(reversal_path, {
            "table": table,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot_name,
            "scanned": len(before_rows),
            "doc_renames": doc_renames_payload,
            "chunk_id_pairs": id_pairs,
        })
        progress(f"reversal record written: {reversal_path}")

        return RenameResult(
            renamed_docs=len(renames), changed_chunks=len(id_pairs),
            chunk_count_before=len(before_rows), chunk_count_after=len(after_rows),
            doc_renames=doc_renames_payload, chunk_id_pairs=id_pairs,
            scanned=len(before_rows), snapshot_name=snapshot_name,
            reversal_path=reversal_path,
        )


def _load_live_store_and_documents() -> tuple[ChunkStoreLike, dict[str, dict[str, Any]]]:
    """Assemble real collaborators from the live corpus. I/O only -- never
    imported at module scope, so importing `identity.rename_docs` (as every
    test in this suite does) can never open a real LanceDB table."""
    from store.chunk_store import ChunkStore
    from store.documents import load_documents

    return ChunkStore(), load_documents()


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m identity.rename_docs --dry-run | --apply`."""
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="compute and report the proposed renames; write nothing",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help="lock the corpus, snapshot it, and rename the documents",
    )
    ap.add_argument("--table", default="budget_chunks",
                     help="corpus table to rename within (default: budget_chunks)")
    ap.add_argument("--out", type=Path, default=None,
                     help="also dump the full result (incl. chunk_id_pairs -- "
                          "what identity.history_migrate.py's --rename-result "
                          "consumes) as JSON to this path")
    ap.add_argument("--data-dir", type=Path, default=None,
                     help="override JLBC_DATA_DIR for this run")
    args = ap.parse_args(argv)

    if args.data_dir is not None:
        os.environ["JLBC_DATA_DIR"] = str(args.data_dir)

    store, documents = _load_live_store_and_documents()
    result = rename_corpus(
        store=store, documents=documents, table=args.table,
        dry_run=not args.apply,
    )

    print(f"renamed_docs: {result.renamed_docs}")
    print(f"changed_chunks: {result.changed_chunks}")
    print(f"chunk_count_before: {result.chunk_count_before}")
    print(f"chunk_count_after: {result.chunk_count_after}")
    for entry in result.doc_renames:
        print(f"  {entry['old_doc_id']} -> {entry['new_doc_id']} "
              f"({entry['old_family']} -> {entry['new_family']}, {entry['source_url']})")
    if result.reversal_path is not None:
        print(f"reversal record: {result.reversal_path}")

    if args.out is not None:
        _atomic_write_json(args.out, {
            "table": args.table,
            "dry_run": not args.apply,
            "scanned": result.scanned,
            "renamed_docs": result.renamed_docs,
            "changed_chunks": result.changed_chunks,
            "chunk_count_before": result.chunk_count_before,
            "chunk_count_after": result.chunk_count_after,
            "doc_renames": result.doc_renames,
            "chunk_id_pairs": result.chunk_id_pairs,
        })
        print(f"written: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
