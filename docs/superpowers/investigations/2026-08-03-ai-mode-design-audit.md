# AI Mode — design-vs-implementation audit (gap report)

**Date:** 2026-08-03
**Scope:** AI Mode only (Destin's choice). The audit compares three documents
against the shipped code on the `chat-history` branch:
- the original overall design (`docs/superpowers/specs/2026-05-04-ask-the-budget-az-design.md`),
  **AI Mode sections only** (§3 Invariants, §5 data flow, §10 citation UX, §11 refusal, §12 audit log);
- the AI Mode UI redesign (`docs/superpowers/specs/2026-08-01-ai-mode-ui-redesign-design.md`), D1–D8;
- the chat-history design (`docs/superpowers/specs/2026-08-02-ai-mode-chat-history-design.md`), H1–H6 + A1.

**Method:** code reading only, cross-checked against STATUS.md's shipped/open
ledger. This is a written report, not a fix-list — nothing here is code that
was changed by this audit.

**Verbatim conventions:** In several places a later spec or a design decision
deliberately deviates from an earlier one. Where that happened I note the
deviation and treat the NEWER decision as authoritative, per the handoff's
instruction ("don't 'restore fidelity' naively" — the `Ai.tsx` header explicitly
warns against re-adding the removed S9 toggle).

---

## What shipped and matches its spec (no gap)

These were verified present and behaving as specified. Listed so the audit's
"gaps" section is read against a working baseline, not as a sweeping critique.

| Spec point | Shipped state | Evidence |
|---|---|---|
| §10.1 Inline citation rendering | Chips render at figure positions, numbered in reading order | `CitedMarkdownContent.tsx`, `CitationChip.tsx`, `placeFigures()` |
| §10.2 Hover tooltip (filename, page, fiscal year, verbatim quote) | Present, escapes the scroller via fixed positioning | `citation-annotation.ts` sources, `CitationChip.tsx` |
| §10.2 "Copy citation" button | Present, formats like `JLBC Baseline Book FY24, p. 47` | `CitationChip.tsx:371-444`, `formatCopyCitation` |
| §10.2 Click → PDF page + bbox highlight | Present; annotation now self-describing (docId, page_start, bbox) | `SourceView.tsx`, `PdfViewer.tsx` bbox prop |
| §11 Refusal "refusal_low_confidence" shape | Banner shows raw passages for unsourced answers | `RefusalBanner.tsx` `detectRefusal` ("synthesis"), `no_retrieval` |
| Core Invariant 2 (verified, visibly stripped) | Links verified; failed marks visibly, quote kept | `CitationChip.tsx` stale/`markUnresolvable`, `chat-cite-fail` |
| Core Invariant 5 (no "hallucination-free" language) | Honesty line verbatim, unsoftened | `Footer.tsx:74` "Answers are cited, not guaranteed. Verify against sources." |
| Redesign D1 one-column measure | `--ai-col` governs thread/banners/composer | `app.css`, `AiModePanel.tsx` |
| Redesign D2 one scroller + floating bottom chrome | Implemented; composer publishes measured height | `AiModePanel.tsx` `chromeRef` + ResizeObserver |
| Redesign D3 tool rows (not cards), coalesced, glyph-shape status | Implemented (~30px rows, grouping) | `ToolCard`/`tool-body`, `chat-css-contract.test.ts:152` |
| Redesign D5 presentation-only citation work | Extract logic untouched, tooltip via fixed/portal | `citation-extract.ts` unchanged per prior handoff |
| Redesign D6 bus last-value replay + close button | Both present | `citation-context.tsx` `lastRef`, `PdfViewer onClose` |
| Redesign D8 AiModeToggle deleted | Gone (imported by nothing but tests historically) | `webapp/src` |
| Chat-history H1 files-on-disk, no index | Implemented; write after turn + on abort | `harness/history.py`, `persist_turn` |
| Chat-history H2 lazy rehydration, free to browse | Implemented | `use-chat.ts` rehydration effect, `rehydrateTurns` |
| Chat-history H4 search prose only | Implemented, role-filtered | `harness/history.py::search`, `_SEARCHABLE_ROLES` |
| Chat-history H5 stale citation marked, quote kept | Implemented (click-time, two unresolvable shapes) | `PdfViewer` 404-vs-200 handling |
| Chat-history H6 keep everything, delete manual, no cap | Implemented | `harness/history.py`, `DELETE` route |
| Chat-history A1 rail (collapsible, auto-collapses on source open, persists) | Implemented | `HistoryRail.tsx`, `AiModePanel.tsx:137-147` |
| Chat-history rehydration restores citations | **NEW in this session (Handoff Issue 1)** — annotation now persisted and rebuilt | `HarnessSession._attach_annotation`, `rehydrateTurns` |

---

## Gaps — spec said it, code does not have it

### G1. Verify mode (§10.3 of the original design) — NOT built

**Spec:** "A toggle in the answer pane (off by default). When on, scrolling
the answer auto-scrolls the PDF viewer to follow each citation as it comes
into view. Synchronized scrollytelling for analysts auditing a long answer."

**Shipped:** No verify-mode toggle anywhere in `webapp/src`. Phase 2 is
`🔴 Not started` in STATUS.md, and the original design's §10.3 was part of the
v1 UX, not an explicitly-deferred Phase 2 item in the section that travelled
(§10.4 clearly defers DOCX "to Phase 2"; §10.3 has no such deferral marker).

**Status: GAP** — deferred implicitly, not recorded. Either build it (Phase 2)
or record the deferral in STATUS.md so it reads as a decision, not an omission.
This is the standalone's own "verify mode" ancestor mentioned in STATUS.md's
Phase 2 row ("distribution and verify mode remain").

### G2. Audit log (§12 of the original design) — NOT built

**Spec:** whole-turn audit record per assistant turn — user message, tool
calls + arguments, retrieved chunk IDs, reranker scores, chunks visible to
Claude, citations emitted, faithfulness verdicts, final rendered answer,
refusal type, latency, scoped under the conversation. Also: "Trust auditing
(analyst can ask 'show me everything I asked yesterday and the citations I
got')".

**Shipped:** `harness/ledger.py` is a **spend ledger** (per-user S19 cost
caps), a different thing. There is no whole-turn audit log: no persisted record
of retrieved chunks visible to the model, faithfulness verdicts, or refusal
type per turn. The closest is the persisted chat transcript (now including the
annotation, this session), which captures messages + tool calls + retrieved
text but NOT the post-generation faithfulness verdicts, RERANK/scores, or a
per-turn refusal-type audit field.

**STATUS.md is honest about this:** Plan 1c says "faithfulness verifier (WS3)
+ audit log (WS5) remain unbuilt and carry forward." So it is a **recorded**
gap, not a silent one — but it is still absent from the shipped AI Mode.

**Status: GAP (recorded).** The chat transcript that now persists is a solid
foundation for it — a faithful-verdict / refusal-type field could ride the same
`history` message the annotation now rides.

### G3. §10.2 "multiple rects for multi-region citations" — partial

**Spec:** "Yellow rectangle overlay painted on the precise bbox(es); multiple
rects for multi-region citations."

**Shipped:** a single `bbox` per chunk/source; `SourceView` restricts the
text-layer search to one bbox. The annotation's `AnnotationSource` carries a
single `bbox: number[] | null`, not an array of regions. Multi-region (the same
figure spanning two page regions) is not represented.

**Status: GAP (probably fine).** In practice a cited figure lives in one
region; the multi-rect case is rare. But the annotation schema has no slot for
it, so the original spec's "multiple rects" claim is not implementable today.

### G4. §10.5 Non-PDF (.docx) source rendering — NOT built (deferred)

**Spec:** server converts .docx to HTML on demand; citation chip resolves to a
DOM `id`.

**Shipped:** no DOCX viewer path. STATUS.md Phase 2 row confirms DOCX viewer
was deferred (and the original design's §10.5 explicitly said "deferred to
Phase 2"). This is a **recorded deferral**, not a gap — listed for completeness.

---

## Gaps-ish / deviations that are intentional (do NOT "fix")

These are places where the shipped code deliberately deviates from the
original spec. The audit catalogs them so a future reader doesn't mistake a
decision for a defect.

| Original/earlier spec | Shipped behavior | Why it's intentional |
|---|---|---|
| §4.2 / §9 "running YouCoded instance" chat host | In-process OpenRouter tool loop | Standalone consolidation retired the MCP/YouCoded architecture |
| §9 `cite(chunk_id, span_start, span_end, confidence, claim_span)` tool call per citation | Figure **linking** at turn end; model cites only prose; `citation/` package emits one annotation | Citation-linking redesign (2026-08-02), spec `2026-08-02-citation-linking-design.md` |
| §12 audit log via `messages`/`queries` tables (Postgres) | File-based transcript + spend ledger; no whole-turn audit table | Postgres deleted (Plan 5 Track 4); recorded in STATUS.md |
| Redesign D1 "compact navy band" with corpus chips + scope chip | Band deleted; corpus + tier moved to the tools menu | `Ai.tsx` header comment (Destin, 2026-08-02) — "the band's three items moved, not dropped" |
| Redesign D4 GitHub hljs global import replaced by owned code style | Owned navy/token `.chat-md .hljs-*` theme in `app.css:1228-1232`; no global `highlight.js/styles` import anywhere in `webapp/` | Design's own D4 requirement |
| Redesign D7 mascot clamps to available space | `.chat-welcome-mascot` clamps `max-height:min(420px,40dvh)` (`app.css:1102`) — the old `calc(100dvh - 440px)` hand-measured constant is gone | Design requirement |

---

## Chat-history follow-ups from its own spec — still open

The chat-history spec ends with two explicit "Follow-ups this creates":

1. **The Administrator Handbook needs a paragraph** — history writes analysts'
   questions to disk in plain text; the first exchange is sent to OpenRouter
   for naming. **`docs/HANDBOOK.md` does not exist yet** (Plan 5 Track 5 owns
   it; still open in STATUS.md Track 5). **Still open.**
2. **`MAX_CONVERSATIONS = 40` may want revisiting** once eviction is no longer
   data loss. `app/routes/conversations.py:59` still hardcodes 40, and the eviction
   is now non-destructive (transcripts persist). **Still open** — explicitly
   out of scope for the chat-history work.

---

## Observations relevant to the two issues already fixed this session

This audit ran in the same session as Handoff Issues 1 and 2, which are both
implemented on this branch:

- **Issue 1 (citations unlink on rehydrate)** was a real regression the audit
  confirms: the annotation existed only on the ephemeral `_done` frame, never
  in the transcript. Now persisted and rehydrated. The audit also surfaced that
  `_context_window` had no reason to carry it to the provider — that risk is
  now closed by `_strip_wire_annotation`.
- **Issue 2 (+ New chat no-op)** was a pure keying bug (nonce fix). No spec
  claim contradicted; it was an implementation defect.

---

## Recommended next actions (none done here — this is a report)

1. **Record G1 and G2 as explicit deferrals in STATUS.md** (verify mode and
   whole-turn audit log) so they read as decisions. G1 and G2 are the only two
   true "spec said it, code lacks it" gaps in the AI Mode scope.
2. **Decide on G3** (multi-region bbox) — likely "accept single region", and
   note it in the citation-linking spec if so.
3. **Track 5 (HANDBOOK)** — the confidentiality paragraph the chat-history spec
   requires exists nowhere yet; it is the one follow-up with a confidentiality
   implication.
4. Revisit `MAX_CONVERSATIONS = 40` when convenient — now that eviction is
   non-destructive it is merely a memory bound, but 40 concurrent in-memory
   Deep Research sessions is worth a sanity check.

---

## Priorities

In order of "would assert something false if left unrecorded":

1. **G2 (audit log) + G1 (verify mode)** — record as Phase-2 decisions; the
   shipped AI Mode is otherwise consistent with its own specs.
2. **Handbook paragraph** — confidentiality disclosure the chat-history spec
   promised but no file delivers.
3. G3 multi-region bbox — accept+note, or build.
