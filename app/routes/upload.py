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

from ingest.coverage import COVERAGE_FLOOR
from ingest.doc_types import DocType, all_types, get as get_doc_type
from ingest.driver import make_doc_id
from ingest.jobs import TERMINAL_STATES, load_active, new_job, save
from store.config import data_dir, documents_path
from store.documents import document_record

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

# WHY derived and not written out: this was already a projection of
# EXTRACTOR_REGISTRY; it now projects the registry that feeds it directly. A
# third hand-maintained list is exactly what this change exists to prevent.
# Every key here IS wired through to an extractor -- ingest/dispatcher.py's
# EXTRACTOR_REGISTRY is itself a projection of this same registry, and
# `test_the_registry_and_the_dispatcher_are_in_full_parity` (test_doc_types.py)
# pins the two sets equal. (Finding 5, 2026-08-11: this comment used to say
# agency-submission and budget-bill-summary sat in a dispatcher.py
# `_NOT_YET_WIRED` holdout and would "simply wait at extracting" -- that
# scaffolding was deleted in Task 4 and grep confirms zero remaining
# references; both types route to MinerU like any other PDF type.)
ACCEPTED_DOC_TYPES = frozenset(t.key for t in all_types())

# The bill-summary ladder has exactly two rungs (spec T2). JLBC titles some
# engrossed versions "Final Budget Bills"; that wording maps to `engrossed`,
# it is not a third stage. Accepting one would break "Engrossed supersedes
# Introduced" by introducing a value the rule says nothing about.
ACCEPTED_STAGES = frozenset({"introduced", "engrossed"})
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
    # WHY optional (was Form(...) -- required): Finding 1. The registry is
    # now authoritative for any doc_type that declares a `publisher`, so the
    # webapp is dropping its hand-maintained doc_type -> publisher map and
    # will stop sending this field. See `_resolve_publisher` below.
    publisher: str = Form(""),
    doc_type: str = Form(...),
    fiscal_year: str = Form(...),
    title: str = Form(""),
    is_public_record: str = Form(""),
    reprocess: str = Form(""),
    stage: str = Form(""),
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

    row = get_doc_type(doc_type)
    # Finding 1: the registry decides `publisher`, never the client, for any
    # row that declares one -- see `_resolve_publisher`'s docstring for the
    # silent-corruption shape this replaces.
    publisher = _resolve_publisher(row, publisher)
    stage_value = stage.strip().lower()
    if stage_value and stage_value not in ACCEPTED_STAGES:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown stage {stage!r}. Choose Introduced or Engrossed.",
        )
    if row is not None and row.stage_field and not stage_value:
        raise HTTPException(
            status_code=422,
            detail="Say whether this is the Introduced or the Engrossed version.",
        )
    # Review finding: a stage supplied for a type that declares no
    # `stage_field` used to be accepted silently and ridden straight into
    # `build_title`, which appends "(Introduced)"/"(Engrossed)"
    # unconditionally. That suffix is the ONLY signal the system prompt's
    # "Engrossed supersedes Introduced" rule can read (doc_title rides on
    # every retrieved chunk) — a false suffix on, say, a final AFR would
    # teach the model the document is provisional and safe to supersede.
    # The two existing guards above bracket "unknown stage" and "missing
    # stage on a staged type"; this is the gap between them.
    if row is not None and not row.stage_field and stage_value:
        raise HTTPException(
            status_code=422,
            detail=f"{row.label} documents do not have a stage — leave that field blank.",
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
        publisher=publisher, doc_type=doc_type, fiscal_year=year, filename=filename,
        stage=stage_value or None,
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
        stage=stage_value or None,
    )
    save(job)

    # Belt and braces. The server starts the worker at startup now (see
    # app/main.py's lifespan), so this is no longer what gets the queue
    # moving — but `start()` is idempotent, and a worker that died is worth
    # reviving at the moment somebody is actually waiting on a document.
    worker = getattr(request.app.state, "ingest_worker", None)
    if worker is not None:
        worker.start()

    return {"job_id": job.job_id, "doc_id": doc_id}


# --- helpers ----------------------------------------------------------------


def _resolve_publisher(row: DocType | None, submitted: str) -> str:
    """Decide the `publisher` a document is stamped with.

    WHY the registry wins whenever the row declares one: `publisher` used to
    be pure client input, and `GET /api/document-types` never projected the
    registry's own `publisher` field -- so the webapp hand-maintained a
    SECOND doc_type -> publisher map and posted whatever it guessed. A row
    the webapp's map didn't know about (or drifted on) posted the wrong
    value with nothing erroring: `make_doc_id`'s JLBC branch is keyed on the
    literal string "jlbc", so a wrong publisher silently mints the wrong
    doc_id CLASS, and every chunk of that document carries the wrong
    publisher facet for search filtering. Deriving it here makes the
    registry the only place that fact can live (spec T4's acceptance test:
    adding a row must be a YAML edit, not a code change).

    A row that declares no `publisher` (none exist in the committed registry
    today, but the field is optional on `DocType`) falls back to whatever the
    client sent -- validated against the registry's own set of known
    publisher values rather than accepted as-is, so a typo still 422s
    instead of silently seeding a new value nothing else recognizes.
    """
    if row is not None and row.publisher:
        return row.publisher
    value = submitted.strip()
    known = {t.publisher for t in all_types() if t.publisher}
    if value not in known:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown publisher {value!r}. Choose one of: "
                   f"{', '.join(sorted(known))}.",
        )
    return value


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
            health, message = _duplicate_health(doc_id)
            return {
                "detail": "already in corpus",
                "existing_doc_id": doc_id,
                "added_at": entry.get("ingested_at"),
                "added_by": entry.get("uploaded_by"),
                "health": health,
                "message": message,
            }

    # load_active(): every archived job is terminal, so the filter below
    # already excluded all of them -- the same set, without reading the
    # archive. An already-INGESTED file is caught by the documents.json
    # loop above, not by this one; the two together are what make a
    # re-upload of a finished document still report as a duplicate.
    for job in load_active():
        if job.source_sha256 == sha256 and job.state not in TERMINAL_STATES:
            health, message = _duplicate_health(job.doc_id)
            return {
                "detail": "already in corpus",
                "existing_doc_id": job.doc_id,
                "added_at": job.created_at,
                "added_by": job.user,
                "health": health,
                "message": message,
            }
    return None


# T12: what today's fixed sentence stays for a document this check has no
# evidence about — every document ingested before this shipped (7,434 of
# them at the time), and unchanged from before this task.
_NO_HEALTH_MESSAGE = "This document is already in the corpus."


def _duplicate_health(doc_id: str) -> tuple[dict[str, float | bool] | None, str]:
    """Whether the existing copy's extraction looked complete, and the
    sentence that says so.

    WHY `coverage is None` -- covering both "no extraction key at all" and
    "extraction ran but coverage is null" -- gets the SAME silent treatment
    as the legacy-document case: `ingest/coverage.py::coverage_ratio`
    returns None (not 0.0) when the source has no text layer to measure
    against, e.g. an image-only PDF routed straight to OCR. That is a
    genuinely unmeasured state, not a measured failure, and the global
    constraint this task shipped against is explicit that a health claim
    with no evidence behind it is exactly the thing to avoid -- "unknown"
    would be noise on the 7,434 legacy documents that are the overwhelming
    majority of what this branch will see, and "healthy" would be a lie
    about a document nothing was ever computed for.
    """
    record = document_record(doc_id)
    extraction = record.get("extraction") if isinstance(record, dict) else None
    coverage = extraction.get("coverage") if isinstance(extraction, dict) else None
    if coverage is None:
        return None, _NO_HEALTH_MESSAGE

    # The floor REJECTS; it never approves (global constraint) — equality
    # with COVERAGE_FLOOR must land on the healthy side, matching the T5
    # ladder's own "at or above the floor" rule in `ingest/coverage.py`.
    recommend_reprocess = coverage < COVERAGE_FLOOR
    verdict = "recommended" if recommend_reprocess else "not needed"
    message = (
        f"Extraction produced {round(coverage * 100)}% as much text as the "
        f"file contains. Re-processing is {verdict}."
    )
    return {"coverage": coverage, "recommend_reprocess": recommend_reprocess}, message


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
