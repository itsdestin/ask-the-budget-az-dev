// 2026-08-16 — the source-level guard for the cross-lane glyph defect.
//
// ToolCard.tsx moved the glyph wrapper to a 24x24 stroked viewBox; ToolGroup.tsx
// was edited in a parallel worktree that never touched this file and stayed on
// the retired 12x12 viewBox with no stroke/fill. Both branches merged clean,
// every existing suite stayed green, because nothing asserted the two callers
// agreed with each other — each was individually "correct" for the file it sat
// in. `tool-card.test.tsx` and `tool-group.test.tsx` now each pin their own
// glyph's viewBox/stroke/fill, which would have caught THIS instance. But a
// per-caller assertion never catches a NEW caller making the same mistake —
// this file does, by making the mistake impossible to write rather than
// merely testable.
//
// The structural fix (tool-views/primitives.tsx) is that `toolGlyph`, the raw
// shape table, is no longer exported — only `ToolGlyph`, a component that owns
// its own <svg viewBox="0 0 24 24" fill="none" stroke="currentColor">, is. A
// caller can no longer choose a viewBox, correct or otherwise: `tsc -b`
// already refuses `import { toolGlyph }` from anywhere outside this file. This
// test pins that property directly rather than trusting the type checker
// alone — if a later change re-exports the raw table "for convenience", this
// is what still catches a caller wrapping it in a hand-rolled <svg>.
import { readFileSync, readdirSync } from "node:fs";
import { resolve, join } from "node:path";
import { describe, expect, it } from "vitest";

const chatDir = resolve(process.cwd(), "src/chat");

/** Every .ts/.tsx file under `dir`, recursing, excluding test files. */
function sourceFiles(dir: string): string[] {
  const out: string[] = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "__tests__") continue;
      out.push(...sourceFiles(full));
    } else if (/\.tsx?$/.test(entry.name)) {
      out.push(full);
    }
  }
  return out;
}

describe("tool glyph rendering is centralized", () => {
  it("no file outside primitives.tsx calls the raw glyph shape table", () => {
    // If this ever fires, it means `toolGlyph` (the un-exported shape table)
    // was re-exported and a caller reached for it directly instead of
    // rendering <ToolGlyph>. That caller is free to pick any viewBox it
    // likes, which is exactly how ToolGroup.tsx drifted from ToolCard.tsx.
    const offenders: string[] = [];
    for (const file of sourceFiles(chatDir)) {
      if (file.endsWith("/tool-views/primitives.tsx")) continue;
      const src = readFileSync(file, "utf-8");
      if (/\btoolGlyph\s*\(/.test(src)) {
        offenders.push(file);
      }
    }
    expect(
      offenders,
      `call <ToolGlyph tool="..."/> instead of toolGlyph(...) directly in: ${offenders.join(", ")}`,
    ).toEqual([]);
  });

  it("no file outside primitives.tsx declares its own viewBox for a tool glyph", () => {
    // A caller rendering <ToolGlyph> never writes `viewBox` at all — the
    // component owns it. If a file both imports ToolGlyph AND declares its
    // own `viewBox=`, either it's a false positive (an unrelated icon, like
    // the chevron both ToolCard and ToolGroup already draw inline — allowed)
    // or it's this bug again. The chevron path is excluded by name below
    // rather than by asserting "the only <svg> in the file", which would be
    // too strong: several tool-view files draw their own unrelated icons.
    const offenders: string[] = [];
    for (const file of ["ToolCard.tsx", "ToolGroup.tsx"]) {
      const path = join(chatDir, file);
      const src = readFileSync(path, "utf-8");
      const importsToolGlyph = /import\s*\{\s*ToolGlyph\s*\}\s*from\s*"\.\/tool-views\/primitives\.js"/.test(
        src,
      );
      expect(importsToolGlyph, `${file} must render <ToolGlyph>`).toBe(true);
      // Strip the chevron's own inline <svg viewBox="0 0 10 6">...</svg> block
      // — that one is a real, unrelated per-caller icon, not a copy of the
      // tool glyph's wrapper — before checking for a stray glyph-shaped one.
      const withoutChevron = src.replace(
        /<svg\s+viewBox="0 0 10 6"[\s\S]*?<\/svg>/,
        "",
      );
      if (/<svg[^>]*viewBox=/.test(withoutChevron)) {
        offenders.push(file);
      }
    }
    expect(
      offenders,
      `these files declare their own <svg viewBox> outside the chevron, which ` +
        `is exactly the shape of the original defect: ${offenders.join(", ")}`,
    ).toEqual([]);
  });
});
