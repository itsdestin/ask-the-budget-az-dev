"""Live fiscal-note refresh (spec S10).

The fiscal-note coordinator's whole job is triaging new note requests against
prior notes, which only works if "prior notes" stays current across
legislative sessions. Plan 2 shipped the directory as a frozen snapshot of
the website mockup's scrape; this makes it live: fetch the newest sessions
from azjlbc.gov, diff against what we have, download only the new note PDFs,
and hand them to the normal ingest queue.

**Failure degrades to last-good, loudly.** If the scrape fails — the site is
down, or JLBC rewrites the page and the regex stops matching — the directory
file is left exactly as it was and the job fails with the real reason. A
partial write would silently delete sessions; a silent success would leave a
coordinator believing they'd searched notes that were never fetched.

The parse itself is the website mockup's, imported from
`scripts/export_fiscal_notes_snapshot.py` rather than re-derived: those
regexes are the citation for what a fiscal-note row looks like, and having
two copies drift is how the committed snapshot and the live data would stop
agreeing.
"""
from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Iterable

from ingest.cache import DownloadCache, Fetcher, _default_fetcher
from ingest.jobs import JobRecord, new_job, save
from scripts.export_fiscal_notes_snapshot import (
    chamber_of,
    leg_session,
    numkey,
    parse_session_html,
)
from store.config import data_dir

SESSION_URL = "https://www.azjlbc.gov/fiscal-notes/?Year={year}"
DIRECTORY_FILENAME = "fiscal-notes-directory.json"

# Only the newest two sessions are re-fetched. Older sessions are closed
# history — the legislature does not add fiscal notes to a session that ended
# years ago — so re-scraping 28 pages every refresh would be 26 pointless
# round-trips against a state web server.
REFRESH_SESSIONS = 2


def directory_path() -> Path:
    return data_dir() / DIRECTORY_FILENAME


def fetch_session(year: int, fetcher: Fetcher) -> list[dict]:
    """Scrape one session year's fiscal-note rows from azjlbc.gov."""
    html = fetcher(SESSION_URL.format(year=year)).decode("utf-8", errors="replace")
    return parse_session_html(html)


def diff_against_directory(
    parsed: Iterable[dict], directory: dict, year: int
) -> list[dict]:
    """Rows in `parsed` the directory doesn't already have for `year`.

    Keyed on (bill_number, fiscal_note_url), not the bill number: a bill can
    have an original AND a revised note, and both are real documents the
    coordinator needs to find.
    """
    known = {
        (b["bill_number"], b["fiscal_note_url"])
        for session in directory.get("sessions", [])
        if session.get("year") == year
        for b in session.get("bills", [])
    }
    fresh: list[dict] = []
    for row in parsed:
        key = (row["bill_number"], row["fiscal_note_url"])
        if key not in known:
            fresh.append(row)
    return fresh


def load_directory() -> dict:
    """The live directory if one exists, else the committed snapshot.

    Falling back to the snapshot (rather than an empty directory) means a
    fresh install shows 28 sessions of history on day one and the first
    refresh only adds what's new.
    """
    path = directory_path()
    if path.is_file():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except ValueError:
            # Corrupt live file — fall through to the snapshot rather than
            # serve nothing. The next successful refresh rewrites it.
            pass
    return _snapshot()


def write_directory(directory: dict) -> Path:
    """Atomically replace the directory file (tmp + os.replace).

    Whole-file rewrite is fine: it's ~460 KB, and a merge would need
    per-session conflict rules for data that has exactly one writer.
    """
    path = directory_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(directory, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    os.replace(tmp, path)
    return path


def run_refresh(
    *,
    fetcher: Fetcher | None = None,
    years: list[int] | None = None,
    enqueue: Callable[[JobRecord], None] | None = None,
    on_progress: Callable[[str], None] | None = None,
) -> dict:
    """Fetch the newest sessions, update the directory, queue new note PDFs.

    Returns `{years, new_notes, queued}`. Raises if any session fetch fails —
    the caller (the queue job) turns that into a failed job with the real
    error, and the directory file is untouched.
    """
    directory = load_directory()
    years = years or _newest_years(directory)
    enqueue = enqueue or _default_enqueue
    fetcher = fetcher or _default_fetcher

    fresh_by_year: dict[int, list[dict]] = {}
    parsed_by_year: dict[int, list[dict]] = {}
    for year in years:
        if on_progress:
            on_progress(f"reading the {year} session")
        parsed = fetch_session(year, fetcher)
        if not parsed and _existing_count(directory, year):
            # A session we already have notes for coming back empty means the
            # page changed shape, not that the notes were withdrawn. Replacing
            # it would silently delete the coordinator's history — the exact
            # "scraper breakage" S10 says must degrade to last-good. Fail the
            # whole refresh so nothing is written and the reason is visible.
            raise RuntimeError(
                f"The {year} session page returned no fiscal notes, but "
                f"{_existing_count(directory, year)} are already on file. "
                "azjlbc.gov has probably changed its page layout — the "
                "directory was left unchanged."
            )
        parsed_by_year[year] = parsed
        fresh_by_year[year] = diff_against_directory(parsed, directory, year)

    # Every fetch succeeded — only now touch the directory, so a failure
    # halfway through leaves last-good rather than a half-updated file.
    for year, parsed in parsed_by_year.items():
        _replace_session(directory, year, parsed)
    directory["sessions"].sort(key=lambda s: -s["year"])
    write_directory(directory)

    cache = DownloadCache(data_dir() / "pdfs", fetcher=fetcher)
    queued = 0
    for year, rows in fresh_by_year.items():
        for index, row in enumerate(rows):
            if on_progress:
                on_progress(f"downloading {row['bill_number']} ({year})")
            local = cache.fetch(row["fiscal_note_url"])
            job = new_job(
                doc_id=_note_doc_id(year, row["bill_number"], index),
                title=f"Fiscal Note — {row['bill_number']} ({year})",
                corpus="fiscal_notes",
                source_path=local.relative_to(data_dir()).as_posix(),
                source_sha256=cache.sha256_of(row["fiscal_note_url"]) or "",
                publisher="legislature",
                doc_type="fiscal-note",
                fiscal_year=year,
                user_title=f"Fiscal Note — {row['bill_number']}: {row['title']}",
                source_url=row["fiscal_note_url"],
            )
            enqueue(job)
            queued += 1

    return {
        "years": years,
        "new_notes": sum(len(v) for v in fresh_by_year.values()),
        "queued": queued,
    }


# --- internals --------------------------------------------------------------


def _default_enqueue(job: JobRecord) -> None:
    save(job)


def _replace_session(directory: dict, year: int, rows: list[dict]) -> None:
    """Swap in a freshly-scraped session, keeping the snapshot's row shape."""
    bills = [
        {
            "bill_number": r["bill_number"],
            "title": r["title"],
            "chamber": chamber_of(r["bill_number"]),
            "fiscal_note_url": r["fiscal_note_url"],
        }
        for r in sorted(rows, key=lambda r: numkey(r["bill_number"]))
    ]
    sessions = directory.setdefault("sessions", [])
    for session in sessions:
        if session.get("year") == year:
            session["name"] = leg_session(year)
            session["bills"] = bills
            return
    if bills:
        # A session with no notes yet (January of a new session) is not worth
        # an empty card on the page.
        sessions.append({"year": year, "name": leg_session(year), "bills": bills})


def _existing_count(directory: dict, year: int) -> int:
    for session in directory.get("sessions", []):
        if session.get("year") == year:
            return len(session.get("bills", []))
    return 0


def _newest_years(directory: dict) -> list[int]:
    """The two session years worth re-fetching.

    Anchored on the calendar year rather than on the directory's newest
    session: a brand-new session has no rows yet, so deriving from the data
    would never discover it.
    """
    current = datetime.now(timezone.utc).year
    return [current - offset for offset in range(REFRESH_SESSIONS)]


def _note_doc_id(year: int, bill_number: str, index: int) -> str:
    """`legislature-fiscal-note-fy2026-sb1010-0`.

    The trailing index disambiguates a bill's original note from its revised
    one — `bill_number` is NOT unique within a session (93 such pairs corpus
    -wide), so without it the second note would overwrite the first.
    """
    slug = re.sub(r"[^a-z0-9]", "", bill_number.lower())
    return f"legislature-fiscal-note-fy{year}-{slug}-{index}"


def _snapshot() -> dict:
    path = (
        Path(__file__).resolve().parent.parent
        / "app" / "data" / "fiscal-notes-snapshot.json"
    )
    if not path.is_file():
        return {"sessions": []}
    return json.loads(path.read_text(encoding="utf-8"))
