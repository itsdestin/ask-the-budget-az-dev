# Budget Documents — highlighting and book sections Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make query highlighting work on the Budget Documents content-search
cards, and fold the 647 documents currently rendering under raw machine slugs
(`s-pdf`, `bd-pdf`, …) into the books they are sections of.

**Architecture:** Two nearly-disjoint tracks. **Track A** (Tasks 1–4) ships the
full chunk text to the browser and does window selection and term marking there,
in one place, in one language. **Track B** (Tasks 5–9) adds one Python
derivation of "which book is this a section of", from `source_url`, and serves
it on both the browse listing and the search results; the browser stops
inventing families from doc_type slugs it doesn't recognise.

**Tech Stack:** FastAPI + Python 3.12 (pytest), Vite + React 18 + TypeScript
(vitest), LanceDB via `store/`.

**Spec:** `docs/superpowers/specs/2026-08-11-budget-docs-highlighting-and-book-sections-design.md`
— decisions H1–H11 and B1–B8. Read it before Task 1.

## Global Constraints

- **Never `dangerouslySetInnerHTML`.** Snippets and chunk text are corpus text,
  not trusted markup. `highlight()` returns runs; components render elements.
- **No eval run is required** — nothing under `retrieval/`, `ingest/`,
  `chunking/`, `citation/` or `harness/system-prompt.md` changes. If a task
  finds a reason to touch `retrieval/`, stop: the eval gate applies
  (`uv run python -m eval.run_eval`, ~60s, needs `JLBC_DATA_DIR`, results
  committed with the diff).
- **Annotate non-trivial edits with a WHY comment** recording the evidence, not
  just the choice. The owner is a non-developer and relies on them.
- **No hand-maintained vocabulary lists.** Specifically: no stopword list, no
  length-based term filter beyond the 1-character guard in Task 2, and do not
  import `_LOGICAL_KEY_STOPWORDS` from `retrieval/query_agency.py`.
- **Nothing may stop being findable** (B6). The 647 sections stay reachable by
  the title filter box and by content search.
- **Gate on the error rate, not the production rate.** "A mark appeared" and "a
  parent was derived" are both production counts and both were wrong during
  design. Assertions must check that the result is *right*.
- Run commands from the worktree root
  `~/ask-the-budget-az-worktrees/budget-docs-highlighting-sections`.
  Python: `JLBC_DATA_DIR=<repo>/data/insight-data PYTHONPATH=$PWD uv run …`.
  Webapp: `cd webapp && npx vitest run …`.

---

## File Structure

**Track A — highlighting (Tasks 1–4)**

| File | Responsibility |
|---|---|
| `app/search_provider.py` (modify) | emit the full chunk `text` alongside `snippet` |
| `tests/test_search_route.py` (modify) | pin that `text` is served and complete |
| `webapp/src/api.ts` (modify) | `text` on `SearchResult` |
| `webapp/src/search/contentSearch.ts` (modify) | `queryTerms`, `highlight`, `previewWindow` |
| `webapp/src/search/contentSearch.test.ts` (modify) | their unit tests |
| `webapp/src/components/PassageCard.tsx` (modify) | render the window; card-level expand |
| `webapp/src/components/PassageCard.test.tsx` (create) | card rendering + expand |

**Track B — book sections (Tasks 5–9)**

| File | Responsibility |
|---|---|
| `app/book_sections.py` (create) | THE derivation: `section_of(doc_type, source_url)` |
| `tests/test_book_sections.py` (create) | its unit tests, incl. the 21 known collisions |
| `app/routes/corpus.py` (modify) | `section_of` on each listing row |
| `tests/test_corpus_documents_route.py` (modify) | pin it |
| `app/search_provider.py` (modify) | `section_of` on results + exact family filtering |
| `tests/test_search_route.py` (modify) | pin the filtering |
| `webapp/src/api.ts` (modify) | `section_of` on `CorpusDocument` and `SearchResult` |
| `webapp/src/reportFamilies.ts` (modify) | `familyOf(docType, sectionOf)` |
| `webapp/src/pages/Search.tsx` (modify) | group by it; two groups in the tray |
| `webapp/src/pages/Search.test.tsx` (modify) | rail, grouping, tray |

**Why `section_of` and not `family`:** the five raw slugs are the only documents
whose family cannot be read off `doc_type`. A field that answers only that
question leaves `FAMILY_OF_DOC_TYPE` as the single home for the rest of the
vocabulary. Emitting a full `family` would duplicate that map into Python and
create the two-lists-that-drift bug the spec exists to avoid.

---

## Track A — Query highlighting

### Task 1: Serve the full chunk text

**Files:**
- Modify: `app/search_provider.py` (the result dict in `LanceSearchProvider.search`)
- Modify: `webapp/src/api.ts` (`SearchResult`)
- Test: `tests/test_search_route.py`

**Interfaces:**
- Produces: `SearchResult.text: string` — the chunk's verbatim text, untruncated.
  `snippet` is unchanged and still `text[:280]`; Fiscal Notes reads it (H11).

- [ ] **Step 1: Write the failing test**

Add to `tests/test_search_route.py`:

```python
def test_search_results_carry_the_full_chunk_text(monkeypatch):
    """The browser picks the preview window and paints the marks (H8), so it
    needs the whole passage, not a 280-char prefix. `snippet` stays for the
    Fiscal Notes page, which does no highlighting (H11)."""
    long_text = "Florence Replacement Beds. " + ("filler word " * 60) + "prison beds funded."
    assert len(long_text) > 280

    client = _client_with_chunks(monkeypatch, [_chunk(text=long_text)])
    body = client.post("/api/search", json={"query": "prison beds"}).json()

    row = body["results"][0]
    assert row["text"] == long_text
    assert row["snippet"] == long_text[:280]
```

If `_client_with_chunks` / `_chunk` helpers do not exist in that file under
those names, reuse whatever fixture the neighbouring search-route tests use to
inject fake chunks — do NOT open a real LanceDB directory or load ONNX weights
from a test (repo rule).

- [ ] **Step 2: Run test to verify it fails**

Run: `JLBC_DATA_DIR=$PWD/data/insight-data PYTHONPATH=$PWD uv run pytest tests/test_search_route.py::test_search_results_carry_the_full_chunk_text -v`
Expected: FAIL with `KeyError: 'text'`.

- [ ] **Step 3: Emit the field**

In `app/search_provider.py`, in the result dict, immediately after the
`"snippet"` entry:

```python
                "snippet": c.text[:280],
                # The FULL passage. The browser chooses the preview window and
                # marks the query's words in one place, in one language (spec
                # H8) — a server-chosen window plus browser-chosen marks can
                # disagree, and its failure is silent: a window obviously
                # picked BECAUSE of the match, with nothing marked in it.
                # Measured cost ~18KB per search (chunk text median 789 chars,
                # max 2,117, twenty results). Safe to ship as text: 0 of 4,000
                # sampled chunk `text` values contain markup — table markup
                # lives in the separate `table_html` column, not shipped here.
                "text": c.text,
```

- [ ] **Step 4: Run test to verify it passes**

Run: `JLBC_DATA_DIR=$PWD/data/insight-data PYTHONPATH=$PWD uv run pytest tests/test_search_route.py -v`
Expected: PASS, and every other test in the file still passes.

- [ ] **Step 5: Add the field to the TypeScript contract**

In `webapp/src/api.ts`, inside `interface SearchResult`, after `snippet`:

```ts
  snippet: string;
  /** The passage's FULL text (additive, 2026-08-11). The browser picks the
   *  preview window and marks query terms in it — see search/contentSearch.ts.
   *  `snippet` remains the leading 280 chars for the Fiscal Notes page. */
  text: string;
```

Then update the `hit()` fixture in `webapp/src/search/contentSearch.test.ts` to
include `text: "text"` so the file still type-checks.

- [ ] **Step 6: Type-check and commit**

Run: `cd webapp && npx tsc -b`
Expected: exit 0.

```bash
git add app/search_provider.py tests/test_search_route.py webapp/src/api.ts webapp/src/search/contentSearch.test.ts
git commit -m "feat(search): results carry the full passage text

The browser needs the whole passage to pick a preview window and mark the
query's words in one place (spec H8). snippet stays as-is for Fiscal Notes."
```

---

### Task 2: Mark every typed word, on word boundaries

**Files:**
- Modify: `webapp/src/search/contentSearch.ts`
- Test: `webapp/src/search/contentSearch.test.ts`

**Interfaces:**
- Produces:
  - `queryTerms(query: string): string[]` — lowercased, deduped, longest-first.
  - `highlight(text: string, query: string): { text: string; hit: boolean }[]`
    — unchanged signature, new behaviour.
  - `highlightTerms(text: string, terms: string[]): { text: string; hit: boolean }[]`
    — the same, for a caller that already tokenised (Task 3 and Task 4 use it).

- [ ] **Step 1: Write the failing tests**

Replace the three existing `highlight` tests in
`webapp/src/search/contentSearch.test.ts` (they assert the whole-query
substring behaviour this task deletes) with:

```ts
import { highlight, queryTerms } from "./contentSearch";

test("every typed word marks independently, not the whole query as one string", () => {
  // The shipped behaviour searched for the entire query as one literal
  // substring. Measured: 0 of 200 real cards produced a single mark.
  const runs = highlight("Child care subsidy waiting list rose", "child care waiting");
  expect(runs.filter((r) => r.hit).map((r) => r.text)).toEqual(["Child", "care", "waiting"]);
});

test("marks are case-insensitive but keep the ORIGINAL casing", () => {
  expect(highlight("AHCCCS funding", "ahcccs")).toEqual([
    { text: "AHCCCS", hit: true },
    { text: " funding", hit: false },
  ]);
});

test("matching is on WORD BOUNDARIES, not substrings", () => {
  // Substring matching measured 8.3 marks per card peaking at 31, because
  // short words match inside longer ones. Boundaries: 6.0, capped at 14.
  expect(highlight("He said the aid was paid", "aid").filter((r) => r.hit))
    .toEqual([{ text: "aid", hit: true }]);
});

test("three-letter domain terms are NOT dropped", () => {
  // A length>=4 rule was measured and rejected: it silently loses "aid"
  // (basic state aid) and "des", the terms this domain is about (spec H1).
  expect(highlight("DES basic state aid", "des aid").filter((r) => r.hit).length).toBe(2);
});

test("no stopword list — function words mark like any other word", () => {
  // Four rules were measured and all four leave the blank rate at 2.9%, so
  // dropping function words is cosmetic. "We underline the words you typed."
  expect(highlight("the fund for schools", "the for").filter((r) => r.hit).map((r) => r.text))
    .toEqual(["the", "for"]);
});

test("a possessive contributes its stem, not a stray one-letter term", () => {
  expect(queryTerms("the state's share")).toEqual(
    expect.arrayContaining(["state", "share", "the"]),
  );
  expect(queryTerms("the state's share")).not.toContain("s");
});

test("longer terms win over shorter ones that start inside them", () => {
  const runs = highlight("childcare and child care", "child childcare");
  expect(runs.filter((r) => r.hit).map((r) => r.text)).toEqual(["childcare", "child"]);
});

test("regex metacharacters in the query are literal, not patterns", () => {
  expect(highlight("a (b) c", "(b)").filter((r) => r.hit).map((r) => r.text)).toEqual(["b"]);
});

test("no match, or an empty query, returns one plain run", () => {
  expect(highlight("nothing here", "zzz")).toEqual([{ text: "nothing here", hit: false }]);
  expect(highlight("nothing here", "   ")).toEqual([{ text: "nothing here", hit: false }]);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && npx vitest run src/search/contentSearch.test.ts`
Expected: FAIL — `queryTerms` is not exported, and the word-splitting
assertions fail against the substring implementation.

- [ ] **Step 3: Implement**

In `webapp/src/search/contentSearch.ts`, replace the whole `highlight`
function with:

```ts
/** Escape a term so it is matched literally inside a RegExp. A query is
 *  reader input; "(b)" must find "(b)", never compile as a group. */
function escapeRegExp(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** The words to mark: every word the analyst typed, lowercased and deduped,
 *  longest first.
 *
 *  WHY no stopword list, no length rule, no vocabulary of any kind (spec H1):
 *  four candidate rules were measured over 240 real cards and ALL FOUR leave
 *  the share of cards with no mark at 2.9%. Dropping function words rescues
 *  nothing; it only moves mark density from 6.0 to 4.8 in a window of about
 *  45 words. Meanwhile a `length >= 4` rule silently loses "aid" (basic state
 *  aid) and "des" — the terms this domain is actually about. So the cheap,
 *  explainable rule wins: we underline the words you typed.
 *
 *  The ONE exclusion is single-character tokens, and it is not a stopword
 *  rule: "the state's share" tokenises to state / s / share, and a lone "s"
 *  would mark stray letters. Three-character domain terms are deliberately
 *  kept — there is a test for exactly that.
 *
 *  Longest-first because the alternation below is ordered: with "child" and
 *  "childcare" both typed, the shorter one would otherwise win the prefix. */
export function queryTerms(query: string): string[] {
  const seen = new Set<string>();
  for (const raw of query.toLowerCase().replace(/[’']s\b/g, "").split(/[^a-z0-9]+/)) {
    if (raw.length > 1) seen.add(raw);
  }
  return [...seen].sort((a, b) => b.length - a.length);
}

function termsPattern(terms: string[]): RegExp | null {
  if (!terms.length) return null;
  // Word boundaries, not substrings (spec H2): substring matching measured
  // 8.3 marks per card and peaked at 31, because short words match inside
  // longer ones ("aid" in "said"/"paid").
  return new RegExp(`\\b(?:${terms.map(escapeRegExp).join("|")})\\b`, "gi");
}

/** Split text into matched / unmatched runs for a set of already-tokenised
 *  terms. Each run carries the ORIGINAL casing — an analyst reading "AHCCCS"
 *  must not be shown "ahcccs" because that is what they typed. */
export function highlightTerms(
  text: string,
  terms: string[],
): { text: string; hit: boolean }[] {
  const re = termsPattern(terms);
  if (!re) return [{ text, hit: false }];
  const runs: { text: string; hit: boolean }[] = [];
  let i = 0;
  for (const m of text.matchAll(re)) {
    const at = m.index ?? 0;
    if (at > i) runs.push({ text: text.slice(i, at), hit: false });
    runs.push({ text: m[0], hit: true });
    i = at + m[0].length;
  }
  if (i < text.length) runs.push({ text: text.slice(i), hit: false });
  return runs.length ? runs : [{ text, hit: false }];
}

/** Split a snippet into matched / unmatched runs for the query.
 *
 *  WHY this returns runs instead of an HTML string: the snippet is corpus
 *  text, and building `<mark>` markup from it would mean
 *  dangerouslySetInnerHTML on data this app does not control. The component
 *  renders these runs as real elements instead. */
export function highlight(text: string, query: string): { text: string; hit: boolean }[] {
  return highlightTerms(text, queryTerms(query));
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && npx vitest run src/search/contentSearch.test.ts`
Expected: PASS, all tests in the file.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/search/contentSearch.ts webapp/src/search/contentSearch.test.ts
git commit -m "fix(search): mark every typed word, on word boundaries

Highlighting searched for the entire query as one literal substring, so it
marked nothing for any natural-language question -- measured 0 of 200 real
cards. Every typed word now marks independently, matched on word boundaries.

No stopword list: four rules were measured and all four leave the blank rate
at 2.9%, while a length>=4 rule silently loses 'aid' and 'des'."
```

---

### Task 3: The preview window — leading by default, match-centred as fallback

**Files:**
- Modify: `webapp/src/search/contentSearch.ts`
- Test: `webapp/src/search/contentSearch.test.ts`

**Interfaces:**
- Consumes: `queryTerms`, `highlightTerms` (Task 2).
- Produces:
  ```ts
  export interface Preview { text: string; ellipsisStart: boolean; ellipsisEnd: boolean }
  export function previewWindow(text: string, terms: string[], size?: number): Preview
  ```

- [ ] **Step 1: Write the failing tests**

Append to `webapp/src/search/contentSearch.test.ts`:

```ts
import { previewWindow, queryTerms } from "./contentSearch";

const LEAD = "Florence Replacement Beds. The Baseline includes an increase of $22,500,000 ";

test("short passages are shown whole, with no ellipsis", () => {
  expect(previewWindow("A short passage about beds.", queryTerms("beds"))).toEqual({
    text: "A short passage about beds.",
    ellipsisStart: false,
    ellipsisEnd: false,
  });
});

test("the LEADING text is the default preview, even when a later window holds more terms", () => {
  // Measured and deliberate (spec H3): JLBC front-loads these documents --
  // heading, then "The Baseline includes $X for Y", then background. A
  // match-centred window scores higher on terms visible and reads worse,
  // dropping the heading AND the dollar figure. Median first match: char 5.
  const text = LEAD + "x".repeat(400) + " beds beds beds beds";
  const p = previewWindow(text, queryTerms("beds"), 280);
  expect(p.text.startsWith("Florence Replacement Beds.")).toBe(true);
  expect(p.ellipsisStart).toBe(false);
  expect(p.ellipsisEnd).toBe(true);
});

test("it slides to the first match ONLY when the leading text has no typed word", () => {
  // The 3.5% case (spec H4). Falling back is explainable in one sentence;
  // defaulting to it is not.
  const text = "z".repeat(400) + " the waiting list grew " + "z".repeat(400);
  const p = previewWindow(text, queryTerms("waiting"), 280);
  expect(p.text).toContain("waiting");
  expect(p.ellipsisStart).toBe(true);
  expect(p.ellipsisEnd).toBe(true);
});

test("a slid window snaps to word boundaries and never cuts mid-word", () => {
  const text = "z".repeat(400) + " extraordinary waiting list " + "z".repeat(400);
  const p = previewWindow(text, queryTerms("waiting"), 120);
  expect(p.text).not.toMatch(/^\S/);
  expect(p.text.trim().split(/\s+/).some((w) => w === "extraordinary" || w === "waiting")).toBe(true);
});

test("a passage with no typed word anywhere still previews its leading text", () => {
  // ~3% of cards ranked on the dense leg alone and contain none of the
  // reader's words. They render with no marks -- an honest absence beats a
  // guess (spec H6) -- but they still show the start of the passage.
  const text = LEAD + "y".repeat(400);
  const p = previewWindow(text, queryTerms("nothingmatcheshere"), 280);
  expect(p.text.startsWith("Florence Replacement Beds.")).toBe(true);
  expect(p.ellipsisStart).toBe(false);
});

test("an empty term list previews the leading text", () => {
  const text = LEAD + "y".repeat(400);
  expect(previewWindow(text, [], 280).text.startsWith("Florence")).toBe(true);
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && npx vitest run src/search/contentSearch.test.ts`
Expected: FAIL — `previewWindow` is not exported.

- [ ] **Step 3: Implement**

Append to `webapp/src/search/contentSearch.ts`:

```ts
/** How much of a passage a card shows before the reader expands it. Matches
 *  the width the card was designed around (it was `text[:280]` server-side). */
const PREVIEW_CHARS = 280;

export interface Preview {
  text: string;
  /** The window does not start at the beginning of the passage. */
  ellipsisStart: boolean;
  /** The window does not reach the end of the passage. */
  ellipsisEnd: boolean;
}

/** Pick the slice of a passage the card previews.
 *
 *  The LEADING text is the default, and that is a measured decision, not
 *  laziness (spec H3). JLBC front-loads these documents by construction:
 *  every chunk opens with a section heading, then "The Baseline includes $X
 *  for Y", then background prose. So the leading characters ARE the summary,
 *  which is also why the median first query-word match sits at character 5
 *  and only 3.5% of cards lose their mark to truncation.
 *
 *  A match-centred window was measured and reads WORSE: it scores higher on
 *  terms visible while dropping the heading and the dollar figure, and in one
 *  observed case shifted ten characters to gain one term, chopping
 *  "Enrollment Changes" into " Changes". Optimising for terms-visible rewards
 *  drifting into dense prose and away from the headline. So it is the
 *  FALLBACK, for the ~3.5% of cards whose leading text has no typed word at
 *  all -- otherwise the reader sees a passage with no visible reason for
 *  being there. */
export function previewWindow(
  text: string,
  terms: string[],
  size: number = PREVIEW_CHARS,
): Preview {
  if (text.length <= size) {
    return { text, ellipsisStart: false, ellipsisEnd: false };
  }
  const lead = text.slice(0, size);
  const hasMark = (s: string) => highlightTerms(s, terms).some((r) => r.hit);
  if (!terms.length || hasMark(lead)) {
    return { text: lead, ellipsisStart: false, ellipsisEnd: true };
  }

  const re = termsPattern(terms);
  const first = re ? text.search(re) : -1;
  if (first === -1) {
    // No typed word anywhere in the passage (spec H6). Nothing to slide to,
    // so show the start rather than an arbitrary middle.
    return { text: lead, ellipsisStart: false, ellipsisEnd: true };
  }

  // Centre on the match, then snap OUTWARD to whitespace so the window never
  // begins or ends mid-word.
  let start = Math.max(0, Math.min(first - Math.floor(size / 3), text.length - size));
  let end = Math.min(text.length, start + size);
  if (start > 0) {
    const ws = text.lastIndexOf(" ", start);
    start = ws === -1 ? start : ws;
  }
  if (end < text.length) {
    const ws = text.indexOf(" ", end);
    end = ws === -1 ? text.length : ws;
  }
  return {
    text: text.slice(start, end),
    ellipsisStart: start > 0,
    ellipsisEnd: end < text.length,
  };
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && npx vitest run src/search/contentSearch.test.ts`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/search/contentSearch.ts webapp/src/search/contentSearch.test.ts
git commit -m "feat(search): preview window, leading by default

JLBC front-loads these documents, so the leading text is the summary -- a
match-centred window scores higher on terms visible and reads worse, dropping
the heading and the dollar figure. It becomes the fallback for the 3.5% of
cards whose leading text holds no typed word."
```

---

### Task 4: Render the window, and expand the card in place

**Files:**
- Modify: `webapp/src/components/PassageCard.tsx`
- Create: `webapp/src/components/PassageCard.test.tsx`

**Interfaces:**
- Consumes: `queryTerms`, `highlightTerms`, `previewWindow`, `Preview` (Tasks 2–3);
  `SearchResult.text` (Task 1).
- Produces: nothing later tasks depend on.

**Design note the implementer must respect:** the passage rows are real
`<button>` elements, so the expand control CANNOT be nested inside one — that
is invalid HTML. Expansion is therefore **card-level** (spec H9: "the card
expands in place"), with one control in the existing `.ctx-row` beside "More
from this document", and it applies to every quote in the card.

- [ ] **Step 1: Write the failing tests**

Create `webapp/src/components/PassageCard.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { PassageCard } from "./PassageCard";
import type { SearchResult } from "../api";
import type { PassageDoc } from "../search/contentSearch";

const LONG = "Florence Replacement Beds. The Baseline includes an increase of $22,500,000 "
  + "filler ".repeat(80) + "final prison words.";

function passage(over: Partial<SearchResult> = {}): SearchResult {
  return {
    chunk_id: "c1", doc_id: "d1", doc_title: "FY 2023 Appropriations Report — ADC",
    snippet: LONG.slice(0, 280), text: LONG, page: 12, score: 1,
    doc_type: "approps-per-agency", fiscal_year: 2023, publisher: "jlbc",
    agencies: [], doc_url: null, doc_meta: null, ...over,
  };
}

function doc(passages: SearchResult[]): PassageDoc {
  return {
    doc_id: "d1", doc_title: "FY 2023 Appropriations Report — ADC",
    publisher: "jlbc", passages,
  };
}

function renderCard(query: string, passages = [passage()]) {
  return render(
    <PassageCard
      doc={doc(passages)}
      query={query}
      trayOpen={false}
      onToggleTray={() => {}}
      onOpenPassage={() => {}}
    />,
  );
}

test("the query's words are marked in the quoted passage", () => {
  renderCard("prison beds");
  const marks = screen.getAllByText(/beds/i, { selector: "mark" });
  expect(marks.length).toBeGreaterThan(0);
});

test("a passage longer than the preview is truncated until expanded", async () => {
  renderCard("prison beds");
  expect(screen.queryByText(/final prison words/)).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /full passage/i }));
  expect(screen.getByText(/final prison words/)).toBeInTheDocument();
});

test("the expanded passage is marked too, not just the preview", () => {
  // Guards the real risk in expansion: rendering the full text through a
  // different path that forgets the marks. "No second fetch" is NOT tested —
  // the component receives `text` as a prop and has no code path that could
  // fetch, so such an assertion would pass trivially and would keep passing
  // if expansion broke entirely.
  renderCard("prison beds");
  return userEvent
    .click(screen.getByRole("button", { name: /full passage/i }))
    .then(() => {
      expect(screen.getByText(/final prison words/)).toBeInTheDocument();
      expect(screen.getAllByText(/prison/i, { selector: "mark" }).length).toBeGreaterThan(1);
    });
});

test("a passage with none of the reader's words renders with no marks", () => {
  // ~3% of cards ranked on the dense leg alone. An honest absence (spec H6).
  const { container } = renderCard("zzzznotpresent");
  expect(container.querySelectorAll("mark")).toHaveLength(0);
});

test("no expand control when the whole passage already fits", () => {
  renderCard("beds", [passage({ text: "Short passage about beds." })]);
  expect(screen.queryByRole("button", { name: /full passage/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && npx vitest run src/components/PassageCard.test.tsx`
Expected: FAIL — the card renders `passage.snippet` through the old `Quote`,
so there is no expand control and the truncation assertions fail.

- [ ] **Step 3: Implement**

In `webapp/src/components/PassageCard.tsx`, replace the imports and the
`Quote` / `PassageRow` definitions:

```tsx
import { useMemo, useState } from "react";
import { publisherLabel } from "../publishers";
import { ChevronIcon } from "./DocIcons";
import {
  highlightTerms,
  previewWindow,
  queryTerms,
  type PassageDoc,
} from "../search/contentSearch";
import type { SearchResult } from "../api";

/** The quoted passage, with the analyst's words marked.
 *
 *  Runs come from `highlightTerms()` and are rendered as ELEMENTS — the text is
 *  corpus text, so building markup from it and setting innerHTML would be
 *  handing untrusted content to the DOM.
 *
 *  `expanded` is owned by the CARD, not by this component: the rows are real
 *  <button> elements and a nested <button> is invalid HTML, so the control
 *  lives once in the card's context row (spec H9). */
function Quote({
  text,
  terms,
  expanded,
}: {
  text: string;
  terms: string[];
  expanded: boolean;
}) {
  const view = expanded
    ? { text, ellipsisStart: false, ellipsisEnd: false }
    : previewWindow(text, terms);
  return (
    <span className="doc-quote">
      {view.ellipsisStart && <span aria-hidden="true">… </span>}
      {highlightTerms(view.text, terms).map((run, i) =>
        run.hit ? <mark key={i}>{run.text}</mark> : <span key={i}>{run.text}</span>,
      )}
      {view.ellipsisEnd && <span aria-hidden="true"> …</span>}
    </span>
  );
}

/** One passage row. It is a real <button>: the href would be a placeholder,
 *  the handler is what opens the source, and provenance is the one path that
 *  must not require a pointing device. The page pill carries the arrow that
 *  says so (the A1 affordance). */
function PassageRow({
  passage,
  terms,
  expanded,
  onOpen,
}: {
  passage: SearchResult;
  terms: string[];
  expanded: boolean;
  onOpen: (chunkId: string) => void;
}) {
  return (
    <button type="button" className="doc quoterow" onClick={() => onOpen(passage.chunk_id)}>
      <div className="doc-main">
        <Quote text={passage.text} terms={terms} expanded={expanded} />
      </div>
      <span className="doc-pill">
        {passage.page === null ? "no page" : `p. ${passage.page}`}
        <span className="go" aria-hidden="true">
          →
        </span>
      </span>
    </button>
  );
}
```

Then in `PassageCard` itself, add the state and the control. Replace the
component body from `const [best, ...rest] = doc.passages;` down to the closing
`</article>`:

```tsx
  const [best, ...rest] = doc.passages;
  const [expanded, setExpanded] = useState(false);
  const terms = useMemo(() => queryTerms(query), [query]);
  // Only offer the control when something is actually hidden — an "expand"
  // that does nothing is worse than none.
  const canExpand = doc.passages.some(
    (p) => previewWindow(p.text, terms).text.length < p.text.length,
  );
  return (
    <article className="grp grp-passage">
      <button type="button" className="doc quoterow" onClick={() => onOpenPassage(best.chunk_id)}>
        <span className="doc-pub">{publisherLabel(doc.publisher)}</span>
        <div className="doc-main">
          <Quote text={best.text} terms={terms} expanded={expanded} />
        </div>
        <span className="doc-pill">
          {best.page === null ? "no page" : `p. ${best.page}`}
          <span className="go" aria-hidden="true">
            →
          </span>
        </span>
      </button>
      <div className="ctx">
        <div className="ctx-row">
          <span className="doc-pub">{publisherLabel(doc.publisher)}</span>
          <span className="badge">{doc.doc_title}</span>
          <span className="spacer" />
          {canExpand && (
            <button
              type="button"
              className={expanded ? "grp-more open" : "grp-more"}
              aria-expanded={expanded}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show less" : "Show full passage"}
            </button>
          )}
          {rest.length > 0 && (
            <button
              type="button"
              className={trayOpen ? "grp-more open" : "grp-more"}
              aria-expanded={trayOpen}
              onClick={onToggleTray}
            >
              More from this document <ChevronIcon />
            </button>
          )}
        </div>
        {trayOpen && rest.length > 0 && (
          <div className="tray open">
            {rest.map((p) => (
              <PassageRow
                key={p.chunk_id}
                passage={p}
                terms={terms}
                expanded={expanded}
                onOpen={onOpenPassage}
              />
            ))}
          </div>
        )}
      </div>
    </article>
  );
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && npx vitest run src/components/PassageCard.test.tsx`
Expected: PASS.

- [ ] **Step 5: Run the whole webapp suite and type-check**

Run: `cd webapp && npx vitest run && npx tsc -b`
Expected: all specs pass, `tsc -b` exit 0. `Search.test.tsx` fixtures may need
`text` added to their `SearchResult` objects — add it, do not weaken assertions.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/components/PassageCard.tsx webapp/src/components/PassageCard.test.tsx webapp/src/pages/Search.test.tsx
git commit -m "feat(search): render the preview window and expand in place

The card marks the analyst's words and expands to the full passage with no
second fetch. Expansion is card-level because the rows are real buttons and a
nested button is invalid HTML."
```

---

## Track B — Book sections

### Task 5: Derive which book a section belongs to

**Files:**
- Create: `app/book_sections.py`
- Test: `tests/test_book_sections.py`

**Interfaces:**
- Produces: `section_of(doc_type: str | None, source_url: str | None) -> str | None`
  — `"Baseline"`, `"Appropriations Report"`, or `None` for every document that
  is not one of the five section types (or whose URL cannot be read).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_book_sections.py`:

```python
"""The parent-book derivation for JLBC book sections (spec B1-B2)."""
import pytest

from app.book_sections import SECTION_DOC_TYPES, section_of


def test_the_five_section_types_are_exactly_these():
    assert SECTION_DOC_TYPES == frozenset(
        {"detailed-list-pdf", "s-pdf", "bd-pdf", "bh-pdf", "topic-pdf"}
    )


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.azjlbc.gov/22baseline/473.pdf", "Baseline"),
        ("https://www.azjlbc.gov/12book1/s1.pdf", "Baseline"),
        ("https://www.azjlbc.gov/25ar/apprpttoc.pdf", "Appropriations Report"),
        ("https://www.azjlbc.gov/05app/bd10.pdf", "Appropriations Report"),
    ],
)
def test_the_book_directory_in_the_source_url_names_the_parent(url, expected):
    assert section_of("s-pdf", url) == expected


def test_a_document_that_is_not_a_section_is_never_folded():
    assert section_of("approps-per-agency", "https://www.azjlbc.gov/25ar/adc.pdf") is None
    assert section_of("afr", "https://gao.az.gov/afr.pdf") is None
    assert section_of(None, "https://www.azjlbc.gov/25ar/x.pdf") is None


def test_an_unreadable_url_folds_nothing_rather_than_guessing():
    # familyOf's contract (spec B8): a document we cannot place still renders
    # under its own doc_type rather than being dropped or mis-filed.
    assert section_of("s-pdf", None) is None
    assert section_of("s-pdf", "https://example.org/whatever.pdf") is None


# The 21 documents whose doc_id says approps and whose source_url says
# baseline -- the make_doc_id family collisions STATUS.md records. A
# doc_id-based implementation passes every other test in this file and fails
# these, which is exactly why they are named individually (spec B2).
COLLISIONS = [
    ("jlbc-approps-fy2022-473", "https://www.azjlbc.gov/22baseline/473.pdf"),
    ("jlbc-approps-fy2022-497", "https://www.azjlbc.gov/22baseline/497.pdf"),
    ("jlbc-approps-fy2023-467", "https://www.azjlbc.gov/23baseline/467.pdf"),
    ("jlbc-approps-fy2024-495", "https://www.azjlbc.gov/24baseline/495.pdf"),
    ("jlbc-approps-fy2025-514", "https://www.azjlbc.gov/25baseline/514.pdf"),
    ("jlbc-approps-fy2026-487", "https://www.azjlbc.gov/26baseline/487.pdf"),
    ("jlbc-approps-fy2027-502", "https://www.azjlbc.gov/27baseline/502.pdf"),
    ("jlbc-approps-fy2027-522", "https://www.azjlbc.gov/27baseline/522.pdf"),
]


@pytest.mark.parametrize("doc_id,url", COLLISIONS)
def test_a_mis_minted_doc_id_does_not_decide_the_parent(doc_id, url):
    assert doc_id.startswith("jlbc-approps-")
    assert section_of("detailed-list-pdf", url) == "Baseline"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=$PWD uv run pytest tests/test_book_sections.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.book_sections'`.

- [ ] **Step 3: Implement**

Create `app/book_sections.py`:

```python
"""Which JLBC book is a section a section OF? (spec B1-B2)

WHY this exists: 647 documents render under raw machine slugs -- "FY 2027
s-pdf" beside "FY 2027 Baseline" -- as if they were report families. They are
not. The doc_id stems are literally `bd1..bd10`, `bh11`, `s1`, and the
table-of-contents titles carry the matching page references ("Summary of Total
Spending Authority ... BD-10"). They are JLBC's own PRINTED PAGE-NUMBER
PREFIXES: BD-x and BH-x are page ranges in the Appropriations Report, S-x is
the Baseline's summary section. `ingest/lance_writer.py` already says so -- the
`-pdf` suffix is "a corpus-internal marker for which JLBC index page a document
came off, not something an analyst should ever read."

WHY source_url and not doc_id, which is the obvious choice: measured against
all 647, the doc_id prefix PARSES for 647 and is WRONG for 21 of them. Those 21
are the `make_doc_id` family collisions STATUS.md records -- Baseline sections
minted with an approps doc_id, e.g. `jlbc-approps-fy2022-497`, titled "General
Fund Revenue -- FY 2022 Baseline", living at azjlbc.gov/22baseline/497.pdf.
"647 of 647 parse" is a production count; the error count is what mattered.

source_url is the only independent evidence -- the address JLBC actually
published the section at. Measured: 647/647 have one, 647/647 parse, and ZERO
disagree with the document's own title. Split: Appropriations Report 389,
Baseline 258.

This does NOT repair the 21 doc_ids. Re-minting them re-points chunk_ids and
eval ground truth; that is its own work with its own re-ingest question.

Design: docs/superpowers/specs/2026-08-11-budget-docs-highlighting-and-book-sections-design.md
"""
from __future__ import annotations

import re

# The five doc_types that are book SECTIONS rather than document types. Any
# other doc_type is left entirely alone -- this module only ever folds these.
SECTION_DOC_TYPES: frozenset[str] = frozenset(
    {"detailed-list-pdf", "s-pdf", "bd-pdf", "bh-pdf", "topic-pdf"}
)

# JLBC's own directory naming on azjlbc.gov, verified against all 647 section
# URLs in the live corpus: `22baseline`, `12book1` (the older Baseline
# spelling), `25ar` and `05app` (both Appropriations Report).
_BOOK_DIR = re.compile(r"azjlbc\.gov/\d{2}(baseline|book\d*|ar|app)\b", re.I)

_FAMILY = {
    "baseline": "Baseline",
    "book": "Baseline",
    "ar": "Appropriations Report",
    "app": "Appropriations Report",
}


def section_of(doc_type: str | None, source_url: str | None) -> str | None:
    """The report family this document is a SECTION of, or None.

    None means "not a section" -- either the doc_type is a real document type,
    or the URL cannot be read. Returning None rather than guessing keeps
    `familyOf`'s contract (spec B8): a document we cannot place still renders
    under its own doc_type instead of being dropped or mis-filed.
    """
    if doc_type not in SECTION_DOC_TYPES or not source_url:
        return None
    m = _BOOK_DIR.search(source_url)
    if not m:
        return None
    key = m.group(1).lower()
    # `book1`, `book2` -> `book`; the digit is the volume, not the family.
    return _FAMILY.get(re.sub(r"\d+$", "", key))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD uv run pytest tests/test_book_sections.py -v`
Expected: PASS, all cases.

- [ ] **Step 5: Verify against the LIVE corpus, not just fixtures**

Run:

```bash
JLBC_DATA_DIR=$PWD/data/insight-data PYTHONPATH=$PWD uv run python -c "
from app.book_sections import SECTION_DOC_TYPES, section_of
from store.documents import load_documents
import collections
docs = load_documents()
raw = {k: v for k, v in docs.items() if v.get('doc_type') in SECTION_DOC_TYPES}
fam = collections.Counter(section_of(v.get('doc_type'), v.get('source_url')) for v in raw.values())
print('sections:', len(raw), dict(fam))
print('unplaced:', fam.get(None, 0))
"
```

Expected exactly: `sections: 647 {'Appropriations Report': 389, 'Baseline': 258}`
and `unplaced: 0`. **If any document is unplaced, stop and report it** — the
spec's B1 claim that folding orphans nothing depends on this number being zero.

- [ ] **Step 6: Commit**

```bash
git add app/book_sections.py tests/test_book_sections.py
git commit -m "feat(corpus): derive a section's parent book from its source URL

647 documents render under raw slugs; bd/bh/s are JLBC's own printed page
prefixes, not document types. The parent comes from source_url: the doc_id
parses for all 647 and is WRONG for 21 of them, the make_doc_id collisions
STATUS.md records. Measured 389 approps / 258 baseline, 0 unplaced."
```

---

### Task 6: Serve `section_of` on the browse listing

**Files:**
- Modify: `app/routes/corpus.py` (the row dict in `document_listing`)
- Modify: `webapp/src/api.ts` (`CorpusDocument`)
- Test: `tests/test_corpus_documents_route.py`

**Interfaces:**
- Consumes: `app.book_sections.section_of` (Task 5).
- Produces: `CorpusDocument.section_of: string | null`.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_corpus_documents_route.py`:

```python
def test_listing_rows_say_which_book_a_section_belongs_to(tmp_path, monkeypatch):
    """Folding happens in the browser, but the DERIVATION is server-side so it
    has exactly one implementation -- the provider needs the same answer for
    content-mode filtering (spec B3/B5)."""
    rows = _listing_with(
        monkeypatch,
        tmp_path,
        {
            "jlbc-approps-fy2022-497": {
                "doc_type": "detailed-list-pdf",
                "fiscal_year": 2022,
                "publisher": "jlbc",
                "source_url": "https://www.azjlbc.gov/22baseline/497.pdf",
                "title": "General Fund Revenue — FY 2022 Baseline",
            },
            "jlbc-approps-fy2025-adc": {
                "doc_type": "approps-per-agency",
                "fiscal_year": 2025,
                "publisher": "jlbc",
                "source_url": "https://www.azjlbc.gov/25ar/adc.pdf",
                "title": "FY 2025 Appropriations Report — ADC",
            },
        },
    )
    by_id = {r["doc_id"]: r for r in rows}
    # The mis-minted doc_id says approps; the URL says baseline and wins.
    assert by_id["jlbc-approps-fy2022-497"]["section_of"] == "Baseline"
    # A real document type is never folded.
    assert by_id["jlbc-approps-fy2025-adc"]["section_of"] is None
```

Use whatever fixture helper the neighbouring tests in that file already use to
build a listing from a fake sidecar; `_listing_with` above is a stand-in name.
If none exists, follow the pattern of the closest existing test in the file.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=$PWD uv run pytest tests/test_corpus_documents_route.py -v`
Expected: FAIL with `KeyError: 'section_of'`.

- [ ] **Step 3: Implement**

In `app/routes/corpus.py`, add the import at the top with the others:

```python
from app.book_sections import section_of
```

and add one entry to the row dict, after `"doc_url"`:

```python
            "doc_url": meta.get("source_url"),
            # Which JLBC book this document is a SECTION of, or null when it
            # is a document type in its own right. 647 documents used to
            # render under raw slugs ("FY 2027 s-pdf") because their doc_type
            # is a page-number prefix, not a type. Derived HERE, not in the
            # browser, because app/search_provider.py needs the same answer
            # for content-mode filtering and two implementations of one
            # convention drift -- the same reason `terms` is computed here.
            "section_of": section_of(meta.get("doc_type"), meta.get("source_url")),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=$PWD uv run pytest tests/test_corpus_documents_route.py -v`
Expected: PASS.

- [ ] **Step 5: Add it to the TypeScript contract**

In `webapp/src/api.ts`, inside `interface CorpusDocument`, after `doc_url`:

```ts
  /** The JLBC book this document is a SECTION of ("Baseline",
   *  "Appropriations Report"), or null when it is a document type in its own
   *  right. Derived server-side from source_url — see app/book_sections.py
   *  for why the doc_id is not usable. */
  section_of: string | null;
```

Then add `section_of: null` to every `CorpusDocument` fixture in
`webapp/src/pages/Search.test.tsx` so the file type-checks.

- [ ] **Step 6: Type-check and commit**

Run: `cd webapp && npx tsc -b`
Expected: exit 0.

```bash
git add app/routes/corpus.py tests/test_corpus_documents_route.py webapp/src/api.ts webapp/src/pages/Search.test.tsx
git commit -m "feat(corpus): listing rows carry the section's parent book"
```

---

### Task 7: Exact family filtering in content mode

**Files:**
- Modify: `app/search_provider.py`
- Test: `tests/test_search_route.py`

**Interfaces:**
- Consumes: `app.book_sections.section_of` (Task 5).
- Produces: `SearchResult.section_of: string | null`, and the guarantee that a
  `doc_type` filter naming a section slug returns only that family's sections.

**The problem this solves (spec B5):** `detailed-list-pdf` splits 255 approps /
45 baseline and `topic-pdf` splits 14 / 6. A "Baseline" filter expands to
`detailed-list-pdf`, which would pull in up to 269 Appropriations Report
sections. The provider already reads the documents sidecar per result
(`self._info(c.doc_id)`), so it can compute the exact family and drop the
leakage. This is `app/`, not `retrieval/` — **no eval gate, no ranking change.**

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_search_route.py`:

```python
def test_results_carry_the_section_parent(monkeypatch):
    client = _client_with_chunks(monkeypatch, [_chunk(doc_type="s-pdf")])
    row = client.post("/api/search", json={"query": "x"}).json()["results"][0]
    assert "section_of" in row


def test_a_family_filter_does_not_leak_the_other_book_s_sections(monkeypatch):
    """`detailed-list-pdf` belongs to BOTH books, so a doc_type filter alone
    cannot express "Baseline sections". The provider filters exactly."""
    client = _client_with_chunks(
        monkeypatch,
        [
            _chunk(chunk_id="a", doc_id="base-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/22baseline/473.pdf"),
            _chunk(chunk_id="b", doc_id="appr-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/05app/302.pdf"),
        ],
    )
    body = client.post(
        "/api/search",
        json={"query": "x", "filters": {"doc_type": ["baseline-per-agency", "detailed-list-pdf"],
                                        "section_family": "Baseline"}},
    ).json()
    assert [r["chunk_id"] for r in body["results"]] == ["a"]


def test_no_family_filter_means_no_dropping(monkeypatch):
    """Over-inclusion is a visible wrong; removing a match the reader did not
    exclude is the forbidden one (spec B6)."""
    client = _client_with_chunks(
        monkeypatch,
        [
            _chunk(chunk_id="a", doc_id="base-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/22baseline/473.pdf"),
            _chunk(chunk_id="b", doc_id="appr-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/05app/302.pdf"),
        ],
    )
    body = client.post("/api/search", json={"query": "x"}).json()
    assert {r["chunk_id"] for r in body["results"]} == {"a", "b"}
```

Extend the file's chunk fixture helper so `_chunk` accepts `source_url` and the
fake documents sidecar returns it, mirroring how `doc_url` is already faked.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=$PWD uv run pytest tests/test_search_route.py -v`
Expected: FAIL — `section_of` is absent and `section_family` is ignored.

- [ ] **Step 3: Accept the filter on the route**

In the `/api/search` request model (`app/routes/search.py`'s filters model, or
wherever `SearchFilters` is validated), add an optional field:

```python
    # Which BOOK's sections to keep when the doc_type list names a section
    # slug that belongs to both books (spec B5). Not a retrieval filter -- it
    # is applied by the provider after ranking, from the documents sidecar.
    section_family: str | None = None
```

Keep the existing validation posture of that model (an unknown value must not
500; it simply matches nothing, same as any other filter value).

- [ ] **Step 4: Implement in the provider**

In `app/search_provider.py`, import the derivation:

```python
from app.book_sections import section_of
```

In `LanceSearchProvider.search`, add `section_of` to the emitted dict, beside
`doc_meta`:

```python
                "doc_meta": info["meta"],
                # Which JLBC book this passage's document is a section of, or
                # null. Same derivation the browse listing uses.
                "section_of": section_of(c.doc_type, info["url"]),
```

Then, after building the rows, drop cross-family leakage:

```python
        wanted = filters.get("section_family")
        if wanted:
            # `detailed-list-pdf` belongs to BOTH books (255 approps / 45
            # baseline), so a doc_type filter alone cannot express "Baseline
            # sections" and would leak up to 269 documents. Dropping here
            # removes only what the reader explicitly filtered out -- that is
            # honouring a filter, not losing a match. Applied ONLY when the
            # filter is present, so an unfiltered search never loses a row.
            rows = [r for r in rows if r["section_of"] in (None, wanted)]
```

Note `r["section_of"] in (None, wanted)`: a document that is not a section at
all (an agency page) must not be dropped by a section filter — the reader
picked a family, and the family's agency pages belong to it.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=$PWD uv run pytest tests/test_search_route.py -v`
Expected: PASS.

- [ ] **Step 6: MEASURE the over-fetch factor — do not guess it**

Filtering shrinks the pool after ranking, so a filtered search can return fewer
rows than it promised. Measure the real yield:

```bash
JLBC_DATA_DIR=$PWD/data/insight-data PYTHONPATH=$PWD uv run python -c "
from app.book_sections import section_of
from retrieval.pipeline import RetrievalRequest, retrieve
from store.documents import load_documents
docs = load_documents()
QS = ['capital outlay', 'general fund revenue', 'detailed list of changes',
      'summary of rent charges', 'budget stabilization fund']
for want in ('Baseline', 'Appropriations Report'):
    kept = []
    for q in QS:
        r = retrieve(RetrievalRequest(query=q, top_k=20,
                     doc_type=['detailed-list-pdf', 'topic-pdf']))
        k = sum(1 for c in r.chunks
                if section_of(c.doc_type, (docs.get(c.doc_id) or {}).get('source_url')) in (None, want))
        kept.append((len(r.chunks), k))
    print(want, kept)
"
```

Record the worst-case yield in a WHY comment at the over-fetch constant, then
set the provider's internal `top_k` for a family-filtered search to
`ceil(top_k / worst_case_yield)`, capped so it never exceeds the pipeline's own
limits. **If the measured yield is above ~0.9 in every case, do NOT add an
over-fetch** — record that measurement in the comment instead and leave the
code simpler.

- [ ] **Step 7: Commit**

```bash
git add app/search_provider.py app/routes/search.py tests/test_search_route.py
git commit -m "feat(search): exact family filtering for book sections

detailed-list-pdf belongs to both books, so a doc_type filter alone would
leak up to 269 approps sections into a Baseline filter. The provider already
reads the sidecar per result, so it filters exactly -- app/, not retrieval/,
so no eval gate and no ranking change."
```

---

### Task 8: Fold the sections into their books on the browse page

**Files:**
- Modify: `webapp/src/reportFamilies.ts` (`familyOf`)
- Modify: `webapp/src/pages/Search.tsx` (`groupCorpus`, `typeOptions`)
- Test: `webapp/src/pages/Search.test.tsx`

**Interfaces:**
- Consumes: `CorpusDocument.section_of` (Task 6).
- Produces: `familyOf(docType: string, sectionOf?: string | null): string`.

- [ ] **Step 1: Write the failing tests**

Add to `webapp/src/pages/Search.test.tsx`:

```tsx
test("no raw machine slug appears as a report family", async () => {
  // 647 documents used to render as "FY 2027 s-pdf" beside "FY 2027 Baseline".
  // bd/bh/s are JLBC's printed page-number prefixes, not document types.
  renderSearchWith([
    corpusDoc({ doc_id: "jlbc-baseline-fy2027-s1", doc_type: "s-pdf",
                fiscal_year: 2027, section_of: "Baseline",
                title: "Statement of General Fund Revenues — FY 2027 Baseline" }),
    corpusDoc({ doc_id: "jlbc-baseline-fy2027-ahcccs", doc_type: "baseline-per-agency",
                fiscal_year: 2027, section_of: null,
                title: "FY 2027 Baseline — AHCCCS" }),
  ]);
  expect(await screen.findByText("FY 2027 Baseline")).toBeInTheDocument();
  expect(screen.queryByText(/s-pdf/)).not.toBeInTheDocument();
});

test("a section is COUNTED under its parent book, not dropped", async () => {
  // The counts describe what renders (spec B7). Folding must move a document,
  // never delete one -- documents were once counted but never displayed.
  renderSearchWith([
    corpusDoc({ doc_id: "a", doc_type: "s-pdf", fiscal_year: 2027, section_of: "Baseline" }),
    corpusDoc({ doc_id: "b", doc_type: "baseline-per-agency", fiscal_year: 2027, section_of: null }),
  ]);
  const rail = await screen.findByRole("group", { name: /document type/i });
  expect(within(rail).getByText(/Baseline/)).toBeInTheDocument();
  expect(within(rail).getByText("2")).toBeInTheDocument();
});

test("a doc_type nobody has named still renders under its own slug", async () => {
  // familyOf's contract survives (spec B8). This behaviour was itself a bug
  // fix -- such documents used to be counted and never shown.
  renderSearchWith([
    corpusDoc({ doc_id: "z", doc_type: "brand-new-type", fiscal_year: 2027, section_of: null }),
  ]);
  expect(await screen.findByText(/brand-new-type/)).toBeInTheDocument();
});
```

Use the file's existing render/fixture helpers; `renderSearchWith` and
`corpusDoc` are stand-in names for whatever it already provides.

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && npx vitest run src/pages/Search.test.tsx`
Expected: FAIL — `s-pdf` still renders as its own family.

- [ ] **Step 3: Widen `familyOf`**

In `webapp/src/reportFamilies.ts`, replace `familyOf`:

```ts
/** The family name for a document.
 *
 *  `sectionOf` wins when present: five doc_types (`s-pdf`, `bd-pdf`,
 *  `bh-pdf`, `detailed-list-pdf`, `topic-pdf`) are not document types at all
 *  but JLBC's own printed page-number prefixes, so which book they belong to
 *  cannot be read off the doc_type — `detailed-list-pdf` splits 255
 *  Appropriations Report / 45 Baseline. The server derives it from the
 *  document's source URL (app/book_sections.py) so there is one
 *  implementation, not one per language.
 *
 *  Otherwise unknown slugs become their own family under the raw slug —
 *  honest (nothing invented) and future-proof (a new doc_type still groups,
 *  it just isn't prettified until someone names it here). */
export function familyOf(docType: string, sectionOf?: string | null): string {
  return sectionOf ?? FAMILY_OF_DOC_TYPE[docType] ?? docType;
}
```

- [ ] **Step 4: Pass the field at both call sites**

In `webapp/src/pages/Search.tsx`, in `groupCorpus`:

```ts
    const family = familyOf(d.doc_type, d.section_of);
```

and in `typeOptions`:

```ts
  const typeOptions = useMemo<MultiSelectOption[]>(() => {
    const present = orderFamilies([
      ...new Set(docs.map((d) => familyOf(d.doc_type, d.section_of))),
    ]);
    return present.map((f) => ({
      key: f,
      label: f,
      count: docs.filter((d) => familyOf(d.doc_type, d.section_of) === f).length,
    }));
  }, [docs]);
```

Search `webapp/src/` for every other `familyOf(` call and pass `section_of`
there too — the second parameter is optional, so a missed call site compiles
and silently keeps the old behaviour.

- [ ] **Step 5: Carry the family into content-mode filters**

In `webapp/src/search/contentSearch.ts`, `toSearchFilters` must send the new
`section_family` so Task 7's exact filtering engages. Change its signature to
take the selected families and set the field when exactly one book family is
selected:

```ts
export function toSearchFilters(
  types: ReadonlySet<string>,
  years: ReadonlySet<number>,
): SearchFilters {
  const filters: SearchFilters = {};
  if (types.size) {
    filters.doc_type = [...types].flatMap(slugsForFamily);
    // `detailed-list-pdf` belongs to BOTH books, so the slug list alone
    // cannot say which one. Send the family when exactly one is selected;
    // with two selected there is nothing to exclude anyway.
    const books = [...types].filter((t) => t === "Baseline" || t === "Appropriations Report");
    if (books.length === 1) filters.section_family = books[0];
  }
  if (years.size) {
    const real = [...years].filter((y) => y !== 0);
    if (real.length) filters.fiscal_year = real;
  }
  return filters;
}
```

Add `section_family?: string` to `SearchFilters` in `webapp/src/api.ts`, and
extend `slugsForFamily` so the two book families include their section slugs —
otherwise a Baseline filter never reaches the sections at all.

**The section slugs must NOT be hardcoded here.** `app/book_sections.py`
already holds that list as `SECTION_DOC_TYPES`, and a second copy in
TypeScript is precisely the two-lists-that-drift bug this project's Global
Constraints forbid. Derive them from the listing the browser already loaded —
every section document carries a non-null `section_of`, so its `doc_type` is a
section slug by definition. Add to `webapp/src/reportFamilies.ts`:

```ts
/** The doc_type slugs that are book SECTIONS, derived from the corpus itself.
 *
 *  WHY derived and not written down: `app/book_sections.py` already owns that
 *  vocabulary (`SECTION_DOC_TYPES`), and a second hand-maintained copy here
 *  would silently stop matching the day a sixth section type is ingested. A
 *  document the server marked with `section_of` HAS a section doc_type, by
 *  definition — so the listing already answers the question. */
export function sectionSlugsFrom(
  docs: readonly { doc_type: string; section_of: string | null }[],
): string[] {
  return [...new Set(docs.filter((d) => d.section_of).map((d) => d.doc_type))];
}

/** Every doc_type slug that belongs to a family — the inverse of `familyOf`.
 *
 *  `sectionSlugs` (from `sectionSlugsFrom`) joins the two BOOK families:
 *  `detailed-list-pdf` and `topic-pdf` genuinely occur under both, and the
 *  server's `section_family` filter is what makes the result exact. */
export function slugsForFamily(family: string, sectionSlugs: readonly string[] = []): string[] {
  const slugs = Object.entries(FAMILY_OF_DOC_TYPE)
    .filter(([, name]) => name === family)
    .map(([slug]) => slug);
  if (family === "Baseline" || family === "Appropriations Report") {
    return [...slugs, ...sectionSlugs];
  }
  return slugs.length ? slugs : [family];
}
```

`toSearchFilters` gains the same trailing parameter and passes it through:

```ts
export function toSearchFilters(
  types: ReadonlySet<string>,
  years: ReadonlySet<number>,
  sectionSlugs: readonly string[] = [],
): SearchFilters {
  const filters: SearchFilters = {};
  if (types.size) {
    filters.doc_type = [...types].flatMap((t) => slugsForFamily(t, sectionSlugs));
    const books = [...types].filter((t) => t === "Baseline" || t === "Appropriations Report");
    if (books.length === 1) filters.section_family = books[0];
  }
  if (years.size) {
    const real = [...years].filter((y) => y !== 0);
    if (real.length) filters.fiscal_year = real;
  }
  return filters;
}
```

Its caller in `webapp/src/pages/Search.tsx` computes the set once from the
loaded listing — `useMemo(() => sectionSlugsFrom(docs), [docs])` — and passes
it. Add a test pinning that the derivation comes from the data:

```ts
test("section slugs come from the corpus, never from a hardcoded list", () => {
  const docs = [
    { doc_type: "s-pdf", section_of: "Baseline" },
    { doc_type: "brand-new-section-pdf", section_of: "Baseline" },
    { doc_type: "baseline-per-agency", section_of: null },
  ];
  // A section type nobody has written down anywhere still reaches the filter.
  expect(sectionSlugsFrom(docs).sort()).toEqual(["brand-new-section-pdf", "s-pdf"]);
});
```

Update the two `slugsForFamily` / `toSearchFilters` tests in
`contentSearch.test.ts` to the new expected values — they are pinning real
behaviour that is changing, so change the expectations, do not delete the tests.

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd webapp && npx vitest run && npx tsc -b`
Expected: PASS, exit 0.

- [ ] **Step 7: Commit**

```bash
git add webapp/src/reportFamilies.ts webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx webapp/src/search/contentSearch.ts webapp/src/search/contentSearch.test.ts webapp/src/api.ts
git commit -m "feat(docs-page): fold book sections into their parent book

647 documents rendered as 'FY 2027 s-pdf' beside 'FY 2027 Baseline'. They are
sections of those books -- bd/bh/s are JLBC's printed page prefixes. familyOf
now takes the server-derived parent, and unknown slugs still render."
```

---

### Task 9: Two groups in a book's tray

**Files:**
- Modify: `webapp/src/pages/Search.tsx` (the family card's tray)
- Test: `webapp/src/pages/Search.test.tsx`

**Interfaces:**
- Consumes: `CorpusDocument.section_of` (Task 6).
- Produces: nothing later tasks depend on.

**Why (spec B4):** books gain 20–24 sections against the 112–150 agency pages
they already carry. Twenty topical sections dropped into a list of a hundred
and fifty agency entries are buried, and "Capital Outlay" and "General Fund
Revenue" are exactly the cross-cutting pages an analyst hunts by name. It also
mirrors how the book is printed: the BD/BH/S pages are a front section.

- [ ] **Step 1: Write the failing test**

Add to `webapp/src/pages/Search.test.tsx`:

```tsx
test("a book's tray separates summary sections from agency pages", async () => {
  renderSearchWith([
    corpusDoc({ doc_id: "s1", doc_type: "s-pdf", fiscal_year: 2027,
                section_of: "Baseline", title: "General Fund Revenue" }),
    corpusDoc({ doc_id: "ahcccs", doc_type: "baseline-per-agency", fiscal_year: 2027,
                section_of: null, title: "FY 2027 Baseline — AHCCCS" }),
  ]);
  await userEvent.click(await screen.findByRole("button", { name: /browse sections/i }));

  const summary = screen.getByRole("group", { name: /summary sections/i });
  expect(within(summary).getByText("General Fund Revenue")).toBeInTheDocument();

  const agencies = screen.getByRole("group", { name: /agency pages/i });
  expect(within(agencies).getByText(/AHCCCS/)).toBeInTheDocument();
});

test("a book with no summary sections shows no empty group", async () => {
  // An empty state must name only conditions that are true.
  renderSearchWith([
    corpusDoc({ doc_id: "ahcccs", doc_type: "baseline-per-agency", fiscal_year: 2027,
                section_of: null, title: "FY 2027 Baseline — AHCCCS" }),
  ]);
  await userEvent.click(await screen.findByRole("button", { name: /browse sections/i }));
  expect(screen.queryByRole("group", { name: /summary sections/i })).not.toBeInTheDocument();
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd webapp && npx vitest run src/pages/Search.test.tsx`
Expected: FAIL — the tray renders one flat list with no groups.

- [ ] **Step 3: Implement**

In `webapp/src/pages/Search.tsx`, inside the family card that renders the tray,
split the documents and render two labelled groups. Replace the single
document list with:

```tsx
{(() => {
  // Two groups, not one flat list (spec B4): a book gains 20-24 summary
  // sections against 112-150 agency pages, and "Capital Outlay" / "General
  // Fund Revenue" are exactly the cross-cutting pages an analyst hunts by
  // name -- buried in a list of a hundred and fifty agency entries. It also
  // mirrors how the book is printed: BD/BH/S are a front section.
  const sections = group.docs.filter((d) => d.section_of !== null);
  const agencies = group.docs.filter((d) => d.section_of === null);
  return (
    <>
      {sections.length > 0 && (
        <div role="group" aria-label="Summary sections" className="tray-group">
          <h4 className="tray-group-title">Summary sections</h4>
          {sections.map((d) => (
            <DocumentRow key={d.doc_id} doc={d} />
          ))}
        </div>
      )}
      {agencies.length > 0 && (
        <div role="group" aria-label="Agency pages" className="tray-group">
          <h4 className="tray-group-title">Agency pages</h4>
          {agencies.map((d) => (
            <DocumentRow key={d.doc_id} doc={d} />
          ))}
        </div>
      )}
    </>
  );
})()}
```

`DocumentRow` is a stand-in for whatever the file already uses to render one
document row inside a tray — reuse it exactly, do not write a second one.
Summary sections come first because they are the book's front matter.

Add minimal styles to the page's stylesheet for `.tray-group` and
`.tray-group-title`, following the conventions already in that file. **Do not
put `contain`, `container`, `container-type`, `content-visibility` or
`mask-image` on any scroll container** — that class of rule has already
silently clipped a tooltip on this page once.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd webapp && npx vitest run src/pages/Search.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/pages/Search.tsx webapp/src/pages/Search.test.tsx webapp/src/styles/app.css
git commit -m "feat(docs-page): separate summary sections from agency pages"
```

---

### Task 10: Full verification, in the suites and in the browser

**Files:** none changed unless a defect is found.

**Both defects this plan fixes shipped green under 2,999 passing tests. The
suites are necessary and are not sufficient. This task is not optional.**

- [ ] **Step 1: Run every suite**

```bash
JLBC_DATA_DIR=$PWD/data/insight-data PYTHONPATH=$PWD uv run pytest -q > /tmp/pytest.log 2>&1; echo "pytest exit: $?"
cd webapp && npx vitest run > /tmp/vitest.log 2>&1; echo "vitest exit: $?"; npx tsc -b; echo "tsc exit: $?"
```

Expected: all three exit 0. Capture the exit code directly — piping into `tail`
returns `tail`'s status and hides a failure.

- [ ] **Step 2: Confirm no eval was required**

Run: `git diff --stat origin/master -- retrieval/ ingest/ chunking/ citation/ harness/system-prompt.md`
Expected: empty. If it is not empty, the eval gate applies: run
`uv run python -m eval.run_eval` and commit the results with the diff.

- [ ] **Step 3: Build and run the app**

```bash
cd webapp && npm run build && cd ..
JLBC_DATA_DIR=$PWD/data/insight-data uv run uvicorn app.main:create_app --factory --port 9300
```

- [ ] **Step 4: Verify highlighting in a real browser**

At `http://127.0.0.1:9300/search`, search `how much did child care subsidy cost`
— a phrase no document title contains, so the page escalates to content search
after about two seconds. Confirm each of:

- Words are marked in the quoted passages. **Before this plan, zero cards
  marked anything.**
- Marks land on whole words, never inside longer ones.
- Function words like "did" and "much" mark too — that is the agreed rule.
- The preview starts at the beginning of the passage, showing the heading and
  the dollar figure.
- "Show full passage" expands in place, with no network request in the
  Network tab.
- Search something absurd (`zzzznotpresent budget`) and confirm passages render
  with **no marks at all** rather than anything invented.

- [ ] **Step 5: Verify the folding in a real browser**

- No `s-pdf`, `bd-pdf`, `bh-pdf`, `detailed-list-pdf` or `topic-pdf` appears
  anywhere on the page.
- The Document Type rail lists only real families.
- Open a Baseline or Appropriations Report year card: the tray shows **Summary
  sections** above **Agency pages**.
- Type `capital outlay` in the filter box and confirm those sections are still
  found — B6 is the hardest constraint and a title-filter regression is exactly
  what it forbids.
- Tick the **Baseline** type filter, then run a content search, and confirm no
  Appropriations Report section appears in the results.
- The page's document count still matches what renders.

- [ ] **Step 6: Shut the server down and commit any fixes**

Stop the dev server. Commit anything Steps 4–5 turned up, each with its own
WHY comment recording what the browser showed that the suites did not.

---

## Self-Review

**Spec coverage.** H1 → Task 2. H2 → Task 2. H3, H5 → Task 3. H4 → Task 3.
H6 → Tasks 3, 4. H7 → no code; enforced by Task 2 doing no backend term work,
and the rejected idf-lite scheme is recorded in the spec. H8 → Task 1. H9 →
Task 4. H10 → Task 4 (runs preserved). H11 → Task 1 leaves `snippet` intact.
B1, B2 → Task 5. B3 → Tasks 6, 8. B4 → Task 9. B5 → Task 7. B6 → Task 10
Step 5. B7 → Task 8 counting test. B8 → Tasks 5, 8 unknown-slug tests.

**Both spec "open questions" are closed by tasks:** the over-fetch factor is
measured in Task 7 Step 6 with an explicit instruction not to guess it; the
expand affordance is specified in Task 4.

**Known judgement calls the implementer should not silently reverse:**
- `queryTerms` drops single-character tokens. This is apostrophe debris
  (`state's` → `state` + `s`), not a stopword rule, and there is a test pinning
  that three-character domain terms survive.
- `previewWindow` adds a trailing ellipsis, which the spec does not require.
  It is honest about truncation and costs nothing.
- Task 7 keeps `section_of is None` documents under a family filter, because a
  book's agency pages belong to that book.
