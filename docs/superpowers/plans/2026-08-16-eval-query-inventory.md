# Eval Query Inventory & Scoring Guide

**Branch:** `consolidated-eval-pipeline` — the re-tagged set (Tasks 1–9 merged).
**Corpus verification:** all **62 queries** run through `scripts/verify_agent_query.py` — **0 fact-presence misses, 0 reachability misses**. Every key fact exists in `budget_chunks` and is returned in a top-20 `retrieve()` of the verbatim question.
**Status:** Tasks 1–9 done; the new Multi set is **not** authored yet (Task 10, awaiting content decisions); the Quick set was **diversified** (27 → 54 queries, added niche agencies/years/shapes — see "Quick Lookup" notes); nothing here has spent money.

---

## How the eval scores — the pipeline in brief

A run records a **transcript** per query (the agent's retrieve calls, cite calls, reasoning, and final answer), then the **mechanical scorer** (`eval/agent_scoring.py`) computes per-query signals from the transcript alone, and `aggregate()` rolls them into a summary. An optional **paid judge** adds LLM judgment on top. The consolidated pipeline's headline is **cost-to-accurate**: tokens and turns **only** for responses that pass the accurate bar.

### The accurate bar (headline gate)
A query counts toward the headline (`tokens_to_accurate` / `turns_to_accurate`) **only when**:
1. the terminal frame is `_done` (no crash),
2. it passes **all** its key facts, **and**
3. it produced **≥1 verified citation**.

Fast-but-wrong and fast-but-uncited are excluded (their token/turn counts still recorded separately). Refusal queries (0 key facts) are **never** "accurate" — their correctness lives in the refusal metric.

### How each of the four axes scores

| Axis | What it answers | Metric | How it's computed from the transcript |
|---|---|---|---|
| **Headline** | Cost of a *correct* answer | `tokens_to_accurate`, `turns_to_accurate` (per set + overall) | Over accurate-bar-passing queries only: total tokens (input+output+cached) and step count |
| **1 — Retrieval** | Did the right chunks come back / get used | `retrieval_efficiency` | Used chunks (cited, OR containing a currency/regex fact that also appears in the answer) ÷ distinct chunks retrieved. Judge's `chunk_relevance` adds a semantic "did these chunks match the question" grade |
| **2 — Agent efficiency** | Was the search economical | steps, retrieve calls, token split, cost, `retrieves_after_sufficient`, filter usage | Direct counts of tool calls / tokens / retries after facts were already in hand (reported per query/set) |
| **3 — Doc-type** (Multi only) | Cited the right kind of document | `document_correctness` | Share of verified citations whose chunk's `doc_id` ∈ the query's `correct_response_docs`. Zero citations → `None` + `unanswered` flag, not 0 |

### Every query also carries these scored signals
- **`ok`** — did the agent reach a `_done` frame (crash = not ok)
- **`key_fact_rate`** — matched key facts ÷ total key facts (the core correctness signal)
- **citation discipline** — `cite_pass_rate`, `first_try_cite_rate`, `retries_per_citation`, `figure_coverage`
- **output hygiene** — meta-narration hits, internal-vocab hits, token leak
- **refusal correctness** — a should-refuse query that correctly refuses scores well (and is never in the headline)

With **tool-error harvesting**, every failed retrieve/cite/argument is logged with the turn it cost, feeding prompt/tool tuning.

---

## The query sets

### Quick Lookup — `set: quick` — 54 queries
**Contract:** a well-tuned agent answers in **one retrieve call**; single fact / single agency / single FY. **Measures:** retrieval precision + minimal-turn efficiency. These are the workhorse regression signal — most of them are `lookup` (find one number) with a few `comparison`/`analyze`/`historical` shapes that are still single-shot.

**Diversification (2026-08-16):** the original 27 were heavily ADC/DES/highways/FY2026. Added 27 more spread over **niche agencies** (Agriculture, Lottery, Gaming, Registrar of Contractors, Liquor, Mine Inspector, Water Resources, State Parks, Insurance, Game & Fish, Secretary of State, Juvenile Corrections, Tourism, Veterans' Services, Nursing Board, Revenue, UA Health Sciences), **more years** (FY2025 operating budgets, FY2027 governor's budget, FY2013 historical), and **harder shapes** (analyze/comparison across years). Anchors verified present + reachable. A few carry "NOTE: verify anchor" in judge_notes — those were authored against plausible figures and must be re-verified with the script before a scored run (flagged, not silent).

| id | shape | #facts | What it asks |
|---|---|---|---|
| lk-adc-total-fy2026 | lookup | 2 | Total ADC prison-system FY26 spend + GF vs other share |
| lk-k12-basic-aid-fy2026 | lookup | 1 | Bottom-line K-12 formula funding in the passed FY26 budget |
| lk-gf-revenue-fy2026 | lookup | 2 | FY26 revenue assumption + projected ending balance |
| lk-dps-operating-fy2026 | lookup | 2 | Highway patrol FY26 total + plain operating vs earmarked |
| lk-asu-operating-fy2026 | lookup | 2 | ASU state money + GF vs non-GF share |
| lk-adc-officer-stipend-fy2026 | lookup | 2 | CO one-time bonus amount + per-officer split |
| lk-eorp-offset | lookup | 2 | County elected-officials pension offset: yearly amount + division |
| lk-asrs-rate-fy2026 | lookup | 2 | ASRS (pension) employer rate |
| lk-scotus-salary | lookup | 2 | A SCOTUS-judge salary figure |
| lk-bsf-balance-fy2026 | lookup | 2 | Budget Stabilization Fund balance |
| lk-prop123-increment | lookup | 2 | Prop 123 inflation increment |
| lk-hurf-split | lookup | 3 | Highway User Revenue Fund split |
| cm-basic-aid-3yr | comparison | 3 | K-12 basic aid across 3 fiscal years |
| cm-des-gf-growth | comparison | 3 | DES General Fund growth |
| cm-highway-construction | comparison | 2 | Highway construction comparison |
| cm-supplementals-fy2026 | comparison | 2 | FY26 supplemental appropriations |
| cm-university-funding-dr | comparison | 3 | Which of ASU/UofA/NAU leans hardest on state tax dollars (re-homed from Deep; now Standard tier) |
| an-ahcccs-enrollment | analyze | 2 | AHCCCS enrollment analysis |
| an-ahcccs-gf-drivers | analyze | 3 | AHCCCS GF cost drivers |
| an-esa-growth | analyze | 2 | ESA growth analysis |
| mm-adc-briefing | memo | 2 | ADC briefing-style memo |
| mm-esa-memo | memo | 1 | ESA memo |
| hs-arra-k12-stabilization-2010 | historical | 1 | FY10 stimulus / K-12 maintenance-of-effort |
| hs-leaseback-prisons-2010 | historical | 1 | FY10 sale-and-leaseback (incl. prisons) |
| hs-bsf-draw-2008 | historical | 1 | FY08 BSF draw for GF shortfall |
| hs-full-day-kindergarten-2005 | historical | 1 | Early full-day-K phase-in / deadline |
| hs-fy2010-oneshot-financing | historical | 1 | FY10 one-time-vs-ongoing reliance |
| lk-agr-operating-fy2025 | lookup | 2 | Agriculture Dept FY25 operating budget + FTE (verify anchor) |
| lk-lot-operating-fy2025 | lookup | 1 | Lottery operating budget FY25 |
| lk-gam-operating-fy2025 | lookup | 1 | Gaming Dept FY25 operating budget |
| lk-roc-operating-fy2025 | lookup | 1 | Registrar of Contractors FY25 |
| lk-liq-operating-fy2025 | lookup | 1 | Liquor Dept FY25 |
| lk-min-operating-fy2025 | lookup | 1 | State Mine Inspector FY25 |
| lk-wat-operating-fy2025 | lookup | 1 | Water Resources FY25 |
| lk-psp-operating-fy2025 | lookup | 1 | State Parks FY25 (verify anchor) |
| lk-gf-revenue-fy2027 | analyze | 1 | Governor's FY27 GF revenue projection (verify anchor) |
| lk-baseline-asrs-fy2026 | analyze | 1 | Baseline ASRS contribution FY26 (verify anchor) |
| lk-hur-construction-fy2025 | comparison | 1 | HURF construction vs maintenance FY25 (verify anchor) |
| lk-uhsc-arizona-health-fy2026 | lookup | 1 | UA Health Sciences GF FY26 (verify anchor) |
| lk-dps-historical-operating-fy2013 | historical | 1 | DPS FY13 operating budget (verify anchor) |
| lk-ema-military-affairs-fy2026 | analyze | 1 | DEMA FY26 (verify anchor) |
| lk-ins-insurance-dept-fy2025 | lookup | 1 | Insurance Dept FY25 (verify anchor) |
| lk-fis-game-and-fish-fy2025 | lookup | 1 | Game & Fish FY25 |
| lk-sos-secretary-of-state-fy2025 | lookup | 1 | Secretary of State FY25 (verify anchor) |
| lk-djc-juvenile-corrections-fy2025 | lookup | 1 | Juvenile Corrections FY25 (verify anchor) |
| lk-tou-tourism-fy2026 | lookup | 1 | Tourism FY26 |
| lk-vsc-veterans-services-fy2025 | lookup | 1 | Veterans' Services FY25 |
| lk-agr-horse-liaison-fy2025 | lookup | 1 | Agriculture horse-liaison cut FY25 |
| lk-dps-highway-patrol-fy2027 | lookup | 1 | Governor's FY27 DPS total |
| lk-gf-revenue-recent-trend | comparison | 1 | FY25→FY26 GF revenue growth |
| lk-esa-funding-formula-fy2026 | analyze | 1 | ESA funding formula base |
| lk-ahcccs-enrollment-history | analyze | 1 | AHCCCS enrollment history + GF driver |
| lk-nursing-board-operating-fy2025 | lookup | 1 | State Board of Nursing FY25 |
| lk-dor-revenue-operating-fy2025 | lookup | 1 | Dept of Revenue operating FY25 |

### Deep Research — `set: deep` — 3 queries
**Contract:** extremely broad scope over wide time spans; judged primarily. **Measures:** synthesis + citation discipline + worst-case cost. Each **must carry ≥1 key fact** (so it isn't a vacuous headline pass) and `judge_notes` name the correct source docs per temporal slice.

| id | shape | #facts | What it asks |
|---|---|---|---|
| cm-adc-3yr-dr | comparison | 2 | ADC across ~3 years |
| an-gf-structural-dr | analyze | 3 | General Fund structural balance/revenue analysis |
| an-taxcut-package-dr | analyze | 4 | A tax-cut package — broad multi-part analysis |

### Refusal — `set: refusal` — 5 queries
**Contract:** must correctly refuse; `should_refuse: true`, **0 key facts**. **Measures:** refusal discipline (a correct refusal is scored as correct on the refusal axis and is never in the headline). These probe corpus boundaries — wrong jurisdiction, other state, city/county, future FY.

| id | shape | What it asks (all to be refused) |
|---|---|---|
| rf-federal-budget | refusal | Federal VA appropriation (federal, out of scope) |
| rf-other-state | refusal | Nevada per-pupil K-12 (other state) |
| rf-city-budget | refusal | City of Tucson police overtime (local) |
| rf-future-budget | refusal | Governor's FY2029 executive budget (beyond corpus) |
| rf-county-budget | refusal | Maricopa County general fund (local) |

### Multi — `set: multi` — **0 (not yet authored)**
**Contract:** spans 2–3 narrow agencies × 2–3 fiscal years; each carries a hand-pinned `correct_response_docs` list. **Measures:** doc-type understanding (did it cite the Appropriations Report and not the Baseline?). This is the empty set Task 10 must author — the existing 35 were all single-fact/single-doc lookups, so none qualified as a genuine agency×year multi-lookup.

---

## What a score "pass" looks like, per set

- **Quick**: high `key_fact_rate`, ≥1 verified cite, **~1 retrieve call** (2+ is a smell), low tokens/turns. Refusal queries here: none.
- **Deep**: key-fact pass + correct source citations + judge's holistic grade; tokens/turns only meaningful when the whole question is answered.
- **Refusal**: `refusal_correct` = the agent refused (and didn't hallucinate a number). A refusal is correct on its own axis, excluded from the headline.
- **Multi** (once authored): `key_fact_rate` for correctness + `document_correctness` for doc-type + `unanswered` flag if no citation at all.

---

## The headline trend

`eval/results/over-time/metrics.jsonl` accumulates one row per scored run (with `queries_sha256`/`corpus_counts`/`profile`). Trend lines **split into segments at every query-set or corpus change**, so an edit to the YAML during tuning starts a new labeled segment instead of lying with a continuous line. Wall-clock is deliberately **not** a metric (network/machine-load dominated); tokens and turns are load-invariant and are what trends.
