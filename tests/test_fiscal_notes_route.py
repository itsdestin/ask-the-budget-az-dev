from fastapi.testclient import TestClient

from app.main import create_app


def test_fiscal_notes_serves_snapshot():
    r = TestClient(create_app()).get("/api/fiscal-notes")
    assert r.status_code == 200
    body = r.json()
    assert len(body["sessions"]) >= 20
    bill = body["sessions"][-1]["bills"][0]
    assert bill["chamber"] in ("H", "S")


def test_sessions_sorted_newest_first():
    body = TestClient(create_app()).get("/api/fiscal-notes").json()
    years = [s["year"] for s in body["sessions"]]
    assert years == sorted(years, reverse=True)
