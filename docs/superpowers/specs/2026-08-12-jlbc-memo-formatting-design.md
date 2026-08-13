# JLBC memo formatting for agent-generated reports — design

**Date:** 2026-08-12
**Status:** approved, not implemented
**Supersedes:** Plan 5 Task 21's placement decision (`scripts/jlbc_memo.py`), which
cannot work — see M1.

---

## The problem

AI Mode's `create_document` tool writes a `.docx` an analyst can download and
send. It renders that file with Word's stock styling — `Title`, `Heading 1..6`,
`List Bullet`, `Table Grid`, and no page setup at all. The result is a generic
Office document that shares nothing with the JLBC house style, so an analyst who
wants to send it has to reformat it by hand first.

JLBC's real format is committed at
`samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` — the FY 2027
Appropriations Report Round 1 instructions memo, vendored 2026-07-31 per
CLAUDE.md's primary-source rule specifically so a fixture for this work survives
a fresh clone.

**Goal: a document produced by `create_document` is visually a JLBC memo**,
carrying its letterhead, its memo block, its typography and its section-heading
conventions, with the tool's involvement disclosed rather than hidden.

## What the reference document actually is

Measured, not eyeballed. Note that two structural elements are invisible to
`python-docx`'s `Document.paragraphs` and were missed on a first pass: the
horizontal rule is a VML `pict`, and the DATE/TO/FROM/SUBJECT block is a
borderless table. Anyone re-deriving these values must walk `document.body`
elements, not the paragraph list.

Body order:

| # | Element | Measured spec |
|---|---|---|
| 0 | `Joint Legislative Budget Committee` | Word `Title` style — 14 pt, bold, centered |
| 1 | `Staff Memorandum` | 14 pt bold centered, **direct run formatting**, not a style |
| 2 | `1716 West Adams` TAB `Telephone: (602) 926-5491` | 10 pt, one left tab stop at **7020 twips** (4.875″) |
| 3 | `Phoenix, Arizona 85007` TAB `azjlbc.gov` | as above |
| 4 | horizontal rule | VML `pict` line, stroke weight **2.25 pt** |
| 5 | spacer | empty paragraph, 6 pt |
| 6 | memo block | borderless **7×2 table**, columns **1458 / 7740 twips**, 10.5 pt. Rows: `DATE:` · spacer · `TO:` · spacer · `FROM:` · spacer · `SUBJECT:`. Label cells use the `Header` paragraph style |
| 7+ | body | see below |

Page and body:

| Property | Value |
|---|---|
| Page | US Letter |
| Margins | top **0.7″**, bottom **0.5″**, left/right **1.0″** |
| Header distance | 0.75″ · footer 0.6″ |
| Body text | Calibri **10.5 pt** — the `Normal` style says 12 pt and **every body run overrides it** |
| Section headings | the built-in **`Header` paragraph style**, bold, 10.5 pt, flush left. JLBC reuses `Header` as a section heading; matching the house style means matching that |
| Bullets | `List Paragraph` style, left indent **0.1875″**, bullet glyph from `numbering.xml` |
| Run-in labels | bold label, then `: ` or ` – `, then normal text (`Policy Issues – …`, `BUDS Table: …`) |
| Vertical spacing | **empty paragraphs**, never space-after |
| Page 2+ header | TAB then `- «PAGE» -`; **first-page header is blank** (`different_first_page = True`) |
| Footer | empty in the reference |

There is **no title line** in the body. The document's subject lives in the memo
block's `SUBJECT:` row.

---

## Decisions

### M1 — the renderer is a new top-level `memo/` package

Plan 5 Task 21 specified `scripts/jlbc_memo.py` and its Step 5 asked for
`harness/documents.py::_render_docx` to call it. **That cannot work.**
`tests/test_create_document.py::test_documents_module_cannot_reach_the_shared_data_dir`
pins an AST import allowlist on `harness/documents.py` — `__future__`,
`dataclasses`, `os`, `pathlib`, `re`, `secrets`, `threading`, `time`, `typing`,
`unicodedata`, `docx`, and nothing else. That allowlist is the structural half of
Invariant 7: the module must have no code path by which it could learn where the
shared drive is. `scripts/` contains modules that import `store.config`
(`migrate_to_lancedb.py` among them), so adding `scripts` to the allowlist would
convert a structural guarantee into a promise.

Three placements were considered:

| Option | Verdict |
|---|---|
| Inline the styling into `_render_docx` | Works, needs no allowlist change, but leaves Plan 5's handbook renderer nothing to reuse and gives `documents.py` a second responsibility |
| `scripts/jlbc_memo.py` (Plan 5 as written) | **Rejected** — breaks the Invariant 7 allowlist as above |
| **New top-level `memo/` package** | **Chosen** |

`memo/` is a pure renderer that knows Markdown and Word and nothing else. It
carries **its own** AST allowlist test pinning it to stdlib + `docx`, and
`"memo"` is added to `documents.py`'s allowlist. The Invariant 7 guard therefore
stays structural and becomes transitive: `documents.py` may import `memo`,
`memo` may import nothing that could reach the share, and both facts are pinned
by tests rather than asserted in comments.

Plan 5's future `scripts/build_handbook.py` imports the same module, which was
Task 21's actual intent.

**Public interface:**

```
memo.render(
    body_markdown: str,
    *,
    subject: str,
    sender: str,
    recipient: str,
    date: str,
) -> docx.Document
```

Every parameter is a finished string. The renderer performs no identity
resolution, no date formatting policy, and no I/O.

### M2 — the masthead is carried verbatim, with the subtitle changed

Line 1 is `Joint Legislative Budget Committee`, unchanged. Line 2 reads
**`Research Memorandum`**, not `Staff Memorandum`.

The letterhead is carried in full — same fonts, same address block, same rule —
because the analyst's intent is to edit the document and send it as their own
work, and a document that needs its letterhead pasted in has not saved them the
formatting pass. The subtitle changes because a `Staff Memorandum` is a specific
JLBC work product with a specific authorship, and a machine-drafted document
should not claim to be one.

### M3 — the tool's involvement is disclosed in the page footer

Every page carries `Generated with JLBC Agentic Search`, 9 pt, centered, in the
footer — including the first page, which needs its own footer part because
`different_first_page` is set for the header.

The footer is the disclosure surface rather than a body line because a body line
sits in the analyst's prose and will be deleted; a footer travels with the
document, survives printing, and costs no vertical space in the memo body. The
reference document's footer is empty, so nothing is displaced.

### M4 — the memo block's four rows

| Row | Content |
|---|---|
| `DATE:` | today's date, long form (`June 15, 2026`) |
| `TO:` | model-supplied when the analyst named an audience, otherwise the literal **`[Recipient(s)]`** |
| `FROM:` | **`{Analyst Name}, via JLBC Agentic Search`** |
| `SUBJECT:` | the `title` the model already supplies to `create_document` |

**`SUBJECT:` is where the title goes, and there is no separate title line.** The
reference document has none, and Word's `Title` style is already spent on the
masthead. The existing `doc.add_heading("", level=0)` call in `_render_docx` is
removed.

`TO:` falls back to a visible placeholder rather than an empty cell so the
analyst can see there is a field to fill; an empty cell beside a label reads as
a rendering bug.

`FROM:` names the analyst because they are the person who will edit and send the
memo, with the tool's contribution stated inline. Neither a bare analyst name
(which hides the tool) nor a bare `JLBC Insight` (which the analyst would
overwrite on every document) is right.

### M5 — the analyst's name resolves from Windows first, a per-machine override second

Resolution order:

1. **Windows display name** — `GetUserNameEx(NameDisplay)` via `ctypes`/`secur32`,
   which returns the AD full name (`Geoff Paulsen`). Auto-fills for most
   analysts with nothing to configure.
2. **A stored override** — set by the analyst on the existing Settings page.
3. **The bare username** from `app.identity.current_user()`.

Nothing raises. A machine where step 1 fails degrades to step 3, which is the
behaviour the app already has everywhere else identity is uncertain.

### M6 — the override lives in per-machine `machine.json`, not the shared settings

Keyed by username, so a machine with two Windows accounts keeps two names.

**Not the shared `settings.json`.** `save_settings()` is a read-modify-write on
a file that ~20 machines share, and it holds the OpenRouter API key, the
tier→model map, the admin username and every spend limit. Routing a routine
per-analyst write through it adds a corruption path to all of that in exchange
for a name following an analyst between PCs — and the app is installed per
machine (S7) and launched by the person sitting at it (S8), so it would rarely
move anyway.

`machine.json` already holds `data_dir` and `ingest_enabled` and already has a
read-modify-write-safe setter and a CLI entry point (`app.machine_config`).

`GET /api/me` gains `display_name`. It is already ungated, and
`webapp/src/pages/Settings.tsx` is already the analyst-facing (non-admin)
surface, described in its own header comment as answering "the three questions a
person has about themselves" — a fourth, "what name goes on documents I
generate", belongs there.

### M7 — identity never enters `harness/documents.py`

`harness/tools.py` already knows the calling user and already passes it to
`materialize()`. It resolves the display name and the date and passes finished
strings. `documents.py` and `memo/` receive text and render it.

This is what keeps M5 and M6 from re-opening Invariant 7: the modules that write
files have no knowledge of identity sources, and the module that knows identity
writes no files.

### M8 — the Markdown mapping mirrors the reference's actual structure

The reference memo uses **one** heading level plus bold run-in labels. The
mapping reproduces that rather than inventing a hierarchy Word would render but
JLBC never uses:

| Markdown | Rendered as |
|---|---|
| `#`, `##` | `Header` paragraph style, flush left, **bold applied to the runs** |
| `###` and deeper | bold run-in label paragraph — which is what the memo's third level actually is |
| `-`, `*` | `List Bullet` style, left indent 0.1875″ |
| `**bold**` | bold runs (unchanged) |
| pipe tables | `Table Grid`, header row bolded (unchanged) |
| anything else | **a verbatim plain paragraph** (unchanged) |

**Bold on the runs, never on the `Header` style itself.** The memo block's
label cells (`DATE:`, `TO:`, `FROM:`, `SUBJECT:`) also use the `Header`
paragraph style, and in the reference they are **not** bold — only the section
headings are, via direct run formatting. Setting `bold` on the style would
bold the memo block's labels as a side effect. This is the same shape as M9
in reverse, and the reason the two decisions differ: size is uniform across
everything that uses these styles, so it belongs on the style; bold is not, so
it belongs on the run.

`List Bullet` rather than the reference's `List Paragraph` because
`List Bullet` carries the bullet glyph through `numbering.xml` in python-docx's
default template, where `List Paragraph` does not; the reference's bullets come
from a numbering definition its own file carries. Same rendered result, without
hand-authoring a numbering part.

**The "no silent drops" rule is unchanged and is load-bearing.** An analyst who
receives a memo with a section quietly missing has no way to know it happened.
A blockquote rendering as ordinary text is a far better failure.

### M9 — body typography is set on `Normal`, not on every run

The reference sets 10.5 pt on each body run over a 12 pt `Normal` style. The
renderer instead restyles `Normal` to Calibri 10.5 pt.

The rendered result is identical, and it means table cells, bullets and any
paragraph a future edit adds inherit correctly instead of depending on someone
remembering to size each run.

### M10 — the horizontal rule is a paragraph border

The reference's rule is a VML `pict` line at 2.25 pt. The renderer emits a
paragraph bottom border at 2.25 pt instead: visually identical, expressible in
plain WordprocessingML, and it does not require embedding a drawing part.

### M11 — one new optional `to` parameter on `create_document`

The model fills it when the analyst's request names an audience ("write this up
for the Director") and omits it otherwise. `harness/system-prompt.md` gains two
points: when to fill `to`, and that `title` becomes the SUBJECT line rather than
a heading — so it should read like a subject.

No other parameter is added. `date`, `from` and the letterhead are not model
surface: they are facts the app knows, and a model that can write a name onto a
memo is a model that can write the wrong one.

### M12 — the `md` format path does not change

`create_document(format="md")` stays byte-faithful to what the model wrote. It
is the escape hatch for an analyst who wants the text without the formatting,
and round-tripping it through a renderer could lose a construct.

---

## Testing

**`tests/test_jlbc_memo.py`** renders a small fixture document and asserts
against the committed reference. Where practical it reads expected values **out
of the reference docx** rather than hardcoding them, so a future JLBC style
change is a fixture swap rather than a code rewrite:

- page margins match to the EMU
- the four masthead lines exist with the right sizes, alignment and tab stop
- the memo block is a 7×2 table with the reference's column widths and the four
  labels in order
- `TO:` reads `[Recipient(s)]` when no recipient is supplied, and the supplied
  value when one is
- `FROM:` carries `, via JLBC Agentic Search`
- a `##` line becomes a `Header`-styled bold 10.5 pt paragraph
- a `-` line becomes a bullet at 0.1875″
- the footer note is present on the first page as well as later pages
- body runs render at 10.5 pt

**`memo/`'s own import allowlist test**, mirroring the one on
`harness/documents.py`.

**`tests/test_create_document.py`** — whichever assertions pin today's generic
`Title`/`Heading 2`/`List Bullet` output are updated **deliberately in the same
commit**, not worked around. Its allowlist test gains `"memo"`.

**A human has to look at the output.** Every offline check here is structural.
Render a document, open it beside the reference, and confirm it reads as a JLBC
memo — the plan carries this as an explicit step, because a document that
passes every assertion and still looks wrong is the expected failure mode.

## Out of scope

- `docs/HANDBOOK.md` and `scripts/build_handbook.py` (Plan 5 Tasks 21–22). This
  work delivers the renderer they will use; it does not write the handbook.
- Any change to what the model *says* in a document — only how it is rendered.
- Retrieval, ingest, chunking, citation. Nothing under `retrieval/`, `ingest/`,
  `chunking/` or `citation/` is touched.

## The eval rule, and why it is not run here

CLAUDE.md asks for an eval run after any change to `harness/system-prompt.md`,
and M11 edits that file. **The eval cannot measure this change**:
`eval/run_eval.py` calls `retrieve()` directly and never reads the system
prompt, and the edit is confined to the `create_document` section, which no
retrieval path consults.

This is the same call recorded for S22/S23 in `STATUS.md` ("Eval not re-run,
deliberately") on the same reasoning, so it is a precedent rather than a new
exemption. It is stated here explicitly so a reviewer sees the rule was
considered rather than missed.
