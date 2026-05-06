# Phase 0 Task 4 — Scouting Shortlist

Scouted 3472 pages across 6 PDFs. Pick ~3–5 from each archetype below to fill `samples/scoring-pages.yaml`.

Heuristics are simple (regex + counts), so candidates need a quick human eyeball before committing — open the PDF to the page, confirm it actually exhibits the archetype, swap if it doesn't.

## Multi-page tables (last page of a long table run) (target: 5 pages)

| doc_id | page | why |
|---|---|---|
| `jlbc-approps-fy26` | 520 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 1474 numbers) |
| `jlbc-approps-fy26` | 513 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 407 numbers) |
| `governors-state-agency-detail-fy27` | 535 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 304 numbers) |
| `governors-state-agency-detail-fy27` | 602 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 301 numbers) |
| `governors-state-agency-detail-fy27` | 587 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 281 numbers) |
| `jlbc-approps-fy26` | 27 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 280 numbers) |
| `governors-state-agency-detail-fy27` | 564 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 280 numbers) |
| `governors-state-agency-detail-fy27` | 609 | Last page of a 5-page run where every page has ≥25 numeric tokens and an FY header (window total: 280 numbers) |

## Restated AFR tables (target: 3 pages)

| doc_id | page | why |
|---|---|---|
| `agao-afr-fy25` | 163 | Contains 'prior year' marker; 94 numeric tokens; fund-balance/financial-statement language |
| `agao-afr-fy25` | 128 | Contains 'prior year' marker; 72 numeric tokens; fund-balance/financial-statement language |
| `agao-afr-fy25` | 126 | Contains 'prior year' marker; 68 numeric tokens; fund-balance/financial-statement language |
| `agao-afr-fy25` | 177 | Contains 'prior year' marker; 3 numeric tokens; fund-balance/financial-statement language |

## Multi-column narrative (Baseline Book agency descriptions) (target: 3 pages)

| doc_id | page | why |
|---|---|---|
| `jlbc-baseline-fy27` | 163 | Has Mission/Program-Description heading; 5367 chars (prose-heavy); 9 numeric tokens (mixes prose with inline table) |
| `jlbc-baseline-fy27` | 496 | Has Mission/Program-Description heading; 5111 chars (prose-heavy); 11 numeric tokens (mixes prose with inline table) |
| `jlbc-baseline-fy27` | 140 | Has Mission/Program-Description heading; 4823 chars (prose-heavy); 39 numeric tokens (mixes prose with inline table) |
| `jlbc-baseline-fy23` | 125 | Has Mission/Program-Description heading; 4763 chars (prose-heavy); 15 numeric tokens (mixes prose with inline table) |
| `jlbc-baseline-fy23` | 140 | Has Mission/Program-Description heading; 4666 chars (prose-heavy); 19 numeric tokens (mixes prose with inline table) |
| `jlbc-baseline-fy27` | 456 | Has Mission/Program-Description heading; 4663 chars (prose-heavy); 19 numeric tokens (mixes prose with inline table) |

## Footnote-heavy schedules (target: 3 pages)

| doc_id | page | why |
|---|---|---|
| `governors-state-agency-detail-fy27` | 6 | 10 footnote markers (parens like (1), letter (a), or stars); 88 numeric tokens - looks like a schedule |
| `jlbc-approps-fy26` | 101 | 7 footnote markers (parens like (1), letter (a), or stars); 61 numeric tokens - looks like a schedule |
| `jlbc-approps-fy26` | 164 | 9 footnote markers (parens like (1), letter (a), or stars); 24 numeric tokens - looks like a schedule |
| `jlbc-approps-fy26` | 136 | 5 footnote markers (parens like (1), letter (a), or stars); 50 numeric tokens - looks like a schedule |
| `governors-state-agency-detail-fy27` | 112 | 7 footnote markers (parens like (1), letter (a), or stars); 16 numeric tokens - looks like a schedule |
| `governors-state-agency-detail-fy27` | 143 | 8 footnote markers (parens like (1), letter (a), or stars); 6 numeric tokens - looks like prose |

## Cross-doc-name entity-resolution stress (target: 3 pages)

| doc_id | page | why |
|---|---|---|
| `governors-state-agency-detail-fy27` | 32 | 'AHCCCS' appears 7× on a content-rich page (2427 chars) |
| `jlbc-baseline-fy23` | 112 | 'AHCCCS' appears 11× on a content-rich page (3768 chars) |
| `jlbc-baseline-fy27` | 143 | 'AHCCCS' appears 19× on a content-rich page (3730 chars) |

## Misc (variety — different doc types / page styles) (target: 3 pages)

| doc_id | page | why |
|---|---|---|
| `agao-afr-fy25` | 177 | AFR prose page (likely Notes-to-Financial-Statements section); 4434 chars, 3 numbers — tests narrative/disclosure handling vs. all-table pages |
| `governors-sources-and-uses-fy27` | 24 | Early Sources-and-Uses summary table (176 numbers, page near start) |
| `jlbc-baseline-fy23` | 90 | FY23 Baseline agency overview (Mission + small inline table) — pair with FY27 candidate for cross-year drift |
| `jlbc-approps-fy26` | 49 | Approps page with explicit SPECIAL LINE ITEMS / OPERATING LUMP SUM marker; 81 numbers |
