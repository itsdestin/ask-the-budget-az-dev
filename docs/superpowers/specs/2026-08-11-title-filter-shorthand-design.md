# Budget Documents — analyst shorthand in the title filter

**Date:** 2026-08-11
**Status:** Approved 2026-08-11 — one flagged assumption, see O1.
**Branch:** `budget-docs-browse-page` (follow-on work; the content-search feature on that branch is complete and reviewed)
**Amends:** `2026-08-10-budget-documents-content-search-design.md` — that spec defined the two-mode search box; this one changes what title mode matches. Content mode, escalation timing and the source drawer are untouched.

## Why

Typing `dema` into the Budget Documents filter box today returns **nothing**. So does `ema`. Both are how an analyst actually refers to the Department of Emergency and Military Affairs, and both are already reviewed vocabulary elsewhere in this repo — `dema` is a curated alias in `samples/entity-catalog.yaml` and `ema` is the agency's JLBC URL slug.

Same for `26ar`. That string is a literal directory name on azjlbc.gov (`azjlbc.gov/26AR/508.pdf`), `retrieval/query_year.py::parse_jlbc_shorthand` already parses it, and the filter box has never heard of it.

Measured against the live corpus (5,330 documents):

| typed | title matches today |
|---|---|
| `dema` | **0** |
| `ema` | **0** |
| `br` | 6 |
| `afr` | 21 |
| `exec` | 42 |
| `ar` | 3,675 |

The knowledge exists. It just never reaches the browser, because title filtering runs client-side over a listing payload that carries no agency and no shorthand.

## Non-goals

- **Ranking.** The filter box matches or does not match. It has no scores, and this spec introduces none.
- **Changing retrieval's behaviour on existing forms.** `ar` and `baseline` keep parsing exactly as they do.
- **A query language.** No `type:` prefixes, no quoting, no operators.
- **Fiscal Notes.** `queryHit` and `corpusDocuments` are used only by `webapp/src/pages/Search.tsx` (verified: `grep -rn "corpusDocuments\|queryHit" webapp/src` returns hits in `api.ts` and `Search.tsx` only). That page has its own path and is untouched.

## Decisions

### D1 — Shorthand matches silently; the rail dropdowns do not move

Typing `26ar dema` narrows the results. The Document Type and Fiscal Year dropdowns keep reading "Any type / Any year".

**Rejected:** having shorthand drive the rail dropdowns so the reader can see and undo what was understood. It is more discoverable, but it lets the box mutate state outside itself, and it makes every keystroke a potential filter change. **Rejected:** moving title search to the server so it can reuse the real parser — that reintroduces the per-keystroke network call the browse rewrite deliberately removed.

**Consequence, accepted:** while a shorthand token is active the rail describes the rail's own filters, not everything narrowing the list. The status line still names the query (`N reports in <scope>, matching "26ar"`), so the page never claims the result set is unfiltered.

### D2 — Every whitespace-separated word must match (all-words, not phrase)

`queryHit` is today a single case-insensitive substring test over the whole query. `26ar dema` cannot match under it at any vocabulary — it is not a substring of anything.

So the query splits on whitespace and **every** token must match something. This is forced by the feature, not chosen.

**Consequence, accepted:** existing phrase searches widen slightly. "annual financial" today requires that exact string; afterwards both words must appear but need not be adjacent.

**Consequence, welcome:** all-words matching is what makes ambiguity safe. In retrieval a stray `for` was dangerous because one term could hard-filter 13 of 47 eval queries onto Forestry. Here a token can only widen what *it* matches — "funding for education" still requires `funding` and `education` to hit something, which Forestry titles do not. The exposure collapses to single-word queries.

### D3 — Extra terms match on exact token equality; title and publisher stay substring

| Field | Rule | Why |
|---|---|---|
| Title | substring (unchanged) | preserves partial typing — `ahccc` still finds AHCCCS |
| Publisher | substring (unchanged, see D8) | unchanged behaviour |
| Extra terms | **exact equality** | `ar` as a substring would match "arizona" in nearly every title |

Everything is compared lowercased, on both sides. Terms are stored lowercase and the query is lowercased before splitting, so `26AR DEMA` and `26ar dema` behave identically — which matters, because JLBC's own URLs spell it `/26AR/`.

Note that title matching staying substring means `ar` still finds its 3,675 titles *and* now the 2,795 Appropriations Reports. Exact-equality governs the new terms only; it does not narrow anything that works today.

### D4 — The terms are attached server-side, by `/api/corpus/documents`

Each document in the listing gains a short list of extra search terms. The client's matcher stays dumb — tokens in, boolean out — and every piece of judgement (which agency, which aliases survive suppression, which shorthand form) is computed once, server-side, next to the data that defines it.

**Rejected:** a second endpoint serving the alias catalog plus a client-side parser. It duplicates the shorthand rule in TypeScript, and two implementations of one convention drift. This branch already shipped that exact bug class once, in the doc-type slug map.

**Cost:** the listing is 1,228,842 bytes for 5,330 documents. This adds roughly 40–60 KB.

### D5 — A document's agency comes from the trailing segment of its `doc_id`

`jlbc-approps-fy2005-ema` → `ema`, matched against the 157 known catalog slugs.

Measured on the live corpus: **4,321 of 4,674** per-agency documents (92%) resolve this way. Also matching titles against canonical names rescues only 60 more (93% combined), which does not earn a second code path.

The 293 that resolve by neither are FY2005–2012 sub-unit pages JLBC published that never got a catalog entry — `adeassis`, `adeboe`, `axsacute`. They lose nothing: their titles are the slug uppercased ("ADEASSIS — FY 2005 Appropriations Report"), so typing the slug already finds them by title.

The 656 non-per-agency documents (AFRs, Executive Budgets, Budget Bills, and the five raw-slug types) get a shorthand form where one applies and no agency terms.

### D6 — Suppression is reused from retrieval, and applies ONLY to the new terms

`retrieval/query_agency.py` already decides which acronyms may not resolve to an agency, each entry measured against 247,607 tokens of real Arizona budget prose:

- `SUPPRESSED_ALIASES = {tax, for, ban}` — never become an alias at all
- `AMBIGUOUS_ALIASES = {doc, ar, afr, des, pp, per, gov, colleges, art, bar, bat, den, dot, lot, opt, pod}` — demoted to a ranking boost in retrieval
- `AMBIGUOUS_AGENCIES = {agency:gov}` — demoted across every tier

A filter box has no ranking, so "demoted to a boost" has no analogue here: a term either matches or it does not. Both lists therefore **exclude** — those strings do not become agency terms.

**This applies only to the terms added by this spec.** It must never filter the existing title or publisher substring match. Typing `insurance` still finds "Insurance, Department of" by its title exactly as it does today. `AMBIGUOUS_PHRASES = {insurance}` is deliberately **not** consulted, because it governs name matching in retrieval and honouring it here would *remove* matching that currently works. This change is purely additive to what the box already finds.

### D7 — A small reviewed carve-out: `dot` and `doc`

The suppression lists were measured against document *prose*, where "dot" and "doc" are ordinary words. They were not measured against what someone types into a box labelled "Agency or keyword", where `dot` is about as unambiguous as `dema`.

So `dot` (Transportation) and `doc` (Corrections) are carved out and **do** resolve to their agencies in the filter box.

The carve-out is an explicit, named, reviewed set — not a policy. Every other entry on both lists stays suppressed. The point is that the divergence from retrieval is deliberate and documented in one place rather than silent.

### D8 — Publisher codes match as well as labels

`publisherLabel()` maps `governor` → "OSPB" and `agao` → "GAO", and only the label is searched today, so typing `governor` matches nothing. Both the stored code and the display label become matchable. Costs nothing, removes a dead end.

### D9 — The shorthand vocabulary

`_SHORTHAND_DOC_TYPE` in `retrieval/query_year.py` currently holds exactly `{"ar": "approps-per-agency", "baseline": "baseline-per-agency"}`. It gains three entries:

| form | doc_type | source |
|---|---|---|
| `ar` | `approps-per-agency` | JLBC URL convention (existing) |
| `baseline` | `baseline-per-agency` | JLBC URL convention (existing) |
| `br` | `baseline-per-agency` | **new** — Destin, 2026-08-11 |
| `afr` | `afr` | **new** |
| `exec` | `governors-budget` | **new** |

**No form for `budget-bill`** (Destin, 2026-08-11) and none for the five raw-slug types (`s-pdf`, `bd-pdf`, `bh-pdf`, `topic-pdf`, `detailed-list-pdf`).

`afr` and `ar` are on `AMBIGUOUS_ALIASES` precisely *because* they collide with these document types — that is the collision those entries were written about. Suppressing them as agency terms (D6) while activating them as type shorthand is the coherent reading, not a conflict.

**Accepted risk: `exec` fires on ordinary prose. Destin, 2026-08-11.**

**Mechanism (shared by every form):** the shorthand regex (`_JLBC_SHORTHAND` in `retrieval/query_year.py`) allows an optional space between the two digits and the type word, and ends the type word with a `(?![\w])` lookahead rather than a word boundary — so anything that isn't a following word character closes the match, including a hyphen. `br` and `afr` share this exactly: "table 26 br funding" parses as a FY2026 baseline filter and "line 26 afr adjustments" parses as a FY2026 AFR filter, hard-filtering both queries just as `exec` does below. (Verified against this checkout, 2026-08-11.)

**Aggravating factor (unique to `exec`):** `exec` is a common standalone abbreviation in ordinary prose ("exec summary", "exec sessions", "exec orders"), where `br` and `afr` are not. That is what makes `exec` fire so much more *often* than the other two — not what makes it fire at all. These all parse as a FY-and-doc-type pair and **hard-filter the query to `governors-budget`**:

- "page 26 exec summary"
- "the committee held 26 exec sessions"
- "26 exec orders issued last year"
- "in 26 exec-level positions" — the trailing hyphen satisfies `(?![\w])` the same way a space or end-of-string would; no English-prefix collision needed here, just the shared mechanism above

The existing `_YEAR_LOOKALIKE_PREFIX` guard cannot help: it blocks citation designators ("chapter", "HB", "section") before the digits, which is a different problem — confirmed "chapter 26 exec" correctly does not parse. Neither does "26 executive summary": the lookahead fails inside "executive" because "u" (the next character after "exec") is a word character, so the regex only ever matches the standalone token, not an embedded prefix. (Both verified against this checkout, 2026-08-11.)

Found by review after the eval had already passed, because the 44-query eval set contains no such phrasing. The narrowing that was offered and declined was to require no space for `exec` specifically (`26exec` parses, `26 exec` does not), which would have killed every reproduced case while keeping the form.

**The failure mode is a wrong answer, not a missing one** — a question about executive sessions silently answered from the Governor's Executive Budget. That is the harder kind to notice, so it is recorded here rather than left in a review thread. Revisit if anyone reports a question being answered from the wrong document.

### D10 — Extending the map changes retrieval, and pays the eval gate

`_SHORTHAND_DOC_TYPE` has one other consumer, `retrieval/query_doc_type.py:160`, so extending it teaches the new forms to **questions and AI Mode too**, not only the filter box. That is the desired outcome: one vocabulary, so the box and the assistant cannot disagree about what `26afr` means.

It is a change to `retrieval/`, so per CLAUDE.md the eval runs: `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`), with `eval/results/<...>.{json,md}` committed alongside the diff. This is the 60-second recall eval, **not** the Layer 2 agent eval that spends money.

`_SHORTHAND_MIN_YEAR = 2000` and the existing `_YEAR_LOOKALIKE_PREFIX` guard are unchanged, so "chapter 26 ar" still does not parse as a year.

### D11 — Bare type shorthand filters too

`br` alone matches every baseline; `afr` alone every Annual Financial Report; `exec` alone every Executive Budget; `ar` alone every Appropriations Report.

`ar` alone returning ~2,795 documents sounds alarming and is not a regression: it already substring-matches **3,675** titles today via "Arizona" / "Appropriations" / "Year". The results also render as one card per report family per year, not 2,795 rows.

**Rejected:** year-prefixed forms only, and a special case exempting `ar`. Both were declined (Destin, 2026-08-11) — the first loses "pick 2026 in the rail, type `br`", the second is an exception to explain for a case that turns out not to be a real cliff.

Bare type is a **filter-box** behaviour: it needs no retrieval change, because it is a term attached to a document, not a parse of a year+type pair. Documents carry both forms — a FY2026 baseline gets `br`, `baseline` and `26br`, `26baseline`.

## Data flow

```
samples/entity-catalog.yaml ──┐
  (157 agencies: slug,        │
   10 reviewed aliases)       │
                              ├──> app/routes/corpus.py
retrieval/query_agency.py ────┤      per document:
  (suppression lists)         │        agency  = doc_id trailing segment ∩ known slugs
                              │        terms   = {slug} ∪ aliases  − suppressed + carve-out
retrieval/query_year.py ──────┘                ∪ {type form, NN+type form}
  (_SHORTHAND_DOC_TYPE)              │
                                     ▼
                          GET /api/corpus/documents
                            [{ …, terms: string[] }]
                                     │
                                     ▼
                       webapp/src/pages/Search.tsx :: queryHit
                         every token must match:
                           title substring | publisher substring | terms exact
```

## Consequences

1. **Escalation fires less often.** `dema` today returns zero titles and escalates to content search; afterwards it returns 38 documents and does not. Intended — the request was for the acronym to filter — but an acronym that gives passages today gives a document list tomorrow.
2. **Existing phrase searches widen** (D2).
3. **Retrieval and AI Mode learn `br`, `afr`, `exec`** (D10). The eval is the instrument that catches a misfire on real prose.
4. **8% of per-agency documents get no agency terms** (D5), and keep working via title.
5. **Payload grows ~40–60 KB** on 1.23 MB (D4).
6. **One page affected.** Fiscal Notes does not share this code.

## Testing

Per this repo's conventions — mechanism in pytest, quality in eval.

**pytest (`app/routes/corpus.py`):**
- a per-agency document carries its slug and its agency's reviewed aliases
- a suppressed alias (`tax`, `for`, `ban`) never appears in any document's terms
- an ambiguous alias (`bar`, `art`, `per`) never appears
- the carve-out (`dot`, `doc`) **does** appear, on Transportation and Corrections respectively
- a FY2026 baseline carries `br`, `baseline`, `26br`, `26baseline`
- a budget bill carries no type form
- a document whose `doc_id` tail is not a known slug still lists, with no agency terms
- an unreadable catalog degrades to "no terms", never a 500 — same failure posture as `budget_doc_ids`

**pytest (`retrieval/query_year.py`):** extend `tests/test_query_year.py`'s shorthand cases to `26br`, `26afr`, `27exec`; `26bill` must NOT parse; `chapter 26 ar` must still not parse.

**Guard against real data:** `tests/test_query_understanding_eval_safety.py` already checks the parsers against the eval set's ground truth in under a second. Extend it rather than hand-maintaining a list — it has caught two shipped defects before an eval run was spent.

**vitest (`Search.tsx`):**
- `26ar dema` finds the FY2026 DEMA Appropriations Report and nothing else
- every token must match — a query with one unmatchable word returns nothing
- terms match whole-token only: `ar` does not match a document solely because its terms contain `26ar`
- title substring still works (`ahccc`), and `insurance` still finds Insurance, Department of
- `governor` finds OSPB documents (D8)

**eval:** `uv run python -m eval.run_eval`, results committed (D10).

## Open

**O1 — the D7 carve-out is an assumption.** Destin approved the design with "this is good" in response to a message recommending the carve-out, rather than answering the carve-out question directly. It is written in because that was the recommendation on the table; if `dot` and `doc` should stay suppressed, D7 is the one decision to strike, and nothing else in the spec depends on it.
