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
    absolute paths included. Here, escaping the allowed roots is made
    structurally impossible — see `_resolve_blob`.

The Range PARSING is a faithful port, quirks included (`parse_range_header`).
"""
from __future__ import annotations

import re
from pathlib import Path, PurePosixPath
from typing import Any, Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, StreamingResponse

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
    """One document's metadata from Plan 1's `documents.json`.

    REUSES `harness.tools`' mtime-cached reader rather than adding a fourth
    copy of it. There are already three (`retrieval/api.py`,
    `harness/tools.py`, and a partial one inside `app/search_provider.py`);
    consolidating them into `store/documents.py` is a Plan 5 item, and adding
    one more in the meantime is how a reader and a writer end up disagreeing
    about the same file. `retrieval/api.py`'s copy is unusable here because
    importing that module builds a whole FastAPI app at import time.

    Imported inside the function, not at module scope, because `harness.tools`
    drags in the retrieval + storage stack: an app that never serves a PDF
    should not pay for it, and neither should a test that never asks for one.
    """
    from harness.tools import _document_metadata

    record = _document_metadata().get(doc_id)
    return record if isinstance(record, dict) else None


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
        if segment in ("", "/", "."):
            continue
        if segment == "..":
            return None
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
    the root it was built from. Escaping the allowed directories is therefore
    not a matter of getting the sanitizer right — a path outside them cannot
    be returned even if the sanitizer misses something.
    """
    relative = _safe_relative(blob_path)
    if relative is None:
        return None
    for root, candidate in _candidate_paths(relative):
        try:
            resolved = candidate.resolve()
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
                "detail": (
                    f"This source is a {source_format} file, not a PDF, so "
                    "there is no page to display. Show the cited text panel "
                    "instead — the passage and its citation are still valid."
                ),
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
        return StreamingResponse(
            _file_chunks(path, 0, size), status_code=200, headers=headers
        )

    start, end = span
    length = end - start + 1
    headers["Content-Length"] = str(length)
    headers["Content-Range"] = f"bytes {start}-{end}/{size}"
    return StreamingResponse(
        _file_chunks(path, start, length), status_code=206, headers=headers
    )
