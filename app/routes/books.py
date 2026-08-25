"""Add a JLBC book — catalog, discovery, and bulk enqueue.

This is how a colleague adds next year's Baseline after Destin is gone. The
three endpoints separate looking from doing on purpose: `catalog` and
`discover` touch nothing, so somebody can see exactly what a book contains —
and what's unreachable — before committing a machine to an overnight run.

Invariant 8 needs no checkbox here: everything reachable through these
endpoints is a JLBC-published document, which is public record by definition.
The upload page says so in a static notice rather than asking again.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from ingest.book_discovery import (
    DiscoveryError,
    EditionPlan,
    list_editions,
    plan_edition,
    walk_edition,
)
from ingest.driver import make_doc_id
from ingest.worker import revive_if_this_machine_ingests
from ingest.jobs import TERMINAL_STATES, load_active, new_job, save
from app.routes.upload import _documents

router = APIRouter()


class EditionBody(BaseModel):
    family: str = Field(pattern="^(approps|baseline)$")
    fiscal_year: int = Field(ge=1970, le=2100)


def _content_size(headers) -> int | None:
    """How big is this file, per the server's own headers?

    `Content-Range: bytes 0-0/49312768` carries the WHOLE file's size and is
    what a ranged request answers with; `Content-Length` on that same reply is
    `1`. Preferring the range total is therefore the difference between "47 MB"
    and "1 byte" on the admin's card.
    """
    raw_range = headers.get("Content-Range") or ""
    total = raw_range.rpartition("/")[2].strip()
    if total.isdigit():
        return int(total)
    raw_len = headers.get("Content-Length")
    return int(raw_len) if raw_len and str(raw_len).strip().isdigit() else None


class HttpProber:
    """Real network seam: HEAD to verify, GET to download.

    HEAD rather than GET for verification because a book edition means ~130
    checks and the bodies are megabytes each. Some IIS configurations answer
    405 to HEAD, so that falls back to a ranged GET rather than reporting the
    document missing.
    """

    def __init__(self, timeout_s: int = 30) -> None:
        self._timeout_s = timeout_s

    def head(self, url: str) -> bool:
        import requests

        try:
            r = requests.head(url, timeout=self._timeout_s, allow_redirects=True)
            if r.status_code == 405:
                r = requests.get(
                    url, timeout=self._timeout_s, stream=True,
                    headers={"Range": "bytes=0-0"},
                )
                r.close()
            return r.status_code < 400
        except requests.RequestException:
            return False

    def head_info(self, url: str) -> tuple[int | None, int | None]:
        """(HTTP status, size in bytes). `(None, None)` when the host never answered.

        WHY THIS IS A SECOND REQUEST PATH AND NOT A REFACTOR OF `head()`.
        The obvious tidy-up — have `head()` call this and fall back to a GET on
        any status >= 400 — was rejected on measured grounds. `head()` falls
        back only on a literal **405**, the one status IIS uses to say "I don't
        do HEAD", and its fallback GET asks for `Range: bytes=0-0`, i.e. one
        byte. Widening that to >= 400 would turn every **404** into a full,
        unranged GET: adding one book edition performs ~130 of these checks
        against files that are megabytes each, so a single missing 47 MB report
        would be downloaded in its entirety just to learn it is missing.
        Nothing in `tests/` drives `head()`'s real network path (every caller
        injects a fake), so that regression would have shipped green. Two small
        methods with one rule each is cheaper than one method with a footnote.

        The size is read from `Content-Range`'s total FIRST. The 405 fallback
        asks for a single byte, so its `Content-Length` is `1`; a card reporting
        a whole Appropriations Report as "1 byte" would fire exactly the
        "this is visibly the wrong file" alarm that spec R9 reserves for real
        trouble. `None` when the server states no size at all — an unknown size
        must read as unknown, never as zero.
        """
        import requests

        try:
            r = requests.head(url, timeout=self._timeout_s, allow_redirects=True)
            if r.status_code == 405:
                r = requests.get(
                    url, timeout=self._timeout_s, stream=True,
                    headers={"Range": "bytes=0-0"},
                )
                r.close()
            return r.status_code, _content_size(r.headers)
        except requests.RequestException:
            return None, None

    def get(self, url: str) -> bytes:
        import requests

        r = requests.get(url, timeout=self._timeout_s)
        r.raise_for_status()
        return r.content


def _prober(request: Request):
    """Tests inject a fake through app.state; production gets the real one."""
    return getattr(request.app.state, "book_prober", None) or HttpProber()


class NetworkWatch:
    """Wraps the prober so "offline" is distinguishable from "never published".

    🔴 THIS IS NOT DEFENSIVE PADDING; WITHOUT IT THE OFFLINE BRANCH IS DEAD
    CODE. Two facts, both read out of the shipped source rather than assumed:

      * `ingest/book_discovery.py::_first_live` catches EVERY exception per
        rung and moves to the next one, and when no rung answers,
        `plan_edition` raises `DiscoveryError` -- the very same signal it
        raises for "JLBC has not published this edition".
      * `HttpProber.head` (above) never raises at all; it swallows
        `requests.RequestException` and returns `False`.

    So with the WiFi off, the real prober reports every candidate as "not
    there", the ladder raises `DiscoveryError`, and a caller that trusted
    that would say "nothing needs a link" -- a confident wrong answer
    manufactured by a network failure, on an app that is verified to
    cold-start offline.

    The fix costs no extra requests: route every rung through `head_info`,
    which reports `(None, None)` for "the host never answered" and `(404,
    None)` for "the host said no". Counting those two apart is the whole
    mechanism.

    HOISTED (2026-08-22) out of `app/routes/book_formats.py`, where it was
    `_NetworkWatch` and scoped to ONE book edition (a fresh instance per
    call). `app/routes/books_missing.py` shares ONE instance across its
    WHOLE lookahead loop -- several editions, several fiscal years -- and
    that is only safe because of a property this class does not advertise
    loudly enough on its own: an UNREACHABLE result is deliberately never
    memoised (below -- "retry is cheap"), but a REAL answer IS memoised, for
    the life of the watch. `ingest/book_discovery.py`'s approps TOC ladder
    has exactly one rung that is IDENTICAL across every fiscal year --
    `https://www.azjlbc.gov/budget/apprpttoc.pdf`, JLBC's rolling directory,
    with no year anywhere in the path. A caller that shares one watch across
    years will get that rung back from `_seen` on the second and later years
    it is tried, with ZERO counter movement for that specific rung -- no
    request, no `answered` increment, no `unreachable` increment. That is
    safe PROVIDED a caller's "are we offline" rule is `unreachable and not
    answered` (an unreachable rung with nothing else to show for the
    period), never `not answered` alone -- a rung contributing (0, 0)
    trivially satisfies "not answered" without meaning anything went wrong.
    Pinned in `tests/test_books_missing.py` (the "ONE watch across the whole
    lookahead loop" section): a URL answered in year N and reused with zero
    delta in year N+1 must never read as "the network went down".
    """

    def __init__(self, inner) -> None:
        self._inner = inner
        self.answered = 0
        self.unreachable = 0
        # One question per address per edition. The ladder asks about a rung and
        # then `_candidate` asks about the very rung it returned, so without this
        # every probed edition costs two identical requests for the same answer.
        # Scoped to one edition in `book_formats.py` (this object's whole
        # lifetime there); `books_missing.py` deliberately widens that scope to
        # the whole lookahead loop -- see the class docstring above for why that
        # is still safe.
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


def _batch_id_for(family: str, fiscal_year: int) -> str:
    """The batch every document of one book edition shares.

    Family AND year, because both books number their sections identically —
    keying on either alone would merge two genuinely separate editions into
    one restore point. Same reasoning as the `family=` argument to
    `make_doc_id` just below.
    """
    return f"jlbc-{family}-fy{fiscal_year}"


@router.get("/api/books/catalog")
def catalog():
    return {"editions": list_editions()}


@router.post("/api/books/discover")
def discover(body: EditionBody, request: Request):
    plan = _plan(body, request)
    return {
        "source": plan.source,
        "count": len(plan.documents),
        "documents": [
            {"url": d.url, "title": d.title, "doc_type": d.doc_type, "code": d.code}
            for d in plan.documents
        ],
        "unreachable": plan.unreachable,
        "notes": plan.notes,
        "single_file_url": plan.single_file_url,
        "linked_toc_url": plan.linked_toc_url,
    }


@router.post("/api/books/ingest", status_code=202)
def ingest(body: EditionBody, request: Request):
    plan = _plan(body, request)
    known = {
        entry.get("source_url")
        for entry in _documents().values()
        if entry.get("source_url")
    }
    pending = {
        # load_active(): the same set as load_all() under this filter,
        # since every archived job is terminal. A URL that has finished is
        # in `known` (documents.json) just above.
        job.source_url for job in load_active()
        if job.state not in TERMINAL_STATES and job.source_url
    }

    queued, skipped = [], []
    for doc in plan.documents:
        if doc.url in known or doc.url in pending:
            skipped.append(doc.url)
            continue
        job = new_job(
            # `family` is load-bearing, not decoration: both books number
            # their sections the same way, so the doc_type alone cannot say
            # which book `508.pdf` came from. Without it the two books mint
            # the same doc_id and the second ingest silently overwrites the
            # first. This route is the only place that knows the family.
            doc_id=make_doc_id(
                publisher="jlbc", doc_type=doc.doc_type,
                fiscal_year=doc.fiscal_year, filename=doc.url.rsplit("/", 1)[-1],
                family=plan.family,
            ),
            title=doc.title,
            corpus="budget",
            # Empty until the worker downloads it — the job carries the URL,
            # and DownloadCache resolves it at extraction time. Queuing 130
            # jobs must not mean downloading 130 PDFs up front.
            source_path="",
            source_sha256="",
            publisher="jlbc",
            doc_type=doc.doc_type,
            fiscal_year=doc.fiscal_year,
            user_title=doc.title,
            source_url=doc.url,
            # One restore point per BOOK EDITION rather than per document.
            # An edition is ~130 documents; snapshotting each would zip the
            # whole corpus 130 times, and the edition is the unit somebody
            # would actually roll back anyway. See
            # ingest/worker.py::_should_snapshot.
            batch_id=_batch_id_for(plan.family, doc.fiscal_year),
        )
        save(job)
        queued.append(job.job_id)

    # 🔴 GATED (2026-08-16) — see ingest/worker.py's
    # `revive_if_this_machine_ingests`. THIS was the worst of the two
    # bypasses: a book is ~140 documents and hours of CPU, so an analyst
    # pressing Add here is precisely the request that used to conscript
    # their own laptop into doing it, on a machine the office had set not
    # to. The jobs are queued regardless; the machine that ingests picks
    # them up.
    revive_if_this_machine_ingests(request.app)

    return {
        "queued": len(queued),
        "job_ids": queued,
        "skipped_existing": len(skipped),
        "unreachable": plan.unreachable,
    }


def _plan(body: EditionBody, request: Request) -> EditionPlan:
    prober = _prober(request)
    try:
        plan = plan_edition(body.family, body.fiscal_year, prober=prober)
        return walk_edition(plan, prober=prober)
    except DiscoveryError as exc:
        # 502: the failure is upstream (azjlbc.gov changed, or the edition
        # isn't published), not a bad request. The message is what the UI
        # shows, so it stays in plain language.
        raise HTTPException(status_code=502, detail=str(exc)) from exc
