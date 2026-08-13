// One content-search result: ONE note, showing its best passage (spec F11-F14,
// F16). Built from mockups/fiscal-notes-retrieval-results.html, which is the
// pixel reference — the browse mockup's older card is explicitly NOT.

import type { PassageDoc } from "../search/contentSearch";
import { highlightTerms, previewWindow, queryTerms } from "../search/contentSearch";
import { parseNoteTitle } from "../search/fiscalNotes";
import { BillTitle } from "./billTitle";

export interface FiscalNoteResultProps {
  note: PassageDoc;
  /** The label for this note's session, already built by `sessionLabel` and
   *  JOINED from the browse directory — a search result carries only the bare
   *  `fiscal_year`, never the session's name (spec F4). Null when the year has
   *  no directory session, which the 1999-2026 one-per-year mapping makes
   *  unreachable today; rendered as nothing rather than as "null". */
  sessionLabel: string | null;
  /** The query, for marking the words the analyst typed. */
  query: string;
  /** Is this note's passage the one currently open in the drawer? */
  open: boolean;
  onToggle(chunkId: string): void;
}

/** The section heading a passage came from, e.g. "Estimated Impact".
 *
 *  The LAST element of `section_path` — the innermost heading, which is the one
 *  that names this passage rather than the document around it.
 *
 *  It is emphatically NOT `doc_meta`, which an earlier draft used: that field is
 *  the mockup index's category line, and on this corpus it renders as
 *  "Fiscal Notes · Fiscal Notes · FY 2026" — a doubled, uninformative label
 *  where the legend should read "Estimated Impact". Seen only once real
 *  retrieval was wired up; every fixture had a hand-written doc_meta that
 *  looked like a section name and hid it. */
function sectionOf(passage: PassageDoc["passages"][number]): string | null {
  const path = passage.section_path;
  if (!path?.length) return null;
  const leaf = path[path.length - 1]?.trim();
  return leaf ? leaf : null;
}

export function FiscalNoteResult({
  note,
  sessionLabel,
  query,
  open,
  onToggle,
}: FiscalNoteResultProps) {
  // F11: the BEST passage, and nothing else. No tray, no "N more passages".
  // A result answers "which note should I read?", and the top-ranked passage
  // is the evidence for that answer; the rest belong to the note, which is one
  // click away.
  const best = note.passages[0];
  // F16: the retrieval title is `Fiscal Note - HB 2407: victim notification`,
  // NOT the browse row's title. Three things follow and all three are visible
  // defects if skipped — strip the prefix, split on the FIRST colon, and render
  // through BillTitle (which handles the 241 raw-<strike> titles safely).
  const { number, title } = parseNoteTitle(note.doc_title);
  const section = sectionOf(best);
  const terms = queryTerms(query);
  const view = previewWindow(best.text || best.snippet, terms);

  return (
    // F13: the WHOLE card is one button. With the old context strip gone, no
    // second interactive element remains, so the card can be a single control
    // the way a `.fbill` row is a single link. A test pins zero nested
    // buttons/anchors, because a nested one is invalid HTML that jsdom will
    // happily render.
    <button
      type="button"
      className={open ? "grp is-open" : "grp"}
      data-testid="fn-result"
      onClick={() => onToggle(best.chunk_id)}
    >
      <span className="res-top">
        <span className="res-name">
          {number && <span className="res-no">{number}</span>}
          {number && " — "}
          <BillTitle title={title} />
        </span>
        {/* Decorative, exactly as `.fbill-dl`'s "PDF" label is: it names the
            action, it does not take the click. Reads "Close note" while this
            card's drawer is open, because the card is a TOGGLE rather than a
            one-way action. */}
        <span className="grp-open">{open ? "Close note" : "Open note"}</span>
      </span>
      {sessionLabel && <span className="res-year">{sessionLabel}</span>}
      <span className="exc">
        {section && <span className="exc-lbl">{section}</span>}
        {/* Runs, not an HTML string: the passage is corpus text, and building
            <mark> markup from it would mean dangerouslySetInnerHTML on data
            this app does not control. Word boundaries at BOTH ends, matching
            the shipped highlightTerms() — anchoring only the front highlights
            "inmate" inside "inmates" and leaves the "s" outside the mark. */}
        {/* A WINDOW onto the passage, not the whole passage (the same
            `previewWindow` Budget Documents' cards use). Rendering `text` raw
            was a real defect: fiscal-note passages run to a full paragraph, so
            a card grew to ~250px and roughly two fit on a screen — against a
            design whose entire argument for a tighter card was that a result
            list has to be comparable at a glance. Invisible against fixtures,
            whose excerpts were one line by construction. */}
        <span className="doc-quote">
          {view.ellipsisStart && <span aria-hidden="true">… </span>}
          {highlightTerms(view.text, terms).map((run, i) =>
            run.hit ? <mark key={i}>{run.text}</mark> : <span key={i}>{run.text}</span>,
          )}
          {view.ellipsisEnd && <span aria-hidden="true"> …</span>}
        </span>
      </span>
    </button>
  );
}
