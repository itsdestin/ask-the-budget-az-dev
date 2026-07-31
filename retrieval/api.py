"""FastAPI sidecar exposing the retrieval pipeline over HTTP.

The Node MCP server (`mcp-server/`) calls this from its `retrieve` tool
handler — keeping the per-call latency low (no Python cold-start per
request) while letting the MCP server stay free of storage and
embedding-model concerns.

Plan 1 (2026-07-29) took Postgres and Voyage out from under this file:
storage is now an embedded LanceDB directory (`store.chunk_store`) and
the embedder + reranker are local ONNX models owned by
`retrieval.pipeline`'s process-wide singletons. Endpoint paths and
response fields are unchanged apart from three noted places:

* `/health` reports the corpus (`corpus_chunks`, `documents_metadata`,
  `data_dir`) instead of a Voyage key, and answers 503 + `status:
  "degraded"` with the real error text when the corpus is unreachable.
* `top_score` uses the no-results sentinel
  (`retrieval.pipeline.NO_RESULTS_TOP_SCORE`) instead of 0.0.
* `/docs/{doc_id}`'s document-level fields (title, source_format,
  source_blob_path, source_url, page_count) come from the documents.json
  sidecar rather than a Postgres table. Present whenever that file is —
  the normal case — and omitted when a corpus was copied without it,
  which `/health`'s `documents_metadata: 0` names. `page_count` is null
  either way; the ingest never populated it.

Endpoints:

* `GET /health` — liveness probe used by the dev script, the MCP server
  startup check, and the web app's session-start banner.
* `POST /retrieve` — runs the full BM25 + dense + RRF + local rerank
  pipeline (`retrieval.pipeline.retrieve`) and returns the schema-doc
  shape from `docs/superpowers/decisions/2026-05-06-citation-tool-schema.md`
  (chunks, top_score, retrieval_id, plus per-stage diagnostics for the
  audit log).
* `POST /cite/validate` + `/cite/validate_batch` — confirm a chunk_id
  exists and the offset span is within `chunk.text`'s length. Catches
  hallucinated chunk_ids and out-of-range spans server-side so the model
  sees the error in the tool result and can self-correct. The logic
  itself moved to `retrieval.citations` on 2026-07-30 (Plan 4) so the
  in-process tool loop can call it directly and against either corpus;
  these routes are now thin wrappers over that module.
* `GET /docs/{doc_id}` — per-document metadata.
* `POST /list_values` — which canonical_ids actually exist in the corpus.

Run with:

    uvicorn retrieval.api:app --host 127.0.0.1 --port 9200

Env:
    JLBC_DATA_DIR — optional; the shared-data folder holding `lancedb/`.
      Unset falls back to `data/insight-data` inside the repo.
    BUDGET_RETRIEVAL_PORT — informational only (uvicorn arg).
"""
from __future__ import annotations

# Load .env.local on import so subsequent os.environ reads (JLBC_DATA_DIR)
# work whether or not the user remembered to `set -a; source .env.local;
# set +a` (bash) / `Get-Content .env.local | ...` (pwsh). Done at import
# time (not inside lifespan) so it's already in effect by the time
# store.config resolves the data directory.
from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv()  # fallback to .env if .env.local missing

import json
import sys
import threading
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from retrieval import pipeline
# Cite validation lives in retrieval.citations so the Plan 4 in-process
# tool loop can call it without importing this module (which builds a
# FastAPI app at import time) and so it can target either corpus. The
# request/response models are defined there too and re-exported here —
# this module's endpoints are one of two front ends over the same logic,
# not its owner. See that module's docstring for the fetch-vs-pure split.
from retrieval.citations import (
    CiteValidateBody,
    CiteValidateResponse,
    validate_cite,
    validate_cites,
)
from retrieval.pipeline import DEFAULT_CORPUS, RetrievalRequest, retrieve
from store.chunk_store import ChunkStore, sql_str
from store.config import data_dir, documents_path

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
    # top_k is optional now: an explicit value overrides the intent's
    # default; absent + intent set → server picks top_k from the
    # _INTENT_TOP_K table; absent + no intent → server uses
    # DEFAULT_PIPELINE_TOP_K (15).
    #
    # ge=1 because a top_k of 0 or negative used to travel all the way to
    # the reranker and surface as an opaque 500. A 422 naming `top_k` tells
    # the caller what it did wrong.
    top_k: int | None = Field(default=None, ge=1)
    # Route classifier. Tunes top_k server-side and is echoed in the
    # response so the (future) audit log writer can record it.
    intent: str | None = None


class ChunkOut(BaseModel):
    """Per-chunk output shape locked in citation-tool-schema.md.

    `page_start` / `page_end` are equal in v1 (chunks are single-page
    today; multi-page reassembly is deferred — see decisions D2 +
    open-items in the architecture doc). `doc_title` is denormalized
    here from the documents table rather than being threaded through
    RetrievedChunk, keeping retrieval-module concerns separate from
    schema-marshaling concerns.

    `bbox` is the chunk's PDF rectangle in PDF points, shape
    [x1, y1, x2, y2] (single rect for v1 — multi-rect chunks are
    flattened upstream and unsupported by the viewer until Phase 2).
    Null for non-PDF chunks (e.g. DOCX bills). Phase 1c WS4c added
    the field so the PdfViewer can paint a precise bbox highlight
    on chip-click; pre-WS4c clients ignore it harmlessly.
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
    bbox: list[float] | None = None
    text: str
    # Surface the chunk text length so the model can pick span_end
    # without counting characters in `text` itself. Added 2026-05-12
    # after the audit showed span-out-of-range failures with overflows
    # ranging from off-by-1 to off-by-200; the model was reaching for
    # rounded values (1500, 2000) instead of measuring. Auto-clamp
    # in /cite/validate covers small overflows; this field prevents
    # the larger guess-and-fail loop entirely for the model that
    # bothers to read it.
    text_length: int
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
    # Echo of the caller's intent (None when not provided). Surfaced
    # here so the audit-log writer picks it up without re-parsing the
    # request body.
    intent: str | None = None


class DocMetadataResponse(BaseModel):
    """Metadata about an ingested document. Returned by GET /docs/{doc_id}.

    Field names are unchanged from the Postgres version, but four of them
    are now optional: `source_format`, `source_blob_path`, `page_count`,
    `source_url`. They live in the documents.json sidecar (see
    _document_metadata) rather than in the chunk table, so they are present
    whenever that file is — which is the normal case — and omitted
    (`response_model_exclude_none=True`) when a corpus was copied without
    it. `page_count` is null even in the sidecar: the ingest pipeline never
    populated that column.

    Omission rather than invention is deliberate: a fabricated path would
    make the Next.js `/api/pdf/[doc_id]` route fail with
    "source_blob_missing <fabricated path>", sending the next person
    hunting for a file that was never there.
    """

    doc_id: str
    title: str
    publisher: str
    doc_type: str
    # Nullable in the chunk schema, so nullable here — a document ingested
    # without a fiscal year must not 500 the endpoint.
    fiscal_year: int | None = None
    source_format: str | None = None
    source_blob_path: str | None = None
    page_count: int | None = None
    source_url: str | None = None


# CiteValidateBody / CiteValidateResponse are imported from
# retrieval.citations (see the import block's note). The two batch
# wrappers below stay here because they are pure HTTP framing — the
# function-level API takes and returns plain lists.


class CiteValidateBatchBody(BaseModel):
    """Wrap N CiteValidateBody calls in a single HTTP request. The
    sidecar bulk-fetches all unique chunks in one store read and
    validates each cite in-memory — the wall-clock win over N
    sequential /cite/validate calls is both the model-side round-trip
    elimination (1 LLM turn instead of N) and the server-side read
    elimination (1 store read instead of N). See cite_batch tool docstring
    in mcp-server/src/tools/cite-batch.ts for the design rationale."""
    citations: list[CiteValidateBody]


class CiteValidateBatchResponse(BaseModel):
    """Per-citation responses in the same order as the input array.
    Length always equals input length; entries are independent (one
    bad cite does NOT poison the batch). The MCP-side cite_batch tool
    re-pairs these with the model's tool_use args by index."""
    citations: list[CiteValidateResponse]


class FilterValueOut(BaseModel):
    """One row in the list_values response — a canonical slug, how many
    chunks (or documents) it appears on, and a sample document title so
    the model can recognize what the slug is referring to without an
    out-of-band lookup. AHCCCS being keyed under `agency:axs` is the
    canonical example: `axs` alone tells the model nothing, but
    `axs (351 chunks) — sample: "JLBC Baseline FY2027 — AHCCCS"` is
    self-documenting.
    """

    canonical_id: str
    chunk_count: int
    sample_doc_title: str | None = None


class ListValuesBody(BaseModel):
    """Discovery request. `field` selects which catalog to enumerate;
    response is sorted by chunk_count desc so the most-used values come
    first (truncating clients can keep the head and drop the long tail
    of one-off/typo'd canonical_ids that crept in during ingest)."""

    field: str = Field(
        ...,
        description=(
            "One of: 'agency', 'doc_type', 'publisher', 'fund'. "
            "Returns the canonical_ids actually present in the corpus."
        ),
    )


class ListValuesResponse(BaseModel):
    field: str
    values: list[FilterValueOut]


# ---------------------------------------------------------------------------
# Retrieval tuning constants
# ---------------------------------------------------------------------------

# Intent → default top_k. Picked from the dogfood-hardening plan
# (2026-05-20): tight for lookup (analyst wants one number), broader
# for analyze (analyst wants context).
#
# analyze lowered 25 → 18 on 2026-05-20 because the original 25 was
# producing ~50K-char retrieve responses that hit Claude Code's
# spillover threshold (Read of a tool-results .txt file, +5-10s of
# round-trip latency). 18 still gives broader context than compare's
# 12 but stays under the spillover line. Combined with the route-
# classifier prompt update that biases "Show me X" toward Lookup,
# most dogfood queries no longer hit the analyze path at all.
_INTENT_TOP_K: dict[str, int] = {
    "lookup": 5,
    "compare": 12,
    "analyze": 18,
}


# ---------------------------------------------------------------------------
# App + shared store
# ---------------------------------------------------------------------------


def _store() -> ChunkStore:
    """The process-wide ChunkStore — the SAME object `retrieve()` searches.

    WHY not build one here: a second ChunkStore would open a second set of
    LanceDB table handles for the same files (each one a round trip on the
    office share), and the same mistake applied to the models would put a
    second copy of the ONNX weights in memory. One owner for the whole
    process, which is `retrieval.pipeline`.

    `_get_store` is underscore-private *within the retrieval package*, not
    across a real boundary — api.py is that package's own HTTP front end,
    and the pipeline exposes `reset_default_collaborators()` publicly as
    the matching reset hook. Wrapping it in this one-line function keeps
    every call site (and the tests' spy seam) in one place.
    """
    return pipeline._get_store()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Preflight: validate the environment before the sidecar accepts
    # requests. Two checks now that there is no database and no API key —
    # fail fast on either, with a message that names the real problem.
    #
    # 1. The shared data folder resolves and is writable. Writable, not just
    #    readable, because that folder holds every piece of shared state —
    #    the LanceDB tables, the ingest lock, settings — so a dead VPN or a
    #    permissions change on the office share is better surfaced here, by
    #    name, than as a mid-request failure later.
    # 2. The budget corpus has at least one chunk — catches the "fresh
    #    machine, forgot to copy the lancedb folder" case, which would
    #    otherwise answer every question with nothing.
    try:
        root = data_dir()
        # Unique probe name: two sidecars starting at once must not delete
        # each other's probe and report a phantom permissions failure.
        probe = root / f".sidecar-write-probe-{uuid4().hex[:8]}"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as err:
        sys.stderr.write(
            f"\n[retrieval-sidecar] cannot use the shared data folder: {err}\n"
            "  That folder is JLBC_DATA_DIR (unset means data/insight-data\n"
            "  inside the repo). Check the path exists and is writable.\n\n"
        )
        sys.exit(1)

    try:
        chunk_count = _store().count(DEFAULT_CORPUS)
    except Exception as err:
        sys.stderr.write(
            f"\n[retrieval-sidecar] could not open the chunk store in {root}: "
            f"{err}\n"
            "  The folder should contain a `lancedb` directory holding the\n"
            "  corpus tables. Copy it from a machine that has one, or run\n"
            "  scripts/migrate_to_lancedb.py to build it.\n\n"
        )
        sys.exit(1)
    if chunk_count == 0:
        sys.stderr.write(
            f"\n[retrieval-sidecar] the '{DEFAULT_CORPUS}' table in {root} has "
            "no chunks.\n"
            "  Copy the `lancedb` folder from a machine that has the corpus,\n"
            "  or run scripts/migrate_to_lancedb.py, before starting the "
            "sidecar.\n\n"
        )
        sys.exit(1)
    sys.stderr.write(
        f"[retrieval-sidecar] corpus OK - {chunk_count:,} chunks in "
        f"{DEFAULT_CORPUS}.\n"
    )

    # Warm the retrieval path before accepting requests. WHY: the FIRST
    # cold /retrieve has to load two ONNX models off disk (the embedder and
    # the much larger cross-encoder reranker — ~4s together, measured, and
    # slower from the office share) and open the LanceDB table handles and
    # FTS index. The MCP bridge gives a tool call 15s, so a question landing
    # in that cold window can fail with "retrieval service offline" even
    # though nothing is broken. Running one throwaway query here moves that
    # cost into startup, so by the time /health reports OK (what the web UI
    # gates on) the path is primed and the first real query returns in
    # ~1-2s. Best-effort: a warmup failure (e.g. a half-copied model file)
    # logs a warning but does NOT block startup — the lazy path still builds
    # the models on the first real request.
    try:
        retrieve(RetrievalRequest(query="arizona state budget", top_k=1))
        sys.stderr.write("[retrieval-sidecar] warmup query OK - retrieval path primed.\n")
    except Exception as err:
        sys.stderr.write(
            f"[retrieval-sidecar] warmup query failed (non-fatal): {err}\n"
            "  First real /retrieve will pay the cold-start cost instead.\n"
        )

    yield


app = FastAPI(
    title="Ask the Budget AZ — retrieval sidecar",
    version="0.1.0",
    lifespan=lifespan,
)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/health", response_model=None)
def health() -> dict[str, Any] | JSONResponse:
    """Liveness probe. The dev script polls this before launching the
    MCP server so the first `retrieve` call doesn't race with startup.

    `voyage_key_present` was replaced by `corpus_chunks` + `data_dir` in
    Plan 1: there is no Voyage key any more, and "the sidecar is up but
    pointed at the wrong / an empty folder" is the failure this probe is
    actually useful for catching. `documents_metadata` is the same idea for
    the other half of the corpus: 0 here means documents.json is missing or
    unreadable, which is exactly the state in which citation chips can't
    open a PDF.

    Reading the corpus can fail (unreachable share, deleted folder), and
    this is the one endpoint where the failure IS the payload — see the
    except branch.
    """
    try:
        return {
            "status": "ok",
            "version": app.version,
            "corpus_chunks": _store().count(DEFAULT_CORPUS),
            "documents_metadata": len(_document_metadata()),
            "data_dir": str(data_dir()),
        }
    except Exception as err:
        # WHY answer instead of propagating: a bare 500 throws the reason
        # away (a traceback in the sidecar's log, nothing anywhere a user
        # looks) and reads as "the sidecar is down" when the sidecar is up
        # and the folder it reads is not. The real exception text goes in
        # the body verbatim — never a guessed cause.
        #
        # WHY 503 rather than 200: the web app's session-start probe gates
        # purely on `resp.ok` (youcoded-session-provider.ts), so a 200 would
        # be read as healthy and the SystemHealthBanner would stay hidden
        # while every query returned nothing. 503 keeps the banner honest
        # AND carries the detail for anyone who curls it.
        #
        # data_dir() is deliberately not echoed here: resolving it is one of
        # the things that can raise.
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "version": app.version,
                "error": f"{type(err).__name__}: {err}",
            },
        )


# ---------------------------------------------------------------------------
# Document metadata sidecar
# ---------------------------------------------------------------------------
# `<data_dir>/documents.json` — {doc_id: {title, source_format,
# source_blob_path, source_url, page_count, fiscal_year, publisher,
# doc_type}} — written by scripts/migrate_to_lancedb.py (`--docs-only`
# refreshes it in ~1s without re-embedding).
#
# WHY this file exists: the LanceDB chunk schema has nowhere to put
# document-level facts, and `source_format` + `source_blob_path` are what
# the web app's /api/pdf/[doc_id] route needs to stream the right PDF.
# Without them every citation chip fell into that route's
# "unsupported_source_format" branch — a wrong error for a real PDF, and
# Core Invariant 1 (a citation opens the exact page) silently suspended.
#
# Optional by design: a corpus copied without the file still answers
# /docs and /retrieve, just with derived titles and no PDF path.

_docs_lock = threading.Lock()
_docs_cache: dict[str, dict[str, Any]] = {}
# (path, mtime, size) of the file the cache was built from. Comparing all
# three means the cache invalidates itself when the file is rewritten AND
# when JLBC_DATA_DIR is repointed at a different corpus — no reset hook to
# remember to call (tests repoint it constantly).
_docs_stamp: tuple[str, float, int] | None = None


def _document_metadata() -> dict[str, dict[str, Any]]:
    """Parsed documents.json, cached until the file changes on disk.

    Reload is mtime+size based rather than load-once-at-startup so an
    ingest (or a `--docs-only` refresh) shows up without restarting the
    sidecar. A missing file is normal and returns {}; a malformed one warns
    to stderr and also returns {}, because degrading to derived titles is
    better than 500ing every /docs and /retrieve call.
    """
    global _docs_cache, _docs_stamp
    path = documents_path()
    try:
        st = path.stat()
        stamp: tuple[str, float, int] | None = (str(path), st.st_mtime, st.st_size)
    except OSError:
        stamp = None  # absent or unreadable — fall back silently
    with _docs_lock:
        if stamp == _docs_stamp:
            return _docs_cache
        if stamp is None:
            _docs_cache, _docs_stamp = {}, None
            return _docs_cache
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict):
                raise ValueError(
                    "expected a JSON object of doc_id -> metadata, got "
                    f"{type(loaded).__name__}"
                )
        except (OSError, ValueError) as err:
            # Name the file and the real parse error — the fix is always to
            # re-run the migration that writes it.
            sys.stderr.write(
                f"[retrieval-sidecar] ignoring {path}: {err}\n"
                "  Document titles fall back to doc_id slugs and PDF paths\n"
                "  are unavailable until it is valid. Rebuild it with:\n"
                "  uv run python scripts/migrate_to_lancedb.py --docs-only\n"
            )
            loaded = {}
        _docs_cache, _docs_stamp = loaded, stamp
        return _docs_cache


# Slug parts that are acronyms, not words — capitalize() would render them
# "Jlbc" / "Afr". Kept character-identical to the web app's copy of this
# humanizer (Plan 2's `_title_from_doc_id`) so the two layers never show a
# different title for the same document.
_SLUG_ACRONYMS = ("jlbc", "agao", "afr", "sad")


def _title_from_doc_id(doc_id: str) -> str:
    """Best-effort humanization of a doc_id slug
    ('jlbc-baseline-fy2027-axs' -> 'JLBC Baseline FY 2027 Axs').

    FALLBACK ONLY — used when documents.json is missing or doesn't know
    this doc_id. The real ingest title ('JLBC FY2026 — AHCCCS') is much
    better than a prettified slug ('JLBC Baseline FY 2026 Axs'), which is
    why _lookup_doc_titles prefers the sidecar.
    """
    out: list[str] = []
    for part in doc_id.split("-"):
        if part.startswith("fy") and part[2:].isdigit():
            out.append(f"FY {part[2:]}")
        elif part in _SLUG_ACRONYMS:
            out.append(part.upper())
        else:
            out.append(part.capitalize())
    return " ".join(out)


def _lookup_doc_titles(doc_ids: list[str]) -> dict[str, str]:
    """doc_id -> display title. Empty input returns {}.

    Prefers the real ingest title from documents.json; falls back to the
    slug humanizer per doc_id (so a corpus copied without the sidecar, or
    one document the sidecar hasn't caught up with, still gets a label).
    These titles are what the model reads in every retrieve() result, so
    the difference is visible in answers, not just in the UI.
    """
    docs = _document_metadata()
    return {
        doc_id: (docs.get(doc_id, {}).get("title") or _title_from_doc_id(doc_id))
        for doc_id in doc_ids
    }


@app.post("/retrieve")
def http_retrieve(body: RetrieveRequestBody) -> RetrieveResponse:
    """Run the hybrid retrieval pipeline and shape the response per
    citation-tool-schema.md. The Node MCP server forwards the JSON
    body verbatim to Claude (in a `text` content block), so the
    field names + types here are the *visible* contract to the model.
    """
    f = body.filters or RetrieveFiltersBody()
    # Resolve top_k:
    #   explicit body.top_k    > body.intent's default > DEFAULT
    # The explicit-wins rule keeps back-compat for callers that have
    # always passed top_k; the intent path is only consulted when the
    # caller hasn't decided. DEFAULT_PIPELINE_TOP_K covers the no-intent
    # back-compat case.
    if body.top_k is not None:
        resolved_top_k = body.top_k
    elif body.intent and body.intent in _INTENT_TOP_K:
        resolved_top_k = _INTENT_TOP_K[body.intent]
    else:
        from retrieval.pipeline import DEFAULT_PIPELINE_TOP_K
        resolved_top_k = DEFAULT_PIPELINE_TOP_K

    req = RetrievalRequest(
        query=body.query,
        fiscal_year=f.fiscal_year,
        doc_type=f.doc_type,
        publisher=f.publisher,
        agency_canonical_id=f.agency_canonical_id,
        fund_canonical_id=f.fund_canonical_id,
        is_table=f.is_table,
        top_k=resolved_top_k,
    )
    # No collaborators injected: the pipeline's process-wide singletons own
    # the store and the two ONNX models. Passing an embedder from here (as
    # the Voyage version did) would mean the sidecar holding a second one.
    result = retrieve(req)

    # Attach doc_title. Done at the sidecar boundary (rather than inside the
    # retrieval pipeline) so the retrieval module stays focused on retrieval
    # — schema-shape concerns belong to the layer that owns the schema.
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
                bbox=c.bbox,
                text=c.text,
                text_length=len(c.text or ""),
                score=c.score,
            )
            for c in result.chunks
        ],
        top_score=result.top_score,
        retrieval_id=str(uuid4()),
        bm25_count=result.bm25_count,
        dense_count=result.dense_count,
        fused_count=result.fused_count,
        # Echo the caller's intent (None when not provided) so the
        # future audit-log writer can pick it up from the response
        # without re-parsing the request body.
        intent=body.intent,
    )


@app.get("/docs/{doc_id}", response_model_exclude_none=True)
def http_doc_metadata(doc_id: str) -> DocMetadataResponse:
    """Look up a single document's metadata. Used by the Next.js
    `/api/pdf/[doc_id]` route to resolve a citation chip into a file to
    stream. Returns 404 only when NEITHER the documents.json sidecar nor
    any chunk in the corpus knows that doc_id.

    Two sources, merged in that order of preference:
      * documents.json — the real ingest metadata, including the fields
        that make click-to-open-PDF work.
      * the document's own chunk rows — publisher / doc_type / fiscal_year
        are denormalized onto every chunk, so they answer even without the
        sidecar, and they cover a document the sidecar hasn't caught up
        with yet.
    """
    entry = _document_metadata().get(doc_id) or {}
    chunk_rows = _store().scan(
        DEFAULT_CORPUS,
        ["doc_id", "publisher", "doc_type", "fiscal_year"],
        # sql_str, not an f-string: LanceDB filters are SQL text with no
        # parameter binding, and doc_id arrives from the client.
        where=f"doc_id = {sql_str(doc_id)}",
        # limit=1: these columns are document-level, repeated identically on
        # every chunk. Without it, asking about the Governor's budget pulled
        # back 1,395 copies of the same four values.
        limit=1,
    )
    if not entry and not chunk_rows:
        raise HTTPException(status_code=404, detail="doc_id not found")
    # Every chunk of a document carries the same document-level values, so
    # any row answers the question.
    chunk_row = chunk_rows[0] if chunk_rows else {}

    def field(name: str) -> Any:
        """Sidecar value if it has a real one, else the chunk row's."""
        value = entry.get(name)
        return chunk_row.get(name) if value is None else value

    return DocMetadataResponse(
        doc_id=doc_id,
        title=entry.get("title") or _title_from_doc_id(doc_id),
        publisher=field("publisher"),
        doc_type=field("doc_type"),
        fiscal_year=field("fiscal_year"),
        # Sidecar-only: nothing on a chunk row knows where the PDF is.
        source_format=entry.get("source_format"),
        source_blob_path=entry.get("source_blob_path"),
        page_count=entry.get("page_count"),
        source_url=entry.get("source_url"),
    )


# Columns /list_values needs off every chunk. Projected explicitly because a
# full-row scan would drag every chunk's text through memory for what is
# really a metadata question.
_LIST_VALUES_COLUMNS = [
    "doc_id",
    "agency_canonical_ids",
    "fund_canonical_id",
    "doc_type",
    "publisher",
]


def _most_populated_doc(chunks_per_doc: dict[str, int]) -> str:
    """The document contributing the most chunks to one canonical_id; ties
    break on lowest doc_id so the same corpus always yields the same sample.

    WHY most-populated and not highest-fiscal-year (which is what the
    Postgres query did): measured on the real corpus, the newest document
    mentioning almost any agency is the FY2027 Governor's Budget — one
    cross-cutting book that touches nearly all 134 agencies and is titled
    "GOVERNOR FY2027 fy2027". Sampling it tells the model nothing about
    `agency:axs`, which is the entire job of this field. Most-populated
    picks the document that is actually ABOUT the agency: "JLBC FY2025 —
    AHCCCS". This is also what FilterValueOut's docstring has always
    claimed the rule was.
    """
    return min(chunks_per_doc.items(), key=lambda kv: (-kv[1], kv[0]))[0]


def _values_by_chunk(
    rows: list[dict[str, Any]], values_of
) -> list[FilterValueOut]:
    """Count CHUNKS per canonical_id (the agency / fund dimensions).
    `values_of(row)` yields zero or more canonical_ids for one chunk —
    agency_canonical_ids is an array column, so a chunk can count toward
    several agencies, exactly as the Postgres unnest() did."""
    counts: dict[str, int] = {}
    # canonical_id -> doc_id -> how many of that doc's chunks carry it.
    per_doc: dict[str, dict[str, int]] = {}
    for row in rows:
        for value in values_of(row):
            counts[value] = counts.get(value, 0) + 1
            docs = per_doc.setdefault(value, {})
            docs[row["doc_id"]] = docs.get(row["doc_id"], 0) + 1
    samples = {
        value: _most_populated_doc(docs) for value, docs in per_doc.items()
    }
    # _lookup_doc_titles, NOT the slug humanizer: the whole point of the
    # sample title is to make an opaque canonical_id ('agency:axs')
    # recognizable, and a humanized slug ('JLBC Baseline FY 2027 Axs') is
    # just as opaque. The real ingest title says AHCCCS.
    titles = _lookup_doc_titles(list(samples.values()))
    return _sorted_values(
        counts, {value: titles[doc_id] for value, doc_id in samples.items()}
    )


def _values_by_document(
    rows: list[dict[str, Any]], column: str
) -> list[FilterValueOut]:
    """Count DOCUMENTS per value (the doc_type / publisher dimensions).

    Inherited semantics, kept on purpose: the Postgres version aggregated
    the `documents` table for these two, so the number is distinct doc_ids
    rather than chunks (FilterValueOut's docstring says "chunks (or
    documents)"). Changing it here would silently change what the model
    reads off the same field name.
    """
    doc_ids: dict[str, set[str]] = {}
    for row in rows:
        doc_ids.setdefault(row[column], set()).add(row["doc_id"])
    counts = {value: len(ids) for value, ids in doc_ids.items()}
    # `MIN(title)` in the old SQL — alphabetically first title in the group,
    # taken over the REAL titles (see _values_by_chunk for why not the slug
    # humanizer). MIN over humanized slugs would also have picked a
    # different document than MIN over real titles.
    looked_up = _lookup_doc_titles(
        sorted({d for ids in doc_ids.values() for d in ids})
    )
    titles = {
        value: min(looked_up[d] for d in ids) for value, ids in doc_ids.items()
    }
    return _sorted_values(counts, titles)


def _sorted_values(
    counts: dict[str, int], titles: dict[str, str]
) -> list[FilterValueOut]:
    """Most-used first (so a truncating client keeps the head and drops the
    long tail of one-off / typo'd ids). Ties break on canonical_id so the
    order is stable between calls."""
    return [
        FilterValueOut(
            canonical_id=value,
            chunk_count=count,
            sample_doc_title=titles.get(value),
        )
        for value, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    ]


@app.post("/list_values", response_model_exclude_none=True)
def http_list_values(body: ListValuesBody) -> ListValuesResponse:
    """Enumerate the canonical_ids actually present in the corpus for a
    given filter dimension, with a count and a sample doc title so the
    model can identify each slug. The MCP client should call this when it
    sees an unfamiliar agency/fund name in a user question rather than
    guessing the canonical_id and risking a silent zero-match.

    Why a sample title: canonical_ids like `agency:axs` (AHCCCS) or
    `agency:tre` (Treasurer) are opaque without context. The document
    contributing the most chunks to that slug is the one that is actually
    about it, so its title ("JLBC FY2025 — AHCCCS") names the thing. Titles
    come from the documents.json sidecar; without that file they degrade to
    humanized slugs, which is honest but much less useful.

    Implementation note: this was four SQL aggregate queries; on LanceDB it
    is one projected scan plus a Python group-by. Measured on the real
    7,755-chunk corpus with these six columns: ~60ms for the scan, which is
    cheaper than it sounds because the vector column and the chunk text
    are projected away.
    """
    field = body.field.strip().lower()
    if field not in ("agency", "fund", "doc_type", "publisher"):
        raise HTTPException(
            status_code=400,
            detail=(
                f"unknown field '{body.field}' — must be one of "
                "'agency', 'doc_type', 'publisher', 'fund'"
            ),
        )

    rows = _store().scan(DEFAULT_CORPUS, _LIST_VALUES_COLUMNS)
    if field == "agency":
        values = _values_by_chunk(rows, lambda r: r["agency_canonical_ids"] or [])
    elif field == "fund":
        # Nullable column: `WHERE fund_canonical_id IS NOT NULL` in the old
        # SQL, so a NULL never becomes a value named "None".
        values = _values_by_chunk(
            rows, lambda r: [r["fund_canonical_id"]] if r["fund_canonical_id"] else []
        )
    else:
        values = _values_by_document(rows, field)
    return ListValuesResponse(field=field, values=values)


# ---------------------------------------------------------------------------
# Citation validation endpoints
# ---------------------------------------------------------------------------
# Thin HTTP wrappers. Every behavior below (quote resolution, duplicate-
# quote rejection, span sanity, claim_span soft-truncate) lives in
# retrieval.citations so the in-process tool loop runs the SAME code, not
# a second copy that can drift. These routes only translate JSON in and
# out — and always against the default budget corpus, because the sidecar
# has no corpus parameter on the wire.


@app.post("/cite/validate", response_model_exclude_none=True)
def http_cite_validate(body: CiteValidateBody) -> CiteValidateResponse:
    """Validate a single cite() call: chunk_id exists, quote-in-chunk
    (or explicit offsets), span sanity.

    Delegates to retrieval.citations.validate_cite, passing this process's
    store singleton so the sidecar never opens a second set of LanceDB
    table handles against the same files on the share."""
    return validate_cite(body, store=_store())


@app.post("/cite/validate_batch", response_model_exclude_none=True)
def http_cite_validate_batch(
    body: CiteValidateBatchBody,
) -> CiteValidateBatchResponse:
    """Validate N cite() calls in one round-trip.

    Why batch: the 2026-05-20 dogfood pass measured cite() round-trip cost
    at ~3s/call. An analyze-shaped answer with 15-20 cites was therefore
    eating 45-60s of LLM-turn cycle time just in serial tool round-trips,
    even before failures and retries kicked in. The model already wants
    to emit all citations at once after writing its answer; giving it a
    tool that takes them as a single call collapses those 15-20 round-
    trips into 1.

    validate_cites() does the matching server-side collapse: ONE store
    read for all unique chunk_ids, then an in-memory fan-out with order
    preserved and per-citation independence. Empty input returns
    {citations: []} rather than a 4xx — the model may hand over zero
    citations if it changed its mind mid-answer.
    """
    return CiteValidateBatchResponse(
        citations=validate_cites(body.citations, store=_store())
    )
