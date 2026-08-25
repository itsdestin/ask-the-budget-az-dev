"""Which book editions have no "Full report" link yet? (spec R3-R6, R9, R10)

WHY A SCAN AND NOT A HOOK ON INGEST: a scan also catches editions added by a
bulk backfill, added on a machine nobody opened the app on, and added before
this feature existed. A hook catches only books that arrive the one expected
way, and the FY2027 Appropriations Report -- which appeared through the probe
ladder rather than the catalog -- is the standing proof that they arrive other
ways.

WHAT IS CACHED IS THE PROBE, NOT THE ANSWER. Working out WHICH editions are
unanswered is free: it reads `documents.json` and the merged link table, both
already mtime-cached, and touches no network. So it runs on every request and a
newly ingested edition appears at once. Only looking UP a pending edition's
candidate addresses costs requests, and those results are stored per edition
for 12 hours. A fully-answered corpus -- the normal state -- costs zero requests
and carries zero staleness.

Caching the whole reply instead would mean an analyst ingests a book, opens
/admin, and is told nothing is waiting -- for up to twelve hours, with nothing
on screen saying why.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.routes.admin import require_admin
from app.routes.books import NetworkWatch
from app.routes.books_missing import FAMILY_LABELS, corpus_editions
from ingest.book_discovery import DiscoveryError, plan_edition
from store.config import data_dir
from store.report_formats import (
    YEARLESS_BY_DESIGN,
    format_key,
    load,
    names_its_year,
    require_web_url,
    save_edition,
)

router = APIRouter()

# Its OWN file. `app/routes/books_missing.py` owns helpers of exactly this
# shape, but they are hardwired to `book-check.json`. Importing them would make
# the two panels read and overwrite ONE payload, so whichever ran last would
# hand the other its data and the "Add a JLBC book" panel would report an empty
# gap it never measured. Two files, two helper sets, no shared state.
CACHE_FILENAME = "book-format-probe.json"
CACHE_TTL_SECONDS = 12 * 60 * 60

# The same 6-second bound `books_missing.py` uses, for the same measured reason:
# every ladder rung that does not exist has to time out before the next is
# tried, and at the books route's 30s an uncached check took 31 seconds while
# an admin sat looking at a spinner.
PROBE_TIMEOUT_S = 6


def _cache_path() -> Path:
    return data_dir() / CACHE_FILENAME


def _read_cache() -> dict:
    """{format_key: {"checked_at": iso, "single_file": {...}|None, ...}}.

    `format_key` -- "Appropriations Report:2027" -- and NOT `edition_key`, which
    is `ingest.book_discovery`'s "approps-fy2027". Two vocabularies for two
    tables; `format_key`'s own docstring warns about exactly this mix-up, and
    this line used to make it.
    """
    try:
        raw = json.loads(_cache_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A corrupt or absent cache costs a probe, never the page. Same rule as
        # books_missing.py and store/documents.py. ValueError covers both
        # JSONDecodeError and UnicodeDecodeError.
        return {}
    # A non-object parses fine and then explodes on `.get`.
    return raw if isinstance(raw, dict) else {}


def _write_cache(payload: dict) -> None:
    try:
        resolved = _cache_path()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        # Per-call uuid suffix, not per-process: two servers on the share must
        # not share a tmp name (the chat-history lesson recorded in STATUS.md).
        tmp = resolved.with_name(f"{resolved.name}.tmp-{uuid.uuid4().hex[:8]}")
        tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        os.replace(tmp, resolved)
    except OSError:
        # An unwritable data dir means we probe every time. Slower, never wrong.
        pass


def _is_stale(checked_at: str | None) -> bool:
    if not checked_at:
        return True
    try:
        when = datetime.fromisoformat(checked_at)
    except (TypeError, ValueError):
        return True
    return (datetime.now(timezone.utc) - when).total_seconds() > CACHE_TTL_SECONDS


# `NetworkWatch` (offline-vs-not-published detection) moved to
# `app/routes/books.py` on 2026-08-22, next to the `HttpProber` it decorates,
# so `app/routes/books_missing.py`'s "Add a JLBC book" panel could share the
# identical mechanism instead of growing a second, drifting copy. See its
# docstring there for the full reasoning, INCLUDING the one property that
# only matters once a caller shares a single watch across more than one
# edition (`books_missing.py` does; this module still creates one per
# edition, in `_candidates_for` below).


@dataclass
class _Probe:
    """One edition's lookup: what was found, and how it went.

    There is deliberately no `source` field. The route used to compute, cache
    and send `plan.source` — the string "catalog" or "probed", saying which way
    the address was found. Nothing renders it: `webapp/src/api.ts` declines to
    declare it and no component reads it, because that is mechanism vocabulary
    on a page whose own copy rules ban jargon. A field that is stored and never
    read is a field that silently goes wrong, so it is gone.
    """

    candidates: dict = field(default_factory=dict)
    probed: bool = False       # did this cost network? (only then rewrite cache)
    offline: bool = False      # nothing on azjlbc.gov answered at all


def _candidate(url: str | None, fiscal_year: int, prober) -> dict | None:
    """One format's candidate, with the three facts the card shows (R6, R9)."""
    if not url:
        return None
    status, size = prober.head_info(url)
    return {
        "url": url,
        # 🔴 A REAL REQUEST, never an assumption. `plan_edition` is
        # catalog-first, so for a catalogued edition it returns URLs having made
        # no network call at all -- and `data/jlbc-book-catalog.json` is built
        # to feed a ladder that TOLERATES a 404, so it carries addresses nobody
        # ever fetched (STATUS.md records `budget/fy2027approprpt.pdf` as a live
        # 404 sitting in it). Without this the panel would offer a dead link
        # exactly as confidently as a good one, and the size R9 leans on for
        # "a 0.2 MB book is visibly wrong" would never appear.
        "status": status,
        "bytes": size,
        # R6: FLAGGED, NEVER REFUSED. See `check_url` below for why.
        "names_its_year": names_its_year(url, fiscal_year),
    }


def _candidates_for(label: str, family_slug: str, year: int, prober, cache: dict) -> _Probe:
    """This edition's two candidates, from cache when fresh."""
    key = format_key(label, year)
    hit = cache.get(key)
    if isinstance(hit, dict) and not _is_stale(hit.get("checked_at")):
        return _Probe(
            candidates={
                "single_file": hit.get("single_file"),
                "linked_toc": hit.get("linked_toc"),
            },
        )

    watch = NetworkWatch(prober)
    broke = False
    try:
        plan = plan_edition(family_slug, year, prober=watch)
    except DiscoveryError:
        # JLBC published no whole-report file we can find. The edition is STILL
        # pending -- the admin can paste an address by hand -- so this is a
        # normal answer, not an error.
        plan = None
    except Exception:  # noqa: BLE001 — a prober that raises past _first_live
        # 🔴 THE CATCH STAYS WIDE, THE CACHE DOES NOT. Narrowing this to
        # DiscoveryError was considered and rejected: this is a READ path, and
        # R10 says reads degrade -- one edition hitting a bug must not blank the
        # whole panel for every other edition. But a bug is not a measurement,
        # so `broke` stops the empty result being written to the cache, where it
        # would have masqueraded as a finished answer for the next twelve hours.
        # Next page load asks again, which is how a fixed bug becomes visible.
        plan = None
        broke = True

    # 🔴 THE CONFIRM REQUESTS HAPPEN FIRST, THEN THE OFFLINE TEST. This order is
    # the whole fix, and getting it backwards shipped once. `plan_edition` is
    # CATALOG-FIRST: for an edition `data/jlbc-book-catalog.json` names, it
    # returns URLs having made no network call at all. So a test placed before
    # this block reads `unreachable == 0 and answered == 0` and can never trip,
    # and the run continues with `_candidate` collecting `(None, None)` from a
    # dead host. Reproduced on a catalogued FY2003 approps with a silent prober:
    # `online: true`, `reason: null`, and `{"status": null, "bytes": null}`
    # against a perfectly good address -- then cached for 12 hours, so it stayed
    # wrong for the rest of the day after the network came back.
    found = {
        "single_file": _candidate(getattr(plan, "single_file_url", None), year, watch),
        "linked_toc": _candidate(getattr(plan, "linked_toc_url", None), year, watch),
    }

    if watch.unreachable and not watch.answered:
        # Every request for THIS edition went unanswered. Report it as a network
        # failure rather than as an edition with no links, and stop asking.
        # `probed=False` AND no cache write: an outage must leave no trace, or
        # it outlives itself.
        return _Probe(
            candidates={"single_file": None, "linked_toc": None},
            probed=False,
            offline=True,
        )

    if broke:
        return _Probe(candidates={"single_file": None, "linked_toc": None}, probed=False)

    # 🔴 A PARTIAL OUTAGE MUST NOT BE CACHED EITHER, for the same reason the
    # whole-outage branch three lines above is not. If the ladder answered but
    # ONE confirm request timed out, `watch.answered` is above zero, so the
    # offline test does not fire — and a candidate carrying `"status": null`
    # would be written into a cache that is trusted for twelve hours. The card
    # would show a real, probably perfectly good address looking dead, all day,
    # after the network came back. The candidates are still RETURNED, because
    # the address itself may well be fine and the card says so; they are simply
    # not remembered. Next page load asks again, which costs one request.
    if any(
        isinstance(c, dict) and c.get("status") is None for c in found.values()
    ):
        return _Probe(candidates=found, probed=False)

    cache[key] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        **found,
    }
    return _Probe(candidates=found, probed=True)


def _stored_year_check(url: str | None, year: int) -> bool | None:
    """The year verdict shown for an address ALREADY SAVED. `None` = no address.

    🔴 IT EXISTS ONLY TO SILENCE ONE PERMANENT, UNFIXABLE FALSE ALARM. JLBC
    published the FY2023 Appropriations Report's table of contents out of its
    undated `/budget/` folder, so its web address is
    `https://www.azjlbc.gov/budget/apprpttoc.pdf` — an address with no year
    anywhere in it. It was downloaded and read on 2026-08-16 and it really is
    the FY2023 book. It is correct, it cannot be made to name its year, and no
    administrator can do anything about it. `store.report_formats` records that
    one address in `YEARLESS_BY_DESIGN` for exactly this reason.

    Without this, opening the Appropriations Report card showed an amber
    warning about FY2023 EVERY TIME, above the controls for whichever edition
    was actually waiting to be approved — so it read as a complaint about the
    thing the administrator was being asked to approve. A warning that is
    always on screen and always wrong is worse than no warning at all: it
    teaches the reader to scroll past warnings, and the only other warning
    wearing this exact treatment is the real one — a live, downloadable,
    WRONG-year report behind a button labelled "Full report", which is the one
    defect a successful download cannot detect.

    WHY HERE AND NOT INSIDE `names_its_year`. That function answers a narrow,
    literal question — "do the digits of this year appear in this address?" —
    and every caller decides for itself whether the one exemption applies. The
    two callers that already existed do it this way
    (`tests/test_report_formats_data.py::test_every_url_names_its_own_fiscal_year`
    and `scripts/verify_report_formats.py::year_mismatches`), and the callers
    that must NOT be exempt are the reason the shape is right:

      * `POST /api/admin/book-formats/check` — if an administrator pastes this
        address for FY2028 they genuinely SHOULD be warned, because it serves
        the FY2023 book;
      * the `PUT` reply's `names_its_year` echo, for the same reason;
      * a PENDING edition's suggested addresses (`_candidate` above).

    Only the derived warning for an edition ALREADY APPROVED is exempt, and
    that is this function's whole reach.

    KNOWN, PRE-EXISTING LIMIT, recorded rather than fixed here: the exemption
    is keyed on the address string alone, so it would also stay quiet if
    someone copied the FY2023 row onto FY2024 and left the address unchanged.
    A previous review already flagged that; narrowing it is its own change.
    """
    if not url:
        return None
    if url in YEARLESS_BY_DESIGN:
        return True
    return names_its_year(url, year)


def _approved_row(key: str, row) -> dict:
    """One already-answered edition, INCLUDING the year check on what is stored.

    🔴 `names_its_year` IS HERE SO THE WARNING CAN BE DERIVED RATHER THAN
    REMEMBERED, and that is a fix for a real defect. The card used to learn a
    stored address had the wrong year in exactly one way: from the reply to the
    PUT that saved it, held in component state. Every book card on /upload
    unmounts the instant another card is clicked, so the warning died on the
    next click -- and reopening the edition under "Already answered" showed
    nothing either, because a stored edition carried no year check at all. The
    admin was left with a row reading "24 editions set", not amber, over a live
    downloadable WRONG-year report behind a button labelled "Full report".

    That is the ONE defect a `200 OK` cannot detect, and R6 deliberately flags
    it rather than refusing it (`budget/apprpttoc.pdf` genuinely IS the FY2023
    report), so this warning is the whole mitigation. A mitigation that a
    single unrelated click erases is not one. Sending the check with the row
    makes it a property of the DATA, so it survives any remount and any reload.

    `None` for a format recorded as never published: there is no address to
    judge, and `False` there would read as a complaint about one. Same shape as
    `write_edition`'s reply, deliberately -- the card reads the two through one
    code path.

    The verdict comes from `_stored_year_check`, NOT straight from
    `names_its_year`, and the difference is one documented exemption. Read that
    function before changing this one.
    """
    year = int(key.rpartition(":")[2])
    return {
        "family": key.rpartition(":")[0],
        "fiscal_year": year,
        "single_file": row.single_file,
        "linked_toc": row.linked_toc,
        "names_its_year": {
            "single_file": _stored_year_check(row.single_file, year),
            "linked_toc": _stored_year_check(row.linked_toc, year),
        },
    }


def pending_editions(prober, *, refresh: bool = False) -> dict:
    """Every book edition in the corpus that the link table does not answer."""
    table, problems = load()
    cache = {} if refresh else _read_cache()
    pending: list[dict] = []
    online, reason = True, None
    dirty = False

    for family_slug, years in corpus_editions().items():
        label = FAMILY_LABELS[family_slug]
        for year in sorted(years, reverse=True):
            if format_key(label, year) in table:
                continue
            if online:
                probe = _candidates_for(label, family_slug, year, prober, cache)
                dirty = dirty or probe.probed
                if probe.offline:
                    online = False
                    reason = (
                        "Couldn't reach azjlbc.gov to look up the links for "
                        "these editions. They still need one — the suggested "
                        "addresses will appear when the network is back."
                    )
            else:
                # Deliberate deviation from the plan's sketch, which `break`s
                # out of both loops here. An edition is pending because the
                # TABLE does not answer it, which is knowable with no network at
                # all — so a dead network must cost the admin the suggested
                # addresses, not the list. Truncating the list would tell an
                # offline admin that fewer books need attention than really do.
                probe = _Probe(candidates={"single_file": None, "linked_toc": None})
            pending.append({
                "family": label,
                "fiscal_year": year,
                "candidates": probe.candidates,
            })

    if dirty and online:
        _write_cache(cache)

    return {
        "online": online,
        "reason": reason,
        "problems": problems,
        "pending": sorted(pending, key=lambda p: (-p["fiscal_year"], p["family"])),
        # `approved` is what makes a WRONG approval correctable through this
        # same PUT: the card lists the editions already answered and lets the
        # admin re-open one, instead of hand-editing JSON on the share.
        #
        # ITS REACH, stated because it has been wrong here before: the list IS
        # reachable in the healthy, nothing-pending state, as of 2026-08-16.
        # `webapp/src/pages/upload/ReportLinkRow.tsx` renders it as the
        # "Already answered" section of the "Full report link" row inside the
        # Baseline Book / Appropriations Report cards on /upload, and opening an
        # edition there reaches this same correction editor. That row is on the
        # page every day whether or not anything is waiting.
        #
        # (This comment used to name `webapp/src/admin/ReportLinksPanel.tsx`,
        # which was DELETED when the panel moved off /admin — a load-bearing
        # safety comment pointing at nothing. Re-pointed 2026-08-16.)
        #
        # Before the move the whole card was hidden in the healthy state, so
        # approving a wrong URL (which MAKES the state healthy) hid the only
        # repair; that was reproduced in review. If this list ever stops being
        # reachable when nothing is pending, this comment is a lie and a wrong
        # link becomes unfixable outside a text editor.
        "approved": sorted(
            (_approved_row(key, row) for key, row in table.items()),
            key=lambda a: (-a["fiscal_year"], a["family"]),
        ),
    }


def _probe_with(request: Request):
    """The injected fake in tests, a short-timeout HttpProber in production."""
    from app.routes.books import HttpProber, _prober

    prober = _prober(request)
    if isinstance(prober, HttpProber):
        prober = HttpProber(timeout_s=PROBE_TIMEOUT_S)
    return prober


@router.get("/api/admin/book-formats")
def book_formats(request: Request, refresh: bool = False, _s=Depends(require_admin)) -> dict:
    return pending_editions(_probe_with(request), refresh=refresh)


class EditionWrite(BaseModel):
    family: str
    # 🔴 BOUNDED, because the store's own validator is not a substitute for it.
    # Reproduced: `PUT {"fiscal_year": 99}` returned `200 {"ok": true}` and wrote
    # `Baseline:99` into the overlay -- which `store.report_formats._parse` then
    # DROPPED on every later read, because it demands four digits, leaving only
    # a `problems` sentence behind. That is a write reporting success and not
    # taking effect, the one thing R10 forbids. The range is copied from the
    # sibling model in this package (`app/routes/books.py::EditionBody`) rather
    # than invented, so the app states one idea of a plausible year.
    fiscal_year: int = Field(ge=1970, le=2100)
    single_file: str | None = None
    linked_toc: str | None = None


@router.put("/api/admin/book-formats")
def write_edition(body: EditionWrite, _s=Depends(require_admin)) -> dict:
    """Record one edition's whole-report links.

    The same route both APPROVES a pending edition and CORRECTS one that was
    already answered — the overlay entry replaces its key wholesale either way
    (R1), so there is one write path and no separate "edit" verb to keep in
    step with it.

    A `ValueError` from the store is the admin's own input being refused, so it
    becomes a 400 carrying the store's sentence verbatim: that sentence is
    written for a reader, and rewriting it here would give the office two
    wordings for one refusal. Anything else is a real failure and is allowed to
    500 — a save that did not happen must never report success (R10).

    THE REPLY ECHOES `names_its_year` PER SAVED FORMAT, and that is defence in
    depth rather than decoration. A year mismatch is deliberately flagged and
    never refused (R6, because `budget/apprpttoc.pdf` genuinely IS the FY2023
    book), but this route accepted an address it never once looked at — so the
    entire mitigation rested on the admin having pressed **Check** first, which
    nothing makes them do. Now the card can warn on a save either way. `None`
    for a format the admin marked as never published: there is no address to
    judge, and `false` would read as a complaint about one.
    """
    try:
        save_edition(body.family, body.fiscal_year, body.single_file, body.linked_toc)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err
    return {
        "ok": True,
        "names_its_year": {
            "single_file": (
                names_its_year(body.single_file, body.fiscal_year)
                if body.single_file else None
            ),
            "linked_toc": (
                names_its_year(body.linked_toc, body.fiscal_year)
                if body.linked_toc else None
            ),
        },
    }


class UrlCheck(BaseModel):
    url: str
    fiscal_year: int


@router.post("/api/admin/book-formats/check")
def check_url(body: UrlCheck, request: Request, _s=Depends(require_admin)) -> dict:
    """Does a typed address respond, how big is it, does it name its year?

    The same three facts `_candidate` reports, so a pasted link and an offered
    one are described identically on the card.

    🔴 A YEAR MISMATCH IS FLAGGED AND NEVER REFUSED (spec R6). It is tempting to
    reject any address that does not carry its own fiscal year, because that is
    the one defect a `200 OK` cannot detect — a live, downloadable, WRONG-year
    report behind a button. But exactly one genuinely year-less address exists:
    `budget/apprpttoc.pdf`, verified by download on 2026-08-16 to serve the real
    FY2023 Appropriations Report, because JLBC published that edition out of its
    undated directory. Refusing it would make the one edition that needs a hand
    correction the one edition the admin cannot correct. So this reports the
    fact and Task 5's card warns on it; the admin decides.

    The SCHEME, by contrast, is refused outright and before any request — the
    same one rule `store.report_formats.save_edition` applies, checked here too
    so the two answers agree and so this route never fetches an address the
    admin could not save anyway. A refusal comes back in the ordinary `reason`
    field rather than as an error, because to the admin it is the same kind of
    news as "that address didn't respond".
    """
    try:
        require_web_url(body.url)
    except ValueError as err:
        return {
            "ok": False,
            "status": None,
            "bytes": None,
            "names_its_year": False,
            "reason": str(err),
        }
    try:
        status, size = _probe_with(request).head_info(body.url)
    except Exception:  # noqa: BLE001 — offline is an answer, not a 500
        status, size = None, None
    reason = None
    if status is None:
        reason = "That address didn't respond. Check it, or try again later."
    elif status >= 400:
        reason = f"That address answered {status}, so nothing would download."
    return {
        "ok": status is not None and status < 400,
        "status": status,
        "bytes": size,
        "names_its_year": names_its_year(body.url, body.fiscal_year),
        "reason": reason,
    }
