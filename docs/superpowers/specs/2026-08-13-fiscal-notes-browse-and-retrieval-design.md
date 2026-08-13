# Fiscal Notes — browse, unified search, and retrieval results

**Date:** 2026-08-13
**Status:** designed, approved by Destin. **Revised 2026-08-13 after a
measurement pass** — see "What changed after approval" below. Not yet
implemented.
**Mockups (approved, and the reference for implementation):**
`mockups/fiscal-notes-browse.html`, `mockups/fiscal-notes-retrieval-results.html`
**Page:** `webapp/src/pages/FiscalNotes.tsx` (767 lines today)
**Model:** the Budget Documents page, `webapp/src/pages/Search.tsx`

Destin's ask, verbatim: *"create a mockup of the fiscal notes page that more
closely resembles the logic and visual appearance of the budget documents page.
I want to mirror the year selector approach, the unified search (title
filtering → semantic retrieval) approach, the browseable interface with prior
years collapsed."*

Everything below was decided against the two mockups, which were built first
and iterated live. **The mockups are the visual reference; this document is the
reasoning.** Where they disagree, the mockups are right about pixels and this
document is right about why.

---

## What changed after approval (2026-08-13)

The approved draft was checked against the live corpus and the shipped
retrieval code. Six things moved. Recorded here so the delta from what Destin
read is visible in one place rather than buried in the sections.

| # | change | why |
|---|---|---|
| 1 | **F10 rewritten.** "Ship at 20 passages and revisit later" was not a deferrable decision: 20 is a hard ceiling inside the search engine, and how many NOTES that yields is 9–17, measured | the draft named the wrong lever and left a measurable question open |
| 2 | **F9 reversed — the chamber filter now stands down in content mode**, exactly as sort already does | it was the most expensive control in the design and bought a two-way split of a ~13-row list |
| 3 | **F15 added — the page states what the search inferred from the words typed** | a question naming a year silently filters by session today, with the rail still reading "Any session" |
| 4 | **Fact 1 corrected, and F16 added.** Retrieval titles read `Fiscal Note - HB 2407: victim notification`, not `HB 2240 — …`, and 240 of them carry raw `<strike>` HTML | the draft's "a result can wear the same identity a browse row does" needed a parsing step that was never specified |
| 5 | **F8 capped.** Auto-expanding every matching session reaches the exact all-rows-mounted state F3 forbids, on one keystroke | the two sections contradicted each other |
| 6 | **Q1 resolved, Q2 resolved.** Both were small enough to decide | an approved spec should not ship with a text-box width unresolved |
| 7 | **F10 rewritten again (Destin, 2026-08-13). The result list is cut at 15**, and the header says either `Showing top 15 matches` or `Showing all N matches` | a fixed ceiling is a better promise to a reader than a count that swings 9–17 |
| 8 | **F15's server change re-scoped** from "one route" to four files and a protocol change | the provider seam returns rows only, with nowhere to put query-level facts — the draft undercounted the task |
| 9 | **F4 gains the content-mode join.** A result carries the year, never the session NAME | the label was specified for the result card with no data behind it; the failure would have been a silent blank line |
| 10 | **Acceptance 8 rewritten.** It said "renders as text, never markup" — but `BillTitle` renders a real `<s>`, on purpose | as written, the test invited someone to strip the strikethrough and destroy the "title was replaced" signal |
| 11 | **F14 gains the browse-row decision.** The same bill opens a PDF tab from a browse row and the in-app drawer from a result | a real inconsistency the draft never noticed; kept deliberately, with the reason and the upgrade path recorded |
| 12 | community college expenditure limits |
| 13 | child care subsidy waitlist |
| 14 | **F6 gains the return-to-titles rule**, ported from Budget Documents: editing the box always goes back to title mode | without it the page STAYED in content mode however the query changed — backspacing into a title match stranded the reader in a ranked view that no longer answered anything |
| 15 | **New: the page says when it is showing FIXTURE rows.** | the fallback provider ignores the query, so a fresh install returned the same few rows for every question — read on the running page as "stuck at the same 4 notes regardless of query", i.e. as a broken search |

---

## What is different about the two pages today

| | Budget Documents | Fiscal Notes |
|---|---|---|
| shape | Fiscal Year → report family → section documents | session → bills |
| how many groups shown | every in-scope year, newest open | **exactly one session** |
| the year control | multi-select dropdown, per-option counts | 28-row scrolling radio list |
| search | ONE box: title filter, auto-escalates to retrieval | title filter only |
| semantic search | same box | a **second**, separate box in the rail |
| sort | none (fixed title A→Z) | a 4-way menu **in every card header** |

Three of the four asks map cleanly. The one that does not is the middle level:
a Budget Documents year card expands into *report cards*; a Fiscal Notes
session card expands into 112–150 bills with nothing in between.

---

## Facts probed from the live corpus

None of this is assumed. Checked 2026-08-12 and re-checked 2026-08-13 against
`fiscal_note_chunks` (14,161 chunks / 2,104 notes) and real
`LanceSearchProvider.search(..., corpus="fiscal_notes")` calls.

1. **🔴 `doc_title` reads `"Fiscal Note - HB 2407: victim notification"`** —
   an ingest-built title, uniformly prefixed `Fiscal Note - ` (2,104 of 2,104)
   with a **colon** between number and title. **It is NOT the browse row's
   `bill.title`**, which is the scraped directory string and carries no prefix.
   The two identities are close but not the same string, and the result card
   has to build its own. See F16.
2. **🔴 240 of the 2,104 titles contain raw HTML** — e.g.
   `Fiscal Note - HB 2172: <strike>technology transfer; technical
   correction</strike> (NOW: solar device; tax credit)`. The result card must
   run the page's existing `BillTitle`/`stripTags` treatment or it prints the
   tags on screen. See F16.
3. **`fiscal_year` on a fiscal-note chunk IS the session year** (1999–2026).
   So the Session filter reaches content mode through `filters.fiscal_year`,
   the way `toSearchFilters` already does for Budget Documents.
4. **`doc_type` is uniformly `"fiscal-note"`** across all 14,161 chunks. There
   is no Document Type dimension to mirror — one dropdown is correct, not a
   shortcut.
5. **There is NO chamber column.** Chamber is only derivable from the doc_id
   slug (`…-hb2240-66`, `…-scr1001-0`). This has a design consequence, F9.
6. **All 28 sessions in the directory are Regular sessions**, all in the form
   `57th Legislature, 2nd Reg. Session (2026)`. Relevant to F4.
7. Fiscal-note chunks carry `page`, so the source drawer works on this corpus
   exactly as it does on budget documents.
8. **The retrieval pool is capped at 20 passages, corpus-wide and
   permanently** — `FUSED_TOP_K = 20` in `retrieval/pipeline.py`. Asking
   `/api/search` for 40 returns 20. See F10.
9. **The directory holds 2,126 bills; the corpus holds 2,104 notes.** ~22 bills
   have a directory row and no ingested note, so a session can legitimately
   show rows in title mode and nothing in content mode. Not a defect to chase.
10. **Some fiscal-note chunks ARE agency-stamped** (`agency:gov:local-government`
    appears in real results), so a question naming an agency does re-rank this
    corpus. Harmless — agency is a ranking preference, never a filter.
11. **The recency boost does NOT apply to this corpus.** `retrieval/recency.py`
    is budget-only by design, precisely so note triage reaches the whole back
    catalogue. Recorded because every implementer will otherwise worry that a
    1999 note cannot compete with a 2026 one. It can.

**Reproduce facts 1, 2, 8 and 10** with one call:
`LanceSearchProvider().search("TPT exemption on food", top_k=40,
corpus="fiscal_notes", filters={})` — 20 rows come back, their `doc_title`s
carry the prefix, and `len({r["doc_id"] for r in rows})` is the note count.

---

## Part 1 — Browse

### F1. The session control becomes a FILTER, not a selector

The 28-row `.yscroll` radio list is replaced by a **"Legislative Session"
multi-select dropdown** ("Any session", per-option counts) — the twin of
Budget Documents' Fiscal Year control. `.fnmain` then stacks **one collapsible
`.yg` card per in-scope session**, newest expanded, priors collapsed, toggle
state surviving filter round-trips.

This is the whole ask: the page stops being "look at one session" and becomes
"browse the corpus by year".

### F2. Chamber stays a segmented control — in browse and title mode

Not converted to a dropdown. Three options read at a glance; a dropdown hides
which lens is active behind a click. Budget Documents has no segmented control
only because it has no three-value dimension, not because the idiom was
rejected. The rail becomes: search pill → segmented Chamber → session dropdown
→ sort dropdown.

**It stands down in content mode.** F9 is where that is argued.

**The chamber rule is derived in exactly ONE place and shared by both modes.**
Browse reads the directory's `chamber` field; content mode must derive it from
the doc_id slug (fact 5). Two derivations of one fact drift, and the symptom is
the same bill filing under House while browsing and Senate in results. The rule
is: **take the letters before the digits; anything beginning `H` is House,
everything else is Senate.** Verified against the whole directory — the only
prefixes that occur are `HB`, `HCR`, `HJR` (all recorded `H`) and `SB`, `SCR`
(all recorded `S`), so the slug rule reproduces the directory's own field
exactly. Pin that with a test over the real snapshot, not over a hand-written
list of prefixes.

### F3. A session card holds a FLAT bill list

No middle level. Two alternatives were considered and rejected:

- **chamber groups inside the card** (mirroring the tray's Summary-sections /
  Agency-pages split) — bill numbers already sort into chamber-ish runs, so the
  groups would restate the ordering;
- **instrument-type cards** (House Bills / Senate Bills / Concurrent
  Resolutions) — a true structural mirror, but it invents a hierarchy the data
  does not have.

The card body stays today's merged `.fnlist` of `.fbill` rows, untouched.

**Implementation note.** Budget Documents mounts every year body once and hides
it with the `hidden` attribute, specifically to preserve open trays and
head-button focus across a collapse. **Do not copy that here.** A session card
has no trays, and the head button survives either way, so there is no state
that mounting would protect — while mounting all 28 bodies puts ~2,126 rows in
the DOM at once. Mount the body conditionally.

*Do not cite `FiscalNotes.tsx`'s "~113 ms → ~55 ms" comment in support of this.*
That number measures what `memo()` was worth on an earlier draft which happened
to keep all 2,126 rows mounted; it is not a measurement of mounting-vs-not, and
the comment says in terms not to quote it for the current layout. The argument
here is structural, not measured. If mounting ever looks tempting, measure it.

**This constraint is what caps F8.** Conditional mounting is worth nothing if
a search then opens every card at once — see F8's expansion cap.

### F4. The session label puts the year FIRST

    2026 (57th Legislature, 2nd Regular Session)

The directory ships `57th Legislature, 2nd Reg. Session (2026)`, which buries
the year at the end of a string the reader scans *by year*.

The abbreviation is expanded through a **map**, not a blind
`.replace("Reg.", "Regular")`, and the trailing `(YYYY)` is stripped only when
it is exactly that session's own year. Every live session is Regular today
(fact 6), but Arizona holds special sessions, and an unrecognised form must
pass through intact rather than come back half-rewritten.

Used on: session card heads and their aria-labels, the result card's session
line, and the source drawer breadcrumb.

**🔴 In content mode the label has to be JOINED, and the draft never said so.**
A search result carries `fiscal_year` — the bare number, 2026 — and nothing
else about the session. The name string (`57th Legislature, 2nd Reg. Session`)
exists only in the browse directory (`GET /api/fiscal-notes`), never on a
chunk. Verified against the provider's row builder: `chunk_id`, `doc_id`,
`doc_title`, `snippet`, `text`, `page`, `score`, `doc_type`, `fiscal_year`,
`publisher`, `agencies`, `doc_url`, `doc_meta`, `section_of` — no session name.

This is cheap, and only cheap because of where it lands: **the page has already
fetched the directory** for browse, so the join is a `Map<year, Session>` built
once from data in hand. No request, no new endpoint. The 28 sessions cover
1999–2026 one-per-year, so the map is total and every result finds its label.

Say it explicitly in the task, because the failure is quiet: miss the join and
the card renders a bare `2026`, or an empty line, and nothing errors.

### F5. Sort moves to the rail, and sorts WITHIN each session

The 4-way sort menu leaves the card headers — where it forced the header to be
both a collapse toggle and a menu — and becomes one rail control governing
every card. **Sessions themselves stay newest-first; the sort reorders bills
inside each card and never flattens them into one list** (Destin, explicitly).

It is **disabled in content mode**, with the reason stated in the rail:
relevance order is the answer there, and silently reordering a ranked list
would be a lie about what the ranking means.

---

## Part 2 — Search

### F6. One box, two modes, automatic escalation

`SemanticRailSearch` — the rail's second box, "Search note text" — is
**deleted**. The one box filters bill numbers and titles; with zero title hits
it escalates after ~2 s of quiet to real retrieval over `fiscal_note_chunks`;
an `.allbar` pill crosses back either way.

Mechanism is Budget Documents' `ESCALATE_MS` / `suppressedQuery` recipe
verbatim, **including keying the suppression on the query string** rather than
a boolean — a reader who clicks back to titles is by construction the
population that stays at zero title hits, so a boolean would let the page yank
them forward again on the next render.

The title filter itself is unchanged: today's `matchesQuery`, including the
rule that a digits-only query prefix-matches bill numbers only and never
searches titles.

**🔴 EDITING THE BOX ALWAYS RETURNS TO TITLE MODE, and the draft never said so.**
Escalation is one-way in the draft: titles → contents, with no route back
except the toggle or the clear button. Built that way and it is wrong in an
obvious way the moment you use it — **backspacing a question down to something
that matches a bill title leaves you stranded in a ranked list that no longer
answers anything**, and emptying the box leaves you there too. A new query is a
new search, and titles are the cheap default, so every edit returns to titles
and re-arms escalation; two seconds of quiet takes you forward again if the new
query still has no title hits.

This is Budget Documents' rule verbatim, and it is load-bearing there for a
second reason worth keeping: staying in content mode would fire a retrieval
request on **every keystroke**.

The MANUAL toggle is exempt, and must be: it is a fresh decision about the
query as it stands, so it survives until the query is edited again. A single
topical word like `water` matches 11 titles and so never auto-escalates — the
toggle is the only route to the note text there, and undoing it on the next
render would make it useless.

**The waiting state is part of the recipe, and the draft omitted it.** A
content search is not instant — the pipeline's own comments budget ~3 s and
measure 2.7 s mean / 3.1 s max — and F6 adds a 2 s quiet period before the
request is even sent. That is up to ~5 s between the last keystroke and any
result, so *what fills it* is a design decision, not an implementation detail.

Port Search.tsx's answer verbatim, including its reason: **the moment
escalation is ARMED, the page commits to searching contents and says so**, and
keeps saying so straight through the request. The armed pause and the in-flight
request render identically, so the handoff between them is invisible. Without
this, the page sits on "No note titles match" for the full two seconds and
*then* swaps to a spinner — which reads as a failure that changed its mind
(Destin, 2026-08-11, on the Budget Documents page).

Failure gets the standard treatment, not a hand-rolled message: a failed
`/api/search` surfaces the real detail the backend sent (`api.ts`'s `fail()`
already extracts FastAPI's `detail`), never a guessed cause.

**🔴 The box does NOT change. Q1 reversed (Destin, 2026-08-13, after seeing it
built.)** The approved draft grew it to two or three lines as you type. Built,
looked at, undone: **both pages keep the existing one-line Budget Documents
box**, identical markup and identical styling.

The draft's reasoning was not wrong about the problem — about seventeen visible
characters is genuinely tight for a whole question — but it was wrong about the
remedy's scope. Growing this box alone makes the two sibling pages *look*
different, which is the divergence this whole exercise exists to remove; the
draft saw that and answered it by promising the same fix to Budget Documents in
the same pass, which is a second page's redesign smuggled into this one's
plan. If the box is ever too small, that is **one deliberate change to both
pages**, decided on its own merits — not a local improvement to this one.

### F7. "Search all legislative sessions" is retired

Its whole job was widening scope past the one selected session. With sessions
as a filter (F1), search always spans everything in scope. Its slot in
`.allbar` is reused by the titles/contents toggle.

### F8. Title search keeps session cards; content search collapses to one card

Split by mode, deliberately:

- **Title mode** keeps the session cards. It is a filter over rows the reader
  was already browsing, nothing has been reordered, so grouping costs nothing.
  Sessions with no match drop out; surviving cards **expand**, because a
  collapsed card would hide the matches just asked for.
- **Content mode** collapses to one ranked "Results" card. The rank IS the
  answer, and re-bucketing a relevance-ordered list by session would bury the
  best passage under weaker ones from a newer session.

That the two modes look different is a feature: they answer different
questions, and the toggle between them is easier to understand when the shapes
differ.

#### 🔴 The expansion cap — measured, and it contradicts the draft

"Surviving cards expand" reaches **exactly the all-rows-mounted state F3
forbids**, and it does so on one keystroke. Measured against the real 2,126-row
snapshot:

| typed | matching rows | sessions expanded |
|---|---|---|
| `water` | 11 | 10 |
| `fund` | 90 | 25 |
| `school` | 177 | 28 |
| `tax` | 513 | **28** |
| `a` | **2,029** | **28** |

Short prefixes are not an edge case — they are the state every longer query
passes through, on every keystroke.

**So: auto-expand only the NEWEST THREE matching sessions.** Older matching
cards render collapsed with their match count in the header, which is a true
statement and one click from the rows. Three because it holds the shape the
reader asked for (the matches are visible, newest first) while capping the
mounted rows at roughly one session-and-a-half's worth in the worst case.

**Do not "fix" this with virtualised scrolling.** That trades a one-line rule
for a scroll-position and measurement problem on a page that has neither today.

### F9. Chamber and sort BOTH stand down in content mode

There is no chamber column (fact 5). Retrieval returns ranked passages and a
chamber lens could only remove some of them **after** ranking, with no way to
fetch more — so a House-only search would come back short by an amount nobody
can predict, and the page would have to apologise for it in a sentence.

**It is not worth it.** The chamber split of a ~13-note result list is a
two-way cut of a short list, on cards that already show `HB` or `SB` in bold as
the first thing the eye lands on. The reader can see the chamber without a
control removing evidence to prove it.

So the chamber segments grey out in content mode with the reason stated in the
rail, **exactly as sort already does (F5), for the same reason and in the same
words**: *"Ranked results are ordered by relevance — chamber and sort apply to
browsing."* One sentence covers both controls.

**The rejected alternatives, and why each loses:**

- **Filter the results anyway and state the shortfall** (what the approved
  draft said). Honest, and it still throws away ranked evidence with no
  backfill. It also spends the page's most valuable line — the status line — on
  an apology for a control nobody needed.
- **Raise the pool when a chamber is set.** Impossible: the pool is capped at
  20 (fact 8), so there is nothing to raise. This alternative was only ever
  viable in the draft because the draft believed `top_k` was the lever.

**What this deletes from the design:** the shortfall sentence, the
after-ranking filter path, one acceptance test, and the need to explain why two
rail controls behave differently. Content mode becomes *a ranked list of notes,
plus one honest line about what was filtered* — and that line is F15's.

### F10. 🔴 20 passages is a CEILING, not a setting — and it costs notes

Retrieval ranks and truncates at **20 passages**, and F11 shows one passage per
note. So the number of NOTES a search surfaces depends on how concentrated the
ranking is, and it varies more than the draft assumed. Measured, eight
realistic questions, `top_k=20`:

| notes shown | question |
|---|---|
| 17 | TPT exemption on food |
| 16 | prison bed capacity costs |
| 9 | teacher pay raise |
| 9 | veterans tuition waiver |

**Mean 12.8 notes, range 9–17.** A reader cannot tell a thin topic from one
where a single wordy note took five of the twenty slots.

**🔴 The draft's "the lever is `top_k`" is wrong.** `top_k` is capped by
`FUSED_TOP_K = 20` inside `retrieval/pipeline.py` — asking `/api/search` for 40
returns 20 rows (fact 8, verified). The real lever is that constant, and moving
it is a change under `retrieval/`, which **does** trigger the CLAUDE.md eval
rule that "What is NOT changing" waives for everything else here. It is
therefore **out of scope for this work**, not a knob to reach for mid-build.

#### What ships: a hard cut at 15, and a header that says which case you got

**Decided by Destin, 2026-08-13.** The browser collapses the ranked passages
into notes and shows **at most 15**. Nothing under `retrieval/` changes; this
is a slice, applied after the response arrives. Two header strings, and the
page picks between them by comparing the note count to 15:

| case | header |
|---|---|
| more notes came back than fit | `Showing top 15 matches` |
| every note that came back is on screen | `Showing all 9 matches` |

Both are true statements about **what this search surfaced**. Neither is a
claim about the corpus, and no count on this page may imply one.

**Which string you see, measured.** Against the eight questions above, six land
under 15 (9, 9, 12, 13, 13, 13) and two are cut (16, 17) — so **"all N" is the
common case, roughly three in four searches**, and "top 15" is the exception.
That is the opposite of what "top 15" being the headline number suggests, and
it is worth knowing before reading the copy back.

**The one honesty cost, accepted with eyes open.** "All" here means *all that
the twenty-passage ceiling surfaced*, not all the corpus holds. A reader who
types `tax`, sees `Showing all 12 matches`, and concludes the corpus holds
twelve tax notes has been misled — it holds hundreds. The design accepts this
because the alternative wordings are worse in other ways and the fix is one
word if it ever bites: **`Showing 12 matches`** drops the claim entirely and
changes nothing else. Treat that as the pre-approved remedy, not a redesign.

**Counting unit.** One card is one note is one match, so "matches" and "notes"
name the same quantity here and the shorter word ships. What must never be
counted on screen is **passages** — a number nothing visible corresponds to.

**Why not raise the ceiling instead.** Two routes exist and both were rejected
for this pass:
- **Raise `FUSED_TOP_K`.** The reranker costs ~130–250 ms per candidate, so 20
  measures 2.7 s mean / 3.1 s max and 50 measured 4.9 s — already over the
  ~3 s interactive budget the constant's own comment cites. Thirty candidates
  would land near 4.5 s and would only shift the band (roughly 14–26 notes),
  not fix it.
- **Collapse to one passage per note BEFORE the rerank**, so all twenty scored
  candidates are distinct notes. Same runtime, and 15 would then be reached on
  essentially every search. Genuinely the better engine-side answer, and out of
  scope here for three reasons: it is a change under `retrieval/` (eval run
  attached), it must be scoped per corpus or it breaks Budget Documents, which
  deliberately shows several passages from one report, and it would make
  "all N" nearly unreachable — a fixed 15 whose last few entries are whatever
  filled the slots, since **the pipeline applies no relevance floor** (verified:
  `retrieve()` returns the best it found however weak; the refusal threshold
  lives at the MCP-tool boundary, not here).

If a real search is ever observed to miss a note that should obviously be
there, that is a retrieval change with an eval run attached — a separate piece
of work, with the numbers above as its starting baseline.

---

## Part 3 — The retrieval result card

### F11. ONE passage per note — the best one, and nothing else

No tray, no "N more passages". A result answers *"which note should I read?"*,
and the top-ranked passage is the evidence for that answer; the rest belong to
the note, which is one click away. The cost of that choice is F10's, and it is
measured there rather than guessed at here.

### F12. The card layout

    SB 1035 — state department of corrections; appropriation      [Open note]
    2026 (57th Legislature, 2nd Regular Session)
     ┌─ ESTIMATED IMPACT ────────────────────────────────────────────┐
     │ The bill would appropriate $28,700,000 from the General Fund… │
     └───────────────────────────────────────────────────────────────┘

- **Bill number and title are one line**, number in heavier type. No navy chip.
  The two halves are produced by F16, not by the raw `doc_title`.
- **The title wraps; it does not truncate.** A fiscal-note title is the only
  plain-English description of what a bill does, and the retitled
  `…(NOW: …)` forms — 240 of them, and they survive into retrieval titles
  (fact 2) — are long enough that an ellipsis would hide the half that matters.
- **The session sits small and tight beneath it.**
- **"Open note" is on the top row**, right-aligned.
- **No page reference on the card.** The page still names itself in the
  drawer's breadcrumb, which is where the reader is actually looking at it.
- **The section name is a tiny faint legend breaking the top edge of a hairline
  box that traces the whole excerpt**, so the quote reads as lifted OUT of the
  note rather than as more card text. Its text left-aligns with the bill number
  and the session. *(The label's inset and the box's corner radius are pixel
  decisions and belong to the mockup, which is authoritative on them.)*
- **Excerpt type is smaller and padding is tighter throughout.** The cards were
  too tall to compare at a glance, which is the one thing a result list has to
  support. Measured on the mockup: roughly a third shorter, about five results
  per screen where there were three and a half.

### F13. The whole card is ONE button

With the dashed context block gone, no second interactive element remains, so
the card can be a single control the way a `.fbill` row is a single link. Its
"Open note" pill is therefore a **decorative span**, exactly as `.fbill-dl`'s
"PDF" label is — it names the action, it does not take the click. The label
reads **"Close note"** while that card's drawer is open, because the card is a
toggle rather than a one-way action.

### F14. "Open note" opens the SOURCE DRAWER, not the PDF

In-app, at the cited passage, reusing `SourcePanel` / `SourceView` and the
existing `.pdf-drawer`. The drawer carries its own "Open the source PDF" link
out to azleg.gov.

It does **not** jump straight to the PDF. The page pill it replaced was the
drawer's trigger, and handing that click to a new tab would delete the only
surface that shows the cited span in place — which is most of what makes a
result checkable, and the reason Invariant 1 exists.

**`SourcePanel` takes a `corpus` prop that DEFAULTS TO `"budget"`.** Pass
`"fiscal_notes"` explicitly. Miss it and every drawer on this page 404s against
the wrong table — with an honest error message, but a uniformly broken feature.
`/api/chunks/{id}` already accepts the parameter; nothing server-side needs
building.

#### 🔴 The same bill opens two different ways on this page. That is deliberate.

**New — the draft never noticed it.** A `.fbill` browse row is an
`<a target="_blank">` straight to azleg.gov's PDF, and it stays that way ("What
is NOT changing"). A result card opens the in-app drawer. So the same bill,
clicked in two places on one page, does two different things — and both are
visible side by side in the approved mockup.

Kept, for one structural reason and one product reason:

- **Structural.** The drawer opens a PASSAGE. Its whole input is a `chunk_id`,
  and a browse row does not have one — it has a bill number and a URL. Opening
  a note "at the top" would need a doc-to-first-chunk lookup that does not
  exist: `/api/chunks/{chunk_id}` is chunk-keyed, and `/api/pdf/{doc_id}` serves
  bytes, not a citable span (verified in `app/routes/pdf.py`). It is a new
  endpoint, not a prop.
- **Product.** The two clicks answer different questions. Browsing, the reader
  has already chosen the bill and wants the document — the PDF *is* the answer.
  Searching, the reader is triaging, and the drawer's job is to show the cited
  span **in place** so the result can be checked without leaving. F14's whole
  argument is about evidence; a browse row is not evidence, it is a directory
  entry.

**What this costs, stated plainly:** a reader who learns "clicking a bill opens
a PDF tab" while browsing gets something else when they click a search result.
That is a real inconsistency, not an imagined one, and it is the kind of thing
that erodes confidence in a page.

**The upgrade path, if it ever bites:** add a doc-to-first-chunk lookup and
point browse rows at the drawer too, keeping "Open the source PDF" inside it.
One new endpoint and one changed row. Cheap later, and out of scope now.

### F15. 🔴 The page states what the search inferred from the words typed

**New. This is the honesty gap the draft had.**

The retrieval pipeline reads the analyst's words and infers filters from them
before searching. On this corpus that has one live consequence and it is
silent: **a question naming a year hard-filters by session.** Verified —
*"FY 2027 revenue impact of a sales tax exemption"* comes back with
`inferred_fiscal_years = [2027]` applied (widened one year either side), while
the rail still reads **"Any session"**. The page says one thing; the search did
another.

It is worse than the document-type guess, which has a safety net: when a
doc-type guess empties the page the pipeline drops it and reports
`dropped_filters`. **The year guess is never dropped.** A wrong or merely
narrow year guess simply returns less, confidently, forever.

**So the results header states it, in the reader's words, with an undo:**

> Showing all 13 matches for "FY 2027 revenue impact of a sales tax
> exemption".
> **Also limited to the 2026–2028 sessions**, because your question named a
> year. *Search every session.*

*(The `for "…"` tail is this section's requirement, not F10's — the undo
sentence is meaningless without the question it is undoing. F10's two strings
are otherwise verbatim.)*

`retrieve()` already computes `inferred_fiscal_years`, `inferred_doc_types` and
`dropped_filters` (`retrieval/pipeline.py`). **Nothing carries them to the
browser**, and the reason is one layer further down than the route:

| layer | today | what it needs |
|---|---|---|
| `retrieve()` | returns all three on `RetrievalResult` | nothing |
| `SearchProvider.search()` | returns `list[dict]` — **rows only, no slot for query-level facts** | a return shape that carries them |
| `LanceSearchProvider` / `StubSearchProvider` | both build that flat list | both updated, both their tests |
| `POST /api/search` | returns `{results, total, provider}` | three additive keys |

So it is **four files and a protocol change, not one route** — the draft called
it "the one server-side change" and undercounted it. Still genuinely additive
at the HTTP boundary: no field is renamed or removed, every existing caller
keeps working, and the frozen contract stays frozen in the sense that matters.
But size the task for the seam, not the endpoint.

**Both providers must change together**, not just the real one. `StubSearchProvider`
is what the filter UI is tested against; leaving it behind would make F15
untestable in exactly the suite that would otherwise catch a regression.

Budget Documents can then adopt the same line for free; it has the identical
blind spot today.

**"Search every session" must actually work**, which means sending an explicit
session filter wide enough to suppress the inference (the pipeline only infers
when the caller passed no `fiscal_year` of its own) — not stripping the year
from the analyst's question, which would change what they asked.

### F16. 🔴 The card builds its own title, safely

**New. The draft assumed the retrieval title was already card-shaped. It is
not** (facts 1 and 2).

Every fiscal-note `doc_title` arrives as
`Fiscal Note - <NUMBER>: <title>` and 240 of them carry raw `<strike>` HTML.
Three things follow, and all three are visible defects if skipped:

1. **Strip the `Fiscal Note - ` prefix.** Every card on a page titled "Fiscal
   Notes" would otherwise open with the words "Fiscal Note".
2. **Split on the FIRST colon** into number and title, so F12's two weights
   render. Titles contain further colons and semicolons; only the first split
   is the number boundary. A title that does not match the shape renders whole,
   unsplit, rather than being cut in a wrong place.
3. **Render through the page's existing `BillTitle` / `stripTags`.** They
   already handle the `<strike>…</strike> (NOW: …)` form safely. Rendering the
   raw string prints the tags on screen; rendering it as HTML would inject
   scraped web content into the page, which the existing code carries an
   explicit warning against. **Do not reach for `dangerouslySetInnerHTML`
   here** — that is the trap this function exists to close.

Pin all three against the real snapshot, including one of the 240 struck
titles: this is a data-shape dependency, and a hand-written fixture would not
have caught it in the first place.

---

## What is NOT changing

- `matchesQuery`, `sortBills`, `.fbill` row markup — carried over unchanged.
  `BillTitle`/`stripTags` are carried over unchanged **and newly reused by the
  result card** (F16).
- The subhero, beyond a second chip naming the new search behaviour.
- Anything under `retrieval/`, `ingest/`, `chunking/`, `citation/`, or
  `harness/system-prompt.md`. **This is a webapp + `app/` change**, so the
  CLAUDE.md eval rule does not apply and no eval run is required. Say so in the
  commit rather than leaving a reader to wonder.
  **The one thing that would break this is raising `FUSED_TOP_K` (F10) — which
  is exactly why it is out of scope here.**
- The `POST /api/search` response gains three additive fields (F15) and renames
  nothing. The contract stays frozen in the sense that matters.
- **AI Mode is not coming back to this page.** Plan 4's deviation note stands:
  the corpus picker in `/ai` is what preserves the coordinator's workflow.

---

## Open questions — deliberately not decided

**Both of the draft's open questions are now closed:** Q1 (search box width) is
resolved in F6 — and resolved as NO CHANGE: the box stays exactly as Budget
Documents' is.
Q2 (the same sentence printing twice, in `.fnstatus` and again in `.yg-meta`)
is resolved by shortening the inner one to the bare count.

**Q3 is now closed too** (Destin, 2026-08-13): the 9-to-17 band is resolved by
cutting the list at 15 and naming which case the reader got. See F10.

Nothing remains open. The one item to watch — not a question, a trigger — is
F10's: if a search is ever observed to miss a note that should obviously be
there, that starts a retrieval change with an eval run, and nothing short of an
observed miss does.

---

## Acceptance

Gate on **error rates, never production rates** (the standing rule, and the one
that has caught the most in this repo).

1. **Every session in scope renders a card**; newest expanded, priors
   collapsed; toggle state survives a filter change and a search round-trip.
2. **A session with zero matches disappears under a query, and its count always
   equals the rows it renders** — true by construction, since non-matching rows
   are removed. Pin both halves.
3. **A broad title query does NOT expand every card.** Type `a` against the
   real snapshot and assert at most three session bodies are mounted while all
   28 headers render with their counts. This is the F3/F8 contradiction and it
   is the one performance regression this design can actually cause.
4. **Escalation fires only at zero title hits**, only after the quiet period,
   and **never re-fires after the reader crosses back** for that same query.
   Pin the re-fire case specifically; it is the one that was a live defect on
   Budget Documents.
5. **Neither empty state is a dead end** — the mode toggle renders on both.
6. **Chamber and sort are both disabled in content mode, and say why once.**
   Assert the shared sentence renders, and that neither control can reorder or
   remove a ranked result.
7. **A year-naming question states the session narrowing and can undo it.**
   Assert the sentence, the years it names, and that "Search every session"
   produces a request whose session filter suppresses the inference.
8. **A result card renders a struck title through `BillTitle`, never as raw
   HTML.** Drive one of the 240 real struck titles through the card and assert
   three things: the literal text `<strike>` appears nowhere in the DOM, the
   struck words DO render inside a real `<s>` element, and the replacement
   `(NOW: …)` half renders unstruck beside it.
   **Do not assert "renders as plain text."** `BillTitle` deliberately emits a
   React `<s>` element, and the strikethrough is load-bearing meaning — it is
   the only thing on screen saying *this bill's title was replaced*. A test
   phrased as "no markup" invites someone to satisfy it by stripping the
   strikethrough, which passes the test and destroys the information. What must
   never happen is the raw scraped string reaching the DOM as characters, or
   reaching it through `dangerouslySetInnerHTML`.
9. **The result card has exactly one passage and exactly one interactive
   element.** A test asserting zero nested buttons/anchors is cheap and pins
   F13 directly.
10. **The drawer opens at the clicked passage, against the fiscal-note corpus,
    and its breadcrumb names the page.** Assert the corpus argument explicitly
    (F14) — the default is `"budget"` and a miss is invisible in jsdom.
11. **The result list is cut at 15, and the header names which case it is.**
    Assert `Showing top 15 matches` when more notes came back than fit and
    `Showing all N matches` when they all fit, with N equal to the cards
    rendered. Pin the boundary both ways — exactly 15 notes is the "all" case,
    16 is the "top" case — since that is the only place the two strings can be
    swapped without any other symptom.
12. **Counts name notes, never passages**, and no count on the page implies a
    corpus-wide total.
13. Suites green: pytest, vitest, `tsc -b`. No eval run (see "What is NOT
    changing").

### A note on what the suites cannot see

Two defects in this design's own mockups were invisible to behavioural testing
and were found only by **looking at a rendered picture of the page**: a card
28 px too wide for its container, silently clipped; and a highlight that split
"inmates" into a marked "inmate" plus an orphaned "s". jsdom performs no layout
and paints nothing, so neither could ever have failed a test.

A third class was invisible to the mockups too, and was found only by
**querying the live corpus**: every correction in "What changed after approval"
came from probing real data and real code, not from reading the design again.
Both habits are required.

**Whoever implements this must open the page**, not merely run the suites —
the same conclusion the Budget Documents work reached after 17 defects survived
2,999 passing tests.

---

## Appendix — the two highlights

### F17. Two highlights, separated by FORM

*(Was F14 in the approved draft; renumbered when F14 became the drawer
decision. Unchanged in substance.)*

The palette is monochrome navy; there is no warm colour in it. So the two marks
cannot be told apart by hue and must differ in kind:

| mark | means | treatment |
|---|---|---|
| results / titles | **words the analyst typed** | flat pale wash, no rule |
| source drawer | **the passage the system cited** | deeper navy band **+ solid underline** |

The drawer highlight was yellow in the first mockup and is not any more: yellow
is off-palette, and worse, it read as the same *kind* of mark as a search term.

The term wash is deliberately faint. Word matching uses a boundary at **both**
ends, matching the shipped `highlightTerms()` — anchoring only the front
highlights "inmate" inside "inmates" and leaves the "s" outside the mark, which
renders as a highlighted word with a loose letter drifting after it.
