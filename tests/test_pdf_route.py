"""GET /api/pdf/{doc_id} — the Range-aware PDF streamer (Plan 4 Task 8).

A port of `web/tests/pdf-route.test.ts`, which is the SPECIFICATION for
this route's Range behavior: PDF.js asks for 64 KB windows and has
quirks (it overshoots EOF on the trailing fetch), so the odd cases below
— clamped past-EOF end, rejected inverted range, rejected start past EOF
— are load-bearing compatibility, not pedantry. Every `parseRangeHeader`
case from that file has a twin here.

What is NOT a port: source resolution and the traversal guard. The old
Next.js route asked a FastAPI sidecar for the doc's path and then
`fs.stat`'d whatever string came back, absolute paths included. This
route reads the same fact out of `documents.json` — a file on an office
network share that anyone with drive access can edit — so the tests
below pin that a hostile `source_blob_path` (`..`, an absolute path
somewhere else on the disk) cannot serve a byte from outside the
allowed roots.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.routes.pdf import parse_range_header
from app.search_provider import StubSearchProvider
from harness.tools import reset_document_title_cache
from store.config import data_dir, documents_path

# 1 KB of "AAAA…" standing in for a PDF, exactly as the TS suite did.
TEST_BYTES = b"A" * 1024


@pytest.fixture(autouse=True)
def isolated_share(tmp_path, monkeypatch):
    """Every test gets its own share (documents.json + blobs), its own
    stand-in repo root, and a clean document-metadata cache.

    REPO_ROOT is repointed even though most tests never use that fallback:
    otherwise a test whose blob is missing from the share would silently
    fall through to the developer's REAL data/cached-pdfs/ and pass (or
    fail) for reasons that have nothing to do with the route.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    monkeypatch.setattr("app.routes.pdf.REPO_ROOT", tmp_path / "repo")
    reset_document_title_cache()
    yield
    reset_document_title_cache()


def write_sidecar(entries: dict) -> None:
    documents_path().write_text(json.dumps(entries), encoding="utf-8")
    # The reader is mtime+size cached; two writes inside one test could land
    # in the same coarse clock tick, so reset explicitly rather than hope.
    reset_document_title_cache()


def write_blob(relative: str, data: bytes = TEST_BYTES) -> None:
    path = data_dir() / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def client() -> TestClient:
    # Stub provider so building the app never probes for a real corpus.
    return TestClient(
        create_app(provider=StubSearchProvider(), static_dir=None),
        raise_server_exceptions=False,
    )


def pdf_doc(blob: str = "pdfs/d1.pdf") -> dict:
    return {
        "d1": {
            "title": "Foo",
            "publisher": "jlbc",
            "doc_type": "baseline-cross-cut",
            "fiscal_year": 2024,
            "source_format": "pdf",
            "source_blob_path": blob,
        }
    }


# ---------------------------------------------------------------------------
# parse_range_header — the eight cases from web/tests/pdf-route.test.ts
# ---------------------------------------------------------------------------

SIZE = 1000


def test_range_absent_is_none():
    assert parse_range_header(None, SIZE) is None


def test_range_rejects_non_bytes_units():
    assert parse_range_header("octets=0-9", SIZE) is None


def test_range_parses_closed_range():
    assert parse_range_header("bytes=0-99", SIZE) == (0, 99)


def test_range_parses_open_ended_range():
    assert parse_range_header("bytes=500-", SIZE) == (500, 999)


def test_range_parses_suffix_range():
    assert parse_range_header("bytes=-200", SIZE) == (800, 999)


def test_range_clamps_overshooting_end():
    # PDF.js asks past EOF on its trailing fetch; clamping is what real
    # servers do and what the old route did.
    assert parse_range_header("bytes=100-9999", SIZE) == (100, 999)


def test_range_rejects_start_past_eof():
    assert parse_range_header("bytes=2000-2099", SIZE) is None


def test_range_rejects_inverted_range():
    # Rejected, not clamped -> the caller falls back to a 200 full body.
    assert parse_range_header("bytes=500-100", SIZE) is None


def test_range_rejects_empty_and_multi_range():
    assert parse_range_header("bytes=-", SIZE) is None
    assert parse_range_header("bytes=0-99,200-299", SIZE) is None


def test_range_on_empty_file_is_none():
    # A zero-byte file has no satisfiable range; a suffix range would
    # otherwise compute end = -1 and emit "bytes 0--1/0".
    assert parse_range_header("bytes=-200", 0) is None


# ---------------------------------------------------------------------------
# GET /api/pdf/{doc_id}
# ---------------------------------------------------------------------------


def test_full_body_200_with_accept_ranges():
    write_sidecar(pdf_doc())
    write_blob("pdfs/d1.pdf")
    r = client().get("/api/pdf/d1")
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/pdf"
    assert r.headers["accept-ranges"] == "bytes"
    assert r.headers["content-length"] == str(len(TEST_BYTES))
    assert len(r.content) == len(TEST_BYTES)


def test_single_range_gets_206_and_content_range():
    write_sidecar(pdf_doc())
    write_blob("pdfs/d1.pdf")
    r = client().get("/api/pdf/d1", headers={"range": "bytes=100-199"})
    assert r.status_code == 206
    assert r.headers["content-length"] == "100"
    assert r.headers["content-range"] == f"bytes 100-199/{len(TEST_BYTES)}"
    assert len(r.content) == 100
    assert r.content[0:1] == b"A"


def test_suffix_range_serves_the_tail():
    write_sidecar(pdf_doc())
    write_blob("pdfs/d1.pdf", bytes(range(256)) * 4)
    r = client().get("/api/pdf/d1", headers={"range": "bytes=-10"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 1014-1023/1024"
    assert r.content == (bytes(range(256)) * 4)[-10:]


def test_past_eof_end_is_clamped():
    write_sidecar(pdf_doc())
    write_blob("pdfs/d1.pdf")
    r = client().get("/api/pdf/d1", headers={"range": "bytes=1000-99999"})
    assert r.status_code == 206
    assert r.headers["content-range"] == "bytes 1000-1023/1024"
    assert len(r.content) == 24


def test_inverted_range_falls_back_to_the_full_body():
    write_sidecar(pdf_doc())
    write_blob("pdfs/d1.pdf")
    r = client().get("/api/pdf/d1", headers={"range": "bytes=500-100"})
    assert r.status_code == 200
    assert len(r.content) == len(TEST_BYTES)


def test_non_pdf_source_is_415_pointing_at_the_cited_text_panel():
    # DOCX legislative bills and fiscal notes have no page image. This is a
    # real analyst path, so the message has to tell the UI what to do next.
    write_sidecar(
        {
            "bill-A": {
                "title": "SB1234",
                "source_format": "docx",
                "source_blob_path": "pdfs/bill.docx",
            }
        }
    )
    r = client().get("/api/pdf/bill-A")
    assert r.status_code == 415
    body = r.json()
    assert body["source_format"] == "docx"
    assert "cited text" in body["detail"].lower()


def test_unknown_doc_is_404():
    write_sidecar(pdf_doc())
    r = client().get("/api/pdf/ghost")
    assert r.status_code == 404
    assert "ghost" in r.json()["detail"]


def test_missing_sidecar_is_404_not_a_crash():
    r = client().get("/api/pdf/d1")
    assert r.status_code == 404


def test_registered_but_missing_file_is_500_with_the_path():
    write_sidecar(pdf_doc(blob="pdfs/not-there.pdf"))
    r = client().get("/api/pdf/d1")
    assert r.status_code == 500
    assert "not-there.pdf" in r.json()["detail"]


# ---------------------------------------------------------------------------
# Traversal — neither doc_id nor source_blob_path is trustworthy
# ---------------------------------------------------------------------------


def test_traversal_in_doc_id_is_just_an_unknown_key():
    write_sidecar(pdf_doc())
    write_blob("pdfs/d1.pdf")
    # doc_id is only ever a dict key — it is never joined onto a directory —
    # so a traversal-shaped id is an unknown document, not a dangerous path.
    # Backslashes (encoded so they survive URL normalization) are the shape
    # that matters on this app's only deployment target.
    r = client().get("/api/pdf/..%5C..%5Csettings.json")
    assert r.status_code == 404


def test_traversal_in_source_blob_path_cannot_escape(tmp_path):
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"TOP-SECRET")
    write_sidecar(
        {
            "d1": {
                "source_format": "pdf",
                # `share/` is inside tmp_path, so this relative path really
                # would resolve onto the secret if the join were naive.
                "source_blob_path": "../secret.pdf",
            }
        }
    )
    r = client().get("/api/pdf/d1")
    assert r.status_code == 500
    assert b"TOP-SECRET" not in r.content


def test_absolute_source_blob_path_cannot_escape(tmp_path):
    secret = tmp_path / "secret.pdf"
    secret.write_bytes(b"TOP-SECRET")
    write_sidecar(
        {"d1": {"source_format": "pdf", "source_blob_path": str(secret)}}
    )
    r = client().get("/api/pdf/d1")
    assert r.status_code == 500
    assert b"TOP-SECRET" not in r.content


# ---------------------------------------------------------------------------
# Source resolution order
# ---------------------------------------------------------------------------


def _write_repo_blob(tmp_path, data: bytes = b"REPO") -> None:
    repo_pdf = tmp_path / "repo" / "data" / "cached-pdfs" / "x.pdf"
    repo_pdf.parent.mkdir(parents=True, exist_ok=True)
    repo_pdf.write_bytes(data)


def test_data_dir_relative_path_wins(tmp_path):
    # documents.json records repo-relative paths ("data/cached-pdfs/…"); on a
    # share the same tree hangs off the data dir, and that root is tried first.
    _write_repo_blob(tmp_path)
    write_sidecar(pdf_doc(blob="data/cached-pdfs/x.pdf"))
    write_blob("data/cached-pdfs/x.pdf", b"SHARE")
    assert client().get("/api/pdf/d1").content == b"SHARE"


def test_repo_cached_pdfs_fallback(tmp_path):
    # Dev machines: the corpus dir has no blobs, the repo's download cache does.
    _write_repo_blob(tmp_path)
    write_sidecar(pdf_doc(blob="data/cached-pdfs/x.pdf"))
    assert client().get("/api/pdf/d1").content == b"REPO"


def test_pdfs_subdir_fallback_by_filename():
    # Spec S7's install layout keeps PDFs in <data_dir>/pdfs/. A sidecar
    # carried over from another machine still points at the old tree, so the
    # bare filename under pdfs/ is tried last.
    write_sidecar(pdf_doc(blob="data/cached-pdfs/ab/x.pdf"))
    write_blob("pdfs/x.pdf", b"BY-NAME")
    assert client().get("/api/pdf/d1").content == b"BY-NAME"
