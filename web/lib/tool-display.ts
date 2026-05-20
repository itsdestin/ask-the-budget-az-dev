// Friendly labels + summary text for tool-call cards. The renderer
// surfaces these in the collapsed ToolCard header so a user can scan
// the assistant's tool timeline without reading raw `mcp__…` names.
//
// Keep label changes user-facing — debug-style names (chunk_id, raw
// snake_case tool names) belong in the expanded body, never the
// header. The header is a one-line "what just happened" indicator.

/** Normalize an MCP-namespaced name to its tail. `mcp__ask-the-budget-az__retrieve`
 *  → `retrieve`. Returns the input unchanged for non-namespaced names. */
function stripMcpPrefix(toolName: string): string {
  // MCP host emits `mcp__<server>__<tool>`. Two leading underscores
  // separate the prefix from the server name, and two more separate
  // server from tool. We take everything after the last `__`.
  const idx = toolName.lastIndexOf("__");
  return idx >= 0 ? toolName.slice(idx + 2) : toolName;
}

/** User-facing display name for a tool. Falls back to the
 *  prefix-stripped raw name when we haven't specialized it. */
export function toolDisplayLabel(toolName: string): string {
  const bare = stripMcpPrefix(toolName);
  switch (bare) {
    // Budget MCP server
    case "retrieve":
      return "Search corpus";
    case "cite":
      return "Cite claim";
    case "cite_batch":
      return "Cite claims";
    case "list_filter_values":
      return "Browse filters";
    // Claude Code core tools
    case "Bash":
      return "Shell";
    case "Read":
      return "Read file";
    case "Edit":
      return "Edit file";
    case "Write":
      return "Write file";
    case "Glob":
      return "Find files";
    case "Grep":
      return "Search files";
    case "WebFetch":
      return "Fetch URL";
    case "WebSearch":
      return "Web search";
    case "ToolSearch":
      return "Look up tool";
    case "TodoWrite":
      return "Update todos";
    case "Task":
      return "Run subagent";
    default:
      return bare;
  }
}

/** One-line summary for the collapsed ToolCard header. Designed to
 *  fit on a single truncated row alongside the tool label. Returns
 *  null when no useful summary is available (renderer skips the
 *  span in that case).
 *
 *  Important contract: do NOT echo back text that already appears
 *  prominently elsewhere in the chat. `cite`'s claim_span is the
 *  canonical example — that text is already underlined inline in
 *  the assistant turn; repeating it in the tool header is noise.
 *  Show source-side metadata or a status flag instead. */
export function toolHeaderSummary(
  toolName: string,
  input: Record<string, unknown>,
): string | null {
  const bare = stripMcpPrefix(toolName);
  const str = (k: string): string | null => {
    const v = input[k];
    return typeof v === "string" && v.length > 0 ? v : null;
  };
  switch (bare) {
    case "retrieve":
      return str("query");
    case "cite": {
      // Don't echo the full claim_span — it's already underlined
      // inline in the answer text. Show the confidence flag so a
      // skimmer can see at a glance whether this is a verbatim or
      // paraphrase cite.
      const conf = str("confidence");
      return conf ? conf : null;
    }
    case "cite_batch": {
      // Surface the batch size so a skimmer sees "Cite claims · 17
      // citations" rather than just the tool name.
      const arr = (input as { citations?: unknown }).citations;
      if (Array.isArray(arr)) {
        const n = arr.length;
        return `${n} citation${n === 1 ? "" : "s"}`;
      }
      return null;
    }
    case "list_filter_values": {
      const field = str("field");
      return field ? field : null;
    }
    case "Bash":
      return str("command");
    case "Read":
    case "Edit":
    case "Write": {
      const fp = str("file_path");
      if (!fp) return null;
      // Show just the basename (last path segment) so long paths
      // don't push the rest of the header off-screen. The expanded
      // body still has the full path.
      const idx = Math.max(fp.lastIndexOf("/"), fp.lastIndexOf("\\"));
      return idx >= 0 ? fp.slice(idx + 1) : fp;
    }
    case "Glob":
    case "Grep":
      return str("pattern");
    case "WebFetch": {
      const url = str("url");
      if (!url) return null;
      try {
        return new URL(url).hostname;
      } catch {
        return url;
      }
    }
    case "WebSearch":
      return str("query");
    case "ToolSearch":
      return str("query");
    case "TodoWrite":
      // The TodoWrite payload is a list, not a string; surface its
      // length so a skimmer sees "5 todos" without expanding.
      if (Array.isArray((input as { todos?: unknown }).todos)) {
        const n = (input as { todos: unknown[] }).todos.length;
        return `${n} todo${n === 1 ? "" : "s"}`;
      }
      return null;
    default: {
      // Generic fallback — first non-empty string value.
      for (const v of Object.values(input)) {
        if (typeof v === "string" && v.length > 0) return v;
      }
      return null;
    }
  }
}
