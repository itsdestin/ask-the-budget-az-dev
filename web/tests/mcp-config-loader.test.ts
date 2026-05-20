// Pure-unit tests for the MCP config loader. Reads from a path we
// control (the test pins CLAUDE_CONFIG_PATH-style behavior via the
// `configPath` injection arg) so no global filesystem state is needed.

import { promises as fs } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  loadBudgetMcpServerEntry,
  type BudgetMcpServerEntry,
} from "../lib/mcp-config-loader.js";

let cfgDir: string;
let cfgPath: string;

beforeEach(async () => {
  cfgDir = await fs.mkdtemp(join(tmpdir(), "budget-mcpcfg-test-"));
  cfgPath = join(cfgDir, "config.json");
});

afterEach(async () => {
  await fs.rm(cfgDir, { recursive: true, force: true });
});

describe("loadBudgetMcpServerEntry", () => {
  it("returns the entry with command/args/env intact", async () => {
    const written = {
      mcpServers: {
        "ask-the-budget-az": {
          command: "/usr/bin/node",
          args: ["/opt/mcp/dist/index.js"],
          env: { RETRIEVAL_BRIDGE_URL: "http://127.0.0.1:9200" },
        },
      },
    };
    await fs.writeFile(cfgPath, JSON.stringify(written), "utf8");
    const entry: BudgetMcpServerEntry = await loadBudgetMcpServerEntry(cfgPath);
    expect(entry.command).toBe("/usr/bin/node");
    expect(entry.args).toEqual(["/opt/mcp/dist/index.js"]);
    expect(entry.env).toEqual({ RETRIEVAL_BRIDGE_URL: "http://127.0.0.1:9200" });
  });

  it("throws a registration-hint error when the file is missing", async () => {
    await expect(loadBudgetMcpServerEntry(cfgPath)).rejects.toThrow(
      /Budget MCP server isn't registered/,
    );
  });

  it("throws when the file exists but has no ask-the-budget-az entry", async () => {
    await fs.writeFile(
      cfgPath,
      JSON.stringify({ mcpServers: { other: {} } }),
      "utf8",
    );
    await expect(loadBudgetMcpServerEntry(cfgPath)).rejects.toThrow(
      /Budget MCP server isn't registered/,
    );
  });

  it("throws when the file is invalid JSON", async () => {
    await fs.writeFile(cfgPath, "{ not json", "utf8");
    await expect(loadBudgetMcpServerEntry(cfgPath)).rejects.toThrow(/JSON/);
  });
});
