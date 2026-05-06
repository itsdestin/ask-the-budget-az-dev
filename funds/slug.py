"""Fund-name → slug derivation.

JLBC issues no per-fund URL slug (unlike per-agency slugs which the
`<slug>.pdf` filename gives for free), so we generate them. The catalog
builder runs slug derivation once over the full fund list and emits the
result to `data/fund-catalog.yaml`; downstream stamping reads that file
and never re-runs derivation. Stable input → stable slug is the only
contract.

Rules (plan §4.1 step 3):
  1. Lowercase.
  2. Replace non-alphanumeric runs with a single `-`.
  3. Drop a trailing standalone `fund` token (the suffix is informational
     boilerplate; almost every JLBC fund name ends with it).
  4. Collapse consecutive hyphens / strip leading + trailing hyphens.

Edge cases:
  - The bare word `Fund` slugifies to `''` (legitimately empty — the
    suffix-stripping rule is what removed all content).
  - `Trust Fund Reserve` keeps `fund` because it's internal, not trailing.
"""
from __future__ import annotations

import re

_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def slugify_fund_name(name: str) -> str:
    """Derive a stable URL-safe slug from a fund name.

    See module docstring for the rules. Returns an empty string for input
    that produces no alphanumeric content after slugification.
    """
    if not name:
        return ""

    # Step 1+2: lowercase and replace non-alphanumeric runs with hyphens.
    out = _NON_ALNUM_RE.sub("-", name.casefold())
    out = out.strip("-")
    if not out:
        return ""

    # Step 3: drop trailing `fund` token. Token boundary is hyphen since
    # we've already collapsed everything to hyphen-separated lowercase.
    if out.endswith("-fund"):
        out = out[: -len("-fund")]
    elif out == "fund":
        out = ""

    # Step 4: collapsing already happened in the regex (`+` quantifier);
    # but stripping again handles the case where the suffix removal left
    # a trailing hyphen.
    return out.strip("-")
