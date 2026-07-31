// Standing honesty line under the chat surface. Ported from
// web/components/Footer.tsx.
//
// Two edits. The status dot's aria-label used to say "YouCoded connected" /
// "YouCoded disconnected"; there is no YouCoded, so it now names AI Mode —
// which is what the dot has always actually reported. And the corpus line
// said "FY2024–26", which no longer matches the corpus (STATUS.md: FY2025,
// FY2026 and FY2027 across all four publishers). A footer whose job is to
// state limits honestly cannot carry a stale factual claim.
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
        382 docs · FY2025–27
      </span>
    </footer>
  );
}
