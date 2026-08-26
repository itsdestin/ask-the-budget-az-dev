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

import json
import re
import sys
import threading
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from app import identity, machine_config
from app.machine_config import ingest_enabled, set_ingest_enabled
# Moved out 2026-08-16: the upload page needs the same answer, and two
# implementations of "is the queue stalled?" would eventually disagree in
# the worst way — the admin page saying all is well while an analyst stares
# at a stuck upload. See app/queue_status.py.
from app.queue_status import (
    MSG_QUEUE_STALLED,
    TERMINAL_JOB_STATES,
    queue_stalled,
    queue_summary,
)
from app.identity import (
    admin_claimable,
    admin_reset_pending,
    claim_admin,
    current_user,
    display_name,
    is_admin,
)
from harness.catalog import fetch_catalog
from harness.ledger import ARIZONA_TZ, breakdown, check_limit, month_total
from harness.notices import read_notices
from harness.settings import (
    ProviderConfig,
    Settings,
    TierConfig,
    load_settings,
    reset_settings_cache,
    save_settings,
)
from ingest.lock import IngestLock, LockHeldError
# The route compares against the SAME constant the ladder decided with
# (ingest/structure.py), never a copy: a panel whose threshold has drifted
# from the pipeline's would quietly stop listing documents the pipeline
# considers bad, which is worse than not having the panel.
from ingest.structure import MAX_UNLABELLED
from store.backup import (
    SNAPSHOT_PREFIX,
    SNAPSHOT_SUFFIX,
    backups_dir,
    list_snapshots,
    restore,
    snapshot,
)
from store.config import data_dir, documents_path
from users import registry

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
MSG_NEED_PRICES = (
    "Enter what your AI service charges, per million tokens in and out. "
    "Without both figures the app can't work out what anything costs, and "
    "spending limits stop working."
)
MSG_NEGATIVE_PRICE = "A price can't be negative."
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
def me() -> JSONResponse:
    """Who the caller is and what the app will let them see.

    The webapp reads this on load to decide whether the Admin nav pill
    renders and whether to show the "no admin is set up yet" banner.
    `admin_username` is returned to EVERY user, not just the admin,
    because a blocked analyst's next question is "who do I ask?" and the
    ledger's own message ("ask Destin to raise it") needs that name to
    have come from somewhere.

    ALSO WHERE A PERSON GETS WRITTEN DOWN (spec U3): this is the one
    request every user makes, so the roster touch rides on it — as a
    BackgroundTask, after the response is sent, so a slow share cannot
    delay whether the nav renders (spec U4). The response body is
    byte-identical whether or not the touch succeeds.
    """
    settings = load_settings()
    user = current_user()
    body = {
        "user": user,
        "is_admin": is_admin(settings, user),
        "admin_username": settings.admin_username,
        "admin_claimable": admin_claimable(settings),
        # Surfaced so the claim banner can say "a reset file is present and
        # claiming will use it up" — nobody should burn a reset by accident
        # and then wonder where it went.
        "admin_reset_pending": admin_reset_pending(),
        # The name printed on documents this analyst generates. Resolved
        # server-side (roster > override > Windows > username) so the
        # Settings field shows the SAME string the memo will carry, rather
        # than a client-side guess that could disagree with it.
        "display_name": display_name(user),
    }
    return JSONResponse(body, background=BackgroundTask(_touch_roster, user))


def _touch_roster(user: str) -> None:
    """Never raises. A missing touch means a `last_seen` date is a day
    stale — the opposite posture to the ledger, where a missing row means
    money spent and not recorded."""
    try:
        # `identity._windows_display_name()`, not a bare imported name: a
        # `from app.identity import _windows_display_name` here would bind
        # this module's OWN reference to the function object at import
        # time, so a test's `monkeypatch.setattr(identity,
        # "_windows_display_name", ...)` would silently miss this call
        # site — caught by test_me_registers_the_caller_in_the_roster.
        registry.touch(
            user,
            windows_name=identity._windows_display_name(),
            local_typed_name=machine_config.read_display_name(user),
        )
    except Exception as err:  # noqa: BLE001 — see the docstring
        print(f"app.routes.admin: roster touch for {user!r} failed ({err})", file=sys.stderr)


class DisplayNameBody(BaseModel):
    display_name: str = Field(default="", max_length=machine_config.MAX_DISPLAY_NAME)


@router.put("/api/me/display-name")
def set_my_display_name(body: DisplayNameBody) -> dict:
    """The analyst's own name, as it appears on documents they generate.

    DELIBERATELY UNGATED, like `GET /api/me`. There is no authentication
    anywhere in this app (S11), so a gate here would be theater.

    Writes BOTH stores (spec U6): the local machine file first — it is the
    offline fallback and the thing the analyst sitting here asked for — then
    the shared roster. A roster failure is logged and the request still
    returns 200, but NOT necessarily with the name just typed: the response
    is whatever `display_name()` resolves at that moment, and `display_name()`
    reads the roster FIRST. If a roster row with a typed name already exists
    and only this roster write fails, that means the PREVIOUS roster name —
    not the new one — because the ladder is still telling the truth about
    what a memo generated on this machine WILL print (the roster name,
    whenever the share can be read). The Settings page renders the returned
    value, so the analyst sees the save did not fully take and can retry
    once the share is back, rather than being told a name took effect that
    the next machine to read the share will not see.
    """
    user = current_user()
    machine_config.set_display_name(user, body.display_name)
    try:
        registry.set_typed_name(user, body.display_name)
    except Exception as err:  # noqa: BLE001 — local write already succeeded
        print(f"app.routes.admin: roster name save for {user!r} failed ({err})", file=sys.stderr)
    return {"display_name": display_name(user)}


# ---------------------------------------------------------------------------
# POST /api/admin/claim
# ---------------------------------------------------------------------------

MSG_ALREADY_CLAIMED = (
    "An admin is already configured. To reset it, see 'If nobody can get "
    "into Admin' in the handbook."
)


class ClaimBody(BaseModel):
    confirm: bool = False


@router.post("/api/admin/claim")
def claim(body: ClaimBody) -> dict:
    """Take the unclaimed admin seat. DELIBERATELY NOT `require_admin`-gated.

    It would *work* gated — an unclaimed install makes `is_admin` true for
    everyone, so the gate would pass — but a non-admin hitting this on a
    CLAIMED install would then get "The Admin page is limited to Destin",
    which answers the wrong question. The 409 below tells the reader the
    thing they actually need to know: an admin exists, and here is where
    to look if nobody can reach them.

    Nothing is granted here that isn't already available to anyone who can
    open `settings.json` in Notepad — see `app.identity.is_admin`.
    """
    if not body.confirm:
        raise _bad_request("Confirm that you want to become the admin.")
    try:
        # `claim_admin` owns the whole procedure, including consuming a
        # break-glass reset file and recording the notice — this route must
        # not reimplement half of it.
        return {"admin_username": claim_admin(current_user())}
    except PermissionError as err:
        raise HTTPException(status_code=409, detail=MSG_ALREADY_CLAIMED) from err


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
            # Prices are NOT secret — they are what the admin typed, and
            # the form has to render them back to be editable.
            "prompt_usd_per_m": settings.provider.prompt_usd_per_m,
            "completion_usd_per_m": settings.provider.completion_usd_per_m,
        },
        # Resolved values, not the raw sentinels — the webapp renders these
        # into switches, and `undefined` would read as "off" for an install
        # whose settings.json simply predates the switches.
        "tiers": {
            name: {"model": cfg.model, "enabled": cfg.is_enabled}
            for name, cfg in settings.tiers.items()
        },
        "ai_enabled": settings.ai_is_enabled,
        "admin_username": settings.admin_username,
        "default_monthly_limit_usd": settings.default_monthly_limit_usd,
        "user_limits": dict(settings.user_limits),
        "exempt_users": list(settings.exempt_users),
    }


class ProviderBody(BaseModel):
    provider: str | None = None
    base_url: str | None = None
    prompt_usd_per_m: float | None = None
    completion_usd_per_m: float | None = None


class TierBody(BaseModel):
    model: str = ""
    enabled: bool | None = None


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
    ai_enabled: bool | None = None
    admin_username: str | None = None
    default_monthly_limit_usd: float | None = None
    user_limits: dict[str, float] | None = None
    exempt_users: list[str] | None = None
    api_key: str | None = None
    confirm_admin_transfer: bool = False


def _model_id_looks_valid(model_id: str, settings: Settings) -> bool:
    """Typo gate for a hand-typed model id.

    Two acceptance paths, per the plan: the id has a plausible
    `vendor/model` SHAPE, **or** the live catalog vouches for it. Either
    is enough — the goal is catching `gpt4` typed into a text box, not
    restricting an admin to a list that is stale by construction.

    Empty is VALID: a tier with no model assigned is a supported state
    (`ai_available` reports "no model configured — ask the admin" for that
    tier while the other keeps working), and rejecting it would stop an
    admin part-way through setup.

    WHY the catalog is consulted only AFTER the shape check fails: this
    runs on every settings save, and a cold cache means a network round
    trip. The shape check passes for essentially every real id, so the
    slow path is reached only by something already suspicious. When the
    catalog is unreachable it contributes nothing and the shape check is
    the whole rule — which is the right degradation, since refusing to
    save because we couldn't reach OpenRouter would be worse than
    accepting an id the admin can test with one click.
    """
    if not model_id:
        return True
    if _MODEL_ID.match(model_id):
        return True
    return any(card.id == model_id for card in fetch_catalog(settings).catalog)


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
    if new.provider.provider == "custom":
        prices = (new.provider.prompt_usd_per_m, new.provider.completion_usd_per_m)
        if any(p is not None and p < 0 for p in prices):
            raise _bad_request(MSG_NEGATIVE_PRICE)
        if any(p is None for p in prices):
            # THE point of this rule: without prices, every call lands in
            # the ledger with an unknown cost, which silently switches
            # spend limits off office-wide. Refusing the save is how that
            # stops being a state an admin can wander into.
            raise _bad_request(MSG_NEED_PRICES)

    for cfg in new.tiers.values():
        if not _model_id_looks_valid(cfg.model, new):
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
            # Explicit null is a real edit here ("clear this price"), so
            # these read from the sent-set like every other field rather
            # than treating None as "not supplied".
            prompt_usd_per_m=(
                body.provider.prompt_usd_per_m if "prompt_usd_per_m" in p_sent
                else provider.prompt_usd_per_m
            ),
            completion_usd_per_m=(
                body.provider.completion_usd_per_m if "completion_usd_per_m" in p_sent
                else provider.completion_usd_per_m
            ),
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
            existing = tiers.get(str(name))
            t_sent = tier.model_fields_set
            tiers[str(name)] = TierConfig(
                model=tier.model if "model" in t_sent else (existing.model if existing else ""),
                # An omitted `enabled` keeps whatever was there — a client on
                # an older shape must not silently switch a mode off.
                enabled=(
                    tier.enabled if "enabled" in t_sent
                    else (existing.enabled if existing else None)
                ),
            )

    return Settings(
        provider=provider,
        tiers=tiers,
        ai_enabled=(
            body.ai_enabled if "ai_enabled" in sent else current.ai_enabled
        ),
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


# ---------------------------------------------------------------------------
# GET /api/admin/models
# ---------------------------------------------------------------------------


@router.get("/api/admin/models")
def get_models(
    refresh: int = 0, settings: Settings = Depends(require_admin)
) -> dict:
    """The model picker's data (S13).

    `refresh=1` bypasses the six-hour cache — the escape hatch for an
    admin who just read about a model and wants to see it now. Everything
    else, including a total network failure, comes back as a 200 with a
    `note`: this is the page an admin opens BECAUSE something is wrong,
    so it must never be the page that fails.
    """
    result = fetch_catalog(settings, refresh=bool(refresh))
    return {
        "source": result.source,
        "fetched_at": result.fetched_at,
        "recommended": [card.as_dict() for card in result.recommended],
        "catalog": [card.as_dict() for card in result.catalog],
        "note": result.note,
    }


# ---------------------------------------------------------------------------
# GET /api/admin/notices
# ---------------------------------------------------------------------------


@router.get("/api/admin/notices")
def get_notices(
    since: str | None = None, _settings: Settings = Depends(require_admin)
) -> dict:
    """"What went wrong while you weren't looking" (S13).

    `since` is an ISO timestamp — the admin page passes back the `at` of
    the newest notice it has already shown, so a poll returns only what
    is new.
    """
    return {"notices": read_notices(since=since)}


# ---------------------------------------------------------------------------
# Usage (S19)
# ---------------------------------------------------------------------------

_MONTH_SHARD = re.compile(r"^\d{4}-\d{2}$")

MSG_BAD_MONTH = "Pick a month in YYYY-MM form, like 2026-07."


def _current_month() -> str:
    """This month in ARIZONA-local terms, matching the ledger's shards.

    Not the host clock's month: `harness.ledger` shards on a fixed UTC-7
    offset because a single Arizona office should roll over on its own
    midnight, and a default that disagreed with the shard names would
    show an empty page for the first seven hours of every month.
    """
    now = datetime.now(ARIZONA_TZ)
    return f"{now.year:04d}-{now.month:02d}"


def _group_dicts(groups) -> list[dict[str, Any]]:
    return [
        {
            "key": g.key,
            "cost_usd": g.cost_usd,
            "tokens_in": g.tokens_in,
            "tokens_out": g.tokens_out,
            "cached_tokens": g.cached_tokens,
            "rows": g.rows,
            "rows_with_unknown_cost": g.rows_with_unknown_cost,
        }
        for g in groups
    ]


@router.get("/api/admin/usage")
def get_usage(
    month: str | None = None, settings: Settings = Depends(require_admin)
) -> dict:
    """The office's spend for one month, three ways.

    The office totals are summed from the by-user groups rather than
    recomputed from the rows: three breakdowns of one month that don't
    add up to the same number is what makes an admin stop believing the
    page, and summing one of them guarantees they agree by construction.
    """
    shard = month or _current_month()
    if not _MONTH_SHARD.match(shard):
        raise _bad_request(MSG_BAD_MONTH)

    by_user = breakdown(shard, by="user")
    # "Are limits doing anything here?" is a question about the OFFICE, not
    # about the admin reading the page. Asked with the per-user rows
    # stripped, so an admin who put themselves on the exempt list doesn't
    # see "limits inactive" and conclude nobody is capped. The answer still
    # comes from check_limit — S19's policy lives in exactly one place
    # (Ground truth 7) and `reason` is its own string, never re-derived.
    org_view = replace(settings, user_limits={}, exempt_users=())
    org_limit = check_limit("", org_view)
    limits_active = org_limit.reason is None and org_limit.limit_usd is not None

    return {
        "month": shard,
        "total_usd": round(sum(g.cost_usd for g in by_user), 2),
        "rows": sum(g.rows for g in by_user),
        "rows_with_unknown_cost": sum(g.rows_with_unknown_cost for g in by_user),
        "cached_tokens": sum(g.cached_tokens for g in by_user),
        "tokens_in": sum(g.tokens_in for g in by_user),
        "by_user": _group_dicts(by_user),
        "by_model": _group_dicts(breakdown(shard, by="model")),
        "by_tier": _group_dicts(breakdown(shard, by="tier")),
        "limits_active": limits_active,
        "limits_inactive_reason": None if limits_active else org_limit.reason,
    }


@router.get("/api/me/usage")
def get_my_usage() -> dict:
    """The caller's own spend. DELIBERATELY NOT ADMIN-GATED.

    An analyst who has just been told "you've reached your monthly limit"
    needs to be able to see the number and who to ask, without that
    requiring admin access. It returns only the calling user's own rows,
    so an ungated endpoint leaks nothing about anyone else.
    """
    settings = load_settings()
    user = current_user()
    limit = check_limit(user, settings)
    usage = month_total(user)
    return {
        "month": _current_month(),
        "month_usd": usage.cost_usd,
        "limit_usd": limit.limit_usd,
        "status": limit.status,
        # The ledger's exact sentence, emitted from one place — a re-typed
        # copy here would give the office two subtly different "you're over
        # your limit" messages.
        "message": limit.message,
        "reason": limit.reason,
        "rows_with_unknown_cost": usage.rows_with_unknown_cost,
    }


# ---------------------------------------------------------------------------
# Corpus health (S17)
# ---------------------------------------------------------------------------

# Job states that mean "this document is being worked on right now".
# Derived from ingest.jobs.PIPELINE_STATES rather than re-typed, so a new
# pipeline stage counts as running without anyone remembering to come here.


def _dir_bytes(path: Path) -> int:
    """Total size of every file under `path`, 0 if it isn't there.

    Unreadable files are skipped rather than raised on: this walks a
    network share while an ingest may be rewriting it, and a size readout
    is never worth failing the page over.
    """
    total = 0
    if not path.is_dir():
        return 0
    for child in path.rglob("*"):
        try:
            if child.is_file():
                total += child.stat().st_size
        except OSError:
            continue
    return total


# Both counters live in app/routes/corpus.py, which serves the ungated
# footer endpoint. Shared rather than reimplemented: the admin page and the
# footer showing different corpus sizes on the same screen is exactly the
# kind of thing that makes an admin stop trusting both numbers.
from app.routes.corpus import chunk_counts as _chunk_counts  # noqa: E402
from app.routes.corpus import document_count as _document_count  # noqa: E402


def _reclaimable_bytes() -> int | None:
    """Roughly how much of `lancedb/` is superseded versions, or None.

    WHY THIS IS AN ESTIMATE, stated here so nobody later reports it as
    exact: LanceDB keeps every superseded version until a cleanup runs,
    and measuring the dead set precisely means reading each old manifest —
    which needs the `pylance` package this app deliberately does not
    depend on. What IS exactly measurable is the total on disk and, via
    `table.stats()["total_bytes"]`, the size of the CURRENT version. The
    difference is dominated by dead versions but also includes indices and
    live manifests, so it never reaches zero on a healthy corpus.

    That is still the number worth showing: the failure it reveals is 5.1
    GB on disk holding ~18k chunks, where the signal is the order of
    magnitude, not the last byte. Returns None when nothing can be
    measured, so the UI renders "unknown" rather than a confident 0.
    """
    root = data_dir() / "lancedb"
    if not root.is_dir():
        return None
    try:
        from store.chunk_store import ChunkStore

        store = ChunkStore()
    except Exception:  # noqa: BLE001
        return None

    live = 0
    measured = False
    for name in ("budget_chunks", "fiscal_note_chunks"):
        try:
            table = store._open(name)  # noqa: SLF001 — see below
            if table is None:
                continue
            stats = table.stats()
        except Exception:  # noqa: BLE001
            continue
        value = stats.get("total_bytes") if isinstance(stats, dict) else None
        if isinstance(value, (int, float)):
            live += int(value)
            measured = True
    if not measured:
        return None
    # `_open` is ChunkStore's private accessor. Used deliberately rather
    # than adding a public passthrough for one diagnostic: this is the only
    # caller, and a public "give me the raw table" method is an invitation
    # to bypass the store's schema and dimension checks elsewhere.
    return max(0, _dir_bytes(root) - live)


class MachineIngestBody(BaseModel):
    enabled: bool


@router.post("/api/admin/machine/ingest")
def set_machine_ingest(
    body: MachineIngestBody, _settings: Settings = Depends(require_admin)
) -> dict:
    """Make (or unmake) THIS computer the one that processes uploads.

    Per-machine, not in settings.json: settings.json lives on the share and
    every machine reads it, which is the wrong home for "is this PC the one
    that does the work".

    The response says a restart is needed because it is — the worker starts
    from the lifespan hook, so flipping this cannot start one inside the
    process already running. An admin who wasn't told that would watch a
    queue that never moves and reasonably conclude the button is broken.
    """
    set_ingest_enabled(body.enabled)
    return {
        "ingest_enabled_here": body.enabled,
        "message": (
            "This computer will process uploads after JLBC Search is "
            "restarted here."
            if body.enabled
            else "This computer will stop processing uploads after JLBC "
                 "Search is restarted here."
        ),
    }


@router.get("/api/admin/corpus")
def get_corpus(_settings: Settings = Depends(require_admin)) -> dict:
    counts = _chunk_counts()
    queue, last_ingest_at = queue_summary()
    stalled = queue_stalled(queue)
    return {
        "data_dir": str(data_dir()),
        "budget_chunks": counts["budget_chunks"],
        "fiscal_note_chunks": counts["fiscal_note_chunks"],
        "documents": _document_count(),
        "ingest_enabled_here": ingest_enabled(),
        "queue_stalled": stalled,
        "queue_stalled_message": MSG_QUEUE_STALLED if stalled else None,
        "lancedb_bytes": _dir_bytes(data_dir() / "lancedb"),
        "dead_version_bytes": _reclaimable_bytes(),
        "last_ingest_at": last_ingest_at,
        "queue": queue,
    }


# ---------------------------------------------------------------------------
# Identity findings (spec I15) — eval/identity_check.py's report, read the
# same mtime-cached-degrade-to-empty way store/office_aliases.py reads its
# JSON file on the data dir. NOT the notices.json shape: notices is an
# append-only JSONL log with its own reader in harness/notices.py; this is
# one whole-file JSON object rewritten wholesale by a batch script, so the
# office_aliases.py pattern is the closer model.
# ---------------------------------------------------------------------------

IDENTITY_REPORT_FILE = "identity-report.json"

_identity_lock = threading.Lock()
# (path_str, mtime_ns, size) -> parsed dict. One entry — there is one file.
_identity_cache: tuple[tuple[str, int, int], dict] | None = None


def identity_report_path() -> Path:
    return data_dir() / IDENTITY_REPORT_FILE


def _load_identity_report() -> dict:
    """The last `eval.identity_check` run, or {}. NEVER raises — a fresh
    install has never run the check, and a corrupt file must not blank the
    whole Needs-attention panel over an unrelated batch job's output."""
    global _identity_cache
    path = identity_report_path()
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        # Missing is the ordinary case (nobody has run the check yet); any
        # other OSError (share offline, permissions) degrades the same way
        # — this route already has its own "couldn't read..." fallback
        # sentence above for the jobs half of the page, and duplicating
        # that machinery here for one more file would just be two places
        # that can say the same thing differently.
        return {}
    with _identity_lock:
        if _identity_cache is not None and _identity_cache[0] == stamp:
            return _identity_cache[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"expected an object, got {type(raw).__name__}")
    except (OSError, ValueError) as err:
        print(
            f"app.routes.admin: ignoring {path} ({err}) — identity findings "
            "are unavailable for this read.",
            file=sys.stderr,
        )
        return {}
    with _identity_lock:
        _identity_cache = (stamp, raw)
    return raw


def _identity_block() -> dict:
    """`{"findings": int, "report_path": str, "generated_at": str | None}`
    (spec I15's produced shape). `findings` counts the LIST, not any of the
    report's per-kind integer totals — those overlap (one document can
    trip more than one metric) and would double-count against the number
    of rows the panel actually renders."""
    report = _load_identity_report()
    findings = report.get("findings")
    path = identity_report_path()
    try:
        generated_at = datetime.fromtimestamp(
            path.stat().st_mtime, tz=timezone.utc
        ).isoformat()
    except OSError:
        generated_at = None
    return {
        "findings": len(findings) if isinstance(findings, list) else 0,
        "report_path": str(path),
        "generated_at": generated_at,
    }


# ---------------------------------------------------------------------------
# Needs attention (Plan B Task 7) — documents held out of search
# ---------------------------------------------------------------------------


@router.get("/api/admin/attention")
def get_attention(_settings: Settings = Depends(require_admin)) -> dict:
    """Documents the extraction ladder could not save, in one place.

    A `failed` job is either an ordinary crash (network hiccup, a locked
    file, a bad path, an embed/write/lock failure that happened AFTER a
    passing extraction) or a document that was HELD OUT because every rung
    of the ladder scored below `COVERAGE_FLOOR` — and only the second kind
    is an admin's problem to look at here, not the queue's.

    The discriminator is `job.held_out`, an explicit marker — NOT
    `job.extraction_attempts`, which was tried first and found wrong
    (Blocking 1 on this plan's final review): `ingest/worker.py` journals
    `extraction_attempts` after EVERY rung, including a WINNING one, so a
    job that passed extraction and then failed at embedding, writing, or
    losing the ingest-lock race also carries a non-empty
    `extraction_attempts` — reproduced live as a 94%-coverage document
    showing up here as "held out" with a raw traceback for its sentence.
    `job.held_out` is set in exactly one place — the branch in
    `ingest/worker.py::run_job` that decides every rung lost — and nowhere
    else, including the generic crash handler (`_fail`), and it is reset on
    retry (`ingest/jobs.py::advance`) so it cannot survive into a later,
    unrelated failure. An alternative considered and rejected: inferring
    the same fact route-side from "no attempt reached COVERAGE_FLOOR". It
    gives the wrong answer for a document whose WINNING rung had
    `coverage=None` (an unmeasurable source, accepted unconditionally —
    see `ExtractionOutcome.passed`) and which then crashed later: every
    attempt's coverage is `None`, so "no attempt reached the floor" reads
    as held-out when the ladder actually won. The explicit marker has no
    such blind spot.

    See ingest/worker.py's `_held_out_message` for why the job's own
    `error` sentence — not a string rebuilt here — is what ships to the
    reader: it is the one place that already knows to say what was
    MEASURED (how much text came out) and never that anything was
    "checked" or "verified", which this instrument cannot claim (see
    ingest/coverage.py).

    Ordered newest-failure-first, like the Notices panel this sits below —
    a glance at what just went wrong, not a chronicle.
    """
    error: str | None = None
    try:
        # 🔴 TWO READERS, ON PURPOSE. This route serves three panels and they
        # do NOT want the same jobs, which a clean merge on 2026-08-16 hid:
        # spec T13's archiving (this branch) and the swapped/degraded lists
        # (master) landed independently, git merged them without a conflict,
        # and both suites had been green on their own side. The fused
        # function shared ONE `load_active()` list, so the two new lists —
        # which are ONLY ever about jobs that reached `live` — could never
        # match a row. Eight tests caught it here; in production it would
        # have been a permanently empty panel with no error.
        #
        #   held_back  -> `failed`, which by T13 NEVER leaves the main
        #                 folder, so load_active() sees all of it and reads
        #                 no archive.
        #   swapped /
        #   degraded   -> `live`, which by T13 is ALWAYS archived, so these
        #                 need load_all().
        #
        # load_all() opens every archived job file (~7,200 today). That is
        # the O(n) cost T13 removed from the 3-second queue poll, and it is
        # accepted HERE because this is an admin page fetched on open, not a
        # poll. If this route ever becomes polled, index the archive rather
        # than narrowing these lists back to the main folder — narrowing
        # would silently reintroduce exactly this defect.
        from ingest.jobs import load_active, load_all

        jobs = load_active()
        finished = load_all()
    except Exception:  # noqa: BLE001 — an unreadable jobs dir must not 500 the page
        jobs = []
        finished = []
        # Distinguishable from "nothing needs attention" on purpose. An
        # empty `documents` list ALSO looks like this, and is the
        # overwhelmingly common, entirely fine case (absence-reads-as-fine
        # everywhere else in this system) — but a share that has gone away
        # is the one case where silence is the wrong answer, because it
        # reads identically to "the corpus is healthy" on the one screen an
        # admin would check to find out otherwise.
        error = "Couldn't read the list of documents needing attention right now."

    held_back = [job for job in jobs if job.state == "failed" and job.held_out]
    held_back.sort(key=lambda j: j.updated_at, reverse=True)

    documents = []
    for job in held_back:
        measured = [
            a["coverage"]
            for a in job.extraction_attempts
            if a.get("coverage") is not None
        ]
        documents.append({
            "job_id": job.job_id,
            "title": job.title,
            "message": job.error,
            "best_coverage": max(measured) if measured else None,
            "attempts": [
                {
                    "extractor": a.get("extractor"),
                    "coverage": a.get("coverage"),
                    # Both numbers, because they DISAGREE: this whole
                    # feature exists because one document read 49% on
                    # coverage and 30.63% bare on structure. `.get` rather
                    # than `[...]` — job files written before the field
                    # existed have no such key and must not 500 the page.
                    "unlabelled": a.get("unlabelled"),
                }
                for a in job.extraction_attempts
            ],
        })

    # Documents the ladder SAVED by changing extractor. Not an alert —
    # these are successes — but a swap re-mints every chunk_id and
    # replaces the document's text, and a change that size leaving no
    # trace is how a corpus becomes unexplainable a year later.
    #
    # A job kept on its FIRST rung is not listed: nothing changed, so
    # there is nothing to explain, and a list that fills up with ordinary
    # uploads teaches an admin to scroll past it.
    swapped = []
    for job in finished:
        attempts = job.extraction_attempts
        kept = job.kept_extractor
        if job.state != "live" or not kept or len(attempts) < 2:
            continue
        if attempts[0].get("extractor") == kept:
            continue
        swapped.append({
            "job_id": job.job_id,
            "title": job.title,
            "kept": kept,
            "attempts": [
                {
                    "extractor": a.get("extractor"),
                    "coverage": a.get("coverage"),
                    "unlabelled": a.get("unlabelled"),
                }
                for a in attempts
            ],
        })
    # `row["title"] or ""` -- a job file with a null title (this project has
    # already shipped the "one bad file costs the whole rail" defect once:
    # see IngestLock in STATUS.md) must not raise TypeError comparing None
    # to str and 500 this route, blanking both the swaps and held-out panels.
    swapped.sort(key=lambda row: row["title"] or "")

    # Documents that WERE saved and are searchable right now, whose kept
    # reading is still over the structure ceiling — the blind spot the two
    # lists above leave between them, and the one this whole feature exists
    # to close.
    #
    # `held_out` catches only documents the ladder REFUSED to write, and
    # `swapped` catches only documents whose extractor CHANGED. A document
    # that is bad and saved anyway satisfies neither, and there are two
    # ordinary ways to get there:
    #
    #   1. A single-rung source. A DOCX has exactly one extractor, so
    #      nothing can ever "change" and `len(attempts) < 2` drops it.
    #      There is no second reading to swap to and no coverage failure to
    #      hold it out — it is simply written, however it read.
    #   2. Every rung trips the ceiling. `choose_best` still has to return
    #      one, and it returns the LEAST bad; when that is rung 1,
    #      `attempts[0] == kept` drops it from `swapped` too.
    #
    # A swapped document can ALSO be over the ceiling, and then it appears
    # in both lists on purpose: "we changed how this was read" and "what we
    # kept is still poor" are different facts and an admin needs both. The
    # alternative — suppressing one — hides the more actionable of the two
    # behind the less.
    #
    # `unlabelled is None` means NOT MEASURED (fewer than
    # `MIN_JUDGED_CHUNKS` judgeable passages), never "measured and clean",
    # so an unmeasured reading is NOT listed: this panel accuses a document
    # of being bad and must never do that on absent evidence. The same rule
    # is what stops every job file written before this field existed from
    # arriving here as a false alarm on the day the feature ships.
    degraded = []
    for job in finished:
        kept = job.kept_extractor
        if job.state != "live" or not kept:
            continue
        # Last match, not first. Extractor names are unique per job today
        # (`_extract_and_chunk` keys its resume journal by name, so a second
        # entry for one rung cannot survive a save), but if that ever stops
        # being true the LATER record is the run that actually happened.
        kept_attempt = None
        for a in job.extraction_attempts:
            if a.get("extractor") == kept:
                kept_attempt = a
        if kept_attempt is None:
            continue
        unlabelled = kept_attempt.get("unlabelled")
        # `isinstance` rather than a bare `is None` check, because this is
        # the route's only ARITHMETIC on job-file data: everything else here
        # copies values straight through, so a corrupt field costs one blank
        # cell, while `"0.4" <= 0.20` raises TypeError and 500s the request
        # — blanking all three panels over one bad file. That exact shape
        # has shipped in this project before (IngestLock, and the
        # null-title sort two lists above).
        if not isinstance(unlabelled, (int, float)):
            continue
        if unlabelled <= MAX_UNLABELLED:
            continue
        degraded.append({
            "job_id": job.job_id,
            "title": job.title,
            "kept": kept,
            "unlabelled": unlabelled,
            "coverage": kept_attempt.get("coverage"),
        })
    # Worst first. Unlike the two lists above — which are chronological and
    # alphabetical because they are a queue and a record — this one is an
    # alert, and the document with the most unlabelled figures is the one
    # most worth opening. Sorting by title would bury it at random.
    degraded.sort(key=lambda row: row["unlabelled"], reverse=True)

    return {
        "documents": documents,
        "swapped": swapped,
        "degraded": degraded,
        "error": error,
        "identity": _identity_block(),
    }


# ---------------------------------------------------------------------------
# Backups + restore (S17)
# ---------------------------------------------------------------------------

MSG_INGEST_RUNNING = "An ingest is running — wait for it to finish, then try again."
MSG_CONFIRM_RESTORE = (
    'To restore this snapshot, confirm it by typing "restore". This replaces '
    "the whole corpus."
)


def _snapshot_created_at(name: str) -> str | None:
    """The UTC timestamp encoded in the snapshot's filename.

    Read from the NAME, not the file's mtime: store/backup.py sorts by
    name for exactly this reason (mtimes on an SMB share are the one piece
    of metadata most likely to be wrong), and the restore confirmation
    shows this date to a person about to overwrite their corpus.
    """
    stem = name[len(SNAPSHOT_PREFIX):-len(SNAPSHOT_SUFFIX)]
    try:
        # 15 characters — "20260731T120000". The name carries a trailing
        # "Z" (and sometimes a "-01" collision suffix) that strptime must
        # not be handed.
        return (
            datetime.strptime(stem[:15], "%Y%m%dT%H%M%S")
            .replace(tzinfo=timezone.utc)
            .isoformat()
        )
    except ValueError:
        # An unparseable name still lists — an admin who renamed a
        # snapshot by hand should not lose the ability to restore it.
        return None


@router.get("/api/admin/backups")
def get_backups(_settings: Settings = Depends(require_admin)) -> dict:
    snapshots = []
    for name in list_snapshots():
        try:
            size = (backups_dir() / name).stat().st_size
        except OSError:
            continue
        snapshots.append(
            {"name": name, "created_at": _snapshot_created_at(name), "bytes": size}
        )
    return {"snapshots": snapshots}


class RestoreBody(BaseModel):
    # A LITERAL string, not a boolean. A checkbox or a `true` can be sent
    # by a mis-click, a double-submit, or a stale tab replaying a request;
    # typing the word cannot.
    confirm: str = ""


@router.post("/api/admin/backups/{name}/restore")
def restore_backup(
    name: str, body: RestoreBody, _settings: Settings = Depends(require_admin)
) -> dict:
    if body.confirm != "restore":
        raise _bad_request(MSG_CONFIRM_RESTORE)

    if not (backups_dir() / Path(name).name).is_file():
        # Checked before taking the lock: blocking every ingest in the
        # office while we work out that the snapshot doesn't exist would
        # be a silly thing to do.
        raise HTTPException(status_code=404, detail=f"There is no snapshot named {name}.")

    lock = IngestLock()
    try:
        lock.acquire()
    except LockHeldError as err:
        # THE guard that matters. Extracting a zip over `lancedb/` while a
        # writer is mid-commit destroys the corpus rather than damaging one
        # document.
        raise HTTPException(status_code=409, detail=MSG_INGEST_RUNNING) from err

    try:
        # Snapshot the CURRENT corpus before replacing it, so a restore
        # started by mistake is itself reversible. Without this, the safe
        # button is the one that loses the corpus.
        snapshot()
        restore(name)
    except (FileNotFoundError, ValueError) as err:
        raise HTTPException(status_code=404, detail=str(err)) from err
    finally:
        # In a `finally`: a leaked lock blocks every future ingest in the
        # office, with no error naming the cause, until somebody deletes a
        # lockfile by hand.
        lock.release()

    # Ground truth 10: LanceDB table handles and the search provider are
    # resolved at startup, so the running process is still holding the
    # replaced corpus's handles. Saying "done" without saying "restart"
    # would produce an app that claims to be fixed and then serves errors.
    return {"restored": name, "restart_required": True}
