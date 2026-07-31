"""S19 usage ledger + per-user monthly spend limits (Plan 4 Task 5).

Every OpenRouter call costs real money against a single shared API key
(spec S11/S19). This module is the only place that writes "what did a
call cost" and the only place that answers "can this user place another
one right now" — `harness/session.py` (Task 6) calls `record_usage`
after every provider response and `check_limit` before every provider
call, and Plan 5's admin page reads the same ledger rows for
per-user/per-model/per-tier breakdowns. Nothing here talks to a model
provider; it only appends/reads plain JSON lines on the shared data dir.

Three deliberate design decisions, expanded where they're implemented
below because a one-line summary here would just invite drift with the
real comment:

  - ATOMICITY: `_append_line` states the actual guarantee (an
    OS-level advisory mutex around each append), not a stronger one this
    module can't back up on an SMB share.
  - CORRUPT LINES: `_read_rows` skips a bad line rather than raising,
    because a read failure here would disable AI Mode for the whole
    office (see that function's docstring).
  - TIMEZONE: `ARIZONA_TZ` is a fixed UTC-7 offset, not the host
    machine's local zone or a `zoneinfo` name (see its docstring).
"""
from __future__ import annotations

import json
import os
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator

from harness.constants import WARN_THRESHOLD_RATIO
from harness.settings import Settings
from store.config import data_dir

def _load_msvcrt():
    """Import `msvcrt`, or explain on stderr why cross-process append
    locking is disabled.

    Windows is this app's only supported deployment target, so a
    successful import is the overwhelmingly common case; a failure means
    dev/CI on a non-Windows box, where `_append_line`'s in-process
    `threading.Lock` still protects same-process writers even without
    it. Printing rather than degrading silently matches this codebase's
    existing convention for a quiet fallback (`harness/tools.py`'s
    `(OSError, ValueError)` doc-metadata guard does the same) — a
    developer who hits a lock-related race on a Mac should immediately
    see WHY cross-process locking is off, not have to rediscover this
    module's platform assumption from scratch.

    A plain function (not a bare module-level try/except) purely so a
    test can call it directly against a forced `ImportError` — see
    `tests/test_ledger.py`'s `test_msvcrt_unavailable_logs_to_stderr_...`,
    which uses `sys.modules["msvcrt"] = None` (the documented way to make
    `import msvcrt` raise) rather than needing an actual non-Windows box.
    """
    try:
        import msvcrt as _msvcrt
    except ImportError:
        print(
            "harness.ledger: msvcrt unavailable (not running on Windows) — "
            "cross-process ledger-append locking is disabled; same-process "
            "writes are still serialized via _write_lock. This module's "
            "only supported deployment target is Windows, so this should "
            "only ever print in dev/CI.",
            file=sys.stderr,
        )
        return None
    return _msvcrt


msvcrt = _load_msvcrt()


USAGE_DIR = "usage"

# Serializes appends WITHIN this process; see `_append_line`'s docstring
# for why this has to sit in front of the cross-process `msvcrt` lock
# rather than being redundant with it.
_write_lock = threading.Lock()

# Arizona (outside the Navajo Nation, which is where this office sits)
# does NOT observe DST, so a fixed UTC-7 offset IS "Arizona local time"
# every day of the year — unlike `datetime.now().astimezone()` with no
# argument, which trusts whatever timezone the HOST machine's clock
# happens to be set to (a server could be provisioned in UTC, or this
# could run on a laptop that travelled), and unlike
# `zoneinfo.ZoneInfo("America/Phoenix")`, which needs the tzdata package
# present and current. A fixed offset is deterministic regardless of
# where or how the process is launched.
#
# WHY this matters here specifically: it decides two things a user can
# actually feel — which month's SHARD FILE a call near midnight lands
# in, and the exact moment a blocked user's counter rolls over. A single
# Arizona office (this app's whole deployment shape, per spec) should
# roll over on ITS midnight, not on whichever midnight the hosting
# machine's clock happens to be set to.
ARIZONA_TZ = timezone(timedelta(hours=-7), name="MST")


def _as_arizona(when: datetime | None) -> datetime:
    """Normalize `when` (or "now") to an Arizona-local, tz-aware datetime.

    Every public function below takes `now` as an explicit, optional
    parameter rather than calling `datetime.now()` inline, specifically
    so tests can pin the clock instead of racing real time (e.g. a test
    asserting month-shard boundaries would be flaky or midnight-fragile
    otherwise).

    A caller-supplied NAIVE datetime is treated as ALREADY Arizona-local
    rather than assumed-UTC-then-converted — that is the simplest
    contract for a test to reason about ("just write
    `datetime(2026, 1, 15, 12, 0)`, that's Jan 15th noon here") and
    matches how a human types a literal date. A tz-AWARE datetime is
    honestly converted via `astimezone()`, which is how production code
    (Task 6) is expected to pass a real UTC timestamp through.
    """
    if when is None:
        return datetime.now(ARIZONA_TZ)
    if when.tzinfo is None:
        return when.replace(tzinfo=ARIZONA_TZ)
    return when.astimezone(ARIZONA_TZ)


def _month_shard(when: datetime) -> str:
    return f"{when.year:04d}-{when.month:02d}"


def _usage_path(shard: str) -> Path:
    return data_dir() / USAGE_DIR / f"usage-{shard}.jsonl"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def _append_line(path: Path, line: str) -> None:
    """Append one line to `path`, serialized against concurrent writers.

    ATOMICITY GUARANTEE — read this before assuming a stronger one: this
    is a Windows office app writing to a network share that a SECOND
    machine could also be writing to (per the deployment shape in the
    task brief — not hypothetical). A single `write()` of one short JSON
    line is atomic on a genuinely POSIX or local-NTFS filesystem (writes
    below the OS pipe-buffer size don't interleave with each other), but
    SMB does not contractually promise that one client-side `write()`
    call reaches the server as a single indivisible operation — that
    depends on the SMB dialect and server implementation, which this
    module has no way to inspect or verify for whatever share it ends up
    on. So: **this is "best-effort mutual exclusion via an OS advisory
    lock," not a provable cross-network atomicity guarantee.**

    The cross-process mechanism: every append takes an OS-level advisory
    lock on ONE reserved byte (offset 0) of the target file for the
    duration of the write — `msvcrt.locking`, since Windows is the only
    supported deployment target and this must not add a dependency.
    Locking a fixed byte (rather than the byte range about to be
    written, which isn't known until the file's current length is read)
    is the standard poor-man's-mutex trick: contention on that one byte
    serializes every writer that goes through this function, across
    processes, as long as they're all Windows clients honoring advisory
    locks — which every writer of this ledger is, by construction, since
    only this module ever calls it. A client that ignored advisory
    locks, or a non-Windows machine writing the same share, could still
    race; that's an accepted risk given the actual deployment, not a
    silent one.

    There is ALSO an in-process `threading.Lock` (`_write_lock`, module
    scope) wrapping the whole thing, and it is load-bearing, not just
    belt-and-braces: this is "one Python process serving a whole
    office," so two analysts finishing a turn in the same instant means
    two THREADS of the same process racing to append, and Windows'
    `msvcrt.locking()` has a documented failure mode exactly there — its
    underlying CRT deadlock heuristic assumes a process is only ever
    waiting on ONE lock at a time, so when a second thread of the SAME
    process contends for a byte the first thread already holds, it does
    not queue and wait like it does across processes; it immediately
    raises `OSError: [Errno 36] Resource deadlock avoided`. Taking the
    Python lock first means at most one thread of this process is ever
    inside the `msvcrt.locking()` call, so that call only ever contends
    with a genuinely SEPARATE process — the case it actually handles
    correctly.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    data = line.encode("utf-8") + b"\n"
    with _write_lock, open(path, "ab") as f:
        if msvcrt is not None:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            # Explicit seek-to-end rather than relying solely on 'ab'
            # semantics: we just seek(0)'d above to take the lock, so we
            # must reposition before writing regardless of platform.
            f.seek(0, os.SEEK_END)
            f.write(data)
            f.flush()
        finally:
            if msvcrt is not None:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)


def record_usage(
    user: str,
    tier: str,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float | None = None,
    *,
    cached_tokens: int = 0,
    now: datetime | None = None,
) -> None:
    """Append one usage row to this month's ledger shard.

    Row shape (pinned by the spec — Plan 5's admin page reads these
    fields verbatim, so changing names here is a cross-plan breaking
    change): `user`, `timestamp` (ISO 8601, Arizona-local, offset
    included), `tier`, `model`, `tokens_in`, `tokens_out`, `cost_usd`,
    `cached_tokens`.

    `cached_tokens` (S22) is how many of `tokens_in` the provider served
    from its prompt cache. It is recorded for VISIBILITY, not for
    arithmetic: `cost_usd` is OpenRouter's own exact figure and already
    reflects the discount, so nothing downstream should recompute a
    price from these. It exists because prompt caching is otherwise
    unobservable — a broken cache prefix produces identical answers,
    identical tokens and identical logs, and shows up only as a bill
    roughly 10x larger. A row written before S22 simply has no
    `cached_tokens` key, which readers must treat as 0/unknown rather
    than as a corrupt row.

    `cost_usd` is `None` on a custom endpoint (S15), where OpenRouter's
    exact-cost usage accounting isn't available. The row is still
    written — tokens are always known — so an admin sees SOMETHING for
    that call instead of a gap in the ledger, matching the spec's
    "tokens; exact dollar costs unavailable on custom endpoints" UI
    wording rather than silently dropping the row.

    Month-sharded (one file per `<data_dir>/usage/usage-<YYYY-MM>.jsonl`)
    so files stay small and `month_total` never has to scan more than
    one calendar month's worth of rows.

    FAILURE CONTRACT — this function does NOT catch or swallow write
    failures; a `mkdir`/`open`/lock/`write` error propagates straight to
    the caller. This is deliberate, not an oversight: by the time
    `harness/session.py` (Task 6) calls this, the provider call already
    happened and the money is already spent — a write failure here means
    the row didn't get recorded, not that the call didn't happen. That
    is a fact the caller needs to know about (to at minimum log it
    somewhere else, since the ledger itself just failed), so this
    function raises rather than pretending success. Write failures are
    also rarer and more actionable than read failures (see `_read_rows`
    for why THAT path fails open instead) — an admin can fix "the share
    is full" or "permissions changed," but a whole office being locked
    out of AI Mode because one read hiccupped is a worse failure to
    invite.
    """
    when = _as_arizona(now)
    row = {
        "user": user,
        "timestamp": when.isoformat(),
        "tier": tier,
        "model": model,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "cached_tokens": cached_tokens,
    }
    _append_line(_usage_path(_month_shard(when)), json.dumps(row, ensure_ascii=False))


# ---------------------------------------------------------------------------
# Reading
# ---------------------------------------------------------------------------


def _int_or_zero(value: object) -> int:
    """Tolerant coercion for a ledger field that SHOULD be an int.

    Only reached via a hand-edited or externally-corrupted row (every
    row this module itself writes has real ints here) — `month_total`'s
    contract is "never crash on bad data," so a malformed token count is
    worth zero rather than a traceback.
    """
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return 0


def _read_rows(path: Path) -> Iterator[dict]:
    """Yield parsed dict rows from one ledger shard, one bad line at a
    time skipped rather than aborting the whole read.

    WHY skip-and-warn per LINE, not fail-loud: `month_total` feeds
    `check_limit`, which gates whether AI Mode is usable AT ALL for a
    user's next turn. A single truncated or mis-encoded line — the exact
    failure mode `_append_line` above tries to minimize but, being
    honest about SMB, cannot fully rule out — must never turn into
    "nobody in the office can use AI Mode until someone hand-edits a
    JSONL file." A bad row is dropped from every total it would have
    contributed to (undercounting spend by at most that one row) and
    named on stderr so it's discoverable.

    Read as BYTES, decoded per-line, not `path.read_text(encoding=
    "utf-8")` for the whole file: a `UnicodeDecodeError` (which a torn
    multi-byte write can genuinely produce, and which `record_usage`'s
    `ensure_ascii=False` makes reachable via any non-ASCII username or
    model id) is a `ValueError` subclass. Decoding the whole file in one
    call meant ONE mis-encoded byte anywhere raised past the per-line
    `try/except` below entirely, crashing `month_total` — and therefore
    `check_limit`, the exact "can this user place another call" gate
    this module exists to keep alive — for every row in the file,
    including rows for OTHER users. Decoding line-by-line inside the
    same guard as the JSON parse means a mis-encoded line is skipped
    exactly like a malformed-JSON line, and every well-formed sibling
    row still counts.

    WHY the whole-file OPEN itself fails open (missing OR unreadable),
    but only ONE of those two cases is silent: `FileNotFoundError` means
    "no usage recorded yet" — the overwhelmingly common case (new month,
    new hire) — and prints nothing. Any OTHER `OSError` (permission
    denied, the share unreachable) also returns zero rows rather than
    raising, matching S19's "search is never affected" spirit — an
    infrastructure blip should not lock every analyst out of usage
    they're actually still under-limit for — but IS logged, because
    unlike a missing file, a degraded share is a genuine blind spot: it
    can make an over-limit user read as "allowed" until the share
    recovers, and an admin needs a signal that happened, not silence.
    """
    try:
        raw_bytes = path.read_bytes()
    except FileNotFoundError:
        return  # no usage recorded this month yet — not an error
    except OSError as err:
        print(
            f"harness.ledger: {path} is unreadable ({err}) — treating this "
            "month as zero usage for every user (fail-open, per S19's "
            "'search is never affected' spirit). If this persists, an "
            "over-limit user could be let through until the share "
            "recovers — investigate it, don't just note this line.",
            file=sys.stderr,
        )
        return

    for line_number, raw_line in enumerate(raw_bytes.split(b"\n"), start=1):
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        try:
            line = raw_line.decode("utf-8")
        except UnicodeDecodeError as err:
            print(
                f"harness.ledger: {path} line {line_number} is not valid "
                f"UTF-8 ({err}) — skipping it. This month's totals may "
                "undercount by that one row.",
                file=sys.stderr,
            )
            continue
        try:
            row = json.loads(line)
        except ValueError as err:
            print(
                f"harness.ledger: {path} line {line_number} is corrupt "
                f"({err}) — skipping it. This month's totals may "
                "undercount by that one row.",
                file=sys.stderr,
            )
            continue
        if isinstance(row, dict):
            yield row
        else:
            print(
                f"harness.ledger: {path} line {line_number} is not a JSON "
                "object — skipping it.",
                file=sys.stderr,
            )


@dataclass(frozen=True)
class MonthUsage:
    """One user's ledger summary for a single calendar month.

    `cost_usd` sums only rows where the recorded cost is a real number —
    a `None`-cost row (a custom-endpoint call, S15, or a corrupt row
    dropped entirely by `_read_rows`) is EXCLUDED from the dollar total
    rather than treated as `$0`, because "unknown" and "free" are
    different facts and conflating them would understate spend with no
    visible sign it happened. `rows_with_unknown_cost` IS that visible
    sign — Plan 5's admin page can render "at least $X (N calls of
    unknown cost not included)" instead of a number that quietly lies by
    omission. Token totals are kept separately and are NEVER `None` —
    OpenRouter always reports tokens even when it can't report cost.
    """

    # Rounded to whole cents (see month_total) — never a raw float-summation
    # residue like 0.7999999999999999. One rounded representation is used
    # for BOTH the number this dataclass carries and the number
    # check_limit compares against a limit, so the two can never disagree
    # about whether a total that DISPLAYS as the limit actually reached it.
    cost_usd: float
    tokens_in: int
    tokens_out: int
    rows: int
    rows_with_unknown_cost: int
    # S22: how many of `tokens_in` were served from the provider's prompt
    # cache. Defaulted so every existing construction site keeps working,
    # and 0 for rows written before S22 — which is the honest reading:
    # those calls were not cached. This is the number that answers "is
    # prompt caching actually working?", a question nothing else in the
    # system can answer.
    cached_tokens: int = 0


def month_total(user: str, *, now: datetime | None = None) -> MonthUsage:
    """`user`'s usage for the calendar month containing `now` (default:
    the current Arizona-local month).

    A user with zero matching rows this month gets an all-zero
    `MonthUsage`, not an error and not `None` — "no usage yet" (a new
    hire, a quiet week, month just rolled over) is the overwhelmingly
    common case and should be exactly as cheap for a caller to handle as
    any other.

    `cost_usd` is rounded to the cent ONCE, here, before returning —
    summing raw floats (e.g. 0.1 + 0.7 = 0.7999999999999999 in IEEE 754)
    can leave a total that displays as the exact limit but compares as
    narrowly under it. Rounding at the single point every consumer reads
    from means `check_limit`'s blocked/warn/allowed decision and the
    dollar figure in its message are always computed from the SAME
    number — never two representations of "the same" total that can
    silently disagree.
    """
    when = _as_arizona(now)
    path = _usage_path(_month_shard(when))
    cost_usd = 0.0
    tokens_in = 0
    tokens_out = 0
    cached_tokens = 0
    rows = 0
    rows_with_unknown_cost = 0
    for row in _read_rows(path):
        if row.get("user") != user:
            continue
        rows += 1
        tokens_in += _int_or_zero(row.get("tokens_in"))
        tokens_out += _int_or_zero(row.get("tokens_out"))
        # Absent on pre-S22 rows; `_int_or_zero(None)` is 0, which is the
        # right answer for a call that predates prompt caching.
        cached_tokens += _int_or_zero(row.get("cached_tokens"))
        cost = row.get("cost_usd")
        if isinstance(cost, (int, float)) and not isinstance(cost, bool):
            cost_usd += float(cost)
        else:
            rows_with_unknown_cost += 1
    return MonthUsage(
        cost_usd=round(cost_usd, 2),
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        rows=rows,
        rows_with_unknown_cost=rows_with_unknown_cost,
        cached_tokens=cached_tokens,
    )


# ---------------------------------------------------------------------------
# Limit enforcement
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LimitStatus:
    """The result of `check_limit` — one shared shape so every caller
    (Task 6's tool loop, gating a call before it happens; Task 8's
    `/api/ai/status` route, rendering a banner) reads the SAME state and
    the SAME S19 message text, instead of each re-deriving the 80%
    boundary or re-typing the blocked wording.

    `status` is one of `"allowed" | "warn" | "blocked"`. `message` is
    `None` exactly when there is nothing a user needs to be told
    (ordinary "allowed" with usage comfortably under the limit); it is
    filled with the exact S19 wording for `"blocked"` and with an
    analogous heads-up for `"warn"`.

    `reason` distinguishes WHY a call is "allowed" beyond "under the
    limit" — `None` (ordinary case), `"exempt"`, `"no limit"` (no
    default and no override configured), or `"custom endpoint"` (dollar
    limits are structurally unenforceable — S15). Plan 5's admin page
    needs exactly this distinction to render "inactive — exact costs
    unavailable" instead of implying a real limit is being checked and
    passing.

    `limit_usd` / `month_usd` are carried through so a caller doesn't
    have to re-fetch them (`settings.limit_for` / `month_total`) just to
    render a number next to the state.
    """

    status: str
    message: str | None
    reason: str | None
    limit_usd: float | None
    month_usd: float | None


def _format_usd(amount: float) -> str:
    return f"${amount:,.2f}"


def _blocked_message(limit_usd: float, admin_username: str) -> str:
    # S19's exact wording, verbatim except for the two fill-ins. Empty
    # `admin_username` (an admin hasn't set one yet) must still read as
    # a sentence a non-technical analyst can act on — "ask  to raise it"
    # is not that — so it falls back to "your admin" rather than leaving
    # a blank.
    admin_phrase = f"ask {admin_username}" if admin_username else "ask your admin"
    return (
        f"You've reached your monthly AI usage limit ({_format_usd(limit_usd)}) "
        f"— {admin_phrase} to raise it."
    )


def _warn_message(month_usd: float, limit_usd: float) -> str:
    # S19 pins the BLOCKED wording verbatim but only says "a warning
    # shows at 80%" — no exact text is specified for warn, so this is a
    # deliberately-composed heads-up in the same voice (states the
    # numbers, no alarm language), not an invented duplicate of the
    # blocked message.
    ratio_pct = round((month_usd / limit_usd) * 100)
    return (
        f"You've used {_format_usd(month_usd)} of your {_format_usd(limit_usd)} "
        f"monthly AI usage limit ({ratio_pct}%)."
    )


def check_limit(
    user: str, settings: Settings, *, now: datetime | None = None
) -> LimitStatus:
    """Is `user` allowed to place another AI Mode call right now?

    Resolution order, each a deliberate call documented at its own
    branch below: custom-endpoint mode first (limits are structurally
    inactive, independent of any per-user config) > `Settings.limit_for`
    (already handles the exempt list — this function does NOT
    re-implement that resolution) > a configured `<= 0` limit (treated
    as "block outright," not "unlimited" — `None` already owns
    "unlimited") > the ordinary ratio-against-this-month's-spend check.

    `search is never affected` (S19) — this function is never called on
    the search path; only Task 6's AI Mode tool loop consults it.
    """
    if settings.provider.provider == "custom":
        # S15/S19: a custom endpoint's cost_usd is always None (no
        # OpenRouter usage accounting), so there is nothing numeric to
        # compare against a dollar limit. This is NOT "no limit was
        # configured" — it is "there is no meaningful limit to check" —
        # which is exactly what `reason="custom endpoint"` distinguishes
        # for a caller.
        return LimitStatus(
            status="allowed",
            message=None,
            reason="custom endpoint",
            limit_usd=None,
            month_usd=None,
        )

    limit_usd = settings.limit_for(user)
    if limit_usd is None:
        reason = "exempt" if user in settings.exempt_users else "no limit"
        return LimitStatus(
            status="allowed",
            message=None,
            reason=reason,
            limit_usd=None,
            month_usd=month_total(user, now=now).cost_usd,
        )

    if limit_usd <= 0:
        # An admin who types 0 (or, by typo, a negative number) almost
        # certainly means "this user may spend nothing" — `None` already
        # means "unlimited" (see Settings.limit_for's docstring), so a
        # concrete non-positive number has to mean something else, and
        # "block outright, before even looking at this month's usage" is
        # the only reading under which typing 0 isn't a silent no-op.
        # Displayed as $0.00 (clamped) rather than a possibly-negative
        # number, which would read as a typo rather than a deliberate
        # limit.
        return LimitStatus(
            status="blocked",
            message=_blocked_message(max(limit_usd, 0.0), settings.admin_username),
            reason=None,
            limit_usd=limit_usd,
            month_usd=month_total(user, now=now).cost_usd,
        )

    month_usd = month_total(user, now=now).cost_usd
    ratio = month_usd / limit_usd
    if ratio >= 1.0:
        status = "blocked"
        message = _blocked_message(limit_usd, settings.admin_username)
    elif ratio >= WARN_THRESHOLD_RATIO:
        status = "warn"
        message = _warn_message(month_usd, limit_usd)
    else:
        status = "allowed"
        message = None

    return LimitStatus(
        status=status,
        message=message,
        reason=None,
        limit_usd=limit_usd,
        month_usd=month_usd,
    )
