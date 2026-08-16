# Corpus identity consistency — design

**Status: SPEC. Approved 2026-08-16. Revised 2026-08-16 after review. Not implemented.**

Evidence: [`docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md`](../investigations/2026-08-16-identity-consistency-audit.md)
and [`…-document-title-inconsistency.md`](../investigations/2026-08-16-document-title-inconsistency.md).
Every count below is measured against the live corpus on 2026-08-16
(7,574 documents / 83,016 budget chunks / the 157-agency catalog), not
estimated.

---

## Review corrections, 2026-08-16 — read this before the decisions

Six claims in the first draft were checked against the running code and the
live corpus. **Four did not survive.** They are corrected in place below;
they are listed here because each one changed what the work IS, not merely
how it is worded.

| # | first draft said | measurement says |
|---|---|---|
| **R1** | Repairing 3 poisoned catalog names fixes 721 mis-stamped documents | **There is no bare `board of` entry in the catalog.** The audit's stated cause does not exist. The over-matcher is the *fuzzy rule*: `token_set_ratio` at cutoff 85 scores **100** for the single word `Arizona` against the Osteopathic name, and repairing the string does not remove it — for the phrase `Board of` it goes **76.9 → 100**. Repair makes it worse. See I2. |
| **R2** | Repairing stored titles fixes what the analyst sees | **`app/search_provider.py:199` prefers the vendored website index title whenever the URL joins**, and only falls back to the stored title otherwise. The wrong "Agriculture" name for the Barbers document is in `webapp/reference/assets/search/index-lite.js` and `data/jlbc-book-catalog.json` — two committed repo files. Repairing the corpus would leave the search results unchanged and the gate green. There are **three** title ladders, not two — browsing and searching differ. See I6, I12. |
| **R3** | Title repair needs a snapshot, the ingest lock, and the `upsert_chunks` hazard | **The title is not a chunk column.** `store/schema.py` has no title; titles live only in `documents.json`. Title repair is a sidecar edit: no chunk rewrite, no lock, no chunk_id risk. Only the re-stamp (Phase 2) and the doc_id rename (Phase 5) touch chunks. See I7. |
| **R4** | The 137 bad new titles are "a bullet or a bare slug" | **25 carry a bullet. The rest are correct agency names missing the suffix** — `Medical Board, Arizona`, `Physical Therapy, Board of`. They pass any name validator, so the validator cannot be the instrument that catches this class. Separately, **375 documents** (not 6) sit in a third format, `JLBC FY2025 — Agriculture, Arizona Department of`. See I3, I5, I13. |

Two smaller corrections: `app/routes/books.py:148` is not a `build_title`
call (the chain is `books.py:152` → job `user_title` → `ingest/worker.py:1154`
→ `build_title`), and `vector` is projectable only through
`ChunkStore.scan()` — `get_by_ids` and every search path drop it, so a
repair pass that round-trips through the obvious reader would write rows
missing a non-nullable field.

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
| Documents stamped as an agency they never mention | **721** | 72.7% of `agency:ost` |
| Documents carrying a different agency's name | **218** | e.g. Board of Barbers titled "Agriculture" |
| Documents missing the title suffix entirely | **131** | created 2026-08-16; names are correct, format is not |
| Documents in a third title format (`JLBC FY2025 — …`) | **375** | migration-era; none carries `ingested_at` |
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
alone is never sufficient, which is precisely today's behaviour.

**Implemented as one comparison, not a subsystem.** After the matcher fix
in I2 the document's own stamp is right on 98.5–100% of every clean
agency, so the rule that does the work is: *if the supplied title names a
different agency than the stamp, the stamp wins and the disagreement is
recorded.* That is a function on the write path, not a witness-arbitration
package.

**🔴 The URL-slug witness is silently unavailable on 1,448 documents.**
`chunking/entity_stamper.py:42` (`_JLBC_URL_RE`) recognises only
`/NNbaseline/`, `/NNar/` and `azleg.gov/jlbc/NNAR`. JLBC also published
under **`/NNapp/`** (1,294 live documents) and **`/NNbookN/`** (141), and
**965 of those have a slug that IS a catalogued agency** — the strongest
witness, discarded, on exactly the FY2005–2012 era where the mis-stamps
concentrate. `store/book_family.py::_BOOK_DIR` in the same repo already
parses `app` and `book\d*` correctly; the two modules disagree about
JLBC's URL vocabulary. **Reconciling them is part of Phase 2 and is
probably the single largest stamping win available.**

### I2 — The 721 mis-stamps are a MATCHER defect, not a catalog-string defect

**Revised 2026-08-16. The first draft's remedy was measured and rejected.**

The audit attributed the over-match to a bare `Board of` phrase acting as a
name for `agency:ost`. **No such entry exists.** The seven `ost` keys are
all long and specific; the shortest key in the entire catalog is `ahcccs`
(6 characters).

The operative mechanism is `_resolve`'s fuzzy fallback
(`entity_stamper.py:344`): `process.extractOne(cand, all_names,
scorer=token_set_ratio, score_cutoff=85)`. `token_set_ratio` compares
*token sets*, so **any candidate phrase whose tokens are a subset of a
catalog name scores 100**, regardless of how little of the name it covers.
Measured with the real scorer:

| candidate line | vs the corrupted `ost` name | vs the REPAIRED `ost` name |
|---|---|---|
| `Arizona` | **100.0** | **100.0** |
| `Medicine` | **100.0** | **100.0** |
| `Board of` | 76.9 | **100.0** |

The candidates are the first ten non-blank lines of the chunk plus its
`section_path`, so a page whose header says *Arizona* — which is most of
them — reaches a 100-way tie, and `extractOne` resolves it by **catalog
order**, not by evidence.

**Consequences that change the plan:**

1. **Repairing the three names does not fix the 721.** For `Board of` it
   makes the match *stronger*. The catalog repair is still worth doing —
   it is the string `list_filter_values` shows the model — but it belongs
   with I3, not with the stamping fix.
2. **The fix is a matcher guard**: a fuzzy match is accepted only when the
   candidate covers a substantial share of the matched name (a coverage
   floor on matched-token length against name length), and a tie at the
   ceiling is a refusal, not a first-wins pick. A refused match leaves the
   chunk unstamped, which is honest — agency is a *preference*, so an
   unstamped chunk loses a ranking nudge and nothing else.
3. **Nothing is fixed until the corpus is re-stamped.** `agency_canonical_ids`
   is a stored column written once at ingest; no read path consults the
   catalog. Editing YAML changes nothing already on disk, ever.
4. **The guard must be calibrated on measured error rates before the
   corpus-wide re-stamp**, on a sample that includes the clean agencies
   (`tre`, `gam`, `adc`, `axs` — all at 0.0% today). A guard that fixes
   `ost` by unstamping half of Corrections is a worse corpus.

### I3 — The validator QUARANTINES, and a decoration is not a quarantine

One predicate — *does this string look like a name?* — with a **reason**
attached to every rejection.

**Revised: two verdicts, not one.** The first draft said the validator
"never trims", and I6 said to strip bullets and dot leaders. Both cannot
be the rule. The distinction that survives measurement is *where* the
noise sits:

- **Decoration — stripped, deterministically, and recorded.** A leading
  bullet and a trailing run of dot leaders + page code are provably
  additive: `• State Personnel Summary by Agency ……BD-13` is the printed
  section name with the printed page reference attached. Stripping is not
  a guess, and the alternative is worse — those sections have no agency,
  so there is nothing for I5's format to compose from.
- **Corruption — quarantined, never repaired.** Noise *inside* the string
  (`Arizona ... 342 Board of`), a doubled internal space, or an over-long
  string is a question with an answer, and trimming it is a guess. If a
  string still fails after decoration-stripping, it quarantines.

Rejects, each drawn from a measured defect:

| rule | seen in |
|---|---|
| dot leaders (`..`) remaining after decoration-strip | `agency:ost`, `agency:nci` |
| an embedded page number | `ost` (342), `nci` (338), `apc` (286) |
| a doubled internal space | 3 canonical names, 31 variants, `jlbc-approps-fy2027-ost` |
| exceeds 90 characters | `ost`, `nci` |

**Two rules from the first draft are DELETED:**

- **`is all-caps with no space` — deleted.** Measured against the corpus,
  it matches exactly one stored title: `AHCCCS`, which is correct. The
  `AXSACUTE`/`DESAGE` class (20 documents) is *uninformative, not wrong*,
  and the audit says so. Uninformative names are reported by the check,
  never quarantined.
- **`contains an HTML tag` — deleted for fiscal notes, which is where all
  240 of them are.** `Fiscal Note - HB 2527: <strike>…</strike> (NOW: …)`
  is how an analyst sees an amended bill, and the app renders it
  deliberately. A validator rejecting it would quarantine every amended
  note on the next refresh — breaking a shipped feature to enforce a rule
  about a corpus this spec does not cover.

**Scope: budget documents only.** Fiscal-note titles are constructed from
the bill number and the note's own heading and have none of the three
suppliers this spec is about.

Applied at three entry points: the agency catalog on load, a budget
document title on write, and an office-added agency on save.

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

### I5 — One title format: `{Name} — FY {year} {Book}`, and it must be unique

Not a new invention. **4,950 documents already use it** — it is the
website's own format. This makes the minority match the majority.

**Revised: composition must not manufacture a collision.** A composed
title has to be unique within its (book, fiscal year). Measured: **77
documents in 30 groups** have a parent agency and one of its
sub-programmes in the same book and year (`doa` with `doa-apf` and
`doa-cfs`, `des` with `desage`/`desdd`/…). If both compose from the same
agency name they become two indistinguishable rows — a *new* defect
manufactured by the fix, and one the I13 duplicate-title metric would then
report as a failure.

Where the composed title is not unique, the distinguishing element (the
document's own slug or section heading) is kept in the name. **The 20
`AXSACUTE`-class documents are exactly this case** and are the reason they
keep their slug rather than being "repaired" into a duplicate.

### I6 — Repair the SUPPLIERS, not only the corpus

**Revised, and this is the correction that most changes the work.**

The first draft fixed stored titles. **The Budget Documents page does not
read stored titles when the document is in the vendored website index:**

```
app/search_provider.py:199
  "title": entry.get("title") if entry else _ingest_title(meta)
```

`entry` is the row from `webapp/reference/assets/search/index-lite.js`,
joined on `source_url`. That file contains, verbatim:

```
"05app/bar.pdf" → "Agriculture, Arizona Department of — FY 2005 Appropriations Report"
```

**So repairing the 218 stored titles would change nothing on the page**,
while `eval/identity_check.py` — reading `documents.json` — reported zero
errors. A green gate over an unchanged screen. Worse, AI Mode *does* read
the stored title, so between the repair and I12 the two surfaces would
**newly** disagree on exactly those 218 documents.

Three things follow:

1. **Both supplier files are repaired in the repo**, with the corrections
   generated from the documents' own stamps and committed as data:
   `webapp/reference/assets/search/index-lite.js` and
   `data/jlbc-book-catalog.json`. They are committed files the bundle
   ships, so this is a code change on the office's install cadence — not a
   share-side data repair. **Say so in the release note**; a re-stamp that
   lands on the share before the bundle lands on the PCs leaves the page
   and the answer disagreeing.
2. **Un-repaired suppliers are the recurrence path.** Without this, the
   next ingest of any pre-2013 edition re-imports "Agriculture" for
   Barbers, and I14 finds the same defect forever.
3. **The probe-ladder fix stands.** `ingest/book_discovery.py:275` and
   `:284` hand over `entry.name` / `entry.title` raw, which is why the
   2026-08-16 FY2027 ingest produced 131 names with no suffix while the
   catalog path produced 4,950 good ones. Compose the suffix there. The
   route and `build_title` are correct and are not touched — note that the
   chain runs `books.py:152` → job `user_title` → `ingest/worker.py:1154`
   → `build_title`; `books.py` never calls `build_title` itself.

### I7 — Titles need no re-ingest, and no chunk rewrite either

**Revised: the title is not a chunk column.** `store/schema.py` carries
`doc_id`, `agency_canonical_ids`, `fiscal_year`, `doc_type`, `publisher`,
`section_path` and the fund fields. **`title` is only in
`documents.json`.** A title repair is therefore a sidecar edit — atomic
tmp+replace, already the house pattern — with **no `IngestLock`, no
snapshot, no `upsert_chunks`, and no chunk_id risk at all.**

That hazard is real but belongs to the two phases that genuinely rewrite
chunks — the re-stamp (Phase 2) and the doc_id rename (Phase 5):

1. `ChunkStore.upsert_chunks` is keyed on `chunk_id` and replaces rows
   wholesale, so passage ids survive and eval ground truth with them.
2. `EntityStamper.resolve_all()` works from the chunk's own stored text.
   **No MinerU, no re-download, no re-chunking.**
3. `vector` is carried through untouched — **but only via
   `ChunkStore.scan()` with an explicit column list.** `get_by_ids` and
   every search path project it away (`chunk_store.py:107`), so a repair
   that reads through them would write rows missing a non-nullable field.

**🔴 The hazard, and it is real:** `upsert_chunks` is a delete followed by
an add, in **two separate commits**, and `write_doc` widens the window by
calling `delete_doc` first. An interruption between them leaves those
chunk_ids absent. Both chunk-rewriting phases run under `IngestLock`, take
a verified `store.backup.snapshot()` first, and are treated operationally
as an ingest.

### I8 — Every repair writes a reversal record

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

**Added guard: merge only where the two ids do not both appear in the same
fiscal year.** STATUS.md records that ASU's two ids are contiguous and
never overlap — which is what makes that merge a rename — and that the
University of Arizona's Main Campus and Health Sciences Center run in
**parallel every year** and must never be merged. Co-occurrence in one
year is the difference between a rename and two real units, and it is
checkable before the write.

**Recorded risk, since it is irreversible in the data:** this asserts that
a predecessor unit and its successor department are one agency. That is a
judgement a budget analyst may dispute. I8's reversal record and the
snapshot are what make it undoable; the merge map is committed so the
claim is visible rather than implicit.

### I10 — The 22 contradictory doc_ids are RENAMED, and the eval is re-pointed

Revised 2026-08-16 on Destin's instruction: *"if the eval is pinning a
broken thing, we should fix the eval."*

Renaming is deterministic and therefore verifiable.
`chunking/builder.py:149` mints `chunk_id = f"{doc_id}-{idx:04d}"`, so
`jlbc-baseline-fy2026-crr-0013` → `jlbc-approps-fy2026-crr-0013` is a pure
string substitution with the ordinal untouched. Verified: no rename target
collides with an existing doc_id, and **exactly one eval entry is
affected** — `eval/queries.yaml` q-001, whose `anchor_text`
(*"FY 2026 EORP employer contribution rate is 70.70%"*) either still
appears at the new chunk_id or the re-point is wrong and the run fails
loudly. `anchor_text` coverage is 51/51 and 10/10 across the two files, so
the repair path exists for every entry, not just this one.

**🔴 The cost is NOT the eval — it is saved conversations.** `doc_id` is
also a chunk column, so the rename is a full delete-and-re-add, and the
new ids appear nowhere in transcripts already on disk. Saved AI Mode
conversations persist chunk_ids in two independent places (the figure
annotation written by `citation/annotate.py`, and the verbatim `retrieve()`
JSON in `tool` messages, which `harness/history.py` explicitly refuses to
prune). Confirmed on real files: 20 stored transcripts, 42 distinct
doc_ids. After a rename, clicking such a citation returns 404 and the
panel reads **"Source no longer available"** — a hard, visible break, not a
degradation, and no migration hook exists.

**Therefore the rename ships with a transcript migration**: a one-pass
rewrite of stored conversations under the same before/after id map, run on
each machine at startup, guarded by the `version: 1` stamp the transcripts
already carry. This is the first thing that stamp has ever been for.

**Prevention already shipped** — `make_doc_id(family=…)` landed 2026-07-31,
so no new document can do this. The 22 are legacy only.

### I11 — WITHDRAWN: `book_family` / `doc_kind` are not part of this work

**Revised 2026-08-16. Removed from scope, with the reasoning kept so it is
not silently re-proposed.**

`doc_type` genuinely does mean two things at once, and
`app/search_provider.py:332` genuinely re-parses `source_url` at query time
to recover the book family. Recording `book_family` at write **would**
retire real workarounds — `store/book_family.py` and its four call sites,
the `FUSED_TOP_K` over-fetch that exists only to feed the post-rank family
filter, `ingest/driver.py`'s hand-written doc_type→family map, and
`sectionSlugsFrom` in the webapp.

It is out of scope anyway, for three reasons:

1. **No analyst can tell it happened.** Its own gate was "browse page
   identical". The read-time parse works — 0 family leakage measured
   2026-08-11.
2. **`doc_kind` is the redundant half.** `doc_type` stays load-bearing in
   the extractor routing table, the document-type registry, query
   understanding (which distinguishes "budget highlights" from "detailed
   list" — a distinction `book_family` collapses), the AI-mode tool enum,
   title humanisation, the SQL filter and 9 pinned eval dimensions. At the
   same granularity `doc_kind` is a rename touching all of them.
3. **It is a schema change over 83,016 rows with its own eval risk**, and
   it is about *classification*, not about names being wrong.

`book_family` deserves its own spec. This one is about identity.

### I12 — One identity module, used by BOTH the write and the read path

The rules live in six places today: `ingest/lance_writer.py::build_title`,
`ingest/book_discovery.py`, `app/search_provider.py`, `harness/tools.py`,
`store/documents.py::humanize_doc_id`, and the catalog loader.

**That is why the same document can be named three ways** — verified in
code. There are **three** ladders, not the two the audit found: Budget
Documents *browsing* and Budget Documents *searching* are themselves
different paths.

| rung | Search results (`search_provider.py:199`) | Browse listing (`app/routes/corpus.py:221`) | AI Mode (`harness/tools.py:135`) |
|---|---|---|---|
| 1 | website index title | **never consulted** | **never consulted** |
| 2 | sidecar title, **gated** on `ingested_at` | sidecar title, **ungated** | sidecar title, **ungated** |
| 3 | humanised doc_id | humanised doc_id | humanised doc_id |

**This sharpens R2 rather than softening it.** A sidecar repair shows up
when an analyst browses and is invisible the moment they search — the
same document, two names, one page. Searching is the primary path.

A single module that composes on write and resolves on read makes the two
surfaces structurally incapable of disagreeing.

**Revised: this ships FIRST, not last.** It is what makes every later
repair visible on the page the day it lands, and it is what lets the audit
script measure the string an analyst actually reads. Sequenced last — as
the first draft had it — the largest phase in the plan would have had no
observable effect at all (I6).

### I13 — The gate is the ERROR rate, never coverage

`eval/identity_check.py`, offline, free, seconds, over data already on
disk — the shape `eval/false_link_check.py` proved for citations.

**Revised metric set.** The first draft listed six rows; two were the same
218 documents measured twice (verified: the documents whose title names
another agency are exactly the documents sharing a title), one counted a
class the validator cannot see, and none measured what the page displays.

| metric | today | target |
|---|---|---|
| **title SHOWN by the browse page names a different agency than the document's text** | **218** | 0 |
| title shown by AI Mode differs from the title shown by the browse page | not measured | 0 |
| documents no chunk of which mentions their stamped agency | **721** (`ost`) | ≤ the clean-agency floor (0–1.5%) |
| identity strings failing the I3 validator | **34 catalog strings** | 0 |
| budget titles not in the I5 format | **506** (131 + 375) | 0 |
| non-fiscal-note titles shared by 2+ documents | **218** | 0 — *cross-check on row 1, not an independent proof* |
| doc_ids whose family contradicts their `source_url` | **22** | 0 |
| documents with an uninformative (slug) title | **20** | reported, not gated |
| distinct agency slugs vs catalogued agencies | **196 vs 157** | reported, not gated |

**"How many names did we produce" is never reported.** That number rises as
the rules get looser, and mistaking it for quality is the specific error the
citation work paid to learn.

**The stamping metric is measured per DOCUMENT, over all of its chunks and
its URL slug — never per chunk.** A per-agency PDF whose boilerplate page
does not repeat the agency's name is not a mis-stamp, and a per-chunk
version of this metric reports those as errors and can never reach zero.

The last two rows are reported and not gated on purpose: the 39 surplus
slugs are JLBC's own history — DES was published as eight sub-programme
documents in older years and one recently — and collapsing them would
destroy real information.

### I14 — Run it after every ingest

`eval/identity_check.py` runs at the end of the ingest queue and its
failures surface where `ingest/validate.py`'s already do. **This is what
makes the fix durable when the office ingests at volume**, which is the
question that prompted this spec.

**It is detection, and detection is not prevention.** Prevention is the
matcher guard (I2), the validator at the door (I3) and the repaired
supplier files (I6). Without those, this check finds the same defect after
every ingest, forever.

### I15 — A flagged document has a named destination

**New.** I2/I4 flag what cannot be repaired automatically. The first draft
said "listed for a person" and named no surface — which is the FY2024 AFR
failure the spec itself quotes: *a held document looks exactly like a
missing one*, and so does an unread flag.

Two destinations, both existing patterns:

- **Per-document, at ingest:** the queue row's advisory line, where
  `ingest/validate.py`'s "only 17% agency-stamped" warning already goes.
- **Corpus-wide, standing:** a committed `identity-report.json` written by
  `eval/identity_check.py`, surfaced in the admin page's **Needs attention**
  group beside Notices — the group defined by decision E6 of
  `2026-08-12-admin-extensions-design.md`. Where that work lands first, an
  unresolved identity finding is an issue report (E3) and inherits its
  `unresolved` → `resolved` lifecycle for free.

---

## Architecture

A new `identity/` package. Nothing else acquires new responsibilities.

| module | one job | depends on |
|---|---|---|
| `identity/validator.py` | *does this string look like a name?* → decoration-strip, then verdict + reason (I3) | nothing |
| `identity/compose.py` | build a title from the stamp; enforce uniqueness within (book, FY) (I5); record a supplier disagreement (I1) | validator, store.documents |
| `identity/resolve.py` | the single read-path title resolver (I12) | store.documents |
| `identity/repair.py` | the offline passes — sidecar edit for titles; snapshot + lock + upsert for chunks (I7, I8) | store, ingest.lock |
| `identity/merge_map.py` | the committed agency merge table (I9) | nothing |

**Dropped from the first draft: `identity/witnesses.py`.** Three-witness
arbitration is machinery for a problem the matcher guard and the stamp
already solve; what survives is one comparison inside `compose.py` (I1).

**Deliberately NOT in `identity/`:** the entity stamper stays in
`chunking/`, and `build_title` stays in `ingest/`. They are correct; they
gain a validator call and a coverage guard, not a new home.

`eval/identity_check.py` imports `identity/` and nothing imports it back.

---

## Phases

Three units, each independently useful and independently revertible. The
first draft's seven phases are collapsed; the two that had no user-visible
effect are gone (old Phase 6) or merged.

### Unit A — see it, and stop it recurring

| # | phase | fixes | gate |
|---|---|---|---|
| **A1** | `eval/identity_check.py` + the I13 metrics, measured through the REAL read paths | nothing — it **measures** | numbers reproduce the audit's counts |
| **A2** | `identity/resolve.py`; both surfaces resolve through it (I12) | Finding 7 | browse page and AI Mode return the same title for every document |
| **A3** | `identity/validator.py` (I3); repair the 3 catalog names + 31 variants; repair the two supplier files (I6) | recurrence; the string the model sees | 0 catalog strings fail; re-importing FY2005 no longer re-creates a wrong name |

**A1 first, and not as ceremony.** All of this shipped under ~2,900 passing
tests because every check is per-item and correct while **nothing compares
items to each other**. A1 is that missing instrument, and every later phase
is gated on numbers it produces. **A2 before any repair**, because
otherwise the repairs are invisible (I6/R2).

### Unit B — the names

| # | phase | fixes | gate |
|---|---|---|---|
| **B1** | Probe-ladder suffix fix (I6) + `identity/compose.py` (I5) | new ingests | a fresh book edition produces 0 titles outside the format |
| **B2** | Title repair pass — sidecar only, no lock, no snapshot (I7) | **218 + 131 + 375** | 0 titles naming a different agency **on the page**; 0 outside the format; 0 new duplicates |

### Unit C — the data mutations

Each takes `IngestLock`, a verified snapshot, and an I8 reversal record.

| # | phase | fixes | gate |
|---|---|---|---|
| **C1** | Matcher coverage guard + `_JLBC_URL_RE` reconciliation (I2), calibrated on a sample | — | on the sample: `ost` error rate falls, **and every clean agency is unchanged** |
| **C2** | Corpus re-stamp | **721 documents** | per-document error rate at the clean-agency floor; per-column before/after diff clean |
| **C3** | Merge the split agency ids (I9) | **6 agencies** | one id per agency; no merged pair co-occurs in a year; eval unchanged |
| **C4** | Rename the 22 doc_ids + re-point the eval + migrate stored transcripts (I10) | **22 documents** | q-001 verified against `anchor_text`; 0 saved citations 404 after migration |

---

## Gates

- **G-I1 — Layer 1 retrieval eval.** `retrieval/` and `chunking/` are on
  the changed path from C1, so `uv run python -m eval.run_eval` runs before
  and after each of C1–C4, with results committed.
  **A CONTROL run on the same corpus, the same day** — never a remembered
  baseline; the corpus moves under this work and a corpus delta reads
  exactly like a code regression (demonstrated 2026-08-16: recall@5 fell
  2.4 points from 140 new documents with no code change at all).
- **G-I2 — the error rates in I13 reach their targets**, each measured by
  the A1 script through the real read paths.
- **G-I3 — nothing is lost in a chunk rewrite.** Chunk_id count before and
  after must be equal **and** a per-column before/after comparison must be
  clean. Count equality alone cannot see that `agency_canonical_ids`,
  `doc_type` or `fiscal_year` was dropped — and those are the columns C2
  rewrites.
- **G-I4 — the browse page and AI Mode agree.** One test resolving a title
  through both paths for a sample of documents. Its absence is Finding 7.
- **G-I5 — no saved citation breaks.** After C4, every chunk_id referenced
  by a stored transcript resolves.

---

## Risks

| risk | why it is bounded |
|---|---|
| **The matcher guard unstamps correct chunks** | C1 is calibrated on a sample that includes the four 0.0%-error agencies; an unstamped chunk loses a ranking preference, never an answer |
| **A repair makes a name worse** where extraction was poor | I1's stamp-vs-supplier comparison; a lone witness never repairs |
| **~950 names change at once** — anything quoted or bookmarked by name reads differently | I8's reversal record is the audit trail; A2 ships first so the change is visible in one place rather than surfacing twice |
| **The supplier repair ships in the bundle, the re-stamp ships on the share** | different cadences; the release note states the order, and A2 makes a mismatch visible rather than silent |
| **`upsert_chunks` is not atomic** | snapshot + `IngestLock` + G-I3; titles avoid it entirely (I7) |
| **Merging agency ids is irreversible in the data** | Destin's explicit call; co-occurrence guard, merge map committed, snapshot taken, I8 record written |
| **Renaming doc_ids breaks saved conversations** | transcript migration + G-I5; deterministic substitution; every eval entry verified against `anchor_text` |
| **Re-stamping shifts retrieval scores** | G-I1 control run each phase; agency is a *preference*, not a filter, so a stamp change cannot delete an answer |

**One measurement this work invalidates, in a good direction:** STATUS.md
records that a hard agency filter lost to a preference (88.10% → 83.33%
recall@5), and names *"any re-ingest that improves agency stamping"* as
the condition to re-measure. **C2 is that condition.** Re-measuring is
NOT in scope here — it is a separate change with its own eval — but the
result is no longer trustworthy after C2 and this spec is where that is
recorded.

---

## Out of scope

- **`book_family` / `doc_kind`** (I11, withdrawn — it deserves its own spec).
- **Fiscal-note version markers.** 158 notes share a title with another
  note, with no way to tell the introduced version from the amended one.
  Destin's call, 2026-08-16: excluded. Real, affects the coordinator, needs
  its own spec. The fiscal-note corpus is out of scope for the validator
  too (I3).
- **The 20 FY2005–2011 slug titles** (`AXSACUTE`, `AXSADMN`). The *format*
  is right and the *name* is uninformative rather than wrong, and I5's
  uniqueness rule is the reason they keep their slug. Reported by the
  check, never quarantined.
- **Re-opening the agency filter-vs-preference decision** (above).
- **The 39 surplus agency slugs.** JLBC's own sub-programme splits and
  renames; collapsing them would destroy real information (I13).
