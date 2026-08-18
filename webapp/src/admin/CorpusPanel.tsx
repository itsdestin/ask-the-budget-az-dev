import { useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";
import { Toggle } from "./Toggle";
import { bytes, count, when } from "./format";

// Documents, the processing queue, and the one destructive button in the app.
//
// Restore is double-guarded, and both guards are deliberate:
//
//  1. The admin types the word "restore". A checkbox or a plain Confirm
//     button can be hit by a mis-click, a double-submit, or a stale tab
//     replaying a request; typing a word cannot.
//  2. The confirm text names the snapshot's DATE, because "restore the
//     backup" and "restore the backup from three weeks ago" are different
//     decisions and only one of them is usually intended.
//
// The server adds the third guard the UI can't: it refuses while an ingest
// holds the lock, and it snapshots the current documents before replacing
// them.

export function CorpusPanel({
  corpus,
  snapshots,
  onRestore,
  restoreState,
  onSetIngest,
  ingestMessage,
}: {
  corpus: api.AdminCorpus;
  snapshots: api.Snapshot[];
  onRestore: (name: string) => void;
  restoreState: { pending: boolean; error: string | null; restored: string | null };
  onSetIngest: (enabled: boolean) => void;
  /** The server's own "takes effect after a restart" sentence, or null.
   *  Not re-typed here: the reason it needs a restart lives in the server
   *  (the worker starts from the lifespan hook) and so should the wording. */
  ingestMessage: string | null;
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  const dead = corpus.dead_version_bytes;
  // Only worth mentioning when it is a real share of the folder — below that
  // it is measurement noise, and pointing at it would send an admin chasing
  // nothing. See `_reclaimable_bytes` for why this is an estimate.
  const deadWorthShowing =
    dead !== null && corpus.lancedb_bytes > 0 && dead / corpus.lancedb_bytes > 0.2;
  const busy = corpus.queue.queued + corpus.queue.running;

  return (
    <section className="card adm-panel" aria-labelledby="adm-corpus-h" data-testid="admin-corpus">
      <h2 id="adm-corpus-h">Documents</h2>

      <dl className="adm-stats">
        <div>
          <dt>Documents</dt>
          <dd>{count(corpus.documents)}</dd>
        </div>
        <div>
          <dt>Budget passages</dt>
          <dd>{count(corpus.budget_chunks)}</dd>
        </div>
        <div>
          <dt>Fiscal note passages</dt>
          <dd>{count(corpus.fiscal_note_chunks)}</dd>
        </div>
        <div>
          <dt>Last one added</dt>
          <dd>{when(corpus.last_ingest_at)}</dd>
        </div>
      </dl>

      <p className="adm-sub" data-testid="admin-queue">
        {busy === 0 && corpus.queue.failed === 0
          ? "Nothing is being processed right now."
          : [
              corpus.queue.running ? `${corpus.queue.running} being processed` : null,
              corpus.queue.queued ? `${corpus.queue.queued} waiting` : null,
              corpus.queue.failed ? `${corpus.queue.failed} failed` : null,
            ]
              .filter(Boolean)
              .join(" · ")}
        {busy > 0 ? (
          <span className="adm-hint"> A whole book takes hours — leave the app running.</span>
        ) : null}
      </p>

      {/* The counterweight to `ingest_enabled` defaulting to off. Without
          this, "off by default" just relocates the failure: uploads queue on
          the share and nothing ever drains them, with no error anywhere. The
          server decides WHETHER to warn and supplies the sentence, so the
          rule and its wording can't drift apart. */}
      {corpus.queue_stalled && corpus.queue_stalled_message ? (
        <p className="adm-warn" role="alert" data-testid="admin-queue-stalled">
          {corpus.queue_stalled_message}
        </p>
      ) : null}

      <div className="adm-row">
        <div>
          <h3>Process uploads on this computer</h3>
          <p className="adm-sub">
            {corpus.ingest_enabled_here
              ? "This computer turns uploaded documents into searchable text. It should be one that stays on and isn't needed for other work — processing a whole book can take all night."
              : "This computer doesn't process uploads. One computer in the office needs this turned on, or uploads will wait forever."}
          </p>
        </div>
        <Toggle
          checked={corpus.ingest_enabled_here}
          onChange={onSetIngest}
          label="Process uploads on this computer"
          testId="admin-ingest-toggle"
        />
      </div>
      {ingestMessage ? (
        <p className="adm-ok" role="status" data-testid="admin-ingest-message">
          {ingestMessage}
        </p>
      ) : null}

      {deadWorthShowing ? (
        <p className="adm-warn" data-testid="admin-dead-versions">
          About {bytes(dead)} of this folder is old copies left behind by past
          updates. The app clears these out as it works, so this number should
          fall on its own the next time a document is added.
        </p>
      ) : null}

      {restoreState.restored ? (
        <p className="adm-ok" role="status" data-testid="admin-restore-done">
          Restored.{" "}
          <strong>Close this window and open JLBC Search again to finish.</strong>{" "}
          It is still using the old documents until it restarts.
        </p>
      ) : null}
      {restoreState.error ? (
        <p className="adm-warn" role="alert" data-testid="admin-restore-error">
          {restoreState.error}
        </p>
      ) : null}

      <CollapsibleCard
        title="Backups"
        hint={
          snapshots.length === 0
            ? "none yet"
            : `${snapshots.length} kept · newest ${when(snapshots[0].created_at)}`
        }
        testId="admin-backups"
      >
        <p className="adm-hint">
          The app saves a copy before it changes anything, and keeps the five
          most recent. Restoring puts the documents back to how they were then
          — anything added since is lost.
        </p>

        {snapshots.length === 0 ? (
          <p className="adm-empty">No backups yet.</p>
        ) : (
          <ul className="adm-rows" data-testid="admin-snapshots">
            {snapshots.map((snap) => (
              <li key={snap.name}>
                <span>
                  {when(snap.created_at)} · {bytes(snap.bytes)}
                </span>
                {confirming === snap.name ? (
                  <span className="adm-confirm" data-testid="admin-restore-confirm">
                    <label htmlFor="adm-restore-type">
                      This replaces all documents with the copy from{" "}
                      {when(snap.created_at)}. Type <strong>restore</strong> to
                      confirm.
                    </label>
                    <input
                      id="adm-restore-type"
                      type="text"
                      value={typed}
                      autoComplete="off"
                      onChange={(e) => setTyped(e.target.value)}
                    />
                    <button
                      type="button"
                      className="adm-btn adm-btn-danger"
                      disabled={typed !== "restore" || restoreState.pending}
                      onClick={() => {
                        onRestore(snap.name);
                        setConfirming(null);
                        setTyped("");
                      }}
                    >
                      Restore this backup
                    </button>
                    <button
                      type="button"
                      className="adm-link"
                      onClick={() => {
                        setConfirming(null);
                        setTyped("");
                      }}
                    >
                      Cancel
                    </button>
                  </span>
                ) : (
                  <button
                    type="button"
                    className="adm-btn adm-btn-quiet"
                    onClick={() => {
                      setConfirming(snap.name);
                      setTyped("");
                    }}
                  >
                    Restore…
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </CollapsibleCard>
    </section>
  );
}
