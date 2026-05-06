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

import datetime as dt
import re
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import yaml

from ingest.cache import DownloadCache
from ingest.url_conventions import (
    approps_index_url,
    approps_toc_url,
    baseline_index_url,
    baseline_links_url,
)


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


# ============================================================================
# Discovery orchestrator + cache (Task 1.3)
# ============================================================================


# Entry-class registry — maps a doc_type to (URL builder, walker, entry class).
# Walking three TOC PDFs per fiscal year × multiple years is slow if done
# every run. The discovery cache below memoizes results keyed by
# (publisher, doc_type, fy) and invalidates when the source PDF's sha
# changes (caught via DownloadCache.sha256_of).
_DOC_TYPE_REGISTRY: dict[str, tuple[Callable[[int], str], Callable, type]] = {
    "baseline-cross-cut": (baseline_links_url, walk_baseline_links, BaselineLinksEntry),
    "approps-cross-cut": (approps_toc_url, walk_approps_toc, ApproprsTOCEntry),
    "baseline-per-agency": (baseline_index_url, walk_agency_index, AgencyIndexEntry),
    "approps-per-agency": (approps_index_url, walk_agency_index, AgencyIndexEntry),
}


@dataclass(frozen=True)
class DiscoveryResult:
    """One walk's worth of typed entries plus enough metadata to
    invalidate them when the source PDF changes."""

    publisher: str
    doc_type: str
    fiscal_year: int
    source_url: str
    source_sha256: str
    entries: tuple                     # tuple of typed Entry dataclass instances
    discovered_at: str


class DiscoveryCache:
    """YAML-backed cache of DiscoveryResults, keyed by
    (publisher, doc_type, fiscal_year). Invalidation is via
    source_sha256: any mismatch on lookup forces a re-walk.

    The walk_count attribute counts how many times the cache caused a
    fresh walk (i.e., a miss or invalidation). Tests use it to assert
    cache-hit behavior without mocking the walker.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.walk_count = 0
        self._data: dict[str, Any] = self._load()

    def get(
        self,
        publisher: str,
        doc_type: str,
        fiscal_year: int,
        *,
        expected_sha: str,
    ) -> DiscoveryResult | None:
        """Return a fresh cached result, or None for miss / stale-sha."""
        entry = self._entries.get(self._key(publisher, doc_type, fiscal_year))
        if entry is None:
            return None
        if entry["source_sha256"] != expected_sha:
            # Stale: source PDF has shifted since this cache row was written.
            return None
        return self._reconstruct(entry, doc_type)

    def put(self, result: DiscoveryResult) -> None:
        """Store the result, persisting the YAML file."""
        self._entries[self._key(result.publisher, result.doc_type, result.fiscal_year)] = {
            "publisher": result.publisher,
            "doc_type": result.doc_type,
            "fiscal_year": result.fiscal_year,
            "source_url": result.source_url,
            "source_sha256": result.source_sha256,
            "discovered_at": result.discovered_at,
            "entries": [asdict(e) for e in result.entries],
        }
        self._save()

    # --- Test helper. Not part of the public API. ---
    def set_source_sha_for_test(
        self,
        publisher: str,
        doc_type: str,
        fiscal_year: int,
        sha: str,
    ) -> None:
        """Mutate a cached entry's recorded sha. Used by tests to
        simulate JLBC reissuing a TOC PDF. Not for production use —
        the leading underscore on the dict key prevents collision with
        intended cache writes."""
        key = self._key(publisher, doc_type, fiscal_year)
        if key in self._entries:
            self._entries[key]["source_sha256"] = sha
            self._save()

    # --- Internals ---

    @staticmethod
    def _key(publisher: str, doc_type: str, fiscal_year: int) -> str:
        # YAML keys are strings — flatten the triple to one composite
        # so the manifest reads cleanly. Order: publisher.doc_type.fy.
        return f"{publisher}.{doc_type}.{fiscal_year}"

    @property
    def _entries(self) -> dict[str, dict[str, Any]]:
        return self._data["entries"]

    def _reconstruct(self, entry: dict[str, Any], doc_type: str) -> DiscoveryResult:
        _url_fn, _walker, entry_class = _DOC_TYPE_REGISTRY[doc_type]
        typed_entries = tuple(entry_class(**row) for row in entry["entries"])
        return DiscoveryResult(
            publisher=entry["publisher"],
            doc_type=entry["doc_type"],
            fiscal_year=entry["fiscal_year"],
            source_url=entry["source_url"],
            source_sha256=entry["source_sha256"],
            entries=typed_entries,
            discovered_at=entry["discovered_at"],
        )

    def _load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "entries": {}}
        loaded = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            return {"version": 1, "entries": {}}
        loaded.setdefault("version", 1)
        loaded.setdefault("entries", {})
        return loaded

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            yaml.safe_dump(self._data, sort_keys=True, default_flow_style=False),
            encoding="utf-8",
        )


def _utcnow_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


def discover(
    publisher: str,
    doc_type: str,
    fiscal_year: int,
    *,
    download_cache: DownloadCache | None = None,
    discovery_cache: DiscoveryCache | None = None,
) -> DiscoveryResult:
    """Resolve (publisher, doc_type, fy) to a DiscoveryResult.

    Cache-first: if discovery_cache has a fresh entry (source_sha256
    matches the current download_cache fetch's sha), return it without
    re-walking. Otherwise walk and write back.

    Currently only `publisher='jlbc'` is supported — JLBC is the only
    publisher with TOC-driven URL discovery. AFR, Gov SAD, and budget
    bills are single-document targets and don't need TOC walking; they
    plug directly into the extractor dispatcher (Workstream 2).
    """
    if publisher != "jlbc":
        raise ValueError(
            f"discover: unsupported publisher {publisher!r}. "
            "Only 'jlbc' has TOC-driven URL discovery; other publishers "
            "use single-document ingest paths."
        )
    if doc_type not in _DOC_TYPE_REGISTRY:
        raise ValueError(
            f"discover: unknown doc_type {doc_type!r}. "
            f"Expected one of {sorted(_DOC_TYPE_REGISTRY)}."
        )

    url_fn, walker_fn, _entry_class = _DOC_TYPE_REGISTRY[doc_type]
    url = url_fn(fiscal_year)

    if download_cache is None:
        download_cache = DownloadCache(Path("data/cached-pdfs"))
    if discovery_cache is None:
        discovery_cache = DiscoveryCache(Path("data/discovery-cache.yaml"))

    # Fetch first so we know the current sha.
    pdf_path = download_cache.fetch(url)
    sha = download_cache.sha256_of(url)
    assert sha is not None, "download cache failed to record sha after fetch"

    cached = discovery_cache.get(
        publisher, doc_type, fiscal_year, expected_sha=sha,
    )
    if cached is not None:
        return cached

    # Cache miss / stale — walk fresh and store.
    discovery_cache.walk_count += 1
    entries = walker_fn(pdf_path)
    result = DiscoveryResult(
        publisher=publisher,
        doc_type=doc_type,
        fiscal_year=fiscal_year,
        source_url=url,
        source_sha256=sha,
        entries=tuple(entries),
        discovered_at=_utcnow_iso(),
    )
    discovery_cache.put(result)
    return result
