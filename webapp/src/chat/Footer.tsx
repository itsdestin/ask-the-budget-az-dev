// Standing honesty line under the chat surface. Ported from
// web/components/Footer.tsx.
//
// Two edits. The status dot's aria-label used to say "YouCoded connected" /
// "YouCoded disconnected"; there is no YouCoded, so it now names AI Mode —
// which is what the dot has always actually reported.
//
// And the corpus line lost its document count. It said "FY2024-26", then
// briefly "382 docs · FY2025-27" to match STATUS.md — but Plan 3 shipped a
// GUI upload queue, so ANY hardcoded count is now falsified the first time
// an analyst adds a document, and nothing in the app would notice. There is
// no corpus-count endpoint to read instead (only /api/fiscal-notes/status,
// which counts one corpus). A footer whose whole job is to state limits
// honestly must not carry a number that silently rots; the publisher list
// beside it is stable by design. Restore a count only when it can be read
// live — that endpoint is a Plan 5 item alongside the filter-chip facets.
//
// The middle sentence is Core Invariant 5 territory and is deliberately
// unglamorous: no "grounded", no "hallucination-free". Don't soften it.

interface Props {
  /** Whether AI Mode is currently usable — drives the status dot colour. */
  connected: boolean;
}

export default function Footer({ connected }: Props) {
  return (
    <footer className="chat-footer">
      <span>Sources: JLBC · AGAO · AZ Legislature · Governor&apos;s Office</span>
      <span>Answers are cited, not guaranteed. Verify against sources.</span>
      <span className="chat-footer-status">
        <span
          className="chat-footer-dot"
          style={{
            background: connected ? "var(--chat-ok)" : "var(--chat-danger)",
          }}
          aria-label={connected ? "AI Mode available" : "AI Mode unavailable"}
        />
        {connected ? "AI Mode available" : "AI Mode unavailable"}
      </span>
    </footer>
  );
}
