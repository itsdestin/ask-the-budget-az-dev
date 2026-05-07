---
title: YouCoded port-9900 remote API verification (pre-flight for Phase 1c WS2)
date: 2026-05-06
status: verified
investigator: Claude
audience: Phase 1c WS2 implementer (`YouCodedSessionProvider`)
---

# YouCoded remote API verification

Pre-flight check from the 2026-05-06 architecture reframe (decision D3 — v1 piggybacks on a running YouCoded instance). Confirms the WebSocket surface at `ws://localhost:9900/ws` exposes everything `YouCodedSessionProvider` needs, and flags the few gaps the implementer will have to design around.

Source code read: `youcoded/desktop/src/main/remote-server.ts` (HEAD on the workspace clone, 2026-05-06) plus `session-manager.ts:CreateSessionOpts`, `ipc-handlers.ts` transcript broadcast.

## What works

| Need | Wire format | Notes |
|------|-------------|-------|
| Connect | WebSocket to `ws://localhost:9900/ws` | HTTP server also serves the YouCoded UI; the WS path is `/ws` |
| Auth | Send `{ type: "auth", password: "<pw>", token?: "<existing>" }`. Receive `{ type: "auth:ok", token, platform: "desktop" }` or `{ type: "auth:failed", reason }` | 5s auth timeout; rate-limited to 5 failed attempts per minute per IP |
| Token reuse | Tokens persist in `~/.claude/.remote-tokens.json` (mode 0600). Sending `{ token }` skips password verification | Token survives across restarts; invalidated by password change |
| Create session | `{ type: "session:create", id: "<msg-id>", payload: { name, cwd, skipPermissions, model?, provider? } }` returns `{ type: "session:create:response", id, payload: <SessionInfo> }` | Payload shape: `CreateSessionOpts` from `session-manager.ts:15` |
| Send user message | `{ type: "session:input", payload: { sessionId, text } }` (fire-and-forget) | Goes through `SessionManager.sendInput` → PTY worker; PTY-paste-threshold chunking is handled YouCoded-side |
| Stream transcript events | Server broadcasts `{ type: "transcript:event", payload: TranscriptEvent }` to all auth'd clients on every parsed JSONL line | Includes `user-message`, `assistant-text`, `tool-use`, `tool-result`, `assistant-thinking`, `user-interrupt`, `turn-complete` |
| Initial sync | On connect, server sends `{ type: "chat:hydrate", payload: SerializedChatState }` after a ~500 ms delay, plus `session:list:response`, `session:created` per session, `session:renamed` per topic | Provides full conversation history to date — budget app will largely ignore for Phase 1c v1 since each conversation starts fresh |
| Session destroy | `{ type: "session:destroy", payload: { sessionId } }` | Returns boolean; broadcasts `session:destroyed` |

The transcript-event stream is the load-bearing finding: it's where the budget UI will see Claude's `tool_use` blocks for `retrieve()` and `cite()`, parsed structurally, no prompt-marker sniffing required.

## What's missing from `session:create`

`CreateSessionOpts` accepts only `{ name, cwd, skipPermissions, cols, rows, resumeSessionId, model, provider }`. There is **no** field for:

1. **Custom system prompt.** Cannot be passed at session creation.
2. **Per-session MCP server set.** All MCP servers come from `~/.claude.json` (Claude Code's global MCP config) — registered once, available to every session.
3. **Tool whitelist / permission overrides.** Picked up from settings.json; cannot be overridden per session.

### Implications for `YouCodedSessionProvider`

- **System prompt:** put the constrained-agent rules in a `CLAUDE.md` file at a budget-specific working directory. `CreateSessionOpts.cwd` ensures Claude Code reads it. The budget app can either (a) check that file in to a shared location, or (b) write/refresh it at session start. Approach (b) is simpler and ensures the prompt stays in sync with the MCP tool definitions.
- **MCP server registration:** the budget MCP server registers itself once in `~/.claude.json` (same mechanism as `wecoded-marketplace/spotify-services` plugin). Either ship as a Claude Code plugin and let YouCoded auto-install it, or write the config entry directly during budget-app setup. Phase 1c WS1 needs to pick a path — leaning toward "register on budget-app first launch via a setup script."
- **General-tool availability (D5):** since tools are not per-session, all the standard Claude Code tools (Bash, Grep, Read, Edit, etc.) are available by default. No work needed.

## Authentication pain point

YouCoded's auth requires the user's remote password — there's no "auto-trust localhost" path (`trustTailscale` only matches Tailscale IPs, line 366). For a budget app running on the same machine, three options:

1. **Read existing token from `~/.claude/.remote-tokens.json`.** Picks the first valid token and uses it. Cleanest for v1; only fails if YouCoded has never had a remote client connect.
2. **Prompt user for password once** and stash a token in the budget app's config.
3. **Patch YouCoded** to auto-trust `127.0.0.1` connections when `remoteConfig.enabled = true`. One-line change in `remote-server.ts:handleConnection`. Probably the right long-term answer; out of scope for the budget app to ship.

Phase 1c WS2 should default to option 1 with option 2 as the fallback path. Defer option 3 to a separate YouCoded PR if it's worth doing at all.

## Untested behaviors (worth confirming during WS2 implementation)

- **Streaming `tool_use` blocks during a turn (not just at turn-complete).** The transcript-watcher emits a `tool-use` event with the parsed JSON when a `tool_use` block lands in the JSONL. Need to verify the budget UI gets the `retrieve()` call as it happens, not buffered until turn end. (Almost certainly true based on `assistant-thinking` heartbeats being relayed turn-internal, but worth a smoke test.)
- **`session:input` for very long messages.** Should be handled by `SessionManager.sendInput` echo-driven chunking (see `desktop/CLAUDE.md` PTY Writes section), but budget questions can run long in dogfood. Smoke-test a 4-KB user message.
- **Concurrent sessions.** Each conversation is one session; users could have multiple budget conversations open. YouCoded supports up to N sessions; budget UI should respect that and not silently spawn beyond.
- **Session output mid-thinking.** Verify `assistant-thinking` heartbeats arrive over the WS (the attention banner depends on them).

## Verdict

**Green-light for Phase 1c WS2.** The remote API surface covers create-session + send-input + stream-transcript-events, which is everything the agent-pattern retrieval flow needs. The two minor friction points (system prompt via `cwd` CLAUDE.md, auth via existing token reuse) are well-contained design choices, not blockers.
