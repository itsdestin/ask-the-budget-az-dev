"""The identity ERROR-RATE instrument (spec I13, gate G-I2).

Offline, free, seconds, over data already on disk — the shape
`eval/false_link_check.py` proved for citations. The reason six naming
defects shipped under ~2,900 passing tests is that every check in this
codebase is per-item and correct while NOTHING compares items to each
other. This is that missing comparison.

Two design rules, each bought with a measured mistake:

* **The stamping metric is per DOCUMENT, over all of its chunks.** Measured
  2026-08-16: a per-chunk version counts the `FOOTNOTES` page of a genuinely
  osteopathic document as a mis-stamp, so it can never reach zero and its
  target would be a lie.
* **No production count is ever reported.** "How many names did we make"
  rises as the rules get looser. Only the error rate can see a matcher
  getting worse.

Usage:
    uv run python -m eval.identity_check [--data-dir PATH] [--json PATH]

Writes `<data_dir>/identity-report.json`, which the admin page's
Needs-attention group renders (spec I15).
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from identity.validator import distinctive_words, validate_name

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
            "findings": self.findings,
        }


def _longest_word(words: Iterable[str]) -> str | None:
    """The single most specific token in a set of distinctive words.

    Used instead of "any word" / "all words" for both the stamping check and
    the wrong-agency check. Measured against the live corpus 2026-08-16 for
    `agency:ost` ("Osteopathic Examiners in Medicine and Surgery, Arizona
    Board of" — distinctive words {osteopathic, examiners, medicine,
    surgery}): "any word" scored 142 mis-stamped documents corpus-wide
    because an ordinary budget page saying "medicine" or "surgery" passes;
    "longest word" ("osteopathic") scored 732 for this agency alone (audit:
    721, 1.5% off) and 1140 corpus-wide; "all words" scored 1771 corpus-wide
    — over-strict, since a correct document can phrase its own boilerplate
    around any one distinctive word without using every one of them. The
    longest word is the agency's most specific token: short shared words like
    "medicine" recur across the whole corpus and prove nothing.
    """
    words = list(words)
    return max(words, key=len) if words else None


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
        # its chunks — see `_longest_word` for why "longest", not "any" or
        # "all". Per-document (not per-chunk): checking chunk-by-chunk would
        # flag a correct document's own boilerplate/footnotes page and could
        # never reach zero.
        for agency_id in stamps:
            name = agency_names.get(agency_id)
            if not name:
                continue
            longest = _longest_word(distinctive_words(name))
            if longest and longest not in text:
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
        titled = distinctive_words(title) if title else set()
        if titled:
            corroborated_longest = set()
            for agency_id in stamps:
                name = agency_names.get(agency_id)
                if not name:
                    continue
                longest = _longest_word(distinctive_words(name))
                if longest and longest in text:
                    corroborated_longest.add(longest)
            if corroborated_longest and not (corroborated_longest & titled):
                other = [
                    aid for aid, nm in agency_names.items()
                    if aid not in stamps
                    and (lw := _longest_word(distinctive_words(nm)))
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


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    report = _load_live(args.data_dir)
    payload = report.as_dict()

    out = args.json
    if out is None:
        from store.config import data_dir as _dd
        out = Path(_dd()) / "identity-report.json"
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(out)

    for k, v in payload.items():
        if k != "findings":
            print(f"{k}: {v}")
    print(f"findings: {len(payload['findings'])}  →  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
