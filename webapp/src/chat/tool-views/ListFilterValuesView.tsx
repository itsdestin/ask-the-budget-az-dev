// Per-tool body view for `list_filter_values`. The tool returns
//   { field, values: [{ canonical_id, chunk_count, sample_doc_title }] }
//
// WHY this no longer renders a `canonical_id` / `chunk_count` table (TC20,
// TC21, 2026-08-16): those are internal corpus fields, and a table headed
// "canonical_id" / "chunks" was showing an analyst database plumbing. What an
// analyst can actually use is the AGENCY NAME, which `sample_doc_title`
// already carries — every document title leads with its agency's real name,
// e.g. "AHCCCS — FY 2026 Baseline". The count is dropped outright: it is a
// corpus-internal number (chunks, not documents) with no honest analyst
// reading, and showing it invites exactly the kind of "why does this agency
// have 4,812 of something" question the UI cannot answer.
//
// Deliberately NOT de-duplicated (TC21). Two catalog ids resolving to the
// same displayed name — e.g. two rows both reading "Child Safety" — are a
// real, recorded corpus defect (duplicate agency ids; see STATUS.md's
// "Corpus identity" sections) with its own fix underway elsewhere. Collapsing
// the duplicate here would hide the exact symptom that makes it visible.
//
// Ported from web/components/tool-views/ListFilterValuesView.tsx.

import type { AssistantBlock } from "../chat-types.js";
import { ErrorBlock } from "./primitives.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface FilterValue {
  canonical_id: string;
  chunk_count: number;
  sample_doc_title: string;
}

interface ListFilterValuesOutput {
  field: string;
  values: FilterValue[];
}

// A short lead-in naming what kind of thing is listed below, in plain
// English. Kept local to this view rather than shared with tool-display.ts's
// own field→noun mapping (used for the collapsed header sentence) — the two
// call sites want differently-shaped phrases ("which agencies the corpus
// covers" vs. a label over a list) and a shared table would couple two
// independent copy decisions for no real benefit.
const FIELD_LABEL: Record<string, string> = {
  agency_canonical_id: "Agencies the corpus covers",
  doc_type: "Kinds of document the corpus covers",
  fiscal_year: "Years the corpus covers",
  publisher: "Publishers the corpus covers",
};

function fieldSentence(field: string): string {
  return FIELD_LABEL[field] ?? "What the corpus covers";
}

function parseOutput(raw: string | undefined): ListFilterValuesOutput | null {
  if (!raw) return null;
  try {
    const parsed: unknown = JSON.parse(raw);
    if (
      typeof parsed === "object" &&
      parsed !== null &&
      "field" in parsed &&
      "values" in parsed &&
      Array.isArray((parsed as { values: unknown }).values)
    ) {
      return parsed as ListFilterValuesOutput;
    }
  } catch {
    // fall through
  }
  return null;
}

/** The analyst-facing name for a filter value. `sample_doc_title` already
 *  arrives with every value and begins with the agency's real name, e.g.
 *  "AHCCCS — FY 2026 Baseline". Falls back to the raw id rather than rendering
 *  nothing: a code is ugly, a blank row is a lie about what the corpus holds. */
export function valueDisplayName(v: { canonical_id: string; sample_doc_title?: string }): string {
  const title = (v.sample_doc_title ?? "").trim();
  if (title.length > 0) {
    const head = title.split(/\s+[—–-]\s+/)[0]!.trim();
    if (head.length > 0) return head;
  }
  return v.canonical_id;
}

export default function ListFilterValuesView({ tool }: { tool: ToolBlock }) {
  const field = (tool.input.field as string) || "";
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseOutput(tool.output);

  return (
    <div className="chat-stack">
      {parsed && parsed.values.length > 0 && (
        <>
          <p className="chat-note">{fieldSentence(field)}:</p>
          <div className="chat-filter-values">
            {parsed.values.map((v, i) => (
              // Not keyed on canonical_id: duplicate ids are the exact defect
              // this view must not hide (see the file header), so two rows can
              // legitimately carry the same id and the same name.
              <span key={i} className="chat-chip">
                {valueDisplayName(v)}
              </span>
            ))}
          </div>
        </>
      )}

      {parsed && parsed.values.length === 0 && (
        <div className="chat-note">Nothing found for this search.</div>
      )}

      {error && <ErrorBlock error={error} />}
    </div>
  );
}
