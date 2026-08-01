# AI Mode UI redesign — "One column, floating chrome"

**Date:** 2026-08-01
**Status:** Approved by Destin (design review in session; approach and all sections approved as presented)
**Scope:** `webapp/` only. No retrieval, harness, or prompt changes — the Layer 1 eval is NOT triggered by this work.

## Why

Destin's verdict on the shipped AI Mode page: tool cards are ugly and
disproportionate to the chat, there are extra scrollbars everywhere, the
citation viewer renders strangely, and there is a lot of wasted space. The
goal: make AI Mode feel polished and cozy the way YouCoded's native chat
does — while looking like a page of THIS app, not a YouCoded clone.

Three code audits back this up (AI Mode internals, YouCoded's renderer at
`~/youcoded-dev/youcoded/desktop/src/renderer`, and the app's own design
language). The findings below are the evidence base; the design responds to
them point by point.

### Decisions made in review (do not re-litigate)

| Decision | Choice |
|---|---|
| Depth of change | Structural redesign (not CSS-only, not a from-scratch rebuild) |
| Identity conflict | **App identity wins, YouCoded structure underneath** — colors/fonts/radii from the mockup's navy tokens; scroll model, tool-row compactness, spacing rhythm from YouCoded |
| YouCoded qualities to port | All four: compact tool rows, one scroll + pinned composer, warm visual texture, mascot & personality |
| Source panel behavior | Chat-first collapsible split (not overlay-only, not fixed 50/50) |
| Approach | A — "One column, floating chrome" (B "chat in a card" and C "defect pass only" rejected; C's fixes land as A's first commits) |

## The evidence (audit summary)

### Why tool cards feel disproportionate

- `.chat-tool` has no width cap → fills the 768px column while assistant
  prose caps at 65ch (~505px). The tool card is the widest element on
  screen, ~50% wider than the answer it supports (`app.css:811,830,983`).
- Card header is 14px — same as prose — with an 800-weight label.
- Three concentric 1px-bordered boxes (card → body → chunk row) with three
  different radii; a monospace face (`--chat-mono`) used nowhere else; a
  10px/uppercase/.06em "devtools" micro-label idiom across ten selectors.
- An expanded RetrieveView is taller than the answer it produced.

### Why there are extra scrollbars (12 scroll containers found)

- `.chat-thread-scroll` (`app.css:806`) lacks an `overflow-x` guard —
  `overflow-y:auto` computes `overflow-x:auto`. The 320px citation tooltip
  (`app.css:926`) is absolutely positioned inside it; near the right edge it
  spawns a horizontal scrollbar, and near the top it is CLIPPED by the
  scroller (z-index cannot escape an ancestor's overflow). One root cause,
  two symptoms: "weird scrollbars" and "citations render strangely".
  (The fiscal-notes page fixed this exact bug for `.yscroll` at
  `app.css:541-545`, with a comment.)
- `.chat-welcome` is a second, separate scroller for the empty state.
- Nested live scrollers: `.chat-error-body` (192px) inside a tool card
  inside the thread; `.chat-cite-quote` (96px) inside the tooltip — up to
  4 stacked scroll contexts.
- `.pdf-scroller` double-scrollbar: canvas width is fixed px, so a vertical
  bar makes the canvas no longer fit → horizontal bar appears too.
- YouCoded has exactly ONE scroll container; header and composer float
  over it and the scroller carries matching padding.

### Citation viewer defects

- **First chip click shows an empty panel.** The citation bus
  (`chat/citation-context.tsx`) has no last-value replay; `PdfViewer`
  subscribes in an effect that runs only after it mounts — which happens as
  a RESULT of the same click. The user must click twice. No test covers it.
- Hard 50/50 split, no close control (intentional per comment at
  `AiModePanel.tsx:204-208`, reversed by this design); below 860px the
  panel `display:none`s with no fallback.
- Page renders 24px narrower than fit-to-width: `SourceView.tsx:111` seeds
  width from `clientWidth` (includes padding) but the ResizeObserver writes
  `contentRect.width` (excludes it), then both subtract a constant 24.
- Four stacked background bands; two consecutive white toolbars (crumb +
  toolbar) before any page pixels.
- `.pdf-cited-text{max-height:34vh}` — viewport units inside a panel that
  is not viewport-tall.
- `.pdf-empty` holds an unclamped 240×420 mascot that overflows and is
  clipped by the panel's `overflow:hidden`.

### Wasted space

- Three unaligned grids: subhero content centered at 1140px, stage
  full-bleed (`app.css:1447`), thread at 768px centered in the bleed.
  The h1, the messages, and the corpus note share no edges.
- ~271px of fixed chrome above/below the thread; ~576px of empty canvas
  per side on a 1920px window.
- The mascot slot (`right:calc(50% + 400px)`) needs a ≥1040px content box;
  opening the source panel clips the mascot entirely off-screen.
- RefusalBanner, the error notice, and SuggestionRow render OUTSIDE the
  scroller, permanently stealing thread height while visible.
- `.chat-welcome-mascot`'s clamp uses a hand-measured `440px` constant that
  silently breaks when any chrome height changes (admitted in the comment
  at `app.css:882-890`).

### Design-language divergences (vs the mockup tokens and ported pages)

Radii 4/6/8/10px vs the app scale 22/16/12/pill; five color sources on one
page (tokens, `--chat-*` trio, `--mascot-*` nine, hardcoded PDF ambers,
GitHub's hljs theme); no shadows where every other surface carries
`--shadow-sm`; no card/head-row grammar; hover via opacity/ink instead of
the app's azure border/text language; 9-10px type below the app's 11px
floor. Already-faithful pieces worth preserving: the input focus recipe,
tier switch (re-scoped `.chswitch`), corpus chips (subhero `.chip` recipe),
tier popover (`.sortmenu` recipe), `.ai-gate` on the shared `.card`.

### What YouCoded does that this design ports (in app tokens)

- Tool calls are ~28px single-line rows, collapsed by default; status is
  carried by GLYPH SHAPE, not color; a pure `friendlyToolDisplay()` turns
  raw args into a sentence + a `↳` muted detail; 2+ consecutive tools
  coalesce into one row ("4 tools (Read, Grep ×2) — all complete").
- One scroll container; floating chrome publishes its measured height into
  a CSS var and the scroller pads by it, so content slides behind.
- Intent-driven autoscroll: a ref (not state) is the source of truth;
  unstick synchronously on wheel-up/touch-drag/scrollbar-grab; re-arm only
  within 32px of the true bottom; ResizeObserver re-pins on local growth.
- Texture through restraint: no shadows in the conversation (depth = a
  surface ramp + 1px hairlines), ~150ms color fades and almost no other
  motion, one bubble radius with a squared "tail" corner, spacing that
  encodes turn structure.

## The design

### D1 — Page skeleton & one alignment grid

Keep the full-height pinned page (`html.ai-fullpage`). Below `header.site`:

1. A **compact navy band** (subhero identity retained, one row tall):
   "AI Mode" title, the two corpus chips, the scope chip. The corpus-switch
   warning moves out of the far-right dead zone into a subline/tooltip on
   the chips.
2. The **chat region** filling the rest of the viewport.

**One content measure.** A single CSS var (`--ai-col`, ~768px) governs the
band's inner content, the thread column, in-flow banners, and the composer.
Everything shares one left edge. When the source panel opens, the chat
region narrows and the column re-centers within it — the only permitted
line-length change, and it is user-triggered.

### D2 — Scroll model: one scroller, floating bottom chrome

- `.chat-thread-scroll` is the ONLY scroll container. Add
  `overflow-x:hidden`.
- The welcome/empty state renders INSIDE the scroller (delete the second
  scroller `.chat-welcome`'s own overflow).
- The composer block — tier switch, message input, stop button, suggestion
  chips, honesty line — becomes floating bottom chrome positioned over the
  scroller. It measures its own height into a CSS var via ResizeObserver;
  the scroller carries that var as bottom padding. One variable, no
  z-index stacking arithmetic.
- **RefusalBanner moves into the thread flow**, rendered after the turn it
  evaluates. Autoscroll makes it visible when it appears; it scrolls away
  with history instead of permanently shrinking the thread. Its detection
  logic is untouched.
- The transient error notice stays in the bottom chrome, compact.
- Autoscroll adopts the intent-driven stick model: `stickRef` as source of
  truth; unstick synchronously on wheel-up / touch-drag-down; re-arm when
  within 32px of the true bottom (debounced ~90ms); a ResizeObserver on the
  content wrapper re-pins on local growth (a tool row expanding at the
  bottom); sending a message re-arms. The wheel-physics port (momentum
  synthesis, burst acceleration) is explicitly NOT ported — browsers
  provide native scrolling.
- Add a jump-to-bottom pill: `--canvas` bg, `--r-pill`, `--shadow`,
  floating above the composer chrome.
- Nested-scroller diet inside the thread: `.chat-block pre` loses its
  pointless `overflow:auto` (it is `pre-wrap`); `.chat-error-body` and long
  tool output adopt the capped-lines + "Show N more lines" expander pattern
  instead of inner scrollbars (see D3).

### D3 — Tool rows, not cards

`ToolCard` becomes a compact single-line row (~30px):

- **Row shell:** 1px `--line` border, `--r-sm` (12px), `--card` bg,
  padding 6px 12px, 12.5px text. No shadow. Max width = the prose measure
  (tool rows must never be wider than the answer).
- **Anatomy, left→right:** the existing 12×12 pixel-glyph (status by
  SHAPE — spinner/check/cross — colored neutral `--ink-3`; only the FAILED
  state keeps `--chat-danger`, because Invariant 3 wants failure loud and
  success quiet) · friendly label, 700 weight, `--ink-2` ("Searched budget
  corpus") · truncated `↳ ` detail in `--ink-3`, `flex:1` · a rotating
  chevron (the monospace `+`/`−` toggle is deleted).
- **Grouping:** 2+ consecutive tool calls in one turn coalesce into a
  single row of identical geometry — label like "3 searches — all
  complete", names coalescing as `retrieve ×3`, with a running/failed
  count suffix while in flight. Expanding reveals child rows on a
  `--canvas` inset. A single tool renders bare (no group chrome).
- **Expanded bodies** keep the five views (RetrieveView, CiteView,
  ListFilterValuesView, CreateDocumentView, RawFallbackView) with these
  changes: body recessed to `--canvas` separated by a hairline (no more
  triple-nested bordered boxes — chunk rows separate with 1px dashed
  hairlines like the app's `.ctx` tray rows); long output capped at ~20
  lines with a "Show N more lines" expander; the 10px/.06em micro-labels
  replaced by the app's canonical 11px/800/uppercase/.08em idiom
  (`app.css:550`); `--chat-mono` reserved for code and chunk ids only.
- Collapsed by default, click anywhere on the row to toggle.

### D4 — Messages, rhythm, texture

- **Depth via surface ramp, not borders-on-borders:** chat region on
  `--canvas`, bubbles on `--card`.
- **Assistant bubble:** `--card`, 1px `--line`, radius 16px with a 4px
  tail corner (keeps the tail idiom, lands on the token scale). Max-width
  65ch as today.
- **User bubble:** solid `--navy`, `#fff` text, 16/4 mirrored tail —
  matches the app's solid-navy "active" convention (`.fbill-no`,
  `.chseg .on`) and reads warm against the pale canvas.
- **Spacing on one scale:** 24px between turns, 8px within a turn, 4px
  between stacked tool rows. (Replaces the current 4/8/12/20 mishmash from
  three uncoordinated sources.)
- **Radii from the token scale only:** 16 (bubbles), 12 (tool rows,
  inputs), pill (chips, buttons). The literal 4/6/8/10px radii are
  removed, except the 4px tail corner and tiny cite-chip radii.
- **Shadows:** none on bubbles or tool rows; `--shadow-sm` on the floating
  composer chrome; `--shadow` on tooltip/popovers. (Matches both YouCoded's
  restraint and the app's two-shadow rule.)
- **Hover language:** 150ms color fades using the app's azure recipe —
  border→`--az-gold`, text→`--az-gold-d` — replacing the chat block's
  opacity/ink hovers.
- **Type floor:** nothing below 11px. The 9px cite superscript may stay
  (it is a superscript, not body text).
- **Syntax highlighting:** the global GitHub hljs import
  (`MarkdownContent.tsx:20`) is replaced by a small owned, navy-tinted
  code style — removes the fifth color source on the page.
- **Status palette:** the `--chat-danger/warn/ok` trio STAYS (the
  documented safety exception at `app.css:741-749` holds: a monochrome
  navy palette has no error color, and failed citations must be
  unmistakable) but is confined to failure/refusal semantics. Running/
  complete tool states, decorative accents, and anything non-safety go
  neutral or azure.

### D5 — Citation chips & tooltip

- Extraction logic and the ~70 carried specs in
  `webapp/src/chat/citation-extract.ts` are UNTOUCHED. Presentation only.
- The tooltip renders via a **portal** (or `position:fixed` anchored to
  the chip) so it escapes the scroller — one change fixes both the
  clipping at the top of the thread and the phantom horizontal scrollbar.
- Chip colors align to the app hover language; failed chips keep the
  danger treatment (Invariants 1–3).

### D6 — Source panel: chat-first collapsible split

- **Sizing:** when open, chat keeps a comfortable fixed share
  (`min(720px, ~45%)`); the panel takes the remainder. Not resizable by
  drag (YAGNI).
- **Close button** in the panel header; any chip click reopens.
- **Citation bus gains last-value replay:** the bus stores the most recent
  selection; a subscriber receives it immediately on subscribe. Fixes the
  first-click empty panel. Regression test at the `AiModePanel` level (the
  existing test mounts `PdfViewer` directly and cannot see this bug).
- **One header row:** crumb + toolbar merge — breadcrumb left; zoom,
  open-external, close right. Removes one of the two stacked white bands.
- **Fit-to-width fixed:** one box model (use `contentRect` consistently,
  drop the constant 24), so 1.0 zoom actually fills the container.
- **Cited-text panel:** fixed px cap (not `vh`), plus a collapse toggle.
- **Below 860px:** the panel becomes an overlay drawer reusing the Search
  page's existing `SourcePanel`/`.pdf-drawer` chrome — consolidating the
  two viewer chromes around the one `SourceView` — instead of
  `display:none`.
- The `.pdf-empty` mascot state clamps to its container; the
  UnresolvedState copy is rewritten in plain language (chunk ids demoted
  to a secondary detail line, not the headline).

### D7 — Mascot & personality

- All poses stay (wave/idle/typing/presenting).
- The welcome mascot clamps against real available space (flex-based
  sizing inside the scroller), replacing the hand-measured
  `calc(100dvh - 440px)` constant.
- The thinking/presenting mascot docks left of the column ONLY when the
  chat region is wide enough to fit it fully (region width ≥ column +
  mascot + gutter), else it fades out — no more clipping when the panel
  opens. Implemented with a container-width check, not viewport media
  queries (the trigger is the panel, not the window).
- The honesty footer line survives as a single 11px muted line inside the
  bottom chrome; the separate banded `chat-footer` element is deleted.

### D8 — Dead code & CSS cleanup (in scope)

- `AiModeToggle` (imported by nothing but its tests) — delete, per the
  standing note in STATUS.md.
- Dead/overridden CSS: the `.ai-panel` fallback block (`app.css:1422-1431`)
  whose every declaration except `overflow:hidden` is undone downstream;
  the duplicated `.has-source` divider rule; `.mascot-typing-hand`.
- The three `translate()` offsets papering over the three mascot widths
  go away with D7's placement model.

## Guardrails (Core Invariants preserved behaviorally)

- Failed citations remain visibly marked (chips, tooltips, danger color).
- RefusalBanner's detection logic is unchanged — placement only.
- The honesty line ("AI answers can be wrong…") is kept verbatim.
- No marketing language is introduced anywhere in copy.
- The DOCX-citation error path keeps showing the backend's sentence (the
  known follow-up about pdfjs's raw error in AI Mode may be fixed in
  passing via `api.chunk()` in `PdfViewer.Loaded`, since D6 touches that
  file).

## Testing & verification

- Bus replay, first-click behavior, panel open/close, and the overlay
  fallback get new specs; affected existing vitest specs (304 today) are
  updated stage-by-stage, never bulk-deleted.
- Citation-extract, chat reducer, and SSE plumbing are not modified;
  their suites must pass unchanged.
- Human-at-a-browser pass at the end (the audit's rendering findings are
  exactly the class jsdom cannot see): tooltip near thread top/right edge,
  first chip click, panel open at 1440px and 1920px, mascot behavior with
  panel open, sub-860px drawer.

## Sequencing (for the implementation plan)

1. **Defect pass** (Approach C absorbed): `overflow-x` guard, tooltip
   portal, bus replay + first-click test, PDF fit-to-width fix, close
   button, dead CSS/component deletion.
2. **Skeleton:** one grid, compact band, floating bottom chrome, single
   scroller, welcome-inside-scroller, banner relocation, stick model,
   jump-to-bottom.
3. **Tool rows:** row shell, friendly display, grouping, body diet.
4. **Messages & texture:** bubbles, spacing scale, radii, hovers, code
   style.
5. **Source panel:** split sizing, merged header, cited-text cap, drawer
   fallback, empty/unresolved states.
6. **Mascot & polish:** clamps, docking rule, honesty-line merge.

Work in a git worktree per CLAUDE.md. Each stage merges only with its
tests green; stage 1 is independently shippable.
