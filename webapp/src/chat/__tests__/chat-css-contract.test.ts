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
  resolve(process.cwd(), "src/styles/app.css"),
  "utf-8",
);

/** The full rule body for a selector (first occurrence).
 *  NOTE: this is a plain `indexOf`, so it finds the first substring match —
 *  it would silently return the WRONG rule if a later selector CONTAINS an
 *  earlier one (e.g. `.chat-tool-head` before a lookup for `.chat-tool`) or
 *  if the target selector only appears wrapped in an `@media` block. Correct
 *  for every selector this file looks up today; re-verify by eye if you add
 *  a selector that is a prefix of another one. */
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

  it("the citation tooltip is fixed-position (escapes the scroller's clip)", () => {
    expect(ruleFor(".chat-cite-tooltip")).toMatch(/position:\s*fixed/);
  });

  it("one content measure: no 768px literals outside the --ai-col definition", () => {
    // Everything that used to hardcode the column width must read the token,
    // so the band, thread, banners and composer share one left edge. Guards
    // exactly the two regions that used to carry 768px literals: the chat
    // block and the AI Mode block. These are NOT adjacent — `pdf`,
    // `page-upload`, and the `page-fiscal-notes` rail sit between them — so a
    // single start..end slice would sweep in unrelated CSS (an admin-page
    // 768px literal, if one is ever added, should not fail an AI Mode
    // contract test; nor should anything from those three unrelated blocks in
    // between). Two disjoint slices, concatenated for scanning, instead of
    // one slice spanning everything from the first marker to the last.
    const chatStart = css.indexOf("/* ===== chat =====");
    const chatEnd = css.indexOf(
      "/* ===== pdf ===== (Plan 4 Task 11 — source viewer + search-page source panel)",
    );
    expect(chatEnd, "end-of-chat-block marker must exist").toBeGreaterThan(
      chatStart,
    );
    const aiStart = css.indexOf(
      "/* ===== AI Mode ===== (Plan 4 Task 12 — the toggle, the tier control, the panel)",
    );
    const aiEnd = css.indexOf(
      "/* ===== page-admin + page-settings (Plan 5 Tasks 8/9) =====",
    );
    expect(aiStart, "start-of-AI-Mode-block marker must exist").toBeGreaterThan(
      -1,
    );
    expect(aiEnd, "end-of-AI-Mode-block marker must exist").toBeGreaterThan(
      aiStart,
    );
    const region =
      css.slice(chatStart, chatEnd) + css.slice(aiStart, aiEnd);
    const literals = region.match(/max-width:\s*768px/g) ?? [];
    expect(literals).toHaveLength(0);
    expect(css).toMatch(/--ai-col:\s*768px/);
  });

  it("the scroller pads for the floating chrome and the welcome state has no second scroller", () => {
    expect(ruleFor(".chat-thread-scroll")).toMatch(/var\(--ai-bottom-chrome/);
    expect(ruleFor(".chat-welcome")).not.toMatch(/overflow/);
  });

  it("micro-labels use the app idiom, not the 10px devtools one", () => {
    for (const sel of [".chat-label", ".chat-more", ".chat-copy", ".chat-error-label"]) {
      const rule = ruleFor(sel);
      expect(rule, sel).toMatch(/font-size:\s*11px/);
      expect(rule, sel).toMatch(/letter-spacing:\s*\.08em/);
    }
  });

  // RESOLVED AMBIGUITY vs the brief: once ErrorBlock renders through
  // CollapsibleBlock (see tool-body.test.tsx), nothing emits
  // className="chat-error-body" any more, so the honest assertion is that
  // the selector is GONE — keeping a CSS rule with no consumer would be dead
  // weight of the exact kind an earlier task deleted on sight.
  it("the error body class was retired along with its nested scrollbar", () => {
    expect(css).not.toMatch(/\.chat-error-body\b/);
  });
});
