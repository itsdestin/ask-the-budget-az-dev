# Report types and formatting guidance for generated documents — design

**Date:** 2026-08-13
**Status:** draft, awaiting approval
**Builds on:** `docs/superpowers/specs/2026-08-12-jlbc-memo-formatting-design.md`
(the renderer) and `docs/reference/jlbc-document-conventions.md` (the house
style, cross-checked against two primary sources).

---

## The problem

`create_document` renders a JLBC memo correctly, but the model is told
almost nothing about what to put in it. Its entire editorial instruction is
which Markdown constructs render. Nothing says what sections a memo should
have, when a table beats a bullet list, or how JLBC writes a number.

So the shape of every document is whatever the model defaults to. That is
not yet a measured problem — it has not been observed on a keyed machine —
but it is a known gap in the instructions.

## The constraint that shapes the answer

The system prompt is ~1,100 lines and is **re-sent on every step of every
turn**. Detailed report-type guidance placed there would be paid for by
every lookup that never produces a document. Documents are a small
minority of turns.

Destin's framing was "make it a model-invokable skill." The literal form —
a Claude skill, as `docs/reference/jlbc-fiscal-note-skill/` is — cannot
work: AI Mode has no skill loader, no widget tool, and no filesystem reach
(Invariant 7 forbids the last). The *shape* of the idea transfers exactly.

---

## Decisions

### G1 — a sixth tool, `document_guide(report_type)`

The model calls it when it is about to write a document. It returns the
guidance for that report type as text. Guidance content is therefore paid
for only on turns that produce a document.

**What this costs anyway:** the tool's *schema* joins the cached prefix and
is sent every step, like the other five. That is a fixed ~15 lines, and it
is cached at roughly a tenth of fresh input (S22). The *content* — the part
that is long — never enters the prefix.

Alternatives rejected:

| Option | Why not |
|---|---|
| Put it all in the system prompt | Always paid, on every turn, for a minority use |
| A `report_type` parameter on `create_document` | Server learns the type but the model gets no guidance back — it would still be writing blind |
| Post-process the document server-side | Cannot restructure prose, and rewriting the model's numbers is forbidden by G6 |

### G2 — three report types, not more

| Type | When | Shape |
|---|---|---|
| `research-memo` | the default; answers a question | short summary paragraph, then findings, then what was used |
| `comparison` | two or more years, agencies, or funds | table first, prose explains what moved and why |
| `agency-profile` | "tell me about agency X" | funding table, then program notes, then issues |

Derived from the shapes `eval/agent_queries.yaml` already tracks: 12
`lookup`, 6 `comparison`, 5 `analyze`, 5 `historical`, 2 `memo`. `lookup`
and `analyze` both land in `research-memo`; `comparison` and `historical`
both land in `comparison`.

**Deliberately NOT a fiscal-note type.** Description / Estimated Impact /
Analysis is a legally-shaped product with an official template, an intake
interview, and a source sign-off gate. Destin's existing skill does that
job properly. Producing a lookalike from corpus retrieval would invite it
to be mistaken for the real thing.

**An unrecognised or omitted `report_type` returns the `research-memo`
guidance**, never an error. A model that guesses a type name should get
useful guidance, not a failed call it has to recover from.

### G3 — what the guide returns

Per type: when to use it, a section skeleton, which table style fits, and a
length target. Plus the shared style block — numbers, voice, forbidden
phrases — returned every time, because it is short and applies to all three.

Returned as **Markdown text the model reads**, not as a schema it fills.
The model already writes the whole body; the guide advises it.

### G4 — three table styles, drawn from the corpus's own shapes

| Style | Columns | Use |
|---|---|---|
| Three-year | Item · FY prior (actual) · FY current (estimate) · FY budget | The JLBC books' standard shape. Any question spanning fiscal years |
| Fund source | Fund · Amount · share | General Fund vs Other Appropriated vs Federal |
| Component | Component · Amount · one-time or ongoing | Breaking one total into parts. The `one-time`/`ongoing` label is a JLBC requirement, not decoration |

**A table is for numbers that share a structure.** Two figures in a
sentence stay in the sentence. This is the rule most worth stating, because
the common model failure is tabulating a single pair of values.

### G5 — 🔴 the rounding convention applies to the DOCUMENT BODY ONLY

**This is the decision that most needs to survive.** Destin's call
(2026-08-13) is that writing conventions follow the fiscal note, which
rounds: `$15.0 million`, `$6.0 million`, millions to one decimal.

**Measured against the live citation code, that rounding makes a figure
uncitable:**

| Figure | Written significant digits | Reaches the matcher? |
|---|---|---|
| `$6,043,200` | 5 | yes |
| `$490,700` | 4 | yes |
| `$18.4 million` | 3 | **no** |
| `$15.0 million` | 2 | **no** |
| `$6.0 million` | 1 | **no** |

`citation/matching.py` refuses any figure below **4 written digits** — it
returns no candidates at all, so the figure can never be linked to a
source. `STATUS.md` already records this as the dominant cause of unlinked
figures: 144 of them, 33.1 points of lost coverage.

**Why the conflict is nonetheless resolvable:** a document carries no
citation chips. The system prompt already says so — "the clickable citation
markers do not travel into the file." Chat answers carry chips; documents
do not.

**Therefore:**

- **In the chat answer: write figures as the source writes them.** Full
  precision. This is what keeps citation linking working, and it is
  unchanged from today.
- **In the document body: round to JLBC convention.** Nothing there is
  being linked, and a memo the analyst will send should read like JLBC's
  own writing.

The guide must state this split explicitly, because "round your numbers" as
a bare instruction would be applied to the answer as well and would quietly
degrade the most heavily-measured feature in the app.

**Residual tension, stated honestly:** a rounded figure in a document is
less auditable than a precise one, and this project's North Star is
auditable provenance. What carries the audit trail in a document is the
prose naming its source document and fiscal year, which the prompt already
requires. The analyst reviews and sends; it is a draft, not a published
finding. **If this proves wrong in use, the fix is to make the document
carry precise figures, not to weaken the citation floor.**

### G6 — the server never rewrites the model's numbers

No post-processing pass reformats figures. Tempting, and wrong twice over:
it would change a figure the model may have quoted from a source, and it
would silently alter what the analyst reads without either of them knowing.
Guidance advises; the model writes; the renderer lays out.

### G7 — style rules come from `jlbc-document-conventions.md`

Numbers, voice, forbidden phrases and agency abbreviations are quoted from
that reference, which cross-checks two primary sources. The guide's content
does not restate them from memory.

### G8 — the guide's content is a data file, not code

`memo/guides/*.md`, one per report type, loaded on call. A non-technical
successor can edit house guidance in a Markdown file without touching
Python — the same reasoning that makes `harness/system-prompt.md` a file.

### G9 — advisory, never enforced

Nothing fails if the model skips the tool or ignores the advice. The
failure mode is one document in the model's default style rather than a
refused document. `create_document`'s description points at the guide; a
test pins that pointer, because the pointer is the only thing making the
tool discoverable.

---

## What this does NOT do

- No change to the renderer. `memo/` is untouched.
- No change to retrieval, ingest, chunking or citation.
- No enforcement, no validation, no server-side rewriting.
- No fiscal-note report type (G2).

## Testing

- The tool returns guidance for each of the three types, and falls back to
  `research-memo` for an unknown or absent one.
- Every guide file loads and is non-empty (a missing file must not 500 a
  turn).
- `create_document`'s description mentions the guide (G9's pointer).
- The guide's number rules match `jlbc-document-conventions.md` — pinned
  against the reference, so the two cannot drift.
- **A guard that the chat-answer/document split of G5 is stated in the
  guide.** This is the one instruction whose loss would be invisible and
  costly: citation coverage would fall with no error anywhere.
- `harness/tools.py`'s import allowlist is unchanged.

## Open question for Destin

**Length targets.** The fiscal note mandates "one page maximum, trim
aggressively." That is right for a fiscal note. Whether a research memo
answering a broad question should also be held to one page is a judgement
about how these get used — a one-page cap would force real omissions on a
multi-agency comparison. Proposed: one page for `research-memo`, no cap for
`comparison` and `agency-profile`, with "trim aggressively" stated for all
three.
