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

import re
import unicodedata
from typing import Sequence

from pydantic import BaseModel

from retrieval import pipeline
from retrieval.pipeline import DEFAULT_CORPUS
from store.chunk_store import CORPUS_TABLES, ChunkStore

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


# How many normalized occurrences of a quote we bother locating before
# saying "and more". Mirrors the exact-match duplicate scan below: the
# error only needs to prove ambiguity, not enumerate it.
_MAX_REPORTED_POSITIONS = 3

# Outer punctuation trimmed off the model's quote before matching. A
# quote captured with a trailing period or a leading comma is the same
# quote; INTERIOR punctuation (the commas in `$17,337,200`, the period in
# `$2.1 billion`) must still match, so this only touches the ends.
_OUTER_PUNCT = re.compile(r"^[\s.,;:!?]+|[\s.,;:!?]+$")

# Quote glyphs and dashes that a PDF, an ingest pipeline, and a model
# each spell differently for the same character.
_FOLD_CHARS = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "–": "-", "—": "-", "−": "-",
    "‐": "-", "‑": "-", "‒": "-",
}

# ASCII punctuation a markdown backslash may legally escape (CommonMark
# §2.4). MinerU emits `\$` so `$…$` is not parsed as math, plus `\(`,
# `\)`, `\[`, `\]` in similar contexts.
_ESCAPABLE = set("\\`*_{}[]()#+-.!|>~$")


# ---------------------------------------------------------------------------
# S23 — normalization-tolerant matching
# ---------------------------------------------------------------------------


def normalize_for_match(text: str) -> tuple[str, list[int]]:
    """Fold formatting noise out of `text`, keeping a way back.

    Returns `(normalized, index_map)` where `index_map[i]` is the index
    in the ORIGINAL string of the character that produced
    `normalized[i]`. That map is the whole point: a match found at
    normalized position N has to be reported to the caller as a span in
    the original text, because `resolved_span_start/end` are what the PDF
    bbox highlighter and the cited-text panel slice `chunk.text` with. A
    normalized offset escaping into those fields would highlight the
    wrong words while reporting success — the silent-wrong-answer shape
    Invariant 1 exists to prevent.

    THIS IS A PORT of the webapp's `normalizeForMatch`
    (`webapp/src/chat/citation-extract.ts`), deliberately kept
    semantically identical rather than reinvented: the same chunk text is
    normalized on both sides of the wire — here to resolve the model's
    quote, there to find that quote in the PDF text layer — and two
    dialects would disagree about where a citation points.

    What it folds, and why each one is a real observed drift:
      * NFKC compatibility forms (ligatures like `ﬁ` → `fi`).
      * Markdown backslash escapes — MinerU's `\\$` vs the model's `$`.
      * Accounting-negative parens: `$(10,000)` and `($10,000)` are the
        same figure written two ways (MinerU prefers the first, pdfjs
        emits the second).
      * Markdown emphasis / code / link syntax — the model quotes what it
        reads rendered, not the asterisks around it.
      * Table pipes → space, so cells separate cleanly.
      * Whitespace runs → one space (a PDF line break inside a sentence).
      * Smart quotes and dashes → their ASCII spelling.
      * Case.

    What it does NOT fold: word order, wording, numbers, or anything else
    that would let a paraphrase pass as a quote. This is a FORMATTING
    tolerance, never a semantic one — Invariant 2 is unchanged.

    DIVERGENCE FROM THE TS, deliberate and the safer direction: the
    webapp NFKC-normalizes the whole string at once and, when that
    changes the length, approximates the index map proportionally. Here
    NFKC is applied per code point, so every normalized character has an
    EXACT original index. The two differ only where NFKC composition
    spans adjacent characters (a base letter plus a combining accent),
    which does not occur in this corpus — and where they would differ,
    an exact map is the one that cannot mis-highlight.
    """
    # Per-code-point NFKC, carrying each output char's original index.
    folded: list[str] = []
    origin: list[int] = []
    for index, char in enumerate(text):
        for produced in unicodedata.normalize("NFKC", char):
            folded.append(produced)
            origin.append(index)

    out: list[str] = []
    index_map: list[int] = []
    in_whitespace = False
    # Open accounting-negative parens we collapsed and still owe a close
    # for. Without the counter, the close-paren skip would fire on an
    # unrelated `)` later in the text.
    accounting_depth = 0
    i = 0
    size = len(folded)
    while i < size:
        char = folded[i]
        original_index = origin[i]

        # `\X` renders as `X` alone. Skipping the backslash without
        # emitting means the following character's index_map entry points
        # at THAT character, not at the backslash — so a highlight of
        # `\$17,337,200` starts on the `$`, which is what the PDF text
        # layer actually contains.
        if char == "\\" and i + 1 < size and folded[i + 1] in _ESCAPABLE:
            i += 1
            continue

        # `$(123…` — emit the `$`, drop the paren, remember the close.
        if (
            char == "$"
            and i + 2 < size
            and folded[i + 1] == "("
            and folded[i + 2].isdigit()
        ):
            out.append("$")
            index_map.append(original_index)
            in_whitespace = False
            accounting_depth += 1
            i += 2
            continue
        # `($123…` — drop the paren; the next pass emits the `$`.
        if (
            char == "("
            and i + 2 < size
            and folded[i + 1] == "$"
            and folded[i + 2].isdigit()
        ):
            accounting_depth += 1
            i += 1
            continue
        if char == ")" and accounting_depth > 0:
            accounting_depth -= 1
            i += 1
            continue

        # Markdown emphasis / strikethrough / inline code delimiters.
        if char in "*_" and i + 1 < size and folded[i + 1] == char:
            i += 2
            continue
        if char in "*_":
            i += 1
            continue
        if char == "~" and i + 1 < size and folded[i + 1] == "~":
            i += 2
            continue
        if char == "`":
            i += 1
            continue

        # `[label](url)` — keep the label, drop the syntax and the URL.
        if char == "[":
            close_bracket = _find(folded, "](", i)
            if close_bracket > i and _find(folded, ")", close_bracket + 2) > close_bracket:
                i += 1
                continue
        if char == "]" and i + 1 < size and folded[i + 1] == "(":
            close_paren = _find(folded, ")", i + 2)
            if close_paren > i:
                i = close_paren + 1
                continue

        # Table cell separator behaves as whitespace.
        if char == "|" or char.isspace():
            if not in_whitespace:
                out.append(" ")
                index_map.append(original_index)
                in_whitespace = True
            i += 1
            continue

        in_whitespace = False
        out.append(_FOLD_CHARS.get(char, char.lower()))
        index_map.append(original_index)
        i += 1

    return "".join(out), index_map


def _find(chars: list[str], needle: str, start: int) -> int:
    """`list.index`-style search for a short literal in a char list.
    Returns -1 when absent, matching `str.find`'s contract."""
    limit = len(chars) - len(needle)
    for position in range(start, limit + 1):
        if all(chars[position + offset] == needle[offset] for offset in range(len(needle))):
            return position
    return -1


def find_normalized_occurrences(
    haystack: str, needle: str, *, limit: int
) -> tuple[list[tuple[int, int]], bool]:
    """Locate `needle` inside `haystack` ignoring formatting.

    Returns `(spans, has_more)` where each span is a `[start, end)` range
    in the ORIGINAL `haystack` and `has_more` says whether the scan hit
    `limit` with occurrences still unreported. Spans are found the same
    way the exact scan finds duplicates — advancing one character at a
    time, so overlapping repeats count as the separate ambiguities they
    are.
    """
    if not needle:
        return [], False
    normalized_haystack, index_map = normalize_for_match(haystack)
    normalized_needle, _ = normalize_for_match(needle)
    trimmed = _OUTER_PUNCT.sub("", normalized_needle)
    if not trimmed:
        return [], False

    spans: list[tuple[int, int]] = []
    cursor = 0
    while True:
        found = normalized_haystack.find(trimmed, cursor)
        if found < 0:
            break
        if len(spans) >= limit:
            return spans, True
        spans.append(_original_span(haystack, index_map, found, len(trimmed)))
        cursor = found + 1
    return spans, False


def _original_span(
    haystack: str, index_map: list[int], start: int, length: int
) -> tuple[int, int]:
    """One normalized match → its `[start, end)` range in the original."""
    start_original = index_map[start]
    last_normalized = start + length - 1
    end_original = index_map[last_normalized] + 1
    # A whitespace RUN collapsed to a single normalized space, so the
    # match's last character may be followed by more original whitespace
    # that belongs inside the span. Walk forward only over characters no
    # later normalized character claims, so the span can never swallow
    # text beyond the match.
    while (
        end_original < len(haystack)
        and haystack[end_original].isspace()
        and last_normalized + 1 < len(index_map)
        and index_map[last_normalized + 1] > end_original
    ):
        end_original += 1
    return start_original, end_original


# ---------------------------------------------------------------------------
# Storage read
# ---------------------------------------------------------------------------


def _require_known_corpus(corpus: str) -> None:
    """Reject a typo'd corpus name, always — before any early return.

    WHY this is checked here and not left to the store: both entry points
    below short-circuit on empty input without reading anything, so a bad
    name on a zero-item call would sail straight past the store's own
    check and look like a successful no-op. And a zero-citation call is a
    DOCUMENTED normal path (see validate_cites), so without this the
    expected-empty case and the caller-typo case are indistinguishable.
    The corpus name is a caller-supplied constant — it is wrong or right
    regardless of how many chunk_ids came with it.

    The list of valid names has one home, `store.chunk_store.CORPUS_TABLES`,
    which is what the store's own validator reads too. We re-state the
    message rather than call that validator because it is private to the
    store package; the wording is kept identical so a caller never sees
    two different errors for the same mistake.
    """
    if corpus not in CORPUS_TABLES:
        raise ValueError(
            f"Unknown corpus table {corpus!r}. "
            f"Valid names are: {', '.join(CORPUS_TABLES)}."
        )


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
    An unknown name raises rather than quietly returning nothing, so a
    typo can't look like a corpus full of missing chunks — including on
    an empty call, which never reaches the store at all.

    doc_type used to require a JOIN against `documents`; on LanceDB it is
    denormalized onto the chunk row, so it comes along for free.
    """
    _require_known_corpus(corpus)
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
    citation" would be more annoying than helpful. The corpus name is
    still validated first, so an empty batch can't mask a typo.
    """
    _require_known_corpus(corpus)
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


def _ambiguous_quote_error(positions: Sequence[int], has_more: bool) -> str:
    """The one wording for "your quote matches more than one place".

    Shared by the exact and the normalized paths so the model never sees
    two different sentences for the same mistake — and so the positions
    it is told to look at are always indices into chunk.text as the model
    received it, never into some internal normalized form.
    """
    suffix = ", …" if has_more else ""
    pos_str = ", ".join(str(p) for p in positions) + suffix
    return (
        f"quote appears multiple times in chunk.text "
        f"(positions: {pos_str}). Extend the quote with more "
        "surrounding context so it's unique within this chunk."
    )


def _resolve_quote_normalized(
    quote: str, full_text: str, length: int
) -> tuple[tuple[int, int] | None, CiteValidateResponse | None]:
    """S23's fallback: resolve `quote` to ORIGINAL offsets ignoring
    formatting. Returns `(span, None)` on success or `(None, response)`
    with the rejection to send back.

    Reached only after an exact match has already failed, so exact
    matching always wins — a quote that appears verbatim once and
    "loosely" twice resolves to the verbatim one, which is the occurrence
    the model actually copied.
    """
    spans, has_more = find_normalized_occurrences(
        full_text, quote, limit=_MAX_REPORTED_POSITIONS
    )
    if not spans:
        return None, CiteValidateResponse(
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
    if len(spans) > 1:
        return None, CiteValidateResponse(
            ok=False,
            error=_ambiguous_quote_error([start for start, _ in spans], has_more),
            chunk_text_length=length,
        )
    return spans[0], None


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

    `doc_type` is deliberately accepted and never read. The AFR-specific
    alignment check that used to consume it was dropped 2026-05-20, but
    the parameter stays so a future faithfulness verifier (WS3) can start
    using it without re-plumbing every call site. Nothing below branches
    on it, so no chunk gets a different verdict because of its doc_type.
    """
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
            # S23: exact match failed. Before rejecting, try again with
            # FORMATTING folded out — smart quotes, collapsed line
            # breaks, casing, dashes, MinerU's `\$` escapes, markdown
            # emphasis. Dogfood showed the model routinely emitting
            # quotes that are faithful to the chunk and differ from it
            # only by those artifacts; rejecting them burned a retry
            # round-trip on a citation that was never wrong.
            #
            # This is tolerance of SPELLING, not of meaning. The quote
            # must still really be in the chunk and must still be
            # unambiguous, so Invariant 2 is exactly as strong as before.
            resolved, failure = _resolve_quote_normalized(body.quote, full_text, length)
            if failure is not None:
                return failure
            # Falls through to the SAME span sanity checks an exact match
            # gets — a normalized resolution is not a shortcut past
            # span-too-broad or span-out-of-range.
            resolved_span_start, resolved_span_end = resolved
        else:
            # Duplicate-quote check. When the model picks a quote that
            # appears in multiple places in chunk.text we would silently
            # bind to the first occurrence — which is how the PDF
            # highlight sometimes landed on the wrong dollar amount.
            # Bounce the cite back with positions so the model picks a
            # longer / more surrounding-context quote that's unique
            # within the chunk. We list up to 3 positions then `…` so the
            # error stays readable when the quote is degenerate (e.g.
            # "$5M" appearing 20 times in a per-agency summary).
            positions = [idx]
            next_pos = idx + 1
            while len(positions) < _MAX_REPORTED_POSITIONS:
                found = full_text.find(body.quote, next_pos)
                if found == -1:
                    break
                positions.append(found)
                next_pos = found + 1
            has_more = full_text.find(body.quote, positions[-1] + 1) != -1
            if len(positions) > 1:
                return CiteValidateResponse(
                    ok=False,
                    error=_ambiguous_quote_error(positions, has_more),
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
