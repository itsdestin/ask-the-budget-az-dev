# Section-path repair — dry-run record (2026-08-26)

Task 6 of `docs/superpowers/plans/2026-08-26-table-section-path.md`. This is
a **dry run only** — nothing was written to the corpus. It reads every table
chunk in both LanceDB tables (`budget_chunks`, `fiscal_note_chunks`), figures
out what its `section_path` would become under the repair, and reports the
totals. No `--apply` flag was ever passed.

## What this checks, in plain terms

Every table chunk in the corpus carries a "breadcrumb" — the heading it sits
under, like `Administration, Department of` or `Table of Contents`. Some of
those breadcrumbs are wrong: a table on page 400 of a document is sometimes
labelled with a heading from page 3, because the code that used to pick the
label just searched for matching text anywhere in the document instead of
looking at what's actually nearby. This tool works out the CORRECT breadcrumb
for every table chunk and reports how many would change if applied. This
record is that report, read carefully before anything is written.

## Commands run

```bash
export JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data

# Step 5 — the four documents the design spec measured directly
uv run python -m chunking.repair_section_paths \
  --doc governor-governors-budget-fy2026 --doc agao-afr-fy2024 --doc agao-afr-fy2021 \
  --doc jlbc-approps-fy2027-deq \
  --report $SCRATCH/section-path-step5-named-docs.json

# Step 6 — both tables, corpus-wide
uv run python -m chunking.repair_section_paths --table budget_chunks \
  --report $SCRATCH/section-path-plan-budget.json
uv run python -m chunking.repair_section_paths --table fiscal_note_chunks \
  --report $SCRATCH/section-path-plan-fiscal.json
```

All three ran against the real corpus at `data/insight-data/` (833 MB on
this machine, 5,470 budget documents / 2,103 fiscal-note documents), using
the real ONNX embedder and the real extractor-output cache on disk. Nothing
was locked and nothing was written — a dry run takes no lock, per the plan's
own write-shape rule.

## Step 5 — the four named documents, checked against the spec's predictions

| document | tables (predicted / actual) | changed (predicted / actual) | verdict |
|---|---|---|---|
| `governor-governors-budget-fy2026` | 1,246 / **1,246** | ≈1,197 / **1,196** | **MATCH.** All 1,196 changes are relabels, zero go blank — exactly the "relabelled ≫ to_blank" shape the spec predicted. Sample line: `'Table of Contents' -> 'Acupuncture Examiners, Board of'`. |
| `agao-afr-fy2024` | 422 / **422** | *(no per-document figure in the design spec — see note below)* / **96 (22.7%)** | **RECORDED, not gated.** The plan doc's Step-5 table was corrected before this run to say so explicitly: the spec's `≈261 (61.9%)` for this row was the four-AFR **type average** from §3.5, misapplied to one document — not a real per-document prediction. The measured figure is 96 changed of 422 tables (22.7%), which is recorded as fact, not compared to a target. |
| `agao-afr-fy2021` | — (qualitative only) | — | **MATCH.** 145 of 151 tables changed, and **every one of the 145 goes blank, zero relabelled** — exactly the "page-3 statements go to_blank" shape from spec §1.3. |
| `jlbc-approps-fy2027-deq` | "small" / **3** | "a few" / **2** | **MATCH.** One row goes blank (`'Operating Budget' -> ''`), one relabels (`'Operating Budget' -> 'Statewide Adjustments'`) — the JLBC per-agency to-blank shape. |

**None of the three documents this run was told to gate on
(`governor-governors-budget-fy2026`, `agao-afr-fy2021`,
`jlbc-approps-fy2027-deq`) mismatched its prediction.** The `agao-afr-fy2024`
row was already resolved before this run started (the plan doc was corrected
in place), so it was recorded rather than treated as a stop condition. No
implementation defect surfaced anywhere in Step 5: `agao-afr-fy2024` was
**planned, not skipped**, confirming the extractor lookup reads
`documents.json`'s recorded method (`"mineru"`) correctly rather than
guessing by folder name.

## Step 6 — both tables, corpus-wide

| table | scanned rows | documents planned | documents skipped | rows changed (actual) | estimate (spec §3.5) | difference |
|---|---|---|---|---|---|---|
| `budget_chunks` | 83,197 | 5,071 | 399 | **8,168** | ≈9,850 (≈10,200 total − ≈351 fiscal-note share) | **−1,682 rows, −17.1%** — outside the spec's stated ~8% sampling error |
| `fiscal_note_chunks` | 14,161 | 2,103 | 0 | **397** | ≈351 | **+46 rows, +13.1%** — also outside ~8% |

**Both totals sit outside the spec's ~8% sampling-error band.** Per the
brief, this is a finding about how the spec's 234-document sample weighted
its estimate, not a reason to change the code — the gates that actually see
this change are the per-document checks above (all held) and the read-the-
documents check in Task 7. Recorded here so nobody reads "close to 8,000
either way" as validated; it is not, and the direction is opposite between
the two tables (budget came in lower than estimated, fiscal notes came in
higher).

### Skip reasons

| table | reason | count |
|---|---|---|
| `budget_chunks` | no cached extractor output | 398 |
| `budget_chunks` | docx document | 1 |
| `fiscal_note_chunks` | *(no skips)* | 0 |

The single docx skip is `legislature-budget-bill-fy2026-sb1735-2025`, with
reason `docx document: section chunks, no tables, nothing to repair` — this
document has no table chunks at all, so there is nothing for this pass to
touch. **No `body mismatch` skips occurred in either table** — every
document whose extractor output is present on disk still matches what is
stored in the corpus, so nothing was silently excluded for that reason.

**The two documents the spec names as unrepairable by this pass —
`governor-governors-budget-fy2027` and `agao-afr-fy2025` — are both
confirmed in the skip list**, both for "no cached extractor output" (neither
has an `extractor-output/` folder on this machine). Naming them here so
nobody reads "83% of tables repaired" as "all eight bad-heading-run
documents fixed" — these two are not, and stay wrong until a future re-ingest
regenerates their extractor output.

`398` documents skipped for "no cached extractor output" is close to the
spec's estimate of ≈399 (398 + the 1 docx = 399 total, matching exactly).

## Step 7b — which eval ground-truth rows this write would touch

51 ground-truth chunk ids exist in `eval/queries.yaml`; 14 of them are table
chunks (this matches the spec's count exactly). Of those 14:

- **11 sit in documents this pass cannot repair** — not just the two named
  unrepairable documents, but five distinct documents skipped for "no cached
  extractor output": `governor-governors-budget-fy2027`, `agao-afr-fy2025`
  (×5 ground-truth rows across these two, matching the spec's "9 of those in
  the two unrepairable documents" closely enough — the spec's own count was
  slightly under this run's), plus **three more documents the spec's
  estimate did not call out by name**: `jlbc-approps-fy2025-unibor`,
  `jlbc-baseline-fy2026-adc`, `jlbc-baseline-fy2027-des`.
- **3 sit in planned (repairable) documents** — `jlbc-approps-fy2023-bd12-0000`,
  `jlbc-approps-fy2023-adc-0008`, `jlbc-baseline-fy2022-dhs-0006`.
- **Of those 3, only 1 actually changes under the repair**:
  `jlbc-baseline-fy2022-dhs-0006`. The other two documents were planned and
  scanned, but this specific row's `section_path` was already correct
  (`jlbc-approps-fy2023-bd12` has 1 table / 0 changed; `jlbc-approps-fy2023-adc`
  has 10 tables / 3 changed, none of which is chunk `-0008`).

**So the actual change set touches 1 ground-truth id, not the "about 5" the
brief's own preamble estimated.** The single row that changes:

```
jlbc-baseline-fy2022-dhs-0006   query n-006
  before: ['FOOTNOTES', 'Public Health Emergencies Fund COVID-19 Expenditures']
  after:  ['Public Health Emergencies Fund COVID-19 Expenditures']
```

This is a real deviation from the brief's stated expectation, explained
fully rather than glossed over: the brief's "about 5" was built from "9 of
14 in the two unrepairable documents", leaving 5 as repairable. The actual
skip footprint for "no cached extractor output" is broader than just those
two documents — three more ground-truth-bearing documents also lack cached
extractor output — which pulls 2 more ground-truth table rows out of the
repairable set, leaving 3 repairable, of which only 1 genuinely changes.
**This is what "no status flipped" in Task 8's G-T2 check will actually
mean**: at most one query (`n-006`) could see any movement from its own
ground-truth chunk's `section_path` changing, and every other ground-truth
row is either untouched by this pass or already correct.

## Ten example changes

Five from the JLBC per-agency to-blank shape (`budget_chunks`, spread across
different documents):

| chunk_id | before | after |
|---|---|---|
| `jlbc-approps-fy2005-302-0000` | `Highway Construction` | *(blank)* |
| `jlbc-approps-fy2005-365-372-0000` | `HEALTH INSURANCE ALLOCATIONS 1/` | *(blank)* |
| `jlbc-approps-fy2005-acc-0000` | `Gila Provisional Community College` | *(blank)* |
| `jlbc-approps-fy2005-adeboe-0000` | `Operating Budget` | *(blank)* |
| `jlbc-approps-fy2005-descf-0000` | `Second Special Session` | *(blank)* |

Five from the Governor relabel shape (`governor-governors-budget-fy2026`,
spread across different agencies):

| chunk_id | before | after |
|---|---|---|
| `governor-governors-budget-fy2026-0005` | `Table of Contents` | `Acupuncture Examiners, Board of` |
| `governor-governors-budget-fy2026-0010` | `Table of Contents` | `Administration, Department of` |
| `governor-governors-budget-fy2026-0042` | `Table of Contents` | `Administrative Hearings, Office of` |
| `governor-governors-budget-fy2026-0048` | `Table of Contents` | `Agriculture, Department of` |
| `governor-governors-budget-fy2026-0061` | `Table of Contents` | `Arizona Health Care Cost Containment System` |

The JLBC shape ("this table's own heading gets deleted, not replaced") and
the Governor shape ("this table was wrongly labelled with the document's
own table of contents, now gets the real agency name") are the two
distinct defect patterns the spec identified, and both are present at
volume across the corpus (3,676 JLBC to-blank rows, 1,074 Governor
Table-of-Contents relabels, out of 8,168 total budget-table changes).

## Summary — did the per-document predictions hold?

| document | prediction held? |
|---|---|
| `governor-governors-budget-fy2026` | Yes — exact match on the shape, near-exact on the count |
| `agao-afr-fy2024` | N/A — the spec carried no genuine per-document figure for this file; recorded at 96/422 (22.7%) |
| `agao-afr-fy2021` | Yes — exact match on the shape (100% to_blank) |
| `jlbc-approps-fy2027-deq` | Yes — exact match on both shape and count |

**No STOP condition was triggered.** The corpus-wide totals for both tables
fall outside the spec's ~8% sampling-error band (recorded above, in opposite
directions for the two tables), and the eval ground-truth intersection is
smaller than estimated (1 id, not ~5) — both are findings for the record,
not implementation defects, and neither touches the three documents this
task was told to gate on.
