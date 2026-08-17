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
from app.routes.books_missing import FAMILY_LABELS, corpus_editions
from ingest.book_discovery import DiscoveryError, plan_edition
from store.config import data_dir
from store.report_formats import format_key, load, names_its_year, save_edition

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


class _NetworkWatch:
    """Wraps the prober so "offline" is distinguishable from "never published".

    🔴 THIS IS NOT DEFENSIVE PADDING; WITHOUT IT THE OFFLINE BRANCH IS DEAD
    CODE. Two facts, both read out of the shipped source rather than assumed:

      * `ingest/book_discovery.py::_first_live` catches EVERY exception per
        rung and moves to the next one, and when no rung answers,
        `plan_edition` raises `DiscoveryError` -- the very same signal it
        raises for "JLBC has not published this edition".
      * `app/routes/books.HttpProber.head` never raises at all; it swallows
        `requests.RequestException` and returns `False`.

    So with the WiFi off, the real prober reports every candidate as "not
    there", the ladder raises `DiscoveryError`, and a panel that trusted that
    would say "nothing needs a link" -- a confident wrong answer manufactured
    by a network failure, on an app that is verified to cold-start offline.

    The fix costs no extra requests: route every rung through `head_info`,
    which reports `(None, None)` for "the host never answered" and `(404, None)`
    for "the host said no". Counting those two apart is the whole mechanism.
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.answered = 0
        self.unreachable = 0
        # One question per address per edition. The ladder asks about a rung and
        # then `_candidate` asks about the very rung it returned, so without this
        # every probed edition costs two identical requests for the same answer.
        # Scoped to one edition, which is this object's whole lifetime, so it can
        # never serve a stale answer across a refresh.
        self._seen: dict[str, tuple[int | None, int | None]] = {}

    def head(self, url: str) -> bool:
        # `_first_live` calls this. Answering it out of `head_info` keeps the
        # boolean identical (a status under 400 is live, an unreachable host is
        # not) while recording WHICH kind of "no" it was.
        status, _ = self.head_info(url)
        return status is not None and status < 400

    def head_info(self, url: str) -> tuple[int | None, int | None]:
        if url in self._seen:
            return self._seen[url]
        try:
            status, size = self._inner.head_info(url)
        except Exception:  # noqa: BLE001 — DNS, timeout, a fake that raises
            self.unreachable += 1
            return None, None      # deliberately NOT memoised: retry is cheap
        if status is None:
            self.unreachable += 1
        else:
            self.answered += 1
        self._seen[url] = (status, size)
        return status, size


@dataclass
class _Probe:
    """One edition's lookup: what was found, and how it went."""

    candidates: dict = field(default_factory=dict)
    source: str | None = None
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
            source=hit.get("source"),
        )

    watch = _NetworkWatch(prober)
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

    source = getattr(plan, "source", None)
    cache[key] = {
        "checked_at": datetime.now(timezone.utc).isoformat(),
        "source": source,
        **found,
    }
    return _Probe(candidates=found, source=source, probed=True)


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
                "source": probe.source,
            })

    if dirty and online:
        _write_cache(cache)

    return {
        "online": online,
        "reason": reason,
        "problems": problems,
        "pending": sorted(pending, key=lambda p: (-p["fiscal_year"], p["family"])),
        # `approved` is not decoration. Without it the panel can only show
        # editions nobody has answered, so approving a WRONG link would be
        # unfixable from the app and the admin would be back to hand-editing
        # JSON on the share — the exact thing this feature exists to abolish.
        "approved": sorted(
            (
                {
                    "family": key.rpartition(":")[0],
                    "fiscal_year": int(key.rpartition(":")[2]),
                    "single_file": row.single_file,
                    "linked_toc": row.linked_toc,
                }
                for key, row in table.items()
            ),
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
    """
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
