"""Fund-name lookup — read-only.

`data/fund-catalog.yaml` (committed, 227 funds) is the single source of
truth for `fund:<slug>` canonical IDs. `harness/tools.py` needs only the
REVERSE direction — turn a stored `fund_canonical_id` back into a display
name for `list_filter_values(field="fund")` — so this module is a narrow
YAML -> dict loader, mirroring `chunking/agency_catalog.py::id_to_name`.

Deliberately a NEW module rather than `funds/catalog.py`: that file is the
BUILD side (`write_catalog_yaml`) and imports `funds.parser` ->
`chunking.readers`, pulling MinerU-adjacent extraction machinery into
whatever imports it. This module imports only `yaml` + `pathlib`, so
`harness/tools.py` reaching into `funds` stays read-only and light — see
the Invariant 7 guard at
`tests/test_harness_tools.py::test_tools_module_reaches_only_the_read_side_of_funds`,
which pins that `harness/tools.py` may import `funds.names` and nothing
else in the package.

`id_to_name()` degrades to `{}` on its own for missing file / malformed
YAML / a non-dict top level, rather than leaving all of that to the
caller-side guard in `harness/tools.py::_fund_names()`. That caller-side
guard still exists and still wraps every call in its own try/except —
it has to tolerate failure shapes this loader cannot produce on its own
(the module missing entirely, an attribute of the wrong TYPE, a callable
that raises) — but a metadata nicety failing to parse its own YAML file
must never be what takes down a live conversation, so this loader does
not lean on a caller to catch what it can catch itself.
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

import yaml

# Same locate-by-parent-of-package-dir convention as
# chunking/agency_catalog.py:20-22 and chunking/entity_stamper.py:32.
DEFAULT_CATALOG_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "fund-catalog.yaml"
)


def id_to_name(path: Path | str | None = None) -> dict[str, str]:
    """Return `{canonical_id: canonical_name}` for every fund in the catalog.

    Cached per path (the file is committed and does not change mid-process
    — same tradeoff `chunking/agency_catalog.py` makes). Any parse failure
    — the file is missing, the YAML is malformed, the top level isn't a
    mapping — degrades to `{}` rather than raising, because a fund-name
    lookup is a display nicety and must never be able to crash a live
    conversation.
    """
    try:
        return _load_cached(str(Path(path) if path is not None else DEFAULT_CATALOG_PATH))
    except Exception:
        return {}


@lru_cache(maxsize=None)
def _load_cached(path_str: str) -> dict[str, str]:
    raw = yaml.safe_load(Path(path_str).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return {}
    out: dict[str, str] = {}
    for entry in raw.get("funds", []) or []:
        if not isinstance(entry, dict):
            continue
        canonical_id = entry.get("canonical_id")
        # An entry with no canonical_id can't be referenced by a stamped
        # chunk, so it can't be looked up either — skip rather than key on
        # a blank. Mirrors chunking/agency_catalog.py::_load_cached.
        if not canonical_id:
            continue
        out[str(canonical_id)] = str(entry.get("canonical_name") or "")
    return out
