---
title: Phase 1b/1c Architecture Reframe — v1 piggybacks on running YouCoded
date: 2026-05-06
status: decided
authors: Destin Moss, Claude
audience: Phase 1b + Phase 1c implementers, future contributors
supersedes_in_part:
  - docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md (§4 architecture, §4.2 provider abstraction, §5 data flow, §6 schema, §10.4 citation transport, §16 open questions)
  - docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md (Workstream 7 router/decomposer; "first workstream is full Week 1 ingest" framing)
  - docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md (Workstreams 1–2 companion app; v1 UI scope)
---

# Phase 1b/1c architecture reframe (decision artifact)

A working session on 2026-05-06 made twelve interlocking decisions that shift v1's shape away from the "separate Next.js web app + standalone companion + classifier-driven RAG" framing in the original spec and plans, toward "piggyback on a running YouCoded instance + agent-pattern retrieval." This doc captures those decisions in one place so future sessions don't relitigate them.

The downstream spec amendments + plan rewrites trace back here.

## Context (one paragraph)

Going into the session: Phase 1a was closed under a 5-doc / 161-chunk slice. Phase 1b plan said "first workstream = full Week 1 corpus ingest" before storage/retrieval code. Phase 1c plan said "build a separate companion app that wraps YouCoded's PTY/wrapper infra." Both choices made sense in isolation but, taken together, deferred dogfood by 4–6 weeks while the corpus filled and a separate companion got lifted. The session reframed: build the smallest end-to-end product first on the slice, expand the corpus underneath, and lean on the YouCoded instance Destin already runs instead of building a parallel companion.

## Decisions

### D1. Vertical slice over horizontal slice

Build Phase 1b + Phase 1c end-to-end on the existing 5-doc / 161-chunk slice. Volume ingest is decoupled — runs concurrently with or after WS1–WS6, doesn't gate them. Eval (WS8) is the only Phase 1b workstream that genuinely needs the full corpus.

**Why:** schema, loader, embeddings, BM25, dense, RRF, rerank, MCP server, web UI, and citation rendering all TDD against 161 chunks just as well as 3000. The first thing that needs volume is recall@K measurement. Sequencing infrastructure-first instead of corpus-first delivers a working dogfoodable product weeks earlier.

**Reverses:** Phase 1b plan's stated "first workstream is full Week 1 corpus ingest" framing.

### D2. `agency_canonical_ids TEXT[]` (array, not scalar)

Replace spec §6's `agency_canonical_id TEXT REFERENCES agencies(agency_id)` with `agency_canonical_ids TEXT[] NOT NULL DEFAULT '{}'`. Mirror the existing `fund_mentions TEXT[]` pattern in the Phase 1b plan.

**Why:** fixes the s18 cross-cut single-agency-stamping issue (chunk-shape D6) without re-chunking. A whole-table chunk listing 25 agencies stamps to all 25 instead of to the alphabetical first match. Filter syntax `WHERE 'agency:adc' = ANY(agency_canonical_ids)` is GIN-indexable. "Primary" agency status, if needed later, is recoverable from `section_path[0]`.

**Considered and rejected:**
- Per-row chunks (~12× chunk explosion)
- Section-by-agency chunk subdivision (real chunk-shape redesign, premature)
- Primary + mentions both columns (Option 2 — over-engineered until eval shows the boost matters)
- Status quo (actively wrong; first-match-wins surfaces under wrong agency)

### D3. v1 piggybacks on a running YouCoded instance

The v1 budget app is a separate web app with its own UI, backed by a Node server that connects to YouCoded's existing `ws://localhost:9900` interface. YouCoded provides: Claude Code session lifecycle, Pro/Max OAuth, PTY/wrapper machinery, transcript-watcher (tool-call parsing), attention/thinking state, MCP server registration. The budget app provides: budget-specific UI (chat thread, citation chips, side-panel PDF viewer), retrieval backend, MCP tool definitions, citation rendering.

**v1 hard-depends on YouCoded being installed AND running** on the same machine. If YouCoded isn't open, the budget app shows a "please open YouCoded" notice.

**Why:** every alternative was either heavier (vendor YouCoded's PTY infra into a budget-side companion → fork/maintenance burden) or incompatible with the Pro/Max subscription (Anthropic API direct, Agent SDK — both require separate API billing). Piggybacking treats YouCoded the way a browser treats a system clipboard: an existing platform-level service the app uses without reinventing.

**Considered and rejected:**
- Standalone companion (Phase 1c plan's original WS1-2): Phase 2 problem, when distributing to other analysts.
- Lift YouCoded's PTY/wrapper code into the budget repo: vendoring fork; rejected by user.
- Direct Anthropic API for synthesis: separate billing path, doesn't exercise the actual user-side subscription.
- Claude Agent SDK: also requires API billing per current Anthropic packaging.
- `claude -p` shell-out: works but no streaming, no native tool calls, cold-start per turn — wrong shape for multi-turn chat.

### D4. Multi-turn chat is the UX

Each conversation is one persistent YouCoded session. Follow-ups go to the same session; Claude has full conversation context. Anaphora resolution ("what about FY24?") falls out for free.

**Why:** real fiscal-analyst work is iterative. A single-turn Q&A tool would be worse than `Ctrl+F` for the kinds of follow-up reasoning analysts do. Spec was silent on this; we're now explicit.

**Implication:** spec §5 needs rewriting from single-query data flow to multi-turn flow. Schema gets `conversations` and `messages` tables; existing `queries` table becomes per-assistant-turn.

### D5. Claude keeps general tools

Standard Claude Code tools (Bash, Grep, Read, Glob, Edit, etc.) stay enabled in budget conversations. No permission lockdown.

**Why:** they're useful for follow-ups. "Grep the chunks store for any other mention of this fund," "read raw page 47 of the PDF," "list FY26 budget files" are all reasonable analyst moves. The MCP retrieval tool is the *primary* path to source material; general tools are the *fallback* path when retrieval missed something or the analyst wants to verify directly. Both serve the trust model.

### D6. Custom budget tools live in an MCP server

A small Node process registered with YouCoded's MCP config exposes two tools to any Claude session:

- `retrieve(query: string, filters?: {fiscal_year?: int[], doc_type?: string[], agency_canonical_id?: string[], publisher?: string[]}) → {chunks: Chunk[], top_score: float}`
- `cite(chunk_id: string, span_start: int, span_end: int, confidence: "verbatim" | "paraphrase", claim_span: string) → {ok: true}`

`retrieve()` runs the Phase 1b BM25 + dense + RRF + rerank pipeline. `cite()` records the citation; the actual rendering happens client-side by parsing `tool_use` blocks from YouCoded's transcript stream.

**Why:** custom tools in Claude Code are MCP servers — that's the natural extension point. YouCoded's transcript-watcher already structurally parses `tool_use` blocks, so the budget backend gets clean structured citations without prompt-marker parsing. The MCP server is one Node script + a config entry; the spotify-services plugin in `wecoded-marketplace` is a working precedent.

### D7. Constrained agent-pattern retrieval

Claude calls `retrieve()` per turn (one or more times); the system prompt **requires** at least one `retrieve()` call before answering any user question. Subsumes most of Phase 1b WS7 (router classifier + decomposer) — Claude does routing and decomposition through tool-call sequences.

**Why:** 2026 best-practice for conversational RAG over a corpus (STARA, FinSage, GAO's experimental LLM, Perplexity-Pro-class systems all use this shape). Anaphora resolution, multi-step retrieval, and comparison decomposition are all things the model with conversation context handles better than a regex pipeline. Pre-fetched RAG is incoherent in our setup anyway because Claude has parallel access to source files via Bash/Grep/Read (D5).

**Refusal enforcement (spec §11) reshapes:** the MCP `retrieve()` tool returns `{chunks, top_score}`. If `top_score` is below the calibrated threshold, the system prompt instructs Claude to refuse with `refusal_no_retrieval`. Verifiable at the tool-result level. Faithfulness verifier still runs post-generation per spec §3.4.

**Eval reshapes:** WS8's recall@K is measured by calling the retrieval pipeline directly (single-shot mode, deterministic), bypassing the agent. Production calls go through the MCP tool; eval calls go straight to the Python pipeline. Same code, two entry points.

**Considered and rejected:** pure pre-fetched (loses anaphora, fights conversation pattern), unconstrained agent (no refusal-threshold enforcement point, hallucination risk on first turn).

### D8. Pro/Max via YouCoded's existing OAuth

The budget app does not manage authentication. Synthesis traffic flows through YouCoded's existing Claude Code OAuth, paid for by Destin's Claude Code Max subscription.

**Why:** v1 is for Destin to dogfood on his own machine; using his existing subscription is the entire point. API billing is a separate path, deferred to a hypothetical Phase 4 (public deployment) only.

### D9. No vendoring of YouCoded code

The budget repo does not fork, vendor, copy, or symlink YouCoded source files. It connects to YouCoded over its existing remote-server interface (port 9900) and reads from MCP config files YouCoded already manages.

**Why:** vendoring creates a fork-maintenance burden the project doesn't need at v1 scale. The user explicitly rejected this path.

### D10. v1 UI scope is narrower than spec §10 implies

Drop from v1, ship in Phase 2:
- DOCX HTML renderer (mammoth.js / `DocxViewer` component) — only one DOCX in slice; defer.
- "Verify mode" toggle (spec §10.3 synchronized scrolling) — polish.

Keep in v1:
- Chat thread with citation chips
- Side-panel PDF viewer with bbox highlight
- Three refusal banners (spec §11)
- Click-chip-to-jump behavior (spec §10.2)

### D11. `LLMProvider` interface preserved as a seam

Keep spec §4.2's `LLMProvider` interface (~30 lines of TS), but ship exactly one implementation in v1: `YouCodedSessionProvider` (talks to localhost:9900). Other implementations (`LocalCompanionProvider`, `AnthropicAPIProvider`, `SelfHostedLLMProvider`) slot in for Phase 2/3/4 when their use cases become real.

**Why:** preserves the architectural seam without spending time on multiple implementations that v1 doesn't need.

### D12. Volume ingest happens after the vertical slice, covers all four publishers

Once the v1 stack is end-to-end working on the slice, volume ingest runs as a separate workstream. Target corpus for v1 dogfood:

- All 4 publishers (JLBC + Legislature + Gov + AGAO)
- Most-recent FY for each (FY27 baseline, FY26 approps + bills, FY25 AFR, FY27 Gov SAD/S&U)
- All 15 baseline cross-cut s-PDFs + 28 approps cross-cut PDFs already discovered
- 110 per-agency PDFs (FY27 baseline)
- Primers (writing draft + Gov glossary)

Multi-year backfill (FY15–FY24) is Phase 1.5. Same orchestrator, more URLs, no code changes.

**Why:** spec §3 use cases include "Comparison" as a primary archetype, with the canonical example being Governor-vs-JLBC. Without Gov SAD ingested, half the comparison value-prop doesn't work. Original Phase 1a "Week 1" ingest list omitted Gov and AGAO, deferring to "Week 3 backfill." That ordering doesn't survive the vertical-slice reframe — v1 wants all four publishers from the moment retrieval goes live, even if just one FY each.

## What changes in the existing docs

The corresponding amendments to spec, plans, CLAUDE.md, README.md, and MANIFEST.md are landed in the same commit/branch as this decision artifact. See the git log for the branch `phase-1bc-architecture-amendments` for the exact edits.

## Open items still TBD

These are NOT decided here; flagged for follow-up:

- **Citation tool schema final field names + types.** Sketched in D6; nail down before Phase 1c WS3 (system prompt + tool schema).
- **Refusal threshold value.** Spec §11 calls for calibration during Phase 1; placeholder is reranker score < 0.3.
- **Acronym expansion.** Phase 1b WS7's old role; with agent-pattern retrieval, this becomes a system-prompt instruction ("expand acronyms before calling retrieve()") rather than a separate component. Test in WS8 eval; revisit if recall is poor.
- **Cross-cut multi-page table reassembly** (s18 emitting as 13 chunks). Less urgent under D2 since each chunk now stamps to all 25 agencies; revisit if eval shows it matters.
- **bd2 parser** (yields 0 fund rows). Out of scope for retrieval; revisit when fund-catalog cross-source merge is needed.
- **Volume ingest mechanics** — adapt `scripts/run_phase_1a_slice.py` to walk `ingest/discovery.py` for full Week 1 + add Gov SAD + AGAO AFR. Separate session, after the vertical slice.

## Pointer to the conversation

Decision history (the back-and-forth that produced these twelve decisions) lives in the 2026-05-06 working-session transcript. Highlights:

- Original framing of "Phase 1b first WS = volume ingest" called out as horizontal slicing.
- API path proposed (rejected: separate billing).
- `claude -p` proposed (rejected: no native tool calls, no streaming, wrong shape for multi-turn).
- Lift-YouCoded-PTY proposed (rejected: vendoring burden).
- Companion-app-as-MCP-host proposed → simplified to "MCP server registered with running YouCoded."
- Pure agent-pattern proposed → tightened to constrained agent-pattern (forced retrieve() call) for refusal enforcement.
