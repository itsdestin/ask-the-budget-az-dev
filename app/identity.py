"""Who is this user, and are they the admin? (Plan 5 Task 1, spec S11.)

`current_user()` moved here from `app/routes/conversations.py` — it was
always identity, not conversation, and Plan 5 gave it three new callers
(the admin routes, the usage routes, the claim flow). `conversations.py`
re-imports it so nothing that already depended on it changed.

THE ADMIN GATE IS SOFT AND ALWAYS WILL BE. See `is_admin` for the full
reasoning; the one-sentence version is that this exists so the admin page
isn't advertised office-wide and individual spend isn't casually
browsable, NOT to keep out anyone determined. Nothing may sit behind it
that would be harmful if bypassed.
"""
from __future__ import annotations

import getpass
import os

from harness.settings import Settings

# Overrides the OS username. Exists for tests and for a dev running two
# "analysts" side by side — NOT as an auth mechanism.
USER_ENV_VAR = "JLBC_USER"


def current_user() -> str:
    """Who is asking, per spec S11: the Windows username of this process.

    There is no authentication and this is not pretending to be any. S11 is
    explicit that per-user cost tracking is "not real security" — the app is
    installed per machine (S7) and launched by the person sitting at it (S8),
    so the process owner IS the analyst. Anyone who can set an environment
    variable can call themselves someone else; the ledger is an accounting
    tool for a single office, not an access-control boundary, and building a
    login screen on top of a local-only app would be theater that makes it
    LOOK like one.

    Falls back to "" (which `Settings.limit_for` resolves to the org default)
    rather than raising: an unnameable user should lose accurate accounting,
    not the ability to ask a question.
    """
    override = os.environ.get(USER_ENV_VAR)
    if override:
        return override
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no username source on this host
        return ""


def admin_claimable(settings: Settings) -> bool:
    """Is the admin seat unclaimed, so the next person may take it?

    THE BOOTSTRAP RULE, and why it is this and not one of the two obvious
    alternatives: a fresh install ships `admin_username: ""`.

      - If an empty admin meant "nobody is admin", the first install would
        have no path to configuring anything — no key, no models, no
        limits — and the app would be permanently unusable with no error
        that explains why.
      - If it meant "everybody is admin" forever, a share that never gets
        an admin assigned would leave every analyst able to rewrite the
        OpenRouter key.

    So: an empty `admin_username` is CLAIMABLE. Any user may claim it,
    once, and the claim is written to settings.json. After that it is
    transfer-only — plus the Task 13 break-glass reset file, which is what
    keeps this one-way door from being a trap.
    """
    return not settings.admin_username


def is_admin(settings: Settings, user: str) -> bool:
    """Soft gate (S11) — NOT authentication.

    `current_user()` is the OS username, which any user can override with
    JLBC_USER. This gate exists so the admin page isn't advertised
    office-wide and so individual spend isn't casually browsable, NOT to
    defend against someone determined. Nothing may sit behind it that
    would be harmful if bypassed: the OpenRouter key is spend-capped at
    the provider (S19), and the destructive action here (restore) is
    reversible because it snapshots first.

    Matching is an EXACT string comparison, deliberately — the same rule
    as `Settings.limit_for`. Case folding here would silently merge two
    distinct config rows an admin typed. The cost of that choice is a
    real lockout mode (`destin` vs `Destin`), which is why Task 13's
    break-glass reset is not optional.
    """
    if admin_claimable(settings):
        return True  # unclaimed — see admin_claimable for WHY
    return user == settings.admin_username
