---
title: Citation Accuracy + Per-Sentence Chips — Design Spec
date: 2026-05-20
status: drafted
authors: Destin Moss, Claude
audience: Phase 1c WS3 (UI rendering), retrieval sidecar (cite validator), future #57 ingest-coord-map plan
supersedes_in_part: none (additive — extends the citation tool contract amended 2026-05-20)
---

# Citation Accuracy + Per-Sentence Chips

This spec covers two trust-affecting problems surfaced during 2026-05-20
dogfood, treated as one design because they share a root: the PDF
coordinate truth lives in a different place than the chunk text the
runtime sees.

1. **Wrong / missing PDF highlights.** Chips render, but clicking them
   either lights up the wrong dollar amount on the page or shows the
   "Citation is on this page — exact text couldn't be pinpointed"
   badge. Either failure erodes the analyst's trust faster than a
   refusal would (Invariant 3 inverted).
2. **One chip per claim, not per sentence.** When the model restates
   the same fact across multiple sentences, the chip only attaches to
   the first occurrence. Analysts skimming the second or third sentence
   see no provenance and have to scroll back.

The fix is scoped as **Approach A**: runtime-side fixes that ship in a
single ~1-2 day branch. A follow-up plan (#57 — chunk→PDF coord map
captured at ingest) is queued as a separate spec; this spec includes
small structural hooks so #57 retrofits cleanly.

## Goals

- Drive silent-wrong-highlight to zero. When we can't be certain, we
  say so instead of painting a wrong rectangle.
- Make the source text directly readable next to the PDF, so a missed
  highlight is recoverable rather than dead-end.
- Render a citation chip after every sentence that asserts a cited
  claim, even when the model only emitted one cite() for that claim.
- Tighten the cite() contract so the model can't pick an ambiguous
  quote that has multiple landing spots in the chunk text.

## Non-goals / out of scope

- **#57 — chunk→PDF coord map at ingest.** Eliminates text-layer
  search entirely by storing per-line bboxes alongside each chunk.
  Architecturally correct but requires schema migration + re-processing
  of all 7,755 chunks; gets its own spec.
- **WS3 — semantic faithfulness verifier.** Still unbuilt. This spec
  doesn't change the answer-stripping story.
- **DOCX-source citations.** Bills are DOCX; the existing "Couldn't
  open source PDF" state stays until Phase 2 ships the DOCX viewer.
- **System-prompt rewrite beyond the ambiguous-quote response.** The
  prompt already steers the model toward unique quotes via the
  "Choosing a good quote" section; this spec adds one paragraph
  about the new error code, not a rewrite.

## Background — current pipeline (for context)

1. Model retrieves chunks; each chunk has `chunk_id`, `text`, page
   number, and a stored bbox.
2. Model emits `cite()` or `cite_batch()` per claim with `quote`,
   `claim_span`, `confidence`.
3. Sidecar `/cite/validate(_batch)` scans `chunk.text` for `quote`
   via `chunk.text.find(quote)` after light normalization, derives
   `resolved_span_start`/`resolved_span_end`, returns ok.
4. Web `citation-extract.ts` parses tool blocks into `Citation`
   records; `dedupCitationRetries` collapses failed→ok retries; then
   `planCitationPlacements` finds **the first** source-markdown line
   whose normalized text contains the citation's `claim_span` and
   injects a `{{cite:N}}` sentinel at end-of-line.
5. `PdfPage.tsx` loads the chunk's page, walks search texts (cited
   slice → full chunk text → currency tokens), runs a bbox-restricted
   text-layer search first, falls through to **unrestricted search of
   the whole page** if the bbox-restricted pass missed, paints the
   matched rect or surfaces a "couldn't pinpoint" badge.

The two changes in (4) and (5) — first-line-only placement and
fall-through-to-unrestricted — are where the problems live.

## Design — Section 1: Per-sentence chip placement

**File:** `web/lib/citation-extract.ts`.

`planCitationPlacements` currently returns one `CitationPlacement` per
citation, anchored to the first matching line. We change it to return
one placement **per sentence hit**, with two placement triggers:

1. **claim_span match** (today's rule, iterated over every sentence on
   every line instead of stopping at the first hit).
2. **Key-fact-token match.** Extract the longest "key fact" token from
   `claim_span` (a dollar amount, percentage, or whole-number-with-
   thousand-separators). If a sentence contains that token and is not
   already covered by a chip pointing at the same `chunk_id`, place a
   chip on that sentence.

### Key-fact extraction

```ts
function extractKeyFact(claimSpan: string): string | null {
  // Tries currency, then percentage. Returns null if neither matches.
  // The longest currency match wins so "$3,300,000" beats "$3,300".
  const currency = claimSpan.match(/\$[\d][\d,.]*(?:\s?(?:million|billion|M|B))?/gi);
  if (currency && currency.length) {
    return currency.reduce((a, b) => (b.length > a.length ? b : a));
  }
  const pct = claimSpan.match(/\d+(?:\.\d+)?\s?%/);
  if (pct) return pct[0];
  return null;
}
```

We intentionally do NOT match bare years (`2027`) or short integers
(`1`, `2`) — too many false positives in budget prose where years and
small ordinals appear everywhere.

### Sentence splitting

A simple regex over each markdown line:

```ts
const SENTENCE_RE = /[^.!?\n]+[.!?]+["')\]]*|[^.!?\n]+$/g;
```

This handles the common shape "claim ending with period, optionally
followed by a closing quote/paren." Table rows and bullet points are
treated as single sentences regardless of internal punctuation,
because the placement target is end-of-row / end-of-bullet anyway.

### Output shape change

```ts
export interface CitationPlacement {
  citationIndex: number;
  lineIndex: number;
  /** Column offset within the line of the END of the matched sentence.
   *  When null, the sentinel goes at end-of-line (back-compat for
   *  single-sentence lines and table-row injection). */
  column?: number | null;
}
```

`injectCiteSentinels` is extended in a backward-compatible way: when
a placement has a `column` value, the `{{cite:N}}` sentinel is injected
immediately after the matched sentence's terminating punctuation
rather than at end-of-line. When `column` is null or undefined (the
existing single-sentence and table-row paths), the existing end-of-
line and inside-last-cell behavior is preserved unchanged. Table row
detection (the existing `|` carve-out) takes precedence over column
injection, since table rows are syntactically one sentence at the
markdown level regardless of internal periods.

### Anti-duplicate rule

Within a single sentence, never emit two placements for the same
`chunk_id`. This handles the case where both `claim_span` and the
key-fact token would otherwise match. First-write-wins.

### Across-sentence chip-numbering

The displayed chip number stays one-per-citation (citation #1 renders
as `[1]` wherever it appears). The rendered DOM has multiple
`CitationChip` elements bound to the same `Citation` record. Hover
state is shared via the existing citation-id keying in `ChatThread`.

### Tests

Added to `web/lib/citation-extract.test.ts`:

- Multi-sentence chip placement: a turn that restates the same dollar
  amount in two sentences produces two placements for the single
  citation.
- Key-fact-token rule: a sentence whose wording differs from
  `claim_span` but contains the same `$X,XXX,XXX` value gets a chip.
- Anti-duplicate: a sentence containing both the full `claim_span`
  AND the key-fact token still gets exactly one chip for that
  citation.
- Backward compat: existing single-sentence placement tests still
  pass.

## Design — Section 2: PDF viewer correctness

**File:** `web/components/PdfPage.tsx` + a sibling
`web/components/CitedTextPanel.tsx` (new).

### 2a. Strict bbox restriction

The current passes array:

```ts
const passes = restrictRect ? [restrictRect, null] : [null];
```

becomes:

```ts
const passes = restrictRect ? [restrictRect] : [null];
```

When a chunk has a stored bbox, the text-layer search runs **only**
inside that bbox (with the existing 8pt slack on every side). If the
match fails inside the bbox, we drop straight to the `notLocated`
state — no unrestricted whole-page search.

The slack value (8pt scaled, line 439) is preserved as today. If post-
ship dogfood shows we're missing edge-of-bbox text more often than
acceptable, the slack widens in a separate change (not a structural
revisit).

When the chunk has NO bbox (rare but possible — OpenDataLoader chunks
sometimes lack one), the existing unrestricted-search behavior stays.
This is the legitimate use of unrestricted search; it isn't going away,
it just stops being a fallback for "bbox missed."

### 2b. Inline verify panel — always visible

A new component `CitedTextPanel` renders below the PDF page (inside
`PdfViewer`, beneath the canvas):

```tsx
<CitedTextPanel
  chunkText={citation.resolved?.text ?? ""}
  spanStart={citation.spanStart}
  spanEnd={citation.spanEnd}
  sourceLabel={formatCopyCitation(citation)}
/>
```

Visual layout:

```
┌─ Cited text from this chunk ──────────────────────┐
│ The Baseline includes a decrease of $(3,300,000)  │
│ from the General Fund in FY 2027 to remove        │
│ funding for a one-time distribution to a nonprofit │  ← cited span
│ organization that is designated as an              │     underlined
│ international dark sky discovery center.           │
│                                                   │
│ Source: JLBC FY27 Baseline, p. 152                │
└───────────────────────────────────────────────────┘
```

The cited span is the substring `chunkText.slice(spanStart, spanEnd)`,
rendered with a subtle underline (same color family as the PDF
highlight rectangle — amber). The rest of the chunk text is rendered
in muted color so the analyst's eye lands on the underlined span first.

Empty / missing-data states:

- `Citation.resolved` undefined → "Source text unavailable in this
  turn." (Cross-turn chunk with no metadata; fallback path matches
  today's `formatCopyCitation` behavior.)
- `chunkText` present but `spanStart === spanEnd` (legacy sentinel
  case for pre-fix calls) → render the whole chunk text without
  underline; the panel still works as a verify surface.

### 2c. Strategy interface (#57 hook)

`PdfPage`'s inline text-layer search is wrapped in a small interface
so the future ingest-coord-map strategy slots in cleanly:

```ts
interface HighlightStrategy {
  resolve(args: {
    page: PDFPageProxy;
    viewport: PageViewport;
    quote: string;
    fullChunkText: string;
    bbox: number[] | null;
    coordMap?: ChunkCoordMap;
  }): Promise<HighlightRect[]>;
}

class TextLayerSearchStrategy implements HighlightStrategy { /* current code */ }
// CoordMapStrategy slots in when #57 ships.
```

The component picks the strategy at render time:
`coordMap ? CoordMapStrategy : TextLayerSearchStrategy`. Today
`coordMap` is always undefined so behavior is unchanged.

### Tests

Added to `web/components/PdfPage.test.tsx` (new) using pdfjs stubs,
same shape as existing `web/__tests__` component tests:

- Bbox-restricted search miss returns `[]` and sets `notLocated`
  (no whole-page fallback).
- No-bbox case still falls through to whole-page search and returns
  matches (backward compat for OpenDataLoader chunks).
- Strategy interface honors `coordMap` when provided (regression
  protection — passes a stub `CoordMapStrategy` and asserts it was
  invoked instead of `TextLayerSearchStrategy`).

Added to `web/components/PdfViewer.test.tsx`:

- `CitedTextPanel` renders chunk text with the cited span underlined
  when `resolvedSpanStart/End` are present.
- Missing-resolved-chunk case shows the "Source text unavailable"
  message instead of crashing.

## Design — Section 3: Server-side ambiguous-quote rejection

**File:** `retrieval/api.py` — `_validate_one_cite` (around lines
1085–1115).

Today the quote-resolution path:

```python
idx = full_text.find(body.quote)
if idx == -1:
    return CiteValidateResponse(ok=False, error="quote not found …")
resolved_span_start = idx
resolved_span_end = idx + len(body.quote)
```

Add a duplicate check immediately after the first `find`:

```python
# Collect up to 3 occurrences so the error message is informative
# without being a wall of integers when the quote is degenerate
# (e.g. "$5M" appearing 20 times in a per-agency summary).
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
```

The model retries with a longer quote per existing recovery rules.

### Normalization caveat

The duplicate check runs against the same normalized form the lookup
uses. If `chunk.text` contains both `$3,300,000` and `$(3,300,000)`
and the model cites `$3,300,000`, the normalization collapses both to
the same form — duplicate triggers, model retries with surrounding
context like `Dark Sky Discovery Center $3,300,000` which is unique.

### Tests

Added to `retrieval/tests/test_cite_validate.py`:

- Duplicate quote rejection: chunk text with the same `$5M` token at
  two positions returns `ok:false` with positions in the error string.
- Single-occurrence quotes still validate ok:true (regression).
- Multi-position case reports up to 3 positions in the error string
  (`12, 47, 89, …`) — bounded so the message stays readable when the
  quote appears 10+ times.

## Failure modes (post-ship catalog)

After Approach A ships, the failure-mode catalog from STATUS.md
collapses to:

| Failure | Post-A behavior |
|---|---|
| Source isn't a PDF (DOCX bills) | Still shows "Couldn't open source PDF" PLUS `CitedTextPanel` underneath — analyst still has the verifiable quote. Phase 2 adds the DOCX viewer. |
| PDF exists, text-layer search fails inside bbox | Shows "Couldn't pinpoint" badge PLUS `CitedTextPanel`. #57 drives this near-zero later. |
| PDF exists, chunk bbox wrong (rare) | Same as above — "couldn't pinpoint" + verify panel. No more silent wrong highlight. |
| Wrong-occurrence highlight (multiple quote matches in chunk) | Cannot occur: sidecar rejects the cite at validate time. |
| Cross-turn chunk with no metadata | Same as today — `buildConversationResolvedChunkMap` covers most cases; #56 (queued separately) tackles the rest. |

## Estimated landing

One feature branch, ~1-2 days of work, single PR. The PR is small
enough to review in one pass and large enough that splitting it would
create awkward intermediate states (e.g., per-sentence chips landing
without strict-bbox would expose the wrong-highlight problem on more
sentences, briefly making things worse).

## Files touched

- `web/lib/citation-extract.ts` — placement extension, key-fact extractor
- `web/components/PdfPage.tsx` — strict bbox, strategy interface
- `web/components/PdfViewer.tsx` — wire in CitedTextPanel
- `web/components/CitedTextPanel.tsx` — new component
- `retrieval/api.py` — duplicate-quote rejection in `_validate_one_cite`
- `web/lib/citation-extract.test.ts` — placement tests
- `web/components/PdfPage.test.tsx` — new file
- `web/components/PdfViewer.test.tsx` — verify-panel tests
- `retrieval/tests/test_cite_validate.py` — duplicate-quote tests

## Open items deferred to writing-plans

- Exact slack value for the strict-bbox search (current 8pt may need
  widening; dogfood-measured tuning, not a structural decision).
- Whether the system-prompt mentions the new duplicate-quote error
  code explicitly or relies on the error string steering the model.
- Whether to bake any telemetry counter for "highlight matched" vs
  "couldn't pinpoint" into the bridge JSONL log so we can measure
  post-A improvement without a manual audit.
