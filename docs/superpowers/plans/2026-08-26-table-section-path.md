# Table Section Paths Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A table chunk's `section_path` becomes the heading it physically sits under, instead of the first heading anywhere in the document containing one of its cell strings — and the ~10,200 corpus rows already carrying the wrong answer are repaired in place.

**Architecture:** The readers' `_build_outline` already files every table into the `body_blocks` of the innermost open heading; that list is the haystack the current text search scans. Task 1 exposes it as a lookup (`ExtractedDocument.owner_path`), Task 2 makes the table builder use it and deletes the search, Task 3 pins that the two chunk builders agree on a REAL two-page slice of the Governor's Budget and adds the one read-side lookup the repair needs (`ingest/extract_dirs.py`), Tasks 4–6 build a surgical corpus repair modelled on `identity/relabel.py` / `funds/unstamp.py` and end at a **go/no-go stop for Destin**, and Task 7 runs the write behind the spec's gates.

> **Revised 2026-08-26 after review against the code and the live data.** Five of the first draft's claims were wrong (fixture copied the cover page instead of the contents page; folder precedence read the wrong AFR; eval field names that do not exist; three `outline_path` tests unlisted; a half-copy of the old rule). Also added: the fiscal-note table, the untouched-row half of G-T3, the two unrepairable documents, and the checkpoint. The half-copied old rule and its script are gone — the dry-run report answers the same question from the stored rows.

**Tech Stack:** Python 3.12, `uv`, pytest, LanceDB (`store/chunk_store.py`), local ONNX embedder (`retrieval/local_embedder.py`), pydantic models in `chunking/types.py`.

**Spec:** `docs/superpowers/specs/2026-08-26-table-section-path-design.md`. Read D1, D2, §3 and §6 before starting. Where this plan's code and the spec's prose disagree, **the spec wins and the deviation gets recorded** — this repo has recorded plan-code defects on seven consecutive features.

## Global Constraints

- **`chunk_id` must never change.** `chunk_id = f"{doc_id}-{idx:04d}"` and table chunks are emitted first in `doc.tables` order. Nothing in this plan may reorder tables, add a table, or drop one. Eval ground truth, saved transcripts and citation annotations all pin chunk ids.
- **The repair writes exactly four columns:** `section_path`, `text`, `token_count`, `vector`. Every other column is passed through by value. `agency_canonical_ids` and `fund_mentions` in particular must be byte-identical before and after (spec G-T3).
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX weights** (CLAUDE.md). Reader fixtures are committed JSON under `tests/fixtures/`; the corpus at `data/insight-data/` is gitignored and absent from a fresh clone, so **no test may read it**.
- **A repair pass writes the corpus.** It follows the shape `identity/relabel.py` and `funds/unstamp.py` established: dry run takes no lock and writes nothing; apply is lock → snapshot+verify → scan → compute → batched write → verify → reversal record → **`build_fts_index` + `optimize`**. The FTS rebuild is not optional (`funds/unstamp.py` learned it: re-added rows are invisible to BM25 until then).
- **Run the eval after this change.** `retrieval/` is untouched but `chunking/` is not, and `section_path` is line 0 of embedded text. `uv run python -m eval.run_eval` (~60s, needs `JLBC_DATA_DIR`), as a CONTROL on unmodified code immediately before the write and again after. Commit both result files.
- **Two tables, not one.** Fiscal notes are chunked by the same `chunk_doc` (tables first) into a SEPARATE LanceDB table, `fiscal_note_chunks` (`ingest/worker.py::CORPUS_TABLES`). Spec §3.5 counts ≈351 fiscal-note rows. Every dry run, apply and G-T3 check in this plan runs against **both** tables, the way `funds/unstamp.py` does.
- **The apply holds the ingest lock for a long time.** Snapshotting the corpus takes minutes, and re-embedding ≈10,200 rows on the local CPU model is on the order of 30–60 minutes on this machine. Nobody in the office can upload while it runs. Say so before starting, and run it when nothing else is writing. (`IngestLock.acquire()` starts its own heartbeat thread — the explicit `lock.heartbeat()` calls in Task 5 are belt-and-braces between phases, not what keeps the lock alive.)
- **Which extractor output to read comes from `documents.json`, never from a folder precedence.** `agao-afr-fy2024` holds BOTH `mineru/` and `mineru-ocr/` output; the corpus holds the `mineru` reading and the sidecar's `extraction.method` says so. Task 3's `resolve_extract_dir` reads the sidecar; a guess by folder name reads the wrong document.
- **Scratch files go in the session's scratchpad directory, never `/tmp`.** `$SCRATCH` below means that directory.
- **There is a STOP in this plan.** Task 6 ends with a go/no-go checkpoint for Destin. Task 7 (the write) does not start until he says go.
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

Replace `memo[id(b)] = here` with `memo[id(b)] = list(ancestors)` (dropping the node's own text), run
`uv run pytest tests/test_extracted_document_owner_path.py -v`, and confirm **4 tests fail**. Revert the single line by hand (the file carries this task's own uncommitted edits, so `git checkout` would discard them) and re-run to confirm 6 passed.

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
- Modify: `tests/test_odl_reader.py` (delete the three `test_odl_reader_outline_path_*` specs at ~lines 92–117)
- Modify: `tests/test_table_chunk.py`
- Test: `tests/test_table_chunk.py` (new cases)

**Interfaces:**
- Consumes: `ExtractedDocument.owner_path(block) -> list[str]` from Task 1.
- Produces: `build_table_chunk(table, doc, doc_meta, *, chunk_index, section_path=None) -> Chunk` — unchanged signature; when `section_path is None` it now resolves via `doc.owner_path(table)`.

- [ ] **Step 1: Confirm `outline_path` has exactly one production caller before deleting it**

Run: `grep -rn "outline_path" --include='*.py' . | grep -v __pycache__`

Expected: hits in `chunking/builders/table_chunk.py` (the caller), `chunking/readers/types.py` (the definition), three comments (`narrative_chunk.py:27`, `mineru_reader.py`, `odl_reader.py`), and **four tests** — one in `tests/test_mineru_reader.py` (line ~86) and three in `tests/test_odl_reader.py` (lines ~92, ~108, ~115; verified 2026-08-26). **If a production caller outside `table_chunk.py` appears, stop and report it** — the spec's D1 rests on there being none.

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

Delete `test_mineru_reader_outline_path_finds_table_content` from `tests/test_mineru_reader.py` (around line 86) and the three `test_odl_reader_outline_path_*` specs from `tests/test_odl_reader.py` (around lines 92–117). They pin the method being deleted, not any behaviour a chunk depends on.

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
        (`uv run python -m chunking.repair_section_paths --doc <doc_id>`
        is a dry run that prints old vs new per table).
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
        tests/test_table_chunk.py tests/test_mineru_reader.py tests/test_odl_reader.py
git commit -m "chunking: a table is labelled with the heading it sits under

_resolve_section_path searched the whole document for the table's own cell
text and took the earliest shallowest match. Measured on the live corpus:
median 93 pages between a table and the heading it was given, and 1,079 of
1,246 tables in the FY2026 Governor's Budget filed under 'Table of
Contents' because the contents page names every agency in the book.

outline_path had exactly one production caller and is deleted with it."
```

---

### Task 3: Prove it on a real document — the cross-producer guard, and the read-side folder lookup

**Files:**
- Create: `ingest/extract_dirs.py`
- Create: `tests/test_extract_dirs.py`
- Create: `tests/fixtures/odl-gov-toc-slice/page-2.json`, `tests/fixtures/odl-gov-toc-slice/page-10.json`
- Create: `tests/test_section_path_producers_agree.py`
- Modify: `tests/fixtures/README.md`

**Interfaces:**
- Consumes: Task 2's changed builder.
- Produces: `ingest.extract_dirs.resolve_extract_dir(doc_id: str, root: Path, *, method: str | None = None) -> tuple[Path, str] | None` returning `(directory, extractor_name)`. **Task 4 imports it from here** — do not duplicate it.

> **What changed from the first draft, and why.** The draft had a `scripts/diff_section_paths.py` that re-implemented the OLD text-search rule to print old-vs-new. It was half a copy — the real `_resolve_section_path` has a nearest-preceding-heading fallback the copy omitted — so its numbers would have disagreed with the spec's and tripped a false stop. It is gone. The stored corpus row IS the old answer, so Task 6's dry run (`--doc <id>`) prints the same old-vs-new from real data with no second copy of anything. The one piece worth keeping, "where does this document's extractor output live", moves next to the code that already writes that layout.

- [ ] **Step 1: Write the failing tests for the folder lookup**

Create `tests/test_extract_dirs.py`:

```python
"""ingest.extract_dirs.resolve_extract_dir — the READ side of the layout
`ingest/worker.py::_extract_dir` / `_legacy_extract_dir` write.

The sidecar's `extraction.method` decides the folder. It has to: on the live
share `agao-afr-fy2024` holds both `mineru/` and `mineru-ocr/` (the
2026-08-13 forced-fallback experiment wrote the OCR one) and the corpus
holds the MinerU reading. A rule that picks by folder name reads the wrong
document and the repair's body gate then skips it -- the exact document
spec G-T4's prediction is about.
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest.extract_dirs import resolve_extract_dir


def _pages(directory: Path, extractor: str, *pages: int) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for p in pages:
        (directory / f"page-{p}.json").write_text(
            json.dumps({"extractor": extractor, "page": p, "blocks": []}), encoding="utf-8"
        )


def test_legacy_root_layout_when_no_method_is_recorded(tmp_path: Path):
    _pages(tmp_path / "extractor-output" / "doc-a", "opendataloader-2.4.1", 1, 2)
    assert resolve_extract_dir("doc-a", tmp_path) == (
        tmp_path / "extractor-output" / "doc-a", "opendataloader-2.4.1"
    )


def test_the_sidecar_method_picks_the_folder_even_when_the_root_has_pages(tmp_path: Path):
    base = tmp_path / "extractor-output" / "doc-a"
    _pages(base, "opendataloader-2.4.1", 1)            # an older reading
    _pages(base / "mineru", "mineru-3.1.6", 1)
    _pages(base / "mineru-ocr", "mineru-3.1.6", 1)     # a rung that lost
    assert resolve_extract_dir("doc-a", tmp_path, method="mineru") == (base / "mineru", "mineru-3.1.6")


def test_a_recorded_method_with_no_output_on_disk_is_none_not_a_guess(tmp_path: Path):
    base = tmp_path / "extractor-output" / "doc-a"
    _pages(base / "mineru-ocr", "mineru-3.1.6", 1)
    assert resolve_extract_dir("doc-a", tmp_path, method="mineru") is None


def test_missing_document_is_none(tmp_path: Path):
    assert resolve_extract_dir("nope", tmp_path) is None


def test_the_extractor_comes_from_the_page_file_not_the_folder_name(tmp_path: Path):
    base = tmp_path / "extractor-output" / "doc-a"
    _pages(base / "mineru", "mineru-3.4.4", 1)
    (base / "manifest.json").write_text(json.dumps({"extractor": "opendataloader"}), encoding="utf-8")
    assert resolve_extract_dir("doc-a", tmp_path, method="mineru")[1] == "mineru-3.4.4"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_extract_dirs.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'ingest.extract_dirs'`.

- [ ] **Step 3: Write `ingest/extract_dirs.py`**

```python
"""Where a document's cached extractor output lives, for READ-side tools.

The write side already knows this layout: `ingest/worker.py::_extract_dir`
writes `<root>/extractor-output/<doc_id>/<method>/page-N.json` per rung, and
`_legacy_extract_dir` re-claims the pre-rung `<doc_id>/page-N.json` shape.
Both are keyed on a job record, which a corpus repair does not have. This is
the same rule keyed on what a repair DOES have: the doc_id and the sidecar's
`extraction.method`.

WHY the method comes from `documents.json` and never from a folder
precedence: `agao-afr-fy2024` holds BOTH `mineru/` and `mineru-ocr/` -- the
2026-08-13 forced-fallback experiment wrote the OCR reading, and the corpus
holds the MinerU one (sidecar `extraction.method == "mineru"`). Any rule that
picks by folder name reads the wrong document; the repair's body gate then
skips it, and that is the one document spec G-T4's prediction is about.
"""
from __future__ import annotations

import json
from pathlib import Path


def resolve_extract_dir(
    doc_id: str, root: Path, *, method: str | None = None
) -> tuple[Path, str] | None:
    """`(directory, extractor)` for `doc_id`, or None when nothing usable is cached.

    `method` is the sidecar's `extraction.method` when the document has an
    extraction record (141 of 7,574 on 2026-08-26 -- everything ingested
    since Plan B). Documents without one live in the un-suffixed legacy
    directory. A recorded method whose folder is missing returns None
    rather than falling back to another folder: "the reading the corpus
    holds is not on disk" is a finding, and guessing would hide it.

    The extractor NAME is read from the first page file's own `extractor`
    field, never from `manifest.json` -- thousands of documents have no
    manifest, and `agao-afr-fy2024`'s says `opendataloader` while the
    reading in the corpus is MinerU's.
    """
    base = root / "extractor-output" / doc_id
    if not base.is_dir():
        return None
    directory = base / method if method else base
    first = next(iter(sorted(directory.glob("page-*.json"))), None)
    if first is None:
        return None
    try:
        extractor = str(json.loads(first.read_text(encoding="utf-8")).get("extractor", ""))
    except (OSError, ValueError):
        return None
    return directory, extractor
```

Run: `uv run pytest tests/test_extract_dirs.py -v` → 5 passed.

- [ ] **Step 4: Build the committed fixture from the real slice — pages 2 and 10, NOT page 1**

The fixture must be REAL, not synthetic — this defect only appears when a
contents page's body genuinely names a later agency, which is easy to get
wrong by hand. **Read before copying (verified 2026-08-26):** page 1 of
`governor-governors-budget-fy2026` is the cover (no heading, no table).
**The `Table of Contents` heading is on page 2**, followed by ~110
paragraphs naming every agency — the trap. Page 10 carries its own
`Acupuncture Examiners, Board of` heading and, under it, the agency's
budget-summary table. The two pages are 35 KB + 17 KB; no trimming.

```bash
DATA=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data
SRC=$DATA/extractor-output/governor-governors-budget-fy2026
mkdir -p tests/fixtures/odl-gov-toc-slice
cp $SRC/page-2.json  tests/fixtures/odl-gov-toc-slice/page-2.json
cp $SRC/page-10.json tests/fixtures/odl-gov-toc-slice/page-10.json
ls -la tests/fixtures/odl-gov-toc-slice/
grep -c '"Table of Contents"' tests/fixtures/odl-gov-toc-slice/page-2.json   # must be >= 1
grep -c 'Acupuncture Examiners, Board of' tests/fixtures/odl-gov-toc-slice/page-2.json tests/fixtures/odl-gov-toc-slice/page-10.json   # both >= 1
```

Add a row to the table in `tests/fixtures/README.md`:

```
| `odl-gov-toc-slice/` | OpenDataLoader-PDF per-page output, pages 2 + 10 of `governor-governors-budget-fy2026` (a public document) | The real contents-page-captures-every-table defect (spec 2026-08-26): page 2 is the `Table of Contents` heading plus every agency name as paragraphs; page 10 is one agency's heading and its budget table. Two files, read as a directory. Untrimmed. |
```

- [ ] **Step 5: Write the cross-producer guard**

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
from chunking.readers.types import Paragraph

FIXTURE = Path(__file__).parent / "fixtures" / "odl-gov-toc-slice"
TRAP = "Acupuncture Examiners, Board of"


def _meta() -> DocMeta:
    return DocMeta(
        doc_id="governor-governors-budget-fy2026",
        publisher="governor",
        doc_type="governors-budget",
        fiscal_year=2026,
        extractor="opendataloader",
    )


def test_the_fixture_really_contains_the_trap():
    """The first draft of this plan copied the COVER page instead of the
    contents page, and every test below would have passed against it while
    proving nothing. This spec fails if the fixture is ever re-copied wrong."""
    doc = ODLReader().read(FIXTURE)
    toc = [n for n in doc.outline if n.text == "Table of Contents"]
    assert len(toc) == 1, "page-2.json must carry the Table of Contents heading"
    body = " ".join(b.text for b in toc[0].body_blocks if isinstance(b, Paragraph))
    assert TRAP in body, "the contents page must name the agency whose table is on page 10"
    late_tables = [t for t in doc.tables if (t.pages[0] if t.pages else t.page) >= 10]
    assert late_tables, "page-10.json must carry the agency's table"


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
    """The defect, pinned against the real slice it was measured on: the
    page-10 table must be filed under its own page-10 heading, not under
    the page-2 contents node whose body names the same agency."""
    doc = ODLReader().read(FIXTURE)
    late = [t for t in doc.tables if (t.pages[0] if t.pages else t.page) >= 10]
    assert late, "fixture must contain a table from page 10"
    for table in late:
        chunk = build_table_chunk(table, doc, _meta(), chunk_index=0)
        assert "Table of Contents" not in chunk.section_path
        assert chunk.section_path == [TRAP]
```

- [ ] **Step 6: Run it**

Run: `uv run pytest tests/test_section_path_producers_agree.py -v`
Expected: 4 passed.

If `test_the_fixture_really_contains_the_trap` fails, the wrong pages were copied — re-read Step 4; do not edit the assertion.

- [ ] **Step 7: Prove the guard can fail**

In `chunking/builders/table_chunk.py`, temporarily change
`section_path = doc.owner_path(table)` to `section_path = ["Table of Contents"]`.

Run: `uv run pytest tests/test_section_path_producers_agree.py -v`
Expected: `test_every_table_chunk_agrees_with_the_owner_lookup` and
`test_the_contents_page_does_not_capture_the_agency_table` FAIL; the
fixture-precondition spec still passes (it reads the fixture, not the builder).

Revert the line by hand and re-run: 4 passed.

- [ ] **Step 8: Commit**

```bash
git add ingest/extract_dirs.py tests/test_extract_dirs.py \
        tests/test_section_path_producers_agree.py \
        tests/fixtures/odl-gov-toc-slice tests/fixtures/README.md
git commit -m "chunking: cross-producer guard on the real Governor's-budget contents slice

G-T1: table and narrative chunks must agree about which section a page is
in. Every existing test asked whether one chunk's label was right; nothing
asked whether our two labellers agreed, which is how the defect survived.
The fixture is pages 2 + 10 (the contents heading is on page 2, not 1) and
a spec pins that the trap is really in it.

ingest/extract_dirs.py: the read-side twin of worker._extract_dir, keyed on
the sidecar's extraction.method so the AFR that holds two readings is read
from the one the corpus holds."
```

---

### Task 4: The repair pass — planning and the dry run

**Files:**
- Create: `chunking/repair_section_paths.py`
- Test: `tests/test_repair_section_paths.py` (create)

**Interfaces:**
- Consumes: `ingest.extract_dirs.resolve_extract_dir`, `ExtractedDocument.owner_path`, `chunking.builders._tokens.count_tokens`, `store.chunk_store.ChunkStore.scan/upsert_chunks`.
- Produces:
  - `PLAN_COLUMNS: list[str]`
  - `@dataclass(frozen=True) RowChange` with fields `chunk_id: str`, `doc_id: str`, `old_path: list[str]`, `new_path: list[str]`, `old_text: str`, `new_text: str`
  - `@dataclass RepairResult` with fields `changed: int`, `scanned: int`, `documents_planned: int`, `documents_skipped: dict[str, str]`, `per_document: dict[str, dict[str, int]]` (`tables` / `changed` / `relabelled` / `to_blank`), `reversal: list[dict]`
  - `plan_document(doc_id, rows, root, *, method=None) -> tuple[list[RowChange], str | None]` — changes, and a skip reason when the document cannot be planned
  - `repair_section_paths(*, store, embedder, root, table="budget_chunks", dry_run=True, only=None, ...) -> RepairResult` — `only` restricts planning to a set of doc_ids (the CLI's `--doc`)

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


def test_plan_reads_the_rung_folder_the_sidecar_names(root: Path):
    """`method` selects `<doc_id>/<method>/`; the legacy root output (an
    OLDER reading, here deliberately different) must not be read."""
    sub = root / "extractor-output" / "doc-a" / "mineru"
    sub.mkdir()
    for name in ("page-1.json", "page-9.json"):
        (root / "extractor-output" / "doc-a" / name).replace(sub / name)
    (root / "extractor-output" / "doc-a" / "page-1.json").write_text(
        json.dumps(_page_json(1, [_table("stale reading")])), encoding="utf-8"
    )
    changes, skipped = plan_document("doc-a", _stored_rows(), root, method="mineru")
    assert skipped is None
    assert [c.chunk_id for c in changes] == ["doc-a-0001"]


def test_table_rows_are_matched_by_numeric_suffix_not_string_order(root: Path):
    """chunk ids are zero-padded to four digits; a document with 10,000+
    tables would sort `-10000` before `-0002` as strings. None exists today
    (the Governor's Budget has 1,246); this is cheap insurance, not a fix."""
    from chunking.repair_section_paths import _chunk_index
    assert _chunk_index({"chunk_id": "doc-a-10000"}) > _chunk_index({"chunk_id": "doc-a-0002"})


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
    assert result.per_document["doc-a"] == {"tables": 2, "changed": 1, "relabelled": 1, "to_blank": 0}


def test_dry_run_passes_the_sidecar_method_and_skips_docx(root: Path):
    """The corpus-wide plan reads `documents.json` ONCE and hands each
    document its recorded rung; DOCX bills have no page output and no table
    chunks, and are named as such instead of inflating the 'no cached
    extractor output' count."""
    (root / "documents.json").write_text(json.dumps({
        "doc-a": {"extraction": {"method": "mineru"}},
        "doc-x": {"source_format": "docx"},
    }), encoding="utf-8")
    sub = root / "extractor-output" / "doc-a" / "mineru"
    sub.mkdir()
    for name in ("page-1.json", "page-9.json"):
        (root / "extractor-output" / "doc-a" / name).replace(sub / name)
    rows = _stored_rows() + [
        {"chunk_id": "doc-x-0000", "doc_id": "doc-x", "is_table": False,
         "section_path": ["SEC 06-18"], "text": "[SEC 06-18] Section 1"}
    ]
    result = repair_section_paths(store=_FakeStore(rows), embedder=_FakeEmbedder(), root=root)
    assert result.changed == 1
    assert result.documents_skipped == {"doc-x": "docx document: section chunks, no tables, nothing to repair"}


def test_only_restricts_the_plan_to_the_named_documents(root: Path):
    rows = _stored_rows() + [
        {"chunk_id": "doc-b-0000", "doc_id": "doc-b", "is_table": True,
         "section_path": ["X"], "text": "X\nrow"}
    ]
    result = repair_section_paths(
        store=_FakeStore(rows), embedder=_FakeEmbedder(), root=root, only={"doc-a"}
    )
    assert set(result.per_document) == {"doc-a"}
    assert "doc-b" not in result.documents_skipped
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
from ingest.extract_dirs import resolve_extract_dir

# Planning reads these columns only. The `vector` column is 768 float32s on
# every one of 83,016 rows -- projecting it for a scan that only needs to
# decide WHICH rows change would pull ~255 MB off the share for nothing. The
# apply path re-scans a changed document with every column.
PLAN_COLUMNS = ["chunk_id", "doc_id", "text", "section_path", "is_table"]

DEFAULT_BATCH_SIZE = 2000

# G-T3: how many rows this pass was NOT supposed to touch get re-read after
# the write and compared to their pre-write values (identity/relabel.py's
# `_UNCHANGED_SAMPLE_SIZE`; spec G-T3 says 200 per table).
UNCHANGED_SAMPLE_SIZE = 200


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
    # doc_id -> {"tables", "changed", "relabelled", "to_blank"}: the per-
    # document old-vs-new the spec's predictions are stated in.
    per_document: dict[str, dict[str, int]] = field(default_factory=dict)
    reversal: list[dict[str, Any]] = field(default_factory=list)


def _chunk_index(row: Mapping[str, Any]) -> int:
    """The positional index a chunk_id encodes (`{doc_id}-{idx:04d}`)."""
    return int(str(row["chunk_id"]).rsplit("-", 1)[1])


def _read_sidecar(root: Path) -> dict[str, Any]:
    """`documents.json`, or {} when the data dir has none (a test's tmp root).
    Read ONCE per run -- 7,574 entries is nothing; re-reading it per
    document across the share would not be."""
    try:
        raw = json.loads((root / "documents.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


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
    doc_id: str, rows: list[Mapping[str, Any]], root: Path, *, method: str | None = None
) -> tuple[list[RowChange], str | None]:
    """Which of this document's table rows change, or why it cannot be planned.

    The mapping from stored chunk to extracted table is positional:
    `chunk_doc` emits table chunks FIRST, in `doc.tables` order, so table
    *n* is `{doc_id}-{n:04d}`. That is a hypothesis about what was ingested,
    not a fact about what is on disk now -- so it is GATED, not trusted
    (spec §3.2): the table count must match, and every line of the stored
    text below line 0 must match the rebuilt table's, or the whole document
    is skipped and named.

    `method` is the sidecar's `extraction.method` for this document (None for
    everything ingested before Plan B) -- it picks WHICH reading on disk is
    the one the corpus holds. See `ingest/extract_dirs.py` for why that must
    never be guessed from folder names.
    """
    found = resolve_extract_dir(doc_id, root, method=method)
    if found is None:
        return [], "no cached extractor output"
    directory, extractor = found
    reader = ODLReader() if "opendataloader" in extractor.lower() else MinerUReader()
    try:
        doc = reader.read(directory)
    except (OSError, ValueError) as exc:
        return [], f"extractor output unreadable: {exc}"

    table_rows = sorted((r for r in rows if r.get("is_table")), key=_chunk_index)
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
    store: ChunkStoreLike,
    root: Path,
    table: str,
    progress: Callable[[str], None],
    only: set[str] | None = None,
) -> tuple[list[RowChange], RepairResult, dict[str, Mapping[str, Any]]]:
    """Plan every document; also return the pre-write rows by chunk_id, which
    the apply path's untouched-row sample (G-T3) compares against."""
    rows = store.scan(table, PLAN_COLUMNS)
    before_by_id = {str(r["chunk_id"]): r for r in rows}
    by_doc: dict[str, list[Mapping[str, Any]]] = {}
    for row in rows:
        by_doc.setdefault(str(row["doc_id"]), []).append(row)
    if only is not None:
        by_doc = {d: r for d, r in by_doc.items() if d in only}
    progress(f"scanned {len(rows)} rows across {len(by_doc)} documents")

    sidecar = _read_sidecar(root)
    result = RepairResult(scanned=len(rows))
    changes: list[RowChange] = []
    for index, (doc_id, doc_rows) in enumerate(sorted(by_doc.items()), start=1):
        entry = sidecar.get(doc_id) or {}
        if entry.get("source_format") == "docx":
            # A DOCX bill is one chunk per Section with no Table blocks and no
            # page-N.json output; counting it as "no cached extractor output"
            # would inflate that figure and hide a real gap behind a known one.
            result.documents_skipped[doc_id] = (
                "docx document: section chunks, no tables, nothing to repair"
            )
            continue
        method = (entry.get("extraction") or {}).get("method")
        doc_changes, skipped = plan_document(doc_id, doc_rows, root, method=method)
        if skipped is not None:
            result.documents_skipped[doc_id] = skipped
            continue
        result.documents_planned += 1
        changes.extend(doc_changes)
        result.per_document[doc_id] = {
            "tables": sum(1 for r in doc_rows if r.get("is_table")),
            "changed": len(doc_changes),
            "relabelled": sum(1 for c in doc_changes if c.new_path),
            "to_blank": sum(1 for c in doc_changes if not c.new_path),
        }
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
    return changes, result, before_by_id


def repair_section_paths(
    *,
    store: ChunkStoreLike,
    embedder: EmbedderLike,
    root: Path,
    table: str = "budget_chunks",
    dry_run: bool = True,
    only: set[str] | None = None,
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
    changes, result, before_by_id = _plan_corpus(store, root, table, progress, only)
    if dry_run:
        progress(f"DRY RUN: {result.changed} rows would change; nothing written")
        return result
    raise NotImplementedError("apply path lands in Task 5")
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: 11 passed.

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
is skipped and named rather than half-written. The rung folder comes from
the sidecar's extraction.method; DOCX bills are named as such, not counted
as missing output."
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
    from chunking.builders._tokens import count_tokens
    assert written["token_count"] == count_tokens(written["text"])
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


class _DriftingStore(_FakeStore):
    """A store whose write also corrupts a row the pass never touched --
    the shape `identity/relabel.py`'s untouched-row sample exists to catch
    (a delete-then-add that lands on the wrong ids)."""

    def upsert_chunks(self, name, rows):
        super().upsert_chunks(name, rows)
        self.rows[0]["text"] = "CORRUPTED"


def test_apply_samples_untouched_rows_and_refuses_when_one_drifted(root: Path, tmp_path: Path):
    """G-T3's second half: changed rows verified in full AND a sample of
    rows nothing was supposed to touch compared to their pre-write values."""
    store = _DriftingStore(_full_rows())
    with pytest.raises(RuntimeError, match="never supposed to change"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_repair_section_paths.py -k apply -v`
Expected: all 8 FAIL with `NotImplementedError: apply path lands in Task 5`.

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


def _norm(value: Any) -> Any:
    """Lance hands list columns back as lists or arrays depending on the
    path; compare by value, not by container type."""
    return list(value) if isinstance(value, (list, tuple)) or hasattr(value, "tolist") else value


def _in_list(chunk_ids: Iterable[str]) -> str:
    from store.chunk_store import sql_str
    return "chunk_id IN (" + ", ".join(sql_str(c) for c in chunk_ids) + ")"


def _write_changed_rows(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    embedder: EmbedderLike,
    batch_size: int,
    progress: Callable[[str], None],
) -> list[dict[str, Any]]:
    """Fetch the changed rows in full, rewrite four columns, embed, write.

    Fetched by chunk_id list per batch -- ~5 scans for ~10,200 rows -- not
    one `doc_id = ...` scan per document, which would be ~4,500 filtered
    scans over the share for the same rows.

    Batched because `upsert_chunks` deletes the batch's chunk_ids and then
    adds the replacements as two separate LanceDB commits: batching bounds a
    crash landing between them to one batch instead of the whole corpus.
    """
    by_id = {c.chunk_id: c for c in changes}
    ordered = sorted(by_id)
    written: list[dict[str, Any]] = []
    total_batches = math.ceil(len(ordered) / batch_size) if ordered else 0
    for batch_num, start in enumerate(range(0, len(ordered), batch_size), start=1):
        ids = ordered[start:start + batch_size]
        rows = store.scan(table, _all_columns(), where=_in_list(ids))
        pending: list[dict[str, Any]] = []
        for row in rows:
            change = by_id.get(str(row.get("chunk_id")))
            if change is None:
                continue
            new_row = dict(row)
            new_row["section_path"] = list(change.new_path)
            new_row["text"] = change.new_text
            new_row["token_count"] = count_tokens(change.new_text)
            pending.append(new_row)
        if len(pending) != len(ids):
            raise RuntimeError(
                f"batch {batch_num}: asked for {len(ids)} rows, the store returned "
                f"{len(pending)} -- the corpus moved under the plan; re-run the dry run"
            )
        vectors = embedder.embed_batch([r["text"] for r in pending])
        for row, vector in zip(pending, vectors):
            row["vector"] = vector
        store.upsert_chunks(table, pending)
        written.extend(pending)
        progress(f"wrote batch {batch_num}/{total_batches} ({len(written)}/{len(changes)} rows)")
    return written


def _verify_nothing_was_lost(
    store: ChunkStoreLike,
    table: str,
    changes: list[RowChange],
    before_by_id: Mapping[str, Mapping[str, Any]],
    progress: Callable[[str], None],
) -> None:
    """Re-read every changed row and confirm exactly the four intended
    columns moved; then re-read a bounded sample of rows this pass was NEVER
    supposed to touch and confirm they still read as they did before the
    write. A matching ROW COUNT proves nothing — `upsert_chunks` deletes
    then adds, so a lost column and a lost value both leave the count
    identical (`identity/relabel.py`'s trap 3). The untouched sample is the
    half of spec G-T3 that catches a delete landing on the wrong ids."""
    expected = {c.chunk_id: c for c in changes}
    seen = 0
    ordered = sorted(expected)
    for start in range(0, len(ordered), DEFAULT_BATCH_SIZE):
        ids = ordered[start:start + DEFAULT_BATCH_SIZE]
        for row in store.scan(table, _all_columns(), where=_in_list(ids)):
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

    # Bounded, deterministic sample of rows nothing was supposed to touch.
    untouched = sorted(set(before_by_id) - set(expected))[:UNCHANGED_SAMPLE_SIZE]
    after = {str(r["chunk_id"]): r for r in store.scan(table, PLAN_COLUMNS, where=_in_list(untouched))} if untouched else {}
    for chunk_id in untouched:
        before, now = before_by_id[chunk_id], after.get(chunk_id)
        if now is None:
            raise RuntimeError(f"{chunk_id}: was never supposed to change and is GONE after the write")
        for col in ("text", "section_path", "is_table", "doc_id"):
            if _norm(now.get(col)) != _norm(before.get(col)):
                raise RuntimeError(
                    f"{chunk_id}: was never supposed to change but its {col!r} drifted; "
                    "restore from the snapshot this pass just took"
                )
    progress(f"verified {seen} changed rows in full, {len(untouched)} untouched rows sampled")


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

    # `IngestLock.acquire()` runs its own heartbeat thread; the explicit
    # beats below are belt-and-braces between phases, not what keeps the
    # lock alive through a 30-60 minute embed.
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
        _verify_nothing_was_lost(store, table, changes, before_by_id, progress)
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
Expected: 19 passed.

`sql_str` lives at `store/chunk_store.py:76` (verified) — do not inline a
quoting expression.

- [ ] **Step 5: Prove the FTS guard and the agency guard can fail**

Comment out `store.build_fts_index(table)`; run
`uv run pytest tests/test_repair_section_paths.py -k rebuilds -v` → FAIL. Restore.

Add `new_row["agency_canonical_ids"] = []` inside `_write_changed_rows`; run
`uv run pytest tests/test_repair_section_paths.py -k byte_identical -v` → FAIL. Remove.

Delete the untouched-sample loop from `_verify_nothing_was_lost`; run
`uv run pytest tests/test_repair_section_paths.py -k drifted -v` → FAIL. Restore.

Re-run the file: 19 passed.

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
    parser.add_argument("--table", default="budget_chunks",
                        help="budget_chunks (default) or fiscal_note_chunks")
    parser.add_argument("--doc", action="append", default=[],
                        help="plan only this doc_id (repeatable); prints its old->new per table")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--report", type=Path, default=None,
                        help="write the full plan as JSON")
    args = parser.parse_args(argv)
    if args.apply and args.doc:
        parser.error("--apply rewrites the whole table; --doc is a dry-run aid only")

    store, embedder, root = _load_live_store_and_embedder()
    result = repair_section_paths(
        store=store, embedder=embedder, root=root, table=args.table,
        dry_run=not args.apply, batch_size=args.batch_size,
        only=set(args.doc) or None,
    )
    print(f"table              {args.table}")
    print(f"scanned            {result.scanned}")
    print(f"documents planned  {result.documents_planned}")
    print(f"documents skipped  {len(result.documents_skipped)}")
    print(f"rows changed       {result.changed}")
    for doc_id in args.doc:
        stats = result.per_document.get(doc_id)
        print(f"  {doc_id}: {stats or result.documents_skipped.get(doc_id, 'not in this table')}")
        for r in [r for r in result.reversal if r["doc_id"] == doc_id][:8]:
            print(f"      {r['chunk_id']}: {' > '.join(r['before']['section_path'])!r} -> "
                  f"{' > '.join(r['after']['section_path'])!r}")
    reasons: dict[str, int] = {}
    for reason in result.documents_skipped.values():
        reasons[reason.split(":")[0]] = reasons.get(reason.split(":")[0], 0) + 1
    for reason, count in sorted(reasons.items(), key=lambda kv: -kv[1]):
        print(f"  skipped: {count:5d}  {reason}")
    if args.report:
        _atomic_write_json(args.report, {
            "table": args.table,
            "changed": result.changed,
            "scanned": result.scanned,
            "documents_planned": result.documents_planned,
            "documents_skipped": result.documents_skipped,
            "per_document": result.per_document,
            "rows": result.reversal,
        })
        print(f"report: {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the whole test file plus the full suite**

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: 20 passed.

Run: `uv run pytest -q 2>&1 | tail -5`
Expected: no new failures.

- [ ] **Step 5: Dry-run the three named documents first — the spec's own predictions**

The spec's numbers were measured per document; check those before reading
the corpus-wide total, because a corpus-wide miss is unreadable and a
per-document miss says exactly which shape the model got wrong.

```bash
cd ~/ask-the-budget-az-worktrees/table-section-path
export JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data
uv run python -m chunking.repair_section_paths \
  --doc governor-governors-budget-fy2026 --doc agao-afr-fy2024 --doc agao-afr-fy2021 \
  --doc jlbc-approps-fy2027-deq 2>&1 | tail -40
```

**Expected — predictions from the spec, not targets to tune toward. A mismatch means the model of the defect is wrong: STOP and report.**

| doc | tables | changed | note |
|---|---|---|---|
| `governor-governors-budget-fy2026` | 1,246 | ≈1,197 (spec: 1,196 differ + orphans) | relabelled ≫ to_blank; at least one printed line reads `'Table of Contents' -> '<an agency name>'` |
| `agao-afr-fy2024` | 422 | ≈261 (61.9%) | **planned, not skipped** — it must be read from `mineru/`, the sidecar's method; a `body mismatch` skip here means Task 3's lookup regressed |
| `agao-afr-fy2021` | — | — | the page-3 statements go `to_blank` (spec §1.3) |
| `jlbc-approps-fy2027-deq` | small | a few | the JLBC per-agency to-blank shape for G-T6 |

- [ ] **Step 6: Dry-run BOTH tables corpus-wide**

```bash
uv run python -m chunking.repair_section_paths --table budget_chunks \
  --report $SCRATCH/section-path-plan-budget.json 2>&1 | tail -30
uv run python -m chunking.repair_section_paths --table fiscal_note_chunks \
  --report $SCRATCH/section-path-plan-fiscal.json 2>&1 | tail -30
```

This reads every planned document's extractor JSON off disk (several GB in
total); expect tens of minutes, not seconds. **Expected, from spec §3.5:**

- budget: `rows changed` ≈ **10,200 − 351 ≈ 9,850**; fiscal notes ≈ **351**. The spec gives no tolerance. Treat ±15% as "the model held" and anything beyond as a stop — and say in the record which it was.
- `documents skipped` ≈ **399** with `no cached extractor output` (measured 2026-08-26 — the migration-era entries), **plus one** `docx document` (`legislature-budget-bill-fy2026-sb1735-2025`), plus whatever fails the body gate.
- **Two of the spec's eight bad-heading-run documents are in that 399 and cannot be repaired by this pass:** `governor-governors-budget-fy2027` and `agao-afr-fy2025` (verified: no `extractor-output/` folder for either). Name them in the record so nobody reads "repaired" as "all eight".

- [ ] **Step 7: Read the skip reasons, do not just count them**

```bash
uv run python -c "
import json,collections,sys
for f in sys.argv[1:]:
    p=json.load(open(f))
    c=collections.Counter(v.split(':')[0] for v in p['documents_skipped'].values())
    print(p['table'], dict(c))
    for d,r in [kv for kv in p['documents_skipped'].items() if not kv[1].startswith('no cached')][:10]: print('   ',d,'->',r)
" $SCRATCH/section-path-plan-budget.json $SCRATCH/section-path-plan-fiscal.json
```

**A large `body mismatch` count is a finding, not noise.** It means the
extractor output on the share no longer corresponds to what was ingested for
those documents, and they simply cannot be repaired by this pass. Record the
count and a few examples; do not loosen the gate to absorb them.

- [ ] **Step 8: Write the dry-run record**

Create `docs/superpowers/investigations/2026-08-26-section-path-repair-dry-run.md` containing: the exact commands, the headline counts for BOTH tables, the skip-reason table (with the two unrepairable heading-run documents named), the per-document numbers from Step 5 against the spec's predictions, and **ten example changes copied from the report** — five from the JLBC per-agency to-blank case (`before` path → nothing) and five from the Governor relabel case (`'Table of Contents'` → agency). State plainly whether each prediction matched.

- [ ] **Step 9: Commit**

```bash
git add chunking/repair_section_paths.py tests/test_repair_section_paths.py \
        docs/superpowers/investigations/2026-08-26-section-path-repair-dry-run.md
git commit -m "chunking: section_path repair CLI + the live dry-run record

Dry run is the default; --apply must be typed; --doc prints one document's
old->new. Dry-run counts for both tables recorded against the spec's
predictions."
```

- [ ] **Step 10: ⏸ CHECKPOINT — Destin's go/no-go. Do NOT start Task 7 until he says go.**

This is the one place in the plan where a person's judgement is needed, and
it sits before the only step that is expensive to undo. Show him, in plain
words and few of them:

1. the counts vs the spec's predictions (both tables), and whether they held;
2. the ten example before/after breadcrumbs from Step 8 — this is what the
   change LOOKS like: ~22% of table results will show **no breadcrumb**
   under the document name where they showed a wrong one before (spec D2,
   already his decision — but nobody has shown him one);
3. the skip list: ~399 unrepairable migration-era documents, including two
   of the eight bad-heading-run documents;
4. what the apply costs: the ingest lock held for the snapshot plus the
   re-embed (30–60 min on this machine), during which office uploads wait.

If he wants to see it rendered rather than read: start the dev server, ask
AI Mode a question that retrieves a JLBC agency summary table, screenshot
the breadcrumb line — that is the before; the after needs the write. Offer
it; do not block on it.

**Stop here.** The reversal record and the CRC-verified snapshot make the
write recoverable, but "recoverable" is not "free", and the decision to
rewrite 12% of the corpus is his.

---

### Task 7: Gates, the apply run, and STATUS

**Pre-condition: Destin said go at Task 6 Step 10.**

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
from ingest.extract_dirs import resolve_extract_dir
from store.config import resolve_data_dir

root = resolve_data_dir()
plan = {r['chunk_id']: r for r in json.load(open(sys.argv[1]))['rows']}
docs = json.loads((root/'documents.json').read_text())
bad = 0
for doc_id in ['jlbc-approps-fy2027-deq', 'governor-governors-budget-fy2026', 'agao-afr-fy2024']:
    meta = docs[doc_id]
    d, ex = resolve_extract_dir(doc_id, root, method=(meta.get('extraction') or {}).get('method'))
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
" $SCRATCH/section-path-plan-budget.json
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

- [ ] **Step 2b: G-T3 baseline — dump the columns that must not move, BOTH tables**

```bash
export JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data
uv run python -c "
import json, sys
from store.chunk_store import ChunkStore
from store.config import resolve_data_dir
s = ChunkStore(root=resolve_data_dir())
out = {}
for t in ('budget_chunks', 'fiscal_note_chunks'):
    rows = s.scan(t, ['chunk_id','agency_canonical_ids','fund_mentions','page','bbox','doc_type','fiscal_year'])
    out[t] = {r['chunk_id']: [list(r['agency_canonical_ids'] or []), list(r['fund_mentions'] or []), r['page'], list(r['bbox'] or []), r['doc_type'], r['fiscal_year']] for r in rows}
    print(t, len(rows))
json.dump(out, open(sys.argv[1], 'w'))
" $SCRATCH/gt3-before.json
```

- [ ] **Step 3: Apply — one table at a time, budget first**

```bash
cd ~/ask-the-budget-az-worktrees/table-section-path
uv run python -m chunking.repair_section_paths --apply --table budget_chunks 2>&1 | tee $SCRATCH/apply-budget.log
uv run python -m chunking.repair_section_paths --apply --table fiscal_note_chunks 2>&1 | tee $SCRATCH/apply-fiscal.log
```

Confirm from each log: a snapshot path was printed, `rows changed` equals
that table's dry-run count **exactly** (G-T5), `verified N changed rows in
full, 200 untouched rows sampled` printed with N equal to that count,
`full-text index rebuilt`, and a reversal record path. The second run takes
its own snapshot; that is the price of two tables and it is fine.

- [ ] **Step 4: G-T3 — nothing but the four columns moved, corpus-wide, BOTH tables**

```bash
uv run python -c "
import json, sys
from pathlib import Path
from store.chunk_store import ChunkStore
from store.config import resolve_data_dir
root = resolve_data_dir(); s = ChunkStore(root=root)
before = json.load(open(sys.argv[1]))
for t in ('budget_chunks', 'fiscal_note_chunks'):
    rev = json.load(open(sorted(Path(root).glob(f'section-path-reversal-{t}-*.json'))[-1]))
    rows = s.scan(t, ['chunk_id','section_path','text','agency_canonical_ids','fund_mentions','page','bbox','doc_type','fiscal_year'])
    by = {r['chunk_id']: r for r in rows}
    ids = {r['chunk_id'] for r in rev['rows']}
    missing = [i for i in ids if i not in by]
    wrong = [r['chunk_id'] for r in rev['rows'] if by[r['chunk_id']]['text'] != r['after']['text'] or list(by[r['chunk_id']]['section_path'] or []) != r['after']['section_path']]
    drift = [c for c, v in before[t].items() if c not in by or [list(by[c]['agency_canonical_ids'] or []), list(by[c]['fund_mentions'] or []), by[c]['page'], list(by[c]['bbox'] or []), by[c]['doc_type'], by[c]['fiscal_year']] != v]
    print(t, 'chunks', len(rows), '(before:', len(before[t]), ') reversal rows', len(ids), 'missing', len(missing), 'not landed', len(wrong), 'agency/fund/page/bbox drift corpus-wide', len(drift))
" $SCRATCH/gt3-before.json
```

Expected, for both tables: chunk count unchanged (budget 83,016 at the time
of writing — read it from the dry run's `scanned` figure), `missing 0`,
`not landed 0`, **`drift 0`** — that last number is spec G-T3's
"`agency_canonical_ids` and `fund_mentions` byte-identical corpus-wide".

- [ ] **Step 5: G-T2 post-write — re-run the eval**

```bash
cd /home/destin/YouCoded/Projects/ask-the-budget-az-dev
uv run python -m eval.run_eval 2>&1 | tail -20
```

**The gate is per-query status, not the aggregate.** Compare the two result
JSONs query by query:

The result files carry `per_query` rows keyed `id` / `status` / `rank`
(verified against `eval/results/2026-08-26T0235Z-a1a1eb6.json` — the first
draft of this step used `query_id` / `hit_rank`, which do not exist):

```bash
uv run python -c "
import json,sys
a=json.load(open(sys.argv[1])); b=json.load(open(sys.argv[2]))
qa={q['id']:q for q in a['per_query']}; qb={q['id']:q for q in b['per_query']}
assert set(qa)==set(qb), 'different query sets -- not comparable'
moved=[(k, qa[k].get('rank'), qb[k].get('rank')) for k in qa if qa[k].get('rank') != qb[k].get('rank')]
flipped=[(k, qa[k]['status'], qb[k]['status']) for k in qa if qa[k]['status'] != qb[k]['status']]
print('rank moved:', len(moved), moved[:10]); print('STATUS FLIPPED:', flipped)
" eval/results/<CONTROL>.json eval/results/<AFTER>.json
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
before/after (median 93 pages; 1,079 → 0 TOC labels; ≈10,200 rows across
BOTH tables, each stated), the two eval runs with their filenames and the
per-query verdict, the skip counts and their reasons, the two reversal
record paths and snapshot filenames, the G-T3 `drift 0` result, and — as
their own bullets, because they are open and will otherwise be read as
closed:

- **≈399 migration-era documents have no cached extractor output and were
  not repaired**, among them two of the eight bad-heading-run documents —
  `governor-governors-budget-fy2027` and `agao-afr-fy2025`. Their table
  labels are still the old text-search answer. (`agao-afr-fy2025` is also
  pinned by six eval ground-truth ids, so leaving it alone cost nothing
  there.)
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

**Spec coverage.** D1 → Task 2. D2 → Task 2 Step 2 (`test_a_table_under_no_heading_gets_an_empty_path_and_no_heading_line`) and Task 4. D3 → nothing built for §5, and §5.1–5.3 are carried into STATUS in Task 7 Step 7. §3.1 surgical-not-re-ingest → Task 4's module docstring and Task 5's apply path. §3.2 mapping gate → Task 4 Steps 3, 6. §3.3 four columns, and to-blank REMOVING line 0 → Task 4 `_compose`, Task 5 `test_apply_leaves_the_agency_and_fund_columns_byte_identical`. §3.4 coverage → Task 6 Steps 6–7 (both tables; the two unrepairable heading-run documents named). §3.5 counts → Task 6 Steps 5–6 predictions, per document and per table. §4 rejected alternatives → nothing to build. G-T1 → Task 3 (plus a spec that the fixture really holds the trap). G-T2 → Task 7 Steps 2, 5 (field names verified against a real result file). G-T3 → Task 5's untouched-row sample + Task 7 Steps 2b/4 (corpus-wide, both tables). G-T4 → Task 7 Step 6. G-T5 → Task 7 Step 3. G-T6 → Task 7 Step 1.

**Placeholder scan.** No TBD/TODO. Every code step carries runnable code. The two `<CONTROL>` / `<AFTER>` tokens in Task 7 Step 5 are filenames produced by Steps 2 and 5 and cannot be known in advance; the step says where they come from. `$SCRATCH` is the executing session's scratchpad directory.

**Type consistency.** `resolve_extract_dir(doc_id, root, *, method=None) -> tuple[Path, str] | None` is defined in Task 3 (`ingest/extract_dirs.py`) and imported unchanged in Tasks 4 and 7. `plan_document(..., *, method=None)` in Task 4 is called with the sidecar's method by `_plan_corpus` and without one by the tests. `_plan_corpus` returns a 3-tuple `(changes, result, before_by_id)` and both callers (Task 4's dry run, Task 5's apply) unpack three. `_verify_nothing_was_lost(store, table, changes, before_by_id, progress)` takes five arguments in Task 5's definition and call. `RowChange` fields are used identically in Tasks 4 and 5. `RepairResult.documents_skipped` is `dict[str, str]` and `per_document` is `dict[str, dict[str, int]]` everywhere. `owner_path(block) -> list[str]` is defined in Task 1 and consumed in Tasks 2, 3, 4.

**Claims in this plan verified against the code and data on 2026-08-26, so the executor need not re-derive them:** `doc.tables` and `OutlineNode.body_blocks` hold the SAME `Table` objects (MinerU's multi-page reassembly runs BEFORE `_build_outline`, and ODL has none), so identity matching is sound; `sql_str` is at `store/chunk_store.py:76`; `IngestLock()` takes no required arguments and `acquire()` starts its own heartbeat thread; `identity.relabel._default_snapshot_and_verify` exists; eval `per_query` rows carry `id`/`status`/`rank`; the Governor's Budget contents heading is on page 2; `agao-afr-fy2024` has both `mineru/` and `mineru-ocr/` and the sidecar says `mineru`; 399 documents have no `extractor-output/` folder, including `governor-governors-budget-fy2027` and `agao-afr-fy2025`; the one DOCX document is `legislature-budget-bill-fy2026-sb1735-2025`; `scripts/` ships in the bundle and `ingest/` already imports from it, so `chunking/` importing `ingest.extract_dirs` introduces nothing new.

**One known risk in this plan's own code, stated rather than hidden:** Task 4's `plan_document` imports `_build_text` from `chunking.builders.table_chunk` — a private function. If Task 2's implementer renames or inlines it, Task 4 breaks. It is imported rather than reimplemented on purpose: a second copy of the text format is exactly how the repair and a re-chunk would silently diverge (G-T6). If it must move, make it public rather than duplicating it.
