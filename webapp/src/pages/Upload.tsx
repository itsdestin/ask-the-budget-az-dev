import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";

// The upload surface. Two jobs: get a document into the queue with correct
// metadata, and be honest about what happens next.
//
// Invariant 8 lives here. The corpus is public-record-only because AI Mode
// sends retrieved text to an external inference provider, and the app cannot
// classify confidentiality. So the rule is communicated, not detected: a
// permanently visible notice plus a required checkbox — a deliberate moment,
// not buried fine print. The server enforces the same gate, because a rule
// enforced only in the UI is not enforced.
//
// The other honesty requirement is timing. MinerU runs 1-3 minutes per page on
// the office i5s, so a Baseline book is an overnight job. The copy says so.
// Promising "a few minutes" would make every large upload look broken.

const CORPORA = [
  { value: "budget", label: "Budget documents" },
  { value: "fiscal_notes", label: "Fiscal notes" },
];

const PUBLISHERS = [
  { value: "jlbc", label: "JLBC" },
  { value: "governor", label: "Governor" },
  { value: "legislature", label: "Legislature" },
  { value: "agao", label: "Auditor General (AGAO)" },
];

// Mirrors app/routes/upload.py's ACCEPTED_DOC_TYPES (the extractor registry).
// Labels are analyst language; values are the corpus's doc_type strings.
const DOC_TYPES = [
  { value: "baseline-per-agency", label: "Baseline — agency page" },
  { value: "approps-per-agency", label: "Appropriations Report — agency page" },
  { value: "baseline-book", label: "Baseline — whole book" },
  { value: "approps-report", label: "Appropriations Report — whole book" },
  { value: "s-pdf", label: "Baseline — summary section" },
  { value: "bh-pdf", label: "Baseline — budget history section" },
  { value: "bd-pdf", label: "Baseline — budget detail section" },
  { value: "topic-pdf", label: "Cross-cutting topic report" },
  { value: "detailed-list-pdf", label: "Detailed list of fund changes" },
  { value: "governors-budget", label: "Executive Budget" },
  { value: "budget-bill", label: "Budget bill" },
  { value: "afr", label: "Annual Financial Report" },
  { value: "fiscal-note", label: "Fiscal note" },
];

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

interface Meta {
  corpus: string;
  publisher: string;
  doc_type: string;
  fiscal_year: number;
  title: string;
}

export function Upload() {
  const [file, setFile] = useState<File | null>(null);
  const [meta, setMeta] = useState<Meta | null>(null);
  const [isPublicRecord, setIsPublicRecord] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [status, setStatus] = useState<string>("");
  const [error, setError] = useState<string>("");
  const [duplicate, setDuplicate] = useState<api.DuplicateDocument | null>(null);
  const [jobs, setJobs] = useState<api.Job[]>([]);
  const [queueError, setQueueError] = useState<string>("");
  const inputRef = useRef<HTMLInputElement>(null);

  const refreshJobs = useCallback(async () => {
    try {
      const body = await api.jobs();
      setJobs(body.jobs);
      setQueueError("");
    } catch (e) {
      // Stale-while-revalidate: keep showing the last good queue rather than
      // blanking it, because a momentary share hiccup is not "no jobs".
      setQueueError(e instanceof Error ? e.message : String(e));
    }
  }, []);

  useEffect(() => {
    void refreshJobs();
    const id = setInterval(() => void refreshJobs(), POLL_MS);
    return () => clearInterval(id);
  }, [refreshJobs]);

  function chooseFile(next: File | null) {
    setFile(next);
    setDuplicate(null);
    setError("");
    setMeta(next ? guessMeta(next.name) : null);
  }

  async function submit(reprocess = false) {
    if (!file || !meta) return;
    setSubmitting(true);
    setError("");
    setDuplicate(null);
    try {
      await api.uploadDocument(file, { ...meta, reprocess });
      setStatus(`${file.name} added to the queue.`);
      chooseFile(null);
      if (inputRef.current) inputRef.current.value = "";
      setIsPublicRecord(false);
      await refreshJobs();
    } catch (e) {
      if (e instanceof api.DuplicateDocumentError) {
        setDuplicate(e.info);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setSubmitting(false);
    }
  }

  async function act(kind: "retry" | "cancel", jobId: string) {
    try {
      if (kind === "retry") await api.retryJob(jobId);
      else await api.cancelJob(jobId);
      await refreshJobs();
    } catch (e) {
      setQueueError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <main className="page-upload" data-testid="upload">
      <div className="wrap">
        <h1 className="up-title">Add a document</h1>

        <section className="card up-notice" aria-labelledby="up-notice-h">
          <h2 id="up-notice-h">Public record documents only</h2>
          <p>
            This corpus is only for documents that are already public record:
            baseline books, appropriations reports, fiscal notes, bills, executive
            budget requests, agency budget requests, and Annual Financial Reports.
          </p>
          <p>
            Do not upload confidential state data. When AI Mode answers a question
            it sends the text of retrieved passages to an outside AI provider, and
            anything placed here is readable by everyone with access to the shared
            drive. Search on its own never sends document text anywhere — but the
            document is still on the shared drive once uploaded.
          </p>
        </section>

        <section className="card up-form">
          <div
            className="up-drop"
            data-testid="dropzone"
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              chooseFile(e.dataTransfer.files?.[0] ?? null);
            }}
          >
            <label className="up-choose" htmlFor="up-file">
              Choose a PDF or Word document
            </label>
            <input
              id="up-file"
              ref={inputRef}
              type="file"
              accept=".pdf,.docx"
              onChange={(e) => chooseFile(e.target.files?.[0] ?? null)}
            />
            <p className="up-hint">…or drag one onto this box.</p>
          </div>

          {file && meta && (
            <div className="up-meta">
              <p className="up-filename">{file.name}</p>

              <label>
                Collection
                <select
                  aria-label="Collection"
                  value={meta.corpus}
                  onChange={(e) => setMeta({ ...meta, corpus: e.target.value })}
                >
                  {CORPORA.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </label>

              <label>
                Publisher
                <select
                  aria-label="Publisher"
                  value={meta.publisher}
                  onChange={(e) => setMeta({ ...meta, publisher: e.target.value })}
                >
                  {PUBLISHERS.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </label>

              <label>
                Document type
                <select
                  aria-label="Document type"
                  value={meta.doc_type}
                  onChange={(e) => setMeta({ ...meta, doc_type: e.target.value })}
                >
                  {DOC_TYPES.map((o) => (
                    <option key={o.value} value={o.value}>{o.label}</option>
                  ))}
                </select>
              </label>

              <label>
                Fiscal year
                <input
                  aria-label="Fiscal year"
                  type="number"
                  value={meta.fiscal_year}
                  onChange={(e) =>
                    setMeta({ ...meta, fiscal_year: Number(e.target.value) })
                  }
                />
              </label>

              <label>
                Title (optional)
                <input
                  aria-label="Title"
                  type="text"
                  placeholder="Leave blank to name it automatically"
                  value={meta.title}
                  onChange={(e) => setMeta({ ...meta, title: e.target.value })}
                />
              </label>

              <label className="up-check">
                <input
                  type="checkbox"
                  checked={isPublicRecord}
                  onChange={(e) => setIsPublicRecord(e.target.checked)}
                />
                This document is public record.
              </label>

              <button
                type="button"
                className="allbtn"
                disabled={!isPublicRecord || submitting}
                onClick={() => void submit(false)}
              >
                {submitting ? "Adding…" : "Add to the queue"}
              </button>

              <p className="up-expect">
                Small documents are searchable within the hour. Large books (100+
                pages) process overnight — leave the app running; progress survives
                restarts.
              </p>
            </div>
          )}

          {duplicate && (
            <div className="up-dupe" data-testid="duplicate">
              <p>
                This document is already in the corpus
                {duplicate.added_at ? ` (added ${formatDate(duplicate.added_at)}` : ""}
                {duplicate.added_by ? ` by ${duplicate.added_by})` : duplicate.added_at ? ")" : ""}
                .
              </p>
              <button
                type="button"
                className="allbtn"
                onClick={() => void submit(true)}
              >
                Process it again anyway
              </button>
            </div>
          )}

          <p className="up-status" role="status">
            {error ? <span className="err">{error}</span> : status}
          </p>
        </section>

        <AddBookPanel onQueued={() => void refreshJobs()} />

        <section className="card up-queue" aria-labelledby="up-queue-h">
          <h2 id="up-queue-h">Queue</h2>
          {queueError && (
            <p className="up-note">
              <span className="err">Couldn’t refresh the queue: {queueError}</span>
            </p>
          )}
          {jobs.length === 0 ? (
            <p className="up-note">Nothing is processing right now.</p>
          ) : (
            <ul className="up-jobs">
              {jobs.map((job) => (
                <li key={job.job_id} className="up-job" data-testid="job">
                  <div className="up-job-head">
                    <span className="up-job-title">{job.title}</span>
                    <span className="up-job-state">{STAGE_LABELS[job.state]}</span>
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
        </section>
      </div>
    </main>
  );
}

// --- filename heuristics ----------------------------------------------------

/** Best-effort metadata from a filename. Every field stays editable — this
 *  saves typing, it does not decide anything.
 *
 *  The patterns are the JLBC publishing conventions the corpus already uses:
 *  `27baseline-axs.pdf` (FY 2027 Baseline agency page), `25ar-axs.pdf`
 *  (FY 2025 Appropriations Report agency page), and an explicit `FY2026`
 *  anywhere in the name. */
export function guessMeta(filename: string): Meta {
  const name = filename.toLowerCase();
  let fiscal_year = 0;
  let doc_type = "baseline-per-agency";
  let publisher = "jlbc";

  const explicit = name.match(/fy\s*-?\s*(\d{4})/);
  const twoDigit = name.match(/(?:^|[^0-9])(\d{2})(baseline|ar)\b/);
  if (explicit) {
    fiscal_year = Number(explicit[1]);
  } else if (twoDigit) {
    fiscal_year = 2000 + Number(twoDigit[1]);
  } else {
    // No signal — default to the fiscal year we're most likely adding to.
    // Arizona's FY starts in July, so from July onward the current work is
    // next calendar year's book.
    const now = new Date();
    fiscal_year = now.getMonth() >= 6 ? now.getFullYear() + 1 : now.getFullYear();
  }

  if (twoDigit && twoDigit[2] === "ar") doc_type = "approps-per-agency";
  if (name.includes("afr")) {
    doc_type = "afr";
    publisher = "agao";
  } else if (name.includes("executive") || name.includes("govbudget")) {
    doc_type = "governors-budget";
    publisher = "governor";
  } else if (name.endsWith(".docx")) {
    doc_type = "budget-bill";
    publisher = "legislature";
  }

  return { corpus: "budget", publisher, doc_type, fiscal_year, title: "" };
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString();
}

// ---------------------------------------------------------------------------
// Add a JLBC book
// ---------------------------------------------------------------------------

/** Bulk-add one published JLBC edition — this year's Baseline, or a historical
 *  backfill — without hunting down 130 PDF links by hand.
 *
 *  No Invariant 8 checkbox here: everything this panel can reach is a
 *  JLBC-published report, which is public record by definition. Asking again
 *  would train people to click past the checkbox that does matter.
 *
 *  Discover and Add are separate steps on purpose. A book is an overnight
 *  commitment on office hardware, so the honest sequence is: see exactly what
 *  it contains (and what's unreachable) first, then decide. */
function AddBookPanel({ onQueued }: { onQueued: () => void }) {
  const [editions, setEditions] = useState<api.BookEdition[] | null>(null);
  const [key, setKey] = useState("");
  const [plan, setPlan] = useState<api.BookPlan | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    api
      .bookCatalog()
      .then((body) => {
        const ingestable = body.editions.filter((e) => e.ingestable);
        setEditions(ingestable);
        setKey((current) => current || ingestable[0]?.key || "");
      })
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  const edition = editions?.find((e) => e.key === key) ?? null;

  async function act(kind: "discover" | "ingest") {
    if (!edition) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      if (kind === "discover") {
        setPlan(await api.discoverBook(edition.family, edition.fiscal_year));
      } else {
        const r = await api.ingestBook(edition.family, edition.fiscal_year);
        setMessage(
          `Queued ${r.queued} documents` +
            (r.skipped_existing ? `; ${r.skipped_existing} already in the corpus` : "") +
            (r.unreachable.length ? `; ${r.unreachable.length} unreachable` : "") +
            ".",
        );
        setPlan(null);
        onQueued();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="card up-book" aria-labelledby="up-book-h" data-testid="add-book">
      <h2 id="up-book-h">Add a JLBC book</h2>
      <p>
        JLBC-published reports are public record, so no confirmation is needed —
        pick an edition and the whole book is added at once.
      </p>

      {error && <p className="up-note"><span className="err">{error}</span></p>}

      <div className="up-book-row">
        <label>
          Edition
          <select
            aria-label="Edition"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setPlan(null);
              setMessage("");
            }}
          >
            {(editions ?? []).map((e) => (
              <option key={e.key} value={e.key}>
                {`FY ${e.fiscal_year} ${e.family === "baseline" ? "Baseline" : "Appropriations Report"}`}
                {` — ${e.document_count} documents`}
              </option>
            ))}
          </select>
        </label>
        <button type="button" className="fchip" disabled={!edition || busy}
                onClick={() => void act("discover")}>
          {busy ? "Working…" : "Discover"}
        </button>
        <button type="button" className="allbtn" disabled={!edition || busy}
                onClick={() => void act("ingest")}>
          Add all
        </button>
      </div>

      {edition?.rolling && (
        <p className="up-note">
          This edition is published in a folder JLBC reuses each year. Its
          contents are checked against FY {edition.fiscal_year} before anything
          is queued.
        </p>
      )}

      {plan && (
        <div className="up-book-plan" data-testid="book-plan" role="status">
          <p>
            {`Found ${plan.count} documents for FY ${edition?.fiscal_year} `}
            {edition?.family === "baseline" ? "Baseline" : "Appropriations Report"}
            {plan.unreachable.length
              ? ` (${plan.unreachable.length} unreachable — listed below)`
              : ""}
            .
          </p>
          {plan.notes.map((note) => (
            <p className="up-note" key={note}>{note}</p>
          ))}
          {plan.unreachable.length > 0 && (
            <ul className="up-book-bad">
              {plan.unreachable.map((url) => <li key={url}>{url}</li>)}
            </ul>
          )}
        </div>
      )}

      <p className="up-status" role="status">{message}</p>

      <p className="up-expect">
        A full book takes overnight on office computers. Historical backfills are
        best run one book at a time.
      </p>
    </section>
  );
}
