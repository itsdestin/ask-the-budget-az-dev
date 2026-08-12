# Corpus Navigation — corpus map, spread retrieval, coverage metadata, expand

**Date:** 2026-08-12
**Status:** Approved design, pre-implementation
**Decisions:** N1–N10
**Goal:** answer ACCURACY. The Layer 2 post-backfill regression measured
`key_fact_rate` 0.66 with **74% of missed facts never retrieved in any
round**. More rounds of the same search would not have found them; the
candidate-pool composition and the model's blindness to the corpus's shape
are the targets. Reduced round trips are a welcome side effect, not the
gate.

## Problem

Four measured navigation failures, all from STATUS.md and the Layer 2
baselines:

1. **Edition monoculture.** "ahcccs appropriations report" can never
   surface FY2026: ~2,000 near-identical AHCCCS chunks span FY2005–2026
   and the RRF pool is capped at 20, so one edition's near-duplicates fill
   the pool before rerank starts. Measured: raising
   `RECENCY_BOOST_PER_YEAR` to 4.0 does not help — the right edition is
   not in the pool to be boosted. No ranking constant can fix a pool
   composition problem.
2. **The model cannot see the corpus's shape.** It does not know which
   editions/years/doc types exist (Approps back to FY2005, AFRs only
   FY2021–2025, one budget bill). It discovers gaps by getting weak
   results and retrying — wasted rounds, or worse, a confident answer
   from the wrong edition.
3. **Comparisons burn one retrieve per side.** The tool description says
   so explicitly. A 3-year comparison ran 4 retrieves / 41 chunks / 295 s
   in the Plan 4 dogfood.
4. **The model cannot tell "these results are all FY2026 because that is
   all there is" from "the pool cap hid the other years".** Nothing in
   the retrieve response reports the candidate distribution.

Constraint to respect throughout: input tokens are already the dominant
cost (83–138k per answer) and retrieval efficiency is 0.34–0.44 — two
thirds of retrieved chunks go unused. Every feature here must be
self-limiting on chunk volume.

## Decisions

### N1 — A corpus map is injected into the system prompt

A compact markdown table, one row per (publisher, document family):
years covered (ranges, with gaps named), document count. Built from
`store.documents.load_documents()` — the sidecar carries `doc_type`,
`fiscal_year`, `publisher` per document, so no LanceDB scan is needed.
Each corpus gets its own map (budget books/AFRs/etc.; fiscal notes get
session coverage and note count).

One guidance line accompanies it: *if the map shows no edition for a
year, say so — do not search repeatedly for material that does not
exist.*

Size budget: ~1–2k tokens, amortized to near zero by S22 prompt caching.

### N2 — The map is built by the caller, not by prompt.py

`harness/prompt.py` is deliberately import-light (stdlib +
`harness.constants`); it must not grow a LanceDB or store dependency.
New module `harness/corpus_map.py` owns the builder;
`build_system_prompt()` gains a `{{CORPUS_MAP}}` placeholder and a
`corpus_map: str | None` argument supplied by `session.py`. When the
caller supplies nothing (tests, degraded sidecar), a fallback sentence
renders — never a raw `{{CORPUS_MAP}}` and never a crashed conversation.

### N3 — The map is snapshotted per conversation; the S22 pin is amended

The S22 pinned property is "byte-identical prefix across steps, turns,
and conversations." A corpus-derived map changes when an ingest lands.
Resolution:

- The map string is captured **once at conversation creation** and held
  for the conversation's life. Within-conversation prefix identity — where
  the ~10× cache saving lives — is guaranteed unconditionally.
- Across conversations, the property becomes "identical while the
  sidecar stamp (`store.documents.sidecar_stamp()`) is unchanged." An
  ingest invalidating the office's shared prompt prefix is a real and
  correct cache miss, and it is rare.
- `tests/test_harness_prompt_caching.py` is amended to pin exactly that,
  and keeps its guard that no date/time ever enters the prefix.

### N4 — `spread` is a parameter on retrieve(), not a new tool

```json
"spread": {
  "by": "fiscal_year" | "doc_id",
  "groups": [2022, 2023, 2024, 2025, 2026],
  "per_group": 3
}
```

The model already knows retrieve(); a sixth tool schema is more surface
to misuse, and every retrieve affordance (filters, aliases, citations,
refusal) applies to spread results for free.

Limits, enforced at the tool boundary with actionable errors:
`groups` explicit and required, max 8; `per_group` 1–5, default 3;
**groups × per_group ≤ 24** (today's token envelope for one large
retrieve). `by=fiscal_year` groups are integers (same coercion as
`filters.fiscal_year` — the string-"2027" trap applies here too);
`by=doc_id` groups are doc_id strings.

### N5 — Spread pipeline: one embed, per-group legs, one batched rerank

In `retrieval/pipeline.py` (new code path alongside `retrieve()`, the
default path structurally untouched):

1. Embed the query once (embedding is group-independent).
2. Per group: run the BM25 + dense legs with the group value merged into
   the caller's filters; RRF-fuse per group with a small overfetch
   (≈2 × per_group, min 6 candidates per group).
3. **One** cross-encoder rerank batch over all groups' candidates —
   pool capped at ≈48 (~5 s worst case on the office CPU; cheaper than
   the 3–4 sequential retrieves it replaces).
4. Take the top `per_group` per group.
5. Apply the existing post-rerank penalties unchanged. Within a
   fiscal-year group recency is constant, so it cannot reorder; the
   agency penalty still applies. **Nothing here touches the three
   coupled constants** (`RECENCY_BOOST_PER_YEAR`, `MATCH_PENALTY`,
   `REFUSAL_THRESHOLD`), and spread introduces no bonus — the
   penalty-only invariant on `top_score` holds.

Response shape: the flat `chunks` array exactly as today (alias, doc
metadata, text — citable as normal; each chunk additionally carries its
`group` value), plus a `groups` summary array: per-group `top_score` and
returned count, so the model can see "FY2020's best hit is weak" rather
than inferring it. Overall `top_score` = max across groups; the refusal
comparison is unchanged.

### N6 — Spread calls are exempt from the first-call cap

A spread call consumes the first-call slot (it is a real first search)
but is not truncated to `FIRST_CALL_TOP_K_CAP`. Truncating a structured
per-group request to 5 flat chunks would break its contract and force
the extra round the feature exists to remove; the groups × per_group cap
already bounds it. Risk accepted with eyes open: Layer 2 watches
`input_tokens_mean` for first-call spread abuse, and the exemption is
reverted if it shows up.

### N7 — `year_coverage` metadata on every retrieve response

A histogram of candidate fiscal years counted over the **pre-fusion
candidate legs** (BM25 top-200 ∪ dense top-100, already in memory — zero
extra queries), NOT over the final pool: its entire job is to report
what the pool cap hid. Emitted as
`"year_coverage": {"2005": 41, "2024": 12, …}`; omitted when empty or
when every candidate lacks a fiscal year. The prompt describes it in one
line: approximate relevance signal; use it to decide whether to filter
or spread. This makes failure 4 self-correcting: the model *sees* "my
results are all FY2026 but matches exist back to FY2005".

### N8 — `expand(chunk_id, before, after)` — the cut line

A sixth tool: fetch up to 3 adjacent chunks each way in the same
document, ordered by (page, chunk sequence). Results carry aliases and
the full retrieve chunk shape, so they are citable and enter the
attested-linking pool exactly like retrieve results (the linking pool
reads tool messages in history; expand results must be
shape-indistinguishable from retrieve chunks there). Targets the
"table continues on the next page" / cut-boundary failure — real, but
not where the 74%-never-retrieved misses live.

**This is the explicit cut line: N1–N7 ship without N8 if a smaller
change is wanted.** If dogfooding shows the model wanting whole-document
navigation, a `browse_document` outline tool is the follow-on — not
built now.

### N9 — System prompt guidance

New/edited sections, with `{{#when corpus=…}}` variants where the
corpora differ: the corpus map block (`{{CORPUS_MAP}}`), when to use
spread (multi-year comparisons, "across years" questions,
"newest edition of X" questions), how to read `year_coverage`, and (if
N8 ships) when to expand instead of re-searching. Guidance is additive;
the progressive-retrieval and refusal sections are unchanged.

### N10 — Additive by design; no default-behavior change

The pending work in `PROMPT-retrieval-accuracy-regression.md`
(glm-vs-deepseek head-to-head; year-inference-as-default-filter as the
highest-leverage retrieval candidate) is deliberately not pre-empted:
spread is opt-in, the map and histogram are metadata, and the default
retrieve() path is structurally untouched. Layer 2 comparisons for this
work use the same model as the 2026-08-02 baseline (glm-5.2) so the
numbers stay comparable.

## Not doing (considered and rejected/deferred)

- **`retrieve_batch` (N queries, one round trip).** A latency feature; it
  puts nothing in the pool that sequential retrieves could not. Spread
  covers the dominant multi-query case (same question, different years).
  Revisit if latency becomes the goal.
- **`browse_document` outline tool.** Deferred until observed demand
  (N8).
- **`find_figure` (search by dollar value).** Creative, machinery exists
  in `citation/`, but no measured miss class demands it yet.
- **Raising the RRF pool cap or re-tuning recency for edition
  diversity.** Already measured to fail (STATUS.md query-understanding
  follow-ups); spread is the structural fix.

## Error handling

- Malformed `spread` arguments come back as `ok:false` tool errors with
  the valid shape spelled out, per the existing coercion discipline in
  `harness/tools.py` — never an exception, never a silent ignore.
- A group that matches nothing returns an empty group entry with count 0
  in the `groups` summary — visible, not silently dropped (a filter that
  invisibly is not applied is the haunted-tool failure).
- A missing/corrupt sidecar degrades the corpus map to the fallback
  sentence; conversations proceed.
- `expand` on an unknown chunk_id or a document boundary returns what
  exists with an explanatory field, not an error loop.

## Testing & validation

**pytest (mechanism — no real LanceDB, no ONNX weights, per convention):**
map builder (ranges, gaps, empty corpus, both corpora), `{{CORPUS_MAP}}`
wiring + fallback, S22 test amended to stamp-conditioned identity (and
its no-date guard kept), spread argument coercion and every cap,
per-group grouping correctness against fake search legs, per-group
overfetch and single-rerank-batch behavior, alias minting for
spread/expand chunks, first-call-cap exemption and slot consumption,
`year_coverage` counting from the legs, expand ordering and boundary
behavior, and a guard that spread cannot inflate `top_score` beyond the
best single-group score (penalty-only invariant).

**Layer 1 eval** (required — `retrieval/` is touched): expect numbers
identical to the current baseline, because spread is opt-in and
`year_coverage` is metadata. Any movement on the default path is a stop
signal, not noise. Commit results alongside the change.

**Layer 2, on the keyed machine** (required — `harness/` and
`harness/system-prompt.md` are touched): smoke run vs the 2026-08-02
baseline (`eval/results/agent/2026-08-02T0900Z-0b08221`), same model.
Expected directions: `key_fact_rate` ↑ (the gate), retrieves/answer ↓ on
comparison shapes; watched for harm: `input_tokens_mean` and
`retrieval_efficiency` (the token-blowup failure mode of N6), plus
`marker_coverage_mean` / `tag_accuracy_mean` (spread and expand chunks
must tag and verify like any other). Full 31-query run + judge before
merge, compare report committed.

## Gates

- **G-N1:** Layer 1 numbers unchanged on the default path.
- **G-N2:** Layer 2 full run shows `key_fact_rate` not worse than
  baseline and no regression in citation metrics; `input_tokens_mean`
  within ~15% of baseline unless `key_fact_rate` improved to justify it.
- **G-N3:** the S22 caching property holds in the amended form
  (byte-identical within a conversation; identical across conversations
  at a fixed sidecar stamp; no date in the prefix).
