// Pin the system prompt's structural H1/H2/H3 headings so future edits
// surface a visible diff. NOT a behavioral test — the prompt's content
// is regression-tested via dogfood sessions, not unit tests — but
// catching accidental section deletions (e.g. losing the Refusal
// section, or one of its three H3 sub-cases) before they ship is cheap.
//
// Regex `/^#{1,3} /` matches H1 (`# `), H2 (`## `), and H3 (`### `).
// H3 coverage is load-bearing for the Refusal sub-cases
// (refusal_no_retrieval, refusal_synthesis, refusal_out_of_scope) and
// the Retrieval recipes section, which would otherwise disappear
// silently under a future edit.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

// ESM equivalent of __dirname — this file lives in mcp-server/tests/.
const here = dirname(fileURLToPath(import.meta.url));

describe("mcp-server/system-prompt.md structure", () => {
  it("contains the expected top-level sections in order", () => {
    const promptPath = join(here, "..", "system-prompt.md");
    const text = readFileSync(promptPath, "utf8");
    const headings = text
      .split("\n")
      .filter((l) => /^#{1,3} /.test(l))
      .map((l) => l.replace(/^#+\s+/, "").trim());
    expect(headings).toMatchSnapshot();
  });
});
