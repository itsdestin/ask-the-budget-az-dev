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

import { useState } from "react";

import type { AiStatus } from "../api.js";
import ChatThread from "./ChatThread.js";
import Footer from "./Footer.js";
import MessageInput from "./MessageInput.js";
import RefusalBanner, { detectRefusal } from "./RefusalBanner.js";
import SuggestionRow from "./SuggestionRow.js";
import SystemHealthBanner from "./SystemHealthBanner.js";
import { CitationBusProvider, useCitationSelected } from "./citation-context.js";
import type { AssistantTurn } from "./chat-types.js";
import { useMascotPose } from "./mascot/useMascotPose.js";
import PdfViewer from "../pdf/PdfViewer.js";
import type { Corpus, Tier, UseChatResult } from "./use-chat.js";

/** The one string this task hardcodes. It is the gate's explanation, not tier
 *  copy — the S16 sentences all come off the wire (see AiStatus.tiers). */
export const AI_GATED_TOOLTIP =
  "AI answers require an API key — ask your admin.";

/** Shown while `GET /api/ai/status` is still in flight. Without it a hung
 *  probe leaves a permanently inert pill with no explanation at all, which
 *  reads as a broken control rather than an unanswered question. */
export const AI_PROBING_TOOLTIP =
  "Checking whether AI answers are available on this server…";

const TIER_ORDER: Tier[] = ["standard", "deep_research"];

// ---------------------------------------------------------------------------
// The header pill
// ---------------------------------------------------------------------------

interface ToggleProps {
  on: boolean;
  onChange: (on: boolean) => void;
  status: AiStatus | null;
}

/** The mode switch. Mockup pill idiom (the subhero's `.chip` recipe with an
 *  "on" fill), `aria-pressed` because it is a two-state control, not a link. */
export function AiModeToggle({ on, onChange, status }: ToggleProps) {
  const gated = !status?.available;
  // Two different explanations, because they are two different facts. During
  // the probe the pill is already inert (opening a mode we cannot confirm
  // would be worse), but saying "requires an API key" before anyone has
  // checked would state a cause nobody knows yet — so the in-flight state says
  // so instead of staying silent.
  const gateTooltip =
    status === null
      ? AI_PROBING_TOOLTIP
      : status.available
        ? undefined
        : AI_GATED_TOOLTIP;
  return (
    <button
      type="button"
      className={`ai-toggle${on ? " on" : ""}${gated ? " is-gated" : ""}`}
      // aria-disabled rather than `disabled`: a genuinely disabled button is
      // skipped by keyboard navigation and, in most browsers, never shows its
      // `title` on hover — which would hide the one sentence that explains why
      // the control is dead. It stays focusable and hoverable; the click is
      // what's inert.
      aria-disabled={gated || undefined}
      aria-pressed={on}
      title={gateTooltip}
      onClick={() => {
        if (gated) return;
        onChange(!on);
      }}
    >
      {/* The mockup's Arizona star — it reads as the conventional "AI sparkle"
          and is the only glyph in the mockup that could. Same path Home's AI
          card uses. */}
      <svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true">
        <path d="M12 2l2.9 6.3 6.9.7-5.1 4.6 1.4 6.8L12 17.8 5.9 20.4l1.4-6.8L2.2 9l6.9-.7L12 2z" />
      </svg>
      AI Mode
    </button>
  );
}

// ---------------------------------------------------------------------------
// The tier control
// ---------------------------------------------------------------------------

interface TierProps {
  status: AiStatus | null;
  tier: Tier;
  onChange: (tier: Tier) => void;
}

/** Standard / Deep Research, plus an explainer.
 *
 *  Every user-visible word except "Mode" and the explainer's own toggle label
 *  is read from `GET /api/ai/status`. The S16 sentences are server-side (see
 *  api.ts's AiTierInfo) so the admin surface in Plan 5 renders the same
 *  strings; retyping them here is how the two start disagreeing. */
function TierSwitch({ status, tier, onChange }: TierProps) {
  const [explainerOpen, setExplainerOpen] = useState(false);
  const tiers = status?.tiers ?? {};
  return (
    <div className="ai-tiers">
      <span className="ai-tiers-label" id="ai-tier-label">
        Mode
      </span>
      <div className="ai-tierswitch" role="group" aria-labelledby="ai-tier-label">
        {TIER_ORDER.map((key) => {
          const info = tiers[key];
          const unavailable = info ? !info.available : false;
          return (
            <button
              key={key}
              type="button"
              className={tier === key ? "ai-tierseg on" : "ai-tierseg"}
              aria-pressed={tier === key}
              aria-disabled={unavailable || undefined}
              // Per-tier reason, not the global one: an admin can wire up
              // Standard and leave Deep Research without a model.
              title={unavailable ? (info?.reason ?? undefined) : undefined}
              onClick={() => {
                if (unavailable) return;
                onChange(key);
              }}
            >
              {info?.label ?? key}
            </button>
          );
        })}
      </div>
      <button
        type="button"
        className="ai-tier-info"
        aria-expanded={explainerOpen}
        aria-controls="ai-tier-pop"
        onClick={() => setExplainerOpen((v) => !v)}
      >
        What&apos;s the difference?
      </button>
      {explainerOpen && (
        <div id="ai-tier-pop" className="ai-tier-pop" role="note">
          {TIER_ORDER.map((key) => {
            const info = tiers[key];
            if (!info) return null;
            return (
              <div key={key} className="ai-tier-explain">
                <strong>{info.label}</strong> — {info.description}
                {info.examples.length > 0 && (
                  <ul>
                    {info.examples.map((example) => (
                      <li key={example}>{example}</li>
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// The panel
// ---------------------------------------------------------------------------

interface PanelProps {
  chat: UseChatResult;
  status: AiStatus | null;
  /** Which corpus this panel is asking about. Only the starter chips read it
   *  today — see the gate on SuggestionRow — but it is the panel's own
   *  identity and anything corpus-specific added later belongs behind it. */
  corpus: Corpus;
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

function PanelBody({ chat, status, corpus }: PanelProps) {
  const { state } = chat;
  const mascot = useMascotPose(state, false);

  // The source column is allocated on the first chip click and then stays for
  // the rest of the session. Opening on ANY click, even an unresolved one, is
  // deliberate: PdfViewer renders a specific "couldn't open this" state, which
  // beats a click that silently does nothing.
  const [viewerOpen, setViewerOpen] = useState(false);
  useCitationSelected(() => setViewerOpen(true));

  // Flag only the LATEST assistant turn. Older turns keep their own history;
  // re-warning about every uncited turn in a long thread would bury the one
  // the analyst is actually reading.
  const latestAssistant = [...state.turns]
    .reverse()
    .find((t): t is AssistantTurn => t.kind === "assistant");
  const refusal = latestAssistant ? detectRefusal(latestAssistant) : null;

  return (
    <section className="ai-panel" data-testid="ai-panel" aria-label="AI Mode">
      {chat.health && !chat.health.ok && (
        <SystemHealthBanner reason={chat.health.reason} />
      )}

      <div className={viewerOpen ? "ai-panel-main has-source" : "ai-panel-main"}>
        <div className="ai-panel-chat">
          <ChatThread state={state} mascot={mascot} />
        </div>
        {viewerOpen && (
          <aside className="ai-panel-source" aria-label="Source document">
            <PdfViewer />
          </aside>
        )}
      </div>

      {refusal && <RefusalBanner refusal={refusal} />}

      {state.error && (
        // The message is the server's, rendered verbatim — the S19 over-limit
        // refusal arrives here with the real dollar figures in it.
        <div className="chat-notice is-danger chat-notice-banner" role="alert">
          <span>{state.error}</span>{" "}
          <button type="button" className="ai-dismiss" onClick={chat.clearError}>
            dismiss
          </button>
        </div>
      )}

      {/* Budget only. SuggestionRow's three starters are hardcoded budget
          questions ("the FY2025 Aviation Fund balance", "ADOT in FY2024") and
          the component is Task 10's, so they cannot be swapped per corpus from
          here. Sending them at the fiscal-note corpus would make a
          coordinator's very first click a guaranteed empty retrieval — and,
          with the refusal detector working correctly, land them straight in
          the banner. No starters beats three wrong ones; per-corpus starters
          are a follow-up inside SuggestionRow. */}
      {state.turns.length === 0 && corpus === "budget" && (
        <SuggestionRow onPick={chat.send} />
      )}

      <div className="ai-composer">
        <TierSwitch status={status} tier={chat.tier} onChange={chat.setTier} />
        <MessageInput
          onSubmit={chat.send}
          // Disabling on send is the front line against a duplicate turn: the
          // server answers a second concurrent POST with 409, and a 409 is a
          // mistake to prevent, not an error to render.
          disabled={chat.busy}
          placeholder={
            chat.busy
              ? "Working — press Stop to interrupt."
              : "Ask a question — Enter to send, Shift+Enter for a newline"
          }
        />
        {chat.busy && (
          <button type="button" className="ai-stop" onClick={chat.stop}>
            Stop
          </button>
        )}
      </div>

      <Footer connected={Boolean(status?.available) && !state.error} />
    </section>
  );
}
