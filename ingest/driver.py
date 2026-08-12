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
from ingest.doc_types import has_stage_field, is_one_per_year
from ingest.section_types import SECTION_KIND_TO_DOC_TYPE


def slugify_stem(stem: str) -> str:
    """Filename stem -> a doc_id-safe slug.

    Agency submissions arrive with human filenames full of spaces and
    percent-encoding ('BHA FY27 Executive Budget Submission.pdf'), unlike the
    JLBC books' terse '508.pdf'. A doc_id ends up in URLs and citation
    payloads, so it is lowercased and reduced to [a-z0-9-].
    """
    out = "".join(c if c.isalnum() else "-" for c in stem.lower())
    while "--" in out:
        out = out.replace("--", "-")
    return out.strip("-")


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

# The two JLBC report families. A "family" is which BOOK a document came out
# of; the class above is only a guess at that, inferred from the filename
# convention the section happens to follow.
_JLBC_FAMILIES = frozenset({"baseline", "approps"})


def make_doc_id(
    *,
    publisher: str,
    doc_type: str,
    fiscal_year: int,
    filename: str | None = None,
    bill_id: str | None = None,
    family: str | None = None,
    stage: str | None = None,
) -> str:
    """Construct the stable doc_id for one ingest item.

    `family` ("baseline" | "approps") is which JLBC book the document came
    out of, and callers that know it MUST pass it.

    WHY it has to be part of the identity: both books number their sections
    with the same conventions, so `doc_type` alone cannot tell them apart.
    `508.pdf` is a detailed-list filename in BOTH books, and `capitaloutlay.pdf`
    is a topic filename in both — so without the family two different documents
    of the same fiscal year mint the SAME doc_id, and because a write is an
    upsert the second one silently replaces the first. Two such pairs were
    found in the FY2026 corpus; nothing errored, a document just vanished.

    Passing the family only changes the id for the shape that was misfiled in
    the first place (family != the class its doc_type implies) — every other
    document keeps the exact id the live corpus and `eval/queries.yaml` already
    depend on. Callers that genuinely do not know the family (a person
    uploading a file by hand, singleton publishers) omit it and get the legacy
    id unchanged.

    `stage` ("introduced" | "engrossed") is folded into the id ONLY for a
    doc_type that declares `stage_field: true` in the registry (one today:
    budget-bill-summary). WHY: JLBC often reuses the identical filename for
    both stages of one session ("budgetbills.pdf"), and stage is the ONLY
    thing distinguishing those two documents. Without this, two such uploads
    mint the same doc_id and the second — an upsert — silently replaces the
    first with neither request erroring (review finding, 2026-08-11; same
    shape as the family collision above). Every other doc_type ignores
    `stage` entirely, so no existing id changes: `has_stage_field` defaults
    unknown/undeclared types to False, the safe direction.
    """
    fy_str = f"fy{fiscal_year:04d}"

    if family is not None and family not in _JLBC_FAMILIES:
        # Loud, not lenient: a typo'd family would quietly mint a whole third
        # namespace of ids that no search or citation would ever resolve.
        raise ValueError(
            f"family must be one of {sorted(_JLBC_FAMILIES)} or None, got {family!r}"
        )

    stage_suffix = ""
    if stage is not None and stage.strip() and has_stage_field(doc_type):
        stage_suffix = f"-{stage.strip().lower()}"

    if publisher == "jlbc":
        if doc_type in _JLBC_BASELINE_DOC_TYPES:
            class_ = "baseline"
        elif doc_type in _JLBC_APPROPS_DOC_TYPES:
            class_ = "approps"
        else:
            class_ = doc_type
        # The family is the ground truth; the doc_type-derived class is only a
        # proxy for it. Where they disagree the proxy is simply wrong, so the
        # family wins. Where they agree — which is every document except the
        # misfiled shape — the id is byte-identical to the legacy one.
        if family is not None and class_ in _JLBC_FAMILIES:
            class_ = family
        if filename is None:
            return f"{publisher}-{class_}-{fy_str}{stage_suffix}"
        stem = Path(filename).stem
        return f"{publisher}-{class_}-{fy_str}-{stem}{stage_suffix}"

    # Non-JLBC publishers.
    #
    # WHY the registry decides instead of the publisher: this branch used to
    # assume one document per publisher per fiscal year and DROP `filename`
    # entirely. That is true for the AFR and the Executive Budget and false
    # for agency submissions (78 in FY2027). Measured 2026-08-11: every
    # agency submission minted 'governor-agency-submission-fy2027', and
    # because a write is an upsert they would have collapsed into one
    # document with nothing erroring.
    #
    # Existing ids are unchanged because afr and governors-budget are declared
    # `one_per_year: true` -- pinned by test_one_per_year_types_keep_their_
    # EXACT_existing_ids, which asserts the literal strings the live corpus
    # carries.
    base = f"{publisher}-{doc_type}-{fy_str}"
    if bill_id:
        return f"{base}-{bill_id}{stage_suffix}"
    if is_one_per_year(doc_type):
        return f"{base}{stage_suffix}"
    if filename is None:
        return f"{base}{stage_suffix}"
    return f"{base}-{slugify_stem(Path(filename).stem)}{stage_suffix}"


# ----------------------------------------------------------------------------
# Target resolution
# ----------------------------------------------------------------------------


def _family_of(target: IngestTarget) -> str | None:
    """Which JLBC book a plan target draws from, or None if it isn't a book.

    Plan doc_types are already family-prefixed (`baseline-cross-cut`,
    `approps-per-agency`), so the family is sitting right there — it just
    never reached `make_doc_id`, which is how the two books ended up able to
    mint the same id for different documents.
    """
    if target.publisher != "jlbc":
        return None
    head = target.doc_type.split("-", 1)[0]
    return head if head in _JLBC_FAMILIES else None


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
        leaf_doc_type = SECTION_KIND_TO_DOC_TYPE.get(entry.section_kind)
        if leaf_doc_type is None:
            raise ValueError(
                f"unknown section_kind {entry.section_kind!r} on entry {entry!r} "
                "— update ingest.section_types.SECTION_KIND_TO_DOC_TYPE"
            )
        filename = entry.filename

    doc_id = make_doc_id(
        publisher=target.publisher,
        doc_type=leaf_doc_type,
        fiscal_year=target.fiscal_year,
        filename=filename,
        family=_family_of(target),
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
