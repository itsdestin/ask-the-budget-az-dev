"""What has JLBC published that we don't have? (spec T10)

The "Add a JLBC book" panel used to list every edition the catalog knows
about, with no indication of which ones were already in the corpus. Measured
2026-08-13: **62 editions offered, 0 of them usefully addable** -- 38 marked
ingestable and every one already present, 24 marked not ingestable and
offered anyway. Pressing "Add all" reported `skipped_existing: 139` and
appeared to do nothing.

This module inverts it. It works out which editions the corpus already holds,
probes azjlbc.gov just past them, and reports only the gap.

Everything here is presentation. `ingest/book_discovery.py` -- catalog-first,
with a HEAD-verified probe ladder that on 2026-07-31 found the FY2027
Appropriations Report the harvest had recorded as expected-but-unpublished,
walking 139 documents with 0 unreachable -- is not touched.
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Request

from ingest.book_discovery import DiscoveryError, list_editions, plan_edition
from store.config import data_dir
from store.documents import load_documents

router = APIRouter()

# How far past the newest edition we hold to look. Two years, because JLBC
# publishes a Baseline for the NEXT fiscal year alongside the Appropriations
# Report for the current one, so "one past newest" can already be stale
# within a single publishing cycle. Each year costs at most a handful of
# HEAD requests and usually zero (a catalog hit does no network at all).
LOOKAHEAD_YEARS = 2

# How long a stored answer is served without asking azjlbc.gov again. JLBC
# publishes a couple of books a year; there is nothing to gain from probing
# on every panel open, and a great deal to lose -- this app is deliberately
# offline-capable and was verified cold-starting with WiFi disconnected.
CACHE_TTL_SECONDS = 12 * 60 * 60

CACHE_FILENAME = "book-check.json"

# JLBC has used FOUR directory conventions for its books. Counted across the
# whole live corpus on 2026-08-13:
#
#   {yy}ar        1,782 docs   FY2013-2026   approps
#   {yy}app       1,294 docs   FY2005-2012   approps
#   {yy}baseline  1,866 docs   FY2013-2027   baseline
#   {yy}book1       141 docs   FY2012 only   baseline
#
# A two-pattern regex ({yy}ar / {yy}baseline) was written first and then
# MEASURED against the live corpus, which corrected the guess: it does not
# move the newest year (FY2026/FY2027 both use the modern conventions).
# What it loses is the older end -- approps 22 editions -> 14, baseline
# 16 -> 15. All 9 of those lost editions (approps FY2005-2012 and baseline
# FY2012) are marked INGESTABLE in the catalog, so every one of them would
# have been offered as "not in your corpus" when the corpus holds it: nine
# books to add that are already here, i.e. exactly the noise T10 exists to
# remove. Pinned by test_all_four_url_conventions_are_recognised.
#
# The last two rows were confirmed by TITLE, not guessed: 12book1/353.pdf is
# "CAPITAL OUTLAY ESTIMATES - FY 2012 Baseline" and 12app/260.pdf is
# "Capital Outlay - FY 2012 Appropriations Report".
_EDITION_DIR = re.compile(r"azjlbc\.gov/(\d{2})(ar|app|baseline|book1)/", re.I)

_FAMILY_OF = {
    "ar": "approps",
    "app": "approps",
    "baseline": "baseline",
    "book1": "baseline",
}

FAMILY_LABELS = {"approps": "Appropriations Report", "baseline": "Baseline"}


def corpus_editions() -> dict[str, set[int]]:
    """Which book editions the corpus already holds, per family.

    Read from each document's `source_url` and NEVER from its doc_id. 21
    documents in this corpus carry a family in their id that contradicts
    their own title (the `make_doc_id` collision recorded in STATUS.md);
    `source_url` is the only independent evidence, and 647/647 of the book
    sections parse from it.
    """
    found: dict[str, set[int]] = {"approps": set(), "baseline": set()}
    for entry in load_documents().values():
        url = entry.get("source_url") or ""
        match = _EDITION_DIR.search(url)
        if not match:
            continue
        yy, token = match.group(1), match.group(2).lower()
        found[_FAMILY_OF[token]].add(2000 + int(yy))
    return found


def _cache_path() -> Path:
    return data_dir() / CACHE_FILENAME


def _read_cache() -> dict | None:
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    # A non-object parses fine and then explodes on `.get`. Same degradation
    # rule as store/documents.py: a corrupt cache costs a network round-trip,
    # never the page.
    return raw if isinstance(raw, dict) else None


def _write_cache(payload: dict) -> None:
    try:
        tmp = _cache_path().with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        tmp.replace(_cache_path())
    except OSError:
        # An unwritable data dir means we probe every time. Slower, never wrong.
        pass


def _is_stale(checked_at: str | None) -> bool:
    if not checked_at:
        return True
    try:
        when = datetime.fromisoformat(checked_at)
    except ValueError:
        return True
    return (datetime.now(timezone.utc) - when).total_seconds() > CACHE_TTL_SECONDS


def check_missing(prober, *, refresh: bool = False) -> dict:
    """The T10 answer, from cache unless asked to look again.

    Never raises on a network failure: it serves the last good answer with
    `online: false` and the reason in plain English. A book panel that hangs
    on a dead network would be a regression against the offline cold start
    this app is verified to do.
    """
    cached = _read_cache()
    if not refresh and cached and not _is_stale(cached.get("checked_at")):
        return cached

    present = corpus_editions()
    catalog = list_editions()

    unavailable = [
        {
            "family": e["family"],
            "fiscal_year": e["fiscal_year"],
            "era_note": e["era_note"],
        }
        for e in catalog
        if not e["ingestable"]
    ]

    missing: list[dict] = []
    online, reason = True, None

    # 1. Catalog editions marked ingestable that the corpus does not hold.
    #    Costs no network at all.
    for entry in catalog:
        if not entry["ingestable"]:
            continue
        if entry["fiscal_year"] in present.get(entry["family"], set()):
            continue
        missing.append(
            {
                "family": entry["family"],
                "fiscal_year": entry["fiscal_year"],
                "document_count": entry["document_count"],
                "source": "catalog",
            }
        )

    # 2. Anything published SINCE the catalog snapshot (2026-06-16). This is
    #    the case the panel exists for: the FY2027 Appropriations Report is
    #    not in the catalog, and neither is anything JLBC publishes from now
    #    on. `plan_edition` is catalog-first, so a year already covered above
    #    costs nothing here either.
    known = {(m["family"], m["fiscal_year"]) for m in missing}
    for family, years in present.items():
        if not years:
            continue
        for year in range(max(years) + 1, max(years) + 1 + LOOKAHEAD_YEARS):
            if (family, year) in known:
                continue
            try:
                plan = plan_edition(family, year, prober=prober)
            except DiscoveryError:
                # Not published yet. A normal answer, not an error -- most
                # checks end here, which is what "everything is already
                # here" looks like from the inside.
                continue
            except Exception as exc:  # noqa: BLE001 — network, DNS, timeout
                online = False
                reason = (
                    "Couldn't reach azjlbc.gov to check for new editions "
                    f"({type(exc).__name__}). Showing what we knew last time."
                )
                break
            missing.append(
                {
                    "family": family,
                    "fiscal_year": year,
                    # A probed edition's document count needs `walk_edition`,
                    # which fetches and parses JLBC's index pages -- seconds,
                    # not milliseconds. Left null and filled in when the
                    # analyst actually asks for it, so opening the panel stays
                    # cheap. The UI says "documents will be listed when you
                    # add it" rather than inventing a number.
                    "document_count": None,
                    "source": "probed",
                }
            )
        if not online:
            break

    if not online and cached:
        # Keep the last good list rather than reporting an empty gap, which
        # would read as "everything is already here" -- a confident, wrong
        # answer produced by a network failure.
        payload = dict(cached)
        payload["online"] = False
        payload["reason"] = reason
        return payload

    payload = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "online": online,
        "reason": reason,
        "missing": sorted(missing, key=lambda m: (-m["fiscal_year"], m["family"])),
        "present": sorted(
            ({"family": f, "fiscal_year": y} for f, ys in present.items() for y in ys),
            key=lambda p: (-p["fiscal_year"], p["family"]),
        ),
        "unavailable": sorted(
            unavailable, key=lambda u: (-u["fiscal_year"], u["family"])
        ),
    }
    if online:
        _write_cache(payload)
    return payload


@router.get("/api/books/missing")
def missing(request: Request, refresh: bool = False):
    from app.routes.books import _prober

    return check_missing(_prober(request), refresh=refresh)
