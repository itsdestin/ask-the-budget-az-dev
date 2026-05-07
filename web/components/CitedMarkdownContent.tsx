"use client";

// CitedMarkdownContent — citation-aware variant of MarkdownContent.
// Renders the same react-markdown pipeline (gfm + highlight + the
// shared component overrides) but walks every block-level element's
// rendered children to find string nodes that contain a citation's
// `claim_span`, splitting and wrapping the match with an inline
// CitationChip (underline + superscript chip number).
//
// What this does NOT do:
//   - Find spans that cross markdown formatting boundaries (e.g. a
//     claim_span containing **bold** text). The split runs against
//     post-render text nodes, so a claim_span broken across a
//     <strong> tag won't match. AssistantTurnBubble's end-of-block
//     fallback handles those — the chip still appears, just as a
//     footer row instead of inline.
//   - Find spans Claude paraphrased (e.g. answer text says
//     "$2.5M" but claim_span says "$2,500,000"). Same fallback
//     applies. The system prompt instructs Claude to copy
//     claim_span verbatim from its answer; this is the recovery
//     path for when it doesn't.
//
// Returns the set of citation indexes that actually rendered inline
// via the `onMatched` callback so the caller can avoid double-
// rendering matched citations in the footer row.

import React, { useMemo, useRef, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import type { Citation } from "@/lib/citation-extract";

import CitationChip from "./CitationChip";

const remarkPluginsStable = [remarkGfm];
const rehypePluginsStable = [rehypeHighlight];

interface Props {
  content: string;
  citations: Citation[];
  /** Fired during render with the set of citation indexes that were
   *  successfully matched and rendered inline. The caller can render
   *  the unmatched ones as an end-of-block "Sources" footer. */
  onMatched?: (matchedIndexes: Set<number>) => void;
}

export default function CitedMarkdownContent({
  content,
  citations,
  onMatched,
}: Props) {
  // Per-render state shared across component overrides:
  //   `matched` — citation indexes already injected (so we don't
  //   render the same chip twice when claim_span recurs).
  //   We use a ref to survive across nested renders within a single
  //   ReactMarkdown pass, then expose the final set to the caller
  //   via the layout effect below.
  const matchedRef = useRef<Set<number>>(new Set());
  matchedRef.current = new Set();

  // Components: take the shared overrides and wrap every text-bearing
  // block element with the inline-citation walker. Recompute every
  // render so the closure captures the freshly-reset matchedRef.
  const components = useMemo(() => {
    const wrap = (tag: string, render: ChildRenderer) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ({ children, ...props }: any) => {
        const transformed = walkAndInject(
          children,
          citations,
          matchedRef.current,
        );
        return render(transformed, props);
      };
    };

    // The shared overrides live inline below — duplicating
    // MarkdownContent's keeps both files self-contained and avoids
    // exporting a private API surface from MarkdownContent. If a
    // style here drifts from MarkdownContent's, the chat renders
    // citations differently from any other surface that uses raw
    // MarkdownContent — keep them in sync via review.
    return {
      h1: wrap("h1", (children, props) => (
        <h1
          className="text-xl font-bold mt-6 mb-3 pb-1.5 text-fg border-b border-edge"
          {...props}
        >
          {children}
        </h1>
      )),
      h2: wrap("h2", (children, props) => (
        <h2
          className="text-lg font-bold mt-6 mb-3 pb-1 text-fg border-b border-edge"
          {...props}
        >
          {children}
        </h2>
      )),
      h3: wrap("h3", (children, props) => (
        <h3 className="text-base font-bold mt-5 mb-2 text-fg" {...props}>
          {children}
        </h3>
      )),
      h4: wrap("h4", (children, props) => (
        <h4 className="text-sm font-bold mt-4 mb-1.5 text-fg" {...props}>
          {children}
        </h4>
      )),
      p: wrap("p", (children, props) => (
        <p className="mb-3 last:mb-0 leading-relaxed" {...props}>
          {children}
        </p>
      )),
      li: wrap("li", (children, props) => (
        <li className="leading-relaxed" {...props}>
          {children}
        </li>
      )),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ol: ({ children, ...props }: any) => (
        <ol className="list-decimal pl-6 mb-3 space-y-1.5" {...props}>
          {children}
        </ol>
      ),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      ul: ({ children, ...props }: any) => (
        <ul className="list-disc pl-6 mb-3 space-y-1.5" {...props}>
          {children}
        </ul>
      ),
      blockquote: wrap("blockquote", (children, props) => (
        <blockquote
          className="border-l-2 border-edge pl-3 my-3 text-fg-dim italic"
          {...props}
        >
          {children}
        </blockquote>
      )),
      td: wrap("td", (children, props) => (
        <td className="border border-edge px-3 py-2" {...props}>
          {children}
        </td>
      )),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      th: ({ children, ...props }: any) => (
        <th
          className="border border-edge px-3 py-2 bg-panel text-left font-bold text-fg"
          {...props}
        >
          {children}
        </th>
      ),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      table: ({ children, ...props }: any) => (
        <div className="overflow-x-auto my-3">
          <table
            className="border-collapse border border-edge text-sm w-full"
            {...props}
          >
            {children}
          </table>
        </div>
      ),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      strong: ({ children, ...props }: any) => (
        <strong className="font-bold text-fg" {...props}>
          {children}
        </strong>
      ),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      em: ({ children, ...props }: any) => (
        <em className="italic text-fg-2" {...props}>
          {children}
        </em>
      ),
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      hr: ({ ...props }: any) => <hr className="border-edge my-5" {...props} />,
    };
  }, [citations]);

  // After ReactMarkdown finishes rendering, we know which citations
  // were matched. Surface that to the parent on the next tick so it
  // can decide what to render as a footer fallback.
  React.useLayoutEffect(() => {
    if (onMatched) onMatched(new Set(matchedRef.current));
  });

  return (
    <ReactMarkdown
      remarkPlugins={remarkPluginsStable}
      rehypePlugins={rehypePluginsStable}
      components={components}
    >
      {content}
    </ReactMarkdown>
  );
}

type ChildRenderer = (
  children: ReactNode,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  props: any,
) => React.ReactElement;

/** Walk the rendered children of one block-level element. For every
 *  string-typed leaf, search for any unmatched citation's claim_span
 *  and split the string into [text, <CitationChip inlineText>, text].
 *  Recurses into nested React elements so citations inside an em/
 *  strong/etc. wrap still get matched — but only at the leaf-string
 *  level, so a claim_span split across formatting won't be matched
 *  here (caught by the footer fallback). */
function walkAndInject(
  children: ReactNode,
  citations: Citation[],
  matched: Set<number>,
): ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      return splitStringOnCitations(child, citations, matched);
    }
    if (typeof child === "number") return child;
    if (child === null || child === undefined) return child;
    if (React.isValidElement(child)) {
      const element = child as React.ReactElement<{ children?: ReactNode }>;
      const props = element.props;
      if (props.children !== undefined) {
        const newChildren = walkAndInject(
          props.children,
          citations,
          matched,
        );
        return React.cloneElement(element, undefined, newChildren);
      }
      return child;
    }
    return child;
  });
}

function splitStringOnCitations(
  text: string,
  citations: Citation[],
  matched: Set<number>,
): ReactNode[] {
  const out: ReactNode[] = [];
  let pos = 0;
  while (pos < text.length) {
    let bestIdx = -1;
    let bestCite = -1;
    // Find the earliest unmatched citation whose claim_span occurs
    // in the remaining text. Earliest-first ensures left-to-right
    // rendering matches the order Claude wrote.
    for (let i = 0; i < citations.length; i++) {
      if (matched.has(i)) continue;
      const span = citations[i]!.claimSpan;
      if (!span) continue;
      const idx = text.indexOf(span, pos);
      if (idx < 0) continue;
      if (bestIdx < 0 || idx < bestIdx) {
        bestIdx = idx;
        bestCite = i;
      }
    }
    if (bestCite < 0) {
      // No more matches — emit the remainder.
      out.push(text.slice(pos));
      break;
    }
    matched.add(bestCite);
    if (bestIdx > pos) out.push(text.slice(pos, bestIdx));
    const cite = citations[bestCite]!;
    out.push(
      <CitationChip
        key={`inline-cite-${cite.index}`}
        citation={cite}
        inlineText={cite.claimSpan}
      />,
    );
    pos = bestIdx + cite.claimSpan.length;
  }
  return out;
}
