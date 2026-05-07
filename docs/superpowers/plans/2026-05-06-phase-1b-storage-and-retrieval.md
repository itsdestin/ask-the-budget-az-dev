# Phase 1b — Storage + Retrieval Implementation Plan

> **STATUS 2026-05-07: ✓ Shipped on slice.** WS1–WS7 all merged to master against the 5-doc / 161-chunk slice. End-to-end smoke validated (`Aviation Fund balance` query surfaces s18 chunks via BM25 → dense → RRF → Voyage rerank-2.5). 373 pytest passing. Public API: `retrieval.retrieve(RetrievalRequest) → RetrievalResult` exported from `retrieval/__init__.py`.
>
> | WS | Status | Landed in |
> |---|---|---|
> | WS1 — Postgres infra + schema | ✓ shipped | `phase-1b-ws1` merge |
> | WS2 — Chunk loader + post-load validation | ✓ shipped | `phase-1b-ws2-chunk-loader` merge |
> | WS3 — Voyage embeddings | ✓ shipped | `phase-1b-ws3-embeddings` merge (`8ea409b`) |
> | WS4 — BM25 retrieval | ✓ shipped | `phase-1b-ws4-5-retrieval` merge (`c041b53`) |
> | WS5 — Dense retrieval | ✓ shipped | same merge as WS4 |
> | WS6 — RRF fusion + Voyage rerank-2.5 + `retrieve()` pipeline | ✓ shipped | `phase-1b-ws6-hybrid` merge (`1732f4c`) |
> | WS7 — Public retrieve API | ✓ implicit via `retrieval/__init__.py` | shipped with WS6 |
> | WS8 — Eval set + recall@K | **blocked on volume corpus** — runs concurrent with Phase 1c | — |
>
> WS8 deferred until volume ingest (separate workstream — see [`PROMPT-volume-ingest.md`](../../../PROMPT-volume-ingest.md)) lands; the 161-chunk slice is too narrow to give meaningful recall@K numbers. The remainder of this plan is preserved as the as-built reference; checklist items (`- [ ]`) below are NOT pending — they're shipped.

> **REFRAMED 2026-05-06.** This plan was rewritten in-place to reflect the architectural reframe captured in `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md`. Key changes from the original plan:
> 1. **Vertical-slice scope** — Phase 1b operates on the existing 5-doc / 161-chunk slice. Volume ingest is decoupled (new "Volume ingest" section); doesn't gate WS1–WS6. Reverses the original "first workstream is full Week 1 ingest" framing.
> 2. **WS7 router/decomposer collapses** — under the constrained agent pattern (D7), Claude does query routing and decomposition through tool-call sequences. WS7 becomes "expose retrieve() as MCP tool surface."
> 3. **Schema flips agency_canonical_id scalar → array** — `agency_canonical_ids TEXT[]` (D2). Migration 0001 carries the change.
> 4. **Eval (WS8) is the only workstream that genuinely needs the full corpus** — others TDD against the slice.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Phase 1a's chunks into Postgres with pgvector + ParadeDB, generate Voyage-3-large embeddings, stand up the hybrid retrieval pipeline (BM25 + dense + RRF + rerank), and prepare the surface that Phase 1c's MCP server will wrap. By the end of Phase 1b, `retrieve(query, filters) -> {chunks, top_score}` is callable from a Python REPL with metadata filters and returns the right top-20 candidates for the eval set. Synthesis, citation rendering, faithfulness verification, audit-log writes, the MCP server, and the UI are Phase 1c.

**Inputs from Phase 1a:**
- `data/chunks/<doc-id>.json` — NDJSON Chunk records ready to load
- `samples/entity-catalog.yaml` + `samples/agency-slug-aliases.yaml` — agency canonical map
- `data/fund-catalog.yaml` — fund canonical map
- `data/system-prompt-context.md` — domain primer (loaded by Phase 1c into the system prompt; not used in 1b directly)
- `phase-1a-validated-slice` git tag — Phase 1a closed under slice scope; volume ingest decoupled
- `data/chunks/MANIFEST.md` — Phase 1a → Phase 1b hand-off contract

**Phase-1a-derived items Phase 1b inherits (status updates):**

- ~~Cross-cut whole-table chunks stamp to a single agency~~ — **resolved by D2 (array column).** Migration 0001 carries the schema change; loader (WS2) restamps from existing chunk JSONs (the resolver already returns multiple matches; existing slice files use the singular field but the loader can promote to array trivially).
- ~~Acronym expansion as a server-side query-rewrite step~~ — **reframed by D7:** acronym expansion is a system-prompt instruction in the Budget MCP server's setup ("expand acronyms before calling retrieve()"). Tested in WS8 eval; revisit only if recall is poor.
- **bd2 parser shape mismatch** — out of scope for 1b retrieval. Cross-source fund catalog merge is a Phase 1.5 concern.
- **`samples/agency-slug-aliases.yaml#pending_for_phase_1` items** — surface when volume ingest covers FY15–FY22 (Phase 1.5).
- **Multi-page table reassembly** — less urgent under D2 (each chunk now stamps to all 25 agencies). Revisit if eval shows it matters.

See `data/chunks/MANIFEST.md` "Deferred to Phase 1b" section for the full deferral list.

**Scope this plan:**
- Postgres + pgvector + ParadeDB local setup
- Schema migrations matching spec §6 (with array agency stamping + funds + conversations + messages tables)
- Loader: Phase 1a chunk JSON → Postgres rows (handles scalar → array agency stamping promotion)
- Embedding pipeline (Voyage-3-large API)
- BM25 index via ParadeDB pg_search
- Hybrid retrieval (BM25 top 200 + dense top 100 → RRF → rerank → top 20)
- Metadata filters (`fiscal_year`, `doc_type`, `agency_canonical_ids`, `fund_canonical_id`, `publisher`, `is_table`)
- `retrieve(query, filters) -> {chunks, top_score}` Python entry point — production caller (the Budget MCP server in Phase 1c) imports it; eval calls it directly

**Out of scope (deferred to Phase 1c):**
- LLM synthesis (any Claude call)
- Citation rendering / `cite()` tool implementation
- The Budget MCP server itself (Phase 1c WS1 — but the Python pipeline it wraps is built here)
- NLI faithfulness verifier
- Web UI
- Audit log writes (`queries`, `conversations`, `messages` tables created here, populated in 1c)

**Out of scope (deferred to Phase 2 or later):**
- Standalone companion app (Phase 2 — v1 piggybacks on running YouCoded; D3)
- Server-side query classifier / regex decomposer / FY-range extractor — collapsed under D7
- Cross-source fund catalog merge / bd2 parser revision (Phase 1.5)

**Architecture:** Postgres 16 + pgvector + ParadeDB pg_search, run locally via Docker. Python 3.12 client. Voyage Python SDK for embeddings + reranker. SQL migrations via `alembic` or hand-written `.sql` files in `db/migrations/`. Single source of truth: spec §6 schema; this plan is a faithful implementation of it.

**Tech Stack:**
- Postgres 16 (Docker container for dev)
- pgvector 0.7+
- ParadeDB pg_search 0.10+
- Voyage AI Python SDK (`voyageai>=0.2`)
- Python 3.12, `psycopg[binary]>=3.1` for the client
- `alembic>=1.13` for migrations (or plain `.sql` if migration shape doesn't justify it)

**Source spec:** `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` — §3 (data flow), §6 (schema), §9 (stack table), §11 (refusal behavior — informs threshold tuning here).

---

## File structure

Files created during Phase 1b:

| Path | Purpose | Tracked? |
|---|---|---|
| `db/docker-compose.yml` | Postgres + pgvector + ParadeDB local-dev stack | ✓ |
| `db/migrations/0001_initial_schema.sql` | documents, agencies, funds, chunks, queries, eval_runs | ✓ |
| `db/migrations/0002_indexes.sql` | HNSW (dense), pg_search (BM25), metadata btrees | ✓ |
| `db/migrations/0003_seed_catalogs.sql` | populate `agencies` + `funds` from YAML catalogs | ✓ |
| `db/connection.py` | Connection pool + helpers | ✓ |
| `db/loader.py` | Chunk JSON → SQL rows | ✓ |
| `db/embeddings.py` | Voyage embedding client + per-chunk embedding generator | ✓ |
| `retrieval/types.py` | Pydantic models: `RetrievedChunk`, `RetrievalRequest`, `RetrievalResult` | ✓ |
| `retrieval/router.py` | Query classifier: lookup / comparison / synthesis | ✓ |
| `retrieval/decomposer.py` | Comparison-query sub-query splitter | ✓ |
| `retrieval/bm25.py` | ParadeDB pg_search query helpers | ✓ |
| `retrieval/dense.py` | pgvector ANN query helpers | ✓ |
| `retrieval/rrf.py` | Reciprocal Rank Fusion | ✓ |
| `retrieval/rerank.py` | Voyage rerank-2.5 client | ✓ |
| `retrieval/pipeline.py` | Top-level: query → final top-20 chunks | ✓ |
| `eval/queries.yaml` | ~30 hand-curated eval queries (subset of spec §13 target) | ✓ |
| `eval/run_eval.py` | Runs eval set against retrieval pipeline; reports per-query metrics | ✓ |
| `tests/test_loader.py` | Loader correctness against Phase 1a fixtures | ✓ |
| `tests/test_router.py` | Classifier accuracy on hand-labeled queries | ✓ |
| `tests/test_pipeline.py` | End-to-end retrieval against seeded test DB | ✓ |

Files modified:
- `pyproject.toml` — add `psycopg[binary]`, `voyageai`, `pgvector`, `alembic`
- `.gitignore` — add `db/data/` (Postgres data volume)

Secrets:
- `.env.local` (gitignored) — `VOYAGE_API_KEY`, `DATABASE_URL`. `.env.example` committed with placeholder values.

---

## Workstream 1 — Postgres infrastructure

**Goal:** Local Postgres with pgvector + ParadeDB, schema applied, ready to receive chunks.

### Task 1.1: Local Postgres stack via Docker

**Files:**
- Create: `db/docker-compose.yml`
- Create: `db/.env.example`
- Update: `.gitignore`

- [ ] **Step 1: Compose file using ParadeDB's official image**

ParadeDB ships a Docker image bundling Postgres 16 + pgvector + pg_search pre-installed. Saves us building extensions from source.

```yaml
services:
  postgres:
    image: paradedb/paradedb:latest
    environment:
      POSTGRES_DB: askbudget
      POSTGRES_USER: askbudget
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
    volumes:
      - ./data:/var/lib/postgresql/data
    ports:
      - "5432:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U askbudget"]
```

- [ ] **Step 2: Smoke test — start stack + verify extensions**

```bash
cd db && docker compose up -d
psql $DATABASE_URL -c "CREATE EXTENSION IF NOT EXISTS vector; CREATE EXTENSION IF NOT EXISTS pg_search;"
psql $DATABASE_URL -c "SELECT extname, extversion FROM pg_extension;"
```

Expect rows for `vector` and `pg_search`.

- [ ] **Step 3: Document teardown / reset**

`db/README.md`: "to wipe local DB: `docker compose down -v`". Helpful when iterating on schema during this workstream.

### Task 1.2: Schema migrations

**Files:**
- Create: `db/migrations/0001_initial_schema.sql`
- Create: `db/migrations/0002_indexes.sql`
- Create: `db/migrations/0003_seed_catalogs.sql`

- [ ] **Step 1: 0001 initial schema — apply the reframed spec §6**

Tables: `documents`, `agencies`, `funds`, `chunks`, `conversations`, `messages`, `queries`, `eval_runs`. Spec §6 (post-2026-05-06 reframe) has the full DDL; copy it. Note three differences from the *original* spec §6:

1. `chunks.agency_canonical_id TEXT` is now `chunks.agency_canonical_ids TEXT[] NOT NULL DEFAULT '{}'` (decision D2).
2. `funds` table is part of the initial schema (was an extension in the original plan).
3. `conversations` and `messages` tables are part of the initial schema (decision D4 — multi-turn UX).
4. `queries` table is per-assistant-turn, FK'd to `messages`, with `retrieve_calls` and `cite_calls` JSONB columns recording the agent's tool-call sequence — different shape from the original `queries` schema.

- [ ] **Step 2: 0002 indexes**

```sql
-- Dense vector
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);

-- BM25 via pg_search
CREATE INDEX chunks_bm25 ON chunks USING bm25 (chunk_id, text)
  WITH (key_field = 'chunk_id');

-- Metadata filters
CREATE INDEX chunks_fiscal_year ON chunks (fiscal_year);
CREATE INDEX chunks_doc_type ON chunks (doc_type);
CREATE INDEX chunks_publisher ON chunks (publisher);
CREATE INDEX chunks_agency_ids_gin ON chunks USING gin (agency_canonical_ids);
CREATE INDEX chunks_fund_id ON chunks (fund_canonical_id);
CREATE INDEX chunks_fund_mentions_gin ON chunks USING gin (fund_mentions);
CREATE INDEX chunks_is_table ON chunks (is_table);

-- Documents lookup
CREATE INDEX documents_pub_type_fy ON documents (publisher, doc_type, fiscal_year);

-- Messages lookup
CREATE INDEX messages_conversation_created ON messages (conversation_id, created_at);
CREATE INDEX queries_message ON queries (message_id);
```

The agency + fund GIN indexes are load-bearing for the array-filter pattern: `WHERE 'agency:adc' = ANY(agency_canonical_ids)` uses `chunks_agency_ids_gin`.

- [ ] **Step 3: 0003 seed catalogs**

Loads `samples/entity-catalog.yaml` and `data/fund-catalog.yaml` into the `agencies` and `funds` tables. Non-trivial enough to be a Python script that emits SQL `INSERT`s, not raw SQL — runs once, output committed as `0003_seed_catalogs.sql`. Re-runnable on fresh DB.

- [ ] **Step 4: Apply migrations + verify**

```bash
psql $DATABASE_URL -f db/migrations/0001_initial_schema.sql
psql $DATABASE_URL -f db/migrations/0002_indexes.sql
psql $DATABASE_URL -f db/migrations/0003_seed_catalogs.sql
psql $DATABASE_URL -c "SELECT COUNT(*) FROM agencies;"   # ~157
psql $DATABASE_URL -c "SELECT COUNT(*) FROM funds;"      # ~80
```

### Task 1.3: Connection pool + helper

**Files:**
- Create: `db/connection.py`
- Create: `tests/test_connection.py`

- [ ] **Step 1: Failing test — round-trip a query**

```python
def test_connection_round_trip():
    with get_connection() as conn:
        result = conn.execute("SELECT 1 AS x").fetchone()
        assert result["x"] == 1
```

- [ ] **Step 2: Implement using `psycopg.pool.ConnectionPool`**

`DATABASE_URL` from env. Pool size: 5 for local dev. Module-level singleton.

---

## Workstream 2 — Chunk loader

**Goal:** Read Phase 1a's `data/chunks/<doc-id>.json` files and insert into Postgres. Idempotent — running twice yields the same DB state.

### Task 2.1: Document + chunk insert

**Files:**
- Create: `db/loader.py`
- Create: `tests/test_loader.py`

- [ ] **Step 1: Stage chunk fixture, then failing test — load Phase 1a fixture**

> **Note 2026-05-06:** Phase 1a did NOT pre-stage chunk fixtures under `tests/fixtures/chunks/` — the slice's chunk files live in `data/chunks/` (gitignored except MANIFEST.md). Step 1.a here is to copy a real chunk file into the fixture path so the loader test has stable input. Use `data/chunks/jlbc-baseline-fy2027-s18.json` from a fresh slice run; that file is small (~80KB / 14 chunks). Phase 1a's `doc_type` was `baseline-cross-cut`, NOT `s-pdf` — adjust the assertion below accordingly.

```python
def test_load_s18_fixture():
    load_doc("tests/fixtures/chunks/jlbc-baseline-fy2027-s18.json")
    with get_connection() as conn:
        doc = conn.execute(
            "SELECT * FROM documents WHERE doc_id = 'jlbc-baseline-fy2027-s18'"
        ).fetchone()
        assert doc["publisher"] == "jlbc"
        assert doc["doc_type"] == "baseline-cross-cut"
        chunks = conn.execute(
            "SELECT * FROM chunks WHERE doc_id = 'jlbc-baseline-fy2027-s18'"
        ).fetchall()
        assert len(chunks) == 14   # slice produced 14 chunks; pin against MANIFEST.md
        assert all(c["is_table"] for c in chunks)
```

- [ ] **Step 2: Implement `load_doc(chunk_json_path)`**

Read NDJSON, validate against `Chunk` Pydantic model, insert into `documents` (one row from the manifest) + `chunks` (one row per record). Use `INSERT ... ON CONFLICT DO UPDATE` for idempotence.

> **Note 2026-05-06:** Existing slice chunk JSONs use the singular `agency_canonical_id` field. The loader must promote scalar → array on insert (`agency_canonical_ids = [agency_canonical_id] if agency_canonical_id else []`). For cross-cut chunks that should stamp multiple agencies, **the chunker is updated separately** to emit the array shape natively before re-running the slice ingest. Phase 1b can either (a) re-run the slice with the updated chunker first or (b) accept single-element arrays from existing JSONs and revisit when volume ingest happens. Recommend (a) — re-running the slice is fast (~5 min) and gives correct stamping for s18 from the start.

- [ ] **Step 3: Bulk loader for slice chunks**

```python
def load_all_chunks(chunks_dir="data/chunks"):
    for chunk_file in chunks_dir.glob("*.json"):
        load_doc(chunk_file)
```

Slice has 161 chunks; loads in seconds. Volume corpus (after the "Volume ingest" workstream below) targets ~3000+ chunks; should load in <30s with batch inserts.

### Task 2.2: Validation pass after loading

**Files:**
- Create: `db/validate.py`

- [ ] **Step 1: Sanity queries**

```python
def validate_load():
    checks = [
        ("docs > 0", "SELECT COUNT(*) > 0 FROM documents"),
        ("chunks > 0", "SELECT COUNT(*) > 0 FROM chunks"),
        ("all chunks have provenance", "SELECT COUNT(*) FROM chunks WHERE page IS NULL AND source_anchor IS NULL"),  # expect 0
        ("entity stamping rate", "SELECT COUNT(*) FILTER (WHERE array_length(agency_canonical_ids, 1) > 0) * 1.0 / COUNT(*) FROM chunks"),  # expect ≥ 0.9
        ("agency FK integrity", "SELECT COUNT(*) FROM chunks c WHERE EXISTS (SELECT 1 FROM unnest(c.agency_canonical_ids) aid WHERE aid NOT IN (SELECT agency_id FROM agencies))"),  # expect 0
        ("fund FK integrity", "SELECT COUNT(*) FROM chunks WHERE fund_canonical_id IS NOT NULL AND fund_canonical_id NOT IN (SELECT fund_id FROM funds)"),  # expect 0
    ]
    for label, sql in checks:
        ...
```

Failures here mean Phase 1a output drifted from Phase 1b's schema expectations — caught at load time, not at query time. Note the array-aware checks (FK validation iterates `unnest(agency_canonical_ids)`).

---

## Workstream 3 — Embedding pipeline

**Goal:** Generate Voyage-3-large embeddings for every chunk and store in `chunks.embedding` (vector(1024)).

### Task 3.1: Voyage client wrapper

**Files:**
- Create: `db/embeddings.py`
- Create: `tests/test_embeddings.py`

- [ ] **Step 1: Failing test — single embedding call**

```python
def test_embed_single_chunk():
    text = "The Department of Corrections received a $1.74B General Fund appropriation for FY 2025."
    vec = embed_one(text, input_type="document")
    assert len(vec) == 1024
    assert all(isinstance(v, float) for v in vec)
```

`input_type="document"` for chunk text, `input_type="query"` for queries — Voyage's two-mode behavior matters for retrieval quality.

- [ ] **Step 2: Implement using `voyageai.Client`**

Reads `VOYAGE_API_KEY` from env. Single-call helper + batch helper. Voyage's batch endpoint takes up to 128 inputs per call.

- [ ] **Step 3: Failing test — batch embeddings for chunks**

```python
def test_batch_embed_chunks():
    texts = ["short text 1", "short text 2", ..., "short text 64"]
    vecs = embed_batch(texts, input_type="document")
    assert len(vecs) == 64
    assert all(len(v) == 1024 for v in vecs)
```

- [ ] **Step 4: Cost estimate before running on full corpus**

Voyage-3-large pricing: ~$0.18 / 1M tokens for documents. Phase 1a output: ~3000 chunks × ~600 tokens avg = ~1.8M tokens. **Estimate: ~$0.32 to embed the full corpus.** Confirm before running. Cost is amortized — re-embedding only happens when the chunk text changes.

### Task 3.2: Embed-and-store loop

**Files:**
- Update: `db/embeddings.py`
- Create: `scripts/embed_corpus.py`

- [ ] **Step 1: Implement `embed_unembedded()`**

Query: `SELECT chunk_id, text FROM chunks WHERE embedding IS NULL ORDER BY chunk_id`. Batch in groups of 64. Update each via `UPDATE chunks SET embedding = $1 WHERE chunk_id = $2`. Idempotent — re-running picks up where the last run left off.

- [ ] **Step 2: Failing test against test DB**

Seed test DB with 5 chunks, run embed_unembedded, assert all 5 have embeddings. Re-run, assert no new embeddings (idempotence).

- [ ] **Step 3: Run on full corpus**

```bash
uv run python scripts/embed_corpus.py
```

Verify: `SELECT COUNT(*) FROM chunks WHERE embedding IS NULL` returns 0.

- [ ] **Step 4: HNSW index build**

The HNSW index from migration 0002 has to be built (or re-built) after embeddings populate. `REINDEX INDEX chunks_embedding_hnsw;` (or `CREATE INDEX IF NOT EXISTS` once data is present — pgvector recommends building the index after data is loaded).

---

## Workstream 4 — BM25 setup + tuning

**Goal:** ParadeDB pg_search index over `chunks.text`, queryable via SQL.

### Task 4.1: pg_search query helpers

**Files:**
- Create: `retrieval/bm25.py`
- Create: `tests/test_bm25.py`

- [ ] **Step 1: Failing test — BM25 returns the s18 chunk for "AHCCCS funds"**

```python
def test_bm25_aviation_fund():
    results = bm25_query("aviation fund balance", top_k=5)
    # s18 contains "Aviation Fund" rows; should score in top-5
    assert any("s18" in r.chunk_id for r in results)
```

- [ ] **Step 2: Implement `bm25_query(text, top_k, **filters) -> list[BM25Hit]`**

ParadeDB syntax:
```sql
SELECT chunk_id, paradedb.score(chunk_id) AS score
FROM chunks
WHERE chunk_id @@@ paradedb.match('text', %s)
  AND fiscal_year = ANY(%s)  -- when filter present
ORDER BY score DESC
LIMIT %s;
```

Filters: `fiscal_year`, `publisher`, `doc_type`, `agency_canonical_id` (single or list), `fund_canonical_id`, `is_table`. All optional. Agency filter syntax: `WHERE agency_canonical_ids && %s::text[]` (array overlap operator) — uses the `chunks_agency_ids_gin` index.

- [ ] **Step 3: Top-k = 200 default per spec §3.4**

Spec calls for BM25 top 200 → fused with dense top 100 → reranked → top 20. Expose `top_k` as a parameter; pipeline (Workstream 6) sets the right number.

---

## Workstream 5 — Dense retrieval

**Goal:** pgvector ANN query, returns top-K by cosine similarity. Mirrors BM25 helper shape.

### Task 5.1: Dense query helpers

**Files:**
- Create: `retrieval/dense.py`
- Create: `tests/test_dense.py`

- [ ] **Step 1: Failing test — dense recall on a similar phrasing**

BM25 fails on heavy paraphrase ("how much did the prison system get?" vs. "Department of Corrections appropriation"). Dense should bridge.

```python
def test_dense_paraphrase_recall():
    # Query phrased differently from chunk content
    results = dense_query("how much money did the prison system receive", top_k=20)
    # Should still surface a chunk stamped with ADC
    assert any("agency:adc" in r.agency_canonical_ids for r in results)
```

- [ ] **Step 2: Implement `dense_query(text, top_k, **filters) -> list[DenseHit]`**

```sql
SELECT chunk_id, 1 - (embedding <=> %s::vector) AS score
FROM chunks
WHERE %s  -- filter clause built from kwargs
ORDER BY embedding <=> %s::vector
LIMIT %s;
```

Query embedding generated via `embed_one(query_text, input_type="query")`.

- [ ] **Step 3: Top-k = 100 default per spec §3.4**

---

## Workstream 6 — Hybrid pipeline

**Goal:** Orchestrate BM25 + dense + RRF + rerank → final top 20.

### Task 6.1: RRF fusion

**Files:**
- Create: `retrieval/rrf.py`
- Create: `tests/test_rrf.py`

- [ ] **Step 1: Failing test — RRF math**

Reciprocal Rank Fusion: `score(d) = sum_i 1 / (k + rank_i(d))`. Standard `k = 60`. Test with two synthetic ranked lists with overlap.

- [ ] **Step 2: Implement `rrf_fuse(ranked_lists, k=60, top_k) -> list[FusedHit]`**

Merge multiple ranked candidate lists into one, deduped by chunk_id, scored by RRF. Spec §3.4 hints at "slight weight toward BM25 for lookup-type sub-queries" — implement as an optional per-list weight (default 1.0; pipeline can raise BM25's weight when query type is lookup).

### Task 6.2: Voyage reranker

**Files:**
- Create: `retrieval/rerank.py`
- Create: `tests/test_rerank.py`

- [ ] **Step 1: Voyage rerank-2.5 client**

```python
def rerank(query: str, candidates: list[Chunk], top_k: int = 20) -> list[RerankedChunk]:
    response = voyage_client.rerank(
        query=query,
        documents=[c.text for c in candidates],
        model="rerank-2.5",
        top_k=top_k,
    )
    return [RerankedChunk(chunk=candidates[r.index], score=r.relevance_score) for r in response.results]
```

- [ ] **Step 2: Cost note**

Voyage rerank-2.5 pricing: ~$0.05 / 1k requests, where each request is one query against ≤ 1k docs. Phase 1b sends 50 candidates per query; eval set has ~30 queries → < $0.01 per eval run. Production traffic still cheap.

### Task 6.3: Top-level retrieval pipeline

**Files:**
- Create: `retrieval/pipeline.py`
- Create: `tests/test_pipeline.py`

- [ ] **Step 1: Define `RetrievalRequest` + `RetrievalResult`**

```python
class RetrievalRequest(BaseModel):
    query: str
    fiscal_year: list[int] | None = None
    doc_type: list[str] | None = None
    publisher: list[str] | None = None
    agency_canonical_id: list[str] | None = None
    fund_canonical_id: list[str] | None = None
    is_table: bool | None = None
    top_k: int = 20

class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk]   # top_k
    top_score: float                # max reranker score across results — drives refusal threshold check (spec §11)
    reranker_scores: list[float]
```

> **Note 2026-05-06:** No `query_type` / `sub_queries` fields. The constrained agent pattern (D7) puts routing and decomposition in Claude's reasoning layer, not in this Python pipeline. Each `retrieve()` call is one query with optional filters — comparison queries surface as multiple separate calls from Claude.

- [ ] **Step 2: Failing test — single-query retrieval against the slice**

```python
def test_pipeline_aviation_fund():
    result = retrieve(RetrievalRequest(query="balance of the Aviation Fund"))
    top = result.chunks[0]
    assert "Aviation" in top.text
    assert top.fund_canonical_id == "fund:aviation"
    assert top.is_table  # should win on the s18 cross-cut chunk
    assert result.top_score > 0.3  # above placeholder refusal threshold
```

- [ ] **Step 3: Implement pipeline**

```python
def retrieve(req: RetrievalRequest) -> RetrievalResult:
    bm25_hits = bm25_query(req.query, top_k=200, **req.filters)
    dense_hits = dense_query(req.query, top_k=100, **req.filters)
    fused = rrf_fuse([bm25_hits, dense_hits], top_k=50)
    fused_chunks = load_chunk_text(fused)
    reranked = rerank(req.query, fused_chunks, top_k=req.top_k)
    return RetrievalResult(
        chunks=reranked,
        top_score=max((c.score for c in reranked), default=0.0),
        reranker_scores=[c.score for c in reranked],
    )
```

Single function; no classifier, no decomposer. Comparison-query handling is Claude's job in Phase 1c via multiple `retrieve()` tool calls.

---

## Workstream 7 — Retrieval API surface

**Goal:** Wrap the WS6 pipeline in a stable Python entry point that the Phase 1c MCP server (the production caller) and the WS8 eval harness will both import. Keep the surface small — under the constrained agent pattern (D7), routing and decomposition aren't here.

**Reframed 2026-05-06.** Original WS7 was "regex classifier + FY-range decomposer + sub-query merge logic" (~150 lines). Collapsed to "publish a clean `retrieve(query, filters)` entry point." Phase 1c WS1 (Budget MCP server) wraps this; Claude in YouCoded sessions calls the MCP tool which calls this Python function.

### Task 7.1: Confirm `retrieve()` is import-clean

**Files:**
- Update: `retrieval/__init__.py` (re-export `retrieve`, `RetrievalRequest`, `RetrievalResult`)

- [ ] **Step 1: Verify Phase 1c can import the entry point**

```python
# What the Phase 1c MCP server will do:
from retrieval import retrieve, RetrievalRequest

result = retrieve(RetrievalRequest(
    query="Aviation Fund balance",
    fiscal_year=[2027],
    fund_canonical_id=["fund:aviation"],
))
```

No new code; just confirm the import surface is clean and the type hints are sufficient for the MCP tool wrapper to consume.

> **Routing + decomposition NOT in Phase 1b.** Removed 2026-05-06: regex classifier, FY-range decomposer, sub-query merge logic. Decision D7 puts these in Claude's reasoning layer via the constrained agent pattern. Claude in YouCoded sessions calls `retrieve()` one or more times per turn; the MCP server's system prompt instructs it on routing logic ("expand acronyms; require explicit FY for comparisons; pick narrow filters when possible").

---

## Workstream 8 — Retrieval validation

**Goal:** Curate eval set, evaluate the pipeline against it, calibrate refusal threshold, document the retrieval API contract for Phase 1c.

> **Note 2026-05-06:** WS8 is **the only Phase 1b workstream that genuinely needs the full corpus.** WS1–WS7 TDD against the slice. WS8's recall numbers only hit their target after volume ingest (see "Volume ingest" section below) has loaded the full Week-1 + first-FY corpus across all four publishers.

### Task 8.1: Curate eval queries

**Files:**
- Create: `eval/queries.yaml`

- [ ] **Step 1: Curate ~30 queries across the three types**

```yaml
- id: q-001
  query: "What was the FY24 General Fund appropriation for ADC?"
  type: lookup
  expected_chunks_must_include:
    - {doc_type: "approps-report", fiscal_year: 2024, agency: "agency:adc"}
  expected_refusal: false

- id: q-014
  query: "How did corrections appropriations change between FY23 and FY25?"
  type: comparison
  expected_chunks_must_include:
    - {doc_type: "approps-report", fiscal_year: 2023, agency: "agency:adc"}
    - {doc_type: "approps-report", fiscal_year: 2025, agency: "agency:adc"}
  expected_refusal: false

- id: q-027
  query: "What's the right tax policy for Arizona?"
  type: out-of-scope
  expected_refusal: true
```

Mix per spec §2: ~60% lookup, ~30% comparison, ~10% synthesis + out-of-scope. Each query annotated with `expected_chunks_must_include` (publisher + doc_type + agency + FY constraints) so retrieval can be scored mechanically. The `type` field is informational only (no classifier consumes it); it helps scope the eval mix and lets us compute per-type recall.

### Task 8.2: Eval runner

**Files:**
- Create: `eval/run_eval.py`

- [ ] **Step 1: Implement eval harness (single-shot mode)**

For each query in `eval/queries.yaml`:
1. Call `retrieve(RetrievalRequest(query=q.query))` — bypasses the agent; calls the Python pipeline directly for deterministic measurement.
2. Compare top-K chunks against `expected_chunks_must_include`. A query passes citation recall if every expected (publisher × doc_type × agency × FY) constraint is satisfied by at least one returned chunk.
3. Record per-query: top-K chunk IDs, recall@5, recall@20, latency, top reranker score (for refusal threshold tuning).

Output: `eval/results/<git_sha>.json` + a Markdown summary.

- [ ] **Step 2: First eval run + report**

Run eval (against the volume-ingested corpus); write `docs/superpowers/investigations/2026-MM-DD-phase-1b-eval.md` with:
- Total queries, type breakdown
- Recall@5 / Recall@20 overall and per type
- Per-query failures with hypothesized cause (chunk-shape / extractor / corpus coverage / acronym expansion / filter logic)

Pass bar: **Recall@20 ≥ 80% on lookup queries** (the simplest case). Comparison + synthesis recall is informational; their final accuracy depends on the agent (Phase 1c).

If pass bar isn't met, failures point at the work to do — chunk-shape revisit, extractor coverage gap, missing volume in the corpus, or filter logic.

### Task 8.3: Refusal threshold calibration

**Files:**
- Update: `retrieval/pipeline.py`
- Update: `eval/queries.yaml` (add intentional-refusal cases if not already present)

Spec §11 says the threshold is calibrated during Phase 1 against the eval set; placeholder = `top_score < 0.3` → `refusal_no_retrieval`.

- [ ] **Step 1: Compute optimal threshold**

For each candidate threshold in [0.1, 0.2, 0.3, 0.4, 0.5]:
- Count out-of-scope queries that would (correctly) refuse.
- Count valid queries that would (incorrectly) refuse.
- Pick the threshold maximizing correct refusals minus incorrect refusals.

- [ ] **Step 2: Lock chosen threshold + document rationale**

Constant in `retrieval/pipeline.py` named `REFUSAL_RERANKER_THRESHOLD`. Comment cites the eval-run artifact that justified it. Phase 1c's MCP server reads this constant — the system prompt instructs Claude to refuse when `top_score < REFUSAL_RERANKER_THRESHOLD`.

### Task 8.4: Hand-off package for Phase 1c

- [ ] **Step 1: Document the retrieval API contract**

`docs/retrieval-api.md` — the `RetrievalRequest` / `RetrievalResult` shapes, what filters are supported, what the chunks look like coming out, refusal threshold semantics. Phase 1c's MCP server reads this as its input contract.

- [ ] **Step 2: Tag `phase-1b-complete`**

After eval pass bar is met. Phase 1c starts here.

---

## Volume ingest (decoupled workstream)

**Goal:** Ingest the full v1 corpus (all four publishers, most-recent FY) so WS8's eval can measure recall against representative volume. Runs concurrently with or after WS1–WS7; doesn't gate them.

**Reframed 2026-05-06.** Originally the Phase 1b plan said "full Week 1 ingest is the first workstream" — that path delays the storage/retrieval code by 2–3 weeks for re-running the existing Phase 1a orchestrator. Reversed under decision D1 (vertical slice). The orchestrator is proven; volume ingest is now a parallel track with no code dependencies on WS1–WS7.

### Target corpus for v1

Per decision D12, v1 dogfood needs all four publishers covered for the spec §3 comparison use case to work:

- **JLBC FY27 baseline** — 15 cross-cut s-PDFs + 110 per-agency PDFs (most already on disk in `samples/raw-pdfs/` from Phase 0)
- **JLBC FY26 approps** — 28 cross-cut PDFs (bh*, bd*, page-keyed)
- **Legislature FY26 budget bill (SB 1735)** — already in slice
- **Governor FY27** — State Agency Detail (636 pages) + Sources & Uses (919 pages)
- **AGAO FY25 AFR** — 181 pages, tagged
- **Primers** — writing draft + Gov glossary (system-prompt context, not retrieved)

Multi-year backfill (FY15–FY24) is Phase 1.5 — same orchestrator, more URLs.

### Tasks

**Files:**
- Update: `scripts/run_phase_1a_slice.py` (rename to `run_volume_ingest.py`; widen the doc list; consume `ingest/discovery.py` for TOC-driven URL enumeration)
- Update: `scripts/sweep_entities.py` (add `--root` arg; existing path globs assume the old phase-0 layout)

- [ ] **Step 1: Adapt orchestrator to walk discovery for full Week-1 list**

`ingest/discovery.py` already has `walk_baseline_links()`, `walk_approps_toc()`, `walk_agency_index()`. Wire them into the orchestrator so doc lists come from the live TOC PDFs rather than hardcoded slice constants.

- [ ] **Step 2: Add Gov SAD + AGAO AFR pipelines**

These weren't in the slice. Use the OpenDataLoader path for both (tagged PDFs per Phase 0 stack decisions). Confirm extractor outputs land in `data/extractor-output/<doc-id>/` in the same shape as MinerU outputs.

- [ ] **Step 3: Run end-to-end**

```bash
uv run python scripts/run_volume_ingest.py
uv run python db/loader.py
uv run python scripts/embed_corpus.py
```

Expected: ~3000 chunks, ~$0.32 embedding cost, runs unattended for 1–2 hours.

- [ ] **Step 4: Verify volume ingest with `db/validate.py`**

Same checks as the slice load. Stamping rate ≥ 90%, FK integrity, all chunks have provenance.

### When to run

Two valid sequencings:

- **Concurrent with WS1–WS7:** start volume ingest as a background process while building infra. Re-run the loader as new chunks arrive. Lets WS8 fire as soon as WS1–WS7 + ingest both complete.
- **After WS1–WS7:** simpler bookkeeping; WS1–WS7 finalize against the slice, then volume ingest is a single batch run before WS8.

Either works. Concurrent is faster to v1; sequential is simpler to track.

---

## Deferred decisions (explicit non-goals)

- **LLM provider abstraction (`LLMProvider` interface).** Phase 1c. Storage/retrieval is provider-agnostic.
- **Synthesis call / Budget MCP server.** Phase 1c WS1.
- **Faithfulness verifier.** Phase 1c.
- **Per-query audit log writes.** Schema is created here (`queries`, `conversations`, `messages` tables); writes happen in 1c.
- **Index restatement / AFR Note pairing for retrieval boost.** Phase 1a Workstream 5 Task 5.3 captured the metadata; turning that into a retrieval boost is a Phase 2 enhancement.
- **Per-row metadata for tabular chunks.** Currently the chunk is the table; the row is identified at citation time (Phase 1c). If retrieval ever needs to filter by row-level metadata (e.g., "fund + agency where amount > $50M"), that's a Phase 2 enhancement.
- **Cost optimization.** Voyage-3-large + rerank-2.5 are top-quality but not cheapest. Switching to lower-cost embedding (Voyage-3-lite) or a self-hosted reranker is post-MVP.
- **Hybrid score combination beyond RRF.** RRF is the well-attested default. Per-type weighting (boost BM25 for lookups, dense for synthesis) is supported via the per-list weight parameter; tuning happens during 8.2 if recall is mixed.
- **Server-side query classifier / regex decomposer.** Removed under D7. Claude does this work in Phase 1c.
- **Multi-year backfill ingest (FY15–FY24).** Phase 1.5; same orchestrator with more URLs.

## What "Phase 1b done" means

By the end of Phase 1b:

- Postgres + pgvector + ParadeDB running locally with reframed-spec-§6 schema applied (array agency stamping, funds + conversations + messages tables)
- Volume ingest run; ~3000 chunks across all four publishers loaded; embeddings populated (~$0.32 corpus cost)
- BM25 + dense retrieval helpers working with metadata filters (including array-overlap agency filter)
- RRF fusion + Voyage rerank-2.5 wired into a top-level `retrieve(query, filters) -> {chunks, top_score}` Python API
- Eval set (~30 queries) ≥ 80% recall@20 on lookup queries; eval results doc written
- Refusal threshold calibrated and locked
- Retrieval API contract documented at `docs/retrieval-api.md`
- `phase-1b-complete` tag created

Phase 1c then takes the retrieval API as a black box and builds the LLM synthesis + faithfulness verifier + UI on top.

## Pointer to the conversation

Decision history for Phase 1 split + the Postgres-vs-alternative-stores choice (declined alternatives: pure pgvector without ParadeDB, pure ParadeDB without pgvector, separate vector store + relational store) lives in the spec §9 stack table and the 2026-05-06 cleanup conversation.
