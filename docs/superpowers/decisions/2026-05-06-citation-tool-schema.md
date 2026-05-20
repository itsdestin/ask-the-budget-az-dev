---
title: Citation tool schema (cite()) — locked for Phase 1b/1c
date: 2026-05-06
status: decided (amended 2026-05-20 — see top of doc)
authors: Destin Moss, Claude
audience: Phase 1b WS6 (retrieval), Phase 1c WS1 (MCP server), Phase 1c WS3 (system prompt + UI rendering)
supersedes_in_part:
  - docs/superpowers/decisions/2026-05-06-phase-1bc-architecture.md (D6 sketch — this doc closes its open item)
---

> ## 2026-05-20 amendments (Phase 1c dogfood hardening)
>
> The schema below is the **2026-05-06 baseline**. The 2026-05-20 dogfood pass surfaced several reliability and latency issues that motivated substantive amendments. Both the original (offset-based) shape and the new (quote-based) shape are still accepted; the new shape is preferred.
>
> **`cite()` input changes:**
>
> - **New `quote: string` field (optional).** The exact substring of chunk.text the model wants to cite. Server scans chunk.text for it and derives `span_start`/`span_end`. Avoids the off-by-one failure mode the offset path produced.
> - **`span_start` and `span_end` are now optional.** Either `(span_start, span_end)` OR `quote` is required (handler validates this at runtime; the schema can't express "exactly one of"). When both are supplied, offsets win (back-compat).
> - **`claim_span.max` raised 500 → 2000.** Server soft-clamps to 500 and flags `truncated: true` instead of rejecting.
>
> **`cite()` response changes:**
>
> - **`resolved_span_start` / `resolved_span_end` added to the success response.** Sidecar-derived positions of the cited text inside chunk.text. The web UI uses these to drive the PDF text-layer search; without them, quote-only cites had to fall back to a `(0, claim_span.length)` sentinel that produced "couldn't pinpoint" badges.
>
> **`cite()` validation changes:**
>
> - **Content-word-overlap alignment check (`_check_alignment`) was dropped.** The check was a string-overlap heuristic, not a real faithfulness check (Invariant 2's actual guarantor is WS3 / NLI verifier, still unbuilt). It produced ~40% false rejections on faithful-but-differently-worded claim_spans and dominated query latency through retry loops.
> - What `/cite/validate` still enforces: chunk_id exists in the corpus, quote appears verbatim in chunk.text, span sanity (negative / inverted / `> SPAN_BREADTH_LIMIT`).
>
> **New companion tool: `cite_batch({citations: [...]})`.** Registers N citations in one MCP round-trip with bulk DB fetch. The model's `cite_batch` tool_use carries an array of single-cite shapes; the response is a parallel array of single-cite results. System prompt steers the model toward `cite_batch` whenever an answer has more than one citation. `cite` (single) stays registered for back-compat.
>
> **`retrieve()` schema additions:**
>
> - **New `intent: "lookup" | "compare" | "analyze"` field (optional).** Question-depth classifier that maps to per-route default top_k (5 / 12 / 18) when no explicit top_k is supplied.
> - **New `deep_dive: boolean` field (optional).** First-call-cap bypass — the FIRST retrieve() of any session is capped to 5 chunks regardless of intent/top_k unless deep_dive:true is passed.
>
> **For the current state of these contracts**, read `retrieval/api.py` (sidecar models), `mcp-server/src/tools/cite.ts`, `mcp-server/src/tools/cite-batch.ts`, and `mcp-server/src/tools/retrieve.ts`. The text below is preserved as the **2026-05-06 baseline** so the schema-evolution audit trail stays legible.

---

# Citation tool schema (`cite()`)

Closes the "Citation tool schema final field names + types" open item from the architecture decisions doc. Schema below is the contract three workstreams will agree against:

- **Phase 1c WS1** — MCP server tool definition (Node, `@modelcontextprotocol/sdk` zod schema)
- **Phase 1c WS3** — system prompt instructions + UI parser of `tool_use` blocks
- **Phase 1b WS6** — retrieval pipeline must return `chunk_id` values that survive round-trip into `cite()` calls

## Tool: `cite`

```ts
{
  name: "cite",
  description:
    "Record that the immediately preceding assistant claim is supported by a specific span " +
    "of a retrieved chunk. Call once per distinct claim. Do NOT invent chunk_ids — only use " +
    "ids returned from a prior retrieve() call in this conversation. The MCP server validates " +
    "chunk_id against the retrieval log and returns ok:false if unknown.",
  input_schema: {
    type: "object",
    required: ["chunk_id", "span_start", "span_end", "confidence", "claim_span"],
    properties: {
      chunk_id: {
        type: "string",
        description:
          "Primary key into the chunks table. Must equal a value returned from retrieve() " +
          "in this conversation. Format: '<doc_id>::<chunk_index>' (opaque from the model's view)."
      },
      span_start: {
        type: "integer",
        minimum: 0,
        description:
          "Character offset (inclusive) into chunk.text where the supporting span begins. " +
          "Use 0 for citing the entire chunk."
      },
      span_end: {
        type: "integer",
        minimum: 1,
        description:
          "Character offset (exclusive) into chunk.text where the supporting span ends. " +
          "Must be > span_start. Use chunk.text.length to cite to the end."
      },
      confidence: {
        type: "string",
        enum: ["verbatim", "paraphrase"],
        description:
          "'verbatim' = the claim_span is a direct quote from chunk.text[span_start:span_end] " +
          "(allowing minor formatting normalization). 'paraphrase' = the claim restates content " +
          "from that span in different words. The post-generation faithfulness verifier uses " +
          "exact-match for verbatim and NLI for paraphrase."
      },
      claim_span: {
        type: "string",
        description:
          "The literal substring of the assistant's just-emitted answer that this citation " +
          "supports. The UI uses this to attach the citation chip to the right text. " +
          "Should be a complete clause or sentence; max ~500 chars."
      }
    }
  }
}
```

### Return shape

```ts
// Success
{ ok: true, citation_id: string }   // citation_id is a server-generated UUID for queries table linking

// Validation failure (chunk_id wasn't returned by a prior retrieve() in this conversation)
{ ok: false, error: "unknown chunk_id" }

// Validation failure (span out of range)
{ ok: false, error: "span out of range", chunk_text_length: number }
```

## Tool: `retrieve` (companion, locked here for completeness)

```ts
{
  name: "retrieve",
  description:
    "Search the Arizona budget corpus and return the most relevant chunks for a query. " +
    "Call this BEFORE answering any user question that asks about budget content. " +
    "You MAY call retrieve() multiple times per turn (e.g., one call per sub-claim, or to " +
    "decompose a comparison question). Use filters when the user's question implies them.",
  input_schema: {
    type: "object",
    required: ["query"],
    properties: {
      query: {
        type: "string",
        description:
          "Natural-language search query. Expand acronyms (e.g., 'AHCCCS' → 'Arizona Health " +
          "Care Cost Containment System AHCCCS'). Be specific; vague queries reduce recall."
      },
      filters: {
        type: "object",
        properties: {
          fiscal_year: {
            type: "array",
            items: { type: "integer", minimum: 2015, maximum: 2030 },
            description: "Restrict to documents covering these fiscal years (any-of)."
          },
          doc_type: {
            type: "array",
            items: { type: "string", enum: ["baseline", "approps", "afr", "sad", "session_law", "primer"] },
            description: "Restrict to document types (any-of)."
          },
          agency_canonical_id: {
            type: "array",
            items: { type: "string" },
            description: "Restrict to chunks tagged with these agency IDs (any-of, GIN-indexed)."
          },
          publisher: {
            type: "array",
            items: { type: "string", enum: ["jlbc", "legislature", "governor", "agao"] },
            description: "Restrict to publishers (any-of)."
          }
        }
      }
    }
  }
}
```

### Return shape

```ts
{
  chunks: Array<{
    chunk_id: string;
    doc_title: string;
    doc_id: string;
    publisher: string;
    fiscal_year: number;
    doc_type: string;
    section_path: string[];           // e.g., ["AHCCCS", "Operating Lump Sum"]
    page_start: number | null;
    page_end: number | null;
    text: string;                      // chunk content; the model cites into this via span_start/span_end
    score: number;                     // post-rerank score, 0..1
  }>;
  top_score: number;                   // max(score) across chunks; 0 if no results
  retrieval_id: string;                // UUID; recorded against the conversation's queries table row
}
```

## Why these field names / types

- **`chunk_id` as opaque string** — the model never composes one; it only echoes back values it received. Server-side validation (does this chunk_id appear in any prior `retrieve()` in this conversation?) prevents hallucinated citations cleanly.
- **`span_start` / `span_end` as char offsets, not byte offsets** — Claude reasons in characters; ParadeDB BM25 results return chunk text as strings; PDF.js extraction is char-indexed. No UTF-8 byte/codepoint mismatch.
- **`confidence` as enum, not float** — two distinct verifier paths (exact-match vs. NLI). A float would invite spurious calibration.
- **`claim_span` as string, not character offsets into the answer** — strings survive streaming + retries cleanly. The UI does substring search to attach the chip, which works because Claude rarely emits the exact same sentence twice in one answer.
- **`retrieval_id` returned, not just `top_score`** — letting the MCP server log retrieval calls to the `queries` table and link them by UUID is cleaner than pattern-matching on query strings later. Also lets `cite()` server-side validate that the cited `chunk_id` traces back to a real retrieval, not a hallucination.

## Refusal-threshold enforcement (per spec §11)

The system prompt instructs Claude:

> If `retrieve()` returns `top_score < 0.30`, respond with the exact phrase "I cannot find this in the indexed budget documents." Do NOT call `cite()`. Do NOT speculate.

The MCP server does not enforce this server-side — it returns the chunks and `top_score` and trusts the model to follow the prompt. Faithfulness verifier (post-generation, spec §3.4) catches violations and overwrites the answer if Claude cites a chunk with score below threshold.

Threshold value (`0.30`) is a placeholder; calibrate during Phase 1b WS8 eval.

## What this leaves unsettled

- **The faithfulness verifier's interface.** Verifier reads the assistant's final text plus the list of `tool_use` cite blocks plus the chunks they reference, and decides whether each citation passes. Verifier output reshapes the rendered answer (strips bad citations, swaps in refusal banner). Out of scope for this schema lock; will be designed in Phase 1c WS5.
- **Multi-citation per claim.** Schema permits multiple `cite()` calls per claim_span (model emits two `tool_use` cite blocks pointing at the same span_start..span_end of the answer). UI should render them as a stack of chips. No schema change needed.
- **Page-anchored bounding boxes.** Not in `cite()`. The chunk's bbox lives in `chunks.bbox` (Phase 1b schema); UI looks it up by `chunk_id` to render the highlight. No model-side action needed.
