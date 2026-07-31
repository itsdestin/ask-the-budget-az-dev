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

from app.identity import admin_claimable, current_user, is_admin
from harness.catalog import fetch_catalog
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


def _chunk_counts() -> dict[str, int]:
    """Row counts per corpus table, zero on anything unopenable.

    A missing or unreadable table reads as 0 — the same number a genuinely
    empty corpus produces. That ambiguity is deliberate and acceptable
    here because the health ladder (Task 11) is what distinguishes "empty"
    from "broken", with a sentence for each; this endpoint's job is the
    numbers.
    """
    counts = {"budget_chunks": 0, "fiscal_note_chunks": 0}
    try:
        from store.chunk_store import ChunkStore

        store = ChunkStore()
        for name in counts:
            try:
                counts[name] = store.count(name)
            except Exception:  # noqa: BLE001 — missing table, bad schema…
                continue
    except Exception:  # noqa: BLE001 — LanceDB itself unavailable
        pass
    return counts


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


def _document_count() -> int:
    try:
        raw = json.loads(documents_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return 0
    except (OSError, ValueError) as err:
        # This is the page an admin opens BECAUSE something is wrong.
        print(
            f"app.routes.admin: couldn't read {documents_path()} ({err}) — "
            "reporting 0 documents.",
            file=sys.stderr,
        )
        return 0
    return len(raw) if isinstance(raw, dict) else 0


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
