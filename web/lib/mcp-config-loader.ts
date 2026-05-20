// Reads the user's global ~/.claude.json (or an injected path during
// tests) and returns the `mcpServers["ask-the-budget-az"]` entry — the
// same shape `mcp-server/scripts/register.mjs` writes. We re-use that
// entry in `materializeRuntimeDir()` so the per-conversation .mcp.json
// points at the same node binary + built mcp-server dist that the
// global registration installed. Single source of truth — if register
// changes paths, the budget app picks up the change automatically.

import { promises as fs } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

export interface BudgetMcpServerEntry {
  command: string;
  args: string[];
  // env is optional in the global config; we normalize to {} when absent
  // so callers don't need to null-check.
  env: Record<string, string>;
}

const REGISTRATION_HINT =
  "Budget MCP server isn't registered in ~/.claude.json. " +
  "Run `node mcp-server/scripts/register.mjs` first.";

/** Default to ~/.claude.json; tests inject an explicit path. */
function defaultConfigPath(): string {
  return join(homedir(), ".claude.json");
}

export async function loadBudgetMcpServerEntry(
  configPath: string = defaultConfigPath(),
): Promise<BudgetMcpServerEntry> {
  let raw: string;
  try {
    raw = await fs.readFile(configPath, "utf8");
  } catch (err) {
    if ((err as NodeJS.ErrnoException).code === "ENOENT") {
      throw new Error(REGISTRATION_HINT);
    }
    throw err;
  }
  let parsed: unknown;
  try {
    parsed = JSON.parse(raw);
  } catch (err) {
    // Surface the JSON parse failure verbatim — the user can fix it
    // by hand; we don't want to silently retry or auto-correct.
    throw new Error(
      `Could not parse ${configPath}: ${(err as Error).message}`,
    );
  }
  const entry =
    (parsed as { mcpServers?: Record<string, unknown> })?.mcpServers?.[
      "ask-the-budget-az"
    ];
  if (!entry || typeof entry !== "object") {
    throw new Error(REGISTRATION_HINT);
  }
  const e = entry as {
    command?: unknown;
    args?: unknown;
    env?: unknown;
  };
  if (typeof e.command !== "string" || !Array.isArray(e.args)) {
    throw new Error(
      `${configPath} has a malformed ask-the-budget-az entry: ${JSON.stringify(entry)}`,
    );
  }
  return {
    command: e.command,
    args: e.args as string[],
    env:
      e.env && typeof e.env === "object"
        ? (e.env as Record<string, string>)
        : {},
  };
}
