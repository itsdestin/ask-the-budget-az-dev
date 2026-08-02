import { useEffect, useState } from "react";

import {
  AI_GATED_TOOLTIP,
  AI_PROBING_TOOLTIP,
  AiModePanel,
  type CorpusOption,
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
//
// The navy band is GONE (Destin, 2026-08-02): "i want to remove the 'ai mode'
// hero strip thing. we can move the budget/fiscal note corpus toggle alongside
// the standard/deep research toggle." On a viewport-pinned chat the band spent
// ~110px of thread on every screen to label a page the nav pill already
// labels. This file still OWNS the corpus — `key={corpus}` below is the whole
// safety mechanism — it just no longer draws the control.

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

/** The class this page puts on `<html>` for as long as it is mounted, and the
 *  hook that puts it there. `app.css` hangs the whole pinned-viewport layout off
 *  it (search for "AI Mode — full-page chat shell").
 *
 *  WHY a class on <html> rather than a global stylesheet rule: the retired app
 *  WAS the chat, so it could say `html, body { overflow: hidden }` once and be
 *  done. Here AI Mode is one route among six, and the other five — Home, Budget
 *  Documents, Fiscal Notes, Upload, Settings — are ordinary pages whose content
 *  runs well past one screen. A global rule would clip them with no way to
 *  scroll to what was cut off. Toggling a class means the pin exists exactly as
 *  long as the page that needs it, and React's effect cleanup removes it on
 *  route change AND on unmount without either path needing to remember to.
 *
 *  WHY <html> and not <body>: `html` already carries `overflow-x: clip` from the
 *  base block, and a root element whose overflow is not `visible` stops the
 *  browser propagating <body>'s overflow to the viewport. Pinning the root
 *  itself sidesteps that rule instead of depending on it. */
export const AI_FULLPAGE_CLASS = "ai-fullpage";

function useFullPageChatShell(): void {
  useEffect(() => {
    const root = document.documentElement;
    root.classList.add(AI_FULLPAGE_CLASS);
    return () => root.classList.remove(AI_FULLPAGE_CLASS);
  }, []);
}

export function Ai() {
  const [corpus, setCorpus] = useState<Corpus>("budget");
  useFullPageChatShell();
  const status = useAiStatus();
  // null = the probe is still in flight. Three states, not two: saying "needs an
  // API key" before anyone has checked would state a cause nobody knows yet.
  const probing = status === null;
  const gated = !probing && !status.available;

  return (
    <main className="page-ai" data-testid="ai">
      {/* ── the page's accessible name ───────────────────────────────────────
          The navy band that used to carry this h1, the corpus picker, a scope
          chip and a switch warning is GONE (Destin, 2026-08-02) — see the
          note at the top of this file. The h1 stays because deleting it would
          leave <main> unnamed and the route indistinguishable from the others
          to a screen reader; it is clipped rather than `display:none` so it
          stays in the accessibility tree.

          The band's other three items were not dropped, they moved:
            corpus picker — now beside the Standard / Deep Research switch in
                            the composer chrome, which is where every other
                            "how should this question be answered?" control
                            already lives.
            scope text    — the `title` on each corpus segment (AiModePanel),
                            plus the footer's standing "Sources: JLBC · AGAO ·
                            AZ Legislature · Governor's Office · N documents".
            switch notice — rendered by AiModePanel only once there is a
                            conversation to lose, which is the only moment it
                            says anything. */}
      <h1 className="ai-vh">AI Mode</h1>

      {/* The growth region: everything above is zero-height, so this is what
          absorbs the viewport and hands it to the panel. */}
      <div className="wrap ai-stage">
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
          <AiConversation
            key={corpus}
            corpus={corpus}
            corpusOptions={CORPORA}
            onCorpusChange={setCorpus}
            status={status}
          />
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
  corpusOptions,
  onCorpusChange,
  status,
}: {
  corpus: Corpus;
  corpusOptions: CorpusOption[];
  onCorpusChange: (corpus: Corpus) => void;
  status: ReturnType<typeof useAiStatus>;
}) {
  const chat = useChat(corpus);
  return (
    <AiModePanel
      chat={chat}
      status={status}
      corpus={corpus}
      corpusOptions={corpusOptions}
      // Calling this re-keys THIS component from the parent, so the picker
      // unmounts itself along with the conversation it is discarding. That is
      // fine — it is stateless, and React commits the remount synchronously.
      onCorpusChange={onCorpusChange}
    />
  );
}
