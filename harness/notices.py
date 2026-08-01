"""What went wrong while nobody was looking (Plan 5 Task 5, spec S13).

The admin page's "notices" feed. Everything recorded here has the same
shape: something degraded silently, the app kept working, and an admin
would never find out otherwise. A model was retired and AI Mode quietly
switched to a different one. The API key started coming back rejected. A
scraper's page layout changed. An ingest job failed.

Deliberately NOT an audit log. There is no consumer for "user X asked
question Y at time Z" (that was considered and declined — the ledger
already covers spend, and a log nobody reads is a file that only grows).
This file answers exactly one question: "is anything broken that I
haven't noticed?"

Append-only JSONL at `<data_dir>/notices.json`. The `.json` extension is
the spec's, kept so the filename in the handbook matches what an admin
sees in the folder; the contents are one JSON object per line.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

# The ledger's append is reused rather than reimplemented. It already
# holds the Windows advisory lock over one reserved byte for the duration
# of the write AND takes an in-process threading.Lock in front of it (see
# its docstring for why that ordering is load-bearing on Windows). A
# second, subtly different implementation of that dance in this file is
# exactly how one of them ends up wrong on the share and nobody notices
# until a notices file is interleaved garbage.
from harness.ledger import ARIZONA_TZ, _append_line, _read_rows
from store.config import data_dir

NOTICES_FILE = "notices.json"

# How many rows a read returns. The feed is a "what have I missed" glance,
# not an archive — an admin who wants everything can open the file. Capped
# so a year-old notices file on a slow share can't stall the admin page.
MAX_NOTICES = 200

# The kinds anything in this app may record. A closed set so the admin
# page can group and style them, and so a typo'd kind fails here rather
# than rendering as an unlabelled row.
KIND_MODEL_FALLBACK = "model_fallback"
KIND_KEY_REJECTED = "key_rejected"
KIND_SCRAPER_FAILED = "scraper_failed"
KIND_INGEST_FAILED = "ingest_failed"
KIND_ADMIN_CLAIMED = "admin_claimed"

KINDS = (
    KIND_MODEL_FALLBACK,
    KIND_KEY_REJECTED,
    KIND_SCRAPER_FAILED,
    KIND_INGEST_FAILED,
    KIND_ADMIN_CLAIMED,
)


def notices_path() -> Path:
    return data_dir() / NOTICES_FILE


def record_notice(kind: str, message: str, *, now: datetime | None = None) -> None:
    """Append one notice. NEVER raises.

    WHY this one swallows write failures when `record_usage` deliberately
    does not: a ledger row is money that was already spent and the caller
    needs to know it went unrecorded. A notice is a courtesy message about
    something that ALREADY degraded — and every call site is on a path
    that is currently handling a different failure. Turning "the model was
    retired" into "the model was retired AND the turn crashed writing a
    note about it" would be strictly worse for the analyst waiting on an
    answer.
    """
    if kind not in KINDS:
        # A typo'd kind is a programming error, not a runtime condition —
        # but it still must not take down the path that was reporting a
        # real problem. Recorded under the typo'd name with a loud line.
        print(
            f"harness.notices: unknown notice kind {kind!r} — recording it "
            f"anyway. Add it to KINDS if it is real.",
            file=sys.stderr,
        )
    when = now or datetime.now(ARIZONA_TZ)
    row = {"at": when.isoformat(), "kind": kind, "message": message}
    try:
        _append_line(notices_path(), json.dumps(row, ensure_ascii=False))
    except OSError as err:
        print(
            f"harness.notices: couldn't record a {kind} notice ({err}). "
            f"The notice was: {message}",
            file=sys.stderr,
        )


def read_notices(*, since: str | None = None, limit: int = MAX_NOTICES) -> list[dict]:
    """The most recent notices, newest last, oldest first.

    `since` is an ISO timestamp string and is compared as a STRING, not
    parsed: every row this module writes is an ISO 8601 timestamp in one
    fixed offset (Arizona, no DST — see `harness.ledger.ARIZONA_TZ`), and
    those sort lexicographically in chronological order. Parsing would
    add a failure mode (a hand-edited row with a bad date) to a read path
    whose whole job is to not fail.

    Reuses the ledger's `_read_rows`, so a corrupt line costs its own row
    rather than the file — same reasoning as `month_total`, and the same
    reader, so the two can't drift on Ground truth 8's
    `UnicodeDecodeError`-is-a-`ValueError` trap.
    """
    rows = [
        row for row in _read_rows(notices_path())
        if isinstance(row.get("kind"), str)
    ]
    if since:
        rows = [row for row in rows if str(row.get("at", "")) > since]
    return rows[-limit:]
