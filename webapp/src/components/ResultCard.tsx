import type { SearchResult } from "../api";
import { publisherLabel } from "./FilterBar";

// ResultCard — one document's worth of hits, using the mockup's grouped-result
// markup from webapp/reference/subpage-search_jlbc.html (spec S12):
//
//   .grp            the bordered, rounded group tile
//   .doc + .doc-ic / .doc-main / .doc-title / .doc-sub / .doc-pill
//                   the mockup's document row — used twice here: once as the
//                   group's document header, and once per chunk hit inside it
//   .ctx / .ctx-row / .badge / .spacer / .tray
//                   the dashed "context" box the mockup nests a group's extra
//                   hits inside
//   .rel / .bar     the mockup's relevance meter (`.doc .rel`)
//
// The mockup's search JavaScript was not vendored (only its HTML + CSS are in
// reference/), so this markup is reconstructed from what those CSS rules are
// shaped for: `.grp > .doc` has its bottom border removed — i.e. exactly ONE
// document row sits directly in the group — and `.ctx .tray .doc` re-pads and
// dash-separates the rows nested one level deeper. Hence: header row in `.grp`,
// chunk rows in `.ctx .tray`.

/** One document and every chunk of it that matched, best chunk first. */
export interface DocGroup {
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  doc_type: string;
  chunks: SearchResult[];
}

// The mockup's document glyph, from the `.doc-ic` rows and the `.subhero` chip in
// subpage-search_jlbc.html. Not extracted to a shared component the way the
// magnifier was: Home's fiscal-note card draws the same outline PLUS two inner
// lines, so they are different glyphs, and merging them would change one page's art.
function DocIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M6 2h9l5 5v15H6z" />
      <path d="M14 2v6h6" />
    </svg>
  );
}

export function ResultCard({ group }: { group: DocGroup }) {
  const hits = group.chunks.length;

  return (
    <article className="grp">
      {/* Document header. A <div>, not the mockup's <a>: opening the source PDF is
          Plan 4's viewer panel, and an anchor that navigates nowhere is worse than
          no anchor. app.css cancels the `.doc:hover` tint for this row so it does
          not advertise a click it cannot perform. */}
      <div className="doc">
        <span className="doc-ic">
          <DocIcon />
        </span>
        <div className="doc-main">
          <span className="doc-title">{group.doc_title}</span>
          {/* Raw doc_type — see the note in FilterBar.tsx: there is no display-name
              vocabulary for it, so the contract value is shown rather than invented prose. */}
          <span className="doc-sub">{group.doc_type}</span>
        </div>
        {/* Publisher + fiscal-year badges in the mockup's `.doc-pill` pills. The FY
            pill is omitted (not rendered as "FY null") when the document has no
            fiscal year — the API models it as nullable and the AFR-style documents
            legitimately have none. */}
        <span className="doc-pill">{publisherLabel(group.publisher)}</span>
        {group.fiscal_year !== null && (
          <span className="doc-pill">FY {group.fiscal_year}</span>
        )}
      </div>

      <div className="ctx">
        <div className="ctx-row">
          <span className="badge">
            <DocIcon />
            {hits === 1 ? "1 matching passage" : `${hits} matching passages`}
          </span>
          <span className="spacer" />
        </div>
        {/* `tray open`: the mockup's tray is display:none until an "open" class is
            added (it hid a group's extra hits behind a "more results" button).
            Here every hit is shown, because each one is a distinct page citation
            and that is what the user searched for — the collapse mechanism is left
            in the CSS untouched in case Plan 4 wants it back for huge groups. */}
        <div className="tray open">
          {group.chunks.map((chunk) => (
            // href="#" + data-chunk-id is the agreed stub: Plan 4 swaps this for
            // the PDF side panel keyed on that id. preventDefault stops the "#"
            // from scrolling the page to the top in the meantime.
            <a
              className="doc"
              href="#"
              data-chunk-id={chunk.chunk_id}
              key={chunk.chunk_id}
              onClick={(e) => e.preventDefault()}
            >
              <div className="doc-main">
                <span className="doc-sub">{chunk.snippet}</span>
              </div>
              {/* Relevance meter. The bar width treats the score as a 0–1 fraction
                  and clamps it: the stub provider emits 0.95…0.67, but the real
                  provider's scale is its own business, and an unclamped 1.4 would
                  paint outside the 50px track. The number is printed as-is (no
                  "%" — the scale is provider-defined, so a percentage would be a
                  claim the API does not make). */}
              <span className="rel" title="relevance score (provider-defined scale)">
                <span className="bar">
                  <i style={{ width: `${Math.min(Math.max(chunk.score, 0), 1) * 100}%` }} />
                </span>
                {chunk.score.toFixed(2)}
              </span>
              {/* Page badge. `page` is nullable in the contract; a chunk with no
                  page gets no pill rather than "p. null". */}
              {chunk.page !== null && <span className="doc-pill">p. {chunk.page}</span>}
            </a>
          ))}
        </div>
      </div>
    </article>
  );
}
