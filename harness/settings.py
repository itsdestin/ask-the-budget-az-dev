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
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from store.config import data_dir


def fold(user: str) -> str:
    """The U0 comparison form. A private copy of `users.whoami.fold`, NOT an
    import — this module is on the harness import allowlist (Invariant 7)
    and `users/registry.py` writes files, so admitting the package would
    admit that too. `tests/test_users_whoami.py` pins this line to the same
    expression so the two cannot drift.

    PUBLIC (not `_fold`) because `harness/ledger.py::month_total` needs the
    same fold for the spend total the cap is compared against — found by
    the 2026-08-26 final review: `month_total` matched rows by an EXACT
    username, so a person recorded under two spellings (`dmoss`/`DMOSS`)
    could spend up to their cap under each spelling, twice, while the
    People panel's own total (which sums under the fold) showed the
    correct, larger number. `ledger.py` imports this function rather than
    writing its own `.casefold(` — `tests/test_users_whoami.py`'s source
    guard allows `.casefold(` only in this file and `users/whoami.py`."""
    return user.strip().casefold()


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

    # --- custom-endpoint pricing --------------------------------------
    # Dollars per million tokens, as every model vendor quotes them.
    #
    # WHY these exist (2026-07-31, deviation from S15 as written): S15
    # accepted that a custom endpoint reports no cost, so those rows went
    # into the ledger with `cost_usd: None`. That had two consequences
    # nobody wanted — every total had to be rendered "at least $X (N calls
    # of unknown cost)", and `check_limit` switched spend limits OFF
    # entirely, so an office on a custom endpoint had no cap at all.
    #
    # An admin who is standing up their own endpoint knows what it costs,
    # so the app now ASKS (the admin page refuses to save a custom
    # endpoint without both figures) and computes each call's cost from
    # the token counts the provider does report. The result is an
    # ESTIMATE from admin-entered prices rather than the provider's own
    # exact figure — the UI says so — but it is a real number, it can be
    # summed, and it can be enforced against a limit.
    prompt_usd_per_m: float | None = None
    completion_usd_per_m: float | None = None

    @property
    def has_pricing(self) -> bool:
        """Can a per-call cost be worked out for this provider?

        True for OpenRouter (it reports exact cost per call) and for a
        custom endpoint with both prices filled in. False only for a
        custom endpoint configured by hand-editing settings.json — the
        admin page cannot produce that state.
        """
        if self.provider != "custom":
            return True
        return (
            self.prompt_usd_per_m is not None
            and self.completion_usd_per_m is not None
        )

    def estimate_cost(self, tokens_in: int, tokens_out: int) -> float | None:
        """Dollars for one call, from the admin-entered per-million rates.

        None when there is nothing to compute from — the caller then
        records an unknown cost exactly as it always did, so a
        hand-edited config degrades instead of crashing.
        """
        if self.prompt_usd_per_m is None or self.completion_usd_per_m is None:
            return None
        return (
            (max(tokens_in, 0) / 1_000_000) * self.prompt_usd_per_m
            + (max(tokens_out, 0) / 1_000_000) * self.completion_usd_per_m
        )


@dataclass(frozen=True)
class TierConfig:
    """One analyst-facing tier's admin-assigned model (S16).

    Deliberately just a model id and an on/off switch. The effort-budget
    half of a tier (step caps, deep_dive permission) is NOT
    admin-configurable — it's a hardcoded constant consumed by
    harness/tools.py + harness/session.py — because letting an admin
    accidentally set Standard's step cap to 1 would silently break every
    quick lookup with no error surface. Only the "which model" knob lives
    here.

    `enabled` exists so an admin can turn one answer mode off WITHOUT
    losing which model they had chosen for it (2026-07-31). Before this
    the only way to disable Deep Research was to blank its model, which
    threw away the setting and made re-enabling a re-decision.
    """

    model: str = ""
    # None means "never explicitly set", which resolves to `bool(model)` —
    # see `is_enabled`. A plain False default would report every
    # programmatically-built TierConfig as switched off, and a plain True
    # would show a fresh install's answer modes as on with nothing behind
    # them.
    enabled: bool | None = None

    @property
    def is_enabled(self) -> bool:
        """Is this answer mode switched on?

        Unset resolves to "on if a model is assigned" — which is exactly
        what the app meant before the switch existed, so an upgrade
        changes nothing, and a fresh install (no model yet) shows the
        mode off until an admin turns it on.
        """
        if self.enabled is None:
            return bool(self.model)
        return self.enabled


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

    # The master switch for AI Mode (2026-07-31). Distinct from "is a key
    # configured": an admin turning AI Mode off for a week — a budget
    # freeze, a provider outage, an office-wide pause — must not have to
    # delete the key and re-enter it afterwards.
    #
    # None means "never explicitly set", which resolves to ON: before this
    # field existed AI Mode was never *switched* off, it was only
    # unconfigured, so that is the faithful reading of an older
    # settings.json. An install with no key still reports "no API key
    # configured" rather than "switched off" — see `ai_available`.
    ai_enabled: bool | None = None

    @property
    def ai_is_enabled(self) -> bool:
        return True if self.ai_enabled is None else self.ai_enabled

    # --- S19 per-user spend limits -----------------------------------
    # None means "no cap" at every level below.
    default_monthly_limit_usd: float | None = None
    user_limits: dict[str, float] = field(default_factory=dict)
    exempt_users: tuple[str, ...] = ()

    # People the admin has taken out of every dropdown and the People table
    # (spec U7). HERE, not in the person's roster file: hiding is something
    # the ADMIN decides about someone ELSE, and a roster file is written only
    # by its own user's machine — an admin's machine writing it too was a
    # two-writer race with no lock in which a daily touch could silently
    # un-hide someone. Their ledger rows are untouched and still count.
    hidden_users: tuple[str, ...] = ()

    def limit_for(self, user: str) -> float | None:
        """Resolve `user`'s monthly dollar cap. None means unlimited.

        Resolution order: exempt list wins outright (a director on the
        exempt list should never be blocked even if an admin also typos
        a per-user override for them) > per-user override > org default.

        Matching is EXACT FIRST, THEN CASE-INSENSITIVE (spec U0, 2026-08-25).
        This used to be exact only, on the grounds that folding would
        silently merge two rows an admin TYPED. Every row now comes from a
        dropdown of observed usernames, so two rows for one person cannot
        be created — and the thing exact matching caused was worse:
        `%USERNAME%` reflects how the person typed their name at logon, so
        `DMOSS` today and `dmoss` tomorrow silently got two different limits.
        Where a legacy file holds both spellings the exact one still wins
        and the People panel shows the collision on that row.
        """
        if user in self.exempt_users:
            return None
        if user in self.user_limits:
            return self.user_limits[user]
        folded = fold(user)
        if folded:
            if any(fold(u) == folded for u in self.exempt_users):
                return None
            for key, limit in self.user_limits.items():
                if fold(key) == folded:
                    return limit
        return self.default_monthly_limit_usd

    def is_exempt(self, user: str) -> bool:
        """On the no-limit list, under the same rule `limit_for` uses."""
        if user in self.exempt_users:
            return True
        folded = fold(user)
        return bool(folded) and any(fold(u) == folded for u in self.exempt_users)

    def is_hidden(self, user: str) -> bool:
        """Hidden by the admin (spec U7), under the same rule."""
        if user in self.hidden_users:
            return True
        folded = fold(user)
        return bool(folded) and any(fold(u) == folded for u in self.hidden_users)


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

    Four failure reasons, exact strings (UI code and tests match them
    verbatim), checked in the order an admin sets things up:
      - "AI Mode is switched off — ask the admin"  — the master switch
      - "no API key configured"                    — provider.api_key empty
      - "this answer mode is switched off — ask the admin" — the master
        switch is on and a key is present, but THIS mode is off
      - "no model configured — ask the admin"      — mode on, no model yet

    ADD NEW FAILURE MODES HERE, never at a call site. Every surface that
    explains why AI Mode is unavailable reads these strings, so a sentence
    invented elsewhere is a sentence that will eventually contradict this
    one.
    """
    if not settings.provider.api_key:
        return False, "no API key configured"
    # The key check comes FIRST on purpose. An install with no key has
    # nothing to switch on, and telling that admin "AI Mode is switched
    # off" would send them hunting for a toggle when what they need is a
    # key. Once a key exists, the master switch is the meaningful answer.
    if not settings.ai_is_enabled:
        return False, "AI Mode is switched off — ask the admin"
    tier_config = settings.tiers.get(tier)
    # NO MODEL BEATS THE SWITCH. A mode with nothing assigned is off
    # either way, and "this answer mode is switched off" would send an
    # admin looking for a toggle when the thing they have to do is pick a
    # model. Checking the model first also keeps this function insensitive
    # to whether `enabled` was stored as an explicit false or left unset —
    # saving resolves the sentinel, so those two must mean the same thing
    # here or a save/reload would change the message.
    if tier_config is None or not tier_config.model:
        return False, "no model configured — ask the admin"
    if not tier_config.is_enabled:
        return False, "this answer mode is switched off — ask the admin"
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
        prompt_usd_per_m=_float_or_none(raw, "prompt_usd_per_m"),
        completion_usd_per_m=_float_or_none(raw, "completion_usd_per_m"),
    )


def _float_or_none(d: dict[str, Any], key: str) -> float | None:
    """A price, or None when it is absent or unusable.

    Same tolerance as every other reader here: a hand-edited garbage
    value reads as "not set" rather than crashing the load. A negative
    price is also treated as unset — it cannot be what anyone meant, and
    letting it through would produce negative spend totals.
    """
    value = d.get(key)
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return None if number < 0 else number


def _tier_from_dict(d: dict[str, Any]) -> TierConfig:
    enabled = d.get("enabled")
    # A file written before per-mode switches existed has no `enabled`
    # key; None carries that through to `TierConfig.is_enabled`, which
    # resolves it to "on if a model is assigned" — what the app meant
    # before the switch existed.
    return TierConfig(
        model=_str_or(d, "model", ""),
        enabled=enabled if isinstance(enabled, bool) else None,
    )


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

    hidden_raw = raw.get("hidden_users")
    hidden_users = tuple(str(u) for u in hidden_raw) if isinstance(hidden_raw, list) else ()

    ai_enabled = raw.get("ai_enabled")
    return Settings(
        provider=_provider_from_dict(raw.get("provider")),
        tiers=_tiers_from_dict(raw.get("tiers")),
        admin_username=_str_or(raw, "admin_username", ""),
        # Absent stays None, which `ai_is_enabled` resolves to ON — see
        # the field's comment. An older file simply never had a switch.
        ai_enabled=ai_enabled if isinstance(ai_enabled, bool) else None,
        default_monthly_limit_usd=default_limit,
        user_limits=user_limits,
        exempt_users=exempt_users,
        hidden_users=hidden_users,
    )


def _settings_to_dict(settings: Settings) -> dict[str, Any]:
    return {
        "provider": {
            "base_url": settings.provider.base_url,
            "api_key": settings.provider.api_key,
            "provider": settings.provider.provider,
            "prompt_usd_per_m": settings.provider.prompt_usd_per_m,
            "completion_usd_per_m": settings.provider.completion_usd_per_m,
        },
        # Resolved values, not the raw sentinels: once this file has been
        # written by the admin page, "unset" is no longer a state anyone
        # needs — and a `null` in settings.json would read as broken to an
        # admin opening it in Notepad.
        "tiers": {
            name: {"model": cfg.model, "enabled": cfg.is_enabled}
            for name, cfg in settings.tiers.items()
        },
        "admin_username": settings.admin_username,
        "ai_enabled": settings.ai_is_enabled,
        "default_monthly_limit_usd": settings.default_monthly_limit_usd,
        "user_limits": dict(settings.user_limits),
        "exempt_users": list(settings.exempt_users),
        "hidden_users": list(settings.hidden_users),
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


def _preserve_if_corrupt(target: Path) -> None:
    """Copy an UNPARSEABLE settings.json aside before it gets overwritten.

    THE FAILURE THIS PREVENTS (Plan 5 Task 13). `load_settings` fails open:
    a corrupt file degrades to `Settings()`, which makes admin claimable,
    which is right — a file nobody can parse must not lock out the only
    person who could fix it. But the very next thing that happens is
    somebody claiming admin and saving, and that save would replace the
    corrupt bytes with a clean default file.

    Those bytes are usually the last surviving copy of the OpenRouter API
    key. A hand-edit that breaks the JSON does not remove the key from it,
    and `settings.json.corrupt-<timestamp>` can be opened in Notepad to
    read it back out. Without this, the app's own fail-open behaviour eats
    the evidence and the key is gone.

    Only fires on a file that is present and does NOT parse — a healthy
    save must not litter the share with copies. Never raises: this runs
    inside the save path, and failing to make a backup copy is not a
    reason to fail the save the admin actually asked for.
    """
    try:
        raw = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return  # first write on a fresh install — nothing to preserve
    except OSError:
        return
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return  # healthy; nothing to do
    except ValueError:
        pass

    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    # The microseconds matter: two corruptions in the same second must not
    # overwrite each other's copy, and the OLDER one holds the key more
    # likely to still be valid.
    preserved = target.with_name(f"{target.name}.corrupt-{stamp}")
    try:
        preserved.write_text(raw, encoding="utf-8")
        print(
            f"harness.settings: {target} was unreadable and is being replaced. "
            f"The previous contents are preserved at {preserved} — if AI Mode "
            "stops working, the old API key can usually be read out of it.",
            file=sys.stderr,
        )
    except OSError as err:
        print(
            f"harness.settings: {target} is corrupt and could NOT be preserved "
            f"({err}). It is about to be overwritten; any API key in it will "
            "be lost.",
            file=sys.stderr,
        )


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
    _preserve_if_corrupt(target)
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
