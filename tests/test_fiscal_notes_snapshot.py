"""Validates the committed snapshot artifact, not the scraper —
Plan 3 owns live scraping. This guards the API contract's data shape."""
import json
from pathlib import Path

# Anchored to the repo root so the test passes from any working directory.
SNAPSHOT = Path(__file__).resolve().parents[1] / "app/data/fiscal-notes-snapshot.json"

# Exact counts, not lower bounds: this snapshot is FROZEN (Plan 3 replaces the
# data source wholesale). Nothing should change it in place, so drift here means
# someone re-derived it — which should be a deliberate, reviewed act that updates
# these numbers in the same commit, not a silent diff.
EXPECTED_SESSIONS = 28    # live/*.html cache covers 1999-2026
EXPECTED_BILLS = 2126     # 37-135 per session; Plan 2's pre-read "~98" guess was just wrong


def test_snapshot_exists_and_has_sessions():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(data["sessions"], list)
    assert len(data["sessions"]) == EXPECTED_SESSIONS


def test_bills_have_contract_fields():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    total = 0
    for s in data["sessions"]:
        assert isinstance(s["year"], int) and s["name"]
        for b in s["bills"]:
            assert b["bill_number"] and b["title"]
            assert b["chamber"] in ("H", "S")
            # fiscal_note_url is part of the frozen contract and is the ONLY
            # field distinguishing the 93 rows that share a bill_number with
            # another row in the same session (original vs. revised note).
            assert b["fiscal_note_url"].startswith("https://")
            assert "&amp;" not in b["fiscal_note_url"]   # HTML entity was decoded
            total += 1
    assert total == EXPECTED_BILLS
