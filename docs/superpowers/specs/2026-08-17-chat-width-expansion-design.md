# Chat Width Expansion Design

Date: 2026-08-17
Status: Implemented — all 8 changes landed, suite green, build green. Pending commit.
Scope: Webapp only (AI Mode chat surface). No backend, ingestion, retrieval, or harness changes.

## 1. Problem

On a wide screen (e.g. the 2087px window in the original screenshot), the AI Mode conversation
is held tight to a **768px centered column** (`--ai-col`, app.css `:root`). On a big monitor that
leaves large empty navy bands on both sides. Independently, the two bubble types don't use even
that column well:

- **User bubbles** (`.chat-user-row` + `.chat-user-bubble`) are right-aligned, but capped at
  `max-width: 78%` — so they stop short of the column's right edge.
- **Assistant bubbles** (`.chat-bubble`) are capped at `max-width: 65ch` (≈524px at 14px) — well
  short of the 768px column, so answers float centered with dead space both sides.
- The comparison **table** in the screenshot (12 dimensions wide) is the content that most feels
  the squeeze.

### Goal (per Destin, in his words)

> "The overall chat window area should be expanded, and each user/assistant bubble should get
> closer to the opposing edge at max size … not all the way to the edge, but just a bit for
> longer messages."

Plus, "fine to hide more often" — the mascot may dock sooner. Deliberately **not** a phone-style
edge-to-edge bubble layout; just a measured widening so longer messages fill more of the chat area.

## 2. Design

### D1 — Widen the shared content column: `--ai-col: 768px → 960px`

`--ai-col` is the single content measure for the whole AI route: thread column, composer
(`.ask-bar`), footer (`.chat-footer`), banners (`.chat-notice-banner`), and the mascot offset
(`.chat-mascot-slot`). It lives in one place (`:root`). The AI stage is already full-bleed
(`.page-ai .ai-stage { max-width: none }`), so the column is the limiter today.

960px is chosen as a *conservative* widening (768 → 960 ≈ +25%): it's under the `.wrap`
`--maxw: 1140px` cap, so on a typical 1440px window with the rail open the column still fits;
and it's the smallest value that lets the bubbles get "a bit closer to the edge" without turning
the surface into a runway. Rationale follows the project rule "pick a plateau's centre" — 768 is
the verified lower plateau, 1140 (the wrap max) is the hard upper stop, 960 is between them.

### D2 — User bubbles reach the right edge: `max-width: 78% → min(82ch, 100%)`

`.chat-user-row` stays `justify-content: flex-end`; the bubble is a shrink-to-fit flex item, so:

- short messages stay right-flush and content-sized (unchanged look);
- long messages grow up to `82ch` (~660px at 14px) of the 960px column, flush right — wider, never
  past the column.

(CSS flexbox `flex: 0 1 auto` default: a block with `max-width` in a `flex-end` row is
content-sized up to the max, pinned right. No `margin-left:auto` needed.)

### D3 — Assistant bubbles get wider: `max-width: 65ch → min(90ch, 100%)`

The `ch` cap on `.chat-bubble` is the *prose* measure. Keep it (line-length protection), but raise
it from 65ch (≈524px) to 90ch (≈725px at 14px) — roughly **3/4 of the 960px column**. That is the
approved target (user: "closer to 3/4 the horizontal width so long messages don't get so tall"):
the bottleneck before this change was the *bubble* cap, not the column — a 65/72ch bubble sat at
~580px inside a 960px column with empty space both sides. The `min(90ch, 100%)` makes the cap the
bottleneck only when the column is wide enough; the bubble never exceeds the column.

**Tables are not capped by the `ch` measure**: `.chat-md table` has `width:100%` and the
`.chat-md-table-wrap` scrolls only if the table's intrinsic width exceeds the column. So with a
960px column, the 12-dimension comparison table gets the full ~960px.

### D4 — The tool card must track the bubble's measure (TC22 invariant)

`.chat-tool-group { max-width: calc(90ch - 34px) }` exists so the standalone card (mid-search)
and the nested card (inside a bubble) are the SAME width — that relationship is pinned by the
CSS-contract test. It changed together with the bubble in the same commit, or the card jumps when
it moves inside a wider bubble (the exact TC22 defect).

### D5 — Mascot dock threshold: `MASCOT_DOCK_PX: 1084 → 1276`

The mascot docks (visually hidden, kept in the a11y tree) when the scroller's content-box width
drops below a *derived* no-clip requirement. The derivation is pinned in
`chat-css-contract.test.ts` and documented in `ChatThread.tsx`:

```
no-clip:  A >= 2*(--ai-col/2 + 16) + 2*(sceneWidth - tx)
```

Per-scene, with columns=960:

| scene | sceneWidth | tx | requirement |
|---|---|---|---|
| idle | 120 | 5 | `992 + 2*(120-5)` = **1222** |
| thinking | ≈184.4 | 54 | `992 + 2*(184.4-54)` ≈ **1253** |
| presenting | 168 | 26 | `992 + 2*(168-26)` = **1276** |

Presenting binds → **`MASCOT_DOCK_PX = 1276`**.

Consequences (verified against the layout):

- **Source panel open** (`has-source`): chat column is clamped to `clamp(480px,46%,760px)` ≤ 760
  < 1276 → mascot docks. Same as today (760 < 1084), no change.
- **1440px window + rail open**: scroller ≈ (1440 − 22·2) − 260 ≈ 1136 < 1276 → now docks,
  whereas today (1136 > 1084) it was visible. This is the "fine to hide more often" trade the
  user accepted.
- **1440px window, rail closed**: scroller ≈ 1396 > 1276 → mascot remains visible. Net: the
  mascot is mostly present until the rail or the source panel actually needs the width.
- **2087px window (the screenshot)**: scroller ≈ 2043 > 1276 → mascot present.

The docked state keeps using the visually-hidden recipe (never `display:none` — the mascot's
`role="img"` label is the only AI status assistive tech gets; pinned by test).

## 3. Files to change (all in `webapp/`)

| # | File | Change |
|---|---|---|
| 1 | `webapp/src/styles/app.css` | `:root`: `--ai-col: 768px` → `960px` (kept at 960 after review — see §7) |
| 2 | `webapp/src/styles/app.css` | `.chat-user-bubble`: `max-width: 78%` → `min(82ch, 100%)` |
| 3 | `webapp/src/styles/app.css` | `.chat-bubble`: `max-width: 65ch` → `min(90ch, 100%)` |
| 4 | `webapp/src/styles/app.css` | `.chat-tool-group`: `max-width: calc(65ch - 34px)` → `calc(90ch - 34px)` |
| 5 | `webapp/src/styles/app.css` | `.chat-tool` (unreachable, kept deliberately): `65ch` → `90ch` (comment: match the live measure) |
| 6 | `webapp/src/chat/ChatThread.tsx` | `MASCOT_DOCK_PX = 1084` → `1276`, derive comment updated |
| 7 | `webapp/src/chat/__tests__/chat-css-contract.test.ts` | Update all pinned literals: `65ch` → `90ch`, `calc(65ch - 34px)` → `calc(90ch - 34px)`, `--ai-col: 768px` → `960px`, `MASCOT_DOCK_PX = 1084` → `1276` |
| 8 | `webapp/src/chat/__tests__/chat-thread-scroll.test.tsx` | Update the dock/undock test thresholds: `1083`/`1084` → `1275`/`1276` (they are explicitly one-pixel-under/at the threshold) |

### Test-watch list (existing suite that guards the touched rules)

- `chat-css-contract.test.ts` — "one content measure", the mascot dock threshold, TC22 measure,
  and the containment contract (unchanged but must still pass).
- `chat-thread-scroll.test.tsx` — dock/undock behavior driven by the stub ResizeObserver.
- `assistant-turn-bubble.test.tsx`, `chat-thread-scroll.test.tsx` — render-level, no numeric pins
  expected to change but must pass.
- `ai-mode-panel-source.test.tsx` — source-panel split, no numeric pins expected.

## 4. Unintended consequences, verified

**U1 — Mascot docks on 1440px-class windows with the rail open.** Accepted by the user ("fine to
hide more often"). Documented in D5; no code change to the a11y behavior.

**U2 — The source panel stays at `clamp(480px, 46%, 760px)`.** With `--ai-col: 960`, when the
source panel is open the chat column is clamped to ≤760px, so the *column* actually renders
narrower than its new 960px measure. That's correct flex behavior (the clamp was tuned for a
side-by-side split) and matches today's behavior with 768. Do NOT "fix" the clamp to 960 — that
would crush the PDF viewer. Guarded by the existing `flex: 0 0 clamp(...)` contract test.

**U3 — Prose does NOT touch the edges; tables do.** `.chat-bubble`'s `min(90ch, 100%)` lets prose
reach ~725px (roughly 3/4 of the 960px column); the remaining column is the left gutter for the
bubble's "speech" gap. Long prose is intentionally *not* edge-to-edge (readability); tables render
at the full 960px column width via `.chat-md table { width: 100% }`. This is the "closer to 3/4"
the user specified.

**U4 — The whole surface shares the measure.** Banners (`.chat-notice-banner`), footer
(`.chat-footer`) and composer (`.ask-bar`) all read `--ai-col`, so they widen in lockstep — that's
the point of a single token, and keeps one left edge. No drift risk since all read the token.

**U5 — Test-literal coupling is a feature, not a bug.** The CSS-contract test pins every number
above (`--ai-col: 768px`, `65ch`, `calc(65ch - 34px)`, `MASCOT_DOCK_PX = 1084`, and
`1083/1084` in the scroll test). If any of them lands without the others, the suite reds. Items
1–8 must land in **one commit**.

**U6 — `ch` unit resolution.** `65ch`/`72ch` resolve against the *element's* font-size. `.chat-bubble`
and `.chat-tool-group` both declare `font-size: 14px` (that exact pairing is why the TC22
derivation works). No change to that pairing here; keep it.

**U7 — No containment.** Nothing in this change adds `container-type`/`contain`/`mask`/
`content-visibility`; the citation-tooltip escape contract (pinned in
`chat-css-contract.test.ts`) is untouched. The mascot measurement stays in JS
(`ChatThread.tsx` ResizeObserver).

## 5. Non-goals / explicitly out of scope

- **No edge-to-edge bubble layout** (user explicitly said "not all the way to the edge").
- **No layout changes to** the history rail (260px / collapsed 44px), the source panel clamp, the
  welcome screen, or the mascot art/offsets (beyond the dock threshold value).
- **No backend / pipeline / eval changes.** Pure webapp CSS + one TS constant + test pins.
- **No change to the shared chat-css-contract containment test** (still passes as-is).
- **No attempt to make the mascot smaller instead of docking** — out of scope, needs new art.

## 6. Verification

1. `cd webapp && npx vitest run` — the CSS-contract + scroll tests are the gate.
2. `cd webapp && npm run build` — production build succeeds.
3. Manual browser check (dev server): screenshot-like 2087px window — messages fill more of the
   column, table uses the full width, mascot present; 1440px with rail open — mascot docks,
   column still readable; source panel open — column ≤760, mascot docked, PDF viewer intact.

## 7. History / decisions made in this session

- 2026-08-17: Option A chosen (column up, ch caps up, `--ai-col: 960`). User: "fine to hide more
  often" (mascot docks earlier, U1) and "not all the way to the edge, but just a bit for longer
  messages" (U3) — explicit scope for the design above.
- **Correction (same day, after a browser check): the bubbles must be wider, NOT the column.**
  Destin: "the chat view overall was wide enough … the individual bubbles WITHIN the chat view
  are still too narrow." The original 72ch (`min(72ch, 100%)`, ~580px) was too narrow for long
  answers and left them tall. Rounded bubble caps up to **90ch** (`min(90ch, 100%)`, ~725px ≈ 3/4
  of the 960 column) and user bubble to **82ch**. The column stays **960px**; a brief detour to
  `--ai-col: 1240` was reverted — the user confirmed the overall chat view was already the right
  width, and the bottleneck was the bubble cap, not the column. `MASCOT_DOCK_PX` stays `1276`
  (derived from the 960 column, unchanged by the bubble-only correction).