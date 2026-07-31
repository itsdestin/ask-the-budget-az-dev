"""Corpus health, snapshots and guarded restore (Plan 5 Task 6, spec S17).

The test that matters most here is the 409 one. Restoring while an ingest
is running would interleave a zip extraction with a LanceDB commit — the
one operation in this app that can destroy a corpus rather than merely
corrupt a document. Everything else in this file is reporting.

Restore is also the only destructive button an admin has, so it is
double-guarded: a typed confirmation string (a mis-click cannot fire it)
and a snapshot of the CURRENT corpus taken before the restore, so a
mistaken restore is itself reversible.
"""
from __future__ import annotations

import json
import zipfile

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import Settings, reset_settings_cache, save_settings
from ingest.lock import IngestLock
from store.backup import backups_dir, list_snapshots
from store.config import data_dir

ADMIN = "Destin"


@pytest.fixture(autouse=True)
def _isolated_share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    save_settings(Settings(admin_username=ADMIN))
    reset_settings_cache()
    yield
    reset_settings_cache()


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app(provider=StubSearchProvider(), ingest_worker=None))


def make_corpus(marker: str = "original") -> None:
    """A stand-in `lancedb/` — store/backup.py zips the directory, and does
    not care that these bytes aren't a real LanceDB table."""
    corpus = data_dir() / "lancedb" / "budget_chunks.lance" / "data"
    corpus.mkdir(parents=True, exist_ok=True)
    (corpus / "part-0.lance").write_text(marker, encoding="utf-8")


def read_corpus() -> str:
    return (
        data_dir() / "lancedb" / "budget_chunks.lance" / "data" / "part-0.lance"
    ).read_text(encoding="utf-8")


def make_snapshot(name: str = "lancedb-20260731T120000Z.zip", marker: str = "snapshot") -> str:
    path = backups_dir() / name
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("budget_chunks.lance/data/part-0.lance", marker)
    return name


def write_job(job_id: str, state: str, updated_at: str = "2026-07-31T10:00:00-07:00") -> None:
    jobs = data_dir() / "jobs"
    jobs.mkdir(parents=True, exist_ok=True)
    (jobs / f"{job_id}.json").write_text(json.dumps({
        "job_id": job_id, "doc_id": f"doc-{job_id}", "title": "A book",
        "corpus": "budget", "state": state, "pct": 100, "stage_detail": "",
        "error": None, "machine": "PC1", "user": ADMIN,
        "created_at": "2026-07-31T09:00:00-07:00", "updated_at": updated_at,
        "source_path": "/tmp/x.pdf", "source_sha256": "abc", "publisher": "JLBC",
        "doc_type": "baseline", "fiscal_year": 2027, "user_title": "A book",
    }), encoding="utf-8")


# ---------------------------------------------------------------------------
# GET /api/admin/corpus
# ---------------------------------------------------------------------------


def test_corpus_reports_counts_and_location(client):
    make_corpus()
    (data_dir() / "documents.json").write_text(
        json.dumps({"doc-1": {"title": "One"}, "doc-2": {"title": "Two"}}),
        encoding="utf-8",
    )

    body = client.get("/api/admin/corpus").json()

    assert body["data_dir"] == str(data_dir())
    assert body["documents"] == 2
    assert body["budget_chunks"] == 0        # no real table — honestly zero
    assert body["fiscal_note_chunks"] == 0
    assert body["lancedb_bytes"] > 0


def test_corpus_reports_the_queue(client):
    write_job("j1", "queued")
    write_job("j2", "queued")
    write_job("j3", "embedding")
    write_job("j4", "failed")
    write_job("j5", "live", updated_at="2026-07-31T11:30:00-07:00")

    body = client.get("/api/admin/corpus").json()

    assert body["queue"] == {"queued": 2, "running": 1, "failed": 1}
    # The newest COMPLETED job — "when did this corpus last actually grow",
    # which is not the same question as "is anything running".
    assert body["last_ingest_at"] == "2026-07-31T11:30:00-07:00"


def test_corpus_on_a_fresh_install_is_all_zeros_not_an_error(client):
    body = client.get("/api/admin/corpus").json()
    assert body["documents"] == 0
    assert body["lancedb_bytes"] == 0
    assert body["last_ingest_at"] is None
    assert body["queue"] == {"queued": 0, "running": 0, "failed": 0}
    # Nothing on disk to measure — null, never a made-up zero that would
    # read as "measured it, nothing to reclaim".
    assert body["dead_version_bytes"] is None


def _real_row(cid: str, doc_id: str = "doc-1") -> dict:
    from store.chunk_store import DEFAULT_DIM

    return dict(
        chunk_id=cid, doc_id=doc_id, text="ahcccs provider rates " * 20,
        section_path=["A", "B"], page=3, bbox=[1.0, 2.0, 3.0, 4.0],
        source_anchor='{"p": 3}', agency_canonical_ids=["ahcccs"],
        fund_canonical_id=None, fund_mentions=[], fiscal_year=2026,
        doc_type="baseline-per-agency", is_table=False, table_html=None,
        token_count=42, publisher="jlbc", vector=[0.01] * DEFAULT_DIM,
    )


def test_corpus_measures_a_real_lancedb_table(client):
    """The counts and the byte measurements against an actual table.

    Everything else in this file uses a stand-in directory, which never
    exercises `table.stats()` — so without this test the dead-version
    number would ship having never once been computed.
    """
    from store.chunk_store import ChunkStore

    store = ChunkStore()
    store.upsert_chunks("budget_chunks", [_real_row(f"c{i}") for i in range(50)])
    # Rewrite the same ids repeatedly: every upsert supersedes the previous
    # version and LanceDB keeps the old one until a cleanup runs. This is
    # the shape that reached 5.1 GB for ~18k chunks in production.
    for _ in range(3):
        store.upsert_chunks("budget_chunks", [_real_row(f"c{i}") for i in range(50)])

    body = client.get("/api/admin/corpus").json()

    assert body["budget_chunks"] == 50
    assert body["fiscal_note_chunks"] == 0
    assert body["lancedb_bytes"] > 0
    dead = body["dead_version_bytes"]
    assert isinstance(dead, int)
    # An estimate, not an exact figure (see `_reclaimable_bytes`) — so the
    # assertion is on the property that makes it worth showing: superseded
    # versions register as reclaimable, and the number never exceeds what
    # is actually on disk.
    assert 0 < dead <= body["lancedb_bytes"]


def test_a_corrupt_documents_json_does_not_break_the_page(client):
    (data_dir() / "documents.json").write_text("{ not json", encoding="utf-8")
    body = client.get("/api/admin/corpus").json()
    # This is the page an admin opens BECAUSE something is wrong. It must
    # not be the page that breaks too.
    assert body["documents"] == 0


# ---------------------------------------------------------------------------
# GET /api/admin/backups
# ---------------------------------------------------------------------------


def test_backups_lists_snapshots_newest_first(client):
    make_snapshot("lancedb-20260730T120000Z.zip")
    make_snapshot("lancedb-20260731T120000Z.zip")

    snapshots = client.get("/api/admin/backups").json()["snapshots"]

    assert [s["name"] for s in snapshots] == [
        "lancedb-20260731T120000Z.zip",
        "lancedb-20260730T120000Z.zip",
    ]
    assert all(s["bytes"] > 0 for s in snapshots)
    # Parsed out of the filename, not the file mtime: mtimes on an SMB
    # share are the one piece of metadata most likely to be wrong, and the
    # confirm dialog shows this date.
    assert snapshots[0]["created_at"] == "2026-07-31T12:00:00+00:00"


def test_backups_on_a_fresh_install_is_empty(client):
    assert client.get("/api/admin/backups").json() == {"snapshots": []}


# ---------------------------------------------------------------------------
# POST /api/admin/backups/{name}/restore
# ---------------------------------------------------------------------------


def test_restore_without_the_typed_confirmation_does_nothing(client):
    make_corpus("original")
    name = make_snapshot()

    r = client.post(f"/api/admin/backups/{name}/restore", json={})

    assert r.status_code == 400
    assert read_corpus() == "original"


def test_restore_with_a_wrong_confirmation_does_nothing(client):
    make_corpus("original")
    name = make_snapshot()

    r = client.post(f"/api/admin/backups/{name}/restore", json={"confirm": "yes"})

    assert r.status_code == 400
    assert read_corpus() == "original"


def test_restore_is_refused_while_an_ingest_is_running(client):
    """THE one that matters: a zip extraction interleaved with a LanceDB
    commit is how a corpus gets destroyed rather than merely damaged."""
    make_corpus("original")
    name = make_snapshot()

    with IngestLock():
        r = client.post(f"/api/admin/backups/{name}/restore", json={"confirm": "restore"})

    assert r.status_code == 409
    assert r.json()["detail"] == (
        "An ingest is running — wait for it to finish, then try again."
    )
    assert read_corpus() == "original"


def test_a_successful_restore_snapshots_the_current_corpus_first(client):
    make_corpus("original")
    name = make_snapshot(marker="from-the-snapshot")
    before = set(list_snapshots())

    r = client.post(f"/api/admin/backups/{name}/restore", json={"confirm": "restore"})

    assert r.status_code == 200, r.text
    assert r.json() == {"restored": name, "restart_required": True}
    assert read_corpus() == "from-the-snapshot"
    # A mistaken restore has to be reversible too — otherwise the "safe"
    # button is the one that loses the corpus.
    new_snapshots = set(list_snapshots()) - before
    assert len(new_snapshots) == 1
    with zipfile.ZipFile(backups_dir() / new_snapshots.pop()) as zf:
        assert zf.read("budget_chunks.lance/data/part-0.lance") == b"original"


def test_restore_releases_the_lock_afterwards(client):
    make_corpus()
    name = make_snapshot()
    client.post(f"/api/admin/backups/{name}/restore", json={"confirm": "restore"})
    # A restore that leaked the lock would block every future ingest with
    # no error naming the cause, until someone deleted a lockfile by hand.
    with IngestLock():
        pass


def test_restore_of_an_unknown_snapshot_is_a_404(client):
    make_corpus("original")
    r = client.post(
        "/api/admin/backups/lancedb-20990101T000000Z.zip/restore",
        json={"confirm": "restore"},
    )
    assert r.status_code == 404
    assert read_corpus() == "original"


def test_restore_rejects_a_path_traversal_name(client):
    make_corpus("original")
    r = client.post(
        "/api/admin/backups/..%2F..%2Fsettings.json/restore",
        json={"confirm": "restore"},
    )
    # The encoded traversal never reaches the handler at all — the path
    # normalises to something no route matches. Asserting a SPECIFIC 4xx
    # here would be pinning Starlette's routing rather than this app's
    # behaviour; what has to hold is that it did not succeed and the
    # corpus is untouched.
    assert r.status_code >= 400
    assert read_corpus() == "original"


def test_restore_of_a_non_snapshot_filename_is_refused(client):
    """The traversal guard's other half: a name that DOES reach the handler.

    `settings.json` is a real file on the share sitting next to the
    backups directory — extracting it over `lancedb/` would be nonsense,
    and store/backup.py's `_validated_name` is what stops it.
    """
    make_corpus("original")
    (data_dir() / "settings.json").write_text("{}", encoding="utf-8")

    r = client.post("/api/admin/backups/settings.json/restore",
                    json={"confirm": "restore"})

    assert r.status_code == 404
    assert read_corpus() == "original"


def test_a_failed_restore_still_releases_the_lock(client):
    make_corpus("original")
    r = client.post(
        "/api/admin/backups/lancedb-20990101T000000Z.zip/restore",
        json={"confirm": "restore"},
    )
    assert r.status_code == 404
    with IngestLock():
        pass
