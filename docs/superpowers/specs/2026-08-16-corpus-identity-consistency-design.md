# Corpus identity consistency — design

**Status: SPEC. Approved 2026-08-16. Not implemented.**

Evidence: [`docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md`](../investigations/2026-08-16-identity-consistency-audit.md)
and [`…-document-title-inconsistency.md`](../investigations/2026-08-16-document-title-inconsistency.md).
Every count below is measured against the live corpus on 2026-08-16
(7,566 documents / 83,016 budget chunks / the 157-agency catalog), not
estimated.

---

## The problem in one sentence

**An identity string — an agency's name, a document's title, its type — is
accepted from somebody else's rendering of a PDF and is never checked
against the document itself**, which is the one witness that always knows.

The three suppliers are JLBC's website index (link text), the book catalog
harvested from it, and PDF text extraction of a table of contents. All
three emit strings that look like names and sometimes are not: bullets,
dot leaders, page numbers, all-caps slugs, and — worst — the *previous*
entry's name.

### What that has cost, measured

| | count | |
|---|---|---|
| Documents stamped as an agency they never mention | **721** | 72.7% error rate on `agency:ost` |
| Documents carrying a different agency's name | **218** | e.g. Board of Barbers titled "Agriculture" |
| Documents named by a bullet or a bare slug | **137** | 131 created 2026-08-16; 6 older (`JLBC FY2025 apf`) |
| Corrupted names in the shipped agency catalog | **3** canonical + **31** variants | dot leaders, page numbers |
| Agencies split across multiple live ids | **6** | Child Safety across 4 |
| doc_ids whose family contradicts their own `source_url` | **22** | recorded elsewhere as 6 |
| Documents filed under a page prefix instead of a type | **669** | `s-pdf`, `bd-pdf`, `bh-pdf` |

**Already ruled out, so nobody re-audits them:** 0 documents duplicated by
content hash, 0 by `source_url`, 0 by (book, year, agency). Ingest
de-duplication works. Everything here is about what things are *called*.

### It is already reaching the model

From a committed agent-eval transcript
(`eval/results/agent/2026-08-02T0900Z-0b08221/lk-k12-basic-aid-fy2026-r1.jsonl`),
`list_filter_values` returned to the model, in production:

```json
{"canonical_id": "agency:ost", "chunk_count": 2277,
 "name": "Osteopathic Examiners in Medicine and Surgery, Arizona ...   342  Board of.........",
 "sample_doc_title": "FY 2026 State Agency Detail — Arizona Executive Budget"}
```

Sixth-largest agency in the corpus, above Public Safety, with a corrupted
name and a sample document that is not osteopathic. This is not a
projected risk.

---

## Decisions

### I1 — A name is a claim, and a claim needs two witnesses

Every JLBC document carries three independent statements of what it is:

| witness | example | fails when |
|---|---|---|
| **URL slug** | `/05app/bar.pdf` → `bar`, approps, FY2005 | JLBC reuses or retires a slug |
| **the document's own text** | *"Board of Barbers  Executive Director: …"* | extraction is poor |
| **the external index** | catalog title *"Agriculture, Arizona Department of"* | the scrape shifts a row |

**A derived identity is ACCEPTED when two witnesses agree.** One witness
alone is never sufficient, which is precisely today's behaviour and the
cause of every finding above.

Worked against the real defects:

- **Barbers** — slug says `bar`, text says Barbers, index says Agriculture.
  **2 to 1; the index loses and the disagreement is recorded.**
- **Osteopathic** — 721 documents whose text never says the word.
  **Flagged as ONE catalog problem, not 721 document problems.**
- **Today's 131** — the index has no entry at all. **Compose from the other
  two rather than accept a bullet.**

### I2 — Auto-repair only what two witnesses prove; flag the rest

Where the two-witness test passes, the correction is applied
automatically. Where it fails, **nothing is changed** and the document is
listed for a person.

Rejected: repairing everything (a badly-extracted document would get a
confident wrong name with no record it was a guess), and proposing
everything (≈950 rows nobody reads line by line, which is automatic
repair with extra steps).

### I3 — The validator QUARANTINES, it never silently repairs

One predicate — *does this string look like a name?* — with a **reason**
attached to every rejection. It never trims and retries: a stripped string
is a guess, a rejected one is a question with an answer.

Rejects, each drawn from a measured defect:

| rule | seen in |
|---|---|
| contains dot leaders (`..`) | `agency:ost`, `agency:nci`, 21 titles |
| contains an embedded or trailing page number | `ost` (342), `nci` (338), `apc` (286) |
| begins with a bullet (`•`) or other list glyph | 21 titles created 2026-08-16 |
| contains a doubled internal space | 3 canonical names, 31 variants |
| contains an HTML tag | 158 fiscal-note titles |
| is all-caps with no space | `AXSACUTE`, `DESAGE`, `DOAHUM` |
| exceeds 90 characters | `ost`, `nci` |

Applied at three entry points: the agency catalog on load, a document
title on write, and an office-added agency on save.

### I4 — At ingest, a bad name never blocks the document

The document is ingested and becomes searchable. Its name is composed from
the document itself. The queue row carries a plain sentence saying the
supplied name looked wrong and what was used instead.

**Rationale, and it is evidence not preference:** `ingest/validate.py`
already works this way and has already caught a real defect (the
mislabelled Industrial Commission upload). The alternative — holding the
document — is what happened to the FY2024 Annual Financial Report, which
sat invisible for weeks because *a held document looks exactly like a
missing one*. A name problem does not make the content wrong.

### I5 — One title format: `{Name} — FY {year} {Book}`

Not a new invention. **4,946 documents already use it** — it is the
website's own format. This makes the minority match the majority rather
than re-titling the majority to match a minority.

### I6 — The probe ladder composes the suffix; `build_title` is untouched

`ingest/book_discovery.py` lines 275 and 284 hand over `entry.name` /
`entry.title` raw. The catalog path hands over an already-composed
website title, which is why the same downstream line
(`app/routes/books.py:148` → `build_title`) produced 4,946 good names and
131 bad ones.

**Fix the discovery path, not the route and not `build_title`** — both are
correct. Strip leading bullets and trailing dot leaders there too.

### I7 — Repairing existing documents needs NO re-ingest — verified

Three checks, all confirmed 2026-08-16:

1. `ChunkStore.upsert_chunks` is keyed on `chunk_id` and replaces rows
   wholesale, so **passage ids survive** and eval ground truth with them.
2. `EntityStamper.resolve_all()` works from the chunk's own text, which is
   already stored. **No MinerU, no re-download, no re-chunking.**
3. `vector` is an ordinary projectable column, so the existing embedding is
   **carried through untouched. No re-embedding.**

Minutes of CPU, not the days a re-ingest costs.

**🔴 The one hazard, and it is real:** `upsert_chunks` is a delete followed
by an add, in **two separate commits**. An interruption between them leaves
those chunk_ids absent. The repair pass therefore runs under `IngestLock`,
takes a verified `store.backup.snapshot()` first, and is treated
operationally as an ingest — not as an edit.

### I8 — The repair pass writes a reversal record

Every change lands in a committed JSON file: doc_id, field, before, after,
which witnesses agreed. Two purposes — an analyst who disputes a name can
see why it changed, and the whole pass can be reversed without restoring a
snapshot.

### I9 — Split agency ids are MERGED in the data

Destin's call, 2026-08-16, over the recommended read-time grouping.

| agency | ids today | merge onto |
|---|---|---|
| Child Safety | `dcs` `cs` `doa-csf` `doa-cfs` `doacfs` | **`dcs`** |
| Arizona State University | `uniasu` `uniasum` | **`uniasu`** |
| Water Infrastructure Finance Authority | `wif` `wifa` | **`wifa`** |
| Equal Opportunity | `oco` `oeo` | **`oeo`** |
| Constable Ethics | `cet` `cna` | **`cet`** |
| Revenue | `dor` `rev` | **`dor`** |

**Target selection rule, in order:** the id already referenced by the eval
set (so measurement does not churn), else the id whose abbreviation matches
the agency's modern name, else the id with the most documents. `dcs` is
chosen on rule 1 — `eval/queries_recency.yaml` and
`eval/queries_historical.yaml` both name it.

**Recorded risk, since it is irreversible in the data:** this asserts that
a predecessor unit and its successor department are one agency. That is a
judgement a budget analyst may dispute. I8's reversal record and the
snapshot are what make it undoable; the merge map is committed so the
claim is visible rather than implicit.

### I10 — The 22 contradictory doc_ids are RENAMED, and the eval is re-pointed

Revised 2026-08-16 on Destin's instruction: *"if the eval is pinning a
broken thing, we should fix the eval."* The earlier draft proposed reading
around them precisely because `eval/queries.yaml` q-001 pins
`jlbc-baseline-fy2026-crr-0013`. **Protecting a defect because a test names
it is backwards.**

Renaming is deterministic and therefore verifiable.
`chunking/builder.py:134` mints `chunk_id = f"{doc_id}-{idx:04d}"`, so
`jlbc-baseline-fy2026-crr-0013` → `jlbc-approps-fy2026-crr-0013` is a pure
string substitution with the ordinal untouched.

**Every re-pointed entry is verified against its own `anchor_text`** —
q-001 records `"FY 2026 EORP employer contribution rate is 70.70%"`, so the
new chunk_id either still contains that sentence or the re-point is wrong
and the run fails loudly. This matters because `eval/refresh_chunk_ids.py`
was deleted and nothing replaces it; `anchor_text` is the surviving repair
path and this is exactly the case it was recorded for.

**Prevention already shipped** — `make_doc_id(family=…)` landed 2026-07-31,
so no new document can do this. The 22 are legacy only.

### I11 — `book_family` and `doc_kind` become two fields, because they are two facts

`doc_type` currently means both *which book* and *what kind of document*,
and it cannot express either cleanly:

| doc_type | in the Appropriations Report | in the Baseline |
|---|---|---|
| `detailed-list-pdf` | 244 | 62 |
| `topic-pdf` | 15 | 5 |
| `s-pdf` | 11 unresolved | 176 |

`app/search_provider.py` already works around this by **re-parsing
`source_url` at query time** — deriving at read what should have been
recorded at write. The fields are recorded at ingest instead, and the app
stops parsing URLs.

**`doc_type` itself is NOT removed or renamed.** It is pinned by
`eval/queries.yaml` dimensions (q-001 carries `doc_type: topic-pdf`), by
the retrieval filters, and by the document-type registry. Adding two
honest fields is additive; renaming the existing one is a second change
with its own eval risk, and is out of scope.

### I12 — One identity module, used by BOTH the write and the read path

The rules live in six places today: `ingest/lance_writer.py::build_title`,
`ingest/book_discovery.py`, `app/search_provider.py`, `harness/tools.py`,
`store/documents.py::humanize_doc_id`, and the catalog loader.

**That is why the browse page and AI Mode can name the same document
differently** — measured:

| rung | Budget Documents | AI Mode |
|---|---|---|
| 1 | website index title | **never consulted** |
| 2 | sidecar title, gated on `ingested_at` | sidecar title, **ungated** |
| 3 | humanised doc_id | humanised doc_id |

A single module that composes on write and resolves on read makes the two
surfaces structurally incapable of disagreeing, rather than merely
unlikely to.

### I13 — The gate is the ERROR rate, never coverage

`eval/identity_check.py`, offline, free, seconds, over data already on
disk — the shape `eval/false_link_check.py` proved for citations.

| metric | today | target |
|---|---|---|
| documents whose title names a different agency than their own text | **218** | 0 |
| agency ids stamped on documents that never mention them | **753** | 0 |
| identity strings failing the I3 validator | **137 titles + 34 catalog strings** | 0 |
| doc_ids whose family contradicts their `source_url` | **22** | 0 |
| non-fiscal-note titles shared by 2+ documents | **218** | 0 |
| distinct agency slugs vs catalogued agencies | **196 vs 157** | reported, not gated |

**"How many names did we produce" is never reported.** That number rises as
the rules get looser, and mistaking it for quality is the specific error the
citation work paid to learn.

The last row is reported and not gated on purpose: the 39 surplus slugs are
JLBC's own history — DES was published as eight sub-programme documents in
older years and one recently — and collapsing them would destroy real
information.

### I14 — Run it after every ingest

`eval/identity_check.py` runs at the end of the ingest queue and its
failures surface where `ingest/validate.py`'s already do. **This is what
makes the fix durable when the office ingests at volume**, which is the
question that prompted this spec. Without it, one bad upload silently
reintroduces any of the above.

---

## Architecture

A new `identity/` package. Nothing else acquires new responsibilities.

| module | one job | depends on |
|---|---|---|
| `identity/validator.py` | *does this string look like a name?* → verdict + reason (I3) | nothing |
| `identity/witnesses.py` | read the three witnesses for a document; report agreement (I1) | store, chunking |
| `identity/compose.py` | build a title from agreed witnesses (I5) | validator, witnesses |
| `identity/resolve.py` | the single read-path title resolver (I12) | store.documents |
| `identity/repair.py` | the offline pass — snapshot, lock, upsert, reversal record (I7, I8) | store, ingest.lock |
| `identity/merge_map.py` | the committed agency merge table (I9) | nothing |

**Deliberately NOT in `identity/`:** the entity stamper stays in
`chunking/`, and `build_title` stays in `ingest/`. They are correct; they
gain a validator call and a witness check, not a new home.

`eval/identity_check.py` imports `identity/` and nothing imports it back.

---

## Phases

Each phase is independently useful and independently revertible.

| # | phase | fixes | gate |
|---|---|---|---|
| **1** | `eval/identity_check.py` + the six metrics | nothing — it **measures** | numbers reproduce the audit's counts |
| **2** | `identity/validator.py`; repair the 3 catalog names + 31 variants; re-stamp | **721 documents** | `ost` error rate 72.7% → 0; every clean agency unchanged |
| **3** | Probe-ladder fix (I6) + compose (I5) + repair pass (I7/I8) | **218 + 137 titles** | 0 titles naming a different agency; **Layer 1 eval unchanged** |
| **4** | Merge the split agency ids (I9) | **6 agencies** | one id per agency; eval unchanged |
| **5** | Rename the 22 doc_ids + re-point the eval (I10) | **22 documents** | every re-point verified against `anchor_text` |
| **6** | `book_family` / `doc_kind` (I11); stop the app parsing URLs | **669 documents** | browse page identical; filter can express "Baseline sections" |
| **7** | Collapse the six naming call sites into `identity/resolve.py` (I12) | Finding 7 | browse page and AI Mode return the same title for every document |

**Phase 1 first, and not as ceremony.** All of this shipped under ~2,900
passing tests because every check is per-item and correct while **nothing
compares items to each other**. Phase 1 is that missing instrument, and
every later phase is gated on numbers it produces.

---

## Gates

- **G-I1 — Layer 1 retrieval eval.** `retrieval/` and `chunking/` are on
  the changed path from Phase 2, so `uv run python -m eval.run_eval` runs
  before and after each of Phases 2–6, with results committed.
  **A CONTROL run on the same corpus, the same day** — never a remembered
  baseline; the corpus moves under this work and a corpus delta reads
  exactly like a code regression (demonstrated 2026-08-16: recall@5 fell
  2.4 points from 140 new documents with no code change at all).
- **G-I2 — the error rates in I13 reach their targets**, each measured by
  the Phase 1 script.
- **G-I3 — no chunk_id is lost.** Count before and after every repair pass;
  they must be equal. This is the `upsert_chunks` non-atomicity hazard (I7)
  made visible.
- **G-I4 — the browse page and AI Mode agree.** One test resolving a title
  through both paths for a sample of documents. Its absence is Finding 7.

---

## Risks

| risk | why it is bounded |
|---|---|
| **A repair makes a name worse** where extraction was poor | I1's two-witness rule; a lone witness never repairs |
| **~950 names change at once** — anything quoted or bookmarked by name reads differently | I8's reversal record is the audit trail; phased so titles and labels move separately |
| **`upsert_chunks` is not atomic** | snapshot + `IngestLock` + G-I3 chunk count |
| **Merging agency ids is irreversible in the data** | Destin's explicit call; merge map committed, snapshot taken, I8 record written |
| **Renaming doc_ids breaks eval ground truth** | deterministic substitution, every entry verified against `anchor_text` (I10) |
| **Re-stamping shifts retrieval scores** | G-I1 control run each phase; agency is a *preference*, not a filter, so a stamp change cannot delete an answer |

**One measurement this work invalidates, in a good direction:** STATUS.md
records that a hard agency filter lost to a preference (88.10% → 83.33%
recall@5), and names *"any re-ingest that improves agency stamping"* as
the condition to re-measure. **Phase 2 is that condition.** Re-measuring is
NOT in scope here — it is a separate change with its own eval — but the
result is no longer trustworthy after Phase 2 and this spec is where that
is recorded.

---

## Out of scope

- **Fiscal-note version markers.** 158 notes share a title with another
  note, with no way to tell the introduced version from the amended one.
  Destin's call, 2026-08-16: excluded. Real, affects the coordinator, needs
  its own spec.
- **The FY2005–2011 slug titles** (`AXSACUTE`, `AXSADMN`). The *format* is
  right and the *name* is wrong, and the wrong name is in the harvested
  catalog itself — a slug→agency lookup, a different repair.
- **Renaming `doc_type` values** (I11).
- **Re-opening the agency filter-vs-preference decision** (above).
- **The 39 surplus agency slugs.** JLBC's own sub-programme splits and
  renames; collapsing them would destroy real information (I13).
