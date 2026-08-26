# Agency operating tables: rebuild from the page's own text, and show the model labelled cells

**Status:** approved 2026-08-26 (Destin). Scope and approach are his calls
and are not to be re-litigated: JLBC agency-page operating tables only,
approach B (rebuild from the PDF text layer, verified arithmetically) in
two phases, the labelled-cell rendering shipping first on its own.

Companion review: `docs/superpowers/investigations/2026-08-26-agency-capability-review.md`
— the assessment that put this first among the improvements.

---

## 1. The defect, as measured 2026-08-26

Every JLBC per-agency page (`approps-per-agency`, `baseline-per-agency`)
carries one operating-budget table: a label column and three year
columns (`FY N-2 ACTUAL / FY N-1 ESTIMATE / FY N APPROVED|BASELINE`),
running from FTE positions through the special line items to the fund
ladder and `TOTAL - ALL SOURCES`. MinerU reads it with a vision model
and gets three things wrong. Counted over the **4,875** table chunks on
agency pages that contain a ladder marker (`OPERATING SUBTOTAL`,
`FUND SOURCES`, `AGENCY TOTAL`, `TOTAL - ALL SOURCES`):

| defect | tables | example (live chunk `jlbc-approps-fy2026-axs-0000`) |
|---|---|---|
| **two printed rows merged into one cell** | **2,331 (48%)** | `<td>SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds</td><td>377,583,700 2,778,602,700</td>…` |
| **footnote marker fused onto the figure** | 1,406 (29%) | `99,294,5003/` for 99,294,500 with footnote 3; `212.312/` for 212.3 FTE with footnote 12 |
| **no year header row** | 149 (3%); 131 are page-2 continuations | `FUND SOURCES / General Fund 7,699,669,300 7,882,875,800 <blank> 8,287,685,600` — five columns, no labels |

Only 3.2% of all numeric cells in these tables sit in a merged cell —
but they are the **subtotal and total rows**, which is what an analyst
asks for. In the AHCCCS example above the FY 2026 `TOTAL - ALL SOURCES`
cell reads `186,030,400 23,010,071,300`: the Federal Funds figure spilled
into the total's cell.

**The merging is in MinerU's own HTML** (`table_html`), not in our
flattening. `chunking/builders/table_chunk.py::_build_text` is a faithful
tab-join of rows that were already wrong. So "send the HTML instead of the
text" fixes nothing; the information is gone before we see it.

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
for every word (sampled 5 documents per year across 7 years: 130–545
words on page 1, none empty). Reading the AHCCCS page by coordinates
gives, at y=91 and y=103 of page 2:

```
SUBTOTAL - Other Appropriated Funds   377,583,700    455,300,200    621,178,500
SUBTOTAL - Appropriated Funds       2,778,602,700  3,032,812,300  3,234,831,100
```

Two clean rows where MinerU produced one. The page-2 header row
(`FY 2024 / FY 2025 / FY 2026` at y=53, `ACTUAL / ESTIMATE / APPROVED` at
y=66) is **printed on the page** — MinerU dropped it. Footnote markers
are separate words. Wrapped labels appear as a second line with no
numbers, indented (`Account` at x=60 under a label starting at x=52).

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
  merged, added or deleted.
- **D5 — One producer.** The same refinement function runs at ingest
  (inside the MinerU reader, for every future agency page) and in the
  one-time repair of existing chunks. A future re-chunk from cached
  extractor output must reproduce the repaired text, or the repair is a
  one-off that the next ingest silently undoes.
- **D6 — The model reads labelled cells, not positions.** For every
  table chunk with a detectable header row — repaired or not, in scope
  or not — the `retrieve` payload renders each cell as
  `column-header: value`. This is phase A and ships first, before any
  corpus write.
- **D7 — Sequencing.** The table-section-path repair
  (`docs/superpowers/specs/2026-08-26-table-section-path-design.md`)
  lands first. It rewrites line 0 of the same chunks and verifies that
  everything below line 0 still matches `_build_text(table)`; this
  repair breaks that identity by design, so it must come second. Its
  apply machinery (plan Tasks 4–8: dry run, per-row compare-and-swap,
  rehearsal on a copy, checkpoint) is reused here, not rebuilt.

---

## 3. Phase B — the text-layer rebuild

### 3.1 The refinement function

`chunking/readers/text_layer_table.py::refine_operating_table(table, pdf) -> Table | None`

Input: a MinerU `Table` (rows, `page`, `pages`, `html`) that matches D1,
and the source PDF opened with PyMuPDF. Output: a new `Table` with the
same `page`, `pages`, `bbox`, `caption` and a rebuilt `rows` + `html`; or
`None` when the rebuild cannot be verified, in which case the caller
keeps MinerU's table unchanged.

Steps, in order:

1. **Words.** For each page in `table.pages`, `page.get_text("words")` —
   every word with `x0, y0, x1, y1`. If a page yields no words (a scan),
   return `None`.
2. **Lines.** Group words by baseline (`y0` rounded; two words share a
   line when their `y0` differ by less than half the median word
   height). Sort each line by `x0`.
3. **Anchor the table region.** Match the MinerU table's row labels
   (each cell-0 text, and each half of a merged label) against the
   lines by normalised text. The table on a page spans from the first
   matched line to the last matched line inclusive. This is what keeps
   the ADE page's `Table 1 Basic State Aid Formula Summary` and the
   surrounding narrative out of the operating table, and it is why
   MinerU's output is still needed: it says which rows are the table.
   If fewer than 80% of MinerU's row labels match a line, return `None`
   (80% is a starting value; the plan's dry run reports the match-rate
   distribution and the threshold is set from it, not from this page).
4. **Header and columns.** Within the region (or the lines immediately
   above it on the same page), find the header: a line whose words are
   `FY` + year tokens, optionally followed by a line of
   `ACTUAL|ESTIMATE|APPROVED|BASELINE|EST.` tokens. Each year token's
   `x1` is a column's right edge. A page with no header of its own
   inherits the previous page's columns (page 2 usually has one; the
   131 continuation chunks are the case where it is missing). No header
   on any page → `None`.
5. **Rows.** A line is a row. Words with `x1` at or left of the label
   boundary (the leftmost column edge minus a margin) are the label;
   every other word is assigned to the column whose right edge is
   nearest its own `x1` (figures are right-aligned). A line whose label
   is non-empty and which carries no numbers, sitting directly under a
   row and indented, is a **wrapped label** and is appended to that
   row's label. A line with a label and no numbers that is not indented
   is a **group heading** (`SPECIAL LINE ITEMS`, `Expenditure Authority
   Funds`) and becomes a row with empty cells, as today.
6. **Footnote markers.** A word matching `\d{1,2}/` (or a run like
   `29/-31/`) immediately right of a figure, or with a smaller font size
   and a raised baseline, is a marker. It is recorded on the cell as
   `note="3"` and rendered as `99,294,500 [3/]` — the digits never touch
   the figure. A word that MinerU fused (`99,294,5003/`) does not occur
   in the text layer; the rule exists for the rendering of unrepaired
   chunks (§5) and as the fallback when a marker's font metrics are not
   distinguishable.
7. **Cells.** A figure is `\(?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?` or a
   bare `0`/`-`. Accounting parentheses are kept. A column with no word
   on a line is an empty cell — never a shifted one.
8. **Verify (§4).** Fail → `None`.
9. **Emit.** `rows` in reading order; `html` regenerated from the rows
   (`<table><tr><td>…`), one `<td>` per column, header row first,
   markers rendered inside the cell after the figure. `text` is then
   produced by the existing `_build_text` — line 0 section path, caption,
   tab-joined rows — so nothing downstream learns a new text shape.

### 3.2 Where it runs

- **Ingest:** `MinerUReader.read()` after `_reassemble_multi_page_tables`
  and before the outline is built, for tables that match D1, when the
  source PDF is available to the reader. **Today it is not**:
  `chunking/builder.py::chunk_doc(extractor_output_path, doc_meta, …)`
  takes only the extractor output, while the worker holds the source
  file (`ingest/worker.py::_source_path(job)`, and the `chunk_doc` call
  at line 1133). `chunk_doc` and the reader each gain an optional
  `source_pdf: Path | None` argument and the worker passes it. Where it
  is absent (a unit test on cached output alone, a DOCX source) the
  step is skipped and the table is MinerU's, as today.
- **Repair:** `chunking/repair_tables.py` (the pass, §6) loads each
  in-scope chunk, rebuilds its MinerU `Table` from the stored
  `table_html` (the reader's `_parse_html_table` already does this),
  calls the same function with the document's `source_blob_path`, and
  writes the result.

### 3.3 What is deliberately not attempted

- Tables MinerU never emitted at all (a page it read as prose) are not
  discovered. The anchor is MinerU's table.
- A page whose text layer disagrees with what is printed (a bad OCR
  layer on an old scan) is caught by §4, not by inspection.
- Sub-tables on agency pages (`Table 1 … Formula Summary`) are out of
  scope even though they are on in-scope documents; they lack the
  ladder marker.

---

## 4. The gate — a table must reconcile with itself

Applied to every rebuilt table before it is accepted, in every year
column that has any figure. Zero tolerance: JLBC prints whole dollars
in hundreds, and sums are exact.

Rows are classified by label:

| class | rule |
|---|---|
| **check row** | label starts with `SUBTOTAL`, `TOTAL`, or `AGENCY TOTAL` |
| **group heading** | no figures in any column |
| **FTE row** | label contains `Full Time Equivalent` or `FTE` — excluded from every sum |
| **body row** | everything else |

A check row must equal the sum of the body rows between it and the
previous check row or group heading, **plus** any earlier check rows that
are its named components:

- `OPERATING SUBTOTAL` = the operating body rows.
- `AGENCY TOTAL` = `OPERATING SUBTOTAL` + every special-line-item body row.
- `SUBTOTAL - Other Appropriated Funds` = the other-appropriated body rows.
- `SUBTOTAL - Appropriated Funds` = `General Fund` + `SUBTOTAL - Other Appropriated Funds`.
- `SUBTOTAL - Expenditure Authority Funds` = the expenditure-authority body rows.
- `SUBTOTAL - Appropriated/Expenditure Authority Funds` = the two subtotals above.
- `TOTAL - ALL SOURCES` = that + `Other Non-Appropriated Funds` + `Federal Funds`.
- `AGENCY TOTAL` = `SUBTOTAL - Appropriated Funds` (or `…Appropriated/Expenditure Authority Funds` where an EA block exists), per column.

Older editions use variant labels (`SUBTOTAL - Other Funds`, no EA
block). The implementation matches on the ladder's **shape** — the
generic "a check row equals the body rows since the last boundary" rule
plus the identities above where their labels are present — and reports
the pass rate **per fiscal year** so a layout the rule does not recognise
shows up as a year with a low pass rate, not as silent acceptance.

Also required, independent of the ladder:

- **No number lost.** Every figure token in the current chunk text
  appears in the rebuilt text (a fused `99,294,5003/` counts as its
  figure `99,294,500`). Splitting a merged cell adds rows; it never
  drops one.
- **No merged cell survives.** No cell in the rebuilt table contains two
  figures.

**The pass rate is measured across all 4,875 tables, per year, before
any write** (plan: the dry run). A pass rate under 90% overall, or a
year under 70%, stops the work for a look at the failures — the rule may
be wrong before the pages are.

Gate on the error rate, not the production rate: the number reported is
"tables we could not verify", never "tables changed".

---

## 5. Phase A — labelled cells in the `retrieve` payload

`retrieval/table_view.py::render_labelled(text, table_html, *, header=None) -> str | None`
— a pure function, no store access.

For a table chunk, `harness/tools.py` replaces the payload's `text` with
the rendering and adds `"text_format": "labelled-cells"` so a saved
transcript says what the model saw. Rendering:

```
FY 2026 Budget                                   ← line 0 and caption, unchanged
General Fund | FY 2024 ACTUAL: 7,699,669,300 | FY 2025 ESTIMATE: 7,882,875,800 | FY 2026 APPROVED: 8,287,685,600
Full Time Equivalent Positions | FY 2024 ACTUAL: 212.8 | FY 2025 ESTIMATE: 212.8 | FY 2026 APPROVED: 212.3 [12/]
SPECIAL LINE ITEMS
```

Rules:

1. **Header detection.** The first row with two or more cells matching
   `FY ?\d{4}` optionally followed by `ACTUAL|ESTIMATE|APPROVED|BASELINE|EST\.?`
   (possibly split over two rows) is the header. Its cells name the
   columns. No header → return `None` and the tool sends the text as
   today.
2. **Empty cells are omitted**, not rendered as blanks. A blank fourth
   column cannot shift anything when every value carries its own label.
3. **Footnote peel** on unrepaired text: `(\d{1,3}(?:,\d{3})+)(\d{1,2})/`
   → `\1 [\2/]`; `(\d+\.\d)(\d{1,2})/` → `\1 [\2/]` (JLBC FTE prints one
   decimal). A marker already separated by a space is rendered the same
   way.
4. **A merged cell** (two figures in one cell, unrepaired) renders as
   `FY 2026 APPROVED: 621,178,500 and 3,234,831,100 (two values in one
   cell — read with care)`. Honest, not hidden; phase B removes the
   case.
5. **Continuation header.** When a chunk has no header and is a
   continuation, the tool looks up the nearest earlier table chunk of
   the same document that has one (one projected store read on the ~3%
   of chunks affected) and passes it as `header=`. After phase B this
   path is rarely taken; it stays because out-of-scope tables use it.
6. Group-heading rows render as their label alone.

**System prompt:** one paragraph in the `retrieve` section: table
passages arrive with every cell labelled by its column; read the label,
not the position; quote prose sentences for `cite`, never a table row
(already stated, restated beside the format). No other prompt change.

**What does not change:** the stored chunk, the citation matcher
(`citation/matching.py` scans stored text, and the values are the same
tokens), the PDF locate endpoint, the cited-text panel, Budget
Documents. `cite` validates quotes against stored text; a quote copied
from a rendered line fails with the existing "quote not found" error,
which is visible and already covered by the prompt's rule against
quoting table rows.

---

## 6. The repair pass

`chunking/repair_tables.py`, modelled on the section-path plan's Tasks 4–8
and `funds/unstamp.py`:

1. **Plan** (dry run, no lock): for every in-scope chunk, rebuild, gate,
   and record `{chunk_id, verdict, reason, rows_before, rows_after,
   merged_cells_removed, notes_separated}`. Print the per-year pass
   table, the eval intersection (§7), and 20 random before/after pairs
   for reading. Nothing is written.
2. **Rehearse** the apply on a copy of the LanceDB directory. Re-run the
   dry run against the copy afterwards: it must report nothing left to
   change.
3. **Checkpoint** — Destin reads the before/after pairs and the pass
   table.
4. **Apply** under `IngestLock`, after a CRC-verified snapshot
   (`store/backup.py`): per-row compare-and-swap on `text` (the row is
   skipped and counted if its text changed since the plan), write
   `text`, `table_html`, `token_count`, and `vector` (re-embedded with
   `LocalEmbedder.embed_batch(..., input_type="document")`); batched;
   then `build_fts_index` and `optimize` — re-added rows are invisible
   to BM25 until the index is rebuilt (the `funds/unstamp.py` lesson).
5. **Reversal record** at `<data_dir>/table-rebuild-reversal-<stamp>.json`
   carrying the old `text` and `table_html` per chunk (~25 MB); the
   vector is recomputable from the old text.
6. **Verify**: chunk-id set identical before and after; every untouched
   column identical on all touched rows plus a 200-row untouched sample;
   no rebuilt chunk contains a merged cell.

---

## 7. Gates

- **G-T1 — the reconciliation pass rate** (§4), measured on the dry run
  before any write and recorded in STATUS with the per-year table.
- **G-T2 — Layer 1 eval unchanged within noise**, run as a CONTROL on
  the unmodified corpus immediately before the apply and again after,
  same machine, same query set, both result files committed. 5 of the
  51 ground-truth chunk ids are in-scope table chunks
  (`jlbc-approps-fy2025-unibor-0000`, `jlbc-baseline-fy2026-adc-0004`,
  `jlbc-baseline-fy2027-des-0010`, `jlbc-approps-fy2023-adc-0008`,
  `jlbc-baseline-fy2022-dhs-0006`); their ids do not change and their
  `anchor_text` must still be found in the rebuilt text — checked in
  the dry run. A rank movement on those five is expected and is not a
  regression; a status change is.
- **G-T3 — end-to-end reproduction.** `chunk_doc` run over cached
  extractor output plus the source PDF for 40 in-scope documents
  reproduces the repaired chunks byte-for-byte (D5). This is the check
  the 2026-08-16 heading-inheritance fix lacked and was reverted for.
- **G-T4 — the model reads the right column.** A paid Layer 2 run of the
  lookup queries that failed on column/rung reading
  (`lk-asu-operating-fy2026`, `lk-dps-operating-fy2026`,
  `lk-adc-total-fy2026`, `lk-tou-tourism-fy2026`, `lk-min-operating-fy2025`,
  `cm-supplementals-fy2026`, `cm-university-funding-dr`), once after
  phase A and once after phase B, against a same-day control. Roughly
  $0.10 per run. Not a pass/fail gate on its own — n is small — but the
  reason the work exists, so it is run and recorded.
- **G-T5 — browser.** One repaired agency page opened from a citation
  chip: the highlight box unchanged, the cited-text panel showing
  separate subtotal rows, the Budget Documents passage card for the
  same chunk reading sensibly.

---

## 8. Testing

Mechanism in pytest, quality in the eval, per CLAUDE.md:

- **Reader unit tests on synthetic pages**: build a PDF in the test with
  PyMuPDF (`insert_text` at coordinates) so no fixture needs the network
  and nothing opens the real store. Cases: a clean three-column table;
  two thin adjacent rows; a wrapped label; a footnote marker (both as a
  separate word and as a smaller raised word); a page-2 continuation
  with and without its own header; a sub-table on the same page outside
  the anchor region; accounting negatives; an empty column; a scanned
  page (no words) → `None`.
- **Gate unit tests**: a reconciling table passes; one wrong digit
  fails; a variant-label ladder (`SUBTOTAL - Other Funds`) reconciles
  under the shape rule; the FTE row is excluded; a lost number fails.
- **Rendering unit tests**: header detection over one and two rows;
  empty-cell omission; footnote peel on both shapes; the merged-cell
  sentence; continuation header injection; no header → `None`.
- **Tool test**: a fake store with one table chunk; the payload carries
  `text_format` and the labelled text; a narrative chunk is untouched.
- **Repair-pass tests** against a fake store that **applies writes**
  (the section-path plan's second-review lesson): dry run writes
  nothing; compare-and-swap skips a row whose text moved; the reversal
  file round-trips; the FTS rebuild is called after the write.
- **Prompt test**: the paragraph is present in the budget render.

Mutation checks for each guard, in place with `git checkout` to
restore, per the memory note on mutation testing.

---

## 9. Risks and what is accepted

- **Some tables will not reconcile and will stay garbled.** Expected
  and accepted; they are counted, and the count is the result. The
  alternative — writing an unverified rebuild — is a number the model
  can cite with nothing behind it.
- **Text-layer quirks** (ligatures, split words, a `$` as its own word)
  are absorbed by the figure regex or fail the gate. Fonts where a
  footnote superscript is neither smaller nor raised fall back to the
  digit-pattern rule.
- **Re-embedding changes the ranking of ~4,900 chunks.** G-T2 is the
  guard. The section-path repair moved line 0 of the same chunks and
  expected no eval movement; this moves the body and expects the same,
  because the figures and labels the embedder sees are unchanged in
  substance.
- **Payload size grows ~1.6×** for table chunks under phase A (labels
  repeated per cell). 15 table chunks ≈ 25k characters ≈ 7k tokens;
  acceptable, and offset by fewer retries.
- **A quote from a rendered row fails `cite`.** Visible, already
  forbidden by the prompt, and figures are linked by alias, not by
  quote.
- **An agency page hand-uploaded through the Upload page** goes through
  the same reader and gets the same refinement, because the reader is
  the one producer (D5).

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
