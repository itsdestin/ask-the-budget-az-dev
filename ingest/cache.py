"""sha256-keyed download cache.

Given a URL, fetch the bytes once and never again — until either the
caller explicitly invalidates the entry or a content-integrity check
detects on-disk drift.

## Why a cache here

The ingest pipeline walks dozens of TOC PDFs and 100+ per-agency PDFs
across multiple fiscal years. Every Phase 1a iteration touches the
same source files; re-downloading them on each run would burn JLBC's
bandwidth, slow iteration, and risk hitting their (unwritten) rate
limit. The cache makes ingest reproducible: a fresh worktree can hit
``cache.fetch(url)`` and either pull from local disk or download once.

## Layout

```
<root>/
  manifest.yaml                       # URL → entry metadata
  ab/
    abc12345...sha256.pdf             # fanned out by first-2 hex
  cd/
    cdef9876...sha256.pdf
```

The two-hex prefix avoids cramming 1000+ files into a single directory
(slow on Windows in particular). The full sha256 is the filename so
the path is self-describing.

## Manifest

YAML, single-file, keyed by URL:

```yaml
version: 1
entries:
  "https://www.azjlbc.gov/27baseline/s18.pdf":
    sha256: "11942f74..."
    byte_size: 12345
    fetched_at: "2026-05-06T12:34:56+00:00"
    relative_path: "11/11942f74...pdf"
```

Single-file YAML is fine at Phase-1a scale (low hundreds of entries).
If we ever exceed thousands, switch to SQLite. The relative_path is
forward-slash even on Windows so the manifest is portable.

## Concurrency

The cache is NOT safe for concurrent writes by multiple processes.
Phase 1a's ingest driver is single-process; that's enough. If we ever
parallelize ingest, add a lockfile or move to SQLite.

## Testability

A ``fetcher: Callable[[str], bytes]`` argument is injectable so unit
tests can stub the network. Default fetcher uses ``requests``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import yaml

Fetcher = Callable[[str], bytes]


def _default_fetcher(url: str) -> bytes:
    """Fetch URL bytes via ``requests``. Raises on non-2xx."""
    # Imported lazily so import-time of this module doesn't pay for
    # requests + urllib3 when callers inject a fake fetcher (tests).
    import requests

    response = requests.get(url, timeout=60)
    response.raise_for_status()
    return response.content


def _sha256_hex(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _utcnow_iso() -> str:
    """ISO-8601 UTC timestamp with offset, e.g. ``2026-05-06T12:34:56+00:00``."""
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


class DownloadCache:
    """sha256-keyed local cache with a YAML manifest.

    Constructor:
      ``root`` — directory to store files + manifest under. Created if missing.
      ``fetcher`` — callable that fetches a URL's bytes. Defaults to ``requests.get``.
    """

    MANIFEST_NAME = "manifest.yaml"
    MANIFEST_VERSION = 1

    def __init__(self, root: Path | str, fetcher: Fetcher | None = None) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._fetcher: Fetcher = fetcher or _default_fetcher
        self._manifest_path = self.root / self.MANIFEST_NAME
        self._manifest: dict[str, Any] = self._load_manifest()

    # --- Public API ---

    def has(self, url: str) -> bool:
        """Return True if the URL is already cached AND the local file exists."""
        entry = self._entries.get(url)
        if entry is None:
            return False
        return (self.root / entry["relative_path"]).exists()

    def fetch(self, url: str, *, expected_sha256: str | None = None) -> Path:
        """Return a Path to the cached bytes for ``url``, downloading if needed.

        If ``expected_sha256`` is provided, a fetch's downloaded bytes must
        hash to that value or ``ValueError`` is raised — used to validate
        downloads against a pre-known-good checksum (e.g., from
        ``samples/manifest.yaml``).

        Cache-hit path: existing local file is sha256-verified before
        being returned. Mismatch → re-fetch (silent corruption would
        otherwise propagate downstream into chunking).
        """
        entry = self._entries.get(url)
        if entry is not None:
            local = self.root / entry["relative_path"]
            if local.exists():
                actual = _sha256_hex(local.read_bytes())
                if actual == entry["sha256"]:
                    return local
                # Local file drifted from manifest — fall through to refetch.

        body = self._fetcher(url)
        sha = _sha256_hex(body)
        if expected_sha256 is not None and sha != expected_sha256:
            raise ValueError(
                f"sha256 mismatch for {url}: "
                f"expected {expected_sha256}, got {sha}"
            )

        relative = self._relative_for_sha(sha)
        target = self.root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(body)

        self._entries[url] = {
            "sha256": sha,
            "byte_size": len(body),
            "fetched_at": _utcnow_iso(),
            # POSIX-style relative path so the manifest is portable across OSes.
            "relative_path": relative.as_posix(),
        }
        self._save_manifest()
        return target

    # --- Internal ---

    @staticmethod
    def _relative_for_sha(sha: str) -> Path:
        # Two-hex prefix keeps any one directory's child count manageable.
        return Path(sha[:2]) / f"{sha}.pdf"

    @property
    def _entries(self) -> dict[str, dict[str, Any]]:
        return self._manifest["entries"]  # type: ignore[no-any-return]

    def _load_manifest(self) -> dict[str, Any]:
        if not self._manifest_path.exists():
            return {"version": self.MANIFEST_VERSION, "entries": {}}
        loaded = yaml.safe_load(self._manifest_path.read_text(encoding="utf-8"))
        if not loaded or not isinstance(loaded, dict):
            return {"version": self.MANIFEST_VERSION, "entries": {}}
        loaded.setdefault("entries", {})
        loaded.setdefault("version", self.MANIFEST_VERSION)
        return loaded

    def _save_manifest(self) -> None:
        self._manifest_path.write_text(
            yaml.safe_dump(self._manifest, sort_keys=True, default_flow_style=False),
            encoding="utf-8",
        )
