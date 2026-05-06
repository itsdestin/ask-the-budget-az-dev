# Phase 0 Task 8 — Scoring Helper (OpenDataLoader)

## How to use this file

For each page below you'll see four things:
1. A **preview PNG** showing the PDF page with extraction bboxes drawn on it (light blue = every detected element; ① ② ③ red badges = spot-check cells)
2. The **3 spot-check cell texts** the red badges correspond to
3. **Auto-scores** I've already filled into `samples/scores-opendataloader.csv`
4. **What to score yourself** in the CSV

### Per-page workflow (~3 min/page)

**Step 1 — Open the preview PNG.** Look at the 3 red boxes (① ② ③).
- Does each red box surround a single, readable element on the page (not too much, not too little, not a wrong region)?
- Look at the light-blue boxes overall: do they look like reasonable element boundaries, or is there obvious chaos (boxes crossing unrelated content, missing whole regions, etc.)?

**Step 2 — Compare the 3 spot-check texts** (in the table for each page) **with what's actually in those red boxes on the PNG.**
- All 3 match exactly: the auto-scored `cell_accuracy` is correct.
- 1 mismatch: override `cell_accuracy` to 2 in the CSV.
- 2+ mismatches or wrong digits: override to 1 (or 0).

**Step 3 — Score `bbox_quality` in the CSV** based on Step 1:
- All 3 red boxes tight around their content, blue boxes look reasonable: **3**
- 1 red box off (covers extra content or misses content), or blue boxes drift on a few items: **2**
- 2+ red boxes off, or blue boxes are clearly wrong on many items: **1**
- No bboxes drawn, or wildly off-page: **0**

**Step 4 — Score `footnote_attachment` in the CSV.**
- If the page has no footnote markers visible: **NA**
- If footnotes exist: open the PDF (or just look at the PNG) and pick one footnote marker like `(1)` or `*`. Open `samples/extractor-output/opendataloader/<doc>/page-<N>.md`. Is the footnote text near the row that referenced it (within ~5 lines)?
  - Tied correctly: **3**. Footnote present but unattached: **2**. Wrong row or mangled: **1**. Footnote dropped: **0**.

**Step 5 — Confirm or override `header_detection`.**
- Open the .md file. Count `# Heading` lines.
- Compare with how many visual headings (large/bold text) you see on the PNG.
- All caught, no false flags: **3**. 1 missed or 1 false: **2**. ≥2 missed: **1**. None caught: **0**.
- Sometimes ODL puts headings INSIDE table blocks (visible in the .json) rather than as `heading`-typed blocks. If the heading text is somewhere in the output (just not labeled `heading`), score 2.

**Step 6 — Don't change `cell_accuracy` or `multipage_reassembly` unless Step 2 surfaced a problem** (these were auto-scored from data; trust them by default).

---

## jlbc-approps-fy26 p.520 — `multi-page-table`

**Preview:** `samples/scoring-helpers/jlbc-approps-fy26/page-520.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` (page 520)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-520.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `Veterinary Medical Examining Board Fund` |
| ⓘ2 | `Tobacco Products Tax Fund - Prop. 204 Protection Account` |
| ⓘ3 | `26,044,761,500` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **1** — Table is not linked to other pages of the run

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/3 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-approps-fy26 p.513 — `multi-page-table`

**Preview:** `samples/scoring-helpers/jlbc-approps-fy26/page-513.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` (page 513)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-513.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `SUMMARY  OF ONE.TIME OTHER FUND ADJUSTMENTS` |
| ⓘ2 | `1,515,000` |
| ⓘ3 | `Total - One-Time Spending` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **0** — No table block detected on this page

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/6 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## governors-state-agency-detail-fy27 p.535 — `multi-page-table`

**Preview:** `samples/scoring-helpers/governors-state-agency-detail-fy27/page-535.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` (page 535)
**Extraction output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-535.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `Expenditure Detail of FY 2026 Base Appropriations` |
| ⓘ2 | `290.8` |
| ⓘ3 | `All dollar amounts are expressed in thousands.` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **1** — Table is not linked to other pages of the run

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/1 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## governors-state-agency-detail-fy27 p.602 — `multi-page-table`

**Preview:** `samples/scoring-helpers/governors-state-agency-detail-fy27/page-602.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` (page 602)
**Extraction output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-602.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `Expenditure Detail of FY 2027 Executive Budget` |
| ⓘ2 | `63,222.9` |
| ⓘ3 | `All dollar amounts are expressed in thousands.` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **1** — Table is not linked to other pages of the run

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/1 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-approps-fy26 p.27 — `multi-page-table`

**Preview:** `samples/scoring-helpers/jlbc-approps-fy26/page-27.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` (page 27)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-27.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `SUMMARY OF ONE-TIME GENERAL FUND ADJUSTMENTS V` |
| ⓘ2 | `Subtotal - FY 2025 One-Time Supplementals` |
| ⓘ3 | `BH-24` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **2** — 1 number(s) in pypdf only, 1 in ODL only — likely formatting
- `multipage_reassembly` = **0** — No table block detected on this page

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/7 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## agao-afr-fy25 p.163 — `restated-afr`

**Preview:** `samples/scoring-helpers/agao-afr-fy25/page-163.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` (page 163)
**Extraction output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-163.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `STATE OF ARIZONA` |
| ⓘ2 | `96,679,944.15` |
| ⓘ3 | `See accompanying notes to financial statements. 162` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/28 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## agao-afr-fy25 p.128 — `restated-afr`

**Preview:** `samples/scoring-helpers/agao-afr-fy25/page-128.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` (page 128)
**Extraction output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-128.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `STATE OF ARIZONA` |
| ⓘ2 | `DE2091` |
| ⓘ3 | `35,935.33` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/24 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## agao-afr-fy25 p.126 — `restated-afr`

**Preview:** `samples/scoring-helpers/agao-afr-fy25/page-126.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` (page 126)
**Extraction output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-126.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `STATE OF ARIZONA` |
| ⓘ2 | `TR3740` |
| ⓘ3 | `18,610,245.01` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/26 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-baseline-fy27 p.140 — `multi-column-narrative`

**Preview:** `samples/scoring-helpers/jlbc-baseline-fy27/page-140.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-baseline-fy27.pdf` (page 140)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy27/page-140.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `FY 2027` |
| ⓘ2 | `194,700 28,282,300` |
| ⓘ3 | `FY 2027 Baseline 45 AHCCCS` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/9 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-baseline-fy23 p.125 — `multi-column-narrative`

**Preview:** `samples/scoring-helpers/jlbc-baseline-fy23/page-125.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-baseline-fy23.pdf` (page 125)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy23/page-125.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `AGENCY DESCRIPTION - The Attorney General is an elected constitutional officer, The office provides legal counsel to sta` |
| ⓘ2 | `The Baseline includes S55,936,100  and 456.5 FTE Positions  in FY 2023 for the operating  budget. These amounts consist ` |
| ⓘ3 | `FY 2023 Boseline 65 Attorney Generol - Deportment  of Law` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/2 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-baseline-fy27 p.163 — `multi-column-narrative`

**Preview:** `samples/scoring-helpers/jlbc-baseline-fy27/page-163.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-baseline-fy27.pdf` (page 163)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy27/page-163.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `FY 2027` |
| ⓘ2 | `1 1,556,500` |
| ⓘ3 | `FY 2027 Boseline 68 Attorney General - Deportment  of Law` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/8 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## governors-state-agency-detail-fy27 p.6 — `footnote-heavy`

**Preview:** `samples/scoring-helpers/governors-state-agency-detail-fy27/page-6.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` (page 6)
**Extraction output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-6.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `GENERAL FUND SPENDING BREAKDOWN HEALTH AND WELFARE DEPARTMENT OF CORRECTIONS` |
| ⓘ2 | `517  4` |
| ⓘ3 | `All dollar amounts are expressed in thousands.` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/4 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: applies, 10 marker candidates found in pypdf text).

## jlbc-approps-fy26 p.101 — `footnote-heavy`

**Preview:** `samples/scoring-helpers/jlbc-approps-fy26/page-101.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` (page 101)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-101.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `ble 5` |
| ⓘ2 | `$  14,853,400` |
| ⓘ3 | `FY 2026 Appropriotions  Report 55 AHCCCS` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **2** — 1 number(s) in pypdf only, 0 in ODL only — likely formatting
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/5 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: applies, 7 marker candidates found in pypdf text).

## jlbc-approps-fy26 p.164 — `footnote-heavy`

**Preview:** `samples/scoring-helpers/jlbc-approps-fy26/page-164.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` (page 164)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-164.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `ACJC plans to update this report to evaluate outcomes after they have received data from the county programs.` |
| ⓘ2 | `2,967,300` |
| ⓘ3 | `FY 2026 Appropriotions  Report 118 Arizo na Cri m i na I J u stice Co m m iss io n` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/1 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: applies, 9 marker candidates found in pypdf text).

## governors-state-agency-detail-fy27 p.32 — `cross-doc-name`

**Preview:** `samples/scoring-helpers/governors-state-agency-detail-fy27/page-32.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` (page 32)
**Extraction output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-32.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `Funding` |
| ⓘ2 | `FY 2027` |
| ⓘ3 | `All dollar amounts are expressed in thousands.` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **3** — No visual headings expected; ODL also detected none

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-baseline-fy27 p.143 — `cross-doc-name`

**Preview:** `samples/scoring-helpers/jlbc-baseline-fy27/page-143.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-baseline-fy27.pdf` (page 143)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy27/page-143.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `inflation adjustment of 2.48% and a state population adjustment of 1.28% pursuant to A.R,S. 5It-292'` |
| ⓘ2 | `4,942,30O L0,845,900` |
| ⓘ3 | `FY 2027 Baseline 48 AHCCCS` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/1 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## jlbc-baseline-fy23 p.112 — `cross-doc-name`

**Preview:** `samples/scoring-helpers/jlbc-baseline-fy23/page-112.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-baseline-fy23.pdf` (page 112)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy23/page-112.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `Background  - ln January 20!7 , the Centers for Medicare and Medicaid Services (CMS)  approved AHCCCS'  request` |
| ⓘ2 | `Statutory Changes Long-Term  Budget lmpacts County Contributions Program  Components Tobacco  Master Settlement Agreemen` |
| ⓘ3 | `FY 2023 Boseline 52 AHCCCS` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **3** — No visual headings expected; ODL also detected none

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).

## agao-afr-fy25 p.177 — `misc, afr-notes`

**Preview:** `samples/scoring-helpers/agao-afr-fy25/page-177.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` (page 177)
**Extraction output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-177.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `STATE OF ARIZONA NOTES TO FINANCIAL STATEMENTS JUNE 30, 2025` |
| ⓘ2 | `Local Trans Assistance Fund – State Treasurer (TR3848)` |
| ⓘ3 | `A.R.S. § 35-391 B. requires governmental entities to disclose in their annual financial report the amount of any reward,` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **3** — 3 headings detected vs ~3 CAPS candidates (good coverage)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: applies, 6 marker candidates found in pypdf text).

## governors-sources-and-uses-fy27 p.24 — `misc, summary-table`

**Preview:** `samples/scoring-helpers/governors-sources-and-uses-fy27/page-24.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/governors-sources-and-uses-fy27.pdf` (page 24)
**Extraction output:** `samples/extractor-output/opendataloader/governors-sources-and-uses-fy27/page-24.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `General Fund Sources and Uses` |
| ⓘ2 | `USES OF FUNDS` |
| ⓘ3 | `All dollar amounts are expressed in thousands.` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 1/3 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: applies, 4 marker candidates found in pypdf text).

## jlbc-approps-fy26 p.49 — `misc, line-item-marker`

**Preview:** `samples/scoring-helpers/jlbc-approps-fy26/page-49.png` _(the page with bboxes drawn — open this first)_
**Original PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` (page 49)
**Extraction output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-49.{json,md}`

**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.

| Badge | What's inside the red box should be |
|---|---|
| ⓘ1 | `Arizona Department of Administration` |
| ⓘ2 | `23,037,200u` |
| ⓘ3 | `FY 2026 Appropriotions  Report 3 Arizona Deportment  of Administration` |

**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table

**Auto-suggested, please confirm:** `header_detection` = **1** — 0/11 — ODL missed most visual headings (verify)

**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: likely NA, 0 marker candidates found in pypdf text).
