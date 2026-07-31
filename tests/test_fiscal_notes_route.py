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
    # No live directory here, so _source() falls back to the patched snapshot.
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(fn, "SNAPSHOT", p)
    # Plan 3 replaced lru_cache with a file-signature cache (a refresh has to
    # be visible without a restart); clear it the same way the route does.
    fn._cache = None
    try:
        assert [s["year"] for s in fn._load()["sessions"]] == [2026, 2022, 2019]
    finally:
        fn._cache = None  # don't leak the tmp fixture into other tests
