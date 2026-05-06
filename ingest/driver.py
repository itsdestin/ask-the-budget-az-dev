"""Top-level ingest orchestrator.

Reads ``data/ingest-plan.yaml``, walks each week's target list, and for
each target either:
  - **Discovery-driven** (JLBC TOC walks): expands into one ingest item
    per discovered URL via ``ingest.discovery.discover``.
  - **Local-path** (DOCX bills, AFRs, Gov budgets): produces exactly
    one ingest item pointing at a pre-acquired file.

Each item is a (url-or-path, leaf-doc_type) pair the dispatcher knows
how to extract. The driver itself does not call extract() inside the
test loop — actual extraction takes minutes per doc and runs from
``scripts/run_phase_1a.py``. Tests cover plan parsing, target
resolution, and doc-id generation; the integration smoke that fires
real MinerU lives in WS6.

## doc_id convention

Stable per-doc identifier used as the extraction-output dir name and
as the chunk-table foreign key. Format depends on doc class:

  jlbc-baseline-fy2027-s18           # JLBC baseline cross-cut
  jlbc-approps-fy2026-bh2            # JLBC approps cross-cut
  jlbc-baseline-fy2027-axs           # JLBC per-agency
  agao-afr-fy2025                    # AFR singleton
  governor-governors-budget-fy2027   # Gov SAD singleton
  legislature-budget-bill-fy2026-sb1735-2025  # bill singleton + bill_id

Why collapse the leaf doc_type to the doc-class for JLBC? Because
``jlbc-s-pdf-fy2027-s18`` is redundant — the `s18` in the filename
already encodes that it's an s-PDF. Following the convention from
``samples/manifest.yaml``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ingest.cache import DownloadCache
from ingest.discovery import (
    AgencyIndexEntry,
    ApproprsTOCEntry,
    BaselineLinksEntry,
    DiscoveryCache,
    discover,
)


# section_kind from cross-cut TOC walkers → leaf doc_type for the dispatcher.
_SECTION_KIND_TO_DOC_TYPE: dict[str, str] = {
    "summary-section": "s-pdf",
    "budget-highlights": "bh-pdf",
    "budget-detail": "bd-pdf",
    "detailed-list": "detailed-list-pdf",
    "topic": "topic-pdf",
}


# Plan doc_types that drive discovery (vs. local-path or singleton targets).
_DISCOVERY_DOC_TYPES: frozenset[str] = frozenset({
    "baseline-cross-cut",
    "approps-cross-cut",
    "baseline-per-agency",
    "approps-per-agency",
})


# ----------------------------------------------------------------------------
# Types
# ----------------------------------------------------------------------------


@dataclass(frozen=True)
class IngestTarget:
    """One row in the plan's week_N list."""

    publisher: str
    doc_type: str                 # plan-level doc_type (may be a discovery class)
    fiscal_year: int
    source_format: str | None = None
    local_path: Path | None = None
    bill_id: str | None = None    # only for budget-bill targets


@dataclass(frozen=True)
class IngestItem:
    """One concrete ingestion unit — what the dispatcher actually runs."""

    publisher: str
    doc_type: str                 # LEAF doc_type (s-pdf, bh-pdf, afr, etc.)
    fiscal_year: int
    source_format: str            # 'pdf' | 'docx'
    doc_id: str
    url: str | None = None
    local_path: Path | None = None


@dataclass(frozen=True)
class ResolvedTarget:
    """The expansion of one IngestTarget into its concrete items."""

    target: IngestTarget
    items: tuple[IngestItem, ...]


# ----------------------------------------------------------------------------
# Plan loader
# ----------------------------------------------------------------------------


_REQUIRED_TARGET_FIELDS = ("publisher", "doc_type", "fiscal_year")


def load_plan(path: Path | str) -> dict[str, Any]:
    """Load and validate a Phase 1a ingest plan YAML.

    Returns the parsed dict. Validates that every target row has the
    required (publisher, doc_type, fiscal_year) fields — a missing
    field is a configuration bug worth failing loud over.
    """
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"plan {path}: expected mapping at top level")

    for week_key in [k for k in raw if k.startswith("week_")]:
        for i, target in enumerate(raw[week_key]):
            for required in _REQUIRED_TARGET_FIELDS:
                if required not in target:
                    raise ValueError(
                        f"plan {path}: {week_key}[{i}] missing required "
                        f"field {required!r} (got keys: {sorted(target)})"
                    )
    return raw


# ----------------------------------------------------------------------------
# doc_id generation
# ----------------------------------------------------------------------------


# Leaf doc_types that resolve to the JLBC "baseline" class.
_JLBC_BASELINE_DOC_TYPES = frozenset({
    "s-pdf", "topic-pdf", "baseline-per-agency",
})

# Leaf doc_types that resolve to the JLBC "approps" class.
_JLBC_APPROPS_DOC_TYPES = frozenset({
    "bh-pdf", "bd-pdf", "detailed-list-pdf", "approps-per-agency",
})


def make_doc_id(
    *,
    publisher: str,
    doc_type: str,
    fiscal_year: int,
    filename: str | None = None,
    bill_id: str | None = None,
) -> str:
    """Construct the stable doc_id for one ingest item."""
    fy_str = f"fy{fiscal_year:04d}"

    if publisher == "jlbc":
        if doc_type in _JLBC_BASELINE_DOC_TYPES:
            class_ = "baseline"
        elif doc_type in _JLBC_APPROPS_DOC_TYPES:
            class_ = "approps"
        else:
            class_ = doc_type
        if filename is None:
            return f"{publisher}-{class_}-{fy_str}"
        stem = Path(filename).stem
        return f"{publisher}-{class_}-{fy_str}-{stem}"

    # Singleton (one-doc-per-publisher-per-FY): just publisher + doc_type + fy.
    base = f"{publisher}-{doc_type}-{fy_str}"
    return f"{base}-{bill_id}" if bill_id else base


# ----------------------------------------------------------------------------
# Target resolution
# ----------------------------------------------------------------------------


def _entry_to_item(
    entry: AgencyIndexEntry | ApproprsTOCEntry | BaselineLinksEntry,
    *,
    target: IngestTarget,
) -> IngestItem:
    """Convert one discovered entry into an IngestItem."""
    if isinstance(entry, AgencyIndexEntry):
        leaf_doc_type = target.doc_type           # baseline-per-agency / approps-per-agency
        filename = f"{entry.slug}.pdf"
    else:  # cross-cut entry
        leaf_doc_type = _SECTION_KIND_TO_DOC_TYPE.get(entry.section_kind)
        if leaf_doc_type is None:
            raise ValueError(
                f"unknown section_kind {entry.section_kind!r} on entry {entry!r} "
                "— update _SECTION_KIND_TO_DOC_TYPE"
            )
        filename = entry.filename

    doc_id = make_doc_id(
        publisher=target.publisher,
        doc_type=leaf_doc_type,
        fiscal_year=target.fiscal_year,
        filename=filename,
    )
    return IngestItem(
        publisher=target.publisher,
        doc_type=leaf_doc_type,
        fiscal_year=target.fiscal_year,
        source_format="pdf",
        doc_id=doc_id,
        url=entry.url,
    )


def _resolve_local_path(target: IngestTarget) -> ResolvedTarget:
    """Local-path branch: one item, no discovery."""
    assert target.local_path is not None
    if not target.local_path.exists():
        raise FileNotFoundError(
            f"local_path {target.local_path} does not exist. "
            "samples/raw-pdfs/ and samples/raw-docx/ are gitignored — "
            "did you forget to acquire the source file in this worktree?"
        )
    if target.source_format is None:
        raise ValueError(
            f"local-path target requires source_format "
            f"({target.publisher}/{target.doc_type}/{target.fiscal_year})"
        )
    item = IngestItem(
        publisher=target.publisher,
        doc_type=target.doc_type,
        fiscal_year=target.fiscal_year,
        source_format=target.source_format,
        doc_id=make_doc_id(
            publisher=target.publisher,
            doc_type=target.doc_type,
            fiscal_year=target.fiscal_year,
            bill_id=target.bill_id,
        ),
        local_path=target.local_path,
    )
    return ResolvedTarget(target=target, items=(item,))


def _resolve_discovery(
    target: IngestTarget,
    *,
    download_cache_root: Path,
    discovery_cache_path: Path,
) -> ResolvedTarget:
    """Discovery-driven branch: walk JLBC TOC, expand into per-section items."""
    download = DownloadCache(download_cache_root)
    discovery = DiscoveryCache(discovery_cache_path)
    result = discover(
        target.publisher,
        target.doc_type,
        target.fiscal_year,
        download_cache=download,
        discovery_cache=discovery,
    )
    items = tuple(_entry_to_item(e, target=target) for e in result.entries)
    return ResolvedTarget(target=target, items=items)


def resolve_target(
    target: IngestTarget,
    *,
    download_cache_root: Path | None = None,
    discovery_cache_path: Path | None = None,
) -> ResolvedTarget:
    """Expand one IngestTarget into a ResolvedTarget."""
    if target.local_path is not None:
        return _resolve_local_path(target)

    if target.doc_type not in _DISCOVERY_DOC_TYPES:
        raise ValueError(
            f"resolve_target: target {target.doc_type!r} has no local_path AND "
            f"is not a discovery doc_type (one of {sorted(_DISCOVERY_DOC_TYPES)}). "
            "Either add local_path: <path> to the plan row or use a "
            "discovery-supported doc_type."
        )
    if download_cache_root is None or discovery_cache_path is None:
        raise ValueError(
            "discovery-driven resolution requires download_cache_root and "
            "discovery_cache_path"
        )
    return _resolve_discovery(
        target,
        download_cache_root=download_cache_root,
        discovery_cache_path=discovery_cache_path,
    )
