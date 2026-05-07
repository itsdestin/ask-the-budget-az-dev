// POST /api/conversations/:id/messages
//
// Sends one user message into a conversation and streams the resulting
// turn back as Server-Sent Events. Each event payload is a
// ProviderEvent (lib/types.ts) serialized as JSON; the client parses
// and feeds them into the chat reducer.
//
// SSE wire format:
//   data: {"type":"assistant_text_delta",...}\n\n
//   data: {"type":"tool_use",...}\n\n
//   data: {"type":"turn_complete",...}\n\n
//
// We also send a final synthetic event:
//   data: {"type":"_done","stopReason":"end_turn",...}\n\n
//
// — to give the client a clean signal that the response body has
// finished. Client closes the reader on receipt.
//
// Body:
//   { text: string }

import { getProvider } from "@/lib/server-provider";
import type { ProviderEvent } from "@/lib/types";
import { YouCodedClientError } from "@/lib/youcoded-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface MessageBody {
  text: string;
}

export async function POST(
  req: Request,
  ctx: { params: Promise<{ id: string }> },
): Promise<Response> {
  const { id: conversationId } = await ctx.params;
  let body: MessageBody;
  try {
    body = (await req.json()) as MessageBody;
  } catch {
    return jsonError(400, "bad_request", "request body is not JSON");
  }
  if (typeof body?.text !== "string" || body.text.length === 0) {
    return jsonError(400, "bad_request", "missing/empty `text`");
  }

  const encoder = new TextEncoder();
  const stream = new ReadableStream<Uint8Array>({
    async start(controller) {
      const send = (obj: unknown) => {
        controller.enqueue(
          encoder.encode(`data: ${JSON.stringify(obj)}\n\n`),
        );
      };

      try {
        const provider = getProvider();
        const result = await provider.sendTurn({
          conversationId,
          userMessage: body.text,
          onEvent: (e: ProviderEvent) => send(e),
        });
        // Synthetic turn-end so the client can stop reading deterministically.
        send({
          type: "_done",
          stopReason: result.stopReason,
          finalAnswer: result.finalAnswer,
          citations: result.citations,
          retrievedChunkIds: result.retrievedChunkIds,
        });
      } catch (err) {
        const payload = errorEventPayload(err);
        send(payload);
      } finally {
        controller.close();
      }
    },
  });

  return new Response(stream, {
    headers: {
      "Content-Type": "text/event-stream; charset=utf-8",
      "Cache-Control": "no-cache, no-transform",
      "X-Accel-Buffering": "no",
      Connection: "keep-alive",
    },
  });
}

function errorEventPayload(err: unknown): Record<string, unknown> {
  if (err instanceof YouCodedClientError) {
    return {
      type: "_error",
      code: err.code,
      message: err.message,
    };
  }
  return {
    type: "_error",
    code: "internal_error",
    message: err instanceof Error ? err.message : String(err),
  };
}

function jsonError(status: number, code: string, message: string): Response {
  return new Response(JSON.stringify({ error: code, message }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
