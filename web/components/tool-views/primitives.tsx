"use client";

// Shared primitives for the per-tool ToolBody views. Mirrors the
// helpers in YouCoded's ToolBody.tsx (replicated, not vendored — D9)
// so chat-rendering looks the same in the budget app.

import { useState } from "react";

export function basename(fp: string): string {
  const parts = fp.replace(/\\/g, "/").split("/");
  return parts[parts.length - 1] || fp;
}

export function parentDir(fp: string): string {
  const parts = fp.replace(/\\/g, "/").split("/").filter(Boolean);
  return parts.slice(0, -1).join("/");
}

// Reveal literal \n / \" that JSON.stringify would otherwise hide so
// the raw fallback view stays scannable.
export function unescapeForDisplay(s: string): string {
  return s.replace(/\\n/g, "\n").replace(/\\"/g, '"').replace(/\\t/g, "\t");
}

// Collapse "\rUpdating files: 42%…\rUpdating files: 91%…" progress
// noise common in npm/git output by keeping just the final state of
// each line group.
export function stripCarriageReturns(s: string): string {
  return s
    .split("\n")
    .map((line) => {
      const parts = line.split("\r");
      return parts[parts.length - 1];
    })
    .join("\n");
}

interface CollapsibleBlockProps {
  children: string;
  maxLines?: number;
  className?: string;
}

export function CollapsibleBlock({
  children,
  maxLines = 20,
  className = "",
}: CollapsibleBlockProps) {
  const [open, setOpen] = useState(false);
  const lines = children.split("\n");
  const overflow = lines.length > maxLines;
  const shown = open || !overflow ? children : lines.slice(0, maxLines).join("\n");
  return (
    <div className="relative">
      <pre
        className={`text-xs text-fg-dim bg-panel rounded-sm p-2 overflow-auto whitespace-pre-wrap font-mono ${className}`}
      >
        {shown}
        {overflow && !open && <span className="text-fg-muted">{"\n"}…</span>}
      </pre>
      {overflow && (
        <button
          type="button"
          onClick={() => setOpen((o) => !o)}
          className="mt-1 text-[10px] uppercase tracking-wider text-fg-muted hover:text-fg-2"
        >
          {open ? "Show less" : `Show ${lines.length - maxLines} more lines`}
        </button>
      )}
    </div>
  );
}

interface PathHeaderProps {
  fp: string;
  extra?: React.ReactNode;
}

export function PathHeader({ fp, extra }: PathHeaderProps) {
  const dir = parentDir(fp);
  return (
    <div className="flex items-center gap-1.5 text-[11px] font-mono">
      {dir && <span className="text-fg-muted">{dir}/</span>}
      <span className="text-fg-2 font-medium">{basename(fp)}</span>
      {extra}
    </div>
  );
}

type ChipTone = "neutral" | "add" | "remove" | "warn" | "info";

// Tinted chips. Status text colors stay hardcoded so the add/remove/warn
// signal reads correctly across themes (light/dark/midnight/creme).
export function Chip({
  children,
  tone = "neutral",
}: {
  children: React.ReactNode;
  tone?: ChipTone;
}) {
  const toneClass =
    tone === "add"
      ? "bg-green-600/15 text-green-400 border-green-600/40"
      : tone === "remove"
        ? "bg-red-600/15 text-red-400 border-red-600/40"
        : tone === "warn"
          ? "bg-amber-600/15 text-amber-700 border-amber-600/40"
          : tone === "info"
            ? "bg-inset text-fg-2 border-edge"
            : "bg-inset text-fg-muted border-edge";
  return (
    <span
      className={`px-1.5 py-px text-[10px] uppercase tracking-wider rounded-sm border font-medium ${toneClass}`}
    >
      {children}
    </span>
  );
}

export function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handle = async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard may be blocked — silently ignore.
    }
  };
  return (
    <button
      type="button"
      onClick={handle}
      className="text-[10px] uppercase tracking-wider text-fg-muted hover:text-fg-2 px-1 rounded-sm"
      title="Copy"
    >
      {copied ? "Copied" : "Copy"}
    </button>
  );
}

export function ErrorBlock({ error }: { error: string }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-wider text-red-500 mb-1">
        Error
      </div>
      <pre className="text-xs text-red-400 bg-panel rounded-sm p-2 overflow-auto max-h-48 whitespace-pre-wrap">
        {error}
      </pre>
    </div>
  );
}
