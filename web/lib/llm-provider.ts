// LLMProvider — the abstraction the budget app uses to talk to whatever
// is generating answers. Per decision D11, the seam is preserved even
// though v1 ships exactly one implementation (YouCodedSessionProvider).
// Phase 2/3/4 add LocalCompanionProvider / AnthropicAPIProvider /
// SelfHostedLLMProvider behind the same interface.
//
// The interface is **multi-turn** (decision D4): a conversation is one
// long-lived session; follow-up messages go to the same session so
// Claude has full context for anaphora and drill-downs. `startConversation`
// opens it; `sendTurn` runs one user-input → final-answer cycle within
// it; `endConversation` tears it down.

import type { ProviderEvent } from "./types.js";

// ---------------------------------------------------------------------------
// Citation + refusal types — surfaced post-turn from the transcript
// ---------------------------------------------------------------------------

/** One `cite()` tool call extracted from the transcript. The `claimSpan`
 *  is the literal substring of the assistant answer the chip attaches
 *  to (per the schema doc); the UI does substring search to render. */
export interface Citation {
  chunkId: string;
  spanStart: number;
  spanEnd: number;
  confidence: "verbatim" | "paraphrase";
  claimSpan: string;
}

/** Three refusal modes per spec §11. Populated by post-streaming logic
 *  that inspects the assistant text and the chunks shown — for v1, the
 *  LLMProvider returns `undefined` and lets the audit-log writer (WS5)
 *  classify based on the answer text and the cite-call pattern. */
export type RefusalReason =
  | { type: "no_retrieval" }
  | { type: "synthesis"; chunksShown: string[] }
  | { type: "out_of_scope" };

// ---------------------------------------------------------------------------
// Multi-turn provider interface
// ---------------------------------------------------------------------------

export interface SendTurnArgs {
  conversationId: string;
  userMessage: string;
  /** Streaming callback for every event in the turn — assistant text,
   *  tool_use, tool_result, thinking heartbeats, etc. The UI side
   *  routes per-event-type; the provider does not filter. Errors thrown
   *  by `onEvent` are caught so a buggy listener can't break the turn
   *  loop. */
  onEvent: (e: ProviderEvent) => void;
  /** Optional abort signal — when fired, the provider stops streaming
   *  and resolves the turn promise with whatever has been accumulated.
   *  Used by the UI's "stop" button. */
  signal?: AbortSignal;
}

export interface SendTurnResult {
  /** The assistant's final text (concatenation of latest assistant_text
   *  per uuid). Useful for the audit log. */
  finalAnswer: string;
  /** Citations extracted from the transcript by filtering tool_use
   *  events with toolName === "cite". Schema-validated; malformed
   *  cites are dropped (logged to stderr). */
  citations: Citation[];
  /** Chunk ids returned by every retrieve() tool call in this turn —
   *  the audit log writer correlates retrieve()→cite() pairs by these. */
  retrievedChunkIds: string[];
  /** All tool_use calls in the turn, in order — keyed by toolUseId for
   *  audit-log mapping. Includes retrieve/cite as well as any general
   *  tools Claude used (Bash, Grep, Read, Edit, Agent, etc.). */
  toolCalls: ToolCallSummary[];
  /** Reason the model stopped — "end_turn", "max_tokens", "tool_use"
   *  (mid-turn — shouldn't reach here), "stop_sequence", "refusal", … */
  stopReason: string;
  /** Optional refusal classification. v1 returns `undefined` and lets
   *  Phase 1c WS3 (faithfulness verifier) and WS5 (audit log) decide. */
  refusal?: RefusalReason;
}

export interface ToolCallSummary {
  toolUseId: string;
  toolName: string;
  input: Record<string, unknown>;
  /** The tool_result string content. `undefined` means no result event
   *  arrived before turn-complete (rare; possible if the turn errored). */
  output?: string;
  isError?: boolean;
}

/** What `startConversation` returns. `health` lets the UI render a
 *  banner BEFORE the user's first turn when the retrieval sidecar
 *  isn't reachable — instead of letting them discover the failure
 *  mid-answer. Non-YouCoded providers (e.g., mock providers used in
 *  tests) can return `{ ok: true }` without a probe. */
export interface StartConversationResult {
  conversationId: string;
  health: { ok: boolean; reason?: string };
}

export interface LLMProvider {
  /** Open a new conversation. The returned id is opaque — the caller
   *  passes it back to `sendTurn` and `endConversation`. The `health`
   *  field reports whether the retrieval sidecar (the source of every
   *  budget answer) is reachable; the UI uses it to render a banner
   *  BEFORE the user types their first question. */
  startConversation(
    opts?: StartConversationOpts,
  ): Promise<StartConversationResult>;

  /** Send one user message and stream the assistant turn until
   *  `turn_complete`. Resolves with the accumulated state. */
  sendTurn(args: SendTurnArgs): Promise<SendTurnResult>;

  /** Tear down the conversation. After this, `conversationId` is no
   *  longer valid. */
  endConversation(conversationId: string): Promise<void>;
}

export interface StartConversationOpts {
  /** Working directory for the underlying session. The Phase 1c web
   *  server materializes the system prompt as `<cwd>/CLAUDE.md` per
   *  the YouCoded API verification doc. */
  cwd?: string;
  /** Display name for the session pill in YouCoded's UI. Defaults to
   *  something budget-flavored. */
  name?: string;
}
