// AiModePanel's source column: open-on-chip-click, close-on-button,
// reopen-on-next-chip-click.
//
// Until this task the source column had no way to close once opened — a
// deliberate decision (spec D6) that the analyst's chat column stays halved
// for the rest of the session. That is being reversed: this file pins the
// reversal (close button hides the panel) and the part of the old decision
// that survives (a later chip click still re-opens it, via the same
// `useCitationSelected` subscription AiModePanel already had).
//
// Fixtures are lifted verbatim from refusal-banner.test.tsx (same
// retrieveBlock/citeBlock/textBlock/turn/userTurn/chatState/fakeChat shapes)
// so a real cite() tool call renders a REAL CitationChip inside the panel's
// own CitationBusProvider — clicking it exercises the true chip -> bus ->
// panel-opens path with no test-only exports off AiModePanel.

import { fireEvent, render, screen } from "@testing-library/react";

import { AiModePanel } from "../AiModePanel";
import type { AssistantTurn, ChatState, UserTurn } from "../chat-types";
import { initialChatState } from "../chat-types";
import type { UseChatResult } from "../use-chat";
import { stubScrollIntoView } from "../../pages/ai-test-fixtures";

// Mocked so pdfjs (React.lazy inside PdfViewer -> SourceView) never loads in
// this DOM-only suite; the marker div is enough to prove the panel opened.
// Task 15 moved the close button OUT of AiModePanel and INTO PdfViewer
// (SourceView's merged header for the real component), so this stand-in
// must render one too and forward `onClose` — otherwise this suite tests a
// button that no longer exists anywhere in the real render tree.
vi.mock("../../pdf/PdfViewer", () => ({
  default: ({ onClose }: { onClose?: () => void }) => (
    <div data-testid="pdf-viewer">
      {onClose && (
        <button type="button" onClick={onClose}>
          Close source panel
        </button>
      )}
    </div>
  ),
}));

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

/** Minimal stand-in for useChat()'s return value — same shape
 *  refusal-banner.test.tsx uses; AiModePanel only reads `state` for this
 *  test's question and the rest are inert no-ops. */
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

describe("AiModePanel source panel close button", () => {
  beforeEach(() => stubScrollIntoView());

  it("close button hides the source panel; a new chip click reopens it", () => {
    const cited = turn({
      id: "a1",
      blocks: [retrieveBlock(), textBlock("AHCCCS gets $12.3 M."), citeBlock(true)],
    });

    render(
      <AiModePanel
        chat={fakeChat(
          chatState([userTurn("u1", "How much did AHCCCS get?"), cited]),
        )}
        status={null}
        corpus="budget"
      />,
    );

    // No chip has fired yet — the source column isn't allocated at all.
    expect(screen.queryByTestId("pdf-viewer")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /Citation 1/ }));
    expect(screen.getByTestId("pdf-viewer")).toBeInTheDocument();

    fireEvent.click(
      screen.getByRole("button", { name: "Close source panel" }),
    );
    expect(screen.queryByTestId("pdf-viewer")).not.toBeInTheDocument();

    // The chip itself is untouched by closing the panel — clicking it again
    // re-opens via the same useCitationSelected subscription.
    fireEvent.click(screen.getByRole("button", { name: /Citation 1/ }));
    expect(screen.getByTestId("pdf-viewer")).toBeInTheDocument();
  });
});
