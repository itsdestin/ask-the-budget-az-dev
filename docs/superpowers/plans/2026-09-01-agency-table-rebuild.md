# Agency Operating Tables Implementation Plan

> ## ✅ EXECUTED — ALL 12 TASKS DONE, THE CORPUS WAS WRITTEN 2026-09-03. DO NOT RE-RUN.
>
> **Task 12 ran on 2026-09-03 from the main checkout** (Destin's yes at the
> checkpoint): dry run matched the record to the row, control eval
> `eval/results/2026-09-03T0942Z-ce91af4`, apply 09:42–09:49Z wrote 4,656
> rows / 0 skipped with snapshot `lancedb-20260903T094313Z.zip` and reversal
> `table-rebuild-reversal-budget_chunks-2026-09-03T0943Z.json`, post eval
> `eval/results/2026-09-03T0950Z-ce91af4` per-query identical. Full record in
> the dry-run investigation doc and STATUS.md. G-OT4 offered, not run; G-OT5
> (Destin's browser check) outstanding. The paragraphs below are the state as
> it stood before that run.
>
> **Tasks 1–11 are DONE and committed on branch `agency-tables`.** Phase A
> (Tasks 1–4) shipped 2026-09-01. Phase B's code (Tasks 5–9), the live dry run
> (Task 10) and the rehearsal on a copy plus G-OT2/G-OT3 (Task 11) are all
> built, run and recorded in
> `docs/superpowers/investigations/2026-09-01-operating-table-rebuild-dry-run.md`.
>
> **Task 12 — the live apply — has NOT run and is waiting on Destin's explicit
> yes** at the checkpoint in that record. Nothing has been written to the live
> corpus by this plan.
>
> **A second apply is a content no-op, so run it once.** The rehearsal proved
> it: all 4,656 rebuilt tables come back byte-identical on a second pass, with
> no verdict changing. But the apply rewrites four columns unconditionally
> (spec D4), so a second run still spends a ~670 MB snapshot, a ~30 MB
> reversal record, 4,656 re-embeddings and about ten minutes to write exactly
> the same bytes. There is no reason to do it.
>
> **⚠ The G-OT2 commands below are WRONG as written.** `eval/run_eval.py` has
> no `--note` flag (its options are `--queries`, `--threshold`,
> `--results-dir`, `--corpus`), so `--note "..."` exits 2 and writes nothing —
> run and observed, not inferred. Drop the flag; the filename and the record
> are what label a run. The same wrong flag appears at Task 4's
> `run_agent_eval` line and was not checked there (that run costs money).

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the model labelled table cells in every `retrieve` result (phase A), then rebuild every JLBC agency operating table from the PDF's own text layer, accept only the ones whose subtotals add up, and write them back without moving a chunk (phase B).

**Architecture:** One vocabulary module (`chunking/table_text.py`) holds the regexes for year headers, figures and footnote markers plus the peel and header finder; phase A's renderer (`retrieval/table_view.py`) and phase B's reader (`chunking/readers/text_layer_table.py`) both import it. The arithmetic gate (`chunking/table_gate.py`) is written and calibrated on the stored corpus before the reader exists. The reader runs inside `MinerUReader` when it is handed the source PDF, so ingest and the one-time repair (`chunking/repair_tables.py`) share one producer.

**Tech Stack:** Python 3.12, PyMuPDF (`fitz`, already a dependency), LanceDB via `store.chunk_store.ChunkStore`, pytest, `uv run`.

Spec: `docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md` (read it first; section numbers below refer to it).

## Global Constraints

- **Phase A ships and is committed before any phase B task starts** (spec D6). Tasks 1–4 are phase A.
- **Phase B waits for the section-path plan.** Task 5 opens by checking `chunking/repair_section_paths.py` and `ingest/extract_dirs.py` exist. If they do not, stop and say so — do not rebuild them here (spec D7).
- **The payload's `text` field is never replaced** (spec §5). `text_labelled` is added beside it. No `text_format` key.
- **Chunk boundaries never move** (spec D4): the repair writes only `text`, `table_html`, `token_count`, `vector`. Never `chunk_id`, `page`, `bbox`, `section_path`, stamp columns.
- **A table that fails the gate keeps its current text** (spec D3). The reported number is "tables we could not verify", never "tables changed".
- **No paid model run without Destin's go-ahead.** G-OT4 is offered, not launched.
- **Never run anything against the live LanceDB without `--dry-run` semantics first.** `--apply` only after the rehearsal on a copy (Task 11).
- **Run every command from the repo root** `/home/destin/YouCoded/Projects/ask-the-budget-az-dev` with `uv run`. Tests: `uv run pytest <file> -v`. Store-touching scripts need `JLBC_DATA_DIR` (the live one is `data/insight-data`; a rehearsal copy is a different path).
- **Commit after every task.** Commit messages start `feat(tables):`, `test(tables):`, `docs(tables):`, `chore(tables):`.
- Every non-trivial edit carries a WHY comment (Destin reads the code through them).

## File structure

| File | Responsibility | Task |
|---|---|---|
| `chunking/table_text.py` (new) | The vocabulary: doc types, ladder markers, `YEAR_RE`, `KIND_RE`, `FIGURE_RE`, `MARKER_RE`, `normalise_label`, `split_figure_marker`, `peel_markers`, `find_header`, `has_ladder_marker` | 1 |
| `retrieval/table_view.py` (new) | `render_labelled(text) -> str \| None` | 1 |
| `harness/tools.py` | `_retrieve` adds `text_labelled` for table chunks | 2 |
| `harness/system-prompt.md` | One paragraph under "The 3-year structure of per-agency tables" | 2 |
| `scripts/count_headerless_tables.py` (new) | Measures headerless table chunks outside D1 (spec §5 rule 5) | 3 |
| `chunking/table_gate.py` (new) | `reconcile(rows) -> GateResult`, `count_figure_rows`, `has_merged_cell` | 5 |
| `chunking/repair_common.py` (new) | Helpers moved out of `repair_section_paths.py`: `atomic_write_json`, `in_list`, `all_columns`, `reversal_stamp`, `ChunkStoreLike`, `EmbedderLike`, `default_snapshot_and_verify` | 5 |
| `chunking/readers/text_layer_table.py` (new) | `refine_operating_table(table, pdf) -> RefineOutcome` | 6 |
| `chunking/readers/mineru_reader.py` | `MinerUReader(source_pdf=…)` applies the refinement | 7 |
| `chunking/builder.py`, `ingest/worker.py` | `chunk_doc(source_pdf=…)`; the worker passes the job's file | 7 |
| `chunking/repair_tables.py` (new) | Calibration, plan/dry run, apply, CLI | 5, 8, 9, 10 |
| `tests/test_table_text.py`, `tests/test_table_view.py`, `tests/test_table_gate.py`, `tests/test_text_layer_table.py`, `tests/test_repair_tables.py` (new); `tests/test_harness_tools.py`, `tests/test_harness_prompt.py`, `tests/test_builder.py` (modified) | | |

---

## Phase A — labelled cells

### Task 1: The table vocabulary and the labelled renderer

**Files:**
- Create: `chunking/table_text.py`
- Create: `retrieval/table_view.py`
- Test: `tests/test_table_text.py`, `tests/test_table_view.py`

**Interfaces:**
- Produces (used by Tasks 2, 5, 6, 8):
  - `OPERATING_TABLE_DOC_TYPES: frozenset[str]`, `LADDER_MARKERS: tuple[str, ...]`
  - `YEAR_RE`, `KIND_RE`, `FIGURE_RE`, `MARKER_RE` (compiled regexes)
  - `has_ladder_marker(text: str) -> bool`
  - `normalise_label(s: str) -> str`
  - `split_figure_marker(word: str) -> tuple[str, str | None]`
  - `peel_markers(cell: str) -> str`
  - `figure_tokens(cell: str) -> list[str]`
  - `Header(labels: dict[int, str], rows: tuple[int, ...], first_col: int)`; `find_header(rows: Sequence[Sequence[str]], *, limit: int = 6) -> Header | None`
  - `render_labelled(text: str) -> str | None`; `LABELLED_MAX_CHARS = 20_000`

- [ ] **Step 1: Write the failing vocabulary tests**

`tests/test_table_text.py`:

```python
"""chunking/table_text.py — the vocabulary both phases of the operating-table
work share. Spec §3.1 step 6 and §5 rules 1 and 3."""
from __future__ import annotations

import pytest

from chunking.table_text import (
    find_header,
    figure_tokens,
    has_ladder_marker,
    normalise_label,
    peel_markers,
    split_figure_marker,
)


@pytest.mark.parametrize("word, figure, marker", [
    ("99,294,5003/", "99,294,500", "3/"),
    ("10,124,311,2008/-13/", "10,124,311,200", "8/-13/"),
    ("15,352,3001/", "15,352,300", "1/"),
    ("212.312/", "212.3", "12/"),
    ("2,358.34/", "2,358.3", "4/"),
    ("(1,234,500)3/", "(1,234,500)", "3/"),
    ("99,294,500", "99,294,500", None),
    ("5003/", "5003/", None),          # under 1,000 is ambiguous — left alone
    ("General", "General", None),
])
def test_split_figure_marker(word, figure, marker):
    assert split_figure_marker(word) == (figure, marker)


@pytest.mark.parametrize("cell, rendered", [
    ("99,294,5003/", "99,294,500 [3/]"),
    ("15,916,000 4/", "15,916,000 [4/]"),
    ("197,263,200 1/2/", "197,263,200 [1/2/]"),
    ("212.312/", "212.3 [12/]"),
    ("205,641,700 13/22", "205,641,700 13/22"),   # no trailing slash: not a marker
    ("377,583,700 2,778,602,700", "377,583,700 2,778,602,700"),
    ("", ""),
])
def test_peel_markers(cell, rendered):
    assert peel_markers(cell) == rendered


def test_figure_tokens_ignores_peeled_markers():
    assert figure_tokens("197,263,200 1/2/") == ["197,263,200"]
    assert figure_tokens("377,583,700 2,778,602,700") == ["377,583,700", "2,778,602,700"]
    assert figure_tokens("0") == ["0"]
    assert figure_tokens("SPECIAL LINE ITEMS") == []


def test_normalise_label_strips_markers_case_and_dashes():
    assert normalise_label("Medicaid Services 5/6/7/") == "MEDICAID SERVICES"
    assert normalise_label("SUBTOTAL – Other  Appropriated Funds") == "SUBTOTAL - OTHER APPROPRIATED FUNDS"
    assert normalise_label("  ") == ""


def test_has_ladder_marker():
    assert has_ladder_marker("x\nOPERATING SUBTOTAL\t1\t2")
    assert has_ladder_marker("TOTAL - ALL SOURCES\t1")
    assert not has_ladder_marker("Table 1\nBasic State Aid")


def test_find_header_two_rows_three_columns():
    rows = [
        ["", "FY 2024", "FY 2025", "FY 2026"],
        ["", "ACTUAL", "ESTIMATE", "APPROVED"],
        ["OPERATING BUDGET", "", "", ""],
    ]
    h = find_header(rows)
    assert h is not None
    assert h.rows == (0, 1)
    assert h.first_col == 1
    assert h.labels == {1: "FY 2024 ACTUAL", 2: "FY 2025 ESTIMATE", 3: "FY 2026 APPROVED"}


def test_find_header_one_row_merged_cells():
    rows = [["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"], ["General Fund", "1", "2", "3"]]
    h = find_header(rows)
    assert h.rows == (0,)
    assert h.labels[3] == "FY 2026 APPROVED"


def test_find_header_four_columns_fy2006_shape():
    """The FY2006 chunk: a one-year noise row above, a kind-only cell inside."""
    rows = [
        ["", "", "FY 2005", "JLBC Analyst: Nick Klingerman"],
        ["", "FY 2004 Actual", "Estimate", "FY 2006 Approved", "FY 2007 Approved"],
        ["", "", "", "", ""],
        ["OPERATING BUDGET", "", "", "", ""],
    ]
    h = find_header(rows)
    assert h.rows == (1,)
    assert h.labels == {1: "FY 2004 Actual", 2: "Estimate", 3: "FY 2006 Approved", 4: "FY 2007 Approved"}


def test_find_header_accepts_fy_without_space_and_none_when_absent():
    assert find_header([["", "FY2024", "FY2025"]]) is not None
    assert find_header([["FUND SOURCES", "", ""], ["General Fund", "1", "2"]]) is None
    assert find_header([]) is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_table_text.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'chunking.table_text'`

- [ ] **Step 3: Write `chunking/table_text.py`**

```python
"""The vocabulary of a JLBC operating table.

Shared by phase A (`retrieval/table_view.py`, the labelled rendering the
model reads) and phase B (`chunking/readers/text_layer_table.py`, the
text-layer rebuild) so the two can never disagree about what a year
header, a figure or a footnote marker looks like. Spec:
docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md §3.1, §5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# Spec D1: only these two document types carry the operating table.
OPERATING_TABLE_DOC_TYPES = frozenset({"approps-per-agency", "baseline-per-agency"})

# Spec D1: a table is in scope when its text carries one of these.
LADDER_MARKERS = ("OPERATING SUBTOTAL", "FUND SOURCES", "AGENCY TOTAL", "TOTAL - ALL SOURCES")

# `FY 2024`, `FY2024`. The year is group 1.
YEAR_RE = re.compile(r"\bFY ?(\d{4})\b")
# The second header line. Case-insensitive because FY2006 prints `Actual`.
KIND_RE = re.compile(r"^(ACTUAL|ESTIMATE|EST\.?|APPROVED|BASELINE)$", re.IGNORECASE)
# A printed figure: optional accounting parentheses, optional `$`, comma
# groups, optional decimals (FTE prints one). A bare `0` matches too.
FIGURE_RE = re.compile(r"\(?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?")
# A footnote marker: `3/`, `8/-13/`, `12/13/`, `1/2/`.
MARKER_RE = re.compile(r"\d{1,2}/(?:-?\d{1,2}/)*")

# The two fused shapes MinerU (and the FY2006 text layer) print: a
# comma-grouped figure or a one-decimal FTE with the marker glued on.
# `\d{3}` after each comma is exact, so `99,294,5003/` can only split as
# `99,294,500` + `3/`. A figure under 1,000 (`5003/`) has no comma group
# and is ambiguous, so it is deliberately not matched.
_FUSED_COMMA = re.compile(r"^(\(?\$?\d{1,3}(?:,\d{3})+\)?)(\d{1,2}/(?:-?\d{1,2}/)*)$")
_FUSED_DECIMAL = re.compile(r"^(\(?\$?\d{1,3}(?:,\d{3})*\.\d)(\d{1,2}/(?:-?\d{1,2}/)*)$")

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})


def has_ladder_marker(text: str) -> bool:
    return any(m in text for m in LADDER_MARKERS)


def normalise_label(s: str) -> str:
    """Upper-case, one space between words, ASCII dashes, trailing footnote
    markers and colons removed. Used to compare a printed label with a
    MinerU label and to classify rows in the gate."""
    s = " ".join(s.translate(_DASHES).split()).upper()
    # Strip any run of markers at the end (`MEDICAID SERVICES 5/6/7/`).
    s = re.sub(r"(\s*\d{1,2}/(?:-?\d{1,2}/)*)+$", "", s)
    return s.rstrip(":").strip()


def split_figure_marker(word: str) -> tuple[str, str | None]:
    """`99,294,5003/` -> (`99,294,500`, `3/`); anything else -> (word, None)."""
    for rx in (_FUSED_COMMA, _FUSED_DECIMAL):
        m = rx.match(word)
        if m:
            return m.group(1), m.group(2)
    return word, None


def _is_figure(token: str) -> bool:
    return token in ("-", "0") or FIGURE_RE.fullmatch(token) is not None


def peel_markers(cell: str) -> str:
    """Render every footnote marker in a cell as ` [3/]` after its figure,
    so the digits of the marker never touch the digits of the figure.
    A marker already separated by a space gets the same brackets."""
    out: list[str] = []
    for tok in cell.split():
        fig, mk = split_figure_marker(tok)
        if mk is not None:
            out.extend([fig, f"[{mk}]"])
        elif MARKER_RE.fullmatch(tok) and out and _is_figure(out[-1]):
            out.append(f"[{tok}]")
        else:
            out.append(tok)
    return " ".join(out)


def figure_tokens(cell: str) -> list[str]:
    """The figures in a cell, markers peeled away. Two of them means a
    merged cell (spec §1)."""
    return [t for t in peel_markers(cell).split() if _is_figure(t)]


@dataclass(frozen=True)
class Header:
    labels: dict[int, str]   # column index -> column label
    rows: tuple[int, ...]    # the row indices the header occupied
    first_col: int           # index of the first year column


def _clean(s: str) -> str:
    return " ".join(s.split())


def find_header(rows: Sequence[Sequence[str]], *, limit: int = 6) -> Header | None:
    """Spec §5 rule 1 / §3.1 step 4 on tab-split rows.

    The first row (among the first `limit`) with two or more cells holding
    a year token names the columns. Every non-empty cell from the first
    year cell rightwards is a label — so the FY2006 `Estimate` cell, which
    has no year, still labels its column. If the next row is nothing but
    kind tokens (`ACTUAL / ESTIMATE / APPROVED`) it is appended.
    """
    for i, row in enumerate(rows[:limit]):
        year_cols = [j for j, c in enumerate(row) if YEAR_RE.search(c)]
        if len(year_cols) < 2:
            continue
        first = year_cols[0]
        labels = {j: _clean(c) for j, c in enumerate(row) if j >= first and _clean(c)}
        consumed = [i]
        if i + 1 < len(rows):
            kinds = {j: _clean(c) for j, c in enumerate(rows[i + 1]) if _clean(c)}
            if kinds and all(KIND_RE.match(v) for v in kinds.values()) and all(j >= first for j in kinds):
                for j, v in kinds.items():
                    labels[j] = f"{labels[j]} {v.upper()}" if j in labels else v.upper()
                consumed.append(i + 1)
        return Header(labels=labels, rows=tuple(consumed), first_col=first)
    return None
```

- [ ] **Step 4: Run the vocabulary tests**

Run: `uv run pytest tests/test_table_text.py -v`
Expected: all PASS.

- [ ] **Step 5: Write the failing renderer tests**

`tests/test_table_view.py`:

```python
"""retrieval/table_view.py — spec §5. Pure text in, labelled text out."""
from __future__ import annotations

from retrieval.table_view import LABELLED_MAX_CHARS, MERGED_NOTE, render_labelled

AHCCCS = "\n".join([
    "FY 2026 Budget",
    "\tFY 2024 ACTUAL\tFY 2025 ESTIMATE\tFY 2026 APPROVED",
    "OPERATING BUDGET\t\t\t",
    "Full Time Equivalent Positions\t2,358.3\t2,459.3\t2,459.3",
    "OPERATING SUBTOTAL\t155,570,300\t156,637,800\t197,263,200 1/2/",
    "DES Eligibility\t116,083,200\t98,906,500\t99,294,5003/",
    "SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds\t377,583,700 2,778,602,700\t455,300,200 3,032,812,300\t621,178,500 3,234,831,100",
    "Case Management Provider Wage Increases\t0\t1,000,000\t0",
])


def test_preamble_survives_and_header_rows_are_consumed():
    out = render_labelled(AHCCCS)
    assert out is not None
    lines = out.split("\n")
    assert lines[0] == "FY 2026 Budget"
    assert "FY 2024 ACTUAL\tFY 2025" not in out          # the header row itself is gone
    assert lines[1] == "OPERATING BUDGET"                 # group heading = label alone


def test_every_value_carries_its_column_label():
    out = render_labelled(AHCCCS)
    assert "Full Time Equivalent Positions | FY 2024 ACTUAL: 2,358.3 | FY 2025 ESTIMATE: 2,459.3 | FY 2026 APPROVED: 2,459.3" in out


def test_footnote_markers_are_peeled():
    out = render_labelled(AHCCCS)
    assert "FY 2026 APPROVED: 197,263,200 [1/2/]" in out
    assert "FY 2026 APPROVED: 99,294,500 [3/]" in out
    assert "99,294,5003/" not in out


def test_merged_cell_is_named_not_hidden():
    out = render_labelled(AHCCCS)
    assert f"FY 2026 APPROVED: 621,178,500 and 3,234,831,100 {MERGED_NOTE}" in out


def test_zero_is_a_value_and_empty_cells_are_omitted():
    out = render_labelled(AHCCCS)
    assert "Case Management Provider Wage Increases | FY 2024 ACTUAL: 0 | FY 2025 ESTIMATE: 1,000,000 | FY 2026 APPROVED: 0" in out
    text = "x\n\tFY 2024\tFY 2025\tFY 2026\nGeneral Fund\t1,000\t\t3,000"
    assert "General Fund | FY 2024: 1,000 | FY 2026: 3,000" in render_labelled(text)


def test_extra_column_beyond_the_header_gets_a_positional_label():
    text = "x\n\tFY 2024\tFY 2025\tFY 2026\nGeneral Fund\t1,000\t2,000\t\t4,000"
    assert "General Fund | FY 2024: 1,000 | FY 2025: 2,000 | column 5: 4,000" in render_labelled(text)


def test_no_header_or_no_table_rows_returns_none():
    assert render_labelled("FUND SOURCES\nGeneral Fund\t1\t2\t3") is None
    assert render_labelled("A prose passage with no tabs at all.") is None
    assert render_labelled("") is None


def test_size_cap():
    big = AHCCCS + "\n" + ("Row\t1\t2\t3\n" * 3000)
    assert len(big) > LABELLED_MAX_CHARS
    assert render_labelled(big) is None
```

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/test_table_view.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'retrieval.table_view'`

- [ ] **Step 7: Write `retrieval/table_view.py`**

```python
"""Phase A of the operating-table work (spec §5): render a table chunk's
tab-joined text as `column-header: value` cells so the model reads a
label, not a position.

Pure function over `text`. No store access and no HTML: `table_html`
carries the same merged cells as the text, and nothing else in the app
renders it (verified 2026-09-01).
"""
from __future__ import annotations

from chunking.table_text import figure_tokens, find_header, peel_markers

# Spec §5 rule 7: the four 1.8 MB tab-padded AFR chunks would grow ~1.6x
# inside a payload that is already the problem.
LABELLED_MAX_CHARS = 20_000
MERGED_NOTE = "(two values in one cell — read with care)"


def render_labelled(text: str) -> str | None:
    """`None` means "send the text as today": no tab-joined rows, no
    detectable header, or too big."""
    if not text or len(text) > LABELLED_MAX_CHARS:
        return None
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if "\t" in line), None)
    if first is None:
        return None
    preamble, body = lines[:first], lines[first:]
    rows = [line.split("\t") for line in body]
    header = find_header(rows)
    if header is None:
        return None

    out = list(preamble)
    for i, cells in enumerate(rows):
        if i in header.rows:
            continue
        label = " ".join(c.strip() for c in cells[: header.first_col] if c.strip())
        parts: list[str] = []
        for j in range(header.first_col, len(cells)):
            cell = cells[j].strip()
            if not cell:
                continue  # rule 2: an empty cell is omitted, never a blank
            column = header.labels.get(j) or f"column {j + 1}"
            figures = figure_tokens(cell)
            if len(figures) >= 2:
                # Rule 4: honest, not hidden. Phase B removes the case.
                parts.append(f"{column}: {' and '.join(figures)} {MERGED_NOTE}")
            else:
                parts.append(f"{column}: {peel_markers(cell)}")
        if not label and not parts:
            continue
        out.append(" | ".join(([label] if label else []) + parts))
    return "\n".join(out)
```

- [ ] **Step 8: Run both test files**

Run: `uv run pytest tests/test_table_text.py tests/test_table_view.py -v`
Expected: all PASS.

- [ ] **Step 9: Mutation check, then commit**

Temporarily change `if len(figures) >= 2:` to `>= 3` and run `tests/test_table_view.py` — `test_merged_cell_is_named_not_hidden` must fail. `git checkout retrieval/table_view.py`, re-run, green.

```bash
git add chunking/table_text.py retrieval/table_view.py tests/test_table_text.py tests/test_table_view.py
git commit -m "feat(tables): shared table vocabulary and the labelled-cell renderer (phase A, spec §5)"
```

---

### Task 2: `text_labelled` in the retrieve payload, and the prompt paragraph

**Files:**
- Modify: `harness/tools.py` (imports near line 57; the `response` dict in `_retrieve`, near line 1436–1455)
- Modify: `harness/system-prompt.md` (under `### The 3-year structure of per-agency tables`, near line 897)
- Test: `tests/test_harness_tools.py` (the locked-contract test near line 483, plus two new tests), `tests/test_harness_prompt.py` (one new test)

**Interfaces:**
- Consumes: `retrieval.table_view.render_labelled`
- Produces: payload key `text_labelled: str` on table chunks whose text has a header; absent otherwise.

- [ ] **Step 1: Add the failing tool tests**

Append to `tests/test_harness_tools.py`:

```python
# ---------------------------------------------------------------------------
# Phase A of the operating-table spec: labelled cells ride beside `text`
# ---------------------------------------------------------------------------

_TABLE_TEXT = "\n".join([
    "FY 2026 Budget",
    "\tFY 2024 ACTUAL\tFY 2025 ESTIMATE\tFY 2026 APPROVED",
    "General Fund\t7,699,669,300\t7,882,875,800\t8,287,685,600",
])


def test_table_chunk_carries_text_labelled_beside_unchanged_text(monkeypatch):
    _fake_retrieve(monkeypatch, _chunk(is_table=True, text=_TABLE_TEXT))
    ex = ToolExecutor("conv-1", "budget", "standard")
    chunk = _run(ex, "retrieve", {"query": "q"})["chunks"][0]
    # `text` is what the linker, the viewer and the scorer read — never replaced.
    assert chunk["text"] == _TABLE_TEXT
    assert chunk["text_length"] == len(_TABLE_TEXT)
    assert "General Fund | FY 2024 ACTUAL: 7,699,669,300" in chunk["text_labelled"]


def test_narrative_chunk_and_headerless_table_have_no_text_labelled(monkeypatch):
    _fake_retrieve(monkeypatch, [
        _chunk(),                                                    # prose
        _chunk(chunk_id="t2", is_table=True, text="FUND SOURCES\nGeneral Fund\t1\t2\t3"),
    ])
    ex = ToolExecutor("conv-1", "budget", "standard")
    chunks = _run(ex, "retrieve", {"query": "q"})["chunks"]
    assert "text_labelled" not in chunks[0]
    assert "text_labelled" not in chunks[1]
```

In `test_retrieve_response_shape_matches_the_locked_contract`, add above the `assert set(chunk) == {…}` line:

```python
    # `text_labelled` is the one OPTIONAL key (phase A of the operating-table
    # spec): present only on table chunks with a detectable header. The
    # fake chunk here is prose, so the locked set below is the full set.
```

- [ ] **Step 2: Run to verify the new tests fail**

Run: `uv run pytest tests/test_harness_tools.py -k "text_labelled" -v`
Expected: 1 FAIL (`KeyError: 'text_labelled'`), 1 PASS.

- [ ] **Step 3: Add the field in `harness/tools.py`**

Add the import beside the other `retrieval` imports:

```python
from retrieval.table_view import render_labelled
```

In `_retrieve`, replace the list comprehension that builds `"chunks"` with a helper call. Add this function at module level, just above `_dump`:

```python
def _chunk_entry(c, *, alias: str, title: str, group: Any, include_group: bool) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "chunk_id": c.chunk_id,
        # The short handle the model tags figures with (`[[c3]]`).
        "alias": alias,
        "doc_id": c.doc_id,
        "doc_title": title,
        "publisher": c.publisher,
        "fiscal_year": c.fiscal_year,
        "doc_type": c.doc_type,
        "section_path": c.section_path,
        # v1 chunks are single-page, so start == end. Both fields exist
        # because the interface renders a range.
        "page_start": c.page,
        "page_end": c.page,
        "bbox": c.bbox,
        "text": c.text,
        # Saves the model counting characters when it wants explicit
        # offsets instead of a quote.
        "text_length": len(c.text or ""),
        "score": c.score,
    }
    if include_group:
        entry["group"] = group
    if c.is_table:
        # Phase A of the operating-table spec (§5): the model reads a
        # label, not a position. `text` stays as-is because the citation
        # linker, the viewer and the Layer 2 scorer all read it and the
        # first two hold offsets into the stored text.
        labelled = render_labelled(c.text or "")
        if labelled is not None:
            entry["text_labelled"] = labelled
    return entry
```

and in `_retrieve`:

```python
        response: dict[str, Any] = {
            "chunks": [
                _chunk_entry(
                    c,
                    alias=self._alias_by_chunk[c.chunk_id],
                    title=titles.get(c.doc_id, ""),
                    group=_group_of(c),
                    include_group=spread is not None,
                )
                for c in result.chunks
            ],
```

(Delete the old inline dict; the keys and their order are unchanged, which the locked-contract test proves.)

- [ ] **Step 4: Run the whole tool suite**

Run: `uv run pytest tests/test_harness_tools.py -v`
Expected: all PASS, including the locked-contract test and `test_retrieve_chunks_carry_stable_aliases`.

- [ ] **Step 5: Add the failing prompt test**

Append to `tests/test_harness_prompt.py`:

```python
def test_budget_prompt_tells_the_model_to_read_text_labelled():
    """Phase A of the operating-table spec: the field exists only if the
    prompt says to read it, and says never to quote a rendered row."""
    prompt = build_system_prompt(corpus="budget", tier="standard")
    assert "text_labelled" in prompt
    idx = prompt.index("text_labelled")
    window = prompt[idx - 200: idx + 900]
    assert "label" in window.lower()
    assert "never" in window.lower() and "quote" in window.lower()
```

Run: `uv run pytest tests/test_harness_prompt.py -k text_labelled -v`
Expected: FAIL (`'text_labelled' not in prompt`).

- [ ] **Step 6: Add the paragraph to `harness/system-prompt.md`**

Directly after the bullet that ends `*"per the FY 2025 Actual column of the FY 2027 Baseline…"*.` under `### The 3-year structure of per-agency tables`, insert:

```markdown
**Table passages carry a `text_labelled` field.** When a `retrieve` result
is a table, it has a second field beside `text` in which every cell is
written as `column-header: value` — for example
`General Fund | FY 2024 ACTUAL: 7,699,669,300 | FY 2026 APPROVED: 8,287,685,600`.
Read the figure from its label, never from its position in a row: the
raw `text` has columns that shift and cells that hold two numbers. A cell
rendered as `X and Y (two values in one cell — read with care)` is one
the extractor merged; say which of the two you used and why. Footnote
markers appear as `[3/]` after the figure. `text_labelled` is for
reading only — `cite` quotes must come from `text`, and you never quote a
table row (see the cite rules).
```

- [ ] **Step 7: Run the prompt suite**

Run: `uv run pytest tests/test_harness_prompt.py tests/test_system_prompt_lifecycle.py tests/test_new_doc_types.py -v`
Expected: all PASS.

- [ ] **Step 8: Commit**

```bash
git add harness/tools.py harness/system-prompt.md tests/test_harness_tools.py tests/test_harness_prompt.py
git commit -m "feat(tables): retrieve sends text_labelled beside text for table chunks; prompt says to read the label (phase A)"
```

---

### Task 3: Measure headerless table chunks outside D1 (decides §5 rule 5)

**Files:**
- Create: `scripts/count_headerless_tables.py`
- Create: `docs/superpowers/investigations/2026-09-01-headerless-tables-count.md`

**Interfaces:**
- Consumes: `chunking.table_text.find_header`, `has_ladder_marker`, `OPERATING_TABLE_DOC_TYPES`; `store.chunk_store.ChunkStore`.

- [ ] **Step 1: Write the script**

```python
"""How many table chunks OUTSIDE the operating-table scope have no
detectable year header? Spec §5 rule 5: the continuation-header borrow is
built only if this number justifies a live store read on every search.

Read-only. Run:  JLBC_DATA_DIR=data/insight-data uv run python scripts/count_headerless_tables.py
"""
from __future__ import annotations

from collections import Counter

from chunking.table_text import OPERATING_TABLE_DOC_TYPES, find_header, has_ladder_marker
from store.chunk_store import ChunkStore


def main() -> int:
    store = ChunkStore(create=False)
    rows = store.scan("budget_chunks", ["chunk_id", "doc_type", "fiscal_year", "text"], where="is_table = true")
    in_scope = out_scope = 0
    headerless_out = Counter()
    for r in rows:
        text = r["text"] or ""
        table_rows = [line.split("\t") for line in text.split("\n") if "\t" in line]
        has_header = find_header(table_rows) is not None
        scoped = r["doc_type"] in OPERATING_TABLE_DOC_TYPES and has_ladder_marker(text)
        if scoped:
            in_scope += 1
        else:
            out_scope += 1
            if not has_header and table_rows:
                headerless_out[r["doc_type"]] += 1
    print(f"table chunks: {len(rows)}  in-scope: {in_scope}  out-of-scope: {out_scope}")
    print(f"out-of-scope with tab rows and NO header: {sum(headerless_out.values())}")
    for doc_type, n in headerless_out.most_common():
        print(f"  {doc_type:24s} {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run it**

Run: `JLBC_DATA_DIR=data/insight-data uv run python scripts/count_headerless_tables.py`
Expected: a count per doc type. Paste the whole output into the investigation file.

- [ ] **Step 3: Record the decision**

`docs/superpowers/investigations/2026-09-01-headerless-tables-count.md`:

```markdown
---
status: shipped
---
# Headerless table chunks outside the operating-table scope (spec §5 rule 5)

Run 2026-09-01 with `scripts/count_headerless_tables.py`:

```
<paste output>
```

**Decision:** <one of>
- The count is under 1,000 and spread across doc types whose tables have
  no year columns anyway (fund lists, footnote tables) → rule 5 is
  DROPPED. Those chunks fall to today's plain text.
- The count is dominated by continuations of year-columned tables in one
  doc type → rule 5 is built as a follow-up task with its own spec line,
  not in this plan.
```

Pick the branch the numbers support, delete the other.

- [ ] **Step 4: Commit**

```bash
git add scripts/count_headerless_tables.py docs/superpowers/investigations/2026-09-01-headerless-tables-count.md
git commit -m "docs(tables): count headerless table chunks outside D1 — decides spec §5 rule 5"
```

---

### Task 4: Phase A gates — false-link check, STATUS, and the G-OT4 offer

**Files:**
- Modify: `STATUS.md` (phase-summary row + a dated section)
- Modify: `docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md` (status line)

- [ ] **Step 1: Run the false-link check with the rendering as the pool**

Read the header of `eval/false_link_check.py` for its CLI. Run it once as today, then once with a pool built from `render_labelled(text)` for table chunks. If the script has no pool-override flag, add one:

```python
parser.add_argument("--labelled-pool", action="store_true",
                    help="use render_labelled(text) as the pool text for table chunks (spec §5)")
```

and where the pool text is taken from a chunk:

```python
from retrieval.table_view import render_labelled
...
pool_text = chunk.get("text") or ""
if args.labelled_pool and chunk.get("is_table"):
    pool_text = render_labelled(pool_text) or pool_text
```

Run both and record the per-profile false-link rates side by side. Expected: no profile moves by more than its own noise (the memo's rates are per digit profile; a change under 1 point on any profile is noise).

- [ ] **Step 2: Offer G-OT4, do not run it**

Tell Destin: the phase A run costs ~$0.10 (`uv run python -m eval.run_agent_eval --queries lk-asu-operating-fy2026 lk-dps-operating-fy2026 lk-adc-total-fy2026 lk-tou-tourism-fy2026 lk-min-operating-fy2025 cm-supplementals-fy2026 cm-university-funding-dr --note "G-OT4 after phase A"`) plus a same-day control on the commit before Task 2. Run only if he says yes; record both run directories in STATUS.

- [ ] **Step 3: STATUS and spec status**

Add a phase-summary row:

```markdown
| Operating tables — **phase A** (labelled cells in `retrieve`) | ✓ Shipped (2026-09-xx) | `text_labelled` beside `text`; false-link rate unchanged (<numbers>); G-OT4 <run / offered>. Phase B (text-layer rebuild) not started. See the section below |
```

and a section `## Operating tables — phase A shipped (2026-09-xx)` with: what the model now sees (one rendered example), the false-link numbers, the rule-5 decision from Task 3, and "phase B pending the section-path repair".

Change the spec's first line to `**Status:** approved 2026-08-26 (Destin); phase A shipped 2026-09-xx; phase B in progress.`

- [ ] **Step 4: Commit**

```bash
git add STATUS.md docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md eval/false_link_check.py
git commit -m "docs(tables): phase A shipped — false-link check unchanged, STATUS updated"
```

---

## Phase B — the text-layer rebuild

### Task 5: The gate, its calibration on the stored corpus, and the shared repair helpers

**Precondition check (spec D7).** Run:

```bash
ls chunking/repair_section_paths.py ingest/extract_dirs.py
```

Both must exist. If either is missing, **stop** and report that the section-path plan has not landed; nothing in phase B can start.

**Files:**
- Create: `chunking/table_gate.py`
- Create: `chunking/repair_common.py`; Modify: `chunking/repair_section_paths.py` (import the moved helpers)
- Create: `chunking/repair_tables.py` (calibration only, for now)
- Test: `tests/test_table_gate.py`; run `tests/test_repair_section_paths.py` unchanged

**Interfaces:**
- Produces:
  - `table_gate.reconcile(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> GateResult`; `table_gate.is_check_label(label: str) -> bool`
  - `GateResult(passed: bool, checks: list[Check], reason: str)`; `Check(label, column, expected, actual, rule)` with `.ok`
  - `table_gate.count_figure_rows(rows, *, first_col=1) -> int`, `table_gate.has_merged_cell(rows, *, first_col=1) -> bool`, `table_gate.has_fused_marker(rows, *, first_col=1) -> bool`
  - `repair_common.atomic_write_json(path, payload)`, `in_list(ids) -> str`, `all_columns() -> list[str]`, `reversal_stamp() -> str`, `ChunkStoreLike`, `EmbedderLike`, `default_snapshot_and_verify() -> str | None`
  - `repair_tables.calibrate(store, table="budget_chunks") -> dict[int, dict[str, int]]`

- [ ] **Step 1: Write the failing gate tests**

`tests/test_table_gate.py`:

```python
"""chunking/table_gate.py — spec §4. A rebuilt table is accepted only when
its published subtotals equal the sum of their rows in every column."""
from __future__ import annotations

from chunking.table_gate import count_figure_rows, has_fused_marker, has_merged_cell, reconcile


def _t(*lines: str) -> list[list[str]]:
    return [line.split("\t") for line in lines]


AHCCCS = _t(
    "OPERATING BUDGET\t\t",
    "Full Time Equivalent Positions\t2,358.3\t2,459.3",
    "Personal Services\t100\t200",
    "Equipment\t50\t50",
    "OPERATING SUBTOTAL\t150\t250 1/2/",
    "SPECIAL LINE ITEMS\t\t",
    "Administration\t\t",
    "DES Eligibility\t10\t20 3/",
    "Medicaid Services 5/6/7/\t\t",
    "Traditional Medicaid Services\t40\t30",
    "AGENCY TOTAL\t200\t300",
    "FUND SOURCES\t\t",
    "General Fund\t120\t180",
    "Other Appropriated Funds\t\t",
    "Budget Neutrality Compliance Fund\t30\t20",
    "SUBTOTAL - Other Appropriated Funds\t30\t20",
    "SUBTOTAL - Appropriated Funds\t150\t200",
    "Expenditure Authority Funds\t\t",
    "AHCCCS Fund\t50\t100",
    "SUBTOTAL - Expenditure Authority Funds\t50\t100",
    "SUBTOTAL - Appropriated/Expenditure Authority Funds\t200\t300",
    "Other Non-Appropriated Funds\t5\t5",
    "Federal Funds\t(5)\t10",
    "TOTAL - ALL SOURCES\t200\t315",
)


def test_reconciling_three_section_ladder_passes():
    result = reconcile(AHCCCS)
    assert result.passed, [c for c in result.checks if not c.ok]
    rules = {c.label for c in result.checks}
    assert "TOTAL - ALL SOURCES" in rules and "AGENCY TOTAL = SUBTOTAL - APPROPRIATED/EXPENDITURE AUTHORITY FUNDS" in rules


def test_one_wrong_digit_fails_and_names_the_row_and_column():
    bad = [list(r) for r in AHCCCS]
    bad[3][2] = "51"  # Equipment, column 2
    result = reconcile(bad)
    assert not result.passed
    failed = [c for c in result.checks if not c.ok]
    assert failed[0].label == "OPERATING SUBTOTAL" and failed[0].column == 1
    assert failed[0].expected == 251 and failed[0].actual == 250   # the nearest span, named


def test_fy2006_four_columns_no_operating_subtotal_variant_labels():
    table = _t(
        "OPERATING BUDGET\t\t\t\t",
        "Full Time Equivalent Positions\t186.0\t186.0\t186.0\t186.0",
        "Personal Services\t3,537,100\t4,865,100\t4,947,800\t4,865,100",
        "Employee Related Expenditures\t740,400\t1,131,200\t1,291,900\t1,153,500",
        "AGENCY TOTAL\t4,277,500\t5,996,300\t6,239,7001/\t6,018,600 1/",
        "FUND SOURCES\t\t\t\t",
        "Other Funds\t\t\t\t",
        "Arizona Exposition and State Fair Fund\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
        "SUBTOTAL - Other Funds\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
        "SUBTOTAL - Appropriated Funds\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
        "TOTAL - ALL SOURCES\t4,277,500\t5,996,300\t6,239,700\t6,018,600",
    )
    result = reconcile(table)
    assert result.passed, [c for c in result.checks if not c.ok]


def test_fte_row_is_excluded_from_every_sum():
    table = _t("Full Time Equivalent Positions\t10.0", "Personal Services\t5", "OPERATING SUBTOTAL\t5")
    assert reconcile(table).passed


def test_accounting_negative_sums():
    table = _t("A\t(100)", "B\t300", "OPERATING SUBTOTAL\t200")
    assert reconcile(table).passed


def test_empty_body_cell_is_zero_and_blank_check_cell_is_skipped():
    table = _t("A\t100\t", "B\t\t50", "OPERATING SUBTOTAL\t100\t50", "Federal Funds\t1\t", "TOTAL - ALL SOURCES\t101\t")
    result = reconcile(table)
    assert result.passed
    assert all(c.column == 0 or c.label != "TOTAL - ALL SOURCES" for c in result.checks)


def test_no_check_row_cannot_be_verified():
    result = reconcile(_t("A\t1", "B\t2"))
    assert not result.passed and result.reason == "no check row"


def test_unrecognised_check_label_uses_the_generic_rule():
    assert reconcile(_t("A\t1", "B\t2", "SUBTOTAL - Widgets\t3")).passed
    assert not reconcile(_t("A\t1", "B\t2", "SUBTOTAL - Widgets\t4")).passed


def test_adc_nested_subtotals_inside_the_operating_block():
    """FY2023 ADC: `Personal Services Subtotal` and `Other Operating
    Expenditures Subtotal` sit INSIDE the operating block, and
    `OPERATING SUBTOTAL` is the sum of those two plus the loose rows."""
    table = _t(
        "OPERATING BUDGET\t",
        "Correctional Officer Personal Services\t100",
        "All Other Personal Services\t50",
        "Personal Services Subtotal\t150",
        "Employee Related Expenditures\t30",
        "Other Operating Expenditures\t",
        "Food\t10",
        "Equipment\t5",
        "Other Operating Expenditures Subtotal\t15",
        "OPERATING SUBTOTAL\t195",
        "AGENCY TOTAL\t195",
    )
    result = reconcile(table)
    assert result.passed, [c for c in result.checks if not c.ok]


def test_row_counting_helpers():
    minerU = _t("\tFY 2024\tFY 2025", "A\t1\t2", "SUBTOTAL - X SUBTOTAL - Y\t1 2\t2 4", "G\t\t")
    assert count_figure_rows(minerU) == 2          # the header row's years are not figures
    assert has_merged_cell(minerU)
    assert not has_merged_cell(_t("A\t1\t2"))
    assert has_fused_marker(_t("A\t99,294,5003/"))
    assert not has_fused_marker(_t("A\t99,294,500 3/"))
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_table_gate.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'chunking.table_gate'`

- [ ] **Step 3: Write `chunking/table_gate.py`**

```python
"""The reconciliation gate (spec §4): a rebuilt operating table is accepted
only when every published subtotal equals the sum of its rows, in every
year column, to the dollar. JLBC prints whole dollars in hundreds, so
there is no rounding to forgive.

The rule is one rule, not a list of labels: a check row equals the sum of
the ITEMS since some earlier boundary (the table start, a group heading,
or a previous check row), where an item is a body row not already covered
by an intermediate check row, or that intermediate check row itself. The
candidates are tried nearest-boundary first; the first one that equals
the printed figure wins and records which rows it covered. This is what
makes `SUBTOTAL - Appropriated Funds` = General Fund + `SUBTOTAL - Other
Appropriated Funds`, `AGENCY TOTAL` = `OPERATING SUBTOTAL` + the special
line items, and the ADC page's `Personal Services Subtotal` all reconcile
without a label table.

A wrong digit cannot pass: the candidates are a handful of specific sums,
and a check row that equals none of them fails with the nearest one named.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from chunking.table_text import figure_tokens, normalise_label, split_figure_marker

_FTE_RE = re.compile(r"FULL TIME EQUIVALENT|\bFTE\b")
# Any label carrying the word TOTAL or SUBTOTAL: `OPERATING SUBTOTAL`,
# `AGENCY TOTAL`, `PROGRAM TOTAL`, `SUBTOTAL - …`, `TOTAL - ALL SOURCES`.
_CHECK_RE = re.compile(r"\b(?:SUB)?TOTAL\b")
_AGENCY_TOTALS = ("AGENCY TOTAL", "PROGRAM TOTAL")
_APPROP = "SUBTOTAL - APPROPRIATED FUNDS"
_APPROP_EA = "SUBTOTAL - APPROPRIATED/EXPENDITURE AUTHORITY FUNDS"


@dataclass(frozen=True)
class Check:
    label: str
    column: int
    expected: Decimal
    actual: Decimal
    rule: str

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


@dataclass
class GateResult:
    passed: bool
    checks: list[Check] = field(default_factory=list)
    reason: str = ""


def is_check_label(label: str) -> bool:
    """A normalised label naming a subtotal or total row."""
    return _CHECK_RE.search(label) is not None


def parse_figure(cell: str) -> Decimal | None:
    """The first figure in a cell as a Decimal; `(1,234)` is negative;
    `-` is zero; no figure is None."""
    tokens = figure_tokens(cell)
    if not tokens:
        return Decimal(0) if cell.strip() == "-" else None
    tok = tokens[0]
    neg = tok.startswith("(") and tok.endswith(")")
    value = Decimal(tok.strip("()$").replace(",", ""))
    return -value if neg else value


@dataclass
class _Line:
    label: str
    cls: str                      # "fte" | "check" | "heading" | "body"
    values: list[Decimal | None]


def _classify(rows: Sequence[Sequence[str]], first_col: int) -> list[_Line]:
    ncols = max((len(r) for r in rows), default=first_col) - first_col
    out: list[_Line] = []
    for cells in rows:
        label = normalise_label(" ".join(c for c in cells[:first_col]))
        values = [parse_figure(c) for c in cells[first_col:]]
        values += [None] * (ncols - len(values))
        if _FTE_RE.search(label):
            cls = "fte"
        elif _CHECK_RE.search(label):
            cls = "check"
        elif all(v is None for v in values):
            cls = "heading"
        else:
            cls = "body"
        out.append(_Line(label, cls, values))
    return out


def reconcile(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> GateResult:
    lines = _classify(rows, first_col)
    if not any(l.cls == "check" for l in lines):
        return GateResult(False, [], "no check row")
    ncols = len(lines[0].values) if lines else 0
    checks: list[Check] = []
    for c in range(ncols):
        if not any(l.values[c] is not None for l in lines):
            continue  # a column nobody printed in
        checks.extend(_reconcile_column(lines, c))
    passed = bool(checks) and all(ch.ok for ch in checks)
    return GateResult(passed, checks, "" if passed else "arithmetic")


@dataclass
class _Item:
    value: Decimal
    is_check: bool
    covered_from: int | None = None   # for a check item: index of the first item it covers


def _reconcile_column(lines: list[_Line], c: int) -> list[Check]:
    checks: list[Check] = []
    items: list[_Item] = []
    boundaries: list[int] = [0]           # candidate span starts, nearest last
    seen: dict[str, Decimal] = {}

    for line in lines:
        v = line.values[c]
        if line.cls == "fte":
            continue
        if line.cls == "heading":
            boundaries.append(len(items))
            continue
        if line.cls == "body":
            items.append(_Item(v if v is not None else Decimal(0), False))
            continue
        # A check row. A blank check cell in this column is skipped.
        if v is None:
            boundaries.append(len(items))
            continue
        candidates = [(b, _span_total(items, b)) for b in sorted(set(boundaries), reverse=True)]
        hit = next((b for b, total in candidates if total == v), None)
        nearest_expected = candidates[0][1] if candidates else Decimal(0)
        checks.append(Check(line.label, c, v if hit is not None else nearest_expected, v,
                            "span" if hit is not None else "nearest span"))
        items.append(_Item(v, True, covered_from=hit))
        boundaries.append(len(items))
        seen[line.label] = v

    # Cross-check (spec §4): the agency total equals the appropriated-level subtotal.
    approp_key = _APPROP_EA if _APPROP_EA in seen else _APPROP
    agency_key = next((k for k in _AGENCY_TOTALS if k in seen), None)
    if agency_key and approp_key in seen:
        checks.append(Check(f"{agency_key} = {approp_key}", c, seen[approp_key], seen[agency_key], "cross-check"))
    return checks


def _span_total(items: list[_Item], start: int) -> Decimal:
    """Sum of the items from `start`, where a check item replaces the items
    it covers (they are skipped, it is added)."""
    total = Decimal(0)
    i = start
    # Walk forward; when a later check covers from an index >= start, the
    # items it covers are skipped. Build the skip set first.
    skip: set[int] = set()
    for i, it in enumerate(items[start:], start=start):
        if it.is_check and it.covered_from is not None and it.covered_from >= start:
            skip.update(range(it.covered_from, i))
    for i, it in enumerate(items[start:], start=start):
        if i not in skip:
            total += it.value
    return total


def count_figure_rows(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> int:
    """Rows carrying at least one figure."""
    return sum(1 for cells in rows if any(figure_tokens(c) for c in cells[first_col:]))


def has_merged_cell(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> bool:
    return any(len(figure_tokens(c)) >= 2 for cells in rows for c in cells[first_col:])


def has_fused_marker(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> bool:
    return any(
        split_figure_marker(tok)[1] is not None
        for cells in rows for c in cells[first_col:] for tok in c.split()
    )
```

- [ ] **Step 4: Run the gate tests**

Run: `uv run pytest tests/test_table_gate.py -v`
Expected: all PASS. If `test_reconciling_three_section_ladder_passes` fails, print `[(c.label, c.column, c.expected, c.actual, c.rule) for c in result.checks]` and fix the rule, not the fixture — the fixture's arithmetic is checked by hand (column 2: operating 250 + special items 20 + 30 = agency total 300; appropriated 200 + expenditure authority 100 = 300; 300 + 5 + 10 = 315). The gate and reader code in this plan were run against 206 real agency pages on 2026-09-01 (199 rebuilt, one printed page whose `AGENCY TOTAL` genuinely does not add up, one anchor match at 78%).

- [ ] **Step 5: Move the shared repair helpers into `chunking/repair_common.py`**

Create `chunking/repair_common.py` with the helpers `repair_section_paths.py` defines as `_atomic_write_json`, `_in_list`, `_all_columns` (+ its `_ALL_COLUMNS_CACHE`), `_reversal_stamp`, the `ChunkStoreLike` and `EmbedderLike` protocols, and a `default_snapshot_and_verify` that wraps `identity.relabel._default_snapshot_and_verify`. Copy each function body verbatim from `repair_section_paths.py`, drop the leading underscore, and keep its docstring. Then in `repair_section_paths.py` delete those definitions and add:

```python
# WHY: the operating-table repair (chunking/repair_tables.py) needs the same
# helpers; one copy each, imported by both passes.
from chunking.repair_common import (
    ChunkStoreLike,
    EmbedderLike,
    all_columns as _all_columns,
    atomic_write_json as _atomic_write_json,
    in_list as _in_list,
    reversal_stamp as _reversal_stamp,
)
```

(The aliases keep every existing call site in that module unchanged.)

Run: `uv run pytest tests/test_repair_section_paths.py -v`
Expected: all PASS, unchanged count.

- [ ] **Step 6: Write the calibration entry point in `chunking/repair_tables.py`**

```python
"""The one-time repair of JLBC agency operating tables (spec §6), and the
gate calibration that precedes it (spec §4.1).

    JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --calibrate
    JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables            # dry run
    JLBC_DATA_DIR=<copy>            uv run python -m chunking.repair_tables --apply

Nothing here writes without `--apply`, and `--apply` writes only under
the ingest lock after a CRC-verified snapshot.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from typing import Any, Callable, Mapping

from chunking.table_gate import has_fused_marker, has_merged_cell, reconcile
from chunking.table_text import OPERATING_TABLE_DOC_TYPES, has_ladder_marker
from chunking.repair_common import ChunkStoreLike

PLAN_COLUMNS = ["chunk_id", "doc_id", "fiscal_year", "doc_type", "page", "section_path", "text", "table_html"]


def in_scope(row: Mapping[str, Any]) -> bool:
    """Spec D1."""
    return bool(row.get("is_table")) and row.get("doc_type") in OPERATING_TABLE_DOC_TYPES and has_ladder_marker(row.get("text") or "")


def table_rows(text: str) -> list[list[str]]:
    """The tab-joined rows of a stored chunk text (line 0 and a caption have no tabs)."""
    return [line.split("\t") for line in text.split("\n") if "\t" in line]


def calibrate(store: ChunkStoreLike, table: str = "budget_chunks") -> dict[int, dict[str, int]]:
    """Spec §4.1: run the gate over the tables MinerU already read cleanly
    (no merged cell, no fused marker) exactly as stored. Every failure
    here is the RULE's, so this is run before any rebuild code exists.
    Returns {fiscal_year: {"clean": n, "passed": n}}."""
    rows = store.scan(table, ["chunk_id", "doc_type", "fiscal_year", "is_table", "text"],
                      where="is_table = true")
    per_year: dict[int, dict[str, int]] = defaultdict(lambda: {"clean": 0, "passed": 0})
    for r in rows:
        if not in_scope(r):
            continue
        cells = table_rows(r["text"])
        if has_merged_cell(cells) or has_fused_marker(cells):
            continue
        year = int(r["fiscal_year"] or 0)
        per_year[year]["clean"] += 1
        if reconcile(cells).passed:
            per_year[year]["passed"] += 1
    return dict(per_year)


def _print_calibration(per_year: Mapping[int, Mapping[str, int]]) -> None:
    total_clean = sum(v["clean"] for v in per_year.values())
    total_pass = sum(v["passed"] for v in per_year.values())
    print(f"{'year':>6} {'clean':>7} {'passed':>7} {'rate':>6}")
    for year in sorted(per_year):
        v = per_year[year]
        rate = v["passed"] / v["clean"] if v["clean"] else 0.0
        print(f"{year:>6} {v['clean']:>7} {v['passed']:>7} {rate:>6.1%}")
    print(f"{'all':>6} {total_clean:>7} {total_pass:>7} {(total_pass / total_clean if total_clean else 0):>6.1%}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default="budget_chunks", choices=("budget_chunks",))
    parser.add_argument("--calibrate", action="store_true", help="spec §4.1: gate the stored clean tables, write nothing")
    args = parser.parse_args(argv)
    from store.chunk_store import ChunkStore
    store = ChunkStore(create=False)
    if args.calibrate:
        _print_calibration(calibrate(store, args.table))
        return 0
    parser.error("only --calibrate exists yet; the dry run arrives with Task 8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 7: Run the calibration on the live corpus (read-only)**

Run: `JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --calibrate`
Expected: a per-year table; roughly 2,000–2,500 clean tables. **This is G-OT0.** If the overall rate is under 95%, pull 10 failing chunk ids (add a temporary print of the first failing `Check` per table), read them, and fix the rule in `table_gate.py` — never loosen it to tolerance. Repeat until the clean tables pass or every remaining failure is a genuine printed inconsistency (record those ids).

Record the final table in `docs/superpowers/investigations/2026-09-01-operating-table-gate-calibration.md` with `status: shipped` frontmatter, the command, the output, and the list of any rule changes made.

- [ ] **Step 8: Commit**

```bash
git add chunking/table_gate.py chunking/repair_common.py chunking/repair_section_paths.py chunking/repair_tables.py tests/test_table_gate.py docs/superpowers/investigations/2026-09-01-operating-table-gate-calibration.md
git commit -m "feat(tables): reconciliation gate, calibrated on the stored clean tables (G-OT0); shared repair helpers"
```

---

### Task 6: The text-layer reader

**Files:**
- Create: `chunking/readers/text_layer_table.py`
- Test: `tests/test_text_layer_table.py`

**Interfaces:**
- Consumes: `chunking.table_text.*`, `chunking.table_gate.reconcile/is_check_label`, `chunking.readers.types.Table/Row/Cell`, `MinerUReader._parse_html_table`
- Produces:
  - `RefineOutcome(table: Table | None, reason: str, anchor_match: float)`
  - `refine_operating_table(table: Table, pdf: fitz.Document) -> RefineOutcome`
  - `render_html(rows: Sequence[Sequence[str]]) -> str`
  - `ANCHOR_MIN_MATCH = 0.8`, `MAX_FORWARD_PAGES = 2`

- [ ] **Step 1: Write the failing reader tests**

`tests/test_text_layer_table.py`:

```python
"""chunking/readers/text_layer_table.py — spec §3.1. Every page here is
built in the test with PyMuPDF at real coordinates (the AHCCCS FY2026
page: label at x=52, three columns centred at x=305/404/503, figures
right-aligned to x=334/433/532, 9-pt text, markers 6-pt at x=534)."""
from __future__ import annotations

from pathlib import Path

import fitz
import pytest

from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.text_layer_table import (
    ANCHOR_MIN_MATCH,
    refine_operating_table,
    render_html,
)

CENTRES = (305.0, 404.0, 503.0)
RIGHTS = (334.0, 433.0, 532.0)


class PageBuilder:
    """Places text at coordinates on a US-letter page."""

    def __init__(self, doc: fitz.Document):
        self.page = doc.new_page(width=612, height=792)
        self.y = 60.0

    def centred(self, y: float, text: str, cx: float, size: float = 9) -> None:
        w = fitz.get_text_length(text, fontsize=size)
        self.page.insert_text((cx - w / 2, y), text, fontsize=size)

    def right(self, y: float, text: str, rx: float, size: float = 9) -> None:
        w = fitz.get_text_length(text, fontsize=size)
        self.page.insert_text((rx - w, y), text, fontsize=size)

    def header(self, years=("FY 2024", "FY 2025", "FY 2026"), kinds=("ACTUAL", "ESTIMATE", "APPROVED")) -> None:
        for cx, yr in zip(CENTRES, years):
            self.centred(self.y, yr, cx)
        self.y += 12
        for cx, k in zip(CENTRES, kinds):
            self.centred(self.y, k, cx)
        self.y += 24

    def row(self, label: str, *figures: str, x0: float = 52, marker: str | None = None) -> None:
        self.page.insert_text((x0, self.y), label, fontsize=9)
        for rx, fig in zip(RIGHTS, figures):
            if fig:
                self.right(self.y, fig, rx)
        if marker:
            # 6-pt, one point below the baseline, right of the last column — as printed.
            self.page.insert_text((534, self.y + 1), marker, fontsize=6)
        self.y += 11.5

    def prose(self, text: str) -> None:
        self.page.insert_text((52, self.y), text, fontsize=9)
        self.y += 12


def _minerU(html: str, page: int = 1):
    return MinerUReader._parse_html_table(html, page=page, bbox=None)


def _cells(table) -> list[list[str]]:
    return [[c.text for c in r.cells] for r in table.rows]


CLEAN_HTML = (
    "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
    "<tr><td>OPERATING BUDGET</td><td></td><td></td><td></td></tr>"
    "<tr><td>Full Time Equivalent Positions</td><td>10.0</td><td>10.0</td><td>12.0</td></tr>"
    "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
    "<tr><td>Equipment</td><td>50</td><td>50</td><td>50</td></tr>"
    "<tr><td>OPERATING SUBTOTAL</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>AGENCY TOTAL</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
    "<tr><td>General Fund</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>SUBTOTAL - Appropriated Funds</td><td>150</td><td>250</td><td>350</td></tr>"
    "<tr><td>TOTAL - ALL SOURCES</td><td>150</td><td>250</td><td>350</td></tr></table>"
)


def _clean_page(b: PageBuilder) -> None:
    b.header()
    b.row("OPERATING BUDGET")
    b.row("Full Time Equivalent Positions", "10.0", "10.0", "12.0")
    b.row("Personal Services", "100", "200", "300")
    b.row("Equipment", "50", "50", "50")
    b.row("OPERATING SUBTOTAL", "150", "250", "350", x0=61)
    b.row("AGENCY TOTAL", "150", "250", "350")
    b.row("FUND SOURCES")
    b.row("General Fund", "150", "250", "350")
    b.row("SUBTOTAL - Appropriated Funds", "150", "250", "350", x0=61)
    b.row("TOTAL - ALL SOURCES", "150", "250", "350")


def test_clean_table_round_trips_with_header_row_first():
    doc = fitz.open()
    _clean_page(PageBuilder(doc))
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[0] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]
    assert cells[3] == ["Personal Services", "100", "200", "300"]
    assert cells[1] == ["OPERATING BUDGET", "", "", ""]
    assert out.table.page == 1 and out.table.html.startswith("<table><tr><td></td><td>FY 2024 ACTUAL")


def test_two_merged_rows_come_back_as_two_rows():
    """The defect itself: MinerU fused two printed rows into one cell."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b.row("FUND SOURCES")
    b.row("General Fund", "60", "120", "180")
    b.row("Other Appropriated Funds")
    b.row("Some Fund", "40", "80", "120")
    b.row("SUBTOTAL - Other Appropriated Funds", "40", "80", "120", x0=61)
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>60</td><td>120</td><td>180</td></tr>"
        "<tr><td>Other Appropriated Funds</td><td></td><td></td><td></td></tr>"
        "<tr><td>Some Fund</td><td>40</td><td>80</td><td>120</td></tr>"
        "<tr><td>SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds</td><td>40 100</td><td>80 200</td><td>120 300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert "SUBTOTAL - Other Appropriated Funds" in labels and "SUBTOTAL - Appropriated Funds" in labels
    from chunking.table_gate import has_merged_cell
    assert not has_merged_cell(_cells(out.table)[1:])


def test_wrapped_label_is_appended_to_its_row():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Tobacco Products Tax Fund - Proposition 204 Protection", "10", "20", "30")
    b.row("Account", x0=61)
    b.row("SUBTOTAL - Other Appropriated Funds", "10", "20", "30", x0=61)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Tobacco Products Tax Fund - Proposition 204 Protection</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>Account SUBTOTAL - Other Appropriated Funds</td><td>10</td><td>20</td><td>30</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert "Tobacco Products Tax Fund - Proposition 204 Protection Account" in labels


def test_footnote_markers_separate_word_and_fused_word():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("DES Eligibility", "116,083,200", "98,906,500", "99,294,500", marker="3/")
    b.row("Personal Services", "100", "100", "100")
    b.page.insert_text((52, b.y), "OPERATING SUBTOTAL", fontsize=9)
    b.right(b.y, "116,083,300", 334.0)
    b.right(b.y, "98,906,600", 433.0)
    b.right(b.y, "99,294,6001/", 532.0)   # the FY2006 shape: marker fused in the text layer
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>DES Eligibility</td><td>116,083,200</td><td>98,906,500</td><td>99,294,5003/</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>100</td><td>100</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>116,083,300</td><td>98,906,600</td><td>99,294,6001/</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert cells[1][3] == "99,294,500 [3/]"
    assert cells[3][3] == "99,294,600 [1/]"


def test_minerU_table_whose_rows_span_two_pages_is_followed_forward():
    """MinerU merged both pages into its page-1 block (the AHCCCS shape)."""
    doc = fitz.open()
    b1 = PageBuilder(doc)
    b1.header()
    b1.row("Personal Services", "100", "200", "300")
    b1.row("OPERATING SUBTOTAL", "100", "200", "300", x0=61)
    b1.row("AGENCY TOTAL", "100", "200", "300")
    b2 = PageBuilder(doc)
    b2.header()
    b2.row("FUND SOURCES")
    b2.row("General Fund", "100", "200", "300")
    b2.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b2.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>AGENCY TOTAL</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html, page=1), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert labels[-1] == "TOTAL - ALL SOURCES" and "AGENCY TOTAL" in labels
    assert out.table.page == 1 and out.table.pages == [1]   # D4: provenance untouched


def test_continuation_without_its_own_header_borrows_the_previous_page():
    doc = fitz.open()
    b1 = PageBuilder(doc)
    b1.header()
    b1.row("Personal Services", "100", "200", "300")
    b2 = PageBuilder(doc)          # no header printed on page 2
    b2.row("FUND SOURCES")
    b2.row("General Fund", "100", "200", "300")
    b2.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b2.row("TOTAL - ALL SOURCES", "100", "200", "300")
    html = (
        "<table><tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>100</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html, page=2), doc)
    assert out.table is not None, out.reason
    assert _cells(out.table)[0] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]


def test_sub_table_and_prose_outside_the_anchor_region_are_ignored():
    doc = fitz.open()
    b = PageBuilder(doc)
    _clean_page(b)
    b.prose("AGENCY DESCRIPTION — The agency operates on a health maintenance model.")
    b.y += 10
    b.header(years=("FY 2023", "FY 2024", "FY 2026"), kinds=("Actual", "Actual", "Approved"))
    b.row("PERFORMANCE MEASURES")
    b.row("Fair attendance", "1,067,500", "1,060,086", "1,100,000")
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is not None, out.reason
    labels = [r[0] for r in _cells(out.table)]
    assert "Fair attendance" not in labels and not any("AGENCY DESCRIPTION" in l for l in labels)


def test_accounting_negative_and_empty_column():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("A", "(100)", "", "300")
    b.row("B", "300", "", "0")
    b.row("OPERATING SUBTOTAL", "200", "", "300", x0=61)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>A</td><td>(100)</td><td></td><td>300</td></tr><tr><td>B</td><td>300</td><td></td><td>0</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>200</td><td></td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    assert _cells(out.table)[1] == ["A", "(100)", "", "300"]


def test_scanned_page_and_weak_anchor_return_none_with_a_reason():
    doc = fitz.open()
    doc.new_page()                                  # no words at all
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is None and out.reason == "no text layer"

    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Something Else Entirely", "1", "2", "3")
    out = refine_operating_table(_minerU(CLEAN_HTML), doc)
    assert out.table is None and out.reason.startswith("anchor match")
    assert out.anchor_match < ANCHOR_MIN_MATCH


def test_gate_failure_returns_none():
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("OPERATING SUBTOTAL", "101", "200", "300", x0=61)   # printed page that does not add up
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>101</td><td>200</td><td>300</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is None and out.reason == "arithmetic"


def test_label_that_wrapped_before_its_figures_is_one_row():
    """FY2006 DHS: `SUBTOTAL - Appropriated/Expenditure` on one line, the
    figures on the indented `Authority Funds` line under it."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("General Fund", "100", "200", "300")
    b.row("SUBTOTAL - Appropriated Funds", "100", "200", "300", x0=61)
    b.row("Expenditure Authority Funds")
    b.row("Federal Title XIX Funds", "10", "20", "30")
    b.row("SUBTOTAL - Expenditure Authority Funds", "10", "20", "30", x0=61)
    b.row("SUBTOTAL - Appropriated/Expenditure", x0=61)
    b.row("Authority Funds", "110", "220", "330", x0=69)
    b.row("TOTAL - ALL SOURCES", "110", "220", "330")
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>General Fund</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated Funds</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>Expenditure Authority Funds</td><td></td><td></td><td></td></tr>"
        "<tr><td>Federal Title XIX Funds</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>SUBTOTAL - Expenditure Authority Funds</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>SUBTOTAL - Appropriated/Expenditure Authority Funds</td><td>110</td><td>220</td><td>330</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>110</td><td>220</td><td>330</td></tr></table>"
    )
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is not None, out.reason
    cells = _cells(out.table)
    assert ["SUBTOTAL - Appropriated/Expenditure Authority Funds", "110", "220", "330"] in cells


def test_last_minerU_row_must_be_found_on_the_page():
    """A summary table's lone `Total` further down the page must not stand
    in for `TOTAL - ALL SOURCES`; with the real last row missing the end of
    the region is a guess and the table is refused."""
    doc = fitz.open()
    b = PageBuilder(doc)
    b.header()
    b.row("Personal Services", "100", "200", "300")
    b.row("Equipment", "10", "20", "30")
    b.row("Travel - In State", "1", "2", "3")
    b.row("Other Operating Expenditures", "1", "2", "3")
    b.row("OPERATING SUBTOTAL", "112", "224", "336", x0=61)
    b.prose("AGENCY DESCRIPTION — prose.")
    b.row("Total", "112", "224", "336", x0=91)
    html = (
        "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
        "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
        "<tr><td>Equipment</td><td>10</td><td>20</td><td>30</td></tr>"
        "<tr><td>Travel - In State</td><td>1</td><td>2</td><td>3</td></tr>"
        "<tr><td>Other Operating Expenditures</td><td>1</td><td>2</td><td>3</td></tr>"
        "<tr><td>OPERATING SUBTOTAL</td><td>112</td><td>224</td><td>336</td></tr>"
        "<tr><td>TOTAL - ALL SOURCES</td><td>112</td><td>224</td><td>336</td></tr></table>"
    )   # five of six MinerU rows are on the page (83%), but not the last one
    out = refine_operating_table(_minerU(html), doc)
    assert out.table is None and out.reason == "last row unmatched"


def test_render_html_escapes_and_shapes():
    assert render_html([["", "FY 2024"], ["A & B", "1"]]) == "<table><tr><td></td><td>FY 2024</td></tr><tr><td>A &amp; B</td><td>1</td></tr></table>"
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_text_layer_table.py -v`
Expected: FAIL, `ModuleNotFoundError: No module named 'chunking.readers.text_layer_table'`

- [ ] **Step 3: Write `chunking/readers/text_layer_table.py`**

```python
"""Rebuild a JLBC operating table from the PDF's text layer (spec §3.1).

MinerU's table is the ANCHOR — it says which printed lines are the table
and on which page it starts. Every figure comes from PyMuPDF words and
their positions; the vision model's digits are never trusted (spec D2).
A rebuild is returned only if it reconciles (spec D3, `table_gate`).
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Sequence

from chunking.readers.types import Cell, Row, Table
from chunking.table_gate import is_check_label, reconcile
from chunking.table_text import (
    KIND_RE,
    MARKER_RE,
    figure_tokens,
    normalise_label,
    split_figure_marker,
)

# Spec §3.1 step 3: fewer matched anchor labels than this → None. A starting
# value; the dry run's match-rate distribution sets the real one.
ANCHOR_MIN_MATCH = 0.8
# Spec §3.1 step 3: how many pages past `table.page` to follow MinerU's own
# cross-page merge.
MAX_FORWARD_PAGES = 2
# A wrapped label sits at least this much further right than its row.
WRAP_INDENT = 3.0


@dataclass(frozen=True)
class RefineOutcome:
    table: Table | None
    reason: str
    anchor_match: float = 0.0


@dataclass
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class _Line:
    words: list[_Word]

    @property
    def x0(self) -> float:
        return self.words[0].x0

    @property
    def y0(self) -> float:
        return min(w.y0 for w in self.words)


@dataclass
class _Columns:
    centres: list[float]
    labels: list[str]

    @property
    def spacing(self) -> float:
        gaps = [b - a for a, b in zip(self.centres, self.centres[1:])]
        return min(gaps) if gaps else 100.0

    @property
    def label_limit(self) -> float:
        return self.centres[0] - self.spacing / 2

    def nearest(self, x: float) -> int:
        return min(range(len(self.centres)), key=lambda i: abs(self.centres[i] - x))


@dataclass
class _Draft:
    label: str
    x0: float
    figures: dict[int, str] = field(default_factory=dict)
    markers: dict[int, str] = field(default_factory=dict)


# --- words → lines -----------------------------------------------------------

def _lines(page) -> list[_Line]:
    raw = page.get_text("words")
    if not raw:
        return []
    words = sorted((_Word(w[0], w[1], w[2], w[3], w[4]) for w in raw), key=lambda w: (w.y0, w.x0))
    heights = sorted(w.y1 - w.y0 for w in words)
    tolerance = heights[len(heights) // 2] / 2   # half the median word height
    lines: list[_Line] = []
    for w in words:
        if lines and abs(w.y0 - lines[-1].words[0].y0) < tolerance:
            lines[-1].words.append(w)
        else:
            lines.append(_Line([w]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def _is_figure(text: str) -> bool:
    fig, _ = split_figure_marker(text)
    return bool(figure_tokens(fig))


def _is_marker(text: str) -> bool:
    return MARKER_RE.fullmatch(text) is not None


def _label_text(line: _Line) -> str:
    """The printed label: the line with its TRAILING figures, markers and
    dash-zeros removed. Only trailing ones — `Proposition 204 Services`
    and `Travel - In State` keep their number and their dash."""
    words = [w.text for w in line.words]
    while words and (_is_figure(words[-1]) or _is_marker(words[-1]) or words[-1] == "-"):
        words.pop()
    return normalise_label(" ".join(words))


# --- header ------------------------------------------------------------------

def _year_tokens(line: _Line) -> list[tuple[float, str]]:
    """(centre, 'FY 2024') for every year token on the line — `FY` + `2024`
    as two words, or `FY2024` as one."""
    out: list[tuple[float, str]] = []
    words = line.words
    i = 0
    while i < len(words):
        w = words[i]
        if w.text.upper() == "FY" and i + 1 < len(words) and words[i + 1].text.isdigit() and len(words[i + 1].text) == 4:
            out.append(((w.x0 + words[i + 1].x1) / 2, f"FY {words[i + 1].text}"))
            i += 2
            continue
        if w.text.upper().startswith("FY") and w.text[2:].isdigit() and len(w.text) == 6:
            out.append((w.centre, f"FY {w.text[2:]}"))
        i += 1
    return out


def _is_header_line(line: _Line) -> bool:
    return len(_year_tokens(line)) >= 2 or all(KIND_RE.match(w.text) for w in line.words)


def _find_columns(lines: Sequence[_Line], *, prefer: str = "last") -> _Columns | None:
    """Spec §3.1 step 4 over a run of lines in reading order: a line with
    two or more year tokens, plus the following line if it is all kind
    tokens. `prefer="last"` takes the header nearest the table when
    searching the lines above it; `"first"` when searching inside it."""
    indices = [i for i, line in enumerate(lines) if len(_year_tokens(line)) >= 2]
    if not indices:
        return None
    for i in ([indices[-1]] if prefer == "last" else [indices[0]]):
        line = lines[i]
        years = _year_tokens(line)
        centres = [c for c, _ in years]
        labels = [label for _, label in years]
        if i + 1 < len(lines):
            nxt = lines[i + 1]
            if nxt.words and all(KIND_RE.match(w.text) for w in nxt.words):
                cols = _Columns(centres, labels)
                for w in nxt.words:
                    j = cols.nearest(w.centre)
                    labels[j] = f"{labels[j]} {w.text.upper()}"
        return _Columns(centres, labels)
    return None


# --- anchoring ---------------------------------------------------------------

def _anchor_labels(table: Table) -> list[str]:
    out = []
    for row in table.rows:
        if row.cells:
            label = normalise_label(row.cells[0].text)
            if label:
                out.append(label)
    return out


def _region(lines: list[_Line], anchors: Sequence[str]) -> tuple[list[_Line], set[str]]:
    """Lines from the first anchor-matched line to the last, and which
    anchors matched. The containment runs page → MinerU because a merged
    MinerU label contains both printed lines (spec §3.1 step 3)."""
    matched_idx: list[int] = []
    matched: set[str] = set()
    last_anchor_idx: int | None = None
    for i, line in enumerate(lines):
        text = _label_text(line)
        if not text:
            continue
        # A line matches an anchor it equals, or one it is contained in when
        # it has at least two words — a lone `TOTAL` from a summary table
        # further down the page must not pass for `TOTAL - ALL SOURCES`.
        hits = [a for a in anchors if text == a or (text in a and len(text.split()) >= 2)]
        if hits:
            matched_idx.append(i)
            matched.update(hits)
            if anchors[-1] in hits:
                last_anchor_idx = i
    if not matched_idx:
        return [], set()
    # The region ends where MinerU's LAST row is printed, not at the last
    # line that happens to match any label — a prose heading `Operating
    # Budget` further down the page matches the anchor `OPERATING BUDGET`
    # and would otherwise drag the performance-measures block in.
    end = last_anchor_idx if last_anchor_idx is not None else matched_idx[-1]
    return lines[matched_idx[0]: end + 1], matched


# --- rows --------------------------------------------------------------------

def _rows(region: Sequence[_Line], cols: _Columns, anchors: Sequence[str]) -> list[_Draft] | None:
    drafts: list[_Draft] = []
    last = len(cols.centres) - 1
    for line in region:
        if _is_header_line(line):
            continue
        label_words: list[str] = []
        figures: dict[int, str] = {}
        markers: dict[int, str] = {}
        for w in line.words:
            if w.centre < cols.label_limit:
                label_words.append(w.text)
            elif _is_marker(w.text):
                markers[last if w.centre > cols.centres[last] else cols.nearest(w.centre)] = w.text
            elif _is_figure(w.text) or w.text == "-":
                j = cols.nearest(w.centre)
                if j in figures:
                    return None  # two figures in one column: the assignment is wrong
                fig, mk = split_figure_marker(w.text)
                figures[j] = fig
                if mk:
                    markers[j] = mk
            else:
                label_words.append(w.text)
        label = " ".join(label_words)
        if not figures:
            if not label:
                # A marker on a line of its own: it belongs to the row above.
                if markers and drafts:
                    drafts[-1].markers.update(markers)
                continue
            # Spec §3.1 step 5: indented under a row that has figures → the
            # label wrapped (`Account` under `Tobacco Products Tax Fund - …`).
            is_wrap = bool(drafts) and bool(drafts[-1].figures) and line.x0 > drafts[-1].x0 + WRAP_INDENT
            if is_wrap:
                drafts[-1].label = f"{drafts[-1].label} {label}"
                continue
            drafts.append(_Draft(label, line.x0))
            continue
        # The other wrap shape: the label broke BEFORE the figures
        # (`SUBTOTAL - Appropriated/Expenditure` / `Authority Funds 25,348,200 …`).
        # Accepted only when MinerU read the two lines as one label.
        if (
            drafts and not drafts[-1].figures and line.x0 > drafts[-1].x0 + WRAP_INDENT
            and (
                any(normalise_label(f"{drafts[-1].label} {label}") in a for a in anchors)
                or is_check_label(normalise_label(drafts[-1].label))
            )
        ):
            drafts[-1].label = f"{drafts[-1].label} {label}"
            drafts[-1].figures, drafts[-1].markers = figures, markers
            continue
        drafts.append(_Draft(label, line.x0, figures, markers))
    return drafts


def _cells(drafts: Sequence[_Draft], cols: _Columns) -> list[list[str]]:
    rows = [[""] + list(cols.labels)]
    for d in drafts:
        cells = [d.label]
        for j in range(len(cols.centres)):
            fig = d.figures.get(j, "")
            mk = d.markers.get(j)
            cells.append(f"{fig} [{mk}]" if fig and mk else fig)
        rows.append(cells)
    return rows


def render_html(rows: Sequence[Sequence[str]]) -> str:
    """The `<table><tr><td>` shape `MinerUReader._parse_html_table` reads."""
    body = "".join("<tr>" + "".join(f"<td>{_html.escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{body}</table>"


# --- entry point -------------------------------------------------------------

def refine_operating_table(table: Table, pdf) -> RefineOutcome:
    start = table.page if table.page is not None else (table.pages[0] if table.pages else None)
    if start is None or start < 1 or start > len(pdf):
        return RefineOutcome(None, "no page")
    anchors = _anchor_labels(table)
    if not anchors:
        return RefineOutcome(None, "no anchor labels")

    first_lines = _lines(pdf[start - 1])
    if not first_lines:
        return RefineOutcome(None, "no text layer")

    # Step 3: anchor, walking forward while MinerU's labels keep matching.
    region, matched = _region(first_lines, anchors)
    regions = [region]
    page_no = start
    while anchors[-1] not in matched and page_no - start < MAX_FORWARD_PAGES and page_no < len(pdf):
        page_no += 1
        more, more_matched = _region(_lines(pdf[page_no - 1]), anchors)
        if not (more_matched - matched):
            break
        regions.append(more)
        matched |= more_matched
    match_rate = len(matched) / len(anchors)
    if match_rate < ANCHOR_MIN_MATCH:
        return RefineOutcome(None, f"anchor match {match_rate:.0%}", match_rate)
    if anchors[-1] not in matched:
        # The region ends at MinerU's last row; if that row was never found
        # the end is a guess, and a guessed end can drop the fund ladder.
        return RefineOutcome(None, "last row unmatched", match_rate)

    # Step 4: header — above the region, inside its first lines, else the previous page.
    region_start = first_lines.index(region[0]) if region else 0
    cols = _find_columns(first_lines[:region_start], prefer="last") or _find_columns(region, prefer="first")
    if cols is None and start > 1:
        cols = _find_columns(_lines(pdf[start - 2]), prefer="last")
    if cols is None:
        return RefineOutcome(None, "no header", match_rate)

    # Steps 5–7.
    drafts = _rows([line for r in regions for line in r], cols, anchors)
    if drafts is None:
        return RefineOutcome(None, "two figures in one column", match_rate)
    rows = _cells(drafts, cols)

    # Step 8: the gate.
    verdict = reconcile(rows[1:])
    if not verdict.passed:
        return RefineOutcome(None, verdict.reason, match_rate)
    # Step 9: emit with MinerU's provenance untouched (spec D4).
    out_rows = [
        Row(cells=[Cell(text=c, row=i, col=j, page=table.page) for j, c in enumerate(r)])
        for i, r in enumerate(rows)
    ]
    return RefineOutcome(
        Table(rows=out_rows, caption=table.caption, bbox=table.bbox, page=table.page,
              pages=list(table.pages), html=render_html(rows)),
        "rebuilt",
        match_rate,
    )
```

- [ ] **Step 4: Run the reader tests**

Run: `uv run pytest tests/test_text_layer_table.py -v`
Expected: all PASS. Two likely first-run failures and their fixes:
- If `test_footnote_markers_separate_word_and_fused_word` fails because the 6-pt marker landed on its own line, print `[(l.y0, [w.text for w in l.words]) for l in _lines(doc[0])]` — the tolerance is half the median height (~4.5 pt); the marker is placed 1 pt below the baseline, so it must group. If PyMuPDF reports the smaller glyph's `y0` more than the tolerance away, change `marker` placement in `PageBuilder.row` to `self.y` (not `+ 1`) and note in the test that the real page's 1-pt offset was measured inside tolerance.
- If `test_sub_table_and_prose…` fails because the performance-measures header was picked as the column header, check `_find_columns(above)` is searching *reversed* lines above the region (nearest first) — it is the first header found scanning upward that wins.

- [ ] **Step 5: Mutation check, then commit**

Change `ANCHOR_MIN_MATCH` to `0.0` — `test_scanned_page_and_weak_anchor_return_none_with_a_reason` must fail. Restore with `git checkout`.

```bash
git add chunking/readers/text_layer_table.py tests/test_text_layer_table.py
git commit -m "feat(tables): rebuild an operating table from the PDF text layer, gated by reconciliation (spec §3.1)"
```

---

### Task 7: Wire the reader into ingest — one producer

**Files:**
- Modify: `chunking/readers/mineru_reader.py` (class `MinerUReader`, `read()` at line 54)
- Modify: `chunking/builder.py` (`chunk_doc`, line 67)
- Modify: `ingest/worker.py` (`_chunk`, line 1123–1138)
- Test: `tests/test_builder.py` (new test), `tests/test_mineru_reader.py` (new test), `tests/test_ingest_worker.py` (one assertion)

**Interfaces:**
- Produces: `MinerUReader(source_pdf: Path | None = None)`; `chunk_doc(..., source_pdf: Path | str | None = None)`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_mineru_reader.py`:

```python
def test_reader_refines_operating_tables_when_given_the_pdf(tmp_path):
    """Spec D5: the refinement is inside the reader, so ingest and repair share it."""
    import fitz
    from tests.test_text_layer_table import CLEAN_HTML, PageBuilder, _clean_page

    pdf = fitz.open()
    _clean_page(PageBuilder(pdf))
    pdf_path = tmp_path / "axs.pdf"
    pdf.save(str(pdf_path))
    page_json = tmp_path / "page-1.json"
    page_json.write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": CLEAN_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")

    plain = MinerUReader().read(page_json).tables[0]
    refined = MinerUReader(source_pdf=pdf_path).read(page_json).tables[0]
    assert [c.text for c in plain.rows[0].cells] == ["", "FY 2024 ACTUAL", "FY 2025 ESTIMATE", "FY 2026 APPROVED"]
    assert [c.text for c in refined.rows[3].cells] == ["Personal Services", "100", "200", "300"]
    assert refined.page == plain.page and refined.bbox == plain.bbox
```

Append to `tests/test_builder.py`:

```python
def test_chunk_doc_passes_the_pdf_only_for_in_scope_doc_types(tmp_path, monkeypatch):
    """Spec §3.2: an out-of-scope doc type never opens the PDF; an in-scope
    one hands it to the MinerU reader."""
    import chunking.builder as builder
    seen: list = []

    class SpyReader:
        def __init__(self, *, source_pdf=None):
            seen.append(source_pdf)
        def read(self, path):
            from chunking.readers.mineru_reader import MinerUReader
            return MinerUReader().read(path)

    monkeypatch.setattr(builder, "MinerUReader", SpyReader)
    monkeypatch.setitem(builder._READER_REGISTRY, "mineru", SpyReader)
    pdf = tmp_path / "x.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    chunk_doc(extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
              doc_meta=_approps_meta(doc_type="approps-per-agency"), source_pdf=pdf)
    chunk_doc(extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
              doc_meta=_approps_meta(doc_type="bh-pdf"), source_pdf=pdf)
    chunk_doc(extractor_output_path=FIXTURES / "mineru-jlbc-approps-p513.json",
              doc_meta=_approps_meta(doc_type="approps-per-agency"), source_pdf=tmp_path / "x.docx")
    assert seen == [pdf, None, None]
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_mineru_reader.py tests/test_builder.py -k "refines or passes_the_pdf" -v`
Expected: both FAIL (`TypeError: … unexpected keyword argument 'source_pdf'`).

- [ ] **Step 3: Give `MinerUReader` the PDF**

In `chunking/readers/mineru_reader.py`, add imports:

```python
from chunking.readers.text_layer_table import refine_operating_table
from chunking.table_text import has_ladder_marker
```

and in the class:

```python
class MinerUReader:
    def __init__(self, *, source_pdf: Path | None = None) -> None:
        # WHY: spec D5 — the text-layer rebuild of operating tables lives
        # INSIDE the reader so ingest and the one-time repair are one
        # producer. Without the PDF the reader behaves exactly as before.
        self._source_pdf = Path(source_pdf) if source_pdf is not None else None

    def read(self, path: Path | str) -> ExtractedDocument:
        ...
        pages = self._reassemble_multi_page_tables(pages)
        if self._source_pdf is not None:
            pages = self._refine_operating_tables(pages)
        outline = self._build_outline(pages)
        ...

    def _refine_operating_tables(self, pages: list[Page]) -> list[Page]:
        """Spec §3.2: every table carrying a ladder marker is rebuilt from
        the PDF text layer; a rebuild that does not reconcile is dropped
        and MinerU's table stays."""
        import fitz  # lazy: the reader is imported by code paths that never open a PDF

        with fitz.open(str(self._source_pdf)) as pdf:
            for page in pages:
                for i, block in enumerate(page.blocks):
                    if not isinstance(block, Table):
                        continue
                    if not has_ladder_marker(" ".join(c.text for r in block.rows for c in r.cells)):
                        continue
                    outcome = refine_operating_table(block, pdf)
                    if outcome.table is not None:
                        page.blocks[i] = outcome.table
        return pages
```

- [ ] **Step 4: Thread `source_pdf` through `chunk_doc` and the worker**

In `chunking/builder.py`, add `from chunking.table_text import OPERATING_TABLE_DOC_TYPES` and change the signature and reader construction:

```python
def chunk_doc(
    *,
    extractor_output_path: Path | str,
    doc_meta: DocMeta,
    output_dir: Path | str | None = None,
    stamper: EntityStamper | None = None,
    source_pdf: Path | str | None = None,
) -> list[Chunk]:
    """Read one doc's extractor output, build chunks, stamp, optionally write.

    `source_pdf` (spec §3.2) lets the MinerU reader rebuild agency
    operating tables from the PDF text layer. It is used only for the
    in-scope doc types and only for a `.pdf`; everything else reads
    exactly as before.
    """
    ...
    reader_cls = _READER_REGISTRY.get(doc_meta.extractor)
    ...
    pdf = Path(source_pdf) if source_pdf is not None else None
    if (
        pdf is not None
        and reader_cls is MinerUReader
        and doc_meta.doc_type in OPERATING_TABLE_DOC_TYPES
        and pdf.suffix.lower() == ".pdf"
    ):
        reader = MinerUReader(source_pdf=pdf)
    else:
        reader = reader_cls()
    doc = reader.read(Path(extractor_output_path))
```

In `ingest/worker.py::_chunk`, add the argument to the `chunk_doc(...)` call:

```python
        stamper=ctx.stamper,
        # Spec §3.2: the worker is the only place that holds the source
        # file; the reader needs it to rebuild operating tables.
        source_pdf=_source_path(job) if job.source_path else None,
    )
```

- [ ] **Step 5: Run the suites**

Run: `uv run pytest tests/test_mineru_reader.py tests/test_builder.py tests/test_table_chunk.py tests/test_ingest_worker.py tests/test_worker_ladder.py -v`
Expected: all PASS. If a worker test constructs a `JobRecord` without `source_path`, `_source_path` is not reached because of the guard.

- [ ] **Step 6: Commit**

```bash
git add chunking/readers/mineru_reader.py chunking/builder.py ingest/worker.py tests/test_mineru_reader.py tests/test_builder.py
git commit -m "feat(tables): ingest hands the source PDF to the MinerU reader; operating tables are rebuilt at ingest (spec D5)"
```

---

### Task 8: The repair pass — plan and dry run

**Files:**
- Modify: `chunking/repair_tables.py`
- Test: `tests/test_repair_tables.py`

**Interfaces:**
- Consumes: `ingest.extract_dirs.resolve_extract_dir(doc_id, root, *, method=None) -> tuple[Path, str] | None`; `store.documents.load_documents()`; `app.routes.pdf._resolve_blob(blob_path) -> Path | None` (some `source_blob_path` values are repo-relative `data/cached-pdfs/…`, not under the data dir); `chunking.builders.table_chunk._build_text`; `chunking.builders._tokens.count_tokens`
- Produces:
  - `TableChange(chunk_id, doc_id, fiscal_year, verdict, reason, source, anchor_match, rows_before, rows_after, merged_cells_removed, notes_separated, digit_disagreements, old_text, new_text, old_html, new_html)`
  - `plan_document(doc_id: str, rows: list[Mapping], root: Path, *, pdf_path: Path | None) -> list[TableChange]`
  - `plan_corpus(store, root, table, *, only=None, progress=None) -> tuple[list[TableChange], PlanSummary]`
  - `PlanSummary(per_year: dict[int, dict[str, int]], reasons: Counter, sources: Counter, digit_disagreements: int, eval_intersection: list[dict])`

- [ ] **Step 1: Write the failing tests**

`tests/test_repair_tables.py`:

```python
"""chunking/repair_tables.py — spec §6. A fake store that APPLIES writes
(the section-path plan's lesson), a synthetic PDF, and a MinerU page file."""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.repair_tables import TableChange, plan_corpus, plan_document
from tests.test_text_layer_table import CLEAN_HTML, PageBuilder, _clean_page

DOC = "jlbc-approps-fy2026-axs"


class _FakeStore:
    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.written: list[list[dict]] = []
        self.fts_built: list[str] = []
        self.optimized: list[str] = []

    def scan(self, name, columns, *, where=None, limit=None):
        out = [{c: r.get(c) for c in columns} for r in self.rows]
        if where and "chunk_id IN" in where:
            wanted = {p.strip().strip("'") for p in where.split("(", 1)[1].rstrip(")").split(",")}
            out = [r for r in out if r["chunk_id"] in wanted]
        return out

    def upsert_chunks(self, name, rows):
        rows = list(rows)
        self.written.append(rows)
        by_id = {r["chunk_id"]: r for r in rows}
        self.rows = [dict(by_id.get(r["chunk_id"], r)) for r in self.rows]

    def build_fts_index(self, name):
        self.fts_built.append(name)

    def optimize(self, name, *, retention=None):
        self.optimized.append(name)


@pytest.fixture()
def corpus(tmp_path):
    """One in-scope document with cached extractor output and its PDF; one
    in-scope document with NO extractor output (the html fallback); one
    out-of-scope table chunk that must never be touched."""
    root = tmp_path
    pdf = fitz.open()
    _clean_page(PageBuilder(pdf))
    pdfs = root / "pdfs"
    pdfs.mkdir()
    pdf.save(str(pdfs / "axs.pdf"))
    pdf.save(str(pdfs / "adc.pdf"))
    ext = root / "extractor-output" / DOC
    ext.mkdir(parents=True)
    (ext / "page-1.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": CLEAN_HTML, "bbox": [78, 85, 918, 907]}],
    }))
    (root / "documents.json").write_text(json.dumps({
        DOC: {"doc_type": "approps-per-agency", "fiscal_year": 2026, "source_blob_path": "pdfs/axs.pdf"},
        "jlbc-approps-fy2025-adc": {"doc_type": "approps-per-agency", "fiscal_year": 2025, "source_blob_path": "pdfs/adc.pdf"},
    }))
    minerU = MinerUReader().read(ext / "page-1.json").tables[0]
    stored = _build_text(minerU, ["FY 2026 Budget"])
    rows = [
        dict(chunk_id=f"{DOC}-0000", doc_id=DOC, fiscal_year=2026, doc_type="approps-per-agency", page=1,
             is_table=True, section_path=["FY 2026 Budget"], text=stored, table_html=CLEAN_HTML,
             token_count=10, vector=[0.0] * 4, agency_canonical_id="agency:axs"),
        dict(chunk_id="jlbc-approps-fy2025-adc-0000", doc_id="jlbc-approps-fy2025-adc", fiscal_year=2025,
             doc_type="approps-per-agency", page=1, is_table=True, section_path=["FY 2025 Budget"],
             text=_build_text(minerU, ["FY 2025 Budget"]), table_html=CLEAN_HTML, token_count=10, vector=[0.0] * 4,
             agency_canonical_id="agency:adc"),
        dict(chunk_id=f"{DOC}-0002", doc_id=DOC, fiscal_year=2026, doc_type="approps-per-agency", page=6,
             is_table=True, section_path=["Summary"], text="Summary\nTable 1\tx\ty", table_html="<table></table>",
             token_count=3, vector=[0.0] * 4, agency_canonical_id="agency:axs"),
    ]
    return root, _FakeStore(rows)


def test_plan_reads_extractor_output_first_and_falls_back_to_html(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    changes, summary = plan_corpus(store, root, "budget_chunks")
    by_id = {c.chunk_id: c for c in changes}
    assert set(by_id) == {f"{DOC}-0000", "jlbc-approps-fy2025-adc-0000"}   # the Summary table is out of scope
    assert by_id[f"{DOC}-0000"].source == "extractor"
    assert by_id["jlbc-approps-fy2025-adc-0000"].source == "html"
    assert all(c.verdict == "rebuilt" for c in changes)
    assert summary.sources == {"extractor": 1, "html": 1}
    assert summary.per_year[2026] == {"tables": 1, "rebuilt": 1, "unverified": 0}
    assert store.written == []                      # a plan writes nothing


def test_plan_rows_keep_line_zero_and_report_row_counts(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.new_text.split("\n")[0] == "FY 2026 Budget"        # D4: line 0 untouched
    assert c.rows_after >= c.rows_before
    assert c.merged_cells_removed == 0 and c.digit_disagreements == []
    assert c.new_html.startswith("<table><tr><td></td><td>FY 2024 ACTUAL")


def test_extractor_output_that_does_not_match_the_chunk_falls_back_to_html(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    (root / "extractor-output" / DOC / "page-1.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": "<table><tr><td>Different</td><td>1</td></tr></table>", "bbox": [0, 0, 1, 1]}],
    }))
    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "html" and "extractor output differs" in c.reason


def test_unverifiable_table_is_counted_not_rewritten(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    (root / "pdfs" / "adc.pdf").write_bytes(fitz.open().write())     # a PDF with no pages → no text layer
    doc = fitz.open(); doc.new_page(); doc.save(str(root / "pdfs" / "adc.pdf"))
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == "jlbc-approps-fy2025-adc")
    assert c.verdict == "unverified" and c.reason == "no text layer" and c.new_text is None
    assert summary.per_year[2025] == {"tables": 1, "rebuilt": 0, "unverified": 1}
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_repair_tables.py -v`
Expected: FAIL, `ImportError: cannot import name 'TableChange'`.

- [ ] **Step 3: Add the plan to `chunking/repair_tables.py`**

Add imports:

```python
import json
import random
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.text_layer_table import refine_operating_table
from chunking.table_text import figure_tokens
from ingest.extract_dirs import resolve_extract_dir
```

and the plan:

```python
@dataclass
class TableChange:
    chunk_id: str
    doc_id: str
    fiscal_year: int
    verdict: str            # "rebuilt" | "unverified"
    reason: str
    source: str             # "extractor" | "html"
    anchor_match: float
    rows_before: int
    rows_after: int
    merged_cells_removed: int
    notes_separated: int
    digit_disagreements: list[str]
    old_text: str
    new_text: str | None
    old_html: str | None
    new_html: str | None


@dataclass
class PlanSummary:
    per_year: dict[int, dict[str, int]] = field(default_factory=dict)
    reasons: Counter = field(default_factory=Counter)
    sources: Counter = field(default_factory=Counter)
    match_rates: list[float] = field(default_factory=list)
    digit_disagreements: int = 0
    eval_intersection: list[dict[str, Any]] = field(default_factory=list)


def _chunk_index(chunk_id: str) -> int:
    return int(chunk_id.rsplit("-", 1)[1])


def _figures_in(text: str) -> set[str]:
    """Comma-grouped or decimal figures only — the ones that identify a cell."""
    out = set()
    for line in text.split("\n"):
        for cell in line.split("\t")[1:]:
            out.update(t for t in figure_tokens(cell) if "," in t or "." in t)
    return out


def _body(text: str) -> str:
    """Everything below line 0 — what `_build_text` produced from the table."""
    return "\n".join(text.split("\n")[1:])


def plan_document(doc_id: str, rows: list[Mapping[str, Any]], root: Path, *, pdf_path: Path | None) -> list[TableChange]:
    """Spec §3.2 (repair): the MinerU `Table` comes from cached extractor
    output when it exists AND reproduces the stored text; otherwise from
    the stored `table_html`. Either way the same refinement runs."""
    import fitz

    tables: list | None = None
    located = resolve_extract_dir(doc_id, root)
    if located is not None:
        try:
            tables = MinerUReader().read(located[0]).tables
        except Exception as exc:  # noqa: BLE001 — recorded per chunk below, never fatal
            tables, read_error = None, f"extractor output unreadable: {exc}"
    out: list[TableChange] = []
    pdf = fitz.open(str(pdf_path)) if pdf_path is not None and pdf_path.exists() else None
    try:
        for row in rows:
            idx = _chunk_index(row["chunk_id"])
            section_path = list(row.get("section_path") or [])
            old_text = row.get("text") or ""
            table, source, note = None, "html", ""
            if tables is not None and idx < len(tables) and _body(_build_text(tables[idx], section_path)) == _body(old_text):
                table, source = tables[idx], "extractor"
            elif tables is not None:
                note = "extractor output differs from the stored text; "
            if table is None:
                table = MinerUReader._parse_html_table(row.get("table_html") or "", page=row.get("page") or 1, bbox=None)
            if pdf is None:
                outcome_table, reason, match = None, "no source pdf", 0.0
            else:
                outcome = refine_operating_table(table, pdf)
                outcome_table, reason, match = outcome.table, outcome.reason, outcome.anchor_match
            before_cells = [[c.text for c in r.cells] for r in table.rows]
            change = TableChange(
                chunk_id=row["chunk_id"], doc_id=doc_id, fiscal_year=int(row.get("fiscal_year") or 0),
                verdict="rebuilt" if outcome_table is not None else "unverified",
                reason=note + reason, source=source, anchor_match=match,
                rows_before=len(table.rows), rows_after=len(outcome_table.rows) if outcome_table else 0,
                merged_cells_removed=sum(1 for r in before_cells for c in r[1:] if len(figure_tokens(c)) >= 2),
                notes_separated=0, digit_disagreements=[],
                old_text=old_text, new_text=None, old_html=row.get("table_html"), new_html=None,
            )
            if outcome_table is not None:
                change.new_text = _build_text(outcome_table, section_path)
                change.new_html = outcome_table.html
                change.notes_separated = change.new_text.count(" [")
                old_f, new_f = _figures_in(old_text), _figures_in(change.new_text)
                change.digit_disagreements = sorted(f"-{f}" for f in old_f - new_f) + sorted(f"+{f}" for f in new_f - old_f)
            out.append(change)
    finally:
        if pdf is not None:
            pdf.close()
    return out


def _eval_intersection(changes: list[TableChange], queries_path: Path = Path("eval/queries.yaml")) -> list[dict[str, Any]]:
    """G-OT2: the ground-truth chunks in scope must still contain their anchor_text."""
    if not queries_path.exists():
        return []
    by_id = {c.chunk_id: c for c in changes}
    out = []
    for q in yaml.safe_load(queries_path.read_text(encoding="utf-8")) or []:
        for exp in q.get("expected_chunks") or []:
            c = by_id.get(exp.get("chunk_id"))
            if c is None:
                continue
            anchor = exp.get("anchor_text") or ""
            out.append({"query": q["id"], "chunk_id": c.chunk_id, "verdict": c.verdict,
                        "anchor_found": anchor in (c.new_text or c.old_text)})
    return out


def plan_corpus(store: ChunkStoreLike, root: Path, table: str, *, only: set[str] | None = None,
                progress: Callable[[str], None] | None = None) -> tuple[list[TableChange], PlanSummary]:
    progress = progress or (lambda m: print(m, flush=True))
    from app.routes.pdf import _resolve_blob   # the one resolver for `source_blob_path` (data dir, repo, flat pdfs/)
    from store.documents import load_documents
    docs = load_documents()
    rows = [r for r in store.scan(table, PLAN_COLUMNS + ["is_table"], where="is_table = true") if in_scope(r)]
    if only:
        rows = [r for r in rows if r["doc_id"] in only]
    by_doc: dict[str, list] = defaultdict(list)
    for r in rows:
        by_doc[r["doc_id"]].append(r)
    changes: list[TableChange] = []
    summary = PlanSummary()
    for n, (doc_id, doc_rows) in enumerate(sorted(by_doc.items()), start=1):
        rec = docs.get(doc_id) or {}
        pdf_path = _resolve_blob(str(rec.get("source_blob_path") or ""))
        for c in plan_document(doc_id, doc_rows, root, pdf_path=pdf_path):
            changes.append(c)
            y = summary.per_year.setdefault(c.fiscal_year, {"tables": 0, "rebuilt": 0, "unverified": 0})
            y["tables"] += 1
            y[c.verdict] += 1
            summary.reasons[c.reason] += 1
            summary.sources[c.source] += 1
            summary.match_rates.append(c.anchor_match)
            summary.digit_disagreements += len(c.digit_disagreements)
        if n % 200 == 0:
            progress(f"planned {n}/{len(by_doc)} documents")
    summary.eval_intersection = _eval_intersection(changes)
    return changes, summary
```

Add `from collections import Counter` to the imports.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_repair_tables.py -v`
Expected: all PASS. (`test_unverifiable_table…` overwrites `adc.pdf` with a one-blank-page PDF, so the refinement reports `no text layer`.)

- [ ] **Step 5: Commit**

```bash
git add chunking/repair_tables.py tests/test_repair_tables.py
git commit -m "feat(tables): repair plan — extractor output first, html fallback, per-year verdicts, digit disagreements (spec §6.1)"
```

---

### Task 9: The repair pass — apply, reversal, verify

**Files:**
- Modify: `chunking/repair_tables.py`
- Test: `tests/test_repair_tables.py`

**Interfaces:**
- Consumes: `chunking.repair_common.{all_columns, in_list, atomic_write_json, reversal_stamp, default_snapshot_and_verify, EmbedderLike}`; `ingest.lock.IngestLock`; `chunking.builders._tokens.count_tokens`
- Produces: `repair_tables(*, store, embedder, root, table="budget_chunks", dry_run=True, only=None, batch_size=500, lock=None, snapshot_and_verify=None, reversal_dir=None, progress=None) -> RepairResult`; `RepairResult(changes, summary, written, skipped_moved, snapshot_name, reversal_path)`

- [ ] **Step 1: Write the failing apply tests**

Append to `tests/test_repair_tables.py`:

```python
from chunking.repair_tables import RepairResult, repair_tables


class _FakeEmbedder:
    dim = 4
    def __init__(self):
        self.calls: list[tuple[list[str], str]] = []
    def embed_batch(self, texts, *, input_type="document"):
        self.calls.append((list(texts), input_type))
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


class _FakeLock:
    def __init__(self):
        self.entered = 0
    def __enter__(self):
        self.entered += 1
        return self
    def __exit__(self, *a):
        return None
    def heartbeat(self):
        pass


def _apply(root, store, **over):
    kw = dict(store=store, embedder=_FakeEmbedder(), root=root, dry_run=False, lock=_FakeLock(),
              snapshot_and_verify=lambda: "lancedb-test.zip", reversal_dir=root)
    kw.update(over)
    return repair_tables(**kw)


def test_dry_run_writes_nothing(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    result = repair_tables(store=store, embedder=_FakeEmbedder(), root=root, dry_run=True)
    assert result.written == 0 and store.written == [] and store.fts_built == []
    assert len(result.changes) == 2


def test_apply_rewrites_only_the_four_columns_and_rebuilds_fts(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    before = {r["chunk_id"]: dict(r) for r in store.rows}
    lock = _FakeLock()
    emb = _FakeEmbedder()
    result = _apply(root, store, lock=lock, embedder=emb)
    assert result.written == 2 and lock.entered == 1
    assert store.fts_built == ["budget_chunks"] and store.optimized == ["budget_chunks"]
    assert emb.calls and all(kind == "document" for _, kind in emb.calls)
    after = {r["chunk_id"]: r for r in store.rows}
    for cid, was in before.items():
        now = after[cid]
        if cid == f"{DOC}-0002":
            assert now == was                                      # out of scope: untouched
            continue
        assert now["text"] != was["text"] and now["table_html"] != was["table_html"]
        assert now["vector"] != was["vector"] and now["token_count"] > 0
        for col in ("chunk_id", "doc_id", "page", "section_path", "agency_canonical_id", "fiscal_year"):
            assert now[col] == was[col]                             # D4


def test_apply_skips_a_row_whose_text_moved_and_counts_it(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))

    class MovedStore(_FakeStore):
        def scan(self, name, columns, *, where=None, limit=None):
            out = super().scan(name, columns, where=where, limit=limit)
            if "vector" in columns:                                  # the apply-time read
                for r in out:
                    if r["chunk_id"] == f"{DOC}-0000":
                        r["text"] = r["text"] + "\nmoved"
            return out
    moved = MovedStore(store.rows)
    result = _apply(root, moved)
    assert result.written == 1 and result.skipped_moved == [f"{DOC}-0000"]


def test_reversal_record_round_trips(corpus, monkeypatch):
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    before = {r["chunk_id"]: dict(r) for r in store.rows}
    result = _apply(root, store)
    payload = json.loads(Path(result.reversal_path).read_text())
    assert payload["snapshot"] == "lancedb-test.zip" and payload["table"] == "budget_chunks"
    assert {r["chunk_id"] for r in payload["rows"]} == {f"{DOC}-0000", "jlbc-approps-fy2025-adc-0000"}
    for r in payload["rows"]:
        assert r["before"]["text"] == before[r["chunk_id"]]["text"]
        assert r["before"]["table_html"] == before[r["chunk_id"]]["table_html"]
        assert r["after"]["text"] != r["before"]["text"]


def test_second_plan_after_apply_finds_nothing_to_rebuild(corpus, monkeypatch):
    """Rehearsal step 2: after the apply the dry run reports nothing left —
    the rebuilt text reconciles and has no merged cell, and rebuilding it
    again reproduces itself."""
    root, store = corpus
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    _apply(root, store)
    changes, _ = plan_corpus(store, root, "budget_chunks")
    assert all(c.verdict == "rebuilt" and c.new_text == c.old_text for c in changes)
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_repair_tables.py -v`
Expected: the five new tests FAIL with `ImportError: cannot import name 'RepairResult'`.

- [ ] **Step 3: Add the apply path**

Add to `chunking/repair_tables.py`:

```python
from chunking.builders._tokens import count_tokens
from chunking.repair_common import (
    EmbedderLike,
    all_columns,
    atomic_write_json,
    default_snapshot_and_verify,
    in_list,
    reversal_stamp,
)

DEFAULT_BATCH_SIZE = 500          # rows re-embedded per batch; the embedder is the slow part


@dataclass
class RepairResult:
    changes: list[TableChange]
    summary: PlanSummary
    written: int = 0
    skipped_moved: list[str] = field(default_factory=list)
    snapshot_name: str | None = None
    reversal_path: Path | None = None


def _write_changed_rows(store: ChunkStoreLike, table: str, changes: list[TableChange], embedder: EmbedderLike,
                        batch_size: int, progress: Callable[[str], None]) -> tuple[int, list[str], list[dict]]:
    """Per-row compare-and-swap on `text` (spec §6.4): a row whose stored
    text no longer equals the planned old text is skipped and counted,
    never overwritten. Returns (written, skipped ids, reversal rows)."""
    written, skipped, reversal = 0, [], []
    todo = [c for c in changes if c.verdict == "rebuilt"]
    for start in range(0, len(todo), batch_size):
        batch = todo[start: start + batch_size]
        by_id = {c.chunk_id: c for c in batch}
        rows = store.scan(table, all_columns(), where=in_list(by_id))
        pending, texts = [], []
        for row in rows:
            change = by_id.get(row["chunk_id"])
            if change is None:
                continue
            if (row.get("text") or "") != change.old_text:
                skipped.append(row["chunk_id"])
                continue
            new_row = dict(row)
            new_row["text"] = change.new_text
            new_row["table_html"] = change.new_html
            new_row["token_count"] = count_tokens(change.new_text)
            pending.append(new_row)
            texts.append(change.new_text)
            reversal.append({"chunk_id": row["chunk_id"], "doc_id": row["doc_id"],
                             "before": {"text": row["text"], "table_html": row.get("table_html")},
                             "after": {"text": change.new_text, "table_html": change.new_html}})
        if pending:
            # input_type="document": the embedder is asymmetric (ingest/worker.py).
            vectors = embedder.embed_batch(texts, input_type="document")
            for new_row, vec in zip(pending, vectors):
                new_row["vector"] = vec
            store.upsert_chunks(table, pending)
            written += len(pending)
        progress(f"{table}: wrote {written}/{len(todo)} rebuilt rows ({len(skipped)} skipped, text moved)")
    return written, skipped, reversal


def _verify_nothing_was_lost(store: ChunkStoreLike, table: str, before: dict[str, Mapping[str, Any]],
                             touched: set[str], progress: Callable[[str], None]) -> None:
    """Spec §6.6: same chunk-id set; every column other than the four
    rewritten ones identical on touched rows; a 200-row untouched sample
    byte-identical."""
    after_rows = store.scan(table, all_columns())
    after = {r["chunk_id"]: r for r in after_rows}
    if set(after) != set(before):
        raise RuntimeError(f"{table}: chunk-id set changed during the apply — restore the snapshot")
    rewritten = {"text", "table_html", "token_count", "vector"}
    for cid in touched:
        for col in before[cid]:
            if col not in rewritten and before[cid][col] != after[cid][col]:
                raise RuntimeError(f"{table}: column {col!r} moved on {cid} — restore the snapshot")
    untouched = [cid for cid in before if cid not in touched]
    for cid in random.Random(0).sample(untouched, min(200, len(untouched))):
        if before[cid] != after[cid]:
            raise RuntimeError(f"{table}: untouched row {cid} changed — restore the snapshot")
    for cid in touched:
        if has_merged_cell(table_rows(after[cid]["text"])):
            raise RuntimeError(f"{table}: {cid} still holds a merged cell after the rebuild")
    progress(f"{table}: verified {len(touched)} touched rows and {min(200, len(untouched))} untouched rows")


def repair_tables(*, store: ChunkStoreLike, embedder: EmbedderLike, root: Path, table: str = "budget_chunks",
                  dry_run: bool = True, only: set[str] | None = None, batch_size: int = DEFAULT_BATCH_SIZE,
                  lock: Any | None = None, snapshot_and_verify: Callable[[], str | None] | None = None,
                  reversal_dir: Path | None = None, progress: Callable[[str], None] | None = None) -> RepairResult:
    progress = progress or (lambda m: print(m, flush=True))
    changes, summary = plan_corpus(store, root, table, only=only, progress=progress)
    result = RepairResult(changes, summary)
    if dry_run or not any(c.verdict == "rebuilt" for c in changes):
        return result
    if lock is None:
        from ingest.lock import IngestLock
        lock = IngestLock()
    snapshot_and_verify = snapshot_and_verify or default_snapshot_and_verify
    reversal_dir = Path(reversal_dir) if reversal_dir is not None else root

    before = {r["chunk_id"]: r for r in store.scan(table, all_columns())}
    with lock:
        result.snapshot_name = snapshot_and_verify()
        written, skipped, reversal = _write_changed_rows(store, table, changes, embedder, batch_size, progress)
        result.written, result.skipped_moved = written, skipped
        touched = {r["chunk_id"] for r in reversal}
        _verify_nothing_was_lost(store, table, before, touched, progress)
        # Upsert is delete-then-add; added rows are invisible to BM25 until
        # the index is rebuilt (funds/unstamp.py).
        progress(f"{table}: rebuilding the full-text index and optimizing")
        store.build_fts_index(table)
        store.optimize(table)
    result.reversal_path = reversal_dir / f"table-rebuild-reversal-{table}-{reversal_stamp()}.json"
    atomic_write_json(result.reversal_path, {"table": table, "snapshot": result.snapshot_name, "rows": reversal})
    return result
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_repair_tables.py -v`
Expected: all PASS. If `test_apply_skips_a_row_whose_text_moved…` fails because `_verify_nothing_was_lost` raises on the moved row, note the fake store's moved text is only returned on the `vector`-projecting read; the verify's `all_columns()` read also projects `vector`, so the *before* snapshot must be taken with the same projection — it is (`all_columns()` both times), so the moved row compares equal to itself. If the fake's `scan` filter on `where` breaks because `in_list` quotes differently than the test's parser expects, adjust the parser in `_FakeStore.scan`, not `in_list`.

- [ ] **Step 5: Commit**

```bash
git add chunking/repair_tables.py tests/test_repair_tables.py
git commit -m "feat(tables): repair apply — lock, snapshot, compare-and-swap, four columns, FTS rebuild, reversal, verify (spec §6.4–6.6)"
```

---

### Task 10: The CLI and the dry run on the live corpus (G-OT1)

**Files:**
- Modify: `chunking/repair_tables.py` (`main`)
- Create: `docs/superpowers/investigations/2026-09-XX-operating-table-rebuild-dry-run.md`

- [ ] **Step 1: Finish `main`**

Replace the `main` in `chunking/repair_tables.py`:

```python
def _print_summary(summary: PlanSummary, changes: list[TableChange], pairs: int) -> None:
    print("\nPer fiscal year (G-OT1):")
    print(f"{'year':>6} {'tables':>7} {'rebuilt':>8} {'unverif':>8} {'rate':>6}")
    tot = {"tables": 0, "rebuilt": 0, "unverified": 0}
    for year in sorted(summary.per_year):
        v = summary.per_year[year]
        for k in tot:
            tot[k] += v[k]
        print(f"{year:>6} {v['tables']:>7} {v['rebuilt']:>8} {v['unverified']:>8} {(v['rebuilt'] / v['tables']):>6.1%}")
    print(f"{'all':>6} {tot['tables']:>7} {tot['rebuilt']:>8} {tot['unverified']:>8} {(tot['rebuilt'] / max(tot['tables'], 1)):>6.1%}")
    print("\nSource of the MinerU table:", dict(summary.sources))
    print("\nReasons:")
    for reason, n in summary.reasons.most_common():
        print(f"  {n:>6}  {reason}")
    rates = sorted(summary.match_rates)
    if rates:
        q = lambda p: rates[min(len(rates) - 1, int(p * len(rates)))]
        print(f"\nAnchor match rate: min {rates[0]:.0%}  p10 {q(0.1):.0%}  p50 {q(0.5):.0%}  p90 {q(0.9):.0%}")
    print(f"\nDigit disagreements (MinerU vs text layer, after the gate): {summary.digit_disagreements}")
    rng = random.Random(0)
    examples = [c for c in changes if c.digit_disagreements]
    for c in rng.sample(examples, min(20, len(examples))):
        print(f"  {c.chunk_id}: {', '.join(c.digit_disagreements[:6])}")
    print("\nEval intersection (G-OT2):")
    for e in summary.eval_intersection:
        print(f"  {e['query']:>10} {e['chunk_id']:40s} {e['verdict']:10s} anchor_found={e['anchor_found']}")
    print(f"\n{pairs} before/after pairs for reading:")
    rebuilt = [c for c in changes if c.verdict == "rebuilt"]
    for c in rng.sample(rebuilt, min(pairs, len(rebuilt))):
        print(f"\n===== {c.chunk_id}  ({c.source}, {c.merged_cells_removed} merged cells, {len(c.digit_disagreements)} digit disagreements)")
        print("--- before\n" + c.old_text[:1500])
        print("--- after\n" + (c.new_text or "")[:1500])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default="budget_chunks", choices=("budget_chunks",))
    parser.add_argument("--calibrate", action="store_true", help="spec §4.1: gate the stored clean tables, write nothing")
    parser.add_argument("--apply", action="store_true", help="write under the ingest lock after a verified snapshot")
    parser.add_argument("--doc", action="append", default=None, help="restrict to these doc_ids (repeatable; not with --apply)")
    parser.add_argument("--report", type=Path, default=None, help="write the full plan as JSON here")
    parser.add_argument("--pairs", type=int, default=20, help="before/after pairs to print")
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args(argv)
    if args.apply and args.doc:
        parser.error("--apply rewrites the whole table; drop --doc")

    from store.chunk_store import ChunkStore
    from store.config import data_dir
    store = ChunkStore(create=False)
    root = data_dir()
    if args.calibrate:
        _print_calibration(calibrate(store, args.table))
        return 0

    embedder = None
    if args.apply:
        from retrieval.local_embedder import LocalEmbedder
        embedder = LocalEmbedder()
    result = repair_tables(store=store, embedder=embedder, root=root, table=args.table, dry_run=not args.apply,
                           only=set(args.doc) if args.doc else None, batch_size=args.batch_size)
    _print_summary(result.summary, result.changes, args.pairs)
    if args.report:
        atomic_write_json(args.report, {
            "table": args.table, "dry_run": not args.apply, "written": result.written,
            "skipped_moved": result.skipped_moved, "snapshot": result.snapshot_name,
            "reversal": str(result.reversal_path) if result.reversal_path else None,
            "per_year": result.summary.per_year, "reasons": dict(result.summary.reasons),
            "sources": dict(result.summary.sources), "eval_intersection": result.summary.eval_intersection,
            "rows": [c.__dict__ for c in result.changes],
        })
        print(f"\nreport: {args.report}")
    if args.apply:
        print(f"\nwrote {result.written} rows; skipped {len(result.skipped_moved)} (text moved); "
              f"snapshot {result.snapshot_name}; reversal {result.reversal_path}")
    return 0
```

Check `LocalEmbedder()` constructs with no arguments in `retrieval/local_embedder.py`; if it needs a model path, use the same construction `ingest/worker.py` uses for `ctx.embedder`.

- [ ] **Step 2: Dry run on one document, then a slice**

```bash
JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --doc jlbc-approps-fy2026-axs --pairs 2
JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --doc jlbc-approps-fy2006-col --pairs 2
```

Expected for AHCCCS: `rebuilt`, `source=extractor`, the `SUBTOTAL - Other Appropriated Funds` and `SUBTOTAL - Appropriated Funds` rows separate, `TOTAL - ALL SOURCES` FY 2026 = `23,010,071,300`, `DES Eligibility` FY 2026 = `99,294,500 [3/]`. For the FY2006 page: four columns, `AGENCY TOTAL` FY 2006 = `15,352,300 [1/]`. If either is `unverified`, read the reason, fix the reader with a new unit test reproducing the shape, and re-run.

- [ ] **Step 3: The full dry run**

```bash
JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --report /tmp/table-rebuild-plan.json 2>&1 | tee /tmp/table-rebuild-dry-run.log
```

Runs ~4,800 tables; expect 10–20 minutes (one PyMuPDF open per document). Read the per-year table. **Stop and investigate if the overall rate is under 90% or any year under 70%** (spec §4.1): group the failing reasons, read ten failing chunks per dominant reason, and decide whether it is the rule (fix, with a test) or the page (accept, counted). Set `ANCHOR_MIN_MATCH` from the p10 of the match-rate line if the 80% default is cutting real tables.

- [ ] **Step 4: Record the dry run**

`docs/superpowers/investigations/2026-09-XX-operating-table-rebuild-dry-run.md` with `status: active` frontmatter: the command, the per-year table, the source split (extractor vs html — the html count is the 329-document FY2025 gap), the reasons histogram, the anchor-match quantiles, the digit-disagreement count and the 20 examples, the eval intersection (all five `anchor_found=True`, else stop), and the 20 before/after pairs verbatim. This is the checkpoint document Destin reads (spec §6.3).

- [ ] **Step 5: Commit**

```bash
git add chunking/repair_tables.py docs/superpowers/investigations/2026-09-XX-operating-table-rebuild-dry-run.md
git commit -m "feat(tables): repair CLI; dry run on the live corpus recorded (G-OT1)"
```

---

### Task 11: Rehearsal on a copy, G-OT3, the G-OT2 control, and the checkpoint

**Files:**
- Modify: the dry-run investigation doc (rehearsal results appended)
- Create: `eval/results/<UTC>-<sha>.{json,md}` (the control run)

- [ ] **Step 1: Copy the database and rehearse**

```bash
R=/tmp/table-rehearsal-data
rm -rf $R && mkdir -p $R
cp -r data/insight-data/lancedb $R/lancedb
cp data/insight-data/documents.json $R/documents.json
ln -s $(pwd)/data/insight-data/extractor-output $R/extractor-output
ln -s $(pwd)/data/insight-data/pdfs $R/pdfs
JLBC_DATA_DIR=$R uv run python -m chunking.repair_tables --apply --report /tmp/table-rebuild-rehearsal.json 2>&1 | tee /tmp/table-rebuild-rehearsal.log
JLBC_DATA_DIR=$R uv run python -m chunking.repair_tables --pairs 0 2>&1 | tail -30
```

Expected: the apply writes the planned count with 0 skipped; the second dry run reports every in-scope table as `rebuilt` with `new_text == old_text` — i.e. nothing left to change (spec §6.2). If the second run shows tables that would change again, the reader is not idempotent on its own output; fix before touching the live store.

- [ ] **Step 2: G-OT3 — re-chunk 40 documents and diff**

```bash
JLBC_DATA_DIR=$R uv run python - <<'EOF'
import json, random
from pathlib import Path
from chunking.builder import chunk_doc
from chunking.types import DocMeta
from ingest.extract_dirs import resolve_extract_dir
from store.chunk_store import ChunkStore
from store.config import data_dir
from store.documents import load_documents

root = data_dir(); store = ChunkStore(create=False); docs = load_documents()
plan = json.loads(Path("/tmp/table-rebuild-rehearsal.json").read_text())
rebuilt_docs = sorted({r["doc_id"] for r in plan["rows"] if r["verdict"] == "rebuilt" and r["source"] == "extractor"})
sample = random.Random(0).sample(rebuilt_docs, 40)
drift = 0
for doc_id in sample:
    rec = docs[doc_id]; located = resolve_extract_dir(doc_id, root)
    meta = DocMeta(doc_id=doc_id, publisher=rec["publisher"], doc_type=rec["doc_type"], fiscal_year=rec["fiscal_year"],
                   extractor=located[1].split("-")[0], source_format="pdf", source_url=rec.get("source_url"))
    fresh = {c.chunk_id: c for c in chunk_doc(extractor_output_path=located[0], doc_meta=meta, source_pdf=root / rec["source_blob_path"])}
    stored = {r["chunk_id"]: r for r in store.scan("budget_chunks", ["chunk_id", "text", "table_html"], where=f"doc_id = '{doc_id}'")}
    for cid, row in stored.items():
        if cid in fresh and "\t" in row["text"]:
            body = lambda t: "\n".join(t.split("\n")[1:])
            if body(fresh[cid].text) != body(row["text"]):
                drift += 1; print("DRIFT", cid)
print("documents:", len(sample), "drift:", drift)
EOF
```

Expected: `drift: 0`. (Line 0 is excluded because the section-path repair owns it and the re-chunk's `_resolve_section_path` may differ — that is that plan's G-T6, not this one's.) Any drift means the repair and the ingest path disagree — D5 broken; fix before the live apply.

- [ ] **Step 3: G-OT2 control on the LIVE, unmodified corpus**

```bash
JLBC_DATA_DIR=data/insight-data uv run python -m eval.run_eval --note "G-OT2 control before the operating-table rebuild"
```

Commit the two result files it writes under `eval/results/`.

- [ ] **Step 4: The checkpoint**

Append the rehearsal log summary, the G-OT3 output and the control run's filename to the dry-run investigation doc. Then hand Destin, in plain words: the per-year pass table, how many tables stay garbled and why, the 20 before/after pairs, the digit-disagreement examples, and the one question — apply to the live corpus, yes or no. **Do not run Task 12 until he answers.**

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/investigations/2026-09-XX-operating-table-rebuild-dry-run.md eval/results/
git commit -m "docs(tables): rehearsal on a copy, G-OT3 drift 0, G-OT2 control run — checkpoint"
```

---

### Task 12: The live apply, the post-eval, STATUS, and the docs move

**Precondition:** Destin's explicit yes at the Task 11 checkpoint, and no ingest running (`ls data/insight-data/ingest.lock` absent).

- [x] **Step 1: Re-run the dry run against the live store if the section-path apply happened since Task 10** — DONE 2026-09-03, matched to the row

`JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --pairs 0 | tail -5` — the counts must match Task 10's; if they do not, re-record and re-checkpoint (spec §6.1).

- [x] **Step 2: Apply** — DONE 2026-09-03, 4,656 rows / 0 skipped

```bash
JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --apply --report /tmp/table-rebuild-live.json 2>&1 | tee /tmp/table-rebuild-live.log
```

Expected: `wrote N rows; skipped 0 (text moved); snapshot lancedb-<UTC>.zip; reversal data/insight-data/table-rebuild-reversal-budget_chunks-<UTC>.json`. If the apply raises from `_verify_nothing_was_lost`, restore the named snapshot with `store.backup.restore(name)` and stop.

- [x] **Step 3: G-OT2 after, and G-OT4 offer** — DONE (eval identical; G-OT4 offered). NOTE: `run_eval` has no `--note` flag; run it bare

```bash
JLBC_DATA_DIR=data/insight-data uv run python -m eval.run_eval --note "G-OT2 after the operating-table rebuild"
```

Compare against the control: every query's status (found / not found / refused) must match; rank movement on the five in-scope ground-truth chunks is expected and is not a regression. Commit the result files.

Offer G-OT4 (phase B): the same seven-query command as Task 4, plus a same-day control. Run only on Destin's yes.

- [ ] **Step 4: G-OT5 — the browser check is Destin's** — OUTSTANDING (chunk `jlbc-approps-fy2025-unibor-0000`)

Give him one chunk id from the rebuilt set that a Layer 1 query hits (e.g. `jlbc-approps-fy2025-unibor-0000` if it was rebuilt, else the first rebuilt AHCCCS chunk) and ask him to: open it from a citation chip, confirm the highlight box is where it was, confirm the cited-text panel shows the subtotal rows separately, and glance at its Budget Documents passage card. Record his answer in STATUS.

- [x] **Step 5: STATUS, spec, archive** — DONE (no `docs/superpowers/archive/` exists; docs stay in place with shipped status)

STATUS phase-summary row:

```markdown
| Operating tables — **phase B** (text-layer rebuild) | ✓ Shipped (2026-09-xx) | N of 4,875 tables rebuilt and verified (per-year table in the section); M unverifiable and left as they were; digit disagreements: D. G-OT0–G-OT3 recorded, G-OT2 status-identical, G-OT4 <run/offered>, G-OT5 <Destin's verdict> |
```

and a section `## Operating tables — phase B shipped (2026-09-xx)` carrying: the per-year table, the extractor/html split (the 329 FY2025 documents where D5 is unproven), the reasons histogram, the digit-disagreement count, both eval run filenames, the snapshot and reversal paths, the G-OT3 sample, and a `### ⏸ Known residuals` list (unverified tables by reason; the html-source documents; the empty page-2 chunks MinerU's merge leaves behind; `ANCHOR_MIN_MATCH` as finally set).

Spec status line: `**Status:** shipped 2026-09-xx (phase A 2026-09-xx, phase B 2026-09-xx).` Move the spec, this plan and the two investigation docs' `status:` to `shipped`. Per the workspace convention, shipped lifecycle docs move to the archive folder if this repo has one (`docs/superpowers/archive/`); if it does not, leave them in place with the shipped status.

- [x] **Step 6: Commit and clean up** — DONE

```bash
git add STATUS.md docs/superpowers eval/results/
git commit -m "docs(tables): phase B shipped — N tables rebuilt, gates recorded, residuals listed"
rm -rf /tmp/table-rehearsal-data
```

---

## Self-review (done while writing; kept so the executor can re-check)

- **Spec coverage.** §1–§2 decisions → Tasks 1–2 (D6), 5–7 (D2, D3, D5), 8–9 (D4); §3.1 → Task 6; §3.2 → Tasks 7, 8; §4 + §4.1 → Task 5; §5 → Tasks 1–4; §6 → Tasks 8–12; §7 gates: G-OT0 Task 5, G-OT1 Task 10, G-OT2 Tasks 11–12, G-OT3 Task 11, G-OT4 Tasks 4 and 12 (offered), G-OT5 Task 12; §8 tests: every bullet has a test in Tasks 1, 5, 6, 7, 8, 9 except the mutation checks, which are Steps in Tasks 1 and 6.
- **Names used across tasks.** `render_labelled`, `find_header`, `peel_markers`, `figure_tokens`, `split_figure_marker`, `normalise_label`, `has_ladder_marker`, `OPERATING_TABLE_DOC_TYPES` (Task 1) are the names imported in Tasks 2, 3, 5, 6, 7, 8. `reconcile`, `count_figure_rows`, `has_merged_cell`, `has_fused_marker` (Task 5) are imported in Tasks 6, 8, 9. `refine_operating_table` returning `RefineOutcome(table, reason, anchor_match)` (Task 6) is used that way in Tasks 7 and 8. `plan_corpus`, `TableChange`, `PlanSummary` (Task 8) are used in Task 9's `repair_tables` and Task 10's `main`. The `repair_common` names (Task 5) match their use in Task 9.
- **What this plan does not do.** It does not build §5 rule 5 (decided by Task 3's count). It does not touch the section-path module beyond moving four helpers. It never runs a paid model.
