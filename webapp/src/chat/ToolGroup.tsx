// One row summarizing a RUN of consecutive tool calls — "3 tool calls
// (Search corpus ×2, Browse filters) — all complete". YouCoded's grouping
// pattern in this app's grammar: an expanded turn full of retrieve rows used
// to out-shout the answer; collapsed to one line, the prose stays the star.
// Expanding lifts the children one surface step (is-inset) so header+body
// read as one card.

import { useState } from "react";

import { toolDisplayLabel } from "./tool-display.js";
import type { AssistantBlock } from "./chat-types.js";
import ToolCard from "./ToolCard.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface Props {
  tools: ToolBlock[];
}

/** "Search corpus ×2, Browse filters" — adjacent same-label runs coalesce. */
export function coalesceLabels(tools: ToolBlock[]): string {
  const parts: { label: string; n: number }[] = [];
  for (const t of tools) {
    const label = toolDisplayLabel(t.toolName);
    const last = parts[parts.length - 1];
    if (last && last.label === label) last.n += 1;
    else parts.push({ label, n: 1 });
  }
  return parts
    .map((p) => (p.n > 1 ? `${p.label} ×${p.n}` : p.label))
    .join(", ");
}

export default function ToolGroup({ tools }: Props) {
  const [open, setOpen] = useState(false);
  const running = tools.filter((t) => t.status === "running").length;
  const failed = tools.filter((t) => t.status === "failed").length;
  // Failure outranks progress outranks done — the suffix is the one glanceable
  // health signal for the whole run.
  const suffix =
    failed > 0
      ? `${failed} failed`
      : running > 0
        ? `${running} running`
        : "all complete";

  return (
    <div className={`chat-tool-group${failed > 0 ? " is-failed" : ""}`}>
      <button
        type="button"
        className="chat-tool-head"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        // Fold the coalesced tool-name breakdown into the label too — sighted
        // users see "Search corpus ×2, Browse filters" in chat-tool-summary,
        // and screen-reader users deserve the same detail, not just count +
        // status (Task 13 accessibility fix).
        aria-label={`${tools.length} tool calls, ${coalesceLabels(tools)} — ${suffix}`}
      >
        <span className="chat-tool-label">{tools.length} tool calls</span>
        <span className="chat-tool-summary">
          {coalesceLabels(tools)} — {suffix}
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
        <div className="chat-tool-group-body">
          {tools.map((t) => (
            <ToolCard key={t.toolUseId} tool={t} inGroup />
          ))}
        </div>
      )}
    </div>
  );
}
