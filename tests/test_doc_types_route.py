"""Tests for GET /api/document-types and the upload route's use of it.

The route is a thin projection of ingest.doc_types.upload_rows() — see that
module's tests for the registry's own correctness (ordering, redirects,
stage_field). This file is about the wire shape and the upload gate.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return TestClient(create_app(ingest_worker=None))


def test_the_route_returns_the_six_upload_rows_in_order(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/api/document-types")
    assert r.status_code == 200
    keys = [t["key"] for t in r.json()["types"]]
    assert keys == [
        "baseline-book", "approps-report", "afr",
        "governors-budget", "agency-submission", "budget-bill-summary",
    ]


def test_book_rows_carry_a_redirect_and_no_which_file(tmp_path, monkeypatch):
    types = _client(tmp_path, monkeypatch).get("/api/document-types").json()["types"]
    by_key = {t["key"]: t for t in types}
    for key in ("baseline-book", "approps-report"):
        assert by_key[key]["redirect"]["action"] == "add-jlbc-book"
        assert not by_key[key]["which_file"]


def test_only_the_bill_summary_asks_for_a_stage(tmp_path, monkeypatch):
    types = _client(tmp_path, monkeypatch).get("/api/document-types").json()["types"]
    staged = {t["key"] for t in types if t["stage_field"]}
    assert staged == {"budget-bill-summary"}


def test_upload_accepts_a_new_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("bha-fy27.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "agency",
            "doc_type": "agency-submission", "fiscal_year": "2027",
            "title": "", "is_public_record": "true",
        },
    )
    assert r.status_code == 202, r.text


def test_upload_persists_the_stage_on_the_job(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("engrossed.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "jlbc",
            "doc_type": "budget-bill-summary", "fiscal_year": "2027",
            "title": "", "is_public_record": "true", "stage": "engrossed",
        },
    )
    assert r.status_code == 202, r.text
    jobs = c.get("/api/jobs").json()["jobs"]
    assert [j for j in jobs if j.get("stage") == "engrossed"]


def test_an_unknown_stage_is_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("x.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "jlbc",
            "doc_type": "budget-bill-summary", "fiscal_year": "2027",
            "title": "", "is_public_record": "true", "stage": "final",
        },
    )
    # "Final" is the wording JLBC uses on some titles, but the ladder has two
    # rungs. Accepting a third silently would break the supersession rule.
    assert r.status_code == 422


def test_a_missing_stage_on_a_staged_type_is_rejected(tmp_path, monkeypatch):
    # budget-bill-summary declares stage_field: true — omitting it entirely
    # (not just typing an unknown value) must also 422, or the model never
    # learns which rung a document is on and the supersession rule is silently
    # inert for every upload nobody remembers to fill the field in on.
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("no-stage.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "jlbc",
            "doc_type": "budget-bill-summary", "fiscal_year": "2027",
            "title": "", "is_public_record": "true",
        },
    )
    assert r.status_code == 422
