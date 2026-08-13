---
name: jlbc-fiscal-note
description: >
  Drafts first-draft fiscal notes in the exact style of Arizona's Joint Legislative Budget Committee (JLBC).
  Use this skill whenever the user asks to write, draft, prepare, create, or generate a fiscal note, fiscal
  impact analysis, budget note, or fiscal memo for an Arizona bill, HB, SB, or legislative proposal. Also
  trigger when the user provides a bill number, bill text, agency cost estimates, or prior fiscal notes and
  asks for an analysis of fiscal impact. The output is a filled-in Word document (.docx) matching the official
  JLBC 2026 template exactly, plus a plain-language analyst reasoning memo. Trigger even if the user says
  "rough draft", "first pass", "quick fiscal note", or "fiscal memo."
---
<!-- SPEC: Read specs/jlbc-fiscal-note-spec.md before modifying this file -->

# JLBC Fiscal Note Drafter

Produces **two documents** for every fiscal note request:
1. **The fiscal note** — filled-in Word (.docx) using the official JLBC 2026 template
2. **The analyst reasoning memo** — a plain-language document for the human analyst to review

---

## Interactive UI Rule — Always Apply at Every Pause Point

**Whenever this skill pauses to ask the analyst a question, use the `ask_user_input_v0` tool to present structured options.** Never ask questions as plain prose alone when choices can be offered. This applies at every gate: the Intake Interview, Source Sign-Off, Estimate Decision Point, and any mid-draft clarification.

- For **bounded choices** (agency outreach status, estimate decision, source approve/reject): use `single_select` or `multi_select` widgets
- For **open-ended inputs** (bill text, analyst notes, figure overrides): ask in plain prose — no widget needed
- For **mixed messages** (some bounded, some open-ended): present the open-ended prose questions first, then follow immediately with widgets for the bounded choices
- Bundle all questions for a single gate into **one message** so the analyst can respond to everything at once

---

## Inputs — Work With Whatever the User Provides

| Input | How to use it |
|---|---|
| Bill text or summary | Primary source — read carefully |
| Agency cost estimates | Use directly; note if from agency (may run high) |
| Prior fiscal notes | Use for style reference and program background |
| Bill number only | Search azleg.gov for bill text; record the URL |

If no bill text or number is provided at all, ask before proceeding. Otherwise make a best-effort draft and flag gaps in both documents.

---

## Template Structure

### Header Table
| Field | Rules |
|---|---|
| **BILL #** | `HB 2007` or `SB 1012` — always a space between HB/SB and number |
| **TITLE** | Reference title exactly as it appears on the bill. **Not bold.** 10pt. Wraps naturally. For strike-everything amendments: strike through original title, add `NOW: [title]` or `S/E: [subject]`. |
| **SPONSOR** | Last name only. If duplicate last names: `Hernandez C`, `Hernandez L`. |
| **PREPARED BY** | Default: the user's name. Change only if user specifies. |
| **STATUS** | **Not bold. 10pt (sz val="20").** One of: `As Introduced` / `As Amended by [House/Senate] [Code]` / `House Engrossed` / `Senate Engrossed` / `As Enacted`. |

Committee codes — Senate: ATT, ED, FED, FIN, GOV, HHS, JUDE, NR, MABS, PS, RAGE, RULES. House: APPROP, AII, COM, ED, FMAE, GOV, HHS, IT, JUD, LARA, NREW, PSLE, RO, RULES, RED, ST, TI, WM.

### Date (bottom of document)
Format is `M/D/YY` split into multiple XML runs:
- **Day**: always a yellow-highlighted `#` — use `<w:highlight w:val="yellow"/>` in the run's `<w:rPr>`
- **Month**: plain text, UNLESS drafting in the last 7 days of the month — then also use a yellow-highlighted `#`
- **Year**: plain 2-digit year (e.g., `26`)

Mid-month example (March, day unknown): `3/` plain + `#` yellow + `/26` plain
Last-week example (both unknown): `#` yellow + `/` plain + `#` yellow + `/26` plain

Never use leading zeros. Never write `20` before the year.

---

## Section Writing Guide

### a. Description (mandatory)
- **Length**: Almost universally one sentence; occasionally two. Shorter is always better. Never more than two sentences.
- **Bill version phrasing**:
  - `As Introduced` status: open with `"The introduced version of [BILL #] would..."`
  - Amended or Engrossed status: write `"The bill would..."` or `"[BILL #] would..."` — drop the "introduced version" framing entirely
- **Tense**: Always use `"would"` for bill mechanics — not `"will"` and not present tense
- **No interpretation**: State mechanics only — no commentary on purpose, legislative intent, or policy rationale
- Not bold. 10pt body text.

### b. Estimated Impact (mandatory)

**Spacing — strictly enforced:**
- Insert a **blank line paragraph** after the Description text (before the "Estimated Impact" bold label)
- Insert a **blank line paragraph between every paragraph** within the Estimated Impact section — this includes between the opening impact paragraph, the agency contact paragraph, and any optional local government or table paragraphs
- Insert a **blank line paragraph after the last paragraph** of Estimated Impact (before the Analysis heading)

These blank lines are mandatory. Do not omit them even when content is brief.

**Opening sentence rules:**
- **NEVER**: `"It is estimated that..."` — explicitly prohibited
- **Standard form**: `"We estimate that the bill would [verb] [fund] [direction] by [amount] [beginning in FY XXXX]."` — e.g., `"We estimate that the bill would reduce General Fund revenue by about $(10,000) annually, beginning in FY 2027."`
- Both `"We estimate that the bill would..."` and `"We estimate the bill would..."` are acceptable
- Use `"approximately"` or `"about"` when estimates carry uncertainty; omit when the figure is exact or legislatively specified
- Lead with the bottom line; reader should know the key finding after sentence one
- Decreased figures in **parentheses**: `($3.2 million)`
- Phase-in: note the year full-year costs/savings occur
- Use a range if uncertainty makes a point estimate misleading — always present low end first
- Zero impact: `"We estimate that the bill would not generate a fiscal impact."` — do not say "minimal impact" unless genuinely minimal but nonzero
- Minimal impact: `"We estimate the bill will have a minimal fiscal impact."` followed by explanation of what the impact depends on
- Partial indeterminate: if some components are quantifiable and others are not, quantify what you can — do not make the entire note indeterminate if partial figures exist
- Full indeterminate — state directional expectation first, then explain why magnitude cannot be provided: `"The General Fund impact cannot be precisely determined in advance, as it would depend on..."` Do not simply say `"cannot be determined"` without explanation
- Conditional enactment: if the bill has a conditional enactment clause, note it explicitly: `"Because the bill would only become effective if federal grants are made available..."`

**Agency contact paragraph — required unless Option 3 was selected at intake:**

Based on the agency outreach option selected during intake:
1. **Response received**: `"We reached out to [Agency] for their assessment; they estimate the bill's impact to be [X]."`
   - When JLBC's estimate diverges from the agency's, present both — JLBC's first, the agency's second — and briefly explain why they differ
2. **No response yet**: `"We have asked [Agency] for their estimated impact of the bill and are awaiting a response."` (Variant also acceptable: `"We have asked [Agency] for their perspective on the fiscal impact of the bill but have not yet received a response."`)
3. **No outreach**: Omit the agency contact paragraph entirely. Do not reference agency outreach anywhere in the fiscal note.

**For first drafts where Option 1 was selected but no specific figure was provided**, flag it and ask the analyst for the figure before drafting.

**For first drafts where Option 2 was selected**, use form 2 verbatim as a placeholder.

**Optional additions:**
- Local government impact paragraph — only if there IS a local impact; omit otherwise
- Summary table — only if there is a quantified impact with multiple components

### c. Analysis (mandatory)
- **Always open the Analysis section with one of these two approved boilerplate sentences** (choose whichever fits the note):
  - `"Our estimate is based on the following data and assumptions:"` — use when citing specific data sources
  - `"Our estimate assumes the following:"` — use for assumption-heavy estimates with less external data
- **Numbered items only** — no narrative paragraphs, no policy context, no background, no repeating the bottom line from Estimated Impact
- Sub-items within numbered paragraphs use dashes (`-`) indented further than the parent item text
- **Calculation transparency**: when possible, one bullet or sub-bullet should show the arithmetic explicitly — walk from input → factor → output (e.g., `port count × daily kWh × days × cost per kWh = taxable receipts → × TPT rate = revenue impact`)
- **Source attribution style**: cite sources inline within the numbered item — `"According to [Source], [data point]."` or `"Based on [Source] data, [inference]."` Do not use URLs in the fiscal note itself. Name a source for every non-intuitive number.
- **Agency estimate flagging**: if an agency estimate is used but considered potentially overstated, say so explicitly in the relevant item with a brief reason (`"We believe the agency's estimate of the cost of storing data to be overstated, as..."`)
- **Rounding conventions**: round to the nearest hundred for small-to-medium dollar figures ($14,200; $490,700); round to one decimal for millions ($10.1 million, $8.3 million)
- Insert a **blank line paragraph at the end of the Analysis section** (before the date line)
- Use **numbered items** in `1)  2)  3)` format. Each numbered paragraph uses three runs: `N)` + `<w:tab/>` + text. Set a tab stop at 360 twips and `w:left="360" w:hanging="360"` so the number sits flush with section headers and all wrapped lines align under the first word. Note element order in `<w:pPr>`: `<w:tabs>` must come **before** `<w:ind>`, and `<w:rPr>` last:
  ```xml
  <w:pPr>
    <w:tabs><w:tab w:val="left" w:pos="360"/></w:tabs>
    <w:ind w:left="360" w:hanging="360"/>
    <w:rPr>...</w:rPr>
  </w:pPr>
  <w:r>...<w:t>1)</w:t></w:r>
  <w:r>...<w:tab/></w:r>
  <w:r>...<w:t>Item text here</w:t></w:r>
  ```
- Cite sources inline

---

## Writing Style

| Rule | Convention |
|---|---|
| Voice | Active: `"We estimate..."` not `"The bill is estimated to..."` |
| Person | `"we"` — never `"I"`, never passive constructions |
| **Forbidden phrases** | **Never**: `"It is estimated that..."` / `"note that"` / `"please note"` / `"it should be noted"` / `"on an annual basis"` / `"recurring"` |
| Hedge language | Acceptable and expected when data is limited: `"Since data on [X] is limited, this estimate may not reflect actual future expenditures."` |
| Analytical judgment | Use `"We believe..."` or `"We think..."` to flag JLBC's own reasoning vs. agency reasoning |
| Tense | Always `"would"` for bill mechanics in Description — not `"will"` and not present tense |
| Numbers | Spell out under 10; numerals 10+; `$` with commas |
| Millions | One decimal place: `$18.4 million`, `$6.0 million` (keep trailing zero) |
| Thousands | No decimal: `$400,000`, `$149,200` |
| Negatives | Always in parentheses: `($1.5 million)` or `$(6.0) million` |
| Percentages | Numerals always: `2.5%`, `49.5%` |
| Fund | Spell out `"General Fund"` in full; `"GF"` only in tables after first use |
| Timing | `"one-time"` (hyphenated) or `"ongoing"` — label every component |
| Timing phrases | `"beginning in FY XXXX"` (standard); `"starting in FY XXXX"` (acceptable variant); `"on a one-time basis"` for capital costs; `"annually"` or `"per year"` — **not** `"on an annual basis"` |
| Ranges | `"Between $X and $Y"` — always low end first |
| Fiscal years | `"FY 2026"`, `"FY 2027"` — not `"FY26"` or `"FY'26"` |
| Agency names | Spell out on first use, then abbreviate. See Agency Name Conventions below. |
| Length | **One page maximum.** Trim aggressively. |

### Agency Name Conventions (spell out on first use, then abbreviate)

| Agency | Abbreviation |
|---|---|
| Arizona Department of Transportation | ADOT |
| Arizona Health Care Cost Containment System | AHCCCS |
| Arizona Department of Administration | ADOA |
| Department of Child Safety | DCS |
| Administrative Office of the Courts | AOC |
| Arizona Board of Regents | ABOR |
| Department of Insurance and Financial Institutions | DIFI |
| Department of Forestry and Fire Management | DFFM |
| Centers for Medicare and Medicaid Services | CMS |
| Indian Health Service | IHS |

---

## Workflow

### Step 1: Intake Interview

**Before doing any research or drafting, ask the following questions.** Present them together in a single message so the analyst can answer all at once. Number each question clearly.

---

**Ask:**

Present questions 1, 2, 4, and 5 as plain prose (open-ended). Then use `ask_user_input_v0` widgets for questions 3 and 4 (bounded choices).

1. **Bill text** — "Please provide the bill text or bill summary. If you only have a bill number, I can look it up on azleg.gov." *(prose only)*

2. **Bill status** — "What is the current status of the bill?" *(prose only — status strings vary too much for a fixed list)*
   - If the bill has been amended, ask: "Please provide the **current amended text** only. I will draft the fiscal note solely based on the most recent version."

3. **Agency outreach** — Use a `single_select` widget with these options:
   - `"Yes — and I have the agency's response"` → ask them to paste/attach it
   - `"Yes — but no response received yet"`
   - `"No agency outreach for this note"`

4. **Additional materials** — Use a `multi_select` widget: "Do you have any of the following to share?" Options:
   - `"Prior fiscal notes on this or similar bills"`
   - `"Agency budget data, fee schedules, or enrollment figures"`
   - `"Legislative fact sheets or committee staff analyses"`
   - `"None of the above"`

5. **Analyst notes** — "Is there anything specific you want me to flag, assume, or avoid in this draft? Any known controversies, unusual provisions, or analytical challenges?" *(prose only)*

---

After receiving answers, confirm your understanding of the bill and key inputs in 2–3 sentences, then proceed to Steps 2–5. Do not begin drafting until the intake is complete.

**Exception:** If the user's initial message already clearly answers most of these questions (e.g., they paste in bill text, agency response, and background data all at once), skip or abbreviate the intake and proceed — only ask for what is genuinely missing.

### Step 2: Research + Research Preview Gate

First, read the bill carefully and identify: the policy mechanism, affected state agencies, likely cost/savings drivers (fund source, one-time vs. ongoing, first FY of impact), federal matching implications, and local government impacts.

Then pursue cost estimation using the **tiered research protocol** below. Work through the tiers in order, exhausting each before moving to the next. Record every source — URL, document name, date — for the reasoning memo.

---

#### ⛔ Research Preview Gate — Do Not Draft Until Analyst Approves

After completing research (before writing any section of the fiscal note), **pause and present a Research Preview** to the analyst in two parts. This is a required checkpoint — do not skip it even if you feel confident.

---

##### Part 1: Source Sign-Off

Present every source you intend to use, one row per source, in a table. The analyst must approve the source list before you proceed to the estimate.

**Sources for [Bill #]:**
| # | Source | Tier | URL / Citation | Used For | Notes / Concerns |
|---|---|---|---|---|---|
| 1 | [e.g., Colorado HB 23-1105 fiscal note] | Tier 1 | [URL] | [Admin cost benchmark] | [Adjusted for AZ population] |
| 2 | [e.g., AHCCCS FY2025 budget request] | Tier 2 | [URL] | [Per-member cost] | [Most recent available] |
| ... | | | | | |

Then use `ask_user_input_v0` to present a **`single_select` per source** so the analyst can approve or flag each one without typing. For each source row, present a widget question like:

> **Source #1 — [Source name]** (Tier X)
> Options: `"✅ Approve"` / `"❌ Reject"` / `"🔄 Find an alternative"`

Group all source widgets into a single `ask_user_input_v0` call (one question per source, up to the tool's limit). If there are more sources than the tool supports in one call, split into two calls. After all sources are reviewed, proceed only when all are resolved.

**Do not proceed to Part 2 until the analyst has signed off on sources.** If any source is rejected, drop it from your working set, note the rejection in the reasoning memo, and re-derive any figures that depended on it before presenting the estimate.

---

##### Part 2: Estimate Decision Point

After sources are approved, present your best fixed-dollar estimate and ask the analyst to choose how to proceed.

**Research Preview — [Bill #]**

**Policy mechanism:** [1 sentence]

**Affected agency/agencies:** [list]

**Proposed cost figures:**
| Component | Amount | One-time or Ongoing | Confidence | Source # |
|---|---|---|---|---|
| [e.g., AHCCCS admin costs] | [$X] | [Ongoing] | [Medium] | [#2] |

**Key assumptions:**
1. [Assumption + rationale]
2. [Assumption + rationale]

**Data gaps / flags:**
- [Any remaining concerns, Tier 4/5 reliance, ambiguous bill language, etc.]

**My best fixed-dollar estimate:** [e.g., "We estimate the bill will increase GF costs by approximately $2.3 million ongoing beginning FY 2026."]
*Even if confidence is low, always produce the best specific figure you can derive here — do not default to indeterminate language without giving the analyst a number to consider first.*

Then use a `single_select` widget with `ask_user_input_v0`:

> **How would you like to proceed with the estimate?**
> - `"✅ Use your estimate — draft with the figure above"`
> - `"✏️ Override a figure — I'll specify below"`
> - `"🔍 Re-research a component — I'll specify below"`
> - `"🚫 Go indeterminate — skip the dollar figure"`

If the analyst selects "Override a figure" or "Re-research a component", follow up in plain prose asking what specifically to change — no widget needed for that follow-up since the input is open-ended.

**Do not begin Step 3 until the analyst makes this choice.** If the analyst chooses indeterminate, use the appropriate approved language and skip to drafting — do not produce a number anywhere in the fiscal note.

If the analyst overrides a figure, confirm the change in one sentence, re-derive downstream totals, and proceed with the revised numbers.

---

#### Source Freshness Rule — Always Apply

Before using any source found online, pause and ask: **Is there a more recent or more authoritative version of this information?**

- If the source is a budget document, check whether a newer fiscal year's version has been published
- If the source is a fiscal note from another state, check whether that state has since updated or superseded it
- If the source is a dataset or report, check the publication date and search for a more recent edition
- If a better or more current source exists, use that instead and document both in the reasoning memo

This check applies at every tier. Do not skip it even when the first source found appears sufficient.

#### Tier 1: Comparable Fiscal Notes from Other Jurisdictions

This is the preferred starting point. Search for fiscal notes, fiscal impact statements, budget analyses, or legislative fiscal office estimates from other states or local governments that have enacted or considered the same or similar policy.

Search queries to try:
- `"[policy topic]" "fiscal note" site:*.gov`
- `"[policy topic]" "fiscal impact" "legislative" filetype:pdf`
- `"[state legislature]" "[policy keyword]" "cost estimate"`
- National Conference of State Legislatures (ncsl.org), Pew Charitable Trusts, Urban Institute for policy cost summaries

If found: use the other jurisdiction's estimate as a benchmark. Adjust for Arizona's size (population, caseload, program scale) using Arizona-specific data where available. Document the adjustment methodology explicitly.

#### Tier 2: State and Local Government Budget Documents

If no comparable fiscal notes exist, search for what governments actually spend on similar programs or activities.

Sources to search:
- Arizona state agency budget requests and operating budgets (azospb.gov, individual agency sites)
- Arizona Comprehensive Annual Financial Reports
- Other states' agency budgets for the same program type
- County and municipal budget documents for locally-administered programs
- Federal program expenditure data (usaspending.gov, census.gov/govs) for programs with federal-state cost sharing

Use these to derive unit costs, per-capita costs, or program cost ratios that can be applied to Arizona's context.

#### Tier 3: Government Datasets and Official Statistics

If budget documents don't yield usable cost figures, look for government datasets that can support a bottom-up estimate.

Sources to search:
- Arizona-specific: azed.gov, ahcccs.gov, azdhs.gov, azdor.gov, azleg.gov, Arizona auditor general reports
- Federal datasets: BLS, Census Bureau, HHS, DOE, DOJ, GAO reports
- Program enrollment, caseload, or utilization data that can be multiplied by a unit cost
- Fee schedules, rate tables, or reimbursement rates from relevant agencies

#### Tier 4: Quotes, Reports, and Secondary Sources

If government datasets are insufficient, the following may be used — but note the source type explicitly in the reasoning memo and flag the lower reliability:

- News articles quoting program administrators, government officials, or researchers with specific figures
- Advocacy or lobbying organization materials (use with caution; note potential bias)
- Academic or think-tank research with cited methodology
- Industry cost data (e.g., per-unit costs from trade associations)

#### Tier 5: Abstract or Analogical Methods

As a last resort, cost components may be estimated through analogy, scaling, or inference:

- Scaling from a known cost in a different jurisdiction using population or caseload ratios
- Extrapolating from a related but not identical program's cost structure
- Using wage/salary data to estimate staffing costs for a new program

**Important:** If you reach Tier 4 or Tier 5 for any significant cost component, flag it clearly in the Source Sign-Off table (Part 1 of the Research Preview Gate) with the note "Tier 4/5 — lower reliability." Do not proceed to the estimate until the analyst has reviewed and approved the source. Briefly explain in the notes column:
- What you searched for and didn't find
- What data you are proposing to use instead
- How reliable you think the resulting estimate would be

The analyst may approve it, ask for an alternative, or choose to go indeterminate at the Estimate Decision Point (Part 2).

#### When to Use Indeterminate Language

Indeterminate language is **always the analyst's choice**, made at the Estimate Decision Point. Claude must always produce a best fixed-dollar estimate first — even a low-confidence one — before the analyst can make that call. Never pre-empt the analyst by defaulting to indeterminate on your own.

If the analyst chooses indeterminate, use:
- `"We expect the bill to generate additional [costs/savings], but the magnitude cannot be determined in advance."` — when direction is clear but magnitude is not
- `"The fiscal impact of the bill cannot be determined in advance."` — when even the direction is unclear

---

### Step 3: Draft All Sections and Build the Word Document

Once the analyst has approved the Research Preview (sources and estimate decision), draft all three sections — Description, Estimated Impact, and Analysis — and proceed directly to filling the Word document template. Do not pause between sections for individual approvals.

**Amendment rule — strictly enforced:** If the bill has been amended, draft the fiscal note **solely based on the most recent amended version**. Do not reference, describe, or estimate the impact of any prior version of the bill.

### Step 4: Fill the Fiscal Note Template

```bash
cp ~/.claude/skills/jlbc-fiscal-note/assets/fiscal_note_template.docx /tmp/HBXXXX.docx
cd /tmp && unzip -o HBXXXX.docx -d unpacked/
# Edit unpacked/word/document.xml per XML Map below
cd /tmp/unpacked && zip -r /tmp/HBXXXX.docx . -x ".*"
```

Always use the template — never create from scratch.

### Step 5: Produce the Analyst Reasoning Memo

Create `HBXXXX_reasoning.docx` as a Word document using the `docx` npm library.

**Formatting — match the fiscal note visually:**
- **All text**: Calibri font (`"Calibri"`), 10pt (`size: 20` in docx-js half-points)
- **Section headers**: Calibri, 10pt, bold, black (`color: "000000"`) — no color, no size increase, no theme heading styles
- **Body text**: Calibri, 10pt, not bold
- **Page**: US Letter (12240 × 15840 DXA), 1-inch margins (1440 DXA each side)
- Set the document default font explicitly: `styles: { default: { document: { run: { font: "Calibri", size: 20 } } } }`
- Override Heading styles to match: `{ id: "Heading1", run: { font: "Calibri", size: 20, bold: true, color: "000000" } }`

Structure it with clear headings and sections containing:

1. **Bill summary** (2–3 sentences)
2. **Sources used** — list only sources that were actually used in the final fiscal note. For each:
   - Source name and full URL
   - Tier label (e.g., "Tier 1 — Colorado fiscal note", "Tier 3 — ADE enrollment data")
   - What it was used for
   Do not list sources that were found but rejected or not used.
3. **Estimate math** — show the full calculation chain from source data to final estimate. For each cost/savings component, write out the arithmetic step by step (e.g., "4,200 enrolled students × $312 per-pupil cost = $1,310,400, rounded to $1.3M ongoing GF"). Include the assumption or rationale behind each input value and a confidence level (high/medium/low).
   - **If the analyst chose indeterminate**: omit the final estimate math. Instead, present the best-next-alternative — the specific fixed-dollar estimate you would have used had the analyst not gone indeterminate. Show the full calculation for that alternative, note why it was set aside (e.g., data gap, bill ambiguity, analyst discretion), and label this section clearly as "Alternative Estimate (Not Used)."
4. **Analyst decisions** — two sub-sections:
   - *Figure overrides*: list every figure or assumption the analyst changed, with the original value and the override value
   - *Estimate decision*: note whether the final note used a fixed-dollar estimate, an override, or indeterminate language, and why
5. **Flags for the analyst** — explicit list of items to verify before finalizing:
   - Missing data that was assumed
   - Any Tier 4 or Tier 5 sources used and why
   - Agency response still needed
   - Ambiguous bill language affecting the estimate
   - Any figures that seem unusually high or low

### Step 6: Deliver Both Files
- Fiscal note: `HBXXXX.docx` (no space)
- Reasoning memo: `HBXXXX_reasoning.docx`
- Save both to the current working directory
- Present both with a one-sentence summary of the key fiscal finding

---

## Template XML Map

```
<w:body>
  <w:tbl>
    Row 1 left:  "BILL #" bold + value 10pt not-bold
    Row 1 right: "TITLE:" bold + value 10pt NOT BOLD (spans rows 1-2)
    Row 2 left:  "SPONSOR:" bold + value 10pt not-bold
    Row 3 left:  "PREPARED BY:" bold + value 10pt
    Row 3 right: "STATUS:" bold + value 10pt NOT BOLD (tab stop left-900 — "STATUS:" is wider than "TITLE:" so needs a larger tab stop value to visually align the value at the same distance from the label)
  </w:tbl>

  <Heading2> Description </Heading2>
  <p> [Description text, 10pt, not bold] </p>
  <p> [BLANK LINE] </p>                          <- spacer before Estimated Impact label
  <p> "Estimated Impact" bold [keep from template] </p>
  <p> [Estimated Impact narrative] </p>
  <p> [Agency contact paragraph] </p>
  <p> [BLANK LINE] </p>                          <- spacer before Analysis heading

  <Heading2> Analysis </Heading2>
  <p> [DELETE red strikethrough placeholder; replace with analysis text] </p>
  <p tabs-at-360 ind-left-360-hanging-360> [run: "1)"] [run: tab] [run: text] </p>  <- wraps align under first word
  <p> [BLANK LINE] </p>                          <- spacer after last Analysis paragraph

  <p right-aligned> [date: "M/" plain + "#" yellow + "/YY" plain; last week: "#" yellow + "/" + "#" yellow + "/YY"] </p>
</w:body>
```

**Formatting for inserted runs:**
- Body text: `<w:sz w:val="20"/>`, `<w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi"/>`
- Status value: `<w:sz w:val="20"/>` (10pt), no `<w:b/>` — STATUS cell tab stop must be `left` at pos `900` (not 792) because "STATUS:" is wider than "TITLE:" and needs the extra twips to align the value visually
- Title value: no `<w:b/>`, `<w:sz w:val="20"/>`
- Date `#`: add `<w:highlight w:val="yellow"/>` to its `<w:rPr>`

---

## Quality Checklist

**Interactive workflow gates:**
- [ ] Intake interview completed (or abbreviated with justification)
- [ ] Research Preview Part 1 presented — all sources listed with tier, URL, and notes
- [ ] Analyst signed off on all sources; rejections logged in reasoning memo
- [ ] Research Preview Part 2 presented — best fixed-dollar estimate shown before any indeterminate decision
- [ ] Analyst made explicit estimate decision (use / override / re-research / go indeterminate)
- [ ] All sections drafted and Word doc built immediately after Research Preview approval

**Fiscal note formatting:**

- [ ] Bill # has space: `HB 2007`
- [ ] Title is NOT bold
- [ ] Status is NOT bold, 10pt
- [ ] Date ends with yellow-highlighted `#`
- [ ] Blank line after Description (before Estimated Impact label)
- [ ] Blank line **between every paragraph** within Estimated Impact
- [ ] Blank line after last Estimated Impact paragraph (before Analysis heading)
- [ ] Blank line after last Analysis paragraph (before date line)
- [ ] If bill was amended: fiscal note reflects ONLY the current amended version — no references to prior versions
- [ ] Description is 1–2 sentences, not bold
- [ ] Estimated Impact opens with `"We estimate..."`
- [ ] `"It is estimated that..."` does NOT appear anywhere
- [ ] Agency contact paragraph: present if Option 1 or 2 selected at intake; uses exact approved boilerplate for Option 2; omitted entirely if Option 3 selected
- [ ] Decreased figures in parentheses
- [ ] One-time vs. ongoing labeled for every cost component
- [ ] General Fund addressed (even if no impact)
- [ ] Analysis does not repeat Estimated Impact bottom line
- [ ] No background-only paragraphs in Analysis
- [ ] Entire fiscal note fits on one page
- [ ] No numbered items or bullets in Description or Estimated Impact
- [ ] Fiscal note file: `HBXXXX.docx` no space
- [ ] Reasoning memo produced with all sources and URLs

---
**System rules:** If this skill or its supporting files are modified, follow the System Change Protocol in `CLAUDE.md` and the System Change Checklist in `~/.claude/docs/system.md`. All items are mandatory.
