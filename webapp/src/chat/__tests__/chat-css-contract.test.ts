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
