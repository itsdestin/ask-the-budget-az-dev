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

  // "What has JLBC published that we don't have?" (spec T10) is fetched ONCE
  // here, not inside each book card, for two reasons. It answers for BOTH
  // families in one round-trip, so two cards fetching it separately is two
  // calls for one answer. And the collapsed row shows a count off it — so if
  // the panel owned the fetch, pressing "Check again" inside an open card
  // would update the panel and leave the row above it stating the OLD count,
  // which is the same number disagreeing with itself on one screen.
  const [check, setCheck] = useState<api.BookCheck | null>(null);
  const [checking, setChecking] = useState(true);
  const [checkError, setCheckError] = useState("");

  // Who is looking. The two JLBC-book cards carry a "Full report link" row
  // that only an admin may use (Destin's call, 2026-08-16), and everyone in
  // the office can open this page.
  //
  // Fetched ONCE here rather than inside each book card, for the same reason
  // the check above is: two cards asking the same question is two calls for
  // one answer. A failure means no row, which is the right default — better a
  // missing control than one that 403s. Same idiom as `Header`, which decides
  // the Admin pill this way.
  const [isAdmin, setIsAdmin] = useState(false);
  useEffect(() => {
    let cancelled = false;
    api
      .me()
      .then((m) => !cancelled && setIsAdmin(m.is_admin))
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  const loadCheck = useCallback(async (refresh: boolean) => {
    setChecking(true);
    setCheckError("");
    try {
      setCheck(await api.booksMissing(refresh));
    } catch (e) {
      setCheckError(e instanceof Error ? e.message : String(e));
    } finally {
      setChecking(false);
    }
  }, []);

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

  useEffect(() => {
    void loadCheck(false);
  }, [loadCheck]);

  return (
    <main className="page-upload" data-testid="upload">
      <div className="wrap">
        <h1 className="up-title">Add a document</h1>

        {/* Invariant 8, in ONE line. Measured before this change: the page
            carried 214 words before an analyst could do anything, 87 of them
            here — and the six things they came to choose between are 14
            words. The RULE is what has to be permanently visible, and it is;
            the explanation of why the rule exists is read once and then
            skipped for ever, so it sits behind a disclosure. The per-upload
            tick-box, which is the deliberate moment the invariant is really
            built on, is untouched. */}
        <details className="card up-notice up-disclose" data-testid="public-record-notice">
          <summary>
            <WarnGlyph />
            <span className="up-notice-rule">
              Public record only — never confidential state data.
            </span>
            <Chevron />
          </summary>
          <p>
            When AI Mode answers a question it sends the text of retrieved
            passages to an outside AI provider, and anything placed here is
            readable by everyone with access to the shared drive. Search on its
            own never sends document text anywhere — but the document is still
            on the shared drive once uploaded.
          </p>
        </details>

        {rowsError && (
          <p className="up-note">
            <span className="err">
              Couldn’t load the list of document types: {rowsError}
            </span>
          </p>
        )}

        {/* One NAMED card holding six cards of its own. The rows were
            hairlined inside a single card first; separating them again was
            asked for directly, and the outer card is what stops six floating
            boxes reading as six unrelated features — the objection that
            killed the original six-card layout. The outer card carries the
            page's canvas as its ground so the six read as sitting IN
            something rather than merely near each other. */}
        <section className="card up-list" aria-labelledby="up-list-h">
          <h2 id="up-list-h">Uploads</h2>
          {(rows ?? []).map((row) => (
            <DocTypeCard
              key={row.key}
              row={row}
              open={openKey === row.key}
              status={bookStatus(row, check, checking)}
              // Clicking the open card closes it — the header is a toggle,
              // not a one-way selector, so there is always a way back to
              // "nothing open" without picking something you don't want.
              onToggle={() =>
                setOpenKey((current) => (current === row.key ? null : row.key))
              }
              check={check}
              checking={checking}
              checkError={checkError}
              isAdmin={isAdmin}
              onRecheck={() => void loadCheck(true)}
              onQueued={() => void refreshJobs()}
            />
          ))}
        </section>

        <QueuePanel reloadToken={queueToken} />
      </div>
    </main>
  );
}

// --- one card per document type ----------------------------------------------

/** The collapsed row's right-hand state, for the two JLBC-book types only.
 *
 *  This is the whole reason the check is fetched at page level: it answers
 *  the only question anyone has about a book card — is there anything to
 *  add? — without opening it. The other four types have no equivalent (the
 *  app cannot know whether the Auditor General has published this year's
 *  AFR until somebody looks), and inventing a filler state for them would
 *  be four labels that say nothing.
 */
function bookStatus(
  row: api.DocTypeCard,
  check: api.BookCheck | null,
  checking: boolean,
): { text: string; tone: string } | null {
  if (!row.redirect) return null;
  if (!check) return checking ? { text: "checking…", tone: "wait" } : null;
  // An unreachable azjlbc.gov must not read as "up to date" — that is a
  // confident wrong answer produced by a network failure, on the one row
  // whose job is telling you what is missing.
  if (!check.online) return { text: "can’t check", tone: "warn" };
  const n = check.missing.filter((m) => m.family === row.redirect?.family).length;
  return n > 0
    ? { text: `${n} to add`, tone: "act" }
    : { text: "up to date", tone: "ok" };
}

/** One expandable row of the document-type list.
 *
 *  The head is a `<button aria-expanded>` inside a heading — the standard
 *  disclosure pattern, chosen over the two alternatives this page has worn
 *  before. A `<details>/<summary>` cannot be driven from the outside, and
 *  "only one open at a time" is a decision about the SET, so the parent has
 *  to own it. A radio group (what this replaced) says "choose one of these"
 *  when what actually happens is "open this one" — and a radio can never be
 *  un-picked, so there was no way back to a page with nothing open.
 *
 *  🔴 THE ROW CARRIES THE NAME AND NOTHING ELSE THAT NEEDS READING. It used
 *  to carry `where_published` as a full sentence, which put 101 words across
 *  six rows whose six NAMES are 14 words — the list you came to scan was the
 *  minority of its own text. `group` (already on the wire, and previously
 *  displayed nowhere) becomes a quiet publisher tag in a fixed left column,
 *  so the eye can sort six rows by publisher without reading a word of
 *  prose. The sentence itself is not deleted — it moves inside, where it is
 *  guidance for the moment you act rather than noise while you choose.
 *
 *  The body is UNMOUNTED when closed, not hidden. Two things follow, both
 *  wanted: a closed row's half-filled form cannot survive to be submitted
 *  by accident, and there is only ever one file input in the document, so
 *  "the Add button" is unambiguous to a test, a screen reader and a person.
 */
function DocTypeCard({
  row,
  open,
  status,
  onToggle,
  check,
  checking,
  checkError,
  isAdmin,
  onRecheck,
  onQueued,
}: {
  row: api.DocTypeCard;
  open: boolean;
  status: { text: string; tone: string } | null;
  onToggle: () => void;
  check: api.BookCheck | null;
  checking: boolean;
  checkError: string;
  /** Passed straight through to the book panel, which hides its admin-only
   *  "Full report link" row when false. Resolved once by the page. */
  isAdmin: boolean;
  onRecheck: () => void;
  onQueued: () => void;
}) {
  const headId = `up-head-${row.key}`;
  const bodyId = `up-body-${row.key}`;

  return (
    <div
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
          onClick={onToggle}
        >
          {/* aria-hidden: the publisher is already the first words of the
              sentence inside, and a screen reader hearing "J L B C, Baseline
              Book" gains nothing over "Baseline Book". This tag is a visual
              sorting aid, and claiming otherwise would just make the
              accessible name longer for no one's benefit. */}
          <span className="up-card-pub" aria-hidden="true">
            {row.group}
          </span>
          <span className="up-card-name">{row.label}</span>
          {status && (
            <span className={`up-card-state up-tone-${status.tone}`}>{status.text}</span>
          )}
          <Chevron />
        </button>
      </h2>

      {open && (
        <div className="up-card-body" id={bodyId} role="region" aria-labelledby={headId}>
          {row.redirect ? (
            // A Baseline Book / Appropriations Report is never uploaded as a
            // single file (spec S25 — it's stored as ~110 per-agency
            // documents, and offering "which file?" for it is itself the
            // bug). Its row expands into that family's own gap instead: a
            // list of what JLBC has published that this corpus lacks. Never
            // both, and never a file input a type cannot accept.
            <BookFamilyPanel
              family={row.redirect.family}
              label={row.label}
              detail={row.redirect.detail}
              wherePublished={row.where_published}
              check={check}
              checking={checking}
              checkError={checkError}
              isAdmin={isAdmin}
              onRecheck={onRecheck}
              onQueued={onQueued}
            />
          ) : (
            <DocTypeForm row={row} onQueued={onQueued} />
          )}
        </div>
      )}
    </div>
  );
}

/** The notice's mark. Decorative — the sentence beside it carries the whole
 *  meaning, and a screen reader announcing "warning icon" ahead of it adds
 *  nothing the words don't already say. */
function WarnGlyph() {
  return (
    <svg className="up-notice-glyph" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
      <path
        d="M12 3.8L21 19.5H3L12 3.8zM12 10v4.2M12 16.6v.1"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.9"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
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
  // 🔴 NO TITLE FIELD. Every other type is named completely by its type and
  // its year -- "FY 2025 Annual Financial Report" IS the AFR, there is one a
  // year -- so a free-text box offered a choice where there was none, and
  // invited a hand-typed title to override a correct automatic one. The one
  // type where the name genuinely varies is an agency budget request (~78 a
  // year, otherwise all called "FY 2027 Budget Request"), and that is a
  // PICKED agency rather than typed prose, so two people uploading two
  // agencies' requests cannot spell the same agency two ways.
  const [agencyId, setAgencyId] = useState("");
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
    file !== null &&
    publicRecord &&
    (!row.stage_field || stage !== "") &&
    (!row.agency_field || agencyId !== "");

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
        // Always empty now. The field is kept on the wire because the
        // server still honours a supplied title (`build_title`: "a title the
        // uploader typed wins verbatim") and the books route and any future
        // caller may want it -- the UPLOAD PAGE simply no longer offers one.
        title: "",
        ...(row.stage_field ? { stage: stage as "introduced" | "engrossed" } : {}),
        // Sent only when the row declares it. The route 422s on an agency
        // supplied for a type that has no `agency_field`, the same way it
        // does for a stray stage.
        ...(row.agency_field ? { agency_canonical_id: agencyId } : {}),
        ...(reprocess ? { reprocess: true } : {}),
      });
      setFile(null);
      setPublicRecord(false);
      setStage("");
      setAgencyId("");
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
      {/* Both registry sentences live HERE, not on the collapsed row. They
          are instructions for the moment you go and fetch a file, which is
          after you have opened this — and on the row they were 101 words of
          prose wrapped around 14 words of names. The AFR's is the clearest
          case: "gao.az.gov blocks automated downloads, so save it from a
          browser" is genuinely important and completely useless as scanning
          material. Nothing is lost, it is one click later. */}
      {row.where_published && <p className="up-where">{row.where_published}</p>}
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
          {row.agency_field && (
            <AgencyPicker value={agencyId} onChange={setAgencyId} />
          )}

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

/** Which agency a budget request belongs to.
 *
 *  🔴 A NATIVE <select> WITH 157 OPTIONS WAS THE WRONG SHAPE, and the count
 *  is the reason: a browser's own select only jumps by first letter, so
 *  finding "Water Infrastructure Finance Authority" means scrolling past
 *  most of the list. This is a `<datalist>`-backed text input instead — the
 *  analyst types "water", the browser filters, and the same control still
 *  works with a mouse and a keyboard because it IS a native input.
 *
 *  The typed text is NOT the answer. `value` is the canonical id, resolved
 *  from an exact name match, and the form stays unsubmittable until one
 *  resolves — a half-typed "Depart" must not become a document title, and
 *  the server refuses an id it does not know anyway (422). That is the
 *  whole point of a picker over the free-text Title box it replaces.
 *
 *  Agencies an ADMIN added are listed under their own heading rather than
 *  merged into the alphabetical run. Nothing in the corpus is stamped with
 *  an office-added id, so the two are genuinely different things and the
 *  list should not pretend otherwise.
 */
function AgencyPicker({
  value,
  onChange,
}: {
  value: string;
  onChange: (canonicalId: string) => void;
}) {
  const [options, setOptions] = useState<api.AgencyOption[]>([]);
  const [error, setError] = useState("");
  const [typed, setTyped] = useState("");

  useEffect(() => {
    api
      .agencies()
      .then(setOptions)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  // Exact, case-insensitive, whitespace-collapsed. Deliberately NOT a fuzzy
  // or prefix match: a near-match that silently picks an agency is the
  // failure this control exists to prevent, and "Department of Health
  // Services" vs "Department of Child Safety" are one letter apart in the
  // places that matter.
  function resolve(text: string): string {
    const wanted = text.trim().replace(/\s+/g, " ").toLowerCase();
    const hit = options.find(
      (o) => o.name.trim().replace(/\s+/g, " ").toLowerCase() === wanted,
    );
    return hit ? hit.canonical_id : "";
  }

  const catalog = options.filter((o) => o.source === "catalog");
  const office = options.filter((o) => o.source === "office");

  const noteId = "up-agency-note";
  // 🔴 A <div> with a `htmlFor` label, NOT a <label> wrapping everything —
  // which is what the other fields on this form use and what this was
  // written as first. A <label>'s whole text content becomes the field's
  // ACCESSIBLE NAME, so with the "No agency by that name" note inside it the
  // input stopped being called "Agency" and started being called "Agency No
  // agency by that name. Pick one from the list…". A screen reader would
  // read the error as part of the field's name every time focus landed, and
  // the name would change as you typed. The note is `aria-describedby`
  // instead, which is what describes a field's STATE.
  return (
    <div className="up-field up-field-agency">
      <label htmlFor="up-agency">Agency</label>
      <input
        id="up-agency"
        type="text"
        list="up-agency-options"
        aria-describedby={noteId}
        value={typed}
        placeholder={options.length ? "Start typing an agency's name" : "Loading…"}
        onChange={(e) => {
          setTyped(e.target.value);
          onChange(resolve(e.target.value));
        }}
      />
      <datalist id="up-agency-options">
        {catalog.map((o) => (
          <option key={o.canonical_id} value={o.name} />
        ))}
        {office.length > 0 && (
          <>
            {office.map((o) => (
              <option key={o.canonical_id} value={o.name} label="added by your office" />
            ))}
          </>
        )}
      </datalist>
      {/* Three states, and the middle one is the one that matters: text
          typed that resolves to nothing. Saying nothing there would leave a
          disabled Add button with no explanation for why. */}
      {/* Rendered unconditionally (empty when there is nothing to say) so
          the described-by target always exists — an element that appears and
          disappears is announced unreliably. */}
      <span id={noteId} className={`up-field-note${error ? " err" : ""}`}>
        {error
          ? `Couldn’t load the agency list: ${error}`
          : typed.trim() && !value
            ? "No agency by that name. Pick one from the list — an admin can add a missing agency in Settings."
            : ""}
      </span>
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

