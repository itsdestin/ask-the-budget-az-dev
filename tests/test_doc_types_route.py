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


def test_publisher_is_projected_so_the_webapp_never_hand_maintains_its_own_map(tmp_path, monkeypatch):
    """Review Finding 1: `publisher` used to be absent from this wire shape,
    so the webapp hand-typed its own doc_type -> publisher map that could
    (and did) drift from the registry. It must now be readable straight off
    this endpoint."""
    types = _client(tmp_path, monkeypatch).get("/api/document-types").json()["types"]
    by_key = {t["key"]: t["publisher"] for t in types}
    assert by_key == {
        "baseline-book": "jlbc",
        "approps-report": "jlbc",
        "afr": "agao",
        "governors-budget": "governor",
        "agency-submission": "agency",
        "budget-bill-summary": "jlbc",
    }


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


def test_a_stage_on_an_unstaged_type_is_rejected(tmp_path, monkeypatch):
    """Review Finding 3: `afr` declares no `stage_field`, but the route
    accepted a `stage` anyway and `build_title` appended it unconditionally
    -- "FY 2025 Annual Financial Report (Introduced)". That is not cosmetic:
    the system prompt teaches the model "(Introduced)" means provisional and
    supersedable, so a stray stage on a final AFR instructs the model to
    down-rank a real, enacted document. The route already rejects an unknown
    stage and a missing stage on a staged type; accepting a stage on an
    UNSTAGED type was the arbitrary gap between those two guards."""
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("afr.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "agao",
            "doc_type": "afr", "fiscal_year": "2025",
            "title": "", "is_public_record": "true", "stage": "introduced",
        },
    )
    assert r.status_code == 422
    assert "stage" in r.json()["detail"].lower()


def test_same_filename_different_stage_mints_two_distinct_documents(tmp_path, monkeypatch):
    """Review Finding 4, reproduced end-to-end through the real route: JLBC
    reuses the same filename for the Introduced and Engrossed uploads of one
    session. The two uploads here carry different bytes (real Introduced vs.
    Engrossed files always do) so the sha256 dedup does not mask the id
    collision this test exists to catch."""
    c = _client(tmp_path, monkeypatch)
    base = {
        "corpus": "budget", "publisher": "jlbc",
        "doc_type": "budget-bill-summary", "fiscal_year": "2027",
        "title": "", "is_public_record": "true",
    }
    intro = c.post(
        "/api/upload",
        files={"file": ("budgetbills.pdf", b"%PDF-1.4 introduced version", "application/pdf")},
        data={**base, "stage": "introduced"},
    )
    eng = c.post(
        "/api/upload",
        files={"file": ("budgetbills.pdf", b"%PDF-1.4 engrossed version", "application/pdf")},
        data={**base, "stage": "engrossed"},
    )
    assert intro.status_code == 202, intro.text
    assert eng.status_code == 202, eng.text
    assert intro.json()["doc_id"] != eng.json()["doc_id"]
    assert len(c.get("/api/jobs").json()["jobs"]) == 2


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
