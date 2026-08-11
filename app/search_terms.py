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

from functools import lru_cache

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
def _catalog_by_slug() -> dict[str, tuple[str, tuple[str, ...]]]:
    """`{slug: (canonical_id, aliases)}` for every agency that has a slug.

    ~a dozen catalog entries are Gov-outline-only and carry `slug: None`; they
    are skipped rather than keyed under None.
    """
    from chunking.agency_catalog import load_agency_catalog

    out: dict[str, tuple[str, tuple[str, ...]]] = {}
    for entry in load_agency_catalog().values():
        if not entry.slug:
            continue
        aliases = tuple(a.lower() for a in (entry.aliases or []))
        out[entry.slug.lower()] = (entry.canonical_id, aliases)
    return out


def _agency_terms(doc_id: str) -> set[str]:
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

    Failure posture: an unreadable catalog yields no agency terms rather than a
    500 — same rule as `app.routes.corpus.budget_doc_ids`. Type shorthand needs
    no catalog and still applies.
    """
    slug = doc_id.rsplit("-", 1)[-1].lower()
    try:
        entry = _catalog_by_slug().get(slug)
    except Exception:  # noqa: BLE001 — absent or corrupt catalog
        return set()
    if entry is None:
        return set()
    canonical_id, aliases = entry
    # An agency demoted across EVERY tier contributes nothing at all, however
    # it was named — agency:gov is the case that forced this list.
    if canonical_id in AMBIGUOUS_AGENCIES:
        return set()
    return ({slug} | set(aliases)) - _blocked()


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
    doc_id: str, doc_type: str | None, fiscal_year: int | None
) -> list[str]:
    """Extra strings the filter box matches this document on, sorted and unique.

    These are matched by EXACT token equality in the browser, never as
    substrings — "ar" as a substring would match "arizona" in nearly every
    title in the corpus.
    """
    return sorted(_agency_terms(doc_id) | _type_terms(doc_type, fiscal_year))
