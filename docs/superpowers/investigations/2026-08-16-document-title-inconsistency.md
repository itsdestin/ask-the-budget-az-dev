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

`app/routes/books.py:148` passes `user_title=doc.title`, where `doc.title`
is the **link text scraped off JLBC's index page** — literally the word
"AHCCCS". `ingest/lance_writer.py::build_title` opens with:

```python
if user_title and user_title.strip():
    base = user_title.strip()
```

*"A title the uploader typed wins verbatim — they know what the document is
and we don't."* That reasoning is right for a person filling in a form and
wrong for a scraper: nobody typed anything, and the scraper knows less than
`build_title` does. So the automatic naming is defeated on every document
added by the book tool.

It has not been visible until now because every earlier edition ALSO had a
mockup-index entry, which outranks the sidecar. The FY2027 Appropriations
Report is the first book ingested that the 2026-06-16 harvest never saw —
it is the edition the T10 panel correctly reported as missing — so it is
the first to fall through to rung 2 and show what rung 2 has always
produced.

**126 documents were created in this shape today.**

## What a fix looks like

**One rule for JLBC book documents: `{Agency} — FY {year} {Book}`** — the
mockup index's own format, since that is both the best of the three and the
one the majority of the corpus already uses.

1. **Stop the books route passing scraped link text as `user_title`**
   (`app/routes/books.py:148`). It is the only caller that supplies a title
   nobody typed. `build_title` already produces the right shape from
   doc_type + fiscal_year + agency.
2. **Re-title the affected documents.** This appears to be **metadata only
   — no re-ingest** (`doc_title` is not a column in `store/schema.py`; the
   browse page composes the title at query time from documents.json). ⚠
   VERIFY THAT before relying on it, because STATUS.md says elsewhere that
   "doc_title rides on every retrieved chunk" for AI Mode's
   Engrossed-supersedes-Introduced rule. If AI Mode reads a stored title,
   the two paths need checking separately.
3. **Decide about the ~378 migration-era documents.** They have no
   `ingested_at`, which is why the sidecar's title is distrusted for them.
   Re-titling them is the same metadata operation.

## Two smaller things the same query exposed

- **FY2005–FY2011 AHCCCS reads as raw slugs**: `AXSACUTE — FY 2005
  Appropriations Report`, `AXSADMN`, `AXSLTC`. JLBC split AHCCCS into three
  documents in those years and the website index named them by slug. Older,
  separate, lower priority — but it is the same class of problem.
- The `ingested_at` gate was introduced (Plan 5 Task 19) to stop migration
  junk titles beating the humanizer. It is doing its job. The defect is
  that there are three producers at all, not that the gate is wrong.

## Why no test caught it

Every title-producing path has tests and they all pass. Nothing compares
the OUTPUT of the three paths against each other, and nothing looks at a
result list as a list. The same shape as the other defects this branch
found: individually correct, jointly wrong, and only visible on screen.
