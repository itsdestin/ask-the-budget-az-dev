"""Tests for ingest.driver — the top-level ingest orchestrator.

The driver walks a YAML plan (data/ingest-plan.yaml), resolves each
target into a list of (url-or-local-path, doc_type) pairs to ingest,
and dispatches to download cache + extractor for each.

Test scope: plan loading, target resolution, doc-id generation, and
dry-run iteration. Actual extraction (which fires real MinerU /
OpenDataLoader and takes minutes per doc) is exercised manually via
``scripts/run_phase_1a.py``, not by the test suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from ingest.driver import (
    IngestTarget,
    ResolvedTarget,
    load_plan,
    make_doc_id,
    resolve_target,
)


# --- Plan loading ---


def test_load_plan_reads_yaml_into_dict(tmp_path: Path) -> None:
    plan_path = tmp_path / "p.yaml"
    plan_path.write_text(yaml.safe_dump({
        "order_hypothesis": "test",
        "week_1": [
            {"publisher": "jlbc", "doc_type": "baseline-cross-cut", "fiscal_year": 2027},
        ],
    }), encoding="utf-8")

    plan = load_plan(plan_path)

    assert plan["order_hypothesis"] == "test"
    assert len(plan["week_1"]) == 1


def test_load_plan_validates_required_target_fields(tmp_path: Path) -> None:
    """Each target must have publisher + doc_type + fiscal_year. Missing
    a required field is a configuration error — fail loud rather than
    silently skipping the row."""
    plan_path = tmp_path / "p.yaml"
    plan_path.write_text(yaml.safe_dump({
        "week_1": [{"publisher": "jlbc"}],  # missing doc_type, fiscal_year
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="doc_type|fiscal_year"):
        load_plan(plan_path)


def test_load_plan_workspace_yaml_parses_cleanly() -> None:
    """The repo's actual data/ingest-plan.yaml must round-trip through
    load_plan. Catches drift between what the plan author wrote and what
    the loader expects."""
    plan = load_plan(Path("data/ingest-plan.yaml"))
    assert "order_hypothesis" in plan
    assert "week_1" in plan
    # Order C: cross-cuts first — pin the doc_types of the first two
    # week_1 targets so a reordering can't slip in unnoticed.
    assert plan["week_1"][0]["doc_type"] == "baseline-cross-cut"
    assert plan["week_1"][1]["doc_type"] == "approps-cross-cut"


# --- Target resolution ---


@pytest.mark.network
def test_resolve_jlbc_baseline_cross_cut_returns_per_section_urls(
    tmp_path: Path,
) -> None:
    """A discovery-driven target expands into one URL per section in the
    discovered TOC."""
    target = IngestTarget(
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
    )

    resolved = resolve_target(
        target,
        download_cache_root=Path("data/cached-pdfs"),
        discovery_cache_path=Path("data/discovery-cache.yaml"),
    )

    assert isinstance(resolved, ResolvedTarget)
    # FY27 baselinelinks has 18 entries (16 s-PDFs + 2 topic) per WS1.
    # Each becomes its own per-doc ingest item.
    assert 15 <= len(resolved.items) <= 22
    # Each item carries enough metadata for the dispatcher to pick the
    # right extractor + the right doc_type for chunking.
    for item in resolved.items:
        assert item.url.startswith("https://www.azjlbc.gov/")
        # s-pdf and topic-pdf are the two leaf doc_types from the
        # baseline cross-cut walker.
        assert item.doc_type in {"s-pdf", "topic-pdf"}
        assert item.source_format == "pdf"
        assert item.publisher == "jlbc"
        assert item.fiscal_year == 2027


def test_resolve_local_path_target_returns_single_item(tmp_path: Path) -> None:
    """A local-path target (DOCX bills, AFRs) bypasses discovery and
    yields exactly one item."""
    src = tmp_path / "bill.docx"
    src.write_bytes(b"fake docx body")

    target = IngestTarget(
        publisher="legislature",
        doc_type="budget-bill",
        fiscal_year=2026,
        source_format="docx",
        local_path=src,
    )

    resolved = resolve_target(target)

    assert len(resolved.items) == 1
    item = resolved.items[0]
    assert item.local_path == src
    assert item.url is None
    assert item.doc_type == "budget-bill"
    assert item.source_format == "docx"


def test_resolve_local_path_must_exist() -> None:
    """A missing local_path is almost always a checkout-state issue
    (samples/raw-docx/ is gitignored). Fail loud with a path-pointed
    error."""
    target = IngestTarget(
        publisher="legislature",
        doc_type="budget-bill",
        fiscal_year=2026,
        source_format="docx",
        local_path=Path("nonexistent/budget-bill.docx"),
    )

    with pytest.raises(FileNotFoundError, match="nonexistent"):
        resolve_target(target)


# --- doc_id generation ---


def test_make_doc_id_for_jlbc_cross_cut() -> None:
    """jlbc cross-cut doc IDs encode publisher + doc_type-class + fy + filename."""
    assert make_doc_id(
        publisher="jlbc", doc_type="s-pdf", fiscal_year=2027, filename="s18.pdf",
    ) == "jlbc-baseline-fy2027-s18"
    assert make_doc_id(
        publisher="jlbc", doc_type="bh-pdf", fiscal_year=2026, filename="bh2.pdf",
    ) == "jlbc-approps-fy2026-bh2"
    assert make_doc_id(
        publisher="jlbc", doc_type="bd-pdf", fiscal_year=2026, filename="bd2.pdf",
    ) == "jlbc-approps-fy2026-bd2"
    assert make_doc_id(
        publisher="jlbc", doc_type="topic-pdf", fiscal_year=2027, filename="capitaloutlay.pdf",
    ) == "jlbc-baseline-fy2027-capitaloutlay"


def test_make_doc_id_for_per_agency() -> None:
    assert make_doc_id(
        publisher="jlbc", doc_type="baseline-per-agency", fiscal_year=2027, filename="axs.pdf",
    ) == "jlbc-baseline-fy2027-axs"
    assert make_doc_id(
        publisher="jlbc", doc_type="approps-per-agency", fiscal_year=2026, filename="dot.pdf",
    ) == "jlbc-approps-fy2026-dot"


def test_make_doc_id_for_singletons() -> None:
    """AFR, Gov budget, budget bill — ID is publisher + short-name + fy."""
    assert make_doc_id(
        publisher="agao", doc_type="afr", fiscal_year=2025,
    ) == "agao-afr-fy2025"
    assert make_doc_id(
        publisher="governor", doc_type="governors-budget", fiscal_year=2027,
    ) == "governor-governors-budget-fy2027"
    assert make_doc_id(
        publisher="legislature", doc_type="budget-bill", fiscal_year=2026,
        bill_id="sb1735-2025",
    ) == "legislature-budget-bill-fy2026-sb1735-2025"
