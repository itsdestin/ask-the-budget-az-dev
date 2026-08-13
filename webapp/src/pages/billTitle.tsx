// Rendering a scraped bill title, honestly and safely.
//
// Lifted out of pages/FiscalNotes.tsx on 2026-08-13 so the retrieval RESULT card can reuse
// it (spec F16) without the page importing the card while the card imports the page. It is
// the ONLY safe renderer for the 241 raw-<strike> titles in the corpus, and a second copy
// would be a second chance for someone to reach for dangerouslySetInnerHTML instead.

/** Matches the source page's strike/rename convention:
 *  `<strike>old title</strike> (NOW: new title)` — and its sibling form,
 *  `<strike>old title</strike> S/E: new title` (S/E = a strike-everything amendment).
 *  Both fall out of "whatever text follows `</strike>`", so one pattern covers them. */
const STRUCK_TITLE = /^([\s\S]*?)<strike>([\s\S]*?)<\/strike>([\s\S]*)$/i;

/** Remove any markup and collapse the whitespace it leaves behind.
 *
 *  WHY this exists at all: ~241 of the 2,126 titles in the snapshot arrive as RAW HTML from
 *  the scraped source. Verified against app/data/fiscal-notes-snapshot.json —
 *  `<strike>`/`</strike>` are the ONLY tags that appear (241 of each, nothing else), and no
 *  HTML entities appear either (the single `&` in the corpus is the literal one in "G&F"),
 *  so nothing here needs entity decoding. The mockup, being a static file, just lets the
 *  browser parse those tags; this reaches the same result safely. */
export function stripTags(text: string): string {
  return text.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ").trim();
}

/** The words of a title a reader can actually SEE — what the filter searches and what the
 *  A-Z sort compares, so that typing "strike" cannot match 241 unrelated bills. This is
 *  also what the mockup's island reads (`.fbill-desc`'s textContent, tags already parsed
 *  away by the browser). */
export function titleText(title: string): string {
  return title.includes("<") ? stripTags(title) : title;
}

/** Render a bill title, honestly and safely.
 *
 *  WHY not `{title}` directly: React escapes strings, so the 241 HTML-bearing titles would
 *  show users literal "<strike>…</strike>" tags.
 *  WHY not dangerouslySetInnerHTML: this text came from a scrape. Injecting it as HTML would
 *  hand whatever the source page contains — now, or after a Plan 3 refresh — straight to the
 *  DOM; one `<script>` in one title is enough.
 *  So: recognize the ONE documented pattern and build real elements from it, and strip tags
 *  from anything else. Unknown or unclosed markup degrades to plain text, never to injected
 *  HTML. */
export function BillTitle({ title }: { title: string }) {
  // Fast path — ~89% of titles are plain text with no markup to reason about.
  if (!title.includes("<")) return <>{title}</>;
  const parts = STRUCK_TITLE.exec(title);
  if (!parts) return <>{stripTags(title)}</>;
  const [, lead, struck, rest] = parts;
  const before = stripTags(lead);
  const after = stripTags(rest);
  return (
    <>
      {before ? `${before} ` : ""}
      {/* <s>, not <strike>, which is obsolete in HTML5. It is the semantic element for "no
          longer accurate", which is exactly what a retitled bill's old title is. */}
      <s>{stripTags(struck)}</s>
      {after ? ` ${after}` : ""}
    </>
  );
}

// ---------------------------------------------------------------------------
// Filtering + sorting — behavior parity with the island (build.py:153-201)
