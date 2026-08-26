# Central User Roster Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Record every person who opens the app in a shared roster, show the admin real names and spend in a People panel, and replace every typed-username box with a dropdown — with ONE rule deciding when two usernames are the same person.

**Architecture:** A new leaf package `users/` owns "who is this process running as" (`whoami.py`) and the roster of one JSON file per person under `<data_dir>/users/` (`registry.py`). Roster files are OBSERVATIONS written only by the person's own machine; every admin DECISION about a person (limit, exempt, hidden) stays in `settings.json`. `GET /api/me` touches the roster in a background task; `GET /api/admin/users` joins roster + ledger + settings into one payload; a new `PeoplePanel.tsx` renders it.

**Tech Stack:** Python 3.12 / FastAPI / pytest; React 18 + TypeScript / vitest; plain JSON files on the shared drive.

**Spec:** `docs/superpowers/specs/2026-08-25-central-user-roster-design.md` (U0–U16, G-U0 passed 2026-08-25). **Approved mockup:** `docs/superpowers/specs/assets/2026-08-25-user-roster-mockup/people-panel.html` — the People panel, the slimmed Spending-limits card, and the hand-over picker MUST match it.

## Global Constraints

- **U0:** `same_person(a, b) ⇔ a.strip().casefold() == b.strip().casefold()` (and non-empty). Used by `limit_for`, `is_admin`, the roster key, the ledger join, and "does this stored key belong to a roster person". A source-level guard pins that `.casefold(` appears only in `users/whoami.py` and `harness/settings.py`, and `getpass.getuser(` only in `users/whoami.py`.
- **U1/U7:** A roster file is written ONLY by its own user's machine. No route writes another person's file. `hidden_users` lives in `settings.json`.
- **U4/U6:** `/api/me` never waits on the share for the roster: the touch (read + write) is a `BackgroundTask`; the `display_name()` roster read is one known file, cached on `(mtime_ns, size)`, and ANY failure falls through to the local name with no exception.
- **Invariant 7:** nothing under `harness/` imports `users`. `harness/settings.py`'s fold is a self-contained three-line `_fold`.
- **No `adm-link` anywhere.** Every action is a pill (`adm-btn`, `adm-btn-quiet`, new `adm-btn-sm`). Destin's standing rule, 2026-08-25.
- **No jargon in admin copy:** the words `endpoint`, `corpus`, `chunk`, `prompt caching`, `catalog`, `tier` must not appear in People-panel text (existing guard in `webapp/src/pages/Admin.test.tsx:1159`).
- **Tests never open a real LanceDB or load ONNX weights.** Route tests use `create_app(provider=StubSearchProvider())` and `TestClient`.
- **Every non-trivial code edit carries a WHY comment** recording the evidence, per CLAUDE.md.
- **Worktree:** `~/ask-the-budget-az-worktrees/user-roster/`, branch `user-roster`, `.venv` symlinked from the main repo.
- **Commit message trailer** on every commit: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>` and `Claude-Session: https://claude.ai/code/session_01HszUXDRHu5CDDvZSrmDDXA`.

---

## File map

| File | Responsibility |
|---|---|
| `users/__init__.py` (new) | empty package marker |
| `users/whoami.py` (new) | `current_user()`, `fold()`, `same_person()`, `roster_key()` — stdlib only |
| `users/registry.py` (new) | `Person`, `RosterUnavailable`, `users_dir()`, `read_person()`, `typed_name()`, `list_people()`, `touch()`, `set_typed_name()` |
| `app/identity.py` | re-export `current_user`; `is_admin` folds; `display_name()` reads the roster first |
| `ingest/jobs.py`, `ingest/claim.py`, `ingest/lock.py` | delete private `_current_user`; use `users.whoami.current_user() or "unknown"` |
| `harness/settings.py` | `hidden_users` field; `_fold`; `limit_for` + new `is_exempt` fold |
| `harness/ledger.py:688` | `settings.is_exempt(user)` instead of `user in settings.exempt_users` |
| `app/routes/admin.py` | `/api/me` background touch; PUT display-name writes both; `hidden_users` in settings I/O; `GET /api/admin/users` |
| `webapp/src/api.ts` | `hidden_users` on settings types; `AdminUsers`, `PersonRow`, `adminUsers()` |
| `webapp/src/admin/changes.ts` | "who is hidden" change description |
| `webapp/src/admin/PeoplePanel.tsx` (new) | the table, sort, limit dropdown, Hide/Show |
| `webapp/src/admin/ProviderPanel.tsx` | per-person limit rows + exempt box DELETED; pointer line |
| `webapp/src/admin/AdvancedPanel.tsx` | typed box → picker with three states |
| `webapp/src/pages/Admin.tsx` | fetch `adminUsers`; mount `PeoplePanel` above Spending |
| `webapp/src/styles/app.css` | `.adm-btn-sm`, `.adm-people-*`; `.adm-link` deleted |
| `tests/test_users_whoami.py`, `tests/test_users_registry.py`, `tests/test_admin_users_route.py` (new) | pytest |
| `webapp/src/admin/PeoplePanel.test.tsx` (new) | vitest |
| `STATUS.md` | the shipped record |

---

### Task 1: `users/whoami.py` — one resolver, one identity rule

**Files:**
- Create: `users/__init__.py`, `users/whoami.py`
- Modify: `app/identity.py:16-67` (import + `current_user`), `ingest/jobs.py:19,253,667-671`, `ingest/claim.py:43,227,366-370`, `ingest/lock.py:38,370,408-414`
- Test: `tests/test_users_whoami.py`

**Interfaces:**
- Produces: `users.whoami.current_user() -> str`, `fold(username: str) -> str`, `same_person(a: str, b: str) -> bool`, `roster_key(username: str) -> str`, `USER_ENV_VAR = "JLBC_USER"`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_users_whoami.py
"""users/whoami.py — the ONE answer to "who is this process running as",
and the ONE rule for "are these two usernames the same person" (spec U0).

The source-level guards at the bottom are the point of the file: four
independently-written folds WILL drift, and the three private
`_current_user()` copies that used to live in ingest/ are how a JLBC_USER
override applied to AI usage but not to the job record for the same person.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from users import whoami

ROOT = Path(__file__).resolve().parent.parent


def test_current_user_prefers_the_override(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "analyst1")
    assert whoami.current_user() == "analyst1"


def test_current_user_falls_back_to_the_os(monkeypatch):
    monkeypatch.delenv("JLBC_USER", raising=False)
    monkeypatch.setattr(whoami.getpass, "getuser", lambda: "dmoss")
    assert whoami.current_user() == "dmoss"


def test_current_user_is_blank_when_the_os_cannot_say(monkeypatch):
    monkeypatch.delenv("JLBC_USER", raising=False)

    def boom():
        raise OSError("no USERNAME")

    monkeypatch.setattr(whoami.getpass, "getuser", boom)
    assert whoami.current_user() == ""


@pytest.mark.parametrize("a,b", [
    ("dmoss", "DMOSS"), ("Destin", "destin"), (" dmoss ", "dmoss"),
    ("İ", "i̇"),  # casefold, not lower: Python's lower() leaves these unequal
])
def test_same_person_folds_case_and_whitespace(a, b):
    assert whoami.same_person(a, b)


def test_same_person_never_matches_blank():
    # "" folds to "" — two unnameable users are NOT one person.
    assert not whoami.same_person("", "")
    assert not whoami.same_person("  ", "")


def test_different_people_are_different():
    assert not whoami.same_person("dmoss", "dmoss2")


def test_roster_key_is_identical_for_every_casing():
    assert whoami.roster_key("DMOSS") == whoami.roster_key("dmoss") == "dmoss"


def test_roster_key_sanitises_and_still_folds():
    # THE correction from review: the hash is of the FOLDED form, so the
    # backslash in a domain name does not give DOMAIN\dmoss and domain\dmoss
    # two files.
    a = whoami.roster_key("DOMAIN\\dmoss")
    b = whoami.roster_key("domain\\DMOSS")
    assert a == b
    assert a.startswith("domain-dmoss-")
    assert len(a) == len("domain-dmoss-") + 8


def test_roster_key_truncates_long_names_with_a_hash():
    key = whoami.roster_key("a" * 100)
    assert len(key) == 64 + 1 + 8
    assert key != whoami.roster_key("a" * 99)


def test_roster_key_of_blank_is_blank():
    assert whoami.roster_key("  ") == ""


def _shipped_python() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files", "*.py"], cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout.split()
    return [ROOT / p for p in out if not p.startswith(("tests/", "scripts/", "eval/", "packaging/"))]


def test_only_whoami_asks_the_os_who_is_running():
    """The resolver cannot grow a second copy. Found by review: jobs.py,
    claim.py and lock.py each carried a private one that ignored JLBC_USER."""
    offenders = [
        p for p in _shipped_python()
        if p != ROOT / "users" / "whoami.py" and "getpass.getuser(" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"call users.whoami.current_user() instead: {offenders}"


def test_only_two_places_fold_a_username():
    """U0 is one rule. harness/settings.py gets its own three-line copy
    because Invariant 7 forbids it importing users/ — and the copy is pinned
    to be the SAME expression, so the two cannot drift."""
    allowed = {ROOT / "users" / "whoami.py", ROOT / "harness" / "settings.py"}
    offenders = [
        p for p in _shipped_python()
        if p not in allowed and ".casefold(" in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"use users.whoami.same_person()/fold(): {offenders}"
    settings_src = (ROOT / "harness" / "settings.py").read_text(encoding="utf-8")
    assert "return user.strip().casefold()" in settings_src
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_users_whoami.py -q`
Expected: `ModuleNotFoundError: No module named 'users'`

- [ ] **Step 3: Create the package**

```python
# users/__init__.py
"""People: who is running this process, and the shared roster of everyone
who has opened the app (spec 2026-08-25-central-user-roster-design.md).

`whoami.py` is a LEAF — stdlib only — so `ingest/` can import it without
importing `app/` (the dependency runs app → ingest; reversing it would be
circular). `registry.py` reads and writes files and must never be admitted
to the harness import allowlist wholesale (Invariant 7).
"""
```

```python
# users/whoami.py
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
carries a three-line `_fold` pinned by test to the same expression.
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
```

- [ ] **Step 4: Re-point `app/identity.py` and the three ingest copies**

In `app/identity.py`: delete `import getpass` (line 16), replace the `USER_ENV_VAR` constant and the whole `current_user()` function (lines 33–67) with:

```python
from users.whoami import USER_ENV_VAR, current_user  # noqa: F401 — re-exported

# `current_user` MOVED to users/whoami.py (2026-08-25, spec U0) so that
# ingest/ can share it without importing app/. Re-exported here because ~16
# test modules and every route import it from this module.
```

In `ingest/jobs.py`: delete `import getpass` (line 19); add `from users.whoami import current_user`; change line 253 to `user=user or current_user() or "unknown",`; delete `_current_user()` (lines 667–671). Add above line 253:

```python
        # `or "unknown"`: the private resolver this replaced returned the
        # word "unknown", and job files are read in Notepad — a blank owner
        # would read as a torn file. users.whoami returns "" so the harness
        # can resolve it to the office default; the word is added here.
```

In `ingest/claim.py`: same edit — delete `import getpass` (line 43), import `current_user`, line 227 → `"user": current_user() or "unknown",`, delete lines 366–370.

In `ingest/lock.py`: same — delete `import getpass` (line 38), import `current_user`, line 370 → `"user": current_user() or "unknown",`, delete lines 408–414.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_users_whoami.py tests/test_identity.py tests/test_ingest_lock.py tests/test_ingest_parallel.py tests/test_jobs.py -q`
Expected: all PASS (the `test_only_whoami_asks_the_os_who_is_running` guard is what proves the three copies are gone).

- [ ] **Step 6: Commit**

```bash
git add users/ app/identity.py ingest/jobs.py ingest/claim.py ingest/lock.py tests/test_users_whoami.py
git commit -m "users: one resolver and one identity rule (whoami.py); ingest copies deleted"
```

---

### Task 2: `hidden_users` + case-insensitive `limit_for` / `is_exempt` / `is_admin`

**Files:**
- Modify: `harness/settings.py:199` (field), `:201-220` (`limit_for`), `:373-374` + `:386` (parse), `:411` (serialize); `harness/ledger.py:688`; `app/identity.py::is_admin`
- Test: `tests/test_harness_settings.py` (append), `tests/test_identity.py:34-40` (replace one test)

**Interfaces:**
- Produces: `Settings.hidden_users: tuple[str, ...]`, `Settings.is_exempt(user) -> bool`, `Settings.is_hidden(user) -> bool`, `Settings.limit_for(user)` now folding; `is_admin(settings, user)` folding.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_harness_settings.py`)

```python
# --- spec U0: username matching folds case, exact match wins ------------

def test_limit_for_matches_a_differently_cased_username():
    s = Settings(default_monthly_limit_usd=25.0, user_limits={"dmoss": 100.0})
    assert s.limit_for("DMOSS") == 100.0


def test_limit_for_exact_match_beats_a_folded_one():
    # A legacy hand-typed file can hold both spellings. The exact one wins —
    # silently picking is what the old comment was right to refuse, and the
    # People panel renders the collision (test_admin_users_route.py).
    s = Settings(user_limits={"dmoss": 100.0, "DMOSS": 60.0})
    assert s.limit_for("dmoss") == 100.0
    assert s.limit_for("DMOSS") == 60.0
    assert s.limit_for("Dmoss") == 100.0  # neither exact → first folded match, dict order


def test_exempt_list_folds_too():
    s = Settings(default_monthly_limit_usd=25.0, exempt_users=("director",))
    assert s.limit_for("DIRECTOR") is None
    assert s.is_exempt("Director")
    assert not s.is_exempt("analyst1")


def test_blank_user_never_folds_onto_anyone():
    s = Settings(default_monthly_limit_usd=25.0, user_limits={"": 5.0})
    assert s.limit_for("") == 5.0        # exact match still honoured
    assert s.limit_for("  ") == 25.0     # but whitespace does not fold to ""


def test_hidden_users_round_trip(tmp_path):
    s = Settings(hidden_users=("pchen",))
    save_settings(s, tmp_path / "settings.json")
    reloaded = load_settings(tmp_path / "settings.json")
    assert reloaded.hidden_users == ("pchen",)
    assert reloaded.is_hidden("PCHEN")
    assert not reloaded.is_hidden("dmoss")


def test_hidden_users_absent_from_an_older_file_reads_as_none(tmp_path):
    (tmp_path / "settings.json").write_text('{"admin_username": "x"}', encoding="utf-8")
    assert load_settings(tmp_path / "settings.json").hidden_users == ()
```

Replace `tests/test_identity.py:34-40` with:

```python
def test_admin_matches_the_username_under_the_one_identity_rule():
    s = Settings(admin_username="Destin")
    assert is_admin(s, "Destin") is True
    # Folds now (spec U0). `%USERNAME%` reflects how the person typed it at
    # logon, so `destin` vs `Destin` was a real lockout mode with a real
    # break-glass file to recover from. Once the admin seat is set from a
    # dropdown of observed usernames, "two rows an admin typed" cannot happen.
    assert is_admin(s, "destin") is True
    assert is_admin(s, "destin2") is False
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_harness_settings.py tests/test_identity.py -q`
Expected: 6 failures (`hidden_users` unexpected kwarg, `is_exempt` missing, `limit_for("DMOSS")` returning 25.0, `is_admin(s, "destin")` False).

- [ ] **Step 3: Implement in `harness/settings.py`**

After line 199 (`exempt_users: tuple[str, ...] = ()`) add:

```python
    # People the admin has taken out of every dropdown and the People table
    # (spec U7). HERE, not in the person's roster file: hiding is something
    # the ADMIN decides about someone ELSE, and a roster file is written only
    # by its own user's machine — an admin's machine writing it too was a
    # two-writer race with no lock in which a daily touch could silently
    # un-hide someone. Their ledger rows are untouched and still count.
    hidden_users: tuple[str, ...] = ()
```

Replace `limit_for` (lines 201–220) with:

```python
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
        folded = _fold(user)
        if folded:
            if any(_fold(u) == folded for u in self.exempt_users):
                return None
            for key, limit in self.user_limits.items():
                if _fold(key) == folded:
                    return limit
        return self.default_monthly_limit_usd

    def is_exempt(self, user: str) -> bool:
        """On the no-limit list, under the same rule `limit_for` uses."""
        if user in self.exempt_users:
            return True
        folded = _fold(user)
        return bool(folded) and any(_fold(u) == folded for u in self.exempt_users)

    def is_hidden(self, user: str) -> bool:
        """Hidden by the admin (spec U7), under the same rule."""
        if user in self.hidden_users:
            return True
        folded = _fold(user)
        return bool(folded) and any(_fold(u) == folded for u in self.hidden_users)
```

Add near the top of the module, after the imports:

```python
def _fold(user: str) -> str:
    """The U0 comparison form. A private copy of `users.whoami.fold`, NOT an
    import — this module is on the harness import allowlist (Invariant 7)
    and `users/registry.py` writes files, so admitting the package would
    admit that too. `tests/test_users_whoami.py` pins this line to the same
    expression so the two cannot drift."""
    return user.strip().casefold()
```

In `_settings_from_dict` (after the `exempt_users` parse, line ~374):

```python
    hidden_raw = raw.get("hidden_users")
    hidden_users = tuple(str(u) for u in hidden_raw) if isinstance(hidden_raw, list) else ()
```

and pass `hidden_users=hidden_users,` in the `Settings(...)` constructor (after `exempt_users=exempt_users,`). In `_settings_to_dict` add `"hidden_users": list(settings.hidden_users),` after the `exempt_users` line.

In `harness/ledger.py:688` change `reason = "exempt" if user in settings.exempt_users else "no limit"` to `reason = "exempt" if settings.is_exempt(user) else "no limit"`.

In `app/identity.py::is_admin` replace the docstring's "Matching is an EXACT string comparison…" paragraph and the last line:

```python
    Matching folds case (spec U0, 2026-08-25) via `users.whoami.same_person`
    — the ONE rule every username comparison uses. It was exact, with a
    real lockout mode (`destin` vs `Destin`) that the break-glass file
    existed to recover from; once the seat is set from a dropdown of
    observed usernames the "two typed rows" argument for exactness is gone.
    """
    if admin_claimable(settings):
        return True  # unclaimed — see admin_claimable for WHY
    return same_person(user, settings.admin_username)
```

and add `same_person` to the `from users.whoami import ...` line from Task 1.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_harness_settings.py tests/test_identity.py tests/test_users_whoami.py tests/test_admin_settings_route.py tests/test_admin_usage_route.py tests/test_ledger.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add harness/settings.py harness/ledger.py app/identity.py tests/test_harness_settings.py tests/test_identity.py
git commit -m "settings: hidden_users; limit_for/is_admin fold under the U0 rule"
```

---

### Task 3: `users/registry.py` — the roster files

**Files:**
- Create: `users/registry.py`
- Test: `tests/test_users_registry.py`

**Interfaces:**
- Consumes: `users.whoami.roster_key`, `fold`.
- Produces:
  - `class RosterUnavailable(Exception)`
  - `@dataclass(frozen=True) Person(key, username, display_name, name_source, first_seen, last_seen)`
  - `users_dir() -> Path` (= `data_dir() / "users"`)
  - `read_person(username) -> Person | None` — cached on `(mtime_ns, size)`; NEVER raises
  - `typed_name(username) -> str` — `read_person(...).display_name` when `name_source == "typed"`, else `""`
  - `list_people() -> tuple[list[Person], int]` — `(people, unreadable_count)`; raises `RosterUnavailable`
  - `touch(username, *, windows_name="", local_typed_name="") -> bool` — returns True iff it wrote; raises on write failure (the caller wraps)
  - `set_typed_name(username, name) -> None` — raises on write failure
  - `reset_roster_cache() -> None`
  - `ARIZONA_TZ`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_users_registry.py
"""One JSON file per person under <data_dir>/users/ (spec U1–U7).

Two properties carry the design and both are pinned below: a file is
written only by its own user's machine (nothing here takes another
person's username and writes it — there is no hide function), and a
second touch on the same day writes NOTHING (verified by mtime, because a
rewrite that changes no bytes is still a write on an SMB share).
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timedelta

import pytest

from harness import ledger
from users import registry


@pytest.fixture(autouse=True)
def share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    registry.reset_roster_cache()
    yield tmp_path
    registry.reset_roster_cache()


def _file(username: str):
    return registry.users_dir() / f"{registry.roster_key(username)}.json"


def test_first_touch_creates_the_row_with_the_windows_name():
    assert registry.touch("dmoss", windows_name="Danielle Moss") is True
    p = registry.read_person("dmoss")
    assert p is not None
    assert (p.username, p.display_name, p.name_source) == ("dmoss", "Danielle Moss", "windows")
    assert p.first_seen == p.last_seen
    raw = json.loads(_file("dmoss").read_text(encoding="utf-8"))
    assert raw["version"] == 1


def test_a_second_touch_the_same_day_writes_nothing():
    registry.touch("dmoss", windows_name="Danielle Moss")
    path = _file("dmoss")
    os.utime(path, (1_000_000, 1_000_000))
    assert registry.touch("dmoss", windows_name="Danielle Moss") is False
    assert path.stat().st_mtime == 1_000_000


def test_a_touch_on_a_new_day_updates_last_seen_only(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    first = registry.read_person("dmoss")
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)
    assert registry.touch("dmoss", windows_name="Danielle Moss") is True
    p = registry.read_person("dmoss")
    assert p.first_seen == first.first_seen
    assert p.last_seen[:10] == tomorrow.date().isoformat()


def test_the_day_bucket_is_arizona_local_like_the_ledger():
    # Anti-drift: the ledger shards on a fixed UTC-7; a roster that bucketed
    # on the host clock would write twice on the first UTC-hours of a day.
    assert registry.ARIZONA_TZ == ledger.ARIZONA_TZ


def test_a_changed_spelling_is_recorded_under_the_same_file():
    registry.touch("dmoss")
    assert registry.touch("DMOSS") is True
    assert registry.read_person("dmoss").username == "DMOSS"
    assert len(list(registry.users_dir().iterdir())) == 1


def test_a_typed_name_is_never_overwritten_by_windows(monkeypatch):
    registry.touch("dmoss", windows_name="JARRETTD")
    registry.set_typed_name("dmoss", "Danielle Moss")
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)  # force a next-day touch
    assert registry.touch("dmoss", windows_name="JARRETTD") is True  # last_seen moved…
    p = registry.read_person("dmoss")  # …but the typed name did not
    assert (p.display_name, p.name_source) == ("Danielle Moss", "typed")


def test_a_blank_windows_read_does_not_erase_a_name(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)
    registry.touch("dmoss", windows_name="")
    assert registry.read_person("dmoss").display_name == "Danielle Moss"


def test_a_local_typed_name_migrates_up_on_first_touch():
    registry.touch("dmoss", windows_name="JARRETTD", local_typed_name="Danielle Moss")
    p = registry.read_person("dmoss")
    assert (p.display_name, p.name_source) == ("Danielle Moss", "typed")


def test_clearing_a_typed_name_falls_back_to_windows_next_touch(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    registry.set_typed_name("dmoss", "D. Moss")
    registry.set_typed_name("dmoss", "")
    p = registry.read_person("dmoss")
    assert p.name_source == ""
    tomorrow = datetime.now(registry.ARIZONA_TZ) + timedelta(days=1)
    monkeypatch.setattr(registry, "_now", lambda: tomorrow)
    registry.touch("dmoss", windows_name="Danielle Moss")
    assert registry.read_person("dmoss").name_source == "windows"


def test_typed_name_reads_only_a_typed_source():
    registry.touch("dmoss", windows_name="Danielle Moss")
    assert registry.typed_name("dmoss") == ""
    registry.set_typed_name("dmoss", "Danielle Moss")
    assert registry.typed_name("DMOSS") == "Danielle Moss"


def test_a_blank_username_is_never_written():
    assert registry.touch("") is False
    assert registry.touch("   ") is False
    assert not registry.users_dir().exists() or list(registry.users_dir().iterdir()) == []


def test_read_person_is_cached_on_the_file_stamp(monkeypatch):
    registry.touch("dmoss", windows_name="Danielle Moss")
    registry.read_person("dmoss")
    opened = []
    real = registry.Path.read_text
    monkeypatch.setattr(registry.Path, "read_text", lambda self, *a, **k: (opened.append(self), real(self, *a, **k))[1])
    registry.read_person("dmoss")
    assert opened == []  # same stamp → no read
    registry.set_typed_name("dmoss", "D. Moss")
    assert registry.read_person("dmoss").display_name == "D. Moss"  # new stamp → re-read


@pytest.mark.parametrize("body", ["null", "[]", "5", "{not json", ""])
def test_read_person_degrades_on_a_bad_file(body):
    registry.users_dir().mkdir(parents=True)
    _file("dmoss").write_text(body, encoding="utf-8")
    assert registry.read_person("dmoss") is None
    assert registry.typed_name("dmoss") == ""


def test_list_people_reports_torn_files_as_a_count_not_a_row():
    registry.touch("dmoss", windows_name="Danielle Moss")
    registry.touch("gpaulsen", windows_name="Geoff Paulsen")
    _file("bjw2").write_text("{torn", encoding="utf-8")
    people, unreadable = registry.list_people()
    assert sorted(p.username for p in people) == ["dmoss", "gpaulsen"]
    assert unreadable == 1


def test_list_people_is_empty_when_nobody_has_opened_the_app():
    assert registry.list_people() == ([], 0)


def test_list_people_raises_when_the_folder_cannot_be_read(share):
    d = registry.users_dir()
    d.mkdir(parents=True)
    d.chmod(0)
    try:
        with pytest.raises(registry.RosterUnavailable):
            registry.list_people()
    finally:
        d.chmod(stat.S_IRWXU)


def test_list_people_raises_when_the_share_itself_is_gone(share, monkeypatch):
    # data_dir() creates the root as a side effect, so the discriminator is
    # "root missing" — the way app/health.py and app/issue_reports.py do it.
    monkeypatch.setenv("JLBC_DATA_DIR", str(share / "vanished"))
    monkeypatch.setattr(registry, "users_dir", lambda: share / "vanished" / "users")
    with pytest.raises(registry.RosterUnavailable):
        registry.list_people()


def test_there_is_no_way_to_write_another_persons_file():
    # Structural (spec U1/U7): every writer takes the username it writes FOR.
    # There is no hide(), no unhide(), no write-by-key.
    assert not hasattr(registry, "hide")
    assert not hasattr(registry, "unhide")
    assert not hasattr(registry, "write_person")
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_users_registry.py -q`
Expected: `ImportError: cannot import name 'registry'`

- [ ] **Step 3: Implement**

```python
# users/registry.py
"""The roster: one small JSON file per person under <data_dir>/users/.

    users/dmoss.json
    {
      "version": 1,
      "username": "dmoss",          <- most recently OBSERVED spelling
      "display_name": "Danielle Moss",
      "name_source": "windows",     <- "typed" | "windows" | ""
      "first_seen": "2026-08-25T09:14:03-07:00",
      "last_seen":  "2026-08-25T09:14:03-07:00"
    }

WHY one file per person and not one list (spec U1): ~20 machines rewriting
one list is exactly the corruption risk that kept names off the share
(spec M6). One file per person makes collision structurally impossible
BECAUSE a file is only ever written by the machine its own user is sitting
at — so nothing an ADMIN decides about a person lives here. `hidden` is
`settings.hidden_users` (spec U7); the first draft put it in this file and
had the admin's machine racing the person's own daily touch.

Precedents with the same shape and the same Notepad-readable reason:
ingest/jobs.py (one file per job), app/issue_reports.py (one per report).

Degrades on READ (a torn file costs one row), raises on WRITE (a caller
that could not record something must know — except the /api/me touch,
which catches and drops because a stale last_seen date is not worth a
slow page).
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from store.config import data_dir
from users.whoami import fold, roster_key

USERS_DIR = "users"
VERSION = 1

# Fixed UTC-7, no DST — the same rule harness/ledger.py shards on, pinned
# equal by test. The daily touch buckets on THIS clock so a person opening
# the app at 1 a.m. does not write once for UTC's day and once for Arizona's.
ARIZONA_TZ = timezone(timedelta(hours=-7), name="MST")


class RosterUnavailable(Exception):
    """The users folder itself could not be read — distinct from "nobody
    has opened the app", which is an empty list (spec U12)."""


@dataclass(frozen=True)
class Person:
    key: str
    username: str
    display_name: str
    name_source: str  # "typed" | "windows" | ""
    first_seen: str
    last_seen: str


def users_dir() -> Path:
    return data_dir() / USERS_DIR


def _now() -> datetime:
    return datetime.now(ARIZONA_TZ)


def _path_for(username: str) -> Path | None:
    key = roster_key(username)
    return users_dir() / f"{key}.json" if key else None


# ---------------------------------------------------------------------------
# Reading — one file, cached on its stamp; never raises
# ---------------------------------------------------------------------------

_lock = threading.Lock()
# path -> ((mtime_ns, size), Person | None). display_name() calls this on
# every page load (spec U6), so a page load after a page load costs one stat.
_cache: dict[str, tuple[tuple[int, int], Person | None]] = {}


def reset_roster_cache() -> None:
    with _lock:
        _cache.clear()


def _parse(path: Path, raw: object) -> Person | None:
    if not isinstance(raw, dict):
        return None
    username = raw.get("username")
    if not isinstance(username, str) or not username.strip():
        return None

    def s(key: str) -> str:
        v = raw.get(key)
        return v.strip() if isinstance(v, str) else ""

    return Person(
        key=path.stem,
        username=username,
        display_name=s("display_name"),
        name_source=s("name_source") if s("name_source") in ("typed", "windows") else "",
        first_seen=s("first_seen"),
        last_seen=s("last_seen"),
    )


def _read_path(path: Path) -> Person | None:
    """NEVER raises. Any failure — missing, unreadable, torn, wrong shape —
    is None, because the callers are `display_name()` on the request path
    of every page load and `list_people()`, which counts torn files."""
    try:
        st = path.stat()
        stamp = (st.st_mtime_ns, st.st_size)
    except OSError:
        return None
    with _lock:
        hit = _cache.get(str(path))
        if hit is not None and hit[0] == stamp:
            return hit[1]
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # ValueError covers JSONDecodeError and UnicodeDecodeError — the
        # trap harness/ledger.py documents.
        return None
    person = _parse(path, raw)
    with _lock:
        _cache[str(path)] = (stamp, person)
    return person


def read_person(username: str) -> Person | None:
    path = _path_for(username)
    return _read_path(path) if path else None


def typed_name(username: str) -> str:
    """The name this person TYPED, or "". A Windows-sourced name is not
    returned here: `display_name()` already reads Windows itself, and this
    is only the roster's claim on the top of that ladder (spec U6)."""
    p = read_person(username)
    return p.display_name if p and p.name_source == "typed" else ""


def list_people() -> tuple[list[Person], int]:
    """Every readable row, plus a COUNT of unreadable ones (spec U12).

    Raises RosterUnavailable when the folder cannot be read. Same
    discrimination app/issue_reports.py makes: `os.listdir`, not
    `Path.glob` (pathlib swallows the error and yields nothing — verified
    on this project), and a FileNotFoundError is "nobody yet" only when
    the ROOT data dir exists, because `data_dir()` creates the root as a
    side effect and a vanished share raises the same exception.
    """
    directory = users_dir()
    try:
        names = os.listdir(directory)
    except FileNotFoundError:
        if not directory.parent.is_dir():
            raise RosterUnavailable(f"shared data folder is unreachable: {directory.parent}")
        return [], 0
    except OSError as err:
        print(f"users.registry: cannot read {directory} ({err})", file=sys.stderr)
        raise RosterUnavailable(str(err)) from err
    people: list[Person] = []
    unreadable = 0
    for name in sorted(names):
        if not name.endswith(".json"):
            continue  # a ".tmp-…" half-write never shows up
        person = _read_path(directory / name)
        if person is None:
            unreadable += 1
            print(f"users.registry: unreadable row {directory / name}", file=sys.stderr)
        else:
            people.append(person)
    return people, unreadable


# ---------------------------------------------------------------------------
# Writing — only ever the CALLER'S OWN user; raises
# ---------------------------------------------------------------------------

def _write(path: Path, row: dict) -> None:
    """tmp + os.replace, like every other JSON writer on the share."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp-", suffix=".json.part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(row, f, indent=2)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _row(p: Person) -> dict:
    return {
        "version": VERSION,
        "username": p.username,
        "display_name": p.display_name,
        "name_source": p.name_source,
        "first_seen": p.first_seen,
        "last_seen": p.last_seen,
    }


def touch(username: str, *, windows_name: str = "", local_typed_name: str = "") -> bool:
    """Record that `username` opened the app today. Returns True iff it wrote.

    Writes only when something changed (spec U3): the person is new, the
    Arizona calendar day rolled over, the observed spelling changed, or the
    name changed — and a name changes only per spec U5: a typed name is
    never overwritten; a Windows name is refreshed only from a NON-EMPTY
    read (`_windows_display_name()` returns "" on any failure, and a blank
    must not erase a good name); a name typed on this machine before the
    roster existed migrates up once (spec U6).
    """
    path = _path_for(username)
    if path is None:
        return False
    now = _now()
    stamp = now.isoformat(timespec="seconds")
    existing = _read_path(path)

    windows_name = windows_name.strip()
    local_typed_name = local_typed_name.strip()

    if existing is None:
        if local_typed_name:
            name, source = local_typed_name, "typed"
        elif windows_name:
            name, source = windows_name, "windows"
        else:
            name, source = "", ""
        _write(path, _row(Person(path.stem, username, name, source, stamp, stamp)))
        return True

    name, source = existing.display_name, existing.name_source
    if source != "typed":
        if local_typed_name:
            name, source = local_typed_name, "typed"
        elif windows_name and windows_name != name:
            name, source = windows_name, "windows"

    changed = (
        existing.last_seen[:10] != stamp[:10]
        or existing.username != username
        or (name, source) != (existing.display_name, existing.name_source)
    )
    if not changed:
        return False
    _write(path, _row(Person(
        path.stem, username, name, source, existing.first_seen or stamp, stamp,
    )))
    return True


def set_typed_name(username: str, name: str) -> None:
    """The person's own name, typed on Settings. Blank clears it (spec U5) —
    "never set" and "cleared" are one state, so the Windows name can come
    back on the next touch. Raises on failure; the route decides what that
    means (the local machine file is written first and still counts)."""
    path = _path_for(username)
    if path is None:
        return
    now = _now().isoformat(timespec="seconds")
    existing = _read_path(path)
    cleaned = name.strip()
    if existing is None:
        person = Person(path.stem, username, cleaned, "typed" if cleaned else "", now, now)
    elif cleaned:
        person = Person(path.stem, existing.username, cleaned, "typed",
                        existing.first_seen or now, existing.last_seen or now)
    else:
        person = Person(path.stem, existing.username, "", "",
                        existing.first_seen or now, existing.last_seen or now)
    _write(path, _row(person))
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_users_registry.py -q`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add users/registry.py tests/test_users_registry.py
git commit -m "users: the roster registry — one observation file per person, single-writer, cached reads"
```

---

### Task 4: `/api/me` touches the roster in the background; `display_name()` reads it first

**Files:**
- Modify: `app/identity.py::display_name` (lines ~95–120), `app/routes/admin.py:168-213` (`me`, `set_my_display_name`), imports at `:31`
- Test: `tests/test_display_name.py` (append), `tests/test_identity.py` (append)

**Interfaces:**
- Consumes: `registry.touch`, `registry.typed_name`, `registry.set_typed_name`, `identity._windows_display_name`, `machine_config.read_display_name`.
- Produces: `GET /api/me` unchanged body; `PUT /api/me/display-name` unchanged body.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_display_name.py`)

```python
# --- spec U6: the roster is the top of the ladder, and it must be CHEAP ---

@pytest.fixture(autouse=True)
def _share(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "share"))
    from users import registry
    registry.reset_roster_cache()
    yield
    registry.reset_roster_cache()


def test_a_roster_typed_name_beats_the_local_one(monkeypatch):
    from users import registry
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "JARRETTD")
    machine_config.set_display_name("djarrett", "Local Name")
    registry.set_typed_name("djarrett", "Destin Jarrett")
    assert identity.display_name("djarrett") == "Destin Jarrett"


def test_a_roster_windows_name_does_not_beat_the_local_typed_one(monkeypatch):
    from users import registry
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "")
    machine_config.set_display_name("djarrett", "Local Name")
    registry.touch("djarrett", windows_name="JARRETTD")
    assert identity.display_name("djarrett") == "Local Name"


def test_a_failing_roster_read_falls_through_at_once(monkeypatch):
    from users import registry

    def boom(_):
        raise OSError("share timed out")

    monkeypatch.setattr(registry, "typed_name", boom)
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "")
    machine_config.set_display_name("djarrett", "Local Name")
    assert identity.display_name("djarrett") == "Local Name"


def test_saving_a_name_writes_both_stores():
    from users import registry
    client = TestClient(create_app(provider=StubSearchProvider()))
    r = client.put("/api/me/display-name", json={"display_name": "Danielle Moss"})
    assert r.status_code == 200
    assert machine_config.read_display_name(identity.current_user()) == "Danielle Moss"
    assert registry.typed_name(identity.current_user()) == "Danielle Moss"


def test_saving_a_name_still_succeeds_when_the_roster_write_fails(monkeypatch):
    from users import registry

    def boom(*a, **k):
        raise OSError("read-only share")

    monkeypatch.setattr(registry, "set_typed_name", boom)
    client = TestClient(create_app(provider=StubSearchProvider()))
    r = client.put("/api/me/display-name", json={"display_name": "Danielle Moss"})
    assert r.status_code == 200
    assert r.json()["display_name"] == "Danielle Moss"
```

Append to `tests/test_identity.py`:

```python
def test_me_registers_the_caller_in_the_roster(monkeypatch, tmp_path):
    from users import registry
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "dmoss")
    monkeypatch.setattr(identity, "_windows_display_name", lambda: "Danielle Moss")
    registry.reset_roster_cache()
    with TestClient(create_app(provider=StubSearchProvider())) as client:
        body = client.get("/api/me").json()
    assert body["user"] == "dmoss"
    p = registry.read_person("dmoss")
    assert p is not None and p.display_name == "Danielle Moss"


def test_me_is_unaffected_when_the_roster_write_fails(monkeypatch, tmp_path, capsys):
    from users import registry
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", "dmoss")

    def boom(*a, **k):
        raise OSError("share is read-only")

    monkeypatch.setattr(registry, "touch", boom)
    with TestClient(create_app(provider=StubSearchProvider())) as client:
        r = client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["user"] == "dmoss"
    assert "share is read-only" in capsys.readouterr().err
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_display_name.py tests/test_identity.py -q`
Expected: the five new display-name tests and the two `/api/me` tests fail (roster not consulted; `registry.touch` never called).

- [ ] **Step 3: Implement `display_name()`**

Replace the body of `display_name` in `app/identity.py`:

```python
def display_name(user: str | None = None) -> str:
    """The name to print on a document this analyst generates.

    Order: roster typed name > local typed name > Windows > username
    (spec U6). The roster is the SHARED store, so the name follows the
    analyst between PCs and the admin can see it; the local file is the
    offline fallback and stays in step (PUT /api/me/display-name writes
    both).

    THE ROSTER READ IS ON THE REQUEST PATH OF EVERY PAGE LOAD (`/api/me`),
    so it is bounded: one known file, cached on its (mtime, size) stamp
    inside users.registry, and ANY failure falls through to the local name
    with no exception — a memo signature is not worth a blocked request.
    The first draft of this feature put an unbounded share read here and
    contradicted its own "never wait on the share" rule (spec U4).

    DEVIATION FROM SPEC M5 (unchanged): a typed override beats
    auto-detection, because a WRONG AD name (`JARRETTD`) is likelier than
    a missing one.

    Never raises: the chain bottoms out at `current_user()`, which itself
    bottoms out at "".
    """
    resolved = current_user() if user is None else user
    try:
        from users import registry  # local import: keeps identity importable by store.config's lazy import chain

        shared = registry.typed_name(resolved)
    except Exception:  # noqa: BLE001 — the fallback below IS the handling
        shared = ""
    if shared:
        return shared
    override = machine_config.read_display_name(resolved)
    if override:
        return override
    windows = _windows_display_name()
    if windows:
        return windows
    return resolved
```

- [ ] **Step 4: Implement the touch and the dual write in `app/routes/admin.py`**

Add to the imports (after line 31):

```python
from fastapi.responses import JSONResponse
from starlette.background import BackgroundTask

from app.identity import _windows_display_name
from users import registry
```

Replace `me()` (lines 168–195):

```python
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
        "admin_reset_pending": admin_reset_pending(),
        "display_name": display_name(user),
    }
    return JSONResponse(body, background=BackgroundTask(_touch_roster, user))


def _touch_roster(user: str) -> None:
    """Never raises. A missing touch means a `last_seen` date is a day
    stale — the opposite posture to the ledger, where a missing row means
    money spent and not recorded."""
    try:
        registry.touch(
            user,
            windows_name=_windows_display_name(),
            local_typed_name=machine_config.read_display_name(user),
        )
    except Exception as err:  # noqa: BLE001 — see the docstring
        print(f"app.routes.admin: roster touch for {user!r} failed ({err})", file=sys.stderr)
```

Replace `set_my_display_name` (lines 202–213):

```python
@router.put("/api/me/display-name")
def set_my_display_name(body: DisplayNameBody) -> dict:
    """The analyst's own name, as it appears on documents they generate.

    DELIBERATELY UNGATED, like `GET /api/me`. There is no authentication
    anywhere in this app (S11), so a gate here would be theater.

    Writes BOTH stores (spec U6): the local machine file first — it is the
    offline fallback and the thing the analyst sitting here asked for — then
    the shared roster. A roster failure is logged and the request still
    returns 200 with the name that WILL print on this machine's memos.
    """
    user = current_user()
    machine_config.set_display_name(user, body.display_name)
    try:
        registry.set_typed_name(user, body.display_name)
    except Exception as err:  # noqa: BLE001 — local write already succeeded
        print(f"app.routes.admin: roster name save for {user!r} failed ({err})", file=sys.stderr)
    return {"display_name": display_name(user)}
```

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_display_name.py tests/test_identity.py tests/test_admin_settings_route.py tests/test_conversations_route.py -q`
Expected: all PASS. (`test_me_is_registered_before_the_spa_catch_all` and the existing `/api/me` tests must still pass — the body is unchanged.)

- [ ] **Step 6: Commit**

```bash
git add app/identity.py app/routes/admin.py tests/test_display_name.py tests/test_identity.py
git commit -m "identity: /api/me touches the roster in the background; display_name reads the roster first, cheaply"
```

---

### Task 5: `hidden_users` on the settings routes + `GET /api/admin/users`

**Files:**
- Modify: `app/routes/admin.py:275-306` (`_redacted`), `:320-338` (`SettingsBody`), `:398-405` (`_validate`), `:488-499` (`_merge`); add the new route after `get_usage`
- Test: `tests/test_admin_users_route.py` (new), `tests/test_admin_settings_route.py` (append two)

**Interfaces:**
- Produces: `GET /api/admin/users?month=YYYY-MM` →

```json
{
  "month": "2026-08",
  "unreachable": false,
  "unreadable": 0,
  "people": [
    {
      "key": "dmoss", "username": "dmoss", "display_name": "Danielle Moss",
      "name_source": "windows", "first_seen": "…", "last_seen": "…",
      "hidden": false, "spent_usd": 14.2,
      "limit": {"kind": "custom", "amount": 25.0, "collision": ["dmoss", "DMOSS"]}
    }
  ]
}
```

`limit.kind` ∈ `"default" | "custom" | "exempt"`; `amount` is the custom amount or null; `collision` lists every `user_limits` key that folds to this person when there is more than one, else `[]`. Sorted by `spent_usd` descending (the default the mockup shows) — the panel re-sorts client-side.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_users_route.py
"""GET /api/admin/users — the People panel's one payload (spec U8, U12, U14).

The route JOINS three sources — roster files, the month's ledger rows,
and settings.json — under the ONE identity rule (U0). The join is what the
tests here are about: a limit stored as DMOSS must land on the dmoss row,
spend ledgered under two spellings must sum onto one row, and a stored key
that matches nobody must appear NOWHERE (Destin: the orphan notice was
"wasteful and confusing").
"""
from __future__ import annotations

import json
import stat

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import StubSearchProvider
from harness.settings import ProviderConfig, Settings, TierConfig, reset_settings_cache, save_settings
from store.config import data_dir
from users import registry

ADMIN = "Destin"
MONTH = "2026-08"


@pytest.fixture(autouse=True)
def share(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("JLBC_USER", ADMIN)
    reset_settings_cache()
    registry.reset_roster_cache()
    yield tmp_path
    reset_settings_cache()
    registry.reset_roster_cache()


def configure(**over) -> None:
    save_settings(Settings(
        provider=ProviderConfig(api_key="sk-test", provider="openrouter"),
        tiers={"standard": TierConfig(model="vendor/standard")},
        admin_username=ADMIN, default_monthly_limit_usd=40.0, **over,
    ))
    reset_settings_cache()


def ledger(rows: list[dict]) -> None:
    path = data_dir() / "usage" / f"usage-{MONTH}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def row(user: str, cost: float) -> dict:
    return {"user": user, "tier": "standard", "model": "m", "tokens_in": 1, "tokens_out": 1, "cost_usd": cost}


@pytest.fixture
def client():
    return TestClient(create_app(provider=StubSearchProvider()))


def test_non_admins_get_403(client, monkeypatch):
    configure()
    monkeypatch.setenv("JLBC_USER", "analyst1")
    assert client.get(f"/api/admin/users?month={MONTH}").status_code == 403


def test_the_join_lands_a_differently_cased_limit_and_spend_on_one_row(client):
    """G-U2's server half."""
    configure(user_limits={"DMOSS": 25.0})
    registry.touch("dmoss", windows_name="Danielle Moss")
    ledger([row("dmoss", 10.0), row("DMOSS", 4.2)])
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert body["unreachable"] is False
    [p] = body["people"]
    assert p["username"] == "dmoss"
    assert p["display_name"] == "Danielle Moss"
    assert p["spent_usd"] == 14.2
    assert p["limit"] == {"kind": "custom", "amount": 25.0, "collision": []}


def test_a_stored_key_matching_nobody_appears_nowhere(client):
    """Spec U14 as Destin settled it: not a row, not a warning, not a count."""
    configure(user_limits={"tmartin": 50.0}, exempt_users=("ghost",), hidden_users=("nobody",))
    registry.touch("dmoss")
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert [p["username"] for p in body["people"]] == ["dmoss"]
    assert "tmartin" not in json.dumps(body)
    assert "ghost" not in json.dumps(body)


def test_two_stored_spellings_are_reported_as_a_collision(client):
    configure(user_limits={"dmoss": 25.0, "DMOSS": 60.0})
    registry.touch("dmoss")
    [p] = client.get(f"/api/admin/users?month={MONTH}").json()["people"]
    assert p["limit"]["kind"] == "custom"
    assert p["limit"]["amount"] == 25.0  # exact match wins (U0)
    assert sorted(p["limit"]["collision"]) == ["DMOSS", "dmoss"]


def test_exempt_and_hidden_fold(client):
    configure(exempt_users=("DIRECTOR",), hidden_users=("PCHEN",))
    registry.touch("director")
    registry.touch("pchen")
    people = {p["username"]: p for p in client.get(f"/api/admin/users?month={MONTH}").json()["people"]}
    assert people["director"]["limit"] == {"kind": "exempt", "amount": None, "collision": []}
    assert people["pchen"]["hidden"] is True
    assert people["director"]["hidden"] is False


def test_default_limit_has_no_amount(client):
    configure()
    registry.touch("dmoss")
    [p] = client.get(f"/api/admin/users?month={MONTH}").json()["people"]
    assert p["limit"] == {"kind": "default", "amount": None, "collision": []}


def test_sorted_by_spend_descending(client):
    configure()
    for u in ("a", "b", "c"):
        registry.touch(u)
    ledger([row("b", 9.0), row("c", 1.0)])
    names = [p["username"] for p in client.get(f"/api/admin/users?month={MONTH}").json()["people"]]
    assert names == ["b", "c", "a"]


def test_a_torn_row_is_counted_not_dropped_silently(client):
    configure()
    registry.touch("dmoss")
    (registry.users_dir() / "torn.json").write_text("{", encoding="utf-8")
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert body["unreadable"] == 1
    assert len(body["people"]) == 1


def test_an_unreadable_folder_is_unreachable_not_empty(client, share):
    """G-U3's server half: a prober-shaped failure production can produce."""
    configure()
    d = registry.users_dir()
    d.mkdir(parents=True)
    d.chmod(0)
    try:
        body = client.get(f"/api/admin/users?month={MONTH}").json()
    finally:
        d.chmod(stat.S_IRWXU)
    assert body["unreachable"] is True
    assert body["people"] == []


def test_a_fresh_install_is_empty_and_reachable(client):
    configure()
    body = client.get(f"/api/admin/users?month={MONTH}").json()
    assert body == {"month": MONTH, "unreachable": False, "unreadable": 0, "people": []}


def test_a_bad_month_is_a_400(client):
    configure()
    assert client.get("/api/admin/users?month=nope").status_code == 400
```

Append to `tests/test_admin_settings_route.py`:

```python
def test_hidden_users_round_trip_through_the_settings_routes():
    configure_admin()  # whichever existing helper seeds a claimed admin in this module
    client = TestClient(create_app(provider=StubSearchProvider()))
    r = client.put("/api/admin/settings", json={"hidden_users": ["pchen"], "api_key": "__unchanged__"})
    assert r.status_code == 200, r.text
    assert r.json()["hidden_users"] == ["pchen"]
    assert client.get("/api/admin/settings").json()["hidden_users"] == ["pchen"]


def test_a_blank_hidden_user_is_refused_like_the_other_lists():
    configure_admin()
    client = TestClient(create_app(provider=StubSearchProvider()))
    r = client.put("/api/admin/settings", json={"hidden_users": [" "], "api_key": "__unchanged__"})
    assert r.status_code == 400
```

(Read the module first: reuse its existing seeding helper's real name in place of `configure_admin()`.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_admin_users_route.py tests/test_admin_settings_route.py -q`
Expected: every users-route test 404s; the two settings tests fail on the missing key.

- [ ] **Step 3: Implement**

`_redacted` — add after `"exempt_users": list(settings.exempt_users),`:

```python
        "hidden_users": list(settings.hidden_users),
```

`SettingsBody` — add after `exempt_users: list[str] | None = None`:

```python
    hidden_users: list[str] | None = None
```

`_validate` — after the `exempt_users` loop:

```python
    for username in new.hidden_users:
        if not username.strip():
            raise _bad_request(MSG_BLANK_USERNAME)
```

`_merge` — after the `exempt_users=(...)` entry:

```python
        hidden_users=(
            tuple(str(u) for u in body.hidden_users)
            if body.hidden_users is not None else current.hidden_users
        ),
```

New route, placed directly after `get_usage`:

```python
# ---------------------------------------------------------------------------
# GET /api/admin/users — the People panel (spec U8, U12, U13, U14)
# ---------------------------------------------------------------------------


def _limit_view(settings: Settings, username: str) -> dict[str, Any]:
    """How this person's limit is stored, joined under U0.

    `collision` is the one thing the fold must SAY rather than resolve: a
    legacy hand-typed file can hold `dmoss` and `DMOSS`, `limit_for` picks
    the exact match, and the row shows both keys so the admin removes one.
    """
    if settings.is_exempt(username):
        return {"kind": "exempt", "amount": None, "collision": []}
    matching = [k for k in settings.user_limits if same_person(k, username)]
    if not matching:
        return {"kind": "default", "amount": None, "collision": []}
    return {
        "kind": "custom",
        "amount": settings.limit_for(username),
        "collision": matching if len(matching) > 1 else [],
    }


@router.get("/api/admin/users")
def get_users(
    month: str | None = None, settings: Settings = Depends(require_admin)
) -> dict:
    """Everyone who has opened the app, with this month's spend and their
    limit — ONE payload, joined server-side, so the panel never joins two
    endpoints itself and the three sources cannot disagree on screen.

    A stored limit/exempt/hidden key that matches no roster person is
    LEFT ALONE and NOT REPORTED (spec U14, Destin's call at the mockup):
    it applies to nobody, so it costs nothing, and the row appears with
    that limit already on it if the person ever opens the app.
    """
    shard = month or _current_month()
    if not _MONTH_SHARD.match(shard):
        raise _bad_request(MSG_BAD_MONTH)
    try:
        people, unreadable = registry.list_people()
    except registry.RosterUnavailable:
        # "Nobody has opened the app" and "we could not look" are different
        # facts (spec U12); only the second is known here.
        return {"month": shard, "unreachable": True, "unreadable": 0, "people": []}

    spend: dict[str, float] = {}
    for g in breakdown(shard, by="user"):
        spend[fold(g.key)] = spend.get(fold(g.key), 0.0) + g.cost_usd

    rows = [
        {
            "key": p.key,
            "username": p.username,
            "display_name": p.display_name,
            "name_source": p.name_source,
            "first_seen": p.first_seen,
            "last_seen": p.last_seen,
            "hidden": settings.is_hidden(p.username),
            "spent_usd": round(spend.get(fold(p.username), 0.0), 2),
            "limit": _limit_view(settings, p.username),
        }
        for p in people
    ]
    # Ties broken on the raw username — NOT `.casefold()`, which the U0
    # source guard confines to users/whoami.py and harness/settings.py.
    rows.sort(key=lambda r: (-r["spent_usd"], r["username"]))
    return {"month": shard, "unreachable": False, "unreadable": unreadable, "people": rows}
```

Add to the imports: `from users.whoami import fold, same_person`.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_admin_users_route.py tests/test_admin_settings_route.py tests/test_admin_usage_route.py tests/test_users_whoami.py -q`
Expected: all PASS (including the `.casefold(` source guard).

- [ ] **Step 5: Commit**

```bash
git add app/routes/admin.py tests/test_admin_users_route.py tests/test_admin_settings_route.py
git commit -m "admin: hidden_users on the settings routes; GET /api/admin/users joins roster, ledger and settings under U0"
```

---

### Task 6: `api.ts` types + `adminUsers()` + change description

**Files:**
- Modify: `webapp/src/api.ts:720-757` (`AdminSettings`, `AdminSettingsWrite`), add `adminUsers` after `adminUsage`; `webapp/src/admin/changes.ts:70-78`
- Test: `webapp/src/admin/changes.test.ts` (append; create if absent), `webapp/src/api.test.ts` (append if the file exists — otherwise the wire pin goes in `PeoplePanel.test.tsx`, Task 7)

**Interfaces:**
- Produces:

```ts
export interface PersonLimit { kind: "default" | "custom" | "exempt"; amount: number | null; collision: string[]; }
export interface PersonRow { key: string; username: string; display_name: string; name_source: "typed" | "windows" | ""; first_seen: string; last_seen: string; hidden: boolean; spent_usd: number; limit: PersonLimit; }
export interface AdminUsers { month: string; unreachable: boolean; unreadable: number; people: PersonRow[]; }
export async function adminUsers(month?: string): Promise<AdminUsers>
```

and `hidden_users: string[]` on `AdminSettings`, `hidden_users?: string[]` on `AdminSettingsWrite`.

- [ ] **Step 1: Write the failing test** (append to `webapp/src/admin/changes.test.ts`, creating the file with the standard vitest imports if it does not exist)

```ts
import { describe, expect, it } from "vitest";
import { describeChanges } from "./changes";
import type { AdminSettings } from "../api";

const base: AdminSettings = {
  provider: { provider: "openrouter", base_url: "https://openrouter.ai/api/v1", api_key_set: true, api_key_hint: "…abcd", prompt_usd_per_m: null, completion_usd_per_m: null },
  tiers: { standard: { model: "vendor/m", enabled: true } },
  admin_username: "Destin",
  ai_enabled: true,
  default_monthly_limit_usd: 40,
  user_limits: {},
  exempt_users: [],
  hidden_users: [],
};

describe("hidden people", () => {
  it("names a hide as a change the admin can read", () => {
    const draft = { ...base, hidden_users: ["pchen"] };
    expect(describeChanges(base, draft, null, null)).toEqual(["who is hidden"]);
  });
});
```

(Copy `AdminProvider`'s exact field list from `api.ts` into `base.provider` if it differs from the literal above.)

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp && npx vitest run src/admin/changes.test.ts`
Expected: FAIL — `tsc` complains `hidden_users` is not on `AdminSettings`, and the array is `[]`.

- [ ] **Step 3: Implement**

`api.ts` — in `AdminSettings` after `exempt_users: string[];`:

```ts
  /** People the admin took out of every list (spec U7). Stored HERE, not in
   *  the person's roster file — see harness/settings.py for the two-writer
   *  race that decided it. */
  hidden_users: string[];
```

in `AdminSettingsWrite` after `exempt_users?: string[];`: `hidden_users?: string[];`

After `adminUsage`:

```ts
export interface PersonLimit {
  kind: "default" | "custom" | "exempt";
  amount: number | null;
  /** Every stored limit key that folds to this person when there is more
   *  than one — a legacy hand-typed file can hold `dmoss` and `DMOSS`. */
  collision: string[];
}

export interface PersonRow {
  key: string;
  username: string;
  display_name: string;
  name_source: "typed" | "windows" | "";
  first_seen: string;
  last_seen: string;
  hidden: boolean;
  spent_usd: number;
  limit: PersonLimit;
}

export interface AdminUsers {
  month: string;
  /** The users folder could not be read. Distinct from "nobody yet" — the
   *  panel says so and the hand-over picker degrades to a typed box. */
  unreachable: boolean;
  /** Rows that exist but could not be read. Shown, never silently dropped. */
  unreadable: number;
  people: PersonRow[];
}

export async function adminUsers(month?: string): Promise<AdminUsers> {
  const r = await fetch(`/api/admin/users${month ? `?month=${month}` : ""}`);
  if (!r.ok) await fail(r, "people");
  return r.json();
}
```

`changes.ts` — after the `exempt_users` comparison:

```ts
  if (JSON.stringify(draft.hidden_users) !== JSON.stringify(saved.hidden_users)) {
    changes.push("who is hidden");
  }
```

Then fix every `AdminSettings` literal the type change breaks: run `npx tsc -b` and add `hidden_users: []` to each fixture it names (`Admin.test.tsx:~42`, `Settings.test.tsx`, any `ProviderPanel`/`AdvancedPanel` fixtures).

- [ ] **Step 4: Run**

Run: `cd webapp && npx tsc -b && npx vitest run src/admin/changes.test.ts`
Expected: tsc exit 0, spec PASS.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/api.ts webapp/src/admin/changes.ts webapp/src/admin/changes.test.ts webapp/src/pages/Admin.test.tsx webapp/src/pages/Settings.test.tsx
git commit -m "webapp: AdminUsers types, adminUsers(), hidden_users on settings"
```

---

### Task 7: `PeoplePanel.tsx` — the approved table

**Files:**
- Create: `webapp/src/admin/PeoplePanel.tsx`, `webapp/src/admin/PeoplePanel.test.tsx`
- Modify: `webapp/src/styles/app.css` (append after the `.adm-inline` block, ~line 271 of the admin section)

**Interfaces:**
- Consumes: `api.AdminUsers`, `api.PersonRow`, `api.AdminSettings` (draft), `api.UNCHANGED_KEY` not needed here.
- Produces:

```tsx
export function PeoplePanel(props: {
  people: api.AdminUsers | null;      // null while loading
  loadError: string | null;
  draft: api.AdminSettings;
  onLimitChange: (username: string, next: api.PersonLimit["kind"], amount: number | null) => void;
  onHiddenChange: (hidden_users: string[]) => void;
}): JSX.Element
export function sortPeople(rows: api.PersonRow[], col: SortCol, dir: "asc" | "desc"): api.PersonRow[]
export type SortCol = "person" | "last_seen" | "spent" | "limit";
```

The panel is PURE: it never fetches (Admin.tsx does) and never saves (the save bar does). `onLimitChange` edits `draft.user_limits` / `draft.exempt_users`; `onHiddenChange` edits `draft.hidden_users`.

- [ ] **Step 1: Write the failing tests**

```tsx
// webapp/src/admin/PeoplePanel.test.tsx
import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type * as api from "../api";
import { PeoplePanel, sortPeople } from "./PeoplePanel";

// The mockup this must match:
// docs/superpowers/specs/assets/2026-08-25-user-roster-mockup/people-panel.html

function person(over: Partial<api.PersonRow>): api.PersonRow {
  return {
    key: "x", username: "x", display_name: "", name_source: "", first_seen: "2026-08-01T09:00:00-07:00",
    last_seen: "2026-08-25T09:00:00-07:00", hidden: false, spent_usd: 0,
    limit: { kind: "default", amount: null, collision: [] }, ...over,
  };
}

const PEOPLE: api.PersonRow[] = [
  person({ key: "dmoss", username: "dmoss", display_name: "Danielle Moss", spent_usd: 14.2,
    limit: { kind: "custom", amount: 25, collision: [] } }),
  person({ key: "gpaulsen", username: "gpaulsen", display_name: "Geoff Paulsen", spent_usd: 9.85,
    last_seen: "2026-08-24T09:00:00-07:00" }),
  person({ key: "bjw2", username: "bjw2", spent_usd: 3.1, last_seen: "2026-08-19T09:00:00-07:00",
    limit: { kind: "exempt", amount: null, collision: [] } }),
  person({ key: "pchen", username: "pchen", display_name: "Pat Chen", hidden: true,
    last_seen: "2026-06-30T09:00:00-07:00" }),
];

const DRAFT = {
  provider: { provider: "openrouter", base_url: "", api_key_set: true, api_key_hint: "", prompt_usd_per_m: null, completion_usd_per_m: null },
  tiers: {}, admin_username: "Destin", ai_enabled: true, default_monthly_limit_usd: 40,
  user_limits: { dmoss: 25 }, exempt_users: ["bjw2"], hidden_users: ["pchen"],
} as api.AdminSettings;

function renderPanel(over: Partial<React.ComponentProps<typeof PeoplePanel>> = {}) {
  const props = {
    people: { month: "2026-08", unreachable: false, unreadable: 0, people: PEOPLE },
    loadError: null, draft: DRAFT, onLimitChange: vi.fn(), onHiddenChange: vi.fn(), ...over,
  };
  render(<PeoplePanel {...props} />);
  return props;
}

describe("the table", () => {
  it("lists everyone who is not hidden, spend-first, username under the name", () => {
    renderPanel();
    const rows = screen.getAllByRole("row").slice(1); // minus the header
    expect(rows.map((r) => within(r).getByRole("rowheader").textContent)).toEqual([
      "Danielle Mossdmoss", "Geoff Paulsengpaulsen", "No name yetbjw2",
    ]);
    expect(screen.getByRole("columnheader", { name: /spent this month/i })).toHaveAttribute("aria-sort", "descending");
  });

  it("collapses hidden people to one line with a Show pill, and expands in place", () => {
    renderPanel();
    expect(screen.getByText(/1 person hidden/)).toHaveTextContent("Pat Chen");
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    expect(screen.getByRole("rowheader", { name: /Pat Chen/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Unhide Pat Chen/ })).toBeInTheDocument();
  });

  it("hides and unhides by editing the draft's hidden_users", () => {
    const props = renderPanel();
    fireEvent.click(screen.getByRole("button", { name: /Hide Geoff Paulsen/ }));
    expect(props.onHiddenChange).toHaveBeenCalledWith(["pchen", "gpaulsen"]);
    fireEvent.click(screen.getByRole("button", { name: "Show" }));
    fireEvent.click(screen.getByRole("button", { name: /Unhide Pat Chen/ }));
    expect(props.onHiddenChange).toHaveBeenCalledWith([]);
  });

  it("shows the limit dropdown in the right state per row", () => {
    renderPanel();
    expect(screen.getByRole("combobox", { name: /limit for Danielle Moss/i })).toHaveValue("custom");
    expect(screen.getByRole("spinbutton", { name: /amount for Danielle Moss/i })).toHaveValue(25);
    expect(screen.getByRole("combobox", { name: /limit for Geoff Paulsen/i })).toHaveValue("default");
    expect(screen.queryByRole("spinbutton", { name: /amount for Geoff Paulsen/i })).toBeNull();
    expect(screen.getByRole("combobox", { name: /limit for bjw2/i })).toHaveValue("exempt");
  });

  it("writes the right one of the two settings fields and clears the other", () => {
    const props = renderPanel();
    fireEvent.change(screen.getByRole("combobox", { name: /limit for Geoff Paulsen/i }), { target: { value: "exempt" } });
    expect(props.onLimitChange).toHaveBeenLastCalledWith("gpaulsen", "exempt", null);
    fireEvent.change(screen.getByRole("combobox", { name: /limit for bjw2/i }), { target: { value: "custom" } });
    expect(props.onLimitChange).toHaveBeenLastCalledWith("bjw2", "custom", 40); // starts at the office default
    fireEvent.change(screen.getByRole("spinbutton", { name: /amount for Danielle Moss/i }), { target: { value: "30" } });
    expect(props.onLimitChange).toHaveBeenLastCalledWith("dmoss", "custom", 30);
  });

  it("names both spellings when a limit is stored twice", () => {
    renderPanel({ people: { month: "2026-08", unreachable: false, unreadable: 0, people: [
      person({ key: "dmoss", username: "dmoss", display_name: "Danielle Moss",
        limit: { kind: "custom", amount: 25, collision: ["dmoss", "DMOSS"] } }),
    ] } });
    expect(screen.getByText(/two spellings/i)).toHaveTextContent("DMOSS");
  });

  it("says the folder could not be read rather than showing an empty table", () => {
    renderPanel({ people: { month: "2026-08", unreachable: true, unreadable: 0, people: [] } });
    expect(screen.getByRole("alert")).toHaveTextContent(/couldn't be read/i);
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(/nobody has opened/i)).toBeNull();
  });

  it("says nobody yet on a fresh install, which is a different fact", () => {
    renderPanel({ people: { month: "2026-08", unreachable: false, unreadable: 0, people: [] } });
    expect(screen.getByText(/nobody has opened the app yet/i)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reports unreadable rows as a count, never silently", () => {
    renderPanel({ people: { month: "2026-08", unreachable: false, unreadable: 2, people: PEOPLE } });
    expect(screen.getByText(/2 people's records couldn't be read/)).toBeInTheDocument();
  });

  it("uses pills, never bare link text, for every action", () => {
    const { container } = render(<PeoplePanel people={{ month: "2026-08", unreachable: false, unreadable: 0, people: PEOPLE }}
      loadError={null} draft={DRAFT} onLimitChange={vi.fn()} onHiddenChange={vi.fn()} />);
    expect(container.querySelector(".adm-link")).toBeNull();
    for (const b of container.querySelectorAll("button")) expect(b.className).toMatch(/adm-btn/);
  });

  it("carries no jargon", () => {
    const { container } = render(<PeoplePanel people={{ month: "2026-08", unreachable: true, unreadable: 1, people: [] }}
      loadError={null} draft={DRAFT} onLimitChange={vi.fn()} onHiddenChange={vi.fn()} />);
    for (const jargon of ["endpoint", "corpus", "chunk", "prompt caching", "catalog", "tier", "roster"]) {
      expect(container.textContent!.toLowerCase()).not.toContain(jargon);
    }
  });
});

describe("sortPeople", () => {
  const rows = PEOPLE.filter((p) => !p.hidden);

  it("sorts every column both ways", () => {
    expect(sortPeople(rows, "spent", "desc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "spent", "asc").map((p) => p.username)).toEqual(["bjw2", "gpaulsen", "dmoss"]);
    expect(sortPeople(rows, "last_seen", "desc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "last_seen", "asc").map((p) => p.username)).toEqual(["bjw2", "gpaulsen", "dmoss"]);
    // limit: highest amount, then office default, then no limit — reversed exactly
    expect(sortPeople(rows, "limit", "desc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "limit", "asc").map((p) => p.username)).toEqual(["bjw2", "gpaulsen", "dmoss"]);
  });

  it("puts a person with no name LAST in a name sort in BOTH directions", () => {
    expect(sortPeople(rows, "person", "asc").map((p) => p.username)).toEqual(["dmoss", "gpaulsen", "bjw2"]);
    expect(sortPeople(rows, "person", "desc").map((p) => p.username)).toEqual(["gpaulsen", "dmoss", "bjw2"]);
  });

  it("clicking a heading sorts, clicking again reverses, and aria-sort says so", () => {
    renderPanel();
    const person = screen.getByRole("columnheader", { name: /person/i });
    fireEvent.click(within(person).getByRole("button"));
    expect(person).toHaveAttribute("aria-sort", "ascending");
    expect(screen.getAllByRole("rowheader")[0]).toHaveTextContent("Danielle Moss");
    fireEvent.click(within(person).getByRole("button"));
    expect(person).toHaveAttribute("aria-sort", "descending");
    expect(screen.getAllByRole("rowheader")[0]).toHaveTextContent("Geoff Paulsen");
    expect(screen.getByRole("columnheader", { name: /spent/i })).not.toHaveAttribute("aria-sort");
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp && npx vitest run src/admin/PeoplePanel.test.tsx`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement the component**

```tsx
// webapp/src/admin/PeoplePanel.tsx
import { useState } from "react";
import type * as api from "../api";

// The People panel (spec 2026-08-25-central-user-roster-design.md, U13).
//
// APPROVED FROM A RENDERED MOCKUP — docs/superpowers/specs/assets/
// 2026-08-25-user-roster-mockup/people-panel.html. Two earlier shapes were
// rejected on sight: a seven-column table with a Status column, numbered
// badges and a "show hidden" tick box ("too complicated, visual hierarchy
// messy"), and a box announcing a limit stored for a username nobody has
// logged in as ("wasteful and confusing"). What stands: one row per person,
// the limit as a dropdown on the row, ONE pill per row, hidden people as a
// single line beneath. Every action is a pill — never `adm-link` (Destin's
// standing rule).
//
// PURE. Admin.tsx fetches `people` and owns the settings draft; this edits
// the draft through the two callbacks and the page's save bar writes it.
// A limit change here is therefore listed in the save bar ("who has their
// own limit") exactly like the rows it replaced in ProviderPanel.

export type SortCol = "person" | "last_seen" | "spent" | "limit";
type Dir = "asc" | "desc";

const DEFAULT_SORT: { col: SortCol; dir: Dir } = { col: "spent", dir: "desc" };

function nameOf(p: api.PersonRow): string {
  return p.display_name || "";
}

/** Highest amount, then office default, then no limit (spec U13). */
function limitRank(p: api.PersonRow): number {
  if (p.limit.kind === "exempt") return -Infinity;
  if (p.limit.kind === "default") return -1;
  return p.limit.amount ?? -1;
}

export function sortPeople(rows: api.PersonRow[], col: SortCol, dir: Dir): api.PersonRow[] {
  const sign = dir === "asc" ? 1 : -1;
  const named = rows.filter((p) => nameOf(p));
  const unnamed = rows.filter((p) => !nameOf(p));
  const cmp = (a: api.PersonRow, b: api.PersonRow): number => {
    switch (col) {
      case "person":
        return sign * nameOf(a).localeCompare(nameOf(b));
      case "last_seen":
        return sign * a.last_seen.localeCompare(b.last_seen);
      case "spent":
        return sign * (a.spent_usd - b.spent_usd);
      case "limit":
        return sign * (limitRank(a) - limitRank(b));
    }
  };
  if (col === "person") {
    // A person with no recorded name sorts LAST in BOTH directions:
    // reversing a sort must not promote the least informative rows.
    return [...named].sort(cmp).concat(unnamed.sort((a, b) => a.username.localeCompare(b.username)));
  }
  return [...rows].sort(cmp);
}

function usd(n: number): string {
  return `$${n.toFixed(2)}`;
}

function when(iso: string): string {
  if (!iso) return "";
  const d = new Date(iso);
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const days = Math.round((start(new Date()) - start(d)) / 86_400_000);
  if (days === 0) return "Today";
  if (days === 1) return "Yesterday";
  return d.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

const LIMIT_OPTIONS: Array<{ value: api.PersonLimit["kind"]; label: (d: number | null) => string }> = [
  { value: "default", label: (d) => (d === null ? "Office default (no limit)" : `Office default ($${d})`) },
  { value: "custom", label: () => "A specific amount" },
  { value: "exempt", label: () => "No limit" },
];

export function PeoplePanel({
  people,
  loadError,
  draft,
  onLimitChange,
  onHiddenChange,
}: {
  people: api.AdminUsers | null;
  loadError: string | null;
  draft: api.AdminSettings;
  onLimitChange: (username: string, kind: api.PersonLimit["kind"], amount: number | null) => void;
  onHiddenChange: (hidden_users: string[]) => void;
}) {
  const [sort, setSort] = useState(DEFAULT_SORT);
  const [showHidden, setShowHidden] = useState(false);

  function clickHeading(col: SortCol) {
    setSort((s) => (s.col === col ? { col, dir: s.dir === "asc" ? "desc" : "asc" } : { col, dir: col === "person" ? "asc" : "desc" }));
  }

  // `hidden` comes from the DRAFT, not the server row, so a hide shows at
  // once and the save bar lists it; the server's flag is what the draft
  // started from.
  const isHidden = (p: api.PersonRow) => draft.hidden_users.includes(p.username);

  function hide(p: api.PersonRow) {
    onHiddenChange([...draft.hidden_users, p.username]);
  }
  function unhide(p: api.PersonRow) {
    onHiddenChange(draft.hidden_users.filter((u) => u !== p.username));
  }

  const rows = people ? sortPeople(people.people, sort.col, sort.dir) : [];
  const visible = rows.filter((p) => !isHidden(p) || showHidden);
  const hidden = rows.filter(isHidden);

  const heading = (col: SortCol, label: string) => (
    <th
      scope="col"
      className="adm-people-sortable"
      aria-sort={sort.col === col ? (sort.dir === "asc" ? "ascending" : "descending") : undefined}
    >
      <button type="button" className="adm-people-sort" onClick={() => clickHeading(col)}>
        {label}
        {sort.col === col ? <span className="adm-people-arrow">{sort.dir === "asc" ? "▲" : "▼"}</span> : null}
      </button>
    </th>
  );

  return (
    <section className="card adm-panel" aria-labelledby="adm-people-h" data-testid="admin-people">
      <h2 id="adm-people-h">People</h2>
      <p className="adm-sub">
        Everyone who has opened the app, and what they have spent on AI Mode this
        month. Names come from Windows; anyone can change their own on their
        Settings page.
      </p>

      {loadError ? (
        <p className="adm-warn" role="alert">{loadError}</p>
      ) : people === null ? (
        <p className="adm-empty">Loading…</p>
      ) : people.unreachable ? (
        <p className="adm-warn" role="alert" data-testid="admin-people-unreachable">
          The list of people couldn't be read from the shared folder. Check the
          shared drive is connected, then reload.
        </p>
      ) : people.people.length === 0 ? (
        <p className="adm-empty">Nobody has opened the app yet.</p>
      ) : (
        <>
          <div className="adm-table-wrap">
            <table className="adm-table adm-people">
              <thead>
                <tr>
                  {heading("person", "Person")}
                  {heading("last_seen", "Last seen")}
                  {heading("spent", "Spent this month")}
                  {heading("limit", "Monthly limit")}
                  <th scope="col"><span className="adm-vh">Actions</span></th>
                </tr>
              </thead>
              <tbody>
                {visible.map((p) => {
                  const name = nameOf(p);
                  const label = name || p.username;
                  const hiddenRow = isHidden(p);
                  return (
                    <tr key={p.key} className={hiddenRow ? "is-hidden" : undefined}>
                      <th scope="row">
                        {name ? name : <span className="adm-people-noname">No name yet</span>}
                        <span className="adm-people-who">{p.username}</span>
                      </th>
                      <td>{when(p.last_seen)}</td>
                      <td>{usd(p.spent_usd)}</td>
                      <td>
                        <span className="adm-people-limit">
                          <select
                            aria-label={`Monthly limit for ${label}`}
                            value={p.limit.kind}
                            disabled={hiddenRow}
                            onChange={(e) => {
                              const kind = e.target.value as api.PersonLimit["kind"];
                              onLimitChange(p.username, kind, kind === "custom" ? (p.limit.amount ?? draft.default_monthly_limit_usd ?? 0) : null);
                            }}
                          >
                            {LIMIT_OPTIONS.map((o) => (
                              <option key={o.value} value={o.value}>{o.label(draft.default_monthly_limit_usd)}</option>
                            ))}
                          </select>
                          {p.limit.kind === "custom" ? (
                            <input
                              type="number"
                              min={0}
                              aria-label={`Monthly amount for ${label}`}
                              value={p.limit.amount ?? ""}
                              disabled={hiddenRow}
                              onChange={(e) => onLimitChange(p.username, "custom", e.target.value === "" ? 0 : Number(e.target.value))}
                            />
                          ) : null}
                        </span>
                        {p.limit.collision.length > 1 ? (
                          <p className="adm-people-warn">
                            Two spellings of this limit are saved ({p.limit.collision.join(" and ")}).
                            The exact match is the one in force — remove the other.
                          </p>
                        ) : null}
                      </td>
                      <td className="adm-people-act">
                        {hiddenRow ? (
                          <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => unhide(p)}>
                            Unhide <span className="adm-vh">{label}</span>
                          </button>
                        ) : (
                          <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => hide(p)}>
                            Hide <span className="adm-vh">{label}</span>
                          </button>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          {people.unreadable > 0 ? (
            <p className="adm-hint">
              {people.unreadable === 1 ? "1 person's record" : `${people.unreadable} people's records`} couldn't be read.
            </p>
          ) : null}

          {hidden.length > 0 && !showHidden ? (
            <div className="adm-people-hidden">
              <span>
                {hidden.length === 1
                  ? `1 person hidden (${nameOf(hidden[0]) || hidden[0].username}, last seen ${when(hidden[0].last_seen)})`
                  : `${hidden.length} people hidden`}
              </span>
              <button type="button" className="adm-btn adm-btn-quiet adm-btn-sm" onClick={() => setShowHidden(true)}>Show</button>
            </div>
          ) : null}
          <p className="adm-hint">
            Hiding someone takes them out of the lists on this page. Their past
            spending still counts; nothing is deleted.
          </p>
        </>
      )}
    </section>
  );
}
```

(The tests use fixed ISO dates; "Today"/"Yesterday" are not asserted, so the relative words are safe in jsdom.)

- [ ] **Step 4: Add the CSS** (append to the admin section of `webapp/src/styles/app.css`, after `.adm-price`)

```css
/* --- People (spec U13, mockup 2026-08-25) ---------------------------------
   Every action on this page is a pill. `.adm-btn-sm` is the row-sized one;
   `.adm-link` — bare blue underlined text as a control — is gone from the
   sheet entirely (Destin, 2026-08-25: "shouldn't be used anywhere"). */
.adm-btn-sm{padding:4px 12px;font-size:12px;}
.adm-people-sortable{cursor:pointer;user-select:none;}
.adm-people-sort{border:0;background:none;padding:0;font:inherit;color:inherit;text-transform:inherit;letter-spacing:inherit;cursor:pointer;}
.adm-people-sortable[aria-sort]{color:var(--navy);}
.adm-people-sortable:hover .adm-people-sort{color:var(--az-gold-d);}
.adm-people-arrow{margin-left:4px;font-size:10px;}
.adm-people tbody th{white-space:nowrap;}
.adm-people-who{display:block;font-size:11.5px;font-weight:400;color:var(--ink-3);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;}
.adm-people-noname{color:var(--ink-3);font-weight:400;font-style:italic;}
.adm-people-limit{display:inline-flex;gap:6px;align-items:center;white-space:nowrap;}
.adm-people-limit select{padding:4px 8px;font-size:12.5px;}
.adm-people-limit input[type=number]{width:70px;padding:4px 8px;font-size:12.5px;}
.adm-people-warn{font-size:12.5px;color:var(--warn);margin:4px 0 0;line-height:1.5;max-width:40ch;white-space:normal;}
.adm-people-act{text-align:right;white-space:nowrap;}
.adm-people tr.is-hidden td,.adm-people tr.is-hidden th{color:var(--ink-3);font-weight:400;}
.adm-people-hidden{display:flex;align-items:center;gap:12px;margin:14px 0 0;font-size:13px;color:var(--ink-3);}
```

- [ ] **Step 5: Run**

Run: `cd webapp && npx tsc -b && npx vitest run src/admin/PeoplePanel.test.tsx`
Expected: tsc 0, all specs PASS.

- [ ] **Step 6: Mutation-verify the mount-independent guards, in place then `git checkout`**

Change `className="adm-btn adm-btn-quiet adm-btn-sm"` on the Hide button to `className="adm-link"` → "uses pills" spec must go RED. Remove the `named…concat(unnamed…)` branch → "no name LAST" spec RED. Restore with `git checkout webapp/src/admin/PeoplePanel.tsx`.

- [ ] **Step 7: Commit**

```bash
git add webapp/src/admin/PeoplePanel.tsx webapp/src/admin/PeoplePanel.test.tsx webapp/src/styles/app.css
git commit -m "admin: PeoplePanel — the approved table, limit dropdown per row, hidden line, pills only"
```

---

### Task 8: Mount it; slim `ProviderPanel`; wire the draft

**Files:**
- Modify: `webapp/src/pages/Admin.tsx` (imports `:1-16`, state `:60-75`, load `:118-127`, month effect `:150-160`, render `:465-482`), `webapp/src/admin/ProviderPanel.tsx:215-330` (the Spending limits card), `:60-80` (props)
- Test: `webapp/src/pages/Admin.test.tsx` (mount guard + fixture), delete the ProviderPanel specs that drove the removed rows

**Interfaces:**
- Consumes: `PeoplePanel`, `api.adminUsers`.
- `ProviderPanel` LOSES `onUserLimitsChange` and `onExemptChange` props.

- [ ] **Step 1: Write the failing tests** (append to `webapp/src/pages/Admin.test.tsx`; add `vi.spyOn(api, "adminUsers")` to `mockAll`)

In `mockAll`, after the `issues` spy:

```ts
  vi.spyOn(api, "adminUsers").mockResolvedValue(
    over.users ?? { month: "2026-08", unreachable: false, unreadable: 0, people: [] },
  );
```

and add `users?: api.AdminUsers;` to `mockAll`'s parameter type. Add `hidden_users: []` to the `settings()` fixture (Task 6 may already have).

```ts
describe("People", () => {
  it("is mounted, directly above Spending", async () => {
    // A panel that nothing asserts is mounted has shipped invisible TWICE on
    // this project (ReportLinksPanel, the citation annotation). Deleting the
    // <PeoplePanel/> line must turn this red — verified by mutation.
    mockAll({ users: { month: "2026-08", unreachable: false, unreadable: 0, people: [
      { key: "dmoss", username: "dmoss", display_name: "Danielle Moss", name_source: "windows",
        first_seen: "", last_seen: "2026-08-25T09:00:00-07:00", hidden: false, spent_usd: 1,
        limit: { kind: "default", amount: null, collision: [] } },
    ] } });
    await renderAdmin();
    const people = screen.getByTestId("admin-people");
    const costs = screen.getByTestId("admin-costs");
    expect(people.compareDocumentPosition(costs) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(people).toHaveTextContent("Danielle Moss");
  });

  it("a limit set on a person's row lands in the save bar and the PUT", async () => {
    mockAll({ users: { month: "2026-08", unreachable: false, unreadable: 0, people: [
      { key: "gpaulsen", username: "gpaulsen", display_name: "Geoff Paulsen", name_source: "windows",
        first_seen: "", last_seen: "2026-08-25T09:00:00-07:00", hidden: false, spent_usd: 0,
        limit: { kind: "default", amount: null, collision: [] } },
    ] } });
    const save = vi.spyOn(api, "saveAdminSettings").mockImplementation(async (b) => ({ ...settings(), ...b } as api.AdminSettings));
    await renderAdmin();
    fireEvent.change(screen.getByRole("combobox", { name: /limit for Geoff Paulsen/i }), { target: { value: "exempt" } });
    expect(screen.getByTestId("admin-savebar")).toHaveTextContent(/who has no limit/);
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }));
    await screen.findByTestId("admin-saved");
    expect(save.mock.calls[0][0].exempt_users).toEqual([...settings().exempt_users, "gpaulsen"]);
    expect(save.mock.calls[0][0].user_limits).not.toHaveProperty("gpaulsen");
  });

  it("hiding someone is a settings save, not a separate request", async () => {
    mockAll({ users: { month: "2026-08", unreachable: false, unreadable: 0, people: [
      { key: "gpaulsen", username: "gpaulsen", display_name: "Geoff Paulsen", name_source: "windows",
        first_seen: "", last_seen: "2026-08-25T09:00:00-07:00", hidden: false, spent_usd: 0,
        limit: { kind: "default", amount: null, collision: [] } },
    ] } });
    const save = vi.spyOn(api, "saveAdminSettings").mockImplementation(async (b) => ({ ...settings(), ...b } as api.AdminSettings));
    await renderAdmin();
    fireEvent.click(screen.getByRole("button", { name: /Hide Geoff Paulsen/ }));
    expect(screen.getByTestId("admin-savebar")).toHaveTextContent(/who is hidden/);
    fireEvent.click(screen.getByRole("button", { name: /^Save/ }));
    await screen.findByTestId("admin-saved");
    expect(save.mock.calls[0][0].hidden_users).toEqual(["gpaulsen"]);
  });

  it("the Spending limits card no longer holds per-person rows", async () => {
    mockAll();
    await renderAdmin();
    open(/Spending limits/);
    expect(screen.queryByTestId("admin-user-limit")).toBeNull();
    expect(screen.queryByRole("button", { name: /Add a person/ })).toBeNull();
    expect(screen.queryByLabelText(/no limit, separated by commas/)).toBeNull();
    expect(screen.getByTestId("admin-limits")).toHaveTextContent(/under People/);
  });
});
```

(Check the save bar's real `data-testid` and the Save button's real accessible name in `SaveBar.tsx` and match them.)

- [ ] **Step 2: Run to verify they fail**

Run: `cd webapp && npx vitest run src/pages/Admin.test.tsx -t People`
Expected: 4 FAIL.

- [ ] **Step 3: Wire `Admin.tsx`**

Imports: add `import { PeoplePanel } from "../admin/PeoplePanel";`.

State (after `const [usage, setUsage] = …`):

```tsx
  const [people, setPeople] = useState<api.AdminUsers | null>(null);
  const [peopleError, setPeopleError] = useState<string | null>(null);
```

In the initial load's `Promise.all`, add `api.adminUsers(month)` as a seventh element and `setPeople(p)`; the People fetch is allowed to fail without taking the page down — wrap it like `loadModels`:

```tsx
        api.adminUsers(month).then((p) => !cancelled && setPeople(p))
          .catch((err) => !cancelled && setPeopleError(err instanceof Error ? err.message : String(err)));
```

(placed next to the `aiStatus`/`loadModels` calls rather than inside the `Promise.all`). In the month effect, refetch people beside usage:

```tsx
    api.adminUsers(month).then((p) => !cancelled && setPeople(p)).catch(() => {});
```

Limit-change handler (a page-level function, next to `discard`):

```tsx
  /** The People panel's dropdown writes to ONE of two settings fields and
   *  clears the other (spec U8): a person can never be in both, which is
   *  possible by hand today and resolved silently by `limit_for`. */
  function setPersonLimit(username: string, kind: api.PersonLimit["kind"], amount: number | null) {
    if (!draft) return;
    const user_limits = { ...draft.user_limits };
    // Every spelling of this person, not just the exact key — a legacy file
    // can hold DMOSS and dmoss, and choosing "office default" must clear both.
    for (const k of Object.keys(user_limits)) {
      if (k.trim().toLowerCase() === username.trim().toLowerCase()) delete user_limits[k];
    }
    const exempt_users = draft.exempt_users.filter(
      (u) => u.trim().toLowerCase() !== username.trim().toLowerCase(),
    );
    if (kind === "custom") user_limits[username] = amount ?? 0;
    if (kind === "exempt") exempt_users.push(username);
    setDraft({ ...draft, user_limits, exempt_users });
  }
```

Render — replace the untitled `<Group>` that holds `CostsPanel` with:

```tsx
        {/* People directly ABOVE Spending (mockup, 2026-08-25): its numbers
            are this month's spend, and it is where per-person limits live now
            that ProviderPanel only carries the office-wide default. */}
        <Group>
          <PeoplePanel
            people={people}
            loadError={peopleError}
            draft={draft}
            onLimitChange={setPersonLimit}
            onHiddenChange={(hidden_users) => setDraft({ ...draft, hidden_users })}
          />
        </Group>

        <Group>
          <CostsPanel … unchanged … />
        </Group>
```

Remove the `onUserLimitsChange` and `onExemptChange` props from the `<ProviderPanel …/>` call.

**The `.toLowerCase()` in `setPersonLimit` is the ONE client-side fold**, and it must match the server (`strip().casefold()`); JS has no casefold, `toLowerCase()` is the nearest — record that in the WHY comment and keep the server as the authority (the PeoplePanel row shows what the server resolved).

- [ ] **Step 4: Slim `ProviderPanel.tsx`**

Delete props `onUserLimitsChange`, `onExemptChange` (signature + type) and the `entries` / `setRow` helpers. In the "Spending limits" `CollapsibleCard`, delete everything from `{/* Flat, not nested. …` through the closing `</label>` of "People with no limit at all". Change the card's `hint` to:

```tsx
                hint={
                  settings.default_monthly_limit_usd === null
                    ? "nobody is capped"
                    : `$${settings.default_monthly_limit_usd} a month each`
                }
```

and change the office-default field's hint span to:

```tsx
                  <span className="adm-hint">
                    Blank means no limit. 0 blocks everyone. Set one person's own
                    limit, or no limit, under <strong>People</strong>.
                  </span>
```

Delete the specs in `Admin.test.tsx` that drove the removed rows (search for `admin-user-limit`, `Add a person`, `no limit, separated by commas`, `who has their own limit`, `who has no limit` — keep any that now exercise the People path instead).

- [ ] **Step 5: Run**

Run: `cd webapp && npx tsc -b && npx vitest run src/pages/Admin.test.tsx src/admin`
Expected: tsc 0, all PASS.

- [ ] **Step 6: Mutation — delete the `<PeoplePanel …/>` mount → "is mounted" spec RED; restore with `git checkout webapp/src/pages/Admin.tsx`.**

- [ ] **Step 7: Commit**

```bash
git add webapp/src/pages/Admin.tsx webapp/src/pages/Admin.test.tsx webapp/src/admin/ProviderPanel.tsx
git commit -m "admin: mount People above Spending; per-person limit rows leave ProviderPanel"
```

---

### Task 9: The hand-over picker (`AdvancedPanel.tsx`)

**Files:**
- Modify: `webapp/src/admin/AdvancedPanel.tsx:18-100`, `webapp/src/pages/Admin.tsx` (pass `people`)
- Test: `webapp/src/pages/Admin.test.tsx` (append)

**Interfaces:**
- `AdvancedPanel` gains prop `people: api.AdminUsers | null`.

- [ ] **Step 1: Write the failing tests**

```ts
describe("handing over admin", () => {
  const someone = (username: string, display_name: string, hidden = false): api.PersonRow => ({
    key: username, username, display_name, name_source: "windows", first_seen: "", last_seen: "",
    hidden, spent_usd: 0, limit: { kind: "default", amount: null, collision: [] },
  });

  it("offers a dropdown of people who have opened the app, minus hidden people and me", async () => {
    mockAll({ users: { month: "2026-08", unreachable: false, unreadable: 0, people: [
      someone("Destin", "Destin Jarrett"), someone("gpaulsen", "Geoff Paulsen"), someone("bjw2", ""), someone("pchen", "Pat Chen", true),
    ] } });
    await renderAdmin();
    open(/Who can open this page/);
    const picker = screen.getByRole("combobox", { name: /Hand admin to someone else/ });
    const labels = within(picker).getAllByRole("option").map((o) => o.textContent);
    expect(labels).toEqual(["Choose a person…", "Geoff Paulsen (gpaulsen)", "bjw2"]);
    expect(screen.queryByPlaceholderText(/their Windows username/)).toBeNull();
  });

  it("says nobody else has opened the app yet on day one — not an empty select, not a typed box", async () => {
    mockAll({ users: { month: "2026-08", unreachable: false, unreadable: 0, people: [someone("Destin", "Destin Jarrett")] } });
    await renderAdmin();
    open(/Who can open this page/);
    const picker = screen.getByRole("combobox", { name: /Hand admin to someone else/ });
    expect(picker).toBeDisabled();
    expect(picker).toHaveTextContent(/Nobody else has opened the app yet/);
    expect(screen.queryByPlaceholderText(/their Windows username/)).toBeNull();
    expect(screen.getByRole("button", { name: /Hand over admin/ })).toBeDisabled();
  });

  it("falls back to the typed box, with a reason, when the people list cannot be read", async () => {
    mockAll({ users: { month: "2026-08", unreachable: true, unreadable: 0, people: [] } });
    await renderAdmin();
    open(/Who can open this page/);
    expect(screen.getByTestId("admin-transfer")).toHaveTextContent(/couldn't be read from the shared folder/);
    expect(screen.getByPlaceholderText(/their Windows username/)).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /Hand admin to someone else/ })).toBeNull();
  });

  it("transfers to the picked username and confirms first", async () => {
    mockAll({ users: { month: "2026-08", unreachable: false, unreadable: 0, people: [someone("Destin", "D"), someone("gpaulsen", "Geoff Paulsen")] } });
    await renderAdmin();
    open(/Who can open this page/);
    fireEvent.change(screen.getByRole("combobox", { name: /Hand admin to someone else/ }), { target: { value: "gpaulsen" } });
    fireEvent.click(screen.getByRole("button", { name: /Hand over admin/ }));
    expect(screen.getByTestId("admin-transfer-confirm")).toHaveTextContent("Geoff Paulsen");
    fireEvent.click(screen.getByRole("button", { name: /Yes, hand over admin/ }));
    expect(screen.getByTestId("admin-savebar")).toHaveTextContent(/admin handed to gpaulsen/);
  });

  it("uses no bare link anywhere in the card", async () => {
    mockAll();
    await renderAdmin();
    open(/Who can open this page/);
    expect(screen.getByTestId("admin-transfer").querySelector(".adm-link")).toBeNull();
  });
});
```

- [ ] **Step 2: Run to verify they fail**

Run: `cd webapp && npx vitest run src/pages/Admin.test.tsx -t "handing over admin"`
Expected: 5 FAIL.

- [ ] **Step 3: Implement**

`AdvancedPanel` props: add `people: api.AdminUsers | null;`. Replace the `<label className="adm-field">…</label>` block (the typed box, lines ~55–71) with:

```tsx
        {/* A PICKER, not a typed box (spec U10/U11, Destin 2026-08-25). A
            typed username here was the single most dangerous typo in the
            product — one wrong letter locked both people out, recoverable
            only by hand-creating RESET-ADMIN.txt on the share. The picker
            offers people who have opened the app, minus hidden people and
            me. There is deliberately NO typed escape hatch in normal use: a
            successor opens the app once (thirty seconds) and appears here.
            The typed box returns ONLY when the people list itself cannot be
            read (spec U12) — an empty picker there would be a dead end. */}
        {people?.unreachable ? (
          <>
            <p className="adm-warn">
              The list of people couldn't be read from the shared folder, so
              you'll have to type the username. Their Settings page displays
              it. One wrong letter locks you both out.
            </p>
            <label className="adm-field">
              <span className="adm-label">Hand admin to someone else</span>
              <input
                type="text"
                value={next}
                placeholder="their Windows username"
                onChange={(e) => { setNext(e.target.value); setArmed(false); }}
              />
            </label>
          </>
        ) : (
          <label className="adm-field">
            <span className="adm-label">Hand admin to someone else</span>
            {candidates.length === 0 ? (
              <select disabled aria-label="Hand admin to someone else">
                <option>Nobody else has opened the app yet</option>
              </select>
            ) : (
              <select
                aria-label="Hand admin to someone else"
                value={next}
                onChange={(e) => { setNext(e.target.value); setArmed(false); }}
              >
                <option value="">Choose a person…</option>
                {candidates.map((p) => (
                  <option key={p.key} value={p.username}>
                    {p.display_name ? `${p.display_name} (${p.username})` : p.username}
                  </option>
                ))}
              </select>
            )}
            {candidates.length === 0 ? (
              <span className="adm-hint">Ask your successor to open the app once and they will appear here.</span>
            ) : null}
          </label>
        )}
```

with, above the `return`:

```tsx
  const candidates = (people?.people ?? []).filter(
    (p) => !p.hidden && p.username.trim().toLowerCase() !== me.user.trim().toLowerCase(),
  );
  const chosen = candidates.find((p) => p.username === next);
  const chosenLabel = chosen?.display_name ? chosen.display_name : next;
```

Use `chosenLabel` in the confirmation sentence (`Handing admin to <strong>{chosenLabel}</strong>`); `onTransfer(next.trim())` is unchanged. Replace the `Cancel` `adm-link` button with `className="adm-btn adm-btn-quiet"`. Delete the old "Ask them what Windows shows…" hint. In `Admin.tsx` pass `people={people}` to `<AdvancedPanel …/>`.

- [ ] **Step 4: Run**

Run: `cd webapp && npx tsc -b && npx vitest run src/pages/Admin.test.tsx`
Expected: PASS. Fix the two existing `admin-transfer` specs (`Admin.test.tsx:1178`, `:1187`) only if they typed into the box — they assert copy and the `RESET-ADMIN.txt` sentence, which is unchanged.

- [ ] **Step 5: Commit**

```bash
git add webapp/src/admin/AdvancedPanel.tsx webapp/src/pages/Admin.tsx webapp/src/pages/Admin.test.tsx
git commit -m "admin: hand-over is a picker of people who have opened the app; typed box only when the list can't be read"
```

---

### Task 10: No `adm-link` anywhere

**Files:**
- Modify: `webapp/src/admin/AliasesPanel.tsx:185`, `ProviderPanel.tsx:115,210,372`, `CorpusPanel.tsx:195`, `GuidancePanel.tsx:183`, `SaveBar.tsx:59`, `pages/Repair.tsx:114`; `webapp/src/styles/app.css` (delete `.adm-link`, add `.adm-savebar .adm-btn-quiet`)
- Test: `webapp/src/styles/no-bare-links.test.ts` (new)

- [ ] **Step 1: Write the failing test**

```ts
// webapp/src/styles/no-bare-links.test.ts
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// Destin, 2026-08-25: "i hate the bare blue hyperlink styling and that
// shouldn't be used anywhere. use real pills/buttons." Recorded twice
// (whole-report links 2026-08-16, the People mockup) — pinned once.
function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) walk(p, out);
    else if (/\.(tsx?|css)$/.test(name) && !/\.test\./.test(name)) out.push(p);
  }
  return out;
}

describe("no bare link styling", () => {
  it("adm-link appears nowhere in the source", () => {
    const offenders = walk(join(__dirname, "..")).filter((p) => readFileSync(p, "utf-8").includes("adm-link"));
    expect(offenders).toEqual([]);
  });
});
```

- [ ] **Step 2: Run to verify it fails**

Run: `cd webapp && npx vitest run src/styles/no-bare-links.test.ts`
Expected: FAIL listing 8 files + `app.css`.

- [ ] **Step 3: Replace every usage**

In each of the seven `.tsx` files, change `className="adm-link"` to `className="adm-btn adm-btn-quiet adm-btn-sm"`. In `SaveBar.tsx` (the Discard control on a navy bar) the quiet pill needs contrast: append to `app.css`

```css
/* Discard on the navy save bar: an outlined pill in the bar's own ink, not
   a bare link (Destin, 2026-08-25). */
.adm-savebar .adm-btn-quiet{background:transparent;color:#fff;border-color:#c9cbe6;}
```

Delete the `.adm-link{…}` rule and the `.adm-savebar .adm-link{…}` rule from `app.css`. Run `grep -rn "adm-link" webapp/src` — any spec asserting the class (e.g. `toHaveClass("adm-link")`) is re-pointed at `adm-btn`.

- [ ] **Step 4: Run**

Run: `cd webapp && npx tsc -b && npx vitest run && npm run build`
Expected: all green, exit 0.

- [ ] **Step 5: Render and LOOK** — start the server (`uv run uvicorn app.main:create_app --factory --port 9300`, after `npm run build`), open `/admin` in headless Chrome, screenshot the save bar with a pending change and the Aliases/Corpus/Guidance cards, and read the screenshots. A pill that landed inside a sentence and broke its line is the thing to catch here; fix spacing with `.adm-btn-sm` margins, not by restoring the link.

- [ ] **Step 6: Commit**

```bash
git add webapp/src webapp/src/styles/app.css
git commit -m "webapp: no adm-link anywhere — every action is a pill"
```

---

### Task 11: Gates, browser pass, STATUS

**Files:**
- Modify: `STATUS.md` (phase-summary row + section), `docs/superpowers/specs/2026-08-25-central-user-roster-design.md` (status line)

- [ ] **Step 1: Full suites**

Run: `uv run pytest -q` and `cd webapp && npx tsc -b && npx vitest run && npm run build`
Expected: pytest ≥ 3323 + the new files, 5 skipped; vitest all green; build exit 0. Record the counts.

- [ ] **Step 2: G-U1 — Layer 1 eval against a same-day CONTROL**

`ingest/` was touched (the resolver swap), which triggers the CLAUDE.md eval rule. On the main-repo checkout of `master` (unmodified), run `uv run python -m eval.run_eval`; then on the worktree run it again. Both need `JLBC_DATA_DIR` pointing at the dev corpus. Expected: **identical** recall@5 / @15 / @20 / refusal (last recorded 85.71 / 97.62 / 100 / 60). Commit both result files.

- [ ] **Step 3: G-U2 — executed, not asserted**

On the running dev server with `JLBC_USER=DMOSS`: open any page (the touch writes `users/dmoss.json`); as the admin, set a $25 limit on that row and Save; then in a Python shell:

```python
from harness.settings import load_settings, reset_settings_cache
from harness.ledger import check_limit
reset_settings_cache(); s = load_settings()
print(check_limit("dmoss", s).limit_usd, check_limit("DMOSS", s).limit_usd)   # 25.0 25.0
```

Then hand admin to that row from the picker, Save, and confirm `GET /api/me` with `JLBC_USER=dmoss` reports `is_admin: true`. Restore admin via `RESET-ADMIN.txt` afterwards — that also exercises the documented recovery.

- [ ] **Step 4: G-U3 — executed**

`chmod 000 <data_dir>/users`; reload `/admin`: the People panel shows the could-not-be-read sentence, the hand-over card shows the typed box with its reason. `chmod 755` back; reload: the table returns. Then on a scratch data dir with one person: the picker reads "Nobody else has opened the app yet", disabled.

- [ ] **Step 5: Browser pass against the mockup**

Screenshot `/admin` and compare to `people-panel.html`: the four columns, username under the name, the dropdown states, one Hide pill per row, the hidden line with Show, the slimmed Spending-limits card, the picker. Anything that differs from the approved page is a defect here, not a taste call.

- [ ] **Step 6: STATUS.md**

Add a phase-summary row and a section in the established shape (what shipped, measured before/after — number of roster rows created on first office day is unknowable here; record the gates, the deviations, and "⏸ Known residuals": the client-side `toLowerCase()` fold vs the server's `casefold()`; a name typed on two PCs before this shipped; `%USERNAME%` case drift now folds but the ledger still records each spelling; Risk 1 belongs in the handbook that does not yet exist). Flip the spec's status line to "SHIPPED <date>".

- [ ] **Step 7: Commit, merge, push**

```bash
git add STATUS.md docs/superpowers/specs/2026-08-25-central-user-roster-design.md eval/results/
git commit -m "status: central user roster shipped — gates G-U1..G-U3 executed"
git fetch origin && git rebase origin/master   # or merge, per CLAUDE.md — check master moved
# run the full suites again on the merged tree
git checkout master && git merge --no-ff user-roster && git push origin master
git worktree remove ~/ask-the-budget-az-worktrees/user-roster && git branch -d user-roster
```

---

## Self-review

**Spec coverage.** U0 → Tasks 1, 2, 5 (guard, folds, join). U1/U2 → Tasks 1, 3. U3/U4 → Task 4. U5/U6 → Tasks 3, 4. U7 → Tasks 2, 5, 7, 8 (settings field, route, panel, wiring). U8 → Tasks 7, 8. U10/U11/U12 → Task 9 (+ Task 5's `unreachable`, Task 7's panel state). U13 → Task 7. U14 → Task 5 (nothing rendered; test pins it). U15 → Task 5 (`require_admin`). U16 → untouched by design. Pills rule → Tasks 7, 9, 10. G-U0 passed; G-U1–G-U3 → Task 11. Invariant 7 → Task 2's `_fold` + Task 1's guard.

**Gaps found and closed while reviewing:** the `hidden` flag the panel renders must come from the DRAFT so a hide shows before save (Task 7 comment); the sort tie-break must not use `.casefold(` in `admin.py` (Task 5 note); `AdvancedPanel` needs `people` from `Admin.tsx` (Task 9 Step 3 last line).

**Type consistency.** `PersonLimit.kind` is `"default" | "custom" | "exempt"` in Task 5's JSON, Task 6's TS, Task 7's `LIMIT_OPTIONS` and Task 8's `setPersonLimit`. `registry.touch(username, *, windows_name, local_typed_name)` is called that way in Task 4. `same_person`/`fold` are imported from `users.whoami` in Tasks 2 and 5. `AdminUsers.people: PersonRow[]` matches the route's `"people"` key.

**Known softness, stated rather than hidden.** JS has no `casefold`; the two client-side folds (Task 8 `setPersonLimit`, Task 9 `candidates`) use `toLowerCase()`. For ASCII usernames — every Windows SAM name in this office — the two agree; the server remains the authority and the panel always renders what the server resolved.
