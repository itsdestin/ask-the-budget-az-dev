// RefusalBanner + its detector.
//
// The detector is the load-bearing half. Core Invariant 3 says a system that
// can't ground an answer "says so and shows the raw chunks", and the shipped
// system prompt tells the model the interface already does that. These tests
// pin the two things that make the claim safe: it fires when an answer carries
// no surviving citation, and it stays silent on every ordinary answer.

import { render, screen } from "@testing-library/react";

import { AiModePanel } from "../AiModePanel";
import RefusalBanner, { detectRefusal } from "../RefusalBanner";
import type { AssistantTurn, ChatState, UserTurn } from "../chat-types";
import { initialChatState } from "../chat-types";
import type { UseChatResult } from "../use-chat";
import { stubScrollIntoView } from "../../pages/ai-test-fixtures";

const CHUNK = {
  chunk_id: "ch-1",
  doc_id: "d1",
  doc_title: "AHCCCS — FY 2027 Baseline",
  publisher: "jlbc",
  fiscal_year: 2027,
  doc_type: "baseline-per-agency",
  page_start: 14,
  page_end: 14,
  bbox: null,
  text: "The Executive Budget includes $12,300,000 for provider rate increases.",
};

function retrieveBlock(chunks: unknown[] = [CHUNK]) {
  return {
    kind: "tool" as const,
    toolUseId: "t1",
    toolName: "retrieve",
    input: { query: "ahcccs rates" },
    status: "complete" as const,
    output: JSON.stringify({ chunks, top_score: 4.2, retrieval_id: "r1" }),
  };
}

function citeBlock(ok: boolean) {
  return {
    kind: "tool" as const,
    toolUseId: "t2",
    toolName: "cite",
    input: {
      chunk_id: "ch-1",
      claim_span: "$12.3 M for rate increases",
      quote: "$12,300,000",
      confidence: "verbatim",
    },
    status: "complete" as const,
    output: ok
      ? JSON.stringify({
          ok: true,
          citation_id: "cit-1",
          resolved_span_start: 32,
          resolved_span_end: 43,
        })
      : JSON.stringify({ ok: false, error: "quote not found in chunk" }),
  };
}

const textBlock = (text: string) => ({
  kind: "text" as const,
  uuid: "u1",
  text,
});

function turn(over: Partial<AssistantTurn> = {}): AssistantTurn {
  return {
    kind: "assistant",
    id: "u1",
    blocks: [],
    isComplete: true,
    stopReason: "end_turn",
    timestamp: 1,
    ...over,
  };
}

describe("detectRefusal", () => {
  it("stays silent on an ordinary cited answer", () => {
    expect(
      detectRefusal(
        turn({
          blocks: [
            retrieveBlock(),
            textBlock("AHCCCS gets $12.3 M."),
            citeBlock(true),
          ],
        }),
      ),
    ).toBeNull();
  });

  it("stays silent while the turn is still streaming", () => {
    // Cites land AFTER the prose. Judging an open turn would flash the banner
    // on every answer for as long as the model takes to call cite().
    expect(
      detectRefusal(
        turn({
          isComplete: false,
          stopReason: undefined,
          blocks: [retrieveBlock(), textBlock("AHCCCS gets $12.3 M.")],
        }),
      ),
    ).toBeNull();
  });

  it("stays silent when the turn was cut short rather than refused", () => {
    // max_steps / user_interrupt already have their own notices, and an
    // interrupted answer isn't a refusal — it's an unfinished one.
    for (const stopReason of ["max_steps", "user_interrupt", "max_tokens"]) {
      expect(
        detectRefusal(
          turn({
            stopReason,
            blocks: [retrieveBlock(), textBlock("Partial…")],
          }),
        ),
      ).toBeNull();
    }
  });

  it("stays silent on a turn that never searched", () => {
    // A clarifying question ("which fiscal year?") retrieves nothing and cites
    // nothing. That is not a refusal and there are no chunks to show.
    expect(
      detectRefusal(turn({ blocks: [textBlock("Which fiscal year?")] })),
    ).toBeNull();
  });

  it("reports a synthesis refusal when passages came back but nothing was cited", () => {
    const r = detectRefusal(
      turn({
        blocks: [
          retrieveBlock(),
          textBlock("I can show you the underlying numbers but combining them…"),
        ],
      }),
    );
    expect(r?.kind).toBe("synthesis");
    expect(r?.kind === "synthesis" && r.chunks[0]?.docTitle).toBe(
      "AHCCCS — FY 2027 Baseline",
    );
  });

  it("treats a failed cite as no VERIFIED citation", () => {
    // Invariant 2: a rejected citation must leave the claim unsupported, not
    // quietly accepted. Note this turn DOES show chips — red-X ones — which is
    // why the banner's wording is pinned separately below.
    const r = detectRefusal(
      turn({
        blocks: [retrieveBlock(), textBlock("AHCCCS gets $12.3 M."), citeBlock(false)],
      }),
    );
    expect(r?.kind).toBe("synthesis");
  });

  it("still fires when the model used inline <cite> tags instead of the tool", () => {
    // AssistantTurnBubble renders those tags as ordinary-looking chips, but
    // nothing validated them — no chunk-exists check, no quote-in-chunk check.
    // That is strictly LESS verified than a failed cite(), so hiding the
    // passages here would invert the invariant this banner serves.
    const r = detectRefusal(
      turn({
        blocks: [
          retrieveBlock(),
          textBlock(
            'AHCCCS gets <cite chunk_id="ch-1" claim_span="$12.3 M">$12.3 M</cite>.',
          ),
        ],
      }),
    );
    expect(r?.kind).toBe("synthesis");
  });

  it("reports a no-retrieval refusal when the search came back empty", () => {
    const r = detectRefusal(
      turn({
        blocks: [
          retrieveBlock([]),
          textBlock("I cannot find this in the indexed documents."),
        ],
      }),
    );
    expect(r?.kind).toBe("no_retrieval");
  });
});

describe("RefusalBanner", () => {
  it("shows the retrieved passages so the analyst can read them directly", () => {
    render(
      <RefusalBanner
        refusal={{
          kind: "synthesis",
          chunks: [
            {
              chunkId: "ch-1",
              docTitle: "AHCCCS — FY 2027 Baseline",
              publisher: "jlbc",
              fiscalYear: 2027,
              pageStart: 14,
              pageEnd: 14,
              text: "The Executive Budget includes $12,300,000 for provider rate increases.",
            },
          ],
        }}
      />,
    );
    expect(screen.getByText(/\$12,300,000/)).toBeInTheDocument();
    expect(screen.getByText(/AHCCCS — FY 2027 Baseline/)).toBeInTheDocument();
    expect(screen.getByText(/p\. 14/)).toBeInTheDocument();
  });

  it("never denies citations the analyst can see on screen", () => {
    // The banner fires in two states where chips ARE rendered: every cite()
    // returned ok:false (red-X chips), and the model emitted inline <cite>
    // tags (ordinary-looking chips). "Carries no citation" would be flatly
    // contradicted by the screen in both. Only "verified" is true everywhere.
    for (const refusal of [
      { kind: "synthesis" as const, chunks: [] },
      { kind: "no_retrieval" as const },
    ]) {
      const { container, unmount } = render(<RefusalBanner refusal={refusal} />);
      expect(container.textContent).toContain("no verified citation");
      expect(container.textContent).not.toMatch(/carries no citation\b/);
      expect(container.textContent).not.toMatch(/nothing above is linked/);
      unmount();
    }
  });

  it("never speaks in the model's voice", () => {
    // The detector cannot tell a deliberate refusal from a contract violation
    // (an answer written with no cite() call), so the banner states only what
    // is true in both cases and is rendered as a system notice.
    const { container } = render(
      <RefusalBanner refusal={{ kind: "no_retrieval" }} />,
    );
    expect(container.textContent).not.toMatch(/\bI\b/);
    expect(screen.getByRole("status")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------------------
// AiModePanel's "latest turn only" scoping
// ---------------------------------------------------------------------------
//
// The code review on Task 12 flagged AiModePanel.tsx's `latestAssistant` scan
// (it walks turns in reverse and calls detectRefusal on the single most
// recent assistant turn): once the conversation moves on, an earlier
// unverified turn's banner disappears for good, and scrolling back up shows
// plain unbannered prose that looks identical to an ordinary cited answer.
//
// DECISION (pinned here, not changed): keep that behavior. The banner's own
// header comment already argues re-warning about every uncited turn in a long
// thread would bury the one the analyst is currently reading. This test's
// job is narrower than approving that trade-off — it is to make sure nobody
// "fixes" it by accident. If a future change wants "warn once and remember",
// it has to touch this test on purpose.

const userTurn = (id: string, text: string): UserTurn => ({
  kind: "user",
  id,
  text,
  pending: false,
  timestamp: 1,
});

function chatState(turns: ChatState["turns"]): ChatState {
  return { ...initialChatState, turns };
}

/** Minimal stand-in for useChat()'s return value. AiModePanel only reads
 *  `state` off `chat` for the scoping question this test pins; the rest are
 *  inert no-ops so the panel (and its children — ChatThread, Footer,
 *  MessageInput, the PDF viewer) can mount without a network or a real SSE
 *  stream. */
function fakeChat(state: ChatState): UseChatResult {
  return {
    state,
    send: async () => {},
    stop: () => {},
    clearError: () => {},
    tier: "standard",
    setTier: () => {},
    busy: false,
    health: null,
  };
}

describe("AiModePanel refusal scoping (pinned trade-off)", () => {
  beforeEach(() => stubScrollIntoView());

  it("bans the earlier turn's banner once a new, properly-cited turn lands", () => {
    const turn1 = turn({
      id: "a1",
      blocks: [retrieveBlock(), textBlock("AHCCCS gets $12.3 M.")],
    });

    const { rerender } = render(
      <AiModePanel
        chat={fakeChat(
          chatState([userTurn("u1", "How much did AHCCCS get?"), turn1]),
        )}
        status={null}
        corpus="budget"
      />,
    );

    // Turn 1 alone: no cite() ran, so the banner must show — this is the
    // ordinary (non-regressed) detectRefusal behavior from the suite above,
    // now asserted through the panel that actually decides what's visible.
    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/no verified citation/)).toBeInTheDocument();

    const turn2 = turn({
      id: "a2",
      blocks: [
        retrieveBlock(),
        textBlock("ADOT gets $4.1 M."),
        citeBlock(true),
      ],
    });

    rerender(
      <AiModePanel
        chat={fakeChat(
          chatState([
            userTurn("u1", "How much did AHCCCS get?"),
            turn1,
            userTurn("u2", "And ADOT?"),
            turn2,
          ]),
        )}
        status={null}
        corpus="budget"
      />,
    );

    // THE PINNED BEHAVIOR: turn 1 is still sitting in the thread above,
    // still uncited, still exactly as unverified as it was a moment ago —
    // but the panel only ever asks detectRefusal about the LATEST assistant
    // turn, and turn 2 has a verified cite. The banner disappears entirely,
    // not just off turn 1. Scrolling back up now shows turn 1's prose with
    // no banner at all, indistinguishable on sight from an ordinary answer.
    // That is the accepted trade-off, not a bug — this assertion exists so a
    // future change to "warn once and remember" has to edit this test
    // instead of silently reversing the decision.
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});

// ── Figures linked by the SYSTEM count as verification ──────────────────────
//
// Regression, seen in a real browser 2026-08-02. Citation linking told the
// model to stop calling cite() for figures, because the system now links every
// figure itself. The detector only recognised a cite() ack, so a fully-linked
// numeric answer had ZERO citationIds and the banner fired on it — announcing
// "no verified citation" over an answer in which every number was linked, and
// burying the answer under five raw passages.
//
// A linked figure is not a weaker citation than a cite() ack; it is a stronger
// one. A cite() ack validates a quote the MODEL retyped. A linked figure is a
// value the SYSTEM located in a chunk the turn actually retrieved, with the
// source's own rendering and offsets. Treating it as unverified inverted the
// invariant this banner exists to serve.
describe("detectRefusal — system-linked figures", () => {
  const annotationWith = (...verdicts: string[]) => ({
    figures: verdicts.map((verdict, i) => ({
      text: "$12,300,000",
      start: 0,
      end: 11,
      index: i + 1,
      verdict,
      primary:
        verdict === "linked"
          ? { chunk_id: "ch-1", source_text: "12,300,000", start: 0, end: 10 }
          : null,
      additional: [],
      derived_from: verdict === "derived" ? [1] : [],
    })),
  });

  it("stays silent when the system linked the answer's figures", () => {
    expect(
      detectRefusal(
        turn({
          blocks: [retrieveBlock(), textBlock("AHCCCS gets $12,300,000.")],
          annotation: annotationWith("linked"),
        }),
      ),
    ).toBeNull();
  });

  it("stays silent when a figure is linked and another is derived", () => {
    expect(
      detectRefusal(
        turn({
          blocks: [retrieveBlock(), textBlock("$12,300,000 plus more.")],
          annotation: annotationWith("linked", "derived"),
        }),
      ),
    ).toBeNull();
  });

  it("still fires when every figure came back unverified", () => {
    // Nothing was located, so nothing is verified — the banner is telling the
    // truth here and must keep firing.
    expect(
      detectRefusal(
        turn({
          blocks: [retrieveBlock(), textBlock("AHCCCS gets $99,999,999.")],
          annotation: annotationWith("unverified", "unverified"),
        }),
      ),
    ).not.toBeNull();
  });

  it("still fires on a prose answer that states no figures at all", () => {
    // An empty annotation must not be read as "verified". A refusal, or an
    // uncited prose claim, still needs its passages shown.
    expect(
      detectRefusal(
        turn({
          blocks: [retrieveBlock(), textBlock("The corpus does not cover that.")],
          annotation: { figures: [] },
        }),
      ),
    ).not.toBeNull();
  });

  it("is unaffected by a turn recorded before linking shipped", () => {
    expect(
      detectRefusal(
        turn({ blocks: [retrieveBlock(), textBlock("An uncited claim.")] }),
      ),
    ).not.toBeNull();
  });
});
