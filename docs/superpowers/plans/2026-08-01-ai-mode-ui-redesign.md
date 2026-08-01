# AI Mode UI Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the AI Mode page's layout skeleton on YouCoded's scroll model (one scroller, floating chrome, compact tool rows) rendered entirely in the app's navy design tokens, per the approved spec `docs/superpowers/specs/2026-08-01-ai-mode-ui-redesign-design.md`.

**Architecture:** Webapp-only. The chat stack in `webapp/src/chat/` + `webapp/src/pdf/` keeps its logic (reducer, SSE, citation extraction) untouched; the changes are layout containers, one new `ToolGroup` component, a last-value-replay upgrade to the citation bus, and a large CSS rewrite inside `webapp/src/styles/app.css`'s existing chat/pdf/AI blocks. Stage 1 (Tasks 1–6) is pure defect fixes and independently shippable.

**Tech Stack:** React 18 + Vite + vitest (jsdom) + plain CSS (no Tailwind, no CSS modules). Test command: `cd webapp && npx vitest run`. Type check: `cd webapp && npx tsc -b`.

## Global Constraints

- **S12 one-palette rule:** `webapp/src/styles/tokens.css` is a verbatim mockup copy — NEVER edit it. No new colors anywhere. The `--chat-danger/warn/ok` trio and `--mascot-*` set stay as-is (documented safety exception, `app.css:741-755`).
- **New custom properties allowed:** only `--ai-col` (layout constant) and `--ai-bottom-chrome` (measured height), both in `app.css`'s chat/AI blocks. They are layout plumbing, not palette.
- **Radii:** only `var(--r-md)` 16px, `var(--r-sm)` 12px, `var(--r-pill)` — plus the 4px bubble "tail" corner and the existing 4px cite-chip radii. No 6/8/10px literals may survive in the chat/pdf/AI CSS blocks.
- **Type floor:** nothing below 11px except `.chat-cite-sup` (9px superscript). Micro-labels use the app idiom: `font-size:11px; font-weight:800; text-transform:uppercase; letter-spacing:.08em` (source: `app.css:550`).
- **Core Invariants 1–3 preserved behaviorally:** failed citations stay visibly marked (danger color, strikethrough, tooltip reason); `RefusalBanner`'s detection logic (`detectRefusal`) is NOT modified — placement only; the Footer honesty sentence "Answers are cited, not guaranteed. Verify against sources." is kept verbatim.
- **DO NOT MODIFY:** `webapp/src/chat/citation-extract.ts`, `chat-reducer.ts`, `use-chat.ts`, `provider-events.ts`, anything under `app/` or `harness/`. No eval run is needed (nothing on the retrieval path changes).
- **WHY comments:** Destin is a non-developer; annotate every non-trivial edit with a WHY comment (see CLAUDE.md).
- **`html.ai-fullpage` gating:** the viewport pin must stay gated on that class — `webapp/src/pages/Ai.fullpage.test.tsx` reads `app.css` and fails if it's hoisted to bare `html`/`body`.
- **Worktree:** all work in `~/ask-the-budget-az-worktrees/ai-mode-ui-redesign/` (Task 0). Merge = merge AND push.

---

### Task 0: Worktree + baseline

**Files:** none (setup only)

- [ ] **Step 1: Sync and create the worktree**

```bash
cd ~/YouCoded/Projects/ask-the-budget-az-dev
git fetch origin && git pull origin master
git worktree add ~/ask-the-budget-az-worktrees/ai-mode-ui-redesign -b ai-mode-ui-redesign
cd ~/ask-the-budget-az-worktrees/ai-mode-ui-redesign/webapp
npm install
```

- [ ] **Step 2: Baseline — the full suite must be green before any change**

Run: `npx vitest run 2>&1 | tail -5`
Expected: `Test Files  N passed` (≈304 tests, 0 failures). Record N — every later task compares against it.

---

## Stage 1 — Defect pass (independently shippable)

### Task 1: Kill the phantom horizontal scrollbar + pointless nested scroller

**Files:**
- Modify: `webapp/src/styles/app.css` (lines ~806, ~1016)
- Test: `webapp/src/chat/__tests__/chat-css-contract.test.ts` (create)

**Interfaces:** none — CSS only. Later tasks extend the same CSS-contract test file.

- [ ] **Step 1: Write the failing test**

The repo already has the pattern of testing CSS by reading the file (`pages/Ai.fullpage.test.tsx`). Create `webapp/src/chat/__tests__/chat-css-contract.test.ts`:

```ts
// Pins structural CSS decisions that jsdom cannot render but that broke the
// page in production: the thread scroller must never become a horizontal
// scroll container (overflow-y:auto computes overflow-x:auto unless guarded
// — the same bug .yscroll fixed at app.css:541), and pre-wrap blocks must
// not declare overflow:auto (pre-wrap cannot overflow on x, so the rule only
// created a useless nested scroll context).
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  resolve(__dirname, "../../styles/app.css"),
  "utf-8",
);

/** The full rule body for a selector (first occurrence). */
function ruleFor(selector: string): string {
  const start = css.indexOf(selector);
  expect(start, `selector ${selector} must exist`).toBeGreaterThan(-1);
  const open = css.indexOf("{", start);
  const close = css.indexOf("}", open);
  return css.slice(open + 1, close);
}

describe("chat CSS containment contract", () => {
  it("the thread scroller guards its x axis", () => {
    expect(ruleFor(".chat-thread-scroll")).toMatch(/overflow-x:\s*hidden/);
  });

  it("pre-wrap tool output does not declare its own scroll context", () => {
    expect(ruleFor(".chat-block pre")).not.toMatch(/overflow:\s*auto/);
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/chat/__tests__/chat-css-contract.test.ts`
Expected: FAIL — both specs (no `overflow-x: hidden` on the scroller; `overflow: auto` present on `.chat-block pre`).

- [ ] **Step 3: Make the CSS edits**

In `webapp/src/styles/app.css` line ~806, change:

```css
.chat-thread-scroll { height: 100%; overflow-y: auto; padding: 24px 16px 8px; }
```

to:

```css
/* overflow-x:hidden is load-bearing, not tidiness: overflow-y:auto silently
   computes overflow-x:auto, so anything absolutely positioned past the right
   edge (the 320px citation tooltip was the trigger) spawned a horizontal
   scrollbar across the whole thread. Same bug .yscroll fixed above. */
.chat-thread-scroll { height: 100%; overflow-y: auto; overflow-x: hidden; padding: 24px 16px 8px; }
```

At line ~1016, change:

```css
.chat-block pre { font-size: 12px; color: var(--ink-2); background: var(--canvas); border: 1px solid var(--line); border-radius: 6px; padding: 8px; overflow: auto; white-space: pre-wrap; font-family: var(--chat-mono); margin: 0; }
```

to (drop `overflow: auto` only — the radius changes later, in Task 12):

```css
/* No overflow rule: white-space:pre-wrap means the x axis can never overflow,
   and CollapsibleBlock caps the y axis at 20 lines — the old overflow:auto
   only manufactured a nested scrollbar inside a scrollbar. */
.chat-block pre { font-size: 12px; color: var(--ink-2); background: var(--canvas); border: 1px solid var(--line); border-radius: 6px; padding: 8px; white-space: pre-wrap; font-family: var(--chat-mono); margin: 0; }
```

- [ ] **Step 4: Run the test to verify it passes, then the full suite**

Run: `npx vitest run src/chat/__tests__/chat-css-contract.test.ts` → PASS
Run: `npx vitest run 2>&1 | tail -3` → same N as baseline, 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/styles/app.css src/chat/__tests__/chat-css-contract.test.ts
git commit -m "fix(webapp): guard chat scroller x-axis, drop nested scroll context in tool output"
```

---

### Task 2: Citation bus last-value replay (fixes the first-click empty panel)

**Files:**
- Modify: `webapp/src/chat/citation-context.tsx:36-55`
- Test: `webapp/src/chat/__tests__/citation-bus.test.tsx` (extend)
- Test: `webapp/src/pdf/__tests__/pdf-viewer.test.tsx` (extend)

**Interfaces:**
- Produces: `CitationBus.subscribe(handler)` now REPLAYS the most recent `select()`ed citation to the new subscriber synchronously, once, at subscribe time. Signature unchanged.

- [ ] **Step 1: Write the failing bus test**

In `webapp/src/chat/__tests__/citation-bus.test.tsx`, add (reuse the file's existing `Citation` fixture — it already constructs citations for its other specs; do not invent a second fixture shape):

```tsx
it("replays the last selection to a subscriber that mounts after the click", async () => {
  // Reproduces the first-chip-click bug: PdfViewer mounts BECAUSE of the
  // click, so its subscription used to run after the event had already been
  // delivered — and the panel opened empty until a second click.
  const seen = vi.fn();

  function Clicker() {
    const bus = useCitationBus();
    return (
      <button type="button" onClick={() => bus.select(citation)}>
        fire
      </button>
    );
  }
  function LateViewer() {
    useCitationSelected(seen);
    return null;
  }

  const { rerender } = render(
    <CitationBusProvider>
      <Clicker />
    </CitationBusProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "fire" }));
  expect(seen).not.toHaveBeenCalled();

  // Same provider instance, new child — the shape of PdfViewer mounting.
  rerender(
    <CitationBusProvider>
      <Clicker />
      <LateViewer />
    </CitationBusProvider>,
  );
  expect(seen).toHaveBeenCalledTimes(1);
  expect(seen).toHaveBeenCalledWith(citation);
});
```

(`citation` = the existing fixture variable in that file; match its actual name when editing.)

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/chat/__tests__/citation-bus.test.tsx`
Expected: FAIL — `seen` called 0 times after rerender.

- [ ] **Step 3: Implement replay in the bus**

In `webapp/src/chat/citation-context.tsx`, inside `CitationBusProvider`:

```tsx
  const handlersRef = useRef<Set<CitationHandler>>(new Set());
  // The most recent selection, kept so a viewer that mounts BECAUSE of a
  // click still receives that click. Without this the first chip click
  // opened an empty source panel and the analyst had to click twice —
  // the subscriber's useEffect can only run after the mount that the
  // select() itself triggered.
  const lastRef = useRef<Citation | null>(null);

  const select = useCallback((citation: Citation) => {
    lastRef.current = citation;
    for (const h of handlersRef.current) {
      try {
        h(citation);
      } catch (err) {
        console.error("[citation-bus] subscriber threw:", err);
      }
    }
  }, []);

  const subscribe = useCallback((handler: CitationHandler) => {
    handlersRef.current.add(handler);
    if (lastRef.current !== null) {
      // Replay is once, synchronous, and only to the late subscriber —
      // existing subscribers already saw the live event.
      try {
        handler(lastRef.current);
      } catch (err) {
        console.error("[citation-bus] subscriber threw on replay:", err);
      }
    }
    return () => {
      handlersRef.current.delete(handler);
    };
  }, []);
```

(StrictMode's double-mounted effect subscribes twice and therefore replays twice; both deliveries carry the same citation into a `setState`, which is idempotent — no guard needed.)

- [ ] **Step 4: Add the viewer-level regression spec**

In `webapp/src/pdf/__tests__/pdf-viewer.test.tsx` (it already mocks `SourceView` — reuse that mock), add:

```tsx
it("shows the source on the FIRST chip click (mount-after-select)", async () => {
  // The real sequence: chip click -> select() -> AiModePanel opens the aside
  // -> PdfViewer mounts. The bus replay is what makes this render SourceView
  // instead of the 'Click a citation' empty state.
  function Clicker() {
    const bus = useCitationBus();
    return (
      <button type="button" onClick={() => bus.select(resolvedCitation)}>
        chip
      </button>
    );
  }
  const { rerender } = render(
    <CitationBusProvider>
      <Clicker />
    </CitationBusProvider>,
  );
  await userEvent.click(screen.getByRole("button", { name: "chip" }));
  rerender(
    <CitationBusProvider>
      <Clicker />
      <PdfViewer />
    </CitationBusProvider>,
  );
  expect(screen.getByTestId("source-view")).toBeInTheDocument();
  expect(
    screen.queryByText(/Click a citation to see its source/),
  ).not.toBeInTheDocument();
});
```

(`resolvedCitation` = that file's existing resolved-citation fixture; match its actual name.)

- [ ] **Step 5: Run both files, then the full suite**

Run: `npx vitest run src/chat/__tests__/citation-bus.test.tsx src/pdf/__tests__/pdf-viewer.test.tsx` → PASS
Run: `npx vitest run 2>&1 | tail -3` → baseline+2, 0 failures.

- [ ] **Step 6: Commit**

```bash
git add src/chat/citation-context.tsx src/chat/__tests__/citation-bus.test.tsx src/pdf/__tests__/pdf-viewer.test.tsx
git commit -m "fix(webapp): citation bus replays last selection — first chip click shows the source"
```

---

### Task 3: Citation tooltip escapes the scroller (position:fixed)

**Files:**
- Modify: `webapp/src/chat/CitationChip.tsx`
- Modify: `webapp/src/styles/app.css:926`
- Test: `webapp/src/chat/__tests__/citation-chip.test.tsx` (extend)

**Interfaces:** none — presentation only. Citation extraction and the ~70 carried specs must keep passing unchanged.

- [ ] **Step 1: Why fixed, not a portal (do not re-litigate during implementation)**

The tooltip must stay a DOM child of the hover-tracked `<span className="chat-cite-wrap">` — the whole open/close mechanism is `onMouseEnter/onMouseLeave` on that span, and a portal would fire `mouseleave` the moment the cursor crosses into the tooltip, closing it before "Copy citation" is reachable. `position:fixed` keeps the DOM tree (hover semantics intact) while removing the element from the scroller's clip/scroll geometry. One caveat: a `transform` on an ancestor would re-anchor `fixed` — the only transform nearby is on `.cite-chip` (the button), which is a SIBLING of the tooltip, so this is safe.

- [ ] **Step 2: Write the failing test**

Add to `webapp/src/chat/__tests__/citation-chip.test.tsx`:

```tsx
it("positions the tooltip fixed so the thread scroller cannot clip it", async () => {
  render(
    <CitationBusProvider>
      <CitationChip citation={citation} inlineText="the claim" />
    </CitationBusProvider>,
  );
  await userEvent.hover(screen.getByRole("button", { name: /Citation/ }));
  const tip = screen.getByRole("tooltip");
  // Inline style carries the computed coordinates; the class carries
  // position:fixed (asserted via the CSS contract test).
  expect(tip.style.left).not.toBe("");
  expect(tip.style.bottom).not.toBe("");
});

it("closes the tooltip when the thread scrolls (fixed coords would go stale)", async () => {
  render(
    <CitationBusProvider>
      <CitationChip citation={citation} inlineText="the claim" />
    </CitationBusProvider>,
  );
  await userEvent.hover(screen.getByRole("button", { name: /Citation/ }));
  expect(screen.getByRole("tooltip")).toBeInTheDocument();
  fireEvent.scroll(window);
  expect(screen.queryByRole("tooltip")).not.toBeInTheDocument();
});
```

And to `chat-css-contract.test.ts`:

```ts
  it("the citation tooltip is fixed-position (escapes the scroller's clip)", () => {
    expect(ruleFor(".chat-cite-tooltip")).toMatch(/position:\s*fixed/);
  });
```

- [ ] **Step 3: Run to verify both fail**

Run: `npx vitest run src/chat/__tests__/citation-chip.test.tsx src/chat/__tests__/chat-css-contract.test.ts`
Expected: FAIL (no inline coords, position is absolute).

- [ ] **Step 4: Implement**

In `CitationChip.tsx` — replace the plain `setOpen(true)` open paths with a measuring open, and thread coordinates to the tooltip:

```tsx
const TOOLTIP_WIDTH_PX = 320; // must match .chat-cite-tooltip width

export default function CitationChip({ citation, inlineText }: Props) {
  const [open, setOpen] = useState(false);
  const [tipPos, setTipPos] = useState<{ left: number; bottom: number } | null>(null);
  const [firing, setFiring] = useState(false);
  const wrapRef = useRef<HTMLSpanElement | null>(null);
  const bus = useCitationBus();

  // Fixed positioning needs viewport coordinates computed at open time.
  // Clamped to the viewport so a chip at the right edge no longer pushes
  // 320px past the column (that push was the horizontal-scrollbar source).
  const openTip = () => {
    const rect = wrapRef.current?.getBoundingClientRect();
    if (rect) {
      const left = Math.max(
        8,
        Math.min(rect.left, window.innerWidth - TOOLTIP_WIDTH_PX - 8),
      );
      setTipPos({ left, bottom: window.innerHeight - rect.top + 4 });
    }
    setOpen(true);
  };

  // A fixed tooltip does not travel with the scrolled text under it, so any
  // scroll closes it rather than letting it drift off its chip. Capture
  // phase because the thread scroller's scroll event does not bubble.
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    window.addEventListener("scroll", close, true);
    window.addEventListener("resize", close);
    return () => {
      window.removeEventListener("scroll", close, true);
      window.removeEventListener("resize", close);
    };
  }, [open]);
  ...
```

Wire it in both render branches: `ref={wrapRef}` on the wrapping span, `onMouseEnter={openTip}` / `onFocus={openTip}` (leave `onMouseLeave`/`onBlur` as `() => setOpen(false)`), and pass coords to the tooltip:

```tsx
{open && <CitationTooltip citation={citation} pos={tipPos} />}
```

`CitationTooltip` gains the prop and applies it inline:

```tsx
function CitationTooltip({ citation, pos }: Props & { pos?: { left: number; bottom: number } | null }) {
  ...
  return (
    <div
      role="tooltip"
      className="chat-cite-tooltip"
      style={pos ? { left: pos.left, bottom: pos.bottom } : undefined}
      onMouseEnter={(e) => e.stopPropagation()}
    >
```

In `app.css:926` change the positioning half of the rule (radius/shadow unchanged until Task 13):

```css
/* position:fixed, coords supplied inline by CitationChip at open time. The
   tooltip stays a DOM child of the hover span (portal would break the
   mouseleave hand-off to "Copy citation") but fixed positioning takes it out
   of the thread scroller's clip — a chip on the first visible line used to
   have its tooltip decapitated by overflow, and a right-edge chip spawned a
   horizontal scrollbar. */
.chat-cite-tooltip { position: fixed; z-index: 80; width: 320px; border-radius: 10px; border: 1px solid var(--line); background: var(--card); box-shadow: var(--shadow); padding: 12px; font-size: 12px; color: var(--ink); cursor: default; text-align: left; }
```

(`z-index: 80` — above the sticky site header's 50 and the search drawer's 60; a fixed element competes with page chrome, not just thread content.)

- [ ] **Step 5: Run the chip suite, then everything**

Run: `npx vitest run src/chat/__tests__/citation-chip.test.tsx src/chat/__tests__/chat-css-contract.test.ts` → PASS
Run: `npx vitest run 2>&1 | tail -3` → 0 failures (the existing hover specs must still pass — they assert content, not coordinates).

- [ ] **Step 6: Commit**

```bash
git add src/chat/CitationChip.tsx src/styles/app.css src/chat/__tests__/citation-chip.test.tsx src/chat/__tests__/chat-css-contract.test.ts
git commit -m "fix(webapp): citation tooltip goes position:fixed — no more scroller clipping or phantom h-scrollbar"
```

---

### Task 4: PDF fit-to-width uses one box model

**Files:**
- Modify: `webapp/src/pdf/SourceView.tsx:107-126, 177`
- Test: `webapp/src/pdf/__tests__/source-view-sizing.test.tsx` (create)

**Interfaces:**
- Produces: `PdfPage` receives `containerWidth` equal to the scroller's CONTENT width (padding excluded), with no further subtraction. Zoom 1.0 = page fills the container exactly.

- [ ] **Step 1: Write the failing test**

Create `webapp/src/pdf/__tests__/source-view-sizing.test.tsx`:

```tsx
// The bug: the initial measurement used clientWidth (which INCLUDES the
// scroller's 24px padding) while the ResizeObserver wrote contentRect.width
// (which EXCLUDES it), and both were then reduced by a constant 24 — so in a
// real browser the page rendered 24px narrower than fit-to-width, forever.
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const pageProps = vi.fn();
vi.mock("../PdfPage", () => ({
  default: (props: Record<string, unknown>) => {
    pageProps(props);
    return <div data-testid="pdf-page" />;
  },
}));

import { SourceView } from "../SourceView";

class ImmediateRO {
  cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) {
    this.cb = cb;
  }
  observe() {
    // Fire like a real browser's initial observation, with a known width.
    this.cb(
      [{ contentRect: { width: 500 } }] as unknown as ResizeObserverEntry[],
      this as unknown as ResizeObserver,
    );
  }
  disconnect() {}
  unobserve() {}
}

describe("SourceView container sizing", () => {
  it("passes the content-box width through to PdfPage unreduced", async () => {
    vi.stubGlobal("ResizeObserver", ImmediateRO);
    render(
      <SourceView
        docId="doc-1"
        page={3}
        bbox={null}
        chunkText="some chunk text"
        spanStart={0}
        spanEnd={4}
        docTitle="Test Doc"
        sourceLabel="Test Doc, p. 3"
      />,
    );
    await waitFor(() => expect(screen.getByTestId("pdf-page")).toBeInTheDocument());
    const last = pageProps.mock.calls.at(-1)![0] as { containerWidth: number };
    expect(last.containerWidth).toBe(500); // NOT 476
    vi.unstubAllGlobals();
  });
});
```

- [ ] **Step 2: Run it to verify it fails**

Run: `npx vitest run src/pdf/__tests__/source-view-sizing.test.tsx`
Expected: FAIL — `containerWidth` is 476 (500 − 24).

- [ ] **Step 3: Implement**

In `SourceView.tsx`, the measurement effect becomes:

```tsx
  // Must match .pdf-scroller's horizontal padding (12px each side). The seed
  // and the observer MUST measure the same box: the observer reports
  // contentRect (padding excluded), so the clientWidth seed subtracts the
  // padding to match. Mixing the two box models is what used to render the
  // page 24px short of fit-to-width.
  const PDF_SCROLLER_PADDING_PX = 24;
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  useEffect(() => {
    const el = scrollerRef.current;
    if (!el) return;
    setContainerWidth(Math.max(0, el.clientWidth - PDF_SCROLLER_PADDING_PX));
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver((entries) => {
      for (const entry of entries) {
        setContainerWidth(entry.contentRect.width);
      }
    });
    obs.observe(el);
    return () => obs.disconnect();
  }, []);
```

And at the use site (line ~177), drop the second subtraction:

```tsx
                <PdfPage
                  docId={docId}
                  pageNumber={page!}
                  bbox={bbox}
                  searchTexts={searchTexts}
                  containerWidth={containerWidth}
                  zoomLevel={zoom}
                />
```

- [ ] **Step 4: Run the new file, then the full suite**

Run: `npx vitest run src/pdf/__tests__/source-view-sizing.test.tsx` → PASS
Run: `npx vitest run 2>&1 | tail -3` → 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/pdf/SourceView.tsx src/pdf/__tests__/source-view-sizing.test.tsx
git commit -m "fix(webapp): PDF fit-to-width measures one box model — page fills the panel at 100%"
```

---

### Task 5: Source panel close button

**Files:**
- Modify: `webapp/src/chat/AiModePanel.tsx:225-234`
- Modify: `webapp/src/styles/app.css` (AI Mode block, after `.ai-panel-source`)
- Test: `webapp/src/pages/Ai.test.tsx` or a new `webapp/src/chat/__tests__/ai-mode-panel-source.test.tsx` (create — AiModePanel has no dedicated suite; Ai.test.tsx mounts the whole page)

**Interfaces:**
- Produces: the aside carries a `button[aria-label="Close source panel"]`; clicking it sets `viewerOpen=false`; a later chip click re-opens (the existing `useCitationSelected` subscription already does this). Task 15 relocates this button into the merged PDF header — keep it a distinct element so that move is mechanical.

- [ ] **Step 1: Write the failing test**

Create `webapp/src/chat/__tests__/ai-mode-panel-source.test.tsx`. Model the mocks on `pages/Ai.test.tsx` (it already stubs `useChat`/`useAiStatus` shapes); mock `../pdf/PdfViewer` to a marker div so pdfjs never loads:

```tsx
vi.mock("../../pdf/PdfViewer", () => ({
  default: () => <div data-testid="pdf-viewer" />,
}));

// Minimal UseChatResult stub — state with one cited assistant turn is not
// needed; the panel opens on ANY bus select, so the test drives the bus
// directly through a chip stand-in.
function Chip() {
  const bus = useCitationBus();
  return (
    <button type="button" onClick={() => bus.select(citationFixture)}>
      chip
    </button>
  );
}

it("close button hides the source panel; a new chip click reopens it", async () => {
  render(<AiModePanel chat={chatStub} status={statusStub} corpus="budget" />);
  // Note: the Chip must render INSIDE AiModePanel's provider. Easiest: give
  // chatStub a state whose latest assistant turn carries a resolved citation
  // and click the real chip — OR export PanelBody for tests. Prefer the real
  // chip if the existing Ai.test.tsx fixtures already build a cited turn;
  // reuse those fixtures.
  await userEvent.click(screen.getByRole("button", { name: /chip|Citation/ }));
  expect(screen.getByTestId("pdf-viewer")).toBeInTheDocument();

  await userEvent.click(
    screen.getByRole("button", { name: "Close source panel" }),
  );
  expect(screen.queryByTestId("pdf-viewer")).not.toBeInTheDocument();

  await userEvent.click(screen.getByRole("button", { name: /chip|Citation/ }));
  expect(screen.getByTestId("pdf-viewer")).toBeInTheDocument();
});
```

(Reuse `pages/Ai.test.tsx`'s chat-state fixtures for a cited turn if present; otherwise build the minimal `ChatState` the same way that file does.)

- [ ] **Step 2: Run to verify it fails** — no button named "Close source panel".

- [ ] **Step 3: Implement**

In `AiModePanel.tsx` `PanelBody`:

```tsx
        {viewerOpen && (
          <aside className="ai-panel-source" aria-label="Source document">
            {/* Reversal of the "stays for the rest of the session" decision
                (spec D6): the split halves the chat column, so the analyst
                must be able to get their reading width back. Any later chip
                click re-opens via the bus subscription above. */}
            <button
              type="button"
              className="ai-source-close"
              aria-label="Close source panel"
              onClick={() => setViewerOpen(false)}
            >
              <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
                <path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" />
              </svg>
            </button>
            <PdfViewer />
          </aside>
        )}
```

CSS (AI Mode block, after `.ai-panel-source` at ~1471) — the drawer close recipe (`app.css:1207`) re-scoped onto the panel's light chrome:

```css
/* Close pill for the source column. Same 28px circular affordance as the
   search drawer's close, restyled for the light header area it floats over.
   Task 15 moves it into the merged PDF header row; keep the class. */
.ai-source-close{position:absolute;top:8px;right:8px;z-index:5;display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border:1px solid var(--line);border-radius:var(--r-pill);background:var(--card);color:var(--ink-2);cursor:pointer;transition:border-color .15s,color .15s;}
.ai-source-close:hover{border-color:var(--az-gold);color:var(--az-gold-d);}
```

And make the aside a positioning context — extend the `.ai-panel-source` rule at ~1471 with `position:relative;`.

- [ ] **Step 4: Run new file + full suite** → PASS / 0 failures.

- [ ] **Step 5: Commit**

```bash
git add src/chat/AiModePanel.tsx src/styles/app.css src/chat/__tests__/ai-mode-panel-source.test.tsx
git commit -m "feat(webapp): source panel gets a close button — chat width is recoverable"
```

---

### Task 6: Delete dead code and dead CSS

**Files:**
- Modify: `webapp/src/chat/AiModePanel.tsx` (delete `AiModeToggle`, `AI_GATED_TOOLTIP`/`AI_PROBING_TOOLTIP` stay — `Ai.tsx` imports them)
- Modify: `webapp/src/styles/app.css` (three dead blocks)
- Test: existing suites (deletion is verified by them staying green + grep)

**Interfaces:** `AiModePanel` still exports `AiModePanel`, `AI_GATED_TOOLTIP`, `AI_PROBING_TOOLTIP`. `AiModeToggle` and its `ToggleProps` are deleted.

- [ ] **Step 1: Confirm the toggle really has no importers**

Run: `grep -rn "AiModeToggle" src/ --include="*.tsx" --include="*.ts" | grep -v test`
Expected: only the definition in `AiModePanel.tsx`. (Test files that import it get their toggle-specific specs deleted in Step 2 — STATUS.md already marks this deletion as belonging to "whoever next edits that file".)

- [ ] **Step 2: Delete**

1. In `AiModePanel.tsx`: remove the `AiModeToggle` component and its `ToggleProps` interface (lines ~46-93) and the now-unused Arizona-star SVG. Keep both tooltip constants.
2. Remove any specs that render `AiModeToggle` (search `src/**/__tests__` and `pages/*.test.tsx` for `AiModeToggle`); delete only those specs, not their files.
3. In `app.css`: delete the `.ai-panel` fallback declarations that are all overridden on the only route that mounts it — replace lines ~1417-1432 with:

```css
/* ----- the panel ----------------------------------------------------------
   The panel fills the stage (the AI route is the only mount — the old
   clamp(440px,68vh,760px) "future host" fallback was dead weight whose only
   surviving declaration was an accidental overflow:hidden). overflow:hidden
   is kept DELIBERATELY: it is what clips the thread and source columns to
   the viewport instead of letting them push the composer off-screen. */
.ai-panel{display:flex;flex-direction:column;flex:1 1 auto;min-height:0;overflow:hidden;}
```

   …and delete the now-redundant `.page-ai .ai-panel{flex:1 1 auto;min-height:0;height:auto;margin-top:0;}` (~1432) and `.page-ai .ai-panel{background:none;border:0;border-radius:0;box-shadow:none;}` (~1448) — the base rule no longer sets card chrome, so there is nothing to undo.
4. Delete the duplicate divider rule at ~1451 (`.page-ai .ai-panel-main.has-source .ai-panel-chat{border-right:…}`) — keep the unscoped one at ~1464.
5. Delete `.mascot-typing-hand` (~1082) and its mention in the reduced-motion block (keep `.mascot-typing-cursor` and the `.work-*` halts).

- [ ] **Step 3: Full suite + typecheck**

Run: `npx vitest run 2>&1 | tail -3` → 0 failures (minus any deleted toggle specs).
Run: `npx tsc -b` → clean.

- [ ] **Step 4: Commit**

```bash
git add -A src/
git commit -m "chore(webapp): delete AiModeToggle and dead AI-panel/mascot CSS"
```

**⛔ STAGE 1 GATE:** all defect fixes are in. This is a mergeable checkpoint if work must pause.

---

## Stage 2 — Skeleton: one grid, one scroller, floating chrome

### Task 7: One alignment grid + compact band

**Files:**
- Modify: `webapp/src/styles/app.css` (chat `:root` block ~774; `.chat-thread-column` ~811; `.chat-notice-banner` ~865; `.chat-input` ~868; `.ai-tiers` ~1480; `.ai-tier-pop` ~1493; `.chat-refusal` ~1512; `.page-ai .subhero .wrap` ~1326; `.ai-corpus-note` ~1357)
- Modify: `webapp/src/pages/Ai.tsx:134-136`
- Test: `webapp/src/chat/__tests__/chat-css-contract.test.ts` (extend)

**Interfaces:**
- Produces: CSS custom property `--ai-col` (the single content measure, 768px) declared in the chat `:root` block. Every later task uses `var(--ai-col)` instead of a 768px literal.

- [ ] **Step 1: Extend the CSS contract test**

```ts
  it("one content measure: no 768px literals outside the --ai-col definition", () => {
    // Everything that used to hardcode the column width must read the token,
    // so the band, thread, banners and composer share one left edge.
    const chatBlock = css.slice(css.indexOf("/* ===== chat ====="));
    const literals = chatBlock.match(/max-width:\s*768px/g) ?? [];
    expect(literals).toHaveLength(0);
    expect(css).toMatch(/--ai-col:\s*768px/);
  });
```

- [ ] **Step 2: Run to verify it fails** (six `max-width:768px` sites exist).

- [ ] **Step 3: Implement**

1. In the chat `:root` block (after `--chat-mono`, ~line 782):

```css
  /* THE content measure for the AI route. The thread column, the composer,
     every banner and the band's own content all read this one number — that
     is what makes the page share a single left edge instead of the three
     unaligned grids it shipped with (band at 1140, stage full-bleed, thread
     at a private 768). Layout constant, not palette — S12 unaffected. */
  --ai-col: 768px;
```

2. Replace every `max-width: 768px` in the chat/AI blocks with `max-width: var(--ai-col)` (`.chat-thread-column`, `.chat-notice-banner`, `.chat-input`, `.ai-tiers`, `.ai-tier-pop`, `.chat-refusal`).
3. Align the band to the same measure — change `.page-ai .subhero .wrap` (~1326):

```css
/* The band's content shares the thread's measure (+22px gutters), so the h1
   sits flush over the first message instead of on the 1140px page grid the
   chat below never uses. */
.page-ai .subhero .wrap{position:relative;z-index:2;padding:12px 22px;max-width:calc(var(--ai-col) + 44px);}
```

4. Un-park the switch warning — change `.ai-corpus-note` (~1357):

```css
/* Flows inline after the scope chip instead of margin-left:auto — parking it
   at the far edge of a wide band left a dead gap mid-row, and the band is
   now only as wide as the column anyway. */
.page-ai .ai-corpus-note{margin:0;font-size:11.5px;font-weight:700;color:#b9c0e4;flex:0 1 auto;}
```

5. `Ai.tsx` — no structural change needed (the note element stays; only its CSS placement changed). Verify the band renders as: h1 · chips · scope chip · note, wrapping gracefully.

- [ ] **Step 4: Run contract test + full suite + typecheck** → PASS / 0 failures / clean.

- [ ] **Step 5: Visual check**

Run: `npm run build && cd .. && uv run uvicorn app.main:create_app --factory --port 9301` and open `http://localhost:9301/ai` — the h1's left edge must align with the welcome copy / first message edge at any window ≥ 900px. Kill the server after.

- [ ] **Step 6: Commit**

```bash
git add src/styles/app.css src/pages/Ai.tsx src/chat/__tests__/chat-css-contract.test.ts
git commit -m "feat(webapp): one --ai-col measure — band, thread, composer share a left edge"
```

---

### Task 8: Floating bottom chrome

**Files:**
- Modify: `webapp/src/chat/AiModePanel.tsx` (restructure `PanelBody`'s lower half)
- Modify: `webapp/src/chat/Footer.tsx` (compact restyle — content unchanged)
- Modify: `webapp/src/styles/app.css` (`.ai-composer` ~1479, `.chat-footer` ~904, new `.ai-bottom-chrome`)
- Test: `webapp/src/chat/__tests__/ai-bottom-chrome.test.tsx` (create)

**Interfaces:**
- Produces: `.ai-bottom-chrome` — an absolutely-positioned block inside `.ai-panel-chat` containing (top to bottom): error notice, `SuggestionRow`, `.ai-composer` (tier switch + `MessageInput` + stop), and the Footer line. It measures its own height into the CSS var `--ai-bottom-chrome` set on the `.ai-panel-chat` element via a ResizeObserver. Task 9's scroller padding consumes that var.
- Consumes: nothing new. `RefusalBanner` moves OUT of PanelBody in Task 9 (not here) — leave it in place this task.

- [ ] **Step 1: Write the failing test**

Create `webapp/src/chat/__tests__/ai-bottom-chrome.test.tsx` (reuse `Ai.test.tsx`'s chat/status stubs; mock `../pdf/PdfViewer`):

```tsx
class MeasuredRO {
  cb: ResizeObserverCallback;
  constructor(cb: ResizeObserverCallback) { this.cb = cb; }
  observe(el: Element) {
    Object.defineProperty(el, "offsetHeight", { value: 132, configurable: true });
    this.cb([{ target: el } as unknown as ResizeObserverEntry], this as unknown as ResizeObserver);
  }
  disconnect() {}
  unobserve() {}
}

it("the composer block floats and publishes its measured height", () => {
  vi.stubGlobal("ResizeObserver", MeasuredRO);
  render(<AiModePanel chat={chatStub} status={statusStub} corpus="budget" />);
  const chrome = screen.getByTestId("ai-bottom-chrome");
  expect(chrome).toContainElement(screen.getByRole("textbox"));
  // The chat column carries the measured height as a custom property so the
  // scroller (Task 9) can pad by exactly the chrome's real height.
  const chatCol = chrome.parentElement!;
  expect(chatCol.style.getPropertyValue("--ai-bottom-chrome")).toBe("132px");
  vi.unstubAllGlobals();
});
```

- [ ] **Step 2: Run to verify it fails.**

- [ ] **Step 3: Restructure `PanelBody`**

The returned JSX becomes (RefusalBanner stays where it is until Task 9):

```tsx
  // The chrome measures itself so the thread scroller can pad by its REAL
  // height. One measured var replaces the retired app's guessy constants —
  // suggestion row present or not, stop button present or not, the padding
  // is always exactly right. Deps []: both refs point at elements that exist
  // for the panel's whole life, and the ResizeObserver handles every later
  // size change — re-subscribing per render would only churn observers.
  const chatColRef = useRef<HTMLDivElement | null>(null);
  const chromeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const chrome = chromeRef.current;
    const col = chatColRef.current;
    if (!chrome || !col) return;
    const publish = () =>
      col.style.setProperty("--ai-bottom-chrome", `${chrome.offsetHeight}px`);
    publish();
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(publish);
    obs.observe(chrome);
    return () => obs.disconnect();
  }, []);

  return (
    <section className="ai-panel" data-testid="ai-panel" aria-label="AI Mode">
      {chat.health && !chat.health.ok && (
        <SystemHealthBanner reason={chat.health.reason} />
      )}

      <div className={viewerOpen ? "ai-panel-main has-source" : "ai-panel-main"}>
        <div className="ai-panel-chat" ref={chatColRef}>
          <ChatThread state={state} mascot={mascot} />

          <div className="ai-bottom-chrome" data-testid="ai-bottom-chrome" ref={chromeRef}>
            {state.error && (
              <div className="chat-notice is-danger chat-notice-banner" role="alert">
                <span>{state.error}</span>{" "}
                <button type="button" className="ai-dismiss" onClick={chat.clearError}>
                  dismiss
                </button>
              </div>
            )}
            {state.turns.length === 0 && corpus === "budget" && (
              <SuggestionRow onPick={chat.send} />
            )}
            <div className="ai-composer">
              <TierSwitch status={status} tier={chat.tier} onChange={chat.setTier} />
              <MessageInput
                onSubmit={chat.send}
                disabled={chat.busy}
                placeholder={
                  chat.busy
                    ? "Working — press Stop to interrupt."
                    : "Ask a question — Enter to send, Shift+Enter for a newline"
                }
              />
              {chat.busy && (
                <button type="button" className="ai-stop" onClick={chat.stop}>
                  Stop
                </button>
              )}
            </div>
            <Footer connected={Boolean(status?.available) && !state.error} />
          </div>
        </div>
        {viewerOpen && (
          <aside className="ai-panel-source" aria-label="Source document">
            ... (unchanged from Task 5)
          </aside>
        )}
      </div>

      {refusal && <RefusalBanner refusal={refusal} />}
    </section>
  );
```

(Note the `useEffect` has NO dependency array on purpose — `chromeRef` moves between renders when the suggestion row appears/disappears in jsdom-less environments; re-running publish is cheap and always correct. Keep imports tidy: `useEffect`, `useRef` from react.)

- [ ] **Step 4: CSS**

New rules in the AI Mode block (replacing `.ai-composer`'s standalone border ~1479):

```css
/* ----- floating bottom chrome ----------------------------------------------
   The composer block floats OVER the thread scroller instead of stacking
   under it — the scroller pads its bottom by the measured --ai-bottom-chrome
   height (see .chat-thread-scroll), so content slides behind the chrome and
   there is exactly one scroll container on the page. Translucency + blur so
   the slide-behind reads as depth, with a solid fallback where blur is
   unsupported. */
.ai-panel-chat{position:relative;}
.ai-bottom-chrome{position:absolute;left:0;right:0;bottom:0;z-index:15;border-top:1px solid var(--line);background:var(--card);}
@supports (backdrop-filter: blur(6px)){
  .ai-bottom-chrome{background:rgba(255,255,255,.92);backdrop-filter:blur(6px);}
}
.ai-composer{padding:8px 16px 4px;position:relative;}
```

Footer restyle (`.chat-footer` ~904) — same content, one quiet line, no band:

```css
/* One 11px muted line inside the floating chrome — the separate white banded
   footer read as page chrome on a page that has none. Content unchanged:
   the honesty sentence is Core Invariant 5 territory. */
.chat-footer { flex-shrink: 0; border: 0; background: none; padding: 2px 16px 8px; min-height: 0; display: flex; align-items: center; justify-content: center; flex-wrap: wrap; column-gap: 12px; font-size: 11px; color: var(--ink-3); max-width: var(--ai-col); margin: 0 auto; }
```

- [ ] **Step 5: Run new test + full suite + typecheck.** Footer specs (`footer.test.tsx`) assert content, not layout — they must pass unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/chat/AiModePanel.tsx src/chat/Footer.tsx src/styles/app.css src/chat/__tests__/ai-bottom-chrome.test.tsx
git commit -m "feat(webapp): composer becomes floating bottom chrome with measured height"
```

---

### Task 9: One scroller — welcome inside, refusal in flow, stick model, jump pill

**Files:**
- Modify: `webapp/src/chat/ChatThread.tsx` (welcome-in-scroller, refusal prop, stick upgrade, jump pill)
- Modify: `webapp/src/chat/AiModePanel.tsx` (pass `refusal` down; drop the standalone `<RefusalBanner>` render)
- Modify: `webapp/src/styles/app.css` (`.chat-thread-scroll` padding, `.chat-welcome` ~878, `.chat-refusal` ~1512, new `.chat-jump`)
- Test: `webapp/src/chat/__tests__/chat-thread-scroll.test.tsx` (create); `chat-css-contract.test.ts` (extend)

**Interfaces:**
- Consumes: `--ai-bottom-chrome` (Task 8).
- Produces: `ChatThread` props gain `refusal?: RefusalInfo | null` (type re-exported from `RefusalBanner.tsx` — check its actual exported name, `detectRefusal`'s return type). `WelcomeHero` now renders INSIDE `.chat-thread-scroll`. `RefusalBanner` renders inside `.chat-thread-column` after the turns.

- [ ] **Step 1: Extend the CSS contract test**

```ts
  it("the scroller pads for the floating chrome and the welcome state has no second scroller", () => {
    expect(ruleFor(".chat-thread-scroll")).toMatch(/var\(--ai-bottom-chrome/);
    expect(ruleFor(".chat-welcome")).not.toMatch(/overflow/);
  });
```

- [ ] **Step 2: Write the behavior tests**

Create `webapp/src/chat/__tests__/chat-thread-scroll.test.tsx`:

```tsx
// The scroll model: welcome renders inside the ONE scroller; the refusal
// banner is part of the thread flow (scrolls with history) rather than
// permanent chrome; a jump-to-bottom pill appears when scrolled up.
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ChatThread from "../ChatThread";

const idleMascot = { kind: "idle", pose: "clasped" } as never;

it("empty state renders the welcome INSIDE the thread scroller", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [], isThinking: false, error: null } as never}
      mascot={idleMascot}
    />,
  );
  const scroller = container.querySelector(".chat-thread-scroll")!;
  expect(scroller).not.toBeNull();
  expect(scroller.querySelector(".chat-welcome")).not.toBeNull();
});

it("renders the refusal banner inside the thread column when passed", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
      refusal={refusalFixture}
    />,
  );
  const column = container.querySelector(".chat-thread-column")!;
  expect(column.querySelector(".chat-refusal")).not.toBeNull();
});

it("shows the jump-to-bottom pill only when scrolled away from the bottom", () => {
  const { container } = render(
    <ChatThread
      state={{ turns: [assistantTurnFixture], isThinking: false } as never}
      mascot={idleMascot}
    />,
  );
  expect(screen.queryByRole("button", { name: /Jump to latest/ })).toBeNull();
  const scroller = container.querySelector(".chat-thread-scroll")!;
  // Simulate being 200px above the bottom.
  Object.defineProperty(scroller, "scrollHeight", { value: 1000, configurable: true });
  Object.defineProperty(scroller, "clientHeight", { value: 400, configurable: true });
  Object.defineProperty(scroller, "scrollTop", { value: 400, writable: true, configurable: true });
  fireEvent.scroll(scroller);
  expect(screen.getByRole("button", { name: /Jump to latest/ })).toBeInTheDocument();
});
```

(`assistantTurnFixture` / `refusalFixture`: reuse the fixtures in `refusal-banner.test.tsx` — it builds both an assistant turn and a refusal object for `detectRefusal`.)

- [ ] **Step 3: Run to verify they fail.**

- [ ] **Step 4: Implement `ChatThread`**

Key edits (full-flow description, code for each change):

1. **Props:**

```tsx
import RefusalBanner from "./RefusalBanner.js";
import type { detectRefusal } from "./RefusalBanner.js";

interface Props {
  state: ChatState;
  mascot: MascotState;
  /** Latest-turn refusal info, computed by AiModePanel. Rendered in the
   *  thread FLOW (after the turns) so it appears via autoscroll when fresh
   *  and scrolls away with history — instead of permanently eating thread
   *  height as panel chrome, which is what it used to do. */
  refusal?: ReturnType<typeof detectRefusal>;
}
```

2. **Welcome inside the scroller** — delete the early `return <WelcomeHero />` (lines 112-114) and render conditionally inside the anchor:

```tsx
  const isEmpty = state.turns.length === 0 && !state.isThinking;
  ...
  return (
    <div className="chat-thread">
      <div ref={containerRef} className="chat-thread-scroll">
        <div ref={anchorRef} className="chat-thread-anchor">
          {isEmpty ? (
            <WelcomeHero />
          ) : (
            <>
              <div className="chat-thread-column">
                {state.turns.map(...unchanged...)}
                {refusal && <RefusalBanner refusal={refusal} />}
              </div>
              <div ref={endRef} />
              <div className={`chat-mascot-slot is-${scene}`}>...unchanged...</div>
            </>
          )}
        </div>
      </div>
      {!atBottom && !isEmpty && (
        <button type="button" className="chat-jump" onClick={jumpToBottom}>
          Jump to latest ↓
        </button>
      )}
    </div>
  );
```

(The `avatarPose`/`scene`/`lastAssistantIndex` derivations move below the `isEmpty` early data; they are cheap, run unconditionally.)

3. **Stick model upgrade** — in the existing scroll-tracking effect: rename the constant and add the pill state + re-stick threshold:

```tsx
  const [atBottom, setAtBottom] = useState(true);
  const anchorRef = useRef<HTMLDivElement | null>(null);
  ...
    // 32px, not 5px: wheel physics rarely land a user EXACTLY on the bottom
    // edge, and a re-stick window that narrow made autoscroll feel broken —
    // you returned to the bottom and new messages still didn't follow.
    const BOTTOM_REENGAGE_PX = 32;
    function onScroll() {
      if (!el) return;
      const distanceFromBottom = el.scrollHeight - el.scrollTop - el.clientHeight;
      const near = distanceFromBottom <= BOTTOM_REENGAGE_PX;
      if (near) stickToBottomRef.current = true;
      // Guarded setState so a wheel burst doesn't re-render per frame.
      setAtBottom((prev) => (prev === near ? prev : near));
    }
```

4. **Pin with scrollTop, not smooth scrollIntoView** — replace the auto-scroll effect:

```tsx
  // Pin = set scrollTop past the end and let the browser clamp. The old
  // smooth scrollIntoView animated toward the bottom for hundreds of ms,
  // which fought the user's wheel and made the unstick handlers hair-trigger.
  const pin = () => {
    const el = containerRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  };
  useEffect(() => {
    if (stickToBottomRef.current) pin();
  }, [state.turns, state.isThinking]);

  // Local growth the data layer can't see (a tool row expanding at the
  // bottom) also re-pins — mirror of YouCoded's content ResizeObserver.
  useEffect(() => {
    const anchor = anchorRef.current;
    if (!anchor || typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(() => {
      if (stickToBottomRef.current) pin();
    });
    obs.observe(anchor);
    return () => obs.disconnect();
  }, []);

  // Sending a message re-arms following — the user asked a question, they
  // want to see the answer arrive.
  const lastTurn = state.turns[state.turns.length - 1];
  useEffect(() => {
    if (lastTurn?.kind === "user") {
      stickToBottomRef.current = true;
      setAtBottom(true);
      pin();
    }
  }, [lastTurn?.id]);

  const jumpToBottom = () => {
    stickToBottomRef.current = true;
    setAtBottom(true);
    pin();
  };
```

(Keep the existing wheel/touch/key unstick handlers exactly as they are — they are already the intent-driven model.)

5. **AiModePanel** — remove its `{refusal && <RefusalBanner refusal={refusal} />}` line and the `RefusalBanner` import (keep `detectRefusal`), pass `refusal={refusal}` to `<ChatThread>`.

- [ ] **Step 5: CSS**

```css
/* Scroller pads for the floating chrome so the newest message clears it.
   120px fallback ≈ tier row + input + footer before first measurement. */
.chat-thread-scroll { height: 100%; overflow-y: auto; overflow-x: hidden; padding: 24px 16px calc(var(--ai-bottom-chrome, 120px) + 12px); }

/* Welcome now lives INSIDE the scroller (no second scroll context, no
   overflow). margin:auto centers it vertically in the anchor's flex column. */
.chat-welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; padding: 32px 24px; gap: 8px; margin: auto; }

/* In-flow refusal: shares the column measure; the auto margins go — the
   column already centers it. */
.chat-refusal{max-width:none;margin:8px 0 0;}

/* Jump-to-bottom pill, floating just above the chrome, app pill recipe. */
.chat-jump{position:absolute;bottom:calc(var(--ai-bottom-chrome,120px) + 14px);left:50%;transform:translateX(-50%);z-index:16;background:var(--card);border:1px solid var(--line);border-radius:var(--r-pill);box-shadow:var(--shadow);padding:6px 14px;font-family:inherit;font-size:12px;font-weight:800;color:var(--ink-2);cursor:pointer;transition:border-color .15s,color .15s;}
.chat-jump:hover{border-color:var(--az-gold);color:var(--az-gold-d);}
```

Also make `.chat-thread` the pill's positioning context (it is the scroller's parent, so the pill floats over the scroller's bottom edge): `.chat-thread { flex: 1 1 auto; min-height: 0; position: relative; }`.

- [ ] **Step 6: Run new tests + welcome-hero/refusal-banner/Ai suites + full run + typecheck.** `welcome-hero.test.tsx` renders `WelcomeHero` directly and is unaffected; `Ai.test.tsx` specs that queried the refusal banner still find it (it renders inside the thread now — update any assertion that walked from `.ai-panel` chrome to it).

- [ ] **Step 7: Visual check** (build + run as in Task 7): one scrollbar total; composer floats; welcome centered; long thread → pill appears on scroll-up.

- [ ] **Step 8: Commit**

```bash
git add src/chat/ src/styles/app.css
git commit -m "feat(webapp): one scroller — welcome in-flow, refusal in-thread, stick model + jump pill"
```

---

## Stage 3 — Tool rows

### Task 10: ToolCard becomes a compact row

**Files:**
- Modify: `webapp/src/chat/ToolCard.tsx`
- Modify: `webapp/src/styles/app.css:983-996`
- Test: `webapp/src/chat/__tests__/tool-card.test.tsx` (update)

**Interfaces:**
- Produces: `ToolCard` props gain `inGroup?: boolean` (adds class `is-inset`; Task 11 consumes it). Status color moves from inline style to CSS classes — the `STATUS_GLYPH_COLOR` map is deleted. The `+`/`−` toggle becomes a chevron `<svg className="chat-tool-chevron">`.

- [ ] **Step 1: Update the specs first**

In `tool-card.test.tsx`: delete assertions on the literal `+`/`−` text; keep/extend: `aria-expanded` toggling, label text, summary text, `aria-label` on the glyph, failed state. Add:

```tsx
it("renders as a compact row: chevron toggle, neutral glyph, danger only on failure", () => {
  const { container, rerender } = render(<ToolCard tool={completeTool} />);
  expect(container.querySelector(".chat-tool-chevron")).not.toBeNull();
  expect(container.querySelector(".chat-tool")!.className).not.toContain("is-failed");
  rerender(<ToolCard tool={failedTool} />);
  expect(container.querySelector(".chat-tool")!.className).toContain("is-failed");
});

it("inGroup renders the inset variant", () => {
  const { container } = render(<ToolCard tool={completeTool} inGroup />);
  expect(container.querySelector(".chat-tool")!.className).toContain("is-inset");
});
```

- [ ] **Step 2: Run — new specs fail, old `+`/`−` specs already deleted.**

- [ ] **Step 3: Implement `ToolCard.tsx`**

```tsx
interface Props {
  tool: ToolBlock;
  /** Rendered inside a ToolGroup — takes the recessed tint so the group
   *  header and its children read as one surface with a lifted inner step. */
  inGroup?: boolean;
}

export default function ToolCard({ tool, inGroup = false }: Props) {
  const [open, setOpen] = useState(false);
  const label = toolDisplayLabel(tool.toolName);
  const summary = toolHeaderSummary(tool.toolName, tool.input);
  const isFailed = tool.status === "failed";

  return (
    <div
      className={`chat-tool${isFailed ? " is-failed" : ""}${inGroup ? " is-inset" : ""}`}
    >
      <button
        type="button"
        className="chat-tool-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        {/* Status is carried by the glyph's SHAPE plus the pulse — color goes
            neutral so a run of successful tools reads quiet. Only failure
            keeps a color, because failure is the state worth shouting about
            (Core Invariant 3). Tinting moved from inline style to CSS. */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          className={
            "chat-tool-glyph" + (tool.status === "running" ? " chat-pulse" : "")
          }
          role="img"
          aria-label={STATUS_LABEL[tool.status]}
        >
          {toolGlyph(tool.toolName)}
        </svg>
        <span className="chat-tool-label">{label}</span>
        {summary && <span className="chat-tool-summary">{summary}</span>}
        <svg
          viewBox="0 0 10 6"
          width={10}
          height={6}
          className={`chat-tool-chevron${open ? " is-open" : ""}`}
          aria-hidden="true"
        >
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />
        </svg>
      </button>
      {open && <ToolBody tool={tool} />}
    </div>
  );
}
```

(Delete `STATUS_GLYPH_COLOR`; keep `STATUS_LABEL`.)

- [ ] **Step 4: CSS — replace the tool-card block (~983-993)**

```css
/* ----- tool rows -------------------------------------------------------------
   ~30px single-line rows, not cards: 12.5px type (below the 14px prose so the
   row reads as an annotation, not a competing message), neutral glyph, friendly
   label + truncated detail, chevron. The row shares the prose measure — a
   supporting artifact must never be wider than the answer it supports. */
.chat-tool { border-radius: var(--r-sm); border: 1px solid var(--line); background: var(--card); max-width: 65ch; overflow: hidden; }
/* Stacked rows sit 4px apart (was margin 8px against a 4px turn gap — three
   competing rhythms). The turn's own gap handles distance from prose. */
.chat-tool + .chat-tool { margin-top: 4px; }
.chat-tool.is-failed { border-color: var(--chat-danger); }
.chat-tool.is-inset { background: var(--canvas); }
.chat-tool-head { width: 100%; display: flex; align-items: center; gap: 8px; padding: 6px 12px; font-size: 12.5px; color: var(--ink-2); background: none; border: none; cursor: pointer; text-align: left; transition: background .15s; }
.chat-tool-head:hover { background: var(--navy-100); }
.chat-tool-glyph { flex-shrink: 0; color: var(--ink-3); }
.chat-tool.is-failed .chat-tool-glyph, .chat-tool.is-failed .chat-tool-label { color: var(--chat-danger); }
.chat-tool-label { font-weight: 700; color: var(--ink-2); flex-shrink: 0; }
/* The ↳ marks the detail as subordinate to the label — YouCoded's idiom,
   rendered in CSS so no component carries punctuation. */
.chat-tool-summary { color: var(--ink-3); font-size: 12px; min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.chat-tool-summary::before { content: "↳ "; }
.chat-tool-chevron { margin-left: auto; flex-shrink: 0; color: var(--ink-3); transition: transform .15s; }
.chat-tool-chevron.is-open { transform: rotate(180deg); }
.chat-tool-body { border-top: 1px solid var(--line); padding: 8px 12px; }
```

(The old `margin: 8px 0` and `border-left: 2px` rules are gone — failed rows now color the whole 1px border + glyph + label.)

- [ ] **Step 5: Run tool-card suite + full suite + typecheck.** `assistant-turn-bubble.test.tsx` may assert `.chat-tool` presence — still present.

- [ ] **Step 6: Commit**

```bash
git add src/chat/ToolCard.tsx src/styles/app.css src/chat/__tests__/tool-card.test.tsx
git commit -m "feat(webapp): tool cards become compact rows — glyph-shape status, chevron, prose-width cap"
```

---

### Task 11: ToolGroup — consecutive tools coalesce into one row

**Files:**
- Create: `webapp/src/chat/ToolGroup.tsx`
- Modify: `webapp/src/chat/AssistantTurnBubble.tsx` (segment the block list)
- Modify: `webapp/src/styles/app.css` (group rules, after the tool-row block)
- Test: `webapp/src/chat/__tests__/tool-group.test.tsx` (create); `assistant-turn-bubble.test.tsx` (extend)

**Interfaces:**
- Consumes: `ToolCard` with `inGroup` (Task 10); `toolDisplayLabel` from `tool-display.ts`.
- Produces: `ToolGroup({ tools: ToolBlock[] })` — default export. `AssistantTurnBubble` renders a `ToolGroup` for runs of ≥2 consecutive non-cite tool blocks, a bare `ToolCard` for singletons.

- [ ] **Step 1: Write the failing tests**

`webapp/src/chat/__tests__/tool-group.test.tsx` (fixtures: build ToolBlocks the way `tool-card.test.tsx` does):

```tsx
it("coalesces names and states into one summary row", () => {
  render(
    <ToolGroup
      tools={[retrieveComplete, retrieveComplete2, listFiltersComplete]}
    />,
  );
  const head = screen.getByRole("button", { name: /3 tool calls/ });
  expect(head).toHaveTextContent("Search corpus ×2, Browse filters");
  expect(head).toHaveTextContent("all complete");
});

it("reports running and failed counts while in flight", () => {
  render(<ToolGroup tools={[retrieveRunning, retrieveFailed]} />);
  const head = screen.getByRole("button", { name: /2 tool calls/ });
  expect(head).toHaveTextContent("1 failed");
});

it("expands to inset child rows", async () => {
  const { container } = render(
    <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
  );
  await userEvent.click(screen.getByRole("button", { name: /2 tool calls/ }));
  expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(2);
});
```

`assistant-turn-bubble.test.tsx` — add:

```tsx
it("groups consecutive tool calls but leaves a lone one bare", () => {
  // blocks: text, tool, tool, text, tool  ->  one group of 2, one bare card
  const turn = turnWith([textBlock1, toolA, toolB, textBlock2, toolC]);
  const { container } = render(<AssistantTurnBubble turn={turn} />);
  expect(container.querySelectorAll(".chat-tool-group")).toHaveLength(1);
  expect(
    container.querySelectorAll(":not(.chat-tool-group) > .chat-tool:not(.is-inset)"),
  ).toHaveLength(1);
});
```

- [ ] **Step 2: Run to verify failures.**

- [ ] **Step 3: Implement `ToolGroup.tsx`**

```tsx
// One row summarizing a RUN of consecutive tool calls — "3 tool calls
// (Search corpus ×2, Browse filters) — all complete". YouCoded's grouping
// pattern in this app's grammar: an expanded turn full of retrieve rows used
// to out-shout the answer; collapsed to one line, the prose stays the star.
// Expanding lifts the children one surface step (is-inset) so header+body
// read as one card.

import { useState } from "react";

import { toolDisplayLabel } from "./tool-display.js";
import type { AssistantBlock } from "./chat-types.js";
import ToolCard from "./ToolCard.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tools: ToolBlock[];
}

/** "Search corpus ×2, Browse filters" — adjacent same-label runs coalesce. */
export function coalesceLabels(tools: ToolBlock[]): string {
  const parts: { label: string; n: number }[] = [];
  for (const t of tools) {
    const label = toolDisplayLabel(t.toolName);
    const last = parts[parts.length - 1];
    if (last && last.label === label) last.n += 1;
    else parts.push({ label, n: 1 });
  }
  return parts
    .map((p) => (p.n > 1 ? `${p.label} ×${p.n}` : p.label))
    .join(", ");
}

export default function ToolGroup({ tools }: Props) {
  const [open, setOpen] = useState(false);
  const running = tools.filter((t) => t.status === "running").length;
  const failed = tools.filter((t) => t.status === "failed").length;
  // Failure outranks progress outranks done — the suffix is the one glanceable
  // health signal for the whole run.
  const suffix =
    failed > 0
      ? `${failed} failed`
      : running > 0
        ? `${running} running`
        : "all complete";

  return (
    <div className={`chat-tool-group${failed > 0 ? " is-failed" : ""}`}>
      <button
        type="button"
        className="chat-tool-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={`${tools.length} tool calls, ${suffix}`}
      >
        <span className="chat-tool-label">{tools.length} tool calls</span>
        <span className="chat-tool-summary">
          {coalesceLabels(tools)} — {suffix}
        </span>
        <svg
          viewBox="0 0 10 6"
          width={10}
          height={6}
          className={`chat-tool-chevron${open ? " is-open" : ""}`}
          aria-hidden="true"
        >
          <path d="M1 1l4 4 4-4" stroke="currentColor" strokeWidth="1.6" fill="none" strokeLinecap="round" />
        </svg>
      </button>
      {open && (
        <div className="chat-tool-group-body">
          {tools.map((t) => (
            <ToolCard key={t.toolUseId} tool={t} inGroup />
          ))}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Segment `AssistantTurnBubble`'s render**

Replace the `turn.blocks.map(...)` body with a two-pass segment build:

```tsx
  // Partition the block stream into text blocks and RUNS of consecutive
  // tool calls, so 2+ adjacent tools collapse into one ToolGroup row.
  // Cite tools stay invisible (the chips are their surface — see the
  // suppression ruling above), and they do NOT break a run: retrieve,
  // cite, retrieve is still one group of two retrieves.
  type Segment =
    | { kind: "text"; block: Extract<AssistantBlock, { kind: "text" }> }
    | { kind: "tools"; blocks: Extract<AssistantBlock, { kind: "tool" }>[] };
  const segments: Segment[] = [];
  for (const block of turn.blocks) {
    if (block.kind === "text") {
      segments.push({ kind: "text", block });
    } else if (!isCiteToolBlock(block)) {
      const last = segments[segments.length - 1];
      if (last?.kind === "tools") last.blocks.push(block);
      else segments.push({ kind: "tools", blocks: [block] });
    }
  }

  return (
    <div className="chat-turn">
      {segments.map((seg) => {
        if (seg.kind === "text") {
          const block = seg.block;
          ...existing text-block render, unchanged...
        }
        if (seg.blocks.length === 1) {
          const tool = seg.blocks[0]!;
          return <ToolCard key={tool.toolUseId} tool={tool} />;
        }
        return <ToolGroup key={seg.blocks[0]!.toolUseId} tools={seg.blocks} />;
      })}
      ...stop-reason notices unchanged...
    </div>
  );
```

- [ ] **Step 5: CSS**

```css
/* ----- tool group ------------------------------------------------------------
   Same row geometry as a single tool; the body has no background of its own so
   header+children read as one surface, children lifted by is-inset. */
.chat-tool-group { border-radius: var(--r-sm); border: 1px solid var(--line); background: var(--card); max-width: 65ch; overflow: hidden; }
.chat-tool-group.is-failed { border-color: var(--chat-danger); }
.chat-tool-group.is-failed .chat-tool-label { color: var(--chat-danger); }
.chat-tool-group-body { padding: 4px 8px 8px; display: flex; flex-direction: column; gap: 4px; }
.chat-tool-group-body .chat-tool + .chat-tool { margin-top: 0; }
```

- [ ] **Step 6: Run new + turn-bubble + full suite + typecheck. Commit.**

```bash
git add src/chat/ToolGroup.tsx src/chat/AssistantTurnBubble.tsx src/styles/app.css src/chat/__tests__/
git commit -m "feat(webapp): consecutive tool calls coalesce into one ToolGroup row"
```

---

### Task 12: Tool-body diet

**Files:**
- Modify: `webapp/src/styles/app.css` (tool-view primitive rules ~998-1042)
- Modify: `webapp/src/chat/tool-views/primitives.tsx` (`ErrorBlock` uses `CollapsibleBlock`)
- Test: `webapp/src/chat/__tests__/tool-body.test.tsx` (extend); `chat-css-contract.test.ts` (extend)

**Interfaces:**
- Produces: `CollapsibleBlock` gains `variant?: "danger"` (named modifier per the note in primitives.tsx — NOT a free-form className). `ErrorBlock` renders through it (long errors collapse instead of scrolling in a nested box).

- [ ] **Step 1: Contract + behavior tests**

`chat-css-contract.test.ts`:

```ts
  it("micro-labels use the app idiom, not the 10px devtools one", () => {
    for (const sel of [".chat-label", ".chat-more", ".chat-copy", ".chat-error-label"]) {
      const rule = ruleFor(sel);
      expect(rule, sel).toMatch(/font-size:\s*11px/);
      expect(rule, sel).toMatch(/letter-spacing:\s*\.08em/);
    }
  });

  it("the error body no longer scrolls inside the thread", () => {
    expect(ruleFor(".chat-error-body")).not.toMatch(/overflow|max-height/);
  });
```

`tool-body.test.tsx`:

```tsx
it("long errors collapse behind a Show-more instead of a nested scrollbar", () => {
  const longError = Array.from({ length: 40 }, (_, i) => `line ${i}`).join("\n");
  render(<ErrorBlock error={longError} />);
  expect(screen.getByRole("button", { name: /Show 20 more lines/ })).toBeInTheDocument();
});
```

- [ ] **Step 2: Run to verify failures.**

- [ ] **Step 3: Implement**

`primitives.tsx`:

```tsx
interface CollapsibleBlockProps {
  children: string;
  maxLines?: number;
  /** Named modifier, not a className hole (see the port note above). "danger"
   *  renders the error tint. */
  variant?: "danger";
}

export function CollapsibleBlock({ children, maxLines = 20, variant }: CollapsibleBlockProps) {
  ...
  return (
    <div className={`chat-block${variant === "danger" ? " is-danger" : ""}`}>
    ...
}

export function ErrorBlock({ error }: { error: string }) {
  return (
    <div>
      <div className="chat-error-label">Error</div>
      {/* Collapse, don't scroll: a 192px inner scrollbar inside the thread
          scroller was one of the "scrollbars everywhere" offenders. */}
      <CollapsibleBlock maxLines={20} variant="danger">
        {error}
      </CollapsibleBlock>
    </div>
  );
}
```

CSS — replace the primitive rules:

```css
/* Micro-labels move to the app's canonical idiom (11px/800/upper/.08em —
   the fiscal-notes rail label, app.css:550). The 10px/.06em devtools look
   was the retired app's, not this one's. */
.chat-label { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); margin-bottom: 4px; }
.chat-more { margin-top: 4px; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); background: none; border: none; padding: 0; cursor: pointer; transition: color .15s; }
.chat-more:hover { color: var(--az-gold-d); }
.chat-copy { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); background: none; border: none; padding: 0 4px; cursor: pointer; transition: color .15s; }
.chat-copy:hover { color: var(--az-gold-d); }
.chat-error-label { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; color: var(--chat-danger); margin-bottom: 4px; }
/* Error text renders inside a danger-tinted CollapsibleBlock now. */
.chat-block.is-danger pre { color: var(--chat-danger); background: var(--chat-danger-tint); border-color: var(--chat-danger); }
.chat-error-body { font-size: 12px; color: var(--chat-danger); background: var(--chat-danger-tint); border-radius: var(--r-sm); padding: 8px; white-space: pre-wrap; margin: 0; font-family: var(--chat-mono); }

/* Chunk rows: hairline-separated list on the recessed body, not
   triple-nested bordered boxes. Matches the app's .ctx tray idiom. */
.chat-chunks { display: flex; flex-direction: column; gap: 0; list-style: none; margin: 0; padding: 0; }
.chat-chunk { border: 0; border-bottom: 1px dashed #e3e7f1; background: none; border-radius: 0; padding: 8px 2px; font-size: 12px; }
.chat-chunk:last-of-type { border-bottom: 0; }

.chat-table-wrap { border-radius: var(--r-sm); border: 1px solid var(--line); background: var(--canvas); overflow: hidden; }
.chat-table th { font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); border-bottom: 1px solid var(--line); padding: 4px 8px; text-align: left; }
.chat-table-more { display: block; width: 100%; font-size: 11px; font-weight: 800; text-transform: uppercase; letter-spacing: .08em; color: var(--ink-3); padding: 4px; border: none; border-top: 1px solid var(--line); background: none; cursor: pointer; }

/* Chips keep their outcome hues; radius joins the token scale. */
.chat-chip { padding: 1px 7px; font-size: 11px; text-transform: uppercase; letter-spacing: .08em; border-radius: var(--r-pill); border: 1px solid var(--line); background: var(--canvas); color: var(--ink-3); font-weight: 800; white-space: nowrap; }
.chat-block pre { font-size: 12px; color: var(--ink-2); background: var(--canvas); border: 1px solid var(--line); border-radius: var(--r-sm); padding: 8px; white-space: pre-wrap; font-family: var(--chat-mono); margin: 0; }
.chat-code { color: var(--ink-2); background: var(--navy-100); padding: 2px 6px; border-radius: var(--r-pill); font-family: var(--chat-mono); word-break: break-all; }
```

(Leave `.chat-chip.is-add/is-remove/is-warn/is-info` hue rules as-is.)

- [ ] **Step 4: Run tool-body + retrieve-view-dependent suites + full run + typecheck. Commit.**

```bash
git add src/chat/tool-views/primitives.tsx src/styles/app.css src/chat/__tests__/
git commit -m "feat(webapp): tool bodies — hairline chunk rows, app micro-labels, collapse-not-scroll errors"
```

---

## Stage 4 — Messages, rhythm, texture

### Task 13: Bubbles + spacing scale + radii sweep + hover language

**Files:**
- Modify: `webapp/src/styles/app.css` (bubble/turn/composer/notice/suggestion/cite/tooltip rules)
- Test: `chat-css-contract.test.ts` (extend)

**Interfaces:** none — pure CSS. Component markup unchanged (`.has-tail` class keeps its name; only its rendering changes from triangle carats to a squared corner).

- [ ] **Step 1: Contract test**

```ts
  it("no off-scale radii survive in the chat block (16/12/pill + 4px tail/chips only)", () => {
    const chatStart = css.indexOf("/* ===== chat =====");
    const pdfStart = css.indexOf("/* ===== page-upload");
    const block = css.slice(chatStart, pdfStart);
    // 6px, 8px and 10px radii were the retired app's scale.
    expect(block).not.toMatch(/border-radius:\s*(6|8|10)px/);
  });

  it("turn rhythm is on one scale: 24 between turns, 8 within", () => {
    expect(ruleFor(".chat-thread-column")).toMatch(/gap:\s*24px/);
    expect(ruleFor(".chat-turn")).toMatch(/gap:\s*8px/);
  });
```

- [ ] **Step 2: Run — fails.**

- [ ] **Step 3: The CSS sweep** (each line replaces its counterpart; WHY comments included where the value is a decision):

```css
/* Depth comes from the surface ramp (canvas page, card bubbles) — the thread
   floor goes canvas so white bubbles lift off it without shadows. */
.chat-thread-scroll { /* add: */ background: var(--canvas); }

/* One rhythm: 24px between turns, 8px inside a turn, 4px between stacked tool
   rows (Task 10). Replaces the 20/4/8 three-source mishmash. */
.chat-thread-column { max-width: var(--ai-col); margin: 0 auto; width: 100%; display: flex; flex-direction: column; gap: 24px; }
.chat-turn { display: flex; flex-direction: column; gap: 8px; }

/* Assistant bubble: 16px radius with a 4px "tail" corner on the newest turn —
   the token-scale version of the speech-bubble idiom. The triangle carats are
   deleted: they hung 9px outside the bubble, which is what forced the mascot
   translate() dance and read as clip-art next to the mockup's card grammar. */
.chat-bubble { position: relative; background: var(--card); border: 1px solid var(--line); border-radius: var(--r-md); padding: 10px 16px; color: var(--ink); font-size: 14px; max-width: 65ch; }
.chat-bubble.has-tail { border-bottom-left-radius: 4px; }
/* (delete the .chat-bubble.has-tail::before and ::after triangle rules) */

/* User bubble: solid navy — the app's "active" fill (.chseg.on, .fbill-no) —
   mirrored 4px tail. az-gold was the retired app's accent-as-user-color. */
.chat-user-bubble { background: var(--navy); color: #fff; border-radius: var(--r-md); border-bottom-right-radius: 4px; padding: 10px 16px; max-width: 78%; font-size: 14px; line-height: 1.6; white-space: pre-wrap; }

/* Radii joining the token scale. */
.chat-notice { border-radius: var(--r-sm); border: 1px solid; padding: 8px 12px; font-size: 12px; line-height: 1.5; }
.chat-input { max-width: var(--ai-col); margin: 0 auto; background: var(--card); border: 1.5px solid var(--line); border-radius: var(--r-sm); display: flex; gap: 8px; align-items: flex-end; padding: 6px 8px; }
.chat-cite-tooltip { /* border-radius: 10px -> */ border-radius: var(--r-sm); }
.chat-md pre { /* border-radius: 10px -> */ border-radius: var(--r-sm); }
.chat-md-copy { /* border-radius: 6px -> */ border-radius: var(--r-pill); }
.pdf-zoom-btn { /* 6px -> */ border-radius: var(--r-sm); }
.pdf-open-original { /* 6px -> */ border-radius: var(--r-sm); }
.pdf-skeleton { /* 6px -> */ border-radius: var(--r-sm); }
.chat-cite-copy { /* 6px -> */ border-radius: var(--r-pill); }
.chat-refusal-chunk { /* 6px -> */ border-radius: var(--r-sm); }

/* Send: the app's primary-CTA recipe — pill, brightness hover (app.css:170). */
.chat-send { background: var(--az-gold); color: #fff; border: none; border-radius: var(--r-pill); padding: 7px 16px; font-family: var(--font); font-size: 12.5px; font-weight: 800; cursor: pointer; transition: filter .15s, opacity .15s; }
.chat-send:hover:not(:disabled) { filter: brightness(1.05); }

/* Hover language: azure border + -d text, like every pill on the pages. */
.chat-suggestion:hover { border-color: var(--az-gold); color: var(--az-gold-d); }
.chat-cite-inline:hover { opacity: 1; background: var(--az-gold-100); }
.chat-cite-pill:hover { opacity: 1; border-color: var(--az-gold); }
.chat-download { /* border-radius: 8px -> */ border-radius: var(--r-pill); }
```

Notes: `.chat-cite-sup`/`.chat-cite-pill` keep 4px (allowed); `.pdf-highlight`/`.pdf-cited-mark` keep 2px (page artifact, not UI chrome — exempt, document with a comment); `.chat-user-bubble.is-pending { opacity:.7 }` unchanged.

- [ ] **Step 4: Run contract + full suite.** Fix any spec pinning the old `az-gold` user-bubble background or triangle-tail pseudo-elements (jsdom can't see pseudos — none should exist).

- [ ] **Step 5: Visual check** (build + serve): bubbles on canvas, navy user bubble, one rhythm. **Commit.**

```bash
git add src/styles/app.css src/chat/__tests__/chat-css-contract.test.ts
git commit -m "feat(webapp): bubbles + rhythm on the token scale — navy user bubble, 4px tail, azure hovers"
```

---

### Task 14: Own the syntax-highlight palette

**Files:**
- Modify: `webapp/src/chat/MarkdownContent.tsx:20` (remove the import)
- Modify: `webapp/src/styles/app.css` (new `.chat-md .hljs-*` rules)
- Test: `chat-css-contract.test.ts` (extend)

**Interfaces:** none. highlight.js still emits `hljs-*` classes; only the theme source changes.

- [ ] **Step 1: Test**

```ts
  it("no third-party syntax theme — hljs classes are styled locally in navy", () => {
    expect(css).toMatch(/\.chat-md \.hljs-keyword/);
  });
```

Plus assert the import is gone:

```bash
grep -c "highlight.js/styles" src/chat/MarkdownContent.tsx   # expect 0 after
```

- [ ] **Step 2: Implement** — delete `import "highlight.js/styles/github.css";` from `MarkdownContent.tsx` and add to the markdown CSS section:

```css
/* Syntax highlighting in the house palette — replaces the GitHub theme
   import, which was a fifth color source on this page. Code is rare in
   budget answers; this covers the common token classes and lets the rest
   inherit the pre block's ink. */
.chat-md .hljs-keyword, .chat-md .hljs-selector-tag, .chat-md .hljs-built_in { color: var(--navy); font-weight: 700; }
.chat-md .hljs-string, .chat-md .hljs-attr { color: var(--teal); }
.chat-md .hljs-number, .chat-md .hljs-literal { color: var(--copper); }
.chat-md .hljs-comment { color: var(--ink-3); font-style: italic; }
.chat-md .hljs-title, .chat-md .hljs-function { color: var(--az-gold-d); }
```

- [ ] **Step 3: Run suite + typecheck + commit.**

```bash
git add src/chat/MarkdownContent.tsx src/styles/app.css src/chat/__tests__/chat-css-contract.test.ts
git commit -m "feat(webapp): navy-native code highlighting replaces the GitHub hljs theme"
```

---

## Stage 5 — Source panel

### Task 15: Chat-first split, merged header, cited-text cap, sub-860 drawer

**Files:**
- Modify: `webapp/src/pdf/SourceView.tsx` (merge Breadcrumb+Toolbar into one header; `onClose?` prop)
- Modify: `webapp/src/pdf/PdfViewer.tsx` (thread `onClose` through; clamp empty mascot; plain-language unresolved copy)
- Modify: `webapp/src/chat/AiModePanel.tsx` (pass `onClose` to PdfViewer; drop the Task 5 overlay button)
- Modify: `webapp/src/styles/app.css` (split sizing, `.pdf-head`, cited-text cap, drawer media query)
- Test: `webapp/src/pdf/__tests__/pdf-viewer.test.tsx`, `source-panel.test.tsx`, `chat-css-contract.test.ts` (extend)

**Interfaces:**
- Produces: `SourceViewProps` gains `onClose?: () => void` — when present, the merged header renders the close button (reusing class `ai-source-close` minus the absolute positioning). `PdfViewer` gains the same optional prop and forwards it. `SourcePanel` (search drawer) passes nothing — it has its own close.

- [ ] **Step 1: Tests**

`chat-css-contract.test.ts`:

```ts
  it("split is chat-first, and small screens get a drawer instead of nothing", () => {
    expect(css).toMatch(/\.ai-panel-main\.has-source \.ai-panel-chat\s*\{[^}]*flex:\s*0 0 clamp\(/);
    // The old behavior hid the source entirely below 860px.
    const media = css.slice(css.indexOf("@media (max-width:860px)"));
    expect(media.slice(0, media.indexOf("}") + 200)).not.toMatch(/\.ai-panel-source\s*\{\s*display:\s*none/);
  });

  it("cited text is capped in px, not vh", () => {
    expect(ruleFor(".pdf-cited-text")).not.toMatch(/vh/);
  });
```

`pdf-viewer.test.tsx` — the unresolved-state copy rewrite:

```tsx
it("unresolved state leads with plain language, ids demoted", () => {
  render(
    <CitationBusProvider>
      <UnresolvedDriver citation={unresolvedCitation} />
    </CitationBusProvider>,
  );
  expect(screen.getByText(/couldn.t find the source page/i)).toBeInTheDocument();
  // The chunk id is still there for audit, but as a detail line.
  expect(screen.getByText(unresolvedCitation.chunkId, { exact: false })).toBeInTheDocument();
});
```

- [ ] **Step 2: Implement `SourceView` header merge**

Replace `<Breadcrumb …/>` + `<Toolbar …/>` with one row (delete both sub-components, create `SourceHead`):

```tsx
function SourceHead({
  docTitle, page, fiscalYear, zoom, onZoomIn, onZoomOut, onResetZoom, docId, onClose, showZoom,
}: { ... }) {
  const fullDocHref = `/api/pdf/${encodeURIComponent(docId)}#page=${page ?? 1}`;
  return (
    <div className="pdf-head">
      {page != null && (
        <>
          <span className="pdf-crumb-label">Page</span>
          <span className="pdf-crumb-page">{page}</span>
          <span className="pdf-crumb-label">of</span>
        </>
      )}
      <span className="pdf-crumb-doc" title={docTitle}>{docTitle}</span>
      {fiscalYear != null && <span className="pdf-crumb-fy">FY{fiscalYear}</span>}
      <span className="pdf-head-spacer" />
      {showZoom && (
        <>
          <button type="button" onClick={onZoomOut} aria-label="Zoom out" className="pdf-zoom-btn" disabled={zoom <= MIN_ZOOM + 0.001}>−</button>
          <button type="button" onClick={onResetZoom} aria-label="Reset zoom to fit width" className="pdf-zoom-btn pdf-zoom-level" title="Click to reset to fit-to-width">{`${Math.round(zoom * 100)}%`}</button>
          <button type="button" onClick={onZoomIn} aria-label="Zoom in" className="pdf-zoom-btn" disabled={zoom >= MAX_ZOOM - 0.001}>+</button>
          <a href={fullDocHref} target="_blank" rel="noopener noreferrer" className="pdf-open-original" title="Open the full PDF in a new browser tab">Open ↗</a>
        </>
      )}
      {onClose && (
        <button type="button" className="ai-source-close is-inline" aria-label="Close source panel" onClick={onClose}>
          <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true"><path d="M3 3l10 10M13 3L3 13" stroke="currentColor" strokeWidth="2" strokeLinecap="round" fill="none" /></svg>
        </button>
      )}
    </div>
  );
}
```

Render it once at the top of `.pdf-view` (both branches — with and without a page), `showZoom={!noPageReason}`. `PdfViewer.Loaded` forwards `onClose`; `AiModePanel` passes `onClose={() => setViewerOpen(false)}` to `<PdfViewer onClose=…/>` and deletes the Task 5 overlay button from the aside (keep the aside `position:relative` — harmless). `EmptyState`/`UnresolvedState` keep a floating `ai-source-close` (absolute variant) when `onClose` given, so the panel is always closable.

- [ ] **Step 3: Unresolved copy rewrite** (in `PdfViewer.tsx`):

```tsx
function UnresolvedState({ citation, onClose }: { citation: Citation; onClose?: () => void }) {
  return (
    <div className="pdf-empty">
      {onClose && <button type="button" className="ai-source-close" aria-label="Close source panel" onClick={onClose}>…same svg…</button>}
      <div className="pdf-unresolved">
        <h2>Couldn&rsquo;t find the source page</h2>
        <p>
          This citation points at a passage the current view can&rsquo;t locate —
          usually because it comes from an earlier question, or because the
          source is a Word document rather than a PDF.
        </p>
        {citation.claimSpan && (
          <blockquote className="pdf-unresolved-quote">{citation.claimSpan}</blockquote>
        )}
        <p className="pdf-unresolved-note">
          Ask the question again to refresh the sources. Reference:{" "}
          chip <span className="pdf-mono">[{citation.index}]</span>, passage{" "}
          <span className="pdf-mono">{citation.chunkId}</span>.
        </p>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: CSS**

```css
/* Chat keeps a comfortable reading width; the panel takes the remainder —
   the hard 50/50 halved the chat below its own 65ch measure at 1440px. */
.ai-panel-main.has-source .ai-panel-chat{flex:0 0 clamp(480px, 46%, 760px);}
.ai-panel-source{flex:1 1 0;min-width:0;min-height:0;display:flex;flex-direction:column;position:relative;}

/* One header row: crumb + zoom + open + close. Removes the second stacked
   white band the old crumb/toolbar pair painted before any page pixels. */
.pdf-head { display: flex; align-items: center; gap: 6px; padding: 8px 12px; border-bottom: 1px solid var(--line); background: var(--card); font-size: 12px; }
.pdf-head-spacer { margin-left: auto; }
.ai-source-close.is-inline { position: static; width: 24px; height: 24px; }
/* (delete the old .pdf-crumb and .pdf-toolbar rules; keep .pdf-crumb-label/
   -page/-doc/-fy, which the merged header reuses, and drop .pdf-crumb-fy's
   margin-left:auto — the spacer owns that job now.) */
.pdf-crumb-fy { color: var(--ink-3); flex: 0 0 auto; }

/* px cap, not vh: 34vh was measured against the WINDOW inside a panel that
   isn't window-tall, so the cited text could eat a third of the screen. */
.pdf-cited-text { margin: 0; color: var(--ink); white-space: pre-wrap; max-height: 220px; overflow: auto; }

/* The empty-state mascot clamps to its container (the 240x420 hero used to
   overflow a half-width panel and get clipped by overflow:hidden). */
.pdf-empty { height: 100%; display: flex; align-items: center; justify-content: center; padding: 32px 24px; background: var(--canvas); color: var(--ink-3); font-size: 13px; position: relative; }
.pdf-empty-inner svg { max-height: min(300px, 50%); width: auto; }

/* Below 860px the source becomes an overlay drawer (the search page's
   recipe) instead of display:none — "the panel vanished" was a defect.
   DELETE the existing `@media (max-width:860px){ .ai-panel-source{display:none;} }`
   block (~app.css:1474-1476) and replace it with this one. */
@media (max-width:860px){
  .ai-panel-main.has-source .ai-panel-chat{flex:1 1 0;}
  .ai-panel-source{position:fixed;top:0;right:0;bottom:0;z-index:60;width:min(560px,100vw);background:var(--canvas);border-left:1px solid var(--line);box-shadow:var(--shadow);}
}
```

- [ ] **Step 5: Run pdf suites + search-source-panel (drawer must be unaffected: it renders SourceView with no `onClose` and keeps its navy `.pdf-drawer-head`) + full suite + typecheck.**

- [ ] **Step 6: Visual check:** chip click → panel opens with content on FIRST click; close works; window at 800px → drawer overlays; zoom 100% fills width. **Commit.**

```bash
git add src/pdf/ src/chat/AiModePanel.tsx src/styles/app.css
git commit -m "feat(webapp): chat-first source split — merged header, first-class close, sub-860 drawer"
```

---

## Stage 6 — Mascot + final polish

### Task 16: Mascot docking + welcome clamp + honesty-line polish

**Files:**
- Modify: `webapp/src/styles/app.css` (mascot slot rules ~823-826, welcome mascot ~891)
- Test: `chat-css-contract.test.ts` (extend)

**Interfaces:** none — CSS only. Component markup for the mascot is untouched (all poses stay).

- [ ] **Step 1: Contract test**

```ts
  it("the mascot hides via container query instead of clipping off-canvas", () => {
    expect(css).toMatch(/container-type:\s*inline-size/);
    expect(css).toMatch(/@container[^{]*max-width[^{]*\{[^}]*\.chat-mascot-slot[^}]*display:\s*none/s);
  });

  it("the welcome mascot clamp no longer hardcodes the chrome height", () => {
    expect(ruleFor(".chat-welcome-mascot")).not.toMatch(/440px/);
  });
```

- [ ] **Step 2: Implement**

```css
/* The scroller is the mascot's container: when the chat column is too narrow
   to fit the 768px column PLUS the mascot beside it (the source panel open,
   a narrow window), he fades out instead of being clipped mid-body by the
   column edge — which is what right:calc(50% + 400px) used to do.
   1040px = --ai-col + the widest scene (~184px) + gutters. */
.chat-thread-scroll { container-type: inline-size; }
@container (max-width: 1040px) {
  .chat-mascot-slot { display: none; }
}

/* Welcome mascot: sized against the welcome area itself (it now lives inside
   the scroller, whose padding already accounts for the real chrome heights)
   instead of the hand-measured 440px constant that broke whenever any chrome
   changed height. 40dvh keeps the greeting above the fold on a laptop. */
.chat-welcome-mascot { max-height: min(420px, 40dvh); width: auto; margin-bottom: 8px; }
```

(`container-type: inline-size` on the scroller applies inline-size containment — the scroller's width is parent-driven (flex), never content-driven, so this is safe. If any layout regression appears in the visual check, fall back to wrapping the mascot slot's container query on `.chat-thread-anchor` instead.)

- [ ] **Step 3: Run contract + full suite + typecheck.**

- [ ] **Step 4: Visual check:** panel closed wide window → mascot visible beside column; open panel at 1440px → mascot cleanly absent (not half-clipped); welcome mascot fits with greeting visible. **Commit.**

```bash
git add src/styles/app.css src/chat/__tests__/chat-css-contract.test.ts
git commit -m "feat(webapp): mascot docks by container width; welcome clamp drops the magic constant"
```

---

### Task 17: Full verification + human browser pass + merge

- [ ] **Step 1: Full local verification**

```bash
cd ~/ask-the-budget-az-worktrees/ai-mode-ui-redesign/webapp
npx tsc -b && npx vitest run 2>&1 | tail -5
npm run build
cd .. && bash setup.sh --verify > /tmp/verify.log 2>&1; echo $?
```

Expected: exit 0. (`setup.sh --verify` runs pytest too — nothing server-side changed, it must be green.)

- [ ] **Step 2: Human-at-a-browser checklist** (jsdom is structurally blind to these — this step needs eyes, run the server and walk it):

1. Tooltip: hover a chip on the FIRST visible line of a scrolled thread → tooltip fully visible (not decapitated). Hover a chip at the right column edge → no horizontal scrollbar appears.
2. First chip click → panel opens WITH the page rendered (no "Click a citation" flash).
3. Panel open at 1440px and 1920px → chat column keeps its width; close button returns full width; mascot never renders half-clipped.
4. Window at 800px → chip click opens the overlay drawer; close works.
5. Tool rows: run a real question (needs an OpenRouter key) or eyeball the vitest storyshots — consecutive retrieves collapse to one row; expanding is calm; failed tools are unmistakably red.
6. Exactly ONE scrollbar in the viewport with a long thread; composer floats; jump pill appears on scroll-up and works.
7. Welcome screen: mascot + greeting fit a 13" laptop without internal scroll.

Record findings in the PR/merge description; anything broken loops back to its task.

- [ ] **Step 3: Merge and push** (per CLAUDE.md, merge means merge AND push)

```bash
cd ~/YouCoded/Projects/ask-the-budget-az-dev
git fetch origin && git pull origin master
git merge --no-ff ai-mode-ui-redesign -m "Merge branch 'ai-mode-ui-redesign' — one column, floating chrome (spec 2026-08-01)"
git push origin master
git worktree remove ~/ask-the-budget-az-worktrees/ai-mode-ui-redesign
git branch -D ai-mode-ui-redesign
```

- [ ] **Step 4: Update STATUS.md** — add a short section under the Plan 4/5 entries: what shipped (spec link, merge sha), the human-checklist outcome, and any follow-ups discovered. Commit + push.
