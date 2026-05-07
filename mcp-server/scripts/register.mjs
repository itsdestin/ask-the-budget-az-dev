#!/usr/bin/env node
// Register the budget MCP server with the user's running YouCoded
// instance by writing an entry into ~/.claude.json under
// `mcpServers["ask-the-budget-az"]`. Idempotent — re-running updates
// the entry to point at the current built artifact.
//
// Pre-flight requirements:
//   1. `npm install && npm run build` was run in `mcp-server/`
//   2. The FastAPI sidecar is reachable (or about to be) at
//      $RETRIEVAL_BRIDGE_URL — checked via /health if reachable, but
//      not required for registration.
//
// Usage:
//   node scripts/register.mjs                    # writes the entry
//   node scripts/register.mjs --dry-run          # prints would-be diff
//   node scripts/register.mjs --remove           # removes the entry
//
// After registration, restart YouCoded so its MCP host re-loads
// ~/.claude.json — running sessions don't pick up new servers
// automatically.

import { existsSync, readFileSync, writeFileSync, copyFileSync } from "node:fs";
import { homedir } from "node:os";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";

const SERVER_KEY = "ask-the-budget-az";
const HOME = homedir();
const CONFIG_PATH = process.env.CLAUDE_CONFIG_PATH ?? join(HOME, ".claude.json");

const DRY_RUN = process.argv.includes("--dry-run");
const REMOVE = process.argv.includes("--remove");

const __filename = fileURLToPath(import.meta.url);
const SCRIPT_DIR = dirname(__filename);
const MCP_SERVER_DIR = resolve(SCRIPT_DIR, "..");
const BUILT_ENTRY = join(MCP_SERVER_DIR, "dist", "index.js");

function fail(msg) {
  process.stderr.write(`error: ${msg}\n`);
  process.exit(1);
}

function readConfig() {
  if (!existsSync(CONFIG_PATH)) {
    return {};
  }
  try {
    return JSON.parse(readFileSync(CONFIG_PATH, "utf-8"));
  } catch (err) {
    fail(
      `${CONFIG_PATH} is not valid JSON — refusing to clobber. Fix it first or pass CLAUDE_CONFIG_PATH=... to point elsewhere.\n${err.message}`,
    );
  }
}

function backup(path) {
  const ts = new Date().toISOString().replace(/[:.]/g, "-");
  const dest = `${path}.bak-${ts}`;
  copyFileSync(path, dest);
  return dest;
}

function buildEntry() {
  if (!existsSync(BUILT_ENTRY)) {
    fail(
      `built MCP entry not found at ${BUILT_ENTRY}. Run \`npm install && npm run build\` from mcp-server/ first.`,
    );
  }
  return {
    command: process.execPath, // current Node binary; survives PATH changes
    args: [BUILT_ENTRY],
    env: {
      RETRIEVAL_BRIDGE_URL:
        process.env.RETRIEVAL_BRIDGE_URL ?? "http://127.0.0.1:9200",
    },
  };
}

function main() {
  const config = readConfig();
  config.mcpServers = config.mcpServers ?? {};

  if (REMOVE) {
    if (!(SERVER_KEY in config.mcpServers)) {
      process.stdout.write(
        `nothing to remove — no ${SERVER_KEY} entry in ${CONFIG_PATH}\n`,
      );
      return;
    }
    delete config.mcpServers[SERVER_KEY];
    if (DRY_RUN) {
      process.stdout.write(`[dry-run] would remove ${SERVER_KEY}\n`);
      return;
    }
    if (existsSync(CONFIG_PATH)) {
      const bak = backup(CONFIG_PATH);
      process.stdout.write(`backed up to ${bak}\n`);
    }
    writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + "\n");
    process.stdout.write(`removed ${SERVER_KEY} from ${CONFIG_PATH}\n`);
    return;
  }

  const entry = buildEntry();
  const previous = config.mcpServers[SERVER_KEY];
  config.mcpServers[SERVER_KEY] = entry;

  if (DRY_RUN) {
    process.stdout.write(
      `[dry-run] would write ${SERVER_KEY} to ${CONFIG_PATH}:\n` +
        JSON.stringify({ [SERVER_KEY]: entry }, null, 2) +
        "\n",
    );
    if (previous) {
      process.stdout.write(
        `(replacing existing entry: ${JSON.stringify(previous)})\n`,
      );
    }
    return;
  }

  if (existsSync(CONFIG_PATH)) {
    const bak = backup(CONFIG_PATH);
    process.stdout.write(`backed up to ${bak}\n`);
  }
  writeFileSync(CONFIG_PATH, JSON.stringify(config, null, 2) + "\n");
  process.stdout.write(
    `registered ${SERVER_KEY} in ${CONFIG_PATH} → ${BUILT_ENTRY}\n` +
      `restart YouCoded so its MCP host picks up the new entry.\n`,
  );
}

main();
