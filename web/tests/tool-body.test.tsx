// Smoke tests for the per-tool ToolBody dispatcher and the helpers
// that drive the per-tool views. We test the pure helpers directly
// and use react-dom/server to render the dispatcher to a string with
// representative inputs (no DOM-testing-library dep needed).

import { describe, expect, it } from "vitest";
import { renderToString } from "react-dom/server";

import {
  basename,
  parentDir,
  stripCarriageReturns,
  unescapeForDisplay,
} from "../components/tool-views/primitives";
import ToolBody from "../components/tool-views/ToolBody";
import type { AssistantBlock } from "../state/chat-types.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

function block(overrides: Partial<ToolBlock>): ToolBlock {
  return {
    kind: "tool",
    toolUseId: "t1",
    toolName: "Bash",
    input: {},
    status: "complete",
    ...overrides,
  } as ToolBlock;
}

describe("primitives helpers", () => {
  it("basename extracts the file name from windows-style paths", () => {
    expect(basename("C:\\Users\\foo\\bar.ts")).toBe("bar.ts");
  });

  it("basename extracts the file name from posix paths", () => {
    expect(basename("/a/b/c.ts")).toBe("c.ts");
  });

  it("parentDir returns the directory chain", () => {
    expect(parentDir("/a/b/c.ts")).toBe("a/b");
  });

  it("stripCarriageReturns collapses progress lines to final state", () => {
    const input =
      "Updating files: 10%\rUpdating files: 50%\rUpdating files: 100%\nDone.";
    expect(stripCarriageReturns(input)).toBe("Updating files: 100%\nDone.");
  });

  it("unescapeForDisplay reveals literal \\n / \\\" / \\t escapes", () => {
    expect(unescapeForDisplay("foo\\nbar")).toBe("foo\nbar");
    expect(unescapeForDisplay('say \\"hi\\"')).toBe('say "hi"');
    expect(unescapeForDisplay("a\\tb")).toBe("a\tb");
  });
});

describe("ToolBody dispatcher", () => {
  it("renders Bash command + output in ShellView", () => {
    const tool = block({
      toolName: "Bash",
      input: { command: "ls -la" },
      output: "total 0\n",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("ls -la");
    expect(html).toContain("total 0");
  });

  it("renders Read response as numbered rows with a line-range chip", () => {
    const tool = block({
      toolName: "Read",
      input: { file_path: "/a/b.ts" },
      output: "     1\thello\n     2\tworld",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("hello");
    expect(html).toContain("world");
    expect(html).toContain("lines 1");
  });

  it("renders Edit with a unified diff (LCS fallback)", () => {
    const tool = block({
      toolName: "Edit",
      input: {
        file_path: "/a.ts",
        old_string: "foo\nbar",
        new_string: "foo\nbaz",
      },
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("foo");
    expect(html).toContain("bar");
    expect(html).toContain("baz");
  });

  it("renders Edit with structuredPatch when provided (real file line numbers)", () => {
    const tool = block({
      toolName: "Edit",
      input: { file_path: "/a.ts", old_string: "", new_string: "" },
      structuredPatch: [
        {
          oldStart: 100,
          oldLines: 1,
          newStart: 100,
          newLines: 1,
          lines: ["-stale", "+fresh"],
        },
      ],
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("stale");
    expect(html).toContain("fresh");
    // Absolute file line number (100) should appear in the gutter.
    expect(html).toContain("100");
  });

  it("renders Grep content-mode results grouped by file", () => {
    const tool = block({
      toolName: "Grep",
      input: { pattern: "todo", output_mode: "content" },
      output: "src/a.ts:5:// todo first\nsrc/b.ts:9:// todo second",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("src/a.ts");
    expect(html).toContain("src/b.ts");
    expect(html).toContain("todo first");
    expect(html).toContain("todo second");
  });

  it("renders Glob path list", () => {
    const tool = block({
      toolName: "Glob",
      input: { pattern: "**/*.ts" },
      output: "src/a.ts\nsrc/b.ts",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("**/*.ts");
    expect(html).toContain("src/a.ts");
    // React 18 SSR injects HTML comments between adjacent number/string
    // children to preserve hydration; match the count + label loosely.
    expect(html).toMatch(/2.*?file.*?s/);
  });

  it("renders Write with content + line count chip", () => {
    const tool = block({
      toolName: "Write",
      input: { file_path: "/new.ts", content: "line1\nline2\nline3" },
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("New file");
    expect(html).toContain("line1");
    expect(html).toMatch(/3.*?lines/);
  });

  it("renders WebFetch with the URL + optional prompt", () => {
    const tool = block({
      toolName: "WebFetch",
      input: { url: "https://example.com/path", prompt: "summarize" },
      output: "page contents",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("example.com");
    expect(html).toContain("https://example.com/path");
    expect(html).toContain("summarize");
  });

  it("falls back to raw view for unknown tools (input + output sections)", () => {
    const tool = block({
      toolName: "MysteryTool",
      input: { foo: "bar" },
      output: "ok",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html.toLowerCase()).toContain("input");
    expect(html.toLowerCase()).toContain("output");
    expect(html).toContain("&quot;foo&quot;");
    expect(html).toContain("ok");
  });

  it("surfaces tool errors via the ErrorBlock", () => {
    const tool = block({
      toolName: "Bash",
      input: { command: "false" },
      output: "exit 1",
      isError: true,
      status: "failed",
    });
    const html = renderToString(<ToolBody tool={tool} />);
    expect(html).toContain("Failed");
    expect(html).toContain("Error");
    expect(html).toContain("exit 1");
  });
});
