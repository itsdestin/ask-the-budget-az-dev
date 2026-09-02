# Structural Extraction Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When a document extracts to the right *amount* of text with its *meaning* stripped off, try the next extractor and keep the structurally better reading — instead of stopping at the first rung that clears the volume floor.

**Architecture:** A new `ingest/structure.py` measures what fraction of a document's passages are bare figures, mirroring `ingest/coverage.py`'s shape and `None` contract exactly. `ingest/worker.py::_extract_and_chunk` stops short-circuiting on a passing-but-tripped rung, records every rung's score, and picks the winner by structure among attempts of comparable size. `ingest/ladder.py`'s rung list is untouched; the OCR skip lives in the worker loop so its escape hatch survives. The admin route and page gain the numbers so a swap leaves a trace.

**Tech Stack:** Python 3.12, pytest, FastAPI, React 18 + Vite, vitest. No new dependencies — `re` and the standard library are all the measure needs.

## Global Constraints

Copied verbatim from `docs/superpowers/specs/2026-08-13-structural-extraction-quality-design.md` (revision 3). Every task's requirements implicitly include this section.

- **`MAX_UNLABELLED = 0.20`** — a **ceiling**. A document fails by scoring **above** it, the opposite direction from `COVERAGE_FLOOR`. Never name it `STRUCTURE_FLOOR`.
- **`LETTER_RATIO = 0.10`**, **`MIN_JUDGED_CHARS = 50`**, **`MIN_JUDGED_CHUNKS = 10`**, **`STRUCTURE_TIE_BAND = 0.75`**. The first three are calibrated (sweep 2026-08-13); the band is an explicit **bound, not a calibration**, and its code comment must say so.
- **`COVERAGE_FLOOR` stays `0.10`.** This plan does not touch `ingest/coverage.py`'s constant.
- **No copy anywhere — server, UI, comment or commit message — may describe a kept extraction as verified, checked, validated, healthy or good.** This measure detects one failure shape and certifies nothing. It has a live counterexample: a passage scoring a perfect 0.00% while carrying a units label wrong by a factor of 1,000.
- **Penalty-shaped, never bonus-shaped**, and **no ranking constant in `retrieval/` moves.** Nothing in this plan touches `retrieval/`, `RECENCY_BOOST_PER_YEAR`, `MATCH_PENALTY` or `REFUSAL_THRESHOLD`.
- **No corpus sweep and no re-extraction of any live document** (X8). Changing a document's extractor re-mints its `chunk_id`s and nothing re-binds eval ground truth (`eval/refresh_chunk_ids.py` was deleted). `eval/queries.yaml` contains **no** reference to `agao-afr-fy2024`, which is why Task 8 may re-process that one document by hand. **`agao-afr-fy2025` is pinned — never re-process it.**
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX weights.**
- **`unlabelled_fraction` returns `None`, never `0.0`, when it cannot judge.** `0.0` means "measured, and clean". Confusing the two makes an unjudgeable document look perfect.

---

## File Structure

| File | Responsibility |
|---|---|
| `ingest/structure.py` **(new)** | The measure and its constants. Pure text analysis: no I/O, no imports from `ingest.worker`. Sibling of `ingest/coverage.py` and deliberately shaped like it. |
| `tests/test_structure.py` **(new)** | Unit tests for the measure and the winner-picking rule. |
| `ingest/worker.py` | `ExtractionOutcome` gains `unlabelled`; the loop records it, continues past a tripped rung, picks by structure inside the band, and skips the OCR rung on a text-layer document that already has a passing reading. |
| `tests/test_worker_ladder.py` | Extends the existing scripted-ladder harness so a rung can produce digit-only chunk text. |
| `ingest/jobs.py` | `JobRecord` gains `kept_extractor: str \| None`. |
| `app/routes/admin.py` | `/api/admin/attention` returns each attempt's `unlabelled` and a new `swapped` list. |
| `webapp/src/api.ts` | Types for the two new fields. |
| `webapp/src/admin/ExtractionChanges.tsx` **(new)** | Renders the `swapped` list. Separate file from `NeedsAttention.tsx` because it reports a *success* with a trace, not a problem. |
| `webapp/src/admin/ExtractionChanges.test.tsx` **(new)** | vitest for that component. |
| `webapp/src/admin/NeedsAttention.tsx` | Renders `unlabelled` alongside `coverage` in the existing "Tried:" list. |
| `webapp/src/pages/Admin.tsx` | Mounts `ExtractionChanges`. |
| `scripts/structure_scan.py` **(new)** | The committed corpus scan (X11). Read-only; re-extracts nothing. |
| `tests/test_structure_scan.py` **(new)** | Pins that the scan is read-only and that its histogram maths is right. |

---

### Task 1: The measure

**Files:**
- Create: `ingest/structure.py`
- Test: `tests/test_structure.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `MAX_UNLABELLED: float = 0.20`, `LETTER_RATIO: float = 0.10`, `MIN_JUDGED_CHARS: int = 50`, `MIN_JUDGED_CHUNKS: int = 10`, `STRUCTURE_TIE_BAND: float = 0.75`
  - `is_unlabelled(text: str) -> bool | None`
  - `unlabelled_fraction(chunk_texts: Iterable[str]) -> float | None`
  - `choose_best(candidates: Sequence[tuple[float | None, float | None]]) -> int`

- [ ] **Step 1: Write the failing test**

Create `tests/test_structure.py`:

```python
"""The structural-quality measure (spec X1/X2/X3).

Pure text analysis -- no corpus, no models, no extractor output. Every
number here comes from the 2026-08-13 calibration recorded in the spec.
"""
from __future__ import annotations

import pytest

from ingest.structure import (
    MAX_UNLABELLED,
    STRUCTURE_TIE_BAND,
    choose_best,
    is_unlabelled,
    unlabelled_fraction,
)

# A real flagged chunk, verbatim from `agao-afr-fy2024-0033` (page 10):
# 0 letters of 697 non-whitespace characters.
BARE = (
    "34,863,017 34,863,017    -34,863,017    - - 4,423,700    -4,423,700  "
    "  - - 1,415,900    -1,415,900    - - 151,400    -151,400    - - "
    "1,661,900    -1,661,900    - - 924,400    -924,400    -"
)

# A MinerU table chunk: heading, then tab-joined rows. Heavy tab padding is
# exactly what made the naive (whitespace-counting) form score healthy AFR
# chunks at 5.5-12.9%.
LABELLED_TABLE = (
    "STATE OF ARIZONA GENERAL FUND\n"
    "NET APPROPRIATIONS\tEXPENDITURES\tLAPSED AUTHORITY\n"
    "\t200,000\t200,000\t\t\n\t1,000,000\t1,000,000\t\t\n"
)


def test_a_bare_figure_run_is_unlabelled():
    assert is_unlabelled(BARE) is True


def test_tab_padded_labelled_text_is_labelled():
    """The whitespace case the naive form gets wrong."""
    assert is_unlabelled(LABELLED_TABLE) is False


def test_a_short_chunk_is_not_judged_at_all():
    """Under MIN_JUDGED_CHARS the answer is None -- never False, which
    would claim a measurement that was not taken."""
    assert is_unlabelled("1,234") is None


def test_a_chunk_of_pure_whitespace_is_not_judged():
    assert is_unlabelled(" " * 200) is None


def test_markup_is_stripped_before_measuring():
    """A no-op on chunk text as the pipeline produces it today -- table
    markup lives on `chunk.table_html`, never in `chunk.text`. This is a
    guard against a future reader that stops parsing tables, NOT a fix for
    a defect that exists (spec X1)."""
    tagged = "<table><tr><td>" + BARE + "</td></tr></table>"
    assert is_unlabelled(tagged) is True


def test_fewer_than_ten_judged_chunks_yields_None():
    """The small-denominator trap: without this, 14 documents of 2-5 chunks
    score >= 15% because one numeric chunk out of three reads as 33%."""
    assert unlabelled_fraction([BARE] * 9) is None


def test_the_fraction_is_bare_over_judged():
    texts = [BARE] * 3 + [LABELLED_TABLE] * 7
    assert unlabelled_fraction(texts) == pytest.approx(0.3)


def test_unjudgeable_chunks_are_excluded_from_the_denominator():
    """Short chunks must not dilute the score toward zero."""
    texts = [BARE] * 3 + [LABELLED_TABLE] * 7 + ["1,234"] * 50
    assert unlabelled_fraction(texts) == pytest.approx(0.3)


def test_a_clean_document_measures_zero_not_None():
    assert unlabelled_fraction([LABELLED_TABLE] * 12) == 0.0


def test_structure_beats_coverage_inside_the_band():
    """The real measured pair: OpenDataLoader 49.03% coverage / 30.63%
    unlabelled against MinerU 44.77% / 0.00%. MinerU wins."""
    assert choose_best([(0.4903, 0.3063), (0.4477, 0.0)]) == 1


def test_structure_does_NOT_beat_coverage_outside_the_band():
    """The silent quarter-document guard. A perfectly clean attempt that
    recovered a quarter of the text loses to a tripped attempt that
    recovered all of it -- 0.12 / 0.49 = 0.24, far below the band."""
    assert choose_best([(0.49, 0.30), (0.12, 0.0)]) == 0


def test_the_band_edge_is_inclusive():
    """0.75 exactly is INSIDE the band."""
    assert choose_best([(0.40, 0.30), (0.30, 0.0)]) == 1


def test_just_outside_the_band_loses():
    assert choose_best([(0.40, 0.30), (0.29, 0.0)]) == 0


def test_coverage_breaks_a_structural_tie():
    """Preserves today's behaviour where structure says nothing."""
    assert choose_best([(0.44, 0.0), (0.49, 0.0)]) == 1


def test_an_unjudgeable_attempt_is_ranked_by_coverage():
    """`None` unlabelled means the attempt had too few judged chunks. It
    does not participate in structural ranking (spec X3)."""
    assert choose_best([(0.49, None), (0.44, None)]) == 0


def test_every_attempt_unjudgeable_still_returns_the_best_coverage():
    assert choose_best([(0.20, None), (0.90, None), (0.50, None)]) == 1


def test_an_unmeasurable_coverage_does_not_win_by_default():
    """`None` coverage is a scan-shaped accept, not a high score."""
    assert choose_best([(None, 0.0), (0.44, 0.0)]) == 1


def test_choose_best_rejects_an_empty_candidate_list():
    with pytest.raises(ValueError):
        choose_best([])


def test_the_ceiling_is_a_ceiling():
    """Documented as an executable statement so a future `<=` typo fails
    here rather than silently inverting the gate."""
    assert MAX_UNLABELLED == 0.20
    assert 0.3063 > MAX_UNLABELLED   # the known-degraded document trips
    assert 0.0714 < MAX_UNLABELLED   # the highest healthy document does not
    assert STRUCTURE_TIE_BAND == 0.75
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd ~/ask-the-budget-az-worktrees/<branch> && uv run pytest tests/test_structure.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.structure'`

- [ ] **Step 3: Write the implementation**

Create `ingest/structure.py`:

```python
"""Did this extraction keep the WORDS, or only the numbers? (spec X1/X2/X3)

`ingest/coverage.py` measures VOLUME -- how much text came out. It cannot
see a document whose text all arrived with its meaning stripped off.
`agao-afr-fy2024` scores 49.0% coverage, comfortably over the floor, while
30.6% of its passages are bare figure runs like:

    34,863,017 34,863,017    -34,863,017    - - 4,423,700 ...

Under Invariant 1 an unlabelled figure is WORSE than a missing one, because
it is still citable: a model can quote it with no way to establish whether
it is revenue, an expenditure or an ending balance, or whether it is dollars
or thousands of dollars.

## What this does NOT do

It detects ONE failure shape. A document that passes has not been checked,
verified, validated or certified, and no copy anywhere may say it has. The
counterexample is live and was measured on 2026-08-13: a MinerU table chunk
scoring a perfect 0.00% here while carrying a section heading inherited from
four pages earlier that declares "(expressed in thousands)" over
whole-dollar figures -- a 1,000x error this measure cannot see, because it
counts letters and a wrong heading is made of letters.

## Why the two odd rules are load-bearing

WHITESPACE IS EXCLUDED from the denominator. Counting it scores the four
healthy AFRs at 5.5-12.9%, because JLBC and AGAO table chunks carry heavy
tab padding that dilutes the letter ratio until a fully-labelled header
chunk reads as bare. Excluding it collapses those documents to 0.0-0.5% and
leaves the broken one unchanged at 30.6%: a ~60x separation where the naive
form gave ~2.4x.

MARKUP IS STRIPPED, and this is a FORWARD-GUARD, not a fix. Chunk text
carries no tags today on any path -- `chunking/readers/mineru_reader.py`
parses MinerU's `table_body` into rows before chunking and
`chunking/builders/table_chunk.py` keeps the original HTML on a separate
`table_html` column. Stripping costs nothing and stops a future reader that
starts passing markup through from silently inflating every letter count.
Do NOT re-document it as a defect fix; an earlier draft did, and it was
wrong about this pipeline.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

# CALIBRATED 2026-08-13 by sweeping the live 95,015-chunk corpus (both chunk
# tables -- `budget_chunks` alone omits 2,103 fiscal notes, which then score
# zero and read as catastrophically broken).
#
# LETTER_RATIO is the load-bearing number. Every value from 0.05 to 0.175
# flags exactly one document; 0.20 additionally flags two healthy JLBC
# baselines, and 0.25 flags the three healthy AGAO AFRs that are this
# spec's own control group. The plateau degrades on ONE side only, so this
# is a safe-edge pick rather than a plateau centre: 0.10 sits at double the
# margin of the 0.15 first proposed, and costs nothing measured (the known
# document scores 30.63% at every ratio from 0.05 to 0.30).
LETTER_RATIO = 0.10

# MIN_JUDGED_CHARS is INERT and that is a measurement, not a guess: 20, 30,
# 40, 50, 75, 100 and 150 all flag exactly one document, with the
# known-degraded score moving only 30.23%-30.71%. Kept at 50 because it is
# the value the original investigation used. Do not spend time tuning it.
MIN_JUDGED_CHARS = 50

# Without a minimum chunk count the signal is worthless: unrestricted, 15
# documents score >= 15% and FOURTEEN of them are 2-5 chunk documents where
# a single numeric chunk reads as 33%. A minimum of 10 removes all 14.
#
# The cost is stated plainly: 2,228 documents of 7,434 have >= 10 judged
# chunks, so ~5,200 documents are invisible to this measure entirely -- not
# judged healthy, judged not at all. A small degraded document is a real
# blind spot, not a solved problem.
MIN_JUDGED_CHUNKS = 10

# A CEILING, not a floor: a document fails by scoring ABOVE it. This is the
# opposite direction from COVERAGE_FLOOR sitting one module away, which is
# exactly how a `>` gets typed as a `<` by someone pattern-matching on the
# neighbour. 20% is the centre of a 10%-30% plateau on which every
# threshold catches the same single document; the corpus is EMPTY between
# 7.14% (the highest healthy document) and 30.63%, so this is not a
# delicate choice.
MAX_UNLABELLED = 0.20

# NOT CALIBRATED -- an explicit bound, and the only number here that was
# chosen rather than measured.
#
# It exists because "keep the attempt with the lowest unlabelled fraction"
# has no lower limit on SIZE, and COVERAGE_FLOOR is only 0.10. Without this,
# an attempt that recovered 12% of a document beats one that recovered 49%
# whenever the 12% happens to be clean -- a document quietly reduced to a
# quarter of itself, written live, with the queue green. That is a NEW
# silent failure of the same family the ladder exists to prevent.
#
# 0.75 is picked to sit visibly looser than the one measured pair (49.03%
# and 44.77%, a ratio of 0.91) and visibly tighter than the floor. A band
# that FIRES is a signal to go and measure, never to widen the band.
STRUCTURE_TIE_BAND = 0.75

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_markup(text: str) -> str:
    # Replaced with a SPACE, not the empty string: `<td>A</td><td>B</td>`
    # must not become `AB` and invent a word that was never there.
    return _TAG_RE.sub(" ", text)


def is_unlabelled(text: str) -> bool | None:
    """Is this passage almost entirely figures?

    Returns None when the passage is too short to judge -- deliberately not
    False, which would claim a measurement that was not taken.
    """
    stripped = _strip_markup(text or "")
    if len(stripped) < MIN_JUDGED_CHARS:
        return None
    non_ws = [c for c in stripped if not c.isspace()]
    if not non_ws:
        return None
    letters = sum(1 for c in non_ws if c.isalpha())
    return (letters / len(non_ws)) < LETTER_RATIO


def unlabelled_fraction(chunk_texts: Iterable[str]) -> float | None:
    """Fraction of judgeable passages that are bare figures.

    Returns None when fewer than MIN_JUDGED_CHUNKS passages could be judged.
    None means "not measured" and must never be read as 0.0, which means
    "measured, and clean" -- the same contract `coverage_ratio` uses for a
    source with no text layer, and for the same reason: a check that cannot
    see anything must not report the best possible result.
    """
    judged = 0
    bare = 0
    for text in chunk_texts:
        verdict = is_unlabelled(text)
        if verdict is None:
            continue
        judged += 1
        if verdict:
            bare += 1
    if judged < MIN_JUDGED_CHUNKS:
        return None
    return bare / judged


def choose_best(candidates: Sequence[tuple[float | None, float | None]]) -> int:
    """Index of the attempt to keep (spec X3).

    `candidates` is `(coverage, unlabelled)` per attempt, both `float |
    None`, for attempts that have ALREADY passed the coverage floor --
    filtering on the floor is the caller's job and stays exactly where it
    is today.

    Structure decides among attempts of COMPARABLE SIZE; coverage decides
    everywhere else and breaks structural ties. An attempt whose fraction
    could not be computed does not participate in structural ranking at all.
    """
    if not candidates:
        raise ValueError("choose_best requires at least one candidate")

    measured = [cov for cov, _ in candidates if cov is not None]
    best_coverage = max(measured) if measured else None

    band = [
        i
        for i, (cov, unlabelled) in enumerate(candidates)
        if unlabelled is not None
        and cov is not None
        and best_coverage is not None
        and best_coverage > 0
        and cov >= STRUCTURE_TIE_BAND * best_coverage
    ]
    if band:
        # Lowest unlabelled wins; highest coverage breaks the tie.
        return min(band, key=lambda i: (candidates[i][1], -candidates[i][0]))

    # Nothing is structurally comparable -- today's behaviour, unchanged.
    # -1.0 for an unmeasurable coverage keeps it below a genuine 0.0: a
    # crash tells us nothing, while a measured zero is a real observation.
    return max(
        range(len(candidates)),
        key=lambda i: candidates[i][0] if candidates[i][0] is not None else -1.0,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_structure.py -q`
Expected: PASS, 18 passed

- [ ] **Step 5: Verify the guard tests actually guard**

Temporarily change `STRUCTURE_TIE_BAND` to `0.0` and re-run.
Expected: `test_structure_does_NOT_beat_coverage_outside_the_band` and `test_just_outside_the_band_loses` **FAIL**.
Then change `LETTER_RATIO` to `0.9` and re-run.
Expected: `test_tab_padded_labelled_text_is_labelled` **FAILS**.
Revert both. A guard that passes against the broken version is not a guard.

- [ ] **Step 6: Commit**

```bash
git add ingest/structure.py tests/test_structure.py
git commit -m "feat: structural-quality measure — bare-figure fraction per document

Sibling of ingest/coverage.py: coverage measures how much text came out,
this measures whether it still means anything. Constants calibrated by a
corpus-wide sweep on 2026-08-13; the tie band is an explicit bound and
says so at the constant."
```

---

### Task 2: Every rung's score is recorded, always

**Files:**
- Modify: `ingest/worker.py` (the `ExtractionOutcome` dataclass ~line 367, the attempt dict ~line 471)
- Modify: `ingest/jobs.py` (`JobRecord`, after the `held_out` field)
- Test: `tests/test_worker_ladder.py`

**Interfaces:**
- Consumes: `ingest.structure.unlabelled_fraction` (Task 1).
- Produces:
  - `ExtractionOutcome.unlabelled: float | None`
  - Every dict in `job.extraction_attempts` carries an `"unlabelled"` key
  - `JobRecord.kept_extractor: str | None`

This task changes **no behaviour**. It is separated because the recording is
free, ships on its own, and is what makes Task 3 testable.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_worker_ladder.py`:

```python
def test_every_rung_that_runs_records_its_unlabelled_fraction(
    monkeypatch, ladder_job
):
    """Spec X11. Recorded for a rung that PASSES too, not only a loser --
    the near-miss band is the only path out of "calibrated against one
    example", and a threshold that never records its inputs can only be
    re-argued, never re-tuned."""
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert outcome.unlabelled == 0.0
    assert outcome.attempts[0]["unlabelled"] == 0.0


def test_a_rung_with_too_few_judged_chunks_records_None_not_zero(
    monkeypatch, ladder_job
):
    """None means "not measured". Zero would claim a perfect reading."""
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    ctx = _ctx(monkeypatch, scripted, chunks=3)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.unlabelled is None
    assert outcome.attempts[0]["unlabelled"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_worker_ladder.py -k unlabelled -q`
Expected: FAIL — `AttributeError: 'ExtractionOutcome' object has no attribute 'unlabelled'`

- [ ] **Step 3: Add the field to `ExtractionOutcome`**

In `ingest/worker.py`, add the import beside the coverage one:

```python
from ingest.structure import MAX_UNLABELLED, choose_best, unlabelled_fraction
```

Then add one field to the dataclass (after `coverage`):

```python
    coverage: float | None
    # None means NOT MEASURED (fewer than MIN_JUDGED_CHUNKS judgeable
    # passages), never "measured and clean" -- same contract as `coverage`.
    unlabelled: float | None
```

- [ ] **Step 4: Record it on every attempt**

In `_extract_and_chunk`, replace the attempt-building block:

```python
            chunks = _chunk(job, ctx, extractor=name)
            coverage, coverage_error = _measure_coverage(chunks, source)
            attempt: dict = {
                "extractor": name, "coverage": coverage, "chunks": len(chunks),
            }
```

with:

```python
            chunks = _chunk(job, ctx, extractor=name)
            coverage, coverage_error = _measure_coverage(chunks, source)
            # Recorded for EVERY rung, whether or not it trips the ceiling
            # and whether or not it changes anything (spec X11). It is
            # free -- the number is already computed -- and it is the only
            # mechanism that can ever produce a second positive example:
            # documents in the near-miss band are otherwise ignored and
            # nothing writes down that they were close.
            unlabelled = unlabelled_fraction(c.text for c in chunks)
            attempt: dict = {
                "extractor": name,
                "coverage": coverage,
                "unlabelled": unlabelled,
                "chunks": len(chunks),
            }
```

In the `except Exception` handler just below, add the key so a crashed rung's
dict has the same shape:

```python
            attempt = {
                "extractor": name, "coverage": None, "unlabelled": None,
                "chunks": 0,
                "error": f"{type(exc).__name__}: {exc}",
            }
            chunks, coverage, unlabelled = [], None, None
```

And pass it into both `ExtractionOutcome(...)` constructions in this function
(the in-loop one and the `best is None` fallback at the end) as
`unlabelled=unlabelled` and `unlabelled=None` respectively.

- [ ] **Step 5: Add `kept_extractor` to the job record**

In `ingest/jobs.py`, immediately after the `held_out` field:

```python
    # Which rung's output was actually written, set once in
    # `ingest/worker.py::run_job` after the ladder returns. Recorded
    # because a document whose extractor CHANGED has had its chunk_ids
    # re-minted and its text replaced, and a change that size leaving no
    # trace is how a corpus becomes unexplainable a year later (spec X7).
    # None for every job file written before this field existed, and for a
    # job that never got past extraction.
    kept_extractor: str | None = None
```

In `ingest/jobs.py::advance`, beside the existing `job.held_out = False`
reset on retry, add:

```python
        job.kept_extractor = None
```

In `ingest/worker.py::run_job`, immediately after the `if not outcome.passed:`
block returns — i.e. on the path where the outcome passed — add:

```python
    job.kept_extractor = outcome.extractor
```

- [ ] **Step 6: Run the whole ladder suite**

Run: `uv run pytest tests/test_worker_ladder.py tests/test_ingest_worker.py tests/test_structure.py -q`
Expected: PASS, no failures. The two new tests pass; every pre-existing test is unchanged because no decision changed.

- [ ] **Step 7: Commit**

```bash
git add ingest/worker.py ingest/jobs.py tests/test_worker_ladder.py
git commit -m "feat: record every extraction rung's unlabelled fraction

No behaviour change -- the number is computed and journalled, nothing
reads it yet. Recorded for winning rungs too: the near-miss band is the
only route to a second positive example, and the corpus currently holds
none (measured 2026-08-13, nothing between 7.14% and 30.63%)."
```

---

### Task 3: A tripped document does not stop at the first passing rung

**Files:**
- Modify: `ingest/worker.py::_extract_and_chunk`
- Test: `tests/test_worker_ladder.py`

**Interfaces:**
- Consumes: `ExtractionOutcome.unlabelled` (Task 2), `choose_best` and `MAX_UNLABELLED` (Task 1).
- Produces: no new names. `_extract_and_chunk` may now return a **passing** outcome from the end of the loop, which it never could before.

**🔴 This is three coordinated edits, not one.** An earlier draft of the spec
called it "one line". `_extract_and_chunk` today has one exit for a healthy
document (the early `return`) and one for a document where everything failed
(the `best` path, whose result `run_job` **holds out of search**). A
passing-but-tripped attempt belongs to neither. **If only the early return is
changed, a tripped document falls out of the bottom of the loop and is hidden
from search entirely — strictly worse than shipping nothing.** Step 1's second
test is the guard for exactly that.

- [ ] **Step 1: Write the failing tests**

First extend the harness so a rung can produce digit-only text. In
`tests/test_worker_ladder.py`, change `_fake_chunks` and `_ctx`:

```python
def _fake_chunks(job, count: int, total_chars: int, *, filler: str = "x") -> list[Chunk]:
    """`count` chunks whose text sums to exactly `total_chars` characters.

    `filler` decides whether those characters are LETTERS (the default --
    a structurally healthy reading) or DIGITS, which is how a rung is
    scripted to trip the structure ceiling. The chunk text is real text
    measured by the real `unlabelled_fraction`, not a handed-in score.
    """
    if count <= 0:
        return []
    per = total_chars // count
    lengths = [per] * count
    lengths[-1] += total_chars - per * count
    return [
        Chunk(
            chunk_id=f"{job.doc_id}-{i:04d}",
            doc_id=job.doc_id,
            text=filler * length,
            section_path=[],
            provenance=ChunkProvenance(page=1),
            fiscal_year=job.fiscal_year,
            doc_type=job.doc_type,
            publisher=job.publisher,
            token_count=max(1, length // 4),
        )
        for i, length in enumerate(lengths)
    ]
```

```python
def _ctx(monkeypatch, scripted, *, has_text_layer=True, chunks=3, bare=()):
    """A context whose extraction is scripted per rung.

    `bare` names the rungs whose chunk text is digits rather than letters,
    i.e. the rungs scripted to trip the structure ceiling.
    """
    source = _write_pdf(text=has_text_layer)
    total = source_text_chars(source)
    pending: dict = {}

    def fake_extract(job, ctx, *, extractor=None, method=None):
        pending["ratio"] = scripted(method)
        pending["method"] = method

    def fake_chunk(job, ctx, *, extractor):
        ratio = pending.get("ratio")
        if chunks <= 0:
            return []
        target = 200 * chunks if ratio is None else round(ratio * total)
        filler = "7" if extractor in bare else "x"
        return _fake_chunks(job, chunks, target, filler=filler)

    monkeypatch.setattr(worker, "_extract", fake_extract)
    monkeypatch.setattr(worker, "_chunk", fake_chunk)
    return WorkerContext(store=None, embedder=FakeEmbedder(), stamper=None)
```

Then the new tests:

```python
def test_a_document_over_the_ceiling_advances_to_the_next_rung(
    monkeypatch, ladder_job
):
    """Spec X4. FY2024's exact shape: rung 1 passes on VOLUME and is
    structurally useless, so the ladder keeps going instead of stopping."""
    scripted = _ScriptedLadder({"opendataloader": 0.49, "mineru": 0.4477})
    ctx = _ctx(monkeypatch, scripted, chunks=20, bare=("opendataloader",))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls[:2] == ["opendataloader", "mineru"]
    assert outcome.extractor == "mineru"
    assert outcome.passed


def test_a_tripped_document_with_nothing_better_is_STILL_WRITTEN(
    monkeypatch, ladder_job
):
    """🔴 The regression guard for the worst way this change goes wrong.

    Every rung trips the ceiling, so the loop reaches its end with no
    untripped winner. The document must still be WRITTEN -- a degraded
    reading that is the best available reading is still the best available
    reading. If this returns a failing outcome, `run_job` hides the
    document from search, and an analyst who could previously find its
    figures (badly labelled) can now find nothing at all."""
    scripted = _ScriptedLadder(
        {"opendataloader": 0.49, "mineru": 0.45, "mineru-ocr": 0.44}
    )
    ctx = _ctx(
        monkeypatch, scripted, chunks=20,
        bare=("opendataloader", "mineru", "mineru-ocr"),
    )
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.passed, "a tripped document must not be held out of search"
    assert outcome.extractor == "opendataloader"  # highest coverage, band empty
    assert len(outcome.attempts) == 3


def test_structure_picks_the_winner_among_comparable_attempts(
    monkeypatch, ladder_job
):
    """The real measured pair. Coverage prefers OpenDataLoader (49.03% vs
    44.77%) because a third of its text is the bare digit runs; structure
    prefers MinerU, and structure is right."""
    scripted = _ScriptedLadder({"opendataloader": 0.4903, "mineru": 0.4477})
    ctx = _ctx(monkeypatch, scripted, chunks=20, bare=("opendataloader",))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.extractor == "mineru"
    assert outcome.unlabelled == 0.0


def test_a_clean_attempt_that_collapsed_in_SIZE_does_not_win(
    monkeypatch, ladder_job
):
    """The silent quarter-document guard, end to end. 0.12/0.49 = 0.24 is
    far outside the 0.75 band, so the tripped-but-complete reading is
    kept."""
    scripted = _ScriptedLadder({"opendataloader": 0.49, "mineru": 0.12})
    ctx = _ctx(monkeypatch, scripted, chunks=20, bare=("opendataloader",))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert outcome.extractor == "opendataloader"


def test_a_healthy_document_still_short_circuits(monkeypatch, ladder_job):
    """What keeps 2,227 of 2,228 documents paying exactly what they pay
    today. Fails if X4 is written as "always run every rung"."""
    scripted = _ScriptedLadder({"opendataloader": 0.94})
    ctx = _ctx(monkeypatch, scripted, chunks=20)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == ["opendataloader"]
    assert outcome.extractor == "opendataloader"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_worker_ladder.py -q`
Expected: FAIL — `test_a_document_over_the_ceiling_advances_to_the_next_rung` fails with `assert ['opendataloader'] == ['opendataloader', 'mineru']` (the ladder still stops at rung 1).

- [ ] **Step 3: Change the loop**

In `ingest/worker.py::_extract_and_chunk`, add a collector beside `best`:

```python
    attempts: list[dict] = []
    best: ExtractionOutcome | None = None
    # Outcomes that CLEARED the coverage floor. Kept separately from
    # `best`, which only ever holds failures: a passing-but-tripped
    # attempt belongs to neither the early return nor the failure path,
    # and dropping it into `best` would hide the document from search.
    passing: list[ExtractionOutcome] = []
```

Replace the early-return block:

```python
        if outcome.passed:
            return outcome
        if best is None or _outcome_rank(outcome) > _outcome_rank(best):
            best = outcome
```

with:

```python
        if outcome.passed:
            passing.append(outcome)
            # A document that passes on VOLUME can still have arrived with
            # its meaning stripped off (spec X4). Only an untripped
            # passing rung short-circuits; a tripped one advances so
            # `choose_best` has something to compare it against.
            tripped = (
                outcome.unlabelled is not None
                and outcome.unlabelled > MAX_UNLABELLED
            )
            if not tripped:
                return replace(outcome, attempts=list(attempts))
        elif best is None or _outcome_rank(outcome) > _outcome_rank(best):
            best = outcome
```

Then, immediately before the existing `if best is None:` fallback at the end
of the loop, add the winner selection:

```python
    if passing:
        # Every rung that cleared the floor tripped the ceiling, or the
        # last one did. Keep the structurally best reading of comparable
        # size (spec X3). A degraded document that is the best available
        # reading is still the best available reading -- it is WRITTEN,
        # and X7 makes the choice visible.
        winner = passing[
            choose_best([(o.coverage, o.unlabelled) for o in passing])
        ]
        return replace(winner, attempts=list(attempts))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_worker_ladder.py tests/test_ingest_worker.py -q`
Expected: PASS. Every pre-existing test in both files still passes — none of them scripts a bare rung, so `unlabelled` is 0.0 throughout and every document short-circuits exactly as before.

- [ ] **Step 5: Verify the worst-case guard actually guards**

Temporarily revert only the `passing`-selection block at the end of the loop
(leave the early-return change in place) and re-run.
Expected: `test_a_tripped_document_with_nothing_better_is_STILL_WRITTEN` **FAILS** with `assert outcome.passed`. That is the "document vanishes from search" bug reproducing on demand. Restore the block.

- [ ] **Step 6: Run the full Python suite**

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: all pass, 5 skipped (the documented ONNX/model-closure skips).

- [ ] **Step 7: Commit**

```bash
git add ingest/worker.py tests/test_worker_ladder.py
git commit -m "feat: continue past a rung that passes on volume but not structure

Measured on agao-afr-fy2024: OpenDataLoader 30.63% bare-figure passages
against MinerU's 0.00%, while coverage prefers OpenDataLoader (49.03% vs
44.77%) because 186,184 of its 565,478 characters ARE the bare digit runs.

Three coordinated edits, not one. A passing-but-tripped attempt belonged
to neither existing exit, and changing only the early return drops it out
of the bottom of the loop and hides the document from search."
```

---

### Task 4: The OCR rung is skipped when the document has a real text layer

**Files:**
- Modify: `ingest/worker.py::_extract_and_chunk` (the rung loop)
- Test: `tests/test_worker_ladder.py`

**Interfaces:**
- Consumes: `inspection` (already in scope in `_extract_and_chunk`), `passing` (Task 3).
- Produces: no new names.

**Why this lives in the worker and not in `ingest/ladder.py`:** `ladder_for`
returns the rung list up front and cannot see whether an earlier rung passed.
The escape hatch — *if everything failed, run OCR anyway* — needs that, so the
skip is a guard inside the loop and `ladder_for` is untouched.

- [ ] **Step 1: Write the failing tests**

```python
def test_the_ocr_rung_is_skipped_when_the_document_has_a_text_layer(
    monkeypatch, ladder_job
):
    """Spec X12. Measured on agao-afr-fy2024: mineru-ocr produced 353,002
    characters against mineru's 353,141 and the same 13% bare pages -- a
    full extraction to change essentially nothing. OCR earns its cost on a
    SCAN, and a document with a text layer is not one."""
    scripted = _ScriptedLadder({"opendataloader": 0.49, "mineru": 0.45})
    ctx = _ctx(monkeypatch, scripted, chunks=20,
               bare=("opendataloader", "mineru"))
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == ["opendataloader", "mineru"]
    assert "mineru-ocr" not in scripted.calls
    assert outcome.passed


def test_a_scan_still_reaches_the_ocr_rung(monkeypatch, ladder_job):
    """The test that keeps scans working. A blank PDF makes
    `inspect_source` report a POSITIVE has_text_layer=False, and
    `ladder_for` returns ["mineru-ocr"] alone for it."""
    scripted = _ScriptedLadder({"mineru-ocr": None})
    ctx = _ctx(monkeypatch, scripted, has_text_layer=False, chunks=20)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == ["mineru-ocr"]
    assert outcome.passed


def test_ocr_still_runs_when_every_earlier_rung_FAILED_the_floor(
    monkeypatch, ladder_job
):
    """The escape hatch. With nothing passing, the document is being held
    out of search anyway and OCR is the last thing that might rescue it --
    text layer or not. The skip applies only where a usable reading is
    already in hand."""
    scripted = _ScriptedLadder(
        {"opendataloader": 0.01, "mineru": 0.02, "mineru-ocr": 0.9}
    )
    ctx = _ctx(monkeypatch, scripted, chunks=20)
    outcome = worker._extract_and_chunk(ladder_job, ctx)

    assert scripted.calls == ["opendataloader", "mineru", "mineru-ocr"]
    assert outcome.extractor == "mineru-ocr"
    assert outcome.passed
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_worker_ladder.py -k ocr -q`
Expected: FAIL — `test_the_ocr_rung_is_skipped_when_the_document_has_a_text_layer` fails, `scripted.calls` includes `mineru-ocr`.

- [ ] **Step 3: Add the guard**

In `_extract_and_chunk`, at the very top of the `for index, name in enumerate(rungs):` body, before the `recorded = prior.get(name)` line:

```python
        if (
            name == "mineru-ocr"
            and inspection.has_text_layer is True
            and passing
        ):
            # Spec X12. Measured on the one document this plan exists for:
            # mineru-ocr produced 353,002 characters against mineru's
            # 353,141 and the same 13% bare pages -- a full extraction,
            # roughly 30 minutes on a 191-page book, to change nothing.
            #
            # `is True`, NOT truthiness. `has_text_layer` is `bool | None`
            # and None means the inspector COULD NOT TELL, which is not the
            # same as "there is a text layer". Skipping on an unknown would
            # quietly remove the rescue path from every document the
            # inspector could not read -- disproportionately the damaged
            # ones. `ingest/ladder.py` tests `is False` for the mirror
            # image of this reason.
            #
            # `and passing` is the escape hatch: with nothing above the
            # floor the document is being held out of search anyway, so
            # OCR is the last thing that might rescue it.
            continue
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_worker_ladder.py -q`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Verify the scan guard guards**

Temporarily change `inspection.has_text_layer is True` to
`inspection.has_text_layer is not False`. Re-run.
Expected: no test fails — **this is the point**. Now change it to
`not inspection.has_text_layer` (the truthiness bug) and re-run:
`test_a_scan_still_reaches_the_ocr_rung` **FAILS**. Restore `is True`.
Record in the commit message that the `None` case has no test because the
scripted harness cannot produce an uninspectable PDF; the comment is the guard.

- [ ] **Step 6: Commit**

```bash
git add ingest/worker.py tests/test_worker_ladder.py
git commit -m "feat: skip the OCR rung on a document that has a real text layer

Measured: mineru-ocr produced 353,002 characters against mineru's
353,141 on agao-afr-fy2024, with the same 13% bare pages -- ~30 minutes
to change nothing. Skipped only when a passing reading is already in
hand, so a document with nothing above the floor still gets its last
chance, and only on a POSITIVE has_text_layer finding, never on None."
```

---

### Task 5: The admin route reports what was tried and what was kept

**Files:**
- Modify: `app/routes/admin.py::get_attention` (~lines 900-937)
- Test: `tests/test_admin_attention.py` (append; if the file does not exist, create it with the same imports the neighbouring admin route tests use)

**Interfaces:**
- Consumes: `job.extraction_attempts[*]["unlabelled"]`, `job.kept_extractor` (Task 2).
- Produces: `GET /api/admin/attention` returns
  - each `documents[*].attempts[*]` with an added `"unlabelled": float | None`
  - a new top-level `"swapped": [{job_id, title, kept, attempts}]`

- [ ] **Step 1: Write the failing test**

```python
def test_attention_reports_each_attempt_s_unlabelled_fraction(tmp_path, monkeypatch):
    """Spec X7. Both numbers per rung, because they disagree: the whole
    reason this feature exists is a document where coverage said 49% and
    structure said 30.63% bare."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    job = _held_out_job(
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.05,
             "unlabelled": 0.31, "chunks": 20},
            {"extractor": "mineru", "coverage": 0.04,
             "unlabelled": None, "chunks": 3},
        ]
    )
    body = _call_attention(job)

    tried = body["documents"][0]["attempts"]
    assert tried[0]["unlabelled"] == 0.31
    assert tried[1]["unlabelled"] is None


def test_a_document_whose_extractor_CHANGED_is_listed_as_swapped(
    tmp_path, monkeypatch
):
    """A swap re-mints chunk_ids and replaces the document's text. A
    change that size leaving no trace is how a corpus becomes
    unexplainable a year later."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    job = _live_job(
        kept_extractor="mineru",
        attempts=[
            {"extractor": "opendataloader", "coverage": 0.49,
             "unlabelled": 0.31, "chunks": 388},
            {"extractor": "mineru", "coverage": 0.45,
             "unlabelled": 0.0, "chunks": 450},
        ],
    )
    body = _call_attention(job)

    assert len(body["swapped"]) == 1
    row = body["swapped"][0]
    assert row["kept"] == "mineru"
    assert [a["extractor"] for a in row["attempts"]] == [
        "opendataloader", "mineru"
    ]


def test_a_document_kept_on_its_FIRST_rung_is_not_listed_as_swapped(
    tmp_path, monkeypatch
):
    """Nothing changed, so there is nothing to explain. A list that fills
    up with ordinary uploads teaches an admin to scroll past it."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    job = _live_job(
        kept_extractor="opendataloader",
        attempts=[{"extractor": "opendataloader", "coverage": 0.94,
                   "unlabelled": 0.0, "chunks": 200}],
    )
    body = _call_attention(job)

    assert body["swapped"] == []
```

Write the three helpers at the top of the test file (or reuse the existing
job-building helper if the file already has one):

```python
def _held_out_job(*, attempts):
    from ingest.jobs import new_job, save
    job = new_job(
        doc_id="agao-afr-fy2024", title="FY 2024 Annual Financial Report",
        corpus="budget", source_path="uploads/x.pdf", source_sha256="ab" * 32,
        publisher="agao", doc_type="afr", fiscal_year=2024,
    )
    job.state = "failed"
    job.held_out = True
    job.error = "Held out of search — only 5% of this document's text produced any content, after 2 extraction methods were tried."
    job.extraction_attempts = attempts
    save(job)
    return job


def _live_job(*, kept_extractor, attempts):
    from ingest.jobs import new_job, save
    job = new_job(
        doc_id="agao-afr-fy2024", title="FY 2024 Annual Financial Report",
        corpus="budget", source_path="uploads/x.pdf", source_sha256="ab" * 32,
        publisher="agao", doc_type="afr", fiscal_year=2024,
    )
    job.state = "live"
    job.kept_extractor = kept_extractor
    job.extraction_attempts = attempts
    save(job)
    return job


def _call_attention(job):
    """Call the route function directly, past the admin gate.

    `require_admin` is a FastAPI dependency; calling `get_attention` with an
    explicit Settings object bypasses it, which is what every other admin
    route test in this suite does.
    """
    from app.routes.admin import get_attention
    from harness.settings import Settings
    return get_attention(Settings())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_admin_attention.py -q`
Expected: FAIL — `KeyError: 'swapped'` and `KeyError: 'unlabelled'`.

- [ ] **Step 3: Extend the route**

In `app/routes/admin.py::get_attention`, replace the attempts projection:

```python
            "attempts": [
                {"extractor": a.get("extractor"), "coverage": a.get("coverage")}
                for a in job.extraction_attempts
            ],
```

with:

```python
            "attempts": [
                {
                    "extractor": a.get("extractor"),
                    "coverage": a.get("coverage"),
                    # Both numbers, because they DISAGREE: this whole
                    # feature exists because one document read 49% on
                    # coverage and 30.63% bare on structure. `.get` rather
                    # than `[...]` -- job files written before the field
                    # existed have no such key and must not 500 the page.
                    "unlabelled": a.get("unlabelled"),
                }
                for a in job.extraction_attempts
            ],
```

Then, immediately before the `return`, build the second list:

```python
    # Documents the ladder SAVED by changing extractor (spec X7). Not an
    # alert -- these are successes -- but a swap re-mints every chunk_id
    # and replaces the document's text, and a change that size leaving no
    # trace is how a corpus becomes unexplainable a year later.
    #
    # A job kept on its FIRST rung is not listed: nothing changed, so
    # there is nothing to explain, and a list that fills up with ordinary
    # uploads teaches an admin to scroll past it.
    swapped = []
    for job in jobs:
        attempts = job.extraction_attempts
        kept = job.kept_extractor
        if job.state != "live" or not kept or len(attempts) < 2:
            continue
        if attempts[0].get("extractor") == kept:
            continue
        swapped.append({
            "job_id": job.job_id,
            "title": job.title,
            "kept": kept,
            "attempts": [
                {
                    "extractor": a.get("extractor"),
                    "coverage": a.get("coverage"),
                    "unlabelled": a.get("unlabelled"),
                }
                for a in attempts
            ],
        })
    swapped.sort(key=lambda row: row["title"])

    return {"documents": documents, "swapped": swapped, "error": error}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_admin_attention.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/admin.py tests/test_admin_attention.py
git commit -m "feat: admin route reports each rung's structure score and any swap

Both numbers per rung, because they disagree — the case this exists for
read 49% on coverage and 30.63% bare on structure. A document kept on a
LATER rung is listed separately: the swap re-minted its chunk_ids and
replaced its text, and that must leave a trace."
```

---

### Task 6: The admin page shows it

**Files:**
- Modify: `webapp/src/api.ts` (the `AttentionAttempt` interface ~line 790, the `adminAttention` return type ~line 819)
- Create: `webapp/src/admin/ExtractionChanges.tsx`
- Create: `webapp/src/admin/ExtractionChanges.test.tsx`
- Modify: `webapp/src/admin/NeedsAttention.tsx` (the "Tried:" list ~line 111)
- Modify: `webapp/src/pages/Admin.tsx` (state ~line 69, fetch ~line 126, render ~line 346)

**Interfaces:**
- Consumes: `GET /api/admin/attention` → `{documents, swapped, error}` (Task 5).
- Produces: `ExtractionChanges({ documents }: { documents: api.SwappedDocument[] })`

- [ ] **Step 1: Write the failing test**

Create `webapp/src/admin/ExtractionChanges.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExtractionChanges } from "./ExtractionChanges";

const SWAP = {
  job_id: "j1",
  title: "FY 2024 Annual Financial Report",
  kept: "mineru",
  attempts: [
    { extractor: "opendataloader", coverage: 0.4903, unlabelled: 0.3063 },
    { extractor: "mineru", coverage: 0.4477, unlabelled: 0.0 },
  ],
};

describe("ExtractionChanges", () => {
  it("renders nothing at all when no document changed method", () => {
    const { container } = render(<ExtractionChanges documents={[]} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("names the method that was kept", () => {
    render(<ExtractionChanges documents={[SWAP]} />);
    expect(screen.getByTestId("adm-swap-kept")).toHaveTextContent("MinerU");
  });

  it("shows both numbers for every method tried", () => {
    render(<ExtractionChanges documents={[SWAP]} />);
    const rows = screen.getAllByTestId("adm-swap-attempt");
    expect(rows).toHaveLength(2);
    expect(rows[0]).toHaveTextContent("OpenDataLoader");
    expect(rows[0]).toHaveTextContent("49%");
    expect(rows[0]).toHaveTextContent("31%");
    expect(rows[1]).toHaveTextContent("MinerU");
    expect(rows[1]).toHaveTextContent("0%");
  });

  it("renders an unmeasured structure score as words, never as 0%", () => {
    render(
      <ExtractionChanges
        documents={[{ ...SWAP, attempts: [
          { extractor: "mineru", coverage: 0.5, unlabelled: null },
        ] }]}
      />
    );
    expect(screen.getByTestId("adm-swap-attempt")).toHaveTextContent(
      "not measured"
    );
  });

  it("never describes the kept reading as verified, checked or healthy", () => {
    const { container } = render(<ExtractionChanges documents={[SWAP]} />);
    const text = container.textContent ?? "";
    for (const banned of [
      "verified", "checked", "validated", "healthy", "good",
    ]) {
      expect(text.toLowerCase()).not.toContain(banned);
    }
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd webapp && npx vitest run src/admin/ExtractionChanges.test.tsx`
Expected: FAIL — cannot resolve `./ExtractionChanges`

- [ ] **Step 3: Add the types**

In `webapp/src/api.ts`, add `unlabelled` to `AttentionAttempt`:

```ts
export interface AttentionAttempt {
  extractor: string;
  coverage: number | null;
  /** Fraction of this reading's passages that are bare figures. `null`
   *  means NOT MEASURED (fewer than 10 judgeable passages) -- never render
   *  it as 0%, which would claim the best possible reading was taken.
   *  Optional so fixtures written before this field existed keep
   *  compiling. */
  unlabelled?: number | null;
}
```

Add the new interface below `AttentionDocument`:

```ts
/** A document the ladder SAVED by changing extraction method. Not a
 *  problem — a success with a trace. Listed because a swap re-mints every
 *  chunk_id and replaces the document's text. */
export interface SwappedDocument {
  job_id: string;
  title: string;
  /** The rung whose output was written. */
  kept: string;
  attempts: AttentionAttempt[];
}
```

And extend `adminAttention`'s return type:

```ts
export async function adminAttention(): Promise<{
  documents: AttentionDocument[];
  /** Optional so a server that predates this field keeps type-checking;
   *  the call site defaults it to []. */
  swapped?: SwappedDocument[];
  error?: string | null;
}> {
```

- [ ] **Step 4: Write the component**

Create `webapp/src/admin/ExtractionChanges.tsx`:

```tsx
import * as api from "../api";

// Documents where the extraction ladder kept a LATER method than the one
// it started with (spec X7).
//
// Renders NOTHING when the list is empty — the same rule as NoticesPanel
// and NeedsAttention above it, and the same reasoning: a box that is on
// screen every day teaches an admin to scroll past it.
//
// This is a RECORD, not an alert. Nothing here may say a document was
// verified, checked, validated, healthy or good: the measure behind these
// numbers detects one failure shape and certifies nothing. A passage
// scoring a perfect 0% has been observed carrying a units label wrong by a
// factor of 1,000.
const EXTRACTOR_LABELS: Record<string, string> = {
  opendataloader: "OpenDataLoader",
  mineru: "MinerU",
  "mineru-ocr": "MinerU (OCR)",
};

function extractorLabel(name: string): string {
  return EXTRACTOR_LABELS[name] ?? name;
}

/** A ratio as a percentage. Never capped at 100% — a coverage above 1.0 is
 *  a real, normal reading (healthy AFRs score 278–286%). `null`/undefined
 *  reads as "not measured", never as 0%. */
function pct(value: number | null | undefined): string {
  if (value === null || value === undefined) return "not measured";
  return `${Math.round(value * 100)}%`;
}

export function ExtractionChanges({
  documents,
}: {
  documents: api.SwappedDocument[];
}) {
  if (documents.length === 0) return null;

  return (
    <div className="adm-swaps" data-testid="adm-swaps">
      {documents.map((doc) => (
        <div className="adm-swap" key={doc.job_id} data-testid="adm-swap">
          <p className="adm-attention-title">{doc.title}</p>
          <p className="adm-swap-kept" data-testid="adm-swap-kept">
            Read with {extractorLabel(doc.kept)}
          </p>
          <p className="adm-attention-tried-label">
            Tried, with how much text came out and how much of it was
            figures with no words:
          </p>
          <ul className="adm-attention-tried">
            {doc.attempts.map((attempt, i) => (
              <li
                key={`${attempt.extractor}-${i}`}
                data-testid="adm-swap-attempt"
              >
                <span>{extractorLabel(attempt.extractor)}</span>
                <span>{pct(attempt.coverage)}</span>
                <span>{pct(attempt.unlabelled)}</span>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </div>
  );
}
```

- [ ] **Step 5: Run the component test**

Run: `cd webapp && npx vitest run src/admin/ExtractionChanges.test.tsx`
Expected: PASS, 5 tests

- [ ] **Step 6: Show the structure score in the existing "Tried:" list**

In `webapp/src/admin/NeedsAttention.tsx`, change the attempt row:

```tsx
                <li key={`${attempt.extractor}-${i}`}>
                  <span>{extractorLabel(attempt.extractor)}</span>
                  <span>{pct(attempt.coverage)}</span>
                  {/* The second number is how much of what came out was
                      figures with no words. It is shown beside coverage
                      rather than instead of it because the two DISAGREE:
                      the document this feature exists for read 49% on
                      coverage and 31% bare on structure. `pct` renders an
                      absent value as "not measured" -- job files written
                      before this field existed have no such key. */}
                  <span>{pct(attempt.unlabelled)}</span>
                </li>
```

- [ ] **Step 7: Mount it on the Admin page**

In `webapp/src/pages/Admin.tsx`:

State, beside the existing `attention` state (~line 69):

```tsx
  const [swapped, setSwapped] = useState<api.SwappedDocument[]>([]);
```

In the initial load, where `api.adminAttention()` resolves (~line 126) and in
`attentionAction` (~line 254), add beside the existing `setAttention(a.documents)`:

```tsx
      setSwapped(a.swapped ?? []);
```

Render, immediately after the existing `<Group title="Needs attention">` block
(~line 346):

```tsx
        <Group title="Extraction method changed">
          <ExtractionChanges documents={swapped} />
        </Group>
```

And the import at the top:

```tsx
import { ExtractionChanges } from "../admin/ExtractionChanges";
```

- [ ] **Step 8: Run the whole webapp suite and the production build**

Run: `cd webapp && npx vitest run && npx tsc -b && npm run build`
Expected: all vitest pass; `tsc -b` exit 0; build succeeds.
Note `tsc -b` is stricter than `tsc --noEmit` and rejects unused imports the dev check allows.

- [ ] **Step 9: Commit**

```bash
git add webapp/src/api.ts webapp/src/admin/ExtractionChanges.tsx \
        webapp/src/admin/ExtractionChanges.test.tsx \
        webapp/src/admin/NeedsAttention.tsx webapp/src/pages/Admin.tsx
git commit -m "feat: admin page shows every method tried and which was kept

Both numbers per rung, side by side, because they disagree. A pinned
spec asserts no copy here says verified, checked, validated, healthy or
good — the measure detects one failure shape and certifies nothing."
```

---

### Task 7: The committed corpus scan

**Files:**
- Create: `scripts/structure_scan.py`
- Test: `tests/test_structure_scan.py`

**Interfaces:**
- Consumes: `ingest.structure.unlabelled_fraction`, `store.chunk_store.ChunkStore.scan`.
- Produces: `scan(store) -> dict` with keys `documents`, `judgeable`, `over_ceiling`, `near_miss`, `scores`.

**Why this is in the plan at all:** X11 records scores for documents ingested
from now on. The corpus that exists was built by a backfill that is finished, so
"wait for a second example" has no date on it. This scan reads chunks already on
disk, re-extracts nothing, re-mints nothing, and is therefore outside X8's
prohibition entirely.

- [ ] **Step 1: Write the failing test**

Create `tests/test_structure_scan.py`:

```python
"""The committed corpus scan (spec X11).

No real LanceDB directory and no ONNX weights: the store is a stub whose
`scan` returns rows, which is what keeps this suite runnable on a fresh
clone.
"""
from __future__ import annotations

from scripts.structure_scan import scan

BARE = "1" * 200
WORDS = "budget appropriation general fund " * 6


class _FakeStore:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.asked = []

    def scan(self, name, columns, **kwargs):
        self.asked.append((name, tuple(columns)))
        return self.rows_by_table.get(name, [])


def _rows(doc_id, bare, clean):
    return (
        [{"doc_id": doc_id, "text": BARE} for _ in range(bare)]
        + [{"doc_id": doc_id, "text": WORDS} for _ in range(clean)]
    )


def test_the_scan_reads_BOTH_chunk_tables():
    """budget_chunks alone omits 2,103 fiscal notes, which then score zero
    and read as catastrophically broken -- the exact error that wrecked
    the first pass of the coverage calibration."""
    store = _FakeStore({})
    scan(store)
    assert [name for name, _ in store.asked] == [
        "budget_chunks", "fiscal_note_chunks"
    ]


def test_the_scan_projects_only_two_columns():
    """It must not drag vectors out of the store."""
    store = _FakeStore({})
    scan(store)
    assert store.asked[0][1] == ("doc_id", "text")


def test_a_document_over_the_ceiling_is_reported():
    store = _FakeStore({"budget_chunks": _rows("bad", bare=7, clean=13)})
    result = scan(store)
    assert result["over_ceiling"] == [("bad", 0.35)]


def test_a_document_under_the_ceiling_is_not_reported():
    store = _FakeStore({"budget_chunks": _rows("ok", bare=1, clean=19)})
    result = scan(store)
    assert result["over_ceiling"] == []


def test_a_small_document_is_counted_but_never_judged():
    """The small-denominator trap, at scan level."""
    store = _FakeStore({"budget_chunks": _rows("tiny", bare=3, clean=0)})
    result = scan(store)
    assert result["documents"] == 1
    assert result["judgeable"] == 0
    assert result["over_ceiling"] == []


def test_the_near_miss_band_is_reported_separately():
    """The whole reason to commit this: a document just under the ceiling
    is the second example the corpus does not currently have."""
    store = _FakeStore({"budget_chunks": _rows("close", bare=2, clean=18)})
    result = scan(store)
    assert result["near_miss"] == [("close", 0.1)]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_structure_scan.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.structure_scan'`

- [ ] **Step 3: Write the script**

Create `scripts/structure_scan.py`:

```python
"""Score every document in the corpus with the structural measure (spec X11).

READ-ONLY. It reads chunk text already on disk; it extracts nothing,
embeds nothing, writes nothing to the corpus and re-mints no chunk_id. That
is why it sits outside X8's no-sweep rule entirely.

WHY IT IS COMMITTED rather than left as a throwaway. `ingest/worker.py`
records a score for every rung it runs from now on -- but the corpus that
exists was built by a backfill that is finished, so waiting for new
ingests to produce a second positive example is a plan with no date on it.
This scan answers the same question about the documents already here.

What it said when it was first run, 2026-08-13, against 95,015 chunks:
ONE document over the ceiling (`agao-afr-fy2024`, 30.63%), and the
near-miss band EMPTY -- nothing at all between 7.14% and 30.63%. Two
consequences worth keeping: the ceiling is not a delicate choice, and the
"calibrated against one example" risk is NOT retired by this scan and can
only be retired by genuinely new documents.

Usage:
    JLBC_DATA_DIR=... uv run python -m scripts.structure_scan
"""
from __future__ import annotations

from collections import defaultdict

from ingest.structure import MAX_UNLABELLED, unlabelled_fraction

# The bottom of the near-miss band. Not a threshold anything acts on --
# a reporting boundary, chosen to sit just under the highest healthy
# document measured (7.14%) so the band shows anything that is unusual
# without listing every table-dense budget document.
NEAR_MISS_FLOOR = 0.05

TABLES = ("budget_chunks", "fiscal_note_chunks")


def scan(store) -> dict:
    """Score every document. `store` is anything with ChunkStore's `scan`."""
    texts: dict[str, list[str]] = defaultdict(list)
    for table in TABLES:
        # Two columns only -- never drag vectors out of the store.
        for row in store.scan(table, ["doc_id", "text"]):
            texts[row["doc_id"]].append(row.get("text") or "")

    scores: dict[str, float] = {}
    for doc_id, chunk_texts in texts.items():
        fraction = unlabelled_fraction(chunk_texts)
        if fraction is not None:
            scores[doc_id] = fraction

    over = sorted(
        (d, f) for d, f in scores.items() if f > MAX_UNLABELLED
    )
    near = sorted(
        (d, f) for d, f in scores.items()
        if NEAR_MISS_FLOOR <= f <= MAX_UNLABELLED
    )
    return {
        "documents": len(texts),
        "judgeable": len(scores),
        "over_ceiling": over,
        "near_miss": near,
        "scores": scores,
    }


def main() -> None:
    from store.chunk_store import ChunkStore

    result = scan(ChunkStore())
    print(f"documents            {result['documents']:,}")
    print(f"judgeable (>=10)     {result['judgeable']:,}")
    print(f"over the {MAX_UNLABELLED:.0%} ceiling  {len(result['over_ceiling'])}")
    for doc_id, fraction in result["over_ceiling"]:
        print(f"    {fraction:>7.2%}  {doc_id}")
    print(f"near-miss band       {len(result['near_miss'])}")
    for doc_id, fraction in result["near_miss"]:
        print(f"    {fraction:>7.2%}  {doc_id}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_structure_scan.py -q`
Expected: PASS, 6 tests

- [ ] **Step 5: Run it for real against the dev corpus**

Run: `JLBC_DATA_DIR=<repo>/data/insight-data uv run python -m scripts.structure_scan`
Expected: `documents 7,4xx`, `judgeable 2,228`, **one** document over the ceiling (`agao-afr-fy2024` at 30.63%), and a near-miss band holding exactly **one** document, `jlbc-baseline-fy2018-545` (6.25%).

**🔴 Corrected 2026-08-13, during execution.** An earlier draft of this step
also expected `jlbc-baseline-fy2020-531` at 7.14%. That figure was measured at
a letter ratio of **0.15**; the shipped ratio is **0.10**, at which the same
document scores **0.00%**. The implementer who hit the mismatch correctly
stopped and reported rather than adjusting the code — which is what this step's
own instruction asks for, and the reason the instruction is there.
If the numbers differ, **stop and report** — the corpus moved, and the constants were calibrated against the numbers above.

- [ ] **Step 6: Commit**

```bash
git add scripts/structure_scan.py tests/test_structure_scan.py
git commit -m "feat: committed corpus scan for the structural measure

Read-only: reads chunk text already on disk, re-extracts nothing and
re-mints no chunk_id, so it sits outside the no-sweep rule. Answers the
near-miss question for documents already in the corpus, which the
per-ingest recording cannot — the backfill is finished."
```

---

### Task 8: Acceptance — re-process the one document, and READ it

**Files:** none modified. This task produces a written result, and may produce a `STATUS.md` entry.

**Interfaces:**
- Consumes: everything above.

**🔴 Do not re-process any document other than `agao-afr-fy2024`.** It is the
only one verified absent from `eval/queries.yaml`. `agao-afr-fy2025` is pinned
by six ground-truth chunk ids and nothing re-binds them.

- [ ] **Step 1: Run the Layer 1 eval BEFORE touching the corpus**

Run: `JLBC_DATA_DIR=<repo>/data/insight-data uv run python -m eval.run_eval`
Expected: recall@5 88.10%, recall@15 100%, recall@20 100%, refusal precision 60%.
This is the control. Record the results filename.

- [ ] **Step 2: Re-process the document through the running app**

Start the server (`uv run uvicorn app.main:create_app --factory --port 9300`),
then re-process `agao-afr-fy2024` from the admin queue.

Expected sequence, each observable on the queue page:
1. OpenDataLoader runs, passes the coverage floor at ~49%, and **trips** the ceiling at ~31%
2. The queue says another method is running
3. MinerU runs and scores ~0% unlabelled
4. **`mineru-ocr` never runs** (X12)
5. The document goes `live` with `kept_extractor = "mineru"`
6. It appears under "Extraction method changed" with both numbers for both rungs

- [ ] **Step 3: READ the kept chunks — the count is not the gate**

```bash
JLBC_DATA_DIR=<repo>/data/insight-data uv run python -c "
from store.chunk_store import ChunkStore
rows = ChunkStore().scan('budget_chunks', ['chunk_id','page','text'],
                         where=\"doc_id = 'agao-afr-fy2024'\")
for r in sorted(rows, key=lambda r: (r['page'] or 0))[:12]:
    print('---', r['chunk_id'], 'page', r['page'])
    print((r['text'] or '')[:400]); print()
"
```

**The honest expected outcome is BETTER, NOT FIXED.** With chunk-dropping
deferred, some figures remain hard to attribute:
- Page 9/10 is one landscape spread. MinerU recovers page 10's column headers where OpenDataLoader emitted pure digits — a real win — but the line-item names live in the page-9 chunk and are not joined to it.
- At least one chunk carries a section heading declaring `(expressed in thousands)` over whole-dollar figures. **This is the known chunker defect** (8 wrong passages in 80,854 corpus-wide, measured 2026-08-13), it is a follow-up, and it is not caused by this plan.
  > 🔴 **AMENDED 2026-08-16, and the second half of that sentence turned out to be false.** Task 8 ran, and the swap to MinerU took this document from 0 wrong labels to **122**, corpus-wide 8 → 151 — this plan's own change is what caused it. The defect is also NOT in `_build_outline`; a bounded version was shipped and reverted after measuring zero effect. Real site: `chunking/builders/table_chunk.py::_resolve_section_path`. See the amendment at the top of the spec. **Fixed 2026-09-01** (`owner_path`; corpus repaired in place — `STATUS.md` → *Table section paths*).

**If the kept chunks are no better than today's, STOP and report rather than tuning the ceiling.**

- [ ] **Step 4: Re-run the eval and compare**

Run: `JLBC_DATA_DIR=<repo>/data/insight-data uv run python -m eval.run_eval`
Expected: **identical to Step 1.** `eval/queries.yaml` has no `agao-afr-fy2024` ground truth, so re-minting its chunk ids cannot move Layer 1. **Any movement is a finding to explain, not noise** — most likely a query whose ground truth silently depended on that document ranking somewhere.

- [ ] **Step 5: Run every suite**

```bash
uv run pytest -q 2>&1 | tail -3
cd webapp && npx vitest run 2>&1 | tail -3 && npx tsc -b && npm run build
```
Expected: pytest all pass with 5 skipped; vitest all pass; `tsc -b` exit 0; build clean.

- [ ] **Step 6: Commit the eval results and the outcome**

```bash
git add eval/results/
git commit -m "eval: Layer 1 unmoved by the structural-extraction change

Control run before re-processing agao-afr-fy2024 and the run after are
identical, as expected — queries.yaml holds no ground truth for that
document. Gate G1 passes."
```

- [ ] **Step 7: Update STATUS.md**

Add a section recording: what shipped, the measured before/after (30.63% → 0.00% unlabelled on the one document), the constants and where they were calibrated, that `mineru-ocr` no longer runs on text-layer documents, and the two things deliberately left open — chunk-dropping (X5/X6) and the chunker heading-inheritance defect (8 passages, its own follow-up). **State that a passing structure score certifies nothing**, with the units-label counterexample, so the next reader does not mistake it for a health check.

---

## Self-Review

**Spec coverage:**

| Spec decision | Task |
|---|---|
| X1 — the measure | 1 |
| X2 — ceiling + minimum chunk count | 1 |
| X3 — structure picks the winner, inside the band | 1 (rule), 3 (wiring) |
| X4 — tripped document does not stop early | 3 |
| X5 / X6 — dropping chunks | **deferred by the spec** — no task, and Task 8 Step 7 records that |
| X7 — administrator sees which rung won | 5 (server), 6 (page) |
| X8 — new ingests + deliberate re-processing only | Global Constraints; enforced by Task 8's single-document rule |
| X9 — coverage floor unchanged | Global Constraints; no task touches `ingest/coverage.py` |
| X10 — sample probe | **withdrawn by the spec** — no task |
| X11 — every attempt's score recorded | 2 (per-ingest), 7 (the corpus scan) |
| X12 — skip OCR on a text-layer document | 4 |

**Placeholder scan:** none — every code step carries the actual code, every command carries its expected output, and the two "verify the guard guards" steps name the exact edit and the exact test that must fail.

**Type consistency:** `unlabelled_fraction` returns `float | None` in Task 1 and is consumed as `float | None` in Tasks 2, 5 and 7. `choose_best` takes `Sequence[tuple[float | None, float | None]]` in Task 1 and is called with `[(o.coverage, o.unlabelled) for o in passing]` in Task 3 — matching. `kept_extractor` is `str | None` in Task 2, read as `job.kept_extractor` in Task 5, typed `kept: string` in Task 6 (never null there, because Task 5 skips rows where it is falsy). `AttentionAttempt.unlabelled` is optional in TypeScript and `.get()`-defaulted on the server, so job files predating the field render as "not measured" rather than crashing.

**One gap found and closed during review:** X12's `None` (uninspectable) case has no automated test, because the scripted harness builds real PDFs and cannot produce a file PyMuPDF fails to inspect. Task 4 Step 5 substitutes a mutation check that proves the truthiness bug would be caught, and the code comment carries the reasoning. Recorded rather than papered over.
