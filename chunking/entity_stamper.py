"""Entity stamper.

Per chunk-shape D7 — entity normalization is required, not optional. Three
resolution rules per cross-doc-relationships §5:

  1. Direct slug match (JLBC URL gives slug for free)
  2. Alias map lookup (`samples/agency-slug-aliases.yaml`)
  3. Name-based match against entity catalog with rapidfuzz fallback

Loads the catalog + aliases YAMLs once at construction. `stamp(chunk, *,
source_url=None)` returns a new Chunk with `agency_canonical_id` set when
a match is found, plus the alias-hop chain on `chunk.alias_chain`.

If the chunk already has `agency_canonical_id`, stamp() is a passthrough —
re-running resolution can only weaken a deliberately-set value.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from rapidfuzz import fuzz, process

from chunking.types import Chunk

_DEFAULT_CATALOG = Path(__file__).resolve().parent.parent / "samples" / "entity-catalog.yaml"
_DEFAULT_ALIASES = Path(__file__).resolve().parent.parent / "samples" / "agency-slug-aliases.yaml"

# Cross-cutting topic PDFs — never resolve to a per-agency canonical_id.
# Mirror of `_TOPIC_SLUGS` in ingest/discovery.py.
_TOPIC_SLUGS = frozenset({"capitaloutlay", "agencyindex", "crr", "tobacco", "csbg"})

# JLBC URL slug-extraction patterns. Two host families per url_conventions.py:
#   https://www.azjlbc.gov/<YY>baseline/<slug>.pdf       (FY23+ baselines)
#   https://www.azjlbc.gov/<YY>ar/<slug>.pdf             (FY23+ approps)
#   http://www.azleg.gov/jlbc/<YY>AR/<slug>.pdf          (FY15-FY22 approps)
_JLBC_URL_RE = re.compile(
    r"^https?://(?:www\.azjlbc\.gov/(?:\d{2}baseline|\d{2}ar)/"
    r"|www\.azleg\.gov/jlbc/\d{2}AR/)([a-z0-9_\-]+)\.pdf$",
    re.IGNORECASE,
)

# Fuzzy-match floor — rapidfuzz token_set_ratio. Plan: ≥ 85.
_FUZZY_THRESHOLD = 85


def slug_from_jlbc_url(url: str | None) -> str | None:
    """Extract the per-agency slug from a JLBC URL, or None if the URL is
    a non-JLBC publisher OR the slug is a cross-cutting topic file (which
    has no single canonical_id)."""
    if not url:
        return None
    m = _JLBC_URL_RE.match(url)
    if not m:
        return None
    slug = m.group(1).lower()
    if slug in _TOPIC_SLUGS:
        return None
    return slug


@dataclass
class _CatalogEntry:
    canonical_id: str
    canonical_name: str
    slug: str | None
    name_variants: list[str] = field(default_factory=list)


class EntityStamper:
    """Resolves a chunk's `agency_canonical_id` from URL, slug, or name."""

    def __init__(
        self,
        *,
        catalog_path: Path | str,
        aliases_path: Path | str,
    ) -> None:
        self._slug_to_id: dict[str, str] = {}
        self._name_to_id: dict[str, str] = {}
        self._all_names: list[str] = []  # for fuzzy match
        self._alias_to_canonical_slug: dict[str, str] = {}

        self._load_catalog(Path(catalog_path))
        self._load_aliases(Path(aliases_path))

    @classmethod
    def from_default_paths(cls) -> "EntityStamper":
        """Construct with the workspace's default catalog + aliases paths."""
        return cls(catalog_path=_DEFAULT_CATALOG, aliases_path=_DEFAULT_ALIASES)

    # --- loading ------------------------------------------------------------

    def _load_catalog(self, path: Path) -> None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        agencies = raw.get("agencies", []) or []
        for entry in agencies:
            canonical_id = entry.get("canonical_id")
            canonical_name = entry.get("canonical_name") or ""
            slug = entry.get("slug")
            if not canonical_id:
                continue

            if slug:
                self._slug_to_id[slug.lower()] = canonical_id

            # Name → id index. Use casefolded form as key.
            for name in self._collect_names(entry):
                key = _normalize_for_match(name)
                if key and key not in self._name_to_id:
                    self._name_to_id[key] = canonical_id
                if name and name not in self._all_names:
                    self._all_names.append(name)

    @staticmethod
    def _collect_names(entry: dict) -> list[str]:
        names: list[str] = []
        canonical = entry.get("canonical_name")
        if canonical:
            names.append(canonical)
            # Also add inverted form: 'X, Department of' <-> 'Department of X'
            inverted = _invert_comma_form(canonical)
            if inverted and inverted != canonical:
                names.append(inverted)
        # JLBC observed names from the agency-index pages
        for variants in (entry.get("names_observed_jlbc") or {}):
            if variants:
                names.append(variants)
        # Gov-side alias if present
        gov_alias = entry.get("gov_alias") or entry.get("names_observed_gov")
        if isinstance(gov_alias, str):
            names.append(gov_alias)
        elif isinstance(gov_alias, list):
            names.extend(s for s in gov_alias if isinstance(s, str))
        elif isinstance(gov_alias, dict):
            names.extend(s for s in gov_alias if isinstance(s, str))
        return [n for n in names if n]

    def _load_aliases(self, path: Path) -> None:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for rename in raw.get("renames", []) or []:
            new_slug = rename.get("new_slug")
            if not new_slug:
                continue
            old_slug = rename.get("old_slug")
            if old_slug:
                self._alias_to_canonical_slug[old_slug.lower()] = new_slug.lower()
            for s in rename.get("old_slugs", []) or []:
                if s:
                    self._alias_to_canonical_slug[s.lower()] = new_slug.lower()

    # --- public API ---------------------------------------------------------

    def stamp(self, chunk: Chunk, *, source_url: str | None = None) -> Chunk:
        """Return a new Chunk with `agency_canonical_id` resolved (or None
        if no match) and `alias_chain` listing any slug hops applied."""
        if chunk.agency_canonical_id:
            return chunk  # passthrough — already stamped

        canonical_id, alias_chain = self._resolve(
            section_path=chunk.section_path,
            text=chunk.text,
            source_url=source_url,
        )
        return chunk.model_copy(
            update={
                "agency_canonical_id": canonical_id,
                "alias_chain": alias_chain,
            }
        )

    # --- resolution rules ---------------------------------------------------

    def _resolve(
        self,
        *,
        section_path: list[str],
        text: str,
        source_url: str | None,
    ) -> tuple[str | None, list[str]]:
        # Rule 1: slug from URL (with rule-2 alias hop folded in)
        slug = slug_from_jlbc_url(source_url)
        if slug:
            alias_chain: list[str] = []
            canonical_slug = self._alias_to_canonical_slug.get(slug, slug)
            if canonical_slug != slug:
                alias_chain.append(slug)
            canonical_id = self._slug_to_id.get(canonical_slug)
            if canonical_id:
                return canonical_id, alias_chain
            # Fall through: slug looked JLBC-shaped but isn't in the catalog.
            # Try names anyway.

        # Rule 3: name-based match across section_path + text
        candidates = list(section_path) + _split_text_into_candidate_phrases(text)

        # Exact (normalized) match first
        for cand in candidates:
            key = _normalize_for_match(cand)
            if key and key in self._name_to_id:
                return self._name_to_id[key], []

        # Inverted-form match: catalog has 'X, Department of'; chunk says
        # 'Department of X'. Generate inverted candidates and try those.
        for cand in candidates:
            inverted = _invert_comma_form(cand) or _invert_comma_form_reversed(cand)
            if not inverted:
                continue
            key = _normalize_for_match(inverted)
            if key and key in self._name_to_id:
                return self._name_to_id[key], []

        # Fuzzy fallback: rapidfuzz token_set_ratio against canonical_names
        for cand in candidates:
            best = process.extractOne(
                cand,
                self._all_names,
                scorer=fuzz.token_set_ratio,
                score_cutoff=_FUZZY_THRESHOLD,
            )
            if best is not None:
                matched_name = best[0]
                key = _normalize_for_match(matched_name)
                canonical_id = self._name_to_id.get(key)
                if canonical_id:
                    return canonical_id, []

        return None, []


# --- text-normalization helpers ---------------------------------------------


_PUNCT_RE = re.compile(r"[^\w\s\-]")
_WS_RE = re.compile(r"\s+")


def _normalize_for_match(s: str) -> str:
    if not s:
        return ""
    out = s.casefold()
    out = _PUNCT_RE.sub(" ", out)
    out = _WS_RE.sub(" ", out).strip()
    return out


def _invert_comma_form(s: str) -> str | None:
    """Convert 'Corrections, Department of' → 'Department of Corrections'."""
    parts = [p.strip() for p in s.split(",", 1)]
    if len(parts) != 2:
        return None
    head, tail = parts
    if not tail:
        return None
    return f"{tail} {head}".strip()


def _invert_comma_form_reversed(s: str) -> str | None:
    """Convert 'Department of Corrections' → 'Corrections, Department of'.

    Looks for a leading 'Department of '/'Office of '/'Board of '/etc.; if
    found, swaps to comma form.
    """
    m = re.match(r"^(Department|Office|Board|Commission|Council|Authority)\s+of\s+(.+)$", s, re.IGNORECASE)
    if m:
        return f"{m.group(2).strip()}, {m.group(1).strip()} of"
    return None


def _split_text_into_candidate_phrases(text: str) -> list[str]:
    """Pull up to ~10 candidate name-phrases from chunk text. We don't run
    fuzzy match against every word in the body — just split into lines and
    use the first few non-trivial ones."""
    if not text:
        return []
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[:10]
