// Stored OpenAI-format messages → the UI's Turn[] timeline.
//
// The stored transcript is wire history: `user` messages, `assistant`
// messages carrying `tool_calls` whose `arguments` are a JSON STRING, and
// `tool` replies keyed by `tool_call_id`. The UI timeline is Turn[] of
// AssistantBlock[], built today only by the reducer's from-provider-event
// path. This converter is what makes a reopened chat render with every
// chip, tool card and source link it had live (H2: "renders fully live").

import type { AssistantBlock, AssistantTurn, Turn, UserTurn } from "./chat-types.js";

// A stored message, loosely typed — the wire shape is what it is.
interface StoredMessage {
  role: string;
  content?: string | null;
  tool_calls?: Array<{
    id: string;
    type?: string;
    function: {
      name: string;
      arguments: string;
    };
  }> | null;
  tool_call_id?: string;
  name?: string;
}

/**
 * Convert stored OpenAI-format messages into the UI's Turn[] timeline.
 *
 * Run boundaries are the `user` messages: consecutive assistant/tool
 * messages merge into one AssistantTurn until the next user message.
 *
 * Timestamps are FABRICATED: HarnessSession.history records no per-message
 * time, only the transcript's created_at/updated_at. All turns get the same
 * created_at — nobody should read a rehydrated turn's clock as evidence of
 * when it happened.
 */
export function rehydrateTurns(
  messages: unknown[],
  createdAt: string = "",
): Turn[] {
  const turns: Turn[] = [];
  // Fabricated timestamp — see the comment above. Date.parse returns NaN for
  // an empty string, which falls back to 0 (epoch). Either is fine: the
  // timestamp is required by the Turn type but never read as real.
  const ts = Date.parse(createdAt) || 0;

  const msgs = messages as StoredMessage[];
  let i = 0;
  while (i < msgs.length) {
    const msg = msgs[i];
    if (!msg || typeof msg !== "object") {
      i++;
      continue;
    }

    if (msg.role === "user") {
      turns.push({
        kind: "user",
        id: `rehydrated-user-${i}`,
        text: typeof msg.content === "string" ? msg.content : "",
        pending: false,
        timestamp: ts,
      } satisfies UserTurn);
      i++;
      continue;
    }

    if (msg.role === "assistant" || msg.role === "tool") {
      // Collect consecutive assistant + tool messages into one AssistantTurn.
      const blocks: AssistantBlock[] = [];
      const blockIndexById = new Map<string, number>();

      while (i < msgs.length) {
        const m = msgs[i];
        if (!m || typeof m !== "object") { i++; break; }
        if (m.role === "user") break;

        if (m.role === "assistant") {
          // Text content (when non-empty) becomes a text block.
          if (typeof m.content === "string" && m.content) {
            blocks.push({
              kind: "text",
              uuid: `rehydrated-text-${i}`,
              text: m.content,
            });
          }
          // tool_calls become tool blocks in arrival order.
          if (m.tool_calls) {
            for (const call of m.tool_calls) {
              let input: Record<string, unknown> = {};
              try {
                input = JSON.parse(call.function.arguments || "{}");
              } catch {
                // A truncated tool call is a real shape — `arguments` can
                // be a partial JSON string. One bad chat must not fail to
                // open, so `input: {}` and no throw.
                input = {};
              }
              const block: AssistantBlock = {
                kind: "tool",
                toolUseId: call.id,
                toolName: call.function.name,
                input,
                status: "running",
              };
              blockIndexById.set(call.id, blocks.length);
              blocks.push(block);
            }
          }
          i++;
        } else if (m.role === "tool") {
          // Fill in the output on the matching tool block.
          const blockIdx = m.tool_call_id
            ? blockIndexById.get(m.tool_call_id)
            : undefined;
          if (blockIdx !== undefined) {
            const existing = blocks[blockIdx];
            if (existing && existing.kind === "tool") {
              blocks[blockIdx] = {
                ...existing,
                status: "complete",
                output: typeof m.content === "string" ? m.content : "",
              };
            }
          } else {
            // A tool reply with no matching call — a torn file or an older
            // transcript. Render it as a completed block so the content is
            // not lost.
            blocks.push({
              kind: "tool",
              toolUseId: m.tool_call_id || `rehydrated-tool-${i}`,
              toolName: m.name || "(unknown)",
              input: {},
              status: "complete",
              output: typeof m.content === "string" ? m.content : "",
            });
          }
          i++;
        } else {
          // Unknown role — skip rather than render.
          i++;
        }
      }

      // Any tool block still "running" has no matching reply — a torn file
      // or an older transcript. Mark it failed so the UI does not show a
      // permanent spinner.
      for (let b = 0; b < blocks.length; b++) {
        const block = blocks[b];
        if (block && block.kind === "tool" && block.status === "running") {
          blocks[b] = { ...block, status: "failed" };
        }
      }

      if (blocks.length > 0) {
        const first = blocks[0];
        const turnId = first.kind === "text" ? first.uuid : first.toolUseId;
        const turn: AssistantTurn = {
          kind: "assistant",
          id: turnId,
          blocks,
          isComplete: true,
          timestamp: ts,
        };
        turns.push(turn);
      }
      continue;
    }

    // Unknown role — skip.
    i++;
  }

  return turns;
}
