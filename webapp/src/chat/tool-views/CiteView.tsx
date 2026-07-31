// Per-tool body view for the `cite` tool.
//
// Input is { chunk_id, span_start|quote, confidence, claim_span }; output is a
// small {ok, citation_id?, error?} ack. The visible value here is the
// SOURCE-side metadata, NOT the claim — the claim_span is already underlined
// inline in the assistant turn and the ToolCard header already shows the
// confidence, so a third repeat adds noise without information.
//
// Ported from web/components/tool-views/CiteView.tsx. One deletion: the
// `raw.startsWith("MCP error")` branch. There is no MCP server; a tool that
// fails now returns {ok:false, error:"…"} JSON whose error string is already
// analyst-readable, which the normal parse path handles.

import type { AssistantBlock } from "../chat-types.js";
import { Chip, ErrorBlock } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

const CONFIDENCE_GLYPH: Record<string, { glyph: string; label: string }> = {
  verbatim: { glyph: "✓", label: "Verbatim" },
  paraphrase: { glyph: "≈", label: "Paraphrase" },
};

interface CiteAck {
  ok: boolean;
  citation_id?: string;
  error?: string;
  cited_text_preview?: string;
}

function parseAck(raw: string | undefined): CiteAck | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && "ok" in parsed) {
      return parsed as CiteAck;
    }
  } catch {
    // fall through to the synthetic failure ack below
  }
  // Anything that isn't a well-formed ack becomes a VISIBLE failure rather
  // than a null that renders as a silent success. The `web/` version had a
  // narrower version of this guard (`raw.startsWith("MCP error")`), which
  // this port dropped along with MCP; dropping it outright would have meant
  // an unparseable response showing a green "cite recorded" card. Today no
  // producer emits a non-JSON body — harness/tools.py always returns a JSON
  // object — so this is a latent guard, and a citation silently reading as
  // valid when it isn't is precisely the failure Core Invariant 2 forbids.
  return { ok: false, error: `cite() returned an unreadable response: ${raw}` };
}

export default function CiteView({ tool }: { tool: ToolBlock }) {
  const chunkId = (tool.input.chunk_id as string) || "";
  const spanStart = tool.input.span_start as number | undefined;
  const spanEnd = tool.input.span_end as number | undefined;
  const quote = tool.input.quote as string | undefined;
  const confidence = (tool.input.confidence as string) || "";
  const claimSpan = (tool.input.claim_span as string) || "";

  const ack = parseAck(tool.output);
  const error =
    tool.isError && tool.output
      ? tool.output
      : ack?.ok === false
        ? (ack.error ?? "cite() rejected")
        : undefined;

  const conf = CONFIDENCE_GLYPH[confidence] ?? {
    glyph: "?",
    label: confidence || "unknown",
  };

  // Show the claim only when this cite FAILED — there, the model's text is
  // not successfully underlined inline (the chip is a red ✗), so the analyst
  // needs to see what it intended to cite to make sense of the rejection.
  const showClaim = error !== undefined;

  return (
    <div className="chat-stack">
      <div className="chat-row">
        <Chip tone={confidence === "verbatim" ? "add" : "info"}>
          {conf.glyph} {conf.label}
        </Chip>
        {spanStart != null && spanEnd != null && (
          <span className="chat-muted chat-mono">
            chunk offset [{spanStart}–{spanEnd}]
          </span>
        )}
      </div>

      {/* The quote path is the preferred one (the server derives offsets from
          it), so surface it — it is the exact source text this cite claims. */}
      {quote && !showClaim && (
        <div>
          <div className="chat-label">Quoted from the source</div>
          <blockquote className="chat-cite-quote">{quote}</blockquote>
        </div>
      )}

      {showClaim && claimSpan && (
        <div>
          <div className="chat-label">Intended claim</div>
          <blockquote className="chat-quote">{claimSpan}</blockquote>
        </div>
      )}

      {/* Failed cites carry a cited_text_preview from the validator — what
          the model's span actually pointed at, which is the most useful piece
          of feedback for understanding WHY the cite was rejected. */}
      {error && ack?.cited_text_preview && (
        <div>
          <div className="chat-label">Cited span actually contained</div>
          <div className="chat-block">
            <pre>{ack.cited_text_preview}</pre>
          </div>
        </div>
      )}

      <div className="chat-row chat-muted chat-mono">
        <span>chunk</span>
        <code className="chat-code">{chunkId}</code>
      </div>

      {ack?.ok && ack.citation_id && (
        <div className="chat-muted chat-mono" style={{ fontSize: 10 }}>
          citation_id {ack.citation_id}
        </div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
