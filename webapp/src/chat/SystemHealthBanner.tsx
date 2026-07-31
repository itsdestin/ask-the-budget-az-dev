// Top-of-thread banner shown when AI Mode can't actually run.
//
// The probe result arrives inline on `POST /api/conversations` (as
// `health: {ok, reason?}`) and, per tier, from `GET /api/ai/status`. Showing
// the failure HERE — before the analyst types a question — saves them from
// discovering it halfway through composing one.
//
// Copy was REWRITTEN, not ported. The old banner said "Source documents
// service offline — start the retrieval sidecar (uv run uvicorn
// retrieval.api:app --port 9200)" and elsewhere referred to a YouCoded
// session. Neither the sidecar nor YouCoded exists in Plan 4, so that copy
// named a fix that cannot be performed and a component that is not running.
//
// The failure modes now are: no API key configured; no model configured for
// this tier; the model provider call failing; the document store unreachable.
// The first two are admin configuration and the analyst cannot fix them —
// hence "ask your admin" rather than a command to paste. The raw `reason`
// string from the server is still shown verbatim in parentheses, because it
// is what an admin needs and what an analyst can copy into a message.

interface Props {
  /** The server's own reason string (e.g. "no API key configured",
   *  "no model configured — ask the admin", an HTTP status, a store error).
   *  Optional: a failed probe with no reason still renders the banner. */
  reason?: string;
}

/** Reason -> what the analyst should actually do about it.
 *
 *  Matching is substring-based rather than exact because only two of these
 *  strings are pinned by `harness/settings.py::ai_available`; provider and
 *  store failures arrive as whatever the underlying error said. An unmatched
 *  reason falls through to the generic branch, which is honest about not
 *  knowing rather than guessing at a cause — meaning it also declines to make
 *  the side claims the matched branches can make. See the note there. */
function guidanceFor(reason: string | undefined): string {
  const r = (reason ?? "").toLowerCase();
  if (r.includes("api key")) {
    return (
      "This server has no key for the AI service, so questions can't be " +
      "answered yet. Ask your admin to add one. Budget search and fiscal " +
      "notes are unaffected."
    );
  }
  if (r.includes("model")) {
    return (
      "This server has a key but no model assigned to this mode, so " +
      "questions can't be answered yet. Ask your admin to finish setup. " +
      "Budget search and fiscal notes are unaffected."
    );
  }
  if (r.includes("corpus") || r.includes("store") || r.includes("lancedb")) {
    return (
      "The budget documents can't be reached right now, so nothing can be " +
      "searched or cited. This usually means the shared drive is " +
      "unavailable — try again shortly, and tell your admin if it persists."
    );
  }
  // Deliberately says nothing about Budget Search. The two config branches
  // above can promise it still works because a missing key or model cannot
  // affect it. This branch cannot: matching is substring-based against
  // whatever the underlying error said, so a store outage that surfaces as a
  // bare OSError, "connection refused", or HTTP 500 lands HERE rather than in
  // the store branch — and telling that analyst search is fine sends them to
  // a second dead feature. Not knowing the cause means not making claims
  // that depend on it.
  return (
    "The assistant can't be reached right now, so questions can't be " +
    "answered. Try again in a few minutes; if it keeps happening, ask your " +
    "admin."
  );
}

export default function SystemHealthBanner({ reason }: Props) {
  return (
    // is-danger, not is-warn: this is "nothing you type will work", a strictly
    // heavier condition than the max_steps notice's "this one answer is
    // incomplete". They used to render identically.
    <div role="alert" className="chat-notice is-danger chat-notice-banner">
      <strong>AI Mode is offline.</strong> {guidanceFor(reason)}
      {reason ? <span className="chat-notice-reason">({reason})</span> : null}
    </div>
  );
}
