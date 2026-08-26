# Table Section Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A table chunk's `section_path` becomes the heading it physically sits under, instead of the first heading anywhere in the document containing one of its cell strings — and the ~10,200 corpus rows already carrying the wrong answer are repaired in place.

**Architecture:** The readers' `_build_outline` already files every table into the `body_blocks` of the innermost open heading; that list is the haystack the current text search scans. Task 1 exposes it as a lookup (`ExtractedDocument.owner_path`), Task 2 makes the table builder use it and deletes the search, Task 3 proves the two chunk builders now agree on real documents, Tasks 4–6 build a surgical corpus repair modelled on `identity/relabel.py` / `funds/unstamp.py`, and Task 7 runs it behind the spec's gates.

**Tech Stack:** Python 3.12, `uv`, pytest, LanceDB (`store/chunk_store.py`), local ONNX embedder (`retrieval/local_embedder.py`), pydantic models in `chunking/types.py`.

**Spec:** `docs/superpowers/specs/2026-08-26-table-section-path-design.md`. Read D1, D2, §3 and §6 before starting. Where this plan's code and the spec's prose disagree, **the spec wins and the deviation gets recorded** — this repo has recorded plan-code defects on seven consecutive features.

## Global Constraints

- **`chunk_id` must never change.** `chunk_id = f"{doc_id}-{idx:04d}"` and table chunks are emitted first in `doc.tables` order. Nothing in this plan may reorder tables, add a table, or drop one. Eval ground truth, saved transcripts and citation annotations all pin chunk ids.
- **The repair writes exactly four columns:** `section_path`, `text`, `token_count`, `vector`. Every other column is passed through by value. `agency_canonical_ids` and `fund_mentions` in particular must be byte-identical before and after (spec G-T3).
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX weights** (CLAUDE.md). Reader fixtures are committed JSON under `tests/fixtures/`; the corpus at `data/insight-data/` is gitignored and absent from a fresh clone, so **no test may read it**.
- **A repair pass writes the corpus.** It follows the shape `identity/relabel.py` and `funds/unstamp.py` established: dry run takes no lock and writes nothing; apply is lock → snapshot+verify → scan → compute → batched write → verify → reversal record → **`build_fts_index` + `optimize`**. The FTS rebuild is not optional (`funds/unstamp.py` learned it: re-added rows are invisible to BM25 until then).
- **Run the eval after this change.** `retrieval/` is untouched but `chunking/` is not, and `section_path` is line 0 of embedded text. `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`), as a CONTROL on unmodified code immediately before the write and again after. Commit both result files.
- **Worktree:** `~/ask-the-budget-az-worktrees/table-section-path/`, branched off `origin/master`. `ln -s <main-repo>/.venv <worktree>/.venv`.
- **`uvicorn` runs without `--reload`** — Python changes need a server restart if anyone starts one.

---

### Task 1: `ExtractedDocument.owner_path` — the positional lookup

**Files:**
- Modify: `chunking/readers/types.py:153-215` (the `OutlineNode` `body_blocks` comment, the `ExtractedDocument` dataclass, and `outline_path`)
- Test: `tests/test_extracted_document_owner_path.py` (create)

**Interfaces:**
- Consumes: nothing.
- Produces: `ExtractedDocument.owner_path(block: Block) -> list[str]` — the breadcrumb of the outline node whose `body_blocks` contains `block` by **identity**, plus its ancestors; `[]` when no node owns it.

- [ ] **Step 1: Write the failing test**

Create `tests/test_extracted_document_owner_path.py`:

```python
"""ExtractedDocument.owner_path — which section does this block physically sit in?

The counterpart to the deleted `outline_path`: that one SEARCHED the outline
by text and could return a node hundreds of pages away (spec
`2026-08-26-table-section-path-design.md` §1). This one READS the answer the
reader already recorded when it built the outline.
"""
from __future__ import annotations

from pathlib import Path

from chunking.readers.types import (
    Cell,
    ExtractedDocument,
    Heading,
    OutlineNode,
    Page,
    Paragraph,
    Row,
    Table,
)


def _table(text: str, page: int) -> Table:
    return Table(
        page=page,
        pages=[page],
        rows=[Row(cells=[Cell(text=text, row=0, col=0)])],
        html=f"<table><tr><td>{text}</td></tr></table>",
    )


def _doc_with_a_toc_trap() -> tuple[ExtractedDocument, Table, Table]:
    """Mirrors the real defect: a contents page whose body names every
    agency, and an agency table 9 pages later whose first cell is that
    same name."""
    contents = _table("Acupuncture Examiners, Board of", 1)
    agency = _table("Acupuncture Examiners, Board of", 10)
    orphan = _table("FY 2026 Executive Budget", 1)

    toc_node = OutlineNode(text="Table of Contents", level=1, page=1, body_blocks=[contents])
    agency_node = OutlineNode(
        text="Acupuncture Examiners, Board of", level=1, page=9, body_blocks=[agency]
    )
    doc = ExtractedDocument(
        source_path=Path("fake"),
        extractor="opendataloader",
        pages=[
            Page(page_number=1, blocks=[orphan, Heading(text="Table of Contents", level=1, page=1), contents]),
            Page(page_number=9, blocks=[Heading(text="Acupuncture Examiners, Board of", level=1, page=9)]),
            Page(page_number=10, blocks=[agency]),
        ],
        outline=[toc_node, agency_node],
    )
    return doc, agency, orphan


def test_owner_path_returns_the_node_that_physically_holds_the_block():
    doc, agency, _ = _doc_with_a_toc_trap()
    assert doc.owner_path(agency) == ["Acupuncture Examiners, Board of"]


def test_owner_path_is_identity_not_text_so_a_duplicate_string_cannot_win():
    """Both tables carry the identical cell string. A text search returns the
    contents page for BOTH (that is the shipped defect); identity cannot."""
    doc, agency, _ = _doc_with_a_toc_trap()
    contents = doc.outline[0].body_blocks[0]
    assert contents.rows[0].cells[0].text == agency.rows[0].cells[0].text
    assert doc.owner_path(contents) == ["Table of Contents"]
    assert doc.owner_path(agency) == ["Acupuncture Examiners, Board of"]


def test_owner_path_is_empty_for_a_block_before_the_first_heading():
    """`_build_outline` appends to `stack[-1]` only when the stack is
    non-empty, so a block before the first heading belongs to no node.
    Spec D2: that is an empty path, not a guess."""
    doc, _, orphan = _doc_with_a_toc_trap()
    assert doc.owner_path(orphan) == []


def test_owner_path_includes_ancestors_deepest_last():
    child = _table("row", 3)
    parent = OutlineNode(
        text="Financial Statements",
        level=1,
        page=2,
        children=[OutlineNode(text="Note 3", level=2, page=3, body_blocks=[child])],
    )
    doc = ExtractedDocument(source_path=Path("fake"), extractor="mineru", outline=[parent])
    assert doc.owner_path(child) == ["Financial Statements", "Note 3"]


def test_owner_path_answers_repeatedly_and_consistently():
    """It memoizes; a second call must not return a different answer."""
    doc, agency, orphan = _doc_with_a_toc_trap()
    assert doc.owner_path(agency) == ["Acupuncture Examiners, Board of"]
    assert doc.owner_path(orphan) == []
    assert doc.owner_path(agency) == ["Acupuncture Examiners, Board of"]


def test_owner_path_also_owns_paragraphs_not_just_tables():
    """The narrative builder reaches the same answer through `visit()`; this
    is the same fact from the other side, and Task 3 pins that they agree."""
    para = Paragraph(text="The Baseline includes $1.0 M for the program.", page=4)
    node = OutlineNode(text="Operating Budget", level=1, page=4, body_blocks=[para])
    doc = ExtractedDocument(source_path=Path("fake"), extractor="mineru", outline=[node])
    assert doc.owner_path(para) == ["Operating Budget"]
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_extracted_document_owner_path.py -v`

Expected: every test FAILS with `AttributeError: 'ExtractedDocument' object has no attribute 'owner_path'`. If any test errors on a constructor signature instead, fix the fixture to match `chunking/readers/types.py` — do not change the assertions.

- [ ] **Step 3: Implement `owner_path`**

In `chunking/readers/types.py`, add these two lines to the `ExtractedDocument` dataclass field list, after `sections`:

```python
    # Memo for `owner_path`, built on first call. Readers construct the
    # outline as the LAST step of `read()` and never mutate it afterwards,
    # so one build is safe; `init=False` + `compare=False` keep it out of
    # the dataclass's constructor, equality and repr.
    _owner_memo: dict[int, list[str]] | None = field(
        default=None, init=False, compare=False, repr=False
    )
```

Then add the method immediately **above** `outline_path`:

```python
    def owner_path(self, block: Block) -> list[str]:
        """Breadcrumb of the outline node that PHYSICALLY owns `block`.

        `_build_outline` (both PDF readers) appends every non-`Heading`
        block to `stack[-1].body_blocks` — the innermost heading open at
        that point in the document. So the answer to "which section is this
        block in?" was recorded at read time and needs no searching.

        Matching is by IDENTITY (`is`), never by text. That is the whole
        point: on 2026-08-26 the text-searching `outline_path` was measured
        binding tables to headings a median of 93 pages away, because two
        different blocks routinely carry the same string — a contents page
        lists every agency name in the book, so an agency's own table finds
        its name there first (spec §1.1).

        Returns `[]` when no node owns `block` — a block appearing before
        the document's first heading, which `_build_outline` attaches to
        nothing. Spec D2 makes that an empty `section_path` rather than a
        guess.
        """
        if self._owner_memo is None:
            memo: dict[int, list[str]] = {}

            def walk(node: "OutlineNode", ancestors: list[str]) -> None:
                here = ancestors + [node.text]
                for b in node.body_blocks:
                    memo[id(b)] = here
                for child in node.children:
                    walk(child, here)

            for root in self.outline:
                walk(root, [])
            self._owner_memo = memo
        return list(self._owner_memo.get(id(block), []))
```

- [ ] **Step 4: Correct the `body_blocks` comment, which credits the wrong consumer**

In `chunking/readers/types.py`, replace the two-line comment above `body_blocks` in `OutlineNode`:

```python
    # The blocks that physically sit under this heading, recorded at read
    # time by `_build_outline`. Read by `ExtractedDocument.owner_path`
    # (which section is this block in?) and by
    # `narrative_chunk.visit` (which paragraphs belong to this section?).
    body_blocks: list[Block] = field(default_factory=list)
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_extracted_document_owner_path.py -v`
Expected: 6 passed.

Then run the readers' own suites to prove nothing moved:

Run: `uv run pytest tests/test_mineru_reader.py tests/test_odl_reader.py tests/test_docx_reader.py -q`
Expected: all pass, same counts as before this task.

- [ ] **Step 6: Verify the memo cannot be fooled — mutate in place, do not copy**

Temporarily change `if id(b) is not None` … no: instead, replace `memo[id(b)] = here` with `memo[id(b)] = list(ancestors)` (dropping the node's own text), run
`uv run pytest tests/test_extracted_document_owner_path.py -v`, and confirm **4 tests fail**. Then `git checkout chunking/readers/types.py` is NOT usable here (the file has unstaged work) — revert the single line by hand and re-run to confirm 6 passed.

- [ ] **Step 7: Commit**

```bash
git add chunking/readers/types.py tests/test_extracted_document_owner_path.py
git commit -m "chunking: ExtractedDocument.owner_path — read which section a block sits in

The readers already record it: _build_outline appends every non-Heading
block to the innermost open heading's body_blocks. owner_path reads that
map by identity instead of searching it by text."
```

---

### Task 2: Table chunks read the owning heading; the text search is deleted

**Files:**
- Modify: `chunking/builders/table_chunk.py:44-155` (`build_table_chunk` docstring + `_resolve_section_path` deleted)
- Modify: `chunking/readers/types.py` (delete `outline_path` and its `_block_text` helper if it has no other caller)
- Modify: `chunking/readers/mineru_reader.py:226-241` and `chunking/readers/odl_reader.py:212-227` (the `_build_outline` docstrings describing the old behaviour)
- Modify: `chunking/builders/narrative_chunk.py:27` (comment referencing `outline_path`)
- Modify: `tests/test_mineru_reader.py` (delete `test_mineru_reader_outline_path_finds_table_content`)
- Modify: `tests/test_table_chunk.py`
- Test: `tests/test_table_chunk.py` (new cases)

**Interfaces:**
- Consumes: `ExtractedDocument.owner_path(block) -> list[str]` from Task 1.
- Produces: `build_table_chunk(table, doc, doc_meta, *, chunk_index, section_path=None) -> Chunk` — unchanged signature; when `section_path is None` it now resolves via `doc.owner_path(table)`.

- [ ] **Step 1: Confirm `outline_path` has exactly one production caller before deleting it**

Run: `grep -rn "outline_path" --include='*.py' . | grep -v __pycache__`

Expected: hits in `chunking/builders/table_chunk.py` (the caller), `chunking/readers/types.py` (the definition), three comments (`narrative_chunk.py:27`, `mineru_reader.py`, `odl_reader.py`), and one test (`tests/test_mineru_reader.py`). **If a production caller outside `table_chunk.py` appears, stop and report it** — the spec's D1 rests on there being none.

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_table_chunk.py`:

```python
def _toc_trap_doc():
    """A contents page listing an agency, and that agency's own table nine
    pages later. Both tables carry the identical first-cell string — the
    shipped defect (spec §1.1) labels the agency table 'Table of Contents'."""
    from pathlib import Path

    from chunking.readers.types import (
        Cell, ExtractedDocument, Heading, OutlineNode, Page, Row, Table,
    )

    def t(text, page):
        return Table(
            page=page, pages=[page],
            rows=[Row(cells=[Cell(text=text, row=0, col=0)])],
            html=f"<table><tr><td>{text}</td></tr></table>",
        )

    contents = t("Acupuncture Examiners, Board of", 1)
    agency = t("Acupuncture Examiners, Board of", 10)
    orphan = t("FY 2026 Executive Budget", 1)
    doc = ExtractedDocument(
        source_path=Path("fake"), extractor="opendataloader",
        pages=[
            Page(page_number=1, blocks=[orphan, Heading(text="Table of Contents", level=1, page=1), contents]),
            Page(page_number=9, blocks=[Heading(text="Acupuncture Examiners, Board of", level=1, page=9)]),
            Page(page_number=10, blocks=[agency]),
        ],
        outline=[
            OutlineNode(text="Table of Contents", level=1, page=1, body_blocks=[contents]),
            OutlineNode(text="Acupuncture Examiners, Board of", level=1, page=9, body_blocks=[agency]),
        ],
    )
    return doc, agency, orphan


def test_a_table_is_labelled_with_the_heading_it_sits_under_not_a_text_match():
    doc, agency, _ = _toc_trap_doc()
    chunk = build_table_chunk(agency, doc, _approps_meta(), chunk_index=0)
    assert chunk.section_path == ["Acupuncture Examiners, Board of"]


def test_the_contents_page_no_longer_captures_every_table_in_the_book():
    """Regression pin for the measured defect: 1,079 of 1,246 tables in
    governor-governors-budget-fy2026 were filed under 'Table of Contents'."""
    doc, agency, _ = _toc_trap_doc()
    chunk = build_table_chunk(agency, doc, _approps_meta(), chunk_index=0)
    assert "Table of Contents" not in chunk.section_path
    assert not chunk.text.startswith("Table of Contents")


def test_a_table_under_no_heading_gets_an_empty_path_and_no_heading_line():
    """Spec D2. `_build_text` opens with `if section_path:`, so an empty
    path must produce a chunk whose FIRST line is already table data — not
    a blank line. The repair in Task 5 depends on this exact shape."""
    doc, _, orphan = _toc_trap_doc()
    chunk = build_table_chunk(orphan, doc, _approps_meta(), chunk_index=0)
    assert chunk.section_path == []
    assert chunk.text.splitlines()[0] == "FY 2026 Executive Budget"


def test_an_explicit_section_path_still_wins():
    doc, agency, _ = _toc_trap_doc()
    chunk = build_table_chunk(
        agency, doc, _approps_meta(), chunk_index=0, section_path=["Given"]
    )
    assert chunk.section_path == ["Given"]
```

- [ ] **Step 3: Run the tests to verify they fail**

Run: `uv run pytest tests/test_table_chunk.py -k "toc or sits_under or empty_path or explicit_section" -v`

Expected: `test_a_table_is_labelled_with_the_heading_it_sits_under_not_a_text_match` and `test_the_contents_page_no_longer_captures_every_table_in_the_book` FAIL, asserting `["Table of Contents"]`. That failure **is the defect reproduced** — record the actual value in the commit message.

- [ ] **Step 4: Replace the resolver**

In `chunking/builders/table_chunk.py`, delete the whole `_resolve_section_path` function (currently the last function in the file, ~line 118 to end) and change the resolution line inside `build_table_chunk`:

```python
    if section_path is None:
        section_path = doc.owner_path(table)
```

Replace the `section_path` paragraph of `build_table_chunk`'s docstring with:

```python
    `section_path`, when omitted, is the heading the table PHYSICALLY sits
    under — `doc.owner_path(table)`, the same fact `narrative_chunk.visit`
    reads for paragraphs, so two chunks on one page can no longer disagree
    about their section.

    It used to be resolved by searching the whole document for the table's
    own cell text (`outline_path`). Measured 2026-08-26 on the live corpus:
    that put tables a MEDIAN of 93 pages from the heading they were given,
    and filed 1,079 of the 1,246 tables in the FY2026 Governor's Budget
    under its table of contents, because the contents page names every
    agency in the book and matched first. Do not reintroduce a text search
    here. Spec: docs/superpowers/specs/2026-08-26-table-section-path-design.md
```

- [ ] **Step 5: Delete `outline_path`**

In `chunking/readers/types.py`, delete the `outline_path` method and the module-level `_block_text` helper below it — **first** confirm `_block_text` has no other caller:

Run: `grep -rn "_block_text" --include='*.py' . | grep -v __pycache__`
Expected: only the definition and `outline_path`'s use of it. If anything else uses it, keep `_block_text` and delete only `outline_path`.

Delete `test_mineru_reader_outline_path_finds_table_content` from `tests/test_mineru_reader.py` (around line 86).

- [ ] **Step 6: Correct the three stale docstrings**

`chunking/readers/mineru_reader.py`, in `_build_outline`, replace the paragraph beginning `THIS DOES NOT DECIDE A CHUNK'S section_path…` with:

```
        THIS IS WHERE A CHUNK'S `section_path` COMES FROM. Both builders
        read the `body_blocks` this method fills:
        `narrative_chunk.visit` walks the tree for paragraphs, and
        `table_chunk.build_table_chunk` asks
        `ExtractedDocument.owner_path(table)`.

        Until 2026-08-26 the table side instead SEARCHED the outline by
        text and this docstring warned that the walk below was not
        load-bearing. It is now. A bounded version of the walk was built,
        calibrated and shipped against the old design on 2026-08-16, was
        measured to change ZERO chunks, and was reverted (`1292030`) —
        because it bounded a mechanism nothing read. That no longer
        applies, which cuts both ways: **whatever you change here now
        DOES move production chunks.** Run `chunk_doc` end-to-end over
        cached extractor output and diff the section paths first
        (`scripts/diff_section_paths.py`, Task 3).
```

Apply the same replacement to `chunking/readers/odl_reader.py`'s `_build_outline` docstring.

In `chunking/builders/narrative_chunk.py:27`, replace `identical to what ExtractedDocument.outline_path would return for` with `identical to what ExtractedDocument.owner_path returns for`.

- [ ] **Step 7: Run the full chunking suite**

Run: `uv run pytest tests/test_table_chunk.py tests/test_narrative_chunk.py tests/test_chunk_builder.py tests/test_mineru_reader.py tests/test_odl_reader.py -q`

Expected: all pass. **Any test that fails here is a test that was pinning the text-search behaviour** — read it, and if it asserted a section path that came from a distant heading, re-point it at the positional answer and say so in the commit. Do not weaken an assertion to make it pass.

- [ ] **Step 8: Run the whole suite**

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: no new failures against the baseline count recorded at the start of the worktree.

- [ ] **Step 9: Commit**

```bash
git add chunking/builders/table_chunk.py chunking/readers/types.py \
        chunking/readers/mineru_reader.py chunking/readers/odl_reader.py \
        chunking/builders/narrative_chunk.py \
        tests/test_table_chunk.py tests/test_mineru_reader.py
git commit -m "chunking: a table is labelled with the heading it sits under

_resolve_section_path searched the whole document for the table's own cell
text and took the earliest shallowest match. Measured on the live corpus:
median 93 pages between a table and the heading it was given, and 1,079 of
1,246 tables in the FY2026 Governor's Budget filed under 'Table of
Contents' because the contents page names every agency in the book.

outline_path had exactly one production caller and is deleted with it."
```

---

### Task 3: Prove it on real documents — the cross-producer guard and the diff harness

**Files:**
- Create: `scripts/diff_section_paths.py`
- Create: `tests/fixtures/odl-gov-toc-slice/page-1.json`, `tests/fixtures/odl-gov-toc-slice/page-10.json`
- Create: `tests/test_section_path_producers_agree.py`
- Modify: `tests/fixtures/README.md`

**Interfaces:**
- Consumes: Task 2's changed builder.
- Produces: `scripts/diff_section_paths.py::diff_document(doc_id: str, root: Path) -> dict` — `{"doc_id", "tables", "changed", "relabelled", "to_blank", "examples"}`; and `resolve_extract_dir(doc_id: str, root: Path) -> tuple[Path, str] | None` returning `(directory, extractor_name)`. **Task 4 imports `resolve_extract_dir` from here** — do not duplicate it.

- [ ] **Step 1: Write `scripts/diff_section_paths.py`**

```python
"""Diff table `section_path`s between the shipped rule and this checkout.

WHY this is a script and not a test: it reads `<data_dir>/extractor-output/`,
which is gitignored and absent from a fresh clone, so a test that opened it
would fail for anyone who had not run an ingest (CLAUDE.md testing
conventions). It is also the harness spec gate G-T6 requires — the
2026-08-16 attempt at this defect passed twelve specs and five of six
mutations while changing zero production chunks, because every measurement
was taken against a mechanism no chunk reads.

Usage:
    uv run python -m scripts.diff_section_paths --doc governor-governors-budget-fy2026
    uv run python -m scripts.diff_section_paths --sample 30
"""
from __future__ import annotations

import argparse
import collections
import json
import random
from pathlib import Path
from typing import Any

from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.odl_reader import ODLReader
from store.config import resolve_data_dir


def resolve_extract_dir(doc_id: str, root: Path) -> tuple[Path, str] | None:
    """Where this document's extractor output lives, and which reader reads it.

    Two shapes exist on the share and both are live:
      * `<root>/extractor-output/<doc_id>/page-N.json` — the pre-rung layout,
        which is the overwhelming majority (390 of 400 sampled);
      * `<root>/extractor-output/<doc_id>/<method>/page-N.json` — the
        rung-scoped layout `ingest/worker.py::_extract_dir` writes. A method
        subdirectory SUPERSEDES the root output: `agao-afr-fy2024` was
        re-read with MinerU on 2026-08-16 and its root output is the older
        OpenDataLoader reading.

    The reader is chosen from the page file's own `extractor` field, never
    from `manifest.json` — thousands of documents have no manifest, and
    `agao-afr-fy2024`'s manifest says `opendataloader` while the reading the
    corpus actually holds is MinerU's, in a subdirectory.
    """
    base = root / "extractor-output" / doc_id
    if not base.is_dir():
        return None
    directory = base
    for sub in ("mineru-ocr", "mineru", "opendataloader"):
        candidate = base / sub
        if candidate.is_dir() and any(candidate.glob("page-*.json")):
            directory = candidate
            break
    first = next(iter(sorted(directory.glob("page-*.json"))), None)
    if first is None:
        return None
    try:
        extractor = str(json.loads(first.read_text(encoding="utf-8")).get("extractor", ""))
    except (OSError, ValueError):
        return None
    return directory, extractor


def _reader(extractor: str):
    return ODLReader() if "opendataloader" in extractor.lower() else MinerUReader()


def _old_rule(table, doc) -> list[str]:
    """The DELETED text search, kept here so the diff has something to
    compare against. It is a copy on purpose: production must not keep a
    second way to answer this question (spec D1), but a measurement needs
    the before-picture."""
    candidates: list[str] = []
    for row in table.rows[:3]:
        for cell in row.cells:
            t = " ".join(cell.text.split())
            if len(t) >= 4:
                candidates.append(t)
    for q in candidates:
        best: list[str] = []
        needle = q.casefold()

        def walk(node, ancestors):
            nonlocal best
            here = ancestors + [node.text]
            for child in node.children:
                walk(child, here)
            if best and len(best) >= len(here):
                return
            body = " ".join(
                " ".join(c.text for r in getattr(b, "rows", []) for c in r.cells)
                or getattr(b, "text", "")
                for b in node.body_blocks
            )
            if needle in node.text.casefold() or needle in body.casefold():
                best = here

        for root_node in doc.outline:
            walk(root_node, [])
        if best:
            return best
    return []


def diff_document(doc_id: str, root: Path) -> dict[str, Any]:
    found = resolve_extract_dir(doc_id, root)
    if found is None:
        return {"doc_id": doc_id, "skipped": "no cached extractor output"}
    directory, extractor = found
    doc = _reader(extractor).read(directory)
    relabelled = to_blank = 0
    examples: list[tuple[int | None, str, str]] = []
    for table in doc.tables:
        old = _old_rule(table, doc)
        new = doc.owner_path(table)
        if old == new:
            continue
        if new:
            relabelled += 1
        else:
            to_blank += 1
        if len(examples) < 5:
            page = table.pages[0] if table.pages else table.page
            examples.append((page, " > ".join(old), " > ".join(new)))
    return {
        "doc_id": doc_id,
        "extractor": extractor,
        "tables": len(doc.tables),
        "changed": relabelled + to_blank,
        "relabelled": relabelled,
        "to_blank": to_blank,
        "examples": examples,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doc", action="append", default=[], help="doc_id (repeatable)")
    ap.add_argument("--sample", type=int, default=0, help="also diff N random documents")
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)

    root = resolve_data_dir()
    doc_ids = list(args.doc)
    if args.sample:
        docs = json.loads((root / "documents.json").read_text(encoding="utf-8"))
        pool = [d for d in docs if (root / "extractor-output" / d).is_dir()]
        random.Random(args.seed).shuffle(pool)
        doc_ids += pool[: args.sample]

    totals = collections.Counter()
    for doc_id in doc_ids:
        result = diff_document(doc_id, root)
        if "skipped" in result:
            print(f"{doc_id[:46]:46s} SKIPPED ({result['skipped']})")
            totals["skipped"] += 1
            continue
        totals["tables"] += result["tables"]
        totals["changed"] += result["changed"]
        totals["relabelled"] += result["relabelled"]
        totals["to_blank"] += result["to_blank"]
        print(
            f"{doc_id[:46]:46s} tables={result['tables']:5d} "
            f"changed={result['changed']:5d} "
            f"(relabelled={result['relabelled']}, to_blank={result['to_blank']})"
        )
        for page, old, new in result["examples"]:
            print(f"    p{page}: {old[:60]!r} -> {new[:60]!r}")
    print(f"\nTOTAL tables={totals['tables']} changed={totals['changed']} "
          f"relabelled={totals['relabelled']} to_blank={totals['to_blank']} "
          f"skipped_docs={totals['skipped']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it against the two documents the spec names**

```bash
cd ~/ask-the-budget-az-worktrees/table-section-path
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
  uv run python -m scripts.diff_section_paths \
  --doc governor-governors-budget-fy2026 --doc agao-afr-fy2024 --doc agao-afr-fy2021
```

Expected, from the spec's own measurements — **these are predictions, and a mismatch means the model of the defect is wrong, so stop and report rather than proceeding**:

| doc | tables | changed |
|---|---|---|
| `governor-governors-budget-fy2026` | 1,246 | 1,197 |
| `agao-afr-fy2024` | 422 | ~261 (61.9% of 422) |

At least one `governor` example line must read
`'Table of Contents' -> 'Acupuncture Examiners, Board of'` or similar.

- [ ] **Step 3: Build the committed fixture from the real slice**

The fixture must be REAL, not synthetic — this defect only appears when a
contents page's body genuinely names a later agency, which is easy to get
wrong by hand.

```bash
DATA=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data
SRC=$DATA/extractor-output/governor-governors-budget-fy2026
mkdir -p tests/fixtures/odl-gov-toc-slice
cp $SRC/page-1.json  tests/fixtures/odl-gov-toc-slice/page-1.json
cp $SRC/page-10.json tests/fixtures/odl-gov-toc-slice/page-10.json
ls -la tests/fixtures/odl-gov-toc-slice/
```

If either file exceeds ~400 KB, trim its `blocks` array to the first heading, the contents table, and the agency table — keep the JSON shape identical, and record in `tests/fixtures/README.md` that it was trimmed.

Add a row to the table in `tests/fixtures/README.md`:

```
| `odl-gov-toc-slice/` | OpenDataLoader-PDF per-page output, pages 1 + 10 of `governor-governors-budget-fy2026` | The real contents-page-captures-every-table defect (spec 2026-08-26). Two files, read as a directory. Trimmed only if noted here. |
```

- [ ] **Step 4: Write the cross-producer guard**

Create `tests/test_section_path_producers_agree.py`:

```python
"""G-T1 — the two `section_path` producers must agree.

Every existing test asks "is this chunk's label correct?". None asked "do
our two labellers agree with each other?", and that is exactly the gap that
let the defect live: `narrative_chunk.visit` read the answer positionally
while `table_chunk` searched for it by text. CLAUDE.md, measurement
discipline: *a per-item check cannot find a cross-item defect... when a
field has more than one producer, the test that matters compares the
producers' output.*
"""
from __future__ import annotations

from pathlib import Path

from chunking.builders.narrative_chunk import build_narrative_chunks
from chunking.builders.table_chunk import DocMeta, build_table_chunk
from chunking.readers.odl_reader import ODLReader
from chunking.readers.types import Paragraph, Table

FIXTURE = Path(__file__).parent / "fixtures" / "odl-gov-toc-slice"


def _meta() -> DocMeta:
    return DocMeta(
        doc_id="governor-governors-budget-fy2026",
        publisher="governor",
        doc_type="governors-budget",
        fiscal_year=2026,
        extractor="opendataloader",
    )


def test_every_table_chunk_agrees_with_the_owner_lookup():
    doc = ODLReader().read(FIXTURE)
    assert doc.tables, "fixture must contain tables"
    for index, table in enumerate(doc.tables):
        chunk = build_table_chunk(table, doc, _meta(), chunk_index=index)
        assert chunk.section_path == doc.owner_path(table), (
            f"table {index} on page {table.page}: builder said "
            f"{chunk.section_path!r}, owner lookup says {doc.owner_path(table)!r}"
        )


def test_every_narrative_chunk_agrees_with_the_owner_lookup():
    """The narrative builder reaches its path through `visit()`, never
    through `owner_path`. If the two ever diverge, one of them is wrong."""
    doc = ODLReader().read(FIXTURE)
    paragraph_owner: dict[int, list[str]] = {}

    def walk(node, ancestors):
        here = ancestors + [node.text]
        for block in node.body_blocks:
            if isinstance(block, Paragraph):
                paragraph_owner[id(block)] = here
        for child in node.children:
            walk(child, here)

    for root in doc.outline:
        walk(root, [])

    for chunk in build_narrative_chunks(doc, _meta(), start_index=0):
        # A chunk merges several paragraphs from ONE node, so any one of the
        # node's paragraphs answers for it; an orphan chunk has no owner and
        # an empty path (narrative_chunk.py's `_orphaned_paragraphs`).
        assert chunk.section_path == [] or chunk.section_path in paragraph_owner.values()


def test_the_contents_page_does_not_capture_the_agency_table():
    """The defect, pinned against the real slice it was measured on."""
    doc = ODLReader().read(FIXTURE)
    late = [t for t in doc.tables if (t.pages[0] if t.pages else t.page) >= 10]
    assert late, "fixture must contain a table from page 10"
    for table in late:
        chunk = build_table_chunk(table, doc, _meta(), chunk_index=0)
        assert "Table of Contents" not in chunk.section_path
```

- [ ] **Step 5: Run it**

Run: `uv run pytest tests/test_section_path_producers_agree.py -v`
Expected: 3 passed.

If `test_the_contents_page_does_not_capture_the_agency_table` fails with an
empty `late` list, the fixture pages were trimmed too aggressively — re-copy
`page-10.json` untrimmed.

- [ ] **Step 6: Prove the guard can fail**

In `chunking/builders/table_chunk.py`, temporarily change
`section_path = doc.owner_path(table)` to `section_path = ["Table of Contents"]`.

Run: `uv run pytest tests/test_section_path_producers_agree.py -v`
Expected: `test_every_table_chunk_agrees_with_the_owner_lookup` and
`test_the_contents_page_does_not_capture_the_agency_table` FAIL.

Revert the line by hand and re-run: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add scripts/diff_section_paths.py tests/test_section_path_producers_agree.py \
        tests/fixtures/odl-gov-toc-slice tests/fixtures/README.md
git commit -m "chunking: cross-producer guard + the real Governor's-budget slice

G-T1: table and narrative chunks must agree about which section a page is
in. Every existing test asked whether one chunk's label was right; nothing
asked whether our two labellers agreed, which is how the defect survived.

scripts/diff_section_paths.py is the end-to-end harness G-T6 needs: the
2026-08-16 attempt at this bug passed twelve specs and five of six
mutations while changing zero production chunks."
```

---

### Task 4: The repair pass — planning and the dry run

**Files:**
- Create: `chunking/repair_section_paths.py`
- Test: `tests/test_repair_section_paths.py` (create)

**Interfaces:**
- Consumes: `scripts.diff_section_paths.resolve_extract_dir`, `ExtractedDocument.owner_path`, `chunking.builders._tokens.count_tokens`, `store.chunk_store.ChunkStore.scan/upsert_chunks`.
- Produces:
  - `PLAN_COLUMNS: list[str]`
  - `@dataclass(frozen=True) RowChange` with fields `chunk_id: str`, `doc_id: str`, `old_path: list[str]`, `new_path: list[str]`, `old_text: str`, `new_text: str`
  - `@dataclass RepairResult` with fields `changed: int`, `scanned: int`, `documents_planned: int`, `documents_skipped: dict[str, str]`, `reversal: list[dict]`
  - `plan_document(doc_id, rows, root) -> tuple[list[RowChange], str | None]` — changes, and a skip reason when the document cannot be planned
  - `repair_section_paths(*, store, embedder, root, table="budget_chunks", dry_run=True, ...) -> RepairResult`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_repair_section_paths.py`:

```python
"""The surgical section_path repair (spec §3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chunking.repair_section_paths import (
    PLAN_COLUMNS,
    RowChange,
    plan_document,
    repair_section_paths,
)


def _page_json(page: int, blocks: list[dict]) -> dict:
    return {"extractor": "mineru-3.1.6", "source_pdf": "x.pdf", "page": page, "blocks": blocks}


def _heading(text: str) -> dict:
    return {"type": "text", "text": text, "text_level": 1}


def _table(cell: str) -> dict:
    return {"type": "table", "table_body": f"<table><tr><td>{cell}</td></tr></table>"}


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A data dir holding one document's cached extractor output: a contents
    page naming an agency, then that agency's own table."""
    out = tmp_path / "extractor-output" / "doc-a"
    out.mkdir(parents=True)
    (out / "page-1.json").write_text(json.dumps(_page_json(1, [
        _heading("Table of Contents"), _table("Acupuncture Examiners, Board of"),
    ])), encoding="utf-8")
    (out / "page-9.json").write_text(json.dumps(_page_json(9, [
        _heading("Acupuncture Examiners, Board of"), _table("Acupuncture Examiners, Board of"),
    ])), encoding="utf-8")
    return tmp_path


def _stored_rows() -> list[dict]:
    """What the corpus holds today: BOTH tables labelled 'Table of Contents',
    because the text search matched the contents page first."""
    return [
        {"chunk_id": "doc-a-0000", "doc_id": "doc-a", "is_table": True,
         "section_path": ["Table of Contents"],
         "text": "Table of Contents\nAcupuncture Examiners, Board of"},
        {"chunk_id": "doc-a-0001", "doc_id": "doc-a", "is_table": True,
         "section_path": ["Table of Contents"],
         "text": "Table of Contents\nAcupuncture Examiners, Board of"},
    ]


def test_plan_relabels_the_second_table_and_leaves_the_first(root: Path):
    changes, skipped = plan_document("doc-a", _stored_rows(), root)
    assert skipped is None
    assert [c.chunk_id for c in changes] == ["doc-a-0001"]
    assert changes[0].new_path == ["Acupuncture Examiners, Board of"]
    assert changes[0].new_text == (
        "Acupuncture Examiners, Board of\nAcupuncture Examiners, Board of"
    )


def test_plan_removes_the_heading_line_entirely_when_the_path_goes_empty(root: Path):
    """Spec §3.3: to-blank REMOVES line 0; it does not leave a blank line.
    `_build_text` opens with `if section_path:`, so a blank first line would
    not match what a fresh chunk_doc produces (G-T6)."""
    rows = [{"chunk_id": "doc-a-0000", "doc_id": "doc-a", "is_table": True,
             "section_path": ["Somewhere Else"],
             "text": "Somewhere Else\nAcupuncture Examiners, Board of"}]
    out = (root / "extractor-output" / "doc-a" / "page-1.json")
    out.write_text(json.dumps(_page_json(1, [_table("Acupuncture Examiners, Board of")])),
                   encoding="utf-8")
    (root / "extractor-output" / "doc-a" / "page-9.json").unlink()
    changes, skipped = plan_document("doc-a", rows, root)
    assert skipped is None
    assert changes[0].new_path == []
    assert changes[0].new_text == "Acupuncture Examiners, Board of"
    assert not changes[0].new_text.startswith("\n")


def test_plan_refuses_a_document_whose_body_no_longer_matches(root: Path):
    """The chunk<->table mapping is a hypothesis per document and is GATED
    (spec §3.2). Every line but line 0 must match, or the document is
    skipped and named."""
    rows = _stored_rows()
    rows[1]["text"] = "Table of Contents\nSOMETHING ELSE ENTIRELY"
    changes, skipped = plan_document("doc-a", rows, root)
    assert changes == []
    assert skipped is not None and "body" in skipped.lower()


def test_plan_refuses_a_document_with_a_different_table_count(root: Path):
    rows = _stored_rows() + [
        {"chunk_id": "doc-a-0002", "doc_id": "doc-a", "is_table": True,
         "section_path": [], "text": "extra"}
    ]
    changes, skipped = plan_document("doc-a", rows, root)
    assert changes == []
    assert skipped is not None and "count" in skipped.lower()


def test_plan_skips_a_document_with_no_cached_extractor_output(tmp_path: Path):
    changes, skipped = plan_document("doc-missing", _stored_rows(), tmp_path)
    assert changes == []
    assert skipped is not None and "extractor output" in skipped.lower()


def test_narrative_rows_are_never_touched(root: Path):
    rows = _stored_rows() + [
        {"chunk_id": "doc-a-0002", "doc_id": "doc-a", "is_table": False,
         "section_path": ["Table of Contents"], "text": "prose"}
    ]
    changes, skipped = plan_document("doc-a", rows, root)
    assert skipped is None
    assert all(c.chunk_id != "doc-a-0002" for c in changes)


class _FakeStore:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.written: list[list[dict]] = []
        self.fts_built: list[str] = []
        self.optimized: list[str] = []

    def scan(self, name, columns, *, where=None, limit=None):
        return [{k: r[k] for k in columns if k in r} for r in self.rows]

    def upsert_chunks(self, name, rows):
        self.written.append(list(rows))

    def build_fts_index(self, name):
        self.fts_built.append(name)

    def optimize(self, name, *, retention=None):
        self.optimized.append(name)


class _FakeEmbedder:
    dim = 4

    def embed_batch(self, texts, *, input_type="document"):
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


def test_dry_run_writes_nothing_and_takes_no_lock(root: Path):
    store = _FakeStore(_stored_rows())
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=True
    )
    assert result.changed == 1
    assert result.scanned == 2
    assert store.written == []
    assert store.fts_built == []
    assert len(result.reversal) == 1
    assert result.reversal[0]["chunk_id"] == "doc-a-0001"
    assert result.reversal[0]["before"]["section_path"] == ["Table of Contents"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'chunking.repair_section_paths'`.

- [ ] **Step 3: Write the module's planning half**

Create `chunking/repair_section_paths.py`:

```python
"""Repair `section_path` on table chunks already in the corpus (spec §3).

**A surgical rewrite, NOT a re-ingest, and that is not a preference.**
`identity/merge_agencies.py` merged nine duplicate agency ids out of the
corpus on 2026-08-16 by rewriting rows; `samples/entity-catalog.yaml` still
contains all nine and `chunking/entity_stamper.py` still resolves to them
(verified live 2026-08-26: `Child Safety, Department of` -> `agency:cs`,
`Water Infrastructure Finance Authority` -> `agency:wif`). Re-chunking a
document therefore re-derives the split ids and silently undoes part of that
repair. This pass rewrites four columns and re-derives nothing.

Written: `section_path`, `text`, `token_count`, `vector`.
Untouched: everything else, `agency_canonical_ids` and `fund_mentions` in
particular (spec G-T3 verifies it).

The write shape is `identity/relabel.py`'s and `funds/unstamp.py`'s, and the
traps their docstrings name apply here unchanged — `upsert_chunks` is two
LanceDB commits, a matching row count proves nothing, and re-added rows are
invisible to BM25 until `build_fts_index` runs.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol

from chunking.builders._tokens import count_tokens
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.odl_reader import ODLReader
from scripts.diff_section_paths import resolve_extract_dir

# Planning reads these columns only. The `vector` column is 768 float32s on
# every one of 83,016 rows -- projecting it for a scan that only needs to
# decide WHICH rows change would pull ~255 MB off the share for nothing. The
# apply path re-scans a changed document with every column.
PLAN_COLUMNS = ["chunk_id", "doc_id", "text", "section_path", "is_table"]

DEFAULT_BATCH_SIZE = 2000


class ChunkStoreLike(Protocol):
    def scan(self, name: str, columns: list[str], *, where: str | None = ...,
             limit: int | None = ...) -> list[dict[str, Any]]: ...
    def upsert_chunks(self, name: str, rows: Iterable[dict[str, Any]]) -> None: ...
    def build_fts_index(self, name: str) -> None: ...
    def optimize(self, name: str, *, retention: Any = ...) -> None: ...


class EmbedderLike(Protocol):
    def embed_batch(self, texts: list[str], *, input_type: str = ...) -> list[list[float]]: ...


@dataclass(frozen=True)
class RowChange:
    chunk_id: str
    doc_id: str
    old_path: list[str]
    new_path: list[str]
    old_text: str
    new_text: str


@dataclass
class RepairResult:
    changed: int = 0
    scanned: int = 0
    documents_planned: int = 0
    documents_skipped: dict[str, str] = field(default_factory=dict)
    reversal: list[dict[str, Any]] = field(default_factory=list)


def _default_progress(message: str) -> None:
    print(message, flush=True)


def _body(text: str, section_path: list[str]) -> str:
    """Everything after the heading line.

    `table_chunk._build_text` writes the joined section path as line 0 ONLY
    when the path is non-empty, so a chunk stored with an empty path has no
    heading line to strip.
    """
    if not section_path:
        return text
    head, sep, rest = text.partition("\n")
    return rest if sep else ""


def _compose(body: str, section_path: list[str]) -> str:
    """Inverse of `_body`, and it must match `_build_text` exactly.

    An empty path emits NO heading line -- not an empty one. G-T6 asserts
    this pass's output is byte-identical to a real `chunk_doc` run, and a
    stray leading newline is the way that fails.
    """
    return f"{' > '.join(section_path)}\n{body}" if section_path else body


def plan_document(
    doc_id: str, rows: list[Mapping[str, Any]], root: Path
) -> tuple[list[RowChange], str | None]:
    """Which of this document's table rows change, or why it cannot be planned.

    The mapping from stored chunk to extracted table is positional:
    `chunk_doc` emits table chunks FIRST, in `doc.tables` order, so table
    *n* is `{doc_id}-{n:04d}`. That is a hypothesis about what was ingested,
    not a fact about what is on disk now -- so it is GATED, not trusted
    (spec §3.2): the table count must match, and every line of the stored
    text below line 0 must match the rebuilt table's, or the whole document
    is skipped and named.
    """
    found = resolve_extract_dir(doc_id, root)
    if found is None:
        return [], "no cached extractor output"
    directory, extractor = found
    reader = ODLReader() if "opendataloader" in extractor.lower() else MinerUReader()
    try:
        doc = reader.read(directory)
    except (OSError, ValueError) as exc:
        return [], f"extractor output unreadable: {exc}"

    table_rows = sorted(
        (r for r in rows if r.get("is_table")), key=lambda r: str(r["chunk_id"])
    )
    if len(table_rows) != len(doc.tables):
        return [], (
            f"table count mismatch: corpus has {len(table_rows)}, "
            f"extractor output has {len(doc.tables)}"
        )

    from chunking.builders.table_chunk import _build_text  # local: avoids a cycle

    changes: list[RowChange] = []
    for row, table in zip(table_rows, doc.tables):
        old_path = list(row.get("section_path") or [])
        new_path = doc.owner_path(table)
        stored_body = _body(str(row["text"]), old_path)
        rebuilt_body = _body(_build_text(table, new_path), new_path)
        if stored_body != rebuilt_body:
            return [], (
                f"body mismatch on {row['chunk_id']}: the extractor output on "
                "disk no longer matches what was ingested"
            )
        if old_path == new_path:
            continue
        changes.append(
            RowChange(
                chunk_id=str(row["chunk_id"]),
                doc_id=doc_id,
                old_path=old_path,
                new_path=new_path,
                old_text=str(row["text"]),
                new_text=_compose(stored_body, new_path),
            )
        )
    return changes, None
```

- [ ] **Step 4: Add the dry-run entry point**

Append to `chunking/repair_section_paths.py`:

```python
def _plan_corpus(
    store: ChunkStoreLike, root: Path, table: str, progress: Callable[[str], None]
) -> tuple[list[RowChange], RepairResult]:
    rows = store.scan(table, PLAN_COLUMNS)
    by_doc: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_doc.setdefault(str(row["doc_id"]), []).append(row)
    progress(f"scanned {len(rows)} rows across {len(by_doc)} documents")

    result = RepairResult(scanned=len(rows))
    changes: list[RowChange] = []
    for index, (doc_id, doc_rows) in enumerate(sorted(by_doc.items()), start=1):
        doc_changes, skipped = plan_document(doc_id, doc_rows, root)
        if skipped is not None:
            result.documents_skipped[doc_id] = skipped
            continue
        result.documents_planned += 1
        changes.extend(doc_changes)
        if index % 500 == 0:
            progress(f"planned {index}/{len(by_doc)} documents, {len(changes)} rows so far")
    result.changed = len(changes)
    result.reversal = [
        {
            "chunk_id": c.chunk_id,
            "doc_id": c.doc_id,
            "before": {"section_path": c.old_path, "text": c.old_text},
            "after": {"section_path": c.new_path, "text": c.new_text},
        }
        for c in changes
    ]
    return changes, result


def repair_section_paths(
    *,
    store: ChunkStoreLike,
    embedder: EmbedderLike,
    root: Path,
    table: str = "budget_chunks",
    dry_run: bool = True,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock: Any | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> RepairResult:
    """Recompute every table chunk's `section_path`; write back what changed.

    `dry_run=True` (the default) takes no lock, snapshots nothing and writes
    nothing -- the same asymmetry `identity/relabel.py` documents, and what
    lets Task 6 be re-run by hand against the live corpus as often as anyone
    wants before an apply is approved.
    """
    progress = progress or _default_progress
    changes, result = _plan_corpus(store, root, table, progress)
    if dry_run:
        progress(f"DRY RUN: {result.changed} rows would change; nothing written")
        return result
    raise NotImplementedError("apply path lands in Task 5")
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: 7 passed.

- [ ] **Step 6: Prove the body gate can fail**

In `plan_document`, temporarily change `if stored_body != rebuilt_body:` to `if False:`.

Run: `uv run pytest tests/test_repair_section_paths.py::test_plan_refuses_a_document_whose_body_no_longer_matches -v`
Expected: FAIL. Revert and re-run: PASS.

- [ ] **Step 7: Commit**

```bash
git add chunking/repair_section_paths.py tests/test_repair_section_paths.py
git commit -m "chunking: section_path repair — planning and dry run

Positional chunk<->table mapping, gated per document on table count and on
every line of the stored text below line 0. A document that fails the gate
is skipped and named rather than half-written."
```

---

### Task 5: The repair pass — the apply path

**Files:**
- Modify: `chunking/repair_section_paths.py`
- Modify: `tests/test_repair_section_paths.py`

**Interfaces:**
- Consumes: Task 4's `RowChange`, `RepairResult`, `_plan_corpus`.
- Produces: `repair_section_paths(..., dry_run=False)` performing lock → snapshot+verify → write → verify → reversal → FTS rebuild → optimize.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_repair_section_paths.py`:

```python
class _FakeLock:
    def __init__(self):
        self.entered = 0
        self.beats = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False

    def heartbeat(self):
        self.beats += 1


def _full_rows() -> list[dict]:
    base = {
        "page": 1, "bbox": None, "source_anchor": None,
        "agency_canonical_ids": ["agency:ost"], "fund_canonical_id": None,
        "fund_mentions": ["fund:general"], "fiscal_year": 2026,
        "doc_type": "governors-budget", "table_html": "<table></table>",
        "token_count": 7, "publisher": "governor", "vector": [0.0, 0.0, 0.0, 0.0],
    }
    rows = []
    for row in _stored_rows():
        merged = dict(base)
        merged.update(row)
        rows.append(merged)
    return rows


def test_apply_writes_only_the_changed_row(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    lock = _FakeLock()
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: "snap.zip",
        reversal_dir=tmp_path,
    )
    assert result.changed == 1
    assert lock.entered == 1
    written = [r for batch in store.written for r in batch]
    assert [r["chunk_id"] for r in written] == ["doc-a-0001"]


def test_apply_leaves_the_agency_and_fund_columns_byte_identical(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    written = [r for batch in store.written for r in batch][0]
    assert written["agency_canonical_ids"] == ["agency:ost"]
    assert written["fund_mentions"] == ["fund:general"]
    assert written["page"] == 1
    assert written["table_html"] == "<table></table>"


def test_apply_recomputes_the_vector_and_the_token_count(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    written = [r for batch in store.written for r in batch][0]
    # _FakeEmbedder encodes len(text) in the first component.
    assert written["vector"][0] == float(len(written["text"]))
    assert written["token_count"] != 7


def test_apply_rebuilds_the_full_text_index_then_optimizes(root: Path, tmp_path: Path):
    """funds/unstamp.py's lesson: rows re-added by upsert_chunks are
    invisible to BM25 until the FTS index is rebuilt. identity/relabel.py
    does NOT do this and is a known follow-up; this pass must."""
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    assert store.fts_built == ["budget_chunks"]
    assert store.optimized == ["budget_chunks"]


def test_apply_writes_a_reversal_record_carrying_the_old_text(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    files = list(tmp_path.glob("section-path-reversal-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["rows"][0]["before"]["text"] == (
        "Table of Contents\nAcupuncture Examiners, Board of"
    )


def test_apply_refuses_when_the_snapshot_fails(root: Path, tmp_path: Path):
    def _no_snapshot():
        raise RuntimeError("share unreachable")

    store = _FakeStore(_full_rows())
    with pytest.raises(RuntimeError, match="share unreachable"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=_no_snapshot, reversal_dir=tmp_path,
        )
    assert store.written == []


def test_apply_with_nothing_to_do_writes_nothing_and_skips_the_index_rebuild(
    root: Path, tmp_path: Path
):
    rows = _full_rows()
    rows[1]["section_path"] = ["Acupuncture Examiners, Board of"]
    rows[1]["text"] = "Acupuncture Examiners, Board of\nAcupuncture Examiners, Board of"
    store = _FakeStore(rows)
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    assert result.changed == 0
    assert store.written == []
    assert store.fts_built == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_repair_section_paths.py -k apply -v`
Expected: all 7 FAIL with `NotImplementedError: apply path lands in Task 5`.

- [ ] **Step 3: Implement the apply path**

In `chunking/repair_section_paths.py`, add these helpers above `repair_section_paths`:

```python
_ALL_COLUMNS_CACHE: list[str] | None = None


def _all_columns() -> list[str]:
    """Every column, read from the schema rather than typed out — a
    hand-maintained list silently drops a column added later, and a dropped
    column is written as null on every row this pass touches."""
    global _ALL_COLUMNS_CACHE
    if _ALL_COLUMNS_CACHE is None:
        from store.schema import chunk_schema
        _ALL_COLUMNS_CACHE = [f.name for f in chunk_schema(dim=1)]
    return _ALL_COLUMNS_CACHE


def _write_changed_rows(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    embedder: EmbedderLike,
    batch_size: int,
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Fetch each changed document's full rows, rewrite four columns, write.

    Batched because `upsert_chunks` deletes the batch's chunk_ids and then
    adds the replacements as two separate LanceDB commits: batching bounds a
    crash landing between them to one batch instead of the whole corpus.
    """
    from store.chunk_store import sql_str

    by_id = {c.chunk_id: c for c in changes}
    doc_ids = sorted({c.doc_id for c in changes})
    written: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    total_docs = len(doc_ids)

    def flush() -> None:
        if not pending:
            return
        vectors = embedder.embed_batch([r["text"] for r in pending])
        for row, vector in zip(pending, vectors):
            row["vector"] = vector
        store.upsert_chunks(table, pending)
        written.extend(pending)
        pending.clear()

    for index, doc_id in enumerate(doc_ids, start=1):
        rows = store.scan(table, _all_columns(), where=f"doc_id = {sql_str(doc_id)}")
        for row in rows:
            change = by_id.get(str(row.get("chunk_id")))
            if change is None:
                continue
            new_row = dict(row)
            new_row["section_path"] = list(change.new_path)
            new_row["text"] = change.new_text
            new_row["token_count"] = count_tokens(change.new_text)
            pending.append(new_row)
            if len(pending) >= batch_size:
                flush()
        if index % 100 == 0 or index == total_docs:
            progress(f"wrote {len(written)}/{len(changes)} rows ({index}/{total_docs} documents)")
    flush()
    return written


def _verify_nothing_was_lost(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    progress: Callable[[str], None],
) -> None:
    """Re-read every changed row and confirm exactly the four intended
    columns moved. A matching ROW COUNT proves nothing — `upsert_chunks`
    deletes then adds, so a lost column and a lost value both leave the
    count identical (`identity/relabel.py`'s trap 3)."""
    from store.chunk_store import sql_str

    expected = {c.chunk_id: c for c in changes}
    seen = 0
    for doc_id in sorted({c.doc_id for c in changes}):
        rows = store.scan(table, _all_columns(), where=f"doc_id = {sql_str(doc_id)}")
        for row in rows:
            change = expected.get(str(row.get("chunk_id")))
            if change is None:
                continue
            seen += 1
            if list(row.get("section_path") or []) != change.new_path:
                raise RuntimeError(f"{change.chunk_id}: section_path did not land")
            if str(row.get("text")) != change.new_text:
                raise RuntimeError(f"{change.chunk_id}: text did not land")
            if not row.get("vector"):
                raise RuntimeError(f"{change.chunk_id}: vector is empty after the write")
    if seen != len(expected):
        raise RuntimeError(f"verified {seen} rows, expected {len(expected)}")
    progress(f"verified {seen} changed rows in full")


def _atomic_write_json(path: Path, payload: Any) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)
```

Then replace the `raise NotImplementedError(...)` line with:

```python
    if lock is None:
        from ingest.lock import IngestLock
        lock = IngestLock()
    if snapshot_and_verify is None:
        from identity.relabel import _default_snapshot_and_verify
        snapshot_and_verify = _default_snapshot_and_verify
    if reversal_dir is None:
        from store.config import data_dir
        reversal_dir = data_dir()

    with lock:
        lock.heartbeat()
        snapshot = snapshot_and_verify()
        progress(f"snapshot: {snapshot}")
        lock.heartbeat()
        if not changes:
            progress("nothing to change; no write, no index rebuild")
            return result
        _write_changed_rows(store, table, changes, embedder, batch_size, progress)
        lock.heartbeat()
        _verify_nothing_was_lost(store, table, changes, progress)
        # Re-added rows are invisible to BM25 until the index is rebuilt --
        # the ingest contract funds/unstamp.py had to learn the hard way.
        store.build_fts_index(table)
        store.optimize(table)
        progress("full-text index rebuilt and table optimized")

    stamp = _reversal_stamp()
    path = Path(reversal_dir) / f"section-path-reversal-{table}-{stamp}.json"
    _atomic_write_json(path, {"table": table, "snapshot": snapshot, "rows": result.reversal})
    progress(f"reversal record: {path}")
    return result
```

Add near `_default_progress`:

```python
def _reversal_stamp() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: 14 passed.

If `sql_str` is not importable from `store.chunk_store`, run
`grep -rn "def sql_str" --include='*.py' .` and import it from wherever it
actually lives — do not inline a quoting expression.

- [ ] **Step 5: Prove the FTS guard and the agency guard can fail**

Comment out `store.build_fts_index(table)`; run
`uv run pytest tests/test_repair_section_paths.py -k rebuilds -v` → FAIL. Restore.

Add `new_row["agency_canonical_ids"] = []` inside `_write_changed_rows`; run
`uv run pytest tests/test_repair_section_paths.py -k byte_identical -v` → FAIL. Remove.

Re-run the file: 14 passed.

- [ ] **Step 6: Commit**

```bash
git add chunking/repair_section_paths.py tests/test_repair_section_paths.py
git commit -m "chunking: section_path repair — the apply path

lock -> snapshot+verify -> batched write -> full re-read verification ->
FTS rebuild -> optimize -> reversal record. Four columns written; agency
and fund columns asserted byte-identical."
```

---

### Task 6: The CLI, and the dry run against the live corpus

**Files:**
- Modify: `chunking/repair_section_paths.py` (add `main`)
- Modify: `tests/test_repair_section_paths.py`
- Create: `docs/superpowers/investigations/2026-08-26-section-path-repair-dry-run.md`

**Interfaces:**
- Consumes: Task 5's `repair_section_paths`.
- Produces: `main(argv: list[str] | None = None) -> int`, run as `uv run python -m chunking.repair_section_paths`.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_repair_section_paths.py`:

```python
def test_the_cli_defaults_to_a_dry_run(monkeypatch, root: Path):
    """An apply must be typed, never defaulted into. This pass rewrites
    ~10,200 rows of the live corpus."""
    from chunking import repair_section_paths as mod

    seen: dict[str, object] = {}

    def _fake(**kwargs):
        seen.update(kwargs)
        return mod.RepairResult()

    monkeypatch.setattr(mod, "repair_section_paths", _fake)
    monkeypatch.setattr(mod, "_load_live_store_and_embedder", lambda: (None, None, root))
    assert mod.main([]) == 0
    assert seen["dry_run"] is True
    assert mod.main(["--apply"]) == 0
    assert seen["dry_run"] is False
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest tests/test_repair_section_paths.py::test_the_cli_defaults_to_a_dry_run -v`
Expected: FAIL — `AttributeError: module ... has no attribute 'main'`.

- [ ] **Step 3: Add the CLI**

Append to `chunking/repair_section_paths.py`:

```python
def _load_live_store_and_embedder() -> tuple[ChunkStoreLike, EmbedderLike, Path]:
    """The real store, the real embedder and the real data dir.

    `resolve_data_dir()` rather than `data_dir()`: the latter mkdirs, and a
    check that manufactures the folder it is checking for can only report
    "fine" (the Windows-beta lesson, spec principle 3 of that batch).
    """
    from retrieval.pipeline import _get_embedder
    from store.chunk_store import ChunkStore
    from store.config import resolve_data_dir

    embedder = _get_embedder()
    root = resolve_data_dir()
    return ChunkStore(root=root, dim=embedder.dim), embedder, root


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the corpus (default is a dry run)")
    parser.add_argument("--table", default="budget_chunks")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--report", type=Path, default=None,
                        help="write the full plan as JSON")
    args = parser.parse_args(argv)

    store, embedder, root = _load_live_store_and_embedder()
    result = repair_section_paths(
        store=store, embedder=embedder, root=root, table=args.table,
        dry_run=not args.apply, batch_size=args.batch_size,
    )
    print(f"scanned            {result.scanned}")
    print(f"documents planned  {result.documents_planned}")
    print(f"documents skipped  {len(result.documents_skipped)}")
    print(f"rows changed       {result.changed}")
    reasons: dict[str, int] = {}
    for reason in result.documents_skipped.values():
        reasons[reason.split(":")[0]] = reasons.get(reason.split(":")[0], 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  skipped: {count:5d}  {reason}")
    if args.report:
        _atomic_write_json(args.report, {
            "changed": result.changed,
            "scanned": result.scanned,
            "documents_planned": result.documents_planned,
            "documents_skipped": result.documents_skipped,
            "rows": result.reversal,
        })
        print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole test file plus the full suite**

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: 15 passed.

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: no new failures.

- [ ] **Step 5: Dry-run against the live corpus**

```bash
cd ~/ask-the-budget-az-worktrees/table-section-path
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
  uv run python -m chunking.repair_section_paths \
  --report /tmp/section-path-plan.json 2>&1 | tail -30
```

**Expected, and these are predictions from the spec's §3.5 — a materially different number means the model of the defect is wrong, so STOP and report rather than applying:**

- `rows changed` ≈ **10,200** (accept 8,500–12,000; anything outside that is a stop)
- `documents skipped` ≈ **400** (the migration-era entries with no cached extractor output), plus however many fail the body gate
- the dominant skip reason is `no cached extractor output`

- [ ] **Step 6: Read the skip reasons, do not just count them**

```bash
uv run python -c "
import json,collections
p=json.load(open('/tmp/section-path-plan.json'))
c=collections.Counter(v.split(':')[0] for v in p['documents_skipped'].values())
print(c)
for d,r in list(p['documents_skipped'].items())[:10]: print(d,'->',r)
"
```

**A large `body mismatch` count is a finding, not noise.** It means the
extractor output on the share no longer corresponds to what was ingested for
those documents, and they simply cannot be repaired by this pass. Record the
count and a few examples; do not loosen the gate to absorb them.

- [ ] **Step 7: Write the dry-run record**

Create `docs/superpowers/investigations/2026-08-26-section-path-repair-dry-run.md` containing: the exact command, the four headline counts, the skip-reason table, five example changes copied from the report (page, old path, new path), and the per-document numbers for `governor-governors-budget-fy2026`, `agao-afr-fy2024` and `agao-afr-fy2021`. State plainly whether each matched the spec's prediction.

- [ ] **Step 8: Commit**

```bash
git add chunking/repair_section_paths.py tests/test_repair_section_paths.py \
        docs/superpowers/investigations/2026-08-26-section-path-repair-dry-run.md
git commit -m "chunking: section_path repair CLI + the live dry-run record

Dry run is the default; --apply must be typed. Dry-run counts recorded
against the spec's predictions."
```

---

### Task 7: Gates, the apply run, and STATUS

**Files:**
- Modify: `STATUS.md`
- Modify: `docs/superpowers/specs/2026-08-26-table-section-path-design.md` (status line only)
- Create: `eval/results/<UTC>-<sha>.{json,md}` × 2 (control + post-write)

**Interfaces:**
- Consumes: everything above.

- [ ] **Step 1: G-T6 — the repair must equal a re-chunk**

The gate the 2026-08-16 attempt did not have. For one document of each
shape, run the NEW `chunk_doc` end-to-end over cached extractor output and
compare against what the repair PLANS to write:

```bash
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
uv run python -c "
import json, sys
from pathlib import Path
from chunking.builder import chunk_doc
from chunking.builders.table_chunk import DocMeta
from scripts.diff_section_paths import resolve_extract_dir
from store.config import resolve_data_dir

root = resolve_data_dir()
plan = {r['chunk_id']: r for r in json.load(open('/tmp/section-path-plan.json'))['rows']}
docs = json.loads((root/'documents.json').read_text())
bad = 0
for doc_id in ['jlbc-approps-fy2027-deq', 'governor-governors-budget-fy2026', 'agao-afr-fy2024']:
    d, ex = resolve_extract_dir(doc_id, root)
    meta = docs[doc_id]
    # fiscal_year is a required int on DocMeta; a sidecar entry can carry
    # null, and it is not read by anything this gate compares.
    chunks = chunk_doc(extractor_output_path=d, doc_meta=DocMeta(
        doc_id=doc_id, publisher=meta['publisher'], doc_type=meta['doc_type'],
        fiscal_year=meta.get('fiscal_year') or 0,
        extractor='opendataloader' if 'opendataloader' in ex else 'mineru'))
    for c in chunks:
        if not c.is_table: continue
        want = plan.get(c.chunk_id)
        if want is None: continue
        if list(c.section_path) != want['after']['section_path'] or c.text != want['after']['text']:
            bad += 1
            if bad <= 3:
                print('MISMATCH', c.chunk_id)
                print('  chunk_doc:', c.section_path, repr(c.text[:70]))
                print('  repair   :', want['after']['section_path'], repr(want['after']['text'][:70]))
    print(doc_id, 'checked')
print('mismatches:', bad)
sys.exit(1 if bad else 0)
"
```

Expected: `mismatches: 0`. **A non-zero count blocks the apply** — the
repair and a future re-ingest would disagree, so the next time anyone
re-uploads one of these documents it silently reverts.

- [ ] **Step 2: G-T2 control — run the eval on UNMODIFIED master, now**

```bash
cd /home/destin/YouCoded/Projects/ask-the-budget-az-dev
git stash list && git status --porcelain   # must be clean
uv run python -m eval.run_eval 2>&1 | tail -20
```

Record recall@5 / @15 / @20 / refusal precision and the result filename.
**This is the control and it must be run within the hour of the post-write
run, on this machine** — a recorded number from an earlier day is not a
control (CLAUDE.md).

- [ ] **Step 3: Apply**

```bash
cd ~/ask-the-budget-az-worktrees/table-section-path
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
  uv run python -m chunking.repair_section_paths --apply 2>&1 | tee /tmp/section-path-apply.log
```

Confirm from the log: a snapshot path was printed, `rows changed` equals the
dry run's count **exactly** (G-T5), `verified N changed rows in full`
printed with N equal to that count, `full-text index rebuilt`, and a
reversal record path.

- [ ] **Step 4: G-T3 — nothing but the four columns moved**

```bash
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
uv run python -c "
import json
from store.chunk_store import ChunkStore
from store.config import resolve_data_dir
rev = json.load(open(sorted(__import__('pathlib').Path(resolve_data_dir()).glob('section-path-reversal-*.json'))[-1]))
ids = {r['chunk_id'] for r in rev['rows']}
s = ChunkStore(root=resolve_data_dir())
rows = s.scan('budget_chunks', ['chunk_id','section_path','text','agency_canonical_ids','fund_mentions'])
by = {r['chunk_id']: r for r in rows}
missing = [i for i in ids if i not in by]
wrong = [r['chunk_id'] for r in rev['rows'] if by.get(r['chunk_id'],{}).get('text') != r['after']['text']]
print('rows in reversal:', len(ids), 'missing from corpus:', len(missing), 'text not landed:', len(wrong))
print('total chunks:', len(rows))
"
```

Expected: `missing: 0`, `text not landed: 0`, and the total chunk count
unchanged from before the apply (83,016 at the time of writing — read it
from the dry run's `scanned` figure).

- [ ] **Step 5: G-T2 post-write — re-run the eval**

```bash
cd /home/destin/YouCoded/Projects/ask-the-budget-az-dev
uv run python -m eval.run_eval 2>&1 | tail -20
```

**The gate is per-query status, not the aggregate.** Compare the two result
JSONs query by query:

```bash
uv run python -c "
import json,sys
a=json.load(open('eval/results/<CONTROL>.json')); b=json.load(open('eval/results/<AFTER>.json'))
qa={q['query_id']:q for q in a['per_query']}; qb={q['query_id']:q for q in b['per_query']}
moved=[k for k in qa if qa[k].get('hit_rank') != qb[k].get('hit_rank')]
flipped=[k for k in qa if bool(qa[k].get('hit_rank')) != bool(qb[k].get('hit_rank'))]
print('rank moved:', len(moved), moved[:10]); print('STATUS FLIPPED:', flipped)
"
```

Expected: `STATUS FLIPPED: []`. Rank movement is reported, not failed.

**If a query flipped, the first place to look is spec §D2** — the ~3,400
JLBC per-agency summary tables that lost a keyword from line 0 — not the
relabelled majority.

- [ ] **Step 6: G-T4 — read the documents, do not count them**

```bash
JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data \
uv run python -c "
from store.chunk_store import ChunkStore
from store.config import resolve_data_dir
s=ChunkStore(root=resolve_data_dir())
for d in ['governor-governors-budget-fy2026','agao-afr-fy2024','agao-afr-fy2021']:
    rows=s.scan('budget_chunks',['chunk_id','section_path','page'],where=f\\\"doc_id = '{d}'\\\")
    toc=[r for r in rows if 'Table of Contents' in (r['section_path'] or [])]
    th=[r for r in rows if any('thousand' in x.lower() for x in (r['section_path'] or []))]
    print(d,'chunks',len(rows),'TOC-labelled',len(toc),'units-claiming',len(th))
    for r in rows[:4]: print('   p',r['page'],r['section_path'])
"
```

Expected: `governor-governors-budget-fy2026` TOC-labelled **0**;
`agao-afr-fy2024` units-claiming **51** — the spec's stated prediction. **A
different number means the model of the defect was wrong**; record it and
say so rather than adjusting the spec after the fact.

Then read a handful of the printed paths by eye and confirm they name the
agency the page is about.

- [ ] **Step 7: Update STATUS.md**

Add a row to the phase-summary table and a section recording: the measured
before/after (median 93 pages; 1,079 → 0 TOC labels; ≈10,200 rows), the two
eval runs with their filenames and the per-query verdict, the skip counts
and their reasons, the reversal record path and snapshot filename, and — as
their own bullets, because they are open and will otherwise be read as
closed:

- **51 passages in `agao-afr-fy2024` still claim "expressed in thousands"
  over whole-dollar figures** (spec §5.1) — Destin's call, down from 121.
- **Garbage strings are still accepted as headings** (spec §5.2).
- **🔴 The catalog still holds the nine merged-away agency ids and the
  stamper still mints them** (spec §5.3) — every upload re-splits those
  agencies; the corpus is clean only because nothing has been ingested since
  2026-08-16.
- **Nobody has looked at this in a browser.** The breadcrumb in
  `RetrieveView` and on a fiscal note is unwitnessed; jsdom applies no
  stylesheet.

- [ ] **Step 8: Full suite, then merge**

```bash
uv run pytest -q 2>&1 | tail -3
cd webapp && npx tsc -b && npm run build && npx vitest run 2>&1 | tail -3
```

Expected: no new failures. The webapp is untouched by this plan, so its
counts must be unchanged.

```bash
cd /home/destin/YouCoded/Projects/ask-the-budget-az-dev
git fetch origin && git log --oneline -1 origin/master   # check master again, now
git merge --no-ff table-section-path
git push origin master
git worktree remove ~/ask-the-budget-az-worktrees/table-section-path
git branch -d table-section-path
```

---

## Self-Review

**Spec coverage.** D1 → Task 2. D2 → Task 2 Step 2 (`test_a_table_under_no_heading_gets_an_empty_path_and_no_heading_line`) and Task 4. D3 → nothing built for §5, and §5.1–5.3 are carried into STATUS in Task 7 Step 7. §3.1 surgical-not-re-ingest → Task 4's module docstring and Task 5's apply path. §3.2 mapping gate → Task 4 Steps 3, 6. §3.3 four columns, and to-blank REMOVING line 0 → Task 4 `_compose`, Task 5 `test_apply_leaves_the_agency_and_fund_columns_byte_identical`. §3.4 coverage → Task 6 Step 6. §3.5 counts → Task 6 Step 5 predictions. §4 rejected alternatives → nothing to build. G-T1 → Task 3. G-T2 → Task 7 Steps 2, 5. G-T3 → Task 7 Step 4. G-T4 → Task 7 Step 6. G-T5 → Task 7 Step 3. G-T6 → Task 3 (harness) + Task 7 Step 1 (the gate).

**Placeholder scan.** No TBD/TODO. Every code step carries runnable code. The two `<CONTROL>` / `<AFTER>` tokens in Task 7 Step 5 are filenames produced by Steps 2 and 5 and cannot be known in advance; the step says where they come from.

**Type consistency.** `resolve_extract_dir(doc_id, root) -> tuple[Path, str] | None` is defined in Task 3 and imported unchanged in Task 4. `RowChange` fields are used identically in Tasks 4 and 5. `RepairResult.documents_skipped` is `dict[str, str]` everywhere. `owner_path(block) -> list[str]` is defined in Task 1 and consumed in Tasks 2, 3, 4.

**One known risk in this plan's own code, stated rather than hidden:** Task 4's `plan_document` imports `_build_text` from `chunking.builders.table_chunk` — a private function. If Task 2's implementer renames or inlines it, Task 4 breaks. It is imported rather than reimplemented on purpose: a second copy of the text format is exactly how the repair and a re-chunk would silently diverge (G-T6). If it must move, make it public rather than duplicating it.
