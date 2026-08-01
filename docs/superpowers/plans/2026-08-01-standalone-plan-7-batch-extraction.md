# Standalone Plan 7: Batch Extraction — amortize MinerU's model load

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the remaining 27-edition JLBC backfill (~3,500 documents) from ~3.7 hours to roughly one, by loading MinerU's models once per *batch* instead of once per *document*.

**The measurement this exists for:** a MinerU invocation costs ~38 s, and **~33 s of that is model loading**. We pay it 3,500 times — about 32 core-hours of pure loading. `mineru -p <directory>` processes a whole folder in one process; measured **2.85× on only 4 documents** during the Z13 run, and the amortization improves with batch size.

**Architecture:** `ingest/mineru_runner.py` gains a batch entry point that stages N PDFs into one temp directory under collision-proof names, runs a single `mineru -p <dir>` invocation, and demuxes the per-file output back to each document. `ingest/worker.py` gains a batch-claiming path behind `JLBC_INGEST_BATCH=N` (default 1 = today's behaviour, byte-identical). Nothing else changes.

**Spec:** S7 (offline-first bundling constrains the MinerU version), S17 (per-batch snapshot, already landed in Plan 5 Track 4). Backfill scope: S20.

**Work in a worktree:** `git worktree add ~/atb-worktrees/plan7-batch -b plan7-batch origin/master`

---

## Ground truth (READ FIRST)

1. **The current command is `mineru -p <pdf> -o <tmp> -s <start> -e <end> -b pipeline`** (`_run_range` in `ingest/mineru_runner.py`). `-p` already accepts a **directory** — that is MinerU's own batch mode, so this plan uses a supported path, not a trick.
2. **MinerU is per-file tolerant in batch mode.** The Z13 run produced `Error: 1 task(s) failed while processing documents` and kept going. Verify this still holds (Task 1) — the whole design depends on one bad PDF not killing its 19 batch-mates.
3. **Do NOT batch page ranges.** Extraction resume granularity today is the page range *within* a document, which exists for 200-page books. Batch mode is for **whole small documents**; a document over `BATCH_MAX_PAGES` keeps the existing per-range path. Mixing the two would multiply the state space for no gain — per-agency book pages are 2–6 pages, which is where all the volume is.
4. **Filename stems collide across editions.** MinerU names its output by input stem, and `508.pdf` exists in both the FY2026 Baseline and the FY2026 Approps — the same collision that produced the `make_doc_id` bug (fixed in `f85b20a`). **Stage every PDF into the batch directory under its `doc_id`**, never its original filename, or the demux silently hands one document's text to another.
5. **`write_range_pages(...)` lives in `scripts/run_mineru.py`**, not in `ingest/` — `mineru_runner.py` imports it from there along with `_read_mineru_output` and `_contiguous_ranges`. It is the existing per-document output writer and batch mode reuses it unchanged, once per demuxed document. Note the dependency direction: `ingest/` imports from `scripts/`, so `scripts/run_mineru.py` is live code despite its location, and Plan 5's deletion pass deliberately left it alone.
6. **Extraction output lands in `<data_dir>/extractor-output/<doc_id>/`** and that directory IS the resume signal — the worker skips extraction when it is complete. Batch resume needs no new journal.
7. **Claims are per-job AND per-doc_id** (`ingest/claim.py`). A batch must hold every claim it intends to process, and release them all on failure.
8. **Do not retry the shared `mineru-api` server.** It gave 38 s → 8 s and then died with glibc heap corruption at 12 concurrent requests, failing 101 documents. The seam survives as `JLBC_MINERU_API_URL`; leave it unset. Batch mode is the safe way to claim the same win because it keeps one process per batch.
9. **`mineru==3.1.6` is pinned** (S7 / the bundle work). `>=3.1.6` silently resolves to 3.4.4, which changes chunk text corpus-wide. Do not upgrade inside this plan.

---

## Tasks

### Task 1: Prove batch mode behaves — a spike, before any code

**Files:** `docs/superpowers/investigations/2026-08-01-mineru-batch-mode.md`

- [ ] Stage ~20 real per-agency PDFs from `<data_dir>/pdfs/` into a temp directory under doc_id names. Run `mineru -p <dir> -o <out> -b pipeline` once. Measure wall clock against the same 20 run individually.
- [ ] **Confirm the three properties the design assumes**, and record the evidence: (a) output is written per input file and is mappable back by stem; (b) **one corrupt/empty PDF fails alone and the batch completes** — deliberately include the known zero-byte PDF; (c) per-document text is byte-identical to the one-at-a-time path for at least 3 documents.
- [ ] Measure the batch-size curve at 5 / 10 / 20 / 40 and record peak RSS. **Report before continuing** — if (b) is false, the design needs per-file recovery and the estimate changes.
- [ ] Commit: `docs(investigation): MinerU batch-mode behaviour and batch-size curve`

### Task 2: `MineruRunner.run_batch`

**Files:** Modify `ingest/mineru_runner.py`; Create `tests/test_mineru_batch.py`.

- [ ] **Step 1 — failing tests** against a faked `mineru` executable (the existing tests already fake it — follow that pattern; no real MinerU in unit tests):
  - N documents in, N output directories out, each matched to the right doc_id
  - **two inputs whose original filenames are identical** both survive and are not confused (Ground truth 4)
  - one input producing no output leaves the others complete and is reported as a per-document failure, not a batch failure
  - cancel kills the child and raises `MineruCancelled` for every unfinished document in the batch
  - timeout scales with batch size rather than using the per-document `DEFAULT_TIMEOUT_S`
- [ ] **Step 2 — implement.** `run_batch(items, *, timeout_s, on_document)` where `items` carries `(doc_id, pdf_path, out_dir)`. Stage into one temp dir as `<doc_id>.pdf`, one `-p <dir>` invocation, demux by stem, call the existing `write_range_pages` per document. Progress reports **documents**, not pages.
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_mineru_batch.py tests/test_mineru_runner.py -q`
- [ ] Commit: `feat(ingest): MineruRunner.run_batch — one model load per batch`

### Task 3: Worker batch path, opt-in and default-off

**Files:** Modify `ingest/worker.py`; Create `tests/test_ingest_batch.py`.

- [ ] **Step 1 — failing tests:**
  - `JLBC_INGEST_BATCH` unset or 1 → **byte-identical to today**, per-document path, no batching code reached (assert this explicitly; it is the safety property)
  - a batch claims every job it processes and releases all claims if it dies
  - eligible jobs only: same extractor, page count ≤ `BATCH_MAX_PAGES`, no partial `completed_ranges` (Ground truth 3)
  - a document already having complete extractor output is skipped, not re-extracted — batch resume
  - one failing document inside a batch is quarantined with its own reason; its batch-mates reach `live`
  - an invalid `JLBC_INGEST_BATCH` (0, blank, a typo) means 1 and says so on stderr — mirroring how `JLBC_INGEST_WORKERS` handles the same mistake
- [ ] **Step 2 — implement.** Batching composes with `JLBC_INGEST_WORKERS`: each worker claims and runs its own batch. The write phase stays serialized behind `IngestLock` exactly as now.
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_ingest_batch.py tests/test_ingest_worker.py tests/test_ingest_parallel.py -q`
- [ ] Commit: `feat(ingest): opt-in batch extraction behind JLBC_INGEST_BATCH`

### Task 4: Live validation on one real edition

- [ ] Ingest **one** book edition (~130 documents) with `JLBC_INGEST_BATCH=20 JLBC_INGEST_WORKERS=12`, measured against the recorded 945 docs/hr baseline.
- [ ] **Audit the result, do not assume it:** documents.json count equals distinct doc_ids in LanceDB; zero documents with zero passages; zero orphan chunks; zero duplicate chunk_ids; **and a chunks-per-page sanity check per document** — the FY2024 AFR proved a document can land `live` and near-empty with nothing flagging it.
- [ ] Compare passage counts against the same edition's siblings already in the corpus. A batch bug that mixes documents shows up as plausible text under the wrong doc_id, which only a spot-read catches — read 3.
- [ ] Commit: `docs(STATUS): batch extraction measured on one edition`

### Task 5: Run the remaining 26 editions

- [ ] `~/backfill-scripts/orchestrate.py` with `JLBC_BACKFILL_UNITS=books` (it already carries the full 38-edition list; the 11 done editions skip on `source_url` dedup).
- [ ] Snapshot first — Plan 5 Track 4 landed per-batch S17 snapshots, so leave snapshotting **on**; the O(n²) per-document problem that justified `JLBC_INGEST_SNAPSHOT=off` is gone.
- [ ] Commit: final counts in `STATUS.md`.

### Task 6: Re-calibrate what the bigger corpus invalidates

- [ ] **`RECENCY_BOOST_PER_YEAR = 2.064` was calibrated against a corpus spanning FY2022–2027.** After this run it spans FY2005–2027 — more year spread, and far more old material competing. Re-run `python -m eval.sweep_recency` and re-decide. The code comment in `retrieval/recency.py` says so.
- [ ] Re-run `eval/calibrate_refusal.py` at whatever weight is chosen, and `python -m eval.run_eval`. Commit results.
- [ ] **Add no-year queries with pre-FY2025 ground truth to `eval/queries.yaml`.** 32 of its 34 queries name a fiscal year and never execute the recency path, and every ground-truth chunk is FY2025–2027 — so the set cannot currently measure what any ranking change costs an older target. After this backfill there will finally be old targets to point at. Without this, the re-calibration in the previous step is measured by the same blind instrument as the first one.

---

## Risks

1. **Ground truth 2 is the load-bearing assumption.** If MinerU aborts a batch on one bad file, batch size becomes a blast radius and the design needs per-file recovery. Task 1 exists to find that out for ~30 minutes of work rather than mid-backfill.
2. **Stem collision is the silent failure.** Staging by `doc_id` prevents it; the test in Task 2 Step 1 is the guard. Get this wrong and one agency's budget text is filed under another agency — plausible, cited, and wrong.
3. **Memory scales with batch × workers.** Extraction measured ~2.1 GB RSS per concurrent document; batching may raise the per-process peak. Task 1 records it; size the run from the measurement, not the estimate.
4. **This is the ingest path, and it is now live for the office.** Default-off (`JLBC_INGEST_BATCH` unset = 1) is what makes it safe to merge before it is proven at scale.
