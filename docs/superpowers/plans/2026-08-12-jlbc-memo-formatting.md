# JLBC Memo Formatting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Documents produced by AI Mode's `create_document` tool come out looking like a JLBC memo — letterhead, memo block, house typography — instead of Word's stock styling.

**Architecture:** A new top-level `memo/` package renders Markdown into a JLBC-styled `docx.Document`. It is a pure renderer: no I/O, no identity, no knowledge of the shared drive, pinned by its own AST import allowlist. `harness/documents.py` calls it. The analyst's name is resolved at the HTTP route boundary (`app/routes/conversations.py`, which already imports `app.identity`) and threaded down as a finished string, so neither `harness/tools.py` nor `harness/documents.py` gains a path to identity or to the share.

**Tech Stack:** Python 3.12, `python-docx`, FastAPI, pytest; React + TypeScript + vitest for the Settings field.

**Spec:** `docs/superpowers/specs/2026-08-12-jlbc-memo-formatting-design.md` (decisions M1–M12).

**Reference fixture:** `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` — the real FY 2027 instructions memo. Committed, survives a fresh clone, and is what the tests read expected values out of.

## Global Constraints

- **Worktree:** `~/ask-the-budget-az-worktrees/jlbc-memo-formatting`, branch `jlbc-memo-formatting`, already created off `origin/master`. `.venv` is symlinked. Run everything with `.venv/bin/python`.
- **`harness/documents.py` import allowlist** (`tests/test_create_document.py:321`) may gain exactly one entry: `"memo"`. Nothing else.
- **`harness/tools.py` import allowlist** (`tests/test_harness_tools.py:1078`) — `{__future__, json, sys, threading, typing, uuid, retrieval, store, harness, chunking}` — **must not change.** In particular `harness/tools.py` may not import `app.*`. This is why identity is injected rather than resolved.
- **`memo/` may import only** `__future__`, `dataclasses`, `datetime`, `re`, `typing`, `docx`. Pinned by its own test in Task 4.
- **No silent drops.** Unrecognized Markdown renders as a verbatim plain paragraph. This rule already exists in `harness/documents.py` and does not change.
- **Bold goes on runs, never on the `Header` style** — the memo block's labels share that style and are not bold in the reference (spec M8).
- **Copy strings, verbatim:** masthead line 1 `Joint Legislative Budget Committee`; subtitle `Research Memorandum`; footer `Generated with JLBC Agentic Search`; absent recipient `[Recipient(s)]`; sender suffix `, via JLBC Agentic Search`.
- **No eval run.** Per the spec's "The eval rule" section and Destin's confirmation 2026-08-12: `eval/run_eval.py` calls `retrieve()` directly and never reads the system prompt, so it cannot measure the Task 7 prompt edit.
- **Annotate non-trivial edits with a WHY comment** recording the evidence, per CLAUDE.md.

## Measured values (all verified against the reference during planning)

| Constant | Value |
|---|---|
| Margins | top `Inches(0.7)`, bottom `Inches(0.5)`, left/right `Inches(1.0)` |
| Header distance / footer distance | `Inches(0.75)` / `Inches(0.6)` |
| Masthead font size | `Pt(14)`, bold, centered |
| Address font size | `Pt(10)`, tab stop `Twips(7020)`, LEFT |
| Rule | paragraph bottom border, `w:sz` = `18` (eighths of a point = 2.25pt) |
| Memo block columns | `Twips(1458)` / `Twips(7740)` |
| Body | Calibri `Pt(10.5)` on the `Normal` style |
| Bullet indent | `Inches(0.1875)` |
| Footer note | `Pt(9)`, centered |

**Two traps found during planning, both verified:**

1. **python-docx's default `Title` style carries a blue bottom border** (`w:pBdr`, `sz=8`, `themeColor accent1`) and `spacing after 300`. The reference has neither. Left in place it draws a stray blue line directly above the real 2.25pt rule. Both must be stripped.
2. **`table.autofit = False` alone does not fix column widths** — they round-tripped as `2743200` EMU each instead of `925830` / `4914900`. A `<w:tblLayout w:type="fixed"/>` element on `tblPr` is required as well.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `memo/__init__.py` | The one public entry point, `render()`. Assembles chrome + body. |
| `memo/style.py` | Every measured constant, plus the document chrome: page setup, masthead, rule, memo block, header, footer. |
| `memo/markdown.py` | Markdown → Word body. Ported from `harness/documents.py`'s existing renderer, remapped onto memo styles. |
| `tests/test_jlbc_memo.py` | Structural assertions, reading expected values out of the reference docx. |
| `tests/test_display_name.py` | Name resolution order and the `machine.json` override. |

**Modify:**

| File | Change |
|---|---|
| `harness/documents.py` | `_render_docx` delegates to `memo.render`; the Markdown helpers move to `memo/markdown.py`; `materialize` gains `sender` / `recipient`. |
| `harness/tools.py` | `create_document` schema gains optional `to`; `ToolExecutor` gains `display_name`; new `_opt_str` helper. |
| `harness/session.py` | `HarnessSession` accepts and forwards `display_name`. |
| `harness/system-prompt.md` | The `create_document` section only. |
| `app/identity.py` | New `display_name()` + `_windows_display_name()`. |
| `app/machine_config.py` | `read_display_name()` / `set_display_name()`. |
| `app/routes/admin.py` | `GET /api/me` returns `display_name`; new `PUT /api/me/display-name`. |
| `app/routes/conversations.py` | Passes `display_name=` when building `HarnessSession`. |
| `webapp/src/api.ts` | `Me.display_name`, `setDisplayName()`. |
| `webapp/src/pages/Settings.tsx` | The name field. |
| `tests/test_create_document.py` | Allowlist gains `"memo"`; styling assertions updated. |

---

## Task 1: The `memo/` package — chrome

**Files:**
- Create: `memo/__init__.py`, `memo/style.py`
- Test: `tests/test_jlbc_memo.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `memo.style.new_document() -> docx.document.Document`
  - `memo.style.add_masthead(doc, *, subtitle: str) -> None`
  - `memo.style.add_rule(doc) -> None`
  - `memo.style.MASTHEAD_TITLE`, `SUBTITLE`, `FOOTER_NOTE`, `NO_RECIPIENT`, `SENDER_SUFFIX`, `TAB_STOP_TWIPS`, `LABEL_COL_TWIPS`, `VALUE_COL_TWIPS`, `BODY_PT`, `BULLET_INDENT`
  - `memo.render(body_markdown, *, subject, sender="", recipient="", date=None) -> docx.document.Document` (stub in this task; completed in Task 3)

- [ ] **Step 1: Write the failing test**

Create `tests/test_jlbc_memo.py`:

```python
"""The renderer is measured against the committed reference memo, not
against remembered numbers.

`REFERENCE` is `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx`
— the real FY 2027 Appropriations Report Round 1 instructions memo. Where
a value can be read out of it, these tests read it, so a future JLBC style
change is a fixture swap rather than a code rewrite.

Two structural elements of that document are INVISIBLE to
`Document.paragraphs` and were missed on a first pass: the horizontal rule
is a VML `pict`, and the DATE/TO/FROM/SUBJECT block is a borderless table.
Anything that needs to see them must walk `document.body` elements.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt

import memo
from memo import style

REFERENCE = (
    Path(__file__).resolve().parents[1]
    / "samples"
    / "raw-docx"
    / "jlbc-staff-memorandum-style-reference.docx"
)


@pytest.fixture(scope="module")
def reference():
    return Document(str(REFERENCE))


@pytest.fixture
def rendered():
    return memo.render(
        "Body text.",
        subject="FY 2027 AHCCCS Appropriations Summary",
        sender="Destin Jarrett",
        recipient="",
        date="August 12, 2026",
    )


def test_page_margins_match_the_reference_to_the_emu(rendered, reference):
    ours, theirs = rendered.sections[0], reference.sections[0]
    assert ours.top_margin == theirs.top_margin
    assert ours.bottom_margin == theirs.bottom_margin
    assert ours.left_margin == theirs.left_margin
    assert ours.right_margin == theirs.right_margin
    assert ours.header_distance == theirs.header_distance
    assert ours.footer_distance == theirs.footer_distance


def test_the_masthead_carries_the_letterhead_with_the_research_subtitle(rendered):
    texts = [p.text for p in rendered.paragraphs[:4]]
    assert texts[0] == "Joint Legislative Budget Committee"
    assert texts[1] == "Research Memorandum"
    assert texts[2].startswith("1716 West Adams\t")
    assert texts[3].startswith("Phoenix, Arizona 85007\t")


def test_the_masthead_lines_are_14pt_bold_centered(rendered):
    title_style = rendered.styles["Title"]
    assert title_style.font.size == Pt(14)
    assert title_style.font.bold is True
    assert title_style.paragraph_format.alignment == WD_ALIGN_PARAGRAPH.CENTER
    subtitle = rendered.paragraphs[1]
    assert subtitle.alignment == WD_ALIGN_PARAGRAPH.CENTER
    assert subtitle.runs[0].bold is True
    assert subtitle.runs[0].font.size == Pt(14)


def test_the_title_styles_default_blue_border_and_spacing_are_stripped(rendered):
    """python-docx's default `Title` style ships a blue bottom border
    (sz 8, accent1) and `spacing after 300`. The reference has neither, and
    leaving them draws a stray blue line directly above the real 2.25pt
    rule — two lines where the memo has one. Verified against a stock
    `Document()` during planning."""
    assert "pBdr" not in rendered.styles["Title"].element.xml
    assert rendered.styles["Title"].paragraph_format.space_after == Pt(0)


def test_the_address_lines_use_a_left_tab_stop_at_7020_twips(rendered):
    for index in (2, 3):
        stops = list(rendered.paragraphs[index].paragraph_format.tab_stops)
        assert len(stops) == 1
        assert stops[0].position == style.TAB_STOP_TWIPS
        assert rendered.paragraphs[index].runs[0].font.size == Pt(10)


def test_the_rule_is_a_225pt_paragraph_bottom_border(rendered):
    rule = rendered.paragraphs[4]
    assert "pBdr" in rule._p.xml
    assert 'w:sz="18"' in rule._p.xml  # 18 eighths of a point = 2.25pt


def test_the_footer_note_appears_on_the_first_page_too(rendered):
    section = rendered.sections[0]
    assert section.different_first_page_header_footer is True
    for footer in (section.footer, section.first_page_footer):
        assert footer.paragraphs[0].text == "Generated with JLBC Agentic Search"
        assert footer.paragraphs[0].runs[0].font.size == Pt(9)


def test_later_pages_carry_a_page_number_and_the_first_page_does_not(rendered):
    section = rendered.sections[0]
    assert "PAGE" in section.header.paragraphs[0]._p.xml
    assert section.first_page_header.paragraphs[0].text.strip() == ""


def test_body_text_is_calibri_105pt_on_the_normal_style(rendered):
    """Set on the style, not per-run, so bullets and table cells inherit
    (spec M9). The reference sets 10.5 on each run over a 12pt Normal;
    same rendered result, one place to change."""
    normal = rendered.styles["Normal"]
    assert normal.font.name == "Calibri"
    assert normal.font.size == Pt(10.5)
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ~/ask-the-budget-az-worktrees/jlbc-memo-formatting
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'memo'`.

- [ ] **Step 3: Write `memo/style.py`**

```python
"""Every measured value of the JLBC memo, and the chrome that surrounds
the body.

Measured from `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx`
— the real FY 2027 Appropriations Report Round 1 instructions memo — not
eyeballed. `tests/test_jlbc_memo.py` reads most of these back out of that
file, so changing the house style is a fixture swap.

This module writes nothing and reads nothing. It builds a Document object
and hands it back. That is what lets `harness/documents.py` import it
without widening Invariant 7's blast radius (spec M1).
"""
from __future__ import annotations

from datetime import date as _date

from docx import Document
from docx.document import Document as DocumentT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, Twips

# --- copy, verbatim -------------------------------------------------------
MASTHEAD_TITLE = "Joint Legislative Budget Committee"
# NOT "Staff Memorandum" (spec M2). A Staff Memorandum is a specific JLBC
# work product with specific authorship; a machine-drafted document must
# not claim to be one, even though it carries the letterhead.
SUBTITLE = "Research Memorandum"
ADDRESS_LINES = (
    ("1716 West Adams", "Telephone: (602) 926-5491"),
    ("Phoenix, Arizona 85007", "azjlbc.gov"),
)
FOOTER_NOTE = "Generated with JLBC Agentic Search"
SENDER_SUFFIX = ", via JLBC Agentic Search"
# A visible placeholder, not an empty cell: an empty cell beside a label
# reads as a rendering bug (spec M4).
NO_RECIPIENT = "[Recipient(s)]"

# --- measured geometry ----------------------------------------------------
TOP_MARGIN = Inches(0.7)
BOTTOM_MARGIN = Inches(0.5)
SIDE_MARGIN = Inches(1.0)
HEADER_DISTANCE = Inches(0.75)
FOOTER_DISTANCE = Inches(0.6)

MASTHEAD_PT = Pt(14)
ADDRESS_PT = Pt(10)
BODY_PT = Pt(10.5)
FOOTER_PT = Pt(9)

TAB_STOP_TWIPS = Twips(7020)
LABEL_COL_TWIPS = Twips(1458)
VALUE_COL_TWIPS = Twips(7740)
BULLET_INDENT = Inches(0.1875)

# Word expresses border weight in EIGHTHS of a point, so 2.25pt is 18.
RULE_SIZE_EIGHTHS = "18"

BODY_FONT = "Calibri"


def today_long() -> str:
    """`August 12, 2026`. Built without `%-d`/`%#d`, which differ between
    glibc and the Windows CRT — this app ships to both."""
    now = _date.today()
    return f"{now.strftime('%B')} {now.day}, {now.year}"


def new_document() -> DocumentT:
    """A blank document with the page set up and the styles corrected."""
    doc = Document()
    section = doc.sections[0]
    section.top_margin = TOP_MARGIN
    section.bottom_margin = BOTTOM_MARGIN
    section.left_margin = SIDE_MARGIN
    section.right_margin = SIDE_MARGIN
    section.header_distance = HEADER_DISTANCE
    section.footer_distance = FOOTER_DISTANCE
    # The reference suppresses the page number on page 1, so the first
    # page needs its own header part.
    section.different_first_page_header_footer = True

    # Size on the STYLE, not per-run (spec M9): bullets, table cells and
    # any paragraph a later edit adds all inherit, instead of depending on
    # someone remembering to size each run. The reference sets 10.5 on
    # every run over a 12pt Normal; identical rendered result.
    normal = doc.styles["Normal"]
    normal.font.name = BODY_FONT
    normal.font.size = BODY_PT

    _fix_title_style(doc)
    _add_page_number_header(section)
    _add_footer_note(section)
    return doc


def _fix_title_style(doc: DocumentT) -> None:
    """python-docx's stock `Title` style is not JLBC's.

    It ships a blue bottom border (`w:pBdr`, sz 8, themeColor accent1) and
    `spacing after 300`. The reference has neither — verified by diffing
    both style definitions during planning. Left alone, the masthead draws
    a stray blue line immediately above the real 2.25pt rule, so the memo
    appears to have two.
    """
    title = doc.styles["Title"]
    title.font.size = MASTHEAD_PT
    title.font.bold = True
    title.font.name = BODY_FONT
    title.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    title.paragraph_format.space_after = Pt(0)
    pPr = title.element.get_or_add_pPr()
    for border in pPr.findall(qn("w:pBdr")):
        pPr.remove(border)


def _add_page_number_header(section) -> None:
    """`- 5 -` on page 2 onward; nothing on page 1."""
    paragraph = section.header.paragraphs[0]
    paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph.add_run("- ")
    field = OxmlElement("w:fldSimple")
    field.set(qn("w:instr"), "PAGE")
    paragraph._p.append(field)
    paragraph.add_run(" -")


def _add_footer_note(section) -> None:
    """The disclosure (spec M3), on every page.

    In the FOOTER rather than the body because a body line sits in the
    analyst's prose and gets deleted; a footer travels with the document,
    survives printing, and costs no vertical space. `different_first_page`
    is set for the header's sake, which means page 1 has its own footer
    part and needs the note written into it separately.
    """
    for footer in (section.footer, section.first_page_footer):
        paragraph = footer.paragraphs[0]
        paragraph.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = paragraph.add_run(FOOTER_NOTE)
        run.font.size = FOOTER_PT


def add_masthead(doc: DocumentT, *, subtitle: str = SUBTITLE) -> None:
    doc.add_paragraph(MASTHEAD_TITLE, style="Title")

    line = doc.add_paragraph()
    line.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = line.add_run(subtitle)
    run.bold = True
    run.font.size = MASTHEAD_PT

    for left, right in ADDRESS_LINES:
        paragraph = doc.add_paragraph()
        paragraph.paragraph_format.tab_stops.add_tab_stop(
            TAB_STOP_TWIPS, WD_TAB_ALIGNMENT.LEFT
        )
        run = paragraph.add_run(f"{left}\t{right}")
        run.font.size = ADDRESS_PT


def add_rule(doc: DocumentT) -> None:
    """The line under the letterhead.

    The reference draws it as a VML `pict` at 2.25pt stroke. A paragraph
    bottom border is visually identical, is plain WordprocessingML, and
    needs no embedded drawing part (spec M10).
    """
    paragraph = doc.add_paragraph()
    pPr = paragraph._p.get_or_add_pPr()
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), RULE_SIZE_EIGHTHS)
    bottom.set(qn("w:space"), "1")
    bottom.set(qn("w:color"), "000000")
    borders.append(bottom)
    pPr.append(borders)
```

- [ ] **Step 4: Write `memo/__init__.py` (chrome only — the body arrives in Task 3)**

```python
"""Render Markdown as a JLBC memo.

The one public entry point is `render()`. It returns a `Document`; it does
not save, does not name a file, and does not know who is asking. See
`docs/superpowers/specs/2026-08-12-jlbc-memo-formatting-design.md`.
"""
from __future__ import annotations

from docx.document import Document as DocumentT

from memo import style

__all__ = ["render"]


def render(
    body_markdown: str,
    *,
    subject: str,
    sender: str = "",
    recipient: str = "",
    date: str | None = None,
) -> DocumentT:
    """Build the memo.

    Every argument is a finished string. Resolving who the analyst is and
    what today's date is happens at the HTTP boundary, not here — that
    split is what keeps this module free of any path to identity or to the
    shared drive (spec M7).
    """
    doc = style.new_document()
    style.add_masthead(doc)
    style.add_rule(doc)
    return doc
```

- [ ] **Step 5: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: PASS for every test in this task. (`test_body_text_is_calibri_105pt_on_the_normal_style` passes too — it reads the style, not a rendered run.)

- [ ] **Step 6: Commit**

```bash
git add memo/ tests/test_jlbc_memo.py
git commit -m "feat(memo): JLBC memo chrome — page setup, masthead, rule, footer

Measured from the committed FY 2027 instructions memo, not eyeballed.

Two traps verified during planning and pinned by tests: python-docx's
stock Title style ships a blue bottom border and spacing-after-300 that
the reference does not have (left in place it draws a second line right
above the real rule), and the footer note needs writing into the
first-page footer part separately because different_first_page is set
for the page-number header.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: The DATE / TO / FROM / SUBJECT block

**Files:**
- Modify: `memo/style.py`, `memo/__init__.py`
- Test: `tests/test_jlbc_memo.py`

**Interfaces:**
- Consumes: `memo.style.LABEL_COL_TWIPS`, `VALUE_COL_TWIPS`, `NO_RECIPIENT`, `SENDER_SUFFIX`, `today_long()`.
- Produces: `memo.style.add_memo_block(doc, *, date: str, recipient: str, sender: str, subject: str) -> None`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jlbc_memo.py`:

```python
def test_the_memo_block_is_a_borderless_7x2_table(rendered, reference):
    table = rendered.tables[0]
    theirs = reference.tables[0]
    assert len(table.rows) == len(theirs.rows) == 7
    assert len(table.columns) == 2
    assert [c.width for c in table.columns] == [c.width for c in theirs.columns]
    assert "tblBorders" not in table.style.element.xml


def test_the_memo_block_labels_are_in_order_and_not_bold(rendered):
    """The labels share the `Header` paragraph style with section
    headings, and in the reference they are NOT bold — only the headings
    are, via direct run formatting. A future edit that puts bold on the
    style instead of the run bolds these as a side effect (spec M8)."""
    table = rendered.tables[0]
    labels = [table.rows[i].cells[0].text for i in (0, 2, 4, 6)]
    assert labels == ["DATE:", "TO:", "FROM:", "SUBJECT:"]
    for row in (0, 2, 4, 6):
        paragraph = table.rows[row].cells[0].paragraphs[0]
        assert paragraph.style.name == "Header"
        assert paragraph.runs[0].bold is not True


def test_the_subject_row_carries_the_documents_title(rendered):
    assert (
        rendered.tables[0].rows[6].cells[1].text
        == "FY 2027 AHCCCS Appropriations Summary"
    )


def test_there_is_no_separate_title_line_in_the_body(rendered):
    """The reference has none, and Word's `Title` style is already spent
    on the masthead. The subject IS the title (spec M4)."""
    body_texts = [p.text for p in rendered.paragraphs]
    assert body_texts.count("FY 2027 AHCCCS Appropriations Summary") == 0


def test_an_absent_recipient_renders_a_visible_placeholder(rendered):
    assert rendered.tables[0].rows[2].cells[1].text == "[Recipient(s)]"


def test_a_supplied_recipient_is_used_verbatim():
    doc = memo.render(
        "Body.", subject="S", sender="A. Analyst", recipient="Director Smith"
    )
    assert doc.tables[0].rows[2].cells[1].text == "Director Smith"


def test_the_sender_row_names_the_analyst_and_the_tool(rendered):
    assert (
        rendered.tables[0].rows[4].cells[1].text
        == "Destin Jarrett, via JLBC Agentic Search"
    )


def test_an_unknown_analyst_leaves_the_tool_alone_on_the_from_line():
    """Degrades to the tool's name rather than a dangling comma. An
    unnameable user should lose attribution, not get a malformed memo —
    the same posture `app.identity.current_user` already takes."""
    doc = memo.render("Body.", subject="S", sender="")
    assert doc.tables[0].rows[4].cells[1].text == "JLBC Agentic Search"


def test_the_date_defaults_to_today_in_long_form():
    from memo.style import today_long

    doc = memo.render("Body.", subject="S", sender="A")
    assert doc.tables[0].rows[0].cells[1].text == today_long()
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: FAIL with `IndexError: list index out of range` on `rendered.tables[0]` — no table is emitted yet.

- [ ] **Step 3: Add `add_memo_block` to `memo/style.py`**

```python
MEMO_LABELS = ("DATE:", "TO:", "FROM:", "SUBJECT:")


def add_memo_block(
    doc: DocumentT,
    *,
    date: str,
    recipient: str,
    sender: str,
    subject: str,
) -> None:
    """The DATE / TO / FROM / SUBJECT block.

    A borderless two-column table with a blank spacer row between each
    pair, exactly as the reference builds it. It is invisible to
    `Document.paragraphs`, which is why a first pass at measuring this
    document missed it entirely.
    """
    sender_line = f"{sender}{SENDER_SUFFIX}" if sender else SENDER_SUFFIX.lstrip(", ")
    values = (date, recipient or NO_RECIPIENT, sender_line, subject)

    table = doc.add_table(rows=0, cols=2)
    table.autofit = False
    # `autofit = False` ALONE DOES NOT WORK. Measured during planning:
    # without an explicit fixed layout the widths round-trip as 2743200
    # EMU each (Word's default split) instead of 925830 / 4914900, and
    # the labels wrap. The reference carries this element too.
    layout = OxmlElement("w:tblLayout")
    layout.set(qn("w:type"), "fixed")
    table._tbl.tblPr.append(layout)
    table.columns[0].width = LABEL_COL_TWIPS
    table.columns[1].width = VALUE_COL_TWIPS

    for index, (label, value) in enumerate(zip(MEMO_LABELS, values)):
        if index:
            spacer = table.add_row()
            spacer.cells[0].width = LABEL_COL_TWIPS
            spacer.cells[1].width = VALUE_COL_TWIPS
        row = table.add_row()
        row.cells[0].width = LABEL_COL_TWIPS
        row.cells[1].width = VALUE_COL_TWIPS
        # `Header` style on the label cell, matching the reference. Bold
        # is deliberately NOT applied — see the test that pins this.
        label_paragraph = row.cells[0].paragraphs[0]
        label_paragraph.style = doc.styles["Header"]
        label_paragraph.add_run(label)
        row.cells[1].paragraphs[0].add_run(value)
```

- [ ] **Step 4: Call it from `memo/__init__.py`**

Replace the body of `render()`:

```python
    doc = style.new_document()
    style.add_masthead(doc)
    style.add_rule(doc)
    style.add_memo_block(
        doc,
        date=date or style.today_long(),
        recipient=recipient,
        sender=sender,
        subject=subject,
    )
    return doc
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: PASS, all tests from Tasks 1 and 2.

- [ ] **Step 6: Commit**

```bash
git add memo/ tests/test_jlbc_memo.py
git commit -m "feat(memo): the DATE/TO/FROM/SUBJECT block

The subject row is where create_document's title goes; there is no
separate title line, because the reference has none and Word's Title
style is already spent on the masthead.

table.autofit = False alone does not hold column widths — measured, they
round-trip as 2743200 EMU each instead of 925830/4914900. An explicit
<w:tblLayout w:type=\"fixed\"/> is required, and the reference carries
one too.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: The body — Markdown mapping

**Files:**
- Create: `memo/markdown.py`
- Modify: `memo/__init__.py`
- Test: `tests/test_jlbc_memo.py`

**Interfaces:**
- Consumes: `memo.style.BULLET_INDENT`.
- Produces: `memo.markdown.render_body(doc: DocumentT, body_markdown: str) -> None`

**Porting note:** the regexes and the table/bullet/verbatim logic come from `harness/documents.py`'s current `_render_docx` and its helpers (`_HEADING_RE`, `_BULLET_RE`, `_BOLD_RE`, `_TABLE_SEPARATOR_RE`, `_UNESCAPED_PIPE_RE`, `_is_table_row`, `_split_row`, `_add_runs`, `_add_table`). Move them; do not rewrite them. They carry fixes for real defects — notably that headings and bullets are classified *before* table rows, because `- Agency | Amount` is a bullet and was being turned into a malformed table.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jlbc_memo.py`:

```python
def _body_paragraphs(doc):
    """Paragraphs after the chrome. The masthead is 4 paragraphs, then the
    rule, then the memo block (a table, which does not appear here)."""
    return doc.paragraphs[5:]


def test_a_heading_becomes_a_bold_header_styled_paragraph():
    doc = memo.render("## Policy Issues\n\nText.", subject="S", sender="A")
    heading = [p for p in _body_paragraphs(doc) if p.text == "Policy Issues"][0]
    assert heading.style.name == "Header"
    assert heading.runs[0].bold is True


def test_bold_is_never_put_on_the_header_style_itself():
    """The memo block's labels share this style and must stay unbold."""
    doc = memo.render("## Policy Issues", subject="S", sender="A")
    assert doc.styles["Header"].font.bold is not True


def test_a_deep_heading_becomes_a_bold_run_in_label():
    """`###` and deeper map to the memo's third level, which is a bold
    run-in label (`BUDS Table: ...`), not another heading tier."""
    doc = memo.render("### BUDS Table", subject="S", sender="A")
    label = [p for p in _body_paragraphs(doc) if p.text == "BUDS Table"][0]
    assert label.style.name == "Normal"
    assert label.runs[0].bold is True


def test_a_bullet_is_indented_to_the_house_measure():
    doc = memo.render("- One item", subject="S", sender="A")
    bullet = [p for p in _body_paragraphs(doc) if p.text == "One item"][0]
    assert bullet.style.name == "List Bullet"
    assert bullet.paragraph_format.left_indent == style.BULLET_INDENT


def test_bold_markers_become_bold_runs():
    doc = memo.render("The **budget includes** $5.", subject="S", sender="A")
    paragraph = [p for p in _body_paragraphs(doc) if p.text.startswith("The ")][0]
    assert [(r.text, r.bold) for r in paragraph.runs] == [
        ("The ", None),
        ("budget includes", True),
        (" $5.", None),
    ]


def test_a_pipe_table_becomes_a_real_table_after_the_memo_block():
    doc = memo.render(
        "| Agency | Amount |\n|---|---|\n| ADC | $5 |", subject="S", sender="A"
    )
    assert len(doc.tables) == 2  # memo block + this one
    body_table = doc.tables[1]
    assert body_table.style.name == "Table Grid"
    assert [c.text for c in body_table.rows[0].cells] == ["Agency", "Amount"]
    assert body_table.rows[0].cells[0].paragraphs[0].runs[0].bold is True


def test_a_bullet_containing_a_pipe_stays_a_bullet():
    """Regression, carried over from harness/documents.py: classifying
    table rows before bullets turned `- Agency | Amount` into a malformed
    table whose first cell read `- Agency`."""
    doc = memo.render("- Agency | Amount\n|---|---|", subject="S", sender="A")
    assert len(doc.tables) == 1  # the memo block only
    bullet = [p for p in _body_paragraphs(doc) if "Agency" in p.text][0]
    assert bullet.style.name == "List Bullet"


def test_unrecognized_markup_survives_verbatim():
    """No silent drops. An analyst who receives a memo with a section
    quietly missing has no way to know it happened; a blockquote showing
    its `>` is a far better failure."""
    doc = memo.render("> quoted line\n\n1. numbered", subject="S", sender="A")
    texts = [p.text for p in _body_paragraphs(doc)]
    assert "> quoted line" in texts
    assert "1. numbered" in texts
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: FAIL — `IndexError: list index out of range` on the list comprehensions, because `render()` emits no body yet.

- [ ] **Step 3: Write `memo/markdown.py`**

```python
"""Markdown -> the memo's body.

Ported from `harness/documents.py`'s renderer, remapped onto JLBC's
styles. The regexes and the classification ORDER are carried over
unchanged: each encodes a fix for a real defect, and the ordering one is
load-bearing (see `render_body`).

THE RULE THAT MATTERS, and it is unchanged: anything unrecognized becomes
a plain paragraph, verbatim. Never a silent drop. An analyst who receives
a memo with a section quietly missing has no way to know it happened, and
that is a far worse failure than a blockquote rendering as ordinary text.
"""
from __future__ import annotations

import re

from docx.document import Document as DocumentT

from memo.style import BULLET_INDENT

_HEADING_RE = re.compile(r"^(#{1,6})\s+(\S.*)$")
_BULLET_RE = re.compile(r"^[-*]\s+(\S.*)$")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*")
# A separator row: only dashes, colons, pipes and spaces, and at least one
# dash. Requiring the PRECEDING line to be a row too keeps a bare `---`
# thematic break from being mistaken for a table.
_TABLE_SEPARATOR_RE = re.compile(r"^\|?[\s:|-]*-[\s:|-]*\|?$")
# Split on pipes that are not backslash-escaped — primer/docx_to_md.py
# escapes a literal pipe inside a cell as `\|`, so this is the unescape.
_UNESCAPED_PIPE_RE = re.compile(r"(?<!\\)\|")

# JLBC's memo has exactly ONE heading level plus bold run-in labels
# (`Policy Issues – ...`, `BUDS Table: ...`). `#`/`##` map to the section
# heading; anything deeper maps to the run-in label, which is what the
# third level actually is in this house style (spec M8).
_SECTION_HEADING_DEPTH = 2


def _is_table_row(line: str) -> bool:
    return "|" in line


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    return [c.strip().replace("\\|", "|") for c in _UNESCAPED_PIPE_RE.split(inner)]


def _add_runs(paragraph, text: str) -> None:
    """Write `text` into a paragraph, turning **…** into bold runs.

    Everything outside the markers is emitted as-is, so an unmatched `**`
    stays visible rather than eating the rest of the line.
    """
    position = 0
    for match in _BOLD_RE.finditer(text):
        if match.start() > position:
            paragraph.add_run(text[position : match.start()])
        paragraph.add_run(match.group(1)).bold = True
        position = match.end()
    if position < len(text):
        paragraph.add_run(text[position:])


def _add_table(doc: DocumentT, rows: list[list[str]]) -> None:
    """Render collected pipe-table rows as a real Word table.

    Short rows are PADDED rather than dropped: a ragged row is a
    formatting slip in the model's output, not a reason to lose the cell
    values it does contain.
    """
    columns = max(len(r) for r in rows)
    table = doc.add_table(rows=0, cols=columns)
    table.style = "Table Grid"
    for index, row in enumerate(rows):
        cells = table.add_row().cells
        for column in range(columns):
            value = row[column] if column < len(row) else ""
            paragraph = cells[column].paragraphs[0]
            _add_runs(paragraph, value)
            if index == 0:
                for run in paragraph.runs:
                    run.bold = True


def _add_heading(doc: DocumentT, level: int, text: str) -> None:
    if level <= _SECTION_HEADING_DEPTH:
        paragraph = doc.add_paragraph(style="Header")
    else:
        paragraph = doc.add_paragraph()
    _add_runs(paragraph, text)
    # BOLD ON THE RUNS, NEVER ON THE STYLE. The memo block's DATE/TO/FROM/
    # SUBJECT labels share the `Header` paragraph style and are NOT bold in
    # the reference; putting bold on the style bolds them as a side effect.
    for run in paragraph.runs:
        run.bold = True


def render_body(doc: DocumentT, body_markdown: str) -> None:
    lines = body_markdown.splitlines()
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        # Classify headings and bullets FIRST, because their text may
        # legitimately contain a pipe: "- Agency | Amount" is a bullet,
        # and treating it as a table header row (which it structurally
        # resembles, if the next line happens to be dashes) produced a
        # malformed table whose first cell was the literal "- Agency".
        heading = _HEADING_RE.match(stripped)
        bullet = None if heading else _BULLET_RE.match(stripped)

        # A table row is only a table row when the NEXT line is a
        # separator; otherwise it is ordinary text containing pipes.
        if (
            not heading
            and not bullet
            and _is_table_row(stripped)
            and index + 1 < len(lines)
            and _TABLE_SEPARATOR_RE.match(lines[index + 1].strip())
            and "|" in lines[index + 1]
        ):
            rows = [_split_row(stripped)]
            index += 2  # header + separator
            while index < len(lines) and _is_table_row(lines[index].strip()):
                rows.append(_split_row(lines[index].strip()))
                index += 1
            _add_table(doc, rows)
            continue

        if heading:
            _add_heading(doc, len(heading.group(1)), heading.group(2))
            index += 1
            continue

        if bullet:
            paragraph = doc.add_paragraph(style="List Bullet")
            # `List Bullet` rather than the reference's `List Paragraph`:
            # it carries the bullet glyph through numbering.xml in
            # python-docx's default template, where `List Paragraph` does
            # not. The reference's bullets come from a numbering
            # definition its own file ships. Same rendered result, no
            # hand-authored numbering part.
            paragraph.paragraph_format.left_indent = BULLET_INDENT
            _add_runs(paragraph, bullet.group(1))
            index += 1
            continue

        _add_runs(doc.add_paragraph(), line)
        index += 1
```

- [ ] **Step 4: Call it from `memo/__init__.py`**

Add the import and the final call:

```python
from memo import markdown, style
```

and, in `render()`, immediately before `return doc`:

```python
    markdown.render_body(doc, body_markdown)
```

- [ ] **Step 5: Run tests**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: PASS, every test from Tasks 1–3.

- [ ] **Step 6: Commit**

```bash
git add memo/ tests/test_jlbc_memo.py
git commit -m "feat(memo): Markdown body mapped onto the house styles

#/## become the Header-styled section heading JLBC actually uses; ###+
becomes the bold run-in label that is its real third level. Bullets carry
the 0.1875in house indent.

The regexes and the classification order are ported unchanged from
harness/documents.py — headings and bullets are classified before table
rows because '- Agency | Amount' is a bullet, and the other order turned
it into a malformed table.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: Wire `harness/documents.py` to `memo/`

**Files:**
- Modify: `harness/documents.py`, `tests/test_create_document.py`
- Test: `tests/test_jlbc_memo.py`

**Interfaces:**
- Consumes: `memo.render`.
- Produces: `harness.documents.materialize(title, body_markdown, fmt="docx", *, user="", sender="", recipient="") -> tuple[str, Path]`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jlbc_memo.py`:

```python
def test_memo_package_imports_are_allowlisted():
    """The transitive half of Invariant 7 (spec M1). `harness/documents.py`
    is allowed to import `memo`; that concession is only safe while `memo`
    itself cannot reach the shared drive. Adding an entry here has to be a
    conscious edit, exactly like the allowlist it backs."""
    import ast

    allowed = {"__future__", "dataclasses", "datetime", "re", "typing", "docx", "memo"}
    package = Path(memo.__file__).parent
    roots: set[str] = set()
    for source in package.glob("*.py"):
        tree = ast.parse(source.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                roots.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                roots.add(node.module.split(".")[0])
    assert roots <= allowed, f"unexpected imports: {sorted(roots - allowed)}"


def test_materialize_renders_a_memo_and_keeps_the_title_in_properties(tmp_path, monkeypatch):
    from harness import documents

    monkeypatch.setenv(documents.DOCUMENTS_DIR_ENV, str(tmp_path))
    documents.reset_registry()
    _token, path = documents.materialize(
        "FY 2027 Summary",
        "## Policy Issues\n\nText.",
        "docx",
        user="djarrett",
        sender="Destin Jarrett",
        recipient="Director Smith",
    )
    doc = Document(str(path))
    assert doc.core_properties.title == "FY 2027 Summary"
    assert doc.paragraphs[0].text == "Joint Legislative Budget Committee"
    assert doc.tables[0].rows[6].cells[1].text == "FY 2027 Summary"
    assert doc.tables[0].rows[2].cells[1].text == "Director Smith"
    assert doc.tables[0].rows[4].cells[1].text == "Destin Jarrett, via JLBC Agentic Search"


def test_the_markdown_format_path_is_untouched(tmp_path, monkeypatch):
    """`format="md"` stays byte-faithful to what the model wrote (spec
    M12). It is the escape hatch for an analyst who wants the text without
    the formatting, and round-tripping it could lose a construct."""
    from harness import documents

    monkeypatch.setenv(documents.DOCUMENTS_DIR_ENV, str(tmp_path))
    documents.reset_registry()
    body = "> quoted\n\n1. numbered\n"
    _token, path = documents.materialize("T", body, "md")
    assert path.read_text(encoding="utf-8") == body
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py -q
```

Expected: FAIL — `TypeError: materialize() got an unexpected keyword argument 'sender'`.

- [ ] **Step 3: Edit `harness/documents.py`**

3a. Add `"memo"` to the module docstring's note and replace the `# Markdown -> Word` section. **Delete** `_HEADING_RE`, `_BULLET_RE`, `_BOLD_RE`, `_TABLE_SEPARATOR_RE`, `_UNESCAPED_PIPE_RE`, `_is_table_row`, `_split_row`, `_add_runs`, `_add_table` — they now live in `memo/markdown.py`.

3b. Replace `_render_docx` with:

```python
def _render_docx(
    title: str,
    body_markdown: str,
    target: Path,
    *,
    sender: str,
    recipient: str,
) -> None:
    """Write the .docx as a JLBC memo.

    `memo` is imported HERE, not at module scope — see the module
    docstring on staying import-light. It is the ONLY non-stdlib import
    this module is permitted beyond `docx`, and it is safe precisely
    because `memo` carries its own import allowlist test: it renders and
    nothing else, so it has no path to the share either.
    """
    from memo import render

    doc = render(
        body_markdown,
        subject=title,
        sender=sender,
        recipient=recipient,
    )
    # The subject row carries the title on the page; this carries it into
    # Word's document properties, which is what an email client and File
    # Explorer's preview pane read.
    doc.core_properties.title = title
    doc.save(str(target))
```

3c. Change `materialize`'s signature and its `docx` branch:

```python
def materialize(
    title: str,
    body_markdown: str,
    fmt: str = "docx",
    *,
    user: str = "",
    sender: str = "",
    recipient: str = "",
) -> tuple[str, Path]:
```

and

```python
    else:
        _render_docx(title, body_markdown, target, sender=sender, recipient=recipient)
```

Add to `materialize`'s docstring:

```
    `sender` and `recipient` are FINISHED STRINGS resolved by the caller.
    This module does not know who the analyst is and must not learn —
    resolving a display name means reading per-machine config, which is
    exactly the kind of reach Invariant 7's import allowlist forbids here.
```

- [ ] **Step 4: Update `tests/test_create_document.py`**

4a. In `test_documents_module_cannot_reach_the_shared_data_dir`, add `"memo"` to `allowed`, with a comment:

```python
        # `memo` renders Markdown into a Word document and does nothing
        # else. Safe to allow because tests/test_jlbc_memo.py pins ITS
        # imports the same way, so the guarantee stays structural and
        # becomes transitive rather than becoming a promise.
        "memo",
```

4b. Find every assertion pinning the old generic output — search for `Title`, `Heading`, `List Bullet`, `add_heading`, and `paragraphs[0]`:

```bash
grep -n "Title\|Heading\|List Bullet\|paragraphs\[0\]" tests/test_create_document.py
```

Update each to the memo shape: the document's first paragraph is now `Joint Legislative Budget Committee`, the title lives in `tables[0].rows[6].cells[1]`, headings are `Header`-styled, and bullets are `List Bullet` at 0.1875″. **Update them deliberately — do not weaken an assertion to make it pass.** If one asserted a behaviour that still matters (no silent drops, table rendering, the filename sanitizer), keep the behaviour and re-point the locator.

- [ ] **Step 5: Run both suites**

```bash
.venv/bin/python -m pytest tests/test_jlbc_memo.py tests/test_create_document.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add memo/ harness/documents.py tests/test_jlbc_memo.py tests/test_create_document.py
git commit -m "feat(harness): create_document renders a JLBC memo

The Markdown helpers move from harness/documents.py into memo/markdown.py;
_render_docx becomes a thin delegate. materialize gains sender/recipient
as finished strings — this module still has no way to learn who the
analyst is, which is what its import allowlist exists to guarantee.

The allowlist gains exactly one entry, 'memo', and that is only safe
because memo carries its own allowlist test. The guarantee stays
structural and becomes transitive.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: The analyst's display name

**Files:**
- Modify: `app/identity.py`, `app/machine_config.py`, `app/routes/admin.py`
- Test: `tests/test_display_name.py`

**Interfaces:**
- Produces:
  - `app.machine_config.read_display_name(user: str) -> str`
  - `app.machine_config.set_display_name(user: str, name: str) -> None`
  - `app.identity.display_name(user: str | None = None) -> str`
  - `GET /api/me` gains `"display_name": str`
  - `PUT /api/me/display-name` accepting `{"display_name": str}`, returning `{"display_name": str}`

**⚠ DEVIATION FROM SPEC M5 — resolution order is reversed, deliberately.**

The spec lists Windows display name first, then the stored override. **Implement the override FIRST.** An override that loses to auto-detection cannot correct a wrong AD name — and a wrong name is the likelier failure than a missing one (`JARRETTD`, `Destin J`, a maiden name IT never updated). The spec's intent is "the analyst never has to type this if Windows knows it", which the override-first order still satisfies: the override is empty until somebody deliberately sets it. Record this deviation in `STATUS.md` when the branch merges.

Final order: **stored override → Windows display name → bare username.**

- [ ] **Step 1: Write the failing tests**

Create `tests/test_display_name.py`:

```python
"""Who the memo says it is from.

The name is cosmetic — it appears on a generated document and nowhere
else. Nothing here may raise: an unnameable analyst should lose
attribution on a memo, not the ability to generate one, which is the same
posture `app.identity.current_user` already takes.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import identity, machine_config
from app.main import create_app
from app.search_provider import StubSearchProvider


@pytest.fixture(autouse=True)
def machine_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    return tmp_path


def test_no_override_and_no_windows_name_falls_back_to_the_username(monkeypatch):
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "")
    assert identity.display_name("djarrett") == "djarrett"


def test_the_windows_display_name_is_used_when_there_is_no_override(monkeypatch):
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "Destin Jarrett")
    assert identity.display_name("djarrett") == "Destin Jarrett"


def test_a_stored_override_beats_the_windows_name(monkeypatch):
    """DEVIATION from spec M5, deliberate: the spec put Windows first. An
    override that loses to auto-detection cannot correct a WRONG AD name,
    and a wrong name is likelier than a missing one. The spec's intent —
    nobody types this if Windows knows it — still holds, because the
    override is empty until somebody sets it."""
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "JARRETTD")
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    assert identity.display_name("djarrett") == "Destin Jarrett"


def test_the_override_is_keyed_by_user():
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    machine_config.set_display_name("gpaulsen", "Geoff Paulsen")
    assert machine_config.read_display_name("djarrett") == "Destin Jarrett"
    assert machine_config.read_display_name("gpaulsen") == "Geoff Paulsen"
    assert machine_config.read_display_name("nobody") == ""


def test_clearing_the_override_removes_the_key_rather_than_storing_blank():
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    machine_config.set_display_name("djarrett", "   ")
    assert machine_config.read_display_name("djarrett") == ""


def test_setting_a_name_preserves_every_other_machine_json_key(tmp_path):
    """`_update` is read-modify-write for a reason: set_data_dir once
    wrote its key wholesale and silently switched off the one machine
    configured to process uploads."""
    machine_config.set_ingest_enabled(True)
    machine_config.set_display_name("djarrett", "Destin Jarrett")
    assert machine_config.ingest_enabled() is True


def test_a_corrupt_display_names_value_reads_as_absent(tmp_path):
    """Same degradation posture as every other read here — a broken file
    costs a name, not the app."""
    machine_config.machine_config_path().parent.mkdir(parents=True, exist_ok=True)
    machine_config.machine_config_path().write_text(
        '{"display_names": "not a dict"}', encoding="utf-8"
    )
    assert machine_config.read_display_name("djarrett") == ""


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "djarrett")
    app = create_app(search_provider=StubSearchProvider(), ingest_worker=None)
    with TestClient(app) as c:
        yield c


def test_api_me_reports_the_display_name(client, monkeypatch):
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "")
    body = client.get("/api/me").json()
    assert body["display_name"] == "djarrett"


def test_the_display_name_can_be_set_and_read_back(client):
    response = client.put("/api/me/display-name", json={"display_name": "Destin Jarrett"})
    assert response.status_code == 200
    assert response.json()["display_name"] == "Destin Jarrett"
    assert client.get("/api/me").json()["display_name"] == "Destin Jarrett"


def test_an_over_long_name_is_rejected_rather_than_written(client):
    response = client.put("/api/me/display-name", json={"display_name": "x" * 200})
    assert response.status_code == 422
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_display_name.py -q
```

Expected: FAIL — `AttributeError: module 'app.machine_config' has no attribute 'set_display_name'`.

- [ ] **Step 3: Add the machine.json accessors**

In `app/machine_config.py`, after `set_ingest_enabled`:

```python
# The analyst's name as it should appear on a generated memo. Keyed by
# username, so a machine with two Windows accounts keeps two names.
#
# HERE RATHER THAN THE SHARED settings.json ON PURPOSE (spec M6).
# `save_settings` is a read-modify-write on a file ~20 machines share, and
# it holds the OpenRouter API key, the tier->model map, the admin username
# and every spend limit. Routing a routine per-analyst write through it
# would add a corruption path to all of that in exchange for a name
# following an analyst between PCs — and the app is installed per machine
# (S7) and launched by the person sitting at it (S8), so it rarely moves.
_DISPLAY_NAMES_KEY = "display_names"

# Long enough for a real name with a suffix, short enough that the memo's
# FROM row cannot wrap.
MAX_DISPLAY_NAME = 120


def read_display_name(user: str) -> str:
    """This machine's stored name for `user`, or "" if there isn't one."""
    names = _read_all(quiet=True).get(_DISPLAY_NAMES_KEY)
    if not isinstance(names, dict):
        return ""
    value = names.get(user)
    return value.strip() if isinstance(value, str) else ""


def set_display_name(user: str, name: str) -> None:
    """Record (or, with a blank name, forget) this machine's name for `user`."""
    names = _read_all(quiet=True).get(_DISPLAY_NAMES_KEY)
    if not isinstance(names, dict):
        names = {}
    cleaned = name.strip()[:MAX_DISPLAY_NAME]
    if cleaned:
        names[user] = cleaned
    else:
        # Removed rather than stored blank, so "never set" and "cleared"
        # are the same state and neither shadows the Windows name.
        names.pop(user, None)
    _update({_DISPLAY_NAMES_KEY: names})
```

- [ ] **Step 4: Add the resolver to `app/identity.py`**

Add `import sys` if absent, `from app import machine_config`, then:

```python
def _windows_display_name() -> str:
    """The AD full name (`Geoff Paulsen`), or "" anywhere it isn't available.

    `GetUserNameEx(NameDisplay)` is the documented way to get a person's
    name rather than their logon name. Wrapped in a blanket except because
    every failure here — not Windows, no `secur32`, a machine not joined to
    a domain, an empty AD field — has the same correct answer: fall through
    to the next source. A name on a memo is not worth an exception.
    """
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        name_display = 3  # EXTENDED_NAME_FORMAT.NameDisplay
        secur32 = ctypes.WinDLL("secur32")
        size = wintypes.ULONG(0)
        secur32.GetUserNameExW(name_display, None, ctypes.byref(size))
        if not size.value:
            return ""
        buffer = ctypes.create_unicode_buffer(size.value)
        if not secur32.GetUserNameExW(name_display, buffer, ctypes.byref(size)):
            return ""
        return buffer.value.strip()
    except Exception:  # noqa: BLE001 — see the docstring
        return ""


def display_name(user: str | None = None) -> str:
    """The name to print on a document this analyst generates.

    Order: stored override > Windows display name > the bare username.

    DEVIATION FROM SPEC M5, which listed Windows first. An override that
    loses to auto-detection cannot correct a WRONG AD name, and a wrong
    name (`JARRETTD`, an un-updated maiden name) is likelier than a
    missing one. The spec's intent — nobody has to type this if Windows
    already knows it — is unaffected, because the override is empty until
    somebody deliberately sets it.

    Never raises: the fallback chain bottoms out at `current_user()`,
    which itself bottoms out at "".
    """
    resolved = current_user() if user is None else user
    override = machine_config.read_display_name(resolved)
    if override:
        return override
    windows = _windows_display_name()
    if windows:
        return windows
    return resolved
```

- [ ] **Step 5: Expose it over HTTP in `app/routes/admin.py`**

Add `display_name` to the `me()` return dict:

```python
        "display_name": display_name(user),
```

(importing it from `app.identity` alongside `current_user`), then add the setter route beside `me()`:

```python
class DisplayNameBody(BaseModel):
    display_name: str = Field(default="", max_length=machine_config.MAX_DISPLAY_NAME)


@router.put("/api/me/display-name")
def set_my_display_name(body: DisplayNameBody) -> dict:
    """The analyst's own name, as it appears on documents they generate.

    DELIBERATELY UNGATED, like `GET /api/me`. There is no authentication
    anywhere in this app (S11), so a gate here would be theater; and the
    only thing behind it is the name printed on that person's own memos,
    stored on their own machine.
    """
    user = current_user()
    machine_config.set_display_name(user, body.display_name)
    return {"display_name": display_name(user)}
```

Add `from pydantic import Field` to the existing pydantic import if it is not already there.

- [ ] **Step 6: Run tests**

```bash
.venv/bin/python -m pytest tests/test_display_name.py -q
```

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/identity.py app/machine_config.py app/routes/admin.py tests/test_display_name.py
git commit -m "feat(app): resolve the analyst's display name for generated memos

Order is stored override > Windows display name > bare username. That
REVERSES spec M5, deliberately: an override that loses to auto-detection
cannot correct a wrong AD name, and a wrong name is likelier than a
missing one. The spec's intent (nobody types this if Windows knows it)
is unaffected — the override is empty until somebody sets it.

The override lives in machine.json, not the shared settings.json, which
~20 machines read-modify-write and which holds the API key and every
spend limit.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: The Settings field

**Files:**
- Modify: `webapp/src/api.ts`, `webapp/src/pages/Settings.tsx`
- Test: `webapp/src/pages/Settings.test.tsx`

**Interfaces:**
- Consumes: `GET /api/me` → `display_name`; `PUT /api/me/display-name`.
- Produces: `api.setDisplayName(name: string): Promise<{ display_name: string }>`

- [ ] **Step 1: Write the failing test**

Append to `webapp/src/pages/Settings.test.tsx` (match the file's existing mocking style — read its top before writing):

```tsx
it("shows the name that will appear on generated documents", async () => {
  renderSettings({ me: { display_name: "Destin Jarrett" } });
  expect(await screen.findByDisplayValue("Destin Jarrett")).toBeInTheDocument();
});

it("saves an edited name and reports it saved", async () => {
  const setDisplayName = vi
    .spyOn(api, "setDisplayName")
    .mockResolvedValue({ display_name: "Destin J. Jarrett" });
  renderSettings({ me: { display_name: "Destin Jarrett" } });

  const field = await screen.findByLabelText(/name on documents/i);
  await userEvent.clear(field);
  await userEvent.type(field, "Destin J. Jarrett");
  await userEvent.click(screen.getByRole("button", { name: /save/i }));

  expect(setDisplayName).toHaveBeenCalledWith("Destin J. Jarrett");
  expect(await screen.findByText(/saved/i)).toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd webapp && npx vitest run src/pages/Settings.test.tsx
```

Expected: FAIL — `Unable to find a label with the text of: /name on documents/i`.

- [ ] **Step 3: Extend `webapp/src/api.ts`**

Add to the `Me` interface:

```ts
  /** The name printed on documents this analyst generates. */
  display_name: string;
```

and the setter:

```ts
export async function setDisplayName(
  name: string,
): Promise<{ display_name: string }> {
  return request("/api/me/display-name", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ display_name: name }),
  });
}
```

(match the existing `request` helper's name and signature in that file — read it first.)

- [ ] **Step 4: Add the field to `webapp/src/pages/Settings.tsx`**

A card with a labelled input, a Save button, and a saved/failed line. The copy must say what it is for:

```tsx
{/* The name goes on the FROM line of any memo AI Mode generates, as
    "<name>, via JLBC Agentic Search". Auto-filled from Windows where it
    is available; this field exists for the machines where it isn't, and
    to correct it where Windows has it wrong. */}
<label htmlFor="display-name">Your name on documents</label>
<input
  id="display-name"
  value={name}
  maxLength={120}
  onChange={(e) => setName(e.target.value)}
/>
<button onClick={save}>Save</button>
```

Follow the page's existing card markup and class names — do not invent new styling.

- [ ] **Step 5: Run tests**

```bash
cd webapp && npx vitest run src/pages/Settings.test.tsx && npx tsc -b
```

Expected: PASS, `tsc -b` exit 0.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/api.ts webapp/src/pages/Settings.tsx webapp/src/pages/Settings.test.tsx
git commit -m "feat(webapp): analyst can set the name that appears on generated memos

On the analyst-facing Settings page, not an admin surface — it is that
person's own name and it is stored on their own machine. Auto-filled from
Windows where available; this exists for machines where it is not, and to
correct it where Windows has it wrong.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: The `to` parameter, and threading the name through

**Files:**
- Modify: `harness/tools.py`, `harness/session.py`, `app/routes/conversations.py`, `harness/system-prompt.md`
- Test: `tests/test_harness_tools.py`

**Interfaces:**
- Consumes: `app.identity.display_name`, `harness.documents.materialize(..., sender=, recipient=)`.
- Produces: `ToolExecutor(..., display_name: str = "")`; `HarnessSession(..., display_name: str = "")`; `create_document` accepts optional `to`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_harness_tools.py`:

```python
def test_create_document_passes_the_recipient_and_the_analysts_name(monkeypatch):
    captured: dict = {}

    def fake_materialize(title, body, fmt, *, user="", sender="", recipient=""):
        captured.update(
            title=title, fmt=fmt, user=user, sender=sender, recipient=recipient
        )
        return "tok", Path("/tmp/Memo.docx")

    executor = ToolExecutor(
        corpus="budget",
        user="djarrett",
        display_name="Destin Jarrett",
        materialize=fake_materialize,
    )
    result = executor.execute(
        "create_document",
        {"title": "T", "body_markdown": "B", "to": "Director Smith"},
    )
    assert result["ok"] is True
    assert captured["sender"] == "Destin Jarrett"
    assert captured["recipient"] == "Director Smith"


def test_an_omitted_to_reaches_the_renderer_as_empty(monkeypatch):
    """The renderer owns the `[Recipient(s)]` placeholder, not this layer —
    one source for that string."""
    captured: dict = {}

    def fake_materialize(title, body, fmt, *, user="", sender="", recipient=""):
        captured["recipient"] = recipient
        return "tok", Path("/tmp/Memo.docx")

    executor = ToolExecutor(
        corpus="budget", user="djarrett", materialize=fake_materialize
    )
    executor.execute("create_document", {"title": "T", "body_markdown": "B"})
    assert captured["recipient"] == ""


def test_the_create_document_schema_offers_to_and_does_not_require_it():
    schema = next(
        s for s in TOOL_SCHEMAS if s["function"]["name"] == "create_document"
    )
    params = schema["function"]["parameters"]
    assert "to" in params["properties"]
    assert "to" not in params["required"]
```

(Adjust the import of `TOOL_SCHEMAS` / `ToolExecutor` / `Path` to match the file's existing imports.)

- [ ] **Step 2: Run tests to verify they fail**

```bash
.venv/bin/python -m pytest tests/test_harness_tools.py -q -k "recipient or create_document_schema"
```

Expected: FAIL — `TypeError: ToolExecutor.__init__() got an unexpected keyword argument 'display_name'`.

- [ ] **Step 3: Add `_opt_str` to `harness/tools.py`**

Beside `_req_str` (around line 680):

```python
def _opt_str(args: Mapping[str, Any], key: str) -> str:
    """An optional string argument, or "" when absent, blank or the wrong
    type. Absent and empty are the same thing to every caller here, so
    they are not distinguished."""
    value = args.get(key)
    return value.strip() if isinstance(value, str) else ""
```

- [ ] **Step 4: Extend the schema**

In `_CREATE_DOCUMENT_SCHEMA`, add to `properties` after `title`:

```python
                "to": {
                    "type": "string",
                    "description": (
                        "Who the memo is addressed to — ONLY when the analyst "
                        "named an audience ('write this up for the Director'). "
                        "Omit it otherwise; the document prints a placeholder "
                        "for them to fill in. Never guess a name."
                    ),
                },
```

and extend the tool `description`, replacing `You name the document by TITLE only;` with:

```
"The TITLE becomes the memo's SUBJECT line, so write it like a "
"subject. You name the document by TITLE only; "
```

- [ ] **Step 5: Thread `display_name` through the executor**

In `ToolExecutor.__init__`, add the parameter beside `user`:

```python
        display_name: str = "",
```

and store it:

```python
        # Resolved by the HTTP route, not here: `harness/tools.py`'s import
        # allowlist forbids `app.*`, and resolving a name means reading
        # per-machine config. Injecting a finished string is what keeps
        # that guard structural (spec M7).
        self.display_name = display_name
```

Then in `_create_document`:

```python
        token, path = materialize(
            title,
            body_markdown,
            fmt,
            user=self.user,
            sender=self.display_name,
            recipient=_opt_str(args, "to"),
        )
```

- [ ] **Step 6: Thread it through `harness/session.py`**

Add `display_name: str = ""` to `HarnessSession.__init__` (beside `user: str = ""` at line ~432), store `self.display_name = display_name` (beside line ~450), and pass it at the `ToolExecutor(` construction (~line 1344):

```python
                self.conversation_id,
                self.corpus,
                self.tier,
                user=self.user,
                display_name=self.display_name,
```

(match the actual call's existing argument style.)

- [ ] **Step 7: Pass it from the route**

In `app/routes/conversations.py`, import `display_name` from `app.identity` and add it wherever `user=current_user()` is passed to `HarnessSession`:

```python
            user=current_user(),
            display_name=display_name(),
```

- [ ] **Step 8: Update `harness/system-prompt.md`**

In the `### create_document(title, body_markdown, format?)` section (~line 685), change the signature line to include `to?`, and replace:

```
You choose the TITLE. You do not choose where the file is saved, and
there is no parameter for it.
```

with:

```
The document is rendered as a JLBC memo: letterhead, then a
DATE / TO / FROM / SUBJECT block, then your body. **Your TITLE becomes
the SUBJECT line**, so write it like a subject — "FY 2027 AHCCCS
Appropriations Summary", not "Report".

`to` is optional and you should usually leave it out. Supply it ONLY when
the analyst named an audience ("write this up for the Director"); the
document prints a placeholder for them to fill in otherwise. Never guess
a recipient.

DATE and FROM are filled in for you. You do not choose them, you do not
choose where the file is saved, and there is no parameter for any of it.
```

- [ ] **Step 9: Run the harness suites**

```bash
.venv/bin/python -m pytest tests/test_harness_tools.py tests/test_create_document.py tests/test_jlbc_memo.py -q
```

Expected: PASS — including `test_tools_module_imports_are_allowlisted`, which must still pass **unchanged**. If it fails, `app.*` was imported into `harness/tools.py`; revert that and inject instead.

- [ ] **Step 10: Commit**

```bash
git add harness/ app/routes/conversations.py tests/test_harness_tools.py
git commit -m "feat(harness): optional 'to' on create_document, analyst name threaded from the route

The name is resolved at the HTTP boundary and injected as a finished
string. harness/tools.py's import allowlist forbids app.*, and resolving
a display name means reading per-machine config — injecting keeps that
guard structural instead of turning it into a promise.

The prompt now tells the model its title becomes the SUBJECT line, and to
supply 'to' only when the analyst named an audience.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: Full gate, and look at the document

**Files:** none modified unless a gate fails.

- [ ] **Step 1: Full Python suite**

```bash
cd ~/ask-the-budget-az-worktrees/jlbc-memo-formatting
.venv/bin/python -m pytest -q 2>&1 | tail -20
```

Expected: all pass; skip count unchanged from master's documented 5 ONNX/model-closure skips.

- [ ] **Step 2: Full webapp suite and build**

```bash
cd webapp && npx vitest run 2>&1 | tail -10 && npx tsc -b && npm run build 2>&1 | tail -5
```

Expected: all pass, `tsc -b` exit 0, build clean.

- [ ] **Step 3: Render a real document and open it**

```bash
cd ~/ask-the-budget-az-worktrees/jlbc-memo-formatting
.venv/bin/python - <<'PY'
import memo
doc = memo.render(
    "## Highlights\n\n"
    "- The budget includes $14,200,000 from the General Fund in FY 2027.\n"
    "- Provider rate increases account for $8,100,000 of that amount.\n\n"
    "### BUDS Table\n\n"
    "Export the new table and paste it into the narrative.\n\n"
    "| Fund | FY 2026 | FY 2027 |\n|---|---|---|\n"
    "| General Fund | $12,400,000 | $14,200,000 |\n\n"
    "Please see the attached list prior to submitting.\n",
    subject="FY 2027 AHCCCS Appropriations Summary",
    sender="Destin Jarrett",
    recipient="",
)
doc.save("/tmp/memo-sample.docx")
print("wrote /tmp/memo-sample.docx")
PY
```

- [ ] **Step 4: THE CHECK THAT MATTERS — read it beside the reference**

Open `/tmp/memo-sample.docx` and `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` side by side. **Every check in this plan up to here is structural; a document can satisfy all of them and still look wrong.** Confirm, specifically:

- exactly ONE horizontal rule under the letterhead — not two, and not a blue one (the stripped `Title` border)
- the address lines' right-hand column aligns with the reference's
- `DATE` / `TO` / `FROM` / `SUBJECT` labels do not wrap, and their values start at the same left edge as the reference's
- the FROM line reads `Destin Jarrett, via JLBC Agentic Search`
- TO reads `[Recipient(s)]`
- section headings are visually distinct from body text but not oversized
- bullets sit at the same indent as the reference's
- the footer note appears on page 1
- add enough body text to reach page 2 and confirm `- 2 -` appears at the top of it and nothing appears at the top of page 1

- [ ] **Step 5: Update STATUS.md**

Add a section recording: what shipped, the spec/plan paths, the two planning traps (the `Title` style's blue border, and `tblLayout` being required for column widths), the **M5 resolution-order deviation and why**, and that no eval was run with the reason.

- [ ] **Step 6: Commit and finish the branch**

```bash
git add STATUS.md
git commit -m "docs: record JLBC memo formatting in STATUS.md"
```

Then use the `superpowers:finishing-a-development-branch` skill.

---

## Self-review

**Spec coverage:** M1 → Tasks 1–4 (package + allowlist test). M2 → Task 1. M3 → Task 1. M4 → Task 2. M5 → Task 5 (with a recorded deviation). M6 → Task 5. M7 → Tasks 4 + 7. M8 → Task 3. M9 → Task 1. M10 → Task 1. M11 → Task 7. M12 → Task 4. Eval rule → Global Constraints + Task 8 Step 5.

**Known deviation from the spec:** the display-name resolution order in Task 5, documented at the task, in the test, in the code comment and in the commit message.

**Type consistency:** `render(body_markdown, *, subject, sender, recipient, date)` is used identically in Tasks 1, 2, 3, 4 and 8. `materialize(..., *, user, sender, recipient)` matches between Task 4's implementation and Task 7's fake. `display_name(user=None)` matches its call sites in Tasks 5 and 7. `read_display_name(user)` / `set_display_name(user, name)` match between Task 5's implementation and its tests.
