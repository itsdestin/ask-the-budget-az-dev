// The ask bar's tools menu — two toggles behind one icon.
//
// REPLACES the `.ai-controls` row (CorpusSwitch + TierSwitch + a "What's the
// difference?" link) that sat above the composer. Destin, 2026-08-02, after
// seeing it live: the row read as a control panel bolted above the box, and
// the explainer link was the only place the tier copy lived.
//
// Both settings are now stated as things you switch ON, which is what an
// analyst actually thinks: "use Deep Research", "search fiscal notes". The
// off state is the default in both cases, so nothing needs a label to explain
// what "off" means.
//
// WHY the descriptions live in here rather than behind a link: they are the
// consequences of the switch you are looking at (44x the cost; a new
// conversation). Copy that describes a decision belongs where the decision is
// made — a link asks the analyst to go and check, which nobody does twice.
//
// The tier copy is still the SERVER's (S16: `/api/ai/status` owns those
// sentences so the admin page and this cannot drift). Only the corpus
// sentence is ours, because no endpoint publishes one.

import { useEffect, useRef, useState } from "react";

import type { AiStatus } from "../api.js";
import type { Corpus, Tier } from "./use-chat.js";

interface Props {
  status: AiStatus | null;
  tier: Tier;
  onTierChange: (tier: Tier) => void;
  corpus: Corpus;
  /** Absent when the owner cannot change the corpus — the toggle is then not
   *  rendered at all. Switching corpus discards the conversation, so only the
   *  component that owns the remount (Ai.tsx, via key={corpus}) may offer it. */
  onCorpusChange?: (corpus: Corpus) => void;
  /** What the fiscal-note corpus contains, for the toggle's description. */
  fiscalNotesScope?: string;
}

/** One row: a switch, a name, and what turning it on actually does. */
function ToolToggle({
  on,
  label,
  description,
  disabledReason,
  onChange,
  testId,
}: {
  on: boolean;
  label: string;
  description: string;
  /** Non-null renders the row inert and shows the server's own explanation.
   *  An admin can wire up Standard and leave Deep Research without a model. */
  disabledReason?: string | null;
  onChange: (next: boolean) => void;
  testId: string;
}) {
  const inert = Boolean(disabledReason);
  return (
    <button
      type="button"
      role="menuitemcheckbox"
      aria-checked={on}
      aria-disabled={inert || undefined}
      className={inert ? "ask-opt is-inert" : "ask-opt"}
      data-testid={testId}
      onClick={() => {
        if (inert) return;
        onChange(!on);
      }}
    >
      <span className="ask-sw" aria-hidden="true">
        <span className="ask-sw-track">
          <span className="ask-sw-knob" />
        </span>
      </span>
      <span className="ask-opt-body">
        <span className="ask-opt-title">{label}</span>
        <span className="ask-opt-desc">{disabledReason ?? description}</span>
      </span>
    </button>
  );
}

export default function ToolsMenu({
  status,
  tier,
  onTierChange,
  corpus,
  onCorpusChange,
  fiscalNotesScope,
}: Props) {
  const [open, setOpen] = useState(false);
  const wrapRef = useRef<HTMLSpanElement | null>(null);

  const deepOn = tier === "deep_research";
  const notesOn = corpus === "fiscal_notes";
  // The whole point of the pip. Both settings are invisible once the menu
  // closes, and both are consequential — Deep Research costs roughly 44x a
  // Standard answer, and the corpus decides which documents a citation can
  // come from. A setting the analyst cannot see is a setting they cannot
  // un-set on purpose.
  const anyOn = deepOn || notesOn;

  useEffect(() => {
    if (!open) return;
    const onDocClick = (e: MouseEvent) => {
      if (!wrapRef.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDocClick);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDocClick);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const deep = status?.tiers?.deep_research;
  const deepUnavailable = deep ? !deep.available : false;

  return (
    <span className="ask-tools" ref={wrapRef}>
      <button
        type="button"
        className={anyOn ? "ask-icon is-on" : "ask-icon"}
        aria-label="Answer tools"
        aria-haspopup="menu"
        aria-expanded={open}
        data-testid="ask-tools-button"
        onClick={() => setOpen((v) => !v)}
      >
        <svg
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          aria-hidden="true"
        >
          <path d="M4 7h10M18 7h2M4 12h4M12 12h8M4 17h12" />
          <circle cx="16" cy="7" r="2" />
          <circle cx="10" cy="12" r="2" />
          <circle cx="18" cy="17" r="2" />
        </svg>
      </button>
      {anyOn && <span className="ask-pip" data-testid="ask-tools-pip" />}

      {open && (
        <div className="ask-pop" role="menu" aria-label="Answer tools">
          <ToolToggle
            testId="tool-deep-research"
            on={deepOn}
            label="Use Deep Research"
            // Server-owned copy (S16). The fallback is only reached when the
            // status probe has not answered, which is also when the menu is
            // unreachable — it exists so the type is honest, not for users.
            description={
              deep?.description ??
              "Reads far more of the corpus. Slower, and far more expensive."
            }
            disabledReason={deepUnavailable ? deep?.reason ?? null : null}
            onChange={(next) => onTierChange(next ? "deep_research" : "standard")}
          />
          {onCorpusChange && (
            <>
              <div className="ask-pop-sep" />
              <ToolToggle
                testId="tool-fiscal-notes"
                on={notesOn}
                label="Search Fiscal Notes"
                description={`${
                  fiscalNotesScope ??
                  "JLBC's published fiscal notes on proposed legislation."
                } Starts a new conversation.`}
                onChange={(next) => {
                  onCorpusChange(next ? "fiscal_notes" : "budget");
                  // Closed on purpose: the switch discards the conversation and
                  // remounts everything under it, so leaving a menu open over a
                  // thread that no longer exists would be a lie about state.
                  setOpen(false);
                }}
              />
            </>
          )}
        </div>
      )}
    </span>
  );
}
