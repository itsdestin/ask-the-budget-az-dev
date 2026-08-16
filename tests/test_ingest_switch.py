"""The per-machine ingest switch is not bypassable by a route.

🔴 THE DEFECT, found 2026-08-16 by watching a real ingest run rather than by
any test. `app/main.py`'s lifespan correctly checked `ingest_enabled()`,
declined to start the queue on a machine set not to process uploads, and
said so on stderr. Then `POST /api/books/ingest` called `worker.start()`
with no check at all, and `POST /api/upload` did the same. Pressing "Add"
on a book turned that machine into the ingest machine anyway.

WHY IT MATTERS, in `app/machine_config.ingest_enabled`'s own words: one
bundle ships to ~20 office PCs, so without the switch "the winner is
arbitrary and may be an analyst's laptop that then spends six hours at
100% CPU on a Baseline book while they are trying to work." Queuing a book
is exactly the request that costs six hours, and it was the one request
that ignored the switch.

The jobs must still be QUEUED either way — the share is the queue, and the
machine that does ingest picks them up. Refusing to queue would be a
different and worse bug.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


class RecordingWorker:
    """Records whether anything tried to start it."""

    def __init__(self) -> None:
        self.started = False

    def start(self) -> None:
        self.started = True

    def stop(self, timeout_s: float = 0) -> None:
        pass


@pytest.fixture
def app_and_worker(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    worker = RecordingWorker()
    app = create_app(static_dir=None, ingest_worker=worker)
    return app, worker


def _upload(client, **over):
    data = {
        "corpus": "budget",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": "2027",
        "title": "",
        "is_public_record": "true",
    }
    data.update(over)
    return client.post(
        "/api/upload",
        data=data,
        files={"file": ("27baseline-axs.pdf", b"%PDF-1.4 hello", "application/pdf")},
    )


# --- the switch is OFF ------------------------------------------------------


def test_an_upload_does_not_conscript_a_machine_that_opted_out(
    app_and_worker, monkeypatch
):
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")
    app, worker = app_and_worker
    client = TestClient(app)

    assert _upload(client).status_code == 202
    assert worker.started is False


def test_the_job_is_still_QUEUED_on_a_machine_that_opted_out(
    app_and_worker, monkeypatch
):
    # The share is the queue. Refusing to accept the document would be a
    # worse bug than the one being fixed — an analyst on any of the other
    # nineteen PCs could never upload anything.
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")
    app, _worker = app_and_worker
    client = TestClient(app)

    r = _upload(client)
    assert r.status_code == 202

    from ingest.jobs import load_active

    assert [j.state for j in load_active()] == ["queued"]


def test_adding_a_book_does_not_conscript_a_machine_that_opted_out(
    app_and_worker, monkeypatch
):
    # The worst of the two bypasses: a book is ~140 documents and hours of
    # CPU, and this is the request an analyst makes with one click.
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")
    app, worker = app_and_worker

    class FakeProber:
        def head(self, url: str) -> bool:
            return True

        def get(self, url: str) -> bytes:
            return b"%PDF-1.4"

    app.state.book_prober = FakeProber()
    client = TestClient(app)

    r = client.post("/api/books/ingest", json={"family": "baseline", "fiscal_year": 2027})
    assert r.status_code in (200, 202), r.text
    assert worker.started is False


def test_the_queue_says_nobody_will_pick_this_up(app_and_worker, monkeypatch):
    # The counterweight. Gating the routes without this trades a CPU problem
    # for a trust problem: a row sitting at "Waiting" for ever with nothing
    # on screen explaining why.
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")
    app, _worker = app_and_worker
    client = TestClient(app)

    assert client.get("/api/jobs").json()["stalled_message"] is None  # nothing queued

    _upload(client)
    message = client.get("/api/jobs").json()["stalled_message"]
    assert message and "no computer is set to process them" in message


def test_the_admin_page_and_the_upload_page_say_the_SAME_thing(
    app_and_worker, monkeypatch
):
    # Two implementations of "is the queue stalled?" would eventually
    # disagree, and the failure would be the worst kind: the admin page
    # reporting all is well while an analyst stares at a stuck upload.
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")
    app, _worker = app_and_worker
    client = TestClient(app)
    _upload(client)

    from_queue = client.get("/api/jobs").json()["stalled_message"]
    from_admin = client.get("/api/admin/corpus").json()["queue_stalled_message"]
    assert from_queue == from_admin


# --- the switch is ON -------------------------------------------------------


def test_an_upload_still_revives_the_worker_where_ingest_belongs(
    app_and_worker, monkeypatch
):
    # The reason the route calls start() at all: a worker that died is worth
    # reviving at the moment somebody is actually waiting on a document.
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "1")
    app, worker = app_and_worker
    client = TestClient(app)

    assert _upload(client).status_code == 202
    assert worker.started is True


def test_no_stall_warning_on_the_machine_that_does_the_work(
    app_and_worker, monkeypatch
):
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "1")
    app, _worker = app_and_worker
    client = TestClient(app)
    _upload(client)
    assert client.get("/api/jobs").json()["stalled_message"] is None


def test_a_route_never_BUILDS_a_worker_on_a_machine_that_opted_out(
    tmp_path, monkeypatch
):
    # `ensure_started` creates one when none is attached. A route must not
    # reach that path — a machine that opted out must not acquire a worker
    # because somebody used the upload form.
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")
    app = create_app(static_dir=None, ingest_worker=None)
    client = TestClient(app)

    assert _upload(client).status_code == 202
    assert getattr(app.state, "ingest_worker", None) is None


def test_no_route_module_starts_the_ingest_worker_directly():
    """The CLASS guard, not a third instance of the same fix.

    Two routes were gated on 2026-08-16 (upload, books) and a THIRD —
    `fiscal_notes.refresh` — was found still calling `worker.start()` when
    the branch was merged and the whole tree was grepped. That is the point
    at which patching instances stops being the right move: per CLAUDE.md,
    "a guard that fires twice is telling you the design is wrong".

    Any route that wants the queue to move must call
    `ingest.worker.revive_if_this_machine_ingests`, which consults
    `app.machine_config.ingest_enabled()` first. A direct `.start()` bypasses
    the per-machine switch, and the cost lands on a colleague: one bundle on
    ~20 office PCs, so the machine that gets conscripted is whichever analyst
    happened to press the button, and it then spends hours at 100% CPU on a
    Baseline book while they are trying to work.

    AST rather than a regex so a comment mentioning `.start()` cannot fail
    the suite and a line-wrapped call cannot pass it.
    """
    import ast
    from pathlib import Path

    routes = Path(__file__).resolve().parent.parent / "app" / "routes"
    offenders = []
    for path in sorted(routes.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "start"
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "worker"
            ):
                offenders.append(f"{path.name}:{node.lineno}")

    assert offenders == [], (
        "These routes start the ingest worker directly and so bypass the "
        f"per-machine ingest switch: {offenders}. Call "
        "ingest.worker.revive_if_this_machine_ingests(request.app) instead."
    )
