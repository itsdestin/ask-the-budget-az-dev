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
//      The old namespaced string is still a historical record of the MCP
//      server name, which is why it survives here in the comment.
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

/** The collapsed card's header, split so the caller can weight the two parts
 *  differently: the verb renders bold and keeps the row scannable down a long
 *  conversation, the rest reads as ordinary prose (spec TC13).
 *
 *  Each tool needs its own preposition, which is exactly why this lives here
 *  and not in the component — "Searched for X", "Wrote the document X",
 *  "Checked the house style for X" share no grammar. */
export function toolHeaderSentence(
  tools: { toolName: string; input: Record<string, unknown> }[],
  tense: LabelTense,
): { verb: string; rest: string } {
  const first = tools[0];
  if (!first) return { verb: "", rest: "" };

  const running = tense === "present";
  const tail = running ? "…" : "";

  // How many calls share the LEADING tool's name. Counted on the leading run
  // only: the sentence names what it started doing, then appends anything of a
  // different kind after it.
  let sameKind = 0;
  while (sameKind < tools.length && tools[sameKind]!.toolName === first.toolName) {
    sameKind += 1;
  }
  const more = sameKind > 1 ? ` and ${sameKind - 1} more` : "";

  // Anything after the leading run, described in one clause. Deliberately not
  // recursive: the row is a single truncating line, and a nested sentence would
  // be cut off before it read as one.
  const remainder = tools.slice(sameKind);
  const then =
    remainder.length > 0
      ? `, then ${lowerFirst(coalesceActionLabels(remainder, tense))}`
      : "";

  const q = (s: string) => `“${s}”`;
  const summary = toolHeaderSummary(first.toolName, first.input);

  switch (first.toolName) {
    case "retrieve":
      return {
        verb: running ? "Searching" : "Searched",
        rest: summary ? ` for ${q(summary)}${more}${tail}${then}` : `${more}${tail}${then}`,
      };
    case "create_document":
      return {
        verb: running ? "Writing" : "Wrote",
        rest: summary ? ` the document ${q(summary)}${more}${tail}${then}` : ` a document${more}${tail}${then}`,
      };
    case "document_guide":
      return {
        verb: running ? "Checking" : "Checked",
        rest: ` the house style for a ${reportTypeName(summary)}${more}${tail}${then}`,
      };
    case "list_filter_values":
      // ${more} matches every sibling branch. Without it three filter checks
      // rendered identically to one — a silent undercount of real work, the
      // same defect 3433779 fixed for create_document and document_guide and
      // missed here.
      return {
        verb: running ? "Checking" : "Checked",
        rest: ` which ${filterFieldName(summary)} the corpus covers${more}${tail}${then}`,
      };
    default: {
      // Unregistered tool: the bare name plus its first string argument, which
      // is a legible degradation rather than a blank row.
      return {
        verb: first.toolName,
        rest: summary ? ` ${summary}${more}${tail}${then}` : `${more}${tail}${then}`,
      };
    }
  }
}

function lowerFirst(s: string): string {
  return s.length > 0 ? s.charAt(0).toLowerCase() + s.slice(1) : s;
}

/** "research-memo" -> "research memo". The tool's own default is applied
 *  server-side, so a null here means the model asked for no particular shape;
 *  naming one would show a choice it never made. */
function reportTypeName(reportType: string | null): string {
  if (!reportType) return "document";
  return reportType.replace(/[-_]/g, " ");
}

/** The filter FIELD as a plain noun. Raw column names never reach an analyst.
 *
 *  KEYED ON `list_filter_values`'s OWN vocabulary — `agency | fund | doc_type
 *  | publisher`, the enum in harness/tools.py, which raises on anything else.
 *  This was first keyed on `retrieve`'s FILTER vocabulary
 *  (`agency_canonical_id`, `fiscal_year`) — values this tool can never emit —
 *  so the real input "agency" hit `default` and the header read "Checked which
 *  values the corpus covers" instead of TC14's "agencies". Every test fixture
 *  pinned the impossible input too, which is how it shipped green through
 *  three reviews. Exported so the suite can pin this key set against the tool
 *  file itself. */
export const FILTER_FIELD_NAMES: Record<string, string> = {
  agency: "agencies",
  fund: "funds",
  doc_type: "kinds of document",
  publisher: "publishers",
};

function filterFieldName(field: string | null): string {
  if (!field) return "values";
  return FILTER_FIELD_NAMES[field] ?? "values";
}
