-- 0002_indexes.sql
-- Phase 1b Workstream 1, Task 1.2 Step 2.
--
-- Indexes for retrieval queries. Applied AFTER 0001_initial_schema.sql; idempotent
-- via IF NOT EXISTS so re-running on a populated DB is safe.

-- ---------------------------------------------------------------------------
-- Dense vector index (HNSW for approximate nearest neighbor)
-- ---------------------------------------------------------------------------
-- Built with cosine ops because Voyage-3-large embeddings are L2-normalized;
-- cosine and inner-product ranking are equivalent on unit vectors but cosine_ops
-- is what the spec calls for and the more common default.
--
-- HNSW parameters: pgvector defaults (m=16, ef_construction=64). Tunable later
-- if eval shows recall is bottlenecked here.
CREATE INDEX IF NOT EXISTS chunks_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops);

-- ---------------------------------------------------------------------------
-- BM25 lexical index via ParadeDB pg_search
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS chunks_bm25
  ON chunks USING bm25 (chunk_id, text)
  WITH (key_field = 'chunk_id');

-- ---------------------------------------------------------------------------
-- Metadata filter indexes
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS chunks_fiscal_year ON chunks (fiscal_year);
CREATE INDEX IF NOT EXISTS chunks_doc_type    ON chunks (doc_type);
CREATE INDEX IF NOT EXISTS chunks_publisher_via_doc ON chunks (doc_id);  -- publisher lives on documents; join via doc_id

-- GIN indexes for array-overlap filters (load-bearing — see decision D2).
-- Filter syntax: WHERE agency_canonical_ids && %s::text[]  (uses chunks_agency_ids_gin)
CREATE INDEX IF NOT EXISTS chunks_agency_ids_gin
  ON chunks USING gin (agency_canonical_ids);

CREATE INDEX IF NOT EXISTS chunks_fund_mentions_gin
  ON chunks USING gin (fund_mentions);

CREATE INDEX IF NOT EXISTS chunks_fund_id   ON chunks (fund_canonical_id);
CREATE INDEX IF NOT EXISTS chunks_is_table  ON chunks (is_table);

-- ---------------------------------------------------------------------------
-- Documents lookup
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS documents_pub_type_fy ON documents (publisher, doc_type, fiscal_year);

-- ---------------------------------------------------------------------------
-- Conversation + message + query lookup paths
-- ---------------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS messages_conversation_created
  ON messages (conversation_id, created_at);

CREATE INDEX IF NOT EXISTS queries_message ON queries (message_id);
