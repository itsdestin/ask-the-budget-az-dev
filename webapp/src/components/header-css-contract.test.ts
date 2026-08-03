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

  it("the AI pill has two spark states and rolls its label out", () => {
    // The icon's second state and the label's roll-out are the two things
    // Destin asked to SEE happen. Both are pure CSS hung off NavLink's
    // `.active` class, so nothing in the component would notice their loss.
    expect(bare).toMatch(
      /\.nav-item\.nav-ai>a\.active \.nav-ai-spark\{transform:translate\(/,
    );
    expect(bare).toMatch(/\.nav-item\.nav-ai>a\.active \.nav-ai-text\{[^}]*max-width/);
    // Collapsed at rest — a label that is merely transparent still reserves its
    // width, and the pill would sit wide and empty on every other route.
    expect(bare).toMatch(/\.nav-ai-text\{[^}]*max-width:0/);
    expect(bare).toMatch(/\.nav-ai-spark\{transition:transform/);
  });

  it("reduced motion keeps both states and drops only the travel", () => {
    const at = bare.indexOf(".nav-ai-text,.nav-ai-spark{transition:none;}");
    expect(at, "reduced-motion override must exist").toBeGreaterThan(-1);
    // Not `display:none`, not a cancelled transform: the two states still have
    // to be distinguishable, they just stop animating between each other.
    expect(bare).not.toMatch(/prefers-reduced-motion[\s\S]{0,200}\.nav-ai-spark\{transform:none/);
  });
});
