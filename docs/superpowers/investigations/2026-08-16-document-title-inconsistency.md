# Document titles disagree with each other — three formats, three sources

**Found 2026-08-16** by Destin searching `ahcccs` on Budget Documents and
reading the result list. NOT found by any test. Not fixed yet.

## The symptom

One agency, one publisher, six consecutive years, three naming formats:

| document | displayed as |
|---|---|
| `jlbc-approps-fy2024-axs` | `AHCCCS — FY 2024 Appropriations Report` |
| `jlbc-approps-fy2025-axs` | **`JLBC FY2025 — AHCCCS`** |
| `jlbc-baseline-fy2026-axs` | **`JLBC FY2026 — AHCCCS`** |
| `jlbc-approps-fy2026-axs` | `AHCCCS — FY 2026 Appropriations Report` |
| `jlbc-baseline-fy2027-axs` | **`JLBC FY2027 — AHCCCS`** |
| `jlbc-approps-fy2027-axs` | **`AHCCCS`** |

Scanned as a list — which is exactly how the Budget Documents page is used
— the same agency's pages read as if they came from different systems, and
the FY2027 Appropriations Report entry does not say what year or what book
it is at all.

## Why: the browse page has THREE title sources and they never agreed

`app/search_provider.py` line 121 states the precedence outright:

> mockup index → the sidecar's own title → humanized doc_id

Each rung produces a different shape, and which rung a document lands on is
an accident of when and how it was ingested.

### 1. `AHCCCS — FY 2026 Appropriations Report` — the mockup index

The JLBC website harvest (`webapp/reference/assets/search/index-lite.js`,
snapshot **2026-06-16**) carries the website's own display title, joined by
exact `source_url`. This is the good format and it covers most of the
corpus — every edition the harvest saw, FY2005 through FY2026.

### 2. `JLBC FY2025 — AHCCCS` — the doc_id humanizer

These carry **no `ingested_at`**: they are the ~378 documents from the
original Postgres → LanceDB migration, which STATUS.md already records
under Plan 5 Task 19 ("378 live documents lack `ingested_at`, and gating
them turns *'JLBC FY2027 — AHCCCS'* into *'JLBC Baseline FY 2027 Axs'*").
That note treated the string as merely ugly. It is also **inconsistent with
its own neighbours**, which is the part nobody had looked at.

### 3. `AHCCCS` — 🔴 TODAY'S INGEST, and a regression

**Narrowed 2026-08-16 after the first write-up.** The original diagnosis —
"the books route passes a scraped title and defeats `build_title`" — was
half right and pointed at the wrong file. `build_title` is fine and the
books route is fine. **The defect is in `ingest/book_discovery.py`, and it
is a difference between two discovery paths that both feed the same route.**

`app/routes/books.py:148` passes `user_title=doc.title`, and
`ingest/lance_writer.py::build_title` honours it verbatim —
*"a title the uploader typed wins verbatim"*. That is correct, because
**for most of the corpus `doc.title` is the JLBC website's own display
title.** `data/jlbc-book-catalog.json` (built from the 2026-06-16 harvest)
carries it already composed:

```json
{"code": "axsacute", "title": "AXSACUTE — FY 2005 Appropriations Report", ...}
```

So the 4,946 well-named documents got their names through exactly the same
line that produced today's bad ones. **`discover_documents()` returns the
catalog roster untouched when it has one** (`book_discovery.py:265`).

The probe ladder — the fallback for an edition the harvest never saw —
composes nothing:

```python
title=entry.name or entry.slug,          # agency index  (line 275)
title=entry.title or entry.filename,     # linked TOC    (line 284)
```

`entry.name` is the raw link text off the index PDF. For an agency page
that is the bare agency name (`Gaming, Department of`); for a summary
section it is the table-of-contents line **including its bullet and dot
leaders** (`• Summary of One-Time General Fund Adjustments ..........`).

It has never been visible because until today every edition ingested came
from the catalog. The FY2027 Appropriations Report is the **first edition
ever ingested through the probe ladder** — it is the edition the T10 panel
correctly reported as missing — so it is the first to show what that path
has always produced.

**131 documents were created in this shape today.**

## How big the problem actually is

Measured against the live sidecar, 7,565 documents:

| title shape | count | verdict |
|---|---|---|
| `X — FY nnnn Book` (catalog / website) | **4,946** | correct, the target format |
| `Fiscal Note - SB nnnn: …` | 2,104 | correct — a different corpus with its own format |
| `JLBC FYnnnn — X` (migration-era) | 369 | ugly and inconsistent, but parseable |
| **bare link text (JLBC books)** | **137** | 🔴 the defect — **131 created today** |
| AFR / Governor / bill singletons | 9 | correct |

The 137 are the only genuinely broken ones. Of the 6 that predate today,
all six are the same smaller bug in a different place — `JLBC FY2025 apf`,
where a hyphenated sub-slug (`doa-apf`) defeated the agency lookup.

## What a fix looks like

**One rule for JLBC book documents: `{Name} — FY {year} {Book}`** — the
website's own format, because it is both the best of the shapes and the one
4,946 documents already use. Adopting anything else means re-titling the
majority to match a minority.

1. **Compose the suffix in the probe ladder** (`ingest/book_discovery.py`,
   the two `title=` lines), so both discovery paths hand the route the same
   shape. Strip the leading bullet and trailing dot leaders while there —
   the harvest's own titles have neither. **Roughly five lines**, and it
   touches neither `books.py` nor `build_title`, both of which are correct.
2. **Re-title the 137 affected documents.** ✅ **VERIFIED metadata-only —
   no re-ingest.** `doc_title` is not a column in `store/schema.py`; both
   readers compose it at query time from `documents.json`
   (`app/search_provider.py:236` for the browse page,
   `harness/tools.py:1035` → `store.documents.titles_for` for AI Mode).
   STATUS.md's "doc_title rides on every retrieved chunk" describes the
   retrieve() *payload*, not stored data.
3. **Decide separately about the 369 migration-era documents.** Same
   metadata operation, older problem, not caused by this work.

### ⚠ A second finding, from checking (2): the two surfaces disagree

The browse page and AI Mode do **not** use the same precedence.

| | browse page (`search_provider.py`) | AI Mode (`harness/tools.py`) |
|---|---|---|
| mockup index | ✅ first | **never consulted** |
| sidecar title | gated on `ingested_at` | ungated, and the only source |
| humanized doc_id | last | last |

Both gaps are deliberate and documented at the code, and today they happen
to agree on the six AHCCCS documents because the sidecar already holds the
website title. But **a document can be named one thing on screen and
another inside an answer**, and re-titling must therefore be checked on
both surfaces, not one.

## Two smaller things the same query exposed

- **FY2005–FY2011 AHCCCS reads as raw slugs**: `AXSACUTE — FY 2005
  Appropriations Report`, `AXSADMN`, `AXSLTC`. JLBC split AHCCCS into three
  documents in those years, and **the harvested catalog itself carries those
  slugs as the titles** — confirmed in `data/jlbc-book-catalog.json`. So the
  format is right and the name is wrong, which is a different repair
  (a slug→agency lookup) from the 137 above. Lower priority.
- The `ingested_at` gate was introduced (Plan 5 Task 19) to stop migration
  junk titles beating the humanizer. It is doing its job. The defect is
  that there are three producers at all, not that the gate is wrong.

## Why no test caught it

Every title-producing path has tests and they all pass. Nothing compares
the OUTPUT of the three paths against each other, and nothing looks at a
result list as a list. The same shape as the other defects this branch
found: individually correct, jointly wrong, and only visible on screen.
