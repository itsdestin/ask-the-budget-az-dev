"""DownloadCache under concurrent writers (Plan 5 Task 20, step 2).

Two defects, both of which end in the same place: a manifest that will
not parse reads as an EMPTY cache, and an empty cache re-downloads
~7,400 PDFs from Arizona state web servers, one at a time.

1. The tmp file was `manifest.yaml.tmp` — one shared path for every
   instance and every thread. Two concurrent saves interleave their
   writes into that one file and then both `os.replace` it.
2. There was no lock and no re-read. Each instance loads the manifest
   once at construction and writes back its own in-memory copy, so the
   last writer silently erases every entry the other one added.

The Z13 backfill did not hit this only because the pre-fetch had already
cached 7,419 of 7,428 URLs before parallel ingest was enabled — saved by
the order things happened in, not by the design.
"""
from __future__ import annotations

import threading

import pytest
import yaml

from ingest.cache import DownloadCache


def _fetcher_for(payload: bytes):
    return lambda url: payload + url.encode()


def test_concurrent_threads_lose_no_entries(tmp_path):
    """32 threads on ONE cache instance. Every URL must survive."""
    cache = DownloadCache(tmp_path, fetcher=_fetcher_for(b"body-"))
    urls = [f"https://example.gov/doc{i}.pdf" for i in range(32)]
    errors: list[BaseException] = []

    def grab(url):
        try:
            cache.fetch(url)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=grab, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    on_disk = yaml.safe_load((tmp_path / "manifest.yaml").read_text())
    assert sorted(on_disk["entries"]) == sorted(urls)


def test_concurrent_separate_instances_lose_no_entries(tmp_path):
    """The harder case, and the real one.

    Separate DownloadCache objects each hold their own in-memory
    manifest, so a save that writes that copy wholesale erases whatever
    the other instance added. This is what two ingest workers — or two
    office machines pointed at the share — actually look like.
    """
    urls = [f"https://example.gov/sep{i}.pdf" for i in range(16)]
    errors: list[BaseException] = []

    def grab(url):
        try:
            DownloadCache(tmp_path, fetcher=_fetcher_for(b"body-")).fetch(url)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=grab, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    on_disk = yaml.safe_load((tmp_path / "manifest.yaml").read_text())
    assert sorted(on_disk["entries"]) == sorted(urls)


def test_the_manifest_always_parses_under_concurrency(tmp_path):
    """The consequence that matters. An unparseable manifest is not a
    crash — `_load_manifest` reads it as {} — so the symptom is a silent
    re-download of the whole corpus."""
    urls = [f"https://example.gov/parse{i}.pdf" for i in range(24)]

    def grab(url):
        DownloadCache(tmp_path, fetcher=_fetcher_for(b"x" * 500)).fetch(url)

    threads = [threading.Thread(target=grab, args=(u,)) for u in urls]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    loaded = yaml.safe_load((tmp_path / "manifest.yaml").read_text())
    assert isinstance(loaded, dict)
    assert loaded.get("version") == DownloadCache.MANIFEST_VERSION
    assert len(loaded["entries"]) == 24


def test_tmp_path_is_unique_per_instance(tmp_path):
    """The mechanism, pinned directly. Two instances sharing one tmp path
    is the bug; asserting the outcome alone would let a future edit
    reintroduce it wherever the lock happens to hide it."""
    a = DownloadCache(tmp_path, fetcher=_fetcher_for(b"a"))
    b = DownloadCache(tmp_path, fetcher=_fetcher_for(b"b"))

    assert a._tmp_path() != b._tmp_path()
    # …and neither collides with the manifest itself.
    assert a._tmp_path() != a._manifest_path


def test_no_tmp_files_are_left_behind(tmp_path):
    """A litter of manifest.*.tmp files on the share is its own problem —
    and on Windows an orphan can block the next write."""
    urls = [f"https://example.gov/tidy{i}.pdf" for i in range(8)]
    for url in urls:
        DownloadCache(tmp_path, fetcher=_fetcher_for(b"z")).fetch(url)

    assert list(tmp_path.glob("*.tmp")) == []


def test_a_later_instance_sees_an_earlier_one_s_entries(tmp_path):
    """`has()` must not answer from a stale in-memory copy: reporting a
    miss for something already on disk means re-downloading it."""
    first = DownloadCache(tmp_path, fetcher=_fetcher_for(b"one"))
    first.fetch("https://example.gov/shared.pdf")

    second = DownloadCache(tmp_path, fetcher=_fetcher_for(b"two"))
    assert second.has("https://example.gov/shared.pdf")


def test_a_corrupt_manifest_is_preserved_not_overwritten(tmp_path):
    """If the manifest cannot be parsed, the entries in it are the only
    record of ~7,400 downloads. Overwriting it with a fresh one destroys
    that; keeping a copy leaves a recovery path."""
    (tmp_path / "manifest.yaml").write_text("{[not: valid: yaml", encoding="utf-8")

    DownloadCache(tmp_path, fetcher=_fetcher_for(b"q")).fetch(
        "https://example.gov/after-corruption.pdf"
    )

    salvaged = list(tmp_path.glob("manifest.yaml.corrupt-*"))
    assert len(salvaged) == 1
    assert "not: valid" in salvaged[0].read_text()


def test_fetch_still_returns_the_cached_file(tmp_path):
    """Guard rail: none of the locking may change what fetch() returns."""
    cache = DownloadCache(tmp_path, fetcher=_fetcher_for(b"payload-"))
    path = cache.fetch("https://example.gov/plain.pdf")

    assert path.exists()
    assert path.read_bytes() == b"payload-https://example.gov/plain.pdf"
    assert cache.fetch("https://example.gov/plain.pdf") == path
