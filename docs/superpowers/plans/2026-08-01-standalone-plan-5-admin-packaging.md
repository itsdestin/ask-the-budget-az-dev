# Standalone Plan 5: Admin + Settings, Resilience, Packaging, Cleanup, Handoff Gates

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the app *handoff-survivable*. Everything Destin currently does by editing JSON on the share or running a command must become a button a non-technical admin can press; everything that silently breaks after he leaves must either be fixed or be visibly, plain-Englishly broken. Then package it so a colleague installs it from a zip with no admin rights, write the handbook that lets a non-technical successor operate *and extend* it, delete the retired architecture, and pass the two remaining acceptance gates.

**Architecture:** Four new backend seams — `app/identity.py` (who is this, are they the admin), `app/routes/admin.py` (settings/usage/catalog/corpus/backup APIs), `harness/catalog.py` (OpenRouter model catalog + recommendations + runtime fallback), `app/machine_config.py` (per-machine data-dir pointer, S18) — plus three new pages (`Admin.tsx`, `Help.tsx`, extended `Settings.tsx`), a launch health ladder that fails to a repair screen instead of a stack trace, a `packaging/` tree that produces the distributable zip, and a Markdown-sourced Administrator Handbook rendered into a JLBC-styled Word document that ships both in-app and beside the corpus on the share. Nothing in this plan changes retrieval, chunking, or the tool loop's behaviour.

**Tech Stack:** existing (FastAPI, React/Vite, LanceDB, fastembed) + `httpx` (already a dependency) for the catalog fetch. No new runtime dependencies. Packaging uses python.org's Windows **embeddable** distribution — not PyInstaller (S7).

**Spec:** `docs/superpowers/specs/2026-07-29-standalone-consolidation-design.md` — S7, S8, S11, S13, S15, S16, S17, S18, S19, Invariants 7 + 8, gates G2/G3. Plan 4's **"Task 8 amendments"** block is the as-shipped HTTP contract this plan extends.

**Work in a worktree:** `git worktree add ~/atb-worktrees/plan5 -b plan5 origin/master`

---

## Ground truth (READ FIRST — these are binding)

Facts established by shipped code and by the 2026-07-31 live runs. Getting any of these wrong produces a plausible-looking change that breaks something real.

1. **S22 and S23 already shipped** (merge `5e1ae3b`, 2026-07-31). Prompt caching and normalization-tolerant quote validation are DONE and are not in this plan. `harness/ledger.py` already records `cached_tokens`; the admin page must surface it (that number is the only way to tell whether caching still works — a broken cache prefix produces identical answers, identical tokens, identical logs, and a ~10× bill).
2. **A parallel session is fixing two 🔴 ingest defects** (worker auto-start, `make_doc_id` collisions) on branch `ingest-defects`. **Do not implement those here.** Rebase onto master before starting and check whether they landed; if they did not, they are the first thing to pick up, not a duplicate implementation.
3. **`harness/settings.py` is the single settings reader/writer.** `load_settings()` is mtime-cached, so an admin-page write is picked up by every running process without a restart. `save_settings()` is tmp-file + `os.replace`. Never write `settings.json` from anywhere else. `Settings` is `frozen=True` at the top level but its `tiers`/`user_limits` dicts are not deep-frozen and the dataclass is **unhashable** — do not put one in a set or use it as a cache key.
4. **`ai_available(settings, tier)` returns two exact reason strings** that UI code and tests match verbatim: `"no API key configured"` and `"no model configured — ask the admin"`. Adding a third failure mode means adding a string here, not inventing one at a call site.
5. **`TIER_COPY` in `app/routes/conversations.py` is the ONE source of analyst-facing tier copy** (S16), deliberately server-side so the admin page and the composer cannot drift. The admin page consumes `/api/ai/status`; it does not re-type the sentences.
6. **The ledger row shape is pinned**: `user`, `timestamp` (ISO 8601, Arizona-local, offset included), `tier`, `model`, `tokens_in`, `tokens_out`, `cost_usd`, `cached_tokens`. Month shards are JSONL under `<data_dir>/usage/`. `cost_usd` is `None` on a custom endpoint (S15) — `MonthUsage` deliberately **excludes** those rows from the dollar total and counts them in `rows_with_unknown_cost`. The admin page must render "at least $X (N calls of unknown cost)", never a total that quietly lies by omission.
7. **`check_limit()` already encodes all of S19's policy** — custom-endpoint inactivity, exempt list, per-user override, org default, `<= 0` meaning "block outright", the 80% warn boundary, and the exact blocked/warn wording. The admin page reads and writes the *config*; it must not re-implement the *resolution*.
8. **`UnicodeDecodeError` is a `ValueError`, not an `OSError`** — one mis-encoded byte in a month's shard once crashed the spend gate for every user. Any new ledger reader catches `(OSError, ValueError)`.
9. **`current_user()` reads `JLBC_USER` then the OS username.** It is not authentication and never will be (S11: "explicitly *not* real security — accepted trade"). Admin gating is a soft gate; say so in the code and in the UI, and never put anything behind it that would be harmful if bypassed.
10. **`store/config.data_dir()` is called from everywhere** and today resolves `JLBC_DATA_DIR` or the repo default. S18 inserts a per-machine pointer *below* the env var and *above* the default. LanceDB table handles and the search provider are resolved at startup, so a mid-session relocation cannot be made fully live — the repair flow ends in a restart, and the plan must say so rather than pretend otherwise.
11. **Route-registration order in `app/main.py` is load-bearing** — the `/{path:path}` SPA catch-all must stay registered last or it swallows every new `/api/` route.
12. **Deleting `db/` is not a one-directory delete.** These import it and must be deleted or ported in the same commit: `eval/synthesize_queries.py`, `eval/refresh_chunk_ids.py`, `retrieval/dense.py`, `retrieval/bm25.py`, `scripts/embed_corpus.py`, `scripts/load_slice.py`, `scripts/redownload_cached_pdfs.py`. `retrieval/pipeline.py` is **LIVE** — do not touch it.
13. **`setup.sh` installs and tests `mcp-server/` and `web/`.** Deleting those directories without editing `setup.sh` breaks the installer for the next person who clones. Delete code, tests, and installer steps in one commit.
14. **Capture `setup.sh --verify`'s exit code directly** (`bash setup.sh --verify > log 2>&1; echo $?`). Piping into `tail` returns `tail`'s status and hides failures.

---

## File structure

| File | Responsibility |
|---|---|
| Create `app/identity.py` | `current_user()` (moved from `conversations.py`), `is_admin(settings, user)`, admin-bootstrap rule, `claim_admin()` + the `RESET-ADMIN.txt` break-glass path; `GET /api/me` |
| Create `app/routes/admin.py` | All `/api/admin/*` endpoints: settings read/write, key test, model catalog, usage breakdown, corpus health, backups + restore |
| Create `harness/catalog.py` | OpenRouter `/api/v1/models` client, tool-calling filter, shipped recommendation list, offline degradation, runtime model fallback (S13) |
| Create `harness/notices.py` | Append-only `<data_dir>/notices.json` — model fallbacks, key failures, scraper breakage; the admin page's "what went wrong while you weren't looking" feed |
| Modify `harness/ledger.py` | Add `breakdown(month, *, by)` — aggregate ALL users' rows by user/model/tier; nothing else changes |
| Create `app/machine_config.py` | S18 per-machine pointer at `%LOCALAPPDATA%/JLBC-Insight/machine.json`; `resolve_data_dir()`, `set_data_dir(path)`, `validate_data_dir(path)` |
| Modify `store/config.py` | `data_dir()` consults `machine_config` between the env var and the repo default |
| Create `app/health.py` + modify `/health` | The launch ladder: server → machine config → share reachable → LanceDB readable → models present; each rung a plain-English sentence |
| Create `webapp/src/pages/Admin.tsx` (+ `admin/` subcomponents) | Costs, provider panel, tier model pickers, spend limits, corpus health + queue, restore, admin transfer, notices, log locations |
| Modify `webapp/src/pages/Settings.tsx` | Own monthly usage; AI Mode availability explainer; data-folder location |
| Create `webapp/src/pages/Repair.tsx` + `webapp/src/HealthGate.tsx` | S18 repair screen + the full-page failure states; wraps the router |
| Modify `webapp/src/components/Header.tsx` | Admin nav pill, rendered only when `/api/me` says so |
| Create `packaging/build_bundle.py` | Produces `dist/JLBC-Insight-<version>.zip`: embeddable Python + site-packages + models + `webapp/dist` + launcher |
| Create `packaging/launcher.pyw` + `packaging/install.cmd` | S8 launcher (port reuse, health wait, Chrome `--app` → Edge → default browser) + Start-Menu/Desktop shortcut creation |
| Create `packaging/README.md` | How to rebuild the bundle; what's in it; how to bump it |
| Create `docs/QUICKSTART.md` | The one-page G3 install sheet (includes setting a hard monthly credit cap on the OpenRouter dashboard) |
| Create `docs/HANDBOOK.md` | **Source of truth** for the Administrator Handbook — operation, cost model, the two AI tiers and why those models, confidentiality, and AI-assisted maintenance |
| Create `scripts/jlbc_memo.py` + `scripts/build_handbook.py` | JLBC Staff-Memorandum renderer (measured from the committed reference memo) + the handbook build |
| Create `webapp/src/pages/Help.tsx` | In-app handbook (everyone, not just the admin) + Word download |
| Committed `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` | The real FY 2027 Round 1 instructions memo — the styling fixture, vendored per CLAUDE.md so it survives a fresh clone |
| Create `scripts/verify_citations_sample.py` | G2: sample N chunks corpus-wide, assert page/bbox resolve against the real PDF |
| Create `store/documents.py` | Consolidate the four `documents.json` readers behind one loader |
| Delete | `web/`, `mcp-server/`, `db/`, `retrieval/api.py`, `retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py`, `eval/refresh_chunk_ids.py`, `scripts/embed_corpus.py`, `scripts/load_slice.py`, `scripts/redownload_cached_pdfs.py`, `tests/test_api.py`, and their `setup.sh` steps |
| Tests | `tests/test_identity.py`, `test_admin_settings_route.py`, `test_admin_usage_route.py`, `test_catalog.py`, `test_notices.py`, `test_machine_config.py`, `test_health_ladder.py`, `test_ledger_breakdown.py`, `test_packaging_manifest.py`, webapp `Admin.test.tsx`, `Settings.test.tsx`, `HealthGate.test.tsx` |

---

## API contracts (frozen — the webapp and any future tooling build against these)

```
GET  /api/me
  -> 200 { "user": str, "is_admin": bool, "admin_username": str,
           "admin_claimable": bool,      # no admin configured, OR a reset file is present
           "admin_reset_pending": bool } # a RESET-ADMIN.txt is waiting to be used up

POST /api/admin/claim
  body: { "confirm": true }
  -> 200 { "admin_username": str }
  -> 409 { "detail": "An admin is already configured. To reset it, see
                      'If nobody can get into Admin' in the handbook." }

GET  /api/admin/settings                 (403 for non-admin)
  -> 200 { "provider": { "provider": "openrouter"|"custom", "base_url": str,
                         "api_key_set": bool, "api_key_hint": str },   # NEVER the key
           "tiers": { "standard": {"model": str}, "deep_research": {"model": str} },
           "admin_username": str,
           "default_monthly_limit_usd": float|null,
           "user_limits": { username: float },
           "exempt_users": [str] }

PUT  /api/admin/settings                 (403 for non-admin)
  body: the same shape, plus "api_key": str | "__unchanged__"
  -> 200 (the GET shape, re-read from disk)
  -> 400 { "detail": "<plain sentence>" }   # validation failures, one per message

POST /api/admin/provider/test            (403 for non-admin)
  body: { "base_url": str, "api_key": str | "__unchanged__", "model": str }
  -> 200 { "ok": bool, "detail": str, "latency_ms": int|null }

GET  /api/admin/models?refresh=0|1        (403 for non-admin)
  -> 200 { "source": "live"|"cache"|"bundled", "fetched_at": str|null,
           "recommended": [ModelCard], "catalog": [ModelCard], "note": str|null }
  ModelCard = { id, name, context_length, prompt_usd_per_m, completion_usd_per_m,
                supports_tools: true, available: bool, tier_hint: "standard"|"deep_research"|null,
                blurb: str|null }

GET  /api/admin/usage?month=YYYY-MM       (403 for non-admin)
  -> 200 { "month": str, "total_usd": float, "rows": int,
           "rows_with_unknown_cost": int, "cached_tokens": int, "tokens_in": int,
           "by_user": [{key, cost_usd, tokens_in, tokens_out, cached_tokens, rows, rows_with_unknown_cost}],
           "by_model": [...same shape...], "by_tier": [...same shape...],
           "limits_active": bool, "limits_inactive_reason": str|null }

GET  /api/admin/corpus                    (403 for non-admin)
  -> 200 { "data_dir": str, "budget_chunks": int, "fiscal_note_chunks": int,
           "documents": int, "lancedb_bytes": int, "dead_version_bytes": int|null,
           "last_ingest_at": str|null, "queue": {queued, running, failed} }

GET  /api/admin/backups                   (403 for non-admin)
  -> 200 { "snapshots": [{ "name": str, "created_at": str, "bytes": int }] }
POST /api/admin/backups/{name}/restore    (403 for non-admin)
  body: { "confirm": "restore" }          # literal string; a mis-click cannot fire it
  -> 200 { "restored": str, "restart_required": true }
  -> 409 { "detail": "An ingest is running — wait for it to finish, then try again." }

GET  /api/admin/notices?since=<iso>       (403 for non-admin)
  -> 200 { "notices": [{ "at": str, "kind": str, "message": str }] }

GET  /api/me/usage
  -> 200 { "month": str, "month_usd": float|null, "limit_usd": float|null,
           "status": "allowed"|"warn"|"blocked", "message": str|null,
           "reason": str|null, "rows_with_unknown_cost": int }

GET  /api/health/detail                   (no auth — it is what renders when nothing works)
  -> 200 { "ok": bool,
           "rungs": [ { "name": "server"|"machine_config"|"share"|"corpus"|"models",
                        "ok": bool, "detail": str, "fix": str|null } ],
           "data_dir": str|null, "can_repair": bool }

POST /api/config/data-dir                 (no auth — the app is unusable when this fires)
  body: { "path": str }
  -> 200 { "path": str, "restart_required": true }
  -> 400 { "detail": "That folder doesn't contain a JLBC Insight corpus (no lancedb folder inside)." }

GET  /api/corpus/counts                   (public — the footer reads it)
  -> 200 { "documents": int, "budget_chunks": int, "fiscal_note_chunks": int }

GET  /api/handbook                        (public — everyone benefits from it)
  -> 200 the built .docx, Content-Disposition filename
         "JLBC Insight — Administrator Handbook.docx"
GET  /api/handbook/markdown               (public)
  -> 200 { "markdown": str, "built_at": str|null }
```

**Redaction is a hard rule, not a nicety.** `GET /api/admin/settings` never returns `api_key`. `PUT` accepts the literal sentinel `"__unchanged__"` so an admin editing spend limits cannot blank the key by round-tripping the form. Both properties get their own tests (Task 3, Steps 1–2) because both fail *silently* — a leaked key looks fine until it's in a screenshot, and a clobbered key looks like "AI Mode randomly stopped working".

---

## Sequencing

Tracks 1 and 2 are independent of Track 3 and can be built in parallel by two sessions. Track 4 (deletion) must come **after** Tracks 1–2 (it touches `setup.sh`, which they run) and **before** Track 3's bundle measurement (deleting `web/`+`mcp-server/` removes ~400 MB of `node_modules` from the tree the packager walks). Track 5 is last by construction.

| Track | Tasks | Owner |
|---|---|---|
| 1 — Admin & Settings | 1–9 | Session A |
| 2 — Resilience (S18 + ladder) | 10–13 | Session A (shares `app/` and `webapp/src/pages/`) |
| 3 — Packaging | 14–17 | Session B (owns `packaging/` only until Task 17) |
| 4 — Cleanup | 18–20 | After tracks 1–2 land |
| 5 — Handbook | 21–23 | Session C — **Task 21 can start immediately** (it only needs the committed reference memo); Tasks 22–23 need Tracks 1–2 finished, because Part 5 documents screens that must exist before they can be described accurately |
| 6 — Gates | 24–27 | Last, needs a finished bundle and a finished handbook |

**Parallel-execution contract:** Session A owns `app/`, `harness/`, `store/`, `webapp/src/`. Session B owns `packaging/` and `docs/QUICKSTART.md`. Session C owns `docs/HANDBOOK.md` and `scripts/jlbc_memo.py`/`scripts/build_handbook.py`; its Task 23 touches `app/routes/` and `webapp/src/`, so it lands **after** Session A finishes or coordinates directly with it. All three append to `STATUS.md` (own section, final task only); only Session A edits `setup.sh`. Session B must not edit application code — if the bundle needs an app change (it will: at minimum a `--data-dir` startup flag), Session B files it as a note and Session A makes the change.

**Write the handbook LAST among the docs, not first.** Its Part 5 describes admin screens screen-by-screen; written against a plan rather than a running app, it will describe buttons that ended up named something else — and a handbook that is wrong in its details teaches the reader not to trust it.

---

## Track 1 — Admin & Settings

### Task 1: Identity and the admin gate

**Files:** Create `app/identity.py`, `tests/test_identity.py`; Modify `app/routes/conversations.py` (import `current_user` from the new home, keep the old name working), `app/main.py` (register the route).

The bootstrap rule is the load-bearing decision here. A fresh install ships `settings.json` with `admin_username: ""`. If an empty admin meant "nobody is admin", the first install would have no path to configuring anything and the app would be permanently unusable. If it meant "everybody is admin", a share that never gets an admin assigned leaves every analyst able to rewrite the key. **Chosen rule: an empty `admin_username` is *claimable* — any user may claim it, once, and the claim is recorded in `settings.json`.** After that it is transfer-only — **plus the Task 13 break-glass reset, which is not optional.** A one-way door with no documented way back is exactly how a small office ends up with a permanently unconfigurable app and no vendor to call; build Task 13 in the same pass, not "later". This rule is discoverable, needs no out-of-band step in the quickstart, and matches how the office actually works (Destin sets it up, or the first person who opens the page does).

- [ ] **Step 1 — failing tests.** Write `tests/test_identity.py`:

```python
"""Who is this user, and are they the admin? (Plan 5 Task 1, spec S11.)"""
import pytest

from app.identity import current_user, is_admin, admin_claimable
from harness.settings import Settings


def test_current_user_prefers_env(monkeypatch):
    monkeypatch.setenv("JLBC_USER", "analyst1")
    assert current_user() == "analyst1"


def test_admin_matches_exact_username():
    s = Settings(admin_username="Destin")
    assert is_admin(s, "Destin") is True
    # Exact match, no case folding — same rule as Settings.limit_for. Folding
    # here would silently merge two distinct config rows an admin typed.
    assert is_admin(s, "destin") is False


def test_unclaimed_admin_is_claimable_and_grants_access():
    s = Settings(admin_username="")
    assert admin_claimable(s) is True
    # WHY anyone is admin while unclaimed: a fresh install has no other path
    # to configuring the app. The claim is one-way and recorded.
    assert is_admin(s, "whoever") is True


def test_claimed_admin_is_not_claimable_by_others():
    s = Settings(admin_username="Destin")
    assert admin_claimable(s) is False
    assert is_admin(s, "someone-else") is False
```

- [ ] **Step 2 — implement `app/identity.py`.** Move `USER_ENV_VAR`/`current_user()` verbatim from `conversations.py`, re-import it there so nothing else changes, and add:

```python
def is_admin(settings: Settings, user: str) -> bool:
    """Soft gate (S11) — NOT authentication.

    `current_user()` is the OS username, which any user can override with
    JLBC_USER. This gate exists so the admin page isn't advertised
    office-wide and so individual spend isn't casually browsable, NOT to
    defend against someone determined. Nothing may sit behind it that
    would be harmful if bypassed: the OpenRouter key is spend-capped at
    the provider (S19), and the destructive action here (restore) is
    reversible because it snapshots first.
    """
    if not settings.admin_username:
        return True  # unclaimed — see admin_claimable
    return user == settings.admin_username
```

- [ ] **Step 3 — `GET /api/me`** in `app/routes/admin.py` (created here, filled out in later tasks). Register it in `app/main.py` **above** the SPA catch-all.
- [ ] **Step 4** — `.venv/bin/python -m pytest tests/test_identity.py tests/test_harness_settings.py -q` → all pass.
- [ ] Commit: `feat(app): identity + soft admin gate with one-way bootstrap claim`

### Task 2: Ledger breakdown across users

**Files:** Modify `harness/ledger.py`; Create `tests/test_ledger_breakdown.py`.

- [ ] **Step 1 — failing test.** Assert that `breakdown()` (a) groups by the requested key, (b) sums `cost_usd` **excluding** `None`-cost rows while counting them in `rows_with_unknown_cost`, (c) sums `cached_tokens` treating a pre-S22 row with no key as 0, (d) survives a shard containing one undecodable byte, returning the readable rows:

```python
def test_breakdown_excludes_unknown_cost_from_dollars(tmp_data_dir):
    _write_rows(tmp_data_dir, "2026-07", [
        {"user": "a", "tier": "standard", "model": "m1", "tokens_in": 10,
         "tokens_out": 5, "cost_usd": 0.10, "cached_tokens": 8},
        {"user": "a", "tier": "standard", "model": "m1", "tokens_in": 10,
         "tokens_out": 5, "cost_usd": None},          # custom endpoint (S15)
        {"user": "b", "tier": "deep_research", "model": "m2", "tokens_in": 1,
         "tokens_out": 1, "cost_usd": 0.20},          # no cached_tokens key (pre-S22)
    ])
    by_user = {g.key: g for g in breakdown("2026-07", by="user")}
    assert by_user["a"].cost_usd == 0.10
    assert by_user["a"].rows_with_unknown_cost == 1
    assert by_user["a"].cached_tokens == 8
    assert by_user["b"].cached_tokens == 0   # absent key reads as 0, not corrupt
```

- [ ] **Step 2 — implement.** Reuse the existing `_read_rows()` (it already drops corrupt rows and catches `(OSError, ValueError)` — do not write a second reader). Return a list of a new frozen `UsageGroup` dataclass sorted by `cost_usd` descending. Round to whole cents with the same helper `month_total` uses so the two can never disagree.
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_ledger_breakdown.py tests/test_harness_ledger.py -q`
- [ ] Commit: `feat(harness): ledger breakdown by user/model/tier for the admin page`

### Task 3: Admin settings read/write (redaction + validation)

**Files:** Modify `app/routes/admin.py`; Create `tests/test_admin_settings_route.py`.

- [ ] **Step 1 — failing tests, redaction first.** These two are the reason this task exists:

```python
def test_get_never_returns_the_api_key(admin_client, settings_with_key):
    body = admin_client.get("/api/admin/settings").json()
    assert "api_key" not in body["provider"]
    assert body["provider"]["api_key_set"] is True
    assert body["provider"]["api_key_hint"] == "…cdef"     # last 4 only
    assert "sk-or-v1" not in admin_client.get("/api/admin/settings").text


def test_put_with_sentinel_preserves_the_existing_key(admin_client, settings_with_key):
    # The failure this prevents: an admin edits a spend limit, the form
    # round-trips a blank key, and AI Mode dies office-wide with no error
    # that points at what happened.
    admin_client.put("/api/admin/settings", json={
        **base_body, "api_key": "__unchanged__", "default_monthly_limit_usd": 25.0,
    })
    assert load_settings().provider.api_key == "sk-or-v1-abcdef"
```

- [ ] **Step 2 — more failing tests: validation and lockout.** Each returns 400 with one plain sentence:
  - a tier model that is not in the live catalog **and** not a syntactically plausible `vendor/model` id → `"That model id doesn't look right — pick one from the list, or check the spelling."`
  - `default_monthly_limit_usd` negative → `"A monthly limit can't be negative. Leave it blank for no limit, or enter 0 to block a user entirely."`
  - a `user_limits` key that is empty/whitespace → rejected (an empty username silently applies to nobody)
  - **admin transfer to a different username requires `"confirm_admin_transfer": true`** and the response says plainly that the current admin will lose access. A transfer to an empty string is rejected outright — that would un-claim the install and hand admin to everyone.
- [ ] **Step 3 — failing test: 403 for non-admin** on GET, PUT, and every other `/api/admin/*` route, driven by a `JLBC_USER` that isn't the admin. Parametrize over the route table so a future route added without a gate fails this test.
- [ ] **Step 4 — implement.** Read via `load_settings()`, write via `save_settings()`. Never construct `Settings` field-by-field from the request body — start from the loaded settings and replace only supplied fields, so a client on an older shape cannot blank a field it doesn't know about.
- [ ] **Step 5** — `.venv/bin/python -m pytest tests/test_admin_settings_route.py -q`
- [ ] Commit: `feat(app): admin settings API — redacted reads, sentinel-preserving writes, lockout guards`

### Task 4: OpenRouter model catalog + recommendations (S13)

**Files:** Create `harness/catalog.py`, `tests/test_catalog.py`; Modify `app/routes/admin.py`.

- [ ] **Step 1 — failing tests** against a fixture payload (capture one real `/api/v1/models` response into `tests/fixtures/openrouter_models.json`; do not hit the network in tests):
  - models whose `supported_parameters` lacks `"tools"` are excluded — the harness *requires* function calling, and a non-tool model doesn't degrade, it fails every turn
  - the shipped recommendation list is returned even with **no network**, marked `source: "bundled"`, with `available: false` on anything the catalog couldn't confirm — offline-first (S7)
  - a recommendation that has vanished from the live catalog is returned with `available: false`, not dropped (the admin needs to see *why* their configured model stopped working)
  - prices are converted from OpenRouter's per-token strings to `usd_per_m` floats, and a malformed price yields `None` rather than an exception
- [ ] **Step 2 — implement `harness/catalog.py`.** `fetch_catalog(settings, *, refresh=False)` with a 6-hour on-disk cache at `<data_dir>/model-catalog.json`; `httpx` timeout 10s; any failure returns the bundled list with a `note`. The bundled `RECOMMENDATIONS` list holds ~4 entries per tier with analyst-readable blurbs and a `tier_hint`; **it is the fallback order for Task 5.** Ship-time entries follow S16's guidance (Deep Research = cost-effective frontier-class open model; Standard = best opus-level-performance-per-dollar open model) and are re-checked against live pricing when the admin page opens — do not hardcode prices.
- [ ] **Step 3** — `GET /api/admin/models`. `refresh=1` bypasses the cache.
- [ ] **Step 4** — `.venv/bin/python -m pytest tests/test_catalog.py -q`
- [ ] Commit: `feat(harness): OpenRouter catalog client, tool-calling filter, bundled fallback list`

### Task 5: Runtime model fallback + notices (S13)

**Files:** Create `harness/notices.py`, `tests/test_notices.py`; Modify `harness/session.py` (fallback only), `app/routes/admin.py`.

S13 requires that a deprecated or failing model degrade AI Mode to a *different model*, never to a dead feature. The trap is where the fallback is recorded.

- [ ] **Step 1 — failing test: the fallback is a per-process runtime override, NOT a settings write.**

```python
def test_model_fallback_does_not_rewrite_settings(session_with_dead_model, tmp_path):
    before = settings_path().read_bytes()
    reply = session_with_dead_model.run("hello")
    assert reply.model_used == FALLBACK_MODEL           # it answered
    assert settings_path().read_bytes() == before        # WHY: three office
    # machines hitting the same dead model would otherwise stage three
    # concurrent writes to one settings.json on an SMB share, and the last
    # writer wins over whatever the admin was editing at the time.
    assert any(n["kind"] == "model_fallback" for n in read_notices())
```

- [ ] **Step 2 — implement `harness/notices.py`.** Append-only JSONL at `<data_dir>/notices.json`, same `_append_line` discipline as the ledger (it already handles the SMB append lock), capped read of the most recent 200. Kinds: `model_fallback`, `key_rejected`, `scraper_failed`, `ingest_failed`.
- [ ] **Step 3 — implement the fallback** in the session's call path: on a model-not-found / model-deprecated / 404-from-provider error, walk that tier's `RECOMMENDATIONS` order, record one notice per distinct model transition (not per call — a dead model would otherwise write a notice every turn, all day), and continue. On a custom endpoint (S15) there is no recommendation order, so the error surfaces in-chat unchanged.
- [ ] **Step 4** — `.venv/bin/python -m pytest tests/test_notices.py tests/test_harness_session.py -q`
- [ ] Commit: `feat(harness): S13 model fallback with persisted notices, no settings write`

### Task 6: Corpus health, backups, restore (S17)

**Files:** Modify `app/routes/admin.py`; Create `tests/test_admin_corpus_route.py`.

- [ ] **Step 1 — failing tests:**
  - `GET /api/admin/corpus` reports real counts and reports the LanceDB **dead-version bytes** (see Task 20 — this is currently 5.1 GB on disk for ~18k chunks and is the single most visible corpus-health number)
  - `POST .../restore` without `{"confirm": "restore"}` → 400, corpus untouched
  - `POST .../restore` while `IngestLock` is held → **409 with the plain sentence**, corpus untouched. This is the one that matters: restoring under a live writer would interleave a zip extraction with a LanceDB commit.
  - a successful restore takes the ingest lock, snapshots the *current* corpus first (so a mistaken restore is itself reversible), then extracts
- [ ] **Step 2 — implement**, reusing `store/backup.py`'s `list_snapshots()` / `snapshot()` / `restore()` verbatim. Do not add a second snapshot implementation.
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_admin_corpus_route.py tests/test_store_backup.py -q`
- [ ] Commit: `feat(app): corpus health + guarded one-click restore`

### Task 7: Usage endpoints

**Files:** Modify `app/routes/admin.py`; Create `tests/test_admin_usage_route.py`.

- [ ] **Step 1 — failing tests:** `/api/admin/usage` returns all three breakdowns for the requested month (default: current Arizona-local month); on a custom endpoint it sets `limits_active: false` with `limits_inactive_reason` taken from `check_limit`'s `reason` field, **not** re-derived; `/api/me/usage` returns only the calling user's own numbers and is not admin-gated.
- [ ] **Step 2 — implement** using Task 2's `breakdown()` and the existing `check_limit()`.
- [ ] **Step 3** — pytest as above.
- [ ] Commit: `feat(app): admin usage breakdown + per-user usage endpoint`

### Task 8: Admin page UI

**Files:** Create `webapp/src/pages/Admin.tsx` + `webapp/src/admin/*.tsx`; Modify `webapp/src/api.ts`, `App.tsx`, `Header.tsx`, `styles/app.css` (one labeled `page-admin` block); Create `webapp/src/pages/Admin.test.tsx`.

Panels, in the order a new admin needs them: **Costs** (this month's total with the honest "at least $X (N calls of unknown cost)" wording, per-user / per-model / per-tier tables, and the `cached_tokens` share rendered as "prompt caching: N% of input tokens served from cache" — the one number that reveals a silently broken cache prefix) → **AI Mode setup** (provider panel, key add/replace/test, tier model pickers) → **Spend limits** → **Corpus** (counts, queue, snapshots + restore) → **Notices** → **Admin transfer** → **Where things live** (data dir, logs, `settings.json`, the OpenRouter dashboard link).

- [ ] **Step 1 — failing vitest specs.** The ones that pin real requirements:
  - the key field renders as empty with the hint `…cdef` next to it, and submitting the form without touching it sends `"__unchanged__"`
  - selecting **Custom endpoint** renders the S15 caveats *in the panel* — per-user costs degrade to token counts, no catalog/recommendations/live pricing, the model must support tool calling, self-support territory — and one click returns to OpenRouter
  - tier pickers render `/api/ai/status`'s `description` text verbatim; the test asserts against the string fetched from the API, **not** a copy typed into the test, so a spec-copy edit can't drift
  - a model with `available: false` renders greyed with "no longer offered by OpenRouter" and is not selectable
  - the restore button requires a typed confirmation and shows the snapshot's date in the confirm text
- [ ] **Step 2 — implement.** Follow the shipped webapp conventions verbatim: page class + `data-testid` on `<main>`, page-scoped CSS in a labeled `app.css` block, all calls through `api.ts` with the page importing `* as api`.
- [ ] **Step 3 — nav gating.** The Admin pill renders only when `/api/me` returns `is_admin`. When `admin_claimable`, every user sees a one-time "No admin is set up yet — claim it?" banner on Settings.
- [ ] **Step 4** — `cd webapp && npx vitest run` → green.
- [ ] Commit: `feat(webapp): admin page — costs, provider, tiers, limits, corpus, restore`

### Task 9: Settings page for everyone

**Files:** Modify `webapp/src/pages/Settings.tsx`, `Settings.test.tsx`.

- [ ] **Step 1 — failing specs:** own monthly usage with the limit and a progress bar; at `warn`/`blocked`, the ledger's exact message string (not a re-typed one); when AI Mode is unavailable, the server's own `reason` sentence; the data-folder path; the Invariant 8 public-record reminder.
- [ ] **Step 2 — implement.** No new endpoints — `/api/me`, `/api/me/usage`, `/api/ai/status`.
- [ ] **Step 3** — vitest green.
- [ ] Commit: `feat(webapp): settings page — own usage, AI availability, data location`

---

## Track 2 — Resilience

### Task 10: Per-machine config + data-dir resolution (S18)

**Files:** Create `app/machine_config.py`, `tests/test_machine_config.py`; Modify `store/config.py`.

- [ ] **Step 1 — failing tests:**
  - resolution order is `JLBC_DATA_DIR` env > `machine.json` > repo default, and a test pins all three precedences (an env var set for a backfill must keep winning — the Z13 depends on it)
  - `validate_data_dir()` accepts a folder containing `lancedb/`, rejects one without it with the exact sentence from the contract, and rejects a path that isn't a directory
  - a corrupt/unreadable `machine.json` falls back to the default **and prints why** — never raises, because this file being broken is exactly when the app must still boot far enough to show a repair screen
- [ ] **Step 2 — implement.** `%LOCALAPPDATA%/JLBC-Insight/machine.json` on Windows, `~/.config/jlbc-insight/machine.json` elsewhere (dev machines are Linux). Same tmp+`os.replace` write discipline as `save_settings`.
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_machine_config.py tests/test_store_config.py -q`
- [ ] Commit: `feat(app): S18 per-machine data-dir pointer below the env override`

### Task 11: Health ladder

**Files:** Create `app/health.py`, `tests/test_health_ladder.py`; Modify `app/main.py`.

Rungs, each with a plain-English `detail` and an actionable `fix`: **server** (always ok if you got a response) → **machine_config** (readable) → **share** (the data dir exists and is readable) → **corpus** (`budget_chunks` opens and reports a count) → **models** (the ONNX model files are present locally; on a bundle they are pre-bundled, so "missing" means a broken install, not a download that hasn't happened).

- [ ] **Step 1 — failing tests:** each rung fails independently with its own sentence; the ladder **short-circuits** (an unreachable share does not then report "corpus: broken" as a second scary line, which would send an admin chasing the wrong thing); `can_repair` is true exactly when the share rung is the first failure; `GET /health`'s existing `{ok, provider}` shape is unchanged (Plan 2 tests and the backfill scripts depend on it).
- [ ] **Step 2 — implement.**
- [ ] **Step 3** — `.venv/bin/python -m pytest tests/test_health_ladder.py tests/test_app_server.py -q`
- [ ] Commit: `feat(app): launch health ladder with short-circuiting plain-English rungs`

### Task 12: Repair screen + health gate UI

**Files:** Create `webapp/src/HealthGate.tsx`, `webapp/src/pages/Repair.tsx`, tests; Modify `App.tsx`.

- [ ] **Step 1 — failing specs:** a failing rung renders full-page with the sentence and the fix, and **no stack trace or JSON**; when `can_repair`, the repair screen offers a path entry that calls `POST /api/config/data-dir` and, on success, tells the user plainly that the app must be restarted and how (close the window and reopen it from the Start Menu); a healthy ladder renders the app with no flash of the gate.
- [ ] **Step 2 — implement.** The gate is a wrapper around the router, not a route — a broken share must not depend on client-side routing working.
- [ ] **Step 3** — vitest green.
- [ ] Commit: `feat(webapp): health gate + S18 repair screen`

**Honest limitation to encode in the copy (do not soften):** a relocation cannot take effect mid-session. LanceDB handles and the search provider resolve at startup (Ground truth 10). The screen says "Restart JLBC Insight to finish" and the launcher makes that one double-click. Pretending otherwise would produce an app that says it's fixed and then serves errors from stale handles.

### Task 13: Admin lockout recovery — break-glass reset

**Files:** Modify `app/identity.py`, `harness/settings.py`; Create `tests/test_admin_lockout_recovery.py`.

**Why this exists.** Task 1 makes `admin_username` a one-way claim, which is right — but every one-way door needs a documented way back through. The realistic lockout scenarios are mundane and all of them are *permanent* without a recovery path: the admin transfers to a mistyped username (`destin` vs `Destin` — Ground truth: matching is exact, and deliberately so); the admin leaves and IT deletes the Windows account; IT changes the username format office-wide; someone hand-edits `settings.json` and breaks it. In every case the result is an app nobody can configure, on a share nobody can fix, with no error message that explains what happened. There is no vendor to call.

**Three tiers, escalating. All three get documented in the handbook (Task 22, Part 7).**

**Tier 1 — transfer from inside the app.** Already built (Task 3). The normal path.

**Tier 2 — the break-glass reset file. This is the primary recovery, and it requires no JSON editing.** Create an empty file named `RESET-ADMIN.txt` in the shared data folder. The app then treats admin as unclaimed, and the next person to open the Admin page claims it.

Chosen over an environment variable or a CLI flag because it is the only mechanism a non-technical person can execute on a locked-down Windows PC with nothing but File Explorer — right-click → New → Text Document, rename. **It grants no new power:** anyone who can create that file can already open `settings.json` in Notepad and edit it directly, so this adds convenience, not access. Say exactly that in the code comment, so nobody later "hardens" it into uselessness.

**Tier 3 — edit `settings.json` directly.** Documented as the last resort, with the exact file contents to type if the file is beyond repair.

- [ ] **Step 1 — failing tests:**

```python
def test_reset_file_unclaims_a_configured_admin(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    assert admin_claimable(load_settings()) is False
    (tmp_data_dir / "RESET-ADMIN.txt").touch()
    assert admin_claimable(load_settings()) is True
    assert is_admin(load_settings(), "anyone") is True


def test_claiming_consumes_the_reset_file_and_leaves_a_record(tmp_data_dir):
    save_settings(Settings(admin_username="Destin"))
    (tmp_data_dir / "RESET-ADMIN.txt").touch()
    claim_admin("Jen")
    # RENAMED, not deleted: the file is the only evidence that an admin
    # takeover happened out-of-band, and silently deleting it would erase
    # the one trace anyone could audit later.
    assert not (tmp_data_dir / "RESET-ADMIN.txt").exists()
    assert list(tmp_data_dir.glob("RESET-ADMIN.done-*.txt"))
    assert load_settings().admin_username == "Jen"
    assert any(n["kind"] == "admin_claimed" for n in read_notices())


def test_readonly_share_still_allows_the_claim(tmp_data_dir, readonly):
    # A share that has gone read-only must not turn a recoverable lockout
    # into a permanent one. The claim proceeds; the failure to consume the
    # file is logged loudly rather than raised.
    ...


def test_corrupt_settings_fails_open_and_preserves_the_original(tmp_data_dir):
    settings_path().write_text("{ this is not json")
    assert admin_claimable(load_settings()) is True     # fail OPEN, not locked
    claim_admin("Jen")
    # The corrupt bytes may still contain a recoverable API key. Overwriting
    # them without a copy would destroy the ONLY path back to it — the app's
    # own fail-open behaviour would eat the evidence.
    preserved = list(tmp_data_dir.glob("settings.json.corrupt-*"))
    assert preserved and "not json" in preserved[0].read_text()
```

- [ ] **Step 2 — implement.** `RESET_FILENAME = "RESET-ADMIN.txt"`; `admin_claimable()` returns true when `admin_username` is empty **or** the reset file exists; `claim_admin(user)` writes the username, consumes the reset file by renaming it with a UTC timestamp, and records an `admin_claimed` notice (Task 5's `harness/notices.py`). In `harness/settings.py`, `save_settings()` copies a **corrupt** existing file to `settings.json.corrupt-<timestamp>` before replacing it — never overwriting an existing preserved copy.
- [ ] **Step 3 — surface it in the UI.** When the reset file is present, the Admin page's claim banner says so explicitly ("An admin reset file is present in the data folder — claiming admin now will use it up"), so nobody claims by accident and then wonders where their reset went.
- [ ] **Step 4** — `.venv/bin/python -m pytest tests/test_admin_lockout_recovery.py tests/test_identity.py tests/test_harness_settings.py -q`
- [ ] Commit: `feat(app): break-glass admin reset + corrupt-settings preservation`

---

## Track 3 — Packaging (S7/S8) — **the highest-risk work in this plan**

Nobody has built this bundle or run it on a locked-down JLBC machine. MinerU's dependency tree (torch CPU + its own model weights) is the hard part, and everything else in this plan is worthless if the app can't be installed. **Do Task 14 first and report its number before building anything else in this track.**

### Task 14: Bundle feasibility spike — measure before building

**Files:** Create `packaging/measure.py`, `docs/superpowers/investigations/2026-08-01-bundle-size.md`.

- [ ] **Step 1** — resolve the full dependency closure into a clean throwaway venv on Windows (or a Windows VM), then measure: total bytes, per-package top 20, model-weight bytes (fastembed's two ONNX models + MinerU's), and `webapp/dist`.
- [ ] **Step 2** — measure the same closure **without** `mineru[pipeline]`.
- [ ] **Step 3 — decision point, recorded in the investigation doc.** Expect roughly 3–6 GB with MinerU and well under 1 GB without it. If the full bundle is impractical (share/USB copy time, per-machine disk, IT pushback), the documented fallback is a **split distribution**:
  - **Full bundle** (search + AI Mode + ingest) on one or two designated machines
  - **Client bundle** (search + AI Mode, no MinerU) everywhere else — uploads from a client machine still queue onto the share; the designated machine's worker drains them
  
  This is not a compromise invented to dodge the problem: an i5-1245U runs MinerU at 1–3 min/page, so a 210-page book is an overnight job on any office PC regardless. Concentrating ingest matches how the office will actually use it. It does, however, **depend on the worker auto-start fix** (Ground truth 2) — without it a queued job on machine B never gets picked up by machine A. Note that dependency explicitly in the doc.
- [ ] Commit: `docs(investigation): bundle size measurement + split-distribution decision`

### Task 15: Bundle builder

**Files:** Create `packaging/build_bundle.py`, `packaging/README.md`, `tests/test_packaging_manifest.py`.

- [ ] **Step 1 — failing test** on the manifest, which can run on Linux without building anything: the manifest lists every file the launcher needs (`python.exe`/`pythonw.exe`, `site-packages`, `webapp/dist/index.html`, both ONNX model dirs, `launcher.pyw`, `install.cmd`, `QUICKSTART.md`); it contains **no** `.env`, no `settings.json`, no `data/insight-data/`, no `.git`; and — the one that protects Invariant 8 — no PDFs or corpus content.
- [ ] **Step 2 — implement.** Download python.org's embeddable zip, `pip install --target` the closure, copy `webapp/dist`, pre-download the fastembed models into the bundle's cache path and pin `JLBC_MINERU_*`/fastembed cache env vars in the launcher so **first run downloads nothing** (S7), write `VERSION`, zip it.
- [ ] **Step 3** — build on Windows; unzip to a fresh `%LOCALAPPDATA%` on a machine that has never had Python; confirm the server starts with the network cable unplugged. **That offline start is the acceptance criterion**, not a successful build.
- [ ] Commit: `feat(packaging): bundle builder — embeddable Python, pre-bundled models, offline first run`

### Task 16: Launcher (S8)

**Files:** Create `packaging/launcher.pyw`, `packaging/install.cmd`.

Chosen shape, and why: **`pythonw.exe launcher.pyw`, invoked from a shortcut that `install.cmd` creates** — no compiler, no toolchain, no console window, and it's ordinary Python that the next maintainer can read. A compiled `.exe` would need a build toolchain nobody will have.

- [ ] **Step 1 — implement `launcher.pyw`:**
  1. read the port from `<localappdata>/JLBC-Insight/running.json`; if a server is already answering `/health` there, **skip starting one** and go straight to opening the browser (S8: relaunch reuses the running instance)
  2. otherwise bind a free port, start uvicorn in-process, write `running.json`
  3. poll `/health` for up to 60s; on timeout show a message box naming the log file — never a traceback
  4. open the UI: `chrome.exe --app=http://127.0.0.1:<port>` → Edge `--app=` → `os.startfile` default browser. Chrome paths probed in order (`%ProgramFiles%`, `%ProgramFiles(x86)%`, `%LOCALAPPDATA%`), because JLBC machines vary
  5. the server keeps running when the window closes (S8)
- [ ] **Step 2 — `install.cmd`:** create Start Menu + Desktop shortcuts to `pythonw.exe launcher.pyw`, prompt once for the shared-data folder and write it via Task 10's machine config, print the data folder and log location. No admin rights, no PATH edits, no registry writes.
- [ ] **Step 3 — manual verification on Windows:** double-click twice, confirm exactly one server and two windows; close both windows, confirm the server survives; kill the server, relaunch, confirm recovery.
- [ ] Commit: `feat(packaging): launcher + installer — Chrome app mode, instance reuse, no admin rights`

### Task 17: Server-side support for the bundle

**Files:** Modify `app/main.py` (a `--data-dir` startup override that writes machine config), `packaging/README.md`.

- [ ] Small and last in this track, because Task 14 may change what's needed. Whatever the launcher turned out to require, land it here with tests.
- [ ] Commit: `feat(app): startup data-dir override for the packaged launcher`

---

## Track 4 — Cleanup

### Task 18: Delete the retired architecture

**Files:** Delete `web/`, `mcp-server/`, `db/`, `retrieval/api.py`, `retrieval/bm25.py`, `retrieval/dense.py`, `retrieval/rerank.py`, `eval/refresh_chunk_ids.py`, `scripts/embed_corpus.py`, `scripts/load_slice.py`, `scripts/redownload_cached_pdfs.py`, `tests/test_api.py`; Modify `setup.sh`, `eval/synthesize_queries.py`, `eval/README.md`, `eval/calibrate_refusal.py`, `README.md`, `CLAUDE.md`.

- [ ] **Step 1 — port `eval/synthesize_queries.py`** off Postgres first (one import swap: `db.connection.get_connection` → `store.chunk_store.ChunkStore`). It is the only deleted-dependency script worth keeping — eval-set expansion is a live Phase 3 need, and Phase D of the backfill may want it.
- [ ] **Step 2 — delete**, in one commit per concern so the diff is reviewable: (a) `mcp-server/` + `web/` + their `setup.sh` install/build/test steps, (b) `db/` + the Postgres-era scripts + `eval/refresh_chunk_ids.py`, (c) the dead `retrieval/` modules + `tests/test_api.py`.
- [ ] **Step 3 — fix the stale operator docs** flagged in STATUS: `eval/calibrate_refusal.py` and `eval/README.md` still tell operators to edit `mcp-server/system-prompt.md`; the threshold lives in `harness/constants.py`. `db/migrations/0001`'s doc_type enum comment dies with `db/`.
- [ ] **Step 4** — `bash setup.sh --verify > /tmp/verify.log 2>&1; echo $?` → 0, from a **fresh clone** (Ground truth 14; and `.env.local` must not exist, per the known test-isolation debt).
- [ ] Commit: three commits as above, then `chore: retire the pre-consolidation architecture`

### Task 19: `store/documents.py` + corpus counts

**Files:** Create `store/documents.py`, `tests/test_store_documents.py`; Modify `app/search_provider.py`, `app/routes/pdf.py`, `harness/tools.py`, `ingest/lance_writer.py`; Create `GET /api/corpus/counts`; Modify the webapp footer.

- [ ] **Step 1 — failing test** pinning the behaviour the four current readers must keep: mtime-cached re-read, the `ingested_at` gate that makes migration-era junk titles lose to the humanizer, and the doc-id humanizer fallback.
- [ ] **Step 2 — implement and repoint all four callers.** One reader, one cache.
- [ ] **Step 3 — the footer.** It currently states no corpus size because Plan 3's upload queue falsifies any hardcoded count; `/api/corpus/counts` is the endpoint that lets it say a true number again.
- [ ] **Step 4** — full pytest + vitest.
- [ ] Commit: `refactor(store): one documents.json reader; live corpus counts in the footer`

### Task 20: The remaining ingest defects

**Files:** `store/chunk_store.py`, `ingest/cache.py`, `ingest/lock.py`; tests.

Triaged from STATUS's follow-up list. **Check first whether the `ingest-defects` session landed the two 🔴 items** (worker auto-start, `make_doc_id`) — if so, skip them here.

- [ ] **Step 1 — LanceDB dead-version cleanup. Handoff-blocking; measured 2026-07-31: 5.1 GB on disk holding ~18k chunks.** `optimize()` never drops superseded versions. Pass `cleanup_older_than` / expose `cleanup_old_versions` in the write phase. On the office SMB share this is the difference between a corpus that copies in minutes and one that doesn't. Test: write, delete, re-write, assert on-disk bytes fall after cleanup.
- [ ] **Step 2 — `DownloadCache` concurrency.** Per-instance tmp path (today it's shared across instances) plus a lock around the manifest write. A corrupted manifest parses as an **empty** cache, which would re-download ~7,400 PDFs from state web servers one at a time. Test with concurrent writers asserting a parseable manifest and no lost entries.
- [ ] **Step 3 — `IngestLock` auto-heartbeat.** `_write` heartbeats before `write_doc` but not during it, and `build_fts_index` + `optimize` will exceed the 120s stale window as the corpus grows — so a live writer's lock can be legitimately stolen cross-machine. Add a background heartbeat thread for the lock's lifetime. Test: hold the lock through a simulated 200s write, assert a second acquirer never steals it.
- [ ] **Step 4 — per-batch snapshot mode.** `JLBC_INGEST_SNAPSHOT=off` exists for supervised backfills, but the *right* long-term shape is one snapshot per batch (per book edition / per note session) rather than per document — protection without the O(n²) cost. Small; do it while the surrounding code is open.
- [ ] Commit: one per step.

**Polish (do if time; each is one small change):** the DOCX-backed citation in AI Mode showing pdfjs's raw error instead of the backend's sentence (one `api.chunk()` call in `PdfViewer.Loaded`); the unused `AiModeToggle` export in `webapp/src/chat/AiModePanel.tsx`; the `chunking.agency_catalog` import guard in `harness/tools.py` (Plan 3 merged, the guard can go); merging the two corpus-name alias tables in `harness/tools.py` and `harness/prompt.py` — **carefully, they normalise in opposite directions**, so a naive merge is wrong.

**Explicitly declined — record the reasons, do not build:**

| Item | Why not |
|---|---|
| Faithfulness verifier (WS3) | A real NLI verifier is a project, not a task; the current chunk-id + quote + span check plus the honest refusal banner is a defensible floor, and shipping a weak proxy is what produced the ~40% false-rejection rate we already deleted once |
| Audit-log writer (WS5) | No consumer exists; the ledger + notices cover what an admin actually needs |
| Layer 2 eval | Depends on WS3 |
| DOCX viewer | Spec-declared out of scope; CitedTextPanel is the stopgap |
| MinerU 3.4.4 upgrade | 1.35× faster and fixes a table misalignment, but it changes chunk text **corpus-wide** ⇒ a full re-ingest plus a re-authored eval ground truth. Wrong side of the handoff date; record it as the first thing a future maintainer should evaluate |
| Retrying the shared `mineru-api` server | Native heap corruption under concurrency (`corrupted double-linked list`); no setting fixes it. Batch mode (`-p <dir>`, measured 2.85×) is the safe way to claim the same win |
| Conversation persistence | Accepted as in-memory per app run |
| Refusal banner on scrolled-back turns | Evaluates the latest turn by design; changing it risks Invariant 3's surface for a cosmetic gain |

---

## Track 5 — The Administrator Handbook

**This is the deliverable that outlives everyone.** Destin is leaving; there is no technical successor; the app has to be operable, explainable, and *modifiable* by someone who has never opened a terminal. The quickstart (Task 27) gets a person installed in ten minutes. The handbook is the other thing — the document that answers "how does this work, why is it built this way, and what do I do when I need it to do something new."

**Two decisions that shape all three tasks:**

**1. The Markdown is the source of truth; the `.docx` is generated.** `docs/HANDBOOK.md` lives in the repo, gets updated alongside code like any other doc, and is what an AI assistant reads when the future admin asks for help. `scripts/build_handbook.py` renders it into a JLBC-styled Word document. If a human hand-edits the `.docx`, the edit is lost on the next build — the build stamps a line saying exactly that at the top. A hand-maintained Word file would be stale within a month and there'd be no way to tell.

**2. It has to be findable in File Explorer, not just in the app** — the moment an admin most needs it is when the app *won't start*. So the generated `.docx` sits on the share next to the corpus (`<data_dir>/JLBC Insight — Administrator Handbook.docx`), refreshed whenever a newer build exists, AND is served in-app.

### Task 21: JLBC memo styling module + handbook renderer

**Files:** Create `scripts/jlbc_memo.py`, `scripts/build_handbook.py`, `tests/test_jlbc_memo.py`; Reference `samples/raw-docx/jlbc-staff-memorandum-style-reference.docx` (committed 2026-07-31 — the real FY 2027 Appropriations Report Round 1 instructions memo, vendored per CLAUDE.md's primary-source rule specifically so this task has a fixture that survives a fresh clone).

**The style, measured from the reference document — implement these values, do not eyeball them:**

| Element | Spec |
|---|---|
| Page | US Letter; margins top **0.7"**, bottom **0.5"**, left/right **1.0"**; header distance 0.75", footer 0.6" |
| Masthead line 1 | `Joint Legislative Budget Committee` — Word `Title` style, **14 pt, bold, centered** |
| Masthead line 2 | `Staff Memorandum` — **14 pt bold, centered** (direct run formatting, not a style) |
| Masthead lines 3–4 | `1716 West Adams` TAB `Telephone: (602) 926-5491` / `Phoenix, Arizona 85007` TAB `azjlbc.gov` — **10 pt**, one **left tab stop at 7020 twips (4.875")** |
| Body text | Calibri **10.5 pt** (note: the `Normal` style is 12 pt and every body run overrides to 10.5 — match the runs, not the style) |
| Section headings | The built-in **`Header` paragraph style**, bold, 10.5 pt, flush left. Yes, really — JLBC reuses `Header` as a section heading; matching the house style means matching that, odd as it looks |
| Bullets | `List Paragraph` style, left indent **0.1875"** |
| Run-in labels | **bold + underline** label, then `: ` or ` – `, then normal text (`Policy Issues – …`, `BUDS Table: …`) |
| Emphasis prefix | `NEW:` in bold at the start of a bullet |
| Vertical spacing | **empty paragraphs**, not space-after |
| Page 2+ header | TAB then `- N -` |

- [ ] **Step 1 — failing tests.** `tests/test_jlbc_memo.py` renders a small fixture document and asserts against the reference: page margins match to the EMU; the masthead's four lines exist with the right sizes/alignment/tab stop; a `##` heading becomes a `Header`-styled bold 10.5 pt paragraph; a `-` bullet becomes `List Paragraph` at 0.1875"; a `**Label:**` line-start becomes a bold+underline run-in label; body runs are 10.5 pt. Read the expected values **out of the committed reference docx** in the test where practical, so a future JLBC style change is a fixture swap rather than a code rewrite.
- [ ] **Step 2 — implement `scripts/jlbc_memo.py`** as a reusable renderer: `render(markdown: str, *, title: str, subtitle: str = "Staff Memorandum") -> Document`. Supported Markdown subset — deliberately small, and the handbook is written to stay inside it: `#`/`##`/`###` headings, paragraphs, `-` bullets (one level), `**bold**`, `_italic_`, `` `code` `` (rendered as Consolas), pipe tables (Table Grid, as `harness/documents.py` already does), and horizontal rules as page breaks.
- [ ] **Step 3 — implement `scripts/build_handbook.py`**: read `docs/HANDBOOK.md`, render, stamp `Generated from docs/HANDBOOK.md on <date> — edits made directly to this Word file will be lost the next time it is rebuilt.` as the first body line, write to `dist/JLBC Insight — Administrator Handbook.docx`.
- [ ] **Step 4** — `.venv/bin/python -m pytest tests/test_jlbc_memo.py -q`, then build and open the result to confirm it *looks* like a JLBC memo. This one needs an eye, not just a green test.
- [ ] **Step 5 (optional, small, real payoff)** — repoint `harness/documents.py::_render_docx` at `jlbc_memo.render()` so **AI Mode's generated memos come out in house style too**. Today they use Word's default Title/Heading 2/List Bullet styling, which is fine but generic. Guard it with the existing `harness/documents.py` tests; if they pin the current styling, update them deliberately in the same commit rather than working around them.
- [ ] Commit: `feat(scripts): JLBC staff-memorandum renderer + handbook build`

### Task 22: Write the handbook

**Files:** Create `docs/HANDBOOK.md`.

Audience: **the next admin, who is not technical.** Write in plain English, second person, no jargon without a definition, and no assumed context about how the app was built. Every section that describes a screen names it exactly as it appears in the UI. Where a decision was a trade-off, say what the trade-off was — a successor who understands *why* can adapt; one who only knows *what* is stuck the first time reality differs.

Required sections, in this order:

- [ ] **Step 1 — Part 1: What this is and why it exists.** The tool in one page: two corpora (budget documents, fiscal notes), search that needs no API key, AI Mode that does. The North Star stated plainly — this is retrieval with auditable provenance; answer generation is secondary; a fiscal analyst who can't verify a claim won't use it twice. The six Core Invariants in the admin's language, especially: **refusal beats hallucination** (a high refusal rate is fixable, a confident wrong answer destroys trust), **every claim carries a citation you can click through to the page and highlight**, and **no "hallucination-free" marketing language, ever** — with the Stanford Lexis study named as the reason.
- [ ] **Step 2 — Part 2: How the pieces fit.** One diagram-free walkthrough: the app is a single program on your PC that opens in Chrome; the documents and the search index live in one folder on the shared drive; nothing leaves your network unless AI Mode is on; MinerU reads PDFs into text with page and position recorded; the index is LanceDB; the models that do search run locally on the CPU with no key. Name the folder layout (`lancedb/`, `pdfs/`, `documents.json`, `settings.json`, `jobs/`, `usage/`, `backups/`, `notices.json`) and say what each is in one sentence.
- [ ] **Step 3 — Part 3: OpenRouter, keys, and money.** What OpenRouter is (one account, many model vendors, one bill). Step-by-step key creation with **setting a hard monthly credit limit on the OpenRouter dashboard** as a required step, not a suggestion — that cap is the only true org-wide spend enforcement and it is zero code. How billing works (per token, in and out; costs are recorded per call at OpenRouter's exact figure). What prompt caching is and why the admin page shows a cache percentage: the same system prompt is resent on every step, cache reads cost roughly a tenth of fresh input, and a broken cache is **invisible** except as a bill ~10× larger — that percentage is the only early warning.
- [ ] **Step 4 — Part 4: The two AI modes, and why the models were chosen.** This is the section Destin specifically asked for, so it gets real reasoning, not a table.
  - **Standard is the default on every new question, deliberately.** It keeps a tight retrieval posture (step cap ~15, first-call cap on) because most real questions are lookups.
  - **Deep Research** raises the cap (~50) and permits broad multi-year sweeps.
  - **The measured cost difference, from the 2026-07-31 live run: $0.0127 and 50 seconds for a Standard lookup versus $0.563 and 295 seconds for a comparable Deep Research question — about 44× the cost and 6× the time.** That is why the cheap path is the default and the expensive one is a deliberate, explained click.
  - **Why open-weight models rather than the flagships.** First-party flagship models (Fable/Opus/GPT-class) were explicitly rejected on cost: open-weight alternatives deliver most of the quality for a fraction of the per-token price, and the whole point is a tool an office can afford to leave switched on. Deep Research is assigned a cost-effective frontier-class open model; Standard is assigned the best opus-level-performance-per-dollar open model. Both are **admin-changeable without touching code**, and the app auto-falls-back if a model is retired.
  - **What a tier is NOT:** the step caps are not admin-configurable, on purpose — an admin who set Standard's cap to 1 would silently break every quick lookup with no error to explain it.
- [ ] **Step 5 — Part 5: Every admin surface, screen by screen.** Costs (including the honest "at least $X (N calls of unknown cost)" wording and what makes a cost unknown); AI Mode setup (key, provider, tier models, what "custom endpoint" is for and its four caveats); Spend limits (default, per-user override, exemptions like the director, what a user at their limit sees, and that **search is never affected**); Corpus (counts, queue, snapshots, one-click restore and when to use it); Notices; Admin transfer (and the warning that transferring means losing your own access); Where things live. State plainly that the admin gate is a **soft gate keyed on Windows username, not a security boundary** — it exists so individual spend isn't casually browsable, and nothing harmful sits behind it.
- [ ] **Step 6 — Part 6: Uploading documents, and the confidentiality rule.** Invariant 8 in full, in the admin's words: **only public-record documents** — baseline books, appropriations reports, fiscal notes, bills, executive budget requests, agency budget requests, annual financial reports. The reason, stated honestly: the data-retention practices of OpenRouter and the model providers behind it are inconsistent and likely insufficient for confidential state data. Both halves of the risk: search-only mode never sends document content anywhere, **but** a confidential document uploaded to the share is exposed to anyone who later asks AI Mode a question that retrieves it. What to do if something confidential is uploaded by mistake (remove it, restore a snapshot from before, and understand what may already have been sent). Also the practical reality: large books process overnight, so leave the app running.
- [ ] **Step 7 — Part 7: Routine operation and troubleshooting.** Adding a new edition when JLBC publishes one; refreshing fiscal notes; what to do when the shared drive moves (the repair screen); "AI Mode says no API key"; "a document has been processing for hours" (expected for books — 1–3 min/page); "search returns nothing"; where the logs are; how to restore a snapshot. Each as symptom → what it means → what to do.

- [ ] **Step 7a — Part 7's most important subsection: "If nobody can get into Admin."** Destin asked for this by name, and it is the section most likely to be read by a stranger under pressure, so write it accordingly: **numbered steps, exact filenames, exact text to type, and no assumed knowledge.** It must be followable by someone who has never edited a configuration file.

  Cover, in this order:

  1. **What causes a lockout** — plainly, so the reader can recognise which one they're in: the admin username was mistyped when it was transferred (the app matches it **exactly**, so `destin` and `Destin` are different people to it); the admin left and their Windows account was deleted; IT changed how usernames are formatted; someone edited `settings.json` and it broke.
  2. **The easy fix (do this one).** Open the shared data folder. Right-click → **New → Text Document**. Name it exactly `RESET-ADMIN.txt` — including making sure Windows hasn't quietly named it `RESET-ADMIN.txt.txt`, which it will if file extensions are hidden. **Show the reader how to check that**, because it is the single most likely way this goes wrong. Close and reopen JLBC Insight; open the Admin page; it will offer to let you claim admin; the file is used up automatically.
  3. **What "used up" means** — it gets renamed to `RESET-ADMIN.done-<date>.txt` and a line is written to the notices log recording who claimed and when. It's a record, not a secret; leave it or delete it.
  4. **The manual fix**, if the easy one can't work (say, the folder is read-only). Open `settings.json` **in Notepad** — the words "not Word, not WordPad" in bold, with the reason: those programs replace straight quotes with curly ones and the file stops being readable. Find the line `"admin_username": "Someone",` and change it to `"admin_username": "",`. Save. Restart the app. The next person to open Admin claims it.
  5. **The nuclear option** — a complete minimal `settings.json` printed in full for the reader to copy, and what is lost by using it (the API key and every spend limit, which must be re-entered). State that the app keeps a copy of a broken settings file as `settings.json.corrupt-<date>` **before** replacing it, so the old API key can usually still be read out of that copy with Notepad.
  6. **The honest security note.** Anyone who can write to the shared folder can do all of the above. That is true of any file on a shared drive and was a deliberate choice (the OpenRouter key is protected by a hard spending cap at OpenRouter, not by hiding the file). The admin gate keeps individual spending from being casually browsable; it is not a lock, and nothing dangerous sits behind it.
  7. **The prevention note.** Before transferring admin to someone else, have them tell you the username Windows actually shows for them — the Settings page displays it — rather than guessing from their name. One minute here avoids all of the above.
- [ ] **Step 8 — Part 8: Changing the app with AI help.** The section that makes this a living system instead of a frozen one. Written for a non-developer:
  - **What you need:** the code (the GitHub repo), an AI coding assistant (Claude Code is what built it), and this handbook.
  - **What to point the assistant at first, and why:** `CLAUDE.md` (the working rules), `STATUS.md` (**the single source of truth for current state** — the phase plans are historical and were never updated as things shipped), and the consolidation spec. Say explicitly that reading STATUS.md first prevents an assistant from "fixing" something that was deliberately decided.
  - **Copy-paste starting prompts** for the realistic jobs: *add support for a new file type*, *a document extracted badly*, *change what the AI is told to do* (the system prompt), *add a field to search*, *the eval score dropped*. Each prompt names the files that matter and the command that proves it worked.
  - **The rules to give the assistant, every time:** work in a git worktree, not on master; run the eval (`uv run python -m eval.run_eval`) after any change to retrieval, ingest, chunking, or the system prompt, and **commit the results file alongside the code**; annotate non-obvious code with a WHY comment; never test against a corpus you can't restore; take a snapshot first.
  - **What not to let it do:** rewrite the citation-verification path without understanding Invariants 1–3; change chunk IDs (it invalidates the eval ground truth and orphans live chunks); loosen the refusal threshold to make the tool "more helpful" — that trades trust for the appearance of usefulness, which is the one trade this project never makes.
  - **How to tell whether a change is safe to keep:** the eval numbers, the test suites, and a handful of real questions you already know the answers to.
- [ ] **Step 9 — Part 9: Reference.** Glossary (chunk, embedding, retrieval, rerank, refusal threshold, RRF, provenance, tier, token, prompt cache); the current model assignments and where to change them; key file paths; the eval command and how to read its output; links to the spec, STATUS.md, and the quickstart.
- [ ] **Step 10** — build it (`.venv/bin/python scripts/build_handbook.py`), read the Word output end to end **as if you were the next admin**, and fix every place it assumes knowledge the reader doesn't have.
- [ ] Commit: `docs: administrator handbook — operation, cost model, confidentiality, AI-assisted maintenance`

### Task 23: Ship the handbook where people will find it

**Files:** Modify `app/routes/admin.py` (or a small `app/routes/handbook.py`), `app/main.py`, `webapp/src/pages/Help.tsx` (new), `Header.tsx`, `setup.sh`; Create `tests/test_handbook_route.py`.

- [ ] **Step 1 — failing tests:**
  - `GET /api/handbook` streams the `.docx` with the correct content type and a filename that survives the space and em-dash in it
  - `GET /api/handbook/markdown` returns the source text (this is what the in-app Help page renders, and what an admin can paste into an AI assistant)
  - on startup, if `<data_dir>/JLBC Insight — Administrator Handbook.docx` is missing **or older than the bundled build**, it is copied to the share; a share that is read-only logs one line and does not crash the app — the handbook is important, but not important enough to prevent the app from starting
  - the copy never overwrites a **newer** file on the share without logging what it replaced
- [ ] **Step 2 — implement**, including a **Help** nav item (visible to everyone, not just the admin — analysts benefit from Parts 1, 3, 4 and 6) rendering the Markdown in-app with a prominent "Open the Word version" download.
- [ ] **Step 3 — Task 15 hook:** the packaged bundle includes the built `.docx` and the Markdown; `setup.sh` builds the handbook so a dev checkout has it too.
- [ ] **Step 4** — pytest + vitest green.
- [ ] Commit: `feat(app): serve the handbook in-app and place it beside the corpus on the share`

---

## Track 6 — Handoff gates

### Task 24: The quickstart (G3's script)

**Files:** Create `docs/QUICKSTART.md`.

One page, written for someone who has never seen a terminal. Must include: unzip location; run `install.cmd`; where the shared data folder is; what works with no key (search, fiscal notes, upload) and what needs one; **how to create the OpenRouter key and set a hard monthly credit cap on the OpenRouter dashboard** (S19 — the only true org-wide spend enforcement, and it is zero code); how to claim admin; the Invariant 8 public-record-only rule; where logs live; and the three things that go wrong most (share moved → the repair screen; no key → AI Mode explains itself; big book → it processes overnight, leave it running).

It also carries **one line about lockout recovery** — "if nobody can get into Admin, create an empty file called `RESET-ADMIN.txt` in the data folder and reopen the app; the handbook has the details" — because the person who reads the quickstart is the person who will one day need that sentence, and they will not have the handbook open.

It ends by pointing at the handbook: **the quickstart gets you running, the handbook explains everything else** — and it names both locations (the Help tab, and the Word file sitting next to the corpus on the share).

- [ ] Commit: `docs: one-page quickstart for the cold-start install`

### Task 25: G2 — citation spot-verification corpus-wide

**Files:** Create `scripts/verify_citations_sample.py`, `docs/superpowers/investigations/2026-08-01-g2-citation-verification.md`.

- [ ] **Step 1 — implement.** Sample N chunks (default 200) stratified across publisher × fiscal year × source format; for each, open the source PDF, assert the recorded page exists, the bbox lies within the page's media box, and the chunk's leading text is findable in the page's text layer. Emit a JSON + Markdown report like the eval harness does.
- [ ] **Step 2 — run against the finished backfilled corpus** (after Z13 Phase E) and commit the report. Note the known zero-passage document (azleg published a literal test file) so a future reader doesn't chase it.
- [ ] **Step 3 — G2 passes** when failures are explainable, not merely rare. A systematic failure in one publisher/era is a real finding; scattered misses on scanned old books are expected and get recorded as a known limit of the pre-2012 era.
- [ ] Commit: `feat(scripts): G2 corpus-wide citation spot-verification + first report`

### Task 26: G3 — cold start by someone who is not Destin

- [ ] **Step 1** — a colleague installs from the zip on a real JLBC machine using only `QUICKSTART.md`, with **no narration from Destin**. Anywhere they ask a question, the quickstart is wrong; fix the doc, don't coach.
- [ ] **Step 2 — the search-findability check** (the amended G1's human half): the tester runs ~10 real queries on the Budget Documents page and confirms the right document appears in the first screen of grouped results. Record the queries and outcomes in the report — this is the standing replacement for the retired recall@5 gate.
- [ ] **Step 3** — one AI Mode chat end to end, including clicking a citation chip and seeing the PDF open at the highlight. **This is still unverified by any human** (Plan 4 shipped 298 vitest specs for the logic and nobody has watched it render) — treat a failure here as expected-to-be-possible, not surprising.
- [ ] **Step 4** — record results; G3 passes when all three succeed without help.
- [ ] Commit: `docs: G3 cold-start results`

### Task 27: Close out

- [ ] Update `STATUS.md`: Plan 5 shipped section, gates G2/G3 outcomes, the declined list above (so nobody re-opens them), and the honest remaining-risk list.
- [ ] Update `CLAUDE.md`'s workspace layout table — `web/`, `mcp-server/`, `db/` are gone, `packaging/` is new — and add the rule that **`docs/HANDBOOK.md` is updated in the same commit as any change that alters an admin screen, the model assignments, the folder layout, or the upload rules.** A handbook that drifts is worse than none, because the reader has no way to know which half is stale.
- [ ] **Rebuild the handbook and re-copy it to the share** so the shipped Word file matches the shipped app.
- [ ] Commit: `docs(STATUS): Plan 5 shipped`

---

## Risks, stated plainly

1. **Packaging is the one thing that can fail outright** (Task 14). Everything else in this plan degrades gracefully if imperfect; an app that won't install is worth nothing. Measure first, and take the split-distribution fallback seriously rather than treating it as defeat.
2. **The admin gate is soft by design** (S11). If anyone later mistakes it for security and puts something genuinely sensitive behind it, that is a real vulnerability introduced by misreading, which is why Task 1's docstring says so in the code itself.
3. **Deleting `db/` touches more than `db/`** (Ground truth 12). A partial deletion leaves a repo that imports modules that no longer exist and fails at collection time, which is a nasty first experience for whoever clones next.
4. **The corpus is moving while this plan is written.** The Z13 backfill is still running; Task 20's cleanup and Task 22's G2 verification both need the finished corpus. Sequence them after Phase E.
5. **Nobody has watched a citation chip open a PDF.** It has 298 passing specs and zero human observations. Task 26 Step 3 is the first time; budget for it to find something.
6. **The handbook is the only artifact with no automated test for being *right*.** Every other deliverable here fails loudly when it's wrong; a handbook that is subtly out of date fails silently and is believed. Two mitigations, both in the plan and neither optional: it is written *after* the screens exist (Track 5 sequencing), and `CLAUDE.md` gains the rule that it updates in the same commit as the thing it describes (Task 27). The deeper mitigation is that its source is Markdown in the repo — the same place an AI assistant will be reading when the next admin asks for a change, so it is in the path of the work rather than off to one side.
