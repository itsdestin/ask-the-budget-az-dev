# JLBC Fiscal Note — Spec

**Version:** 1.0
**Last updated:** 2026-03-13
**Feature location:** `~/.claude/skills/jlbc-fiscal-note/`

## Purpose

This skill drafts first-pass fiscal notes in the exact style of Arizona's Joint Legislative Budget Committee (JLBC). Given a bill number, bill text, agency cost estimates, or prior fiscal notes, it produces two documents: a filled-in Word (.docx) fiscal note using the official JLBC 2026 template and a plain-language analyst reasoning memo. The skill handles the full lifecycle from intake interview through tiered research, source vetting, estimate negotiation, template population, and dual-file delivery — designed so that a human analyst reviews and finalizes rather than starting from scratch.

## User Mandates

- (2026-03-13) Output must always be **two documents**: a filled `.docx` fiscal note and a `.docx` analyst reasoning memo. No exceptions.
- (2026-03-13) The fiscal note `.docx` must use the official JLBC 2026 template (`assets/fiscal_note_template.docx`) — never create a document from scratch.
- (2026-03-13) Header field formatting must match exactly: BILL # with a space (`HB 2007`), TITLE not bold at 10pt, STATUS not bold at 10pt (`sz val="20"`), SPONSOR as last name only, PREPARED BY defaults to `Destin Moss`.
- (2026-03-13) Date format is `M/D/YY` with no leading zeros and no four-digit year. The day is always a yellow-highlighted `#` (`<w:highlight w:val="yellow"/>`). The month is also yellow-highlighted if drafting in the last 7 days of the month.
- (2026-03-13) The phrase `"It is estimated that..."` is **explicitly prohibited** anywhere in the fiscal note. The approved opening is `"We estimate that the bill would..."` or `"We estimate the bill would..."`.
- (2026-03-13) Decreased/negative dollar figures must always appear in parentheses: `($1.5 million)`.
- (2026-03-13) Every cost component must be labeled as one-time or ongoing.
- (2026-03-13) The entire fiscal note must fit on **one page maximum**.
- (2026-03-13) Blank line paragraphs are mandatory: after Description (before Estimated Impact label), between every paragraph within Estimated Impact, after last Estimated Impact paragraph (before Analysis), and after last Analysis paragraph (before date line).
- (2026-03-13) Analysis section must use numbered items in `1)  2)  3)` format with tab stops at 360 twips and hanging indent — no narrative paragraphs, no background-only items, no repetition of the Estimated Impact bottom line.
- (2026-03-13) Description must be 1-2 sentences maximum. Use `"would"` tense for bill mechanics; never `"will"` or present tense.
- (2026-03-13) For amended bills, the fiscal note must reflect **only** the current amended version — no references to prior versions.
- (2026-03-13) Agency contact paragraph must follow the exact approved boilerplate for each outreach option (response received / no response yet / no outreach = omit entirely).
- (2026-03-13) Claude must always produce a best fixed-dollar estimate before the analyst can choose to go indeterminate. Never default to indeterminate language without giving the analyst a number first.
- (2026-03-13) All interactive pause points must use `ask_user_input_v0` structured widgets for bounded choices (single_select, multi_select) — never present bounded choices as plain prose alone.
- (2026-03-13) The reasoning memo must use Calibri 10pt throughout, matching the fiscal note visually, with section headers bold but same size/font.
- (2026-03-13) Forbidden phrases (in addition to "It is estimated that..."): `"note that"`, `"please note"`, `"it should be noted"`, `"on an annual basis"`, `"recurring"`.
- (2026-03-13) Voice must be active first-person plural (`"We estimate..."`, `"We believe..."`). Never `"I"`, never passive constructions.

## Design Decisions

| Decision | Rationale | Alternatives considered |
|----------|-----------|----------------------|
| Dual output (fiscal note + reasoning memo) | Separates the official product from the analytical trail so the analyst can review assumptions without cluttering the one-page fiscal note | Single combined document; inline comments in the docx |
| Tiered research protocol (5 tiers) | Ensures the most authoritative and comparable sources are used first, with lower-reliability sources flagged explicitly | Flat source list with no hierarchy; relying solely on agency data |
| Two-part Research Preview Gate (Source Sign-Off then Estimate Decision) | Prevents drafting on unapproved sources or estimates; gives the analyst explicit control over both inputs and outputs | Single approval gate; no approval gate (draft then revise) |
| Template-based docx via unpack/edit XML/repack | Preserves exact JLBC formatting, styles, and layout that would be lost if generating docx from scratch | Generating docx from scratch via python-docx; outputting PDF; markdown output |
| Yellow-highlighted `#` for unknown date components | Signals to the analyst which date fields need to be filled in before release, using in-document visual cues | Comment annotations; placeholder text like "TBD" |
| Mandatory intake interview before any research | Ensures all inputs are collected upfront, reducing rework; exception exists when user front-loads all info | Immediately start researching based on bill number alone |
| Analyst controls indeterminate decision | Prevents Claude from taking the easy path of "cannot be determined" — forces a best-effort number first | Allow Claude to independently choose indeterminate when confidence is low |
| Reasoning memo uses Calibri 10pt matching fiscal note | Visual consistency between the two deliverables; looks professional if both are printed or shared | Different formatting for the memo; markdown memo instead of docx |
| npm `docx` library for reasoning memo, XML editing for fiscal note | The fiscal note requires precise XML control to match the JLBC template exactly; the memo is generated fresh and benefits from the higher-level `docx` API | Same approach for both; LaTeX; HTML-to-docx |
| Source freshness rule at every tier | Government data and fiscal notes from other states can become stale quickly; enforces checking for newer editions | Trust whatever is found first; only check freshness for Tier 4/5 |

## Current Implementation

### File Structure

```
~/.claude/skills/jlbc-fiscal-note/
  SKILL.md                              # Skill definition and full workflow
  assets/
    fiscal_note_template.docx           # Official JLBC 2026 Word template
  specs/
    spec.md                             # This file
```

### Workflow (6 Steps)

**Step 1 — Intake Interview:**
The skill opens with a structured intake collecting five inputs: (1) bill text or number, (2) bill status (As Introduced / As Amended / Engrossed / Enacted), (3) agency outreach status via single_select widget (response received / no response yet / no outreach), (4) additional materials via multi_select widget (prior fiscal notes, agency budget data, fact sheets, or none), and (5) free-text analyst notes on flags or assumptions. If the user's initial message already provides most inputs, the intake is abbreviated — only genuinely missing items are requested. The skill confirms understanding in 2-3 sentences before proceeding.

**Step 2 — Research + Research Preview Gate:**
The skill reads the bill carefully, identifying: policy mechanism, affected agencies, cost/savings drivers (fund source, one-time vs. ongoing, first FY of impact), federal matching implications, and local government impacts. It then pursues cost estimation through the tiered research protocol:

- **Tier 1:** Comparable fiscal notes from other jurisdictions (preferred starting point)
- **Tier 2:** State/local government budget documents and program expenditure data
- **Tier 3:** Government datasets, enrollment/caseload data, fee schedules, rate tables
- **Tier 4:** News articles, advocacy materials, academic research (flagged as lower reliability)
- **Tier 5:** Analogical methods — scaling, extrapolation, wage-based staffing estimates (flagged as lower reliability)

A **Source Freshness Rule** applies at every tier: before using any source, the skill checks whether a more recent or authoritative version exists.

After research, the skill pauses at the **Research Preview Gate** — a mandatory two-part checkpoint:

- **Part 1 (Source Sign-Off):** Every source is presented in a table (source name, tier, URL/citation, usage, notes/concerns). Each source gets a single_select widget for approve/reject/find alternative. No drafting proceeds until all sources are resolved.
- **Part 2 (Estimate Decision Point):** The skill presents its best fixed-dollar estimate with component breakdown, key assumptions, data gaps, and a confidence assessment. The analyst chooses via single_select: use the estimate as-is, override a figure, re-research a component, or go indeterminate. Drafting does not begin until the analyst makes this choice.

**Step 3 — Draft All Sections:**
After Research Preview approval, the skill drafts all three sections (Description, Estimated Impact, Analysis) in a single pass without pausing for individual section approvals. Amendment rule: if the bill has been amended, only the current amended version is addressed.

**Step 4 — Fill the Fiscal Note Template:**
The skill copies the JLBC 2026 template, unpacks it to access `word/document.xml`, edits the XML according to the Template XML Map (header table fields, Description, Estimated Impact with mandatory blank-line spacing, Analysis with numbered items at 360-twip tab stops and hanging indent, and the date line with yellow-highlighted placeholders), then repacks and validates the docx.

Template XML Map structure:
- Header table: Row 1 = BILL # + TITLE (spanning rows 1-2), Row 2 = SPONSOR, Row 3 = PREPARED BY + STATUS (tab stop at pos 900)
- Body: Heading2 "Description" -> description text -> blank line -> bold "Estimated Impact" label -> impact paragraphs (blank lines between each) -> agency contact paragraph -> blank line -> Heading2 "Analysis" -> opening boilerplate sentence -> numbered items (`N) <tab> text` with `w:tabs` before `w:ind` before `w:rPr` in `w:pPr`) -> blank line -> right-aligned date

Formatting specs for inserted runs: body text at `sz val="20"` with `rFonts asciiTheme="minorHAnsi"`, title and status values not bold at 10pt, STATUS cell tab stop at pos 900.

**Step 5 — Produce the Analyst Reasoning Memo:**
Created as `HBXXXX_reasoning.docx` using the `docx` npm library with Calibri 10pt throughout (document default font set explicitly, Heading1 overridden to Calibri 10pt bold black). Contains five sections:
1. Bill summary (2-3 sentences)
2. Sources used — only sources that made it into the final note, each with name, URL, tier label, and usage
3. Estimate math — full calculation chain from source data to final estimate, step by step, with confidence levels per component. If analyst chose indeterminate: presents the "Alternative Estimate (Not Used)" with full math and explanation of why it was set aside
4. Analyst decisions — figure overrides (original vs. override values) and estimate decision rationale
5. Flags for the analyst — missing data assumptions, Tier 4/5 source usage, pending agency responses, ambiguous bill language, unusually high/low figures

**Step 6 — Deliver Both Files:**
Both files saved to the current working directory with naming convention `HBXXXX.docx` (no space) and `HBXXXX_reasoning.docx`. Presented with a one-sentence summary of the key fiscal finding.

### Writing Style Conventions

- Active voice, first-person plural ("We estimate...", "We believe...")
- `"would"` for bill mechanics in Description; `"approximately"` or `"about"` for uncertain estimates
- Numbers: spell out under 10, numerals 10+, `$` with commas
- Millions: one decimal place with trailing zero (`$6.0 million`)
- Thousands: no decimal (`$149,200`)
- Negatives: always in parentheses
- Percentages: always numerals (`2.5%`)
- Fiscal years: `FY 2026` (not `FY26`)
- Fund names: spell out `General Fund` in full; `GF` only in tables after first use
- Agency names: spell out on first use, then abbreviate per the conventions table
- Rounding: nearest hundred for small/medium figures; one decimal for millions

### Quality Checklist

The skill enforces a 26-item quality checklist covering interactive workflow gates (intake completed, source sign-off, estimate decision) and fiscal note formatting (spacing, prohibited phrases, field formatting, one-page limit, file naming).

## Dependencies

- **Depends on:**
  - `~/.claude/skills/jlbc-fiscal-note/assets/fiscal_note_template.docx` — the official JLBC 2026 Word template (must be present)
  - `unzip`/`zip` — for unpacking/repacking docx (ZIP archives of OOXML)
  - `docx` npm library — used to generate the reasoning memo
  - Web search capability — for tiered research (azleg.gov bill lookup, other-state fiscal notes, government datasets)
- **Depended on by:** None (standalone skill; outputs are consumed by JLBC analysts)

## Known Bugs / Issues

*None currently tracked.*

## Planned Updates

*(None currently)*

## Change Log

| Date | Version | What changed | Type | Approved by |
|------|---------|-------------|------|-------------|
| 2026-03-13 | 1.0 | Initial spec | New | Destin |
