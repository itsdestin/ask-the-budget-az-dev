# Arizona State Budget — Document Model & Cross-Cut Summaries

**Date:** 2026-05-06
**Audience:** Future contributors (and future-us). Captures what we've learned about how the source data is published, structured, and related across publishers and years — knowledge that's invisible from reading code alone.

This doc complements (but doesn't replace) `2026-05-05-chunk-shape-decisions.md`. The chunk-shape doc says how chunks should look. This doc says what the source data looks like and what's available beyond the obvious singlefile PDFs.

## TL;DR

1. **JLBC ships every annual budget document four ways**: a monolithic singlefile PDF, a link-navigable index that points to per-section PDFs, an agency-index that points to per-agency PDFs, and a set of cross-cutting summary PDFs (s1-s90 etc.). We've been ingesting only the first format.
2. **Slug is the canonical agency ID** — JLBC's URL filenames (`axs.pdf` for AHCCCS, `dot.pdf` for ADOT) are stable across years going back to FY 2015. We use them as `canonical_id`.
3. **Cross-cut summary PDFs are authoritative.** When an analyst asks "which funds does AHCCCS use?", `s18.pdf` (Other Appropriated Funds Summary by Agency) answers in a single chunk — better than scraping each agency's narrative.
4. **The Governor's docs use a different shape** (one PDF with proper outline tree, no per-agency split). AFR is a third shape (tagged PDF, multi-fund schedules). DOCX bills are a fourth.
5. **OCR drift in older JLBC docs is real** ("Boseline", "Appropriotions", "Deportment"). The matcher uses edit-distance fallbacks; chunks should pin canonical names rather than rely on extracted strings.

## 1. Publisher landscape

Four publishers, four formats:

| Publisher | What they ship | Formats | Provenance shape |
|---|---|---|---|
| **JLBC** (Joint Legislative Budget Committee) | Baseline Books (FY23-FY27 published), Appropriations Reports (FY15-FY26) | PDF (untagged), four parallel layouts (singlefile / link-nav TOC / per-agency / cross-cut sections) — see §2 | (page, bbox) — multi-page tables common |
| **Governor's Office** (OSPB) | State Agency Detail, Sources and Uses of State Funds | PDF (untagged but with rich outline tree) | (page, bbox) + outline-derived section path |
| **AGAO** (Auditor General) | Annual Financial Reports (AFR) | PDF (**tagged**, has structure tree) — composite of 7 sub-PDFs | (page, bbox) — cell-level structure available via OpenDataLoader |
| **Legislature** | Budget bills (e.g., SB 1735 / Chapter 233 of 2025) | DOCX (native) — custom paragraph styles drive section structure | (paragraph_id, table_cell_id) — no bbox needed |

Each is dissected below in §2-§3 (JLBC), §3a (Governor's), §3b (AGAO), §3c (Legislature). We have one or more samples of each on disk; see `samples/manifest.yaml`.

## 2. JLBC publishing structure (the deepest source — most of the corpus)

For each fiscal year, JLBC publishes the same content **four ways**:

```
                        JLBC FY 2027 Baseline Book
                                 │
   ┌────────────────────────┬────┴────────────────┬─────────────────────────────┐
   │                        │                     │                             │
   ▼                        ▼                     ▼                             ▼
27baselinesinglefile.pdf   27baselinelinks.pdf   27baseline/agencyindex.pdf   27baseline/<slug>.pdf  × 111
(monolithic, ~60 MB,        (1-page nav, links    (1-page index, links to       (per-agency PDFs,
 no outline,                 to 22 section PDFs    111 agency PDFs by slug,      ~20-50 KB each,
 our current ingest)         + agency index)       carries page-in-singlefile)   self-contained
                                                                                  per-agency content)
```

**Plus** a set of cross-cutting summary PDFs (described in §3 below).

### Practical consequences

- **The singlefile is what the user typically reads** but is the *worst* format to ingest. No outline. Untagged. ~60 MB for one fiscal year.
- **Per-agency PDFs are a much cleaner ingest unit.** Each `<slug>.pdf` contains one agency's full section (narrative + tables + appropriations footnotes). Boundaries are explicit. Smaller files = faster extraction.
- **The agency-index PDF is a metadata sidecar.** It gives us `(agency_canonical_name, slug, page-in-singlefile, per-agency-pdf-url)` for every agency. It's how we built `samples/entity-catalog.yaml`.
- **The link-navigable PDF** (`27baselinelinks.pdf`) is the table of contents for the section PDFs. It's how we discover the s-PDFs.

### URL conventions (verified across years)

```
Baseline Book:           https://www.azjlbc.gov/<YY>baseline/...
Appropriations Report:   https://www.azjlbc.gov/<YY>ar/...
Agency Index (within):   .../agencyindex.pdf
Per-agency content:      .../<slug>.pdf       (e.g. axs.pdf for AHCCCS)
Summary section:         .../s<N>.pdf         (e.g. s18.pdf — see §3)
Page-content section:    .../<page>.pdf       (e.g. 502.pdf — Revenue Forecast)
Topic-specific section:  .../<keyword>.pdf    (e.g. capitaloutlay.pdf, crr.pdf)
Link-navigable nav:      https://www.azjlbc.gov/budget/<YY>baselinelinks.pdf
```

`<YY>` is the **publishing year** which equals the fiscal year being projected (FY 2027 baseline lives at `27baseline/`). Approps reports follow the SAME convention but cover the just-enacted fiscal year (FY 2026 approps at `26ar/` documents the FY 2026 enacted budget).

JLBC has been using this URL convention going back at least to FY 2015 for Approps Reports. Baseline Books we've verified back to FY 2023; older ones may exist at different paths.

**Approps reports DO have a parallel cross-cut publishing system, just with different naming.** The baseline TOC is at `<YY>baselinelinks.pdf`; the approps TOC is at `<YY>ar/apprpttoc.pdf`. Verified back to FY 2015 on both `azjlbc.gov` and `azleg.gov/jlbc/`.

Naming convention difference:

| Baseline Book | Approps Report | Content shape |
|---|---|---|
| `<YY>baselinelinks.pdf` | `<YY>ar/apprpttoc.pdf` | Top-level link-navigable TOC |
| `s<N>.pdf` (s1, s2, s7, …) | `bh<N>.pdf` (Budget Highlights, where N is the page number where that section starts in the singlefile) + `bd<N>.pdf` (Budget Detail) + `<page>.pdf` (raw page-number-keyed sections) | Cross-cut summary tables |
| `agencyindex.pdf` | `agencyindex.pdf` | Per-agency PDF index (same name) |
| `<slug>.pdf` | `<slug>.pdf` | Per-agency content (same convention) |
| `capitaloutlay.pdf` | `capitaloutlay.pdf` | Capital outlay section (same name) |
| `crr.pdf` | `crr.pdf` | Consolidated retirement report (same name) |

### Approps Budget-Highlights / Budget-Detail mapping (FY26 example)

These approps section PDFs are roughly equivalent to baseline s-PDFs:

| Approps file | Baseline equivalent | Title |
|---|---|---|
| `bh2.pdf` | `s1.pdf` | FY 2025–FY 2028 Statement of General Fund Revenues and Expenditures |
| `bh3.pdf` | `s2.pdf` | FY 2026 State General Fund Budget Summary |
| `bh11.pdf` | (no direct) | General Fund Budget 4-Year Analysis |
| `bh20.pdf` | (no direct) | Summary of One-Time General Fund Adjustments |
| `bh25.pdf` | `s9.pdf` (similar) | Summary of One-Time General Fund Transfers |
| `bh26.pdf` | (no direct) | Graphs of FY 2026 Budget |
| `bh28.pdf` | (no direct) | "Then and Now" Comparisons (FY16–FY26) |
| `bd2.pdf` | `s18.pdf` | **Summary of Appropriated Funds by Agency** (the canonical "what funds does X agency use" cross-cut). **Phase 1a finding 2026-05-06:** s18 and bd2 represent the same logical view but have **different rendered column layouts** in practice — `funds/parser.py::parse_s18_table` works on s18 and yields 0 rows on bd2. They are NOT interchangeable for parsing; bd2 needs a parser revision (Phase 1b). |
| `bd4.pdf` | (no direct) | Summary of Capital Outlay Appropriations |
| `bd6.pdf` | (no direct) | Summary of Additional Operating and Statutory Appropriations |
| `bd8.pdf` | `s80.pdf` | Previously Enacted Appropriations FY 2026 and Beyond |
| `bd10.pdf` | (no direct) | Summary of Total Spending Authority (Appropriated and Non-Appropriated) |
| `bd12.pdf` | `s83.pdf` | State Personnel Summary by Agency |
| `452.pdf` | `s31.pdf` | Detailed List of General Fund Changes by Agency |
| `459.pdf` | `s43.pdf` | Detailed List of Other Fund Changes by Agency |
| `468.pdf` | `s54.pdf` | Summary of One-Time Other Fund Adjustments |
| `471.pdf` | (no direct) | FY 2026 General Fund Crosswalk of GAA to Approps Report Totals |
| `473.pdf` | (no direct) | FY 2026 Other Funds Crosswalk of GAA to Approps Report Totals |
| `482.pdf` | `s87.pdf` + `s90.pdf` | Budget Reconciliation Bills and Major Footnote Changes |

The page-number-keyed PDFs (`452.pdf`, `459.pdf`, `468.pdf`, etc.) are the approps equivalent of baseline's `s<N>.pdf` for the more detailed cross-cuts. JLBC's choice of naming is "the page number where this section starts in the singlefile," which incidentally varies year over year — so file names are NOT stable across years for approps Detailed-List sections. The TOC is the way to discover them.

The earlier rule of thumb is corrected: **approps reports do publish cross-cut summary PDFs, just with TOC-driven discovery rather than predictable filename conventions.** The TOC is at `<YY>ar/apprpttoc.pdf` (verified for FY15, FY18, FY21, FY24, FY26).

## 3. JLBC cross-cut summary PDFs (the under-leveraged data)

The link-navigable nav PDF references a set of summary section PDFs. Each is a focused cross-cut of the baseline data. Below is the FY 2027 baseline set; approps reports publish a parallel set under different filenames (`bh<N>.pdf`, `bd<N>.pdf`, `<page>.pdf` — see §2 for the full mapping).

**All 15 baseline cross-cuts are in `samples/raw-pdfs/`** as `jlbc-baseline-fy2027-s<N>.pdf`. **All 28 FY26 approps section PDFs** (the bh*, bd*, and page-keyed equivalents) are also on disk as `jlbc-approps-fy2026-{bh,bd,<page>}*.pdf`.

| File | Title | Shape | Why it matters |
|---|---|---|---|
| `s1.pdf`  | Statement of General Fund Revenues and Expenditures | Multi-year time series | Top-line GF view |
| `s2.pdf`  | FY 2027 Baseline Summary | High-level totals | The "headline number" page |
| `s7.pdf`  | Summary of Ongoing General Fund Spending by Agency | (Agency, FY26 enacted, FY27 baseline, change) | "What's the GF baseline for X?" answers cleanly |
| `s9.pdf`  | Summary of One-Time General Fund Spending by Agency | (Agency × line item, one-time amounts) | One-time vs ongoing distinction |
| `s15.pdf` | FY 2027 General Fund Summary by Agency | All-agencies GF summary | The single-page answer to most GF queries |
| **`s18.pdf`** | **FY 2027 Other Appropriated Funds Summary by Agency** | **(Agency, Fund, FY26, FY27, change) — multi-row per agency** | **"Which funds does X agency use?" / "Who appropriates from fund Y?"** |
| `s31.pdf` | General Fund Detailed List of FY 2027 Changes by Agency | Line-item changes with footnote refs | Change-tracking queries |
| `s43.pdf` | Other Funds Detailed List of FY 2027 Changes by Agency | Same shape, non-GF funds | Change-tracking, non-GF |
| `s54.pdf` | Summary of One-Time Other Fund Spending by Agency | Mirrors s9 for non-GF | One-time non-GF view |
| `s57.pdf` | FY 2026 Adjustments | Mid-year adjustments to enacted budget | Mid-year supplemental queries |
| `s58.pdf` | Summary of Federal and Other Non-Appropriated Fund Expenditures | Federal + non-appropriated | Major — federal funding queries answer here |
| `s80.pdf` | Previously Enacted Appropriations FY 2027 and Beyond | Multi-year previously-enacted | Out-year visibility |
| `s83.pdf` | State Personnel Summary by FTE | Headcount by agency | FTE / staffing queries |
| `s87.pdf` | FY 2027 Budget Reconciliation Bill Provisions | BRB legal text references | Legislative trail |
| `s90.pdf` | FY 2027 General Appropriation Act Provisions | GAA legal text references | Legislative trail |

Plus topic-specific section PDFs:
- `capitaloutlay.pdf` — Capital Outlay Estimates
- `502.pdf` — General Fund Revenue Forecast
- `507.pdf` — Budget Stabilization Fund
- `crr.pdf` — Consolidated Retirement Report
- `517.pdf` — Technical Budget Assumptions
- `522.pdf` — Directory of Members and JLBC Staff

### Why these matter for our retrieval

A query like "What funds does AHCCCS use?" has THREE possible source chunks:

1. **The agency narrative chunk** (from `axs.pdf`) — mentions funds inline, attributing them to specific programs. Detailed but verbose.
2. **The fund row in s18.pdf** — single row: `AHCCCS Fund | $14.5B | $14.6B | +$112M`. Compact, definitive, but no narrative context.
3. **A subset of s31/s43.pdf rows** — change-by-change line items. Useful for change queries.

Different queries should retrieve different chunk types. The s-PDFs are NOT redundant with per-agency narrative — they're a **complementary index** that's better for tabular cross-cut queries.

For our chunking layer, this implies:
- **The s-PDFs ingest as small, focused docs** (each is a single tabular cross-cut with a clear caption).
- **Each s-PDF row** maps to a chunk that carries its full headers + the doc's caption as context.
- **Retrieval naturally surfaces** s-PDFs for cross-cut queries and narrative chunks for "explain X" queries — both are answerable, often the s-PDF chunk wins on token efficiency.

## 3a. Governor's State Agency Detail — outline-anchored cross-cuts

`samples/raw-pdfs/governors-state-agency-detail-fy27.pdf` is monolithic (636 pages, 144 outline entries) but the **outline tree is rich** and gives us cross-cut anchors equivalent to JLBC's s-PDFs without separate file downloads.

L1 sections (8 total):

| L1 | Page | Title |
|---|---|---|
| 1 | 2 | Table of Contents |
| 2 | 4 | Overview |
| 3 | 6 | **Agency Operating Budget Detail** (102 L2 entries — one per agency) |
| 4 | 466 | Additional Changes |
| 5 | 503 | Revenue by Agency |
| 6 | 510 | Assumptions and Methodology |
| 7 | 513 | **Summary of Appropriated Funds** |
| 8 | 626 | Reference (glossary, org chart, acknowledgements) |

L2 cross-cut sections (anchored by page in the outline tree):

| Page | Section |
|---|---|
| p4 | Executive Budget In-A-Flash |
| p466 | Allocation of Statewide Adjustments |
| p492 | Funds Transfers to the Automation Project Fund |
| p493 | FY 2026 Proposed Fund Transfers |
| p494 | Executive Budget Legislative Changes |
| p499 | Major Budget Footnote Changes |
| p503 | General Fund Revenue by Agency |
| p506 | Other Fund Revenue by Agency |
| p513 | Expenditure Detail of FY 2025 Appropriations |
| p534 | Expenditure Detail of FY 2026 Base Appropriations |
| p557 | Expenditure Detail of FY 2026 Executive Budget |
| p580 | Expenditure Detail of FY 2027 State Agency Requests |
| p601 | Expenditure Detail of FY 2027 Executive Budget |
| p623 | Administrative Costs |
| p626 | **Glossary, Budget Terms** |
| p631 | **Glossary, Acronyms** |
| p634 | State Government Organizational Chart |
| p635 | Resources |

For chunking, the outline tree means we don't need to detect section boundaries — the publisher already declared them. Chunk boundaries follow outline page-spans directly.

### Glossary as system-prompt context

Pages 626-633 contain a two-part glossary:

- **Part 1: Budget Terms** — formal definitions of "actual expenditure," "administrative adjustment," "85/15 funding," etc. About 40+ terms with paragraph-length definitions.
- **Part 2: Acronyms** — comprehensive AZ-specific acronym list (A.R.S., AAC, ABOR, ACDHH, ACJC, ADCRR, ADJC, ADM, ADOT, AHCCCS, ALTCS, …).

This is high-value system-prompt context for the LLM — gives it canonical AZ budget vocabulary plus authoritative definitions for "what does '85/15' funding mean" type questions. Suggest extracting at ingestion and pinning to system-prompt context, parallel to the JLBC writing draft (§10).

### State Government Organizational Chart (p634)

Worth extracting separately as a structural reference. Maps agencies to departments to branches — useful for cross-doc entity normalization (e.g., recognizing that "ADJC" is in the Executive Branch under Public Safety umbrella).

## 3b. Governor's Sources and Uses — large monolithic table dump

`samples/raw-pdfs/governors-sources-and-uses-fy27.pdf` is 919 pages with only 8 outline entries — virtually no structure. Outline:

```
L1 p2  Table of Contents
L1 p3  Index of Other Funds by Agency
  L2 p24  General Fund Sources and Uses
  L2 p25  Sources and Uses of All Major State Funds
L1 p917 Reference
  L2 p917 General Fund Comparative Balance
  L2 p918 Resources
  L2 p919 Acknowledgement
```

The 900-page bulk between p25 and p917 is essentially a **per-fund table dump** — one or more pages per appropriated fund, with consistent layout. The outline is silent about what's in those pages. The cross-cut data we want for fund-level queries lives here, but extraction needs:

- **Index of Other Funds by Agency (p3-p23)** for the index of which fund is on which page
- **Reading the index PDF link annotations** (likely present, untested) to drive per-fund discovery

This is the **largest and most challenging** ingestion target in the corpus. May be a Phase 2 problem if Phase 1 can answer most fund-level queries from the JLBC s18.pdf cross-cut.

## 3c. AGAO Annual Financial Report (AFR) — composite tagged PDF

`samples/raw-pdfs/agao-afr-fy25.pdf` is 181 pages with 39 outline entries. The outline reveals an unusual structure: **the AFR is a concatenation of 7 separate source PDFs**, with the outline preserving the original file boundaries:

```
L1: 2. AFR25 FINANCIAL STATEMENTS - PDF.pdf  (pp.1-7)
  L2: Stmt 1 / Trend Data / Stmt 2 / RevExp Chart / Stmt 3
L1: 3. AFR25 GF FORMATTED - PDF.pdf  (pp.8-41)
  L2: 1_GF Formatted, blank pages
L1: 4. AFR25 CP FORMATTED - PDF.pdf  (pp.42-49)
L1: 5. AFR25 OTHER FORMATTED - PDF.pdf  (pp.50-109)
L1: 6. AFR25 FUND BALANCE - PDF.pdf  (pp.110-172)
L1: 7. AFR25 NOTES TO FS - PDF.pdf  (pp.174-181)
  L2: Note 1 — Summary of Significant Accounting Policies
    L3: Note 2 — Description of Financial Statements
    L3: Note 3 — Statement of Expenditures … Description of Selected Columns
    L3: Note 4 — Budget Stabilization Fund
    L3: Note 5 — Proposition 301
    L3: Note 6 — Statement of Revenues, Expenditures and Changes in Fund Balance
    L3: Note 7 — Disproportionate Share Hospital Payments
    L3: Note 8 — Credit Card Payments by Governmental Entities
    L3: Note 9 — Coronavirus Relief Fund and ARP Act of 2021
    L3: Note 10 — AHCCCS Appropriation Reduction
    L3: Note 11 — Combining Financial Statements
    L3: Note 12 — Administrative Adjustments
```

### What this tells us

- **AGAO assembles AFR from 7 sub-files** — the original sub-files might be available individually on AGAO's website. If so, ingesting them as separate documents is cleaner than parsing the composite. Worth a Phase 1 probe of `gao.az.gov/`.
- **The Notes section (pp.174-181) is a goldmine** for entity normalization and footnote attachment. Note 6 explicitly defines the Statement of Revenues, Expenditures and Changes in Fund Balance — the exact table shape we saw on p163. Notes can be linked to the table chunks they describe.
- **The AFR is tagged** (verified via OpenDataLoader's `use_struct_tree=True`) — outline + structure tree means cell-level extraction with proper section context.
- **L1 entries with duplicate names** ("6. AFR25 FUND BALANCE - PDF.pdf" appears at both p1 and p110) — the assembly process left a redundant outline entry. Filter or de-dup at ingestion.

## 3d. Budget bills (DOCX) — paragraph styles drive structure

`samples/raw-docx/budget-bill-sb1735-2025.docx` is the FY 2026 General Appropriations Act (Chapter 233 of 2025). 2,739 paragraphs, 1 cover-page table.

### Two-part body structure

The bill has two distinct parts:

**Part 1 (paragraphs 0–2370ish): Agency Appropriations Tables.** Each agency gets a section with appropriation line items. Section titles use `Normal` style (paragraphs like "Sec. 25. DEPARTMENT OF CHILD SAFETY" at p15, "Sec. 31. STATE DEPARTMENT OF CORRECTIONS" at p114). Body paragraphs use mostly `P 06-00` (the most common style — 703 instances), `P 10-10` (173 instances), `P 05-00`, `P 00-00` for indented sub-items.

**Part 2 (paragraphs 2374+): Provisions.** 46 individual sections marked by **custom paragraph styles `SEC 06-18` (28 sections)** and **`SEC 06-19` (18 sections)**. These are the structural markers — each tagged paragraph IS a section heading. Examples:

- `SEC 06-18`: "Sec. Supplemental appropriation; acupuncture board of examiners; fiscal year 2024-2025"
- `SEC 06-18`: "Sec. Appropriation reduction; Arizona health care cost containment system administration; fiscal year 2024-2025"
- `SEC 06-19`: "Sec. Fund balance transfer; state highway fund; fiscal year 2025-2026"
- `SEC 06-19`: "Sec. Joint legislative budget committee; projects; review; approval"

**Pattern observation:** the heading text after "Sec. " uses **semicolon-separated phrases** that map to parameters of the appropriation:
```
<action>; <agency or fund>; <purpose modifier>; <fiscal year>; <special clauses>
```

This is parseable — the chunking layer can extract `(action, target, fiscal_year)` tuples directly from heading text, no NLP. Action-types observed:

- "Supplemental appropriation"
- "Appropriation reduction"
- "Appropriation"
- "Fund balance transfer"
- "Reduction in school district state aid apportionment"
- "Department of law; general agency counsel charges"
- "Agency spending and encumbrances; quarterly report"
- (and admin/definition sections)

### Practical consequences

- **Walk paragraph styles to find sections.** `SEC 06-18` and `SEC 06-19` are the section-boundary markers in Part 2; in Part 1, agency headers are detected by all-caps "DEPARTMENT OF X" patterns at `Normal` style.
- **Each `SEC 06-*` paragraph anchors a section chunk.** The section runs from the heading paragraph until the next `SEC 06-*` paragraph.
- **`paragraph_id` is the citation.** No bbox; the `w14:paraId` field in the DOCX XML is stable per-paragraph and survives re-saves (verified via Phase 0 Task 5b dual-run diff).
- **Agency mentions in Part 1 should map to canonical_id** via the `agency:<slug>` catalog. The bill's "DEPARTMENT OF CHILD SAFETY" → `agency:dcs` etc.

### Cross-references in bill text

Paragraph text frequently references statutory sections (e.g., "section 35-142, Arizona Revised Statutes," "section 44-1531.02"). These are out-of-corpus pointers but should be captured as metadata for citation enrichment if we ever add A.R.S. lookup.

## 4. Agency identification — slug as canonical_id

Verified facts about the JLBC agency-slug system from multi-year corpus analysis (FY15-FY27, 17 indexes, 145 unique slugs):

- **Slugs are MOSTLY stable across years.** AHCCCS has been `axs` since FY 2015. ADOT has been `dot`. Agencies renamed at the public-facing level (ADC → ADCRR for Corrections) kept their JLBC slug (`adc`).
- **But slugs DO get renamed occasionally.** Map below.
- **Slugs don't always match the public acronym.** AHCCCS's slug is `axs`, not `ahcccs`. DEMA's slug is `ema`. ASLD's slug is `lan`. Hardcoded acronym → slug map lives in `scripts/build_agency_catalog.py`.
- **Some slugs encode sub-agency relationships.** ADOA has primary slug `doa` plus `doa-apf` (Automation Projects Fund) and `doa-sfd` (School Facilities Division) for budget-distinct sub-units.
- **Agency name varies across years even when slug is stable.** "Corrections, Department of" → "Corrections, State Department of" → ADCRR years had a different name still. The catalog tracks `names_observed_jlbc[name] → list of years`.

### 4.1 JLBC web host migration (FY15-FY22 vs FY23+)

Older approps reports (FY15-FY22) link to a **different host** than newer ones:

```
FY15-FY22 approps:  http://www.azleg.gov/jlbc/<YY>AR/<slug>.pdf
FY23+ everything:   https://www.azjlbc.gov/<YY>{baseline,ar}/<slug>.pdf
```

The catalog builder accepts both forms. Failing to whitelist `azleg.gov/jlbc/` was a real bug — it dropped 25 historical slugs from the catalog (12 years of approps history). Fixed in `scripts/build_agency_catalog.py`.

### 4.2 Slug renames

A handful of agencies have had their JLBC slug changed across years. The original slug stops appearing the year the new slug appears. Captured in `samples/agency-slug-aliases.yaml`. Notable cases:

| Old slug | Years used | New slug | Years used | What happened |
|---|---|---|---|---|
| `rev` | FY15-FY26 | `dor` | FY27+ | Department of Revenue — slug rename |
| `doaapf` | FY15 | `doa-apf` | FY16+ | Hyphenation convention added |
| `doacfs` | FY15-FY16 | `doa-cfs` / `doa-csf` / removed | varies | Naming churn |
| `uniasue`, `uniasum`, `uniasuw` | FY15-FY20 | `uniasu` | FY21+ | ASU East/Main/West merged into single ASU slug |

The aliases file is the source of truth — Phase 1 ingestion must check the alias map when resolving older docs.

### 4.3 Agency lifecycle (FY15-FY27)

The 17-index multi-year sweep reveals real organizational history:

- **30 slugs** appear in FY15 approps but NOT FY27 baseline → eliminated, merged, or renamed.
- **14 slugs** appear in FY27 baseline but NOT FY15 approps → newly created or split out.
- Per-index slug counts have been **gradually shrinking** (FY15: 126, FY27: 110) — consolidation trend.

Why this matters for analysts: a fiscal analyst may ask "what happened to the Department of Weights and Measures?" or "how was FY 2018 funding distributed for the State Boxing Commission?" — both real eliminated agencies. The catalog's `first_seen` / `last_seen` per slug + the slug-aliases file give us authoritative answers.

Full eliminated/added-since lists generated by `scripts/build_agency_catalog.py` and pinned in `samples/agency-slug-aliases.yaml`.

### 4.4 Per-agency PDF outline trees = program-level entity layer

When you download a per-agency PDF (e.g. `https://www.azjlbc.gov/27baseline/axs.pdf`), it carries its **own PDF outline tree** describing the agency's internal program structure:

- **AHCCCS (`axs.pdf`, 20 pages, 6 outline entries):** Operating Budget, Administration, Medicaid Services, Non-Medicaid Behavioral Health Services, Hospital Payments, Other Issues
- **DPS (`dps.pdf`, 13 pages, 18 entries):** Operating Budget, ACTIC, Anti-Human Trafficking Grant Fund Deposit, AZPOST, Border Drug Interdiction, Civil Air Patrol Maintenance, DPS Crime Lab Assistance, Fentanyl Prosecution / Diversion / Testing Fund, …
- **DES (`des.pdf`, 22 pages, 9 entries):** Administration, Aging and Adult Services, Benefits and Medical Eligibility, Child Support Enforcement, Developmental Disabilities (3 sub-entries), Employment and Rehabilitation Services
- **Supreme Court (`judsup.pdf`, 8 pages, 7 entries):** Judges Compensation, Administrative Costs, Probation Programs, Other Programs, Other Issues, CORP Employer Contribution Increase, …

These outline entries are JLBC's authoritative program-level taxonomy below the agency. They:

- Are exactly the chunk-build section_path elements we need (chunk-shape D6 — header propagation).
- Match line-item / program names in the budget bill (DOCX) and appropriations report.
- Resolve the program-level entity catalog problem the chunk-shape doc deferred.

Caveat: **not every per-agency PDF has an outline.** ADOT (`dot.pdf`) has 0 outline entries despite 10 pages of content. Board of Education (`boe.pdf`) has 0 entries. So outline-driven program extraction is opportunistic, not universal — when present it's authoritative; when absent we fall back to header-walk extraction from the page content.

The catalog is at `samples/entity-catalog.yaml`. 157 canonical agencies after the host-filter fix (was 132), 70 of 84 sample sweep candidates auto-matched. See the chunk-shape doc for how the agency catalog is consumed in chunking.

## 5. Provenance layers — what to cite where

A chunk needs an unambiguous citation back to a verifiable source. The right citation layer depends on the source:

| Source | Citation shape |
|---|---|
| JLBC singlefile (current ingest) | `(doc_id, page_in_singlefile, bbox)` |
| JLBC per-agency PDF (alt ingest) | `(doc_id="jlbc-baseline-fy27-axs", page_in_per_agency_pdf, bbox)` plus a back-reference to `page_in_singlefile` for cross-citation parity |
| JLBC summary section (s18, s31 etc.) | `(doc_id="jlbc-baseline-fy27-s18", page, bbox, row_label)` — row-label is critical because s-PDFs are tabular |
| Governor's State Agency Detail | `(doc_id, page, bbox)` + section_path from outline tree |
| AFR | `(doc_id, page, bbox)` + cell row/col indices from tagged structure |
| Budget bill DOCX | `(doc_id, paragraph_id, table_cell_id)` — no bbox |

## 5a. Cross-publisher document relationships

Each fiscal year produces a **predictable cycle of documents** from the four publishers, in roughly this temporal order:

1. **August (year before fiscal year):** Agency budget requests due to OSPB.
2. **January:** Governor's State Agency Detail + Sources and Uses (FY27 docs published Jan 2026).
3. **January–March:** Legislature debates, committees mark up budget.
4. **JLBC publishes Baseline Book** (parallel to legislative process).
5. **April–June:** Legislature passes the General Appropriations Act + Budget Reconciliation Bills (DOCX bills like SB 1735).
6. **June:** Governor signs/vetoes (line-item veto on appropriations possible).
7. **JLBC publishes Appropriations Report** documenting enacted budget (typically late summer / early fall).
8. **Following December:** AGAO publishes Annual Financial Report covering the now-completed prior fiscal year (FY25 AFR published Dec 2025).

This means at any given time, the corpus contains roughly:

```
FY (current)   FY (prior)    FY (two prior)
─────────────  ────────────  ──────────────
Gov S&U        Approps Rpt   AFR
Gov SAD        (enacted)     (audited)
Baseline       AFR
Bills          
```

Cross-doc analyst queries naturally span these:

- "Did the Legislature appropriate what the Governor recommended for X?" — Gov SAD vs Approps Report (same FY)
- "How did actual spending compare to enacted?" — Approps Report vs AFR (FY-1 enacted vs FY-1 audited)
- "What's changed since last year's baseline?" — current Baseline vs prior Approps Report

These relationships have to be discoverable from chunk metadata: every chunk carries `(publisher, doc_type, fiscal_year)` so retrieval can fan out across the right (publisher × fiscal_year) combinations.

## 6. Cross-doc relationships analysts care about

Real fiscal queries cross documents. Our retrieval needs to surface the right doc for each query type.

| Query archetype | Best source | Why |
|---|---|---|
| "What's the FY 2027 baseline for X?" | JLBC Baseline (per-agency or s15) | Baseline is the JLBC's projected starting point |
| "What did the legislature actually appropriate for X?" | JLBC Approps Report (per-agency) | Approps reports document enacted-budget reality |
| "What did the Governor recommend?" | Gov State Agency Detail | Executive's recommendation |
| "What changed from Gov rec to GAA?" | Cross-join Gov + Approps | Two retrievals + reasoning |
| "Show me the legal text appropriating $X to Y" | Budget bill DOCX | Bills are the legal source |
| "What's the year-end balance for fund Y?" | AFR | AFR is the audited financial reality |
| "Which agencies got increases over $50M?" | s31 (GF) or s43 (other) | Pre-aggregated change tables |
| "What funds does X agency draw from?" | s18 | Pre-aggregated cross-cut |
| "FTE headcount for X over time?" | s83 (multi-year) | Pre-aggregated FTE table |

The takeaway: **multi-doc retrieval is required**, but for a meaningful slice of analyst queries the answer lives in a single s-PDF chunk.

## 7. Known gotchas / OCR drift / pitfalls

Captured during Phase 0 work; will surface again in Phase 1 ingestion.

- **OCR drift in JLBC documents.** "Baseline" frequently OCRs as "Boseline"; "Appropriations" → "Appropriotions"; "Department" → "Deportment"; "General" → "Generol". Our footer regex and normalization layer absorb these via edit-distance fallbacks; chunk metadata pins the canonical name from the manifest, not the extracted string.
- **Page numbers in agency-index entries refer to the singlefile PDF.** They do NOT refer to the per-agency PDF (which starts at page 1 internally). When citing from a per-agency PDF, we keep both numbers — the singlefile page for cross-doc parity, the per-agency page for the citation viewer.
- **Multi-page tables span 2-6 pages** in JLBC docs (and AFR fund-balance schedules). Bbox provenance is multi-rect. The chunking layer treats these as one logical chunk per spec D2.
- **Column attribution in untagged JLBC tables** is what made us pick MinerU over OpenDataLoader for that publisher — see chunk-shape doc D4.
- **Some "agency" links in the index are sections, not agencies.** `capitaloutlay`, `s7`, `390` (page-content link). Filter rule: agency slug must match `^[a-z]+(-[a-z]+)*$` and not be in the known section-slug blocklist. Implemented in `scripts/build_agency_catalog.py`.
- **The Governor's outline-tree includes 144 entries** but only the level-2 entries under "Agency Operating Budget Detail" are agencies. Filter as we do.
- **JLBC's slug for the Treasurer is `tre`**, for the Auditor General `legaud`, for Commerce Authority `aca`. None match the public acronym. Build the map; don't guess.
- **"Department of Law" is the same as "Attorney General"** in JLBC's vocabulary (slug `att`). One of those edge cases the matcher handles via hardcoded synonym.

## 8. What we have on disk now

```
samples/raw-pdfs/
├── jlbc-baseline-fy2023-agency-index.pdf  ┐
├── jlbc-baseline-fy2024-agency-index.pdf  │
├── jlbc-baseline-fy2025-agency-index.pdf  │ 5 baseline indexes
├── jlbc-baseline-fy2026-agency-index.pdf  │ (FY23-FY27)
├── jlbc-baseline-fy2027-agency-index.pdf  ┘
│
├── jlbc-approps-fy2015-agency-index.pdf   ┐
├── jlbc-approps-fy2016-agency-index.pdf   │
├── jlbc-approps-fy2017-agency-index.pdf   │
├── jlbc-approps-fy2018-agency-index.pdf   │
├── jlbc-approps-fy2019-agency-index.pdf   │ 12 approps indexes
├── jlbc-approps-fy2020-agency-index.pdf   │ (FY15-FY26)
├── jlbc-approps-fy2021-agency-index.pdf   │
├── jlbc-approps-fy2022-agency-index.pdf   │
├── jlbc-approps-fy2023-agency-index.pdf   │
├── jlbc-approps-fy2024-agency-index.pdf   │
├── jlbc-approps-fy2025-agency-index.pdf   │
├── jlbc-approps-fy2026-agency-index.pdf   ┘
│
├── jlbc-baseline-fy2027-s1.pdf            ┐
├── jlbc-baseline-fy2027-s2.pdf            │
├── jlbc-baseline-fy2027-s7.pdf            │
├── jlbc-baseline-fy2027-s9.pdf            │
├── jlbc-baseline-fy2027-s15.pdf           │
├── jlbc-baseline-fy2027-s18.pdf           │ 15 summary section
├── jlbc-baseline-fy2027-s31.pdf           │ PDFs for FY27 baseline
├── jlbc-baseline-fy2027-s43.pdf           │
├── jlbc-baseline-fy2027-s54.pdf           │
├── jlbc-baseline-fy2027-s57.pdf           │
├── jlbc-baseline-fy2027-s58.pdf           │
├── jlbc-baseline-fy2027-s80.pdf           │
├── jlbc-baseline-fy2027-s83.pdf           │
├── jlbc-baseline-fy2027-s87.pdf           │
├── jlbc-baseline-fy2027-s90.pdf           ┘
│
├── jlbc-baseline-fy27.pdf                 — singlefile (Phase 0 sample)
├── jlbc-baseline-fy23.pdf                 — singlefile
├── jlbc-approps-fy26.pdf                  — singlefile
├── governors-state-agency-detail-fy27.pdf
├── governors-sources-and-uses-fy27.pdf
└── agao-afr-fy25.pdf

samples/raw-docx/
└── budget-bill-sb1735-2025.docx
```

Plus `samples/entity-catalog.yaml` (canonical agency catalog) and the existing chunk-shape decisions doc.

## 9. Implications for Phase 1

> **Note 2026-05-06:** Phase 1 was subsequently split into **Phase 1a** (ingest + chunking — closed 2026-05-06 under slice scope, tag `phase-1a-validated-slice`), **Phase 1b** (storage + retrieval, in planning), and **Phase 1c** (companion + UI, not started). The implications below mostly map to Phase 1a + 1b; see those plan docs for execution detail. The bd2/s18 footnote on the table at line 98 captures one Phase 1a finding (parser handles s18 but not bd2) that this section's "Cross-cut indexing" bullet did not anticipate.

When Phase 1 ingestion is implemented, the data-model decisions to make:

1. **Primary ingest unit per source.** Likely:
   - JLBC: per-agency PDFs (`<slug>.pdf`) as primary content + s-PDFs as cross-cut sidecars + agency-index for entity catalog.
   - Governor's: monolithic PDF with outline-driven section split.
   - AFR: monolithic PDF with structure-tree-driven section split.
   - Bills: monolithic DOCX with paragraph/cell parsing.
2. **Cross-cut indexing.** The s-PDFs should be ingested as their own chunks AND optionally linked to per-agency chunks (a "see also" relation in the citation layer when both forms of an answer exist).
3. **Multi-year coverage scaling.** With 12 approps reports (FY15-FY26) + 5 baselines (FY23-FY27), the doc count grows fast. Ingestion needs to handle `years × per-agency-pdfs` (~111 × 17 = ~1900 per-agency PDFs) plus the s-PDFs (15 × 17 = ~255). Plus singlefile fallbacks for the few cases where per-agency split isn't available. Manageable but plan for it.
4. **Discovery from publisher URLs.** The build_agency_catalog approach (parse the agency index PDF, extract link rects, get slug + page) generalizes — every JLBC year-doc has the same shape. Phase 1 ingestion can drive itself from the index PDFs.

## 10. Domain-knowledge reference

`docs/reference/jlbc-writing-draft-final.docx` — Destin's own primer on the Arizona State Budget. Covers:

- Budget formation process (Governor → Legislature → enactment, Feed Bill, BRBs)
- Key organizations (OSPB, JLBC, JCCR, FAC) — formal definitions of how each operates
- Budget forecasting (Legislature's 4-Sector Revenue Forecast, Governor's Forecast, the Baseline)
- The General Fund (Big 3 revenues: sales tax, individual income tax, corporate income tax)
- Other appropriated vs non-appropriated funds (FY22: $5.9B appropriated other, $41.7B non-appropriated)
- One-time vs ongoing expenditures distinction
- Politics (Governor + Legislature dynamics, contentious issue patterns)
- State Accounting quirks (ADOR doesn't collect all revenues; carryover accounting differences across publishers)

**This is distinct from the source data we ingest.** The source data is *what the State did*; this primer is *how the State works*. Both are needed for analyst-quality answers — the source data for the specific number, the primer for the framing ("you asked about $5.9B in 'other funds' — here's the relevant context for that category").

**Suggested use in Phase 1+**: load (or summarize) this primer into system-prompt context so the model knows the conceptual frame analysts query in. The primer also serves as a glossary for terms like "Feed Bill," "Rainy Day Fund," "BRB," "the Big 3."

The primer was written July of FY23 with FY22 examples; the conceptual content is timeless but specific dollar examples are dated. Don't cite from it as if it were a current source.

## Pointer to the conversation

Reasoning trail and exploration leading to these decisions: chat transcript at `C:\Users\desti\.claude\projects\C--Users-desti-youcoded-dev\b8f34268-7e8a-4a51-be27-8321df34cca7.jsonl`.
