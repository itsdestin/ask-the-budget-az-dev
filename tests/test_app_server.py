import time

import pytest
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


# --- static caching (2026-07-31) -------------------------------------------
# A new logo shipped at the same URL and browsers kept serving the old one;
# separately, a cached index.html pinned the superseded hashed bundles, so the
# whole UI looked un-updated. Both are cache-header bugs, not build bugs.


def test_index_html_is_revalidated_not_blindly_reused(tmp_path):
    """index.html must never be served from cache without asking.

    It names the hashed bundles, so a stale copy pins the whole old app —
    the update lands on the server and nobody sees it. `no-cache` still
    allows storage; it just forces the conditional request.
    """
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    client = TestClient(create_app(provider=StubSearchProvider(), static_dir=tmp_path))
    for url in ("/", "/search", "/ai"):  # every SPA route serves index.html
        r = client.get(url)
        assert r.status_code == 200
        assert r.headers["cache-control"] == "no-cache", url


def test_fingerprinted_assets_are_cached_hard(tmp_path):
    """Vite renames on every build, so an assets/ URL can never go stale."""
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-ABC123.css").write_text("body{}")
    client = TestClient(create_app(provider=StubSearchProvider(), static_dir=tmp_path))
    r = client.get("/assets/index-ABC123.css")
    assert r.status_code == 200
    assert "immutable" in r.headers["cache-control"]


def test_unfingerprinted_public_files_are_revalidated(tmp_path):
    """The logo keeps its filename across rebuilds — it must be rechecked.

    This is the exact file that shipped stale.
    """
    (tmp_path / "index.html").write_text("<!doctype html><title>x</title>")
    (tmp_path / "jlbc-logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    client = TestClient(create_app(provider=StubSearchProvider(), static_dir=tmp_path))
    r = client.get("/jlbc-logo.png")
    assert r.status_code == 200
    assert r.headers["cache-control"] == "no-cache"


# --- the ingest worker actually runs (2026-07-31) ----------------------------
#
# The worker used to be CONSTRUCTED at startup but only ever `.start()`ed by
# the upload route. On the shared office drive that meant a colleague's queued
# job sat untouched until somebody on THAT machine happened to upload a file —
# ingest looked hung, with no error anywhere to explain it.
#
# The app now starts it from its startup handler, so any running server drains
# the queue. Starlette only runs startup/shutdown when the TestClient is used
# as a CONTEXT MANAGER, which is why the route tests above (bare `TestClient(...)`)
# still never spawn a thread.


@pytest.fixture()
def worker_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    # The per-machine ingest switch defaults to OFF (one bundle, ~20 office
    # PCs — see app/machine_config.py::ingest_enabled). These tests are about
    # what happens once a machine IS the ingest machine, so they opt in
    # explicitly. `test_the_queue_does_not_run_when_this_machine_is_not_the_
    # ingest_machine` below covers the default.
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "1")
    return tmp_path


def _fake_context(data_dir):
    """A WorkerContext with no ONNX models and no MinerU — same fakes the
    worker suite uses, so this exercises the real pipeline in milliseconds."""
    from chunking.entity_stamper import EntityStamper
    from ingest.worker import WorkerContext
    from store.chunk_store import ChunkStore
    from tests.test_ingest_worker import FakeEmbedder, FakeExtractor

    return WorkerContext(
        store=ChunkStore(root=data_dir, dim=8),
        embedder=FakeEmbedder(),
        stamper=EntityStamper.from_default_paths(fund_catalog_path=None),
        extractor=FakeExtractor(),
    )


def _queue_a_job(data_dir):
    from ingest.jobs import new_job, save

    source = data_dir / "uploads" / "cd" / f"{'cd' * 32}.pdf"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(b"%PDF-1.4\n")
    job = new_job(
        doc_id="jlbc-baseline-fy2027-axs",
        title="FY 2027 Baseline — AHCCCS",
        corpus="budget",
        source_path=str(source.relative_to(data_dir)),
        source_sha256="cd" * 32,
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2027,
    )
    save(job)
    return job


def test_a_queued_job_runs_with_no_upload_activity(worker_data_dir):
    """The regression: a job nobody uploaded on THIS machine still gets run.

    This is the whole defect. Before the fix the queue only drained after a
    POST to /api/upload, so a colleague's job could sit queued forever.
    """
    from ingest.jobs import load_job
    from ingest.worker import IngestWorker

    job = _queue_a_job(worker_data_dir)
    worker = IngestWorker(ctx=_fake_context(worker_data_dir), poll_interval_s=0.01)
    app = create_app(provider=StubSearchProvider(), static_dir=None,
                     ingest_worker=worker)

    try:
        with TestClient(app) as client:          # runs startup — no upload made
            assert client.get("/health").status_code == 200
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if load_job(job.job_id).state == "live":
                    break
                time.sleep(0.05)
    finally:
        worker.stop()

    assert load_job(job.job_id).state == "live"


def test_the_queue_does_not_run_when_this_machine_is_not_the_ingest_machine(
    worker_data_dir, monkeypatch, capsys
):
    """One bundle goes on all ~20 office PCs and launcher.pyw calls
    `create_app()` with no arguments. Without the per-machine switch every
    one of them starts a worker against the single shared queue — safe
    (IngestLock), but the winner is arbitrary and may be an analyst's
    laptop that then spends six hours at 100% CPU on a Baseline book.

    The server must still serve; only the queue stays idle. And it must
    SAY SO — "off by default" plus silence is the pile-up this switch was
    supposed to prevent, just relocated.
    """
    from ingest.jobs import load_job
    from ingest.worker import IngestWorker

    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")

    job = _queue_a_job(worker_data_dir)
    worker = IngestWorker(ctx=_fake_context(worker_data_dir), poll_interval_s=0.01)
    app = create_app(provider=StubSearchProvider(), static_dir=None,
                     ingest_worker=worker)

    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200   # still serving
            time.sleep(0.3)
    finally:
        worker.stop()

    assert load_job(job.job_id).state == "queued"
    assert "not set to process uploads" in capsys.readouterr().err


def test_starting_the_worker_twice_does_not_build_a_second_pool(worker_data_dir):
    """The factory and the upload route both start it; that must be one pool.

    Two pools would mean two threads racing for the same jobs and double the
    resident embedding model on a 16 GB office PC.
    """
    from ingest.worker import IngestWorker, ensure_started

    worker = IngestWorker(ctx=_fake_context(worker_data_dir), poll_interval_s=0.01)
    app = create_app(provider=StubSearchProvider(), static_dir=None,
                     ingest_worker=worker)
    try:
        with TestClient(app):
            threads = list(worker._threads)
            assert threads, "startup did not start the worker"
            # What the upload route does on every POST.
            worker.start()
            ensure_started(app)
            assert list(worker._threads) == threads
            assert app.state.ingest_worker is worker
    finally:
        worker.stop()


def test_the_app_still_boots_when_the_worker_cannot_start(worker_data_dir, capsys):
    """An unreachable share must degrade to "search is broken", not "no app".

    If a failure to start the queue took the whole server down, the office
    would lose the search UI — and the health ladder that explains WHY — over
    a problem that only affects ingest.
    """
    class ExplodingWorker:
        def start(self):
            raise OSError("\\\\office-nas\\jlbc is unreachable")

        def stop(self, timeout_s: float = 0):
            pass

    app = create_app(provider=StubSearchProvider(), static_dir=None,
                     ingest_worker=ExplodingWorker())
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json()["ok"] is True
    # And it must say what actually went wrong — not a guess, the real error.
    assert "office-nas" in capsys.readouterr().err


def test_a_missing_data_dir_does_not_crash_boot(tmp_path, monkeypatch):
    """The concrete unreachable-share case: JLBC_DATA_DIR points at nothing."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "not-mounted" / "jlbc"))
    app = create_app(provider=StubSearchProvider(), static_dir=None)
    worker = app.state.ingest_worker
    try:
        with TestClient(app) as client:
            assert client.get("/health").status_code == 200
    finally:
        worker.stop()


def test_passing_no_worker_is_an_explicit_opt_out(worker_data_dir):
    """`create_app(ingest_worker=None)` = "this process must not run ingest".

    The DEFAULT is that a real server drains the queue, so opting out has to
    be something a person typed on purpose. Without this the opt-out would
    silently build a worker anyway (`ensure_started` creates one when it finds
    none), which is exactly the surprise this seam exists to prevent.
    """
    from ingest.jobs import load_job

    job = _queue_a_job(worker_data_dir)
    app = create_app(provider=StubSearchProvider(), static_dir=None,
                     ingest_worker=None)
    with TestClient(app) as client:
        assert client.get("/health").status_code == 200
        time.sleep(0.3)
    assert app.state.ingest_worker is None
    assert load_job(job.job_id).state == "queued"      # nothing ran it


def test_a_bare_test_client_never_spawns_an_ingest_thread(worker_data_dir):
    """Pinning test for why the route suites above stay thread-free.

    Every other app test builds `TestClient(create_app(...))` without the
    `with`, which skips Starlette's startup event. If that ever changes, this
    fails here rather than as a mysterious slowdown across the whole suite.
    """
    from ingest.worker import IngestWorker

    worker = IngestWorker(ctx=_fake_context(worker_data_dir), poll_interval_s=0.01)
    TestClient(create_app(provider=StubSearchProvider(), static_dir=None,
                          ingest_worker=worker))
    assert worker._threads == []
