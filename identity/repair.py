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

CORRECTION, 2026-08-16 — the first cut of this pass was dry-run against the
live corpus and proposed 4,355 changes where ~700 were expected. Full
write-up: `.superpowers/sdd/task-7-report.md`, "Repair-pass correction".
Five defects, each with its own guard below:

1. **Fiscal notes were never excluded** and 1,862 got rewritten — their
   titles have none of the three suppliers this module distrusts (see
   `identity/validator.py`'s module docstring). Filtered once, near the
   top, mirroring `eval/identity_check.py`.
2. **Corroboration used to accept ANY of a stamp's distinctive words**
   (`identity/compose.py`'s own copy, independently of and weaker than
   `eval/identity_check.py`'s already-fixed rule) — a page saying "medicine"
   "corroborated" the Board of Osteopathic Examiners. Both modules now share
   one LONGEST-word rule via `identity.validator.mentions_agency`.
3. **1,997 already-correctly-formatted titles were rewritten anyway.** A
   title that already validates, is already in the house format, is unique,
   and does not conflict with a genuinely corroborated stamp is now left
   alone before any composition is attempted at all — see the "Fix #3"
   guard inside `repair_titles` and `_stamp_genuinely_disagrees`.
4. **706 book-section documents (slug is a printed page code or a bare
   number, e.g. `bd2`, `531`) were renamed to an agency** because a table
   chunk inside them stamps dozens of agencies and `stamps[0]` picked one
   arbitrarily. A section is a chapter of a book, not an agency, and an
   arbitrary pick from ANY multi-agency stamp list — section or not — is
   never evidence. See `_resolve_trusted_stamp`.
5. **1,843 titles got a distinguisher appended with no real collision** —
   downstream of #4: many section documents composing to the same wrong,
   arbitrarily-picked agency name collided with EACH OTHER, and an
   already-correct sibling could be swept into that collision and mutated
   even though its own title was never going to change. The collision check
   now compares every candidate's proposed title against every OTHER budget
   document's FINAL title (composed if it's changing, current if it is
   not) — see the collision pass below.

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
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from identity.compose import compose_title, resolve_supplier_disagreement
from identity.validator import distinctive_words, mentions_agency, validate_name

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

# A book SECTION's slug — a printed page code (BD-13 -> "bd13", S-1 -> "s1")
# or a bare page number ("531") — never a real agency abbreviation. An
# agency's own slug is letters only ("bar", "ata") or has an internal
# sub-programme hyphen ("doa-apf"); neither shape matches this. Fix #4
# (module docstring): a section document is a chapter of a book, its own
# title IS the section name, and a stamp is never evidence for what to call
# it — matched against `_doc_id_slug(doc_id)`.
_SECTION_DOC_SLUG = re.compile(r"^(?:[a-z]{1,3}\d+|\d+)$")


@dataclass
class RepairResult:
    """`.changes` is the I8 reversal record; `.skipped` is why a document
    was left alone — an uncorroborated stamp, an unusable name, or one this
    pass simply cannot place a book for. `.fiscal_notes_excluded` is
    informational (fix #1) — how many documents this pass never looked at
    because they are out of scope, reported so the exclusion is VISIBLE
    rather than a silent filter nobody can see (mirrors
    `eval.identity_check.IdentityReport.fiscal_notes_excluded`)."""

    changes: list[dict[str, Any]] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    fiscal_notes_excluded: int = 0


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


def _stamp_genuinely_disagrees(
    supplied_name: str,
    stamps: Iterable[str],
    agency_names: Mapping[str, str],
    doc_text: str,
) -> bool:
    """Fix #3's extra guard: is there a stamp that BOTH names a different
    agency than the supplied title AND is corroborated by the document's
    own text? If not, a clean-looking title is not hiding a real defect.

    Scans EVERY stamp on the document, not just `stamps[0]` — the
    arbitrary-pick problem `_resolve_trusted_stamp` (fix #4) exists for
    applies here too, and a single genuinely-conflicting stamp anywhere in
    a long list is enough to prove the title wrong, even when most of the
    other stamps on the same document are irrelevant table noise. This is
    the one real defect class the audit found:
    `jlbc-approps-fy2011-ata`, titled "Administrative Hearings, Office of",
    is genuinely stamped AND corroborated as the Automobile Theft
    Authority — that must still repair even though its existing title is
    otherwise clean.
    """
    supplied_words = distinctive_words(supplied_name)
    for stamp_id in stamps:
        name = agency_names.get(stamp_id)
        if not name:
            continue
        if distinctive_words(name) & supplied_words:
            continue  # agrees with the supplied name — not a disagreement
        if mentions_agency(doc_text, name):
            return True
    return False


def _resolve_trusted_stamp(
    *,
    doc_id: str,
    stamps: list[str],
    agency_names: Mapping[str, str],
    doc_text: str,
    is_section_doc: bool,
) -> tuple[str | None, str | None]:
    """Which stamp, if any, may be composed into a title.

    Returns `(stamp_id, veto_reason)`. A non-`None` `veto_reason` means:
    skip this document ENTIRELY this pass — do not even attempt a
    format-only repair around the supplied name. This mirrors
    `repair_titles`'s existing "uncorroborated stamp" branch below, which
    already treats "the one witness available cannot be trusted" as a hard
    skip rather than a partial fix; an untrustworthy stamp here is the same
    shape of problem.

    Fix #4, two rules, both measured 2026-08-16 against the first dry run:

    1. A SECTION document — its slug is a printed page code (`bd2`, `s12`)
       or a bare page number (`531`), matched by `_SECTION_DOC_SLUG` — is a
       chapter of a book, not an agency. Its own title IS the section name.
       Never compose a name from a stamp for one, full stop. A table chunk
       inside a section like this often lists dozens of agencies, and the
       original pass took `stamps[0]` — an arbitrary pick, since stamps
       arrive from a `set` with no meaningful order — and renamed 706 such
       documents to whichever agency happened to come out first.
    2. More generally, an arbitrary pick from a MULTI-agency stamp list is
       never evidence, section document or not. A stamp is trusted only
       when it is the single stamp on the document, or when it is the ONE
       stamp — among several — that the document's own text corroborates.
       Two or more corroborated stamps, or none, means no stamp on this
       document is more trustworthy than any other, so none is used.
    """
    if not stamps:
        return None, None
    if is_section_doc:
        return None, (
            f"doc_id {doc_id!r} is a book section (its slug is a printed "
            "page code or a bare number, not an agency abbreviation) — its "
            "own title is already the section name, and an agency stamp is "
            "never evidence for what to rename a section to"
        )
    if len(stamps) == 1:
        return stamps[0], None
    corroborated = [
        s for s in stamps
        if agency_names.get(s) and mentions_agency(doc_text, agency_names[s])
    ]
    if len(corroborated) == 1:
        return corroborated[0], None
    return None, (
        f"document carries {len(stamps)} agency stamps and "
        f"{len(corroborated)} of them are corroborated by its own text — "
        "an arbitrary pick from a multi-agency stamp list is never "
        "evidence, so no stamp was trusted here"
    )


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

    # Fix #1: fiscal notes are OUT OF SCOPE. Their titles are built from the
    # bill number and the note's own heading, not from any of the three
    # suppliers this module distrusts, and the `<strike>…</strike> (NOW: …)`
    # form some of them carry is a deliberate rendered feature, not a naming
    # defect. Filtered ONCE here, near the top — mirrors
    # `eval/identity_check.py::check_corpus`'s identical exclusion so the
    # two tools never disagree about what is in scope. Measured 2026-08-16:
    # the unfiltered first dry run rewrote 1,862 fiscal notes.
    budget_documents = {
        doc_id: meta for doc_id, meta in documents.items()
        if (meta or {}).get("doc_type") != "fiscal-note"
    }
    result.fiscal_notes_excluded = len(documents) - len(budget_documents)

    # Fix #3's uniqueness check needs to know, up front, which CURRENT
    # titles are already unique across the (fiscal-note-excluded) corpus —
    # computed once here rather than per-document.
    title_counts = Counter(
        str((meta or {}).get("title") or "").strip()
        for meta in budget_documents.values()
    )

    candidates: dict[str, dict[str, Any]] = {}
    # Every budget doc_id whose (book, fiscal_year) bucket is known, whether
    # or not it ends up a candidate — the collision pass (fix #5) needs this
    # for EVERY document, because a document left alone still occupies a
    # title in its book/year that a genuinely-changing sibling must not
    # collide with.
    book_year_of: dict[str, tuple[str, int]] = {}

    for doc_id, meta in budget_documents.items():
        title = str((meta or {}).get("title") or "").strip()
        fiscal_year = (meta or {}).get("fiscal_year")
        stamps = list(stamps_by_doc.get(doc_id, ()) or ())
        doc_text = " \n".join(chunks_by_doc.get(doc_id, ()) or ())

        parsed = _parse_title(title)
        if parsed:
            supplied_name, book = parsed
        else:
            supplied_name, book = title, None
        if book is None:
            book = _book_from_doc_id(doc_id)

        if book is not None and isinstance(fiscal_year, int):
            book_year_of[doc_id] = (book, fiscal_year)

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

        # Fix #3: never touch a title that is already correct. Skipped
        # BEFORE this document is ever added to `candidates` — not just
        # skipped-at-the-end when composed==before — so it can never be
        # swept into fix #5's collision pass and mutated on some OTHER
        # document's behalf (the exact `jlbc-baseline-fy2023-oah` shape:
        # already-correct, unique, but caught a distinguisher anyway
        # because an unrelated section document was WRONGLY (pre-fix #4)
        # composing to the same name). All four conditions must hold:
        # the name validates, the title is ALREADY in the house format
        # (not merely composable into it), it is unique among budget
        # documents right now, and no corroborated stamp actually disputes
        # it (`_stamp_genuinely_disagrees` — the one real defect class,
        # e.g. `jlbc-approps-fy2011-ata`, must still repair).
        if (
            parsed is not None
            and validate_name(supplied_name).ok
            and title_counts.get(title, 0) == 1
            and not _stamp_genuinely_disagrees(
                supplied_name, stamps, agency_names, doc_text,
            )
        ):
            continue  # already correct — nothing to change or explain

        # Fix #4: which stamp, if any, may be trusted to compose a name
        # from. A section document, or a document whose several stamps are
        # not unambiguously resolvable, is vetoed here and skipped entirely
        # this pass — see `_resolve_trusted_stamp`.
        is_section_doc = bool(_SECTION_DOC_SLUG.match(_doc_id_slug(doc_id)))
        stamp_id, veto_reason = _resolve_trusted_stamp(
            doc_id=doc_id, stamps=stamps, agency_names=agency_names,
            doc_text=doc_text, is_section_doc=is_section_doc,
        )
        if veto_reason is not None:
            result.skipped.append({
                "doc_id": doc_id, "field": "title", "reason": veto_reason,
            })
            continue
        stamp_name = agency_names.get(stamp_id) if stamp_id else None

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

    # Fix #5 + collision pass. Two documents ending up with the identical
    # title inside the same (book, fiscal_year) are indistinguishable in
    # every list that groups by book and year — a NEW defect this repair
    # would manufacture if left alone (measured: 77 real parent/sub-programme
    # pairs, e.g. `doa` alongside `doa-apf`).
    #
    # `final_title` is what EVERY budget document's title will read as after
    # this pass — the composed candidate for a document that is changing,
    # the untouched current title for one that is not (whether it was never
    # a candidate at all, or was one whose composed title happened to equal
    # its current title). Comparing against this full map, not just against
    # `candidates`, is what fix #5 is: an already-correct sibling (fix #3)
    # must still be visible here so a genuinely-changing document can avoid
    # colliding with it, but that sibling itself must never gain a
    # distinguisher just because it was named in someone else's collision.
    final_title: dict[str, str] = {}
    for doc_id, meta in budget_documents.items():
        if doc_id in candidates:
            final_title[doc_id] = candidates[doc_id]["composed"]
        else:
            final_title[doc_id] = str((meta or {}).get("title") or "").strip()

    groups: dict[tuple[str, int], list[str]] = defaultdict(list)
    for doc_id, key in book_year_of.items():
        groups[key].append(doc_id)

    for (book, fiscal_year), doc_ids in groups.items():
        by_title: dict[str, list[str]] = defaultdict(list)
        for doc_id in doc_ids:
            by_title[final_title[doc_id]].append(doc_id)
        for composed_title, members in by_title.items():
            if len(members) < 2:
                continue
            for doc_id in members:
                # Only a CANDIDATE — a document actually changing this pass
                # — may gain a distinguisher. A member that is here only to
                # be seen (its title is staying exactly as-is) is never
                # touched, by construction: it was never added to
                # `candidates` in the first place.
                if doc_id not in candidates:
                    continue
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
    print(f"fiscal notes excluded (out of scope): {result.fiscal_notes_excluded}")
    if args.out is not None:
        print(f"written: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
