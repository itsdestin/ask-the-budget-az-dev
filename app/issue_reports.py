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


class ReportsUnavailable(Exception):
    """The reports folder itself could not be read.

    Distinct from "there are no reports", which is an empty list. The two
    look identical to a caller that gets `[]` for both, and the screens then
    tell the reader "no reports yet" — a fact nobody actually knows. Callers
    catch this and say the folder couldn't be read instead. Same posture as
    store/office_aliases.py's reader: a missing file is silent, anything
    else gets a stderr line.
    """


def reports_dir() -> Path:
    return data_dir() / REPORTS_DIR


def _write(path: Path, report: dict) -> None:
    # This dir lives on a shared network folder several machines read/write at
    # once. Write to a temp file (whose ".tmp-<uuid>" name doesn't match the
    # "*.json" glob) then atomically replace, so list_reports() can never see
    # a half-written file.
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
        # ValueError covers both JSONDecodeError (torn write) and
        # UnicodeDecodeError; degrade to None instead of raising so one bad
        # report can't take down list_reports() for every other report.
        return None


def list_reports() -> list[dict]:
    """Every report, newest first. A corrupt file is a VISIBLE unreadable
    row — an admin must see that a report exists even when it cannot be
    read, or "the list looks fine" hides a torn submission forever.

    Raises ReportsUnavailable when the folder itself can't be read (the
    share is offline, permissions changed). An empty list from here means
    "nothing has been filed", and nothing else.
    """
    directory = reports_dir()
    try:
        # os.listdir, NOT Path.glob: pathlib's glob SWALLOWS OSError and
        # yields nothing, so a permission-denied share was indistinguishable
        # from an empty folder (verified on this interpreter — glob on a
        # chmod-000 directory returns [] rather than raising). listdir is the
        # call that actually reports the failure.
        names = os.listdir(directory)
    except FileNotFoundError:
        # Fix (IMPORTANT 2, review): FileNotFoundError alone doesn't tell
        # "nobody has filed a report yet" apart from "the share vanished" —
        # store/config.py's `data_dir()` deliberately swallows a failed
        # mkdir on an unreachable share and returns the path anyway, so
        # os.listdir on THIS directory raises the exact same exception in
        # both cases. Same discrimination app/health.py's `_check_share`
        # makes: the ROOT data dir missing means unreachable; the root
        # present with just `issue-reports/` absent means genuinely empty.
        # `directory.parent` IS that root — reports_dir() is always
        # `data_dir() / REPORTS_DIR` — so checking it here stays in step
        # with whatever `reports_dir()` actually points at (tests
        # monkeypatch it directly) instead of re-resolving the root through
        # a second, independent path.
        if not directory.parent.is_dir():
            print(
                f"app.issue_reports: cannot read {directory} — its parent "
                "folder is missing, which means the shared data folder "
                "itself is unreachable (not just empty of reports).",
                file=sys.stderr,
            )
            raise ReportsUnavailable(f"shared data folder is unreachable: {directory.parent}")
        # The root is there; issue-reports/ itself just hasn't been created
        # yet — nobody has filed a report.
        return []
    except OSError as err:
        print(
            f"app.issue_reports: cannot read {directory} ({err}) — the "
            "reports on the shared folder are unavailable for this read.",
            file=sys.stderr,
        )
        raise ReportsUnavailable(str(err)) from err
    # Same selection the "*.json" glob made: the ".tmp-<uuid>" name a
    # half-written report carries does not end in .json, so it never shows up.
    paths = sorted(
        (directory / name for name in names if name.endswith(".json")), reverse=True
    )
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
            # Reopening must not leave stale resolver/timestamp behind —
            # those stamps would otherwise lie about who last resolved it.
            report["resolved_by"] = None
            report["resolved_at"] = None
    if admin_note is not None:
        report["admin_note"] = admin_note or None
    _write(reports_dir() / f"{report_id}.json", report)
    return report
