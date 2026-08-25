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

import re
from functools import lru_cache
from pathlib import Path

import yaml

# Words that mark a complete fund name. Split out so the WHY below can talk
# about the rule in one place.
_FUND_WORDS = ("fund",)
_TAIL_WORDS = ("account", "subaccount", "grant")


def _looks_like_a_fund_name(name: str) -> bool:
    """ALLOWLIST, not a denylist — measured 2026-08-22, at Destin's ask.

    The catalog's fund column is polluted: its parser took whatever sat in
    that column of JLBC's fund schedules, which includes schedule artifacts.
    Audited against the live corpus (see the fund-names spec's post-ship
    audit section): of 187 stamped ids, the pollution includes 18 stamped
    `Total -`/`SUBTOTAL` rows, at least 8 AGENCY names filed as funds
    ("Department of Juvenile Corrections"), budget-adjustment lines
    ("FY 2026 Unallocated Salary Adjustments"), and truncations — the worst
    being the single word "Account", which the ingest stamper then matched
    as a substring inside "Accounting" onto 5,238 chunks across 143
    agencies, the most-stamped "fund" in the corpus.

    A denylist needed six leaky rules and still missed classes on each
    measuring pass. This allowlist — at least two words, and either the
    word "fund" somewhere or an "account"/"subaccount" tail — was run over
    all 227 entries and every name it hides was read: each is pollution or
    a visible mid-phrase truncation, and all four kept names lacking the
    word "fund" are real funds (e.g. "Consumer Remediation Subaccount").
    A hidden name renders as its raw `fund:` id — this repo's doctrine is
    that a visible code beats a plausible wrong name. Cost: 138 of 187
    stamped ids carry names; the other 49 are the pollution itself.
    """
    words = re.findall(r"[a-z0-9']+", name.lower())
    if len(words) < 2:
        return False
    return any(w in words for w in _FUND_WORDS) or words[-1] in _TAIL_WORDS

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
        name = str(entry.get("canonical_name") or "")
        # A name that does not read as a complete fund name is withheld, so
        # the id renders as its honest raw code — see _looks_like_a_fund_name.
        if not _looks_like_a_fund_name(name):
            continue
        out[str(canonical_id)] = name
    return out
