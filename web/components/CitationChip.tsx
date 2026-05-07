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
}

export default function CitationChip({ citation }: Props) {
  const [open, setOpen] = useState(false);
  const bus = useCitationBus();

  const tone =
    citation.confidence === "verbatim"
      ? "bg-green-600/15 text-green-400 border-green-600/40"
      : "bg-inset text-fg-2 border-edge";
  const glyph = citation.confidence === "verbatim" ? "✓" : "≈";

  return (
    <span className="relative inline-block align-baseline">
      <button
        type="button"
        onClick={() => bus.select(citation)}
        onMouseEnter={() => setOpen(true)}
        onMouseLeave={() => setOpen(false)}
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
          {citation.confidence}
        </span>
      </div>
      {verbatimQuote && (
        <blockquote className="text-fg-dim border-l-2 border-edge pl-2 mb-2 italic max-h-24 overflow-y-auto">
          {verbatimQuote}
        </blockquote>
      )}
      <div className="text-fg-muted text-[10px] mb-2">
        <span className="uppercase tracking-wider">Claim:</span>{" "}
        <span className="text-fg-dim italic">{citation.claimSpan}</span>
      </div>
      <button
        type="button"
        onClick={handleCopy}
        className="w-full text-[10px] uppercase tracking-wider rounded-sm border border-edge bg-inset hover:bg-canvas py-1"
      >
        {copied ? "Copied!" : `Copy citation: ${copyText || "—"}`}
      </button>
    </div>
  );
}
