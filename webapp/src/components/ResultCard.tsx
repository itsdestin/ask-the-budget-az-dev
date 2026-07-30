import { useEffect, useState } from "react";
import type { SearchResult } from "../api";
import { type ReportFormats } from "../reportFamilies";

// ResultCard — one REPORT FAMILY's worth of hits, restructured 2026-07-30 to
// match the WEBSITE MOCKUP'S search experience (Destin: "this ui should much
// more closely match the experience of using the old website mockup"), whose
// render logic lives in the vendored webapp/reference/assets/search/search.js
// (docRow / groupCard):
//
//   - The HEADLINE is the best-matching individual document (the agency
//     narrative section), rendered as a real LINK to its own source PDF —
//     search.js's groupCard deliberately promotes the per-agency page over the
//     whole book ("the more useful landing spot"). The URL comes from Plan 1's
//     documents.json sidecar via the API's doc_url field: the exact URL the
//     document was ingested from, no fuzzy matching (auditability invariant).
//   - The whole report stays ONE CLICK AWAY behind the `.grp-full` button
//     (a direct link to the single-file PDF, per Destin 2026-07-29).
//   - Everything below the headline starts COLLAPSED, like the mockup's
//     "N more results" tray: the headline's matching passages behind one
//     `.grp-more` toggle, sibling documents of the same report behind another.
//
// Mockup classes kept: .grp / .doc / .doc-ic / .doc-main / .doc-title /
// .doc-sub / .doc-pill / .ctx / .ctx-row / .badge / .spacer /
// .tray(.open) / .grp-full / .grp-more.

/** One document and every chunk of it that matched, best chunk first. */
export interface DocGroup {
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  doc_type: string;
  /** The document's own source PDF/DOCX URL (from documents.json); null when
   *  unknown — the row then renders unlinked rather than guessing. */
  doc_url: string | null;
  /** The mockup index's meta line. Kept in the contract for Plans 3/4 but NOT
   *  rendered — Destin (2026-07-30): the taglines mostly restated the title. */
  doc_meta: string | null;
  chunks: SearchResult[];
}

/** One report family (e.g. "FY 2027 Baseline") and its matched documents. */
export interface FamilyGroup {
  key: string;
  title: string;
  publisher: string;
  fiscal_year: number | null;
  docs: DocGroup[];
  /** Both whole-report format URLs (single-file PDF + linked TOC) — nulls when
   *  no hand-verified URLs exist (reportFamilies.ts). */
  formats: ReportFormats;
}

// The mockup's glyphs (search.js FILE_IC / BOOK_IC / CHEV_IC / OPEN_IC),
// paths verbatim.
function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M6 2h9l5 5v15H6z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

function BookIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M4 4h13a2 2 0 0 1 2 2v14H6a2 2 0 0 1-2-2z" />
      <path d="M4 18a2 2 0 0 1 2-2h13" />
    </svg>
  );
}

function ChevronIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="m6 9 6 6 6-6" />
    </svg>
  );
}

function OpenIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  );
}

/** One document row — the mockup's docRow reduced per Destin (2026-07-30):
 *  title + Open pill only. No sub-line (the mockup-index titles already
 *  carry agency/report/year), no publisher pill, no relevance display at all
 *  (Destin 2026-07-30 — ranking speaks through result ORDER).
 *  A real link to the document's own PDF when the URL is known; an unlinked
 *  row otherwise (never a dead href). */
function DocRow({ doc }: { doc: DocGroup }) {
  const body = (
    <>
      <span className="doc-ic">
        <DocIcon />
      </span>
      <div className="doc-main">
        <span className="doc-title">{doc.doc_title}</span>
      </div>
      {doc.doc_url && (
        <span className="doc-pill">
          <OpenIcon /> Open
        </span>
      )}
    </>
  );
  return doc.doc_url ? (
    <a className="doc" href={doc.doc_url} target="_blank" rel="noopener noreferrer">
      {body}
    </a>
  ) : (
    // No verified URL (stub rows, sidecar gap): an unlinked row, visually the
    // same minus the Open pill — a link that navigates nowhere would be worse.
    <div className="doc doc-unlinked">{body}</div>
  );
}

/** The mockup's report-format chooser (#reportModal): Linked Table of
 *  Contents vs Single File PDF, copy verbatim from the vendored
 *  subpage-search_jlbc.html. Rendered only while open. */
function ReportChooser({
  title,
  formats,
  onClose,
}: {
  title: string;
  formats: ReportFormats;
  onClose: () => void;
}) {
  // The mockup closes on Escape, backdrop click, the X, or either choice.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div
      className="report-modal open"
      role="dialog"
      aria-modal="true"
      aria-label="Open the full report"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <div className="modal">
        <div className="mhead">
          <span className="mic">
            <BookIcon />
          </span>
          <span className="mt">
            <b>{title}</b>
            <span>Choose how you'd like to open it</span>
          </span>
          <button className="mx" type="button" aria-label="Close" onClick={onClose}>
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" aria-hidden="true">
              <path d="M6 6l12 12M18 6 6 18" />
            </svg>
          </button>
        </div>
        <div className="mbody">
          {formats.linkedToc && (
            <a
              className="choice linked"
              href={formats.linkedToc}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onClose}
            >
              <span className="cic">
                {/* The mockup's link-chain glyph, path verbatim. */}
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
                  <path d="M10 13a5 5 0 0 0 7 0l2-2a5 5 0 0 0-7-7l-1 1" />
                  <path d="M14 11a5 5 0 0 0-7 0l-2 2a5 5 0 0 0 7 7l1-1" />
                </svg>
              </span>
              <span className="cc">
                <b>Linked Table of Contents</b>
                <p>An index page where each agency and section is a link that opens its own smaller PDF.</p>
                <span className="best">
                  Best for jumping straight to one agency or section without downloading the whole report.
                </span>
              </span>
              <span className="carr">
                <OpenIcon />
              </span>
            </a>
          )}
          {formats.singleFile && (
            <a
              className="choice single"
              href={formats.singleFile}
              target="_blank"
              rel="noopener noreferrer"
              onClick={onClose}
            >
              <span className="cic">
                <DocIcon />
              </span>
              <span className="cc">
                <b>Single File PDF</b>
                <p>The complete report as one document — every agency and summary in a single PDF.</p>
                <span className="best">
                  Best for reading start to finish, searching the whole report, or printing. Largest download.
                </span>
              </span>
              <span className="carr">
                <OpenIcon />
              </span>
            </a>
          )}
        </div>
      </div>
    </div>
  );
}

export function ResultCard({ family }: { family: FamilyGroup }) {
  // Both trays start CLOSED, like the mockup's "N more results" collapse
  // (Destin 2026-07-30: "the passages sections should begin collapsed").
  const [passagesOpen, setPassagesOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);
  const [chooserOpen, setChooserOpen] = useState(false);

  // The headline is the family's best document; the rest are siblings. Our
  // provider only returns per-document narrative sections (never whole-book
  // rows), so the mockup's agency-page promotion is satisfied structurally:
  // the best agency section IS the headline; the whole report lives in the
  // report card below — search.js's CASE B, always.
  const [headline, ...siblings] = family.docs;
  const passages = headline.chunks;

  const { singleFile, linkedToc } = family.formats;
  const bothFormats = Boolean(singleFile && linkedToc);
  const oneFormat = singleFile ?? linkedToc;
  const hasReportCard = Boolean(oneFormat) || siblings.length > 0;

  return (
    <article className="grp">
      <DocRow doc={headline} />

      {/* Card layout per Destin (2026-07-30): the passages dropdown is its own
          dashed card; the "Part of X / More from this report" card — with the
          Full report action — sits at the BOTTOM of the result. */}
      {passages.length > 0 && (
        <div className="ctx">
          <div className="ctx-row">
            <span className="badge">
              <DocIcon />
              Matching passages
            </span>
            <span className="spacer" />
            <button
              type="button"
              className={passagesOpen ? "grp-more open" : "grp-more"}
              aria-expanded={passagesOpen}
              onClick={() => setPassagesOpen((v) => !v)}
            >
              {passages.length === 1 ? "1 passage" : `${passages.length} passages`}
              <ChevronIcon />
            </button>
          </div>
          {/* Collapsed until opened; MOUNTED only while open (hidden-but-
              present rows would still be found by tests and screen readers,
              and a wide query can carry hundreds of passages). */}
          {passagesOpen && (
            <div className="tray open">
              {passages.map((chunk) => (
                // href="#" + data-chunk-id is the agreed stub: Plan 4 swaps
                // this for the PDF side panel keyed on that id.
                <a
                  className="doc"
                  href="#"
                  data-chunk-id={chunk.chunk_id}
                  key={chunk.chunk_id}
                  onClick={(e) => e.preventDefault()}
                  tabIndex={-1}
                >
                  <div className="doc-main">
                    <span className="doc-sub">{chunk.snippet}</span>
                  </div>
                  {chunk.page !== null && <span className="doc-pill">p. {chunk.page}</span>}
                </a>
              ))}
            </div>
          )}
        </div>
      )}

      {hasReportCard && (
        <div className="ctx">
          <div className="ctx-row">
            <span className="badge">
              <BookIcon />
              {`Part of the ${family.title}`}
            </span>
            <span className="spacer" />
            {siblings.length > 0 && (
              <button
                type="button"
                className={moreOpen ? "grp-more open" : "grp-more"}
                aria-expanded={moreOpen}
                onClick={() => setMoreOpen((v) => !v)}
              >
                {siblings.length === 1 ? "1 more document" : `${siblings.length} more documents`}
                <ChevronIcon />
              </button>
            )}
            {/* The mockup's Full report behavior (search.js openReport): both
                formats -> the chooser modal; exactly one -> open it directly,
                a one-option chooser would be pointless. */}
            {bothFormats ? (
              <button type="button" className="grp-full" onClick={() => setChooserOpen(true)}>
                <BookIcon />
                Full report
              </button>
            ) : oneFormat ? (
              <a className="grp-full" href={oneFormat} target="_blank" rel="noopener noreferrer">
                <BookIcon />
                Full report
              </a>
            ) : null}
          </div>
          {/* Sibling rows are linked docRows; their further passages aren't
              nested here — Plan 4's viewer owns a document's full match list.
              Mounted only while open, same as the passages tray. */}
          {moreOpen && (
            <div className="tray open">
              {siblings.map((doc) => (
                <DocRow key={doc.doc_id} doc={doc} />
              ))}
            </div>
          )}
        </div>
      )}

      {chooserOpen && (
        <ReportChooser
          title={family.title}
          formats={family.formats}
          onClose={() => setChooserOpen(false)}
        />
      )}
    </article>
  );
}
