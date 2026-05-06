---
title: Ask the Budget AZ — Design Spec
date: 2026-05-04
status: approved
authors: Destin Moss, Claude
audience: design implementers, future contributors, internal pilot stakeholders
---

# Ask the Budget AZ — Design Spec

A Q&A system over Arizona state budget documents, designed for JLBC staff and fiscal analysts. The product's core value is **auditable retrieval with provenance**: every claim the system makes links to the exact PDF page and bounding box that supports it.

This spec is the source of truth for v1 architecture, phasing, citation UX, refusal behavior, evaluation, and governance. The implementation plan (forthcoming) is derived from this document.

## 1. Problem Statement

Arizona produces several large, heterogeneous fiscal documents annually:

- **JLBC Baseline Books** — narrative-dense agency-by-agency program descriptions plus appropriation tables. Often 600–900 pages.
- **JLBC Appropriations Reports** — companion to the baseline; line-item appropriations across the state.
- **AGAO Annual Financial Reports (AFRs)** — GAAP-flavored financial statements with restated tables, dense footnotes, fund balance summaries.
- **Governor's Executive Budget proposals** — competing narrative + numbers from the executive branch, formatted differently again.

Fiscal analysts spend significant time **locating** information across these documents and **comparing** how the same program or line item is treated across publishers and fiscal years. The four publishers each name and structure programs differently, and the AFR's restated tables periodically rewrite the historical record.

Existing tools (full-text PDF search, ad-hoc spreadsheets, institutional memory) handle the *find one thing* case poorly and the *compare across publishers* case worse. LLM-based document Q&A is a natural fit, but only if it doesn't introduce a new failure mode (confident hallucination) that's worse than the slow manual workflow it replaces.

## 2. Audience and Use Cases

**Primary audience (v1):** JLBC staff and fiscal analysts. Domain experts. They already know the documents — they need acceleration, not orientation. UI and answer style are dense, terse, cite-heavy. No over-explanation.

**Possible Phase 4 audience:** Public users (journalists, civic researchers, AZ residents). Gated on internal trust metrics. Architectural decisions support but do not assume this transition.

**Primary use cases (in order of frequency):**

1. **Lookup** — "What was the FY25 General Fund appropriation for ADC?" "Find every mention of the Prop 204 expansion in the FY24 baseline book." Fast retrieval, exact citation, LLM mostly locates and quotes.
2. **Comparison** — "How did corrections appropriations change between FY23 and FY25?" "What changed in the AFR notes between 2022 and 2024?" "What's different between the Governor's FY26 proposal and the JLBC baseline?" Cross-document retrieval, side-by-side synthesis.
3. **Synthesis** — "Summarize the major fiscal pressures in the FY25 baseline book." "What does the AFR say about pension liability trends?" Multi-section retrieval, longer-form output. Less frequent but real.

The retrieval architecture must handle all three from day one. The chat/answer UI optimizes for #1 and #2.

## 3. Core Invariants

These override anything else in the system. Violating any of them breaks the trust model.

1. **Every claim is auditable.** No claim renders without a passing citation. The citation chip → exact PDF page + bbox highlight in the side panel. If we can't ground a claim, we don't make the claim.
2. **Citations are verified, not just emitted.** A separate post-generation faithfulness check confirms each citation actually entails the claim. Failed citations are visibly stripped from the rendered answer with an italic note, not silently dropped or quietly accepted.
3. **Refusal beats hallucination.** When retrieval can't find a relevant chunk, or synthesis can't ground an answer, the system says "I can't answer this from the corpus" and shows the raw chunks for the analyst to read. A high refusal rate means the corpus is incomplete or retrieval is weak — both fixable. Confident hallucination is the trust-destroying failure.
4. **Domain experts, not laypeople.** Dense, terse, cite-heavy. No marketing tone. No padded prose.
5. **Internal first, public never until earned.** Phase 4 is gated on hard metrics in §11 of this spec. Phase decisions are reviewed against those metrics; not vibes.
6. **No automated action triggered by system output.** The tool informs analysts; analysts decide. Outputs never drive downstream automation.
7. **No "hallucination-free" or "grounded" marketing claims.** Stanford's 2024 Lexis/Westlaw study measured 17–33% hallucination on tools that marketed as grounded. We're honest about limits or we don't ship.

## 4. System Architecture

Three runtime tiers, plus a Phase 2 companion app on each analyst's machine.

```
┌─────────────────────────────────────────────────────────────────┐
│ ANALYST'S BROWSER                                               │
│  Next.js front-end: search bar, answer pane, side-panel PDF     │
│  viewer (PDF.js + react-pdf-highlighter-extended), citation     │
│  chips, "verify mode" toggle                                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTPS
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│ WEB SERVER (Vercel free tier in Phase 2)                        │
│  Next.js Server Components + API routes:                        │
│   • Query router: classifies lookup vs. comparison vs. synthesis│
│   • Retrieval pipeline: BM25 + dense → RRF → rerank → top-K     │
│   • Sub-query decomposition for comparison queries              │
│   • Citation post-verifier (NLI/judge pass)                     │
│   • PDF byte serving (HTTP range-request, lazy paged)           │
│   • Audit log writer                                            │
└──────────────┬─────────────────────────────────┬────────────────┘
               │                                 │
               ▼                                 ▼
┌──────────────────────────────┐  ┌──────────────────────────────┐
│ POSTGRES + pgvector + ParadeDB│  │ ANALYST'S MACHINE            │
│ (Supabase or Neon free tier)  │  │ "JLBC Budget Agent"          │
│  • chunks                     │  │ companion app:               │
│  • documents                  │  │  • Wraps Claude Code         │
│  • agencies (canonical map)   │  │    (lifted from YouCoded)    │
│  • queries (audit log)        │  │  • Localhost WebSocket       │
│  • eval_runs                  │  │  • Uses analyst's Pro/Max    │
└──────────────────────────────┘  │  • Synthesis + tool-call     │
                                   │    citations                 │
                                   │  • System tray UI only       │
                                   └──────────────────────────────┘

INGEST PIPELINE (offline, run on Destin's machine for v1):
  raw documents (PDF + DOCX) → per-doc-type extractor routing:
    Tagged PDFs (AFR, Gov State-Agency-Detail)
      → OpenDataLoader-PDF with use_struct_tree=True
      → cell-level JSON + (page, bbox) provenance
    Untagged PDFs (JLBC Baseline, JLBC Approps, Gov Sources-and-Uses)
      → MinerU 2.5 (CLI subprocess)
      → HTML tables + (page, bbox) provenance
    DOCX (budget bills)
      → python-docx
      → JSON + (paragraph_id, cell_id) provenance
  → chunking layer (extractor-aware reader, format-agnostic output)
  → uniform Chunk rows (table chunks + narrative chunks)
  → Voyage-3-large embeddings → Postgres write
  + agency canonical map keyed by JLBC slug (`agency:<slug>`, e.g. `agency:axs` for AHCCCS)
  + cross-cut summary PDFs (JLBC s-PDFs s1–s90) ingested as small focused docs

Why format-aware: budget bills (and likely future legislative artifacts) are
distributed as .docx — a structured XML format where paragraphs, tables,
and headings are tagged explicitly. Converting to PDF and then re-extracting
discards information we already have for free. Native docx ingest is
lossless and deterministic; PDF extraction inherently performs layout
inference that is error-prone on financial docs.
```

### 4.1 Role separation

- **Browser** is dumb: UI only, no business logic.
- **Web server** owns retrieval, ranking, faithfulness verification, audit logging, and source-document serving (PDF byte serving for PDF sources, on-demand HTML rendering for .docx sources). **It does not embed the LLM provider directly** — it delegates synthesis to the active `LLMProvider` implementation (see §4.2). This separation lets us swap providers (local companion / Anthropic API / self-hosted) without touching the retrieval pipeline.
- **Companion app** is small and single-purpose: receives `(question, retrieved_chunks)`, returns `(answer, structured_citations)` via Claude Code running locally. Lifted from YouCoded's existing PTY/wrapper infrastructure.
- **Postgres** is the single persistent store. Chunks, vectors, BM25 index, document metadata, agency canonical map, audit log all live in one database. Single backup, single restore.

### 4.2 Provider abstraction

The web server defines an `LLMProvider` interface:

```ts
interface LLMProvider {
  synthesize(args: {
    query: string;
    chunks: Chunk[];
    queryType: 'lookup' | 'comparison' | 'synthesis';
  }): Promise<{
    answer: string;
    citations: Citation[];
    refusal?: RefusalReason;
  }>;
}
```

Implementations:
- `LocalCompanionProvider` (Phase 2 default) — calls localhost WebSocket on the analyst's machine
- `AnthropicAPIProvider` (Phase 3 option) — direct API for one shared org account
- `SelfHostedLLMProvider` (Phase 4 option for public access) — open-weight model on a server

All three are wired against the same interface. Settings page picks which one is active. We ship `LocalCompanionProvider` first; the others come online when their use case becomes real.

## 5. Data Flow (Typical Query)

1. Analyst types: *"How did ADC General Fund appropriations change between FY23 and FY25?"*
2. **Query router** classifies as **comparison**. Decomposes into sub-queries: `{topic: "ADC General Fund appropriations", fiscal_year: 2023}` and `{...fiscal_year: 2025}`.
3. For each sub-query in parallel:
   - **BM25** retrieves top 200 chunks via ParadeDB
   - **Dense vector** retrieves top 100 via pgvector + Voyage-3-large embeddings
   - **RRF fusion** combines (k=60, slight weight toward BM25 for lookup-type sub-queries)
   - **Reranker** (Voyage rerank-2.5) picks top 50
   - Server selects top 20 with metadata filters (`fiscal_year`, `doc_type`, `agency_canonical_id`)
4. Combined chunks (40 total across both sub-queries) sent to companion via localhost WebSocket: `synthesize({query, chunks, queryType: "comparison"})`.
5. **Companion** runs Claude Code with a structured prompt; the model emits `cite(chunk_id, span_start, span_end, confidence)` tool calls per claim. Answer + citations stream back.
6. **Faithfulness check**: server runs each citation through an NLI/judge pass — does this chunk entail the claim spanning `span_start..span_end`? Citations below the threshold are downgraded to ⚠ and **the claim text they support is stripped** from the rendered answer (replaced with `[claim removed: no supporting source]`).
7. Browser renders the cleaned answer with chips. Click a chip → side panel jumps to PDF page, scrolls cited region into center, paints yellow rect on bbox.
8. Whole interaction (raw query, classified type, sub-queries, retrieved chunk IDs, reranker scores, chunks sent to LLM, citations emitted, faithfulness verdicts, final rendered answer, refusal type if any, latency) logged to `queries` table.

## 6. Data Model (v1)

Postgres schema, simplified:

```sql
-- Documents in the corpus
CREATE TABLE documents (
  doc_id TEXT PRIMARY KEY,
  publisher TEXT NOT NULL,          -- 'jlbc' | 'agao' | 'governor' | 'legislature'
  doc_type TEXT NOT NULL,           -- 'baseline-book' | 'approps-report' | 'afr' | 'governors-budget' | 'budget-bill' | ...
  fiscal_year INT NOT NULL,
  title TEXT NOT NULL,
  source_url TEXT,
  source_format TEXT NOT NULL,      -- 'pdf' | 'docx' (extensible to 'html', 'xml', etc.)
  source_blob_path TEXT NOT NULL,   -- where the original file lives; served via HTTP range (PDF) or on-demand HTML render (DOCX)
  page_count INT,                   -- nullable; populated for PDFs only
  ingested_at TIMESTAMPTZ NOT NULL,
  extractor TEXT NOT NULL,          -- 'mineru-2.5' | 'opendataloader-2.4.1' | 'python-docx' | 'sonnet-vision'
  extractor_version TEXT NOT NULL
);

-- Canonical agency map (Tier 1 entity resolution)
CREATE TABLE agencies (
  agency_id TEXT PRIMARY KEY,             -- e.g., 'adc'
  canonical_name TEXT NOT NULL,           -- 'Department of Corrections'
  short_name TEXT,                        -- 'ADC'
  aliases TEXT[] NOT NULL DEFAULT '{}'    -- ['Adult Corrections', 'Corrections Department', ...]
);

-- Chunks: the retrieval atom
CREATE TABLE chunks (
  chunk_id TEXT PRIMARY KEY,
  doc_id TEXT NOT NULL REFERENCES documents(doc_id),
  text TEXT NOT NULL,
  embedding vector(1024),                  -- Voyage-3-large output dim
  -- Provenance is polymorphic by source format. PDF sources populate (page, bbox);
  -- DOCX sources populate source_anchor with paragraph and cell ids. The CHECK
  -- constraint enforces that at least one provenance shape is present.
  page INT,                                -- nullable; PDF-source chunks only
  bbox NUMERIC[],                          -- nullable; PDF-source chunks only ([x1, y1, x2, y2] in PDF points; multi-rect = flattened)
  source_anchor JSONB,                     -- nullable; non-PDF chunks. Shape for docx: {"paragraph_id": "p47", "table_cell_id": "tbl3.r5.c2"}
  section_path TEXT[],                     -- ['Department of Corrections', 'Operating Lump Sum', 'County Reimbursement']
  agency_canonical_id TEXT REFERENCES agencies(agency_id),
  fiscal_year INT,                         -- denormalized from documents for fast filter
  doc_type TEXT NOT NULL,                  -- denormalized
  is_table BOOLEAN NOT NULL DEFAULT FALSE,
  table_html TEXT,                         -- preserved for is_table=true chunks
  token_count INT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CHECK ((page IS NOT NULL AND bbox IS NOT NULL) OR source_anchor IS NOT NULL)
);

-- BM25 index lives here via ParadeDB pg_search; not a separate table
CREATE INDEX chunks_bm25 ON chunks USING bm25 (chunk_id, text)
  WITH (key_field = 'chunk_id');

-- Dense vector index
CREATE INDEX chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops);

-- Metadata indexes
CREATE INDEX chunks_fiscal_year ON chunks (fiscal_year);
CREATE INDEX chunks_doc_type ON chunks (doc_type);
CREATE INDEX chunks_agency_canonical_id ON chunks (agency_canonical_id);

-- Audit log
CREATE TABLE queries (
  query_id UUID PRIMARY KEY,
  user_id TEXT,
  raw_query TEXT NOT NULL,
  classified_type TEXT NOT NULL,
  sub_queries JSONB,
  retrieved_chunk_ids TEXT[],
  reranker_scores REAL[],
  chunks_sent_to_llm TEXT[],
  llm_provider TEXT NOT NULL,
  llm_response_raw TEXT,
  citations_emitted JSONB,
  faithfulness_verdicts JSONB,
  final_answer_rendered TEXT,
  refusal_type TEXT,
  latency_ms INT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Eval runs (regression test results)
CREATE TABLE eval_runs (
  run_id UUID PRIMARY KEY,
  ran_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  git_sha TEXT NOT NULL,
  total_queries INT NOT NULL,
  faithfulness_pass_rate REAL NOT NULL,
  refusal_rate REAL NOT NULL,
  per_query_results JSONB NOT NULL
);
```

Programs and sub-program canonicalization (Tier 2) is **deferred**; sub-program hits are surfaced with their original names. See §8 for the staged rollout.

## 7. Phasing

| Phase | Scope | Where it runs | Users |
|---|---|---|---|
| **Phase 0 — Investigation** ✓ closed 2026-05-06 | Extractor bake-off, entity-resolution catalog, chunking validation. See `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` (memo), `2026-05-05-chunk-shape-decisions.md` (chunking), `2026-05-06-data-model.md` (source-data model). | Destin's machine | Destin |
| **Phase 1a — Ingest + chunking** ✓ closed 2026-05-06 (slice-validated) | Discovery + per-doc-type extractor dispatch + chunking layer + entity stamping + fund catalog. Tag `phase-1a-validated-slice` (commit `9ba0385`). 5 docs / 161 chunks / 91.3% agency-stamped / 227 funds. Pipeline proven on real source; full-corpus ingest deferred to Phase 1b kickoff. Hand-off contract at `data/chunks/MANIFEST.md`. | Destin's machine | Destin |
| **Phase 1b — Storage + retrieval** | Postgres + pgvector + ParadeDB. Loader, embedding pipeline (Voyage-3-large), hybrid retrieval (BM25 + dense + RRF + rerank), query routing. End-to-end `retrieve(query) -> list[Chunk]`. ~2–3 weeks. Plan at `docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`. | Destin's machine | Destin (dogfooding) |
| **Phase 1c — Companion + UI** | LLM synthesis with per-claim citations, NLI faithfulness verification, refusal triggers, Next.js UI. ~2–3 weeks. Plan at `docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`. | Destin's machine | Destin (dogfooding) |
| **Phase 2 — Companion + first deploy** | Build JLBC Budget Agent companion (lifts from YouCoded). Deploy web app to free tier. Onboard 2–3 trusted analysts. ~2–3 weeks. | Vercel/Supabase + each analyst's machine | Destin + 2–3 analysts |
| **Phase 3 — Internal pilot** | Wider JLBC use. Tier 2 entity resolution informed by real query logs. Eval set expansion. | Same | Wider JLBC |
| **Phase 4 — Public-launch consideration** | Gated on metrics in §11. Probably switches LLM provider to API mode (no companion app for the public). | Same + public host | Public, if trust is established |

Tier 0 / Phase 0 is the **only** phase where we make irreversible architecture decisions. Each subsequent phase adds capability on top.

## 8. Phase 0 Investigation (Concrete Plan)

> **Status: closed 2026-05-06.** Outcomes captured in:
> - `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` — findings memo (settled decisions, deferred decisions, Phase 1 readiness)
> - `docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md` — chunk-shape decisions D1–D7
> - `docs/superpowers/investigations/2026-05-06-data-model.md` — JLBC publishing structure, s-PDFs, slug-as-canonical-id, multi-year corpus
>
> Notable scope changes during execution:
> - **Goal 1 (winner extractor) became per-doc-type routing** — no single winner; ODL for tagged PDFs (AFR, Gov), MinerU for untagged (JLBC), python-docx for DOCX. Documented in §9 stack table below.
> - **Goal 2 (entity catalog) was bootstrapped from publisher data** — JLBC's per-year agency-index PDFs gave us 132 canonical agencies with stable slugs going back to FY 2015. `samples/entity-catalog.yaml`.
> - **Discovery of JLBC's four parallel publishing layouts** (singlefile + link-nav + per-agency PDFs + cross-cut s-PDFs) — this changes the Phase 1 ingestion shape; see data-model doc §2-§3.
>
> The original concrete plan below is preserved as the historical record of how Phase 0 was scoped.

The only phase that produces a memo instead of code. Goal: make irreversible architecture decisions on real data.

### 8.1 Sample corpus

~6–8 PDFs picked to surface every failure mode we know of:

- 1× JLBC Baseline Book FY25 (current)
- 1× JLBC Baseline Book FY23 (older, for cross-year testing)
- 1× JLBC Appropriations Report FY25
- 1× AGAO Annual Financial Report FY24 (different formatting, GAAP, restated tables)
- 1× Governor's Executive Budget FY26
- 1–2× misc (fiscal note, supplement)

Stored in `samples/raw-pdfs/` (gitignored if too large; metadata committed).

### 8.2 Extractor bake-off

Both **MinerU 2.5** and **OpenDataLoader-PDF** run on the same ~20 deliberately-chosen pages. (Originally Docling was the second extractor; pivoted 2026-05-05 — see Phase 0 plan intro.) Pages chosen:

- A 5+ page appropriations table with merged headers
- A restated AFR fund-balance table with footnote chains
- A multi-column narrative program description
- A fiscal note mixing prose and tables
- A footnote-heavy schedule
- A page where the same line item appears under different names across two doc types

Manual scoring on:
- **Cell-level numeric accuracy** (~20 cells per table)
- **Bbox quality** — does the reported bbox actually surround the right text?
- **Multi-page table reassembly**
- **Section header detection**
- **Footnote attachment**

Output: scorecard at `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md`. Winner = v1 primary; loser = documented fallback.

### 8.3 Entity-resolution catalog

Manually pick ~20 fiscal entities at three levels and document their names across all four doc types:
- Agency level (~10): hypothesis trivial, confirm
- Program level (~7): hypothesis tractable but messy, catalog variance
- Sub-program / line item (~3): hypothesis very messy, likely Tier 2

Output: `data/entity-variance-catalog.csv` plus a confidence rating per tier in the bake-off memo.

### 8.4 Chunking shape validation

Take the winning extractor's output, manually mark up where chunks should split. Validate the structure-aware approach (section boundaries, tables atomic, 512-token target / 1024 max) against real Arizona content.

### 8.5 Phase 0 deliverables

1. `samples/raw-pdfs/` — the 6–8 PDFs
2. `samples/extractor-output/` — JSON+Markdown side-by-side
3. `docs/superpowers/investigations/2026-MM-DD-phase-0-bakeoff.md` — scorecard + memo
4. `data/entity-variance-catalog.csv` — entity name catalog
5. **Go/no-go decision** for Phase 1: does open-source quality clear the bar? If both extractors choke (most likely on AFR restatements), revisit the paid-extractor question with concrete data.

## 9. v1 Stack Decisions

| Layer | Choice | Why |
|---|---|---|
| **Format-aware ingest router** | Trivial extension-based dispatch (`.pdf` → PDF path, `.docx` → DOCX path) | Native processing of structured formats avoids the lossy `docx → pdf → re-extract` round-trip. |
| **PDF extraction (tagged docs: AFR, Gov State-Agency-Detail)** | OpenDataLoader-PDF v2.4.1 with `use_struct_tree=True` | Tagged PDFs carry a structure tree; ODL surfaces it as cell-level JSON with row/col indices. Apache-2.0, JDK-only, ~15× faster than MinerU. (Replaces Docling, which proved unworkable on Windows — see Phase 0 plan "Pivot — 2026-05-05".) |
| **PDF extraction (untagged docs: JLBC Baseline, JLBC Approps, Gov S&U)** | MinerU 2.5/3.x via CLI subprocess | Untagged PDFs lose column structure under ODL; MinerU detects tables and emits HTML with row/col attribution. Validated in Phase 0 inspection on JLBC pages 164/513. |
| **PDF extraction (escalation, deferred)** | Claude Sonnet/Opus 4.x vision | Defer to Phase 1+ if MinerU's residual error rate proves unacceptable. Three response strategies in chunk-shape D-defer-1: accept + UI surfacing / confidence-flagging / custom JLBC extractor. |
| **DOCX extraction** | `python-docx` direct | Reads the .docx XML directly. Lossless: paragraphs, tables, headings, and styles are explicit in the source. No layout inference needed. |
| **Chunking** | Structure-aware, tables atomic, 512-token target / 1024 max, ~15% overlap | 2026 consensus for financial RAG (recall 0.877 vs. 0.759 for semantic-only chunking). |
| **Vector + lexical store** | Postgres + pgvector + ParadeDB pg_search | Single store, transactional metadata, easy SQL fan-out for comparison queries. Fits free tier (Supabase or Neon). |
| **Embeddings** | Voyage-3-large | Measurably leads MTEB on legal+financial sub-benchmarks. 1024-dim. |
| **Reranker** | Voyage rerank-2.5 (or Zerank-1 for cost) | Strong financial/legal performance; ~600ms. Pull 200 BM25 + 100 dense → fuse RRF → rerank 100 → top 20 to LLM. |
| **Query routing** | Custom classifier (lookup vs. comparison vs. synthesis), ~150 lines | Comparison queries decompose into per-(year × doc-type) parallel retrieval. |
| **LLM (synthesis)** | Claude Opus 4.7 via local companion | Pro/Max-backed via YouCoded for Phase 1; companion app for Phase 2. |
| **Citation emission** | Tool calls (`cite(chunk_id, span_start, span_end, confidence)`) | Span-level anchoring + structured output + verification hook in one. Cleaner than Anthropic Citations API for our shape. |
| **Faithfulness verifier** | NLI / judge pass post-generation | Single highest-leverage trust feature per research. Strips chip + claim if it fails. |
| **PDF viewer** | PDF.js + react-pdf-highlighter-extended | 2026 winner; supports text + rect highlights with programmatic API. HTTP range-request streaming for large PDFs. |
| **Web framework** | Next.js (App Router) + React + TypeScript | Matches Destin's existing stack; native Vercel deploy. |
| **Hosting (Phase 1)** | Destin's machine | $0 |
| **Hosting (Phase 1.5/early Phase 2)** | Destin's machine port-forwarded | $0; one-day move from Phase 1 |
| **Hosting (Phase 2 proper)** | Vercel free tier + Supabase or Neon free tier | $0 |
| **Hosting (Phase 3+)** | JLBC infrastructure if offered, paid VPS otherwise | TBD |
| **Auth** | Google SSO restricted to `azleg.gov` (or equivalent JLBC domain) | Reuses existing identity; minimal new infra |
| **Repo visibility** | Private through Phase 3, re-evaluate going public at Phase 4 | Civic-tech open-sourcing is great, but only after the system is trustworthy |

## 10. Citation UX

### 10.1 Inline rendering

- Each sentence (or clause) that the system makes a factual claim about is **underlined**, with a numeric chip at the end of the underlined span: *"…fiscal year 2024 General Fund appropriation of $1.74B [3]"*
- The underline scope = the exact span supported by the chunk. **Multiple chips per sentence** when different parts come from different sources.
- **Three confidence states** rendered as glyphs on the chip:
  - ✓ **Verbatim** — the exact phrase appears in the source chunk
  - ≈ **Paraphrase** — the source chunk supports the claim semantically; faithfulness check passed
  - ⚠ **Ungrounded** — faithfulness check failed. **Chip and the claim it supports are stripped** from the rendered answer with an italic note: `[claim removed: no supporting source]`

### 10.2 Hover and click behavior

- **Hover the chip** → tooltip with filename, page number, fiscal year, the exact verbatim quote from the source chunk, and a "Copy citation" button that formats as `JLBC Baseline Book FY24, p. 47`.
- **Click the chip** → side panel:
  - PDF jumps to the page, scrolls the cited region into center viewport
  - Yellow rectangle overlay painted on the precise bbox(es); multiple rects for multi-region citations
  - Highlight persists until the next click
  - Breadcrumb at top: `Page 47 of FY24-baseline-book.pdf`

### 10.3 Verify mode

A toggle in the answer pane (off by default). When on, scrolling the answer auto-scrolls the PDF viewer to follow each citation as it comes into view. Synchronized scrollytelling for analysts auditing a long answer.

### 10.4 Implementation notes (PDF source)

- LLM emits citations as **tool calls**, not Anthropic Citations API. Tool calls give us span-level anchoring + structured output + a verification pass in one shape.
- `react-pdf-highlighter-extended` wraps PDF.js and supports both text and rect highlights. Skip `react-pdf-viewer` (unmaintained since early 2023) and Adobe Embed (vendor lock-in, weak programmatic control).
- Server serves PDFs via HTTP Range requests; PDF.js loads in 64KB chunks. Render only ±2 pages around viewport per PDF.js's own guidance.

### 10.5 Non-PDF source rendering (.docx)

For chunks sourced from .docx documents, the side-panel viewer uses HTML rendering with paragraph- and cell-level highlights instead of bbox overlays. Same UX promise; different rendering primitive.

- **Render path:** Server converts the .docx to HTML on demand (Mammoth.js server-side, or a Python equivalent like `docx2html`). The HTML preserves Word's structural tagging — every `<w:p>` becomes a `<p>` with a stable `id`, every `<w:tc>` becomes a `<td>` with a stable `id`. The same stable ids are stored in `chunks.source_anchor` during ingest, so a click on a citation chip can resolve directly to a DOM element.
- **Highlighting:** The chunk's `source_anchor` JSON carries `{paragraph_id, table_cell_id?}`. The viewer scrolls to that element and applies a yellow background highlight on the matching `<p>` or `<td>`.
- **Multi-paragraph citations** = multiple chips, each opening their own anchor. Same as multi-region PDF citations.
- **Confidence chrome and verify mode** behave identically to the PDF path.
- **Stable ids are the contract.** The DOCX renderer must emit deterministic, ingest-time-equivalent ids — otherwise highlighting silently mismatches the cited paragraph. Verify by re-rendering during ingest and confirming the same id assignment.

## 11. Refusal Behavior

Three explicit cases:

1. **`refusal_no_retrieval`** — top reranked chunk falls below a similarity threshold. The threshold value is calibrated during Phase 1 against the eval set (start with reranker score < 0.3 as a placeholder; tune so the eval set's intended-refusal queries refuse and the rest don't). Response: *"I couldn't find anything in the corpus that addresses this question. The corpus currently includes [doc types and fiscal years]. You may want to rephrase, or this may be outside what's been indexed."*
2. **`refusal_synthesis`** — retrieval found chunks but every claim the LLM tried to emit failed faithfulness check. Response: *"I found these potentially relevant passages but couldn't confidently synthesize an answer."* Lists the top 5 chunks with citations. Analyst reads raw chunks and decides.
3. **`refusal_out_of_scope`** — the query asks for editorial judgment ("what should we do about X"). The classifier and prompt are tuned to recognize this and decline.

Refusal is logged but not a failure. We monitor refusal rate; we treat false confidence as the worse failure mode.

## 12. Audit Log

Every query writes one row to `queries`. Schema in §6. Used for:
- Diagnosing regressions (replay the exact retrieved chunks against a new prompt)
- Eval set seeding (Phase 3 — anonymized real queries become eval cases)
- Trust auditing (analyst can ask "show me everything I asked yesterday and the citations I got")
- Operational metrics (refusal rate, latency, faithfulness pass rate)

Audit log content is **never** used to train, fine-tune, or share with third parties. Operational only.

## 13. Evaluation

Hand-curated, version-controlled eval set at `eval/queries.yaml`. ~50 Q/A pairs at v1 launch, target ~200 by Phase 3.

```yaml
- id: q-001
  query: "What was the FY24 General Fund appropriation for ADC?"
  type: lookup
  expected_answer_contains: ["$1.74", "General Fund", "ADC"]
  expected_chunks_must_include:
    - {doc: "FY24-jlbc-approps-report.pdf", page: 47}
  expected_refusal: false

- id: q-014
  query: "How did corrections appropriations change between FY23 and FY25?"
  type: comparison
  expected_answer_contains: ["FY23", "FY25", "increase|decrease|change"]
  expected_chunks_must_include:
    - {doc: "FY23-jlbc-baseline.pdf", agency: "ADC"}
    - {doc: "FY25-jlbc-baseline.pdf", agency: "ADC"}
  expected_refusal: false

- id: q-027
  query: "What's the right tax policy for Arizona?"
  type: out-of-scope
  expected_refusal: true
```

**Curated by Destin initially.** Once trusted analysts come online in Phase 2, they help expand the set; their queries (anonymized via the audit log) seed new eval cases organically.

**Run automatically** on every PR that touches: ingest, chunking, retrieval, reranker config, query routing, LLM prompts, faithfulness verifier, or `LLMProvider` implementations. Reports:
- Per-query-type accuracy (lookup vs. comparison vs. out-of-scope)
- Faithfulness pass rate
- Refusal rate
- Citation precision (did we cite the right chunk?) and recall (did we cite *all* the right chunks?)

Eval results stored in `eval_runs` table. Regressions surface in CI.

## 14. Public-Launch Gate (Phase 4 entry criteria)

Phase 4 does not begin until **all** of the following are met:

1. Faithfulness pass rate ≥ 95% on the eval set
2. Analyst-confirmed accuracy ≥ 90% on a 50-query human-graded subset
3. Refusal rate between 5% and 35%
4. Zero "egregious failure" regressions for two consecutive eval runs (egregious = wrong dollar figure, wrong fiscal year, wrong agency, conflated programs)
5. 3+ months of continuous internal use by 5+ analysts without major incident
6. Signed-off public-readiness review documenting known limitations, data freshness, evaluation summary, and unsolved failure modes

Falsifiable. If any slips, Phase 4 stays gated. Internal use continues regardless.

## 15. Anti-Patterns Explicitly Rejected

These are codified to prevent future drift.

- **No "hallucination-free" or "grounded" marketing language.** Stanford's Lexis study is the canonical reason. Honest about limits or we don't ship.
- **No automated action on system output.** Outputs inform analysts; analysts decide. The DOGE VA contract AI is the canonical anti-pattern.
- **No summarization of truncated or sampled fiscal numbers without a verifier pass.** If a chunk got cut mid-table, we re-chunk or refuse, but never summarize partial data.
- **No silent fallback when faithfulness check fails.** Stripped citations are visible. Hidden failure erodes trust.
- **No use of corpus content for any purpose beyond answering queries.** Audit log is operational only; not a training set, not shared, not used to fine-tune.
- **No feature creep that competes with citation rigor.** FiscalNote PolicyNote is the cautionary tale — flashy summaries crowd out the core trust loop. Citations are the product. Everything else is secondary.

## 16. Open Questions (To Resolve in Phase 0 or Phase 1)

- **Tier 1 entity scope.** Phase 0 catalog will tell us which agencies are tractable; we may discover some aren't (mid-period reorganizations, sunset agencies). Resolution: Phase 0 memo.
- **AFR restated tables.** How do we represent a value that the AFR has restated across two years? Options: keep both versions and note restatement, replace older with restated, expose both via metadata. Resolution: Phase 0 finding determines difficulty; Phase 1 implementation decision.
- **Comparison query decomposition heuristics.** When user says "compare X" without specifying years, do we fan out across all years? Last 3 years? Resolution: Phase 1, after seeing real query patterns.
- **Faithfulness verifier model choice.** Self-hosted NLI model vs. another LLM call vs. structured-output classifier from the same Claude session. Resolution: Phase 1 spike.
- **Companion app framework.** Electron (matches YouCoded, larger binary) vs. Tauri (smaller, less mature for our integrations). Resolution: Phase 2.
- **JLBC SSO availability.** Whether `azleg.gov` Google Workspace SSO is technically available to our app. Resolution: ask JLBC IT.
- **DOCX→HTML renderer choice.** Mammoth.js (Node, runs in browser or server) vs. python-docx + custom HTML emitter (server-side, fewer deps but more code). Either way, the renderer must emit deterministic, ingest-time-equivalent paragraph/cell ids. Resolution: Phase 1 spike with a stable-id contract test.
- **Source format coverage beyond PDF/DOCX.** If future corpus expansion brings HTML pages (e.g., legislative bill text rendered as HTML on `azleg.gov`) or XML (legislative bill tracker feeds), the format-aware router extends naturally — but we should not pre-build paths until we have a real document to ingest.
- **Cross-cut whole-table chunk stamping.** [Phase 1a finding 2026-05-06] Phase 1a chunk-shape D6 stamps each whole-table cross-cut chunk to a SINGLE `agency_canonical_id` (the first match in source order), even when the table lists ~25 different agencies. AHCCCS rows in the s18 cross-cut sit inside a chunk stamped to `agency:bae` (Board of Accountancy — first alphabetically). Per-row stamping or section-by-agency chunk-shape subdivision is the open subcase. Resolution: Phase 1b chunk-shape revisit, before retrieval is wired against `agency_canonical_id` filters.
- **Acronym expansion for retrieval.** [Phase 1a finding 2026-05-06] Source documents use spelled-out names ("Department of Corrections") — JLBC docs and the bill DOCX both do. Acronym-form queries ("ADC", "ADOT", "GAA") don't tokenize against in-corpus text under TF-IDF. Phase 1b retrieval should expand acronyms via the system-prompt context's acronyms section (or a dedicated query-rewrite step) before BM25/dense retrieval. Resolution: Phase 1b retrieval design.
- **bd2 parser shape mismatch.** [Phase 1a finding 2026-05-06] `funds/parser.py::parse_s18_table` works on `s18.pdf` (FY27 baseline funds × agencies) but yields 0 rows on `bd2.pdf` (FY26 approps funds × agencies) — the column layouts differ enough that the s18 parser doesn't recognize bd2's table shape. The fund catalog is therefore single-source (s18 only); cross-source merge (s18 + bd2) is impossible without a bd2-specific parser or a more format-tolerant unified parser. Resolution: Phase 1b chunk/parser revisit.
- **Multi-page table reassembly across repeated headings.** [Phase 1a finding 2026-05-06] The MinerUReader's reassembly logic blocks merging when ANY heading appears between two same-shape tables. s18's "FY 2027 Other Fund Summary" title repeats on every continuation page, so 13 pages of one logical table emit as 13 separate chunks. Either widen the guard to ignore re-emitted same-text headings, or move reassembly to a post-pass driven by table-shape similarity. Resolution: Phase 1b chunk-shape revisit.

## 17. References

Research informing this design (Phase 0 web research, 2026-05-04):

**PDF extraction (open-source, financial focus):**
- [MinerU 2.5 / OmniDocBench leaderboard](https://www.codesota.com/browse/computer-vision/document-parsing/omnidocbench)
- [Docling (IBM) — visual grounding docs](https://docling-project.github.io/docling/examples/visual_grounding/)
- [PaddleOCR-VL 1.5](https://huggingface.co/PaddlePaddle/PaddleOCR-VL)
- [Best Open-Source PDF-to-Markdown Tools in 2026](https://themenonlab.blog/blog/best-open-source-pdf-to-markdown-tools-2026)
- [Building a Financial RAG System Pt 5 — structure-aware chunking benchmark](https://medium.com/@steveinatorx_49018/building-a-financial-rag-system-pt-5-how-i-fixed-chunking-to-reach-90-recall-7f1158e934a9)

**Hybrid retrieval and embeddings:**
- [ParadeDB Hybrid Search in PostgreSQL](https://www.paradedb.com/blog/hybrid-search-in-postgresql-the-missing-manual)
- [Voyage-3-large announcement (legal & finance benchmarks)](https://blog.voyageai.com/2025/01/07/voyage-3-large/)
- [FinSage: Multi-aspect RAG for Financial Filings QA](https://arxiv.org/html/2504.14493v3)
- [ZeroEntropy: Choosing the Best Reranking Model 2026](https://zeroentropy.dev/articles/ultimate-guide-to-choosing-the-best-reranking-model-in-2025/)

**Citation UX and faithfulness:**
- [Hebbia Matrix product](https://www.hebbia.com/product)
- [Glean Deep-Linked Citations API](https://developers.glean.com/guides/chat/deep-linked-citations)
- [Stanford Legal RAG Hallucinations study (2024, 17–33% rate)](https://dho.stanford.edu/wp-content/uploads/Legal_RAG_Hallucinations.pdf)
- [Layout-Aware RAG with Evidence Pins (Sept 2025)](https://vipulmshah.medium.com/layout-aware-rag-with-evidence-pins-building-clickable-citations-for-pdfs-using-docling-neo4j-5305769759f0)
- [react-pdf-highlighter-extended](https://github.com/DanielArnould/react-pdf-highlighter-extended)
- [Anthropic Citations API](https://claude.com/blog/introducing-citations-api)

**Civic-tech precedents:**
- [Stanford RegLab STARA (closest analog)](https://reglab.github.io/stara/) — [GitHub](https://github.com/reglab/stara)
- [GAO experimental LLM — FedScoop](https://fedscoop.com/gao-in-experimentation-phase-with-ai-model-to-query-reports-inform-its-work/)
- [GRASP — municipal-budget chatbot paper](https://arxiv.org/html/2503.23299)
- [Free Law Project semantic search](https://free.law/2026/05/04/semantic-search-on-courtlistener/)

**Cautionary tales:**
- [ProPublica on DOGE's VA AI tool](https://www.propublica.org/article/inside-ai-tool-doge-veterans-affairs-contracts-sahil-lavingia)
- [FiscalNote PolicyNote release](https://fiscalnote.com/press-room/fiscalnote-unveils-policynote)
- [GovAI Coalition](https://www.sanjoseca.gov/your-government/departments-offices/information-technology/ai-reviews-algorithm-register/govai-coalition)
- [ProPublica AI principles](https://www.propublica.org/ai-principles)
