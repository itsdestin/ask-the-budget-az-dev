// Header CSS whose correctness depends on things jsdom cannot see.
//
// Both rules below fail SILENTLY when broken: the menu still opens, every link
// still works, and every Header.test.tsx spec still passes — the fill just
// stops moving, or the icon stops having two states. That is the same shape as
// the container-type defect the chat contract file exists for.

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(resolve(process.cwd(), "src/styles/app.css"), "utf-8");
/** Comments stripped: the notes below deliberately NAME the selectors they
 *  explain, and a raw substring scan would read that prose as a live rule. */
const bare = css.replace(/\/\*[\s\S]*?\*\//g, "");

describe("header CSS contract", () => {
  // Destin's ask, verbatim: "on hover, the current page should be
  // pre-selected/filled, but fill should still move when hovering over a
  // different option."
  //
  // Three rules make that work and they tie on specificity (0,3,0), so the
  // ORDER is the whole mechanism: the release rule must come before the hover
  // rule, or the current page keeps its fill and the menu looks stuck.
  it("the tools fill can leave the current item — release before hover", () => {
    const release = bare.indexOf(
      ".nav-tools-pop:hover .nav-tools-item.is-current",
    );
    const hover = bare.indexOf(".nav-tools-pop .nav-tools-item:hover");
    expect(release, "the release rule must exist").toBeGreaterThan(-1);
    expect(hover, "the hover rule must exist").toBeGreaterThan(-1);
    expect(
      hover,
      "the hover rule must come AFTER the release rule — they tie on specificity, so source order is what decides which wins, and losing this pins the fill to the current page",
    ).toBeGreaterThan(release);
    // Keyboard gets the same treatment; a menu that only responds to a pointer
    // is a menu a keyboard user cannot read the state of.
    expect(bare).toContain(".nav-tools-pop:focus-within .nav-tools-item.is-current");
  });

  // The JS grace period is only half the fix. Without this strip the pointer
  // is genuinely outside the subtree while crossing the gap, and no timing
  // tweak makes a menu you have to sprint at feel right.
  it("the popover bridges the gap between itself and the trigger", () => {
    const bridge = bare.match(/\.nav-tools-pop::before\{([^}]*)\}/);
    expect(bridge, "the gap bridge must exist").not.toBeNull();
    const body = bridge![1];
    expect(body).toMatch(/position:absolute/);
    // Reaches UP into the gap…
    expect(body).toMatch(/top:-\d+px/);
    // …and spans the popover's full width, or the diagonal path still misses.
    expect(body).toMatch(/left:0/);
    expect(body).toMatch(/right:0/);
  });

  it("the AI pill has two spark states and rolls its label out", () => {
    // The icon's second state and the label's roll-out are the two things
    // Destin asked to SEE happen. Both are pure CSS hung off NavLink's
    // `.active` class, so nothing in the component would notice their loss.
    // The spark ORBITS the star's centre — one rotation is both the arc and
    // the twist. A translate can only slide it up a straight line, which is
    // exactly what read as "disappears and reappears" instead of travelling.
    expect(
      bare,
      "off is a quarter turn round the pivot, not a slide",
    ).toMatch(/\.nav-item\.nav-ai>a \.nav-ai-spark\{transform:rotate\(90deg\)/);
    expect(bare).toMatch(/\.nav-item\.nav-ai>a\.active \.nav-ai-spark\{transform:rotate\(0deg\)/);
    expect(bare, "a translate would straighten the arc").not.toMatch(
      /\.nav-ai-spark\{transform:translate/,
    );
    // The pivot is the STAR's centre, not the spark's: orbiting its own centre
    // would spin in place and go nowhere. Explicit transform-box because
    // browsers have disagreed on the default for SVG children.
    expect(bare).toMatch(/\.nav-ai-spark\{transform-box:view-box;transform-origin:12px 11\.5px/);
    // The arc's far point reaches the edge of the 24-unit box, and an SVG root
    // clips to its viewport by default.
    expect(bare).toMatch(/\.ai-ic\{[^}]*overflow:visible/);
    // ROLLS TO THE TEXT'S OWN WIDTH. `max-width:0 -> 7em` is the version that
    // popped: the label measures ~4em, so 40% of the travel was growing a limit
    // nothing was hitting, and an ease-out curve finished the visible part in
    // the first fifth of the duration. Tightening the guess is not the fix —
    // the mockup ships no webfont, so this text is Nunito on some machines and
    // Segoe UI on the rest, and a max-width tuned to one CLIPS the label on the
    // other.
    expect(bare).toMatch(
      /\.nav-item\.nav-ai>a\.active \.nav-ai-text\{grid-template-columns:1fr/,
    );
    expect(bare, "no guessed width may come back").not.toMatch(
      /\.nav-ai-text\{[^}]*max-width/,
    );
    // Collapsed at rest — a label that is merely transparent still reserves its
    // width, and the pill would sit wide and empty on every other route.
    expect(bare).toMatch(/\.nav-ai-text\{[^}]*grid-template-columns:0fr/);
    // The clip lives on the inner span; the track is what animates. Without
    // `overflow:hidden` here the text spills out of a zero-width column and the
    // pill shows its label on every route.
    expect(bare).toMatch(/\.nav-ai-text-inner\{[^}]*overflow:hidden/);
    expect(bare).toMatch(/\.nav-ai-text-inner\{[^}]*min-width:0/);
    expect(bare).toMatch(/\.nav-ai-spark\{[^}]*transition:transform/);
  });

  // The spark and the label are ONE gesture. They were two — .5s against .3s,
  // a spring against an ease, an opacity finishing before either — and read as
  // two things happening near each other. The shared tokens are what keep them
  // tunable as a unit; hardcoding a duration back into either rule is how they
  // drift apart again, silently, because both still animate.
  it("the spark and the label are timed as one gesture", () => {
    expect(bare).toMatch(/--ai-throw:[\d.]+s/);
    expect(bare).toMatch(/--ai-roll:[\d.]+s/);
    expect(bare).toMatch(/--ai-lead:[\d.]+s/);
    expect(bare).toMatch(/\.nav-ai-spark\{[^}]*transition:transform var\(--ai-throw\) var\(--ai-ease-throw\)/);
    expect(bare).toMatch(
      /\.nav-ai-text\{[^}]*grid-template-columns var\(--ai-roll\) var\(--ai-ease-roll\)/,
    );
    // The reveal gets its OWN curve. --ai-ease is an ease-out — 80% travelled
    // by a third of the way — which on a reveal reads as a pop however long the
    // duration is; the roll needs its motion through the middle instead.
    expect(bare).toMatch(/--ai-ease-roll:cubic-bezier/);
  });

  // The stagger runs BOTH ways round, and not symmetrically: going in the
  // spark leads and the label follows; coming out the label clears first so the
  // spark is not arcing across a word still on screen. Lose either delay and
  // the two halves collide.
  it("the stagger reverses on the way out", () => {
    expect(bare).toMatch(
      /\.nav-item\.nav-ai>a\.active \.nav-ai-text\{[^}]*transition-delay:var\(--ai-lead\)/,
    );
    expect(bare).toMatch(
      /\.nav-item\.nav-ai>a \.nav-ai-spark\{[^}]*transition-delay:var\(--ai-lead\)/,
    );
    // …and the leading half of each direction must NOT be delayed, or nothing
    // staggers and both just start late.
    expect(bare).toMatch(
      /\.nav-item\.nav-ai>a\.active \.nav-ai-spark\{[^}]*transition-delay:0s/,
    );
  });

  it("reduced motion keeps both states and drops only the travel", () => {
    const at = bare.indexOf(".nav-ai-text,.nav-ai-spark{transition:none;}");
    expect(at, "reduced-motion override must exist").toBeGreaterThan(-1);
    // Not `display:none`, not a cancelled transform: the two states still have
    // to be distinguishable, they just stop animating between each other.
    expect(bare).not.toMatch(/prefers-reduced-motion[\s\S]{0,200}\.nav-ai-spark\{transform:none/);
  });
});
