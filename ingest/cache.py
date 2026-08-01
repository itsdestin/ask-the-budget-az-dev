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

Safe for concurrent writers as of Plan 5 Task 20 — parallel ingest
(`JLBC_INGEST_WORKERS`) made that necessary, and several office machines
can point at one share.

Three things make it safe, and the third is the one that matters:

1. A per-instance tmp file. It used to be `manifest.yaml.tmp` — one path
   shared by every instance and thread, so two saves interleaved into it
   and both then `os.replace`d the result.
2. A lock around the save: a same-process mutex keyed by manifest path,
   plus a short-lived exclusive-create lockfile for cross-machine writers.
3. **Save is re-read-merge-write, not write.** Each instance holds its
   own in-memory manifest from construction, so writing that copy back
   wholesale erases every entry another writer added in the meantime.
   Locking alone would not have fixed that — it would only have made the
   loss orderly.

Why any of this is worth the code: an unparseable or truncated manifest
does not raise. `_load_manifest` reads it as an EMPTY cache, and an empty
cache re-downloads ~7,400 PDFs from Arizona state web servers one file at
a time. The failure is silent and expensive, and it lands on somebody
else's infrastructure.

## Testability

A ``fetcher: Callable[[str], bytes]`` argument is injectable so unit
tests can stub the network. Default fetcher uses ``requests``.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import itertools
import os
import sys
import threading
import time
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import yaml

# PyYAML's C-accelerated loader/dumper when the wheel was built with libyaml,
# which the manylinux and Windows wheels both are. Measured on the real
# 7,482-entry manifest (2.1 MB): load 1.86s -> 0.42s, dump 1.08s -> 0.25s.
#
# That is not a micro-optimisation here. `_save_manifest` now RE-READS before
# writing (see its docstring), so without this the safety fix would have made
# every save ~2.9s against ~1.1s before — and during a bulk backfill at
# ~945 docs/hr a save happens every few seconds. With it, the safer version is
# also the faster one: ~0.67s.
try:
    from yaml import CSafeDumper as _YamlDumper, CSafeLoader as _YamlLoader
except ImportError:  # pragma: no cover — pure-Python PyYAML build
    from yaml import SafeDumper as _YamlDumper, SafeLoader as _YamlLoader

Fetcher = Callable[[str], bytes]

# One mutex per manifest path. Keyed by path rather than global because two
# DownloadCache instances on DIFFERENT roots are genuinely independent and
# serializing them would slow parallel ingest for nothing — while two on the
# SAME root are the case this exists for. Mirrors ingest/lock.py's
# `_process_mutex`.
_MANIFEST_MUTEXES: dict[Path, threading.Lock] = {}
_MUTEX_REGISTRY_LOCK = threading.Lock()
# Distinguishes the tmp files of two instances inside one process, where pid
# is identical and thread ids get recycled.
_INSTANCE_COUNTER = itertools.count()

# How long to wait for another machine's manifest write before giving up on
# the lockfile and proceeding anyway. A manifest save is a sub-millisecond
# write of a few hundred KB; anything past this is a crashed holder or a dead
# share, and blocking ingest forever on a stale lockfile would be worse than
# the race it prevents.
_MANIFEST_LOCK_TIMEOUT_S = 10.0
_MANIFEST_LOCK_POLL_S = 0.01


def _manifest_mutex(path: Path) -> threading.Lock:
    try:
        key = path.resolve()
    except OSError:
        key = path
    with _MUTEX_REGISTRY_LOCK:
        mutex = _MANIFEST_MUTEXES.get(key)
        if mutex is None:
            mutex = threading.Lock()
            _MANIFEST_MUTEXES[key] = mutex
        return mutex

# Extensions the ingest pipeline knows how to route. Anything else is stored
# as .pdf, matching the pre-2026-07 behavior — the corpus is overwhelmingly
# PDFs and a query-string-mangled URL shouldn't produce a `.aspx` file the
# dispatcher then refuses.
_KNOWN_SUFFIXES = frozenset({".pdf", ".docx", ".doc", ".htm", ".html", ".xlsx"})


def _suffix_for_url(url: str) -> str:
    """File extension implied by a URL's path, defaulting to .pdf."""
    suffix = Path(unquote(urlsplit(url).path)).suffix.lower()
    return suffix if suffix in _KNOWN_SUFFIXES else ".pdf"


# WHY a browser User-Agent rather than an honest "JLBC-Insight/1.0" one:
# `requests` defaults to `python-requests/x.y`, and several Arizona state sites
# sit behind a WAF that rejects it outright. Measured 2026-08-01 against the
# real hosts:
#
#   User-Agent                    gao.az.gov   ospb.az.gov   azjlbc.gov
#   python-requests (the default)    403           200          200
#   JLBC-Insight/1.0 (descriptive)   403           200          200
#   browser string                   200           200          200
#
# A descriptive agent string was tried first and preferred — it is the more
# honest thing to send — but gao.az.gov 403s anything that does not look like a
# browser, and that is where every Annual Financial Report lives. The block is
# an indiscriminate WAF rule, not a publisher policy: these are public-record
# documents, the AFR is the top of the accuracy hierarchy in the system prompt,
# and this tool is fetching them one at a time for a state agency's own use.
# Revisit if a state host ever asks us to identify differently.
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)


def _default_fetcher(url: str) -> bytes:
    """Fetch URL bytes via ``requests``. Raises on non-2xx."""
    # Imported lazily so import-time of this module doesn't pay for
    # requests + urllib3 when callers inject a fake fetcher (tests).
    import requests

    response = requests.get(url, timeout=60, headers={"User-Agent": _USER_AGENT})
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
        self._lock_path = self.root / f"{self.MANIFEST_NAME}.lock"
        self._instance_id = next(_INSTANCE_COUNTER)
        self._mutex = _manifest_mutex(self._manifest_path)
        self._manifest: dict[str, Any] = self._load_manifest()

    # --- Public API ---

    def has(self, url: str) -> bool:
        """Return True if the URL is already cached AND the local file exists."""
        entry = self._entries.get(url)
        if entry is None:
            return False
        return (self.root / entry["relative_path"]).exists()

    def sha256_of(self, url: str) -> str | None:
        """Return the recorded sha256 for ``url``, or None if not cached.

        Does NOT re-hash the on-disk file — returns the manifest's
        recorded value. Callers that want to verify integrity should
        re-fetch (which sha-checks before returning).
        """
        entry = self._entries.get(url)
        return None if entry is None else entry["sha256"]

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

        relative = self._relative_for_sha(sha, _suffix_for_url(url))
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
    def _relative_for_sha(sha: str, suffix: str = ".pdf") -> Path:
        # Two-hex prefix keeps any one directory's child count manageable.
        #
        # The suffix used to be hardcoded `.pdf`, which was true while the
        # cache only ever fetched JLBC PDFs. Fiscal-note refresh and the
        # book walker now pull DOCX and HTML too, and a .docx saved as .pdf
        # routes to the wrong extractor — a failure that surfaces as garbled
        # chunks rather than an error.
        return Path(sha[:2]) / f"{sha}{suffix}"

    @property
    def _entries(self) -> dict[str, dict[str, Any]]:
        return self._manifest["entries"]  # type: ignore[no-any-return]

    def _empty_manifest(self) -> dict[str, Any]:
        return {"version": self.MANIFEST_VERSION, "entries": {}}

    def _load_manifest(self) -> dict[str, Any]:
        """Parse the manifest from disk, degrading to empty.

        Degrading is not free — an empty manifest means re-downloading the
        whole corpus — so an UNPARSEABLE one is copied aside first. Those
        bytes may be the only record of thousands of downloads, and the
        very next save would otherwise overwrite them.
        """
        if not self._manifest_path.exists():
            return self._empty_manifest()
        try:
            raw = self._manifest_path.read_text(encoding="utf-8")
            loaded = yaml.load(raw, Loader=_YamlLoader)
        except (OSError, yaml.YAMLError) as err:
            self._preserve_corrupt_manifest(err)
            return self._empty_manifest()
        if not loaded or not isinstance(loaded, dict):
            if raw.strip():
                # Parsed, but not into the shape we wrote. Same reasoning.
                self._preserve_corrupt_manifest("not a mapping")
            return self._empty_manifest()
        loaded.setdefault("entries", {})
        loaded.setdefault("version", self.MANIFEST_VERSION)
        return loaded

    def _preserve_corrupt_manifest(self, reason: object) -> None:
        stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S")
        target = self._manifest_path.with_name(
            f"{self.MANIFEST_NAME}.corrupt-{stamp}-{os.getpid()}"
        )
        try:
            os.replace(self._manifest_path, target)
        except OSError:
            return  # nothing more we can do; the warning below still fires
        print(
            f"ingest.cache: {self._manifest_path} could not be parsed ({reason}). "
            f"Kept a copy at {target.name} — it may be the only record of what "
            "has already been downloaded. The cache is being treated as empty, "
            "so anything not recoverable from that copy will be re-fetched.",
            file=sys.stderr,
        )

    def _tmp_path(self) -> Path:
        """A tmp file no other writer can be using.

        It used to be `manifest.yaml.tmp` — ONE path for every instance in
        every process. Two concurrent saves interleaved their writes into
        that single file and then both `os.replace`d it, producing a
        manifest that parses as empty. pid + instance counter + thread id:
        pid separates machines and processes, the counter separates two
        caches inside one process (where pid is identical), and the thread
        id separates parallel-ingest workers sharing one instance.
        """
        return self._manifest_path.with_name(
            f"{self.MANIFEST_NAME}.{os.getpid()}.{self._instance_id}"
            f".{threading.get_ident()}.tmp"
        )

    @contextmanager
    def _manifest_file_lock(self):
        """Best-effort cross-process lock on the manifest.

        Exclusive-create is the same primitive `ingest/lock.py` uses, and
        works on an SMB share where fcntl does not. Deliberately
        BEST-EFFORT: after `_MANIFEST_LOCK_TIMEOUT_S` it proceeds anyway
        rather than failing the ingest. A stale lockfile left by a crashed
        writer must not wedge every future download, and the tmp+replace
        below already makes the worst case an ordering question rather
        than a corruption one.
        """
        deadline = time.monotonic() + _MANIFEST_LOCK_TIMEOUT_S
        fd = None
        while True:
            try:
                fd = os.open(str(self._lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                if time.monotonic() >= deadline:
                    print(
                        f"ingest.cache: {self._lock_path.name} has been held for "
                        f"over {_MANIFEST_LOCK_TIMEOUT_S:.0f}s — proceeding without "
                        "it. If this repeats, delete that file.",
                        file=sys.stderr,
                    )
                    break
                time.sleep(_MANIFEST_LOCK_POLL_S)
            except OSError:
                break  # unwritable dir — the save below will report the real error
        try:
            yield
        finally:
            if fd is not None:
                os.close(fd)
                try:
                    self._lock_path.unlink()
                except OSError:
                    pass

    def _save_manifest(self) -> None:
        """Merge this instance's entries into the on-disk manifest.

        **Re-read, merge, write — not write.** Each instance holds the
        manifest it loaded at construction, so writing that copy back
        wholesale erases every entry another writer added since. Locking
        alone would not fix that; it would only make the loss orderly.

        tmp + replace stays: `os.replace` is atomic on Windows and POSIX,
        so a crash or a share disconnect mid-write leaves the previous
        manifest intact rather than truncated YAML — which reads as an
        empty cache and re-downloads the entire corpus.
        """
        with self._mutex, self._manifest_file_lock():
            merged = self._load_manifest()
            # Ours wins on conflict: a URL both writers fetched resolves to
            # the same sha anyway (content-addressed), so the only
            # difference is `fetched_at`.
            merged.setdefault("entries", {}).update(self._entries)
            merged["version"] = self.MANIFEST_VERSION
            self._manifest = merged

            tmp = self._tmp_path()
            try:
                tmp.write_text(
                    yaml.dump(
                        merged, Dumper=_YamlDumper, sort_keys=True,
                        default_flow_style=False,
                    ),
                    encoding="utf-8",
                )
                os.replace(tmp, self._manifest_path)
            finally:
                # An exception between write and replace would otherwise
                # litter the share with tmp files, and on Windows an orphan
                # can block the next write to the same name.
                try:
                    tmp.unlink()
                except OSError:
                    pass
