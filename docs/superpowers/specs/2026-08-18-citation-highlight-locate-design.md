# Citation highlight locate — design

**Date:** 2026-08-18
**Status:** approved-in-conversation (Destin: stages 1–3 now; error surfaces folded in;
every failure surface that has a PDF behind it gets an "Open document" button)
**Supersedes-in-part:** the deferred A7 coordmap
(`2026-08-02-attested-citation-linking-design.md` §A7) and STATUS follow-up #57,
for the existing corpus: highlighting becomes a **lookup at read time** instead
of a stored ingest artifact. A7's ingest-time coordmap remains the right shape
for a future backfill and is NOT built here.

## The problem, as measured

Replayed every linked figure chip from the live Layer-2 run
`eval/results/agent/2026-08-17T2324Z-88f90b3` (137 figures) against the real
PDFs on disk, simulating the viewer's exact chain (pdf.js-style flat string +
`normalizeForMatch` + strict stored-bbox restriction):

| outcome | count | analyst sees |
|---|---|---|
| highlight works end-to-end | 71 | tight box ✓ |
| value IS on the stored page, stored bbox excludes it | 46 | amber "couldn't pinpoint" |
| value is on a DIFFERENT page than the chunk's `page` | 7 | amber badge, wrong page |
| accounting-paren format drift (`$(X)` in PDF vs `(X)` stored) | 7 | amber badge |
| source is DOCX (no page image by design) | 4 | "Couldn't open source PDF" |
| value genuinely absent from the PDF | 2 | amber badge (honest) |

44% of correctly-linked citations render as a miss; 2 of the 60 misses are
honest. A separate surface defect: any `/api/pdf` failure (404 renamed doc,
500 share blip, pdfjs choking on a JSON error body) paints pdfjs's raw red
error with no recovery and no way out.

## Root causes

1. **`chunking/builders/narrative_chunk.py` stores the FIRST paragraph's bbox
   and page for a chunk that merges several paragraphs.** Verified on live
   rows: `jlbc-baseline-fy2024-ade-0087`'s bbox ends at y=334 while its own
   second bullet sits at y≈350–390. The strict-bbox viewer search then cannot
   see the chunk's own text. This is the 46 + part of the 7.
2. **The two accounting-negative conventions are not reconciled at search
   time.** MinerU chunk text prefers `$(546,838,600)`; pdf.js text layers on
   these pages emit `$(…)` too, but the LINKER's stored `source_text` carries
   `(546,838,600)` (the answer-side form). `normalizeForMatch` collapses both
   to the same token, but PyMuPDF/pdfjs RAW search does not.
3. **Multi-page sections:** narrative outline sections legitimately span
   pages under their heading (the orphan-bucket fix deliberately kept that),
   so `page` = first paragraph's page while a cited value sits pages later.
4. **Failure surfaces are error-styled dead ends.**

## Decisions

**L1 — narrative chunks store the union bbox of their member paragraphs
(same page only) and a per-paragraph line map in `source_anchor`.**
`emit()` already holds `buffer_paragraphs` with per-paragraph bboxes and
throws them away. Store:
- `provenance.bbox` = union of the bboxes of buffer paragraphs whose `page`
  equals the first paragraph's page (a bbox is a rectangle ON one page; a
  cross-page union would be a nonsense rectangle, so other-page paragraphs
  contribute nothing to it);
- `source_anchor` = `{"page": N, "lines": [{"text", "page", "bbox"}, …]}` —
  one entry per buffer paragraph that has a bbox. Table chunks keep today's
  `{"page": N}`: a table's bbox is the whole table and cited values sit
  inside it (the probe's bbox misses were all narrative chunks).

Chunk ids and text are UNCHANGED by this — provenance/anchor only — so eval
ground truth (which pins chunk_ids) is untouched. `bbox`/`page` are
display-only: verified no consumer in `retrieval/` ranking, refusal, or eval
reads them (grep: only `retrieval/types.py` passthrough + UI).

**L2 — server-side locate endpoint, the read-time coordmap.**
`GET /api/chunks/{chunk_id}/locate?corpus=…&text=…` returns

```json
{"chunk_id": "…", "page": 17, "rects": [[x0,y0,x1,y1]], "basis": "anchor"|"stored-page"|"scan"|"none"}
```

rects in PDF user-space points (the space `bboxToViewportRect` already
speaks). Algorithm, first success wins:
1. **anchor** — a `source_anchor.lines` entry whose text contains `text`
   (whitespace-collapsed compare; anchor text is a substring of chunk text BY
   CONSTRUCTION, no normalization needed) → PyMuPDF `search_for` restricted to
   that entry's page+bbox.
2. **stored-page** — `search_for` on the stored `page`, restricted to the
   stored bbox.
3. **scan** — `search_for` over every page, first hit (measured 0.04–0.25 s
   per document incl. the 191-page AFR; PyMuPDF ships in the Windows bundle
   and is already a runtime dep of `ingest/`).
Each step tries the text as-given AND the paren-swapped variant
(`(X)` ↔ `$(X)`), which is the measured format drift. `basis: "none"` when
nothing found OR fitz/store unavailable — the endpoint must NEVER error the
viewer out of its existing fallback chain; a locate failure degrades to
today's behaviour, exactly as A7's fallback rule says.

fitz is imported lazily inside the route (app server never imports it today;
a broken fitz must read as `basis: "none"`, mirroring `ingest/ladder.py`'s
posture) and opened documents are cached in a small LRU (cap 8, evicted docs
closed — the share-handle lesson from `_streamed` applies).

**L3 — the viewer consumes locate as the primary highlight source.**
`PdfViewer`'s click-time check already fetches `/api/chunks/{id}`; it adds the
locate call with `text = citation.sourceText ?? chunk.text.slice(span)` and
passes `serverPage`/`serverRects` down. `PdfPage` with non-empty
`serverRects` draws exactly those rects (converted through
`viewport.convertToViewportRectangle`) and skips the text-layer strategy —
the server answer IS the ground truth the probe validated. Empty/absent →
today's chain unchanged. `SourceView` renders `page = serverPage ?? page`.
The same click-time fetch's `chunk.text` also hydrates the CitedTextPanel for
figure chips (today `resolved.text = ""` by design, so the panel says
"Source text unavailable in this turn." on exactly the chips that have a
source — the annotation does not ship chunk bodies, but the fetch does).

**L4 — honest failure surfaces with a way out.**
- `PdfPage`'s red error overlay becomes a plain-language panel: what failed,
  the cited text below is still the verbatim source, **Open document ↗**
  (`/api/pdf/{docId}#page=N`, always accurate — it is the raw file), and a
  Retry button (re-runs the effect via a nonce).
- The DOCX/no-page surface keeps the backend's own sentence and gains the
  cited-text-forward layout it already has; no Open button there (there is no
  PDF; `/api/pdf` 415s by design).
- `Open ↗` stays in the loaded header as today.

**L5 — what does NOT change.** The client strict-bbox rule (loosening it is
how wrong-number highlights shipped pre-Wave-E); citation validation
(`retrieval/citations.py`); the annotation/linker (`citation/`); eval
scoring; `SourcePanel` (search page) behaviour beyond inheriting the union
bbox for new ingests.

## File map (two parallel lanes, disjoint)

- **Python lane:** `chunking/builders/narrative_chunk.py`,
  `app/routes/pdf.py` (get_chunk returns decoded `source_anchor`; new locate
  route), `tests/test_narrative_chunk.py`, new `tests/test_chunk_locate.py`.
- **Webapp lane:** `webapp/src/api.ts`, `webapp/src/pdf/PdfViewer.tsx`,
  `webapp/src/pdf/SourceView.tsx`, `webapp/src/pdf/PdfPage.tsx`,
  `webapp/src/styles/app.css`, tests under `webapp/src/pdf/__tests__/` and
  `webapp/src/chat/__tests__/`.

Gates: pytest, vitest, `tsc -b`, `npm run build`, Layer 1 eval (chunking
touched) with results committed.
