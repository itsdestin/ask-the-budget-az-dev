"""The one shared settings.json (Plan 4 Task 1, spec S13/S15/S16/S19).

Lives at `<data_dir>/settings.json`, next to the LanceDB corpus, so every
process that needs it (this harness, the ledger, and — in Plan 5 — an
admin page that writes it) reads/writes the same file over the office
network share. It is plain, unencrypted JSON: accepted per spec S11
(the OpenRouter key is spend-capped at the provider, not treated as a
high-value secret worth key-management machinery).

Nothing in this module talks to a network or a model provider — it only
loads/saves the config tree and answers "is AI Mode usable right now"
and "what's this user's spend limit" from data already in hand.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from store.config import data_dir

SETTINGS_FILE = "settings.json"

# S13: OpenRouter is the recommended, admin-default provider. S15's
# "custom endpoint" escape hatch is the same base_url/api_key/provider
# triple pointed somewhere else — the wire protocol (OpenAI-compatible
# chat completions) doesn't change, so the harness needs no branching
# beyond which triple it was handed.
_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_PROVIDER = "openrouter"


def settings_path() -> Path:
    """Path to the shared settings.json (may not exist yet).

    One definition, mirroring store.config.documents_path()'s shape: the
    harness (and later the admin page) both import this instead of each
    hardcoding the filename, so a rename only happens in one place.
    """
    return data_dir() / SETTINGS_FILE


@dataclass(frozen=True)
class ProviderConfig:
    """Where chat-completion calls go. Frozen so a loaded Settings tree
    can be handed to a request-building function without it accidentally
    mutating shared config mid-request."""

    base_url: str = _DEFAULT_BASE_URL
    api_key: str = ""
    provider: str = _DEFAULT_PROVIDER  # "openrouter" | "custom" (S15)


@dataclass(frozen=True)
class TierConfig:
    """One analyst-facing tier's admin-assigned model (S16).

    Deliberately just a model id. The effort-budget half of a tier (step
    caps, deep_dive permission) is NOT admin-configurable — it's a
    hardcoded constant consumed by harness/tools.py + harness/session.py
    (Tasks 3/6) — because letting an admin accidentally set Standard's
    step cap to 1 would silently break every quick lookup with no error
    surface. Only the "which model" knob lives here.
    """

    model: str = ""


_STANDARD = "standard"
_DEEP_RESEARCH = "deep_research"


def _default_tiers() -> dict[str, TierConfig]:
    return {_STANDARD: TierConfig(), _DEEP_RESEARCH: TierConfig()}


@dataclass(frozen=True)
class Settings:
    """The full shared config tree.

    Frozen at the top level (fields can't be reassigned), but `tiers`
    and `user_limits` are plain dicts rather than e.g. frozen mapping
    types — this file is small, hand-editable, and rewritten wholesale
    via save_settings() rather than mutated in place, so the extra
    immutability machinery would buy nothing but ceremony. One
    consequence worth knowing: the `tiers`/`user_limits` dict fields make
    `Settings` itself unhashable despite `frozen=True` — `frozen` here
    buys attribute-reassignment safety, not hashability or deep
    immutability, so don't put a `Settings` in a set or use one as a dict
    key. (`ProviderConfig` and `TierConfig`, with only str fields, ARE
    hashable — it's specifically the container that isn't.)
    """

    provider: ProviderConfig = field(default_factory=ProviderConfig)
    tiers: dict[str, TierConfig] = field(default_factory=_default_tiers)
    admin_username: str = ""

    # --- S19 per-user spend limits -----------------------------------
    # None means "no cap" at every level below.
    default_monthly_limit_usd: float | None = None
    user_limits: dict[str, float] = field(default_factory=dict)
    exempt_users: tuple[str, ...] = ()

    def limit_for(self, user: str) -> float | None:
        """Resolve `user`'s monthly dollar cap. None means unlimited.

        Resolution order: exempt list wins outright (a director on the
        exempt list should never be blocked even if an admin also typos
        a per-user override for them) > per-user override > org default.

        Username matching is an EXACT string comparison — no case
        folding. Windows usernames are case-preserving-but-insensitive
        at the OS level, but folding here would mean "Analyst1" and
        "analyst1" silently share one limit even though the admin typed
        two distinct entries. Silent merging of what looks like two
        different config rows is worse than requiring the admin (Plan 5
        UI) to match the OS's actual username casing exactly.
        """
        if user in self.exempt_users:
            return None
        if user in self.user_limits:
            return self.user_limits[user]
        return self.default_monthly_limit_usd


def ai_available(settings: Settings, tier: str) -> tuple[bool, str | None]:
    """Can `tier` place a call right now? (True, None) or (False, reason).

    Module function rather than a Settings method, and tier is a
    REQUIRED argument rather than "check any tier" — because later
    callers (harness/session.py, Task 6) always have a specific
    conversation's tier in hand and need to gate THAT tier, not answer
    "is AI Mode on at all" as one undifferentiated switch. An admin can
    legitimately wire up Standard while Deep Research sits unconfigured;
    collapsing that into a single boolean would either report Standard
    unavailable (wrong) or Deep Research available (worse — a request
    would reach a call site with no model id). A caller that genuinely
    wants "is anything usable" loops over settings.tiers.keys() and ORs
    the results; that policy belongs at the call site, not baked in here.

    Two failure reasons, exact strings pinned by the plan (later UI code
    and tests match on them verbatim):
      - "no API key configured"            — provider.api_key is empty
      - "no model configured — ask the admin" — key present, but this
        tier's model id is empty (an admin turned on AI Mode but hasn't
        finished assigning a model to every tier yet)
    """
    if not settings.provider.api_key:
        return False, "no API key configured"
    tier_config = settings.tiers.get(tier)
    if tier_config is None or not tier_config.model:
        return False, "no model configured — ask the admin"
    return True, None


# ---------------------------------------------------------------------------
# JSON <-> dataclass conversion
# ---------------------------------------------------------------------------
# Hand-rolled rather than dataclasses.asdict()/a generic loader: this file
# will be hand-edited and, later, written by an admin page that may lag
# behind this module's field set. Every _*_from_dict() below reads known
# keys with .get(...) defaults and silently ignores anything else, so an
# extra or renamed key never crashes a load — it's just inert until this
# code is updated to notice it.


def _str_or(d: dict[str, Any], key: str, default: str) -> str:
    """d.get(key, default), but ALSO falling back to default on an explicit
    JSON null. Plain dict.get only substitutes its default when the key is
    ABSENT — a present `"key": null` (a natural way to hand-edit-clear a
    field, e.g. an admin "unsetting" api_key) sails through as `None`, and
    `str(None)` is the literal three-character string "None". For api_key
    specifically that string is truthy, so `ai_available()`'s `if not
    settings.provider.api_key` check would not fire and the harness would
    go on to send "None" as a bearer token instead of refusing honestly.
    """
    value = d.get(key, default)
    return default if value is None else str(value)


def _provider_from_dict(raw: Any) -> ProviderConfig:
    # WHY the isinstance guard here (unlike a bare str(d.get(...)) call):
    # `Settings.provider` and `ProviderConfig.provider` share a field name
    # at two nesting levels, so an admin hand-editing "the provider" quite
    # naturally writes `"provider": "custom"` at the TOP level — the wrong
    # nesting, but valid JSON. Without this guard that shape reaches
    # dict-only code (`.get()` on a str) and raises, which is exactly the
    # "never crash AI availability over a config typo" contract this
    # module exists to uphold. Mirrors _tiers_from_dict's guard below.
    if not isinstance(raw, dict):
        return ProviderConfig()
    return ProviderConfig(
        base_url=_str_or(raw, "base_url", _DEFAULT_BASE_URL),
        api_key=_str_or(raw, "api_key", ""),
        provider=_str_or(raw, "provider", _DEFAULT_PROVIDER),
    )


def _tier_from_dict(d: dict[str, Any]) -> TierConfig:
    return TierConfig(model=_str_or(d, "model", ""))


def _tiers_from_dict(raw: Any) -> dict[str, TierConfig]:
    tiers = _default_tiers()
    if isinstance(raw, dict):
        for name, cfg in raw.items():
            if isinstance(cfg, dict):
                tiers[str(name)] = _tier_from_dict(cfg)
    return tiers


def _settings_from_dict(raw: dict[str, Any]) -> Settings:
    default_limit = raw.get("default_monthly_limit_usd")
    if default_limit is not None:
        try:
            default_limit = float(default_limit)
        except (TypeError, ValueError):
            default_limit = None  # malformed value -> treat as unset, not a crash

    user_limits_raw = raw.get("user_limits")
    user_limits: dict[str, float] = {}
    if isinstance(user_limits_raw, dict):
        for user, limit in user_limits_raw.items():
            try:
                user_limits[str(user)] = float(limit)
            except (TypeError, ValueError):
                continue  # drop one bad row rather than discarding the whole file

    exempt_raw = raw.get("exempt_users")
    exempt_users = tuple(str(u) for u in exempt_raw) if isinstance(exempt_raw, list) else ()

    return Settings(
        provider=_provider_from_dict(raw.get("provider")),
        tiers=_tiers_from_dict(raw.get("tiers")),
        admin_username=_str_or(raw, "admin_username", ""),
        default_monthly_limit_usd=default_limit,
        user_limits=user_limits,
        exempt_users=exempt_users,
    )


def _settings_to_dict(settings: Settings) -> dict[str, Any]:
    return {
        "provider": {
            "base_url": settings.provider.base_url,
            "api_key": settings.provider.api_key,
            "provider": settings.provider.provider,
        },
        "tiers": {name: {"model": cfg.model} for name, cfg in settings.tiers.items()},
        "admin_username": settings.admin_username,
        "default_monthly_limit_usd": settings.default_monthly_limit_usd,
        "user_limits": dict(settings.user_limits),
        "exempt_users": list(settings.exempt_users),
    }


# ---------------------------------------------------------------------------
# Load / save, mtime-cached
# ---------------------------------------------------------------------------
# Same shape as retrieval/api.py's _document_metadata(): cache on a
# (path, mtime, size) stamp so a settings.json rewritten on the share —
# by a future admin page, or by hand — is picked up by every already-running
# harness process without a restart, while a call that finds the stamp
# unchanged skips the JSON parse entirely.

_settings_lock = threading.Lock()
_settings_cache: Settings = Settings()
_settings_stamp: tuple[str, float, int] | None = None


def reset_settings_cache() -> None:
    """Force the next load_settings() to re-stat and re-parse.

    Two callers, both legitimate. (1) Tests, per the original reason
    below. (2) Plan 5's admin route, immediately after `save_settings` —
    it must then re-read from disk to build its response, and the cache
    stamp is `(path, mtime, size)`, so a write that lands in the same
    coarse mtime tick AND happens to produce the same file size would
    otherwise serve the admin their PREVIOUS settings as confirmation of
    the save they just made. Dropping the cache after a write we know
    happened is cheaper than making the stamp finer-grained and hoping.

    _document_metadata() in retrieval/api.py never needed a reset hook
    because its tests always repoint JLBC_DATA_DIR at a fresh tmp_path
    per test, so the cached stamp can never collide with the new one.
    This module's own tests do that too (see the autouse fixture in
    tests/test_harness_settings.py) but ALSO routinely call
    save_settings() then load_settings() against the SAME path within a
    single test — a sequence where a coarse OS mtime clock could, in
    principle, report a stamp that looks unchanged. Resetting explicitly
    removes that race instead of relying on save+load always landing in
    different clock ticks.
    """
    global _settings_cache, _settings_stamp
    with _settings_lock:
        _settings_cache, _settings_stamp = Settings(), None


def load_settings(path: Path | None = None) -> Settings:
    """Parsed settings.json, cached until the file changes on disk.

    A missing file returns Settings() (all defaults) — normal on a fresh
    checkout or a dev machine, not an error. A present-but-corrupt file
    (a bad hand-edit, or a save that landed mid-write despite the atomic
    rename below — e.g. truncated by something outside this module)
    likewise falls back to Settings() rather than raising: letting a
    single malformed config file take down every AI-availability check
    across the app would be a worse failure than degrading. The
    degraded state is indistinguishable from "never configured" to the
    caller — ai_available() reports "no API key configured" either way
    — but a stderr line names the real parse error so whoever broke the
    file (or is debugging why AI Mode "just stopped working") can find it
    fast instead of guessing.
    """
    global _settings_cache, _settings_stamp
    target = path or settings_path()
    try:
        st = target.stat()
        stamp: tuple[str, float, int] | None = (str(target), st.st_mtime, st.st_size)
    except OSError:
        stamp = None  # absent or unreadable -> defaults

    with _settings_lock:
        if stamp == _settings_stamp:
            return _settings_cache
        if stamp is None:
            _settings_cache, _settings_stamp = Settings(), None
            return _settings_cache
        try:
            raw = json.loads(target.read_text(encoding="utf-8"))
            if not isinstance(raw, dict):
                raise ValueError(f"expected a JSON object, got {type(raw).__name__}")
            settings = _settings_from_dict(raw)
        except (OSError, ValueError) as err:
            print(
                f"harness.settings: {target} is unreadable/corrupt ({err}) — "
                "falling back to defaults. AI Mode will report "
                "'no API key configured' until this file is fixed.",
                file=sys.stderr,
            )
            settings = Settings()
        _settings_cache, _settings_stamp = settings, stamp
        return _settings_cache


def save_settings(settings: Settings, path: Path | None = None) -> None:
    """Write settings.json via tmp-file + os.replace, to reduce (not
    eliminate) the window where a concurrent reader sees a partial file.

    This file lives on an office SMB share and is read by every harness
    process plus, later, an admin page that writes it live while other
    people may be mid-chat. A plain open()+write() leaves an obvious
    window where a concurrent reader sees a truncated/partial JSON
    document and every load_settings() in that window degrades AI Mode
    office-wide — tmp-file + os.replace() closes that specific hole. On
    a genuinely POSIX or NTFS-local filesystem os.replace() is a single
    atomic rename. On an SMB share, whether the rename lands atomically
    depends on the server-side filesystem and the SMB dialect/client in
    play — this module has no way to verify that for whatever share it
    ends up on, so treat this as "much safer than a direct write," not
    as a provable cross-network guarantee.
    """
    target = path or settings_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(target.parent), prefix=".settings-", suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(_settings_to_dict(settings), f, indent=2)
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
