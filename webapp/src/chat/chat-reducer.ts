// Pure chat reducer. Builds a timeline of UserTurn + AssistantTurn
// entries from a stream of ChatActions. The `chatActionFromProviderEvent`
// helper translates a ProviderEvent (whatever the server streams over
// SSE) into the matching ChatAction.
//
// Design points:
//   - One in-flight assistant turn at a time. Opens lazily on the
//     first ASSISTANT_TEXT / TOOL_USE / TOOL_RESULT after a user
//     prompt; closes on TURN_COMPLETE.
//   - text blocks are uuid-keyed: ASSISTANT_TEXT events with the same
//     uuid replace (not append) the existing block's text. This
//     mirrors how YouCoded's transcript-watcher emits growing
//     assistant messages.
//   - tool blocks are appended in arrival order. TOOL_RESULT finds
//     its matching block by toolUseId in the *current* assistant
//     turn and updates status/output.

import type { ProviderEvent } from "./provider-events.js";
import type {
  AssistantBlock,
  AssistantTurn,
  ChatAction,
  ChatState,
  Turn,
} from "./chat-types.js";
import { initialChatState } from "./chat-types.js";

export function chatReducer(state: ChatState, action: ChatAction): ChatState {
  switch (action.type) {
    case "CONVERSATION_STARTED":
      // keepTurns: the resumed-chat first send. The rehydrated turns are the
      // analyst's view of the transcript — resetting to initialChatState here
      // emptied the thread the moment they continued a stored chat (the bug
      // where "resumed" behaved like "new"). A genuinely new chat omits the
      // flag and still gets the clean slate.
      if (action.keepTurns) {
        return { ...state, conversationId: action.conversationId, error: null };
      }
      return {
        ...initialChatState,
        conversationId: action.conversationId,
      };

    case "REHYDRATED":
      // Opening a stored chat replaces the timeline wholesale — it never
      // merges into an existing one. Shaped like CONVERSATION_STARTED
      // (which resets to initialChatState) but carries turns. It ALSO carries
      // the stored chat's id in conversationId: the id is "who this thread
      // is", not "a live session exists" (the server session is still only
      // built on the first send — H2: browsing is free). Recording the id is
      // what lets send() recognize the continuation as a resume rather than a
      // brand-new conversation, and what stops it wiping the turns it just
      // showed the analyst.
      return {
        ...initialChatState,
        conversationId: action.conversationId,
        turns: action.turns,
      };

    case "USER_PROMPT": {
      const userTurn: Turn = {
        kind: "user",
        id: action.clientUuid,
        text: action.text,
        pending: true,
        timestamp: action.timestamp,
      };
      return {
        ...state,
        turns: [...state.turns, userTurn],
        isThinking: true,
        error: null,
      };
    }

    case "USER_MESSAGE_CONFIRMED": {
      // Find the oldest pending user entry whose text matches and clear
      // its pending flag (mirrors YouCoded's pending-flag dedup pattern).
      // If none matches, append the transcript's user message — covers
      // the "user typed directly into the terminal" / replay edge case.
      const idx = state.turns.findIndex(
        (t) => t.kind === "user" && t.pending && t.text === action.text,
      );
      if (idx >= 0) {
        const existing = state.turns[idx] as Turn & { kind: "user" };
        const updated: Turn = { ...existing, pending: false };
        const next = state.turns.slice();
        next[idx] = updated;
        return { ...state, turns: next };
      }
      return {
        ...state,
        turns: [
          ...state.turns,
          {
            kind: "user",
            id: action.uuid,
            text: action.text,
            pending: false,
            timestamp: action.timestamp,
          },
        ],
      };
    }

    case "ASSISTANT_TEXT": {
      return upsertAssistantTurn(state, action.timestamp, (turn) => {
        const existingIdx = turn.blocks.findIndex(
          (b) => b.kind === "text" && b.uuid === action.uuid,
        );
        if (existingIdx >= 0) {
          // Same uuid, growing message — replace text in place.
          const blocks = turn.blocks.slice();
          const existing = blocks[existingIdx] as AssistantBlock & {
            kind: "text";
          };
          blocks[existingIdx] = {
            ...existing,
            text: action.text,
            ...(action.model !== undefined ? { model: action.model } : {}),
          };
          return {
            ...turn,
            blocks,
            ...(action.model !== undefined && !turn.model
              ? { model: action.model }
              : {}),
          };
        }
        // New text block.
        const block: AssistantBlock = {
          kind: "text",
          uuid: action.uuid,
          text: action.text,
          ...(action.model !== undefined ? { model: action.model } : {}),
        };
        return {
          ...turn,
          blocks: [...turn.blocks, block],
          ...(action.model !== undefined && !turn.model
            ? { model: action.model }
            : {}),
        };
      });
    }

    case "ASSISTANT_THINKING":
      // Heartbeat only — the timeline doesn't surface a block for it.
      // The hook on the renderer side may use these to keep
      // ThinkingIndicator alive past stretches without text.
      return { ...state, isThinking: true };

    case "TOOL_USE": {
      return upsertAssistantTurn(state, action.timestamp, (turn) => {
        // Avoid double-add if the same toolUseId arrives twice (shouldn't
        // happen, but defensive — YouCoded's reducer has a similar guard).
        if (turn.blocks.some(
          (b) => b.kind === "tool" && b.toolUseId === action.toolUseId,
        )) {
          return turn;
        }
        const block: AssistantBlock = {
          kind: "tool",
          toolUseId: action.toolUseId,
          toolName: action.toolName,
          input: action.input,
          status: "running",
        };
        return { ...turn, blocks: [...turn.blocks, block] };
      });
    }

    case "TOOL_RESULT": {
      // Find the matching tool block in the current assistant turn and
      // update its status. If the tool isn't found (race / stale state),
      // create a synthetic completed block — keeps the UI consistent.
      return upsertAssistantTurn(state, action.timestamp, (turn) => {
        const idx = turn.blocks.findIndex(
          (b) => b.kind === "tool" && b.toolUseId === action.toolUseId,
        );
        if (idx >= 0) {
          const blocks = turn.blocks.slice();
          const existing = blocks[idx] as AssistantBlock & { kind: "tool" };
          blocks[idx] = {
            ...existing,
            status: action.isError ? "failed" : "complete",
            output: action.output,
            ...(action.isError !== undefined
              ? { isError: action.isError }
              : {}),
            ...(action.structuredPatch !== undefined
              ? { structuredPatch: action.structuredPatch }
              : {}),
          };
          return { ...turn, blocks };
        }
        // Synthetic — tool_result without a tool_use. Should not normally
        // happen but is safer than dropping the result.
        const block: AssistantBlock = {
          kind: "tool",
          toolUseId: action.toolUseId,
          toolName: "(unknown)",
          input: {},
          status: action.isError ? "failed" : "complete",
          output: action.output,
          ...(action.isError !== undefined ? { isError: action.isError } : {}),
        };
        return { ...turn, blocks: [...turn.blocks, block] };
      });
    }

    case "TURN_COMPLETE": {
      // Close the in-flight turn (if any), attach metadata. If no turn
      // is open, do nothing — defensive against stray events.
      const idx = lastOpenAssistantIndex(state);
      if (idx < 0) {
        // The turn is ALREADY closed — the normal case for the `_done`
        // frame, which arrives after `turn_complete` has closed it. `_done`
        // is the only frame carrying the figure annotation, so returning
        // early here would drop every figure chip in production while every
        // unit test still passed. Attach it to the turn that just closed.
        const closedIdx = lastAssistantIndex(state);
        if (action.annotation === undefined || closedIdx < 0) {
          return { ...state, isThinking: false };
        }
        const turns = [...state.turns];
        turns[closedIdx] = {
          ...(turns[closedIdx] as AssistantTurn),
          annotation: action.annotation,
        };
        return { ...state, turns, isThinking: false };
      }
      const existing = state.turns[idx] as AssistantTurn;
      const closed: AssistantTurn = {
        ...existing,
        isComplete: true,
        stopReason: action.stopReason,
        ...(action.model !== undefined ? { model: action.model } : {}),
        ...(action.anthropicRequestId !== undefined
          ? { anthropicRequestId: action.anthropicRequestId }
          : {}),
        ...(action.usage !== undefined ? { usage: action.usage } : {}),
        // Only overwrite when the frame actually carried one. `turn_complete`
        // arrives just before `_done` and has no annotation; letting it write
        // `undefined` would erase the annotation the very next event brings.
        ...(action.annotation !== undefined
          ? { annotation: action.annotation }
          : {}),
      };
      const turns = state.turns.slice();
      turns[idx] = closed;
      return { ...state, turns, isThinking: false };
    }

    case "TURN_ERROR":
      return failOpenTools(
        { ...state, isThinking: false, error: action.message },
        "Turn errored",
      );

    case "CONNECTION_LOST":
      return failOpenTools(
        { ...state, isThinking: false, error: action.message },
        "Connection lost",
      );

    case "CLEAR_ERROR":
      return { ...state, error: null };

    default: {
      const _exhaustive: never = action;
      void _exhaustive;
      return state;
    }
  }
}

// ---------------------------------------------------------------------------
// ProviderEvent → ChatAction translation
// ---------------------------------------------------------------------------

/**
 * Translate one streamed ProviderEvent into a ChatAction. Returns null
 * when the event has no UI-visible action (e.g. compact_summary, or
 * the user_message that was already optimistically applied).
 */
export function chatActionFromProviderEvent(
  ev: ProviderEvent,
): ChatAction | null {
  switch (ev.type) {
    case "user_message":
      return {
        type: "USER_MESSAGE_CONFIRMED",
        uuid: ev.uuid,
        text: ev.text,
        timestamp: ev.timestamp,
      };
    case "user_interrupt":
      // Treated as turn-end + flag. For now we surface it as a turn
      // error message; the user can clear it and continue.
      return { type: "TURN_ERROR", message: "Turn interrupted" };
    case "assistant_text_delta":
      return {
        type: "ASSISTANT_TEXT",
        uuid: ev.uuid,
        text: ev.text,
        ...(ev.model !== undefined ? { model: ev.model } : {}),
        timestamp: ev.timestamp,
      };
    case "assistant_thinking":
      return {
        type: "ASSISTANT_THINKING",
        uuid: ev.uuid,
        timestamp: ev.timestamp,
      };
    case "tool_use":
      return {
        type: "TOOL_USE",
        toolUseId: ev.toolUseId,
        toolName: ev.toolName,
        input: ev.input,
        uuid: ev.uuid,
        timestamp: ev.timestamp,
      };
    case "tool_result":
      return {
        type: "TOOL_RESULT",
        toolUseId: ev.toolUseId,
        output: ev.output,
        ...(ev.isError !== undefined ? { isError: ev.isError } : {}),
        ...(ev.structuredPatch !== undefined
          ? { structuredPatch: ev.structuredPatch }
          : {}),
        uuid: ev.uuid,
        timestamp: ev.timestamp,
      };
    case "turn_complete":
      return {
        type: "TURN_COMPLETE",
        stopReason: ev.stopReason,
        ...(ev.model !== undefined ? { model: ev.model } : {}),
        ...(ev.anthropicRequestId !== undefined
          ? { anthropicRequestId: ev.anthropicRequestId }
          : {}),
        ...(ev.usage !== undefined ? { usage: ev.usage } : {}),
        uuid: ev.uuid,
        timestamp: ev.timestamp,
      };
    case "compact_summary":
      // No timeline impact — compact summaries are out of scope for
      // the budget UI in v1. Could surface a divider in the future.
      return null;
    default: {
      const _exhaustive: never = ev;
      void _exhaustive;
      return null;
    }
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Returns -1 if no open assistant turn exists. */
/** The most recent assistant turn regardless of whether it is still open.
 *  Needed because the annotation arrives on `_done`, one frame AFTER
 *  `turn_complete` has already closed the turn it belongs to. */
function lastAssistantIndex(state: ChatState): number {
  for (let i = state.turns.length - 1; i >= 0; i--) {
    const t = state.turns[i];
    if (t && t.kind === "assistant") return i;
  }
  return -1;
}

function lastOpenAssistantIndex(state: ChatState): number {
  for (let i = state.turns.length - 1; i >= 0; i--) {
    const t = state.turns[i];
    if (t && t.kind === "assistant" && !t.isComplete) return i;
  }
  return -1;
}

/**
 * Apply `mutate` to the open assistant turn. If none is open, create
 * a new one (uses the action's timestamp as the seed). Returns a new
 * ChatState with the turn updated/appended.
 */
function upsertAssistantTurn(
  state: ChatState,
  timestamp: number,
  mutate: (turn: AssistantTurn) => AssistantTurn,
): ChatState {
  const idx = lastOpenAssistantIndex(state);
  if (idx >= 0) {
    const turn = state.turns[idx] as AssistantTurn;
    const updated = mutate(turn);
    if (updated === turn) return state;
    const turns = state.turns.slice();
    turns[idx] = ensureTurnId(updated);
    return { ...state, turns };
  }
  const turn: AssistantTurn = {
    kind: "assistant",
    id: "pending",
    blocks: [],
    isComplete: false,
    timestamp,
  };
  const updated = ensureTurnId(mutate(turn));
  return { ...state, turns: [...state.turns, updated], isThinking: true };
}

/** A new turn's `id` is set from its first block's identifier so React
 *  keys stay stable as the turn fills in. */
function ensureTurnId(turn: AssistantTurn): AssistantTurn {
  if (turn.id !== "pending") return turn;
  const first = turn.blocks[0];
  if (!first) return turn;
  const id = first.kind === "text" ? first.uuid : first.toolUseId;
  return { ...turn, id };
}

/** When a connection drops or an error fires mid-turn, every running
 *  tool block should flip to `failed` so the UI doesn't show stale
 *  spinners. Mirrors YouCoded's `endTurn()` helper. */
function failOpenTools(state: ChatState, errMsg: string): ChatState {
  const idx = lastOpenAssistantIndex(state);
  if (idx < 0) return state;
  const turn = state.turns[idx] as AssistantTurn;
  let changed = false;
  const blocks = turn.blocks.map((b) => {
    if (b.kind === "tool" && b.status === "running") {
      changed = true;
      return { ...b, status: "failed" as const, output: errMsg, isError: true };
    }
    return b;
  });
  if (!changed) return state;
  const turns = state.turns.slice();
  turns[idx] = { ...turn, blocks, isComplete: true, stopReason: "error" };
  return { ...state, turns };
}
