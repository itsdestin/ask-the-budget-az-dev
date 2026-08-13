# Document Guide Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A sixth tool, `document_guide(report_type)`, that hands the model JLBC's report-type and formatting guidance only when it is about to write a document.

**Architecture:** Guidance lives in Markdown files under `harness/guides/`, loaded by a small `harness/guides.py`. `harness/tools.py` gains one schema and one handler. Nothing is enforced; the guide advises and the model writes.

**Tech Stack:** Python 3.12, pytest.

**Spec:** `docs/superpowers/specs/2026-08-13-document-guide-design.md` (G1–G11).

## Global Constraints

- **Worktree:** `~/ask-the-budget-az-worktrees/jlbc-memo-formatting`, branch `jlbc-memo-formatting`. `.venv` is symlinked. Run Python as `.venv/bin/python`.
- **`harness/tools.py`'s import allowlist MUST NOT CHANGE.** `tests/test_harness_tools.py` pins it to `{__future__, json, sys, threading, typing, uuid, retrieval, store, harness, chunking}`. `harness` is already there, which is exactly why the guides live in `harness/guides/` and not `memo/guides/` (spec G8). If you find yourself adding `pathlib` or `memo`, stop — the design has been inverted.
- **Baseline suite: 2592 passed, 5 skipped.** Nothing may regress.
- **No enforcement anywhere.** No validation of the model's output, no server-side rewriting of its numbers (spec G6).
- **No eval run.** The prompt edit is confined to the `create_document` section, which `eval/run_eval.py` cannot measure — it calls `retrieve()` directly. Same call as S22/S23 and the memo spec.
- **Annotate non-trivial code with a WHY comment** recording the evidence, per CLAUDE.md.

## Two facts that are easy to get wrong

1. **The citation floor is 4 untagged and 2 tagged** (`citation/annotate.py:128`, `citation/matching.py:87`). The guide's rounding advice is scoped to the **document body** because documents carry no citation chips. The chat answer keeps source precision. A bare "round your numbers" would be applied to answers too and would degrade untagged citation coverage with no error anywhere.
2. **`memo/markdown.py` does not render numbered lists.** A `1)` line becomes an unstyled plain paragraph, pinned by `tests/test_jlbc_memo.py`. Every guide must say bullets.

---

## File Structure

**Create:**

| File | Responsibility |
|---|---|
| `harness/guides/shared.md` | Style block returned with every report type |
| `harness/guides/research-memo.md` | The default type |
| `harness/guides/comparison.md` | Two or more years / agencies / funds |
| `harness/guides/agency-profile.md` | One agency's budget |
| `harness/guides.py` | Loads and assembles guide text |
| `tests/test_document_guide.py` | Loader + tool + content guards |

**Modify:** `harness/tools.py` (schema, handler, registry, `create_document` description), `harness/system-prompt.md` (the pointer).

---

## Task 1: The guide content and loader

**Files:**
- Create: `harness/guides/shared.md`, `harness/guides/research-memo.md`, `harness/guides/comparison.md`, `harness/guides/agency-profile.md`, `harness/guides.py`
- Test: `tests/test_document_guide.py`

**Interfaces:**
- Produces:
  - `harness.guides.REPORT_TYPES: tuple[str, ...]` — `("research-memo", "comparison", "agency-profile")`
  - `harness.guides.DEFAULT_TYPE: str` — `"research-memo"`
  - `harness.guides.guide_for(report_type: str) -> str` — shared block + the type's block; falls back to the default for an unknown or empty type; never raises

- [ ] **Step 1: Write the failing test**

Create `tests/test_document_guide.py`:

```python
"""The guidance the model gets when it writes a document.

These are CONTENT guards as much as code guards. Two rules in the guide
text would be silently costly to lose, so each has a test naming the
consequence — see the two tests at the bottom of this file.
"""
from __future__ import annotations

import pytest

from harness import guides


def test_every_report_type_has_a_guide():
    for report_type in guides.REPORT_TYPES:
        text = guides.guide_for(report_type)
        assert text.strip(), f"{report_type} guide is empty"


def test_the_shared_style_block_is_included_in_every_type():
    for report_type in guides.REPORT_TYPES:
        assert "Forbidden phrases" in guides.guide_for(report_type)


@pytest.mark.parametrize("bad", ["", "  ", "fiscal-note", "MEMO", None])
def test_an_unknown_type_falls_back_rather_than_failing(bad):
    """A model that guesses a type name should get useful guidance, not a
    failed call it has to spend a round-trip recovering from."""
    assert guides.guide_for(bad) == guides.guide_for(guides.DEFAULT_TYPE)


def test_there_is_no_fiscal_note_type(): 
    """Spec G2. A fiscal note is a legally-shaped product with an official
    template and a source sign-off gate; Destin's own skill does that job.
    A lookalike built from corpus retrieval could be mistaken for one."""
    assert "fiscal-note" not in guides.REPORT_TYPES


def test_the_answer_versus_document_number_split_is_stated(): 
    """🔴 THE GUARD THAT MATTERS MOST (spec G5).

    Rounding belongs to the DOCUMENT body only. Documents carry no
    citation chips; chat answers do, and `citation/matching.py` refuses an
    untagged figure below 4 written significant digits outright. If this
    split is ever dropped from the guide, the model rounds in answers too
    and untagged citation coverage falls with NO error anywhere — no test
    fails, no log line, nothing visible until someone re-measures.
    """
    text = guides.guide_for("research-memo").lower()
    assert "in the answer" in text and "in the document" in text
    assert "as the source writes" in text


def test_no_guide_recommends_numbered_lists():
    """`memo/markdown.py` renders `1)` as an unstyled plain paragraph —
    pinned by tests/test_jlbc_memo.py. The fiscal-note skill mandates
    numbered items, so borrowing its list convention would produce
    visibly broken documents."""
    for report_type in guides.REPORT_TYPES:
        text = guides.guide_for(report_type)
        assert "numbered list" not in text.lower()
        assert "1)" not in text


def test_the_number_rules_match_the_conventions_reference():
    """Pinned against docs/reference/jlbc-document-conventions.md so the
    guide and the reference cannot drift apart."""
    from pathlib import Path

    reference = (
        Path(__file__).resolve().parents[1]
        / "docs" / "reference" / "jlbc-document-conventions.md"
    ).read_text(encoding="utf-8")
    shared = guides.guide_for(guides.DEFAULT_TYPE)
    for rule in ("$6.0 million", "$400,000", "FY 2026", "one-time"):
        assert rule in reference, f"{rule} missing from the reference"
        assert rule in shared, f"{rule} missing from the guide"
```

- [ ] **Step 2: Run it to verify it fails**

```bash
cd ~/ask-the-budget-az-worktrees/jlbc-memo-formatting
.venv/bin/python -m pytest tests/test_document_guide.py -q
```

Expected: collection error — `ImportError: cannot import name 'guides' from 'harness'`.

- [ ] **Step 3: Write `harness/guides/shared.md`**

```markdown
## House style — applies to every document

### Numbers

Follow JLBC's fiscal-note conventions:

- Millions: one decimal, keep the trailing zero — `$18.4 million`, `$6.0 million`
- Thousands: no decimal — `$400,000`, `$149,200`
- Round to the nearest hundred for small and medium figures
- Negatives always in parentheses — `($1.5 million)`
- Percentages always numerals — `2.5%`
- Fiscal years written `FY 2026` — never `FY26` or `FY'26`
- Spell out numbers under 10; numerals for 10 and above
- Spell out `General Fund`; `GF` only inside a table, after first use
- Spell out an agency on first use, then abbreviate
- Label every component `one-time` or `ongoing`
- Write `beginning in FY 2027`, `annually`, `per year` — never `on an annual basis`
- Ranges as `Between $X and $Y`, low end first

### 🔴 Rounding applies IN THE DOCUMENT, not in your answer

**In the answer you write in chat: give figures exactly as the source
writes them** — `$6,043,200`, not `$6.0 million`. The interface links each
figure back to the passage it came from, and it can only do that when the
figure is written precisely enough to be found.

**In the document body: round to the conventions above.** Nothing in the
file is being linked, and a memo the analyst will send should read like
JLBC's own writing.

Because a rounded figure cannot be found by searching the source PDF, the
document has to carry its provenance in the prose instead — see "Name your
sources" below.

### Voice

- Active, first person plural — "We estimate...", "We found..."
- Never "I". Never passive constructions.
- Use "We believe..." to mark JLBC's own judgement apart from an agency's claim
- Hedge honestly where the data is thin
- Descriptive and explanatory words only. No advocacy adverbs or adjectives.

### Forbidden phrases

Never write: "It is estimated that", "note that", "please note", "it should
be noted", "on an annual basis", "recurring".

### Rules for every document

- **Lead with the bottom line.** The reader should know the key finding
  after the first sentence.
- **Name your sources.** For every figure that is not self-evident, say
  where it came from in the sentence — "According to the FY 2027 Baseline,
  ...". The document carries no clickable citations, so the prose is the
  only provenance it has.
- **Show the arithmetic** when a figure is derived: input, factor, output.
  This is what lets a reader re-derive a rounded number.
- **No URLs** in the document.
- **Do not repeat the bottom line** in the findings, and do not include
  background that carries no finding.
- **When the answer is indeterminate**, say which direction the impact runs
  and *why* the size cannot be given. Never a bare "cannot be determined".
- **End with a short "What to verify" list** — the two or three things the
  analyst should check before sending it.

### Length

**Two pages maximum. One page where the material allows.** Be concise while
conveying all relevant information — cut padding, never cut a finding.

### Formatting

- Use `##` for section headings, `-` for bullets, `**bold**` for emphasis.
- **Use bullets, never numbered lists.** Numbers do not render as a list.
- A table is for numbers that share a structure. Two figures in a sentence
  stay in the sentence.
```

- [ ] **Step 4: Write the three type files**

`harness/guides/research-memo.md`:

```markdown
# Research memo — the default

Use for a question with an answer: what something cost, what changed, what
a document says.

## Sections

- **Bottom line** — one short paragraph. The finding, with its figure and
  fiscal year.
- **Detail** — what the finding rests on. Prose, not bullets, wherever there
  is reasoning; bullets only for genuinely parallel items.
- **What this is based on** — the documents used, by name and fiscal year.
- **What to verify** — two or three items.

A table only if several figures share a structure.
```

`harness/guides/comparison.md`:

```markdown
# Comparison — two or more years, agencies, or funds

Use when the answer sets things side by side.

## Sections

- **Bottom line** — what moved, by how much, and over what period.
- **The table** — leads the document. Rows are the things compared.
- **What moved and why** — prose under the table. A table states; it does
  not explain, and the explanation is the part the analyst cannot get from
  the source alone.
- **What this is based on** — documents by name and fiscal year.
- **What to verify** — two or three items.

## The table

For fiscal-year and fund-source shapes, follow the table conventions
already given for reading budget documents: the published three-year
layout, and the fund ladder ending in the published total. **Never build a
total by adding rows yourself** — the totals are published; use them.

Do not add a percentage-share column. It requires dividing by a total, and
JLBC's own tables almost never carry one.

If a comparison would produce a table with one row, it is not a comparison
— write a research memo instead.
```

`harness/guides/agency-profile.md`:

```markdown
# Agency profile — one agency's budget

Use for a memo about a single agency: its funding, what changed, and the
issues attached to it.

## Sections

- **Bottom line** — total funding for the year in question, and the
  General Fund share.
- **Funding** — a table of the agency's funding, by fund source, using the
  published totals.
- **What changed** — the notable increases and decreases, each labelled
  `one-time` or `ongoing`.
- **Issues** — program or policy items worth the reader's attention.
- **What this is based on** — documents by name and fiscal year.
- **What to verify** — two or three items.

Omit any section the corpus does not support. An empty heading is worse
than a missing one.
```

- [ ] **Step 5: Write `harness/guides.py`**

```python
"""The report-type guidance handed to the model by `document_guide`.

Content lives in `harness/guides/*.md` rather than in Python, for the same
reason `harness/system-prompt.md` does: a non-technical successor can edit
house guidance in a Markdown file without touching code.

IN `harness/`, NOT `memo/`, AND THAT IS LOAD-BEARING. `harness/tools.py`
carries an AST import allowlist (`tests/test_harness_tools.py`) that
permits `harness` and does NOT permit `memo` or `pathlib`. Putting the
guides under `memo/` would force that allowlist open — and it is the
structural half of Invariant 7. It also keeps `memo/` to the single
responsibility its own spec gave it: a pure renderer.
"""
from __future__ import annotations

from pathlib import Path

_GUIDE_DIR = Path(__file__).with_name("guides")
_SHARED = "shared"

DEFAULT_TYPE = "research-memo"
REPORT_TYPES: tuple[str, ...] = ("research-memo", "comparison", "agency-profile")


def _read(name: str) -> str:
    """One guide file, or "" if it is missing or unreadable.

    Degrades rather than raising: a packaging slip that drops a file
    should cost the model some advice, never the turn it is in the middle
    of. `tests/test_document_guide.py` asserts every file is present, so a
    missing one fails the suite rather than passing silently.
    """
    try:
        return (_GUIDE_DIR / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def guide_for(report_type: str | None) -> str:
    """The shared style block plus the guidance for one report type.

    An unknown, empty or non-string type resolves to `DEFAULT_TYPE`. A
    model that guesses a name should get useful guidance rather than an
    error it must spend a round-trip recovering from — and there is
    nothing it could usefully do with the error anyway.
    """
    requested = report_type.strip() if isinstance(report_type, str) else ""
    resolved = requested if requested in REPORT_TYPES else DEFAULT_TYPE
    return f"{_read(resolved)}\n\n{_read(_SHARED)}".strip()
```

- [ ] **Step 6: Run the tests**

```bash
.venv/bin/python -m pytest tests/test_document_guide.py -q
```

Expected: PASS, 11 tests.

- [ ] **Step 7: Commit**

```bash
git add harness/guides harness/guides.py tests/test_document_guide.py
git commit -m "feat(harness): report-type guidance as loadable Markdown

Content in harness/guides/*.md so a non-technical successor can edit
house guidance without touching Python — the same reasoning that makes
harness/system-prompt.md a file.

In harness/ and not memo/ deliberately: harness/tools.py's import
allowlist permits harness and forbids memo and pathlib, and that
allowlist is the structural half of Invariant 7.

Two content guards carry their consequence in the docstring. The
answer-versus-document number split is the one whose loss would be
invisible — the model would round in chat answers too and untagged
citation coverage would fall with no error anywhere.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: The tool, and the pointer that makes it discoverable

**Files:**
- Modify: `harness/tools.py`, `harness/system-prompt.md`
- Test: `tests/test_document_guide.py`, `tests/test_harness_tools.py`

**Interfaces:**
- Consumes: `harness.guides.guide_for`, `REPORT_TYPES`, `DEFAULT_TYPE`
- Produces: a `document_guide` entry in `harness.tools.TOOLS`; `ToolExecutor.execute("document_guide", {...})` returning JSON `{"ok": true, "report_type": str, "guide": str}`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_document_guide.py`:

```python
import json

from harness.tools import TOOLS, ToolExecutor


def _executor():
    return ToolExecutor("conv-1", "budget", "standard")


def test_the_tool_is_registered_and_takes_an_optional_report_type():
    schema = next(t for t in TOOLS if t["function"]["name"] == "document_guide")
    params = schema["function"]["parameters"]
    assert params["properties"]["report_type"]["enum"] == list(guides.REPORT_TYPES)
    assert not params.get("required")


def test_calling_it_returns_the_guide_for_that_type():
    result = json.loads(_executor().execute("document_guide", {"report_type": "comparison"}))
    assert result["ok"] is True
    assert result["report_type"] == "comparison"
    assert "The table" in result["guide"]
    assert "Forbidden phrases" in result["guide"]


def test_calling_it_with_no_arguments_returns_the_default():
    result = json.loads(_executor().execute("document_guide", {}))
    assert result["ok"] is True
    assert result["report_type"] == guides.DEFAULT_TYPE


def test_an_unknown_type_reports_the_type_it_actually_used():
    """Reporting the REQUESTED type back would tell the model it got
    comparison guidance when it got the default."""
    result = json.loads(_executor().execute("document_guide", {"report_type": "fiscal-note"}))
    assert result["report_type"] == guides.DEFAULT_TYPE


def test_create_document_points_at_the_guide():
    """Spec G9. The pointer is the ONLY thing making the tool
    discoverable — nothing enforces the call, so if the description stops
    mentioning it the feature silently stops being used."""
    schema = next(t for t in TOOLS if t["function"]["name"] == "create_document")
    assert "document_guide" in schema["function"]["description"]
```

- [ ] **Step 2: Run to verify failure**

```bash
.venv/bin/python -m pytest tests/test_document_guide.py -q
```

Expected: FAIL — `StopIteration` on the `next(...)` for `document_guide`.

- [ ] **Step 3: Add the schema to `harness/tools.py`**

Beside `_CREATE_DOCUMENT_SCHEMA`:

```python
_DOCUMENT_GUIDE_SCHEMA = {
    "type": "function",
    "function": {
        "name": "document_guide",
        "description": (
            "House formatting and structure guidance for a document you "
            "are about to write. Call it BEFORE create_document, once, "
            "with the report type that fits: 'research-memo' (the "
            "default — a question with an answer), 'comparison' (two or "
            "more years, agencies or funds), 'agency-profile' (one "
            "agency's budget). Returns JLBC's conventions for sections, "
            "tables, numbers and voice. Free and instant — no search, no "
            "cost."
        ),
        "parameters": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "report_type": {
                    "type": "string",
                    "enum": list(REPORT_TYPES),
                    "description": (
                        "Which kind of document. Defaults to "
                        "'research-memo' when omitted."
                    ),
                },
            },
        },
    },
}
```

Add `from harness.guides import DEFAULT_TYPE, REPORT_TYPES, guide_for` to the imports — `harness` is already on the allowlist, so the guard is unaffected.

Register it in `TOOLS`, after `_CREATE_DOCUMENT_SCHEMA`:

```python
    _CREATE_DOCUMENT_SCHEMA,
    _DOCUMENT_GUIDE_SCHEMA,
)
```

- [ ] **Step 4: Add the handler**

In the dispatch table beside `"create_document": self._create_document`:

```python
            "document_guide": self._document_guide,
```

and the method, beside `_create_document`:

```python
    # -- document_guide -----------------------------------------------------

    def _document_guide(self, args: dict[str, Any]) -> dict[str, Any]:
        """House guidance for a document the model is about to write.

        Reads nothing, writes nothing, costs nothing. `report_type` echoes
        back the type ACTUALLY used, not the one requested — telling a
        model it got `comparison` guidance when it got the default would
        make a wrong document look like a correct one.
        """
        requested = _opt_str(args, "report_type")
        resolved = requested if requested in REPORT_TYPES else DEFAULT_TYPE
        return {"ok": True, "report_type": resolved, "guide": guide_for(resolved)}
```

- [ ] **Step 5: Point `create_document` at it**

In `_CREATE_DOCUMENT_SCHEMA`'s description, after `"...link the analyst can click."`, add:

```python
            "Call document_guide first for the house rules on sections, "
            "tables and numbers. "
```

- [ ] **Step 6: Update the system prompt**

In `harness/system-prompt.md`'s `### create_document(...)` section, after the paragraph beginning "The document is rendered as a JLBC memo", insert:

```markdown
**Call `document_guide` before you write it.** It returns JLBC's rules for
sections, tables, numbers and voice, for the report type you name —
`research-memo`, `comparison`, or `agency-profile`. It costs nothing and
takes no search. A document written without it comes out in generic style
and the analyst has to reformat it before sending.

One rule from it is worth stating here because it applies to your ANSWER
too: **in the answer, write figures exactly as the source writes them**
(`$6,043,200`). Rounding belongs in the document, not in what you say in
chat — the interface links each figure in your answer back to its passage,
and it can only do that when the figure is written precisely.
```

Also add `document_guide` to the tool list at line ~227 (`retrieve`, `cite`, `cite_batch`, `list_filter_values`, and `create_document`).

- [ ] **Step 7: Run the suites**

```bash
.venv/bin/python -m pytest tests/test_document_guide.py tests/test_harness_tools.py tests/test_harness_prompt_caching.py -q
```

Expected: PASS. `test_tools_module_imports_are_allowlisted` must pass **unchanged** — if it fails, `pathlib` or `memo` leaked into `harness/tools.py`.

- [ ] **Step 8: Commit**

```bash
git add harness tests
git commit -m "feat(harness): document_guide tool + the pointer that makes it discoverable

A sixth tool. Only its schema joins the cached prefix; the guidance
content is paid for only on turns that write a document.

report_type echoes back the type ACTUALLY used rather than the one
requested — telling a model it got comparison guidance when it got the
default would make a wrong document look correct.

The prompt repeats one rule from the guide inline, deliberately: figures
in the ANSWER keep source precision. Rounding belongs to the document
only, because chat answers carry citation chips and documents do not.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: Gates

- [ ] **Step 1: Full Python suite**

```bash
.venv/bin/python -m pytest -q 2>&1 | tail -3
```

Expected: at least 2592 passed, 5 skipped. The 5 skips are the documented ONNX/model-closure skips.

- [ ] **Step 2: Confirm the guide actually reads well**

```bash
.venv/bin/python -c "
from harness.guides import guide_for, REPORT_TYPES
for t in REPORT_TYPES:
    text = guide_for(t)
    print(f'=== {t}: {len(text.split())} words ===')
print(guide_for('comparison'))
"
```

Read the output as if you were the model. It should be short enough to act on — if any type exceeds ~700 words, cut it. This is guidance, not a manual.

- [ ] **Step 3: Update STATUS.md**

Record: what shipped; that the guidance is advisory and unenforced; the answer-versus-document number split and why it matters (untagged citation coverage); that no eval was run and why; and that **nobody has watched a real document produced under it**, because that needs a keyed machine.

- [ ] **Step 4: Commit and finish the branch**

```bash
git add STATUS.md && git commit -m "docs: record the document guide in STATUS.md"
```

Then use `superpowers:finishing-a-development-branch`.

---

## Self-review

**Spec coverage:** G1 → Task 2. G2 → Task 1 Steps 4-5 (+ the no-fiscal-note test). G3 → Task 1. G4 → `comparison.md` (one table style; points at the prompt for the published shapes; forbids a share column). G5 → `shared.md` + the guard test + the prompt paragraph. G6 → nothing to build; no rewriting exists. G7 → the drift test against the conventions reference. G8 → `harness/guides/` + the docstring. G9 → the pointer test. G10 → `shared.md`'s "Rules for every document". G11 → `shared.md`'s Length section.

**Placeholder scan:** none. Every guide file is written out in full.

**Type consistency:** `guide_for(report_type) -> str`, `REPORT_TYPES`, `DEFAULT_TYPE` are used identically in Tasks 1 and 2. `_opt_str` already exists in `harness/tools.py` (added for `create_document`'s `to`).
