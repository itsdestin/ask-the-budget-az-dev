# Fiscal Notes — Browse, Unified Search, Retrieval Results: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship spec F1–F17 (`docs/superpowers/specs/2026-08-13-fiscal-notes-browse-and-retrieval-design.md`): rebuild `webapp/src/pages/FiscalNotes.tsx` so the Legislative Session control becomes a filter over collapsible session cards, the rail's two search boxes become one that escalates from title filtering to real retrieval, and content results render as ranked note cards that open the in-app source drawer.

**Architecture:** Four seams, in dependency order.
1. **Server (Python)** — `SearchProvider.search()` returns rows only, with nowhere to carry query-level facts. It gains a result shape that also carries `inferred_fiscal_years` / `inferred_doc_types` / `dropped_filters`, both implementations follow, and `POST /api/search` adds three additive response keys (spec F15). This is the only Python work and the only thing blocking the front end.
2. **Pure helpers (TS, no React)** — a new `webapp/src/search/fiscalNotes.ts` holding everything testable without mounting: the session label, the retrieval-title parser, the note grouping + 15-cut, and the header strings (F4, F10, F16).
3. **The page** — `FiscalNotes.tsx` rebuilt around session cards, the unified box, and the two modes (F1–F9).
4. **The result card + drawer** — `FiscalNoteResult`, wired to `SourcePanel` with an explicit corpus (F11–F14).

**Tech Stack:** Python 3.12 / FastAPI / pytest on the server; React 18 + TypeScript + Vitest + Testing Library on the front end. No new dependencies on either side.

## Global Constraints

- **Read the spec first.** Every task cites F-numbers; the spec is the authority on *why*, the mockups on *pixels*.
- **The mockups are the visual reference, with one exception recorded in the file itself:** `mockups/fiscal-notes-retrieval-results.html` is authoritative for the result card and the rail. `mockups/fiscal-notes-browse.html` is authoritative for browse and title mode, and its `passageCard()` carries a comment saying it is NOT the reference for the card. Build the card from the results mockup.
- **Plan code blocks are sketches to RUN AND CORRECT, not text to transcribe** (this repo's recorded lesson: plan prose holds up; plan example code has divided by zero, called APIs that don't exist, and asserted the unsatisfiable). TDD every step; the test output is the authority.
- **Every non-trivial edit carries a WHY comment.** Destin is a non-developer and reads comments to understand what changed; record the evidence, not just the choice.
- **Nothing under `retrieval/`, `ingest/`, `chunking/`, `citation/`, or `harness/system-prompt.md` may change.** This is a webapp + `app/` change, so the CLAUDE.md eval rule does not apply and **no eval run is required** — say so in the commit rather than leaving a reader to wonder. The one thing that would break this is raising `FUSED_TOP_K`, which is why the 15-note cut is applied in the browser (spec F10).
- **Tests may not open a real LanceDB directory or load ONNX weights** (repo testing convention). Server tests use the existing fixtures; front-end tests use the real snapshot fixture, never a hand-written bill list — the `<strike>` class of defect is invisible to invented data (spec F16).
- Work in a worktree at `~/ask-the-budget-az-worktrees/fiscal-notes-browse/` branched off current master. Sync master immediately before merging.
- Run the FULL suites at the end of every task, not just the task's file: `uv run pytest -q` and `npm test --prefix webapp`. Record the baseline counts in Task 1 and expect them to grow only.
- **Whoever implements this must OPEN THE PAGE, not merely run the suites.** Two defects in this design's own mockups were invisible to behavioural testing and were found only by looking at a rendered picture: a card 28 px too wide for its container, silently clipped, and a highlight that split "inmates" into a marked "inmate" plus an orphaned "s". jsdom performs no layout and paints nothing. The Budget Documents work reached this same conclusion after 17 defects survived 2,999 passing tests.

---

### Task 1: Baseline, worktree, and the fixture the front end will test against

Nothing ships in this task. It establishes the two numbers every later task is measured against, and pins the real-snapshot fixture that Tasks 5–10 depend on — because the interesting defects in this design (the 240 struck titles, the 2,029-row `a` query) only exist in real data.

**Files:**
- Create: `~/ask-the-budget-az-worktrees/fiscal-notes-browse/` (worktree)
- Read only: `webapp/src/pages/FiscalNotes.test.tsx` (how it loads its fixture today)

- [ ] **Step 1: Worktree and baseline**

```bash
git -C <main-repo> worktree add ~/ask-the-budget-az-worktrees/fiscal-notes-browse -b feat/fiscal-notes-browse
ln -s <main-repo>/.venv ~/ask-the-budget-az-worktrees/fiscal-notes-browse/.venv
cd ~/ask-the-budget-az-worktrees/fiscal-notes-browse
uv run pytest -q                       # record: N passed / M skipped
npm ci --prefix webapp && npm test --prefix webapp -- --run   # record: N passed
```

- [ ] **Step 2: Confirm the fixture is the real snapshot, not a hand-written list**

Check what `FiscalNotes.test.tsx` currently feeds the page. The spec's F16 and F8 acceptance both require driving *real* data:
- at least one of the 240 titles containing `<strike>`,
- enough rows that a one-letter query matches thousands.

If the existing fixture is a handful of invented bills, this task's real output is a snapshot fixture. Record which it is before writing any test that claims to cover the struck-title case.

- [ ] **Step 3: Verify the two facts the whole design rests on**

```bash
uv run python -c "
from app.search_provider import LanceSearchProvider
rows = LanceSearchProvider().search('TPT exemption on food', top_k=40, corpus='fiscal_notes', filters={})
print('rows returned:', len(rows))                       # expect 20, NOT 40 (spec fact 8)
print('distinct notes:', len({r[\"doc_id\"] for r in rows}))
print('sample title:', rows[0]['doc_title'])             # expect 'Fiscal Note - HB ...: ...'
"
```

If `rows returned` is not 20, **stop and re-read spec F10** — the 15-cut's whole justification is that 20 is a ceiling.

---

### Task 2: `SearchProvider` carries query-level facts, not just rows

Spec F15. The pipeline already computes what the page needs to be honest about; the provider seam drops it. This is the only server change and it blocks Task 9.

**Files:**
- Modify: `app/search_provider.py` (Protocol + both implementations)
- Modify: `app/routes/search.py` (three additive response keys)
- Test: `tests/test_search_route.py`, `tests/test_lance_provider.py`

**Interfaces:**
- `SearchProvider.search(...)` returns a shape carrying `rows` plus `inferred_fiscal_years: list[int]`, `inferred_doc_types: list[str]`, `dropped_filters: list[str]`.
- `POST /api/search` response becomes `{results, total, provider, inferred_fiscal_years, inferred_doc_types, dropped_filters}`. **No existing key is renamed or removed.**

- [ ] **Step 1: Write the failing route test**

```python
# tests/test_search_route.py
def test_search_echoes_what_the_pipeline_inferred():
    """A question naming a year is hard-filtered by session before the search
    runs, and the page has no way to know (spec F15). The route must say so.

    Additive only: the three original keys are asserted alongside, because the
    contract is frozen in the sense that nothing existing may move.
    """
    body = client().post("/api/search", json={
        "query": "FY 2027 revenue impact of a sales tax exemption",
        "corpus": "fiscal_notes",
    }).json()
    assert {"results", "total", "provider"} <= body.keys()      # nothing lost
    assert body["inferred_fiscal_years"] == [2027]
    assert body["inferred_doc_types"] == []
    assert body["dropped_filters"] == []
```

- [ ] **Step 2: Change the Protocol and BOTH implementations**

`StubSearchProvider` is what the filter UI is tested against — leaving it behind makes F15 untestable in the suite most likely to catch a regression. Both return the new shape; the stub returns empty lists (it infers nothing, by design).

- [ ] **Step 3: Pass through in the route, and pin that filters suppress inference**

```python
def test_explicit_session_filter_suppresses_the_year_guess():
    """F15's undo must actually work: the pipeline only infers when the caller
    passed no fiscal_year of its own, so "Search every session" sends an
    explicit wide filter rather than editing the analyst's question."""
    body = client().post("/api/search", json={
        "query": "FY 2027 revenue impact of a sales tax exemption",
        "corpus": "fiscal_notes",
        "filters": {"fiscal_year": [<every session year>]},
    }).json()
    assert body["inferred_fiscal_years"] == []
```

- [ ] **Step 4: Full suite** — `uv run pytest -q`, no regressions against Task 1's baseline.

---

### Task 3: `api.ts` types the three new fields

Small, but it belongs on its own so the front-end tasks can rely on it.

**Files:**
- Modify: `webapp/src/api.ts` (`SearchResponse`)
- Test: `webapp/src/api.test.ts`

- [ ] **Step 1:** Extend `SearchResponse` with the three fields, each optional (`?`) so a server that predates Task 2 does not break typing during a partial deploy.
- [ ] **Step 2:** The existing test asserting the request body is exactly `{query, filters, corpus}` must stay green — this task changes the RESPONSE only.

---

### Task 4: `sessionLabel()` — year first, through a map

Spec F4. Pure function, no React. It is used in four places (card heads, aria-labels, the result card's session line, the drawer breadcrumb), which is exactly why it is extracted before anything renders.

**Files:**
- Create: `webapp/src/search/fiscalNotes.ts`
- Test: `webapp/src/search/fiscalNotes.test.ts`

**Interfaces:**
- `sessionLabel(session: {year: number; name: string}) -> string`

- [ ] **Step 1: Write the failing test**

```ts
test("puts the year first and expands the abbreviation", () => {
  expect(sessionLabel({year: 2026, name: "57th Legislature, 2nd Reg. Session (2026)"}))
    .toBe("2026 (57th Legislature, 2nd Regular Session)");
});

test("an unrecognised form passes through intact rather than half-rewritten", () => {
  // Arizona holds special sessions; every live session is Regular TODAY (spec
  // fact 6), which is exactly why a blind .replace() would rot silently.
  const odd = {year: 2027, name: "58th Legislature, 1st Spec. Session (2027)"};
  expect(sessionLabel(odd)).toBe("2027 (58th Legislature, 1st Special Session)");
});

test("strips the trailing year ONLY when it is this session's own", () => {
  expect(sessionLabel({year: 2026, name: "Something (1999)"})).toBe("2026 (Something (1999))");
});
```

- [ ] **Step 2:** Implement with a `SESSION_WORDS` map, not a chained `.replace()`.
- [ ] **Step 3:** Run against every one of the 28 real session names and assert none comes back containing a `.` abbreviation or a doubled year.

---

### Task 5: `parseNoteTitle()` — the retrieval title is not the browse title

Spec F16, and spec facts 1–2. This is the task most likely to be skipped by someone who assumes the search result already looks like a card, and it produces three visible defects if skipped.

**Files:**
- Modify: `webapp/src/search/fiscalNotes.ts`
- Test: `webapp/src/search/fiscalNotes.test.ts`

**Interfaces:**
- `parseNoteTitle(docTitle: string) -> {number: string | null; title: string}`

- [ ] **Step 1: Write the failing tests, driven by REAL titles**

```ts
test("strips the ingest prefix and splits on the FIRST colon", () => {
  // Every one of 2,104 titles is prefixed "Fiscal Note - " (spec fact 1). A
  // page titled "Fiscal Notes" whose every card opens with "Fiscal Note" is
  // the defect this exists to prevent.
  expect(parseNoteTitle("Fiscal Note - HB 2407: victim notification"))
    .toEqual({number: "HB 2407", title: "victim notification"});
});

test("later colons and semicolons belong to the title", () => {
  expect(parseNoteTitle("Fiscal Note - SB 1035: corrections; appropriation: FY25"))
    .toEqual({number: "SB 1035", title: "corrections; appropriation: FY25"});
});

test("a title that does not match the shape renders WHOLE, not cut wrong", () => {
  expect(parseNoteTitle("something unexpected"))
    .toEqual({number: null, title: "something unexpected"});
});

test("HTML in the title survives the parse as characters, not markup", () => {
  // 240 of 2,104 carry raw <strike> (spec fact 2). The parser must not eat it,
  // strip it, or interpret it — BillTitle handles it downstream (Task 8).
  const raw = "Fiscal Note - HB 2172: <strike>technology transfer</strike> (NOW: solar device; tax credit)";
  expect(parseNoteTitle(raw).title).toBe("<strike>technology transfer</strike> (NOW: solar device; tax credit)");
});
```

- [ ] **Step 2: Implement.** Split on the first `: ` after stripping the prefix; return `{number: null}` on no match rather than guessing a boundary.
- [ ] **Step 3: Run it over every real title in the corpus** and assert zero come back with a `number` longer than ~8 characters — a long "number" means the split landed in the wrong place.

---

### Task 6: `groupNotes()` and `resultsHeader()` — one card per note, cut at 15

Spec F10 and F11. `webapp/src/search/contentSearch.ts` already has `groupPassages()`, which collapses a flat result list into one entry per document, best passage first, best document first. **Reuse it rather than writing a second one** — then cut.

**Files:**
- Modify: `webapp/src/search/fiscalNotes.ts`
- Test: `webapp/src/search/fiscalNotes.test.ts`

**Interfaces:**
- `SHOW_NOTES = 15`
- `groupNotes(results: SearchResult[]) -> {notes: PassageDoc[]; cut: boolean}`
- `resultsHeader(n: number, cut: boolean) -> string`

- [ ] **Step 1: Write the failing tests**

```ts
test("cuts at 15 and reports that it cut", () => {
  const {notes, cut} = groupNotes(resultsAcross(17 /* distinct notes */));
  expect(notes).toHaveLength(15);
  expect(cut).toBe(true);
});

test("the boundary: exactly 15 is the 'all' case, 16 is the 'top' case", () => {
  // The ONLY place the two header strings can be swapped with no other symptom.
  expect(groupNotes(resultsAcross(15)).cut).toBe(false);
  expect(groupNotes(resultsAcross(16)).cut).toBe(true);
});

test("the two header strings", () => {
  expect(resultsHeader(15, true)).toBe("Showing top 15 matches");
  expect(resultsHeader(9, false)).toBe("Showing all 9 matches");
  expect(resultsHeader(1, false)).toBe("Showing all 1 match");   // singular
});

test("one card per note, holding that note's BEST passage first", () => {
  // F11: a card shows one passage. Grouping still ranks within a note so the
  // card takes [0]; the rest inform nothing but the ordering.
  const {notes} = groupNotes(twoPassagesOfOneNote({scores: [0.2, 0.9]}));
  expect(notes).toHaveLength(1);
  expect(notes[0].passages[0].score).toBe(0.9);
});
```

- [ ] **Step 2: Implement on top of `groupPassages`.** If it is directly reusable, import it; if the fiscal-note row shape differs, say why in a WHY comment rather than silently forking it.
- [ ] **Step 3:** Assert no count anywhere in this module names passages — spec F10 requires every on-screen count to be notes/matches.

---

### Task 7: The rail — session filter, chamber segments, sort, one search box

Spec F1, F2, F5, F6, F9. The page's controls, before the cards change under them.

**Files:**
- Modify: `webapp/src/pages/FiscalNotes.tsx`
- Test: `webapp/src/pages/FiscalNotes.test.tsx`

- [ ] **Step 1: Session becomes a multi-select dropdown with per-option counts** (F1), replacing the 28-row `.yscroll` radio list. Twin of Budget Documents' Fiscal Year control.
- [ ] **Step 2: Sort moves out of the card headers into the rail** (F5). It sorts bills WITHIN each card and never flattens sessions into one list; sessions stay newest-first regardless.
- [ ] **Step 3: Delete `SemanticRailSearch`** (F6) and retire "Search all legislative sessions" (F7) — its `.allbar` slot is reused by the titles/contents toggle.
- [ ] **Step 4: Both chamber and sort stand down in content mode, sharing ONE sentence** (F9):

```ts
test("chamber and sort go inactive together, and say why once", () => {
  // ONE sentence covering both: two sentences would imply two different
  // reasons. Chamber cannot filter a ranked list without removing evidence it
  // has no way to backfill (spec fact 5 + fact 8).
  renderInContentMode();
  expect(screen.getByRole("button", {name: /house/i})).toBeDisabled();
  expect(screen.getByRole("button", {name: /sort/i})).toBeDisabled();
  expect(screen.getAllByText(/ranked results are ordered by relevance/i)).toHaveLength(1);
});
```

- [ ] **Step 5: The search box grows to two or three lines as you type** (F6/Q1), keeping its rail position. **Budget Documents gets the identical fix in the same pass** — leaving one sibling unfixed re-creates the divergence this work exists to remove.

---

### Task 8: Session cards — collapsible, flat bill lists, conditional mounting

Spec F3, F4, F8. This task contains the one performance regression this design can actually cause.

**Files:**
- Modify: `webapp/src/pages/FiscalNotes.tsx`
- Test: `webapp/src/pages/FiscalNotes.test.tsx`

- [ ] **Step 1: One `.yg` card per in-scope session**, newest expanded, priors collapsed, toggle state surviving filter round-trips (F1/F3).
- [ ] **Step 2: Mount the body CONDITIONALLY.** Budget Documents mounts every year body and hides it with `hidden` to preserve open trays and head-button focus; a session card has neither, so there is no state that mounting would protect — while mounting all 28 bodies puts ~2,126 rows in the DOM. **Do not cite `FiscalNotes.tsx`'s "~113 ms → ~55 ms" comment in support of this**; that measured what `memo()` was worth on an earlier draft that kept all rows mounted, and the comment says in terms not to quote it for this layout. The argument is structural.
- [ ] **Step 3: The expansion cap — the acceptance test that matters most**

```tsx
test("a broad title query does NOT expand every card", async () => {
  // THE regression this design can cause. Typing `a` matches 2,029 of 2,126
  // rows across all 28 sessions; `tax` matches 513 across 28. Short prefixes
  // are not an edge case — they are the state every longer query passes
  // through, on every keystroke (spec F8, measured).
  renderWithRealSnapshot();
  await userEvent.type(screen.getByRole("searchbox"), "a");
  expect(document.querySelectorAll(".yg .fnlist")).toHaveLength(3);   // bodies mounted
  expect(document.querySelectorAll(".yg")).toHaveLength(28);          // headers + counts
});

test("a collapsed matching card still states its true match count", () => {
  // The 4th-newest matching session is collapsed, not hidden: the count is a
  // true statement and the rows are one click away.
});
```

- [ ] **Step 4: A session with zero matches disappears, and every count equals the rows it renders.** True by construction (non-matching rows are removed) — pin both halves anyway.
- [ ] **Step 5: The toggle handler must flip what is ON SCREEN, not recompute the default.** The default differs by mode — newest one while browsing, newest three during a title search — and re-deriving it at the click site is how those drift apart. The symptom is a first click that appears to do nothing. (This exact bug was found and fixed in the mockups on 2026-08-13.)

---

### Task 9: Escalation, the waiting state, and the inference line

Spec F6, F15. Port Budget Documents' recipe rather than reinventing it — including the two defects it already paid for.

**Files:**
- Modify: `webapp/src/pages/FiscalNotes.tsx`
- Test: `webapp/src/pages/FiscalNotes.content.test.tsx` (new, mirroring `Search.content.test.tsx`)

- [ ] **Step 1: `ESCALATE_MS` / `suppressedQuery`, keyed on the QUERY STRING, not a boolean**

```tsx
test("crossing back to titles does not yank the reader forward again", async () => {
  // The live defect on Budget Documents (2026-08-10). A reader who clicks back
  // to titles is BY CONSTRUCTION the population that stays at zero title hits,
  // so a boolean flag would re-escalate them on the next render. Keyed on the
  // query, it self-invalidates the moment the query changes by any route.
});

test("typing again restarts the pause instead of firing on the stale timer", async () => {
  // `q` is load-bearing in the effect's dependency list, not an exhaustive-deps
  // nit: titleHits stays 0 across successive zero-hit keystrokes.
});
```

- [ ] **Step 2: The waiting state — the page commits the moment escalation is ARMED** (F6). The armed pause and the in-flight request must render identically, so the handoff is invisible. Without this the page shows "No note titles match" for two full seconds and *then* a spinner, which reads as a failure that changed its mind.
- [ ] **Step 3: Escalation fires only at zero title hits, only after the quiet period.** Also pin that the mode toggle renders when title mode HAS hits — a single topical word like `water` matches 11 titles and never auto-escalates, by design, so the manual route must be visible exactly there.
- [ ] **Step 4: The inference line** (F15), consuming Task 2's new fields:

```tsx
test("a year-naming question states the narrowing and can undo it", async () => {
  // The honesty gap: "FY 2027 …" is hard-filtered by session while the rail
  // still reads "Any session". Worse than the doc-type guess, which gets
  // dropped and reported when it empties the page — the YEAR guess is never
  // dropped, so a narrow guess quietly returns less, forever.
  expect(screen.getByText(/also limited to the 2026–2028 sessions/i)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", {name: /search every session/i}));
  // The undo sends an explicit WIDE session filter (which suppresses the
  // inference), rather than editing the analyst's question.
  expect(lastRequest().filters.fiscal_year).toHaveLength(28);
});
```

- [ ] **Step 5: Failure surfaces the real detail** the backend sent, never a guessed cause (`api.ts`'s `fail()` already extracts FastAPI's `detail`).

---

### Task 10: The result card

Spec F11–F14, F16, F17. Build from `mockups/fiscal-notes-retrieval-results.html`.

**Files:**
- Create: `webapp/src/pages/FiscalNoteResult.tsx`
- Test: `webapp/src/pages/FiscalNoteResult.test.tsx`

- [ ] **Step 1: Layout** (F12) — bill number and title on ONE line, number heavier, no navy chip; **the title wraps, it does not truncate** (a fiscal-note title is the only plain-English description of what a bill does, and the 240 retitled `(NOW: …)` forms are long enough that an ellipsis would hide the half that matters); session small and tight beneath; "Open note" top-right; no page reference (the drawer's breadcrumb names the page, which is where the reader is actually looking at it); the section name as a faint legend breaking the top edge of a hairline box tracing the whole excerpt.
- [ ] **Step 2: The two halves come from `parseNoteTitle` (Task 5), and render through the page's existing `BillTitle`/`stripTags`.**

```tsx
test("a struck title renders through BillTitle, never as raw HTML", () => {
  // Drive one of the 240 REAL struck titles. Note what is asserted and what is
  // NOT: the strikethrough must SURVIVE — it is the only thing on screen
  // saying this bill's title was replaced. What must never happen is the raw
  // string reaching the DOM as characters, or via dangerouslySetInnerHTML.
  render(<FiscalNoteResult note={realStruckNote} />);
  expect(document.body.innerHTML).not.toContain("&lt;strike&gt;");
  expect(document.body.innerHTML).not.toContain("<strike>");
  expect(screen.getByText("technology transfer").tagName).toBe("S");
  expect(screen.getByText(/NOW: solar device/)).toBeInTheDocument();
});
```

- [ ] **Step 3: The session line is JOINED from the directory** (F4). A result carries `fiscal_year` — the bare number — and never the session name; the name exists only in `GET /api/fiscal-notes`, which the page has already fetched. Build a `Map<year, Session>` once. **Pin the join**: the failure is a silent blank line, not an error.
- [ ] **Step 4: The whole card is ONE button** (F13). Its "Open note" pill is a decorative span, exactly as `.fbill-dl`'s "PDF" label is. The label reads **"Close note"** while that card's drawer is open, because the card is a toggle.

```tsx
test("exactly one passage and exactly one interactive element", () => {
  expect(screen.getAllByRole("button")).toHaveLength(1);
  expect(document.querySelectorAll("button button, button a")).toHaveLength(0);
});
```

- [ ] **Step 5: "Open note" opens the SOURCE DRAWER** (F14), reusing `SourcePanel`/`SourceView` and the existing `.pdf-drawer`.

```tsx
test("the drawer opens against the FISCAL-NOTE corpus", () => {
  // SourcePanel's `corpus` prop DEFAULTS TO "budget". Miss it and every drawer
  // on this page 404s against the wrong table — honest error message, but a
  // uniformly broken feature, and invisible in jsdom. Assert it explicitly.
  expect(sourcePanelProps().corpus).toBe("fiscal_notes");
});
```

- [ ] **Step 6: The two highlights differ by FORM, not hue** (F17) — the palette is monochrome navy. Typed terms get a flat pale wash with no rule; the cited passage in the drawer gets a deeper navy band **plus a solid underline**. Word matching uses a boundary at BOTH ends, matching the shipped `highlightTerms()`: anchoring only the front highlights "inmate" inside "inmates" and leaves the "s" outside the mark.

---

### Task 11: Wire the modes together, and the empty states

Spec F8. The two modes look different on purpose — they answer different questions, and the toggle between them is easier to understand when the shapes differ.

**Files:**
- Modify: `webapp/src/pages/FiscalNotes.tsx`
- Test: `webapp/src/pages/FiscalNotes.content.test.tsx`

- [ ] **Step 1: Title mode keeps session cards; content mode collapses to ONE ranked "Results" card.** Re-bucketing a relevance-ordered list by session would bury the best passage under weaker ones from a newer session.
- [ ] **Step 2: Neither empty state is a dead end** — the mode toggle renders on both.
- [ ] **Step 3: A session can legitimately show rows in title mode and nothing in content mode.** The directory holds 2,126 bills and the corpus 2,104 notes, so ~22 bills have a directory row and no ingested note (spec fact 9). **Not a defect to chase** — do not add a "missing note" warning.
- [ ] **Step 4: The results header** uses Task 6's strings, and no count on the page implies a corpus-wide total.

---

### Task 12: Full verification, and the part the suites cannot see

**Files:** none — this task produces evidence.

- [ ] **Step 1: Both full suites green.** `uv run pytest -q` and `npm test --prefix webapp -- --run`, compared against Task 1's baseline. Plus `npx tsc -b --noEmit` in `webapp/`.
- [ ] **Step 2: OPEN THE PAGE.** Run the app and exercise, at minimum:
  - typing `a`, then `tax`, then a whole question, watching what expands and when escalation fires;
  - a question naming a year, and clicking "Search every session";
  - a struck-title note in the results;
  - opening and closing a drawer, and confirming the label toggles;
  - the rail with chamber and sort greyed out, and the one sentence beneath.
- [ ] **Step 3: Look for the two classes jsdom cannot catch** — layout (a card wider than its container, silently clipped) and highlighting (a mark that splits a word and orphans its last letter). Neither can ever fail a test; both shipped in this design's own mockups.
- [ ] **Step 4: Commit says no eval run is required, and why** — this is a webapp + `app/` change, nothing under `retrieval/` moved.

---

## What is NOT in this plan

- **Raising `FUSED_TOP_K`.** The 15-note cut is applied in the browser precisely so nothing under `retrieval/` moves (spec F10). Raising it is a separate piece of work with an eval run attached, triggered by an observed miss and nothing less.
- **Collapsing to one passage per note before the reranker.** The better engine-side answer to the same problem, out of scope for the same reason, and it would need to be corpus-scoped or it breaks Budget Documents (spec F10).
- **Making browse rows open the in-app drawer.** They stay PDF links; the reasoning and the upgrade path are recorded in spec F14.
- **AI Mode returning to this page.** Plan 4's deviation note stands: the corpus picker in `/ai` is what preserves the coordinator's workflow.
- **Porting the browse mockup's result card** to the F12 layout. It carries a comment saying it is not the reference; the results mockup is.
