# Phase 1b — Storage + Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist Phase 1a's chunks into Postgres with pgvector + ParadeDB, generate Voyage-3-large embeddings, and stand up the hybrid retrieval pipeline (BM25 + dense + RRF + rerank). By the end of Phase 1b, we should be able to call `retrieve(query) -> list[Chunk]` from a Python REPL and get top-20 candidate chunks back with the right content for the spec §13 eval queries. Synthesis, faithfulness verification, and the UI are Phase 1c.

**Inputs from Phase 1a:**
- `data/chunks/<doc-id>.json` — NDJSON Chunk records ready to load
- `samples/entity-catalog.yaml` + `samples/agency-slug-aliases.yaml` — agency canonical map
- `data/fund-catalog.yaml` — fund canonical map
- `data/system-prompt-context.md` — domain primer (loaded by Phase 1c, not used here)
- `phase-1a-validated-slice` git tag (Phase 1a closed under slice scope, not full corpus — see "Slice-scope caveat" below)
- `data/chunks/MANIFEST.md` — Phase 1a → Phase 1b hand-off contract; lists what's in scope, what was deferred, integration findings, chunk-shape observations

**Slice-scope caveat:** Phase 1a closed under a validated-slice scope (5 docs / 161 chunks) rather than the full Week 1–3 corpus the original Phase 1a plan envisioned. The pipeline (download → MinerU/DOCX → chunk → stamp) is proven end-to-end on real source, but volume targets ("5+ fiscal years", "~3000+ chunks") are deferred. Phase 1b's first workstream should be **full Week 1 corpus ingest** (~50 PDFs the orchestrator at `scripts/run_phase_1a_slice.py` already supports — adapt it to a wider doc list) so storage + retrieval is plumbed against representative volume. Phase-1a-derived items Phase 1b inherits:

- `funds/parser.py::parse_s18_table` works on s18 but yields 0 rows on bd2 (different column layout). bd2 parser revision needed before fund catalog can be cross-source merged.
- Cross-cut whole-table chunks (chunk-shape D6) stamp to a SINGLE `agency_canonical_id` — the first match the resolver sees alphabetically — even when the table lists ~25 agencies. Per-row stamping or section-by-agency chunk subdivision is open.
- Source documents use spelled-out names ("Department of Corrections"); the Phase 1a smoke queries used acronyms ("ADC", "ADOT", "GAA") that don't tokenize against in-corpus text under TF-IDF. Acronym expansion (likely query-rewrite using the system-prompt context's acronyms section) is a Phase 1b retrieval concern.
- `samples/agency-slug-aliases.yaml#pending_for_phase_1` items still open — require FY15-FY22 ingest to resolve naturally. Will surface when Phase 1b ingests prior years.

See `data/chunks/MANIFEST.md` "Deferred to Phase 1b" section for the full deferral list.

**Scope this plan:**
- Postgres + pgvector + ParadeDB local setup
- Schema migrations matching spec §6 (extended with a `funds` table)
- Loader: Phase 1a chunk JSON → Postgres rows
- Embedding pipeline (Voyage-3-large API)
- BM25 index via ParadeDB pg_search
- Hybrid retrieval (BM25 top 200 + dense top 100 → RRF → rerank → top 20)
- Query routing classifier (lookup / comparison / synthesis)
- Sub-query decomposition for comparison queries
- Metadata filters (`fiscal_year`, `doc_type`, `agency_canonical_id`)

**Out of scope (deferred to Phase 1c):**
- LLM synthesis call
- Tool-call citation emission
- NLI faithfulness verifier
- Web UI
- Companion app
- Audit log writes (table created here, but only retrieval rows; query-side rows happen in 1c)

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

- [ ] **Step 1: 0001 initial schema — copy spec §6 verbatim**

Tables: `documents`, `agencies`, `chunks`, `queries`, `eval_runs`. Spec §6 has the full DDL; copy it.

Plus one **extension** to spec §6: a `funds` table (Phase 1a built the catalog; Phase 1b persists it).

```sql
CREATE TABLE funds (
  fund_id TEXT PRIMARY KEY,             -- e.g., 'aviation'
  canonical_name TEXT NOT NULL,         -- 'Aviation Fund'
  short_name TEXT,
  aliases TEXT[] NOT NULL DEFAULT '{}',
  present_in TEXT[] NOT NULL DEFAULT '{}'  -- ['jlbc-s18', 'jlbc-bd2', 'agao-afr']
);

ALTER TABLE chunks ADD COLUMN fund_canonical_id TEXT REFERENCES funds(fund_id);
ALTER TABLE chunks ADD COLUMN fund_mentions TEXT[] NOT NULL DEFAULT '{}';
```

`fund_mentions` carries the list of all funds mentioned in a chunk (chunk-shape narrative chunks may touch many funds; one is primary, others are mentioned). Phase 1a Workstream 3 Task 3.4 step 3 produces this.

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
CREATE INDEX chunks_agency ON chunks (agency_canonical_id);
CREATE INDEX chunks_fund ON chunks (fund_canonical_id);
CREATE INDEX chunks_is_table ON chunks (is_table);

-- Documents lookup
CREATE INDEX documents_pub_type_fy ON documents (publisher, doc_type, fiscal_year);
```

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

- [ ] **Step 3: Bulk loader for full Phase 1a output**

```python
def load_all_phase_1a(chunks_dir="data/chunks"):
    for chunk_file in chunks_dir.glob("*.json"):
        load_doc(chunk_file)
```

Runtime expectation: ~3000 chunks should load in < 30 seconds with batch inserts. (Slice has 161 chunks; full-corpus volume target carries forward from the original Phase 1a plan.)

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
        ("entity stamping rate", "SELECT COUNT(*) FILTER (WHERE agency_canonical_id IS NOT NULL) * 1.0 / COUNT(*) FROM chunks"),  # expect ≥ 0.9
        ("foreign key integrity", "SELECT COUNT(*) FROM chunks WHERE agency_canonical_id IS NOT NULL AND agency_canonical_id NOT IN (SELECT agency_id FROM agencies)"),  # expect 0
    ]
    for label, sql in checks:
        ...
```

Failures here mean Phase 1a output drifted from Phase 1b's schema expectations — caught at load time, not at query time.

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

Filters: `fiscal_year`, `publisher`, `doc_type`, `agency_canonical_id`, `fund_canonical_id`, `is_table`. All optional.

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
    # Should still surface the ADC chunk
    assert any(r.agency_canonical_id == "agency:adc" for r in results)
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
    query_type: Literal["lookup", "comparison", "synthesis"] | None = None  # auto if None
    fiscal_year: list[int] | None = None
    doc_type: list[str] | None = None
    agency_canonical_id: list[str] | None = None
    top_k: int = 20

class RetrievalResult(BaseModel):
    chunks: list[RetrievedChunk]   # top_k
    sub_queries: list[SubQueryResult] | None = None  # for comparison queries
    classified_type: Literal["lookup", "comparison", "synthesis"]
    reranker_scores: list[float]
```

- [ ] **Step 2: Failing test — end-to-end retrieval against a 5-eval-query subset**

```python
def test_pipeline_aviation_fund():
    result = retrieve(RetrievalRequest(query="What's the balance of the Aviation Fund?"))
    top = result.chunks[0]
    assert "Aviation" in top.text
    assert top.fund_canonical_id == "fund:aviation"
    assert top.is_table  # should win on the s18 cross-cut chunk
```

- [ ] **Step 3: Implement pipeline**

```python
def retrieve(req: RetrievalRequest) -> RetrievalResult:
    classified = classify(req.query) if req.query_type is None else req.query_type
    if classified == "comparison":
        sub_queries = decompose(req.query)
        sub_results = [_retrieve_single(sq, req.filters) for sq in sub_queries]
        # Merge sub-query results, preserving sub-query attribution
        chunks = merge_sub_results(sub_results, total_k=req.top_k)
        return RetrievalResult(chunks=chunks, sub_queries=sub_results, classified_type=classified, ...)
    else:
        chunks = _retrieve_single(req.query, req.filters, top_k=req.top_k)
        return RetrievalResult(chunks=chunks, classified_type=classified, ...)

def _retrieve_single(query, filters, top_k=20):
    bm25_hits = bm25_query(query, top_k=200, **filters)
    dense_hits = dense_query(query, top_k=100, **filters)
    fused = rrf_fuse([bm25_hits, dense_hits], top_k=50)
    fused_chunks = load_chunk_text(fused)  # hydrate from DB
    reranked = rerank(query, fused_chunks, top_k=top_k)
    return reranked
```

---

## Workstream 7 — Query routing

**Goal:** Classifier that picks `lookup` / `comparison` / `synthesis` per spec §3.4. Decomposer that splits comparison queries into per-FY sub-queries.

### Task 7.1: Hand-labeled training set

**Files:**
- Create: `eval/queries.yaml`

Spec §13 calls for ~50 hand-curated eval queries by Phase 1 launch. Phase 1b builds ~30; Phase 1c expands.

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
  expected_decomposition:
    - {topic: "corrections appropriations", fiscal_year: 2023}
    - {topic: "corrections appropriations", fiscal_year: 2025}
  expected_refusal: false

- id: q-027
  query: "What's the right tax policy for Arizona?"
  type: out-of-scope
  expected_refusal: true
```

Mix per spec §2: ~60% lookup, ~30% comparison, ~10% synthesis + out-of-scope. Each query annotated with `expected_chunks_must_include` (publisher + doc_type + agency + FY constraints) so retrieval can be scored mechanically.

### Task 7.2: Classifier

**Files:**
- Create: `retrieval/router.py`
- Create: `tests/test_router.py`

Spec §9 calls for ~150 lines, custom classifier. Probably regex + keyword heuristics for v1; LLM-classifier later.

- [ ] **Step 1: Failing tests against hand-labeled queries**

```python
def test_classify_examples():
    # Comparison signals: "compare", "between X and Y", "change", "difference"
    assert classify("How did corrections change between FY23 and FY25?") == "comparison"
    assert classify("What's the difference between Gov rec and GAA for ADE?") == "comparison"
    # Synthesis signals: "summarize", "overview", "what are the major"
    assert classify("Summarize fiscal pressures in the FY25 baseline") == "synthesis"
    assert classify("What are the major changes in the AFR notes between 2022 and 2024?") == "comparison"  # 'between' wins
    # Lookup default
    assert classify("What was the FY24 GF appropriation for ADC?") == "lookup"
    # Out-of-scope
    assert classify("What's the right tax policy?") == "out_of_scope"
```

- [ ] **Step 2: Implement classifier**

Regex tier first:
- `\bbetween\b.*\band\b` → comparison
- `\b(compare|comparison|change|changed|difference|vs)\b` → comparison
- `\b(summarize|overview|major|trends?)\b` → synthesis
- `\b(should|recommend|policy|opinion)\b` → out_of_scope
- default → lookup

Test against the labeled set; iterate on keywords until ≥ 90% accuracy on hand-labeled queries. Document misclassified queries in `eval/router-misses.md` for later LLM-classifier upgrade.

### Task 7.3: Comparison query decomposer

**Files:**
- Create: `retrieval/decomposer.py`
- Create: `tests/test_decomposer.py`

Per spec §5 example: `"How did ADC General Fund appropriations change between FY23 and FY25?"` → `[{topic: "ADC General Fund appropriations", fiscal_year: 2023}, {...fiscal_year: 2025}]`.

- [ ] **Step 1: Failing test — extract FY range from "between X and Y"**

```python
def test_decompose_fy_range():
    result = decompose("How did corrections appropriations change between FY23 and FY25?")
    assert len(result.sub_queries) == 2  # or 3 (FY23, FY24, FY25) — design choice
    assert all("corrections" in sq.topic for sq in result.sub_queries)
    assert {sq.fiscal_year for sq in result.sub_queries} == {2023, 2025}
```

- [ ] **Step 2: Implement decomposer**

Two regex patterns:
- "between FY(N) and FY(M)" → sub-queries for FY N and FY M (start with endpoints only; if eval shows queries expect intermediate years, expand)
- "in FY(N) vs FY(M)" → same

Topic = the rest of the query with the fiscal-year clause removed. Per spec §16 open question: "When user says 'compare X' without specifying years, do we fan out across all years? Last 3?" — punt for v1; require explicit years. Surface a refusal `"Need explicit fiscal years for comparison queries"` if absent.

---

## Workstream 8 — Retrieval validation

**Goal:** Evaluate the pipeline against the curated eval set.

### Task 8.1: Eval runner

**Files:**
- Create: `eval/run_eval.py`

- [ ] **Step 1: Implement eval harness**

For each query in `eval/queries.yaml`:
1. Call `retrieve(query)`.
2. Compare top-K chunks against `expected_chunks_must_include`. A query passes citation recall if every expected (publisher × doc_type × agency × FY) constraint is satisfied by at least one returned chunk.
3. Record per-query: classified type, sub-queries, top-K chunk IDs, recall@5, recall@20, latency.

Output: `eval/results/<git_sha>.json` and a Markdown summary.

- [ ] **Step 2: First eval run + report**

Run eval; write `docs/superpowers/investigations/2026-MM-DD-phase-1b-eval.md` with:
- Total queries, type breakdown
- Recall@5 / Recall@20 overall and per type
- Per-query failures with hypothesized cause (chunk-shape issue / extractor issue / classifier issue / corpus-coverage issue)

Pass bar: **Recall@20 ≥ 80% on lookup queries** (the simplest case). Comparison + synthesis recall is informational for now; their final accuracy depends on synthesis quality (Phase 1c).

If pass bar isn't met, the failures point at the work to do — could be chunk-shape (revisit chunking layer in 1a worktree), extractor coverage (re-extract a problematic doc), embedding mode (forgot to use input_type="query"), or filter logic.

### Task 8.2: Refusal threshold calibration

**Files:**
- Update: `retrieval/pipeline.py`
- Update: `eval/queries.yaml` (add intentional-refusal cases if not already present)

Spec §11 says the threshold is calibrated during Phase 1 against the eval set; placeholder = reranker score < 0.3 → `refusal_no_retrieval`.

- [ ] **Step 1: Compute optimal threshold**

For each candidate threshold in [0.1, 0.2, 0.3, 0.4, 0.5]:
- Count out-of-scope queries that would (correctly) refuse.
- Count valid queries that would (incorrectly) refuse.
- Pick the threshold maximizing correct refusals minus incorrect refusals.

- [ ] **Step 2: Lock chosen threshold + document rationale**

Constant in `retrieval/pipeline.py` named `REFUSAL_RERANKER_THRESHOLD`. Comment cites the eval-run artifact that justified it.

### Task 8.3: Hand-off package for Phase 1c

- [ ] **Step 1: Document the retrieval API contract**

`docs/retrieval-api.md` — the `RetrievalRequest` / `RetrievalResult` shapes, what filters are supported, what the chunks look like coming out, refusal behavior. Phase 1c's synthesis layer reads this as its input contract.

- [ ] **Step 2: Tag `phase-1b-complete`**

After eval pass bar is met. Phase 1c starts here.

---

## Phase 1a derived open questions for Phase 1b

These are scope inputs from Phase 1a's slice run, captured here so Phase 1b's first session has them in front of it. Full list with context in `data/chunks/MANIFEST.md`.

- **Full Week 1 corpus ingest** (~50 PDFs the Phase 1a orchestrator already supports). Should be Phase 1b's first workstream — closes the volume gap before storage + retrieval work meaningfully.
- **bd2 parser shape mismatch.** `funds/parser.py::parse_s18_table` works on `s18.pdf` but yields 0 rows on `bd2.pdf` (different column layout). Without a bd2 parser revision, the fund catalog stays single-source (s18 only) and cross-source merge is impossible. Decide between: bd2-specific parser, format-tolerant unified parser, or accept single-source.
- **Cross-cut whole-table chunk-shape revisit.** Current chunks stamp to a single `agency_canonical_id` (first match in source order) even when the table lists ~25 agencies. Retrieval by agency filter won't surface non-first agencies. Decide between per-row stamping, section-by-agency chunk subdivision, or alt-shape (multi-agency stamping array). Resolve before retrieval is wired against `agency_canonical_id` filters.
- **Multi-page table reassembly across repeated headings.** s18's 13-page Funds × Agencies table emits as 13 chunks because the title heading repeats on every continuation page. Either widen the reassembly guard to ignore re-emitted same-text headings, or move reassembly to a post-pass driven by table-shape similarity rather than heading boundaries.
- **Acronym expansion for retrieval.** Source documents use spelled-out names; queries often use acronyms. TF-IDF over raw chunk text can't bridge that. Likely fix: query-rewrite step using the system-prompt context's acronyms section, OR augment chunk text with an acronyms appendix at index time.
- **`samples/agency-slug-aliases.yaml#pending_for_phase_1`** — four open items requiring FY15-FY22 ingest to resolve naturally. Will surface during full-corpus ingest.
- **`scripts/sweep_entities.py` layout incompatibility.** The Phase 0 script's hardcoded path globs (`opendataloader/*/*.md`, `mineru/*/*.md`, `docx/*/*.md`) don't match the WS6 layout (`<doc_id>/page-*.md` directly under `data/extractor-output/`). Add a `--root` argparse option (or layout normalization) before re-running for full corpus.

## Deferred decisions (explicit non-goals)

- **LLM provider abstraction (`LLMProvider` interface).** Phase 1c. Storage/retrieval is provider-agnostic.
- **Synthesis call.** Phase 1c.
- **Faithfulness verifier.** Phase 1c.
- **Per-query audit log writes.** Schema is created here (queries table); writes happen in 1c when there's a query path with results worth logging.
- **Index restatement / AFR Note pairing for retrieval boost.** Phase 1a Workstream 5 Task 5.3 captured the metadata; turning that into a retrieval boost is a Phase 2 enhancement.
- **Per-row metadata for tabular chunks.** Currently the chunk is the table; the row is identified at citation time (Phase 1c). If retrieval ever needs to filter by row-level metadata (e.g., "fund + agency where amount > $50M"), that's a Phase 2 enhancement.
- **Cost optimization.** Voyage-3-large + rerank-2.5 are top-quality but not cheapest. Switching to lower-cost embedding (Voyage-3-lite) or a self-hosted reranker is post-MVP.
- **Hybrid score combination beyond RRF.** RRF is the well-attested default. Per-type weighting (boost BM25 for lookups, dense for synthesis) is supported via the per-list weight parameter; tuning happens during 8.1 if recall is mixed.

## What "Phase 1b done" means

By the end of Phase 1b:

- Postgres + pgvector + ParadeDB running locally with schema applied
- All Phase 1a chunks loaded; embeddings populated (~$0.32 corpus cost confirmed before run)
- BM25 + dense retrieval helpers working with metadata filters
- RRF fusion + Voyage rerank-2.5 wired into a top-level `retrieve(query)` API
- Query classifier ≥ 90% accuracy on hand-labeled set; comparison decomposer working on FY-range queries
- Eval set ≥ 80% recall@20 on lookup queries; eval results doc written
- Refusal threshold calibrated and locked
- Retrieval API contract documented at `docs/retrieval-api.md`
- `phase-1b-complete` tag created

Phase 1c then takes the retrieval API as a black box and builds the LLM synthesis + faithfulness verifier + UI on top.

## Pointer to the conversation

Decision history for Phase 1 split + the Postgres-vs-alternative-stores choice (declined alternatives: pure pgvector without ParadeDB, pure ParadeDB without pgvector, separate vector store + relational store) lives in the spec §9 stack table and the 2026-05-06 cleanup conversation.
