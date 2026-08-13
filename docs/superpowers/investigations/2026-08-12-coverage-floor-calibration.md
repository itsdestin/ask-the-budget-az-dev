# Coverage-floor calibration — the T6 measurement, run corpus-wide

**Date:** 2026-08-12
**Spec:** `docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md` (T6)
**Corpus:** 7,434 documents / 80,486 budget chunks / 14,161 fiscal-note chunks
(post orphan-recovery repair, commits `c1b43f9` + `52e74d9`)

T6 fixes the floor at "expected 15–25%" from a **16-document sample** and
requires the measure be run corpus-wide before a floor is chosen: *"A floor
chosen from 16 documents and shipped without that step is a guess wearing a
number."* This is that run.

**Result: the floor is 10%, and the spec's 15–25% expectation is too high.**

---

## Method

Coverage ratio = characters of chunk text produced ÷ characters in the source
file's own text layer (PyMuPDF). Every one of the 7,434 documents in
`documents.json` was scored; **0 unresolved sources, 0 unreadable files**.

The controls are the spec's own: the four AGAO Annual Financial Reports —
same publisher, near-identical page counts, one of them known-broken.

---

## The distribution

| percentile | coverage |
|---|---|
| p0.1 | 24.9% |
| p1 | 50.2% |
| p5 | 65.6% |
| p25 | 79.0% |
| p50 | **87.9%** |
| p75 | 97.6% |
| p95 | 100.0% |

**Ratios above 100% are normal and must not be capped.** The healthy AFRs
score 278–286% because chunk text carries table markup the source's text
layer does not. This is a proxy for extraction health, **not** "fraction of
the document captured."

## The controls separate by two orders of magnitude

| document | coverage | chunks / pages | |
|---|---|---|---|
| `agao-afr-fy2021` | 278.6% | 177 / 163 | healthy |
| `agao-afr-fy2022` | 286.0% | 190 / 178 | healthy |
| `agao-afr-fy2023` | 281.0% | 198 / 184 | healthy |
| **`agao-afr-fy2024`** | **2.0%** | **20 / 191** | **known broken** |

## What each candidate floor catches

| floor | docs below | share of corpus |
|---|---|---|
| 2% | 2 | 0.03% |
| 5% | 2 | 0.03% |
| **10%** | **2** | **0.03%** |
| 15% | 2 | 0.03% |
| 20% | 3 | 0.04% |
| 25% | 8 | 0.11% |

**Every floor from just above 2.0% to just below 17.1% catches an identical
set of two documents.** The lowest-scoring real document after the broken AFR
sits at **17.1%** — a 15-point band containing nothing at all.

**10% is the plateau CENTRE**, which is the right pick here because the metric
degrades on *both* sides: below 2.0% the known-broken AFR escapes, and above
17.1% the floor starts catching short documents that are fine. (Contrast the
recency weight, where lower was always safe and the safe *edge* was correct.)

**Spec Risk 2 is closed.** At 10%, **2 documents of 7,434 (0.03%)** would ever
pay for a fallback. The "fallback doubles extraction time" cost is real per
document and negligible in aggregate.

## The two documents a 10% floor catches

Both were read, not counted.

1. **`agao-afr-fy2024` — 2.0%, genuinely broken.** The document this whole
   design exists for. Correctly caught.
2. **`legislature-fiscal-note-fy2016-hb2003-27` — 0.0%, zero chunks.**
   Not an extraction failure: **azleg.gov published a literal test file.** Its
   entire text layer is 323 characters reading `BILL # HB 2003 / SPONSOR:
   xxxxxxx / THIS IS A TEST`. A floor correctly quarantines it, and it is the
   worked example for why T8 needs a human dismissal path — no amount of
   re-extraction will improve it.

---

## 🔴 Three findings that change how T6 must be implemented

### 1. The corpus has TWO chunk tables, and the check must sum the right one

The first pass of this measurement summed `budget_chunks` only. Every one of
the 2,104 fiscal notes therefore scored **0.0%**, and **28.3% of the corpus
read as catastrophically broken** when nothing whatsoever was wrong with it.

Caught only by reading the list of low scorers instead of counting it — the
entire bottom of the table was fiscal notes in a suspiciously perfect block.
The coverage check must resolve a document's own table before dividing, and
that deserves a test.

### 2. 🔴 The ratio catches catastrophic loss, NOT corruption — a known blind spot

A volume ratio cannot see a document that produced the right *amount* of the
*wrong* text. The evidence is on this corpus: `agao-afr-fy2024`'s recovered
chunks are flattened table rows (`‐ (2,600) 8,021,000 7,981,822 ‐39,178`)
whose figures have lost their row labels, and a numeric-density heuristic
scored them **1.6% "junk"** — apparently clean — because they are full of
agency and fund names.

**T6 must be described and documented as a catastrophic-failure detector.**
A document that passes the floor has not been certified as good, and the
implementation must not imply otherwise in copy the analyst reads. This is
also why T8's human surface is not optional.

### 3. `jlbc-baseline-fy2013-s1` is FIXED and is no longer a re-route candidate

`STATUS.md` records it as a second broken document awaiting Plan B's extractor
re-route. **That is now wrong.** The orphan-recovery fix repaired it: 8 → 16
chunks, coverage 1.03% → **97.6%**, and chunks 0008–0015 are ~14,140
characters of real substantive prose. Its first 8 chunks remain garbled
heading fragments (`Federal 59 uirements`, `FY 20l3`), which is a minor
extraction-quality issue in headings only.

**`agao-afr-fy2024` is the only document Plan B's ladder must recover.**

---

## Reproducing this

The scripts are not committed — they are a one-shot measurement, and the
inputs (the live corpus) are not in the repo. The method is fully specified
above: sum `len(text)` per `doc_id` across **both** chunk tables, divide by
`sum(len(page.get_text()))` over the source PDF resolved by joining
`documents.json`'s `source_blob_path` **to the data dir**.

⚠ `source_blob_path` is stored **sharded** (`pdfs/4d/4d2a….pdf`). A first
attempt reconstructed it from the basename and silently resolved only **378 of
7,434** documents — exactly the migration-era entries, which use a different
layout. Join the recorded path; do not rebuild it.
