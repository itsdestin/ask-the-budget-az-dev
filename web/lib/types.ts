// Wire-protocol types mirrored from YouCoded's source (NOT imported — D9
// forbids vendoring). When YouCoded adds a transcript event type or
// changes a payload field, that's a wire-protocol change the budget app
// has to track here. The reference is
// `youcoded/desktop/src/shared/types.ts` in the YouCoded workspace.
//
// Wire format on `ws://localhost:9900/ws`:
//   client→server: `{ type, id?, payload?, ... }`
//   server→client: same shape; responses use `<original>:response` and
//                  echo the request's `id`.

// ---------------------------------------------------------------------------
// SessionInfo — payload of session:create / session:created / session:list
// ---------------------------------------------------------------------------

export type PermissionMode =
  | "normal"
  | "auto-accept"
  | "plan"
  | "auto"
  | "bypass";

export type SessionProvider = "claude" | "gemini";

export interface SessionInfo {
  id: string;
  name: string;
  cwd: string;
  permissionMode: PermissionMode;
  skipPermissions: boolean;
  status: "active" | "idle" | "destroyed";
  createdAt: number;
  provider: SessionProvider;
  model?: string;
  initialInput?: string;
}

/** Subset of SessionInfo accepted by `session:create`. The server fills
 *  in id/status/createdAt/provider defaults. */
export interface CreateSessionOpts {
  name: string;
  cwd: string;
  permissionMode?: PermissionMode;
  skipPermissions?: boolean;
  model?: string;
  provider?: SessionProvider;
}

// ---------------------------------------------------------------------------
// TranscriptEvent — the load-bearing chat-state stream
// ---------------------------------------------------------------------------

export type TranscriptEventType =
  | "user-message"
  | "assistant-text"
  | "tool-use"
  | "tool-result"
  | "thinking"
  | "assistant-thinking"
  | "turn-complete"
  | "compact-summary"
  | "user-interrupt";

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

export interface TranscriptEventData {
  text?: string;
  toolUseId?: string;
  toolName?: string;
  toolInput?: Record<string, unknown>;
  toolResult?: string;
  isError?: boolean;
  stopReason?: string;
  structuredPatch?: StructuredPatchHunk[];
  model?: string;
  anthropicRequestId?: string;
  usage?: TurnUsage;
  parentAgentToolUseId?: string;
  agentId?: string;
  /** user-interrupt marker variant. */
  kind?: "plain" | "tool-use";
}

export interface TranscriptEvent {
  type: TranscriptEventType;
  sessionId: string;
  /** JSONL line uuid; used to dedup repeated assistant-text emissions
   *  (Claude rewrites growing messages — same uuid, growing text). */
  uuid: string;
  timestamp: number;
  data: TranscriptEventData;
}

// ---------------------------------------------------------------------------
// ProviderEvent — what the LLMProvider streams to its callers
// ---------------------------------------------------------------------------
//
// One-to-one mapping with TranscriptEventType but in JS-idiomatic shapes
// and snake_case→camelCase as appropriate. Critically, **all tool types
// flow through generic tool_use / tool_result events** — the provider
// does not special-case retrieve/cite. The UI (Phase 1c WS4) routes
// per-tool rendering by toolName.

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

// ---------------------------------------------------------------------------
// WebSocket message envelopes
// ---------------------------------------------------------------------------

export interface AuthRequest {
  type: "auth";
  token?: string;
  password?: string;
}

export type AuthResponse =
  | { type: "auth:ok"; token: string; platform: "desktop" | "android" }
  | { type: "auth:failed"; reason: string };

/** Server→client transcript broadcast. */
export interface TranscriptEventMessage {
  type: "transcript:event";
  payload: TranscriptEvent;
}

export interface SessionCreateRequest {
  type: "session:create";
  id: string;
  payload: CreateSessionOpts;
}

export interface SessionCreateResponse {
  type: "session:create:response";
  id: string;
  payload: SessionInfo;
}

export interface SessionInputMessage {
  type: "session:input";
  payload: { sessionId: string; text: string };
}

export interface SessionDestroyRequest {
  type: "session:destroy";
  id: string;
  payload: { sessionId: string };
}

export interface SessionDestroyResponse {
  type: "session:destroy:response";
  id: string;
  payload: boolean;
}

export interface SessionCreatedBroadcast {
  type: "session:created";
  payload: SessionInfo;
}

export interface SessionDestroyedBroadcast {
  type: "session:destroyed";
  payload: { sessionId: string; exitCode?: number };
}
