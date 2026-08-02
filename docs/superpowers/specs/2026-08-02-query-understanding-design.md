# Query understanding — agency, document type and JLBC shorthand

**Status:** approved in brainstorming 2026-08-02. Not yet planned or built.

**Goal.** An analyst typing the shorthand they actually use — `doc baseline`,
`dema ar`, `ahcccs 27ar` — gets that agency's documents, of that type, newest
first.

**Not a recency problem.** The recency ranking was re-calibrated the same day
(weight 0.85 / threshold 1.46) and orders results correctly *wherever
retrieval returns the right documents*. This spec is about the cases where it
does not.

---

## The evidence this rests on

Six shorthand queries, run against the finished FY2005–2027 corpus on
2026-08-02:

| query | chronological? | right documents? |
|---|---|---|
| `ahcccs baseline` | yes | yes |
| `ahcccs 27ar` | yes | **no** — all *baselines*; `27ar` read as neither FY2027 nor Approps |
| `ahcccs 2027 approps report` | yes (year filter fired) | mixed types |
| `ahcccs appropriations report` | roughly | **no** — #1 a Governor's budget, #3 an AFR |
| `dema ar` | no | **no** — mostly Attorney General |
| `doc baseline` | no | **no** — zero Corrections documents |

**Three of six return largely wrong documents.** That is worth more than any
ordering refinement.

### Root cause 1 — the filters exist and nothing populates them

`RetrievalRequest` already carries `fiscal_year`, `doc_type`, `publisher`,
`agency_canonical_id`, `fund_canonical_id`, `fund_mentions`, `is_table`. All of
them reach LanceDB through `to_filters()` → `search_lance.py`. **62,251 of
77,574 chunks (80%) carry an agency stamp** (`agency:adc`, `agency:ema`, …).

Only `fiscal_year` has a query-side parser (`retrieval/query_year.py`). So
today only AI Mode can use the others, because the model can pass filters
explicitly. The zero-inference search box cannot.

Measured directly — same query, filter applied by hand:

```
'doc baseline'  as typed     -> GOVERNOR FY2027, FY2015 detailed list, FY2026 exec budget…
'doc baseline'  + agency:adc -> Corrections FY2025, 2025, 2024, 2022, 2023, 2021
```

### Root cause 2 — the catalog barely knows any abbreviations

**103 of 157 agencies (66%) carry only their canonical name and no alias at
all.**

```
adc  "Corrections, State Department of"              variants: [canonical only]
ema  "Emergency and Military Affairs, Department of" variants: [canonical only]
```

That is why `corrections baseline` works and `doc baseline` does not. It is
not only an abbreviation problem: *"emergency and military affairs
appropriations report"* — the full official name — returns **Agriculture** at
ranks 1, 2, 3 and 5.

One data defect found on the way: `agency:des` carries the variant
`'pp y, Economic Security, Department of'`, which is PDF-extraction garbage
that reached the catalog. Fix it here.

---

## Decisions

### Q1 — Three parsers, mirroring `query_year.py`

- **`retrieval/query_agency.py`** — resolve agencies from the query text.
- **`retrieval/query_doc_type.py`** — map natural phrases onto the ten real
  `doc_type` values (`approps-per-agency`, `baseline-per-agency`,
  `detailed-list-pdf`, `governors-budget`, `s-pdf`, `afr`, `bd-pdf`,
  `topic-pdf`, `bh-pdf`, `budget-bill`).
- **`retrieval/query_year.py`** — extended, not replaced.

**The agency matcher REUSES `chunking/entity_stamper.py`.** That module already
resolves agency names against the catalog with rapidfuzz `token_set_ratio` and
a documented ≥85 floor, and it is the code that *stamped* the chunks in the
first place. Using the same resolver on both sides makes query and corpus agree
by construction — the property S23 established for quote normalization, where
two independent implementations were the risk worth engineering away.

### Q2 — Confidence decides filter versus boost

| match | strength |
|---|---|
| canonical name, or a multi-word variant | **hard filter** |
| acronym matching exactly one agency, not stoplisted | **hard filter** |
| fuzzy match, or several agencies match, or a stoplisted alias | **soft boost** |

**Why not always a hard filter**, symmetric with the year parser: a year token
is unambiguous, an agency acronym is not. `doc`, `ar`, `pp` are ordinary words.
A mis-resolution under a hard filter returns an empty page for a query the
analyst typed in good faith.

**Why not always a boost:** a boost competes with reranker scores rather than
overriding them, and would not reliably clear the Attorney General results out
of a DEMA query.

**The stoplist** is a small, hand-maintained set of aliases that are also
ordinary English words — `doc` is the motivating case. A stoplisted alias still
*matches*; it just earns a boost instead of a filter. Accepted cost: it is
maintained by hand and will need occasional additions.

### Q3 — A hard filter that returns nothing retries unfiltered

**Non-negotiable.** An analyst who typed something reasonable must never get a
blank page because the parser was confidently wrong. When a hard filter yields
zero results, retrieval retries without it.

**And says so.** The response carries what was inferred and whether it was
applied or dropped, so the UI can show "showing all documents — no Corrections
results matched" rather than silently pretending no filter existed. A filter
that is invisibly not applied is the kind of thing that makes a tool feel
haunted.

### Q4 — The boost mirrors `apply_recency_boost` exactly

Applied post-rerank at the same seam (`retrieval/pipeline.py:332`), with the
same shape: a **penalty on non-matching chunks**, never a bonus on matching
ones, so nothing is scored above what the reranker gave it.

**This is not stylistic.** `top_score` after boosting is what
`REFUSAL_THRESHOLD` is compared against. A bonus-shaped boost would inflate
`top_score` and silently weaken refusal — the exact coupling that forced
`REFUSAL_THRESHOLD` from 1.04 to 1.46 hours earlier. Its weight must be
calibrated in the same change, and the existing
`test_the_shipped_weight_and_refusal_threshold_move_together` guard extended to
cover it.

### Q5 — JLBC shorthand feeds both parsers

`27ar` → FY2027 **and** `approps-per-agency`. `26baseline` → FY2026 **and**
`baseline-per-agency`. One tokenizer addition in `query_year.py`, consumed by
the year parser and the doc-type parser.

This is the form an analyst who lives in `azjlbc.gov/26AR/508.pdf` types
naturally, and it is already the corpus's own URL convention.

### Q6 — Alias data is drafted, then reviewed before it ships

Two sources, kept separate because they carry different risk:

1. **Derived, no review needed:** every agency gains its JLBC slug as a variant
   (`adc`, `ema`, `dps`). Mechanical, nothing invented.
2. **Drafted, REVIEW REQUIRED:** colloquial acronyms (`DOC`, `DEMA`, `ADOA`)
   generated from canonical names, each marked with confidence, handed to
   Destin as a checklist.

**Nothing drafted reaches the hard-filter path unreviewed.** A missing alias
merely fails to help; a *wrong* alias under a hard filter sends a query
confidently to the wrong agency, which is worse than the problem being solved.

---

## Testing

The six queries above become the fixture, each with its expected agency and
doc type.

Plus:

- A stoplisted alias produces a boost, not a filter (`doc baseline`).
- A hard filter returning zero results retries unfiltered, and the response
  records that it was dropped.
- `27ar` yields both FY2027 and the approps doc type.
- An acronym matching two agencies falls back to a boost.
- Query and corpus resolution agree: an agency resolved from a query string
  matches the `agency_canonical_ids` stamped on that agency's own chunks.
- The catalog's derived slug variants exist for all 157 agencies.
- `agency:des` no longer carries the `'pp y, …'` garbage variant.

**Eval is mandatory, not optional.** This changes `retrieval/`, so
`eval/run_eval.py` runs, and shorthand queries go into `eval/queries.yaml` so
the gain is measured rather than asserted. Any boost weight is calibrated and
`REFUSAL_THRESHOLD` re-checked in the same change.

---

## Out of scope

- **Fund resolution.** `fund_canonical_id` has exactly the same gap and the
  same fix shape. Deliberately deferred so this stays one reviewable change.
- **The fiscal-notes corpus.** Notes are not agency-stamped the same way.
- **`publisher` and `is_table`.** No evidence an analyst types these.

## Follow-ups this creates

- The UI needs somewhere to show what was inferred and whether it was applied
  (Q3). Coordinate with the in-flight AI Mode UI redesign and Budget Documents
  page rather than inventing a second pattern.
- The stoplist is hand-maintained and will drift; it should be reviewed
  whenever aliases are added.
