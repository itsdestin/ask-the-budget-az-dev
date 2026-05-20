// Singleton wrapping YouCodedSessionProvider for use inside Next.js
// API route handlers.
//
// Why a singleton: the provider holds an open WebSocket to YouCoded
// (one connection, multiplexed across budget conversations). Each API
// route call should reuse it, not open a new one. In dev, Next.js
// hot-reloads server code on every change — we stash the singleton on
// `globalThis` so HMR doesn't leak a fresh provider per reload.
//
// Per-conversation state (UUID-dedup, accumulator) lives on the
// provider itself; the budget app's web layer is stateless beyond
// holding this reference.

import { resolve } from "node:path";

import {
  YouCodedSessionProvider,
  type YouCodedSessionProviderOptions,
} from "./youcoded-session-provider.js";

const GLOBAL_KEY = "__budgetYouCodedProvider__";

interface GlobalWithProvider {
  [GLOBAL_KEY]?: YouCodedSessionProvider;
}

export function getProvider(): YouCodedSessionProvider {
  const g = globalThis as unknown as GlobalWithProvider;
  if (!g[GLOBAL_KEY]) {
    const opts: YouCodedSessionProviderOptions = {};
    // INVARIANT (Task 3 of 2026-05-20 dogfood-hardening plan): production
    // MUST NOT set `globalMcpConfigPath` here. The loader's default of
    // `$HOME/.claude.json` is the contract — overriding it here would point
    // the per-session .mcp.json materialization at the wrong global config
    // and break every conversation's MCP eager-load. Tests inject their own
    // fixture path; production falls through to the default.
    //
    // Allow .env.local overrides without leaking process.env into the
    // library — the lib stays pure and consumable from non-Next hosts.
    if (process.env.YOUCODED_WS_URL) opts.url = process.env.YOUCODED_WS_URL;
    if (process.env.YOUCODED_TOKEN) opts.token = process.env.YOUCODED_TOKEN;
    if (process.env.YOUCODED_TOKEN_PATH)
      opts.tokenPath = process.env.YOUCODED_TOKEN_PATH;
    if (process.env.BUDGET_DEFAULT_CWD)
      opts.defaultCwd = process.env.BUDGET_DEFAULT_CWD;
    // System-prompt materialization. Without this, Claude spawns in the
    // budget app's source tree and reads the developer-facing CLAUDE.md,
    // which makes it think it's helping build the budget tool rather
    // than acting as the budget tool's research backend. The Next.js
    // dev server runs from `web/`, so the project root is one level up.
    const repoRoot = resolve(process.cwd(), "..");
    opts.systemPromptPath =
      process.env.BUDGET_SYSTEM_PROMPT_PATH ??
      resolve(repoRoot, "mcp-server", "system-prompt.md");
    opts.systemPromptContextPath =
      process.env.BUDGET_SYSTEM_PROMPT_CONTEXT_PATH ??
      resolve(repoRoot, "data", "system-prompt-context.md");
    // Pin every conversation to Opus 4.7 unless overridden. The
    // constrained-agent workflow (retrieve → cite → refuse) is
    // measurably more reliable on Opus; Haiku has been observed
    // emitting inline <cite> XML markup instead of calling the
    // cite() MCP tool, which breaks the chip → PdfViewer flow even
    // when the model has the right facts.
    opts.model = process.env.BUDGET_MODEL ?? "claude-opus-4-7";
    g[GLOBAL_KEY] = new YouCodedSessionProvider(opts);
  }
  return g[GLOBAL_KEY]!;
}
