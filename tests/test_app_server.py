from fastapi.testclient import TestClient

from app.main import create_app


def test_health_reports_provider():
    client = TestClient(create_app())
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["provider"] == "stub"


def test_spa_fallback_serves_index_when_built(tmp_path):
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    client = TestClient(create_app(static_dir=dist))
    # Unknown non-API path -> SPA index (client-side routing).
    r = client.get("/fiscal-notes")
    assert r.status_code == 200 and "app" in r.text


def test_missing_build_gives_plain_message():
    client = TestClient(create_app(static_dir=None))
    r = client.get("/")
    assert r.status_code == 200
    assert "not built" in r.text.lower()


def test_traversal_cannot_escape_static_dir(tmp_path):
    # A file OUTSIDE dist must never be served, even via an encoded "..".
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<html>app</html>")
    (tmp_path / "secret.txt").write_text("TOP-SECRET")
    client = TestClient(create_app(static_dir=dist))
    r = client.get("/%2e%2e/secret.txt")
    assert "TOP-SECRET" not in r.text


def test_real_static_asset_is_served_not_swallowed_by_fallback(tmp_path):
    # The SPA fallback must not shadow genuine build assets.
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<html>app</html>")
    (dist / "assets" / "x.js").write_text("console.log('asset');")
    client = TestClient(create_app(static_dir=dist))
    r = client.get("/assets/x.js")
    assert r.status_code == 200
    assert "console.log('asset')" in r.text


def test_api_routes_are_not_shadowed_by_catch_all():
    # Pinning test: the `/{path:path}` catch-all is registered last, so a real
    # /api/* route still wins, and an unknown /api path is a JSON 404 (not HTML).
    client = TestClient(create_app())
    r = client.post("/api/search", json={"query": "budget"})
    assert r.status_code == 200
    assert r.json()["provider"] == "stub"

    missing = client.get("/api/nonexistent")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Unknown API route"
