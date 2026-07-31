// Per-tool body view for `create_document` — NEW in Plan 4, so this is
// written rather than ported.
//
// WHY it exists at all: the shipped system prompt tells the model that
// create_document "returns a download link the analyst can click." The tool
// itself cannot return a link — it returns {ok, download_token, filename},
// and `GET /api/documents/{token}` is what serves the bytes. Something has to
// join those two facts into an <a href>, and this is the only surface that
// sees both. Without it the promise in the prompt is false and the analyst
// gets a hex string in a JSON dump.
//
// It belongs in the tool view rather than in the chat surface because the
// token arrives on a tool RESULT, and tool results already render here in
// arrival order. Putting it in the bubble would mean re-deriving which tool
// call the file came from.

import type { AssistantBlock } from "../chat-types.js";
import MarkdownContent from "../MarkdownContent.js";
import { Chip, CollapsibleBlock, ErrorBlock } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface CreateDocumentAck {
  ok: boolean;
  download_token?: string;
  filename?: string;
  error?: string;
}

function parseAck(raw: string | undefined): CreateDocumentAck | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (typeof parsed === "object" && parsed !== null && "ok" in parsed) {
      return parsed as CreateDocumentAck;
    }
    return null;
  } catch {
    return null;
  }
}

/** Same-origin path built from the token. `encodeURIComponent` is not
 *  decoration: the token is server-generated randomness today, but a URL
 *  assembled from a value that reached us over the wire gets encoded on
 *  principle, not on inspection. */
export function downloadUrl(token: string): string {
  return `/api/documents/${encodeURIComponent(token)}`;
}

const PREVIEW_LINES = 12;

export default function CreateDocumentView({ tool }: { tool: ToolBlock }) {
  const title = (tool.input.title as string) || "";
  const body = (tool.input.body_markdown as string) || "";
  const format = (tool.input.format as string) || "docx";

  const ack = parseAck(tool.output);
  const error =
    tool.isError && tool.output
      ? tool.output
      : ack?.ok === false
        ? (ack.error ?? "create_document() failed")
        : undefined;

  const token = ack?.ok ? ack.download_token : undefined;
  const filename = ack?.filename ?? "";

  return (
    <div className="chat-stack">
      <div className="chat-row">
        <Chip tone="info">{format}</Chip>
        {title && <span className="chat-chunk-title">{title}</span>}
      </div>

      {token ? (
        <a className="chat-download" href={downloadUrl(token)} download={filename || undefined}>
          Download {filename || title || "document"}
        </a>
      ) : (
        !error && (
          <div className="chat-note">
            Waiting for the file to be written…
          </div>
        )
      )}

      {/* The analyst should be able to see what they are about to download
          without downloading it. Rendered as markdown, not raw source, so a
          table in the memo reads like a table. */}
      {body && (
        <details>
          <summary className="chat-more">Preview document body</summary>
          <div className="chat-md" style={{ marginTop: 8 }}>
            <MarkdownContent content={body} />
          </div>
        </details>
      )}

      {/* Raw source, collapsed — useful when the rendered preview and the
          downloaded file disagree about something. */}
      {body && (
        <CollapsibleBlock maxLines={PREVIEW_LINES}>{body}</CollapsibleBlock>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
