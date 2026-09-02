---
status: shipped
---
# Headerless table chunks outside the operating-table scope (spec §5 rule 5)

**What this measures, in plain words.** Spec §3.1/§5 rule 5 asks: when a
table chunk has no year header (`FY 2024 / FY 2025 / …` across the top), is
that because it is the SECOND PIECE of a bigger table whose header sits in
an earlier chunk — in which case a "continuation-header borrow" could go
fetch that earlier chunk's header at answer time — or is it a table that
never had a year header to begin with, in which case there is nothing to
borrow and the mechanism would cost a live database read on every search
for no benefit? Phase A only covers the two agency-operating-table document
types (`approps-per-agency`, `baseline-per-agency`) and only the chunks that
carry a ladder word (`FUND SOURCES`, `AGENCY TOTAL`, etc.) — this measures
every table chunk OUTSIDE that scope.

**Population covered.** Every row in the live corpus's `budget_chunks`
table (`JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data`)
where `is_table = true` — **22,889 of 83,197 budget chunks**. This is a
full scan, not a sample: `ChunkStore.scan()` with no `limit` returns every
matching row. `fiscal_note_chunks` (14,161 rows) was **not** scanned —
operating tables and the ladder vocabulary in `chunking/table_text.py` are
a budget-document phenomenon; fiscal notes carry no `approps-per-agency` /
`baseline-per-agency` chunks and the spec discusses this rule only in the
budget-corpus context.

## Run

Command: `JLBC_DATA_DIR=/home/destin/YouCoded/Projects/ask-the-budget-az-dev/data/insight-data uv run python -m scripts.count_headerless_tables`

(See "Deviation from the sketch" below for why `-m scripts.count_headerless_tables`
rather than the brief's `python scripts/count_headerless_tables.py`.)

```
table chunks: 22889  in-scope: 4875  out-of-scope: 18014
out-of-scope with tab rows and NO header: 7411
  approps-per-agency       2323
  baseline-per-agency      1650
  detailed-list-pdf        1083
  afr                      1012
  governors-budget         972
  s-pdf                    132
  bd-pdf                   102
  bh-pdf                   87
  topic-pdf                50
```

## What the 7,411 chunks actually ARE (read by hand, not just counted)

The brief's template guesses a count "under 1,000." The real count is
**7,411 — well over that.** A number alone would point at "rule 5 is
built," so before deciding anything I read more than 30 of the actual
chunks across every doc type in the list, plus the chunks immediately
before and after several of them inside the same document, to find out
whether these are really split-off pieces of a bigger table.

**They are not.** Every one read is a complete, self-contained table that
simply never had two-or-more fiscal years side by side — the exact shape
`find_header` correctly returns nothing for, because there is nothing to
find, not because something was lost.

**The clearest evidence is inside a single document.** `jlbc-approps-fy2025-adc`
(Corrections, FY2025 Appropriations Report) chunks in order:

- `-0000` — **in scope, has a ladder marker, no header of its own** (a
  genuine phase-B continuation case, already handled): `FUND SOURCES /
  General Fund  1,385,450,900  1,420,670,200  1,537,433,400` — three years
  side by side.
- `-0001` — counted here: `Operating Budget / General Fund  FY 2025
  $821,758,300 / Alcohol Abuse Treatment Fund  250,300 / …` — a fund-source
  FOOTNOTE table for ONE year only, immediately below the ladder table in
  the printed page, but its own separate table with its own heading.
- `-0002` — counted here: `Statewide Adjustments / General Fund
  20,634,100 / Inmate Store Proceeds Fund  (7,000) / …` — another
  one-year, differently-headed table.
- `-0003` — counted here: another one-year `Operating Budget` footnote,
  a different fiscal year's fund breakdown.
- `-0004` — counted here: `Statewide Adjustments / Table 1 FY 2023
  Community Corrections Program Expenditures` — a named, numbered table
  with its own subject (comm. supervision program spending by category),
  nothing to do with the ladder table above it.

`-0001` through `-0004` are not `-0000` continuing — they are four
different named tables JLBC prints one after another on the same pages,
each answering a different question, and only one of them (`-0000`) is a
multi-year comparison. A "borrow the nearest earlier chunk's header"
mechanism applied to `-0001` would attach `-0000`'s three-year
`FY 2023 / FY 2024 / FY 2025` column labels to a table that has nothing
to do with those years — a wrong label is worse than no label, because it
would read as fact instead of an honest "we don't know."

**The same shape repeats across every doc type in the list**, read by
sampling several chunks from each:

- `approps-per-agency` / `baseline-per-agency` (3,973 combined, over half
  the total) — mostly county property-tax equalization tables, community
  college tax/tuition tables (each headed `Table 2`, `Table 5`, `Table 6`
  — named, numbered, one point in time), and the `Operating Budget` /
  `Statewide Adjustments` fund-breakdown footnotes shown above. A word
  search for the operating table's own line-item vocabulary
  (`Personal Services`, `Employee Related Expenditures`, `FTE Positions`)
  inside this bucket found it in only **32 of 3,973** chunks — and reading
  those 32 showed them to be the SAME kind of one-year footnote
  (`"The budget includes $35,423,700 and 299.9 FTE Positions... General
  Fund $816,600, Arizona Arts Trust Fund $60,000"`), not a mid-table
  continuation either.
- `detailed-list-pdf` (1,083) — dental/health-insurance contribution rate
  tables, employer contribution-rate schedules, statewide revenue forecast
  tables. Different subject, different shape, no year-over-year columns.
- `afr` (1,012) — the AFR's pie-chart-style summary pages: mostly blank
  tab-padded rows (MinerU's rendering of a chart) ending in one or two
  total lines like `TOTAL EXPENDITURES  $23,973,152,672` for a single
  year.
- `governors-budget` (972) — the Governor's budget "Table of Contents"
  funding-by-issue lines: `Funding  FY 2027 / General Fund  0.0 / Issue
  Total  0.0` — one year, one number.
- `s-pdf` (132) — Baseline "S" section summary pages (statewide General
  Fund spending/detailed changes lists) — dense multi-column pages that
  are visually table-shaped but carry only one explicit `FY` mention, not
  two side by side.
- `bd-pdf` (102) — capital outlay appropriation summaries, one fiscal
  year per table.
- `bh-pdf` (87) — the "Where It Comes From" / "Where It Goes" revenue and
  spending pie-chart pages, one year each.
- `topic-pdf` (50) — cross-agency topical tables (PSPRS contribution-rate
  changes, the Capital Outlay "Rent Adjustments" page). One of these
  (`jlbc-baseline-fy2025-capitaloutlay-0002`) genuinely DOES carry ladder
  words (`AGENCY TOTAL`, `SUBTOTAL`, `TOTAL - ALL SOURCES`) and is
  structurally a ladder table — it is correctly excluded from D1 by
  document type (`topic-pdf` is not `approps-per-agency` /
  `baseline-per-agency`), which is a scope decision already made
  elsewhere in the spec, not a defect this measurement should second-guess.

**None of the more than 30 chunks read, across all nine doc types, is a
truncated fragment of a table whose header lives in a chunk before it.**
Every one is a complete table on its own — mostly single-year fund/topic
breakdowns that never had a multi-year header to lose.

## Decision

**The count is dominated by tables that have no year columns anyway,
spread across nine doc types → rule 5 is DROPPED.** Those chunks fall to
today's plain text, same as before this phase existed.

**Why the raw count (7,411, far above the brief's "under 1,000" guess)
does not change the answer.** The brief's number was a guess made before
anyone read the chunks; the number that actually decides rule 5 is not
"how many are headerless" but "how many are headerless BECAUSE they are a
continuation of some other chunk's table." Reading a genuine cross-section
— including a full same-document chunk sequence that shows exactly what a
real ladder table (`-0000`) looks like next to what follows it — found
**zero** cases of the second kind. A borrow mechanism exists to answer "what
years does this row belong to," and for these 7,411 chunks that question
either has a one-word answer already printed in the table's own text (a
single `FY 2025` token, correctly not treated as a "header" because
`find_header` requires two or more) or does not apply at all (a named,
numbered, single-point-in-time table like `Table 5 Community College Tax
Rates`). Building a live store read into the retrieve path to answer a
question that has no continuation to find would add a new failure mode
(a wrong or stale chunk read at answer time) for a case that, on the
evidence read here, does not exist.

## Deviation from the sketch

The brief's script sketch runs as `uv run python scripts/count_headerless_tables.py`.
Running it that way fails: `python <path>` puts the SCRIPT's own directory
(`scripts/`) on `sys.path`, not the repo root, so `from chunking.table_text
import …` raises `ModuleNotFoundError: No module named 'chunking'`. This
repo has no installed package and no `sys.path` shim for scripts (verified:
no `.pth` file, no `conftest.py`-style path insertion for `scripts/`), so
the working invocation is **`uv run python -m scripts.count_headerless_tables`**,
which runs with the repo root on `sys.path` because it starts from the
current working directory rather than the script's own folder. The script's
own code is unchanged from the sketch — it matches `ChunkStore`'s real API
(`ChunkStore(create=False)`, `store.scan(name, columns, where=...)`)
exactly as written, verified against `store/chunk_store.py` before running.
The one-line module docstring's run command was corrected to match.
