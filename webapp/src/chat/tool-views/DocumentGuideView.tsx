// Per-tool body view for `document_guide`. Until 2026-08-16 this tool had NO
// view and NO icon: it fell through to RawFallbackView and dumped escaped
// JSON. It runs immediately before the assistant writes a document, so it
// appears in exactly the conversations that end in a memo the analyst sends
// under their own name.

import type { AssistantBlock } from "../chat-types.js";
import MarkdownContent from "../MarkdownContent.js";
import { ErrorBlock } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface GuideOutput {
  report_type: string | null;
  guide: string;
}

function parseGuide(raw: string | undefined): GuideOutput | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "guide" in parsed &&
      typeof (parsed as { guide: unknown }).guide === "string"
    ) {
      return parsed as GuideOutput;
    }
  } catch {
    // fall through
  }
  return null;
}

/** "research-memo" -> "research memo". */
function readableType(t: string | null | undefined): string {
  if (!t) return "document";
  return t.replace(/[-_]/g, " ");
}

export default function DocumentGuideView({ tool }: { tool: ToolBlock }) {
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseGuide(tool.output);
  const asked = (tool.input.report_type as string | undefined) ?? null;
  const type = readableType(parsed?.report_type ?? asked);

  return (
    <div className="chat-stack">
      {/* The honesty line, and it is not optional. Nothing validates the
          finished document against these rules — the design that added this
          tool refused a server-side rewrite on purpose, because that would
          mean editing figures the analyst is about to send under their own
          name. A card that displayed house rules without saying so would imply
          a check that does not exist. */}
      <p className="chat-guide-note">
        Read JLBC's writing rules for a <strong>{type}</strong> before drafting.
        These are the rules the assistant was given — advice only, and nothing
        checks the finished document against them.
      </p>

      {parsed && (
        <div className="chat-guide-rule">
          <MarkdownContent content={parsed.guide} />
        </div>
      )}

      {!parsed && !error && tool.output && (
        <div className="chat-block">
          <pre>{tool.output}</pre>
        </div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
