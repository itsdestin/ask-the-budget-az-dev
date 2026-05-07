# Phase 1a chunk store — MANIFEST

This directory holds the Phase 1a chunk hand-off to Phase 1b. Each `.json`
is NDJSON (one Pydantic-validated `Chunk` per line). Phase 1b reads this
manifest as its input contract.

## Slice scope

This is a **validated slice**, not the full Week-1 corpus. Five
hand-picked docs cover the WS6 plan's smoke-query expectations
end-to-end. Full ingest (Week 1: ~50 docs; Weeks 2–3: prior FYs +
per-agency PDFs + AFR + Gov SAD) moves to the first session of Phase 1b
when the storage layer is plumbed and we'd be re-ingesting anyway. See
"Deferred to Phase 1b" below.

## Inventory

| Doc ID | Source URL / path | Pages | Chunks | sha256 (first 16) | Notes |
|---|---|---:|---:|---|---|
| `jlbc-baseline-fy2027-s18` | `azjlbc.gov/27baseline/s18.pdf` | 13 | 14 | `b9f0ca8b03a547f9` | FY27 Other Fund Summary by Agency. 100% agency-stamped, 100% fund-stamped. |
| `jlbc-baseline-fy2027-s83` | `azjlbc.gov/27baseline/s83.pdf` | 4 | 4 | `1116d67f941dc1d0` | FY27 State Personnel Summary (FTE by agency). 75% agency-stamped (cross-cut summary chunk unstamped), 100% fund-stamped. |
| `jlbc-approps-fy2026-bh20` | `azjlbc.gov/26ar/bh20.pdf` | 5 | 5 | `0d09c4a29f8e1e93` | FY26 One-Time GF Adjustments. 80% agency, 40% fund. |
| `jlbc-approps-fy2026-bd2` | `azjlbc.gov/26ar/bd2.pdf` | 2 | 2 | `20a7250b91cf578c` | FY26 Budget Detail by Agency × Fund. 100% agency, 100% fund. |
| `legislature-budget-bill-fy2026-sb1735-2025` | `samples/raw-docx/budget-bill-sb1735-2025.docx` | (DOCX) | 136 | `4b70d270056ddc9e` | SB 1735 General Appropriations Act. 91.2% agency, 48.5% fund. |

**Totals:** 5 docs / 161 chunks / 91.3% agency-stamped (147/161). Meets
the plan's "≥ 90% agency-canonical-id stamped" target for Phase-1a-done.

Sample chunk-ids: `<doc_id>-0000` (zero-padded 4-digit index per doc, dense
numbering across table + narrative chunks).

## Smoke-query baseline

`scripts/smoke_query.py` runs 5 plan-defined analyst queries through
naive in-memory TF-IDF over chunk text. Current result on this slice:
**5/5 queries pass top-3 expectation**, all substring expectations
satisfied. Replays via:

```bash
uv run python scripts/smoke_query.py
```

## Catalogs

- `samples/entity-catalog.yaml` (157 agencies, 95 with slugs) — Phase 0 output, unmodified.
- `samples/agency-slug-aliases.yaml` — Phase 0 output, unmodified. The
  four `pending_for_phase_1` items remain open (require FY15-FY22 ingest
  to resolve naturally; deferred to Phase 1b).
- `data/fund-catalog.yaml` (227 funds) — produced by
  `scripts/build_fund_catalog.py --source jlbc-s18:... --source jlbc-bd2:...`
  on this slice's extractor output. Plan target was ≥80 funds; we have
  227.
- `data/audit/2026-05-06-chunk-audit.json` — programmatic audit output
  (per-doc stamping, token distributions, provenance integrity).

## Integration findings (caught by real ingest, not synthetic fixtures)

The slice run surfaced four real bugs and four chunk-shape observations.
Bugs are fixed in this branch and pinned by regression tests; observations
are recorded for Phase 1b chunk-shape decisions.

### Bugs fixed in WS6

1. **DOCX bill Part-1 dept headings missed.** Real bills use
   `Sec. NN.  <ALL-CAPS NAME>` (numbered or unnumbered Sec.) instead of
   the bare `<ALL-CAPS NAME>` in the synthetic fixture. Without the
   prefix-tolerant detector, the entire bill body collapsed into one
   55K-token section. Fixed in `chunking/readers/docx_reader.py`.
2. **rapidfuzz token_set_ratio is case-sensitive in 3.x.** Every ALL-CAPS
   bill heading scored ~19 against mixed-case catalog names, far below
   the 85 floor. Fixed by adding `processor=` casefold in
   `chunking/entity_stamper.py`.
3. **rapidfuzz does NOT tokenize on NBSP.** Word writes
   `Sec.\xa0NN.\xa0\xa0DEPT` between section number and dept name; the
   dept-name token fused with the prefix and never matched. Fixed by
   normalizing NBSP→space inside the same `processor=` helper.
4. (No bug #4 — listed for symmetry with the chunk-shape observations.)

### Chunk-shape observations (Phase 1b decisions)

- **Cross-cut whole-table chunks stamp to a single agency.** `s18.pdf`
  is `funds × agencies`; the whole-table chunk-shape (D6) means each
  chunk gets stamped to the FIRST agency the resolver matches in the
  table, even though the chunk lists ~25 agencies. AHCCCS rows are
  inside chunk 0000, but that chunk is stamped `agency:bae` (Board of
  Accountancy).
  **RESOLVED 2026-05-06 (decision D2):** schema flips
  `agency_canonical_id TEXT` → `agency_canonical_ids TEXT[]` in Phase 1b
  migration 0001. Whole-table chunks stamp ALL agencies; filter syntax
  `WHERE 'agency:adc' = ANY(agency_canonical_ids)` uses GIN index. No
  per-row chunk explosion, no chunk-shape redesign. Loader promotes
  scalar → array on insert; existing slice JSONs work as-is. See
  `docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md`.
- **Multi-page tables not reassembling on s18.** s18 spans 13 pages
  with the same logical Funds × Agencies table, but each page got its
  own chunk because the table title heading repeats on every continuation
  page and the reader's "no heading between" rule blocks reassembly.
  **Less urgent under D2** — each chunk now stamps to all 25 agencies,
  so retrieval by agency filter still surfaces all 13 chunks. Revisit
  if eval shows it matters.
- **bd2 parser yields 0 fund-rows.** `funds/parser.py::parse_s18_table`
  is tuned to s18's specific shape; bd2 has agency-as-section-spanned-row
  + fund-rows but a different exact column layout. **Out of scope for
  Phase 1b retrieval** — cross-source fund catalog merge is a Phase 1.5
  concern.
- **Plan smoke queries used acronyms (`ADC`, `ADOT`, `GAA`) that don't
  appear in source text.** JLBC docs use spelled-out names; the bill
  too. **REFRAMED under D7:** acronym expansion is a system-prompt
  instruction in the Phase 1c Budget MCP server ("expand acronyms before
  calling retrieve()"), not a separate retrieval-layer component. Tested
  in WS8 eval; revisit only if recall is poor.

## What "Phase 1a done" means (plan §"What Phase 1a done means")

| Criterion | Plan target | Slice actual |
|---|---|---|
| Source content extracted | 5+ fiscal years | FY26 + FY27 (slice) |
| Chunks emitted | ~3000+ (full corpus) | 161 (slice) |
| Pydantic schema validation | every chunk passes | 161/161 ✓ |
| `agency_canonical_id` stamped | ≥ 90% | 91.3% ✓ |
| Fund catalog | ≥ 80 funds | 227 ✓ |

Slice meets every quality target; volume targets (5+ fiscal years, 3000+
chunks) are explicitly deferred to Phase 1b kickoff.

## Deferred to Phase 1b

These are intentionally NOT done in this slice — captured here so they
don't get forgotten when Phase 1b starts:

- **Full Week-1 corpus ingest** (~50 cross-cut PDFs). Pipeline proven on
  slice; Phase 1b re-ingests as part of storage-layer plumbing.
- **Week 2 per-agency PDFs** (~110 docs for FY27 baseline alone).
- **Week 3 backfill** (FY15–FY22 approps; FY25 AFR; Gov SAD).
- **AFR Notes ingestion at scale** (`primer/notes_chunker.py` exists,
  needs real AFR run).
- **Per-row stamping for cross-cut tables** — see chunk-shape obs above.
- **Multi-page table reassembly across logical-table boundaries** — s18
  case + AFR Fund Balance schedule. Plan's "deferred decisions"
  section already.
- **bd2 parser revision** — see chunk-shape obs above.
- **Singlefile fallback** for missing per-agency PDFs. Plan deferred.
- **Sources and Uses (Gov S&U) ingestion** — 919 pp, weak outline.
  Plan deferred to Phase 2.
- **Resolution of `agency-slug-aliases.yaml#pending_for_phase_1`** —
  resolves naturally during FY15-FY22 ingest in Phase 1b.

## Reproducing this slice

```bash
# 1. Drop the bill DOCX
cp ~/Downloads/0233\ \(1\).docx samples/raw-docx/budget-bill-sb1735-2025.docx

# 2. Run ingest (downloads PDFs, runs MinerU, runs DOCX, chunks all)
uv run python scripts/run_phase_1a_slice.py

# 3. Build fund catalog from real corpus
uv run python scripts/build_fund_catalog.py \
  --source jlbc-s18:data/extractor-output/jlbc-baseline-fy2027-s18 \
  --source jlbc-bd2:data/extractor-output/jlbc-approps-fy2026-bd2 \
  --out data/fund-catalog.yaml

# 4. Re-chunk to fold in fund stamps
uv run python scripts/run_phase_1a_slice.py

# 5. Audit + smoke-query
uv run python scripts/audit_chunks.py
uv run python scripts/smoke_query.py
```

Total wall time on RTX 4070 + CUDA 12.8 torch: ~7 minutes (24 PDF pages
through MinerU + 2744-block DOCX through python-docx + chunking + stamping).
