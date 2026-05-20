// LLMProvider implementation backed by a running YouCoded instance via
// `ws://localhost:9900/ws`. One YouCoded session per conversation; one
// `sendTurn` call per user-input → final-answer cycle.
//
// All tool types pass through to `onEvent` — the provider is agnostic
// about which tools Claude uses (decision D5). After turn-complete it
// extracts retrieve→cite metadata for the SendTurnResult, but it does
// NOT filter what reaches the UI: a budget-app conversation may also
// see Bash, Grep, Read, etc. for fallback verification, and those need
// to render too.

import { promises as fs, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";

import type {
  Citation,
  LLMProvider,
  SendTurnArgs,
  SendTurnResult,
  StartConversationOpts,
  StartConversationResult,
  ToolCallSummary,
} from "./llm-provider.js";
import { parseTranscriptEvent, type ParserContext } from "./transcript-parser.js";
import type { ProviderEvent, TranscriptEvent } from "./types.js";
import {
  YouCodedClient,
  YouCodedClientError,
  type YouCodedClientOptions,
} from "./youcoded-client.js";
import { loadBudgetMcpServerEntry } from "./mcp-config-loader.js";

const DEFAULT_NAME = "Ask the Budget AZ";

export interface YouCodedSessionProviderOptions
  extends YouCodedClientOptions {
  /** Default cwd applied to startConversation when no override is given
   *  AND no system prompt is being materialized. When `systemPromptPath`
   *  is set, the provider creates a per-conversation runtime dir and
   *  uses THAT as cwd, ignoring this fallback. */
  defaultCwd?: string;
  /** Absolute path to `mcp-server/system-prompt.md`. See class docstring. */
  systemPromptPath?: string;
  /** Optional path to `data/system-prompt-context.md`. */
  systemPromptContextPath?: string;
  /** Parent directory under which per-conversation runtime dirs are
   *  created. Defaults to `os.tmpdir()/ask-the-budget-az`. */
  runtimeDirRoot?: string;
  /** Path to the user's global ~/.claude.json. Tests inject a fixture
   *  path; production callers omit and the loader defaults to
   *  $HOME/.claude.json. We materialize a per-session .mcp.json that
   *  copies this file's `mcpServers["ask-the-budget-az"]` entry and
   *  adds `alwaysLoad: true` — eager-loading the budget tools
   *  eliminates ToolSearch round-trips at session start (verified on
   *  branch test-alwaysload, commit 6d47efa). */
  globalMcpConfigPath?: string;
  /** Claude Code model slug to use for every session. */
  model?: string;
}

export class YouCodedSessionProvider implements LLMProvider {
  private readonly client: YouCodedClient;
  private readonly defaultCwd: string | undefined;
  private readonly systemPromptPath: string | undefined;
  private readonly systemPromptContextPath: string | undefined;
  private readonly runtimeDirRoot: string;
  private readonly globalMcpConfigPath: string | undefined;
  private readonly model: string | undefined;
  /** Per-conversation materialized runtime dir, used to clean up on
   *  endConversation. Only populated when `systemPromptPath` is set. */
  private runtimeDirByConversation = new Map<string, string>();
  private connectPromise: Promise<void> | null = null;
  /** Per-session UUID-dedup state for assistant_text emissions. Lives
   *  with the provider so multiple turns in one conversation share it
   *  (Claude's growing-message rewrites can span tool-result boundaries). */
  private parserContextByConversation = new Map<string, ParserContext>();

  /** Per-session "first hook event seen" flag. YouCoded fires the first
   *  hook only after CC has booted past its SessionStart hook, which is
   *  the same signal YouCoded's own UI uses to enable the InputBar
   *  (App.tsx setInitializedSessions). The session provider gates
   *  sendInput on this so the user message isn't sent into CC's
   *  startup banner where the trailing \r gets absorbed as paste
   *  content. Map value: array of pending "send when ready" callbacks
   *  (resolves on the first hook event for that session). Replaced
   *  with `READY` once ready, so subsequent turns send immediately. */
  private readyState = new Map<
    string,
    "ready" | Array<() => void>
  >();
  private hookUnsubscribe: (() => void) | null = null;

  constructor(opts: YouCodedSessionProviderOptions = {}) {
    this.client = new YouCodedClient(opts);
    this.defaultCwd = opts.defaultCwd;
    this.systemPromptPath = opts.systemPromptPath;
    this.systemPromptContextPath = opts.systemPromptContextPath;
    this.runtimeDirRoot =
      opts.runtimeDirRoot ?? join(tmpdir(), "ask-the-budget-az");
    this.globalMcpConfigPath = opts.globalMcpConfigPath;
    this.model = opts.model;
  }

  /** Build a per-conversation tempdir containing CLAUDE.md (the system
   *  prompt), data/system-prompt-context.md (the JLBC primer), .mcp.json
   *  (eager-loads the budget MCP server so ToolSearch isn't invoked at
   *  session start), and .claude/settings.json (allow-list for Bash/Read
   *  + budget tools; deny-list for tools past dogfood sessions never
   *  used legitimately). Returns the dir path. */
  private async materializeRuntimeDir(): Promise<string> {
    if (!this.systemPromptPath) {
      throw new Error(
        "materializeRuntimeDir() requires systemPromptPath in opts",
      );
    }
    // Load the budget MCP server entry from the global ~/.claude.json
    // FIRST so we fail fast (before any tempdir is made) when the user
    // hasn't run `node mcp-server/scripts/register.mjs`. Throws a
    // registration-hint message the user can act on.
    const entry = await loadBudgetMcpServerEntry(this.globalMcpConfigPath);

    const promptText = await fs.readFile(this.systemPromptPath, "utf8");
    const dir = join(this.runtimeDirRoot, `conv-${randomUUID()}`);
    await fs.mkdir(dir, { recursive: true });

    // 1. CLAUDE.md (the system prompt) — Claude Code reads this from cwd.
    await fs.writeFile(join(dir, "CLAUDE.md"), promptText, "utf8");

    // 2. data/system-prompt-context.md (the JLBC primer the system prompt
    //    references). Optional; only materialized when the path was passed.
    if (this.systemPromptContextPath) {
      const contextText = await fs.readFile(
        this.systemPromptContextPath,
        "utf8",
      );
      const dataDir = join(dir, "data");
      await fs.mkdir(dataDir, { recursive: true });
      await fs.writeFile(
        join(dataDir, "system-prompt-context.md"),
        contextText,
        "utf8",
      );
    }

    // 3. .mcp.json — eager-load the budget MCP server. The `alwaysLoad`
    //    flag tells Claude Code to register every budget tool at session
    //    start instead of through ToolSearch's lazy-resolve path.
    //    Verified 2026-05-19 on branch test-alwaysload: 0 ToolSearch
    //    calls in a 287-line transcript vs. 1-25 per past session.
    const mcpJson = {
      mcpServers: {
        "ask-the-budget-az": {
          command: entry.command,
          args: entry.args,
          env: entry.env,
          alwaysLoad: true,
        },
      },
    };
    await fs.writeFile(
      join(dir, ".mcp.json"),
      JSON.stringify(mcpJson, null, 2),
      "utf8",
    );

    // 4. .claude/settings.json — explicit allow/deny per dogfood audit.
    //    Decision D5: general tools (Bash, Read) stay enabled — they're
    //    fallback verification paths. The deny list removes tools the
    //    audit showed were never legitimately used in budget sessions.
    //    ToolSearch is NOT denied — denying it could break lazy-load
    //    fallback for any tool we haven't eager-loaded. (We just don't
    //    NEED it now that alwaysLoad covers the budget tools.)
    const settings = {
      permissions: {
        allow: [
          "Bash",
          "Read",
          "mcp__ask-the-budget-az__retrieve",
          "mcp__ask-the-budget-az__cite",
          "mcp__ask-the-budget-az__cite_batch",
          "mcp__ask-the-budget-az__list_filter_values",
        ],
        deny: [
          "Grep",
          "Write",
          "Edit",
          "MultiEdit",
          "NotebookEdit",
          "Glob",
          "PowerShell",
          "WebFetch",
          "WebSearch",
          "mcp__windows-control__*",
          "mcp__gmessages__*",
          "mcp__imessages__*",
          "mcp__todoist__*",
          "mcp__spotify-services__*",
        ],
      },
    };
    const claudeDir = join(dir, ".claude");
    await fs.mkdir(claudeDir, { recursive: true });
    await fs.writeFile(
      join(claudeDir, "settings.json"),
      JSON.stringify(settings, null, 2),
      "utf8",
    );

    return dir;
  }

  /** Subscribe once to global hook events; route the first per-session
   *  event to whatever's waiting in `readyState[sessionId]`. */
  private ensureHookSubscription(): void {
    if (this.hookUnsubscribe) return;
    this.hookUnsubscribe = this.client.onHookEvent(({ sessionId }) => {
      const entry = this.readyState.get(sessionId);
      if (entry === "ready") return; // already flushed
      this.readyState.set(sessionId, "ready");
      if (Array.isArray(entry)) {
        for (const cb of entry) {
          try {
            cb();
          } catch {
            // Don't let one waiter break the others.
          }
        }
      }
    });
  }

  /** Wait for the first hook event for `sessionId` (i.e. CC ready),
   *  then send the user message + \r. Subsequent turns on the same
   *  session resolve immediately because readyState is already 'ready'.
   *  If CC is so slow we time out (30s safety), fail the turn rather
   *  than hang forever. */
  private dispatchSendWhenReady(
    sessionId: string,
    userMessage: string,
    fail: (err: Error) => void,
  ): void {
    const READY_TIMEOUT_MS = 30_000;
    const send = () => {
      try {
        this.client.sendInput(sessionId, userMessage + "\r");
      } catch (err) {
        fail(err as Error);
      }
    };
    const entry = this.readyState.get(sessionId);
    if (entry === "ready") {
      send();
      return;
    }
    const waiters = Array.isArray(entry) ? entry : [];
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      fail(
        new YouCodedClientError(
          `Claude session didn't initialize within ${READY_TIMEOUT_MS / 1000}s — ` +
            `no hook events received. Is YouCoded responsive?`,
          "request_failed",
        ),
      );
    }, READY_TIMEOUT_MS);
    waiters.push(() => {
      if (timedOut) return;
      clearTimeout(timer);
      send();
    });
    this.readyState.set(sessionId, waiters);
  }

  /** Lazy connect — `startConversation` triggers it. Re-uses the same
   *  client connection across many conversations.
   *
   *  Stale-connection guard: once the original connectPromise resolves,
   *  the client may still LOSE its socket (YouCoded restart, network
   *  blip, idle close). The promise stays fulfilled so a naive cache
   *  short-circuit would leave the provider thinking it's connected
   *  while every subsequent request throws "not connected — call
   *  connect() first". We probe `client.isConnected` BEFORE returning
   *  the cached promise; if the socket is gone, drop the cache and
   *  re-handshake. This was the root cause of the 2026-05-08 dead-
   *  singleton outage where the budget app silently broke after the
   *  WS server momentarily disappeared. */
  private async ensureConnected(): Promise<void> {
    if (this.connectPromise && !this.client.isConnected) {
      this.connectPromise = null;
    }
    if (!this.connectPromise) {
      this.connectPromise = this.client.connect().catch((err) => {
        // Reset so a retry can try again — otherwise a transient
        // failure would permanently disable the provider.
        this.connectPromise = null;
        throw err;
      });
    }
    return this.connectPromise;
  }

  async startConversation(
    opts: StartConversationOpts = {},
  ): Promise<StartConversationResult> {
    await this.ensureConnected();
    // Subscribe once to hook events — the first per-session event flips
    // readyState[sid] to 'ready' and flushes any waiting sendTurns.
    // Subscribing BEFORE createSession avoids missing an early hook
    // that fires between create and our subscribe call.
    this.ensureHookSubscription();
    // Resolve cwd. Priority: explicit opts.cwd > materialized runtime
    // dir (when systemPromptPath is set) > defaultCwd > process.cwd().
    // Materialization happens BEFORE createSession so a failure here
    // doesn't leave an orphan YouCoded session.
    let cwd = opts.cwd ?? this.defaultCwd ?? process.cwd();
    let runtimeDir: string | null = null;
    if (!opts.cwd && this.systemPromptPath) {
      runtimeDir = await this.materializeRuntimeDir();
      cwd = runtimeDir;
    }
    const name = opts.name ?? DEFAULT_NAME;
    let info: { id: string };
    try {
      info = await this.client.createSession({
        name,
        cwd,
        // Budget conversations auto-approve everything: the system prompt
        // constrains Claude to retrieve/cite for the budget questions, and
        // the analyst opted into the workflow by opening the chat. We do
        // NOT want a permission prompt every time Claude calls retrieve.
        skipPermissions: true,
        // Pin the model for the budget app's constrained-agent flow.
        // When unset, YouCoded picks its default — currently Haiku
        // for new sessions, which has been observed to emit inline
        // <cite> XML tags instead of calling the cite() tool. Opus
        // is more reliable on tool-call discipline and on producing
        // verbatim claim_spans.
        ...(this.model !== undefined ? { model: this.model } : {}),
      });
    } catch (err) {
      // Roll back the materialized dir if YouCoded refused — keeping
      // a tempdir that no session points at would just leak disk.
      if (runtimeDir) {
        await this.removeRuntimeDirSafely(runtimeDir);
      }
      throw err;
    }
    if (runtimeDir) {
      this.runtimeDirByConversation.set(info.id, runtimeDir);
    }
    this.parserContextByConversation.set(info.id, {
      seenAssistantTextUuids: new Set<string>(),
    });
    // Seed the ready state with an empty waiter list (the hook handler
    // flips it to 'ready' on first hook). Done after createSession so
    // we have the real session id to key on.
    if (!this.readyState.has(info.id)) {
      this.readyState.set(info.id, []);
    }

    // Sidecar /health probe. Done synchronously AFTER createSession (so
    // failures here can't strand a half-created session) and BEFORE we
    // return (so the caller sees the result in one place). 2s hard
    // timeout — the probe must fail fast; we don't want a slow /health
    // delaying the chat. We return the failure on the result object
    // rather than emitting an event so the UI doesn't need any
    // subscription plumbing.
    const probeUrl =
      (process.env.RETRIEVAL_BRIDGE_URL ?? "http://127.0.0.1:9200") + "/health";
    let health: { ok: boolean; reason?: string };
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 2000);
    try {
      const resp = await fetch(probeUrl, { signal: controller.signal });
      if (resp.ok) {
        health = { ok: true };
      } else {
        health = { ok: false, reason: `HTTP ${resp.status}` };
      }
    } catch (err) {
      health = { ok: false, reason: (err as Error).message };
    } finally {
      clearTimeout(timer);
    }

    return { conversationId: info.id, health };
  }

  async sendTurn(args: SendTurnArgs): Promise<SendTurnResult> {
    const { conversationId, userMessage, onEvent, signal } = args;
    const ctx = this.parserContextByConversation.get(conversationId);
    if (!ctx) {
      throw new YouCodedClientError(
        `unknown conversationId ${conversationId} — call startConversation first`,
        "request_failed",
      );
    }

    // Per-turn accumulator. Reset between sendTurn calls so the result
    // reflects only the current turn (citations, chunk ids, tool calls,
    // final answer). The UUID-dedup set on `ctx` persists across turns
    // because Claude's growing-message rewrites can outlive a turn.
    const finalAnswerByUuid = new Map<string, string>();
    const finalAnswerOrder: string[] = [];
    const toolCallsByUseId = new Map<string, ToolCallSummary>();
    const toolCallOrder: string[] = [];
    const retrievedChunkIds: string[] = [];
    const citations: Citation[] = [];
    let stopReason = "unknown";
    let resolved = false;
    // YouCoded sometimes broadcasts `turn-complete` BEFORE the final
    // `assistant-text` event in the same WS-message batch (observed:
    // assistant-thinking → turn-complete → assistant-text → turn-complete).
    // Finalising synchronously on the first turn-complete unsubscribes
    // the transcript listener and the trailing assistant-text never
    // reaches `onEvent` or the accumulator. Defer the finalize via
    // setImmediate and reschedule on every subsequent turn-complete so
    // trailing events in the same tick still update state.
    let pendingFinalize: NodeJS.Immediate | null = null;
    const FINALIZE_GRACE_MS = 250;
    let graceTimer: NodeJS.Timeout | null = null;

    return new Promise<SendTurnResult>((resolve, reject) => {
      const finalize = (reason: string) => {
        if (resolved) return;
        resolved = true;
        if (pendingFinalize) clearImmediate(pendingFinalize);
        if (graceTimer) clearTimeout(graceTimer);
        unsubscribeTranscript();
        unsubscribeDestroyed();
        if (signal) signal.removeEventListener("abort", abortHandler);
        const finalAnswer = finalAnswerOrder
          .map((u) => finalAnswerByUuid.get(u) ?? "")
          .join("\n\n");
        resolve({
          finalAnswer,
          citations,
          retrievedChunkIds,
          toolCalls: toolCallOrder.map((id) => toolCallsByUseId.get(id)!),
          stopReason: reason,
        });
      };

      // Schedule (or reschedule) finalize. Called for every turn-complete.
      // The setImmediate gives same-tick trailing events a chance to be
      // processed before unsubscribe; the additional graceTimer covers
      // events that arrive in subsequent ticks (rare but observed when
      // YouCoded's transcript-watcher batches a JSONL flush across ticks).
      const scheduleFinalize = (reason: string) => {
        if (resolved) return;
        if (pendingFinalize) clearImmediate(pendingFinalize);
        if (graceTimer) clearTimeout(graceTimer);
        pendingFinalize = setImmediate(() => {
          pendingFinalize = null;
          // Start the grace window AFTER the current tick drains.
          graceTimer = setTimeout(() => finalize(reason), FINALIZE_GRACE_MS);
        });
      };

      const fail = (err: Error) => {
        if (resolved) return;
        resolved = true;
        unsubscribeTranscript();
        unsubscribeDestroyed();
        if (signal) signal.removeEventListener("abort", abortHandler);
        reject(err);
      };

      const abortHandler = () => finalize("aborted");

      const unsubscribeDestroyed = this.client.onSessionDestroyed(
        (payload) => {
          if (payload.sessionId === conversationId) {
            // Surface as session-died via stopReason; the audit log
            // writer translates this into the appropriate banner.
            finalize("session_died");
          }
        },
      );

      const unsubscribeTranscript = this.client.onTranscriptEvent(
        conversationId,
        (ev: TranscriptEvent) => {
          // When Claude Code redirects an oversized tool_result to a
          // sidecar file, `data.toolResult` arrives as a "result
          // exceeds maximum allowed tokens" message with the path,
          // not the actual JSON. Inline the file contents in-place
          // so downstream parsers (parseTranscriptEvent, the chat
          // reducer's tool blocks, citation-extract) see the real
          // chunks. Without this, every cite() shows "Couldn't open
          // source PDF" because the resolved-chunk map is empty.
          if (ev.type === "tool-result" && ev.data) {
            const inlined = inlineRedirectedToolResult(ev.data.toolResult);
            if (inlined !== ev.data.toolResult) {
              ev.data.toolResult = inlined;
            }
          }
          // Pre-emit accumulator updates — these need to happen even
          // when parseTranscriptEvent returns null (deduplicated
          // assistant_text), because the *latest* text per uuid is the
          // canonical answer text we'll return.
          if (ev.type === "assistant-text") {
            const text = ev.data.text ?? "";
            if (!finalAnswerByUuid.has(ev.uuid)) {
              finalAnswerOrder.push(ev.uuid);
            }
            finalAnswerByUuid.set(ev.uuid, text);
          } else if (ev.type === "tool-use") {
            const toolUseId = ev.data.toolUseId ?? "";
            const summary: ToolCallSummary = {
              toolUseId,
              toolName: ev.data.toolName ?? "",
              input: ev.data.toolInput ?? {},
            };
            if (!toolCallsByUseId.has(toolUseId)) {
              toolCallOrder.push(toolUseId);
            }
            toolCallsByUseId.set(toolUseId, summary);
            // Capture cite() metadata for the audit log.
            if (summary.toolName === "cite") {
              const cite = extractCitation(summary.input);
              if (cite) citations.push(cite);
            }
          } else if (ev.type === "tool-result") {
            const toolUseId = ev.data.toolUseId ?? "";
            const existing = toolCallsByUseId.get(toolUseId);
            if (existing) {
              existing.output = ev.data.toolResult;
              if (ev.data.isError !== undefined) {
                existing.isError = ev.data.isError;
              }
              // If the matching call was a retrieve(), parse the chunk
              // ids out of the JSON payload. Best-effort — malformed
              // bodies just don't contribute, which is fine.
              if (existing.toolName === "retrieve") {
                const ids = extractRetrievedChunkIds(ev.data.toolResult);
                for (const id of ids) retrievedChunkIds.push(id);
              }
            }
          } else if (ev.type === "turn-complete") {
            stopReason = ev.data.stopReason ?? "end_turn";
          }

          // Forward the typed ProviderEvent to the UI. Done after the
          // accumulator updates so the consumer sees consistent state
          // if it queries other things off the side.
          const pev = parseTranscriptEvent(ev, ctx);
          if (pev) safeOnEvent(onEvent, pev);

          // Turn complete? Schedule a deferred finalize. Don't unsubscribe
          // synchronously — see comment at `pendingFinalize` declaration.
          if (ev.type === "turn-complete") {
            scheduleFinalize(stopReason);
          }
        },
      );

      if (signal) {
        if (signal.aborted) {
          finalize("aborted");
          return;
        }
        signal.addEventListener("abort", abortHandler, { once: true });
      }

      // Send the user message with a trailing CR so YouCoded's
      // pty-worker classifies it as a SUBMIT (PITFALLS "PTY Writes" #2).
      // CRITICAL: gate on the first hook event for this session before
      // sending. YouCoded's own UI does this — its InputBar is disabled
      // until `setInitializedSessions` adds the sessionId, which only
      // happens on the first hook event (see App.tsx:665-680). Sending
      // before then races CC's startup banner: the bytes hit the input
      // bar but the trailing \r gets absorbed as paste content because
      // CC is mid-render, leaving the message stranded.
      this.dispatchSendWhenReady(conversationId, userMessage, fail);
    });
  }

  async endConversation(conversationId: string): Promise<void> {
    this.parserContextByConversation.delete(conversationId);
    this.readyState.delete(conversationId);
    const runtimeDir = this.runtimeDirByConversation.get(conversationId);
    this.runtimeDirByConversation.delete(conversationId);
    try {
      await this.client.destroySession(conversationId);
    } catch (err) {
      if (err instanceof YouCodedClientError && err.code === "not_connected") {
        // Still clean up the runtime dir — the session is gone either way.
        if (runtimeDir) await this.removeRuntimeDirSafely(runtimeDir);
        return;
      }
      if (runtimeDir) await this.removeRuntimeDirSafely(runtimeDir);
      throw err;
    }
    if (runtimeDir) await this.removeRuntimeDirSafely(runtimeDir);
  }

  /** Best-effort cleanup of a materialized runtime dir. Failures are
   *  logged but not thrown — a leaked tempdir is annoying but not
   *  worth poisoning the caller's promise chain over. */
  private async removeRuntimeDirSafely(dir: string): Promise<void> {
    try {
      await fs.rm(dir, { recursive: true, force: true });
    } catch (err) {
      process.stderr.write(
        `[youcoded-session-provider] failed to remove runtime dir ${dir}: ${(err as Error).message}\n`,
      );
    }
  }

  /** Test-only / shutdown helper. Tears down the underlying WebSocket
   *  connection; subsequent calls re-connect. */
  async disconnect(): Promise<void> {
    this.connectPromise = null;
    await this.client.disconnect();
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function safeOnEvent(
  cb: (e: ProviderEvent) => void,
  e: ProviderEvent,
): void {
  try {
    cb(e);
  } catch (err) {
    process.stderr.write(
      `[youcoded-session-provider] onEvent listener threw: ${(err as Error).stack ?? err}\n`,
    );
  }
}

function extractCitation(
  input: Record<string, unknown>,
): Citation | null {
  const chunkId = input["chunk_id"];
  const spanStart = input["span_start"];
  const spanEnd = input["span_end"];
  const confidence = input["confidence"];
  const claimSpan = input["claim_span"];
  if (
    typeof chunkId !== "string" ||
    typeof spanStart !== "number" ||
    typeof spanEnd !== "number" ||
    (confidence !== "verbatim" && confidence !== "paraphrase") ||
    typeof claimSpan !== "string"
  ) {
    process.stderr.write(
      `[youcoded-session-provider] dropping malformed cite() input: ${JSON.stringify(input)}\n`,
    );
    return null;
  }
  return {
    chunkId,
    spanStart,
    spanEnd,
    confidence,
    claimSpan,
  };
}

/** Patterns Claude Code uses when a tool result exceeds its max token
 *  budget. Two have been seen in the wild:
 *
 *    A. Token-limit form:
 *       "Error: result (88,629 characters) exceeds maximum allowed
 *        tokens. Output has been saved to <path>.txt."
 *
 *    B. Size-limit form (wrapped in <persisted-output> tags, with a
 *       2KB preview after the path line):
 *       "<persisted-output>\nOutput too large (67.3KB). Full output
 *        saved to: <path>.json\n\nPreview (first 2KB): ..."
 *
 *  Both stash the real `[{type, text}, ...]` JSON at the path. We
 *  follow the redirect and return the inlined `text` so downstream
 *  code (citation extraction, reducer tool blocks) sees the real JSON
 *  instead of the redirect message + preview. The file extension
 *  varies (.txt / .json), so the regex captures any common ext.
 */
const REDIRECT_RES: RegExp[] = [
  /Output has been saved to\s+(\S+?\.(?:txt|json|md))\b/,
  /Full output saved to:\s+(\S+?\.(?:txt|json|md))(?=\s|$)/,
];

function inlineRedirectedToolResult(raw: string | undefined): string | undefined {
  if (!raw) return raw;
  let path: string | null = null;
  for (const re of REDIRECT_RES) {
    const m = raw.match(re);
    if (m) {
      path = m[1]!.trim();
      break;
    }
  }
  if (!path) return raw;
  try {
    const fileText = readFileSync(path, "utf8");
    const parts: unknown = JSON.parse(fileText);
    if (Array.isArray(parts)) {
      for (const part of parts) {
        if (
          part &&
          typeof part === "object" &&
          (part as { type?: unknown }).type === "text" &&
          typeof (part as { text?: unknown }).text === "string"
        ) {
          return (part as { text: string }).text;
        }
      }
    }
    // Fallback: file isn't an array-of-parts; return the raw file
    // contents — at worst the parser sees a JSON it can't parse,
    // which is the same end state as not inlining at all.
    return fileText;
  } catch (err) {
    process.stderr.write(
      `[youcoded-session-provider] failed to inline redirected tool result at ${path}: ${(err as Error).message}\n`,
    );
    return raw;
  }
}

function extractRetrievedChunkIds(toolResult?: string): string[] {
  if (!toolResult) return [];
  try {
    const parsed = JSON.parse(toolResult);
    if (
      parsed &&
      typeof parsed === "object" &&
      Array.isArray((parsed as { chunks?: unknown[] }).chunks)
    ) {
      const chunks = (parsed as { chunks: unknown[] }).chunks;
      return chunks
        .map((c) =>
          c && typeof c === "object" && typeof (c as { chunk_id?: unknown }).chunk_id === "string"
            ? ((c as { chunk_id: string }).chunk_id)
            : null,
        )
        .filter((s): s is string => s !== null);
    }
  } catch {
    // Tool result wasn't JSON; budget retrieve() always emits JSON,
    // but other (general) retrieve-named tools might not. No-op.
  }
  return [];
}
