"use client";

// RefusalBanner — three cases from spec §11. Props-driven for v1;
// auto-detection from the assistant turn (post-faithfulness verifier
// in WS3, refusal-marker tool / system-prompt classifier in WS5)
// wires this in later. Until then, callers can construct the banner
// directly when they know they're handling a refusal turn.
//
// Copy is verbatim from the spec — refusal language is load-bearing
// (the user's trust contract is "honest about limits or we don't
// ship"). Don't paraphrase without updating the spec.

import { Chip } from "./tool-views/primitives";

export interface RefusalChunkPreview {
  chunkId: string;
  docTitle: string;
  publisher: string;
  fiscalYear: number | null;
  pageStart: number | null;
  pageEnd: number | null;
  text: string;
}

export type RefusalReason =
  | { kind: "no_retrieval"; corpusSummary?: string }
  | { kind: "synthesis"; chunks: RefusalChunkPreview[] }
  | { kind: "out_of_scope" };

interface Props {
  refusal: RefusalReason;
}

const COPY: Record<RefusalReason["kind"], { title: string; body: string }> = {
  no_retrieval: {
    title: "Couldn't find anything in the corpus.",
    body: "I couldn't find anything in the corpus that addresses this question. You may want to rephrase, or this may be outside what's been indexed.",
  },
  synthesis: {
    title: "Found relevant passages but couldn't synthesize.",
    body: "I found these potentially relevant passages but couldn't confidently synthesize an answer. Read the chunks below directly and decide.",
  },
  out_of_scope: {
    title: "This question is outside the tool's scope.",
    body: "This is an editorial or policy question — the kind of judgment call the tool isn't designed to make. The system retrieves and cites; you decide what to do with the information.",
  },
};

export default function RefusalBanner({ refusal }: Props) {
  const copy = COPY[refusal.kind];
  return (
    <div className="rounded-md border border-amber-600/40 bg-amber-600/10 p-3 text-sm text-fg space-y-2">
      <div className="flex items-center gap-2">
        <Chip tone="warn">Refusal</Chip>
        <span className="font-bold text-fg">{copy.title}</span>
      </div>
      <p className="text-fg-2">{copy.body}</p>
      {refusal.kind === "no_retrieval" && refusal.corpusSummary && (
        <p className="text-xs text-fg-muted italic">
          The corpus currently includes: {refusal.corpusSummary}
        </p>
      )}
      {refusal.kind === "synthesis" && refusal.chunks.length > 0 && (
        <ul className="flex flex-col gap-2 mt-2">
          {refusal.chunks.slice(0, 5).map((c, i) => (
            <ChunkPreviewRow key={c.chunkId} chunk={c} rank={i + 1} />
          ))}
        </ul>
      )}
    </div>
  );
}

const PREVIEW_CHARS = 280;

function ChunkPreviewRow({
  chunk,
  rank,
}: {
  chunk: RefusalChunkPreview;
  rank: number;
}) {
  const snippet =
    chunk.text.length > PREVIEW_CHARS
      ? chunk.text.slice(0, PREVIEW_CHARS).trimEnd() + "…"
      : chunk.text;
  const pageLabel =
    chunk.pageStart != null
      ? chunk.pageEnd != null && chunk.pageEnd !== chunk.pageStart
        ? `pp. ${chunk.pageStart}–${chunk.pageEnd}`
        : `p. ${chunk.pageStart}`
      : null;
  return (
    <li className="rounded-sm border border-edge-dim bg-canvas p-2 text-xs">
      <div className="flex items-center gap-2 flex-wrap mb-1">
        <span className="text-fg-muted font-mono shrink-0">#{rank}</span>
        <span className="text-fg-2 font-medium truncate">
          {chunk.docTitle || chunk.chunkId}
        </span>
        {pageLabel && <Chip>{pageLabel}</Chip>}
        {chunk.fiscalYear != null && <Chip>FY{chunk.fiscalYear}</Chip>}
        <Chip tone="info">{chunk.publisher}</Chip>
      </div>
      <div className="text-fg-dim whitespace-pre-wrap">{snippet}</div>
    </li>
  );
}
