// CitedMarkdownContent — the chat surface's citation-aware markdown renderer.
//
// Approach:
//
//   1. planCitationPlacements() walks the raw markdown line by line and
//      decides which line each citation anchors to. Matching runs on a
//      normalized + markdown-stripped form of both the line and the
//      claim_span, so `**$2.5M**` in a claim_span still finds `$2.5M` in the
//      rendered text.
//
//   2. injectCiteSentinels() splices `{{cite:N}}` sentinels into the matched
//      markdown lines (or at the bottom for unmatched citations). Sentinels
//      are plain text — curly braces have no meaning in CommonMark, so they
//      survive ReactMarkdown intact and land in a text node.
//
//   3. ReactMarkdown renders the augmented markdown. Wrapped block elements
//      (p, li, td, h*, blockquote) walk their children for `{{cite:N}}` and
//      split each into [text, <CitationChip>, text]. The chip ends up:
//        - at end of paragraph (claim was in a paragraph)
//        - at end of list item (claim was in `- foo`)
//        - inside the last cell of a table row (claim was in `| a | b |`)
//        - in a standalone paragraph at the bottom (unmatched)
//
// Ported from web/components/CitedMarkdownContent.tsx. The element overrides
// no longer carry Tailwind class strings — styling comes from the `.chat-md …`
// descendant rules in app.css — but every override still exists, because
// `wrap()` is what performs the sentinel replacement and dropping an override
// would silently drop chips from that element type.

import React, { useMemo, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

import {
  CITE_SENTINEL_RE,
  injectCiteSentinels,
  planCitationPlacements,
  type Citation,
} from "./citation-extract.js";

import CitationChip from "./CitationChip.js";

const remarkPluginsStable = [remarkGfm];
const rehypePluginsStable = [rehypeHighlight];

interface Props {
  content: string;
  citations: Citation[];
}

export default function CitedMarkdownContent({ content, citations }: Props) {
  // Build the augmented markdown once per (content, citations) change. Both
  // inputs are stable across re-renders because the parent memoizes
  // citations, so this runs roughly once per turn, not per streamed token.
  const augmentedContent = useMemo(() => {
    if (citations.length === 0) return content;
    const placements = planCitationPlacements(content, citations);
    return injectCiteSentinels(content, placements);
  }, [content, citations]);

  // Closure that wraps a ReactMarkdown element override and runs the
  // sentinel-replacement walker on its children. Applied to every
  // text-bearing block element so a sentinel landing in any of them becomes
  // a chip.
  const components = useMemo(() => {
    const wrap = (render: ChildRenderer) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ({ children, ...props }: any) => {
        const transformed = walkAndReplaceSentinels(children, citations);
        return render(transformed, props);
      };
    };

    return {
      h1: wrap((children, props) => <h1 {...props}>{children}</h1>),
      h2: wrap((children, props) => <h2 {...props}>{children}</h2>),
      h3: wrap((children, props) => <h3 {...props}>{children}</h3>),
      h4: wrap((children, props) => <h4 {...props}>{children}</h4>),
      p: wrap((children, props) => <p {...props}>{children}</p>),
      li: wrap((children, props) => <li {...props}>{children}</li>),
      blockquote: wrap((children, props) => (
        <blockquote {...props}>{children}</blockquote>
      )),
      td: wrap((children, props) => <td {...props}>{children}</td>),
      // Wide tables scroll inside their own box rather than widening the
      // bubble. Structural, so it survives the styling move.
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      table: ({ children, ...props }: any) => (
        <div className="chat-md-table-wrap">
          <table {...props}>{children}</table>
        </div>
      ),
    };
  }, [citations]);

  return (
    <div className="chat-md">
      <ReactMarkdown
        remarkPlugins={remarkPluginsStable}
        rehypePlugins={rehypePluginsStable}
        components={components}
      >
        {augmentedContent}
      </ReactMarkdown>
    </div>
  );
}

type ChildRenderer = (
  children: ReactNode,
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  props: any,
) => React.ReactElement;

/** Walk a rendered React node tree depth-first. For every leaf string child,
 *  scan for `{{cite:N}}` sentinels and split the string into alternating text
 *  + <CitationChip> nodes. Recurses into nested elements so a sentinel that
 *  ends up inside a `<strong>` or `<em>` still resolves.
 *
 *  Sentinels referencing an out-of-range citation index (shouldn't happen,
 *  but defensive) render as the literal sentinel text so the bug is visible
 *  rather than silently dropped. */
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
      // Out of range — surface the sentinel so the bug is visible.
      out.push(match[0]);
    }
    lastEnd = match.index + match[0].length;
  }
  if (lastEnd < text.length) out.push(text.slice(lastEnd));
  // Keep the original string when no sentinels were found, so React doesn't
  // reconcile a wrapping array around plain text needlessly.
  return out.length > 0 ? out : text;
}
