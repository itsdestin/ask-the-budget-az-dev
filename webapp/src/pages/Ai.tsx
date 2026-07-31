import { useState } from "react";

import {
  AI_GATED_TOOLTIP,
  AI_PROBING_TOOLTIP,
  AiModePanel,
} from "../chat/AiModePanel";
import { useAiStatus } from "../chat/use-ai-status";
import { useChat, type Corpus } from "../chat/use-chat";

// AI Mode — its own destination (Destin, 2026-07-31).
//
// It used to be a toggle in the page-header band of BOTH corpus pages, which
// spec S9 asked for. Destin used it and asked for this instead: "I hate that
// 'AI Mode' is part of the budget search tab." So the toggles are gone from
// Budget Documents and Fiscal Notes, and the corpus they chose implicitly is
// chosen explicitly here. See the deviation note in STATUS.md's Plan 4 section
// — a future session should NOT "restore fidelity" to S9.
//
// The corpus picker is not decoration. The fiscal-note coordinator is a primary
// user in the spec, and their triage question ("have we written a note like
// this before?") is a fiscal-note-corpus question; deleting the fiscal-note
// toggle without replacing it would have deleted their workflow.
//
// The page is deliberately thin: `AiModePanel` is the shared surface (thread,
// tier control, composer, source viewer, honesty footer) and this file only
// decides WHICH corpus it is pointed at and WHETHER the server can answer at
// all.

interface CorpusOption {
  value: Corpus;
  label: string;
  /** What the assistant can actually see when this corpus is picked. Stated on
   *  the page because "AI Mode" alone does not tell an analyst which documents
   *  the answer will be built from — and that is the first thing a citation
   *  audit depends on. */
  scope: string;
}

const CORPORA: CorpusOption[] = [
  {
    value: "budget",
    label: "Budget documents",
    scope: "Baselines, appropriations reports, executive budgets, and budget bills.",
  },
  {
    value: "fiscal_notes",
    label: "Fiscal notes",
    scope: "JLBC's published fiscal notes on proposed legislation.",
  },
];

export function Ai() {
  const [corpus, setCorpus] = useState<Corpus>("budget");
  const status = useAiStatus();
  // null = the probe is still in flight. Three states, not two: saying "needs an
  // API key" before anyone has checked would state a cause nobody knows yet.
  const probing = status === null;
  const gated = !probing && !status.available;
  const picked = CORPORA.find((c) => c.value === corpus)!;

  return (
    <main className="page-ai" data-testid="ai">
      <section className="subhero">
        <div className="wrap">
          <h1>AI Mode</h1>
          {/* Written to ~124 chars: the `.lead` rule clamps at two lines, so
              anything longer would be cut mid-sentence (DESIGN-SYSTEM.md §6). */}
          <p className="lead">
            Ask a question in plain language and get a written answer, with every
            claim carrying a citation to the page behind it.
          </p>
          {/* The mockup's page-header chip row, same as the other sub-pages. The
              picker sits in it because "which corpus am I asking?" is page-level
              state, which is exactly what this band is for — and it is where the
              AI Mode pill used to live on the two corpus pages. */}
          <div className="chips">
            <div className="ai-corpus" role="group" aria-label="Corpus">
              {CORPORA.map((option) => (
                <button
                  key={option.value}
                  type="button"
                  className={
                    option.value === corpus ? "ai-corpus-chip on" : "ai-corpus-chip"
                  }
                  aria-pressed={option.value === corpus}
                  onClick={() => setCorpus(option.value)}
                >
                  {option.label}
                </button>
              ))}
            </div>
            <span className="chip">{picked.scope}</span>
          </div>
          {/* Said BEFORE it happens, not after: switching corpus discards the
              thread on screen (see the key= note below), and an analyst who
              loses a long conversation to a chip click without warning has been
              ambushed by the UI. */}
          <p className="ai-corpus-note">
            Switching corpus starts a new conversation.
          </p>
        </div>
      </section>

      <div className="wrap">
        {probing || gated ? (
          <section className="card ai-gate" data-testid="ai-gate">
            <p>{probing ? AI_PROBING_TOOLTIP : AI_GATED_TOOLTIP}</p>
            {gated && status.reason && (
              // The server's own sentence, verbatim — it knows whether the key
              // is missing, the model is unset, or the config failed to load.
              <p className="ai-gate-reason">Reported reason: {status.reason}</p>
            )}
          </section>
        ) : (
          // key={corpus} REMOUNTS the conversation on every corpus switch, and
          // that is load-bearing, not a re-render hint. `useChat` creates a
          // conversation lazily on the first send and then holds that
          // conversation_id for the life of the hook; the corpus is only read
          // when the conversation is created. Without this remount, an analyst
          // who asks a budget question and then switches to Fiscal notes would
          // keep sending into the BUDGET conversation — the answer would come
          // back cited, confident, and drawn from the wrong corpus, which is the
          // worst failure this app has. Remounting also resets the tier to
          // Standard, which is what S16 requires of every new conversation.
          <AiConversation key={corpus} corpus={corpus} status={status} />
        )}
      </div>
    </main>
  );
}

/** Owns the chat hook so that `key` on THIS component is what starts a fresh
 *  conversation. Splitting it out is the whole mechanism: a `key` on
 *  `AiModePanel` would not help, because the hook lives in the parent. */
function AiConversation({
  corpus,
  status,
}: {
  corpus: Corpus;
  status: ReturnType<typeof useAiStatus>;
}) {
  const chat = useChat(corpus);
  return <AiModePanel chat={chat} status={status} corpus={corpus} />;
}
