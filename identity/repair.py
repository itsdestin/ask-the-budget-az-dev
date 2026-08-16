"""Repair stored titles — a documents.json edit, nothing more (spec I7).

The title is NOT a chunk column. `store/schema.py` carries `doc_id`,
`agency_canonical_ids`, `fiscal_year`, `doc_type`, `publisher`,
`section_path` and the fund fields — `title` lives only in
`documents.json`. So this pass:

* takes **no ingest lock** (`ingest.lock`) — nothing here writes a chunk row,
  and the lock exists to serialize writers of the LanceDB tables;
* takes **no snapshot** (`store.backup.snapshot()`) — that snapshots the
  whole corpus (LanceDB + documents.json together) for a write that touches
  neither the schema nor a chunk_id, at a real cost (STATUS.md: 3.5+ minutes
  on the live corpus, holding the ingest lock the whole time). The reversal
  record this module writes on every apply IS this pass's undo path (spec
  I8) — a snapshot would duplicate that at the wrong price;
* **never calls `upsert_chunks`** — there is no chunk being rewritten, and a
  document's chunk_ids are completely unaffected by its title changing.

A reviewer familiar with `ingest/driver.py` will expect all three by
analogy. They would be wrong here — this module edits one sidecar file, not
the corpus. The doc_id rename and the re-stamp (a later unit) DO touch
chunk_ids and DO need those hazards handled; title repair does not.

`repair_titles()` is a pure function of its arguments plus, when
`dry_run=False`, two file writes: the repaired `documents.json` (via
`store.config.write_documents_sidecar`, which already does tmp+`os.replace`)
and a reversal record at `<data_dir>/identity-repairs-<UTC>.json` carrying
one row per change (`doc_id`, `field`, `before`, `after`, `reason`) — enough
for a human to revert any single title, or all of them, without restoring a
backup. Nothing is written when `dry_run=True`: the CLI's `--out` flag is
what lets a dry run be inspected on disk, and that write belongs to `main()`,
not to this function — so five tests can call `repair_titles(..., dry_run=True)`
with no `JLBC_DATA_DIR` set and never touch the real corpus.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from collections import defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from identity.compose import compose_title, resolve_supplier_disagreement

# The composed format is `{name} — FY {year} {book}` (identity/compose.py).
# Splitting an EXISTING title on this pattern recovers the "book" text
# (`"Appropriations Report"`, `"Baseline"`, ...) so a document that is
# already correctly formatted, just wrongly NAMED, gets its book preserved
# exactly rather than re-guessed.
_TITLE_FORMAT = re.compile(r"^(.+?) — FY \d{4} (.+)$")

# Fallback for the 131 titles the audit found outside the format entirely
# (no " — FY YYYY <book>" suffix to read a book from at all — e.g. "ADOA").
# Keyed on the doc_id FAMILY prefix that `ingest/lance_writer.py::make_doc_id`
# mints, which is the one piece of book identity that survives even a
# completely mangled title. Order matters: longer/more specific prefixes
# first, since e.g. every jlbc- id also starts with a bare letter run.
_BOOK_BY_DOC_ID_FAMILY = (
    ("jlbc-approps-", "Appropriations Report"),
    ("jlbc-baseline-", "Baseline"),
    ("agao-afr-", "Annual Financial Report"),
    ("governor-", "Executive Budget"),
    ("legislature-", "Budget Bill"),
)

# The document-specific tail of a doc_id (e.g. "doa-apf" out of
# "jlbc-approps-fy2016-doa-apf"), used as `compose_title`'s `distinguisher`
# when two documents in the same (book, fiscal_year) would otherwise compose
# to the identical name — the parent-agency / sub-programme collision spec
# I5 exists for (77 real pairs, e.g. `doa` alongside `doa-apf`).
_DOC_ID_TAIL = re.compile(r"fy\d{4}-(.+)$")


@dataclass
class RepairResult:
    """`.changes` is the I8 reversal record; `.skipped` is why a document
    was left alone — an uncorroborated stamp, an unusable name, or one this
    pass simply cannot place a book for."""

    changes: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)


def _parse_title(title: str) -> tuple[str, str] | None:
    """Split a well-formed title into (name, book); None if it never had
    the shape at all (the whole string then becomes the "supplied" witness)."""
    match = _TITLE_FORMAT.match(title.strip())
    if not match:
        return None
    return match.group(1).strip(), match.group(2).strip()


def _book_from_doc_id(doc_id: str) -> str | None:
    for prefix, book in _BOOK_BY_DOC_ID_FAMILY:
        if doc_id.startswith(prefix):
            return book
    return None


def _doc_id_slug(doc_id: str) -> str:
    match = _DOC_ID_TAIL.search(doc_id)
    return match.group(1) if match else doc_id


def _atomic_write_json(path: Path, payload: Any) -> None:
    """tmp + `os.replace`, same recipe as `store.config.write_documents_sidecar` —
    a reader on the share must never catch a half-written reversal record."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)


def repair_titles(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    chunks_by_doc: Mapping[str, Iterable[str]],
    agency_names: Mapping[str, str],
    stamps_by_doc: Mapping[str, Iterable[str]],
    dry_run: bool = True,
) -> RepairResult:
    result = RepairResult()
    # Deep copy: `documents` is caller-owned (the CLI hands it a fresh
    # `load_documents()` result, but tests reuse one module-level fixture
    # dict across several test functions) — mutating it in place would leak
    # a "repaired" title into a later, unrelated test.
    updated: dict[str, dict[str, Any]] = deepcopy(dict(documents))

    candidates: dict[str, dict[str, Any]] = {}

    for doc_id, meta in documents.items():
        title = str((meta or {}).get("title") or "").strip()
        fiscal_year = (meta or {}).get("fiscal_year")
        # WHICH stamp is "the" stamp when a document carries several is an
        # open question this pass inherits rather than answers — the same
        # `stamps[0]` choice `eval/identity_check.py` already makes when it
        # reports `title-wrong-agency` findings, kept identical so the two
        # tools never disagree about which document a fix does or doesn't
        # cover.
        stamps = list(stamps_by_doc.get(doc_id, ()) or ())
        stamp_id = stamps[0] if stamps else None
        stamp_name = agency_names.get(stamp_id) if stamp_id else None
        doc_text = " \n".join(chunks_by_doc.get(doc_id, ()) or ())

        parsed = _parse_title(title)
        if parsed:
            supplied_name, book = parsed
        else:
            supplied_name, book = title, None
        if book is None:
            book = _book_from_doc_id(doc_id)

        if not supplied_name:
            result.skipped.append({
                "doc_id": doc_id, "field": "title",
                "reason": "no existing title to repair from",
            })
            continue
        if book is None:
            result.skipped.append({
                "doc_id": doc_id, "field": "title",
                "reason": (
                    "could not determine the book — the title has no "
                    "' — FY YYYY <book>' suffix to read one from, and the "
                    f"doc_id {doc_id!r} names no recognised book family"
                ),
            })
            continue
        if not isinstance(fiscal_year, int):
            result.skipped.append({
                "doc_id": doc_id, "field": "title",
                "reason": "no fiscal_year on record to compose a title with",
            })
            continue

        chosen_name, note = resolve_supplier_disagreement(
            supplied=supplied_name, stamp_name=stamp_name, doc_text=doc_text,
        )

        if note is not None and chosen_name == supplied_name:
            # resolve_supplier_disagreement's "left unchanged" branch: the
            # stamp disagrees with the supplied name but the document's own
            # text does not corroborate the stamp either — one uncorroborated
            # witness is exactly today's bug (spec I1: two witnesses
            # required), so nothing here is trustworthy enough to compose
            # from. Leave the document alone entirely rather than just
            # reformatting around the unchanged (equally unverified) name.
            result.skipped.append({
                "doc_id": doc_id, "field": "title", "reason": note,
            })
            continue

        try:
            composed = compose_title(
                name=chosen_name, fiscal_year=fiscal_year, book=book,
            )
        except ValueError as err:
            result.skipped.append({
                "doc_id": doc_id, "field": "title",
                "reason": f"composed name rejected: {err}",
            })
            continue

        candidates[doc_id] = {
            "title": title, "book": book, "fiscal_year": fiscal_year,
            "chosen_name": chosen_name, "note": note, "composed": composed,
        }

    # Collision pass. Two documents composing to the identical title inside
    # the same (book, fiscal_year) are indistinguishable in every list that
    # groups by book and year — a NEW defect this repair would manufacture
    # if left alone (measured: 77 real parent/sub-programme pairs). Grouped
    # by the composed CANDIDATE, not by agency id, because that is the
    # actual collision surface: two different stamps that both resolve to
    # the same displayed name are exactly as indistinguishable as one stamp
    # shared by two documents.
    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for doc_id, candidate in candidates.items():
        groups[(candidate["book"], candidate["fiscal_year"])].append(doc_id)

    for (book, fiscal_year), doc_ids in groups.items():
        by_title: dict[str, list[str]] = defaultdict(list)
        for doc_id in doc_ids:
            by_title[candidates[doc_id]["composed"]].append(doc_id)
        for composed_title, members in by_title.items():
            if len(members) < 2:
                continue
            for doc_id in members:
                candidate = candidates[doc_id]
                slug = _doc_id_slug(doc_id)
                others = ", ".join(m for m in members if m != doc_id)
                try:
                    recomposed = compose_title(
                        name=candidate["chosen_name"], fiscal_year=fiscal_year,
                        book=book, distinguisher=slug,
                    )
                except ValueError as err:
                    result.skipped.append({
                        "doc_id": doc_id, "field": "title",
                        "reason": (
                            f"would collide with {others} in the {book} "
                            f"FY {fiscal_year} book, and its own doc_id "
                            f"{slug!r} is not a usable distinguisher: {err}"
                        ),
                    })
                    del candidates[doc_id]
                    continue
                collision_note = (
                    "composing from the agency name alone would have "
                    f"produced the same title as {others} in the {book} "
                    f"FY {fiscal_year} book — disambiguated with the "
                    f"document's own id, {slug!r}"
                )
                candidate["composed"] = recomposed
                candidate["note"] = (
                    f"{candidate['note']}; {collision_note}"
                    if candidate["note"] else collision_note
                )

    for doc_id, candidate in candidates.items():
        before = candidate["title"]
        after = candidate["composed"]
        if after == before:
            continue  # already correct — nothing to change or explain
        reason = candidate["note"] or (
            "title did not match the standard "
            "'{name} — FY {year} {book}' format — recomposed from the "
            "corroborated agency stamp"
        )
        result.changes.append({
            "doc_id": doc_id, "field": "title",
            "before": before, "after": after, "reason": reason,
        })
        updated[doc_id]["title"] = after

    if not dry_run:
        # Both writes only ever happen here, gated on dry_run=False — every
        # dry-run test above calls this function with no JLBC_DATA_DIR set,
        # and `data_dir()` would otherwise resolve to (and create) the real
        # repo corpus directory just by being called.
        from store.config import data_dir, write_documents_sidecar

        write_documents_sidecar(updated)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
        _atomic_write_json(
            data_dir() / f"identity-repairs-{stamp}.json",
            {"changes": result.changes, "skipped": result.skipped},
        )

    return result


def _load_live_inputs():
    """Assemble `repair_titles`' arguments from the real corpus.

    Mirrors `eval/identity_check.py::_load_live` deliberately — the two
    tools must see identical stamping and chunk data, or a document could
    show as a defect in the report and be untouched by the repair (or vice
    versa) for no reason a human could find. Not unit-tested: this is I/O
    (opens LanceDB), and `store.chunk_store` / `chunking.agency_catalog` are
    imported here, inside the function, rather than at module scope — the
    thing the CLAUDE.md test rule protects is exactly this: `tests/` may
    never end up loading a real database just because it imported this file.
    """
    from chunking.agency_catalog import id_to_name
    from store.chunk_store import ChunkStore
    from store.documents import load_documents

    documents = load_documents()
    chunk_store = ChunkStore()
    chunks_by_doc: dict[str, list[str]] = defaultdict(list)
    stamps_by_doc: dict[str, set[str]] = defaultdict(set)
    for row in chunk_store.scan(
        "budget_chunks", ["doc_id", "text", "agency_canonical_ids"]
    ):
        chunks_by_doc[row["doc_id"]].append(row.get("text") or "")
        for agency_id in row.get("agency_canonical_ids") or []:
            stamps_by_doc[row["doc_id"]].add(agency_id)

    return documents, chunks_by_doc, id_to_name(), stamps_by_doc


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="compute changes and print counts; write nothing",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help="write the repaired documents.json and the reversal record",
    )
    ap.add_argument(
        "--out", type=Path, default=None,
        help="also dump {changes, skipped} as JSON to this path, for either mode",
    )
    ap.add_argument(
        "--data-dir", type=Path, default=None,
        help="override JLBC_DATA_DIR for this run",
    )
    args = ap.parse_args(argv)

    if args.data_dir is not None:
        os.environ["JLBC_DATA_DIR"] = str(args.data_dir)

    documents, chunks_by_doc, agency_names, stamps_by_doc = _load_live_inputs()
    result = repair_titles(
        documents=documents, chunks_by_doc=chunks_by_doc,
        agency_names=agency_names, stamps_by_doc=stamps_by_doc,
        dry_run=not args.apply,
    )

    if args.out is not None:
        _atomic_write_json(
            args.out, {"changes": result.changes, "skipped": result.skipped},
        )

    print(f"changes: {len(result.changes)}")
    print(f"skipped: {len(result.skipped)}")
    if args.out is not None:
        print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
