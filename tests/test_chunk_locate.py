"""GET /api/chunks/{chunk_id}/locate — the read-time coordinate map (spec L2).

The viewer's client-side text-layer search misses 44% of correctly linked
figures (measured 2026-08-18 on a live run): the stored bbox covered only the
chunk's first paragraph, the cited value sat on a later page, or accounting
parens differed between chunk text and PDF text layer. This route answers
with PyMuPDF's own search, in PDF user-space points.

The store and documents.json are faked (same posture as
test_chunks_route.py); the PDF is REAL — a tiny two-page document written
with fitz into tmp_path — because the whole point of the route is PyMuPDF's
search behaviour (clips, paren variants, page scan), and faking fitz would
test nothing. fitz ships in the Windows bundle and is a runtime dep of
ingest/, so it is present on every machine that runs this suite.
"""
from __future__ import annotations

import json

import fitz
import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.tools import reset_document_title_cache
from store.config import documents_path


class FakeStore:
    def __init__(self, rows: list[dict]):
        self.rows = rows

    def get_by_ids(self, table: str, chunk_ids: list[str]) -> list[dict]:
        return [r for r in self.rows if r["chunk_id"] in chunk_ids]


@pytest.fixture(autouse=True)
def isolated_share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    reset_document_title_cache()
    yield
    reset_document_title_cache()


@pytest.fixture
def tiny_pdf(tmp_path):
    """Two pages: page 1 holds 1,234,567 in the top-left and $(9,999) in the
    bottom-right; page 2 holds 9,876,543. Real bytes, real search."""
    path = tmp_path / "share" / "pdfs" / "d1.pdf"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text(fitz.Point(80, 120), "Total: 1,234,567 carried forward.")
    p1.insert_text(fitz.Point(400, 700), "Variance $(9,999) explained below.")
    p2 = doc.new_page(width=612, height=792)
    p2.insert_text(fitz.Point(80, 120), "Prior year: 9,876,543.")
    doc.save(str(path))
    doc.close()
    return path


@pytest.fixture
def client_with(monkeypatch, tiny_pdf):
    documents_path().parent.mkdir(parents=True, exist_ok=True)

    def make(row: dict) -> TestClient:
        monkeypatch.setattr(
            "retrieval.pipeline._get_store", lambda: FakeStore([row])
        )
        documents_path().write_text(
            json.dumps(
                {"d1": {"source_format": "pdf", "source_blob_path": "pdfs/d1.pdf"}}
            ),
            encoding="utf-8",
        )
        reset_document_title_cache()
        # The route caches open documents per blob path; a fresh cache per
        # test so one test's PDF is never another's.
        from app.routes import pdf as pdf_route

        pdf_route._locate_doc_cache.clear()
        return TestClient(
            create_app(provider=StubSearchProvider(), static_dir=None),
            raise_server_exceptions=False,
        )

    return make


BASE_ROW = {
    "chunk_id": "c1",
    "doc_id": "d1",
    "text": "Total: 1,234,567 carried forward.",
    "page": 1,
    "bbox": [70.0, 100.0, 300.0, 130.0],
}


def test_missing_text_is_a_400_with_a_plain_sentence(client_with):
    r = client_with(BASE_ROW).get("/api/chunks/c1/locate")
    assert r.status_code == 400
    assert "text" in r.json()["detail"]


def test_stored_page_basis_finds_the_value_inside_the_bbox(client_with):
    r = client_with(BASE_ROW).get(
        "/api/chunks/c1/locate", params={"text": "1,234,567"}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["basis"] == "stored-page"
    assert body["page"] == 1
    assert len(body["rects"]) == 1
    x0, y0, x1, y1 = body["rects"][0]
    # The rect is the VALUE's own span, inside the stored bbox — the
    # narrowest-possible-highlight property the spec promises (R4).
    assert 70 <= x0 and x1 <= 300
    assert 100 <= y0 and y1 <= 130


def test_anchor_basis_resolves_a_value_from_a_later_paragraph(client_with):
    # The measured defect: cited value in paragraph 2, stored bbox from
    # paragraph 1. The lines map names paragraph 2's page + bbox, and the
    # search clips to it.
    row = {
        **BASE_ROW,
        "text": "Total: 1,234,567 carried forward.\nVariance $(9,999) explained below.",
        "bbox": [70.0, 100.0, 300.0, 130.0],
        "source_anchor": json.dumps(
            {
                "page": 1,
                "lines": [
                    {"text": "Total: 1,234,567 carried forward.",
                     "page": 1, "bbox": [70, 100, 300, 130]},
                    {"text": "Variance $(9,999) explained below.",
                     "page": 1, "bbox": [390, 680, 560, 710]},
                ],
            }
        ),
    }
    r = client_with(row).get(
        "/api/chunks/c1/locate", params={"text": "9,999"}
    )
    body = r.json()
    assert body["basis"] == "anchor"
    assert body["page"] == 1
    x0, y0, x1, y1 = body["rects"][0]
    # Inside the SECOND paragraph's bbox, not the stored (first-paragraph)
    # one — the whole point of the anchor step.
    assert 390 <= x0 and x1 <= 560
    assert 680 <= y0 and y1 <= 710


def test_paren_swap_finds_the_pdfs_rendering(client_with):
    # Stored form `(9,999)` (the linker's answer-side rendering); the PDF
    # prints `$(9,999)`. Raw search would miss; the paren-swapped
    # candidate must hit.
    row = {**BASE_ROW, "bbox": None}
    r = client_with(row).get(
        "/api/chunks/c1/locate", params={"text": "(9,999)"}
    )
    body = r.json()
    assert body["basis"] in ("stored-page", "scan")
    assert body["page"] == 1
    assert body["rects"]


def test_scan_basis_finds_a_value_on_a_later_page(client_with):
    # The stored page is 1; the value lives on page 2 (the wrong-page
    # cases, 7/137 measured).
    row = {**BASE_ROW, "bbox": None}
    r = client_with(row).get(
        "/api/chunks/c1/locate", params={"text": "9,876,543"}
    )
    body = r.json()
    assert body["basis"] == "scan"
    assert body["page"] == 2
    assert body["rects"]


def test_absent_value_is_basis_none_with_the_stored_page(client_with):
    r = client_with(BASE_ROW).get(
        "/api/chunks/c1/locate", params={"text": "42,424,242"}
    )
    body = r.json()
    assert body == {
        "chunk_id": "c1",
        "page": 1,
        "rects": [],
        "basis": "none",
    }


def test_non_pdf_source_is_basis_none_without_touching_fitz(client_with, monkeypatch):
    c = client_with({**BASE_ROW})

    def boom(*a, **k):
        raise AssertionError("fitz must not be imported for a DOCX source")

    monkeypatch.setattr("app.routes.pdf._import_fitz", boom)
    # Flip the sidecar AFTER the client exists: the route must read the
    # source format before ever importing fitz.
    documents_path().write_text(
        json.dumps({"d1": {"source_format": "docx", "source_blob_path": "x.docx"}}),
        encoding="utf-8",
    )
    reset_document_title_cache()
    r = c.get("/api/chunks/c1/locate", params={"text": "1,234,567"})
    assert r.json()["basis"] == "none"


def test_broken_fitz_degrades_to_none_not_a_500(client_with, monkeypatch):
    # ingest/ladder.py's posture: a damaged bundle reads as "no locate",
    # and the viewer keeps its existing fallback chain.
    monkeypatch.setattr("app.routes.pdf._import_fitz", lambda: None)
    r = client_with(BASE_ROW).get(
        "/api/chunks/c1/locate", params={"text": "1,234,567"}
    )
    assert r.status_code == 200
    assert r.json()["basis"] == "none"


def test_unknown_chunk_is_the_same_404_as_get_chunk(client_with):
    r = client_with(BASE_ROW).get(
        "/api/chunks/nope/locate", params={"text": "1,234,567"}
    )
    assert r.status_code == 404
    assert "nope" in r.json()["detail"]


def test_mineru_normalized_bbox_is_autodetected_for_the_clip(client_with):
    # A 0–1000-normalized bbox (MinerU's space, ~99% of the corpus) must be
    # scaled to page points before clipping; read as raw points it would
    # clip to a postage stamp and miss the value (verified on live rows,
    # e.g. jlbc-approps-fy2023-ade p7).
    # Wide enough that max(bbox) exceeds the page's larger dimension — the
    # ONLY discriminator the viewer's (and this route's) autodetect has; a
    # small normalized bbox is genuinely ambiguous with points and both
    # sides read it as points.
    row = {**BASE_ROW, "bbox": [114.0, 126.0, 980.0, 164.0]}
    r = client_with(row).get(
        "/api/chunks/c1/locate", params={"text": "1,234,567"}
    )
    body = r.json()
    assert body["basis"] == "stored-page"
    assert body["rects"]


def test_lance_writer_round_trips_lines():
    # Spec L1: the writer serializes provenance.lines into source_anchor.
    from chunking.types import Chunk, ChunkProvenance, ProvenanceLine
    from ingest.lance_writer import chunk_to_lance_row

    chunk = Chunk(
        chunk_id="d1-0000",
        doc_id="d1",
        text="a\nb",
        section_path=[],
        provenance=ChunkProvenance(
            page=1,
            bbox=[1.0, 2.0, 3.0, 4.0],
            lines=[ProvenanceLine(text="a", page=1, bbox=[1, 2, 3, 4]),
                   ProvenanceLine(text="b", page=2, bbox=[5, 6, 7, 8])],
        ),
        fiscal_year=2026,
        doc_type="approps-per-agency",
        publisher="jlbc",
        token_count=2,
    )
    row = chunk_to_lance_row(chunk, vector=[0.0])
    anchor = json.loads(row["source_anchor"])
    assert anchor["page"] == 1
    assert anchor["lines"] == [
        {"text": "a", "page": 1, "bbox": [1.0, 2.0, 3.0, 4.0]},
        {"text": "b", "page": 2, "bbox": [5.0, 6.0, 7.0, 8.0]},
    ]


def test_lance_writer_without_lines_keeps_the_old_anchor_shape():
    from chunking.types import Chunk, ChunkProvenance
    from ingest.lance_writer import chunk_to_lance_row

    chunk = Chunk(
        chunk_id="d1-0000",
        doc_id="d1",
        text="t",
        section_path=[],
        provenance=ChunkProvenance(page=3),
        fiscal_year=2026,
        doc_type="approps-per-agency",
        publisher="jlbc",
        token_count=1,
    )
    row = chunk_to_lance_row(chunk, vector=[0.0])
    assert json.loads(row["source_anchor"]) == {"page": 3}
