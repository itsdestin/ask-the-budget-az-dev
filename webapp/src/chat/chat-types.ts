// Chat state shape consumed by the renderer. Mirrors YouCoded's
// flat-timeline-of-turns model from chat-reducer.ts but narrower —
// no permission flow (we set skipPermissions on the YouCoded session
// per the budget app's design), no group/agent timelines, no
// optimistic-vs-confirmed dedup (one client emits all events for one
// conversation, no remote replay layer like YouCoded's port-9900 has
// to support).

import type { StructuredPatchHunk } from "./provider-events.js";

/**
 * Inside an assistant turn the model alternates between text and tool
 * calls. We preserve their arrival order in `blocks`, so the UI can
 * render text → ToolCard → text → ToolCard … the way YouCoded does.
 */
export type AssistantBlock =
  | {
      kind: "text";
      uuid: string;
      text: string;
      model?: string;
    }
  | {
      kind: "tool";
      toolUseId: string;
      toolName: string;
      input: Record<string, unknown>;
      status: "running" | "complete" | "failed";
      output?: string;
      isError?: boolean;
      structuredPatch?: StructuredPatchHunk[];
    };

export interface UserTurn {
  kind: "user";
  /** Stable id for React keying; we use a uuid from the client when we
   *  optimistically append the entry, then accept the transcript's
   *  uuid if it differs. */
  id: string;
  text: string;
  /** True when the entry was added optimistically (before the
   *  transcript event arrived) and not yet confirmed. */
  pending: boolean;
  timestamp: number;
}

export interface AssistantTurn {
  kind: "assistant";
  /** Stable id for React keying — the uuid of the first block. */
  id: string;
  blocks: AssistantBlock[];
  isComplete: boolean;
  stopReason?: string;
  model?: string;
  anthropicRequestId?: string;
  /** The server's figure annotation, from the `_done` frame: what every
   *  figure in this turn's answer is backed by. Absent on turns that
   *  predate citation linking, and on turns that ended in an error. */
  annotation?: unknown;
  /** Token + cache usage from the turn-complete event. */
  usage?: {
    inputTokens: number;
    outputTokens: number;
    cacheReadTokens: number;
    cacheCreationTokens: number;
  };
  timestamp: number;
}

export type Turn = UserTurn | AssistantTurn;

export interface ChatState {
  conversationId: string | null;
  turns: Turn[];
  /** True between USER_PROMPT and TURN_COMPLETE; drives the
   *  ThinkingIndicator. Cleared on TURN_ERROR / CONNECTION_LOST too. */
  isThinking: boolean;
  /** Most-recent error surfaced to the UI (connection drop, server
   *  error, etc.). UI shows it as a banner; the user can dismiss. */
  error: string | null;
}

export const initialChatState: ChatState = {
  conversationId: null,
  turns: [],
  isThinking: false,
  error: null,
};

// ---------------------------------------------------------------------------
// Reducer actions
// ---------------------------------------------------------------------------

/**
 * Action shapes the reducer accepts. The `from-provider-event` helpers
 * in `chat-reducer.ts` translate ProviderEvent shapes into these
 * actions; the renderer dispatches `USER_PROMPT` and `CONVERSATION_STARTED`
 * directly.
 */
export type ChatAction =
  | {
      type: "CONVERSATION_STARTED";
      conversationId: string;
      /** When true the timeline is PRESERVED, not reset — the first send of a
       *  resumed chat, where the rehydrated turns are already on screen and
       *  wiping them would make the transcript vanish the moment the analyst
       *  continues it. Absent/false on a genuinely new chat, which resets. */
      keepTurns?: boolean;
    }
  | { type: "REHYDRATED"; conversationId: string | null; turns: Turn[] }
  | { type: "USER_PROMPT"; text: string; clientUuid: string; timestamp: number }
  | {
      type: "USER_MESSAGE_CONFIRMED";
      uuid: string;
      text: string;
      timestamp: number;
    }
  | {
      type: "ASSISTANT_TEXT";
      uuid: string;
      text: string;
      model?: string;
      timestamp: number;
    }
  | { type: "ASSISTANT_THINKING"; uuid: string; timestamp: number }
  | {
      type: "TOOL_USE";
      toolUseId: string;
      toolName: string;
      input: Record<string, unknown>;
      uuid: string;
      timestamp: number;
    }
  | {
      type: "TOOL_RESULT";
      toolUseId: string;
      output: string;
      isError?: boolean;
      structuredPatch?: StructuredPatchHunk[];
      uuid: string;
      timestamp: number;
    }
  | {
      type: "TURN_COMPLETE";
      stopReason: string;
      model?: string;
      anthropicRequestId?: string;
      annotation?: unknown;
      usage?: AssistantTurn["usage"];
      uuid: string;
      timestamp: number;
    }
  | { type: "TURN_ERROR"; message: string }
  | { type: "CONNECTION_LOST"; message: string }
  | { type: "CLEAR_ERROR" };
