# Project Status

**Last updated:** 2026-08-01

This file is the single source of truth for what's shipped, what's
open, and what's blocked. The phase plans under `docs/superpowers/`
remain as the historical record of design intent — but those plans
have NOT been updated as features shipped, so use this file (not the
plans) to understand current state.

`CLAUDE.md` auto-imports this file via `@STATUS.md`, so every Claude
Code session sees the latest contents in context. **Do not duplicate
status info into CLAUDE.md** — every duplication is a future drift
source. When something ships, update only this file.

---

## Phase summary

| Phase | Status | Notes |
|---|---|---|
| Phase 0 — Investigation | ✓ Done (2026-05-06) | Findings memo + chunk-shape + data-model docs |
| Phase 1a — Ingest + chunking | ✓ Done on slice (2026-05-06), volume ingest substantially complete (2026-05-12) | 382 docs / 7,755 chunks; missing older FYs + a few in-cycle gaps |
| Phase 1b — Storage + retrieval | ✓ Done (slice 2026-05-07, volume-validated implicitly, WS8 eval harness shipped 2026-05-22) | Hybrid pipeline live and serving 7K+ chunks; eval harness baseline: recall@5 86%, recall@20 100% on 34-query set |
| Phase 1c — Synthesis + UI | ⬛ Superseded by Standalone consolidation (Plans 1–4) | The MCP/sidecar/Next.js stack it shipped is retired; faithfulness verifier (WS3) + audit log (WS5) remain unbuilt and carry forward |
| Volume ingest / S20 backfill | 🟡 **IN PROGRESS on the Z13** (2026-07-31) | Fiscal-note back catalogue ~65% done (1,384 of 2,126 notes, sessions 2026→2008); JLBC book editions not started. See the Z13 section below |
| Phase 2 — Companion + verify-mode | 🔴 Not started | Defers until v1 demonstrates internal value |
| Standalone consolidation — Plan 1 (storage + retrieval) | ✓ Shipped (2026-07-30) | Postgres/pgvector/ParadeDB → embedded LanceDB; Voyage → local ONNX models. See the section below |
| Standalone consolidation — Plan 2 (app server + search UI) | ✓ Shipped (2026-07-30) | New `app/` (port 9300) + `webapp/` SPA: home, budget search (real corpus), fiscal notes directory. See the section below |
| Standalone consolidation — Plan 3 (ingest) | ✓ Shipped (2026-07-31) | GUI upload → background queue → LanceDB; fiscal-note refresh; Add-a-JLBC-book. Postgres/Docker now needed for NOTHING. See the section below |
| Standalone consolidation — Plan 4 (AI Mode) | ✓ Shipped (2026-07-31) | In-process OpenRouter tool loop; MCP and YouCoded dropped. Cited chat + PDF viewer on both corpora, Standard/Deep-Research tiers, per-user spend ledger. See the section below |
| Standalone consolidation — Plan 5 (admin + packaging + deletion) | 🟡 **Tracks 1–4 done, 5–6 open** (2026-08-01) | 20 of 27 tasks. Tracks 1–2 (1–13, Session A): admin identity + gate, settings API, OpenRouter catalog, model fallback, corpus health/restore, Admin + Settings pages, per-machine data dir, health ladder, lockout recovery. Track 3 (14–17, Session B): the Windows bundle. **Track 4 (18–20) shipped 2026-08-01** — `web/`, `mcp-server/`, `db/` and the dead `retrieval/` modules are DELETED (~36,000 lines), one `documents.json` reader, four ingest defects fixed, and all three of Session B's orphaned app-side asks built. **Track 5 (handbook, 21–23) and Track 6 (gates, 24–27) remain.** See the Track 4 section below |

## Corpus — what is ingested and what is NOT (2026-08-01)

**The corpus is MVP-complete for recent years. It is NOT finished.** Recorded
here because the deferral previously existed only as a comment in
`~/backfill-scripts/orchestrate.py`, which is not in this repo.

**In the corpus:** 24,841 budget chunks + 13,278 fiscal-note chunks / 3,527
documents. JLBC Baselines FY2022–2027 and Approps FY2022–2026 (11 editions),
the complete fiscal-note back catalogue (2,104 notes, sessions 2026→1999),
and exactly **three** other documents — one AFR (FY2025), one executive budget
(FY2027), one budget bill (FY2026).

| Remaining work | Count | Blocked by |
|---|---|---|
| **JLBC books, pre-FY2022** | **27 editions** (Baselines FY2012–2021, Approps FY2005–2021) | Nothing — deferred by Destin's MVP call 2026-07-31. Run with `JLBC_BACKFILL_UNITS=books` |
| **Annual Financial Reports** | 3 (FY2022–24) | **`gao.az.gov` is behind Cloudflare bot management** — see below. Needs a human with a browser |
| **Executive budgets** | ~~2~~ **0 — INGESTED 2026-08-01** | done (FY2025 + FY2026 now live) |
| **Budget bills** | 7 (FY2022–2027) | S24 — the harvest holds **PDFs**, and budget-bill is **DOCX-only** by design. Word versions come from JLBC internally |
| **Agency budget requests** | 78 (FY2027 only) | **Plan 6 Track 1** — `agency-budget-request` is not a registered doc_type. 60 reachable, **18 behind bot protection** needing a human with a browser |

**So: 5 documents can be ingested with no new code; 85 need Plan 6's registry;
27 book editions are a deliberate deferral, not an oversight.**

**The AFRs cannot be fetched automatically (2026-08-01).** All four failed with
HTTP 403. Two distinct causes, found in that order:

1. `ingest/cache.py` sent no User-Agent, so it identified as `python-requests`
   and the WAF rejected it outright. **Fixed** in `e198074` (browser UA, with
   the measurements in the code comment). This was real and worth fixing — it
   would have hit other hosts too.
2. Underneath that, **`gao.az.gov` sits behind Cloudflare bot management.** The
   403 body is the "Just a moment…" JavaScript challenge (`server: cloudflare`);
   after ~15 requests it challenges the IP and even `gao.az.gov/` returns 403.
   No header defeats this — it requires executing JS in a real browser, and
   working around it is not something this project should do.

**Therefore the 3 AFRs are a MANUAL step**, in the same category as the 18
bot-blocked agency budget requests: download them in a browser, then add them
through the app's Upload page (which is the designed path — it carries the
Invariant 8 public-record confirmation). The URLs are in the mockup index.
Record this in the handbook next to the agency-request list.

Sources and verified URLs for all of the above are in the website mockup's
5,854-row index (`webapp/reference/assets/search/index-lite.js`), which spec
**S28** turns into `data/document-catalog.json`. Plan 6 Task 16 ingests the
backlog. Earlier years of agency budget requests are NOT harvested and live on
78 separate agency websites with no shared URL convention — a research project,
not a crawl.

## 🔴 FY2024 AFR ingested but effectively EMPTY (2026-08-01)

**Found immediately after ingest, by comparing passage counts.** All four AFRs
report `live`; three are fine and one is not:

| doc | pages | passages | tokens |
|---|---|---|---|
| `agao-afr-fy2021` | 163 | 169 | — |
| `agao-afr-fy2022` | 178 | 182 | — |
| `agao-afr-fy2023` | 184 | 189 | 758,497 |
| **`agao-afr-fy2024`** | **191** | **20** | **5,673** |

FY2024 yielded chunks only from pages 58 and 184–191; **pages 1–183 produced
nothing**, and its first chunk is a "THIS PAGE INTENTIONALLY LEFT BLANK" marker.

**Not a bad download and not a scan.** The PDF is tagged (`StructTreeRoot`
present) and its mid-page carries 8,700 characters of text — *more* than
FY2023's 5,076. The source is fine.

**Root cause: the publisher changed how it tags the document between years.**
On page 100, FY2023 emits **1 table block** (rows/columns, 235 KB of page JSON)
where FY2024 emits **17 paragraph blocks** (24 KB). GAO tagged FY2023's
financial statements as tables and FY2024's as loose paragraphs.
OpenDataLoader reported each faithfully; `chunking/builder.py` builds table
chunks then narrative, and found almost nothing it recognised in the paragraph
form.

**Why this matters more than one document:** a publisher silently changing
structure between editions is a recurring hazard for a corpus meant to be fed
for years by non-technical staff, and **nothing flagged it** — the job says
`live`, the queue is green, and an analyst searching FY2024 AFR content simply
gets nothing and concludes the corpus lacks it.

**This is exactly the S27 gate case, now with a real example**: a chunks-per-page
floor (~0.10 here vs ~1.03 for its three siblings) would have quarantined it
with an actionable reason. Use these four documents as the S27 calibration
fixture — they are a rare clean control, same publisher and near-identical page
counts.

**Open decisions** (deliberately not made at 2 AM): whether to re-route this
document to MinerU (S26's detect-don't-declare would do it automatically),
whether the narrative chunker should handle paragraph-tagged tables, and
whether to delete the near-empty document meanwhile so search does not answer
"nothing" for FY2024.

## ✅ `eval/queries.yaml` can now measure the recency boost (2026-08-01)

**FIXED — and the first thing it measured is a real cost.** Thirteen no-year
queries (`n-001`..`n-013`) with FY2022–2024 ground truth were added to
`eval/queries.yaml`. Coverage went from **0 of 34** queries exercising the
recency path to **13 of 47**, and the set now holds pre-FY2025 ground truth
(FY2022 ×9, FY2023 ×4, FY2024 ×4 chunks) for the first time.

**What the new instrument reports about the shipped weight
(`RECENCY_BOOST_PER_YEAR = 2.064`), same corpus, boost the only variable:**

| weight | n-* recall@5 | n-* recall@15 |
|---|---|---|
| 0.000 | **100.0%** (13/13) | 100.0% |
| 2.064 (shipped) | **76.9%** (10/13) | 100.0% |

**The boost costs 23 points of top-5 recall on old targets and costs nothing
at @15.** Ten of the thirteen sit at rank 1 with the boost off; five are
demoted and three fall out of the top 5 — `n-003` 1→8, `n-010` 1→7, `n-013`
1→8. The recurring shape is a newer near-duplicate that says *"no funding for
this program"* outranking the single edition that funded it. Worst case:
"Which appropriations did the Governor line-item veto?" puts three FY2026/27
boilerplate passages about the veto *process* above the only veto-summary
document in the corpus.

**This is a trade, not a defect** — @15 is what gate G1 measures, AI Mode reads
all 15 chunks, and the chronological-ordering win is real. But it is now a
trade with numbers on both sides, which it was not when 2.064 was chosen.
Re-decide it during the post-backfill sweep (Plan 7 Task 6).

Whole-set eval, before → after adding the block: recall@5 62.07% → **66.67%**,
recall@15 96.55% → **97.62%**, recall@20 100% → **100%**. **No existing query
changed status or rank** — the movement is entirely the new entries, which
score better at @5 than the incumbent set. Guards: `test_sweep_recency.py`
now asserts coverage stays non-zero, that pre-2025 ground truth survives, and
that no `n-*` question ever acquires a fiscal year (the silent-failure case —
layer 1 would filter it and the entry would keep printing a plausible number
while measuring nothing).

Two things deliberately NOT done: no AGAO AFR entries (the AFRs are
near-identical fund tables edition over edition, so an undated question about
a fund is legitimately answered by the newest one — pointing it at FY2022
would be ground truth invented to fail), and no FY2021 entries (the FY2021
AFR is the only FY2021 material and has the same problem).

<details><summary>The original finding, kept as the record of what was wrong</summary>

Found during the Phase D sweep and **verified independently**: of the 34 queries
in the Layer 1 budget eval, **32 name a fiscal year**, so S21 layer 1 hard-filters
them and the recency boost never executes. The other 2 are refusal queries with
no ground truth. **Zero queries exercise the code path.**

That matters beyond recency: the flat `cur@5 / cur@15 / cur@20` column across an
entire weight sweep looks like proof of safety and is nothing of the kind — it
is proof the set never ran the code. Any future "no regression" claim from this
set about ranking policy is worthless until it has no-year coverage.

**Second gap, same file:** every ground-truth chunk in it is **FY2025 (9),
FY2026 (12), FY2027 (13)** — nothing older. The set predates the backfill, so
**nothing in the repo can currently measure harm to an older target.** The
sweep's `prx@` columns (explicit-year queries with the year stripped, original
ground truth kept) are a stand-in and are **optimistic**, because their targets
are all recent and the boost helps recent targets.

Fix: add no-year queries with pre-FY2025 ground truth to `eval/queries.yaml`.
This is a prerequisite for trusting any ranking-policy change — S30's section
boost has the same blind spot.

</details>

## What's next

- **🔵 RUNNING NOW — S20 backfill on the Z13** (`PROMPT-z13-backfill.md`).
  Phase A (parity gate) and Phase B (recency machinery) are DONE and merged.
  Phase C (the backfill itself) is ~65% through the fiscal notes with the
  38 book editions still to come; ~6 h remaining at the current rate.
  Phase D (recency + refusal calibration) is BLOCKED until the corpus is
  complete. Nothing else in this list touches the ingest path, so all of it
  is safe to work in parallel.
- **Parallel work available NOW** (safe alongside the running backfill — all
  disjoint from the ingest path). Handoff prompts at the repo root:
  ~~[`PROMPT-parallel-ai-hardening.md`](PROMPT-parallel-ai-hardening.md)~~
  **DONE 2026-07-31** — S22 + S23 shipped, merge `5e1ae3b`; see the section
  below,
  [`PROMPT-parallel-ingest-defects.md`](PROMPT-parallel-ingest-defects.md) (the
  two 🔴 handoff-blocking defects; develop + merge, do NOT restart the running
  server), and
  ~~[`PROMPT-parallel-write-plan5.md`](PROMPT-parallel-write-plan5.md)~~
  **DONE 2026-07-31** — the plan is written (see the next bullet).
- **Plan 5 — Tracks 1–4 SHIPPED; Tracks 5–6 remain (20 of 27 tasks).**
  What is left: **Track 5, the Administrator Handbook** (tasks 21–23,
  [`PROMPT-plan5-session-c.md`](PROMPT-plan5-session-c.md) — Task 21's memo
  renderer can start now; 22–23 describe admin screens that now exist, so
  they are unblocked) and **Track 6, gates G2/G3** (24–27), which need a
  finished bundle and a finished handbook. Track 4's handoff
  (`PROMPT-plan5-track4-cleanup.md`) is retired — do not execute.
  The original plan, for reference:
  [`docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md`](docs/superpowers/plans/2026-08-01-standalone-plan-5-admin-packaging.md).
  27 tasks in six tracks: admin/settings UI (S11/S13/S15/S16/S17/S19),
  resilience (S18 repair flow + launch health ladder + a `RESET-ADMIN.txt`
  break-glass path out of an admin lockout), packaging + launcher
  (S7/S8), legacy deletion (`web/`, `mcp-server/`, `db/`, dead `retrieval/`
  modules), the **Administrator Handbook** (JLBC-memo-styled Word doc built
  from `docs/HANDBOOK.md`, shipped in-app AND beside the corpus on the share —
  covers operation, the cost model, why each AI tier got its model,
  confidentiality, and how a non-technical successor extends the app with AI
  help), and gates G2/G3. Tracks 1–2, Track 3 and Track 5's Task 20 can run in
  three parallel sessions; Track 4 must follow 1–2; the handbook's writing
  tasks follow the admin UI; Track 6 needs the finished corpus.
  **Handoff prompts, one per parallel session:**
  [`PROMPT-plan5-session-a.md`](PROMPT-plan5-session-a.md) (tasks 1–13, admin +
  resilience), [`PROMPT-plan5-session-b.md`](PROMPT-plan5-session-b.md) (tasks
  14–17, packaging — **stops after the Task 14 measurement for a shape
  decision**), [`PROMPT-plan5-session-c.md`](PROMPT-plan5-session-c.md) (task
  21 now, the memo renderer; tasks 22–23 wait for Session A).
  **Task 13 (bundle-size measurement) is the highest-risk item and gates the
  rest of packaging** — it also carries the split-distribution fallback if a
  MinerU-inclusive bundle proves impractical. The AI-Mode hardening that used
  to sit here (S22 + S23) shipped 2026-07-31 — see the section below.
- **Z13 backfill + recency calibration (S20/S21)** — historical-year corpus
  backfill and recency-ranking calibration on the Z13 Linux machine.
  Runbook: [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md) (the only
  active handoff). Recency plan:
  [`docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md`](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md).
- **Layer 2 agent-loop eval — BUILT, first smoke baseline COMMITTED
  2026-08-01** (`eval/results/agent/2026-08-01T1157Z-25399b1/`, 11 queries,
  $0.43, 0 errors, model `z-ai/glm-5.2`). The full 31-query baseline has NOT
  been run — do that before trusting a `compare_agent_runs.py` delta on
  anything outside the smoke set. What the first baseline says, and the four
  improvement targets it hands us, are in the section below.

---

## Citation linking — code complete, re-baseline OUTSTANDING (2026-08-02)

Spec: `docs/superpowers/specs/2026-08-02-citation-linking-design.md`.
Plan: `docs/superpowers/plans/2026-08-02-citation-linking.md`.
Branch `citation-linking`, 12 tasks, all 12 implemented.

**The system links figures now; the model cites only prose.** A new
`citation/` package runs in-process at turn end: it extracts every figure
from the final answer with offsets and scale, locates each value in the
chunks that turn retrieved (scale-aware), ranks candidate sources by
document authority (AFR > Approps > Baseline > Governor), reconciles the
leftovers as arithmetic over linked figures, and emits ONE annotation on
the `_done` frame. The webapp renders it as chips; the eval judge renders
the same annotation as inline markers, so the two cannot drift.

**Measured over the 31-query 2026-08-02 baseline, 435 figures:**

| verdict | count | share |
|---|---|---|
| linked | 357 | 82.1% |
| derived | 47 | 10.8% |
| **unverified** | **31** | **7.1%** |

**Coverage (linked + derived) 92.9%**, against the design's measured
feasibility ceiling of 93.6% locatable. Under the plan's ~10% stop
threshold.

**The specificity floor is calibrated, not guessed.** Floors 3/4/5/6 link
357/357/342/300 of 435. Floor 4 ships: indistinguishable from 3 on this
corpus, so it costs nothing measured while still refusing 3-digit
collisions. Floor 5 was rejected by READING all 15 links it would drop —
every one is correct (student counts, FTE positions, inmate counts,
average awards).

### The unverified 31 were read, and one of them is a real find

They are two honest shapes: model-computed deltas whose own inputs are
never stated in the answer ("+$18.3M"), and approximations ("caseload now
above 50,000").

**Except `lk-gf-revenue-fy2026`, which is 6 of 6 unverified — and its
retrieved chunks contain ZERO grouped numbers across 4,413 characters
while the answer states six specific dollar figures.** That is a genuine
Invariant 3 case (retrieval gap or unsourced assertion) surfaced for the
first time by this instrument, not a matcher failure. Worth its own look.

### Defects found and fixed that the plan did not anticipate

Each was caught by making the thing work, not by the tests as written:

- **`find_in_chunks` applied the context scale twice.** It walked the
  scale ladder from `fig.absolute`, so `scale_used` always returned 1 and
  a source that tabulates in millions could never match. Caught by the
  plan's own `test_scale_shifted_match`.
- **The extractor did not know "M"/"B"/"K".** Real answers write
  "+$243.5M" far more often than "$243.5 million"; scale read as 1, which
  broke the match AND made the floor treat $243 million as three digits.
- **The year guard had no word boundary**, so `within $1,000,000` and
  `margin 1,234,567` silently dropped a real figure.
- **🔴 THE ANNOTATION NEVER REACHED THE UI.** `turn_complete` closes the
  turn and `_done` — the only frame carrying the annotation — arrives
  after it, so the reducer's "no open turn, do nothing" early return
  dropped **every figure chip in production** while every component test
  passed. This is the one that would have shipped a feature that does
  nothing.
- **Annotation offsets are not safe to trust in the renderer.** They
  index the whole `finalAnswer`, but `CitedMarkdownContent` renders PER
  TEXT BLOCK and its content may have been rewritten by inline-`<cite>`
  stripping. `placeFigures()` verifies the offset before using it and
  otherwise finds the text; a figure it cannot locate gets NO chip,
  because an absence is visible and a chip on the wrong number is a false
  provenance claim.
- **Both plan test fixtures carried offsets that did not index their own
  answer** (judge figure 1 at 12:20 slices `'287.7 an'`). Both now derive
  offsets and assert they slice correctly.

### Verified offline, end to end

`tests/test_citation_end_to_end.py` drives a REAL `HarnessSession`
through the REAL SSE route with the reported defect's shape — a markdown
table, a chunk whose text fuses the agency name onto the number, and a
stated total — and asserts linked/linked/derived with `derived_from`
[1, 2], `source_text` carrying the SOURCE's rendering, indices in reading
order, and **zero `cite`/`cite_batch` calls** for a fully-numeric answer.
No key, no network.

**Suites: 1986 pytest, 451 vitest, `tsc -b` exit 0.**

### 🔴 OUTSTANDING — needs a machine with an OpenRouter key

Plan Task 12 Steps 3–4 could not run here: `ai_available` reports **"no
API key configured"** on this machine, and both steps spend real money.

1. **The live reproduction** of *"what are the biggest agencies by
   budget"*. The offline end-to-end test covers its shape, but nobody has
   watched a real model answer under the new prompt.
2. **The Layer 2 re-baseline** (`--subset full`, ~$0.50–1.50, plus the
   judge as a separate charge), then `compare_agent_runs.py` against
   `eval/results/agent/2026-08-02T0900Z-0b08221`. Expected direction:
   `figure_coverage_mean` high, `unverified_rate` low, `steps_mean` and
   `input_tokens_mean` DOWN (cite round-trips removed), `cite_pass_rate`
   no longer dominated by figure citations.

**Until that runs, the prompt change (Task 7) is unmeasured.** Everything
else in this section is measured against recorded transcripts or pinned
by tests.

**Also unverified in a real browser:** the chips themselves — derived and
unverified tone, the "Also appears in:" list, and chip click opening the
PDF at the source rendering. 22 new vitest specs cover the logic; nobody
has watched it render.

---

## Plan 7 — batch extraction: Tasks 1–4 shipped (2026-08-01)

Plan: `docs/superpowers/plans/2026-08-01-standalone-plan-7-batch-extraction.md`.
Measurement: `docs/superpowers/investigations/2026-08-01-mineru-batch-mode.md`.
Merges `71ac0ae` (runner), `6a78d64` (worker), `516542e` (spike), `10f7a50`
(poison-pill fix). **Default-off**: `JLBC_INGEST_BATCH` unset = today's exact
per-document behaviour, which is what made it safe to merge while the office
is live on the ingest path.

### Ground truth 2 of the plan was FALSE — found by the spike, as designed

**A truncated PDF aborts the ENTIRE `mineru -p <dir>` batch**, zero output for
every batch-mate. It fails in MinerU's pdfium preflight *before* any
extraction, so it costs ~3.3 s rather than a wasted batch — but at
`JLBC_INGEST_BATCH=40` one bad file would mark 40 documents failed.

Fixed by probing every candidate with **pypdfium2 before staging** and
excluding bad ones individually. **Do not "simplify" this to
`ingest.dispatcher._pdf_page_count`** — that uses PyMuPDF, which is more
tolerant than pdfium and therefore does not predict MinerU. Measured: a real
PDF cut to 90% of its bytes opens fine in PyMuPDF and reports all 6 pages,
while pdfium rejects it; **an HTML 404 body renamed `.pdf` reads to PyMuPDF as
a valid 1-page document**, and that is a shape azjlbc.gov has actually served.
Pinned by `test_the_probe_catches_what_pymupdf_would_have_waved_through`.

A second hazard the plan did not anticipate: zero-byte and garbage PDFs are
**silently dropped** by MinerU — `rc=0`, batch completes, filename never
mentioned in 46 log lines. Already covered, because `_demux_one` fails any
staged document that produced no output (the FY2024-AFR shape).

### Measured, not projected

**3.55×–4.64× at 20 documents** (~4.0× at the batch mean). Reported as a range
because the two batch runs disagree 23.5% — page-cache warmth on ~5.5 GB of
weights; the *second* was faster despite higher load. The serial half is
corroborated externally at 41.6 s/doc / 87 docs/hr against this file's
independently recorded ~40 s/doc / 93 docs/hr.

| batch | s/page | docs/hr | peak tree RSS |
|---|---|---|---|
| 1 (serial) | 10.67 | 87 | 3.9 GB |
| 5 | 3.19 | 282 | 4.5 GB |
| 10 | 2.38 | 378 | 5.1 GB |
| 20 | 3.01 / 2.30 | 307 / 401 | ~8 GB |
| 40 | 1.55 | 625 | 11.7 GB |

**No knee found** — 40 was the edge of the measurement, not a plateau.

**Two plan claims corrected.** `WORKERS=12 BATCH=20` is NOT runnable here
(12 × 8.1 GB ≈ 97 GB on a 121 GB box); use `WORKERS=4`. And "3.7 h → roughly
one hour" was optimistic — **~2 h is the defensible claim**.

**Extraction is not perfectly reproducible across batch sizes.** 17 of 20
documents were byte-identical; the 3 that differ do so by **exactly one
character** each in table HTML, with **every numeric token identical**. Isolated
by experiment, not guessed: batch-20-vs-batch-20 is 20/20 identical, while
batch-3 and both single-document forms agree with each other and all differ
from batch-20. So it is batch *composition*, not run-to-run noise. No dollar
figure moves, but a document's chunk text depends slightly on what it was
batched with.

### Task 4 — live validation, JLBC Baseline FY2021 (2026-08-01)

`WORKERS=4 BATCH=20`. **134 queued → 132 live, 2 failed, in 964 s = 500
docs/hr.** Peak memory 47 GB of 121 GB.

Both failures are **azjlbc.gov 404s** (`21baseline/legsen.pdf`, `otr.pdf`) —
the sources do not exist, not a code defect.

Audited rather than assumed: documents.json count == distinct doc_ids in
LanceDB (132 == 132), 0 duplicate chunk_ids, 0 chunks missing page or bbox,
0 documents with zero passages. **Chunks-per-page 3.52, dead centre of its
siblings (FY2022–27 span 3.24–3.66)**, and 0 documents in the FY2024-AFR
shape. Spot-read 3 documents: `adc` is Corrections, `acc` is Community
Colleges, `dps` is Public Safety — each document's text is genuinely its own,
which is the only check that catches a stem-collision demux bug.

**12 empty-text chunks (0.65%) are PRE-EXISTING, not a batch regression** —
proven by control: FY2022 0.45%, FY2023 0.46%, FY2024 0.58%, FY2025 0.53%,
all ingested without batch mode, all on page 2. (FY2026/27 have none.) Worth
its own look; not caused by this work.

**Ingest is per-machine and default-OFF since Plan 5 Track 4**, so a backfill
run must set `JLBC_INGEST_ENABLED=1` or the queue silently will not run.
`~/backfill-scripts/restart_batch.sh` does this.

### 🔴 A STOLEN INGEST LOCK NEVER HEARTBEATED — fixed, merge `6c7c19b`

**S6 single-writer invariant violation, observed live, not theorised.**
`IngestLock.acquire()` had two paths that take the lock; `_start_heartbeat()`
had exactly ONE call site, on the ordinary-create path. **The stale-steal path
set `_held = True` and returned without starting the beat.**

Consequence on the shared drive: a lock taken by stealing keeps its
`heartbeat_at` frozen at acquisition, so after the 120 s stale window **every
other machine correctly judges it stale and steals it while the first is still
writing** — two writers on one corpus. It is also **self-perpetuating**: once
one steal happens, each later holder also acquires by stealing, so the
heartbeat never runs again for that corpus's lifetime.

Found by accident: a mid-write server restart left a stale lockfile, the new
worker stole it, and the heartbeat then sat frozen for **866 seconds** while a
live holder did real work and 147 threads queued behind it. Neither existing
lock suite caught it because both exercised only the ordinary-create path.

Fixed with a single `_take()` helper both success paths call, deliberately
rather than a second `_start_heartbeat()` call — two paths independently
assigning `_held` is the *shape* that allowed the omission. Guard:
`tests/test_ingest_lock_heartbeat.py` (3 specs, verified failing before the
fix, incl. a rival that collected 13 successful steals against an expected 0).
Intra-process double-write was never possible — `_process_mutex` covers that —
so the exposure was strictly cross-machine.

### 🔴 SNAPSHOTS ARE THE INGEST BOTTLENECK, and Task 5's premise was wrong

Plan 7 Task 5 says per-batch snapshots removed the O(n²) that justified
`JLBC_INGEST_SNAPSHOT=off`. **They did not — they moved it.** Per-batch cut the
count from ~3,775 to 29, but `store/backup.py::snapshot()` zips the WHOLE
corpus with single-threaded Python `ZIP_DEFLATED` **while holding the ingest
lock**, and the corpus grows all run.

Measured 2026-08-01 mid-backfill:

| symptom | measurement |
|---|---|
| snapshot archives | 2.3 → 10.8 → 16.8 → **17.4 GB**, one per edition |
| lock held per snapshot | 7–15 min, single core, all other workers blocked |
| corpus on disk | **13 GB for 37,709 rows** |
| live LanceDB versions | **522** |
| throughput with snapshots on | 370 docs/hr |
| throughput with `SNAPSHOT=off` + `RETENTION=2` | **727 docs/hr**, corpus 12.5 → 6.1 GB while running |

**Root cause of the 13 GB is version pileup, not row count.** `optimize()`
prunes versions older than `JLBC_LANCE_RETENTION_MINUTES` (default 10). Writes
land every ~1.3 s during a bulk run, so ~460 versions are always inside the
window — 522 observed is arithmetic, not a defect in `optimize()`.

**Bulk-run settings are supervised-only and live in the environment** (they die
with the process). `~/backfill-scripts/restart_batch.sh` sets both with the
reasoning inline. **Do NOT make the 2-minute retention an office default** —
the prune compares version timestamps against the *pruning* machine's clock and
~20 machines read this corpus off a shared drive.

**This probably degrades the OFFICE experience too, and is not fixed.** One
analyst uploading one document triggers a full-corpus zip under the lock; at
6 GB that is minutes of apparent hang for a single upload, and the corpus only
grows. Office write rates will not pile up 500 versions, so the corpus should
stay smaller there — but zip-the-whole-corpus-per-write does not scale. An
incremental or copy-on-write snapshot is the real fix. **Follow-up, not done.**

---

## Plan 5 Track 4 (cleanup) — shipped (2026-08-01)

Tasks 18–20 plus the three orphaned bundle requirements. Handoff:
`PROMPT-plan5-track4-cleanup.md` (now retired — do not execute).

**Plan 5 is 20 of 27 tasks done.** Remaining: Track 5 (handbook, 21–23) and
Track 6 (gates, 24–27).

### Task 18 — the retired architecture is GONE

`web/`, `mcp-server/`, `db/`, and `retrieval/{api,bm25,dense,rerank,sql}.py`
plus their suites: **~36,000 lines deleted.** Every directory in the repo is
now live code.

`setup.sh` went from eight steps to four. It used to run `npm ci` twice, a
tsc build, and 277 vitest specs across two directories Plan 4 retired, plus
bring up a Postgres container and run `db.validate` against it — on every
fresh clone, including the G3 cold-start install.

**The known test-isolation defect is gone with it, not worked around.**
`setup.sh` sourced `.env.local` before pytest, which leaked `DATABASE_URL`
into the process and un-skipped the Postgres suites mid-run against a schema
they did not own. Both the suites and the sourcing are deleted.

- **`eval/synthesize_queries.py` was PORTED, not deleted** — eval-set
  expansion is a live Phase 3 need. Both samplers pushed their randomness
  into SQL (`ORDER BY RANDOM()`, a self-join for comparison pairs) and
  LanceDB has neither, so the sampling happens in Python over one projected
  scan. Adds `--corpus fiscal_note_chunks`. Verified against the real corpus:
  25 seeds balanced across all four publishers, 5 valid cross-FY pairs.
- **`retrieval/sql.py` was not on the deletion list but is orphaned by it** —
  its only consumers were bm25.py and dense.py. `tests/test_retrieval_sql.py`
  became `test_retrieval_types.py`: half of it covered `RetrievedChunk.from_row`,
  which is still live (search_lance.py builds RetrievedChunk from Lance dicts —
  same column names psycopg rows had, which is why the adapter survived).
- **`docs/corpus-recovery.md` advertised a one-command recovery** running a
  script this deleted. Rewritten: the acquisition trail is still what makes
  recovery possible, but the flow is manual and now says so, and the two
  recovery-posture checks are re-expressed against `documents.json`. Verified
  on the live corpus — 0 missing `source_url`, 0 out-of-tree paths.

> ⚠ **THE ONE REAL CAPABILITY LOST.** `eval/refresh_chunk_ids.py` was the tool
> that re-bound stale eval chunk_ids after a re-ingest. It never ran against
> LanceDB and was deleted per the handoff. **Nothing replaces it.** What
> absorbs the damage is `eval/scoring.py`'s dimensions fallback — which is
> loose, and can credit a different chunk of the same document. `anchor_text`
> is still recorded for every expected chunk and is the manual repair path.
> **This bit within hours** (see the eval note below). Written up at
> `eval/README.md` → "After a re-ingest", `eval/schema.py` and `eval/scoring.py`.

**Verified from a FRESH CLONE, not the working tree:** `bash setup.sh --verify`
→ **exit 0**, 1559 pytest + 426 vitest, four steps.

### Task 19 — one `documents.json` reader

`store/documents.py` replaces what the brief called four readers and was
actually **five** — `app/routes/admin.py::_document_count()` hand-rolled its
own parse that nobody had listed. They had already drifted three ways, and
each divergence is preserved deliberately rather than averaged away:

1. **mtime resolution** — one stamped float seconds, one nanoseconds.
   Nanoseconds wins; a rewrite inside one filesystem tick is what a fast
   local ingest looks like, and the float version served stale titles with no
   symptom.
2. **corrupt-file policy** — read paths degrade to `{}` so search keeps
   working; the WRITE path RAISES. Not fastidiousness: the writer does a
   read-modify-write, so degrading there writes a sidecar containing one
   document and orphans every PDF in the viewer.
3. **the `ingested_at` title gate — OPTIONAL, defaulting OFF.** Measured
   before choosing: 378 live documents lack `ingested_at`, and gating them
   turns *"JLBC FY2027 — AHCCCS"* into *"JLBC Baseline FY 2027 Axs"*. The
   gate is right on the search page (mockup index is primary, this is the
   tiebreak) and wrong in AI Mode (sidecar is the only source, and an ugly
   title lands in the ANSWER). **A consolidation that picked one policy
   would have silently degraded 378 documents.**

Also `GET /api/corpus/counts` (ungated — it feeds a footer every analyst
sees) and the footer states a true corpus size again: **3,527 documents /
24,841 budget chunks / 13,278 fiscal-note chunks**. The number renders only
once the server has answered; first paint and a failed fetch both show
nothing rather than guessing.

### Task 20 — the remaining ingest defects

| Defect | Evidence |
|---|---|
| **Dead LanceDB versions never pruned** | Live corpus measured at **1.91 GB on disk holding 0.14 GB of live data**, 105 versions. `optimize()` *was* pruning — `cleanup_older_than` just defaults to **seven days**, so on a bulk run where every version is minutes old it pruned nothing and returned successfully. Retention now 10 min (`JLBC_LANCE_RETENTION_MINUTES`). Measured 98% reclaimed on an ingest-shaped run. |
| **`DownloadCache` concurrency** | Per-instance tmp path, a lock, and — the part locking alone would not have fixed — **re-read-merge-write**, because each instance wrote its own in-memory copy back wholesale. Verified on the REAL 7,482-entry manifest: 12 concurrent writers, zero lost. |
| **`IngestLock` heartbeat** | `_write` beat before `write_doc`, not during; `build_fts_index` + `optimize` will pass the 120s window as the corpus grows, so a **live, healthy writer** gets its lock stolen. `acquire()` now runs a daemon beat at ¼ the stale window. Verified at production ratios: held through a 6s write against a 2s window, rival judged it stale 0 times in 22 checks. |
| **Per-batch snapshots** | One restore point per book edition / note session instead of per document — 1 zip instead of ~130. `JLBC_INGEST_SNAPSHOT=off` still wins outright. |

Two chosen defaults worth not re-litigating: the version retention is **10
minutes, not 0**, because ~20 machines read this corpus and the prune compares
version timestamps to the *pruning* machine's clock; and `delete_unverified`
stays False because LanceDB's own docs say it is only safe when no other
process is touching the dataset, which a shared drive cannot promise.

### The three orphaned bundle requirements — now built

Session B filed four; Session A merged with two unbuilt and one half-noted.
(`docs/superpowers/investigations/2026-08-01-bundle-app-requirements.md`.)

- **Per-machine `ingest_enabled`, default OFF.** One bundle on ~20 PCs and
  `launcher.pyw` calls `create_app()` with no arguments, so all twenty would
  start a worker on one queue. Resolution order mirrors the data dir:
  `JLBC_INGEST_ENABLED` > `machine.json` > False. A machine.json without the
  key reads as False (that is install.cmd's file — silence is not consent);
  an unrecognised env value falls through to the FILE, because a typo on the
  one machine doing the work would otherwise stop the office silently.
  **`set_data_dir` is now read-modify-write** — it wrote `{"data_dir": …}`
  wholesale, so using the repair screen would have switched off the ingest
  machine.
- **The "nobody is processing uploads" warning**, which is not optional: OFF
  by default re-creates the silent pile-up the one-bundle decision existed to
  avoid. Fires only when something is queued AND nothing is running AND
  ingest is off here. The server owns both the decision and the sentence.
- **`python -m app.machine_config`** so `install.cmd` stops hand-writing JSON.
  Silent exit 0 on success; a validation failure is a WARNING and **still**
  exit 0, because a network drive that is not connected during setup is
  normal and refusing to record the path would strand the user.

### Eval — retrieval-neutral, but the corpus moved under it

**recall@5 62.07%, recall@15 96.55%, recall@20 100%, p95 832ms. Gate G1
passes.** recall@5 is 21 points below the last recorded run and **none of it
is Track 4** — proven by control, not asserted: the same eval on
`origin/master` with none of this branch's code, same corpus, produced
identical figures (`eval/results/2026-08-01T0934Z-6cd522e`). Nothing here
touches ranking.

**The fallback rate is 41% of passes** — two in five ground-truth chunk_ids
no longer resolve and are matching on dimensions instead. That is the
re-ingest hazard above, arriving within hours because the parallel session's
User-Agent fix re-fetched and re-ingested documents. **Do not read 62% as a
retrieval regression; re-point the stale chunk_ids first.**

### Found and fixed on the way (neither caused by Track 4)

- **Three `/api/me/usage` specs went red at midnight.** They seeded a
  hardcoded `2026-07` shard and called an endpoint that always reads the
  CURRENT month, so they passed only while the wall clock was in July.
- **`test_the_query_set_is_honestly_marked_as_unbaselined` was red on
  `origin/master`** — the parallel session filled in fiscal-note ground truth
  but left the guard asserting the old "NOT YET FILLED IN" marker. Re-pointed
  at the DRAFT / PENDING HUMAN REVIEW banner the file now carries; the
  property it protects is unchanged.

### Follow-ups this work created

- **`pyproject.toml` still DECLARES the retired stack** even though the tree
  is gone: `psycopg`, `pgvector`, `voyageai` have zero importers, and
  `python-dotenv` had exactly one (`retrieval/api.py`, deleted). Not dropped
  here on purpose — it changes the wheel closure that Session B's 3.33 GB
  bundle was verified against on real Windows hardware, and that verification
  cannot be re-run from this machine. **Whoever next rebuilds the bundle
  should drop them and re-verify.** `psycopg` has one remaining consumer,
  `scripts/migrate_to_lancedb.py`, kept as the migration-era record.
- **Provenance comments across ~35 files cite `web/…` paths** ("ported from
  web/components/ChatThread.tsx"). They resolve against git history and are
  honest attribution, so they were left alone; CLAUDE.md now says so
  explicitly, with the `git log --diff-filter=D` incantation that recovers
  the deleted trees.
- **The admin queue warning and ingest toggle are unverified in a real
  browser.** Same gap Session A recorded for the rest of that page.
- **`data/cached-pdfs/` vs `<data_dir>/pdfs/` is still two homes for the same
  bytes** — untouched here (it is a decision, not a defect).

---

## Plan 5 Track 3 (packaging) — shipped, running on Windows (2026-08-01)

Session B of the three parallel Plan 5 sessions. Tasks 14–17 complete. Merges
`92028c5`, `74747e9`. (Written while Session A was still in flight — Tasks 1–13
have since landed; Tasks 18–27 remain. Two of the four app-side requirements
this track filed are still unbuilt: see the Session A section below.)

**The bundle exists and runs.** `python packaging/build_bundle.py --version X` produces
`dist/JLBC-Insight-X.zip` — **3.33 GB unzipped / 2.11 GB zipped**, 36,102 files —
containing an embeddable CPython, the Windows wheel closure, a vendored Temurin JRE, the
app source, the built SPA, and every model weight pre-seeded. **It builds on Linux**;
`uv` resolves real Windows wheels for a foreign platform and everything else Windows-
specific is a download rather than a compile.

**Verified on Destin's work laptop, 2026-08-01** — a machine that had never had Python,
standard user account, no admin rights: all 36,102 files extract; the full core and
ingest closures import; `app.main` imports; the bundled JRE runs; `install.cmd` completes
with no elevation and no endpoint-security prompt; the shortcut starts the server and
serves the SPA; several clicks leave exactly one `pythonw.exe` (S8 relaunch-reuse);
and **the acceptance criterion passed — an offline cold start with WiFi disconnected.**

**Shape decision: one bundle everywhere** (~20 PCs), not the split the plan hedged
toward. Vendoring a 47 MB Temurin JRE removed the need for an IT request for Java, which
was the split's main argument; ~500 GB free per machine removed the disk argument. Two
artefacts would have meant somebody eventually installing the search-only one on the
ingest machine, with uploads queueing forever and no error anywhere.

**S8 amended 2026-08-01:** the launcher opens an ordinary browser tab, not Chrome
`--app` mode. Reversed within seconds of the first real user seeing it — this is a
reference tool used alongside a dozen research tabs, not a program you live inside.

**Four findings the plan did not anticipate**, all handled, all detailed in
`docs/superpowers/investigations/2026-08-01-bundle-size.md`:
- `opendataloader-pdf` shells out to `java` and bundles no JRE → JRE vendored
- `mineru==3.1.6` cannot resolve wheel-only (`antlr4` 4.9.x is sdist-only) → one
  pure-python wheel pre-built at build time. **`>=3.1.6` silently resolves to 3.4.4**,
  which un-declines the corpus-wide re-ingest the plan rejected; it is pinned
- `tiktoken` downloads its encoding at runtime and **fails soft** to different chunk
  boundaries → cache pre-seeded, `TIKTOKEN_CACHE_DIR` set by the launcher
- fastembed's model cache defaults to `%TEMP%`, which Windows deletes → `FASTEMBED_CACHE_PATH` set

**Open, blocking nothing:**
- **Real retrieval is untested.** Every Windows run so far had an empty data dir, where
  `create_app()` serves stub fixtures. Needs the 4.9 GB corpus copied to the laptop —
  deferred while the backfill is writing to it.
- ~~Session A owes two changes~~ ~~`install.cmd` writes `machine.json` by hand~~
  **ALL THREE BUILT in Track 4, 2026-08-01** — per-machine `ingest_enabled`
  (default OFF), the "nobody is processing uploads" admin warning, and
  `python -m app.machine_config`, which `install.cmd` now calls instead of
  emitting JSON by hand. See the Track 4 section above.

## Z13 backfill — IN PROGRESS (2026-07-31)

Runbook: [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md). Spec: S20 (scope),
S21 (recency). This section is the live record; update it as phases land.

**Machine:** Ryzen AI MAX+ 395, 32 threads, 121 GB RAM, Linux. Repo at
`~/YouCoded/Projects/ask-the-budget-az-dev`, corpus at `data/insight-data/`.

| Phase | State |
|---|---|
| A — setup + parity gate | ✅ **PASSED**, exact reproduction of the Windows baseline: recall@5 72.41 / @15 96.55 / @20 100.00, refusal precision 40.00. Latency p95 **821 ms vs 3,187 ms** on the office box (3.9× faster). Results committed. |
| B — recency machinery (S21) | ✅ **MERGED** (`4c75f2c`). Year-parser hard filter + `inferred_fiscal_years` + recency boost shipped OFF (0.0) + prompt guidance. **Eval improved to recall@5 82.76% (+10.35pp) and refusal precision 60% (+20pp)** from the year filter alone. |
| C — the backfill | 🔵 **RUNNING.** Fiscal notes ~65% (1,384 of 2,126 docs, sessions 2026→2008); 38 book editions not started. ~6 h remaining. |
| D — calibration | ⬜ **BLOCKED on C.** Author `eval/queries_historical.yaml` against the finished corpus, run `eval/calibrate_recency.py`, set `RECENCY_BOOST_PER_YEAR`, re-run `calibrate_refusal.py`, then the three-set eval that proves old books don't swamp no-year queries. |
| E — wrap | ⬜ Final counts, canonical corpus declared, this section closed. |

**Corpus right now:** `budget_chunks` 7,808 · `fiscal_note_chunks` 8,438 ·
1,770 documents (was 382 / 7,755 / 0 notes at the start).

**Throughput work done during the run** (all merged; measured, not estimated):

| change | effect |
|---|---|
| Bulk snapshot mode (`JLBC_INGEST_SNAPSHOT=off`) | 89 → 96 docs/hr and, more importantly, flattened an O(n²) decay curve |
| Parallel ingest (`JLBC_INGEST_WORKERS`, merge `f4ddf1d`) | 95 → 700 docs/hr at N=8, 840+ at N=12 |
| Worker cap raised 8 → 16, sized from measured CPU draw (`502841b`) | knee is ~8; N=12 is the practical setting |
| Thread-unique job temp files (`1f63393`) | closed a save() race that failed 1 document per ~100 at N=14 |
| **Net** | **95 → ~945 docs/hr (10×); remaining work 67 h → ~6 h** |

**Live operating config** (all three processes detached, restartable via
`~/backfill-scripts/restart_stack.sh <workers> <omp> <shared_mineru>`):
`JLBC_INGEST_WORKERS=12`, `JLBC_INGEST_SNAPSHOT=off`, `OMP_NUM_THREADS=3`,
shared mineru-api DISABLED. Progress log: `~/backfill-progress.log`.
Restore points: `~/pre-backfill-corpus.zip` (pre-run) and
`~/corpus-before-parallel.tgz` (1.5 GB, pre-parallel, 2,956 notes in).

**Data quality verified under 8-way and 12-way parallelism** (audited, not
assumed): documents.json count == distinct doc_ids in LanceDB; 0 documents
with zero chunks; 0 orphan chunks; 0 duplicate chunk_ids; 0 rows missing page
or bbox; 93/93 sampled titles real and content-derived. 1 known
zero-passage document — azleg.gov published a literal test file
("THIS IS A TESTT"), not an extraction failure.

---

## Standalone consolidation — Plan 1 shipped (2026-07-30)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(decisions S4/S5). Plan: `docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md`.

- **Store:** new `store/` package — embedded LanceDB at `<data_dir>/lancedb`
  (`JLBC_DATA_DIR` env override; dev default `data/insight-data/`, gitignored).
  Vector search (cosine) + native Lance BM25 FTS + DataFusion filters, one
  table per corpus (`budget_chunks` live, `fiscal_note_chunks` reserved for
  Plan 3). No server, no Docker on the retrieval path.
- **Models (local ONNX via fastembed, CPU):** embeddings
  `snowflake/snowflake-arctic-embed-m` (768-dim, query-instruction prefix
  applied query-side), reranker `Xenova/ms-marco-MiniLM-L-12-v2`. Fused
  RRF pool lowered 50 → 20 so the rerank stage stays ≤ ~3s interactive
  (measured 2.7s mean / 3.1s max at 20; 4.9s at 50).
- **Score scale changed:** reranker scores are raw cross-encoder logits
  (≈ −10..10), not Voyage's 0..1. No-results sentinel is
  `NO_RESULTS_TOP_SCORE = -1e9` (0.0 would outrank a genuinely-bad hit).
  Refusal threshold recalibrated 0.65 → **1.9** in
  `mcp-server/system-prompt.md` (sweep: precision 0.67 / recall 0.40 /
  pass-rate 0.97).
- **Gate G1 — passed as amended.** The original gate (recall@5 ≥ 0.80)
  was missed by both local embedder candidates (best 0.69–0.72; every
  local cross-encoder ranks worse than Voyage rerank-2.5) and the
  plan's stop rule fired. Destin reframed G1 mid-execution (spec commit
  `835900f`): **recall@15 ≥ 90% and recall@20 ≥ 95%**, with recall@5
  tracked and reported in every run so the gap stays visible. Final
  numbers: recall@5 72.41%, recall@15 96.55%, recall@20 100%, latency
  p95 ~3.0s (Voyage baseline: 86% / — / 100%, p95 2.6s). **Future
  sessions: the recall@5 gap vs the Voyage baseline is a known,
  accepted trade — do not rediscover it as a regression.** The consuming
  model reads all 15 returned chunks, which is what the amended gate
  measures.
- **Migration:** `scripts/migrate_to_lancedb.py` (one-time; re-runnable;
  `--docs-only` refreshes metadata without the ~50-min re-embed).
  Chunk_ids preserved verbatim; eval ground truth unchanged. G2 spot
  checks: exact chunk-id parity, 60-row full-column diff clean,
  provenance (page+bbox / source_anchor) intact corpus-wide.
- **Sidecar (`retrieval/api.py`):** same endpoints/shapes on LanceDB —
  no `VOYAGE_API_KEY`/`DATABASE_URL`; preflight = data-dir writable +
  corpus non-empty; `/health` reports `corpus_chunks`,
  `documents_metadata`, and returns 503 `degraded` with the real error
  when the store is unreachable. `top_k` validates ≥ 1 (422).
- **documents.json:** per-doc metadata sidecar (title, source_format,
  source_blob_path, source_url) written by the migration next to
  `lancedb/`. This is what lets the web PDF viewer open sources; if it's
  missing, `/health` shows `documents_metadata: 0` and
  `migrate_to_lancedb.py --docs-only` regenerates it in seconds. Titles
  fall back to a doc_id humanizer when absent.
- **Eval harness:** now computes recall@15 alongside 5/20;
  `calibrate_refusal.py` derives its sweep grid from the observed score
  distribution (survives future model swaps); a crashed retrieve can no
  longer masquerade as a confident refusal.
- **Still Postgres/Docker:** ingest only (until Plan 3). Legacy modules
  (`retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py`,
  `db/`) stay in-tree unused; removal is Plan 5.
- **Known follow-ups:** web PDF route can't distinguish "metadata
  missing" from "actually DOCX" (415 either way — Plan 2 web-side fix);
  lancedb `table_names()` deprecation (pagination-shaped `list_tables()`
  migration pending); stale data-file versions accumulate after
  `optimize()` (`cleanup_old_versions` not exposed — matters for the SMB
  share); ingest-side title quality is poor for a few docs ("GOVERNOR
  FY2027 fy2027") — Plan 3; expose fastembed `parallel=` for faster bulk
  re-embeds — Plan 3; PRE-EXISTING test-isolation debt (predates Plan 1,
  verified on pre-merge master): when `.env.local` exists, dotenv loading
  during the api tests leaks `DATABASE_URL` into the process env, which
  un-skips the legacy Postgres suites (test_connection/test_loader/
  test_embeddings) mid-run and they fail with UndefinedTable against a
  schema they don't own — run suites without `.env.local` (fresh-clone
  behavior) or fix the skip gates to snapshot env at collection time.

---

## Standalone consolidation — Plan 2 shipped (2026-07-30)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S1, S9, S12). Plan: `docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md`
(its frozen API-contract block is what Plans 3/4 build against — note the
Task 3 amendments recorded there: `fiscal_note_url` on bills, real
`leg_session()` names, non-unique `bill_number`).

- **App server (`app/`, port 9300):** FastAPI factory serving the built SPA
  (SPA fallback for client-side routes, JSON 404s under /api/, traversal-safe
  static serving) + `POST /api/search` + `GET /api/fiscal-notes` + `/health`.
  Provider seam: `_default_provider()` probes the LanceDB corpus once at
  startup — real `LanceSearchProvider` (Plan 1 stack) when `budget_chunks`
  has rows, fixture `StubSearchProvider` otherwise with the reason on stderr.
  Startup-only by design: a share outage mid-session surfaces as an honest
  JSON 503 from the search route, never a silent swap to fake rows. Run:
  `uv run uvicorn app.main:create_app --factory --port 9300` (set
  `JLBC_DATA_DIR` for a non-default corpus location).
- **Webapp (`webapp/`):** Vite + React 18 SPA ported from the JLBC Website
  Revamp mockup per S12 (verbatim `:root` tokens; page-scoped CSS convention
  documented in `webapp/src/styles/app.css` — the three mockup sources
  conflict on ~74 shared selectors). Pages: Home (hero search + gateway
  cards), Budget Search (see next bullet), Fiscal Notes (28-session /
  2,126-bill directory from the committed snapshot — Plan 3 swaps in the live
  corpus behind the same contract; safe `<strike>/NOW:` title rendering;
  session rail tuned live with Destin).
- **Budget Search — FINAL UI (iterated live with Destin 2026-07-30; the
  "As shipped" section of the Plan 2 doc + the spec's S12 amendment are the
  baseline for Plans 3/4/5):** results group by report family; each card =
  a linked headline row (best agency document, title ONLY — the mockup
  index's display title via exact source-URL join, 373/382 docs; `doc_url`
  from Plan 1's documents.json; "Open" pill; NO relevance display — number
  and bar both removed, ranking speaks through result order) → a collapsed "Matching
  passages" card (snippets + page pills, `data-chunk-id` stubs for Plan 4's
  viewer) → a bottom "Part of the FY YYYY <family>" card with collapsed
  sibling documents and the **Full report** chooser (the mockup's modal:
  Linked TOC vs Single File PDF, hand-verified URLs per family in
  `webapp/src/reportFamilies.ts`). NO publisher pills, NO taglines, NO
  percentages (removed at Destin's direction). Filters: publisher chips +
  curated type buckets + FY dropdown; retry + stale-while-revalidate states.
- **Fiscal-notes snapshot:** `scripts/export_fiscal_notes_snapshot.py`
  (parser transcribed from the vendored mockup generator) → committed
  `app/data/fiscal-notes-snapshot.json`, exact-count pinned (28 / 2,126).
- **Vendored references:** `webapp/reference/` now holds the mockup pages
  (including the GENERATED `subpage-fiscal-notes.html` — base.html's body is
  a superseded scaffold, do not port from it) plus the mockup's in-browser
  search engine (`assets/search/search.js` — report families, curated
  buckets, ranking blend) and its 419-doc URL index (`index-lite.js`), kept
  as input for retrieval tuning and the report-format chooser follow-up.
- **UI score display:** none — scores (raw cross-encoder logits) drive
  ordering only; the relevance number and bar were both removed at Destin's
  direction (2026-07-30).
- **Tests:** 24 app pytest (`tests/test_app_server.py`, `test_search_route`,
  `test_fiscal_notes_route`, `test_fiscal_notes_snapshot`,
  `test_lance_provider`) + 39 webapp vitest. `setup.sh` now installs/builds
  `webapp/` and `--verify` runs its suite.
- **Known follow-ups:** book-vs-agency-page open actions SHIPPED as external
  azjlbc.gov links (agency rows via the sidecar URL, whole books via the
  chooser modal) — the remaining piece is Plan 4 swapping them to the in-app
  viewer over `pdfs/` (offline-first per spec S7); doc titles come from the
  mockup-index URL join (373/382 docs) with the slug humanizer covering the
  9 unmatched — Plan 3's ingest should write real titles into
  `documents.json` for docs the website never indexed; filter-chip counts
  need a facets endpoint (corpus-wide numbers, not per-search); Nunito is
  named but never loaded by the mockup (one `<link>` if the approved look
  was really Nunito); `db/migrations/0001` doc_type enum comment is stale
  vs live data (`baseline-agency` vs `baseline-per-agency`).

---

## Standalone consolidation — Plan 3 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S6, S7, S10, S17, Invariant 8). Plan:
`docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md`.

**Postgres and Docker are now needed for NOTHING.** They were ingest-only
after Plan 1; ingest no longer touches either. The legacy `db/` modules stay
in-tree unused (removal is Plan 5), and `scripts/migrate_to_lancedb.py`
remains as the migration-era record.

- **Queue (`ingest/`):** `jobs.py` (one JSON file per job under
  `<data_dir>/jobs/`, atomic writes, state machine, crash-resume),
  `lock.py` (SMB-safe single-writer lock via exclusive-create + heartbeat
  stale-steal — S6), `worker.py` (one daemon thread in the app process:
  extract → chunk → embed → write), `mineru_runner.py` (streamed per-page
  progress, timeout, cooperative cancel that kills the child, `JLBC_MINERU_*`
  offline pinning — S7), `lance_writer.py` (Chunk→Arrow row, idempotent
  per-doc replace, documents.json merge, real titles), `validate.py`
  (advisory post-ingest checks ported from `db/validate.py`).
- **Resume granularity is the stage, and inside extraction the page range.**
  MinerU runs 1–3 min/page on an i5-1245U, so a 210-page book is an overnight
  job that WILL be interrupted. Extraction output lands on the share
  (`<data_dir>/extractor-output/<doc_id>/`) so any machine can continue.
  Chunking and embedding are re-derived rather than journalled — minutes, not
  hours.
- **Write phase, every time:** ingest lock → S17 `snapshot()` →
  `delete_doc` → `upsert_chunks` → `build_fts_index` → `optimize` →
  documents.json merge. The FTS rebuild is not optional: new rows are
  invisible to BM25 without it, which looks like a working ingest with
  silently broken keyword search.
- **Upload API + page:** `POST /api/upload` (multipart) with the Invariant 8
  gate enforced SERVER-side (400 without the public-record confirmation),
  content-hash dedup against both documents.json and pending jobs (409 with
  when/who + an explicit re-process option), `GET /api/jobs`,
  retry/cancel. `webapp/src/pages/Upload.tsx`: always-visible Invariant 8
  notice, required checkbox, filename-heuristic metadata form, live queue with
  per-stage progress. Copy states the real cost — "large books process
  overnight" — deliberately not softened.
- **Real titles.** `build_title()` retires the migration's
  "GOVERNOR FY2027 fy2027" strings for new ingests, and
  `app/search_provider.py` now consults documents.json's title (gated on
  `ingested_at`, so migration-era junk titles still lose to the humanizer) and
  re-reads the sidecar when its mtime changes. Both gaps were found by the
  end-to-end run, not by a test.
- **Fiscal notes are live (S10).** `POST /api/fiscal-notes/refresh` queues a
  `refresh`-kind job that scrapes `azjlbc.gov/fiscal-notes/?Year=`, diffs
  against the directory, downloads only new note PDFs, and feeds them to the
  normal queue. `GET /api/fiscal-notes` now serves
  `<data_dir>/fiscal-notes-directory.json` when present (mtime-checked; the
  Plan 2 `lru_cache` is gone — it would have pinned the pre-refresh copy for
  the process lifetime) and falls back to the committed snapshot otherwise, so
  a fresh install shows 28 sessions on day one. Scraper breakage degrades to
  last-good LOUDLY: a session that returns zero rows when notes are already on
  file fails the refresh instead of deleting them. The FiscalNotes rail's
  reserved search box is now a real semantic search over `fiscal_note_chunks`,
  disabled until the corpus reports passages.
- **Add a JLBC book (Task 15).** `data/jlbc-book-sources/` vendors the website
  mockup's verified URL harvest (read-only, snapshot 2026-06-16);
  `scripts/build_book_catalog.py` turns it into the committed
  `data/jlbc-book-catalog.json` — **41 approps (FY1984–2026) + 21 baseline
  (FY2007–2027) editions**, pinned by test. `ingest/book_discovery.py` is
  catalog-first (zero network on a hit) and falls back to a HEAD-verified
  candidate ladder for editions published after the snapshot, walking BOTH the
  agency index and the linked TOC (their children are disjoint). Dead hosts
  rewritten, URLs never re-encoded, case-insensitive dedupe, and a rolling
  `/budget/` guard that refuses an index whose links belong to another year.
  `GET /api/books/catalog`, `POST /api/books/discover` (no downloads),
  `POST /api/books/ingest` (one job per document, URL-only — each job fetches
  its own PDF when its turn comes).
- **Tests:** 772 pytest + 71 webapp vitest green.
- **Corpus counts** are unchanged for the shared dev corpus (382 documents /
  7,755 budget chunks); Plan 3 adds no documents on its own.

### Verified end-to-end on 2026-07-31 (real network, real MinerU)

- A real 2-page PDF uploaded through `POST /api/upload` ran
  `extracting → live` with per-page progress, produced 6 passages, took an
  S17 snapshot, copied the source into `<data_dir>/pdfs/`, and came back in
  search titled **"FY 2027 Baseline — Industrial Commission of Arizona"** —
  a title derived from the document's CONTENT, not its filename.
- The validation gate correctly flagged that document as only 17%
  agency-stamped (it is the Industrial Commission's page; the filename said
  AHCCCS) — advisory, non-fatal, visible on the queue.
- A live fiscal-note refresh scraped azjlbc.gov, detected two withheld 2026
  notes (HB 4049, HB 4092), downloaded them, ingested both, and the rail
  search returned their real text. Directory restored to 112 bills.
- A live dry-run of book discovery (listing only, nothing ingested) found the
  **FY2027 Appropriations Report** — which the harvest recorded as
  expected-but-unpublished — via the probe ladder and walked **139 documents,
  0 unreachable**. That is the exact scenario Task 15 exists for.
- Budget eval re-run against the real corpus: **recall@5 72.41%, recall@15
  96.55%, recall@20 100%** — identical to the Plan 1 baseline. No retrieval
  regression. Results committed under `eval/results/`.

### Known follow-ups

- **The fiscal-note eval set has queries but no ground truth.**
  `eval/fiscal_note_queries.yaml` holds 12 coordinator-triage-shaped queries
  and `eval/run_eval.py` takes `--corpus fiscal_notes` (with its own results
  filename prefix so a fiscal-note run can never be diffed against a budget
  one). Ground truth is deliberately empty: it must be real chunk_ids from a
  populated corpus, and populating the 2,126-note back catalogue is an
  overnight MinerU run that has not happened. The file says so at the top.
  **This is the one part of Plan 3 that is not finished.**
- The search provider's corpus probe is still startup-only (Plan 2's
  documented trade), so the FIRST ever ingest into an empty data dir needs a
  restart before search leaves the stub. Every later ingest is picked up live.
- Large historical backfills (dozens of books) are smartest run on Destin's
  machine before departure — office CPUs make it a weeks-long grind. The
  catalog + picker make it possible either way.
- FY2024/25 approps summary-section titles were partly unextractable in the
  mockup harvest; the PyMuPDF walk may recover them, humanized filenames are
  the fallback.
- `db/migrations/0001` doc_type enum comment is still stale vs live data.

---

## Standalone consolidation — Plan 4 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S2, S3, S9, S13-read, S15, S16, S19, Invariants 7 + 8). Plan:
`docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md` — see its
**"Task 8 amendments"** block for the as-shipped HTTP contract, which is what
Plan 5 builds against.

**MCP and YouCoded are gone.** AI Mode is an in-process Python tool loop
talking to OpenRouter. No `ws://localhost:9900`, no PTY, no per-conversation
`.mcp.json`, no separate Node process, no dependency on a running desktop app.
`mcp-server/` and `web/` remain in-tree, unused and still passing their own
tests; deleting both is Plan 5.

- **Harness (`harness/`):** `settings.py` (the shared `settings.json` —
  provider triple per S15, tier→model map per S16, admin username, S19 limits),
  `constants.py` (**`REFUSAL_THRESHOLD = 1.9` is now the single source**;
  three contradictory numbers used to reach the model — 1.9 in the prompt,
  0.65 and 0.30 in stale tool descriptions), `tools.py` (the five tools as
  OpenAI function schemas + `ToolExecutor`), `documents.py` (`create_document`),
  `ledger.py` (S19), `session.py` (the loop), `prompt.py` + `system-prompt.md`.
- **The first-call cap is per-conversation, not per-process.** The Node
  original used a module-level flag because there was one process per session;
  one process now serves the whole office, so that shape would have left user
  B's first question uncapped because user A had already asked one.
- **`retrieval/citations.py`** — cite validation lifted out of the FastAPI
  sidecar module so the harness can call it in-process for either corpus. The
  dead alignment heuristics (6 functions, 2 thresholds, ~10 regex tables, 16
  tests) are deleted; the endpoint-level regression guards that assert the
  check stays dead are kept.
- **Routes (`app/routes/`):** `conversations.py` (create + SSE messages +
  stop + `/api/ai/status`), `pdf.py` (Range-streaming + `/api/chunks/{id}`),
  `documents.py` (token downloads). Conversation registry is in-process,
  LRU-capped at 40, and never evicts a conversation with a turn in flight.
- **Webapp:** the chat stack ported from `web/` into `webapp/src/chat/` and
  `webapp/src/pdf/` — citation extraction (~70 carried specs), chat reducer,
  citation bus, chips, markdown, tool cards, mascot, PDF viewer with
  strict-bbox highlighting, cited-text panel. AI Mode toggle on Budget Search
  and Fiscal Notes (**superseded 2026-07-31** — see the deviation note below);
  Home's AI card goes live when a key is present.
- **Tiers (S16):** Standard (step cap 15, `deep_dive` ignored) and Deep
  Research (cap 50, `deep_dive` allowed). Tier explainer copy lives
  **server-side** in `/api/ai/status` so Plan 5's admin page and the webapp
  cannot drift. Every new conversation starts on Standard.
- **Cost (S19):** month-sharded JSONL ledger on the share, per-user limits with
  overrides and exemptions, warn at 80%, block at 100%. Blocked users get the
  ledger's exact sentence, emitted from one place. Limits are inactive on a
  custom endpoint (S15) because exact costs are unavailable, and that state is
  distinguishable from "allowed because under limit".
- **Invariant 7 is structural, not aspirational.** No tool schema takes a path;
  `harness/documents.py` does not import `store.config`, so it has no way to
  learn where the share is; AST-based tests pin the import allowlist.
  `create_document` writes only to `%LOCALAPPDATA%`.
- **Tests:** 1209 pytest / 36 skipped, 297 webapp vitest. `setup.sh --verify`
  green (it also still runs the retired `mcp-server` 57 and `web` 220 suites).

### Verified end-to-end on 2026-07-31 (real OpenRouter key, real corpus)

Tiers as configured: Standard = `qwen/qwen3.7-plus`, Deep Research =
`moonshotai/kimi-k3`. Driven through the real SSE route, not in-process fakes.

| Check | Result |
|---|---|
| Standard lookup ("ADC General Fund, FY 2025") | 3 retrieves → 1 passing cite. **$0.0127, 50s.** Answer volunteered the AFR-vs-Baseline accuracy hierarchy from the prompt without being asked |
| Refusal (out-of-scope question) | Named its corpus, cited nothing, fabricated nothing, **did not retrieve** (correct — out-of-scope needs no search). $0.0018, 13s |
| `create_document` | Real `.docx` in `%LOCALAPPDATA%\JLBC-Insight\documents\` — Title style, memo header, Heading 2 sections, List Bullets. **Nothing written to the share (Invariant 7 held)** |
| Deep Research (3-year AHCCCS comparison) | 4 retrieves / 41 chunks → a correct 3-year table, 5 passing cites. **$0.563, 295s** |
| Ledger | 20 rows, one per step, real per-call cost, `month_total` $0.61, **0 rows with unknown cost** |
| Key removed | `/api/ai/status` → `available: false`, `"no API key configured"`; **search still returned 20 results**. Restoring the key re-enabled AI Mode with no restart (the mtime cache works) |

**Not verified — needs a human at a browser.** Chip click → PDF opens at the
highlighted bbox, and the source panel's visual behaviour. The logic underneath
has 298 vitest specs, but nobody has watched it render.

### Problems the live run surfaced (model/prompt behaviour, not code defects)

- **Citation discipline is unreliable on memo-shaped asks.** Two identical runs
  of the same `create_document` prompt produced 20 citations (12 passing) and
  then **zero** — the second wrote a memo full of specific dollar figures and
  cited nothing, which is an Invariant 1 failure in practice. The UI degrades
  honestly (this is exactly the shape `RefusalBanner` detects: complete turn,
  retrieved, no verified citation), so an analyst sees "This answer carries no
  verified citation" plus the passages rather than false confidence. But the
  prompt and/or the Standard model needs work before this is trustworthy.
- **Cite failure rate is high when cites ARE emitted** — 12/20 and 5/7 passing
  across runs. Worth reading the failure reasons in a longer dogfood.
- **The download token leaked into answer prose.** The model wrote the raw
  `token: 2DZz_Lf…` into the answer instead of leaving the UI to render the
  link. Output-hygiene rule, not a code bug.
- **Meta-narration still leaks** — "let me search the corpus", "I have what I
  need. Let me write the memo". Note `finalAnswer` concatenates *every* prose
  block including pre-tool narration by design, so it reads worse in the audit
  record than on screen.
- **Deep Research costs ~44× Standard and takes ~5 minutes.** $0.563 vs $0.0127
  on comparable questions. The tier split is doing its job, but the copy should
  probably set the time expectation.

### What review caught that tests didn't

Recorded because the same classes will recur:

- **Starlette never closes a `StreamingResponse` body iterator.** It relies on
  garbage collection, and on the disconnect path the iterator sits in a
  reference cycle. A closed browser tab left a model streaming and billing into
  a dead socket, and left a PDF file handle open (which on Windows also blocks
  re-ingest from overwriting the cached file). Cleanup rides a `BackgroundTask`
  in both routes now. `TestClient` cannot catch this — it buffers a "streamed"
  response into a `BytesIO` before returning it, so `tests/live_request.py`
  drives the real ASGI stack.
- **An abandoned SSE stream used to corrupt the conversation permanently** —
  the assistant `tool_calls` message was in history with no matching reply, so
  every later turn 400'd. `_repair_history()` back-fills cancelled results.
- **`UnicodeDecodeError` is a `ValueError`, not an `OSError`.** One mis-encoded
  byte in a month's ledger shard crashed the spend gate for every user.
- **The old system prompt was lying about the refusal threshold** — it said
  `top_score` is "between 0 and 1" and to refuse below 0.30. Both false since
  the Plan 1 model swap (raw cross-encoder logits, roughly −10..10).
- **A dropped tool call rendered as a successful, empty answer** — Invariant 3's
  exact failure shape.
- **The refusal banner denied citations the analyst could see.** It counted
  tool-block cites only, but the renderer also extracts inline `<cite>` tags,
  which open-weight models emit more often than the models that fallback was
  written for.

### 2026-07-31 — AI Mode moved to its own tab (deliberate deviation from S9)

**Do not "restore fidelity" to S9.** Spec S9 says *"Every corpus page =
zero-inference semantic search + an AI Mode toggle (same search box; off =
results list, on = cited chat answer)."* That is what Plan 4 shipped, and after
using it Destin asked for the opposite: *"I hate that 'AI Mode' is part of the
budget search tab."*

As of 2026-07-31:

- **AI Mode is a destination, not a mode.** New route `/ai` (`webapp/src/pages/Ai.tsx`),
  reached from an **icon-only sparkle pill on the right end of the nav**
  (`.nav-item.nav-ai`, accessible name "AI Mode" via `aria-label` + `title`,
  built to the house glyph's exact recipe). Home's AI card points there too.
- **`Budget Search` is renamed `Budget Documents`.** The route is still
  `/search`; only the pill label and the page's identity changed — it is the
  document browser now, and nothing else.
- **The per-page toggles are gone** from Budget Documents and Fiscal Notes.
  Both pages render their browse surface unconditionally; neither imports the
  chat stack. `AiModeToggle` still exists in `webapp/src/chat/AiModePanel.tsx`,
  imported by nothing (deletion belongs to whoever next edits that file).
- **A corpus picker replaces the two toggles.** Budget documents / Fiscal notes,
  chosen inside `/ai`. This is not cosmetic: the fiscal-note coordinator is a
  primary user in the spec, and dropping the fiscal-notes toggle without a
  replacement would have deleted their "have we written a note like this
  before?" triage path.
- **Switching corpus starts a NEW conversation**, by remounting the component
  that owns `useChat` (`key={corpus}`). This is load-bearing: `useChat` reads
  the corpus only when it lazily creates the conversation and then holds that
  `conversation_id` for the hook's lifetime, so a prop change alone would keep
  answering fiscal-note questions out of the BUDGET corpus — cited and
  confident. Three specs in `webapp/src/pages/Ai.test.tsx` fail if the remount
  is removed. It also gives S16 for free: the tier resets to Standard.
- **AI Mode's gate is now a page, not a dimmed pill.** With no key configured,
  `/ai` renders the server's own explanation and no composer, rather than a box
  that would swallow the analyst's question.
- Webapp suites: **304 vitest** (was 297/298).

### Known follow-ups (Plan 5 unless noted)

**Found during the 2026-07-31 Z13 backfill run (see `~/backfill-progress.log`
on that machine and the ROCm investigation doc). These degrade the office
experience silently. Everything marked ✅ is on master — the lock-steal fix in
`f4ddf1d`, the worker-never-started and `make_doc_id`-collision pair in
`ingest-defects`, all 2026-07-31. Those code fixes ship at the app server's
next restart, since the running backfill has its modules already loaded.
Entries still marked 🔴 are genuinely open.**

- **✅ FIXED — the ingest lock could be STOLEN FROM A LIVE HOLDER, giving two
  writers on one corpus.** `IngestLock._try_create` created the lockfile and
  then wrote its JSON payload in a separate buffered step. A second machine
  that read the file inside that window saw it empty, judged it corrupt,
  treated it as stale, and stole the lock — defeating the entire S6
  single-writer invariant. **Reproduced, not theoretical:** a 24-thread race
  produced 8 simultaneous "winners" before the fix. Both halves of the fix are
  on master: `_try_create` now creates and writes in a single `os.write` on a
  raw fd (`ingest/lock.py`, with the WHY comment at that line), and a reader
  waits out `_SETTLE_PATIENCE_S = 1.0` before judging a lockfile corrupt.
  Landed 2026-07-31 in merge `f4ddf1d` ("Merge branch 'parallel-ingest' —
  opt-in parallel extraction + atomic job claiming"), so it is in regardless
  of whether parallel ingest is ever enabled. Guards:
  `tests/test_ingest_lock.py::test_corrupt_lockfile_is_treated_as_stale` and
  `tests/test_ingest_parallel.py::test_the_process_mutex_stops_a_sibling_thread_stealing_a_stale_lock`.
  **This entry said "not merged" until 2026-07-31** — it had in fact shipped
  earlier the same day, and the stale text caused a later session to report it
  as still-open work. Verify with `git merge-base --is-ancestor`, not prose.
- **✅ FIXED — `IngestWorker` was constructed at startup but never
  `.start()`ed.** Only the upload POST route started it, so on the shared
  drive a colleague's queued job sat untouched until somebody on *that*
  machine uploaded something — ingest appeared to hang for no visible reason.
  The app now starts it from a **lifespan handler** (`app/main.py::_lifespan`
  → `ingest.worker.ensure_started`), so any running server drains the queue.
  A lifespan handler rather than a line in `create_app()` because *building*
  an app object (every route test does) must not spawn threads — only
  *serving* should; Starlette runs lifespan on real startup and when a test
  opts in with `with TestClient(app)`. Starting is idempotent (the upload and
  books routes still call `start()` and get the same pool), a failure to start
  is caught and reported on stderr with the real error rather than taking the
  whole server down, and `create_app(ingest_worker=None)` is the explicit
  opt-out for a process that must not run ingest. Guards:
  `tests/test_app_server.py` — a job queued with no upload activity reaches
  `live`, double-start yields one pool, an exploding worker still boots the
  app, a missing `JLBC_DATA_DIR` still boots the app.
- **✅ FIXED — `make_doc_id()` collision silently DROPPED a document.** It
  filed `detailed-list-pdf` under "approps" regardless of family, so a
  baseline and an approps doc could generate the same doc_id; because a write
  is an upsert, the second replaced the first and one document vanished with
  no error. `make_doc_id()` now takes `family=` and, for JLBC book documents,
  the family wins wherever it disagrees with the class the `doc_type` implies.
  Wired at both mint sites that know the family: `app/routes/books.py`
  (`plan.family`) and `ingest/driver.py::_entry_to_item` (via `_family_of`,
  reading the plan target's already-family-prefixed doc_type). Callers that
  genuinely don't know the family — a person uploading a file by hand,
  singleton publishers — omit it and get byte-identical legacy ids.
  **Two collisions, not one.** The original audit ran against
  `data/jlbc-book-catalog.json` and found exactly one in 5,320 in-scope
  documents (FY2026 `26ar/508.pdf` vs `26baseline/508.pdf`, both
  `jlbc-approps-fy2026-508`). A second one exists that the catalog-based audit
  could not see, because the approps linked-TOC walk yields sections the
  catalog snapshot doesn't list: `26AR/capitaloutlay.pdf` is already in the
  corpus as `jlbc-baseline-fy2026-capitaloutlay` (`topic-pdf` hardcodes the
  baseline class), and the FY2026 Baseline book's **own** `capitaloutlay.pdf`
  is in the catalog, in scope, and not yet ingested — it would have minted the
  same id and overwritten it. That second collision is in the
  approps-filed-as-baseline direction, so a fix that only moved the baseline
  side would not have caught it. Guards: `tests/test_driver.py` (both
  collision pairs mint distinct ids; real non-colliding ids pinned unchanged;
  omitting `family` reproduces the legacy id exactly) and
  `tests/test_books_route.py` (enqueue both FY2026 books, assert zero doc_id
  reuse).
- **Six already-ingested documents would mint a different id on a
  from-scratch re-ingest** — the cost of the fix above, and the reason it was
  scoped to the misfiled shape only. They are the documents whose family
  disagreed with their `doc_type`'s class: `jlbc-approps-fy2027-{502,507,517,522}`
  (baseline sections filed as approps) and `jlbc-baseline-fy2026-{crr,capitaloutlay}`
  (approps sections filed as baseline). **Nothing rewrites them today** —
  `documents.json` entries and `chunk_id`s are written once, and
  `/api/books/ingest` de-dupes on `source_url`, so re-running an edition skips
  them rather than re-minting. The exposure is a full corpus rebuild:
  `eval/queries.yaml` q-001 pins `jlbc-baseline-fy2026-crr-0013`, which would
  become `jlbc-approps-fy2026-crr-0013`, and `eval/refresh_chunk_ids.py` — the
  tool that would re-bind it from `anchor_text` — is unported and still
  imports the retired Postgres `db.connection`. **Port the refresh tool before
  any from-scratch rebuild**, or re-point q-001 by hand at that time.
- **Pre-fetched PDFs landed in the wrong directory for ingest.**
  `ingest/cache.py`'s `DownloadCache` writes `data/cached-pdfs/` but the
  worker reads `<data_dir>/pdfs/`. Worked around during the backfill by
  hardlinking 7,479 blobs (0 extra GB). Decide on one canonical location —
  two caches for the same bytes is a trap for whoever maintains this next.
- **🔴 Shared `mineru-api` server: TRIED, CRASHED, ROLLED BACK — do not retry
  at high concurrency.** The idea was sound and the measurement was real: a
  per-document `mineru` invocation spends ~33 s of ~38 s loading models, and a
  warm shared server via `--api-url` took a document from 38 s to **8 s** with
  **byte-identical output** (block counts, text and bboxes verified on 3 docs).
  It also freed ~15 GB by keeping one set of models resident instead of one per
  worker. **But MinerU's server is not memory-safe under concurrency:** at
  `MINERU_API_MAX_CONCURRENT_REQUESTS=12` it died with a glibc
  `corrupted double-linked list` — native heap corruption, not something a
  setting can fix — and every in-flight worker then failed with
  `httpx.ConnectError`. 101 documents failed before rollback; all 101 were
  re-queued and recovered, no data was lost, and the pre-experiment archive
  (`~/corpus-before-parallel.tgz`) was never needed. The code seam survives:
  `JLBC_MINERU_API_URL` (merge `57035a8`, default unset = spawn-per-document =
  today's behavior). **If anyone revisits this, cap it at ~3 concurrent (the
  MinerU default) and expect roughly N=3 throughput, or wait for an upstream
  fix.** The per-invocation model load remains the single biggest theoretical
  win in ingest — batch mode (`-p <directory>`, measured **2.85×** on 4 docs)
  is the safer way to claim it, since it keeps one process per batch.
- **Measured parallel scaling curve (Z13, 32 threads / 121 GB, MinerU 3.1.6
  CPU).** Use these numbers, not guesses, when sizing any future bulk run:

  | workers | docs/hr | per doc | vs serial | notes |
  |---|---|---|---|---|
  | 1 | 93 | 40.0 s | — | extraction is ~92% of a document (39.0 s of 42 s) |
  | 4 | 413 | 8.7 s | 4.4× | |
  | 8 | ~700 | 5.1 s | 7.5× | **the knee** — 14.6 of 32 cores, 12 GB |
  | 14 | 750 | 4.8 s | 7.9× | +7% only; 18 cores, 25 GB; exposed the job-journal race |

  Past ~8 workers the machine is NOT CPU-bound (18 of 32 cores at N=14) — the
  limit is MinerU's own serial phases and I/O, so more workers buy very little.
  The FTS rebuild inside the serialized write cost 0.25 s at 4.7k rows (a
  ~14,000 docs/hr ceiling, not binding then) but **grows with table size**, so
  on a much larger corpus the serialized write becomes the wall and a
  per-batch FTS rebuild is the fix. The remaining real lever on extraction
  itself is **MinerU 3.4.4** (measured 1.35× on plain CPU).
- **Parallel ingest is LIVE and VERIFIED (2026-07-31).** Merged (`f4ddf1d`)
  and enabled on the Z13 backfill at `JLBC_INGEST_WORKERS=4`. **Measured 385
  docs/hour vs the 95/hr serial baseline = 4.05x** — above the 2.5-3.5x
  projection; remaining backfill fell from ~67 h to ~17 h. Verified live, not
  just in tests: 4 concurrent extractions with distinct doc_ids and zero
  duplicates, 0 failed jobs, 0 `ingest lock held by` errors, load 13.9/32.
  Data quality on 93 parallel-ingested documents audited: 93/93 real
  content-derived titles (incl. the `<strike>`/`NOW:` amended-bill form),
  0 missing source paths, 0 chunks missing page provenance across 400
  sampled, 0 empty text, 0 documents with zero passages. Default remains
  N=1 for the office; every invalid value means 1; clamped to
  `min(8, cpu_count/4)` so a 4-core office PC gets 1 and says so.
  **Superseded design note kept for Plan 5:** the prior entry below described
  this as awaiting a decision.
- **[superseded] Safe parallel ingest was BUILT AND TESTED, awaiting a decision** — branch
  `parallel-ingest` (`85ecccb`), not merged, not deployed. Design: parallelize
  extraction (the ~78–90% of wall clock that needs no lock), keep the write
  phase serialized under the existing `IngestLock`, serialize embedding behind
  one process mutex (one shared ONNX model). New `ingest/claim.py` gives
  atomic per-job ownership keyed on BOTH job_id and doc_id (the doc_id key
  guards the `make_doc_id` collision above), with heartbeat/PID stale-steal.
  Opt-in via `JLBC_INGEST_WORKERS=N`, default 1 = byte-identical to today;
  every invalid value means 1; clamped to `min(8, cpu_count/4)` so the same
  variable on a 4-core office PC clamps to 1 and says so. **196 tests pass**,
  asserting no double-run, no lost jobs, same-doc serialization, writes
  serialized, extraction never holding the lock, crash-recovery in both
  directions, and N=1 identical. Measured from the live run to size it:
  ~2.1 GB RSS / ~3.2 cores per extraction. Reasoned projection **~2.5–3.5× at
  N=4** (95 → 240–330 docs/hr) — NOT measured against real MinerU, since that
  would have competed with the live backfill. Verified prerequisite: the
  backfill maintainer (`~/backfill-scripts/maintain.py`) already takes
  `IngestLock` and heartbeats during `optimize`, so it is safe alongside a
  worker pool. Before enabling mid-run also: re-export
  `JLBC_INGEST_SNAPSHOT=off` and kill orphaned `mineru` trees after the
  restart. (The old "POST something to start the pool" step is gone — since
  the `ensure_started` fix above, a restart alone starts it.)
- **MinerU 3.4.4 vs the pinned 3.1.6** — measured 1.35× faster on plain CPU
  (28.5s vs 38.5s on an 8-page doc; beats the ROCm GPU path outright),
  device-invariant output, and it fixes a table row-misalignment seen at
  3.1.6. Changes chunk text corpus-wide ⇒ needs an eval-gated evaluation and
  a re-ingest decision. Worth ~16h on a full backfill.
- **ROCm GPU MinerU: tested, rejected, do not re-litigate without new
  evidence.** Works trivially on gfx1151 (torch 2.13+rocm7.2, no
  `HSA_OVERRIDE`), but break-even is ~5 pages against a 2-page corpus median
  (CPU ≈61h vs GPU ≈63h over the real backfill mix — it's an APU sharing one
  power budget), and at MinerU 3.1.6 it produced device-dependent table
  extraction that put a real dollar figure on the wrong budget line. Full
  evidence: `docs/superpowers/investigations/2026-07-31-rocm-mineru-benchmark.md`.

- ~~**Prompt caching is not requested.**~~ ~~**Quote-not-found cite failures
  on faithful quotes.**~~ **Both SHIPPED 2026-07-31 (S22 + S23, merge
  `5e1ae3b`) — see "AI Mode hardening" below.**
- **`--chat-*` / `--mascot-*` tokens on `:root`** (16 of them) deviate from
  S12's one-palette rule. The mockup palette is monochrome navy — `--az-red` is
  `#2f55c4`, a blue — so there is no error/warning colour, and a failed-citation
  chip rendered in navy would regress Invariants 1–3. **Worth Destin's eye.**
- **[v2, DEFERRED 2026-07-31] Drop the AI Mode corpus picker; let relevance
  choose the corpus.** Destin: "I really don't want a toggle for two distinct
  budget/fiscal-note corpus modes — I'd rather the model pull the right
  documents based on its own determination." Deferred to a v2 pass, not
  rejected. The investigation is recorded here so it isn't re-done:
  - **The UI is the cheap part** (~20 min): delete the picker, the `key={corpus}`
    remount, and 3 specs in `webapp/src/pages/Ai.test.tsx`.
  - **The cost is the system prompt** — `harness/system-prompt.md` carries **20
    `{{#when corpus=…}}` blocks across 1,107 lines** (corpus-specific retrieval
    recipes, filter dimensions, doc-lifecycle guidance). Merging them into one
    both-corpora prompt is real prompt engineering with eval risk.
  - **Nothing is needed in `retrieval/pipeline.py`** — `RetrievalRequest.corpus`
    already exists, so retrieval is per-call corpus-aware today.
  - **Preferred design: search BOTH corpora, don't make the model choose.**
    Embed the query once (the embedding is corpus-independent), run both hybrid
    searches concurrently, merge into ONE rerank pool (top-10 each, so the pool
    stays at today's 20 and the cost is nearly unchanged), and label each result
    with its corpus. This removes the failure mode rather than relying on the
    model to avoid it — a mis-classified question currently answers out of the
    wrong corpus, cited and confident. It also makes the S22 cache prefix
    corpus-independent.
  - **The subtle piece is `cite`.** `validate_cite(body, corpus=…)` needs to
    know which corpus a chunk came from. Do NOT ask the model to re-state it —
    have `ToolExecutor` record chunk_id → corpus from every retrieve result it
    already sees, and resolve from that map. `/api/chunks/{id}` (which takes a
    `corpus` query param) needs the same treatment.
  - **Prerequisite:** build ground truth for `eval/fiscal_note_queries.yaml`
    (~1 h against the now-complete note corpus). Without it a merged-retrieval
    change is protected by the budget eval only.
- Conversation persistence is in-memory per app run (accepted).
- The faithfulness verifier (WS3) and audit-log writer (WS5) remain unbuilt —
  citation enforcement is still chunk-id + quote-in-text + span sanity.
- **Bulk-ingest mode exists (`JLBC_INGEST_SNAPSHOT=off`, 2026-07-31)** — it
  suppresses the per-document S17 snapshot for supervised backfills, because
  zipping the whole corpus once per document is O(n²) (measured: ~54 MB zip
  every ~40 s at 68 MB of corpus; projected 60–90 s/doc after the books).
  Default is unchanged (`per-doc`) and only the literal `off` disables it. The
  better long-term design is a per-BATCH snapshot — once per book edition /
  fiscal-note session rather than per document — which keeps a restore point
  without the quadratic cost.
- **Parallel ingest exists (`JLBC_INGEST_WORKERS=N`, branch
  `parallel-ingest`, 2026-07-31)** — N worker threads each claim their own
  job and extract concurrently; the write phase stays strictly serialized
  behind `IngestLock`. Default is 1 = today's behaviour, and anything that
  isn't a number above 1 (typo, blank, `0`) means 1. The request is clamped
  to `min(8, cpu_count/4)` so the same variable typed on a 4-core office PC
  clamps to 1, and the clamp is announced on stderr. Ownership is decided by
  `ingest/claim.py` — an atomic exclusive-create claim file per job AND per
  doc_id, with a heartbeat thread and stale-steal, mirroring `ingest/lock.py`.
  Measured input: a MinerU extraction averages ~3.2 CPU cores (peak ~7) and
  ~2.1 GB RSS (peak ~3.0 GB) across its 2–3 processes, and is ~90% of a
  document's wall clock. Two pre-existing concurrency defects were fixed on
  the way: the old lock-based claim was a non-atomic read-then-write (two
  workers could both take a job) and it stopped claiming entirely whenever
  any machine held the write lock; and both the lock and claim files could be
  read empty by a racing acquirer mid-create, which read as "corrupt" → "stale"
  → **steal**, i.e. two writers on one corpus. Creation is now a single
  `os.write` and an unreadable file gets 1s to settle before it is judged
  corrupt.

---

## AI Mode hardening — S22 + S23 shipped (2026-07-31)

Spec: `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`
(S22, S23). Handoff: `PROMPT-parallel-ai-hardening.md` (now retired — do not
execute). Merge `5e1ae3b`. Done in parallel with the running Z13 backfill;
touches only `harness/` and `retrieval/citations.py`, nothing on the ingest
path.

### S22 — prompt caching

The ~40 KB (~13.5K-token) system prompt was resent uncached on every step,
up to 50 steps in one Deep Research turn, while every candidate model prices
cache reads roughly 10× below fresh input.

- **The cacheable prefix is now a pinned PROPERTY, not a coincidence.**
  `tests/test_harness_prompt_caching.py` asserts the system message + tool
  schemas are byte-identical across steps of a turn, across turns, and across
  conversations and users, plus a guard that today's date never appears in
  the prefix. That guard is the point of the file: the obvious way a future
  edit breaks caching ("tell the model what day it is") is one line, and it
  has NO symptom — answers stay correct, tests stay green, the bill silently
  goes back up ~10×.
- **Anthropic-style models get an explicit `cache_control: ephemeral`
  breakpoint** on the system content part; OpenAI/DeepSeek/Moonshot-style
  models rely on implicit prefix caching and still get a plain string.
  Anthropic orders a request tools → system → messages, so ONE breakpoint at
  the end of the system block covers the tool schemas too. Selection is a
  substring table (`ANTHROPIC_STYLE_MODEL_MARKERS` in `harness/session.py`),
  because the same model arrives under more than one id. Gated on
  `provider == "openrouter"` for the same reason `usage: {include: true}` is
  — S15's custom endpoint may reject unknown fields outright.
- **`cached_tokens` now rides on every ledger row** and sums into
  `MonthUsage`. Visibility, not arithmetic: `cost_usd` is OpenRouter's own
  exact figure and already reflects the discount. Pre-S22 rows have no such
  key and read as 0.
- **Defect fixed on the way:** the context-window budget passed
  `len(system["content"])` as `reserved`, which reads **1**, not ~40,000, once
  the prompt is wrapped in content parts — the history window would have
  silently grown by the whole prompt's budget and pushed requests over the
  model's context limit with no local error. A test pins that the window is
  identical with and without the wrapper.
- **NOT VERIFIED LIVE.** No OpenRouter key is configured on this machine, so
  nobody has yet seen a real `cached_tokens > 0` or the per-step cost drop
  after step 1. **The next person with a key should run one multi-step turn
  and check the ledger rows** — that is S22's acceptance criterion and it is
  outstanding.
- **Known limit, accepted per S22:** context-window truncation breaks the
  prefix when it fires. Rare, and noted in a comment rather than engineered
  around.

### S23 — normalization-tolerant quote validation

Models emit quotes that are faithful to the chunk and differ from it only by
formatting — a smart quote, a collapsed line break, casing, an em dash
retyped as a hyphen, MinerU's `\$` escape. Exact-substring validation called
every one of those "quote not found" and burned a retry round-trip.

- `retrieval/citations.py` falls back to normalized matching **after** exact
  match fails, so a quote that appears verbatim still binds to the verbatim
  occurrence.
- **`resolved_span_start` / `resolved_span_end` always reference the ORIGINAL
  chunk text**, via an index map. The PDF bbox highlighter and the
  cited-text panel slice `chunk.text` with those offsets, so a normalized
  offset leaking out would highlight the wrong words while reporting success.
- The normalizer is a **port of the webapp's `normalizeForMatch`**
  (`webapp/src/chat/citation-extract.ts`), not a second dialect — the same
  chunk text is normalized on both sides of the wire.
- **Formatting-tolerant, never semantically looser.** Reordered words and
  paraphrases are still rejected; ambiguity rejection still applies
  post-normalization, with positions reported as ORIGINAL-text offsets.
  Invariant 2 is unchanged.
- System-prompt nudge added: quote SHORT, distinctive spans copied exactly.
  The prompt's "Format equivalence" paragraph previously described a
  normalization that **did not exist** — it now describes what the check
  really does.
- Two defects caught in self-review and fixed: `'İ'.lower()` is two code
  points in Python, which desynchronized the index map (every citation later
  in that chunk would have mis-highlighted); and the markdown-link scan was
  O(n²) on a bracket-heavy chunk. Both pinned by tests.

**Tests:** 1394 pytest / 36 skipped (was 1392 before this work — 38 new
specs across two new files). The webapp was not touched, so its 304 vitest
were not re-run.

**Eval not re-run, deliberately.** `harness/system-prompt.md` changed, which
normally triggers the eval rule in CLAUDE.md — but `eval/run_eval.py` calls
`retrieve()` directly and never reads the system prompt, so it cannot
measure this change; and the corpus is actively changing under the running
backfill, so any number produced now would be meaningless. Re-run it after
Phase C for the recency work, not for this.

### Follow-ups this work created or found (for Plan 5)

- **S22 live verification is outstanding** (above).
- **Only the SYSTEM prefix is cached.** In a long Deep Research turn the
  conversation history — every prior tool result — is also resent every step
  and is often larger than the prompt. A rolling `cache_control` breakpoint
  on the last history message is the standard next win. Deliberately not
  attempted here: it is outside S22's scope, and OpenRouter's translation of
  content parts on `tool`-role messages is unverified.
- **The webapp and server normalizers can still drift.** Two known
  divergences, both benign today and both worth knowing about: the server
  applies NFKC **per code point** (exact index map) where the TS normalizes
  the whole string and approximates the map proportionally when the length
  changes; and Python's `str.isspace()` covers a few characters JS's `\s`
  does not. Neither occurs in this corpus. There is no shared test fixture
  pinning the two implementations against each other — that would be the
  real fix.
- `MonthUsage` gained `cached_tokens`; Plan 5's admin usage panel should
  render it, otherwise the number is recorded and never seen.
  **Resolved in Plan 5 Session A, but not as written** — see that section's
  "cached tokens are watched, not displayed".

---

## Standalone consolidation — Plan 5 Session A shipped (2026-08-01)

**Tracks 1 and 2 (tasks 1–13).** Track 3 (packaging) shipped separately from
Session B — see its own section. Track 5 (handbook, tasks 21–23, Session C)
is not started. Track 4 (legacy deletion + remaining ingest defects, tasks
18–20) waits on Session C, so `web/`, `mcp-server/`, `db/`, and the legacy
`retrieval/` modules are **still in-tree and still unused**.

> ✅ **RESOLVED in Track 4 (2026-08-01) — all three open items are built.**
> Kept below as the record of what was owed and why. See
> `docs/superpowers/investigations/2026-08-01-bundle-app-requirements.md`.
> Status as of this merge: **#1 (per-machine `ingest_enabled` flag + the
> "nobody is processing uploads" admin warning) — **BUILT, Track 4**. **#2
> (`/health` returns 200 whenever the process serves) — already satisfied;**
> the route is a plain dict with no status logic and the ladder deliberately
> lives at `/api/health/detail`, so no change is needed. **#3
> (`python -m app.machine_config --set-data-dir` so `install.cmd` stops
> hand-writing JSON) — **BUILT, Track 4**. #4 is informational.
>
> **#1 is the consequential one.** `launcher.pyw` calls `create_app()` with
> no arguments, which starts the ingest worker — on ~20 office PCs that is 20
> workers racing for one queue. `IngestLock` keeps it safe, but the winner is
> arbitrary and may be an analyst's laptop that then spends six hours at 100%
> CPU. Defaulting the flag to OFF re-creates the opposite failure (uploads
> queue on the share and nothing drains them, silently), which is why the
> admin warning is not optional.

### What shipped

- **Admin identity + soft gate** (`app/identity.py`). Keyed on the Windows
  username. **This is not authentication and must never be described as
  such** — it keeps a curious analyst out of the settings page, nothing
  more. First run claims the admin slot one-way.
- **Break-glass recovery.** A file named `RESET-ADMIN.txt` in the data dir
  clears the admin slot; it is consumed on read, so it works once.
- **Settings API** (`app/routes/admin.py`) — reads never return the API key
  (only `api_key_set` and a last-4 hint); writes take a `"__unchanged__"`
  sentinel so a round-trip cannot blank the key.
- **Ledger breakdown** by user / model / tier, plus `/api/me` and
  `/api/me/usage`.
- **OpenRouter catalog** (`harness/catalog.py`) — tool-calling filter, 8
  curated recommendations, 6-hour cache, offline-first with a bundled
  fallback list.
- **S13 model fallback** — a per-process runtime override with a persisted
  notice. Deliberately **not** a settings write: a transient provider fault
  must not silently rewrite what the admin chose.
- **Corpus health + guarded one-click restore**; snapshot listing.
- **Admin page + Settings page** (`webapp/src/admin/`, `webapp/src/pages/`).
- **S18 per-machine data-dir pointer** below the env override.
- **Launch health ladder + repair screen** — five short-circuiting rungs in
  plain English.
- **Corrupt-settings preservation** — an unparseable `settings.json` is
  copied to `settings.json.corrupt-<timestamp>` before being overwritten.
  Those bytes may hold the only recoverable copy of the API key.

### The admin page was rebuilt across seven review rounds

The first version passed its tests and was still wrong on the page. What
Destin's review changed, in order: eliminate "unknown cost" at source; drop
jargon; group into nested cards; make AI Mode a chain of switches; replace
the orphaned Save button; fix toggle hitboxes; rebuild the model picker with
cost and capability; keep it a dropdown rather than a list; replace "pages at
once" with a real capability measure.

### Decisions worth not re-litigating

1. **A custom endpoint must declare both per-million prices.** This is not
   cosmetic. `check_limit` previously treated *any* custom endpoint as
   "limits structurally inactive", so an office on a custom endpoint had **no
   spending cap at all**, silently. The gate is now `has_pricing`, and a
   custom endpoint without prices is refused at save time.
2. **AI Mode is a chain of switches**: master switch → API key → per-mode
   switch → model choice. Each step unlocks the next.
3. **In `ai_available()`, "no model configured" is checked BEFORE the
   per-mode switch.** Saving resolves the unset sentinel, so without this
   ordering a save-and-reload turned "never configured" into "explicitly
   switched off" — two different things to an admin trying to fix it.
4. **The model picker is a dropdown, not a list.** A radio list showed
   eight rows permanently; this is a twice-a-year setting.
5. **Intelligence is a percentage of a fixed ceiling** (`INTELLIGENCE_CEILING`
   in `harness/catalog.py` — Opus 5's Artificial Analysis Intelligence Index
   plus 10% headroom), not the raw index. The headroom is deliberate: a
   leader at 100% would claim "as good as models get", which expires the week
   a better model ships. Nothing on the shortlist may reach 100% — there is a
   test that fails when it does.
6. **No speed or latency rating anywhere.** OpenRouter publishes those fields
   but returned `null` for every shipped recommendation on 2026-07-31. A
   spec test asserts the words "latency", "throughput", and "speed" never
   appear in the picker.
7. **Cached tokens are watched, not displayed.** The prior follow-up asked
   for a "cached input" column; "cached input" is meaningless to a
   non-technical admin, so `cached_tokens` instead drives a
   `cacheLooksBroken` health warning. The number is used, never shown.
8. **First-party flagships stay off the shortlist** (S16). For scale, at the
   prices and question profile in `TYPICAL_QUESTION`, Opus 5 costs ~42¢ for
   a Standard lookup against ~1¢ on Qwen3.7 Plus.

### What review caught that tests didn't

The suite mocks the API and jsdom applies no stylesheet, so wire-format,
layout, and paint-order bugs are **structurally invisible** to it. Every one
of these came from opening the page:

- **`ai_enabled` never reached the API.** It was added to the TS types and
  the UI but not to `_redacted()`/`_merge()`, so the client read `undefined`
  → falsy → a working install rendered AI Mode OFF. All vitest passed.
- **Toggle hitboxes only worked on the label text.** `.adm-toggle-track` is
  `position: relative`, so it painted above the `inset: 0` input and ate the
  click; the statically-positioned text did not. Fixed with a `<label>`
  wrapper — reverting it fails 4 of 8 specs.
- **The picker popup was clipped by three separate contexts** —
  `.card{overflow:hidden}`, `.adm-card{overflow:hidden}`, and
  `.adm-panel{overflow-x:auto}`. The identical bug and fix already existed in
  the same stylesheet for `.page-search .big-search-card`.
- **`data_dir()` creates the directory as a side effect**, so the health
  ladder could never detect a missing share — it conjured one and passed.
  Split into a pure `resolve_data_dir()` for the check.
- **`limits_active` was computed from the calling admin**, so an exempt admin
  saw "limits inactive" for the whole office. Now probed against an org view.
- **An empty corpus failed the health gate**, which would have locked a fresh
  install behind a failure screen with no route to Upload. It is an OK rung.
- **`tsc -b` (the production build) is stricter than `tsc --noEmit`** and
  rejects unused imports the dev check allows.

### Follow-ups this work created

- **The whole page is unverified against a real browser on a JLBC machine.**
  It was reviewed in a browser here against a synthetic data dir.
- **Three recommendations tie at 66% intelligence** (raw 44.4 / 44.3 / 44.2).
  Honest — that gap is noise — but the picker shows three identical numbers
  and only cost separates them.
- **The intelligence scale spans 50–85% in practice**, so the bottom half of
  every bar is dead space. Rescaling to the shipped range would use the full
  width at the cost of a fixed reference point.
- **`INTELLIGENCE_CEILING` is a hardcoded constant** and goes stale when
  Artificial Analysis re-scores. The re-derivation recipe is in its comment.
- **Error-message standards were not audited** across the admin surfaces.
- ~~**Two of Session B's four app-side asks are unbuilt**~~ **DONE in
  Track 4, 2026-08-01** — the per-machine `ingest_enabled` flag, its admin
  warning, and the `app.machine_config` CLI entry point all shipped.

---

## Layer 2 agent-loop eval harness shipped (2026-08-01)

### First live baseline — smoke, 2026-08-01

`eval/results/agent/2026-08-01T1157Z-25399b1/` — 11 queries, Standard tier
(`z-ai/glm-5.2`), **0 errors, $0.43, ~4 min**. Derived artefacts committed;
transcripts are gitignored by policy. This is the number every future
`compare_agent_runs.py` delta on the smoke set is measured against.

| metric | baseline | reading |
|---|---|---|
| key-fact rate | **0.91** | the answers are largely correct |
| refusal correctness | **1.00** | both out-of-scope questions correctly refused, nothing fabricated |
| `cite_pass_rate` / `first_try_cite_rate` | **0.99 / 1.00** | citations essentially never fail or retry |
| citations per answer | **9.0** | ⚠ far more than "a smaller number of high-value citations" |
| median quote length | **131 chars** | ⚠ wide; the goal is narrow, targeted spans |
| retrieval efficiency | **0.34** | ⚠ two thirds of retrieved chunks go unused |
| input tokens / answer | **83.6k** (60.3k cached) | ⚠ the dominant cost driver |
| steps / retrieves per answer | 3.5 / 2.1 | already tight |
| cost per answer | $0.039 | ~3× the $0.0127 STATUS recorded for a Plan 4 lookup |
| meta-narration | 1 of 11 queries | the known leak, now measured |

**The four ⚠ rows are the improvement backlog** and they map onto the goals
this harness was built to serve: citation volume and quote width (goal 4),
retrieval efficiency (goal 3), and prompt tokens (goal 1). Accuracy and
citation *reliability* are already strong, so the work is about doing the
same job with less — not about correctness.

**S22 prompt caching is VERIFIED LIVE by this run** — closing the acceptance
criterion left open on 2026-07-31. Of 39 billed steps, 35 report
`cached_tokens > 0`; the first step of each conversation reads 0 and every
later step is ~90% cached (e.g. 13,835 in / 13,760 cached). The caching is
real and is already saving roughly 72% of input tokens.

**Not yet run:** the full 31-query set and the 4-query Deep Research probe,
and the LLM judge (so `claim_coverage_precision` has no baseline yet).

Spec: `docs/superpowers/specs/2026-08-01-agent-loop-eval-design.md`
(the Layer 1 spec, `2026-05-20-retrieval-eval-harness-design.md`, is where
the Layer 2 goal was first deferred from — it is NOT what this was built
against). Nine tasks: query schema + transcript format,
the money-spending runner, the free mechanical scorer, the LLM judge, and
the run-comparison tool. Full usage docs, cost guide, and the experiment
loop are in `eval/README.md` → "Layer 2 — agent-loop eval"; this section
is the shipped-status record.

**What it measures that Layer 1 cannot.** Layer 1 (`run_eval.py`) calls
`retrieve()` directly and scores chunk recall — fast, free, and a strong
regression detector, but blind to everything downstream of retrieval.
Layer 2 (`run_agent_eval.py`) drives the REAL `HarnessSession` — the
production tool loop, no HTTP server — against open-ended analyst
questions and measures agent turns, tokens, cost, whether the final
answer actually contains the right key facts, citation discipline (cite
attempts vs. first-attempt passes), and output-hygiene leaks (meta-
narration, internal vocabulary, a leaked download token). **The two
layers' numbers are not interchangeable and must never be diffed against
each other** — different query sets, different things measured.

**It costs real money — unlike every eval that came before it.** A
`smoke` run (11 queries) runs roughly $0.15–0.30 on Standard tier, a
`full` run $0.50–1.50, and the 4-query `dr-probe` subset $2–3 (Deep
Research runs ~44× the per-query cost of Standard — see the Plan 4
dogfood numbers above). The LLM judge is a second, separate charge
layered on top of a run.

**`full` is all 31 STANDARD-tier queries and contains no Deep Research
query** — spec Decision #4, "Standard for the full set + a fixed 4-query
Deep Research probe", which explicitly rejected full-set DR runs. The
four DR queries briefly carried a `full` tag as well (fixed 2026-08-01):
that put ~$3 of Deep Research into a run priced at $0.50–1.50, moved
`wall_p95_ms` onto a ~295-second DR answer so Standard latency
regressions became invisible, and made `--subset full` refuse to start
on an install with Standard configured and Deep Research off — a
configuration `harness/settings.py` explicitly allows.
`tests/test_eval_agent_queries.py` now pins the exclusivity in both
directions.

**The runner writes its own ledger and never touches the office one.**
`check_limit` is stubbed to always-allow and `record_usage` writes into
the run directory's own `ledger.jsonl`, not the shared office spend
ledger — an eval run is pre-authorized by the human who started it, so
it must not be blocked by S19 office limits, and it must not silently
accrue against them either. **Eval spending will never show up in the
office usage totals** — that is by design, not a bug to chase.

**Single runs are stochastic.** `--repeats N` exists because model
output varies run to run; `compare_agent_runs.py` prints an explicit
warning whenever either side of a comparison is a single run, so a
small delta doesn't get mistaken for a real regression.

**The experiment loop the harness exists to serve** (for any change to
`harness/`, `retrieval/citations.py`, or `harness/system-prompt.md`):
cheap layer first (Layer 1 + free re-scoring of old transcripts), then a
live `smoke` run compared against a baseline `smoke` run, then before
merging a `full` run plus the judge, with the compare report committed
alongside the code change.

**Results-committing policy, implemented and verified against real
files, not just described.** Raw transcripts (`<query_id>-r<N>.jsonl`)
embed full retrieved-chunk text — large, and derived from the corpus
rather than from the change under test — so `.gitignore` now excludes
`eval/results/agent/*/*-r*.jsonl` and `eval/results/agent/*/ledger.jsonl`.
`manifest.json`, `scores.json`, `scores.md`, `judge.json`, and any
`compare-*.md` report are NOT excluded — they're the derived regression
record, at a fraction of the transcripts' size, and that's what a future
diff needs. Verified with a throwaway run directory containing one file
of each kind: `git status --porcelain` showed the untracked directory,
`git check-ignore -v` confirmed the transcript and ledger files matched
the new `.gitignore` lines and the five derived files matched nothing,
and `git add -n` staged the five derived files while refusing the two
ignored ones. The throwaway directory was deleted afterward — nothing
from the verification is in this commit.

**Final-review fix batch, 2026-08-01** (all pre-baseline, so no committed
results were invalidated):

- **`full` is Standard-only** — see the paragraph above.
- **`manifest.json` now carries `queries_sha256`**, a content hash of the
  queries a run actually asked, and `compare_agent_runs.py` refuses a
  comparison across differing query sets exactly the way it already refused
  one across differing corpus counts (`--force` overrides both, and a forced
  report says so). The id list alone was byte-identical when a query's
  key_facts were EDITED between two `full` runs, so the whole delta was
  authoring drift with nothing on the page saying so.
- **Two metrics were renamed and two added** — anything reading `scores.json`
  must follow. `first_attempt_cite_rate` was never a first-attempt rate; it is
  now **`cite_pass_rate`** (passes ÷ all attempts). The genuine measure is the
  new **`first_try_cite_rate`** (intended citations that passed on the first
  try), with **`retries_per_citation`** beside it. The spec's promised
  filter/corpus-parameter usage counts are now emitted too
  (`filtered_retrieve_rate`, `filter_dimension_counts`, and friends —
  informational, no better/worse arrow).
- **`retrieves_after_sufficient_mean` publishes its population**
  (`..._n` / `..._eligible_queries`) and the compare tool withholds the
  better/worse arrow when that population moved. The metric only exists for
  queries where the facts were eventually found, so a genuine retrieval
  improvement could otherwise render as a ▼ regression.
- **`total_cost_usd` is not the authoritative spend number** — a query that
  crashes mid-turn produces an error frame with no usage at all, so its
  already-paid tokens are invisible. `cost_missing_queries` counts those
  queries; `ledger.jsonl` (one row per step, written as it happens) is the
  real record, and `eval/README.md` now says so instead of presenting the two
  as equivalent.
- **Transcripts are written tmp+replace**, like every other artifact here. The
  reader's torn-file degradation stays — but a run should not manufacture the
  damage it tolerates, since a torn transcript scores as a failed query.

**Second fix-batch (small, post-review), 2026-08-01:**

- **`compare_agent_runs.py` now keys `total_cost_usd` on `cost_missing_queries`
  too**, the same population-dependent-arrow-withholding mechanism the first
  batch built for `retrieves_after_sufficient_mean`. A crashed query sums $0
  into `total_cost_usd` despite real spend, so a regression that crashes
  10-of-31 queries could render as a green cost improvement — reproduced
  before the fix (`cost_missing_queries` 0→10 alongside `total_cost_usd`
  1.2→0.81 showed a bare ▲). Deliberately NOT extended to `cost_mean_usd`,
  `steps_mean`, and the other means, which are equally population-dependent on
  `errors` — `errors` already carries its own visible ▼ on the same table,
  and over-applying the suppression would strip arrows off most of the
  report.
- **`retrieves_after_sufficient_eligible` held two types under one name** —
  a bool on each `per_query` row, an int count in `summary` (confirmed in
  real output: `true` vs `2`). Anything reading `scores.json` generically
  trips on it. The summary-side key is renamed
  **`retrieves_after_sufficient_eligible_queries`**; the per-query bool is
  unchanged. Safe to do now because no baseline run has been committed yet.

**No live baseline run has happened yet.** The harness is built and
unit-tested (110 pytest specs, synthetic fixtures throughout —
transcript read/write, scoring, the judge's JSON parsing and error
handling, the comparison tool's corpus-count and query-set refusals, and
a runner→scorer seam test that drives the REAL `HarnessSession` over a
fake transport and then scores the transcript it produced) but nobody
has pointed it at a real OpenRouter key. `eval/agent_queries.yaml` — the
query set itself, 35 queries across the lookup / comparison / analyze /
memo / refusal / historical shapes, all on the BUDGET corpus, with
machine-checked key facts — is committed. **The acceptance step for
whoever has a key next:** run `--subset smoke`, score it, and commit the
result as the first baseline — every later `compare_agent_runs.py` call
needs one to diff against.

---

> ## ⚠ HISTORICAL FROM HERE DOWN
>
> Everything from this point through the end of the
> "Recently fixed — verify in next dogfood pass" section describes the
> **RETIRED pre-consolidation architecture** — the sidecar on `:9200`, the
> Budget MCP server, the Next.js `web/` UI, Voyage reranking, and Postgres.
> None of it is running code anymore; it is kept only as the historical
> record of what Phase 1c shipped. **Current state is the four
> "Standalone consolidation — Plan N shipped" sections above.** In
> particular: the live refusal threshold is **1.9** in
> `harness/constants.py` — the 0.65 mentioned below is the dead Voyage
> 0..1 score scale.

## What's shipped (Phase 1c)

### Retrieval sidecar (`retrieval/api.py`)
- FastAPI service on `127.0.0.1:9200`
- `POST /retrieve` — BM25 + dense + RRF + Voyage rerank. Accepts optional `intent: "lookup" | "compare" | "analyze"` (resolves to default top_k 5 / 12 / 18 when no explicit top_k passed) and echoes intent in the response. Default `top_k` when no intent + no explicit value is 15 (was 20 through 2026-05-19; lowered after dogfood showed spillover at top_k=20).
- `POST /cite/validate` — chunk_id existence + quote-in-chunk-text + span sanity (negative / inverted / oversized). **The content-word-overlap alignment check was DROPPED 2026-05-20** — it was a string-overlap heuristic that produced ~40% false rejections on faithful-but-differently-worded claim_spans. Real faithfulness validation will come from WS3 (NLI verifier, unbuilt).
- `POST /cite/validate_batch` — validates N citations in one round-trip with bulk DB fetch (one `WHERE chunk_id = ANY(%s)` query for all unique chunks). Powers the MCP `cite_batch` tool.
- `POST /list_values` — returns canonical_id slugs with chunk counts + sample doc titles
- `GET /docs/{doc_id}` — document metadata for the PDF viewer
- Sidecar startup loads `.env.local` via python-dotenv; lifespan preflight validates `VOYAGE_API_KEY` + `DATABASE_URL` + chunks-table-non-empty before accepting requests, exiting with a clear stderr message on any failure.
- **55 pytest passing**

### Citation `cite()` / `cite_batch()` behavior
- `cite()` accepts either explicit `span_start`/`span_end` offsets OR a `quote: string` field (server scans chunk.text for the quote and derives the offsets). Quote is the preferred path; offsets are legacy. `claim_span.max` is 2000 chars on the schema; server soft-clamps to 500 with `truncated: true` flag.
- `cite_batch({citations: [...]})` is the multi-citation companion: collapses N serial round-trips into one. The model's tool_use carries an array of single-cite shapes; the response is a parallel array of single-cite results. System prompt steers toward `cite_batch` whenever an answer has more than one citation.
- Both tools return `resolved_span_start` / `resolved_span_end` on success — the sidecar-derived position of the cited text inside chunk.text. The web UI uses these for precise PDF text-layer highlighting.
- The locked schema decision doc (`docs/superpowers/decisions/2026-05-06-citation-tool-schema.md`) has a 2026-05-20 amendment header documenting all of the above.

### MCP server (`mcp-server/`)
- Four tools registered: `retrieve`, `cite`, `cite_batch`, `list_filter_values`
- Per-conversation `.mcp.json` materialization with `alwaysLoad: true` on the budget MCP server (eliminates ToolSearch round-trips for the budget tools). Per-conversation `.claude/settings.json` allow/deny — allow: Bash, Read, the four budget MCP tools; deny: Grep, Write, Edit, MultiEdit, NotebookEdit, Glob, PowerShell, WebFetch, WebSearch, ToolSearch, plus glob denies for unrelated MCP servers (`windows-control`, `gmessages`, `imessages`, `todoist`, `spotify-services`).
- `retrieve()` first-call cap: the FIRST retrieve() of any session is capped to 5 chunks regardless of input top_k/intent. Response carries `first_call_capped: true`. Bypassable with `deep_dive: true` for explicit thorough-coverage requests. Subsequent retrieves are uncapped.
- System prompt (~1300 lines) covers: constrained-agent contract, "tools are preloaded — do NOT call ToolSearch" notice, **progressive retrieval pattern** (first call samples, model expands if needed), **Route-the-question-first classifier** (lookup/compare/analyze → answer FORMAT, not retrieve breadth), **Output hygiene** (banned leak categories: internal vocabulary, corpus mechanics, retry narration), cite() quote recipe, filter dimensions + agency cheat sheet, doc lifecycle (Governor → Baseline → Approps → AFR), 3-year table structure, AFR accuracy hierarchy, retrieval recipes, refusal cases.
- Structured per-call JSONL logging at `~/.claude/ask-the-budget-az/bridge.log` (timestamp, endpoint, duration, outcome, httpStatus, errorCategory, retrievalId). One line per /retrieve and /cite/validate(_batch) call.
- **57 vitest passing**

### Web app (`web/`)
- Next.js multi-turn chat UI on `127.0.0.1:3000`
- Citation rendering:
  - Inline-underlined chips for successful cites; red-X wavy-underline for failed
  - Retry chips collapse via two-pass dedup: (1) chunk_id + substring-chain union-find; (2) FIFO-pair fail→ok across blocks for the same chunk_id (handles claim_span-rewritten retries). Suppresses pairing within a single `cite_batch` (same `batchId`) — sibling claims in a batch are intentional distinct citations, not retries.
  - Tooltip shows verbatim quote (success) or claim-vs-actual-cited side-by-side (failure)
  - MCP zod errors humanized (not raw JSON)
  - Markdown table-row claims inject sentinel inside the last cell
  - Citation `spanStart`/`spanEnd` resolution order: ack's `resolved_span_start/end` (preferred) → explicit input offsets (legacy) → `(0, claim_span.length)` sentinel (only for in-flight or pre-fix calls; produces "couldn't pinpoint" badges in the PDF viewer).
- Tool cards: friendly labels (Search corpus, Cite claim, Cite claims, Browse filters, Shell, …) with per-tool body views (RetrieveView, CiteView, ListFilterValuesView, EditView, ShellView, …). Single status indicator on the header (pixel-glyph color encodes running/complete/failed); pulses while running.
- PDF viewer (`web/components/PdfPage.tsx`):
  - pdfjs-dist canvas render with bbox-restricted text-layer search
  - Multi-pass match strategy: chunk.text\[span_start:span_end\] → full chunk.text → individual currency tokens; bbox-restricted first, then unrestricted
  - "Couldn't pinpoint" badge instead of misleading chunk-bbox fallback when all matches fail
  - "Couldn't open source PDF" error when chunk's source isn't a PDF (DOCX legislative bills currently — DOCX viewer is Phase 2)
- ChatThread auto-scroll: event-driven detection, only follows bottom when the user is at bottom. Messages anchor to the BOTTOM of the viewport.
- UI refresh + JLBC mascot (shipped 2026-05-19, branch `ui-prettify-mascot`):
  - Civic-warm theme tokens; single-mascot architecture with pixel-aligned variant swaps (idle / typing / presenting / refusal); seated typing scene with 12-second behavior loop; welcome hero on empty thread; suggestion chips; speech-bubble assistant messages; page pinned (only chat thread + PDF viewer scroll); footer honesty line.
- Sidecar `/health` probe at session start; renders a `SystemHealthBanner` above the chat thread when the probe fails (e.g. sidecar not running). Returned inline from `startConversation` as `{conversationId, health}` — no event-subscription plumbing.
- **197 vitest passing**

### Eval harness (`eval/`) — Layer 1 retrieval eval

- 34 LLM-synthesized queries (`eval/queries.yaml`) with hybrid ground truth (chunk_id + dimensions + anchor_text)
- `eval/run_eval.py` — calls retrieve() directly, emits JSON + Markdown to `eval/results/<UTC-ISO>-<git-sha>.{json,md}`, computes delta vs previous run
- `eval/refresh_chunk_ids.py` — post-reingest stale-chunk_id fixer (anchor match → cosine fallback)
- `eval/calibrate_refusal.py` — sweep refusal thresholds + recommend
- `eval/synthesize_queries.py` — LLM-driven query generator (Anthropic SDK; subagent-driven path is also documented when no API key)
- **44 pytest passing** across 6 test modules
- **First baseline (committed under `eval/results/`)**: recall@5 86%, recall@20 100%, latency p95 2561ms on the 34-query set. Refusal precision was 0% at the hardcoded 0.30 threshold (Voyage rerank scores sit at 0.56-0.93 — calibration recommends moving the prompt threshold to 0.60 for perfect separation on this eval set).

---

## 2026-05-19 → 2026-05-20 hardening pass

Substantial reliability + UX work landed across this window. Each item ships as a feature branch merged with `--no-ff`; the merge commit is the entry point for the audit trail. All work in worktrees per CLAUDE.md convention, cleaned up after merge.

### Items 1-7 of the original dogfood-hardening plan (merge `1939347`, 2026-05-19/20)

| Item | What | Most-relevant file(s) |
|---|---|---|
| 1 | Per-session `.mcp.json` (alwaysLoad:true) + `.claude/settings.json` allow/deny (eliminates ToolSearch) | `web/lib/youcoded-session-provider.ts`, `web/lib/mcp-config-loader.ts` |
| 2 | `cite()` accepts `quote` (server derives offsets); `claim_span` relaxed 500→2000 with server soft-clamp | `mcp-server/src/tools/cite.ts`, `retrieval/api.py` `http_cite_validate` |
| 3 | `DEFAULT_PIPELINE_TOP_K` lowered 20→15 (measurement-gated by `scripts/measure_retrieve_size.py`) | `retrieval/pipeline.py` |
| 4 | `intent` parameter on `retrieve()` (lookup/compare/analyze → top_k 5/12/25); routes table in system prompt | `mcp-server/src/tools/retrieve.ts`, `retrieval/api.py` |
| 5 | Output-hygiene prompt rewrite — three banned leak categories + dogfood-test plan | `mcp-server/system-prompt.md`, `docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md` |
| 6 | Bridge JSONL logging + session-start `/health` probe + SystemHealthBanner | `mcp-server/src/lib/bridge-log.ts`, `web/components/SystemHealthBanner.tsx` |
| 7 | Sidecar `python-dotenv` auto-loads `.env.local` + startup preflight + README "Daily startup" checklist | `retrieval/api.py` `lifespan`, `README.md` |

Plan doc at `docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md` (historical — captures the pre-execution design + open-question resolutions Q1/Q2/Q3).

### Follow-up fix waves (after Items 1-7 shipped)

Each wave responded to specific issues surfaced during dogfood verification of the previous wave.

**Wave A — Citation-extract patches (commits `5981dbb`, `4620ec3`).** Quote-only cite() calls were being silently dropped at the UI extraction layer because the extractor required numeric offsets. Patched to accept quote-only with a sentinel range; added FIFO-pair-fail→OK dedup for retries that rewrite claim_span entirely.

**Wave B — `cite-batch` branch (merge `3c6bf04`).** Dropped `_check_alignment` from `/cite/validate` (~40%→~5% false-rejection rate; removed the dominant retry-loop latency source). Added the `cite_batch` MCP tool + matching `/cite/validate_batch` sidecar endpoint with bulk DB fetch — collapses N serial cite round-trips into one for analyze-shaped answers. Web `citation-extract.ts` walks the batched input/output arrays; new `batchId` field disambiguates same-batch siblings from cross-block retries in the dedup pass.

**Wave C — `cite-resolved-offsets` branch (merge `2c570e6`).** Threads sidecar-derived `resolved_span_start` / `resolved_span_end` through the cite + cite_batch tool responses to the web UI, fixing the "Citation is on this page — exact text couldn't be pinpointed" badge cluster. Also denies `ToolSearch` in `.claude/settings.json` (alwaysLoad wasn't fully eliminating model-side ToolSearch habit), tightens the route classifier to default-to-Lookup for "Show me X" / "What is X" wording, lowers analyze top_k 25→18 to stay under Claude Code's spillover threshold.

**Wave D — `first-call-cap` branch (merge `af6a673`).** Progressive retrieval: first retrieve() of any session is capped to 5 chunks regardless of intent/top_k. Bypass via `deep_dive: true` for explicit thorough-coverage requests. After the first call, pass-through behavior. Route classifier rewritten to be about answer FORMAT, not retrieve sizing — breadth comes from iterative follow-up retrieves, not one-shot top_k.

**Wave E — `citation-accuracy` branch (merge `400d674`).** Three connected improvements to citation handling. (1) Per-sentence chip placement: `planCitationPlacements` walks every sentence and places a chip wherever the claim_span or the citation's key-fact token (largest currency / percentage) appears, with anti-duplicate guard. `CitationPlacement` gains an optional `column` field; `injectCiteSentinels` splices sentinels mid-line via right-to-left injection. Restated facts across multiple sentences now each get their own chip. (2) Strict-bbox PDF highlight: text-layer search extracted into a new `HighlightStrategy` interface (`web/lib/highlight-strategy.ts`) with `TextLayerSearchStrategy` as the default and a `CoordMapStrategy` placeholder for the #57 follow-up. When a chunk has a bbox, search is strictly bbox-restricted — no whole-page fallback. A miss surfaces "couldn't pinpoint" instead of a silent wrong highlight. (3) Always-visible `CitedTextPanel` below the PDF page renders the chunk's verbatim text with the cited span underlined — verify-by-eye surface for both happy and miss cases. Plus a sidecar-side change: `_validate_one_cite` now rejects quotes that appear multiple times in chunk.text, returning up to 3 positions in the error so the model picks a longer, unique quote on retry. Plan at `docs/superpowers/plans/2026-05-20-citation-accuracy-and-per-sentence-chips.md`. Spec at `docs/superpowers/specs/2026-05-20-citation-accuracy-and-per-sentence-chips-design.md`.

---

## What's open

### Modeling / behavior gaps
- **Model meta-narration leaks** ("Retrying the cites…", "All cites anchored", "Task tracking isn't relevant…") still appear in user-visible answer prose despite Task 12's Output-hygiene rewrite. The prompt-only fix isn't sufficient; needs another pass and possibly a mechanism-level intervention (e.g. stripping retry-narration text in the renderer before display).
- **Model occasionally writes verbose `claim_spans` that don't substring-match the rendered answer** — soft-fixed by the cite_batch + resolved-offsets work but not eliminated; chip attachment still fails when the model rewrites prose between cite() and final emission.

### PDF viewer accuracy (failure mode catalog — updated post-Wave E)
- **A. Source isn't a PDF (DOCX legislative bills).** UI still shows "Couldn't open source PDF" but the new always-visible `CitedTextPanel` below the viewer now shows the chunk's verbatim text with the cited span underlined, so the analyst can verify the cite even without a PDF viewer. #55's broader DOCX viewer is still a separate concern.
- **B. PDF exists, text-layer search fails to find the quote.** "Couldn't pinpoint" badge — same surface, but now the CitedTextPanel underneath shows the cited span in chunk text, so a miss is recoverable rather than dead-end. **Architectural fix still queued (#57):** capture chunk_text→PDF-coord mapping during ingest. Wave E added the `HighlightStrategy` interface so #57 can drop in as a `CoordMapStrategy` without rewriting `PdfPage`.
- **C. PDF exists, chunk's stored bbox is wrong** (MinerU mis-detection). Now produces an honest "couldn't pinpoint" badge instead of a silent wrong highlight, since Wave E removed the unrestricted-search fallback. Ingest QA still out of scope.
- **D. Citation references a chunk_id from a prior turn with no metadata** in the current turn's retrieve. `buildConversationResolvedChunkMap` exists for cross-turn fallback but is sometimes missing chunks. **Diagnosis queued (#56):** verify whether the cross-turn map is consulted, identify where the lookup fails.
- **E. Quote is ambiguous (appears multiple times in chunk.text).** Used to silently bind to the first occurrence → wrong-bbox highlight. Wave E rejects these at validate time so the model must pick a longer, unique quote.

### Not yet implemented (per the Phase 1c plan)
- **Faithfulness verifier (WS3).** Post-generation NLI-style check that strips claims whose cites don't actually back them. Core Invariant 2 says "citations are verified, not just emitted" — current enforcement is chunk_id + quote-in-chunk-text (catches invented chunks/quotes, not semantic faithfulness). The dropped `_check_alignment` was a string-overlap proxy, not real faithfulness. WS3 is the real fix.
- **Audit log writer (WS5).** No persistent record of `(retrieval_id, citation_id, claim_span, intent)` tuples for offline review. Schema-side hooks are in place — `retrieval_id` flows through retrieve() responses, `intent` echoes back, JSONL bridge log captures call-level data — but no DB writer.
- **Layer 2 eval (open-ended analyst queries, LLM-as-judge or rubric scoring).** Layer 1 (chunk-recall regression detector) shipped 2026-05-22 — see "Eval harness" subsection above. Layer 2 is what measures real analyst usefulness: open-ended queries like "spending on homelessness projects?" with multiple acceptable chunks per answer. Deferred until WS3 (faithfulness verifier) ships, since end-to-end scoring depends on it. See [eval/README.md](eval/README.md) for the framing.
- **DOCX viewer (Phase 2).** Bills are DOCX; the Phase 2 plan adds an inline DOCX viewer. Until then, #55 (text-only fallback) is the stopgap.

### Volume ingest — current corpus
**382 documents / 7,755 chunks** as of 2026-05-12. These counts are
pre-Plan-3: the GUI ingest queue adds documents whenever someone uploads,
so the live numbers come from `/health` and `GET /api/jobs`, not this
table. Coverage at the 2026-05-12 snapshot:

| Publisher | FY 2025 | FY 2026 | FY 2027 |
|---|---|---|---|
| JLBC | Approps Report (111 per-agency) | Baseline (110 per-agency + 6 bd-pdf + 7 bh-pdf + 16 detailed-list + 2 topic) | Baseline (110 per-agency + 15 s-pdf + 2 topic) |
| Legislature | — | budget-bill | — |
| Governor | — | — | Executive Budget |
| AGAO | AFR (1) | — | — |

**Known gaps to fill** (none blocking but worth scoping):
- Older FYs entirely — FY24, FY23, FY22 baselines + approps reports + AFRs
- FY 2026 Approps Report (summarizes what actually passed in 2025 session)
- FY 2027 Approps Report / Budget bill (if/when it passes)
- Older Governor's Budgets (FY26, FY25)
- AGAO AFRs for FY24 and FY23

Backfill now goes through [`PROMPT-z13-backfill.md`](PROMPT-z13-backfill.md)
(`PROMPT-volume-ingest.md` is retired — superseded by the Plan 3 GUI queue).

### Open follow-up tasks (tracked in TaskList)
- **#45** — Investigate `(unknown)` tool card after Item 1 ships (verification-only; needs a fresh dogfood transcript)
- **#55** — DOCX chunk fallback (render chunk text inline when no PDF backing)
- **#56** — Diagnose cross-turn metadata gap
- **#57** — Capture chunk→PDF coord map during ingest (architectural PDF-accuracy fix)
- **#58** — Post-mortem: 2026-05-20 dogfood revealed 4 distinct fix categories worth documenting

### Recently fixed — verify in next dogfood pass
- BM25 query parser crashed on apostrophes (#47) — fixed by sanitizing tantivy/Lucene special chars before query string reaches pg_search. 14 of 34 eval queries previously aborted; now 0 crash.
- MCP refusal threshold raised from 0.30 → **0.65** in mcp-server/system-prompt.md (2026-05-22). Old 0.30 was effectively dead — Voyage rerank scores on the current corpus sit at 0.56–0.93, never below 0.56. Calibration recommended 0.70 (refusal recall 0.80, precision 0.67, retrieval pass-rate 0.93); 0.65 picked as a slightly more conservative starting point (refusal recall 0.60, retrieval pass-rate 0.93). Dogfood for real failure modes; re-calibrate after any meaningful corpus or rerank-model change.
- Restated facts across multiple sentences only chipped the first occurrence (per-sentence placement + key-fact-token rule)
- Wrong yellow rectangle when bbox-restricted search missed (strict-bbox, no whole-page fallback)
- Source text only visible inside the PDF (always-visible `CitedTextPanel` below the page)
- Quote-ambiguity silent wrong highlights (sidecar duplicate-quote rejection)
- Citation chips weren't rendering at all (citation-extract required offsets; now accepts quote-only)
- Failed retries weren't collapsing with their successful replacements (FIFO-pair-fail→OK dedup)
- 40% cite() false-rejection rate (dropped alignment heuristic)
- 60s+ tool round-trips on analyze-shaped answers (cite_batch single round-trip)
- "Couldn't pinpoint" PDF badges (resolved-offsets passthrough)
- ToolSearch round-trips at session start (added to deny list)
- "Show me X" classifying as Analyze and pulling 25 chunks (route-classifier defaults to Lookup; analyze lowered 25→18)
- First retrieve always pulling too many chunks regardless of question shape (progressive-retrieval first-call cap)

---

## Repo + portability

### Single git repo
Everything lives in `ask-the-budget-az-dev` →
`github.com/itsdestin/ask-the-budget-az-dev`. No multi-repo workspace,
no submodules.

### What's tracked vs not
- **Tracked:** all source, the MinerU manifests, the JLBC primer, agency/fund catalogs, raw DOCX user uploads (samples/raw-docx/), test fixtures
- **Gitignored:** `node_modules/`, `.venv/`, `db/data/` (Postgres volume), `data/cached-pdfs/`, `data/extractor-output/`, `data/chunks/*` (except MANIFEST.md), `data/insight-data/` (LanceDB corpus + documents.json), `.env.local`, build outputs

### What must travel for a fresh device
1. **The LanceDB corpus** — copy the whole `data/insight-data/` directory
   (the `lancedb/` folder AND `documents.json` — the sidecar is what lets
   the PDF viewer locate sources; without it search still works but PDFs
   won't open, visible as `documents_metadata: 0` on `/health`). Retrieval
   is then live with zero external services — no Docker, no keys.
2. **`data/cached-pdfs/`** — the PDFs themselves (the viewer streams from
   here; re-downloadable from public URLs if lost).
3. **`<data_dir>/settings.json`** — only if AI Mode should work on the new
   machine. It carries the OpenRouter key, the tier→model map, the admin
   username and the spend limits. Without it the app runs fine and AI Mode
   reports `no API key configured`, which is the honest state, not a crash.
   It is plain JSON on the share by design (spec S11) — the protection is a
   hard monthly credit cap set on the OpenRouter dashboard, not file secrecy.

**Nothing else travels.** Post-Plan-3 there is no `.env.local` and no Postgres
volume on any path — ingest, retrieval and AI Mode all run off `data_dir()`
plus one optional key.

See [README.md → Moving to a new device](README.md#moving-to-a-new-device) for the exact commands.

### What's installed externally (NOT in the repo)
- Node 20+ and npm (build-time only — the shipped app serves a static bundle)
- Python 3.12 and `uv` (`pip install uv`)
- **Nothing else.** Docker/Postgres were ingest-only after Plan 1 and unneeded
  after Plan 3. The YouCoded/Claude Code dependency (`ws://localhost:9900`)
  died with Plan 4 — AI Mode is an in-process OpenRouter tool loop. An
  OpenRouter key unlocks AI Mode and nothing else; search, fiscal notes and
  upload all work with zero keys, which is a hard spec constraint ("no paid API
  is load-bearing").

---

## Working conventions

- `setup.sh` — one-shot installer for everything regenerable. Run after `git clone`.
- `bash setup.sh --verify` — runs all suites (pytest + 3× vitest). Use before
  merging non-trivial work. Two of those suites (`mcp-server/`, `web/`) cover
  code Plan 4 retired; Plan 5 deletes the suites and the directories together.
  **Capture its exit code directly** (`bash setup.sh --verify > log 2>&1; echo $?`)
  — piping it into `tail` returns `tail`'s status and hides a failure.
- **One process now.** `uv run uvicorn app.main:create_app --factory --port 9300`
  serves the API and the built `webapp/dist`. `npm` is used to build `webapp/`;
  `mcp-server/` and `web/` are dead weight until Plan 5.
- The launch order is: build `webapp/`, then start the one server. There is no
  Docker step, no sidecar, no MCP registration, and no desktop app to run first.

---

## Doc map

Current architecture first:

- [docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md](docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md) — **the consolidation spec** (S1–S21, Invariants 7–8, gates G1–G3). Read this before non-trivial changes.
- [docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md](docs/superpowers/plans/2026-07-29-standalone-plan-1-storage-retrieval.md) — Plan 1: LanceDB + local models (shipped 2026-07-30)
- [docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md](docs/superpowers/plans/2026-07-29-standalone-plan-2-app-shell.md) — Plan 2: app server + search UI (shipped 2026-07-30; its frozen API-contract block is what later plans build against)
- [docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md](docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md) — Plan 3: GUI ingest queue (shipped 2026-07-31)
- [docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md](docs/superpowers/plans/2026-07-30-standalone-plan-4-ai-mode.md) — Plan 4: AI Mode (shipped 2026-07-31; see its "Task 8 amendments" for the as-shipped HTTP contract)
- [docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md](docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md) — recency-ranking plan (S21; pending)
- [PROMPT-z13-backfill.md](PROMPT-z13-backfill.md) — **the only active handoff** — Z13 backfill + recency calibration runbook
- [README.md](README.md) — how to run it, links
- [STATUS.md](STATUS.md) — this file (current state)
- [CLAUDE.md](CLAUDE.md) — workspace conventions for Claude Code sessions
- [eval/README.md](eval/README.md) — Layer 1 retrieval eval harness: when/how to run, scoring rules, caveats, calibration interpretation

Historical (retired architectures; kept as record, do not build against):

- [docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md](docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md) — original design spec (invariants live on; architecture superseded)
- [docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md](docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md) — twelve interlocking decisions for Phase 1b/1c (superseded by the consolidation spec)
- [docs/superpowers/decisions/2026-05-06-citation-tool-schema.md](docs/superpowers/decisions/2026-05-06-citation-tool-schema.md) — locked `retrieve()` + `cite()` schema (semantics carried into `harness/tools.py`; MCP/sidecar transport gone)
- [docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md](docs/superpowers/plans/2026-05-20-budget-app-dogfood-hardening.md) — dogfood-hardening pass against the retired stack
- [docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md](docs/superpowers/investigations/2026-05-20-prompt-rewrite-dogfood-tests.md) — dogfood-test plan for the output-hygiene rewrite
- [docs/superpowers/plans/](docs/superpowers/plans/) — phase plans (not kept in sync with shipped features)
- [data/chunks/MANIFEST.md](data/chunks/MANIFEST.md) — Phase 1a → Phase 1b hand-off contract (live ingest contract is `ingest/` + `store/schema.py`)
- [docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md](docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md) — eval harness spec (Layer 1; amended 2026-05-22 with what shipped vs diverged)
- [docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md](docs/superpowers/plans/2026-05-20-retrieval-eval-harness.md) — eval harness implementation plan (shipped 2026-05-22, merge `3a26c19`)
- [PROMPT-volume-ingest.md](PROMPT-volume-ingest.md) — retired volume-ingest handoff (superseded by the Plan 3 GUI queue)
