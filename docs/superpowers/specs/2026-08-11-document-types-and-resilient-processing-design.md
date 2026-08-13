# Document Types and Resilient Processing — Design

**Date:** 2026-08-11
**Status:** design agreed with Destin; not yet planned or implemented
**Decisions:** T1–T14

## What this supersedes

This **replaces the scope of Plan 6**
(`docs/superpowers/plans/2026-08-01-standalone-plan-6-document-types.md`) and
amends spec decisions **S24–S29** in
`docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md`.

Plan 6 kept all 13 existing document types, added `other` as a catch-all, and
treated ingest quality as a **gate that quarantines** a bad document for an
administrator to adjudicate. This design differs on three points:

1. The upload surface offers **six rows**, not fourteen. There is **no `other`
   catch-all** initially.
2. Bad extraction is **recovered automatically** by falling back to another
   extractor, not escalated to a human. A person is involved only when every
   method has failed.
3. Whether extraction worked is judged **on the output**, measured against the
   source file — not predicted from inspecting the input.

Point 3 is not a preference. It is forced by a measurement recorded below:
the two AFRs that behave differently are **indistinguishable on inspection**.

---

## The problem, in one paragraph

The system knows exactly 13 document types, hardcoded as a dict in
`ingest/dispatcher.py`, and `pick_extractor` raises on anything else. Which
extractor runs is decided by **what the uploader clicked**, and nothing
afterwards checks whether that choice worked. When it does not work, the
document is still written, still marked `live`, and still reported as a
success — so an analyst searching for its content simply finds nothing and
concludes the corpus lacks it. This has already happened once, to a document
currently in the corpus.

---

## Measured evidence

Everything in this section was measured on 2026-08-11 against the live
77,574-chunk corpus and the source PDFs on disk. It is not recalled or
projected.

### The failure that motivates the design

`agao-afr-fy2024` is 191 pages and produced **20 chunks**. Its three siblings,
near-identical in length, produced 169 / 182 / 189. Pages 1–183 produced
nothing at all.

**The file is fine.** The Auditor General changed how the document is marked
up between editions — FY2023's financial statements are tagged as tables,
FY2024's as loose paragraphs. OpenDataLoader reported each faithfully;
`chunking/builder.py` builds table chunks then narrative chunks, and found
almost nothing it recognised in the paragraph form.

### Inspection cannot predict this — the decisive measurement

|  | FY2023 AFR | FY2024 AFR |
|---|---|---|
| pages | 184 | 191 |
| `/StructTreeRoot` present | **yes** (`6 0 R`) | **yes** (`6 0 R`) |
| text on page 100 | 7,701 chars | 4,876 chars |
| chunks produced | 189 | **20** |

**Both are tagged PDFs.** A pre-extraction check for a structure tree — the
D4 rule the dispatcher's own docstring describes, and the check Plan 6 Task 5
proposed — would have routed both to OpenDataLoader and caught nothing. The
difference is in the *shape* of the tagging, which is only observable after
extraction has been attempted.

**This is why T5 judges output, not input.**

### The quality signal, measured across both extractors

Compare the characters of text that reached the corpus against the characters
in the source PDF's own text layer (PyMuPDF).

| document | extractor | PDF chars | chunk chars | coverage |
|---|---|---|---|---|
| `agao-afr-fy2021` | opendataloader | 949,961 | 2,642,751 | 278.2% |
| `agao-afr-fy2022` | opendataloader | 1,037,104 | 2,962,226 | 285.6% |
| `agao-afr-fy2023` | opendataloader | 1,081,137 | 3,034,269 | 280.7% |
| **`agao-afr-fy2024`** | opendataloader | 1,153,423 | **22,718** | **2.0%** |

Sampled across MinerU-extracted types (seed 7, 12 documents, 2 skipped for
unreadable source paths):

| doc_type | coverage range |
|---|---|
| `baseline-per-agency` | 45.1% – 80.9% |
| `approps-per-agency` | 72.7% – 82.9% |
| `s-pdf` | 56.1% – 108.5% |
| `detailed-list-pdf` | 80.2% – 97.9% |
| `governors-budget` | 92.2% – 96.0% |

**Readings that matter:**

- Coverage exceeds 100% for healthy documents because tables are emitted as
  markup, which adds characters. The ratio is a **sanity check, not an
  accuracy measure.** Do not read 278% as "better than" 92%.
- The two extractors sit in **different bands** (OpenDataLoader ~280%, MinerU
  45–108%) because they differ in how much markup they emit. A threshold must
  therefore be a **floor well below both bands**, never a target range.
- Lowest healthy observation **45.1%**; the failure **2.0%**. A floor anywhere
  in 15–25% separates them with ≥ 2× margin below the healthy band and ≥ 7×
  margin above the failure.
- The signal needs **no per-document-type tuning**, which is its main
  advantage over the chunks-per-page floor Plan 6 proposed (AFRs run ~1.0
  chunks/page, JLBC books 3.2–5.2, so that approach needs a table of
  thresholds that must be maintained as types are added).

### The "Add a JLBC book" panel is non-functional

`list_editions()` reads only `data/jlbc-book-catalog.json`, a snapshot of
azjlbc.gov taken 2026-06-16. The picker renders every row it returns, with no
filter.

```
62 editions offered in the dropdown
├── 38 marked ingestable  → all 38 are ALREADY in the corpus
└── 24 marked NOT ingestable → offered anyway (approps FY1984–2004,
                                baseline FY2007–2011: years JLBC never
                                published as per-agency PDFs)

Editions offered that a user could usefully add: 0
```

Catalog coverage is approps FY1984–**FY2026** and baseline FY2007–**FY2027**.
**The FY2027 Appropriations Report is not in it**, and neither is anything
JLBC publishes from now on.

`plan_edition()` already falls back to `_plan_by_probing()` on a catalog miss,
climbing HEAD-verified URL ladders. That path works — on 2026-07-31 a live
dry-run found the FY2027 Appropriations Report by probing and walked **139
documents, 0 unreachable**. **The server can add it today; the interface
offers no way to ask.**

### The job queue is unbounded

`GET /api/jobs` is `{"jobs": [job.view() for job in load_all()]}` — no filter,
no limit, no sort. Measured against the live data dir:

| | |
|---|---|
| job files on disk | **7,116** (28 MB) |
| `/api/jobs` response | **3.02 MB**, every poll |
| `live` | 7,099 |
| `failed` | 13 |
| `cancelled` | 4 |

`load_all()` takes 0.15 s here on NVMe. **The office reads this off an SMB
share**, where it is 7,116 file reads per refresh of the Upload page, which
polls. The 3 MB payload is then rendered as an ever-growing list in which the
13 rows that need attention are buried under 7,099 that do not.

---

## Decisions

### T1 — Six upload rows over the corpus's existing types, plus two new ones

The six rows are the **analyst-facing** vocabulary. They are not a new set of
document types; they are a presentation over the 13 `doc_type` values the
corpus already uses, plus the two this design adds — **15 registered types,
six upload rows.**

Two existing types are deliberately absent from the rows and remain
registered and unchanged: `budget-bill` (T3) and `fiscal-note`, which belongs
to the separate fiscal-note corpus and is added by its own refresh flow, not
by upload.

| Upload row | Behaviour | Internal `doc_type` |
|---|---|---|
| Baseline Book | **Redirects** to Add-a-JLBC-book | `baseline-per-agency`, `s-pdf`, `bh-pdf`, `bd-pdf` |
| Appropriations Report | **Redirects** to Add-a-JLBC-book | `approps-per-agency`, `detailed-list-pdf`, `topic-pdf` |
| Annual Financial Report | Upload a PDF | `afr` |
| Executive Budget | Upload a PDF | `governors-budget` |
| Agency Submission | Upload a PDF | `agency-submission` **(new)** |
| Budget Bill Summary | Upload a PDF + stage | `budget-bill-summary` **(new)** |

**Internal doc_types are NOT collapsed.** Doing so would re-type 7,434
documents, re-mint every `doc_id` (which embeds `doc_type`), and break eval
ground-truth `chunk_id`s — and `eval/refresh_chunk_ids.py`, the tool that
would re-bind them, was deleted with the Postgres tooling and has no
replacement. The per-agency vs section distinction is also what makes
agency-scoped search work.

**The two book rows redirect rather than accept a file** (S25 unchanged). An
edition is ~110 per-agency documents; uploading the single-file PDF would add
a 400-page book as ONE document and degrade agency search for that year.

#### 🔴 The registry must also decide doc_id identity

Found while planning, by executing `make_doc_id` rather than reading it:

```
make_doc_id(publisher='governor', doc_type='agency-submission',
            fiscal_year=2027, filename='BHA-FY27.pdf')
  -> 'governor-agency-submission-fy2027'
make_doc_id(publisher='governor', doc_type='agency-submission',
            fiscal_year=2027, filename='DXA-FY27.pdf')
  -> 'governor-agency-submission-fy2027'          # IDENTICAL
```

**The non-JLBC branch drops `filename` entirely**, because it assumes one
document per publisher per fiscal year. That holds for the AFR and the
Executive Budget. It is false for agency submissions (78 in FY2027) and bill
summaries (3 in FY2027). A write is an upsert, so ingesting the 78 would have
left **one document**, with nothing erroring anywhere — the same shape as the
JLBC book collision fixed in `f85b20a`, arriving by a different route.

So the registry carries **`one_per_year`** per type, and `make_doc_id`
consults it. `afr` and `governors-budget` are declared one-per-year and keep
their exact existing ids; the two new types are not, and take the filename
into their identity.

**This is why identity belongs in the registry rather than being inferred
from the publisher.** The publisher was never the thing that determined it —
it was a proxy that happened to hold for the three types that existed.

Bill summaries would not have collided, because their publisher is `jlbc` and
that branch does use the filename. Agency submissions need a publisher value
that does not exist yet; the harvest records the **agency name** (78 distinct
values), so a new publisher `agency` is added rather than 78 — the agency
identity already lives in the entity stamper and `agency_canonical_id`, and 78
publishers would destroy the publisher filter's usefulness.

### T2 — `budget-bill-summary` is a new type with a stage

The JLBC-published *"House and Senate Budget Bills"* PDF at
`azjlbc.gov/budget/`. Precursor to the Appropriations Report.

The upload row asks for one extra field: **stage — Introduced or Engrossed.**
There is no Final stage; JLBC titles that read "Final Budget Bills" are the
engrossed version and record as `engrossed`.

**Ordering rule:** `engrossed` supersedes `introduced`. Where two documents
share a stage and fiscal year, the later-added one wins. This is sufficient
because summaries are **not backfilled** (T11) — every one the corpus will
ever hold is uploaded as it is published, so upload order matches publication
order. No date field is required of the uploader.

### T3 — The DOCX feed bill stays

`budget-bill` (DOCX, `python-docx`) is retained. The Word file carries the
section and paragraph structure that lets the app cite an exact provision;
the summary PDF does not. The two serve different questions.

**It is not offered as an upload row initially.** The type remains registered
and its one existing document is untouched.

### T4 — The type table becomes data

`data/document-types.yaml` + `ingest/doc_types.py`, consumed by the
dispatcher, the upload route, the validator and the webapp via
`GET /api/document-types`. Mtime-cached; a malformed file **raises** rather
than falling back to defaults, because silently forgetting how to route
documents is worse than not starting.

Each row carries: key, analyst label, group, accepted formats, the preferred
extractor per format, **the fallback ladder**, publisher hint, redirect (if
any), and the one-line `where_published` / `which_file` guidance the upload
row displays.

`webapp/src/pages/Upload.tsx`'s hand-typed `DOC_TYPES` list is **deleted**,
not kept in sync. `app/routes/upload.py`'s `ACCEPTED_DOC_TYPES` is already
derived from the registry and is repointed, not duplicated.

**Adding a seventh row must be a change to this YAML file, not to code.**
That is the acceptance test for T4.

**The registry must not become a fourth copy of the section-kind mapping.**
`ingest/section_types.py` landed on master on 2026-08-11 for exactly this
reason — `SECTION_KIND_TO_DOC_TYPE` had been hand-maintained in three places
(`book_discovery.py`, `driver.py`, `app/book_sections.py`) and was
consolidated into one module. The registry describes *document types*; that
module describes *which cross-cut section filename becomes which doc_type*.
They are different vocabularies at different levels. The registry **imports**
it where it needs it and restates nothing.

Note also that the two importers deliberately disagree on the miss case —
`book_discovery.py` defaults an unknown kind to `topic-pdf`, `driver.py`
raises — and that difference is documented in that module. Do not "unify" it.

### T5 — Detect, try, check, fall back

```
1. INSPECT the file        format, page count, has a text layer at all,
                           structure tree present
                           → picks the STARTING method only
2. EXTRACT                 with the registry's preferred method
3. CHECK the output        coverage ratio vs the source (T6)
4. FALL BACK               if below floor, try the next method and re-check;
                           keep whichever result scored highest
5. ESCALATE                only when every method has been tried (T8)
```

**Step 1 picks the starting rung; it never decides success.** The FY2023 /
FY2024 measurement above is the reason: two files identical on inspection,
one of which fails.

Where the declared type and detection disagree — a PDF declared `afr` with no
structure tree — detection wins and the disagreement is recorded on the job.

### T6 — The coverage check

**Signal:** characters of chunk text produced ÷ characters in the source
file's own text layer (PyMuPDF for PDF, python-docx for DOCX).

**Placement: after chunking, before embedding.** Extraction takes hours;
chunking and embedding take minutes (`ingest/worker.py` module docstring).
Checking after chunking means the measurement is taken on exactly what was
measured in this document's evidence section, and a failing document is
caught before the embedding and write phases are paid for.

**Floor: 10% — CALIBRATED 2026-08-12 across all 7,434 documents.**
Measurement: `docs/superpowers/investigations/2026-08-12-coverage-floor-calibration.md`.

The original expectation here was 15–25% from a 16-document sample. The
corpus-wide run says that is **too high**. Median coverage is 87.9%; every
floor from just above 2.0% to just below 17.1% catches an identical set of
**two** documents, and 10% is that plateau's centre — the right pick because
the metric degrades on both sides (below 2.0% the known-broken AFR escapes;
above 17.1% healthy short documents start being caught). **Risk 2 is closed:**
2 documents of 7,434 (0.03%) would ever pay for a fallback.

Two implementation constraints the measurement produced, both load-bearing:

- **The corpus has two chunk tables.** Summing `budget_chunks` alone scored
  all 2,104 fiscal notes at 0.0% and made 28.3% of the corpus read as broken.
  Resolve the document's own table before dividing.
- **🔴 The ratio detects catastrophic loss, not corruption.** It cannot see a
  document that produced the right *amount* of the *wrong* text — the FY2024
  AFR's own recovered rows are label-stripped table fragments that a
  numeric-density check scored 1.6% "junk". A document that passes the floor
  is **not** thereby certified good, and no copy may imply it is. This is why
  T8's human surface is not optional.

Ratios routinely exceed 100% (the healthy AFRs score 278–286%) because chunk
text carries table markup the source text layer does not. **Do not cap or
normalize the ratio** — it is a proxy for extraction health, not a "fraction
captured".

Two cases the ratio does not cover, handled separately:

- **No text layer at all** (a scan) — the denominator is ~0 and the ratio is
  meaningless. Detected in step 1 and routed straight to OCR.
- **DOCX** — has no page count and a different text model. Ratio still
  applies (chunk text vs document text); the page-based reasoning does not.

### T7 — The fallback ladders

**PDF:**

| rung | method | why it is where it is |
|---|---|---|
| 1 | OpenDataLoader | Fast, cell-level table fidelity — but depends entirely on how the publisher tagged the file |
| 2 | MinerU (`--method auto`) | Slower; reconstructs layout visually, indifferent to tagging. **This is what recovers the FY2024 AFR** |
| 3 | MinerU (`--method ocr`) | Reads pages as images. For scans and image-only PDFs |

A PDF with no structure tree starts at rung 2. A PDF with no text layer starts
at rung 3.

**DOCX:** `python-docx` only. No ladder — the structure is in the file, and
there is no second tool to try.

**Cost:** a document that needs a fallback pays extraction twice — hours, not
minutes. Accepted deliberately: large books already run overnight, fallbacks
should be rare, and the alternative is a silently empty document. **The job
record must show that a fallback occurred and why**, so "this upload took
twice as long" is explicable rather than mysterious.

### T8 — Terminal failure is held out of search, not marked live

When every rung is below the floor, the document is **not** marked `live`. It
is recorded with its findings and appears on the admin page with what was
tried and what each attempt scored.

This is the one place a human is required, and it should be rare. It is also
the specific behaviour whose absence produced the FY2024 AFR: a job that
reports success while delivering nothing is worse than a job that fails.

`documents.json` gains two optional document-level keys (**not** chunk
columns — the value is identical on every chunk of a document, and adding a
column means a schema migration over 77k rows on a shared drive):

```
"extraction": { "method": "mineru", "attempts": [...], "coverage": 0.94,
                "fell_back": true }
"validation": { "findings": [str], "blocking": bool, "checked_at": str }
```

Absent on all 7,434 existing documents, and absence must read as "fine" —
not as an error.

### T9 — What the AI is told about bill summaries

Added to `harness/system-prompt.md`'s "lifecycle of a budget number" section,
which already carries the Proposal → Recommendation → Enactment → Actual
table. Bill summaries sit between Recommendation and Enactment.

> A **Budget Bill Summary** is JLBC's summary of the budget bills as they move
> through the Legislature. It precedes the Appropriations Report for that
> fiscal year and is superseded by it.
>
> - Use it for current-year questions **only when no Appropriations Report
>   exists yet for that fiscal year.** Before relying on one, run a search
>   filtered to that fiscal year and the Appropriations Report document type.
>   If it returns material, use that and ignore the summary.
> - There may be several within one fiscal year. **Engrossed supersedes
>   Introduced.** Never answer a "what is the budget for X" question from an
>   Introduced summary when an Engrossed one exists.
> - When you do use a summary, say so in the answer — it describes a bill in
>   progress, not an enacted appropriation.

**This is prompt guidance only. No retrieval filter, no ranking change.**

The rule is written as something the model can **check** rather than assume.
The model cannot observe corpus state directly — it sees only the chunks a
retrieve returned — so "ignore the summary if an Appropriations Report
exists" is unenforceable as stated. Instructing it to run one filtered search
makes the condition observable using a tool it already has.

**Known limit, accepted:** this is a rule followed, not a door locked. A model
that ignores the instruction will cite a superseded draft, and neither
Invariant 1 nor 2 catches it, because the citation is faithful to a real
passage in a real document. Destin's call: the mechanisms that would make it
a guarantee (retrieval-side exclusion, or supersession metadata on each chunk)
are not worth their cost now. Revisit if Layer 2 evaluation shows the model
using superseded summaries.

`_DOC_TYPES` in `harness/tools.py` must gain both new types. That enum has
drifted from the corpus before and the failure was **silent** — a filtered
search on a value the corpus lacks returns zero chunks with no error, and the
model concludes the corpus lacks the material. The comment at that enum says
to extend the system prompt in the same change; do so.

### T10 — Invert the "Add a JLBC book" panel

The panel answers **"what has JLBC published that we don't have?"** — not
"here is every edition that exists".

On open:

1. Determine the newest fiscal year present in the corpus for each family.
2. Probe azjlbc.gov for editions beyond it (the existing
   `_plan_by_probing` ladders; a handful of HEAD requests).
3. Also surface any catalog edition marked ingestable that is **not** in the
   corpus.
4. Show what is missing, with an Add button. When nothing is missing, say so.

```
Add a JLBC book

Checking azjlbc.gov for editions you don't have…

  FY 2027 Appropriations Report — 139 documents — not in your corpus  [ Add ]

Everything else JLBC publishes is already here.

Need an older edition?  [ Choose a specific year ]
```

Three properties this must have:

- **Editions already in the corpus are marked as such**, or omitted. Today the
  list makes no distinction, which is what makes it read as noise.
- **Non-ingestable editions are not selectable.** Show them greyed with their
  `era_note` — "FY 1984 was never published as per-agency PDFs" is a fact
  worth stating — but Add must not be offered.
- **A specific year can still be requested**, reaching `_plan_by_probing` for
  a year the automatic check missed.

**Accepted limit:** if JLBC changes its URL scheme entirely, probing finds
nothing and `DiscoveryError` already says a new pattern must be added to
`ingest/book_discovery.py`. That is honest and is not worth engineering
around.

### T11 — The backfill

| | Work |
|---|---|
| Annual Financial Reports FY2021–2025 | **Already complete.** All five are in the corpus; FY2021–2024 were manual uploads past the Cloudflare block. The only work is **re-processing FY2024** through the T5 ladder |
| Executive Budgets FY2021–2024 | 4 documents. **A person must locate them on ospb.az.gov** — the June 2026 harvest never indexed that site, and filenames follow no pattern (`FY 2025 State Agency Detail.pdf` vs `state-agency-detail-fy-2027.pdf`) |
| Agency Submissions FY2027 | 78 in the harvest — 60 fetch automatically, **18 are behind bot protection** and need a person with a browser |
| Agency Submissions FY2026 | Not in the harvest. A person must locate them |
| Budget Bill Summaries | **Not backfilled** (Destin's call — Appropriations Reports already cover prior years) |

**What we hold as "Executive Budget" is the *State Agency Detail* volume**,
one part of the Governor's Executive Budget, not the whole publication. Worth
confirming that is the intended document before fetching four more.

The manual items belong in `docs/HANDBOOK.md` as a checklist, so they are
ordinary office work rather than an unscheduled project.

### T12 — Never silently re-ingest a healthy document

Two mechanisms already exist and are **kept**:

- **Upload** dedupes on the file's SHA-256 against both `documents.json` and
  pending jobs, returning **409** with when and who added it, plus an explicit
  `reprocess` flag to override. This is already the confirmation this decision
  asks for.
- **Book ingest** skips any `source_url` already in `documents.json` or in a
  non-terminal job, and reports `skipped_existing`.

Three gaps to close:

1. **The book panel offers editions it will then skip.** All 38 ingestable
   editions in the picker are already in the corpus, so "Add all" reports
   `skipped_existing: 139` and appears to do nothing. **T10 fixes this at the
   source** by not offering them.
2. **Neither check knows whether the existing copy is healthy.** With T6 in
   place, `documents.json` records each document's extraction coverage, so the
   duplicate response must distinguish two cases that deserve opposite advice:

   > *"Already added 2026-08-02. Extraction looked healthy (94% coverage).
   > Re-processing is not needed."*

   > *"Already added 2026-08-01, but extraction looked poor (2% coverage) —
   > pages 1–183 produced nothing. **Re-processing is recommended**, and the
   > app will now try a different method."*

   A blanket "already ingested" warning would discourage exactly the
   re-processing the FY2024 AFR needs.
3. **Re-processing must be a deliberate act with a visible consequence.** A
   re-ingest replaces the document's chunks and therefore its `chunk_id`s. The
   confirmation says so in plain language, and Risk 3 below applies.

**Not in scope:** deduping on anything other than exact bytes / exact URL. A
publisher re-issuing a byte-different but substantively identical PDF is a
real case, and detecting it is a separate problem — the current behaviour
(same `doc_id` ⇒ upsert-replace) is defensible and unchanged.

### T13 — The queue shows work, not history

`GET /api/jobs` returns:

- every job in a **non-terminal** state (queued, extracting, chunking,
  embedding, writing), and
- ~~terminal jobs that finished **within a window, default 24 hours**~~
  — **DROPPED 2026-08-13, see the amendment below**, and
- **every `failed` job, regardless of age**, until it is retried, cancelled or
  dismissed.

That last clause is deliberate and is the one rule not to relax. This project
has repeatedly been bitten by work that fails without anyone being told; a
failure that ages off the screen after a day is a failure nobody will ever
see. Successes age out because a finished document is visible in search — the
queue is not where you confirm it exists.

**Filter on the job file's mtime from the directory scan, before parsing it.**
The current cost is 7,116 file reads; deciding from the directory entry means
parsing only the handful that qualify. This matters specifically because the
office reads the queue off an SMB share.

> #### 🔴 AMENDED 2026-08-13 — the mtime instruction above CANNOT be
> #### implemented as written, and following it hides the failures
>
> A job file's modification time does not carry the job's **state** — that is
> inside the file. So a timestamp-first filter cannot identify either category
> this decision says must always appear, and the 24-hour window then deletes
> them. Measured against the live data dir on 2026-08-13:
>
> | | count |
> |---|---|
> | job files on disk | 7,118 |
> | `live` | 7,100 |
> | **`failed`** | **14** |
> | `cancelled` | 4 |
> | **`failed` with a file older than 24 h** | **13 (all 12.6 days old)** |
>
> **A 24-hour mtime window drops 13 of the 14 failures** — the exact opposite
> of the clause above it, which this decision calls the one rule not to relax.
> The same hole applies to a `queued` job: ingest is default-OFF per machine,
> so an uploaded document can legitimately wait days with a stale timestamp
> while the ingest PC is closed, and the row would silently disappear.
> (0 such jobs today; that is luck, not safety.)
>
> **Knowing a job's state cheaply requires changing how job files are written.**
> Three options were put to Destin and he chose the third on 2026-08-13:
>
> 1. Keep reading every file and filter after parsing — correct, shrinks only
>    the payload, fixes none of the other callers below.
> 2. Put the state in the filename, `<job_id>.<state>.json`.
> 3. ✅ **CHOSEN — finished jobs move to a `jobs/done/` subdirectory.**
>
> Chosen over (2) because it preserves the property this whole one-file-per-job
> design rests on — *"a colleague (or a future maintainer with no code access)
> can read the queue in Notepad"* (`ingest/jobs.py` module docstring). A folder
> named `done` states what it holds; a filename suffix does not. `failed` stays
> in the main folder, which is what makes "every failed job, regardless of age"
> fall out of the storage shape instead of needing a rule to enforce it.
>
> **The cost is also in six other callers**, not just the listing route:
> `app/routes/admin.py` (×2), `app/routes/upload.py` (every upload),
> `app/routes/books.py` (every book ingest), `ingest/jobs.py::resumable`, and
> — the one nobody had noticed — **`ingest/worker.py::_candidates`, which reads
> all 7,118 files every time the background worker looks for the next document
> to process.** A filename/subdirectory scheme fixes all of them; a filter in
> the listing route fixes none of them.
>
> **✅ ACCEPTED 2026-08-13 — the 24-hour window is dropped.** The rule above
> is superseded by: *"the queue shows anything unfinished plus anything failed,
> and one line saying how many finished documents exist."* Once finished jobs
> live in another folder an age window has nothing left to do, and an age
> window with an exception clause is exactly what produced the defect measured
> above. One rule with no exception cannot reproduce it.
>
> The window's only genuine job was not yanking a row out from under someone
> watching their upload finish. **The browser knows what it was watching**, so
> that becomes a client-side touch — keep those rows for the rest of the
> session — rather than a server-side window with a configurable duration.

**Job files are not deleted.** They are the ingest audit trail — what was
added, by whom, when, and now which extraction methods were tried. This
decision changes what the queue *shows*, not what is *kept*. Pruning them is a
separate question with a different risk profile and is not decided here.

The page keeps a way to see everything — a count and a link — so "where did my
document go" has an answer that is not "trust me".

### T14 — Explicitly out of scope

- **No `other` catch-all row.** Destin: these six "initially". T4 makes a
  seventh row a data change, so this is deferred, not foreclosed.
  **Consequence to state plainly:** roughly 171 JLBC publications in the
  harvest — Tax Handbooks, Monthly Fiscal Highlights, ballot-initiative
  analyses, revenue reports — remain un-ingestable.
- **No supersession filter or ranking change** (see T9).
- **No re-typing of existing documents** (see T1).
- **No scraper for pre-FY2027 agency submissions** — 78 separate agency
  websites with no shared URL convention.

---

## Testing

Per CLAUDE.md: mechanism in pytest, quality in the eval.

**pytest:**
- The registry reproduces today's routing **exactly** — every shipped
  `(doc_type, format)` pair resolves to the same extractor class. This is the
  safety net for the whole refactor; a differently-extracted document produces
  different chunk text, different `chunk_id`s, and broken eval ground truth.
- A characterization test written and confirmed green **against unmodified
  master first** — one that has never passed against the old code proves
  nothing.
- The coverage check computes the measured values above for fixtures of known
  shape, including the 2.0% case.
- The fallback ladder advances on a below-floor score and keeps the best
  result; a document that passes on rung 1 never runs rung 2.
- Terminal failure does not reach `live`.
- `extraction` / `validation` absent from a document is not an error.
- Adding a row to the YAML adds an upload row with no code change.
- The book panel omits or marks editions already in the corpus, and never
  offers Add on a non-ingestable edition.
- A duplicate upload of a **healthy** document returns 409 and says so; a
  duplicate of a **below-floor** document returns 409 and recommends
  re-processing. Both are pinned, because the two sentences must not be
  swapped.
- `/api/jobs` excludes a `live` job older than the window, includes a `live`
  job inside it, and includes a `failed` job **of any age**. The last one gets
  a test with an explicitly ancient timestamp — it is the clause most likely
  to be "simplified" away later.
- The mtime filter is exercised by a job file whose *contents* would qualify
  but whose *mtime* would not, proving the cheap path is the one taken.

**Not pytest:** nothing here may open a real LanceDB directory or load ONNX
weights.

**Eval:** this changes `ingest/`, `chunking/` routing and
`harness/system-prompt.md`, so `uv run python -m eval.run_eval` must run and
its results commit alongside. **Expect no movement** — no existing document is
re-extracted by this work — and treat any movement as a finding to explain,
not noise.

---

## Risks

1. ~~**The floor is the whole design.**~~ **RESOLVED 2026-08-12** — calibrated
   corpus-wide at **10%** (T6). The separation is not marginal: two orders of
   magnitude between the broken control and its healthy siblings, and a
   15-point band around the floor containing no documents at all.
   **The residual risk is different from the one stated here:** the floor is
   safe, but the *signal* is blind to corruption that preserves volume. See
   T6's second constraint.
2. ~~**A fallback doubles extraction time.**~~ **RESOLVED 2026-08-12** — at the
   calibrated floor, **2 documents of 7,434 (0.03%)** are below it. The
   per-document cost is real; the aggregate cost is not.
3. **Re-processing the FY2024 AFR replaces its chunks**, and therefore its
   `chunk_id`s. Nothing in `eval/queries.yaml` currently references that
   document — **verify before re-processing**, not after.
4. **T9 is unenforced.** Stated plainly at T9; the mitigation is Layer 2
   observation, not a mechanism.
