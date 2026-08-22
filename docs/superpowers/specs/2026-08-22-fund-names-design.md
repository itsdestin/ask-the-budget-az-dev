# Fund names in AI Mode tool cards — design

**Date:** 2026-08-22 · **Scope:** F1–F5 · **Status:** draft

## Problem

STATUS.md, "Tool cards" section, still-open item: *"Funds render as raw ids
(`fund:2005`). No catalog name and no display table exists for that dimension,
so it is the honest last resort — but it is still a code on screen. Needs a
fund-name lookup."* When the model calls `list_filter_values(field="fund")`,
the analyst sees a wall of slugs. The STATUS example is stale: the live corpus
stamps **187 distinct fund ids on 23,628 chunks, all slug-shaped**
(`fund:long-term-care-system`), never numeric — but they are still codes.

The catalog already exists. `data/fund-catalog.yaml` (committed, 227 funds)
carries `canonical_id` → `canonical_name`, and **all 187 corpus ids are in
it** (verified against the live store). The name is simply never attached.

## Evidence (verified in this worktree)

- `harness/tools.py:1638` — the fund branch of `_list_filter_values` builds
  values and attaches nothing; the agency branch (`:1630`) attaches `name`
  via `_agency_names()` (`:155`, a degrade-to-`{}` guarded import of
  `chunking.agency_catalog.id_to_name`).
- `webapp/src/chat/tool-views/ListFilterValuesView.tsx:117`
  (`valueDisplayName`) already renders a server-attached `name` first, for
  ANY field — the component needs **no rendering change**, only its stale
  comments (`:20`, `:114`: "a `fund` id has no table and no catalog name").
- `webapp/src/chat/__tests__/tool-body.test.tsx:543` pins the old behaviour
  ("shows a fund as its own id rather than inventing a name") — and its
  fixture is `fund:2005`, an id the corpus never mints. Same impossible-
  fixture shape as the STATUS falsehood; must be replaced, not kept.
- `tests/test_harness_tools.py:1158` — the Invariant-7 root-import allowlist
  (`funds` not in it); `:1192` — the narrow read-side-only guard precedent
  (`identity.resolve` yes, `identity.repair` no).
- `chunking/entity_stamper.py:32` — precedent for locating the committed
  catalog: `Path(__file__).resolve().parent.parent / "data" / "fund-catalog.yaml"`.
  `packaging/build_bundle.py:114` selects files via `git ls-files`, and
  `data/fund-catalog.yaml` is tracked, so it ships in the Windows bundle
  automatically.
- `webapp/src/chat/tool-views/RetrieveView.tsx:244` renders fund FILTER ARGS
  as `f.replace(/^fund:/, "").toUpperCase()`.

## Design

**F1 — a read-only fund-name loader in `funds/` (new module `funds/names.py`).**
`id_to_name() -> dict[str, str]`, mirroring `chunking/agency_catalog.py:59`:
parse `data/fund-catalog.yaml` once (`lru_cache` per path), map
`canonical_id → canonical_name`. Located by the `entity_stamper.py:32`
precedent (`Path(__file__).resolve().parent.parent / "data" / …`). It lives in
`funds/` because `chunking/` triggers the eval-after-change rule for a change
retrieval cannot observe, and `harness` may not import `app.*`. A NEW module
rather than `funds/catalog.py` because that file is the build/write side
(`write_catalog_yaml`) and imports `funds.parser` → `chunking.readers`;
`names.py` imports only `yaml` + `pathlib`, keeping the harness's reach
read-only and light.

**F2 — attach `name` in the fund branch of `_list_filter_values`.** Mirror
the agency branch exactly, via a `_fund_names()` helper beside
`_agency_names()` with the same degrade-everywhere contract: missing file,
bad YAML, wrong type, raising callable — all return `{}` and the tool answers
with raw ids, exactly today's output. A live conversation must never die over
a metadata nicety. Sketch (to be run and corrected by the implementer, not
transcribed):

```python
# harness/tools.py — beside _agency_names(); same guard shape, same reason.
def _fund_names() -> dict[str, str]:
    try:
        from funds.names import id_to_name
        names = id_to_name()
        return names if isinstance(names, dict) else {}
    except Exception:
        return {}
```

**F3 — allowlist changes (Invariant 7), following the `identity` precedent:**
add root `"funds"` to `test_tools_module_imports_are_allowlisted` (with a WHY
comment: read side only, grants no filesystem reach beyond one committed YAML)
AND add a narrow guard `test_tools_module_reaches_only_the_read_side_of_funds`
pinning that `harness/tools.py` imports only `funds.names` — because
`funds.catalog` writes YAML files and admitting the package admits it by the
back door, exactly the `identity.repair` argument at
`tests/test_harness_tools.py:1192`.

**F4 — webapp:** no component change (`valueDisplayName`'s ladder already
prefers `name`). Update the two stale comments and the `interface FilterValue`
doc for `name` (`:49` says "Present on `agency` values" — now agency OR fund).
Replace the `tool-body.test.tsx:543` spec with two honest ones (see Test plan).

**F5 — RetrieveView filter-arg display: LEAVE AS-IS (option a).** Rejected
(b) humanize-the-slug: title-casing `fund:ahcccs` yields "Ahcccs Fund"-style
miscasings that read as wrong names, and this repo's own doctrine
(ListFilterValuesView header) is that a wrong name is worse than a visible
code. The filter-args line is a collapsed echo of what the model *asked for*,
not the payoff surface; the payoff surface (the values list) gets real
catalog names. Piping catalog names to the client is a follow-up, not this.

## Exact files to change

| file | change |
|---|---|
| `funds/names.py` | NEW — `id_to_name()`, yaml+pathlib only |
| `harness/tools.py` | `_fund_names()` helper; fund branch attaches `name` |
| `tests/test_harness_tools.py` | allowlist + read-side guard + fund-name specs |
| `tests/test_fund_names.py` | NEW — loader specs (real committed YAML + tmp fixtures) |
| `webapp/src/chat/tool-views/ListFilterValuesView.tsx` | comments only |
| `webapp/src/chat/__tests__/tool-body.test.tsx` | re-point fund fixtures |

## Test plan

Server (pytest — no real LanceDB, no ONNX; use the existing `store` fake):
- Loader: reads the real committed YAML (`fund:ahcccs` → "AHCCCS Fund");
  missing file / malformed YAML / non-dict top level → `{}`, never raises.
- Tool: mirror the three agency specs at `tests/test_harness_tools.py:824–856`
  for fund — name attached when available, callable accepted, every failure
  shape degrades to raw ids with `"name" not in v`.
- Guards: F3's two tests; verify each RED first by mutation (import
  `funds.catalog` in tools.py → the narrow guard fails).

Webapp (vitest/jsdom):
- **Fixtures must be values the tool can emit** — `field: "fund"`,
  slug-shaped ids. The `fund:2005` fixture pinned impossible input and is why
  the old assumption survived; replace it.
- New specs: a fund value WITH `name` renders the name, not the id; a fund
  value WITHOUT `name` still renders its raw id (degrade legibly). The
  anti-drift guard reading the enum out of `harness/tools.py` is unchanged —
  the accepted field set does not move.

## UX consequences (plain English)

When the assistant lists what funds it can search, the analyst will see real
fund names — "Long Term Care System Fund", "AHCCCS Fund" — instead of dashed
codes. Nothing else on screen changes; a fund the catalog doesn't know still
shows its code rather than a guessed name. All displayed strings come from the
committed catalog, so no new copy needs the jargon guard ("corpus"/"chunk"
banned) — but any NEW sentence added around the list must pass it.

## Risks + what NOT to do

- **Do not de-duplicate or merge fund rows** — duplicate/degenerate catalog
  entries are corpus defects this view must not hide (same rule as agencies).
- **Catalog names ship as-is.** `fund:account` → "Account" is a poor name;
  that is the catalog's defect and out of scope. Do not filter or "fix" names.
- **Do not touch** `retrieval/`, `ingest/`, `chunking/`, `citation/`, or
  `harness/system-prompt.md`. Nothing here is on the eval path; no eval run
  is owed (the CLAUDE.md rule does not fire).
- **Do not** widen the harness's reach into `funds.catalog`/`funds.parser` —
  the read-side guard exists to make that a conscious edit.
- Risk: catalog drift (a future corpus id missing from the YAML) silently
  renders as a code. That is the designed degrade, not a failure; if it ever
  matters, an `eval/identity_check.py`-style audit is the fix, not a looser
  lookup.

## Amendments (implementation)

Recorded 2026-08-22, in the same session that implemented this spec, under
an independent review that corrected three points before code was written
(all applied — see below). TDD throughout: every test was run RED (or
verified RED by mutation where it could not fail naturally) before the
matching code landed.

1. **`_fund_names()` mirrors `_agency_names()` exactly, not the F2 sketch.**
   The sketch (`if not isinstance(names, dict): return {}`) checked `dict`
   and never handled a callable `id_to_name`. The shipped version does what
   `_agency_names()` does: `id_to_name() if callable(id_to_name) else
   id_to_name`, `isinstance(mapping, Mapping)` (not `dict`), and
   `{str(k): str(v) for k, v in mapping.items()}`. Verified by the same
   three degrade shapes the agency branch is tested against (`None`,
   `"not-a-mapping"`, `object()`) plus a fourth — a callable that raises —
   since the sketch's plain-`dict`-check version would have crashed on that
   shape rather than degrading.
2. **`funds/names.py::id_to_name()` degrades to `{}` on its own**, for a
   missing file, malformed YAML, or a non-dict top level — a stronger
   contract than `chunking/agency_catalog.py::id_to_name()`, which lets
   those propagate and relies entirely on `_agency_names()`'s catch-all.
   This was the Test Plan section's explicit ask ("missing file / malformed
   YAML / non-dict top level → `{}`, never raises") and is *narrower* than
   what F1's "mirroring `chunking/agency_catalog.py:59`" line reads as by
   itself — the loader's PARSE SHAPE mirrors the agency loader (same
   `lru_cache`-per-path convention, same skip-on-missing-`canonical_id`
   rule); its FAILURE CONTRACT is stricter. `_fund_names()` in
   `harness/tools.py` still wraps every call in its own try/except
   regardless — it has to tolerate failure shapes the loader cannot
   produce by itself (module absent, wrong return TYPE, a raising
   callable), which is a different concern than "can this loader parse its
   own file."
3. **pytest fixtures use the `_install_fake_catalog` ModuleType +
   `sys.modules` pattern exactly**, via a new sibling helper
   `_install_fake_fund_catalog` beside it — not a monkeypatched attribute
   on the real `funds.names`, which would not be able to simulate "module
   present but no `id_to_name` attribute at all" or an import that fails.
4. **Two webapp specs, not one**, replacing the single `fund:2005` fixture:
   one WITH a server-attached `name` (`fund:ahcccs` → "AHCCCS Fund", the
   real committed catalog row, verified present at
   `data/fund-catalog.yaml:33`), one WITHOUT (`fund:long-term-care-system`
   — the spec's own live-corpus example id — with no `name` key, asserting
   the raw id renders and `sample_doc_title`'s agency name does not leak
   in). No component logic changed, confirmed by mutation: temporarily
   deleting `valueDisplayName`'s name-preference branch turned both new
   specs (plus, incidentally, the pre-existing duplicate-name-agency spec)
   red; reverting restored all 47/47 green.
5. **Extra loader tests beyond the spec's minimum**, added because the
   loader carries its own degrade contract (point 2 above) and needed its
   own coverage independent of `_fund_names()`'s: an "every key starts with
   `fund:`" sanity check against the real 227-entry catalog, and an
   "entry with no `canonical_id` is skipped, not crashed on" case mirroring
   `chunking/agency_catalog.py::_load_cached`'s identical guard.
6. **Guard tests verified RED by mutation, not just written and left
   green.** `test_tools_module_reaches_only_the_read_side_of_funds` was
   proven to fail when a bogus `from funds.catalog import
   build_fund_catalog` was inserted beside the real `funds.names` import,
   then confirmed to pass again after reverting — the exact check the
   spec's Test Plan asks for.

No deviations from F3, F4 (beyond the two-test split above), or F5 — F5
(leave `RetrieveView`'s filter-arg display as-is) required no code and none
was written. No file outside the "Exact files to change" table plus
`tests/test_fund_names.py` (already listed there) was touched.
