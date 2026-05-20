"use client";

// Top-of-thread banner that appears when the retrieval sidecar's
// /health probe failed at session start. The probe result is read
// from the `startConversation` return value (no event subscription) —
// the chat-state slice that owns `conversationId` also owns this
// banner's visibility. Surfacing the failure here — BEFORE the user
// types a question — saves them from getting a mid-answer "retrieval
// service unavailable" error.

interface Props {
  /** Optional underlying reason string from the probe (e.g. "HTTP 500"
   *  or "ECONNREFUSED"). Surfaced as small dim text after the main
   *  message so the user has something to paste into a bug report. */
  reason?: string;
}

const FALLBACK_MESSAGE =
  "Source documents service offline — start the retrieval sidecar " +
  "(uv run uvicorn retrieval.api:app --port 9200).";

export default function SystemHealthBanner({ reason }: Props) {
  // NOTE: spec called for `border-warn/30 bg-warn/10 text-warn-fg`
  // tokens but this theme defines `--color-warning` (no `warn-fg`).
  // Using the existing `warning` token — same visual intent, matches
  // RefusalBanner.tsx's `border-warning/50 bg-warning/10` precedent.
  return (
    <div
      role="alert"
      className="mx-auto max-w-3xl mt-3 mb-2 px-3 py-2 rounded-md border border-warning/30 bg-warning/10 text-warning text-xs"
    >
      <strong className="font-medium">Heads up:</strong> {FALLBACK_MESSAGE}
      {reason ? (
        <span className="ml-2 opacity-70">({reason})</span>
      ) : null}
    </div>
  );
}
