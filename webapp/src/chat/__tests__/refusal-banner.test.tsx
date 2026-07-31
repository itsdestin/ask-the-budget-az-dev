// RefusalBanner + its detector.
//
// The detector is the load-bearing half. Core Invariant 3 says a system that
// can't ground an answer "says so and shows the raw chunks", and the shipped
// system prompt tells the model the interface already does that. These tests
// pin the two things that make the claim safe: it fires when an answer carries
// no surviving citation, and it stays silent on every ordinary answer.

import { render, screen } from "@testing-library/react";

import RefusalBanner, { detectRefusal } from "../RefusalBanner";
import type { AssistantTurn } from "../chat-types";

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
