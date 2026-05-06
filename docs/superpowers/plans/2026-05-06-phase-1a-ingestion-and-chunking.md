# Phase 1a — Ingestion + Chunking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stand up an end-to-end pipeline that pulls source documents from publisher URLs, extracts them with the right per-doc-type tool, and produces uniform `Chunk` rows matching the spec §6 schema. By the end of Phase 1a, we should be able to type a question against an in-memory chunk list and see plausible candidate chunks come back. Storage, retrieval scoring, embeddings, the LLM call, and the UI are out of scope here — those are Phase 1b and 1c.

**Scope this plan:**
- Discovery layer (TOC-driven URL enumeration)
- Per-doc-type extractor dispatch (wraps existing Phase 0 extractor scripts)
- Chunking layer (the heart — produces `Chunk` rows from any extractor output)
- Slug-alias resolution at chunk-build time
- Fund catalog construction (parallels the Phase 0 agency catalog)
- Domain primer ingestion (writing draft + Gov glossary → system-prompt context blob)

**Out of scope (deferred to Phase 1b):**
- Postgres schema, pgvector + ParadeDB setup
- Voyage-3-large embedding generation
- Hybrid retrieval (BM25 + dense + RRF)
- Reranker (Voyage rerank-2.5)
- Query routing classifier

**Out of scope (deferred to Phase 1c):**
- Companion app + LLM synthesis
- Tool-call citation emission
- NLI faithfulness verifier
- Web UI (Next.js + PDF.js + react-pdf-highlighter-extended)
- Audit log persistence

**Architecture:** Python 3.12+, `uv` for env. Builds on Phase 0's existing extractor wrappers (`run_mineru.py`, `run_opendataloader.py`, `run_docx_ingest.py`) and entity catalog (`samples/entity-catalog.yaml`, `samples/agency-slug-aliases.yaml`). Output of Phase 1a is JSON-serialized `Chunk` records on disk — Phase 1b will consume those into Postgres.

**Tech Stack:** Python 3.12+, `uv`, Pydantic for `Chunk` shape validation, PyMuPDF for outline + link-annotation reading, `requests` for downloads, `pyyaml` for catalogs. No web/Node tooling at this stage. No embeddings or vector store yet.

**Source spec:** `docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md` — especially §3 (pipeline), §6 (data model), §9 (stack table). Cross-doc behavior reference: `docs/cross-doc-relationships.md`.

**Source investigation docs (Phase 0 outputs):**
- `docs/superpowers/investigations/2026-05-05-chunk-shape-decisions.md` — chunk-shape D1–D7 (load-bearing)
- `docs/superpowers/investigations/2026-05-06-data-model.md` — publisher landscape, JLBC layout, slug stability
- `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` — what we settled and what's deferred

---

## Ingest order — Order C

Per the cross-doc-relationships §2 query-archetype mapping, **most simple lookup queries have their best answer in a cross-cut summary PDF chunk**, not in a narrative or singlefile chunk. So we front-load the smallest, highest-ROI form-factor:

| Week | Target | Why first / why now |
|---|---|---|
| **Week 1** | 15 baseline s-PDFs (FY 2027) + 28 approps cross-cuts (FY 2026) + budget bill DOCX (SB 1735) + primers (writing draft + Gov glossary) | Smallest files, cleanest tables, highest semantic density per byte. ~90 chunks total. Lets us validate the chunking layer end-to-end on day-one-shippable content. |
| **Week 2** | 110 per-agency PDFs (FY 2027 baseline) | Per-agency boundaries are explicit. Outline trees (where present) carry program taxonomy. Chunking layer is proven by now; only narrative-handling is new. |
| **Week 3** | Backfill prior years — FY 2026 baseline, FY 2025 approps, AFR FY 2025, Gov FY 2027 SAD/S&U | Same chunking layer, more docs. Slug aliases + host migration kick in for older years. |
| **Week 4** | Integration tests, chunk validation, prep handoff to Phase 1b (storage) | Validate by hand-querying against the chunk list. Verify entity stamping, citation provenance, fund catalog consistency. |

**Configurable order — important.** The ingest driver iterates over a YAML-configured doc list, not a hardcoded sequence. Switching to Order B (per-agency-first) is a one-file edit. We default to Order C based on the data-model §6 hypothesis that lookup queries dominate; if early dogfood reveals narrative-driven queries dominate, we switch.

The Order C hypothesis lives at the top of `data/ingest-plan.yaml` as a comment so it's revisitable.

---

## File structure

Files created during Phase 1a (paths relative to `~/ask-the-budget-az-dev/`):

| Path | Purpose | Tracked? |
|---|---|---|
| `data/ingest-plan.yaml` | Doc list driving ingestion order; week-by-week target sets | ✓ |
| `data/cached-pdfs/` | sha256-keyed local cache of downloaded source PDFs | gitignored |
| `data/extractor-output/` | Per-doc extractor JSON output (one subdir per doc) | gitignored |
| `data/chunks/` | Per-doc chunk JSON output | gitignored |
| `data/fund-catalog.yaml` | Canonical fund catalog parallel to `samples/entity-catalog.yaml` | ✓ |
| `data/system-prompt-context.md` | Pre-rendered domain primer bundle (writing draft + Gov glossary) | ✓ |
| `data/discovery-cache.yaml` | TOC-walker output: every (publisher, doc_type, fy, url) tuple discovered | ✓ |
| `ingest/discovery.py` | TOC-driven URL discovery for JLBC indexes/TOCs | ✓ |
| `ingest/url_conventions.py` | JLBC URL pattern library (baseline vs. approps, host migration) | ✓ |
| `ingest/cache.py` | sha256-keyed download cache | ✓ |
| `ingest/dispatcher.py` | Per-doc-type extractor dispatch (wraps Phase 0 wrappers) | ✓ |
| `ingest/driver.py` | Top-level ingest orchestrator that walks `ingest-plan.yaml` | ✓ |
| `chunking/types.py` | Pydantic models: `Chunk`, `ChunkSource`, `ChunkProvenance` | ✓ |
| `chunking/readers/` | Format-aware readers (one per extractor output shape) | ✓ |
| `chunking/readers/odl_reader.py` | Reads OpenDataLoader-PDF JSON → uniform internal records | ✓ |
| `chunking/readers/mineru_reader.py` | Reads MinerU HTML+JSON → uniform internal records | ✓ |
| `chunking/readers/docx_reader.py` | Reads python-docx output → uniform internal records | ✓ |
| `chunking/builders/table_chunk.py` | Whole-table chunk builder (D1, D6) | ✓ |
| `chunking/builders/narrative_chunk.py` | Narrative chunk builder (512-token target / 1024 max) | ✓ |
| `chunking/entity_stamper.py` | Resolves agency name → canonical_id with slug-alias map | ✓ |
| `chunking/builder.py` | Top-level chunking orchestrator: extractor output → chunk list | ✓ |
| `scripts/build_fund_catalog.py` | Parses s18.pdf + bd2.pdf + AFR schedules → fund catalog | ✓ |
| `scripts/load_domain_primer.py` | Renders writing draft + Gov glossary into system-prompt blob | ✓ |
| `scripts/run_phase_1a.py` | Convenience entry point: load plan, drive ingest, write chunks | ✓ |
| `tests/test_discovery.py` | Tests TOC walking, URL convention generation, slug-alias resolution | ✓ |
| `tests/test_chunking.py` | Tests chunk builders on Phase 0 extractor-output fixtures | ✓ |
| `tests/test_entity_stamper.py` | Tests slug-alias resolution + name-to-canonical fallback | ✓ |
| `tests/fixtures/` | Pinned extractor outputs from Phase 0 (small, committed) | ✓ |

Files modified:
| Path | Change |
|---|---|
| `pyproject.toml` | Add `pydantic>=2.x`, `requests>=2.x` runtime deps |
| `.gitignore` | Add `data/cached-pdfs/`, `data/extractor-output/`, `data/chunks/` |

---

## Workstream 1 — Discovery layer

**Goal:** Given a `(publisher, doc_type, fiscal_year)` tuple, enumerate every URL we'd want to ingest from that document. TOC-driven, not hardcoded — approps page-keyed filenames (`452.pdf`, `459.pdf`) shift year over year, so static URL templating can't enumerate them. Reading the TOC PDF's link annotations gives us the authoritative list.

### Task 1.1: URL convention library

**Files:**
- Create: `ingest/url_conventions.py`
- Create: `tests/test_url_conventions.py`

The static patterns (per cross-doc-relationships §7): JLBC baseline URLs at `<YY>baseline/...`, approps at `<YY>ar/...`, host migration to `azleg.gov/jlbc/<YY>AR/...` for FY15-FY22.

- [ ] **Step 1: Write failing tests for URL pattern generation**

`tests/test_url_conventions.py`. For each of:
- `baseline_index_url(2027)` → `https://www.azjlbc.gov/27baseline/agencyindex.pdf`
- `baseline_index_url(2023)` → `https://www.azjlbc.gov/23baseline/agencyindex.pdf` (oldest baseline we have)
- `approps_index_url(2026)` → `https://www.azjlbc.gov/26ar/agencyindex.pdf`
- `approps_index_url(2015)` → `http://www.azleg.gov/jlbc/15AR/agencyindex.pdf` (legacy host)
- `baseline_links_url(2027)` → `https://www.azjlbc.gov/budget/27baselinelinks.pdf`
- `approps_toc_url(2026)` → `https://www.azjlbc.gov/26ar/apprpttoc.pdf`
- `per_agency_url("baseline", 2027, "axs")` → `https://www.azjlbc.gov/27baseline/axs.pdf`

Plus the boundary cases:
- `approps_per_agency_url(2022, "rev")` — uses legacy host AND old slug
- `approps_per_agency_url(2023, "rev")` — new host, slug still `rev` (the rename is FY27)
- `baseline_per_agency_url(2027, "rev")` — should this fail (canonical FY27 slug is `dor`)? Or auto-resolve via alias? Decision: caller passes canonical slug; this layer doesn't resolve aliases. Slug-alias resolution lives in entity_stamper.

- [ ] **Step 2: Implement to pass tests**

Hardcode the host-migration cutoff as a constant: `LEGACY_HOST_MAX_FY = 2022`. JLBC's behavior is empirically observed; if it changes, update the constant.

- [ ] **Step 3: Document the patterns in module docstring**

Reference cross-doc-relationships §7 from the docstring so future maintenance has the rationale.

### Task 1.2: TOC walker (link-annotation reader)

**Files:**
- Create: `ingest/discovery.py`
- Create: `tests/test_discovery.py`

PyMuPDF reads link annotations on PDF pages. Phase 0's `scripts/build_agency_catalog.py` already does this for `agencyindex.pdf` — extract the pattern into a reusable module.

- [ ] **Step 1: Failing test — agency-index walker**

```python
def test_walk_agency_index_fy27_baseline():
    entries = walk_agency_index("samples/raw-pdfs/jlbc-baseline-fy2027-agency-index.pdf")
    # Spot-check a few known agencies
    axs = [e for e in entries if e.slug == "axs"][0]
    assert axs.canonical_name == "Health Care Cost Containment System, Arizona"
    assert axs.url.endswith("/27baseline/axs.pdf")
    # Total count from Phase 0 work: 110 agencies in FY27 baseline
    assert len(entries) == 110
```

- [ ] **Step 2: Implement `walk_agency_index(pdf_path) -> list[AgencyIndexEntry]`**

Reuse the link-rect-to-text logic from `scripts/build_agency_catalog.py`. Returns a typed list (Pydantic model). Move shared logic into `ingest/discovery.py`; `scripts/build_agency_catalog.py` can import from it.

- [ ] **Step 3: Failing test — approps TOC walker**

`apprpttoc.pdf` lists cross-cut PDFs (`bh*.pdf`, `bd*.pdf`, `<page>.pdf`). Different shape than agency index — entries have section titles + section type (Budget Highlights, Budget Detail, Detailed List, etc.).

```python
def test_walk_approps_toc_fy26():
    entries = walk_approps_toc("https://www.azjlbc.gov/26ar/apprpttoc.pdf")
    # bh2.pdf is the FY 2025-FY 2028 GF Statement; spot check it
    bh2 = [e for e in entries if e.url.endswith("/bh2.pdf")][0]
    assert "General Fund Revenues and Expenditures" in bh2.title
    # bd2.pdf is "Summary of Appropriated Funds by Agency"
    bd2 = [e for e in entries if e.url.endswith("/bd2.pdf")][0]
    assert "Funds by Agency" in bd2.title
```

- [ ] **Step 4: Implement `walk_approps_toc(pdf_or_url) -> list[ApproprTOCEntry]`**

Returns each link target with title + URL + an inferred section_kind (Budget Highlights / Budget Detail / Detailed List / Other).

- [ ] **Step 5: Failing test — baseline-links walker**

`<YY>baselinelinks.pdf` is the baseline TOC equivalent. Returns entries pointing at `s<N>.pdf` files plus per-section topical PDFs (`capitaloutlay.pdf`, `crr.pdf`, etc.).

- [ ] **Step 6: Implement `walk_baseline_links(pdf_or_url) -> list[BaselineLinksEntry]`**

### Task 1.3: Discovery cache + driver

**Files:**
- Create: `data/discovery-cache.yaml`
- Update: `ingest/discovery.py`

Walking three TOC PDFs per fiscal year × multiple years is slow if done every run. Cache the discovery output to `data/discovery-cache.yaml` keyed by `(publisher, doc_type, fy)`. Re-walk only when the source TOC PDF's sha256 changes.

- [ ] **Step 1: Failing test — discovery cache hit/miss behavior**

Test that walking the same TOC twice doesn't re-download or re-parse. Test that bumping the source PDF's sha256 invalidates the cache.

- [ ] **Step 2: Implement `discover(publisher, doc_type, fy) -> DiscoveryResult`**

Wraps the three walkers above. Writes/reads `data/discovery-cache.yaml`.

---

## Workstream 2 — Per-doc-type extractor dispatch

**Goal:** Given a downloaded source file (PDF or DOCX) plus its doc_type, route to the right extractor, capture the output deterministically.

The Phase 0 wrappers (`run_mineru.py`, `run_opendataloader.py`, `run_docx_ingest.py`) already work and are tested. Phase 1a wraps them into a dispatcher that picks based on doc_type — and adds a sha256-keyed download cache so we don't re-download a 60 MB PDF on every run.

### Task 2.1: Download cache

**Files:**
- Create: `ingest/cache.py`
- Create: `tests/test_cache.py`

- [ ] **Step 1: Failing test — sha256-keyed cache**

```python
def test_cache_round_trip():
    cache = DownloadCache("data/cached-pdfs")
    path = cache.fetch("https://www.azjlbc.gov/27baseline/s18.pdf")
    assert path.exists()
    assert sha256_of(path) == known_sha256_for_s18_fy27
    # Second fetch should be local (no network)
    path2 = cache.fetch("https://www.azjlbc.gov/27baseline/s18.pdf")
    assert path == path2
```

- [ ] **Step 2: Implement DownloadCache**

Stores at `data/cached-pdfs/<sha256-prefix>/<sha256>.pdf`. On fetch: check cache by URL→sha256 manifest; download if missing; verify sha256 after write. Manifest entry: `(url, sha256, byte_size, fetched_at)`.

- [ ] **Step 3: Pre-populate cache from Phase 0 samples**

`samples/raw-pdfs/` and `samples/raw-docx/` already have validated content. Write a one-time migration that hashes each, indexes into the cache manifest under both the original URL and the local-file sentinel. Avoids re-downloading what we already have.

### Task 2.2: Doc-type → extractor dispatch

**Files:**
- Create: `ingest/dispatcher.py`
- Create: `tests/test_dispatcher.py`

Per chunk-shape D4 + spec §9:
- `afr` → OpenDataLoader (tagged PDF, structure tree)
- `governors-budget` → OpenDataLoader (tagged PDF, rich outline)
- `baseline-book`, `approps-report` → MinerU (untagged, table detection needed)
- `budget-bill` → python-docx
- `s-pdf`, `bh-pdf`, `bd-pdf`, `topic-pdf` → MinerU (small focused tabular PDFs)

- [ ] **Step 1: Failing test — extractor selection by doc_type**

```python
def test_dispatch_picks_odl_for_afr():
    extractor = pick_extractor(doc_type="afr", source_format="pdf")
    assert extractor.name == "opendataloader"

def test_dispatch_picks_mineru_for_jlbc_baseline():
    extractor = pick_extractor(doc_type="baseline-book", source_format="pdf")
    assert extractor.name == "mineru"

def test_dispatch_picks_python_docx_for_budget_bill():
    extractor = pick_extractor(doc_type="budget-bill", source_format="docx")
    assert extractor.name == "python-docx"
```

- [ ] **Step 2: Implement `pick_extractor(doc_type, source_format) -> Extractor`**

Lookup table. Errors loudly on unknown combinations rather than guessing.

- [ ] **Step 3: Failing test — end-to-end extract on s18.pdf**

```python
def test_extract_s18_baseline_fy27():
    result = extract(
        local_path="data/cached-pdfs/<sha>/jlbc-baseline-fy2027-s18.pdf",
        doc_type="s-pdf",
        publisher="jlbc",
        fiscal_year=2027,
    )
    assert result.extractor == "mineru"
    assert len(result.tables) >= 1   # s18 is one big table
    assert result.output_dir.exists()
```

- [ ] **Step 4: Implement `extract(...)` wrapping the existing scripts**

`scripts/run_mineru.py` and friends already accept the right arguments. Dispatcher wraps them as subprocesses (or imports their `extract()` functions if those exist). Output goes under `data/extractor-output/<doc-id>/` with a manifest file recording extractor name, version, and inputs for reproducibility.

### Task 2.3: Top-level ingest driver

**Files:**
- Create: `ingest/driver.py`
- Create: `data/ingest-plan.yaml`

The driver reads `data/ingest-plan.yaml`, walks the listed docs, calls discovery + cache + extract for each.

- [ ] **Step 1: Write `data/ingest-plan.yaml` for Week 1**

```yaml
# Phase 1a Week 1 ingest target list — Order C (cross-cuts first).
# See docs/superpowers/plans/2026-05-06-phase-1a-ingestion-and-chunking.md
# for the rationale; the list is intentionally configurable so we can
# pivot to Order B if dogfood data argues for it.

order_hypothesis: |
  Order C — front-load JLBC cross-cut s/bh/bd-PDFs because most simple
  lookup queries have their best answer in a single cross-cut chunk per
  cross-doc-relationships §2. Per-agency PDFs in Week 2; singlefiles
  deferred to a Phase 1b safety-net.

week_1:
  - publisher: jlbc
    doc_type: baseline-cross-cut       # discovery walks 27baselinelinks.pdf
    fiscal_year: 2027
  - publisher: jlbc
    doc_type: approps-cross-cut         # discovery walks 26ar/apprpttoc.pdf
    fiscal_year: 2026
  - publisher: legislature
    doc_type: budget-bill
    fiscal_year: 2026
    local_path: samples/raw-docx/budget-bill-sb1735-2025.docx

week_2:
  - publisher: jlbc
    doc_type: baseline-per-agency       # discovery walks 27baseline/agencyindex.pdf, then enumerates each <slug>.pdf
    fiscal_year: 2027

week_3:
  - publisher: jlbc
    doc_type: baseline-per-agency
    fiscal_year: 2026
  - publisher: jlbc
    doc_type: approps-per-agency
    fiscal_year: 2025
  - publisher: agao
    doc_type: afr
    fiscal_year: 2025
    local_path: samples/raw-pdfs/agao-afr-fy25.pdf
  - publisher: governor
    doc_type: governors-budget
    fiscal_year: 2027
    local_path: samples/raw-pdfs/governors-state-agency-detail-fy27.pdf
  # Sources and Uses deferred — 919 pages, 8 outline entries, the hardest
  # extraction target. May be Phase 2 work if Phase 1 retrieval can answer
  # most fund-level queries from JLBC s18.pdf cross-cut.
```

- [ ] **Step 2: Failing test — ingest plan parsing + Week 1 dry run**

```python
def test_ingest_plan_week_1_dry_run():
    plan = load_plan("data/ingest-plan.yaml")
    targets = plan["week_1"]
    dry_run_results = [resolve_to_urls(t) for t in targets]
    # Week 1 should resolve to: 15 baseline s-PDFs + 28 approps cross-cuts + 1 DOCX
    total_urls = sum(len(r.urls) for r in dry_run_results)
    assert 40 < total_urls < 50  # rough sanity bound
```

- [ ] **Step 3: Implement driver**

For each target: resolve via discovery → fetch via cache → extract via dispatcher. Write a per-doc manifest under `data/extractor-output/<doc-id>/manifest.json` with `(publisher, doc_type, fiscal_year, source_url, sha256, extractor, extractor_version, extracted_at)`.

---

## Workstream 3 — Chunking layer (the heart)

**Goal:** Format-aware reader that consumes any extractor's output and produces uniform `Chunk` rows. Per chunk-shape D4-D7.

This is the biggest workstream. Splits into: type definitions, three readers, two builders, entity stamper, orchestrator.

### Task 3.1: Chunk type definitions

**Files:**
- Create: `chunking/types.py`
- Create: `tests/test_types.py`

Pydantic models for the chunk schema. Mirrors spec §6 SQL schema but lives in Python until Phase 1b serializes to Postgres.

- [ ] **Step 1: Write Pydantic models matching spec §6**

```python
class ChunkProvenance(BaseModel):
    # Polymorphic per chunk-shape D3 + spec §6
    page: int | None = None              # PDF only
    bbox: list[float] | None = None      # PDF only — multi-rect flattened
    paragraph_id: str | None = None      # DOCX only — w14:paraId
    table_cell_id: str | None = None     # DOCX only — for table cells

    @model_validator
    def at_least_one_provenance(self):
        # CHECK constraint from spec §6
        if self.page is None and self.paragraph_id is None:
            raise ValueError("provenance requires page or paragraph_id")

class Chunk(BaseModel):
    chunk_id: str
    doc_id: str
    text: str
    section_path: list[str]              # ['Department of Corrections', 'Operating Lump Sum']
    is_table: bool = False
    table_html: str | None = None
    provenance: ChunkProvenance
    agency_canonical_id: str | None = None
    fund_canonical_id: str | None = None
    fiscal_year: int
    doc_type: str
    publisher: str
    token_count: int
```

`embedding` deliberately omitted — Phase 1b adds it.

- [ ] **Step 2: Failing test — round-trip JSON serialization**

Chunks must serialize to JSON cleanly for hand-off to Phase 1b's storage layer. Test that `Chunk.model_dump_json()` round-trips.

### Task 3.2: Format-aware readers

Three readers, one per extractor. Each emits a uniform internal record shape (`ExtractedDocument`) that the chunk builders consume. Decouples extractor specifics from chunking logic.

#### Task 3.2.a: ODL reader

**Files:**
- Create: `chunking/readers/odl_reader.py`
- Create: `tests/test_odl_reader.py`
- Test fixture: `tests/fixtures/odl-afr-p163.json` (small Phase 0 sample)

OpenDataLoader emits per-element JSON with `type`, `bounding box`, `content`, structure-tree hierarchy. Per Phase 0's `samples/extractor-output/opendataloader/README.md`.

- [ ] **Step 1: Failing test — read AFR p163 fixture**

```python
def test_odl_reader_afr_p163():
    doc = ODLReader().read("tests/fixtures/odl-afr-p163.json")
    assert doc.has_tables
    assert doc.outline_path("Note 6")[-1] == "Statement of Revenues, Expenditures and Changes in Fund Balance"
```

- [ ] **Step 2: Implement ODL reader**

Reads ODL JSON → emits an `ExtractedDocument` with `pages: list[Page]`, each `Page` having `blocks: list[Block]` (typed: paragraph / heading / table / image). Tables expose `cells: list[Cell]` with row/col indices.

- [ ] **Step 3: Outline tree extraction**

ODL's structure-tree info lives at the document level. Parse `Doctitle`/`H1`/`H2` etc. into a section tree. For tagged PDFs (AFR, Gov SAD), this gives chunk-builder D6 header propagation for free.

#### Task 3.2.b: MinerU reader

**Files:**
- Create: `chunking/readers/mineru_reader.py`
- Create: `tests/test_mineru_reader.py`
- Test fixture: `tests/fixtures/mineru-jlbc-approps-p513.json` (small Phase 0 sample)

MinerU emits Markdown + `_content_list.json` with bbox per block. Tables come through as HTML strings. Per Phase 0's `samples/extractor-output/mineru/README.md`.

- [ ] **Step 1: Failing test — read JLBC approps p513 fixture**

```python
def test_mineru_reader_approps_p513():
    doc = MinerURead().read("tests/fixtures/mineru-jlbc-approps-p513.json")
    assert len(doc.tables) >= 1
    parks_table = doc.tables[0]
    # The "Parks Statewide Solar Shade Structures" line item lives in this table
    assert any("Parks" in cell.text for row in parks_table.rows for cell in row.cells)
```

- [ ] **Step 2: Implement MinerU reader**

Tables → parse the HTML string into row/col cells (BeautifulSoup or lxml). Other blocks (paragraph, heading, image) → typed records. Bbox from `_content_list.json` joined to each block.

- [ ] **Step 3: Heading detection from font/size cues**

MinerU's `text_level` integer is its heading signal — already documented. Treat `text_level: 1/2/3` as section headings; build a section tree by stack-pushing on heading encounters.

- [ ] **Step 4: Multi-page table reassembly**

When a table appears on consecutive pages with the same column headers, reassemble into one logical table object. Chunk-shape D2 — "logical table" = semantic sub-table, not printed-page table. Multi-page tables are one chunk.

#### Task 3.2.c: DOCX reader

**Files:**
- Create: `chunking/readers/docx_reader.py`
- Create: `tests/test_docx_reader.py`
- Test fixture: `tests/fixtures/docx-sb1735-sample.json` (output of Phase 0 `run_docx_ingest.py`)

Bills have two-part structure (cross-doc-relationships §9): Part 1 agency tables (`Normal` style headings + `P 06-*` body), Part 2 provisions (`SEC 06-18` / `SEC 06-19` style markers).

- [ ] **Step 1: Failing test — DOCX section detection**

```python
def test_docx_reader_sb1735_part_2():
    doc = DocxReader().read("tests/fixtures/docx-sb1735-sample.json")
    sec_06_18 = [s for s in doc.sections if s.style == "SEC 06-18"]
    assert len(sec_06_18) == 28  # per data-model §3d
    sec_06_19 = [s for s in doc.sections if s.style == "SEC 06-19"]
    assert len(sec_06_19) == 18
```

- [ ] **Step 2: Implement DOCX reader**

Walk paragraphs; section boundary at any `SEC 06-*` style or `Normal` style with all-caps "DEPARTMENT OF X" pattern. Each section's body runs from the heading paragraph until the next heading.

- [ ] **Step 3: Bill heading parser — semicolon → tuple**

Per cross-doc-relationships §9: section heading text follows `<action>; <target>; <fiscal_year>; ...` pattern. Implement `parse_bill_heading(text) -> dict` returning `{action, target, fiscal_year, modifiers}`. Action types observed: "Supplemental appropriation", "Appropriation reduction", "Appropriation", "Fund balance transfer", etc. Match by prefix; unknown actions fall through with `action: "other"` and the original heading text preserved.

- [ ] **Step 4: A.R.S. citation capture**

`parse_bill_body(text) -> {ars_refs: list[str]}`. Extract A.R.S. section references via regex (`section \d+-\d+(\.\d+)?`). Capture as metadata on each body paragraph; useful for citation enrichment in a later phase.

### Task 3.3: Chunk builders

Two builders, one per chunk type per chunk-shape D5.

#### Task 3.3.a: Table chunk builder

**Files:**
- Create: `chunking/builders/table_chunk.py`
- Create: `tests/test_table_chunk.py`

Per chunk-shape D1 + D6: whole logical table is one chunk. Headers + section path stamped into both `text` (for retrieval embedding) and structured metadata.

- [ ] **Step 1: Failing test — table chunk on JLBC approps p513**

```python
def test_build_table_chunk_jlbc_approps_p513():
    doc = MinerURead().read("tests/fixtures/mineru-jlbc-approps-p513.json")
    table = doc.tables[0]
    chunk = build_table_chunk(
        table, doc, doc_meta=fake_doc_meta_jlbc_approps_fy26
    )
    # Chunk-shape D6 — header propagation in embedded text
    assert "Department of Administration" in chunk.section_path
    assert "FY2026" in chunk.text  # column header denormalized
    assert chunk.is_table
    assert chunk.table_html is not None
```

- [ ] **Step 2: Implement `build_table_chunk(table, doc, doc_meta) -> Chunk`**

Embedded text format: section path → caption → header row → flattened cells. Each row appears as one line for retrieval signal. Original HTML preserved in `table_html` for UI rendering.

- [ ] **Step 3: Big-table subdivision (chunk-shape D-defer-2)**

When a logical table exceeds 3K tokens, subdivide at next-level heading per the deferred decision. Heuristic; revisit when we see real corpus distribution. For now: simple guard at `if token_count > 3000:` — log a warning, build the chunk anyway, flag for manual review. Phase 1b's eval set will surface whether this breaks retrieval quality.

#### Task 3.3.b: Narrative chunk builder

**Files:**
- Create: `chunking/builders/narrative_chunk.py`
- Create: `tests/test_narrative_chunk.py`

Per chunk-shape D5: 512-token target, 1024-token max. Per-paragraph or per-section; sliding window with ~15% overlap for cross-section boundary cases.

- [ ] **Step 1: Failing test — narrative chunk emission**

```python
def test_narrative_chunks_respect_token_limits():
    doc = MinerURead().read("tests/fixtures/mineru-jlbc-baseline-axs.json")
    chunks = build_narrative_chunks(doc, doc_meta=...)
    for c in chunks:
        assert 50 < c.token_count <= 1024
    # All chunks have section_path stamped
    for c in chunks:
        assert len(c.section_path) >= 1
```

- [ ] **Step 2: Implement narrative chunking**

Naive paragraph-based split → merge sequential paragraphs up to 512 tokens → never split mid-paragraph. Section path inherited from the heading hierarchy walked during reader pass.

- [ ] **Step 3: Embedded-values handling (chunk-shape D-defer-3, partial)**

Some narrative paragraphs reference specific dollar values that also appear in table chunks ("AHCCCS received $14.5B…"). Chunk-shape D-defer-3 says we'll pick a chunk-type-priority rule once we see real query→retrieval behavior. For Phase 1a: do nothing special — both narrative and table chunks coexist; retrieval surfaces whichever scores higher. Note this in the chunk's metadata so we can filter/boost in Phase 1b retrieval if needed.

### Task 3.4: Entity stamper

**Files:**
- Create: `chunking/entity_stamper.py`
- Create: `tests/test_entity_stamper.py`

Per chunk-shape D7 — entity normalization is required, not optional. Three resolution rules per cross-doc-relationships §5:
1. Direct slug match (JLBC URL gives slug for free)
2. Alias map lookup (`samples/agency-slug-aliases.yaml`)
3. Name-based match against entity catalog with edit-distance fallback

- [ ] **Step 1: Failing tests — three resolution paths**

```python
def test_stamp_jlbc_url_direct_slug():
    chunk = chunk_from_jlbc_url(url="https://www.azjlbc.gov/27baseline/axs.pdf", ...)
    stamped = stamp(chunk)
    assert stamped.agency_canonical_id == "agency:axs"

def test_stamp_alias_old_slug():
    chunk = chunk_from_jlbc_url(url="https://www.azjlbc.gov/26ar/rev.pdf", ...)
    stamped = stamp(chunk)
    # rev → dor per aliases.yaml; FY26 doc, but we resolve to current canonical
    assert stamped.agency_canonical_id == "agency:dor"
    assert "rev" in stamped.alias_chain  # observability

def test_stamp_name_based_governor():
    # Gov SAD doesn't carry slugs; resolve by canonical name
    chunk = chunk_with_section_path(["Department of Corrections", ...], publisher="governor")
    stamped = stamp(chunk)
    assert stamped.agency_canonical_id == "agency:adc"

def test_stamp_ocr_drift_fuzzy_match():
    chunk = chunk_with_section_path(["Boseline Book", "Deportment of Revenue", ...])
    stamped = stamp(chunk)
    assert stamped.agency_canonical_id == "agency:dor"
```

- [ ] **Step 2: Implement `stamp(chunk) -> Chunk`**

Loads `samples/entity-catalog.yaml` and `samples/agency-slug-aliases.yaml` once at module init. For each chunk:
- If `chunk.source_url` is JLBC: extract slug from URL, resolve via alias map, return `agency:<resolved_slug>`.
- Else: scan `chunk.section_path` and chunk text for canonical names from the catalog. Edit-distance fallback when no exact match (use rapidfuzz at ratio ≥ 85).
- If still no match: leave `agency_canonical_id = None`, log to a "needs review" file for manual triage.

- [ ] **Step 3: Fund stamping (depends on fund catalog from Workstream 4)**

Same pattern, against `data/fund-catalog.yaml`. Most chunks will mention multiple funds (a single agency table touches several). For Phase 1a: stamp the *primary* fund only (first detected with highest confidence); list secondary funds in a `fund_mentions: list[str]` metadata field.

### Task 3.5: Top-level chunking orchestrator

**Files:**
- Create: `chunking/builder.py`
- Create: `tests/test_builder.py`

Walks one extractor's output and calls the right reader → builders → stamper, emits per-doc JSON to `data/chunks/<doc-id>.json`.

- [ ] **Step 1: Failing test — full chunking pass on s18 fixture**

```python
def test_chunk_s18_baseline_fy27():
    chunks = chunk_doc(
        extractor_output_dir="data/extractor-output/jlbc-baseline-fy2027-s18",
        doc_meta=DocMeta(publisher="jlbc", doc_type="s-pdf", fiscal_year=2027, ...),
    )
    # s18 is one big table; expect 1 chunk
    assert len(chunks) == 1
    s18 = chunks[0]
    assert s18.is_table
    assert "Other Appropriated Funds" in s18.text
    # All 110 FY27 agencies should appear in the embedded text
    for slug in ALL_FY27_AGENCY_SLUGS:
        # at least most should appear; allow a small miss tolerance for OCR drift
        ...
```

- [ ] **Step 2: Implement orchestrator**

Picks reader by `doc_meta.extractor`, loads extractor output, calls `build_table_chunks` and `build_narrative_chunks` separately, stamps every chunk, writes `data/chunks/<doc-id>.json` with one Chunk record per line (NDJSON for streaming).

---

## Workstream 4 — Fund catalog

**Goal:** Build a canonical fund catalog parallel to the agency catalog. Required so chunk-builder D7 can stamp `fund_canonical_id` on fund-level chunks.

### Task 4.1: Parse s18.pdf for fund × agency × amount tuples

**Files:**
- Create: `scripts/build_fund_catalog.py`
- Create: `data/fund-catalog.yaml`

`s18.pdf` (FY27 baseline) has the canonical "every appropriated fund × every agency" matrix.

- [ ] **Step 1: Extract via the existing dispatcher**

Run `dispatcher.extract(local_path="...s18.pdf", doc_type="s-pdf")` to get MinerU output.

- [ ] **Step 2: Parse the table**

s18 uses a known shape: agency name (full row span), then one row per fund the agency uses, ending with an agency total. Walk rows to extract `(agency_canonical_name, fund_name, fy26_amount, fy27_amount)`.

- [ ] **Step 3: Derive fund slugs**

No publisher-issued fund slug exists, so we generate them. Rules:
- Lowercase, replace non-alphanumeric with `-`.
- Drop "fund" suffix when present.
- Collapse consecutive hyphens.
- Examples: "Aviation Fund" → `aviation`; "State Highway Fund" → `state-highway`; "Health Innovation Trust Fund" → `health-innovation-trust`.

Slug derivation lives in the catalog builder, not the chunking layer — so the stamping rules read a finished catalog with stable slugs.

- [ ] **Step 4: Cross-validate with bd2.pdf (FY26 approps equivalent)**

bd2.pdf is the FY26 approps cross-cut equivalent of s18. The fund list should be ~identical; differences flag funds added/removed between FY26 enacted and FY27 baseline. Capture as lifecycle metadata parallel to the agency lifecycle.

- [ ] **Step 5: Cross-validate with AFR fund-balance schedules**

AFR's pp.110-172 is the audited authoritative fund register. Walk the AFR's fund list; flag funds in s18 that don't appear in AFR (likely non-appropriated or off-budget) and vice-versa. The diff is informative but not blocking — keep both AFR-known and JLBC-known funds in the catalog with a `present_in: [jlbc-s18, jlbc-bd2, agao-afr]` field.

- [ ] **Step 6: Emit `data/fund-catalog.yaml`**

Same shape as agency catalog: per-fund entries with canonical name, slug, aliases, and `_meta` block for stats.

### Task 4.2: Fund alias / lifecycle tracking

**Files:**
- Update: `data/fund-catalog.yaml`

Funds get renamed and merged across years. Same pattern as agency aliases.

- [ ] **Step 1: Backfill prior years' s18 equivalents**

Re-run catalog builder against earlier years' baseline cross-cuts (`s18` files for FY23, FY24, FY25, FY26 baselines, plus `bd2` files for FY15-FY26 approps). Compare fund lists year-over-year; surface renames for manual confirmation.

- [ ] **Step 2: Emit `data/fund-aliases.yaml`** (only if renames are found)

Same shape as `samples/agency-slug-aliases.yaml`. Likely smaller — funds are renamed less often than agencies.

---

## Workstream 5 — Domain primer ingestion

**Goal:** Pre-render the writing draft + Gov glossary into a single system-prompt context blob the LLM (Phase 1c) loads on every query.

### Task 5.1: Writing draft → Markdown

**Files:**
- Create: `scripts/load_domain_primer.py`
- Create: `data/system-prompt-context.md`

`docs/reference/jlbc-writing-draft-final.docx` is a DOCX. Reuse `run_docx_ingest.py`'s output, render as Markdown.

- [ ] **Step 1: Extract**

```bash
uv run python scripts/run_docx_ingest.py \
  --in docs/reference/jlbc-writing-draft-final.docx \
  --out data/extractor-output/writing-draft
```

- [ ] **Step 2: Render to Markdown**

Walk paragraphs in order; preserve heading hierarchy; convert tables to Markdown tables. Output: `data/system-prompt-context.md` with a section divider — first half is the writing draft.

### Task 5.2: Gov glossary → structured form

**Files:**
- Update: `data/system-prompt-context.md`

Pages 626-633 of `governors-state-agency-detail-fy27.pdf` carry the two-part glossary: Budget Terms (formal definitions) + Acronyms list.

- [ ] **Step 1: Extract pages 626-633**

```bash
uv run python scripts/run_opendataloader.py \
  --pdf samples/raw-pdfs/governors-state-agency-detail-fy27.pdf \
  --out data/extractor-output/gov-glossary \
  --pages 626-633
```

- [ ] **Step 2: Parse Budget Terms**

Each entry is a `**term**` heading followed by 1-3 paragraphs. Render as Markdown definition list.

- [ ] **Step 3: Parse Acronyms**

Two-column layout: acronym → expansion. Render as a Markdown table.

- [ ] **Step 4: Append to `data/system-prompt-context.md`**

Section divider after the writing draft. Writing draft + glossary sit side by side; Phase 1c loads the whole file as system prompt context.

### Task 5.3: AFR Notes section ingestion

**Files:**
- (Phase 1a touches this lightly; full linkage deferred to Phase 1b retrieval scoring)

AFR Notes 1-12 (pp. 174-181) define and contextualize the financial-statement tables. Per cross-doc-relationships §8, these should be associated with the table chunks they describe — but the specific pairing requires retrieval-side logic.

For Phase 1a: ingest Notes as their own chunks (under doc_id `agao-afr-fy25-notes`) with full text, but no table-association metadata yet. Phase 1b's retrieval scoring will boost a Notes chunk when a related table chunk is retrieved.

- [ ] **Step 1: Extract Notes pages**

Already extracted as part of full-AFR ingest in Workstream 2. No new extraction.

- [ ] **Step 2: Chunk per Note**

Each Note (Note 1, Note 2, ..., Note 12) becomes one narrative chunk with `section_path = ["Notes to Financial Statements", "Note N — <title>"]`. Most Notes are short (< 500 tokens), so they fit comfortably below the narrative chunk size limit.

- [ ] **Step 3: Capture defined-table-name → chunk-id mapping**

Note 6 explicitly names "Statement of Revenues, Expenditures and Changes in Fund Balance" — when ingesting the AFR's matching fund-balance tables, capture them under the same logical-table name. Phase 1b can join on it.

---

## Workstream 6 — Integration tests + Week-4 validation

**Goal:** Hand-validate the full Phase 1a output before handing off to Phase 1b storage.

### Task 6.1: Smoke-query against Week-1 chunks

- [ ] **Step 1: Pick 5 representative analyst queries from cross-doc-relationships §2**

```yaml
test_queries:
  - q: "What funds does AHCCCS use?"
    expected_chunk_doc_id: jlbc-baseline-fy2027-s18
    expected_row_label_substring: "Health Care Cost Containment"
  - q: "Show me the One-Time GF Adjustments for FY 2026"
    expected_chunk_doc_id: jlbc-approps-fy2026-bh20
  - q: "What did the FY 2026 GAA appropriate to ADC?"
    expected_chunk_doc_id: budget-bill-sb1735-2025
    expected_section_style: "SEC 06-18"
  - q: "What's the FTE headcount for ADOT?"
    expected_chunk_doc_id: jlbc-baseline-fy2027-s83
  - q: "What's in the Aviation Fund?"
    expected_chunk_doc_id: jlbc-baseline-fy2027-s18
    expected_row_label_substring: "Aviation"
```

- [ ] **Step 2: Naive in-memory retrieval**

For Phase 1a only: load all chunks into memory, embed each query into a TF-IDF vector, rank by cosine similarity. No Voyage embeddings, no BM25, no rerank — just enough to verify the chunks contain the right content. If the right chunk doesn't even rank top-3 on TF-IDF, something is wrong with chunk-shape or entity stamping; fix before handing to Phase 1b.

- [ ] **Step 3: Manual chunk inspection**

Open `data/chunks/jlbc-baseline-fy2027-s18.json` in a text editor. Verify:
- Section path is populated
- All 110 FY27 agency slugs appear in the embedded text (or at least most — note OCR drift cases)
- `agency_canonical_id` is stamped on every chunk (or `None` with the chunk logged for review)
- Provenance has page + bbox for PDF chunks, paragraph_id for DOCX chunks

### Task 6.2: Catalog audit

- [ ] **Step 1: Re-run Phase 0 entity catalog builder against Week-1 + Week-2 chunks**

`scripts/sweep_entities.py` iterates `samples/extractor-output/`. After Phase 1a ingestion, point it at `data/extractor-output/` and re-run. New unmatched candidates feed back into the entity catalog or aliases file.

- [ ] **Step 2: Manual review of `agency-slug-aliases.yaml#pending_for_phase_1`**

Phase 0 left four open items (pending review of `eliminated_or_merged` notes; resolve `doa-cfs / doa-csf / doa-sfd / sfb` identity; verify `ban → dif` merger; check approps-fy2015 hosting URL path). Phase 1a Week 3 ingests FY15-FY22 approps — that's when these resolve naturally. Document the resolutions back into `agency-slug-aliases.yaml`.

### Task 6.3: Hand-off package for Phase 1b

- [ ] **Step 1: Write `data/chunks/MANIFEST.md`**

Lists every doc ingested, chunk count, sha256 of the chunk file, and a sample chunk-id from each. Phase 1b uses this as the input contract.

- [ ] **Step 2: Tag the merge commit `phase-1a-complete`**

After integration tests pass and the manifest is written. Phase 1b starts from this tag.

---

## Deferred decisions (explicit non-goals)

These don't block Phase 1a closure. Capture so they're not forgotten — many become Phase 1b or Phase 1c work.

- **Embeddings (Voyage-3-large).** Phase 1b. Embeddings get joined to chunks at storage time, not at chunk-build time.
- **Multi-page table reassembly across logical-table boundaries.** Phase 1a does same-doc same-section reassembly. Cross-section assembly (e.g., AFR's Fund Balance schedule continues across multiple sub-PDFs) deferred until we see whether retrieval needs it.
- **Singlefile fallback.** If per-agency PDF for an agency × FY combination is missing, we'd fall back to the singlefile and slice by page range. Not implemented in Phase 1a — assume per-agency PDFs exist for everything Week 2 targets. If missing, log and skip; Week 3 backfill can add the singlefile path then.
- **Sources and Uses (Gov S&U) ingestion.** 919 pages, weak outline. Deferred to Phase 2 unless Phase 1 retrieval proves to need it.
- **AFR Note → Table chunk pairing logic.** Captured in Workstream 5 Task 5.3 as a metadata-only step. Retrieval-side boosting is Phase 1b.
- **Faithfulness verifier construction.** Phase 1c.
- **Custom JLBC deterministic extractor (chunk-shape D-defer-1 option (c)).** Only escalate if Week-2 per-agency MinerU error rate proves unacceptable on real ingest.

## What "Phase 1a done" means

By the end of Phase 1a:

- 5+ fiscal years of source content extracted to `data/extractor-output/`
- ~3000+ chunks emitted to `data/chunks/` (rough estimate; bounded by per-agency PDF count × years + cross-cut PDF count × years + bills + AFR + Gov SAD)
- Every chunk passes Pydantic schema validation
- ≥ 90% of chunks have `agency_canonical_id` stamped (the rest go to a review file)
- Fund catalog populated with ≥ 80 funds; cross-validated with AFR
- Domain primer rendered into `data/system-prompt-context.md`
- 5 smoke-query test cases pass on TF-IDF retrieval (proves chunks contain the right content for representative analyst questions)
- `data/chunks/MANIFEST.md` written; `phase-1a-complete` tag created

Phase 1b then takes the chunk JSON + fund catalog + system-prompt context as inputs and builds storage + retrieval on top.

## Pointer to the conversation

The Phase 1 split decision (this plan = 1a, separate 1b for storage/retrieval, separate 1c for companion/UI) and the Order C ingest decision were settled during the Phase 1 cleanup pass on 2026-05-06. See `docs/superpowers/investigations/2026-05-06-phase-0-findings.md` for the input state.
