"""Admin tuning routes: the office alias overlay (spec E1).

A separate module rather than more of app/routes/admin.py — that file is
926 lines of provider/settings machinery, and these routes have a
different rhythm (corpus vocabulary, not keys and caps). The gate is the
same `require_admin`, so the parametrized gate test in
tests/test_admin_settings_route.py picks these routes up automatically.

WHAT THIS SURFACE IS FOR: `samples/entity-catalog.yaml` ships read-only,
so an office that calls the Department of Revenue "TPT" has nowhere to
say so. This writes `store/office_aliases.py`'s overlay instead — added
aliases resolve WEAK only, and a shipped shorthand can be switched off.

VALIDATION IS THE POINT OF THE MODULE. Everything an admin types here
becomes retrieval vocabulary, and a bad entry is silent: nobody sees a
search go to the wrong agency, they just get a worse answer. So no input
reaches `save_office_aliases` without passing every check below.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import current_user
from app.routes.admin import require_admin
from chunking.agency_catalog import id_to_name, load_agency_catalog

# `_normalize_for_match` is the SAME normalizer the corpus-side stamper and
# the query-side resolver use. Imported rather than re-implemented for the
# reason retrieval/query_agency.py imports it: an alias validated under one
# spelling rule and matched under another is a stoplist anyone bypasses by
# typing "For." instead of "for".
from chunking.entity_stamper import _normalize_for_match
from harness.settings import Settings

# `_index` is the resolver's own matching tables for the shipped catalog —
# `alias_to_ids` is literally what its tier 3 scans, `phrase_to_ids` what
# tiers 1-2 scan. Reading them (rather than rebuilding the same tables here)
# is what keeps this page's answer to "can this alias be switched off?"
# identical to what search actually does. Cached for the process lifetime,
# because the catalog cannot change under a running server.
from retrieval.query_agency import (
    AMBIGUOUS_ALIASES,
    SUPPRESSED_ALIASES,
    _index,
)
from store.office_aliases import (
    OfficeAlias,
    OfficeAliases,
    load_office_aliases,
    save_office_aliases,
)

router = APIRouter()

# Long enough for "office of economic opportunity", short enough that a
# pasted paragraph is refused rather than stored as vocabulary.
_MAX_ALIAS_LEN = 40

# Below this an alias still saves, but with a warning — two letters match
# by accident often enough that the admin should be told, not blocked.
_SHORT_ALIAS_LEN = 2


class AliasRow(BaseModel):
    alias: str
    canonical_id: str


class AliasesBody(BaseModel):
    added: list[AliasRow]
    disabled: list[str]


def _bad_request(detail: str) -> HTTPException:
    """One plain sentence, 400 — same shape as app/routes/admin.py. The
    reader is a non-technical office administrator looking at a form."""
    return HTTPException(status_code=400, detail=detail)


def _shipped_aliases() -> list[dict]:
    """The shipped shorthands an admin may actually switch off.

    Two exclusions, both of strings that would be a checkbox doing nothing
    or a hammer far bigger than "switch a shorthand off":

    DERIVED SLUGS — every agency's JLBC URL slug is folded into its alias
    list automatically (chunking/agency_catalog._aliases). `adc` is how the
    publisher itself abbreviates Corrections, not an office's reviewed
    acronym, and disabling it is a much bigger hammer than spec E1's
    "switch a shipped alias off".

    PHRASES A HIGHER TIER CLAIMS — disabling suppresses the ALIAS tier
    only (retrieval/query_agency.py tier 3). An alias that is also a
    catalog name phrase is claimed by tier 1/2 first, so it keeps
    resolving no matter what the overlay says. Measured on today's
    catalog this drops exactly 3 of the 156 aliases the resolver knows:
    `financial institutions`, `comm colleges`, `university of arizona`.
    Computed from the resolver's own phrase table rather than hardcoded,
    so a catalog edit that creates or removes a collision is picked up
    without anyone remembering this list exists.
    """
    index = _index(None)
    names = id_to_name()
    slugs = {
        _normalize_for_match(entry.slug)
        for entry in load_agency_catalog().values()
        if entry.slug
    }
    rows: list[dict] = []
    for alias, ids in index.alias_to_ids.items():
        if alias in slugs or alias in index.phrase_to_ids:
            continue
        # One row per agency: a curated alias like `ua` names two catalog
        # entries (Main Campus and the Health Sciences Center), and saying
        # so is more honest than picking one.
        for canonical_id in sorted(ids):
            rows.append({
                "alias": alias,
                "canonical_id": canonical_id,
                "agency_name": names.get(canonical_id, canonical_id),
            })
    return sorted(rows, key=lambda row: (row["alias"], row["canonical_id"]))


def _payload(overlay: OfficeAliases, warnings: list[str]) -> dict:
    names = id_to_name()
    return {
        "added": [
            {
                "alias": entry.alias,
                "canonical_id": entry.canonical_id,
                "agency_name": names.get(entry.canonical_id, entry.canonical_id),
                "added_by": entry.added_by,
                "added_at": entry.added_at,
            }
            for entry in overlay.added
        ],
        "disabled": sorted(overlay.disabled),
        "shipped": _shipped_aliases(),
        "agencies": [
            {"canonical_id": canonical_id, "name": name}
            for canonical_id, name in sorted(names.items(), key=lambda kv: kv[1])
        ],
        "warnings": warnings,
    }


@router.get("/api/admin/aliases")
def get_aliases(_settings: Settings = Depends(require_admin)) -> dict:
    return _payload(load_office_aliases(), [])


@router.put("/api/admin/aliases")
def put_aliases(
    body: AliasesBody, _settings: Settings = Depends(require_admin)
) -> dict:
    """Replace the overlay wholesale.

    WHOLESALE, never a per-key merge: a merge leaves an admin no way to
    DELETE an alias — they remove the row, the merge re-adds it from disk,
    and the word they came here to get rid of is still vocabulary.
    """
    catalog = load_agency_catalog()
    index = _index(None)
    names = id_to_name()

    warnings: list[str] = []
    cleaned: list[OfficeAlias] = []
    existing = {entry.alias: entry for entry in load_office_aliases().added}
    now = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()

    for row in body.added:
        alias = _normalize_for_match(row.alias)
        if not alias:
            # Two different mistakes, so two different sentences: an empty box
            # versus something like "!!!" that normalizes away to nothing.
            typed = row.alias.strip()
            if typed:
                raise _bad_request(
                    f"'{typed}' can't be an alias — it needs at least one "
                    "letter or number."
                )
            raise _bad_request(
                "An alias can't be blank. Type the shorthand your office uses, "
                "or remove the empty row."
            )
        if len(alias) > _MAX_ALIAS_LEN:
            raise _bad_request(
                f"'{alias[:_MAX_ALIAS_LEN]}…' is too long for an alias. Keep "
                f"it under {_MAX_ALIAS_LEN} characters."
            )
        if alias in seen:
            raise _bad_request(f"'{alias}' is in the list twice. Remove one of them.")
        seen.add(alias)
        if alias in SUPPRESSED_ALIASES or alias in AMBIGUOUS_ALIASES:
            # Checked on the NORMALIZED word, so "For." is the same entry as
            # "for" — see the _normalize_for_match import note above.
            raise _bad_request(
                f"'{alias}' is an everyday word that has sent searches to the "
                "wrong agency before, so it can't be used as an alias. Try a "
                "longer or more distinctive shorthand."
            )
        if row.canonical_id not in catalog:
            # NOT a harmless no-op, which is why it is a hard rejection: an
            # unknown id makes the match list non-empty, so the fuzzy tier
            # that would have found the RIGHT agency never runs, and the id
            # then reaches ranking as the only preferred agency and penalises
            # every chunk in the corpus.
            raise _bad_request(
                f"There's no agency with the id '{row.canonical_id}'. Pick an "
                "agency from the list."
            )
        owners = index.alias_to_ids.get(alias) or set()
        if owners and not _same_agency(index, owners, row.canonical_id):
            raise _bad_request(
                f"'{alias}' already means "
                f"{names.get(sorted(owners)[0], sorted(owners)[0])}. One word "
                "can't point at two agencies, so pick a different shorthand."
            )
        if len(alias) <= _SHORT_ALIAS_LEN:
            warnings.append(
                f"'{alias}' is very short. It will work, but short words match "
                "by accident, so watch whether it starts pulling up the wrong "
                "agency."
            )
        prior = existing.get(alias)
        # An unchanged row keeps its original stamp — re-saving the form
        # must not rewrite who added a word two years ago.
        keep_stamp = prior is not None and prior.canonical_id == row.canonical_id
        cleaned.append(
            OfficeAlias(
                alias=alias,
                canonical_id=row.canonical_id,
                added_by=prior.added_by if keep_stamp else current_user(),
                added_at=prior.added_at if keep_stamp else now,
            )
        )

    offered = {row["alias"] for row in _shipped_aliases()}
    disabled: set[str] = set()
    for word in body.disabled:
        key = _normalize_for_match(word)
        if not key:
            continue
        if key not in offered:
            # Covers both "no such alias" and "an alias a higher tier claims,
            # so switching it off would do nothing" — from the admin's side
            # they are the same sentence: it isn't on the list of things this
            # page can turn off.
            raise _bad_request(
                f"'{key}' isn't one of the built-in shorthands you can switch "
                "off. Pick one from the list."
            )
        disabled.add(key)

    overlay = OfficeAliases(added=tuple(cleaned), disabled=frozenset(disabled))
    # Uncaught on purpose (same as put_settings): reads degrade to empty,
    # writes RAISE. A save that failed on the shared drive must reach the
    # admin's screen, never look like it worked.
    save_office_aliases(overlay)
    # Re-read from disk, like put_settings does — the response is the
    # admin's confirmation that the save landed, so it should come from the
    # file, not from the object we hoped we wrote.
    return _payload(load_office_aliases(), warnings)


def _same_agency(index, owners: set[str], canonical_id: str) -> bool:
    """Is `canonical_id` the same REAL agency as everything in `owners`?

    Not string equality, because the catalog records some agencies twice:
    `dor` is agency:dor's slug and agency:rev is the same "Revenue,
    Department of". Refusing that would print "'dor' already means Revenue,
    Department of" to an admin who just asked for Revenue, Department of.
    `logical_group` is the resolver's own duplicate-detection key.
    """
    wanted = index.logical_group.get(canonical_id)
    return all(index.logical_group.get(owner) == wanted for owner in owners)
