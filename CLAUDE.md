# CLAUDE.md

Workspace guidance for Claude Code working on **Ask the Budget AZ** — a Q&A tool over Arizona state budget documents (JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, Governor's Executive Budget proposals).

This workspace repo holds cross-cutting docs, plans, specs, and dev tooling. Sub-repo code lives in separate folders (e.g., `ask-the-budget-az/` for the web app, `ask-the-budget-az-companion/` for the JLBC Budget Agent companion app once it exists).

## Project North Star

The system's job is **retrieval with auditable provenance**. Answer generation is secondary. A fiscal analyst who can't trust a claim won't use the tool twice.

Read `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` before any non-trivial change. The invariants section is load-bearing. Also read `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md` for the v1 architectural decisions that shape Phase 1b/1c.

## v1 in one paragraph

v1 is a multi-turn budget Q&A web app that runs on Destin's machine and **hard-depends on a running YouCoded instance** for synthesis. The budget app's Node backend talks to YouCoded over `ws://localhost:9900`; YouCoded provides the Claude Code session, Pro/Max OAuth, PTY/wrapper, and MCP host. A small Budget MCP server (separate Node process, registered with YouCoded) exposes `retrieve(query, filters)` and `cite(...)` tools. Claude in each conversation calls `retrieve()` (constrained agent pattern — system prompt requires it before answering) and emits `cite()` per claim. The budget UI is a chat thread with citation chips and a side-panel PDF viewer. Standalone companion app, DOCX viewer, verify-mode toggle, and multi-analyst distribution all defer to Phase 2. v1's corpus targets all four publishers (JLBC + Legislature + Gov + AGAO) for the most-recent FY each. See decisions doc D1–D12 for rationale.

## Core Invariants (override anything else when in conflict)

1. **Every claim is auditable.** No claim renders without a passing citation. Citations link to exact PDF page + bbox highlight in the side panel.
2. **Citations are verified, not just emitted.** Post-generation faithfulness check runs on every citation. Failed citations are visibly stripped, not silently dropped or quietly accepted.
3. **Refusal beats hallucination.** When the system can't ground an answer, it says so and shows the raw chunks. High refusal rate = fixable. Confident hallucination = trust-destroying.
4. **No automated action on outputs.** The tool informs analysts; analysts decide. No workflow ever triggers on a system-generated answer.
5. **No "hallucination-free" or "grounded" marketing language.** Stanford's Lexis study (2024) is the canonical reason. Honest about limits or we don't ship.
6. **Internal first, public later, never until earned.** Phase 4 (public) is gated on hard metrics defined in the spec. Not vibes.

## Working Rules

**Never touch a running production deployment to debug it.** All testing happens against a local dev instance or a deliberately-isolated test environment. (Mirrors the rule from `~/youcoded-dev/CLAUDE.md`.)

**Always sync before working.** Before any change, plan, or investigation:
```bash
cd <repo> && git fetch origin && git pull origin master
```

**Use worktrees for non-trivial work.** Any work beyond a handful of lines must be done in a separate git worktree (or use the Agent tool with `isolation: "worktree"`). Prevents concurrent Claude sessions from overwriting each other. Worktrees live at `~/ask-the-budget-az-worktrees/<branch-name>/`.

**Annotate non-trivial code edits with a WHY comment.** Destin is a non-developer relying on comments to understand what code does and why. Example: `// Strip citation chip when faithfulness check returns < 0.7 — better to show "no source" than fake confidence.`

**"Merge" means merge AND push.** Don't stop at a local merge.

**Verify cross-cutting changes on both the retrieval and citation paths.** A change to chunking can break citations downstream. A change to the LLM prompt can quietly tank the eval set. Run the eval set whenever the retrieval pipeline or LLM prompt changes.

**Pushing to master green-lights closing the dev server.** If you started a local dev server to verify a change, shut it down once the commit lands on `origin/master`. Don't leave orphan processes.

**Clean up worktrees after merging.** `git worktree remove <path>` then `git branch -D <branch>`. Stale worktrees confuse future sessions.

**Sample primary sources go in `samples/raw-<format>/` and are committed.** When the user uploads a primary-source document (legislative bill DOCX, agency report, etc.) that can't be auto-fetched from a public URL the way JLBC PDFs can, drop it under `samples/raw-<format>/` (e.g. `samples/raw-docx/`) and commit it. These files are load-bearing for the slice and Phase 1b's retrieval tests; treating them as gitignored runtime data means they're lost on every worktree create / fresh clone, and the user has to re-upload. PDFs are different — they live under `samples/raw-pdfs/` (gitignored) because the DownloadCache fetches them from public URLs on demand.

## Workspace Layout (planned)

| Directory | Repo | What it is |
|-----------|------|------------|
| `ask-the-budget-az-dev/` | (this) | Workspace repo: docs, plans, specs, dev tooling, ingest pipeline (currently colocated), retrieval pipeline (Phase 1b), MCP server + web app (Phase 1c) |
| `ask-the-budget-az/` | (later, Phase 2) | If we split, the deployable web-app artifact moves here |
| `ask-the-budget-az-companion/` | (later, Phase 2) | Standalone companion app — only built when distributing to analysts who don't run YouCoded |

Sub-repo code goes in the relevant sub-repo. Workspace-level artifacts (specs, plans, investigations, decisions, cross-cutting docs, this `CLAUDE.md`, `.claude/rules/`, dev tooling) get committed to this workspace repo. For v1, most code lives in this repo (separation can wait until Phase 2 deployment).

## Active handoffs

If you're starting a fresh session and the user asks you to pick up "volume ingest" or similar Phase 1b corpus-expansion work, read [`PROMPT-volume-ingest.md`](PROMPT-volume-ingest.md) at the repo root first. It's a self-contained handoff prompt for a desktop session with a beefier GPU; the goal is to widen the corpus from the 5-doc validated slice (JLBC + Legislature only) to all four publishers (adds Governor + AGAO) per architecture decision D12.

## Project Phases

| Phase | Status | What happens | Where it runs |
|---|---|---|---|
| **Phase 0 — Investigation** | ✓ closed 2026-05-06 | Per-doc-type extractor routing decision, 157-agency canonical catalog, JLBC four-layout structure mapped, chunk-shape decisions D1–D7. | Destin's machine |
| **Phase 1a — Ingest + chunking** | ✓ closed 2026-05-06 (slice-validated) | Tag `phase-1a-validated-slice` at `9ba0385`. 5 docs / 161 chunks / 91.3% agency-stamped / 227 funds. Pipeline proven on real source. Hand-off at `data/chunks/MANIFEST.md`. | Destin's machine |
| **Phase 1b — Storage + retrieval** | ✓ shipped on slice 2026-05-07; WS8 awaits volume corpus | Postgres + pgvector + ParadeDB schema (D2 array agency stamping). WS1 (infra), WS2 (loader), WS3 (Voyage embeddings), WS4 (BM25), WS5 (dense), WS6 (RRF + Voyage rerank-2.5 + `retrieve()`), WS7 (public API via `retrieval/__init__.py`) all merged to master. End-to-end smoke validated against the 161-chunk slice — Aviation Fund query surfaces s18 chunks via BM25 → dense → RRF → rerank. WS8 (eval set + recall@K) blocked on volume ingest. **373 pytest passing.** Plan at `docs/superpowers/plans/2026-05-06-phase-1b-storage-and-retrieval.md`. | Destin's machine |
| **Phase 1c — Synthesis + UI** | in progress (reframed 2026-05-06) | **Shipped:** WS1 Budget MCP server (`mcp-server/`) ✓; WS6 FastAPI retrieval sidecar (`retrieval/api.py`, bundled with WS1) ✓; WS2 `LLMProvider` + `YouCodedSessionProvider` (`web/lib/`) ✓; WS4a Next.js chat skeleton (`web/app/`, `web/components/`, `web/state/`, generic ToolCard with JSON fallback) ✓; WS4b per-tool ToolBody views + CitationChip + RefusalBanner ✓; WS4c PdfViewer with bus subscription, `/api/pdf/[doc_id]` Range serving, pdfjs-dist canvas render + bbox highlight ✓; **WS4d UI refresh + JLBC mascot** (civic-warm theme, single-mascot architecture, seated typing scene, welcome hero + suggestion chips, speech-bubble messages, page pinned, bottom-anchored messages, message-column edges aligned with input-box edges) — **shipped (merged to master 2026-05-19)**; plan at `docs/superpowers/plans/2026-05-15-ui-prettify-mascot.md`, spec at `docs/superpowers/specs/2026-05-15-ui-prettify-mascot-design.md` (read the "Post-implementation reconciliation" section for what shipped vs. what was originally specified). **176/176 vitest passing, 345/345 pytest passing** (vitest count up from 109 thanks to the mascot/UI test additions). **Pending:** WS3 (faithfulness verifier — needs spike), WS5 (audit log writes — schema exists, no writer; this also unlocks refusal auto-detection wiring into the already-built `RefusalBanner` AND the already-built `crossed`-arms mascot path: `useMascotPose(state, refusalActive)` accepts the boolean, v1 passes `false`), WS7 (eval expansion — blocked on volume corpus). Plan at `docs/superpowers/plans/2026-05-06-phase-1c-companion-and-ui.md`. | Destin's machine + running YouCoded |
| **Phase 2 — Standalone companion + first deploy** | not started | Build standalone companion (lifts YouCoded PTY/wrapper into separate process). Add DOCX viewer + verify mode. Deploy to free-tier hosting. Onboard 2-3 trusted analysts. | Vercel/Supabase + each analyst's machine |
| **Phase 3 — Internal pilot** | not started | Wider JLBC use. Tier 2 entity resolution. Eval set expansion. | Same |
| **Phase 4 — Public-launch consideration** | not started | Gated on hard metrics in the spec. | Same, plus public host |

## Documentation Structure

- `docs/superpowers/specs/` — design specs, one per major decision area
- `docs/superpowers/plans/` — implementation plans, derived from specs
- `docs/superpowers/investigations/` — research memos, Phase 0 findings, ad-hoc investigations
- `docs/superpowers/decisions/` — decision artifacts that supersede portions of specs/plans (e.g., `2026-05-06-phase-1bc-architecture.md` for the v1 reframe)
- `docs/reference/` — domain primers and reference material (e.g., the JLBC writing draft used as system-prompt context)
- `.claude/rules/` — auto-loaded rules for specific subsystems (e.g., `live-app-safety.md` once we have a deployed instance)

## Compaction Guidance

When compacting context (`/compact`), always preserve:
- The current task objective and success criteria
- The Core Invariants section above
- Architectural invariants discovered during this session
- File paths of files currently being modified
- Uncommitted work state

Do NOT preserve: full file contents already read, intermediate debugging output, or resolved sub-tasks.
