# Cross-Document Relationships

**Permanent reference.** What the four publishers each produce, when, and how their documents relate. This doc is the durable architectural reference for retrieval routing, query fan-out, and chunk metadata stamping. It supersedes the dated content scattered across `docs/superpowers/investigations/2026-05-06-data-model.md` §§ 5–6 — that doc captured what we learned during Phase 0 investigation; this one is the going-forward contract.

> **Read alongside:**
> - `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` — overall system design
> - `docs/superpowers/investigations/2026-05-06-data-model.md` — investigation-time deep dive on each publisher's structure (per-publisher details, OCR drift, slug-aliases history)
> - `docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md` — chunk-shape decisions D1–D7

## 1. Annual document cycle

Each fiscal year produces a predictable sequence of artifacts from the four publishers, in roughly this temporal order:

| Phase | When | Publisher | Artifact |
|---|---|---|---|
| Agency requests | August (year before FY) | Agencies → OSPB | Agency budget requests (internal) |
| Executive recommendation | January | Governor's Office (OSPB) | State Agency Detail PDF + Sources and Uses PDF |
| Legislative analysis | January–March | JLBC | Baseline Book |
| Mark-up & passage | January–June | Legislature | General Appropriations Act + Budget Reconciliation Bills (DOCX) |
| Enacted budget documentation | Late summer / early fall | JLBC | Appropriations Report |
| Audited reality | Following December (~18 mo after FY start) | AGAO | Annual Financial Report |

At any given moment the corpus contains roughly:

```
FY (current)        FY (prior)             FY (two prior)
──────────────      ──────────────         ──────────────
Gov S&U             Approps Report         AFR (audited)
Gov SAD             AFR (audited)
Baseline
Bills
```

A query about "FY 2025" can pull from up to seven different documents (Gov SAD/S&U, Baseline, ~3-5 budget bills, Approps Report, AFR) — five of them produced *after* the FY started, with the AFR most authoritative and most delayed.

## 2. Document → query archetype mapping

Different question shapes have different best-source documents. Retrieval should favor the right document type for the question, not just the most-relevant chunk by similarity.

| Query archetype | Best source | Why |
|---|---|---|
| "What's the FY N baseline for X?" | JLBC Baseline (per-agency PDF or s15 cross-cut) | Baseline is JLBC's projected starting point |
| "What did the Legislature actually appropriate for X?" | JLBC Approps Report (per-agency PDF) | Approps reports document enacted-budget reality |
| "What did the Governor recommend?" | Gov State Agency Detail | Executive's recommendation |
| "What changed from Gov rec to GAA?" | Cross-join Gov SAD + JLBC Approps | Two retrievals + reasoning |
| "Show me the legal text appropriating $X to Y" | Budget bill DOCX | Bills are the legal source |
| "What's the year-end balance for fund Y?" | AFR | AFR is audited financial reality |
| "Which agencies got increases over $50M?" | Approps `bd*` cross-cuts (or baseline `s31` for proposed) | Pre-aggregated change tables |
| "What funds does X agency draw from?" | Baseline `s18.pdf` (= approps `bd2.pdf`) | Pre-aggregated cross-cut |
| "FTE headcount for X over time?" | Baseline `s83.pdf` (= approps `bd12.pdf`) | Pre-aggregated FTE table |
| "What does '85/15 funding' / 'BSF' / 'feed bill' mean?" | Gov glossary (pp. 626–633) + JLBC writing draft | Domain primer, system-prompt context |

**Implication for retrieval:** chunks carry `(publisher, doc_type, fiscal_year)` metadata so the query router can fan out across the right (publisher × FY) combinations. When the query archetype is known (lookup vs. comparison vs. synthesis), the router can boost candidates by doc_type.

## 3. Cross-publisher comparison patterns

Real analyst questions cross documents. Three recurring patterns:

### 3a. Governor recommendation vs. enacted budget (same FY)

`Gov SAD (FY N)` ↔ `JLBC Approps Report (FY N)`

Both describe the same fiscal year, same agency, same line items — but reflect the executive's proposal vs. the Legislature's enactment. The diff *is* the legislative change. Retrieval should fan out across both publishers when query mentions "compare", "different", "changed", "Governor proposed".

Note: the JLBC Approps Report's "Detailed List of GF/Other Fund Changes" sections (`s31.pdf` / `s43.pdf` for baseline, `452.pdf` / `459.pdf` for FY26 approps — page-keyed filenames vary year over year) are pre-computed deltas and are often *the* answer.

### 3b. Baseline vs. enacted (mid-cycle within same FY)

`JLBC Baseline (FY N)` ↔ `JLBC Approps Report (FY N)`

Both are JLBC, same FY, but published months apart. Baseline is the projection; Approps Report documents what the Legislature actually did. Useful for "what did the Legislature change relative to baseline?" Both publish per-agency PDFs and cross-cut summary tables; same `agency:<slug>` canonical id ties them together.

### 3c. Enacted vs. audited (FY N-1 to FY N+1)

`JLBC Approps Report (FY N-1)` ↔ `AGAO AFR (FY N-1)`

The Approps Report says what was appropriated; the AFR says what was actually spent and what fund balances ended at. Restated tables in subsequent AFRs may rewrite history (see open question §16 in the design spec).

### 3d. Year-over-year drift (any single publisher)

Any document type, multiple FYs. Pattern: "how did X change between FY N and FY N+k?" Retrieval fans out across the FY range and the LLM synthesizes. Slug aliases (`rev`→`dor`, ASU campus merge, etc.) must resolve correctly across years — see §5 below.

## 4. Provenance & citation shapes per source

Each chunk needs an unambiguous citation back to a verifiable source. Citation shape varies by source:

| Source | Citation shape | Notes |
|---|---|---|
| JLBC singlefile | `(doc_id, page_in_singlefile, bbox)` | Untagged PDF; bbox via MinerU table detection |
| JLBC per-agency PDF | `(doc_id, page_in_per_agency_pdf, bbox)` + back-reference `page_in_singlefile` for cross-doc parity | Per-agency PDFs internally restart at page 1 |
| JLBC summary section (`s18`, `bd2`, etc.) | `(doc_id, page, bbox, row_label)` | Row-label is critical — s/bh/bd-PDFs are tabular cross-cuts |
| Governor's State Agency Detail | `(doc_id, page, bbox)` + `section_path` from outline tree | Untagged PDF but with rich outline |
| Governor's Sources and Uses | `(doc_id, page, bbox)` | 919 pages, weak outline — hardest extraction target |
| AFR | `(doc_id, page, bbox)` + cell `(row_idx, col_idx)` | Tagged PDF; cell-level structure via OpenDataLoader |
| Budget bill DOCX | `(doc_id, paragraph_id, table_cell_id)` | No bbox; `w14:paraId` is stable and survives DOCX re-saves |

UI implication (chunk-shape D3): citation chip click → side panel scrolls to the cited region. For tabular chunks, the bbox is the whole table; the row label drives a row-within-table highlight overlay.

## 5. Cross-doc entity stamping

The `agency:<slug>` canonical ID (from `samples/entity-catalog.yaml`) ties chunks across publishers. The chunking layer must resolve any extracted agency name to its canonical slug at chunk-build time so retrieval can join across documents.

Three resolution rules, in order:

1. **Direct slug match.** JLBC URLs already carry the slug (`<YY>baseline/axs.pdf` → `agency:axs`). For JLBC chunks, the slug is known from the URL.
2. **Alias map.** Older JLBC docs use slugs that have since been renamed. `samples/agency-slug-aliases.yaml` lists the renames (`rev` → `dor`, three ASU campus slugs → merged `uniasu`, etc.). Resolve via alias before stamping.
3. **Name-based match.** Non-JLBC docs (Gov, AFR, bills) require name-to-canonical resolution. The catalog's `aliases` field carries observed name variants. Edit-distance fallback handles OCR drift in older JLBC docs ("Boseline", "Deportment").

Eliminated agencies (`samples/agency-slug-aliases.yaml#eliminated_or_merged`) are queryable too — analysts ask "what happened to the State Boxing Commission?" and the system should answer from the historical chunks even though the agency no longer exists.

Per-agency PDF outline trees (where present) provide the program-level taxonomy below the agency — see `data-model.md` §4.4. The chunking layer can use these outline entries directly as `section_path` elements (chunk-shape D6).

## 6. Domain primers (system-prompt context)

Two static reference sources should be loaded into LLM system-prompt context (or summarized into one), separate from the queryable corpus:

- **`docs/reference/jlbc-writing-draft-final.docx`** — Destin's primer on AZ budget process: OSPB / JLBC / JCCR / FAC, GF vs. other funds, Feed Bill / BRBs, the Big 3 revenues, one-time vs. ongoing distinction. Conceptual frame analysts query in.
- **Governor's Glossary** (Gov State Agency Detail, pp. 626–633): two-part — Budget Terms with definitions + Acronyms list. About 40+ formal term definitions plus the canonical AZ-specific acronym set.

These are *how the State works*; the queryable corpus is *what the State did*. Both are needed for analyst-quality answers.

## 7. JLBC URL conventions (ingestion contract)

JLBC's URLs are stable enough to drive ingestion discovery directly. Pattern:

```
Baseline Book:           https://www.azjlbc.gov/<YY>baseline/...
Appropriations Report:   https://www.azjlbc.gov/<YY>ar/...
                         (FY15–FY22: http://www.azleg.gov/jlbc/<YY>AR/...)
Agency Index (within):   .../agencyindex.pdf
Per-agency content:      .../<slug>.pdf
Baseline summary:        .../s<N>.pdf
Approps section:         .../bh<N>.pdf, .../bd<N>.pdf, .../<page>.pdf
Topic-specific section:  .../<keyword>.pdf  (capitaloutlay.pdf, crr.pdf, etc.)
Link-navigable nav:      https://www.azjlbc.gov/budget/<YY>baselinelinks.pdf
                         https://www.azjlbc.gov/<YY>ar/apprpttoc.pdf
```

`<YY>` = the publishing year, which equals the fiscal year being projected (FY 2027 baseline → `27baseline/`). Approps reports cover the *just-enacted* fiscal year (FY 2026 approps at `26ar/`).

**Approps page-keyed filenames are NOT stable across years.** `452.pdf` is FY26's "Detailed List of GF Changes" because that section starts on page 452 of the FY26 singlefile; FY15's equivalent has a different page number. Use the TOC PDF (`apprpttoc.pdf`) to discover them, never hardcoded filenames. Baseline `s<N>.pdf` filenames *are* stable (s18 is "Other Funds by Agency" every year).

The baseline ↔ approps cross-cut equivalence map (e.g., `s18.pdf` ↔ `bd2.pdf` are both "Funds by Agency") is in `data-model.md` §2.

## 8. AGAO AFR composite structure

`AFR <YY>.pdf` is a concatenation of 7 sub-PDFs assembled by AGAO:

1. Financial Statements
2. GF Formatted
3. CP Formatted (Capital Projects)
4. Other Formatted
5. Fund Balance (multi-page schedule, biggest section)
6. *(duplicate outline entry — assembly artifact)*
7. Notes to Financial Statements (12 numbered notes — pp. 174-181 in FY25)

The AFR is **tagged** — OpenDataLoader's `use_struct_tree=True` exposes cell-level structure and accurate outline-driven section boundaries.

Notes 1-12 in the Notes section define and contextualize the financial-statement tables. Note 6 explicitly defines the "Statement of Revenues, Expenditures and Changes in Fund Balance" — the same table shape that appears throughout the Fund Balance section. Chunking layer should associate Notes content with the table chunks they describe (deferred — see chunk-shape D-defer-3 / data-model §3c for context).

If the per-sub-PDF originals are individually published on `gao.az.gov`, ingesting them directly is cleaner than parsing the composite — Phase 1 should probe.

## 9. Budget bill DOCX structure

Budget bills (e.g., `samples/raw-docx/budget-bill-sb1735-2025.docx`) split into two body parts:

- **Part 1 — Agency Appropriations Tables.** Section titles in `Normal` style (e.g., "Sec. 25. DEPARTMENT OF CHILD SAFETY"); body in `P 06-00` / `P 10-10` / `P 05-00` / `P 00-00` styles.
- **Part 2 — Provisions.** 46 individual sections marked by custom paragraph styles `SEC 06-18` (28 sections) and `SEC 06-19` (18 sections). Each tagged paragraph IS a section heading.

Section heading text follows a semicolon-separated pattern: `<action>; <agency or fund>; <purpose modifier>; <fiscal year>; <special clauses>`. Parseable directly into `(action, target, fiscal_year)` metadata tuples — no NLP needed. Action types observed: "Supplemental appropriation," "Appropriation reduction," "Appropriation," "Fund balance transfer," "Reduction in school district state aid apportionment," etc.

Cross-references in bill text point to A.R.S. sections (e.g., "section 35-142, Arizona Revised Statutes"). Out-of-corpus today; capture as metadata if A.R.S. lookup ever joins the corpus.
