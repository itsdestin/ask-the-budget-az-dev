// Side-panel PDF viewer for AI Mode. Subscribes to citation-bus selections
// and renders the cited page (SourceView -> PdfPage) with the highlight
// overlay, per spec §10.2.
//
// This component IS the mechanism behind the promise the system prompt makes
// to the model — "The interface parses every cite() call and renders a marker
// on the claim, linking it to its source page in the document viewer."
// Task 10 wired the chip to `bus.select(citation)`; the subscription below is
// the other end of that wire, and the only integration point between the chat
// surface and this one.
//
// Ported from web/components/PdfViewer.tsx (Plan 4 Task 11). Deltas: the
// `Loaded` body moved into SourceView so the search page can reuse it,
// next/dynamic became React.lazy (inside SourceView), and the Tailwind
// classes became `pdf-`-prefixed semantic ones.
//
// Task 15: `onClose` is threaded through from AiModePanel, which used to
// float its own close button on top of this whole panel. That button now
// lives INSIDE SourceView's merged header for the loaded state; the empty
// and unresolved states below have no header row, so they keep a floating
// variant (`FloatingClose`) — the panel must be closable in every state.

import { useRef, useState } from "react";

import * as api from "../api";
import type { ChunkLocate } from "../api";
import type { Citation } from "../chat/citation-extract";
import { formatCopyCitation, normalizeForMatch } from "../chat/citation-extract";
import { spanKeyOf, useCitationBus, useCitationSelected } from "../chat/citation-context";
import Mascot from "../chat/mascot/Mascot";
import { SourceView } from "./SourceView";

// H5 as amended: PdfViewer checks at click time whether the citation's source
// still resolves, and treats TWO shapes as unresolvable:
//   - 404 (the chunk is gone — the document was deleted or the corpus
//     re-ingested with different chunking)
//   - 200 but the stored quote is no longer in the returned text (the document
//     was re-ingested and this passage moved or changed)
// A 503 (share offline) is NOT reported as stale — "we cannot tell" is a worse
// lie than saying nothing. The existing error surface handles it.
//
// The verdict is published on the citation bus so the chip can mark itself
// (Invariant 2: a citation that no longer resolves is VISIBLE, never silently
// dropped).

interface PdfViewerProps {
  onClose?: () => void;
  /** Which corpus to fetch chunks from. AiModePanel passes this so the
   *  staleness check hits the right /api/chunks/{id}?corpus=… endpoint. */
  corpus?: string;
}

export default function PdfViewer({ onClose, corpus = "budget" }: PdfViewerProps = {}) {
  const [selected, setSelected] = useState<Citation | null>(null);
  // Track the last-clicked unresolved citation so we can show
  // *which* citation we couldn't load, instead of looking
  // identical to the no-clicks-yet state.
  const [unresolvedClick, setUnresolvedClick] = useState<Citation | null>(null);
  // H5: a citation whose source no longer resolves (gone or moved).
  const [staleCitation, setStaleCitation] = useState<{ citation: Citation; reason: "gone" | "moved" } | null>(null);
  // Spec L2/L3: the locate endpoint's answer for the selected citation,
  // plus the chunk text the click-time check already fetched (figure
  // chips carry no chunk body in their annotation, so without this the
  // cited-text panel would say "unavailable" on exactly the chips that
  // have a source). Both ride the same staleness guard as the check.
  const [locate, setLocate] = useState<ChunkLocate | null>(null);
  const [fetchedText, setFetchedText] = useState("");

  const bus = useCitationBus();

  // Guard the async staleness check: two fast citation clicks race, and the
  // panel must render the verdict for the citation the analyst clicked LAST.
  // A request sequence number ignores any answer that is not the latest.
  const checkSeqRef = useRef(0);

  useCitationSelected((citation) => {
    if (!citation.resolved?.docId || citation.resolved.pageStart == null) {
      // No source metadata for this chunk — likely the retrieve()
      // result didn't carry doc_id/page_start, or the chunk_id
      // came from a previous turn the renderer doesn't have on hand.
      // Surface that explicitly so the user knows the click landed.
      setUnresolvedClick(citation);
      setSelected(null);
      setStaleCitation(null);
      return;
    }
    setUnresolvedClick(null);
    setStaleCitation(null);
    setLocate(null);
    setFetchedText("");
    setSelected(citation);

    // H5: check at click time whether the chunk still resolves. Nothing
    // is fetched until a citation is selected — verifying on open would
    // cost one round-trip per citation, which is what H2 exists to avoid.
    // A direct fetch rather than api.chunk because we need the STATUS CODE
    // to distinguish 404 (chunk gone) from 503 (share offline) — api.chunk
    // wraps the error and loses the status.
    const seq = ++checkSeqRef.current;
    void (async () => {
      try {
        const chunkUrl =
          `/api/chunks/${encodeURIComponent(citation.chunkId)}?corpus=${encodeURIComponent(corpus)}`;
        const resp = await fetch(chunkUrl);
        if (seq !== checkSeqRef.current) return; // a later click won
        if (!resp.ok) {
          if (resp.status === 404) {
            setStaleCitation({ citation, reason: "gone" });
            setSelected(null);
            bus.markUnresolvable(citation.chunkId, "gone");
          }
          // 503 or any other failure: NOT a stale citation. "We cannot
          // tell" is better than a false "your source is dead." Leave
          // the existing state — SourceView will surface its own error.
          return;
        }
        const chunk = await resp.json();
        if (seq !== checkSeqRef.current) return; // a later click won
        // 200 + text: check if the cited span is still in the chunk.
        // The cited span is the slice of the STORED resolved text —
        // what the model saw when it cited. If the document was
        // re-ingested, the chunk may still exist but carry different
        // text, so the quote would be gone even though the chunk is not.
        const r = citation.resolved;
        if (r?.text) {
          const start = Math.max(0, citation.spanStart);
          const end = Math.min(r.text.length, citation.spanEnd);
          const storedQuote = r.text.slice(start, end);
          if (storedQuote) {
            const storedNorm = normalizeForMatch(storedQuote).normalized.trim();
            const currentNorm = normalizeForMatch(chunk.text || "").normalized;
            if (storedNorm && !currentNorm.includes(storedNorm)) {
              // The chunk exists but the cited passage is no longer in it.
              setStaleCitation({ citation, reason: "moved" });
              setSelected(null);
              // Span-scoped: only THIS quote is missing from the re-ingested
              // chunk. A sibling citation into the same chunk may be fine.
              bus.markUnresolvable(citation.chunkId, "moved", spanKeyOf(citation));
              return;
            }
          }
        }
        // 200 + quote present (or no stored quote to compare): the source
        // still resolves. Clear any stale brand this citation was carrying —
        // a transient 404 (e.g. an ingest mid-rewrite) may have marked it
        // "gone" earlier, and a false "your source is dead" that never clears
        // is its own kind of lie. The existing Loaded path is otherwise
        // unchanged.
        // Span-scoped for the same reason `moved` is: this clears the mark on
        // the citation we actually re-checked, and NOT on a sibling into the
        // same chunk whose own quote really is gone.
        bus.markUnresolvable(citation.chunkId, "resolved", spanKeyOf(citation));

        // Spec L2/L3: the click-time check has the chunk body in hand
        // anyway, so keep it for the cited-text panel (figure chips'
        // annotations carry no chunk text by design), and ask the locate
        // endpoint where the cited value sits on the page. The search
        // text is the source-side rendering when the chip has one
        // (figure chips), else the cited slice of the stored chunk text
        // (prose cites). A null/none answer leaves today's chain intact.
        setFetchedText(typeof chunk.text === "string" ? chunk.text : "");
        const locateText =
          citation.sourceText ??
          (citation.resolved?.text
            ? citation.resolved.text.slice(
                Math.max(0, citation.spanStart),
                Math.min(citation.resolved.text.length, citation.spanEnd),
              )
            : "");
        const located = await api.chunkLocate(
          citation.chunkId,
          locateText,
          corpus,
        );
        if (seq !== checkSeqRef.current) return; // a later click won
        setLocate(located);
      } catch {
        if (seq !== checkSeqRef.current) return;
        // Network error — NOT a stale citation. Same posture as a 503:
        // "we cannot tell" beats a false positive.
      }
    })();
  });

  if (staleCitation)
    return <StaleState citation={staleCitation.citation} reason={staleCitation.reason} onClose={onClose} />;
  if (selected)
    return (
      <Loaded
        citation={selected}
        locate={locate}
        fetchedText={fetchedText}
        onClose={onClose}
      />
    );
  if (unresolvedClick)
    return <UnresolvedState citation={unresolvedClick} onClose={onClose} />;
  return <EmptyState onClose={onClose} />;
}

/** Floating × — the same class + markup AiModePanel used to render directly
 *  over this whole panel before Task 15 moved the loaded-state close button
 *  into SourceView's merged header. The empty and unresolved states have no
 *  header row to put a close button in, so they keep this absolutely
 *  positioned variant instead (`.ai-source-close`'s own CSS positions it
 *  top-right of `.pdf-empty`, which Task 15 gave `position: relative`). */
function FloatingClose({ onClose }: { onClose: () => void }) {
  return (
    <button
      type="button"
      className="ai-source-close"
      aria-label="Close source panel"
      onClick={onClose}
    >
      <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
        <path
          d="M3 3l10 10M13 3L3 13"
          stroke="currentColor"
          strokeWidth="2"
          strokeLinecap="round"
          fill="none"
        />
      </svg>
    </button>
  );
}

function EmptyState({ onClose }: { onClose?: () => void }) {
  return (
    <div className="pdf-empty">
      {onClose && <FloatingClose onClose={onClose} />}
      <div className="pdf-empty-inner">
        {/* Mascot with clipboard pose — welcoming prompt to click a citation. */}
        <Mascot pose="clipboard" size="hero" />
        <p>Click a citation to see its source.</p>
      </div>
    </div>
  );
}

function UnresolvedState({
  citation,
  onClose,
}: {
  citation: Citation;
  onClose?: () => void;
}) {
  return (
    <div className="pdf-empty">
      {onClose && <FloatingClose onClose={onClose} />}
      <div className="pdf-unresolved">
        {/* Task 15: plain-language headline first; the raw chunk_id and chip
            index used to lead the copy, which reads as an internal error
            message rather than something a non-developer analyst can act
            on. They still appear below — an analyst reporting a bad
            citation needs something concrete to quote. */}
        <h2>Couldn&rsquo;t find the source page</h2>
        <p>
          This citation points at a passage the current view can&rsquo;t
          locate — usually because it comes from an earlier question, or
          because the source is a Word document rather than a PDF.
        </p>
        {citation.claimSpan && (
          <blockquote className="pdf-unresolved-quote">
            {citation.claimSpan}
          </blockquote>
        )}
        <p className="pdf-unresolved-note">
          Ask the question again to refresh the sources. Reference: chip{" "}
          <span className="pdf-mono">[{citation.index}]</span>, passage{" "}
          <span className="pdf-mono">{citation.chunkId}</span>.
        </p>
      </div>
    </div>
  );
}

/** H5: a citation whose source no longer resolves. Two reasons:
 *  `gone` — the chunk was deleted (document removed or corpus re-ingested
 *  with different chunking); `moved` — the chunk exists but the cited
 *  passage is no longer in it (document re-ingested, passage changed).
 *  Invariant 2: the verified quote IS still shown — it WAS verified when
 *  written, which is a fact about the past, not a claim about the present. */
function StaleState({
  citation,
  reason,
  onClose,
}: {
  citation: Citation;
  reason: "gone" | "moved";
  onClose?: () => void;
}) {
  return (
    <div className="pdf-empty">
      {onClose && <FloatingClose onClose={onClose} />}
      <div className="pdf-unresolved">
        <h2>Source no longer available</h2>
        <p>
          {reason === "gone"
            ? "The document this citation came from is no longer in the system — it may have been removed or replaced."
            : "This document was updated since the citation was made, and the passage it pointed at has moved or changed."}
        </p>
        {/* The verified quote is still shown — it was verified when written. */}
        {citation.resolved?.text && (() => {
          const start = Math.max(0, citation.spanStart);
          const end = Math.min(citation.resolved.text.length, citation.spanEnd);
          const quote = citation.resolved.text.slice(start, end);
          return quote ? (
            <blockquote className="pdf-unresolved-quote">{quote}</blockquote>
          ) : null;
        })()}
        {citation.claimSpan && (
          <div className="pdf-unresolved-note">
            <strong>Claim:</strong> {citation.claimSpan}
          </div>
        )}
        <p className="pdf-unresolved-note">
          Reference: chip{" "}
          <span className="pdf-mono">[{citation.index}]</span>, passage{" "}
          <span className="pdf-mono">{citation.chunkId}</span>.
        </p>
      </div>
    </div>
  );
}

function Loaded({
  citation,
  locate,
  fetchedText,
  onClose,
}: {
  citation: Citation;
  locate: ChunkLocate | null;
  fetchedText: string;
  onClose?: () => void;
}) {
  const r = citation.resolved!;
  // A locate answer only overrides the stored page/rects when it actually
  // FOUND the value; basis "none" keeps today's chain exactly as is.
  const found = locate && locate.basis !== "none" ? locate : null;
  return (
    <SourceView
      docId={r.docId}
      page={r.pageStart!}
      bbox={r.bbox}
      // Figure chips carry no chunk body in their annotation (by design);
      // the click-time check's fetch hydrates the cited-text panel so it
      // never says "unavailable" on a chip that has a source.
      chunkText={r.text || fetchedText}
      spanStart={citation.spanStart}
      spanEnd={citation.spanEnd}
      sourceText={citation.sourceText}
      serverPage={found?.page ?? null}
      serverRects={found?.rects}
      docTitle={r.docTitle || r.docId}
      fiscalYear={r.fiscalYear}
      sourceLabel={formatCopyCitation(citation)}
      onClose={onClose}
    />
  );
}
