// Plain (non-citation) markdown renderer: react-markdown + remark-gfm +
// rehype-highlight. Used for model-authored prose that carries no citations —
// today that is the create_document body preview.
//
// Ported from web/components/MarkdownContent.tsx. The Tailwind class strings
// are gone: styling now comes from the `.chat-md …` descendant rules in
// app.css, so the overrides below only do STRUCTURAL work (the code copy
// button, the table scroll wrapper, the unsafe-href guard). That is why most
// of them still exist despite carrying no className.

import React, { useState } from "react";
import ReactMarkdown from "react-markdown";
import rehypeHighlight from "rehype-highlight";
import remarkGfm from "remark-gfm";

// Syntax-highlight theme for rehype-highlight's output. Imported from a
// component rather than app.css because a CSS `@import` is only legal at the
// top of a stylesheet, and app.css opens with the mockup's own base layer.
// Vite inlines it into the same bundle either way.
import "highlight.js/styles/github.css";

const remarkPluginsStable = [remarkGfm];
const rehypePluginsStable = [rehypeHighlight];

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = () => {
    navigator.clipboard.writeText(text);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };
  return (
    <button onClick={handleCopy} className="chat-md-copy" type="button">
      {copied ? "Copied!" : "Copy"}
    </button>
  );
}

// Stable component overrides — defined at module scope so ReactMarkdown sees
// the same object reference on every render.
const mdComponents = {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  pre({ children, ...props }: any) {
    let codeText = "";
    React.Children.forEach(children, (child) => {
      if (React.isValidElement(child) && child.props) {
        const c = child as React.ReactElement<{ children?: React.ReactNode }>;
        if (typeof c.props.children === "string") {
          codeText = c.props.children;
        }
      }
    });
    return (
      <div className="chat-md-pre-wrap">
        <pre {...props}>{children}</pre>
        {codeText && <CopyButton text={codeText} />}
      </div>
    );
  },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  a({ href, children, ...props }: any) {
    // Anything that isn't http(s) or mailto renders as inert text. Model
    // output is untrusted input; a `javascript:` href would otherwise be one
    // click from executing in the analyst's session.
    const isSafeHref = href && /^(https?:|mailto:)/.test(href);
    if (!isSafeHref) {
      return <span>{children}</span>;
    }
    return (
      <a href={href} target="_blank" rel="noopener noreferrer" {...props}>
        {children}
      </a>
    );
  },
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  table({ children, ...props }: any) {
    // Wide tables scroll inside their own box rather than widening the bubble.
    return (
      <div className="chat-md-table-wrap">
        <table {...props}>{children}</table>
      </div>
    );
  },
};

interface Props {
  content: string;
}

export default React.memo(function MarkdownContent({ content }: Props) {
  return (
    <ReactMarkdown
      remarkPlugins={remarkPluginsStable}
      rehypePlugins={rehypePluginsStable}
      components={mdComponents}
    >
      {content}
    </ReactMarkdown>
  );
});
