"use client";

// Unified-diff renderer. Prefers Claude Code's pre-computed
// `structuredPatch` hunks (absolute file line numbers) and falls back
// to an LCS line-diff of `old_string`/`new_string` while the tool is
// still running. Mirrors YouCoded's DiffView (replicated per D9) —
// kept narrower because the budget chat doesn't have CC's expand-all
// keyboard shortcut yet.

import React, { useMemo, useState } from "react";

import type { StructuredPatchHunk } from "@/lib/types.js";

type DiffRow =
  | { kind: "ctx"; oldN: number; newN: number; text: string }
  | { kind: "del"; oldN: number; text: string }
  | { kind: "add"; newN: number; text: string };

const DIFF_ROW_PX = 20;
const DIFF_PREVIEW_LINES = 15;

function diffLines(oldLines: string[], newLines: string[]): DiffRow[] {
  const m = oldLines.length;
  const n = newLines.length;
  // dp[i][j] = LCS length of oldLines[i..] and newLines[j..]. The
  // `noUncheckedIndexedAccess` tsconfig flag widens the indexed type
  // to `T | undefined`, so we narrow with non-null helpers below
  // — the recurrence guarantees every read is in-bounds.
  const dp: number[][] = Array.from({ length: m + 1 }, () =>
    new Array<number>(n + 1).fill(0),
  );
  const dpAt = (i: number, j: number): number => dp[i]![j]!;
  const oldAt = (i: number) => oldLines[i]!;
  const newAt = (j: number) => newLines[j]!;
  for (let i = m - 1; i >= 0; i--) {
    for (let j = n - 1; j >= 0; j--) {
      dp[i]![j] =
        oldAt(i) === newAt(j)
          ? dpAt(i + 1, j + 1) + 1
          : Math.max(dpAt(i + 1, j), dpAt(i, j + 1));
    }
  }
  const rows: DiffRow[] = [];
  let i = 0;
  let j = 0;
  while (i < m && j < n) {
    if (oldAt(i) === newAt(j)) {
      rows.push({ kind: "ctx", oldN: i + 1, newN: j + 1, text: oldAt(i) });
      i++;
      j++;
    } else if (dpAt(i + 1, j) >= dpAt(i, j + 1)) {
      rows.push({ kind: "del", oldN: i + 1, text: oldAt(i) });
      i++;
    } else {
      rows.push({ kind: "add", newN: j + 1, text: newAt(j) });
      j++;
    }
  }
  while (i < m) {
    rows.push({ kind: "del", oldN: i + 1, text: oldAt(i) });
    i++;
  }
  while (j < n) {
    rows.push({ kind: "add", newN: j + 1, text: newAt(j) });
    j++;
  }
  return rows;
}

function rowsFromHunk(hunk: StructuredPatchHunk): DiffRow[] {
  const rows: DiffRow[] = [];
  let oldN = hunk.oldStart;
  let newN = hunk.newStart;
  for (const raw of hunk.lines) {
    const prefix = raw.charAt(0);
    const text = raw.slice(1);
    if (prefix === "-") {
      rows.push({ kind: "del", oldN, text });
      oldN++;
    } else if (prefix === "+") {
      rows.push({ kind: "add", newN, text });
      newN++;
    } else {
      rows.push({ kind: "ctx", oldN, newN, text });
      oldN++;
      newN++;
    }
  }
  return rows;
}

interface DiffViewProps {
  oldStr: string;
  newStr: string;
  structuredPatch?: StructuredPatchHunk[];
}

export default function DiffView({
  oldStr,
  newStr,
  structuredPatch,
}: DiffViewProps) {
  const { rows, hunkBoundaries, maxLineNum } = useMemo(() => {
    if (structuredPatch && structuredPatch.length > 0) {
      const out: DiffRow[] = [];
      const boundaries = new Set<number>();
      let max = 0;
      structuredPatch.forEach((hunk, i) => {
        if (i > 0) boundaries.add(out.length);
        const hunkRows = rowsFromHunk(hunk);
        out.push(...hunkRows);
        max = Math.max(
          max,
          hunk.oldStart + hunk.oldLines,
          hunk.newStart + hunk.newLines,
        );
      });
      return { rows: out, hunkBoundaries: boundaries, maxLineNum: max };
    }
    const oldLines = oldStr.split("\n");
    const newLines = newStr.split("\n");
    return {
      rows: diffLines(oldLines, newLines),
      hunkBoundaries: new Set<number>(),
      maxLineNum: Math.max(oldLines.length, newLines.length),
    };
  }, [oldStr, newStr, structuredPatch]);

  const total = rows.length;
  const [open, setOpen] = useState(false);
  const overflow = total > DIFF_PREVIEW_LINES;
  const containerStyle =
    open || !overflow
      ? undefined
      : { maxHeight: `${DIFF_PREVIEW_LINES * DIFF_ROW_PX}px` };

  // Single line-number gutter — del shows old-file number, add/ctx
  // show new-file number. Pad to the widest number in view.
  const gutterWidth = Math.max(2, String(maxLineNum).length);
  const gutterCh = `${gutterWidth}ch`;

  return (
    <>
      <div
        className="text-xs font-mono rounded-sm border border-edge overflow-auto"
        style={containerStyle}
      >
        {rows.map((row, idx) => {
          const showSeparator = hunkBoundaries.has(idx);
          const lineNum =
            row.kind === "del" ? String(row.oldN) : String(row.newN);
          const rowClass =
            row.kind === "del"
              ? "bg-red-600/10 border-l-[3px] border-red-500"
              : row.kind === "add"
                ? "bg-green-600/10 border-l-[3px] border-green-400"
                : "border-l-[3px] border-transparent";
          const glyph =
            row.kind === "del" ? "−" : row.kind === "add" ? "+" : " ";
          const glyphClass =
            row.kind === "del"
              ? "text-red-400 font-bold"
              : row.kind === "add"
                ? "text-green-400 font-bold"
                : "text-fg-muted";
          const textClass = row.kind === "ctx" ? "text-fg-dim" : "text-fg";
          return (
            <React.Fragment key={idx}>
              {showSeparator && (
                <div className="flex items-center text-fg-faint text-[10px] border-y border-edge-dim bg-inset/40 select-none">
                  <span className="px-2 py-0.5">⋯</span>
                </div>
              )}
              <div className={`flex items-start ${rowClass}`}>
                <span
                  className="text-right px-1.5 py-0.5 text-fg-muted select-none shrink-0"
                  style={{ width: gutterCh }}
                >
                  {lineNum}
                </span>
                <span
                  className={`w-4 select-none shrink-0 ${glyphClass}`}
                >
                  {glyph}
                </span>
                <span
                  className={`py-0.5 pr-2 whitespace-pre-wrap break-all flex-1 ${textClass}`}
                >
                  {row.text || " "}
                </span>
              </div>
            </React.Fragment>
          );
        })}
      </div>
      {overflow && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-1 text-[10px] uppercase tracking-wider text-fg-muted hover:text-fg-2"
        >
          {open ? "Collapse" : `Expand (${total} lines)`}
        </button>
      )}
    </>
  );
}
