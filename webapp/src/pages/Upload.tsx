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
// The other honesty requirement is timing. MinerU can take a while per page
// on the office i5s, so a large document can run for hours. The copy says so.
//
// WHY one card with a type PICKER, not six full cards (this rework,
// superseding Task 6's "six guided rows" — see that section's history in
// STATUS.md): six independent cards with their own file input, fiscal year,
// checkbox and Submit button read as six different features, and the product
// owner's reaction to seeing them was blunt — "why are there 6 entirely
// different upload cards." The types themselves are still exactly Task 6's
// insight (an analyst doesn't know a raw doc_type slug, so name a real
// document and let the row determine its own doc_type/publisher) — only the
// SHAPE changed: the six are now a selectable list feeding one form, so
// there is one file input, one fiscal year field, one checkbox and one
// Submit button on the page at a time, no matter which type is picked. The
// rows still come from GET /api/document-types, a straight projection of
// data/document-types.yaml, so this file holds no copy of the type list at
// all — that list drifting from the server's is exactly the bug this page
// used to ship (twice, now, in two different shapes).

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

export function Upload() {
  const [rows, setRows] = useState<api.DocTypeCard[] | null>(null);
  const [rowsError, setRowsError] = useState("");
  const [jobs, setJobs] = useState<api.Job[]>([]);
  const [queueError, setQueueError] = useState<string>("");
  // Which of the registry's types the analyst has picked, if any. Lives on
  // the page (not inside a child) because it decides which single form to
  // render below the list — there is exactly one form on screen, so exactly
  // one component needs to know which type it is for.
  const [selectedKey, setSelectedKey] = useState<string | null>(null);

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

  useEffect(() => {
    api
      .documentTypes()
      .then(setRows)
      .catch((e) => {
        // An empty page with no explanation reads as "nothing to upload
        // here", not "the registry couldn't be reached" — the two look
        // identical unless this says which one happened.
        setRows([]);
        setRowsError(e instanceof Error ? e.message : String(e));
      });
  }, []);

  const selected = (rows ?? []).find((r) => r.key === selectedKey) ?? null;

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

        <p className="up-note up-expect">
          Most documents here are searchable within the hour. Larger uploads take
          longer — progress survives restarts, and the queue below shows exactly
          where each document stands.
        </p>

        {rowsError && (
          <p className="up-note">
            <span className="err">
              Couldn’t load the list of document types: {rowsError}
            </span>
          </p>
        )}

        <section className="card up-card" data-testid="upload-card">
          <fieldset className="up-types">
            <legend>What are you uploading?</legend>
            {(rows ?? []).map((row) => (
              <DocTypeOption
                key={row.key}
                row={row}
                selected={selectedKey === row.key}
                onSelect={() => setSelectedKey(row.key)}
              />
            ))}
          </fieldset>

          {selected &&
            (selected.redirect ? (
              // No `key` needed here: a redirect panel holds no form state of
              // its own, so there is nothing that could leak across a switch.
              <RedirectPanel row={selected} />
            ) : (
              // `key={selected.key}` is the whole fix for the hazard this
              // rework introduces: six independent cards used to mean six
              // independent pieces of React state, so nothing could leak
              // between them. One form now serves six types in turn, so
              // switching the selection must not let a file, fiscal year,
              // stage, error, duplicate or success message from the type
              // just left carry into the type just picked. Changing `key`
              // is what tells React "this is conceptually a different
              // component instance" — it unmounts the old form's state
              // (and its DOM, including the native file input's own
              // displayed filename) and mounts a brand new one, rather than
              // reusing the same instance and hoping every field was
              // reset by hand. See Upload.test.tsx's "switching the
              // selected type" spec, which fails the moment this key is
              // removed.
              <DocTypeForm key={selected.key} row={selected} onQueued={() => void refreshJobs()} />
            ))}
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

// --- the type picker ---------------------------------------------------------

/** One selectable row in the "What are you uploading?" list. Native radio
 *  semantics (shared `name`, grouped by a `<fieldset>`/`<legend>`) rather
 *  than a hand-rolled listbox — a single choice from a short list is exactly
 *  what a radio group is for, and it comes with keyboard (arrow-key) support
 *  and screen-reader grouping for free.
 *
 *  The radio's accessible NAME is just the type's label (`<label htmlFor>`);
 *  the "where to find it / which file" guidance is a separate paragraph
 *  wired in as `aria-describedby` rather than folded into the label. That
 *  keeps the name short (so "Annual Financial Report" reads as one clean
 *  choice, not a paragraph) while most screen readers still announce the
 *  description right after the name — the guidance stays legible, it's just
 *  not IN the name.
 */
function DocTypeOption({
  row,
  selected,
  onSelect,
}: {
  row: api.DocTypeCard;
  selected: boolean;
  onSelect: () => void;
}) {
  const inputId = `doctype-${row.key}`;
  const guidanceId = `${inputId}-guidance`;
  // where_published and which_file are two separate registry fields but read
  // as one sentence here — a redirect row's which_file is "" (see
  // api.ts's DocTypeCard comment), so this naturally drops the empty second
  // half instead of leaving a trailing space or an empty <p>.
  const guidance = [row.where_published, row.which_file].filter(Boolean).join(" ");

  return (
    <div
      className={`up-type-row${selected ? " is-selected" : ""}`}
      data-doc-type={row.key}
    >
      <input
        type="radio"
        id={inputId}
        name="doc-type"
        value={row.key}
        checked={selected}
        onChange={onSelect}
        aria-describedby={guidance ? guidanceId : undefined}
      />
      <div className="up-type-copy">
        <label htmlFor={inputId}>{row.label}</label>
        {guidance && (
          <p id={guidanceId} className="up-type-guidance">
            {guidance}
          </p>
        )}
      </div>
    </div>
  );
}

/** A Baseline Book / Appropriations Report is never uploaded as a single
 *  file (spec S25 — it's stored as ~110 per-agency documents, and offering
 *  "which file?" for it is itself the bug). Picking one of these two types
 *  shows its `redirect.detail` and a button to the existing Add-a-JLBC-book
 *  panel INSTEAD of a form — never both, and never a file input a type
 *  cannot accept.
 */
function RedirectPanel({ row }: { row: api.DocTypeCard }) {
  const redirect = row.redirect;
  // Guarded rather than asserted: the caller only renders this component for
  // a row it already checked has `redirect` set, but narrowing it here
  // (instead of a non-null assertion) means a future caller mistake fails
  // quietly with nothing rendered, not a runtime crash.
  if (!redirect) return null;
  return (
    <div className="up-redirect" data-testid="upload-redirect" data-doc-type={row.key}>
      <p>{redirect.detail}</p>
      <button
        type="button"
        className="fchip"
        onClick={() =>
          document
            .querySelector('[data-testid="add-book"]')
            ?.scrollIntoView({ behavior: "smooth" })
        }
      >
        {redirect.label}
      </button>
    </div>
  );
}

// --- the form, for whichever type is selected --------------------------------

/** Human-readable format list for the file-picker label, e.g. ".pdf" ->
 *  "PDF", [".pdf",".docx"] -> "PDF or DOCX". Derived from the registry's own
 *  `formats` rather than hardcoded, so the label can never claim a format
 *  the selected type doesn't actually accept. */
function formatsLabel(formats: string[]): string {
  return formats.map((f) => f.replace(/^\./, "").toUpperCase()).join(" or ");
}

/** The one form on the page. Rendered only for a selected, non-redirect
 *  type — remounted (via the caller's `key={row.key}`) every time the
 *  selection changes, which is what keeps one type's file/fiscal-year/
 *  stage/error/duplicate/success state from leaking into the next.
 */
function DocTypeForm({
  row,
  onQueued,
}: {
  row: api.DocTypeCard;
  onQueued: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [stage, setStage] = useState("");
  const [fy, setFy] = useState(() => String(defaultFiscalYear()));
  const [title, setTitle] = useState("");
  const [publicRecord, setPublicRecord] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [duplicate, setDuplicate] = useState<api.DuplicateDocument | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // A staged type (only budget-bill-summary today) may not submit without a
  // stage — this is the ONE gate that makes "Engrossed supersedes
  // Introduced" true, so it must hold on every submission through this
  // form, not just the first (see the "requires a fresh stage pick" spec).
  const ready =
    file !== null && publicRecord && (!row.stage_field || stage !== "");

  // The ONE place a new file — picked or dropped — enters this form's state.
  // Both the <input onChange> and the form's own onDrop call this same
  // function instead of setting state directly, so picking and dropping
  // can't drift apart (e.g. one re-derives the fiscal year, the other
  // forgets to).
  function selectFile(next: File | null) {
    setFile(next);
    setDuplicate(null);
    setError("");
    // A fresh file pick starts a new attempt through this form, so any
    // success message left over from the LAST upload of the SAME type must
    // go — otherwise a stale "added to the queue" line would sit above a
    // brand-new (possibly failing) attempt and read as if the new one had
    // already succeeded. (A switch to a DIFFERENT type clears this for
    // free, via the remount described at the call site above — this handles
    // the same-type, second-upload case that a remount doesn't cover.)
    setStatus("");
    // Re-derive the fiscal year every time the file changes — a fresh file
    // replaces the guess, even one the analyst just typed over.
    setFy(String(defaultFiscalYear(next?.name)));
  }

  async function submit(reprocess = false) {
    if (!file) return;
    // Captured before the success branch nulls `file` out — the confirmation
    // needs to name the document that was just submitted, not whatever this
    // form's file state happens to hold by the time React re-renders.
    const submittedName = file.name;
    setBusy(true);
    setError("");
    // Clear any leftover confirmation from a PRIOR successful submission of
    // the same type before this attempt is decided — a duplicate/error
    // result must never render underneath an old "added to the queue" line
    // from a previous, unrelated upload.
    setStatus("");
    try {
      await api.uploadDocument(file, {
        corpus: "budget",
        doc_type: row.key,
        fiscal_year: Number(fy),
        title: title.trim(),
        ...(row.stage_field ? { stage: stage as "introduced" | "engrossed" } : {}),
        ...(reprocess ? { reprocess: true } : {}),
      });
      setFile(null);
      setPublicRecord(false);
      setStage("");
      setTitle("");
      setDuplicate(null);
      // The only success signal on the page — scoped to this form's own
      // `.up-status` (the same element/role AddBookPanel already uses for
      // its own queued-confirmation message below), since only one form is
      // ever on screen there is nothing else it could be mistaken for.
      setStatus(`${submittedName} added to the queue.`);
      // Clearing React state doesn't clear the browser's own file input
      // display — without this the widget would keep showing the just-
      // submitted filename after a successful upload.
      if (fileInputRef.current) fileInputRef.current.value = "";
      onQueued();
    } catch (e) {
      if (e instanceof api.DuplicateDocumentError) {
        setDuplicate(e.info);
      } else {
        setError(e instanceof Error ? e.message : String(e));
      }
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="up-form"
      data-testid="upload-form"
      data-doc-type={row.key}
      // Dragging a file onto this form is the same as picking it through
      // the file input below — preventDefault on dragover is required or
      // the browser navigates to the file instead of handing it to onDrop,
      // the classic way this silently does nothing.
      onDragOver={(e) => e.preventDefault()}
      onDrop={(e) => {
        e.preventDefault();
        selectFile(e.dataTransfer.files?.[0] ?? null);
      }}
    >
      <h3>{row.label}</h3>
      <p className="up-note">{row.where_published}</p>
      {row.which_file && <p>{row.which_file}</p>}

      <div className="up-meta">
        <div className="up-drop">
          <label>
            {`Choose a ${formatsLabel(row.formats)} document`}
            <input
              ref={fileInputRef}
              type="file"
              accept={row.formats.join(",")}
              onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
            />
          </label>
          <p className="up-drop-hint">or drag and drop it here</p>
          {file && <p className="up-filename">{file.name}</p>}
        </div>

        {row.stage_field && (
          <label>
            Version
            <select
              name="stage"
              value={stage}
              onChange={(e) => setStage(e.target.value)}
            >
              <option value="">Choose…</option>
              <option value="introduced">As Introduced</option>
              <option value="engrossed">As Engrossed</option>
            </select>
          </label>
        )}

        <label>
          Fiscal year
          <input
            type="text"
            value={fy}
            onChange={(e) => setFy(e.target.value)}
            inputMode="numeric"
          />
        </label>

        <label>
          Title (optional)
          <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
        </label>

        {/* Invariant 8. The server returns 400 without this, so removing it
            here produces a confusing error rather than a hole — but it is
            the deliberate human moment the invariant exists for. */}
        <label className="up-check">
          <input
            type="checkbox"
            checked={publicRecord}
            onChange={(e) => setPublicRecord(e.target.checked)}
          />
          This document is a public record.
        </label>

        {duplicate && (
          <div className="up-dupe" data-testid="duplicate">
            <p>
              This document is already in the corpus
              {duplicate.added_at ? ` (added ${formatDate(duplicate.added_at)}` : ""}
              {duplicate.added_by ? ` by ${duplicate.added_by})` : duplicate.added_at ? ")" : ""}
              .
            </p>
            <button type="button" className="allbtn" onClick={() => void submit(true)}>
              Process it again anyway
            </button>
          </div>
        )}

        {error && (
          <p className="up-note">
            <span className="err">{error}</span>
          </p>
        )}

        <button
          type="button"
          className="allbtn"
          disabled={!ready || busy}
          onClick={() => void submit(false)}
        >
          {busy ? "Adding…" : "Add document"}
        </button>

        {/* Rendered unconditionally (empty text when there's nothing to
            say) — a role="status" live region announces most reliably when
            it's already present in the DOM and only its TEXT changes,
            rather than appearing and disappearing. Never coexists with
            `error`/`duplicate`: both are cleared the instant a fresh
            attempt starts (selectFile, submit), so a stale success line
            can't sit above a new failure. */}
        <p className="up-status" role="status">{status}</p>
      </div>
    </div>
  );
}

// --- filename heuristics ------------------------------------------------------

/** Best-effort fiscal year from a filename, falling back to the year most
 *  likely being worked on when there's no signal in the name at all. Every
 *  field this feeds stays editable — it saves typing, it doesn't decide
 *  anything.
 *
 *  The patterns are the JLBC publishing conventions the corpus already uses:
 *  `27baseline-axs.pdf` (a two-digit year folded into a JLBC slug) and an
 *  explicit `FY2026` anywhere in the name.
 */
export function defaultFiscalYear(filename?: string): number {
  if (filename) {
    const name = filename.toLowerCase();
    const explicit = name.match(/fy\s*-?\s*(\d{4})/);
    if (explicit) return Number(explicit[1]);
    const twoDigit = name.match(/(?:^|[^0-9])(\d{2})(baseline|ar)\b/);
    if (twoDigit) return 2000 + Number(twoDigit[1]);
  }
  // No signal — default to the fiscal year we're most likely adding to.
  // Arizona's FY starts in July, so from July onward the current work is
  // next calendar year's book.
  const now = new Date();
  return now.getMonth() >= 6 ? now.getFullYear() + 1 : now.getFullYear();
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
