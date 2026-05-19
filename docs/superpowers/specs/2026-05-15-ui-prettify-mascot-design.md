---
title: Web UI Refresh + JLBC Mascot — Design Spec
date: 2026-05-15
status: shipped (with post-implementation reconciliation — see bottom)
authors: Destin Moss, Claude
audience: design implementers, future contributors
---

> **Reading note (2026-05-19):** the spec below is the approved design as
> authored before implementation. During build the design pivoted on
> several iterations — single-mascot architecture, speech-bubble messages,
> seated typing scene, etc. The **Post-implementation reconciliation**
> section at the bottom records what shipped vs. what is specified above;
> read that first if you only want to know the current state.

# Web UI Refresh + JLBC Mascot — Design Spec

A visual refresh of the Ask the Budget AZ web app (`web/`), introducing an independent
"civic-warm" visual identity and a pixel-art mascot — a Funko-style JLBC analyst — that
acts as a reactive stage character across the UI.

This is a **presentation-layer** spec. It does not touch retrieval, citation
verification, the MCP server, or any Core Invariant. All work lives under `web/`.

## Goals

- Give the app its own visual identity, **independent of YouCoded's theme system**
  (the current `globals.css` deliberately mirrors YouCoded; that parity is dropped here).
- Introduce the JLBC mascot as a "stage character": full-size on the welcome screen,
  a small persistent presence during conversations, and reactive to app state.
- Replace the plain thinking spinner with a mascot-typing-on-a-laptop animation.
- Touch every conversation surface — header, bubbles, tool cards, citation chips,
  refusal banner, input, footer — so the new identity is coherent.

## Non-goals / out of scope

- No change to retrieval, the eval set, the MCP server, faithfulness verification,
  or any backend behavior.
- No change to the PDF viewer's render logic (only its empty/loading states get
  restyled).
- The mascot's source render (the uploaded Funko PNG) is **not** used as a runtime
  asset — the mascot is rebuilt from scratch as layered SVG so it can be posed and
  animated. The PNG was reference only.

## Core Invariant compliance

This refresh must not weaken any Core Invariant. Two are directly relevant:

- **Invariant 3 (Refusal beats hallucination):** the refusal state gets a *more*
  prominent, on-brand treatment (the crossed-arms mascot + amber banner) — refusal is
  surfaced, never hidden.
- **Invariant 5 (No "hallucination-free" / "grounded" marketing language):** the new
  footer carries an explicit honesty line — "Answers are cited, not guaranteed.
  Verify against sources." No copy anywhere may claim the system is hallucination-free.

---

## §1 — Theme system + typography

### Theme system

`web/app/globals.css` is **rewritten outright**. The four mirrored YouCoded themes
(`light`, `dark`, `midnight`, `creme`) and the "mirror YouCoded per D9" comment block
are removed. The file defines exactly **one** theme — civic-warm light, the Paper &
Civic Blue palette. There is no dark mode and no theme switching: the app is internal,
desktop-first, and the paper aesthetic is the identity.

The existing token *names* are preserved (`--canvas`, `--panel`, `--inset`, `--well`,
`--accent`, `--on-accent`, `--fg`, `--fg-2`, `--fg-dim`, `--fg-muted`, `--fg-faint`,
`--edge`, `--edge-dim`, `--code`, `--link`, `--link-hover`) so existing components
re-paint without rewrites.

New tokens added:

- `--mascot-cap`, `--mascot-skin`, `--mascot-suit`, `--mascot-skin-shadow`,
  `--mascot-skin-hi`, `--mascot-cap-hi`, `--mascot-brim` — the mascot reads these so
  it themes cleanly and has no per-component palette duplication.
- `--success`, `--warning`, `--danger` — semantic status tokens (today only raw
  `green-400` / `amber-700` / `red-400` literals exist).

Palette anchors: canvas `#fbf7f0`, panel `#efe9dc`, accent / civic-blue `#3a6ea5`,
fg `#1f2937`.

The `data-theme` attribute on `<html>` is removed — there is only one theme, so the
tokens live directly on `:root`.

### Typography

Three faces, loaded via `next/font/google` (self-hosted, inlined, no FOUT, no CDN
dependency):

- **Source Serif 4** — headings, welcome copy, section labels. Civic-document feel.
- **Inter** — body text, UI controls, message text.
- **Cascadia Mono** (already present) — code, citation IDs, monetary values, tabular
  data, session IDs. Kept for exactly what mono is good at.

Tailwind `@theme` maps these to `--font-serif`, `--font-sans`, `--font-mono`.

---

## §2 — Mascot visual design + asset system

### Visual design

The mascot is a **pixel-art Funko-style figure**: the JLBC analyst — bald, glasses,
dark suit, light-blue ball cap reading "JLBC". Style is "civic-warm pixel" (a 24×32
chunky sprite grid, ~10px cells), palette-matched to the Paper & Civic Blue theme.

It is built as **layered SVG**, never a raster image. Every part is its own group so
parts can be swapped, recolored, and animated independently. Fills reference CSS
variables (the `--mascot-*` tokens) so the mascot themes with the app — and so the
`<use>` shadow-DOM class-selector trap is avoided (variables cascade through `<use>`;
class selectors do not).

### Poses

Front-view poses (shared body + swappable arms):

- `sides` — arms at sides (built, not wired to a trigger in v1)
- `clasped` — hands clasped front; the default idle pose
- `wave` — one hand raised; welcome state
- `crossed` — arms crossed; refusal state
- `clipboard` — holding a clipboard; result-settled state
- `hips` — hands on hips (built, not wired in v1)

Two full alternate scenes (not arm-swaps — different compositions):

- **side-typing scene** — mascot in left-facing profile, typing on a sleek aluminum
  laptop. Laptop is desk-scaled (~64×72, roughly 60% of torso width), lid at a
  comfortable ~110° back-lean, screen face toward the mascot, hinge at the far end of
  the keyboard, one hand on the keys. Laptop drawn in the same pixel-block language as
  the mascot.
- **front-presenting scene** — mascot turned to face the viewer, the laptop tilted
  forward so its screen (showing the answer + a citation chip) faces the viewer.

### File layout

New folder `web/components/mascot/`:

```
mascot/
  Mascot.tsx            // front-view mascot: composes Body + chosen arms
  MascotBody.tsx        // shared body — head, cap, glasses, face, torso, base
  MascotTyping.tsx      // the side-typing laptop scene
  MascotPresenting.tsx  // the front-presenting laptop scene
  poses/
    ArmsSides.tsx
    ArmsClasped.tsx
    ArmsWave.tsx
    ArmsCrossed.tsx
    ArmsClipboard.tsx
    ArmsHips.tsx
  types.ts              // MascotPose, MascotSize
  useMascotPose.ts      // app-state -> pose/scene orchestration hook
```

### Component API

```ts
type MascotPose = 'sides' | 'clasped' | 'wave' | 'crossed' | 'clipboard' | 'hips';
type MascotSize = 'hero' | 'chip' | 'tiny';
```

```tsx
<Mascot pose="wave" size="hero" />
<Mascot pose="clasped" size="chip" animate={false} />
<MascotTyping />        // self-contained animated scene
<MascotPresenting />    // self-contained scene
```

Sizes: `hero` 240×320 (welcome), `chip` ~40×54 (header + persistent nook),
`tiny` ~24×32 (inline in refusal banner / citation contexts).

Accessibility: each mascot SVG carries `role="img"` and
`aria-label="JLBC budget assistant"`.

### Animation model

Pixel art is **never tweened** (sub-pixel interpolation blurs it). All motion is
frame-based — discrete swaps. Idle motion:

- **bob** — a 2-frame 1px vertical shift, ~3.2s loop; always on for static poses.
- **blink** — eye rects swap to skin color for ~150ms; random every 3–6s.
- **push-glasses** — rare idle "moment": the right arm briefly raises and the glasses
  shift up a notch; random every 15–25s. (Chosen from a larger menu; the only
  non-blink idle moment included in v1.)

The side-typing scene animates a continuous finger-tap (hand drops 2px on press) plus
a blinking screen cursor. Pure CSS keyframes on SVG sub-elements — no JS rAF loop
needed for the scene itself; the idle bob/blink/push-glasses timing is driven by the
`Mascot` component.

### Orchestration

`useMascotPose(chatState)` is the **single** place that decides which pose/scene
shows. Components never decide their own pose — they render what the hook returns.
The full mapping is §5.

---

## §3 — Welcome hero (Layout A — centered stack)

The empty/welcome state, shown before any conversation exists. Centered vertical
stack:

1. Header bar (small mascot chip + "Ask the Budget AZ" brand).
2. Mascot, `hero` size, `wave` pose, centered.
3. Headline (Source Serif): "Hi — let's look at the budget."
4. Sub-copy (Inter): one sentence naming the four publishers and the citation promise.
5. Primary input (the message box), civic-blue "Ask" button.
6. A "try one of these" label + 3 suggestion chips with example queries.

Suggestion chips, when clicked, populate the input with that query. Chip copy uses
real example questions (e.g. "What was the FY2025 Aviation Fund balance?").

---

## §4 — Conversation chrome

The in-conversation UI. All surfaces re-skinned to the civic-warm theme.

### Header

Slim bar: small mascot chip (pose mirrors current app state) + "Ask the Budget AZ"
brand (Source Serif) on the left; on the right, a `close source panel` ghost button
(only when the panel is open) and the truncated session id (Cascadia Mono).

### Message bubbles

- **User message** — right-aligned, civic-blue (`#3a6ea5`) fill, `--on-accent` text,
  asymmetric radius (`12px 12px 4px 12px`).
- **Assistant turn** — left-aligned, rendered directly on the canvas (no bubble),
  Inter body text. Monetary values and citation IDs render in Cascadia Mono.

### Tool card

Collapsible card: header strip with a per-tool pixel-art glyph, the tool name (Inter
semibold), and right-aligned meta (chunk count / duration, Cascadia Mono). Body shows
the call detail in mono. Civic-blue accent; **red accent if the tool call errored**.

### Citation chips

Inline pills, Cascadia Mono. Passing citation: civic-blue border + tinted fill,
hover inverts to solid civic-blue. **Failed citation: red border, red text,
strikethrough** — visibly stripped per Invariant 2, never silently dropped.

### Refusal banner

Amber-bordered card (`--warning`) containing the `tiny` crossed-arms mascot inline +
a short refusal message in the mascot's voice ("I can't ground that one.") + the
existing raw-chunks affordance. The header chip and persistent nook mascot also
switch to the crossed-arms pose for the duration.

### Persistent mascot nook

A small (`chip` size) front-view mascot floats in a fixed bottom-left nook, above the
footer, present throughout the conversation. Its pose is driven by `useMascotPose`.
The nook is **hidden during the thinking state** — the inline side-typing scene is
the mascot at that moment, so two mascots would be redundant.

### Input

Message box: white fill, civic-blue 1.5px border, civic-blue focus ring, civic-blue
"Ask" button. Disabled state (no conversation / connecting) keeps the existing
placeholder messaging.

---

## §5 — Animation triggers + state→pose map

`useMascotPose` resolves exactly one row:

| App state | Mascot location | Pose / scene | Sub-animation |
|---|---|---|---|
| Welcome (no conversation) | Hero, large, centered | `wave` | bob + blink + push-glasses |
| Idle (conversation open, awaiting input) | Nook (chip) | `clasped` | bob + blink + push-glasses |
| Thinking (`isThinking`) | Inline in thread | side-typing scene | finger-tap + screen cursor |
| Result landing (~1.5s) | Inline in thread | front-presenting scene (hard-cut from side-typing) | screen cursor blink |
| Result settled | Nook (chip) | `clipboard` | bob + blink + push-glasses |
| Refusal (last assistant msg is a refusal) | Nook + header chip + banner | `crossed` | bob + blink |
| Error (existing red error bar) | Nook (chip) | `clasped` (neutral) | bob + blink |

### The handoff beat

When `isThinking` flips false **and** the turn produced a grounded answer, the inline
side-typing scene **hard-cuts** (no fade, no spin — a clean instant swap, pixel-art
correct) to the front-presenting scene for ~1.5s — the "here's what I found" moment,
laptop screen turned to the viewer. Then the scene collapses, the answer text renders
in the thread, and the nook mascot settles to `clipboard`. On a refusal, there is no
presenting beat — it goes straight to the crossed-arms refusal banner.

### Trigger rules

- *bob* — always on, any static pose
- *blink* — random 3–6s, static poses only
- *push-glasses* — random 15–25s, static poses only
- *finger-tap + cursor* — continuous, only during the thinking scene
- *hard-cut transition* — fires once per turn, on successful completion

### Reduced motion

`prefers-reduced-motion: reduce` halts bob, blink, push-glasses, finger-tap, and the
hard-cut. **Poses still change with state** — pose is information, not decoration —
they just snap with no sub-animation, and the thinking scene shows a single static
frame.

---

## §6 — Footer + tertiary touches

### Footer

A slim (~26px) bar below the input, muted Cascadia Mono:

- Left: `Sources: JLBC · AGAO · AZ Legislature · Governor's Office`
- Center: the honesty line — `Answers are cited, not guaranteed. Verify against sources.`
- Right: a connection dot (green = YouCoded connected, red = down) + corpus stat
  (e.g. `382 docs · FY2024–26`).

The nook mascot floats above the footer's left edge; the footer stays slim so they
don't collide.

### Tool card glyphs

Tiny pixel-art glyphs, cohesive with the mascot:

- `retrieve` → pixel magnifier
- `cite` → pixel bookmark/page
- `list_filter_values` → pixel list
- unknown tool → the civic-blue square dot (current fallback)

### Citation chip → PDF panel transition

On chip click: a quick (~250ms) scale-up + civic-blue glow on the chip, plus a faint
ghost trail toward the source panel as it opens. `prefers-reduced-motion` → panel
opens with no motion.

### Tertiary touches

- Civic-blue 2px focus rings on all inputs and buttons.
- Scrollbars retuned to the civic palette.
- Empty source-panel state: a small `clipboard`-pose mascot + "Click a citation to
  see its source."
- PDF panel loading: a civic-tinted shimmer skeleton.
- `close source panel` link restyled as a proper small ghost button.

---

## Files touched

**Rewritten:** `web/app/globals.css`, `web/app/layout.tsx` (font wiring),
`web/app/page.tsx` (welcome hero + nook + footer layout).

**New:** `web/components/mascot/` (12 files per §2).

**Restyled (no logic change):** `ChatThread.tsx`, `UserMessage.tsx`,
`AssistantTurnBubble.tsx`, `MessageInput.tsx`, `ToolCard.tsx`,
`tool-views/primitives.tsx`, `CitationChip.tsx`, `RefusalBanner.tsx`, `PdfViewer.tsx`
(empty/loading states only).

**New small components:** a `Footer.tsx`, a `WelcomeHero.tsx`.

## Testing

- Vitest: `Mascot.test.tsx` — every pose renders, accessibility attributes present.
- Vitest: `useMascotPose.test.tsx` — every state→pose row in the §5 table.
- Vitest: a snapshot per pose at default size.
- Existing vitest suite (109 tests) must stay green — restyle is class/markup only.
- Manual: run the dev server, verify welcome → thinking → answer → refusal flow in a
  browser, including `prefers-reduced-motion` on.

## Deferred

- `sides` and `hips` poses (built, unwired).
- The other idle moments from the brainstorm menu (coffee, look-sideways, lightbulb,
  stretch, smile, tip-cap) — only blink + push-glasses ship in v1.
- Animated transitions beyond the one hard-cut handoff beat.

---

## Post-implementation reconciliation (2026-05-19)

The spec above is the design as approved before implementation. During build the
design pivoted across several user-feedback iterations. This section records what
shipped vs. what is specified above — for future contributors reading the spec.
The branch is `ui-prettify-mascot`.

### 1. Single-mascot architecture (replaces three concurrent placements)

§4 placed three concurrent mascot instances on screen: a header chip mascot, a
persistent bottom-left "nook" mascot, and the inline scene during thinking.
**Shipped:** exactly one instance at any moment, position state-driven —

- Welcome → hero mascot centered.
- Thinking → `MascotTyping` centered.
- Presenting → `MascotPresenting` centered.
- Idle / Result / Refusal / Error → a `small` mascot pinned to the **left** of the
  chat thread, persistent while messages scroll. Messages render to its right.

The header chip and the bottom-left nook are removed entirely. `useMascotPose` still
drives the choice; the consumer just reads `mascot.kind` and `mascot.pose` and picks
one render slot.

### 2. Speech-bubble assistant messages (reverses §4's "bare on canvas")

§4 specified the assistant turn would render bare on the canvas (no bubble). The
single-mascot pivot reintroduced a bubble for each assistant text block — class
`.speech-bubble` with a left-pointing CSS triangle tail toward the mascot avatar —
so messages read as spoken by him. Tool cards and citation chips are unchanged.

### 3. MascotTyping is a seated working-loop scene (replaces standing side-typing)

§2 described MascotTyping as a left-profile mascot standing at an aluminum laptop
with a card-D ~110° lid and a finger-tap loop. **Shipped:** a seated side view at a
modern task chair, laptop on the lap, with a 12-second behavioral loop — types ~8s
(mitten hands tapping alternately), pauses, head lifts to "think" with a small
ponder shift, head returns, typing resumes. The laptop was rebuilt as chunky
axis-aligned rect pixel-art (no polygons), matching the rest of the mascot's style.

### 4. Take-3 round clear glasses + eyebrows (replaces rectangular pixel glasses)

§2's mascot used rectangular pixel glasses without eyebrows. **Shipped:** round
`<circle>`-stroke frames with skin-tone "clear" lenses, distinct round pupils with a
white catch-light glint, and short eyebrow strokes — chosen by user via a 4-take
comparison page. The push-glasses idle moment was updated so the eyebrows and eyes
stay fixed; only the frame translates up onto the forehead.

### 5. Take-C low-curved wave arm (replaces straight raised arm)

§2's `wave` pose was a straight raised arm. **Shipped:** a low, three-segment
stepped-rect curve sweeping out to an open mitten hand at shoulder/chin height,
never crossing the face — chosen via a 4-take comparison page after one earlier
4-take round of straight-arm variants was rejected.

### 6. Mascot has legs; canvas grew 320 → 420

§2 sized the mascot at viewBox `0 0 240 320` (head + cap + torso, no legs, base
shadow). **Shipped:** the figure has standing legs (suit trousers + suit-shadow
shoes). The shared viewBox is now `0 0 240 420`. `MASCOT_DIMENSIONS` gained a
`small` size (120×210) used for the left avatar in the has-messages layout. The
base ground-shadow ellipses are removed.

### 7. Page-shell layout polish (post-Task-18 iteration)

After Task 18's automated checks passed, the user iterated on the shell:

- `html`/`body` have `overflow: hidden` and `overscroll-behavior: none` — the page
  itself never scrolls; only the chat thread (and the PDF viewer) scroll internally.
  The outer page `<div>` adds `h-screen overflow-hidden`.
- The header brand "Ask the Budget AZ" is centered (3-column grid: empty left,
  centered brand, right-aligned controls).
- The suggestion chips float on the canvas above the input panel (not inside it),
  centered via `mx-auto w-fit` inside `overflow-x-auto` — native two-finger
  trackpad horizontal scroll works when chips overflow.
- The input bar sits in its own bordered/panel container directly above the footer.
- The footer is locked at the very bottom of the page.

### 8. Throwaway preview routes removed

During iteration the workspace held several throwaway Next.js routes used as
side-by-side comparison pages: `/mascot-preview`, `/mascot-glasses`, `/mascot-wave`,
`/mascot-sit`. These were never committed and have been deleted before the branch
was wrapped up.

### Not changed

The Core Invariants are intact. The honesty line and the `crossed`-arms refusal
banner ship as specified. The state→pose decision logic in `useMascotPose`, the
bob / blink / push-glasses idle moments, and `prefers-reduced-motion` handling all
match §5. The civic-warm theme + Source Serif 4 / Inter / Cascadia Mono typography
(§1) shipped as designed.

### Items deferred past this branch

- **Refusal auto-detection wiring (Phase 1c WS5).** The `crossed`/`refusal` mascot
  path is built and unit-tested; `useMascotPose` takes an explicit
  `refusalActive: boolean` so WS5 can flip the flag once auto-detection lands. v1
  passes `false`.
- **Faithfulness verifier (Phase 1c WS3).** Independent of this refresh.
- **Eval expansion (Phase 1c WS7).** Blocked on volume corpus.
