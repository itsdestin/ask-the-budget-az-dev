import * as api from "../api";
import { when } from "./format";

// "What went wrong while you weren't looking."
//
// Everything in this feed shares one shape: something degraded, the app kept
// working, and nobody would find out otherwise. A model was retired and AI
// Mode quietly switched to a different one; the key started coming back
// rejected; a scraper's page layout changed; an ingest job failed.
//
// The empty state says "nothing has gone wrong" rather than "no notices",
// because an empty list is genuinely good news here and should read that way.

const KIND_LABELS: Record<string, string> = {
  model_fallback: "AI model changed",
  key_rejected: "API key rejected",
  scraper_failed: "Fiscal note refresh failed",
  ingest_failed: "Document processing failed",
  admin_claimed: "Admin access claimed",
};

export function NoticesPanel({ notices }: { notices: api.Notice[] }) {
  // Newest first: the feed is a glance at what just broke, not a chronicle.
  const newestFirst = [...notices].reverse();
  return (
    <section className="card adm-panel" aria-labelledby="adm-notices-h" data-testid="admin-notices">
      <h2 id="adm-notices-h">Things that need your attention</h2>
      {newestFirst.length === 0 ? (
        <p className="adm-empty">Nothing has gone wrong that the app noticed.</p>
      ) : (
        <ul className="adm-notices">
          {newestFirst.map((notice, i) => (
            <li key={`${notice.at}-${i}`} data-testid="admin-notice">
              <span className="adm-notice-kind">
                {KIND_LABELS[notice.kind] ?? notice.kind}
              </span>
              <span className="adm-notice-when">{when(notice.at)}</span>
              <p>{notice.message}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
