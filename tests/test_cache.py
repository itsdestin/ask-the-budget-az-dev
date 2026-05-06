"""Tests for ingest.cache.DownloadCache.

Cache design (per Phase 1a plan Workstream 2 Task 2.1):
- sha256-keyed storage at ``<root>/<sha256-prefix>/<sha256>.pdf``
- YAML manifest at ``<root>/manifest.yaml`` keyed by URL
- Manifest entry: ``{sha256, byte_size, fetched_at, relative_path}``
- Fetch is idempotent: re-fetching a cached URL returns the same Path
  without invoking the network

Tests use an injected fake fetcher (Callable[[str], bytes]) so no
network is touched. A single integration test that hits a real URL
lives under tests/integration/ (not run by default).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

import pytest

from ingest.cache import DownloadCache


# --- Helpers ---


def _sha256(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


class _FakeFetcher:
    """Records calls; returns canned bytes per URL."""

    def __init__(self, responses: dict[str, bytes]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def __call__(self, url: str) -> bytes:
        self.calls.append(url)
        try:
            return self.responses[url]
        except KeyError as e:
            raise RuntimeError(f"fake fetcher: no response for {url}") from e


# --- Round trip ---


def test_cache_fetch_returns_path_to_local_file(tmp_path: Path) -> None:
    body = b"%PDF-1.7\n...minimal pdf body..."
    fetcher = _FakeFetcher({"https://example.com/x.pdf": body})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    path = cache.fetch("https://example.com/x.pdf")

    assert path.exists()
    assert path.read_bytes() == body


def test_cache_second_fetch_skips_network(tmp_path: Path) -> None:
    body = b"second-fetch-body"
    fetcher = _FakeFetcher({"https://example.com/y.pdf": body})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    p1 = cache.fetch("https://example.com/y.pdf")
    p2 = cache.fetch("https://example.com/y.pdf")

    assert p1 == p2
    # Network was hit exactly once — second call read from local cache.
    assert fetcher.calls == ["https://example.com/y.pdf"]


# --- Layout + integrity ---


def test_cache_stores_under_sha256_prefix_path(tmp_path: Path) -> None:
    body = b"layout-body"
    expected_sha = _sha256(body)
    fetcher = _FakeFetcher({"https://example.com/z.pdf": body})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    path = cache.fetch("https://example.com/z.pdf")

    # Layout: <root>/<first-2-hex>/<full-sha>.pdf
    expected_relative = Path(expected_sha[:2]) / f"{expected_sha}.pdf"
    assert path == tmp_path / expected_relative


def test_cache_verifies_sha256_after_write(tmp_path: Path) -> None:
    """If a fetcher returns bytes whose hash is provably stable, the
    cache must produce a file whose on-disk sha256 matches the bytes
    received. We verify the contract — not just that we computed the
    right hash, but that we re-read what we wrote."""
    body = b"integrity-check"
    expected_sha = _sha256(body)
    fetcher = _FakeFetcher({"https://example.com/integ.pdf": body})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    path = cache.fetch("https://example.com/integ.pdf")
    on_disk_sha = _sha256(path.read_bytes())

    assert on_disk_sha == expected_sha


# --- Manifest ---


def test_cache_manifest_records_required_metadata(tmp_path: Path) -> None:
    import yaml

    body = b"manifest-body" * 4
    expected_sha = _sha256(body)
    fetcher = _FakeFetcher({"https://example.com/m.pdf": body})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    cache.fetch("https://example.com/m.pdf")

    manifest_path = tmp_path / "manifest.yaml"
    assert manifest_path.exists()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    entry = manifest["entries"]["https://example.com/m.pdf"]
    assert entry["sha256"] == expected_sha
    assert entry["byte_size"] == len(body)
    assert "fetched_at" in entry
    # ISO-8601 with timezone (UTC). Round-trip via fromisoformat to assert format.
    dt.datetime.fromisoformat(entry["fetched_at"])
    # Path stored as forward-slash relative for cross-platform manifest portability.
    assert entry["relative_path"] == f"{expected_sha[:2]}/{expected_sha}.pdf"


def test_cache_persists_across_instances(tmp_path: Path) -> None:
    body = b"persisted"
    fetcher = _FakeFetcher({"https://example.com/p.pdf": body})

    cache1 = DownloadCache(tmp_path, fetcher=fetcher)
    p1 = cache1.fetch("https://example.com/p.pdf")
    # Simulate process restart: new cache instance, same root.
    fetcher2 = _FakeFetcher({})  # no responses — must NOT be called
    cache2 = DownloadCache(tmp_path, fetcher=fetcher2)

    assert cache2.has("https://example.com/p.pdf")
    p2 = cache2.fetch("https://example.com/p.pdf")
    assert p2 == p1
    assert fetcher2.calls == []  # second instance read manifest, did not fetch


# --- Has-check ---


def test_cache_has_returns_false_for_unfetched_url(tmp_path: Path) -> None:
    cache = DownloadCache(tmp_path, fetcher=_FakeFetcher({}))
    assert not cache.has("https://example.com/nope.pdf")


# --- Defensive cases ---


def test_cache_redownloads_when_local_file_corrupted(tmp_path: Path) -> None:
    """If something tampers with the cached file on disk, the next
    fetch should detect the sha mismatch and re-fetch. Without this,
    silent corruption would propagate downstream into chunking."""
    body_v1 = b"original-content"
    body_v2 = b"refetched-content"
    fetcher = _FakeFetcher({"https://example.com/c.pdf": body_v1})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    path = cache.fetch("https://example.com/c.pdf")

    # Tamper with the on-disk file.
    path.write_bytes(b"corrupted")

    # Re-prime fetcher with new bytes to confirm it's actually called.
    fetcher.responses["https://example.com/c.pdf"] = body_v2
    fetcher.calls = []

    path2 = cache.fetch("https://example.com/c.pdf")
    assert path2.read_bytes() == body_v2
    assert fetcher.calls == ["https://example.com/c.pdf"]


def test_cache_raises_on_sha256_mismatch_during_initial_fetch(tmp_path: Path) -> None:
    """If a caller passes ``expected_sha256`` and the downloaded bytes
    don't match, raise — don't silently cache wrong content. Used when
    the manifest gives us a known-good sha (e.g., samples/manifest.yaml
    pre-validated checksums)."""
    body = b"some-bytes"
    fetcher = _FakeFetcher({"https://example.com/v.pdf": body})
    cache = DownloadCache(tmp_path, fetcher=fetcher)

    wrong_sha = "0" * 64
    with pytest.raises(ValueError, match="sha256"):
        cache.fetch("https://example.com/v.pdf", expected_sha256=wrong_sha)
