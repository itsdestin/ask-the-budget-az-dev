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
