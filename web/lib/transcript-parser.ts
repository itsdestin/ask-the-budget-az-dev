// Translates YouCoded TranscriptEvent shapes into ProviderEvent shapes
// the budget app's UI consumes. **All tool types pass through generically**
// — the user can ask Claude to grep, read files, run commands, etc.
// alongside the budget-specific retrieve/cite tools (decision D5: Claude
// keeps general tools), and every one of them must surface for the UI
// to render.
//
// The parser is pure (no I/O), and stateful only via an optional UUID
// dedup set the caller threads through — Claude rewrites growing
// `assistant-text` messages with the same uuid (per
// `youcoded/desktop/src/main/transcript-watcher.ts`), so emitting them
// blindly produces N copies of the same prefix. The UI works against
// per-uuid-final-text instead.

import type {
  ProviderEvent,
  TranscriptEvent,
  TranscriptEventData,
} from "./types.js";

export interface ParserContext {
  /** Mutable set of uuids already emitted as assistant_text_delta. The
   *  caller owns the lifetime — typically per-conversation. Pass the
   *  same set across calls. */
  seenAssistantTextUuids?: Set<string>;
}

/**
 * Convert one TranscriptEvent into a ProviderEvent. Returns `null` when
 * the event should be filtered (currently: repeated `assistant-text`
 * uuids and 'thinking' which carries no UI signal).
 *
 * `'thinking'` and `'assistant-thinking'` are merged: both signal "Claude
 * is producing internal thought, no chat text" and the UI handles them
 * identically as a heartbeat.
 */
export function parseTranscriptEvent(
  ev: TranscriptEvent,
  ctx: ParserContext = {},
): ProviderEvent | null {
  const { type, uuid, timestamp, data } = ev;

  switch (type) {
    case "user-message":
      return {
        type: "user_message",
        text: data.text ?? "",
        uuid,
        timestamp,
      };

    case "user-interrupt":
      return {
        type: "user_interrupt",
        kind: data.kind ?? "plain",
        uuid,
        timestamp,
      };

    case "assistant-text": {
      // Dedup: Claude rewrites a growing message with the same uuid.
      // The UI wants the *latest* text per uuid; emitting every
      // intermediate would render the same text N times concatenated.
      // We surface only the first emission per uuid; the caller is
      // expected to pair this stream with a UUID-keyed text store on
      // the UI side that overwrites instead of appending. (Decision
      // mirrors YouCoded's reducer's approach to this same problem.)
      if (ctx.seenAssistantTextUuids) {
        if (ctx.seenAssistantTextUuids.has(uuid)) return null;
        ctx.seenAssistantTextUuids.add(uuid);
      }
      return {
        type: "assistant_text_delta",
        text: data.text ?? "",
        ...(data.model !== undefined ? { model: data.model } : {}),
        uuid,
        timestamp,
      };
    }

    case "thinking":
    case "assistant-thinking":
      // Both kinds collapse to one "Claude is thinking" heartbeat.
      // Drives ThinkingIndicator UI; carries no text. Stays per-uuid
      // distinguishable in case the UI wants to count them.
      return { type: "assistant_thinking", uuid, timestamp };

    case "tool-use":
      return {
        type: "tool_use",
        toolUseId: data.toolUseId ?? "",
        toolName: data.toolName ?? "",
        input: data.toolInput ?? {},
        uuid,
        timestamp,
      };

    case "tool-result":
      return {
        type: "tool_result",
        toolUseId: data.toolUseId ?? "",
        output: data.toolResult ?? "",
        ...(data.isError !== undefined ? { isError: data.isError } : {}),
        ...(data.structuredPatch !== undefined
          ? { structuredPatch: data.structuredPatch }
          : {}),
        uuid,
        timestamp,
      };

    case "turn-complete":
      return {
        type: "turn_complete",
        stopReason: data.stopReason ?? "end_turn",
        ...(data.model !== undefined ? { model: data.model } : {}),
        ...(data.anthropicRequestId !== undefined
          ? { anthropicRequestId: data.anthropicRequestId }
          : {}),
        ...(data.usage !== undefined ? { usage: data.usage } : {}),
        uuid,
        timestamp,
      };

    case "compact-summary":
      return { type: "compact_summary", uuid, timestamp };

    default: {
      // Exhaustiveness guard. Adding a new TranscriptEventType requires
      // updating this switch — the never-assert flags it at compile time.
      const _exhaustive: never = type;
      void _exhaustive;
      void data; // satisfy unused-locals in pathological future
      return null;
    }
  }
}
