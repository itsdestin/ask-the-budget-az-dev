// Standing honesty line under the chat surface. Ported from
// web/components/Footer.tsx (deleted in Plan 5 Track 4; see git history).
//
// Two edits at port time. The status dot's aria-label used to say "YouCoded
// connected" / "YouCoded disconnected"; there is no YouCoded, so it names AI
// Mode — which is what the dot has always actually reported.
//
// And the corpus line lost its document count. It said "FY2024-26", then
// briefly "382 docs · FY2025-27" to match STATUS.md — but Plan 3 shipped a
// GUI upload queue, so any hardcoded count is falsified the first time an
// analyst adds a document, and nothing in the app would notice.
//
// PLAN 5 TASK 19 RESTORES THE COUNT, read live from /api/corpus/counts. The
// rule that removed it still holds, and is now enforced by construction: the
// number renders ONLY when the server has answered. While the fetch is in
// flight, and forever if it fails, the footer says nothing about corpus size
// rather than guessing — a footer whose whole job is stating limits honestly
// must not carry a number it cannot verify.
//
// The middle sentence is Core Invariant 5 territory and is deliberately
// unglamorous: no "grounded", no "hallucination-free". Don't soften it.

import { useEffect, useState } from "react";

import { corpusCounts } from "../api.js";

interface Props {
  /** Whether AI Mode is currently usable — drives the status dot colour. */
  connected: boolean;
  /** Injected by tests to render a known count without a fetch. `undefined`
   *  means "not known yet" and renders no number at all. */
  documentCount?: number;
}

/** en-US grouping, so 3,527 reads as a count rather than a version string. */
function formatCount(n: number): string {
  return n.toLocaleString("en-US");
}

export default function Footer({ connected, documentCount }: Props) {
  const [fetched, setFetched] = useState<number | undefined>(undefined);

  useEffect(() => {
    if (documentCount !== undefined) return; // caller supplied it
    let live = true;
    corpusCounts()
      .then((c) => {
        if (live) setFetched(c.documents);
      })
      // Swallowed on purpose. A footer must never raise an error banner or
      // take the page down; failing to learn the count leaves this
      // undefined, which renders no number — the honest degradation.
      .catch(() => {});
    return () => {
      live = false;
    };
  }, [documentCount]);

  const count = documentCount ?? fetched;

  return (
    <footer className="chat-footer">
      <span>
        Sources: JLBC · AGAO · AZ Legislature · Governor&apos;s Office
        {count !== undefined && ` · ${formatCount(count)} documents`}
      </span>
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
