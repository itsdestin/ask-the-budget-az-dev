// Friendly labels + summary text for tool-call cards. The renderer surfaces
// these in the collapsed ToolCard header so an analyst can scan the model's
// tool timeline without reading raw snake_case names.
//
// Keep label changes user-facing — debug-style names (chunk_id, raw tool
// names) belong in the expanded body, never the header. The header is a
// one-line "what just happened" indicator.
//
// Ported from web/lib/tool-display.ts with two deliberate edits:
//
//   1. `stripMcpPrefix` is gone. It normalized `mcp__ask-the-budget-az__cite`
//      down to `cite`, which mattered when an MCP host prefixed every tool
//      name. Plan 4 deleted the MCP server; harness/tools.py hands the model
//      bare names and there is no code path that can produce a prefixed one.
//   2. The Claude Code core tools (Bash, Read, Edit, Write, Glob, Grep,
//      WebFetch, WebSearch, ToolSearch, TodoWrite, Task) are gone for the
//      same reason — Invariant 7 removed the whole filesystem/shell surface.
//      `create_document` and `document_guide` are the two additions.
//
// The generic fallbacks stay: a tool that reaches the UI without an entry
// here renders its own name and its first string argument, which is a
// legible degradation rather than a blank header.

/** User-facing display name for a tool. Falls back to the raw name when we
 *  haven't specialized it. */
export function toolDisplayLabel(toolName: string): string {
  switch (toolName) {
    case "retrieve":
      return "Search corpus";
    case "cite":
      return "Cite claim";
    case "cite_batch":
      return "Cite claims";
    case "list_filter_values":
      return "Browse filters";
    case "create_document":
      return "Write document";
    case "document_guide":
      return "Check style guide";
    default:
      return toolName;
  }
}

/** One-line summary for the collapsed ToolCard header. Designed to fit on a
 *  single truncated row alongside the tool label. Returns null when no useful
 *  summary is available (the renderer skips the span in that case).
 *
 *  Important contract: do NOT echo back text that already appears prominently
 *  elsewhere in the chat. `cite`'s claim_span is the canonical example — that
 *  text is already underlined inline in the assistant turn, so repeating it in
 *  the tool header is noise. Show source-side metadata or a status flag. */
export function toolHeaderSummary(
  toolName: string,
  input: Record<string, unknown>,
): string | null {
  const str = (k: string): string | null => {
    const v = input[k];
    return typeof v === "string" && v.length > 0 ? v : null;
  };
  switch (toolName) {
    case "retrieve":
      return str("query");
    case "cite": {
      // Don't echo the full claim_span — it's already underlined inline in
      // the answer. Show the confidence flag so a skimmer can see at a glance
      // whether this is a verbatim or paraphrase cite.
      return str("confidence");
    }
    case "cite_batch": {
      // Surface the batch size so a skimmer sees "Cite claims · 17 citations"
      // rather than just the tool name.
      const arr = (input as { citations?: unknown }).citations;
      if (Array.isArray(arr)) {
        const n = arr.length;
        return `${n} citation${n === 1 ? "" : "s"}`;
      }
      return null;
    }
    case "list_filter_values":
      return str("field");
    case "create_document":
      // The title, not the body: the body is a whole memo and the header is
      // one truncated line.
      return str("title");
    case "document_guide":
      // The report type the model ASKED for. Null when it asked for none —
      // the tool defaults to research-memo server-side, but printing that
      // here would show a choice the model never made. Stated explicitly
      // rather than left to the generic fallback below, which would start
      // returning some other field the day the schema grows a second string.
      return str("report_type");
    default: {
      // Generic fallback — first non-empty string value.
      for (const v of Object.values(input)) {
        if (typeof v === "string" && v.length > 0) return v;
      }
      return null;
    }
  }
}

/** Which tense a run's label is written in. A run is described in the present
 *  participle while any of its calls is still in flight and in the past tense
 *  once every call has settled — "Searched" over a call that is still running
 *  is a false statement about a live process (spec TC4). */
export type LabelTense = "past" | "present";

// These are ACTION labels for a whole run, and they are deliberately separate
// from `toolDisplayLabel` above. That one names a CALL — "Search corpus" — and
// present-tense-imperative is the right register for a row that says "here is
// the call that was made"; it still names the child rows inside an expansion.
// This one names what the assistant DID, and reads as narration.
const PAST_ACTION: Record<string, string> = {
  retrieve: "Searched",
  cite: "Cited",
  cite_batch: "Cited",
  list_filter_values: "Browsed filters",
  create_document: "Wrote a document",
  document_guide: "Checked the style guide",
};

const PRESENT_ACTION: Record<string, string> = {
  retrieve: "Searching",
  cite: "Citing",
  cite_batch: "Citing",
  list_filter_values: "Browsing filters",
  create_document: "Writing a document",
  document_guide: "Checking the style guide",
};

/** What the assistant did (or is doing) with one tool. Falls back to the raw
 *  name, which is a legible degradation for a tool nobody has labelled yet. */
export function toolActionLabel(toolName: string, tense: LabelTense): string {
  const table = tense === "past" ? PAST_ACTION : PRESENT_ACTION;
  return table[toolName] ?? toolName;
}

/** "Searched ×2, wrote a document" — ADJACENT same-label calls coalesce into a
 *  count, and only the leading phrase keeps its capital so the whole thing
 *  reads as one sentence fragment rather than several stacked headings.
 *
 *  Adjacency matters: the array is the model's real sequence of work, so
 *  merging across a gap would claim a run of three searches where there were
 *  two separated by something else. */
export function coalesceActionLabels(
  tools: { toolName: string }[],
  tense: LabelTense,
): string {
  const parts: { label: string; n: number }[] = [];
  for (const t of tools) {
    const label = toolActionLabel(t.toolName, tense);
    const last = parts[parts.length - 1];
    if (last && last.label === label) last.n += 1;
    else parts.push({ label, n: 1 });
  }
  return parts
    .map((p, i) => {
      const text = p.n > 1 ? `${p.label} ×${p.n}` : p.label;
      return i === 0 ? text : text.charAt(0).toLowerCase() + text.slice(1);
    })
    .join(", ");
}
