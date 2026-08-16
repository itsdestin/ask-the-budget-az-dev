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

CORRECTION 2, 2026-08-16 (same day, after the corpus was re-labelled and a
fresh dry run — with the corpus's own labels now good, 962 -> 171 wrong
labels — proposed 733 changes). Two more defects, see "Label-selection fix"
in `.superpowers/sdd/task-7-report.md` for the full record:

6. **A minority label could outrank the document's own URL slug.**
   `jlbc-baseline-fy2021-nav` carries `agency:nav` ("Navigable Stream
   Adjudication Commission, Arizona") on 7 of its passages and `agency:wat`
   ("Water Resources, Department of") on 1 — and its own filename,
   `nav.pdf`, names `agency:nav` directly. The old multi-stamp rule trusted
   whichever single stamp `mentions_agency` happened to corroborate, and a
   generic 2-word agency name corroborates far more easily (1 word needed)
   than a specific 3-word one (2 of 3 needed) — so a single incidental
   "water" mention beat the document's own majority label and its own
   filename. `_resolve_trusted_stamp` now ranks candidates BEFORE asking
   `mentions_agency` anything: the document's own URL slug first (it is
   JLBC's own filename for the page — the strongest witness in the whole
   system), then the label carried by strictly more passages than every
   other, and only skips (never guesses) when neither breaks the tie. The
   textual-corroboration guard still runs, unchanged, downstream in
   `resolve_supplier_disagreement` — it decides whether the resolved stamp
   may override a SUPPLIED title, which is a different question from which
   stamp is the document's own.
7. **A legacy `JLBC FY<year> — ` prefix was kept and a house-format suffix
   added on top of it**, doubling the year and leaving the original stray
   bullet/dot-leaders in place: `jlbc-baseline-fy2027-s1` composed to
   `"JLBC FY2027 — • Statement of General Fund Revenues and Expenditures —
   FY 2027 Baseline"`. ~375 documents carry this older format, which puts
   the book/year FIRST — `_parse_title` only recognises the house format
   (book/year LAST), so on a legacy title the whole string, prefix
   included, became the "name" being composed from. `_strip_legacy_prefix`
   removes the prefix before the name reaches `validate_name` at all; the
   bullet-strip and dot-leader-strip it already does then apply exactly as
   they do for any other name — verified directly, not assumed, before
   this fix shipped.

CORRECTION 3, 2026-08-16 (after applying Corrections 1-2 to the live
corpus). Fix #4's veto (rule 1 above) was doing two jobs at once and only
one of them was correct: it correctly stops a section document's AGENCY
NAME from being guessed off an arbitrary row of its own table of agencies
(the Barbers Board incident) — but it was also refusing to so much as tidy
the FORMAT of a section document's title, so all 706 of them kept their
stray bullet, dot-leaders, printed page code and legacy `JLBC FY<year> — `
prefix forever, no matter how many of Corrections 1-2's fixes landed.
Measured against the live corpus after Corrections 1-2: 74 of the
remaining out-of-format titles and most of the remaining 82 wrong-agency
flags are this same population — e.g. `jlbc-approps-fy2027-bh20` ("• FY
2017 - FY 2027 "Then and Now" Comparisons .................."),
`jlbc-baseline-fy2027-s18` ("JLBC FY2027 — •  FY 2027 Other Appropriated
Funds Summary by Agency"). Full write-up: `.superpowers/sdd/task-7-report.md`,
"Format-only repair for section documents".

8. **A section document now gets a FORMAT-ONLY repair instead of being
   skipped outright.** The agency-name guard stays exactly as strict as it
   was — a section's title is never composed from any of its stamps, full
   stop, still enforced by `_resolve_trusted_stamp` returning a veto for
   every section document regardless of how many stamps it carries. What
   changed is what `repair_titles` does with that veto: for a section
   document (only) it now takes the name ALREADY in the title — the
   chapter's own real name, the one trustworthy source, since no agency
   label may ever stand in for it — strips the same decoration and legacy
   prefix every other title gets stripped (`validate_name`,
   `_strip_legacy_prefix`), and recomposes `{that name} — FY {year}
   {book}` around it. A name that cannot be cleaned into something
   `validate_name` accepts (corruption INSIDE the string, not just
   decoration at its edges) is left alone and recorded as skipped with the
   reason — a corrupt name is a question with an answer, not something to
   guess at. See the "Fix #8" branch inside `repair_titles`'s main loop.

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
from identity.validator import (
    distinctive_words,
    doc_id_tail,
    is_section_document,
    mentions_agency,
    validate_name,
)

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

# `doc_id_tail` (the document-specific tail of a doc_id, e.g. "doa-apf" out
# of "jlbc-approps-fy2016-doa-apf") and `is_section_document` moved to
# `identity/validator.py` 2026-08-16 so `identity/check.py` can share the
# exact same "is this a section document" test — see that module's
# docstring for the full reasoning. `doc_id_tail` is used two ways here:
# as `compose_title`'s `distinguisher` when two documents in the same
# (book, fiscal_year) would otherwise compose to the identical name (spec
# I5, 77 real parent/sub-programme pairs), and, via `is_section_document`,
# to veto composing a section's title from its table of agencies (fix #4
# below) — a book SECTION's slug is a printed page code (BD-13 -> "bd13")
# or a bare page number ("531"), never a real agency abbreviation.

# The older title format (~375 live documents) puts the book/year FIRST —
# "JLBC FY2025 — African-American Affairs, Arizona Commission of" — where
# the house format (`_TITLE_FORMAT` above) puts it LAST. `_parse_title`
# only recognises the house shape, so on a legacy title the whole string
# became the "name" `compose_title` was asked to build from, doubling the
# year and keeping the stray glyph. Stripped BEFORE `validate_name` ever
# sees the name — `validate_name`'s own leading-glyph and trailing-decoration
# strips then apply to what is left, unchanged (verified 2026-08-16 against
# `jlbc-baseline-fy2027-s1`'s real title, not assumed): "JLBC FY2027 — •
# Statement of General Fund Revenues and Expenditures ......... S-1"
# -> (this strip) -> "• Statement of General Fund Revenues and
# Expenditures ......... S-1" -> (validate_name) -> "Statement of General
# Fund Revenues and Expenditures". Matches en dash, em dash and a plain
# hyphen — JLBC's own scrape used all three across different editions.
_LEGACY_PREFIX = re.compile(r"^JLBC\s+FY\d{4}\s*[—–-]\s*", re.IGNORECASE)


def _strip_legacy_prefix(name: str) -> str:
    return _LEGACY_PREFIX.sub("", name, count=1).strip()


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
    stamp_counts: Mapping[str, int],
    slug_agency_id: str | None,
    is_section_doc: bool,
) -> tuple[str | None, str | None]:
    """Which stamp, if any, may be composed into a title.

    Returns `(stamp_id, veto_reason)`. A non-`None` `veto_reason` means:
    this document's AGENCY may not be re-decided this pass. For a
    non-section document that is a hard skip of the whole document — this
    mirrors `repair_titles`'s existing "uncorroborated stamp" branch below,
    which already treats "the one witness available cannot be trusted" as
    a hard skip rather than a partial fix, and an untrustworthy stamp here
    is the same shape of problem. For a SECTION document (below), a veto
    from THIS function only means "no agency label" — as of the 2026-08-16
    format-only-repair fix (`repair_titles`'s caller, not here), the
    document's own existing name is still cleaned up around whatever book
    and year it belongs to. This function decides agency trust only; it has
    no opinion on formatting.

    `stamp_counts` is `{agency_id: passages that stamp carries}` — not a
    plain set. Fix #4 (module docstring), rule 1: a SECTION document — its
    slug is a printed page code (`bd2`, `s12`) or a bare page number
    (`531`), matched by `identity.validator.is_section_document` — is a
    chapter of a book, not an agency. Its own title IS the section name.
    Never compose a name from a stamp for one, full stop. A table chunk
    inside a section like this
    often lists dozens of agencies, and the original pass took `stamps[0]`
    — an arbitrary pick, since stamps arrive from a `set` with no
    meaningful order — and renamed 706 such documents to whichever agency
    happened to come out first.

    For an ordinary (non-section) document carrying MORE THAN ONE stamp,
    fix #6 (CORRECTION 2 in the module docstring) replaced the old
    "the one stamp `mentions_agency` corroborates" rule with two STRONGER,
    ranked witnesses — because that rule itself mis-ranked a real document:
    `jlbc-baseline-fy2021-nav` carries `agency:nav` on 7 passages and
    `agency:wat` on 1, and `mentions_agency`'s corroboration is not a fair
    contest between them — `agency:wat`'s 2-word name ("Water Resources,
    Department of") needs only 1 word present where `agency:nav`'s 3-word
    name needs 2, so one incidental "water" mention outweighs the
    document's own 7-passage majority AND its own filename (`nav.pdf`).

    1. The document's own URL slug is the strongest witness in the whole
       system — it is JLBC's own filename for the page. If it resolves to
       an agency that is among this document's stamps, that is the
       document's agency, full stop.
    2. Otherwise, the stamp carried by STRICTLY more passages than every
       other wins — more of the document's own pages agree with it than
       with anything else.
    3. Otherwise (a genuine tie, or no slug evidence at all) there is no
       unambiguous agency. An arbitrary pick from a tie is exactly the
       mistake that previously renamed 706 summary chapters to whichever
       agency happened to be listed first in a table — skip, don't guess.

    The textual-corroboration guard (`mentions_agency`, spec I1's "two
    witnesses") is deliberately NOT consulted here. It still runs,
    unchanged, downstream in `resolve_supplier_disagreement` — it decides
    whether the stamp this function resolves may override a document's
    SUPPLIED title, which is a different question from which stamp is the
    document's own.
    """
    if not stamp_counts:
        return None, None
    if is_section_doc:
        return None, (
            f"doc_id {doc_id!r} is a book section (its slug is a printed "
            "page code or a bare number, not an agency abbreviation) — its "
            "own title is already the section name, and an agency stamp is "
            "never evidence for what to rename a section to"
        )
    if len(stamp_counts) == 1:
        return next(iter(stamp_counts)), None
    if slug_agency_id is not None and slug_agency_id in stamp_counts:
        return slug_agency_id, None
    ranked = sorted(stamp_counts.items(), key=lambda kv: kv[1], reverse=True)
    if ranked[0][1] > ranked[1][1]:
        return ranked[0][0], None
    return None, (
        f"document carries {len(stamp_counts)} agency stamps, none named by "
        "the document's own URL slug, and no stamp is carried by strictly "
        "more passages than every other — an arbitrary pick from a tie is "
        "never evidence, so no stamp was trusted here"
    )


def repair_titles(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    chunks_by_doc: Mapping[str, Iterable[str]],
    agency_names: Mapping[str, str],
    stamps_by_doc: Mapping[str, Iterable[str]],
    agency_slugs: Mapping[str, str] | None = None,
    dry_run: bool = True,
) -> RepairResult:
    result = RepairResult()
    # Fix #6 (module docstring, CORRECTION 2): `slug_from_jlbc_url` is a
    # pure regex function — no catalog, no DB, no model — so importing it
    # here costs nothing and stays consistent with this file's existing
    # rule that `chunking`/`store` imports live inside functions, never at
    # module scope (see the module docstring on `_load_live_inputs`).
    # `agency_slugs` defaults to None so every pre-existing caller/test that
    # doesn't pass it keeps today's behaviour exactly (no slug evidence
    # available means step 1 of `_resolve_trusted_stamp` never fires).
    from chunking.entity_stamper import slug_from_jlbc_url
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
        # One entry per PASSAGE that carries this stamp (not deduplicated) —
        # `_load_live_inputs` below appends once per row, so a `Counter`
        # over this list is the passage count fix #6 ranks candidates on.
        # Pre-existing tests pass each stamp once, which just means every
        # count is 1 — a tie, exactly as it read before this fix.
        stamps = list(stamps_by_doc.get(doc_id, ()) or ())
        doc_text = " \n".join(chunks_by_doc.get(doc_id, ()) or ())

        # Fix #6: the document's own filename, when it resolves to one of
        # this document's own stamps, is the strongest witness available —
        # see `_resolve_trusted_stamp`.
        slug = slug_from_jlbc_url(str((meta or {}).get("source_url") or ""))
        slug_agency_id = (
            agency_slugs.get(slug) if (slug and agency_slugs) else None
        )

        parsed = _parse_title(title)
        if parsed:
            supplied_name, book = parsed
        else:
            supplied_name, book = title, None
        # Fix #7: strip a legacy "JLBC FY<year> — " prefix BEFORE the name
        # ever reaches `validate_name` — see `_strip_legacy_prefix`. A no-op
        # on every house-format or already-clean title.
        supplied_name = _strip_legacy_prefix(supplied_name)
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
        is_section_doc = is_section_document(doc_id)
        stamp_id, veto_reason = _resolve_trusted_stamp(
            doc_id=doc_id, stamp_counts=Counter(stamps),
            slug_agency_id=slug_agency_id, is_section_doc=is_section_doc,
        )
        if veto_reason is not None:
            # Fix #8, 2026-08-16 (`.superpowers/sdd/task-7-report.md`,
            # "Format-only repair for section documents"): a vetoed SECTION
            # document must not be skipped OUTRIGHT — only the agency-name
            # part of its repair is unsafe (the Barbers Board incident this
            # veto exists for, module docstring fix #4), not the FORMAT
            # part. Its existing title's own words are the chapter's real
            # name — the only trustworthy source for one, since no agency
            # label may ever be consulted for it — so still strip the
            # decoration (`validate_name`, inside `compose_title`) and the
            # legacy prefix (`supplied_name` above already has it stripped)
            # and recompose `{that name} — FY {year} {book}` around it. A
            # non-section veto (the ambiguous-tie case, fix #4's general
            # form) still gets skipped outright — an ordinary document with
            # more than one CORROBORATED stamp and no way to break the tie
            # really might be misnamed, where a section chapter's title was
            # never going to be an agency name in the first place.
            if not is_section_doc:
                result.skipped.append({
                    "doc_id": doc_id, "field": "title", "reason": veto_reason,
                })
                continue
            try:
                composed = compose_title(
                    name=supplied_name, fiscal_year=fiscal_year, book=book,
                )
            except ValueError as err:
                # Corrupt INSIDE the string (identity/validator.py's own
                # distinction) — a stripped string here would be a guess,
                # and this pass never guesses. Leave the document alone.
                result.skipped.append({
                    "doc_id": doc_id, "field": "title",
                    "reason": (
                        f"{veto_reason}; its existing name could not be "
                        f"cleaned up into a usable one either: {err}"
                    ),
                })
                continue
            candidates[doc_id] = {
                "title": title, "book": book, "fiscal_year": fiscal_year,
                "chosen_name": supplied_name,
                "note": (
                    "book section — its own title is the section name; "
                    "only the format was cleaned up (stray bullet, "
                    "dot-leaders, legacy prefix), no agency stamp was "
                    "consulted for the name itself"
                ),
                "composed": composed,
            }
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
                slug = doc_id_tail(doc_id)
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
    from chunking.agency_catalog import id_to_name, load_agency_catalog
    from store.chunk_store import ChunkStore
    from store.documents import load_documents

    documents = load_documents()
    chunk_store = ChunkStore()
    chunks_by_doc: dict[str, list[str]] = defaultdict(list)
    # Fix #6: one entry per PASSAGE that carries the stamp, not a
    # deduplicated set — `repair_titles` needs passage COUNTS to rank
    # multiple stamps on one document, which a set structurally cannot
    # carry. Deduplicated per ROW first (`dict.fromkeys`) so a single
    # passage naming the same agency twice in its own
    # `agency_canonical_ids` still counts as ONE passage, not two.
    stamps_by_doc: dict[str, list[str]] = defaultdict(list)
    for row in chunk_store.scan(
        "budget_chunks", ["doc_id", "text", "agency_canonical_ids"]
    ):
        chunks_by_doc[row["doc_id"]].append(row.get("text") or "")
        for agency_id in dict.fromkeys(row.get("agency_canonical_ids") or []):
            stamps_by_doc[row["doc_id"]].append(agency_id)

    # Fix #6: the same slug->id mapping `EntityStamper` builds internally
    # (`chunking/entity_stamper.py`, `_load_catalog`), reconstructed here
    # from the same public loader rather than by instantiating the full
    # stamper — building one also loads the alias map, the fund catalog and
    # the fuzzy-match indexes, none of which a title repair needs.
    agency_slugs = {
        entry.slug.lower(): canonical_id
        for canonical_id, entry in load_agency_catalog().items()
        if entry.slug
    }

    return documents, chunks_by_doc, id_to_name(), stamps_by_doc, agency_slugs


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

    documents, chunks_by_doc, agency_names, stamps_by_doc, agency_slugs = (
        _load_live_inputs()
    )
    result = repair_titles(
        documents=documents, chunks_by_doc=chunks_by_doc,
        agency_names=agency_names, stamps_by_doc=stamps_by_doc,
        agency_slugs=agency_slugs, dry_run=not args.apply,
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
