// One collapsible card summarizing a run of tool calls. Since 2026-08-16 it is
// normally the FIRST CHILD OF AN ANSWER BUBBLE rather than a sibling above one
// — see docs/superpowers/specs/2026-08-16-tool-card-in-message-bubble-design.md.
//
// It renders for a run of ANY size, n >= 1. At n = 1 it expands straight to
// that call's body: the bare ToolCard it replaced opened in one click, and
// making an analyst click twice to reach a source would be a regression the
// count-based tests could not see (TC5).

import { useState } from "react";

import { coalesceActionLabels, toolHeaderSummary } from "./tool-display.js";
import type { AssistantBlock } from "./chat-types.js";
import ToolCard from "./ToolCard.js";
import ToolBody from "./tool-views/ToolBody.js";
import { toolGlyph } from "./tool-views/primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tools: ToolBlock[];
}

export default function ToolGroup({ tools }: Props) {
  const [open, setOpen] = useState(false);

  const first = tools[0];
  if (!first) return null;

  const running = tools.some((t) => t.status === "running");
  const label = coalesceActionLabels(tools, running ? "present" : "past");

  // n = 1 always shows the call's own summary — the query — in both states.
  // A multi-call run shows progress while it is in flight and NOTHING once it
  // settles: "all complete" would be a false positive claim while a failure is
  // suppressed, and silence claims nothing (TC3, TC9).
  const single = tools.length === 1;
  const settled = tools.filter((t) => t.status !== "running").length;
  const detail = single
    ? toolHeaderSummary(first.toolName, first.input)
    : running
      ? `${settled} of ${tools.length} done`
      : null;

  // The accessible name tracks the visible text EXACTLY. A screen-reader user
  // must not be told about a transient failure the sighted user is
  // deliberately not being alarmed by, or the suppression is only cosmetic
  // (TC12).
  const ariaLabel = detail ? `${label}, ${detail}` : label;

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
            in flight. aria-hidden because the button's own aria-label is its
            accessible name. */}
        <svg
          viewBox="0 0 12 12"
          width={12}
          height={12}
          className={"chat-tool-glyph" + (running ? " chat-pulse" : "")}
          aria-hidden="true"
        >
          {toolGlyph(first.toolName)}
        </svg>
        <span className="chat-tool-label">{label}</span>
        {detail && <span className="chat-tool-summary">{detail}</span>}
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
            <ToolBody tool={first} />
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
