"""FastAPI sidecar exposing the Phase 1b retrieval pipeline over HTTP.

Phase 1c WS1 + WS6. The Node MCP server (`mcp-server/`) calls this from
its `retrieve` tool handler — keeping the per-call latency low (no
Python cold-start per request) while letting the MCP server stay free
of Postgres / Voyage SDK concerns.

Three endpoints:

* `GET /health` — liveness probe used by the dev script + MCP server
  startup check.
* `POST /retrieve` — runs the full BM25 + dense + RRF + Voyage rerank
  pipeline (`retrieval.pipeline.retrieve`) and returns the schema-doc
  shape from `docs/superpowers/decisions/2026-05-06-citation-tool-schema.md`
  (chunks, top_score, retrieval_id, plus per-stage diagnostics for the
  audit log).
* `POST /cite/validate` — confirms a chunk_id exists and the offset
  span is within `chunk.text`'s length. Catches hallucinated chunk_ids
  and out-of-range spans server-side so the model sees the error in
  the tool result and can self-correct.

Run with:

    uvicorn retrieval.api:app --host localhost --port 9200

Env:
    DATABASE_URL — required (db/.env.example).
    VOYAGE_API_KEY — required for the embedder + reranker.
    BUDGET_RETRIEVAL_PORT — informational only (uvicorn arg).
"""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field

from db.connection import get_connection
from db.embeddings import VoyageEmbedder
from retrieval.pipeline import RetrievalRequest, retrieve

# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class RetrieveFiltersBody(BaseModel):
    """Optional filters narrowing the retrieval; matches RetrievalFilters
    1:1 except `fund_mentions` is omitted (the MCP `retrieve` tool's
    public schema doesn't expose it — we keep it on RetrievalFilters
    for the eval harness only)."""

    fiscal_year: list[int] | None = None
    doc_type: list[str] | None = None
    publisher: list[str] | None = None
    agency_canonical_id: list[str] | None = None
    fund_canonical_id: list[str] | None = None
    is_table: bool | None = None


class RetrieveRequestBody(BaseModel):
    query: str
    filters: RetrieveFiltersBody | None = None
    top_k: int = 20


class ChunkOut(BaseModel):
    """Per-chunk output shape locked in citation-tool-schema.md.

    `page_start` / `page_end` are equal in v1 (chunks are single-page
    today; multi-page reassembly is deferred — see decisions D2 +
    open-items in the architecture doc). `doc_title` is denormalized
    here from the documents table rather than being threaded through
    RetrievedChunk, keeping retrieval-module concerns separate from
    schema-marshaling concerns.
    """

    chunk_id: str
    doc_id: str
    doc_title: str
    publisher: str
    fiscal_year: int | None
    doc_type: str
    section_path: list[str]
    page_start: int | None
    page_end: int | None
    text: str
    score: float


class RetrieveResponse(BaseModel):
    chunks: list[ChunkOut]
    top_score: float
    retrieval_id: str = Field(
        ...,
        description=(
            "Server-generated UUID for this retrieval call. The Phase 1c "
            "audit log writer (WS5) correlates retrieve() and cite() rows "
            "by this id."
        ),
    )
    bm25_count: int
    dense_count: int
    fused_count: int


class CiteValidateBody(BaseModel):
    chunk_id: str
    span_start: int
    span_end: int


class CiteValidateResponse(BaseModel):
    ok: bool
    error: str | None = None
    chunk_text_length: int | None = None


# ---------------------------------------------------------------------------
# App + embedder cache
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Embedder is constructed lazily on the first /retrieve call (see
    # `_get_embedder` below) so unit tests can monkey-patch retrieve()
    # without needing a Voyage API key. The first production request
    # pays a one-time SDK-init cost (~tens of ms); subsequent calls
    # reuse the cached client on app.state.
    app.state.embedder = None
    yield


app = FastAPI(
    title="Ask the Budget AZ — retrieval sidecar",
    version="0.1.0",
    lifespan=lifespan,
)


def _get_embedder() -> VoyageEmbedder:
    """Return the cached VoyageEmbedder, constructing on first use.

    Raises RuntimeError if VOYAGE_API_KEY is unset — fails the request
    cleanly rather than allowing a downstream NoneType error inside
    `retrieve()`.
    """
    if app.state.embedder is None:
        app.state.embedder = VoyageEmbedder()
    return app.state.embedder


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness probe. The dev script polls this before launching the
    MCP server so the first `retrieve` call doesn't race with startup.
    """
    return {
        "status": "ok",
        "version": app.version,
        "voyage_key_present": bool(os.environ.get("VOYAGE_API_KEY")),
    }


def _lookup_doc_titles(doc_ids: list[str]) -> dict[str, str]:
    """Fetch doc_title for every doc_id in one query. Empty input returns {}."""
    if not doc_ids:
        return {}
    with get_connection() as conn:
        rows = conn.execute(
            "SELECT doc_id, title FROM documents WHERE doc_id = ANY(%s)",
            [doc_ids],
        ).fetchall()
    # rows are dict_row factory → {"doc_id": ..., "title": ...}
    return {r["doc_id"]: r["title"] for r in rows}


@app.post("/retrieve")
def http_retrieve(body: RetrieveRequestBody) -> RetrieveResponse:
    """Run the hybrid retrieval pipeline and shape the response per
    citation-tool-schema.md. The Node MCP server forwards the JSON
    body verbatim to Claude (in a `text` content block), so the
    field names + types here are the *visible* contract to the model.
    """
    f = body.filters or RetrieveFiltersBody()
    req = RetrievalRequest(
        query=body.query,
        fiscal_year=f.fiscal_year,
        doc_type=f.doc_type,
        publisher=f.publisher,
        agency_canonical_id=f.agency_canonical_id,
        fund_canonical_id=f.fund_canonical_id,
        is_table=f.is_table,
        top_k=body.top_k,
    )
    result = retrieve(req, embedder=_get_embedder())

    # Denormalize doc_title from the documents table. Done at the
    # sidecar boundary (rather than inside the retrieval pipeline) so
    # the retrieval module stays focused on retrieval — schema-shape
    # concerns belong to the layer that owns the schema.
    doc_titles = _lookup_doc_titles(list({c.doc_id for c in result.chunks}))

    return RetrieveResponse(
        chunks=[
            ChunkOut(
                chunk_id=c.chunk_id,
                doc_id=c.doc_id,
                doc_title=doc_titles.get(c.doc_id, ""),
                publisher=c.publisher,
                fiscal_year=c.fiscal_year,
                doc_type=c.doc_type,
                section_path=c.section_path,
                page_start=c.page,
                page_end=c.page,
                text=c.text,
                score=c.score,
            )
            for c in result.chunks
        ],
        top_score=result.top_score,
        retrieval_id=str(uuid4()),
        bm25_count=result.bm25_count,
        dense_count=result.dense_count,
        fused_count=result.fused_count,
    )


@app.post("/cite/validate", response_model_exclude_none=True)
def http_cite_validate(body: CiteValidateBody) -> CiteValidateResponse:
    """Confirm a chunk_id exists and the (span_start, span_end) range
    is within `chunk.text`'s length. Two failure modes returned with
    `ok: false`:

      * `unknown chunk_id` — chunk_id wasn't found.
      * `span out of range` — chunk exists but the span doesn't fit.
        `chunk_text_length` accompanies this so the model can see the
        actual bound and self-correct.
    """
    with get_connection() as conn:
        row = conn.execute(
            "SELECT length(text) AS len FROM chunks WHERE chunk_id = %s",
            [body.chunk_id],
        ).fetchone()

    if row is None:
        return CiteValidateResponse(ok=False, error="unknown chunk_id")

    length = int(row["len"])
    if (
        body.span_start < 0
        or body.span_end <= body.span_start
        or body.span_end > length
    ):
        return CiteValidateResponse(
            ok=False,
            error="span out of range",
            chunk_text_length=length,
        )

    return CiteValidateResponse(ok=True, chunk_text_length=length)
