"""Issue report routes (spec E3).

POST is every analyst's door and is deliberately ungated. GET filters
server-side: the admin reads everything; anyone else reads their own.
The gate is the same soft S11 username check as the rest of the admin
surface — NOT authentication, and nothing here is harmful if bypassed
(a determined user could already read the share directly).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import current_user, is_admin
from app.issue_reports import create_report, list_reports, update_report
from app.routes.admin import require_admin
from harness.settings import Settings, load_settings

router = APIRouter()


def _load_transcript(conversation_id: str):
    """Seam for tests; the real path reads the caller's per-device history."""
    from harness import history

    return history.load(conversation_id)


class IssueBody(BaseModel):
    description: str
    expected: str = ""
    conversation_id: str | None = None


class IssuePatch(BaseModel):
    status: str | None = None
    admin_note: str | None = None


MSG_EMPTY_DESCRIPTION = "Describe what went wrong — an empty report can't be acted on."
MSG_UNKNOWN_CONVERSATION = (
    "That conversation isn't stored on this computer, so it can't be "
    "attached. Submit without it, or reopen the chat and try again."
)
MSG_UNKNOWN_REPORT = "No such report — it may have been deleted from the share."


@router.post("/api/issues")
def submit_issue(body: IssueBody) -> dict:
    description = body.description.strip()
    if not description:
        raise HTTPException(400, MSG_EMPTY_DESCRIPTION)
    transcript = None
    if body.conversation_id:
        loaded = _load_transcript(body.conversation_id)
        if loaded is None:
            raise HTTPException(400, MSG_UNKNOWN_CONVERSATION)
        # The analyst's explicit act of attaching their local transcript to
        # the report — asdict() exercises the real Transcript shape.
        transcript = asdict(loaded)
    report = create_report(
        submitted_by=current_user() or "",
        description=description,
        expected=body.expected.strip(),
        transcript=transcript,
    )
    return {"report": _redact(report, admin=False)}


def _redact(report: dict, *, admin: bool) -> dict:
    """Non-admins get a flag, not the transcript body — their own transcript
    is already on their machine, and re-serving it is pure payload."""
    if admin or report.get("unreadable"):
        return report
    out = {k: v for k, v in report.items() if k != "transcript"}
    out["transcript_attached"] = report.get("transcript") is not None
    return out


@router.get("/api/issues")
def get_issues() -> dict:
    user = current_user()
    admin = is_admin(load_settings(), user)
    reports = list_reports()
    if not admin:
        reports = [r for r in reports if r.get("submitted_by") == user]
    visible = [_redact(r, admin=admin) for r in reports]
    unresolved = sum(1 for r in visible if r.get("status") == "unresolved")
    return {"reports": visible, "unresolved": unresolved, "is_admin": admin}


@router.patch("/api/issues/{report_id}")
def patch_issue(
    report_id: str, body: IssuePatch, _: Settings = Depends(require_admin)
) -> dict:
    try:
        report = update_report(
            report_id,
            status=body.status,
            admin_note=body.admin_note,
            actor=current_user() or "",
        )
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    if report is None:
        raise HTTPException(404, MSG_UNKNOWN_REPORT)
    return {"report": report}
