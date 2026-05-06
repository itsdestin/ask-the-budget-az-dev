"""JLBC URL pattern library.

Pure URL string templating. Given (doc_type, fiscal_year, optional slug),
returns the canonical URL JLBC publishes the artifact at. No HTTP, no
filesystem, no PDF parsing — those happen one layer up.

## Pattern reference

Pulled from `docs/cross-doc-relationships.md` §7. The full table lives
there; this module is the executable form.

```
Baseline Book:           https://www.azjlbc.gov/<YY>baseline/...
Appropriations Report:   https://www.azjlbc.gov/<YY>ar/...
                         (FY15-FY22: http://www.azleg.gov/jlbc/<YY>AR/...)
Agency Index (within):   .../agencyindex.pdf
Per-agency content:      .../<slug>.pdf
Link-navigable nav:      https://www.azjlbc.gov/budget/<YY>baselinelinks.pdf
                         https://www.azjlbc.gov/<YY>ar/apprpttoc.pdf
```

`<YY>` is the last two digits of the fiscal year. For baseline books,
that's the FY being projected (FY 2027 → `27baseline/`). For approps
reports, it's the FY just enacted (FY 2026 approps → `26ar/`).

## Host migration (FY15-FY22 vs. FY23+)

JLBC moved hosts at FY23. Pre-cutoff URLs use a different scheme, host,
and case for the AR directory:

| Era | Host | Path case | Scheme |
|---|---|---|---|
| FY15-FY22 | `www.azleg.gov/jlbc/` | `<YY>AR/` (uppercase) | `http://` |
| FY23+ | `www.azjlbc.gov/` | `<YY>ar/` (lowercase) | `https://` |

The cutoff is encoded as `LEGACY_HOST_MAX_FY = 2022`. Baseline books
are always served from the modern host — only approps URLs carry the
legacy path. If JLBC ever republishes pre-FY23 docs at azjlbc.gov, bump
this constant.

## What this layer does NOT do

- **Slug alias resolution.** Caller passes the slug for the FY in
  question. `rev` for FY26 approps, `dor` for FY27 baseline — the URL
  layer doesn't know that's the same agency. That's the entity stamper's
  job (chunk-shape D7, cross-doc-relationships §5).
- **HTTP fetching.** That's `ingest/cache.py`.
- **TOC discovery.** Per-section URLs (`s<N>.pdf`, `bh<N>.pdf`,
  `<page>.pdf`, etc.) are NOT URL-templated — they're discovered by
  walking the TOC PDFs. That's `ingest/discovery.py`. This module
  provides only the static, predictable URLs.
"""

from __future__ import annotations

# --- Empirical constants ---

# JLBC migrated approps URLs from azleg.gov/jlbc/ to azjlbc.gov/ at FY23.
# FY22 and earlier: legacy host. FY23+: modern host.
LEGACY_HOST_MAX_FY: int = 2022

_MODERN_HOST = "https://www.azjlbc.gov"
_LEGACY_HOST = "http://www.azleg.gov/jlbc"

_VALID_PER_AGENCY_DOC_TYPES = ("baseline", "approps")


# --- Helpers ---


def _yy(fy: int) -> str:
    """Last two digits of the fiscal year, zero-padded.

    FY 2027 → "27". FY 2009 → "09".
    """
    return f"{fy % 100:02d}"


def _approps_root(fy: int) -> str:
    """Root URL for an appropriations-report fiscal year, host-aware.

    Modern: ``https://www.azjlbc.gov/<YY>ar``
    Legacy: ``http://www.azleg.gov/jlbc/<YY>AR`` (note uppercase AR)
    """
    yy = _yy(fy)
    if fy <= LEGACY_HOST_MAX_FY:
        return f"{_LEGACY_HOST}/{yy}AR"
    return f"{_MODERN_HOST}/{yy}ar"


def _baseline_root(fy: int) -> str:
    """Root URL for a baseline-book fiscal year.

    Baselines are always on the modern host — there's no observed
    pre-FY23 baseline URL on azleg.gov, so the host migration is
    approps-only.
    """
    return f"{_MODERN_HOST}/{_yy(fy)}baseline"


# --- Index URLs (one per FY × doc_type) ---


def baseline_index_url(fy: int) -> str:
    """URL for a baseline book's `agencyindex.pdf` — links to per-agency PDFs."""
    return f"{_baseline_root(fy)}/agencyindex.pdf"


def approps_index_url(fy: int) -> str:
    """URL for an approps report's `agencyindex.pdf` — links to per-agency PDFs."""
    return f"{_approps_root(fy)}/agencyindex.pdf"


# --- Cross-cut TOC URLs (one per FY × doc_type) ---


def baseline_links_url(fy: int) -> str:
    """URL for a baseline's `<YY>baselinelinks.pdf` — TOC of s-PDFs.

    Lives under `/budget/`, NOT under `/<YY>baseline/`. This is a JLBC
    quirk; see cross-doc-relationships §7.
    """
    return f"{_MODERN_HOST}/budget/{_yy(fy)}baselinelinks.pdf"


def approps_toc_url(fy: int) -> str:
    """URL for an approps report's `apprpttoc.pdf` — TOC of bh/bd/page PDFs."""
    return f"{_approps_root(fy)}/apprpttoc.pdf"


# --- Per-agency URLs ---


def baseline_per_agency_url(fy: int, slug: str) -> str:
    """URL for a baseline book's per-agency PDF: ``<root>/<slug>.pdf``.

    Caller passes the slug as-is. No alias resolution here; if `slug`
    is wrong for this FY (e.g., `rev` for an FY27 baseline), the URL
    is still well-formed but will likely 404 on fetch.
    """
    return f"{_baseline_root(fy)}/{slug}.pdf"


def approps_per_agency_url(fy: int, slug: str) -> str:
    """URL for an approps report's per-agency PDF: ``<root>/<slug>.pdf``."""
    return f"{_approps_root(fy)}/{slug}.pdf"


def per_agency_url(doc_type: str, fy: int, slug: str) -> str:
    """Unified per-agency URL dispatch by doc_type.

    `doc_type` must be `"baseline"` or `"approps"` — the only two JLBC
    forms that publish per-agency PDFs at predictable URLs. Cross-cut
    PDFs (s/bh/bd/page) are discovered via TOC walking, not URL
    templating, so they don't appear here.
    """
    if doc_type == "baseline":
        return baseline_per_agency_url(fy, slug)
    if doc_type == "approps":
        return approps_per_agency_url(fy, slug)
    raise ValueError(
        f"per_agency_url: unsupported doc_type {doc_type!r}; "
        f"expected one of {_VALID_PER_AGENCY_DOC_TYPES}. "
        "Cross-cut PDFs (s/bh/bd/page) are discovered via TOC walking, "
        "not URL templating — see ingest/discovery.py."
    )
