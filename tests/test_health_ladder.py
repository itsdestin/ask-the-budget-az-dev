"""The launch health ladder (Plan 5 Task 11, spec S18).

What this replaces: a stack trace. When the share moves, the app used to
fail somewhere deep in LanceDB and the person sitting in front of it saw
a Python traceback, or nothing at all.

The ladder walks five rungs — server, machine config, share, corpus,
models — and each one carries a sentence a non-technical admin can act
on. Two properties are pinned hard:

  * IT SHORT-CIRCUITS. An unreachable share must NOT also report
    "corpus: broken" as a second scary line. It can't read the corpus
    because it can't reach the folder; saying both sends an admin
    chasing a corruption that isn't there.
  * `GET /health`'s existing `{ok, provider}` shape is UNCHANGED. Plan 2's
    tests and the backfill scripts both depend on it.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.health import RUNGS, health_detail
from app.main import create_app
from app.search_provider import StubSearchProvider


@pytest.fixture(autouse=True)
def _isolated(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    yield


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def make_corpus(tmp_path) -> None:
    from store.chunk_store import ChunkStore

    ChunkStore(root=tmp_path / "share").ensure_tables()


def rung(report: dict, name: str) -> dict:
    return next(r for r in report["rungs"] if r["name"] == name)


# ---------------------------------------------------------------------------
# The existing /health contract
# ---------------------------------------------------------------------------


def test_the_old_health_shape_is_untouched(client):
    # Plan 2's tests AND the backfill scripts poll this. Adding fields to it
    # (rather than the new endpoint) would have been the easy mistake.
    body = client.get("/health").json()
    assert body == {"ok": True, "provider": "stub"}


def test_health_detail_needs_no_admin(client, monkeypatch):
    # It is what renders when NOTHING works, including identity. Gating it
    # would mean the one page that explains the failure is unreachable
    # during the failure.
    monkeypatch.setenv("JLBC_USER", "nobody-in-particular")
    assert client.get("/api/health/detail").status_code == 200


# ---------------------------------------------------------------------------
# The rungs
# ---------------------------------------------------------------------------


def test_a_healthy_ladder_reports_every_rung_ok(client, tmp_path):
    make_corpus(tmp_path)
    report = client.get("/api/health/detail").json()

    assert [r["name"] for r in report["rungs"]] == list(RUNGS)
    assert report["ok"] is True
    assert all(r["ok"] for r in report["rungs"])
    assert report["can_repair"] is False
    assert report["data_dir"] == str(tmp_path / "share")


def test_the_server_rung_is_ok_by_construction(client):
    # If you got a response, the server is up. Saying anything else would
    # be a lie the reader can disprove by being here.
    report = client.get("/api/health/detail").json()
    assert rung(report, "server")["ok"] is True


def test_an_unreachable_share_fails_with_an_actionable_sentence(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "not-there"))
    report = client.get("/api/health/detail").json()

    share = rung(report, "share")
    assert share["ok"] is False
    assert "shared" in share["detail"].lower() or "folder" in share["detail"].lower()
    # An actionable fix, not a diagnosis. The reader is a person standing
    # at a machine that won't start.
    assert share["fix"]
    assert report["ok"] is False


def test_the_ladder_short_circuits_after_the_first_failure(client, monkeypatch, tmp_path):
    """The property that decides whether an admin fixes the right thing.

    A missing share means the corpus cannot be read — reporting "corpus:
    broken" as a SECOND failure would send someone hunting a corruption
    that does not exist.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "not-there"))
    report = client.get("/api/health/detail").json()

    assert rung(report, "share")["ok"] is False
    for later in ("corpus", "models"):
        assert rung(report, later)["ok"] is None
        assert rung(report, later)["detail"] == "Not checked — fix the problem above first."


def test_can_repair_is_true_exactly_when_the_share_is_the_first_failure(
    client, monkeypatch, tmp_path
):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "not-there"))
    report = client.get("/api/health/detail").json()
    # This is what turns the failure screen into a repair screen: the app
    # can only offer "point me somewhere else" when the problem IS where
    # it is pointed.
    assert report["can_repair"] is True


def test_can_repair_is_false_when_the_corpus_is_the_problem(client, tmp_path):
    # The share is reachable, so relocating it fixes nothing. Offering the
    # repair box here would waste an admin's time on the wrong action.
    (tmp_path / "share").mkdir(parents=True, exist_ok=True)
    report = client.get("/api/health/detail").json()

    assert rung(report, "share")["ok"] is True
    assert rung(report, "corpus")["ok"] is False
    assert report["can_repair"] is False


def test_a_corrupt_machine_config_fails_its_own_rung(client, tmp_path):
    machine = tmp_path / "machine"
    machine.mkdir(parents=True, exist_ok=True)
    (machine / "machine.json").write_text("{ not json", encoding="utf-8")
    make_corpus(tmp_path)

    report = client.get("/api/health/detail").json()

    config = rung(report, "machine_config")
    assert config["ok"] is False
    assert config["fix"]
    # And it short-circuits, so nothing below it reports a scary second line.
    assert rung(report, "share")["ok"] is None


def test_missing_models_fail_the_last_rung(client, tmp_path, monkeypatch):
    make_corpus(tmp_path)
    monkeypatch.setattr("app.health._models_present", lambda: (False, "the search model files"))

    report = client.get("/api/health/detail").json()

    models = rung(report, "models")
    assert models["ok"] is False
    # On a packaged bundle the models ship pre-downloaded, so "missing"
    # means a broken install — not a download that hasn't happened yet.
    assert "install" in models["detail"].lower() or "install" in (models["fix"] or "").lower()
    assert report["can_repair"] is False


def test_every_failing_rung_carries_a_fix(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "not-there"))
    report = client.get("/api/health/detail").json()
    for r in report["rungs"]:
        if r["ok"] is False:
            assert r["fix"], f"{r['name']} failed with no suggested fix"


def test_no_rung_leaks_a_stack_trace(client, monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "not-there"))
    report = client.get("/api/health/detail").json()
    for r in report["rungs"]:
        blob = f"{r['detail']} {r['fix'] or ''}"
        assert "Traceback" not in blob
        assert "Error(" not in blob


# ---------------------------------------------------------------------------
# health_detail() called directly
# ---------------------------------------------------------------------------


def test_health_detail_never_raises(monkeypatch, tmp_path):
    """Whatever is broken, this function reports it — it does not become it.

    Everything else in the app is allowed to fail. This is the thing that
    explains the failure, so it has to survive conditions nothing else does.
    """
    monkeypatch.setattr(
        "app.health.resolve_data_dir",
        lambda: (_ for _ in ()).throw(OSError("share exploded")),
    )
    report = health_detail()
    assert report["ok"] is False
    assert any(r["ok"] is False for r in report["rungs"])


# ---------------------------------------------------------------------------
# The pointer failures the laptop actually hit (2026-08-18)
# ---------------------------------------------------------------------------


def test_a_bundle_with_no_pointer_fails_the_config_rung_and_can_repair(
    client, monkeypatch, tmp_path
):
    """The laptop (2026-08-18): first failing rung was machine_config, so
    can_repair was False, the folder box never rendered, and the only advice
    was 'delete this file by hand'."""
    import store.config as config_mod

    monkeypatch.delenv("JLBC_DATA_DIR")
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)

    report = client.get("/api/health/detail").json()

    config = rung(report, "machine_config")
    assert config["ok"] is False
    assert "hasn't been told" in config["detail"]
    assert "below" in config["fix"]
    assert report["can_repair"] is True
    assert rung(report, "share")["ok"] is None


def test_a_corrupt_pointer_offers_the_box_not_a_hand_edit(client, tmp_path):
    machine = tmp_path / "machine"
    machine.mkdir(parents=True, exist_ok=True)
    (machine / "machine.json").write_text("{ not json", encoding="utf-8")
    make_corpus(tmp_path)

    report = client.get("/api/health/detail").json()

    config = rung(report, "machine_config")
    assert "Delete this file" not in config["fix"]
    assert "below" in config["fix"]
    assert report["can_repair"] is True


def test_a_dev_checkout_with_no_pointer_is_still_fine(client, tmp_path):
    """Nothing changes for the dev box: no VERSION marker, no failure."""
    make_corpus(tmp_path)
    report = client.get("/api/health/detail").json()
    assert rung(report, "machine_config")["ok"] is True


def test_a_pointer_file_without_a_data_dir_is_fine_when_a_folder_resolves(client, tmp_path):
    """machine.json can legitimately hold only `ingest_enabled` (the
    installer writes it even when the data folder was skipped) or only
    `display_names` (the Settings page). With JLBC_DATA_DIR set — every
    dev box and the Z13 — that is NOT a failure. Only 'nothing resolves at
    all' (DataDirNotConfigured) fails this rung."""
    machine = tmp_path / "machine"
    machine.mkdir(parents=True, exist_ok=True)
    (machine / "machine.json").write_text('{"ingest_enabled": false}', encoding="utf-8")
    make_corpus(tmp_path)
    report = client.get("/api/health/detail").json()
    assert rung(report, "machine_config")["ok"] is True


def test_a_lancedb_folder_with_no_tables_fails_the_corpus_rung(client, tmp_path):
    """An empty lancedb/ used to read as 'set up, no documents yet' — the
    same sentence a fresh install gets. Zero ROWS stays OK (the Upload page
    must be reachable); zero TABLES is a wrong folder or a half copy."""
    (tmp_path / "share" / "lancedb").mkdir(parents=True)  # a folder, NO tables
    report = client.get("/api/health/detail").json()
    corpus = rung(report, "corpus")
    assert corpus["ok"] is False
    assert "holds no search index" in corpus["detail"]
    assert report["can_repair"] is False
