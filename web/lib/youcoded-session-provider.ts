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

import type {
  Citation,
  LLMProvider,
  SendTurnArgs,
  SendTurnResult,
  StartConversationOpts,
  ToolCallSummary,
} from "./llm-provider.js";
import { parseTranscriptEvent, type ParserContext } from "./transcript-parser.js";
import type { ProviderEvent, TranscriptEvent } from "./types.js";
import {
  YouCodedClient,
  YouCodedClientError,
  type YouCodedClientOptions,
} from "./youcoded-client.js";

const DEFAULT_NAME = "Ask the Budget AZ";

export interface YouCodedSessionProviderOptions
  extends YouCodedClientOptions {
  /** Default cwd applied to startConversation when no override is given.
   *  The web server typically passes the conversation's runtime
   *  directory (where the system-prompt CLAUDE.md is materialized). */
  defaultCwd?: string;
}

export class YouCodedSessionProvider implements LLMProvider {
  private readonly client: YouCodedClient;
  private readonly defaultCwd: string | undefined;
  private connectPromise: Promise<void> | null = null;
  /** Per-session UUID-dedup state for assistant_text emissions. Lives
   *  with the provider so multiple turns in one conversation share it
   *  (Claude's growing-message rewrites can span tool-result boundaries). */
  private parserContextByConversation = new Map<string, ParserContext>();

  constructor(opts: YouCodedSessionProviderOptions = {}) {
    this.client = new YouCodedClient(opts);
    this.defaultCwd = opts.defaultCwd;
  }

  /** Lazy connect — `startConversation` triggers it. Re-uses the same
   *  client connection across many conversations. */
  private async ensureConnected(): Promise<void> {
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
  ): Promise<{ conversationId: string }> {
    await this.ensureConnected();
    const cwd = opts.cwd ?? this.defaultCwd ?? process.cwd();
    const name = opts.name ?? DEFAULT_NAME;
    const info = await this.client.createSession({
      name,
      cwd,
      // Budget conversations auto-approve everything: the system prompt
      // constrains Claude to retrieve/cite for the budget questions, and
      // the analyst opted into the workflow by opening the chat. We do
      // NOT want a permission prompt every time Claude calls retrieve.
      skipPermissions: true,
    });
    this.parserContextByConversation.set(info.id, {
      seenAssistantTextUuids: new Set<string>(),
    });
    return { conversationId: info.id };
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

    return new Promise<SendTurnResult>((resolve, reject) => {
      const finalize = (reason: string) => {
        if (resolved) return;
        resolved = true;
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

          // Turn complete? Resolve.
          if (ev.type === "turn-complete") {
            finalize(stopReason);
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

      // Send the user message. Note YouCoded's PTY layer handles the
      // long-message echo-driven submit logic — we don't append \r
      // here; the wrapper does the right thing. (See PITFALLS "PTY
      // Writes" in the youcoded-dev workspace for the rationale.)
      try {
        this.client.sendInput(conversationId, userMessage);
      } catch (err) {
        fail(err as Error);
      }
    });
  }

  async endConversation(conversationId: string): Promise<void> {
    this.parserContextByConversation.delete(conversationId);
    try {
      await this.client.destroySession(conversationId);
    } catch (err) {
      if (err instanceof YouCodedClientError && err.code === "not_connected") {
        return;
      }
      throw err;
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
