import type { SearchResult } from "../api";
import { publisherLabel } from "./FilterBar";

// ResultCard — one REPORT FAMILY's worth of hits (Destin, 2026-07-29: results
// group by fiscal year + document type, the way the mockup's engine grouped
// under annual reports). Mockup markup from subpage-search_jlbc.html (S12):
//
//   .grp            the bordered, rounded group tile — one per report family
//   .grp > .doc     the family header row (.doc-ic / .doc-title / .doc-sub /
//                   .doc-pill), plus the mockup's `.grp-full` "Full report"
//                   action — here a real link to the report's single-file PDF
//                   when a hand-verified URL exists (reportFamilies.ts)
//   .ctx / .ctx-row / .badge / .spacer / .tray
//                   the dashed context box; one .ctx-row per matched DOCUMENT
//                   (the per-agency page), its chunk hits in the .tray below
//   .rel / .bar     the mockup's relevance meter
//
// This is the mockup's own hierarchy read correctly: its engine collapsed a
// Baseline year's ~110 per-agency documents into one group, with the matched
// sub-documents as rows inside it (see the vendored search.js, familyOf).

/** One document and every chunk of it that matched, best chunk first. */
export interface DocGroup {
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  doc_type: string;
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

// The mockup's document glyph, from the `.doc-ic` rows in subpage-search_jlbc.html.
function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M6 2h9l5 5v15H6z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

export function ResultCard({ family }: { family: FamilyGroup }) {
  const passages = family.docs.reduce((n, d) => n + d.chunks.length, 0);

  return (
    <article className="grp">
      {/* Family header. A <div>, not an anchor: the family itself isn't a
          document. The one action lives in the explicit button beside it. */}
      <div className="doc">
        <span className="doc-ic">
          <DocIcon />
        </span>
        <div className="doc-main">
          <span className="doc-title">{family.title}</span>
          <span className="doc-sub">
            {family.docs.length === 1 ? "1 document" : `${family.docs.length} documents`} ·{" "}
            {passages === 1 ? "1 matching passage" : `${passages} matching passages`}
          </span>
        </div>
        <span className="doc-pill">{publisherLabel(family.publisher)}</span>
        {/* The mockup's `.grp-full` "Full report" action. The mockup opened a
            format-chooser modal; per Destin (2026-07-29) this links straight to
            the report's full single-file PDF. Rendered ONLY when a hand-verified
            URL exists for this family+year (reportFamilies.ts) — no button is
            better than a guessed link. External: azjlbc.gov. */}
        {family.fullPdfUrl && (
          <a
            className="grp-full"
            href={family.fullPdfUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            <DocIcon />
            Full report (PDF)
          </a>
        )}
      </div>

      <div className="ctx">
        {family.docs.map((doc) => (
          <div key={doc.doc_id}>
            {/* One labelled row per matched document (the per-agency page). */}
            <div className="ctx-row">
              <span className="badge">
                <DocIcon />
                {doc.doc_title}
              </span>
              <span className="spacer" />
              {doc.chunks.length > 1 && (
                <span className="doc-pill">{doc.chunks.length} passages</span>
              )}
            </div>
            {/* `tray open`: the mockup's tray is display:none until opened (it hid
                extra hits behind a "more results" button). Every hit shows here —
                each is a distinct page citation, which is what the user searched
                for. The collapse CSS stays untouched in case Plan 4 wants it. */}
            <div className="tray open">
              {doc.chunks.map((chunk) => (
                // href="#" + data-chunk-id is the agreed stub: Plan 4 swaps this
                // for the PDF side panel keyed on that id.
                <a
                  className="doc"
                  href="#"
                  data-chunk-id={chunk.chunk_id}
                  key={chunk.chunk_id}
                  onClick={(e) => e.preventDefault()}
                  // Out of the tab order until Plan 4 wires the viewer: keyboard
                  // users would otherwise tab through one focusable do-nothing
                  // link per passage. Remove when the click does something.
                  tabIndex={-1}
                >
                  <div className="doc-main">
                    <span className="doc-sub">{chunk.snippet}</span>
                  </div>
                  {/* Relevance meter. The real provider emits raw cross-encoder
                      LOGITS (roughly -10..10, negatives normal) — a plain 0–1
                      clamp would pin every real bar at 100%. The sigmoid is that
                      model's own probability reading of its logit, so the bar
                      shows an honest 0–1 without inventing a scale (and the
                      stub's 0.67–0.95 fixture scores land at sensible 66–72%
                      widths through the same formula). The printed number stays
                      the RAW score — no "%", that would be a claim the API does
                      not make. */}
                  <span className="rel" title="relevance score (provider-defined scale)">
                    <span className="bar">
                      <i style={{ width: `${(1 / (1 + Math.exp(-chunk.score))) * 100}%` }} />
                    </span>
                    {chunk.score.toFixed(2)}
                  </span>
                  {/* `page` is nullable; a chunk with no page gets no pill rather
                      than "p. null". */}
                  {chunk.page !== null && <span className="doc-pill">p. {chunk.page}</span>}
                </a>
              ))}
            </div>
          </div>
        ))}
      </div>
    </article>
  );
}
