-- 0001_initial_schema.sql
-- Phase 1b Workstream 1, Task 1.2 Step 1.
-- Source: docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md §6 (post-2026-05-06 reframe).
--
-- This migration creates extensions + tables only. Indexes go in 0002. Seeds go in 0003.

-- ---------------------------------------------------------------------------
-- Extensions
-- ---------------------------------------------------------------------------
-- pgvector for dense embeddings (Voyage-3-large, dim 1024).
CREATE EXTENSION IF NOT EXISTS vector;

-- ParadeDB pg_search for BM25 over chunk.text.
CREATE EXTENSION IF NOT EXISTS pg_search;

-- pgcrypto for gen_random_uuid() — used as the default for conversation/message/query/run UUIDs.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ---------------------------------------------------------------------------
-- Documents in the corpus
-- ---------------------------------------------------------------------------
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  publisher TEXT NOT NULL,           -- 'jlbc' | 'agao' | 'governor' | 'legislature'
  doc_type TEXT NOT NULL,            -- 'baseline-cross-cut' | 'baseline-agency' | 'approps-report' | 'afr' | 'governors-budget' | 'budget-bill' | 'primer'
  fiscal_year INT NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT,
  source_format TEXT NOT NULL,       -- 'pdf' | 'docx' (extensible to 'html', 'xml', etc.)
  source_blob_path TEXT NOT NULL,    -- where the original file lives
  page_count INT,                    -- nullable; PDF-only
  ingested_at TIMESTAMPTZ NOT NULL,
  extractor TEXT NOT NULL,           -- 'mineru-2.5' | 'opendataloader-2.4.1' | 'python-docx' | 'sonnet-vision'
  extractor_version TEXT NOT NULL
);

-- ---------------------------------------------------------------------------
-- Canonical agency map (Tier 1 entity resolution)
-- ---------------------------------------------------------------------------
CREATE TABLE agencies (
  agency_id TEXT PRIMARY KEY,                -- e.g., 'agency:adc'
  canonical_name TEXT NOT NULL,              -- 'Department of Corrections'
  short_name TEXT,                           -- 'ADC'
  aliases TEXT[] NOT NULL DEFAULT '{}'       -- alternative names observed in sources
);

-- ---------------------------------------------------------------------------
-- Canonical fund catalog (parallels agencies)
-- ---------------------------------------------------------------------------
CREATE TABLE funds (
  fund_id TEXT PRIMARY KEY,                  -- e.g., 'fund:aviation'
  canonical_name TEXT NOT NULL,              -- 'Aviation Fund'
  short_name TEXT,
  aliases TEXT[] NOT NULL DEFAULT '{}',
  present_in TEXT[] NOT NULL DEFAULT '{}'    -- ['jlbc-s18', 'jlbc-bd2', 'agao-afr']
);

-- ---------------------------------------------------------------------------
-- Chunks: the retrieval atom
-- ---------------------------------------------------------------------------
-- agency_canonical_ids is an ARRAY (decision D2 — see decisions doc) so cross-cut
-- table chunks (e.g. s18 funds×agencies) can stamp all agencies present in the
-- table rather than collapsing to alphabetical first match.
CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id),
  text TEXT NOT NULL,
  embedding vector(1024),                            -- Voyage-3-large output dim; populated in WS3
  -- Provenance is polymorphic by source format. PDF sources populate (page, bbox);
  -- non-PDF sources populate source_anchor with paragraph and cell ids. The CHECK
  -- constraint enforces that at least one provenance shape is present.
  page INT,                                          -- nullable; PDF-source chunks only
  bbox NUMERIC[],                                    -- nullable; [x1, y1, x2, y2] in PDF points; multi-rect = flattened
  source_anchor JSONB,                               -- nullable; non-PDF only
  section_path TEXT[],                               -- ['Department of Corrections', 'Operating Lump Sum', ...]
  agency_canonical_ids TEXT[] NOT NULL DEFAULT '{}', -- entries SHOULD reference agencies(agency_id); validated in WS2 loader
  fund_canonical_id TEXT REFERENCES funds(fund_id),  -- primary fund; nullable
  fund_mentions TEXT[] NOT NULL DEFAULT '{}',        -- all funds mentioned (validated array against funds)
  fiscal_year INT,                                   -- denormalized from documents for fast filter
  doc_type TEXT NOT NULL,                            -- denormalized
  is_table BOOLEAN NOT NULL DEFAULT FALSE,
  table_html TEXT,                                   -- preserved for is_table=true chunks
  token_count INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((page IS NOT NULL AND bbox IS NOT NULL) OR source_anchor IS NOT NULL)
);

-- ---------------------------------------------------------------------------
-- Conversations: top-level chat thread (decision D4 — multi-turn UX)
-- ---------------------------------------------------------------------------
CREATE TABLE conversations (
  conversation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id TEXT,                                      -- nullable in v1 (single-user)
  started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  ended_at TIMESTAMPTZ,
  llm_provider TEXT NOT NULL,                        -- 'youcoded-session' | 'companion' | 'anthropic-api'
  external_session_id TEXT                           -- maps to YouCoded's session id (or whatever provider tracks)
);

-- ---------------------------------------------------------------------------
-- Messages: one row per user/assistant turn, ordered within a conversation
-- ---------------------------------------------------------------------------
CREATE TABLE messages (
  message_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  conversation_id UUID NOT NULL REFERENCES conversations(conversation_id),
  parent_message_id UUID REFERENCES messages(message_id),  -- chains turns within a conversation
  role TEXT NOT NULL CHECK (role IN ('user', 'assistant', 'system')),
  content TEXT NOT NULL,                             -- raw text (assistant content = rendered answer post-faithfulness)
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Per-assistant-turn audit log (one row per assistant message worth retrieving for)
-- ---------------------------------------------------------------------------
CREATE TABLE queries (
  query_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  message_id UUID NOT NULL REFERENCES messages(message_id),  -- the assistant message this audits
  raw_user_message TEXT NOT NULL,                            -- the user message that triggered this turn
  retrieve_calls JSONB NOT NULL,                             -- list of {query, filters, returned_chunk_ids, reranker_scores, top_score}
  cite_calls JSONB NOT NULL,                                 -- list of {chunk_id, span_start, span_end, confidence, claim_span}
  faithfulness_verdicts JSONB,                               -- per-citation NLI/judge results
  refusal_type TEXT,                                         -- 'refusal_no_retrieval' | 'refusal_synthesis' | 'refusal_out_of_scope' | NULL
  latency_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ---------------------------------------------------------------------------
-- Eval runs (regression test results)
-- ---------------------------------------------------------------------------
CREATE TABLE eval_runs (
  run_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  git_sha TEXT NOT NULL,
  total_queries INT NOT NULL,
  faithfulness_pass_rate REAL NOT NULL,
  refusal_rate REAL NOT NULL,
  per_query_results JSONB NOT NULL
);
