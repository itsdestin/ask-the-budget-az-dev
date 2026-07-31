"""Admin identity + the /api/admin/* surface (Plan 5, Track 1).

Created by Task 1 with `GET /api/me` and filled out by Tasks 3–7 with
settings, catalog, usage, corpus and backup endpoints.

Every route under /api/admin/ is gated by `is_admin` — a SOFT gate
(spec S11). Read `app/identity.is_admin` before adding anything here:
nothing may sit behind this gate that would be harmful if bypassed.
`GET /api/me` itself is deliberately ungated — it is how the webapp
learns whether to render the Admin pill at all, so every user must be
able to call it.
"""
from __future__ import annotations

from fastapi import APIRouter

from app.identity import admin_claimable, current_user, is_admin
from harness.settings import load_settings

router = APIRouter()


@router.get("/api/me")
def me() -> dict:
    """Who the caller is and what the app will let them see.

    The webapp reads this on load to decide whether the Admin nav pill
    renders and whether to show the "no admin is set up yet" banner.
    `admin_username` is returned to EVERY user, not just the admin,
    because a blocked analyst's next question is "who do I ask?" and the
    ledger's own message ("ask Destin to raise it") needs that name to
    have come from somewhere.
    """
    settings = load_settings()
    user = current_user()
    return {
        "user": user,
        "is_admin": is_admin(settings, user),
        "admin_username": settings.admin_username,
        "admin_claimable": admin_claimable(settings),
        # Task 13 (the RESET-ADMIN.txt break-glass path) is what makes this
        # ever true; until it lands there is no reset file to detect.
        "admin_reset_pending": False,
    }
