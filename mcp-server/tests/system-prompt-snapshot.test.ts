// Pin the system prompt's structural H1/H2 headings so future edits
// surface a visible diff. NOT a behavioral test — the prompt's content
// is regression-tested via dogfood sessions, not unit tests — but
// catching accidental section deletions (e.g. losing the Refusal
// section) before they ship is cheap.
//
// Regex `/^##? /` matches H1 (`# `) and H2 (`## `) only. H3
// sub-headings (e.g. inside the cite() section) are intentionally
// NOT pinned so we can rework them freely.

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
      .filter((l) => /^##? /.test(l))
      .map((l) => l.replace(/^#+\s+/, "").trim());
    expect(headings).toMatchSnapshot();
  });
});
