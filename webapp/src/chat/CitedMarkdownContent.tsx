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

import CitationChip, { FigureChip } from "./CitationChip.js";
import {
  figuresForRender,
  placeFigures,
  type AnnotationFigure,
} from "./citation-annotation.js";

const remarkPluginsStable = [remarkGfm];
const rehypePluginsStable = [rehypeHighlight];

/** Figure sentinel, deliberately a separate namespace from `{{cite:N}}`.
 *  Model-issued prose citations and system-linked figures are different
 *  things with different chips; sharing one sentinel would make an
 *  off-by-one in either resolve to the other's chip. */
const FIG_SENTINEL_RE = /\{\{fig:(\d+)\}\}/g;

interface Props {
  content: string;
  citations: Citation[];
  /** The server's figure annotation for this turn. Absent on turns
   *  recorded before citation linking shipped, which must still render. */
  annotation?: unknown;
}

export default function CitedMarkdownContent({
  content,
  citations,
  annotation,
}: Props) {
  // Only figures the system actually sourced get a chip. An unverified
  // figure is not a citation — nothing was found — and drawing a numbered
  // red marker for each one buries the real citations in noise: a nine-row
  // table rendered as 13,14,…,20 struck through around a single live 21.
  //
  // Nothing announces the omission, deliberately. A number with no chip is
  // visibly uncited, so a second statement saying so is redundant. The
  // all-unverified case still gets `RefusalBanner`, which is a different
  // claim: not "this figure lacks a source" but "this ANSWER has none".
  const figures = useMemo(
    () => figuresForRender(annotation).filter((f) => f.verdict !== "unverified"),
    [annotation],
  );

  // Build the augmented markdown once per (content, citations) change. Both
  // inputs are stable across re-renders because the parent memoizes
  // citations, so this runs roughly once per turn, not per streamed token.
  const augmentedContent = useMemo(() => {
    let out = content;
    if (citations.length > 0) {
      const placements = planCitationPlacements(out, citations);
      out = injectCiteSentinels(out, placements);
    }
    if (figures.length > 0) {
      // Resolve positions against the text the cite pass just produced —
      // injecting cite sentinels first shifts every later offset, so
      // resolving beforehand would put figure chips adrift by exactly the
      // number of characters the cite sentinels added.
      const placed = placeFigures(out, figures);
      // Right-to-left, so an earlier insertion cannot move a later target.
      for (let i = placed.length - 1; i >= 0; i -= 1) {
        const { figure, at } = placed[i]!;
        const slot = figures.indexOf(figure);
        out = `${out.slice(0, at)}{{fig:${slot}}}${out.slice(at)}`;
      }
    }
    return out;
  }, [content, citations, figures]);

  // ONE sequence across both kinds of mark, assigned by position in the
  // finished markdown.
  //
  // Figures are numbered 1..N by the server annotation and prose citations
  // 1..M by citation-extract; rendered together those two sequences collide,
  // so an analyst saw a "4" sitting under figures numbered 1-3, and a prose
  // [1] could coexist with a figure [1] pointing somewhere else entirely.
  // The number has to mean "the Nth mark down this answer" or it means
  // nothing.
  //
  // Derived from `augmentedContent` rather than from the two source lists
  // because that string is the only place their relative order actually
  // exists — cite sentinels are placed BY LINE and figure sentinels BY
  // OFFSET, so neither list knows where the other landed.
  const displayNumbers = useMemo(() => {
    const map = new Map<string, number>();
    const re = /\{\{(cite|fig):(\d+)\}\}/g;
    let match: RegExpExecArray | null;
    let next = 1;
    while ((match = re.exec(augmentedContent)) !== null) {
      const key = `${match[1]}:${match[2]}`;
      // A retry can emit the same sentinel twice; it is one mark.
      if (!map.has(key)) map.set(key, next++);
    }
    return map;
  }, [augmentedContent]);

  // Closure that wraps a ReactMarkdown element override and runs the
  // sentinel-replacement walker on its children. Applied to every
  // text-bearing block element so a sentinel landing in any of them becomes
  // a chip.
  const components = useMemo(() => {
    const wrap = (render: ChildRenderer) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      return ({ children, ...props }: any) => {
        const transformed = walkAndReplaceSentinels(
          children, citations, figures, displayNumbers,
        );
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
  }, [citations, figures, displayNumbers]);

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
  figures: AnnotationFigure[] = [],
  displayNumbers: Map<string, number> = new Map(),
): ReactNode {
  return React.Children.map(children, (child) => {
    if (typeof child === "string") {
      return splitStringOnSentinels(child, citations, figures, displayNumbers);
    }
    if (typeof child === "number") return child;
    if (child === null || child === undefined) return child;
    if (React.isValidElement(child)) {
      const element = child as React.ReactElement<{ children?: ReactNode }>;
      const props = element.props;
      if (props.children !== undefined) {
        const newChildren = walkAndReplaceSentinels(
          props.children,
          citations,
          figures,
          displayNumbers,
        );
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
  figures: AnnotationFigure[] = [],
  displayNumbers: Map<string, number> = new Map(),
): ReactNode {
  const hasCite = text.includes("{{cite:");
  const hasFig = text.includes("{{fig:");
  if (!hasCite && !hasFig) return text;

  // Both sentinel kinds are collected in ONE positional pass. Running two
  // sequential passes would let the second pass's slicing lose the chips
  // the first pass had already turned into React elements.
  const marks: { at: number; len: number; node: ReactNode; raw: string }[] = [];
  const collect = (re: RegExp, build: (i: number) => ReactNode) => {
    re.lastIndex = 0; // global regexes carry state across calls
    let m: RegExpExecArray | null;
    while ((m = re.exec(text)) !== null) {
      const idx = Number.parseInt(m[1]!, 10);
      marks.push({ at: m.index, len: m[0].length, node: build(idx), raw: m[0] });
    }
  };
  collect(CITE_SENTINEL_RE, (idx) => {
    const cite = citations[idx];
    // Out of range — surface the sentinel so the bug is visible.
    return cite ? (
      <CitationChip
        key={`cite-${idx}`}
        citation={cite}
        displayIndex={displayNumbers.get(`cite:${idx}`)}
      />
    ) : null;
  });
  collect(FIG_SENTINEL_RE, (idx) => {
    const figure = figures[idx];
    return figure ? (
      <FigureChip
        key={`fig-${idx}`}
        figure={figure}
        displayIndex={displayNumbers.get(`fig:${idx}`)}
      />
    ) : null;
  });
  marks.sort((a, b) => a.at - b.at);

  const out: ReactNode[] = [];
  let lastEnd = 0;
  for (const mark of marks) {
    if (mark.at > lastEnd) out.push(text.slice(lastEnd, mark.at));
    out.push(mark.node ?? mark.raw);
    lastEnd = mark.at + mark.len;
  }
  if (lastEnd < text.length) out.push(text.slice(lastEnd));
  // Keep the original string when no sentinels were found, so React doesn't
  // reconcile a wrapping array around plain text needlessly.
  return out.length > 0 ? out : text;
}
