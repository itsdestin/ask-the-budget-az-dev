# JLBC document conventions

**What this is:** JLBC's house style for written products, derived from two
primary sources rather than inferred. Written 2026-08-13 while building
`memo/`; it is the reference for any future work on generated documents.

**Sources, both committed:**

1. **The staff memorandum** — `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx`,
   the real FY 2027 Appropriations Report Round 1 instructions memo.
   Everything attributed to it below was **measured** out of the file.
2. **The fiscal-note skill** — `docs/reference/jlbc-fiscal-note-skill/`,
   Destin's own Claude skill, plus the official JLBC 2026 fiscal-note
   template shipped inside it. Everything attributed to it is **stated**
   there as a rule, most of it recorded as a dated user mandate.

The two are different document types, so where they agree the agreement is
strong evidence of a house rule.

## 🔵 How conflicts are resolved (Destin's call, 2026-08-13)

Where the two sources disagree:

- **WRITING conventions follow the FISCAL NOTE.** Numbers, voice, phrasing,
  rounding, forbidden phrases, abbreviations. The fiscal-note skill wins
  because its rules are recorded as explicit dated mandates rather than
  read off one document, and they are consistent across every JLBC written
  product.
- **DOCUMENT STRUCTURE stays SEPARATE, per document type.** Page setup,
  letterhead, section-heading treatment, list style, and length are
  properties of the document you are producing, not of JLBC writing in
  general. A research memo keeps the staff memorandum's structure; it does
  not become fiscal-note-shaped.

The dividing line: **structure is what the page looks like; conventions are
what the sentences say.** `memo/` owns the first. The guidance given to the
model owns the second.

One item sits on the line and is settled here: **body point size is
STRUCTURE.** `memo/` stays at the staff memorandum's measured 10.5pt rather
than adopting the fiscal note's 10pt, because it is a property of that page
layout and was measured from the document being reproduced.

---

## The rules both documents share — treat these as house style

### Headings are bold body text. They are never bigger.

| | Value |
|---|---|
| Staff memorandum | section headings are 10.5pt bold — the same size as its body |
| Fiscal-note template | `Heading 2` is defined at **10pt bold**, the same size as its body |
| Fiscal-note skill, on the memo it generates | "Section headers: Calibri, 10pt, bold, black — **no color, no size increase, no theme heading styles**" |

Three independent statements of one rule. **A generated JLBC document must
never use Word's stock heading sizes**, which run 13-16pt and coloured.

### Vertical space comes from empty paragraphs, not from space-after

The staff memorandum builds every gap out of empty paragraphs. The
fiscal-note skill makes it explicit and mandatory:

> Insert a **blank line paragraph between every paragraph** within the
> Estimated Impact section… These blank lines are mandatory. Do not omit
> them even when content is brief.

Its quality checklist carries four separate blank-line items.

**Consequence for any generator:** the tool's own default space-after must
be zeroed, or every deliberate gap is doubled. See the trap section below —
this cost real time here.

### Calibri, throughout

Both documents. No second face anywhere, including headings.

### No coloured headings, and no accent rules

Neither document uses colour as decoration. The fiscal-note skill says
`color: "000000"` explicitly for its section headers.

**Colour IS used, but only as an analyst flag** — an earlier version of
this file wrongly said "no colour at all", and both sources refute it:

- the fiscal-note template carries a red strikethrough placeholder the
  analyst is told to delete (SKILL.md:460)
- the skill **mandates** yellow highlighting on the unknown date digits
  (SKILL.md:61-63; spec mandate 2026-03-13)
- the staff memorandum instructs analysts to highlight *"substantive
  changes from the Baseline"* in yellow (para 125)

So the convention is: **colour marks something a human must act on, never
anything decorative.** A generated document should carry none, because it
has nothing for the analyst to fill in — but if that ever changes, yellow
highlight is the house signal for it.

---

## The rules that are per-document — do NOT unify these

| | Staff memorandum | Fiscal note |
|---|---|---|
| Body size | **10.5pt** (`sz 21`) | **10pt** (`sz 20`) |
| Margins (T/B/L/R) | 0.7″ / 0.5″ / 1.0″ / 1.0″ | 0.75″ / 0.5″ / 0.8″ / 0.8″ |
| Section headings | in a **bordered box**, via the built-in `Header` paragraph style | plain bold, via `Heading 2` |
| Lists | bullets (`List Paragraph`) | numbered `1)` with a tab stop at 360 twips and a 360 hanging indent |
| Length | runs to several pages | **one page maximum**, "trim aggressively" |
| Letterhead | full masthead + address + rule + seal | header table (BILL # / TITLE / SPONSOR / PREPARED BY / STATUS) |

`memo/` implements the staff-memorandum column. A future fiscal-note-shaped
output would need the other one.

---

## Numbers — the conventions worth reusing verbatim

From the fiscal-note skill's style table. These are JLBC's, not inferred,
and they are the most directly reusable thing in it.

| Rule | Convention |
|---|---|
| Millions | one decimal, **keep the trailing zero** — `$18.4 million`, `$6.0 million` |
| Thousands | no decimal — `$400,000`, `$149,200` |
| Negatives | always parentheses — `($1.5 million)` or `$(6.0) million` |
| Percentages | numerals always — `2.5%`, `49.5%` |
| Fiscal years | `FY 2026` — never `FY26`, never `FY'26` |
| Small numbers | spell out under 10, numerals 10 and above |
| Rounding | nearest hundred for small/medium (`$14,200`, `$490,700`); one decimal for millions |
| Fund names | spell out `General Fund`; `GF` only in tables, after first use |
| Agencies | spell out on first use, then abbreviate |
| Timing | label every component `one-time` (hyphenated) or `ongoing` |
| Timing phrasing | `beginning in FY XXXX`; `annually` or `per year` — **never** `on an annual basis` |
| Ranges | `Between $X and $Y` — low end first, always |

**Agency abbreviations** the skill fixes: ADOT, AHCCCS, ADOA, DCS, AOC,
ABOR, DIFI, DFFM, CMS, IHS.

**The one real conflict, and its resolution.** The staff memorandum
carries the rule twice, and the second statement is the sharper one:

> para 23: "Continue to use full numbers (e.g., `$15,000,000`) throughout
> the entire document."
>
> para 72: "**Numbers: Match numbers in the narrative to the BUDS table.**
> Numbers greater than one million should be written out completely (e.g.
> `$15,000,000`) rather than abbreviated."

That contradicts the fiscal note's `$15.0 million`. Two things follow that
an earlier version of this file missed. The rule is **scoped to figures
over $1 million** — exactly the range the fiscal note rounds, so the
conflict is narrower and more direct than first stated. And its stated
*reason* is that the narrative must match the BUDS table, i.e. **JLBC's own
tables carry full numbers** — which a sweep of the live corpus confirms.

**Resolved 2026-08-13 in favour of the fiscal note: generated documents use
`$15.0 million`.** The memorandum's rule governs *Appropriations Report
narratives*, a specific product with its own house requirement, and AI Mode
does not produce those; the fiscal note is by far the closer product to a
research memo.

**An earlier version of this file argued that full numbers "would make
comparison tables unreadable". That argument is withdrawn — the source it
was overriding refutes it.** Para 72's whole point is that JLBC's own
tables carry full numbers, and analysts do not even author that table by
hand (para 57: *"Export the new table, run the macro… do NOT make manual
edits to BUDS table numbers"*).

**So this is a real trade, not a free win.** The full-number form is also
the citable form — see the citation-floor section of
`docs/superpowers/specs/2026-08-13-document-guide-design.md` (G5). Rounding
buys JLBC-native prose and costs the analyst the ability to find the figure
by searching the source PDF.

**If the app is ever extended to draft Appropriations Report narratives,
this flips for that type only** — which is exactly why number style belongs
to the report type rather than to the renderer.

---

## Voice and phrasing

| Rule | Convention |
|---|---|
| Voice | active, first-person plural — `"We estimate…"`, `"We believe…"` |
| Never | `"I"`, and never passive constructions |
| Marking JLBC's own judgement | `"We believe…"` / `"We think…"`, to separate it from an agency's claim |
| Hedging | expected where data is thin — `"Since data on [X] is limited, this estimate may not reflect actual future expenditures."` |

**Forbidden phrases**, listed as a dated mandate:

> `"It is estimated that…"` · `"note that"` · `"please note"` ·
> `"it should be noted"` · `"on an annual basis"` · `"recurring"`

**Neutrality**, from the staff memorandum (para 74) rather than the skill:

> "limit the text to descriptive/explanatory words, and avoid 'advocacy'
> adverbs and adjectives, particularly for Executive-requested budget
> increases."

JLBC's own house rule against editorialising, and squarely on point for a
tool that must not advocate.

---

## 🔴 Two Word traps, hit independently by both implementations

Worth recording because they are the same defect class in two different
toolchains, which means the next person will hit them too.

**1. The tool's document defaults leak in.** The fiscal-note skill (using
the `docx` npm library) instructs:

> Set the document default font explicitly:
> `styles: { default: { document: { run: { font: "Calibri", size: 20 } } } }`

`memo/` hit the same thing from the other direction: python-docx's blank
template sets `w:spacing w:after="200" w:line="276"` in its document
defaults — 10pt after every paragraph and 1.15 line spacing — which the
reference sets nowhere. Combined with the empty-paragraph rhythm above,
every gap came out roughly doubled.

**2. Theme heading styles leak in.** The skill says:

> Override Heading styles to match: `{ id: "Heading1", run: { font:
> "Calibri", size: 20, bold: true, color: "000000" } }`
> — **no color, no size increase, no theme heading styles**

`memo/` hit exactly this: python-docx's stock `Title` style carries an
accent-blue bottom border and `spacing after 300`, so the first render had
a blue masthead with a stray blue line above the real rule.

**The rule that falls out of both: in a JLBC document, never inherit a
style — state it.**

---

## What does NOT transfer to AI Mode

The skill is built for a Claude harness with a skill loader, an
`ask_user_input_v0` widget tool, and filesystem access to unpack and
hand-edit `word/document.xml`. AI Mode has none of those, and the last one
is forbidden by Invariant 7.

Its **workflow** — intake interview, source sign-off gate, estimate
decision point, tiered research protocol — is a human-in-the-loop drafting
process across many turns. AI Mode answers a question in one turn.

Its **section structure** — Description / Estimated Impact / Analysis — is
the legally-shaped form of a fiscal note, not a general report shape.
Applying it to "what did we spend on child care subsidy" would produce
padded, mislabelled sections.

**Borrow the style rules. Do not borrow the workflow or the section
structure.** That is the same dividing line stated at the top: conventions
transfer, structure does not.
