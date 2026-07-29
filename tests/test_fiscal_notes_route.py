import json

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


def test_load_sorts_unsorted_source(tmp_path, monkeypatch):
    # Guards _load()'s defensive sort against Plan 3's live source: the
    # committed snapshot is already descending on disk, so the route-level
    # test above would still pass if the sort line were deleted.
    from app.routes import fiscal_notes as fn

    p = tmp_path / "snap.json"
    p.write_text(
        json.dumps({"sessions": [{"year": 2019}, {"year": 2026}, {"year": 2022}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(fn, "SNAPSHOT", p)
    fn._load.cache_clear()
    try:
        assert [s["year"] for s in fn._load()["sessions"]] == [2026, 2022, 2019]
    finally:
        fn._load.cache_clear()  # don't leak the tmp fixture into other tests
