# Phase 0 Task 8 — Scoring Helper (OpenDataLoader)

For each page below, open the PDF in a viewer to the listed page, then check the 3 spot-check cells. Each row in the CSV is pre-filled with auto-scored dimensions; you fill in `bbox_quality` and `footnote_attachment`, and confirm/override the auto-suggestions.

**Auto-scored** (computed from JSON + pypdf reference):
- `cell_accuracy` — full numeric-token diff against pypdf
- `multipage_reassembly` — JSON inspection for shared table IDs

**Auto-suggested** (you confirm in the viewer):
- `header_detection` — pypdf CAPS-line count vs ODL heading-block count

**You score** (visual inspection required):
- `bbox_quality` — open the PDF, look at the 3 spot-check bboxes below
- `footnote_attachment` — pick a footnote on the page, check it ties to the right row

---

## jlbc-approps-fy26 p.520 — `multi-page-table`

**PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` — open page **520**
**Output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-520.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `Veterinary Medical Examining Board Fund` | [61, 527, 124, 531] | r421,c1 |
| 2 | `Tobacco Products Tax Fund - Prop. 204 Protection Account` | [62, 291, 150, 295] | r16,c2 |
| 3 | `26,044,761,500` | [713, 191, 737, 194] | r1,c1 |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **1** — Table is not linked to other pages of the run
- `header_detection` = **1** _(suggested)_ — 0/3 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-approps-fy26 p.513 — `multi-page-table`

**PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` — open page **513**
**Output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-513.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `SUMMARY  OF ONE.TIME OTHER FUND ADJUSTMENTS` | [161, 727, 462, 741] | — |
| 2 | `1,515,000` | [396, 577, 427, 585] | — |
| 3 | `Total - One-Time Spending` | [59, 464, 150, 472] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **0** — No table block detected on this page
- `header_detection` = **1** _(suggested)_ — 0/6 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## governors-state-agency-detail-fy27 p.535 — `multi-page-table`

**PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` — open page **535**
**Output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-535.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `Expenditure Detail of FY 2026 Base Appropriations` | [36, 560, 470, 580] | — |
| 2 | `290.8` | [621, 320, 642, 329] | r32,c11 |
| 3 | `All dollar amounts are expressed in thousands.` | [34, 7, 201, 15] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **1** — Table is not linked to other pages of the run
- `header_detection` = **1** _(suggested)_ — 0/1 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## governors-state-agency-detail-fy27 p.602 — `multi-page-table`

**PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` — open page **602**
**Output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-602.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `Expenditure Detail of FY 2027 Executive Budget` | [38, 560, 446, 580] | — |
| 2 | `63,222.9` | [663, 336, 694, 345] | r32,c12 |
| 3 | `All dollar amounts are expressed in thousands.` | [34, 7, 201, 15] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **1** — Table is not linked to other pages of the run
- `header_detection` = **1** _(suggested)_ — 0/1 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-approps-fy26 p.27 — `multi-page-table`

**PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` — open page **27**
**Output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-27.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `SUMMARY OF ONE-TIME GENERAL FUND ADJUSTMENTS V` | [136, 717, 493, 739] | — |
| 2 | `Subtotal - FY 2025 One-Time Supplementals` | [31, 485, 184, 495] | — |
| 3 | `BH-24` | [301, 38, 326, 48] | — |

**Auto-scores:**
- `cell_accuracy` = **2** — 1 number(s) in pypdf only, 1 in ODL only — likely formatting
- `multipage_reassembly` = **0** — No table block detected on this page
- `header_detection` = **1** _(suggested)_ — 0/7 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## agao-afr-fy25 p.163 — `restated-afr`

**PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` — open page **163**
**Output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-163.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `STATE OF ARIZONA` | [283, 764, 347, 772] | r1,c64 |
| 2 | `96,679,944.15` | [469, 387, 510, 394] | r3537,c9 |
| 3 | `See accompanying notes to financial statements. 162` | [245, 23, 385, 39] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/28 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## agao-afr-fy25 p.128 — `restated-afr`

**PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` — open page **128**
**Output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-128.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `STATE OF ARIZONA` | [283, 764, 347, 772] | r1,c29 |
| 2 | `DE2091` | [59, 405, 81, 412] | r1225,c2 |
| 3 | `35,935.33` | [394, 60, 423, 67] | r1261,c7 |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/24 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## agao-afr-fy25 p.126 — `restated-afr`

**PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` — open page **126**
**Output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-126.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `STATE OF ARIZONA` | [283, 764, 347, 772] | r1,c27 |
| 2 | `TR3740` | [59, 377, 80, 384] | r1096,c2 |
| 3 | `18,610,245.01` | [548, 60, 590, 67] | r1129,c11 |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/26 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-baseline-fy27 p.140 — `multi-column-narrative`

**PDF:** `samples/raw-pdfs/jlbc-baseline-fy27.pdf` — open page **140**
**Output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy27/page-140.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `FY 2027` | [490, 728, 520, 738] | — |
| 2 | `194,700 28,282,300` | [500, 565, 540, 586] | — |
| 3 | `FY 2027 Baseline 45 AHCCCS` | [58, 33, 569, 45] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/9 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-baseline-fy23 p.125 — `multi-column-narrative`

**PDF:** `samples/raw-pdfs/jlbc-baseline-fy23.pdf` — open page **125**
**Output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy23/page-125.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `AGENCY DESCRIPTION - The Attorney General is an elected constitutional officer, The office provides legal counsel to sta` | [55, 697, 562, 736] | — |
| 2 | `The Baseline includes S55,936,100  and 456.5 FTE Positions  in FY 2023 for the operating  budget. These amounts consist ` | [55, 312, 270, 348] | — |
| 3 | `FY 2023 Boseline 65 Attorney Generol - Deportment  of Law` | [56, 30, 566, 43] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/2 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-baseline-fy27 p.163 — `multi-column-narrative`

**PDF:** `samples/raw-pdfs/jlbc-baseline-fy27.pdf` — open page **163**
**Output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy27/page-163.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `FY 2027` | [490, 728, 520, 738] | — |
| 2 | `1 1,556,500` | [399, 668, 437, 677] | — |
| 3 | `FY 2027 Boseline 68 Attorney General - Deportment  of Law` | [58, 33, 569, 46] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/8 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## governors-state-agency-detail-fy27 p.6 — `footnote-heavy`

**PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` — open page **6**
**Output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-6.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `GENERAL FUND SPENDING BREAKDOWN HEALTH AND WELFARE DEPARTMENT OF CORRECTIONS` | [43, 544, 609, 553] | — |
| 2 | `517  4` | [639, 249, 684, 265] | — |
| 3 | `All dollar amounts are expressed in thousands.` | [34, 7, 201, 15] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/4 — ODL missed most visual headings (verify)
- `footnote_attachment` — **applies** (10 marker candidates in pypdf text)

## jlbc-approps-fy26 p.101 — `footnote-heavy`

**PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` — open page **101**
**Output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-101.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `ble 5` | [68, 732, 84, 741] | — |
| 2 | `$  14,853,400` | [476, 374, 544, 390] | — |
| 3 | `FY 2026 Appropriotions  Report 55 AHCCCS` | [57, 36, 568, 47] | — |

**Auto-scores:**
- `cell_accuracy` = **2** — 1 number(s) in pypdf only, 0 in ODL only — likely formatting
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/5 — ODL missed most visual headings (verify)
- `footnote_attachment` — **applies** (7 marker candidates in pypdf text)

## jlbc-approps-fy26 p.164 — `footnote-heavy`

**PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` — open page **164**
**Output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-164.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `ACJC plans to update this report to evaluate outcomes after they have received data from the county programs.` | [330, 721, 560, 745] | — |
| 2 | `2,967,300` | [351, 310, 387, 319] | — |
| 3 | `FY 2026 Appropriotions  Report 118 Arizo na Cri m i na I J u stice Co m m iss io n` | [56, 37, 567, 48] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/1 — ODL missed most visual headings (verify)
- `footnote_attachment` — **applies** (9 marker candidates in pypdf text)

## governors-state-agency-detail-fy27 p.32 — `cross-doc-name`

**PDF:** `samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` — open page **32**
**Output:** `samples/extractor-output/opendataloader/governors-state-agency-detail-fy27/page-32.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `Funding` | [39, 738, 74, 748] | r1,c1 |
| 2 | `FY 2027` | [519, 408, 553, 418] | r1,c2 |
| 3 | `All dollar amounts are expressed in thousands.` | [35, 19, 201, 28] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **3** _(suggested)_ — No visual headings expected; ODL also detected none
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-baseline-fy27 p.143 — `cross-doc-name`

**PDF:** `samples/raw-pdfs/jlbc-baseline-fy27.pdf` — open page **143**
**Output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy27/page-143.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `inflation adjustment of 2.48% and a state population adjustment of 1.28% pursuant to A.R,S. 5It-292'` | [330, 718, 542, 743] | — |
| 2 | `4,942,30O L0,845,900` | [248, 366, 292, 388] | — |
| 3 | `FY 2027 Baseline 48 AHCCCS` | [59, 34, 570, 46] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/1 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## jlbc-baseline-fy23 p.112 — `cross-doc-name`

**PDF:** `samples/raw-pdfs/jlbc-baseline-fy23.pdf` — open page **112**
**Output:** `samples/extractor-output/opendataloader/jlbc-baseline-fy23/page-112.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `Background  - ln January 20!7 , the Centers for Medicare and Medicaid Services (CMS)  approved AHCCCS'  request` | [55, 714, 283, 739] | — |
| 2 | `Statutory Changes Long-Term  Budget lmpacts County Contributions Program  Components Tobacco  Master Settlement Agreemen` | [73, 369, 233, 443] | — |
| 3 | `FY 2023 Boseline 52 AHCCCS` | [56, 33, 565, 43] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **3** _(suggested)_ — No visual headings expected; ODL also detected none
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)

## agao-afr-fy25 p.177 — `misc, afr-notes`

**PDF:** `samples/raw-pdfs/agao-afr-fy25.pdf` — open page **177**
**Output:** `samples/extractor-output/opendataloader/agao-afr-fy25/page-177.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `STATE OF ARIZONA NOTES TO FINANCIAL STATEMENTS JUNE 30, 2025` | [218, 700, 394, 734] | — |
| 2 | `Local Trans Assistance Fund – State Treasurer (TR3848)` | [72, 581, 329, 592] | — |
| 3 | `A.R.S. § 35-391 B. requires governmental entities to disclose in their annual financial report the amount of any reward,` | [36, 56, 579, 102] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **3** _(suggested)_ — 3 headings detected vs ~3 CAPS candidates (good coverage)
- `footnote_attachment` — **applies** (6 marker candidates in pypdf text)

## governors-sources-and-uses-fy27 p.24 — `misc, summary-table`

**PDF:** `samples/raw-pdfs/governors-sources-and-uses-fy27.pdf` — open page **24**
**Output:** `samples/extractor-output/opendataloader/governors-sources-and-uses-fy27/page-24.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `General Fund Sources and Uses` | [111, 580, 266, 591] | — |
| 2 | `USES OF FUNDS` | [110, 326, 144, 330] | — |
| 3 | `All dollar amounts are expressed in thousands.` | [34, 7, 201, 15] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 1/3 — ODL missed most visual headings (verify)
- `footnote_attachment` — **applies** (4 marker candidates in pypdf text)

## jlbc-approps-fy26 p.49 — `misc, line-item-marker`

**PDF:** `samples/raw-pdfs/jlbc-approps-fy26.pdf` — open page **49**
**Output:** `samples/extractor-output/opendataloader/jlbc-approps-fy26/page-49.{json,md}`

**Spot-check cells** (open PDF, find these on the page, verify text matches and bbox surrounds the right region):

| # | content | bbox (PDF user-space) | row,col |
|---|---|---|---|
| 1 | `Arizona Department of Administration` | [59, 726, 282, 742] | — |
| 2 | `23,037,200u` | [502, 402, 550, 412] | — |
| 3 | `FY 2026 Appropriotions  Report 3 Arizona Deportment  of Administration` | [59, 38, 566, 48] | — |

**Auto-scores:**
- `cell_accuracy` = **3** — All distinct numeric tokens match pypdf reference.
- `multipage_reassembly` = **NA** — Archetype is not multi-page-table
- `header_detection` = **1** _(suggested)_ — 0/11 — ODL missed most visual headings (verify)
- `footnote_attachment` — **likely NA** (0 marker candidates in pypdf text)
