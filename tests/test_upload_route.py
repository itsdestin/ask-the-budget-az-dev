"""Tests for POST /api/upload — Invariant 8 gate, dedup, queueing."""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routes.upload import _resolve_publisher
from ingest.doc_types import DocType
from ingest.jobs import load_all
from store.config import documents_path


class NoopWorker:
    """Route tests must never start a background thread."""

    started = False

    def start(self) -> None:
        self.started = True

    def stop(self, timeout_s: float = 0) -> None:
        pass


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    app = create_app(provider=_StubProvider(), static_dir=None,
                     ingest_worker=NoopWorker())
    return TestClient(app)


class _StubProvider:
    name = "stub"

    def search(self, *a, **kw):
        return []


def _form(**over) -> dict:
    base = {
        "corpus": "budget",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": "2027",
        "title": "",
        "is_public_record": "true",
    }
    base.update(over)
    return base


def _upload(client, *, content: bytes = b"%PDF-1.4 hello", name="27baseline-axs.pdf",
            **over):
    return client.post(
        "/api/upload",
        data=_form(**over),
        files={"file": (name, content, "application/pdf")},
    )


# --- happy path -------------------------------------------------------------


def test_upload_queues_a_job(client, tmp_path):
    r = _upload(client)
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["job_id"] and body["doc_id"]

    jobs = load_all()
    assert [j.job_id for j in jobs] == [body["job_id"]]
    assert jobs[0].state == "queued"


def test_uploaded_bytes_land_content_addressed(client, tmp_path):
    r = _upload(client, content=b"%PDF-1.4 payload")
    job = load_all()[0]
    landed = tmp_path / job.source_path
    assert landed.is_file()
    assert landed.read_bytes() == b"%PDF-1.4 payload"
    assert job.source_sha256 in landed.name


def test_doc_id_follows_the_shared_convention(client):
    r = _upload(client, name="27baseline-axs.pdf")
    assert r.json()["doc_id"] == "jlbc-baseline-fy2027-27baseline-axs"


def test_user_title_rides_along_to_the_job(client):
    _upload(client, title="FY 2027 Baseline — AHCCCS")
    assert load_all()[0].user_title == "FY 2027 Baseline — AHCCCS"


# --- Invariant 8 ------------------------------------------------------------


def test_missing_public_record_checkbox_is_rejected(client):
    r = _upload(client, is_public_record="")
    assert r.status_code == 400
    assert "public record" in r.json()["detail"].lower()
    assert load_all() == []


def test_false_public_record_checkbox_is_rejected(client):
    r = _upload(client, is_public_record="false")
    assert r.status_code == 400
    assert "public record" in r.json()["detail"].lower()


def test_the_gate_is_server_side_not_just_ui(client, tmp_path):
    """Invariant 8 says the checkbox gates the ENDPOINT — a client that
    doesn't send the field must not be able to seed the corpus."""
    r = client.post(
        "/api/upload",
        data={k: v for k, v in _form().items() if k != "is_public_record"},
        files={"file": ("x.pdf", b"%PDF", "application/pdf")},
    )
    assert r.status_code == 400
    assert not (tmp_path / "uploads").exists()


# --- validation -------------------------------------------------------------


def test_unknown_doc_type_is_422(client):
    assert _upload(client, doc_type="not-a-real-type").status_code == 422


def test_non_numeric_fiscal_year_is_422(client):
    assert _upload(client, fiscal_year="two thousand").status_code == 422


def test_implausible_fiscal_year_is_422(client):
    assert _upload(client, fiscal_year="1776").status_code == 422


def test_unknown_corpus_is_422(client):
    assert _upload(client, corpus="everything").status_code == 422


def test_unsupported_file_type_is_422(client):
    r = _upload(client, name="notes.txt")
    assert r.status_code == 422
    assert "pdf" in r.json()["detail"].lower()


def test_empty_file_is_422(client):
    assert _upload(client, content=b"").status_code == 422


# --- duplicate detection ----------------------------------------------------


def test_duplicate_of_a_live_document_is_409_with_provenance(client, tmp_path):
    documents_path().write_text(json.dumps({
        "jlbc-baseline-fy2027-27baseline-axs": {
            "title": "FY 2027 Baseline — AHCCCS",
            "source_sha256": _sha(b"%PDF-1.4 hello"),
            "ingested_at": "2026-07-01T12:00:00+00:00",
            "uploaded_by": "DMOSS",
        }
    }), encoding="utf-8")
    r = _upload(client, content=b"%PDF-1.4 hello")
    assert r.status_code == 409
    body = r.json()
    assert body["detail"] == "already in corpus"
    assert body["existing_doc_id"] == "jlbc-baseline-fy2027-27baseline-axs"
    assert body["added_at"] == "2026-07-01T12:00:00+00:00"
    assert body["added_by"] == "DMOSS"


def test_duplicate_of_a_pending_job_is_409(client):
    """Double-clicking Upload must not queue the same book twice."""
    assert _upload(client).status_code == 202
    r = _upload(client)
    assert r.status_code == 409


def test_reprocess_overrides_the_duplicate_check(client):
    """The spec's explicit re-process option — a document was re-issued at
    the same URL, or a chunker bug needs re-running."""
    assert _upload(client).status_code == 202
    assert _upload(client, reprocess="true").status_code == 202


def test_a_finished_job_does_not_block_a_reupload(client):
    """Only PENDING jobs dedup; documents.json is what guards live docs."""
    from ingest.jobs import advance, load_all as _all

    _upload(client)
    job = _all()[0]
    advance(job, "cancelled")
    assert _upload(client).status_code == 202


def _sha(blob: bytes) -> str:
    import hashlib
    return hashlib.sha256(blob).hexdigest()


# --- Review Finding 1: the registry, not the client, decides `publisher` ----
#
# `GET /api/document-types` doesn't project `publisher`, so the webapp used to
# hand-maintain its own doc_type -> publisher map and post whatever it
# decided. An admin adding a new registry row with `upload_row: true` got a
# working row whose every upload posted the WRONG publisher (the webapp's
# fallback) -- silently minting the wrong doc_id class and stamping the wrong
# publisher facet, with nothing erroring. Spec T4's acceptance test ("adding a
# row must be a YAML edit, not a code change") failed as a result.


def test_publisher_form_field_is_optional_when_the_registry_declares_one(client):
    """The webapp agent working webapp/ in parallel is deleting its
    doc_type -> publisher map and will stop sending the field entirely. If
    `publisher` stays a required Form field, every upload 422s the moment
    both changes merge -- this is the other half of that contract."""
    r = client.post(
        "/api/upload",
        data={k: v for k, v in _form(doc_type="afr").items() if k != "publisher"},
        files={"file": ("afr.pdf", b"%PDF-1.4 hello", "application/pdf")},
    )
    assert r.status_code == 202, r.text
    assert r.json()["doc_id"].startswith("agao-")


def test_a_client_supplied_publisher_is_overridden_by_the_registry(client):
    """`afr` declares `publisher: agao`. A wrong client value must not reach
    `make_doc_id` -- it would mint the wrong doc_id class (the non-JLBC
    branch is keyed on the literal publisher string) and stamp the wrong
    publisher facet on every chunk of the document."""
    r = client.post(
        "/api/upload",
        data=_form(doc_type="afr", publisher="totally-wrong"),
        files={"file": ("afr.pdf", b"%PDF-1.4 hello", "application/pdf")},
    )
    assert r.status_code == 202, r.text
    assert r.json()["doc_id"] == "agao-afr-fy2027"
    assert load_all()[0].publisher == "agao"


def test_resolve_publisher_prefers_the_registry_over_the_client():
    row = DocType(key="afr", label="AFR", group="Auditor General", order=30,
                  formats=(".pdf",), extractors={}, publisher="agao",
                  one_per_year=True, where_published="", which_file="")
    assert _resolve_publisher(row, "some-other-value") == "agao"
    assert _resolve_publisher(row, "") == "agao"


def test_resolve_publisher_falls_back_and_validates_when_the_row_declares_none():
    """Only reachable for a hypothetical future row -- every row in the
    committed registry declares a publisher today -- but the fallback must
    validate rather than accept anything, per the finding."""
    row = DocType(key="x", label="X", group="X", order=1, formats=(".pdf",),
                  extractors={}, publisher=None, one_per_year=False,
                  where_published="", which_file="")
    assert _resolve_publisher(row, "agency") == "agency"
    with pytest.raises(Exception):
        _resolve_publisher(row, "not-a-real-publisher")


def test_resolve_publisher_with_no_row_still_validates():
    with pytest.raises(Exception):
        _resolve_publisher(None, "not-a-real-publisher")
