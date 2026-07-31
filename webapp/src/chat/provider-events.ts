// ProviderEvent — what the LLMProvider streams to its callers.
//
// Ported from `web/lib/types.ts` (the Next.js app's wire-protocol file,
// which mixed ProviderEvent with YouCoded's WebSocket envelopes). This
// file carries ONLY the ProviderEvent section: TurnUsage, the
// StructuredPatchHunk shape it references, and the ProviderEvent union
// itself. The YouCoded-specific wire types (SessionInfo, AuthRequest,
// TranscriptEvent, and the rest of the `ws://localhost:9900` envelope
// shapes) do not carry over — Plan 4 replaced the YouCoded desktop app
// + MCP server with an in-process Python OpenRouter tool loop
// (`harness/session.py`), which emits this same event shape directly
// over SSE instead of over a WebSocket transcript bridge.

/** jsdiff-style hunk shipped on Edit/MultiEdit tool results. */
export interface StructuredPatchHunk {
  oldStart: number;
  oldLines: number;
  newStart: number;
  newLines: number;
  /** Each string begins with ' ' (context), '-' (deletion), or '+' (addition). */
  lines: string[];
}

export interface TurnUsage {
  inputTokens: number;
  outputTokens: number;
  cacheReadTokens: number;
  cacheCreationTokens: number;
}

/** One-to-one mapping with the old TranscriptEventType but in
 *  JS-idiomatic shapes and snake_case→camelCase as appropriate.
 *  Critically, **all tool types flow through generic tool_use /
 *  tool_result events** — the provider does not special-case
 *  retrieve/cite. The UI routes per-tool rendering by toolName. */
export type ProviderEvent =
  | { type: "user_message"; text: string; uuid: string; timestamp: number }
  | {
      type: "user_interrupt";
      kind: "plain" | "tool-use";
      uuid: string;
      timestamp: number;
    }
  | {
      type: "assistant_text_delta";
      text: string;
      model?: string;
      uuid: string;
      timestamp: number;
    }
  | { type: "assistant_thinking"; uuid: string; timestamp: number }
  | {
      type: "tool_use";
      toolUseId: string;
      toolName: string;
      input: Record<string, unknown>;
      uuid: string;
      timestamp: number;
    }
  | {
      type: "tool_result";
      toolUseId: string;
      output: string;
      isError?: boolean;
      structuredPatch?: StructuredPatchHunk[];
      uuid: string;
      timestamp: number;
    }
  | {
      type: "turn_complete";
      stopReason: string;
      model?: string;
      anthropicRequestId?: string;
      usage?: TurnUsage;
      uuid: string;
      timestamp: number;
    }
  | { type: "compact_summary"; uuid: string; timestamp: number };
