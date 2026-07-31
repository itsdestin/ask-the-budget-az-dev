"""Tests for ingest/fiscal_notes_refresh.py (spec S10)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from ingest.fiscal_notes_refresh import (
    SESSION_URL,
    diff_against_directory,
    directory_path,
    fetch_session,
    load_directory,
    run_refresh,
)

FIXTURE_HTML = (
    Path(__file__).resolve().parent.parent
    / "webapp" / "reference" / "fiscal-notes-build" / "live" / "2026.html"
)


@pytest.fixture()
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return tmp_path


@pytest.fixture()
def empty_2026(data_dir):
    """A live directory that knows about 2026 but has no notes for it yet.

    Needed because load_directory() falls back to the COMMITTED snapshot,
    which already contains all 112 of the 2026 session's notes — so a refresh
    against a virgin data dir correctly finds nothing new.
    """
    (data_dir / "fiscal-notes-directory.json").write_text(
        json.dumps({"sessions": [{"year": 2025, "name": "prior", "bills": []}]}),
        encoding="utf-8",
    )
    return data_dir


class FakeSite:
    """Serves the vendored session page for any year, PDFs as bytes."""

    def __init__(self, html: str | None = None) -> None:
        self.html = html if html is not None else FIXTURE_HTML.read_text(
            encoding="utf-8", errors="replace"
        )
        self.urls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.urls.append(url)
        if "fiscal-notes/?Year=" in url:
            return self.html.encode("utf-8")
        return b"%PDF-1.4 fiscal note"


# --- scraping ---------------------------------------------------------------


def test_fetch_session_hits_the_right_url_and_parses_rows(data_dir):
    site = FakeSite()
    rows = fetch_session(2026, site)
    assert site.urls == [SESSION_URL.format(year=2026)]
    assert rows
    assert set(rows[0]) == {"bill_number", "title", "fiscal_note_url"}
    assert all("/fiscal/" in r["fiscal_note_url"] for r in rows)


def test_diff_returns_only_rows_the_directory_lacks():
    parsed = [
        {"bill_number": "HB 2001", "title": "a", "fiscal_note_url": "u1"},
        {"bill_number": "SB 1010", "title": "b", "fiscal_note_url": "u2"},
    ]
    directory = {"sessions": [
        {"year": 2026, "bills": [
            {"bill_number": "HB 2001", "fiscal_note_url": "u1"},
        ]},
    ]}
    fresh = diff_against_directory(parsed, directory, 2026)
    assert [r["bill_number"] for r in fresh] == ["SB 1010"]


def test_diff_treats_a_revised_note_as_new():
    """bill_number is not unique — a revised note is a separate document."""
    parsed = [
        {"bill_number": "SB 1010", "title": "orig", "fiscal_note_url": "SB1010.pdf"},
        {"bill_number": "SB 1010", "title": "rev", "fiscal_note_url": "SB1010R.pdf"},
    ]
    directory = {"sessions": [
        {"year": 2026, "bills": [
            {"bill_number": "SB 1010", "fiscal_note_url": "SB1010.pdf"},
        ]},
    ]}
    fresh = diff_against_directory(parsed, directory, 2026)
    assert [r["fiscal_note_url"] for r in fresh] == ["SB1010R.pdf"]


def test_diff_ignores_other_sessions():
    parsed = [{"bill_number": "HB 2001", "title": "a", "fiscal_note_url": "u1"}]
    directory = {"sessions": [
        {"year": 2025, "bills": [{"bill_number": "HB 2001", "fiscal_note_url": "u1"}]},
    ]}
    assert len(diff_against_directory(parsed, directory, 2026)) == 1


# --- the full refresh -------------------------------------------------------


def test_refresh_writes_the_directory_and_queues_new_notes(empty_2026):
    site = FakeSite()
    queued = []
    result = run_refresh(fetcher=site, years=[2026], enqueue=queued.append)

    directory = json.loads(directory_path().read_text(encoding="utf-8"))
    session = next(s for s in directory["sessions"] if s["year"] == 2026)
    assert session["bills"]
    assert session["name"] == "57th Legislature, 2nd Reg. Session (2026)"
    assert result["queued"] == len(queued) > 0


def test_queued_jobs_target_the_fiscal_note_corpus(empty_2026):
    site = FakeSite()
    queued = []
    run_refresh(fetcher=site, years=[2026], enqueue=queued.append)
    job = queued[0]
    assert job.corpus == "fiscal_notes"
    assert job.doc_type == "fiscal-note"
    assert job.doc_id.startswith("legislature-fiscal-note-fy2026-")
    assert job.source_url.startswith("http")


def test_note_pdfs_land_in_the_shared_pdfs_dir(empty_2026):
    site = FakeSite()
    queued = []
    run_refresh(fetcher=site, years=[2026], enqueue=queued.append)
    landed = empty_2026 / queued[0].source_path
    assert landed.is_file()
    assert landed.read_bytes() == b"%PDF-1.4 fiscal note"


def test_a_second_refresh_queues_nothing_new(empty_2026):
    site = FakeSite()
    run_refresh(fetcher=site, years=[2026], enqueue=lambda j: None)
    queued = []
    result = run_refresh(fetcher=site, years=[2026], enqueue=queued.append)
    assert result["queued"] == 0 and queued == []


def test_doc_ids_are_unique_per_note(empty_2026):
    site = FakeSite()
    queued = []
    run_refresh(fetcher=site, years=[2026], enqueue=queued.append)
    ids = [j.doc_id for j in queued]
    assert len(ids) == len(set(ids))


# --- failure degrades to last-good ------------------------------------------


def test_a_failed_scrape_leaves_the_directory_untouched(empty_2026):
    site = FakeSite()
    run_refresh(fetcher=site, years=[2026], enqueue=lambda j: None)
    before = directory_path().read_bytes()

    def broken(url: str) -> bytes:
        raise ConnectionError("azjlbc.gov is unreachable")

    with pytest.raises(ConnectionError):
        run_refresh(fetcher=broken, years=[2026], enqueue=lambda j: None)
    assert directory_path().read_bytes() == before


def test_one_bad_year_does_not_half_write_the_other(data_dir):
    """All fetches must succeed before ANY session is replaced — a partial
    write would silently delete a session's notes."""
    calls = {"n": 0}

    def flaky(url: str) -> bytes:
        calls["n"] += 1
        if calls["n"] > 1:
            raise ConnectionError("dropped")
        return FIXTURE_HTML.read_text(encoding="utf-8", errors="replace").encode()

    with pytest.raises(ConnectionError):
        run_refresh(fetcher=flaky, years=[2026, 2025], enqueue=lambda j: None)
    assert not directory_path().exists()


def test_an_empty_page_does_not_wipe_a_session(empty_2026):
    """JLBC changing their markup must not read as 'this session has no
    notes'. The refresh fails loudly and the session's rows survive."""
    run_refresh(fetcher=FakeSite(), years=[2026], enqueue=lambda j: None)
    before = len(_session(2026)["bills"])
    assert before > 0

    with pytest.raises(RuntimeError, match="changed its page layout"):
        run_refresh(fetcher=FakeSite("<html>nothing here</html>"), years=[2026],
                    enqueue=lambda j: None)
    assert len(_session(2026)["bills"]) == before


# --- fallback ---------------------------------------------------------------


def test_directory_falls_back_to_the_committed_snapshot(data_dir):
    """A fresh install shows history on day one."""
    assert not directory_path().exists()
    directory = load_directory()
    assert len(directory["sessions"]) >= 20


def _session(year: int) -> dict:
    directory = json.loads(directory_path().read_text(encoding="utf-8"))
    return next(s for s in directory["sessions"] if s["year"] == year)
