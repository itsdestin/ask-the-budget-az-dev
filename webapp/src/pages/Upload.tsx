import { useCallback, useEffect, useRef, useState } from "react";
import * as api from "../api";
import { BookFamilyPanel } from "./upload/BookFamilyPanel";
import { QueuePanel } from "./upload/QueuePanel";

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
// WHY six cards that expand ONE AT A TIME (2026-08-15, superseding both the
// original "six guided rows" and the radio-list-plus-one-shared-form that
// replaced it). The history matters because the two obvious shapes have each
// already been rejected for a reason worth keeping:
//
//   - Six full cards, all expanded, was rejected on sight — "why are there 6
//     entirely different upload cards." Six file inputs, six fiscal-year
//     boxes, six checkboxes and six Add buttons down one page read as six
//     features, and make it easy to fill in one card and press Add in
//     another.
//   - A radio list feeding one shared form below fixed that, and was
//     rejected in turn: the form was visibly a separate section rather than
//     part of the thing you picked, and it left a SECOND separate section
//     ("Add a JLBC book") restating two of the same six types.
//
// The accordion keeps the property the shared form was built for — exactly
// one file input, one fiscal year, one checkbox and one Add button on screen
// at any moment — while the form lives INSIDE the card it belongs to.
// Opening a card closes the one that was open, and a closed card's body is
// unmounted, so no half-filled form for a type you are not looking at can
// exist at all. That is what makes the "does not carry X to the next type"
// specs structural rather than something a future edit could quietly undo:
// they used to depend on a `key=` prop, and now the state cannot outlive the
// close.
//
// The two JLBC-book types expand into their OWN family's gap (spec T10)
// instead of a file form — that is the whole of "no separate JLBC Books
// section".
//
// The types themselves are still exactly Task 6's insight (an analyst
// doesn't know a raw doc_type slug, so name a real document and let the row
// determine its own doc_type/publisher). The rows come from
// GET /api/document-types, a straight projection of data/document-types.yaml,
// so this file holds no copy of the type list at all — that list drifting
// from the server's is exactly the bug this page used to ship (twice, now,
// in two different shapes). That is also why the book family arrives as
// `redirect.family` off the wire rather than a key→family map written here.

export function Upload() {
  const [rows, setRows] = useState<api.DocTypeCard[] | null>(null);
  const [rowsError, setRowsError] = useState("");
  // Bumped whenever this page queues something, so QueuePanel refetches
  // immediately instead of waiting out its poll interval. The panel owns
  // the queue state itself (spec T13) -- the page only says "look again".
  const [queueToken, setQueueToken] = useState(0);
  const refreshJobs = useCallback(() => setQueueToken((n) => n + 1), []);
  // Which card is open, if any. Lives on the page rather than inside each
  // card because "one at a time" is a statement about the SET — a card
  // cannot know to close itself when a sibling opens.
  const [openKey, setOpenKey] = useState<string | null>(null);

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

        <div className="up-cards">
          {(rows ?? []).map((row) => (
            <DocTypeCard
              key={row.key}
              row={row}
              open={openKey === row.key}
              // Clicking the open card closes it — the header is a toggle,
              // not a one-way selector, so there is always a way back to
              // "nothing open" without picking something you don't want.
              onToggle={() =>
                setOpenKey((current) => (current === row.key ? null : row.key))
              }
              onQueued={() => void refreshJobs()}
            />
          ))}
        </div>

        <QueuePanel reloadToken={queueToken} />
      </div>
    </main>
  );
}

// --- one card per document type ----------------------------------------------

/** One expandable document-type card.
 *
 *  The header is a `<button aria-expanded>` inside a heading — the standard
 *  disclosure pattern, chosen over the two alternatives this page has worn
 *  before. A `<details>/<summary>` cannot be driven from the outside, and
 *  "only one open at a time" is a decision about the SET, so the parent has
 *  to own it. A radio group (what this replaced) says "choose one of these"
 *  when what actually happens is "open this one" — and a radio can never be
 *  un-picked, so there was no way back to a page with nothing open.
 *
 *  The accessible name is just the type's label, so a screen reader hears
 *  "Annual Financial Report, collapsed" rather than a paragraph. The "where
 *  it's published" line rides along as `aria-describedby`, which most
 *  readers announce straight after the name — legible, just not IN the name.
 *
 *  The body is UNMOUNTED when closed, not hidden. Two things follow, both
 *  wanted: a closed card's half-filled form cannot survive to be submitted
 *  by accident, and there is only ever one file input in the document, so
 *  "the Add button" is unambiguous to a test, a screen reader and a person.
 */
function DocTypeCard({
  row,
  open,
  onToggle,
  onQueued,
}: {
  row: api.DocTypeCard;
  open: boolean;
  onToggle: () => void;
  onQueued: () => void;
}) {
  const headId = `up-head-${row.key}`;
  const bodyId = `up-body-${row.key}`;
  const whereId = `up-where-${row.key}`;

  return (
    <section
      className={`card up-card${open ? " is-open" : ""}`}
      data-testid="doc-type-card"
      data-doc-type={row.key}
    >
      <h2 className="up-card-head">
        <button
          type="button"
          id={headId}
          className="up-card-toggle"
          aria-expanded={open}
          aria-controls={bodyId}
          aria-describedby={row.where_published ? whereId : undefined}
          onClick={onToggle}
        >
          <span className="up-card-ttl">
            <span className="up-card-name">{row.label}</span>
            {row.where_published && (
              <span id={whereId} className="up-card-where">
                {row.where_published}
              </span>
            )}
          </span>
          <Chevron />
        </button>
      </h2>

      {open && (
        <div className="up-card-body" id={bodyId} role="region" aria-labelledby={headId}>
          {row.redirect ? (
            // A Baseline Book / Appropriations Report is never uploaded as a
            // single file (spec S25 — it's stored as ~110 per-agency
            // documents, and offering "which file?" for it is itself the
            // bug). Its card expands into that family's own gap instead: a
            // list of what JLBC has published that this corpus lacks. Never
            // both, and never a file input a type cannot accept.
            <BookFamilyPanel
              family={row.redirect.family}
              label={row.label}
              detail={row.redirect.detail}
              onQueued={onQueued}
            />
          ) : (
            <DocTypeForm row={row} onQueued={onQueued} />
          )}
        </div>
      )}
    </section>
  );
}

/** The drop zone's mark. Decorative — `aria-hidden`, because the label and
 *  the hint beside it already say what this box does, and a screen reader
 *  announcing "upload icon" adds nothing a blind user can act on. */
function UploadGlyph() {
  return (
    <svg className="up-drop-glyph" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5M4 15v3a2 2 0 002 2h12a2 2 0 002-2v-3"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/** The disclosure caret. Rotated by CSS on `.is-open` rather than swapped
 *  for a second glyph, so the two states are one shape in motion — the same
 *  treatment the Budget Documents year cards already use. */
function Chevron() {
  return (
    <svg className="up-card-caret" viewBox="0 0 16 16" aria-hidden="true" focusable="false">
      <path
        d="M4 6l4 4 4-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
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

/** The upload form, rendered inside its own type's card and only while that
 *  card is open. Closing the card unmounts it, which is what keeps one
 *  type's file / fiscal-year / stage / error / duplicate / success state
 *  from ever reaching another type's — the earlier shared-form design
 *  needed a deliberate `key=` prop to get the same guarantee.
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
      {/* `which_file` — which of a publisher's several PDFs to take — lives
          here rather than on the collapsed card header. It is instructions
          for the moment you go and fetch the file, which is after you've
          opened this card; `where_published` is the recognition cue and
          stays on the header where it helps you choose. */}
      {row.which_file && <p className="up-which">{row.which_file}</p>}

      <div className="up-meta">
        {/* The file input itself is visually hidden (never `display:none`,
            which would take it out of the accessibility tree and off the
            keyboard) and its own <label> is painted as the button. The
            browser's native widget is the "Choose File · No file chosen"
            control that made this page look like a raw HTML form. */}
        <div className="up-drop">
          <UploadGlyph />
          <p className="up-drop-hint">Drag and drop it here, or</p>
          <label className="fchip up-drop-btn">
            {`Choose a ${formatsLabel(row.formats)} document`}
            <input
              className="up-file"
              ref={fileInputRef}
              type="file"
              accept={row.formats.join(",")}
              onChange={(e) => selectFile(e.target.files?.[0] ?? null)}
            />
          </label>
          {file && <p className="up-filename">{file.name}</p>}
        </div>

        <div className="up-fields">
          {row.stage_field && (
            <label className="up-field">
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

          <label className="up-field">
            Fiscal year
            <input
              type="text"
              value={fy}
              onChange={(e) => setFy(e.target.value)}
              inputMode="numeric"
            />
          </label>

          <label className="up-field">
            Title (optional)
            <input type="text" value={title} onChange={(e) => setTitle(e.target.value)} />
          </label>
        </div>

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
            {/* Plan B Blocking 3 (T12): the server's OWN sentence about
                whether the existing copy's extraction looked complete —
                app/routes/upload.py's `_duplicate_health`, pinned by six
                backend tests that were shipping with nothing on screen to
                show for them. Rendered VERBATIM, never recomposed here —
                T12 exists specifically because a blanket "already
                ingested" warning would discourage exactly the
                re-processing a badly-extracted document (like the FY2024
                AFR) needs, and a client-built paraphrase of `health` could
                say something the server didn't.

                Gated on `health`, not just on `message` being truthy:
                `_duplicate_health` ALWAYS returns a message string — for
                the 7,434 legacy documents with no recorded coverage it
                returns a generic one ("This document is already in the
                corpus.") alongside a null `health` — so gating on
                `message` alone would print that generic line under the
                sentence above on every single duplicate, which is exactly
                the redundant, un-actionable line T12 is about NOT adding.
                `health` is null for precisely those legacy documents and
                only those, so gating on it is what makes "nothing new to
                say" actually render as nothing — the sentence above stays
                exactly what it always rendered, and that is genuinely the
                overwhelmingly common case, not just a fallback for a
                missing field. */}
            {duplicate.health && duplicate.message && (
              <p data-testid="duplicate-health">{duplicate.message}</p>
            )}
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

