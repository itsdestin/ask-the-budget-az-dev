# Scoring Rubric — Phase 0 Extractor Bake-Off

Five dimensions, scored 0–3 per (page × extractor). Not every dimension
applies to every page — see the "When applies" line. Use `NA` when a
dimension doesn't apply; aggregate stats compute over applicable cells only.

## Scale

| Score | Meaning |
|---|---|
| **3** | Clean. Output matches the PDF closely enough that downstream chunking + retrieval would work correctly. |
| **2** | Minor issues. Output is mostly right; an analyst reading the chunk would not be misled, but some quality is lost (e.g., column alignment off by one, paragraph break missing). |
| **1** | Major issues. Output contains a wrong fact (e.g., wrong dollar figure, footnote attached to wrong row, table column misaligned in a way that conflates rows). Downstream system would mislead an analyst. |
| **0** | Failed. Extractor errored, omitted the content entirely, or produced gibberish. |
| **NA** | Dimension does not apply to this page (e.g., footnote-attachment NA on a page with no footnotes). |

## Dimensions

### 1. Cell-level numeric accuracy
**When applies:** Pages with tables that have numeric cells.

**Procedure:** Pick 5–10 cells from the page (mix top, middle, bottom; mix small and large numbers). For each, compare the extracted value to the PDF.

- **3** — All cells match exactly (digit-for-digit).
- **2** — 1 cell off by formatting only (e.g., `$1.74B` vs `1,740,000,000`); no numeric drift.
- **1** — At least 1 cell has a wrong digit, dropped digit, or shifted decimal.
- **0** — Numbers absent or scrambled.

### 2. Bbox quality
**When applies:** All pages.

**Procedure:** Open the page-N.json. For 3 randomly-chosen blocks (mix small and large), look at the reported bbox and check whether it surrounds the right text in the PDF.

> **Coordinate system note** — extractors don't agree:
> - **OpenDataLoader-PDF** uses **PDF user-space**: `[x0, y0, x1, y1]` with origin at the bottom-left of the page, y-axis pointing up. Units are PDF points (72/inch).
> - **MinerU** uses **image-space**: `[x0, y0, x1, y1]` with origin at the top-left, y-axis pointing down. Units are pixels at MinerU's render DPI (typically 96 or 200).
>
> Don't compare bbox numbers between the two extractors directly — convert mentally to "is this region tight around the right text" before scoring.

- **3** — Bbox tightly surrounds the reported text on all 3 spot checks.
- **2** — Bbox is a few units off but clearly indicates the right region on all 3.
- **1** — At least 1 bbox points to the wrong region or is off by an amount that would highlight unrelated text in the side-panel viewer.
- **0** — No bboxes provided, or bboxes are clearly wrong (zeros, negative, way outside the page).

### 3. Multi-page table reassembly
**When applies:** Pages flagged with the `multi-page-table` archetype, **and** specifically the LAST page of a multi-page table (not all pages of one).

**Procedure:** Look at the blocks from this page. Does the extractor signal this content continues a table from previous pages? Some extractors expose a `table_continues_from` flag or share a stable `table_id`; others rely on the structural type label being consistent across pages.

- **3** — Yes, with explicit linkage to the prior page's table object (shared id, or `continues_from` reference).
- **2** — Yes, but only structurally (same column headers, same row pattern, no explicit linkage).
- **1** — Treats this page as a fresh table, losing connection to the rest.
- **0** — Fails to detect a table at all.

### 4. Section header detection
**When applies:** All pages.

**Procedure:** For each clear visual heading on the PDF page (judge by font size, weight, vertical spacing), check whether the extractor labeled it as a heading rather than a body paragraph.

> **Tip** — OpenDataLoader exposes both `type: "heading"` and a numeric `heading level` (1–6) plus a PDF-semantic `level` like `"Doctitle"` / `"Subtitle"`. MinerU exposes headings as paragraphs with a `text_level` integer. Either signal counts as "labeled as heading" — don't penalize an extractor for using the format that's natural for it.

- **3** — Every visual heading is labeled as a heading; no false positives.
- **2** — 1 missing or 1 false positive.
- **1** — ≥ 2 missing or ≥ 2 false positives, OR a critical heading is missed (e.g., agency name).
- **0** — No heading detection at all (everything labeled as body text).

### 5. Footnote attachment
**When applies:** Pages flagged with the `footnote-heavy` archetype, **or** any page where a numeric cell carries a footnote marker (`*`, `(1)`, `†`, etc.).

**Procedure:** For 1 footnote on the page, check whether the extractor associated it with the correct cell/row.

- **3** — Footnote is attached to the right row (either as part of the row's block or via an explicit reference).
- **2** — Footnote text extracted but as an unattached block; analyst could pair them manually.
- **1** — Footnote attached to the wrong row, OR text mangled.
- **0** — Footnote dropped entirely.

## Recording

For each (page × extractor) combination, fill one row in:
- `samples/scores-mineru.csv`
- `samples/scores-opendataloader.csv`

with this header:
```
doc_id,page,archetypes,cell_accuracy,bbox_quality,multipage_reassembly,header_detection,footnote_attachment,notes
```

Use `NA` (uppercase) for non-applicable dimensions. `notes` is freeform — capture anything surprising, especially failures the rubric doesn't cover so we can decide post-hoc whether to add a 6th dimension.

## Bias controls

- **Score MinerU and OpenDataLoader independently.** Do not score Extractor B by saying "compared to A this is worse." Open the PDF, open one extractor's output, score against the rubric. Then repeat for the other extractor.
- **Spot-check three pages twice.** Re-score 3 random pages from scratch (without looking at the prior score). If any score differs by more than 1, the rubric is too subjective on that dimension — refine this file and re-score those pages.
