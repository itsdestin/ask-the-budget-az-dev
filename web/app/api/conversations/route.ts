// POST /api/conversations
//
// Starts a new budget conversation by calling
// YouCodedSessionProvider.startConversation(). Returns the
// conversationId the client uses for subsequent /api/conversations/:id/messages
// calls.
//
// Body (optional):
//   { name?: string, cwd?: string }
//
// Response:
//   200 { conversationId: string, health: { ok: boolean, reason?: string } }
//     health.ok=false means the retrieval sidecar /health probe failed
//     during session start. The client renders a SystemHealthBanner so
//     the user sees the problem BEFORE they try to ask a question (see
//     Decision Q1 — probe result returned inline, no event plumbing).
//   503 { error: "youcoded_not_running" } — when YouCoded isn't reachable
//   503 { error: "no_token" }              — when ~/.claude/.remote-tokens.json is missing
//   500 { error: string }                  — anything else

import { NextResponse } from "next/server";

import { getProvider } from "@/lib/server-provider";
import { YouCodedClientError } from "@/lib/youcoded-client";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

interface StartBody {
  name?: string;
  cwd?: string;
}

export async function POST(req: Request): Promise<NextResponse> {
  let body: StartBody = {};
  try {
    body = (await req.json()) as StartBody;
  } catch {
    // Empty body is fine — defaults apply.
  }

  try {
    const provider = getProvider();
    // startConversation now returns both the id AND a sidecar-health
    // probe result; pass both through so the client can render a
    // top-of-thread banner when health.ok=false.
    const { conversationId, health } = await provider.startConversation({
      ...(body.name !== undefined ? { name: body.name } : {}),
      ...(body.cwd !== undefined ? { cwd: body.cwd } : {}),
    });
    return NextResponse.json({ conversationId, health });
  } catch (err) {
    return errorResponse(err);
  }
}

function errorResponse(err: unknown): NextResponse {
  if (err instanceof YouCodedClientError) {
    if (err.code === "connection_failed") {
      return NextResponse.json(
        {
          error: "youcoded_not_running",
          message:
            "Couldn't reach YouCoded at ws://localhost:9900/ws. Open YouCoded and try again.",
        },
        { status: 503 },
      );
    }
    if (err.code === "no_token") {
      return NextResponse.json(
        {
          error: "no_token",
          message:
            "No persisted YouCoded token found. Pair a remote client in YouCoded → Settings → Remote Access, then retry.",
        },
        { status: 503 },
      );
    }
    if (err.code === "auth_failed") {
      return NextResponse.json(
        {
          error: "auth_failed",
          message:
            "YouCoded rejected the saved token. Re-pair via YouCoded → Settings → Remote Access.",
        },
        { status: 401 },
      );
    }
  }
  const message = err instanceof Error ? err.message : String(err);
  return NextResponse.json(
    { error: "internal_error", message },
    { status: 500 },
  );
}
