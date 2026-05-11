"use client";

// CitedMarkdownContent — the chat surface's citation-aware markdown
// renderer.
//
// Approach (post-2026-05-07 rework, replacing the prior "walk rendered
// text nodes for claim_span substring" matcher):
//
//   1. Pre-process: planCitationPlacements() walks the raw markdown
//      line-by-line and decides which line each citation anchors to.
//      Matching is done on a normalized + markdown-stripped form of
//      both the line and the claim_span, so `**$2.5M**` in a cite()
//      claim_span still finds `$2.5M` in the rendered text.
//
//   2. injectCiteSentinels() appends `{{cite:N}}` sentinels to the end
//      of each matched markdown line (or to the bottom of the content
//      for unmatched citations). The sentinels are plain text — curly
//      braces have no special meaning in CommonMark, so they survive
//      ReactMarkdown intact and land in a text node.
//
//   3. ReactMarkdown renders the augmented markdown. Wrapped block
//      elements (p, li, td, h*, blockquote) walk their children for
//      `{{cite:N}}` patterns and split each into [text, <CitationChip>,
//      text]. The chip ends up:
//        - at end of paragraph (when claim was in a paragraph)
//        - at end of list item (when claim was in `- foo` line)
//        - inside the last cell of a table row (when claim was in
//          `| a | b | c |`)
//        - in a standalone paragraph at the bottom (unmatched)
//
// What this does NOT do (deliberate limitation): inline-underline the
// matched span. Earlier attempts at underlining inside markdown ran
// into formatting boundaries (bold/italic/code/table cells) that
// fragment text nodes and made the underline silently disappear in
// most real cases. The chip-at-end-of-block placement keeps every
// citation visibly anchored to the right reading-order context
// without depending on perfect substring matching, which is what the
// user actually noticed was broken.

import React, { useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import {
  CITE_SENTINEL_RE,
  injectCiteSentinels,
  planCitationPlacements,
  type Citation,
} from "@/lib/citation-extract";

import CitationChip from "./CitationChip";

const remarkPluginsStable = [remarkGfm];
const rehypePluginsStable = [rehypeHighlight];

interface Props {
  content: string;
  citations: Citation[];
}

export default function CitedMarkdownContent({ content, citations }: Props) {
  // Build the augmented markdown once per (content, citations) change.
  // Both inputs are stable across re-renders because the parent uses
  // useMemo for citations, so the augmentation work runs roughly once
  // per turn, not per keystroke during streaming.
  const augmentedContent = useMemo(() => {
    if (citations.length === 0) return content;
    const placements = planCitationPlacements(content, citations);
    return injectCiteSentinels(content, placements);
  }, [content, citations]);

  // Closure that wraps a ReactMarkdown element override and runs the
  // sentinel-replacement walker on its children. Used for every
  // text-bearing block element so a sentinel ending up in any of them
  // gets converted to a chip.
  const components = useMemo(() => {
    const wrap = (render: ChildRenderer) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ({ children, ...props }: any) => {
        const transformed = walkAndReplaceSentinels(children, citations);
        return render(transformed, props);
      };
    };

    return {
      h1: wrap((children, props) => (
        <h1
          className="text-xl font-bold mt-6 mb-3 pb-1.5 text-fg border-b border-edge"
          {...props}
        >
          {children}
        </h1>
      )),
      h2: wrap((children, props) => (
        <h2
          className="text-lg font-bold mt-6 mb-3 pb-1 text-fg border-b border-edge"
          {...props}
        >
          {children}
        </h2>
      )),
      h3: wrap((children, props) => (
        <h3 className="text-base font-bold mt-5 mb-2 text-fg" {...props}>
          {children}
        </h3>
      )),
      h4: wrap((children, props) => (
        <h4 className="text-sm font-bold mt-4 mb-1.5 text-fg" {...props}>
          {children}
        </h4>
      )),
      p: wrap((children, props) => (
        <p className="mb-3 last:mb-0 leading-relaxed" {...props}>
          {children}
        </p>
      )),
      li: wrap((children, props) => (
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
      blockquote: wrap((children, props) => (
        <blockquote
          className="border-l-2 border-edge pl-3 my-3 text-fg-dim italic"
          {...props}
        >
          {children}
        </blockquote>
      )),
      td: wrap((children, props) => (
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

  return (
    <ReactMarkdown
      remarkPlugins={remarkPluginsStable}
      rehypePlugins={rehypePluginsStable}
      components={components}
    >
      {augmentedContent}
    </ReactMarkdown>
  );
}

type ChildRenderer = (
  children: ReactNode,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  props: any,
) => React.ReactElement;

/** Walk a rendered React node tree depth-first. For every leaf string
 *  child, scan for `{{cite:N}}` sentinels and split the string into
 *  alternating text + <CitationChip> nodes. Recurses into nested
 *  elements so a sentinel ending up inside a `<strong>` or `<em>`
 *  still gets resolved.
 *
 *  Sentinels that reference an out-of-range citation index (shouldn't
 *  happen in practice, but defensive) are rendered as the literal
 *  sentinel text so the bug is visible rather than silently dropped. */
function walkAndReplaceSentinels(
  children: ReactNode,
  citations: Citation[],
): ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      return splitStringOnSentinels(child, citations);
    }
    if (typeof child === "number") return child;
    if (child === null || child === undefined) return child;
    if (React.isValidElement(child)) {
      const element = child as React.ReactElement<{ children?: ReactNode }>;
      const props = element.props;
      if (props.children !== undefined) {
        const newChildren = walkAndReplaceSentinels(props.children, citations);
        return React.cloneElement(element, undefined, newChildren);
      }
      return child;
    }
    return child;
  });
}

function splitStringOnSentinels(
  text: string,
  citations: Citation[],
): ReactNode {
  if (!text.includes("{{cite:")) return text;
  const out: ReactNode[] = [];
  let lastEnd = 0;
  // Reset the regex index — global regexes carry state across calls.
  CITE_SENTINEL_RE.lastIndex = 0;
  let match: RegExpExecArray | null;
  while ((match = CITE_SENTINEL_RE.exec(text)) !== null) {
    const idx = Number.parseInt(match[1]!, 10);
    const cite = citations[idx];
    if (match.index > lastEnd) {
      out.push(text.slice(lastEnd, match.index));
    }
    if (cite) {
      out.push(<CitationChip key={`cite-${idx}`} citation={cite} />);
    } else {
      // Out-of-range — surface the sentinel so the bug is visible.
      out.push(match[0]);
    }
    lastEnd = match.index + match[0].length;
  }
  if (lastEnd < text.length) out.push(text.slice(lastEnd));
  // Keep the original string when no sentinels were found, so React
  // doesn't reconcile a wrapping array around plain text needlessly.
  return out.length > 0 ? out : text;
}
