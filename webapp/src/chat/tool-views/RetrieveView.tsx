// Per-tool body view for `retrieve`. The tool's output is the JSON
// RetrieveResponse produced by harness/tools.py (same shape the retired
// sidecar returned): { chunks, top_score, retrieval_id, bm25_count,
// dense_count, fused_count }.
//
// Ported from web/components/tool-views/RetrieveView.tsx; Tailwind classes
// became the semantic classes in app.css's chat block.
//
// REBUILT (Part 2, Task 3). The unit is now the DOCUMENT, not the passage.
// Four things drove the rewrite, all of them things an analyst told us made
// the old card unreadable:
//
//   1. Five near-identical rows from one book printed that book's title five
//      times. They are now one block, with every page as a chip.
//   2. `score 1.260` sat beside dollar figures. That number is a RAW
//      cross-encoder logit on roughly a -10..10 scale -- not a percentage and
//      not a confidence -- and printing it next to money invites reading it as
//      one. Budget Documents removed its relevance number and bar for exactly
//      this reason; result ORDER carries the ranking. Gone, along with the
//      rank index and the bm25/dense/fused counters, which describe the
//      machinery rather than the finding.
//   3. A passage's stored text BEGINS with its own section heading, and this
//      view renders that heading too -- so roughly three lines of every result
//      were the line above it, repeated. See stripLeadingHeading.
//   4. `doc_type: afr` printed the field name. Filters are a sentence now.

import { useState } from "react";

import type { AssistantBlock } from "../chat-types.js";
import { Chip, ErrorBlock } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface ChunkPreview {
  chunk_id: string;
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  doc_type: string;
  section_path: string[];
  page_start: number | null;
  page_end: number | null;
  text: string;
  score: number;
}

interface RetrieveOutput {
  chunks: ChunkPreview[];
  top_score: number;
  retrieval_id: string;
  bm25_count: number;
  dense_count: number;
  fused_count: number;
}

const PREVIEW_CHARS = 240;

// How many document blocks show before the "show more". Six, not the old
// five-passage cap: one document block now stands for several passages, so the
// same screen budget buys more of the answer.
const VISIBLE_GROUPS_DEFAULT = 6;

function parseRetrieveOutput(raw: string | undefined): RetrieveOutput | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "chunks" in parsed &&
      Array.isArray((parsed as { chunks: unknown }).chunks)
    ) {
      return parsed as RetrieveOutput;
    }
    return null;
  } catch {
    return null;
  }
}

interface DocGroup {
  doc_id: string;
  doc_title: string;
  publisher: string;
  fiscal_year: number | null;
  best: ChunkPreview;
  pages: string[];
  count: number;
}

/** Group by document, preserving arrival order -- which is rank order, so the
 *  first chunk of each group is that document's strongest passage and the
 *  groups themselves stay in relevance order. */
function groupByDocument(chunks: ChunkPreview[]): DocGroup[] {
  const out: DocGroup[] = [];
  const byId = new Map<string, DocGroup>();
  for (const c of chunks) {
    let g = byId.get(c.doc_id);
    if (!g) {
      g = {
        doc_id: c.doc_id,
        doc_title: c.doc_title || c.doc_id,
        publisher: c.publisher,
        fiscal_year: c.fiscal_year,
        best: c,
        pages: [],
        count: 0,
      };
      byId.set(c.doc_id, g);
      out.push(g);
    }
    g.count += 1;
    const p = pageLabel(c);
    if (p && !g.pages.includes(p)) g.pages.push(p);
  }
  return out;
}

function pageLabel(c: ChunkPreview): string | null {
  if (c.page_start == null) return null;
  return c.page_end != null && c.page_end !== c.page_start
    ? `pp. ${c.page_start}–${c.page_end}`
    : `p. ${c.page_start}`;
}

/** The passage text with its own section heading removed.
 *
 *  The chunker prepends the section path to the stored text, and the view
 *  renders that heading too, so without this ~3 lines of every result were the
 *  line above it repeated -- the single biggest source of noise in the old
 *  card. Compared on collapsed whitespace and with the separator normalised,
 *  because the stored text writes " > " where the breadcrumb writes " › ". */
export function stripLeadingHeading(text: string, sectionPath: string[]): string {
  if (sectionPath.length === 0) return text;
  const norm = (s: string) => s.replace(/[›>]/g, ">").replace(/\s+/g, " ").trim();
  const heading = norm(sectionPath.join(" > "));
  if (heading.length === 0) return text;
  const lines = text.split("\n");
  let cut = 0;
  let seen = "";
  while (cut < lines.length && norm(seen).length < heading.length) {
    seen += (seen ? " " : "") + lines[cut]!;
    cut += 1;
    if (norm(seen) === heading) return lines.slice(cut).join("\n").trimStart();
  }
  return text;
}

function preview(text: string): string {
  return text.length > PREVIEW_CHARS
    ? text.slice(0, PREVIEW_CHARS).trimEnd() + "…"
    : text;
}

// Display-only names for the publisher codes carried on every chunk. An
// unknown code falls through to itself rather than being hidden, so a new
// publisher reads as its code instead of vanishing.
// Exported so ListFilterValuesView can name a `publisher` filter value from
// the SAME table this view names a chunk's publisher from. A second copy is
// the shape that has already shipped two real drift defects in this repo
// (harness/tools.py's _DOC_TYPES, Upload.tsx's doc_type→publisher map).
export const PUBLISHER_NAMES: Record<string, string> = {
  agao: "Auditor General",
  jlbc: "JLBC",
  governor: "Governor's Office",
  legislature: "Legislature",
  agency: "Agency",
};

function publisherName(p: string): string {
  return PUBLISHER_NAMES[p] ?? p;
}

// Display-only names for the document-type codes, in the plural form the
// filter sentence uses. The authority is data/document-types.yaml, served by
// GET /api/document-types -- but a tool card must never wait on a fetch to
// render, so these are carried here and ANY code without an entry falls
// through to itself ("Looked in afr from FY 2025"). That degradation is the
// safety property: a type added to the registry reads as its own code here,
// never as a wrong name and never as a crash. Nothing functional keys off this
// map -- it is words on a page.
export const DOC_TYPE_NAMES: Record<string, string> = {
  "baseline-book": "Baseline Books",
  "approps-report": "Appropriations Reports",
  afr: "Annual Financial Reports",
  "governors-budget": "Executive Budgets",
  "agency-submission": "Agency Submissions",
  "budget-bill-summary": "Budget Bill Summaries",
  "baseline-per-agency": "Baseline agency pages",
  "approps-per-agency": "Appropriations Report agency pages",
  "s-pdf": "Baseline summary sections",
  "bh-pdf": "Baseline budget history sections",
  "bd-pdf": "Baseline budget detail sections",
  "detailed-list-pdf": "Detailed lists of fund changes",
  "topic-pdf": "Cross-cutting topic reports",
  "budget-bill": "Feed Bills (the General Appropriations Act)",
  "fiscal-note": "Fiscal notes",
};

function docTypeName(t: string): string {
  return DOC_TYPE_NAMES[t] ?? t;
}

/** A filter's values as a list, whether the model sent one or several. */
function valuesOf(
  filters: Record<string, unknown> | undefined,
  key: string,
): string[] {
  const v = filters?.[key];
  if (v == null) return [];
  const list = Array.isArray(v) ? v : [v];
  return list.filter((x) => x != null && String(x).length > 0).map(String);
}

function joinList(items: string[]): string {
  if (items.length <= 1) return items[0] ?? "";
  if (items.length === 2) return `${items[0]} and ${items[1]}`;
  return `${items.slice(0, -1).join(", ")} and ${items[items.length - 1]}`;
}

/** "Looked in Annual Financial Reports from FY 2025." -- or "" when the model
 *  searched without narrowing anything.
 *
 *  The field NAME is never printed. `doc_type: afr` told the analyst about our
 *  database and nothing about their question; every clause here is written so
 *  the value carries the meaning on its own. Unknown keys are skipped rather
 *  than dumped, and the tool schema forbids them anyway
 *  (`additionalProperties: false` in harness/tools.py). */
function describeFilters(filters: Record<string, unknown> | undefined): string {
  if (!filters || typeof filters !== "object") return "";

  const types = valuesOf(filters, "doc_type").map(docTypeName);
  const pubs = valuesOf(filters, "publisher").map(publisherName);
  // A slug is a code, not a name -- "agency:ahcccs" reads as a database
  // value. Most JLBC agency slugs are acronyms, so uppercasing the stripped
  // remainder ("AHCCCS") reads correctly; a non-acronym slug still reads as a
  // deliberate short code rather than a raw value, which is the best
  // available without an agency-name lookup this view does not have.
  const agencies = valuesOf(filters, "agency_canonical_id").map((a) =>
    a.replace(/^agency:/, "").toUpperCase(),
  );
  const funds = valuesOf(filters, "fund_canonical_id").map((f) =>
    f.replace(/^fund:/, "").toUpperCase(),
  );
  const years = valuesOf(filters, "fiscal_year").map((y) => `FY ${y}`);
  const isTable = filters["is_table"];

  if (
    types.length === 0 &&
    pubs.length === 0 &&
    agencies.length === 0 &&
    funds.length === 0 &&
    years.length === 0 &&
    typeof isTable !== "boolean"
  ) {
    return "";
  }

  // Built as one noun phrase rather than a list of clauses, so that any SUBSET
  // of the six filters still reads as English. A clause list produced "Looked
  // from FY 2025." the moment the model sent a year on its own.
  let scope = types.length > 0 ? joinList(types) : "documents";
  if (pubs.length > 0) scope += ` published by ${joinList(pubs)}`;

  const tail: string[] = [];
  if (agencies.length > 0) tail.push(` for ${joinList(agencies)}`);
  if (funds.length > 0) tail.push(` in the ${joinList(funds)} fund`);
  if (years.length > 0) tail.push(` from ${joinList(years)}`);
  if (isTable === true) tail.push(", tables only");
  if (isTable === false) tail.push(", prose only");

  return `Looked in ${scope}${tail.join("")}.`;
}

/** What the search did and what came back, in one sentence. */
function describeSearch(
  filters: Record<string, unknown> | undefined,
  passages: number,
  documents: number,
): string {
  const where = describeFilters(filters);
  const found =
    passages === 0
      ? "Found nothing."
      : `Found ${passages} passage${passages === 1 ? "" : "s"} across ` +
        `${documents} document${documents === 1 ? "" : "s"}.`;
  return where ? `${where} ${found}` : found;
}

export default function RetrieveView({ tool }: { tool: ToolBlock }) {
  // The card header already shows the query string; we don't echo it here.
  const filters = tool.input.filters as Record<string, unknown> | undefined;
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseRetrieveOutput(tool.output);
  const [showAll, setShowAll] = useState(false);

  const groups = parsed ? groupByDocument(parsed.chunks) : [];
  const shown = showAll ? groups : groups.slice(0, VISIBLE_GROUPS_DEFAULT);

  return (
    <div className="chat-stack">
      {parsed && (
        <p className="chat-search-summary">
          {describeSearch(filters, parsed.chunks.length, groups.length)}
        </p>
      )}

      {shown.map((g) => (
        <div className="chat-doc-group" key={g.doc_id}>
          <div className="chat-doc-head">
            <span className="chat-doc-title">{g.doc_title}</span>
            <Chip>{publisherName(g.publisher)}</Chip>
            {g.fiscal_year != null && <Chip>FY {g.fiscal_year}</Chip>}
          </div>
          {g.best.section_path.length > 0 && (
            // Where in the document the strongest passage sits. Rendered ONCE,
            // here -- stripLeadingHeading takes the same words back out of the
            // passage text below.
            //
            // TC18: the breadcrumb reduces to the LEAF heading only -- the full
            // ancestor chain ("Note 1. — Summary › Note 3. — Statement of
            // Expenditures") is the noise this element exists to delete, not
            // information worth keeping at this size.
            <div className="chat-doc-path">
              {g.best.section_path[g.best.section_path.length - 1]}
            </div>
          )}
          <div className="chat-doc-text">
            {preview(stripLeadingHeading(g.best.text, g.best.section_path))}
          </div>
          <div className="chat-doc-pages">
            <span className="chat-muted">
              {g.count} passage{g.count === 1 ? "" : "s"}
              {g.pages.length > 0 ? " —" : ""}
            </span>
            {g.pages.map((p) => (
              <Chip key={p}>{p}</Chip>
            ))}
          </div>
        </div>
      ))}

      {groups.length > VISIBLE_GROUPS_DEFAULT && (
        <button
          type="button"
          onClick={() => setShowAll((v) => !v)}
          className="chat-more"
        >
          {showAll
            ? "Show fewer"
            : `Show ${groups.length - VISIBLE_GROUPS_DEFAULT} more documents`}
        </button>
      )}

      {!parsed && !error && tool.output && (
        // Output present but not parseable as the expected shape — show the
        // raw text so the analyst can still see what came back.
        <div className="chat-block">
          <pre>{tool.output}</pre>
        </div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
