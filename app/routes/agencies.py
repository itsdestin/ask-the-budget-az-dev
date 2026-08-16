"""The agency picker's list, and the admin's ability to extend it.

WHY THIS EXISTS. Every document type on the upload page is named completely
by its type and its year — "FY 2025 Annual Financial Report" is the AFR,
there is one a year. Agency budget requests are the exception: there are
~78 in a year and nothing else in their titles varies, so without an agency
they would every one of them read "FY 2027 Budget Request". A free-text
Title box was the old answer, and it put the burden on whoever uploaded to
spell the agency the same way as the last person did.

GET /api/agencies is UNGATED, unlike everything else in this module. It
feeds a picker on the upload page, which any analyst can reach; the list is
the contents of a committed catalog file plus names an admin typed, and
none of it is sensitive. Gating it would break the upload page for exactly
the people it is for.

The two write routes ARE gated (`require_admin`, the same soft gate as the
rest of the admin surfaces — see app/identity.py, which is explicit that it
is NOT authentication).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import current_user
from app.routes.admin import require_admin
from chunking.entity_stamper import _normalize_for_match
from store.office_agencies import (
    OFFICE_ID_PREFIX,
    Agency,
    OfficeAgency,
    all_agencies,
    load_office_agencies,
    save_office_agencies,
)

router = APIRouter()

# Long enough for "Water Infrastructure Finance Authority of Arizona" (49)
# with room to spare, short enough that a pasted paragraph is refused rather
# than becoming a document title.
MAX_AGENCY_NAME = 90


def _row(agency: Agency) -> dict:
    return {
        "canonical_id": agency.canonical_id,
        "name": agency.name,
        "source": agency.source,
    }


@router.get("/api/agencies")
def list_agencies():
    return {"agencies": [_row(a) for a in all_agencies()]}


class AgencyAdd(BaseModel):
    name: str


def _slug(name: str) -> str:
    """A stable id from a name. Lowercase, alphanumerics, single hyphens.

    Derived from the name rather than a uuid so the id is legible in a job
    file and in `office-agencies.json` — an admin reading either should be
    able to tell what `agency:office-water-infrastructure-finance` is
    without a lookup table.
    """
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return f"{OFFICE_ID_PREFIX}{slug}"


@router.post("/api/admin/agencies")
def add_agency(body: AgencyAdd, _: str = Depends(require_admin)):
    name = " ".join(body.name.split())
    if not name:
        raise HTTPException(status_code=422, detail="Type the agency's name.")
    if len(name) > MAX_AGENCY_NAME:
        raise HTTPException(
            status_code=422,
            detail=f"That name is {len(name)} characters; the limit is "
                   f"{MAX_AGENCY_NAME}. Use the agency's name, not its "
                   "description.",
        )

    # Duplicate check runs against BOTH sources, through the same normalizer
    # the corpus-side stamper and the query-side resolver use. Two entries
    # differing only by punctuation or case would give the picker two rows
    # that look identical, and the person uploading no way to tell which one
    # the last person used — which is the whole failure the picker replaces.
    normalized = _normalize_for_match(name)
    for existing in all_agencies():
        if _normalize_for_match(existing.name) == normalized:
            raise HTTPException(
                status_code=409,
                detail=f"{existing.name} is already in the list"
                       + (" (it ships with the app)." if existing.source == "catalog"
                          else "."),
            )

    added = load_office_agencies()
    entry = OfficeAgency(
        canonical_id=_slug(name),
        name=name,
        added_by=current_user(),
        added_at=datetime.now(timezone.utc).isoformat(),
    )
    # A name that normalizes differently but slugs the same (two names whose
    # only difference is punctuation the slug drops) would silently replace
    # the earlier entry, because the id is the key everywhere downstream.
    if any(a.canonical_id == entry.canonical_id for a in added):
        raise HTTPException(
            status_code=409,
            detail="An agency with that name is already in the list.",
        )
    save_office_agencies(added + (entry,))
    return {"agency": _row(Agency(entry.canonical_id, entry.name, "office"))}


@router.delete("/api/admin/agencies/{canonical_id}")
def remove_agency(canonical_id: str, _: str = Depends(require_admin)):
    # Only office entries can be removed. The 157 catalogued agencies are a
    # committed file the bundle ships read-only, and an admin who could
    # delete one would break the agency filter for a corpus already stamped
    # with it.
    if not canonical_id.startswith(OFFICE_ID_PREFIX):
        raise HTTPException(
            status_code=422,
            detail="That agency ships with the app and cannot be removed.",
        )
    added = load_office_agencies()
    remaining = tuple(a for a in added if a.canonical_id != canonical_id)
    if len(remaining) == len(added):
        raise HTTPException(status_code=404, detail="That agency is not in the list.")
    save_office_agencies(remaining)
    # Documents already uploaded under this agency KEEP their titles: the
    # name was copied into the title at ingest, not looked up at read time.
    # Removing an entry stops it being offered again; it does not rewrite
    # history, which is the behaviour an admin correcting a typo wants.
    return {"removed": canonical_id}
