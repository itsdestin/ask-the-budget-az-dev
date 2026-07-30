"""Tests for retrieval/api.py — the FastAPI sidecar that fronts the
hybrid retrieval pipeline for the MCP server and the web app.

Post-Plan-1 there is no Postgres and no Voyage account, so the old
"integration tests gated on DATABASE_URL + VOYAGE_API_KEY" layer is
gone. Everything here runs against a REAL LanceDB built in a tmp
directory (pointed at by `JLBC_DATA_DIR`), with the two ONNX models
replaced by fakes:

* Storage is real — chunk fetches, `/docs`, and `/list_values` exercise
  the actual ChunkStore reads, so a column rename or a filter that
  matches nothing fails a test instead of silently emptying an endpoint.
* Models are fake — `LocalEmbedder` / `LocalReranker` are patched at the
  `retrieval.pipeline` seam. Without that the startup warmup query would
  download and load ~150MB of ONNX weights in a unit test.
* `retrieve()` itself is monkeypatched in the route-logic tests (intent →
  top_k, response marshaling) because those assert on shape, not ranking.

Real models over the real corpus are covered by the smoke boot in Task 9
Step 5 and by the eval harness (Task 11), not here.
"""
from __future__ import annotations

import json
from uuid import uuid4

import pytest

fastapi_testclient = pytest.importorskip("fastapi.testclient")

from fastapi.testclient import TestClient

import retrieval.api as api_module
from retrieval.api import app
from retrieval.pipeline import (
    NO_RESULTS_TOP_SCORE,
    RetrievalResult,
    reset_default_collaborators,
)
from retrieval.types import RetrievedChunk
from store.chunk_store import ChunkStore

# Must match ChunkStore's default dim: the pipeline builds its singleton as
# a bare `ChunkStore()`, and opening a table whose vectors are a different
# width raises (by design — see _check_dim).
DIM = 768


# ---------------------------------------------------------------------------
# Fixtures — a real tmp LanceDB corpus + fake models
# ---------------------------------------------------------------------------


def _vec(seed: int) -> list[float]:
    """One-hot DIM-wide vector. Hand-made so no embedding model is needed;
    the exact direction only matters for the ANN ordering, which no test
    here asserts on."""
    v = [0.0] * DIM
    v[seed % DIM] = 1.0
    return v


def _row(chunk_id: str, text: str, *, seed: int = 0, **over) -> dict:
    """A complete chunk row for the LanceDB schema (mirrors the `_row`
    helper in tests/test_chunk_store.py)."""
    row = dict(
        chunk_id=chunk_id,
        doc_id="jlbc-baseline-fy2027-axs",
        text=text,
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=47,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor='{"page": 47}',
        agency_canonical_ids=["agency:axs"],
        fund_canonical_id="fund:ahcccs",
        fund_mentions=["fund:ahcccs"],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=True,
        table_html=None,
        token_count=120,
        publisher="jlbc",
        vector=_vec(seed),
    )
    row.update(over)
    return row


class FakeEmbedder:
    """Stands in for LocalEmbedder. Returns a fixed DIM-wide vector — the
    width has to be right or LanceDB rejects the ANN query."""

    def embed_one(self, text: str, *, input_type: str = "document") -> list[float]:
        return _vec(0)


class FakeReranker:
    """Stands in for LocalReranker: keeps the fused order, slices to top_k."""

    def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_k: int
    ) -> list[RetrievedChunk]:
        return list(chunks)[:top_k]


def _build_corpus(root, rows: list[dict]) -> ChunkStore:
    """Create <root>/lancedb with `rows` in budget_chunks + an FTS index."""
    store = ChunkStore(root=root, dim=DIM)
    store.upsert_chunks("budget_chunks", rows)
    store.build_fts_index("budget_chunks")
    return store


@pytest.fixture(scope="session")
def corpus_dir(tmp_path_factory):
    """One shared tmp corpus for the whole module — building a LanceDB table
    plus its FTS index per test would dominate the suite's runtime. Tests
    that need an exact row set (list_values, docs metadata) use the
    function-scoped `fresh_corpus` fixture instead of this one."""
    root = tmp_path_factory.mktemp("insight-data")
    _build_corpus(root, [
        _row("base-1", "ahcccs provider rates increase in the baseline"),
        _row("base-2", "department of child safety caseworkers", seed=1),
        _row("base-3", "arizona state budget summary", seed=2),
    ])
    return root


@pytest.fixture(autouse=True)
def sidecar_env(monkeypatch, corpus_dir):
    """Point the sidecar at the tmp corpus and keep real models out.

    WHY reset_default_collaborators() on BOTH sides: the store/embedder/
    reranker are process-wide singletons in retrieval.pipeline. Without the
    reset going in, a singleton built against an earlier test's tmp
    directory would still be open here; without the reset coming out, this
    test's tmp store (deleted with the tmp dir) would leak into another
    module's tests. The hook is public for exactly this.
    """
    monkeypatch.setenv("JLBC_DATA_DIR", str(corpus_dir))
    # WHY patch the model classes: the lifespan warmup runs a real
    # retrieve(), which would otherwise download + load ~150MB of ONNX
    # weights on every TestClient(app) in this file.
    monkeypatch.setattr("retrieval.pipeline.LocalEmbedder", FakeEmbedder)
    monkeypatch.setattr("retrieval.pipeline.LocalReranker", FakeReranker)
    reset_default_collaborators()
    yield
    reset_default_collaborators()


@pytest.fixture()
def put_chunk(corpus_dir):
    """Add a chunk to the shared tmp corpus and return its chunk_id.

    Replaces the old `FakeConn` mocks: the cite endpoints now read chunk
    text through ChunkStore, so a test supplies its text by actually
    storing it. Ids are unique per call, so rows accumulating in the
    session corpus can't collide between tests."""
    store = ChunkStore(root=corpus_dir, dim=DIM)

    def _put(text: str, **over) -> str:
        chunk_id = over.pop("chunk_id", f"cite-{uuid4().hex[:8]}")
        store.upsert_chunks("budget_chunks", [_row(chunk_id, text, **over)])
        return chunk_id

    return _put


@pytest.fixture()
def fresh_corpus(tmp_path, monkeypatch):
    """A corpus with EXACTLY the rows a test asks for, in its own tmp dir.

    /list_values and /docs assert on counts and sample titles, which stray
    rows from other tests would perturb — so those tests get a private
    corpus rather than the shared session one.

    `documents=` optionally writes the documents.json sidecar alongside it.
    The api module's cache keys on (path, mtime, size), so pointing
    JLBC_DATA_DIR at a new tmp dir invalidates it without a reset hook."""

    def _make(rows: list[dict], documents: dict | None = None):
        _build_corpus(tmp_path, rows)
        if documents is not None:
            (tmp_path / "documents.json").write_text(
                json.dumps(documents), encoding="utf-8"
            )
        monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
        # The singleton may already be open on the session corpus.
        reset_default_collaborators()

    return _make


# One document's worth of sidecar metadata, shaped exactly like
# scripts/migrate_to_lancedb.py writes it.
_SIDECAR_DOC = {
    "title": "JLBC FY2027 — AHCCCS",
    "publisher": "jlbc",
    "doc_type": "baseline-per-agency",
    "fiscal_year": 2027,
    "source_format": "pdf",
    "source_blob_path": "data/cached-pdfs/40/40831007.pdf",
    "source_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
    "page_count": None,
}


# ---------------------------------------------------------------------------
# Unit tests — /health
# ---------------------------------------------------------------------------


def test_health_endpoint_returns_ok(corpus_dir):
    """Sanity check: /health is reachable and returns the expected shape.
    Used by the dev script + the web app to wait for the sidecar.

    `voyage_key_present` is gone (there is no Voyage key any more);
    `corpus_chunks`, `documents_metadata`, and `data_dir` replace it,
    because "sidecar is up but pointed at an empty corpus" — or at one
    without documents.json, where citation chips can't open a PDF — is the
    failure this probe exists to catch.
    """
    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["version"] == app.version
    assert body["corpus_chunks"] >= 3
    # The shared tmp corpus has no documents.json — 0 is the honest answer.
    assert body["documents_metadata"] == 0
    assert body["data_dir"] == str(corpus_dir)


def test_health_reports_degraded_with_the_real_error(monkeypatch):
    """A dead share must not surface as a bare 500 that throws the reason
    away. 503 (so the web app's `resp.ok` probe still shows its banner)
    plus the actual exception text in the body — never a guessed cause.

    Patched AFTER startup so the preflight isn't the thing that fails."""

    def unreachable():
        raise OSError(r"[WinError 53] The network path was not found: \\JLBC-share")

    with TestClient(app) as client:
        monkeypatch.setattr(api_module, "_store", unreachable)
        resp = client.get("/health")

    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["version"] == app.version
    assert "WinError 53" in body["error"]
    assert "JLBC-share" in body["error"]


def test_health_counts_the_documents_sidecar_when_present(fresh_corpus):
    """documents_metadata is the diagnostic for "why won't my citations open
    a PDF" — it must reflect the file, not a hardcoded 0."""
    fresh_corpus(
        [_row("h1", "chunk", doc_id="agao-afr-fy2025")],
        documents={"agao-afr-fy2025": _SIDECAR_DOC, "other-doc": _SIDECAR_DOC},
    )
    with TestClient(app) as client:
        assert client.get("/health").json()["documents_metadata"] == 2


# ---------------------------------------------------------------------------
# Unit tests — /retrieve (monkeypatched pipeline)
# ---------------------------------------------------------------------------


def _fake_chunk(
    chunk_id: str,
    *,
    doc_id: str = "test-doc",
    score: float = 0.9,
    text: str = "Aviation Fund balance was $123,456.",
    page: int | None = 47,
) -> RetrievedChunk:
    """Build a RetrievedChunk fixture that satisfies every required field.
    Used by tests that monkeypatch retrieve() — the values are never
    compared against the store, only marshaled into the API response."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=doc_id,
        text=text,
        score=score,
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=page,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor=None,
        agency_canonical_ids=["agency:ahcccs"],
        fund_canonical_id="fund:ahcccs",
        fund_mentions=["fund:ahcccs"],
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        is_table=True,
        table_html=None,
        token_count=120,
        publisher="jlbc",
    )


def test_retrieve_marshals_chunks_to_schema_shape(monkeypatch):
    """The MCP `retrieve` tool's return shape is locked in
    citation-tool-schema.md. Confirm the FastAPI sidecar produces
    exactly that shape from a RetrievalResult.
    """
    fake_result = RetrievalResult(
        chunks=[_fake_chunk("c1", doc_id="d1"), _fake_chunk("c2", doc_id="d2")],
        top_score=0.9,
        reranker_scores=[0.9, 0.8],
        bm25_count=42,
        dense_count=37,
        fused_count=20,
    )

    monkeypatch.setattr(api_module, "retrieve", lambda req: fake_result)
    monkeypatch.setattr(
        api_module,
        "_lookup_doc_titles",
        lambda doc_ids: {"d1": "Doc One", "d2": "Doc Two"},
    )

    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={
                "query": "Aviation Fund balance",
                "filters": {"fiscal_year": [2027]},
                "top_k": 5,
            },
        )

    assert resp.status_code == 200
    body = resp.json()

    # Top-level shape per schema doc. `intent` joined in Task 10
    # (2026-05-20) — it's echoed back from the request so the future
    # audit-log writer (WS5) can pick it up; null here because this
    # test doesn't pass an intent.
    assert set(body.keys()) == {
        "chunks",
        "top_score",
        "retrieval_id",
        "bm25_count",
        "dense_count",
        "fused_count",
        "intent",
    }
    assert body["intent"] is None
    assert body["top_score"] == 0.9
    assert body["bm25_count"] == 42
    assert body["dense_count"] == 37
    assert body["fused_count"] == 20
    assert isinstance(body["retrieval_id"], str) and body["retrieval_id"]
    assert len(body["chunks"]) == 2

    # Per-chunk shape. `bbox` joined the schema in Phase 1c WS4c so the
    # PdfViewer can paint a precise rectangle highlight on chip-click;
    # required-field set unchanged otherwise.
    c0 = body["chunks"][0]
    assert set(c0.keys()) == {
        "chunk_id",
        "doc_id",
        "doc_title",
        "publisher",
        "fiscal_year",
        "doc_type",
        "section_path",
        "page_start",
        "page_end",
        "bbox",
        "text",
        "text_length",
        "score",
    }
    assert c0["chunk_id"] == "c1"
    assert c0["doc_id"] == "d1"
    assert c0["doc_title"] == "Doc One"
    assert c0["publisher"] == "jlbc"
    assert c0["fiscal_year"] == 2027
    assert c0["doc_type"] == "baseline-cross-cut"
    assert c0["section_path"] == ["AHCCCS", "Operating Lump Sum"]
    assert c0["page_start"] == 47 and c0["page_end"] == 47
    assert c0["bbox"] == [10.0, 20.0, 100.0, 40.0]
    assert c0["score"] == 0.9


def test_retrieve_calls_the_pipeline_without_injecting_collaborators(monkeypatch):
    """Pins the Plan-1 decision that the sidecar does NOT hold its own
    embedder/store: it calls retrieve(req) bare and lets the pipeline's
    process-wide singletons own the ONNX weights. Passing `embedder=` from
    here (as the Voyage version did) would mean a second resident copy of
    the models."""
    captured: dict = {}

    def fake_retrieve(req, *args, **kwargs):
        captured["args"] = args
        captured["kwargs"] = kwargs
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "x"})

    assert resp.status_code == 200
    assert captured["args"] == ()
    assert captured["kwargs"] == {}


def test_sidecar_shares_the_pipelines_store_singleton():
    """Same decision from the other side: the store the cite/docs endpoints
    read is the identical object the retrieval pipeline searches, so there
    is exactly one set of LanceDB table handles per process."""
    from retrieval import pipeline

    assert api_module._store() is pipeline._get_store()


def test_retrieve_empty_filters_omitted(monkeypatch):
    """Filters block is optional; sidecar should accept the bare
    `{ query }` body and pass through to retrieve()."""
    captured: dict = {}

    def fake_retrieve(req):
        captured["req"] = req
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "x"})

    assert resp.status_code == 200
    req = captured["req"]
    assert req.query == "x"
    assert req.fiscal_year is None
    assert req.publisher is None
    assert req.is_table is None


def test_retrieve_empty_query_returns_zero_chunks(monkeypatch):
    """retrieve() short-circuits on whitespace queries — sidecar should
    pass the empty result through cleanly with retrieval_id still set
    (the audit log writer relies on its presence).

    top_score is the no-results SENTINEL, not 0.0: reranker scores are raw
    cross-encoder logits now, and 0.0 would outrank a genuinely-bad hit.
    It serializes as -1000000000.0."""
    monkeypatch.setattr(api_module, "retrieve", lambda req: RetrievalResult())

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "   "})

    assert resp.status_code == 200
    body = resp.json()
    assert body["chunks"] == []
    assert body["top_score"] == NO_RESULTS_TOP_SCORE == -1e9
    assert body["retrieval_id"]


def test_retrieve_rejects_malformed_filter_types():
    """fiscal_year must be a list of ints; a string should 422."""
    with TestClient(app) as client:
        resp = client.post(
            "/retrieve",
            json={"query": "x", "filters": {"fiscal_year": "2027"}},
        )
    assert resp.status_code == 422


def test_retrieve_rejects_top_k_below_one():
    """A client top_k of 0 or -1 used to reach the reranker and surface as
    an opaque 500. `Field(ge=1)` turns it into a 422 that names the field."""
    with TestClient(app) as client:
        for bad in (0, -3):
            resp = client.post("/retrieve", json={"query": "x", "top_k": bad})
            assert resp.status_code == 422, bad
            assert "top_k" in resp.text


def test_retrieve_filters_pass_through_to_pipeline(monkeypatch):
    """Each documented filter dimension reaches RetrievalRequest in the
    correct field. Catches accidental rename / drop bugs."""
    captured: dict = {}

    def fake_retrieve(req):
        captured["req"] = req
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    payload = {
        "query": "x",
        "filters": {
            "fiscal_year": [2027, 2026],
            "doc_type": ["baseline-cross-cut"],
            "publisher": ["jlbc"],
            "agency_canonical_id": ["agency:ahcccs"],
            "fund_canonical_id": ["fund:ahcccs"],
            "is_table": True,
        },
        "top_k": 7,
    }

    with TestClient(app) as client:
        resp = client.post("/retrieve", json=payload)
    assert resp.status_code == 200

    req = captured["req"]
    assert req.fiscal_year == [2027, 2026]
    assert req.doc_type == ["baseline-cross-cut"]
    assert req.publisher == ["jlbc"]
    assert req.agency_canonical_id == ["agency:ahcccs"]
    assert req.fund_canonical_id == ["fund:ahcccs"]
    assert req.is_table is True
    assert req.top_k == 7


def test_retrieve_end_to_end_over_the_real_store():
    """The one /retrieve test that goes through the REAL pipeline and the
    REAL store (fake models only): it would catch a store/pipeline wiring
    break that every monkeypatched test above sails past. This fixture has
    no documents.json, so doc_title takes the slug-humanizer fallback (the
    sidecar-present path is test_doc_titles_prefer_the_real_ingest_title)."""
    with TestClient(app) as client:
        resp = client.post(
            "/retrieve", json={"query": "ahcccs provider rates", "top_k": 3}
        )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["chunks"]) > 0
    assert body["top_score"] > NO_RESULTS_TOP_SCORE
    assert body["retrieval_id"]
    for c in body["chunks"]:
        assert c["doc_title"], f"chunk {c['chunk_id']} missing doc_title"
        assert c["text_length"] == len(c["text"])


def test_doc_titles_fall_back_to_the_slug_humanizer():
    """With no documents.json, doc_title is a best-effort prettification of
    the slug. Kept character-identical to the web app's copy of this
    humanizer so the two layers agree on a title."""
    assert api_module._title_from_doc_id("jlbc-baseline-fy2027-axs") == (
        "JLBC Baseline FY 2027 Axs"
    )
    assert api_module._title_from_doc_id("agao-afr-fy2025") == "AGAO AFR FY 2025"
    assert api_module._lookup_doc_titles(["agao-afr-fy2025"]) == {
        "agao-afr-fy2025": "AGAO AFR FY 2025"
    }
    assert api_module._lookup_doc_titles([]) == {}


def test_doc_titles_prefer_the_real_ingest_title(fresh_corpus, monkeypatch):
    """These titles are what the MODEL reads in every retrieve() result, so
    the sidecar's real title ("JLBC FY2027 — AHCCCS") beats the stuttery
    slug form ("Governor Governors Budget FY 2027"). A doc the sidecar
    doesn't know still gets the derived title in the same response."""
    fresh_corpus(
        [_row("t1", "chunk", doc_id="jlbc-baseline-fy2027-axs")],
        documents={"jlbc-baseline-fy2027-axs": _SIDECAR_DOC},
    )
    assert api_module._lookup_doc_titles(
        ["jlbc-baseline-fy2027-axs", "agao-afr-fy2025"]
    ) == {
        "jlbc-baseline-fy2027-axs": "JLBC FY2027 — AHCCCS",
        "agao-afr-fy2025": "AGAO AFR FY 2025",
    }

    # …and it reaches the /retrieve response, not just the helper.
    monkeypatch.setattr(
        api_module,
        "retrieve",
        lambda req: RetrievalResult(
            chunks=[_fake_chunk("c1", doc_id="jlbc-baseline-fy2027-axs")],
            top_score=0.9,
        ),
    )
    with TestClient(app) as client:
        body = client.post("/retrieve", json={"query": "x"}).json()
    assert body["chunks"][0]["doc_title"] == "JLBC FY2027 — AHCCCS"


# ---------------------------------------------------------------------------
# Unit tests — /cite/validate (real store reads)
# ---------------------------------------------------------------------------


def test_cite_validate_rejects_unknown_chunk_id():
    """`unknown chunk_id` is the dominant hallucination mode; the
    server-side check catches it cleanly so Claude sees the error in
    the tool result and self-corrects."""
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": "made-up", "span_start": 0, "span_end": 10},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "unknown chunk_id"


def test_cite_validate_rejects_out_of_range_span(put_chunk):
    """Returns the actual `chunk_text_length` so the model can self-correct."""
    chunk_id = put_chunk("x" * 50)

    with TestClient(app) as client:
        # 200 over a 50-char chunk — 200 > max(50 abs, 2.5 ratio) so
        # this is above the auto-clamp budget and rejects cleanly.
        # Smaller overflows now clamp (covered by the dedicated
        # test_span_end_auto_clamp_small_overflow test below).
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": chunk_id, "span_start": 0, "span_end": 250},
        )

    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"
    assert body["chunk_text_length"] == 50


def test_cite_validate_accepts_valid_span(put_chunk):
    chunk_id = put_chunk("x" * 50)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": chunk_id, "span_start": 0, "span_end": 25},
        )

    body = resp.json()
    assert body["ok"] is True
    assert body["chunk_text_length"] == 50


def test_cite_validate_rejects_inverted_span(put_chunk):
    """span_end <= span_start is structurally invalid; we don't even
    need to know chunk_text_length to reject it. Belt-and-braces case
    in case Pydantic field constraints get relaxed in the future."""
    chunk_id = put_chunk("x" * 50)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": chunk_id, "span_start": 30, "span_end": 30},
        )

    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"


def test_cite_validate_against_a_real_stored_chunk(put_chunk):
    """The chunk-fetch seam itself: text stored through ChunkStore comes
    back with the right length through /cite/validate. Catches a column
    rename or a filter that silently matches nothing."""
    text = "The Aviation Fund balance was $123,456 as of June 30, 2024."
    chunk_id = put_chunk(text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={"chunk_id": chunk_id, "span_start": 0, "span_end": 5},
        )
    body = resp.json()
    assert body["ok"] is True
    assert body["chunk_text_length"] == len(text)


# ---------------------------------------------------------------------------
# Unit tests — /docs/{doc_id}
# ---------------------------------------------------------------------------


def test_doc_metadata_flows_the_sidecar_fields_through(fresh_corpus):
    """THE PDF-viewer contract: with documents.json present, /docs returns
    the real title and — critically — source_format + source_blob_path.
    Without them the web app's /api/pdf/[doc_id] route takes its
    "unsupported_source_format" branch for every citation chip, which reads
    as a broken PDF instead of missing metadata (and suspends the
    citation-opens-the-exact-page invariant)."""
    fresh_corpus(
        [_row("d1-c1", "first chunk", doc_id="jlbc-baseline-fy2027-axs")],
        documents={"jlbc-baseline-fy2027-axs": _SIDECAR_DOC},
    )

    with TestClient(app) as client:
        resp = client.get("/docs/jlbc-baseline-fy2027-axs")

    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == "jlbc-baseline-fy2027-axs"
    assert body["title"] == "JLBC FY2027 — AHCCCS"  # real title, not the slug
    assert body["source_format"] == "pdf"
    assert body["source_blob_path"] == "data/cached-pdfs/40/40831007.pdf"
    assert body["source_url"] == "https://www.azjlbc.gov/27baseline/axs.pdf"
    assert body["publisher"] == "jlbc"
    assert body["doc_type"] == "baseline-per-agency"
    assert body["fiscal_year"] == 2027
    # page_count is null even in the sidecar (the ingest never populated the
    # column), so it stays omitted rather than guessed.
    assert "page_count" not in body


def test_doc_metadata_falls_back_to_chunk_columns_without_the_sidecar(fresh_corpus):
    """A corpus copied without documents.json still answers: publisher /
    doc_type / fiscal_year are denormalized onto every chunk, and the title
    degrades to the slug humanizer. The PDF-locating fields are omitted
    rather than guessed — a fabricated path would make the PDF route fail
    with a misleading "file missing" error."""
    fresh_corpus([_row("d2-c1", "only chunk", doc_id="agao-afr-fy2025")])

    with TestClient(app) as client:
        resp = client.get("/docs/agao-afr-fy2025")

    body = resp.json()
    assert resp.status_code == 200
    assert body["title"] == "AGAO AFR FY 2025"  # derived
    assert body["publisher"] == "jlbc"  # from the chunk row
    assert "source_blob_path" not in body
    assert "source_format" not in body
    assert "source_url" not in body
    assert "page_count" not in body


def test_doc_metadata_sidecar_fields_win_over_chunk_columns(fresh_corpus):
    """When both sources know a field, the sidecar wins — it is the ingest
    record, while the chunk copy is a denormalized snapshot that a
    re-ingest could leave behind."""
    fresh_corpus(
        [_row("d5-c1", "chunk", doc_id="agao-afr-fy2025", publisher="jlbc",
              fiscal_year=2027)],
        documents={"agao-afr-fy2025": {**_SIDECAR_DOC, "publisher": "agao",
                                       "fiscal_year": 2025, "doc_type": "afr"}},
    )

    with TestClient(app) as client:
        body = client.get("/docs/agao-afr-fy2025").json()
    assert body["publisher"] == "agao"
    assert body["fiscal_year"] == 2025
    assert body["doc_type"] == "afr"


def test_doc_metadata_answers_for_a_document_with_no_chunks(fresh_corpus):
    """The Postgres version read the documents table, so a document whose
    chunks were never loaded still resolved. Preserve that: the sidecar
    alone is enough to answer."""
    fresh_corpus(
        [_row("d6-c1", "unrelated chunk", doc_id="jlbc-baseline-fy2027-axs")],
        documents={"governor-governors-budget-fy2027": _SIDECAR_DOC},
    )

    with TestClient(app) as client:
        resp = client.get("/docs/governor-governors-budget-fy2027")
    assert resp.status_code == 200
    assert resp.json()["source_format"] == "pdf"


def test_doc_metadata_ignores_a_malformed_sidecar(fresh_corpus, capfd):
    """A truncated / hand-broken documents.json must not 500 every request.
    Degrade to derived titles, and say which file and what parse error so
    the fix is obvious."""
    fresh_corpus([_row("d7-c1", "chunk", doc_id="agao-afr-fy2025")])
    (api_module.documents_path()).write_text("{not json", encoding="utf-8")

    with TestClient(app) as client:
        resp = client.get("/docs/agao-afr-fy2025")
    assert resp.status_code == 200
    assert resp.json()["title"] == "AGAO AFR FY 2025"
    assert "documents.json" in capfd.readouterr().err


def test_document_metadata_reloads_when_the_file_changes(fresh_corpus):
    """mtime+size-keyed cache, not load-once: an ingest (or a --docs-only
    refresh) has to show up without restarting the sidecar."""
    fresh_corpus(
        [_row("d8-c1", "chunk", doc_id="agao-afr-fy2025")],
        documents={"agao-afr-fy2025": {**_SIDECAR_DOC, "title": "First Title"}},
    )
    assert api_module._document_metadata()["agao-afr-fy2025"]["title"] == "First Title"

    api_module.documents_path().write_text(
        json.dumps({"agao-afr-fy2025": {**_SIDECAR_DOC, "title": "Second Title!!"}}),
        encoding="utf-8",
    )
    assert (
        api_module._document_metadata()["agao-afr-fy2025"]["title"] == "Second Title!!"
    )


def test_doc_metadata_returns_404_for_unknown_doc(fresh_corpus):
    """Hallucinated doc_ids hit 404 cleanly (the Next.js route relays
    that to the browser as a 404 too — no PDF panel painted)."""
    fresh_corpus([_row("d3-c1", "only chunk", doc_id="jlbc-approps-fy2025-adc")])

    with TestClient(app) as client:
        resp = client.get("/docs/ghost-doc")
    assert resp.status_code == 404


def test_doc_metadata_survives_an_apostrophe_in_the_doc_id(fresh_corpus):
    """The doc_id reaches a LanceDB filter, and LanceDB filters are SQL
    strings with no parameter binding — an unescaped apostrophe would be a
    DataFusion parse error (500) instead of a lookup."""
    fresh_corpus([_row("d4-c1", "only chunk", doc_id="o'brien-fy2026")])

    with TestClient(app) as client:
        resp = client.get("/docs/o'brien-fy2026")
    assert resp.status_code == 200
    assert resp.json()["doc_id"] == "o'brien-fy2026"


# ---------------------------------------------------------------------------
# Unit tests — /list_values (LanceDB scan + Python aggregation)
# ---------------------------------------------------------------------------


def _list_values(field: str):
    with TestClient(app) as client:
        resp = client.post("/list_values", json={"field": field})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_list_values_agency_counts_chunks_and_samples_a_title(fresh_corpus):
    """agency_canonical_ids is an array column, so one chunk can count
    toward several agencies (the Postgres version unnested it).

    No documents.json in this fixture, so the sample title takes the
    slug-humanizer FALLBACK. The sidecar-present path — the one that
    actually makes `agency:axs` recognizable — is the next test."""
    fresh_corpus([
        _row("a1", "axs chunk", agency_canonical_ids=["agency:axs"]),
        _row("a2", "axs + adc chunk",
             agency_canonical_ids=["agency:axs", "agency:adc"]),
        _row("a3", "adc chunk in the adc book", agency_canonical_ids=["agency:adc"],
             doc_id="jlbc-approps-fy2025-adc"),
        _row("a4", "another adc chunk in the adc book",
             agency_canonical_ids=["agency:adc"], doc_id="jlbc-approps-fy2025-adc"),
    ])

    body = _list_values("agency")
    assert body["field"] == "agency"
    values = {v["canonical_id"]: v for v in body["values"]}
    assert values["agency:axs"]["chunk_count"] == 2
    assert values["agency:adc"]["chunk_count"] == 3
    # Sorted by chunk_count desc.
    assert [v["canonical_id"] for v in body["values"]] == [
        "agency:adc",
        "agency:axs",
    ]
    # adc's sample is the document that is ABOUT adc (2 of its chunks) — not
    # the axs book that mentions it once.
    assert values["agency:adc"]["sample_doc_title"] == "JLBC Approps FY 2025 Adc"
    assert values["agency:axs"]["sample_doc_title"] == "JLBC Baseline FY 2027 Axs"


def test_list_values_samples_the_most_populated_document(fresh_corpus):
    """THE sample-selection rule, and the reason it isn't the Postgres
    "newest document" rule: on the real corpus the newest document
    mentioning nearly every agency is the FY2027 Governor's Budget — one
    cross-cutting book titled "GOVERNOR FY2027 fy2027", which explains
    nothing about `agency:axs`. Here the cross-cutting doc is even NEWER and
    still must lose to the book that is actually about the agency."""
    fresh_corpus(
        [
            _row("g1", "governor mentions axs", doc_id="governor-budget-fy2028",
                 fiscal_year=2028, agency_canonical_ids=["agency:axs"]),
            _row("b1", "axs book chunk", doc_id="jlbc-baseline-fy2027-axs",
                 agency_canonical_ids=["agency:axs"]),
            _row("b2", "axs book chunk two", doc_id="jlbc-baseline-fy2027-axs",
                 agency_canonical_ids=["agency:axs"]),
        ],
        documents={
            "governor-budget-fy2028": {**_SIDECAR_DOC,
                                       "title": "GOVERNOR FY2028 fy2028"},
            "jlbc-baseline-fy2027-axs": _SIDECAR_DOC,
        },
    )
    values = {v["canonical_id"]: v for v in _list_values("agency")["values"]}
    assert values["agency:axs"]["chunk_count"] == 3
    assert values["agency:axs"]["sample_doc_title"] == "JLBC FY2027 — AHCCCS"


def test_list_values_sample_titles_come_from_the_sidecar(fresh_corpus):
    """THE point of sample_doc_title: it exists to explain an opaque
    canonical_id, so it has to be the real ingest title. A humanized slug
    ("JLBC Baseline FY 2027 Axs") is exactly as opaque as `agency:axs`,
    which is what FilterValueOut's docstring and the MCP tool's own test
    (mcp-server/tests/list-filter-values.test.ts, asserting the sample
    contains "AHCCCS") expect to be fixed by the sidecar."""
    fresh_corpus(
        [
            _row("s1", "axs chunk", agency_canonical_ids=["agency:axs"],
                 fund_canonical_id="fund:ahcccs"),
            _row("s2", "older adc chunk", agency_canonical_ids=["agency:adc"],
                 doc_id="jlbc-approps-fy2025-adc", fiscal_year=2025,
                 doc_type="approps-per-agency", fund_canonical_id=None),
        ],
        documents={
            "jlbc-baseline-fy2027-axs": _SIDECAR_DOC,
            "jlbc-approps-fy2025-adc": {**_SIDECAR_DOC,
                                        "title": "JLBC FY2025 — Corrections"},
        },
    )

    agencies = {
        v["canonical_id"]: v["sample_doc_title"]
        for v in _list_values("agency")["values"]
    }
    assert agencies["agency:axs"] == "JLBC FY2027 — AHCCCS"
    assert agencies["agency:adc"] == "JLBC FY2025 — Corrections"

    funds = {
        v["canonical_id"]: v["sample_doc_title"]
        for v in _list_values("fund")["values"]
    }
    assert funds["fund:ahcccs"] == "JLBC FY2027 — AHCCCS"

    # doc_type / publisher take MIN(title) over the group's REAL titles.
    doc_types = {
        v["canonical_id"]: v["sample_doc_title"]
        for v in _list_values("doc_type")["values"]
    }
    assert doc_types["baseline-per-agency"] == "JLBC FY2027 — AHCCCS"
    assert doc_types["approps-per-agency"] == "JLBC FY2025 — Corrections"
    publishers = {
        v["canonical_id"]: v["sample_doc_title"]
        for v in _list_values("publisher")["values"]
    }
    # Two jlbc docs; MIN over the real titles picks the FY2025 one
    # alphabetically ("JLBC FY2025 …" < "JLBC FY2027 …").
    assert publishers["jlbc"] == "JLBC FY2025 — Corrections"


def test_list_values_sample_title_falls_back_per_document(fresh_corpus):
    """Per-doc fallback, not all-or-nothing: a document the sidecar hasn't
    caught up with still gets a humanized-slug sample while its neighbours
    keep their real titles."""
    fresh_corpus(
        [
            _row("m1", "axs chunk", agency_canonical_ids=["agency:axs"]),
            _row("m2", "adc chunk", agency_canonical_ids=["agency:adc"],
                 doc_id="jlbc-approps-fy2025-adc", fiscal_year=2025),
        ],
        documents={"jlbc-baseline-fy2027-axs": _SIDECAR_DOC},
    )
    agencies = {
        v["canonical_id"]: v["sample_doc_title"]
        for v in _list_values("agency")["values"]
    }
    assert agencies["agency:axs"] == "JLBC FY2027 — AHCCCS"
    assert agencies["agency:adc"] == "JLBC Approps FY 2025 Adc"


def test_list_values_fund_skips_rows_without_a_fund(fresh_corpus):
    """fund_canonical_id is nullable; the Postgres version filtered
    `IS NOT NULL` so a NULL never became a value named "None"."""
    fresh_corpus([
        _row("f1", "fund chunk", fund_canonical_id="fund:aviation"),
        _row("f2", "fund chunk again", fund_canonical_id="fund:aviation"),
        _row("f3", "no fund chunk", fund_canonical_id=None),
    ])

    body = _list_values("fund")
    assert [(v["canonical_id"], v["chunk_count"]) for v in body["values"]] == [
        ("fund:aviation", 2)
    ]


def test_list_values_doc_type_and_publisher_count_documents(fresh_corpus):
    """Inherited semantics: the Postgres version aggregated the DOCUMENTS
    table for these two dimensions, so the count is distinct doc_ids, not
    chunks (FilterValueOut's docstring says "chunks (or documents)"). Kept
    as-is so the numbers the model sees don't change meaning."""
    fresh_corpus([
        _row("p1", "chunk", doc_id="jlbc-baseline-fy2027-axs"),
        _row("p2", "chunk", doc_id="jlbc-baseline-fy2027-axs", page=2),
        _row("p3", "chunk", doc_id="jlbc-approps-fy2025-adc",
             doc_type="approps-per-agency"),
        _row("p4", "chunk", doc_id="agao-afr-fy2025", doc_type="afr",
             publisher="agao"),
    ])

    doc_types = {
        v["canonical_id"]: v["chunk_count"] for v in _list_values("doc_type")["values"]
    }
    # 2 chunks in one baseline doc → count 1.
    assert doc_types == {
        "baseline-per-agency": 1,
        "approps-per-agency": 1,
        "afr": 1,
    }

    publishers = {
        v["canonical_id"]: v["chunk_count"]
        for v in _list_values("publisher")["values"]
    }
    assert publishers == {"jlbc": 2, "agao": 1}


def test_list_values_rejects_an_unknown_field():
    with TestClient(app) as client:
        resp = client.post("/list_values", json={"field": "flavor"})
    assert resp.status_code == 400
    assert "unknown field" in resp.json()["detail"]


def test_list_values_normalizes_field_case_and_whitespace(fresh_corpus):
    """The Postgres version lowercased + stripped before dispatching; a
    client sending " Agency " must not get a 400."""
    fresh_corpus([_row("n1", "chunk")])
    body = _list_values("  Agency ")
    assert body["field"] == "agency"
    assert body["values"][0]["canonical_id"] == "agency:axs"


# ---------------------------------------------------------------------------
# Unit tests — citation-alignment helpers (no store needed)
# ---------------------------------------------------------------------------


def test_normalize_for_match_folds_quotes_and_dashes():
    """NFKC + smart-quote folds + dash folds must match the renderer's
    normalizeForMatch (web/lib/citation-extract.ts:376). If these
    diverge, a claim_span the renderer finds in the PDF text-layer
    won't pass server-side validation here — same input, different
    verdict per layer."""
    n = api_module._normalize_for_match
    assert n("“Hello”") == '"hello"'  # smart double quotes
    assert n("don’t") == "don't"  # smart apostrophe
    assert n("a—b") == "a-b"  # em dash
    assert n("a–b") == "a-b"  # en dash
    assert n("ﬁle") == "file"  # NFKC ligature
    assert n("  multi   spaces  ") == "multi spaces"


def test_normalize_for_match_strips_markdown_tokens():
    """Bold/italic/code/pipe must be stripped so the model's
    markdown-formatted claim_span matches the raw PDF text in the
    chunk (which has no markdown)."""
    n = api_module._normalize_for_match
    assert n("**bold**") == "bold"
    assert n("*italic*") == "italic"
    assert n("`code`") == "code"
    assert n("[label](http://example.com)") == "label"
    assert n("| FY 2024 | $4,679,100 |") == "fy 2024 $4,679,100"


def test_normalize_for_match_decodes_html_entities():
    """parseInlineCiteAttrs on the renderer side decodes &quot; etc.
    before matching; mirror that here or quoted claim_spans (common
    in budget bills citing statute names) will silently fail."""
    n = api_module._normalize_for_match
    assert n("&quot;Aviation Fund&quot;") == '"aviation fund"'
    assert n("&amp;") == "&"


def test_normalize_strips_markdown_backslash_escapes():
    """MinerU emits `\\$(10,000,000)` to prevent `$…$` from rendering
    as math; the PDF text layer and the model's claim_span both use
    the unescaped form. Without backslash-stripping, the verbatim
    substring check fails because `\\$` and `$` are different chars.

    This was the 2026-05-11 cite-#14 root cause: chunk text had
    `\\$(10,000,000)` and findTextRects couldn't match it against the
    PDF, so the renderer fell back to the chunk's coarse bbox."""
    n = api_module._normalize_for_match
    assert n(r"\$10,000,000") == "$10,000,000"
    assert n(r"\(10,000,000\)") == "(10,000,000)"
    assert n(r"\[note\]") == "[note]"
    # All CommonMark-escapable punctuation. Note: after backslash is
    # stripped, the bare `*` / `_` / `` ` `` chars are then handled by
    # the bold/italic/code markdown stripper later in the pipeline and
    # disappear — so escaped emphasis markers collapse to whitespace,
    # NOT to literal `*`. Same logic as the renderer's normalize.
    assert n(r"\\ \` \* \_ \{ \} \[ \] \( \) \# \+ \- \. \! \| \> \~ \$") == \
        "\\ { } [ ] ( ) # + - . ! > ~ $"


def test_normalize_collapses_accounting_parens_on_dollars():
    """`$(10,000,000)` and `($10,000,000)` both denote accounting
    negatives; for citation alignment, treat both as `$10,000,000`
    so a claim that says "removes $10 million" matches a source that
    uses either convention. The sign is in the verb, not the parens.
    2026-05-12: added paren-first form for parity with the PDF text
    layer (pdfjs renders `($X)` even when the source PDF was MinerU-
    extracted with `\\$(X)`)."""
    n = api_module._normalize_for_match
    # Dollar-first convention (MinerU's preferred markdown output).
    assert n("$(10,000,000)") == "$10,000,000"
    assert n(r"decrease of \$(10,000,000)") == "decrease of $10,000,000"
    # Paren-first convention (pdfjs text-layer output).
    assert n("($10,000,000)") == "$10,000,000"
    assert n("decrease of ($3,500,000) from the General Fund") == \
        "decrease of $3,500,000 from the general fund"
    # Non-dollar parens left alone (don't accidentally strip
    # parenthesized notes like "(Item 9 of Section 116)" or
    # "(see footnote 1)").
    assert n("note (see footnote 1)") == "note (see footnote 1)"
    assert n("(Item 9 of Section 116)") == "(item 9 of section 116)"


def test_normalize_expands_abbreviated_dollar_amounts():
    """Single highest-leverage fix from the 2026-05-11 audit: models
    write `$40 million` while sources use `$40,000,000`. Without
    expansion, the content-word check treats `$40` and `$40,000,000`
    as different tokens and paraphrase overlap craters."""
    n = api_module._normalize_for_match
    assert n("$40 million") == "$40,000,000"
    assert n("$5.0 million") == "$5,000,000"
    assert n("$11.5 M") == "$11,500,000"
    assert n("$501.9 million") == "$501,900,000"
    assert n("$1.74B") == "$1,740,000,000"
    assert n("$10K") == "$10,000"
    assert n("$10 thousand") == "$10,000"
    # Case-insensitive units.
    assert n("$5 MILLION") == "$5,000,000"
    # Already-expanded numbers untouched.
    assert n("$40,000,000") == "$40,000,000"
    # Word-boundary protection: "$10 minute" shouldn't match "m".
    assert n("$10 minute") == "$10 minute"
    # Decimal precision preserved through the int conversion.
    assert n("$0.5 million") == "$500,000"


def test_normalize_dollar_expansion_handles_audit_failure_case():
    """Reproduces cite-#14 from the 2026-05-11 audit: the model wrote
    a paraphrase claim with `$10 million` and `$40 million`, and the
    chunk text had `\\$(10,000,000)` and `$40,000,000`. With the new
    normalize: claim's `$10,000,000` and `$40,000,000` tokens both
    appear in the chunk after backslash-stripping + paren-collapse +
    dollar-expansion."""
    cw = api_module._content_words
    n = api_module._normalize_for_match
    claim = (
        "The JLBC FY 2027 Baseline continues the $40 million ongoing "
        "transfer to ADC but removes the FY 2026 $10 million Coordinated "
        "Reentry appropriation as one-time funding."
    )
    chunk = (
        r"Remove One-Time Funding. The Baseline includes a decrease of "
        r"\$(10,000,000) from the Consumer Remediation Subaccount in FY "
        r"2027 for Coordinated Reentry. A separate footnote requires the "
        r"AG to transfer $40,000,000 ongoing to the ADC Opioid "
        r"Remediation Fund."
    )
    claim_words = cw(n(claim))
    chunk_words = set(cw(n(chunk)))
    # Both dollar amounts must match across the abbreviation gap.
    # Currency tokens canonicalize to bare-number form (no $ prefix).
    assert "10,000,000" in claim_words
    assert "10,000,000" in chunk_words
    assert "40,000,000" in claim_words
    assert "40,000,000" in chunk_words


def test_check_alignment_now_passes_audit_failure_case():
    """End-to-end on cite-#14 from the audit: with the normalize
    upgrades, the paraphrase overlap clears the 0.60 threshold so the
    validator returns None (no error) for what was previously a
    7/17 = 0.41 failure."""
    claim = (
        "The JLBC FY 2027 Baseline continues the $40 million ongoing "
        "transfer to ADC but removes the FY 2026 $10 million Coordinated "
        "Reentry appropriation as one-time funding."
    )
    chunk = (
        r"Remove One-Time Funding. The Baseline includes a decrease of "
        r"\$(10,000,000) from the Consumer Remediation Subaccount in FY "
        r"2027 for Coordinated Reentry. A separate footnote requires the "
        r"AG to transfer $40,000,000 ongoing to the ADC Opioid "
        r"Remediation Fund Baseline appropriation, one-time funding "
        r"removes the JLBC continues."
    )
    err = api_module._check_alignment(chunk, claim, "paraphrase")
    assert err is None


def test_content_words_includes_numbers_and_currency():
    """Dollar amounts and bare numbers are the most diagnostic words
    in budget claims — a paraphrase cite that drops the $4,677,100
    figure has lost the actual support. Currency tokens are emitted
    in canonical bare-number form (no `$` prefix) so claim vs cited
    compare symmetrically regardless of which side has the sign."""
    cw = api_module._content_words
    # Currency emitted as bare number — `$X` → `X`.
    assert "4,677,100" in cw(api_module._normalize_for_match("Total $4,677,100 in FY 2024"))
    assert "2024" in cw(api_module._normalize_for_match("Total $4,677,100 in FY 2024"))
    # Short words (≤3 chars) excluded.
    assert "the" not in cw(api_module._normalize_for_match("the the the the"))


def test_check_alignment_verbatim_pass():
    """Strict normalized substring — the cited text must contain the
    claim verbatim (after normalize folds)."""
    err = api_module._check_alignment(
        "The Baseline includes $4,677,100 for FY 2026.",
        "Baseline includes $4,677,100",
        "verbatim",
    )
    assert err is None


def test_check_alignment_verbatim_fail_with_suggestion():
    """Verbatim mismatch returns an error that tells the model to
    either re-pick the span or downgrade to paraphrase. Both options
    are actionable; an unhelpful error string drives the model to
    invent yet another wrong cite. Wholly-mismatched cites must still
    fail even with the loosened threshold."""
    err = api_module._check_alignment(
        "Operating Budget composition: General Fund $342,500.",
        "$6,000,000 (one-time) for secure ballot paper",
        "verbatim",
    )
    assert err is not None
    assert "verbatim" in err
    assert "paraphrase" in err  # suggests downgrade option


def test_check_alignment_verbatim_loose_accepts_label_prefixed_claims():
    """The 2026-05-12 user-feedback case: the model wrote
    `**FY 2025 (Approved):** $4,677,100 and 38.4 FTE — $342,500 General
    Fund + $4,334,600 State Treasurer's Operating Fund.` and chose
    verbatim. Every load-bearing figure IS in the source; only the
    label `(Approved)` is the model's addition. Strict substring
    rejected this; loose verbatim (≥85% content-word overlap) accepts
    it. Verifying with the actual chunk text shape from the audit."""
    chunk_text = (
        r"Operating Budget |  | The budget includes \$4,677,100 and 38.4 "
        r"FTE Positions in FY 2025 for the operating budget. These amounts "
        r"consist of: |  | General Fund \$342,500 |  | State Treasurer's "
        r"Operating Fund 4,334,600 |  | Adjustments are"
    )
    claim = (
        "**FY 2025 (Approved):** $4,677,100 and 38.4 FTE — $342,500 "
        "General Fund + $4,334,600 State Treasurer's Operating Fund."
    )
    err = api_module._check_alignment(chunk_text, claim, "verbatim")
    assert err is None


def test_content_words_canonicalizes_currency_to_bare_form():
    """`$4,334,600` in the claim and `4,334,600` in the source both
    canonicalize to bare `4,334,600` — so set-based overlap matches
    symmetrically. This replaces the earlier dual-emit approach
    which inflated the claim-token count when one side had `$X` and
    the other bare `X`."""
    cw = api_module._content_words
    n = api_module._normalize_for_match
    # Currency token emitted as bare number (no $ prefix).
    tokens = cw(n("Total $4,334,600 in FY 2025"))
    assert "4,334,600" in tokens
    assert "$4,334,600" not in tokens
    # Bare numbers without $ stay bare (consistent).
    bare_tokens = cw(n("38.4 FTE"))
    assert "38.4" in bare_tokens
    assert "$38.4" not in bare_tokens


def test_check_alignment_verbatim_single_dollar_token():
    """The 2026-05-12 audit cite #22 pattern: model verbatim-cites
    a single dollar figure (`$131,582,200`) against a chunk that
    contains the bare number (`131,582,200`, without `$`). With the
    old dual-emit approach this scored 1/2 = 50% and failed; with
    canonical bare-number tokens it scores 1/1 = 100% and passes.
    No store needed — go direct to _check_alignment to keep this fast."""
    err = api_module._check_alignment(
        "AGENCY TOTAL 131,582,200 23,303,200 18,401,400",
        "$131,582,200",
        "verbatim",
    )
    assert err is None


def test_check_alignment_paraphrase_pass_high_overlap():
    """A genuine paraphrase: claim restates the chunk's content with
    different ordering / connective words but same content words."""
    err = api_module._check_alignment(
        "The Baseline includes $4,721,600 and 38.4 FTE Positions in "
        "FY 2027 for the operating budget. These amounts are unchanged "
        "from FY 2026.",
        "The FY 2027 Baseline operating budget of $4,721,600 with 38.4 "
        "FTE is unchanged from FY 2026.",
        "paraphrase",
    )
    assert err is None


def test_check_alignment_paraphrase_fail_low_overlap():
    """The cite-#18 pattern from the 2026-05-11 audit: claim is about
    'ballot paper', cited span is about 'Operating Budget composition'.
    Content-word overlap is near zero and the validator must catch it."""
    err = api_module._check_alignment(
        "Operating Budget composition: General Fund $342,500. State "
        "Treasurer's Operating Fund $4,334,600.",
        "$6,000,000 (one-time) for secure ballot paper",
        "paraphrase",
    )
    assert err is not None
    assert "paraphrase" in err
    assert "content words" in err


# ---------------------------------------------------------------------------
# /cite/validate behavior over stored chunks
# ---------------------------------------------------------------------------


def test_cite_validate_alignment_check_no_longer_rejects(put_chunk):
    """Regression / contract: as of 2026-05-20, /cite/validate no
    longer enforces a content-word-overlap check between claim_span
    and the cited chunk text. The dogfood pass that day showed a ~40%
    false-rejection rate on claims that were semantically faithful but
    used different wording (abbreviated dollars, markdown-table
    formatting, etc.) — the resulting retry loop dominated query
    latency. The check was a string-overlap heuristic, not a real
    faithfulness check; the actual NLI verifier (WS3) will live
    elsewhere. So a claim_span with NO word overlap against the cited
    span (here: `$6,000,000 one-time for secure ballot paper` vs an
    Operating Budget paragraph) now passes."""
    chunk_text = (
        "Operating Budget. The budget includes $4,677,100 and 38.4 FTE "
        "Positions in FY 2025 for the operating budget. These amounts "
        "consist of: General Fund $342,500. State Treasurer's Operating "
        "Fund $4,334,600."
    )
    chunk_id = put_chunk(chunk_text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": "$6,000,000 one-time for secure ballot paper",
                "confidence": "paraphrase",
            },
        )

    body = resp.json()
    assert body["ok"] is True, body


def test_cite_validate_verbatim_substring_passes(put_chunk):
    """Verbatim happy path: claim is a substring of cited text after
    normalize."""
    chunk_text = "The Baseline includes $4,677,100 in FY 2026."
    chunk_id = put_chunk(chunk_text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": "Baseline includes $4,677,100",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is True


def test_cite_validate_span_too_broad_rejected(put_chunk):
    """A span longer than SPAN_BREADTH_LIMIT chars is rejected before
    the alignment check, even if the claim happens to be in there.
    This pushes the model toward focused citations and produces
    usable PDF highlights."""
    chunk_text = "Operating Budget content. " + ("x " * 2000) + "Tail content."
    chunk_id = put_chunk(chunk_text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": "Operating Budget",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is False
    assert "too broad" in body["error"]
    # Preview still attached so the model sees what to narrow from.
    assert body["cited_text_preview"].startswith("Operating Budget")


def test_cite_validate_no_claim_span_skips_alignment_check(put_chunk):
    """Back-compat: when claim_span and confidence are omitted (older
    MCP servers or test harnesses), only the chunk_id + bounds check
    runs. Validates that the new fields are truly optional."""
    chunk_text = "Some unrelated text content."
    chunk_id = put_chunk(chunk_text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
            },
        )

    body = resp.json()
    assert body["ok"] is True


# ---------------------------------------------------------------------------
# AFR currency-only alignment + auto-clamp + doc_type dispatch
# (2026-05-12 audit-driven changes)
# ---------------------------------------------------------------------------


def test_afr_alignment_passes_when_dollar_amounts_match(put_chunk):
    """The 2026-05-12 audit's #18 case: model writes English prose
    ('Corrections started FY 2025 with $75,000,000 balance, received
    $40,000,000...') against a raw AFR table row ('FUND TOTAL
    75,000,000.00 40,000,000.00 99,360,968.11 15,639,031.89').
    Normal paraphrase overlap was 0.06 because the English words
    ('started', 'received') aren't in the table."""
    chunk_text = (
        "2573-CONSUMER RESTITUTION AND REMEDIATION REVOLVING FUND | "
        "DCA DC2573 APPROPRIATED ACTIVITY 40,000,000.00 - | "
        "DCA DC2573 OPIOID REMEDIATION - 99,360,968.11 | "
        "FUND TOTAL 75,000,000.00 40,000,000.00 99,360,968.11 15,639,031.89"
    )
    chunk_id = put_chunk(chunk_text, doc_type="afr")
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": (
                    "The Corrections (DCA) side of fund 2573 started FY 2025 "
                    "with a $75,000,000 balance, received $40,000,000 in "
                    "revenues, spent $99,360,968.11, ended FY 2025 at "
                    "$15,639,031.89."
                ),
                "confidence": "paraphrase",
            },
        )
    body = resp.json()
    assert body["ok"] is True, body


def test_afr_alignment_no_longer_rejects_wrong_dollar_amounts(put_chunk):
    """Regression / contract: as of 2026-05-20, /cite/validate dropped
    its content-overlap alignment check (including the AFR-specific
    dollar-amount variant). A claim with dollar amounts that don't
    appear in the cited AFR span — e.g. claim says `$75,000,000` but
    chunk has only `3,000,000.00 / 2,313,971.39` — now returns ok:true.
    The trade-off is accepted because the check was a string-overlap
    heuristic, not real faithfulness validation (WS3 is that), and the
    false-rejection rate it produced was hurting dogfood badly. See
    the http_cite_validate comment block for the full rationale."""
    chunk_text = (
        "MAA MA2573 MA OPIOID REMEDIATION 3,000,000.00 2,313,971.39 | "
        "FUND TOTAL 3,000,000.00 2,313,971.39 686,028.61"
    )
    chunk_id = put_chunk(chunk_text, doc_type="afr")
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": (
                    "The ADC side: started with $75,000,000, ended at "
                    "$15,639,031.89."
                ),
                "confidence": "paraphrase",
            },
        )
    body = resp.json()
    assert body["ok"] is True, body


def test_afr_alignment_ignores_year_and_small_numbers(put_chunk):
    """Years (2025) and small fractional numbers (38.4 FTE) appear
    in claims but aren't load-bearing data. The AFR check only
    matches numbers with ≥4 integer digits to skip them."""
    chunk_text = "FUND TOTAL 75,000,000.00 40,000,000.00 99,360,968.11"
    chunk_id = put_chunk(chunk_text, doc_type="afr")
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": (
                    "In FY 2025, the fund opened with $75,000,000 and "
                    "received $40,000,000 (38.4 FTE)."
                ),
                "confidence": "paraphrase",
            },
        )
    body = resp.json()
    assert body["ok"] is True


def test_span_end_auto_clamp_small_overflow(put_chunk):
    """Audit #10: span_end=1850 on a 1832-char chunk (off by 18).
    The model picked a rounded value past the end; clamping to length
    and proceeding catches the model's intent without forcing a
    wasted retry. Threshold is max(50 chars, 5% of length) — 30 is
    well inside that, so this clamps."""
    chunk_text = "x" * 100  # short chunk; 5% = 5, abs cap = 50; effective = 50
    chunk_id = put_chunk(chunk_text)
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": 130,  # 30 over, within abs cap of 50
                "claim_span": "x",
                "confidence": "verbatim",
            },
        )
    body = resp.json()
    assert body["ok"] is True


def test_span_end_clamp_rejects_large_overflow(put_chunk):
    """A 200-char overflow on a 100-char chunk is genuinely wrong;
    the validator still rejects so the model self-corrects.
    Boundary: max(50, 5% × 100) = 50. 200 > 50 → reject."""
    chunk_id = put_chunk("x" * 100)
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": 300,
                "claim_span": "x",
                "confidence": "verbatim",
            },
        )
    body = resp.json()
    assert body["ok"] is False
    assert body["error"] == "span out of range"
    assert body["chunk_text_length"] == 100


def test_verbatim_threshold_lowered_to_070(put_chunk):
    """The 2026-05-12 audit's #15/#16 cases: verbatim cites where the
    claim is MOSTLY in the cited span (82%, 68%) but the trailing
    few words spill past span_end. With 0.85 threshold they failed;
    with 0.70 they pass."""
    chunk_text = (
        "Operating Budget includes amounts Treasurer General Fund balance "
        "appropriation summary."
    )
    claim = (
        "Operating Budget includes amounts Treasurer General Fund — "
        "expanded discussion follows."  # 'expanded' 'discussion' 'follows' missing
    )
    chunk_id = put_chunk(chunk_text)
    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": len(chunk_text),
                "claim_span": claim,
                "confidence": "verbatim",
            },
        )
    body = resp.json()
    assert body["ok"] is True, body


# ---------------------------------------------------------------------------
# Quote-based cites (server derives the offsets)
# ---------------------------------------------------------------------------


def test_cite_validate_accepts_quote_and_derives_offsets(put_chunk):
    """Quote-based cite: the server scans chunk.text for the quoted
    substring and derives span_start/span_end. The validation then
    proceeds the same way as if the caller had passed offsets directly.
    """
    text = (
        "The Aviation Fund began FY 2025 with a balance of $123,456 and "
        "ended the year at $98,765 after transfers."
    )
    chunk_id = put_chunk(text)
    quote = text[20:60]

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "quote": quote,
                "claim_span": quote,  # verbatim — the claim IS the quote
                "confidence": "verbatim",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True, body
    # The sidecar echoes back the derived offsets so the UI can attach
    # the bbox highlight at the right position.
    assert body["resolved_span_start"] == 20
    assert body["resolved_span_end"] == 60


def test_cite_validate_quote_not_found_returns_error(put_chunk):
    chunk_id = put_chunk("A perfectly ordinary chunk of budget text.")

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "quote": "definitely-not-in-this-chunk-XYZ-12345",
                "claim_span": "x",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is False
    assert "quote not found" in body["error"].lower()


def test_cite_validate_rejects_duplicate_quote(put_chunk):
    """When the cited quote appears multiple times in chunk.text the
    sidecar bounces the cite back with positions, so the model picks a
    longer (unique) quote. Otherwise we silently bind to the first
    occurrence and the PDF highlight lands on the wrong dollar amount.
    """
    chunk_id = put_chunk(
        "Item A: $5,000,000 in FY 2025. Item B: $5,000,000 in FY 2026."
    )

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "quote": "$5,000,000",
                "claim_span": "$5,000,000 in FY 2025",
                "confidence": "verbatim",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "multiple times" in body["error"]
    # Both occurrence positions surfaced for the model.
    assert "positions:" in body["error"]


def test_cite_validate_unique_quote_still_validates(put_chunk):
    """Regression — a quote appearing exactly once is not rejected by
    the duplicate check."""
    chunk_id = put_chunk(
        "The Aviation Fund balance was $123,456 as of June 30, 2024."
    )

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "quote": "$123,456",
                "claim_span": "$123,456",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is True, body


def test_cite_validate_duplicate_quote_caps_positions_at_3(put_chunk):
    """A degenerate quote that appears many times surfaces up to 3
    positions then '…' — keeps the error string readable."""
    chunk_id = put_chunk("$X here $X there $X again $X once more $X last")

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "quote": "$X",
                "claim_span": "$X here",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is False
    err = body["error"]
    # Three positions then ellipsis (more occurrences than we list).
    assert "positions:" in err
    assert "…" in err
    # Count commas inside the parenthesized positions list: 3 numbers
    # joined by ", " plus one ", …" tail = 3 commas inside the parens.
    inside = err.split("(", 1)[1].split(")", 1)[0]
    assert inside.count(",") == 3, inside


def test_cite_validate_soft_clamps_claim_span_over_500(put_chunk):
    """Past sessions had 7 cite calls rejected at the 500-char boundary.
    The sidecar should now truncate (and flag truncated:true) rather than
    reject."""
    text = "The Baseline includes $4,677,100 and 38.4 FTE Positions in FY 2025."
    chunk_id = put_chunk(text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "quote": text[:30],
                # A 750-char claim_span — schema allows it; server
                # soft-clamps to 500.
                "claim_span": "x" * 750,
                "confidence": "paraphrase",
            },
        )

    body = resp.json()
    assert body.get("truncated") is True


def test_cite_validate_offsets_win_when_both_passed(put_chunk):
    """Back-compat: if a caller sends both offsets AND quote, offsets win
    and the quote field is ignored."""
    text = (
        "The Aviation Fund began FY 2025 with a balance of $123,456 and "
        "ended the year at $98,765 after transfers."
    )
    chunk_id = put_chunk(text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": chunk_id,
                "span_start": 0,
                "span_end": 40,
                # An obviously-wrong quote — if the server used the
                # quote path, this would fail "quote not found". The
                # test passes only if offsets win.
                "quote": "definitely-not-in-the-chunk-quote-XYZ",
                "claim_span": text[:40],
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is True, body
    assert "quote not found" not in (body.get("error") or "").lower()


# ---------------------------------------------------------------------------
# /cite/validate_batch — 2026-05-20 cite-batch addition
# ---------------------------------------------------------------------------
# Batch endpoint that validates N cites in one round-trip, with a single
# bulk store fetch for all unique chunks. Result order matches input order;
# entries are independent (one bad cite does NOT poison the batch).


def test_cite_validate_batch_happy_path_all_ok(put_chunk):
    """Two valid cites against the same stored chunk → both ok:true."""
    text = (
        "The Aviation Fund began FY 2025 with a balance of $123,456 and "
        "ended the year at $98,765 after transfers to the General Fund."
    )
    chunk_id = put_chunk(text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate_batch",
            json={
                "citations": [
                    {
                        "chunk_id": chunk_id,
                        "quote": text[10:30],
                        "claim_span": text[10:30],
                        "confidence": "verbatim",
                    },
                    {
                        "chunk_id": chunk_id,
                        "quote": text[50:80],
                        "claim_span": text[50:80],
                        "confidence": "verbatim",
                    },
                ]
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert len(body["citations"]) == 2
    assert body["citations"][0]["ok"] is True
    assert body["citations"][1]["ok"] is True
    # Order preserved: derived offsets should match the input quote
    # positions.
    assert body["citations"][0]["resolved_span_start"] == 10
    assert body["citations"][1]["resolved_span_start"] == 50


def test_cite_validate_batch_mixed_ok_and_fail_preserves_order(put_chunk):
    """A batch with one valid cite, one with unknown chunk_id, and one
    with a quote-not-in-chunk returns three responses in the same order.
    A bad cite in the middle must not poison the others."""
    text = (
        "The Aviation Fund began FY 2025 with a balance of $123,456 and "
        "ended the year at $98,765 after transfers to the General Fund."
    )
    chunk_id = put_chunk(text)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate_batch",
            json={
                "citations": [
                    {
                        "chunk_id": chunk_id,
                        "quote": text[10:30],
                        "claim_span": text[10:30],
                        "confidence": "verbatim",
                    },
                    {
                        # Invented chunk_id — should return unknown
                        "chunk_id": "definitely-not-a-real-chunk-XYZ",
                        "quote": "anything",
                        "claim_span": "anything",
                        "confidence": "verbatim",
                    },
                    {
                        "chunk_id": chunk_id,
                        # Invented quote — should return quote-not-found
                        "quote": "definitely-not-in-this-chunk-XYZ-99999",
                        "claim_span": "x",
                        "confidence": "verbatim",
                    },
                ]
            },
        )

    body = resp.json()
    cites = body["citations"]
    assert len(cites) == 3
    assert cites[0]["ok"] is True
    assert cites[1]["ok"] is False
    assert cites[1]["error"] == "unknown chunk_id"
    assert cites[2]["ok"] is False
    assert "quote not found" in cites[2]["error"].lower()


def test_cite_validate_batch_empty_input_returns_empty_response():
    """Empty `citations` array is allowed — returns empty array,
    not a 4xx. The model may legitimately call cite_batch with zero
    items if it changed its mind during answer composition."""
    with TestClient(app) as client:
        resp = client.post("/cite/validate_batch", json={"citations": []})
    assert resp.status_code == 200
    assert resp.json() == {"citations": []}


def test_cite_validate_batch_single_store_fetch_for_repeated_chunk_ids(
    monkeypatch, put_chunk
):
    """The whole point of the batch endpoint is to avoid N round-trips for
    N cites. When the model emits 5 cites against the SAME chunk_id (common:
    multiple facts from one budget table), the bulk fetch must be ONE
    get_by_ids call asking for ONE id — the store read is a network hop on
    the office share, so a per-cite fetch is 5 of them."""
    chunk_text = "Some chunk text with $1,000 mentioned twice $1,000."
    chunk_id = put_chunk(chunk_text)
    calls: list[list[str]] = []

    real_store = api_module._store()

    class CountingStore:
        """Delegates everything to the real store, recording get_by_ids."""

        def __getattr__(self, name):
            return getattr(real_store, name)

        def get_by_ids(self, corpus, ids):
            calls.append(list(ids))
            return real_store.get_by_ids(corpus, ids)

    monkeypatch.setattr(api_module, "_store", CountingStore)

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate_batch",
            json={
                "citations": [
                    {"chunk_id": chunk_id, "quote": "Some chunk", "claim_span": "x", "confidence": "verbatim"},
                    {"chunk_id": chunk_id, "quote": "twice", "claim_span": "y", "confidence": "verbatim"},
                    {"chunk_id": chunk_id, "quote": "text", "claim_span": "z", "confidence": "verbatim"},
                    {"chunk_id": chunk_id, "quote": "mentioned", "claim_span": "w", "confidence": "verbatim"},
                    {"chunk_id": chunk_id, "quote": "$1,000", "claim_span": "v", "confidence": "verbatim"},
                ]
            },
        )

    body = resp.json()
    assert len(body["citations"]) == 5
    assert calls == [[chunk_id]], calls


# ---------------------------------------------------------------------------
# Unit tests — intent → top_k resolution (Task 10, 2026-05-20)
# ---------------------------------------------------------------------------
# The dogfood-hardening plan introduces an optional `intent` field on the
# /retrieve body. The sidecar maps it to top_k via the _INTENT_TOP_K table
# (lookup→5, compare→12, analyze→18) when the caller hasn't passed an
# explicit top_k. Explicit top_k always wins; absent intent + absent
# top_k falls back to DEFAULT_PIPELINE_TOP_K. The intent value is echoed
# on the response so the audit-log writer (WS5) picks it up.


def test_retrieve_intent_lookup_uses_top_k_5(monkeypatch):
    captured: dict = {}

    def fake_retrieve(req):
        captured["top_k"] = req.top_k
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        resp = client.post("/retrieve", json={"query": "x", "intent": "lookup"})

    assert resp.status_code == 200
    assert captured["top_k"] == 5
    # Audit-log fields surface intent in the response so the writer (WS5)
    # picks it up.
    assert resp.json()["intent"] == "lookup"


def test_retrieve_intent_analyze_uses_top_k_18(monkeypatch):
    # Lowered from 25 → 18 on 2026-05-20: 25 produced ~50K-char
    # responses that hit Claude Code's spillover threshold, adding a
    # Read round-trip and 5-10s of latency to every analyze query.
    captured: dict = {}

    def fake_retrieve(req):
        captured["top_k"] = req.top_k
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        client.post("/retrieve", json={"query": "x", "intent": "analyze"})
    assert captured["top_k"] == 18


def test_retrieve_explicit_top_k_wins_over_intent(monkeypatch):
    captured: dict = {}

    def fake_retrieve(req):
        captured["top_k"] = req.top_k
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        client.post("/retrieve", json={"query": "x", "intent": "lookup", "top_k": 30})
    assert captured["top_k"] == 30


def test_retrieve_without_intent_uses_default_top_k(monkeypatch):
    captured: dict = {}

    def fake_retrieve(req):
        captured["top_k"] = req.top_k
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        client.post("/retrieve", json={"query": "x"})
    # No intent, no top_k → falls through to DEFAULT_PIPELINE_TOP_K
    # (assert against the constant rather than the literal so this test
    # moves with future tuning).
    from retrieval.pipeline import DEFAULT_PIPELINE_TOP_K

    assert captured["top_k"] == DEFAULT_PIPELINE_TOP_K


# ---------------------------------------------------------------------------
# Startup preflight + warmup
# ---------------------------------------------------------------------------
# The preflight no longer checks VOYAGE_API_KEY / DATABASE_URL (neither
# exists after Plan 1). It checks the two things that can actually be wrong
# now: the shared data folder is usable, and the corpus has chunks in it.
#
# These call the lifespan async-context-manager directly rather than via
# TestClient because Starlette + anyio wrap SystemExit raised inside
# lifespan into a BaseExceptionGroup, which makes pytest.raises(SystemExit)
# on the TestClient context messier than necessary.


def _enter_lifespan():
    import asyncio

    async def _run():
        async with api_module.lifespan(app):
            pass

    asyncio.run(_run())


def test_lifespan_preflight_exits_when_the_corpus_is_empty(tmp_path, monkeypatch):
    """A data directory with no chunks in it is the "fresh machine, forgot
    to copy the lancedb folder" case. Fail fast at startup instead of
    answering every query with nothing."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "empty"))
    reset_default_collaborators()
    with pytest.raises(SystemExit):
        _enter_lifespan()


def test_lifespan_preflight_exits_when_the_data_dir_is_unusable(monkeypatch):
    """Second preflight check: the shared folder itself. On the office
    share this is the "VPN is down / permissions changed" case, and it must
    name the real OS error rather than guess."""

    def _boom() -> None:
        raise OSError("Access is denied: \\\\JLBC-share\\jlbc-insight-data")

    monkeypatch.setattr(api_module, "data_dir", _boom)
    with pytest.raises(SystemExit):
        _enter_lifespan()


def test_lifespan_preflight_passes_and_warms_the_retrieval_path(monkeypatch):
    """Happy path: the corpus is there, so startup completes AND runs one
    throwaway query so the first real request doesn't pay the model-load
    cost inside the MCP bridge's 15s timeout."""
    warmups: list[str] = []

    def fake_retrieve(req):
        warmups.append(req.query)
        return RetrievalResult()

    monkeypatch.setattr(api_module, "retrieve", fake_retrieve)

    with TestClient(app) as client:
        assert client.get("/health").json()["status"] == "ok"
    assert len(warmups) == 1, warmups


def test_warmup_failure_does_not_block_startup(monkeypatch):
    """Best-effort by design: a warmup that raises (corrupt index, a model
    file half-copied) logs and continues, because the lazy path still
    builds everything on the first real request. Blocking startup here
    would turn a slow first query into a dead sidecar."""

    def exploding_retrieve(req):
        raise RuntimeError("simulated warmup failure")

    monkeypatch.setattr(api_module, "retrieve", exploding_retrieve)

    with TestClient(app) as client:
        resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"
