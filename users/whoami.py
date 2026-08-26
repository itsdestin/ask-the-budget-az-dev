"""Who is this process running as, and are two usernames the same person.

THE ONE RESOLVER. Before this module, `app/identity.py::current_user`
honoured the `JLBC_USER` override and three private `_current_user()`
copies in ingest/ did not — so a dev running as "analyst1" for a test
had their AI usage ledgered under that name and their upload job stamped
with their real OS name. `tests/test_users_whoami.py` pins that nothing
else calls `getpass.getuser()` again.

THE ONE IDENTITY RULE (spec U0). Windows is case-insensitive about
usernames but `%USERNAME%` reflects how the person TYPED it at logon, so
the same analyst arrives as `DMOSS` one day and `dmoss` the next. Every
comparison of two usernames in the app goes through `same_person`, and
every filename derived from one goes through `roster_key`. harness/
cannot import this package (Invariant 7), so `harness/settings.py`
carries a three-line public `fold` pinned by test to the same expression
— `harness/ledger.py` imports THAT copy (not this module) to fold the
spend total a monthly cap is compared against.
"""
from __future__ import annotations

import getpass
import hashlib
import os
import re

# Overrides the OS username. Exists for tests and for a dev running two
# "analysts" side by side — NOT as an auth mechanism (spec S11).
USER_ENV_VAR = "JLBC_USER"

_KEY_SAFE = re.compile(r"[^a-z0-9._-]")
_KEY_MAX = 64


def current_user() -> str:
    """The Windows username of this process, or "" if nothing can say.

    "" rather than raising: an unnameable user should lose accurate
    accounting, not the ability to ask a question (`Settings.limit_for`
    resolves "" to the office default). Ingest call sites append
    `or "unknown"` so their Notepad-readable job files keep the word they
    always carried.
    """
    override = os.environ.get(USER_ENV_VAR)
    if override:
        return override
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no username source on this host
        return ""


def fold(username: str) -> str:
    """The comparison form of a username. `casefold`, not `lower`: it is
    the Unicode-correct case-insensitive form (ß/SS, dotted İ) and it is
    what the roster filename is built from, so the two cannot disagree."""
    return username.strip().casefold()


def same_person(a: str, b: str) -> bool:
    """U0. Blank never matches blank — two unnameable users are not one."""
    fa = fold(a)
    return bool(fa) and fa == fold(b)


def roster_key(username: str) -> str:
    """The filename stem for a person's roster file.

    Windows filenames are case-insensitive and Linux (dev, CI) filenames
    are not, so deriving the name from the raw username would fold on one
    platform and not the other. Fold first, then replace anything outside
    `[a-z0-9._-]` (a domain backslash, a space) with `-`, cap at 64, and
    append 8 hex characters of a hash **of the folded form** whenever the
    replacement or the cap changed anything — so a sanitised name cannot
    collide with a different name that sanitises the same way.

    Hashing the FOLDED form and not the original is the correction from
    review: hashing the original gave `DMOSS` and `dmoss` different files,
    which is the exact split U0 exists to remove.
    """
    folded = fold(username)
    if not folded:
        return ""
    cleaned = _KEY_SAFE.sub("-", folded)[:_KEY_MAX]
    if cleaned != folded:
        cleaned += "-" + hashlib.sha1(folded.encode("utf-8")).hexdigest()[:8]
    return cleaned
