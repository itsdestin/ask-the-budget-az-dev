# Identity consistency audit — how the same thing gets named more than one way

> ## ⚠ CORRECTED 2026-08-16 — read this before Finding 1
>
> **This audit's stated ROOT CAUSE for Finding 1 is wrong**, and the finding
> itself is right. The work it prompted is built and applied; the outcome is
> in `STATUS.md` under "Corpus identity — names and agency labels repaired".
>
> Finding 1 blames `agency:ost`'s corrupted `canonical_name` — a
> table-of-contents row — on the theory that the standalone phrase
> `Board of` therefore acts as a name for that agency. **There is no bare
> `Board of` entry in the catalog**; its shortest key is `ahcccs` (6 chars).
> Repairing all three corrupted names changes the labelling outcome on 300
> sampled mis-labelled chunks by **zero**, and for the phrase `Board of` the
> repaired name scores *higher* (76.9 → 100).
>
> The real cause is `_resolve`'s fuzzy fallback, which scored with
> `rapidfuzz.token_set_ratio` at cutoff 85. That compares token **sets**, so
> any candidate whose tokens are a subset of a catalog name scores 100
> regardless of coverage — the single word `Arizona` scored **100** against
> the Osteopathic entry. `extractOne` then broke the resulting tie by catalog
> order. Fixed by scoring with `token_sort_ratio` (which scores those 14 and
> 16 while keeping genuine matches at 88–98) and refusing ties.
>
> **Two other numbers here were also measured differently:** Finding 2's
> "137 documents named by a bullet or a bare slug" is really 25 bullets plus
> ~112 correct names missing the format suffix, and a further **375**
> documents sit in a third title format this audit does not mention. The
> counts of *documents affected* were sound; the characterisations were not.
>
> Everything else in this document held up.


> **STATUS: this is the EVIDENCE. The approved design is
> [`../specs/2026-08-16-corpus-identity-consistency-design.md`](../specs/2026-08-16-corpus-identity-consistency-design.md)**
> (I1–I14, seven phases, approved 2026-08-16). No implementation plan
> exists yet and nothing is built. Where this document's closing "The fix"
> section and the spec differ, **the spec wins** — two decisions moved
> after Destin reviewed it: split agency ids are merged in the DATA rather
> than grouped at read time, and the 22 contradictory doc_ids are RENAMED
> with the eval re-pointed rather than read around.

**Measured 2026-08-16** against the live corpus: 7,566 documents,
83,016 budget chunks, the 157-agency catalog. Prompted by the title
inconsistency in
[`2026-08-16-document-title-inconsistency.md`](2026-08-16-document-title-inconsistency.md),
which turned out to be the smallest member of a family.

Every number below is measured, not estimated. Reproduce any of them with
`store.chunk_store.ChunkStore().scan("budget_chunks", [...])` plus
`data/insight-data/documents.json`.

---

## The headline

**One mechanism produces every defect in this document:**

> An identity string — an agency's name, a document's title, a document
> type — is accepted from **somebody else's rendering of a PDF** and is
> never checked against the document itself.

The three suppliers are JLBC's website index (link text), the harvested
book catalog built from it, and PDF text extraction of a table of
contents. All three emit strings that *look* like names and sometimes are
not: bullets, dot leaders, page numbers, all-caps slugs, and — worst —
the **previous** entry's name.

Nothing in the pipeline asks "does this string look like a name?", and
nothing asks "does this name agree with what the document says it is?"
The document itself is the one witness never consulted, even though it
opens with the answer: *"Board of Barbers  Executive Director: Mario J.
Herrera"*.

---

## What is NOT wrong — checked first

These were the obvious duplication hypotheses and the corpus is clean on
all of them. Worth recording so nobody re-audits them.

| check | result |
|---|---|
| Same bytes (sha256) under more than one doc_id | **0** |
| Same `source_url` under more than one doc_id | **0** |
| Same (book, year, agency slug) under more than one doc_id | **0** |
| Stamped agency ids that are not in the catalog | **0** |
| Documents with a missing `fiscal_year` | **0** |

**Ingest de-duplication works.** No document is in the corpus twice. Every
problem below is about what things are *called*, not about duplicates.

---

## 🔴 Finding 1 — 721 documents are stamped as an agency they never mention

**The largest and most consequential finding, and it is not about titles.**

`agency:ost` — the **Board of Osteopathic Examiners**, a small regulatory
board — is stamped on **992 documents**, more than any other agency in the
corpus:

| id | agency | documents |
|---|---|---|
| **`agency:ost`** | **Osteopathic Examiners** | **992** |
| `agency:doa` | Administration | 615 |
| `agency:ade` | Education | 605 |
| `agency:axs` | AHCCCS | 506 |
| `agency:adc` | Corrections | 376 |

A board like this should appear in ~23 documents, one per fiscal year.

**Error rate, measured by scanning the documents' own text:**

| stamp | documents | never mention the agency | error rate |
|---|---|---|---|
| **`agency:ost`** | 992 | **721** | **72.7%** |
| `agency:apc` (Parents Commission) | 28 | 24 | 85.7% |
| `agency:nci` (Nursing Care Institution Admin.) | 72 | 8 | 11.1% |
| `agency:tre` Treasurer | 489 | 0 | 0.0% |
| `agency:gam` Gaming | 401 | 0 | 0.0% |
| `agency:adc` Corrections | 376 | 0 | 0.0% |
| `agency:axs` AHCCCS | 506 | 0 | 0.0% |
| `agency:deq` Environmental Quality | 461 | 7 | 1.5% |

**Stamping is not generally weak — three specific catalog entries are
poisoned.** Every clean agency sits at 0–1.5%.

### Root cause: a table-of-contents line was saved as an agency's name

`samples/entity-catalog.yaml`, `agency:ost`, `canonical_name`:

```
Osteopathic Examiners in Medicine and Surgery, Arizona ...   342  Board of........................................................................
```

That is a TOC row — dot leaders, page number 342, and the name wrapped
onto a second line. The matcher therefore treats the standalone phrase
**"Board of"** as a name for this agency, and **every "… Board of …"
document in 23 years of budget books matches it.** Observed live:
Appraisal, Nursing, Physical Therapy, Opticians, Cosmetology all stamped
Osteopathic.

Two more entries carry the same shape:

| id | canonical_name |
|---|---|
| `agency:nci` | `…Assisted Living   338  Facility Managers, Board of E` |
| `agency:apc` | `Parents Comm. on Drug Education and Prevention, Arizona  286` |

**3 of 157 canonical names, and 31 of 219 name variants, carry a PDF
artefact** (dot leaders, an embedded page number, or a doubled space).

STATUS.md records removing a bare `'Board of'` entry **query-side** during
the query-understanding work. That fixed what a typed search resolves to.
**The canonical_name itself was never repaired, and it is what stamped the
corpus** — so the damage is in the data and survives until a re-stamp.

### Why it matters

Agency is a retrieval *preference*, so this does not delete answers. It
promotes 721 irrelevant documents whenever anyone asks about a board, and
it makes the agency facet a lie for `ost`. It also means the
**agency-filter-vs-preference decision recorded in STATUS.md was measured
on poisoned data** — the note there says to re-measure "after any
re-ingest that improves agency stamping", and this is that condition.

---

## 🔴 Finding 2 — 218 documents carry another agency's name

`jlbc-approps-fy2005-bar` is titled **"Agriculture, Arizona Department
of — FY 2005 Appropriations Report"**. Its own first line reads *"Board of
Barbers, Executive Director: Mario J. Herrera"*.

**109 title strings are shared by 2+ non-fiscal-note documents, covering
218 documents.** Verified against the documents' text:

| doc_id | titled | actually is |
|---|---|---|
| `…fy2005-bar` | Agriculture, Arizona Department of | Board of Barbers |
| `…fy2005-rac` | Pioneers' Home, Arizona | Department of Racing |
| `…fy2005-ata` | Administrative Hearings, Office of | Automobile Theft Authority |
| `…fy2006-wei` | Arizona State University – East Campus | Weights and Measures |
| `…fy2020-cos` | Citizens Clean Election Commission | Board of Cosmetology |
| `…fy2015-ins` | Historical Society of AZ, Prescott | Department of Insurance |

**It is not a one-off.** `bar` is mis-titled in FY2005, 2006, 2007, 2014,
2015, 2016 — every year it appears.

**The catalog is where it comes from**, confirmed by reading
`data/jlbc-book-catalog.json`: it records `bar` → *"Agriculture, Arizona
Department of"*. The harvest of JLBC's index page picked up the **previous
row's** label — the classic scrape off-by-one when a row has no link text.

**This is the most serious defect in this document for trust**, because
the wrong name is what a citation displays. An analyst citing *"Agriculture
— FY 2005 Appropriations Report"* is looking at the Barbers Board. That is
Invariant 1 territory: provenance that names the wrong source is worse
than no provenance.

**And the fix is free**: the agency stamp on these documents is *correct*
(`agency:bar`, `agency:rac`, `agency:ata`). The document already knows who
it is. Only the title — the one field taken from a third party — is wrong.

### The broader measurement

Comparing every per-agency document's title against its own majority
agency stamp: **613 of 4,684 (13.1%)** share no distinctive word. Reading
a random sample of 22 splits them three ways:

| shape | example | verdict |
|---|---|---|
| Title names a **different real agency** | `bar` → "Agriculture" | 🔴 the defect above |
| Title is a **raw slug** | `AXSACUTE`, `DESAGE`, `DOAHUM`, `DESC&F` | uninformative, not wrong |
| **The stamp** is wrong, not the title | anything stamped `ost` | Finding 1 |

The three overlap, so 13.1% is the union and not a clean count of any one.
**A proper split needs the audit script proposed at the end** — that is
precisely the instrument this codebase does not have.

---

## 🔴 Finding 3 — one agency, up to four ids, splitting its own corpus

Grouping catalog entries by name (token multiset, since the catalog writes
both "Child Safety, Department of" and "Department of Child Safety"):

| agency | ids | chunks each |
|---|---|---|
| **Child Safety** | `dcs` / `cs` / `doa-csf` / `doa-cfs` / `doacfs` | 1595 / 520 / 19 / 0 / 0 |
| **Arizona State University** | `uniasu` / `uniasum` | 1353 / 80 |
| **Water Infrastructure Finance Authority** | `wif` / `wifa` | 192 / 130 |
| **Equal Opportunity** | `oco` / `oeo` | 209 / 118 |
| **Constable Ethics** | `cet` / `cna` | 84 / 34 |
| **Revenue** | `dor` / `rev` | 1204 / 0 |

**6 groups.** STATUS.md records fixing this **query-side** — typing "child
safety" resolves to every id in the group, and that works. Two things it
does not fix:

1. **`list_filter_values`, the tool AI Mode uses to discover what agencies
   exist, emits raw ids with no grouping** (`harness/tools.py:816`). The
   model sees `agency:cs`, `agency:dcs` and `agency:doa-csf` as three
   agencies and, picking one, gets **24 documents instead of 265**.
2. The corpus stays split, so any future per-agency count is wrong.

### And the slugs disagree with the ids

**196 distinct agency slugs for 157 catalogued agencies.** The extra 39 are
JLBC's own history:

- **Sub-programme splits that were later consolidated.** `des` (32 years)
  vs `desage`, `desdd`, `desemp`, `descs`, `descyf`, `desltc`, `desc&f` —
  DES was published as eight documents in older years and one recently.
  The same is true of `ade` (`adeboe`, `adegs`, `adenf`), `dhs`
  (`dhsash`, `dhsfam`, `dhspub`), `doa` (7 sub-slugs), `axs`, `dot`.
- **The same division under two spellings**: `desc&f` / `descf`,
  `doa-apf` / `doaapf`, `doa-cfs` / `doacfs`.
- **Renames**: `wif` → `wifa`, `uniasu` → `uniasue`.

**Consequence an analyst will hit:** comparing DES across years compares
a whole department to one of its divisions, and nothing on screen says so.

---

## 🟡 Finding 4 — 158 fiscal notes are indistinguishable on screen

**86 bills have more than one note in the same session**, and **77 title
strings are shared by 158 notes**:

```
Fiscal Note - SB 1452: Arizona empowerment scholarships accounts; revisions   ×3
Fiscal Note - HB 2134: critical infrastructure; foreign adversaries…          ×3
```

These are legitimately different documents — introduced, engrossed,
amended versions of one bill — and AI Mode has an explicit
Engrossed-supersedes-Introduced rule in its prompt. **But the title
carries no version marker**, so a coordinator sees three identical rows
and cannot tell which is current without opening each.

Where a version *is* distinguishable it is because raw markup leaked into
the title: `Fiscal Note - HB 2527: <strike>tax subtraction…</strike>`.
The app renders that safely, but the stored identity string contains HTML.

---

## 🟡 Finding 5 — `doc_type` holds two different ideas at once

| doc_type | count | what it actually is |
|---|---|---|
| `approps-per-agency` | 2,905 | a real type |
| `baseline-per-agency` | 1,879 | a real type |
| `fiscal-note` | 2,104 | a real type |
| **`detailed-list-pdf`** | **310** | **a page-number prefix** |
| **`s-pdf`** | **187** | **a page-number prefix** |
| **`bd-pdf`** | **117** | **a page-number prefix** |
| **`bh-pdf`** | **35** | **a page-number prefix** |
| **`topic-pdf`** | **20** | **a page-number prefix** |

**669 documents are filed under JLBC's printed page prefix** (BD-10, S-1)
rather than under what kind of document they are. And the prefixes do not
partition cleanly by book:

| doc_type | in the Appropriations Report | in the Baseline |
|---|---|---|
| `detailed-list-pdf` | 244 | 62 |
| `topic-pdf` | 15 | 5 |
| `s-pdf` | 11 unknown | 176 |

So `doc_type` **cannot express "Baseline summary sections"** — already
worked around in `app/search_provider.py` by parsing `source_url`, but
the underlying field still conflates *which book* with *what kind*.

---

## 🟡 Finding 6 — doc_id family disagrees with the source URL, 22 times

The `make_doc_id` collision class STATUS.md records as **6 documents** is
**22** when checked against every document's own `source_url`:

```
jlbc-approps-fy2022-473  →  https://www.azjlbc.gov/22baseline/473.pdf
jlbc-approps-fy2023-467  →  https://www.azjlbc.gov/23baseline/467.pdf
…  (FY2022 ×5, FY2023 ×3, FY2024 ×4, FY2025 ×2, FY2026 ×3, FY2027 ×4)
jlbc-baseline-fy2026-crr →  https://www.azjlbc.gov/26AR/crr.pdf
```

The earlier audit only looked at FY2026/FY2027. **The id says one book and
the URL says the other, in every year from 2022 on.** Because a write is an
upsert, a colliding id silently *replaces* a document — the failure mode
that fix exists to prevent. It is latent today (they happen not to collide)
and it fires on any from-scratch rebuild.

---

## 🟢 Finding 7 — the browse page and AI Mode name documents differently

| rung | Budget Documents (`app/search_provider.py:236`) | AI Mode (`harness/tools.py:1035`) |
|---|---|---|
| 1 | website index title | — **never consulted** |
| 2 | sidecar title, gated on `ingested_at` | sidecar title, **ungated** |
| 3 | humanised doc_id | humanised doc_id |

Both gaps are deliberate and commented. But **a document can be called one
thing on the page and another inside an answer**, and there is no test
that compares the two.

---

# The fix: stop trusting strangers' strings

Six defects, one cause. The robust answer is not six patches — it is to
make identity **derived, cross-checked, and quarantined when the witnesses
disagree**. Four layers, cheapest first, each useful alone.

## Layer 1 — one validator, at every point a name enters

A single shared predicate — *does this string look like a name?* — applied
to agency catalog names, document titles, and office-added agencies.

It rejects what all six findings have in common:

| reject | seen in |
|---|---|
| dot leaders (`..`) | `ost`, `nci`, today's `• …………` titles |
| an embedded or trailing page number | `ost` (342), `apc` (286), `nci` (338) |
| a leading bullet (`•`) | 21 titles created today |
| doubled internal spaces | 3 catalog names, 31 variants |
| HTML tags | 158 fiscal-note titles |
| all-caps with no space | `AXSACUTE`, `DESAGE`, `DOAHUM` |
| over ~90 characters | `ost`, `nci` |

**It must QUARANTINE, never silently repair.** A stripped string is a
guess; a rejected one is a question with an answer. This is the same
posture as the S27 chunks-per-page gate and the existing "only 17%
agency-stamped" warning — both of which have already caught real defects.

**Effort: small.** One module, one predicate, three call sites. It would
have blocked Findings 1 and 5 at the source and today's 131 titles.

## Layer 2 — derive identity from the document, not from the link to it

Every document opens by naming itself:

```
Board of Barbers   Executive Director: Mario J. Herrera
Arizona Department of Racing   Director: Geoffrey Gonsher
```

The corpus already extracts and stamps this, and **the stamp was right in
every Finding-2 case where the title was wrong.** So a title composed as
`{agency the document says it is} — FY {year} {book}` is correct on all
218, uses the format 4,946 documents already use, and needs no new data.

**The catch, and it is why Layer 3 exists:** where the *stamp* is the
broken witness (Finding 1), composing from it would propagate the error
into the title. Derivation alone is not enough.

## Layer 3 — three witnesses, and disagreement is a finding

Every JLBC document has three independent statements of what it is:

| witness | example | fails when |
|---|---|---|
| **the URL slug** | `/05app/bar.pdf` → `bar` | JLBC reuses or retires a slug |
| **the document's own text** | *"Board of Barbers"* | extraction is poor |
| **the external index** | catalog title | the scrape shifts a row |

Today each is used alone in a different place. **Requiring two to agree
turns every finding here into a caught error rather than shipped data:**

- `bar` — slug says barbers, text says Barbers, index says Agriculture →
  **2 to 1, index loses, and it is flagged.**
- `ost` — 721 documents whose text never says "osteopathic" →
  **flagged, one entry, not 721 investigations.**
- today's 131 — index has no entry at all →
  **compose from the other two rather than accept a bullet.**

This is not new machinery. `ingest/validate.py` already runs advisory
post-ingest checks and already surfaces them on the queue row.

## Layer 4 — one identity module, read AND write

The rules are currently in six places: `ingest/lance_writer.py::build_title`,
`ingest/book_discovery.py`, `app/search_provider.py`,
`harness/tools.py`, `store/documents.py::humanize_doc_id`, and the
catalog loader. **Finding 7 is what that costs** — two surfaces, two
precedences, no test comparing them.

One module that both composes a title on write and resolves one on read
makes them structurally incapable of disagreeing.

## Layer 5 — an audit script, gated on the ERROR rate

The reason all of this shipped green under 2,900 tests is that **every
check is per-item and correct; nothing compares items to each other.**
That is exactly the lesson the citation work paid for: coverage rose as
the matcher loosened, and the honest gate was the false-link rate.

Build `eval/identity_check.py` — the queries in this document, as a
committed script — reporting:

| metric | today |
|---|---|
| documents whose title names a different agency than their own text | **218** |
| agency ids stamped on documents that never mention them | **753** |
| identity strings failing the Layer-1 validator | **~140 + 34** |
| doc_ids whose family disagrees with their source URL | **22** |
| non-fiscal-note titles shared by 2+ documents | **218** |
| distinct agency slugs vs catalogued agencies | **196 vs 157** |

Every one is computable offline, free, in seconds, against data already on
disk — the same property that made the citation false-link check worth
building. **Run it after every ingest**, and the office's own uploads
cannot quietly reintroduce any of this.

---

## Suggested order

| # | work | fixes | cost |
|---|---|---|---|
| 1 | **Repair the 3 poisoned catalog names + re-stamp** | Finding 1 (721 docs) | catalog edit is minutes; re-stamp needs a re-ingest decision |
| 2 | **The audit script** (Layer 5) | measures everything | half a day, free to run |
| 3 | **The validator** (Layer 1) | stops all of it recurring | small |
| 4 | **Compose titles from the document** (Layer 2) + fix the probe ladder | Findings 2 + today's 131 | small; metadata-only re-title, **verified** |
| 5 | **Cross-check + quarantine** (Layer 3) | catches the next one | medium |
| 6 | **One identity module** (Layer 4) | Finding 7 | medium |
| 7 | Fiscal-note version markers; `doc_type` split; the 22 doc_ids | Findings 4, 5, 6 | separate decisions |

**#1 and #2 first.** #1 is the largest live error and is three lines of
YAML plus a decision about re-stamping. #2 is what turns every other item
from an opinion into a number, and it is the thing whose absence let all
six of these ship.
