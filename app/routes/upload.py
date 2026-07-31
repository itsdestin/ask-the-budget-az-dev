"""POST /api/upload — the one way a document enters the corpus.

Three responsibilities, in order:

1. **Invariant 8.** The corpus is public-record-only, because AI Mode ships
   retrieved chunk text to an external inference provider. The app cannot
   classify confidentiality, so enforcement is a deliberate human moment: a
   required "this document is public record" checkbox. It gates the ENDPOINT,
   not just the form — a rule enforced only in the UI is not enforced.
2. **Duplicate detection by content hash.** Re-uploading a document that's
   already in the corpus reports when it landed and who added it, with an
   explicit re-process option, instead of silently double-ingesting.
3. **Queue it.** The file is content-addressed into `<data_dir>/uploads/`
   and a job record is written. Everything expensive happens in the worker.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from ingest.dispatcher import EXTRACTOR_REGISTRY
from ingest.driver import make_doc_id
from ingest.jobs import TERMINAL_STATES, load_all, new_job, save
from store.config import data_dir, documents_path

router = APIRouter()

PUBLIC_RECORD_NOTICE = (
    "Only public-record documents may be uploaded — baseline books, "
    "appropriations reports, fiscal notes, bills, executive budget requests, "
    "agency budget requests, and Annual Financial Reports. Confirm the document "
    "is public record before uploading. Confidential state data must never be "
    "placed in this corpus: AI Mode sends retrieved text to an external "
    "inference provider, and anything uploaded here is readable by everyone "
    "with access to the shared drive."
)

# Accepted doc_types are exactly the ones an extractor can handle. Accepting a
# type we can't extract would queue a job guaranteed to fail — better a 422 the
# uploader can act on than a failed job they can't.
ACCEPTED_DOC_TYPES = frozenset(dt for dt, _fmt in EXTRACTOR_REGISTRY)
ACCEPTED_CORPORA = frozenset({"budget", "fiscal_notes"})
ACCEPTED_SUFFIXES = frozenset({".pdf", ".docx"})

# A fiscal year outside this window is a typo (or a page number pasted into
# the wrong box), not a real document.
MIN_FISCAL_YEAR = 1970
MAX_FISCAL_YEAR = 2100

# Read the upload in chunks so a 200 MB Baseline book doesn't sit in memory
# twice (once for the body, once for the hash).
_READ_CHUNK = 1 << 20


@router.post("/api/upload", status_code=202)
async def upload(
    request: Request,
    file: UploadFile = File(...),
    corpus: str = Form(...),
    publisher: str = Form(...),
    doc_type: str = Form(...),
    fiscal_year: str = Form(...),
    title: str = Form(""),
    is_public_record: str = Form(""),
    reprocess: str = Form(""),
):
    # Invariant 8 first — before the file is written anywhere. A rejected
    # upload must leave no trace of the document on the share.
    if not _is_true(is_public_record):
        raise HTTPException(status_code=400, detail=PUBLIC_RECORD_NOTICE)

    year = _validated_year(fiscal_year)
    if corpus not in ACCEPTED_CORPORA:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown corpus {corpus!r}. Choose one of: "
                   f"{', '.join(sorted(ACCEPTED_CORPORA))}.",
        )
    if doc_type not in ACCEPTED_DOC_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown document type {doc_type!r}. Choose one of: "
                   f"{', '.join(sorted(ACCEPTED_DOC_TYPES))}.",
        )

    filename = Path(file.filename or "upload").name
    suffix = Path(filename).suffix.lower()
    if suffix not in ACCEPTED_SUFFIXES:
        raise HTTPException(
            status_code=422,
            detail=f"{filename} is not a PDF or DOCX. This app can only read "
                   "PDF and DOCX documents.",
        )

    sha256, size, staged = await _stage_upload(file, suffix)
    if size == 0:
        staged.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail=f"{filename} is empty.")

    if not _is_true(reprocess):
        existing = _find_duplicate(sha256)
        if existing is not None:
            # JSONResponse, not HTTPException: the frozen contract puts
            # existing_doc_id / added_at / added_by at the TOP level of the
            # body, and HTTPException would nest them under "detail".
            return JSONResponse(status_code=409, content=existing)

    doc_id = make_doc_id(
        publisher=publisher, doc_type=doc_type, fiscal_year=year, filename=filename
    )
    job = new_job(
        doc_id=doc_id,
        title=title.strip() or filename,
        corpus=corpus,
        source_path=staged.relative_to(data_dir()).as_posix(),
        source_sha256=sha256,
        publisher=publisher,
        doc_type=doc_type,
        fiscal_year=year,
        user_title=title.strip(),
    )
    save(job)

    # Start the worker lazily, on first upload, rather than at app startup:
    # it builds the embedding model, and a machine that only ever searches
    # should never pay for that.
    worker = getattr(request.app.state, "ingest_worker", None)
    if worker is not None:
        worker.start()

    return {"job_id": job.job_id, "doc_id": doc_id}


# --- helpers ----------------------------------------------------------------


def _is_true(value: str) -> bool:
    return value.strip().lower() in {"true", "on", "yes", "1"}


def _validated_year(raw: str) -> int:
    try:
        year = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=422, detail=f"Fiscal year {raw!r} is not a number."
        ) from None
    if not MIN_FISCAL_YEAR <= year <= MAX_FISCAL_YEAR:
        raise HTTPException(
            status_code=422,
            detail=f"Fiscal year {year} is outside {MIN_FISCAL_YEAR}–{MAX_FISCAL_YEAR}.",
        )
    return year


async def _stage_upload(file: UploadFile, suffix: str) -> tuple[str, int, Path]:
    """Stream the upload to `<data_dir>/uploads/<sha2>/<sha256><ext>`.

    Written to a temp name first and renamed once the hash is known — the
    final name IS the hash, so it can't be chosen up front, and a partial
    file under the real name would look like a complete cached document.
    """
    uploads = data_dir() / "uploads"
    uploads.mkdir(parents=True, exist_ok=True)
    tmp = uploads / f".incoming-{os.getpid()}-{id(file)}{suffix}"

    digest = hashlib.sha256()
    size = 0
    with tmp.open("wb") as out:
        while True:
            block = await file.read(_READ_CHUNK)
            if not block:
                break
            digest.update(block)
            size += len(block)
            out.write(block)

    sha256 = digest.hexdigest()
    target = uploads / sha256[:2] / f"{sha256}{suffix}"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        # Same bytes already staged (a re-upload with reprocess=true). Keep
        # the existing file — they're identical by construction.
        tmp.unlink(missing_ok=True)
    else:
        os.replace(tmp, target)
    return sha256, size, target


def _find_duplicate(sha256: str) -> dict[str, str | None] | None:
    """Report an existing copy of these bytes — live document or pending job.

    Both sources matter: documents.json catches "this is already searchable",
    and the job list catches "somebody just queued this book and it's still
    extracting", which is the more common double-click case.
    """
    for doc_id, entry in _documents().items():
        if entry.get("source_sha256") == sha256:
            return {
                "detail": "already in corpus",
                "existing_doc_id": doc_id,
                "added_at": entry.get("ingested_at"),
                "added_by": entry.get("uploaded_by"),
            }

    for job in load_all():
        if job.source_sha256 == sha256 and job.state not in TERMINAL_STATES:
            return {
                "detail": "already in corpus",
                "existing_doc_id": job.doc_id,
                "added_at": job.created_at,
                "added_by": job.user,
            }
    return None


def _documents() -> dict[str, dict]:
    path = documents_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError:
        # An unreadable sidecar must not block uploads — it only costs the
        # dedup check, and the write phase surfaces the corruption loudly.
        return {}
    return data if isinstance(data, dict) else {}
