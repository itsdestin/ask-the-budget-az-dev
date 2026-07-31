# Standalone Plan: Recency-Aware Ranking (S21)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement spec S21 so the S20 backfill (20 years of near-identical per-agency pages) can't poison no-year queries: query year-parsing → hard filter; soft post-rerank recency bonus (budget corpus only) calibrated by eval sweep; AI prompt guidance; refusal recalibration.

**Context:** Executed on the Z13 as part of the backfill runbook (`PROMPT-z13-backfill.md`) — machinery is built BEFORE the backfill (boost weight defaults to 0.0 = off), calibrated AFTER the backfill when old docs exist to tune against. All retrieval-path changes ⇒ the eval runs at every step (CLAUDE.md rule).

**Spec:** S21 in `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`. Work in a worktree.

---

## File structure

| File | Responsibility |
|---|---|
| Create `retrieval/query_year.py` | `parse_query_years(query) -> list[int]` — mockup-ported year forms |
| Create `retrieval/recency.py` | `RECENCY_BOOST_PER_YEAR` (default 0.0), `apply_recency_boost(chunks, *, anchor_fy)` |
| Modify `retrieval/pipeline.py` | Wire both into `retrieve()` (budget corpus only for the boost) |
| Create `eval/queries_historical.yaml` + `eval/calibrate_recency.py` | Historical/explicit-year query set; boost-weight sweep |
| Modify `harness/system-prompt.md` + `harness/prompt.py` | Recency guidance section |
| Tests | `tests/test_query_year.py`, `test_recency.py`, pipeline additions, `test_calibrate_recency.py`, prompt test additions |

---

### Task 1: Query year-parser (`retrieval/query_year.py`)

- [ ] Step 1 — failing tests (`tests/test_query_year.py`), forms ported from the mockup's `webapp/reference/assets/search/search.js` year handling: `"dcs caseworkers fy26"` → `[2026]`; `"FY 2019 DES funding"` → `[2019]`; `"appropriations 2013"` → `[2013]`; `"compare fy24 and fy25"` → `[2024, 2025]`; `"HB2001"` → `[]` (bill numbers are NOT years); `"$2,019,000 for programs"` → `[]` (dollar amounts are not years); `"'19 baseline"` → `[2019]`; bare two-digit numbers WITHOUT fy/'-prefix → `[]` (too ambiguous); plausible range clamp 1990–2035.
- [ ] Step 2 — fail. Step 3 — implement (pure regex module, ~40 lines; document each pattern's source form). Step 4 — PASS. Step 5 — commit `feat(retrieval): query year-parser (mockup-ported forms)`.

### Task 2: Hard filter on parsed years

- [ ] Step 1 — failing pipeline tests: `retrieve(RetrievalRequest(query="fy2019 DES funding"))` passes `fiscal_year=[2019]` into both search stages (assert via monkeypatched stages) **only when** the request carried no explicit `fiscal_year` filter; an explicit caller filter always wins (parser never overrides); applies to BOTH corpora; parsed years echoed on `RetrievalResult` as `inferred_fiscal_years: list[int]` (additive field, default `[]`) so the UI/tools can show "filtered to FY 2019".
- [ ] Step 2 — fail. Step 3 — implement in `retrieve()` before the stage calls. Step 4 — PASS + full eval run (expect unchanged numbers — current queries that name years now hard-filter, which should only help; investigate any regression before proceeding). Step 5 — commit `feat(retrieval): explicit query years become hard fiscal-year filters`.

### Task 3: Soft recency bonus (`retrieval/recency.py`)

- [ ] Step 1 — failing tests: `apply_recency_boost(chunks, anchor_fy=2027)` with weight 0.4 adds `0.4 * (fy - 2027)` to each score (negative for older; `fy=None` chunks get the oldest-in-set penalty, never a free pass), then re-sorts desc with chunk_id tiebreak; weight 0.0 is a byte-identical no-op (order and scores unchanged); boost is applied in `retrieve()` **after** rerank, **only** for `corpus="budget_chunks"`, **only** when no explicit AND no parsed year filter is active; `top_score`/`reranker_scores` reflect boosted values (they feed the refusal check — that's why Task 6 recalibrates); anchor_fy = max fiscal_year present in the result set (not wall-clock — corpus-relative).
- [ ] Step 2 — fail. Step 3 — implement; `RECENCY_BOOST_PER_YEAR = 0.0` ships as the default in `retrieval/recency.py` with a WHY comment ("0.0 until calibrated by eval/calibrate_recency.py — see S21"). Step 4 — PASS + eval run (weight 0 ⇒ identical numbers, assert exactly). Step 5 — commit `feat(retrieval): post-rerank recency bonus, off by default pending calibration`.

### Task 4: Eval expansion + calibration sweep

- [ ] Step 1 — `eval/queries_historical.yaml`: ~10 explicit-year queries against backfilled editions (authored AFTER the backfill lands — real chunk_ids; e.g. "fy2014 ADC private prison per diem", "FY 2008 appropriations report DES funding") + ~6 no-year current-intent queries whose ground truth is the NEWEST edition's chunk ("what is the AHCCCS provider rate increase" → FY27 chunk). Schema identical to `queries.yaml`; runner accepts `--queries` (already does).
- [ ] Step 2 — `eval/calibrate_recency.py` (mirror `calibrate_refusal.py`'s pattern): sweeps `RECENCY_BOOST_PER_YEAR` over a grid derived from the observed rerank-score spread (e.g. 0 → spread/5 in 12 steps), running BOTH query sets at each weight via in-process `retrieve()` with the weight injected; reports per-weight recall@15 on (a) the original 34-query set, (b) the no-year current set, (c) the historical set (must be invariant — they hard-filter); recommends the **minimal** weight where (a) and (b) both clear the G1 bars. Tests with a synthetic corpus fixture (no models: injected stages).
- [ ] Step 3 — tests PASS. Step 4 — commit `eval: historical + no-year query sets and recency-weight calibration sweep`.

### Task 5: AI Mode prompt guidance

- [ ] Add a short "Recency and fiscal years" section to `harness/system-prompt.md`: when the user names a year it is auto-filtered (mention `inferred_fiscal_years` echo); when they don't, results arrive recency-favored — pass explicit `fiscal_year` filters for historical/comparative questions; Deep Research multi-year sweeps should iterate explicit year filters rather than one giant unfiltered retrieve. Prompt tests: section present, no stale claims. Commit `feat(harness): recency guidance in system prompt`.

### Task 6: Calibration + refusal recalibration (RUN AFTER BACKFILL — sequenced by the runbook)

- [ ] Run `uv run python -m eval.calibrate_recency` against the fully backfilled corpus → set `RECENCY_BOOST_PER_YEAR` to the recommendation (commit with the sweep table in the message). Re-run `eval/calibrate_refusal.py` (boosted top_scores shift the distribution) → update `harness/constants.py::REFUSAL_THRESHOLD` if recommended, with the same one-source discipline. Full eval suite (all three query sets) green at the chosen weight; results committed. STATUS.md updated (S21 shipped, chosen weight, before/after recall table). Merge per finishing-a-development-branch.

---

## Self-review notes

- The boost never touches explicit-year paths (hard-filter short-circuits it), never touches fiscal notes, ships off (0.0) so the machinery merges safely before the backfill exists, and is calibrated by sweep rather than vibes.
- `inferred_fiscal_years` is additive on `RetrievalResult` — no consumer breaks; UI surfacing of "filtered to FY X" is optional Plan 5 polish.
- Known interaction pinned in tests: boosted scores feed the refusal threshold ⇒ Task 6 recalibrates; tests in Task 3 assert `top_score` reflects the boost so this can't be silently missed.
