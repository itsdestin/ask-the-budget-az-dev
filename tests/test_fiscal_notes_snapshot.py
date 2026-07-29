"""Validates the committed snapshot artifact, not the scraper —
Plan 3 owns live scraping. This guards the API contract's data shape."""
import json
from pathlib import Path

SNAPSHOT = Path("app/data/fiscal-notes-snapshot.json")


def test_snapshot_exists_and_has_sessions():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert isinstance(data["sessions"], list) and len(data["sessions"]) >= 20


def test_bills_have_contract_fields():
    data = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    total = 0
    for s in data["sessions"]:
        assert isinstance(s["year"], int) and s["name"]
        for b in s["bills"]:
            assert b["bill_number"] and b["title"]
            assert b["chamber"] in ("H", "S")
            total += 1
    assert total >= 90  # mockup reconciled ~98 real bills
