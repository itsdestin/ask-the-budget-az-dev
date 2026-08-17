// One collapsible card summarizing a run of tool calls. Since 2026-08-16 it is
// normally the FIRST CHILD OF AN ANSWER BUBBLE rather than a sibling above one
// — see docs/superpowers/specs/2026-08-16-tool-card-in-message-bubble-design.md.
//
// It renders for a run of ANY size, n >= 1. At n = 1 it expands straight to
// that call's body: the bare ToolCard it replaced opened in one click, and
// making an analyst click twice to reach a source would be a regression the
// count-based tests could not see (TC5).

import { useState } from "react";

import { toolHeaderSentence } from "./tool-display.js";
import type { AssistantBlock } from "./chat-types.js";
import ToolCard from "./ToolCard.js";
import ToolBody from "./tool-views/ToolBody.js";
import { ToolGlyph } from "./tool-views/primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tools: ToolBlock[];
}

export default function ToolGroup({ tools }: Props) {
  const [open, setOpen] = useState(false);

  const first = tools[0];
  if (!first) return null;

  const running = tools.some((t) => t.status === "running");

  // n = 1 always shows the call's own summary — the query — in both states.
  // A multi-call run reads as one sentence (TC13) and settles into silence
  // about individual outcomes: "all complete" would be a false positive claim
  // while a failure is suppressed, and silence claims nothing (TC3, TC9).
  const single = tools.length === 1;

  // The header sentence, split so the verb can render bold while the rest
  // stays normal weight (TC13/TC14). The accessible name tracks the visible
  // text EXACTLY — a screen-reader user must not be told about a transient
  // failure the sighted user is deliberately not being alarmed by, or the
  // suppression is only cosmetic (TC12).
  const sentence = toolHeaderSentence(tools, running ? "present" : "past");
  const ariaLabel = `${sentence.verb}${sentence.rest}`;

  // Only consulted inside the expansion — never in the collapsed header, where
  // TC9 forbids any failure signal at all.
  const failed = single && first.status === "failed";
  const hasErrorBody = Boolean(first.isError && first.output);

  return (
    <div className="chat-tool-group">
      <button
        type="button"
        className="chat-tool-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-label={ariaLabel}
      >
        {/* The run's leading tool supplies the glyph. Neutral in every state —
            failure spends no colour here (TC9) — and it pulses while work is
            in flight. No `label` is passed, so ToolGlyph renders
            aria-hidden: the button's own aria-label is its accessible name. */}
        <ToolGlyph tool={first.toolName} running={running} />
        <span className="chat-tool-sentence">
          <b className="chat-tool-verb">{sentence.verb}</b>
          {sentence.rest}
        </span>
        <svg
          viewBox="0 0 10 6"
          width={10}
          height={6}
          className={`chat-tool-chevron${open ? " is-open" : ""}`}
          aria-hidden="true"
        >
          <path
            d="M1 1l4 4 4-4"
            stroke="currentColor"
            strokeWidth="1.6"
            fill="none"
            strokeLinecap="round"
          />
        </svg>
      </button>
      {open && (
        // ONE capped container for either expansion shape, so several child
        // rows opened at once still cannot exceed the cap (TC8).
        <div className="chat-tool-group-expansion">
          {single ? (
            // TC9 is "demoted, not DELETED". At n >= 2 the failure survives
            // because each call renders through ToolCard, which owns both the
            // `.chat-tool.is-failed` treatment and the glyph's "failed"
            // accessible name. The n = 1 branch renders ToolBody directly (TC5
            // — one click, not two) and so bypasses BOTH, which erased the
            // failure entirely: a lone failed retrieve expanded to
            // `<div class="chat-tool-body"><div class="chat-stack"></div></div>`
            // with nothing matching /fail/i anywhere in the DOM or the
            // accessible name. This wrapper restores the signal at the only
            // place TC9 allows it — inside the expansion — without adding the
            // child row that would cost the single click.
            //
            // The note renders on `status === "failed"` and NOT on
            // `isError && output`, because that pair is reachable with both
            // absent: history-rehydrate.ts marks any still-running tool block
            // failed when a stored transcript was torn or stopped mid-call,
            // with no error text to show. That case is the whole reason this
            // exists — every tool view gates its ErrorBlock on `isError &&
            // output`, so an expansion built on that gate renders NOTHING.
            <div
              className={"chat-tool-single" + (failed ? " is-failed" : "")}
            >
              {failed && (
                <p className="chat-tool-failed-note">
                  This call failed.
                  {hasErrorBody ? "" : " No result was recorded."}
                </p>
              )}
              <ToolBody tool={first} />
            </div>
          ) : (
            <div className="chat-tool-group-body">
              {tools.map((t) => (
                <ToolCard key={t.toolUseId} tool={t} inGroup />
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
