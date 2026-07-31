"""Discover the documents that make up one JLBC book edition.

Two paths, and which one runs is the whole design:

**Catalog hit (the normal case).** Every edition through FY2027 is in
`data/jlbc-book-catalog.json`, built from a crawl that verified each URL
returned 200. A catalog hit does ZERO network calls and guesses nothing.

**Catalog miss (a newly published edition).** Only then do we probe, and
even then we never guess blind: a candidate ladder of the naming patterns
JLBC has actually used, each rung HEAD-verified before acceptance. A rung
that doesn't answer 200 is not used.

The rules below all come from auditing the real corpus, and each exists
because violating it produces a silent wrong answer rather than an error:

  * **Walk BOTH indexes.** The agency-index PDF lists per-agency pages; the
    linked-TOC PDF lists statewide sections. Their children are disjoint by
    construction, so walking only one silently loses half the book.
  * **Rolling `/budget/` guard.** JLBC republishes `/budget/apprpttoc.pdf`
    each cycle with no year in the path. Accepting it for the requested year
    without checking would ingest last year's book under this year's label.
  * **Never re-encode a URL.** One AFR URL only resolves double-encoded;
    "cleaning" it breaks it.
  * **Case-insensitive dedupe.** IIS is case-insensitive and JLBC's own
    casing is inconsistent *within* an edition, so `AXS.pdf` and `axs.pdf`
    are one document.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Protocol

from ingest.cache import DownloadCache
from ingest.discovery import (
    walk_agency_index,
    walk_approps_toc,
    walk_baseline_links,
)
from scripts.build_book_catalog import edition_key, normalize_url

CATALOG_PATH = Path(__file__).resolve().parent.parent / "data" / "jlbc-book-catalog.json"

FAMILIES = ("approps", "baseline")

# Section-filename → corpus doc_type. Mirrors the doc_types already in the
# corpus (see documents.json), so discovered documents route to the same
# extractors and chunkers as the ones ingested by hand.
_SECTION_DOC_TYPES = {
    "summary-section": "s-pdf",
    "budget-highlights": "bh-pdf",
    "budget-detail": "bd-pdf",
    "detailed-list": "detailed-list-pdf",
    "topic": "topic-pdf",
    "other": "topic-pdf",
}


class Prober(Protocol):
    """Network seam. `head` verifies existence; `get` downloads bytes."""

    def head(self, url: str) -> bool: ...

    def get(self, url: str) -> bytes: ...


@dataclass(frozen=True)
class DiscoveredDoc:
    url: str
    title: str
    doc_type: str
    fiscal_year: int
    publisher: str = "jlbc"
    code: str = ""


@dataclass
class EditionPlan:
    family: str
    fiscal_year: int
    source: str                      # "catalog" | "probed"
    single_file_url: str | None = None
    linked_toc_url: str | None = None
    agency_index_url: str | None = None
    documents: list[DiscoveredDoc] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def key(self) -> str:
        return edition_key(self.family, self.fiscal_year)


class DiscoveryError(RuntimeError):
    """The edition could not be located at all."""


# --- catalog ----------------------------------------------------------------


def load_book_catalog(path: Path | None = None) -> dict:
    return json.loads((path or CATALOG_PATH).read_text(encoding="utf-8"))


def list_editions(path: Path | None = None) -> list[dict]:
    """Editions for the UI picker, newest first."""
    catalog = load_book_catalog(path)
    out = []
    for key, entry in catalog["editions"].items():
        out.append({
            "key": key,
            "family": entry["family"],
            "fiscal_year": entry["fiscal_year"],
            "ingestable": entry["ingestable"],
            "rolling": entry["rolling"],
            "era_note": entry["era_note"],
            "single_file_url": entry["single_file_url"],
            "linked_toc_url": entry["linked_toc_url"],
            "document_count": len(entry["per_agency"]) + len(entry["summary_sections"]),
        })
    out.sort(key=lambda e: (-e["fiscal_year"], e["family"]))
    return out


# --- planning ---------------------------------------------------------------


def plan_edition(
    family: str,
    fiscal_year: int,
    *,
    prober: Prober,
    catalog_path: Path | None = None,
) -> EditionPlan:
    """Everything known about one edition, without downloading its content."""
    if family not in FAMILIES:
        raise DiscoveryError(f"Unknown report family {family!r}")

    catalog = load_book_catalog(catalog_path)
    entry = catalog["editions"].get(edition_key(family, fiscal_year))
    if entry is not None:
        return _plan_from_catalog(family, fiscal_year, entry)
    return _plan_by_probing(family, fiscal_year, prober=prober)


def _plan_from_catalog(family: str, fiscal_year: int, entry: dict) -> EditionPlan:
    """Catalog hit: verified URLs, verified rosters, zero network calls."""
    plan = EditionPlan(
        family=family,
        fiscal_year=fiscal_year,
        source="catalog",
        single_file_url=entry["single_file_url"],
        linked_toc_url=entry["linked_toc_url"],
        agency_index_url=entry["agency_index_url"],
    )
    per_agency_type = f"{family}-per-agency"
    for child in entry["per_agency"]:
        plan.documents.append(DiscoveredDoc(
            url=child["url"], title=child["title"] or child["code"],
            doc_type=per_agency_type, fiscal_year=fiscal_year, code=child["code"],
        ))
    for section in entry["summary_sections"]:
        plan.documents.append(DiscoveredDoc(
            url=section["url"], title=section["title"] or section["name"],
            doc_type=_section_doc_type(section["name"]),
            fiscal_year=fiscal_year, code=section["name"],
        ))
    _dedupe(plan)
    if not entry["ingestable"]:
        plan.notes.append(entry["era_note"])
    if entry["rolling"]:
        plan.notes.append(
            "This edition's book URLs live under the rolling /budget/ "
            "directory, which JLBC repurposes each cycle."
        )
    return plan


# Candidate ladders: every naming pattern JLBC has actually used, newest
# convention first. `{yy}` is the two-digit fiscal year. Each rung is
# HEAD-verified — nothing here is assumed to exist.
_INDEX_LADDERS = {
    "baseline": (
        "https://www.azjlbc.gov/{yy}baseline/agencyindex.pdf",
        "https://www.azjlbc.gov/{yy}baseline/{yy}BaselineAgencyIndex.pdf",
        "https://www.azjlbc.gov/{yy}baseline/FY20{yy}BaselineAgencyIndex.pdf",
        "https://www.azjlbc.gov/{yy}book1/{yy}BaselineAgencyIndex.pdf",
    ),
    "approps": (
        "https://www.azjlbc.gov/{yy}ar/agencyindex.pdf",
        "https://www.azjlbc.gov/{yy}AR/agencyindex.pdf",
        "https://www.azjlbc.gov/{yy}app/agencyindex.pdf",
    ),
}

_TOC_LADDERS = {
    "baseline": (
        "https://www.azjlbc.gov/{yy}baseline/{yy}baselinelinks.pdf",
        "https://www.azjlbc.gov/{yy}baseline/{yy}BaselineLinks.pdf",
        "https://www.azjlbc.gov/budget/{yy}baselinelinks.pdf",
    ),
    "approps": (
        "https://www.azjlbc.gov/{yy}ar/apprpttoc.pdf",
        "https://www.azjlbc.gov/{yy}AR/apprpttoc.pdf",
        "https://www.azjlbc.gov/{yy}app/apprpttoc.pdf",
        "https://www.azjlbc.gov/budget/apprpttoc.pdf",
    ),
}

_SINGLE_LADDERS = {
    "baseline": (
        "https://www.azjlbc.gov/{yy}baseline/{yy}baselinesinglefile.pdf",
        "https://www.azjlbc.gov/{yy}Baseline/{yy}baselinesinglefile.pdf",
        "https://www.azjlbc.gov/budget/{yy}baselinesinglefile.pdf",
    ),
    "approps": (
        "https://www.azjlbc.gov/{yy}ar/fy20{yy}approprpt.pdf",
        "https://www.azjlbc.gov/{yy}AR/FY20{yy}AppropRpt.pdf",
        "https://www.azjlbc.gov/budget/fy20{yy}approprpt.pdf",
    ),
}


def _plan_by_probing(family: str, fiscal_year: int, *, prober: Prober) -> EditionPlan:
    """Catalog miss: climb the ladders, HEAD-verifying every rung."""
    yy = f"{fiscal_year % 100:02d}"
    plan = EditionPlan(family=family, fiscal_year=fiscal_year, source="probed")

    plan.agency_index_url = _first_live(_INDEX_LADDERS[family], yy, prober)
    plan.linked_toc_url = _first_live(_TOC_LADDERS[family], yy, prober)
    plan.single_file_url = _first_live(_SINGLE_LADDERS[family], yy, prober)

    if not any((plan.agency_index_url, plan.linked_toc_url, plan.single_file_url)):
        raise DiscoveryError(
            f"No FY{fiscal_year} {family} book found on azjlbc.gov. If it has "
            "just been published under a new URL pattern, it needs to be added "
            "to the candidate list in ingest/book_discovery.py."
        )
    if _is_rolling(plan.agency_index_url) or _is_rolling(plan.linked_toc_url):
        plan.notes.append(
            "Found under the rolling /budget/ directory — its contents are "
            "checked against the requested year before anything is queued."
        )
    return plan


def _first_live(candidates: Iterable[str], yy: str, prober: Prober) -> str | None:
    for template in candidates:
        url = template.format(yy=yy)
        try:
            if prober.head(url):
                return url
        except Exception:
            # A network error on one rung is not evidence about the next.
            continue
    return None


# --- walking ----------------------------------------------------------------


def walk_edition(
    plan: EditionPlan,
    *,
    prober: Prober,
    cache: DownloadCache | None = None,
) -> EditionPlan:
    """Fill in `plan.documents` by walking its index PDFs.

    A catalog plan already has its roster and is returned untouched — the
    catalog's list came from a verified crawl, and re-walking would trade a
    known-good answer for a live one that can only be worse.
    """
    if plan.source == "catalog" and plan.documents:
        return plan

    cache = cache or DownloadCache(Path("data/cached-pdfs"), fetcher=prober.get)
    per_agency_type = f"{plan.family}-per-agency"

    if plan.agency_index_url:
        for entry in walk_agency_index(plan.agency_index_url, cache=cache):
            plan.documents.append(DiscoveredDoc(
                url=normalize_url(entry.url), title=entry.name or entry.slug,
                doc_type=per_agency_type, fiscal_year=plan.fiscal_year,
                code=entry.slug,
            ))

    if plan.linked_toc_url:
        walker = walk_approps_toc if plan.family == "approps" else walk_baseline_links
        for entry in walker(plan.linked_toc_url, cache=cache):
            plan.documents.append(DiscoveredDoc(
                url=normalize_url(entry.url), title=entry.title or entry.filename,
                doc_type=_SECTION_DOC_TYPES.get(entry.section_kind, "topic-pdf"),
                fiscal_year=plan.fiscal_year, code=Path(entry.filename).stem,
            ))

    _apply_rolling_guard(plan)
    _dedupe(plan)
    _verify_children(plan, prober)
    return plan


def _apply_rolling_guard(plan: EditionPlan) -> None:
    """Reject a rolling `/budget/` index whose children aren't this year's.

    `/budget/apprpttoc.pdf` has no year in its path and is republished every
    cycle. If we followed it for FY2028 and it still held FY2027's links, we
    would ingest last year's book under this year's label — searchable,
    plausible, and wrong. The children's own year-stamped directories are the
    evidence, so this is checkable rather than a matter of trust.
    """
    if plan.source != "probed":
        return
    if not (_is_rolling(plan.linked_toc_url) or _is_rolling(plan.agency_index_url)):
        return

    yy = f"{plan.fiscal_year % 100:02d}"
    stamped = [d for d in plan.documents if re.search(r"/\d{2}(app|ar|baseline|book)",
                                                      d.url, re.I)]
    if not stamped:
        # Children are also un-year-stamped; nothing contradicts the request,
        # but nothing confirms it either. Say so rather than pretend.
        plan.notes.append(
            "The rolling /budget/ index gave no year-stamped links, so its "
            "fiscal year could not be confirmed. Check one document before "
            "ingesting the rest."
        )
        return

    mismatched = [
        d.url for d in stamped
        if not re.search(rf"/{yy}(app|ar|baseline|book)", d.url, re.I)
    ]
    if len(mismatched) > len(stamped) / 2:
        plan.documents = []
        plan.unreachable = []
        raise DiscoveryError(
            f"The rolling /budget/ index does not currently hold the FY"
            f"{plan.fiscal_year} book — its links point at a different year "
            "(example: " + mismatched[0] + "). Nothing was queued."
        )


def _verify_children(plan: EditionPlan, prober: Prober) -> None:
    """HEAD-check every discovered child; misses are reported, not fatal."""
    live: list[DiscoveredDoc] = []
    for doc in plan.documents:
        try:
            ok = prober.head(doc.url)
        except Exception:
            ok = False
        (live if ok else plan.unreachable).append(doc if ok else doc.url)
    plan.documents = live


# --- helpers ----------------------------------------------------------------


def _section_doc_type(name: str) -> str:
    stem = name.lower()
    if re.fullmatch(r"s\d+", stem):
        return "s-pdf"
    if re.fullmatch(r"bh\d+", stem):
        return "bh-pdf"
    if re.fullmatch(r"bd\d+", stem):
        return "bd-pdf"
    if re.fullmatch(r"\d+(-\d+)?", stem):
        return "detailed-list-pdf"
    return "topic-pdf"


def _is_rolling(url: str | None) -> bool:
    return bool(url) and "/budget/" in url.lower()


def _dedupe(plan: EditionPlan) -> None:
    """One document per URL, compared case-insensitively (IIS doesn't care)."""
    seen: dict[str, DiscoveredDoc] = {}
    for doc in plan.documents:
        seen.setdefault(doc.url.lower(), doc)
    plan.documents = sorted(seen.values(), key=lambda d: (d.doc_type, d.code, d.url))
