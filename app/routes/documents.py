"""GET /api/documents/{token} — download a create_document artifact (Plan 4).

The chat UI turns the `download_token` from a `create_document` tool call
into a link to this route. The token is looked up in `harness.documents`'
in-process registry; it is never joined onto a directory, so a token
shaped like a traversal string is an unknown key rather than a dangerous
path.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from harness.documents import lookup

router = APIRouter()

_NOT_FOUND = (
    "Unknown download link. Documents live only for as long as the server "
    "has been running — ask for the document again."
)


@router.get("/api/documents/{token}")
def download_document(token: str) -> FileResponse:
    """Serve one artifact as an attachment.

    NOT single-use, despite the plan's "serves the file once" wording.
    Browsers issue HEAD and range requests, download managers retry, and
    people click a link twice; burning the token on first read would turn
    any of those into a broken download with no way to recover the file
    short of re-asking the model to write it again. The token is 256 bits
    of randomness held in a process-local registry — expiring it after one
    read buys no meaningful security, and costs the primary use case.
    Tokens do die with the process, which is the actual lifetime bound.

    A registered token whose file has since been deleted 404s like an
    unknown one: from the analyst's side "this download is gone" is the
    same situation, and FileResponse would otherwise raise mid-response
    after the 200 header had already gone out.
    """
    artifact = lookup(token)
    if artifact is None or not artifact.path.is_file():
        raise HTTPException(status_code=404, detail=_NOT_FOUND)
    return FileResponse(
        artifact.path,
        media_type=artifact.media_type,
        # Content-Disposition: attachment; filename="…". The name was
        # sanitized when the file was written (harness/documents.py's
        # _safe_stem), so no model-supplied character reaches this header.
        filename=artifact.path.name,
    )
