# Tool card Part 2 — what the card says — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the tool card legible to a fiscal analyst — a sentence header, a
line-drawn icon set, search results grouped by document, a real view for the
style guide, English instead of field codes, and one width in both contexts.

**Architecture:** All wording moves into `tool-display.ts`; all icons into
`tool-views/primitives.tsx`; each tool's expanded body stays in its own view
file. No component assembles English and no view invents data — every field
rendered already arrives with the tool result.

**Tech Stack:** React 18 + TypeScript, Vite, vitest + @testing-library/react,
plain CSS in `webapp/src/styles/app.css`.

**Spec:** [`../specs/2026-08-16-tool-card-in-message-bubble-design.md`](../specs/2026-08-16-tool-card-in-message-bubble-design.md)
**Part 2, TC13–TC22.** Approved rendering:
[`../specs/assets/2026-08-16-tool-card-mockup/tool-cards-v2.html`](../specs/assets/2026-08-16-tool-card-mockup/tool-cards-v2.html).

**This continues an unmerged branch.** Part 1 (TC1–TC12) is already on
`tool-card-in-bubble` and must not be undone. In particular TC9 still holds:
**no failure signal anywhere on a collapsed card**, in the visible text or the
`aria-label`, no matter what wording changes here.

## Global Constraints

- **Webapp only.** Nothing under `retrieval/`, `ingest/`, `chunking/`,
  `citation/`, `harness/`, `app/`, `store/`. No eval run.
- **No corpus name** ("Budget Documents", "Fiscal Notes") in any card.
- **No jargon reaches an analyst.** Banned in card-visible text: `chunk`,
  `chunks`, `bm25`, `dense`, `fused`, `top score`, `score`, `canonical_id`,
  `doc_type`, `agency_canonical_id`, `retrieval_id`, and any raw snake_case
  field name.
- **No relevance number, bar, or rank index anywhere** (TC17).
- **`create_document`'s expanded view is not to be redesigned** — it gets the
  new icon and the new header sentence and nothing else.
- **Do not de-duplicate agency names** (TC21). Duplicate catalog ids are a real
  corpus defect with its own spec; hiding it here would bury it.
- `tsc -b` rejects unused imports and unused locals.
- Baseline to beat, measured on this branch at `c7c8b92`: **vitest 1010
  passing / 88 files**, `npm run build` exit 0, `pytest` 3151 passed / 5
  skipped.
- All commands run from the worktree root unless a step says otherwise.
- Commit after every task.

---

## File structure

| File | Responsibility after Part 2 |
|---|---|
| `webapp/src/chat/tool-display.ts` | **All wording**, including the new per-tool header sentence. |
| `webapp/src/chat/ToolGroup.tsx` | Renders the sentence; unchanged otherwise. |
| `webapp/src/chat/tool-views/primitives.tsx` | **All icons.** One stroked set, four tools. |
| `webapp/src/chat/tool-views/RetrieveView.tsx` | Search results, grouped by document. |
| `webapp/src/chat/tool-views/ListFilterValuesView.tsx` | Names, not codes. |
| `webapp/src/chat/tool-views/DocumentGuideView.tsx` | **New.** The style guide, readable. |
| `webapp/src/chat/tool-views/ToolBody.tsx` | Dispatch only — gains one case. |
| `webapp/src/styles/app.css` | New view styles + the TC22 width parity. |

## Execution order and parallelism

Tasks 1–3 touch disjoint file sets and **run concurrently in separate
worktrees**. Task 4 is CSS, which all three would otherwise contend on, so it
is serialized after them. Task 5 is the gate.

| | Task | Files |
|---|---|---|
| Lane A | 1 — header sentence | `tool-display.ts`, `ToolGroup.tsx`, their tests |
| Lane B | 2 — icons + style guide + filters | `primitives.tsx`, `DocumentGuideView.tsx`, `ListFilterValuesView.tsx`, `ToolBody.tsx`, their tests |
| Lane C | 3 — search grouped by document | `RetrieveView.tsx`, its tests |
| then | 4 — CSS + width parity | `app.css`, `chat-css-contract.test.ts` |
| then | 5 — gates | none |

**No lane may touch `app.css`.** A lane that needs a style declares the class
name it used in its report; Task 4 implements every one of them.

---

### Task 1: The collapsed card reads as a sentence

**Files:**
- Modify: `webapp/src/chat/tool-display.ts`
- Modify: `webapp/src/chat/ToolGroup.tsx`
- Test: `webapp/src/chat/__tests__/tool-display.test.ts`
- Test: `webapp/src/chat/__tests__/tool-group.test.tsx`

**Interfaces:**
- Consumes: `toolActionLabel`, `coalesceActionLabels`, `LabelTense`,
  `toolHeaderSummary` — all existing in `tool-display.ts`.
- Produces: `export function toolHeaderSentence(tools: {toolName: string; input: Record<string, unknown>}[], tense: LabelTense): { verb: string; rest: string }`
  — the verb is rendered bold, `rest` normal weight. Task 4 styles them.

- [ ] **Step 1: Write the failing tests**

Append to `webapp/src/chat/__tests__/tool-display.test.ts`, adding
`toolHeaderSentence` to the existing import from `../tool-display.js`:

```ts
describe("toolHeaderSentence", () => {
  const search = (query: string) => ({ toolName: "retrieve", input: { query } });

  it("reads as a sentence for a single search", () => {
    const s = toolHeaderSentence([search("State Aviation Fund balance FY2025")], "past");
    expect(s.verb).toBe("Searched");
    expect(s.rest).toBe(' for “State Aviation Fund balance FY2025”');
  });

  it("keeps the first query visible however many searches ran", () => {
    // The rejected alternative led with the count, which pushes the one
    // informative part of the row toward the ellipsis.
    const s = toolHeaderSentence(
      [search("State Aviation Fund balance FY2025"), search("b"), search("c")],
      "past",
    );
    expect(s.verb).toBe("Searched");
    expect(s.rest).toBe(' for “State Aviation Fund balance FY2025” and 2 more');
  });

  it("uses the present participle while a call is in flight", () => {
    const s = toolHeaderSentence([search("aviation fund")], "present");
    expect(s.verb).toBe("Searching");
    expect(s.rest).toBe(' for “aviation fund”…');
  });

  it("names each tool with its own preposition", () => {
    expect(
      toolHeaderSentence([{ toolName: "create_document", input: { title: "AHCCCS FY24-26" } }], "past"),
    ).toEqual({ verb: "Wrote", rest: ' the document “AHCCCS FY24-26”' });
    expect(
      toolHeaderSentence([{ toolName: "document_guide", input: { report_type: "research-memo" } }], "past"),
    ).toEqual({ verb: "Checked", rest: " the house style for a research memo" });
    expect(
      toolHeaderSentence([{ toolName: "list_filter_values", input: { field: "agency_canonical_id" } }], "past"),
    ).toEqual({ verb: "Checked", rest: " which agencies the corpus covers" });
  });

  it("appends a second kind of work rather than dropping the query", () => {
    const s = toolHeaderSentence(
      [search("AHCCCS General Fund FY2026"), search("b"), search("c"),
       { toolName: "create_document", input: { title: "Memo" } }],
      "past",
    );
    expect(s.rest).toBe(' for “AHCCCS General Fund FY2026” and 2 more, then wrote a document');
  });

  it("never leaks a raw field name or a corpus name", () => {
    const s = toolHeaderSentence(
      [{ toolName: "list_filter_values", input: { field: "agency_canonical_id" } }],
      "past",
    );
    const whole = s.verb + s.rest;
    expect(whole).not.toMatch(/canonical_id|doc_type|Budget Documents|Fiscal Notes/);
  });

  it("degrades legibly for an unregistered tool", () => {
    const s = toolHeaderSentence([{ toolName: "some_future_tool", input: { thing: "x" } }], "past");
    expect(s.verb).toBe("some_future_tool");
    expect(s.rest).toContain("x");
  });

  it("returns an empty sentence for an empty run", () => {
    expect(toolHeaderSentence([], "past")).toEqual({ verb: "", rest: "" });
  });
});
```

Append to `webapp/src/chat/__tests__/tool-group.test.tsx`:

```tsx
describe("ToolGroup header sentence", () => {
  it("renders the verb bold and the rest normal", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    const verb = container.querySelector(".chat-tool-verb")!;
    expect(verb, "the verb must be its own element so it can be bold").not.toBeNull();
    expect(verb.textContent).toBe("Searched");
    expect(container.querySelector(".chat-tool-head")!.textContent).toContain(
      "for “Aviation Fund”",
    );
  });

  it("still carries NO failure word when a call failed (TC9 survives Part 2)", () => {
    // Part 1's whole failure decision must not be undone by rewording.
    const { container } = render(
      <ToolGroup tools={[retrieveComplete, retrieveFailed]} />,
    );
    const head = container.querySelector(".chat-tool-head")!;
    expect(head.textContent).not.toMatch(/fail/i);
    expect(head.getAttribute("aria-label")).not.toMatch(/fail/i);
    expect(container.querySelector(".is-failed")).toBeNull();
  });

  it("the accessible name is the whole sentence", () => {
    const { container } = render(<ToolGroup tools={[retrieveComplete]} />);
    expect(
      container.querySelector(".chat-tool-head")!.getAttribute("aria-label"),
    ).toBe("Searched for “Aviation Fund”");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-display.test.ts src/chat/__tests__/tool-group.test.tsx`
Expected: FAIL — `toolHeaderSentence is not a function`, and `.chat-tool-verb`
is null.

- [ ] **Step 3: Implement the sentence builder**

Append to `webapp/src/chat/tool-display.ts`:

```ts
/** The collapsed card's header, split so the caller can weight the two parts
 *  differently: the verb renders bold and keeps the row scannable down a long
 *  conversation, the rest reads as ordinary prose (spec TC13).
 *
 *  Each tool needs its own preposition, which is exactly why this lives here
 *  and not in the component — "Searched for X", "Wrote the document X",
 *  "Checked the house style for X" share no grammar. */
export function toolHeaderSentence(
  tools: { toolName: string; input: Record<string, unknown> }[],
  tense: LabelTense,
): { verb: string; rest: string } {
  const first = tools[0];
  if (!first) return { verb: "", rest: "" };

  const running = tense === "present";
  const tail = running ? "…" : "";

  // How many calls share the LEADING tool's name. Counted on the leading run
  // only: the sentence names what it started doing, then appends anything of a
  // different kind after it.
  let sameKind = 0;
  while (sameKind < tools.length && tools[sameKind]!.toolName === first.toolName) {
    sameKind += 1;
  }
  const more = sameKind > 1 ? ` and ${sameKind - 1} more` : "";

  // Anything after the leading run, described in one clause. Deliberately not
  // recursive: the row is a single truncating line, and a nested sentence would
  // be cut off before it read as one.
  const remainder = tools.slice(sameKind);
  const then =
    remainder.length > 0
      ? `, then ${lowerFirst(coalesceActionLabels(remainder, tense))}`
      : "";

  const q = (s: string) => `“${s}”`;
  const summary = toolHeaderSummary(first.toolName, first.input);

  switch (first.toolName) {
    case "retrieve":
      return {
        verb: running ? "Searching" : "Searched",
        rest: summary ? ` for ${q(summary)}${more}${tail}${then}` : `${more}${tail}${then}`,
      };
    case "create_document":
      return {
        verb: running ? "Writing" : "Wrote",
        rest: summary ? ` the document ${q(summary)}${more}${tail}${then}` : ` a document${tail}${then}`,
      };
    case "document_guide":
      return {
        verb: running ? "Checking" : "Checked",
        rest: ` the house style for a ${reportTypeName(summary)}${tail}${then}`,
      };
    case "list_filter_values":
      return {
        verb: running ? "Checking" : "Checked",
        rest: ` which ${filterFieldName(summary)} the corpus covers${tail}${then}`,
      };
    default: {
      // Unregistered tool: the bare name plus its first string argument, which
      // is a legible degradation rather than a blank row.
      return {
        verb: first.toolName,
        rest: summary ? ` ${summary}${more}${tail}${then}` : `${more}${tail}${then}`,
      };
    }
  }
}

function lowerFirst(s: string): string {
  return s.length > 0 ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

/** "research-memo" -> "research memo". The tool's own default is applied
 *  server-side, so a null here means the model asked for no particular shape;
 *  naming one would show a choice it never made. */
function reportTypeName(reportType: string | null): string {
  if (!reportType) return "document";
  return reportType.replace(/[-_]/g, " ");
}

/** The filter FIELD as a plain noun. Raw column names never reach an analyst. */
function filterFieldName(field: string | null): string {
  switch (field) {
    case "agency_canonical_id":
      return "agencies";
    case "doc_type":
      return "kinds of document";
    case "fiscal_year":
      return "years";
    case "publisher":
      return "publishers";
    default:
      return "values";
  }
}
```

- [ ] **Step 4: Render it in the card**

In `webapp/src/chat/ToolGroup.tsx`, replace the `label` / `detail` computation
and the two `<span>`s in the header with the sentence. Keep everything else —
the glyph, the chevron, the expansion, and the absence of any failure signal —
exactly as it is.

```tsx
  const sentence = toolHeaderSentence(tools, running ? "present" : "past");
  const ariaLabel = `${sentence.verb}${sentence.rest}`;
```

and in the JSX, in place of the label and summary spans:

```tsx
        <span className="chat-tool-sentence">
          <b className="chat-tool-verb">{sentence.verb}</b>
          {sentence.rest}
        </span>
```

Import `toolHeaderSentence` and drop `coalesceActionLabels` /
`toolHeaderSummary` from `ToolGroup.tsx`'s imports if they become unused —
`tsc -b` fails otherwise.

**Do not delete `coalesceActionLabels` or `toolHeaderSummary` from
`tool-display.ts`.** The sentence builder calls both, and `toolHeaderSummary`
also still drives the inset child rows.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-display.test.ts src/chat/__tests__/tool-group.test.tsx`
Expected: PASS, including every Part 1 test in those files.

- [ ] **Step 6: Prove the TC9 guard is not vacuous**

Temporarily append `" — 1 failed"` to `sentence.rest` in `ToolGroup.tsx`.
Run: `cd webapp && npx vitest run src/chat/__tests__/tool-group.test.tsx -t "NO failure word"`
Expected: FAIL. Restore by hand and re-run to confirm PASS.

- [ ] **Step 7: Commit**

```bash
git add webapp/src/chat/tool-display.ts webapp/src/chat/ToolGroup.tsx \
        webapp/src/chat/__tests__/tool-display.test.ts \
        webapp/src/chat/__tests__/tool-group.test.tsx
git commit -m "tool card: the collapsed header reads as a sentence (TC13, TC14)"
```

---

### Task 2: The icon set, the style-guide view, and English filters

**Files:**
- Modify: `webapp/src/chat/tool-views/primitives.tsx`
- Create: `webapp/src/chat/tool-views/DocumentGuideView.tsx`
- Modify: `webapp/src/chat/tool-views/ListFilterValuesView.tsx`
- Modify: `webapp/src/chat/tool-views/ToolBody.tsx`
- Test: `webapp/src/chat/__tests__/tool-body.test.tsx`
- Test: `webapp/src/chat/__tests__/tool-card.test.tsx`

**Interfaces:**
- Consumes: `ToolBlock` from `chat-types.js`; `Chip` / `ErrorBlock` from
  `primitives.js`; `MarkdownContent` from `../MarkdownContent.js`.
- Produces: `toolGlyph(toolName)` returning stroked paths on a **24×24**
  viewBox (it was 12×12 — every caller's `viewBox` must move with it);
  `DocumentGuideView`.
- Declares for Task 4: classes `chat-guide-note`, `chat-guide-rule`,
  `chat-filter-values`.

- [ ] **Step 1: Write the failing tests**

Append to `webapp/src/chat/__tests__/tool-body.test.tsx`:

```tsx
describe("DocumentGuideView", () => {
  const guideTool = (overrides = {}) =>
    ({
      kind: "tool",
      toolUseId: "g1",
      toolName: "document_guide",
      input: { report_type: "research-memo" },
      status: "complete",
      output: JSON.stringify({
        report_type: "research-memo",
        guide:
          "## Numbers\n\nRound to one decimal place in the document body.\n\n## Shape\n\nIssue, background, analysis, options.",
      }),
      ...overrides,
    }) as ToolBlock;

  it("renders the guide as readable text, not raw JSON", () => {
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toContain("Round to one decimal place");
    // The raw payload's own punctuation must not survive to the screen.
    expect(container.textContent).not.toContain('"report_type"');
    expect(container.textContent).not.toContain("\\n");
  });

  it("names the report type in plain English", () => {
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toContain("research memo");
    expect(container.textContent).not.toContain("research-memo");
  });

  it("states that the guidance is advice, not enforcement", () => {
    // Nothing validates the finished document against these rules. A card
    // that showed house rules without saying so would imply a check that does
    // not exist.
    const { container } = render(<ToolBody tool={guideTool()} />);
    expect(container.textContent).toMatch(/nothing checks|not enforced|advice/i);
  });
});

describe("ListFilterValuesView — names, not codes", () => {
  const filterTool = () =>
    ({
      kind: "tool",
      toolUseId: "f1",
      toolName: "list_filter_values",
      input: { field: "agency_canonical_id" },
      status: "complete",
      output: JSON.stringify({
        field: "agency_canonical_id",
        values: [
          { canonical_id: "agency:ahcccs", chunk_count: 4812, sample_doc_title: "AHCCCS — FY 2026 Baseline" },
          { canonical_id: "agency:ade", chunk_count: 3109, sample_doc_title: "Education, Department of — FY 2026 Baseline" },
        ],
      }),
      ...{},
    }) as ToolBlock;

  it("shows no field codes, no slugs and no chunk counts", () => {
    const { container } = render(<ToolBody tool={filterTool()} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("agency_canonical_id");
    expect(text).not.toContain("agency:ahcccs");
    expect(text).not.toContain("4,812");
    expect(text).not.toMatch(/chunk/i);
  });

  it("shows the agencies themselves", () => {
    const { container } = render(<ToolBody tool={filterTool()} />);
    expect(container.textContent).toContain("AHCCCS");
  });
});
```

Append to `webapp/src/chat/__tests__/tool-card.test.tsx`:

```tsx
describe("tool glyphs", () => {
  it("gives every tool that reaches an analyst its own icon", () => {
    // `document_guide` had no case and fell through to the generic filled
    // square — and it is the tool that runs right before a memo is written.
    const shapes = new Map<string, string>();
    for (const name of ["retrieve", "list_filter_values", "create_document", "document_guide"]) {
      const { container } = render(
        <ToolCard tool={block({ toolName: name, toolUseId: name })} />,
      );
      const svg = container.querySelector(".chat-tool-glyph")!;
      shapes.set(name, svg.innerHTML);
    }
    expect(new Set(shapes.values()).size, "each tool needs a distinct glyph").toBe(4);
    for (const [name, html] of shapes) {
      expect(html, `${name} must not be the fallback square`).not.toBe(
        '<rect x="2" y="2" width="8" height="8" fill="currentColor"></rect>',
      );
    }
  });

  it("draws the glyphs as strokes on a 24x24 grid, matching the app's own icons", () => {
    const { container } = render(<ToolCard tool={block({ toolName: "retrieve" })} />);
    const svg = container.querySelector(".chat-tool-glyph")!;
    expect(svg.getAttribute("viewBox")).toBe("0 0 24 24");
    expect(svg.getAttribute("stroke")).toBe("currentColor");
    expect(svg.getAttribute("fill")).toBe("none");
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-body.test.tsx src/chat/__tests__/tool-card.test.tsx`
Expected: FAIL — no `DocumentGuideView`, glyphs are 12×12 filled rects, and the
filter view prints `agency_canonical_id`.

- [ ] **Step 3: Replace the glyph set**

In `webapp/src/chat/tool-views/primitives.tsx`, replace the whole `toolGlyph`
function. Every glyph is now stroked paths on a **24×24** viewBox.

```tsx
// Stroked line icons on a 24x24 grid, returned as a <g> for the caller to wrap
// in <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">.
//
// WHY these replaced the pixel-art set (spec TC15, 2026-08-16): the old
// magnifier was six rects approximating a ring on a 12x12 grid, and at the
// ~13px these render at, the ring closed into an illegible blob — the product
// owner reported it as "the icon thing". The app ALREADY owns a magnifier,
// components/SearchIcon.tsx, taken from the approved design mockup and used in
// four places on Home and Budget Documents; the tool row was the only place in
// the app drawing a second one. The mascot keeps its pixel art: that is
// character art, this is chrome, and the rest of the app's chrome is lines.
export function toolGlyph(toolName: string): ReactNode {
  switch (toolName) {
    case "retrieve":
      // The app's own magnifier, verbatim from components/SearchIcon.tsx.
      return (
        <g>
          <circle cx="11" cy="11" r="7" />
          <path d="m21 21-4.3-4.3" />
        </g>
      );
    case "cite":
    case "cite_batch":
      // Never rendered — cite blocks are suppressed (TC7) — but kept so the
      // set is total and a future caller cannot fall through to nothing.
      return (
        <g>
          <path d="M6 3h12v18l-6-4-6 4z" />
        </g>
      );
    case "list_filter_values":
      return (
        <g>
          <path d="M3 5h18l-7 8v6l-4 2v-8z" />
        </g>
      );
    case "create_document":
      return (
        <g>
          <path d="M6 3h8l4 4v14H6z" />
          <path d="M14 3v4h4" />
          <path d="M9 12h6M9 16h6" />
        </g>
      );
    case "document_guide":
      // An open book. This tool had NO case at all and fell through to the
      // square below, which is what left it iconless in the UI.
      return (
        <g>
          <path d="M4 4.5A2.5 2.5 0 0 1 6.5 2H19v18H6.5A2.5 2.5 0 0 0 4 22z" />
          <path d="M9 7h6" />
        </g>
      );
    default:
      // Unknown tool — a neutral square outline.
      return <rect x="4" y="4" width="16" height="16" rx="2" />;
  }
}
```

Then update **every** caller's wrapping `<svg>` from the 12×12 filled form to
the 24×24 stroked form. Find them with:

```bash
cd webapp && grep -rn "toolGlyph" src/
```

Each wrapper becomes:

```tsx
        <svg
          viewBox="0 0 24 24"
          width={13}
          height={13}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinejoin="round"
          strokeLinecap="round"
          className={/* unchanged */}
          /* keep each caller's existing role / aria-label / aria-hidden */
        >
          {toolGlyph(tool.toolName)}
        </svg>
```

**Leaving a caller on `viewBox="0 0 12 12"` renders a quarter of the icon,
scaled up and cropped — and no test in this plan would catch it**, so change
every hit the grep returns.

- [ ] **Step 4: Create the style-guide view**

Create `webapp/src/chat/tool-views/DocumentGuideView.tsx`:

```tsx
// Per-tool body view for `document_guide`. Until 2026-08-16 this tool had NO
// view and NO icon: it fell through to RawFallbackView and dumped escaped
// JSON. It runs immediately before the assistant writes a document, so it
// appears in exactly the conversations that end in a memo the analyst sends
// under their own name.

import type { AssistantBlock } from "../chat-types.js";
import MarkdownContent from "../MarkdownContent.js";
import { ErrorBlock } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface GuideOutput {
  report_type: string | null;
  guide: string;
}

function parseGuide(raw: string | undefined): GuideOutput | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "guide" in parsed &&
      typeof (parsed as { guide: unknown }).guide === "string"
    ) {
      return parsed as GuideOutput;
    }
  } catch {
    // fall through
  }
  return null;
}

/** "research-memo" -> "research memo". */
function readableType(t: string | null | undefined): string {
  if (!t) return "document";
  return t.replace(/[-_]/g, " ");
}

export default function DocumentGuideView({ tool }: { tool: ToolBlock }) {
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseGuide(tool.output);
  const asked = (tool.input.report_type as string | undefined) ?? null;
  const type = readableType(parsed?.report_type ?? asked);

  return (
    <div className="chat-stack">
      {/* The honesty line, and it is not optional. Nothing validates the
          finished document against these rules — the design that added this
          tool refused a server-side rewrite on purpose, because that would
          mean editing figures the analyst is about to send under their own
          name. A card that displayed house rules without saying so would imply
          a check that does not exist. */}
      <p className="chat-guide-note">
        Read JLBC's writing rules for a <strong>{type}</strong> before drafting.
        These are the rules the assistant was given — advice only, and nothing
        checks the finished document against them.
      </p>

      {parsed && (
        <div className="chat-guide-rule">
          <MarkdownContent content={parsed.guide} />
        </div>
      )}

      {!parsed && !error && tool.output && (
        <div className="chat-block">
          <pre>{tool.output}</pre>
        </div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
```

Wire it in `webapp/src/chat/tool-views/ToolBody.tsx` by adding one case
alongside the others:

```tsx
      case "document_guide":
        return <DocumentGuideView tool={tool} />;
```

- [ ] **Step 5: Rewrite the filter view's analyst-facing text**

In `webapp/src/chat/tool-views/ListFilterValuesView.tsx`: replace the
`Field` / chip / `N values` row with a sentence, and render each value as its
readable name with no count.

The readable name comes from the value's own `sample_doc_title`, which already
arrives: take the portion before the first `—` or `-` separator and trim it;
fall back to the raw `canonical_id` when there is no usable title, because a
blank row is worse than a code.

```tsx
/** The analyst-facing name for a filter value. `sample_doc_title` already
 *  arrives with every value and begins with the agency's real name, e.g.
 *  "AHCCCS — FY 2026 Baseline". Falls back to the raw id rather than rendering
 *  nothing: a code is ugly, a blank row is a lie about what the corpus holds. */
export function valueDisplayName(v: { canonical_id: string; sample_doc_title?: string }): string {
  const title = (v.sample_doc_title ?? "").trim();
  if (title.length > 0) {
    const head = title.split(/\s+[—–-]\s+/)[0]!.trim();
    if (head.length > 0) return head;
  }
  return v.canonical_id;
}
```

**Do not de-duplicate the resulting names** (TC21). Two rows both reading
"Child Safety" are a real corpus defect with its own spec; collapsing them here
would hide it.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-body.test.tsx src/chat/__tests__/tool-card.test.tsx`
Expected: PASS.

- [ ] **Step 7: Prove the glyph test is not vacuous**

Temporarily delete the `case "document_guide":` branch from `toolGlyph` so it
falls back to the square.
Run: `cd webapp && npx vitest run src/chat/__tests__/tool-card.test.tsx -t "own icon"`
Expected: FAIL. Restore by hand and re-run to confirm PASS.

- [ ] **Step 8: Commit**

```bash
git add webapp/src/chat/tool-views/ webapp/src/chat/__tests__/tool-body.test.tsx \
        webapp/src/chat/__tests__/tool-card.test.tsx
git commit -m "tool card: one icon set, a real style-guide view, English filters (TC15, TC20, TC21)"
```

---

### Task 3: Search results group by document

**Files:**
- Modify: `webapp/src/chat/tool-views/RetrieveView.tsx`
- Test: `webapp/src/chat/__tests__/tool-body.test.tsx` — **append only**, in a
  new `describe`. Task 2 is editing this same file in a parallel worktree; keep
  your additions in one contiguous block at the end so the merge is clean.

**Interfaces:**
- Consumes: the existing `ChunkPreview` / `RetrieveOutput` shapes already
  declared in `RetrieveView.tsx`. **No new data.**
- Declares for Task 4: classes `chat-search-summary`, `chat-doc-group`,
  `chat-doc-head`, `chat-doc-pages`.

- [ ] **Step 1: Write the failing tests**

Append a new `describe` block at the end of
`webapp/src/chat/__tests__/tool-body.test.tsx`:

```tsx
describe("RetrieveView — grouped by document", () => {
  const chunk = (over: Record<string, unknown> = {}) => ({
    chunk_id: "c1", doc_id: "agao-afr-fy2025",
    doc_title: "FY 2025 Annual Financial Report",
    publisher: "agao", fiscal_year: 2025, doc_type: "afr",
    section_path: ["Note 1. — Summary", "Note 3. — Statement of Expenditures"],
    page_start: 162, page_end: null,
    text: "Note 1. — Summary > Note 3. — Statement of Expenditures\nSTATE OF ARIZONA\nFund balance, June 30 2025 … 60,092,781.04",
    score: 1.26, ...over,
  });
  const retrieveTool = (chunks: unknown[]) =>
    ({
      kind: "tool", toolUseId: "r1", toolName: "retrieve",
      input: { query: "Aviation Fund", filters: { doc_type: "afr", fiscal_year: 2025 } },
      status: "complete",
      output: JSON.stringify({
        chunks, top_score: 1.26, retrieval_id: "x",
        bm25_count: 131, dense_count: 100, fused_count: 20,
      }),
    }) as ToolBlock;

  it("shows one block per DOCUMENT, not one per passage", () => {
    const { container } = render(
      <ToolBody tool={retrieveTool([
        chunk({ chunk_id: "a", page_start: 162 }),
        chunk({ chunk_id: "b", page_start: 163 }),
        chunk({ chunk_id: "c", page_start: 164 }),
        chunk({ chunk_id: "d", doc_id: "jlbc-baseline-fy2026-tra",
                doc_title: "FY 2026 Baseline — Transportation", publisher: "jlbc",
                fiscal_year: 2026, page_start: 4, section_path: ["Aviation Fund"],
                text: "The Aviation Fund receives revenue from the aircraft licence tax." }),
      ])} />,
    );
    expect(container.querySelectorAll(".chat-doc-group")).toHaveLength(2);
    // Three passages from one document must not print its title three times.
    const titles = [...container.querySelectorAll(".chat-doc-head")]
      .map((n) => n.textContent ?? "")
      .filter((t) => t.includes("Annual Financial Report"));
    expect(titles).toHaveLength(1);
  });

  it("lists every page of a document it grouped", () => {
    const { container } = render(
      <ToolBody tool={retrieveTool([
        chunk({ chunk_id: "a", page_start: 162 }),
        chunk({ chunk_id: "b", page_start: 163 }),
      ])} />,
    );
    const pages = container.querySelector(".chat-doc-pages")!.textContent ?? "";
    expect(pages).toContain("162");
    expect(pages).toContain("163");
  });

  it("shows no score, no rank number and no pipeline counters", () => {
    // A raw cross-encoder logit beside a dollar figure invites reading it as a
    // confidence. Budget Documents removed its relevance number for the same
    // reason; order carries the ranking.
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const text = container.textContent ?? "";
    expect(text).not.toMatch(/score/i);
    expect(text).not.toMatch(/bm25|dense|fused/i);
    expect(text).not.toMatch(/#1/);
    expect(text).not.toMatch(/chunk/i);
    expect(text).not.toContain("1.26");
  });

  it("does not print the section heading twice", () => {
    // The stored passage text BEGINS with its own heading, and the view also
    // renders that heading, so ~3 lines of every result were the line above it
    // repeated.
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const text = container.textContent ?? "";
    const first = text.indexOf("Note 3. — Statement of Expenditures");
    expect(first).toBeGreaterThanOrEqual(0);
    expect(
      text.indexOf("Note 3. — Statement of Expenditures", first + 1),
      "the heading must appear once, not once as a breadcrumb and again inside the passage",
    ).toBe(-1);
  });

  it("describes the filters in English", () => {
    const { container } = render(<ToolBody tool={retrieveTool([chunk()])} />);
    const text = container.textContent ?? "";
    expect(text).not.toContain("doc_type");
    expect(text).not.toContain("fiscal_year");
    expect(text).toMatch(/2025/);
  });

  it("says plainly what it found", () => {
    const { container } = render(
      <ToolBody tool={retrieveTool([chunk({ chunk_id: "a" }), chunk({ chunk_id: "b", page_start: 163 })])} />,
    );
    expect(container.querySelector(".chat-search-summary")!.textContent)
      .toMatch(/2 passages.*1 document/);
  });

  it("says so when it found nothing", () => {
    const { container } = render(<ToolBody tool={retrieveTool([])} />);
    expect(container.textContent).toMatch(/nothing|no passages/i);
    expect(container.textContent).not.toMatch(/threshold|refusal/i);
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-body.test.tsx -t "grouped by document"`
Expected: FAIL — no `.chat-doc-group`, and `score` / `chunk` are present.

- [ ] **Step 3: Implement**

Rewrite the body of `RetrieveView.tsx`. Keep `parseRetrieveOutput` and the
interfaces; replace the render and `ChunkRow`.

Group the chunks preserving arrival order (which is rank order), keep each
document's FIRST chunk as the one whose text is shown, and collect every page.

```tsx
interface DocGroup {
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  best: ChunkPreview;
  pages: string[];
  count: number;
}

/** Group by document, preserving arrival order — which is rank order, so the
 *  first chunk of each group is that document's strongest passage and the
 *  groups themselves stay in relevance order. */
function groupByDocument(chunks: ChunkPreview[]): DocGroup[] {
  const out: DocGroup[] = [];
  const byId = new Map<string, DocGroup>();
  for (const c of chunks) {
    let g = byId.get(c.doc_id);
    if (!g) {
      g = {
        doc_id: c.doc_id,
        doc_title: c.doc_title || c.doc_id,
        publisher: c.publisher,
        fiscal_year: c.fiscal_year,
        best: c,
        pages: [],
        count: 0,
      };
      byId.set(c.doc_id, g);
      out.push(g);
    }
    g.count += 1;
    const p = pageLabel(c);
    if (p && !g.pages.includes(p)) g.pages.push(p);
  }
  return out;
}

function pageLabel(c: ChunkPreview): string | null {
  if (c.page_start == null) return null;
  return c.page_end != null && c.page_end !== c.page_start
    ? `pp. ${c.page_start}–${c.page_end}`
    : `p. ${c.page_start}`;
}

/** The passage text with its own section heading removed.
 *
 *  The chunker prepends the section path to the stored text, and the view
 *  renders that heading too, so without this ~3 lines of every result were the
 *  line above it repeated — the single biggest source of noise in the old
 *  card. Compared on collapsed whitespace and with the separator normalised,
 *  because the stored text writes " > " where the breadcrumb writes " › ". */
export function stripLeadingHeading(text: string, sectionPath: string[]): string {
  if (sectionPath.length === 0) return text;
  const norm = (s: string) => s.replace(/[›>]/g, ">").replace(/\s+/g, " ").trim();
  const heading = norm(sectionPath.join(" > "));
  if (heading.length === 0) return text;
  const lines = text.split("\n");
  let cut = 0;
  let seen = "";
  while (cut < lines.length && norm(seen).length < heading.length) {
    seen += (seen ? " " : "") + lines[cut]!;
    cut += 1;
    if (norm(seen) === heading) return lines.slice(cut).join("\n").trimStart();
  }
  return text;
}
```

The render replaces the filters row, the counters row and the chunk list with:

```tsx
    <div className="chat-stack">
      {parsed && (
        <p className="chat-search-summary">
          {describeSearch(filters, parsed.chunks.length, groups.length)}
        </p>
      )}
      {groups.map((g) => (
        <div className="chat-doc-group" key={g.doc_id}>
          <div className="chat-doc-head">
            <span className="chat-doc-title">{g.doc_title}</span>
            <Chip>{publisherName(g.publisher)}</Chip>
            {g.fiscal_year != null && <Chip>FY {g.fiscal_year}</Chip>}
          </div>
          <div className="chat-doc-text">
            {preview(stripLeadingHeading(g.best.text, g.best.section_path))}
          </div>
          {g.pages.length > 0 && (
            <div className="chat-doc-pages">
              <span className="chat-muted">
                {g.count} passage{g.count === 1 ? "" : "s"} —
              </span>
              {g.pages.map((p) => (
                <Chip key={p}>{p}</Chip>
              ))}
            </div>
          )}
        </div>
      ))}
      {parsed && parsed.chunks.length === 0 && (
        <div className="chat-note">This search found nothing.</div>
      )}
      {error && <ErrorBlock error={error} />}
    </div>
```

You must also write `describeSearch`, `publisherName` and `preview`:

- `describeSearch(filters, passages, documents)` — a sentence like
  `Looked in Annual Financial Reports from FY 2025. Found 5 passages across 2 documents.`
  The filter names come from `GET /api/document-types` where available; **do
  not block the render on a fetch** — if no label is known, use the raw value
  in the sentence rather than a field name, e.g. `Looked in afr from FY 2025`.
  Never print the key.
- `publisherName(p)` — `agao` → `Auditor General`, `jlbc` → `JLBC`,
  `governor` → `Governor's Office`, `legislature` → `Legislature`; unknown
  falls back to the raw value.
- `preview(text)` — the existing 240-character truncation with an ellipsis.

Delete `VISIBLE_CHUNKS_DEFAULT`, the `showAll` state and the `ChunkRow`
component if nothing else uses them; keep a "show more" only if a run exceeds
**six** document groups.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd webapp && npx vitest run src/chat/__tests__/tool-body.test.tsx -t "grouped by document"`
Expected: PASS.

- [ ] **Step 5: Prove the de-duplication test is not vacuous**

Temporarily make `stripLeadingHeading` return `text` unchanged.
Run: `cd webapp && npx vitest run src/chat/__tests__/tool-body.test.tsx -t "section heading twice"`
Expected: FAIL. Restore by hand and re-run to confirm PASS.

- [ ] **Step 6: Commit**

```bash
git add webapp/src/chat/tool-views/RetrieveView.tsx webapp/src/chat/__tests__/tool-body.test.tsx
git commit -m "tool card: search results group by document (TC16, TC17, TC18, TC19)"
```

---

### Task 4: The stylesheet, and one width in both contexts

Runs after Tasks 1–3 are merged, because all three would otherwise contend on
this file.

**Files:**
- Modify: `webapp/src/styles/app.css`
- Test: `webapp/src/chat/__tests__/chat-css-contract.test.ts`

**Interfaces:**
- Consumes: the class names Tasks 1–3 declared — `chat-tool-sentence`,
  `chat-tool-verb`, `chat-guide-note`, `chat-guide-rule`,
  `chat-filter-values`, `chat-search-summary`, `chat-doc-group`,
  `chat-doc-head`, `chat-doc-title`, `chat-doc-text`, `chat-doc-pages`.
  **Read each task's report for the final list — do not trust this one.**

- [ ] **Step 1: Write the failing test**

Append to `webapp/src/chat/__tests__/chat-css-contract.test.ts`:

```ts
  // ------------------------------------------------------------------
  // 2026-08-16 — TC22. The card must be the SAME WIDTH standalone and nested.
  // It was not, and the gap was large: `.chat-bubble` sets `font-size: 14px`
  // and `max-width: 65ch`, so its `ch` resolves at 14px AND a nested card
  // loses a further 32px of padding plus 2px of border — while the standalone
  // `.chat-tool-group` also said `65ch` but inherited the document's 16px, a
  // BIGGER unit. The standalone card was ~100px wider and shrank the instant
  // an answer arrived and it moved inside the bubble.
  //
  // This asserts the mechanism that makes them equal; the real acceptance
  // test is measuring both in a browser, which jsdom cannot do.
  it("the standalone card states the bubble's own measure, not a wider one", () => {
    const rule = bareRule(".chat-tool-group");
    expect(rule).toMatch(/font-size:\s*14px/);
    expect(rule).toMatch(/max-width:\s*calc\(65ch\s*-\s*34px\)/);
    // And the bubble it must match is still 65ch at 14px.
    const bubble = bareRule(".chat-bubble");
    expect(bubble).toMatch(/font-size:\s*14px/);
    expect(bubble).toMatch(/max-width:\s*65ch/);
    expect(bubble).toMatch(/padding:\s*10px 16px/);
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd webapp && npx vitest run src/chat/__tests__/chat-css-contract.test.ts`
Expected: FAIL — `.chat-tool-group` has no `font-size` and its `max-width` is a
bare `65ch`.

- [ ] **Step 3: Fix the width**

In `webapp/src/styles/app.css`, change the `.chat-tool-group` rule:

```css
/* ONE measure in both contexts (spec TC22, 2026-08-16). `.chat-bubble` is
   `65ch` at its own `font-size: 14px`, and a card nested inside it loses a
   further 32px of side padding and 2px of border — so the standalone card must
   state that same number itself. It used to say a bare `65ch` while inheriting
   the document's 16px, which makes `ch` a BIGGER unit: the standalone card was
   about 100px wider and visibly shrank the moment an answer arrived and it
   moved inside the bubble. Declaring `font-size: 14px` here is what makes the
   `ch` units comparable; it changes nothing visible, because `.chat-tool-head`
   sets its own 12.5px. */
.chat-tool-group { font-size: 14px; border-radius: var(--r-sm); border: 1px solid var(--line); background: var(--card); max-width: calc(65ch - 34px); overflow: hidden; }
```

- [ ] **Step 4: Style the new views**

Add rules for every class Tasks 1–3 declared, in the existing tool-card
neighbourhood of the file, following the surrounding conventions: 12.5px body
type (below the 14px prose so the card reads as an annotation), `--ink-2` for
text and `--ink-3` for muted, `--r-sm` corners, no new colour tokens.

Each non-obvious rule carries a WHY comment. In particular
`.chat-tool-sentence` must keep the single-line ellipsis truncation the header
had before (`min-width: 0; flex: 1 1 auto; overflow: hidden; text-overflow:
ellipsis; white-space: nowrap`), or a long query will wrap the row to two lines.

- [ ] **Step 5: Run the full suite**

Run: `cd webapp && npm test` — must be ≥ 1010 passing, 0 failing
Run: `cd webapp && npm run build` — exit 0

- [ ] **Step 6: Commit**

```bash
git add webapp/src/styles/app.css webapp/src/chat/__tests__/chat-css-contract.test.ts
git commit -m "tool card: styles for the new views, and one width in both contexts (TC22)"
```

---

### Task 5: Gates

- [ ] **Step 1: Suites**

```bash
cd webapp && npm test && npm run build
cd .. && uv run pytest -q
```
Expected: vitest ≥ 1010 / 0 failing, build exit 0, pytest 3151 passed / 5
skipped. **Re-measure rather than trusting these numbers** — master moves.

- [ ] **Step 2: No eval run**

Nothing under `retrieval/`, `ingest/`, `chunking/`, `citation/` or
`harness/system-prompt.md` was touched.

- [ ] **Step 3: Grep for leaked jargon across the built bundle**

```bash
cd webapp && npm run build && grep -o "agency_canonical_id\|top score\|bm25" dist/assets/*.js | sort -u
```
Any hit in analyst-facing copy is a defect. Hits inside filter KEYS the client
sends to the server are fine — read each one before dismissing it.

- [ ] **Step 4: Browser pass**

Rebuild, then at `http://127.0.0.1:9300/ai` check, in order:

| # | Check |
|---|---|
| 1 | A one-search answer: header reads `Searched for “…”`, verb bold |
| 2 | A multi-search answer: `Searched for “…” and N more` |
| 3 | **Width — the specific ask.** Watch a search run, then watch the card move into the bubble as the answer arrives. It must not change width. Measure if unsure |
| 4 | Open a search: document blocks, page chips, no scores, no repeated heading |
| 5 | All four icons render whole and legible at their real size — not cropped, which is what a missed `viewBox` looks like |
| 6 | Ask for a memo: the style-guide card has a book icon and readable rules, and says the guidance is advice |
| 7 | A failed call still shows nothing on the collapsed card, and its failure inside the expansion |

---

## Self-review

**Spec coverage.** TC13 → Task 1. TC14 → Task 1. TC15 → Task 2. TC16 → Task 3.
TC17 → Task 3. TC18 → Task 3. TC19 → Task 3. TC20 → Task 2. TC21 → Task 2.
TC22 → Task 4. Part 1's TC9 is re-guarded in Task 1 Step 6.

**Type consistency.** `toolHeaderSentence` returns `{verb, rest}` in Task 1 and
is consumed under those names in the same task. `toolGlyph` moves to a 24×24
viewBox in Task 2, and Task 2 Step 3 explicitly requires updating every caller
— that cross-file change is the plan's single biggest silent-breakage risk.
`stripLeadingHeading` and `groupByDocument` are local to Task 3.

**Known risk the plan cannot remove.** Task 2 and Task 3 both append to
`tool-body.test.tsx` from parallel worktrees. Both are instructed to append one
contiguous block at the end. If git conflicts there, resolve by keeping both
blocks — no assertion in either depends on the other.
