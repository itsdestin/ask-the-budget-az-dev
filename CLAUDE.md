# CLAUDE.md

Workspace guidance for Claude Code working on **Ask the Budget AZ** — a Q&A tool over Arizona state budget documents (JLBC Appropriations Reports, Baseline Books, AGAO Annual Financial Reports, Governor's Executive Budget proposals).

Everything — app code, ingest pipeline, docs, plans, specs, dev tooling — lives in this single repo. The once-planned split into separate `ask-the-budget-az/` / `ask-the-budget-az-companion/` repos died with the standalone consolidation: the standalone app IS the companion.

## Project North Star

The system's job is **retrieval with auditable provenance**. Answer generation is secondary. A fiscal analyst who can't trust a claim won't use the tool twice.

Read `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` before any non-trivial change — it records the current architecture (decisions S1–S30, Invariants 7–8, gates G1–G3). The invariants section of the original design spec (`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`) is still load-bearing. `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md` is historical background only — the YouCoded/MCP architecture it describes was retired by the consolidation.

**Current project status: @STATUS.md** (auto-loaded into every Claude Code session via the `@file` import). `STATUS.md` is the **single source of truth** for what's shipped, what's open, and what's blocked. The Project Phases table below is a stable conceptual map of the phases (their design intent + where each runs) — it intentionally carries **no status**. If you want to describe what's shipped/open/blocked, that data lives in STATUS.md and **only** in STATUS.md. Do not re-record status here; do not infer status from this file. When STATUS.md and CLAUDE.md disagree about status, STATUS.md is right by construction (this file says nothing about status).

## The app in one paragraph

The app is a single FastAPI process (`app/`, port 9300) serving a built Vite/React SPA (`webapp/`) — home, Budget Documents, Fiscal Notes, Upload, AI Mode, and an admin page, with the secondary destinations behind a tools menu in the nav. Storage is embedded LanceDB (`store/`) with local ONNX models on CPU: `snowflake-arctic-embed-m` embeddings + `ms-marco-MiniLM-L-12-v2` reranker, whose scores are **raw cross-encoder logits (roughly −10..10, negatives are normal)**, not a 0..1 scale. Retrieval (`retrieval/`) is BM25 + dense + RRF + rerank, then two post-rerank penalties (recency, agency/doc-type match), then a refusal check. Query text is parsed for fiscal year, agency and document type before searching. Ingest is a GUI upload → background queue (`ingest/`) → MinerU extract → chunk (`chunking/`) → embed → LanceDB write. AI Mode is an in-process OpenRouter tool loop (`harness/`; system prompt at `harness/system-prompt.md`, rendered by `harness/prompt.py`) that calls `retrieve()` before answering, emits verified citations per claim, and runs `citation/` at turn end to link figures in the answer back to the chunks they came from. **Search, fiscal notes, and upload work with zero API keys**; one OpenRouter key in `<data_dir>/settings.json` plus a chain of switches (master AI Mode toggle → key → per-mode toggle → model choice) unlocks AI Mode. A custom endpoint must additionally declare both per-million prices — without them there is no spending cap, so it is refused at save time. The admin page is gated on the Windows username; that gate is **not authentication** and must not be described as such. The corpus + settings live on the shared drive (`JLBC_DATA_DIR`, then a per-machine pointer file, then the dev default `data/insight-data/`). No Postgres, no Docker, no Voyage, no `.env.local`, no YouCoded — anywhere. Run it: `cd webapp && npm run build` once, then `uv run uvicorn app.main:create_app --factory --port 9300`.

## Core Invariants (override anything else when in conflict)

1. **Every claim is auditable.** No claim renders without a passing citation. Citations link to exact PDF page + bbox highlight in the side panel.
2. **Citations are verified, not just emitted.** Post-generation faithfulness check runs on every citation. Failed citations are visibly stripped, not silently dropped or quietly accepted.
3. **Refusal beats hallucination.** When the system can't ground an answer, it says so and shows the raw chunks. High refusal rate = fixable. Confident hallucination = trust-destroying.
4. **No automated action on outputs.** The tool informs analysts; analysts decide. No workflow ever triggers on a system-generated answer.
5. **No "hallucination-free" or "grounded" marketing language.** Stanford's Lexis study (2024) is the canonical reason. Honest about limits or we don't ship.
6. **Internal first, public later, never until earned.** Phase 4 (public) is gated on hard metrics defined in the spec. Not vibes.

## Working Rules

**Never touch a running production deployment to debug it.** All testing happens against a local dev instance or a deliberately-isolated test environment.

**Always sync before working.** `git fetch origin && git pull origin master`. Several Claude sessions run against this repo at once and master moves in large merges; check it again immediately before you merge, not just when you start.

**Use worktrees for non-trivial work.** Any work beyond a handful of lines goes in a separate git worktree at `~/ask-the-budget-az-worktrees/<branch-name>/`. Prevents concurrent sessions from overwriting each other.

**Annotate non-trivial code edits with a WHY comment.** Destin is a non-developer relying on comments to understand what code does and why. Record the *evidence* that drove a choice, not just the choice — a comment saying which measurement rejected the obvious alternative is what stops it being re-tried in six months.

**"Merge" means merge AND push.** Don't stop at a local merge.

**Pushing to master green-lights closing the dev server.** If you started one to verify a change, shut it down once the commit lands on `origin/master`.

**Clean up worktrees after merging.** `git worktree remove <path>` then `git branch -d <branch>`.

**Sample primary sources go in `samples/raw-<format>/` and are committed.** When Destin uploads a primary-source document (legislative bill DOCX, agency report) that can't be auto-fetched from a public URL the way JLBC PDFs can, drop it under `samples/raw-<format>/` and commit it. These are load-bearing test fixtures; treating them as gitignored runtime data means they're lost on every fresh clone and he has to re-upload. PDFs are different — `samples/raw-pdfs/` is gitignored because `DownloadCache` re-fetches them on demand.

## Measurement discipline

This is the part of the workflow that most often goes wrong, and every rule here was bought with a real defect.

**Gate on the ERROR rate, not the production rate.** Ask "how often is this wrong?", never "how often does it fire?". Citation linking shipped a measured 92.9% *coverage* — how often a link was produced — and ~2,000 passing tests missed that 34% of links could point at the wrong document. Coverage rises as a matcher gets looser. So does harm.

**Run a CONTROL, not a remembered baseline.** This machine is often under heavy load from other sessions, and absolute latency swings 70% because of it. Re-run the unmodified code *now*, on the same machine, and compare against that. A recorded number from this morning is not a control.

**Compare only across identical query sets.** Layer 1 recall is not comparable when `eval/queries.yaml` changed. Adding four queries moved recall@15 from 97.62% to 91.30% with no code change at all — which reads exactly like a regression.

**Pass explicit `--weights` grids to any sweep.** The derived grid is coarse. `sweep_recency` once stepped 0.585, never tested 0.85, and shipped 2.064 as "the smallest weight that works". Never take a sweep's printed recommendation without checking what it was allowed to consider.

**Pick a plateau's CENTRE when the metric degrades on both sides**, its safe edge when only one side is safe. "Largest weight that costs nothing" is not a universal rule.

**Three ranking constants are COUPLED and must move together:** `RECENCY_BOOST_PER_YEAR` (`retrieval/recency.py`), `MATCH_PENALTY` (`retrieval/agency_boost.py`), and `REFUSAL_THRESHOLD` (`harness/constants.py`). All three feed the `top_score` that refusal is compared against. `tests/test_recency.py::test_the_shipped_weight_and_refusal_threshold_move_together` fails if one moves alone — that guard has caught a real silent-refusal bug, so do not weaken it. Any post-rerank adjustment must be a **penalty on non-matching chunks, never a bonus on matching ones**, or it inflates `top_score` and quietly weakens refusal.

**`eval/calibrate_refusal.py` needs `--result <path>`** or it grabs the newest file in `eval/results/`, which may be a sweep JSON, and dies with `KeyError: 'per_query'`.

**A guard that fires twice is telling you the design is wrong.** Two exemptions is the signal to measure the policy, not to add a third exemption.

**A per-item check cannot find a cross-item defect.** ~2,900 passing tests missed 721 documents stamped as an agency they never mention and 218 carrying a *different* agency's name, because every check asks "is this item correct?" and nothing asks "do these items agree with each other?". When a field has more than one producer, the test that matters compares the producers' output — not each producer against its own spec. See `docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md`.

**A "fixed" claim in STATUS.md is a hypothesis until you check the data.** *"Catalog debris removed"* was true of the query resolver and false of the corpus, which is where the damage was; *"six documents would mint a different id"* was 22 once every year was checked instead of two. Both had shipped, both read as closed, and both were wrong in the direction that costs you a day.

## Testing conventions

**Mechanism goes in pytest; quality goes in the eval.** Pipeline tests monkeypatch the two Lance search legs and inject fake embedder/reranker (see `tests/test_pipeline.py`) — nothing in `tests/` may open a real LanceDB directory or load ONNX weights, or the suite stops running on a fresh clone. "Does this query return the right documents?" is a *quality* question and belongs in `eval/`, measured against a baseline.

**Guard against real data where you can.** `tests/test_query_understanding_eval_safety.py` checks the query parsers against the eval set's own ground truth and runs in under a second. It caught two shipped defects before any eval run was spent, and then caught the design flaw that changed the feature. Prefer this shape over a hand-maintained list that cannot guard itself.

**Assert behaviour, not mechanism.** A test pinned to *which* stoplist holds a value breaks when the value is moved to a stricter one — an improvement failing as a regression.

**Run the eval after any change to `retrieval/`, `ingest/`, `chunking/`, `citation/`, or `harness/system-prompt.md`.** `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`). Commit the `eval/results/<...>.{json,md}` files alongside the code change so regressions are visible in the diff. There is also `eval/navigational_check.py` for "show me this agency's document" queries, which recall@k scores badly, and a Layer 2 agent-loop eval that **spends real money** — see `eval/README.md` before running that one.

> ⚠ **`eval/refresh_chunk_ids.py` was deleted** with the Postgres tooling and nothing replaces it. Nothing re-binds stale eval `chunk_id`s after a re-ingest — read `eval/README.md` → "After a re-ingest" before any from-scratch corpus rebuild.

## Working efficiently

**A worktree needs a venv.** `ln -s <main-repo>/.venv <worktree>/.venv` — the packages are the same and it costs nothing, where `uv sync` per worktree costs minutes.

**Parallelize on disjoint FILE SETS, not on tasks.** Two tasks that touch the same file cannot run concurrently no matter how independent they sound; give each agent its own worktree branched off your work, then merge. Read the plan's file list first and group by file, not by task number.

**Tell a subagent what NOT to touch.** The most common failure is an agent helpfully editing a file another agent owns.

**Probe the corpus before trusting a plan's fixture.** Plans are written before the data is checked. A plan's "this returns zero results" example returned 1,670 chunks; its `agency:ada` did not exist. One `store.chunk_store.ChunkStore().scan(...)` call settles it.

**Read a subagent's report critically.** They are usually right and occasionally confidently wrong. Verify a surprising claim before acting on it.

## Workspace Layout

One repo, one process. Every directory here is live code.

| Directory | What it is |
|-----------|------------|
| `app/` | FastAPI app server (port 9300) — API routes + serves the built SPA |
| `webapp/` | Vite + React SPA — home, Budget Documents, Fiscal Notes, Upload, AI Mode, admin |
| `harness/` | AI Mode — in-process OpenRouter tool loop, settings, spend ledger, system prompt |
| `retrieval/` | Retrieval pipeline, query parsers, ranking penalties, citation validation |
| `citation/` | Post-answer figure linking — extract figures, locate them in retrieved chunks, annotate |
| `store/` | Embedded LanceDB storage layer + local ONNX model wiring |
| `ingest/` | GUI ingest queue — jobs, SMB-safe lock, worker, MinerU runner, LanceDB writer |
| `chunking/` | Per-publisher extractors + chunkers, entity stamper, agency catalog loader |
| `funds/` | Fund catalog + parser (corpus-side fund resolution) |
| `users/` | Who is running this process (`whoami.py`, the ONE username resolver + same-person rule) and the shared roster of people who have opened the app (`registry.py`, one JSON file per person under `<data_dir>/users/`, written only by that person's own machine). Admin decisions about people (limits, no-limit, hidden) stay in `settings.json` |
| `primer/` | Domain primer/glossary tooling + fiscal-note chunker |
| `eval/` | Layer 1 retrieval eval, Layer 2 agent eval, calibration sweeps |
| `packaging/` | Windows bundle builder + launcher |
| `scripts/` | One-off and build-time tools — catalog builders, audits, migration-era records |
| `tests/` | The pytest suite (webapp tests live in `webapp/`) |
| `samples/` | Committed source documents + the 157-agency `entity-catalog.yaml` |
| `data/` | Corpus, caches, catalogs. `data/insight-data/` is the dev corpus (gitignored) |
| `docs/` | Specs, plans, investigations, decisions, reference material |

**The retired pre-consolidation trees are GONE, deleted 2026-08-01**: `web/` (Next.js UI), `mcp-server/` (Budget MCP server), `db/` (Postgres), and the dead `retrieval/` modules (`api.py`, `bm25.py`, `dense.py`, `rerank.py`, `sql.py`). They live in git history — `git log --diff-filter=D -- web/` finds the deletion. **Comments across ~35 files cite `web/…` paths as provenance** ("ported from web/components/ChatThread.tsx"); those resolve against history and are honest attribution, not stale references to fix.

## Handoff prompts

`PROMPT-*.md` files at the repo root are long-running handoffs. **`STATUS.md` decides which are live** — this list is only a map, and a file existing does not mean it should be executed.

- [`PROMPT-retrieval-accuracy-regression.md`](PROMPT-retrieval-accuracy-regression.md) — the post-backfill accuracy regression (`key_fact_rate` 0.81 → 0.66, 74% of misses never retrieved) and the unfinished glm-vs-deepseek agent head-to-head. **Needs an OpenRouter key and spends real money.**
- [`PROMPT-attested-citation-baseline.md`](PROMPT-attested-citation-baseline.md) — the live baseline for attested citation linking; measures marker compliance, which nothing offline can. **Needs an OpenRouter key and spends real money.** Supersedes `PROMPT-citation-linking-baseline.md`, which is now historical.
- [`PROMPT-plan5-session-c.md`](PROMPT-plan5-session-c.md) — the Administrator Handbook (Plan 5 Track 5).
- Everything else at the root — `PROMPT-z13-backfill.md` (the backfill it describes is complete), `PROMPT-volume-ingest.md`, `PROMPT-parallel-*.md`, `PROMPT-plan1..4`, `PROMPT-plan5-session-{a,b}.md`, `PROMPT-plan5-track4-cleanup.md` — is a **shipped historical record. Do not execute.**

## Project Phases

A **conceptual map** — what each phase IS and where it runs. Status is intentionally absent; that lives in `STATUS.md`.

| Phase | What it is | Where it runs |
|---|---|---|
| **Phase 0 — Investigation** | Per-doc-type extractor routing, 157-agency canonical catalog, JLBC four-layout structure mapping, chunk-shape decisions D1–D7. | Destin's machine |
| **Phase 1a — Ingest + chunking** | Per-publisher extractor + chunking pipeline. Hand-off contract at `data/chunks/MANIFEST.md`. | Destin's machine |
| **Phase 1b — Storage + retrieval** | Postgres + pgvector + ParadeDB hybrid pipeline. **Superseded by the standalone consolidation** — storage is now embedded LanceDB + local ONNX models. | Destin's machine |
| **Phase 1c — Synthesis + UI** | Budget MCP server + FastAPI sidecar + Next.js chat UI, hard-depending on a running YouCoded instance. **Superseded** — synthesis is now the in-process `harness/` loop inside `app/`. | Historical |
| **Standalone consolidation — Plans 1–7** | The current architecture: embedded LanceDB + local models (1), one FastAPI app + Vite SPA (2), GUI ingest queue (3), in-process OpenRouter AI Mode (4), admin UI + packaging + legacy deletion (5), document-type registry (6), batch extraction (7). Spec at `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`. | Office machines off the shared drive |
| **Phase 2 — Distribution + verify mode** | The companion goal was absorbed by the consolidation; distribution and verify mode remain. | Each analyst's machine |
| **Phase 3 — Internal pilot** | Wider JLBC use. Tier 2 entity resolution. Eval set expansion. | Same |
| **Phase 4 — Public-launch consideration** | Gated on hard metrics in the spec. | Same, plus public host |

## Documentation Structure

- `docs/superpowers/specs/` — design specs, one per major decision area
- `docs/superpowers/plans/` — implementation plans, derived from specs
- `docs/superpowers/investigations/` — research memos, Phase 0 findings, ad-hoc investigations
- `docs/superpowers/decisions/` — decision artifacts that supersede portions of specs/plans
- `docs/reference/` — domain primers and reference material (the system-prompt-context primer lives at `data/system-prompt-context.md`)
- `.claude/rules/` — auto-loaded rules for specific subsystems (currently empty)

**A plan is a hypothesis, not a specification.** Plans here are written before the data is checked, and several have been wrong in ways that only measurement caught. When a plan's instruction conflicts with a measurement, the measurement wins — implement what is right, and record the deviation with the numbers on both sides at the code and in `STATUS.md`.

## Compaction Guidance

When compacting context (`/compact`), always preserve:
- The current task objective and success criteria
- The Core Invariants section above
- Architectural invariants discovered during this session
- Measurements taken this session, with the conditions they were taken under
- File paths of files currently being modified
- Uncommitted work state

Do NOT preserve: full file contents already read, intermediate debugging output, or resolved sub-tasks.
