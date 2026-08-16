# Corpus identity — fixing the agency labels (implementation plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every document's agency label correct, then apply the title repair that depends on it — so a document's name and its agency both say what the document actually is.

**Architecture:** The label comes from `chunking/entity_stamper.py`'s resolution ladder. Two rungs are broken: the URL rung silently ignores two of JLBC's four directory conventions, and the fuzzy text rung scores a full match for a single shared word. Both are fixed and calibrated against a per-agency error rate before anything is written. Then the corpus is re-labelled in place — no re-download, no re-extraction, no re-embedding — and the previously-blocked half of the title repair is applied on top.

**Tech Stack:** Python 3.12 (`uv`), pytest, LanceDB via `store/`, rapidfuzz, PyYAML.

**Scope:** The third group of the spec at
[`docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md`](../specs/2026-08-16-corpus-identity-consistency-design.md)
— decisions **I2, I9, I10**, gates **G-I1, G-I3, G-I5** — plus applying the
title repair built by
[`2026-08-16-corpus-identity-consistency-units-a-b.md`](2026-08-16-corpus-identity-consistency-units-a-b.md),
which is code-complete and deliberately unapplied.

> **Naming.** The spec calls these groups Unit A / B / C. This repo already
> has "Phases" and "Plans 1–7", and a third lettering scheme earns nothing.
> Task 12 renames them in the spec to **measure it** / **fix the titles** /
> **fix the labels**. This plan is *fix the labels*.

---

## Global Constraints

Copied verbatim from the spec, the previous plan, and `CLAUDE.md`. Every
task's requirements implicitly include this section.

- **Gate on the ERROR rate, never coverage.** How many labels were produced
  is never the measure. How many are wrong is.
- **The label metric is per DOCUMENT, over all of its chunks — never per
  chunk.** A per-chunk version counts the boilerplate page of a correctly
  labelled document as an error and can never reach zero.
- **Any post-rerank ranking adjustment must be a penalty on non-matching
  chunks, never a bonus on matching ones**, or it inflates `top_score` and
  quietly weakens refusal. Nothing in this plan should touch ranking, but if
  a task finds itself there, stop.
- **Three ranking constants are COUPLED and must move together:**
  `RECENCY_BOOST_PER_YEAR` (`retrieval/recency.py`), `MATCH_PENALTY`
  (`retrieval/agency_boost.py`), `REFUSAL_THRESHOLD` (`harness/constants.py`).
  `tests/test_recency.py::test_the_shipped_weight_and_refusal_threshold_move_together`
  fails if one moves alone. **Do not weaken that guard.**
- **Agency is a retrieval PREFERENCE, not a filter** (a measured deviation
  from spec Q2). A label change therefore cannot delete an answer — it moves
  ranking only. This is what makes re-labelling a safe operation.
- **Run the Layer 1 eval after any change to `retrieval/`, `ingest/`,
  `chunking/`, `citation/` or `harness/system-prompt.md`:**
  `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`), and commit
  the `eval/results/<...>.{json,md}` files with the change.
  **It must be a CONTROL run** — the unmodified code, on the same corpus, the
  same day. A remembered baseline is not a control; this machine's load
  swings latency by 70%, and the corpus moves under the work.
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX
  weights.** Mechanism goes in pytest; quality goes in `eval/`.
- **Shipped code may never import `eval/`.** `eval/` is excluded from the
  Windows bundle, so such an import raises on every office install and is
  silently swallowed — the check appears to run and never runs. The corpus
  scanner lives in `identity/check.py`; `eval/identity_check.py` is its CLI.
- **Comment WHY, with the evidence.** Record the measurement that drove a
  choice, not just the choice. This codebase's author is not a developer.
- **Verbatim values that must not drift:**
  - fuzzy floor `_FUZZY_THRESHOLD = 85` (`chunking/entity_stamper.py`)
  - agency catalog `samples/entity-catalog.yaml`
  - chunk id format `f"{doc_id}-{idx:04d}"` (`chunking/builder.py:149`)
  - transcript stamp `version: 1` (`harness/history.py`)

---

## Ground truth this plan is built on

Measured by the controller on 2026-08-16 against the live corpus
(7,574 documents / 83,016 budget chunks / 157-agency catalog). **Do not
re-derive these; do re-check them if a number looks wrong.**

**The fuzzy rung is the defect.** `chunking/entity_stamper.py:344` runs
`process.extractOne(cand, all_names, scorer=fuzz.token_set_ratio,
score_cutoff=85)`. `token_set_ratio` compares token *sets*, so any candidate
whose tokens are a subset of a catalog name scores 100 regardless of how
little of the name it covers:

| candidate line | `token_set_ratio` | `token_sort_ratio` | verdict |
|---|---|---|---|
| `Arizona` vs the Osteopathic entry | **100** | **14** | must reject |
| `Medicine` vs the Osteopathic entry | **100** | **16** | must reject |
| `Board of` vs the Osteopathic entry | 77 | 16 | must reject |
| `Board of Barbers` vs `Barbers, Board of` | 97 | **97** | must accept |
| `DEPARTMENT OF CORRECTIONS` vs `Corrections, State Department of` | 88 | **88** | must accept |
| `Arizona Department of Racing` vs `Racing, Arizona Department of` | 98 | **98** | must accept |

`token_sort_ratio` separates the two classes completely at the existing
floor of 85. It sorts tokens before comparing, so it still handles the
reordered-name case the current scorer was chosen for, and it penalises the
length mismatch that `token_set_ratio` ignores.

**Switching the scorer costs nothing on candidates with extra words**,
because both scorers already reject those: `Board of Barbers   Executive
Director: Mario J. Herrera` scores 64 with the current scorer and 46 with the
replacement — both below 85. The fuzzy rung only ever fires on short, clean
candidate lines, which is exactly where the defect lives.

**The tie is the second half of the defect.** `extractOne` returns the first
best match, so a 100-way tie is resolved by catalog order — not by evidence.

**The URL rung is silently unavailable on ~1,448 documents.**
`_JLBC_URL_RE` (`chunking/entity_stamper.py:42`) recognises only
`azjlbc.gov/NNbaseline`, `azjlbc.gov/NNar` and `azleg.gov/jlbc/NNAR`. JLBC
also published under `/NNapp/` (~1,294 live documents) and `/NNbookN/`
(~141), and roughly 965 of those have a slug that IS a catalogued agency —
the strongest witness, discarded, on exactly the FY2005–2012 era where the
mis-labels concentrate. `store/book_family.py:55` (`_BOOK_DIR`) in the same
repo already parses `\d{2}(baseline|book\d*|ar|app)` correctly. **The two
modules disagree about JLBC's own URL vocabulary.**

**Editing the catalog fixes nothing on its own.** `agency_canonical_ids` is
a stored column written once at ingest; no read path consults the catalog.
Repairing the three corrupted canonical names changes the stamping outcome
on 300 sampled mis-labelled chunks by **zero** — and for the phrase
`Board of` the repaired name scores *higher* (76.9 → 100). Only a re-label
changes the data.

**Current error counts** (`eval/results/identity-2026-08-16-baseline.json`,
committed): documents no chunk of which mentions their label — **1,072**, of
which `agency:ost` alone is **732** (an independent audit found 721). Next
largest are small and plausible: `rac` 38, `lan` 38, `pod` 29, `den` 27,
`art` 25. Clean agencies (`tre`, `gam`, `adc`, `axs`) sit at **0**.

**Re-labelling needs no re-ingest.** `EntityStamper.resolve_all()` works
from the chunk's own stored text; `ChunkStore.upsert_chunks` is keyed on
`chunk_id` and replaces rows wholesale, so passage ids and eval ground truth
survive; `vector` is carried through untouched — **but only via
`ChunkStore.scan()` with an explicit column list.** `get_by_ids` and every
search path project `vector` away (`store/chunk_store.py:107`), so a pass
that reads through them writes rows missing a non-nullable field.

**🔴 `upsert_chunks` is a delete followed by an add, in two separate
commits**, and `write_doc` widens the window by calling `delete_doc` first.
An interruption between them leaves those chunk_ids absent. Every task here
that writes chunks takes `IngestLock`, snapshots first, and is treated
operationally as an ingest.

**The corroboration rule has a known weak spot, and this plan fixes it.**
`identity.validator.mentions_agency` asks whether the document contains the
agency name's *longest* distinctive word. For `Highway Safety, Governor's
Office of` that word is **"governor"**, which appears in nearly every budget
document — so a wrong label passes the check. This is what made the title
repair propose renaming *Liquor Licenses and Control* to *Highway Safety,
Governor's Office of*. Task 3 replaces "longest" with a rule calibrated on
the corpus.

---

## File Structure

**Created:**

| file | responsibility |
|---|---|
| `identity/label_audit.py` | per-agency label error rate + a dry-run simulator that re-resolves labels without writing (shipped side, so `ingest/` may import it) |
| `identity/relabel.py` | the offline re-label pass — lock, snapshot, scan, resolve, upsert, verify, reversal record |
| `identity/history_migrate.py` | rewrite chunk/doc ids inside saved conversations under a committed id map |
| `tests/test_identity_label_audit.py` | audit + simulator specs |
| `tests/test_entity_stamper_fuzzy.py` | the scorer and tie-refusal specs |
| `tests/test_identity_relabel.py` | re-label pass specs |
| `tests/test_identity_history_migrate.py` | transcript migration specs |
| `eval/label_calibration.py` | CLI: corpus-wide before/after per-agency error rates |

**Modified:**

| file | change |
|---|---|
| `chunking/entity_stamper.py` | URL rung learns `/NNapp/` + `/NNbookN/`; fuzzy rung switches scorer and refuses ties |
| `identity/validator.py` | `mentions_agency` corroboration rule, calibrated |
| `identity/merge_map.py` (create) | the committed agency merge table |
| `identity/repair.py` | apply-mode used for the full title repair (Task 10) |
| `eval/queries.yaml` | q-001 re-pointed after the doc_id rename |
| `samples/entity-catalog.yaml` | the 3 corrupted canonical names + 31 variants |

**Deliberately untouched:** `retrieval/`, `harness/constants.py`,
`app/`, `webapp/`. Nothing here changes ranking.

---

## Task 1: Per-agency label audit and a no-write simulator

**Files:**
- Create: `identity/label_audit.py`, `tests/test_identity_label_audit.py`

**Interfaces:**
- Consumes: `identity.validator.distinctive_words`,
  `chunking.agency_catalog.id_to_name`, `store.chunk_store.ChunkStore`.
- Produces:
  `audit_labels(*, chunks_by_doc, stamps_by_doc, agency_names, mentions) -> LabelAudit`
  where `LabelAudit` has `.per_agency: dict[str, AgencyError]` (fields
  `documents: int`, `unmentioned: int`, `rate: float`) and `.total_unmentioned: int`;
  and `simulate(*, rows, agency_names, resolver) -> dict[str, list[str]]`
  mapping chunk_id → the labels a given resolver WOULD assign. Tasks 2–4
  call both.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_label_audit.py`:

```python
"""Per-agency label error rates, and a simulator that writes nothing.

This is the instrument the label fix is calibrated on. It exists because the
alternative -- change the matcher, re-label, then look -- writes 83,016 rows
before anyone knows whether the change helped.

The per-agency split is the load-bearing part. A single corpus-wide number
cannot distinguish "fixed the osteopathic defect" from "unlabelled half of
Corrections", and those have opposite value.
"""
from __future__ import annotations

from identity.label_audit import audit_labels


def _mentions(text: str, name: str) -> bool:
    """Test double for the corroboration rule — substring, deliberately dumb,
    so these specs measure the AUDIT and not the rule Task 3 calibrates."""
    return name.lower() in text.lower()


def test_a_document_no_chunk_of_which_mentions_its_label_is_an_error():
    a = audit_labels(
        chunks_by_doc={"d1": ["General Fund revenue collections"]},
        stamps_by_doc={"d1": ["agency:ost"]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        mentions=_mentions,
    )
    assert a.per_agency["agency:ost"].unmentioned == 1
    assert a.per_agency["agency:ost"].rate == 1.0
    assert a.total_unmentioned == 1


def test_a_mention_in_ANY_chunk_clears_the_document():
    """Per DOCUMENT, over all its chunks. A per-chunk metric counts the
    FOOTNOTES page of a correct document as an error and can never reach 0."""
    a = audit_labels(
        chunks_by_doc={"d1": ["FOOTNOTES", "The Osteopathic Examiners board"]},
        stamps_by_doc={"d1": ["agency:ost"]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        mentions=_mentions,
    )
    assert a.per_agency["agency:ost"].unmentioned == 0


def test_a_clean_agency_and_a_poisoned_one_are_reported_separately():
    a = audit_labels(
        chunks_by_doc={
            "d1": ["General Fund revenue"],
            "d2": ["Department of Corrections operates the prisons"],
        },
        stamps_by_doc={"d1": ["agency:ost"], "d2": ["agency:adc"]},
        agency_names={
            "agency:ost": "Osteopathic Examiners",
            "agency:adc": "Department of Corrections",
        },
        mentions=_mentions,
    )
    assert a.per_agency["agency:ost"].rate == 1.0
    assert a.per_agency["agency:adc"].rate == 0.0


def test_an_agency_with_no_documents_is_absent_rather_than_zero_over_zero():
    a = audit_labels(
        chunks_by_doc={"d1": ["anything"]},
        stamps_by_doc={"d1": ["agency:ost"]},
        agency_names={"agency:ost": "Osteopathic", "agency:xyz": "Unused"},
        mentions=_mentions,
    )
    assert "agency:xyz" not in a.per_agency


def test_the_simulator_writes_nothing_and_reports_what_WOULD_change():
    """Calibration must be free and reversible. The simulator takes a
    resolver callable so a task can compare today's matcher against a
    candidate without touching the corpus."""
    from identity.label_audit import simulate

    rows = [
        {"chunk_id": "d1-0001", "doc_id": "d1", "text": "Board of Barbers",
         "section_path": [], "is_table": False, "source_url": None,
         "agency_canonical_ids": ["agency:ost"]},
    ]
    out = simulate(
        rows=rows,
        agency_names={"agency:bar": "Barbers, Board of"},
        resolver=lambda **kw: ["agency:bar"],
    )
    assert out == {"d1-0001": ["agency:bar"]}
    # the input row is untouched
    assert rows[0]["agency_canonical_ids"] == ["agency:ost"]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd /home/destin/ask-the-budget-az-worktrees/identity-consistency && uv run pytest tests/test_identity_label_audit.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'identity.label_audit'`

- [ ] **Step 3: Implement `identity/label_audit.py`**

A `LabelAudit` dataclass with `per_agency` and `total_unmentioned` and an
`as_dict()`; `audit_labels(...)` computing per-agency `documents`,
`unmentioned` and `rate` per the tests; `simulate(...)` mapping chunk_id to
the labels `resolver(**row_fields)` returns, deep-copying nothing and
mutating nothing; and a `load_live(...)` I/O helper that assembles the
arguments from `ChunkStore().scan("budget_chunks", [...])` — that helper is
not unit-tested, and the pure functions it feeds are.

**`scan` must request `vector` nowhere in this module** — the audit never
writes, so it never needs it, and pulling 768 floats per row over 83,016
rows is a pointless cost.

Module docstring records: why per-agency (a corpus-wide number cannot tell a
fix from a regression), and the current baseline (1,072 total; `ost` 732;
`rac` 38, `lan` 38, `pod` 29; `tre`/`gam`/`adc`/`axs` at 0).

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_label_audit.py -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Run it against the real corpus and commit the baseline**

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m identity.label_audit --json eval/results/label-audit-baseline.json`

Expected, and **stop and reconcile if the first two differ by more than
5%**: total ≈ 1,072; `agency:ost` ≈ 732; `tre`/`gam`/`adc`/`axs` at 0.

- [ ] **Step 6: Commit**

```bash
git add identity/label_audit.py tests/test_identity_label_audit.py eval/results/label-audit-baseline.json
git commit -m "identity: per-agency label error rate + no-write simulator"
```

---

## Task 2: Teach the URL rung JLBC's other two directory conventions

**Files:**
- Modify: `chunking/entity_stamper.py` (`_JLBC_URL_RE`, ~line 42)
- Test: `tests/test_entity_stamper.py` (append)

**Interfaces:**
- Consumes: nothing new.
- Produces: no new names. `slug_from_jlbc_url` now returns a slug for
  `/NNapp/` and `/NNbookN/` URLs.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_entity_stamper.py`:

```python
def test_the_url_rung_knows_every_directory_jlbc_actually_published_under():
    """~1,448 JLBC-hosted documents got no slug at all, and ~965 of them have
    a slug that IS a catalogued agency -- the strongest witness in the ladder,
    discarded, on exactly the FY2005-2012 era where the mis-labels concentrate.

    `store/book_family.py:55` in this same repo already parses
    `\\d{2}(baseline|book\\d*|ar|app)`. The two modules disagreed about JLBC's
    own URL vocabulary; this is the module that mattered."""
    from chunking.entity_stamper import slug_from_jlbc_url

    assert slug_from_jlbc_url("https://www.azjlbc.gov/05app/bar.pdf") == "bar"
    assert slug_from_jlbc_url("https://www.azjlbc.gov/12book1/des.pdf") == "des"
    # the two that already worked must keep working
    assert slug_from_jlbc_url("https://www.azjlbc.gov/26baseline/crr.pdf") == "crr"
    assert slug_from_jlbc_url("https://www.azjlbc.gov/26ar/ost.pdf") == "ost"
    assert slug_from_jlbc_url("http://www.azleg.gov/jlbc/15AR/adc.pdf") == "adc"


def test_a_url_that_is_not_a_jlbc_book_still_yields_no_slug():
    """The rung must stay a JLBC-book rule. A governor's-budget or AFR URL
    has no agency slug in it and must not be coerced into one."""
    from chunking.entity_stamper import slug_from_jlbc_url

    assert slug_from_jlbc_url("https://azgovernor.gov/fy2027-detail.pdf") is None
    assert slug_from_jlbc_url("https://gao.az.gov/afr-fy2024.pdf") is None
    assert slug_from_jlbc_url("https://www.azjlbc.gov/notes/hb2172.pdf") is None
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_entity_stamper.py -k url_rung -q`
Expected: FAIL — `/05app/` and `/12book1/` return `None`.

- [ ] **Step 3: Implement**

Widen the alternation to match `store/book_family.py`'s vocabulary, and say
why in a comment:

```python
# WHY these four directories and not two (2026-08-16): JLBC published agency
# pages under `/NNapp/` (~1,294 live documents) and `/NNbookN/` (~141) as
# well as the `/NNbaseline/` and `/NNar/` this rule started with. Those
# ~1,448 documents therefore reached the fuzzy text rung with no slug at
# all -- and ~965 of them have a slug that IS a catalogued agency. That is
# the strongest witness in the ladder, discarded, on exactly the FY2005-2012
# era where the mis-labels concentrate. `store/book_family.py::_BOOK_DIR`
# already knew all four; the two modules disagreed and this is the one that
# assigned labels.
_JLBC_URL_RE = re.compile(
    r"^https?://(?:www\.azjlbc\.gov/\d{2}(?:baseline|book\d*|ar|app)/"
    r"|www\.azleg\.gov/jlbc/\d{2}AR/)([a-z0-9_\-]+)\.pdf$",
    re.IGNORECASE,
)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_entity_stamper.py -q`
Expected: PASS, no pre-existing test broken.

- [ ] **Step 5: Measure what it changes, without writing**

Run the Task 1 simulator over the corpus with today's matcher plus this
change only, and record how many chunks gain a slug-derived label:

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m eval.label_calibration --only-url-rung`

(If Task 5 has not built that CLI yet, do this as a throwaway script and
paste the numbers into the report; do not commit the throwaway.)

- [ ] **Step 6: Commit**

```bash
git add chunking/entity_stamper.py tests/test_entity_stamper.py
git commit -m "chunking: the URL rung learns /NNapp/ and /NNbookN/ (I2)"
```

---

## Task 3: Calibrate the corroboration rule

**Files:**
- Modify: `identity/validator.py` (`mentions_agency`)
- Test: `tests/test_identity_validator.py` (append)

**Interfaces:**
- Consumes: `identity.validator.distinctive_words`.
- Produces: `mentions_agency(text, agency_name) -> bool` — same signature,
  calibrated rule. `identity/check.py`, `identity/compose.py`,
  `identity/repair.py` and Task 1's audit all already call it.

- [ ] **Step 1: Establish the problem with a failing test**

Append to `tests/test_identity_validator.py`:

```python
def test_a_common_word_does_not_corroborate_a_label():
    """The measured failure that blocked the title repair.

    `mentions_agency` asked whether the document contained the agency name's
    LONGEST distinctive word. For "Highway Safety, Governor's Office of" that
    word is "governor", which appears in nearly every budget document -- so a
    wrong label passed the check, and the title repair proposed renaming
    "Liquor Licenses and Control, Department of" to "Highway Safety,
    Governor's Office of" on a document whose title was already correct."""
    from identity.validator import mentions_agency

    liquor_page = (
        "Liquor Licenses and Control, Department of. The Governor's Office "
        "recommends no change to the agency's operating budget."
    )
    assert mentions_agency(liquor_page, "Liquor Licenses and Control, Department of")
    assert not mentions_agency(liquor_page, "Highway Safety, Governor's Office of")


def test_a_genuine_mention_still_corroborates():
    from identity.validator import mentions_agency

    assert mentions_agency(
        "The Board of Osteopathic Examiners licenses physicians.",
        "Osteopathic Examiners in Medicine and Surgery, Arizona Board of",
    )
    assert mentions_agency(
        "Arizona Department of Racing  Director: Geoffrey Gonsher",
        "Racing, Arizona Department of",
    )


def test_a_single_word_agency_name_still_works():
    """AHCCCS has exactly one distinctive word. A rule that requires two
    would silently stop corroborating the fourth-largest agency."""
    from identity.validator import mentions_agency

    assert mentions_agency("AHCCCS capitation rates rose", "AHCCCS")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_identity_validator.py -k corroborate -q`
Expected: FAIL — `mentions_agency(liquor_page, "Highway Safety, …")` returns
True, because "governor" is present.

- [ ] **Step 3: Calibrate, then implement**

**Do not pick a rule and ship it.** Measure at least these three candidates
with the Task 1 audit over the live corpus, and record all three in the
report and in a comment:

1. longest distinctive word (today's rule) — the baseline;
2. **all** distinctive words present;
3. a majority of distinctive words present (≥ half, minimum one).

For each, record `agency:ost`'s error rate, the corpus total, and — the row
that decides it — the rate on the four known-clean agencies `tre`, `gam`,
`adc`, `axs`, which must stay at **0**. A rule that "fixes" `ost` by
declaring Corrections uncorroborated is worse than the defect.

Pick the rule the numbers support, implement it, and put the table in the
docstring. If none of the three separates the classes, say so and propose a
fourth rather than choosing the least-bad one silently.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_validator.py tests/test_identity_check.py tests/test_identity_compose.py tests/test_identity_repair.py -q`
Expected: PASS. `mentions_agency` has four consumers; a stricter rule will
move numbers in `identity/check.py`'s specs. Where a spec pinned the old
behaviour, update it and say why in its docstring.

- [ ] **Step 5: Commit**

```bash
git add identity/validator.py tests/
git commit -m "identity: calibrate the corroboration rule (I1)"
```

---

## Task 4: Fix the fuzzy rung — scorer and tie refusal

**Files:**
- Modify: `chunking/entity_stamper.py` (the fuzzy fallback, ~line 344)
- Create: `tests/test_entity_stamper_fuzzy.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: no new public names. `EntityStamper._resolve` returns `None` for
  a candidate that no longer clears the floor, and for a tie at the ceiling.

- [ ] **Step 1: Write the failing test**

Create `tests/test_entity_stamper_fuzzy.py`:

```python
"""The fuzzy rung, which is what mis-labelled 732 documents.

`token_set_ratio` compares token SETS, so a candidate whose tokens are a
subset of a catalog name scores 100 no matter how little of the name it
covers. Measured against the real Osteopathic entry:

    candidate     token_set_ratio   token_sort_ratio
    'Arizona'                 100                 14
    'Medicine'                100                 16
    'Board of'                 77                 16
    'Board of Barbers'         97                 97   (vs 'Barbers, Board of')
    'DEPARTMENT OF CORRECTIONS' 88                88   (vs 'Corrections, State Department of')

`extractOne` then breaks the resulting 100-way tie by CATALOG ORDER rather
than by evidence, which is why one small regulatory board collected 992
documents.
"""
from __future__ import annotations

import pytest

from chunking.entity_stamper import EntityStamper


@pytest.fixture(scope="module")
def stamper():
    return EntityStamper.from_default_paths()


def test_a_single_common_word_no_longer_resolves_to_an_agency(stamper):
    for candidate in ("Arizona", "Medicine", "Surgery", "Board of"):
        got, _chain = stamper._resolve(
            section_path=[], text=candidate, source_url=None
        )
        assert got is None, f"{candidate!r} resolved to {got}"


def test_a_real_agency_heading_still_resolves(stamper):
    for text, expected in (
        ("Board of Barbers", "agency:bar"),
        ("Arizona Department of Racing", "agency:rac"),
        ("Department of Child Safety", "agency:dcs"),
    ):
        got, _chain = stamper._resolve(
            section_path=[], text=text, source_url=None
        )
        assert got == expected, f"{text!r} -> {got}"


def test_a_tie_at_the_ceiling_refuses_rather_than_taking_catalog_order(stamper):
    """An ambiguous match is not evidence. Leaving the chunk unlabelled costs
    a ranking preference; guessing costs a wrong agency facet -- and agency is
    a PREFERENCE, not a filter, so refusing cannot delete an answer."""
    got, _chain = stamper._resolve(
        section_path=[], text="Board", source_url=None
    )
    assert got is None


def test_the_url_rung_still_wins_over_the_text(stamper):
    """Rung order is unchanged: a slug is stronger evidence than a phrase."""
    got, _chain = stamper._resolve(
        section_path=[],
        text="Board of Barbers",
        source_url="https://www.azjlbc.gov/26ar/rac.pdf",
    )
    assert got == "agency:rac"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_entity_stamper_fuzzy.py -q`
Expected: FAIL — `Arizona` and `Medicine` resolve to an agency (whichever
the catalog lists first among the 100-way tie).

- [ ] **Step 3: Implement**

Replace the scorer and add tie refusal. Use `process.extract` (plural) with
a small limit so ties are visible, rather than `extractOne` which hides
them. Keep `_FUZZY_THRESHOLD = 85` and keep `_fuzzy_processor` exactly as it
is — it is load-bearing for casefolding and NBSP, and both reasons are
documented at the call site.

Record the measured table above in the comment, plus the fact that switching
scorers costs nothing on candidates carrying extra words (both scorers
already reject `Board of Barbers   Executive Director: Mario J. Herrera` —
64 and 46, against a floor of 85).

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_entity_stamper_fuzzy.py tests/test_entity_stamper.py tests/test_agency_catalog.py -q`
Expected: PASS.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: 3047+ passed. `chunking/` is imported widely; investigate any
failure rather than re-pointing it.

- [ ] **Step 6: Commit**

```bash
git add chunking/entity_stamper.py tests/test_entity_stamper_fuzzy.py
git commit -m "chunking: the fuzzy rung scores by token_sort_ratio and refuses ties (I2)"
```

---

## Task 5: Calibration report — prove the fix before writing anything

**Files:**
- Create: `eval/label_calibration.py`
- Test: `tests/test_label_calibration.py`

**Interfaces:**
- Consumes: `identity.label_audit.audit_labels`, `.simulate`, `.load_live`.
- Produces: `python -m eval.label_calibration` writing
  `eval/results/label-calibration-<date>.json` and printing a per-agency
  before/after table. **This is gate G-I2 for the re-label.**

- [ ] **Step 1: Write the failing test**

Create `tests/test_label_calibration.py` driving the comparison logic with
plain dict fixtures (never the real corpus):

```python
"""The gate the re-label is allowed through, or not.

The number that matters is NOT "how many labels changed" -- that rises with
any looser or stricter rule alike. It is: does the poisoned agency's error
rate fall, AND does every clean agency stay clean.
"""
from __future__ import annotations

from eval.label_calibration import compare


def test_a_fix_that_helps_one_agency_and_harms_none_is_reported_as_a_pass():
    verdict = compare(
        before={"agency:ost": (992, 732), "agency:adc": (376, 0)},
        after={"agency:ost": (992, 4), "agency:adc": (376, 0)},
    )
    assert verdict.passes is True
    assert verdict.improved == ["agency:ost"]
    assert verdict.regressed == []


def test_a_fix_that_unlabels_a_clean_agency_FAILS_however_much_it_helps():
    """The specific bad trade: 'fixing' the osteopathic defect by declaring
    half of Corrections uncorroborated is worse than the defect."""
    verdict = compare(
        before={"agency:ost": (992, 732), "agency:adc": (376, 0)},
        after={"agency:ost": (992, 0), "agency:adc": (376, 188)},
    )
    assert verdict.passes is False
    assert "agency:adc" in verdict.regressed


def test_the_report_never_states_how_many_labels_were_produced():
    verdict = compare(
        before={"agency:ost": (992, 732)}, after={"agency:ost": (992, 4)}
    )
    keys = verdict.as_dict().keys()
    assert not any("produced" in k or "coverage" in k or "total_labels" in k
                   for k in keys)
```

- [ ] **Step 2: Run and verify failure; Step 3: implement; Step 4: verify pass**

Run: `uv run pytest tests/test_label_calibration.py -q`

- [ ] **Step 5: Run the calibration against the live corpus**

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m eval.label_calibration --json eval/results/label-calibration-2026-08-16.json`

**The gate, all three required:**

1. `agency:ost` error rate falls from ~732 to near zero;
2. **every agency at 0 today is still at 0** — `tre`, `gam`, `adc`, `axs`
   at minimum, and no agency's error count rises;
3. the corpus total falls.

**If any clean agency regresses, STOP.** Do not proceed to Task 6, do not
"accept a small regression". Report the numbers and go back to Task 3 or 4.

- [ ] **Step 6: Commit**

```bash
git add eval/label_calibration.py tests/test_label_calibration.py eval/results/label-calibration-2026-08-16.json
git commit -m "eval: label calibration gate — per-agency before/after"
```

---

## Task 6: Re-label the corpus

**Files:**
- Create: `identity/relabel.py`, `tests/test_identity_relabel.py`

**Interfaces:**
- Consumes: `store.chunk_store.ChunkStore`, `ingest.lock.IngestLock`,
  `store.backup.snapshot`, `chunking.entity_stamper.EntityStamper`.
- Produces: `relabel_corpus(*, dry_run=True, ...) -> RelabelResult` with
  `.changed: int`, `.chunk_count_before/after: int`, `.reversal: list[dict]`;
  and `python -m identity.relabel --dry-run | --apply`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_relabel.py`. Drive it with a fake store — **no
real LanceDB.** Required specs:

```python
def test_the_pass_reads_and_rewrites_the_vector_column():
    """`vector` is non-nullable and every convenient reader projects it away
    (`store/chunk_store.py:107`): `get_by_ids`, `vector_search`, `fts_search`
    all use a column list that excludes it. Only `scan` with an explicit list
    returns it. A pass that round-trips through the convenient reader writes
    rows missing a required field -- and would do it 83,016 times."""


def test_no_chunk_id_is_lost(): ...
    # G-I3: count before == count after, and the id SETS are equal.


def test_every_other_column_survives_untouched():
    """G-I3 again, and count equality is not enough for it: this pass rewrites
    `agency_canonical_ids`, so a bug that dropped `doc_type` or `fiscal_year`
    would keep the count identical and be invisible."""


def test_a_dry_run_writes_nothing(): ...


def test_the_pass_refuses_to_run_without_the_ingest_lock():
    """`upsert_chunks` is a delete followed by an add in two separate commits
    and `write_doc` widens the window further. An interruption between them
    leaves those chunk_ids absent, so this is operationally an ingest."""


def test_a_reversal_record_carries_the_old_labels(): ...
```

- [ ] **Step 2: Run and verify failure; Step 3: implement**

The pass, in order: take `IngestLock` → `store.backup.snapshot()` and
**verify it** → `scan` with an explicit column list **including `vector`** →
re-resolve each chunk's labels via `EntityStamper.resolve_all` → write only
the rows whose labels changed, via `upsert_chunks` → re-count and compare
chunk ids → write the reversal record to
`<data_dir>/label-reversal-<UTC>.json`.

**Batch the writes** (a few thousand rows at a time) so one interruption
costs one batch, and log progress — this runs over 83,016 rows and a silent
twenty-minute pass is indistinguishable from a hang.

- [ ] **Step 4: Verify tests pass; Step 5: dry-run the real corpus**

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m identity.relabel --dry-run --out /tmp/relabel-dry-run.json`

Then **read at least 30 proposed changes by hand**, spread across FY2005,
FY2015 and FY2027, and specifically inspect several `agency:ost` documents
and several `agency:adc` ones. Report what you found. **Do not apply on a
subagent's own authority** — this rewrites the corpus, and the controller
takes that step.

- [ ] **Step 6: Commit the code (not the application)**

```bash
git add identity/relabel.py tests/test_identity_relabel.py
git commit -m "identity: corpus re-label pass — locked, snapshotted, reversible (I2)"
```

---

## Task 7: Apply the re-label, then re-measure everything

**Files:** none — this is an operation, and it is the controller's.

- [ ] **Step 1: Confirm the gate from Task 5 passed.** If any clean agency
      regressed, stop.
- [ ] **Step 2: Control eval BEFORE**, on the same corpus, the same day:
      `JLBC_DATA_DIR=data/insight-data uv run python -m eval.run_eval`
- [ ] **Step 3: Apply.**
      `JLBC_DATA_DIR=data/insight-data uv run python -m identity.relabel --apply`
- [ ] **Step 4: G-I3.** Chunk count before == after, id sets equal, and a
      per-column diff clean on a sample of 500 rows.
- [ ] **Step 5: Re-measure.** `python -m identity.label_audit` and
      `python -m eval.identity_check`. `ost` at ~0, clean agencies still 0.
- [ ] **Step 6: Eval AFTER.** Same command as Step 2. **Gate G-I1:**
      recall@15 ≥ 90%, recall@20 ≥ 95%. Commit both result files.
      Agency is a preference, not a filter, so a label change cannot delete
      an answer — a large recall move means something else changed and must
      be explained, not accepted.
- [ ] **Step 7: Commit** the eval results and an updated
      `eval/results/label-audit-after.json`.

---

## Task 8: Merge the six split agency ids

**Files:**
- Create: `identity/merge_map.py`, `tests/test_identity_merge_map.py`
- Modify: `identity/relabel.py` (a merge mode)

**Interfaces:**
- Consumes: `identity.relabel`'s write machinery.
- Produces: `MERGE_MAP: dict[str, str]` (old id → surviving id) and
  `python -m identity.relabel --merge`.

- [ ] **Step 1: Write the failing test**

```python
def test_the_merge_map_is_exactly_the_six_recorded_groups():
    """Committed as data so the claim is visible rather than implicit. This
    asserts that a predecessor unit and its successor department are ONE
    agency -- a judgement a budget analyst may dispute, which is why it is
    written down and why the pass is reversible."""
    from identity.merge_map import MERGE_MAP
    assert MERGE_MAP == {
        "agency:cs": "agency:dcs",
        "agency:doa-csf": "agency:dcs",
        "agency:doa-cfs": "agency:dcs",
        "agency:doacfs": "agency:dcs",
        "agency:uniasum": "agency:uniasu",
        "agency:wif": "agency:wifa",
        "agency:oco": "agency:oeo",
        "agency:cna": "agency:cet",
        "agency:rev": "agency:dor",
    }


def test_no_merged_pair_appears_in_the_SAME_fiscal_year():
    """The guard that separates a RENAME from two real units. STATUS.md
    records that ASU's two ids are contiguous and never overlap -- which is
    what makes that merge a rename -- and that the University of Arizona's
    Main Campus and Health Sciences Center run in PARALLEL every year and
    must never be merged. Co-occurrence in one year is the difference."""
```

- [ ] **Steps 2–4:** verify failure, implement, verify pass.

- [ ] **Step 5: Run the co-occurrence guard against the live corpus** and
      report per pair. **If any pair co-occurs in a fiscal year, do not merge
      that pair** — report it and leave it for a human decision. Target
      selection is the spec's rule, in order: the id already named by the
      eval set (`dcs` qualifies — `queries_recency.yaml` and
      `queries_historical.yaml` both name it), else the id matching the
      agency's modern name, else the id with the most documents.

- [ ] **Step 6: Apply, verify, commit** — same lock/snapshot/reversal
      discipline and the same G-I3 checks as Task 7.

---

## Task 9: Rename the 22 doc_ids, re-point the eval, migrate saved chats

**Files:**
- Create: `identity/history_migrate.py`, `tests/test_identity_history_migrate.py`
- Modify: `identity/relabel.py` (a rename mode), `eval/queries.yaml`

**Interfaces:**
- Produces: `migrate_transcripts(*, id_map, history_dir) -> MigrationResult`
  and `python -m identity.history_migrate --apply`.

- [ ] **Step 1: Write the failing test**

```python
def test_a_saved_conversation_follows_a_renamed_document():
    """The cost of this rename is NOT the eval -- it is saved conversations.

    Transcripts persist chunk ids in two independent places: the figure
    annotation written by `citation/annotate.py`, and the verbatim retrieve()
    JSON in `tool` messages, which `harness/history.py` explicitly refuses to
    prune. Confirmed on real files: 20 stored transcripts, 42 distinct doc
    ids. Without this migration, clicking such a citation returns 404 and the
    panel reads "Source no longer available" -- a hard, visible break."""


def test_a_transcript_with_no_version_stamp_is_still_migrated():
    """`version: 1` was added so "written before versioning" and "written
    today" are distinguishable. This is the first migration that has ever
    needed it."""


def test_a_corrupt_transcript_costs_ONE_conversation_and_not_the_rail(): ...


def test_the_rename_is_a_pure_string_substitution_with_the_ordinal_intact():
    """chunk_id = f"{doc_id}-{idx:04d}" (chunking/builder.py:149), so
    jlbc-baseline-fy2026-crr-0013 -> jlbc-approps-fy2026-crr-0013."""
```

- [ ] **Steps 2–4:** verify failure, implement, verify pass.

- [ ] **Step 5: Verify no rename target collides** with an existing doc_id
      before writing anything. (Checked 2026-08-16: none did.)

- [ ] **Step 6: Re-point the eval and VERIFY IT.** Exactly one entry is
      affected — `eval/queries.yaml` q-001, `jlbc-baseline-fy2026-crr-0013`,
      whose `anchor_text` is `"FY 2026 EORP employer contribution rate is
      70.70%"`. Assert that text appears at the NEW chunk_id, or the
      re-point is wrong and must fail loudly. `eval/refresh_chunk_ids.py`
      was deleted and nothing replaces it; `anchor_text` is the surviving
      repair path and this is the case it was recorded for.

- [ ] **Step 7: Apply, then gate G-I5** — every chunk_id referenced by a
      stored transcript resolves. Commit.

---

## Task 10: Apply the full title repair

**Files:** `identity/repair.py` (no code change expected), `eval/results/`

The title repair is code-complete from the previous plan and was held
because it depends on labels. With Tasks 7–9 applied, that dependency is
satisfied.

- [ ] **Step 1: Re-run the dry run**
      `JLBC_DATA_DIR=data/insight-data uv run python -m identity.repair --dry-run --out /tmp/title-dry-run.json`
- [ ] **Step 2: Compare against the pre-label-fix dry run** (746 changes).
      The wrong renames that blocked it must be gone — specifically
      `jlbc-baseline-fy2012-liq`, `jlbc-baseline-fy2021-nav` and
      `jlbc-baseline-fy2013-lem` must no longer be renamed at all, because
      their existing titles are correct.
- [ ] **Step 3: Read 30 changes by hand**, across FY2005 / FY2015 / FY2027.
      **This step is not optional and cannot be delegated to a passing
      test.** The flagship case must hold: `jlbc-approps-fy2005-bar` →
      *"Barbers, Board of — FY 2005 Appropriations Report"*.
- [ ] **Step 4: Check the two known-bad formats are fixed** —
      `jlbc-baseline-fy2027-s1` and `s54` previously kept a `JLBC FY2027 — •`
      prefix AND gained a suffix, producing a double-format title.
- [ ] **Step 5: Apply**, then re-run `python -m eval.identity_check`.
      Targets: `title_names_wrong_agency` → 0, `titles_outside_format` → 0,
      `duplicate_titles` → 0.
- [ ] **Step 6: Commit** the identity-check result alongside.

---

## Task 11: Repair the suppliers so none of it comes back

**Files:**
- Create: `scripts/repair_supplier_titles.py`
- Modify: `data/jlbc-book-catalog.json`,
  `webapp/reference/assets/search/index-lite.js`,
  `samples/entity-catalog.yaml`
- Test: `tests/test_book_catalog.py`, `tests/test_agency_catalog.py` (append)

Both wrong-name suppliers are committed repo files. Un-repaired, the next
ingest of any pre-2013 edition re-imports "Agriculture" for the Board of
Barbers, and the post-ingest check finds the same defect forever.

- [ ] **Step 1: Write the failing tests** — no catalogued agency name fails
      `validate_name`; no two `per_agency` entries in one book edition share
      a title.
- [ ] **Step 2: Verify they fail** — `agency:ost`, `agency:nci`,
      `agency:apc`; and `('approps-fy2005', 'agr', 'bar', 'Agriculture, …')`.
- [ ] **Step 3: Repair `samples/entity-catalog.yaml` by hand** — 3
      `canonical_name` values and 31 `names_observed_jlbc` keys.
      **This is for the name the MODEL is shown by `list_filter_values`, NOT
      for labelling** — measured, repairing these strings changes labelling
      by zero, and for the phrase `Board of` the repaired name scores
      *higher* (76.9 → 100). Say so in the commit message so nobody later
      reads it as the labelling fix.
- [ ] **Step 4: Write the regenerator** — join each supplier row to the
      repaired corpus on `source_url` (case-insensitive, exactly as
      `search_provider._info` does) and rewrite only `title`. **Preserve the
      files' exact serialization**: `index-lite.js` must stay
      `window.JLBC_DOCS=[…];` or the SPA's parser
      (`raw.split("=", 1)[1].strip().rstrip(";")`) breaks.
- [ ] **Step 5: Verify** — the two suites, plus `cd webapp && npm run build`.
- [ ] **Step 6: Commit.**

---

## Task 12: Rename the groups, and record what happened

**Files:** the spec, both plans, `STATUS.md`

- [ ] **Step 1: Rename Unit A / B / C** in
      `docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md`
      and both plan files to **measure it** / **fix the titles** /
      **fix the labels**. Keep the phase ids (A1, B2, C1 …) as short labels
      but expand their headings. The repo already has "Phases" and
      "Plans 1–7"; a third lettering scheme costs a reader more than it saves.
- [ ] **Step 2: Update `STATUS.md`** with a section for this work carrying
      the before/after numbers from every gate, the browser checks, and what
      was NOT done. **Numbers only — no claim that a check passed unless it
      was run.**
- [ ] **Step 3: Record the defects this work found in its own plans**, since
      the pattern recurs: plan prose held up under measurement and plan
      example code did not — a regex that could not match its own test case,
      two title literals that were wrong about the humanizer, function names
      that did not exist, and an import that would have failed on every
      office install.
- [ ] **Step 4: Commit.**

---

## Task 13: Verify in a real browser

**Files:** none.

- [ ] **Step 1: Build and start**
      `cd webapp && npm run build && cd .. && JLBC_DATA_DIR=data/insight-data uv run uvicorn app.main:create_app --factory --port 9300`
      `uvicorn` runs without `--reload`, so **Python changes need a restart** —
      only the SPA picks up a rebuild. Several rounds of testing on this repo
      have measured a stale build.
- [ ] **Step 2: The flagship defect.** Search `barbers`; the FY2005 result
      must read *Barbers, Board of*, not *Agriculture*. Open the same
      document in the browse listing — the two must read identically.
- [ ] **Step 3: The agency facet.** Filter by Osteopathic Examiners. It must
      return a handful of documents, not ~992, and each must genuinely be
      that board's.
- [ ] **Step 4: AI Mode.** Ask a question that retrieves a repaired FY2005
      document; the name in the answer must match the browse page.
- [ ] **Step 5: A saved conversation.** Open a chat saved before the rename
      that cites one of the 22 documents; its citation must still open the
      PDF, not read "Source no longer available".
- [ ] **Step 6: Admin.** `/admin` → Needs attention shows the identity
      findings as a plain sentence.
- [ ] **Step 7: Record what you saw in `STATUS.md`**, including anything
      that did not work.

---

## Self-review notes

**Spec coverage.** I2 → Tasks 2, 3, 4, 5, 6, 7. I9 → Task 8. I10 → Task 9.
I5/I6/I7/I8 application → Tasks 10, 11. I1's corroboration rule → Task 3.
Naming and record → Task 12. Browser → Task 13.

**Gates.** G-I1 in Task 7 Steps 2/6 (control + after). G-I2 is Task 5, and
Task 6 may not proceed without it. G-I3 in Tasks 7 and 8. G-I5 in Task 9.

**Ordering constraint that is not obvious.** Task 3 (corroboration) must
land before Task 5 (calibration), because the calibration measures error
rates *using* that rule — calibrating the matcher against a broken ruler
would report a fix that isn't one.

**The riskiest task is 6**, and its risk is not the labelling logic — it is
the write. `upsert_chunks` is non-atomic, `vector` is invisible to the
convenient reader, and it runs over 83,016 rows. Its tests are about the
write, not about agencies.
