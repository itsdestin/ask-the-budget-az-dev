// webapp/src/styles/no-bare-links.test.ts
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Destin, 2026-08-25: "i hate the bare blue hyperlink styling and that
// shouldn't be used anywhere. use real pills/buttons." Recorded twice
// (whole-report links 2026-08-16, the People mockup) — pinned once.
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|css)$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}

describe("no bare link styling", () => {
  it("adm-link appears nowhere in the source", () => {
    const offenders = walk(join(__dirname, "..")).filter((p) => readFileSync(p, "utf-8").includes("adm-link"));
    expect(offenders).toEqual([]);
  });
});
