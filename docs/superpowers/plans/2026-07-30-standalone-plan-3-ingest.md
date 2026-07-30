# Standalone Plan 3: Ingest — Upload GUI, Queue, Fiscal-Note Corpus

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the corpus self-feeding: colleagues upload PDFs/DOCX in the GUI, a persistent background queue runs MinerU → chunking → stamping → embedding → LanceDB with no manual steps; the fiscal-note corpus gets populated and refreshable from azjlbc.gov; Postgres/Docker leave the ingest path.

**Architecture:** New `ingest/jobs.py` (job records on the share) + `ingest/lock.py` (SMB-safe single-writer lock) + `ingest/worker.py` (background thread in the app process driving the existing extraction/chunking/stamping callables in-process) + `store/backup.py` (S17 snapshots). New app routes (`upload`, `jobs`, live `fiscal-notes`) + an Upload page and fiscal-note wiring in the webapp. The heavy lifting reuses the audited Plan-0/1a code paths verbatim — the 2026-07-30 codebase review (see "Ground truth" below) produced exact reuse lists; this plan cites them instead of re-specifying.

**Tech Stack:** existing Python toolchain (`mineru[pipeline]` subprocess, python-docx, PyMuPDF, fastembed, lancedb), FastAPI, React/Vite.

**Spec:** `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — S6, S10, S17, Invariant 8, ingest section (dup detection, PDF copy), testing section (fiscal-note eval). Work in a worktree (`~/ask-the-budget-az-worktrees/plan3-ingest`).

**Ground truth (READ FIRST, these are binding):** the four signature/gotcha inventories in this plan's parent review; the load-bearing ones for this plan:
- `ChunkStore` semantics: `upsert_chunks` = delete-then-add across two commits (NOT atomic); FTS index must be rebuilt (`build_fts_index`, `replace=True`) after ANY append or new rows are invisible to BM25; `optimize()` after bulk loads; all filter values through `store.chunk_store.sql_str`; `ChunkStore(dim=embedder.dim)` pattern mandatory (three-way dim lockstep at 768); non-nullable list columns need `or []`; `source_anchor` must be `json.dumps`'d; embed chunk text with `input_type="document"` (never "query").
- Reuse-as-is callables: `ingest.dispatcher.extract/pick_extractor`, `chunking.builder.chunk_doc`, `chunking.readers.*`, `chunking.builders.*` (+ `DocMeta`), `chunking.entity_stamper.EntityStamper.from_default_paths`, `ingest.driver.make_doc_id/IngestItem`, `retrieval.local_embedder.LocalEmbedder`, `scripts/export_fiscal_notes_snapshot.py` parse functions (`parse_session_html`, `chamber_of`, `leg_session`, …), `scripts/migrate_to_lancedb.py::write_documents_sidecar` (atomic tmp+`os.replace` — keep that discipline).
- Known adaptation points: `scripts/run_mineru.py::run_mineru` is `subprocess.run(["uv","run","mineru",…])` with no timeout/progress/cancel; `ingest/cache.py::DownloadCache._relative_for_sha` hardcodes `.pdf`; `db/loader.py` dies but its `DocumentMeta` field set and `chunk_to_row` polarity logic are templates; `routes/fiscal_notes.py` has an `lru_cache` that must go when data turns live.

**PARALLEL-EXECUTION CONTRACT (runs concurrently with Plan 4):**
- This plan owns: `ingest/` (new + existing), `chunking/`, `store/` (additive methods only), `scripts/` ingest-related, `app/routes/upload.py`, `app/routes/jobs.py`, `app/routes/fiscal_notes.py`, `app/ingest_*` modules, `webapp/src/pages/Upload.tsx`, the FiscalNotes page **rail search block only** (`FiscalNotes.tsx` lines around the `.fside-search.is-disabled` hook), `eval/fiscal_note_queries.yaml` + eval corpus plumbing, its own tests.
- Plan 4 owns: `harness/`, `app/routes/conversations*.py`, `app/routes/pdf.py`, `app/routes/documents.py`, `retrieval/citations.py` (promotion of `_validate_one_cite`), `webapp/src/chat/**`, `webapp/src/pdf/**`, `Search.tsx`, `Home.tsx`, `mcp-server/system-prompt.md` successor. Do NOT touch these.
- Both plans append to: `app/main.py` (one `include_router` line each — keep both on merge), `App.tsx` routes, `Header.tsx` `NAV_ITEMS`, `webapp/src/api.ts` (additive functions), `app.css` (each in its own labeled page block), `STATUS.md` (own section, final task only). These are the only expected merge points; conflicts are additive keep-both.
- Follow the shipped webapp conventions verbatim (page class + testid on `<main>`, page-scoped CSS in labeled `app.css` blocks, new API calls through `api.ts` with pages importing `* as api`, `HTTPException` with real `detail`, routers registered above the SPA catch-all).

---

## File structure

| File | Responsibility |
|---|---|
| Create `ingest/lock.py` | `IngestLock`: SMB-safe cross-process/machine single-writer lock at `<data_dir>/ingest.lock` |
| Create `ingest/jobs.py` | `JobRecord` + JSON-file journal at `<data_dir>/jobs/` (atomic writes, resume, cancel) |
| Create `ingest/worker.py` | Background worker thread: job pipeline extract→chunk→stamp→embed→write; progress; crash-resume |
| Create `ingest/mineru_runner.py` | Adapted MinerU wrapper: resolved exe, timeout, stdout progress, cooperative cancel, pinned model cache |
| Create `ingest/lance_writer.py` | `chunk_to_lance_row(chunk, vector)`, `write_doc(chunks, vectors, doc_meta)` (delete_doc→upsert→fts→optimize under lock), documents.json merge, title builder |
| Create `ingest/fiscal_notes_refresh.py` | Live scraper (`azjlbc.gov/fiscal-notes/?Year=Y`) → diff vs corpus → download PDFs → enqueue; directory JSON writer |
| Create `chunking/agency_catalog.py` | `load_agency_catalog()` / `id_to_name()` extracted from EntityStamper privates |
| Create `store/backup.py` | S17: `snapshot()` zip rotation (5) + `restore(name)`; taken before every write phase |
| Modify `store/chunk_store.py` | Add `delete_doc(name, doc_id)`; nothing else |
| Modify `chunking/types.py` + `chunking/builders/table_chunk.py` | Move `DocMeta` to types.py (re-export from old location for compat) |
| Modify `chunking/entity_stamper.py` | D2 multi-agency resolution for table chunks (`stamp_multi` path); consume `agency_catalog` loader |
| Modify `ingest/cache.py` | Real extension in `_relative_for_sha`; atomic manifest writes |
| Create `app/routes/upload.py`, `app/routes/jobs.py` | Upload endpoint (Invariant 8 + dedup), queue status/retry/cancel API |
| Create `app/routes/books.py` | "Add a JLBC book": TOC discovery → bulk enqueue (Task 15) |
| Modify `app/routes/fiscal_notes.py` | Live directory source (mtime-checked) with committed snapshot fallback; drop `lru_cache` |
| Create `webapp/src/pages/Upload.tsx` (+ `api.ts` additions, `app.css` `page-upload` block) | Drop zone, Invariant 8 notice + required checkbox, metadata form, queue list w/ progress + retry/cancel |
| Modify `webapp/src/pages/FiscalNotes.tsx` (rail block only) | Wire the reserved `.fside-search.is-disabled` input to `api.search(q, {}, "fiscal_notes")` |
| Create `eval/fiscal_note_queries.yaml` + modify `eval/run_eval.py` | ~12 coordinator-triage queries; `--corpus` flag |
| Tests | `tests/test_ingest_lock.py`, `test_ingest_jobs.py`, `test_ingest_worker.py`, `test_lance_writer.py`, `test_store_backup.py`, `test_agency_catalog.py`, `test_stamper_multi_agency.py`, `test_upload_route.py`, `test_jobs_route.py`, `test_fiscal_notes_live.py`, `test_fiscal_refresh.py`, webapp `Upload.test.tsx` + FiscalNotes rail tests |

API contracts (frozen for Plans 4/5):

```
POST /api/upload  (multipart/form-data)
  fields: file, corpus ("budget"|"fiscal_notes"), publisher, doc_type,
          fiscal_year: int, title: str, is_public_record: "true" (REQUIRED true)
  -> 202 { "job_id": str, "doc_id": str }
  -> 400 missing/false is_public_record ("Only public-record documents may be uploaded…")
  -> 409 duplicate: { "detail": "already in corpus", "existing_doc_id", "added_at", "added_by" }

GET  /api/jobs                 -> { "jobs": [JobView] }   # newest first, all machines' jobs
POST /api/jobs/{id}/retry      -> 200 {job} | 409 not-failed
POST /api/jobs/{id}/cancel     -> 200 {job} | 409 terminal
JobView = { job_id, doc_id, title, corpus, state:
            "queued"|"extracting"|"chunking"|"embedding"|"writing"|"live"|"failed"|"cancelled",
            pct: int, stage_detail: str,      # "page 34/210"
            error: str|null, machine: str, user: str,
            created_at, updated_at }

GET /api/fiscal-notes          -> unchanged contract; data source becomes
                                  <data_dir>/fiscal-notes-directory.json when present,
                                  committed snapshot otherwise
POST /api/fiscal-notes/refresh -> 202 { "job_id" } (scraper+downloads run as a queue job)
```

---

## Reality expectations to encode in UI copy (do not soften)

MinerU on an i5-1245U runs ~1–3 min/page. The upload page's processing note says: *"Small documents are searchable within the hour. Large books (100+ pages) process overnight — leave the app running; progress survives restarts."* Jobs journal per-stage so a sleep/reboot resumes at the last completed stage, re-extracting only unfinished page ranges.

---

### Task 1: Agency catalog module

**Files:** Create `chunking/agency_catalog.py`; Test `tests/test_agency_catalog.py`; Modify `chunking/entity_stamper.py` (consume loader — no behavior change).

- [ ] Step 1 — failing tests:

```python
# tests/test_agency_catalog.py
from chunking.agency_catalog import id_to_name, load_agency_catalog


def test_loads_157_agencies_with_ids():
    cat = load_agency_catalog()
    assert len(cat) >= 150
    entry = cat["agency:ahcccs"]
    assert "AHCCCS" in entry.canonical_name or "Health Care" in entry.canonical_name
    assert entry.slug == "ahcccs"


def test_id_to_name_map():
    names = id_to_name()
    assert names["agency:ahcccs"]
    assert all(k.startswith("agency:") for k in names)
```

- [ ] Step 2 — run, expect ModuleNotFoundError. Step 3 — implement: `AgencyEntry` frozen dataclass `{canonical_id, canonical_name, slug, name_variants: list[str]}`; `load_agency_catalog(path=samples/entity-catalog.yaml)` parsing the `agencies:` list (names_observed_jlbc keys become name_variants), lru_cached; `id_to_name()` derived map. Then edit `EntityStamper.__init__` to build `_slug_to_id`/`_name_to_id` from the loader instead of inline YAML parsing (assert existing stamper tests stay green — that's the no-behavior-change proof). Step 4 — `uv run pytest tests/test_agency_catalog.py tests/test_entity_stamper.py -v` → PASS. Step 5 — commit `feat(chunking): standalone agency catalog module (id→name for UI/tools)`.

---

### Task 2: DocMeta relocation (mechanical)

**Files:** Modify `chunking/types.py`, `chunking/builders/table_chunk.py`.

- [ ] Move the `DocMeta` dataclass into `chunking/types.py`; leave `from chunking.types import DocMeta` re-export in `table_chunk.py` so the three existing import sites keep working. Run `uv run pytest tests/ -m "not slow" -q` → green. Commit `refactor(chunking): DocMeta lives in chunking.types`.

---

### Task 3: SMB-safe ingest lock

**Files:** Create `ingest/lock.py`; Test `tests/test_ingest_lock.py`.

- [ ] Step 1 — failing tests:

```python
# tests/test_ingest_lock.py
import json
import time

import pytest

from ingest.lock import IngestLock, LockHeldError


def test_acquire_creates_lockfile_with_owner(tmp_path):
    with IngestLock(root=tmp_path) as lock:
        data = json.loads((tmp_path / "ingest.lock").read_text())
        assert data["machine"] and data["pid"] and data["heartbeat_at"]
    assert not (tmp_path / "ingest.lock").exists()  # released


def test_second_acquire_raises_with_owner_name(tmp_path):
    with IngestLock(root=tmp_path):
        with pytest.raises(LockHeldError) as e:
            IngestLock(root=tmp_path).acquire()
        assert "held by" in str(e.value)


def test_stale_lock_is_stolen(tmp_path):
    stale = {"machine": "DEAD-PC", "pid": 1, "user": "x",
             "heartbeat_at": time.time() - 999}
    (tmp_path / "ingest.lock").write_text(json.dumps(stale))
    with IngestLock(root=tmp_path, stale_after_s=120) as lock:
        assert lock.held


def test_heartbeat_refreshes_timestamp(tmp_path):
    with IngestLock(root=tmp_path) as lock:
        t1 = json.loads((tmp_path / "ingest.lock").read_text())["heartbeat_at"]
        lock.heartbeat()
        t2 = json.loads((tmp_path / "ingest.lock").read_text())["heartbeat_at"]
        assert t2 >= t1
```

- [ ] Step 2 — run, expect failure. Step 3 — implement: `IngestLock(root: Path | None = None, stale_after_s: int = 120)`; acquisition via `open(path, "x")` (atomic-create on SMB — the one primitive Windows shares honor reliably); payload `{machine: socket.gethostname(), pid, user: getpass.getuser(), heartbeat_at: time.time()}`; on `FileExistsError` read payload → stale (heartbeat older than `stale_after_s`) means delete + retry once, else `LockHeldError("ingest lock held by {machine}/{user}")`; `heartbeat()` rewrites payload in place (worker calls it between stages — spec S6's heartbeat expiry); context-manager release deletes; release tolerates already-gone. Step 4 — PASS. Step 5 — commit `feat(ingest): SMB-safe single-writer lock with heartbeat stale-steal (S6)`.

---

### Task 4: Store additions — `delete_doc` + S17 backups

**Files:** Modify `store/chunk_store.py`; Create `store/backup.py`; Tests `tests/test_chunk_store.py` (extend), `tests/test_store_backup.py`.

- [ ] Step 1 — failing tests (extend existing chunk-store suite with the same `_row` helper):

```python
def test_delete_doc_removes_only_that_doc(store):
    store.delete_doc("budget_chunks", "doc-1")
    assert store.count("budget_chunks") == 0  # fixture rows all doc-1

# tests/test_store_backup.py
from store.backup import list_snapshots, restore, snapshot


def test_snapshot_creates_zip_and_rotates(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "lancedb").mkdir(parents=True)
    (tmp_path / "lancedb" / "x.txt").write_text("corpus")
    for _ in range(7):
        snapshot()
    assert len(list_snapshots()) == 5  # rotation cap


def test_restore_round_trip(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    lancedb = tmp_path / "lancedb"
    lancedb.mkdir(parents=True)
    (lancedb / "x.txt").write_text("good")
    name = snapshot()
    (lancedb / "x.txt").write_text("corrupted")
    restore(name)
    assert (lancedb / "x.txt").read_text() == "good"
```

- [ ] Step 2 — fail. Step 3 — implement. `ChunkStore.delete_doc(name, doc_id)`: `tbl.delete(f"doc_id = {sql_str(doc_id)!s}")` via the existing `sql_str` escaper (mirror `upsert_chunks`' open-or-create handling; no-op when table absent). `store/backup.py`: `snapshot() -> str` zips `<data_dir>/lancedb` to `<data_dir>/backups/lancedb-<UTC-compact>.zip` (`zipfile`, deflate), prunes to newest 5; `list_snapshots() -> list[str]` newest first; `restore(name)` extracts over a cleared `lancedb/` — caller holds the ingest lock (docstring states it; the admin route in Plan 5 enforces it). Timestamps via `datetime.now(timezone.utc)`. Step 4 — PASS. Step 5 — commit `feat(store): delete_doc + S17 snapshot/restore rotation`.

---

### Task 5: Lance writer (Chunk → row, atomic-ish doc write, documents.json merge, titles)

**Files:** Create `ingest/lance_writer.py`; Test `tests/test_lance_writer.py`.

- [ ] Step 1 — failing tests:

```python
# tests/test_lance_writer.py
import json

from chunking.types import Chunk, ChunkProvenance, DocMeta
from ingest.lance_writer import build_title, chunk_to_lance_row, write_doc
from store.chunk_store import ChunkStore


def _chunk(i: int) -> Chunk:
    return Chunk(
        chunk_id=f"gov-test-fy2027-{i:04d}", doc_id="gov-test-fy2027",
        text=f"appropriation text {i}", section_path=["A"], is_table=False,
        table_html=None,
        provenance=ChunkProvenance(page=i + 1, bbox=[1, 2, 3, 4],
                                   paragraph_id=None, table_cell_id=None),
        agency_canonical_id="agency:ahcccs", fund_canonical_id=None,
        fiscal_year=2027, doc_type="governors-budget", publisher="governor",
        token_count=4, alias_chain=[], fund_mentions=[],
    )


def test_row_mapping_matches_schema():
    row = chunk_to_lance_row(_chunk(0), vector=[0.0] * 8)
    assert row["agency_canonical_ids"] == ["agency:ahcccs"]   # scalar → array
    assert json.loads(row["source_anchor"])["page"] == 1
    assert row["bbox"] == [1.0, 2.0, 3.0, 4.0]
    assert "alias_chain" not in row


def test_write_doc_is_idempotent_and_fts_searchable(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    store = ChunkStore(root=tmp_path, dim=8)
    chunks = [_chunk(0), _chunk(1)]
    vectors = [[1.0] + [0.0] * 7, [0.0, 1.0] + [0.0] * 6]
    meta = DocMeta(doc_id="gov-test-fy2027", publisher="governor",
                   doc_type="governors-budget", fiscal_year=2027)
    write_doc(store, "budget_chunks", chunks, vectors, meta,
              title="FY 2027 Test Budget", source_sha256="ab" * 32,
              source_blob_path="pdfs/ab/abab.pdf", source_url=None,
              source_format="pdf", uploaded_by="TESTUSER")
    write_doc(store, "budget_chunks", chunks, vectors, meta,
              title="FY 2027 Test Budget", source_sha256="ab" * 32,
              source_blob_path="pdfs/ab/abab.pdf", source_url=None,
              source_format="pdf", uploaded_by="TESTUSER")  # re-ingest
    assert store.count("budget_chunks") == 2                 # no duplicates
    assert store.fts_search("budget_chunks", "appropriation", top_k=5)
    docs = json.loads((tmp_path / "documents.json").read_text())
    assert docs["gov-test-fy2027"]["title"] == "FY 2027 Test Budget"
    assert docs["gov-test-fy2027"]["source_sha256"] == "ab" * 32


def test_build_title():
    assert build_title(publisher="jlbc", doc_type="baseline-per-agency",
                       fiscal_year=2027, user_title="",
                       agency_name="AHCCCS") == "FY 2027 Baseline — AHCCCS"
    assert build_title(publisher="agao", doc_type="afr", fiscal_year=2025,
                       user_title="", agency_name=None) \
        == "FY 2025 Annual Financial Report"
    assert build_title(publisher="jlbc", doc_type="afr", fiscal_year=2025,
                       user_title="My Custom Name", agency_name=None) \
        == "My Custom Name"
```

- [ ] Step 2 — fail. Step 3 — implement:
  - `chunk_to_lance_row(chunk: Chunk, *, vector: list[float]) -> dict` — the three review-pinned conversions: `provenance.page/bbox` flatten (floats), `source_anchor = json.dumps({k: v for k in (page, paragraph_id, table_cell_id) if v is not None})`, scalar `agency_canonical_id` → `agency_canonical_ids` list (empty list when None — non-nullable column), `fund_mentions or []`, `section_path or []`, drop `alias_chain`.
  - `write_doc(store, table, chunks, vectors, doc_meta, *, title, source_sha256, source_blob_path, source_url, source_format, uploaded_by)` — sequence: `store.ensure_tables()` → `store.delete_doc(table, doc_id)` → `store.upsert_chunks(table, rows)` → `store.build_fts_index(table)` → `store.optimize(table)` → documents.json merge. Merge = read current sidecar (empty dict if absent), update this doc's entry (the migration's `DOCS_FIELDS` plus new `source_sha256`, `ingested_at`, `uploaded_by`), write via the migration script's `write_documents_sidecar` (import it — it's already atomic). Caller holds the ingest lock; docstring says so.
  - `build_title(*, publisher, doc_type, fiscal_year, user_title, agency_name) -> str` — user-supplied title wins verbatim; else pattern table (`baseline-per-agency` → `FY {y} Baseline — {agency}`, `approps-per-agency` → `FY {y} Appropriations Report — {agency}`, `afr` → `FY {y} Annual Financial Report`, `governors-budget` → `FY {y} Executive Budget`, `budget-bill` → `FY {y} Budget Bill`, fiscal-note doc_type → `Fiscal Note — {user context}`; fallback: humanized slug). This is what retires the "GOVERNOR FY2027 fy2027" titles for new ingests.
- [ ] Step 4 — PASS. Step 5 — commit `feat(ingest): Chunk→LanceDB writer with idempotent per-doc replace + real titles`.

---

### Task 6: MinerU runner adaptation

**Files:** Create `ingest/mineru_runner.py` (wraps, does not modify, `scripts/run_mineru.py` internals); Test `tests/test_mineru_runner.py`.

- [ ] Step 1 — failing tests (fake executable — a tiny Python script standing in for mineru that writes the expected `_content_list.json` layout and prints page progress lines):

```python
# tests/test_mineru_runner.py
from ingest.mineru_runner import MineruRunner, resolve_mineru_exe


def test_resolve_exe_prefers_env(monkeypatch, tmp_path):
    fake = tmp_path / "mineru.exe"
    fake.write_text("")
    monkeypatch.setenv("JLBC_MINERU_EXE", str(fake))
    assert resolve_mineru_exe() == fake


def test_runner_reports_progress_and_writes_pages(tmp_path, fake_mineru):
    seen = []
    runner = MineruRunner(exe=fake_mineru)
    runner.run(pdf=..., out=tmp_path / "out", pages=[1, 2, 3],
               on_progress=lambda done, total: seen.append((done, total)))
    assert (tmp_path / "out" / "page-1.json").exists()
    assert seen and seen[-1] == (3, 3)


def test_cancel_kills_subprocess(tmp_path, slow_fake_mineru):
    runner = MineruRunner(exe=slow_fake_mineru)
    runner.cancel()          # set before run → immediate cooperative exit
    with pytest.raises(MineruCancelled):
        runner.run(pdf=..., out=tmp_path / "out", pages=[1])
```

(Write the `fake_mineru` fixtures as executable scripts in the test module via `tmp_path`; the exact content_list layout to emulate is in `scripts/run_mineru.py::_read_mineru_output` — one method subdir, `<stem>_content_list.json` + `<stem>.md`.)

- [ ] Step 2 — fail. Step 3 — implement `MineruRunner`:
  - `resolve_mineru_exe()`: `JLBC_MINERU_EXE` env → `shutil.which("mineru")` → fall back to `["uv", "run", "mineru"]` dev-mode invocation (spec S7's bundled install sets the env var; dev machines keep working).
  - `run(pdf, out, pages, *, on_progress, timeout_s=7200)`: reuse `scripts/run_mineru.py`'s `_contiguous_ranges` + `_read_mineru_output` + page-reindex math by importing them (they're module-level); replace `subprocess.run` with `subprocess.Popen` reading stdout lines for MinerU's per-page log lines → `on_progress(done, total)`; enforce timeout; check `self._cancelled` between ranges and kill the child on cancel (`MineruCancelled`). Pin `MINERU_MODEL_SOURCE=local` + `MINERU_TOOLS_CONFIG_JSON`/model-cache env to `<install>/models` when `JLBC_MINERU_MODELS` is set (S7 no-phone-home; dev machines without it keep default cache).
  - One invocation per contiguous range exactly as today — per-range invocation is also the resume granularity (job journal records completed ranges).
- [ ] Step 4 — PASS. Step 5 — commit `feat(ingest): MinerU runner with progress, timeout, cancel, pinned model source`.

---

### Task 7: Job records + journal

**Files:** Create `ingest/jobs.py`; Test `tests/test_ingest_jobs.py`.

- [ ] Step 1 — failing tests covering: `JobRecord` create → `save(job)` writes `<data_dir>/jobs/<job_id>.json` atomically (tmp+replace); `load_all()` returns newest-first across machines; state transitions guarded (`queued→extracting→chunking→embedding→writing→live`, any→`failed` with error, non-terminal→`cancelled`); `resumable()` returns jobs in non-terminal states owned by THIS machine (machine field match) for startup resume; `mark_stage(job, stage, pct, detail)` bumps `updated_at`; job_id format `<UTCcompact>-<sha8>`.
- [ ] Step 2 — fail. Step 3 — implement: frozen-ish dataclass with `to_json/from_json`, fields exactly the `JobView` contract plus `source_path`, `corpus`, `publisher`, `doc_type`, `fiscal_year`, `source_sha256`, `completed_ranges: list[list[int]]` (MinerU resume), `user_title`. `state` transitions via `advance(job, new_state)` raising on illegal jumps. All writes atomic. Step 4 — PASS. Step 5 — commit `feat(ingest): persistent job journal on the shared data dir`.

---

### Task 8: The worker

**Files:** Create `ingest/worker.py`; Test `tests/test_ingest_worker.py` (uses the dispatcher's dry-run extractor + 8-dim fake embedder — no models).

- [ ] Step 1 — failing tests: `run_job(job)` on a tiny DOCX fixture drives all stages and ends `live` with chunks searchable; a job failed at `embedding` re-runs from `embedding` not from `extracting` (journal); `cancel` between stages → `cancelled`, no partial rows visible (write phase never started); `IngestWorker.start(app_state)` background thread picks up `queued` jobs and `resumable()` jobs at startup; exceptions land in `job.error` verbatim and never kill the thread; the write phase acquires `IngestLock` and calls `store/backup.snapshot()` first (assert snapshot exists after run).
- [ ] Step 2 — fail. Step 3 — implement the stage pipeline, each stage a function taking `(job, ctx)`:
  1. `extracting`: `pick_extractor`/`extract` via `ingest.dispatcher` for DOCX/ODL; MinerU docs through `MineruRunner` with `on_progress` → `mark_stage(job, "extracting", pct, f"page {done}/{total}")`, recording `completed_ranges`. Output dir: `<data_dir>/extractor-output/<doc_id>/` (share-side so any machine can resume).
  2. `chunking`: `chunk_doc(extractor_output_path=…, doc_meta=DocMeta(...), stamper=EntityStamper.from_default_paths())`.
  3. `embedding`: `LocalEmbedder().embed_batch([c.text for c in chunks], input_type="document")` in batches of 64 with per-batch `mark_stage` pct. Construct embedder once per worker (module singleton via `retrieval.pipeline._get_embedder()` — same process, no double model load).
  4. `writing`: `IngestLock()` → `snapshot()` → `write_doc(...)` (Task 5) → copy the source file to `<data_dir>/pdfs/<sha2>/<sha256>.<ext>` if not already there → release.
  5. `live`.
  - Worker: daemon thread started from `create_app` (Plan-3 route module calls `worker.ensure_started(app)`), polling `<data_dir>/jobs` every 5s for `queued` owned-by-any-machine jobs but **claiming** by writing `machine` under the ingest lock (one worker across the office); heartbeat during long stages.
- [ ] Step 4 — PASS. Step 5 — commit `feat(ingest): background worker — extract→chunk→embed→write with resume, lock, snapshot`.

---

### Task 9: D2 multi-agency stamping

**Files:** Modify `chunking/entity_stamper.py`; Test `tests/test_stamper_multi_agency.py`.

- [ ] Step 1 — failing test: a table chunk whose text names three known agencies (use catalog names) gets `agency_canonical_ids` (via the writer) containing all three, primary first; narrative chunks keep single-resolution behavior; existing stamper tests untouched.
- [ ] Step 2 — fail. Step 3 — implement `EntityStamper.resolve_all(chunk) -> list[str]`: for `is_table` chunks, run the rule-3 name scan across the whole text (not just first 10 lines) collecting every distinct match above threshold, primary = existing `_resolve()` result placed first. `chunk_to_lance_row` (Task 5) grows an optional `agency_ids: list[str] | None` parameter; the worker passes `stamper.resolve_all(chunk)` for tables. `Chunk` model unchanged (D2 lands at the row layer, matching how the old loader promoted scalar→array).
- [ ] Step 4 — PASS. Step 5 — commit `feat(chunking): D2 multi-agency stamping for table chunks`.

---

### Task 10: Upload + jobs API routes

**Files:** Create `app/routes/upload.py`, `app/routes/jobs.py`; Modify `app/main.py` (two `include_router` lines above the catch-all), `ingest/cache.py` (extension fix, atomic manifest); Tests `tests/test_upload_route.py`, `tests/test_jobs_route.py`.

- [ ] Step 1 — failing tests: multipart upload happy path → 202 with job_id + doc_id, file landed content-addressed under `<data_dir>/uploads/`, job file exists `queued`; `is_public_record` missing or `"false"` → 400 with the Invariant 8 message; same-content re-upload → 409 with `existing_doc_id`/`added_at`/`added_by` (dedup source: `documents.json` entries' `source_sha256` + pending jobs); bad `doc_type`/`fiscal_year` → 422; `GET /api/jobs` lists newest-first; retry flips `failed→queued`; cancel on `live` → 409. Inject a no-op worker (`create_app(ingest_worker=...)` seam mirroring the `provider=` pattern) so tests never start threads.
- [ ] Step 2 — fail. Step 3 — implement per the frozen contract above. `doc_type` accepted values = the retrieve-tool enum plus `fiscal-note`; `make_doc_id(publisher, doc_type, fiscal_year, filename=…)` names uploads. Register the fiscal-note doc_type in `ingest/dispatcher.EXTRACTOR_REGISTRY` as `("fiscal-note", "pdf") → MinerUExtractor`. Fix `DownloadCache._relative_for_sha` to honor the real extension and wrap manifest writes tmp+replace.
- [ ] Step 4 — PASS. Step 5 — commit `feat(app): upload + jobs API — Invariant 8 gate, content-hash dedup, queue control`.

---

### Task 11: Upload page (webapp)

**Files:** Create `webapp/src/pages/Upload.tsx`; Modify `App.tsx` (route `/upload`), `Header.tsx` (`NAV_ITEMS` + "Upload"), `api.ts` (upload/jobs functions + interfaces), `app.css` (`/* ===== page-upload ===== */` block); Test `webapp/src/pages/Upload.test.tsx`.

- [ ] Step 1 — failing vitest specs: renders the Invariant 8 notice text (assert the phrase "public record" and the document-type list) with a required checkbox gating the submit button; drop/select file → metadata form appears with publisher/doc_type/FY/title fields pre-filled from filename heuristics (e.g. `FY2026` → 2026); submit posts multipart via `api.uploadDocument` and shows the new job in the queue list; queue list polls `api.jobs()` (fake timers), renders per-job progress bar + `stage_detail`, retry button on failed, cancel on running; 409 duplicate response renders the "already in corpus (added … by …)" message with a re-process affordance.
- [ ] Step 2 — fail. Step 3 — implement following the house conventions: `<main className="page-upload" data-testid="upload">`, phase union state, `role="status"` live region, mockup primitives (`.card`, `.fchip`, `.allbtn`), notice as a `.card` with the S12 look — no new tokens. Processing-time expectation copy from "Reality expectations" above. Step 4 — vitest PASS + manual `npm run build`. Step 5 — commit `feat(webapp): upload page — Invariant 8 notice, metadata form, live queue`.

---

### Task 12: Fiscal-note corpus — refresh pipeline + live directory + rail search

**Files:** Create `ingest/fiscal_notes_refresh.py`; Modify `app/routes/fiscal_notes.py`, `webapp/src/pages/FiscalNotes.tsx` (rail block only), `api.ts`; Tests `tests/test_fiscal_refresh.py`, `tests/test_fiscal_notes_live.py`, FiscalNotes rail vitest.

- [ ] Step 1 — failing tests: `fetch_session(year, fetcher)` hits `https://www.azjlbc.gov/fiscal-notes/?Year={year}` and parses via the snapshot exporter's `parse_session_html` (inject fixture HTML from `webapp/reference/fiscal-notes-build/live/2026.html`); `diff_against_directory(parsed, directory)` returns only new `(bill, fiscal_note_url)` rows; `run_refresh(enqueue, fetcher)` writes `<data_dir>/fiscal-notes-directory.json` (atomic; full sessions structure, exporter's shape) and enqueues one `fiscal-note` job per new PDF (doc_id `legislature-fiscal-note-fy{year}-{billslug}-{n}`); scraper failure → directory untouched, error surfaced ("loudly but harmlessly", S10). Route tests: with a directory file present, `GET /api/fiscal-notes` serves it (mtime-checked reload, no `lru_cache`); absent → committed snapshot; contract shape unchanged. Rail test: typing in the (now-enabled) rail search calls `api.search(q, {}, "fiscal_notes")` and renders chunk snippets; while `fiscal_note_chunks` is empty the input stays disabled with the existing hint (drive via a `corpusReady` prop fetched from a lightweight `GET /api/fiscal-notes/status` → `{chunks: n}`).
- [ ] Step 2 — fail. Step 3 — implement. Refresh runs as a queue job type (`POST /api/fiscal-notes/refresh` → 202) so it serializes under the same lock/backup machinery; PDF downloads go through the fixed `DownloadCache` into `<data_dir>/pdfs/`. Current-year default: refresh fetches the newest 2 session years (older sessions never change). Step 4 — PASS. Step 5 — commit `feat(fiscal-notes): live refresh pipeline + corpus-backed directory + rail semantic search`.

---

### Task 13: Fiscal-note eval set

**Files:** Create `eval/fiscal_note_queries.yaml`; Modify `eval/run_eval.py` (`--corpus` flag → `RetrievalRequest(corpus=…)`, results filename prefix); Test `tests/test_eval_fiscal_corpus.py`.

- [ ] Step 1 — write ~12 coordinator-triage-shaped queries against real ingested notes (do this AFTER Task 12's first real refresh populates the corpus; ground truth = chunk_id + anchor_text, same schema as `queries.yaml`). Queries shaped like the triage workflow: "prior fiscal notes about community college expenditure limits", "notes estimating AHCCCS provider rate costs", etc.
- [ ] Step 2 — `uv run python -m eval.run_eval --corpus fiscal_notes` runs green and writes results; commit the baseline numbers. No hard gate (this corpus has no history) — the numbers ARE the baseline. Commit `eval: fiscal-note corpus baseline (coordinator-triage query set)`.

---

### Task 14: Post-ingest validation gate

**Files:** Create `ingest/validate.py` (port of `db/validate.py` checks onto `ChunkStore.scan`); Test `tests/test_ingest_validate.py`.

- [ ] Port the MANIFEST.md definition-of-done checks: ≥90% agency-stamped for per-agency doc_types, provenance present on every chunk, non-empty text, token_count sanity. `validate_doc(store, table, doc_id) -> list[str]` (empty = pass); worker runs it at the end of `writing` and attaches warnings to the job (visible in JobView `stage_detail`, non-fatal). Tests + commit `feat(ingest): post-ingest validation gate (ports db/validate checks)`.

---

### Task 15: "Add a JLBC book" — bulk ingest from the linked TOC

**Files:** Create `app/routes/books.py`; Modify `webapp/src/pages/Upload.tsx` (second panel), `api.ts`; Tests `tests/test_books_route.py`, Upload.test.tsx additions.

- [ ] Step 1 — failing tests: `POST /api/books/discover {book: "baseline"|"approps", fiscal_year}` → derives the index URL via `ingest/url_conventions.py`, runs `ingest.discovery.discover(...)` (injected fake walker in tests using `data/discovery-cache.yaml` shapes), returns `{documents: [{slug, name, url, doc_type}], count}` without downloading anything; `POST /api/books/ingest {book, fiscal_year}` → 202, enqueues one job per discovered document (doc_ids via `make_doc_id`, dedup rules from Task 10 apply — already-ingested docs are skipped with counts reported `{queued: n, skipped_existing: m}`); discovery failure (site changed / URL 404) → honest 502-style detail, nothing queued. UI: an "Add a JLBC book" panel on the Upload page — book-type + FY selectors → *Check availability* renders "Found 112 documents for FY 2028 Baseline" with the list collapsed → *Add all to queue* → queue list shows them; the overnight-expectation copy repeats here.
- [ ] Step 2 — fail. Step 3 — implement (downloads happen inside each job via `DownloadCache.fetch(url)`, not at discovery time; the Invariant 8 checkbox is replaced by static notice text for this flow — JLBC-published documents are public record by definition, state that in the panel copy). Step 4 — PASS. Step 5 — commit `feat(ingest): Add-a-JLBC-book — TOC discovery to bulk queue (annual-cadence handoff path)`.

---

### Task 16: End-to-end + STATUS + merge

- [ ] E2E on the dev machine: upload a small real PDF through the GUI → job runs to `live` → doc searchable on the Search page with its real title; run one live fiscal-note refresh for 2026 → directory updates, a few note PDFs ingest, rail search returns results; `bash setup.sh --verify` + `cd webapp && npx vitest run` green; run the budget eval (`uv run python -m eval.run_eval`) to prove no retrieval regression (CLAUDE.md rule — ingest changes touch the corpus path) and commit results.
- [ ] STATUS.md: Plan 3 section (what shipped, corpus counts incl. fiscal_note_chunks, known follow-ups); note Postgres/Docker now needed for NOTHING (migration-era only).
- [ ] Merge per superpowers:finishing-a-development-branch (`--no-ff`, push, remove worktree). Coordinate: if Plan 4 merged first, rebase over it — expected conflicts only in the shared append points listed in the parallel contract.

---

## Self-review notes

- Spec coverage: S6 (Task 3), S10 (Task 12), S17 (Task 4), Invariant 8 (Tasks 10–11), dup detection (Task 10), PDF copy to share (Task 8 write phase), real titles (Task 5), fiscal-note eval (Task 13), D2 (Task 9), agency catalog follow-up (Task 1), validation gate (Task 14), annual-cadence book ingest via TOC discovery (Task 15 — added 2026-07-30 after Destin asked how staff add a new year's Baseline; the discovery machinery existed but had no GUI path). MinerU weight bundling itself is Plan 5 (packaging) — this plan only honors `JLBC_MINERU_MODELS` when set.
- Deliberate scope cuts: no tiered fast-then-refine extraction (user chose background-queue-is-fine); refresh limited to newest 2 session years per run (older sessions are immutable); `fiscal-notes-directory.json` full-rewrite (tiny file, atomic).
- Type-consistency check: `write_doc` signature matches worker call; `JobView` fields match jobs.py dataclass; `resolve_all` return feeds `chunk_to_lance_row(agency_ids=…)`.
