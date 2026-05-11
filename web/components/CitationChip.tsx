"use client";

// CitationChip — inline numbered chip rendered alongside an assistant
// turn's cited claims (spec §10.1). Hover surfaces a tooltip with
// filename, page, fiscal year, and the verbatim chunk quote (§10.2).
// Click selects the citation on a per-app context bus; the PdfViewer
// component (Phase 1c WS4c) subscribes and scrolls/highlights. Until
// WS4c ships, the click is a no-op for end users — but the bus is
// already in place.

import { useState } from "react";

import {
  formatCopyCitation,
  type Citation,
} from "@/lib/citation-extract";
import { useCitationBus } from "@/state/citation-context";

interface Props {
  citation: Citation;
  /** When provided, the chip wraps this text inline with an underline,
   *  appending a small superscript chip number. Used by the
   *  CitedMarkdownContent renderer so cite()'d claims are highlighted
   *  in place rather than as a footer row. Without this prop, falls
   *  back to the pill-only rendering used for unmatched citations. */
  inlineText?: string;
}

export default function CitationChip({ citation, inlineText }: Props) {
  const [open, setOpen] = useState(false);
  const bus = useCitationBus();

  const verbatim = citation.confidence === "verbatim";
  const failed = citation.failureReason !== undefined;
  // Three visual states for the chip: failed (red ✗ — server rejected
  // the cite, claim is uncited), verbatim (green ✓ — strict source
  // match), paraphrase (neutral ≈ — supported but reworded). The
  // failed variant takes priority over the confidence variant; the
  // user needs to see "this claim has no valid citation" before
  // anything else.
  const tone = failed
    ? "bg-red-600/15 text-red-400 border-red-600/40"
    : verbatim
      ? "bg-green-600/15 text-green-400 border-green-600/40"
      : "bg-inset text-fg-2 border-edge";
  const glyph = failed ? "✗" : verbatim ? "✓" : "≈";

  // Hover tracking is on the WRAPPING SPAN, not the button. The
  // tooltip is positioned with a 4px gap above the chip — if we
  // tracked hover on the button, moving the cursor toward the
  // tooltip would cross that gap, fire mouseleave on the button,
  // and close the tooltip before the user could reach it. The span
  // bounds both chip and tooltip, so the cursor stays "inside"
  // throughout the traversal.
  if (inlineText !== undefined) {
    const underline = failed
      ? "underline decoration-red-500/60 decoration-wavy decoration-1 underline-offset-2"
      : verbatim
        ? "underline decoration-green-500/60 decoration-1 underline-offset-2"
        : "underline decoration-fg-muted decoration-dashed decoration-1 underline-offset-2";
    return (
      <span
        className="relative inline"
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
      >
        <button
          type="button"
          onClick={() => bus.select(citation)}
          onFocus={() => setOpen(true)}
          onBlur={() => setOpen(false)}
          className={`inline cursor-pointer text-fg ${underline} hover:opacity-80`}
          aria-label={`Citation ${citation.index} (${citation.confidence}): ${inlineText}`}
        >
          {inlineText}
          <sup
            className={`ml-0.5 px-1 py-px text-[9px] font-medium rounded-sm border ${tone} align-super`}
            aria-hidden
          >
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
      className="relative inline-block align-baseline"
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      <button
        type="button"
        onClick={() => bus.select(citation)}
        onFocus={() => setOpen(true)}
        onBlur={() => setOpen(false)}
        className={`inline-flex items-center gap-1 px-1.5 py-px text-[10px] font-medium rounded-sm border ${tone} hover:opacity-80 transition-opacity`}
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
  // model-supplied span. Falls back to the model's claim_span when
  // the chunk text isn't available (no retrieve in this turn).
  let verbatimQuote = "";
  if (r?.text) {
    const start = Math.max(0, citation.spanStart);
    const end = Math.min(r.text.length, citation.spanEnd);
    if (end > start) verbatimQuote = r.text.slice(start, end);
  }

  return (
    <div
      role="tooltip"
      className="absolute bottom-[calc(100%+4px)] left-0 z-50 w-80 rounded-md border border-edge bg-panel shadow-lg p-3 text-xs text-fg cursor-default"
      // The button sits inside a span; the tooltip lives in the same
      // span so mouseleave on the button still fires before the
      // tooltip can react. Block pointer events FROM the tooltip
      // contents so the surrounding chat doesn't receive accidental
      // clicks while the user is reaching for "Copy citation".
      onMouseEnter={(e) => e.stopPropagation()}
    >
      <div className="flex items-center gap-2 mb-2">
        <span className="font-bold text-fg">[{citation.index}]</span>
        <span className="text-fg-2 truncate">
          {r?.docTitle || `chunk ${citation.chunkId}`}
        </span>
      </div>
      <div className="flex items-center gap-2 flex-wrap text-[10px] text-fg-muted mb-2">
        {r?.pageStart != null && (
          <span>
            {r.pageEnd != null && r.pageEnd !== r.pageStart
              ? `pp. ${r.pageStart}–${r.pageEnd}`
              : `p. ${r.pageStart}`}
          </span>
        )}
        {r?.fiscalYear != null && <span>FY{r.fiscalYear}</span>}
        {r?.publisher && <span>· {r.publisher}</span>}
        <span className="ml-auto uppercase tracking-wider">
          {citation.failureReason ? "uncited" : citation.confidence}
        </span>
      </div>
      {citation.failureReason && (
        // Surface the server's rejection reason so the user knows
        // WHY the citation didn't validate (wrong span, wrong chunk,
        // span out of range, etc.). Plain-text, no copy affordance —
        // there's nothing to copy when the cite isn't valid.
        <div className="text-red-300 border-l-2 border-red-600/50 pl-2 mb-2 text-[11px]">
          <div className="uppercase tracking-wider text-red-400 mb-1">
            Citation failed
          </div>
          <div className="text-red-200/80">{citation.failureReason}</div>
        </div>
      )}
      {verbatimQuote && !citation.failureReason && (
        <blockquote className="text-fg-dim border-l-2 border-edge pl-2 mb-2 italic max-h-24 overflow-y-auto">
          {verbatimQuote}
        </blockquote>
      )}
      <div className="text-fg-muted text-[10px] mb-2">
        <span className="uppercase tracking-wider">Claim:</span>{" "}
        <span className="text-fg-dim italic">{citation.claimSpan}</span>
      </div>
      {!citation.failureReason && (
        <button
          type="button"
          onClick={handleCopy}
          className="w-full text-[10px] uppercase tracking-wider rounded-sm border border-edge bg-inset hover:bg-canvas py-1"
        >
          {copied ? "Copied!" : `Copy citation: ${copyText || "—"}`}
        </button>
      )}
    </div>
  );
}
