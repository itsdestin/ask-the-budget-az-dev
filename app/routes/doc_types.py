"""GET /api/document-types — the upload page's rows, from the registry.

WHY this exists: webapp/src/pages/Upload.tsx used to carry its own hand-typed
copy of the type list. Two lists that must agree and nothing enforcing it is a
shape this project has shipped bugs from more than once, so the page now reads
the rows off the wire and holds no copy at all.
"""
from __future__ import annotations

from fastapi import APIRouter

from ingest.doc_types import upload_rows

router = APIRouter()


@router.get("/api/document-types")
def document_types():
    return {
        "types": [
            {
                "key": row.key,
                "label": row.label,
                "group": row.group,
                # DocType.formats is a tuple (Arrow/dataclass-friendly); JSON
                # has no tuple type, so this must be a list or FastAPI's
                # jsonable_encoder would silently turn it into one anyway —
                # doing it here keeps the shape explicit rather than incidental.
                "formats": list(row.formats),
                # Finding 1: projected so the page has a read-only source of
                # truth for publisher that cannot drift from the registry the
                # way a hand-typed webapp-side map did. The upload POST no
                # longer trusts this value even if the client echoes it back
                # -- see app/routes/upload.py::_resolve_publisher.
                "publisher": row.publisher,
                "where_published": row.where_published,
                "which_file": row.which_file,
                "redirect": row.redirect,
                "stage_field": row.stage_field,
                "order": row.order,
            }
            for row in upload_rows()
        ]
    }
