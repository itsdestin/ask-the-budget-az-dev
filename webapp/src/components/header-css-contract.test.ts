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
    expect(bare).toMatch(/\.nav-item\.nav-ai>a\.active \.nav-ai-text\{[^}]*max-width/);
    // Collapsed at rest — a label that is merely transparent still reserves its
    // width, and the pill would sit wide and empty on every other route.
    expect(bare).toMatch(/\.nav-ai-text\{[^}]*max-width:0/);
    expect(bare).toMatch(/\.nav-ai-spark\{[^}]*transition:transform/);
  });

  it("reduced motion keeps both states and drops only the travel", () => {
    const at = bare.indexOf(".nav-ai-text,.nav-ai-spark{transition:none;}");
    expect(at, "reduced-motion override must exist").toBeGreaterThan(-1);
    // Not `display:none`, not a cancelled transform: the two states still have
    // to be distinguishable, they just stop animating between each other.
    expect(bare).not.toMatch(/prefers-reduced-motion[\s\S]{0,200}\.nav-ai-spark\{transform:none/);
  });
});
