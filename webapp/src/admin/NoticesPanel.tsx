import * as api from "../api";
import { when } from "./format";

// "What went wrong while you weren't looking."
//
// Everything in this feed shares one shape: something degraded, the app kept
// working, and nobody would find out otherwise.
//
// It renders NOTHING when there is nothing wrong — no empty-state card, no
// reassuring "all clear" panel. A section that is present every day teaches
// an admin to scroll past it, which is exactly the habit that makes it
// useless on the day it has something in it.

const KIND_LABELS: Record<string, string> = {
  model_fallback: "AI model changed",
  key_rejected: "Key rejected",
  scraper_failed: "Fiscal note update failed",
  ingest_failed: "A document failed to process",
  admin_claimed: "Admin access claimed",
};

export function NoticesPanel({ notices }: { notices: api.Notice[] }) {
  if (notices.length === 0) return null;
  // Newest first: a glance at what just broke, not a chronicle.
  const newestFirst = [...notices].reverse();
  return (
    <section
      className="card adm-panel adm-panel-alert"
      aria-labelledby="adm-notices-h"
      data-testid="admin-notices"
    >
      <h2 id="adm-notices-h">Needs a look</h2>
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
    </section>
  );
}
