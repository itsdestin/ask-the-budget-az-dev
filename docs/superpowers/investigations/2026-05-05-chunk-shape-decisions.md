# Chunk-Shape Design Decisions

**Date:** 2026-05-05
**Context:** Phase 0 design work. Refines §8.4 (Chunking shape validation) and §3 (Pipeline) of the design spec; addresses Task 12 (Validate chunking shape) from the Phase 0 plan.

> **Companion doc:** `2026-05-06-data-model.md` covers the source-data side — how JLBC, Governor's, AGAO, and Legislature publish their documents, plus the JLBC summary-section PDFs and per-agency PDFs that this doc's chunking decisions consume.

This doc captures decisions reached while designing the target chunk shape — what every retrieved chunk needs to contain for the system to reliably answer fiscal Q&A. Reasoning is preserved for future-us; implementation lives in the Phase 1 plan.

## What we were trying to answer

Not "is the extraction good?" — but **"what does the data NEED to look like for functional, reliable, citable RAG?"** Then: how does current extractor output gap against that target? The exercise was inspection-only — read the actual chunk text we'd be sending to the LLM, against realistic analyst queries, and see what's missing.

## The 6-point chunk-shape target

For any retrieved chunk to be usable in fiscal Q&A:

1. **Document context** — doc_id, doc_title, publisher, doc_type, fiscal_year. Stamped at chunk-build time from the manifest.
2. **Section context** — heading hierarchy (`agency → fund → schedule`) + table caption if applicable. From the extractor's structure tree at chunk-build time.
3. **Header context** — for tabular chunks, column labels with parsed semantics (`fiscal_year`, `status`, `units`). Denormalized into the chunk so it's retrieval-self-sufficient.
4. **Content with column attribution** — values tied to columns, not flattened to reading order. Comes from the extractor's table structure (HTML for MinerU, cell row/col indices for OpenDataLoader).
5. **Provenance** — page + bbox; for multi-page tables, multi-rect bbox.
6. **Entity normalization** — agency / fund / appropriation names resolved to canonical IDs from the entity catalog.

A chunk missing any of these introduces a specific failure mode at runtime. Items 1, 2, 6 are chunking-layer responsibilities. Items 3, 4, 5 are extraction-quality dependent for untagged docs.

## Inspection findings (existing extractor outputs)

Tested against three pages: AFR p.163 (tagged, ODL), JLBC Approps p.513 (untagged, ODL), JLBC Approps p.513 (untagged, MinerU).

| Target | AFR ODL (tagged) | JLBC ODL (untagged) | JLBC MinerU (untagged) |
|---|---|---|---|
| 1. Doc context | not chunk-stamped | not chunk-stamped | not chunk-stamped |
| 2. Section context | no table caption | caption present | caption present (OCR drift on `OTHeR`) |
| 3. Header context | flat in MD; cell-level in JSON | reordered, mangled | HTML thead, clean |
| 4. Column attribution | partial-row ambiguity (2 of 4 values) | values detached from labels | preserved in HTML |
| 5. Cell-precise bbox | cell-level in JSON | paragraph-level | table-block-level |
| 6. Entity normalization | none | none | none |

**Key takeaway:** items 1, 2, 6 are NOT extraction problems — they're chunking-layer work that has to happen regardless of extractor choice. The genuine extraction-quality split is on item 4: ODL fails on untagged tables; MinerU mostly succeeds.

## Decisions

### D1. Whole-table chunking is the default for tabular content

**Decision:** chunks for tabular content are whole logical tables, not per-row.

**Rationale:**
- Headers stay attached to their data — no denormalization step needed.
- Filter / list / compare queries work natively (Claude sees every row, no parent-chunk + child-chunk strategy).
- Tables are the unit analysts already think in.
- Variable-column rows (AFR sub-rows with 2 of 4 values, totals row with all 4) are unambiguous in context — Claude can map values from the totals row + dashes.
- No per-row bbox derivation needed.

**Trade-offs accepted:**
- Bigger chunks (1.5–2K tokens for medium tables, more for large). Fine on Claude's context window; worth knowing for retrieval-side embedding choice.
- Embedding signal dilution on big tables — mitigated by ensuring all row labels appear in the embedded text (high-signal, short).
- Citation precision concern handled at the UI layer (D3), not by smaller chunks.

**Refines spec §8.4:** existing line "tables atomic, 512-token target / 1024 max" holds — the 512/1024 target is for narrative chunks; tables are atomic by exception and may exceed.

**WS6 follow-up 2026-05-06:** real-corpus run on s18 (Funds × Agencies cross-cut, 13 pages, ~25 agencies per chunk) revealed that whole-table chunking + single `agency_canonical_id` per chunk is the wrong unit for **cross-cut tables specifically**. Each chunk gets stamped to the FIRST agency the resolver matches in source order (alphabetical for s18), so retrieval by `agency_canonical_id` filter won't surface the correct chunk for any non-first agency. Per-row stamping or section-by-agency chunk-shape subdivision is open for Phase 1b. D1 holds for per-agency tables (one agency = one chunk is correct); cross-cut tables are the open subcase.

### D2. "Logical table" = semantic sub-table, not printed-page table

**Decision:** chunk boundary = one logically complete fiscal unit (one fund-section in AFR, one agency's appropriation table in Approps, one freestanding summary table). Multi-page tables are one chunk; very large tables (>~100 rows) subdivide at next-level heading, not arbitrary row count.

**Rationale:**
- AFR's fund-balance schedule is one printed table that spans 3 pages and contains many funds. The natural retrieval unit is per-fund — that's what queries target ("Aviation Fund", "Highway Fund").
- JLBC's per-agency appropriation pages have one logical table per agency.
- Subdividing by row count breaks semantic coherence and forces parent-chunk strategies; subdividing by heading preserves coherence.

**WS6 follow-up 2026-05-06:** the Phase 1a MinerUReader did NOT reassemble s18's 13-page Funds × Agencies table into one chunk. Cause: the heading "FY 2027 Other Fund Summary by Agency" repeats on every continuation page, and the reader's "no heading between" reassembly guard blocks merging when ANY heading appears between two same-shape tables. Two possible fixes for Phase 1b: (a) widen the guard to ignore re-emitted same-text headings (heading whose text equals the most recent already-claimed heading); or (b) move multi-page reassembly to a post-pass that uses table-shape similarity (column count + header text equivalence) rather than heading boundaries. Listed in `data/chunks/MANIFEST.md` as a Phase 1b chunk-shape revisit.

### D3. Citation = chunk_id + row identifier; UI highlights row within table

**Decision:** the chunk's bbox is the whole table region. When the LLM cites, it returns `chunk_id` plus the relevant row label (or row_index). The PDF viewer scrolls to the table region and visually highlights the specific row.

**Rationale:**
- Per-row bbox derivation isn't free (text-search against PDF word stream). Avoiding it simplifies the chunking layer.
- Row-level citation is sufficient for fiscal analysts (per user feedback: "row level might be better, as rows typically include both the name of the approp and the number"). Cell-level was never required.
- Showing surrounding rows is actually *useful context* for analysts verifying a value.

### D4. Per-doc-type extractor choice; chunking layer normalizes downstream

**Decision:** extractor is chosen by document type. Output flows through a chunking layer that produces uniform chunks regardless of source extractor.

```
PDF (tagged: AFR, Gov State-Agency-Detail) → OpenDataLoader → JSON (cell-level)
PDF (untagged: JLBC Approps, Baseline, Gov S&U) → MinerU → HTML tables + bboxes
DOCX (budget bills) → python-docx → paragraph + cell IDs

  ↓ chunking layer (format-aware reader, format-agnostic output)

Uniform chunk schema (table chunks + narrative chunks)
```

**Rationale:**
- Tagged PDFs already give us cell-level structure — using a heavier tool (MinerU) on them adds cost without value.
- Untagged PDFs need MinerU's table detection — ODL flattens columns to reading order.
- DOCX is a separate path entirely (paragraph_id / cell_id provenance, no bbox needed).
- Downstream RAG doesn't need to know which extractor produced a chunk.

### D5. Two chunk types: table chunks + narrative chunks

**Decision:** every chunk is either a table chunk (atomic, whole logical table) or a narrative chunk (paragraph or section level, 512-token target / 1024 max). Same metadata schema, different sizing rules. Marked by `is_table` field (already in spec §6 schema).

**Rationale:**
- Already implied by the spec's `is_table` / `table_html` fields. Making it explicit clarifies chunking logic.
- Tabular and narrative content have fundamentally different shapes; one sizing rule for both forces compromises in both directions.

### D6. Header propagation at chunk-build time

**Decision:** when the chunking layer emits a table chunk, it walks up the heading hierarchy from the chunk's anchor and includes:
- Doc-level metadata (from manifest)
- Full section path (heading chain)
- Column header row (parsed from extractor structure, with semantic annotations: fiscal_year, status, units where derivable)

These appear both in the chunk's structured metadata AND in the embedded text representation that goes to retrieval + LLM.

**Rationale:** addresses target items 1, 2, 3 in one place. No runtime "fetch parent context" step.

### D7. Entity normalization is required, not optional

**Decision:** the chunking layer joins each chunk against an entity catalog and stamps `agency_canonical_id`, `fund_canonical_id`, etc. Catalog construction is Phase 0 Tasks 10/11.

**Rationale:**
- Cross-doc joins (Gov rec vs final GAA, multi-year comparisons) require it.
- Embedding retrieval drifts when "AHCCCS" / "Arizona Health Care Cost Containment System" / "AHCCCS Fund" are treated as distinct strings.
- Already in spec §6 schema (`agency_canonical_id`); making it required means the catalog must exist before chunking can produce production-quality chunks.

## Deferred decisions

These don't block Phase 0 closure or Phase 1 design — capture them now so they're not forgotten:

- **D-defer-1: MinerU error-rate handling.** Three options: (a) accept the rate, surface "verify against source PDF" prominently in UI; (b) build a confidence-flagging step that detects suspicious rows (mismatched column counts, OCR garbage in numeric fields, totals ≠ sum of rows) and routes them; (c) build a custom JLBC deterministic extractor (~3-5 days). Plan: start with (a), measure against ground truth, escalate only if needed.
- **D-defer-2: Big-table subdivision heuristic.** When a "logical table" exceeds ~3K tokens, where to split. Likely "next-level heading boundary"; needs validation against actual JLBC corpus distribution.
- **D-defer-3: Embedded values in narrative prose.** Some pages have values in prose ("AHCCCS received $14.5B..."). Same value may exist in both a narrative chunk and a table chunk; retrieval may surface either. Need a chunk-type-priority rule, or accept that both can be cited.
- **D-defer-4: Multi-page table bbox rendering.** Implementation detail for the citation viewer, not a chunking concern.

## What's NOT a problem we worried about

Two things that early conversation made me think were extraction problems but turned out to be chunking-layer work:

- **Header attachment for tagged docs (AFR).** ODL gives us cell row/col indices in the JSON. The synthesized markdown was flat, but that was a markdown-rendering choice, not an extraction limitation. The chunking layer reads the JSON directly.
- **Document context absence.** No extractor produces "this is from JLBC FY26 Approps Report" — that's manifest-stamped at chunk-build time. Trivial.

## Implications for Phase 0 closure

These decisions don't require new extractor work to validate. The remaining Phase 0 tasks (8 ODL scoring, 7 MinerU scoring, 9 aggregation) still produce useful evidence — but the architectural decision (per-doc-type extractor + chunking-layer normalization) doesn't hinge on which extractor "wins" overall, because the answer is "use both, by doc type."

The chunk-shape validation (Task 12) is now substantively answered by this doc; the remaining empirical work is:
- Build one example chunk by hand from real extractor output (already done in conversation; could be persisted as a fixture).
- Once Phase 1 implements the chunking layer, run real chunks against a small query set to validate.

## Implications for Phase 1 plan

The Phase 1 ingestion+chunking work needs to:
1. Implement per-doc-type extractor dispatch.
2. Implement the chunking layer that reads from any extractor's output and produces uniform `Chunk` rows.
3. Build the entity catalog before chunking can stamp canonical IDs.
4. Output two chunk types (table, narrative) with the schema in spec §6.

Citation rendering (UI side) needs to support row-within-table highlight — accepts `chunk_id` + `row_label` or `row_index` and visually overlays the row.

---

## Conversation pointer

Reasoning trail and the worked-example chunk YAML for `jlbc-approps-fy26 p.513` (Parks Statewide Solar Shade Structures row) and the AFR p.163 fund-section walkthrough live in the chat transcript at `C:\Users\desti\.claude\projects\C--Users-desti-youcoded-dev\b8f34268-7e8a-4a51-be27-8321df34cca7.jsonl`. Worth re-reading if any of the decisions above feel too compressed.
