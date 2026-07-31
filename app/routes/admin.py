"""Admin identity + the /api/admin/* surface (Plan 5, Track 1).

Created by Task 1 with `GET /api/me`, extended by Task 3 with the
settings read/write pair, and filled out by Tasks 4–7 with the catalog,
usage, corpus and backup endpoints.

Every route under /api/admin/ is gated by `require_admin` — a SOFT gate
(spec S11). Read `app/identity.is_admin` before adding anything here:
nothing may sit behind this gate that would be harmful if bypassed.
`GET /api/me` itself is deliberately ungated — it is how the webapp
learns whether to render the Admin pill at all, so every user must be
able to call it.

REDACTION IS A HARD RULE HERE, not a nicety. `GET /api/admin/settings`
never returns `api_key`; `PUT` accepts the literal sentinel
`"__unchanged__"` so an admin editing a spend limit cannot blank the key
by round-tripping the form. Both failures are silent — see the module
docstring of tests/test_admin_settings_route.py.
"""
from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import admin_claimable, current_user, is_admin
from harness.settings import (
    ProviderConfig,
    Settings,
    TierConfig,
    load_settings,
    reset_settings_cache,
    save_settings,
)

router = APIRouter()

# The literal a client sends in place of the key to mean "I am not editing
# this field". Spelled out rather than "" because "" is a REAL edit an
# admin can legitimately make (clearing the key to turn AI Mode off), and
# a form that submits every field it rendered has no other way to say
# "leave the one I was never shown alone".
UNCHANGED = "__unchanged__"

VALID_PROVIDERS = ("openrouter", "custom")

# What a model id has to look like when the catalog can't vouch for it:
# `vendor/model`, optionally with an OpenRouter variant suffix
# (`:free`, `:nitro`). Deliberately loose — this is a typo catcher, not
# an allowlist. A brand-new model released tomorrow must be typeable by
# an admin who read about it before the catalog cache refreshed.
_MODEL_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._:-]*$")

MSG_BAD_MODEL = (
    "That model id doesn't look right — pick one from the list, "
    "or check the spelling."
)
MSG_NEGATIVE_LIMIT = (
    "A monthly limit can't be negative. Leave it blank for no limit, "
    "or enter 0 to block a user entirely."
)
MSG_BLANK_USERNAME = (
    "A spend limit needs a username. Remove the blank row, or type "
    "the Windows username it applies to."
)
MSG_BAD_PROVIDER = "Provider must be either 'openrouter' or 'custom'."
MSG_BAD_BASE_URL = "The endpoint address needs to start with http:// or https://."
MSG_BLANK_ADMIN = (
    "The admin username can't be blank — that would hand admin access "
    "to everyone. To hand over the app, type the new admin's Windows "
    "username; to reset it entirely, see 'If nobody can get into Admin' "
    "in the handbook."
)


def _bad_request(detail: str) -> HTTPException:
    """One plain sentence, 400. Never a field path or a validator name —
    the reader is a non-technical admin looking at a form."""
    return HTTPException(status_code=400, detail=detail)


# ---------------------------------------------------------------------------
# The gate
# ---------------------------------------------------------------------------


def require_admin() -> Settings:
    """FastAPI dependency: 403 unless the caller holds the (soft) admin seat.

    Returns the loaded Settings so a handler doesn't re-read them — one
    read per request, and the handler is guaranteed to be looking at the
    same snapshot the gate decided on.

    A dependency rather than a check inside each handler because a check
    inside each handler is a check somebody eventually forgets to write;
    tests/test_admin_settings_route.py enumerates this router's routes and
    fails if any of them answers a non-admin.
    """
    settings = load_settings()
    user = current_user()
    if not is_admin(settings, user):
        raise HTTPException(
            status_code=403,
            detail=(
                f"The Admin page is limited to {settings.admin_username}. "
                "Ask them if you need something changed."
            ),
        )
    return settings


# ---------------------------------------------------------------------------
# GET /api/me
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# GET/PUT /api/admin/settings
# ---------------------------------------------------------------------------


def _key_hint(api_key: str) -> str:
    """A last-four fingerprint an admin can match against their OpenRouter
    dashboard, and nothing more.

    A key of four characters or fewer gets a bare ellipsis: "…abc" would
    print the whole thing, and the point of a hint is that it is safe to
    read out loud, screenshot, or leave on a projector.
    """
    if not api_key:
        return ""
    if len(api_key) <= 4:
        return "…"
    return "…" + api_key[-4:]


def _redacted(settings: Settings) -> dict[str, Any]:
    """The frozen GET shape. THE API KEY IS NEVER IN IT.

    Note what is returned instead: `api_key_set` (so the UI can say "a key
    is configured" without holding one) and `api_key_hint` (so an admin
    staring at two OpenRouter keys can tell which one this is).
    """
    return {
        "provider": {
            "provider": settings.provider.provider,
            "base_url": settings.provider.base_url,
            "api_key_set": bool(settings.provider.api_key),
            "api_key_hint": _key_hint(settings.provider.api_key),
        },
        "tiers": {name: {"model": cfg.model} for name, cfg in settings.tiers.items()},
        "admin_username": settings.admin_username,
        "default_monthly_limit_usd": settings.default_monthly_limit_usd,
        "user_limits": dict(settings.user_limits),
        "exempt_users": list(settings.exempt_users),
    }


class ProviderBody(BaseModel):
    provider: str | None = None
    base_url: str | None = None


class TierBody(BaseModel):
    model: str = ""


class SettingsBody(BaseModel):
    """Every field optional, on purpose.

    "Absent" and "explicitly set to null" are different requests here —
    an omitted `default_monthly_limit_usd` means "don't touch it", a null
    one means "no limit". Pydantic's `model_fields_set` is what tells them
    apart, so the handler below checks membership in that set rather than
    testing for None.
    """

    provider: ProviderBody | None = None
    tiers: dict[str, TierBody] | None = None
    admin_username: str | None = None
    default_monthly_limit_usd: float | None = None
    user_limits: dict[str, float] | None = None
    exempt_users: list[str] | None = None
    api_key: str | None = None
    confirm_admin_transfer: bool = False


def _model_id_looks_valid(model_id: str) -> bool:
    """Typo gate for a hand-typed model id.

    Empty is VALID: a tier with no model assigned is a supported state
    (`ai_available` reports "no model configured — ask the admin" for that
    tier while the other keeps working), and rejecting it would stop an
    admin part-way through setup.

    Task 4 adds the catalog as a second acceptance path — an id the live
    catalog confirms is valid even if it doesn't match this pattern. Until
    then, and whenever the catalog is unreachable, the shape check is the
    whole rule.
    """
    if not model_id:
        return True
    return bool(_MODEL_ID.match(model_id))


def _validate(new: Settings, current: Settings, body: SettingsBody) -> None:
    """Raise the first problem as one plain 400 sentence, or return.

    One message at a time rather than a list: the admin page renders a
    form the admin is editing live, and a wall of validation text reads as
    "everything is broken" when one field has a typo in it.
    """
    if new.provider.provider not in VALID_PROVIDERS:
        raise _bad_request(MSG_BAD_PROVIDER)
    if not new.provider.base_url.startswith(("http://", "https://")):
        raise _bad_request(MSG_BAD_BASE_URL)

    for cfg in new.tiers.values():
        if not _model_id_looks_valid(cfg.model):
            raise _bad_request(MSG_BAD_MODEL)

    if new.default_monthly_limit_usd is not None and new.default_monthly_limit_usd < 0:
        raise _bad_request(MSG_NEGATIVE_LIMIT)
    for username, limit in new.user_limits.items():
        if not username.strip():
            raise _bad_request(MSG_BLANK_USERNAME)
        if limit < 0:
            raise _bad_request(MSG_NEGATIVE_LIMIT)
    for username in new.exempt_users:
        if not username.strip():
            raise _bad_request(MSG_BLANK_USERNAME)

    # --- the lockout guards -------------------------------------------
    if new.admin_username != current.admin_username:
        if not new.admin_username.strip():
            # No confirmation flag can authorise this: it un-claims the
            # install, and the next person to open the page — anyone —
            # becomes admin.
            raise _bad_request(MSG_BLANK_ADMIN)
        if not body.confirm_admin_transfer:
            raise _bad_request(
                f'Transferring admin to "{new.admin_username}" means you '
                "lose access to this page yourself, and only they can give "
                "it back. Confirm the transfer if that's what you want."
            )


def _merge(current: Settings, body: SettingsBody) -> Settings:
    """Apply only the fields the client actually sent.

    NEVER build a Settings field-by-field out of the request body: a
    client on an older shape (an admin page from a previous version, left
    open in a tab) would silently blank every field it has never heard of.
    Starting from disk and replacing what was supplied means an unknown
    field survives the round trip untouched.
    """
    sent = body.model_fields_set
    provider = current.provider
    if body.provider is not None:
        p_sent = body.provider.model_fields_set
        provider = replace(
            provider,
            provider=(body.provider.provider or "") if "provider" in p_sent else provider.provider,
            base_url=(body.provider.base_url or "") if "base_url" in p_sent else provider.base_url,
        )
    # The key rides at the TOP level of the body, not inside `provider`,
    # so a client can send the (redacted) provider block it was given back
    # verbatim and add the key beside it.
    if "api_key" in sent and body.api_key != UNCHANGED:
        provider = replace(provider, api_key=body.api_key or "")

    tiers = dict(current.tiers)
    if body.tiers is not None:
        # Per-tier merge: sending only {"standard": …} must not delete the
        # Deep Research assignment.
        for name, tier in body.tiers.items():
            tiers[str(name)] = TierConfig(model=tier.model)

    return Settings(
        provider=provider,
        tiers=tiers,
        admin_username=(
            body.admin_username if "admin_username" in sent and body.admin_username is not None
            else current.admin_username
        ),
        default_monthly_limit_usd=(
            body.default_monthly_limit_usd if "default_monthly_limit_usd" in sent
            else current.default_monthly_limit_usd
        ),
        # user_limits and exempt_users replace WHOLESALE when supplied,
        # unlike tiers: removing a row is a real edit an admin makes, and
        # a per-key merge would make deletion impossible through the UI.
        user_limits=(
            {str(k): float(v) for k, v in body.user_limits.items()}
            if body.user_limits is not None else dict(current.user_limits)
        ),
        exempt_users=(
            tuple(str(u) for u in body.exempt_users)
            if body.exempt_users is not None else current.exempt_users
        ),
    )


@router.get("/api/admin/settings")
def get_settings(settings: Settings = Depends(require_admin)) -> dict:
    return _redacted(settings)


@router.put("/api/admin/settings")
def put_settings(
    body: SettingsBody, settings: Settings = Depends(require_admin)
) -> dict:
    merged = _merge(settings, body)
    _validate(merged, settings, body)
    save_settings(merged)
    # Drop the mtime cache before re-reading: the response is the admin's
    # confirmation that the save landed, so it has to come from disk, not
    # from a cache entry stamped a millisecond before the write.
    reset_settings_cache()
    return _redacted(load_settings())
