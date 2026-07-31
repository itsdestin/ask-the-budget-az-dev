// use-chat.ts — the SSE client behind AI Mode.
//
// WHY these tests exist: the wire format is the one part of the chat surface
// nothing else can catch. `POST /api/conversations/{id}/messages` answers with
// a stream, not a JSON body, so TypeScript checks nothing about it, and the
// three ways a stream can end (`_done`, `_error`, or the socket simply
// stopping) each need a different UI outcome. Everything below drives the real
// hook against a hand-built ReadableStream so the frame parser is exercised at
// the byte level — including a frame deliberately split across two chunks,
// which is what a real network does and a naive `split("\n\n")` gets wrong.

import { act, renderHook, waitFor } from "@testing-library/react";

import { useChat } from "../use-chat";

// ---------------------------------------------------------------------------
// Fetch plumbing
// ---------------------------------------------------------------------------

const CONVERSATION = {
  conversation_id: "conv-1",
  health: { ok: true },
  tier_default: "standard",
};

/** A Response-alike whose body streams the given strings, one per read().
 *  Strings are byte-encoded so the hook's TextDecoder does the real work. */
function sseResponse(chunks: string[], status = 200) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    body: {
      getReader() {
        return {
          read: async () =>
            i < chunks.length
              ? { done: false, value: encoder.encode(chunks[i++]) }
              : { done: true, value: undefined },
          cancel: async () => {},
        };
      },
    },
  };
}

function jsonResponse(body: unknown, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  };
}

/** Route the two endpoints the hook talks to. `messages` is whatever the test
 *  wants the turn to answer with. */
function stubFetch(
  messages: unknown,
  opts: { onStop?: () => void; createFails?: boolean } = {},
) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/conversations") {
      if (opts.createFails) return jsonResponse({ detail: "nope" }, 500);
      return jsonResponse(CONVERSATION);
    }
    if (url.endsWith("/stop")) {
      opts.onStop?.();
      return jsonResponse({ stopped: true });
    }
    return typeof messages === "function"
      ? (messages as () => unknown)()
      : messages;
  });
  vi.stubGlobal("fetch", mock);
  return { mock, calls };
}

const evt = (o: Record<string, unknown>) => `data: ${JSON.stringify(o)}\n\n`;

const TEXT = evt({
  type: "assistant_text_delta",
  uuid: "a1",
  text: "Appropriations rose.",
  timestamp: 1,
});
const COMPLETE = evt({
  type: "turn_complete",
  uuid: "a1",
  stopReason: "end_turn",
  timestamp: 2,
});
const DONE = evt({ type: "_done", stopReason: "end_turn", finalAnswer: "x" });

afterEach(() => vi.unstubAllGlobals());

// ---------------------------------------------------------------------------

describe("useChat", () => {
  it("creates no conversation until the first send", async () => {
    const { mock } = stubFetch(sseResponse([TEXT, COMPLETE, DONE]));
    renderHook(() => useChat("budget"));
    // A mounted-but-unused AI panel must not open a conversation: creation is
    // what allocates a server-side session slot.
    await new Promise((r) => setTimeout(r, 0));
    expect(mock).not.toHaveBeenCalled();
  });

  it("creates the conversation on first send and reuses it after", async () => {
    const { calls } = stubFetch(() => sseResponse([TEXT, COMPLETE, DONE]));
    const { result } = renderHook(() => useChat("budget"));

    await act(async () => result.current.send("first"));
    await act(async () => result.current.send("second"));

    const creates = calls.filter((c) => c.url === "/api/conversations");
    expect(creates).toHaveLength(1);
    expect(JSON.parse(creates[0]!.init!.body as string)).toEqual({
      corpus: "budget",
    });
    expect(
      calls.filter((c) => c.url === "/api/conversations/conv-1/messages"),
    ).toHaveLength(2);
  });

  it("sends the selected tier with each message and starts on standard", async () => {
    const { calls } = stubFetch(() => sseResponse([TEXT, COMPLETE, DONE]));
    const { result } = renderHook(() => useChat("budget"));

    expect(result.current.tier).toBe("standard");
    await act(async () => result.current.send("q1"));
    act(() => result.current.setTier("deep_research"));
    await act(async () => result.current.send("q2"));

    const bodies = calls
      .filter((c) => c.url.endsWith("/messages"))
      .map((c) => JSON.parse(c.init!.body as string));
    expect(bodies).toEqual([
      { text: "q1", tier: "standard" },
      { text: "q2", tier: "deep_research" },
    ]);
  });

  it("reassembles a frame split across chunk boundaries", async () => {
    // The JSON is cut mid-token; only a buffering parser survives this.
    const half = TEXT.slice(0, 30);
    const rest = TEXT.slice(30);
    stubFetch(sseResponse([half, rest + COMPLETE, DONE]));
    const { result } = renderHook(() => useChat("budget"));

    await act(async () => result.current.send("q"));

    await waitFor(() => {
      const turn = result.current.state.turns.find(
        (t) => t.kind === "assistant",
      );
      expect(turn).toBeDefined();
    });
    const turn = result.current.state.turns.find((t) => t.kind === "assistant")!;
    expect(JSON.stringify(turn)).toContain("Appropriations rose.");
    expect(result.current.state.isThinking).toBe(false);
  });

  it("ignores non-data SSE lines and blank keepalive frames", async () => {
    stubFetch(
      sseResponse([": keepalive\n\n", `event: ping\n${TEXT}`, COMPLETE, DONE]),
    );
    const { result } = renderHook(() => useChat("budget"));
    await act(async () => result.current.send("q"));
    expect(result.current.state.error).toBeNull();
    expect(JSON.stringify(result.current.state.turns)).toContain(
      "Appropriations rose.",
    );
  });

  it("renders an _error frame's message verbatim (the S19 refusal path)", async () => {
    // The over-limit refusal rides a 200 as a terminal _error frame carrying
    // the ledger's own sentence. The UI must not re-derive that wording.
    const message =
      "You've reached your monthly AI usage limit ($25.00) — ask jlbcadmin to raise it.";
    stubFetch(sseResponse([evt({ type: "_error", message })]));
    const { result } = renderHook(() => useChat("budget"));

    await act(async () => result.current.send("q"));

    expect(result.current.state.error).toBe(message);
    expect(result.current.state.isThinking).toBe(false);
  });

  it("treats _error as terminal — no 'stream ended' error on top of it", async () => {
    const message = "provider rejected the request";
    stubFetch(sseResponse([TEXT, evt({ type: "_error", message })]));
    const { result } = renderHook(() => useChat("budget"));
    await act(async () => result.current.send("q"));
    expect(result.current.state.error).toBe(message);
  });

  it("reports a stream that ends with no terminator at all", async () => {
    // Silence is the worst outcome: without this the composer would stay
    // disabled behind isThinking forever.
    stubFetch(sseResponse([TEXT]));
    const { result } = renderHook(() => useChat("budget"));

    await act(async () => result.current.send("q"));

    expect(result.current.state.isThinking).toBe(false);
    expect(result.current.state.error).toMatch(/ended/i);
  });

  it("does not surface a 409 as an error — it is a double-submit, not a failure", async () => {
    stubFetch(jsonResponse({ detail: "a turn is already streaming" }, 409));
    const { result } = renderHook(() => useChat("budget"));

    await act(async () => result.current.send("q"));

    expect(result.current.state.error).toBeNull();
    expect(result.current.state.isThinking).toBe(false);
  });

  it("refuses a second send while a turn is streaming", async () => {
    // The composer disables on send; this is the belt to that brace, and the
    // reason a 409 should never be reachable from one tab.
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    const encoder = new TextEncoder();
    let served = false;
    stubFetch(() => ({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            if (served) return { done: true, value: undefined };
            await gate;
            served = true;
            return { done: false, value: encoder.encode(TEXT + COMPLETE + DONE) };
          },
          cancel: async () => {},
        }),
      },
    }));
    const { result } = renderHook(() => useChat("budget"));

    let first!: Promise<void>;
    await act(async () => {
      first = result.current.send("q1") as unknown as Promise<void>;
      await Promise.resolve();
    });
    await act(async () => result.current.send("q2"));
    release();
    await act(async () => {
      await first;
    });

    const userTurns = result.current.state.turns.filter(
      (t) => t.kind === "user",
    );
    expect(userTurns).toHaveLength(1);
  });

  it("stop() posts /stop and ends the turn as a user interrupt", async () => {
    let stopped = false;
    const encoder = new TextEncoder();
    let release!: () => void;
    const gate = new Promise<void>((r) => (release = r));
    stubFetch(
      () => ({
        ok: true,
        status: 200,
        body: {
          getReader: () => ({
            read: async () => {
              await gate;
              return { done: true, value: undefined };
            },
            cancel: async () => {},
          }),
        },
      }),
      { onStop: () => (stopped = true) },
    );
    void encoder;
    const { result } = renderHook(() => useChat("budget"));

    let turn!: Promise<void>;
    await act(async () => {
      turn = result.current.send("q") as unknown as Promise<void>;
      await Promise.resolve();
    });
    await act(async () => {
      result.current.stop();
      await Promise.resolve();
    });
    release();
    await act(async () => {
      await turn;
    });

    await waitFor(() => expect(stopped).toBe(true));
    // A stopped turn is not an error — it is a thing the analyst chose.
    expect(result.current.state.error).toBeNull();
    expect(result.current.state.isThinking).toBe(false);
  });

  it("surfaces a failed conversation create without losing the question", async () => {
    stubFetch(sseResponse([]), { createFails: true });
    const { result } = renderHook(() => useChat("budget"));

    await act(async () => result.current.send("where did the money go"));

    expect(result.current.state.error).toBeTruthy();
    // The typed question is still on screen — MessageInput cleared its box, so
    // dropping it here would lose it outright.
    expect(
      result.current.state.turns.some(
        (t) => t.kind === "user" && t.text === "where did the money go",
      ),
    ).toBe(true);
  });

  it("exposes the create response's health block", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (url: string) =>
        url === "/api/conversations"
          ? jsonResponse({
              conversation_id: "c9",
              health: { ok: false, reason: "no API key configured" },
              tier_default: "standard",
            })
          : sseResponse([TEXT, COMPLETE, DONE]),
      ),
    );
    const { result } = renderHook(() => useChat("fiscal_notes"));
    await act(async () => result.current.send("q"));
    expect(result.current.health).toEqual({
      ok: false,
      reason: "no API key configured",
    });
  });
});
