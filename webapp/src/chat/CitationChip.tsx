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

interface Props {
  citation: Citation;
  /** When provided, the chip wraps this text inline with an underline and
   *  appends a small superscript chip number. Used by CitedMarkdownContent so
   *  cited claims are highlighted in place rather than as a footer row.
   *  Without it, falls back to the pill-only rendering used for unmatched
   *  citations. */
  inlineText?: string;
}

export default function CitationChip({ citation, inlineText }: Props) {
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
          aria-label={`Citation ${citation.index} (${citation.confidence}): ${inlineText}`}
        >
          {inlineText}
          <sup className={`chat-cite-sup ${tone}`} aria-hidden>
            {glyph}
            {citation.index}
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
        aria-label={`Citation ${citation.index} (${citation.confidence})`}
      >
        <span aria-hidden>{glyph}</span>
        <span>{citation.index}</span>
      </button>
      {open && <CitationTooltip citation={citation} />}
    </span>
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
