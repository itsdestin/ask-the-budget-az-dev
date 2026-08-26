# Agent capability review — can AI Mode answer what a JLBC analyst actually asks? (2026-08-26)

Read-only review of `harness/system-prompt.md` (1,416 lines, ~16k tokens
rendered), `harness/tools.py`, `retrieval/pipeline.py`, the live corpus,
and the two most recent Layer 2 eval runs (`2026-08-18T0850Z-6a28d03`
deepseek-v4-flash, judged; `2026-08-18T1041Z-b373e18` gpt-5.6-luna,
unjudged). Nothing was changed.

## Bottom line

The agent is a good **single-page lookup tool** and a weak **analyst**.
On the one question shape the eval mostly tests — "what is agency X's
FY N operating budget" — it lands 71–76%. On the shapes an analyst asks
that the eval does not test (cross-agency roll-ups, ten-year trends,
footnotes, Governor-vs-enacted, percent changes, "what funds does X
use", "summarize this agency's budget") it is structurally unable to
answer well, and the reasons are not the model — they are what the
tools let it see.

Retrieval is not the bottleneck for either speed or quality. A search
takes 0.6–0.8 s and finds the right document 97.6% of the time at
recall@15. The failures happen **after** retrieval: the model reads a
flattened, tab-separated table and picks the wrong column, the wrong
row, or the wrong document stage.

## What the corpus can support (facts)

| Collection | Years | Notes |
|---|---|---|
| Approps Report agency pages | FY2005–FY2027, every year | 42k chunks; the enacted number for any agency any year |
| Baseline agency pages | FY2012–FY2027, every year | 27k chunks |
| Approps/Baseline summary sections | FY2012+ (baseline), sparse before FY2026 (approps) | GF Summary by Agency, One-Time Spending by Agency, "Then and Now" 10-year tables, BSF, GF Revenue, BRB provisions, Major Footnote Changes |
| Governor's Executive Budget | FY2025–2027 only | **No agency label on any chunk; units in thousands stated on 6 of 2,351 tables** |
| AGAO AFR | FY2021–2025 only | Four chunks are 1.8 MB of tab padding; section paths wrong |
| Budget bill | FY2026 only | one DOCX |
| Agency budget requests, bill summaries | **zero** | the prompt describes both as if present |
| Fiscal notes | 1999–2026 | separate corpus; bill number only in title/doc_id |

A `FOOTNOTES` section exists on ~92% of approps pages from FY2020 on and
~0% before FY2020. FTE rows are legible (4,080 table chunks carry
`Full Time Equivalent Positions <n> <n> <n>`). The word "proviso" never
appears; Arizona's term is "footnote".

## Analyst question shapes vs. what the agent can do

| Shape | Answerable today? | Why / why not |
|---|---|---|
| One number, one agency, one year (FY2005+) | Mostly (71–76%) | Failures are reading errors: wrong column, wrong rung of the fund ladder, baseline vs enacted |
| FTE count | Yes | row is legible, but footnote digits fuse onto numbers (`212.312/`) in 3,411 tables |
| "What changed and why" for an agency | Yes, well | each change is its own narrative chunk with clean prose |
| Footnotes / legislative intent | FY2020+ only | section labelling absent on older pages; prompt never tells the model the vocabulary |
| 3-year comparison | Usually | `spread` handles it |
| 10+ year trend | Poorly | `spread` caps at 8 groups; 13 years = 2 calls and ~40 table chunks (~40k tokens). The "Then and Now" summary tables would answer it directly, but the model is never told they exist |
| Cross-agency roll-up ("total GF on behavioral health", "which agencies got one-time money", "rank agencies by GF") | Poorly | the summary tables exist (GF Summary by Agency, One-Time by Agency) but are split across chunks with the header only in the first, and there is no way to read a whole table |
| Governor vs JLBC vs enacted | Weak | Governor chunks carry no agency id (an agency filter returns nothing) and no units — a 1,000× hazard on every cited figure |
| Fund balance | FY2021–25 only | AFR chunks are the worst-formed in the corpus |
| "What funds does agency X draw on" | Weak | the FUND SOURCES block at the bottom of every operating table is where rows and columns merge (`Other Non-Appropriated Funds Federal Funds 151,730,300 150,981,400`) |
| Percent change / inflation-adjusted / sums | No auditable path | no calculator; "in today's terms" was answered nominally; the prompt (correctly) forbids hand-summing the ladder |
| "Summarize agency X's budget" | Partial | no document-read tool; an agency page is 15–30 chunks and the caps are 5/15/24 |
| Fiscal note ↔ appropriation cross-reference | Impossible in one chat | two corpora, one picker |
| Statutory/BRB changes | FY2026–27 mostly | "Budget Reconciliation Bill Provisions" sections exist recently, sparse earlier |
| Agency requests, bill summaries | No | not ingested |

## Where the 13 + 11 recent failures actually come from

| Cause | Deepseek run | GPT run | Fixable by |
|---|---|---|---|
| Wrong column / wrong rung of the same table | 4 | 6 | structured table access |
| Baseline used where enacted was asked | 3 | 1 | prompt + doc-type default |
| Right number, no citation emitted | 4 | 0 | model behaviour (gpt run: 0 tool errors) |
| Wrong year / wrong episode | 2 | 2 | retrieval miss on one; reading on the other |
| GF vs expenditure-authority conflation | 1 | 1 | structured table access |

Two thirds of the failures are the model misreading a table. **Correction
made the same day:** the stored HTML (`table_html`) is NOT clean — MinerU
itself merges adjacent thin rows into one cell (2,331 of 4,875 operating
tables) and fuses footnote digits onto figures (1,406). The flattened text
is a faithful copy of an already-garbled table. The fix is therefore to
rebuild these tables from the PDF's own text layer, not to send the HTML;
see `docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md`.

## Defects in the system prompt itself

1. **It contradicts its own corpus map.** "Covers … the most-recent few
   fiscal years" (line 9); "Question references a year before FY15 →
   older material may exist but has not been indexed" (§8); the doc_type
   table annotates `baseline-per-agency` "(FY26, FY27)" and
   `approps-per-agency` "(FY25 enacted)". The map two screens later says
   FY2005–FY2027. A model told both will sometimes refuse a historical
   question it could answer — and `historical` is the weakest eval shape.
2. **It lists two document types that hold zero documents**
   (`agency-submission`, `budget-bill-summary`) with search recipes.
3. **It mandates the sentence its own hygiene rule bans.** "Conversation
   rhythm" requires *"let me pull the relevant budget documents"*; the
   scorer flags that exact phrase as meta-narration on 6 of 45 answers.
4. **The corpus map lists collections, not contents.** The model cannot
   know that "General Fund Summary by Agency", "Summary of One-Time
   Spending by Agency" or "Then and Now" exist, so it reconstructs
   roll-ups from agency pages instead of reading the table JLBC already
   built.
5. **No vocabulary bridge**: proviso → footnote; "state support" → GF;
   "position" → FTE. Cheap to add.
6. ~16k tokens per step. Cached, so cost is fine; but the fiscal-note
   and budget branches, the cite recipe (obsolete for figures), and the
   legacy offset path are dead weight the model re-reads every step.

## Tool gaps (facts from `harness/tools.py`)

- `table_html` is stored on every table chunk and **never sent**.
- No `read_document` / `expand(chunk_id)` / neighbour fetch; `chunk_id` is
  only usable in `cite`.
- No calculator; computed figures are labelled "computed" by the UI
  with no trail of what they were computed from.
- `fund_mentions` is filterable in the store and absent from the schema
  the model sees; `fund_canonical_id` was used **0 times** in both runs.
- Tool calls within one step execute sequentially (`session.py:789`).
- Chunk text is sent untruncated. The four 1.8 MB AFR chunks did not
  surface in two test queries, but nothing stops them.

## Recommendations, ranked

### 1. Send tables as tables (biggest quality lever)

Rebuild the JLBC agency operating tables from the PDF text layer
(positions), verified arithmetically, and hand the model every cell
labelled with its column header instead of tab-flattened positions.
This attacks the dominant failure class in both runs. Specced at
`docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md`.

- Pros: directly targets ~60% of observed failures; no UI change; the
  citation matcher also stops seeing `99,294,5003`.
- Cons: touches `chunking/` → eval gate; if chunk text changes, chunk
  ids and the eval ground truth must be preserved (add fields, do not
  rewrite `text`). The in-flight table-section-path plan is adjacent
  and should land first.
- What the analyst experiences: fewer confidently wrong numbers;
  nothing visibly different.

### 2. Fix the prompt (one afternoon, no eval risk to retrieval)

Remove the three stale year claims; drop the two empty doc types until
ingested; reconcile the acknowledgment rule with the narration rule
(keep the acknowledgment — it is good UX — and stop the scorer counting
it); add the vocabulary bridge; extend the corpus map to name the
summary sections available per year.

- Pros: cheap; removes false refusals on FY2005–FY2019 questions.
- Cons: prompt edits are unmeasurable by Layer 1; needs one paid smoke
  run to see the effect.
- What the analyst experiences: historical questions stop being
  refused; roll-up questions start landing on the right table.

### 3. A bounded `read_document(doc_id, pages?)` / `expand(chunk_id)` tool

Lets the model read a whole agency page or a whole summary table.

- Pros: unlocks "summarize agency X", cross-agency roll-ups, and
  10-year trends from the "Then and Now" tables in one call instead of
  eight.
- Cons: token cost — cap it (e.g. 40k characters) and keep it off the
  first call; a Standard-tier answer that uses it is slower.
- What the analyst experiences: longer questions get complete answers
  instead of a partial table; those answers take longer.

### 4. A `calculate` tool with an auditable trail

Returns the arithmetic as a string the citation layer can show
("computed: 133,115,400 − 119,548,900 = 13,566,500, +11.3%").

- Pros: percent change is the single most common analyst operation;
  today it is unverifiable and the prompt tells the model to refuse it.
- Cons: none structural; the "never hand-sum the fund ladder" rule still
  holds and the tool must not be read as permission to break it.
- What the analyst experiences: a computed figure chip that shows its
  inputs and can be checked in one glance.

### 5. Expand the eval before tuning

20 of the 45 quick queries are one template. Add footnotes, roll-ups,
Governor-vs-enacted, 10-year trends, fund sources, FTE, BRB changes,
and the refusal/deep sets (never run). Without this none of 1–4 can be
measured, and the CLAUDE.md rule about gating on error rate cannot be
applied.

### 6. Data repairs that feed the model bad input

Governor's budget: stamp agency ids and state units. Footnote-digit
separation corpus-wide. Drop the 398 empty chunks and trim the four
tab-padded AFR chunks. All are read-around today; each one shows up as
a wrong number in an answer.

### 7. Ingest gaps

Budget bills for years other than FY2026 (DOCX from JLBC internal);
the 78 agency requests (18 need a browser); bill summaries; AFRs before
FY2021 (manual, Cloudflare). Until then the prompt should not promise
them.

## Speed

Where the ~30–50 s of a Standard answer goes: not retrieval (0.7 s per
search). It is 3.5 model round-trips (mean), each re-sending ~16k prompt
tokens (cached) plus a growing history, and generating. Levers, in
order of effect:

1. **Fewer round-trips.** Structured tables (#1) and a section inventory
   (#2) turn the common 2.3-retrieve answer into a 1-retrieve answer.
   This is the only lever that halves the time.
2. **Smaller payloads.** 15 chunks ≈ 10–16k characters today; a
   row-rendered table is denser than tab soup. Drop `bbox` and
   `text_length` from the model payload (UI-only fields).
3. **Run a step's tool calls concurrently** — small, ~1 s per extra call.
4. Prompt trimming — the fiscal-note branch, the offset path and the
   figure-cite recipe are dead weight; caching makes this cheap in
   dollars but not in attention.
5. Model choice is already the fast one (deepseek-flash); GPT-5.6-luna
   scored higher with zero tool errors — worth a judged run.

Not recommended: dropping the acknowledgment (it costs no round-trip,
it is emitted in the same step as the first search, and it is what
makes a 40-second wait tolerable).

## What I would not do

- Re-tune retrieval constants. Recall@15 is 97.6%; the misses are
  downstream.
- Merge the two corpora yet. The fiscal-note ↔ budget cross-reference is
  a real gap but the v2 note in STATUS.md prices the prompt work
  correctly; do 1–4 first.
- Trust the 71–76% as a ceiling. The GPT run had zero tool errors and
  still misread columns — the model is not the limit, the table
  rendering is.
