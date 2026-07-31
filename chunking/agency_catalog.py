"""Agency catalog loader.

`samples/entity-catalog.yaml` (the Phase 0 157-agency canonical catalog) is the
single source of truth for `agency:<slug>` canonical IDs. `EntityStamper` has
parsed it inline since Phase 1a, but stamping isn't the only consumer: the
search UI, ingest metadata, and title building all need the reverse direction —
turn a stored `agency_canonical_id` back into a display name. Constructing an
`EntityStamper` just to read a name means also loading the alias map and fund
catalog and building fuzzy-match indexes, which is a lot of machinery for a
dictionary lookup. So the parsing lives here, and the stamper consumes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "samples" / "entity-catalog.yaml"
)


@dataclass(frozen=True)
class AgencyEntry:
    """One agency as the catalog records it.

    `slug` is the JLBC URL slug (`axs` → `https://www.azjlbc.gov/27baseline/axs.pdf`)
    and is None for the ~dozen Gov-outline-only entries that JLBC never
    published a per-agency page for — callers must not assume it exists.
    """

    canonical_id: str
    canonical_name: str
    slug: str | None
    name_variants: list[str] = field(default_factory=list)


def load_agency_catalog(path: Path | str | None = None) -> dict[str, AgencyEntry]:
    """Return `{canonical_id: AgencyEntry}` in catalog file order.

    Order matters to `EntityStamper`: its name→id index is first-wins, so two
    agencies sharing a printed name resolve to whichever appears first here.

    The result is cached per path (the YAML is ~10k lines and every consumer
    wants the same parse), which has two consequences: treat the returned dict
    as read-only, and note that rewriting the file mid-process won't be picked
    up until the interpreter restarts.
    """
    return _load_cached(str(Path(path) if path is not None else DEFAULT_CATALOG_PATH))


def id_to_name(path: Path | str | None = None) -> dict[str, str]:
    """Return `{canonical_id: canonical_name}` — the display-name lookup.

    This is the map the UI and ingest metadata want: they hold a canonical_id
    from a stored chunk and need something human-readable to render. Rebuilt
    per call (cheap — 157 entries) on top of the cached catalog parse.
    """
    return {
        canonical_id: entry.canonical_name
        for canonical_id, entry in load_agency_catalog(path).items()
    }


@lru_cache(maxsize=None)
def _load_cached(path_str: str) -> dict[str, AgencyEntry]:
    raw = yaml.safe_load(Path(path_str).read_text(encoding="utf-8")) or {}
    catalog: dict[str, AgencyEntry] = {}
    for entry in raw.get("agencies", []) or []:
        canonical_id = entry.get("canonical_id")
        # An entry with no canonical_id can't be referenced by a stamped chunk,
        # so it can't be looked up either — skip rather than key on a blank.
        if not canonical_id:
            continue
        catalog[canonical_id] = AgencyEntry(
            canonical_id=canonical_id,
            canonical_name=entry.get("canonical_name") or "",
            # Normalize an empty/absent slug to None so callers have one
            # "no slug" value to check instead of two.
            slug=entry.get("slug") or None,
            name_variants=_name_variants(entry),
        )
    return catalog


def _name_variants(entry: dict) -> list[str]:
    """Alternate printed names for one agency, in publisher-observed order.

    `names_observed_jlbc` is a map of `{printed name: [docs it appeared in]}` —
    the KEYS are the names, the values are provenance we don't need here. Gov
    aliases are folded into the same list because the stamper's name index has
    always included them; keeping them here (rather than as a separate field)
    means the stamper's matching set is unchanged by this refactor.
    """
    names: list[str] = [n for n in (entry.get("names_observed_jlbc") or {}) if n]
    gov_alias = entry.get("gov_alias") or entry.get("names_observed_gov")
    if isinstance(gov_alias, str):
        names.append(gov_alias)
    elif isinstance(gov_alias, (list, dict)):
        # A dict here iterates its keys, same as names_observed_jlbc.
        names.extend(s for s in gov_alias if isinstance(s, str))
    return names
