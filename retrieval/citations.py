"""Citation validation — the code path that enforces Core Invariant 2.

Every claim the system renders must be auditable, and this module is
what decides whether a `cite()` call is admissible: the chunk exists,
the quoted text really appears in it verbatim, the quote is unambiguous
within the chunk, and the resulting span is sane. A cite that fails here
is bounced back to the model with an error string written to be
*actionable* — the model reads it and retries. Treat those strings as a
public contract: the web UI surfaces them to analysts too.

WHY this is a module and not a FastAPI route (moved here 2026-07-30,
Plan 4 Task 2). Two things changed at once:

1. **A second consumer.** Plan 4 replaces the Node MCP server with an
   in-process Python tool loop (`harness/`) that needs to validate cites
   as a function call, not an HTTP round trip. Importing `retrieval.api`
   to get at the logic is not an option: that module builds a FastAPI
   `app` object at import time, so the harness would drag the whole
   sidecar in just to check a quote.
2. **A second corpus.** The logic used to hardcode
   `pipeline.DEFAULT_CORPUS`. Plan 3 adds `fiscal_note_chunks` beside
   `budget_chunks`, and a cite against a fiscal note must be checked
   against fiscal-note text — never against budget text that happens to
   share a chunk_id.

So the pydantic request/response models live HERE and are re-exported by
`retrieval/api.py`; the direction of the dependency is api → citations,
never the reverse.

**Fetch-vs-pure**, resolved deliberately, because both shapes are load
bearing:

* `validate_cite_against_text()` is the pure core. No storage, no
  corpus — you already have the chunk text.
* `fetch_chunk_texts()` is the only storage read, and it is a BULK read.
* `validate_cite()` (one cite) and `validate_cites()` (N cites) compose
  the two. `validate_cites` does exactly ONE store read for all unique
  chunk_ids and then fans out in memory. That is not a micro-
  optimization: the corpus lives on an office SMB share, each read is a
  network round trip, and a 20-cite answer regressed to 20 round trips
  would put ~60s back into the model's turn — the precise problem the
  2026-05-20 cite_batch work removed. Callers validating more than one
  citation must use `validate_cites`, not a loop over `validate_cite`.

There is deliberately no singular `fetch_chunk_text()`. The old one
existed only because a single HTTP endpoint wanted it; `validate_cite()`
now covers that case, and one fetch implementation can't drift from a
second one that doesn't exist.

Every collaborator is injectable (`store=`), mirroring
`retrieval.pipeline.retrieve()`'s convention. Passing nothing uses the
process-wide store singleton, which is the right default: a second
`ChunkStore` would open a second set of LanceDB table handles against
the same files on the share.
"""
from __future__ import annotations

from typing import Sequence

from pydantic import BaseModel

from retrieval import pipeline
from retrieval.pipeline import DEFAULT_CORPUS
from store.chunk_store import ChunkStore

# ---------------------------------------------------------------------------
# Request / response shapes
# ---------------------------------------------------------------------------


class CiteValidateBody(BaseModel):
    chunk_id: str
    # Either (span_start, span_end) OR quote must be supplied. The tool
    # handler also enforces this; the dual-layer check catches calls
    # from any other future client too.
    span_start: int | None = None
    span_end: int | None = None
    # Preferred path post-2026-05-20: the model pastes the exact
    # substring of chunk.text it wants to cite, and the server scans
    # for it. Avoids the 21-occurrence Bash-script workaround past
    # sessions used to compute offsets.
    quote: str | None = None
    # claim_span and confidence are optional for back-compat. They used
    # to drive an alignment check; that check is retired (see
    # validate_cite_against_text) and claim_span now only rides along so
    # the UI can attach the citation chip to the right sentence.
    claim_span: str | None = None
    confidence: str | None = None


class CiteValidateResponse(BaseModel):
    ok: bool
    error: str | None = None
    chunk_text_length: int | None = None
    cited_text_preview: str | None = None
    # When the caller passed a `quote`, the server derives offsets and
    # echoes them back so the UI can attach the bbox highlight at the
    # right position. None when the caller passed offsets directly.
    resolved_span_start: int | None = None
    resolved_span_end: int | None = None
    # True when claim_span was over CLAIM_SPAN_SOFT_LIMIT chars and the
    # server truncated it. The UI still uses the (truncated) claim_span
    # for chip attachment.
    truncated: bool | None = None


# ---------------------------------------------------------------------------
# Tuning constants
# ---------------------------------------------------------------------------

# When the model picks span_start=0 / span_end=len(chunk), the bbox
# highlight covers the whole chunk and the user sees a giant useless
# rectangle. 2500 chars is roughly a multi-paragraph passage; longer is
# almost always the "I'm citing the whole chunk because I'm not sure
# where the support is" pattern.
SPAN_BREADTH_LIMIT = 2500
# Auto-clamp threshold for span_end overflow. When the model picks a
# span_end slightly past chunk_text length (off-by-one through ~5%
# of chunk length, OR ≤50 chars in absolute terms), the validator
# clamps to the chunk length and proceeds. Larger overflows still
# reject with the chunk_text_length echo so the model can self-correct.
# Empirically, off-by-1 to off-by-50 was ~half the span-out-of-range
# failures in the 2026-05-12 audit — pure model imprecision, not a
# sign the cite is fundamentally wrong.
SPAN_END_CLAMP_ABS = 50
SPAN_END_CLAMP_RATIO = 0.05
# Past sessions had 7 cite calls rejected at this boundary. Truncating-
# and-flagging beats rejecting outright, because the UI's chip-attachment
# substring search still works on the truncated form.
CLAIM_SPAN_SOFT_LIMIT = 500
# Longest cited_text_preview echoed back to the model.
PREVIEW_LIMIT = 500
# The one error string callers pattern-match on. Kept as a constant so a
# second consumer can compare against it without re-typing the literal.
UNKNOWN_CHUNK_ID_ERROR = "unknown chunk_id"


# ---------------------------------------------------------------------------
# Storage read
# ---------------------------------------------------------------------------


def fetch_chunk_texts(
    chunk_ids: Sequence[str],
    *,
    corpus: str = DEFAULT_CORPUS,
    store: ChunkStore | None = None,
) -> dict[str, tuple[str, str | None]]:
    """Bulk fetch (text, doc_type) for a list of chunk_ids in one store
    read. Returns only the rows that exist; the caller decides how to
    handle missing ids (typically: emit `unknown chunk_id` in the
    corresponding response slot). Dedups the input list first so a repeated
    chunk_id costs one row, not N.

    This is the optimization that makes `validate_cites` fast: instead
    of N individual lookups (one per cite() call), it does one
    `chunk_id IN (...)` read for all unique chunks and fans out
    in-memory. For a typical analyze-shaped answer with 20 cites against
    4-5 unique chunks, that's one read of 5 rows instead of 20 reads of 1 —
    and on the office share each read is a network round trip.

    `corpus` names the LanceDB table (see store.chunk_store.CORPUS_TABLES).
    An unknown name raises from the store rather than quietly returning
    nothing, so a typo can't look like a corpus full of missing chunks.

    doc_type used to require a JOIN against `documents`; on LanceDB it is
    denormalized onto the chunk row, so it comes along for free.
    """
    if not chunk_ids:
        return {}
    unique_ids = list(set(chunk_ids))
    store = store if store is not None else pipeline._get_store()
    rows = store.get_by_ids(corpus, unique_ids)
    return {
        row["chunk_id"]: (row["text"] or "", row.get("doc_type")) for row in rows
    }


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_cite(
    body: CiteValidateBody,
    *,
    corpus: str = DEFAULT_CORPUS,
    store: ChunkStore | None = None,
) -> CiteValidateResponse:
    """Fetch one chunk and validate a single cite against it.

    Use `validate_cites` when there is more than one citation — this
    function costs one store read per call, and N of them is exactly the
    round-trip pileup the batch path exists to avoid.
    """
    fetched = fetch_chunk_texts([body.chunk_id], corpus=corpus, store=store).get(
        body.chunk_id
    )
    if fetched is None:
        return CiteValidateResponse(ok=False, error=UNKNOWN_CHUNK_ID_ERROR)
    full_text, doc_type = fetched
    return validate_cite_against_text(body, full_text, doc_type)


def validate_cites(
    bodies: Sequence[CiteValidateBody],
    *,
    corpus: str = DEFAULT_CORPUS,
    store: ChunkStore | None = None,
) -> list[CiteValidateResponse]:
    """Validate N cites with ONE store read. Order is preserved and
    entries are independent — one bad cite does NOT poison the batch, so
    the caller can re-pair results with the model's arguments by index.

    Why batch: the 2026-05-20 dogfood pass measured cite() round-trip cost
    at ~3s/call. An analyze-shaped answer with 15-20 cites was therefore
    eating 45-60s of LLM-turn cycle time just in serial round-trips, even
    before failures and retries kicked in. The model already wants to emit
    all citations at once after writing its answer.

    Empty input is allowed (returns []) — the model may hand over zero
    citations if it changed its mind, and "you must provide at least one
    citation" would be more annoying than helpful.
    """
    if not bodies:
        return []
    chunk_map = fetch_chunk_texts(
        [item.chunk_id for item in bodies], corpus=corpus, store=store
    )
    out: list[CiteValidateResponse] = []
    for item in bodies:
        fetched = chunk_map.get(item.chunk_id)
        if fetched is None:
            out.append(
                CiteValidateResponse(ok=False, error=UNKNOWN_CHUNK_ID_ERROR)
            )
            continue
        full_text, doc_type = fetched
        out.append(validate_cite_against_text(item, full_text, doc_type))
    return out


def validate_cite_against_text(
    body: CiteValidateBody,
    full_text: str,
    doc_type: str | None,
) -> CiteValidateResponse:
    """Pure (storage-free) validation of a single cite call against a
    chunk's text. Split out from the fetching wrappers so the batch path
    can fan out across many citations after a single bulk chunk fetch.
    Caller is responsible for confirming the chunk exists; when it
    doesn't, emit the `unknown chunk_id` response instead of calling this
    function.

    `doc_type` is currently unused (the AFR-specific alignment check
    that consumed it was dropped 2026-05-20); kept as a parameter so a
    future faithfulness verifier (WS3) can wire back in without
    re-plumbing the call site.
    """
    del doc_type  # explicit acknowledgement that the alignment path retired
    length = len(full_text)

    # Resolve quote → offsets. When BOTH quote and offsets are supplied,
    # offsets win (back-compat per the schema doc's disposition rule). When
    # only quote is supplied, we scan chunk.text and derive the offsets.
    resolved_span_start = body.span_start
    resolved_span_end = body.span_end
    if resolved_span_start is None or resolved_span_end is None:
        if not body.quote:
            return CiteValidateResponse(
                ok=False,
                error=(
                    "cite() requires either (span_start, span_end) OR "
                    "quote. Pass the exact quoted substring of chunk.text "
                    "as `quote` and the server derives the offsets."
                ),
                chunk_text_length=length,
            )
        idx = full_text.find(body.quote)
        if idx < 0:
            return CiteValidateResponse(
                ok=False,
                error=(
                    "quote not found in chunk.text — the substring you "
                    "supplied as `quote` does not appear verbatim in the "
                    "chunk. Pick text that exists in the chunk (read the "
                    "retrieve() result's `text` field) or retrieve a "
                    "different chunk."
                ),
                chunk_text_length=length,
            )

        # Duplicate-quote check. When the model picks a quote that
        # appears in multiple places in chunk.text we would silently bind
        # to the first occurrence — which is how the PDF highlight
        # sometimes landed on the wrong dollar amount. Bounce the cite
        # back with positions so the model picks a longer / more
        # surrounding-context quote that's unique within the chunk.
        # We list up to 3 positions then `…` so the error stays readable
        # when the quote is degenerate (e.g. "$5M" appearing 20 times
        # in a per-agency summary).
        positions = [idx]
        next_pos = idx + 1
        while len(positions) < 3:
            found = full_text.find(body.quote, next_pos)
            if found == -1:
                break
            positions.append(found)
            next_pos = found + 1
        has_more = full_text.find(body.quote, positions[-1] + 1) != -1
        if len(positions) > 1:
            suffix = ", …" if has_more else ""
            pos_str = ", ".join(str(p) for p in positions) + suffix
            return CiteValidateResponse(
                ok=False,
                error=(
                    f"quote appears multiple times in chunk.text "
                    f"(positions: {pos_str}). Extend the quote with more "
                    "surrounding context so it's unique within this chunk."
                ),
                chunk_text_length=length,
            )

        resolved_span_start = idx
        resolved_span_end = idx + len(body.quote)

    # Soft-clamp claim_span. Past sessions had 7 cite calls rejected at
    # the 500-char boundary; truncating-and-flagging is better than
    # rejecting outright because the UI's chip-attachment substring
    # search still works on the truncated form.
    truncated_flag: bool | None = None
    claim_span_effective = body.claim_span
    if (
        claim_span_effective is not None
        and len(claim_span_effective) > CLAIM_SPAN_SOFT_LIMIT
    ):
        claim_span_effective = claim_span_effective[:CLAIM_SPAN_SOFT_LIMIT]
        truncated_flag = True

    # Negative starts and inverted ranges remain hard errors.
    if resolved_span_start < 0 or resolved_span_end <= resolved_span_start:
        return CiteValidateResponse(
            ok=False,
            error="span out of range",
            chunk_text_length=length,
            truncated=truncated_flag,
        )
    # Auto-clamp small overflows.
    effective_span_end = resolved_span_end
    if resolved_span_end > length:
        overflow = resolved_span_end - length
        clamp_budget = max(
            SPAN_END_CLAMP_ABS, int(length * SPAN_END_CLAMP_RATIO)
        )
        if overflow <= clamp_budget:
            effective_span_end = length
        else:
            return CiteValidateResponse(
                ok=False,
                error="span out of range",
                chunk_text_length=length,
                truncated=truncated_flag,
            )

    cited = full_text[resolved_span_start:effective_span_end]
    cited_len = effective_span_end - resolved_span_start
    preview = cited[:PREVIEW_LIMIT]

    if cited_len > SPAN_BREADTH_LIMIT:
        return CiteValidateResponse(
            ok=False,
            error=(
                f"span too broad: {cited_len} chars cited "
                f"(limit {SPAN_BREADTH_LIMIT}). Narrow span_start / "
                "span_end (or pick a shorter quote) to the specific "
                "sentence or table row that supports the claim — broad "
                "spans produce useless PDF highlights and usually "
                "indicate uncertainty about where the support is."
            ),
            chunk_text_length=length,
            cited_text_preview=preview,
            resolved_span_start=resolved_span_start,
            resolved_span_end=effective_span_end,
            truncated=truncated_flag,
        )

    # The content-word-overlap alignment check used to live here, but
    # dogfood (2026-05-20) showed it had a ~40% false-rejection rate —
    # the model often picks quotes whose words don't textually overlap
    # the user-facing answer prose (e.g. cites a chunk with
    # "$17,337,200" while writing "$17.3M" in the answer; cites a
    # narrative chunk while writing the claim as a markdown table row).
    # The retry loop the rejection triggered added 30-60s per query and
    # produced apologetic meta-narration in the visible answer.
    #
    # The check was a STRING-OVERLAP HEURISTIC, not a real faithfulness
    # check (Invariant 2's actual guarantor — WS3 / NLI verifier — is
    # still unbuilt). What it caught: cosmetic mismatches between the
    # model's wording and the chunk's wording. What it missed:
    # semantically-wrong-but-overlap-passing citations. Removing it does
    # not lose protection we had; it surfaces what we never had to
    # begin with. The helper functions it used (normalize / content-word
    # / AFR-currency matching) were deleted 2026-07-30 once nothing had
    # called them for two months — see git history if WS3 wants a
    # starting point rather than a clean sheet.
    #
    # What we keep (real protection):
    #   - chunk_id must exist in the corpus (catches invented chunks)
    #   - quote must appear verbatim in chunk.text (catches invented
    #     quotes — the only way the model can fake a citation today)
    #   - quote must be UNIQUE in chunk.text (catches ambiguous cites
    #     that would highlight the wrong figure)
    #   - span_out_of_range / span_too_broad sanity checks
    return CiteValidateResponse(
        ok=True,
        chunk_text_length=length,
        resolved_span_start=resolved_span_start,
        resolved_span_end=effective_span_end,
        truncated=truncated_flag,
    )
