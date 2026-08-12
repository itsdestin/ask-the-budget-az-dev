# Corpus Navigation — corpus map, spread retrieval, coverage metadata, expand

**Date:** 2026-08-12 (amended same day after external review — see the
review-fixes note at the bottom)
**Status:** Approved design, pre-implementation
**Decisions:** N1–N11 (N8 removed — expand deferred)
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

**Family comes from `source_url`, never from doc_id or doc_type.**
`doc_type` cannot express family (`detailed-list-pdf` / `topic-pdf`
occur under both JLBC books) and 21 doc_ids are known to encode the
WRONG family — the `make_doc_id` collision class that
`app/book_sections.py` exists to read around. The map builder reuses
that source_url rule; since `harness/` should not import `app/`, the
parser is hoisted to a shared module under `store/` and
`app/book_sections.py` re-imports it. A map built from doc_id would
claim editions that do not exist, and the map's own guidance line ("if
the map shows no edition, say so") makes a false edition claim the
harmful direction.

**Fiscal-note coverage is by fiscal year, not legislative session.**
Verified: 0 of 2,104 note sidecar entries carry a session field; all
2,104 carry an integer `fiscal_year`. Coverage by FY keeps the map on
one data source with one failure mode (the sidecar), rather than adding
a `fiscal-notes-directory.json` read with its own fallback story.

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
4. Apply the agency match penalty over each group's FULL candidate set,
   **before** the per-group trim. Order is load-bearing: the default
   path's own WHY comment (`pipeline.py`, at the rerank call) records
   that a post-rerank adjustment can only reorder chunks it can see —
   penalising after the trim would mean a matching chunk at position
   per_group+1 can never be promoted into the group's results.
5. Take the top `per_group` per group.

**Recency is never applied on the spread path, on either axis.** This
is the existing skip rule extended, not a new idea: the default path
already skips recency whenever a year filter is active ("inside a set
the analyst already narrowed, preferring newer is fighting the
instruction"), and every `by=fiscal_year` group IS a year filter. A
`by=doc_id` group names an explicit document, where the same reasoning
holds. Two consequences, stated so nobody rediscovers them:

- Per-group `top_score`s in the summary are rerank + agency-penalty
  scores only, comparable ACROSS groups. Letting recency in would let
  an anchor-relative penalty (~0.85/yr × 16 yr ≈ 13.6 logits — larger
  than the whole ±10 logit range) tell the model "FY2010 has nothing"
  when FY2010 holds a perfect hit.
- Refusal interaction: recency is a penalty, so skipping it can only
  RAISE `top_score` — spread refuses no more than the default path and
  possibly less. This mirrors what an explicit year-filtered retrieve
  already does against the same `REFUSAL_THRESHOLD`, so it is not a new
  exposure class, but it is a deliberate one.

**Nothing here touches the three coupled constants**
(`RECENCY_BOOST_PER_YEAR`, `MATCH_PENALTY`, `REFUSAL_THRESHOLD`), and
spread introduces no bonus — the penalty-only invariant on `top_score`
holds.

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
when every candidate lacks a fiscal year.

**The histogram is post-filter, and both the prompt and the response
must say which filters were in force.** The legs already carry the
caller's filters, the S21 inferred-year filter, and any inferred
doc-type filter — so on a year-named query the histogram structurally
cannot show other years, and that is fine (the target failure is
no-year queries) but must not be over-trusted. Two requirements:

- The prompt's one-line description reads "distribution of candidate
  years WITHIN the current filters — approximate; use it to decide
  whether to filter or spread."
- The response says which filters were in force: N11 echoes the
  inferred-filter fields alongside this histogram. Without them the
  model cannot interpret the numbers — it cannot even tell an inferred
  doc-type filter fired.

This makes failure 4 self-correcting: the model *sees* "my results are
all FY2026 but matches exist back to FY2005".

### N8 — REMOVED: `expand` is deferred to observed demand

The first draft included an `expand(chunk_id, before, after)` tool
(adjacent same-doc chunks, the "table continues on the next page"
failure) marked as the cut line. It is now cut, before implementation,
for the reason the review's finding #1 exposed: its true integration
cost is materially larger than drafted. The chunk-pool consumers
dispatch on the literal tool name `"retrieve"` — `session.py`
`_record_tool_call` (~1900), `_retrieved_chunk_map` (~2007),
`_this_turn_chunk_ids` (~2041), plus webapp chip-metadata consumers —
so shipping expand means teaching every name-keyed site about a second
source tool and proving it end-to-end, or a figure from an expanded
chunk renders as an unverifiable red chip on a correct answer (the
2026-08-11 defect class). That cost buys a failure mode that is
explicitly NOT where the 74%-never-retrieved misses live.

Ship N1–N7, run the Layer 2 comparison, and let dogfooding demand
expand — the same logic that already deferred `browse_document`,
applied one item earlier. The consumer-checklist and end-to-end
acceptance requirements recorded above are the entry fee for whoever
picks it up.

### N11 — Inferred filters are echoed in every retrieve response

`RetrievalResult` already computes `inferred_doc_types`,
`inferred_agencies`, and `dropped_filters`; `harness/tools.py` echoes
only `inferred_fiscal_years` and drops the rest. The response now
carries all of them, present only when non-empty, matching the existing
style:

- `inferred_doc_types` — a HARD filter that was guessed from the query
  text. Today a doc-type guess that narrows the whole search is
  invisible to the model — the "haunted tool" failure the pipeline's
  own comments name (`RetrievalResult` docstring: "a filter that is
  invisibly not applied is the kind of thing that makes a tool feel
  haunted" — and an invisibly APPLIED one is worse).
- `dropped_filters` — the guessed filter that matched nothing and was
  abandoned for an unfiltered second search (spec Q3). Without it the
  model cannot distinguish "unfiltered because nothing was guessed"
  from "unfiltered because the guess found nothing".
- `inferred_agencies` — surfaced with wording that marks it a ranking
  PREFERENCE, never a filter (the docstring's own distinction; a UI or
  model describing it as a filter would be wrong).

This rides the same tool-response edit as N7's `year_coverage` and
completes the instrument N7 starts: a coverage histogram is
half-readable if the model does not know which filters produced it. It
is also the model-facing half of the follow-up STATUS.md already
tracks for the UI ("the UI does not yet show what was inferred").

### N9 — System prompt guidance

New/edited sections, with `{{#when corpus=…}}` variants where the
corpora differ: the corpus map block (`{{CORPUS_MAP}}`), when to use
spread (multi-year comparisons, "across years" questions,
"newest edition of X" questions), and how to read `year_coverage` plus
the N11 inferred-filter fields. Guidance is additive; the
progressive-retrieval and refusal sections are unchanged.

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
- **`expand` (adjacent-chunk tool).** Cut before implementation — see
  N8 for the full record (name-keyed pool integration cost vs. a
  benefit outside the measured miss class).
- **`browse_document` outline tool.** Deferred until observed demand,
  same logic as expand.
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

## Testing & validation

**pytest (mechanism — no real LanceDB, no ONNX weights, per convention):**
map builder (ranges, gaps, empty corpus, both corpora, and the
source_url family rule — including at least one of the 21 wrong-doc_id
sections resolving to its true family), `{{CORPUS_MAP}}` wiring +
fallback, S22 test amended to stamp-conditioned identity (and its
no-date guard kept), spread argument coercion and every cap, per-group
grouping correctness against fake search legs, per-group overfetch and
single-rerank-batch behavior, **agency penalty applied before the
per-group trim** (a matching chunk at position per_group+1 must be able
to enter the results — the test fails if the order is swapped),
**recency never applied on the spread path** (both axes; a
by=doc_id spread over old documents must show undepressed group
top_scores), alias minting for spread chunks, first-call-cap
exemption and slot consumption, `year_coverage` counting from the legs,
the N11 inference fields (`inferred_doc_types`, `dropped_filters`,
`inferred_agencies`) reaching the tool response — present when
non-empty, absent otherwise — and a guard that spread cannot inflate
`top_score` beyond the best single-group score (penalty-only
invariant).

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
`marker_coverage_mean` / `tag_accuracy_mean` (spread chunks must tag
and verify like any other). Full 31-query run + judge before merge,
compare report committed.

## Gates

- **G-N1:** Layer 1 numbers unchanged on the default path.
- **G-N2:** Layer 2 full run shows `key_fact_rate` not worse than
  baseline and no regression in citation metrics; `input_tokens_mean`
  within ~15% of baseline unless `key_fact_rate` improved to justify it.
- **G-N3:** the S22 caching property holds in the amended form
  (byte-identical within a conversation; identical across conversations
  at a fixed sidecar stamp; no date in the prefix).

## Review fixes (2026-08-12)

An external review of the first draft found six defects; all six were
verified against the code and accepted. The material changes:

1. N8 claimed shape-compatibility was the linking-pool mechanism; the
   real mechanism is tool-NAME dispatch at three `session.py` sites
   (plus webapp consumers). N8 now carries the consumer checklist and
   gate G-N4.
2. N5 ordered penalties AFTER the per-group trim — inverting the
   default path's own recorded lesson. Reordered: penalty before trim.
3. Recency across groups would have corrupted the `groups` summary by
   up to ~13.6 logits. Spread now never applies recency, with the
   refusal interaction stated.
4. "Document family" is not a sidecar field and doc_id is wrong for 21
   documents; the map builder now mandates the `book_sections`
   source_url rule, hoisted to `store/`.
5. Fiscal-note "session coverage" does not exist in the sidecar
   (verified: 0 of 2,104); note coverage is by fiscal year.
6. The `year_coverage` histogram is post-filter; the description now
   says so, and the response must surface `inferred_doc_types`,
   `dropped_filters`, and `inferred_agencies` (preference-worded),
   which the tool layer currently computes and drops.

## Second amendment (2026-08-12, same day)

Two scope changes on Destin's direction, after the review fixes:

- **The inferred-filter echo is promoted from an N7 sub-bullet to its
  own decision, N11.** It stands alone: it completes the instrument N7
  starts, rides the same tool-response edit, and is the model-facing
  half of the UI follow-up STATUS.md already tracks.
- **N8 (`expand`) is REMOVED, not just cut-lined.** Finding #1 raised
  its real integration cost (every name-keyed consumer of retrieve
  payloads, both sides of the wire) while its benefit sits outside the
  measured miss class. Ship N1–N7 + N11, run the Layer 2 comparison,
  and let dogfooding demand it. This supersedes review-fix note #1's
  "N8 now carries the consumer checklist and gate G-N4" — G-N4 is gone
  with it; the checklist survives inside N8's record as the entry fee
  for whoever revives it.
