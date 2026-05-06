"""Tests for ingest.discovery.discover — the orchestrator that wraps
the three TOC walkers and caches their output.

Cache invariants:
- A repeat call with the same (publisher, doc_type, fy) and the same
  source PDF sha256 returns cached entries without re-walking.
- A change to the source PDF's sha256 invalidates the cached entry
  and triggers a fresh walk.
- The cache persists across DiscoveryCache instances (i.e., across
  driver runs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ingest.cache import DownloadCache
from ingest.discovery import (
    AgencyIndexEntry,
    ApproprsTOCEntry,
    BaselineLinksEntry,
    DiscoveryCache,
    DiscoveryResult,
    discover,
)
from ingest.url_conventions import baseline_links_url

# Live cache populated by earlier WS1-T1.2 tests; reused so we don't
# repeat the same network fetches on every test session.
_LIVE_CACHE_ROOT = Path("data/cached-pdfs")


@pytest.fixture(scope="module")
def download_cache() -> DownloadCache:
    return DownloadCache(_LIVE_CACHE_ROOT)


# --- discover dispatches by doc_type ---


@pytest.mark.network
def test_discover_baseline_cross_cut_returns_typed_result(
    tmp_path: Path,
    download_cache: DownloadCache,
) -> None:
    discovery_cache = DiscoveryCache(tmp_path / "discovery-cache.yaml")
    result = discover(
        "jlbc",
        "baseline-cross-cut",
        2027,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    assert isinstance(result, DiscoveryResult)
    assert result.publisher == "jlbc"
    assert result.doc_type == "baseline-cross-cut"
    assert result.fiscal_year == 2027
    assert result.source_url == baseline_links_url(2027)
    assert len(result.source_sha256) == 64  # hex sha256
    # Entries are typed BaselineLinksEntry instances.
    assert all(isinstance(e, BaselineLinksEntry) for e in result.entries)
    assert len(result.entries) >= 10


@pytest.mark.network
def test_discover_approps_cross_cut_dispatches_to_correct_walker(
    tmp_path: Path,
    download_cache: DownloadCache,
) -> None:
    discovery_cache = DiscoveryCache(tmp_path / "discovery-cache.yaml")
    result = discover(
        "jlbc",
        "approps-cross-cut",
        2026,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    assert all(isinstance(e, ApproprsTOCEntry) for e in result.entries)


@pytest.mark.network
def test_discover_baseline_per_agency_dispatches_to_agency_index(
    tmp_path: Path,
    download_cache: DownloadCache,
) -> None:
    discovery_cache = DiscoveryCache(tmp_path / "discovery-cache.yaml")
    result = discover(
        "jlbc",
        "baseline-per-agency",
        2027,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    assert all(isinstance(e, AgencyIndexEntry) for e in result.entries)


def test_discover_rejects_unknown_publisher(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="publisher"):
        discover(
            "agao",  # AFR has no JLBC-style URL convention
            "afr",
            2025,
            discovery_cache=DiscoveryCache(tmp_path / "d.yaml"),
        )


def test_discover_rejects_unknown_doc_type(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="doc_type"):
        discover(
            "jlbc",
            "nonsense-cross-cut",
            2027,
            discovery_cache=DiscoveryCache(tmp_path / "d.yaml"),
        )


# --- Cache hit / miss / invalidation ---


@pytest.mark.network
def test_discover_skips_walk_on_cache_hit(
    tmp_path: Path,
    download_cache: DownloadCache,
) -> None:
    discovery_cache = DiscoveryCache(tmp_path / "discovery-cache.yaml")

    r1 = discover(
        "jlbc", "baseline-cross-cut", 2027,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    # On second call, walker count must NOT increment.
    walks_before = discovery_cache.walk_count
    r2 = discover(
        "jlbc", "baseline-cross-cut", 2027,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    walks_after = discovery_cache.walk_count
    assert walks_before == walks_after, "second call should not re-walk"
    assert r1.source_sha256 == r2.source_sha256
    assert [e.filename for e in r1.entries] == [e.filename for e in r2.entries]


@pytest.mark.network
def test_discover_invalidates_when_source_pdf_changes(
    tmp_path: Path,
    download_cache: DownloadCache,
) -> None:
    """If the source TOC PDF's sha shifts (JLBC reissues), the cache
    must invalidate and re-walk. Simulated by overwriting the cached
    entry with a wrong sha."""
    discovery_cache = DiscoveryCache(tmp_path / "discovery-cache.yaml")

    discover(
        "jlbc", "baseline-cross-cut", 2027,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    walks_before_invalidate = discovery_cache.walk_count

    # Hand-corrupt the cache entry's sha to force invalidation.
    discovery_cache.set_source_sha_for_test(
        "jlbc", "baseline-cross-cut", 2027, "0" * 64,
    )

    discover(
        "jlbc", "baseline-cross-cut", 2027,
        download_cache=download_cache,
        discovery_cache=discovery_cache,
    )
    assert discovery_cache.walk_count == walks_before_invalidate + 1


@pytest.mark.network
def test_discovery_cache_persists_across_instances(
    tmp_path: Path,
    download_cache: DownloadCache,
) -> None:
    cache_path = tmp_path / "discovery-cache.yaml"

    cache_a = DiscoveryCache(cache_path)
    discover(
        "jlbc", "baseline-cross-cut", 2027,
        download_cache=download_cache,
        discovery_cache=cache_a,
    )

    # New instance, same file — should read existing cache.
    cache_b = DiscoveryCache(cache_path)
    walks_before = cache_b.walk_count
    discover(
        "jlbc", "baseline-cross-cut", 2027,
        download_cache=download_cache,
        discovery_cache=cache_b,
    )
    assert cache_b.walk_count == walks_before, "new instance should hit existing cache"
