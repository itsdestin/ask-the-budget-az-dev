import { useState } from "react";
import * as api from "../api";
import { bytes, count, when } from "./format";

// Corpus health and the one destructive button in this app.
//
// Restore is double-guarded, and both guards are deliberate:
//
//  1. The admin types the word "restore". A checkbox or a plain "Confirm"
//     button can be hit by a mis-click, a double-submit or a stale tab
//     replaying a request; typing a word cannot.
//  2. The confirm text names the snapshot's DATE, because "restore the
//     backup" and "restore the backup from three weeks ago" are different
//     decisions and only one of them is usually intended.
//
// The server adds the third guard the UI can't: it refuses while an ingest
// holds the lock, and it snapshots the current corpus before replacing it.

export function CorpusPanel({
  corpus,
  snapshots,
  onRestore,
  restoreState,
}: {
  corpus: api.AdminCorpus;
  snapshots: api.Snapshot[];
  onRestore: (name: string) => void;
  restoreState: { pending: boolean; error: string | null; restored: string | null };
}) {
  const [confirming, setConfirming] = useState<string | null>(null);
  const [typed, setTyped] = useState("");

  const dead = corpus.dead_version_bytes;
  // Only worth mentioning when it is a real share of the folder — otherwise
  // it is measurement noise and pointing at it would send an admin chasing
  // nothing. See `_reclaimable_bytes` for why this is an estimate.
  const deadWorthShowing =
    dead !== null && corpus.lancedb_bytes > 0 && dead / corpus.lancedb_bytes > 0.2;

  return (
    <section className="card adm-panel" aria-labelledby="adm-corpus-h" data-testid="admin-corpus">
      <h2 id="adm-corpus-h">Documents and search index</h2>

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
          <dt>Search index size</dt>
          <dd>{bytes(corpus.lancedb_bytes)}</dd>
        </div>
        <div>
          <dt>Last document added</dt>
          <dd>{when(corpus.last_ingest_at)}</dd>
        </div>
      </dl>

      {deadWorthShowing ? (
        <p className="adm-warn" data-testid="admin-dead-versions">
          About {bytes(dead)} of that is old copies left behind by past updates.
          They are safe to remove and doing so makes the folder much faster to
          copy or back up — ask whoever maintains the app to run a cleanup.
        </p>
      ) : null}

      <h3>Processing queue</h3>
      <p data-testid="admin-queue">
        {corpus.queue.queued} waiting · {corpus.queue.running} in progress ·{" "}
        {corpus.queue.failed} failed
      </p>
      <p className="adm-hint">
        A whole book takes hours — MinerU reads roughly one to three minutes per
        page. Leave the app running.
      </p>

      <h3>Snapshots</h3>
      <p className="adm-hint">
        The app takes one of these before it writes to the index, and keeps the
        five most recent. Restoring puts the index back to how it was at that
        moment — anything added since is lost.
      </p>

      {restoreState.restored ? (
        <p className="adm-ok" role="status" data-testid="admin-restore-done">
          Restored {restoreState.restored}.{" "}
          <strong>Close this window and reopen JLBC Insight to finish.</strong>{" "}
          The app is still using the old index until it restarts.
        </p>
      ) : null}
      {restoreState.error ? (
        <p className="adm-warn" role="alert" data-testid="admin-restore-error">
          {restoreState.error}
        </p>
      ) : null}

      {snapshots.length === 0 ? (
        <p className="adm-empty">No snapshots yet.</p>
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
                    This replaces the whole search index with the copy from{" "}
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
                    Restore this snapshot
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
    </section>
  );
}
