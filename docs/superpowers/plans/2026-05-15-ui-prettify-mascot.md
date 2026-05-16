# Web UI Refresh + JLBC Mascot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the Ask the Budget AZ web app an independent "civic-warm" visual identity and a pixel-art JLBC mascot that reacts to app state.

**Architecture:** Presentation-layer only — all changes under `web/`. A rewritten `globals.css` (single civic-warm light theme), a new `web/components/mascot/` folder of layered-SVG React components, an orchestration hook (`useMascotPose`) that maps chat state to a mascot pose/scene, and restyles of every conversation surface. No backend, retrieval, or MCP changes.

**Tech Stack:** Next.js 15 (App Router) · React 19 · Tailwind v4 (`@theme` in CSS) · `next/font/google` · Vitest 3 (SSR smoke tests via `react-dom/server`).

**Spec:** `docs/superpowers/specs/2026-05-15-ui-prettify-mascot-design.md`
**SVG geometry reference (committed):** `docs/superpowers/specs/assets/2026-05-15-mascot-reference/` — see its `README.md` for the file→component map. Every pixel coordinate was tuned in those mockups; tasks below port them.

---

## Conventions for every task

- **Working directory:** `web/`. All `npm` / path references are relative to `web/`.
- **Tests:** SSR smoke tests. Render with `renderToString` from `react-dom/server`, assert on HTML substrings. This matches every existing test (`tests/refusal-banner.test.tsx`, `tests/citation-chip.test.tsx`). The vitest environment stays `node` — do NOT switch to jsdom.
- **Run a single test file:** `npm run test -- tests/<file>.test.tsx`
- **Run the whole suite:** `npm run test`  (must end at **109+ passing** — never fewer than the 109 that exist today, plus whatever this plan adds).
- **Type check:** `npm run typecheck`
- **Porting SVG:** the mockup files use literal hex colors and `<symbol>`/`<use>`. React components must instead (a) be plain JSX returning `<g>` or `<svg>`, and (b) replace every literal mascot hex with the matching `var(--mascot-*)` CSS variable from Task 1. The hex→variable mapping is in Task 1's token table.
- **Commit** after each task with the message shown in its final step.

---

## File structure

**Rewritten:**
- `web/app/globals.css` — single civic-warm theme, mascot tokens, mascot keyframes
- `web/app/layout.tsx` — font wiring, drop `data-theme`
- `web/app/page.tsx` — welcome hero / nook / footer layout, `useMascotPose` wiring

**New — `web/components/mascot/`:**
- `types.ts` · `MascotBody.tsx` · `Mascot.tsx` · `MascotTyping.tsx` · `MascotPresenting.tsx` · `useMascotPose.ts`
- `poses/ArmsSides.tsx` · `ArmsClasped.tsx` · `ArmsWave.tsx` · `ArmsCrossed.tsx` · `ArmsClipboard.tsx` · `ArmsHips.tsx`

**New — other:**
- `web/components/WelcomeHero.tsx`
- `web/components/Footer.tsx`

**Restyled (markup/class changes only, no logic change):**
- `ChatThread.tsx` · `UserMessage.tsx` · `AssistantTurnBubble.tsx` · `MessageInput.tsx` · `ToolCard.tsx` · `tool-views/primitives.tsx` · `CitationChip.tsx` · `RefusalBanner.tsx` · `PdfViewer.tsx` (empty/loading states only)

---

# Phase A — Foundation

## Task 1: Rewrite the theme stylesheet

**Files:**
- Modify (rewrite): `web/app/globals.css`

- [ ] **Step 1: Replace the theme block.** Open `web/app/globals.css`. Keep lines 1–6 (the `@import "tailwindcss"`, the highlight.js import, and the two `@source` directives). Delete everything from the `:root,[data-theme="light"]` block through the end of the `[data-theme="creme"]` block (the four mirrored YouCoded themes). Replace with a single `:root` block:

```css
/* ═══════════════════════════════════════════════════════════════════════════
   Civic-warm theme — the app's own identity. Not tied to YouCoded.
   One theme, light only: the app is internal and desktop-first.
   ═══════════════════════════════════════════════════════════════════════════ */
:root {
  /* Surfaces */
  --canvas: #fbf7f0;
  --panel: #efe9dc;
  --inset: #e4ddcb;
  --well: #fffdf8;
  --accent: #3a6ea5;
  --on-accent: #fbf7f0;

  /* Text */
  --fg: #1f2937;
  --fg-2: #54585e;
  --fg-dim: #6a6e74;
  --fg-muted: #8a8e94;
  --fg-faint: #b4b1a8;

  /* Borders */
  --edge: #d8d2c4;
  --edge-dim: #d8d2c480;

  /* Inline code text color */
  --code: #b45309;

  /* Links */
  --link: #3a6ea5;
  --link-hover: #2c557f;

  /* Semantic status */
  --success: #3f8f4f;
  --warning: #c98f1e;
  --danger: #c0392b;

  /* Mascot palette — source values are the hex literals used in the
     committed reference mockups; the SVG components read these vars. */
  --mascot-cap: #3a6ea5;
  --mascot-cap-hi: #5a8cc4;
  --mascot-brim: #2c557f;
  --mascot-skin: #e8c8a4;
  --mascot-skin-hi: #f4dab7;
  --mascot-skin-shadow: #c8a47e;
  --mascot-suit: #1f2937;
  --mascot-suit-hi: #303a4a;
  --mascot-suit-shadow: #13181f;

  color-scheme: light;
}
```

- [ ] **Step 2: Update the `@theme` block.** In the `@theme { … }` block, the surface/text/border/code/link variable mappings stay as-is (they point at `var(--canvas)` etc.). Make these three changes:
  - Replace the three status colors `--color-green-400` / `--color-red-400` / `--color-amber-700` with `--color-success: var(--success);`, `--color-danger: var(--danger);`, `--color-warning: var(--warning);`.
  - Add the mascot colors so they're usable as Tailwind classes if needed: `--color-mascot-cap: var(--mascot-cap);` and the same for every `--mascot-*` token.
  - Replace the `--font-sans` / `--font-mono` declarations with:
    ```css
    --font-serif: var(--font-source-serif), Georgia, "Times New Roman", serif;
    --font-sans: var(--font-inter), system-ui, -apple-system, sans-serif;
    --font-mono: "Cascadia Mono", "Cascadia Code", "Fira Code", "Consolas", "Menlo", monospace;
    ```
    (`--font-source-serif` and `--font-inter` are injected by `next/font` in Task 2.)

- [ ] **Step 3: Update the `body` font + add mascot keyframes.** In the `html, body` rule, change `font-family: var(--font-sans);` — it already says that, leave it. At the end of the file, append the mascot animation keyframes:

```css
/* ═══════════════════════════════════════════════════════════════════════════
   Mascot animation — frame-based (steps()), never smooth tweens.
   prefers-reduced-motion halts all of it (Task 6 / Task 7 apply the
   classes; this just defines the keyframes).
   ═══════════════════════════════════════════════════════════════════════════ */
@keyframes mascot-bob {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(-1px); }
}
@keyframes mascot-tap {
  0%, 100% { transform: translateY(0); }
  50%      { transform: translateY(2px); }
}
@keyframes mascot-cursor {
  0%, 50%        { opacity: 1; }
  50.01%, 100%   { opacity: 0; }
}
```

- [ ] **Step 4: Verify the build.** Run: `npm run build`
Expected: build succeeds with no CSS errors. (Components still reference `bg-canvas`, `text-fg`, etc. — those tokens still exist, so nothing breaks.)

- [ ] **Step 5: Commit.**

```bash
git add web/app/globals.css
git commit -m "feat(web): civic-warm theme — rewrite globals.css, drop YouCoded mirror"
```

## Task 2: Wire the typography

**Files:**
- Modify: `web/app/layout.tsx`

- [ ] **Step 1: Add the font imports.** At the top of `web/app/layout.tsx`, below the existing imports, add:

```tsx
import { Source_Serif_4, Inter } from "next/font/google";

// Self-hosted, inlined — no FOUT, no CDN dependency. The CSS-variable
// names match the @theme mapping in globals.css.
const sourceSerif = Source_Serif_4({
  subsets: ["latin"],
  variable: "--font-source-serif",
  display: "swap",
});
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});
```

- [ ] **Step 2: Apply the font variables + drop `data-theme`.** Replace the `<html>` and `<body>` tags. The current `<html lang="en" data-theme="light">` becomes `<html lang="en" className={`${sourceSerif.variable} ${inter.variable}`}>`. The `<body>` keeps `className="min-h-screen bg-canvas text-fg"`. Remove the two-line comment above the old `<html>` about `data-theme` driving the theme switch — there is no switch now.

- [ ] **Step 3: Verify.** Run: `npm run build && npm run typecheck`
Expected: both succeed. `next/font` downloads Source Serif 4 and Inter at build time.

- [ ] **Step 4: Commit.**

```bash
git add web/app/layout.tsx
git commit -m "feat(web): wire Source Serif 4 + Inter via next/font"
```

---

# Phase B — Mascot core

## Task 3: Mascot type definitions

**Files:**
- Create: `web/components/mascot/types.ts`

- [ ] **Step 1: Write the types file.**

```ts
// Shared types for the JLBC mascot component family. See
// docs/superpowers/specs/2026-05-15-ui-prettify-mascot-design.md §2.

/** Front-view poses — each is a swappable arm set over the shared body. */
export type MascotPose =
  | "sides"
  | "clasped"
  | "wave"
  | "crossed"
  | "clipboard"
  | "hips";

/** Render size. hero = welcome screen, chip = header/nook, tiny = inline. */
export type MascotSize = "hero" | "chip" | "tiny";

/** Pixel dimensions per size. The SVG viewBox is always 0 0 240 320. */
export const MASCOT_DIMENSIONS: Record<MascotSize, { width: number; height: number }> = {
  hero: { width: 240, height: 320 },
  chip: { width: 40, height: 54 },
  tiny: { width: 24, height: 32 },
};
```

- [ ] **Step 2: Verify it type-checks.** Run: `npm run typecheck`
Expected: PASS (no errors).

- [ ] **Step 3: Commit.**

```bash
git add web/components/mascot/types.ts
git commit -m "feat(web): mascot type definitions"
```

## Task 4: MascotBody — the shared body SVG

**Files:**
- Create: `web/components/mascot/MascotBody.tsx`

The body = base, torso, neck, head, cap, JLBC text, glasses, eyes, mouth — everything *except* arms. Geometry source: the `#body` symbol in `docs/superpowers/specs/assets/2026-05-15-mascot-reference/mascot-pixel-poses.html` (it is the `<symbol id="body" viewBox="0 0 240 320">` block).

- [ ] **Step 1: Write the component.** Port the `#body` symbol's `<rect>`/`<text>` children into a React component returning a `<g>`. Replace every literal hex with the matching `var(--mascot-*)`:
  - `#3a6ea5` cap → `var(--mascot-cap)` · `#5a8cc4` → `var(--mascot-cap-hi)` · `#2c557f` brim → `var(--mascot-brim)`
  - `#e8c8a4` skin → `var(--mascot-skin)` · `#c8a47e` → `var(--mascot-skin-shadow)` · `#f4dab7` → `var(--mascot-skin-hi)`
  - `#1f2937` suit/frame/eye → `var(--mascot-suit)` for suit fills, `var(--mascot-suit)` for the glasses frame + eyes
  - `#303a4a` → `var(--mascot-suit-hi)` · `#fbf7f0` JLBC text + shirt → `var(--mascot-cap)` is wrong — JLBC text fill is `#fbf7f0`, use `var(--canvas)` (the paper color); shirt is also `#fbf7f0` → `var(--canvas)`
  - `#cbbfad` / `#a89e8e` (the base ellipses) → keep as literals (`#cbbfad`, `#a89e8e`) — the base is a neutral, not part of the mascot palette
  - The eyes are two separate `<rect>` elements — give each `data-mascot-eye` attribute so Task 6's blink can target them. Render them as `<rect data-mascot-eye ... />`.

```tsx
// The shared mascot body: head, cap, glasses, face, torso, base.
// Arms are composed on top by Mascot.tsx. Geometry ported 1:1 from
// the #body symbol in the committed reference mockup
// (specs/assets/2026-05-15-mascot-reference/mascot-pixel-poses.html);
// literal hex swapped for --mascot-* CSS variables.
export default function MascotBody() {
  return (
    <g>
      {/* ...ported rects/text — see Step 1 instructions... */}
    </g>
  );
}
```

- [ ] **Step 2: Smoke test.** Create `web/tests/mascot.test.tsx` with a first test:

```tsx
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import MascotBody from "../components/mascot/MascotBody";

describe("MascotBody", () => {
  it("renders the JLBC cap text and does not throw", () => {
    const html = renderToString(<svg viewBox="0 0 240 320"><MascotBody /></svg>);
    expect(html).toContain("JLBC");
    expect(html).toContain("var(--mascot-cap)");
    expect(html).toContain("var(--mascot-skin)");
  });
});
```

- [ ] **Step 3: Run the test.** Run: `npm run test -- tests/mascot.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add web/components/mascot/MascotBody.tsx web/tests/mascot.test.tsx
git commit -m "feat(web): MascotBody shared SVG"
```

## Task 5: Pose components — the six arm sets

**Files:**
- Create: `web/components/mascot/poses/ArmsSides.tsx`, `ArmsClasped.tsx`, `ArmsWave.tsx`, `ArmsCrossed.tsx`, `ArmsClipboard.tsx`, `ArmsHips.tsx`

Geometry source: `mascot-pixel-poses.html` symbols `#arms-sides`, `#arms-clasped`, `#arms-wave`, `#arms-crossed`, `#arms-clipboard`, `#arms-hips`. (Note: `ArmsClasped` is the spec's default pose; `ArmsWave` is welcome; `ArmsCrossed` is refusal; `ArmsClipboard` is result-settled.)

- [ ] **Step 1: Write all six components.** Each is the same shape — port one `#arms-*` symbol's children into a `<g>`, swapping hex for `var(--mascot-*)` per Task 4's mapping. The clipboard pose also has a paper/clip in neutral `#a89e8e` + `var(--canvas)` — keep `#a89e8e` literal, paper is `var(--canvas)`. Example:

```tsx
// Geometry ported from the #arms-clasped symbol in the committed
// reference mockup. P3b — the default idle pose.
export default function ArmsClasped() {
  return (
    <g>
      {/* ...ported rects... */}
    </g>
  );
}
```

- [ ] **Step 2: Add smoke tests** to `web/tests/mascot.test.tsx`:

```tsx
import ArmsClasped from "../components/mascot/poses/ArmsClasped";
import ArmsWave from "../components/mascot/poses/ArmsWave";
import ArmsCrossed from "../components/mascot/poses/ArmsCrossed";
import ArmsClipboard from "../components/mascot/poses/ArmsClipboard";
import ArmsSides from "../components/mascot/poses/ArmsSides";
import ArmsHips from "../components/mascot/poses/ArmsHips";

describe("pose components", () => {
  it("every pose renders without throwing", () => {
    for (const Arms of [ArmsClasped, ArmsWave, ArmsCrossed, ArmsClipboard, ArmsSides, ArmsHips]) {
      const html = renderToString(<svg viewBox="0 0 240 320"><Arms /></svg>);
      expect(html).toContain("var(--mascot-suit)");
    }
  });
});
```

- [ ] **Step 3: Run the test.** Run: `npm run test -- tests/mascot.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add web/components/mascot/poses web/tests/mascot.test.tsx
git commit -m "feat(web): six mascot pose components"
```

## Task 6: Mascot component — composition, sizing, idle animation

**Files:**
- Create: `web/components/mascot/Mascot.tsx`

- [ ] **Step 1: Write the failing test.** Add to `web/tests/mascot.test.tsx`:

```tsx
import Mascot from "../components/mascot/Mascot";

describe("Mascot", () => {
  it("renders with role=img and an aria-label", () => {
    const html = renderToString(<Mascot pose="wave" size="hero" />);
    expect(html).toContain('role="img"');
    expect(html).toContain('aria-label="JLBC budget assistant"');
  });

  it("renders the chip size at 40x54", () => {
    const html = renderToString(<Mascot pose="clasped" size="chip" />);
    expect(html).toContain('width="40"');
    expect(html).toContain('height="54"');
  });

  it("includes the bob animation class when animate is not false", () => {
    const html = renderToString(<Mascot pose="clasped" size="hero" />);
    expect(html).toContain("mascot-animate");
  });

  it("omits the animation class when animate=false", () => {
    const html = renderToString(<Mascot pose="clasped" size="hero" animate={false} />);
    expect(html).not.toContain("mascot-animate");
  });

  it("renders every pose without throwing", () => {
    for (const pose of ["sides", "clasped", "wave", "crossed", "clipboard", "hips"] as const) {
      expect(() => renderToString(<Mascot pose={pose} size="hero" />)).not.toThrow();
    }
  });
});
```

- [ ] **Step 2: Run the test to verify it fails.** Run: `npm run test -- tests/mascot.test.tsx`
Expected: FAIL — `Mascot` does not exist.

- [ ] **Step 3: Write the component.**

```tsx
"use client";

import { useEffect, useRef, useState } from "react";

import { MASCOT_DIMENSIONS, type MascotPose, type MascotSize } from "./types";
import MascotBody from "./MascotBody";
import ArmsSides from "./poses/ArmsSides";
import ArmsClasped from "./poses/ArmsClasped";
import ArmsWave from "./poses/ArmsWave";
import ArmsCrossed from "./poses/ArmsCrossed";
import ArmsClipboard from "./poses/ArmsClipboard";
import ArmsHips from "./poses/ArmsHips";

const POSE_COMPONENTS: Record<MascotPose, () => React.JSX.Element> = {
  sides: ArmsSides,
  clasped: ArmsClasped,
  wave: ArmsWave,
  crossed: ArmsCrossed,
  clipboard: ArmsClipboard,
  hips: ArmsHips,
};

interface Props {
  pose: MascotPose;
  size?: MascotSize;
  /** Idle bob + blink + push-glasses. Default true. */
  animate?: boolean;
  className?: string;
}

export default function Mascot({ pose, size = "hero", animate = true, className }: Props) {
  const { width, height } = MASCOT_DIMENSIONS[size];
  const Arms = POSE_COMPONENTS[pose];

  return (
    <svg
      viewBox="0 0 240 320"
      width={width}
      height={height}
      role="img"
      aria-label="JLBC budget assistant"
      className={[
        "mascot",
        animate ? "mascot-animate" : "",
        className ?? "",
      ].filter(Boolean).join(" ")}
      style={{ shapeRendering: "crispEdges" }}
    >
      <MascotBody />
      <Arms />
    </svg>
  );
}
```

- [ ] **Step 4: Run the test to verify it passes.** Run: `npm run test -- tests/mascot.test.tsx`
Expected: PASS.

- [ ] **Step 5: Add the idle-animation CSS.** Append to `web/app/globals.css`:

```css
/* The mascot bob runs on the whole SVG; blink + push-glasses are
   driven by JS (Mascot.tsx) toggling data-attributes, because their
   timing is randomized and CSS can't randomize. */
.mascot-animate { animation: mascot-bob 3.2s steps(2, end) infinite; transform-origin: 50% 100%; }
.mascot [data-mascot-eye] { transition: none; }
.mascot[data-blink="true"] [data-mascot-eye] { fill: var(--mascot-skin); }

@media (prefers-reduced-motion: reduce) {
  .mascot-animate { animation: none; }
}
```

- [ ] **Step 6: Add the JS-driven blink.** Update `Mascot.tsx` — add a `blink` state and an effect that, when `animate` is true and `prefers-reduced-motion` is not set, toggles it on for ~150ms at a random 3–6s gap:

```tsx
  const [blink, setBlink] = useState(false);

  useEffect(() => {
    if (!animate) return;
    if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;
    let timer: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const gap = 3000 + Math.random() * 3000;
      timer = setTimeout(() => {
        setBlink(true);
        setTimeout(() => setBlink(false), 150);
        schedule();
      }, gap);
    };
    schedule();
    return () => clearTimeout(timer);
  }, [animate]);
```

  Add `data-blink={blink ? "true" : undefined}` to the `<svg>`. The CSS rule from Step 5 (`.mascot[data-blink="true"] [data-mascot-eye]`) recolors the eyes to skin while it's set.

- [ ] **Step 7: Port and wire the push-glasses moment.** Create `web/components/mascot/poses/ArmsPushingGlasses.tsx` from the `#arms-pushing` symbol in `docs/superpowers/specs/assets/2026-05-15-mascot-reference/idle-moments.html`, and `web/components/mascot/poses/GlassesUp.tsx` from the `#glasses-up` symbol (same file). Both port hex→`var(--mascot-*)` per Task 4's mapping. In `Mascot.tsx`, add a `pushGlasses` boolean state on a random 15–25s timer (same `animate` + reduced-motion guard as blink); while it is true (~700ms), render `<ArmsPushingGlasses />` in place of the pose's `<Arms />` and additionally render `<GlassesUp />`. Only run the timer when `pose` is one of `clasped` / `clipboard` / `sides` / `hips` — skip it for `wave` and `crossed` (those arms are already raised/occupied).

- [ ] **Step 8: Run the full suite.** Run: `npm run test`
Expected: all tests pass (109 existing + the mascot tests).

- [ ] **Step 9: Commit.**

```bash
git add web/components/mascot/Mascot.tsx web/components/mascot/poses/ArmsPushingGlasses.tsx web/app/globals.css web/tests/mascot.test.tsx
git commit -m "feat(web): Mascot component — composition, sizing, idle bob + blink + push-glasses"
```

---

# Phase C — Mascot scenes

## Task 7: MascotTyping — the side-typing scene

**Files:**
- Create: `web/components/mascot/MascotTyping.tsx`

Geometry source: `typing-side-v6-lid-angles.html` — use the shared `#m-body`, `#base-sleek`, `#hand` symbols **plus the lid polygons from card D ("d-comfortable")**. The viewBox is `0 0 360 320`.

- [ ] **Step 1: Write the component.** Port `#m-body` + `#base-sleek` + the card-D lid polygons + `#hand` into one component returning a full `<svg viewBox="0 0 360 320">`. Swap mascot hex for `var(--mascot-*)`; the laptop's silver/screen colors stay literal (they are not themed — they are the laptop's own palette: `#eef0f2`, `#c8ccd0`, `#a8acb2`, `#6a6e74`, `#1a1d22` bezel, `#3a6ea5` screen → use `var(--mascot-cap)` for the screen since it is civic-blue, `#fbf7f0` screen text → `var(--canvas)`). Give the tapping hand group `className="mascot-typing-hand"` and the screen cursor `className="mascot-typing-cursor"`.

```tsx
"use client";

// The side-typing scene — the "thinking" state. Mascot in left profile
// typing on a sleek aluminum laptop (card D, ~110° lid). Geometry ported
// from typing-side-v6-lid-angles.html in the committed reference folder.
export default function MascotTyping() {
  return (
    <svg viewBox="0 0 360 320" role="img" aria-label="JLBC budget assistant — searching"
         style={{ shapeRendering: "crispEdges" }} className="mascot-typing">
      {/* ...ported rects + lid polygons... */}
    </svg>
  );
}
```

- [ ] **Step 2: Add the scene animation CSS.** Append to `web/app/globals.css`:

```css
.mascot-typing-hand   { animation: mascot-tap 460ms steps(2, end) infinite; transform-origin: 50% 100%; transform-box: fill-box; }
.mascot-typing-cursor { animation: mascot-cursor 600ms steps(2, end) infinite; }
@media (prefers-reduced-motion: reduce) {
  .mascot-typing-hand, .mascot-typing-cursor { animation: none; }
}
```

- [ ] **Step 3: Smoke test.** Add to `web/tests/mascot.test.tsx`:

```tsx
import MascotTyping from "../components/mascot/MascotTyping";

describe("MascotTyping", () => {
  it("renders the scene with the laptop and a typing hand", () => {
    const html = renderToString(<MascotTyping />);
    expect(html).toContain("mascot-typing-hand");
    expect(html).toContain('aria-label="JLBC budget assistant — searching"');
  });
});
```

- [ ] **Step 4: Run the test.** Run: `npm run test -- tests/mascot.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add web/components/mascot/MascotTyping.tsx web/app/globals.css web/tests/mascot.test.tsx
git commit -m "feat(web): MascotTyping side-typing scene"
```

## Task 8: MascotPresenting — the front-presenting scene

**Files:**
- Create: `web/components/mascot/MascotPresenting.tsx`

Geometry source: the `#front-presenting` symbol in `typing-side-present-v2.html`. viewBox `0 0 320 320`.

- [ ] **Step 1: Write the component.** Port `#front-presenting` into a full `<svg viewBox="0 0 320 320">`. Same color rules as Task 7 (mascot hex → `var(--mascot-*)`, laptop silver stays literal, screen → `var(--mascot-cap)`, screen text → `var(--canvas)`, citation chip on screen → `var(--mascot-cap)`). Give the screen cursor `className="mascot-typing-cursor"` (reuse the keyframe from Task 7).

```tsx
"use client";

// The front-presenting scene — the brief "here's what I found" beat
// after a successful turn. Geometry ported from the #front-presenting
// symbol in typing-side-present-v2.html (committed reference folder).
export default function MascotPresenting() {
  return (
    <svg viewBox="0 0 320 320" role="img" aria-label="JLBC budget assistant — presenting results"
         style={{ shapeRendering: "crispEdges" }} className="mascot-presenting">
      {/* ...ported rects + polygons... */}
    </svg>
  );
}
```

- [ ] **Step 2: Smoke test.** Add to `web/tests/mascot.test.tsx`:

```tsx
import MascotPresenting from "../components/mascot/MascotPresenting";

describe("MascotPresenting", () => {
  it("renders the presenting scene", () => {
    const html = renderToString(<MascotPresenting />);
    expect(html).toContain('aria-label="JLBC budget assistant — presenting results"');
  });
});
```

- [ ] **Step 3: Run the test.** Run: `npm run test -- tests/mascot.test.tsx`
Expected: PASS.

- [ ] **Step 4: Commit.**

```bash
git add web/components/mascot/MascotPresenting.tsx web/tests/mascot.test.tsx
git commit -m "feat(web): MascotPresenting front-presenting scene"
```

---

# Phase D — Orchestration

## Task 9: useMascotPose — the state→pose hook

**Files:**
- Create: `web/components/mascot/useMascotPose.ts`
- Test: `web/tests/use-mascot-pose.test.tsx`

The hook is the single decision point for which pose/scene shows. It reads `ChatState` (`web/state/chat-types.ts`) plus a `refusalActive` flag. Spec §5 table.

**Important — refusal:** the app does not yet auto-detect refusals (`RefusalBanner` is props-driven; auto-detection is the deferred Phase 1c WS5). So `useMascotPose` takes an explicit `refusalActive: boolean`. `page.tsx` passes `false` for v1 (Task 16). The `crossed` mapping is built and tested here so WS5 can wire it later by flipping that flag.

The hook returns a discriminated union the renderer switches on:

```ts
export type MascotState =
  | { kind: "welcome" }                       // wave, hero
  | { kind: "idle"; pose: "clasped" }         // nook
  | { kind: "thinking" }                      // side-typing scene, inline
  | { kind: "presenting" }                    // front-presenting scene, inline (~1.5s)
  | { kind: "result"; pose: "clipboard" }     // nook
  | { kind: "refusal"; pose: "crossed" }      // nook + banner
  | { kind: "error"; pose: "clasped" };       // nook
```

- [ ] **Step 1: Write the failing test.** Create `web/tests/use-mascot-pose.test.tsx`. Test a hook with a tiny probe component that calls it and renders the result kind as text:

```tsx
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import { useMascotPose } from "../components/mascot/useMascotPose";
import type { ChatState } from "../state/chat-types";
import { initialChatState } from "../state/chat-types";

function Probe({ state, refusalActive }: { state: ChatState; refusalActive: boolean }) {
  const m = useMascotPose(state, refusalActive);
  return <span>{m.kind}</span>;
}

function render(state: ChatState, refusalActive = false): string {
  return renderToString(<Probe state={state} refusalActive={refusalActive} />);
}

const base = initialChatState;

describe("useMascotPose", () => {
  it("welcome when there is no conversation and no turns", () => {
    expect(render(base)).toContain("welcome");
  });

  it("idle when a conversation exists, has turns, and is not thinking", () => {
    const state: ChatState = {
      ...base,
      conversationId: "c1",
      turns: [{ kind: "user", id: "u1", text: "hi", pending: false, timestamp: 1 }],
    };
    expect(render(state)).toContain("idle");
  });

  it("thinking when isThinking is true", () => {
    const state: ChatState = { ...base, conversationId: "c1", isThinking: true };
    expect(render(state)).toContain("thinking");
  });

  it("refusal when refusalActive is true (overrides idle)", () => {
    const state: ChatState = { ...base, conversationId: "c1",
      turns: [{ kind: "user", id: "u1", text: "x", pending: false, timestamp: 1 }] };
    expect(render(state, true)).toContain("refusal");
  });

  it("error when state.error is set", () => {
    const state: ChatState = { ...base, conversationId: "c1", error: "boom" };
    expect(render(state)).toContain("error");
  });
});
```

- [ ] **Step 2: Run the test to verify it fails.** Run: `npm run test -- tests/use-mascot-pose.test.tsx`
Expected: FAIL — `useMascotPose` does not exist.

- [ ] **Step 3: Write the hook.**

```ts
"use client";

import { useEffect, useRef, useState } from "react";

import type { ChatState } from "@/state/chat-types";

export type MascotState =
  | { kind: "welcome" }
  | { kind: "idle"; pose: "clasped" }
  | { kind: "thinking" }
  | { kind: "presenting" }
  | { kind: "result"; pose: "clipboard" }
  | { kind: "refusal"; pose: "crossed" }
  | { kind: "error"; pose: "clasped" };

const PRESENTING_MS = 1500;

/**
 * Single decision point for the mascot's pose/scene. Reads chat state
 * plus an explicit refusalActive flag (refusal auto-detection is not
 * built yet — Phase 1c WS5 — so the caller passes false for v1).
 */
export function useMascotPose(state: ChatState, refusalActive: boolean): MascotState {
  // Track the isThinking true->false edge to fire the ~1.5s presenting beat.
  const wasThinking = useRef(false);
  const [presenting, setPresenting] = useState(false);

  useEffect(() => {
    if (wasThinking.current && !state.isThinking && !state.error && !refusalActive) {
      setPresenting(true);
      const t = setTimeout(() => setPresenting(false), PRESENTING_MS);
      wasThinking.current = state.isThinking;
      return () => clearTimeout(t);
    }
    wasThinking.current = state.isThinking;
  }, [state.isThinking, state.error, refusalActive]);

  if (state.error) return { kind: "error", pose: "clasped" };
  if (refusalActive) return { kind: "refusal", pose: "crossed" };
  if (state.isThinking) return { kind: "thinking" };
  if (presenting) return { kind: "presenting" };
  if (state.conversationId === null && state.turns.length === 0) {
    return { kind: "welcome" };
  }
  if (state.turns.some((t) => t.kind === "assistant")) {
    return { kind: "result", pose: "clipboard" };
  }
  return { kind: "idle", pose: "clasped" };
}
```

- [ ] **Step 4: Run the test to verify it passes.** Run: `npm run test -- tests/use-mascot-pose.test.tsx`
Expected: PASS (all 5 tests).

- [ ] **Step 5: Commit.**

```bash
git add web/components/mascot/useMascotPose.ts web/tests/use-mascot-pose.test.tsx
git commit -m "feat(web): useMascotPose orchestration hook"
```

---

# Phase E — UI integration

## Task 10: WelcomeHero component

**Files:**
- Create: `web/components/WelcomeHero.tsx`
- Test: `web/tests/welcome-hero.test.tsx`

Layout source: `welcome-hero.html` card A ("a-centered"). Centered stack: mascot (wave, hero) → headline → sub-copy → input → "try one of these" + 3 chips.

- [ ] **Step 1: Write the failing test.** Create `web/tests/welcome-hero.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { renderToString } from "react-dom/server";
import WelcomeHero from "../components/WelcomeHero";

describe("WelcomeHero", () => {
  it("renders the headline, mascot, and three suggestion chips", () => {
    const html = renderToString(<WelcomeHero onPick={vi.fn()} />);
    expect(html).toContain("let&#x27;s look at the budget");
    expect(html).toContain('aria-label="JLBC budget assistant"');
    expect(html).toContain("Aviation Fund");
  });
});
```

- [ ] **Step 2: Run it to verify it fails.** Run: `npm run test -- tests/welcome-hero.test.tsx`
Expected: FAIL — `WelcomeHero` does not exist.

- [ ] **Step 3: Write the component.** A centered flex column. Props: `onPick(query: string)` — fired when a suggestion chip is clicked, so `page.tsx` can drop the query into the input. Uses `<Mascot pose="wave" size="hero" />`, a Source Serif headline (`font-serif` class), Inter sub-copy. Three suggestion chips with the example queries from the mockup ("What was the FY2025 Aviation Fund balance?", "How much did ADOT receive in FY2024?", "Show me General Fund revenue projections"). The hero does NOT contain the input box itself — `page.tsx` already owns `MessageInput`; the hero is the empty-thread content only.

```tsx
"use client";

import Mascot from "./mascot/Mascot";

const SUGGESTIONS = [
  "What was the FY2025 Aviation Fund balance?",
  "How much did ADOT receive in FY2024?",
  "Show me General Fund revenue projections",
];

interface Props {
  onPick: (query: string) => void;
}

export default function WelcomeHero({ onPick }: Props) {
  return (
    <div className="flex-1 flex flex-col items-center justify-center text-center px-6 py-12 gap-2">
      <Mascot pose="wave" size="hero" className="mb-2" />
      <h1 className="font-serif text-3xl font-bold text-fg">
        Hi — let&apos;s look at the budget.
      </h1>
      <p className="text-fg-2 max-w-xl">
        I&apos;ll search the JLBC Appropriations Reports, Baseline Books, AGAO Annual
        Financial Reports, and Governor&apos;s Executive Budget. Every claim gets a
        citation to the source page.
      </p>
      <div className="mt-4 text-xs uppercase tracking-wider text-fg-muted">
        try one of these
      </div>
      <div className="flex flex-wrap gap-2 justify-center max-w-xl">
        {SUGGESTIONS.map((q) => (
          <button
            key={q}
            type="button"
            onClick={() => onPick(q)}
            className="rounded-full border border-edge bg-panel px-3 py-1.5 text-xs text-fg
                       hover:border-accent hover:text-accent transition-colors"
          >
            {q}
          </button>
        ))}
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Run it to verify it passes.** Run: `npm run test -- tests/welcome-hero.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add web/components/WelcomeHero.tsx web/tests/welcome-hero.test.tsx
git commit -m "feat(web): WelcomeHero centered-stack welcome screen"
```

## Task 11: Footer component

**Files:**
- Create: `web/components/Footer.tsx`
- Test: `web/tests/footer.test.tsx`

Spec §6: slim bar, three regions — sources (left), honesty line (center), connection dot + corpus stat (right).

- [ ] **Step 1: Write the failing test.** Create `web/tests/footer.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import Footer from "../components/Footer";

describe("Footer", () => {
  it("renders the honesty line (Core Invariant 5)", () => {
    const html = renderToString(<Footer connected={true} />);
    expect(html).toContain("Answers are cited, not guaranteed");
    expect(html).toContain("JLBC");
  });

  it("must never claim the system is hallucination-free", () => {
    const html = renderToString(<Footer connected={true} />).toLowerCase();
    expect(html).not.toContain("hallucination-free");
    expect(html).not.toContain("grounded");
  });
});
```

- [ ] **Step 2: Run it to verify it fails.** Run: `npm run test -- tests/footer.test.tsx`
Expected: FAIL — `Footer` does not exist.

- [ ] **Step 3: Write the component.**

```tsx
interface Props {
  /** YouCoded connection status — drives the status dot color. */
  connected: boolean;
}

export default function Footer({ connected }: Props) {
  return (
    <footer className="flex-shrink-0 border-t border-edge bg-panel/40 px-4 h-[26px]
                       flex items-center justify-between text-[11px] font-mono text-fg-muted">
      <span>Sources: JLBC · AGAO · AZ Legislature · Governor&apos;s Office</span>
      <span>Answers are cited, not guaranteed. Verify against sources.</span>
      <span className="flex items-center gap-2">
        <span
          className="inline-block w-2 h-2 rounded-full"
          style={{ background: connected ? "var(--success)" : "var(--danger)" }}
          aria-label={connected ? "YouCoded connected" : "YouCoded disconnected"}
        />
        382 docs · FY2024–26
      </span>
    </footer>
  );
}
```

- [ ] **Step 4: Run it to verify it passes.** Run: `npm run test -- tests/footer.test.tsx`
Expected: PASS.

- [ ] **Step 5: Commit.**

```bash
git add web/components/Footer.tsx web/tests/footer.test.tsx
git commit -m "feat(web): Footer with sources + honesty line + status"
```

## Task 12: Restyle the header, message bubbles, and input

**Files:**
- Modify: `web/components/UserMessage.tsx`
- Modify: `web/components/MessageInput.tsx`
- Modify: `web/components/AssistantTurnBubble.tsx`

These are class-only restyles — no logic, no prop changes. Spec §4.

- [ ] **Step 1: Restyle `UserMessage.tsx`.** The user bubble becomes right-aligned, civic-blue fill. Wherever the bubble `<div>` sets its classes, use: `bg-accent text-on-accent rounded-[12px_12px_4px_12px] px-3.5 py-2 max-w-[78%]`, and the row wrapper `flex justify-end`. Body text uses `font-sans` (Inter) at `text-sm leading-relaxed`.

- [ ] **Step 2: Restyle `MessageInput.tsx`.** The input container: `bg-well border-[1.5px] border-edge rounded-[10px]`. Add a civic-blue focus ring on the input — `focus-within:border-accent focus-within:ring-2 focus-within:ring-accent/30`. The send button: `bg-accent text-on-accent rounded-md px-3.5 py-1.5 text-xs font-semibold font-sans`. Keep all existing disabled/placeholder logic untouched.

- [ ] **Step 3: Restyle `AssistantTurnBubble.tsx`.** The assistant turn renders directly on canvas — no bubble. Ensure the wrapper has no background/border. Body text `font-sans`. Leave the block-mapping logic (text / ToolCard interleaving) untouched.

- [ ] **Step 4: Run the full suite.** Run: `npm run test`
Expected: all existing tests still pass (these are restyles — `tests/tool-body.test.tsx` etc. assert on structure/text, not colors).

- [ ] **Step 5: Verify in the browser.** Run `npm run dev`, open the app, confirm the user bubble is civic-blue and right-aligned, the input has a blue focus ring. Stop the dev server.

- [ ] **Step 6: Commit.**

```bash
git add web/components/UserMessage.tsx web/components/MessageInput.tsx web/components/AssistantTurnBubble.tsx
git commit -m "feat(web): restyle message bubbles + input — civic-warm"
```

## Task 13: Restyle the tool card + add pixel-art glyphs

**Files:**
- Modify: `web/components/ToolCard.tsx`
- Modify: `web/components/tool-views/primitives.tsx`

- [ ] **Step 1: Write a failing test for the glyph mapping.** Add `web/tests/tool-card.test.tsx`:

```tsx
import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";
import { toolGlyph } from "../components/tool-views/primitives";

describe("toolGlyph", () => {
  it("returns a distinct glyph element for each known tool", () => {
    const retrieve = renderToString(<svg>{toolGlyph("retrieve")}</svg>);
    const cite = renderToString(<svg>{toolGlyph("cite")}</svg>);
    expect(retrieve).not.toEqual(cite);
  });
  it("falls back for an unknown tool without throwing", () => {
    expect(() => renderToString(<svg>{toolGlyph("mystery_tool")}</svg>)).not.toThrow();
  });
});
```

- [ ] **Step 2: Run it to verify it fails.** Run: `npm run test -- tests/tool-card.test.tsx`
Expected: FAIL — `toolGlyph` not exported.

- [ ] **Step 3: Add `toolGlyph` to `primitives.tsx`.** A function returning a tiny pixel-art SVG `<g>` per tool name: `retrieve` → magnifier (a few rects forming a circle + handle), `cite` → bookmark/page, `list_filter_values` → three stacked list lines, default → a single `var(--accent)` square. Each glyph is drawn in a `0 0 12 12` coordinate space, ~12px rendered. Use `var(--accent)` for the fill; `var(--danger)` is applied by the caller for errored calls.

- [ ] **Step 4: Restyle `ToolCard.tsx`.** Header strip: `bg-panel`, the glyph from `toolGlyph(toolName)` on the left, tool name in `font-sans font-semibold`, meta right-aligned in `font-mono text-fg-muted`. Card border `border-edge rounded-lg`. When the tool block `status === "failed"` or `isError`, the accent (glyph + a left border) uses `var(--danger)` instead of `var(--accent)`. Keep the existing collapse/expand logic and the JSON-fallback body untouched.

- [ ] **Step 5: Run the suite.** Run: `npm run test`
Expected: all pass (existing `tool-body.test.tsx` + the new `tool-card.test.tsx`).

- [ ] **Step 6: Commit.**

```bash
git add web/components/ToolCard.tsx web/components/tool-views/primitives.tsx web/tests/tool-card.test.tsx
git commit -m "feat(web): restyle tool card + pixel-art tool glyphs"
```

## Task 14: Restyle citation chips + PDF-panel transition

**Files:**
- Modify: `web/components/CitationChip.tsx`

Spec §4 (chip styling) + §6 (click transition). The chip currently has three tones (failed/verbatim/paraphrase). Keep the three-state logic; restyle the colors to the civic palette.

- [ ] **Step 1: Restyle the chip tones.** In `CitationChip.tsx`, the `tone` and `underline` strings: passing/verbatim → civic-blue (`bg-accent/12 text-accent border-accent/50`, hover `bg-accent text-on-accent`); paraphrase → neutral (`bg-inset text-fg-2 border-edge`); failed → danger (`bg-danger/12 text-danger border-danger/50` + `line-through`). Keep the `glyph` logic (`✗` / `✓` / `≈`) and the tooltip untouched.

- [ ] **Step 2: Add the click transition.** On the chip `<button>`, add a CSS class `cite-chip` and, on click (in the existing `onClick` that calls `bus.select`), briefly add a `cite-chip-firing` class for 250ms. Append to `globals.css`:

```css
.cite-chip { transition: transform 120ms ease-out; }
.cite-chip-firing { transform: scale(1.15); box-shadow: 0 0 8px 1px var(--accent); }
@media (prefers-reduced-motion: reduce) {
  .cite-chip, .cite-chip-firing { transition: none; transform: none; box-shadow: none; }
}
```

  Implement the toggle with a `useState` + `setTimeout(…, 250)` in the component.

- [ ] **Step 3: Run the suite.** Run: `npm run test`
Expected: `tests/citation-chip.test.tsx` still passes (it asserts on glyphs/aria-labels/structure, not colors).

- [ ] **Step 4: Commit.**

```bash
git add web/components/CitationChip.tsx web/app/globals.css
git commit -m "feat(web): restyle citation chips + click transition"
```

## Task 15: Restyle the refusal banner

**Files:**
- Modify: `web/components/RefusalBanner.tsx`

Spec §4: amber card, `tiny` crossed-arms mascot inline. The banner stays props-driven (no behavior change) — copy is load-bearing, do NOT change the spec-§11 copy strings.

- [ ] **Step 1: Restyle + add the mascot.** Change the outer `<div>` classes to use the warning token: `rounded-md border border-warning/50 bg-warning/10 p-3`. At the start of the banner's flex row, add `<Mascot pose="crossed" size="tiny" />` (import from `./mascot/Mascot`). The title gets `font-serif font-bold`. Keep the `COPY` map, the `ChunkPreviewRow`, and all three refusal-kind branches exactly as they are.

- [ ] **Step 2: Run the suite.** Run: `npm run test`
Expected: `tests/refusal-banner.test.tsx` still passes (it asserts on the copy strings + chunk rendering — unchanged).

- [ ] **Step 3: Commit.**

```bash
git add web/components/RefusalBanner.tsx
git commit -m "feat(web): restyle refusal banner + crossed-arms mascot"
```

## Task 16: Integrate the mascot into page.tsx + ChatThread.tsx

**Files:**
- Modify: `web/app/page.tsx`
- Modify: `web/components/ChatThread.tsx`

This wires `useMascotPose`, swaps the empty state for `WelcomeHero`, swaps the "Thinking…" text for the scenes, adds the persistent nook, and mounts the footer.

- [ ] **Step 1: Replace ChatThread's empty + thinking states.** In `ChatThread.tsx`:
  - Add a prop `onPickSuggestion: (q: string) => void` to `Props`.
  - Replace the `state.turns.length === 0 && !state.isThinking` empty-state block (current lines ~111–129) with `<WelcomeHero onPick={onPickSuggestion} />`.
  - Replace the `{state.isThinking && <div>Thinking…</div>}` block (current lines ~154–158) with a centered render of `<MascotTyping />` plus the label "Searching the budget documents…" (Inter, `text-fg-muted`).
  - Add a prop `mascot: MascotState` (from `useMascotPose`). When `mascot.kind === "presenting"`, render `<MascotPresenting />` centered in the thread *instead of* `MascotTyping` (the handoff beat). Import `MascotState` from `../components/mascot/useMascotPose`.

- [ ] **Step 2: Wire page.tsx.** In `web/app/page.tsx`:
  - Call `const mascot = useMascotPose(state, false);` (the `false` = `refusalActive`; refusal auto-detection is deferred WS5 — leave a comment saying so).
  - Pass `mascot` and an `onPickSuggestion` (a callback that stores the query so `MessageInput` can show it — simplest: a `useState` lifted to page, passed to `MessageInput` as a controlled initial value, OR just call `send(q)` directly) into `ChatThread`. For v1, `onPickSuggestion={(q) => send(q)}` is acceptable and simplest — clicking a suggestion sends it immediately.
  - Add the persistent nook: when `mascot.kind` is one of `idle` / `result` / `refusal` / `error`, render an absolutely-positioned `<div className="absolute left-2.5 bottom-2 z-10">` containing `<Mascot pose={mascot.pose} size="chip" />` inside the chat column. Hidden during `welcome` / `thinking` / `presenting`.
  - Restyle the `<header>`: add `<Mascot pose={headerPose} size="chip" />` before the brand text, where `headerPose` is `mascot.pose` if it has one, else `clasped`. Brand text gets `font-serif`. The "close source panel" link becomes a small ghost button (`border border-edge rounded px-2 py-0.5 text-xs hover:bg-panel`).
  - Mount `<Footer connected={state.error === null} />` as the last child of the outer column (below `MessageInput`). (`connected` is approximated by "no error" for v1 — a precise YouCoded heartbeat is out of scope.)

- [ ] **Step 2b: Adjust the input padding for the nook.** The `MessageInput` wrapper needs left padding so the nook mascot doesn't overlap the text field — add `pl-24` to the input row container (matches the mockup's `cv-input` padding).

- [ ] **Step 3: Type-check + full suite.** Run: `npm run typecheck && npm run test`
Expected: both pass. `tests/chat-reducer.test.ts` and the others are unaffected.

- [ ] **Step 4: Manual browser check.** Run `npm run dev`. Verify the full flow: welcome hero on load → type a question → side-typing scene appears → answer renders, presenting beat flashes, nook mascot shows clipboard pose. Then re-test with the OS `prefers-reduced-motion` setting on — confirm no animation but poses still change. Stop the dev server once it's on `origin/master` (per CLAUDE.md).

- [ ] **Step 5: Commit.**

```bash
git add web/app/page.tsx web/components/ChatThread.tsx
git commit -m "feat(web): integrate mascot — welcome hero, typing scene, nook, footer"
```

## Task 17: Tertiary touches

**Files:**
- Modify: `web/app/globals.css`
- Modify: `web/components/PdfViewer.tsx`

- [ ] **Step 1: Focus rings + scrollbars.** In `globals.css`, retune the existing `::-webkit-scrollbar-thumb` to `background: var(--edge)` (already theme-driven — confirm it still reads right on the new palette). Add a global focus-visible ring:

```css
:where(button, input, textarea, a):focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
```

- [ ] **Step 2: PdfViewer empty + loading states.** In `PdfViewer.tsx`, find the empty state ("we couldn't find source metadata" / "click a citation") and the loading state. For the empty state, add `<Mascot pose="clipboard" size="hero" />` above the existing message and reword to "Click a citation to see its source." For the loading state, replace any spinner with a civic-tinted shimmer block (`bg-inset animate-pulse rounded`). Do NOT touch the pdfjs render logic.

- [ ] **Step 3: Run the suite.** Run: `npm run test`
Expected: `tests/pdf-route.test.ts` unaffected (it tests the API route, not the viewer component); all pass.

- [ ] **Step 4: Commit.**

```bash
git add web/app/globals.css web/components/PdfViewer.tsx
git commit -m "feat(web): focus rings, scrollbars, PdfViewer empty/loading states"
```

## Task 18: Final verification

**Files:** none (verification only)

- [ ] **Step 1: Full type-check.** Run: `npm run typecheck`
Expected: PASS, no errors.

- [ ] **Step 2: Full test suite.** Run: `npm run test`
Expected: all pass — 109 pre-existing + the new tests from Tasks 4, 6, 7, 8, 9, 10, 11, 13. Confirm the count went UP, not down.

- [ ] **Step 3: Production build.** Run: `npm run build`
Expected: build succeeds, fonts inline, no CSS errors.

- [ ] **Step 4: Manual smoke (dev server).** Run `npm run dev`. Walk the whole flow once more — welcome → ask → thinking → answer → citation chip click opens the PDF panel → close panel. Confirm: civic-warm palette everywhere, no leftover grayscale, mascot present and reactive, footer honesty line visible, no console errors. Check `prefers-reduced-motion` once. Stop the dev server.

- [ ] **Step 5: Commit (if any cleanup was needed).** If Steps 1–4 surfaced fixes, commit them:

```bash
git add -A
git commit -m "fix(web): UI refresh final-verification fixes"
```

---

## Notes for the implementer

- **Refusal is built but not auto-triggered.** `useMascotPose` has the `crossed`/`refusal` path and `RefusalBanner` is restyled, but nothing in v1 sets `refusalActive = true` — refusal auto-detection is the separate, deferred Phase 1c WS5. This is intentional and consistent with how `RefusalBanner` already shipped (props-driven, not wired). Do not invent a refusal heuristic.
- **`sides` and `hips` poses** are built and tested but wired to no trigger — they exist for future use. Don't delete them.
- **Laptop colors are not themed.** The mascot reads `--mascot-*` variables; the laptop's silver palette stays as literal hex (it's the laptop's own identity, not the mascot's). Only the laptop *screen* uses `var(--mascot-cap)` since it's civic-blue.
- **Never tween pixel art.** Every animation uses `steps()` or discrete state swaps. No `transition` on transforms of mascot sub-parts, no smooth scale/rotate. The one exception is the citation-chip click pop (Task 14) — that's a UI chip, not the mascot.
