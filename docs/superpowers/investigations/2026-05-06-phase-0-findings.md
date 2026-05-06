# Phase 0 — Findings Memo

**Date:** 2026-05-06
**Closes:** Phase 0 — Investigation (started 2026-05-04)
**Deliverable for:** Task 13 (Write findings memo) + signals readiness for Task 14 (spec update + tag)

This memo summarizes what Phase 0 settled, what's deferred, and what Phase 1 needs to assume. Detailed reasoning lives in the companion docs:

- `2026-05-05-chunk-shape-decisions.md` — chunk-shape decisions (D1–D7)
- `2026-05-06-data-model.md` — source-data model: publishers, JLBC publishing layout, s-PDFs, slug stability, per-agency PDFs

## What Phase 0 was supposed to do

Per the original plan (`docs/superpowers/plans/2026-05-04-phase-0-investigation.md`):

1. Pick a winning extractor via 20-page bake-off (ODL vs MinerU)
2. Build an entity-resolution catalog
3. Validate chunking shape against real content
4. Output a findings memo

## What actually happened

The work spread across all three goals but the **shape of the answer changed mid-investigation** as the data revealed itself. Specifically:

- **Goal 1 (extractor winner) became per-doc-type routing.** No single winner. Tagged PDFs (AFR, Gov State-Agency-Detail) extract cleanly with OpenDataLoader's structure-tree mode. Untagged PDFs (JLBC Approps, Baseline, Gov Sources-and-Uses) need MinerU's table detection. DOCX uses python-docx natively. The per-doc-type assignment is captured in chunk-shape decision D4.
- **Goal 2 (entity catalog) was bootstrapped from publisher data, not heuristics.** JLBC publishes an authoritative agency index PDF for every year (FY15–FY27 verified). Each link target's URL filename is a stable slug — `axs.pdf` for AHCCCS since at least FY 2015. We adopted slug as `canonical_id` rather than building a heuristic catalog.
- **Goal 3 (chunking shape) settled into whole-table chunking with row-precise UI citation.** Captured in chunk-shape decisions D1–D7.

Plus four outcomes that weren't on the original plan but matter as much or more than any of the above (all captured in `2026-05-06-data-model.md`):

- **Goal 4a — JLBC publishes every doc-year four parallel ways.** Singlefile, link-navigable TOC, per-agency PDFs, and cross-cutting summary section PDFs. We'd been ingesting only the singlefile. **Both baselines and approps reports** publish all four — the naming differs (baseline `s<N>.pdf` vs approps `bh<N>.pdf`/`bd<N>.pdf`/`<page>.pdf`), and the approps TOC is at `<YY>ar/apprpttoc.pdf` rather than `<YY>baselinelinks.pdf`. Verified back to FY15 on both hosts. The cross-cut PDFs are authoritative answers for analyst queries the singlefile-narrative chunks would answer poorly.
- **Goal 4b — Agency lifecycle history across 12 years.** Slug renames (`rev`→`dor`, ASU East/Main/West→merged `uniasu`), 30 eliminated/merged agencies, 14 newly created. Critical for analyst queries about defunct agencies (e.g. "what happened to the Cosmetology Board?"). Captured in `samples/agency-slug-aliases.yaml`.
- **Goal 4c — Per-agency PDFs carry their own program-level outline trees.** AHCCCS's `axs.pdf` outline lists Operating Budget / Administration / Medicaid Services / Hospital Payments / etc. — these are JLBC's authoritative program-level taxonomy. Resolves the program-level entity catalog gap chunk-shape decisions had deferred. Not universal: ~half of agencies have outlines, the rest need header-walk extraction.
- **Goal 4d — JLBC web host migration.** Older approps (FY15–FY22) live on `azleg.gov/jlbc/`, newer docs on `azjlbc.gov/`. Catalog builder handles both. Failing to whitelist the legacy host had silently dropped 25 historical slugs from the catalog before this was caught.
- **Goal 4e — Each publisher has its own structural shape, fully mapped.** Beyond JLBC: the Governor's State Agency Detail is monolithic with a rich 144-entry outline tree (eliminates need for boundary detection); Governor's Sources and Uses is 919 pages with only 8 outline entries (the hardest extraction target — a per-fund table dump); AFR is a tagged composite of 7 sub-PDFs assembled by AGAO (its outline preserves the original file boundaries); the budget bill DOCX uses custom paragraph styles (`SEC 06-18`, `SEC 06-19`) as section markers, with semicolon-separated heading text that's directly parseable into action/target/fiscal-year tuples. Captured in data-model doc §3a–§3d.
- **Goal 4f — Two domain reference sources for system-prompt context.** Destin's own JLBC writing draft + the Governor's two-part Glossary (pp. 626-633: Budget Terms with definitions + Acronyms list). Both should be loaded (or summarized) into Phase 1's system-prompt context. Glossary captured in data-model doc §3a.
- **Goal 4g — Cross-publisher document cycle is predictable.** Each FY produces a consistent sequence: Gov SAD/S&U (Jan) → Baseline → enacted Bills → Approps Report → AFR (~18 months later). Phase 1 chunk metadata stamps `(publisher, doc_type, fiscal_year)` so cross-doc retrieval can fan out across the right (publisher × FY) combinations. Captured in data-model doc §5a.

## Settled decisions

| Decision | Where it's recorded |
|---|---|
| Per-doc-type extractor routing (ODL tagged / MinerU untagged / python-docx DOCX) | chunk-shape D4 |
| Whole-table chunking with logical-table boundaries | chunk-shape D1, D2 |
| Citation = chunk_id + row identifier; UI highlights row within table | chunk-shape D3 |
| Two chunk types: table chunks + narrative chunks | chunk-shape D5 |
| Header propagation at chunk-build time | chunk-shape D6 |
| Entity normalization required, not optional | chunk-shape D7 |
| `agency:<slug>` as canonical_id (slug from JLBC URL) | data-model §4 |
| Per-agency PDFs available as alternate JLBC ingest unit | data-model §2 |
| s-PDFs ingested as their own focused cross-cut chunks | data-model §3 |
| Domain primer (`docs/reference/jlbc-writing-draft-final.docx`) loaded into system-prompt context | data-model §10 |

## Concrete artifacts produced

- **157 canonical agencies** in `samples/entity-catalog.yaml` (built from 17 JLBC indexes FY15–FY27 + Gov FY27 outline). 101 have both JLBC + Gov coverage; 70 of 84 sample sweep candidates auto-matched.
- **Slug-aliases history** in `samples/agency-slug-aliases.yaml` — captures slug renames (`rev`→`dor`, ASU campus split→merged), 30 eliminated/merged agencies, 14 newly added since FY15.
- **15 cross-cut summary PDFs** for FY27 baseline (`samples/raw-pdfs/jlbc-baseline-fy2027-s*.pdf`) — verified content shape; baseline-only (approps reports don't publish s-PDFs).
- **17 agency-index PDFs** for multi-year publisher data (FY15–FY26 approps + FY23–FY27 baselines).
- **Sample per-agency PDFs** for FY27 baseline (`axs`, `dot`, `dps`, `des`, `dor`, `legjlbc`, `lan`, `judsup`, `boe`, `exe`, `jus`) — confirms per-agency PDFs carry their own outline trees describing program structure.
- **Working extractor wrappers**: `scripts/run_opendataloader.py`, `scripts/run_mineru.py`, `scripts/run_docx_ingest.py`.
- **Variance-discovery sweep** (`scripts/sweep_entities.py`) and **catalog builder** (`scripts/build_agency_catalog.py`) — reusable in Phase 1 against the full corpus. Catalog builder accepts both legacy (`azleg.gov/jlbc/`) and current (`azjlbc.gov/`) JLBC hosts.
- **20-page sample extraction** under `samples/extractor-output/` for ODL + MinerU spot checks (kept — used by `scripts/sweep_entities.py` and as Phase 1 chunking-layer fixtures); PNG previews under `samples/phase-0-archive/scoring-helpers*/` (archived along with the bake-off scoring artifacts).

## Deferred decisions (explicit non-goals for Phase 1's first pass)

- **Full extractor scoring (Tasks 7, 8, 9 from original plan).** The per-doc-type routing decision doesn't depend on a measured winner; the inspection-based design exercise gave us enough confidence. The 20-page samples remain on disk if a future calibration is needed.
- **MinerU residual error-rate strategy (chunk-shape D-defer-1).** Three options: (a) accept + UI-surface, (b) confidence-flagging step, (c) custom JLBC extractor. Plan: start with (a) in Phase 1, measure against a small ground-truth set, escalate only if the rate is unacceptable.
- **Fund catalog construction.** Agencies catalog is built; funds are not. JLBC's `s18.pdf` (FY 2027 Other Appropriated Funds Summary by Agency) is the natural starting point — it lists every appropriated fund × every agency × the FY26→FY27 amounts. Phase 1 work.
- **Big-table subdivision rules (chunk-shape D-defer-2).** When a "logical table" exceeds ~3K tokens, subdivide at next-level heading. Heuristic; needs validation against real corpus distribution in Phase 1.
- **Embedded-values-in-prose handling (chunk-shape D-defer-3).** Some narrative chunks contain values that also appear in table chunks; retrieval may surface either. Pick a chunk-type-priority rule once we see real query→retrieval behavior.
- **Multi-page table bbox rendering (chunk-shape D-defer-4).** UI-layer concern; not chunking-layer.
- **Edge-case unmatched candidates** in the agency catalog (3 of the 14 unmatched: extreme OCR drift on "Criminal Justice Commission", sub-unit "Department of Assured and Adequate Water Supply Admin", "department of law" → `agency:att` synonym). Manual review during Phase 1.

## Phase 1 readiness

What Phase 1 can assume as given:

- Chunk schema (per spec §6 + chunk-shape D1–D7)
- Extractor choice per doc type (D4)
- Entity catalog populated for agencies (`samples/entity-catalog.yaml`) — query by `agency:<slug>`
- JLBC URL conventions known and reusable for ingestion-driven discovery
- Domain primer available for system-prompt context

What Phase 1 needs to build first:

1. **Ingestion layer** that knows about all four JLBC formats (singlefile, link-nav, per-agency, s-PDFs) and uses the agency-index as the discovery driver.
2. **Chunking layer** that consumes any extractor output and produces uniform chunks per the chunk-shape decisions.
3. **Fund catalog** parsed from `s18` (FY27) and equivalents from prior years.
4. **Companion synthesizer** + faithfulness check (per spec §3.5–3.6) — independent of ingestion, parallelizable.

## What "Phase 0 done" means

Phase 0 was investigation. It didn't ship runnable retrieval, didn't ingest the full corpus, didn't build the storage schema. What it did:

- Made the per-doc-type extractor decision (and built working wrappers for all three).
- Made the chunking-shape decision (and validated it by hand-walking real chunks against the 6-point target).
- Built the canonical agency catalog from publisher-authoritative data, with 70/84 sample candidates already matched.
- Discovered + documented the JLBC publishing structure (s-PDFs, per-agency PDFs, multi-year slug stability) — the most valuable single output, since it changes the ingestion shape entirely.
- Captured the deferred decisions explicitly so Phase 1 doesn't have to rediscover them.

Phase 1 inherits a clearer architectural target than the original Phase 0 plan anticipated.

## Recommended next moves

1. Update the design spec (Task 14) to reflect:
   - Per-doc-type extractor routing in §3 Pipeline
   - JLBC's four-layout publishing structure in §6 (or a new §6a)
   - s-PDFs as a chunk source
   - `agency:<slug>` canonical_id pattern
2. Tag Phase 0 complete (e.g. `phase-0-complete`) so it's a stable git reference.
3. Open the Phase 1 plan with the four-step workstream above.

## Pointer to the conversation

Reasoning trail and worked-example chunks lived in the chat transcript at `C:\Users\desti\.claude\projects\C--Users-desti-youcoded-dev\b8f34268-7e8a-4a51-be27-8321df34cca7.jsonl`.
