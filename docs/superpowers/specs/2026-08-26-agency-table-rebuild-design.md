# Agency operating tables: rebuild from the page's own text, and show the model labelled cells

**Status:** approved 2026-08-26 (Destin); phase A shipped 2026-09-01; phase B
not started, pending the section-path repair. Scope and approach are his
calls and are not to be re-litigated: JLBC agency-page operating tables
only, approach B (rebuild from the PDF text layer, verified
arithmetically) in two phases, the labelled-cell rendering shipping first
on its own.

Companion review: `docs/superpowers/investigations/2026-08-26-agent-capability-review.md`
— the assessment that put this first among the improvements.
Implementation plan: `docs/superpowers/plans/2026-09-01-agency-table-rebuild.md`.

**Revised 2026-09-01 (second review, against the code, the live corpus and
two real pages read through PyMuPDF).** The corpus counts reproduce
(4,875 tables on 4,771 documents). What changed, and why:

- The §1 defect table now carries the reproduced counts; the first draft
  kept its 2026-08-26 numbers beside a note saying they had been
  reproduced as different numbers.
- **MinerU merges a two-page table itself.** The AHCCCS FY2026 example is
  ONE MinerU block on page 1 holding all 68 rows from both pages, plus an
  EMPTY table block on page 2 (chunk `jlbc-approps-fy2026-axs-0001`,
  text `""`). The first draft assumed every continuation was its own
  chunk. The rebuild now walks forward across pages by matching labels
  (§3.1 step 3) instead of trusting `table.pages`.
- **Fused footnote markers DO occur in the text layer.** The FY2006
  Exposition & State Fair page prints `15,352,3001/` as one word. The
  first draft said fused markers were MinerU's artefact only and gave the
  rebuild a font-metric rule for superscripts; that rule is gone and one
  digit-pattern peel serves both phases (§3.1 step 6, §5 rule 3).
- **Year headers are centred over their columns; figures are
  right-aligned.** On the AHCCCS page the year token spans x 295–315 and
  the figures end at x 334. A column is the nearest header centre, not
  the year token's right edge.
- **152 tables carry FOUR year columns** (FY2006 and FY2008 biennial
  budgets, one FY2014). "Three year columns" is now "two to four".
- §4 is one span rule instead of a label table. The first draft's
  "generic rule plus identities" could not pass a normal ladder
  (`SUBTOTAL - Appropriated Funds` has zero body rows above it), and a
  label table missed `PROGRAM TOTAL` and the ADC page's nested
  `Personal Services Subtotal`.
- **The gate is calibrated on the unrepaired corpus first** (§4.1), so a
  wrong rule is found before any PyMuPDF code exists.
- `render_labelled` takes `text` alone. Nothing in the app renders
  `table_html` (verified: it is stored, loaded into `RetrievedChunk`, and
  read by nothing), and the tab-joined text carries the same merges. The
  `text_format` payload key is dropped; `text_labelled`'s presence says
  what the model saw.
- Section 3.1 step 3 matched "each half of a merged label", which cannot
  be found without the text layer. The match now runs the other way.
- The section-path plan's machinery this spec reuses (`resolve_extract_dir`,
  the repair module) **is not in the repository yet**; D7 says so.
- **The reader and gate in the plan were run against 206 real pages
  before the plan was written** (199 rebuilt). That run replaced §4's
  label table with one span rule, found that a lone `Total` from a
  summary table matched `TOTAL - ALL SOURCES`, and found the wrap shape
  where the label breaks before its figures.

---

## 1. The defect, as measured 2026-08-26 and reproduced 2026-09-01

Every JLBC per-agency page (`approps-per-agency`, `baseline-per-agency`)
carries an operating-budget table — almost always one; 71 of the 4,771
in-scope documents carry two to four, mostly FY2006 pages with a table
per programme, and each is rebuilt and gated on its own. A label column
and two to four year columns (`FY N-2 ACTUAL / FY N-1 ESTIMATE / FY N
APPROVED|BASELINE`; the FY2006 and FY2008 biennial editions add
`FY N+1 APPROVED`), running from FTE positions through the special line
items to the fund ladder and `TOTAL - ALL SOURCES`. MinerU reads it with
a vision model and gets three things wrong. Counted over the **4,875**
table chunks on agency pages that contain a ladder marker (`OPERATING
SUBTOTAL`, `FUND SOURCES`, `AGENCY TOTAL`, `TOTAL - ALL SOURCES`):

| defect | tables | example (live chunk `jlbc-approps-fy2026-axs-0000`) |
|---|---|---|
| **two printed rows merged into one cell** | **2,336 (48%)** | `<td>SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds</td><td>377,583,700 2,778,602,700</td>…` |
| **footnote marker fused onto the figure** | 1,405 (29%) | `99,294,5003/` for 99,294,500 with footnote 3; `212.312/` for 212.3 FTE with footnote 12 |
| **no year header row** | 146 (3%); 131 are page-2 continuations | `FUND SOURCES / General Fund 7,699,669,300 7,882,875,800 <blank> 8,287,685,600` — five columns, no labels |

Only 3.2% of all numeric cells in these tables sit in a merged cell —
but they are the **subtotal and total rows**, which is what an analyst
asks for. In the AHCCCS example above the FY 2026 `TOTAL - ALL SOURCES`
cell reads `186,030,400 23,010,071,300`: the Federal Funds figure spilled
into the total's cell.

**The merging is in MinerU's own HTML** (`table_html`), not in our
flattening. `chunking/builders/table_chunk.py::_build_text` is a faithful
tab-join of rows that were already wrong. So "send the HTML instead of the
text" fixes nothing; the information is gone before we see it.

**Two shapes of two-page table.** MinerU sometimes merges the pages
itself: the AHCCCS example's page-1 block holds all 68 rows, page 1 and
page 2 alike, and page 2 carries an empty `table` block that became a
chunk with empty text. Other editions leave page 2 as its own block with
no header (the 131 continuations). The rebuild handles both by walking
pages until the table's labels run out (§3.1).

### 1.1 Why this is the first thing to fix

Of the 24 failures in the two most recent Layer 2 runs
(`eval/results/agent/2026-08-18T0850Z-6a28d03`, deepseek, and
`…T1041Z-b373e18`, gpt-5.6-luna), **10 are the model reading the wrong
column or the wrong rung of one of these tables**, and 2 more are
General-Fund-vs-expenditure-authority conflations on the same rows. The
GPT run made zero tool errors and still misread columns. Retrieval found
the right page (Layer 1 recall@15 is 97.6%); the model could not read it.

### 1.2 What the PDF itself knows

Every one of these PDFs, FY2005–FY2027, has a text layer with a position
for every word (25 documents sampled in every year, none thin or empty;
the FY2006 pages are typeset, not scanned). Reading the AHCCCS page by
coordinates gives, at y=91 and y=103 of page 2:

```
SUBTOTAL - Other Appropriated Funds   377,583,700    455,300,200    621,178,500
SUBTOTAL - Appropriated Funds       2,778,602,700  3,032,812,300  3,234,831,100
```

Two clean rows where MinerU produced one. Measured on that page and on
the FY2006 Exposition & State Fair page:

- The page-2 header (`FY 2024 / FY 2025 / FY 2026` at y=53, `ACTUAL /
  ESTIMATE / APPROVED` at y=66) is **printed** — MinerU dropped it.
- Year tokens are centred over their columns (`2024` at x 295–315);
  figures are right-aligned ending at x 333–334, 433, 532. The FY2006
  page has four columns centred at x 264, 347, 429, 512.
- Footnote markers are 6-pt words to the right of the last column
  (`3/` at x 534–540, one point below the row's baseline). On the FY2006
  page the marker is fused into the figure's word: `15,352,3001/`.
- Wrapped labels are a second line with no figures, indented: `Account`
  at x=61 under a label starting at x=52; `Funds` at x=69 under a
  `SUBTOTAL` row starting at x=61. Check rows are indented 9 pt.
- Group headings (`SPECIAL LINE ITEMS`, `Administration`, `Expenditure
  Authority Funds`) sit at the body indent with no figures.

---

## 2. Decisions

- **D1 — Scope is the JLBC agency-page operating table.** A chunk is in
  scope when `doc_type ∈ {approps-per-agency, baseline-per-agency}`,
  `is_table`, and its text contains a ladder marker. Summary tables
  (`s-pdf`, `bd-pdf`, `bh-pdf`), the Governor's budget, the AFRs and
  fiscal notes are **out of scope** — each has a different layout and a
  different defect (the Governor's has no agency labels and unstated
  units) and gets its own measurement and spec.
- **D2 — Read the table from the text layer; never trust the picture for
  numbers.** A new refinement step rebuilds the rows from PyMuPDF words
  and positions. MinerU's output is kept only as the anchor that says
  which rows and pages belong to the table (§3.1).
- **D3 — Never write a table that does not reconcile.** A rebuilt table
  is accepted only when every published subtotal equals the sum of its
  rows in every year column (§4). A table that fails keeps its current
  text and is counted. The count of unverifiable tables is the headline
  number of this work.
- **D4 — Chunk boundaries never move.** The repair rewrites `text`,
  `table_html`, `vector` and `token_count` inside an existing chunk.
  `chunk_id`, `page`, `bbox`, `section_path` (line 0 of the text),
  `caption`, and every stamp column are untouched. No chunk is split,
  merged, added or deleted. The empty page-2 chunks MinerU's own merge
  leaves behind are out of scope (no ladder marker) and stay as they are.
- **D5 — One producer.** The same refinement function runs at ingest
  (inside the MinerU reader, for every future agency page) and in the
  one-time repair of existing chunks. A future re-chunk from cached
  extractor output must reproduce the repaired text, or the repair is a
  one-off that the next ingest silently undoes.
- **D6 — The model reads labelled cells, not positions.** For every
  table chunk with a detectable header row — repaired or not, in scope
  or not — the `retrieve` payload carries a second field,
  `text_labelled`, rendering each cell as `column-header: value`. This
  is phase A and ships first, before any corpus write.
- **D7 — Sequencing.** The table-section-path repair
  (`docs/superpowers/specs/2026-08-26-table-section-path-design.md`)
  lands first. It rewrites line 0 of the same chunks and verifies that
  everything below line 0 still matches `_build_text(table)`; this
  repair breaks that identity by design, so it must come second. Its
  apply machinery (plan Tasks 4–8: dry run, per-row compare-and-swap,
  rehearsal on a copy, checkpoint) is reused here, not rebuilt. **As of
  2026-09-01 none of it is in the repository** — `ingest/extract_dirs.py`
  and `chunking/repair_section_paths.py` are that plan's deliverables,
  and phase B's plan opens by checking they exist. Once phase B has
  landed, that plan's G-T6 check ("the repair equals a re-chunk") must
  pass the source PDF to `chunk_doc`, or it will report the body as a
  false revert.

---

## 3. Phase B — the text-layer rebuild

### 3.1 The refinement function

`chunking/readers/text_layer_table.py::refine_operating_table(table, pdf) -> Table | None`

Input: a MinerU `Table` (rows, `page`, `pages`, `html`) that matches D1,
and the source PDF opened with PyMuPDF. Output: a new `Table` with the
same `page`, `pages`, `bbox`, `caption` and a rebuilt `rows` + `html`; or
`None` when the rebuild cannot be verified, in which case the caller
keeps MinerU's table unchanged.

The regexes for a year header, a figure and a footnote marker, the
D1 marker test and the peel live in one module, `chunking/table_text.py`,
imported by both phases so they cannot drift.

Steps, in order:

1. **Words.** `page.get_text("words")` on `table.page` — every word with
   `x0, y0, x1, y1`. If the page yields no words (a scan), return `None`.
2. **Lines.** Group words by baseline: two words share a line when their
   `y0` differ by less than half the median word height (the 6-pt
   markers sit one point below their row and land on it). Sort each line
   by `x0`.
3. **Anchor the table region, walking pages.** The anchor labels are
   MinerU's non-empty cell-0 texts, normalised (case-folded, whitespace
   collapsed, trailing markers stripped). A text-layer line **matches**
   when its non-figure text, normalised, is contained in some anchor
   label — the containment runs from the page toward MinerU, because a
   merged MinerU label (`SUBTOTAL - Other Appropriated Funds SUBTOTAL -
   Appropriated Funds`) contains both printed lines and nothing can split
   it the other way. A one-word line matches only an anchor it equals —
   a lone `Total` from a summary table further down the page must not
   pass for `TOTAL - ALL SOURCES`. On a page the region spans from the
   first matched line to the line matching MinerU's **last** row (not
   the last line matching any label: a prose heading `Operating Budget`
   further down the page matches the anchor `OPERATING BUDGET` and would
   drag the performance-measures block in). This keeps the ADE page's
   `Table 1 Basic State Aid Formula Summary` and the surrounding
   narrative out. If the last anchor label is not matched on
   `table.page`, the next page is read and its region appended, up to
   two pages forward, while the match count grows — this is how MinerU's
   own two-page merge (§1) is followed. If fewer than 80% of the anchor
   labels match a line, return `None` (80% is a starting value; the dry
   run reports the match-rate distribution and the threshold is set from
   it, not from this page). **If MinerU's last row is never matched,
   return `None`**: the region's end would be a guess, and a guessed end
   drops the fund ladder while the arithmetic on the rows above it still
   passes.
4. **Header and columns.** Search the lines above the first region on
   its page, then the region's first three lines, for a header: a line
   with two or more year tokens (`FY` immediately followed by a
   four-digit word, or one word `FY2024`), optionally followed by a line
   of kind tokens (`ACTUAL|ESTIMATE|EST.|APPROVED|BASELINE`,
   case-insensitive — FY2006 prints `Actual`). Each year token's
   **centre** is a column centre; a kind token attaches to the nearest
   centre and the column's label is `FY 2024 ACTUAL`. If the page has no
   header of its own (a continuation chunk with `pages=[2]`), the
   preceding page of the PDF is searched whole. No header on either page
   → `None`.
5. **Rows.** A line in the region is a row. Column boundaries are the
   midpoints between neighbouring centres; the label zone ends half a
   column spacing left of the first centre. A word whose centre lies in
   the label zone is label text; a figure word right of it belongs to
   the column whose centre is nearest its own centre. A line with label
   text and no figures, whose `x0` is greater than the previous row's
   `x0`, is a **wrapped label** and is appended to that row's label
   (`Account` under `Tobacco Products Tax Fund - Proposition 204
   Protection`; `Funds` under `SUBTOTAL - Appropriated/Expenditure
   Authority`). The other wrap shape — the label broke BEFORE the
   figures (`SUBTOTAL - Appropriated/Expenditure` on one line, the
   figures on the indented `Authority Funds` line under it, FY2006 DHS)
   — is joined when MinerU read the two lines as one label or the first
   line names a subtotal. A line with label text, no figures and no
   extra indent is a **group heading** and becomes a row with empty
   cells, as today.
6. **Footnote markers.** One peel, `table_text.split_figure_marker`,
   applied to every figure word: `99,294,5003/` → (`99,294,500`, `3/`);
   `212.312/` → (`212.3`, `12/`); `15,352,3001/` → (`15,352,300`, `1/`).
   A separate marker word (`3/`, `8/-13/`, `12/13/`, `1/2/`) whose centre
   falls right of the last column is attached to the last column's cell.
   A marker word in the label zone (`Medicaid Services 5/6/7/`) stays in
   the label. The cell renders as `99,294,500 [3/]` — the digits never
   touch the figure.
7. **Cells.** A figure is `\(?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?` or a
   bare `0`/`-`. Accounting parentheses are kept. A column with no word
   on a line is an empty cell — never a shifted one. Two figure words
   landing in one column on one line is a column-assignment failure →
   `None`.
8. **Verify (§4).** Fail → `None`.
9. **Emit.** `rows` in reading order: the header row first (`""` then
   the column labels), then each row as label + one cell per column;
   `html` regenerated from the rows by the same `<table><tr><td>` shape
   `_parse_html_table` reads, because the repair's fallback path (§3.2)
   is the only reader of stored HTML. `text` is then produced by the
   existing `_build_text` — line 0 section path, caption, tab-joined
   rows — so nothing downstream learns a new text shape.

### 3.2 Where it runs

- **Ingest:** `MinerUReader` gains a `source_pdf: Path | None`
  constructor argument; `read()` applies the refinement after
  `_reassemble_multi_page_tables` and before the outline is built, to
  every table that carries a ladder marker. **Today the reader cannot
  see the PDF**: `chunking/builder.py::chunk_doc(extractor_output_path,
  doc_meta, …)` takes only the extractor output, while the worker holds
  the source file (`ingest/worker.py::_source_path(job)`, and the
  `chunk_doc` call at line 1131). `chunk_doc` gains `source_pdf: Path |
  None = None` and passes it to `MinerUReader` only when
  `doc_meta.doc_type` is in D1's set and the path ends in `.pdf`; the
  worker passes `_source_path(job)`. Where it is absent (a unit test on
  cached output alone, a DOCX source, an out-of-scope document) the step
  is skipped and the table is MinerU's, as today.
- **Repair:** `chunking/repair_tables.py` (the pass, §6) obtains each
  in-scope chunk's MinerU `Table` **from the cached extractor output
  first** — `resolve_extract_dir(doc_id, root)` (the section-path plan's
  Task 3 helper; the layout is
  `extractor-output/<doc_id>[/<method>]/page-N.json`), read by
  `MinerUReader`, matched to the chunk by table index: `chunk_doc` emits
  tables first, numbered from 0, so table *i* of the document is chunk
  `<doc_id>-000i`. The repair then feeds the refinement the same object
  ingest does and D5 holds by construction. **329 in-scope documents have
  no extractor output on this machine** (the FY2025 Appropriations Report
  pages, measured 2026-09-01); for those, and only those, the `Table` is
  rebuilt from the stored `table_html` via `_parse_html_table` and the
  dry run reports them as a separate count, because D5 cannot be proven
  for them until that edition is re-extracted. Either way the function
  is called with the document's `source_blob_path` from `documents.json`,
  resolved through `app/routes/pdf.py::_resolve_blob` (some values are
  repo-relative `data/cached-pdfs/…`, not under the data dir), and the
  result written.

### 3.3 What is deliberately not attempted

- Tables MinerU never emitted at all (a page it read as prose) are not
  discovered. The anchor is MinerU's table.
- A page whose text layer disagrees with what is printed (a bad OCR
  layer on an old scan) is caught by §4, not by inspection.
- Sub-tables on agency pages (`Table 1 … Formula Summary`, the
  performance-measures block with its own `FY` header) are out of scope
  even though they are on in-scope documents; they lack the ladder
  marker and sit outside the anchor region.
- The empty chunks left by MinerU's own page merge (`…-axs-0001`) are
  not deleted or filled (D4).

---

## 4. The gate — a table must reconcile with itself

`chunking/table_gate.py::reconcile(rows) -> GateResult`, applied to
every rebuilt table before it is accepted, in every year column that has
any figure. Zero tolerance: JLBC prints whole dollars in hundreds, and
sums are exact. An empty cell in a body row is zero.

Rows are classified by normalised label (upper-cased, whitespace
collapsed, ASCII dashes, trailing footnote markers stripped):

| class | rule |
|---|---|
| **FTE row** | label contains `FULL TIME EQUIVALENT` or `FTE` — excluded from every sum |
| **check row** | label contains the word `TOTAL` or `SUBTOTAL` (`OPERATING SUBTOTAL`, `AGENCY TOTAL`, `PROGRAM TOTAL`, `SUBTOTAL - …`, `TOTAL - ALL SOURCES`, and the FY2023 ADC page's `Personal Services Subtotal`) |
| **group heading** | no figures in any column |
| **body row** | everything else |

**One rule, not a label table.** A check row must equal the sum of the
*items* since some earlier boundary — the table start, a group heading,
or a previous check row — where an item is a body row not already
covered by an intermediate check row, or that intermediate check row
itself. Candidates are tried nearest boundary first; the first that
equals the printed figure passes and records which rows it covered; if
none does, the check fails with the nearest candidate named. An empty
body cell is zero; a blank check cell skips that column. This one rule
is what makes every ladder JLBC prints reconcile:

- `OPERATING SUBTOTAL` = the operating body rows (boundary: the
  `OPERATING BUDGET` heading) — or, on the ADC page, `Personal Services
  Subtotal` + the loose rows + `Other Operating Expenditures Subtotal`.
- `AGENCY TOTAL` / `PROGRAM TOTAL` = `OPERATING SUBTOTAL` + every
  special line item (boundary: the table start; the special-line-item
  group headings are boundaries the rule tries and rejects). With no
  `OPERATING SUBTOTAL` row (FY2006), every body row.
- `SUBTOTAL - Other Appropriated Funds` (and the older `SUBTOTAL - Other
  Funds`) = the funds under their heading.
- `SUBTOTAL - Appropriated Funds` = `General Fund` + `SUBTOTAL - Other
  Appropriated Funds` (boundary: `FUND SOURCES`).
- `SUBTOTAL - Appropriated/Expenditure Authority Funds` = the two
  subtotals above (boundary: `FUND SOURCES`; the funds are covered).
- `TOTAL - ALL SOURCES` = that + `Other Non-Appropriated Funds` +
  `Federal Funds`.

**Plus one identity the span rule cannot express**, checked whenever
both rows exist: `AGENCY TOTAL` (or `PROGRAM TOTAL`) = `SUBTOTAL -
Appropriated/Expenditure Authority Funds` where an EA block exists,
else `SUBTOTAL - Appropriated Funds`, per column. The FY2020 Secretary
of State baseline page prints an `AGENCY TOTAL` that satisfies neither
the span rule nor this identity; it is refused, which is the gate doing
its job on a page that is wrong.

A wrong digit cannot pass: the candidates are a handful of specific
sums, and a check row that equals none of them fails. A table with no
check row at all cannot be verified and fails. The pass rate is
reported **per fiscal year** so a layout the rule does not recognise
shows up as a year with a low pass rate, not as silent acceptance.

Also required, by construction rather than as a separate veto: every
line in the anchored region becomes a row or a wrap, and two figures
landing in one column on one line refuse the table (§3.1 step 7), so
**no merged cell survives** and no printed row inside the region is
dropped. MinerU rows the page never matched are the 20% the anchor
threshold allows and are reported, not silently accepted — and MinerU's
last row must be among the matched (§3.1 step 3). The dry run reports
`rows_before` / `rows_after` per table for reading.

**Measured 2026-09-01 on 206 real agency pages** (random sample across
FY2005–FY2026, the reader and gate exactly as in the plan): 199
rebuilt, 1 refused for a printed total that does not add up, 1 refused
at a 78% anchor match. Earlier drafts of the rule — a label table with
"generic rule plus identities" and a "no row lost" count — failed 26 of
the first 44 pages, for reasons that were all the rule's: `OPERATING
SUBTOTAL` did not start with `SUBTOTAL`; nested subtotals on the ADC
page; a spilled figure counted as a lost row.

**Deliberately NOT a gate: "every MinerU figure survives".** That would
contradict D2 — a page where the vision model misread a digit is exactly
the page the text layer corrects, and the rule would refuse it for being
right. Instead the dry run records, per table, the **digit
disagreements**: figures MinerU printed that the text layer does not
contain, and vice versa, after the arithmetic gate has passed. The count
and 20 read examples are part of the checkpoint. This is the first
measurement anyone will have of how often the vision model put a wrong
digit in front of an analyst, which is a worse defect than a merged cell
and until now invisible.

### 4.1 Calibrate the gate on the unrepaired corpus first

Before any PyMuPDF code exists, `reconcile` is run over the tables
MinerU already read cleanly — the in-scope chunks with no merged cell
and no fused marker, roughly half of the 4,875 — exactly as they are
stored. Those tables are arithmetically whole, so every failure there is
the **rule's** fault, not the page's. The per-year pass table from this
run is recorded (plan: the calibration step) and the rule is fixed
until the clean tables pass. Without this, a low pass rate on the
rebuild could not be attributed to the rule or to the pages.

**The rebuild's pass rate is then measured across all 4,875 tables, per
year, before any write** (plan: the dry run). A pass rate under 90%
overall, or a year under 70%, stops the work for a look at the failures.

Gate on the error rate, not the production rate: the number reported is
"tables we could not verify", never "tables changed".

---

## 5. Phase A — labelled cells in the `retrieve` payload

`retrieval/table_view.py::render_labelled(text) -> str | None`
— a pure function over the chunk's tab-joined text; no store access, no
HTML.

For a table chunk, `harness/tools.py` adds the rendering to the payload
as **`text_labelled`** beside the unchanged `text`. **`text` itself is
not replaced**, for a reason the first draft got wrong: the payload
`text` is what the citation linker, the viewer and the Layer 2 scorer
read (below), and the first two hold offsets into the STORED text. The
prompt tells the model to read `text_labelled` when present. A saved
transcript says what the model saw by carrying the field. Rendering:

```
FY 2026 Budget                                   ← line 0 and caption, unchanged
General Fund | FY 2024 ACTUAL: 7,699,669,300 | FY 2025 ESTIMATE: 7,882,875,800 | FY 2026 APPROVED: 8,287,685,600
Full Time Equivalent Positions | FY 2024 ACTUAL: 212.8 | FY 2025 ESTIMATE: 212.8 | FY 2026 APPROVED: 212.3 [12/]
SPECIAL LINE ITEMS
```

Rules:

1. **Header detection** — `table_text.find_header`, shared with §3.1
   step 4. Among the first six tab-joined rows, the first with two or
   more cells containing a year token names the columns; if the next
   row's cells are kind tokens they are appended (`FY 2024` + `ACTUAL`
   → `FY 2024 ACTUAL`). A header cell with no year token but a kind
   token (the FY2006 `Estimate` column) is its own label. No header →
   return `None` and the tool sends the text as today.
2. **Empty cells are omitted**, not rendered as blanks. A blank fourth
   column cannot shift anything when every value carries its own label.
3. **Footnote peel** — `table_text.peel_markers`, the same function the
   rebuild uses, applied to every cell. Fused: `99,294,5003/` →
   `99,294,500 [3/]`; `212.312/` → `212.3 [12/]`; `(1,234,500)3/` →
   `(1,234,500) [3/]`. Separated: `15,916,000 4/` → `15,916,000 [4/]`;
   ranges and runs (`8/-13/`, `12/13/`) are one marker. A figure under
   1,000 with a fused marker (`5003/`) is ambiguous and is left alone.
4. **A merged cell** (two figures in one cell, unrepaired) renders as
   `FY 2026 APPROVED: 621,178,500 and 3,234,831,100 (two values in one
   cell — read with care)`. Honest, not hidden; phase B removes the
   case.
5. **Continuation header — measure before building.** A chunk with no
   header that is a continuation could borrow the nearest earlier table
   chunk's header from the same document, at the cost of a live store
   read inside the retrieve tool. Phase B removes the 131 in-scope
   cases; nobody has counted the out-of-scope ones. The plan's first
   step counts headerless table chunks outside D1's scope; if the number
   is small, this rule is dropped and those chunks fall to today's plain
   text. It is built only if the count justifies a new failure mode on
   every search.
6. Group-heading rows render as their label alone.
7. **Size cap.** A chunk whose `text` exceeds 20,000 characters is not
   rendered (`None`). The four 1.8 MB tab-padded AFR chunks would
   otherwise grow ~1.6× in a payload that is already the problem.

**System prompt:** one paragraph, placed under the existing "The 3-year
structure of per-agency tables" heading: table passages carry a
`text_labelled` field with every cell labelled by its column; read the
label, not the position; quote prose sentences for `cite`, never a table
row (already stated in the cite section, restated beside the format).
No other prompt change.

**What the payload `text` feeds, and why it is left alone.** The figure
linker builds its pool from the `text` field of the retrieve tool
messages still in the conversation — never from the store
(`harness/session.py::_conversation_chunks`, by design: the linker must
only see what the model saw). The webapp does the same: the resolved
chunk a citation chip carries is the payload's `text`
(`webapp/src/chat/citation-extract.ts`), and the PDF viewer and the
cited-text panel slice it with the server's offsets, which index the
STORED text. The Layer 2 scorer reads the same field
(`eval/agent_scoring.py`, the retrieved-figure and seen-text checks) and
ignores keys it does not know, so `text_labelled` changes no score. Had
`text` been replaced, a `cite()` into a table chunk's caption would
underline the wrong words with no error.

**Cost, stated once.** The labelled copy is ~1.6× the body, so a table
chunk's payload grows ~2.6×: 15 table chunks ≈ 40k characters ≈ 11k
tokens, of which ~7k is the new field. Accepted over a silent viewer
defect, and offset by fewer retries. If it proves to matter, the cheaper
shape is to send `text` truncated to line 0 for table chunks and have
the linker read `text_labelled` — a change to two consumers, not to this
decision.

**A benefit the first draft missed:** the linker scans the payload, so
the footnote peel makes `99,294,5003/` findable as `99,294,500`. Today
that figure is unlinkable. `eval/false_link_check.py` is run once with
the rendering as the pool text to confirm the false-link rate does not
move.

**What does not change:** the stored chunk, `citation/matching.py`
itself, the PDF locate endpoint, Budget Documents, the expanded search
card (`RetrieveView.tsx` previews the payload's `text`). `cite`
validates quotes against stored text; a quote copied from a rendered
line fails with the existing "quote not found" error, which is visible
and already covered by the prompt's rule against quoting table rows.

---

## 6. The repair pass

`chunking/repair_tables.py`, modelled on `chunking/repair_section_paths.py`
(the section-path plan's Tasks 4–8) and `funds/unstamp.py`. The helpers
both passes need — atomic JSON write, the `IN (…)` builder, the column
list, the reversal stamp, the store and embedder protocols, the
CRC-verified snapshot — move to `chunking/repair_common.py` and are
imported by both; the section-path module keeps its behaviour.

1. **Plan** (dry run, no lock): for every in-scope chunk, rebuild, gate,
   and record `{chunk_id, doc_id, fiscal_year, verdict, reason, source
   (extractor|html), rows_before, rows_after, merged_cells_removed,
   notes_separated, digit_disagreements}`. Print the per-year pass
   table, the extractor-vs-html source split, the digit-disagreement
   total with 20 read examples, the eval intersection (§7), and 20
   random before/after pairs for reading. Nothing is written. **The dry
   run is re-run after the section-path apply** if that apply happens
   between this plan's dry run and its apply — compare-and-swap would
   otherwise skip every row.
2. **Rehearse** the apply on a copy of the LanceDB directory. Re-run the
   dry run against the copy afterwards: it must report nothing left to
   change.
3. **Checkpoint** — Destin reads the before/after pairs and the pass
   table.
4. **Apply** under `IngestLock`, after a CRC-verified snapshot
   (`store/backup.py` via `identity.relabel._default_snapshot_and_verify`):
   per-row compare-and-swap on `text` (the row is skipped and counted
   if its text changed since the plan), write `text`, `table_html`,
   `token_count`, and `vector` (re-embedded with
   `LocalEmbedder.embed_batch(..., input_type="document")`); batched;
   then `build_fts_index` and `optimize` — re-added rows are invisible
   to BM25 until the index is rebuilt (the `funds/unstamp.py` lesson).
5. **Reversal record** at `<data_dir>/table-rebuild-reversal-<table>-<stamp>.json`
   carrying the old `text` and `table_html` per chunk (~25 MB); the
   vector is recomputable from the old text.
6. **Verify**: chunk-id set identical before and after; every untouched
   column identical on all touched rows plus a 200-row untouched sample;
   no rebuilt chunk contains a merged cell.

---

## 7. Gates

Named `G-OT*` (operating tables) because the section-path spec's gates
are already `G-T1`–`G-T6` with different meanings, and STATUS records
both in the same fortnight.

- **G-OT0 — the gate passes the clean tables** (§4.1), recorded per
  year before the rebuild is written.
- **G-OT1 — the reconciliation pass rate** (§4), measured on the dry run
  before any write and recorded in STATUS with the per-year table and
  the digit-disagreement count.
- **G-OT2 — Layer 1 eval unchanged within noise**, run as a CONTROL on
  the unmodified corpus immediately before the apply and again after,
  same machine, same query set, both result files committed. 5 of the
  51 ground-truth chunk ids are in-scope table chunks
  (`jlbc-approps-fy2025-unibor-0000`, `jlbc-baseline-fy2026-adc-0004`,
  `jlbc-baseline-fy2027-des-0010`, `jlbc-approps-fy2023-adc-0008`,
  `jlbc-baseline-fy2022-dhs-0006`); their ids do not change and their
  `anchor_text` must still be found in the rebuilt text — checked in
  the dry run. A rank movement on those five is expected and is not a
  regression; a status change is.
- **G-OT3 — end-to-end reproduction.** `chunk_doc` run over cached
  extractor output plus the source PDF for 40 in-scope documents
  reproduces the repaired chunks byte-for-byte (D5). This is the check
  the 2026-08-16 heading-inheritance fix lacked and was reverted for.
  It cannot cover the 329 documents with no extractor output (§3.2);
  STATUS says so rather than reporting D5 as proven corpus-wide.
- **G-OT4 — the model reads the right column.** A paid Layer 2 run of the
  lookup queries that failed on column/rung reading
  (`lk-asu-operating-fy2026`, `lk-dps-operating-fy2026`,
  `lk-adc-total-fy2026`, `lk-tou-tourism-fy2026`, `lk-min-operating-fy2025`,
  `cm-supplementals-fy2026`, `cm-university-funding-dr`), once after
  phase A and once after phase B, against a same-day control. Roughly
  $0.10 per run. Not a pass/fail gate on its own — n is small — but the
  reason the work exists, so it is run and recorded. **Destin decides
  when a paid run happens.**
- **G-OT5 — browser.** One repaired agency page opened from a citation
  chip: the highlight box unchanged, the cited-text panel showing
  separate subtotal rows, the Budget Documents passage card for the
  same chunk reading sensibly.

---

## 8. Testing

Mechanism in pytest, quality in the eval, per CLAUDE.md:

- **Vocabulary unit tests** (`table_text`): header detection over one
  and two rows, three and four columns, `FY2024` without a space, the
  FY2006 `Estimate`-only cell; the peel on every shape in §5 rule 3 and
  the under-1,000 refusal; the D1 marker test.
- **Gate unit tests**: a reconciling three-column ladder passes; the
  FY2006 four-column ladder with no `OPERATING SUBTOTAL` passes; the
  ADC page's nested `Personal Services Subtotal` passes; one wrong digit
  fails and names the nearest candidate; a variant-label ladder
  (`SUBTOTAL - Other Funds`) reconciles; the FTE row is excluded; a
  table with no check row fails; an accounting negative sums correctly.
- **Reader unit tests on synthetic pages**: build a PDF in the test with
  PyMuPDF (`insert_text` at coordinates) so no fixture needs the network
  and nothing opens the real store. Cases: a clean three-column table;
  two thin adjacent rows; a wrapped label; a footnote marker as a
  separate word right of the last column, and fused into the figure; a
  page-2 continuation with and without its own header; a MinerU table
  whose rows span two pages; a label that wrapped before its figures; a
  sub-table on the same page outside the anchor region; a summary
  table's lone `Total` standing in for a missing last row → `None`;
  accounting negatives; an empty column; a scanned page (no words) →
  `None`; an anchor match under 80% → `None`.
- **Rendering unit tests**: header detection over one and two rows;
  empty-cell omission; footnote peel on both shapes; the merged-cell
  sentence; no header → `None`; the size cap.
- **Tool test**: a fake store with one table chunk; the payload carries
  `text_labelled`; a narrative chunk is untouched; the locked
  response-shape test learns the new key.
- **Ingest test**: `chunk_doc` over a MinerU fixture with and without
  `source_pdf`; the refined text differs only in the table body.
- **Repair-pass tests** against a fake store that **applies writes**
  (the section-path plan's second-review lesson): dry run writes
  nothing; compare-and-swap skips a row whose text moved; the reversal
  file round-trips; the FTS rebuild is called after the write; the
  html-fallback path is counted separately.
- **Prompt test**: the paragraph is present in the budget render.

Mutation checks for each guard, in place with `git checkout` to
restore, per the memory note on mutation testing.

---

## 9. Risks and what is accepted

- **Some tables will not reconcile and will stay garbled.** Expected
  and accepted; they are counted, and the count is the result. The
  alternative — writing an unverified rebuild — is a number the model
  can cite with nothing behind it.
- **Text-layer quirks** (ligatures, split words, a `$` as its own word,
  a marker fused into the figure's word) are absorbed by the figure
  regex and the peel, or fail the gate.
- **Re-embedding changes the ranking of ~4,900 chunks.** G-OT2 is the
  guard. The section-path repair moved line 0 of the same chunks and
  expected no eval movement; this moves the body and expects the same,
  because the figures and labels the embedder sees are unchanged in
  substance. Adding a header row to the 146 headerless tables shifts
  what the embedder's window sees first; that is the intended change.
- **Payload size grows ~2.6×** for table chunks under phase A (§5, cost
  stated once there).
- **The "10 of 24 Layer 2 failures" attribution in §1.1 is a reading of
  the transcripts, not a measurement**, and the 2026-09-01 review did
  not re-read them. G-OT4 is what tests it.
- **A quote from a rendered row fails `cite`.** Visible, already
  forbidden by the prompt, and figures are linked by alias, not by
  quote.
- **An agency page hand-uploaded through the Upload page** goes through
  the same reader and gets the same refinement, because the reader is
  the one producer (D5).
- **The 80% anchor threshold and the two-page walk are starting values.**
  The dry run's match-rate distribution sets them.

---

## 10. Out of scope, recorded so it is not re-derived

- Summary tables (`s-pdf`, `bd-pdf`, `bh-pdf`, `detailed-list-pdf`) — a
  different layout (agency rows, year or fund columns); the rendering
  of §5 applies to them wherever a header is detectable, the rebuild
  does not.
- Governor's Executive Budget — OpenDataLoader, no `table_html`, no
  agency ids, units in thousands stated on 6 of 2,351 tables. Needs its
  own spec; the agency-label defect matters more than the columns.
- AFRs — the four 1.8 MB tab-padded chunks and the section paths are
  the section-path plan's and a trim pass's.
- Changing chunk boundaries, or re-extracting with a different tool.
- A `read_document` / `expand` tool, a calculator, the corpus-map
  section inventory — items 2–4 of the capability review, each its own
  spec.
