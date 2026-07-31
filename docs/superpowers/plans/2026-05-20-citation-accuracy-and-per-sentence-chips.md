# Citation Accuracy + Per-Sentence Chips Implementation Plan

> **✓ SHIPPED (2026-05) against the retired `web/` + `mcp-server/` stack — historical; do not execute.**

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Drive silent-wrong-highlights to zero, surface the verbatim source text next to the PDF on every cite, render a chip after every sentence that asserts a cited claim (not just the first occurrence), and tighten the cite() contract so ambiguous quotes are rejected at validate time. Lands in a single ~1-2 day branch.

**Architecture:** Three layers change. (1) Sidecar `_validate_one_cite` adds a duplicate-quote rejection so quotes that appear multiple times in chunk.text are bounced back to the model with positions in the error. (2) Web `citation-extract.ts` `planCitationPlacements` walks every sentence (not just the first matching line) and places a chip on any sentence whose normalized text contains the claim_span OR a key-fact token (largest currency / percentage in claim_span). (3) `PdfPage.tsx` stops falling through to whole-page text search when a chunk bbox exists — bbox-restricted only, "couldn't pinpoint" badge on miss — and `PdfViewer.tsx` always renders a new `CitedTextPanel` below the rendered page that shows the verbatim chunk text with the cited span underlined. A small `HighlightStrategy` interface is introduced as a hook for the future #57 (chunk→PDF coord-map at ingest) follow-up.

**Tech Stack:** TypeScript / Next.js 15 + React 19 + vitest + JSDOM (web), Python 3.12 + FastAPI + pydantic + pytest (sidecar). pdfjs-dist on the web side. The plan is a single feature branch with one PR.

**Reference:** [docs/superpowers/specs/2026-05-20-citation-accuracy-and-per-sentence-chips-design.md](../specs/2026-05-20-citation-accuracy-and-per-sentence-chips-design.md)

---

## File Structure (created or modified)

### Sidecar (Section 3 of the spec)
- **Modify:** `retrieval/api.py` — `_validate_one_cite` gets a duplicate-quote check after `full_text.find(body.quote)`.
- **Modify:** `tests/test_api.py` — three new tests around the new rejection path.

### Web — placement (Section 1 of the spec)
- **Modify:** `web/lib/citation-extract.ts` — add `extractKeyFact`, extend `CitationPlacement` with optional `column`, rewrite `planCitationPlacements` to iterate sentences, extend `injectCiteSentinels` to honor `column`.
- **Modify:** `web/tests/citation-extract.test.ts` — new describe block "per-sentence placement" plus a small update to the existing placement assertions to tolerate the new optional `column` field.

### Web — PDF viewer (Section 2 of the spec)
- **Create:** `web/lib/highlight-strategy.ts` — `HighlightStrategy` interface + `TextLayerSearchStrategy` class wrapping the existing text-layer search. `CoordMapStrategy` placeholder (throws — populated when #57 ships).
- **Create:** `web/tests/highlight-strategy.test.ts` — unit tests with a fake pdfjs page proxy: happy path + strict-bbox miss returns `[]`.
- **Modify:** `web/components/PdfPage.tsx` — extract the inline `findTextRects` call into `TextLayerSearchStrategy.resolve(...)`; drop the `null` unrestricted-fallback entry from the `passes` array when a bbox exists; optional `strategy` prop accepted (defaults to `TextLayerSearchStrategy`).
- **Create:** `web/components/CitedTextPanel.tsx` — renders the chunk text with the cited span underlined; source label underneath.
- **Create:** `web/tests/cited-text-panel.test.tsx` — renders cited span with underline, missing-data fallback, non-PDF fallback.
- **Modify:** `web/components/PdfViewer.tsx` — render `CitedTextPanel` always-visible beneath the canvas inside `Loaded`. Forward an optional `coordMap` (always undefined today) to `PdfPage` to keep the #57 plumbing wired.
- **Modify:** `web/tests/pdf-viewer.test.tsx` — assert `CitedTextPanel` is in the DOM when a citation is selected.

### TypeScript type extension (the #57 hook)
- **Modify:** `web/lib/citation-extract.ts` — `ResolvedChunk` gains optional `coordMap?: ChunkCoordMap` field; new type `ChunkCoordMap` declared in `web/lib/highlight-strategy.ts` and re-exported from `citation-extract.ts`. Today: always undefined; the type is present so consumers stay stable when #57 ships.

---

## Task 0: Worktree setup

**Files:** none modified — sets up the workspace.

- [ ] **Step 1: Create the worktree**

Run:
```bash
git fetch origin && git pull origin master
mkdir -p ~/ask-the-budget-az-worktrees
git worktree add ~/ask-the-budget-az-worktrees/citation-accuracy -b citation-accuracy origin/master
cd ~/ask-the-budget-az-worktrees/citation-accuracy
```

Expected: a fresh worktree at `~/ask-the-budget-az-worktrees/citation-accuracy/` on a new `citation-accuracy` branch.

- [ ] **Step 2: Run baseline tests to confirm green start**

Run:
```bash
bash setup.sh --verify
```

Expected: pytest passes, two vitest suites pass. If any baseline test fails, STOP — investigate before proceeding so we never confuse a pre-existing failure with a regression we caused.

---

## Task 1: Sidecar — duplicate-quote rejection (failing test)

**Files:**
- Test: `tests/test_api.py` (modify — add new tests near existing `test_cite_validate_quote_not_found_returns_error`)

- [ ] **Step 1: Add the failing test**

Append after the existing `test_cite_validate_quote_not_found_returns_error` test in `tests/test_api.py`:

```python
def test_cite_validate_rejects_duplicate_quote(monkeypatch):
    """When the cited quote appears multiple times in chunk.text the
    sidecar bounces the cite back with positions, so the model picks a
    longer (unique) quote. Otherwise we silently bind to the first
    occurrence and the PDF highlight lands on the wrong dollar amount.
    """

    class FakeConn:
        def execute(self, sql, *_args, **_kw):
            is_preflight = "SELECT 1 FROM chunks" in str(sql)

            class _Cur:
                def fetchone(_self):
                    if is_preflight:
                        return (1,)
                    # Chunk text where "$5,000,000" appears twice.
                    return (
                        "Item A: $5,000,000 in FY 2025. Item B: $5,000,000 in FY 2026.",
                        "jlbc-baseline-book",
                    )

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("retrieval.api.psycopg.connect", lambda *_a, **_kw: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "quote": "$5,000,000",
                "claim_span": "$5,000,000 in FY 2025",
                "confidence": "verbatim",
            },
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "multiple times" in body["error"]
    # Both occurrence positions surfaced for the model.
    assert "positions:" in body["error"]


def test_cite_validate_unique_quote_still_validates(monkeypatch):
    """Regression — a quote appearing exactly once is not rejected by
    the new duplicate check."""

    class FakeConn:
        def execute(self, sql, *_args, **_kw):
            is_preflight = "SELECT 1 FROM chunks" in str(sql)

            class _Cur:
                def fetchone(_self):
                    if is_preflight:
                        return (1,)
                    return (
                        "The Aviation Fund balance was $123,456 as of June 30, 2024.",
                        "jlbc-baseline-book",
                    )

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("retrieval.api.psycopg.connect", lambda *_a, **_kw: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "quote": "$123,456",
                "claim_span": "$123,456",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is True, body


def test_cite_validate_duplicate_quote_caps_positions_at_3(monkeypatch):
    """A degenerate quote that appears many times surfaces up to 3
    positions then '…' — keeps the error string readable."""

    class FakeConn:
        def execute(self, sql, *_args, **_kw):
            is_preflight = "SELECT 1 FROM chunks" in str(sql)

            class _Cur:
                def fetchone(_self):
                    if is_preflight:
                        return (1,)
                    # "$X" appears 5 times.
                    return ("$X here $X there $X again $X once more $X last", "jlbc-baseline-book")

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    monkeypatch.setattr("retrieval.api.psycopg.connect", lambda *_a, **_kw: FakeConn())

    with TestClient(app) as client:
        resp = client.post(
            "/cite/validate",
            json={
                "chunk_id": "c1",
                "quote": "$X",
                "claim_span": "$X here",
                "confidence": "verbatim",
            },
        )

    body = resp.json()
    assert body["ok"] is False
    err = body["error"]
    # Three positions then ellipsis (more occurrences than we list).
    assert "positions:" in err
    assert "…" in err
    # Count commas inside the parenthesized positions list: 3 numbers
    # joined by ", " plus one ", …" tail = 3 commas inside the parens.
    inside = err.split("(", 1)[1].split(")", 1)[0]
    assert inside.count(",") == 3, inside
```

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
uv run pytest tests/test_api.py::test_cite_validate_rejects_duplicate_quote -v
```

Expected: FAIL — current sidecar binds to the first occurrence and returns `ok: true`, so the `assert body["ok"] is False` line fails.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_api.py
git commit -m "test(sidecar): add failing duplicate-quote rejection tests"
```

---

## Task 2: Sidecar — implement duplicate-quote rejection

**Files:**
- Modify: `retrieval/api.py:1085-1115` (`_validate_one_cite`)

- [ ] **Step 1: Add the duplicate check after the first `find`**

In `retrieval/api.py`, inside `_validate_one_cite`, between the existing `idx = full_text.find(body.quote)` block and the `resolved_span_start = idx` assignment, insert the duplicate-quote check. The full new shape of that section (replace `idx = full_text.find(body.quote)` through `resolved_span_end = idx + len(body.quote)`):

```python
        idx = full_text.find(body.quote)
        if idx < 0:
            return CiteValidateResponse(
                ok=False,
                error=(
                    "quote not found in chunk.text — the substring you "
                    "supplied as `quote` does not appear verbatim in the "
                    "chunk. Pick text that exists in the chunk (read the "
                    "retrieve() result's `text` field) or retrieve a "
                    "different chunk."
                ),
                chunk_text_length=length,
            )

        # Duplicate-quote check. When the model picks a quote that
        # appears in multiple places in chunk.text we silently bind to
        # the first occurrence today — which is how the PDF highlight
        # sometimes lands on the wrong dollar amount. Bounce the cite
        # back with positions so the model picks a longer / more
        # surrounding-context quote that's unique within the chunk.
        # We list up to 3 positions then `…` so the error stays readable
        # when the quote is degenerate (e.g. "$5M" appearing 20 times
        # in a per-agency summary).
        positions = [idx]
        next_pos = idx + 1
        while len(positions) < 3:
            found = full_text.find(body.quote, next_pos)
            if found == -1:
                break
            positions.append(found)
            next_pos = found + 1
        has_more = full_text.find(body.quote, positions[-1] + 1) != -1
        if len(positions) > 1:
            suffix = ", …" if has_more else ""
            pos_str = ", ".join(str(p) for p in positions) + suffix
            return CiteValidateResponse(
                ok=False,
                error=(
                    f"quote appears multiple times in chunk.text "
                    f"(positions: {pos_str}). Extend the quote with more "
                    "surrounding context so it's unique within this chunk."
                ),
                chunk_text_length=length,
            )

        resolved_span_start = idx
        resolved_span_end = idx + len(body.quote)
```

- [ ] **Step 2: Run the three new tests, confirm they PASS**

Run:
```bash
uv run pytest tests/test_api.py::test_cite_validate_rejects_duplicate_quote tests/test_api.py::test_cite_validate_unique_quote_still_validates tests/test_api.py::test_cite_validate_duplicate_quote_caps_positions_at_3 -v
```

Expected: all 3 PASS.

- [ ] **Step 3: Run the full cite_validate test family — no regressions**

Run:
```bash
uv run pytest tests/test_api.py -k cite_validate -v
```

Expected: all existing cite_validate tests still pass.

- [ ] **Step 4: Commit**

```bash
git add retrieval/api.py
git commit -m "feat(sidecar): reject duplicate-quote cites with positions in error

A quote that appears multiple times in chunk.text used to silently
bind to the first occurrence, which is how the PDF highlight sometimes
landed on the wrong dollar amount. Now the sidecar returns ok:false
with up to 3 positions in the error so the model picks a longer,
unique quote on retry."
```

---

## Task 3: Web — add `extractKeyFact` helper (failing test)

**Files:**
- Test: `web/tests/citation-extract.test.ts` (modify — new describe block)
- Code: `web/lib/citation-extract.ts` (modify — add new helper)

- [ ] **Step 1: Add the failing test**

In `web/tests/citation-extract.test.ts`, add a new describe block at end of file (before the final closing import or whatever section ends the file — append to bottom):

```typescript
import { extractKeyFact } from "../lib/citation-extract.js";

describe("extractKeyFact", () => {
  it("returns the longest currency token in claim_span", () => {
    expect(extractKeyFact("$3,300,000 for the Dark Sky Discovery Center"))
      .toBe("$3,300,000");
  });

  it("picks the longest of multiple currency tokens", () => {
    expect(extractKeyFact("Up from $5M to $123,456,789 in FY 2027"))
      .toBe("$123,456,789");
  });

  it("returns a percentage when no currency is present", () => {
    expect(extractKeyFact("an increase of 12.5% over the prior year"))
      .toBe("12.5%");
  });

  it("returns null when the claim has no currency or percentage", () => {
    expect(extractKeyFact("Aviation Fund growth in FY 2027")).toBeNull();
  });

  it("returns null for bare years and small integers (too noisy)", () => {
    expect(extractKeyFact("Section 9 of HB 2729 in 2027")).toBeNull();
  });

  it("matches '5 million' / '$5M' shorthand forms", () => {
    expect(extractKeyFact("about $5 million in carry-forward"))
      .toBe("$5 million");
    expect(extractKeyFact("about $5M in carry-forward")).toBe("$5M");
  });
});
```

Add `extractKeyFact` to the import statement at the top of the test file:

```typescript
import {
  buildConversationResolvedChunkMap,
  extractCitations,
  extractInlineCiteTags,
  extractKeyFact,
  findNormalizedMatch,
  formatCopyCitation,
  injectCiteSentinels,
  normalizeForMatch,
  planCitationPlacements,
  type Citation,
} from "../lib/citation-extract.js";
```

(Remove the bottom-of-file `import { extractKeyFact }` you wrote in the describe block — it goes in the top import block instead.)

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: FAIL — `extractKeyFact is not defined`.

- [ ] **Step 3: Implement `extractKeyFact`**

In `web/lib/citation-extract.ts`, add this function near the top of the file (after the type exports, before `parseRetrieveOutput`):

```typescript
/** Extract the "key fact" token from a claim_span — the load-bearing
 *  numeric figure that the citation is really about (e.g. a dollar
 *  amount or percentage). Returned by `planCitationPlacements` as a
 *  secondary placement key so sentences that restate a fact in
 *  different wording still get the citation's chip.
 *
 *  Returns null when there's nothing distinctive enough to safely match
 *  on. We intentionally do NOT match bare years or small integers —
 *  too many false positives in budget prose where years and small
 *  ordinals appear everywhere.
 *
 *  Currency match supports the dollar-amount-with-suffix shorthand
 *  the model often uses ("$5 million", "$5M") in addition to the
 *  long form ("$5,000,000"). Longest match wins so "$3,300,000" beats
 *  "$3,300" within the same claim_span. */
export function extractKeyFact(claimSpan: string): string | null {
  // Currency: $ followed by digits and optional thousand separators,
  // optionally trailed by a "million" / "billion" / "M" / "B" suffix.
  // The /g + reduce(longest) pattern handles "Up from $5M to $123,456,789"
  // by picking $123,456,789.
  const currency = claimSpan.match(
    /\$[\d][\d,.]*(?:\s?(?:million|billion|M|B))?/gi,
  );
  if (currency && currency.length > 0) {
    return currency.reduce((a, b) => (b.length > a.length ? b : a));
  }
  const pct = claimSpan.match(/\d+(?:\.\d+)?\s?%/);
  if (pct) return pct[0];
  return null;
}
```

- [ ] **Step 4: Run the test, confirm it PASSES**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: all six `extractKeyFact` tests PASS; no other tests broken.

- [ ] **Step 5: Commit**

```bash
git add web/lib/citation-extract.ts web/tests/citation-extract.test.ts
git commit -m "feat(web): add extractKeyFact helper for per-sentence chip placement

Pulls the load-bearing dollar amount or percentage out of a claim_span
so planCitationPlacements can place chips on later sentences that
restate the same fact in different wording. Bare years and small
integers are intentionally not matched (too noisy)."
```

---

## Task 4: Web — extend `CitationPlacement` + add `column` field, sentence iteration on claim_span

**Files:**
- Code: `web/lib/citation-extract.ts` (modify — extend `CitationPlacement` and `planCitationPlacements`)
- Test: `web/tests/citation-extract.test.ts` (modify — add per-sentence tests)

- [ ] **Step 1: Add the failing test — same claim across two sentences → two placements**

Add a new describe block at end of `web/tests/citation-extract.test.ts`:

```typescript
describe("planCitationPlacements per-sentence iteration", () => {
  it("places a chip on EVERY sentence whose normalized text contains the claim_span", () => {
    const content = [
      "JLBC reports a $3.3M decrease for the Dark Sky Discovery Center.",
      "The $3.3M removes one-time funding from FY 2027.",
    ].join("\n");
    const placements = planCitationPlacements(content, [
      { claimSpan: "$3.3M" },
    ]);
    // Two placements for the SAME citation — one per matching sentence.
    expect(placements).toHaveLength(2);
    expect(placements[0]!.citationIndex).toBe(0);
    expect(placements[1]!.citationIndex).toBe(0);
    expect(placements[0]!.lineIndex).toBe(0);
    expect(placements[1]!.lineIndex).toBe(1);
  });

  it("multiple sentences on the same line each get their own placement", () => {
    const content =
      "The Fund got $5M in FY25. The Fund also got $5M in FY26.";
    const placements = planCitationPlacements(content, [
      { claimSpan: "$5M" },
    ]);
    expect(placements).toHaveLength(2);
    // Both placements anchor to line 0 with different column offsets.
    expect(placements[0]!.lineIndex).toBe(0);
    expect(placements[1]!.lineIndex).toBe(0);
    expect(placements[0]!.column).not.toBe(placements[1]!.column);
  });

  it("falls back to (lineIndex: -1) when no sentence on any line matches", () => {
    const content = "Aviation Fund grew in FY 2027.";
    const placements = planCitationPlacements(content, [
      { claimSpan: "no such phrase" },
    ]);
    expect(placements).toHaveLength(1);
    expect(placements[0]!.lineIndex).toBe(-1);
  });
});
```

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: FAIL — current `planCitationPlacements` returns one placement per citation and doesn't produce the two-placement output the new tests expect. Also `placements[0]!.column` is `undefined`, failing the `not.toBe` assertion in the second test.

- [ ] **Step 3: Extend `CitationPlacement` and rewrite `planCitationPlacements`**

In `web/lib/citation-extract.ts`, replace the existing `CitationPlacement` interface and `planCitationPlacements` function with this version:

```typescript
/** Per-citation placement decision used by the renderer to inject
 *  chip sentinels into the markdown source. A single citation can
 *  produce MULTIPLE placements — one per sentence whose normalized
 *  text contains the citation's claim_span or its key-fact token. */
export interface CitationPlacement {
  /** Index in the citations array we were given. */
  citationIndex: number;
  /** Source-markdown line index this citation will anchor to, or -1
   *  when no line/sentence contained the claim_span (chip drops to
   *  end-of-content). */
  lineIndex: number;
  /** Column offset (in the ORIGINAL, non-normalized line) of the END
   *  of the matched sentence. When null, the sentinel goes at end-of-
   *  line (back-compat for tables and bullet lines where a sentence
   *  isn't a useful anchor). */
  column?: number | null;
}

/** Regex over a single markdown line that captures one sentence per
 *  match. Handles "claim.", "claim?", "claim!", optionally followed by
 *  a closing quote / paren / bracket. The trailing `|...$` catches a
 *  tail sentence with no terminating punctuation (the last fragment on
 *  the line, which we still want to consider for matching). */
const SENTENCE_RE = /[^.!?\n]+[.!?]+["')\]]*|[^.!?\n]+$/g;

/** Plan chip placements for each citation. Walks every line, then every
 *  sentence inside that line, and emits a CitationPlacement for any
 *  sentence whose normalized text contains the citation's claim_span.
 *  Table rows and bullet lines are treated as single sentences — we
 *  return one placement at the LINE level (no column) for those so the
 *  existing table-row carve-out in `injectCiteSentinels` keeps working.
 *
 *  Citations whose claim_span doesn't match any sentence on any line
 *  emit a single placement with lineIndex -1 (caller appends them at
 *  end of content as a fallback). */
export function planCitationPlacements(
  content: string,
  citations: { claimSpan: string }[],
): CitationPlacement[] {
  if (!content || citations.length === 0) return [];
  const lines = content.split("\n");
  const out: CitationPlacement[] = [];
  for (let i = 0; i < citations.length; i++) {
    const span = citations[i]!.claimSpan;
    if (!span) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
      continue;
    }
    const normSpan = normalizeForMatch(span).normalized;
    const trimmed = normSpan.replace(/^[\s.,;:!?]+|[\s.,;:!?]+$/g, "");
    if (!trimmed) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
      continue;
    }

    let anyMatched = false;
    for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
      const raw = lines[lineIdx]!;
      const isTableRow =
        /^\s*\|/.test(raw.trim()) && /\|\s*$/.test(raw.trim());
      // Table rows: treat the whole row as one sentence at line-level
      // anchoring (no column). The existing table carve-out in
      // injectCiteSentinels handles closing-pipe injection.
      if (isTableRow) {
        const normalizedLine = normalizeForMatch(raw).normalized;
        if (normalizedLine.includes(trimmed)) {
          out.push({ citationIndex: i, lineIndex: lineIdx, column: null });
          anyMatched = true;
        }
        continue;
      }

      // Walk sentences within this line. Each sentence gets matched
      // against the claim_span; matches emit one placement at the end
      // of the matched sentence.
      const matches = Array.from(raw.matchAll(SENTENCE_RE));
      if (matches.length === 0) continue;
      for (const m of matches) {
        const sentence = m[0];
        const sentenceStart = m.index!;
        const sentenceEndExclusive = sentenceStart + sentence.length;
        const normalizedSentence = normalizeForMatch(sentence).normalized;
        if (normalizedSentence.includes(trimmed)) {
          out.push({
            citationIndex: i,
            lineIndex: lineIdx,
            column: sentenceEndExclusive,
          });
          anyMatched = true;
        }
      }
    }

    if (!anyMatched) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
    }
  }
  return out;
}
```

- [ ] **Step 4: Run the new tests, confirm they PASS**

Run:
```bash
cd web && npm test -- citation-extract.test.ts -t "per-sentence iteration"
```

Expected: all 3 per-sentence tests PASS.

- [ ] **Step 5: Run the full citation-extract test file — check existing tests**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: existing placement tests now fail because their `expect(placements).toEqual([{ citationIndex: 0, lineIndex: 2 }])` doesn't account for the new `column` field. We'll fix those next.

- [ ] **Step 6: Update existing placement assertions for the new `column` field**

In `web/tests/citation-extract.test.ts`, replace the existing assertions in the `describe("planCitationPlacements + injectCiteSentinels", …)` block:

For the "anchors a paragraph claim to its source line" test, change:
```typescript
expect(placements).toEqual([{ citationIndex: 0, lineIndex: 2 }]);
```
to:
```typescript
expect(placements).toEqual([
  { citationIndex: 0, lineIndex: 2, column: expect.any(Number) },
]);
```

For the "appends unmatched citations to the end of content" test, change:
```typescript
expect(placements[0]?.lineIndex).toBe(-1);
```
(already passes — keep it).

For the "groups multiple citations on the same line in original order" test, no assertion on `placements` directly — only on `augmented`. Keep as is.

For the "anchors a table-row claim to the matching row" test, the assertion is `expect(placements[0]?.lineIndex).toBe(2)` — already passes since table-row placements set `column: null`. Keep as is.

For the "injects multiple sentinels inside the last cell for table-row claims" test — the assertion is on `augmented`, not `placements`. Keep as is.

- [ ] **Step 7: Run the full file again, confirm everything PASSES**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add web/lib/citation-extract.ts web/tests/citation-extract.test.ts
git commit -m "feat(web): per-sentence chip placement under claim_span match

planCitationPlacements now walks every sentence on every line (not
just the first matching line) and emits one CitationPlacement per
matching sentence. CitationPlacement gains an optional 'column' field
carrying the sentence-end offset so injectCiteSentinels can inject
the chip after the sentence's terminating punctuation rather than at
end-of-line. Table rows still anchor at line level (column: null)
since the row carve-out in injectCiteSentinels handles them."
```

---

## Task 5: Web — extend `injectCiteSentinels` to honor `column`

**Files:**
- Code: `web/lib/citation-extract.ts` (modify — extend `injectCiteSentinels`)
- Test: `web/tests/citation-extract.test.ts` (modify — add a sentence-injection test)

- [ ] **Step 1: Add the failing test**

In `web/tests/citation-extract.test.ts`, inside the `describe("planCitationPlacements + injectCiteSentinels", …)` block (or a new sibling describe), add:

```typescript
it("injects sentinels after each matching sentence, not just end-of-line", () => {
  const content = "The Fund got $5M in FY25. The Fund also got $5M in FY26.";
  const placements = planCitationPlacements(content, [
    { claimSpan: "$5M" },
  ]);
  const augmented = injectCiteSentinels(content, placements);
  // Chip appears after BOTH sentence-terminating periods, not just
  // at end-of-line. Sentinels grouped by citation index.
  expect(augmented).toBe(
    "The Fund got $5M in FY25. {{cite:0}} The Fund also got $5M in FY26. {{cite:0}}",
  );
});
```

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
cd web && npm test -- citation-extract.test.ts -t "after each matching sentence"
```

Expected: FAIL — current `injectCiteSentinels` injects at end-of-line only, so the output puts both sentinels at the very end.

- [ ] **Step 3: Extend `injectCiteSentinels`**

In `web/lib/citation-extract.ts`, replace the existing `injectCiteSentinels` function with:

```typescript
export function injectCiteSentinels(
  content: string,
  placements: CitationPlacement[],
): string {
  if (placements.length === 0) return content;
  const lines = content.split("\n");
  // Two buckets per line: end-of-line placements (column null) and
  // per-sentence placements (column set). End-of-line still goes
  // through the table-row carve-out; per-sentence injections splice
  // into the line at the sentence's end column. Sentence placements
  // are applied right-to-left so earlier column offsets stay valid.
  const eolPerLine = new Map<number, number[]>();
  const sentencePerLine = new Map<
    number,
    Array<{ column: number; citationIndex: number }>
  >();
  const unmatched: number[] = [];

  for (const p of placements) {
    if (p.lineIndex < 0 || p.lineIndex >= lines.length) {
      unmatched.push(p.citationIndex);
      continue;
    }
    if (p.column == null) {
      if (!eolPerLine.has(p.lineIndex)) eolPerLine.set(p.lineIndex, []);
      eolPerLine.get(p.lineIndex)!.push(p.citationIndex);
    } else {
      if (!sentencePerLine.has(p.lineIndex))
        sentencePerLine.set(p.lineIndex, []);
      sentencePerLine.get(p.lineIndex)!.push({
        column: p.column,
        citationIndex: p.citationIndex,
      });
    }
  }

  // Apply per-sentence injections first. Sort each line's list
  // descending by column so we splice from the right, which keeps
  // earlier column offsets pointing at the right characters.
  for (const [lineIdx, items] of sentencePerLine) {
    items.sort((a, b) => b.column - a.column);
    let line = lines[lineIdx]!;
    for (const it of items) {
      const sentinel = `{{cite:${it.citationIndex}}}`;
      // Insert " {{cite:N}}" immediately after the sentence's end
      // column. Adding a leading space keeps the chip visually
      // separated from the sentence's terminating punctuation.
      line = line.slice(0, it.column) + " " + sentinel + line.slice(it.column);
    }
    lines[lineIdx] = line;
  }

  // Then apply end-of-line / table-row injections (existing behavior).
  for (const [lineIdx, citIdxs] of eolPerLine) {
    const sentinels = citIdxs.map((i) => `{{cite:${i}}}`).join(" ");
    const raw = lines[lineIdx]!;
    const stripped = raw.replace(/\s+$/u, "");
    if (/^\s*\|/.test(stripped) && /\|\s*$/.test(stripped)) {
      // Table row: inject inside the last cell (existing carve-out).
      const closeIdx = stripped.lastIndexOf("|");
      const before = stripped.slice(0, closeIdx).replace(/\s+$/u, "");
      lines[lineIdx] =
        before + " " + sentinels + " " + stripped.slice(closeIdx);
    } else {
      // Non-table line: append at end of line.
      lines[lineIdx] = stripped + " " + sentinels;
    }
  }

  let result = lines.join("\n");
  if (unmatched.length > 0) {
    const sentinels = unmatched.map((i) => `{{cite:${i}}}`).join(" ");
    result += "\n\n" + sentinels;
  }
  return result;
}
```

- [ ] **Step 4: Run the new test, confirm it PASSES**

Run:
```bash
cd web && npm test -- citation-extract.test.ts -t "after each matching sentence"
```

Expected: PASS.

- [ ] **Step 5: Run the full citation-extract file — no regressions**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: all tests pass, including the existing table-row, end-of-line, and unmatched-fallback cases.

- [ ] **Step 6: Commit**

```bash
git add web/lib/citation-extract.ts web/tests/citation-extract.test.ts
git commit -m "feat(web): injectCiteSentinels honors per-sentence column

When a CitationPlacement has a non-null column the sentinel is spliced
in immediately after the sentence's terminating punctuation rather
than appended at end-of-line. Right-to-left application keeps earlier
column offsets valid. Table-row and end-of-line paths unchanged."
```

---

## Task 6: Web — key-fact-token placement rule

**Files:**
- Code: `web/lib/citation-extract.ts` (modify — extend `planCitationPlacements`)
- Test: `web/tests/citation-extract.test.ts` (modify — add a key-fact-token test)

- [ ] **Step 1: Add the failing test**

In `web/tests/citation-extract.test.ts`, inside the `describe("planCitationPlacements per-sentence iteration", …)` block, add:

```typescript
it("places a chip on a sentence whose wording differs but contains the key-fact token", () => {
  // Model emits claim_span = "$3,300,000 for the Dark Sky Discovery Center"
  // but the second sentence restates the fact in different prose. The
  // key-fact token ($3,300,000) is the bridge.
  const content = [
    "The Baseline cuts $3,300,000 for the Dark Sky Discovery Center.",
    "That $3,300,000 reduction removes one-time funding from FY 2027.",
  ].join("\n");
  const placements = planCitationPlacements(content, [
    { claimSpan: "$3,300,000 for the Dark Sky Discovery Center" },
  ]);
  expect(placements).toHaveLength(2);
  expect(placements[0]!.lineIndex).toBe(0);
  expect(placements[1]!.lineIndex).toBe(1);
});

it("anti-duplicate: a sentence covered by claim_span match isn't double-chipped via key fact", () => {
  // Sentence contains BOTH the literal claim_span AND the key-fact
  // token. Only one chip for this citation in that sentence.
  const content = "The Baseline cuts $3,300,000 for the Dark Sky Discovery Center.";
  const placements = planCitationPlacements(content, [
    { claimSpan: "$3,300,000 for the Dark Sky Discovery Center" },
  ]);
  expect(placements).toHaveLength(1);
});

it("does not match bare years as key facts", () => {
  // Year alone is too noisy to be a placement signal.
  const content = [
    "JLBC's FY 2027 baseline includes a $5M increase.",
    "Section 9 of HB 2729 in 2027 also references the increase.",
  ].join("\n");
  const placements = planCitationPlacements(content, [
    { claimSpan: "$5M increase in FY 2027" },
  ]);
  // Only the first sentence contains "$5M". The second's "2027" alone
  // is not a key-fact token, so it doesn't match.
  expect(placements).toHaveLength(1);
  expect(placements[0]!.lineIndex).toBe(0);
});
```

- [ ] **Step 2: Run the new tests, confirm they FAIL**

Run:
```bash
cd web && npm test -- citation-extract.test.ts -t "key-fact"
```

Expected: the first key-fact test FAILS — only one placement is returned because the second sentence doesn't contain the literal claim_span.

- [ ] **Step 3: Add the key-fact placement rule to `planCitationPlacements`**

In `web/lib/citation-extract.ts`, modify `planCitationPlacements` to also try key-fact-token matching after the claim_span pass. Specifically, replace the inner per-citation loop body (the section starting `let anyMatched = false;` through the `if (!anyMatched)` fallback) with:

```typescript
    let anyMatched = false;
    // First pass: claim_span match (sentence-level, existing rule).
    for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
      const raw = lines[lineIdx]!;
      const isTableRow =
        /^\s*\|/.test(raw.trim()) && /\|\s*$/.test(raw.trim());
      if (isTableRow) {
        const normalizedLine = normalizeForMatch(raw).normalized;
        if (normalizedLine.includes(trimmed)) {
          out.push({ citationIndex: i, lineIndex: lineIdx, column: null });
          anyMatched = true;
        }
        continue;
      }
      const matches = Array.from(raw.matchAll(SENTENCE_RE));
      if (matches.length === 0) continue;
      for (const m of matches) {
        const sentence = m[0];
        const sentenceStart = m.index!;
        const sentenceEndExclusive = sentenceStart + sentence.length;
        const normalizedSentence = normalizeForMatch(sentence).normalized;
        if (normalizedSentence.includes(trimmed)) {
          out.push({
            citationIndex: i,
            lineIndex: lineIdx,
            column: sentenceEndExclusive,
          });
          anyMatched = true;
        }
      }
    }

    // Second pass: key-fact-token match. Adds chips to sentences that
    // restate the citation's load-bearing figure in different wording.
    // We skip any sentence already covered by the claim_span pass (the
    // anti-duplicate rule).
    const keyFact = extractKeyFact(span);
    if (keyFact) {
      const normKeyFact = normalizeForMatch(keyFact).normalized;
      // Track (lineIdx, sentenceEnd) already placed in pass 1 so we
      // don't double-chip the same sentence.
      const alreadyPlacedSentences = new Set<string>();
      for (const p of out) {
        if (p.citationIndex !== i) continue;
        if (p.lineIndex < 0) continue;
        alreadyPlacedSentences.add(`${p.lineIndex}:${p.column ?? "eol"}`);
      }
      for (let lineIdx = 0; lineIdx < lines.length; lineIdx++) {
        const raw = lines[lineIdx]!;
        const isTableRow =
          /^\s*\|/.test(raw.trim()) && /\|\s*$/.test(raw.trim());
        if (isTableRow) continue; // table rows only match via claim_span
        const matches = Array.from(raw.matchAll(SENTENCE_RE));
        for (const m of matches) {
          const sentence = m[0];
          const sentenceStart = m.index!;
          const sentenceEndExclusive = sentenceStart + sentence.length;
          const sentenceKey = `${lineIdx}:${sentenceEndExclusive}`;
          if (alreadyPlacedSentences.has(sentenceKey)) continue;
          const normalizedSentence = normalizeForMatch(sentence).normalized;
          if (normalizedSentence.includes(normKeyFact)) {
            out.push({
              citationIndex: i,
              lineIndex: lineIdx,
              column: sentenceEndExclusive,
            });
            anyMatched = true;
          }
        }
      }
    }

    if (!anyMatched) {
      out.push({ citationIndex: i, lineIndex: -1, column: null });
    }
```

- [ ] **Step 4: Run the key-fact tests, confirm they PASS**

Run:
```bash
cd web && npm test -- citation-extract.test.ts -t "key-fact"
cd web && npm test -- citation-extract.test.ts -t "anti-duplicate"
cd web && npm test -- citation-extract.test.ts -t "bare years"
```

Expected: all 3 PASS.

- [ ] **Step 5: Run the full file — confirm no regressions**

Run:
```bash
cd web && npm test -- citation-extract.test.ts
```

Expected: every test passes.

- [ ] **Step 6: Commit**

```bash
git add web/lib/citation-extract.ts web/tests/citation-extract.test.ts
git commit -m "feat(web): key-fact-token placement rule with anti-duplicate

planCitationPlacements now runs a second pass after claim_span match
that places chips on sentences containing the citation's key-fact
token (largest currency or percentage in claim_span). Sentences
already chipped via the claim_span pass are excluded to avoid double
chips on the same sentence. Bare years aren't key facts (extractKeyFact
returns null) so they don't trigger the second pass."
```

---

## Task 7: Web — create `HighlightStrategy` interface and `TextLayerSearchStrategy`

**Files:**
- Create: `web/lib/highlight-strategy.ts`
- Create: `web/tests/highlight-strategy.test.ts`

- [ ] **Step 1: Write the failing test**

Create `web/tests/highlight-strategy.test.ts`:

```typescript
// Unit tests for the HighlightStrategy interface and the
// TextLayerSearchStrategy that wraps pdfjs text-layer search. The
// strategy abstraction is the seam where the future #57 coord-map
// strategy will plug in.

import { describe, expect, it } from "vitest";

import {
  TextLayerSearchStrategy,
  type ChunkCoordMap,
  type HighlightStrategy,
} from "../lib/highlight-strategy.js";

/** Tiny fake pdfjs page proxy — just enough surface area to drive
 *  findTextRects. We don't need to render anything; we only need
 *  getTextContent() to return TextItem-shaped objects. */
function fakePage(items: Array<{
  str: string;
  x: number;
  y: number;
  width: number;
  height: number;
}>) {
  return {
    async getTextContent() {
      return {
        items: items.map((it) => ({
          str: it.str,
          // transform = [scaleX, skewY, skewX, scaleY, x, y]
          transform: [1, 0, 0, 1, it.x, it.y],
          width: it.width,
          height: it.height,
          hasEOL: false,
        })),
      };
    },
  } as unknown as Parameters<
    HighlightStrategy["resolve"]
  >[0]["page"];
}

/** Fake viewport — convertToViewportRectangle is identity in CSS
 *  pixels for our purposes (no rotation, scale = 1). */
function fakeViewport() {
  return {
    scale: 1,
    convertToViewportRectangle: ([x1, y1, x2, y2]: number[]) => [
      x1,
      y1,
      x2,
      y2,
    ],
  } as unknown as Parameters<
    HighlightStrategy["resolve"]
  >[0]["viewport"];
}

describe("TextLayerSearchStrategy", () => {
  it("returns a rect for a match inside the chunk bbox", async () => {
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        { str: "Aviation Fund", x: 50, y: 100, width: 80, height: 12 },
        { str: "$2,587,400", x: 140, y: 100, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "Aviation Fund $2,587,400",
      bbox: { left: 40, top: 90, width: 200, height: 30 },
    });
    expect(rects.length).toBe(1);
    // x ≈ 140, y ≈ 100, width ≈ 60.
    expect(rects[0]!.left).toBeCloseTo(140, 0);
    expect(rects[0]!.width).toBeCloseTo(60, 0);
  });

  it("returns [] when the quote isn't inside the bbox-restricted region", async () => {
    // The strict-bbox change: if the match is outside the bbox, we do
    // NOT fall back to a whole-page search. Honest miss.
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        // The $2,587,400 text is at x=500, y=600 — far outside the
        // chunk bbox supplied below.
        { str: "Aviation Fund", x: 500, y: 600, width: 80, height: 12 },
        { str: "$2,587,400", x: 580, y: 600, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "Aviation Fund $2,587,400",
      bbox: { left: 40, top: 90, width: 200, height: 30 },
    });
    expect(rects).toEqual([]);
  });

  it("returns [] when bbox is null and no items match the quote", async () => {
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        { str: "Unrelated", x: 50, y: 100, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "x",
      bbox: null,
    });
    expect(rects).toEqual([]);
  });

  it("returns rects when bbox is null but the quote matches anywhere on the page", async () => {
    // Without a bbox we fall back to whole-page search (legitimate use
    // — OpenDataLoader chunks sometimes lack a bbox).
    const strategy = new TextLayerSearchStrategy();
    const rects = await strategy.resolve({
      page: fakePage([
        { str: "$2,587,400", x: 500, y: 600, width: 60, height: 12 },
      ]),
      viewport: fakeViewport(),
      quote: "$2,587,400",
      fullChunkText: "$2,587,400",
      bbox: null,
    });
    expect(rects.length).toBe(1);
  });
});
```

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
cd web && npm test -- highlight-strategy.test.ts
```

Expected: FAIL — module does not exist yet.

- [ ] **Step 3: Create `web/lib/highlight-strategy.ts`**

```typescript
// Highlight resolution strategy interface. Today's only implementation
// is `TextLayerSearchStrategy`, which performs the same text-layer
// search that used to live inline in PdfPage.tsx. The seam is here
// so the future #57 follow-up (chunk→PDF coord map captured at
// ingest) can swap in a `CoordMapStrategy` without rewriting the
// component.
//
// The strict-bbox-only behavior is the spec's correctness change:
// when a chunk has a stored bbox, we never search outside it. A miss
// surfaces as an empty result so the viewer can show the "couldn't
// pinpoint" badge — honest miss instead of silent wrong highlight.

import type {
  PDFPageProxy,
  TextItem,
  TextMarkedContent,
} from "pdfjs-dist/types/src/display/api";
import type { PageViewport } from "pdfjs-dist/types/src/display/display_utils";

import { findNormalizedMatch } from "./citation-extract.js";

/** A single highlight rectangle in viewport (canvas) pixel space. */
export interface HighlightRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** Future-shape placeholder for #57. Per-chunk list of
 *  (text-slice, page, rect) tuples captured at ingest from the
 *  per-line bboxes the extractor produces. Today: always undefined. */
export interface ChunkCoordMap {
  /** Per-line text + viewport-space rect. */
  entries: Array<{ text: string; page: number; rect: HighlightRect }>;
}

export interface ResolveArgs {
  page: PDFPageProxy;
  viewport: PageViewport;
  /** Cited substring of chunk.text. */
  quote: string;
  /** Full chunk text — used as a wider fallback search target when
   *  the quote can't be matched. */
  fullChunkText: string;
  /** Chunk-stored bbox in VIEWPORT-PIXEL space, OR null when the
   *  chunk has no stored bbox (OpenDataLoader). When non-null the
   *  search is strictly restricted to the bbox; on miss we return
   *  [] rather than falling back to whole-page. */
  bbox: HighlightRect | null;
  /** Forwarded for the future CoordMapStrategy. Today: undefined. */
  coordMap?: ChunkCoordMap;
}

export interface HighlightStrategy {
  resolve(args: ResolveArgs): Promise<HighlightRect[]>;
}

/** Default strategy: searches the pdfjs text layer for the quote
 *  (then full chunk text, then currency tokens) inside the chunk's
 *  bbox if present. */
export class TextLayerSearchStrategy implements HighlightStrategy {
  async resolve(args: ResolveArgs): Promise<HighlightRect[]> {
    const { page, viewport, quote, fullChunkText, bbox } = args;
    const targets = [quote, fullChunkText].filter(
      (t): t is string => typeof t === "string" && t.length > 0,
    );
    for (const target of targets) {
      const rects = await findTextRects(page, target, viewport, bbox);
      if (rects.length > 0) return rects;
    }
    // Currency-token fallback for the common case where formatting
    // drift between chunk text and PDF text layer defeats the full
    // match but the dollar amount survives.
    const currencyMatches = quote.match(/\$[\d][\d,.]*/g) ?? [];
    const uniq = Array.from(new Set(currencyMatches));
    for (const tok of uniq) {
      const rects = await findTextRects(page, tok, viewport, bbox);
      if (rects.length > 0) return rects;
    }
    return [];
  }
}

/** Placeholder for the future #57 strategy. Today this throws so we
 *  never silently swap to a no-op. Replace the body when #57 ships. */
export class CoordMapStrategy implements HighlightStrategy {
  async resolve(_args: ResolveArgs): Promise<HighlightRect[]> {
    throw new Error(
      "CoordMapStrategy not implemented yet — see plan #57 follow-up",
    );
  }
}

function isTextItem(item: TextItem | TextMarkedContent): item is TextItem {
  return typeof (item as { str?: unknown }).str === "string";
}

/** Search the page's text layer for `searchText` and return one
 *  highlight rect PER LINE the match crosses. Strict-bbox: when
 *  `restrictTo` is non-null, items outside it (with 8pt of slack)
 *  are dropped from the search; if the match isn't inside the
 *  restricted region we return [] WITHOUT a whole-page fallback. */
async function findTextRects(
  page: PDFPageProxy,
  searchText: string,
  viewport: PageViewport,
  restrictTo: HighlightRect | null,
): Promise<HighlightRect[]> {
  if (!searchText) return [];
  const content = await page.getTextContent();
  let items = content.items.filter(isTextItem);
  if (items.length === 0) return [];

  if (restrictTo) {
    const slack = 8 * (viewport.scale ?? 1);
    const rx1 = restrictTo.left - slack;
    const ry1 = restrictTo.top - slack;
    const rx2 = restrictTo.left + restrictTo.width + slack;
    const ry2 = restrictTo.top + restrictTo.height + slack;
    items = items.filter((item) => {
      const x1 = item.transform[4]!;
      const y1 = item.transform[5]!;
      const x2 = x1 + item.width;
      const y2 = y1 + item.height;
      const [vx1, vy1, vx2, vy2] = viewport.convertToViewportRectangle([
        x1,
        y1,
        x2,
        y2,
      ]);
      const ix1 = Math.min(vx1, vx2);
      const iy1 = Math.min(vy1, vy2);
      const ix2 = Math.max(vx1, vx2);
      const iy2 = Math.max(vy1, vy2);
      return ix1 < rx2 && ix2 > rx1 && iy1 < ry2 && iy2 > ry1;
    });
    if (items.length === 0) return [];
  }

  let flat = "";
  const itemForChar: number[] = [];
  for (let i = 0; i < items.length; i++) {
    const item = items[i]!;
    const start = flat.length;
    flat += item.str;
    for (let k = start; k < flat.length; k++) itemForChar.push(i);
    if (i + 1 < items.length) {
      const endsInSpace = item.str.endsWith(" ");
      if (!endsInSpace) {
        flat += " ";
        itemForChar.push(i);
      }
      if (item.hasEOL) {
        flat += "\n";
        itemForChar.push(i);
      }
    }
  }

  const match = findNormalizedMatch(flat, searchText, 0);
  if (!match) return [];

  const involved = new Set<number>();
  for (let i = match.start; i < match.end && i < itemForChar.length; i++) {
    involved.add(itemForChar[i]!);
  }
  if (involved.size === 0) return [];

  // Bucket items by baseline y to emit one rect per text line.
  const buckets = new Map<number, number[]>();
  for (const idx of involved) {
    const item = items[idx]!;
    const yKey = Math.round(item.transform[5]! * 2) / 2;
    if (!buckets.has(yKey)) buckets.set(yKey, []);
    buckets.get(yKey)!.push(idx);
  }

  const rects: HighlightRect[] = [];
  for (const [, idxs] of buckets) {
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const idx of idxs) {
      const item = items[idx]!;
      const x1 = item.transform[4]!;
      const y1 = item.transform[5]!;
      const x2 = x1 + item.width;
      const y2 = y1 + item.height;
      const [vx1, vy1, vx2, vy2] = viewport.convertToViewportRectangle([
        x1,
        y1,
        x2,
        y2,
      ]);
      minX = Math.min(minX, vx1, vx2);
      maxX = Math.max(maxX, vx1, vx2);
      minY = Math.min(minY, vy1, vy2);
      maxY = Math.max(maxY, vy1, vy2);
    }
    rects.push({
      left: minX,
      top: minY,
      width: Math.max(1, maxX - minX),
      height: Math.max(1, maxY - minY),
    });
  }
  rects.sort((a, b) => a.top - b.top);
  return rects;
}
```

- [ ] **Step 4: Run the test, confirm it PASSES**

Run:
```bash
cd web && npm test -- highlight-strategy.test.ts
```

Expected: all 4 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/lib/highlight-strategy.ts web/tests/highlight-strategy.test.ts
git commit -m "feat(web): HighlightStrategy interface + TextLayerSearchStrategy

Extracts the text-layer search from PdfPage into a strategy class so
the #57 follow-up (chunk-to-PDF coord map captured at ingest) can
swap in a CoordMapStrategy without rewriting the component.

The TextLayerSearchStrategy implements the spec's strict-bbox
behavior: when a chunk has a stored bbox, the search is restricted
to that bbox (with 8pt slack); on miss we return [] rather than
falling back to whole-page. Honest miss instead of silent wrong
highlight."
```

---

## Task 8: Web — `PdfPage` uses the strategy + drops unrestricted fallback

**Files:**
- Modify: `web/components/PdfPage.tsx`

- [ ] **Step 1: Replace inline `findTextRects` usage with the strategy**

In `web/components/PdfPage.tsx`:

1. Replace the import line at the top:

```typescript
import { findNormalizedMatch } from "@/lib/citation-extract";
```

with:

```typescript
import {
  TextLayerSearchStrategy,
  type ChunkCoordMap,
  type HighlightRect,
  type HighlightStrategy,
} from "@/lib/highlight-strategy";
```

2. Remove the local `HighlightRect` interface declaration (now imported).

3. Update the `Props` interface to add the optional `coordMap` + `strategy` fields:

```typescript
interface Props {
  docId: string;
  pageNumber: number;
  bbox: number[] | null;
  searchTexts?: string[];
  containerWidth?: number;
  zoomLevel?: number;
  /** Optional per-chunk coord map from a future #57 ingest pipeline.
   *  Today: always undefined. */
  coordMap?: ChunkCoordMap;
  /** Optional strategy override — tests pass a fake; production uses
   *  TextLayerSearchStrategy. */
  strategy?: HighlightStrategy;
}
```

4. Inside the component, instantiate the default strategy and call it instead of the inline `findTextRects` loop. Replace the entire block from `// Highlight strategy: walk searchTexts in priority order, …` through the closing of the `if (computed.length === 0) { setNotLocated(true); } setHighlights(computed); setLoading(false); }` with:

```typescript
        // Highlight strategy. Default is TextLayerSearchStrategy
        // (text-layer search restricted to the chunk's bbox if any);
        // tests + the future #57 path can pass a different strategy.
        // Strict bbox: when a chunk has a stored bbox, the strategy
        // does NOT fall back to whole-page search on miss — we want
        // an honest "couldn't pinpoint" badge instead of a yellow
        // rectangle on the wrong text.
        const activeStrategy = strategy ?? new TextLayerSearchStrategy();
        const restrictRect =
          bbox && bbox.length >= 4
            ? bboxToViewportRect(bbox, naturalViewport, renderScale)
            : null;
        const quote = (searchTexts ?? [])[0] ?? "";
        const fullChunkText = (searchTexts ?? [])[1] ?? "";
        const computed = await activeStrategy.resolve({
          page,
          viewport,
          quote,
          fullChunkText,
          bbox: restrictRect,
          coordMap,
        });
        if (cancelled) return;
        if (computed.length === 0) setNotLocated(true);
        setHighlights(computed);
        setLoading(false);
```

5. Delete the entire helper function `findTextRects` AND the `isTextItem` type-guard helper just above it (lines ~400-559 in the current file — both now live in `highlight-strategy.ts`). The other helper, `bboxToViewportRect`, stays — the new code still calls it.

6. Update the `useEffect` deps to include the new optional props:

```typescript
  }, [
    docId,
    pageNumber,
    bbox,
    (searchTexts ?? []).join(" "),
    containerWidth,
    zoomLevel,
    coordMap,
    strategy,
  ]);
```

7. Destructure `strategy` and `coordMap` from props in the component signature:

```typescript
export default function PdfPage({
  docId,
  pageNumber,
  bbox,
  searchTexts,
  containerWidth,
  zoomLevel = 1,
  coordMap,
  strategy,
}: Props) {
```

- [ ] **Step 2: Run the existing web test suite — confirm no regressions**

Run:
```bash
cd web && npm test
```

Expected: all tests pass. The PdfPage component is still untested directly; the `pdf-viewer.test.tsx` covers the integration smoke path.

- [ ] **Step 3: Run a quick TypeScript check**

Run:
```bash
cd web && npx tsc --noEmit
```

Expected: no type errors.

- [ ] **Step 4: Commit**

```bash
git add web/components/PdfPage.tsx
git commit -m "refactor(web): PdfPage delegates highlight resolution to a strategy

PdfPage no longer owns the text-layer search loop — it instantiates
TextLayerSearchStrategy by default and forwards args through. Drops
the unrestricted-fallback behavior: when a chunk has a bbox, search
is strictly bbox-restricted, and a miss surfaces the 'couldn't
pinpoint' badge instead of silently highlighting the wrong content
elsewhere on the page. Wires through optional coordMap + strategy
props for the future #57 follow-up and for tests."
```

---

## Task 9: Web — `CitedTextPanel` component

**Files:**
- Create: `web/components/CitedTextPanel.tsx`
- Create: `web/tests/cited-text-panel.test.tsx`

- [ ] **Step 1: Write the failing test**

Create `web/tests/cited-text-panel.test.tsx`:

```typescript
// CitedTextPanel renders the chunk's verbatim text with the cited
// span underlined so the analyst can verify the claim even when the
// PDF highlight failed. Tests cover: cited-span rendering, missing-
// data fallback, and source-label rendering.

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import CitedTextPanel from "../components/CitedTextPanel";

describe("CitedTextPanel", () => {
  it("underlines the cited span inside the chunk text", () => {
    const chunkText = "The Aviation Fund got $2,587,400 in FY 2026.";
    const html = renderToString(
      <CitedTextPanel
        chunkText={chunkText}
        spanStart={22}
        spanEnd={32}
        sourceLabel="JLBC FY26 Baseline, p. 47"
      />,
    );
    // The cited span text appears in a marked element.
    expect(html).toContain("$2,587,400");
    // The mark/underline element wraps the span.
    expect(html).toMatch(/<mark[^>]*>\$2,587,400<\/mark>/);
    // Source label is rendered.
    expect(html).toContain("JLBC FY26 Baseline, p. 47");
    // Heading is visible.
    expect(html).toContain("Cited text from this chunk");
  });

  it("renders fallback when chunkText is empty", () => {
    const html = renderToString(
      <CitedTextPanel
        chunkText=""
        spanStart={0}
        spanEnd={0}
        sourceLabel=""
      />,
    );
    expect(html).toContain("Source text unavailable in this turn");
  });

  it("renders the whole chunk text without underline when spans are sentinel (0, claimLen)", () => {
    // Legacy sentinel range used by pre-resolved-offsets cites. The
    // panel should still be useful — show the whole chunk, just no
    // underline.
    const html = renderToString(
      <CitedTextPanel
        chunkText="Whole chunk text here."
        spanStart={0}
        spanEnd={0}
        sourceLabel="src"
      />,
    );
    expect(html).toContain("Whole chunk text here.");
    expect(html).not.toContain("<mark");
  });
});
```

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
cd web && npm test -- cited-text-panel.test.tsx
```

Expected: FAIL — `Cannot find module '../components/CitedTextPanel'`.

- [ ] **Step 3: Create `web/components/CitedTextPanel.tsx`**

```typescript
// Always-visible panel below the PDF page showing the cited span
// in-context within the chunk text. The PDF highlight is the
// primary affordance, but when the text-layer search misses (or
// when the analyst wants to verify by eye anyway) this panel is
// the trust signal: the verbatim source text with the cited span
// underlined.
//
// Empty / sentinel states:
//   - chunkText empty → "Source text unavailable in this turn."
//   - spanStart === spanEnd → render whole chunk text without
//     underline (legacy sentinel from pre-resolved-offsets cites).

interface Props {
  chunkText: string;
  /** Resolved span start in chunk.text (inclusive). */
  spanStart: number;
  /** Resolved span end in chunk.text (exclusive). */
  spanEnd: number;
  /** Display label for the source ("JLBC FY26 Baseline, p. 47"). */
  sourceLabel: string;
}

export default function CitedTextPanel({
  chunkText,
  spanStart,
  spanEnd,
  sourceLabel,
}: Props) {
  if (!chunkText) {
    return (
      <div className="border-t border-edge bg-panel/40 px-3 py-3 text-xs">
        <div className="font-bold text-fg-2 mb-1">Cited text from this chunk</div>
        <p className="text-fg-muted italic">
          Source text unavailable in this turn.
        </p>
      </div>
    );
  }
  const hasValidSpan =
    spanEnd > spanStart && spanEnd <= chunkText.length && spanStart >= 0;
  const before = hasValidSpan ? chunkText.slice(0, spanStart) : chunkText;
  const cited = hasValidSpan ? chunkText.slice(spanStart, spanEnd) : "";
  const after = hasValidSpan ? chunkText.slice(spanEnd) : "";
  return (
    <div className="border-t border-edge bg-panel/40 px-3 py-3 text-xs">
      <div className="font-bold text-fg-2 mb-1">Cited text from this chunk</div>
      <p className="text-fg whitespace-pre-wrap">
        <span className="text-fg-muted">{before}</span>
        {hasValidSpan && (
          <mark className="bg-amber-300/30 text-fg border-b border-amber-500 rounded-sm">
            {cited}
          </mark>
        )}
        <span className="text-fg-muted">{after}</span>
      </p>
      {sourceLabel && (
        <div className="text-fg-faint mt-2">Source: {sourceLabel}</div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the test, confirm it PASSES**

Run:
```bash
cd web && npm test -- cited-text-panel.test.tsx
```

Expected: all 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add web/components/CitedTextPanel.tsx web/tests/cited-text-panel.test.tsx
git commit -m "feat(web): CitedTextPanel component for inline source verification

Always-visible panel that renders the chunk's verbatim text with the
cited span underlined. Converts the worst-feeling PDF failure
('yellow box on what?') into a tolerable one ('the highlight missed
but I can read the cited text right here'). Handles empty chunkText
and legacy sentinel (0, claimLen) span ranges."
```

---

## Task 10: Web — wire `CitedTextPanel` into `PdfViewer`

**Files:**
- Modify: `web/components/PdfViewer.tsx`
- Modify: `web/tests/pdf-viewer.test.tsx`

- [ ] **Step 1: Add the failing test**

In `web/tests/pdf-viewer.test.tsx`, append a new test inside the `describe("PdfViewer bus subscription (client)", …)` block (after the existing "flips to the loaded state" test). The test must drive the same bus-subscription flow as the existing one and then assert the panel rendered:

```typescript
it("renders CitedTextPanel beneath the loaded PDF page", async () => {
  const dom = new JSDOM("<!doctype html><html><body></body></html>");
  const { window } = dom;
  (globalThis as unknown as { IS_REACT_ACT_ENVIRONMENT: boolean })
    .IS_REACT_ACT_ENVIRONMENT = true;
  (globalThis as unknown as { window: Window }).window =
    window as unknown as Window;
  (globalThis as unknown as { document: Document }).document =
    window.document;
  (globalThis as unknown as { HTMLElement: typeof HTMLElement }).HTMLElement =
    window.HTMLElement;

  const container = window.document.createElement("div");
  window.document.body.appendChild(container);

  let busHandle: ReturnType<typeof useCitationBus> | null = null;
  function BusProbe() {
    busHandle = useCitationBus();
    return null;
  }

  let root: Root | null = null;
  await act(async () => {
    root = createRoot(container);
    root.render(
      <CitationBusProvider>
        <BusProbe />
        <PdfViewer />
      </CitationBusProvider>,
    );
  });

  await act(async () => {
    busHandle!.select(citation());
  });

  // Verify panel heading is in the DOM. The PdfPage canvas is loaded
  // via next/dynamic so it may render later; we don't assert on it.
  expect(container.innerHTML).toContain("Cited text from this chunk");
  // Cited span (chunkText.slice(0, 5) = "hello") is present.
  expect(container.innerHTML).toContain("hello");

  await act(async () => {
    root!.unmount();
  });
});
```

- [ ] **Step 2: Run the test, confirm it FAILS**

Run:
```bash
cd web && npm test -- pdf-viewer.test.tsx
```

Expected: FAIL — `Cited text from this chunk` is not in the rendered output.

- [ ] **Step 3: Wire `CitedTextPanel` into `PdfViewer`**

In `web/components/PdfViewer.tsx`, add the import near the top:

```typescript
import CitedTextPanel from "./CitedTextPanel";
import { formatCopyCitation } from "@/lib/citation-extract";
```

Then inside the `Loaded` function, modify the JSX `return` to add the `CitedTextPanel` below the scrollable PDF page area. Replace the existing `return ( <div className="h-full flex flex-col bg-canvas"> … </div> );` with:

```tsx
  return (
    <div className="h-full flex flex-col bg-canvas">
      <Breadcrumb docTitle={docTitle} page={page} citation={citation} />
      <Toolbar
        zoom={zoom}
        onZoomIn={zoomIn}
        onZoomOut={zoomOut}
        onResetZoom={resetZoom}
        docId={docId}
        page={page}
      />
      <div
        ref={scrollerRef}
        className="flex-1 min-h-0 overflow-auto p-3 bg-inset"
      >
        {containerWidth > 0 && (
          <PdfPage
            docId={docId}
            pageNumber={page}
            bbox={bbox}
            searchTexts={searchTexts}
            containerWidth={Math.max(0, containerWidth - 24)}
            zoomLevel={zoom}
          />
        )}
      </div>
      <CitedTextPanel
        chunkText={r.text ?? ""}
        spanStart={citation.spanStart}
        spanEnd={citation.spanEnd}
        sourceLabel={formatCopyCitation(citation)}
      />
    </div>
  );
```

- [ ] **Step 4: Run the test, confirm it PASSES**

Run:
```bash
cd web && npm test -- pdf-viewer.test.tsx
```

Expected: PASS.

- [ ] **Step 5: Run the full web test suite — confirm no regressions**

Run:
```bash
cd web && npm test
```

Expected: every web test passes.

- [ ] **Step 6: Commit**

```bash
git add web/components/PdfViewer.tsx web/tests/pdf-viewer.test.tsx
git commit -m "feat(web): always-visible CitedTextPanel under the PDF page

The PdfViewer's loaded state now renders CitedTextPanel below the
canvas. Trust signal is consistently visible: even when the PDF
highlight is correct, having the chunk's verbatim text directly
readable removes friction — and when the highlight fails (couldn't
pinpoint or wrong-bbox cases) the panel becomes the verify surface."
```

---

## Task 11: Manual verification + final integration

**Files:** none — runs the app and verifies behavior end-to-end.

- [ ] **Step 1: Run the full backend + web test suites**

Run from the worktree root:
```bash
bash setup.sh --verify
```

Expected: all pytest + both vitest suites pass.

- [ ] **Step 2: Start the stack and verify in a browser**

Per `README.md` daily-startup checklist:
```bash
docker compose up -d
uv run uvicorn retrieval.api:app --host 127.0.0.1 --port 9200 &
# In a separate terminal:
cd web && npm run dev
```

Open `http://127.0.0.1:3000`. Ask a question that exercises the design:
- **Lookup repeating a fact** — "What was AHCCCS's appropriation for FY 2026, and what did that change from FY 2025?" — both sentences mentioning the FY26 figure should have a chip.
- **Cite on an unambiguous chunk** — Click the chip; the PDF should highlight the cited dollar amount AND the inline CitedTextPanel should show the chunk text with the cited span underlined.
- **Cite where the bbox-restricted text-layer search misses** — Look for the "couldn't pinpoint" badge. The CitedTextPanel below should still show the verbatim chunk text.
- **Ambiguous-quote rejection** — Hard to provoke manually; rely on the unit tests. If you see the new error message in a tool-card body during natural use ("quote appears multiple times in chunk.text (positions: …)"), the rejection is firing.

If any of these don't behave as expected, file an open follow-up task and STOP before merging — describe the divergence in the task body.

- [ ] **Step 3: Shut down the dev server**

```bash
# Kill the sidecar process (find via `jobs` or its PID from step 2).
# Stop the web dev server (Ctrl-C in the terminal running it).
docker compose down
```

(Per CLAUDE.md: "Pushing to master green-lights closing the dev server.")

- [ ] **Step 4: Open the PR**

From the worktree:
```bash
git push -u origin citation-accuracy
gh pr create --title "feat: per-sentence citation chips + strict-bbox PDF + duplicate-quote rejection" --body "$(cat <<'EOF'
## Summary

Implements the design at `docs/superpowers/specs/2026-05-20-citation-accuracy-and-per-sentence-chips-design.md` (Approach A).

- Per-sentence chip placement: `planCitationPlacements` walks every sentence on every line. A chip lands on any sentence whose normalized text contains the claim_span OR the citation's key-fact token (largest currency / percentage in claim_span). Sentences already covered by claim_span don't double-chip.
- Strict-bbox PDF highlight: when a chunk has a stored bbox, the text-layer search is strictly restricted to it. No more silent fall-through to whole-page search → no more wrong yellow rectangles on the wrong dollar amount.
- Always-visible CitedTextPanel below the PDF page: shows the chunk's verbatim text with the cited span underlined. Even when the PDF highlight misses, the analyst can verify the claim by reading the source text directly.
- HighlightStrategy interface (`TextLayerSearchStrategy` today, `CoordMapStrategy` placeholder): the seam for the future #57 follow-up.
- Sidecar duplicate-quote rejection: `_validate_one_cite` rejects quotes that appear more than once in chunk.text, returning up to 3 positions in the error so the model picks a longer, unique quote on retry.

## Test plan

- [x] pytest passes (`uv run pytest`)
- [x] web vitest passes (`cd web && npm test`)
- [x] mcp-server vitest passes (`cd mcp-server && npm test`)
- [ ] Manual: dogfood query restating a fact across two sentences shows two chips
- [ ] Manual: chip click highlights the right number on the PDF (strict-bbox)
- [ ] Manual: chip click on a cite the text-layer search misses still shows the cited text in the CitedTextPanel below
- [ ] Manual: ambiguous-quote rejection visible in a tool-card body when a model picks a non-unique quote
EOF
)"
```

- [ ] **Step 5: Clean up the worktree after merge**

Once the PR merges to master:
```bash
cd ~/ask-the-budget-az-dev
git fetch origin && git pull origin master
git worktree remove ~/ask-the-budget-az-worktrees/citation-accuracy
git branch -D citation-accuracy
```

- [ ] **Step 6: Update STATUS.md**

In `~/ask-the-budget-az-dev/STATUS.md`, move the "PDF viewer accuracy" failure-mode bullets out of "What's open" and into "Recently fixed — verify in next dogfood pass" with the appropriate description. Add a note to the open task list referencing #57 as the next architectural step. Commit and push:

```bash
git add STATUS.md
git commit -m "docs: STATUS.md update for citation-accuracy branch shipping"
git push origin master
```

---

## Spec-coverage self-review

Walking the spec section by section to verify every requirement is implemented:

- **Section 1 — Per-sentence chip placement.** Implemented in Tasks 3 (`extractKeyFact`), 4 (claim_span sentence iteration + `column` field), 5 (`injectCiteSentinels` honors column), 6 (key-fact-token rule + anti-duplicate). ✓
- **Section 2a — Strict bbox restriction.** Implemented in Task 7 (`TextLayerSearchStrategy.resolve` returns [] on bbox-restricted miss) + Task 8 (`PdfPage` delegates to the strategy). Tests in `highlight-strategy.test.ts` verify the no-fallback behavior. ✓
- **Section 2b — Always-visible CitedTextPanel.** Implemented in Tasks 9 (component) + 10 (wired into `PdfViewer`). ✓
- **Section 2c — Strategy interface.** Implemented in Tasks 7 (interface + `TextLayerSearchStrategy` + `CoordMapStrategy` placeholder) + 8 (`PdfPage` accepts optional `strategy` + `coordMap` props). ✓
- **Section 3 — Server-side ambiguous-quote rejection.** Implemented in Tasks 1 (tests) + 2 (sidecar). The spec's bounded-positions list (3 entries + `…`) is in Task 2's implementation. ✓
- **Section 4 — Tests, error handling, scope.** All tests listed in the spec map to tasks above. The `ChunkCoordMap` type is declared in `web/lib/highlight-strategy.ts` and flows through `PdfPage`'s `coordMap?: ChunkCoordMap` prop (Task 8). The spec mentioned a `Citation.resolved.coordMap` field, but in practice the type only needs to live on the strategy-args path — adding a field to `ResolvedChunk` that's always undefined would be YAGNI. When #57 ships and starts populating coord maps, the field can be added then alongside the data plumbing. ✓
- **Spec's "Open items deferred to writing-plans":**
  - Slack value tuning — left at 8pt (Task 7), can be widened later without a structural change.
  - System-prompt mention of the new duplicate-quote error code — deferred; the error string itself carries enough recovery guidance. Captured as a follow-up in the task body if needed.
  - Telemetry counter — not added in this plan. The bridge JSONL log already captures cite-validate outcomes; if post-ship dogfood shows we need a structured "highlight matched / not located" counter we'll add it in a small follow-up.

No placeholders, no `TBD`, every code step has the actual code.
