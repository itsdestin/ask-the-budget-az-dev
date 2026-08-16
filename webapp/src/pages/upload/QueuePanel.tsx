import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../../api";

// The ingest queue (spec T13: "the queue shows work, not history").
//
// Lifted out of Upload.tsx unchanged in look, changed in what it lists.
// Before this, `GET /api/jobs` returned every job that had ever run --
// measured on the live data dir at 7,118 rows / 3.13 MB on EVERY poll, of
// which 14 needed anybody's attention. The server now returns outstanding
// work plus every failure regardless of age, and a count of what finished.
//
// There is deliberately NO age filter in this file. The server decides what
// the queue shows, and it decides it by which folder a job file is in; a
// second filter here would be a second place for that rule to be got wrong.
//
// It lives in its own file because a peer session edits Upload.tsx too, and
// two small files conflict far less than one file two sessions both rewrite.

// Moved here VERBATIM from Upload.tsx along with the queue itself. Retyping
// them is how "Searchable" briefly became "Done" during this extraction, and
// the existing suite caught it -- these strings are the ones an analyst has
// learned to read, so they are carried across, not rewritten.
const RUNNING_STATES: api.JobState[] = [
  "queued",
  "extracting",
  "chunking",
  "embedding",
  "writing",
];

const STAGE_LABELS: Record<api.JobState, string> = {
  queued: "Waiting",
  extracting: "Reading the document",
  chunking: "Splitting into passages",
  embedding: "Building the search index",
  writing: "Saving to the corpus",
  live: "Searchable",
  failed: "Failed",
  cancelled: "Cancelled",
};

const POLL_MS = 3000;

export function QueuePanel({ reloadToken }: { reloadToken?: number }) {
  const [jobs, setJobs] = useState<api.Job[]>([]);
  const [finishedCount, setFinishedCount] = useState(0);
  const [showing, setShowing] = useState<"active" | "all">("active");
  // Set by the server when work is queued and no computer is set to process
  // it. This is the counterweight to the 2026-08-16 ingest-switch fix: the
  // upload and books routes no longer start the queue on a machine that
  // opted out, which is correct -- but without this an analyst would queue a
  // document and watch it sit at "Waiting" for ever with nothing explaining
  // why, trading a CPU problem for a trust problem.
  const [stalled, setStalled] = useState<string | null>(null);
  const [queueError, setQueueError] = useState("");

  // Job ids this browser has seen in a non-terminal state, i.e. documents the
  // person at this screen actually watched. See `visibleJobs` below for why.
  const watched = useRef<Set<string>>(new Set());
  const [justFinished, setJustFinished] = useState<api.Job[]>([]);

  const refresh = useCallback(
    async (mode: "active" | "all" = showing) => {
      try {
        const body = await api.jobs(mode === "all");
        const incoming = body.jobs;
        setStalled(body.stalled_message ?? null);

        // Remember anything still in flight, so we can keep its row when it
        // vanishes from the server's list a moment later.
        for (const job of incoming) {
          if (RUNNING_STATES.includes(job.state)) watched.current.add(job.job_id);
        }
        // A watched job that is no longer listed has finished. Spec T13
        // dropped the server-side 24-hour window because a finished document
        // is visible in search -- but a row disappearing at the exact instant
        // it succeeds is abrupt for the one person who was watching it, and
        // that moment is the only thing the window was really buying. The
        // BROWSER knows what it was watching, so this is the right side of
        // the wire for it. Session-scoped on purpose: a reload is a fresh
        // question, and these rows should not accumulate for ever.
        const listed = new Set(incoming.map((j) => j.job_id));
        const stillWatched = [...watched.current].filter((id) => !listed.has(id));
        if (stillWatched.length) {
          const gone = await api
            .jobs(true)
            .then((all) => all.jobs.filter((j) => stillWatched.includes(j.job_id)))
            .catch(() => [] as api.Job[]);
          setJustFinished(gone);
        } else {
          setJustFinished([]);
        }

        setJobs(incoming);
        setFinishedCount(body.finished_count);
        setShowing(body.showing);
        setQueueError("");
      } catch (e) {
        // Stale-while-revalidate: keep showing the last good queue rather than
        // blanking it, because a momentary share hiccup is not "no jobs".
        setQueueError(e instanceof Error ? e.message : String(e));
      }
    },
    [showing],
  );

  useEffect(() => {
    void refresh();
    const id = setInterval(() => void refresh(), POLL_MS);
    return () => clearInterval(id);
    // `refresh` closes over `showing`, and re-subscribing when the analyst
    // switches to "view all" is exactly what we want.
  }, [refresh, reloadToken]);

  async function act(kind: "retry" | "cancel", jobId: string) {
    try {
      if (kind === "retry") await api.retryJob(jobId);
      else await api.cancelJob(jobId);
      await refresh();
    } catch (e) {
      setQueueError(e instanceof Error ? e.message : String(e));
    }
  }

  const visibleJobs =
    showing === "all" ? jobs : [...jobs, ...justFinished.filter((j) => j.state === "live")];

  return (
    <section className="card up-queue" aria-labelledby="up-queue-h">
      <h2 id="up-queue-h">Queue</h2>
      {queueError && (
        <p className="up-note">
          <span className="err">Couldn’t refresh the queue: {queueError}</span>
        </p>
      )}

      {/* Moved down from the top of the page (2026-08-15). It used to sit
          above the document-type list as a 26-word paragraph, where it was
          text between an analyst and the thing they came to do — and it
          describes THIS panel ("the queue below shows exactly where each
          document stands"), so it belongs beside it. Shortened on the way,
          but neither honest number is softened: an hour is an hour and
          overnight is overnight. */}
      <p className="up-note">
        Most documents are searchable within the hour; a full book takes
        overnight. Progress survives restarts.
      </p>

      {/* Above the rows, not below: it explains why the rows below are not
          moving, and a reader who has scrolled past them has already formed
          the wrong conclusion. Rendered VERBATIM from the server -- see
          api.ts's JobsResponse. */}
      {stalled && (
        <p className="up-note up-stalled" role="status" data-testid="queue-stalled">
          <span className="err">{stalled}</span>
        </p>
      )}

      {visibleJobs.length === 0 ? (
        <p className="up-note">Nothing is processing right now.</p>
      ) : (
        <ul className="up-jobs">
          {visibleJobs.map((job) => (
            <li key={job.job_id} className="up-job" data-testid="job">
              <div className="up-job-head">
                <span className="up-job-title">{job.title}</span>
                <span className="up-job-state">{STAGE_LABELS[job.state] ?? job.state}</span>
              </div>
              {RUNNING_STATES.includes(job.state) && (
                <div
                  className="up-bar"
                  role="progressbar"
                  aria-label={`${job.title} progress`}
                  aria-valuenow={job.pct}
                  aria-valuemin={0}
                  aria-valuemax={100}
                >
                  <span style={{ width: `${job.pct}%` }} />
                </div>
              )}
              <p className="up-job-detail">
                {job.stage_detail}
                {job.machine ? ` · ${job.machine}` : ""}
              </p>
              {job.error && <p className="up-job-error">{job.error}</p>}
              <div className="up-job-actions">
                {job.state === "failed" && (
                  <button
                    type="button"
                    className="fchip"
                    onClick={() => void act("retry", job.job_id)}
                  >
                    Retry
                  </button>
                )}
                {RUNNING_STATES.includes(job.state) && (
                  <button
                    type="button"
                    className="fchip"
                    onClick={() => void act("cancel", job.job_id)}
                  >
                    Cancel
                  </button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {/* "Where did my document go?" must have an answer better than "trust
          me" (spec T13). An empty queue and an empty CORPUS would otherwise
          look identical. The number comes off the wire -- never counted here,
          because the whole point is that the browser no longer holds 7,104
          finished rows to count. */}
      {finishedCount > 0 && (
        <p className="up-note up-queue-finished">
          {showing === "all" ? (
            <>
              Showing everything, including {finishedCount.toLocaleString()} finished{" "}
              {finishedCount === 1 ? "document" : "documents"}.{" "}
              <button type="button" className="linkish" onClick={() => void refresh("active")}>
                Show just what’s outstanding
              </button>
            </>
          ) : (
            <>
              {finishedCount.toLocaleString()} {finishedCount === 1 ? "document has" : "documents have"}{" "}
              finished and {finishedCount === 1 ? "is" : "are"} searchable.{" "}
              <button type="button" className="linkish" onClick={() => void refresh("all")}>
                View all
              </button>
            </>
          )}
        </p>
      )}
    </section>
  );
}
