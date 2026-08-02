// CitationChip — the inline marker rendered on an assistant turn's cited
// claims. Hover surfaces a tooltip with document title, page, fiscal year and
// the verbatim source quote. Click publishes the citation on the citation bus;
// the source viewer (Task 11) subscribes and scrolls/highlights.
//
// The system prompt promises the analyst that "the interface parses every
// cite() call and renders a marker on the claim, linking it to its source
// page in the document viewer." This component is the marker AND the link:
// `bus.select(citation)` is the whole coupling, so Task 11 attaches a viewer
// by calling `useCitationSelected(...)` and changes nothing here.
//
// Ported from web/components/CitationChip.tsx.

import { useState } from "react";

import { formatCopyCitation, type Citation } from "./citation-extract.js";
import { useCitationBus } from "./citation-context.js";
import type { AnnotationFigure } from "./citation-annotation.js";

interface Props {
  citation: Citation;
  /** When provided, the chip wraps this text inline with an underline and
   *  appends a small superscript chip number. Used by CitedMarkdownContent so
   *  cited claims are highlighted in place rather than as a footer row.
   *  Without it, falls back to the pill-only rendering used for unmatched
   *  citations. */
  inlineText?: string;
  /** The mark's position in the answer's ONE reading-order sequence. Falls
   *  back to `citation.index` (this citation's position among the model's
   *  own citations) only when the renderer didn't supply one — those two
   *  sequences diverge as soon as system-linked figures share the page. */
  displayIndex?: number;
}

export default function CitationChip({
  citation,
  inlineText,
  displayIndex,
}: Props) {
  const shown = displayIndex ?? citation.index;
  const [open, setOpen] = useState(false);
  // `firing` drives the 250ms pop that plays on click — a brief scale + glow
  // confirms the click registered and the source panel is opening/scrolling.
  const [firing, setFiring] = useState(false);
  const bus = useCitationBus();

  const verbatim = citation.confidence === "verbatim";
  const failed = citation.failureReason !== undefined;
  // Three visual states: failed (red ✗ — the server rejected the cite, so the
  // claim is UNCITED), verbatim (blue ✓ — strict source match), paraphrase
  // (neutral ≈ — supported but reworded). Failed wins over the confidence
  // variant; "this claim has no valid citation" outranks everything else.
  const tone = failed ? "is-failed" : verbatim ? "is-verbatim" : "is-paraphrase";
  const glyph = failed ? "✗" : verbatim ? "✓" : "≈";

  const handleChipClick = () => {
    bus.select(citation);
    setFiring(true);
    setTimeout(() => setFiring(false), 250);
  };

  // Hover tracking is on the WRAPPING SPAN, not the button. The tooltip sits
  // 4px above the chip — tracking hover on the button would fire mouseleave
  // as the cursor crossed that gap on its way to the tooltip, closing it
  // before the user could reach "Copy citation". The span bounds both.
  const fireClass = firing ? " cite-chip-firing" : "";

  if (inlineText !== undefined) {
    return (
      <span
        className="chat-cite-wrap"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <button
          type="button"
          onClick={handleChipClick}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          className={`cite-chip${fireClass} chat-cite-inline ${tone}`}
          aria-label={`Citation ${shown} (${citation.confidence}): ${inlineText}`}
        >
          {inlineText}
          <sup className={`chat-cite-sup ${tone}`} aria-hidden>
            {glyph}
            {shown}
          </sup>
        </button>
        {open && <CitationTooltip citation={citation} />}
      </span>
    );
  }

  return (
    <span
      className="chat-cite-pill-wrap"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={handleChipClick}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={`cite-chip${fireClass} chat-cite-pill ${tone}`}
        aria-label={`Citation ${shown} (${citation.confidence})`}
      >
        <span aria-hidden>{glyph}</span>
        <span data-testid="prose-chip">{shown}</span>
      </button>
      {open && <CitationTooltip citation={citation} />}
    </span>
  );
}

/** The chip for a figure the SYSTEM linked, as opposed to a claim the model
 *  cited. Three states, and the difference between them is the whole point
 *  of Decision 1 in the design: a computed total that renders like a sourced
 *  figure is what erodes trust in a table.
 *
 *  - linked      — opens the primary source, lists outranked editions
 *  - derived     — says what it was computed FROM, offers no source link
 *  - unverified  — says plainly that it was not found in the sources
 */
export function FigureChip({
  figure,
  displayIndex,
}: {
  figure: AnnotationFigure;
  displayIndex?: number;
}) {
  // The annotation's `index` is the figure's position among FIGURES; the
  // number on screen must be its position among ALL marks, or two
  // sequences collide on one answer.
  const shown = displayIndex ?? figure.index;
  const [open, setOpen] = useState(false);
  const [firing, setFiring] = useState(false);
  const bus = useCitationBus();

  const tone =
    figure.verdict === "linked"
      ? "is-verbatim"
      : figure.verdict === "derived"
        ? "is-paraphrase"
        : "is-failed";
  // Two test hooks, deliberately on different elements. The BUTTON is
  // always "citation-chip", so a test can count every chip on the page in
  // reading order — that count is the reported defect (2 chips on a
  // 10-row table). The WRAPPER carries the verdict-and-index marker, so a
  // test can also assert that figure 3 specifically renders as derived.
  // One element cannot answer both questions: data-testid is single-valued.
  const wrapperTestId = `citation-chip-${figure.verdict}-${shown}`;

  const handleClick = () => {
    // Only a linked figure has somewhere to go. A derived or unverified
    // chip must not open a viewer — claiming a source it hasn't got is
    // exactly the failure this design exists to remove.
    if (figure.verdict === "linked" && figure.primary) {
      const p = figure.primary;
      const selected: Citation = {
        chunkId: p.chunkId,
        claimSpan: figure.text,
        confidence: "verbatim",
        index: figure.index,
        spanStart: p.start,
        spanEnd: p.end,
        sourceText: p.sourceText,
        // PdfViewer opens nothing without resolved.docId + pageStart — it
        // renders "Couldn't open source PDF" instead, which is what every
        // figure chip did until the annotation started carrying these.
        // `text` is absent by design (the annotation does not ship chunk
        // bodies), so the highlighter works from `sourceText`.
        resolved: p.docId
          ? {
              docId: p.docId,
              docTitle: p.docTitle ?? "",
              publisher: p.publisher ?? "",
              docType: p.docType ?? "",
              fiscalYear: p.fiscalYear,
              pageStart: p.pageStart,
              pageEnd: p.pageEnd,
              bbox: p.bbox,
              text: "",
            }
          : undefined,
      };
      bus.select(selected);
    }
    setFiring(true);
    setTimeout(() => setFiring(false), 250);
  };

  return (
    <span
      className="chat-cite-pill-wrap"
      data-testid={wrapperTestId}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        data-testid="citation-chip"
        data-figure-verdict={figure.verdict}
        onClick={handleClick}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={`cite-chip${firing ? " cite-chip-firing" : ""} chat-cite-pill ${tone}`}
        aria-label={`Figure ${shown}, ${figure.verdict}: ${figure.text}`}
      >
        {shown}
      </button>
      {open && <FigureTooltip figure={figure} />}
    </span>
  );
}

function FigureTooltip({ figure }: { figure: AnnotationFigure }) {
  if (figure.verdict === "derived") {
    const inputs = figure.derivedFrom.map((n) => `[${n}]`).join(" and ");
    return (
      <div role="tooltip" className="chat-cite-tooltip">
        <div className="chat-cite-tooltip-head">
          <span className="chat-cite-tooltip-index">[{figure.index}]</span>
          <span className="chat-cite-tooltip-title">Computed figure</span>
        </div>
        <div className="chat-cite-claim">
          {inputs ? `Computed from ${inputs}` : "Computed from other figures"}
        </div>
      </div>
    );
  }
  if (figure.verdict === "unverified") {
    return (
      <div role="tooltip" className="chat-cite-tooltip">
        <div className="chat-cite-tooltip-head">
          <span className="chat-cite-tooltip-index">[{figure.index}]</span>
          <span className="chat-cite-tooltip-title">No source found</span>
        </div>
        <div className="chat-cite-fail">
          <div>This figure was not found in the retrieved sources.</div>
        </div>
      </div>
    );
  }
  return (
    <div role="tooltip" className="chat-cite-tooltip">
      <div className="chat-cite-tooltip-head">
        <span className="chat-cite-tooltip-index">[{figure.index}]</span>
        <span className="chat-cite-tooltip-title">
          {figure.primary ? `chunk ${figure.primary.chunkId}` : "source"}
        </span>
      </div>
      {figure.primary && (
        <blockquote className="chat-cite-quote">
          {figure.primary.sourceText}
        </blockquote>
      )}
      {figure.additional.length > 0 && (
        // Outranked editions of the same material. Shown rather than
        // hidden: the analyst decides whether the Baseline agreeing with
        // the Approps Report matters to their question.
        <div className="chat-cite-claim">
          <span className="chat-cite-claim-label">Also appears in:</span>{" "}
          {figure.additional.map((a) => a.chunkId).join(", ")}
        </div>
      )}
    </div>
  );
}

function CitationTooltip({ citation }: Props) {
  const [copied, setCopied] = useState(false);
  const r = citation.resolved;
  const copyText = formatCopyCitation(citation);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(copyText);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be blocked — silently ignore.
    }
  };

  // Verbatim quote pulled from the resolved chunk text using the
  // model-supplied span. Empty when the chunk text isn't available (no
  // retrieve in this turn surfaced it).
  let verbatimQuote = "";
  if (r?.text) {
    const start = Math.max(0, citation.spanStart);
    const end = Math.min(r.text.length, citation.spanEnd);
    if (end > start) verbatimQuote = r.text.slice(start, end);
  }

  return (
    <div
      role="tooltip"
      className="chat-cite-tooltip"
      // The button sits inside a span; the tooltip lives in the same span so
      // mouseleave on the button still fires before the tooltip can react.
      onMouseEnter={(e) => e.stopPropagation()}
    >
      <div className="chat-cite-tooltip-head">
        <span className="chat-cite-tooltip-index">[{citation.index}]</span>
        <span className="chat-cite-tooltip-title">
          {r?.docTitle || `chunk ${citation.chunkId}`}
        </span>
      </div>
      <div className="chat-cite-tooltip-meta">
        {r?.pageStart != null && (
          <span>
            {r.pageEnd != null && r.pageEnd !== r.pageStart
              ? `pp. ${r.pageStart}–${r.pageEnd}`
              : `p. ${r.pageStart}`}
          </span>
        )}
        {r?.fiscalYear != null && <span>FY{r.fiscalYear}</span>}
        {r?.publisher && <span>· {r.publisher}</span>}
        <span className="chat-cite-tooltip-state">
          {citation.failureReason ? "uncited" : citation.confidence}
        </span>
      </div>
      {citation.failureReason && (
        // Surface the server's rejection reason so the analyst knows WHY the
        // citation didn't validate. Plain text, no copy affordance — there is
        // nothing to copy when the cite isn't valid.
        <div className="chat-cite-fail">
          <div className="chat-cite-fail-label">Citation failed</div>
          <div>{citation.failureReason}</div>
        </div>
      )}
      {verbatimQuote && !citation.failureReason && (
        <blockquote className="chat-cite-quote">{verbatimQuote}</blockquote>
      )}
      <div className="chat-cite-claim">
        <span className="chat-cite-claim-label">Claim:</span>{" "}
        <em>{citation.claimSpan}</em>
      </div>
      {!citation.failureReason && (
        <button type="button" onClick={handleCopy} className="chat-cite-copy">
          {copied ? "Copied!" : `Copy citation: ${copyText || "—"}`}
        </button>
      )}
    </div>
  );
}
