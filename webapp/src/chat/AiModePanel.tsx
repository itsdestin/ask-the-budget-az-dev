// The AI Mode surface, composed once and mounted by both corpus pages.
//
// Tasks 9-11 ported the pieces (reducer, chips, thread, mascot, PDF viewer)
// and deliberately left them unmounted. This file is the assembly: the header
// pill that turns the mode on, the tier control, the thread, the source
// viewer, and the honesty footer — arranged the way the retired app's
// page.tsx arranged them, minus the parts that were page chrome there and are
// the mockup's job here.
//
// It lives in `chat/` rather than in one of the pages because Search and
// Fiscal Notes must not drift apart: the two pages differ ONLY in which corpus
// they open a conversation against.

import { useEffect, useRef, useState } from "react";

import type { AiStatus } from "../api.js";
import ChatThread from "./ChatThread.js";
import Footer from "./Footer.js";
import { HistoryRail } from "./HistoryRail.js";
import MessageInput from "./MessageInput.js";
import { detectRefusal } from "./RefusalBanner.js";
import SuggestionRow from "./SuggestionRow.js";
import ToolsMenu from "./ToolsMenu.js";
import SystemHealthBanner from "./SystemHealthBanner.js";
import { CitationBusProvider, useCitationSelected } from "./citation-context.js";
import type { AssistantTurn } from "./chat-types.js";
import { useMascotPose } from "./mascot/useMascotPose.js";
import PdfViewer from "../pdf/PdfViewer.js";
import type { Corpus, UseChatResult } from "./use-chat.js";

/** The unavailable screen's headline. Deliberately says WHAT is true, not what
 *  is missing — "requires an API key" was an implementation detail aimed at an
 *  audience (the analyst) who cannot act on it. The cause still reaches the
 *  person who can: `status.reason`, rendered below and addressed to them.
 *
 *  Not tier copy — the S16 sentences all come off the wire (AiStatus.tiers). */
export const AI_GATED_HEADLINE = "AI Mode is currently unavailable";

/** The action, under the headline. One sentence, one instruction. */
export const AI_GATED_ACTION = "Contact your administrator to turn it on.";

/** Shown while `GET /api/ai/status` is still in flight. Without it a hung probe
 *  would fall through to the unavailable screen, which states a cause nobody
 *  has checked yet — an unanswered question rendered as a settled failure. */
export const AI_PROBING_HEADLINE =
  "Checking whether AI answers are available on this server…";

/** Corpus options the panel offers in its tools menu. Owned by the page (only
 *  it can act on a change — a corpus switch discards the conversation), passed
 *  down so the menu can name what each corpus contains. */
export interface CorpusOption {
  value: Corpus;
  label: string;
  /** What the assistant can actually see when this corpus is picked. Surfaced
   *  in the tools menu because "AI Mode" alone does not tell an analyst which
   *  documents the answer will be built from — and that is the first thing a
   *  citation audit depends on. */
  scope: string;
}

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

interface PanelProps {
  chat: UseChatResult;
  status: AiStatus | null;
  /** Which corpus this panel is asking about. Read by the starter chips (see
   *  the gate on SuggestionRow) and by the corpus switch below. */
  corpus: Corpus;
  /** The corpus switch renders only when the OWNER supplies both of these —
   *  it cannot change the corpus by itself, because switching means discarding
   *  the conversation, and only the owner (Ai.tsx, via `key={corpus}`) can do
   *  that. A panel mounted without them is read-only on corpus, which is what
   *  every corpus-agnostic test harness wants. */
  corpusOptions?: CorpusOption[];
  onCorpusChange?: (corpus: Corpus) => void;
  /** The id of the selected stored chat, or null for a new chat. Owned by
   *  Ai.tsx; the rail reads it to highlight the active chat. */
  selectedChatId?: string | null;
  onSelectChat?: (id: string) => void;
  onNewChat?: () => void;
}

export function AiModePanel(props: PanelProps) {
  // The bus must wrap BOTH the chips (inside the thread) and the viewer that
  // listens for them; PanelBody sits inside it so its own subscription — the
  // one that opens the source column — is served by the same provider.
  return (
    <CitationBusProvider>
      <PanelBody {...props} />
    </CitationBusProvider>
  );
}

function PanelBody({
  chat,
  status,
  corpus,
  corpusOptions,
  onCorpusChange,
  selectedChatId,
  onSelectChat,
  onNewChat,
}: PanelProps) {
  const { state } = chat;
  const mascot = useMascotPose(state, false);

  // The source column is allocated on chip click and closes on its own close
  // button below (Task 5 — it used to stay open for the rest of the session,
  // which left the chat column permanently halved; the analyst can now get
  // that width back). A later chip click re-opens it regardless, via the
  // subscription just below. Opening on ANY click, even an unresolved one, is
  // deliberate: PdfViewer renders a specific "couldn't open this" state, which
  // beats a click that silently does nothing.
  const [viewerOpen, setViewerOpen] = useState(false);
  useCitationSelected(() => setViewerOpen(true));

  // The rail's collapsed state persists per device in localStorage. Guard
  // the read: a localStorage that throws (private mode, a locked-down
  // profile) must default to expanded rather than break the panel.
  const [railCollapsed, setRailCollapsed] = useState(() => {
    try {
      return localStorage.getItem("jlbc-history-rail-collapsed") === "true";
    } catch {
      return false;
    }
  });
  const toggleRail = () => {
    setRailCollapsed((prev) => {
      const next = !prev;
      try { localStorage.setItem("jlbc-history-rail-collapsed", String(next)); } catch { /* ignore */ }
      return next;
    });
  };

  // The rail auto-collapses when the source panel opens. D1 gives the chat
  // region ONE content measure (~768px); a rail plus that column plus a PDF
  // panel would crush the thread, which is the exact problem D1 exists to
  // prevent. The rail yields, the thread does not.
  // Auto-collapse must not become a trap: closing the source panel leaves
  // the rail collapsed (it does not spring back), and the toggle stays
  // reachable, so an analyst who re-expands it while a source is open is not
  // fought by the effect on the next citation click.
  useEffect(() => {
    if (viewerOpen) setRailCollapsed(true);
  }, [viewerOpen]);

  // Flag only the LATEST assistant turn, and only while it is still the LAST
  // turn in the thread. Older turns keep their own history; re-warning about
  // every uncited turn in a long thread would bury the one the analyst is
  // actually reading.
  //
  // The "still last" half is not a detail. ChatThread renders this banner at
  // the end of the turn list, and sending a follow-up appends a user turn and
  // nothing else until the first streamed event arrives — so a reverse scan
  // that ignored position left the PREVIOUS turn's refusal sitting directly
  // beneath the analyst's brand-new question (with the send-re-arms-scrolling
  // effect pinning the view right at it). Read in place, that reads as a
  // verdict on the question they just asked. A refusal has to be attributed
  // to the answer it belongs to or it is worse than no refusal at all.
  const lastTurn = state.turns[state.turns.length - 1];
  const latestAssistant =
    lastTurn?.kind === "assistant" ? (lastTurn as AssistantTurn) : undefined;
  const refusal = latestAssistant ? detectRefusal(latestAssistant) : null;

  // The chrome measures itself so the thread scroller can pad by its REAL
  // height. One measured var replaces the retired app's guessy constants —
  // suggestion row present or not, stop button present or not, the padding
  // is always exactly right. Deps []: both refs point at elements that exist
  // for the panel's whole life, and the ResizeObserver handles every later
  // size change — re-subscribing per render would only churn observers.
  const chatColRef = useRef<HTMLDivElement | null>(null);
  const chromeRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const chrome = chromeRef.current;
    const col = chatColRef.current;
    if (!chrome || !col) return;
    // Queried rather than ref'd: the scroller is ChatThread's own element, and
    // threading a ref out of it just to measure a scrollbar would make the
    // thread's internals part of this file's contract.
    const scroller = col.querySelector<HTMLElement>(".chat-thread-scroll");
    const publish = () => {
      col.style.setProperty("--ai-bottom-chrome", `${chrome.offsetHeight}px`);
      // The chrome is absolutely positioned across the chat column, so at
      // right:0 it paints over the bottom of the thread's OWN scrollbar — the
      // bar appears to run under the composer and stop, which is what a
      // half-drawn scrollbar looks like. Insetting it by the exact bar width
      // lets the full track stay visible. Classic (non-overlay) scrollbars
      // report a positive difference here; overlay scrollbars report 0, which
      // is also correct — there is nothing to clear.
      if (scroller) {
        const bar = scroller.offsetWidth - scroller.clientWidth;
        col.style.setProperty("--ai-scrollbar", `${Math.max(0, bar)}px`);
      }
    };
    publish();
    if (typeof ResizeObserver === "undefined") return;
    const obs = new ResizeObserver(publish);
    obs.observe(chrome);
    // Observed too, because the bar appears and disappears as the thread
    // crosses one screen of content — and its arrival shrinks the scroller's
    // content box, which is exactly what ResizeObserver reports.
    if (scroller) obs.observe(scroller);
    return () => obs.disconnect();
  }, []);

  return (
    <section className="ai-panel" data-testid="ai-panel" aria-label="AI Mode">
      {chat.health && !chat.health.ok && (
        <SystemHealthBanner reason={chat.health.reason} />
      )}

      <div className="ai-panel-layout">
        <HistoryRail
          activeId={selectedChatId ?? null}
          onSelect={onSelectChat ?? (() => {})}
          onNewChat={onNewChat ?? (() => {})}
          collapsed={railCollapsed}
          onToggle={toggleRail}
        />

      <div className={viewerOpen ? "ai-panel-main has-source" : "ai-panel-main"}>
        <div className="ai-panel-chat" ref={chatColRef}>
          <ChatThread state={state} mascot={mascot} refusal={refusal} />

          {/* The chrome is ONE measured block — the scroller pads by its full
              height — but only the panel inside it is opaque. The starter
              chips sit above that panel on the thread's own background, so
              they read as offered questions floating over the conversation
              rather than as furniture bolted to the composer (Destin,
              2026-08-02). Keeping them inside the measured element is what
              stops them overlapping the last message. */}
          <div className="ai-bottom-chrome" data-testid="ai-bottom-chrome" ref={chromeRef}>
            {/* Budget only. SuggestionRow's three starters are hardcoded
                budget questions ("the FY2025 Aviation Fund balance", "ADOT
                in FY2024") and the component is Task 10's, so they cannot be
                swapped per corpus from here. Sending them at the
                fiscal-note corpus would make a coordinator's very first
                click a guaranteed empty retrieval — and, with the refusal
                detector working correctly, land them straight in the
                banner. No starters beats three wrong ones; per-corpus
                starters are a follow-up inside SuggestionRow. */}
            {state.turns.length === 0 && corpus === "budget" && (
              <SuggestionRow onPick={chat.send} />
            )}

            <div className="ai-chrome-panel">
              {state.error && (
                // The message is the server's, rendered verbatim — the S19
                // over-limit refusal arrives here with the real dollar
                // figures in it.
                <div className="chat-notice is-danger chat-notice-banner" role="alert">
                  <span>{state.error}</span>{" "}
                  <button type="button" className="ai-dismiss" onClick={chat.clearError}>
                    dismiss
                  </button>
                </div>
              )}

              <div className="ai-composer">
                <MessageInput
                  onSubmit={chat.send}
                  // Disabling on send is the front line against a duplicate
                  // turn: the server answers a second concurrent POST with
                  // 409, and a 409 is a mistake to prevent, not an error to
                  // render.
                  disabled={chat.busy}
                  // The placeholder NAMES THE CORPUS, and that is load-bearing
                  // rather than flavour: the corpus toggle lives inside a menu
                  // that closes, so without this the only permanent statement
                  // of which documents an answer can come from would be gone.
                  placeholder={
                    chat.busy
                      ? "Working — press Stop to interrupt."
                      : corpus === "fiscal_notes"
                        ? "Ask about fiscal notes…"
                        : "Ask about the budget…"
                  }
                  tools={
                    <ToolsMenu
                      status={status}
                      tier={chat.tier}
                      onTierChange={chat.setTier}
                      corpus={corpus}
                      onCorpusChange={onCorpusChange}
                      fiscalNotesScope={
                        corpusOptions?.find((c) => c.value === "fiscal_notes")?.scope
                      }
                    />
                  }
                  // Present only while a turn is streaming — that is what puts
                  // the square stop icon in the bar beside Send, instead of the
                  // full-width button that used to sit under the composer and
                  // shove the whole thread up when it appeared.
                  onStop={chat.busy ? chat.stop : undefined}
                />
              </div>

              <Footer />
            </div>
          </div>
        </div>
        {viewerOpen && (
          <aside className="ai-panel-source" aria-label="Source document">
            {/* Reversal of the "stays for the rest of the session" decision
                (spec D6): the split halves the chat column, so the analyst
                must be able to get their reading width back. Any later chip
                click re-opens via the useCitationSelected subscription
                above — closing only hides the panel, it doesn't unsubscribe
                anything.
                Task 15: the close button used to be floated here, on top of
                whichever PdfViewer state happened to be showing. It now
                lives INSIDE PdfViewer — in SourceView's merged header for
                the loaded state, or a floating variant for the empty/
                unresolved states — so there is exactly one button per state
                instead of this one plus a second one buried in SourceView.
                The aside stays `position:relative` (app.css) for those
                floating variants' positioning context. */}
            <PdfViewer onClose={() => setViewerOpen(false)} />
          </aside>
        )}
      </div>
      </div>
    </section>
  );
}
