# Report types and formatting guidance for generated documents — design

**Date:** 2026-08-13
**Status:** ⬛ **IMPLEMENTED AND MERGED 2026-08-13 (`f91b68f`).** G1–G11 all
shipped. One deviation: G4's component-breakdown table style landed in
`harness/guides/shared.md`, not `comparison.md`. What shipped is recorded in
`STATUS.md` → "Document guide — SHIPPED, unwitnessed"; the plan
(`docs/superpowers/plans/2026-08-13-document-guide.md`) carries a header
listing five defects in its own example code — do not re-run it.
**Revised:** 2026-08-13 after an audit against the fiscal-note skill found
seven defects, including a wrong measurement in G5 and an internal
contradiction in G8. Every correction below was re-verified against the
live code, not accepted on the auditor's word.

**Builds on:** `docs/superpowers/specs/2026-08-12-jlbc-memo-formatting-design.md`
(the renderer) and `docs/reference/jlbc-document-conventions.md` (the house
style, cross-checked against two primary sources).

---

## The problem

`create_document` renders a JLBC memo correctly, and the system prompt
already tells the model **when** to offer a document, never to produce one
for a simple answer, to keep citation substance in the prose, and that the
title becomes the subject line.

What it does not say is **what goes in the document**: no section skeleton,
no number style, no guidance on when a table beats a sentence. So the shape
of every document is whatever the model defaults to.

Not yet a measured problem — nobody has watched a real document produced
under the current prompt, because this machine has no API key. It is a
known gap in the instructions, not an observed defect in the output.

## The constraint that shapes the answer

The system prompt is ~1,100 lines and is **re-sent on every step of every
turn**. Detailed report-type guidance placed there is paid for by every
lookup that never produces a document.

Destin's framing was "make it a model-invokable skill." The literal form —
a Claude skill, as `docs/reference/jlbc-fiscal-note-skill/` is — cannot
work: AI Mode has no skill loader, no widget tool, and no filesystem reach
(Invariant 7 forbids the last). The *shape* of the idea transfers exactly.

---

## Decisions

### G1 — a sixth tool, `document_guide(report_type)`

The model calls it when it is about to write a document. It returns the
guidance for that report type as text.

**What this costs anyway:** the tool's *schema* joins the cached prefix and
is sent every step, like the other five — a fixed ~15 lines, cached at
roughly a tenth of fresh input (S22). The *content* never enters the prefix.

Alternatives rejected:

| Option | Why not |
|---|---|
| Put it all in the system prompt | Always paid, on every turn, for a minority use |
| A `report_type` parameter on `create_document` | Server learns the type but the model gets no guidance back |
| Post-process the document server-side | Cannot restructure prose, and rewriting the model's numbers is forbidden by G6 |

### G2 — three report types

| Type | Trigger | Shape |
|---|---|---|
| `research-memo` | the default; answers a question | bottom line first, then findings, then what was used |
| `comparison` | two or more years, agencies, or funds **in the answer** | table first, prose explains what moved and why |
| `agency-profile` | a memo about one agency's budget | funding table, then program notes, then issues |

**Corrected derivation.** An earlier draft derived these from
`eval/agent_queries.yaml`'s `shape` field and got it wrong in four ways.
The corrected reading:

- The file holds **35 queries**; the standard set is **31** (the 4
  `dr-probe` Deep Research queries are mutually exclusive with `full`,
  pinned by `tests/test_eval_agent_queries.py::test_dr_probe_subset`).
  Over the 31: 12 `lookup`, 5 `refusal`, 4 `comparison`, 3 `analyze`,
  5 `historical`, 2 `memo`.
- **`shape` measures retrieval difficulty, not output form.** The file says
  so. It is therefore weak evidence for report types and is cited here only
  as a rough demand signal.
- **`historical` does NOT map to `comparison`.** All five pin exactly one
  `key_fact` and ask a single-year question. A table-first document for any
  of them is a table with one row.
- **The two `memo` queries are the only ones in the set that ask for a
  document**, and they are the real evidence: `mm-esa-memo` ("how voucher
  costs have moved over the last two budgets and why") is `comparison`;
  `mm-adc-briefing` ("total funding, the general fund share, and the
  one-time items") is `agency-profile`.

`agency-profile` is triggered by the `mm-adc-briefing` shape — a memo about
one agency's budget — **not** by "tell me about agency X", which occurs
zero times in the set.

**Deliberately NOT a fiscal-note type.** Description / Estimated Impact /
Analysis is a legally-shaped product with an official template, an intake
interview, and a source sign-off gate. Destin's existing skill does that
job properly. Producing a lookalike from corpus retrieval would invite it
to be mistaken for the real thing.

**An unrecognised or absent `report_type` returns the `research-memo`
guidance**, never an error.

### G3 — what the guide returns

Per type: when to use it, a section skeleton, which table style fits, and a
length target. Plus the shared style block — numbers, voice, forbidden
phrases, the borrowed rules in G10 — returned every time.

Returned as **Markdown text the model reads**, not a schema it fills.

### G4 — ONE table style, and a pointer to the two the prompt already owns

An earlier draft proposed three styles "drawn from the corpus's own
shapes." A sweep of 22,110 real table chunks refuted the columns:

- `Item` appears as a header cell **0 times**. The real first column is
  **blank** — 3,995 of 4,121 four-column tables (96.9%).
- The third column reads `BASELINE` or `APPROVED`, never "FY budget". That
  distinction is load-bearing: a Baseline figure is a recommendation, an
  Approved figure is enacted law.
- Fund source is **not a separate table**. It is a row section inside the
  same three-year table (`FUND SOURCES General Fund`, `SUBTOTAL - Other
  Appropriated Funds`, `TOTAL - ALL SOURCES`).
- A `share` column exists in **7 of 4,794** instances.

**And `harness/system-prompt.md:850-885` already documents both shapes
correctly**, including the fund ladder and the rule *"the totals are
published — never build one by adding rows yourself."* A `share` column
requires dividing by a total, so the earlier draft would have put a
less-accurate restatement in front of the model **and** invited it to break
a rule already in the prompt.

**So the guide carries one style and points at the prompt for the rest:**

| Style | Columns | Use |
|---|---|---|
| Component breakdown | Component · Amount · one-time or ongoing | Breaking one total into parts |

Its provenance is stated honestly: it comes from **SKILL.md:271-274**, and
the skill permits a *"Summary table — only if there is a quantified impact
with multiple components"* (SKILL.md:121) **without specifying columns**.
It is not a corpus shape. The `one-time`/`ongoing` labelling *is* a JLBC
requirement (spec mandate 2026-03-13; SKILL.md:165, 502) — but on **prose
adjectives**; rendering it as a column is this design's choice.

**The rule that matters most: a table is for numbers that share a
structure.** Two figures in a sentence stay in the sentence. The common
model failure is tabulating a single pair of values.

**The guide must say "bullets", not numbered lists.** The skill mandates
`1) 2) 3)` for its Analysis section, and `memo/markdown.py` does not render
numbered lists — a `1)` line comes out as an unstyled plain paragraph,
pinned deliberately by `tests/test_jlbc_memo.py`. Borrowing the skill's
list convention would produce visibly unstyled output.

### G5 — 🔴 the rounding convention applies to the DOCUMENT BODY ONLY

Destin's call (2026-08-13): writing conventions follow the fiscal note,
which rounds — `$15.0 million`, millions to one decimal.

**The citation floor is 4 for an untagged figure and 2 for a tagged one.**
An earlier draft of this spec claimed a flat floor of 4 and was wrong.
`citation/annotate.py:128-129` passes `min_significant_digits=2` on the tag
path, with the reason at the line: the tag is independent evidence, so a
round figure must still verify inside the one chunk the model named.
`citation/matching.py:87` defaults to 4, and that default governs only the
untagged fallback.

Re-measured against the live code:

| Figure | Written digits | Tagged (floor 2) | Untagged (floor 4) |
|---|---|---|---|
| `$6,043,200` | 5 | ✅ | ✅ |
| `$490,700` | 4 | ✅ | ✅ |
| `$18.4 million` | 3 | ✅ | ❌ |
| `$15.0 million` | 2 | ✅ | ❌ |
| `$14,200` | 3 | ✅ | ❌ |
| `$6.0 million` | 1 | ❌ | ❌ |
| `$400,000` | 1 | ❌ | ❌ |

**Two corrections to the earlier draft, both material.** Rounded millions
mostly DO link when the model tags them, so the problem is smaller than
claimed. But the skill's *thousands* rule is worse than shown: `$400,000`
(SKILL.md:161) has one written digit and fails **both** floors.

**The 144-figure / 33.1-point loss must not be cited as current
behaviour.** `STATUS.md` attaches an explicit warning to it — *"This is the
untagged floor, not the shipped number… Recorded transcripts carry no
markers"* — and the live verified turn linked **44 of 60 figures by tag**.

**The resolution stands, on narrower grounds.** A document carries no
citation chips; the system prompt already says the markers do not travel
into the file, and the audit verified this independently: `annotate_answer`
runs only on assistant **text blocks**, so `body_markdown` never reaches it.

Therefore:

- **Chat answer: write figures as the source writes them.** Unchanged from
  today, and it is what keeps the untagged fallback working.
- **Document body: round to JLBC convention.**

The guide must state this split explicitly. "Round your numbers" as a bare
instruction would be applied to the answer too.

**The real cost of rounding, stated properly.** It is not only the loss of
a chip. A rounded figure **cannot be found by searching the source PDF** —
an analyst who reads `$6.0 million` in a memo has no string to look for in
the document it came from. That is the loss, and G10's source-naming and
calculation-transparency rules are what partly repair it.

### G6 — the server never rewrites the model's numbers

No post-processing pass reformats figures. It would change a figure the
model may have quoted from a source, and silently alter what the analyst
reads without either of them knowing.

### G7 — style rules come from `jlbc-document-conventions.md`

Quoted from that reference, which cross-checks two primary sources. The
guide does not restate them from memory.

### G8 — the guide's content lives in `harness/guides/*.md`

**Not `memo/guides/`.** An earlier draft said `memo/`, which contradicted
this spec's own testing section: `tests/test_harness_tools.py` pins
`harness/tools.py`'s imports to a list containing neither `memo` nor
`pathlib`, and loading a file from `memo/` requires one of them.

`harness/` is already on that allowlist, so a `harness/guides.py` loader
changes nothing. It also makes the cited precedent exact —
`harness/system-prompt.md` lives in `harness/` and is read by
`harness/prompt.py` — and it keeps `memo/` to the single responsibility
memo-spec M1 gave it: a pure renderer that knows Markdown and Word and
nothing else.

A non-technical successor can still edit house guidance in a Markdown file
without touching Python, which was the point.

### G9 — advisory, never enforced

Nothing fails if the model skips the tool or ignores the advice. The
failure mode is one document in the model's default style, not a refused
document. `create_document`'s description points at the guide; a test pins
that pointer, because it is the only thing making the tool discoverable.

### G10 — eight rules borrowed from the skill

Each is editorial, works in one turn, and is absent from the current prompt.

| Rule | Source | Why |
|---|---|---|
| Lead with the bottom line — the reader knows the key finding after sentence one | SKILL.md:99 | Turns G2's "summary paragraph" into something enforceable |
| Name a source for every non-intuitive number, inline: *"According to [Source], [data point]"* | SKILL.md:130 | This is the mechanism G5 leans on and never specified |
| No URLs in the document | SKILL.md:130 | STATUS records a real defect — a download token leaked into answer prose |
| Show the arithmetic: input → factor → output | SKILL.md:129 | The only thing that makes a **rounded** figure re-derivable |
| End with a short "what to verify" list | SKILL.md:424-429 | The best answer to G5's auditability cost, and it costs nothing |
| Findings must not repeat the summary's bottom line; no background-only items | SKILL.md:127, 504-505 | Directly applicable to the section skeletons |
| When the answer is indeterminate, state the direction first, then **why** the magnitude cannot be given — never a bare "cannot be determined" | SKILL.md:104, 377 | Invariant 3 refusal phrasing, which nothing currently specifies |
| Descriptive and explanatory words only — no advocacy adverbs or adjectives | Staff memorandum, para 74 | JLBC's own neutrality rule |

---

## What this does NOT do

- No change to the renderer. `memo/` is untouched.
- No change to retrieval, ingest, chunking or citation.
- No enforcement, no validation, no server-side rewriting.
- No fiscal-note report type (G2).

## The eval rule

G9's pointer edits `harness/system-prompt.md`, which CLAUDE.md says
triggers an eval run. **It cannot measure this**: `eval/run_eval.py` calls
`retrieve()` directly and never reads the prompt, and the edit is confined
to the `create_document` section. Same call as S22/S23 and as the memo
spec, recorded here so it is visibly considered rather than missed.

## Testing

- The tool returns guidance for each of the three types, and falls back to
  `research-memo` for an unknown or absent one.
- Every guide file loads and is non-empty — a missing file must not 500 a
  turn.
- `create_document`'s description mentions the guide (G9's pointer).
- The guide's number rules match `jlbc-document-conventions.md`, pinned
  against the reference so the two cannot drift.
- **A guard that G5's answer/document split is stated in the guide.** Its
  loss would be invisible: untagged citation coverage would fall with no
  error anywhere.
- **A guard that no guide recommends numbered lists**, which the renderer
  does not style (G4).
- `harness/tools.py`'s import allowlist is unchanged — now true, given G8.

## G11 — length: two pages maximum, one page preferred

**Destin's call, 2026-08-13.** All three report types: **two pages
maximum, one page where the material allows.** The instruction the guide
gives the model is *"be concise while conveying all relevant
information"* — a completeness rule with a ceiling, not a word budget.

Why not the fiscal note's flat one page: that cap belongs to a
single-purpose statutory product. A multi-agency comparison held to one
page would have to drop rows, and a document that omits an agency to fit
is worse than one that runs to a second page. Why a cap at all: without
one, models expand to fill available structure, and an analyst who has to
skim a generated memo has lost the reason to use it.

**"Conveying all relevant information" is the load-bearing half.** Paired
with G10's "no background-only items" and "findings must not repeat the
bottom line", it cuts padding rather than content — the two rules aim at
opposite failure modes and are stated together deliberately.
