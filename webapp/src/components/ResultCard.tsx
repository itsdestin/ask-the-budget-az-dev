import { useState } from "react";
import type { SearchResult } from "../api";
import { familyOf, familyTitle } from "../reportFamilies";
import { publisherLabel } from "./FilterBar";

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
// .doc-sub / .doc-pill / .rel / .bar / .ctx / .ctx-row / .badge / .spacer /
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
  /** The mockup index's meta line; null when the doc isn't in it. */
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
  /** The report's full single-file PDF — null when no hand-verified URL exists. */
  fullPdfUrl: string | null;
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

/** The relevance meter, mockup order (percentage, then bar). The percentage is
 *  the sigmoid of the reranker's raw logit — the model's own probability
 *  reading — which is what makes "%" an honest claim here (the mockup's scores
 *  were already 0–1; ours are ±logits). */
function RelMeter({ score }: { score: number }) {
  const pct = Math.round((1 / (1 + Math.exp(-score))) * 100);
  return (
    <span className="rel" title="model confidence (best matching passage)">
      {pct}%
      <span className="bar">
        <i style={{ width: `${pct}%` }} />
      </span>
    </span>
  );
}

/** One document row — the mockup's docRow: a real link to the document's own
 *  PDF when the URL is known, an unlinked row otherwise (never a dead href). */
function DocRow({ doc, showPublisher = false }: { doc: DocGroup; showPublisher?: boolean }) {
  const best = doc.chunks[0];
  const body = (
    <>
      <span className="doc-ic">
        <DocIcon />
      </span>
      <div className="doc-main">
        <span className="doc-title">{doc.doc_title}</span>
        {/* The mockup's one-line meta ("category · doc_type · FY"), straight
            from its index via doc_meta. NOT the passage text — Destin
            (2026-07-30): rows read like the mockup's; retrieval passages are
            a tack-on behind the collapsed tray. Fallback when the doc isn't
            in the mockup index: our family vocabulary + year. */}
        <span className="doc-sub">
          {doc.doc_meta ?? familyTitle(familyOf(doc.doc_type), doc.fiscal_year)}
        </span>
      </div>
      <RelMeter score={best.score} />
      {showPublisher && <span className="doc-pill">{publisherLabel(doc.publisher)}</span>}
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

export function ResultCard({ family }: { family: FamilyGroup }) {
  // Both trays start CLOSED, like the mockup's "N more results" collapse
  // (Destin 2026-07-30: "the passages sections should begin collapsed").
  const [passagesOpen, setPassagesOpen] = useState(false);
  const [moreOpen, setMoreOpen] = useState(false);

  // The headline is the family's best document; the rest are siblings. Our
  // provider only returns per-document narrative sections (never whole-book
  // rows), so the mockup's agency-page promotion is satisfied structurally:
  // the best agency section IS the headline and the whole report is only ever
  // the .grp-full button — search.js's CASE B, always.
  const [headline, ...siblings] = family.docs;
  // The tray holds ALL of the headline's passages: since 2026-07-30 the doc
  // row shows the mockup's meta line (not passage text), so nothing in the
  // tray duplicates the row above it.
  const passages = headline.chunks;

  return (
    <article className="grp">
      <DocRow doc={headline} showPublisher />

      <div className="ctx">
        <div className="ctx-row">
          <span className="badge">
            <BookIcon />
            {/* "Part of the FY 2026 Baseline" for report families (mockup
                wording); a standalone document (AFR, budget bill) IS its
                family, so just name it. */}
            {family.docs.length > 1 || family.fullPdfUrl
              ? `Part of the ${family.title}`
              : family.title}
          </span>
          <span className="spacer" />
          {family.fullPdfUrl && (
            <a
              className="grp-full"
              href={family.fullPdfUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              <BookIcon />
              Full report (PDF)
            </a>
          )}
          {passages.length > 0 && (
            <button
              type="button"
              className={passagesOpen ? "grp-more open" : "grp-more"}
              aria-expanded={passagesOpen}
              onClick={() => setPassagesOpen((v) => !v)}
            >
              {passages.length === 1
                ? "1 matching passage"
                : `${passages.length} matching passages`}
              <ChevronIcon />
            </button>
          )}
        </div>
        {/* Collapsed until the button above opens it — the mockup's tray. The
            content is MOUNTED only while open (not merely display:none'd):
            hidden-but-present rows would still be found by tests and screen
            readers, and a wide query can carry hundreds of passages. */}
        {passagesOpen && (
        <div className="tray open">
          {passages.map((chunk) => (
            // href="#" + data-chunk-id is the agreed stub: Plan 4 swaps this
            // for the PDF side panel keyed on that id. Out of the tab order
            // until then.
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
              <RelMeter score={chunk.score} />
              {chunk.page !== null && <span className="doc-pill">p. {chunk.page}</span>}
            </a>
          ))}
        </div>
        )}

        {siblings.length > 0 && (
          <>
            <div className="ctx-row">
              <span className="badge">
                <DocIcon />
                More from this report
              </span>
              <span className="spacer" />
              <button
                type="button"
                className={moreOpen ? "grp-more open" : "grp-more"}
                aria-expanded={moreOpen}
                onClick={() => setMoreOpen((v) => !v)}
              >
                {siblings.length === 1 ? "1 more document" : `${siblings.length} more documents`}
                <ChevronIcon />
              </button>
            </div>
            {/* Sibling rows are linked docRows showing each document's best
                passage; their FURTHER passages aren't nested here (a tray
                inside a tray) — Plan 4's viewer is where a document's full
                match list belongs. Mounted only while open, same as above. */}
            {moreOpen && (
              <div className="tray open">
                {siblings.map((doc) => (
                  <DocRow key={doc.doc_id} doc={doc} />
                ))}
              </div>
            )}
          </>
        )}
      </div>
    </article>
  );
}
