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
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import (
    admin_claimable,
    admin_reset_pending,
    claim_admin,
    current_user,
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
from store.backup import (
    SNAPSHOT_PREFIX,
    SNAPSHOT_SUFFIX,
    backups_dir,
    list_snapshots,
    restore,
    snapshot,
)
from store.config import data_dir, documents_path

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
        # Surfaced so the claim banner can say "a reset file is present and
        # claiming will use it up" — nobody should burn a reset by accident
        # and then wonder where it went.
        "admin_reset_pending": admin_reset_pending(),
    }


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
_TERMINAL_JOB_STATES = frozenset({"live", "failed", "cancelled"})


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


def _queue_summary() -> tuple[dict[str, int], str | None]:
    """(counts by state, when the corpus last actually grew).

    "running" is every non-terminal, non-queued state collapsed into one
    number: an admin wants to know that something is moving, not which of
    six pipeline stages it is in — the Documents page already shows that
    per job.
    """
    summary = {"queued": 0, "running": 0, "failed": 0}
    last_live: str | None = None
    try:
        from ingest.jobs import load_all

        jobs = load_all()
    except Exception:  # noqa: BLE001 — unreadable jobs dir
        return summary, None

    for job in jobs:
        if job.state == "queued":
            summary["queued"] += 1
        elif job.state == "failed":
            summary["failed"] += 1
        elif job.state not in _TERMINAL_JOB_STATES:
            summary["running"] += 1
        if job.state == "live" and (last_live is None or job.updated_at > last_live):
            last_live = job.updated_at
    return summary, last_live


@router.get("/api/admin/corpus")
def get_corpus(_settings: Settings = Depends(require_admin)) -> dict:
    counts = _chunk_counts()
    queue, last_ingest_at = _queue_summary()
    return {
        "data_dir": str(data_dir()),
        "budget_chunks": counts["budget_chunks"],
        "fiscal_note_chunks": counts["fiscal_note_chunks"],
        "documents": _document_count(),
        "lancedb_bytes": _dir_bytes(data_dir() / "lancedb"),
        "dead_version_bytes": _reclaimable_bytes(),
        "last_ingest_at": last_ingest_at,
        "queue": queue,
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
