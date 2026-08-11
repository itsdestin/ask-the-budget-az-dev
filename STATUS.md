# Project Status

**Last updated:** 2026-08-03

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
| Volume ingest / S20 backfill | ✓ **Done (2026-08-02)** | Every ingestable JLBC book edition is in the corpus — 38 editions, 7 failures all azjlbc.gov 404s. Corpus 77,574 budget chunks / 7,434 documents. See Plan 7 Task 5 below |
| Phase 2 — Companion + verify-mode | 🔴 Not started | Defers until v1 demonstrates internal value |
| Standalone consolidation — Plan 1 (storage + retrieval) | ✓ Shipped (2026-07-30) | Postgres/pgvector/ParadeDB → embedded LanceDB; Voyage → local ONNX models. See the section below |
| Standalone consolidation — Plan 2 (app server + search UI) | ✓ Shipped (2026-07-30) | New `app/` (port 9300) + `webapp/` SPA: home, budget search (real corpus), fiscal notes directory. See the section below |
| Standalone consolidation — Plan 3 (ingest) | ✓ Shipped (2026-07-31) | GUI upload → background queue → LanceDB; fiscal-note refresh; Add-a-JLBC-book. Postgres/Docker now needed for NOTHING. See the section below |
| Standalone consolidation — Plan 4 (AI Mode) | ✓ Shipped (2026-07-31) | In-process OpenRouter tool loop; MCP and YouCoded dropped. Cited chat + PDF viewer on both corpora, Standard/Deep-Research tiers, per-user spend ledger. See the section below |
| Standalone consolidation — Plan 5 (admin + packaging + deletion) | 🟡 **Tracks 1–4 done, 5–6 open** (2026-08-01) | 20 of 27 tasks. Tracks 1–2 (1–13, Session A): admin identity + gate, settings API, OpenRouter catalog, model fallback, corpus health/restore, Admin + Settings pages, per-machine data dir, health ladder, lockout recovery. Track 3 (14–17, Session B): the Windows bundle. **Track 4 (18–20) shipped 2026-08-01** — `web/`, `mcp-server/`, `db/` and the dead `retrieval/` modules are DELETED (~36,000 lines), one `documents.json` reader, four ingest defects fixed, and all three of Session B's orphaned app-side asks built. **Track 5 (handbook, 21–23) and Track 6 (gates, 24–27) remain.** See the Track 4 section below |
| Standalone consolidation — Plan 6 (document types) | 🔴 **Not started** | 16 tasks. Unblocks ~85 catalogued documents that cannot be ingested at all (agency budget requests, AFR re-route) and makes doc types extensible by a non-technical office |
| Standalone consolidation — Plan 7 (batch extraction) | ✓ Shipped (2026-08-02) | Batch MinerU (~4x), the backfill, recency re-calibration. Three defect fixes not in any plan. See the Plan 7 section below |
| Citation linking (post-hoc linker) | ⬛ **Superseded 2026-08-11** by attested linking | Shipped 2026-08-02, then found to overclaim: 34.2% of linked figures matched >1 document and were resolved by document authority. That ranking is now DELETED. Section kept as the historical record of the defect |
| **Attested citation linking** | ✅ **Shipped and VERIFIED LIVE** (2026-08-11) | The model tags each figure, the system verifies the tag. False-link rate down 13–15×; 100% coverage on a captured live turn, 44 figures linked by tag. Six defects found by browser testing — see the section below. The 31-query Layer 2 baseline still has not been run |
| AI Mode UI redesign | ✓ Shipped (2026-08-02) | One column, floating chrome, tools menu. Six defects found by review that left the suite green |
| Query understanding | ✓ Shipped (2026-08-03) | Agency / doc-type / JLBC-shorthand parsing. recall@5 73.81% → 88.10%, recall@15 and @20 100%. Agency is a PREFERENCE, not a filter — a measured deviation from spec Q2 |
| Budget Documents highlighting + book sections | ✓ **Shipped (2026-08-11)**, one browser check outstanding | Query highlighting marked NOTHING (measured 0 of 200 cards); now 96.5%. 647 documents rendering under raw slugs (`s-pdf`, `bd-pdf`) fold into the books they are sections of. See the section below |
| AI Mode chat history | ✓ Shipped (2026-08-03), **reviewed and hardened 2026-08-11** | Per-device transcripts, browse/search/resume past chats, auto-naming, collapsible rail. Local disk only — never the share. A second review found ELEVEN defects, four of them silent data loss; all fixed. See the section below |
| AI Mode persistent conversation | 🟡 **Code complete, NOT seen in a browser** (2026-08-11) | "+ New chat" shows a row at once; the conversation survives a tab switch and keeps streaming. 741 vitest / `tsc -b` clean. **The four headline behaviours have never been watched working — this machine has no OpenRouter key.** See the section below |

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

- **Attested citation linking — SHIPPED AND VERIFIED LIVE 2026-08-11**
  (section below). The model tags each figure with the passage it came from
  and the system verifies the tag; document-authority ranking is deleted.
  False-link rate down **13–15×**, and a captured live turn reached **100%
  coverage with 44 figures linked by tag** — marker compliance, the design's
  one open risk, is closed. Browser testing found **six defects that all the
  offline measurement missed**; every one is fixed and pinned. Do not read
  the ~55% offline coverage as a regression — it is the UNTAGGED floor,
  measured on transcripts that predate tagging.
  **Still to do:** the 31-query Layer 2 baseline + judge
  ([`PROMPT-attested-citation-baseline.md`](PROMPT-attested-citation-baseline.md)),
  and two non-citation findings — a mislabelled source chunk
  (`jlbc-approps-fy2026-bh26-0003`) and the model narrating tool mechanics.
- **The post-backfill retrieval regression — the free half DONE 2026-08-03**
  (`PROMPT-retrieval-accuracy-regression.md`). The `historical` agent-eval
  queries were RE-AUTHORED against the genuinely old books (see the section
  below) — the one piece of that handoff that needs no OpenRouter key. The
  keyed half still stands: finish the interrupted glm-vs-deepseek head-to-head
  (deepseek run is 25/31 on a keyed machine) and, per the handoff, only then
  make the retrieval change (year-inference-as-default-filter is the highest-
  leverage target, but it must be validated with a Layer 2 run — never Layer 1
  numbers alone). **Nothing on the retrieval path was changed here.**
- **Eval speed + the defend loop SHIPPED 2026-08-03 (no eval numbers changed).**
  `run_agent_eval --workers N`, `judge_agent_run --workers N`, and a new
  one-shot `eval.run_full_layer2` (run → score → judge, one pinned run dir)
  all parallelize the paid OpenRouter calls; `eval.defend_agent_run` replays
  a weakly-scored transcript through a fresh session so the model can defend
  or revise its answer against the evaluator's feedback — useful for spotting
  faulty evals. Thread-based (not process): the paid work is I/O, and the two
  ONNX models are already shared singletons. Defaults stay serial (1 worker).
  No Layer 1 or Layer 2 numbers changed.
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

## Budget Documents — highlighting + book sections — SHIPPED (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-11-budget-docs-highlighting-and-book-sections-design.md`
(H1–H11, B1–B8). Plan:
`docs/superpowers/plans/2026-08-11-budget-docs-highlighting-and-book-sections.md`
(10 tasks). Merged `e6e0e14`. Resolves both issues in
`docs/superpowers/handoffs/2026-08-11-highlighting-and-raw-doc-types.md`.

**Two defects, both found by opening the running app after 2,999 tests passed.**

| | before | after |
|---|---|---|
| cards showing any mark | **0 / 200 (0.0%)** | **193 / 200 (96.5%)** |
| documents under raw machine slugs | 647 | **0** |
| mis-minted doc_ids resolved correctly | — | **21 / 21** |
| family-filter leakage | up to 269 docs | **0** |

Gates on the merged tree: pytest 2392 / 5 skipped, vitest 723, `tsc -b` 0,
eval recall@5 88.10% · @15 100% · @20 100% · refusal 60% · p95 752 ms —
identical to baseline, G1 passes.

### Highlighting: the matcher was the whole story, and the obvious snippet fix was WRONG

`highlight()` searched the snippet for the **entire query as one literal
substring**, so a mark appeared only when every word of the question appeared
consecutively and in order. Measured against the live corpus: **0 of 200
cards produced a single `<mark>`.** Now: every typed word marks on word
boundaries, **no vocabulary list of any kind**.

Four candidate rules were measured over 240 cards and **all four leave the
blank rate at 2.9%** — dropping function words is cosmetic, and a `length >= 4`
rule silently loses `aid` (basic state aid) and `des`. Word boundaries are what
actually matters: substring matching runs 8.3 marks per card peaking at 31.

**🔴 The match-centred preview window was measured and REJECTED.** It scores
higher on terms-visible and reads worse: JLBC front-loads these documents
(heading, then "The Baseline includes $X for Y", then background), so the
median first query-word match sits at **character 5** and the leading text IS
the summary. One observed case shifted ten characters to gain one term and
chopped "Enrollment Changes" into " Changes". It ships as a **fallback** for
the 3.5% of cards whose leading text holds no typed word. **Do not re-tune this
into the default** — the 32%-of-cards figure that argues for it counts marks,
not usefulness.

**Also dead, and instructively:** "only mark terms that are rare across the
results" collapses to 0.4 marks and 70% blank, because it drops `ahcccs`,
`child`, `subsidy` — the words that made the passages rank. Retrieval has
already filtered to passages sharing the topic, so within a result set the most
relevant terms are the most common. **Any "let the data decide which words
matter" scheme fails for this reason**, including deriving matched terms from
BM25.

### Book sections: the parent comes from `source_url`, never the doc_id

`bd`, `bh` and `s` are **JLBC's own printed page-number prefixes** (BD-10,
BH-11, S-1), not document types — every one of the 647 is a chapter of a book
already on the page. `ingest/lance_writer.py` already said so in a comment.

**🔴 The doc_id parses for all 647 and is WRONG for 21** — Baseline sections
minted with an approps doc_id, the `make_doc_id` collision class recorded
elsewhere in this file. `source_url` is the only independent evidence: 647/647
parse, **zero** disagree with the document's own title. Split: Appropriations
Report 389 / Baseline 258. **The 21 doc_ids are read around, not repaired** —
re-minting re-points chunk_ids and eval ground truth.

`detailed-list-pdf` and `topic-pdf` occur under **both** books, so a `doc_type`
filter cannot express "Baseline sections" and would leak up to 269 documents.
`app/search_provider.py` filters exactly, in `app/` — no eval gate, no ranking
change. Measured post-filter yield is **0 of 20 in the worst case**, so a
family filter can legitimately return a short or empty page; the page's
existing "with those filters" copy names the cause.

A book's tray shows **two groups, summary sections above agency pages** — but
only when both exist. Most families (AFR, Executive Budget, Budget Bill) have
no sections at all, and a lone "Agency pages" label restates what the reader
can already see.

### 🔴 The suites were necessary and nowhere near sufficient

**17 defects surfaced during execution. None was caught by any test suite** —
including **five tests that passed whether or not the feature worked**: an
assertion whose `getByText` regex could never match across a `<mark>` boundary
(so it passed on broken truncation), a regression test that passed identically
with and without the guard it existed to pin, and one that would have stayed
green if its feature were deleted outright. Each was caught only by tracing
what the test would do against the **pre-change** code.

The pattern is worth keeping: the plan's **prose reasoning** held up under
measurement, while its **example code** — written out in full and never run —
produced a formula that divides by zero, a `frozenset` membership test that
raises on a list, snapping arithmetic wrong in both directions, a dependency
this repo does not have, and an unsatisfiable assertion.

### ⏸ OUTSTANDING — nobody has looked at the page

Every check above is data and logic. **The rendering is unverified**, and both
original defects shipped green under 2,999 passing tests. Task 10 Steps 4–5 of
the plan carry the specific checks: search `how much did child care subsidy
cost` (marking, expand-in-place, no marks on a nonsense query), then open a
Baseline year card (two tray groups), tick the Baseline type filter and confirm
no Appropriations Report section appears, and confirm `capital outlay` still
finds its sections in the filter box.

---

## ✅ The `historical` agent-eval queries re-authored against the old books (2026-08-03)

The one free piece of `PROMPT-retrieval-accuracy-regression.md`'s §5 done on a
key-less machine. Before the S20 backfill the corpus floor was FY2022, so the
five `historical` Layer 2 queries were authored to the FY 2022/23 JLBC editions
and the file header promised to re-author them once the old books landed. The
backfill (2026-08-02) brought every ingestable book edition back to FY2005, so
they were re-authored — all five REPLACED, not edited — to target genuinely old
material with no modern near-duplicate.

The old five (hs-promise-program-2023, hs-enhanced-fmap-2022,
hs-water-augmentation-2023, hs-building-renewal-2023, hs-esa-cost-2022) were
"not wrong, just no longer the oldest material" and are gone, replaced by:

| query | targets | pinned figure(s) |
|---|---|---|
| `hs-arra-k12-stabilization-2010` *smoke* | FY2010 ARRA State Fiscal Stabilization cut-and-backfill of Basic State Aid | $472,114,000 |
| `hs-leaseback-prisons-2010` | FY2010 state sale/lease-back requirement (incl. prisons) | $735,419,300 |
| `hs-bsf-draw-2008` | FY2008 Budget Stabilization Fund drawdown (Laws 2008 Ch. 53) | $487,000,000 |
| `hs-full-day-kindergarten-2005` | FY2005 Full-Day Kindergarten start-up (Ch. 278) | $21,000,000 |
| `hs-fy2010-oneshot-financing` | FY2010 one-time financing total (with the revised-figure dual basis) | $1,104,000,000 or $1,510,000,000 |

**Authoring discipline followed exactly as the file header prescribes:**

- **Every pinned figure verified present in the corpus** by a full-table
  substring scan against the live 77,574-chunk `budget_chunks`, not assumed.
- **Figure recurrence checked across all FYs** to reject weak fingerprints:
  `$21M`/`$4M` and `1,677` recur in modern editions as unrelated lines, so the
  FDK query names FY2005 + the program specifically rather than relying on the
  round figure alone; `$472,114,000`, `$735,419,300` and `$487.0M` are
  distinctive to FY2009–2012, so the only way to score is the actual old book.
- **The chance to score from a wrong-but-modern near-duplicate is closed by
  construction** — the recession measures have no FY2025-27 analog.
- **REACHABLE, verified offline** (no API key needed): each passed the header's
  spot-check — ONE top-20 retrieve of the verbatim question, every key fact
  present in the concatenated chunk text; the pipeline correctly inferred the
  fiscal year and ranked the old book first.

Guards: `tests/test_eval_agent_queries.py` (shape quotas still `historical
>= 3`, smoke still 11 queries across ≥4 shapes incl. exactly 1 historical) and
`tests/test_eval_agent_schema.py` pass; **2168 pytest / 5 skipped** (the 5
skips are the documented ONNX/model-closure skips). Nothing under
`retrieval/`, `harness/`, `ingest/`, `chunking/` or `citation/` was touched —
this is a query-set change, so no eval was run (per the CLAUDE.md rule).

**Still open, needs a keyed machine (unchanged by this work):** finish the
interrupted glm-vs-deepseek head-to-head (deepseek `.../2026-08-03T0242Z/
9a8fd91` is 25/31 — its six `hs-*` transcripts and `rf-county-budget` are
missing, and those six hs- queries no longer exist under the old ids, so the
re-run should use the new set), then make the retrieval fix.

---

## Attested citation linking — code complete, live baseline OUTSTANDING (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-02-attested-citation-linking-design.md`
(A1–A9). Plan: `docs/superpowers/plans/2026-08-02-attested-citation-linking.md`
(11 tasks, all implemented). **Supersedes the post-hoc linker documented in
the next section**, which stays as the record of the defect that motivated
this.

**The model now attests, and the system verifies.** Each retrieved passage
carries a stable per-conversation alias (`c1`, `c2`, …) on the retrieve
JSON. The model appends `[[c3]]` after every figure it takes from a
passage. At turn end the markers are parsed out of the raw answer — they
reach the annotator and **nothing else**, not the streaming frames, not
`finalAnswer`, not transcripts — and each is treated as a **hypothesis**,
verified against the named chunk only.

**A false link now needs two independent failures**: the model must name
the wrong chunk AND that chunk must coincidentally hold the value inside
the figure's written-precision window. Previously one failure sufficed.

### 🔴 `citation/authority.py` is DELETED, not demoted

Document-authority ranking was the mechanism behind the wrong-doc defect
(34.2% of linked figures matched more than one document; the rule picked
by document type, which cannot see whether a chunk concerns the right
agency, fund or topic). **No code path may now pick a source by rank.**
An untagged figure links only when exactly ONE document in the turn's pool
contains the value; otherwise it is refused with an `ambiguity_count`.
Re-introducing any tie-break here re-introduces the defect.

### The gate: false-link rate, not coverage

`eval/false_link_check.py` is the memo §5.2 method as a committed script —
it links **invented** figures against real retrieve pools, so every link
is false by construction. 1,080 trials per profile across the 27 baseline
pools that retrieved anything:

| profile | before | after |
|---|---|---|
| 4-sig billions (`$12.49B`) | 3.7% | **0.28%** (13× down) |
| 4-sig millions (`$376.2M`) | 2.9% | **0.19%** (15× down) |
| exact grouped (`391,157,700`) | 0.4% | **0.00%** |

Not a seed artefact — `--seed 99` gives 0.19 / 0.19 / 0.00.

**Coverage on the recorded figures fell 92.9% → 54.7%.** **This is the
untagged floor, not the shipped number.** Recorded transcripts carry no
markers, and the diagnostic confirms it: every link is
`unambiguous-fallback`, zero are tag-verified.

**On a LIVE turn with tagging, coverage is 100%** — see the live-session
section below.

The figure count rose 435 → 468 during the live fixes, because accounting
negatives stopped being invisible, so the percentages below that predate
that change are on the smaller denominator. False-link rate never moved.

### 🔴 The specificity floor dominates the loss, not ambiguity

Of the 42.6 lost points: **144 figures (33.1 pts) fall below the
4-written-digit floor**, 53 (12.2 pts) are ambiguous, 19 (4.4 pts) are
genuinely absent. This surprised the measurement. A4 fixed
`_significant_digits` to count **written** digits where it previously
counted magnitude (`$12.49 billion` scored 11, truly 4), so rounded
figures no longer bypass the floor built for them — and a below-floor
figure returns no hits at all, so it never reaches the ambiguity branch.

**Consequence: marker coverage matters more than the design assumed.** A
tagged figure verifies at floor 2, so tagging buys back both the
floor-refusals and the ambiguity-refusals. If the model tags nothing,
coverage is 50.3%.

### ⏸ The fallback floor is deliberately left at 4, pending the live run

Swept offline against the same 27 pools. It is a **monotonic trade with no
plateau**, so neither "largest weight that costs nothing" nor "plateau
centre" picks it:

| floor | coverage | false-link (bil / mil / exact) |
|---|---|---|
| 2 | 63.7% | 0.46% / 0.19% / 0.00% |
| 3 | 60.0% | 0.37% / 0.19% / 0.00% |
| **4 (shipped)** | **50.3%** | **0.28% / 0.19% / 0.00%** |
| 5 | 38.4% | 0.00% / 0.00% / 0.00% |
| 6 | 29.0% | 0.00% / 0.00% / 0.00% |

The right answer depends on how much traffic the fallback actually
carries, which only `marker_coverage_mean` from a live run can say. The
tag path keeps floor 2 regardless — there the tag is independent evidence,
so a round `$1,000,000` may still verify inside the one chunk the model
named.

### Also shipped

- **Written-precision tolerance (A4/A5).** A figure's written form defines
  the interval it certifies: `$10.3M` → [10.25M, 10.35M]; `$10,297,300.17`
  → exactly itself; a grouped integer → ±0.5. One rule replaces the
  matcher's flat ±0.1% and reconcile's flat 1%, and it satisfies the
  format-variance requirement structurally. `13.24 + 3.53 = 16.77` no
  longer "explains" a stated `$16.83B`.
- **Matching is anchored on the figure's ABSOLUTE value** — one target,
  always; the scale ladder varies only the *source's* rendering
  multiplier. The old code anchored on the value as written, turning an
  unknown-scale figure into four targets and multiplying collisions.
- **Near-miss (A6).** A failed link reports the nearest source value and
  its relative distance — "you said $12.49B; c3's nearest value is
  12,515.4" is the actionable sentence. 152 of the 216 unverified carry
  one. **An ambiguous figure deliberately carries none**: the value is in
  the pool exactly, so `nearest_value` returns distance 0.0 and the chip
  would read "appears in 2 different documents" beside "differs by 0.0%".
  Ambiguity and not-found are different failures.
- **`marker_coverage_mean` and `tag_accuracy_mean`** on Layer 2 scoring —
  the early-warning metrics for the design's one open risk.

### Deviation from spec A1: aliases are per-CONVERSATION monotonic

The spec said per-turn. A per-turn reset would reuse `c3` for a different
chunk while the old `c3`-labelled chunk is still in the model's history, so
a model tagging from memory would verify against the WRONG chunk — the
exact failure this design exists to remove. Monotonic aliases cannot
collide; a previous-turn alias resolves to a chunk absent from the current
pool and degrades to the fallback. Strictly stronger, same observable
behaviour.

### ✅ VERIFIED LIVE, and six defects it found (2026-08-11)

**A live browser session on a keyed machine closed the design's one open
risk: the model tags reliably.** A captured turn emitted 19 markers, all
19 parsed; a second, 70 markers across 60 figures. **Marker compliance was
never the problem — the system discarding good markers was.**

Final state on a captured live transcript (60 figures, 51 chunks):
**100% coverage, 44 figures linked by TAG, zero unverified.**

| # | defect | why it mattered |
|---|---|---|
| 1 | Linking pool scoped to the TURN | A follow-up answered from context had nothing to verify against — a 9-row table came back all red. The pool is now the conversation, read off the tool messages still in history; the **untagged** fallback stays turn-scoped, because widening it to 8 turns took false-links 0.28% → 2.50% |
| 2 | Source values under $1,000 invisible | The answer side accepted `$974.6`; the source side required a comma group. A table "in millions" writes every agency under $1B without one, so most rows of a General Fund table were unmatchable. Coverage 50.3% → 55.2%, false-link unchanged |
| 3 | The tag-binding distance rule | Discarded `$12.49B (Mar 2020) [[c18]]` and `$1,574.1 million in FY 2026 [[c22]]` — a model tags the end of the NOUN PHRASE. Widened once, then **deleted**: a distance heuristic could only lose citations, never prevent a false one, because VERIFICATION is the guard |
| 4 | Accounting negatives yielded no figure | `$(0.07)B` — a whole variance column was unseen, so neither citable nor derivable. Needed three parts: extractor, source scanner, and `reconcile` comparing difference MAGNITUDES |
| 5 | Chip rendered inside the amount | `$13.98[1]B`. The scale word is part of the figure's span now |
| 6 | Unverified figures were numbered | A table read 13,14,…,20 struck through around a live 21. Only citations are numbered; unverified figures draw no chip and **no count is shown — an uncited number is already visibly uncited** (Destin's call) |

**Two findings that are NOT citation defects:**

- **`jlbc-approps-fy2026-bh26-0003` is mislabelled at the source.** It
  carries the heading of the chart above it (*"FY 2026 General Fund
  Appropriations — Where It Goes"*) while its numbers are total spending
  (AHCCCS $23,010.1M), and its labels are fused
  (`AHCCCSK-12 Education (ADE)`). A correct citation there points at a
  chart whose header contradicts its own figures. **Ingest defect.**
- **The model narrates tool mechanics** ("tagged to c22", "no cite() call
  was made") when asked how it cited something. Output hygiene bans
  exposing corpus mechanics; the prompt needs a pass.

**Process note worth keeping:** several rounds of testing measured a stale
build. `uvicorn` runs without `--reload`, so **Python changes need a server
restart** — only the SPA picks up a rebuild.

### 🟡 STILL OUTSTANDING — the full Layer 2 baseline

The live session verified behaviour on captured single turns. What has NOT
run is the **31-query Layer 2 baseline with the judge**, which is what
produces `marker_coverage_mean` / `tag_accuracy_mean` across the whole
query set and a `compare_agent_runs.py` delta against
`eval/results/agent/2026-08-02T0900Z-0b08221`. Runbook:
**[`PROMPT-attested-citation-baseline.md`](PROMPT-attested-citation-baseline.md)**
— live browser reproduction, Layer 2 smoke then full, and a decision table
gating on `marker_coverage_mean ≥ 0.80` and `tag_accuracy_mean ≥ 0.90`.

A low `tag_accuracy_mean` is the serious outcome: it would mean
attestation is not trustworthy evidence and the floor-2 concession on the
tag path needs re-thinking. That is a reason to stop, not to tune.

**Also unverified in a real browser:** the near-miss and ambiguity tooltip
copy, and chip click opening the PDF at the source rendering.

---

## Citation linking (post-hoc linker) — SUPERSEDED 2026-08-11

> ### ⬛ HISTORICAL — this design was REPLACED by attested linking
>
> Kept as the record of the defect that motivated the replacement. The
> `citation/authority.py` ranking described below is **deleted**; the
> 92.9% coverage figure measured how often a link was PRODUCED, never
> whether it was RIGHT, and that was the wrong gate. See the section
> above for what replaced it.
>
> **Three browser sessions on 2026-08-02 found eight defects; five were
> fixed, and two were fundamental and NOT fixed.** Those two are what
> attested linking exists to solve.
>
> **Full write-up:
> [`docs/superpowers/investigations/2026-08-02-citation-linking-review.md`](docs/superpowers/investigations/2026-08-02-citation-linking-review.md)**
> — old design, why it was replaced, what replaced it, every defect, and
> how to reproduce each measurement offline for free.
>
> The two unfixed problems:
>
> 1. **34.2% of linked figures match a value in more than one document**,
>    and the primary source is picked by document authority — a rule that
>    cannot see whether the chunk concerns the right agency, fund or
>    topic. Observed live: `$16.28 billion` linked to an irrelevant source.
> 2. **A rounded figure is a weak fingerprint.** An *invented* figure
>    falsely links **3.7%** of the time at the profile of `$12.49B`
>    (2.9% for millions) against **0.4%** for an exactly-written
>    `1,391,157,700`. The code treats both identically.
>
> Also unfixed: `reconcile`'s flat 1% tolerance asserts "computed from"
> on figures that are not computed (`13.24 + 3.53 = 16.77` was accepted
> as `$16.83`), and `_significant_digits` measures magnitude rather than
> distinctiveness, so the specificity floor is bypassed for exactly the
> rounded figures that need it.
>
> **The 92.9% coverage figure below measures how often a link is
> PRODUCED, never whether it is RIGHT.** That was the wrong gate, and it
> is why ~2,000 passing tests missed all of this. Any future work here
> should be accepted on the **false-link rate**, not coverage. Building
> that measurement took ten minutes against transcripts already on disk.


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

### Three defects found in the FIRST browser session (2026-08-02)

All three shipped green: 1986 pytest, 451 vitest, `tsc -b` clean, and a
92.9% offline measurement. **Every one of them was invisible to all of
that**, and each is a distinct lesson about what those numbers cover.

1. **🔴 The refusal banner fired on every fully-linked numeric answer.**
   `detectRefusal` recognised only a `cite()` ack as verification. Task 7
   told the model to stop citing figures, so a linked answer has ZERO
   acks — the banner announced "This answer carries no verified citation"
   over an answer where every number was linked, and its five raw-passage
   previews filled the viewport and pushed the answer off screen. Fixed:
   a linked figure counts as verification, and is the stronger kind (an
   ack validates a quote the MODEL retyped; a linked figure is a value the
   SYSTEM located). `derived` and `unverified` deliberately do not count.
   **Lesson: the change removed a signal another component was reading,
   and nothing tested the consumer.**

2. **🔴 Clicking a figure chip could never open the PDF.** `PdfViewer`
   gates on `citation.resolved.docId` + `pageStart`; the annotation
   carried only `chunk_id`, so every chip landed on "Couldn't open source
   PDF". The design's entire payoff was dead on arrival. Fixed: the
   annotation now carries `doc_id`, `doc_type`, `doc_title`, `publisher`,
   `fiscal_year`, `page_start`, `page_end`, `bbox` per source, making it
   self-describing for the judge and any later audit too. Chunk TEXT is
   deliberately still absent — it would ship a chunk body per figure, and
   the highlighter searches `source_text` first.
   **Lesson: every test asserted the annotation was PRODUCED; none
   asserted it was USABLE by its consumer.**

3. **🔴 A real figure was silently dropped: "took in $27,362,036.72".**
   The year guard treated a preceding "in" as a year cue. Worse, the
   guard had **no true positives available to it** — `_FIGURE_RE` needs
   comma-grouping or a currency marker with a decimal, so a bare `2026`
   can never match it in the first place. It could only ever cost real
   money. Deleted, and pinned by
   `test_no_year_can_reach_the_extractor_in_the_first_place`.
   **Lesson, and the sharpest one: re-running the 31-transcript
   measurement after the fix gives byte-identical numbers — 435 figures,
   92.9% coverage, before and after.** The recorded corpus simply never
   contained that sentence shape. A clean offline measurement over a
   fixed transcript set says nothing about the shapes it happens not to
   contain, and the FIRST live answer found one.

Suites after all three: **1997 pytest, 459 vitest, `tsc -b` exit 0.**

### 🔴 OUTSTANDING — needs a machine with an OpenRouter key

Plan Task 12 Steps 3–4 could not run here: `ai_available` reports **"no
API key configured"** on this machine, and both steps spend real money.
**Runbook: [`PROMPT-citation-linking-baseline.md`](PROMPT-citation-linking-baseline.md)**
— it carries the exact commands, the expected metric directions, and the
browser checks.

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

## Query understanding — SHIPPED (2026-08-03)

Spec: `docs/superpowers/specs/2026-08-02-query-understanding-design.md` (Q1–Q6).
Plan: `docs/superpowers/plans/2026-08-02-query-understanding.md`. Branch
`query-understanding`.

**An analyst typing the shorthand they actually use now gets that agency's
documents, of that type.** `RetrievalRequest` already carried
`agency_canonical_id` and `doc_type` filters that reached LanceDB; nothing
populated them from query text. Three parsers now do, mirroring `query_year.py`.

**Measured against a CONTROL run of unmodified master on the same machine
under the same load** — not the morning's recorded baseline, because the box
was at load 11 and the apparent latency regression was entirely contention:

| | control (master) | shipped |
|---|---|---|
| recall@5 | 73.81% | **88.10%** |
| recall@15 | 97.62% | **100.00%** |
| recall@20 | 97.62% | **100.00%** |
| refusal precision | 60% | 60% |

**+14.3 points of recall@5, and perfect recall at 15 and 20. Gate G1 passes.**
Suite 1986 → **2155**.

On the six shorthand queries that motivated the work
(`eval/navigational_check.py`, precision@5): mean agency precision 0.767 →
0.833, mean doc-type precision **0.200 → 0.833**.

### 🔴 AGENCY IS A PREFERENCE, NOT A FILTER — a measured deviation from spec Q2

The spec says an exact agency match becomes a hard filter. **It was measured
and it loses.** Same eval set, agency-filter ON vs OFF, nothing else changed:

| | recall@5 | recall@15 | recall@20 | failed lookups |
|---|---|---|---|---|
| hard filter (spec Q2) | 83.33% | 95.24% | 95.24% | q-009, q-022 |
| **preference only** | **88.10%** | **100%** | **100%** | none |

**Why the filter loses, and it is not a tuning accident: the corpus is stamped
incompletely, so a CORRECT reading of the question can still exclude the
answer.** q-009 names "the DOR Unclaimed Property Fund" and the AFR passage
answering it carries only `agency:sba`; q-022 names the Secretary of State and
its answer sits in a House document. In both the parser is right and the filter
deletes the answer anyway — **silently**, because the agency has other chunks so
the Q3 empty-result fallback never fires.

Cost: one slot on one navigational query of six (`dema ar`).

**Doc type still hard-filters** — it has no equivalent stamping gap, and it is
what took doc-type precision from 0.200 to 0.833.

**Re-open this only with a measurement, and re-run it after any re-ingest that
improves agency stamping** — the trade could genuinely reverse once the corpus
side has the aliases the query side now has.

### 🔴 The corpus has the SAME missing-alias problem, on the ingest side

This is the finding behind the deviation above and it outlives it.
`chunking/entity_stamper.py` cannot resolve "DOR" in document text any better
than the query parser could before this work: **103 of the 157 agencies carry
no alias at all**. The query side now has them. **The ingest side does not, and
fixing it needs a re-ingest.**

### Calibration

**`MATCH_PENALTY = 2.0`** (`retrieval/agency_boost.py`), penalty-shaped like the
recency boost so `top_score` can only fall. Re-swept after agency became a
preference, which routes the whole agency signal through it: recall@5 plateaus
at .8810 from 1.0 through 3.0, falling to .8333 at 0.0 and .8571 at 4.0. **2.0
is the plateau CENTRE** — the right pick when the metric degrades in both
directions, unlike the recency weight where lower was always safe.

**`REFUSAL_THRESHOLD` stays 1.46.** `calibrate_refusal.py` recommends −0.77;
rejected, with the reasoning at the constant. The penalty does not disturb the
distribution (`max_top_score` 8.6779 at every weight 0.0–4.0, because a penalty
only lowers non-matching chunks), and −0.77 trades refusal RECALL 0.60 → 0.40
for precision — it refuses LESS, which is backwards under Invariant 3.

### 🔴 The stoplist was load-bearing, and the review gate would NOT have caught it

Every JLBC slug becomes an alias unconditionally, and **13 of the 145 slugs are
ordinary English words**. **`for` is a preposition appearing as a standalone
token in 14 of the 47 eval queries** — unguarded it hard-filtered all of them
onto the Department of Forestry.

These arrive through SLUGS, not drafted aliases, so **Task 8's human review gate
could not have caught them.** Two independent derivations agreed: a frequency
count over 247,607 tokens of real budget English (`gov` 5944 · `per` 3993 ·
`tax` 541 · `for` 474, then a ~190 noise floor) and an ordinary-word scan.

Three escalation levels now exist, and the distinction is load-bearing:

| mechanism | effect | examples |
|---|---|---|
| `AMBIGUOUS_ALIASES` | demote to a boost | `doc`, `colleges`, `art`, `bar` |
| `SUPPRESSED_ALIASES` | never resolve at all | `tax`, `for`, `ban` |
| `AMBIGUOUS_PHRASES` | demote a NAME head | `insurance` |
| `AMBIGUOUS_AGENCIES` | demote an agency, every tier | `agency:gov` |

**A demotion is not always enough** — even a boost pulls the wrong agency up the
page, which is what "2024 income tax rate" did to the Board of Tax Appeals.
And `AMBIGUOUS_PHRASES` exists because the same defect occurs one tier up where
a suppressed slug cannot reach it: "Insurance, Department of" has the
single-word head "Insurance", so "health insurance premiums for state
employees" hard-filtered onto the insurance regulator.

### Four silent wrong-answer paths, all found before the eval was run

All share a shape worth naming: **a bad guess that SUCCEEDS**, so the Q3
fallback never fires and the analyst is never told a filter was inferred. A
guess returning nothing is self-correcting; a guess returning the wrong thing
is not.

- **`chapter 21 baseline`** read as a FY2021 hard filter — the JLBC shorthand
  bypassed the designator guard the four-digit rule already used.
- **`general appropriation act` → `budget-bill`.** It is the NAME OF A LAW. The
  phrase appears in **6,253 corpus chunks, ZERO of them budget-bill**, while the
  whole type is a single 136-chunk document. Cost n-003 and n-007 their ground
  truth.
- **`for` → Forestry**, above.
- **`insurance` → the regulator**, above.

Found by `tests/test_query_understanding_eval_safety.py`, which checks the
parsers against the eval set's own ground truth. **That guard is also what
forced the agency-filter deviation**: it fired on q-009, then on q-022 the
moment `for` was suppressed, and two exemptions was the signal to measure the
policy rather than keep exempting.

### Duplicate catalog entries cost a filter AND split the corpus

Found by Destin reviewing the checklist. Five agencies are recorded twice
(ASU, Child Safety ×5, Revenue, WIFA, Constable Ethics, Equal Opportunity).
A duplicated name is not cosmetic: entries resolving to two ids were treated as
ambiguous, and the duplicate ids **split the stamped chunks**.

Fixed query-side, no re-ingest: entries whose canonical name matches as a
sorted token multiset are ONE logical agency, and a match resolves to every id
in the group. Token multiset rather than string equality because the catalog
writes the same agency both ways round — "Child Safety, Department of" and
"Department of Child Safety" are five entries for one agency.

| query | chunks reachable | years now returned |
|---|---|---|
| `asu` | 1,263 → **1,343** | 2019–2025 |
| `child safety` | 505 → **2,033** | 2018–2027 |
| `water infrastructure finance authority` | 169 → **295** | 2022–2027 |

**ASU is one university split by a naming change, not two agencies** — printed
"ASU – Tempe/DPC" FY2015–2018 then plain "Arizona State University"
FY2019–2020, while `agency:uniasu` runs FY2021–2027. Contiguous, never
overlapping.

**UA is the opposite case and needed its own mechanism.** No entry is named
plainly "University of Arizona"; Main Campus (959 chunks) and Health Sciences
Center (564) run in PARALLEL every year, so neither supersedes the other.
`CURATED_ALIAS_AGENCIES` holds aliases that deliberately name a SET of entries
— also used for `financial institutions` → {ban, dif}, since a MERGER cannot be
detected the way a rename can.

### ⏸ Aliases — eight applied, the rest deferred

Approved by Destin by name: **`adoa` `difi` `dohs` `dhs` `asu` `nau` `aph`
`dffm`**, plus `doc` and `dema` from the spec's own evidence. A test pins this
as the whole set — anything beyond an agency's own slug fails the suite.

**The 158 machine-drafted proposals in
`docs/superpowers/investigations/2026-08-02-agency-alias-review.md` are NOT
applied** and the review is deferred. That document is on master and is now
**stale in six places** (ASU, Administration, DIFI, Homeland Security, NAU,
Pioneers' Home) — regenerate it if the review resumes.

**Worth knowing before spending 35–50 minutes on it:** the generator builds
acronyms from initials only, so it proposed `nu` for Northern Arizona
University and `ph` for Pioneers' Home. Destin supplied `nau` and `aph` from
memory. On both cases he cared about, human knowledge beat the drafted list —
the document's real value may be its appendix, which surfaced the 13
ordinary-word slugs nobody knew were live.

### Catalog debris removed

Five PDF-extraction fragments that would fuzzy-match noise: `'pp y, Economic
Security…'` (`agency:des`), a bare `'Board of'` (`agency:ost`, from a page
break — it would have hard-filtered "board of regents" onto Osteopathic
Examiners), `'p University of Arizona…'` (`agency:uniuhsc`), a leading-comma
Forestry variant, and **`'ministration, Arizona Department of…'`**
(`agency:doa-apf`) — a truncated "Administration" that registered as a
single-word phrase and HARD-FILTERED. Guarded as a class, not as five
instances.

### Follow-ups this created

- **Edition diversity in the candidate pool.** Chronological ordering is
  UNCHANGED at 0.750 and **raising the recency weight does not help** —
  measured at 0.85, 2.0 and 4.0, `ahcccs appropriations report` never surfaces
  FY2026, which exists. The newest edition is not in the RRF pool to be
  reordered: ~2,000 near-identical AHCCCS chunks span FY2005–2026 and the pool
  is capped at 20. **Do not re-tune `RECENCY_BOOST_PER_YEAR` for this.**
- **Agency stamping on the ingest side** (above) — the largest remaining win,
  and it would let the agency-filter decision be re-measured.
- **Fund resolution** has the identical gap and fix shape; deferred to keep
  this change reviewable.
- **The UI does not yet show what was inferred.** `RetrievalResult` carries
  `inferred_agencies`, `inferred_doc_types` and `dropped_filters` so it can —
  and they must be described DIFFERENTLY, since doc type filters and agency
  only prefers. The AI Mode UI redesign shipped alongside this (see the
  section below), so there is now a settled surface to add it to.
- **`AMBIGUOUS_PHRASES` candidates not acted on:** `administration`, `housing`,
  `nursing`, `senate`. Judgement calls, not clear defects.
- **The shared normalizer keeps hyphens**, so a hyphenated catalog name only
  matches tier 1 if the analyst types the dash. It belongs to
  `entity_stamper.py` and both sides must agree, so changing it is its own
  change with its own re-ingest question.

---

## AI Mode UI redesign — shipped (2026-08-02)

Spec: `docs/superpowers/specs/2026-08-01-ai-mode-ui-redesign-design.md`.
Plan: `docs/superpowers/plans/2026-08-01-ai-mode-ui-redesign.md`.
Merge `2cef0f9`. **Webapp-only** — nothing under `retrieval/`, `ingest/`,
`chunking/` or `harness/` is touched, so the CLAUDE.md eval rule does not
apply and no eval was run.

**571 vitest across 54 files** (was 432) + pytest 2012, tsc and build clean.

Started from four complaints: "the tool cards are ugly and disproportionate
to chat, there are weird extra scroll bars all over, the citation viewer
renders strangely, and there is a lot of wasted space." All four traced to
root causes and fixed — but the live browser pass changed more than the
plan did, and that part is below.

### As shipped

- **One scroll container** in the chat column. The composer floats over it
  and publishes its measured height, so messages scroll behind it.
- **Tool rows**, not cards: ~30px, capped below the prose measure,
  consecutive calls coalesced into one row, status carried by glyph shape
  so only failure spends a colour.
- **One `--ai-col` measure** governs thread, banners and composer.
- **The ask bar.** Single-line-then-wrapping composer wearing Home's
  hero-search recipe verbatim (pill, canvas fill, navy focus ring), so the
  app has ONE search-input identity instead of three. Paperclip stub +
  tools menu + Send. Grows to four lines, then scrolls with no scrollbar
  and a per-edge fade.
- **Corpus and mode are two toggles** behind the tools icon, each carrying
  the copy describing its own consequence. The tier sentences still come
  off the wire (S16). A pip on the closed icon reports any non-default
  setting, and the placeholder names the live corpus — those are the only
  permanent statements of either, now that both live behind a menu.
- **The navy hero strip is gone**; the thread has a navy-wash ground the
  composer fades INTO rather than sitting on.
- **The footer's "AI Mode available" line is gone.** A working system does
  not need to announce it. The failing case got the whole page instead,
  with the server's reason demoted and addressed to the administrator, and
  probing kept as a separate screen.
- **Header:** the row is the two corpora with AI Mode between them, plus
  one menu holding Upload, Settings and Admin. Home left (the logo goes
  there). The AI icon's spark orbits the glyph on select, and the label
  rolls out to its own measured width.

### 🔴 Five defects found by REVIEW, not by tests

Recorded because the same classes will recur, and every one of them left
the suite green:

1. **`container-type: inline-size` on the thread scroller silently
   re-clipped the citation tooltip** — including `.chat-cite-fail`, the
   panel saying WHY a citation failed (Invariant 2). Layout containment
   makes an element a containing block for `position: fixed`. Both
   existing contract specs stayed green because each was individually true
   and jointly wrong. The guard now covers `contain`, `container`,
   `container-type` and `content-visibility`, and a later spec forbids
   `mask-image` on the scroller for the same reason.
2. **A hover rule painted the azure SUCCESS tint behind FAILED citations.**
3. **A cross-branch defect neither side could see.** Master's `FigureChip`
   renders `.chat-cite-tooltip`, which this branch had made
   `position: fixed` with JS-supplied coordinates. FigureChip passed none,
   so its tooltips detached from their chips on the first scroll. The two
   changes never touched the same lines; git merged them without a murmur
   and both suites stayed green.
4. **The bottom chrome painted over the thread's own scrollbar** — it sat
   at `right:0`, so the bar looked half-drawn.
5. **The tools menu was unreachable by pointer.** Trigger and popover are
   both absolutely positioned, so the gap between them belonged to
   neither; crossing it left the subtree and fired `mouseleave`.

### 🔴 And one this work CAUSED

Removing the retired `.chat-input` block **by range** took `.chat-welcome*`
with it — the empty state lost its centring and the mascot drifted. Nothing
failed, because no spec covered that block. There are two now, verified by
re-running the exact accident. **The lesson generalises: this stylesheet
has several rules whose ABSENCE is silent, because a flex container that
stops existing just leaves its children looking approximately fine.**

### Still unverified

- **The AI-mode animations have not been confirmed on a machine with
  `prefers-reduced-motion` OFF.** The app honours it everywhere; with it on,
  the spark throw and the stop-button spinner are disabled by design and
  snap between states. Worth knowing before anyone reports them as broken.
- The bundle has not been rebuilt against this webapp.

---

## AI Mode chat history — shipped, then reviewed and tightened (2026-08-03)

Spec: `docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md`
(H1–H6 + A1, with implementation amendments). Implementation handoff:
`docs/active/handoffs/2026-08-02-chat-history-implementation.md`. Follow-up
session handoff: `docs/active/handoffs/2026-08-03-ai-mode-chat-history-followups.md`
(its "uncommitted fixes" were all committed in the branch; the three issues
it lists are resolved by commits `9d73754`/`9645e9c` (Issue 1), `6f35f7e`
(Issue 2) and `62197cc` (Issue 3 audit)). Merged via the `chat-history` PR.

Analysts can browse, search and resume their own past AI Mode conversations.
Transcripts are per-device files at `%LOCALAPPDATA%\JLBC-Insight\conversations\`
— **never the share** (Invariant 7, pinned by the AST import-allowlist test):
one analyst's questions are not ~20 colleagues' reading material.

### As shipped (decisions H1–H6)

- **H1 — files, not a database.** One JSON per conversation; the directory IS
  the index. Atomic tmp+`os.replace` writes (per-call uuid suffix, not
  per-process, so two writers on the same id can't share a tmp name). Read
  paths degrade on a corrupt file; the write path raises.
- **H2 — browsing is free.** Opening a stored chat renders it live with no
  server session and no API spend; the session is rebuilt from the stored
  transcript on the FIRST send (`resume_from` on `POST /api/conversations` —
  no parallel resume endpoint). The stored corpus wins over whatever the
  client requested, and the picker now follows it (review fix below).
- **H3 — auto-naming is one cheap LLM call after the first exchange**, ledgered
  under its own `"title"` tier, falling back to the truncated question on
  EVERY failure (no key, AI Mode off, over-limit, provider error). Manual
  renames are never overwritten by auto-naming.
- **H4 — search** scans titles and prose only; `tool` messages are excluded
  by ROLE (their content is a JSON payload of retrieved chunks, so an
  isinstance check would not exclude them).
- **H5 — a stale citation is marked, never silently dropped.** Click-time
  chunk fetch distinguishes 404 ("gone") from 200-with-quote-missing
  ("moved"); a 503 publishes nothing ("we cannot tell" beats a false "your
  source is dead"). The verified quote still renders.
- **H6 — keep everything.** No cap, no expiry, explicit delete only.
- **A1 — collapsible history rail** amends the UI redesign's D1; auto-
  collapses when the source panel opens; collapsed state persists.

### The 2026-08-03 review found real bugs; this is what was fixed

A commit-by-commit review of the branch (all 20 commits unique to
`chat-history`) found the code careful overall but with genuine logic gaps.
Fixed in the branch before the PR:

- **Resuming a chat wiped its transcript on first send.** The resume id never
  reached `conversationIdRef`, so the first send dispatched
  `CONVERSATION_STARTED`, whose reducer resets the timeline — emptying the
  rehydrated turns the analyst was looking at. Fix: the rehydrate effect
  seeds the ref and the `REHYDRATED` id; `send` detects the resume case and
  dispatches with a new `keepTurns` flag. Regression-tested.
- **The annotation persistence fix (Handoff Issue 1) had a hole on the
  interrupt path.** `_attach_annotation` sits after the interrupt breaks, so a
  STOPPED turn persisted without its figure annotation — and the amended test
  asserted a shape that path never produced. **STILL OPEN** (below).
- **Corpus mismatch on select.** The rail lists both corpora but selecting a
  chat never moved the picker, so the thread could answer out of one corpus
  while the UI showed the other. Selecting now reads the stored transcript's
  corpus and sets both in one remount.
- **Sticky stale marks.** A chip branded "source no longer available" (e.g.
  a transient 404 mid-ingest) never cleared. The viewer now publishes a
  `resolved` verdict on a clean re-check; the chip clears itself.
- **The mid-turn delete/rename race.** `persist_turn` runs AFTER `end_turn`
  in a background thread, so the rail could delete or rename a chat while its
  turn streamed. Two fixes: a turn-end write skips when the file is gone and
  this is NOT the first turn (a deleted chat stays deleted — the first-turn
  discriminator is the USER-message count, since a tool-calling first turn has
  two assistant messages), and `harness/history.py` gained a per-id write lock
  (`threading.RLock`) wrapping save/delete/rename so the turn-end write and a
  rail rename can't interleave. The lock-probe test is verified to FAIL when
  the lock is stripped.
- Smaller: the `useHistory` empty-query guard now gates on real search state,
  not a seq counter the mount fetch also bumps; the transcript tmp name is
  unique per call (`uuid` and `threading` added to the Invariant-7 allowlist
  — both stdlib, neither can reach the share).

### ✅ The 2026-08-11 second review — eleven defects, all fixed

A second review of the merged branch (this session plus a parallel
`/code-review high` over `7b4059d..47cc551`) found eleven defects. **Four
were reproduced by execution before any fix was written, and every guard
below was verified FAILING against the unfixed code** — three of them only
after the test itself was rebuilt, because the first versions passed against
master and proved nothing. Suites **2343 → 2368 pytest** (5 skips unchanged)
and **678 → 693 vitest**, `tsc -b` and `npm run build` clean.

**No eval was run, and the CLAUDE.md rule does not ask for one**: nothing
under `retrieval/`, `ingest/`, `chunking/`, `citation/` or
`harness/system-prompt.md` was touched. The changes are `harness/session.py`,
`harness/history.py`, `app/routes/conversations.py` and the webapp.

#### 🔴 The four that silently destroyed data

1. **A silent turn wiped the PREVIOUS answer's citation chips.**
   `_attach_annotation` searched backwards through the whole history, and
   `_Accumulator.annotation()` returns `{"figures": []}` — a **truthy** dict —
   so `if not annotation` never fired. A turn that appended no assistant
   message (the model returned neither text nor tool calls; a stop landed
   before step 1) walked into the previous turn and overwrote a correctly
   linked answer's annotation with an empty one. Reproduced: turn 1's figure
   count fell 1 → 0. **Fixed by bounding the SEARCH** (`since=turn_start`,
   captured right after the user message), not by filtering the payload —
   filtering would have broken the deliberate pin in
   `test_interrupt_on_a_text_only_turn_is_a_plain_interrupt`.
2. **The auto-title path erased a later turn.** `persist_turn` loaded the
   transcript, made a blocking HTTP call of up to 20 s, then saved the *stale*
   object. Reproduced: 4 messages → 2. It also **resurrected a chat deleted**
   during that window and **reverted a rename** made during it, clearing
   `title_is_manual` so auto-naming re-armed against a title the analyst
   chose.
3. **Stop lost the answer as well as the annotation.** `use-chat`'s `stop()`
   aborts the fetch first, so GeneratorExit reaches `stream_turn` and the
   end-of-turn code never runs. Reproduced: history after a stop was
   `[user, assistant(tool_calls), tool]` — the partial answer the analyst was
   watching stream in was never recorded. New `_abandon_turn()` records it and
   attaches the annotation before `_repair_history()` runs.
4. **Deleting the open chat's row made it permanently uncontinuable.**
   `create_conversation` raised 404 on `resume_from` *before* consulting the
   registry, and `Ai.tsx` never cleared `selectedChatId` on delete. Reproduced
   through the real route: every later message 404'd against a live in-memory
   session, with no escape but "+ New chat".

#### The mechanism, named once

Defects 2 and the rename clobber are one shape, and the fix is one idea:
**a lock was added where a transaction was needed.** `history.save` took the
id's lock, which makes each WRITE atomic and does nothing for the
read-modify-write around it. `harness/history.py` now exposes
`transaction(id)` (hold the lock across the whole load→mutate→save) and
`set_title_if_absent(id, title)` (re-read under the lock, write ONE field).
The title call stays **outside** the lock — holding it across 20 s of HTTP
would freeze the rail's rename and delete, and there is a guard asserting it
does not.

#### The rest

5. **A "resolved" verdict cleared stale marks it had no business clearing.**
   `moved` is decided per-QUOTE and was published per-CHUNK, so clicking a
   still-good citation cleared the stale mark on a sibling into the same chunk
   whose source really had moved — a moved source reading as verified, i.e.
   Invariant 2. `markUnresolvable` now carries a span key; `gone` stays
   chunk-wide (the chunk 404s, so every citation into it is dead).
6. **`ConversationRegistry.get_or_add` was written to make resume atomic and
   was never called** — the route still did `get` then `add`, so two tabs
   resuming one chat each built a session and the second replaced the first
   without closing it. Now wired.
7. **Resume never stopped being a resume.** `isResume` compared the id to
   `resumeFrom`, and the server returns the same id, so every message
   re-POSTed `/api/conversations`. A one-time latch; a failed handover still
   retries.
8. **`_read` degraded on malformed JSON but not on non-object JSON.** `null`,
   `[]`, `5` parse fine and then raise `AttributeError` on `raw.get`, which
   escaped and 500'd `GET /api/history` — blanking the entire rail, the exact
   opposite of "one corrupt file costs one chat".
9. **`CostsPanel` used `??` where every other tab used `||`**, so an
   unrecorded key (the empty string) painted a blank cell instead of
   "(not recorded)" — contradicting the comment directly above it.
10. **`useHistory`'s debounce cleanup hung off one branch**, so clearing the
    search box scheduled an uncancellable fetch; the rail unmounts on every
    chat switch, well inside the 200 ms window.
11. **`reload` was returned by `useHistory` and called by nobody**, so a new
    chat's row and the title generated for it seconds later never appeared
    until something remounted the rail. The panel now bumps a token when a
    turn ends.

**Also: delete now takes two clicks.** The ✕ sat beside the ✎ and destroyed a
transcript outright, under a spec (H6) with no expiry and no undo anywhere.
The armed state is a labelled word, not the same glyph — a confirmation you
can hit by reflex is not a confirmation.

**Transcripts are now stamped `version: 1`.** Nothing reads it; that is the
point. A file with no stamp reads back as **0**, so "written before
versioning" and "written today" are distinguishable — which is the only thing
that makes a future migration possible, and it cannot be added retroactively.

### Still open after that review

- **No tier on the transcript.** A resumed Deep Research chat silently
  continues at Standard. Deliberately NOT fixed here: `_Conversation` does not
  carry the tier (it is per-message), and restoring it on resume is a product
  decision about whether reopening a chat should silently re-arm Deep
  Research's ~44× cost. The schema half of this item is done (above).
- **409-on-resume-busy reads as a generic error** in the composer, though the
  server's sentence does reach the client — `api.ts` surfaces FastAPI's
  `detail`, so the analyst sees "This conversation is still answering the
  previous question", just wearing a generic prefix.
- **`harness/history.py`'s `_write_locks` dict is never pruned.** Left alone
  on purpose: it is bounded by distinct conversation ids touched in one
  process (hundreds, a few hundred bytes), and removing a lock another thread
  may be holding trades a real correctness risk for a trivial saving.
- **None of the UI changes has been seen in a browser.** jsdom applies no
  stylesheet, so the armed-delete styling, the rail's reload-on-turn-end, and
  the span-scoped chip marking are pinned by specs and unwitnessed — the same
  gap that produced this branch's original defect list.

Spec follow-ups still open: the Administrator Handbook paragraph (history
writes questions to disk in plain text; the first exchange goes to the model
for naming — a confidentiality note that `docs/HANDBOOK.md` must carry, and
the file does not exist yet), and `MAX_CONVERSATIONS = 40` may want a
revisit now that eviction is no longer data loss.

---

## AI Mode persistent conversation — code complete, UNWATCHED (2026-08-11)

Spec: `docs/superpowers/specs/2026-08-11-ai-mode-persistent-conversation-design.md`
(P1–P8). Plan: `docs/superpowers/plans/2026-08-11-ai-mode-persistent-conversation.md`.
Two things Destin asked for after using the shipped chat history: a new chat
should appear in the rail the moment it starts, and the conversation should
survive clicking Budget Documents. **Webapp-only** — nothing under `app/`,
`harness/`, `retrieval/`, `ingest/`, `chunking/` or `citation/`, so the eval
rule does not apply and no eval was run. **741 vitest / 73 files, `tsc -b`
exit 0** (baseline 693: +18 here, ~30 from master since branching).

### As shipped

- **The new-chat row is a CLIENT-SIDE placeholder, never a file (P1).** It is
  replaced by IDENTITY, not timing — the synthetic row renders while the
  current conversation's id is absent from `/api/history`'s list, so there is
  never a moment with two rows or with none. Writing an empty transcript was
  rejected: it re-creates the zero-message rows deleted as debris hours
  earlier, and contradicts H2's browsing-is-free.
- **The conversation moved above the router (P4).** `AiSessionProvider` owns
  corpus / selected chat / nonce; a headless `ChatEngine` owns `useChat`.
  A route change is no longer an unmount, so nothing aborts. **Closing the tab
  still aborts (P5)** — the page unloads and the socket drops, which is the
  whole safety argument, since abort-on-close exists because a closed tab once
  left a model streaming and billing into a dead socket.
- **The key `${corpus}:${selectedChatId ?? "new"}:${nonce}` survives unchanged**
  and still remounts on a corpus switch. `Ai.test.tsx`'s wire assertions
  (`createdCorpora` → `["budget","fiscal_notes"]`) pass **unedited** through
  the hoist — they are the wrong-corpus guard and were not allowed to move.

### 🔴 The plan's own code was wrong in three places, each found by RUNNING it

Worth keeping as the record of what a plan's finished-looking code block is
actually worth:

1. **A hook after an early return.** The new `useMemo` was placed below
   `HistoryRail`'s `if (collapsed) return`, a conditional hook. Caught by a
   PRE-EXISTING suite that toggles the rail — the plan's own new tests passed.
2. **`chat.id === draftId` was not a sufficient render guard.** Once the real
   row lands with that same id the predicate is still true, so the real titled
   row would have rendered as a dead "New chat" span with no rename or delete.
3. **The whole architecture diagram.** A keyed host wrapping `Header` +
   `<Routes>` remounts the CURRENT ROUTE on a corpus switch, resetting
   `Ai.tsx`'s unrelated `useAiStatus` probe and flashing the availability gate
   over the composer. The remount boundary had to narrow to `ChatEngine`.

### 🔴 P4's own scenario did NOT work when this first went green

697 specs passed and the feature's headline behaviour was broken. `Ai.tsx`
still unmounts on navigation and `useAiStatus()` had no cache, so returning to
`/ai` re-probed from `null` and rendered the availability gate **over the live,
surviving answer** — and a hiccuped probe rendered "AI Mode is currently
unavailable" while a paid turn streamed invisibly behind it. Every spec mocks
`aiStatus` with an already-resolving promise and then awaits the panel, so
nothing could see it. Fixed both ways: the probe seeds from a module-level last
verdict, and the gate yields to a conversation that already has turns.

### The mirror is `useLayoutEffect`, and that is load-bearing

`ChatEngine` reports its `useChat` result up to a stable provider. With a
passive `useEffect` a rendered frame can exist where the picker reads "Fiscal
notes" while `chat.send` is still the budget instance's closure — `send` bakes
the corpus in at hook level. `useLayoutEffect` commits it in the same commit,
before paint. The dep list names all eight members of `UseChatResult`
individually; passing the whole object re-creates an infinite loop.

### `chatDeleted` has been written three ways and two were wrong

A functional updater (correct, but impure — StrictMode double-invokes it); a
plain closure read (pure, but its only caller runs it AFTER an await, so
deleting chat A then clicking chat B mid-flight discarded B); and the shipped
`selectedIdRef`. **A fix for a style nitpick cost a real data-visible race.**
Both that race and `INERT_CHAT.send`'s synchronous throw are now pinned by
specs verified failing against the exact broken versions.

### 🟡 OUTSTANDING — nobody has watched any of it work

**No OpenRouter key on the dev machine**, so `/ai` renders the gate and no turn
was ever driven. Headless Chrome on the merged build did confirm: all five
routes render, `ai-fullpage` stays scoped to `/ai`, the no-key gate is correct,
and **zero `POST /api/conversations`** across every route — so the hoisted
`useChat` is genuinely inert and H2 holds. But the four headline behaviours are
covered by jsdom alone, and jsdom missed six defects on this feature's
predecessor. **On a keyed machine, confirm:**

1. "+ New chat" → a selected "New chat" row under *Today* at once, no ✎ or ✕.
2. Ask a question → the row keeps its place and takes a real title; never two
   rows, never zero.
3. Deep Research streaming → click Budget Documents, wait, come back: the
   answer is there and no availability gate appears.
4. Corpus switch mid-conversation → thread clears, tier back to Standard.
5. **Close the tab mid-turn** → the server logs the turn ending. This is P5,
   the only safety property here, and no test on this branch can reach it.
6. Delete the chat you are looking at, having reached it by ASKING rather than
   clicking the rail → expect the known cosmetic defect below.
7. Add an API key to an install that had none, then visit `/ai` → watch for a
   stale "unavailable" flash.

### Four known Minors, deliberately carried

- **A seam defect the parallel split created.** Deleting the row for a chat you
  reached by asking (so `selectedChatId` is null) leaves the "New chat"
  placeholder over a full thread: `chatDeleted` correctly does nothing, but the
  id vanishes from `chats` so the placeholder re-renders. Not data loss — the
  next send still works. The clean fix touches the P3 boundary, so it is
  written down rather than fixed blind.
- **`AiModePanel`'s own state now survives a corpus switch** (open PDF panel,
  composer draft, rail collapse), because only `ChatEngine` is keyed now. P6/P7
  read slightly false as a result. No wrong-corpus fetch is possible — the old
  chips are gone from the thread.
- **The verdict cache can show a stale definitive "unavailable"** where the old
  code showed "Checking…" — the admin-just-added-a-key case. Self-corrects on
  the round trip.
- **A turn completing while the analyst is away never bumps the rail's reload
  token**, so an auto-title can land unseen. This is defect 11 of the
  2026-08-11 chat-history review re-opening through a new door.

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

### Task 5 — the backfill is DONE (2026-08-02)

**Every ingestable JLBC book edition is in the corpus.** 4,957 book documents
live, 7 failed — all of them azjlbc.gov 404s where the PDF does not exist.

| | session start | final |
|---|---|---|
| `budget_chunks` | 28,530 | **77,574** |
| documents | 3,533 | **7,434** |
| book editions | 11 | **38 (all ingestable ones)** |

Quality audited across all 21 editions, not assumed: **0 documents in the
FY2024-AFR shape** (<0.5 chunks/page) anywhere, 0 missing titles, and the seven
oldest editions (FY2005–2011) land at 3.65–4.84 chunks/page against the
pre-existing FY2022–27 range of 3.24–5.24. Spot-reads confirmed each document's
text is its own — the only check that catches a stem-collision demux bug.

**Snapshots restored to normal, bulk env discarded.** One fresh verified
snapshot (4.34 GB, 353 entries); the five stale pre-fix archives were deleted,
taking `backups/` from 54 GB to 4.1 GB.

### Task 6 — recency RE-CALIBRATED against the finished corpus (2026-08-02)

**`RECENCY_BOOST_PER_YEAR` 2.064 → 0.85, `REFUSAL_THRESHOLD` 1.04 → 1.46.**
Sweep `eval/results/recency-sweep-2026-08-02T1101Z-c9c16b7.json`; eval
`eval/results/2026-08-02T1109Z-f7ff858.json`.

**Verified the instrument BEFORE trusting it:** 0 of 61 ground-truth chunk_ids
across all three query sets had gone missing. The backfill was purely additive
(`source_url` dedup), so none of the 41%-fallback damage of the last re-ingest
recurred.

| weight | recall@5 | chronological order |
|---|---|---|
| 0.000 | 73.8% | 59.1% |
| 0.700 | 73.8% | 91.0% |
| **0.850** | **73.8%** | **92.5%** |
| 1.000 | 71.4% | 93.4% |
| 1.169 | 71.4% | 94.1% |
| 2.064 (was shipped) | 69.0% | 97.7% |

**0.85 is the largest weight that costs NOTHING** — recall@5 identical to the
boost being off, while ordering clears the 90% target. The cliff starts at 1.0.

**The sweep's own recommendation (1.169) was GRID-LIMITED, not principled.**
`sweep_recency` derives its grid from the score spread — 13 steps of 0.585 here
— so 0.70 and 0.85 were never tested and the smallest grid point clearing 90%
won by default. **Always pass an explicit `--weights` grid before believing the
recommendation it prints.**

**Why the old 2.064 was wrong:** it was picked by the same "costs nothing" rule
on 2026-08-01, but against an eval set where 32 of 34 queries named a year and
never executed the code. The flat recall column justifying it was evidence the
set never ran the boost, not evidence of safety.

**The coupling bit in the counter-intuitive direction, and the guard caught
it.** LOWERING the weight RAISES `top_score` (a smaller penalty depresses less),
so the threshold had to go UP. Refusal query q-030 went −1.17 → +1.42 and
answered a question it should have refused until 1.46 landed.
`test_the_shipped_weight_and_refusal_threshold_move_together` failed exactly as
designed.

**Final eval: recall@5 73.81%, recall@15 97.62%, recall@20 97.62%, refusal
precision 60%, p95 852 ms. Gate G1 passes.** recall@5 is up 7.1 points on the
same corpus.

**One genuine regression, and it is the CORPUS, not the weight.** `q-009` was
passing at rank 17 and its ground truth now sits outside the top 20, pushed
out by a newly-ingested FY2024 document. `cur@20` is 97.6% at weight **0.000**
too, so switching the boost off would not recover it. Re-point or accept that
query; do not read it as a ranking regression.

### 🔴 THE PDFIUM PROBE WAS NOT THREAD-SAFE — it failed 224 VALID PDFs

**Introduced by the poison-pill fix earlier the same day, caught in the live
run.** `pypdfium2` has global state and is not thread-safe. The pre-stage probe
runs inside `run_batch`, which runs on a worker thread, so at
`JLBC_INGEST_WORKERS=4` several threads probed concurrently, corrupted pdfium,
and rejected **perfectly valid** PDFs with `PdfiumError: Data format error`.

Proven, not inferred: all 224 rejected files open fine single-threaded, and
their mtimes showed they had been byte-final on disk since 2026-07-31 — two
days before the failure. Nothing was wrong with the files.

Reproduced on demand with the same 80 real PDFs in one process:

| | failures |
|---|---|
| serial | **0 / 80** |
| 4 threads | **60, 80, 80 of 80** |

Fixed with `_PDFIUM_MUTEX` around the whole open→count→close sequence, mirroring
`_EMBED_MUTEX`. Merge `71e85a7`.

**The regression test is size-dependent and that matters.** With the suite's
existing 662-byte fixture PDFs the unlocked code passed 0 failures out of 600 —
a test that would have proven nothing. The guard only arms at realistic file
sizes, so the fixture is 500 pages (~62 KB, the real corpus median) and the
docstring says never to shrink it for speed.

**Office exposure was nil** — the default is one worker. Only parallel
backfills could hit this.

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

**This DOES degrade the OFFICE experience, now measured rather than predicted.**
The final post-backfill snapshot — a healthy corpus at normal retention, not
the bloated one — took **3 minutes 30 seconds** to zip 4.7 GB into 4.34 GB, one
core, single-threaded. In the office that is what one analyst uploading one
document costs: a 3.5-minute apparent hang with the ingest lock held, growing
with the corpus. Office write rates will not pile up 500 versions, so the
corpus stays smaller there — but zip-the-whole-corpus-per-write does not scale.
An incremental or copy-on-write snapshot is the real fix. **Follow-up, not
done, and it should be done before the office relies on uploads.**

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

**Superseded by the full baseline** — `eval/results/agent/2026-08-02T0900Z-0b08221/`,
31 queries, 0 errors, $1.20. Key figures: key-fact rate 0.81, refusal
correctness 1.00, `cite_pass_rate` 0.84, `first_try_cite_rate` 0.90,
citations/answer 10.1, retrieval efficiency 0.44, 138k input tokens/answer.
Judged by **`z-ai/glm-5.2`**: `claim_coverage_precision` 0.578,
`claim_coverage_recall` 0.969, holistic 4.13.

**The judge is glm-5.2 for everything from 2026-08-02** (Destin's call).
Measured against claude-sonnet-5 over these same 31 answers: 0 errors, every
disagreement within one point, rank correlation 0.89, comparable claim counts
(144 vs 135), ~8x cheaper — so every run can be judged, not just merge gates.
Accepted risk: glm-5.2 is also the model under test, so it grades its own
output. Evidence and the rejected alternatives:
`docs/superpowers/investigations/2026-08-02-judge-model-comparison.md`.
**Judge results are not comparable across judge models** — now enforced by
`compare_agent_runs.py`, which withholds the judge section when they differ.

**Still not run:** the 4-query Deep Research probe.

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
