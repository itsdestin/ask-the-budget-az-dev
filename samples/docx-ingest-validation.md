# DOCX Ingest Validation — Budget Bill SB 1735

Phase 0 Task 5b. Validates that native `python-docx` extraction produces
clean enough structured output to make the lossy `docx → pdf → re-extract`
round-trip unnecessary. Spec §10.5 calls this the "stable id contract"
for the DOCX path.

## Tooling

- **Library:** `python-docx` (latest, pulled transitively via `mineru`)
- **Wrapper:** `scripts/run_docx_ingest.py` (commit on this branch)
- **Tests:** `scripts/tests/test_run_docx_ingest.py` — 2 dry-run tests
- **Wall-clock:** ~3.2 s on the 192 KB SB 1735 file

## Document under test

`samples/raw-docx/budget-bill-sb1735-2025.docx` — AZ Senate Bill 1735
(Chapter 233 of 2025), the General Appropriations Act for FY 2025–2026.

## Stable id mechanism

- **Source:** Word's `w14:paraId` attribute on every `<w:p>` element.
  Word writes this once per paragraph and preserves it across edits to
  that paragraph. It's the on-disk equivalent of bbox for the DOCX path.
- **Format:** 8-hex-digit Word-internal id, prefixed with `p:` in our output
  (e.g. `p:4BC2F4DD`).
- **Coverage on SB 1735:** **100% (2,739 / 2,739 paragraphs).**
  Every paragraph in the bill carries a paraId. The wrapper still has
  a fallback (`p:idx-N` based on source-order index) for hypothetical
  files where Word didn't assign one.
- **Determinism:** `diff` between two consecutive runs of the wrapper on
  the same `.docx` is empty. Verified by re-running and diffing
  `document.json`. The bbox-equivalent stable-id contract holds.

For table cells, `table_cell_id = "t<table>-r<row>-c<col>"` is computed
deterministically from source position. SB 1735 has 1 cover-page table
with 5 cells; ids range `t1-r1-c1` to `t1-r5-c1`. (The bill body is
NOT in Word tables — it's in tab-separated paragraphs; see below.)

## Extraction shape

| Metric | Value |
|---|---|
| Total blocks | 2,744 |
| Paragraph blocks | 2,739 (99.8%) |
| Table-cell blocks | 5 (cover page only) |
| Paragraphs with `cells` (tab-separated line items) | 1,290 (47.0% of paragraphs) |
| `paragraph_id` coverage | 100% |
| `table_cell_id` coverage | 100% |

### Paragraph-style distribution (top 8)

| Count | Style |
|---|---|
| 1,705 | `Normal` (default — explicit in our output, never `null`) |
| 703 | `P 06-00` (the AZ Legislature's body-text style for indented body paragraphs) |
| 173 | `P 10-10` (deeper-indent body) |
| 41 | `Body Text Indent` |
| 28 | `SEC 06-18` (section heading marker) |
| 27 | `P 05-00` |
| 26 | `P 00-00` |
| 18 | `SEC 06-19` (section heading marker, alt level) |

The `SEC ...` style names are a stable signal that the paragraph is a
section heading — usable for chunking and section-boundary detection
without OCR or layout inference.

## Quality assessment

| Check | Result | Evidence |
|---|---|---|
| Paragraph fidelity | ✅ Pass | All 2,739 paragraphs preserved in source order |
| Table preservation | ✅ Pass | Cover-page table (5 cells) preserved with deterministic cell ids; bill body is NOT in Word tables (it's in tab-separated paragraphs — handled separately, see "Footgun" below) |
| Heading detection | ✅ Pass via style name | Section headings all carry `style: SEC 06-18` (or `SEC 06-19`); body lines are `Normal` / `P 06-00` / `P 10-10`. Downstream chunking can treat any `style.startswith('SEC')` as a section boundary |
| Stable id contract | ✅ Pass | `diff` between two runs of `document.json` is empty |
| Line-item structure | ✅ Pass | The 1,290 tab-bearing paragraphs include all the bill's appropriations line items. Spot-check: paragraph `p:4BC2F4DD` reads `JOBS\t11,005,600` and renders as `cells: ['JOBS', '11,005,600']` — ready to chunk as a structured record |

### Sample blocks

**Section heading (the `SEC 06-18` style is the chunking-boundary signal):**
```json
{
  "kind": "paragraph",
  "paragraph_id": "p:7973832C",
  "style": "SEC 06-18",
  "text": "Sec.   Supplemental appropriation; acupuncture board of examiners; fiscal year 2024-2025"
}
```

**Line-item row (tab-separated cells preserved):**
```json
{
  "kind": "paragraph",
  "paragraph_id": "p:4BC2F4DD",
  "style": "Normal",
  "text": "JOBS\t11,005,600",
  "cells": ["JOBS", "11,005,600"]
}
```

## Footgun discovered: budget data lives in **paragraphs**, not Word tables

The AZ Legislature's bill template encodes appropriations line items as
single paragraphs with **tab characters** separating columns
(`<NAME>\t<AMOUNT>` etc.) rather than as Word `<w:tbl>` elements. The
only `<w:tbl>` in SB 1735 is the cover-page banner. The wrapper handles
this by splitting tab-bearing paragraph text into a `cells: [...]` field
on the same block — downstream chunking can treat such paragraphs as
structured records without conflating them with prose.

Implication: a generic DOCX → flat-text pipeline that drops tab
characters (which `python-docx`'s default `Paragraph.text` accessor does
on some platforms) would lose the column structure entirely. Our wrapper
walks the XML directly and preserves tabs explicitly to avoid this.

## v1 routing decision

✅ **Pass: native DOCX ingest is clean. v1 ingest pipeline routes `.docx`
→ `python-docx` natively, NOT through PDF conversion.** Per spec §10.5
the `(paragraph_id, cell_id)` tuple is the citation provenance for DOCX
sources; both ids are populated and stable.

## Reproduction

```bash
cd ~/ask-the-budget-az-dev/  # or the phase-0 worktree
uv run python scripts/run_docx_ingest.py \
  --docx samples/raw-docx/budget-bill-sb1735-2025.docx \
  --out samples/extractor-output/docx/budget-bill-sb1735-2025
```

Stable-id determinism check:

```bash
uv run python scripts/run_docx_ingest.py --docx samples/raw-docx/budget-bill-sb1735-2025.docx --out /tmp/run-a
uv run python scripts/run_docx_ingest.py --docx samples/raw-docx/budget-bill-sb1735-2025.docx --out /tmp/run-b
diff /tmp/run-a/document.json /tmp/run-b/document.json   # expect: empty
```
