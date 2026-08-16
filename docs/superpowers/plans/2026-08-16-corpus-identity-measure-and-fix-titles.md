# Corpus identity consistency — Units A + B implementation plan

> # ⛔ EXECUTED AND MERGED 2026-08-16 — DO NOT RUN THIS PLAN AGAIN
>
> Every task below is done, merged to `master`, and **applied to the live
> corpus**. The unchecked `- [ ]` boxes are the record of what was planned,
> not a to-do list, and the "REQUIRED SUB-SKILL … implement this plan
> task-by-task" line above is addressed to the session that already did.
>
> **Re-running it would re-apply corpus mutations that have already
> happened** — re-labelling, agency merges, document renames, title
> rewrites — against data those passes have already changed.
>
> What actually shipped, the measured before/after, the places this plan
> was WRONG, and the open follow-ups are in **`STATUS.md` → "Corpus
> identity — names and agency labels repaired (2026-08-16)"**. STATUS.md
> is the source of truth for status; this file is design intent only.
>
> This plan is the *measure it / fix the titles* group of the spec.


> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make every surface show the same, correct name for a document, measured by an error rate rather than by coverage — and stop the wrong names being re-imported.

**Architecture:** A new `identity/` package owns three things nothing owns today: a name validator with reasons, a title composer, and the ONE read-path resolver that all three existing title ladders collapse into. A new `eval/identity_check.py` measures the error rates through the real read paths. The stored corpus is then repaired as a `documents.json` edit — no chunk rewrite, no lock, no snapshot — and the two committed supplier files that feed the wrong names are corrected in the repo.

**Tech Stack:** Python 3.12 (`uv`), pytest, LanceDB via `store/`, PyYAML, Vite/React webapp (untouched except one vendored data file).

**Scope:** Units A and B of
[`docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md`](../specs/2026-08-16-corpus-identity-consistency-design.md)
— decisions I1, I3, I4, I5, I6, I7, I8, I12, I13, I14, I15.

**"fix the labels" is deliberately NOT in this plan** (I2 matcher guard, corpus
re-stamp, I9 agency merge, I10 doc_id rename + transcript migration). Its
first task is calibrating a fuzzy-match coverage floor against measured
per-agency error rates, and **those numbers do not exist until Task 4 of
this plan runs.** Writing calibration steps before the instrument exists
is exactly the failure the spec's own measurement discipline forbids.
"fix the labels" gets its own plan, written from Task 4's output.

---

## Global Constraints

Copied verbatim from the spec and from `CLAUDE.md`. Every task's
requirements implicitly include this section.

- **Gate on the ERROR rate, never coverage.** "How many names did we
  produce" is never reported by `eval/identity_check.py`.
- **The stamping metric is measured per DOCUMENT, over all of its chunks
  and its URL slug — never per chunk.** A per-chunk version reports
  boilerplate pages of correct documents as errors and can never reach 0.
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX
  weights.** Mechanism goes in pytest; quality goes in `eval/`.
- **Fiscal notes are out of scope for the validator.** `Fiscal Note - HB
  2527: <strike>…</strike> (NOW: …)` is a rendered feature, not a defect.
- **The one title format is `{Name} — FY {year} {Book}`** — 4,950
  documents already use it.
- **A composed title must be unique within its (book, fiscal year).**
  Where it would not be, the distinguishing element is kept.
- **Annotate non-trivial edits with a WHY comment** recording the
  *evidence* that drove the choice, not just the choice.
- **Run the Layer 1 eval after any change to `retrieval/`, `ingest/`,
  `chunking/`, `citation/` or `harness/system-prompt.md`**:
  `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`), and
  commit the `eval/results/<...>.{json,md}` files with the change. **Tasks
  1–4 and 9 touch none of those paths and need no eval run.** Tasks 5–8
  do — and it must be a CONTROL run on the same corpus the same day, never
  a remembered baseline.
- **Verbatim strings that must not drift:**
  - mockup index file: `webapp/reference/assets/search/index-lite.js`,
    format `window.JLBC_DOCS=[…];`
  - book catalog: `data/jlbc-book-catalog.json`, editions keyed
    `approps-fy2005`, each with a `per_agency` list of
    `{code, title, url}`
  - agency catalog: `samples/entity-catalog.yaml`, entries with
    `canonical_name`, `canonical_id`, `slug`, `names_observed_jlbc`

---

## File Structure

**Created:**

| file | responsibility |
|---|---|
| `identity/__init__.py` | package marker; re-exports `resolve_title`, `compose_title`, `validate_name` |
| `identity/validator.py` | decoration-strip + verdict/reason for one string (I3) |
| `identity/compose.py` | build `{Name} — FY {year} {Book}`; uniqueness; supplier-disagreement record (I1, I5) |
| `identity/resolve.py` | the ONE read-path title resolver (I12) |
| `identity/repair.py` | offline `documents.json` title repair + I8 reversal record |
| `eval/identity_check.py` | the error-rate instrument (I13) |
| `tests/test_identity_validator.py` | validator specs |
| `tests/test_identity_compose.py` | composer specs |
| `tests/test_identity_resolve.py` | resolver specs, incl. the three-ladder agreement gate (G-I4) |
| `tests/test_identity_repair.py` | repair-pass specs |
| `tests/test_identity_check.py` | instrument specs against synthetic fixtures |
| `scripts/repair_supplier_titles.py` | one-off generator for the two committed supplier files (I6) |

**Modified:**

| file | change |
|---|---|
| `app/search_provider.py:199` | title comes from `identity.resolve_title` |
| `app/routes/corpus.py:221` | title comes from `identity.resolve_title` |
| `harness/tools.py:135` | `_doc_titles` comes from `identity.resolve_titles` |
| `samples/entity-catalog.yaml` | 3 `canonical_name` + 31 variant repairs |
| `data/jlbc-book-catalog.json` | regenerated `per_agency` titles |
| `webapp/reference/assets/search/index-lite.js` | regenerated titles |
| `ingest/book_discovery.py:275,284` | compose the suffix instead of handing over a raw string |
| `ingest/worker.py` | validator call + advisory queue line (I4) |
| `app/routes/admin.py` | surface `identity-report.json` in Needs attention (I15) |

**Deliberately untouched:** `ingest/lance_writer.py::build_title`,
`app/routes/books.py`, `chunking/entity_stamper.py` ("fix the labels"),
`store/schema.py` (the title is not a chunk column).

---

## Task 1: The name validator

**Files:**
- Create: `identity/__init__.py`, `identity/validator.py`
- Test: `tests/test_identity_validator.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `Verdict` (frozen dataclass: `ok: bool`, `value: str`,
  `reason: str | None`, `stripped: bool`) and
  `validate_name(raw: str) -> Verdict`. Later tasks call only these two
  names.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_validator.py`:

```python
"""One predicate: does this string look like a name? (spec I3)

Two verdicts, not one. A DECORATION sits at the edge of the string and is
provably additive, so stripping it is deterministic, not a guess. CORRUPTION
sits inside the string, and trimming it IS a guess — those quarantine.

The two deleted rules are pinned here as negatives, because both were in the
first spec draft and both were measured wrong: `AHCCCS` is the only all-caps
stored title in the corpus and it is CORRECT, and every HTML-bearing title is
a fiscal note, where the markup is a rendered feature.
"""
from __future__ import annotations

import pytest

from identity.validator import validate_name


def test_a_clean_name_passes_untouched():
    v = validate_name("Agriculture, Arizona Department of")
    assert v.ok is True
    assert v.value == "Agriculture, Arizona Department of"
    assert v.stripped is False
    assert v.reason is None


def test_a_leading_bullet_is_a_decoration_and_is_stripped():
    v = validate_name("• General Fund Revenue")
    assert v.ok is True
    assert v.value == "General Fund Revenue"
    assert v.stripped is True


def test_trailing_dot_leaders_and_page_code_are_decorations():
    raw = "• State Personnel Summary by Agency ......................BD-13"
    v = validate_name(raw)
    assert v.ok is True
    assert v.value == "State Personnel Summary by Agency"
    assert v.stripped is True


def test_noise_INSIDE_the_string_quarantines_and_says_why():
    raw = (
        "Osteopathic Examiners in Medicine and Surgery, Arizona ...   342  "
        "Board of........................................"
    )
    v = validate_name(raw)
    assert v.ok is False
    assert "dot leaders" in v.reason


def test_an_embedded_page_number_quarantines():
    v = validate_name("Parents Comm. on Drug Education and Prevention, Arizona  286")
    assert v.ok is False
    assert "page number" in v.reason


def test_a_doubled_internal_space_quarantines():
    v = validate_name("Osteopathic Examiners in Medicine and Surgery, Arizona  Board of")
    assert v.ok is False
    assert "doubled space" in v.reason


def test_over_ninety_characters_quarantines():
    v = validate_name("A" + " b" * 60)
    assert v.ok is False
    assert "too long" in v.reason


def test_an_empty_or_blank_string_quarantines():
    assert validate_name("   ").ok is False


# --- the two rules that were MEASURED and REJECTED -------------------------

def test_an_all_caps_acronym_is_NOT_rejected():
    """Measured 2026-08-16: `AHCCCS` is the ONLY all-caps stored title in the
    corpus, and it is correct. An all-caps rule rejects a right answer."""
    assert validate_name("AHCCCS").ok is True


def test_a_slug_title_is_uninformative_but_NOT_rejected():
    """`AXSACUTE` is 20 documents. The audit's own verdict is "uninformative,
    not wrong" — reported by the check, never quarantined."""
    assert validate_name("AXSACUTE").ok is True


def test_html_in_a_fiscal_note_title_is_NOT_rejected():
    """All 240 HTML-bearing titles are fiscal notes, where `<strike>…</strike>
    (NOW: …)` is how an analyst sees an amended bill. Rejecting it would
    quarantine every amended note on the next refresh."""
    raw = "Fiscal Note - HB 2527: <strike>tax subtraction</strike> (NOW: sales tax)"
    assert validate_name(raw).ok is True
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `cd /home/destin/ask-the-budget-az-worktrees/plan-c && uv run pytest tests/test_identity_validator.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'identity'`

- [ ] **Step 3: Write the implementation**

Create `identity/__init__.py`:

```python
"""Document and agency identity — one validator, one composer, one resolver.

Spec: docs/superpowers/specs/2026-08-16-corpus-identity-consistency-design.md
"""
from identity.validator import Verdict, validate_name  # noqa: F401
```

Create `identity/validator.py`:

```python
"""Does this string look like a name? — with a REASON when it does not.

Two verdicts, and the distinction is load-bearing (spec I3):

* A DECORATION sits at the EDGE of the string and is provably additive.
  `• State Personnel Summary by Agency ......BD-13` is the printed section
  name with the printed page reference attached; removing it is
  deterministic. The alternative was measured and is worse — those summary
  sections have no agency, so quarantining them leaves the composer with
  nothing to build a name from.
* CORRUPTION sits INSIDE the string. `Arizona ... 342 Board of` cannot be
  trimmed back to a name without guessing which half is real, so it
  quarantines. A stripped string is a guess; a rejected one is a question
  with an answer.

Scope is BUDGET documents. Fiscal-note titles are constructed from the bill
number and the note's own heading and have none of the three suppliers this
module exists to distrust.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_NAME_CHARS = 90

# Leading list glyphs JLBC's TOC extraction emits.
_LEADING_GLYPH = re.compile(r"^\s*[•·▪◦*\-–—]\s+")
# A trailing run of >=2 dots, optionally followed by a printed page code
# (BD-13, S-1, 342). Anchored at the END: this is the decoration case.
_TRAILING_DECORATION = re.compile(r"\s*\.{2,}\s*[A-Z]{0,3}-?\d*\s*$")
# Any surviving run of >=2 dots is INSIDE the string.
_INNER_DOT_LEADERS = re.compile(r"\.{2,}")
# A bare integer of 2-4 digits sitting between words — a page number that
# the TOC wrapped into the name. Word-bounded on both sides so a real
# number in a name (none observed, but cheap) is not caught mid-token.
_EMBEDDED_PAGE_NUMBER = re.compile(r"(?<=\s)\d{2,4}(?=\s)")
_DOUBLED_SPACE = re.compile(r"\S {2,}\S")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    value: str
    reason: str | None = None
    stripped: bool = False


def validate_name(raw: str) -> Verdict:
    """Verdict for one identity string. `value` is the usable name when ok."""
    if not isinstance(raw, str):
        return Verdict(False, "", "not a string")

    original = raw
    text = _LEADING_GLYPH.sub("", raw)
    text = _TRAILING_DECORATION.sub("", text)
    text = text.strip()
    stripped = text != original.strip()

    if not text:
        return Verdict(False, "", "empty", stripped)
    if _INNER_DOT_LEADERS.search(text):
        return Verdict(False, text, "contains dot leaders", stripped)
    if _EMBEDDED_PAGE_NUMBER.search(text):
        return Verdict(False, text, "contains an embedded page number", stripped)
    if _DOUBLED_SPACE.search(text):
        return Verdict(False, text, "contains a doubled space", stripped)
    if len(text) > MAX_NAME_CHARS:
        return Verdict(False, text, f"too long (> {MAX_NAME_CHARS} chars)", stripped)
    return Verdict(True, text, None, stripped)
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_validator.py -q`
Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add identity/ tests/test_identity_validator.py
git commit -m "identity: name validator — decorations strip, corruption quarantines (I3)"
```

---

## Task 2: The single read-path resolver

**Files:**
- Create: `identity/resolve.py`, `tests/test_identity_resolve.py`
- Modify: `identity/__init__.py`

**Interfaces:**
- Consumes: `store.documents.load_documents`, `sidecar_title`,
  `humanize_doc_id`.
- Produces: `resolve_title(doc_id: str) -> str` and
  `resolve_titles(doc_ids: Iterable[str]) -> dict[str, str]`. These are the
  ONLY title functions Task 3 wires into the three call sites.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_resolve.py`:

```python
"""ONE title ladder for every surface (spec I12).

Three ladders exist today and they disagree:

| rung | search results | browse listing | AI Mode |
|---|---|---|---|
| 1 | website index title | never consulted | never consulted |
| 2 | sidecar, GATED on ingested_at | sidecar, ungated | sidecar, ungated |
| 3 | humanised doc_id | humanised doc_id | humanised doc_id |

The website index is a HARVEST of somebody else's page and is the supplier
that produced 218 wrong names, so it is demoted below the corpus's own
record. The `ingested_at` gate is dropped with it: it existed only to keep
migration-era titles from beating the index, and measured against the live
corpus it would swap 375 real agency names ("JLBC FY2025 — African-American
Affairs, Arizona Commission of") for doc-id slugs.
"""
from __future__ import annotations

import json

import pytest

from store.documents import reset_documents_cache
from identity.resolve import resolve_title, resolve_titles


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_documents_cache()
    yield tmp_path
    reset_documents_cache()


def _write(data_dir, payload):
    (data_dir / "documents.json").write_text(json.dumps(payload), encoding="utf-8")
    reset_documents_cache()


def test_the_sidecar_title_wins(data_dir):
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "ingested_at": "2026-08-16T00:00:00+00:00",
    }})
    assert resolve_title("jlbc-approps-fy2005-bar") == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_a_migration_era_title_with_no_ingested_at_is_STILL_used(data_dir):
    """375 live documents lack `ingested_at` and most of their titles are
    fine. The old search-page gate would replace this with a doc-id slug."""
    _write(data_dir, {"jlbc-approps-fy2025-aam": {
        "title": "JLBC FY2025 — African-American Affairs, Arizona Commission of",
    }})
    assert resolve_title("jlbc-approps-fy2025-aam") == (
        "JLBC FY2025 — African-American Affairs, Arizona Commission of"
    )


def test_a_missing_document_falls_back_to_the_humanised_doc_id(data_dir):
    _write(data_dir, {})
    assert resolve_title("jlbc-approps-fy2005-bar") == "Jlbc Approps FY 2005 Bar"


def test_a_blank_title_falls_back_rather_than_rendering_empty(data_dir):
    _write(data_dir, {"jlbc-approps-fy2005-bar": {"title": "   "}})
    assert resolve_title("jlbc-approps-fy2005-bar") == "Jlbc Approps FY 2005 Bar"


def test_resolve_titles_reads_the_sidecar_ONCE_and_agrees_with_the_singular(data_dir, monkeypatch):
    """Twenty search rows must not re-parse and re-deepcopy the whole map."""
    _write(data_dir, {
        "a": {"title": "Alpha — FY 2026 Baseline"},
        "b": {"title": "Beta — FY 2026 Baseline"},
    })
    import store.documents as docs_mod

    calls = {"n": 0}
    real = docs_mod._load_cached

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(docs_mod, "_load_cached", counting)
    out = resolve_titles(["a", "b"])
    assert out == {"a": "Alpha — FY 2026 Baseline", "b": "Beta — FY 2026 Baseline"}
    assert calls["n"] == 1
    assert out["a"] == resolve_title("a")
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_identity_resolve.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'identity.resolve'`

- [ ] **Step 3: Write the implementation**

Create `identity/resolve.py`:

```python
"""The ONE read-path title resolver (spec I12).

Every surface calls this. Three ladders existed before it — search results,
the browse listing, and AI Mode — and they disagreed on both of their upper
rungs, which is why the same document could be called one thing on the page
and another inside an answer with no test able to see it.

WHY the website index is not a rung here, when it was rung 1 of the search
page: it is a harvest of JLBC's own index page and it is the supplier that
produced the 218 wrong names (`05app/bar.pdf` → "Agriculture, Arizona
Department of", for the Board of Barbers). The corpus's own record is
repaired from the document's text; the harvest is not. Keeping the harvest
above it would have made the entire title repair invisible on the primary
path — measured, and the reason this module ships before any repair.

The harvest is still repaired in place (spec I6) so that a future re-ingest
cannot re-import a wrong name; it is simply no longer the authority at read
time.

WHY there is no `require_ingested` gate: it existed only as a tiebreak
against the harvest. With the harvest gone the sidecar is the sole source,
and gating it swaps 375 real agency names for doc-id slugs.
"""
from __future__ import annotations

from typing import Iterable

from store.documents import humanize_doc_id, sidecar_title
from store import documents as _docs


def resolve_title(doc_id: str) -> str:
    """Display title for one doc_id. Never empty."""
    meta = _docs._load_cached().get(doc_id)
    return sidecar_title(meta) or humanize_doc_id(doc_id)


def resolve_titles(doc_ids: Iterable[str]) -> dict[str, str]:
    """`resolve_title` over many ids with ONE sidecar read."""
    docs = _docs._load_cached()
    return {
        doc_id: sidecar_title(docs.get(doc_id)) or humanize_doc_id(doc_id)
        for doc_id in doc_ids
    }
```

Append to `identity/__init__.py`:

```python
from identity.resolve import resolve_title, resolve_titles  # noqa: F401
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_resolve.py -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add identity/resolve.py identity/__init__.py tests/test_identity_resolve.py
git commit -m "identity: one read-path title resolver (I12)"
```

---

## Task 3: Wire all three surfaces to the resolver

**Files:**
- Modify: `app/search_provider.py` (the `_info` title expression, ~line 199)
- Modify: `app/routes/corpus.py:221`
- Modify: `harness/tools.py:135`
- Test: `tests/test_identity_resolve.py` (append the agreement gate)

**Interfaces:**
- Consumes: `identity.resolve_title`, `identity.resolve_titles` (Task 2).
- Produces: no new names. After this task no module outside `identity/`
  composes a display title.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_identity_resolve.py`:

```python
def test_all_three_surfaces_return_the_SAME_title(data_dir):
    """Gate G-I4. Its absence is audit Finding 7.

    Drives the three real call sites, not three copies of the ladder:
    the search provider's `_info`, the browse route's title expression,
    and the harness's `_doc_titles`.
    """
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "source_url": "https://www.azjlbc.gov/05app/bar.pdf",
    }})

    from app.search_provider import LanceSearchProvider
    from store.documents import title_for
    from harness import tools as harness_tools

    provider = LanceSearchProvider.__new__(LanceSearchProvider)
    provider._doc_info = None
    provider._doc_info_sig = None
    search_title = provider._info("jlbc-approps-fy2005-bar")["title"]

    browse_title = title_for("jlbc-approps-fy2005-bar")
    ai_title = harness_tools._doc_titles({"jlbc-approps-fy2005-bar"})[
        "jlbc-approps-fy2005-bar"
    ]

    assert search_title == browse_title == ai_title == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_the_website_harvest_no_longer_overrides_a_repaired_title(data_dir, monkeypatch):
    """The regression this whole unit exists to prevent.

    The harvest says "Agriculture" for `05app/bar.pdf`. Before this change
    it won unconditionally on the search page, so repairing the corpus
    changed nothing an analyst saw while the audit script reported zero
    errors.
    """
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "source_url": "https://www.azjlbc.gov/05app/bar.pdf",
    }})
    from app.search_provider import LanceSearchProvider

    monkeypatch.setattr(
        LanceSearchProvider,
        "_load_mockup_index",
        staticmethod(lambda: {
            "https://www.azjlbc.gov/05app/bar.pdf": {
                "url": "https://www.azjlbc.gov/05app/bar.pdf",
                "title": "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
                "category": "Agency Budget Detail",
                "doc_type": "Appropriations Report",
                "fiscal_year": 2005,
            }
        }),
    )
    provider = LanceSearchProvider.__new__(LanceSearchProvider)
    provider._doc_info = None
    provider._doc_info_sig = None
    info = provider._info("jlbc-approps-fy2005-bar")

    assert info["title"] == "Board of Barbers — FY 2005 Appropriations Report"
    # The meta line still comes from the harvest — it is the only source of
    # the category/doc-type sentence and it was never wrong.
    assert info["meta"] == "Agency Budget Detail · Appropriations Report · FY 2005"
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_identity_resolve.py -q`
Expected: FAIL — `test_the_website_harvest_no_longer_overrides_a_repaired_title` asserts "Board of Barbers…" and gets "Agriculture, Arizona Department of…".

- [ ] **Step 3: Change the three call sites**

In `app/search_provider.py`, inside `_info`, replace the title expression:

```python
                    info[did] = {
                        "url": url,
                        # WHY the harvest is no longer rung 1 (2026-08-16):
                        # `index-lite.js` is a scrape of JLBC's index page and
                        # is the SUPPLIER of the 218 wrong names — it records
                        # `05app/bar.pdf` as "Agriculture, Arizona Department
                        # of" for the Board of Barbers. It won unconditionally
                        # here, so repairing the corpus changed nothing on this
                        # page while the audit script read documents.json and
                        # reported zero errors. The harvest still supplies the
                        # meta line, which was never wrong.
                        "title": resolve_title(did),
                        "meta": " · ".join(
```

Add the import near the other `store.documents` imports:

```python
from identity.resolve import resolve_title
```

Leave `_ingest_title` and `_title_from_doc_id` defined but unused ONLY if
another call site still needs them; otherwise delete both aliases and the
now-unused `sidecar_title` / `humanize_doc_id` imports — `tsc`-equivalent
strictness does not apply to Python, but `ruff` will flag them.

In `app/routes/corpus.py`, replace line 221 and its import:

```python
    from store.documents import load_documents
    from identity.resolve import resolve_title
...
            "title": resolve_title(doc_id),
```

In `harness/tools.py`, replace the `_doc_titles` binding at line 135:

```python
# WHY this moved to `identity/` (2026-08-16): three surfaces resolved a
# title three different ways, so the same document could be named one thing
# on the page and another inside an answer, with no test able to compare
# them. `identity.resolve_titles` is now the only ladder. See spec I12.
from identity.resolve import resolve_titles as _doc_titles
```

- [ ] **Step 4: Run the full affected suites**

Run: `uv run pytest tests/test_identity_resolve.py tests/test_search_route.py tests/test_corpus_documents_route.py tests/test_harness_titles.py tests/test_store_documents.py -q`
Expected: PASS. If `tests/test_search_route.py` pins a harvest-derived
title, re-point that assertion at the sidecar title and record why in the
test's docstring — that assertion was encoding the defect.

- [ ] **Step 5: Run the whole suite**

Run: `uv run pytest -q`
Expected: PASS. Note the totals; the baseline before this plan is ~2,900.

- [ ] **Step 6: Commit**

```bash
git add app/search_provider.py app/routes/corpus.py harness/tools.py tests/test_identity_resolve.py
git commit -m "identity: search, browse and AI Mode share one title ladder (I12, G-I4)"
```

---

## Task 4: The measurement instrument

**Files:**
- Create: `eval/identity_check.py`, `tests/test_identity_check.py`

**Interfaces:**
- Consumes: `identity.validate_name`, `identity.resolve_title`,
  `store.chunk_store.ChunkStore`, `store.documents.load_documents`,
  `chunking.agency_catalog`.
- Produces: `check_corpus(...) -> IdentityReport` (dataclass with one field
  per I13 metric plus `findings: list[dict]`), and a
  `python -m eval.identity_check` entry point writing
  `<data_dir>/identity-report.json`. Task 9 reads that file.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_check.py`:

```python
"""The instrument whose ABSENCE let all six defects ship (spec I13).

Runs against injected fixtures, never a real LanceDB directory — the suite
must survive a fresh clone. The real-corpus run is a manual eval step.

Two properties are pinned because getting either wrong makes the number
meaningless:
  * the stamping metric is per DOCUMENT, over all its chunks — a per-chunk
    version reports the boilerplate page of a correct document as an error
    and can never reach zero;
  * the check never reports how many names were produced.
"""
from __future__ import annotations

from eval.identity_check import check_corpus


def _doc(title, url=None, fy=2005, book="Appropriations Report"):
    return {"title": title, "source_url": url, "fiscal_year": fy, "book": book}


def test_a_title_naming_a_different_agency_than_the_text_is_counted():
    report = check_corpus(
        documents={"jlbc-approps-fy2005-bar": _doc(
            "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
            "https://www.azjlbc.gov/05app/bar.pdf",
        )},
        chunks_by_doc={"jlbc-approps-fy2005-bar": [
            "Board of Barbers  Executive Director: Mario J. Herrera",
        ]},
        agency_names={"agency:agr": "Agriculture, Arizona Department of",
                      "agency:bar": "Board of Barbers"},
        stamps_by_doc={"jlbc-approps-fy2005-bar": ["agency:bar"]},
    )
    assert report.title_names_wrong_agency == 1


def test_a_boilerplate_chunk_does_NOT_make_a_correct_document_a_mis_stamp():
    """The document mentions its agency SOMEWHERE. A per-chunk metric would
    count its FOOTNOTES page as an error; this one must not."""
    report = check_corpus(
        documents={"jlbc-approps-fy2026-ost": _doc(
            "Osteopathic Examiners — FY 2026 Appropriations Report",
            "https://www.azjlbc.gov/26ar/ost.pdf",
        )},
        chunks_by_doc={"jlbc-approps-fy2026-ost": [
            "FOOTNOTES",
            "The Board of Osteopathic Examiners licenses physicians.",
        ]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        stamps_by_doc={"jlbc-approps-fy2026-ost": ["agency:ost"]},
    )
    assert report.documents_never_mentioning_stamp == 0


def test_a_document_no_chunk_of_which_mentions_its_stamp_is_counted():
    report = check_corpus(
        documents={"governor-governors-budget-fy2026": _doc("Executive Budget")},
        chunks_by_doc={"governor-governors-budget-fy2026": [
            "General Fund revenue collections exceeded forecast.",
        ]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        stamps_by_doc={"governor-governors-budget-fy2026": ["agency:ost"]},
    )
    assert report.documents_never_mentioning_stamp == 1


def test_titles_outside_the_format_are_counted():
    report = check_corpus(
        documents={
            "a": _doc("Medical Board, Arizona"),
            "b": _doc("JLBC FY2025 — Agriculture, Arizona Department of"),
            "c": _doc("Agriculture, Arizona Department of — FY 2005 Appropriations Report"),
        },
        chunks_by_doc={"a": [""], "b": [""], "c": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.titles_outside_format == 2


def test_duplicate_titles_are_counted_as_a_CROSS_CHECK_not_a_second_proof():
    report = check_corpus(
        documents={
            "jlbc-approps-fy2005-agr": _doc("Agriculture — FY 2005 Appropriations Report"),
            "jlbc-approps-fy2005-bar": _doc("Agriculture — FY 2005 Appropriations Report"),
        },
        chunks_by_doc={"jlbc-approps-fy2005-agr": [""], "jlbc-approps-fy2005-bar": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.duplicate_titles == 2


def test_a_slug_title_is_REPORTED_and_never_counted_as_a_failure():
    report = check_corpus(
        documents={"jlbc-approps-fy2005-axsacute": _doc(
            "AXSACUTE — FY 2005 Appropriations Report")},
        chunks_by_doc={"jlbc-approps-fy2005-axsacute": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    assert report.uninformative_titles == 1
    assert report.titles_outside_format == 0
    assert report.validator_failures == 0


def test_the_report_never_carries_a_production_count():
    """Gate on the ERROR rate, never coverage — spec I13, and the specific
    lesson the citation work paid for."""
    report = check_corpus(
        documents={"a": _doc("Alpha — FY 2026 Baseline")},
        chunks_by_doc={"a": [""]},
        agency_names={},
        stamps_by_doc={},
    )
    fields = report.as_dict().keys()
    assert not any(
        k for k in fields
        if "produced" in k or "coverage" in k or "linked" in k
    )
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_identity_check.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.identity_check'`

- [ ] **Step 3: Write the implementation**

Create `eval/identity_check.py`:

```python
"""The identity ERROR-RATE instrument (spec I13, gate G-I2).

Offline, free, seconds, over data already on disk — the shape
`eval/false_link_check.py` proved for citations. The reason six naming
defects shipped under ~2,900 passing tests is that every check in this
codebase is per-item and correct while NOTHING compares items to each
other. This is that missing comparison.

Two design rules, each bought with a measured mistake:

* **The stamping metric is per DOCUMENT, over all of its chunks.** Measured
  2026-08-16: a per-chunk version counts the `FOOTNOTES` page of a genuinely
  osteopathic document as a mis-stamp, so it can never reach zero and its
  target would be a lie.
* **No production count is ever reported.** "How many names did we make"
  rises as the rules get looser. Only the error rate can see a matcher
  getting worse.

Usage:
    uv run python -m eval.identity_check [--data-dir PATH] [--json PATH]

Writes `<data_dir>/identity-report.json`, which the admin page's
Needs-attention group renders (spec I15).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping

from identity.validator import validate_name

_FORMAT_RE = re.compile(r" — FY \d{4} .+$")
# A title that is the document's own slug shouted back at it.
_SLUG_TITLE_RE = re.compile(r"^[A-Z0-9&]{4,}(?= — FY |$)")


@dataclass
class IdentityReport:
    title_names_wrong_agency: int = 0
    documents_never_mentioning_stamp: int = 0
    validator_failures: int = 0
    titles_outside_format: int = 0
    duplicate_titles: int = 0
    doc_id_family_contradicts_url: int = 0
    uninformative_titles: int = 0
    distinct_agency_slugs: int = 0
    catalogued_agencies: int = 0
    findings: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "title_names_wrong_agency": self.title_names_wrong_agency,
            "documents_never_mentioning_stamp": self.documents_never_mentioning_stamp,
            "validator_failures": self.validator_failures,
            "titles_outside_format": self.titles_outside_format,
            "duplicate_titles": self.duplicate_titles,
            "doc_id_family_contradicts_url": self.doc_id_family_contradicts_url,
            "uninformative_titles": self.uninformative_titles,
            "distinct_agency_slugs": self.distinct_agency_slugs,
            "catalogued_agencies": self.catalogued_agencies,
            "findings": self.findings,
        }


def _distinctive(name: str) -> set[str]:
    """Content words of an agency name, for "does this title name it?"."""
    stop = {"of", "the", "and", "arizona", "state", "department", "office",
            "board", "commission", "az", "for", "fy"}
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in stop}


def check_corpus(
    *,
    documents: Mapping[str, Mapping[str, Any]],
    chunks_by_doc: Mapping[str, Iterable[str]],
    agency_names: Mapping[str, str],
    stamps_by_doc: Mapping[str, Iterable[str]],
) -> IdentityReport:
    """Every I13 metric, computed from already-loaded data.

    Pure function of its arguments so the suite can drive it with fixtures
    and never open a LanceDB directory.
    """
    report = IdentityReport(
        catalogued_agencies=len(agency_names),
        distinct_agency_slugs=len({
            a.split(":", 1)[-1] for ids in stamps_by_doc.values() for a in ids
        }),
    )

    title_counts = Counter(
        (d.get("title") or "") for d in documents.values() if d.get("title")
    )

    for doc_id, meta in documents.items():
        title = (meta.get("title") or "").strip()
        text = " \n".join(chunks_by_doc.get(doc_id, [])).lower()
        stamps = list(stamps_by_doc.get(doc_id, []))

        if _SLUG_TITLE_RE.match(title):
            report.uninformative_titles += 1
        elif title and not _FORMAT_RE.search(title):
            report.titles_outside_format += 1
            report.findings.append(
                {"doc_id": doc_id, "kind": "title-format", "title": title}
            )

        if title and title_counts[title] > 1:
            report.duplicate_titles += 1

        verdict = validate_name(title.split(" — FY ")[0]) if title else None
        if verdict is not None and not verdict.ok:
            report.validator_failures += 1
            report.findings.append(
                {"doc_id": doc_id, "kind": "invalid-name",
                 "title": title, "reason": verdict.reason}
            )

        # Per-DOCUMENT stamping check.
        for agency_id in stamps:
            name = agency_names.get(agency_id)
            if not name:
                continue
            words = _distinctive(name)
            if words and not any(w in text for w in words):
                report.documents_never_mentioning_stamp += 1
                report.findings.append(
                    {"doc_id": doc_id, "kind": "stamp-unmentioned",
                     "agency": agency_id}
                )
                break

        # Does the TITLE name a different agency than the document's own
        # stamp? Only meaningful when the stamp itself is corroborated by
        # the text — otherwise this double-counts the stamping metric.
        stamped_names = [agency_names[a] for a in stamps if a in agency_names]
        if title and stamped_names:
            own = _distinctive(stamped_names[0])
            titled = _distinctive(title)
            corroborated = bool(own) and any(w in text for w in own)
            if corroborated and titled and own and not (own & titled):
                other = [
                    aid for aid, nm in agency_names.items()
                    if aid not in stamps and _distinctive(nm) & titled
                ]
                if other:
                    report.title_names_wrong_agency += 1
                    report.findings.append(
                        {"doc_id": doc_id, "kind": "title-wrong-agency",
                         "title": title, "stamped": stamps[0],
                         "titled": other[0]}
                    )

    for doc_id, meta in documents.items():
        url = (meta.get("source_url") or "").lower()
        if not url:
            continue
        if doc_id.startswith("jlbc-approps-") and "baseline" in url:
            report.doc_id_family_contradicts_url += 1
        elif doc_id.startswith("jlbc-baseline-") and re.search(r"/\d{2}ar/", url):
            report.doc_id_family_contradicts_url += 1

    return report


def _load_live(data_dir: Path | None) -> IdentityReport:
    """Assemble the arguments from the real corpus. Not unit-tested — it is
    I/O, and the logic it feeds is."""
    from chunking.agency_catalog import load_agency_names
    from store.chunk_store import ChunkStore
    from store.documents import load_documents

    documents = load_documents()
    store = ChunkStore()
    chunks_by_doc: dict[str, list[str]] = defaultdict(list)
    stamps_by_doc: dict[str, set[str]] = defaultdict(set)
    for row in store.scan(
        "budget_chunks", ["doc_id", "text", "agency_canonical_ids"]
    ):
        chunks_by_doc[row["doc_id"]].append(row.get("text") or "")
        for a in row.get("agency_canonical_ids") or []:
            stamps_by_doc[row["doc_id"]].add(a)

    return check_corpus(
        documents=documents,
        chunks_by_doc=chunks_by_doc,
        agency_names=load_agency_names(),
        stamps_by_doc=stamps_by_doc,
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--data-dir", type=Path, default=None)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    report = _load_live(args.data_dir)
    payload = report.as_dict()

    out = args.json
    if out is None:
        from store.config import data_dir as _dd
        out = Path(_dd()) / "identity-report.json"
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=1), encoding="utf-8")
    tmp.replace(out)

    for k, v in payload.items():
        if k != "findings":
            print(f"{k}: {v}")
    print(f"findings: {len(payload['findings'])}  →  {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

If `chunking/agency_catalog.py` exposes no `load_agency_names`, add one
there returning `{canonical_id: canonical_name}` — do not inline a second
YAML parse.

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_check.py -q`
Expected: PASS, 7 passed.

- [ ] **Step 5: Run it against the real corpus and record the baseline**

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m eval.identity_check --json eval/results/identity-2026-08-16-baseline.json`

Expected, from the audit — **these are the numbers "fix the labels" is calibrated
against, so record what you actually get even if it differs**:

```
title_names_wrong_agency: ~218
documents_never_mentioning_stamp: ~721
titles_outside_format: ~506
duplicate_titles: 218
doc_id_family_contradicts_url: 22
uninformative_titles: ~20
```

If a number differs from the audit by more than ~5%, **stop and reconcile
before continuing** — either the metric is wrong or the corpus moved, and
both change what the later tasks are aiming at.

- [ ] **Step 6: Commit**

```bash
git add eval/identity_check.py tests/test_identity_check.py eval/results/identity-2026-08-16-baseline.json
git commit -m "eval: identity error-rate check + committed baseline (I13)"
```

---

## Task 5: The title composer

**Files:**
- Create: `identity/compose.py`, `tests/test_identity_compose.py`
- Modify: `identity/__init__.py`

**Interfaces:**
- Consumes: `identity.validator.validate_name` (Task 1).
- Produces: `compose_title(*, name, fiscal_year, book, distinguisher=None)
  -> str` and `resolve_supplier_disagreement(*, supplied, stamp_name,
  doc_text) -> tuple[str, str | None]` returning `(chosen_name, note)`.
  Task 6 and Task 7 both call these.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_compose.py`:

```python
"""Compose `{Name} — FY {year} {Book}` (spec I5) and settle supplier
disagreements (spec I1).

4,950 documents already use this format; this makes the minority match the
majority rather than re-titling the majority.

The uniqueness rule is not decoration. Measured 2026-08-16: 77 documents in
30 groups have a parent agency and one of its sub-programmes in the same
book and year (`doa` with `doa-apf`; `des` with `desage`, `desdd`, …). If
both compose from the same agency name they become two indistinguishable
rows — a NEW defect manufactured by the fix, which the duplicate-title
metric would then report as a failure.
"""
from __future__ import annotations

from identity.compose import compose_title, resolve_supplier_disagreement


def test_the_house_format():
    assert compose_title(
        name="Board of Barbers", fiscal_year=2005, book="Appropriations Report"
    ) == "Board of Barbers — FY 2005 Appropriations Report"


def test_a_decorated_name_is_stripped_before_composing():
    assert compose_title(
        name="• General Fund Revenue ......400",
        fiscal_year=2027,
        book="Appropriations Report",
    ) == "General Fund Revenue — FY 2027 Appropriations Report"


def test_a_corrupt_name_refuses_rather_than_guessing():
    import pytest

    with pytest.raises(ValueError) as e:
        compose_title(
            name="Osteopathic Examiners, Arizona ...  342  Board of...",
            fiscal_year=2026,
            book="Appropriations Report",
        )
    assert "dot leaders" in str(e.value)


def test_a_distinguisher_is_appended_when_one_is_supplied():
    """The sub-programme case: parent and child in the same book and year."""
    assert compose_title(
        name="Administration, Arizona Department of",
        fiscal_year=2016,
        book="Appropriations Report",
        distinguisher="Automation Projects Fund",
    ) == (
        "Administration, Arizona Department of (Automation Projects Fund) "
        "— FY 2016 Appropriations Report"
    )


def test_the_stamp_beats_the_supplier_when_they_disagree():
    chosen, note = resolve_supplier_disagreement(
        supplied="Agriculture, Arizona Department of",
        stamp_name="Board of Barbers",
        doc_text="Board of Barbers  Executive Director: Mario J. Herrera",
    )
    assert chosen == "Board of Barbers"
    assert note is not None and "Agriculture" in note


def test_agreement_records_nothing():
    chosen, note = resolve_supplier_disagreement(
        supplied="Board of Barbers",
        stamp_name="Board of Barbers",
        doc_text="Board of Barbers  Executive Director: Mario J. Herrera",
    )
    assert chosen == "Board of Barbers"
    assert note is None


def test_an_UNCORROBORATED_stamp_does_not_overrule_the_supplier():
    """I1: one witness is never sufficient. If the document's own text does
    not back the stamp, there is no second witness and nothing is repaired."""
    chosen, note = resolve_supplier_disagreement(
        supplied="Agriculture, Arizona Department of",
        stamp_name="Osteopathic Examiners",
        doc_text="General Fund revenue collections exceeded forecast.",
    )
    assert chosen == "Agriculture, Arizona Department of"
    assert note is not None and "not corroborated" in note
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_identity_compose.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'identity.compose'`

- [ ] **Step 3: Write the implementation**

Create `identity/compose.py`:

```python
"""Build a document's display name, and settle supplier disagreements.

Spec I5 (one format, and it must be unique) and I1 (two witnesses).

WHY the stamp beats the supplier: measured 2026-08-16 over the 218
mis-titled documents, the agency STAMP was correct in every case where the
TITLE was wrong (`jlbc-approps-fy2005-bar` is stamped `agency:bar` and
titled "Agriculture"). The document already knows who it is; only the field
taken from a third party is wrong.

WHY an uncorroborated stamp does NOT overrule the supplier: that is one
witness, and one witness is precisely today's behaviour and the cause of
every finding in the audit. Where the stamp is the broken witness — the 721
`ost` documents — composing from it would write the error into the title.
"""
from __future__ import annotations

import re

from identity.validator import validate_name


def compose_title(
    *,
    name: str,
    fiscal_year: int,
    book: str,
    distinguisher: str | None = None,
) -> str:
    """`{Name} — FY {year} {Book}`, raising on a name that cannot be trusted."""
    verdict = validate_name(name)
    if not verdict.ok:
        raise ValueError(f"unusable name {name!r}: {verdict.reason}")
    stem = verdict.value
    if distinguisher:
        d = validate_name(distinguisher)
        stem = f"{stem} ({d.value if d.ok else distinguisher.strip()})"
    return f"{stem} — FY {fiscal_year} {book}"


def _distinctive(name: str) -> set[str]:
    stop = {"of", "the", "and", "arizona", "state", "department", "office",
            "board", "commission", "az", "for", "fy"}
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in stop}


def resolve_supplier_disagreement(
    *, supplied: str, stamp_name: str | None, doc_text: str
) -> tuple[str, str | None]:
    """(chosen name, note) — the note is the I8 reversal record's reason."""
    if not stamp_name:
        return supplied, None

    stamp_words = _distinctive(stamp_name)
    supplied_words = _distinctive(supplied)
    if stamp_words & supplied_words:
        return supplied, None

    text = (doc_text or "").lower()
    corroborated = bool(stamp_words) and any(w in text for w in stamp_words)
    if not corroborated:
        return supplied, (
            f"supplier said {supplied!r}, stamp said {stamp_name!r}, and the "
            "stamp is not corroborated by the document text — left unchanged"
        )
    return stamp_name, (
        f"supplier said {supplied!r}; the document's own text says "
        f"{stamp_name!r} — stamp wins (2 witnesses to 1)"
    )
```

Append to `identity/__init__.py`:

```python
from identity.compose import compose_title, resolve_supplier_disagreement  # noqa: F401
```

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_compose.py -q`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add identity/compose.py identity/__init__.py tests/test_identity_compose.py
git commit -m "identity: title composer with uniqueness + two-witness rule (I1, I5)"
```

---

## Task 6: Compose the suffix in the probe ladder

**Files:**
- Modify: `ingest/book_discovery.py` (lines ~275 and ~284)
- Test: `tests/test_book_discovery.py` (append)

**Interfaces:**
- Consumes: `identity.compose.compose_title` (Task 5).
- Produces: no new names. `PlannedDocument.title` is now always in the
  house format for the probe path, as it already is for the catalog path.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_book_discovery.py`:

```python
def test_the_probe_ladder_composes_the_house_title_format():
    """The 2026-08-16 defect (spec I6).

    The CATALOG path hands over an already-composed website title, which is
    why it produced 4,950 good names. The PROBE ladder handed over
    `entry.name` raw, which is why the same downstream code produced 131
    titles with no suffix — "Medical Board, Arizona" instead of "Medical
    Board, Arizona — FY 2027 Appropriations Report". The names were never
    the problem; the composition was.
    """
    from ingest.book_discovery import _document_from_agency_entry

    doc = _document_from_agency_entry(
        _AgencyEntry(name="Medical Board, Arizona", slug="med",
                    url="https://www.azjlbc.gov/27ar/med.pdf"),
        fiscal_year=2027,
        family="approps",
    )
    assert doc.title == "Medical Board, Arizona — FY 2027 Appropriations Report"


def test_a_bulleted_section_name_keeps_its_words():
    """A summary section has no agency, so quarantining it would leave the
    composer with nothing. The bullet and the printed page code are
    decorations and strip deterministically."""
    from ingest.book_discovery import _document_from_section_entry

    doc = _document_from_section_entry(
        _SectionEntry(
            title="• Summary of Rent Charges ...............372",
            filename="372.pdf",
            url="https://www.azjlbc.gov/27ar/372.pdf",
        ),
        fiscal_year=2027,
        family="approps",
    )
    assert doc.title == "Summary of Rent Charges — FY 2027 Appropriations Report"
```

Adapt `_AgencyEntry` / `_SectionEntry` and the two helper names to whatever
`ingest/book_discovery.py` actually defines at lines 275 and 284 — read
those lines first and mirror the real constructors. If the title is built
inline rather than in a helper, **extract the two inline expressions into
`_document_from_agency_entry` / `_document_from_section_entry` first**, in
its own commit, with no behaviour change; a test cannot pin an expression
buried in a comprehension.

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_book_discovery.py -q`
Expected: FAIL — the titles come back as `"Medical Board, Arizona"` and
`"• Summary of Rent Charges ...............372"`.

- [ ] **Step 3: Implement**

At both sites, replace the raw hand-over with a composed title:

```python
        # WHY compose here and not in `build_title` (2026-08-16): the CATALOG
        # path already hands over a fully-composed website title, so the same
        # downstream line produced 4,950 correct names and 131 wrong ones.
        # The defect is that this path hands over a raw scraped string. The
        # route, the job and `build_title` are all correct — see spec I6, and
        # note the chain runs books.py:152 → job.user_title →
        # ingest/worker.py:1154 → build_title.
        title=compose_title(
            name=entry.name or entry.slug,
            fiscal_year=fiscal_year,
            book=_BOOK_LABEL[family],
        ),
```

with, at module level:

```python
from identity.compose import compose_title

_BOOK_LABEL = {"approps": "Appropriations Report", "baseline": "Baseline"}
```

Wrap each call in `try/except ValueError` and fall back to the raw string
plus an advisory note — **a bad name must never block the document** (I4).

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_book_discovery.py tests/test_books_route.py -q`
Expected: PASS.

- [ ] **Step 5: Run the Layer 1 eval — `ingest/` is on the changed path**

Run a CONTROL first, on the same corpus, the same day:

```bash
git stash && JLBC_DATA_DIR=data/insight-data uv run python -m eval.run_eval && git stash pop
JLBC_DATA_DIR=data/insight-data uv run python -m eval.run_eval
```

Expected: identical recall@5 / @15 / @20. This change cannot move
retrieval — it renames documents that are not yet ingested — so any
movement is corpus drift and must be reconciled, not accepted.

- [ ] **Step 6: Commit**

```bash
git add ingest/book_discovery.py tests/test_book_discovery.py eval/results/
git commit -m "ingest: probe ladder composes the house title format (I6)"
```

---

## Task 7: The title repair pass

**Files:**
- Create: `identity/repair.py`, `tests/test_identity_repair.py`

**Interfaces:**
- Consumes: `identity.compose.compose_title`,
  `resolve_supplier_disagreement`, `store.documents.load_documents`.
- Produces: `repair_titles(*, documents, chunks_by_doc, agency_names,
  stamps_by_doc, dry_run=True) -> RepairResult` with
  `.changes: list[dict]` (doc_id, field, before, after, reason) and
  `.skipped: list[dict]`; plus `python -m identity.repair`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_identity_repair.py`:

```python
"""Repair stored titles — a documents.json edit, nothing more (spec I7).

The title is NOT a chunk column: `store/schema.py` carries doc_id,
agency_canonical_ids, fiscal_year, doc_type, publisher, section_path and
the fund fields, and `title` lives only in `documents.json`. So this pass
takes no ingest lock, needs no snapshot, never calls `upsert_chunks`, and
cannot lose a chunk_id. Those hazards belong to the re-stamp and the
doc_id rename ("fix the labels").
"""
from __future__ import annotations

import json

from identity.repair import repair_titles

_DOCS = {
    "jlbc-approps-fy2005-bar": {
        "title": "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
        "fiscal_year": 2005,
        "source_url": "https://www.azjlbc.gov/05app/bar.pdf",
    },
    "jlbc-approps-fy2005-agr": {
        "title": "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
        "fiscal_year": 2005,
        "source_url": "https://www.azjlbc.gov/05app/agr.pdf",
    },
}
_CHUNKS = {
    "jlbc-approps-fy2005-bar": ["Board of Barbers  Executive Director: M. Herrera"],
    "jlbc-approps-fy2005-agr": ["Arizona Department of Agriculture  Director: M. Smith"],
}
_NAMES = {"agency:bar": "Board of Barbers",
          "agency:agr": "Agriculture, Arizona Department of"}
_STAMPS = {"jlbc-approps-fy2005-bar": ["agency:bar"],
           "jlbc-approps-fy2005-agr": ["agency:agr"]}


def test_the_wrong_title_is_repaired_and_the_right_one_is_left_alone():
    result = repair_titles(
        documents=_DOCS, chunks_by_doc=_CHUNKS,
        agency_names=_NAMES, stamps_by_doc=_STAMPS, dry_run=True,
    )
    changed = {c["doc_id"]: c for c in result.changes}
    assert set(changed) == {"jlbc-approps-fy2005-bar"}
    assert changed["jlbc-approps-fy2005-bar"]["after"] == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_every_change_carries_a_reversal_record(tmp_path):
    """Spec I8 — an analyst who disputes a name can see why it changed, and
    the whole pass reverses without restoring a snapshot."""
    result = repair_titles(
        documents=_DOCS, chunks_by_doc=_CHUNKS,
        agency_names=_NAMES, stamps_by_doc=_STAMPS, dry_run=True,
    )
    c = result.changes[0]
    assert set(c) >= {"doc_id", "field", "before", "after", "reason"}
    assert c["field"] == "title"
    assert c["before"] != c["after"]
    assert "witness" in c["reason"] or "stamp wins" in c["reason"]


def test_a_repair_never_creates_a_duplicate_title():
    """Two sub-programme documents of one agency in one book and year.
    Composing both from the agency name would make them indistinguishable —
    77 real documents are in this shape."""
    docs = {
        "jlbc-approps-fy2016-doa": {
            "title": "ADOA", "fiscal_year": 2016,
            "source_url": "https://www.azjlbc.gov/16ar/doa.pdf"},
        "jlbc-approps-fy2016-doa-apf": {
            "title": "ADOA - Automation Projects Fund", "fiscal_year": 2016,
            "source_url": "https://www.azjlbc.gov/16ar/doa-apf.pdf"},
    }
    chunks = {
        "jlbc-approps-fy2016-doa": ["Arizona Department of Administration"],
        "jlbc-approps-fy2016-doa-apf": ["Arizona Department of Administration"],
    }
    stamps = {"jlbc-approps-fy2016-doa": ["agency:doa"],
              "jlbc-approps-fy2016-doa-apf": ["agency:doa"]}
    result = repair_titles(
        documents=docs, chunks_by_doc=chunks,
        agency_names={"agency:doa": "Administration, Arizona Department of"},
        stamps_by_doc=stamps, dry_run=True,
    )
    after = {c["doc_id"]: c["after"] for c in result.changes}
    for doc_id, meta in docs.items():
        after.setdefault(doc_id, meta["title"])
    assert len(set(after.values())) == 2, after


def test_an_uncorroborated_stamp_is_SKIPPED_not_repaired():
    docs = {"governor-governors-budget-fy2026": {
        "title": "FY 2026 State Agency Detail — Arizona Executive Budget",
        "fiscal_year": 2026, "source_url": "https://azgovernor.gov/x.pdf"}}
    result = repair_titles(
        documents=docs,
        chunks_by_doc={"governor-governors-budget-fy2026": ["General Fund revenue"]},
        agency_names={"agency:ost": "Osteopathic Examiners"},
        stamps_by_doc={"governor-governors-budget-fy2026": ["agency:ost"]},
        dry_run=True,
    )
    assert result.changes == []
    assert result.skipped and "not corroborated" in result.skipped[0]["reason"]


def test_writing_is_atomic_and_only_touches_the_title(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    from store.documents import reset_documents_cache

    path = tmp_path / "documents.json"
    path.write_text(json.dumps(_DOCS), encoding="utf-8")
    reset_documents_cache()

    repair_titles(
        documents=_DOCS, chunks_by_doc=_CHUNKS,
        agency_names=_NAMES, stamps_by_doc=_STAMPS, dry_run=False,
    )
    written = json.loads(path.read_text(encoding="utf-8"))
    assert written["jlbc-approps-fy2005-bar"]["title"] == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )
    assert written["jlbc-approps-fy2005-bar"]["source_url"] == (
        "https://www.azjlbc.gov/05app/bar.pdf"
    )
    assert not list(tmp_path.glob("*.tmp"))
    reset_documents_cache()
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_identity_repair.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'identity.repair'`

- [ ] **Step 3: Write the implementation**

Create `identity/repair.py` implementing `repair_titles` with, in order:
compose a candidate for every document from its corroborated stamp via
`resolve_supplier_disagreement`; group candidates by `(book, fiscal_year)`
and, where a candidate collides, re-compose with the document's own slug as
the `distinguisher`; emit one change record per document whose title
actually moves; write with tmp+`os.replace` through the existing
`store.config` writer when `dry_run=False`; and write the reversal record
to `<data_dir>/identity-repairs-<UTC>.json`.

**Do not import `ingest.lock` and do not call `store.backup.snapshot()`.**
Reviewers will expect them by analogy with the ingest path; they are wrong
here and the docstring must say why (the title is not a chunk column).

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_identity_repair.py -q`
Expected: PASS, 5 passed.

- [ ] **Step 5: Dry-run against the real corpus and READ the diff**

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m identity.repair --dry-run --out /tmp/identity-dry-run.json`

Then read at least 25 proposed changes by hand, spread across FY2005,
FY2015 and FY2027. **Do not skip this.** ~950 names change and the review
gate for that is a person reading them, not a passing test.

- [ ] **Step 6: Apply, then re-measure**

```bash
JLBC_DATA_DIR=data/insight-data uv run python -m identity.repair --apply
JLBC_DATA_DIR=data/insight-data uv run python -m eval.identity_check --json eval/results/identity-after-title-repair.json
```

Expected against Task 4's baseline: `title_names_wrong_agency` → 0,
`titles_outside_format` → 0, `duplicate_titles` → 0,
`documents_never_mentioning_stamp` **unchanged** (that is "fix the labels").

- [ ] **Step 7: Commit**

```bash
git add identity/repair.py tests/test_identity_repair.py eval/results/identity-after-title-repair.json
git commit -m "identity: title repair pass — sidecar only, with a reversal record (I7, I8)"
```

---

## Task 8: Repair the two suppliers and the agency catalog

**Files:**
- Create: `scripts/repair_supplier_titles.py`
- Modify: `data/jlbc-book-catalog.json`,
  `webapp/reference/assets/search/index-lite.js`,
  `samples/entity-catalog.yaml`
- Test: `tests/test_agency_catalog.py` (append), `tests/test_book_catalog.py` (append)

**Interfaces:**
- Consumes: `identity.validator.validate_name`, and the repair records
  written by Task 7.
- Produces: no importable names. This task's output is data.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_agency_catalog.py`:

```python
def test_no_catalogued_agency_name_fails_the_validator():
    """The 3 canonical names and 31 variants carrying a PDF artefact (spec
    I3). `agency:ost`'s canonical_name is a table-of-contents ROW — dot
    leaders, page number 342, and the name wrapped onto a second line — and
    it is what `list_filter_values` shows the MODEL.
    """
    from chunking.agency_catalog import load_agency_names
    from identity.validator import validate_name

    bad = {
        aid: (name, validate_name(name).reason)
        for aid, name in load_agency_names().items()
        if not validate_name(name).ok
    }
    assert bad == {}, bad
```

Append to `tests/test_book_catalog.py`:

```python
def test_no_catalogued_book_title_names_a_different_agency_than_its_slug():
    """The supplier of the 218 wrong names (spec I6).

    `data/jlbc-book-catalog.json` records `05app/bar.pdf` (the Board of
    Barbers) as "Agriculture, Arizona Department of". Un-repaired, the next
    ingest of any pre-2013 edition re-imports it, and the identity check
    finds the same defect forever.
    """
    import json
    from pathlib import Path

    catalog = json.loads(
        Path("data/jlbc-book-catalog.json").read_text(encoding="utf-8")
    )
    offenders = []
    for key, edition in catalog["editions"].items():
        seen = {}
        for entry in edition.get("per_agency", []):
            title = entry["title"].split(" — FY ")[0]
            if title in seen:
                offenders.append((key, seen[title], entry["code"], title))
            seen[title] = entry["code"]
    assert offenders == [], offenders[:10]
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_agency_catalog.py tests/test_book_catalog.py -q`
Expected: FAIL — the agency test reports `agency:ost`, `agency:nci`,
`agency:apc`; the catalog test reports `('approps-fy2005', 'agr', 'bar',
'Agriculture, Arizona Department of')` among others.

- [ ] **Step 3: Repair `samples/entity-catalog.yaml` by hand**

Three `canonical_name` values and 31 `names_observed_jlbc` keys. Load the
file with `ruamel.yaml` **only if it is already a dependency** — otherwise
edit by hand; 34 strings is not worth a new dependency. The three canonical
repairs:

```yaml
- canonical_name: Osteopathic Examiners in Medicine and Surgery, Arizona Board of
- canonical_name: Assisted Living Facility Managers, Board of
- canonical_name: Parents Commission on Drug Education and Prevention, Arizona
```

**Do NOT expect this to change any stamp.** Measured 2026-08-16: repairing
these strings changes the stamping outcome by zero, because the over-match
comes from `token_set_ratio`, not from the string — and for the phrase
`Board of` the repaired name scores **higher** (76.9 → 100). That is "fix the labels"
(I2). This repair is for the name the MODEL is shown by
`list_filter_values`, and record that in the commit message so nobody later
reads it as the stamping fix.

- [ ] **Step 4: Write the supplier regenerator**

Create `scripts/repair_supplier_titles.py`: read the corpus's repaired
`documents.json`, join to each supplier row on `source_url`
(case-insensitive, exactly as `search_provider._info` does), and rewrite
the supplier's `title` to the corpus title. Preserve every other field and
the files' exact serialization —`index-lite.js` must remain
`window.JLBC_DOCS=[…];` on one line, or the webapp's parser
(`raw.split("=", 1)[1].strip().rstrip(";")`) breaks.

Run it:

```bash
JLBC_DATA_DIR=data/insight-data uv run python scripts/repair_supplier_titles.py --apply
git diff --stat data/jlbc-book-catalog.json webapp/reference/assets/search/index-lite.js
```

- [ ] **Step 5: Run the tests and the webapp build**

```bash
uv run pytest tests/test_agency_catalog.py tests/test_book_catalog.py -q
cd webapp && npm run build && cd ..
```

Expected: PASS, and a clean build (the index file is vendored data the SPA
reads at runtime, so a malformed rewrite shows up here).

- [ ] **Step 6: Run the full suite and the Layer 1 eval**

```bash
uv run pytest -q
JLBC_DATA_DIR=data/insight-data uv run python -m eval.run_eval
```

Expected: suite green; eval identical to Task 6's — the agency catalog is
read by `chunking/`, so this is on the changed path even though no stamp
should move.

- [ ] **Step 7: Commit**

```bash
git add samples/entity-catalog.yaml data/jlbc-book-catalog.json \
        webapp/reference/assets/search/index-lite.js \
        scripts/repair_supplier_titles.py tests/ eval/results/
git commit -m "identity: repair the two supplier files + 34 catalog names (I6)

The catalog repair fixes the name list_filter_values shows the MODEL. It is
NOT the stamping fix — measured, repairing these strings changes stamping by
zero, and for 'Board of' the repaired name scores 76.9 -> 100. See spec I2."
```

---

## Task 9: Surface findings, and run the check after every ingest

**Files:**
- Modify: `ingest/worker.py` (advisory line, I4), `app/routes/admin.py` (I15)
- Test: `tests/test_admin_attention_route.py` (append),
  `tests/test_worker_agency_title.py` (append)

**Interfaces:**
- Consumes: `eval.identity_check.check_corpus` (Task 4),
  `identity.validator.validate_name` (Task 1).
- Produces: `GET /api/admin/attention` gains an `identity` block:
  `{"findings": int, "report_path": str, "generated_at": str}`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_admin_attention_route.py`:

```python
def test_identity_findings_appear_in_needs_attention(tmp_path, monkeypatch):
    """Spec I15 — a flag nobody sees is the FY2024-AFR failure again: a held
    document looks exactly like a missing one, and so does an unread flag."""
    import json

    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "identity-report.json").write_text(json.dumps({
        "title_names_wrong_agency": 2,
        "findings": [
            {"doc_id": "jlbc-approps-fy2005-bar", "kind": "title-wrong-agency"},
            {"doc_id": "jlbc-approps-fy2027-ost", "kind": "invalid-name"},
        ],
    }), encoding="utf-8")

    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app(ingest_worker=None)) as client:
        body = client.get("/api/admin/attention").json()
    assert body["identity"]["findings"] == 2


def test_a_missing_identity_report_is_not_an_error(tmp_path, monkeypatch):
    """A fresh install has never run the check. Absence reports zero, it does
    not 500 the whole Needs-attention group."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    from fastapi.testclient import TestClient
    from app.main import create_app

    with TestClient(create_app(ingest_worker=None)) as client:
        r = client.get("/api/admin/attention")
    assert r.status_code == 200
    assert r.json()["identity"]["findings"] == 0
```

Append to `tests/test_worker_agency_title.py`:

```python
def test_a_bad_supplied_name_does_not_block_the_document(tmp_path):
    """Spec I4. `ingest/validate.py` already works this way and has already
    caught a real defect. The alternative — holding the document — is what
    happened to the FY2024 AFR, which sat invisible for weeks because a held
    document looks exactly like a missing one."""
    from identity.validator import validate_name

    verdict = validate_name("Osteopathic Examiners, Arizona ... 342 Board of...")
    assert verdict.ok is False
    # The worker records the reason and keeps going; it never raises.
    note = f"supplied name looked wrong ({verdict.reason}); used the document's own name"
    assert "dot leaders" in note
```

- [ ] **Step 2: Run the tests and verify they fail**

Run: `uv run pytest tests/test_admin_attention_route.py tests/test_worker_agency_title.py -q`
Expected: FAIL — `KeyError: 'identity'`.

- [ ] **Step 3: Implement**

In `app/routes/admin.py`'s attention handler, read
`<data_dir>/identity-report.json` with the house pattern already used for
`notices.json` — mtime-checked cache, degrade to `{}` on a corrupt or
missing file — and add the `identity` block.

In `ingest/worker.py`, after the title is decided, call `validate_name` on
the SUPPLIED title and, when it fails, append the advisory sentence to the
job's existing validation notes (the same field
`ingest/validate.py`'s "only 17% agency-stamped" warning uses). **It must
not raise and must not change the job's state.**

- [ ] **Step 4: Run the tests and verify they pass**

Run: `uv run pytest tests/test_admin_attention_route.py tests/test_worker_agency_title.py -q`
Expected: PASS.

- [ ] **Step 5: Run the check at the end of the ingest queue**

In the worker's queue-drained path, call `eval.identity_check.main([])`
inside a `try/except Exception` that logs to stderr and swallows — I14 is
detection, and a broken instrument must never fail an ingest.

- [ ] **Step 6: Run the whole suite plus the webapp suite**

```bash
uv run pytest -q
cd webapp && npx vitest run && npx tsc -b && cd ..
```

Expected: pytest green (~2,900 + ~35 new), vitest green, `tsc -b` exit 0.

- [ ] **Step 7: Commit**

```bash
git add app/routes/admin.py ingest/worker.py tests/
git commit -m "identity: findings surface in Needs attention; check runs after ingest (I14, I15)"
```

---

## Task 10: Verify in a real browser

**Files:** none — this is the step every previous piece of work in this
repo has skipped and then paid for.

**Interfaces:** none.

- [ ] **Step 1: Build and start the app**

```bash
cd webapp && npm run build && cd ..
JLBC_DATA_DIR=data/insight-data uv run uvicorn app.main:create_app --factory --port 9300
```

`uvicorn` runs without `--reload`, so **Python changes need a restart** —
only the SPA picks up a rebuild. Several rounds of testing on this repo
have measured a stale build.

- [ ] **Step 2: Check the defect that started this**

Search Budget Documents for `barbers`. The FY2005 result must be titled
**Board of Barbers — FY 2005 Appropriations Report**, not "Agriculture".
Then open the browse listing and find the same document: **the two must
read identically.** That pair is the whole point of Task 3.

- [ ] **Step 3: Check the 2026-08-16 FY2027 documents**

Filter to FY2027 Appropriations Report. Every card must carry the
`— FY 2027 Appropriations Report` suffix; none may begin with a bullet.

- [ ] **Step 4: Check AI Mode names them the same way**

Ask AI Mode a question that retrieves a repaired FY2005 document, and
confirm the document name in the answer matches the browse page.

- [ ] **Step 5: Check the admin page**

Open `/admin` → Needs attention. The identity findings count must render,
and must read as a plain sentence — not a metric name.

- [ ] **Step 6: Record what you saw**

Update `STATUS.md` with the before/after numbers from Task 4 and Task 7,
the browser checks that passed, and anything that did not. **Numbers only
— no claim that a check passed unless you ran it.**

- [ ] **Step 7: Commit**

```bash
git add STATUS.md
git commit -m "docs: identity Units A+B shipped — measured before/after"
```

---

## Self-review notes

**Spec coverage.** I1 → Task 5 (`resolve_supplier_disagreement`). I3 →
Task 1. I4 → Task 6 fallback + Task 9. I5 → Task 5 + Task 7 uniqueness.
I6 → Tasks 6 and 8. I7 → Task 7 (and its docstring pins why no lock).
I8 → Task 7 reversal record. I12 → Tasks 2, 3. I13 → Task 4. I14 → Task 9
Step 5. I15 → Task 9. **I2, I9, I10 are "fix the labels" and are deliberately
absent** — see the scope note at the top.

**Gates.** G-I1 runs in Tasks 6 and 8 (the two touching `ingest/` and
`chunking/`). G-I2 is Task 7 Step 6. G-I4 is Task 3 Step 1. G-I3 and G-I5
belong to "fix the labels" — nothing here rewrites a chunk.

**Known soft spot.** Task 6's test names (`_document_from_agency_entry`,
`_AgencyEntry`) are written against what lines 275/284 of
`ingest/book_discovery.py` are *described* as doing. The first step of that
task is to read those lines and mirror the real constructors — and, if the
title is built inline, to extract it first in a no-behaviour-change commit.
Plan prose holds up in this repo; plan example code does not, and this is
the one place where I could not verify the exact signature.
