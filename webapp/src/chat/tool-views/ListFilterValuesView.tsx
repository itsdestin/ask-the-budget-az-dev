// Per-tool body view for `list_filter_values`. The tool returns
//   { field, values: [{ canonical_id, chunk_count, sample_doc_title, name? }] }
// where `field` is one of agency | fund | doc_type | publisher
// (harness/tools.py raises on anything else).
//
// WHY this no longer renders a `canonical_id` / `chunk_count` table (TC20,
// TC21, 2026-08-16): those are internal corpus fields, and a table headed
// "canonical_id" / "chunks" was showing an analyst database plumbing. The
// count is dropped outright: it is a corpus-internal number (chunks, not
// documents) with no honest analyst reading, and showing it invites exactly
// the kind of "why does this agency have 4,812 of something" question the UI
// cannot answer.
//
// 🔴 WHY `sample_doc_title` IS NEVER USED FOR A NAME (whole-branch review,
// 2026-08-16). The first version of this view derived every displayed name
// from `sample_doc_title` — but that field is an EXAMPLE DOCUMENT, so its
// leading phrase is an AGENCY no matter which dimension was listed. On screen
// a `doc_type` listing therefore read "Kinds of document the corpus covers:
// AHCCCS, ADOA", telling a fiscal analyst the corpus holds kinds of document
// that are really agency names. Same falsehood for `publisher` and `fund`.
//
// The authority is already on the wire and was being thrown away:
// harness/tools.py attaches a catalog `name` to every `agency` value, and its
// own comment says why — "the sample title only implies what an id means; the
// catalog states it". Since 2026-08-22 it attaches one to `fund` values too
// (funds/names.py, reading data/fund-catalog.yaml). So the ladder is: catalog
// `name` → the display table for that dimension (shared with RetrieveView,
// never a second copy) → the raw canonical_id. There is deliberately NO
// `sample_doc_title` rung: a wrong name is worse than a raw code, because a
// code is visibly a code and a wrong name is not.
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
import { DOC_TYPE_NAMES, PUBLISHER_NAMES } from "./RetrieveView.js";

type ToolBlock = Extract<AssistantBlock, { kind: "tool" }>;

interface FilterValue {
  canonical_id: string;
  chunk_count: number;
  sample_doc_title: string;
  /** The catalog's real name for this id. Present on `agency` and `fund`
   *  values whenever the respective catalog resolved them (harness/tools.py
   *  `_list_filter_values`), absent on `doc_type` and `publisher`, which have
   *  no catalog of their own (see DOC_TYPE_NAMES / PUBLISHER_NAMES below
   *  instead). Undeclared until 2026-08-16, which is how the view came to
   *  invent names out of `sample_doc_title` instead. */
  name?: string;
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
//
// KEYED ON THE TOOL'S OWN VOCABULARY — `agency | fund | doc_type | publisher`,
// the enum in harness/tools.py. It was first keyed on `retrieve`'s FILTER
// vocabulary (`agency_canonical_id`, `fiscal_year`), which this tool can never
// emit, so the real input "agency" fell through the `??` and the body read
// "What the corpus covers". `tool-display.test.ts` now pins both this table
// and tool-display.ts's against the tool file, so the mismatch cannot recur.
export const FIELD_LABEL: Record<string, string> = {
  agency: "Agencies the corpus covers",
  fund: "Funds the corpus covers",
  doc_type: "Kinds of document the corpus covers",
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

/** The analyst-facing name for one filter value, in the vocabulary of the
 *  DIMENSION that was listed.
 *
 *  1. the catalog `name` the tool attached (agency values), which STATES what
 *     an id means rather than implying it;
 *  2. the display table for that dimension, shared with RetrieveView so the
 *     same code never reads two different ways in one conversation;
 *  3. the raw canonical_id.
 *
 *  `sample_doc_title` is deliberately NOT a rung — see the file header. A
 *  `fund` id the catalog doesn't recognise (or `doc_type/publisher`, which
 *  have no catalog `name` at all) falls through to its display table or its
 *  own raw code; that is the honest degrade, not a gap to fill with a
 *  document title. */
export function valueDisplayName(
  v: { canonical_id: string; name?: string },
  field: string,
): string {
  const name = (v.name ?? "").trim();
  if (name.length > 0) return name;
  if (field === "doc_type") return DOC_TYPE_NAMES[v.canonical_id] ?? v.canonical_id;
  if (field === "publisher") return PUBLISHER_NAMES[v.canonical_id] ?? v.canonical_id;
  return v.canonical_id;
}

export default function ListFilterValuesView({ tool }: { tool: ToolBlock }) {
  const error = tool.isError && tool.output ? tool.output : undefined;
  const parsed = error ? null : parseOutput(tool.output);
  // ONE field drives both the label and the naming. The server's echo wins
  // over the model's argument because the server lowercases and validates it,
  // and it is the value that actually shaped `values` — labelling a list one
  // way while naming its rows another is the defect this file just fixed.
  const field = parsed?.field || ((tool.input.field as string) ?? "");

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
                {valueDisplayName(v, field)}
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
