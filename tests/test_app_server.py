from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider

# Since Task 12, a bare create_app() PROBES for a migrated corpus and serves
# real retrieval when one exists — so any test that pins stub behavior must
# inject the stub explicitly, or it would pass or fail depending on whether
# the machine running it has corpus data.


def test_health_reports_provider():
    client = TestClient(create_app(provider=StubSearchProvider()))
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
    # 200 + index.html, i.e. the traversal was absorbed by the SPA fallback.
    # Asserting the status too keeps this from passing on an unrelated error page.
    assert r.status_code == 200
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
    client = TestClient(create_app(provider=StubSearchProvider()))
    r = client.post("/api/search", json={"query": "budget"})
    assert r.status_code == 200
    assert r.json()["provider"] == "stub"

    missing = client.get("/api/nonexistent")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "Unknown API route"

    # Bare /api must 404 as JSON too, not fall through to the SPA.
    bare = client.get("/api")
    assert bare.status_code == 404
    assert bare.json()["detail"] == "Unknown API route"


class _FalsyProvider:
    """Provider that is falsy but perfectly valid — pins the `is None` check."""

    name = "fake"

    def __bool__(self):
        return False

    def search(self, query, *, top_k, corpus, filters):
        return []


def test_falsy_injected_provider_is_not_replaced_by_stub():
    # Regression guard: `provider or StubSearchProvider()` (which Task 12's plan
    # text still shows) would silently discard this provider because it is falsy.
    client = TestClient(create_app(provider=_FalsyProvider()))
    assert client.get("/health").json()["provider"] == "fake"


class _FakeStore:
    """Stands in for ChunkStore so the probe's three branches run model-free."""

    behavior = "empty"  # overridden per test: "empty" | "populated" | "broken"

    def __init__(self, **kw):
        if self.behavior == "broken":
            raise RuntimeError("share unreachable")

    def count(self, name):
        return 7755 if self.behavior == "populated" else 0


def _probe_with(monkeypatch, behavior):
    from app import main as app_main

    _FakeStore.behavior = behavior
    monkeypatch.setattr("store.chunk_store.ChunkStore", _FakeStore)
    return app_main._default_provider()


def test_default_provider_uses_real_provider_when_corpus_has_rows(monkeypatch):
    assert _probe_with(monkeypatch, "populated").name == "lance"


def test_default_provider_falls_back_to_stub_on_empty_corpus(monkeypatch, capsys):
    assert _probe_with(monkeypatch, "empty").name == "stub"
    # The fallback must say WHY on stderr, not happen silently.
    assert "budget_chunks table is empty" in capsys.readouterr().err


def test_default_provider_falls_back_to_stub_when_probe_raises(monkeypatch, capsys):
    assert _probe_with(monkeypatch, "broken").name == "stub"
    assert "share unreachable" in capsys.readouterr().err


class _ExplodingProvider:
    """Provider whose search dies mid-request — the share-offline scenario."""

    name = "lance"

    def search(self, query, *, top_k, corpus, filters):
        raise OSError("network share unreachable")


def test_provider_failure_is_a_json_503_not_a_plain_500():
    # Without the route's try/except this would be FastAPI's PLAIN-TEXT
    # "Internal Server Error", which the web client's detail plumbing can't
    # parse — the user would see a bare status code with no cause.
    client = TestClient(
        create_app(provider=_ExplodingProvider()), raise_server_exceptions=False
    )
    r = client.post("/api/search", json={"query": "budget"})
    assert r.status_code == 503
    assert "network share unreachable" in r.json()["detail"]
