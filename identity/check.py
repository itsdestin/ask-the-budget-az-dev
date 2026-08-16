"""The identity ERROR-RATE instrument itself (spec I13, gate G-I2) — moved
here from `eval/identity_check.py` 2026-08-16 to fix a layering defect.

WHY THIS LIVES IN `identity/`, NOT `eval/`: `eval/` is a development harness
and `packaging/build_bundle.py` deliberately excludes it from the Windows
bundle every office PC runs. `ingest/worker.py` SHIPS in that bundle and
calls this check on every queue drain (spec I14) — so if the check's logic
lived in `eval/`, a real installed copy would hit `ModuleNotFoundError` on
every attempt. That failure is INVISIBLE: `_maybe_check_identity()` swallows
every exception on purpose (a detection instrument must never be able to
fail an ingest), so the log would say nothing, the admin page would just
keep showing its last successful result forever, and nobody would know the
check had never once run on a real machine. Shipped code may import
`identity/` (and other shipped packages) but never `eval/` — `eval/` is the
only side allowed to import back, per the design spec. Keep it that way.

Two design rules carried over unchanged from the original, each bought with
a measured mistake:

* **The stamping metric is per DOCUMENT, over all of its chunks.** Measured
  2026-08-16: a per-chunk version counts the `FOOTNOTES` page of a genuinely
  osteopathic document as a mis-stamp, so it can never reach zero and its
  target would be a lie.
* **No production count is ever reported.** "How many names did we make"
  rises as the rules get looser. Only the error rate can see a matcher
  getting worse.

`eval/identity_check.py` is now a thin CLI wrapper around this module: it
owns argument parsing and the human-readable stdout summary, and re-exports
these names so nothing that already imported from it broke.
"""
from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from identity.validator import (
    distinctive_words,
    is_section_document,
    longest_distinctive_word,
    mentions_agency,
    validate_name,
)

_FORMAT_RE = re.compile(r" — FY \d{4} .+$")
# A title that is the document's own slug shouted back at it.
_SLUG_TITLE_RE = re.compile(r"^[A-Z0-9&]{4,}(?= — FY |$)")


@dataclass
class IdentityReport:
    title_names_wrong_agency: int = 0
    documents_never_mentioning_stamp: int = 0
    validator_failures: int = 0
    titles_outside_format: int = 0
    duplicate_titles: int = 0
    doc_id_family_contradicts_url: int = 0
    uninformative_titles: int = 0
    distinct_agency_slugs: int = 0
    catalogued_agencies: int = 0
    # Informational, not an error count — how many documents were dropped by
    # the fiscal-note exclusion below. Reported so the exclusion is VISIBLE
    # rather than a silent filter nobody can see (2026-08-16 reconciliation).
    fiscal_notes_excluded: int = 0
    # Informational, not an error count. Defect 2, 2026-08-16
    # (`.superpowers/sdd/task-7-report.md`, "Format-only repair for section
    # documents"): a book-section chapter (its own slug is a printed page
    # code or a bare page number, e.g. `bh20`, `531` — see
    # `identity.validator.is_section_document`) names no agency of its own,
    # so `title_names_wrong_agency` cannot legitimately fire on one — a
    # metric measuring "does the title name a DIFFERENT agency than the
    # document's own" has no meaning for a document with no agency of its
    # own to differ FROM. Measured: `jlbc-baseline-fy2021-491`, titled
    # "General Fund Revenue", was flagged as naming the wrong agency purely
    # because "revenue" happens to be the Department of Revenue's longest
    # distinctive word — a chapter covering every agency's revenue can
    # never pass a check built to catch a document standing in for ONE
    # wrong agency, so the metric could never reach zero and nobody would
    # trust it. Counted here instead, using the SAME slug test
    # `identity/repair.py` already uses to veto composing a section's title
    # from its own table of agencies — extracted to
    # `identity.validator.is_section_document` so the two can never
    # disagree about what counts as a section.
    section_documents: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title_names_wrong_agency": self.title_names_wrong_agency,
            "documents_never_mentioning_stamp": self.documents_never_mentioning_stamp,
            "validator_failures": self.validator_failures,
            "titles_outside_format": self.titles_outside_format,
            "duplicate_titles": self.duplicate_titles,
            "doc_id_family_contradicts_url": self.doc_id_family_contradicts_url,
            "uninformative_titles": self.uninformative_titles,
            "distinct_agency_slugs": self.distinct_agency_slugs,
            "catalogued_agencies": self.catalogued_agencies,
            "fiscal_notes_excluded": self.fiscal_notes_excluded,
            "section_documents": self.section_documents,
            "findings": self.findings,
        }


# The longest-distinctive-word corroboration rule used to be reimplemented
# here as a private `_longest_word` helper, with its own copy of the
# 2026-08-16 measurement in its docstring. `identity/compose.py` had an
# independent (and weaker, "any word") copy of the same idea, and the two
# had already drifted — see `identity.validator.mentions_agency`'s
# docstring for the full three-way comparison this module's measurement
# fed into. Both modules now call the one shared implementation.


def check_corpus(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    chunks_by_doc: Mapping[str, Iterable[str]],
    agency_names: Mapping[str, str],
    stamps_by_doc: Mapping[str, Iterable[str]],
) -> IdentityReport:
    """Every I13 metric, computed from already-loaded data.

    Pure function of its arguments so the suite can drive it with fixtures
    and never open a LanceDB directory.
    """
    # Fiscal notes are OUT OF SCOPE for I13 (spec + identity/validator.py
    # docstring) — they have none of the three suppliers (title-parser,
    # page-number scraper, dot-leader OCR) this module exists to distrust,
    # and their "Fiscal Note - HB 2172: <strike>...</strike> (NOW: ...)"
    # titles are a deliberate app feature, not a naming defect. Confirmed by
    # measurement 2026-08-16: including their 2,104 documents contaminated
    # every metric — titles_outside_format 2627 -> 523 budget-only (audit
    # ~506), duplicate_titles 376 -> 218 budget-only (audit 218, exact),
    # invalid-name findings 471 -> 218 budget-only. Filtered ONCE here, not
    # per metric, so no metric can silently start counting them again.
    budget_documents = {
        doc_id: meta for doc_id, meta in documents.items()
        if meta.get("doc_type") != "fiscal-note"
    }

    report = IdentityReport(
        catalogued_agencies=len(agency_names),
        distinct_agency_slugs=len({
            a.split(":", 1)[-1] for ids in stamps_by_doc.values() for a in ids
        }),
        fiscal_notes_excluded=len(documents) - len(budget_documents),
    )

    title_counts = Counter(
        (d.get("title") or "") for d in budget_documents.values() if d.get("title")
    )

    for doc_id, meta in budget_documents.items():
        title = (meta.get("title") or "").strip()
        text = " \n".join(chunks_by_doc.get(doc_id, [])).lower()
        stamps = list(stamps_by_doc.get(doc_id, []))
        # Defect 2 (see `section_documents`'s field docstring above): a
        # section chapter names no agency of its own, computed once per
        # document from the doc_id alone via the SAME test
        # `identity/repair.py` uses to veto composing one from its table of
        # agencies — the two must never disagree about what counts as one.
        is_section = is_section_document(doc_id)
        if is_section:
            report.section_documents += 1

        if _SLUG_TITLE_RE.match(title):
            report.uninformative_titles += 1
        elif title and not _FORMAT_RE.search(title):
            report.titles_outside_format += 1
            report.findings.append(
                {"doc_id": doc_id, "kind": "title-format", "title": title}
            )

        if title and title_counts[title] > 1:
            report.duplicate_titles += 1

        verdict = validate_name(title.split(" — FY ")[0]) if title else None
        if verdict is not None and not verdict.ok:
            report.validator_failures += 1
            report.findings.append(
                {"doc_id": doc_id, "kind": "invalid-name",
                 "title": title, "reason": verdict.reason}
            )

        # Per-DOCUMENT stamping check. A document is a mis-stamp only when
        # the stamped agency's LONGEST distinctive word appears nowhere in
        # its chunks — see `identity.validator.mentions_agency` for why
        # "longest", not "any" or "all". Per-document (not per-chunk):
        # checking chunk-by-chunk would flag a correct document's own
        # boilerplate/footnotes page and could never reach zero.
        for agency_id in stamps:
            name = agency_names.get(agency_id)
            if not name:
                continue
            if not mentions_agency(text, name):
                report.documents_never_mentioning_stamp += 1
                report.findings.append(
                    {"doc_id": doc_id, "kind": "stamp-unmentioned",
                     "agency": agency_id}
                )
                break

        # Does the TITLE name a different agency than the document's own
        # stamp? Tightened 2026-08-16 from "any shared word off stamps[0]"
        # to three conditions, verified against the live corpus (239 vs the
        # audit's 218, within 10%; top hits are exactly the known defects —
        # jlbc-approps-fy2005-bar titled "Agriculture, Arizona Department of"
        # against agency:agr, jlbc-approps-fy2005-ata titled "Administrative
        # Hearings, Office of" against agency:oah):
        #   1. a stamp is CORROBORATED only when its LONGEST distinctive word
        #      (mirrors the stamping check above) is actually in the text —
        #      an uncorroborated stamp says nothing about whether the title
        #      is wrong, it says the STAMP might be wrong, a separate defect;
        #   2. none of the corroborated stamps' longest words may appear in
        #      the title, or this double-counts the stamping metric;
        #   3. some OTHER agency's longest distinctive word, >4 chars, must
        #      appear in the title — a short word is too likely to be
        #      coincidence (mirrors the same reasoning as the stamping rule).
        # KNOWN accepted false-positive shape, NOT fixed here: a document
        # whose title is right but whose stamp is missing/wrong shows up in
        # THIS metric too (e.g. jlbc-approps-fy2005-ban titled "Financial
        # Institutions, Department of" flagged against agency:ban, its own
        # slug) — that is a stamping defect surfacing here, and the stamping
        # fix is separate, later work.
        #
        # Defect 2, 2026-08-16: a SECTION document (`is_section`, above) is
        # excluded from this metric entirely — its title is a chapter name,
        # not a claim about which agency the document is, so it cannot
        # "name a different agency" than a document that never claimed to
        # be any one agency in the first place. Measured:
        # `jlbc-baseline-fy2021-491`, titled "General Fund Revenue", was
        # flagged here purely because "revenue" is agency:dor's longest
        # distinctive word — a false defect this metric cannot avoid
        # manufacturing for every summary chapter unless section documents
        # are excluded up front, which is what `report.section_documents`
        # (counted above) exists to make visible instead.
        titled = distinctive_words(title) if (title and not is_section) else set()
        if titled:
            corroborated_longest = set()
            for agency_id in stamps:
                name = agency_names.get(agency_id)
                if not name:
                    continue
                if mentions_agency(text, name):
                    corroborated_longest.add(longest_distinctive_word(name))
            if corroborated_longest and not (corroborated_longest & titled):
                other = [
                    aid for aid, nm in agency_names.items()
                    if aid not in stamps
                    and (lw := longest_distinctive_word(nm))
                    and len(lw) > 4
                    and lw in titled
                ]
                if other:
                    report.title_names_wrong_agency += 1
                    report.findings.append(
                        {"doc_id": doc_id, "kind": "title-wrong-agency",
                         "title": title, "stamped": stamps[0] if stamps else None,
                         "titled": other[0]}
                    )

    for doc_id, meta in budget_documents.items():
        url = (meta.get("source_url") or "").lower()
        if not url:
            continue
        if doc_id.startswith("jlbc-approps-") and "baseline" in url:
            report.doc_id_family_contradicts_url += 1
        elif doc_id.startswith("jlbc-baseline-") and re.search(r"/\d{2}ar/", url):
            report.doc_id_family_contradicts_url += 1

    return report


def _load_live(data_dir: Path | None) -> IdentityReport:
    """Assemble the arguments from the real corpus. Not unit-tested — it is
    I/O, and the logic it feeds is."""
    from chunking.agency_catalog import id_to_name
    from store.chunk_store import ChunkStore
    from store.documents import load_documents

    documents = load_documents()
    store = ChunkStore()
    chunks_by_doc: dict[str, list[str]] = defaultdict(list)
    stamps_by_doc: dict[str, set[str]] = defaultdict(set)
    for row in store.scan(
        "budget_chunks", ["doc_id", "text", "agency_canonical_ids"]
    ):
        chunks_by_doc[row["doc_id"]].append(row.get("text") or "")
        for a in row.get("agency_canonical_ids") or []:
            stamps_by_doc[row["doc_id"]].add(a)

    return check_corpus(
        documents=documents,
        chunks_by_doc=chunks_by_doc,
        agency_names=id_to_name(),
        stamps_by_doc=stamps_by_doc,
    )


def write_report(
    data_dir: Path | None = None, json_path: Path | None = None
) -> tuple[IdentityReport, Path]:
    """Run the live check and persist it to `<data_dir>/identity-report.json`
    (or `json_path`), the same write the CLI has always done — the admin
    page's Needs-attention group (spec I15) reads that file. Split out as
    its own entry point so `ingest/worker.py` can produce the same on-disk
    report the CLI does without going through `eval/identity_check.py`'s
    argument parsing or stdout summary, neither of which belongs on the
    ingest path. Returns the report and the path it was written to.
    """
    report = _load_live(data_dir)
    payload = report.as_dict()

    out = json_path
    if out is None:
        from store.config import data_dir as _dd
        out = Path(_dd()) / "identity-report.json"
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(out)

    return report, out
