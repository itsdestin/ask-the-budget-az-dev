// webapp/src/components/PassageCard.tsx
// ONE content-search result: one card per DOCUMENT (Destin, 2026-08-10).
// Two documents from the same report in the same fiscal year are two cards;
// one document is never two cards.
//
// The headline row is the best matching PASSAGE, quoted — not the document
// title. WHY: the reader escalated to content search because they had a
// question, and the sentence that answers it is the result. A document title
// tells them which book to open, which is what title mode already did.
//
// The dashed block carries the document's identity and exactly ONE action,
// "More from this document". No "Open document", no "Full report" — the
// format chooser belongs to the browse card, not this one.

import { useMemo, useState } from "react";
import { publisherLabel } from "../publishers";
import { ChevronIcon } from "./DocIcons";
import {
  highlightTerms,
  previewWindow,
  queryTerms,
  type PassageDoc,
} from "../search/contentSearch";
import type { SearchResult } from "../api";

/** The quoted passage, with the analyst's words marked.
 *
 *  Runs come from `highlightTerms()` and are rendered as ELEMENTS — the text is
 *  corpus text, so building markup from it and setting innerHTML would be
 *  handing untrusted content to the DOM.
 *
 *  `expanded` is owned by the CARD, not by this component: the rows are real
 *  <button> elements and a nested <button> is invalid HTML, so the control
 *  lives once in the card's context row (spec H9). */
function Quote({
  text,
  terms,
  expanded,
}: {
  text: string;
  terms: string[];
  expanded: boolean;
}) {
  const view = expanded
    ? { text, ellipsisStart: false, ellipsisEnd: false }
    : previewWindow(text, terms);
  return (
    <span className="doc-quote">
      {view.ellipsisStart && <span aria-hidden="true">… </span>}
      {highlightTerms(view.text, terms).map((run, i) =>
        run.hit ? <mark key={i}>{run.text}</mark> : <span key={i}>{run.text}</span>,
      )}
      {view.ellipsisEnd && <span aria-hidden="true"> …</span>}
    </span>
  );
}

/** One passage row. It is a real <button>: the href would be a placeholder,
 *  the handler is what opens the source, and provenance is the one path that
 *  must not require a pointing device. The page pill carries the arrow that
 *  says so (the A1 affordance). */
function PassageRow({
  passage,
  terms,
  expanded,
  onOpen,
}: {
  passage: SearchResult;
  terms: string[];
  expanded: boolean;
  onOpen: (chunkId: string) => void;
}) {
  return (
    <button type="button" className="doc quoterow" onClick={() => onOpen(passage.chunk_id)}>
      <div className="doc-main">
        <Quote text={passage.text} terms={terms} expanded={expanded} />
      </div>
      <span className="doc-pill">
        {passage.page === null ? "no page" : `p. ${passage.page}`}
        <span className="go" aria-hidden="true">
          →
        </span>
      </span>
    </button>
  );
}

export function PassageCard({
  doc,
  query,
  trayOpen,
  onToggleTray,
  onOpenPassage,
}: {
  doc: PassageDoc;
  query: string;
  trayOpen: boolean;
  onToggleTray: () => void;
  onOpenPassage: (chunkId: string) => void;
}) {
  const [best, ...rest] = doc.passages;
  const [expanded, setExpanded] = useState(false);
  const terms = useMemo(() => queryTerms(query), [query]);
  // Only offer the control when something is actually hidden — an "expand"
  // that does nothing is worse than none.
  const canExpand = doc.passages.some(
    (p) => previewWindow(p.text, terms).text.length < p.text.length,
  );
  return (
    // `grp-passage` scopes the appended app.css rules to this component only.
    // WHY: the bare `.ctx`/`.tray`/`.doc` selectors this markup reuses are
    // shared with the browse page's report-family cards (Search.tsx), which
    // have the identical markup shape — unscoped rules here were winning
    // page-wide and silently reskinning the browse trays (review finding 1,
    // 2026-08-10). Verified unique: `grp-passage` has no other match in
    // Search.tsx.
    <article className="grp grp-passage">
      <button type="button" className="doc quoterow" onClick={() => onOpenPassage(best.chunk_id)}>
        <span className="doc-pub">{publisherLabel(doc.publisher)}</span>
        <div className="doc-main">
          <Quote text={best.text} terms={terms} expanded={expanded} />
        </div>
        <span className="doc-pill">
          {best.page === null ? "no page" : `p. ${best.page}`}
          <span className="go" aria-hidden="true">
            →
          </span>
        </span>
      </button>
      <div className="ctx">
        <div className="ctx-row">
          <span className="doc-pub">{publisherLabel(doc.publisher)}</span>
          <span className="badge">{doc.doc_title}</span>
          <span className="spacer" />
          {canExpand && (
            <button
              type="button"
              className={expanded ? "grp-more open" : "grp-more"}
              aria-expanded={expanded}
              onClick={() => setExpanded((v) => !v)}
            >
              {expanded ? "Show less" : "Show full passage"}
            </button>
          )}
          {rest.length > 0 && (
            <button
              type="button"
              className={trayOpen ? "grp-more open" : "grp-more"}
              aria-expanded={trayOpen}
              onClick={onToggleTray}
            >
              More from this document <ChevronIcon />
            </button>
          )}
        </div>
        {trayOpen && rest.length > 0 && (
          <div className="tray open">
            {rest.map((p) => (
              <PassageRow
                key={p.chunk_id}
                passage={p}
                terms={terms}
                expanded={expanded}
                onOpen={onOpenPassage}
              />
            ))}
          </div>
        )}
      </div>
    </article>
  );
}
