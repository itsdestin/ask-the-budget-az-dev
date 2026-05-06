"""TOC-walking layer.

Given a JLBC TOC PDF (agency index, baseline links, or approps TOC),
read its link annotations and return a typed list of entries naming
every per-section/per-agency PDF the TOC links to.

Why TOC-walking instead of static URL templating? Because some JLBC
filenames are page-keyed (`452.pdf` is "Detailed List of GF Changes"
in FY26 because that section starts on page 452, but the FY15 equivalent
has a different filename). The TOC PDF is the authoritative directory.

Three walkers, one per TOC shape:

  walk_agency_index(...)    # <YY>baseline/agencyindex.pdf, <YY>ar/agencyindex.pdf
                            # → per-agency PDFs (`<slug>.pdf`)
  walk_baseline_links(...)  # <YY>baselinelinks.pdf
                            # → s-PDFs + topic-PDFs (capitaloutlay, crr, …)
  walk_approps_toc(...)     # <YY>ar/apprpttoc.pdf
                            # → bh/bd/page-PDFs

Each accepts EITHER a local filesystem ``Path`` OR a URL string. URLs
are resolved through the download cache (``ingest.cache``) so callers
don't need to pre-fetch.

The link-rect → text extraction reuses the pattern proven in
``scripts/build_agency_catalog.py::parse_one_index``. That script
remains a separate program; the shared logic lives here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

from ingest.cache import DownloadCache


# --- Typed entries ---


@dataclass(frozen=True)
class AgencyIndexEntry:
    """One per-agency link from `agencyindex.pdf`."""

    slug: str
    name: str
    url: str
    page_in_doc: int | None  # page-in-singlefile the link points to


@dataclass(frozen=True)
class ApproprsTOCEntry:
    """One link from `apprpttoc.pdf`. Targets a bh-/bd-/page-PDF."""

    title: str
    filename: str        # 'bh2.pdf', 'bd1.pdf', '452.pdf'
    url: str
    section_kind: str    # see _classify_approps_filename
    page_in_doc: int | None


@dataclass(frozen=True)
class BaselineLinksEntry:
    """One link from `<YY>baselinelinks.pdf`. Targets an s-PDF or topic-PDF."""

    title: str
    filename: str        # 's18.pdf', 'capitaloutlay.pdf'
    url: str
    section_kind: str    # see _classify_baseline_filename
    page_in_doc: int | None


# --- Filename → section_kind classification ---

_S_RE = re.compile(r"^s\d+$")
_BH_RE = re.compile(r"^bh\d+$")
_BD_RE = re.compile(r"^bd\d+$")
_DIGITS_RE = re.compile(r"^\d+$")

# Cross-cutting topic PDFs that show up in BOTH baseline-links and
# approps-TOC. Stable JLBC names; if a new one is introduced and we
# don't know about it, the walker keeps it under "other".
_TOPIC_SLUGS = frozenset({"capitaloutlay", "crr", "tobacco", "csbg"})


def _classify_approps_filename(stem: str) -> str:
    """Classify an approps-TOC entry by its filename stem."""
    if _BH_RE.match(stem):
        return "budget-highlights"
    if _BD_RE.match(stem):
        return "budget-detail"
    if _DIGITS_RE.match(stem):
        # Page-keyed PDFs are the Detailed List of GF/Other Fund Changes
        # — they show up in apprpttoc.pdf with the page number as filename.
        return "detailed-list"
    if stem in _TOPIC_SLUGS:
        return "topic"
    return "other"


def _classify_baseline_filename(stem: str) -> str:
    """Classify a baseline-links entry by its filename stem."""
    if _S_RE.match(stem):
        return "summary-section"
    return "topic"


# --- PDF source resolution ---


def _open_pdf(source: Path | str, cache: DownloadCache | None = None) -> fitz.Document:
    """Open ``source`` as a PyMuPDF document, fetching via cache if a URL."""
    if isinstance(source, Path):
        return fitz.open(source)
    if isinstance(source, str) and source.startswith(("http://", "https://")):
        if cache is None:
            cache = DownloadCache(Path("data/cached-pdfs"))
        return fitz.open(cache.fetch(source))
    return fitz.open(Path(source))


# --- Link-rect → (text, slug, page_in_doc) extraction ---

_DOTS_TAIL_RE = re.compile(r"\s*\.{2,}\s*\d+\s*$")


def _is_jlbc_uri(uri: str) -> bool:
    """JLBC URLs live on two hosts (modern + legacy migrated FY23).
    External / non-JLBC links don't belong in our discovery output."""
    if "azjlbc.gov" in uri:
        return True
    if "azleg.gov" in uri and "/jlbc/" in uri:
        return True
    return False


def _slug_of(uri: str) -> str:
    """Filename stem of a `.pdf` URL: ``.../foo.pdf`` → ``foo``."""
    return uri.rsplit("/", 1)[-1].rsplit(".", 1)[0]


def _extract_link_text(page: fitz.Page, rect: fitz.Rect) -> tuple[str, int | None]:
    """Pull the visible text under a link rect, plus a page-in-doc number
    if the rect ends in a TOC dot-leader (``.... 452``)."""
    raw = page.get_text(clip=rect).strip().replace("\n", " ")
    page_in_doc: int | None = None
    pm = re.search(r"\.{2,}\s*(\d+)\s*$", raw)
    if pm:
        page_in_doc = int(pm.group(1))
    cleaned = _DOTS_TAIL_RE.sub("", raw).strip()
    # Drop a single bleed-through char from the line above (`a, Department of...`).
    cleaned = re.sub(r"^[a-z0-9],?\s+", "", cleaned)
    return cleaned, page_in_doc


def _walk_links(
    doc: fitz.Document,
) -> list[tuple[str, str, str, int | None]]:
    """Iterate every JLBC-internal link in ``doc``. Yields tuples of
    ``(uri, slug, name_text, page_in_doc)``."""
    out: list[tuple[str, str, str, int | None]] = []
    for page in doc:
        for link in page.get_links():
            uri = link.get("uri")
            rect = link.get("from")
            if not (uri and rect and uri.endswith(".pdf")):
                continue
            if not _is_jlbc_uri(uri):
                continue
            text, page_in_doc = _extract_link_text(page, rect)
            if not text or len(text) < 3:
                continue
            slug = _slug_of(uri)
            out.append((uri, slug, text, page_in_doc))
    return out


# --- Agency-index walker ---

# Slugs that appear in agencyindex.pdf but are NOT per-agency content
# (whole-document or summary-section links). Mirror the Phase 0 filter.
_NON_AGENCY_SLUGS = frozenset({
    "capitaloutlay", "agencyindex", "crr", "tobacco", "csbg",
})


def _is_agency_slug(slug: str) -> bool:
    """Agency slugs are 2-15 chars, lowercase, alpha+hyphen only.
    Anything else is a section/page/topic URL that leaked into the index."""
    if slug in _NON_AGENCY_SLUGS:
        return False
    if not re.match(r"^[a-z]+(-[a-z]+)*$", slug):
        return False
    # Summary-section links: `s7`, `s15`, `s18`.
    if slug.startswith("s") and len(slug) <= 3 and slug[1:].isdigit():
        return False
    return True


def walk_agency_index(
    source: Path | str,
    *,
    cache: DownloadCache | None = None,
) -> list[AgencyIndexEntry]:
    """Walk an `agencyindex.pdf` and return every per-agency link."""
    doc = _open_pdf(source, cache)
    try:
        out: list[AgencyIndexEntry] = []
        for uri, slug, name, page_in_doc in _walk_links(doc):
            if not _is_agency_slug(slug):
                continue
            out.append(AgencyIndexEntry(
                slug=slug, name=name, url=uri, page_in_doc=page_in_doc,
            ))
        return out
    finally:
        doc.close()


# --- Approps-TOC walker ---

# Slugs in apprpttoc.pdf that are not section content.
_NON_SECTION_APPROPS_SLUGS = frozenset({
    "apprpttoc", "agencyindex",
})


def walk_approps_toc(
    source: Path | str,
    *,
    cache: DownloadCache | None = None,
) -> list[ApproprsTOCEntry]:
    """Walk an `apprpttoc.pdf` and return its bh/bd/page-PDF entries."""
    doc = _open_pdf(source, cache)
    try:
        out: list[ApproprsTOCEntry] = []
        for uri, slug, title, page_in_doc in _walk_links(doc):
            if slug in _NON_SECTION_APPROPS_SLUGS:
                continue
            kind = _classify_approps_filename(slug)
            filename = f"{slug}.pdf"
            out.append(ApproprsTOCEntry(
                title=title,
                filename=filename,
                url=uri,
                section_kind=kind,
                page_in_doc=page_in_doc,
            ))
        return out
    finally:
        doc.close()


# --- Baseline-links walker ---

# Slugs in baselinelinks.pdf that are not section content.
_NON_SECTION_BASELINE_SLUGS = frozenset({
    "agencyindex",
})


def walk_baseline_links(
    source: Path | str,
    *,
    cache: DownloadCache | None = None,
) -> list[BaselineLinksEntry]:
    """Walk a `<YY>baselinelinks.pdf` and return its s/topic-PDF entries."""
    doc = _open_pdf(source, cache)
    try:
        out: list[BaselineLinksEntry] = []
        for uri, slug, title, page_in_doc in _walk_links(doc):
            # Skip per-agency PDFs that may also be linked from the TOC —
            # those are handled by walk_agency_index, not this walker.
            # Per-agency slugs are alpha+hyphen with no digits, but topic
            # PDFs (capitaloutlay, crr, tobacco, csbg) match that shape too.
            # Distinguishing is hard from URL alone; we keep the topic
            # slugs in the allow-list and exclude everything else that
            # looks per-agency.
            if slug in _NON_SECTION_BASELINE_SLUGS:
                continue
            # Only emit s-PDFs and the known topic-PDFs.
            stem = slug
            if not (_S_RE.match(stem) or stem in _TOPIC_SLUGS):
                continue
            kind = _classify_baseline_filename(stem)
            out.append(BaselineLinksEntry(
                title=title,
                filename=f"{stem}.pdf",
                url=uri,
                section_kind=kind,
                page_in_doc=page_in_doc,
            ))
        return out
    finally:
        doc.close()
