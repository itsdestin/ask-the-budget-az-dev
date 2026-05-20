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

# Load .env.local on import so subsequent os.environ reads (VOYAGE_API_KEY,
# DATABASE_URL) work whether or not the user remembered to `set -a;
# source .env.local; set +a` (bash) / `Get-Content .env.local | ...` (pwsh).
# Done at import time (not inside lifespan) so it's already in effect by
# the time pydantic / psycopg read env vars during module load.
from dotenv import load_dotenv
load_dotenv(".env.local")
load_dotenv()  # fallback to .env if .env.local missing

import html
import os
import re
import unicodedata
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
    # top_k is optional now: an explicit value overrides the intent's
    # default; absent + intent set → server picks top_k from the
    # _INTENT_TOP_K table; absent + no intent → server uses
    # DEFAULT_PIPELINE_TOP_K (15 after Task 8 lands).
    top_k: int | None = None
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

    `source_blob_path` is the on-disk path the ingest pipeline saved
    the original artifact to (relative to the project root or
    absolute, depending on how ingest was run). Phase 1c WS4c reads
    it from the Next.js `/api/pdf/[doc_id]` route to stream the PDF
    bytes back to PDF.js with HTTP Range support. The endpoint is
    metadata-only — actual file bytes flow through Next.js because
    Phase 1 is single-machine (Next + sidecar share the filesystem)
    and Node has cleaner Range-streaming primitives than uvicorn.
    """

    doc_id: str
    title: str
    publisher: str
    doc_type: str
    fiscal_year: int
    source_format: str
    source_blob_path: str
    page_count: int | None
    source_url: str | None


class CiteValidateBody(BaseModel):
    chunk_id: str
    # Either (span_start, span_end) OR quote must be supplied. The MCP
    # handler also enforces this; the dual-layer check catches calls
    # from any other future client too.
    span_start: int | None = None
    span_end: int | None = None
    # Preferred path post-2026-05-20: the model pastes the exact
    # substring of chunk.text it wants to cite, and the server scans
    # for it. Avoids the 21-occurrence Bash-script workaround past
    # sessions used to compute offsets.
    quote: str | None = None
    # claim_span and confidence are optional for back-compat — when both
    # are present, /cite/validate ALSO checks that the cited span
    # actually supports the claim.
    claim_span: str | None = None
    confidence: str | None = None


class CiteValidateResponse(BaseModel):
    ok: bool
    error: str | None = None
    chunk_text_length: int | None = None
    cited_text_preview: str | None = None
    # When the caller passed a `quote`, the server derives offsets and
    # echoes them back so the UI can attach the bbox highlight at the
    # right position. None when the caller passed offsets directly.
    resolved_span_start: int | None = None
    resolved_span_end: int | None = None
    # True when claim_span was over 500 chars and the server truncated
    # it before running alignment. The UI still uses the (truncated)
    # claim_span for chip attachment.
    truncated: bool | None = None


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
_INTENT_TOP_K: dict[str, int] = {
    "lookup": 5,
    "compare": 12,
    "analyze": 25,
}


# ---------------------------------------------------------------------------
# App + embedder cache
# ---------------------------------------------------------------------------


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Preflight: validate the environment before the sidecar accepts
    # requests. Three checks; fail fast on any.
    #
    # 1. VOYAGE_API_KEY present — every /retrieve and rerank call needs it.
    # 2. DATABASE_URL reachable — `SELECT 1` confirms libpq can connect.
    # 3. The chunks table has at least one embedded row — sanity check that
    #    the corpus actually loaded (catches a freshly-built but unseeded DB).
    #
    # On any failure we log a clear message and sys.exit(1) so the user
    # sees the problem at uvicorn startup instead of mid-request.
    import sys

    if not os.environ.get("VOYAGE_API_KEY"):
        sys.stderr.write(
            "\n[retrieval-sidecar] VOYAGE_API_KEY is not set.\n"
            "  Add it to .env.local (the sidecar auto-loads that file)\n"
            "  or export it before running `uv run uvicorn retrieval.api:app`.\n\n"
        )
        sys.exit(1)
    if not os.environ.get("DATABASE_URL"):
        sys.stderr.write(
            "\n[retrieval-sidecar] DATABASE_URL is not set.\n"
            "  Check db/.env (it should set DATABASE_URL to your Postgres URI).\n\n"
        )
        sys.exit(1)
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT 1 FROM chunks LIMIT 1").fetchone()
            if row is None:
                sys.stderr.write(
                    "\n[retrieval-sidecar] connected to Postgres but the "
                    "chunks table is empty.\n"
                    "  Run the ingest pipeline (or restore db/data from a "
                    "working machine) before starting the sidecar.\n\n"
                )
                sys.exit(1)
    except Exception as err:  # psycopg.OperationalError + a few others
        sys.stderr.write(
            f"\n[retrieval-sidecar] could not connect to Postgres: {err}.\n"
            "  Is Docker running?  (cd db && docker compose up -d)\n\n"
        )
        sys.exit(1)

    # Embedder is constructed lazily on first /retrieve.
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
    """Look up a single document's metadata (including the on-disk
    source path). Used by the Next.js `/api/pdf/[doc_id]` route to
    resolve a click-on-chip into a file to stream. Returns 404 when
    `doc_id` is not in the documents table.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT doc_id, title, publisher, doc_type, fiscal_year,
                   source_format, source_blob_path, page_count, source_url
            FROM documents
            WHERE doc_id = %s
            """,
            [doc_id],
        ).fetchone()
    if row is None:
        # Importing here keeps the top-of-module imports stable and
        # avoids paying the import cost when /docs is never called.
        from fastapi import HTTPException

        raise HTTPException(status_code=404, detail="doc_id not found")
    return DocMetadataResponse(
        doc_id=row["doc_id"],
        title=row["title"],
        publisher=row["publisher"],
        doc_type=row["doc_type"],
        fiscal_year=row["fiscal_year"],
        source_format=row["source_format"],
        source_blob_path=row["source_blob_path"],
        page_count=row["page_count"],
        source_url=row["source_url"],
    )


@app.post("/list_values", response_model_exclude_none=True)
def http_list_values(body: ListValuesBody) -> ListValuesResponse:
    """Enumerate the canonical_ids actually present in the corpus for a
    given filter dimension, with a count and a sample doc title so the
    model can identify each slug. Cheap (one indexed aggregate query)
    and stable within a session — the MCP client should call this when
    it sees an unfamiliar agency/fund name in a user question rather
    than guessing the canonical_id and risking a silent zero-match.

    Why a sample title: canonical_ids like `agency:axs` (AHCCCS) or
    `agency:tre` (Treasurer) are opaque without context. The most-
    populated document for that agency tells the model what it is.
    """
    field = body.field.strip().lower()
    with get_connection() as conn:
        if field == "agency":
            # CROSS JOIN LATERAL on unnest() (NOT comma-FROM): the comma
            # form parses as `FROM chunks, (unnest JOIN documents)` so
            # the documents JOIN can't see the chunks alias. Same
            # gotcha applies to the samples CTE below.
            rows = conn.execute(
                """
                WITH counts AS (
                  SELECT aid, COUNT(*) AS chunk_count
                  FROM chunks
                  CROSS JOIN LATERAL unnest(agency_canonical_ids) AS aid
                  GROUP BY aid
                ),
                samples AS (
                  SELECT DISTINCT ON (aid)
                    aid, d.title AS sample_title
                  FROM chunks c
                  JOIN documents d ON c.doc_id = d.doc_id
                  CROSS JOIN LATERAL unnest(c.agency_canonical_ids) AS aid
                  ORDER BY aid, d.fiscal_year DESC NULLS LAST
                )
                SELECT cnt.aid AS canonical_id,
                       cnt.chunk_count,
                       s.sample_title
                FROM counts cnt
                LEFT JOIN samples s USING (aid)
                ORDER BY cnt.chunk_count DESC
                """,
            ).fetchall()
        elif field == "fund":
            rows = conn.execute(
                """
                WITH counts AS (
                  SELECT fund_canonical_id AS canonical_id, COUNT(*) AS chunk_count
                  FROM chunks
                  WHERE fund_canonical_id IS NOT NULL
                  GROUP BY fund_canonical_id
                ),
                samples AS (
                  SELECT DISTINCT ON (c.fund_canonical_id)
                    c.fund_canonical_id AS canonical_id,
                    d.title AS sample_title
                  FROM chunks c
                  JOIN documents d ON c.doc_id = d.doc_id
                  WHERE c.fund_canonical_id IS NOT NULL
                  ORDER BY c.fund_canonical_id, d.fiscal_year DESC NULLS LAST
                )
                SELECT c.canonical_id,
                       c.chunk_count,
                       s.sample_title
                FROM counts c
                LEFT JOIN samples s USING (canonical_id)
                ORDER BY c.chunk_count DESC
                """,
            ).fetchall()
        elif field == "doc_type":
            rows = conn.execute(
                """
                SELECT doc_type AS canonical_id,
                       COUNT(*) AS chunk_count,
                       MIN(title) AS sample_title
                FROM documents
                GROUP BY doc_type
                ORDER BY chunk_count DESC
                """,
            ).fetchall()
        elif field == "publisher":
            rows = conn.execute(
                """
                SELECT publisher AS canonical_id,
                       COUNT(*) AS chunk_count,
                       MIN(title) AS sample_title
                FROM documents
                GROUP BY publisher
                ORDER BY chunk_count DESC
                """,
            ).fetchall()
        else:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=(
                    f"unknown field '{body.field}' — must be one of "
                    "'agency', 'doc_type', 'publisher', 'fund'"
                ),
            )
    return ListValuesResponse(
        field=field,
        values=[
            FilterValueOut(
                canonical_id=r["canonical_id"],
                chunk_count=int(r["chunk_count"]),
                sample_doc_title=r.get("sample_title"),
            )
            for r in rows
        ],
    )


# ---------------------------------------------------------------------------
# Citation-alignment helpers (used by /cite/validate)
# ---------------------------------------------------------------------------

# Smart quotes / dashes that the renderer's normalizeForMatch folds. Keeping
# the table in sync with web/lib/citation-extract.ts:486-510 — when one side
# changes, port the change to the other or claim_span matching will diverge.
_QUOTE_FOLDS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
}
_DASH_FOLDS = {
    "–": "-", "—": "-", "−": "-",
    "‐": "-", "‑": "-", "‒": "-",
}
# Markdown formatting tokens stripped during normalize. We keep the
# delimiter set narrow (bold/italic/strikethrough/inline-code/pipe) to
# match the renderer; broader stripping would risk dropping content
# that legitimately contains these characters (e.g. dollar amounts).
_MD_BOLD_OR_ITALIC = re.compile(r"\*\*|__|\*|_|~~|`")
# Markdown link [label](url) — collapse to label only.
_MD_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
# Markdown backslash escape: `\X` where X is a markdown-escapable
# punctuation char means "literal X". MinerU and other ingest pipelines
# emit `\$` to prevent `$…$` from rendering as math, and `\(`, `\)`,
# `\[`, `\]` for similar reasons. The renderer's PDF text layer has the
# UNESCAPED form, so a chunk-text-to-PDF substring match silently fails
# unless we strip the leading backslash here. Set of escapable chars
# matches CommonMark §2.4.
_MD_ESCAPE = re.compile(r"\\([\\`*_{}\[\]()#+\-.!|>~$])")
# Accounting parentheses around dollar amounts. Two equivalent
# conventions appear in budget docs:
#   `$(10,000,000)` — dollar-first, MinerU's preferred output shape
#   `($10,000,000)` — paren-first, the form that often appears in
#     the PDF text layer because pdfjs reads characters left-to-right
#     and the rendered glyph order is "(", "$", "1", "0", ...
# Both denote a negative / decrease; the sign is in the verb of the
# claim, not the number. Collapsing both forms means a claim that
# normalizes to `$10,000,000` matches a chunk or PDF text using
# either accounting convention.
_ACCOUNTING_PARENS_DOLLAR_FIRST = re.compile(r"\$\(([\d,.]+)\)")
_ACCOUNTING_PARENS_PAREN_FIRST = re.compile(r"\(\$([\d,.]+)\)")
# Abbreviated dollar amounts: `$5.0 million` / `$5.0 M` / `$5.0 billion`
# / `$5.0 B` / `$5.0 thousand` / `$5.0 K`. Models routinely write the
# abbreviated form in claims while the source has the explicit comma-
# grouped form (`$5,000,000`). Expanding to the explicit form lets both
# verbatim and paraphrase checks match across the abbreviation gap.
# Capturing the suffix as a word boundary keeps "minute" / "moderate"
# from triggering "M".
_DOLLAR_ABBREV = re.compile(
    r"\$([\d,.]+)\s*(million|billion|thousand|m|b|k)\b",
    flags=re.IGNORECASE,
)
_DOLLAR_MULTIPLIER = {
    "million": 1_000_000, "m": 1_000_000,
    "billion": 1_000_000_000, "b": 1_000_000_000,
    "thousand": 1_000, "k": 1_000,
}


def _expand_dollar_amount(match: re.Match[str]) -> str:
    """Convert `$5.0 million` → `$5,000,000`. Handles decimals; ignores
    commas inside the source number ("$5,000 million" → 5000 × 1M)."""
    amount_str = match.group(1).replace(",", "")
    try:
        amount = float(amount_str)
    except ValueError:
        return match.group(0)  # leave malformed amounts alone
    unit = match.group(2).lower()
    multiplier = _DOLLAR_MULTIPLIER.get(unit, 1)
    return f"${int(amount * multiplier):,}"


def _normalize_for_match(text: str) -> str:
    """Lowercase, NFKC, fold smart quotes / dashes, strip markdown
    formatting tokens, expand dollar abbreviations, collapse whitespace.
    Mirrors the renderer's `normalizeForMatch`
    (web/lib/citation-extract.ts:376) closely enough that a claim_span
    found by the renderer in the cited PDF text will also pass
    server-side validation here. The renderer also produces an
    indexMap back to original offsets; we don't need that here because
    the validator only does substring / word-bag checks, not span
    remapping.

    Order matters: markdown-escape stripping must run BEFORE accounting-
    paren collapse (`\\$(X)` → `$(X)` → `$X`), and dollar-abbreviation
    expansion runs BEFORE NFKC/lowercase so the unit regex can match
    case-insensitively without re-folding.
    """
    if not text:
        return ""
    # HTML entity decode (the renderer does this in parseInlineCiteAttrs).
    s = html.unescape(text)
    # Strip markdown backslash escapes (\$ → $, \( → (, etc.) — must run
    # before accounting-paren collapse since chunks frequently have
    # `\$(X)` from the ingest pipeline.
    s = _MD_ESCAPE.sub(r"\1", s)
    # Collapse both accounting-negative conventions to `$X` so claim
    # "$10 million" matches chunk "$(10,000,000)" or PDF "($10,000,000)"
    # after expansion.
    s = _ACCOUNTING_PARENS_DOLLAR_FIRST.sub(r"$\1", s)
    s = _ACCOUNTING_PARENS_PAREN_FIRST.sub(r"$\1", s)
    # Expand abbreviated dollar amounts before NFKC/lowercase so the
    # unit-matching is straightforward and we don't have to handle
    # NFKC compatibility forms inside the unit regex.
    s = _DOLLAR_ABBREV.sub(_expand_dollar_amount, s)
    # NFKC so compatibility forms (e.g. ﬁ → fi) collapse.
    s = unicodedata.normalize("NFKC", s)
    # Strip markdown link wrappers — keep the label.
    s = _MD_LINK.sub(r"\1", s)
    # Strip bold/italic/strikethrough/inline-code delimiters.
    s = _MD_BOLD_OR_ITALIC.sub("", s)
    # Table-cell separator → whitespace (so cells separate cleanly).
    s = s.replace("|", " ")
    # Smart quote / dash folds.
    out: list[str] = []
    for ch in s:
        if ch in _QUOTE_FOLDS:
            out.append(_QUOTE_FOLDS[ch])
        elif ch in _DASH_FOLDS:
            out.append(_DASH_FOLDS[ch])
        else:
            out.append(ch.lower())
    # Collapse whitespace runs (including NBSP, already covered by \s).
    return re.sub(r"\s+", " ", "".join(out)).strip()


# Words ≥4 letters are the "content words" used for paraphrase overlap.
# Short words (the, and, for, of, in) are dropped because they're shared
# by almost any English text and produce false-positive overlap. Numbers
# and currency punctuation are preserved as their own tokens — claim
# texts often hinge on a specific dollar figure ("$4,677,100"), and a
# paraphrase cite that omits the number is a cite to nothing.
_CONTENT_WORD_RE = re.compile(r"[a-z]{4,}|\$[\d,.]+|\d[\d,.]*")


def _content_words(normalized: str) -> list[str]:
    """Tokenize a normalized string into content words for overlap
    scoring. Currency tokens are CANONICALIZED to their bare form
    (`$X` → `X`) so claim and cited compare equal regardless of which
    side carries the dollar sign — common in budget tables where the
    `$` is shown once in the header and dropped on every value row.

    Earlier (2026-05-12) implementation dual-emitted both `$X` and
    `X` from the same input, which inflated the denominator when one
    side had `$X` (counted twice in claim_words) and the other had
    bare `X` (matched once). A pure-verbatim cite of `$131,582,200`
    against cited `131,582,200` then scored 1/2 = 50% instead of
    100% and failed the threshold. Canonicalizing both sides to the
    bare form fixes the asymmetry.
    """
    out: list[str] = []
    for tok in _CONTENT_WORD_RE.findall(normalized):
        if tok.startswith("$"):
            out.append(tok[1:])  # drop $ — canonical bare-number form
        else:
            out.append(tok)
    return out


# Threshold tuning notes (2026-05-11):
# - The 0.60 paraphrase threshold was chosen by replaying the latest
#   conversation's 28 cite() calls through this validator. Settings:
#     * 0.50 — passes everything including the genuinely bad #18
#       ("ballot paper" claim cited to Operating Budget composition).
#     * 0.60 — catches the worst cases (#10, #11, #18, #28) while
#       letting genuine paraphrases (#6, #23) pass.
#     * 0.70 — starts rejecting legitimate paraphrases where the
#       cited text uses different word order or substitutes phrasing.
#   Re-run the audit script after any normalize change to confirm.
# - SPAN_BREADTH_LIMIT is a separate signal: when the model picks
#   span_start=0 / span_end=len(chunk), the bbox highlight covers the
#   whole chunk and the user sees a giant useless rectangle. 2500
#   chars is roughly a multi-paragraph passage; longer is almost
#   always the "I'm citing the whole chunk because I'm not sure where
#   the support is" pattern.
PARAPHRASE_OVERLAP_THRESHOLD = 0.60
# Verbatim cites are loose: the model picks verbatim when it believes
# the load-bearing facts (dollar figures, entity names, fiscal years)
# come directly from the source. Dropped 0.85 → 0.70 on 2026-05-12
# after audit showed legitimate verbatim cites at 0.82 and 0.68 being
# rejected (cite #15 / cite #16). The 0.85 bar fired on cases where
# the model picked a span containing MOST of the claim's content
# words but the trailing few words spilled past span_end; relaxing
# accepts those while still catching wholly-wrong cites (which score
# near 0).
VERBATIM_OVERLAP_THRESHOLD = 0.70
SPAN_BREADTH_LIMIT = 2500
# Auto-clamp threshold for span_end overflow. When the model picks a
# span_end slightly past chunk_text length (off-by-one through ~5%
# of chunk length, OR ≤50 chars in absolute terms), the validator
# clamps to the chunk length and proceeds. Larger overflows still
# reject with the chunk_text_length echo so the model can self-correct.
# Empirically, off-by-1 to off-by-50 was ~half the span-out-of-range
# failures in the 2026-05-12 audit — pure model imprecision, not a
# sign the cite is fundamentally wrong.
SPAN_END_CLAMP_ABS = 50
SPAN_END_CLAMP_RATIO = 0.05


# Currency tokens in the claim — ONLY the $-prefixed form. Bare
# numbers in claims are usually years (2025), IDs (2573), FTEs (38.4)
# — none of which are load-bearing dollar amounts and most of which
# wouldn't appear verbatim in the cited AFR table even if the cite is
# correct. By requiring the $, we limit the check to amounts the
# model explicitly tagged as currency.
_AFR_CLAIM_CURRENCY_RE = re.compile(r"\$[\d][\d,]*(?:\.\d+)?")
# Currency in the cited span — either prefixed OR bare. AFR table
# cells drop the $ on every value ("FUND TOTAL 75,000,000.00 ..."),
# so accept both forms here and canonicalize numerically.
_AFR_CITED_NUMBER_RE = re.compile(r"\$?[\d][\d,]*(?:\.\d+)?")
# Minimum integer-digit count for the cited-span numbers we consider
# "comparable to a dollar amount". 4 digits skips ID codes (2573,
# 3010) but keeps any real dollar value ($1,000 and up).
_AFR_MIN_INTEGER_DIGITS = 4


def _numeric_value(token: str) -> str | None:
    """Canonicalize a currency-or-number token to its integer-digits
    form (commas stripped, dollar sign stripped, fractional part
    dropped). Returns None for unparseable tokens. The integer-only
    representation lets `$75,000,000` and `75,000,000.00` compare
    equal — fractional cents in the AFR table aren't load-bearing for
    claim alignment.
    """
    cleaned = token.replace("$", "").replace(",", "")
    if "." in cleaned:
        cleaned = cleaned.split(".", 1)[0]
    if not cleaned or not cleaned.isdigit():
        return None
    return cleaned


def _check_afr_alignment(cited: str, claim: str) -> str | None:
    """AFR-specific alignment check: require every substantive
    dollar amount in the claim to appear as a numerically-equivalent
    token in the cited span. English-word overlap is NOT checked
    because AFR chunks are raw table cells with minimal English
    connective tissue — the model's prose ("started", "received",
    "spent") doesn't appear in `FUND TOTAL 75,000,000.00 40,000,000.00`,
    so the regular overlap check rejected every legitimate AFR cite
    in the 2026-05-12 audit (11 of 19 failures).
    """
    n_cited = _normalize_for_match(cited)
    n_claim = _normalize_for_match(claim)
    # Build the set of numeric values present in the cited span (both
    # `$X` and bare `X` forms accepted on the cited side).
    cited_values: set[str] = set()
    for tok in _AFR_CITED_NUMBER_RE.findall(n_cited):
        v = _numeric_value(tok)
        if v is not None and len(v) >= _AFR_MIN_INTEGER_DIGITS:
            cited_values.add(v)
    # Only check claim tokens that are explicitly currency ($-prefixed).
    # Skips years, IDs, FTEs, and other non-currency numbers the model
    # might mention in the same sentence.
    missing: list[str] = []
    for tok in _AFR_CLAIM_CURRENCY_RE.findall(n_claim):
        v = _numeric_value(tok)
        if v is None or len(v) < _AFR_MIN_INTEGER_DIGITS:
            continue
        if v not in cited_values:
            # Format back to human-readable for the error message.
            missing.append(f"${int(v):,}")
    if not missing:
        return None
    sample = missing[:3]
    rest = f" (and {len(missing) - 3} more)" if len(missing) > 3 else ""
    return (
        f"afr cite: dollar amount{'s' if len(missing) > 1 else ''} "
        f"{', '.join(sample)}{rest} not found in the cited AFR span. "
        "Pick a different chunk or span — the AFR row containing "
        "those figures isn't in this cited slice."
    )


def _check_alignment(
    cited: str,
    claim: str,
    confidence: str,
    doc_type: str | None = None,
) -> str | None:
    """Returns an error message if cited text doesn't support the
    claim under the given confidence, or None if it does. Does NOT
    enforce span breadth — that's a separate check on raw length
    before normalize collapses the string.

    Special path for AFR chunks (doc_type=afr): defers to currency-
    only matching because AFR table cells lack the English content
    that the normal overlap check needs. See _check_afr_alignment.
    """
    if doc_type == "afr":
        return _check_afr_alignment(cited, claim)
    nc = _normalize_for_match(claim)
    nt = _normalize_for_match(cited)
    if not nc:
        # Empty claim after normalize — nothing to check. Treat as
        # pass; the schema's min_length=1 on claim_span makes this
        # only reachable if the claim was pure markdown punctuation.
        return None
    if confidence == "verbatim":
        # Fast path: strict substring after normalize. Cheapest possible
        # match. The renderer uses the same check for inline-underline
        # placement; passing here also means the chip will attach cleanly.
        if nc in nt:
            return None
        # Slow path: content-word overlap, stricter threshold than
        # paraphrase. Honors model's verbatim choice when every
        # load-bearing token (currency, fiscal year, entity name) is
        # in the cited span but a small label or summary word was
        # added at the front of the claim — e.g. "FY 2025 (Approved):"
        # prepended to an otherwise verbatim figure list.
        claim_words = _content_words(nc)
        if not claim_words:
            # Pure punctuation / short-word claim. Treat as pass — the
            # alternative is rejecting a claim that contains no
            # checkable content, which is a different kind of bug.
            return None
        cited_words = set(_content_words(nt))
        matched = sum(1 for w in claim_words if w in cited_words)
        ratio = matched / len(claim_words)
        if ratio >= VERBATIM_OVERLAP_THRESHOLD:
            return None
        return (
            f"verbatim cite: only {matched}/{len(claim_words)} content "
            f"words from the claim appear in the cited span "
            f"(ratio {ratio:.2f}, threshold {VERBATIM_OVERLAP_THRESHOLD}). "
            "Either pick a span that contains the claim's content, or "
            "downgrade to paraphrase if the wording differs even though "
            "the facts match."
        )
    # paraphrase — content-word overlap heuristic.
    claim_words = _content_words(nc)
    if not claim_words:
        # Claim has no content words (rare — pure short words or
        # punctuation). Skip the check rather than fail-open vs
        # fail-closed; the verbatim path covers exact text.
        return None
    cited_words = set(_content_words(nt))
    matched = sum(1 for w in claim_words if w in cited_words)
    ratio = matched / len(claim_words)
    if ratio >= PARAPHRASE_OVERLAP_THRESHOLD:
        return None
    return (
        f"paraphrase cite: only {matched}/{len(claim_words)} content "
        f"words from the claim appear in the cited span "
        f"(ratio {ratio:.2f}, threshold {PARAPHRASE_OVERLAP_THRESHOLD}). "
        "The cited span likely doesn't support this claim — pick a "
        "different chunk or a different span within the same chunk."
    )


@app.post("/cite/validate", response_model_exclude_none=True)
def http_cite_validate(body: CiteValidateBody) -> CiteValidateResponse:
    """Confirm a chunk_id exists, resolve a quote to offsets (or use
    explicit offsets), check the span is in bounds, then verify the
    cited span supports the claim. See docstring on each step for the
    failure-mode breakdown.
    """
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT c.text, d.doc_type
            FROM chunks c JOIN documents d ON c.doc_id = d.doc_id
            WHERE c.chunk_id = %s
            """,
            [body.chunk_id],
        ).fetchone()

    if row is None:
        return CiteValidateResponse(ok=False, error="unknown chunk_id")

    full_text: str = row["text"] or ""
    doc_type: str | None = row["doc_type"]
    length = len(full_text)

    # Resolve quote → offsets. When BOTH quote and offsets are supplied,
    # offsets win (back-compat per the brief's disposition rule). When
    # only quote is supplied, we scan chunk.text and derive the offsets.
    resolved_span_start = body.span_start
    resolved_span_end = body.span_end
    if resolved_span_start is None or resolved_span_end is None:
        if not body.quote:
            return CiteValidateResponse(
                ok=False,
                error=(
                    "cite() requires either (span_start, span_end) OR "
                    "quote. Pass the exact quoted substring of chunk.text "
                    "as `quote` and the server derives the offsets."
                ),
                chunk_text_length=length,
            )
        idx = full_text.find(body.quote)
        if idx < 0:
            return CiteValidateResponse(
                ok=False,
                error=(
                    "quote not found in chunk.text — the substring you "
                    "supplied as `quote` does not appear verbatim in the "
                    "chunk. Pick text that exists in the chunk (read the "
                    "retrieve() result's `text` field) or retrieve a "
                    "different chunk."
                ),
                chunk_text_length=length,
            )
        resolved_span_start = idx
        resolved_span_end = idx + len(body.quote)

    # Soft-clamp claim_span to 500 chars. Past sessions had 7 cite calls
    # rejected at the 500-char boundary; truncating-and-flagging is
    # better than rejecting outright because the UI's chip-attachment
    # substring search still works on the truncated form.
    truncated_flag: bool | None = None
    claim_span_effective = body.claim_span
    if claim_span_effective is not None and len(claim_span_effective) > 500:
        claim_span_effective = claim_span_effective[:500]
        truncated_flag = True

    # Negative starts and inverted ranges remain hard errors.
    if resolved_span_start < 0 or resolved_span_end <= resolved_span_start:
        return CiteValidateResponse(
            ok=False,
            error="span out of range",
            chunk_text_length=length,
            truncated=truncated_flag,
        )
    # Auto-clamp small overflows (unchanged behavior).
    effective_span_end = resolved_span_end
    if resolved_span_end > length:
        overflow = resolved_span_end - length
        clamp_budget = max(
            SPAN_END_CLAMP_ABS, int(length * SPAN_END_CLAMP_RATIO)
        )
        if overflow <= clamp_budget:
            effective_span_end = length
        else:
            return CiteValidateResponse(
                ok=False,
                error="span out of range",
                chunk_text_length=length,
                truncated=truncated_flag,
            )

    cited = full_text[resolved_span_start:effective_span_end]
    cited_len = effective_span_end - resolved_span_start
    preview = cited[:500]

    if cited_len > SPAN_BREADTH_LIMIT:
        return CiteValidateResponse(
            ok=False,
            error=(
                f"span too broad: {cited_len} chars cited "
                f"(limit {SPAN_BREADTH_LIMIT}). Narrow span_start / "
                "span_end (or pick a shorter quote) to the specific "
                "sentence or table row that supports the claim — broad "
                "spans produce useless PDF highlights and usually "
                "indicate uncertainty about where the support is."
            ),
            chunk_text_length=length,
            cited_text_preview=preview,
            resolved_span_start=resolved_span_start,
            resolved_span_end=effective_span_end,
            truncated=truncated_flag,
        )

    if claim_span_effective is not None and body.confidence is not None:
        alignment_error = _check_alignment(
            cited, claim_span_effective, body.confidence, doc_type,
        )
        if alignment_error is not None:
            return CiteValidateResponse(
                ok=False,
                error=alignment_error,
                chunk_text_length=length,
                cited_text_preview=preview,
                resolved_span_start=resolved_span_start,
                resolved_span_end=effective_span_end,
                truncated=truncated_flag,
            )

    return CiteValidateResponse(
        ok=True,
        chunk_text_length=length,
        resolved_span_start=resolved_span_start,
        resolved_span_end=effective_span_end,
        truncated=truncated_flag,
    )
