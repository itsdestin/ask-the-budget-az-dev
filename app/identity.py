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

import os
import sys
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

from app import machine_config
from harness.notices import KIND_ADMIN_CLAIMED, record_notice
from harness.settings import (
    Settings,
    load_settings,
    reset_settings_cache,
    save_settings,
)
from store.config import data_dir

from users.whoami import USER_ENV_VAR, current_user, same_person  # noqa: F401 — re-exported

# `current_user` MOVED to users/whoami.py (2026-08-25, spec U0) so that
# ingest/ can share it without importing app/. Re-exported here because ~16
# test modules and every route import it from this module.

# Tier 2 of the lockout recovery (Task 13) and the primary one: an empty
# file with this name in the shared data folder makes admin claimable
# again. Chosen over an environment variable or a CLI flag because it is
# the only mechanism a non-technical person can execute on a locked-down
# Windows PC with nothing but File Explorer.
RESET_FILENAME = "RESET-ADMIN.txt"


def _windows_display_name() -> str:
    """The AD full name (`Geoff Paulsen`), or "" anywhere it isn't available.

    `GetUserNameEx(NameDisplay)` is the documented way to get a person's
    name rather than their logon name. Wrapped in a blanket except because
    every failure here — not Windows, no `secur32`, a machine not joined to
    a domain, an empty AD field — has the same correct answer: fall through
    to the next source. A name on a memo is not worth an exception.
    """
    if sys.platform != "win32":
        return ""
    try:
        import ctypes
        from ctypes import wintypes

        name_display = 3  # EXTENDED_NAME_FORMAT.NameDisplay
        secur32 = ctypes.WinDLL("secur32")
        size = wintypes.ULONG(0)
        secur32.GetUserNameExW(name_display, None, ctypes.byref(size))
        if not size.value:
            return ""
        buffer = ctypes.create_unicode_buffer(size.value)
        if not secur32.GetUserNameExW(name_display, buffer, ctypes.byref(size)):
            return ""
        return buffer.value.strip()
    except Exception:  # noqa: BLE001 — see the docstring
        return ""


def display_name(user: str | None = None) -> str:
    """The name to print on a document this analyst generates.

    Order: stored override > Windows display name > the bare username.

    DEVIATION FROM SPEC M5, which listed Windows first. An override that
    loses to auto-detection cannot correct a WRONG AD name, and a wrong
    name (`JARRETTD`, an un-updated maiden name) is likelier than a
    missing one. The spec's intent — nobody has to type this if Windows
    already knows it — is unaffected, because the override is empty until
    somebody deliberately sets it.

    Never raises: the fallback chain bottoms out at `current_user()`,
    which itself bottoms out at "".
    """
    resolved = current_user() if user is None else user
    override = machine_config.read_display_name(resolved)
    if override:
        return override
    windows = _windows_display_name()
    if windows:
        return windows
    return resolved


def reset_file_path() -> Path:
    """The break-glass file's path in the shared data folder.

    The handbook tells a non-technical reader to create this by name in
    File Explorer (right-click → New → Text Document, rename), so the
    filename is part of a documented procedure — renaming it here silently
    invalidates those steps.
    """
    return data_dir() / RESET_FILENAME


def admin_reset_pending() -> bool:
    """Is a break-glass reset file waiting to be used up?

    Surfaced on `/api/me` so the claim banner can say so explicitly —
    nobody should claim admin by accident and then wonder where their
    reset went.
    """
    try:
        return reset_file_path().is_file()
    except OSError:
        # An unreachable share can't have a reset file we can honour. The
        # health ladder reports the share; this is not the place to raise.
        return False


def admin_claimable(settings: Settings) -> bool:
    """Is the admin seat available, so the next person may take it?

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
    transfer-only — OR until a break-glass reset file appears.

    THE RESET FILE GRANTS NO NEW POWER, and this is the sentence to read
    before "hardening" it: anyone who can create a file in the shared data
    folder can already open `settings.json` in Notepad and edit
    `admin_username` directly. This adds convenience, not access — and the
    convenience is the point, because it is the only mechanism a
    non-technical person can execute on a locked-down Windows PC with
    nothing but File Explorer.

    Note this also fails OPEN on a corrupt settings.json: `load_settings`
    degrades a broken file to `Settings()`, whose `admin_username` is
    empty. That is deliberate — a file nobody can parse must not lock out
    the only person who could fix it.
    """
    if not settings.admin_username:
        return True
    return admin_reset_pending()


def claim_admin(user: str) -> str:
    """Take the admin seat, consuming a reset file if one was used.

    Raises PermissionError when the seat is not available — the HTTP layer
    turns that into the 409 that names the recovery path.
    """
    settings = load_settings()
    if not admin_claimable(settings):
        raise PermissionError("An admin is already configured.")

    previous = settings.admin_username
    save_settings(replace(settings, admin_username=user))
    reset_settings_cache()
    _consume_reset_file()

    if previous:
        # Only worth a notice when it REPLACED someone. A fresh install's
        # first claim is the normal setup path, not an event.
        record_notice(
            KIND_ADMIN_CLAIMED,
            f"{user} claimed admin using a reset file, replacing {previous}. "
            "If that wasn't expected, ask them why.",
        )
    return user


def _consume_reset_file() -> None:
    """Rename the reset file so it can only be used once.

    RENAMED, not deleted: the file is the only evidence that an admin
    takeover happened out-of-band, and silently deleting it would erase
    the one trace anyone could audit later.

    A failure here is LOGGED, NEVER RAISED. A share that has gone
    read-only must not turn a recoverable lockout into a permanent one —
    the claim itself already succeeded, and refusing to complete it
    because the housekeeping failed would be exactly the trap this whole
    mechanism exists to avoid.
    """
    source = reset_file_path()
    if not source.is_file():
        return
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = source.with_name(f"RESET-ADMIN.done-{stamp}.txt")
    try:
        os.replace(source, target)
    except OSError as err:
        print(
            f"app.identity: claimed admin, but the reset file at {source} "
            f"could not be renamed ({err}). The claim stands. Delete or "
            "rename that file by hand, or the next person to open the Admin "
            "page can claim it too.",
            file=sys.stderr,
        )


def is_admin(settings: Settings, user: str) -> bool:
    """Soft gate (S11) — NOT authentication.

    `current_user()` is the OS username, which any user can override with
    JLBC_USER. This gate exists so the admin page isn't advertised
    office-wide and so individual spend isn't casually browsable, NOT to
    defend against someone determined. Nothing may sit behind it that
    would be harmful if bypassed: the OpenRouter key is spend-capped at
    the provider (S19), and the destructive action here (restore) is
    reversible because it snapshots first.

    Matching folds case (spec U0, 2026-08-25) via `users.whoami.same_person`
    — the ONE rule every username comparison uses. It was exact, with a
    real lockout mode (`destin` vs `Destin`) that the break-glass file
    existed to recover from; once the seat is set from a dropdown of
    observed usernames the "two typed rows" argument for exactness is gone.
    """
    if admin_claimable(settings):
        return True  # unclaimed — see admin_claimable for WHY
    return same_person(user, settings.admin_username)
