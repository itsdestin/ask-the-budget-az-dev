// Shared fixtures for the AI Mode page specs.
//
// The tier copy below is a COPY OF THE SERVER'S response, not a source of
// truth: `app/routes/conversations.py::TIER_COPY` owns those sentences (spec
// S16), and the whole point of the page tests is that the webapp reads them
// off the wire rather than retyping them. Keeping the strings here — in a test
// fixture that stands in for the API — is what lets a test assert "these exact
// sentences rendered" without any component hardcoding them.

import type { AiStatus } from "../api";

/** jsdom implements no scrolling at all, so ChatThread's auto-scroll (a real
 *  browser behavior this task does not own) throws the moment a turn renders.
 *  Stubbing the method is the standard workaround; it asserts nothing. */
export function stubScrollIntoView(): void {
  if (!Element.prototype.scrollIntoView) {
    Element.prototype.scrollIntoView = function scrollIntoView() {};
  }
}

export const AI_STATUS: AiStatus = {
  available: true,
  tiers: {
    standard: {
      label: "Standard",
      default: true,
      description:
        "for quick lookups — e.g. 'how much did we spend on X last year?' " +
        "or 'did we appropriate money for xyz in FY 2020?'",
      examples: [
        "how much did we spend on X last year?",
        "did we appropriate money for xyz in FY 2020?",
      ],
      available: true,
      reason: null,
    },
    deep_research: {
      label: "Deep Research",
      default: false,
      description:
        "for open-ended, historical, broad-scope research — e.g. " +
        "'a comprehensive accounting of appropriated vs actual expenditures " +
        "for all border-enforcement programs across the past 10 fiscal years'",
      examples: [
        "a comprehensive accounting of appropriated vs actual expenditures " +
          "for all border-enforcement programs across the past 10 fiscal years",
      ],
      available: true,
      reason: null,
    },
  },
  user_usage: { month_usd: 1.25, limit_usd: 25, warned: false },
};

/** A Response-alike whose body streams the given SSE strings. */
export function sseResponse(chunks: string[], status = 200) {
  const encoder = new TextEncoder();
  let i = 0;
  return {
    ok: status >= 200 && status < 300,
    status,
    body: {
      getReader: () => ({
        read: async () =>
          i < chunks.length
            ? { done: false, value: encoder.encode(chunks[i++]!) }
            : { done: true, value: undefined },
        cancel: async () => {},
      }),
    },
  };
}

const evt = (o: Record<string, unknown>) => `data: ${JSON.stringify(o)}\n\n`;

/** The happy-path turn: one text delta, a turn_complete, a _done. */
export const ANSWER_STREAM = [
  evt({
    type: "assistant_text_delta",
    uuid: "a1",
    text: "AHCCCS receives $12.3 M.",
    timestamp: 1,
  }),
  evt({ type: "turn_complete", uuid: "a1", stopReason: "end_turn", timestamp: 2 }),
  evt({ type: "_done", stopReason: "end_turn", finalAnswer: "AHCCCS receives $12.3 M." }),
];

/** Stub `fetch` for the conversation endpoints. `turn` is whatever the
 *  messages route should answer with (default: a normal answer stream). */
export function stubConversationFetch(turn?: unknown) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const mock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    if (url === "/api/conversations") {
      return {
        ok: true,
        status: 200,
        json: async () => ({
          conversation_id: "conv-1",
          health: { ok: true },
          tier_default: "standard",
        }),
      };
    }
    if (url === "/api/history") {
      return { ok: true, status: 200, json: async () => ({ conversations: [] }) };
    }
    if (url.startsWith("/api/history/search")) {
      return { ok: true, status: 200, json: async () => ({ results: [] }) };
    }
    if (url.endsWith("/stop")) {
      return { ok: true, status: 200, json: async () => ({ stopped: true }) };
    }
    return turn ?? sseResponse(ANSWER_STREAM);
  });
  vi.stubGlobal("fetch", mock);
  return { mock, calls };
}
