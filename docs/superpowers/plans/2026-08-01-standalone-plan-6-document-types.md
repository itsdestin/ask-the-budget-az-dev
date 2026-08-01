# Standalone Plan 6: Document Types — Registry, Honest Routing, Ingest Gates, Guided Upload

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the corpus *extensible by a non-technical office*. Today the system knows exactly 13 document types, the set is closed, and anything outside it raises — so an office with no maintainer cannot ingest a report nobody anticipated, and 85 of the 90 documents already researched for the next backfill wave cannot be ingested at all. This plan makes the type table declarative data, routes on what a file *is* rather than what someone clicked, adds a first-class "Other" path that is honest about its weaker provenance, turns post-ingest validation from two advisory checks into real per-type gates, and replaces the upload form's dropdown of internal slugs with a guided flow.

**Architecture:** One declarative registry (`data/document-types.yaml` + `ingest/doc_types.py`) becomes the single source of truth consumed by the dispatcher, the upload route, the validator, and the webapp via `GET /api/document-types`. A new `ingest/detect.py` inspects files. `ingest/validate.py` grows per-type expectations. `app/routes/upload.py` gains an inspect endpoint. `webapp/src/pages/Upload.tsx` becomes a four-step flow. `data/jlbc-book-catalog.json` generalises into a document catalog seeded from the website mockup's verified 5,854-row index.

**Tech Stack:** existing (FastAPI, React/Vite, LanceDB, PyMuPDF, MinerU, python-docx). PyYAML is already a dependency. No new runtime dependencies.

**Spec:** `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — **S24** (declarative registry carrying analyst instruction), **S25** (JLBC books redirect, never a single-file upload), **S26** (detect-don't-declare routing + honest general fallback), **S27** (per-type ingest gates), **S28** (one catalog for every publisher), **S29** (guided upload flow with first-class "Other"). Invariant 8 throughout.

**Work in a worktree:** `git worktree add ~/atb-worktrees/plan6 -b plan6 origin/master`

---

## ⛔ Do not start until the Z13 book backfill has finished

Tracks 2–4 modify the live ingest path — `ingest/dispatcher.py`, `ingest/validate.py`, the worker's write phase. The Z13 backfill is running against exactly those modules. Editing files does not disturb a running process, but **merging this plan and then restarting the server mid-backfill would swap the ingest path underneath a half-finished corpus**, and the S27 gate thresholds in Track 3 must be calibrated against a *finished* corpus or they are guesses.

Track 1 (the registry) is pure refactor with no behaviour change and is safe to build early. Everything else waits for Phase E.

---

## Ground truth (READ FIRST — these are binding)

Established by reading the code on 2026-07-31, not recalled.

1. **`EXTRACTOR_REGISTRY` in `ingest/dispatcher.py` is a `dict[tuple[str, str], type]`** keyed on `(doc_type, source_format)` — 13 entries, 12 PDF + `("budget-bill", "docx")`. `pick_extractor` **raises `ValueError`** on a miss. There is no fallback path today.
2. **`app/routes/upload.py`'s `ACCEPTED_DOC_TYPES` is DERIVED** (`frozenset(dt for dt, _fmt in EXTRACTOR_REGISTRY)`), not a hand-maintained copy. Do not create a third list — repoint this at the registry loader.
3. **`webapp/src/pages/Upload.tsx`'s `DOC_TYPES` IS hand-typed** and, as of 2026-07-31, exactly in sync with the registry (verified by diff — no live bug, only drift risk). **Delete it** in favour of `GET /api/document-types`; do not "keep it in sync".
4. **Chunking does NOT dispatch on `doc_type`.** `chunking/builder.py::chunk_doc` dispatches on `doc_meta.extractor` through `_READER_REGISTRY` (`mineru` / `opendataloader` / `python-docx`) and then runs tables-then-narrative for PDFs or sections for DOCX. **Adding a document type is almost never "write a chunker"** — it is declaring which extractor it routes to. This is what makes the whole plan cheap.
5. **`ingest/validate.py` is advisory BY DESIGN and its docstring explains why**: an 80%-stamped document is degraded, not wrong, and refusing it leaves the analyst with nothing. S27 does **not** reverse that. It adds gates only for *unusable* outcomes (no chunks, no text, chunks-per-page far below floor, round-trip failure) and keeps everything else advisory. Read that docstring before changing the policy.
6. **`extraction_profile` goes in `documents.json`, NOT the chunk schema.** It is a document-level fact and the sidecar already carries document-level metadata. Adding a column to `budget_chunks` would mean a schema migration over 20k+ rows on a share, for data that is identical on every chunk of a document. Do not do that.
7. **Books are stored as per-agency pages** — FY2025 Approps is 111 `approps-per-agency` + 4 `detailed-list-pdf`; FY2027 Baseline is 110 per-agency + 15 `s-pdf` + 2 `topic-pdf`. `walk_edition` produces this by walking the agency index AND the linked TOC (their children are disjoint). `single_file_url` is stored for **viewing** and is never walked for children. S25 exists because uploading it would ingest a 400-page book as one document.
8. **`make_doc_id` is family-aware as of `f85b20a`** — the old collision (baseline vs approps `detailed-list-pdf`) is fixed. Do not re-fix it.
9. **The mockup index (`webapp/reference/assets/search/index-lite.js`) is a 2026-06-16 snapshot** of 5,854 documents with `url`, `title`, `publisher`, `doc_type`, `fiscal_year`. Verified 2026-07-31: of the 90 FY2022+ documents across the four target types, **72 resolve, 18 are hard HTTP 403** (WAF bot protection, all Agency Budget Requests, unchanged by a browser user-agent). Its `doc_type` values are the **mockup's** vocabulary ("Annual Financial Report", "Agency Budget Request"), NOT the corpus's slugs — they need mapping, not copying.
10. **Agency Budget Requests exist for FY2027 only** in the harvest, across 78 separate agency websites with no shared URL convention. Earlier years are a research project, not a crawl. Do not plan a scraper for them.

---

## File structure

| File | Responsibility |
|---|---|
| Create `data/document-types.yaml` | **The registry.** One row per type: key, label, group, formats, extractor per format, publisher hint, per-agency flag, analyst guidance (`where_published`, `which_file`), optional `redirect`, validation expectations |
| Create `ingest/doc_types.py` | Loader + `DocType` dataclass; `all_types()`, `get(key)`, `extractor_for(key, fmt)`, `expectations_for(key)`. Mtime-cached like `harness/settings.py` |
| Modify `ingest/dispatcher.py` | `EXTRACTOR_REGISTRY` becomes a projection of the registry; `pick_extractor` consults detection (S26) with the declared type as a hint; unknown → general profile instead of `ValueError` |
| Create `ingest/detect.py` | `inspect_file(path)` → format, page count, PDF structure-tree presence, first-page text, sha256; `suggest_type(inspection, filename)` → ranked candidates |
| Modify `ingest/validate.py` | Per-type expectations from the registry + round-trip spot check; returns findings **and** a `blocking` flag |
| Modify `ingest/lance_writer.py` | Write `extraction_profile` + `validation` into `documents.json` (Ground truth 6) |
| Create `app/routes/doc_types.py` | `GET /api/document-types` |
| Modify `app/routes/upload.py` | `POST /api/upload/inspect`; allowlist from the registry; accept `other` |
| Create `data/document-catalog.json` + `scripts/build_document_catalog.py` | S28: seeded from the mockup index, mapped to corpus slugs, with reachability recorded |
| Modify `app/routes/books.py` → add `app/routes/catalog.py` | `GET /api/catalog/updates`, `POST /api/catalog/ingest` |
| Rewrite `webapp/src/pages/Upload.tsx` (+ `webapp/src/upload/*`) | S29 four-step flow; delete the hand-typed `DOC_TYPES` |
| Modify `webapp/src/components/ResultCard.tsx` | Show the general-profile label (S26) |
| Tests | `tests/test_doc_types.py`, `test_detect.py`, `test_dispatcher_registry.py`, `test_validate_gates.py`, `test_doc_types_route.py`, `test_upload_inspect.py`, `test_document_catalog.py`, webapp `Upload.test.tsx` (rewritten) |

---

## API contracts (frozen)

```
GET /api/document-types
  -> 200 { "types": [DocTypeCard] }         # ordered; "other" is always last
  DocTypeCard = {
    key: str,                  # corpus doc_type slug, e.g. "afr"
    label: str,                # analyst language, e.g. "Annual Financial Report"
    group: str,                # "JLBC" | "Governor" | "Agencies" | "Legislature" | "Other"
    formats: [str],            # [".pdf"] | [".docx"] — drives the picker's accept
    where_published: str,      # one line: who publishes it and where
    which_file: str,           # one line: WHICH file to grab
    redirect: { action: str, label: str, detail: str } | null,   # S25
    is_other: bool,
    order: int
  }

POST /api/upload/inspect   (multipart: file)
  -> 200 { "format": ".pdf"|".docx", "pages": int|null,
           "has_structure_tree": bool|null, "bytes": int, "sha256": str,
           "thumbnail_png": str|null,          # base64, first page, <=200 KB
           "inferred": { "title": str|null, "fiscal_year": int|null,
                         "publisher": str|null, "doc_type": str|null,
                         "confidence": "high"|"low" },
           "warnings": [str],                  # plain sentences, pre-queue
           "duplicate": { "doc_id": str, "added_at": str, "added_by": str } | null }
  -> 415 { "detail": "<plain sentence>" }      # not a PDF or DOCX

POST /api/upload   (unchanged contract; doc_type may now be "other")

GET  /api/catalog/updates?since_snapshot=1
  -> 200 { "available": [CatalogEntry], "unreachable": [CatalogEntry],
           "snapshot_date": str }
POST /api/catalog/ingest
  body: { "keys": [str] }
  -> 202 { "queued": int, "skipped_existing": int }
```

`documents.json` gains two document-level keys (Ground truth 6), both optional so existing rows stay valid:

```
"extraction_profile": "tuned" | "general",
"validation": { "findings": [str], "blocking": bool, "checked_at": str }
```

---

## Sequencing

| Track | Tasks | Depends on |
|---|---|---|
| 1 — Registry (S24) | 1–4 | nothing; **safe to build during the backfill** |
| 2 — Detection + Other (S26) | 5–7 | Track 1; **backfill must be finished** |
| 3 — Ingest gates (S27) | 8–10 | Track 1; needs a **finished corpus** to calibrate |
| 4 — Guided upload (S25/S29) | 11–13 | Tracks 1–2 |
| 5 — Catalog (S28) | 14–15 | Track 1 |
| 6 — Backlog | 16 | everything |

Tracks 4 and 5 are disjoint enough to run in two sessions once 1–3 land: Track 4 owns `webapp/src/pages/Upload.tsx` + `webapp/src/upload/`, Track 5 owns `data/document-catalog.json`, `scripts/`, `app/routes/catalog.py`.

---

## Track 1 — The registry (S24)

### Task 1: `data/document-types.yaml` + loader

**Files:** Create `data/document-types.yaml`, `ingest/doc_types.py`, `tests/test_doc_types.py`.

The registry row shape — every field exists because something downstream needs it:

```yaml
- key: budget-bill
  label: Feed Bill (General Appropriations Act)
  group: Legislature
  order: 40
  formats: [".docx"]              # S24: DOCX-ONLY, enforced at the picker
  extractors: { ".docx": python-docx }
  publisher: legislature
  per_agency: false
  where_published: "Passed by the Legislature; JLBC circulates the Word version."
  which_file: >-
    The Word (.docx) version. We deliberately do not accept the PDF — the Word
    file carries the section and paragraph structure that lets the app cite an
    exact provision, and the PDF loses it.
  expectations:
    min_chunks_per_page: 0.2
    require_page_provenance: false   # DOCX cites paragraph ids, not pages

- key: approps-report
  label: Appropriations Report (whole book)
  group: JLBC
  order: 11
  formats: [".pdf"]
  extractors: { ".pdf": mineru }
  publisher: jlbc
  per_agency: false
  redirect:                          # S25 — do not upload this
    action: add-jlbc-book
    label: "Use “Add a JLBC book” instead"
    detail: >-
      Appropriations Reports are stored as one document per agency, which is
      what makes “show me ADC’s budget” work. Adding the book through the book
      tool fetches every agency page. Uploading the single-file PDF would add
      the whole 400-page book as ONE document and agency search would get worse.

- key: other
  label: Other document
  group: Other
  order: 999
  formats: [".pdf", ".docx"]
  extractors: {}                     # decided by detection (S26)
  is_other: true
  where_published: "Anything else that belongs in the corpus."
  which_file: >-
    Any public-record budget document. It will be searchable and citable, but
    extracted with a general-purpose profile rather than one tuned to a known
    format, so its page positions may be less precise.
```

- [ ] **Step 1 — failing tests.** `tests/test_doc_types.py`:

```python
def test_registry_covers_every_shipped_extractor_route():
    """The registry must reproduce today's routing EXACTLY.

    This is the safety net for the whole refactor: Task 2 repoints the
    dispatcher at this file, so any row that disagrees with the shipped
    EXTRACTOR_REGISTRY would silently change how a document is extracted —
    and a differently-extracted document produces different chunk text,
    different chunk_ids, and a broken eval ground truth.
    """
    from ingest.dispatcher import EXTRACTOR_REGISTRY
    for (doc_type, fmt), extractor_cls in EXTRACTOR_REGISTRY.items():
        row = doc_types.get(doc_type)
        assert row is not None, f"{doc_type} missing from the registry"
        assert f".{fmt}" in row.formats
        assert row.extractors[f".{fmt}"] == _NAME_OF[extractor_cls]


def test_budget_bill_is_docx_only():
    # S24, named by Destin: the Word file is the highest-information format
    # the office holds. A PDF must not be selectable, not merely rejected.
    assert doc_types.get("budget-bill").formats == [".docx"]


def test_book_types_redirect_and_carry_no_upload_instruction():
    # S25: offering "which file?" for these at all is the bug.
    for key in ("approps-report", "baseline-book"):
        row = doc_types.get(key)
        assert row.redirect is not None
        assert row.redirect["action"] == "add-jlbc-book"


def test_other_exists_is_last_and_accepts_both_formats():
    types = doc_types.all_types()
    assert types[-1].key == "other" and types[-1].is_other
    assert set(types[-1].formats) == {".pdf", ".docx"}


def test_every_non_redirect_type_tells_the_user_which_file_to_get():
    # A dropdown entry with no guidance is what this plan exists to delete.
    for row in doc_types.all_types():
        if row.redirect is None:
            assert row.which_file.strip(), f"{row.key} has no which_file guidance"
            assert row.where_published.strip()
```

- [ ] **Step 2 — implement `ingest/doc_types.py`.** Mtime-cached load (mirror `harness/settings.py`'s `(path, mtime, size)` stamp so an edited YAML is picked up without a restart). A malformed YAML **raises** — unlike settings.json, this file is shipped and version-controlled, and silently falling back to defaults would mean the app quietly forgets how to route documents.
- [ ] **Step 3 — write the YAML** with all 13 existing types plus `other`. Analyst-language labels for every one: `s-pdf` → "Baseline — summary section", `detailed-list-pdf` → "Detailed list of fund changes", etc.
- [ ] **Step 4** — `.venv/bin/python -m pytest tests/test_doc_types.py -q`
- [ ] Commit: `feat(ingest): declarative document-type registry (S24)`

### Task 2: Repoint the dispatcher — no behaviour change

**Files:** Modify `ingest/dispatcher.py`; Create `tests/test_dispatcher_registry.py`.

- [ ] **Step 1 — a characterization test FIRST**, capturing today's behaviour before touching anything: every `(doc_type, format)` pair in the shipped registry resolves to the same extractor class, and every unknown pair still raises. Run it against unmodified `master` and confirm green — a characterization test that has never passed against the old code proves nothing.
- [ ] **Step 2 — implement.** `EXTRACTOR_REGISTRY` becomes a projection built from `doc_types`, keyed identically so every existing import keeps working. `pick_extractor` keeps its signature and its raise (S26 changes that in Task 6, deliberately as a separate commit so a routing regression is bisectable).
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_dispatcher_registry.py tests/test_dispatcher.py tests/test_driver.py -q`
- [ ] Commit: `refactor(ingest): dispatcher routes from the registry, behaviour identical`

### Task 3: Serve the registry

**Files:** Create `app/routes/doc_types.py`, `tests/test_doc_types_route.py`; Modify `app/routes/upload.py`, `app/main.py`.

- [ ] **Step 1 — failing tests:** `GET /api/document-types` returns every type ordered with `other` last; redirect types carry their redirect and no `which_file`; the upload route's allowlist now comes from the registry and **accepts `other`**; a `.pdf` uploaded as `budget-bill` is rejected with the registry's own sentence, not a generic message.
- [ ] **Step 2 — implement.** Register above the SPA catch-all (Plan 5 Ground truth 11).
- [ ] **Step 3** — pytest.
- [ ] Commit: `feat(app): GET /api/document-types; upload allowlist from the registry`

### Task 4: Delete the webapp's hand-typed list

**Files:** Modify `webapp/src/pages/Upload.tsx`, `webapp/src/api.ts`, `Upload.test.tsx`.

- [ ] **Step 1 — failing spec:** the dropdown renders from the API, and a test asserts **no hardcoded doc_type string literals remain in the page source** (grep the module in the test, or assert the option set matches the mocked API response exactly). Ground truth 3 — the point is to make drift impossible, not to fix today's alignment.
- [ ] **Step 2 — implement**, keeping the existing form working (the full S29 rewrite is Task 12).
- [ ] **Step 3** — `cd webapp && npx vitest run`
- [ ] Commit: `refactor(webapp): upload types come from the API, not a parallel list`

---

## Track 2 — Detection and the honest fallback (S26)

### Task 5: `ingest/detect.py`

**Files:** Create `ingest/detect.py`, `tests/test_detect.py`.

- [ ] **Step 1 — failing tests** against real fixtures already in the repo (`samples/raw-docx/`, and a small PDF from `data/insight-data/pdfs/`):
  - a tagged PDF reports `has_structure_tree=True`; an untagged JLBC PDF reports `False` — **this is the D4 rule the dispatcher's own docstring describes, computed instead of declared**
  - page count, byte size, and sha256 match independently-computed values
  - first-page text is returned for a text PDF and **empty for a scanned one** (that emptiness is what later warns "this looks like a scan with no text layer")
  - a `.docx` returns `pages=None` rather than a fake number — DOCX has no fixed pagination, and inventing one would make the S27 chunks-per-page gate nonsense
  - a corrupt/truncated file returns a `warnings` entry and does not raise
- [ ] **Step 2 — implement** with PyMuPDF (already a dependency) for PDFs and python-docx for DOCX. `has_structure_tree` reads the PDF catalog's `/StructTreeRoot`.
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_detect.py -q`
- [ ] Commit: `feat(ingest): file inspection — format, structure tree, pages, first-page text`

### Task 6: Route on detection; stop raising on unknown types

**Files:** Modify `ingest/dispatcher.py`, `ingest/worker.py`, `ingest/lance_writer.py`; Create `tests/test_routing_fallback.py`.

- [ ] **Step 1 — failing tests:**
  - a known type routes exactly as before **when detection agrees** (the whole existing corpus must remain reproducible)
  - a PDF declared `afr` (OpenDataLoader) but with **no structure tree** routes to MinerU, and the job records why — a mislabeled upload extracts correctly instead of producing garbage cells
  - `doc_type="other"` + PDF routes by detection and the document is written with `extraction_profile: "general"` in `documents.json`
  - an unknown type string no longer raises; it behaves as `other`
  - **`extraction_profile` is absent for every existing document and that is not an error** — readers treat missing as `"tuned"`, because 2,400 documents predate the field
- [ ] **Step 2 — implement.** Declared type is the hint; detection decides; disagreements are recorded on the job and in `documents.json`. Do **not** add a chunk column (Ground truth 6).
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_routing_fallback.py tests/test_ingest_worker.py tests/test_lance_writer.py -q`
- [ ] Commit: `feat(ingest): detection-based routing + honest general profile (S26)`

### Task 7: Make the general profile visible

**Files:** Modify `app/search_provider.py`, `webapp/src/components/ResultCard.tsx`, `webapp/src/pages/Upload.tsx` (queue rows), tests.

- [ ] **Step 1 — failing specs:** a result whose document has `extraction_profile: "general"` renders a quiet label ("added as a general document — page positions may be less precise"); a `tuned` or missing profile renders nothing; the ingest queue shows the same flag on the job row.
- [ ] **Step 2 — implement.** Quiet, not alarming: this is a provenance note, not a warning. Never use the failed-citation red — Invariants 1–3 own that colour.
- [ ] **Step 3** — vitest + pytest.
- [ ] Commit: `feat(webapp): surface the general extraction profile in results and the queue`

---

## Track 3 — Ingest gates (S27)

### Task 8: Per-type expectations

**Files:** Modify `ingest/validate.py`, `data/document-types.yaml`; Create `tests/test_validate_gates.py`.

**Read `ingest/validate.py`'s docstring before starting** (Ground truth 5). The advisory-by-default policy is deliberate and stays. What changes: expectations become per-type and registry-driven, and a small set of *unusable* outcomes become blocking.

- [ ] **Step 1 — failing tests:**
  - a 300-page document yielding 12 chunks **fails** `min_chunks_per_page` and is **blocking** — this is the "it ingested but it's useless" case that currently passes
  - a per-agency document at 17% agency stamping stays **advisory** (degraded, not unusable — the Plan 3 live run produced exactly this and the analyst is better served by a flagged document than by nothing)
  - a document with zero chunks is blocking (already true; keep it and pin it)
  - a DOCX type does **not** get page-provenance findings (`require_page_provenance: false`)
  - findings text stays plain-English — assert no jargon leaks ("chunk", "bbox", "stamp") into user-visible strings
- [ ] **Step 2 — implement.** `validate_doc` returns `(findings, blocking)`. Thresholds come from the registry so tuning a type is a data edit.
- [ ] **Step 3 — calibrate against the finished corpus**, not intuition: compute the chunks-per-page distribution across all documents by type and set each floor below the observed 5th percentile. Record the numbers in the YAML comments.
- [ ] Commit: `feat(ingest): per-type validation expectations, blocking only when unusable (S27)`

### Task 9: Round-trip spot check

**Files:** Modify `ingest/validate.py`; Create `tests/test_validate_roundtrip.py`.

- [ ] **Step 1 — failing tests:** sample up to N chunks with page provenance, open the source PDF, and confirm the chunk's leading text is findable on the page it claims; a document whose chunks systematically cite the wrong page **fails blocking**; a scanned PDF with no text layer produces the "no extractable text" finding rather than a false page-mismatch; the check is skipped (not failed) for DOCX and for documents whose source file is not on disk.
- [ ] **Step 2 — implement.** Cap the sample (default 5) and the time — this runs inside the write phase, which holds the ingest lock, and Plan 5's Task 20 already flags that long writes risk cross-machine lock theft.
- [ ] **Step 3** — pytest.
- [ ] Commit: `feat(ingest): round-trip page-provenance spot check`

### Task 10: Quarantine with a reason a human can act on

**Files:** Modify `ingest/worker.py`, `webapp/src/pages/Upload.tsx`; tests.

- [ ] **Step 1 — failing tests:** a blocking finding moves the job to `failed` with the plain-English reason and **the document is not written live**; a non-blocking finding writes the document and attaches findings; retry re-runs the whole pipeline; the queue row shows the reason and a "what to do" line from the registry.
- [ ] **Step 2 — implement.**
- [ ] **Step 3** — pytest + vitest.
- [ ] Commit: `feat(ingest): quarantine unusable documents with an actionable reason`

---

## Track 4 — The guided upload flow (S25 + S29)

### Task 11: `POST /api/upload/inspect`

**Files:** Modify `app/routes/upload.py`; Create `tests/test_upload_inspect.py`.

- [ ] **Step 1 — failing tests:** returns format/pages/structure-tree/sha256 and a base64 first-page PNG under 200 KB; **infers metadata from first-page text, not the filename** — the fixture is Plan 3's real failure, a file named for AHCCCS whose first page is the Industrial Commission's, and the inferred agency must be the Industrial Commission; existing duplicate detection is reported here as data, not a 409; a non-PDF/DOCX returns 415 with a plain sentence; inspection **writes nothing** to the corpus.
- [ ] **Step 2 — implement**, reusing `ingest/detect.py` and the existing content-hash dedup.
- [ ] **Step 3** — pytest.
- [ ] Commit: `feat(app): pre-upload inspection with content-derived metadata`

### Task 12: The four-step upload flow

**Files:** Rewrite `webapp/src/pages/Upload.tsx`, create `webapp/src/upload/*`, rewrite `Upload.test.tsx`, extend the `page-upload` CSS block.

- [ ] **Step 1 — failing specs:**
  - step 1 renders type **cards** grouped by publisher with `where_published` + `which_file` from the API — no raw slugs anywhere in the DOM
  - choosing **Appropriations Report** or **Baseline Book** renders the S25 redirect and **offers no file picker at all**
  - choosing **Feed Bill** sets the picker's `accept` to `.docx` and states the rule; a `.pdf` cannot be selected
  - step 3 shows the thumbnail, the content-inferred metadata, and any warning **before** the queue button is enabled
  - a declared/detected mismatch renders the plain sentence and requires an explicit "Continue anyway"
  - a duplicate renders as a normal branch with when/who and a re-process option
  - the Invariant 8 notice and required public-record checkbox remain **always visible** — they are not a step to be clicked past
  - **"Other document" is last**, and when inspection suggests a better-fitting type the confirm step names it
- [ ] **Step 2 — implement.** Keep the shipped webapp conventions: page class + testid on `<main>`, page-scoped CSS in the labeled block, all calls through `api.ts`.
- [ ] **Step 3** — `cd webapp && npx vitest run`
- [ ] Commit: `feat(webapp): guided four-step upload flow (S29)`

### Task 13: Wire the book redirect

**Files:** Modify `webapp/src/upload/*` and the books page/route.

- [ ] The redirect action deep-links to the existing "Add a JLBC book" surface with the family and fiscal year pre-filled from whatever the user already typed. A redirect that dumps someone on a blank page is a dead end wearing a helpful hat.
- [ ] Commit: `feat(webapp): upload redirects book types into the book adder (S25)`

---

## Track 5 — One catalog (S28)

### Task 14: Build the document catalog

**Files:** Create `scripts/build_document_catalog.py`, `data/document-catalog.json`, `tests/test_document_catalog.py`.

- [ ] **Step 1 — failing tests:** the mockup's doc_type vocabulary maps to corpus slugs (`"Annual Financial Report"` → `afr`, `"State Agency Detail"` → `governors-budget`, `"Agency Budget Request"` → `agency-budget-request`, `"Budget Bill"` → `budget-bill`) and an **unmapped** mockup type is reported, never silently dropped; counts are pinned (Ground truth 9); each entry records `reachable` with the check date; entries already in `documents.json` are marked `ingested`.
- [ ] **Step 2 — implement.** Note in the file header that `budget-bill` entries from the harvest are **PDFs against a DOCX-only rule (S24)** — they are catalogued as `format_mismatch` with the reason, not quietly routed to `other`. The Word versions come from JLBC internally; the handbook says where.
- [ ] **Step 3 — add `agency-budget-request` and `state-agency-detail` to the registry** if Task 1 did not (agency requests: PDF → detection; per_agency true).
- [ ] Commit: `feat(scripts): unified document catalog seeded from the verified harvest (S28)`

### Task 15: Check for new documents

**Files:** Create `app/routes/catalog.py`, `tests/test_catalog_route.py`; webapp surface on the Upload page.

- [ ] **Step 1 — failing tests:** `GET /api/catalog/updates` returns catalogued-but-not-ingested entries, separating `unreachable` with the reason; `POST /api/catalog/ingest` queues URL-only jobs (the shape `app/routes/books.py` already uses — `source_url` set, `source_path` empty) and skips ones already present.
- [ ] **Step 2 — implement.**
- [ ] Commit: `feat(app): check-for-new-documents over the unified catalog`

---

## Track 6 — Ingest the backlog

### Task 16: The 90 FY2022+ documents

- [ ] **Step 1** — enqueue the **72 reachable** entries via Task 15. Expected: 3 AFRs, 2 executive budgets, 60 agency budget requests, and the budget bills **only if** Word versions were sourced (Task 14).
- [ ] **Step 2** — record the **18 WAF-blocked** agency requests in the catalog as `unreachable` with the reason, and list them in the handbook so a human with a browser can fetch them. Prioritise the four that matter analytically: **DES, Corrections, DEQ, Juvenile Corrections**.
- [ ] **Step 3** — run the S27 gates over the new documents and fix what they surface. AFRs are OpenDataLoader-routed and 200+ pages; **expect this step to find something**.
- [ ] **Step 4** — re-run `uv run python -m eval.run_eval` and commit the results (CLAUDE.md rule: any ingest change re-runs the eval).
- [ ] **Step 5** — update `STATUS.md` with final counts and the deferred list (pre-FY2022 books, pre-FY2027 agency requests).
- [ ] Commit: `chore(corpus): FY2022+ AFRs, executive budgets, and agency budget requests`

---

## Risks, stated plainly

1. **Task 2 is the dangerous one.** Repointing the dispatcher must be byte-for-byte behaviour-preserving; a routing change alters chunk text corpus-wide, which changes chunk_ids and invalidates the eval ground truth. That is why Task 2 ships a characterization test *proven green against old master first*, and why S26's behaviour change is a separate commit.
2. **The S27 thresholds are only as good as their calibration.** Set from intuition they will either block good documents or pass useless ones. Task 8 Step 3 requires computing the real distribution over the finished corpus; if the backfill isn't done, that step blocks.
3. **The upload rewrite touches the one screen a colleague uses to do something irreversible.** Every specced guardrail is cheaper than the failure it prevents, and the expensive failures are silent — they succeed and degrade retrieval quietly.
4. **18 documents cannot be automated.** That is a real, permanent gap in an otherwise self-feeding pipeline, and it must be written down where a human will see it rather than tracked in someone's memory.
5. **This plan does not fix the chunkers.** It routes correctly, validates honestly, and fails loudly — but a document type whose *content shape* needs a tuned chunker (a new table format, say) still needs chunking work. The registry makes that a contained addition rather than a cross-cutting one; it does not make it free.
