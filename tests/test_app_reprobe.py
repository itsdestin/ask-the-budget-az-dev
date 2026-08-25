"""While the app is on the stub provider it re-probes the corpus (spec §3.3).

Before 2026-08-25 the provider was chosen ONCE at startup: a share that
hiccupped at 8 AM meant fake fixture rows all day, and a repair from the
health screen told the analyst to 'reopen the app' — which the launcher
turns into a no-op by reusing the running server.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import app.main as main_mod
from app.main import create_app


from app.search_provider import SearchOutcome  # the dataclass the route unpacks


class FakeLance:
    """Stands in for LanceSearchProvider. The route DOES call search() after
    the swap, so return a real empty outcome (the route turns exceptions into
    a 503, which would hide a swap that happened)."""
    name = "lance"

    def search(self, *a, **k):
        return SearchOutcome(rows=[], inferred_fiscal_years=[], inferred_doc_types=[],
                             dropped_filters=[])


# WHY every test here (and every fake `name = "stub"` provider elsewhere)
# is safe: tests/conftest.py isolates JLBC_DATA_DIR to a temp dir, so the
# re-probe's ChunkStore(create=False) raises FileNotFoundError and never
# touches a real corpus. That autouse fixture is what keeps CLAUDE.md's
# "nothing in tests/ opens a real LanceDB" rule true for this feature.
@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))


def _app(monkeypatch, probe_results):
    calls = []

    def probe():
        calls.append(1)
        return probe_results.pop(0)

    monkeypatch.setattr(main_mod, "_probe_provider", probe)
    app = create_app(ingest_worker=None)
    return app, calls


def test_startup_falls_to_stub_when_the_probe_fails(monkeypatch):
    app, calls = _app(monkeypatch, [None])
    assert app.state.provider.name == "stub"
    assert calls == [1]


def test_a_search_while_stub_reprobes_and_swaps(monkeypatch):
    app, calls = _app(monkeypatch, [None, FakeLance()])
    now = [1000.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: now[0])
    client = TestClient(app)
    now[0] += 60
    client.post("/api/search", json={"query": "x"})
    assert app.state.provider.name == "lance"
    assert len(calls) == 2


def test_reprobes_are_rate_limited(monkeypatch):
    app, calls = _app(monkeypatch, [None, None, None])
    now = [1000.0]
    monkeypatch.setattr(main_mod.time, "monotonic", lambda: now[0])
    client = TestClient(app)
    now[0] += 60
    client.post("/api/search", json={"query": "x"})
    client.post("/api/search", json={"query": "y"})  # inside the window
    assert len(calls) == 2
    now[0] += 60
    client.post("/api/search", json={"query": "z"})
    assert len(calls) == 3


def test_a_real_provider_never_reprobes_on_its_own(monkeypatch):
    app, calls = _app(monkeypatch, [FakeLance()])
    app.state.reprobe()
    assert len(calls) == 1


def test_force_rebuilds_even_a_live_provider(monkeypatch):
    """The repair screen can appear on a machine that booted with a REAL
    corpus (the share rung fails later). Its provider then holds dead
    handles; a repair must rebuild it, not skip because it is 'not stub'."""
    first, second = FakeLance(), FakeLance()
    app, calls = _app(monkeypatch, [first, second])
    resets = []
    monkeypatch.setattr("retrieval.pipeline.reset_default_collaborators", lambda: resets.append(1))
    app.state.reprobe(force=True)
    assert app.state.provider is second
    assert resets == [1]


def test_the_probe_creates_nothing(monkeypatch, tmp_path):
    """Spec principle 3, at the site that actually created the laptop's
    folder: _default_provider() -> ChunkStore() used to mkdir <share>/lancedb."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    (tmp_path / "share").mkdir()
    assert main_mod._probe_provider() is None
    assert not (tmp_path / "share" / "lancedb").exists()


def test_a_bundle_with_no_pointer_boots_to_the_repair_screen(monkeypatch, tmp_path):
    """The laptop incident as a test: DEFAULT provider, VERSION at the root,
    no pointer, no env var, real lifespan. Boot must succeed, /health must
    answer, and the ladder must offer the box. Nothing else in the suite
    exercises DataDirNotConfigured propagating out of data_dir() at boot."""
    import store.config as config_mod

    monkeypatch.delenv("JLBC_DATA_DIR")
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)
    app = create_app(ingest_worker=None)  # default provider
    with TestClient(app) as client:
        assert client.get("/health").json()["provider"] == "stub"
        report = client.get("/api/health/detail").json()
        assert report["can_repair"] is True
        assert next(r for r in report["rungs"] if r["name"] == "machine_config")["ok"] is False


def test_saving_the_folder_swaps_at_once_and_resets_the_pipeline(monkeypatch, tmp_path):
    app, calls = _app(monkeypatch, [None, FakeLance()])
    monkeypatch.setattr("app.machine_config.validate_data_dir", lambda p: None)
    resets = []
    monkeypatch.setattr("retrieval.pipeline.reset_default_collaborators", lambda: resets.append(1))
    client = TestClient(app)
    r = client.post("/api/config/data-dir", json={"path": str(tmp_path / "share")})
    assert r.status_code == 200
    assert "restart_required" not in r.json()
    assert app.state.provider.name == "lance"
    assert resets == [1]
