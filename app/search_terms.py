"""Per-document search terms for the Budget Documents filter box.

WHY this exists: typing "dema" into that box returns ZERO documents today, and
so does "ema" — measured against the live 5,330-document corpus. Both are how
an analyst refers to the Department of Emergency and Military Affairs, and both
are already reviewed vocabulary in this repo: "dema" is a curated alias in
`samples/entity-catalog.yaml` and "ema" is the agency's JLBC URL slug. The
knowledge existed; it just never reached the browser, because title filtering
runs client-side over a listing payload that carried no agency and no shorthand.

So the listing carries the terms, computed HERE — server-side, once per page
load, next to the data that defines them. The browser's matcher stays dumb:
tokens in, boolean out. The alternative (ship the catalog to the browser and
parse there) means a second implementation of JLBC's convention in TypeScript,
and two implementations of one convention drift — this branch already shipped
that exact bug class once, in the doc-type slug map.

Design: docs/superpowers/specs/2026-08-11-title-filter-shorthand-design.md
"""
from __future__ import annotations

import sys
from functools import lru_cache

# Only used to name the exceptions a bad catalog FILE can raise (see
# _catalog_by_slug's narrowed try/except, 2026-08-11 review fix, widened to
# three exceptions by review finding 4). Already in this module's dependency
# closure via chunking/agency_catalog.py.
import yaml

# The lists below were tuned for QUESTIONS, where a stray "for" hard-filtered 13
# of 47 eval queries onto Forestry. A filter box has no ranking — a term matches
# or it does not — so retrieval's "demote to a boost" has no analogue here and
# both lists simply EXCLUDE.
#
# `AMBIGUOUS_PHRASES` is deliberately NOT imported. It governs name matching in
# retrieval, and honouring it here would REMOVE matching that works today:
# "insurance" already finds "Insurance, Department of" through the title. This
# module may only ever ADD.
from retrieval.query_agency import (
    AMBIGUOUS_AGENCIES,
    AMBIGUOUS_ALIASES,
    SUPPRESSED_ALIASES,
)
from retrieval.query_year import SHORTHAND_DOC_TYPE

# `{slug: (canonical_id, aliases)}`. Named because it appears in three
# signatures and the tuple-of-tuples spelling is unreadable inline.
Catalog = dict[str, tuple[str, tuple[str, ...]]]

# Deliberate, reviewed divergence from retrieval (Destin, 2026-08-11).
#
# Both suppression lists were measured against document PROSE, where "dot" and
# "doc" are ordinary English words. They were never measured against what
# someone types into a box labelled "Agency or keyword" — and there, "dot" is
# about as unambiguous as "dema".
#
# Kept as an explicit named set rather than a policy so the divergence is
# visible in one place. Every OTHER entry on both lists stays excluded.
FILTER_BOX_CARVE_OUT: frozenset[str] = frozenset({"dot", "doc"})

# The 20xx-only floor the JLBC convention itself observes — mirrors
# `retrieval.query_year._SHORTHAND_MIN_YEAR`. Below it, "98br" is a reference to
# nothing: JLBC spelled pre-2000 editions out in full (FY1984AppropRpt.pdf).
# The BARE form ("br") is ours and carries no such floor.
_SHORTHAND_MIN_YEAR = 2000


def _blocked() -> frozenset[str]:
    """Alias strings that may not become search terms."""
    return frozenset(SUPPRESSED_ALIASES | AMBIGUOUS_ALIASES) - FILTER_BOX_CARVE_OUT


@lru_cache(maxsize=1)
def _doc_type_forms() -> dict[str, tuple[str, ...]]:
    """`{doc_type: (form, ...)}` — the inverse of `SHORTHAND_DOC_TYPE`.

    DERIVED, never written out by hand: two lists of the same forms is how one
    silently stops matching a type somebody added to only the other. A doc_type
    can have several forms ("baseline-per-agency" has both "baseline" and "br").
    """
    out: dict[str, list[str]] = {}
    for form, doc_type in SHORTHAND_DOC_TYPE.items():
        out.setdefault(doc_type, []).append(form)
    return {doc_type: tuple(sorted(forms)) for doc_type, forms in out.items()}


@lru_cache(maxsize=1)
def _catalog_by_slug_cached() -> Catalog:
    """`{slug: (canonical_id, aliases)}` for every agency that has a slug.

    ~a dozen catalog entries are Gov-outline-only and carry `slug: None`; they
    are skipped rather than keyed under None.

    Narrowed 2026-08-11 (review fix): only the catalog READ, inside
    `load_agency_catalog()`, is meant to degrade — see `load_agency_catalog_by_slug`
    below, the wrapper that actually catches it. The per-entry loop here is
    deliberately UNGUARDED: it used to sit inside a bare `except Exception`,
    so a field renamed on `AgencyEntry` (`.slug`, `.aliases`,
    `.canonical_id`) raised `AttributeError` and was silently absorbed as
    "catalog unreadable" — shipping a corpus with zero agency terms and
    nothing logged to say why. A renamed field is a programming bug, not a
    bad file, and must raise.

    (2026-08-11 review finding 4, considered and rejected: also catching the
    valid-YAML-but-wrong-shape case — `raw.get("agencies", ...)` raising
    `AttributeError` inside `load_agency_catalog` itself. That AttributeError
    is indistinguishable from the renamed-field bug above, so catching it
    would silently reopen the exact hole the paragraph above closes.)

    THIS function must let a failed `load_agency_catalog()` call raise
    rather than catching it and returning `{}` here — `lru_cache` only
    memoizes a `return`, never a raise. Catching in here (as the
    pre-2026-08-11-review-finding-1 version of this module did, before the
    split into this function and `load_agency_catalog_by_slug`) let one transient read
    failure get cached as "the catalog is empty" for the rest of the
    process. `load_agency_catalog_by_slug` is the uncached wrapper that catches the
    raise, logs why, and lets the NEXT call retry instead of replaying a
    stale failure forever.

    Also caches on top of `load_agency_catalog`'s own `lru_cache`
    (chunking/agency_catalog.py:72) — deliberate, not a missed dedupe: that
    cache holds `{canonical_id: entry}`, and re-keying it by slug on every
    request would rebuild this dict per call for no reason.
    """
    from chunking.agency_catalog import load_agency_catalog

    catalog = load_agency_catalog()

    out: dict[str, tuple[str, tuple[str, ...]]] = {}
    for entry in catalog.values():
        if not entry.slug:
            continue
        aliases = tuple(a.lower() for a in (entry.aliases or []))
        out[entry.slug.lower()] = (entry.canonical_id, aliases)
    return out


def load_agency_catalog_by_slug() -> Catalog:
    """`_catalog_by_slug_cached()`, with a failed catalog READ degraded to
    `{}` instead of raising.

    2026-08-11 review finding 1: a failed read must not become a PERMANENT
    empty catalog. Catching HERE — outside `_catalog_by_slug_cached`'s
    `lru_cache(maxsize=1)` — means the failure is never memoized: the next
    call re-invokes `_catalog_by_slug_cached`, which retries
    `load_agency_catalog` fresh. A transient failure (a file lock, an AV
    scan, a bad packaging run) self-heals on the next request instead of
    silently zeroing agency terms for the life of the process. A successful
    read still only ever parses the ~10k-line YAML once, same as before.

    2026-08-11 review finding 4: `UnicodeDecodeError` is a `ValueError`, not
    an `OSError` — `Path.read_text` raises it for a mis-encoded catalog
    file. That is bad DATA, the same posture as a missing file or bad YAML,
    so it degrades here too.
    """
    try:
        return _catalog_by_slug_cached()
    except (OSError, yaml.YAMLError, UnicodeDecodeError) as err:
        # Say why every time the READ fails — not just the first time ever —
        # mirroring store.documents's "degrades ... and says why on stderr"
        # convention (store/documents.py's `_load_cached`).
        #
        # Callers that need terms for MANY documents must call this once and
        # pass the result down (see `search_terms`'s `catalog` argument), or
        # this line fires per document: a degraded catalog logged 5,330 times
        # and 1.33 MB of stderr for ONE page load against the live corpus
        # before `document_listing` was fixed to hoist it (2026-08-11 review).
        print(
            f"app.search_terms: ignoring the agency catalog ({err}) — agency "
            'search terms ("dema", "ema") are unavailable for this read; '
            'type shorthand ("26br") still works. The next call retries the '
            "catalog read from scratch.",
            file=sys.stderr,
        )
        return {}


def _agency_terms(doc_id: str, catalog: Catalog) -> set[str]:
    """The agency vocabulary for `doc_id`, or an empty set.

    The agency comes from the TRAILING SEGMENT of the doc_id
    (`jlbc-approps-fy2005-ema` -> `ema`) matched against the 157 known catalog
    slugs. Measured on the live corpus: 4,321 of 4,674 per-agency documents
    (92%) resolve this way. Also matching titles against canonical names
    rescues only 60 more (93% combined), which does not earn a second code
    path.

    The 293 that resolve by neither are FY2005-2012 sub-unit pages JLBC
    published that never got a catalog entry (adeassis, adeboe, axsacute).
    They lose nothing: their titles are the slug uppercased, so typing the slug
    already finds them by TITLE.

    Takes the catalog rather than fetching it, so a caller looping over many
    documents reads it once — see `search_terms`.

    Failure posture: an unreadable catalog yields no agency terms rather than a
    500 — same rule as `app.routes.corpus.budget_doc_ids`. Type shorthand needs
    no catalog and still applies. That posture lives entirely in
    `load_agency_catalog_by_slug`, which guards only the catalog READ; a malformed
    `AgencyEntry` raises out of this function too (2026-08-11 review fix —
    see `load_agency_catalog_by_slug` for why).
    """
    slug = doc_id.rsplit("-", 1)[-1].lower()
    entry = catalog.get(slug)
    if entry is None:
        return set()
    canonical_id, aliases = entry
    # An agency demoted across EVERY tier contributes nothing at all, however
    # it was named — agency:gov is the case that forced this list.
    if canonical_id in AMBIGUOUS_AGENCIES:
        return set()
    # `aliases` already contains `slug` unconditionally — chunking/
    # agency_catalog.py's `_aliases()` appends the slug first, before any
    # reviewed alias, whenever the entry has one (verified 2026-08-11). The
    # `{slug} |` union here was a no-op; dropped rather than kept as
    # ineffective belt-and-braces.
    return set(aliases) - _blocked()


def _type_terms(doc_type: str | None, fiscal_year: int | None) -> set[str]:
    """The shorthand vocabulary for a document's report type.

    Both the bare form and the year-prefixed one: a FY2026 baseline carries
    "br", "baseline", "26br" and "26baseline". Bare forms filter too (Destin,
    2026-08-11) so "pick 2026 in the rail, type br" works.
    """
    forms = _doc_type_forms().get(doc_type or "", ())
    terms = set(forms)
    if fiscal_year and fiscal_year >= _SHORTHAND_MIN_YEAR:
        terms |= {f"{fiscal_year % 100:02d}{form}" for form in forms}
    return terms


def search_terms(
    doc_id: str,
    doc_type: str | None,
    fiscal_year: int | None,
    catalog: Catalog | None = None,
) -> list[str]:
    """Extra strings the filter box matches this document on, sorted and unique.

    These are matched by EXACT token equality in the browser, never as
    substrings — "ar" as a substring would match "arizona" in nearly every
    title in the corpus.

    `catalog` exists for callers that need terms for MANY documents. Pass
    `load_agency_catalog_by_slug()` once and hand it to every call; omit it and
    each call resolves the catalog itself. That matters in the DEGRADED case,
    not the happy one — a successful read is cached process-wide, but a FAILED
    read deliberately is not (so a later request retries), and re-resolving per
    document meant a degraded catalog logged 5,330 times and 1.33 MB of stderr
    for one page load against the live corpus (2026-08-11 review).
    """
    if catalog is None:
        catalog = load_agency_catalog_by_slug()
    return sorted(_agency_terms(doc_id, catalog) | _type_terms(doc_type, fiscal_year))
