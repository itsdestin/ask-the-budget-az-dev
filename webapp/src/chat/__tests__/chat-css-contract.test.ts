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

const chatThreadSrc = readFileSync(
  resolve(process.cwd(), "src/chat/ChatThread.tsx"),
  "utf-8",
);

/** The stylesheet with every /* … *\/ comment removed.
 *
 *  WHY: several assertions below prove a declaration is ABSENT, and the
 *  comments deliberately NAME those declarations (a WHY note explaining why
 *  CSS containment must never come back has to say the words "container-type"
 *  to be useful). A raw substring scan would read that prose as a live rule
 *  and pass — or fail — for the wrong reason. Strip comments, then scan. */
const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");

function escapeRe(s: string): string {
  return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

/** Body of the rule whose selector list ENDS in `selector` immediately before
 *  the `{`. Unlike `ruleFor` above this cannot be fooled by a comment mention
 *  or by a longer selector that merely starts with the same characters. */
function bareRule(selector: string): string {
  const match = bare.match(
    new RegExp(escapeRe(selector) + "\\s*\\{([^}]*)\\}"),
  );
  expect(match, `selector ${selector} must exist`).not.toBeNull();
  return match![1];
}

/** The numeric z-index declared by a rule, for order comparisons. */
function zIndexOf(selector: string): number {
  const m = bareRule(selector).match(/z-index:\s*(-?\d+)/);
  expect(m, `${selector} must declare a numeric z-index`).not.toBeNull();
  return Number(m![1]);
}

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

/** EVERY rule body whose selector list ends in `selector`, concatenated.
 *
 *  Unlike `bareRule`, which returns the first match only. This stylesheet
 *  deliberately splits a selector across thematic blocks — `.ai-panel-chat`
 *  carries its flex sizing in the panel block, `position:relative` in the
 *  floating-chrome block, and its background in the ground block — so a
 *  first-match lookup silently asserts against whichever one happens to come
 *  first in the file. */
function bareRulesFor(selector: string): string {
  const re = new RegExp(escapeRe(selector) + "\\s*\\{([^}]*)\\}", "g");
  const bodies = [...bare.matchAll(re)].map((m) => m[1]);
  expect(bodies.length, `selector ${selector} must exist`).toBeGreaterThan(0);
  return bodies.join("\n");
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
    expect(ruleFor(".ask-send:hover:not(:disabled)")).toMatch(
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

  // ------------------------------------------------------------------
  // FINAL REVIEW — CRITICAL 1. The citation tooltip is position:fixed so it
  // escapes the thread scroller's clip (test above). `position: fixed` only
  // resolves against the VIEWPORT while no ancestor establishes a containing
  // block for it — and `container-type` (any value) and `contain` (layout /
  // paint / strict / content) BOTH do exactly that, per CSS Containment 2
  // §3.1. An ancestor with either one silently re-clips the tooltip inside
  // the scroller AND turns that scroller into a stacking context, so the
  // tooltip's z-index:80 no longer clears the sticky site header (50) or the
  // sub-860 source drawer (60).
  //
  // That is not a cosmetic regression: `.chat-cite-fail` — the READABLE
  // REASON a citation failed validation — lives inside the tooltip. A
  // clipped tooltip is an Invariant 2 failure (citations are verified, not
  // merely emitted; a failure must stay legible), which is why this is
  // pinned as a contract rather than left to review.
  //
  // Scoped to the whole stylesheet on purpose: the tooltip's ancestor chain
  // runs .chat-cite-* -> .chat-md -> .chat-bubble -> .chat-turn ->
  // .chat-thread-column -> .chat-thread-anchor -> .chat-thread-scroll ->
  // .chat-thread -> .ai-panel-chat -> .ai-panel-main -> .ai-panel ->
  // .page-ai -> body, i.e. it crosses every section of this file, so
  // enumerating selectors would leave gaps. This app uses no CSS containment
  // anywhere today; if a future page genuinely needs it, narrow this test
  // then — deliberately, with the tooltip re-checked.
  //
  // Containment isn't the only way an ancestor can become a containing block
  // for position:fixed: `transform`, `filter`, `backdrop-filter`,
  // `perspective`, and `will-change` (naming any of the former) on an
  // ancestor do the same thing. This stylesheet already has a
  // `backdrop-filter` on `.ai-bottom-chrome` — a sibling of the thread today,
  // harmless, but one edit that moves a blur onto `.chat-thread` or
  // `.ai-panel-chat` would silently re-clip the tooltip the same way
  // container-type did. This test does NOT assert against those five
  // properties — several are legitimately used elsewhere in this file, so a
  // blanket check would false-fail. Known gap, not an oversight.
  it("no ancestor of the citation tooltip declares CSS containment", () => {
    expect(
      bare,
      "container-type makes the element a containing block for position:fixed — it re-clips the citation tooltip",
    ).not.toMatch(/container-type\s*:/);
    expect(
      bare,
      "contain: layout/paint/strict/content does the same thing container-type does",
    ).not.toMatch(/(^|[;{\s])contain\s*:/);
    expect(
      bare,
      "container: <name> / inline-size is the shorthand for container-type — same hazard, different spelling",
    ).not.toMatch(/(^|[;{\s])container\s*:/);
    expect(
      bare,
      "content-visibility: auto/hidden applies layout+paint containment per the CSS Containment spec — same hazard as container-type",
    ).not.toMatch(/content-visibility\s*:\s*(auto|hidden)/);
  });

  // Task 16 (review pass), amended by the final review: the mascot used to
  // clip mid-body against the column edge (a fixed right offset never
  // reacted to the source panel opening or a narrow window). The dock/undock
  // is now driven from ChatThread.tsx's ResizeObserver — NOT from a CSS
  // container query, which would have re-broken the tooltip above.
  it("the mascot docks from JS, and the CSS only supplies the hidden state", () => {
    expect(chatThreadSrc).toMatch(/ResizeObserver/);
    expect(chatThreadSrc).toMatch(/is-cramped/);
    expect(css).toMatch(/\.chat-mascot-slot\.is-cramped/);
    // No @container rule may come back — the whole point of moving the
    // measurement into JS is that this stylesheet stays containment-free.
    expect(bare).not.toMatch(/@container/);
  });

  // The shipped 1040px was a rounded guess ("--ai-col + the widest scene +
  // gutters") that turned out too low for ALL THREE scenes — a real number
  // pinned here so a future edit to something obviously wrong (say, 100px)
  // fails loudly instead of silently reopening the clip bug.
  //
  // The number and its derivation are UNCHANGED by the final review; only
  // WHO measures moved (a CSS @container -> ChatThread.tsx's ResizeObserver,
  // because container-type re-clipped the citation tooltip). A
  // ResizeObserver's `contentRect.width` is the observed element's CONTENT
  // box — the exact same quantity `@container … (inline-size)` reported —
  // so the threshold carries over verbatim rather than needing a re-derive.
  //
  // Derivation (re-derive this yourself before ever touching the number):
  //   .chat-mascot-slot sits in .chat-thread-anchor, inside
  //   .chat-thread-scroll's content box — so this ignores that scroller's own
  //   16px+16px padding, which is the conservative direction: a real border
  //   between padding and content-box clip would buy ~16px more slack, not
  //   less. Call that content box width A.
  //   right: calc(50% + var(--ai-col)/2 + 16px) puts the slot's untransformed
  //   right edge a constant 16px left of .chat-thread-column's left edge, for
  //   ANY A (the two halves of A always cancel out — verified by algebra, not
  //   assumed).
  //   Each scene's `transform: translate(tx, _)` shifts that right edge
  //   right by tx, and the div's shrink-to-fit width equals the rendered
  //   scene width (sceneWidth). No clipping requires:
  //     A >= 800 + 2 * (sceneWidth - tx)
  //   where 800 = 2 * (384 + 16) (half the 768px column, doubled, plus the
  //   16px gap doubled).
  //   Per scene, reading tx straight from the .is-* rules below and
  //   sceneWidth from each component's actual rendered size:
  //     idle:       Mascot size="small"          = 120w,  tx=5  -> 1030
  //     thinking:   MascotTyping  (360x410 vB @ 210px tall) ≈184.4w, tx=54 -> ~1061
  //     presenting: MascotPresenting (320x400 vB @ 210px tall) = 168w, tx=26 -> 1084
  //   presenting BINDS despite not being the widest scene, because its
  //   translate offset is the smallest of the three. 1084 is therefore the
  //   smallest threshold that clips NO scene; anything lower reopens the
  //   exact bug this test exists to catch.
  it("the dock threshold is the real per-scene no-clip requirement (1084px, presenting binds)", () => {
    expect(
      chatThreadSrc,
      "threshold must be exactly 1084px — see the derivation comment above this test",
    ).toMatch(/MASCOT_DOCK_PX\s*=\s*1084/);
  });

  // Mascot/MascotTyping/MascotPresenting's role="img" aria-label ("JLBC
  // budget assistant — searching" / "— presenting results") is the ONLY
  // place the assistant's searching/presenting state is exposed to
  // assistive tech anywhere on this page — there is no aria-live region or
  // textual status in ChatThread.tsx. display:none removes an element from
  // the accessibility tree entirely, so hiding the mascot that way would
  // silently take away the one status indicator a screen-reader user has —
  // worse than the old clipping bug, which at least left it in the tree.
  // Fixed with the classic visually-hidden clip recipe instead: gone from
  // the screen, still present (and readable) for assistive tech.
  it("the docked state visually hides the mascot without removing it from the accessibility tree", () => {
    const body = bareRule(".chat-mascot-slot.is-cramped");
    expect(body, "must not use display:none — that strips role=img from the a11y tree").not.toMatch(
      /display:\s*none/,
    );
    // The standard sr-only/visually-hidden recipe: shrunk to 1x1px and
    // clipped to a zero-area rect, never display:none/visibility:hidden
    // (both of which assistive tech treats as absent, not "hidden but
    // present").
    expect(body).toMatch(/width:\s*1px/);
    expect(body).toMatch(/height:\s*1px/);
    expect(body).toMatch(/clip:\s*rect\(0,?\s*0,?\s*0,?\s*0\)/);
    expect(body).not.toMatch(/visibility:\s*hidden/);
  });

  // The 440px in the old clamp was hand-measured chrome height that every
  // later task (footer restyle, floating composer, etc.) silently
  // invalidated. The welcome mascot must size off something that can't drift
  // out from under it, not a re-measured constant.
  it("the welcome mascot clamp no longer hardcodes the chrome height", () => {
    expect(ruleFor(".chat-welcome-mascot")).not.toMatch(/440px/);
  });

  // ------------------------------------------------------------------
  // FINAL REVIEW — IMPORTANT 2. One flex row, one auto margin. When BOTH
  // `.pdf-head-spacer` and `.pdf-open-original` declare margin-left:auto the
  // row's free space is split evenly BETWEEN them, so the zoom controls stop
  // at neither edge and float mid-header. `.pdf-head-spacer` exists for
  // exactly this job, so the duplicate on the button is what goes. Shared
  // surface: SourceView renders in AI Mode AND in the search page's source
  // drawer, so this was two pages wrong, not one.
  it("the merged PDF header has exactly one auto-margin spacer", () => {
    expect(bareRule(".pdf-head-spacer")).toMatch(/margin-left:\s*auto/);
    expect(
      bareRule(".pdf-open-original"),
      "a second margin-left:auto splits the free space and floats the zoom controls mid-row",
    ).not.toMatch(/margin-left:\s*auto/);
  });

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

  // ------------------------------------------------------------------
  // FINAL REVIEW — IMPORTANT 5. Stacking order inside `.ai-panel-chat`.
  // `.ai-bottom-chrome` carries a z-index, which makes it a stacking context,
  // so `.ai-tier-pop`'s own z-index is TRAPPED inside it and the whole chrome
  // competes with its siblings at the chrome's number. The jump pill was
  // above that number, so the tier explainer — which opens upward into
  // exactly the space the pill occupies — was painted over. The pill only
  // ever needs to clear thread CONTENT (the mascot slot is the highest thing
  // in there), never the chrome.
  it("the jump pill sits above thread content but below the bottom chrome", () => {
    const jump = zIndexOf(".chat-jump");
    const chrome = zIndexOf(".ai-bottom-chrome");
    const mascot = zIndexOf(".chat-mascot-slot");
    expect(jump, "the tier explainer opens into the pill's space").toBeLessThan(
      chrome,
    );
    expect(jump).toBeGreaterThan(mascot);
  });

  // ------------------------------------------------------------------
  // FINAL REVIEW — MINOR. --ai-col is meant to be THE content measure; a
  // hardcoded 400px (= 768/2 + 16) silently desynchronises the mascot the
  // day someone changes the token.
  it("the mascot offset is expressed in the --ai-col token, not a 400px literal", () => {
    const rule = bareRule(".chat-mascot-slot");
    expect(rule).toMatch(/var\(--ai-col\)/);
    expect(rule).not.toMatch(/400px/);
  });

  // ------------------------------------------------------------------
  // FINAL REVIEW — MINOR. Adjacent `.chat-tool` siblings only ever exist
  // inside `.chat-tool-group-body` (a run of consecutive tool calls always
  // coalesces into a group), and that body sets its own flex `gap`, so the
  // sibling margin never applied anywhere — it was dead the moment ToolGroup
  // shipped. The rule and the neutraliser that cancelled it go together;
  // keeping either alone would just be confusing.
  it("the unreachable adjacent-tool margin and its neutraliser are both gone", () => {
    expect(bare).not.toMatch(/\.chat-tool\s*\+\s*\.chat-tool\s*\{/);
    expect(bareRule(".chat-tool-group-body")).toMatch(/gap:\s*4px/);
  });

  // ------------------------------------------------------------------
  // 2026-08-02. The bottom chrome is one MEASURED block but only its inner
  // panel is opaque, so the starter chips float on the thread's background.
  // Putting a background back on `.ai-bottom-chrome` would silently swallow
  // them into the composer container again — the exact thing Destin asked to
  // undo — with no test failing anywhere else.
  it("nothing at the bottom of the column paints a card-coloured slab", () => {
    // REWRITTEN 2026-08-02. This used to assert the opposite — that
    // `.ai-chrome-panel` painted an opaque card with a top border — back when
    // the point was only to keep the starter chips OUTSIDE that panel. The
    // panel itself then cut a hard white band across the bottom of the ground,
    // so it is gone: the chrome fades into the ground instead, and the chips,
    // the pill and the footer all float on one continuous surface.
    //
    // The intent that survives from the old spec is the same one: nothing down
    // here may re-acquire a slab, because a slab is what breaks the ground.
    const panel = bareRulesFor(".ai-chrome-panel");
    expect(panel).not.toMatch(/var\(--card\)/);
    expect(panel).not.toMatch(/border-top/);

    const chrome = bareRulesFor(".ai-bottom-chrome");
    // The fade must START fully transparent, or the last message stops
    // dissolving into the ground and slides under a visible edge again.
    expect(chrome).toMatch(/linear-gradient\(180deg,\s*transparent 0%/);
    // …and END on the ground's own bottom tone, or the seam shows.
    expect(chrome).toMatch(/rgba\(43,47,99,\.105\)/);
    expect(chrome).toMatch(/var\(--canvas\)/);
  });

  // The obvious way to fade a scroller is `mask-image` on the scroller. It is
  // also a re-run of the container-type Critical: masking clips everything the
  // element paints, including position:fixed descendants, so the citation
  // tooltip — and the panel saying WHY a citation failed — would be cut off
  // again, and both existing containment specs would stay green.
  it("the thread scroller is never masked or clipped", () => {
    const scroller = bareRulesFor(".chat-thread-scroll");
    expect(scroller).not.toMatch(/mask/);
    expect(scroller).not.toMatch(/clip-path/);
  });

  // The chrome is absolutely positioned across the chat column; at right:0 it
  // painted over the bottom of the thread's own scrollbar, so the bar looked
  // half-drawn. AiModePanel measures the real bar width into --ai-scrollbar.
  it("the bottom chrome insets itself off the thread's scrollbar", () => {
    expect(bareRule(".ai-bottom-chrome")).toMatch(
      /right:\s*var\(--ai-scrollbar,\s*0px\)/,
    );
  });

  // ------------------------------------------------------------------
  // 2026-08-02. The composer is now the ask bar, and its whole design claim is
  // that it IS Home's hero search field — same pill, same fill, same focus
  // ring — so the app has one search-input identity instead of three. That
  // claim is only true while the declarations actually match, and nothing else
  // would fail if they silently drifted apart.
  it("the ask bar wears Home's search-field recipe", () => {
    const home = bareRule(".page-home .search-field");
    const ask = bareRule(".ask-bar");
    for (const decl of [
      /background:\s*var\(--canvas\)/,
      /border:\s*2px solid var\(--line\)/,
      /border-radius:\s*var\(--r-pill\)/,
    ]) {
      expect(home, `home must set ${decl}`).toMatch(decl);
      expect(ask, `the ask bar must match home on ${decl}`).toMatch(decl);
    }
    const homeFocus = bareRule(".page-home .search-field:focus-within");
    const askFocus = bareRule(".ask-bar:focus-within");
    expect(homeFocus).toMatch(/border-color:\s*var\(--navy\)/);
    expect(askFocus).toMatch(/border-color:\s*var\(--navy\)/);
    expect(askFocus).toMatch(/box-shadow:\s*0 0 0 4px var\(--navy-100\)/);
  });

  // The controls the ask bar replaced. Their CSS is deleted, not orphaned —
  // this file's own convention is that dead page-scoped CSS does not survive
  // the markup that used it.
  it("no CSS survives for the retired tier and corpus switches", () => {
    for (const dead of [
      ".ai-tierswitch",
      ".ai-tierseg",
      ".ai-tier-pop",
      ".ai-tier-info",
      ".ai-controls",
      ".ai-corpus-chip",
      ".ai-corpus-note",
      ".chat-input",
    ]) {
      expect(bare, `${dead} has no markup left to style`).not.toContain(dead);
    }
  });

  // ------------------------------------------------------------------
  // 2026-08-02, written because it already happened. Removing the retired
  // `.chat-input` block took `.chat-welcome*` with it — the two were adjacent,
  // the deletion was by range, and the welcome screen lost its layout with
  // nothing failing anywhere. Every other rule in this file has a component
  // that renders it; these are the ones whose ABSENCE is silent, because a
  // flex container that stops existing just leaves its children in the flow
  // looking approximately fine.
  it("the welcome screen still has layout rules at all", () => {
    const welcome = bareRule(".chat-welcome");
    expect(welcome, "the mascot/greeting row").toMatch(/display:\s*flex/);
    expect(welcome).toMatch(/flex-direction:\s*row/);
    // margin:auto inside the scroller is what vertically centres the whole
    // empty state; without it the mascot pins to the top of the thread.
    expect(welcome).toMatch(/margin:\s*auto/);
    expect(bareRule(".chat-welcome-mascot")).toMatch(/max-height/);
  });

  // The greeting is a speech bubble aimed at the mascot beside it. The app's
  // bubble idiom is a squared CORNER, never a triangle carat — Task 13 deleted
  // those from .chat-bubble for hanging outside the box; regrowing one here
  // would undo that decision in the most visible place on the page.
  it("the welcome bubble points at the mascot with a corner, not a carat", () => {
    const bubble = bareRule(".chat-welcome-bubble");
    expect(bubble).toMatch(/border-bottom-left-radius:\s*4px/);
    expect(bare).not.toMatch(/\.chat-welcome-bubble(::before|::after)/);
  });

  // 2026-08-02. The thread's ground is painted on `.ai-panel-chat` — the
  // non-scrolling container — so it stays put while messages move under it.
  // The scroller sits ON TOP of it and must stay transparent: re-adding
  // `background: var(--canvas)` there covers the gradient completely, and
  // NOTHING else looks wrong. The page just goes back to being a flat sheet,
  // which is the exact thing this replaced.
  it("the thread ground is on the panel, and the scroller does not cover it", () => {
    const ground = bareRulesFor(".ai-panel-chat");
    expect(ground, "the ground lives on the non-scrolling container").toMatch(
      /radial-gradient/,
    );
    expect(ground).toMatch(/var\(--canvas\)/);
    const scroller = bareRule(".chat-thread-scroll");
    expect(scroller).toMatch(/background:\s*transparent/);
    expect(scroller).not.toMatch(/background:\s*var\(--canvas\)/);
  });

  // S12: one palette, tokens copied verbatim, no invented entries. The washes
  // are alpha-composited --navy (#2b2f63 = 43,47,99), the same vocabulary the
  // mockup's own subhero used — so no NEW hue may appear in them.
  it("the ground introduces no colour that is not navy", () => {
    const ground = bareRulesFor(".ai-panel-chat");
    for (const rgba of ground.match(/rgba\([^)]*\)/g) ?? []) {
      expect(rgba, `${rgba} is not the navy token`).toMatch(/rgba\(43,\s*47,\s*99,/);
    }
  });

  // The stop button's ring is the ONLY indication that a turn is still
  // generating — there is no separate spinner anywhere. If the animation is
  // dropped the button silently becomes a static circle and the composer stops
  // reporting that anything is happening.
  it("the stop button spins while generating, and halts rather than vanishing", () => {
    const ring = bareRule(".ask-stop::before");
    expect(ring).toMatch(/animation:\s*ask-spin/);
    expect(ring).toMatch(/border-top-color:\s*var\(--chat-danger\)/);
    expect(bare).toMatch(/@keyframes\s+ask-spin\s*\{[^}]*rotate\(360deg\)/);
    // Reduced motion stops the rotation but keeps a complete ring, so the
    // control still reads as active-and-interruptible.
    const reduced = bare.slice(bare.indexOf("@media (prefers-reduced-motion: reduce){\n  .ask-stop"));
    expect(reduced.slice(0, 200)).toMatch(/animation:\s*none/);
    expect(reduced.slice(0, 200)).not.toMatch(/display:\s*none/);
  });

  // The pip is the only thing standing between an analyst and invisible state:
  // Deep Research costs ~44x a Standard answer and the corpus decides which
  // documents a citation can come from, and BOTH toggles live inside a menu
  // that closes. Its ring fakes a cut-out, so it has to follow the bar's fill.
  it("the tools pip is drawn outside the icon and tracks the bar's fill", () => {
    const pip = bareRule(".ask-pip");
    expect(pip).toMatch(/position:\s*absolute/);
    // Negative offsets = it sits ON the icon's edge, like a badge.
    expect(pip).toMatch(/top:\s*-\d/);
    expect(pip).toMatch(/right:\s*-\d/);
    expect(bareRule(".ask-bar:focus-within .ask-pip")).toMatch(
      /border-color:\s*var\(--card\)/,
    );
  });

  // Reported by Destin 2026-08-11, testing in a real browser: pointing at any
  // row in the history rail lit up TWO rows. `:hover` and `.is-active` both
  // painted `background:var(--card)` — identical — so the hovered row became
  // indistinguishable from the open conversation, and the rail stopped
  // answering the one question it exists to answer: which chat am I in?
  //
  // The fix suppresses the ACTIVE row's highlight while the pointer is over
  // some OTHER row, rather than restyling hover. Two reasons that direction is
  // right: hover already reads correctly on its own, and the alternative
  // (giving hover its own tint) leaves two lit rows and just makes them
  // different colours, which is the same defect with extra steps.
  //
  // Pinned in CSS rather than in jsdom because jsdom applies no stylesheet and
  // cannot hover — the whole class of defect this file exists for.
  it("only one history-rail row is highlighted at a time", () => {
    // The precondition that made the defect possible. If these two ever stop
    // matching, re-read the fix below before assuming it is still needed.
    expect(bareRule(".history-rail-item:hover")).toMatch(
      /background:\s*var\(--card\)/,
    );
    expect(bareRule(".history-rail-item.is-active")).toMatch(
      /background:\s*var\(--card\)/,
    );

    // Hovering the list de-highlights the active row UNLESS it is the row
    // under the pointer — `:not(:hover)` is what keeps the open chat lit when
    // you point at it, which is the common case.
    const yielded = bareRule(
      ".history-rail-list:hover .history-rail-item.is-active:not(:hover)",
    );
    expect(yielded).toMatch(/background:\s*transparent/);
    // The shadow is half of what reads as "selected"; leaving it would keep a
    // lifted, shadowed row beside the hovered one.
    expect(yielded).toMatch(/box-shadow:\s*none/);

    // The title's gold is the other half, and it is the louder half.
    expect(
      bareRule(
        ".history-rail-list:hover .history-rail-item.is-active:not(:hover) .history-rail-chat-title",
      ),
    ).toMatch(/color:\s*var\(--ink\)/);
  });

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
});
