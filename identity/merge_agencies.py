"""Apply `identity.merge_map.MERGE_MAP` to the corpus: rewrite
`agency_canonical_ids`, replacing a merged-away id with its target and
de-duplicating (spec I9).

This is a SIBLING pass to `identity/relabel.py`, not a rewrite of it and
not an extension of it -- `identity/relabel.py` is owned by other work in
this plan (Tasks 7 and 9 both touch it) and must not be edited here. What
this module does instead is import `identity.relabel`'s already-tested
write machinery (`_ALL_COLUMNS`, `_write_changed_rows`,
`_verify_nothing_was_lost`, `_default_snapshot_and_verify`,
`_atomic_write_json`, `DEFAULT_BATCH_SIZE`) rather than writing a second
copy of the lock -> snapshot -> batch -> verify -> reversal shape. Every
trap that module's own docstring names (vector column invisibility,
`upsert_chunks`' two-commit delete-then-add, "a matching row count proves
nothing") applies unchanged here, because the underlying write call is the
identical one.

## The guard, CORRECTED: same-name first, co-occurrence as the fallback

**A first version of this pass gated every pair on co-occurrence alone,
and that was the wrong test for most of `MERGE_MAP`.** The controller
compared canonical names (`samples/entity-catalog.yaml`) across all nine
entries and found ALL NINE share the same name as a sorted token multiset
-- `agency:cs` "Child Safety, Department of" and `agency:dcs` "Child
Safety, Department of" are not two units that happen to overlap, they are
ONE catalog entry recorded twice under two ids. Co-occurrence between two
ids naming the identical agency is EXPECTED (both get stamped in the same
fiscal year by construction), not evidence against merging them. Under
co-occurrence alone, five of nine entries were wrongly refused; under the
corrected two-stage guard below, all nine clear (see the task-8 report and
`identity/merge_map.py`'s docstring for the full per-pair evidence).

The guard is now, in order, per pair:

1. **`same_name_pairs`** -- do the old and target ids' canonical names
   (`chunking.agency_catalog.id_to_name()`) match as a sorted, casefolded,
   punctuation-stripped token multiset? If so the pair is safe
   UNCONDITIONALLY, regardless of what co-occurrence would say -- the
   catalog writes the same agency both ways round ("Child Safety,
   Department of" / "Department of Child Safety" is the recorded example;
   this is the identical normalization the query side already applies,
   per STATUS.md's query-understanding section).
2. **Co-occurrence, as the FALLBACK** -- only reached when the names
   genuinely differ. This is the rename-vs-parallel-units case the
   original guard was built for, and it is still exactly right there: two
   ids that alternate across years are one agency renamed (safe); two ids
   that run in parallel every year are two real units, and merging them
   destroys information (see `identity/merge_map.py`'s docstring for the
   ASU-vs-University-of-Arizona evidence this rule is built on).
3. A pair that fails both is refused and reported -- never silently
   dropped.

`check_cooccurrence` answers step 2 per pair from a plain iterable of rows
carrying `agency_canonical_ids` and `fiscal_year` -- no store, no lock, safe
to run read-only and as often as needed. It is scoped to each chunk's
PRIMARY (index-0) agency id, not every id the chunk carries. That choice is
load-bearing, not incidental:

`chunking/entity_stamper.py`'s `resolve_all` (decision D2) returns every
catalog name it finds inside a TABLE chunk, with the chunk's own scalar
resolution pinned first. A single statewide comparison table names dozens
of agencies in one chunk, and those tables exist in essentially every
fiscal year's book. Measured against the live corpus: scoping to ALL ids a
chunk carries makes `agency:cna` -> `agency:cet` -- FY2011-2019 then
FY2020-2027 in the PRIMARY view, a clean, contiguous, zero-overlap rename
-- register as overlapping in eight separate years, entirely from stray
table mentions, which would have blocked a genuinely safe merge for no
real reason. The PRIMARY id is what D2 itself treats as "this chunk is
ABOUT this agency"; a table's other mentions are co-references, not
ownership, and the guard needs ownership. The same PRIMARY scoping
correctly flags the University of Arizona negative control (Main Campus vs
Health Sciences Center) as full-overlap across all 23 corpus years --
proof the scoping is discriminating real parallel units, not just hiding
them. `same_name_pairs` correctly does NOT clear that same negative
control -- "University of Arizona - Main Campus" and "University of
Arizona - Health Sciences Center" are genuinely different names, so it
falls straight through to the co-occurrence fallback, which still refuses
it.

`check_merge_guard` runs both stages and returns one `PairCooccurrence`
per pair, same shape either way, so `merge_agencies()` and its callers
don't need to know which stage cleared (or refused) a given pair.
`merge_agencies()` never silently drops an unsafe pair from the merge it
runs -- it computes `check_merge_guard` itself (over the same rows it just
scanned, so no second corpus read), excludes only the pairs the guard
flags from the write, and reports every excluded pair on `MergeResult.
excluded_pairs` and via `progress()`, loudly, in both dry-run and apply
mode. The full nine-entry `MERGE_MAP` stays the input; what changes size is
the EFFECTIVE map actually applied.
"""
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

from identity.merge_map import MERGE_MAP
from identity.relabel import (
    _ALL_COLUMNS,
    _atomic_write_json,
    _default_snapshot_and_verify,
    _verify_nothing_was_lost,
    _write_changed_rows,
    DEFAULT_BATCH_SIZE,
    ChunkStoreLike,
)
from ingest.lock import IngestLock


def _default_progress(message: str) -> None:
    import sys

    print(f"identity.merge_agencies: {message}", file=sys.stderr, flush=True)


@dataclass(frozen=True)
class PairCooccurrence:
    """Whether one `MERGE_MAP` entry is safe to apply, and the evidence."""

    old_id: str
    target_id: str
    safe: bool
    overlapping_years: tuple[int, ...]


def check_cooccurrence(
    rows: Iterable[Mapping[str, Any]],
    merge_map: Mapping[str, str] = MERGE_MAP,
) -> dict[str, PairCooccurrence]:
    """For every `(old_id -> target_id)` entry in `merge_map`, do the two ids
    ever both appear as a chunk's PRIMARY agency label in the same fiscal
    year? Returns one `PairCooccurrence` per entry, keyed by `old_id`.

    `rows` needs only `agency_canonical_ids` and `fiscal_year` -- callers
    scanning the live corpus should request exactly those two columns
    (see `identity/label_audit.py::load_live` for the same pattern), and
    tests build them directly with no store at all. A row with an empty
    `agency_canonical_ids` or a missing `fiscal_year` contributes nothing
    (an unlabelled or undated chunk cannot evidence a co-occurrence in
    either direction), rather than raising -- the live corpus does have
    both shapes and a read-only report must not crash on them.
    """
    years_by_primary: dict[str, set[int]] = {}
    for row in rows:
        ids = row.get("agency_canonical_ids") or []
        fy = row.get("fiscal_year")
        if not ids or fy is None:
            continue
        primary = ids[0]
        years_by_primary.setdefault(primary, set()).add(fy)

    result: dict[str, PairCooccurrence] = {}
    for old_id, target_id in merge_map.items():
        overlap = tuple(sorted(
            years_by_primary.get(old_id, set())
            & years_by_primary.get(target_id, set())
        ))
        result[old_id] = PairCooccurrence(
            old_id=old_id, target_id=target_id,
            safe=not overlap, overlapping_years=overlap,
        )
    return result


def safe_merge_map(
    cooccurrence: Mapping[str, PairCooccurrence],
    merge_map: Mapping[str, str] = MERGE_MAP,
) -> dict[str, str]:
    """`merge_map` restricted to the entries `check_cooccurrence` cleared.

    A pair with no entry in `cooccurrence` at all is excluded, not assumed
    safe -- the only source of "safe" is a check that actually ran."""
    return {
        old_id: target_id
        for old_id, target_id in merge_map.items()
        if cooccurrence.get(old_id) is not None and cooccurrence[old_id].safe
    }


# Casefold, then keep only alnum runs -- punctuation (commas, apostrophes,
# hyphens) never survives comparison, so "Governor's Office of" and
# "Governors Office, of" tokenize identically.
_WORD_RE = re.compile(r"[a-z0-9]+")


def _normalized_name_tokens(name: str) -> tuple[str, ...]:
    """A canonical name as a SORTED token multiset, so word order doesn't
    matter either. "Child Safety, Department of" and "Department of Child
    Safety" are the catalog's own two ways of printing one agency --
    verified against `samples/entity-catalog.yaml` (2026-08-16): every one
    of `MERGE_MAP`'s nine old/target pairs produces the identical tuple
    here. This mirrors the query-side normalization already shipped for
    agency aliasing (STATUS.md, query-understanding section) rather than
    inventing a second dialect of "the same name"."""
    return tuple(sorted(_WORD_RE.findall(name.casefold())))


def same_name_pairs(
    merge_map: Mapping[str, str], id_to_name: Mapping[str, str]
) -> set[str]:
    """`old_id`s whose canonical name matches their target's name as a
    sorted token multiset -- i.e. the catalog records ONE agency twice
    under two ids, not two units that happen to co-occur.

    This is the PRIMARY guard (see the module docstring): a same-named
    pair is safe regardless of co-occurrence, because co-occurrence
    between two ids naming the identical agency is expected, not evidence
    against merging. A pair is never assumed same-named on missing
    evidence -- an id absent from `id_to_name` (a catalog gap) is excluded
    here and falls through to the co-occurrence fallback instead."""
    matches: set[str] = set()
    for old_id, target_id in merge_map.items():
        old_name = id_to_name.get(old_id)
        target_name = id_to_name.get(target_id)
        if not old_name or not target_name:
            continue
        if _normalized_name_tokens(old_name) == _normalized_name_tokens(target_name):
            matches.add(old_id)
    return matches


def check_merge_guard(
    rows: Iterable[Mapping[str, Any]],
    merge_map: Mapping[str, str] = MERGE_MAP,
    id_to_name: Mapping[str, str] | None = None,
) -> dict[str, PairCooccurrence]:
    """The guard `merge_agencies()` actually applies: `same_name_pairs`
    first, `check_cooccurrence` as the fallback for pairs whose names
    genuinely differ. Returns one `PairCooccurrence` per `merge_map` entry
    -- callers (and the report they print) don't need to know which stage
    decided a given pair, only whether it's safe and, if not, why.

    `id_to_name` defaults to the real catalog (`chunking.agency_catalog.
    id_to_name()`, a committed YAML file, not a database or a model) when
    not given -- lazily imported so importing this module never reads it,
    and tests can inject a synthetic mapping to isolate one guard stage
    from the other without touching the live catalog.

    `rows` is consumed once by `check_cooccurrence` internally; pass a
    list (not a one-shot generator) if the caller also needs it again
    afterward -- `merge_agencies()` does exactly that."""
    if id_to_name is None:
        from chunking.agency_catalog import id_to_name as _load_id_to_name

        id_to_name = _load_id_to_name()

    same_name = same_name_pairs(merge_map, id_to_name)
    cooccurrence = check_cooccurrence(rows, merge_map)

    result: dict[str, PairCooccurrence] = {}
    for old_id, target_id in merge_map.items():
        if old_id in same_name:
            result[old_id] = PairCooccurrence(
                old_id=old_id, target_id=target_id,
                safe=True, overlapping_years=(),
            )
        else:
            result[old_id] = cooccurrence[old_id]
    return result


def _merge_labels(
    old_labels: Iterable[str], merge_map: Mapping[str, str]
) -> list[str]:
    """Replace every merged-away id with its target, preserving first-seen
    order and de-duplicating -- a chunk carrying both `agency:doa-cfs` and
    `agency:dcs` already (two ids, one of which happens to already be the
    target) must not end up with `agency:dcs` listed twice."""
    new_labels: list[str] = []
    seen: set[str] = set()
    for agency_id in old_labels:
        replacement = merge_map.get(agency_id, agency_id)
        if replacement not in seen:
            seen.add(replacement)
            new_labels.append(replacement)
    return new_labels


def _compute_merge_changes(
    rows: list[dict[str, Any]],
    effective_map: Mapping[str, str],
) -> list[tuple[dict[str, Any], list[str], list[str]]]:
    """Every row whose labels actually change under `effective_map`. Mirrors
    `identity.relabel._compute_changes`'s return shape exactly (`(row,
    old_labels, new_labels)` triples) so `_write_changed_rows` and
    `_verify_nothing_was_lost`, both imported unmodified from that module,
    work on this pass's output with no adapter."""
    changes: list[tuple[dict[str, Any], list[str], list[str]]] = []
    for row in rows:
        old_labels = list(row.get("agency_canonical_ids") or [])
        new_labels = _merge_labels(old_labels, effective_map)
        if new_labels != old_labels:
            changes.append((row, old_labels, new_labels))
    return changes


@dataclass
class MergeResult:
    changed: int
    chunk_count_before: int
    chunk_count_after: int
    reversal: list[dict[str, Any]] = field(default_factory=list)
    scanned: int = 0
    snapshot_name: str | None = None
    reversal_path: Path | None = None
    # The map actually applied, after excluding any pair the co-occurrence
    # guard flagged. A caller diffing this against MERGE_MAP sees exactly
    # what got left out and why (via excluded_pairs).
    effective_merge_map: dict[str, str] = field(default_factory=dict)
    excluded_pairs: list[PairCooccurrence] = field(default_factory=list)


def _report_excluded(
    excluded: list[PairCooccurrence], progress: Callable[[str], None]
) -> None:
    for pair in excluded:
        progress(
            f"REFUSING to merge {pair.old_id} -> {pair.target_id}: both ids "
            f"label a chunk's PRIMARY agency in the same fiscal year(s) "
            f"{list(pair.overlapping_years)}. This looks like two real "
            "units running in parallel, not a rename -- left unmerged for "
            "a human decision."
        )


def merge_agencies(
    *,
    store: ChunkStoreLike,
    merge_map: Mapping[str, str] = MERGE_MAP,
    table: str = "budget_chunks",
    dry_run: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock: IngestLock | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
    id_to_name: Mapping[str, str] | None = None,
) -> MergeResult:
    """Merge split agency ids onto their target, excluding any pair the
    guard flags -- same-name first, co-occurrence as the fallback for
    pairs whose names genuinely differ (see the module docstring for why
    co-occurrence alone was the wrong test for most of `MERGE_MAP`). Same
    `dry_run` asymmetry as `identity.relabel.relabel_corpus` and for the
    identical reason: a dry run is a pure reader (no lock, no snapshot, no
    write) so it can be re-run against the live corpus by hand as many
    times as needed before anyone approves an apply; `dry_run=False` is
    operationally an ingest (lock -> snapshot+verify -> scan -> merge ->
    write batched -> verify -> reversal record), because `upsert_chunks`
    is a delete-then-add across two LanceDB commits.

    `id_to_name` defaults to the real catalog when not given (see
    `check_merge_guard`); tests pass an explicit mapping (including `{}`
    to isolate the co-occurrence fallback with no name offered for either
    id).
    """
    progress = progress or _default_progress

    if dry_run:
        rows = store.scan(table, _ALL_COLUMNS)
        cooccurrence = check_merge_guard(rows, merge_map, id_to_name)
        effective_map = safe_merge_map(cooccurrence, merge_map)
        excluded = [p for p in cooccurrence.values() if not p.safe]
        _report_excluded(excluded, progress)
        changes = _compute_merge_changes(rows, effective_map)
        reversal = [
            {"doc_id": row["doc_id"], "chunk_id": row["chunk_id"],
             "before": old, "after": new}
            for row, old, new in changes
        ]
        return MergeResult(
            changed=len(changes),
            chunk_count_before=len(rows),
            chunk_count_after=len(rows),
            reversal=reversal,
            scanned=len(rows),
            effective_merge_map=effective_map,
            excluded_pairs=excluded,
        )

    # --- apply: lock -> snapshot+verify -> scan -> merge -> write -> verify -> reversal ---
    if lock is None:
        lock = IngestLock()

    with lock:
        lock.heartbeat()
        progress("acquired the ingest lock -- taking a corpus snapshot")
        snapshot_name = (snapshot_and_verify or _default_snapshot_and_verify)()
        lock.heartbeat()

        before_rows = store.scan(table, _ALL_COLUMNS)
        progress(f"scanned {len(before_rows)} rows from {table!r}")

        cooccurrence = check_merge_guard(before_rows, merge_map, id_to_name)
        effective_map = safe_merge_map(cooccurrence, merge_map)
        excluded = [p for p in cooccurrence.values() if not p.safe]
        _report_excluded(excluded, progress)

        changes = _compute_merge_changes(before_rows, effective_map)
        progress(f"{len(changes)} rows will change under the safe map")
        lock.heartbeat()

        _write_changed_rows(store, table, changes, batch_size, progress)
        lock.heartbeat()

        changed_ids = {row["chunk_id"] for row, _old, _new in changes}
        after_rows = _verify_nothing_was_lost(
            store, table, before_rows, changed_ids, progress,
        )

        reversal = [
            {"doc_id": row["doc_id"], "chunk_id": row["chunk_id"],
             "before": old, "after": new}
            for row, old, new in changes
        ]
        if reversal_dir is None:
            from store.config import data_dir as _resolve_data_dir

            reversal_dir = _resolve_data_dir()
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        reversal_path = reversal_dir / f"agency-merge-reversal-{stamp}.json"
        _atomic_write_json(reversal_path, {
            "table": table,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot_name,
            "merge_map": dict(merge_map),
            "effective_merge_map": effective_map,
            "excluded_pairs": [
                {"old_id": p.old_id, "target_id": p.target_id,
                 "overlapping_years": list(p.overlapping_years)}
                for p in excluded
            ],
            "scanned": len(before_rows),
            "changed": len(changes),
            "changes": reversal,
        })
        progress(f"reversal record written: {reversal_path}")

        return MergeResult(
            changed=len(changes),
            chunk_count_before=len(before_rows),
            chunk_count_after=len(after_rows),
            reversal=reversal,
            scanned=len(before_rows),
            snapshot_name=snapshot_name,
            reversal_path=reversal_path,
            effective_merge_map=effective_map,
            excluded_pairs=excluded,
        )


def _load_live_store() -> ChunkStoreLike:
    """I/O only -- never imported at module scope, so importing
    `identity.merge_agencies` (as every test in this suite does) can never
    open a real LanceDB table just by being imported."""
    from store.chunk_store import ChunkStore

    return ChunkStore()


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m identity.merge_agencies --dry-run | --apply`."""
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
                     help="corpus table to merge (default: budget_chunks)")
    ap.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    ap.add_argument("--out", type=Path, default=None,
                     help="also dump the result as JSON to this path")
    ap.add_argument("--data-dir", type=Path, default=None,
                     help="override JLBC_DATA_DIR for this run")
    args = ap.parse_args(argv)

    if args.data_dir is not None:
        os.environ["JLBC_DATA_DIR"] = str(args.data_dir)

    store = _load_live_store()
    result = merge_agencies(
        store=store, table=args.table, dry_run=not args.apply,
        batch_size=args.batch_size,
    )

    print(f"scanned: {result.scanned}")
    print(f"changed: {result.changed}")
    print(f"chunk_count_before: {result.chunk_count_before}")
    print(f"chunk_count_after: {result.chunk_count_after}")
    print(f"effective_merge_map: {result.effective_merge_map}")
    if result.excluded_pairs:
        print(f"excluded pairs ({len(result.excluded_pairs)}):")
        for pair in result.excluded_pairs:
            print(f"  {pair.old_id} -> {pair.target_id}: "
                  f"overlaps in {list(pair.overlapping_years)}")
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
            "effective_merge_map": result.effective_merge_map,
            "excluded_pairs": [
                {"old_id": p.old_id, "target_id": p.target_id,
                 "overlapping_years": list(p.overlapping_years)}
                for p in result.excluded_pairs
            ],
            "reversal": result.reversal,
        })
        print(f"written: {args.out}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
