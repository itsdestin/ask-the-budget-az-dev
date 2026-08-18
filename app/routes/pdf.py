"""GET /api/pdf/{doc_id} — Range-aware PDF streaming (Plan 4 Task 8).

PDF.js loads a document in ~64 KB windows over HTTP Range requests. Serving
the whole file as one 200 response would mean the analyst waits for a 400-page
Appropriations Report to download before page 1 draws, so this route honors
`Range` and streams only the bytes asked for.

A port of the retired Next.js route (`web/app/api/pdf/[doc_id]/route.ts`) with
two deliberate changes:

  * **No sidecar hop.** The old route asked the FastAPI sidecar on :9200 for
    the doc's on-disk path. Plan 4 has no sidecar; the same fact comes from
    Plan 1's `documents.json` sidecar file directly.
  * **The stored path is treated as untrusted.** `documents.json` lives on an
    office network share that anyone with drive access can edit, and `doc_id`
    arrives in a URL. The old route `fs.stat`'d whatever string it was handed,
    absolute paths included. Here a stored path cannot escape the allowed
    roots, AND cannot reach a non-PDF inside them — the roots contain
    `settings.json` (the API key) and the install directory, so containment
    alone would not be enough. See `_resolve_blob`.

The Range PARSING is a faithful port, quirks included (`parse_range_header`).
"""
from __future__ import annotations

import json
import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse
from starlette.background import BackgroundTask

from store.config import data_dir

router = APIRouter()

# The repo checkout, used only as a fallback root (see _candidate_paths).
# Module-level so tests can repoint it instead of writing into the real repo.
REPO_ROOT = Path(__file__).resolve().parent.parent.parent

# How much of the file to read per yield. Matches PDF.js's own window size:
# small enough that a range request doesn't materialize a whole report in
# memory, large enough that a 40 MB book isn't 40,000 syscalls.
READ_CHUNK_BYTES = 64 * 1024

_RANGE_RE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range_header(header: str | None, size: int) -> tuple[int, int] | None:
    """`Range` -> inclusive (start, end), or None meaning "send the whole file".

    Every branch below is a port of `parseRangeHeader` in the retired
    TypeScript route, and its test suite is the specification:

      * Only the single-range `bytes=` form is honored. Multi-range and other
        units return None (full body) rather than 416 — a full body is always
        a correct answer to a Range request, and PDF.js never sends either.
      * An end past EOF is CLAMPED, not rejected: PDF.js routinely overshoots
        on its trailing fetch and recovers fine when the server caps it.
      * An inverted range (end < start) and a start past EOF are REJECTED
        (-> full body). Both indicate a bug-level header rather than a
        recoverable overshoot, and neither has a sane clamped reading.

    One case the port ADDS: a zero-byte file has no satisfiable range at all.
    Without this guard a suffix range would compute end = -1 and advertise
    `Content-Range: bytes 0--1/0`.
    """
    if not header or size <= 0:
        return None
    match = _RANGE_RE.match(header.strip())
    if not match:
        return None
    start_text, end_text = match.group(1), match.group(2)
    if start_text == "" and end_text == "":
        return None

    if start_text == "":
        # Suffix form: the LAST n bytes.
        suffix = int(end_text)
        if suffix <= 0:
            return None
        return max(0, size - suffix), size - 1

    start = int(start_text)
    if start >= size:
        return None
    if end_text == "":
        return start, size - 1
    end = int(end_text)
    if end < start:
        return None
    return start, min(end, size - 1)


def _document_record(doc_id: str) -> dict[str, Any] | None:
    """One document's metadata from `documents.json`.

    Plan 5 Task 19 made `store.documents` the single reader; this route
    used to borrow `harness.tools`' copy of it, which meant serving a PDF
    imported the whole retrieval + tool-loop stack to read a JSON file.
    """
    from store.documents import document_record

    return document_record(doc_id)


def non_pdf_detail(source_format: str) -> str:
    """The one sentence both routes say about a source with no page image.

    Written for the analyst, not the developer: a DOCX legislative bill (and,
    from Plan 3, a fiscal note) is an ORDINARY source, not an error, so the
    message tells the UI what to show instead rather than apologizing. It
    lives in a function because two routes need the identical words — the PDF
    route's 415 body and `/api/chunks/{chunk_id}`'s `pdf_unavailable_reason`,
    which is what lets the viewer skip the canvas without a wasted round trip
    to a route it already knows will 415.
    """
    return (
        f"This source is a {source_format} file, not a PDF, so there is no "
        "page to display. Show the cited text panel instead — the passage and "
        "its citation are still valid."
    )


def _safe_relative(blob_path: str) -> PurePosixPath | None:
    """Reduce a stored path to a relative, traversal-free one, or None.

    First of two independent guards. `source_blob_path` comes out of a JSON
    file on a shared drive, so it is treated exactly like user input: the
    drive letter / leading slash is dropped, and any `..` segment voids the
    whole path rather than being "cleaned up" (a silently rewritten path is
    how a traversal attempt turns into a mystery 404 instead of a refusal).
    Backslashes are normalized first — the sidecar may have been written on a
    Windows machine, where `..\\..\\x` is the traversal that matters.
    """
    text = blob_path.replace("\\", "/").strip()
    if not text:
        return None
    parts: list[str] = []
    for segment in PurePosixPath(text).parts:
        if segment == "..":
            return None
        # Anchors, not directories. `strip("/")` rather than a literal tuple
        # because a UNC path's anchor is "//" (two slashes), not "/" — and a
        # surviving "//" would silently discard the root this is about to be
        # joined onto, leaving the containment check as the ONLY guard. Two
        # guards that both have to hold is the design; one is not.
        if segment.strip("/") == "" or segment == ".":
            continue
        if segment.endswith(":"):  # a drive letter ("C:") — not a directory
            continue
        parts.append(segment)
    return PurePosixPath(*parts) if parts else None


def _candidate_paths(relative: PurePosixPath) -> Iterator[tuple[Path, Path]]:
    """(root, candidate) pairs to try, best first.

    1. `<data_dir>/<relative>` — the deployed shape: documents.json and the
       blobs travel together on the share.
    2. `<repo>/<relative>` — dev machines, where documents.json records
       repo-relative paths like `data/cached-pdfs/ab/<sha>.pdf` and the blobs
       sit in the repo's download cache.
    3. `<data_dir>/pdfs/<filename>` — spec S7's install layout keeps PDFs in
       a flat `pdfs/` folder, so a sidecar carried over from the machine that
       ingested them still resolves by filename.
    """
    share = data_dir()
    yield share, share / relative
    yield REPO_ROOT, REPO_ROOT / relative
    yield share, share / "pdfs" / relative.name


def _resolve_blob(blob_path: str) -> Path | None:
    """The on-disk file for a stored `source_blob_path`, or None.

    Second guard: every candidate is fully resolved (which collapses symlinks
    as well as any `.`/`..` that survived) and then checked for containment in
    the root it was built from, so a path outside the allowed roots cannot be
    returned even if the sanitizer missed something.

    Third guard, and the one the containment check does NOT cover: the file
    must actually be a `.pdf`. The allowed roots include `<data_dir>`, which is
    where `settings.json` — the OpenRouter API key — lives, and the repo/install
    root, which a share-writer may not otherwise be able to read. Containment
    alone would serve either of those to a sidecar entry claiming
    `{"source_format": "pdf", "source_blob_path": "settings.json"}`. Checked on
    the RESOLVED path as well as the recorded one, so a symlink named `x.pdf`
    pointing at the key file is caught after resolution.
    """
    relative = _safe_relative(blob_path)
    if relative is None or relative.suffix.lower() != ".pdf":
        return None
    for root, candidate in _candidate_paths(relative):
        try:
            resolved = candidate.resolve()
            if resolved.suffix.lower() != ".pdf":
                continue
            if not resolved.is_relative_to(root.resolve()):
                continue
            if resolved.is_file():
                return resolved
        except OSError:
            continue
    return None


def _file_chunks(path: Path, start: int, length: int) -> Iterator[bytes]:
    with path.open("rb") as handle:
        handle.seek(start)
        remaining = length
        while remaining > 0:
            data = handle.read(min(READ_CHUNK_BYTES, remaining))
            if not data:  # truncated under us mid-stream
                return
            remaining -= len(data)
            yield data


@router.get("/api/pdf/{doc_id}")
def get_pdf(doc_id: str, request: Request):
    """Stream a document's PDF bytes, honoring a single `Range`.

    `doc_id` is only ever a dict key into documents.json — it is never joined
    onto a directory — so a traversal-shaped id is an unknown document.
    """
    record = _document_record(doc_id)
    if record is None:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No document named '{doc_id}' is in this corpus. If it was "
                "just ingested, the document index may need rebuilding."
            ),
        )

    source_format = str(record.get("source_format") or "unknown")
    if source_format != "pdf":
        # DOCX legislative bills and (Plan 3) fiscal notes have no page image.
        # This is an ordinary analyst path, not an edge case: the UI is
        # expected to keep the citation and show the passage as text.
        return JSONResponse(
            status_code=415,
            content={
                "detail": non_pdf_detail(source_format),
                "source_format": source_format,
                "doc_id": doc_id,
            },
        )

    blob_path = str(record.get("source_blob_path") or "")
    path = _resolve_blob(blob_path)
    if path is None:
        # 500, not 404: the document IS in the index, so this is a broken
        # deployment (blobs not copied with the corpus, or a hand-edited
        # sidecar), and an admin needs to see the path that failed.
        raise HTTPException(
            status_code=500,
            detail=(
                f"'{doc_id}' is in the document index but its file could not "
                f"be found on disk (recorded as '{blob_path}'). Copy the PDF "
                "cache alongside the corpus, or re-run the ingest."
            ),
        )

    try:
        size = path.stat().st_size
    except OSError as err:
        # The file passed is_file() a moment ago; a failure here means the
        # share blinked. Answer as JSON so the viewer can say something
        # useful instead of showing FastAPI's plain-text 500.
        raise HTTPException(
            status_code=500,
            detail=f"Could not read the source file for '{doc_id}': {err}",
        ) from err

    headers = {
        "Content-Type": "application/pdf",
        # Tells PDF.js it may switch to Range requests for the rest of the doc.
        "Accept-Ranges": "bytes",
        # `private` because the corpus can contain material the office does not
        # want in a shared cache; five minutes covers one reading session.
        "Cache-Control": "private, max-age=300",
    }

    span = parse_range_header(request.headers.get("range"), size)
    if span is None:
        headers["Content-Length"] = str(size)
        return _streamed(_file_chunks(path, 0, size), 200, headers)

    start, end = span
    length = end - start + 1
    headers["Content-Length"] = str(length)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return _streamed(_file_chunks(path, start, length), 206, headers)


def _streamed(
    chunks: Iterator[bytes], status_code: int, headers: dict[str, str]
) -> StreamingResponse:
    """Stream `chunks`, closing them even if the browser hangs up.

    Starlette never closes a response's body iterator itself — it relies on
    the generator being garbage-collected, and on the disconnect path the
    iterator sits in a reference cycle, so the `with path.open(...)` inside
    `_file_chunks` stays open until the cyclic collector happens by. A
    BackgroundTask is the one hook Starlette runs on BOTH the normal and the
    disconnect path, so cleanup rides there instead.

    This is not a rare case: PDF.js abandons in-flight Range requests every
    time the analyst pages, zooms, or closes the viewer. On Windows a leaked
    handle also blocks a re-ingest from overwriting the cached PDF.
    """
    return StreamingResponse(
        chunks,
        status_code=status_code,
        headers=headers,
        background=BackgroundTask(chunks.close),
    )


# ---------------------------------------------------------------------------
# GET /api/chunks/{chunk_id} — what the viewer needs to open one passage
# ---------------------------------------------------------------------------


@router.get("/api/chunks/{chunk_id}")
def get_chunk(
    chunk_id: str,
    corpus: str = Query("budget", pattern="^(budget|fiscal_notes)$"),
):
    """One chunk's provenance fields, for the source viewer.

    WHY this exists (Plan 4 Task 11): in AI Mode the viewer already has
    everything it needs — a `cite()` chip carries the chunk's doc_id, page,
    bbox and text, resolved from the same turn's `retrieve()` output. On the
    SEARCH page there is no citation and no retrieve() envelope, only the
    `chunk_id` a result row was rendered with, so clicking a matching passage
    has to ask for the rest. That click is the search-only half of the G3
    findability check: search without AI must still answer "where does this
    number come from?".

    The field list is deliberately the viewer's appetite and nothing more —
    what PdfPage and CitedTextPanel actually consume — rather than a general
    chunk-dump endpoint that later grows a scoring or embedding field nobody
    renders:

      chunk_id  echoed so a response can be matched to its request when two
                clicks race (the panel drops answers for a stale chunk).
      doc_id    the viewer streams /api/pdf/{doc_id}.
      page      which page to render (1-indexed). Null for a chunk with no
                page — the viewer then shows text only.
      bbox      the strict-bbox restriction for text-layer search. Null is
                meaningful (search the whole page), so it is always present.
      text      the verbatim chunk text: both the highlight search target and
                the cited-text panel's content.
      source_format / pdf_unavailable_reason
                whether this source HAS a page image at all. Comes from
                documents.json, not from the chunk row. Without it the viewer
                would have to provoke a 415 from /api/pdf just to find out,
                and the analyst would watch a canvas try and fail to load a
                DOCX bill. The reason string is the PDF route's own words
                (`non_pdf_detail`), so the two routes cannot drift.

    Not returned: doc_title and fiscal_year. Both callers already hold them
    (a search row and a resolved citation each carry the title they render),
    and the two in-tree title sources disagree — documents.json's
    migration-era titles are rougher than the mockup-index join the search
    provider uses — so serving one here would mean a passage panel whose
    heading contradicts the row that opened it.
    """
    row, record = _chunk_row(chunk_id, corpus)
    source_format = str(record.get("source_format") or "") if record else ""
    bbox = row.get("bbox")
    page = row.get("page")
    return {
        "chunk_id": row.get("chunk_id"),
        "doc_id": row.get("doc_id"),
        "page": int(page) if page is not None else None,
        # LanceDB hands back float32 values (and sometimes a numpy array);
        # normalize to plain floats so the JSON encoder never chokes on a
        # numpy scalar and the client always sees four numbers.
        "bbox": [float(v) for v in bbox] if bbox is not None else None,
        "text": row.get("text") or "",
        # Per-paragraph locators for merged narrative chunks (spec L1),
        # decoded from the JSON column. The viewer passes `lines` back to
        # /locate; null on rows written before the field existed.
        "source_anchor": _decode_anchor(row.get("source_anchor")),
        # "" rather than None when documents.json has no record: the viewer
        # tests `pdf_unavailable_reason`, and an unknown format is not a
        # reason to refuse to try the PDF route.
        "source_format": source_format or None,
        "pdf_unavailable_reason": (
            non_pdf_detail(source_format)
            if source_format and source_format != "pdf"
            else None
        ),
    }


def _chunk_row(chunk_id: str, corpus: str) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """The stored row for one chunk plus its document record.

    Shared by get_chunk and the locate route: both need the identical 404
    (unknown chunk) and 503 (share offline) posture, and two copies of that
    error wording would drift.
    """
    # Imported inside the function for the same reason as _document_record:
    # these modules pull in the retrieval + storage stack, and an app that
    # never opens a passage should not pay to import it.
    from harness.tools import resolve_corpus
    from retrieval import pipeline

    table = resolve_corpus(corpus)
    try:
        # The process-wide store singleton, exactly as retrieval/citations.py
        # does it: a second ChunkStore would open a second set of LanceDB
        # table handles against the same files on the office share.
        rows = pipeline._get_store().get_by_ids(table, [chunk_id])
    except Exception as err:
        # Share offline, missing table, corrupt index. Same posture as the
        # search route: an honest JSON 503 the client can render, never
        # FastAPI's plain-text 500 (which the fetch wrapper cannot parse).
        raise HTTPException(
            status_code=503,
            detail=f"Chunk store unavailable: {type(err).__name__}: {err}",
        ) from err
    if not rows:
        raise HTTPException(
            status_code=404,
            detail=(
                f"No chunk named '{chunk_id}' is in the {corpus} corpus. "
                "Re-run the search — chunk ids change when a document is "
                "re-ingested."
            ),
        )
    return rows[0], _document_record(str(rows[0].get("doc_id") or ""))


def _decode_anchor(raw: Any) -> dict[str, Any] | None:
    """Decode the source_anchor JSON column for a viewer-facing route.

    Unlike retrieval/search_lance.row_to_chunk — which RAISES on malformed
    anchor JSON so a bad writer is loud at query time — this route must
    DEGRADE to null: the viewer treats a missing anchor as "no lines" and
    falls back to page+bbox+scan, while a 500 here would replace the whole
    provenance surface with an error for a field that is only an
    optimization. The loud copy stays in row_to_chunk, where retrieval
    reads the same column for real.
    """
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


# ---------------------------------------------------------------------------
# GET /api/chunks/{chunk_id}/locate — the read-time coordinate map (spec L2)
# ---------------------------------------------------------------------------

# Open PyMuPDF documents, keyed by resolved blob path. PyMuPDF opens are
# cheap on this corpus (measured 0.00s cold for a 23- and a 28-page book)
# but a click burst on one document would re-open it per request; the cache
# bounds that. Evicted docs are CLOSED — the share-handle lesson from
# _streamed applies: a leaked handle on Windows blocks a re-ingest
# overwriting the cached PDF.
_LOCATE_DOC_CACHE_MAX = 8
_locate_doc_cache: dict[str, Any] = {}


def _import_fitz() -> Any | None:
    """PyMuPDF, lazily. The app server never imports it at startup, and a
    broken install (damaged Windows bundle) must read as "no locate" —
    ingest/ladder.py's posture — not as a 500 on a provenance route."""
    try:
        import fitz

        return fitz
    except Exception:
        return None


def _locate_open_doc(fitz: Any, path: Path) -> Any | None:
    key = str(path)
    doc = _locate_doc_cache.pop(key, None)
    if doc is not None:
        _locate_doc_cache[key] = doc  # refresh LRU order
        return doc
    try:
        doc = fitz.open(path)
    except Exception:
        return None
    while len(_locate_doc_cache) >= _LOCATE_DOC_CACHE_MAX:
        _, evicted = _locate_doc_cache.popitem(last=False)
        try:
            evicted.close()
        except Exception:
            pass
    _locate_doc_cache[key] = doc
    return doc


def _locate_candidates(text: str) -> list[str]:
    """Search strings for one cited value, in priority order.

    The measured format drift (2026-08-18 probe, 7/137 figures): the PDF
    text layer prints accounting negatives as `$(546,838,600)` while the
    linker's stored source_text carries `(546,838,600)`, and vice versa —
    a RAW text search sees two different strings where normalizeForMatch
    sees one. So every candidate rides along with its paren-swapped twin.
    The numeric core (no `$`, no parens) is the third tier: it is what
    finds a value when BOTH conventions disagree with the stored form.
    Interior commas/digits are untouched — this is a spelling tolerance,
    never a value tolerance.
    """

    def swapped(s: str) -> str | None:
        if s.startswith("$(") and s.endswith(")"):
            return s[1:]  # drop the $: $(X) -> (X)
        if s.startswith("(") and s.endswith(")"):
            return "$" + s  # (X) -> $(X)
        return None

    out: list[str] = []
    for cand in (text, swapped(text)):
        if cand and cand not in out:
            out.append(cand)
    core = re.sub(r"^[$(\s]+|[\s)]+$", "", text)
    if core and core not in out:
        out.append(core)
    return [c for c in out if c]


def _clip_rect(fitz: Any, page: Any, bbox: Any) -> Any | None:
    """A stored bbox as a PyMuPDF clip rect, in the page's point space.

    Mirrors the viewer's bboxToViewportRect autodetect (PdfPage.tsx,
    verified empirically 2026-05-07): MinerU bboxes are 0–1000 normalized
    per axis, OpenDataLoader's are PDF points, and the discriminator is
    whether any value exceeds the page's larger dimension. Clipping with
    the wrong interpretation would search a postage stamp (normalized
    read as points) or the whole page (points read as normalized) — the
    former silently missing the value, which is the defect this route
    exists to remove.
    """
    if bbox is None or len(bbox) != 4:
        return None
    try:
        values = [float(v) for v in bbox]
    except (TypeError, ValueError):
        return None
    r = page.rect
    if max(values) > max(r.width, r.height):
        values = [
            values[0] / 1000 * r.width,
            values[1] / 1000 * r.height,
            values[2] / 1000 * r.width,
            values[3] / 1000 * r.height,
        ]
    return r & fitz.Rect(*values)


def _search_page(page: Any, candidates: list[str], clip: Any | None) -> list[list[float]] | None:
    for cand in candidates:
        try:
            hits = page.search_for(cand, clip=clip) if clip is not None else page.search_for(cand)
        except Exception:
            continue
        if hits:
            return [[float(h.x0), float(h.y0), float(h.x1), float(h.y1)] for h in hits]
    return None


@router.get("/api/chunks/{chunk_id}/locate")
def locate_chunk(
    chunk_id: str,
    text: str = Query(""),
    corpus: str = Query("budget", pattern="^(budget|fiscal_notes)$"),
):
    """Resolve a cited value to exact PDF rects — the read-time coordmap.

    Spec L2 (2026-08-18-citation-highlight-locate-design.md). The viewer's
    client-side text-layer search misses 44% of correctly linked figures
    (measured on a live run): the stored bbox covered only the chunk's
    first paragraph, the cited value sat on a later page, or accounting
    parens differed between chunk text and PDF text layer. This route
    answers with PyMuPDF's own search — the same ground truth the probe
    validated — in the PDF user-space points the viewer's
    `bboxToViewportRect` already speaks.

    First success wins:
      anchor      a source_anchor.lines entry containing `text` names the
                  paragraph's page + bbox; search clipped to it.
      stored-page search the chunk's stored page (clipped to its bbox).
      scan        every page, first hit (measured 0.04–0.25 s per document,
                  incl. the 191-page AFR).
      none        nothing found, no PDF behind the chunk, or fitz/store
                  unavailable. The viewer then runs its EXISTING chain
                  unchanged — a locate failure can only add precision,
                  exactly as spec A7's fallback rule required of the
                  ingest-time map.

    Rects are in PDF user-space points; `page` is 1-indexed.
    """
    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=400,
            detail="locate needs the cited text to search for (?text=…).",
        )
    row, record = _chunk_row(chunk_id, corpus)
    page_no = row.get("page")
    page_no = int(page_no) if page_no is not None else None
    none = {"chunk_id": chunk_id, "page": page_no, "rects": [], "basis": "none"}
    if not record or str(record.get("source_format") or "") != "pdf":
        # DOCX bills and fiscal notes have no page image; there is nothing
        # to search and the viewer already shows the cited-text panel.
        return none
    path = _resolve_blob(str(record.get("source_blob_path") or ""))
    if path is None:
        return none
    fitz = _import_fitz()
    if fitz is None:
        return none
    doc = _locate_open_doc(fitz, path)
    if doc is None:
        return none

    candidates = _locate_candidates(text)
    anchor = _decode_anchor(row.get("source_anchor")) or {}
    lines = anchor.get("lines") if isinstance(anchor.get("lines"), list) else []

    try:
        # 1. anchor — the line map written at ingest (spec L1). Anchor text
        #    is a substring of chunk text BY CONSTRUCTION, so a
        #    whitespace-collapsed containment test is exact; no
        #    normalization machinery needed.
        collapsed = re.sub(r"\s+", " ", text).strip()
        for line in lines:
            if not isinstance(line, dict):
                continue
            line_text = re.sub(r"\s+", " ", str(line.get("text") or "")).strip()
            if not collapsed or collapsed not in line_text:
                continue
            lp = line.get("page")
            lb = line.get("bbox")
            if not isinstance(lp, int) or not isinstance(lb, (list, tuple)) or len(lb) != 4:
                continue
            if lp < 1 or lp > doc.page_count:
                continue
            clip = _clip_rect(fitz, doc[lp - 1], lb)
            rects = _search_page(doc[lp - 1], candidates, clip)
            if rects:
                return {"chunk_id": chunk_id, "page": lp, "rects": rects, "basis": "anchor"}

        # 2. stored page, clipped to the stored bbox when present.
        if page_no is not None and 1 <= page_no <= doc.page_count:
            page = doc[page_no - 1]
            clip = _clip_rect(fitz, page, row.get("bbox"))
            rects = _search_page(page, candidates, clip)
            if rects:
                return {"chunk_id": chunk_id, "page": page_no, "rects": rects, "basis": "stored-page"}

        # 3. scan — first hit anywhere. Fixes the wrong-page cases the
        #    stored page cannot see.
        for i in range(doc.page_count):
            rects = _search_page(doc[i], candidates, None)
            if rects:
                return {"chunk_id": chunk_id, "page": i + 1, "rects": rects, "basis": "scan"}
        return none
    except Exception:
        # Any surprise inside fitz (a corrupt page, a search exception on
        # one glyph run) must read as "none", never as a 500: the viewer's
        # contract is that locate only ADDS precision.
        return none
