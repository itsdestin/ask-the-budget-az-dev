# Plan A — Document Types and Upload Rows Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the hardcoded document-type table into a data file, add the two
missing document types (`agency-submission`, `budget-bill-summary`), and
replace the upload form's dropdown of internal slugs with six guided rows.

**Architecture:** One YAML registry (`data/document-types.yaml`) loaded by
`ingest/doc_types.py` becomes the single source of truth for the dispatcher,
the upload route, the webapp (via `GET /api/document-types`) and doc_id
identity. Nothing about extraction behaviour changes: Task 2 repoints the
dispatcher at the registry and must leave routing byte-identical.

**Tech Stack:** Python 3.12, FastAPI, PyYAML 6.0.3 (already installed —
verified 2026-08-11), React 18 + Vite, pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`
— decisions **T1, T2, T3, T4, T9**. T5–T8 and T12 are Plan B; T10 and T13 are
Plan C. Do not implement them here.

## Global Constraints

- **Work in a worktree:** `git worktree add ~/ask-the-budget-az-worktrees/plan-a -b plan-a origin/master`, then `ln -s <main-repo>/.venv ~/ask-the-budget-az-worktrees/plan-a/.venv`.
- **Sync before you start and again before you merge.** Master moved twice on 2026-08-11 alone.
- **Annotate non-trivial edits with a WHY comment.** The owner is a non-developer and relies on them. Record the evidence that drove a choice, not just the choice.
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX weights.**
- **Never `dangerouslySetInnerHTML`** — corpus text is not trusted markup.
- **This plan does NOT change extraction behaviour.** If any task produces a different extractor for any existing `(doc_type, format)` pair, stop — that changes chunk text, chunk_ids, and eval ground truth.
- **Run the eval before merging** (`uv run python -m eval.run_eval`, ~60 s, needs `JLBC_DATA_DIR`) because `harness/system-prompt.md` changes in Task 7. **Expect no movement**; commit results with the change.
- **`ingest/section_types.py` is the one home for `section_kind → doc_type`.** Import it; never restate it. It was consolidated out of three copies on 2026-08-11 for exactly this reason.
- The registry describes *document types*. It is not a place for query-side vocabulary, agency aliases, or section-kind mappings.

---

## File structure

| File | Responsibility |
|---|---|
| Create `data/document-types.yaml` | The registry. One entry per document type: routing, identity, and (for six of them) the upload row's copy |
| Create `ingest/doc_types.py` | `DocType` dataclass + mtime-cached loader. `all_types()`, `get(key)`, `extractor_for(key, fmt)`, `upload_rows()`, `is_one_per_year(key)`, `reset_cache()` |
| Modify `ingest/dispatcher.py` | `EXTRACTOR_REGISTRY` becomes a projection of the registry. `pick_extractor` keeps its signature and its raise |
| Modify `ingest/driver.py` | `make_doc_id` consults the registry for whether a type is one-per-year |
| Modify `harness/tools.py` | `_DOC_TYPES` and `_PUBLISHERS` gain the new values |
| Modify `harness/system-prompt.md` | T9 bill-summary guidance |
| Create `app/routes/doc_types.py` | `GET /api/document-types` |
| Modify `app/routes/upload.py` | Allowlist from the registry; accept + persist `stage` |
| Modify `app/main.py` | Register the new router |
| Modify `webapp/src/api.ts` | `documentTypes()`, `DocTypeCard`, `stage` on `UploadMeta` |
| Modify `webapp/src/pages/Upload.tsx` | Six guided rows; delete the hand-typed `DOC_TYPES` |
| Tests | `tests/test_doc_types.py`, `tests/test_dispatcher_registry.py`, `tests/test_doc_id_identity.py`, `tests/test_doc_types_route.py`, `webapp/src/pages/Upload.test.tsx` |

---

## Ground truth (read before starting — measured 2026-08-11, not recalled)

1. **`EXTRACTOR_REGISTRY` has exactly 13 entries**, `dict[tuple[str, str], type]` keyed `(doc_type, source_format)` where format is `"pdf"` / `"docx"` with **no leading dot**. 12 PDF + `("budget-bill", "docx")` + `("fiscal-note", "pdf")`.
2. **`ACCEPTED_DOC_TYPES` in `app/routes/upload.py:46` is already derived** (`frozenset(dt for dt, _fmt in EXTRACTOR_REGISTRY)`). Repoint it; do not add a third list.
3. **`webapp/src/pages/Upload.tsx`'s `DOC_TYPES` IS hand-typed** (13 entries, currently in sync). **Delete it.**
4. **Chunking does not dispatch on `doc_type`** — `chunking/builder.py::chunk_doc` dispatches on `doc_meta.extractor` through `_READER_REGISTRY` (`mineru` / `opendataloader` / `python-docx`). Adding a type is declaring an extractor, not writing a chunker.
5. **🔴 `make_doc_id`'s non-JLBC branch IGNORES `filename`.** Verified by execution:
   ```
   make_doc_id(publisher='governor', doc_type='agency-submission',
               fiscal_year=2027, filename='BHA-FY27.pdf')
     -> 'governor-agency-submission-fy2027'
   make_doc_id(publisher='governor', doc_type='agency-submission',
               fiscal_year=2027, filename='DXA-FY27.pdf')
     -> 'governor-agency-submission-fy2027'      # IDENTICAL
   ```
   A write is an upsert, so ingesting 78 agency submissions would leave **one document**. This is the same collision shape already fixed once for JLBC books. **Task 3 fixes it.**
6. **Bill summaries do not have this problem** *if* their publisher is `jlbc` — the JLBC branch appends the filename stem. The 2026-06 harvest records publisher `JLBC` for all 7 Budget Bill rows, and the URLs are `azjlbc.gov/budget/…`. Verified: the two FY2027 documents mint distinct ids.
7. **The harvest's publisher for Agency Budget Requests is the AGENCY NAME** — 78 distinct values ("Board of Dental Examiners", "Department of Corrections", …). `_PUBLISHERS` in `harness/tools.py` is `["jlbc", "legislature", "governor", "agao"]`. Agency submissions therefore need a publisher value; this plan uses **`agency`** (Task 4), because the agency identity already lives in the entity stamper and `agency_canonical_id`, and adding 78 publishers would break the publisher filter's usefulness.
8. **PyYAML 6.0.3 is installed** (verified). No new dependency.
9. **`_DOC_TYPES` in `harness/tools.py` has drifted from the corpus before and the failure was SILENT** — a filtered search on a value the corpus lacks returns zero chunks with no error, and the model concludes the corpus lacks the material. The comment at that enum says to extend the system prompt in the same change. Do so.

---

### Task 1: The registry file and its loader

**Files:**
- Create: `data/document-types.yaml`
- Create: `ingest/doc_types.py`
- Test: `tests/test_doc_types.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `ingest.doc_types.DocType` — frozen dataclass with fields `key: str`, `label: str`, `group: str`, `order: int`, `formats: list[str]` (dotted, e.g. `".pdf"`), `extractors: dict[str, str]` (dotted format → `"mineru"` / `"opendataloader"` / `"python-docx"`), `publisher: str | None`, `one_per_year: bool`, `where_published: str`, `which_file: str`, `redirect: dict | None`, `stage_field: bool`, `upload_row: bool`
  - `ingest.doc_types.all_types() -> list[DocType]` — ordered by `order`
  - `ingest.doc_types.get(key: str) -> DocType | None`
  - `ingest.doc_types.extractor_for(key: str, fmt: str) -> str | None` — `fmt` dotted
  - `ingest.doc_types.upload_rows() -> list[DocType]` — only `upload_row: true`, ordered
  - `ingest.doc_types.is_one_per_year(key: str) -> bool` — consumed by Task 3
  - `ingest.doc_types.reset_cache() -> None` — for tests

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doc_types.py
"""The registry is the one place document types are described.

These tests pin the two properties that make the registry worth having:
it reproduces today's routing EXACTLY (so the Task 2 repoint cannot change
extraction), and every row an analyst can see tells them what to do.
"""
import pytest

from ingest import doc_types


def test_registry_reproduces_every_shipped_extractor_route():
    """The safety net for the whole refactor.

    Task 2 repoints the dispatcher at this file. Any row that disagrees with
    the shipped EXTRACTOR_REGISTRY would silently change how a document is
    extracted -- and a differently-extracted document produces different chunk
    text, different chunk_ids, and broken eval ground truth.
    """
    from ingest.dispatcher import EXTRACTOR_REGISTRY

    names = {
        "MinerUExtractor": "mineru",
        "OpenDataLoaderExtractor": "opendataloader",
        "PythonDocxExtractor": "python-docx",
    }
    for (doc_type, fmt), cls in EXTRACTOR_REGISTRY.items():
        row = doc_types.get(doc_type)
        assert row is not None, f"{doc_type} missing from data/document-types.yaml"
        assert f".{fmt}" in row.formats, f"{doc_type} does not accept .{fmt}"
        assert row.extractors[f".{fmt}"] == names[cls.__name__]


def test_the_registry_adds_exactly_the_two_new_types_and_nothing_else():
    from ingest.dispatcher import EXTRACTOR_REGISTRY

    shipped = {dt for dt, _fmt in EXTRACTOR_REGISTRY}
    registered = {t.key for t in doc_types.all_types()}
    assert registered - shipped == {"agency-submission", "budget-bill-summary"}
    assert shipped - registered == set()


def test_exactly_six_upload_rows_in_a_stable_order():
    rows = [t.key for t in doc_types.upload_rows()]
    assert rows == [
        "baseline-book",
        "approps-report",
        "afr",
        "governors-budget",
        "agency-submission",
        "budget-bill-summary",
    ]


def test_book_rows_redirect_and_carry_no_upload_instruction():
    # T1/S25: offering "which file?" for a book at all is the bug. An edition
    # is ~110 per-agency documents; the single-file PDF would land as ONE.
    for key in ("baseline-book", "approps-report"):
        row = doc_types.get(key)
        assert row.redirect is not None
        assert row.redirect["action"] == "add-jlbc-book"
        assert not row.which_file


def test_every_non_redirect_row_tells_the_analyst_which_file_to_get():
    # A dropdown entry with no guidance is what this plan exists to delete.
    for row in doc_types.upload_rows():
        if row.redirect is None:
            assert row.which_file.strip(), f"{row.key} has no which_file"
            assert row.where_published.strip(), f"{row.key} has no where_published"


def test_only_the_bill_summary_asks_for_a_stage():
    staged = {t.key for t in doc_types.all_types() if t.stage_field}
    assert staged == {"budget-bill-summary"}


def test_multi_per_year_types_are_marked_as_such():
    # Drives doc_id identity in Task 3. Getting this wrong silently collapses
    # every document of that type in a fiscal year into one.
    assert doc_types.get("afr").one_per_year is True
    assert doc_types.get("governors-budget").one_per_year is True
    assert doc_types.get("agency-submission").one_per_year is False
    assert doc_types.get("budget-bill-summary").one_per_year is False


def test_a_malformed_registry_raises_rather_than_defaulting(tmp_path):
    # Unlike settings.json, this file is shipped and version-controlled.
    # Silently forgetting how to route documents is worse than not starting.
    bad = tmp_path / "document-types.yaml"
    bad.write_text("types: [ this is not: valid: yaml", encoding="utf-8")
    doc_types.reset_cache()
    with pytest.raises(Exception):
        doc_types.all_types(path=bad)
    doc_types.reset_cache()


def test_an_edited_registry_is_picked_up_without_a_restart(tmp_path):
    path = tmp_path / "document-types.yaml"
    path.write_text(
        "types:\n"
        "  - key: afr\n"
        "    label: Annual Financial Report\n"
        "    group: Auditor General\n"
        "    order: 30\n"
        "    formats: ['.pdf']\n"
        "    extractors: {'.pdf': opendataloader}\n"
        "    publisher: agao\n"
        "    one_per_year: true\n"
        "    upload_row: true\n"
        "    where_published: x\n"
        "    which_file: y\n",
        encoding="utf-8",
    )
    doc_types.reset_cache()
    assert doc_types.get("afr", path=path).label == "Annual Financial Report"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "label: Annual Financial Report", "label: Renamed"
        ),
        encoding="utf-8",
    )
    import os, time
    # Force a distinct mtime -- a same-tick rewrite is the one case the
    # (path, mtime, size) stamp cannot see, and the sizes here differ anyway.
    os.utime(path, (time.time() + 1, time.time() + 1))
    assert doc_types.get("afr", path=path).label == "Renamed"
    doc_types.reset_cache()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_doc_types.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.doc_types'`

- [ ] **Step 3: Write `data/document-types.yaml`**

All 15 types. The nine without `upload_row` still need routing, because the
dispatcher is a projection of this file.

```yaml
# The one description of every document type the corpus holds.
#
# WHY this is data and not Python: the office has no maintainer. Adding a
# seventh upload row must be an edit to this file, not a code change and a
# rebuild. Consumed by ingest/dispatcher.py, ingest/driver.py,
# app/routes/upload.py, app/routes/doc_types.py and the webapp.
#
# WHY `extractors` values are names, not classes: this file must stay
# readable by a non-developer. ingest/dispatcher.py maps name -> class.
#
# `one_per_year: false` means SEVERAL documents of this type can exist in one
# fiscal year, so the filename has to be part of the doc_id. Getting this
# wrong makes every document of that type in a year overwrite the last --
# see ingest/driver.py::make_doc_id and tests/test_doc_id_identity.py.
types:
  # --- JLBC books: redirect, never uploaded (T1 / spec S25) ---------------
  - key: baseline-book
    label: Baseline Book
    group: JLBC
    order: 10
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: true
    upload_row: true
    where_published: "Published by JLBC each January at azjlbc.gov."
    which_file: ""
    redirect:
      action: add-jlbc-book
      label: "Use “Add a JLBC book” instead"
      detail: >-
        A Baseline Book is stored as one document per agency, which is what
        makes “show me Corrections’ budget” work. The book tool fetches
        every agency page for the year. Uploading the single-file PDF would
        add a 400-page book as ONE document and make agency search worse.

  - key: approps-report
    label: Appropriations Report
    group: JLBC
    order: 11
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: true
    upload_row: true
    where_published: "Published by JLBC after the session at azjlbc.gov."
    which_file: ""
    redirect:
      action: add-jlbc-book
      label: "Use “Add a JLBC book” instead"
      detail: >-
        An Appropriations Report is stored as one document per agency, the
        same way the Baseline Book is. Use the book tool so every agency page
        is added.

  # --- The six rows that accept a file -----------------------------------
  - key: afr
    label: Annual Financial Report
    group: Auditor General
    order: 30
    formats: ['.pdf']
    extractors: {'.pdf': opendataloader}
    publisher: agao
    one_per_year: true
    upload_row: true
    where_published: >-
      Published each autumn by the Arizona Auditor General at gao.az.gov.
      That site blocks automated downloads, so it must be saved from a
      browser and uploaded here.
    which_file: >-
      The combined PDF — its name usually contains “AFR” and
      “COMBINED”. Not the individual statements.

  - key: governors-budget
    label: Executive Budget
    group: Governor
    order: 40
    formats: ['.pdf']
    extractors: {'.pdf': opendataloader}
    publisher: governor
    one_per_year: true
    upload_row: true
    where_published: >-
      Published each January by the Governor’s Office of Strategic
      Planning and Budgeting at ospb.az.gov.
    which_file: "The State Agency Detail volume."

  - key: agency-submission
    label: Agency Submission
    group: Agencies
    order: 50
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: agency
    one_per_year: false
    upload_row: true
    where_published: >-
      Each agency publishes its own budget request each autumn, on its own
      website. Some are also collected at ospb.az.gov.
    which_file: >-
      That agency’s budget request for the fiscal year. One upload per
      agency — there are dozens each year.

  - key: budget-bill-summary
    label: Budget Bill Summary
    group: JLBC
    order: 60
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    stage_field: true
    upload_row: true
    where_published: >-
      Published by JLBC at azjlbc.gov/budget/ while the budget bills move
      through the Legislature.
    which_file: >-
      The “House and Senate Budget Bills” PDF. Say whether it is the
      Introduced or the Engrossed version — Engrossed replaces Introduced,
      and there is often more than one in a year.

  # --- Registered, routed, but not offered as an upload row --------------
  # These exist because documents of these types are already in the corpus and
  # the dispatcher is a projection of this file. Adding an upload row for any
  # of them is a change to `upload_row`, nothing more.
  - key: baseline-per-agency
    label: Baseline — agency page
    group: JLBC
    order: 100
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A page of the Baseline Book; added by the book tool."
    which_file: ""

  - key: approps-per-agency
    label: Appropriations Report — agency page
    group: JLBC
    order: 101
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A page of the Appropriations Report; added by the book tool."
    which_file: ""

  - key: s-pdf
    label: Baseline — summary section
    group: JLBC
    order: 102
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A cross-cutting section of a JLBC book; added by the book tool."
    which_file: ""

  - key: bh-pdf
    label: Baseline — budget history section
    group: JLBC
    order: 103
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A cross-cutting section of a JLBC book; added by the book tool."
    which_file: ""

  - key: bd-pdf
    label: Baseline — budget detail section
    group: JLBC
    order: 104
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A cross-cutting section of a JLBC book; added by the book tool."
    which_file: ""

  - key: detailed-list-pdf
    label: Detailed list of fund changes
    group: JLBC
    order: 105
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A cross-cutting section of a JLBC book; added by the book tool."
    which_file: ""

  - key: topic-pdf
    label: Cross-cutting topic report
    group: JLBC
    order: 106
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: jlbc
    one_per_year: false
    upload_row: false
    where_published: "A cross-cutting section of a JLBC book; added by the book tool."
    which_file: ""

  # WHY this is registered but not offered (spec T3): the Word feed bill
  # carries the section and paragraph structure that lets the app cite an
  # exact provision, which the summary PDF does not. Different document,
  # different use. DOCX-only is deliberate -- the PDF loses that structure.
  - key: budget-bill
    label: Feed Bill (General Appropriations Act)
    group: Legislature
    order: 107
    formats: ['.docx']
    extractors: {'.docx': python-docx}
    publisher: legislature
    one_per_year: false
    upload_row: false
    where_published: "Passed by the Legislature; JLBC circulates the Word version."
    which_file: "The Word (.docx) version, never the PDF."

  # Belongs to the separate fiscal-note corpus and is added by its own
  # refresh flow (POST /api/fiscal-notes/refresh), not by upload.
  - key: fiscal-note
    label: Fiscal note
    group: Legislature
    order: 108
    formats: ['.pdf']
    extractors: {'.pdf': mineru}
    publisher: legislature
    one_per_year: false
    upload_row: false
    where_published: "Scraped from azjlbc.gov/fiscal-notes by the refresh button."
    which_file: ""
```

- [ ] **Step 4: Write `ingest/doc_types.py`**

```python
"""The document-type registry: loader for `data/document-types.yaml`.

WHY a data file rather than a dict in Python: the office that runs this app
has no maintainer. Adding a document type must be an edit to a readable file,
not a code change, a rebuild and a redeploy.

WHY a malformed file RAISES instead of falling back to defaults (unlike
harness/settings.py, which degrades): settings.json is written by an admin at
runtime and a bad one should not stop the app. This file ships in the repo, so
a parse failure means the build is broken -- and an app that has silently
forgotten how to route documents is worse than one that will not start.

The mtime cache mirrors harness/settings.py's (path, mtime, size) stamp so an
edited registry is picked up without a restart.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

REGISTRY_PATH = Path(__file__).resolve().parent.parent / "data" / "document-types.yaml"


@dataclass(frozen=True)
class DocType:
    key: str
    label: str
    group: str
    order: int
    formats: tuple[str, ...]
    extractors: dict[str, str]
    publisher: str | None
    one_per_year: bool
    where_published: str
    which_file: str
    upload_row: bool = False
    stage_field: bool = False
    redirect: dict[str, str] | None = None


_cache: tuple[DocType, ...] | None = None
_stamp: tuple[str, float, int] | None = None


def reset_cache() -> None:
    """Drop the cache. Tests that write their own registry call this."""
    global _cache, _stamp
    _cache, _stamp = None, None


def _load(path: Path | None = None) -> tuple[DocType, ...]:
    global _cache, _stamp
    target = path or REGISTRY_PATH
    st = target.stat()
    stamp = (str(target), st.st_mtime, st.st_size)
    if stamp == _stamp and _cache is not None:
        return _cache

    raw: Any = yaml.safe_load(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or not isinstance(raw.get("types"), list):
        raise ValueError(f"{target} must be a mapping with a 'types' list.")

    rows = []
    for entry in raw["types"]:
        rows.append(DocType(
            key=entry["key"],
            label=entry["label"],
            group=entry["group"],
            order=int(entry["order"]),
            formats=tuple(entry["formats"]),
            extractors=dict(entry.get("extractors") or {}),
            publisher=entry.get("publisher"),
            one_per_year=bool(entry["one_per_year"]),
            where_published=entry.get("where_published", ""),
            which_file=entry.get("which_file", ""),
            upload_row=bool(entry.get("upload_row", False)),
            stage_field=bool(entry.get("stage_field", False)),
            redirect=entry.get("redirect"),
        ))

    keys = [r.key for r in rows]
    if len(keys) != len(set(keys)):
        dupes = sorted({k for k in keys if keys.count(k) > 1})
        raise ValueError(f"{target} has duplicate keys: {dupes}")

    _cache = tuple(sorted(rows, key=lambda r: r.order))
    _stamp = stamp
    return _cache


def all_types(path: Path | None = None) -> list[DocType]:
    return list(_load(path))


def get(key: str, path: Path | None = None) -> DocType | None:
    for row in _load(path):
        if row.key == key:
            return row
    return None


def extractor_for(key: str, fmt: str, path: Path | None = None) -> str | None:
    """`fmt` is dotted, e.g. '.pdf'."""
    row = get(key, path)
    return None if row is None else row.extractors.get(fmt)


def upload_rows(path: Path | None = None) -> list[DocType]:
    return [r for r in _load(path) if r.upload_row]


def is_one_per_year(key: str, path: Path | None = None) -> bool:
    """Unknown types default to False -- the SAFE direction.

    A wrong `True` silently overwrites documents; a wrong `False` produces a
    longer id. Only one of those loses data.
    """
    row = get(key, path)
    return bool(row and row.one_per_year)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_doc_types.py -q`
Expected: PASS, 9 tests

- [ ] **Step 6: Commit**

```bash
git add data/document-types.yaml ingest/doc_types.py tests/test_doc_types.py
git commit -m "feat(ingest): declarative document-type registry (T4)"
```

---

### Task 2: Repoint the dispatcher — behaviour identical

**Files:**
- Modify: `ingest/dispatcher.py:180-226`
- Test: `tests/test_dispatcher_registry.py`

**Interfaces:**
- Consumes: `ingest.doc_types.all_types()`, `.extractor_for()`
- Produces: `EXTRACTOR_REGISTRY` with the identical shape and contents it has today — `dict[tuple[str, str], type]`, undotted format keys. Every existing importer keeps working.

- [ ] **Step 1: Write the characterization test and confirm it passes on UNMODIFIED code**

This is the point of the task. A characterization test that has never passed
against the old code proves nothing.

```python
# tests/test_dispatcher_registry.py
"""The registry repoint must not change one byte of routing.

A differently-extracted document produces different chunk text, different
chunk_ids, and broken eval ground truth. This file is the guard, and it is
written to pass against the PRE-refactor dispatcher first.
"""
from ingest.dispatcher import (
    EXTRACTOR_REGISTRY,
    MinerUExtractor,
    OpenDataLoaderExtractor,
    PythonDocxExtractor,
    pick_extractor,
)

# The shipped table, transcribed by hand from ingest/dispatcher.py on
# 2026-08-11. Hand-transcribed ON PURPOSE: deriving it from the module under
# test would make this assert that a thing equals itself.
SHIPPED = {
    ("afr", "pdf"): OpenDataLoaderExtractor,
    ("governors-budget", "pdf"): OpenDataLoaderExtractor,
    ("baseline-book", "pdf"): MinerUExtractor,
    ("approps-report", "pdf"): MinerUExtractor,
    ("baseline-per-agency", "pdf"): MinerUExtractor,
    ("approps-per-agency", "pdf"): MinerUExtractor,
    ("s-pdf", "pdf"): MinerUExtractor,
    ("bh-pdf", "pdf"): MinerUExtractor,
    ("bd-pdf", "pdf"): MinerUExtractor,
    ("topic-pdf", "pdf"): MinerUExtractor,
    ("detailed-list-pdf", "pdf"): MinerUExtractor,
    ("budget-bill", "docx"): PythonDocxExtractor,
    ("fiscal-note", "pdf"): MinerUExtractor,
}


def test_the_registry_is_exactly_the_shipped_table():
    assert EXTRACTOR_REGISTRY == SHIPPED


def test_every_shipped_pair_resolves_to_the_same_extractor_instance_type():
    for (doc_type, fmt), cls in SHIPPED.items():
        assert isinstance(pick_extractor(doc_type, fmt), cls)


def test_unknown_pairs_still_raise():
    import pytest
    # A budget-bill PDF is the canonical caller bug: the Word file is the
    # whole point of that type.
    with pytest.raises(ValueError):
        pick_extractor("budget-bill", "pdf")
    with pytest.raises(ValueError):
        pick_extractor("not-a-type", "pdf")


def test_the_new_types_are_NOT_reachable_through_the_dispatcher_yet():
    """Task 4 wires these. Until then the dispatcher must not know them.

    Pinned so Task 2 cannot quietly pull them in as a side effect of reading
    the registry -- that would make Task 4's own test vacuous.
    """
    import pytest
    for key in ("agency-submission", "budget-bill-summary"):
        with pytest.raises(ValueError):
            pick_extractor(key, "pdf")
```

- [ ] **Step 2: Run against unmodified `ingest/dispatcher.py`**

Run: `.venv/bin/python -m pytest tests/test_dispatcher_registry.py -q`
Expected: **PASS, 4 tests.** If any fail, the transcription is wrong — fix the
test, not the code. Do not proceed until this is green on unmodified code.

- [ ] **Step 3: Replace the literal with a projection**

In `ingest/dispatcher.py`, delete the 13-entry literal (lines ~180–205) and
put in its place:

```python
from ingest.doc_types import all_types as _all_doc_types

_EXTRACTOR_CLASSES = {
    "mineru": MinerUExtractor,
    "opendataloader": OpenDataLoaderExtractor,
    "python-docx": PythonDocxExtractor,
}

# WHY this is built rather than written out: the table used to live here AND
# in webapp/src/pages/Upload.tsx, and app/routes/upload.py derived a third
# copy from it. One source of truth is data/document-types.yaml; this is a
# projection of it in the shape every existing importer already expects
# (undotted format keys, extractor CLASSES not names).
#
# Types the registry knows but that declare no extractor for a format are
# simply absent, exactly as they were when this was a literal -- which is what
# keeps `pick_extractor` raising for (budget-bill, pdf).
def _build_registry() -> dict[tuple[str, str], type]:
    table: dict[tuple[str, str], type] = {}
    for row in _all_doc_types():
        for fmt, name in row.extractors.items():
            cls = _EXTRACTOR_CLASSES.get(name)
            if cls is None:
                raise ValueError(
                    f"document-types.yaml: {row.key} names unknown extractor "
                    f"{name!r}. Known: {sorted(_EXTRACTOR_CLASSES)}."
                )
            table[(row.key, fmt.lstrip("."))] = cls
    return table


EXTRACTOR_REGISTRY: dict[tuple[str, str], type] = _build_registry()
```

Leave `pick_extractor` untouched — same signature, same raise. The routing
change that S26/T5 describes is **Plan B**, deliberately a separate commit so
a routing regression is bisectable.

- [ ] **Step 4: Run the characterization test plus the dispatcher's own suites**

Run: `.venv/bin/python -m pytest tests/test_dispatcher_registry.py tests/test_dispatcher.py tests/test_driver.py tests/test_doc_types.py -q`
Expected: PASS. `test_the_registry_is_exactly_the_shipped_table` passing after
the change is the whole point.

- [ ] **Step 5: Commit**

```bash
git add ingest/dispatcher.py tests/test_dispatcher_registry.py
git commit -m "refactor(ingest): dispatcher routes from the registry, behaviour identical"
```

---

### Task 3: Registry-driven doc_id identity — the collision fix

**Files:**
- Modify: `ingest/driver.py:151-212`
- Test: `tests/test_doc_id_identity.py`

**Interfaces:**
- Consumes: `ingest.doc_types.is_one_per_year(key)`
- Produces: `make_doc_id(...)` — unchanged signature, unchanged output for every existing type.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doc_id_identity.py
"""A doc_id must be unique per DOCUMENT, not per publisher-per-year.

WHY this file exists: measured on 2026-08-11, make_doc_id's non-JLBC branch
ignored `filename`, so all 78 FY2027 agency submissions minted
'governor-agency-submission-fy2027'. A write is an upsert, so ingesting them
would have left ONE document, with nothing erroring anywhere. This is the same
shape as the JLBC book collision fixed in f85b20a.
"""
from ingest.driver import make_doc_id


def test_agency_submissions_in_one_year_get_distinct_ids():
    a = make_doc_id(publisher="agency", doc_type="agency-submission",
                    fiscal_year=2027, filename="BHA FY27 Budget Submission.pdf")
    b = make_doc_id(publisher="agency", doc_type="agency-submission",
                    fiscal_year=2027, filename="DXA FY27 Budget Submission.pdf")
    assert a != b


def test_bill_summaries_in_one_year_get_distinct_ids():
    intro = make_doc_id(publisher="jlbc", doc_type="budget-bill-summary",
                        fiscal_year=2027,
                        filename="senatehouseintroducedbudgetbills.pdf")
    eng = make_doc_id(publisher="jlbc", doc_type="budget-bill-summary",
                      fiscal_year=2027,
                      filename="houseandsenateplanasengrossed061126.pdf")
    assert intro != eng


def test_one_per_year_types_keep_their_EXACT_existing_ids():
    """The corpus and eval/queries.yaml depend on these strings.

    Verified against the live corpus on 2026-08-11: these are the ids
    agao-afr-fy2024 and governor-governors-budget-fy2027 actually carry.
    """
    assert make_doc_id(
        publisher="agao", doc_type="afr", fiscal_year=2024,
        filename="AFR24 COMBINED with Transmittal Letter.pdf",
    ) == "agao-afr-fy2024"
    assert make_doc_id(
        publisher="governor", doc_type="governors-budget", fiscal_year=2027,
        filename="state-agency-detail-fy-2027.pdf",
    ) == "governor-governors-budget-fy2027"


def test_jlbc_book_ids_are_untouched():
    # The family-aware branch is not what this task changes.
    assert make_doc_id(
        publisher="jlbc", doc_type="detailed-list-pdf", fiscal_year=2026,
        filename="508.pdf", family="approps",
    ) == "jlbc-approps-fy2026-508"
    assert make_doc_id(
        publisher="jlbc", doc_type="detailed-list-pdf", fiscal_year=2026,
        filename="508.pdf", family="baseline",
    ) == "jlbc-baseline-fy2026-508"


def test_a_singleton_type_with_no_filename_still_works():
    assert make_doc_id(
        publisher="agao", doc_type="afr", fiscal_year=2024,
    ) == "agao-afr-fy2024"


def test_bill_id_still_wins_for_budget_bills():
    assert make_doc_id(
        publisher="legislature", doc_type="budget-bill", fiscal_year=2026,
        bill_id="sb1735-2025",
    ) == "legislature-budget-bill-fy2026-sb1735-2025"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_doc_id_identity.py -q`
Expected: FAIL — `test_agency_submissions_in_one_year_get_distinct_ids`
(both sides equal `agency-agency-submission-fy2027`). The other five pass.

- [ ] **Step 3: Change the non-JLBC branch to consult the registry**

Replace the final block of `make_doc_id` in `ingest/driver.py`:

```python
    # Non-JLBC publishers.
    #
    # WHY the registry decides instead of the publisher: this branch used to
    # assume one document per publisher per fiscal year and DROP `filename`
    # entirely. That is true for the AFR and the Executive Budget and false
    # for agency submissions (78 in FY2027) and bill summaries (3 in FY2027).
    # Measured 2026-08-11: every agency submission minted
    # 'governor-agency-submission-fy2027', and because a write is an upsert
    # they would have collapsed into one document with nothing erroring.
    #
    # Existing ids are unchanged because afr and governors-budget are declared
    # `one_per_year: true` -- pinned by test_one_per_year_types_keep_their_
    # EXACT_existing_ids, which asserts the literal strings the live corpus
    # carries.
    base = f"{publisher}-{doc_type}-{fy_str}"
    if bill_id:
        return f"{base}-{bill_id}"
    if is_one_per_year(doc_type):
        return base
    if filename is None:
        return base
    return f"{base}-{slugify_stem(Path(filename).stem)}"
```

Add near the top of the module:

```python
from ingest.doc_types import is_one_per_year


def slugify_stem(stem: str) -> str:
    """Filename stem -> a doc_id-safe slug.

    Agency submissions arrive with human filenames full of spaces and
    percent-encoding ('BHA FY27 Executive Budget Submission.pdf'), unlike the
    JLBC books' terse '508.pdf'. A doc_id ends up in URLs and citation
    payloads, so it is lowercased and reduced to [a-z0-9-].
    """
    out = "".join(c if c.isalnum() else "-" for c in stem.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_doc_id_identity.py tests/test_driver.py tests/test_books_route.py -q`
Expected: PASS

- [ ] **Step 5: Prove no live document's id would move**

This is the check that matters more than the tests. Run:

```bash
JLBC_DATA_DIR=data/insight-data .venv/bin/python - <<'PY'
from store.documents import load_documents
from ingest.driver import make_doc_id
from pathlib import Path
docs = load_documents()
moved = []
for doc_id, v in docs.items():
    p, dt, fy = v.get("publisher"), v.get("doc_type"), v.get("fiscal_year")
    if not (p and dt and fy) or p == "jlbc":
        continue          # jlbc ids need `family`, which documents.json lacks
    blob = v.get("source_blob_path") or ""
    fn = Path(blob).name or None
    got = make_doc_id(publisher=p, doc_type=dt, fiscal_year=fy, filename=fn)
    if got != doc_id:
        moved.append((doc_id, got))
print(f"non-jlbc documents checked: {sum(1 for v in docs.values() if v.get('publisher') != 'jlbc')}")
print(f"ids that would MOVE: {len(moved)}")
for a, b in moved[:20]:
    print("  ", a, "->", b)
PY
```

Expected: **`ids that would MOVE: 0`.** A non-zero count means a type is
mis-declared in the registry — fix `one_per_year`, do not accept the move.

- [ ] **Step 6: Commit**

```bash
git add ingest/driver.py tests/test_doc_id_identity.py
git commit -m "fix(ingest): doc_id identity comes from the registry, not the publisher

Measured: all 78 FY2027 agency submissions minted the same doc_id, and a
write is an upsert, so ingesting them would have left one document with
nothing erroring. Verified 0 existing non-JLBC ids move."
```

---

### Task 4: Register the two new types end to end

**Files:**
- Modify: `harness/tools.py:172-190`
- Test: `tests/test_dispatcher_registry.py` (amend), `tests/test_new_doc_types.py`

**Interfaces:**
- Consumes: the registry from Task 1, `EXTRACTOR_REGISTRY` from Task 2.
- Produces: `agency-submission` and `budget-bill-summary` routable end to end; `agency` a valid publisher.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_new_doc_types.py
"""The two new types must be known EVERYWHERE, not just in the registry.

WHY a dedicated file: harness/tools.py's _DOC_TYPES has drifted from the
corpus before and the failure was SILENT -- a filtered search on a value the
corpus lacks returns zero chunks with no error, and the model concludes the
corpus does not cover it. The comment at that enum says to extend the system
prompt in the same change; test_the_system_prompt_mentions_the_new_type
enforces the half a reviewer would forget.
"""
from pathlib import Path

from ingest.dispatcher import EXTRACTOR_REGISTRY, MinerUExtractor, pick_extractor
from harness.tools import _DOC_TYPES, _PUBLISHERS

NEW = ("agency-submission", "budget-bill-summary")


def test_both_new_types_route_to_an_extractor():
    for key in NEW:
        assert (key, "pdf") in EXTRACTOR_REGISTRY
        assert isinstance(pick_extractor(key, "pdf"), MinerUExtractor)


def test_both_new_types_are_filterable_by_the_model():
    for key in NEW:
        assert key in _DOC_TYPES


def test_agency_is_a_publisher():
    assert "agency" in _PUBLISHERS


def test_the_doc_type_enum_matches_the_registry_exactly():
    """The enum and the registry are the two lists that must never drift."""
    from ingest import doc_types
    assert set(_DOC_TYPES) == {t.key for t in doc_types.all_types()}


def test_the_system_prompt_mentions_the_new_type():
    prompt = Path("harness/system-prompt.md").read_text(encoding="utf-8")
    assert "budget-bill-summary" in prompt
    assert "agency-submission" in prompt
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_new_doc_types.py -q`
Expected: FAIL — `agency-submission` not in `EXTRACTOR_REGISTRY` (the Task 2
guard `test_the_new_types_are_NOT_reachable_through_the_dispatcher_yet` is
what has been holding them out).

- [ ] **Step 3: Remove the Task 2 holdout guard**

Delete `test_the_new_types_are_NOT_reachable_through_the_dispatcher_yet` from
`tests/test_dispatcher_registry.py` and add both pairs to `SHIPPED`:

```python
    ("agency-submission", "pdf"): MinerUExtractor,
    ("budget-bill-summary", "pdf"): MinerUExtractor,
```

The registry already declares them (Task 1), so `EXTRACTOR_REGISTRY` picks
them up with no further change to `ingest/dispatcher.py`.

- [ ] **Step 4: Extend `harness/tools.py`**

```python
_DOC_TYPES = [
    "baseline-per-agency",
    "approps-per-agency",
    "baseline-book",
    "approps-report",
    "s-pdf",
    "bd-pdf",
    "bh-pdf",
    "detailed-list-pdf",
    "topic-pdf",
    "afr",
    "governors-budget",
    "budget-bill",
    # JLBC's summary of the budget bills in progress. Precedes the
    # Appropriations Report and is superseded by it -- see the lifecycle
    # section of system-prompt.md.
    "budget-bill-summary",
    # An agency's own budget request, one per agency per year.
    "agency-submission",
    # Added for Plan 3's fiscal-note corpus.
    "fiscal-note",
]

_PUBLISHERS = ["jlbc", "legislature", "governor", "agao", "agency"]
```

> **Note:** `baseline-book` and `approps-report` were absent from `_DOC_TYPES`
> and present in `EXTRACTOR_REGISTRY` — a live instance of the drift the
> comment warns about. `test_the_doc_type_enum_matches_the_registry_exactly`
> is what caught it. Adding them is correct and is not scope creep.

- [ ] **Step 5: Add the doc_type names to the system prompt's filter list**

`test_the_system_prompt_mentions_the_new_type` fails until the two names
appear. Add them to the filter-dimensions table in `harness/system-prompt.md`
alongside the existing `doc_type` values. Task 7 writes the behavioural
guidance; this step only makes the values known.

- [ ] **Step 6: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_new_doc_types.py tests/test_dispatcher_registry.py tests/test_doc_types.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add harness/tools.py harness/system-prompt.md tests/test_new_doc_types.py tests/test_dispatcher_registry.py
git commit -m "feat: register agency-submission and budget-bill-summary end to end

Also adds baseline-book and approps-report to _DOC_TYPES, which were in
EXTRACTOR_REGISTRY but missing from the enum -- a live instance of the
silent drift the comment at that enum warns about."
```

---

### Task 5: Serve the registry, and accept the new types on upload

**Files:**
- Create: `app/routes/doc_types.py`
- Modify: `app/routes/upload.py:46`, `app/routes/upload.py:60-130`, `app/main.py:36,187`
- Test: `tests/test_doc_types_route.py`

**Interfaces:**
- Consumes: `ingest.doc_types.upload_rows()`, `.all_types()`, `.get()`
- Produces: `GET /api/document-types -> {"types": [DocTypeCard]}` where
  `DocTypeCard = {key, label, group, formats, where_published, which_file, redirect, stage_field, order}`.
  `POST /api/upload` additionally accepts `stage: str = Form("")`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_doc_types_route.py
from fastapi.testclient import TestClient

from app.main import create_app


def _client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return TestClient(create_app(ingest_worker=None))


def test_the_route_returns_the_six_upload_rows_in_order(tmp_path, monkeypatch):
    r = _client(tmp_path, monkeypatch).get("/api/document-types")
    assert r.status_code == 200
    keys = [t["key"] for t in r.json()["types"]]
    assert keys == [
        "baseline-book", "approps-report", "afr",
        "governors-budget", "agency-submission", "budget-bill-summary",
    ]


def test_book_rows_carry_a_redirect_and_no_which_file(tmp_path, monkeypatch):
    types = _client(tmp_path, monkeypatch).get("/api/document-types").json()["types"]
    by_key = {t["key"]: t for t in types}
    for key in ("baseline-book", "approps-report"):
        assert by_key[key]["redirect"]["action"] == "add-jlbc-book"
        assert not by_key[key]["which_file"]


def test_only_the_bill_summary_asks_for_a_stage(tmp_path, monkeypatch):
    types = _client(tmp_path, monkeypatch).get("/api/document-types").json()["types"]
    staged = {t["key"] for t in types if t["stage_field"]}
    assert staged == {"budget-bill-summary"}


def test_upload_accepts_a_new_type(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("bha-fy27.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "agency",
            "doc_type": "agency-submission", "fiscal_year": "2027",
            "title": "", "is_public_record": "true",
        },
    )
    assert r.status_code == 202, r.text


def test_upload_persists_the_stage_on_the_job(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("engrossed.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "jlbc",
            "doc_type": "budget-bill-summary", "fiscal_year": "2027",
            "title": "", "is_public_record": "true", "stage": "engrossed",
        },
    )
    assert r.status_code == 202, r.text
    jobs = c.get("/api/jobs").json()["jobs"]
    assert [j for j in jobs if j.get("stage") == "engrossed"]


def test_an_unknown_stage_is_rejected(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post(
        "/api/upload",
        files={"file": ("x.pdf", b"%PDF-1.4 stub", "application/pdf")},
        data={
            "corpus": "budget", "publisher": "jlbc",
            "doc_type": "budget-bill-summary", "fiscal_year": "2027",
            "title": "", "is_public_record": "true", "stage": "final",
        },
    )
    # "Final" is the wording JLBC uses on some titles, but the ladder has two
    # rungs. Accepting a third silently would break the supersession rule.
    assert r.status_code == 422
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_doc_types_route.py -q`
Expected: FAIL — 404 on `/api/document-types`

- [ ] **Step 3: Write `app/routes/doc_types.py`**

```python
"""GET /api/document-types — the upload page's rows, from the registry.

WHY this exists: webapp/src/pages/Upload.tsx used to carry its own hand-typed
copy of the type list. Two lists that must agree and nothing enforcing it is a
shape this project has shipped bugs from more than once, so the page now reads
the rows off the wire and holds no copy at all.
"""
from __future__ import annotations

from fastapi import APIRouter

from ingest.doc_types import upload_rows

router = APIRouter()


@router.get("/api/document-types")
def document_types():
    return {
        "types": [
            {
                "key": row.key,
                "label": row.label,
                "group": row.group,
                "formats": list(row.formats),
                "where_published": row.where_published,
                "which_file": row.which_file,
                "redirect": row.redirect,
                "stage_field": row.stage_field,
                "order": row.order,
            }
            for row in upload_rows()
        ]
    }
```

- [ ] **Step 4: Register it in `app/main.py`**

Add the import beside the others (line ~30) and the registration beside the
others (line ~187). **Both must be above the SPA catch-all**, or the route
returns index.html:

```python
from app.routes.doc_types import router as doc_types_router
...
    app.include_router(doc_types_router)
```

- [ ] **Step 5: Repoint the upload allowlist and accept `stage`**

In `app/routes/upload.py`, replace line 46:

```python
from ingest.doc_types import all_types, get as get_doc_type

# WHY derived and not written out: this was already a projection of
# EXTRACTOR_REGISTRY; it now projects the registry that feeds it. A third
# hand-maintained list is exactly what this change exists to prevent.
ACCEPTED_DOC_TYPES = frozenset(t.key for t in all_types())

# The bill-summary ladder has exactly two rungs (spec T2). JLBC titles some
# engrossed versions "Final Budget Bills"; that wording maps to `engrossed`,
# it is not a third stage. Accepting one would break "Engrossed supersedes
# Introduced" by introducing a value the rule says nothing about.
ACCEPTED_STAGES = frozenset({"introduced", "engrossed"})
```

Add `stage: str = Form("")` to the signature, and after the `doc_type` check:

```python
    row = get_doc_type(doc_type)
    stage_value = stage.strip().lower()
    if stage_value and stage_value not in ACCEPTED_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown stage {stage!r}. Choose Introduced or Engrossed.",
        )
    if row is not None and row.stage_field and not stage_value:
        raise HTTPException(
            status_code=422,
            detail="Say whether this is the Introduced or the Engrossed version.",
        )
```

and pass `stage=stage_value or None` to `new_job(...)`.

- [ ] **Step 6: Add `stage` to the job record**

In `ingest/jobs.py`, add `stage: str | None = None` to the job dataclass and
include it in `view()`. It must be **optional with a `None` default** — 7,116
job files already exist without it, and `_read` must not raise on them.

- [ ] **Step 7: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_doc_types_route.py tests/test_upload_route.py tests/test_jobs_route.py -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add app/routes/doc_types.py app/routes/upload.py app/main.py ingest/jobs.py tests/test_doc_types_route.py
git commit -m "feat(app): GET /api/document-types; upload allowlist and stage from the registry"
```

---

### Task 6: The upload page becomes six guided rows

**Files:**
- Modify: `webapp/src/api.ts:326-346`
- Modify: `webapp/src/pages/Upload.tsx:30-46` (delete `DOC_TYPES`), `:220-240` (the picker)
- Test: `webapp/src/pages/Upload.test.tsx`

**Interfaces:**
- Consumes: `GET /api/document-types`
- Produces: `api.documentTypes(): Promise<DocTypeCard[]>`; `UploadMeta` gains `stage?: "introduced" | "engrossed"`.

- [ ] **Step 1: Write the failing specs**

```tsx
// webapp/src/pages/Upload.test.tsx  (add to the existing file)
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import Upload from "./Upload";
import * as api from "../api";

const ROWS = [
  { key: "baseline-book", label: "Baseline Book", group: "JLBC", formats: [".pdf"],
    where_published: "JLBC, each January.", which_file: "",
    redirect: { action: "add-jlbc-book", label: "Use “Add a JLBC book” instead",
                detail: "Stored as one document per agency." },
    stage_field: false, order: 10 },
  { key: "afr", label: "Annual Financial Report", group: "Auditor General",
    formats: [".pdf"], where_published: "Auditor General, gao.az.gov.",
    which_file: "The combined PDF.", redirect: null, stage_field: false, order: 30 },
  { key: "budget-bill-summary", label: "Budget Bill Summary", group: "JLBC",
    formats: [".pdf"], where_published: "azjlbc.gov/budget/",
    which_file: "The House and Senate Budget Bills PDF.",
    redirect: null, stage_field: true, order: 60 },
];

beforeEach(() => {
  vi.spyOn(api, "documentTypes").mockResolvedValue(ROWS as never);
  vi.spyOn(api, "listJobs").mockResolvedValue({ jobs: [] } as never);
});

describe("upload rows", () => {
  it("renders one row per document type from the API", async () => {
    render(<Upload />);
    expect(await screen.findByText("Annual Financial Report")).toBeInTheDocument();
    expect(screen.getByText("Budget Bill Summary")).toBeInTheDocument();
  });

  it("shows where to get the file and which file to get", async () => {
    render(<Upload />);
    expect(await screen.findByText(/The combined PDF\./)).toBeInTheDocument();
    expect(screen.getByText(/gao\.az\.gov/)).toBeInTheDocument();
  });

  it("a redirect row offers no file input", async () => {
    render(<Upload />);
    const row = (await screen.findByText("Baseline Book")).closest("[data-doc-type]")!;
    expect(row.querySelector('input[type="file"]')).toBeNull();
    expect(row.textContent).toMatch(/Add a JLBC book/);
  });

  it("only the bill summary asks for a stage", async () => {
    render(<Upload />);
    await screen.findByText("Budget Bill Summary");
    const summary = screen.getByText("Budget Bill Summary").closest("[data-doc-type]")!;
    const afr = screen.getByText("Annual Financial Report").closest("[data-doc-type]")!;
    expect(summary.querySelector('select[name="stage"]')).not.toBeNull();
    expect(afr.querySelector('select[name="stage"]')).toBeNull();
  });

  it("sends the stage with the upload", async () => {
    const up = vi.spyOn(api, "uploadDocument").mockResolvedValue(
      { job_id: "j", doc_id: "d" } as never);
    render(<Upload />);
    await screen.findByText("Budget Bill Summary");
    const row = screen.getByText("Budget Bill Summary").closest("[data-doc-type]")!;
    await userEvent.selectOptions(row.querySelector("select[name=stage]")!, "engrossed");
    await userEvent.upload(
      row.querySelector('input[type="file"]')! as HTMLInputElement,
      new File(["x"], "bills.pdf", { type: "application/pdf" }),
    );
    await userEvent.click(row.querySelector('input[type="checkbox"]')!);
    await userEvent.click(screen.getByRole("button", { name: /add document/i }));
    await waitFor(() => expect(up).toHaveBeenCalled());
    expect(up.mock.calls[0][1]).toMatchObject({
      doc_type: "budget-bill-summary", stage: "engrossed",
    });
  });

  it("holds no hardcoded doc_type strings of its own", async () => {
    // The point is to make drift impossible, not to fix today's alignment.
    const src = await import("./Upload.tsx?raw");
    for (const slug of ["baseline-per-agency", "approps-per-agency", "s-pdf",
                        "bh-pdf", "bd-pdf", "detailed-list-pdf", "topic-pdf"]) {
      expect(src.default).not.toContain(`"${slug}"`);
    }
  });
});
```

- [ ] **Step 2: Run to verify failure**

Run: `cd webapp && npx vitest run src/pages/Upload.test.tsx`
Expected: FAIL — `api.documentTypes is not a function`

- [ ] **Step 3: Add the client call**

```ts
// webapp/src/api.ts
export interface DocTypeCard {
  key: string;
  label: string;
  group: string;
  formats: string[];
  where_published: string;
  which_file: string;
  redirect: { action: string; label: string; detail: string } | null;
  stage_field: boolean;
  order: number;
}

export async function documentTypes(): Promise<DocTypeCard[]> {
  const r = await fetch("/api/document-types");
  if (!r.ok) await fail(r, "document types");
  return (await r.json()).types;
}
```

and in `uploadDocument`, after the `title` append:

```ts
  if (meta.stage) form.append("stage", meta.stage);
```

Add `stage?: "introduced" | "engrossed";` to `UploadMeta`.

- [ ] **Step 4: Rewrite the picker as rows**

Delete the `DOC_TYPES` const (lines 30–46) and the `<select>` that consumed
it. Add a new component in the same file:

```tsx
/** One upload row. A row either ACCEPTS A FILE or REDIRECTS — never both.
 *
 *  WHY the redirect rows have no file input at all rather than a disabled
 *  one: a Baseline Book is stored as ~110 per-agency documents, and offering
 *  "which file?" for it is itself the bug (spec S25). An input you are told
 *  not to use still gets used.
 */
function DocTypeRow({
  row,
  onQueued,
}: {
  row: api.DocTypeCard;
  onQueued: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState("");
  const [fy, setFy] = useState(() => String(defaultFiscalYear()));
  const [title, setTitle] = useState("");
  const [publicRecord, setPublicRecord] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  if (row.redirect) {
    return (
      <section className="card up-row" data-doc-type={row.key}>
        <h3>{row.label}</h3>
        <p className="up-note">{row.where_published}</p>
        <p>{row.redirect.detail}</p>
        <button
          type="button"
          className="fchip"
          onClick={() =>
            document
              .querySelector('[data-testid="add-book"]')
              ?.scrollIntoView({ behavior: "smooth" })
          }
        >
          {row.redirect.label}
        </button>
      </section>
    );
  }

  const ready =
    file !== null && publicRecord && (!row.stage_field || stage !== "");

  async function submit() {
    if (!file) return;
    setBusy(true);
    setError("");
    try {
      await api.uploadDocument(file, {
        corpus: "budget",
        publisher: inferPublisher(row.key),
        doc_type: row.key,
        fiscal_year: Number(fy),
        title: title.trim(),
        ...(row.stage_field ? { stage: stage as "introduced" | "engrossed" } : {}),
      });
      setFile(null);
      setPublicRecord(false);
      setStage("");
      onQueued();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card up-row" data-doc-type={row.key}>
      <h3>{row.label}</h3>
      <p className="up-note">{row.where_published}</p>
      <p>{row.which_file}</p>

      <label>
        Document
        <input
          type="file"
          accept={row.formats.join(",")}
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        />
      </label>

      {row.stage_field && (
        <label>
          Version
          <select
            name="stage"
            value={stage}
            onChange={(e) => setStage(e.target.value)}
          >
            <option value="">Choose…</option>
            <option value="introduced">As Introduced</option>
            <option value="engrossed">As Engrossed</option>
          </select>
        </label>
      )}

      <label>
        Fiscal year
        <input value={fy} onChange={(e) => setFy(e.target.value)} inputMode="numeric" />
      </label>

      <label>
        Title (optional)
        <input value={title} onChange={(e) => setTitle(e.target.value)} />
      </label>

      {/* Invariant 8. The server returns 400 without this, so removing it
          here produces a confusing error rather than a hole — but it is the
          deliberate human moment the invariant exists for. Do not remove it. */}
      <label className="up-public">
        <input
          type="checkbox"
          checked={publicRecord}
          onChange={(e) => setPublicRecord(e.target.checked)}
        />
        This document is a public record.
      </label>

      {error && <p className="up-note"><span className="err">{error}</span></p>}

      <button type="button" className="allbtn" disabled={!ready || busy} onClick={() => void submit()}>
        {busy ? "Adding…" : "Add document"}
      </button>
    </section>
  );
}
```

Add the two small helpers beside it — `defaultFiscalYear()` is the existing
heuristic lifted out of `inferMetaFromFilename`, and `inferPublisher` reads
the registry's own grouping so the page still holds no doc_type table:

```tsx
/** Arizona's FY starts in July, so from July onward the work is next
 *  calendar year's book. Lifted verbatim from inferMetaFromFilename. */
function defaultFiscalYear(): number {
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() + 1 : now.getFullYear();
}

/** The publisher each row's documents belong to.
 *
 *  WHY a map here and not on the card: publisher is an ingest-side fact the
 *  registry already records, and it is only four values. If a seventh row
 *  ever needs a fifth publisher, add `publisher` to the DocTypeCard payload
 *  rather than growing this. */
const ROW_PUBLISHERS: Record<string, string> = {
  afr: "agao",
  "governors-budget": "governor",
  "agency-submission": "agency",
  "budget-bill-summary": "jlbc",
};
function inferPublisher(key: string): string {
  return ROW_PUBLISHERS[key] ?? "jlbc";
}
```

Then replace the old form's markup in `Upload`'s render with:

```tsx
  const [rows, setRows] = useState<api.DocTypeCard[] | null>(null);
  useEffect(() => {
    api.documentTypes().then(setRows).catch(() => setRows([]));
  }, []);
  ...
  {(rows ?? []).map((row) => (
    <DocTypeRow key={row.key} row={row} onQueued={() => void refreshJobs()} />
  ))}
```

Keep the existing `AddBookPanel` and queue sections untouched — they are
Plan C's.

> **`ROW_PUBLISHERS` is a small hand-maintained map and this repo distrusts
> those.** It is accepted here only because it is four entries that the
> `test_only_the_bill_summary_asks_for_a_stage`-style route tests cannot
> drift from silently — an unknown publisher is rejected by the upload route
> with a 422. If a fifth is ever needed, move `publisher` onto `DocTypeCard`
> (it is already on `DocType`) and delete the map.

> **Do not remove the Invariant 8 checkbox from any file-accepting row.** It
> gates the endpoint too (`app/routes/upload.py` returns 400 without it), so
> dropping it client-side produces a confusing 400 rather than a security
> hole — but it is still the deliberate human moment the invariant exists for.

- [ ] **Step 5: Run the specs and the type check**

Run: `cd webapp && npx vitest run && npx tsc -b`
Expected: PASS, `tsc -b` exit 0. (`tsc -b` is stricter than `--noEmit` and
rejects unused imports — deleting `DOC_TYPES` will orphan some.)

- [ ] **Step 6: Commit**

```bash
git add webapp/src/api.ts webapp/src/pages/Upload.tsx webapp/src/pages/Upload.test.tsx
git commit -m "feat(webapp): six guided upload rows, served from the registry"
```

---

### Task 7: Teach the model the bill-summary rule (T9)

**Files:**
- Modify: `harness/system-prompt.md` (the "lifecycle of a budget number" section, ~line 725)
- Test: `tests/test_system_prompt_lifecycle.py`

**Interfaces:**
- Consumes: the doc_type names registered in Task 4.
- Produces: nothing programmatic.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_system_prompt_lifecycle.py
"""The supersession rule is prompt-only (spec T9), so the prompt IS the
implementation and these assertions are the only guard it has.

WHY the "check, don't assume" wording is pinned: the model cannot observe
corpus state -- it sees only the chunks a retrieve returned. An instruction
to "ignore the summary if an Appropriations Report exists" is unenforceable
as written. Telling it to RUN A SEARCH makes the condition observable with a
tool it already has, and that is the difference between a rule it can follow
and one it cannot.
"""
from pathlib import Path

import pytest

PROMPT = Path("harness/system-prompt.md").read_text(encoding="utf-8")


def test_the_lifecycle_section_places_the_summary_before_the_approps_report():
    assert "Budget Bill Summary" in PROMPT


def test_the_rule_tells_the_model_to_CHECK_not_to_assume():
    lowered = PROMPT.lower()
    assert "budget-bill-summary" in lowered
    # It must instruct an actual search, not merely state the condition.
    assert "search" in lowered.split("budget bill summary", 1)[1][:1500]


def test_engrossed_supersedes_introduced_is_stated():
    window = PROMPT.split("Budget Bill Summary", 1)[1][:1500].lower()
    assert "engrossed" in window and "introduced" in window


@pytest.mark.parametrize("phrase", ["hallucination-free", "grounded"])
def test_no_marketing_language_crept_in(phrase):
    # Core Invariant 5.
    assert phrase not in PROMPT.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `.venv/bin/python -m pytest tests/test_system_prompt_lifecycle.py -q`
Expected: FAIL — "Budget Bill Summary" absent

- [ ] **Step 3: Add the guidance**

In `harness/system-prompt.md`, add a row to the lifecycle table between
stage 2 (Recommendation) and stage 3 (Enactment):

```markdown
| 2.5 In progress | `budget-bill-summary` | jlbc | JLBC's summary of the budget bills as they move through the Legislature. **Not enacted**, and replaced by the Appropriations Report |
```

and immediately below the table:

```markdown
**Budget Bill Summaries are provisional, and there is often more than one.**

- Use one for a current-year question **only when no Appropriations Report
  exists yet for that fiscal year.** Before relying on a summary, run one
  search filtered to that fiscal year with `doc_type: ["approps-per-agency"]`.
  If it returns material, answer from that and ignore the summary.
- **Engrossed supersedes Introduced.** Never answer "what is the budget for
  X" from an Introduced summary when an Engrossed one is available for the
  same year.
- When you do answer from a summary, say so in the answer — it describes a
  bill in progress, not an enacted appropriation.
```

- [ ] **Step 4: Run the test**

Run: `.venv/bin/python -m pytest tests/test_system_prompt_lifecycle.py tests/test_new_doc_types.py -q`
Expected: PASS

- [ ] **Step 5: Run the full suite and the eval**

```bash
.venv/bin/python -m pytest -q
cd webapp && npx vitest run && npx tsc -b && npm run build
JLBC_DATA_DIR=data/insight-data .venv/bin/python -m eval.run_eval
```

Expected: pytest green (baseline 2368 + the new specs), vitest green,
`tsc -b` exit 0. **Eval: no movement.** `run_eval` calls `retrieve()`
directly and never reads the system prompt, so it cannot measure this change —
it is run because CLAUDE.md requires it after a `system-prompt.md` edit, and
any movement means something else moved and must be explained.

- [ ] **Step 6: Commit**

```bash
git add harness/system-prompt.md tests/test_system_prompt_lifecycle.py eval/results/
git commit -m "feat(prompt): the Budget Bill Summary lifecycle rule (T9)

Written as something the model can CHECK -- it cannot observe corpus state,
so 'ignore the summary if an Appropriations Report exists' is unenforceable
unless it is told to run the search that makes the condition observable."
```

---

## Merging

- [ ] `git fetch origin && git merge origin/master` — **check master again immediately before merging**, not just at the start. It moved twice on 2026-08-11.
- [ ] Re-run `bash setup.sh --verify` capturing the exit code directly: `bash setup.sh --verify > /tmp/verify.log 2>&1; echo $?` — piping into `tail` returns `tail`'s status and hides a failure.
- [ ] Merge with `--no-ff`, push, then `git worktree remove` and `git branch -d`.
- [ ] Update `STATUS.md`: what shipped, the doc_id collision that was found and fixed before it could bite, and that Plans B and C remain.

## What this plan deliberately does NOT do

- **No detection, no fallback, no quality gate** (T5–T8). Plan B. `pick_extractor` still raises on an unknown pair and still routes on the declared type.
- **No `other` catch-all row.** T14. The registry makes a seventh row a data change.
- **No book-panel or queue changes** (T10, T13). Plan C.
- **No backfill** (T11).
- **No re-typing of existing documents.** Task 3 asserts 0 ids move.
