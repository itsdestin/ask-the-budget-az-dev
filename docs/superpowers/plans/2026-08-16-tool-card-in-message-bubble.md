# Tool card in the message bubble — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move a run of tool calls out of the space above the answer and into
the top of the answer bubble as one self-contained collapsible card, and stop
the collapsed card from reporting tool failures.

**Architecture:** Purely a rendering change over unchanged chat state.
`AssistantTurnBubble` stops emitting tool rows as siblings and instead pairs
each run with the text block that follows it, rendering `ToolGroup` as the
bubble's first child. `ToolGroup` grows to handle runs of one, gains
tense-aware wording, and loses every failure signal from its collapsed row.
Wording moves to `tool-display.ts`; containment and the expansion cap are CSS.

**Tech Stack:** React 18 + TypeScript, Vite, vitest + @testing-library/react,
plain CSS in `webapp/src/styles/app.css`.

**Spec:** [`docs/superpowers/specs/2026-08-16-tool-card-in-message-bubble-design.md`](../specs/2026-08-16-tool-card-in-message-bubble-design.md)
(TC1–TC12). Approved rendering:
[`docs/superpowers/specs/assets/2026-08-16-tool-card-mockup/options.html`](../specs/assets/2026-08-16-tool-card-mockup/options.html)
— **option B**.

## Global Constraints

- **Webapp only.** Do not touch `retrieval/`, `ingest/`, `chunking/`,
  `citation/`, `harness/`, `app/`, or `store/`. No eval run is required and
  none should be performed.
- **No corpus name anywhere in the card** (TC3).
- **The collapsed card carries no failure signal** — no `is-failed` class on
  the group, no red, no word "failed", no failure count, in the visible text
  **or** the `aria-label` (TC9, TC12).
- **A settled multi-call card shows no detail line at all.** `all complete` is
  deleted, not kept — it would be a false positive claim while `1 failed` is
  suppressed (TC3).
- **Citation failure is untouched.** `cite` / `cite_batch` never render as tool
  rows; a failed citation stays a red-X chip (TC7, TC9).
- `tsc -b` rejects unused imports. Remove an import the moment its last use
  goes.
- All commands below run from the repo root unless the step says otherwise.
- Commit after every task.

---

## File structure

| File | Responsibility after this change |
|---|---|
| `webapp/src/chat/tool-display.ts` | **All wording.** Present-tense per-call labels (unchanged), plus new past/present *action* labels and the run coalescer. |
| `webapp/src/chat/ToolGroup.tsx` | The card: a run's shape, open/closed state, header composition, and which expansion body to render. Renders for n ≥ 1. |
| `webapp/src/chat/ToolCard.tsx` | One call. Unchanged — still the child-row renderer inside an expansion. |
| `webapp/src/chat/AssistantTurnBubble.tsx` | Pairing runs to the bubble that follows them; the standalone fallback. |
| `webapp/src/styles/app.css` | Nested-card containment, width, expansion cap; deletion of the group failure rules. |

Tasks 1–4 build the card in isolation; Task 5 moves it into the bubble; Task 6
is its containment; Task 7 is the gate. Each task's suite is green at its
commit.

---

### Task 1: Action labels and the run coalescer

Wording lives in `tool-display.ts`, so the card component never composes
English. `coalesceLabels` currently lives in `ToolGroup.tsx` and moves here.

**Files:**
- Modify: `webapp/src/chat/tool-display.ts` (append; do not alter the existing
  `toolDisplayLabel` / `toolHeaderSummary`)
- Test: `webapp/src/chat/__tests__/tool-display.test.ts` (append)

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `export type LabelTense = "past" | "present"`
  - `export function toolActionLabel(toolName: string, tense: LabelTense): string`
  - `export function coalesceActionLabels(tools: { toolName: string }[], tense: LabelTense): string`

- [ ] **Step 1: Write the failing tests**

Append to `webapp/src/chat/__tests__/tool-display.test.ts`. Add
`coalesceActionLabels` and `toolActionLabel` to the existing import at the top
of the file so it reads:

```ts
import {
  coalesceActionLabels,
  toolActionLabel,
  toolDisplayLabel,
  toolHeaderSummary,
} from "../tool-display.js";
```

Then append:

```ts
describe("toolActionLabel", () => {
  it("names what happened, in the tense the run is actually in", () => {
    expect(toolActionLabel("retrieve", "past")).toBe("Searched");
    expect(toolActionLabel("retrieve", "present")).toBe("Searching");
    expect(toolActionLabel("create_document", "past")).toBe("Wrote a document");
    expect(toolActionLabel("create_document", "present")).toBe(
      "Writing a document",
    );
    expect(toolActionLabel("list_filter_values", "past")).toBe(
      "Browsed filters",
    );
    expect(toolActionLabel("document_guide", "past")).toBe(
      "Checked the style guide",
    );
  });

  it("never leaks a raw snake_case tool name for a registered tool", () => {
    // Same guard as toolDisplayLabel's, for the same reason: `document_guide`
    // reached the UI unlabelled once. Asserting the whole registered set means
    // the next tool added to harness/tools.py fails HERE rather than in front
    // of an analyst.
    const registered = [
      "retrieve",
      "cite",
      "cite_batch",
      "list_filter_values",
      "create_document",
      "document_guide",
    ];
    for (const name of registered) {
      for (const tense of ["past", "present"] as const) {
        expect(toolActionLabel(name, tense)).not.toBe(name);
        expect(toolActionLabel(name, tense)).not.toContain("_");
      }
    }
  });

  it("falls back to the bare name for an unknown tool", () => {
    expect(toolActionLabel("some_future_tool", "past")).toBe("some_future_tool");
  });
});

describe("coalesceActionLabels", () => {
  const t = (toolName: string) => ({ toolName });

  it("collapses an adjacent same-label run into a count", () => {
    expect(
      coalesceActionLabels([t("retrieve"), t("retrieve")], "past"),
    ).toBe("Searched ×2");
  });

  it("keeps only the first phrase capitalised", () => {
    // "Searched ×3, wrote a document" reads as one sentence fragment.
    // "Searched ×3, Wrote a document" reads as two headings jammed together.
    expect(
      coalesceActionLabels(
        [t("retrieve"), t("retrieve"), t("retrieve"), t("create_document")],
        "past",
      ),
    ).toBe("Searched ×3, wrote a document");
  });

  it("does not merge non-adjacent same-label runs", () => {
    // Order is the model's actual sequence of work; collapsing across a gap
    // would claim it did three searches back to back when it did not.
    expect(
      coalesceActionLabels(
        [t("retrieve"), t("create_document"), t("retrieve")],
        "past",
      ),
    ).toBe("Searched, wrote a document, searched");
  });

  it("carries the tense through to every phrase", () => {
    expect(
      coalesceActionLabels([t("retrieve"), t("create_document")], "present"),
    ).toBe("Searching, writing a document");
  });

  it("returns an empty string for an empty run", () => {
    expect(coalesceActionLabels([], "past")).toBe("");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-display.test.ts`
Expected: FAIL — `coalesceActionLabels is not a function` / TypeScript cannot
resolve `toolActionLabel`.

- [ ] **Step 3: Implement**

Append to `webapp/src/chat/tool-display.ts`:

```ts
/** Which tense a run's label is written in. A run is described in the present
 *  participle while any of its calls is still in flight and in the past tense
 *  once every call has settled — "Searched" over a call that is still running
 *  is a false statement about a live process (spec TC4). */
export type LabelTense = "past" | "present";

// These are ACTION labels for a whole run, and they are deliberately separate
// from `toolDisplayLabel` above. That one names a CALL — "Search corpus" — and
// present-tense-imperative is the right register for a row that says "here is
// the call that was made"; it still names the child rows inside an expansion.
// This one names what the assistant DID, and reads as narration.
const PAST_ACTION: Record<string, string> = {
  retrieve: "Searched",
  cite: "Cited",
  cite_batch: "Cited",
  list_filter_values: "Browsed filters",
  create_document: "Wrote a document",
  document_guide: "Checked the style guide",
};

const PRESENT_ACTION: Record<string, string> = {
  retrieve: "Searching",
  cite: "Citing",
  cite_batch: "Citing",
  list_filter_values: "Browsing filters",
  create_document: "Writing a document",
  document_guide: "Checking the style guide",
};

/** What the assistant did (or is doing) with one tool. Falls back to the raw
 *  name, which is a legible degradation for a tool nobody has labelled yet. */
export function toolActionLabel(toolName: string, tense: LabelTense): string {
  const table = tense === "past" ? PAST_ACTION : PRESENT_ACTION;
  return table[toolName] ?? toolName;
}

/** "Searched ×2, wrote a document" — ADJACENT same-label calls coalesce into a
 *  count, and only the leading phrase keeps its capital so the whole thing
 *  reads as one sentence fragment rather than several stacked headings.
 *
 *  Adjacency matters: the array is the model's real sequence of work, so
 *  merging across a gap would claim a run of three searches where there were
 *  two separated by something else. */
export function coalesceActionLabels(
  tools: { toolName: string }[],
  tense: LabelTense,
): string {
  const parts: { label: string; n: number }[] = [];
  for (const t of tools) {
    const label = toolActionLabel(t.toolName, tense);
    const last = parts[parts.length - 1];
    if (last && last.label === label) last.n += 1;
    else parts.push({ label, n: 1 });
  }
  return parts
    .map((p, i) => {
      const text = p.n > 1 ? `${p.label} ×${p.n}` : p.label;
      return i === 0 ? text : text.charAt(0).toLowerCase() + text.slice(1);
    })
    .join(", ");
}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-display.test.ts`
Expected: PASS, all describe blocks green.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/chat/tool-display.ts webapp/src/chat/__tests__/tool-display.test.ts
git commit -m "tool card: action labels and the run coalescer (TC3, TC4)"
```

---

### Task 2: The card renders for a run of one and expands in one click

Today a lone call renders a bare `ToolCard` whose one click reveals the
passages. The card must absorb that case without adding a second click — TC5.

**Files:**
- Modify: `webapp/src/chat/ToolGroup.tsx`
- Test: `webapp/src/chat/__tests__/tool-group.test.tsx`

**Interfaces:**
- Consumes: `coalesceActionLabels`, `toolActionLabel` from Task 1;
  `toolHeaderSummary` (existing, `tool-display.ts:53`); `ToolBody` from
  `webapp/src/chat/tool-views/ToolBody.js`; `toolGlyph` from
  `webapp/src/chat/tool-views/primitives.js`.
- Produces: `ToolGroup` accepting `{ tools: ToolBlock[] }` with `tools.length >= 1`.
  New DOM element `.chat-tool-group-expansion` wrapping whatever the open card
  shows.

- [ ] **Step 1: Write the failing tests**

Replace the whole `describe("ToolGroup", …)` block in
`webapp/src/chat/__tests__/tool-group.test.tsx` (lines 47–72) with the
following. Leave the `block()` helper and the fixtures above it alone; the
`describe("ToolGroup danger scoping", …)` block and the
`failedGroupLabelSelector` helper below it are replaced in Task 4, not here —
they will go red at Step 2 and that is expected and temporary.

```tsx
describe("ToolGroup", () => {
  it("coalesces a multi-call run into one past-tense summary row", () => {
    render(
      <ToolGroup
        tools={[retrieveComplete, retrieveComplete2, listFiltersComplete]}
      />,
    );
    const head = screen.getByRole("button", {
      name: /Searched ×2, browsed filters/,
    });
    expect(head).toHaveTextContent("Searched ×2, browsed filters");
  });

  it("renders a run of ONE, carrying that call's own summary", () => {
    render(<ToolGroup tools={[retrieveComplete]} />);
    const head = screen.getByRole("button", { name: /Searched/ });
    expect(head).toHaveTextContent("Searched");
    // The query is the single most useful thing on the row and the bare
    // ToolCard this replaced showed it. Losing it would be a regression.
    expect(head).toHaveTextContent("Aviation Fund");
  });

  it("expands a run of ONE straight to that call's body — one click, not two", () => {
    // The bare ToolCard this replaced opened its body on a single click.
    // Wrapping the sole call in a child row would silently make every source
    // check a two-click operation, and every count-based assertion would
    // still pass.
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    fireEvent.click(screen.getByRole("button", { name: /Searched/ }));
    expect(container.querySelector(".chat-tool-body")).not.toBeNull();
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(0);
  });

  it("expands a multi-call run to inset child rows", () => {
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Searched, browsed filters/ }),
    );
    expect(container.querySelectorAll(".chat-tool.is-inset")).toHaveLength(2);
  });

  it("puts every expansion inside one capped container", () => {
    // TC8's cap is a single CSS rule on this element. If a future edit renders
    // the body outside it, the cap silently stops applying and a 15-passage
    // expansion buries the answer again.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, listFiltersComplete]} />,
    );
    fireEvent.click(
      screen.getByRole("button", { name: /Searched, browsed filters/ }),
    );
    const expansion = container.querySelector(".chat-tool-group-expansion")!;
    expect(expansion, "the expansion must have its capped wrapper").not.toBeNull();
    expect(expansion.querySelector(".chat-tool-group-body")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx`
Expected: FAIL — the accessible name is still `3 tool calls`, so
`getByRole("button", { name: /Searched ×2, browsed filters/ })` throws
"Unable to find an accessible element". The danger-scoping block below also
fails; it is rewritten in Task 4.

- [ ] **Step 3: Implement**

Replace the entire contents of `webapp/src/chat/ToolGroup.tsx` with:

```tsx
// One collapsible card summarizing a run of tool calls. Since 2026-08-16 it is
// normally the FIRST CHILD OF AN ANSWER BUBBLE rather than a sibling above one
// — see docs/superpowers/specs/2026-08-16-tool-card-in-message-bubble-design.md.
//
// It renders for a run of ANY size, n >= 1. At n = 1 it expands straight to
// that call's body: the bare ToolCard it replaced opened in one click, and
// making an analyst click twice to reach a source would be a regression the
// count-based tests could not see (TC5).

import { useState } from "react";

import { coalesceActionLabels, toolHeaderSummary } from "./tool-display.js";
import type { AssistantBlock } from "./chat-types.js";
import ToolCard from "./ToolCard.js";
import ToolBody from "./tool-views/ToolBody.js";
import { toolGlyph } from "./tool-views/primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tools: ToolBlock[];
}

export default function ToolGroup({ tools }: Props) {
  const [open, setOpen] = useState(false);

  const first = tools[0];
  if (!first) return null;

  const running = tools.some((t) => t.status === "running");
  const label = coalesceActionLabels(tools, running ? "present" : "past");

  // n = 1 always shows the call's own summary — the query — in both states.
  // A multi-call run shows progress while it is in flight and NOTHING once it
  // settles: "all complete" would be a false positive claim while a failure is
  // suppressed, and silence claims nothing (TC3, TC9).
  const single = tools.length === 1;
  const settled = tools.filter((t) => t.status !== "running").length;
  const detail = single
    ? toolHeaderSummary(first.toolName, first.input)
    : running
      ? `${settled} of ${tools.length} done`
      : null;

  // The accessible name tracks the visible text EXACTLY. A screen-reader user
  // must not be told about a transient failure the sighted user is
  // deliberately not being alarmed by, or the suppression is only cosmetic
  // (TC12).
  const ariaLabel = detail ? `${label}, ${detail}` : label;

  return (
    <div className="chat-tool-group">
      <button
        type="button"
        className="chat-tool-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={ariaLabel}
      >
        {/* The run's leading tool supplies the glyph. Neutral in every state —
            failure spends no colour here (TC9) — and it pulses while work is
            in flight. aria-hidden because the button's own aria-label is its
            accessible name. */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          className={"chat-tool-glyph" + (running ? " chat-pulse" : "")}
          aria-hidden="true"
        >
          {toolGlyph(first.toolName)}
        </svg>
        <span className="chat-tool-label">{label}</span>
        {detail && <span className="chat-tool-summary">{detail}</span>}
        <svg
          viewBox="0 0 10 6"
          width={10}
          height={6}
          className={`chat-tool-chevron${open ? " is-open" : ""}`}
          aria-hidden="true"
        >
          <path
            d="M1 1l4 4 4-4"
            stroke="currentColor"
            strokeWidth="1.6"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
      </button>
      {open && (
        // ONE capped container for either expansion shape, so several child
        // rows opened at once still cannot exceed the cap (TC8).
        <div className="chat-tool-group-expansion">
          {single ? (
            <ToolBody tool={first} />
          ) : (
            <div className="chat-tool-group-body">
              {tools.map((t) => (
                <ToolCard key={t.toolUseId} tool={t} inGroup />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 4: Run the tests to verify the new block passes**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx -t "ToolGroup"`
Expected: the five tests in `describe("ToolGroup", …)` PASS. The
`ToolGroup danger scoping` test still FAILS — it is rewritten in Task 4. Do
not commit until Step 5's narrower run is green.

- [ ] **Step 5: Verify the one-click behaviour by mutation**

Temporarily change the `single` branch in `ToolGroup.tsx` from
`<ToolBody tool={first} />` to:

```tsx
            <div className="chat-tool-group-body">
              <ToolCard tool={first} inGroup />
            </div>
```

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx -t "one click, not two"`
Expected: FAIL. Then `git checkout webapp/src/chat/ToolGroup.tsx` is **not**
what you want here (it would discard the whole task) — undo the mutation by
hand, restoring `<ToolBody tool={first} />`, and re-run to confirm PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/ToolGroup.tsx webapp/src/chat/__tests__/tool-group.test.tsx
git commit -m "tool card: render a run of one, expand it in a single click (TC5, TC8)"
```

---

### Task 3: Tense follows the run's state

**Files:**
- Modify: none (Task 2 already wired `running ? "present" : "past"`)
- Test: `webapp/src/chat/__tests__/tool-group.test.tsx`

This task is tests only. It exists as its own gate because TC4 is a
one-expression behaviour that a reviewer can reject independently, and because
without a pinned test the tense is the first thing a later refactor loses.

**Interfaces:**
- Consumes: `ToolGroup` from Task 2.
- Produces: nothing.

- [ ] **Step 1: Write the tests**

Append to `webapp/src/chat/__tests__/tool-group.test.tsx`:

```tsx
describe("ToolGroup tense and progress", () => {
  it("uses the present participle while any call is still in flight", () => {
    // "Searched" over a call that has not finished is a false statement about
    // a live process (TC4).
    render(<ToolGroup tools={[retrieveRunning, retrieveComplete]} />);
    const head = screen.getByRole("button", { name: /Searching/ });
    expect(head).toHaveTextContent("Searching ×2");
    expect(head).not.toHaveTextContent("Searched");
  });

  it("reports progress while a multi-call run is in flight", () => {
    render(<ToolGroup tools={[retrieveRunning, retrieveComplete]} />);
    expect(
      screen.getByRole("button", { name: /Searching/ }),
    ).toHaveTextContent("1 of 2 done");
  });

  it("shows NO detail line once a multi-call run has settled", () => {
    // "all complete" is deleted, not kept. Asserting it while suppressing
    // "1 failed" would make the card claim a clean run it cannot vouch for;
    // silence claims nothing (TC3).
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveComplete2]} />,
    );
    expect(container.querySelector(".chat-tool-summary")).toBeNull();
    expect(container.textContent).not.toContain("all complete");
  });

  it("still shows the query on a settled run of one", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    expect(container.querySelector(".chat-tool-summary")).not.toBeNull();
  });
});
```

- [ ] **Step 2: Run the tests**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx -t "tense and progress"`
Expected: PASS (Task 2 implemented the behaviour).

- [ ] **Step 3: Prove the tense test is not vacuous**

In `ToolGroup.tsx` temporarily change

```tsx
  const label = coalesceActionLabels(tools, running ? "present" : "past");
```

to

```tsx
  const label = coalesceActionLabels(tools, "past");
```

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx -t "present participle"`
Expected: FAIL. Restore the line by hand and re-run to confirm PASS.

- [ ] **Step 4: Commit**

```bash
git add webapp/src/chat/__tests__/tool-group.test.tsx
git commit -m "tool card: pin tense and the settled-run silence (TC3, TC4)"
```

---

### Task 4: The collapsed card carries no failure signal

**Files:**
- Modify: `webapp/src/chat/ToolGroup.tsx` (nothing to remove — Task 2's
  rewrite already dropped it; this task VERIFIES and pins it)
- Modify: `webapp/src/styles/app.css:1287` and `:1294` — delete both
  `.chat-tool-group.is-failed` rules and the comment block above the second
- Test: `webapp/src/chat/__tests__/tool-group.test.tsx` (replace the
  `ToolGroup danger scoping` describe block and its
  `failedGroupLabelSelector` helper)
- Test: `webapp/src/chat/__tests__/chat-css-contract.test.ts` (re-point the
  failed-group tint pin)

**Interfaces:**
- Consumes: `ToolGroup` from Task 2.
- Produces: nothing.

- [ ] **Step 1: Write the failing tests**

In `webapp/src/chat/__tests__/tool-group.test.tsx`, delete everything from the
comment banner `// FINAL REVIEW — IMPORTANT 3: a failed group must not redden
its successful children` (line 74) to the end of the file — the banner, the
`failedGroupLabelSelector` helper and the whole
`describe("ToolGroup danger scoping", …)` block. Replace it with:

```tsx
// ---------------------------------------------------------------------------
// 2026-08-16 — TC9. The collapsed card carries NO failure signal at all.
//
// This INVERTS what this file used to assert. The old tests pinned a red group
// header and a "1 failed" count, and carefully scoped the tint so it could not
// reach a successful child. All of that is gone, because the signal is not
// actionable: the model retries a failed call itself, so a red row usually
// marks a transient step in work that then succeeded, and alarming an analyst
// about a self-correcting event spends the trust every other warning needs.
//
// DEMOTED, NOT DELETED — the second test below is the half that matters. A
// suppression that also drops the call on the floor would satisfy the first
// test perfectly and destroy the audit trail, which is the direction this is
// most at risk of drifting in.
// ---------------------------------------------------------------------------

describe("ToolGroup failure handling", () => {
  it("looks identical to an all-successful run when collapsed", () => {
    const { container: withFailure } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    const head = withFailure.querySelector(".chat-tool-head")!;

    expect(withFailure.querySelector(".is-failed")).toBeNull();
    expect(withFailure.textContent).not.toMatch(/fail/i);
    expect(head.getAttribute("aria-label")).not.toMatch(/fail/i);
  });

  it("still records the failure inside the expansion", () => {
    // The audit trail is intact for anyone who opens the card; it simply stops
    // shouting at people who did not ask.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    fireEvent.click(container.querySelector(".chat-tool-head") as HTMLElement);

    const failedRows = container.querySelectorAll(
      ".chat-tool-group-body .chat-tool.is-failed",
    );
    expect(
      failedRows,
      "the failed call must still be visible once expanded",
    ).toHaveLength(1);
    expect(
      container.querySelectorAll(".chat-tool-group-body .chat-tool"),
    ).toHaveLength(2);
  });
});
```

`readFileSync` and `resolve` become unused in this file — remove the two
`node:fs` / `node:path` imports at the top (lines 8–9) or `tsc -b` fails.

Then in `webapp/src/chat/__tests__/chat-css-contract.test.ts`, replace the
test at line 434 (`"the failed-group tint stops at the group's own header
row"`) and the comment banner above it with:

```ts
  // ------------------------------------------------------------------
  // 2026-08-16 — TC9. This REPLACES a pin that required the failed-group tint
  // to exist and be scoped with a child combinator. There is no group-level
  // failure tint any more, so the defect that pin guarded — a descendant
  // selector reddening a successful child's label — is now structurally
  // impossible rather than merely tested for.
  //
  // The second assertion is what keeps this non-vacuous: the CHILD row's own
  // failed treatment must survive, or "no red on the card" would be satisfied
  // by a stylesheet that had stopped marking failures anywhere at all.
  it("the card header never carries a failure tint in any state", () => {
    expect(bare).not.toMatch(/\.chat-tool-group\.is-failed/);
    expect(bare).toMatch(
      /\.chat-tool\.is-failed\s*\{[^}]*border-color:\s*var\(--chat-danger\)/,
    );
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx src/chat/__tests__/chat-css-contract.test.ts`
Expected: the CSS-contract test FAILS — `.chat-tool-group.is-failed` is still
in `app.css`. The two `ToolGroup failure handling` tests should already PASS,
because Task 2's rewrite dropped the class from the component; if either
fails, `ToolGroup.tsx` is not the version Task 2 specified.

- [ ] **Step 3: Delete the group failure rules from the stylesheet**

In `webapp/src/styles/app.css`, delete this line (currently `:1287`):

```css
.chat-tool-group.is-failed { border-color: var(--chat-danger); }
```

and this comment block plus the rule beneath it (currently `:1288`–`:1294`):

```css
/* CHILD combinator, and only as far as the group's own header row. As a
   descendant selector this reddened the labels of the group's SUCCESSFUL
   children too whenever it was expanded, telling the analyst that calls
   which actually worked had failed. Each child row already has its own
   `.chat-tool.is-failed` treatment; the header keeps the run-level summary
   tint and nothing reaches into the body. */
.chat-tool-group.is-failed > .chat-tool-head > .chat-tool-label { color: var(--chat-danger); }
```

In their place put:

```css
/* NO group-level failure treatment, deliberately (spec TC9, 2026-08-16). A
   failed tool call no longer reddens this card or reports itself in the
   collapsed row. The model retries a failed call itself, so a red row usually
   marks a transient step in work that then succeeded — not actionable, and
   alarming an analyst about a self-correcting event costs the trust every
   other warning in this app depends on.
   Demoted, not deleted: the child row inside the expansion keeps its own
   `.chat-tool.is-failed` border and its error body, so the audit trail is
   intact for anyone who opens the card.
   Two rules used to live here — a group border tint, and a child-combinator
   label tint written that way because as a DESCENDANT selector it reddened
   successful children too. With no group tint at all, that defect is
   structurally impossible rather than merely guarded against. */
```

**Do not touch `.chat-tool.is-failed` at `:1268`** — that is the child row's
own treatment and it is what the second CSS-contract assertion pins.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx src/chat/__tests__/chat-css-contract.test.ts`
Expected: PASS.

- [ ] **Step 5: Prove the demotion test is not vacuous**

In `ToolGroup.tsx` temporarily change the multi-call expansion to drop failed
calls:

```tsx
              {tools
                .filter((t) => t.status !== "failed")
                .map((t) => (
                  <ToolCard key={t.toolUseId} tool={t} inGroup />
                ))}
```

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx -t "still records the failure"`
Expected: FAIL. Restore by hand and re-run to confirm PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/__tests__/tool-group.test.tsx webapp/src/chat/__tests__/chat-css-contract.test.ts webapp/src/styles/app.css
git commit -m "tool card: no failure signal on the collapsed card (TC9)"
```

---

### Task 5: The card moves inside the bubble that follows it

**Files:**
- Modify: `webapp/src/chat/AssistantTurnBubble.tsx:150-207`
- Test: `webapp/src/chat/__tests__/assistant-turn-bubble.test.tsx`

**Interfaces:**
- Consumes: `ToolGroup` from Task 2.
- Produces: the DOM contract every later task and test depends on — a run
  renders as `.chat-bubble > .chat-tool-group`, or standalone as a direct
  child of `.chat-turn` when no text block follows it.

- [ ] **Step 1: Write the failing tests**

In `webapp/src/chat/__tests__/assistant-turn-bubble.test.tsx`, replace the test
`"groups consecutive tool calls but leaves a lone one bare"` (line 119 to the
end of that `it` block) with:

```tsx
  it("attaches each run of tool calls to the bubble that FOLLOWS it", () => {
    // blocks: text, tool, tool, text, tool
    //   -> bubble u1 with no card (nothing preceded it)
    //   -> bubble u2 carrying the run of 2
    //   -> a standalone card for the trailing call, which has no bubble after it
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            { kind: "text", uuid: "u1", text: "Looking this up." },
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "Aviation Fund" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "toolB",
              toolName: "list_filter_values",
              input: { field: "agency" },
              status: "complete",
            },
            { kind: "text", uuid: "u2", text: "One more check." },
            {
              kind: "tool",
              toolUseId: "toolC",
              toolName: "retrieve",
              input: { query: "General Fund" },
              status: "complete",
            },
          ],
        })}
      />,
    );

    const bubbles = [...container.querySelectorAll(".chat-bubble")];
    expect(bubbles).toHaveLength(2);
    expect(bubbles[0]!.querySelector(".chat-tool-group")).toBeNull();
    expect(bubbles[1]!.querySelector(".chat-tool-group")).not.toBeNull();

    // TC6 — the trailing run has nowhere to nest and must still be visible.
    expect(
      container.querySelectorAll(".chat-turn > .chat-tool-group"),
    ).toHaveLength(1);
  });

  it("never hoists a run to the top of the turn", () => {
    // Two rounds of work. Reading order is the whole point of TC1: the card
    // sits above the text it produced, not above text that came before it.
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "FY2025" },
              status: "complete",
            },
            { kind: "text", uuid: "u1", text: "The FY 2025 figure." },
            {
              kind: "tool",
              toolUseId: "toolB",
              toolName: "retrieve",
              input: { query: "FY2024" },
              status: "complete",
            },
            {
              kind: "tool",
              toolUseId: "toolC",
              toolName: "retrieve",
              input: { query: "FY2024 detail" },
              status: "complete",
            },
            { kind: "text", uuid: "u2", text: "And the year before." },
          ],
        })}
      />,
    );

    const bubbles = [...container.querySelectorAll(".chat-bubble")];
    expect(bubbles).toHaveLength(2);
    // One card in each bubble — not two in the first and none in the second.
    for (const bubble of bubbles) {
      expect(bubble.querySelectorAll(".chat-tool-group")).toHaveLength(1);
    }
    expect(bubbles[0]!.textContent).toContain("Searched");
    expect(bubbles[1]!.textContent).toContain("Searched ×2");
    // Nothing floats between or above the bubbles.
    expect(
      container.querySelectorAll(".chat-turn > .chat-tool-group"),
    ).toHaveLength(0);
  });

  it("renders a run standalone while no answer text exists yet", () => {
    // Mid-search: there is no text block to nest inside, and withholding the
    // card would leave the analyst watching a blank screen through a
    // multi-second search (TC6).
    const { container } = render(
      <AssistantTurnBubble
        turn={turn({
          blocks: [
            {
              kind: "tool",
              toolUseId: "toolA",
              toolName: "retrieve",
              input: { query: "Aviation Fund" },
              status: "running",
            },
          ],
        })}
      />,
    );
    expect(container.querySelectorAll(".chat-bubble")).toHaveLength(0);
    expect(
      container.querySelectorAll(".chat-turn > .chat-tool-group"),
    ).toHaveLength(1);
    expect(container.textContent).toContain("Searching");
  });
```

The existing test `"keeps a run intact across an interleaved cite call"`
(immediately below) asserts `.chat-tool-group` count and stays as written —
verify it still passes rather than editing it.

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/assistant-turn-bubble.test.tsx`
Expected: FAIL — `bubbles[1].querySelector(".chat-tool-group")` is `null`
because the card is still a sibling.

- [ ] **Step 3: Implement**

In `webapp/src/chat/AssistantTurnBubble.tsx`, replace the `Segment` block and
the `return` that follows it (lines 150–218, from `const stopReason =` through
the closing `}` of the component) with:

```tsx
  const stopReason = turn.isComplete ? turn.stopReason : undefined;

  // TC1 — a run of tool calls attaches DOWNWARD, to the bubble that follows
  // it, and renders as that bubble's FIRST CHILD rather than as a sibling
  // above it. Reading order is the point: a turn that searched, wrote a
  // paragraph, searched again and wrote more produces two bubbles each wearing
  // its own card, never one card at the top claiming all the work.
  //
  // A run with no text after it renders standalone (TC6) — that covers both
  // mid-search, where no text block exists yet, and a turn that ended on a
  // tool call. Withholding it would leave the analyst watching nothing through
  // a multi-second search.
  //
  // Cite tools stay invisible (see the ruling above CITE_TOOL_NAMES) and,
  // because they are SKIPPED rather than treated as a boundary, do not split a
  // run: retrieve, cite, retrieve is still one run of two searches (TC7).
  type ToolBlockT = Extract<AssistantBlock, { kind: "tool" }>;
  type TextBlockT = Extract<AssistantBlock, { kind: "text" }>;
  type Row = { tools: ToolBlockT[]; block?: TextBlockT };

  const rows: Row[] = [];
  let pendingTools: ToolBlockT[] = [];
  for (const block of turn.blocks) {
    if (block.kind === "text") {
      rows.push({ tools: pendingTools, block });
      pendingTools = [];
    } else if (!isCiteToolBlock(block)) {
      pendingTools.push(block);
    }
  }
  if (pendingTools.length > 0) rows.push({ tools: pendingTools });

  return (
    <div className="chat-turn">
      {rows.map((row) => {
        if (!row.block) {
          return <ToolGroup key={row.tools[0]!.toolUseId} tools={row.tools} />;
        }
        const block = row.block;
        const tool = toolCitationsByBlock.get(block.uuid) ?? [];
        const inline = blockData.get(block.uuid);
        const blockCitations = [...tool, ...(inline?.citations ?? [])];
        const renderText = inline?.renderText ?? block.text;
        return (
          <div
            key={block.uuid}
            // The tail (`has-tail`) is applied ONLY on the most-recent
            // assistant turn, so one tail anchors the conversation to the
            // mascot. Older turns keep the bubble look without it.
            className={`chat-bubble${isLatest ? " has-tail" : ""}`}
          >
            {row.tools.length > 0 && <ToolGroup tools={row.tools} />}
            <CitedMarkdownContent
              content={renderText}
              citations={blockCitations}
              annotation={turn.annotation}
            />
          </div>
        );
      })}
      {stopReason === "max_steps" && (
        <div className="chat-notice is-warn" role="status">
          <strong>Incomplete answer.</strong> {INCOMPLETE_NOTICE}
        </div>
      )}
      {stopReason && STOP_NOTE[stopReason] && (
        <div className="chat-stop-note">{STOP_NOTE[stopReason]}</div>
      )}
    </div>
  );
}
```

`ToolCard` is no longer referenced in this file. Delete its import (line 29,
`import ToolCard from "./ToolCard.js";`) or `tsc -b` fails on an unused import.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/assistant-turn-bubble.test.tsx`
Expected: PASS, including the untouched cite-suppression and stop-note tests.

- [ ] **Step 5: Verify citation rendering is genuinely undisturbed (TC11)**

The card is now a sibling of `CitedMarkdownContent` inside the same element.
Chip numbering and the figure annotation index the answer TEXT, not the DOM,
so this should be inert — verify rather than assume.

Run: `cd webapp && npx vitest run src/chat/__tests__/citation-extract.test.ts src/chat/__tests__/citation-chip.test.tsx src/chat/__tests__/unified-numbering.test.tsx src/chat/__tests__/annotation-render.test.tsx`
Expected: PASS, with no test edited.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/AssistantTurnBubble.tsx webapp/src/chat/__tests__/assistant-turn-bubble.test.tsx
git commit -m "tool card: attach a run to the bubble that follows it (TC1, TC6, TC7)"
```

---

### Task 6: Containment — the card sits in the bubble's padding

This is option B from the approved mockup: the bubble keeps its own padding
and radius, and the card is a self-contained object inside it with white
gutter on all four sides.

**Files:**
- Modify: `webapp/src/styles/app.css` (append to the tool-group block, after
  `.chat-tool-group-body`)
- Test: `webapp/src/chat/__tests__/chat-css-contract.test.ts`

**Interfaces:**
- Consumes: the DOM contract from Task 5 (`.chat-bubble > .chat-tool-group`)
  and the `.chat-tool-group-expansion` element from Task 2.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Write the failing tests**

Append to the main describe block in
`webapp/src/chat/__tests__/chat-css-contract.test.ts`:

```ts
  // ------------------------------------------------------------------
  // 2026-08-16 — TC2/TC10. The card is nested by DOM POSITION, so the
  // containment styling hangs off a child selector rather than a prop. If that
  // selector is ever renamed without the component moving with it, the card
  // silently reverts to looking like a standalone row inside a white bubble —
  // a change no render test can see, because jsdom applies no stylesheet.
  it("a card inside a bubble takes the inset fill and the bubble's full width", () => {
    const rule = bareRule(".chat-bubble > .chat-tool-group");
    expect(rule, "the nested-card rule must exist").toBeTruthy();
    expect(rule).toMatch(/background:\s*var\(--canvas\)/);
    // 65ch is right for a standalone row and wrong here: the parent bubble
    // already enforces the prose measure, so leaving it on would stop the card
    // short of the bubble's right edge for no reason.
    expect(rule).toMatch(/max-width:\s*none/);
    expect(rule).toMatch(/width:\s*100%/);
  });

  it("the standalone card keeps its own prose measure", () => {
    // A supporting artifact must never be wider than the answer it supports,
    // and mid-search there is no bubble to inherit that from.
    expect(bareRule(".chat-tool-group")).toMatch(/max-width:\s*65ch/);
  });

  it("the card's expansion is capped and scrolls", () => {
    // TC8. Without this, opening a search that returned 15 passages pushes the
    // answer far down the page — the analyst opens a card to check a source
    // and loses what they were reading.
    const rule = bareRule(".chat-tool-group-expansion");
    expect(rule, "the expansion cap rule must exist").toBeTruthy();
    expect(rule).toMatch(/max-height:\s*50vh/);
    expect(rule).toMatch(/overflow-y:\s*auto/);
  });
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/chat-css-contract.test.ts`
Expected: FAIL — `bareRule(".chat-bubble > .chat-tool-group")` is falsy.

- [ ] **Step 3: Implement**

In `webapp/src/styles/app.css`, immediately after the
`.chat-tool-group-body { … }` rule, insert:

```css
/* ONE capped container for either expansion shape (spec TC8, 2026-08-16).
   Without the cap, opening a search that returned 15 passages pushes the
   answer far down the page — the analyst opens a card to check a source and
   loses what they were reading. The cap sits on this single wrapper rather
   than on each child, so several child rows opened at once still cannot
   exceed it. */
.chat-tool-group-expansion { max-height: 50vh; overflow-y: auto; }

/* ----- the card nested in an answer bubble (spec TC2/TC10, 2026-08-16) -------
   Option B of three rendered candidates, approved 2026-08-16 — see
   docs/superpowers/specs/assets/2026-08-16-tool-card-mockup/options.html.
   The bubble keeps its own padding and radius and the card sits INSIDE that
   padding as a self-contained object: its own border, its own corners, white
   gutter on all four sides. It must read as an object IN the message, never as
   a title bar ON it — a flush strip taking the bubble's top corners was shown
   and rejected outright.
   Nesting is decided by DOM POSITION, not a prop: AssistantTurnBubble renders
   the card as the bubble's first child, so a child selector is the whole
   mechanism.
   `max-width: none` because the parent bubble already enforces the 65ch prose
   measure; the standalone form (mid-search, when there is no bubble to inherit
   from) keeps 65ch of its own. */
.chat-bubble > .chat-tool-group { background: var(--canvas); max-width: none; width: 100%; margin-bottom: 10px; }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/chat-css-contract.test.ts`
Expected: PASS, including every pre-existing pin in that file (the 24/8 turn
rhythm, the deleted `.chat-tool + .chat-tool` rule, the `.chat-tool-group-body`
gap).

- [ ] **Step 5: Commit**

```bash
git add webapp/src/styles/app.css webapp/src/chat/__tests__/chat-css-contract.test.ts
git commit -m "tool card: containment inside the bubble + the expansion cap (TC2, TC8, TC10)"
```

---

### Task 7: Gates

**Files:** none modified. This task runs the suites and the browser pass.

**Interfaces:**
- Consumes: everything above.
- Produces: the evidence the work is done.

- [ ] **Step 1: Full webapp suite**

Run: `cd webapp && npm test`
Expected: exit 0. Baseline before this work is **958 passing**; the count
should rise. Any failure outside the files this plan names is a real
regression — investigate rather than update the test.

- [ ] **Step 2: Type-check and production build**

Run: `cd webapp && npm run build`
Expected: exit 0. This runs `tsc -b` first, which is stricter than the dev
check and will reject any import left unused by Tasks 4 and 5.

- [ ] **Step 3: Python suite**

Run: `uv run pytest -q`
Expected: exit 0, **2909 passed / 5 skipped** (the documented ONNX skips).
Nothing Python-side was touched; this confirms it.

- [ ] **Step 4: No eval run**

Do not run `eval.run_eval`. Nothing under `retrieval/`, `ingest/`,
`chunking/`, `citation/` or `harness/system-prompt.md` was modified, so the
CLAUDE.md eval rule does not apply and a run would measure nothing.

- [ ] **Step 5: Build the SPA and start a dev server**

```bash
cd webapp && npm run build
cd .. && JLBC_DATA_DIR=data/insight-data uv run uvicorn app.main:create_app --factory --port 9300
```

Open `http://127.0.0.1:9300/ai`. `uvicorn` runs without `--reload`, but this
change is webapp-only, so a rebuild is enough — no restart is needed unless
something Python-side was touched.

- [ ] **Step 6: The browser pass — jsdom applies no stylesheet**

This is a required gate, not a nicety. This repo has shipped four UI defects
green under thousands of passing specs. Work through every row and report what
you see:

| # | Check | Looking for |
|---|---|---|
| 1 | Ask a question needing one search | Card inside the bubble, white gutter all round, showing `Searched ↳ <the query>` |
| 2 | Ask a question needing several searches | One card reading `Searched ×N` with **no** text after it |
| 3 | Watch a search in flight | Standalone card reading `Searching`, then the bubble forming beneath it — judge whether the settle is acceptable |
| 4 | Expand a card whose search returned many passages | The answer stays reachable; the expansion scrolls inside itself rather than pushing the page |
| 5 | Expand a multi-call card | **Contrast of the inset child rows against the card.** Both are `--canvas` today, separated only by their borders. If it reads flat, the fix is one rule giving nested children `background: var(--card)` — flagged deliberately as a judgement call for the screen, not the spec |
| 6 | An answer with two rounds of work | A card above each round's prose, nothing hoisted to the top of the turn |
| 7 | A turn containing a failed call | The collapsed card looks completely ordinary — no red, no count — **and** expanding it still shows the failed call with its error |
| 8 | A resumed conversation from the history rail | Renders identically to a live one |

- [ ] **Step 7: Update STATUS.md**

Add a row to the phase-summary table and a short section recording: what
shipped, the suite counts from Steps 1–3, that no eval was run and why, the
TC9 failure-signal removal with its accepted risk (a search that fails and is
not retried now looks ordinary), and whatever Step 6 row 5 was judged to be.

- [ ] **Step 8: Commit and merge**

```bash
git add STATUS.md
git commit -m "status: the tool card now lives inside the answer bubble"
git fetch origin && git pull origin master
cd webapp && npm test && npm run build
cd .. && uv run pytest -q
git push origin HEAD
```

Re-run the suites **after** the pull, not just before it — master moves in
large merges on this repo, and STATUS.md already records a cross-branch defect
where git merged cleanly and both suites stayed green.

---

## Self-review

**Spec coverage.** TC1 → Task 5. TC2 → Task 6. TC3 → Tasks 1 and 3. TC4 →
Tasks 1 and 3. TC5 → Task 2. TC6 → Task 5. TC7 → Task 5 (the existing cite
test is preserved unedited). TC8 → Tasks 2 and 6. TC9 + TC9a → Task 4. TC10 →
Task 6. TC11 → Task 5 Step 5. TC12 → Task 2's `ariaLabel` and Task 4's
aria-label assertion. Gates → Task 7.

**Type consistency.** `coalesceActionLabels(tools, tense)` and
`toolActionLabel(name, tense)` are defined in Task 1 and used under those exact
names in Task 2. `LabelTense` is `"past" | "present"` throughout.
`.chat-tool-group-expansion` is created in Task 2 and styled in Task 6 under
the same name. `Row` / `ToolBlockT` / `TextBlockT` are local to Task 5.

**Known behaviour changes a reviewer should expect, not flag:**
`coalesceLabels` is deleted from `ToolGroup.tsx` (its replacement lives in
`tool-display.ts`); `ToolGroup`'s accessible name is no longer `N tool calls`;
`ToolCard` is no longer rendered standalone anywhere.
