"""Analyst issue reports on the shared data dir (spec E3).

One JSON file per report under <data_dir>/issue-reports/ — the jobs/
shape. No index file exists to corrupt; the directory listing IS the
index, and a torn report costs exactly its own row.

Filenames sort chronologically (UTC timestamp prefix + uuid suffix), so
"newest first" is a reverse filename sort with no parsing.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from store.config import data_dir

REPORTS_DIR = "issue-reports"
VALID_STATUS = ("unresolved", "resolved")


def reports_dir() -> Path:
    return data_dir() / REPORTS_DIR


def _write(path: Path, report: dict) -> None:
    tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def create_report(
    *,
    submitted_by: str,
    description: str,
    expected: str = "",
    transcript: dict | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    report_id = f"{now.strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
    report = {
        "id": report_id,
        # Stamped so "written before versioning" stays distinguishable from
        # "written today" — the chat-history lesson; it cannot be added later.
        "version": 1,
        "submitted_by": submitted_by,
        "submitted_at": now.isoformat(),
        "description": description,
        "expected": expected,
        "status": "unresolved",
        "admin_note": None,
        "resolved_by": None,
        "resolved_at": None,
        "transcript": transcript,
    }
    reports_dir().mkdir(parents=True, exist_ok=True)
    _write(reports_dir() / f"{report_id}.json", report)
    return report


def _read(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, ValueError):
        return None


def list_reports() -> list[dict]:
    """Every report, newest first. A corrupt file is a VISIBLE unreadable
    row — an admin must see that a report exists even when it cannot be
    read, or "the list looks fine" hides a torn submission forever."""
    directory = reports_dir()
    try:
        paths = sorted(directory.glob("*.json"), reverse=True)
    except OSError:
        return []
    out: list[dict] = []
    for path in paths:
        report = _read(path)
        if report is None:
            print(f"app.issue_reports: unreadable report {path}", file=sys.stderr)
            out.append({"id": path.stem, "unreadable": True})
        else:
            out.append(report)
    return out


def load_report(report_id: str) -> dict | None:
    # The id is embedded in a filename; refuse anything path-shaped.
    if not report_id or "/" in report_id or "\\" in report_id or ".." in report_id:
        return None
    return _read(reports_dir() / f"{report_id}.json")


def update_report(
    report_id: str, *, status: str | None = None, admin_note: str | None = None,
    actor: str = "",
) -> dict | None:
    report = load_report(report_id)
    if report is None:
        return None
    if status is not None:
        if status not in VALID_STATUS:
            raise ValueError(f"Unknown status {status!r}.")
        report["status"] = status
        if status == "resolved":
            report["resolved_by"] = actor
            report["resolved_at"] = datetime.now(timezone.utc).isoformat()
        else:
            report["resolved_by"] = None
            report["resolved_at"] = None
    if admin_note is not None:
        report["admin_note"] = admin_note or None
    _write(reports_dir() / f"{report_id}.json", report)
    return report
