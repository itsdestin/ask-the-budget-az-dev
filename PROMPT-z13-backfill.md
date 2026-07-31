> **STATUS 2026-07-31 — PARTIALLY EXECUTED. Read this before acting.**
>
> - **Phase A (setup + parity gate): DONE.** Gate passed exactly; p95 821 ms.
> - **Phase B (recency machinery): DONE and merged** (`4c75f2c`). The boost
>   ships at `RECENCY_BOOST_PER_YEAR = 0.0` awaiting Phase D.
> - **Phase C (backfill): RUNNING RIGHT NOW** on three detached processes.
>   Do NOT start a second backfill, and do NOT re-run Phase A/B.
>   Fiscal notes ~65% done; the 38 book editions have not started.
> - **Phase D (calibration): BLOCKED** until C finishes — it needs the
>   completed corpus to author ground truth against.
> - **Phase E:** not started.
>
> Live state, operating config, restore points and the throughput work done
> during the run are recorded in `STATUS.md` → "Z13 backfill — IN PROGRESS".
> Restart the stack with `~/backfill-scripts/restart_stack.sh <workers> <omp>
> <shared_mineru>` (currently `12 3 0`); progress in `~/backfill-progress.log`.
>
> **If you are picking this up to CONTINUE:** the only work left in this
> runbook is Phase D and Phase E. Everything else below is history.

# Handoff: Z13 Backfill + Recency Calibration (S20 + S21)

You are a fresh Claude session on **Destin's Ryzen AI Max+ 395 machine
(Linux)**. Your job: implement the recency-ranking plan, run the full
historical backfill, calibrate, and produce the canonical handoff corpus.
The design is settled — spec decisions S20/S21 record it; do not
re-litigate.

## Read first (in order)

1. `STATUS.md` (auto-loaded) — Plans 1–4 are shipped; read all four ship sections
2. `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — S20 (backfill scope), S21 (recency), Invariant 8
3. `docs/superpowers/plans/2026-07-31-standalone-plan-recency-ranking.md` — the code plan you will execute (Tasks 1–5 before the backfill, Task 6 after)
4. `docs/superpowers/plans/2026-07-30-standalone-plan-3-ingest.md` Task 15 — how Add-a-JLBC-book / the catalog / the probe ladder work

## Phase A — Setup + parity gate (do not skip)

```bash
git clone git@github.com:itsdestin/ask-the-budget-az-dev.git ~/ask-the-budget-az-dev
cd ~/ask-the-budget-az-dev && bash setup.sh
```

- Copy the current corpus from the Windows machine: `data/insight-data/`
  (lancedb + documents.json + any pdfs/) and `data/cached-pdfs/` into the
  same repo-relative paths (or set `JLBC_DATA_DIR`). Do NOT try to resume
  Windows-created queue jobs (`<data_dir>/jobs/*.json` carry Windows
  paths) — finish or delete them on the Windows side first.
- Model caches download on first use (fastembed + MinerU weights) — do
  this on good bandwidth.
- **Parity gate:** `uv run python -m eval.run_eval` must reproduce the
  Plan 3 baseline within noise: recall@5 72.41%, recall@15 96.55%,
  recall@20 100%. If it doesn't, STOP and diagnose (platform/ONNX issue)
  before investing days of processing.
- MinerU: `uv run mineru --version` works; CPU mode is the plan of
  record. You MAY spend up to ~30 minutes testing ROCm torch as a
  speedup; if it isn't cleanly working in that budget, stay on CPU
  (16 Zen 5 cores is already the win we came for).

## Phase B — Recency machinery (plan Tasks 1–5)

Execute the recency plan's Tasks 1–5 via
superpowers:subagent-driven-development in a worktree, merge to master
(`--no-ff`, push). The boost ships OFF (0.0); nothing user-visible
changes yet. This lands BEFORE the backfill so the eval machinery is
ready and the year-parser hard-filter already protects explicit-year
queries as old docs arrive.

## Phase C — The backfill (S20 scope, EXACTLY)

All through the app's own queue (run the server:
`uv run uvicorn app.main:create_app --factory --port 9300`) — this
dogfoods the exact machinery being handed off. Order: **newest → oldest**
(most-used data lands first; an interruption still leaves the best
possible corpus).

1. **Fiscal-note back catalogue**: `POST /api/fiscal-notes/refresh` is
   newest-2-sessions by design; for the back catalogue drive
   `ingest/fiscal_notes_refresh.py`'s session fetch per year 2026 → 1999
   (small script or loop; parser + queue path already exist). ~2,126
   notes, most 2–5 pages. Expect this to take a day-ish of queue time.
2. **Baselines FY2027 → FY2012** and **Approps FY2026 → FY2005** via
   `POST /api/books/discover` + `/api/books/ingest` per edition (catalog
   hits — zero URL guessing; FY25–27 baselines + FY25 approps largely
   exist already and dedup will skip them). ~38 editions ≈ 4,700 PDFs.
   Run editions serially (the single-writer lock enforces it anyway);
   monitor via `GET /api/jobs` or the Upload page.
3. **Do NOT ingest** the single-file-only era (approps FY1984–2004,
   baselines FY2007–2011) — S20 records why. They stay
   viewable-not-searchable.
4. Per-edition spot check (cheap, do it every few editions): pick one
   fresh doc → search finds it → title is real (not a slug) → PDF opens
   at the right page from a passage click → validation warnings on the
   job are sane.

Watch for: probe-ladder editions reporting `unreachable` children (log
and continue — report the list at the end); the FY2024/25 approps
summary-title gap (humanized fallbacks are acceptable); disk (few GB).

## Phase D — Calibration + gates (plan Task 6)

1. Author `eval/queries_historical.yaml` ground truth against the now-real
   backfilled corpus (plan Task 4 Step 1).
2. `uv run python -m eval.calibrate_recency` → set
   `RECENCY_BOOST_PER_YEAR` per the recommendation.
3. Re-run `eval/calibrate_refusal.py` → update
   `harness/constants.py::REFUSAL_THRESHOLD` if recommended.
4. Full eval: original 34 + no-year + historical sets all green at the
   chosen weight. **This is the poisoning check** — the no-year set
   proves recent docs still win; the historical set proves old docs are
   reachable on request.
5. Commit eval results + the weight/threshold changes; push.

## Phase E — Wrap

- `bash setup.sh --verify` green.
- STATUS.md: backfill section — final corpus counts (docs + chunks per
  corpus), editions ingested, unreachable-children list, chosen recency
  weight, refusal threshold, eval table. This corpus is now canonical:
  note that `data/insight-data/` on THIS machine is what Plan 5 deploys
  to the office share.
- Report: counts, timings (pages/min observed — Plan 5's packaging docs
  want realistic office-hardware expectations to compare against),
  deviations, anything unreachable.

## Hard rules

- Parity gate before anything else; eval after every retrieval-path
  change (CLAUDE.md rule).
- Newest-first ordering; app-queue path only (no bespoke ingest
  scripts — if the queue can't do something, that's a bug to fix, not
  bypass).
- S20 scope is exact — no old single-file books, no FY2000/01 hunting.
- Backups: the queue's S17 snapshots rotate at 5; before starting
  Phase C take one manual archive of the pre-backfill corpus
  (`zip data/insight-data → ~/pre-backfill-corpus.zip`) and keep it
  until handoff.
