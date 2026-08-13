# Admin Extensions Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship spec E1–E3 + E6 (`docs/superpowers/specs/2026-08-12-admin-extensions-design.md`): an admin-editable alias overlay for search, an admin-authored office-guidance block in the AI prompt, analyst issue reports with an admin inbox, and the `/admin` page regrouped by function.

**Architecture:** Three purpose-built files on the shared data dir (`office-aliases.json`, `office-guidance.md`, `issue-reports/`), each read through an mtime-checked cache and written tmp+`os.replace` — the established `settings.json`/`notices.json` pattern. The alias overlay is consumed by `retrieval/query_agency.py` (WEAK confidence only, never a hard filter) and `app/search_terms.py`; guidance is injected via a new `{{OFFICE_GUIDANCE}}` template placeholder; issue reports are one JSON file per report (the `jobs/` pattern). New admin routes live in a new `app/routes/tuning.py` + `app/routes/issues.py`, gated by the existing `require_admin`.

**Tech Stack:** Python 3.12 / FastAPI / pytest; React 18 + TypeScript / vitest. No new dependencies.

## Global Constraints

- **Execute in a worktree**: `~/ask-the-budget-az-worktrees/admin-extensions/` on branch `admin-extensions`, with `ln -s <main-repo>/.venv <worktree>/.venv`. Sync master first (`git fetch origin && git pull origin master`).
- **Layering:** `store/` must not import `retrieval/`, `chunking/`, or `harness/`. `retrieval/` and `app/search_terms.py` must not import `harness/`. `harness/prompt.py` stays light (stdlib + `harness.constants` + the new `harness.office_guidance`, which itself imports only stdlib + `store.config`).
- **E1 hard rule:** an overlay alias may NEVER resolve at `Confidence.EXACT`. Structural, pinned by test.
- **E2 hard rules:** empty/missing guidance renders the prompt byte-identical to today; guidance cap is **8192 bytes**; every save writes the prior version to `office-guidance.md.bak`.
- **File posture:** reads degrade (missing → empty; corrupt → empty with a stderr line, or a visible "unreadable" row for reports); writes raise. Nothing in `tests/` opens a real LanceDB or loads ONNX weights.
- **Copy rules:** the admin gate is never described as authentication. Error messages are plain sentences. No "hallucination-free"/"grounded" language anywhere.
- **WHY comments** on every non-trivial edit (CLAUDE.md rule — Destin reads the comments, and plan code is a sketch: if reality disagrees with a code block here, fix the code and note the deviation).
- Commit after every task. Full gates at the end: pytest, vitest, `tsc -b`, `npm run build`, and the eval task (Task 13).

## Recorded deviations from the spec (decided while planning, carry into STATUS.md)

1. **Report context capture is trimmed.** The spec listed `page` and `app_version` on a report. The report form is its own route (so "page they were on" would always read `/report`), and the dev tree exposes no version constant. Reports carry `submitted_by`, `submitted_at`, `description`, `expected` only.
2. **Transcript attach is a picker, not a "current conversation" checkbox.** The conversation lives in `Ai.tsx` state, which the report page cannot see without new cross-page plumbing. Instead the form offers an optional "Attach one of your recent AI conversations" dropdown fed by the existing `GET /api/history` (the caller's own chats, already per-device). Same consent property — unchecked/none by default, explicit copy that the admin will read everything in it.
3. **Only the NEW panels are collapsible.** Retrofitting collapse onto the five shipped panels touches every panel test for a purely visual change; the page gets group headings + reordering now, and the three new sections use collapsed-by-default cards. If the page still reads as a wall after this ships, retrofit then.

---

### Task 1: `store/office_aliases.py` — the overlay file

**Files:**
- Create: `store/office_aliases.py`
- Test: `tests/test_office_aliases_store.py`

**Interfaces:**
- Consumes: `store.config.data_dir()`
- Produces: `OfficeAlias(alias, canonical_id, added_by, added_at)` frozen dataclass; `OfficeAliases(added: tuple[OfficeAlias, ...], disabled: frozenset[str])` with method `added_by_agency() -> dict[str, tuple[str, ...]]`; `office_aliases_path() -> Path`; `load_office_aliases(path=None) -> OfficeAliases` (cached on `(path, mtime_ns, size)`, degrades to empty); `save_office_aliases(OfficeAliases, path=None)` (atomic, raises); `reset_office_aliases_cache()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_office_aliases_store.py
"""The office alias overlay file (spec E1/E5).

Same posture as settings.json: reads degrade, writes raise, a rewrite on
the share is picked up by the (path, mtime, size) stamp.
"""
import json

from store.office_aliases import (
    OfficeAlias,
    OfficeAliases,
    load_office_aliases,
    reset_office_aliases_cache,
    save_office_aliases,
)


def _sample() -> OfficeAliases:
    return OfficeAliases(
        added=(
            OfficeAlias("dor", "agency:rev", "destin", "2026-08-12T17:00:00Z"),
        ),
        disabled=frozenset({"colleges"}),
    )


def test_round_trip(tmp_path):
    path = tmp_path / "office-aliases.json"
    save_office_aliases(_sample(), path=path)
    reset_office_aliases_cache()
    loaded = load_office_aliases(path=path)
    assert loaded == _sample()


def test_missing_file_is_empty(tmp_path):
    reset_office_aliases_cache()
    loaded = load_office_aliases(path=tmp_path / "nope.json")
    assert loaded == OfficeAliases()


def test_corrupt_file_degrades_to_empty_and_says_why(tmp_path, capsys):
    path = tmp_path / "office-aliases.json"
    path.write_text("{not json", encoding="utf-8")
    reset_office_aliases_cache()
    assert load_office_aliases(path=path) == OfficeAliases()
    assert "office-aliases" in capsys.readouterr().err


def test_non_object_json_degrades_not_raises(tmp_path):
    # The chat-history review's defect 8, guarded here from day one: null,
    # [] and 5 all parse fine and then explode on .get. They are bad DATA.
    for junk in ("null", "[]", "5"):
        path = tmp_path / "office-aliases.json"
        path.write_text(junk, encoding="utf-8")
        reset_office_aliases_cache()
        assert load_office_aliases(path=path) == OfficeAliases()


def test_rewrite_on_disk_is_picked_up_without_reset(tmp_path):
    path = tmp_path / "office-aliases.json"
    save_office_aliases(OfficeAliases(), path=path)
    reset_office_aliases_cache()
    assert load_office_aliases(path=path) == OfficeAliases()
    # Another machine writes the file. Force a different mtime stamp.
    import os
    save_office_aliases(_sample(), path=path)
    os.utime(path, ns=(1, 1))
    os.utime(path)  # now() again — size changed, so the stamp differs anyway
    assert load_office_aliases(path=path) == _sample()


def test_added_by_agency_groups_and_lowercases():
    aliases = OfficeAliases(
        added=(
            OfficeAlias("DOR", "agency:rev", "", ""),
            OfficeAlias("rev-dept", "agency:rev", "", ""),
            OfficeAlias("ade", "agency:ade", "", ""),
        )
    )
    assert aliases.added_by_agency() == {
        "agency:rev": ("dor", "rev-dept"),
        "agency:ade": ("ade",),
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_office_aliases_store.py -v`
Expected: FAIL — `ModuleNotFoundError: store.office_aliases`

- [ ] **Step 3: Implement**

```python
# store/office_aliases.py
"""The admin's alias overlay for search (spec E1, decision E5).

`samples/entity-catalog.yaml` is a COMMITTED file the office bundle ships
read-only, so the admin's own acronyms live here instead — a small JSON
file on the shared data dir that merges OVER the catalog at query time.
The stoplists and the catalog itself are untouched by design: this file
may only add aliases (which resolve WEAK, never as a hard filter) and
switch shipped aliases off.

Read posture mirrors harness/settings.py: cached on a (path, mtime, size)
stamp so a rewrite by another machine on the share is picked up, degrading
to empty on any bad file. Writes are tmp+os.replace and RAISE — a failed
save must reach the admin's screen, not vanish.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from store.config import data_dir

OFFICE_ALIASES_FILE = "office-aliases.json"


@dataclass(frozen=True)
class OfficeAlias:
    alias: str
    canonical_id: str
    added_by: str = ""
    added_at: str = ""


@dataclass(frozen=True)
class OfficeAliases:
    added: tuple[OfficeAlias, ...] = ()
    disabled: frozenset[str] = field(default_factory=frozenset)

    def added_by_agency(self) -> dict[str, tuple[str, ...]]:
        """{canonical_id: (lowercased aliases...)} for the filter box."""
        out: dict[str, list[str]] = {}
        for entry in self.added:
            out.setdefault(entry.canonical_id, []).append(entry.alias.lower())
        return {cid: tuple(names) for cid, names in out.items()}


def office_aliases_path() -> Path:
    return data_dir() / OFFICE_ALIASES_FILE


_lock = threading.Lock()
# (path_str, mtime_ns, size) -> OfficeAliases. One entry — there is one file.
_cache: tuple[tuple[str, int, int], OfficeAliases] | None = None


def reset_office_aliases_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def load_office_aliases(path: Path | None = None) -> OfficeAliases:
    """The overlay, or empty. NEVER raises — a bad file must not take down
    retrieval, whose hot path calls this on every query."""
    global _cache
    resolved = path if path is not None else office_aliases_path()
    try:
        stat = resolved.stat()
        stamp = (str(resolved), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return OfficeAliases()
    with _lock:
        if _cache is not None and _cache[0] == stamp:
            return _cache[1]
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"expected an object, got {type(raw).__name__}")
        parsed = _from_dict(raw)
    except (OSError, ValueError, TypeError, KeyError) as err:
        # ValueError covers json.JSONDecodeError AND UnicodeDecodeError —
        # the trap harness/ledger.py documents. Say why every time; callers
        # on the hot path get an empty overlay, not a 500.
        print(
            f"store.office_aliases: ignoring {resolved} ({err}) — the "
            "admin's alias overlay is unavailable for this read.",
            file=sys.stderr,
        )
        return OfficeAliases()
    with _lock:
        _cache = (stamp, parsed)
    return parsed


def _from_dict(raw: dict) -> OfficeAliases:
    added = []
    for row in raw.get("added", []) or []:
        alias = str(row.get("alias") or "").strip().lower()
        canonical_id = str(row.get("canonical_id") or "").strip()
        if not alias or not canonical_id:
            continue  # a torn row costs itself, not the file
        added.append(
            OfficeAlias(
                alias=alias,
                canonical_id=canonical_id,
                added_by=str(row.get("added_by") or ""),
                added_at=str(row.get("added_at") or ""),
            )
        )
    disabled = frozenset(
        str(d).strip().lower() for d in (raw.get("disabled", []) or []) if str(d).strip()
    )
    return OfficeAliases(added=tuple(added), disabled=disabled)


def save_office_aliases(aliases: OfficeAliases, path: Path | None = None) -> None:
    """Atomic write. RAISES on failure — the admin route turns that into a
    visible error, never a silent no-op save."""
    resolved = path if path is not None else office_aliases_path()
    payload = {
        "added": [
            {
                "alias": a.alias,
                "canonical_id": a.canonical_id,
                "added_by": a.added_by,
                "added_at": a.added_at,
            }
            for a in aliases.added
        ],
        "disabled": sorted(aliases.disabled),
    }
    # Per-call uuid suffix, not per-process — the chat-history lesson: two
    # writers on one file must not share a tmp name.
    tmp = resolved.with_name(f"{resolved.name}.tmp-{uuid.uuid4().hex[:8]}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, resolved)
    reset_office_aliases_cache()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_office_aliases_store.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add store/office_aliases.py tests/test_office_aliases_store.py
git commit -m "feat(E1): office alias overlay store — mtime-cached read, atomic write"
```

---

### Task 2: Overlay consumption in `retrieval/query_agency.py` — WEAK only

**Files:**
- Modify: `retrieval/query_agency.py` (function `parse_query_agencies`, ~line 308–405)
- Test: `tests/test_query_agency_overlay.py`

**Interfaces:**
- Consumes: `store.office_aliases.load_office_aliases`, `OfficeAliases`, `OfficeAlias`
- Produces: `parse_query_agencies(query, *, catalog_path=None, office_aliases=None)` — new keyword-only `office_aliases: OfficeAliases | None` (None = load from disk; tests pass a fixture). Behavior contract for later tasks: overlay-added aliases yield `Match(id, Confidence.WEAK, alias)`; disabled strings never resolve through the alias tier.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_query_agency_overlay.py
"""The admin alias overlay in query resolution (spec E1).

THE ONE RULE THAT MAY NEVER WEAKEN: an overlay alias resolves WEAK, no
matter how unique, long, or plausible it is. EXACT becomes a hard filter,
a hard filter deletes every other agency from the page, and 'for' →
Forestry already shipped that defect once. The guard here is structural —
it constructs the most EXACT-deserving alias possible and asserts WEAK.
"""
from pathlib import Path

from retrieval.query_agency import parse_query_agencies
from retrieval.query_match import Confidence
from store.office_aliases import OfficeAlias, OfficeAliases

# The same fixture catalog the existing suite uses. If the existing tests
# use a different fixture path, reuse THEIRS — do not add a second catalog.
CATALOG = Path(__file__).parent / "fixtures" / "agency-catalog.yaml"


def _overlay(*pairs: tuple[str, str], disabled: frozenset[str] = frozenset()):
    return OfficeAliases(
        added=tuple(OfficeAlias(a, cid, "t", "now") for a, cid in pairs),
        disabled=disabled,
    )


def test_overlay_alias_resolves_weak_never_exact():
    # Long, unique, unambiguous — everything that earns EXACT in tier 3.
    # Still WEAK, structurally.
    overlay = _overlay(("revenuedept", "agency:rev"))
    matches = parse_query_agencies(
        "revenuedept baseline", catalog_path=CATALOG, office_aliases=overlay
    )
    ours = [m for m in matches if m.canonical_id == "agency:rev"]
    assert ours and all(m.confidence is Confidence.WEAK for m in ours)


def test_overlay_never_downgrades_a_catalog_match():
    # A catalog name resolving EXACT must stay EXACT when an overlay alias
    # for the same agency also appears — first tier to name an agency owns it.
    overlay = _overlay(("revx", "agency:rev"))
    matches = parse_query_agencies(
        "revenue, department of revx", catalog_path=CATALOG, office_aliases=overlay
    )
    exact = [m for m in matches if m.confidence is Confidence.EXACT]
    assert any(m.canonical_id == "agency:rev" for m in exact)


def test_disabled_shipped_alias_stops_resolving():
    # Pick an alias the fixture catalog resolves through tier 3 today, then
    # disable it. It must vanish from the alias tier (the NAME tier is
    # untouched — disabling a shorthand never hides the agency's real name).
    baseline = parse_query_agencies("rev baseline", catalog_path=CATALOG)
    assert any(m.canonical_id == "agency:rev" for m in baseline)
    matches = parse_query_agencies(
        "rev baseline",
        catalog_path=CATALOG,
        office_aliases=_overlay(disabled=frozenset({"rev"})),
    )
    assert not any(
        m.canonical_id == "agency:rev" and m.matched_text == "rev" for m in matches
    )


def test_overlay_match_suppresses_fuzzy_tier():
    # An overlay hit counts as a match, so tier 4 (fuzzy) must not ALSO run
    # and drag in a guess — same rule as every other tier.
    overlay = _overlay(("dorx", "agency:rev"))
    matches = parse_query_agencies(
        "dorx unclaimed property", catalog_path=CATALOG, office_aliases=overlay
    )
    assert [m.canonical_id for m in matches] == ["agency:rev"]


def test_none_means_load_from_disk_and_missing_file_changes_nothing(monkeypatch, tmp_path):
    # Production callers pass nothing. With no overlay file on disk the
    # result is byte-identical to before this feature existed.
    import store.office_aliases as oa
    monkeypatch.setattr(oa, "office_aliases_path", lambda: tmp_path / "none.json")
    oa.reset_office_aliases_cache()
    with_none = parse_query_agencies("revenue, department of", catalog_path=CATALOG)
    explicit_empty = parse_query_agencies(
        "revenue, department of", catalog_path=CATALOG, office_aliases=OfficeAliases()
    )
    assert with_none == explicit_empty
```

> Fixture note: if `tests/fixtures/agency-catalog.yaml` does not exist, find the fixture the existing `tests/test_query_agency.py` uses (`grep -n "catalog_path" tests/test_query_agency.py`) and reuse it; adjust agency ids in these tests to ones that fixture defines. Do NOT invent a second fixture catalog.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_query_agency_overlay.py -v`
Expected: FAIL — `TypeError: parse_query_agencies() got an unexpected keyword argument 'office_aliases'`

- [ ] **Step 3: Implement in `retrieval/query_agency.py`**

Add the import near the other imports:

```python
from store.office_aliases import OfficeAliases, load_office_aliases
```

Change the signature and add the overlay steps. The tier-3 loop gains a
disabled check; a new overlay scan runs between tier 3 and tier 4:

```python
def parse_query_agencies(
    query: str,
    *,
    catalog_path: Path | str | None = None,
    office_aliases: OfficeAliases | None = None,
) -> list[Match]:
    ...
    # (existing body unchanged down to the tier loops)

    # The admin's overlay (spec E1). Loaded here, not baked into _AgencyIndex:
    # the index is lru-cached for the process lifetime, while this file can
    # change under a running server whenever an admin saves — the store's own
    # mtime stamp makes this call cheap.
    overlay = office_aliases if office_aliases is not None else load_office_aliases()
    disabled = {_normalize_for_match(d) for d in overlay.disabled}
    disabled.discard("")
```

In the tier-3 loop, first line inside `for alias in _scan_phrases(...)`:

```python
        # An admin-disabled shipped alias never resolves through this tier.
        # Only the shorthand dies — the agency's NAME is a higher tier and
        # still resolves, so the escape hatch can't hide an agency outright.
        if alias in disabled:
            continue
```

After the tier-3 loop, before the tier-4 `if not matches:` block:

```python
    # --- Overlay tier: admin-added aliases (spec E1) ------------------------
    # ALWAYS WEAK. The confidence is hardcoded — not computed from
    # uniqueness like tier 3 — because these strings never went through the
    # eval-gated review that earns a hard filter. A bad overlay alias may
    # cost ranking; it may never delete the right answer from the page.
    if overlay.added:
        overlay_to_ids: dict[str, set[str]] = {}
        for entry in overlay.added:
            key = _normalize_for_match(entry.alias)
            if key and key not in disabled:
                overlay_to_ids.setdefault(key, set()).add(entry.canonical_id)
        overlay_longest_first = sorted(overlay_to_ids, key=len, reverse=True)
        for alias in _scan_phrases(normalized, overlay_longest_first):
            for canonical_id in overlay_to_ids[alias]:
                _add(canonical_id, Confidence.WEAK, alias)
```

(The existing `_add` dedupe means a catalog tier that already claimed the agency keeps its confidence — the overlay can only add, never downgrade.)

- [ ] **Step 4: Run the new tests AND the existing agency suite**

Run: `uv run pytest tests/test_query_agency_overlay.py tests/test_query_agency.py tests/test_query_understanding_eval_safety.py -v`
Expected: all PASS — the existing suites prove no-overlay behavior is unchanged.

- [ ] **Step 5: Commit**

```bash
git add retrieval/query_agency.py tests/test_query_agency_overlay.py
git commit -m "feat(E1): overlay aliases resolve WEAK-only in query agency resolution"
```

---

### Task 3: Overlay in the Budget Documents filter box

**Files:**
- Modify: `app/search_terms.py` (`_agency_terms`, `search_terms`)
- Modify: the one call site that hoists the catalog — find with `grep -rn "load_agency_catalog_by_slug()\|search_terms(" app/` (it is the document-listing route; it must hoist the overlay the same way it hoists the catalog, for the same 5,330-stderr-lines reason documented in `search_terms`)
- Test: extend `tests/test_search_terms.py`

**Interfaces:**
- Consumes: `store.office_aliases.load_office_aliases`, `OfficeAliases`
- Produces: `search_terms(doc_id, doc_type, fiscal_year, catalog=None, overlay=None)` — new optional `overlay: OfficeAliases | None`.

- [ ] **Step 1: Write the failing tests** (append to `tests/test_search_terms.py`, matching its existing fixture style — read the file first and reuse its catalog-dict helpers)

```python
from store.office_aliases import OfficeAlias, OfficeAliases


def test_overlay_added_alias_becomes_a_search_term():
    catalog = {"rev": ("agency:rev", ("rev",))}
    overlay = OfficeAliases(added=(OfficeAlias("dor", "agency:rev", "", ""),))
    terms = search_terms("jlbc-approps-fy2026-rev", "approps-per-agency", 2026,
                         catalog=catalog, overlay=overlay)
    assert "dor" in terms


def test_overlay_disabled_alias_is_removed_from_terms():
    catalog = {"rev": ("agency:rev", ("rev", "dor"))}
    overlay = OfficeAliases(disabled=frozenset({"dor"}))
    terms = search_terms("jlbc-approps-fy2026-rev", "approps-per-agency", 2026,
                         catalog=catalog, overlay=overlay)
    assert "dor" not in terms and "rev" in terms


def test_overlay_cannot_resurrect_a_blocked_word():
    # The suppress/ambiguous lists still win: an admin alias spelled "for"
    # must not become a filter-box term even if the save-side validation
    # is somehow bypassed (hand-edited JSON on the share).
    catalog = {"rev": ("agency:rev", ("rev",))}
    overlay = OfficeAliases(added=(OfficeAlias("for", "agency:rev", "", ""),))
    terms = search_terms("jlbc-approps-fy2026-rev", "approps-per-agency", 2026,
                         catalog=catalog, overlay=overlay)
    assert "for" not in terms
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_search_terms.py -v -k overlay`
Expected: FAIL — unexpected keyword argument `overlay`

- [ ] **Step 3: Implement**

In `app/search_terms.py`, import and thread the overlay:

```python
from store.office_aliases import OfficeAliases, load_office_aliases
```

`_agency_terms` gains a parameter and two lines:

```python
def _agency_terms(doc_id: str, catalog: Catalog, overlay: OfficeAliases) -> set[str]:
    ...
    canonical_id, aliases = entry
    if canonical_id in AMBIGUOUS_AGENCIES:
        return set()
    # The admin's overlay: added aliases join, disabled ones leave — and the
    # blocked() lists still apply LAST, so a hand-edited overlay cannot
    # resurrect "for". This module may only ever ADD reviewed vocabulary.
    added = set(overlay.added_by_agency().get(canonical_id, ()))
    disabled = {d.lower() for d in overlay.disabled}
    return (set(aliases) | added) - disabled - _blocked()
```

`search_terms` mirrors the `catalog` hoisting contract:

```python
def search_terms(doc_id, doc_type, fiscal_year, catalog=None, overlay=None):
    if catalog is None:
        catalog = load_agency_catalog_by_slug()
    if overlay is None:
        overlay = load_office_aliases()
    return sorted(
        _agency_terms(doc_id, catalog, overlay) | _type_terms(doc_type, fiscal_year)
    )
```

Then update the listing call site to hoist once: `overlay = load_office_aliases()` next to its existing `load_agency_catalog_by_slug()` hoist, passed into each `search_terms(...)` call.

- [ ] **Step 4: Run the whole file's suite**

Run: `uv run pytest tests/test_search_terms.py -v`
Expected: all PASS (old specs prove no-overlay behavior unchanged — the default `OfficeAliases()` is empty sets all the way down).

- [ ] **Step 5: Commit**

```bash
git add app/search_terms.py app/routes/ tests/test_search_terms.py
git commit -m "feat(E1): overlay aliases reach the Budget Documents filter box"
```

---

### Task 4: Admin alias routes — `GET/PUT /api/admin/aliases`

**Files:**
- Create: `app/routes/tuning.py`
- Modify: `app/main.py` (~line 194, register the router next to `admin_router`)
- Test: `tests/test_admin_tuning_routes.py`

**Interfaces:**
- Consumes: `require_admin` (import from `app.routes.admin`), `current_user` (`app.identity`), `load_agency_catalog`/`id_to_name` (`chunking.agency_catalog`), `SUPPRESSED_ALIASES`/`AMBIGUOUS_ALIASES` (`retrieval.query_agency`), Task 1's store.
- Produces:
  - `GET /api/admin/aliases` → `{"added": [...], "disabled": [...], "shipped": [{"alias", "canonical_id", "agency_name"}], "agencies": [{"canonical_id", "name"}], "warnings": []}`
  - `PUT /api/admin/aliases` body `{"added": [{"alias", "canonical_id"}], "disabled": ["..."]}` → same shape as GET, plus `warnings` (e.g. 2-char alias). Wholesale replace (the `user_limits` rule: per-key merge makes deletion impossible). 400 with a plain sentence on any rejection.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_admin_tuning_routes.py
"""Admin alias + guidance routes (spec E1/E2). Uses the same TestClient +
admin-user setup as tests/test_admin_settings_route.py — read that file
first and copy its fixture pattern (JLBC_USER env + tmp data dir) exactly."""
import json

import pytest
from fastapi.testclient import TestClient

# Reuse the existing admin-route fixture helpers. If test_admin_settings_route
# defines them inline, lift the minimal client/tmp-data-dir setup here.


def test_put_and_get_round_trip(admin_client):
    body = {"added": [{"alias": "dor", "canonical_id": "agency:rev"}], "disabled": []}
    r = admin_client.put("/api/admin/aliases", json=body)
    assert r.status_code == 200
    r = admin_client.get("/api/admin/aliases")
    added = r.json()["added"]
    assert added[0]["alias"] == "dor"
    assert added[0]["added_by"]  # stamped server-side
    assert added[0]["added_at"]


def test_suppressed_word_is_rejected_with_a_reason(admin_client):
    body = {"added": [{"alias": "for", "canonical_id": "agency:rev"}], "disabled": []}
    r = admin_client.put("/api/admin/aliases", json=body)
    assert r.status_code == 400
    assert "for" in r.json()["detail"]


def test_unknown_agency_is_rejected(admin_client):
    body = {"added": [{"alias": "zz9", "canonical_id": "agency:nope"}], "disabled": []}
    assert admin_client.put("/api/admin/aliases", json=body).status_code == 400


def test_collision_with_another_agencys_vocabulary_is_rejected(admin_client):
    # An alias that IS a different agency's slug must be refused — it would
    # boost two agencies under one word with no ambiguity machinery to notice.
    # Pick real ids from the committed catalog: "adc" is Corrections' slug.
    body = {"added": [{"alias": "adc", "canonical_id": "agency:rev"}], "disabled": []}
    r = admin_client.put("/api/admin/aliases", json=body)
    assert r.status_code == 400


def test_two_char_alias_is_allowed_with_a_warning(admin_client):
    body = {"added": [{"alias": "xr", "canonical_id": "agency:rev"}], "disabled": []}
    r = admin_client.put("/api/admin/aliases", json=body)
    assert r.status_code == 200
    assert r.json()["warnings"]


def test_existing_stamp_is_preserved_on_resave(admin_client):
    body = {"added": [{"alias": "dor", "canonical_id": "agency:rev"}], "disabled": []}
    first = admin_client.put("/api/admin/aliases", json=body).json()["added"][0]
    again = admin_client.put(
        "/api/admin/aliases",
        json={"added": [{"alias": "dor", "canonical_id": "agency:rev"},
                        {"alias": "ade2", "canonical_id": "agency:ade"}],
              "disabled": []},
    ).json()["added"]
    kept = next(a for a in again if a["alias"] == "dor")
    assert kept["added_at"] == first["added_at"]


def test_non_admin_gets_403(analyst_client):
    assert analyst_client.get("/api/admin/aliases").status_code == 403
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_admin_tuning_routes.py -v` → FAIL (404, no route)

- [ ] **Step 3: Implement `app/routes/tuning.py`**

```python
"""Admin tuning routes: the alias overlay and office guidance (spec E1/E2).

A separate module rather than more of app/routes/admin.py — that file is
926 lines of provider/settings machinery, and these routes have a
different rhythm (corpus vocabulary and prompt text, not keys and caps).
The gate is the same `require_admin`.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import current_user
from app.routes.admin import require_admin
from chunking.agency_catalog import id_to_name, load_agency_catalog
from retrieval.query_agency import AMBIGUOUS_ALIASES, SUPPRESSED_ALIASES
from store.office_aliases import (
    OfficeAlias,
    OfficeAliases,
    load_office_aliases,
    save_office_aliases,
)

router = APIRouter()


class AliasRow(BaseModel):
    alias: str
    canonical_id: str


class AliasesBody(BaseModel):
    added: list[AliasRow]
    disabled: list[str]


def _shipped_aliases() -> list[dict]:
    """The catalog's own reviewed `aliases:` entries (NOT the auto-folded
    slugs — disabling a slug would be a much bigger hammer than the spec's
    'switch a shipped alias off', and slugs are how JLBC itself abbreviates)."""
    names = id_to_name()
    out = []
    for entry in load_agency_catalog().values():
        for alias in entry.aliases:
            if entry.slug and alias.lower() == entry.slug.lower():
                continue  # the slug is derived, not a reviewed alias
            out.append({
                "alias": alias.lower(),
                "canonical_id": entry.canonical_id,
                "agency_name": names.get(entry.canonical_id, entry.canonical_id),
            })
    return sorted(out, key=lambda r: r["alias"])


def _payload(overlay: OfficeAliases, warnings: list[str]) -> dict:
    names = id_to_name()
    return {
        "added": [
            {
                "alias": a.alias,
                "canonical_id": a.canonical_id,
                "agency_name": names.get(a.canonical_id, a.canonical_id),
                "added_by": a.added_by,
                "added_at": a.added_at,
            }
            for a in overlay.added
        ],
        "disabled": sorted(overlay.disabled),
        "shipped": _shipped_aliases(),
        "agencies": [
            {"canonical_id": cid, "name": name} for cid, name in sorted(
                names.items(), key=lambda kv: kv[1]
            )
        ],
        "warnings": warnings,
    }


@router.get("/api/admin/aliases")
def get_aliases(_: None = Depends(require_admin)) -> dict:
    return _payload(load_office_aliases(), [])


@router.put("/api/admin/aliases")
def put_aliases(body: AliasesBody, _: None = Depends(require_admin)) -> dict:
    catalog = load_agency_catalog()
    # Every string another agency already answers to, for collision checks.
    taken: dict[str, str] = {}
    for entry in catalog.values():
        for word in [entry.slug or "", *entry.aliases]:
            if word:
                taken.setdefault(word.lower(), entry.canonical_id)

    warnings: list[str] = []
    cleaned: list[OfficeAlias] = []
    existing = {a.alias: a for a in load_office_aliases().added}
    now = datetime.now(timezone.utc).isoformat()
    seen: set[str] = set()
    for row in body.added:
        alias = row.alias.strip().lower()
        if not alias or len(alias) > 40:
            raise HTTPException(400, f"'{row.alias}' isn't usable as an alias.")
        if alias in seen:
            raise HTTPException(400, f"'{alias}' is listed twice.")
        seen.add(alias)
        if alias in SUPPRESSED_ALIASES or alias in AMBIGUOUS_ALIASES:
            raise HTTPException(
                400,
                f"'{alias}' can't be an alias — it's an ordinary word that "
                "already misdirected searches once, and it is blocked for "
                "every agency.",
            )
        if row.canonical_id not in catalog:
            raise HTTPException(400, f"Unknown agency '{row.canonical_id}'.")
        owner = taken.get(alias)
        if owner and owner != row.canonical_id:
            raise HTTPException(
                400,
                f"'{alias}' already means {id_to_name().get(owner, owner)} — "
                "one word can't point at two agencies.",
            )
        if len(alias) <= 2:
            warnings.append(
                f"'{alias}' is very short — two-letter terms match by accident. "
                "It will work, but watch whether it misfires."
            )
        prior = existing.get(alias)
        keep_stamp = prior is not None and prior.canonical_id == row.canonical_id
        cleaned.append(
            OfficeAlias(
                alias=alias,
                canonical_id=row.canonical_id,
                added_by=prior.added_by if keep_stamp else (current_user() or ""),
                added_at=prior.added_at if keep_stamp else now,
            )
        )

    shipped = {r["alias"] for r in _shipped_aliases()}
    disabled = set()
    for word in body.disabled:
        key = word.strip().lower()
        if key and key not in shipped:
            raise HTTPException(400, f"'{key}' isn't a shipped alias, so it can't be disabled.")
        if key:
            disabled.add(key)

    overlay = OfficeAliases(added=tuple(cleaned), disabled=frozenset(disabled))
    save_office_aliases(overlay)
    return _payload(overlay, warnings)
```

Register in `app/main.py` next to the existing includes: `from app.routes.tuning import router as tuning_router` … `app.include_router(tuning_router)`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_admin_tuning_routes.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/tuning.py app/main.py tests/test_admin_tuning_routes.py
git commit -m "feat(E1): admin alias routes with plain-English validation"
```

---

### Task 5: `harness/office_guidance.py` + the `{{OFFICE_GUIDANCE}}` prompt slot

**Files:**
- Create: `harness/office_guidance.py`
- Modify: `harness/prompt.py` (`build_system_prompt`, ~line 273)
- Modify: `harness/system-prompt.md` (one insertion, see below)
- Test: `tests/test_office_guidance.py`

**Interfaces:**
- Consumes: `store.config.data_dir` only (keeps `harness/prompt.py` light — no LanceDB/ONNX in the import closure).
- Produces: `GUIDANCE_FILE = "office-guidance.md"`, `MAX_GUIDANCE_BYTES = 8192`, `guidance_path()`, `load_office_guidance() -> str` (mtime-cached, degrades to `""`), `office_guidance_block() -> str` (empty string, or preamble + text), `save_office_guidance(text: str, user: str)` (cap check raises `ValueError`; writes `.bak` of prior version; writes `office-guidance.meta.json` with `edited_by`/`edited_at`), `load_guidance_meta() -> dict`, `reset_guidance_cache()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_office_guidance.py
"""Office guidance file + its prompt slot (spec E2).

THE PROPERTY THAT MATTERS MOST: with no guidance file, the rendered
prompt is byte-identical to the template with the slot removed — this
feature invisible is this feature safe.
"""
import pytest

import harness.office_guidance as og
from harness.prompt import build_system_prompt, reset_template_cache


@pytest.fixture(autouse=True)
def _guidance_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(og, "guidance_path", lambda: tmp_path / "office-guidance.md")
    monkeypatch.setattr(og, "meta_path", lambda: tmp_path / "office-guidance.meta.json")
    og.reset_guidance_cache()
    yield
    og.reset_guidance_cache()


def test_missing_file_renders_nothing():
    assert og.office_guidance_block() == ""


def test_block_carries_the_conflicts_lose_preamble():
    og.save_office_guidance("Prefer the AFR for fund balances.", "destin")
    block = og.office_guidance_block()
    assert "Prefer the AFR for fund balances." in block
    assert "those rules win" in block  # the fixed preamble


def test_cap_is_enforced_at_save():
    with pytest.raises(ValueError):
        og.save_office_guidance("x" * (og.MAX_GUIDANCE_BYTES + 1), "destin")


def test_save_keeps_a_bak_of_the_previous_version():
    og.save_office_guidance("first", "destin")
    og.save_office_guidance("second", "destin")
    assert og.guidance_path().with_suffix(".md.bak").read_text(encoding="utf-8") == "first"


def test_meta_records_who_and_when():
    og.save_office_guidance("text", "destin")
    meta = og.load_guidance_meta()
    assert meta["edited_by"] == "destin" and meta["edited_at"]


def test_prompt_is_byte_identical_when_guidance_absent():
    # Render with no file, then with an EMPTY file — both must equal each
    # other; and rendering with real text must differ only by the block.
    reset_template_cache()
    empty = build_system_prompt(corpus="budget", tier="standard")
    og.save_office_guidance("", "destin")
    og.reset_guidance_cache()
    assert build_system_prompt(corpus="budget", tier="standard") == empty
    og.save_office_guidance("OFFICE-MARKER-XYZ", "destin")
    og.reset_guidance_cache()
    with_text = build_system_prompt(corpus="budget", tier="standard")
    assert "OFFICE-MARKER-XYZ" in with_text
    assert with_text.replace(og.office_guidance_block(), "") == empty


def test_both_corpora_receive_the_block():
    og.save_office_guidance("OFFICE-MARKER-XYZ", "destin")
    og.reset_guidance_cache()
    for corpus in ("budget", "fiscal_notes"):
        assert "OFFICE-MARKER-XYZ" in build_system_prompt(corpus=corpus, tier="standard")
```

- [ ] **Step 2: Run to verify failure** — `uv run pytest tests/test_office_guidance.py -v` → FAIL (`ModuleNotFoundError`)

- [ ] **Step 3: Implement `harness/office_guidance.py`**

```python
"""The administrator's guidance block for the AI prompt (spec E2).

The shipped system prompt is a 1,200-line template wired to citation
discipline and refusal thresholds; nobody edits it at runtime. What the
admin CAN do is write this file — plain markdown on the share — and it is
injected into one designated slot with a preamble that makes the shipped
rules win on any conflict. Empty or missing, the prompt renders
byte-identical to today.

Kept import-light on purpose: harness/prompt.py pulls this in, and
building a prompt must not drag LanceDB or the ONNX models into a process
that only wanted a string. stdlib + store.config only.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from store.config import data_dir

GUIDANCE_FILE = "office-guidance.md"
META_FILE = "office-guidance.meta.json"

# ~2,000 tokens. The block rides EVERY request in every AI conversation
# office-wide, so a runaway paste is a silent, recurring token bill — the
# cap turns it into a visible save error instead.
MAX_GUIDANCE_BYTES = 8192

# Fixed, never admin-editable: the sentence that keeps shipped citation/
# refusal/tool rules senior to anything written here.
_PREAMBLE = (
    "## Office guidance from the administrator\n\n"
    "The office administrator added the guidance below. It supplements the "
    "rules above; where it conflicts with citation, refusal, or tool rules, "
    "those rules win.\n\n"
)


def guidance_path() -> Path:
    return data_dir() / GUIDANCE_FILE


def meta_path() -> Path:
    return data_dir() / META_FILE


_lock = threading.Lock()
_cache: tuple[tuple[str, int, int], str] | None = None


def reset_guidance_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def load_office_guidance() -> str:
    """The raw guidance text, or "". NEVER raises — a bad file must not
    take down prompt building for the whole office."""
    global _cache
    path = guidance_path()
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return ""
    with _lock:
        if _cache is not None and _cache[0] == stamp:
            return _cache[1]
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError) as err:
        print(f"harness.office_guidance: ignoring {path} ({err}).", file=sys.stderr)
        return ""
    with _lock:
        _cache = (stamp, text)
    return text


def office_guidance_block() -> str:
    """What `{{OFFICE_GUIDANCE}}` renders to: nothing, or preamble + text."""
    text = load_office_guidance()
    return f"{_PREAMBLE}{text}\n" if text else ""


def save_office_guidance(text: str, user: str) -> None:
    """Atomic save with a one-step undo. RAISES on failure or over-cap."""
    cleaned = text.strip()
    if len(cleaned.encode("utf-8")) > MAX_GUIDANCE_BYTES:
        raise ValueError(
            f"Guidance is limited to {MAX_GUIDANCE_BYTES:,} characters of "
            "text — this text rides every AI request the whole office makes, "
            "so shorter is genuinely better. Trim it and save again."
        )
    path = guidance_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    # One-step undo: the version being replaced survives as .bak — the
    # settings-corrupt-preservation idea, applied to deliberate edits.
    if path.is_file():
        os.replace(path, path.with_suffix(".md.bak"))
    tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(cleaned, encoding="utf-8")
    os.replace(tmp, path)
    meta = {
        "edited_by": user,
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    mtmp = meta_path().with_name(f"{META_FILE}.tmp-{uuid.uuid4().hex[:8]}")
    mtmp.write_text(json.dumps(meta), encoding="utf-8")
    os.replace(mtmp, meta_path())
    reset_guidance_cache()


def load_guidance_meta() -> dict:
    try:
        raw = json.loads(meta_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}
```

- [ ] **Step 4: Wire the slot.** In `harness/prompt.py`:

```python
from harness.office_guidance import office_guidance_block
```

and in `build_system_prompt`'s `_substitute` dict add:

```python
            # The admin's block (spec E2). Dynamic content in a "pure"
            # prompt is safe here because session.py memoizes per
            # conversation — a mid-conversation edit never changes a live
            # cache prefix; new conversations pick it up (and the admin UI
            # says exactly that).
            "OFFICE_GUIDANCE": office_guidance_block(),
```

- [ ] **Step 5: Edit the template.** In `harness/system-prompt.md`, find the `{{/when}}` that closes the budget-corpus block containing `### Accuracy hierarchy for actuals` (grep for that heading; the block closes before line ~934's next marker). Immediately AFTER that `{{/when}}`, at top level (outside every `{{#when}}` block — verify by confirming the insertion point is not between an open and close marker), insert exactly:

```

{{OFFICE_GUIDANCE}}
```

Top-level placement is deliberate: guidance is office-wide and both corpora receive it (`test_both_corpora_receive_the_block` enforces this — if the chosen point turns out to be inside a corpus block, the test fails and the marker must move up/down to top level).

- [ ] **Step 6: Run the guidance tests AND every existing prompt suite**

Run: `uv run pytest tests/test_office_guidance.py tests/test_harness_prompt.py tests/test_harness_prompt_caching.py tests/test_citation_prompt.py -v`
Expected: all PASS. The caching suite matters most — the prefix must stay byte-identical across steps/turns/conversations (guidance is stable within a process run, so it does).

- [ ] **Step 7: Commit**

```bash
git add harness/office_guidance.py harness/prompt.py harness/system-prompt.md tests/test_office_guidance.py
git commit -m "feat(E2): office guidance block — capped, .bak undo, {{OFFICE_GUIDANCE}} slot"
```

---

### Task 6: Guidance admin routes — `GET/PUT /api/admin/guidance`

**Files:**
- Modify: `app/routes/tuning.py` (append)
- Test: extend `tests/test_admin_tuning_routes.py`

**Interfaces:**
- Produces: `GET /api/admin/guidance` → `{"text", "max_bytes", "edited_by", "edited_at"}`; `PUT /api/admin/guidance` body `{"text"}` → same shape; 400 with the save's own sentence when over cap.

- [ ] **Step 1: Failing tests** (append)

```python
def test_guidance_round_trip_and_meta(admin_client):
    r = admin_client.put("/api/admin/guidance", json={"text": "Prefer the AFR."})
    assert r.status_code == 200
    got = admin_client.get("/api/admin/guidance").json()
    assert got["text"] == "Prefer the AFR."
    assert got["edited_by"] and got["edited_at"]
    assert got["max_bytes"] == 8192


def test_guidance_over_cap_is_a_400_with_the_reason(admin_client):
    r = admin_client.put("/api/admin/guidance", json={"text": "x" * 9000})
    assert r.status_code == 400
    assert "limited" in r.json()["detail"]


def test_guidance_routes_are_admin_only(analyst_client):
    assert analyst_client.get("/api/admin/guidance").status_code == 403
```

- [ ] **Step 2: Verify failure** — 404s.

- [ ] **Step 3: Implement** (append to `tuning.py`)

```python
from harness.office_guidance import (
    MAX_GUIDANCE_BYTES,
    load_guidance_meta,
    load_office_guidance,
    reset_guidance_cache,
    save_office_guidance,
)


class GuidanceBody(BaseModel):
    text: str


def _guidance_payload() -> dict:
    meta = load_guidance_meta()
    return {
        "text": load_office_guidance(),
        "max_bytes": MAX_GUIDANCE_BYTES,
        "edited_by": meta.get("edited_by", ""),
        "edited_at": meta.get("edited_at", ""),
    }


@router.get("/api/admin/guidance")
def get_guidance(_: None = Depends(require_admin)) -> dict:
    return _guidance_payload()


@router.put("/api/admin/guidance")
def put_guidance(body: GuidanceBody, _: None = Depends(require_admin)) -> dict:
    try:
        save_office_guidance(body.text, current_user() or "")
    except ValueError as err:
        # The save's own sentence — written for this reader.
        raise HTTPException(400, str(err)) from err
    reset_guidance_cache()
    return _guidance_payload()
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_admin_tuning_routes.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/tuning.py tests/test_admin_tuning_routes.py
git commit -m "feat(E2): guidance admin routes"
```

---

### Task 7: `app/issue_reports.py` — report storage

**Files:**
- Create: `app/issue_reports.py`
- Test: `tests/test_issue_reports_store.py`

**Interfaces:**
- Consumes: `store.config.data_dir`
- Produces: `REPORTS_DIR = "issue-reports"`, `create_report(*, submitted_by, description, expected="", transcript=None) -> dict`, `list_reports() -> list[dict]` (newest first; corrupt file → `{"id": <stem>, "unreadable": True}` row), `load_report(report_id) -> dict | None`, `update_report(report_id, *, status=None, admin_note=None, actor="") -> dict | None`. Report dict keys: `id, version, submitted_by, submitted_at, description, expected, status, admin_note, resolved_by, resolved_at, transcript`.

- [ ] **Step 1: Failing tests**

```python
# tests/test_issue_reports_store.py
"""One JSON file per report, the jobs/ pattern (spec E3): the directory is
the index, a corrupt file costs one visible row, never the list."""
import json

import pytest

import app.issue_reports as ir


@pytest.fixture(autouse=True)
def _reports_dir(monkeypatch, tmp_path):
    monkeypatch.setattr(ir, "reports_dir", lambda: tmp_path / "issue-reports")


def test_create_and_list_newest_first():
    a = ir.create_report(submitted_by="asmith", description="search is empty")
    b = ir.create_report(submitted_by="bjones", description="pdf will not open")
    listed = ir.list_reports()
    assert [r["id"] for r in listed] == [b["id"], a["id"]]
    assert listed[0]["status"] == "unresolved"
    assert listed[0]["version"] == 1


def test_update_resolves_and_stamps():
    r = ir.create_report(submitted_by="asmith", description="x")
    out = ir.update_report(r["id"], status="resolved", admin_note="fixed", actor="destin")
    assert out["status"] == "resolved"
    assert out["resolved_by"] == "destin" and out["resolved_at"]
    assert ir.load_report(r["id"])["admin_note"] == "fixed"


def test_reopen_clears_the_resolution_stamp():
    r = ir.create_report(submitted_by="a", description="x")
    ir.update_report(r["id"], status="resolved", actor="destin")
    out = ir.update_report(r["id"], status="unresolved", actor="destin")
    assert out["resolved_by"] is None and out["resolved_at"] is None


def test_corrupt_file_is_a_visible_row_not_a_blank_list():
    ir.create_report(submitted_by="a", description="fine")
    bad = ir.reports_dir() / "9999-deadbeef.json"
    bad.write_text("{torn", encoding="utf-8")
    listed = ir.list_reports()
    assert any(r.get("unreadable") for r in listed)
    assert any(r.get("description") == "fine" for r in listed)


def test_update_unknown_id_returns_none():
    assert ir.update_report("nope", status="resolved", actor="d") is None


def test_transcript_is_embedded_verbatim():
    t = {"id": "c1", "title": "chat", "messages": [{"role": "user", "content": "hi"}]}
    r = ir.create_report(submitted_by="a", description="x", transcript=t)
    assert ir.load_report(r["id"])["transcript"] == t
```

- [ ] **Step 2: Verify failure** — `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# app/issue_reports.py
"""Analyst issue reports on the shared data dir (spec E3).

One JSON file per report under <data_dir>/issue-reports/ — the jobs/
shape. No index file exists to corrupt; the directory listing IS the
index, and a torn report costs exactly its own row.

Filenames sort chronologically (UTC timestamp prefix + uuid suffix), so
"newest first" is a reverse filename sort with no parsing.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from store.config import data_dir

REPORTS_DIR = "issue-reports"
VALID_STATUS = ("unresolved", "resolved")


def reports_dir() -> Path:
    return data_dir() / REPORTS_DIR


def _write(path: Path, report: dict) -> None:
    tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def create_report(
    *,
    submitted_by: str,
    description: str,
    expected: str = "",
    transcript: dict | None = None,
) -> dict:
    now = datetime.now(timezone.utc)
    report_id = f"{now.strftime('%Y%m%dT%H%M%S%f')}-{uuid.uuid4().hex[:8]}"
    report = {
        "id": report_id,
        # Stamped so "written before versioning" stays distinguishable from
        # "written today" — the chat-history lesson; it cannot be added later.
        "version": 1,
        "submitted_by": submitted_by,
        "submitted_at": now.isoformat(),
        "description": description,
        "expected": expected,
        "status": "unresolved",
        "admin_note": None,
        "resolved_by": None,
        "resolved_at": None,
        "transcript": transcript,
    }
    reports_dir().mkdir(parents=True, exist_ok=True)
    _write(reports_dir() / f"{report_id}.json", report)
    return report


def _read(path: Path) -> dict | None:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else None
    except (OSError, ValueError):
        return None


def list_reports() -> list[dict]:
    """Every report, newest first. A corrupt file is a VISIBLE unreadable
    row — an admin must see that a report exists even when it cannot be
    read, or "the list looks fine" hides a torn submission forever."""
    directory = reports_dir()
    try:
        paths = sorted(directory.glob("*.json"), reverse=True)
    except OSError:
        return []
    out: list[dict] = []
    for path in paths:
        report = _read(path)
        if report is None:
            print(f"app.issue_reports: unreadable report {path}", file=sys.stderr)
            out.append({"id": path.stem, "unreadable": True})
        else:
            out.append(report)
    return out


def load_report(report_id: str) -> dict | None:
    # The id is embedded in a filename; refuse anything path-shaped.
    if not report_id or "/" in report_id or "\\" in report_id or ".." in report_id:
        return None
    return _read(reports_dir() / f"{report_id}.json")


def update_report(
    report_id: str, *, status: str | None = None, admin_note: str | None = None,
    actor: str = "",
) -> dict | None:
    report = load_report(report_id)
    if report is None:
        return None
    if status is not None:
        if status not in VALID_STATUS:
            raise ValueError(f"Unknown status {status!r}.")
        report["status"] = status
        if status == "resolved":
            report["resolved_by"] = actor
            report["resolved_at"] = datetime.now(timezone.utc).isoformat()
        else:
            report["resolved_by"] = None
            report["resolved_at"] = None
    if admin_note is not None:
        report["admin_note"] = admin_note or None
    _write(reports_dir() / f"{report_id}.json", report)
    return report
```

- [ ] **Step 4: Run** — `uv run pytest tests/test_issue_reports_store.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add app/issue_reports.py tests/test_issue_reports_store.py
git commit -m "feat(E3): issue report storage — one file per report, visible-corrupt rows"
```

---

### Task 8: Issue routes — `POST/GET /api/issues`, `PATCH /api/issues/{id}`

**Files:**
- Create: `app/routes/issues.py`
- Modify: `app/main.py` (register router)
- Test: `tests/test_issues_routes.py`

**Interfaces:**
- Consumes: Task 7's store; `app.identity.current_user`; `app.routes.admin.require_admin` + whatever helper admin.py uses to *check* adminness without raising (read `require_admin`'s body — it calls `is_admin(load_settings(), current_user())`; reuse those pieces); `harness.history.load` (`Transcript`) + `dataclasses.asdict` for the embed.
- Produces:
  - `POST /api/issues` body `{"description", "expected"?, "conversation_id"?}` → `{"report": {...}}`, 400 on empty description. When `conversation_id` is present, the server loads the caller's local transcript and embeds it; unknown id → 400 ("that conversation isn't on this computer").
  - `GET /api/issues` → `{"reports": [...], "unresolved": N, "is_admin": bool}` — admin sees all (transcripts included); non-admin sees only their own, `transcript` replaced by `"transcript_attached": true/false` (their own transcript is already on their machine; re-serving it is pointless payload).
  - `PATCH /api/issues/{id}` (admin only) body `{"status"?, "admin_note"?}` → `{"report": {...}}`, 404 unknown id.

- [ ] **Step 1: Failing tests**

```python
# tests/test_issues_routes.py
"""Issue report routes (spec E3). Reuses the admin/analyst client fixtures
from tests/test_admin_tuning_routes.py (JLBC_USER + tmp data dir)."""


def test_analyst_can_submit_and_see_their_own(analyst_client):
    r = analyst_client.post("/api/issues", json={"description": "search broke"})
    assert r.status_code == 200
    listed = analyst_client.get("/api/issues").json()
    assert listed["reports"][0]["description"] == "search broke"
    assert listed["unresolved"] == 1


def test_empty_description_is_a_400(analyst_client):
    assert analyst_client.post("/api/issues", json={"description": "  "}).status_code == 400


def test_analyst_sees_only_their_own(analyst_client, admin_client):
    analyst_client.post("/api/issues", json={"description": "mine"})
    admin_client.post("/api/issues", json={"description": "admins own report"})
    mine = analyst_client.get("/api/issues").json()["reports"]
    assert [r["description"] for r in mine] == ["mine"]
    everyone = admin_client.get("/api/issues").json()["reports"]
    assert len(everyone) == 2


def test_admin_resolves_with_a_note(analyst_client, admin_client):
    rid = analyst_client.post("/api/issues", json={"description": "x"}).json()["report"]["id"]
    r = admin_client.patch(f"/api/issues/{rid}",
                           json={"status": "resolved", "admin_note": "restarted it"})
    assert r.status_code == 200
    mine = analyst_client.get("/api/issues").json()["reports"][0]
    assert mine["status"] == "resolved" and mine["admin_note"] == "restarted it"


def test_patch_is_admin_only(analyst_client):
    assert analyst_client.patch("/api/issues/whatever", json={"status": "resolved"}).status_code == 403


def test_transcript_embeds_when_a_conversation_is_named(analyst_client, monkeypatch):
    # The history module is per-device local storage; fake its load.
    import app.routes.issues as issues_routes

    class FakeTranscript:
        pass

    def fake_load(cid):
        assert cid == "conv-1"
        import harness.history as hh
        # Build the real dataclass so asdict() exercises the real shape.
        return hh.Transcript(**{**_minimal_transcript_kwargs(), "id": "conv-1"})

    monkeypatch.setattr(issues_routes, "_load_transcript", fake_load)
    r = analyst_client.post(
        "/api/issues", json={"description": "bad answer", "conversation_id": "conv-1"}
    )
    assert r.status_code == 200
    # Non-admin GET replaces the transcript body with a flag.
    mine = analyst_client.get("/api/issues").json()["reports"][0]
    assert mine.get("transcript_attached") is True and "transcript" not in mine


def test_unknown_conversation_is_a_400(analyst_client, monkeypatch):
    import app.routes.issues as issues_routes
    monkeypatch.setattr(issues_routes, "_load_transcript", lambda cid: None)
    r = analyst_client.post(
        "/api/issues", json={"description": "x", "conversation_id": "gone"}
    )
    assert r.status_code == 400
```

> `_minimal_transcript_kwargs()`: write a tiny helper in the test that builds the minimal valid `harness.history.Transcript` kwargs — read the dataclass at `harness/history.py:38` at execution time and fill required fields (id, title, corpus, messages, timestamps as the class requires).

- [ ] **Step 2: Verify failure** — 404s.

- [ ] **Step 3: Implement `app/routes/issues.py`**

```python
"""Issue report routes (spec E3).

POST is every analyst's door and is deliberately ungated. GET filters
server-side: the admin reads everything; anyone else reads their own.
The gate is the same soft S11 username check as the rest of the admin
surface — NOT authentication, and nothing here is harmful if bypassed
(a determined user could already read the share directly).
"""
from __future__ import annotations

from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.identity import current_user, is_admin
from app.issue_reports import create_report, list_reports, update_report
from app.routes.admin import require_admin
from harness.settings import load_settings

router = APIRouter()


def _load_transcript(conversation_id: str):
    """Seam for tests; the real path reads the caller's per-device history."""
    from harness import history

    return history.load(conversation_id)


class IssueBody(BaseModel):
    description: str
    expected: str = ""
    conversation_id: str | None = None


class IssuePatch(BaseModel):
    status: str | None = None
    admin_note: str | None = None


@router.post("/api/issues")
def submit_issue(body: IssueBody) -> dict:
    description = body.description.strip()
    if not description:
        raise HTTPException(400, "Describe what went wrong — an empty report can't be acted on.")
    transcript = None
    if body.conversation_id:
        loaded = _load_transcript(body.conversation_id)
        if loaded is None:
            raise HTTPException(
                400,
                "That conversation isn't stored on this computer, so it "
                "can't be attached. Submit without it, or reopen the chat "
                "and try again.",
            )
        # The analyst's explicit act of publishing their local transcript to
        # the share (spec E3) — the checkbox copy on the form says so.
        transcript = asdict(loaded)
    report = create_report(
        submitted_by=current_user() or "",
        description=description,
        expected=body.expected.strip(),
        transcript=transcript,
    )
    return {"report": _redact(report, admin=False)}


def _redact(report: dict, *, admin: bool) -> dict:
    """Non-admins get a flag, not the transcript body — their own transcript
    is already on their machine, and re-serving it is pure payload."""
    if admin or report.get("unreadable"):
        return report
    out = {k: v for k, v in report.items() if k != "transcript"}
    out["transcript_attached"] = report.get("transcript") is not None
    return out


@router.get("/api/issues")
def get_issues() -> dict:
    user = current_user()
    admin = is_admin(load_settings(), user)
    reports = list_reports()
    if not admin:
        reports = [r for r in reports if r.get("submitted_by") == user]
    visible = [_redact(r, admin=admin) for r in reports]
    unresolved = sum(1 for r in visible if r.get("status") == "unresolved")
    return {"reports": visible, "unresolved": unresolved, "is_admin": admin}


@router.patch("/api/issues/{report_id}")
def patch_issue(report_id: str, body: IssuePatch, _: None = Depends(require_admin)) -> dict:
    try:
        report = update_report(
            report_id,
            status=body.status,
            admin_note=body.admin_note,
            actor=current_user() or "",
        )
    except ValueError as err:
        raise HTTPException(400, str(err)) from err
    if report is None:
        raise HTTPException(404, "No such report — it may have been deleted from the share.")
    return {"report": report}
```

Register in `app/main.py`: `from app.routes.issues import router as issues_router` … `app.include_router(issues_router)`.

- [ ] **Step 4: Run** — `uv run pytest tests/test_issues_routes.py -v` → all PASS

- [ ] **Step 5: Commit**

```bash
git add app/routes/issues.py app/main.py tests/test_issues_routes.py
git commit -m "feat(E3): issue routes — ungated submit, own-only listing, admin resolve"
```

---

### Task 9: `webapp/src/api.ts` — types + client functions

**Files:**
- Modify: `webapp/src/api.ts` (append, following the file's existing `fail(r, what)` pattern)
- Test: extend `webapp/src/api.test.ts` if it stubs fetch per-function (read it first; if it only tests error mapping, add one spec per new failure path)

**Interfaces (produced, consumed by Tasks 10–11):**

```typescript
export interface OfficeAliasRow {
  alias: string;
  canonical_id: string;
  agency_name: string;
  added_by: string;
  added_at: string;
}
export interface ShippedAlias { alias: string; canonical_id: string; agency_name: string }
export interface AdminAliases {
  added: OfficeAliasRow[];
  disabled: string[];
  shipped: ShippedAlias[];
  agencies: { canonical_id: string; name: string }[];
  warnings: string[];
}
export async function adminAliases(): Promise<AdminAliases>;
export async function saveAdminAliases(body: {
  added: { alias: string; canonical_id: string }[];
  disabled: string[];
}): Promise<AdminAliases>;

export interface AdminGuidance { text: string; max_bytes: number; edited_by: string; edited_at: string }
export async function adminGuidance(): Promise<AdminGuidance>;
export async function saveAdminGuidance(text: string): Promise<AdminGuidance>;

export interface IssueReport {
  id: string;
  submitted_by: string;
  submitted_at: string;
  description: string;
  expected: string;
  status: "unresolved" | "resolved";
  admin_note: string | null;
  resolved_by: string | null;
  resolved_at: string | null;
  transcript?: unknown;          // admin GET only
  transcript_attached?: boolean; // non-admin GET only
  unreadable?: boolean;
}
export interface IssuesResponse { reports: IssueReport[]; unresolved: number; is_admin: boolean }
export async function issues(): Promise<IssuesResponse>;
export async function submitIssue(body: {
  description: string;
  expected?: string;
  conversation_id?: string;
}): Promise<{ report: IssueReport }>;
export async function updateIssue(
  id: string,
  body: { status?: "unresolved" | "resolved"; admin_note?: string },
): Promise<{ report: IssueReport }>;
```

- [ ] **Step 1:** Append the types + functions above to `api.ts`; each function follows the file's house pattern exactly — e.g.:

```typescript
export async function adminAliases(): Promise<AdminAliases> {
  const r = await fetch("/api/admin/aliases");
  if (!r.ok) return fail(r, "loading search language");
  return r.json();
}

export async function saveAdminAliases(body: {
  added: { alias: string; canonical_id: string }[];
  disabled: string[];
}): Promise<AdminAliases> {
  const r = await fetch("/api/admin/aliases", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) return fail(r, "saving search language");
  return r.json();
}
```

(PATCH for `updateIssue`, POST for `submitIssue`, mirroring `createConversation`'s shape.)

- [ ] **Step 2:** `cd webapp && npx tsc -b` → exit 0. Run `npx vitest run src/api.test.ts` → PASS.

- [ ] **Step 3: Commit**

```bash
git add webapp/src/api.ts webapp/src/api.test.ts
git commit -m "feat: api client for aliases, guidance, issues"
```

---

### Task 10: Admin page — three new panels + function-group layout (E6)

**Files:**
- Create: `webapp/src/admin/AliasesPanel.tsx`, `webapp/src/admin/GuidancePanel.tsx`, `webapp/src/admin/IssuesPanel.tsx`
- Modify: `webapp/src/pages/Admin.tsx` (grouping + mounting), the admin styles block (find with `grep -rn "adm-panel" webapp/src/styles/`)
- Test: `webapp/src/admin/AliasesPanel.test.tsx`, `GuidancePanel.test.tsx`, `IssuesPanel.test.tsx`, extend `webapp/src/pages/Admin.test.tsx` (it exists if the page has specs — check; otherwise the panel tests carry the weight)

**Interfaces:**
- Consumes: Task 9's api functions/types; `Card`/`CollapsibleCard` from `webapp/src/admin/Card.tsx`.
- Produces: `<AliasesPanel />`, `<GuidancePanel />`, `<IssuesPanel />` — each self-contained (own fetch + own save; they do NOT ride the settings draft/SaveBar, per the spec's "an alias edit never rides along with a half-finished settings draft").

- [ ] **Step 1: Failing tests.** One file per panel; the shape (msw or fetch-stub) must match the house pattern — read `webapp/src/admin/CorpusPanel.test.tsx` (or nearest neighbor) first and copy its setup. The behaviors to pin:

```
AliasesPanel:
- renders rows from adminAliases(); add-row saves via saveAdminAliases and
  renders the server's returned list (never local-appends)
- a 400 from save renders the server's detail sentence, role="alert"
- shipped list renders with a disable toggle; toggling saves
- warnings from the response render (the 2-char case)
GuidancePanel:
- textarea shows fetched text; save button disabled while unchanged
- byte meter renders n / max_bytes and goes warning-toned over 90%
- copy includes "Changes apply to new conversations" and the
  test-a-few-questions caution (exact strings from the spec)
- a 400 renders the server's sentence
IssuesPanel:
- unresolved-first ordering; header badge shows unresolved count
- expanding a row shows description/expected/note; resolve toggle PATCHes
  and re-renders from the response
- an unreadable row renders as "Unreadable report" and offers no actions
- a report with a transcript renders a simple message list (role + content
  for user/assistant strings; tool messages summarized as "retrieved
  passages", never dumped as JSON)
```

Write these as real vitest specs with the house fetch-stub pattern — each asserting through the rendered DOM (`screen.getByText`, `getByRole`), not implementation internals.

- [ ] **Step 2: Verify failures** — components don't exist.

- [ ] **Step 3: Implement the three panels.** Each is a `<section className="card adm-panel">` with an `<h2>`, body in `CollapsibleCard`s **collapsed by default** (plan deviation 3). Sketches to build from (full styling per the house `adm-*` classes):

```tsx
// webapp/src/admin/GuidancePanel.tsx — the simplest; the other two follow its shape.
import { useEffect, useState } from "react";
import * as api from "../api";
import { CollapsibleCard } from "./Card";

export function GuidancePanel() {
  const [saved, setSaved] = useState<api.AdminGuidance | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ok, setOk] = useState(false);

  useEffect(() => {
    api.adminGuidance().then((g) => { setSaved(g); setText(g.text); }).catch(
      (e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  if (!saved) return null;
  const bytes = new TextEncoder().encode(text).length;
  const dirty = text !== saved.text;

  async function save() {
    setError(null); setOk(false);
    try {
      const next = await api.saveAdminGuidance(text);
      setSaved(next); setText(next.text); setOk(true);
    } catch (e) { setError(e instanceof Error ? e.message : String(e)); }
  }

  return (
    <section className="card adm-panel" data-testid="guidance-panel">
      <h2>AI guidance</h2>
      <CollapsibleCard title="Office guidance for AI answers"
        hint={saved.edited_by ? `last edited by ${saved.edited_by}` : "not set"}>
        <p className="adm-hint">
          This text shapes AI answers for the whole office. After editing,
          ask a few test questions to check the effect. Changes apply to
          new conversations.
        </p>
        <textarea value={text} onChange={(e) => setText(e.target.value)}
          rows={10} aria-label="Office guidance" />
        <p className={bytes > saved.max_bytes * 0.9 ? "adm-warn" : "adm-hint"}>
          {bytes.toLocaleString()} / {saved.max_bytes.toLocaleString()} characters
        </p>
        {error ? <p className="adm-warn" role="alert">{error}</p> : null}
        {ok ? <p className="adm-ok" role="status">Saved. New conversations use it.</p> : null}
        <button className="btn" onClick={save} disabled={!dirty}>Save guidance</button>
      </CollapsibleCard>
    </section>
  );
}
```

`AliasesPanel`: table of `added` rows (alias / agency name / added-by / date / remove ✕), an add row — text input + `<select>` over `agencies` (157 options is fine in a native select) — and a collapsed "Shipped shorthand" card listing `shipped` with per-row disable checkboxes. Every mutation builds the full `{added, disabled}` body and calls `saveAdminAliases`, rendering the response (server is the source of truth). Include the honest-limitation copy from the spec: *"Aliases apply to searches immediately. Documents already in the corpus were catalogued without them, so a new alias improves typed searches, not older documents' own labels."*

`IssuesPanel`: fetches `issues()`, renders unresolved-first (`status !== "resolved"` first, then `submitted_at` desc), header `<h2>Issue reports{unresolved ? ` (${unresolved} open)` : ""}</h2>`, each row a `CollapsibleCard` titled `description` truncated to 80 chars with hint `submitted_by · date`; body: full description, expected, transcript viewer when present, a note `<input>`, and a Resolve/Reopen button calling `updateIssue`.

- [ ] **Step 4: Regroup `Admin.tsx`.** Wrap panels in labeled groups, in the spec's order, using a tiny local component:

```tsx
function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="adm-group">
      <h2 className="adm-group-title">{title}</h2>
      {children}
    </div>
  );
}
```

Order inside `.wrap` becomes:

```tsx
<Group title="Needs attention">
  <NoticesPanel notices={notices} />
  <IssuesPanel />
</Group>
<Group title="AI Mode">
  <ProviderPanel ... />
  <GuidancePanel />
</Group>
<Group title="Search & documents">
  <CorpusPanel ... />
  <AliasesPanel />
</Group>
<Group title="Spending">
  <CostsPanel ... />
</Group>
<Group title="Access & files">
  <AdvancedPanel ... />
</Group>
```

(NoticesPanel already renders nothing when empty; the group heading must also hide when ALL its children are empty — for "Needs attention", render the Group only when `notices.length > 0 || issuesPresent`. Since IssuesPanel owns its own fetch, have it accept an optional `onCount(n)` callback the page uses to decide; simplest correct shape: IssuesPanel always renders its section (an empty inbox that says "No reports" is a feature — the analyst-facing door needs a visible other end), so the group always renders and only NoticesPanel conditionally hides.)

Add CSS for `.adm-group-title` (smaller, uppercase-tracked label above the cards — match the existing `adm-*` type scale) in the admin styles block.

- [ ] **Step 5: Run** — `cd webapp && npx vitest run src/admin src/pages/Admin.test.tsx && npx tsc -b`
Expected: all PASS, tsc exit 0. Existing Admin page specs may pin the old panel order — update them to the new grouped order deliberately (that IS the feature), never by loosening assertions.

- [ ] **Step 6: Commit**

```bash
git add webapp/src
git commit -m "feat(E6): admin page regrouped; aliases, guidance and issues panels"
```

---

### Task 11: "Report an issue" — page, route, nav entry

**Files:**
- Create: `webapp/src/pages/ReportIssue.tsx`
- Modify: `webapp/src/App.tsx` (route `/report`), `webapp/src/components/ToolsNav.tsx` (TOOLS entry + icon)
- Test: `webapp/src/pages/ReportIssue.test.tsx`, extend `webapp/src/components/Header.test.tsx` (menu shows the new item for non-admins)

**Interfaces:**
- Consumes: `api.issues`, `api.submitIssue`; the existing history-listing client function in `api.ts` (find it — the chat-history feature added one for the rail; `grep -n "history" webapp/src/api.ts`) for the transcript picker.

- [ ] **Step 1: Failing tests**

```
ReportIssue:
- submits description + expected; renders the new report in "Your reports"
  below (from the POST response + refetch)
- empty description: submit disabled (no dead-click 400 round trip)
- transcript picker renders the caller's chats (stubbed history fn) with
  "Don't attach a conversation" as the default option, and the consent
  sentence "the administrator will be able to read everything in it"
  renders next to it
- own past reports render status, and admin_note when present
- a resolved report renders the resolved state (visibly different row)
Header:
- the tools menu shows "Report an issue" when isAdmin is false
```

- [ ] **Step 2: Verify failures.**

- [ ] **Step 3: Implement.** ToolsNav entry (between Settings and Admin):

```typescript
  {
    to: "/report",
    label: "Report an issue",
    hint: "Tell the administrator something's wrong",
    adminOnly: false,
  },
```

plus a `ReportIcon` drawn to the house recipe (24×24, `stroke="currentColor"`, 2px, round caps — a speech-bubble-with-! outline). Route in `App.tsx`: `<Route path="/report" element={<ReportIssue />} />`.

`ReportIssue.tsx` shape:

```tsx
// Form: what happened (required textarea) / what you expected (optional) /
// optional conversation picker / submit. Below: "Your reports" — the
// caller's own list from api.issues(), refetched after submit, so a
// report visibly exists the moment it is filed (spec E3's whole point).
//
// The context the server records (your username, the time) is STATED on
// the form — nothing is collected invisibly.
```

Transcript picker: `<select>` fed by the history list function, first option `value=""` → "Don't attach a conversation"; when a conversation is chosen, render the consent copy verbatim: *"Attaching shares this conversation with the administrator — they will be able to read everything in it."* Send `conversation_id` only when non-empty.

- [ ] **Step 4: Run** — `cd webapp && npx vitest run src/pages/ReportIssue.test.tsx src/components/Header.test.tsx && npx tsc -b` → PASS / exit 0.

- [ ] **Step 5: Commit**

```bash
git add webapp/src
git commit -m "feat(E3): report-an-issue page + nav entry"
```

---

### Task 12: Full gates

- [ ] **Step 1:** `uv run pytest -x -q` → everything green (expect ~2400+ passed, 5 documented skips).
- [ ] **Step 2:** `cd webapp && npx vitest run && npx tsc -b && npm run build` → all green, exit 0.
- [ ] **Step 3:** Fix anything red; commit fixes with their own messages.

---

### Task 13: Eval with a representative overlay fixture (the E1 gate)

The overlay touches `retrieval/`, so the CLAUDE.md eval rule applies. The claim to prove: **an admin alias cannot move ground-truth queries** (WEAK-only means eval recall must be unchanged with a plausible overlay loaded).

- [ ] **Step 1: Control run** (no overlay file in the data dir — verify `data/insight-data/office-aliases.json` does not exist):

```bash
uv run python -m eval.run_eval
```

Record recall@5 / @15 / @20 / refusal / p95 from the printed summary.

- [ ] **Step 2: Overlay run.** Write a representative overlay into the dev data dir:

```bash
cat > data/insight-data/office-aliases.json <<'EOF'
{
  "added": [
    {"alias": "dor", "canonical_id": "agency:rev", "added_by": "eval-fixture", "added_at": "2026-08-12T00:00:00Z"},
    {"alias": "ade", "canonical_id": "agency:ade", "added_by": "eval-fixture", "added_at": "2026-08-12T00:00:00Z"},
    {"alias": "azdps", "canonical_id": "agency:dps", "added_by": "eval-fixture", "added_at": "2026-08-12T00:00:00Z"}
  ],
  "disabled": []
}
EOF
uv run python -m eval.run_eval
```

> Verify each canonical_id exists in the committed catalog first (`grep "canonical_id: agency:rev" samples/entity-catalog.yaml` etc.); substitute real ids if any differ. A fixture pointing at a nonexistent agency measures nothing.

- [ ] **Step 3: Compare.** Expected: recall@5 / @15 / @20 and refusal precision **identical** to Step 1 (same machine, minutes apart — this is the control discipline; a WEAK boost on aliases none of the eval queries type should move nothing). If any recall number moves: STOP and investigate — a moved number means the overlay reached a hard-filter path, which is the exact defect class E1 exists to prevent. That is a bug, not a tuning question.

- [ ] **Step 4: Clean up and commit the evidence:**

```bash
rm data/insight-data/office-aliases.json
git add eval/results/
git commit -m "eval: overlay fixture run — recall unchanged with admin aliases loaded (E1 gate)"
```

---

### Task 14: STATUS.md + merge

- [ ] **Step 1:** Add a STATUS.md section "Admin extensions — aliases, guidance, issue reports (2026-08-12)": what shipped, the three recorded deviations from the top of this plan, the eval numbers from Task 13, suite counts, and the standing browser-verification caveat (jsdom applies no stylesheet; the regrouped page, the collapsed cards, and the report form are pinned by specs and unwitnessed until someone opens the app).
- [ ] **Step 2:** Commit; then merge per house rules: `git fetch origin && git pull origin master` (re-check immediately before merging — master moves in large merges), merge `admin-extensions` into master, **push**, remove the worktree (`git worktree remove ~/ask-the-budget-az-worktrees/admin-extensions && git branch -d admin-extensions`).
- [ ] **Step 3:** If a dev server was started for verification, shut it down once the commit lands on `origin/master`.

---

## Self-review notes (run after drafting — issues found and fixed inline)

- **Spec coverage:** E1 → Tasks 1–4, 13; E2 → Tasks 5–6; E3 → Tasks 7–8, 11; E6 → Task 10; error-handling posture is embedded per task; the spec's guard test ("no overlay alias may ever resolve EXACT") is Task 2's first test; the eval requirement is Task 13. E4 requires no task (future direction).
- **Type consistency:** `OfficeAliases`/`OfficeAlias` names match across Tasks 1–4 and 13; route payload keys match Task 9's TS types; `search_terms(..., catalog, overlay)` matches Tasks 3's call-site instruction.
- **Known sketch points** (executor must verify against reality, per the plan-code-is-a-sketch rule): the fixture catalog path in Task 2; the admin-client fixture pattern in Task 4; `harness.history.Transcript`'s exact fields in Task 8; the history-list client function name in Task 11; the `{{OFFICE_GUIDANCE}}` insertion line in Task 5.
