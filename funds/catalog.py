"""Fund catalog builder + YAML emitter.

Aggregates `FundAgencyRow` tuples (from `funds.parser`) into one
`FundEntry` per canonical fund. Multiple input source documents (s18,
bd2, AFR fund schedules) merge by canonical_id with the union of their
`present_in` lists.

Public API:
    - `FundEntry` — one fund's catalog record
    - `build_fund_catalog(rows=[...], source_id="...")` — single-source path
    - `build_fund_catalog(sources=[(id, rows), ...])` — multi-source path
    - `write_catalog_yaml(path, catalog, *, sources)` — emit YAML

Catalog YAML shape mirrors `samples/entity-catalog.yaml`: top-level `_meta`
block + `funds:` list with `canonical_name`, `canonical_id`, `slug`,
`observed_in_agencies`, `present_in`, optional `name_variants`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from funds.parser import FundAgencyRow
from funds.slug import slugify_fund_name

log = logging.getLogger(__name__)

_CATALOG_INSTRUCTIONS = (
    "Canonical fund names + slugs derived from JLBC cross-cut sources. "
    "Slug derivation rules in funds/slug.py. Per fund, observed_in_agencies "
    "lists every agency that appropriated from this fund across the "
    "processed sources. present_in records the source set."
)


@dataclass
class FundEntry:
    """One fund's catalog record. Mirrors agency-catalog shape."""

    canonical_name: str
    canonical_id: str
    slug: str
    observed_in_agencies: list[str] = field(default_factory=list)
    present_in: list[str] = field(default_factory=list)
    name_variants: list[str] = field(default_factory=list)


def build_fund_catalog(
    rows: Iterable[FundAgencyRow] | None = None,
    *,
    source_id: str | None = None,
    sources: Iterable[tuple[str, Iterable[FundAgencyRow]]] | None = None,
) -> list[FundEntry]:
    """Aggregate fund-agency rows into FundEntry list.

    Two callable shapes:
      - single source: `build_fund_catalog(rows, source_id="jlbc-s18-fy2027")`
      - multi source:  `build_fund_catalog(sources=[(id, rows), ...])`

    Either form is required; calling with neither raises ValueError.
    """
    if sources is None:
        if rows is None or not source_id:
            raise ValueError(
                "build_fund_catalog requires either (rows, source_id) "
                "or sources=[(id, rows), ...]"
            )
        sources = [(source_id, rows)]

    by_slug: dict[str, FundEntry] = {}
    # Track first-seen agency order per fund (dict insertion order is the contract)
    agency_order: dict[str, dict[str, None]] = {}

    for src_id, src_rows in sources:
        # Track which slugs we already added to this source's present_in,
        # so a fund appearing 50 times in s18 only adds 's18' once.
        seen_in_source: set[str] = set()

        for row in src_rows:
            slug = slugify_fund_name(row.fund_name)
            if not slug:
                continue  # bare 'Fund' or whitespace-only — drop silently

            entry = by_slug.get(slug)
            if entry is None:
                entry = FundEntry(
                    canonical_name=row.fund_name.strip(),
                    canonical_id=f"fund:{slug}",
                    slug=slug,
                )
                by_slug[slug] = entry
                agency_order[slug] = {}
            else:
                # Slug collision: same slug, different name. Record the
                # variant so review can decide whether the merge is right.
                normalized_existing = entry.canonical_name.strip()
                normalized_new = row.fund_name.strip()
                if normalized_new != normalized_existing and normalized_new not in entry.name_variants:
                    entry.name_variants.append(normalized_new)
                    log.warning(
                        "fund slug collision on %r: existing=%r incoming=%r",
                        slug,
                        entry.canonical_name,
                        normalized_new,
                    )

            agency_order[slug][row.agency_name] = None

            if slug not in seen_in_source:
                seen_in_source.add(slug)
                if src_id not in entry.present_in:
                    entry.present_in.append(src_id)

    # Materialize observed_in_agencies in first-seen order
    for slug, entry in by_slug.items():
        entry.observed_in_agencies = list(agency_order[slug].keys())

    return sorted(by_slug.values(), key=lambda e: e.canonical_name.casefold())


def write_catalog_yaml(
    path: Path | str,
    catalog: list[FundEntry],
    *,
    sources: list[str],
) -> None:
    """Write the catalog to YAML in the agency-catalog shape."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "_meta": {
            "instructions": _CATALOG_INSTRUCTIONS,
            "sources_processed": list(sources),
            "unique_funds": len(catalog),
        },
        "funds": [_entry_to_dict(e) for e in catalog],
    }
    path.write_text(
        yaml.safe_dump(payload, sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )


def _entry_to_dict(e: FundEntry) -> dict:
    out: dict = {
        "canonical_name": e.canonical_name,
        "canonical_id": e.canonical_id,
        "slug": e.slug,
        "observed_in_agencies": list(e.observed_in_agencies),
        "present_in": list(e.present_in),
    }
    if e.name_variants:
        out["name_variants"] = list(e.name_variants)
    return out
