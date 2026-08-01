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

const markdownContentSrc = readFileSync(
  resolve(process.cwd(), "src/chat/MarkdownContent.tsx"),
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
    // Match a rule DEFINITION (selector + optional whitespace + `{`), not any
    // textual mention — a plain \b scan already tripped once on this exact
    // string appearing inside a comment, which is not a live rule.
    expect(css).not.toMatch(/\.chat-error-body\s*\{/);
  });

  it("no third-party syntax theme — hljs classes are styled locally in navy", () => {
    // Replaces highlight.js's github.css import (a fifth independent color
    // source on a monochrome-navy page) with a handful of house-token rules.
    expect(css).toMatch(/\.chat-md \.hljs-keyword/);
    expect(markdownContentSrc).not.toMatch(/highlight\.js\/styles/);
  });

  // Task 13: radii + rhythm sweep. The scan range below covers BOTH the chat
  // block and the pdf block — deliberately, not by accident: the pdf viewer's
  // 6px zoom-button/skeleton radii are part of this same sweep (Step 3 of the
  // brief touches .pdf-zoom-btn/.pdf-open-original/.pdf-skeleton alongside the
  // chat rules). Following the "one content measure" test's now-established
  // style above: locate regions by their section-comment markers rather than
  // inventing a third lookup approach. Named for what it actually bounds
  // (end of the chat+pdf region, at the start of page-upload) — the brief's
  // own sample called this same offset `pdfStart`, which describes neither
  // what it points at (page-upload's marker, not pdf's) nor its role here
  // (an end bound, not a start).
  it("no off-scale radii survive in the chat+pdf blocks (16/12/pill + 4px tail/chips only)", () => {
    const chatStart = css.indexOf("/* ===== chat =====");
    const chatAndPdfEnd = css.indexOf("/* ===== page-upload");
    expect(chatStart, "start-of-chat marker must exist").toBeGreaterThan(-1);
    expect(
      chatAndPdfEnd,
      "start-of-page-upload marker must exist",
    ).toBeGreaterThan(chatStart);
    const block = css.slice(chatStart, chatAndPdfEnd);
    // 6px, 8px and 10px radii were the retired app's scale. Exempt by
    // selector, not by value, so this can't be satisfied by accident:
    // .pdf-highlight/.pdf-cited-mark (2px, page marks not UI chrome) and
    // .chat-cite-sup/.chat-cite-pill (4px, allowed) are excluded before the
    // sweep is checked.
    const swept = block
      .replace(/\.pdf-highlight\s*\{[^}]*\}/g, "")
      .replace(/\.pdf-cited-mark\s*\{[^}]*\}/g, "")
      .replace(/\.chat-cite-sup\s*\{[^}]*\}/g, "")
      .replace(/\.chat-cite-pill\s*\{[^}]*\}/g, "");
    expect(swept).not.toMatch(/border-radius:\s*(6|8|10)px/);
  });

  it("turn rhythm is on one scale: 24 between turns, 8 within", () => {
    expect(ruleFor(".chat-thread-column")).toMatch(/gap:\s*24px/);
    expect(ruleFor(".chat-turn")).toMatch(/gap:\s*8px/);
  });

  it("the assistant bubble is on the token radius scale with a squared tail corner, no triangle carats", () => {
    expect(ruleFor(".chat-bubble")).toMatch(/border-radius:\s*var\(--r-md\)/);
    // The triangle-carat pseudo-elements are gone; the tail is now just one
    // squared corner on the bubble itself.
    expect(css).not.toMatch(/\.chat-bubble\.has-tail::before/);
    expect(css).not.toMatch(/\.chat-bubble\.has-tail::after/);
    expect(ruleFor(".chat-bubble.has-tail")).toMatch(
      /border-bottom-left-radius:\s*4px/,
    );
  });

  it("the user bubble is solid navy, not the retired app's az-gold accent", () => {
    const rule = ruleFor(".chat-user-bubble");
    expect(rule).toMatch(/background:\s*var\(--navy\)/);
    expect(rule).not.toMatch(/var\(--az-gold\)/);
    expect(rule).toMatch(/border-bottom-right-radius:\s*4px/);
  });

  it("hover language matches the browse pages: azure border/-d text, brightness on CTAs", () => {
    expect(ruleFor(".chat-suggestion:hover")).toMatch(
      /color:\s*var\(--az-gold-d\)/,
    );
    expect(ruleFor(".chat-send:hover:not(:disabled)")).toMatch(
      /filter:\s*brightness/,
    );
  });

  // Review finding: the Task 13 hover sweep gave EVERY .chat-cite-inline —
  // including .is-failed ones — the azure "valid" tint on hover. The red
  // wavy underline survived, but a failed citation hovering into a
  // success-colored highlight reads as "this one's fine", which is exactly
  // backwards: a failed citation must look unmistakably failed, always,
  // Invariant-2 territory (citations are verified, not just emitted; a
  // failure must never be dressed up as a pass). The sibling .chat-cite-pill
  // already gets this right (its .is-failed rule overrides the hover's
  // border-color at equal specificity via source order); .chat-cite-inline
  // needs its own guard because it never had an .is-failed color override to
  // begin with.
  it("a failed inline citation's hover never carries the success (gold) tint", () => {
    const failedHover = ruleFor(".chat-cite-inline.is-failed:hover");
    expect(failedHover).toMatch(/background:\s*var\(--chat-danger-tint\)/);
    expect(failedHover).not.toMatch(/az-gold/);
  });

  // Task 15: chat-first split + sub-860 drawer (replaces the hard 50/50 and
  // the old display:none breakpoint).
  it("split is chat-first, and small screens get a drawer instead of nothing", () => {
    expect(css).toMatch(/\.ai-panel-main\.has-source \.ai-panel-chat\s*\{[^}]*flex:\s*0 0 clamp\(/);
    // The old behavior hid the source entirely below 860px.
    const media = css.slice(css.indexOf("@media (max-width:860px)"));
    expect(media.slice(0, media.indexOf("}") + 200)).not.toMatch(/\.ai-panel-source\s*\{\s*display:\s*none/);
  });

  it("cited text is capped in px, not vh", () => {
    expect(ruleFor(".pdf-cited-text")).not.toMatch(/vh/);
  });

  // Task 16: the mascot used to clip mid-body against the column edge
  // (right: calc(50% + 400px) never reacted to the source panel opening or a
  // narrow window). It now docks/undocks off a container query on its own
  // scroller instead of a fixed offset that assumed a fixed-width viewport.
  it("the mascot hides via container query instead of clipping off-canvas", () => {
    expect(css).toMatch(/container-type:\s*inline-size/);
    expect(css).toMatch(
      /@container[^{]*max-width[^{]*\{[^}]*\.chat-mascot-slot[^}]*display:\s*none/s,
    );
  });

  // The 440px in the old clamp was hand-measured chrome height that every
  // later task (footer restyle, floating composer, etc.) silently
  // invalidated. The welcome mascot must size off something that can't drift
  // out from under it, not a re-measured constant.
  it("the welcome mascot clamp no longer hardcodes the chrome height", () => {
    expect(ruleFor(".chat-welcome-mascot")).not.toMatch(/440px/);
  });
});
