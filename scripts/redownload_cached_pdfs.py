"""Re-fetch PDFs into the local cache and rewrite DB blob paths.

Why this exists
---------------

The volume-ingest run that produced the latest pg_dump cached its PDFs
inside a worktree directory (``…ask-the-budget-az-worktrees/phase-1b-volume-
ingest/data/cached-pdfs/<sha2>/<sha>.pdf``). That worktree was cleaned
up after the dump was taken, so every ``source_blob_path`` in the
restored DB points at a path that no longer exists. The DB rows have
the right *sha* baked into the path basename, but no ``source_url``
column to re-download from.

The URLs DO live in ``data/discovery-cache.yaml``: a YAML file produced
by the discovery pass that walked JLBC's TOC pages. Each entry has a
``url`` field; downloading those URLs into the project's
sha256-keyed DownloadCache populates ``data/cached-pdfs/<sha2>/<sha>.pdf``
with the same content-addressed names the DB already references.

Strategy
--------

1. Walk every URL in ``data/discovery-cache.yaml`` and fetch it through
   ``ingest.cache.DownloadCache``. The cache short-circuits on a hit
   so this is idempotent; first run fetches ~380 PDFs, subsequent
   runs are a no-op.
2. For every ``documents`` row, extract the sha256 from its
   ``source_blob_path`` basename. If a file with that sha exists in
   the local cache, rewrite the DB row's path to the project-relative
   form. Rows whose sha doesn't show up in the cache are reported at
   the end so you know what's still unreachable.

Usage
-----

    DATABASE_URL=postgresql://askbudget:askbudget-dev@127.0.0.1:5432/askbudget \\
        python -m scripts.redownload_cached_pdfs

Optional ``--no-fetch`` to skip the download pass and only rewrite
paths against whatever's already cached. Optional ``--dry-run`` to
fetch + report without writing path updates back to the DB.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Any

import yaml

# Allow `python scripts/redownload_cached_pdfs.py` to work whether or not
# the project is on sys.path — append the project root if it isn't.
_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from db.connection import close_pool, get_connection  # noqa: E402
from ingest.cache import DownloadCache  # noqa: E402
from ingest.discovery import DiscoveryCache, discover  # noqa: E402

CACHE_ROOT = _REPO / "data" / "cached-pdfs"
DISCOVERY_CACHE = _REPO / "data" / "discovery-cache.yaml"
RELATIVE_CACHE_ROOT = "data/cached-pdfs"

# JLBC doc_types that are TOC-driven (need discover() to enumerate
# their per-section PDFs). The first three came from the volume
# ingest run; the cross-cut walks turn up the bh-/bd-/s-/topic-/detailed-
# list PDFs that live under those TOCs.
JLBC_DISCOVERY_COMBOS: list[tuple[str, int]] = [
    ("baseline-per-agency", 2026),
    ("baseline-per-agency", 2027),
    ("approps-per-agency", 2025),
    ("baseline-cross-cut", 2027),
    ("approps-cross-cut", 2026),
]

# Path basenames look like ``<sha>.pdf``. Be tolerant of any case.
_SHA_FROM_BASENAME = re.compile(r"^([0-9a-fA-F]{64})\.pdf$")


def extract_sha(blob_path: str) -> str | None:
    if not blob_path:
        return None
    name = Path(blob_path).name
    m = _SHA_FROM_BASENAME.match(name)
    if not m:
        return None
    return m.group(1).lower()


def collect_discovery_urls(yaml_path: Path) -> list[str]:
    """Walk every group's `entries` list and pull out every `url` field.
    The same URL can appear in multiple groups (e.g., a per-agency PDF
    referenced from both the agency index and the per-section TOC) —
    de-dupe before returning."""
    if not yaml_path.exists():
        return []
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    seen: set[str] = set()
    for group in (raw.get("entries") or {}).values():
        for entry in group.get("entries") or []:
            url = entry.get("url")
            if isinstance(url, str) and url:
                seen.add(url)
    return sorted(seen)


def download_all(cache: DownloadCache, urls: list[str]) -> tuple[int, int, list[tuple[str, str]]]:
    """Fetch every URL into the cache. Returns (already_cached, downloaded, failures)."""
    cached = 0
    fetched = 0
    failures: list[tuple[str, str]] = []
    total = len(urls)
    for i, url in enumerate(urls, start=1):
        if cache.has(url):
            cached += 1
            continue
        try:
            cache.fetch(url)
            fetched += 1
        except Exception as exc:  # noqa: BLE001
            failures.append((url, str(exc)))
        if i % 25 == 0 or i == total:
            print(
                f"  [{i}/{total}] cumulative — fetched {fetched}, "
                f"already-cached {cached}, failed {len(failures)}",
            )
    return cached, fetched, failures


def fetch_pdf_rows() -> list[dict[str, Any]]:
    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT doc_id, source_blob_path
            FROM documents
            WHERE source_format = 'pdf'
            ORDER BY doc_id
            """,
        ).fetchall()
    return list(rows)


def update_blob_path(doc_id: str, new_path: str) -> None:
    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET source_blob_path = %s WHERE doc_id = %s",
            [new_path, doc_id],
        )


def update_source_url(doc_id: str, url: str) -> None:
    """Backfill the row's source_url from the rebuilt cache manifest.
    Without this column populated, a fresh dump leaves no acquisition
    trail — the recurring "we lost the source docs" failure mode."""
    with get_connection() as conn:
        conn.execute(
            "UPDATE documents SET source_url = %s WHERE doc_id = %s "
            "AND (source_url IS NULL OR source_url = '')",
            [url, doc_id],
        )


def sha_to_url_index(cache: DownloadCache) -> dict[str, str]:
    """Build sha256 → url from the DownloadCache's manifest. Used to
    populate documents.source_url from the cache manifest after a
    download pass."""
    out: dict[str, str] = {}
    # Access the entries dict through the same shape the cache uses
    # internally; we don't have a public accessor for "all entries" but
    # the manifest file is the source of truth.
    manifest_path = cache.root / DownloadCache.MANIFEST_NAME
    if not manifest_path.exists():
        return out
    parsed = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
    entries = (parsed.get("entries") or {})
    for url, entry in entries.items():
        sha = entry.get("sha256")
        if isinstance(sha, str):
            out[sha.lower()] = url
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--no-fetch",
        action="store_true",
        help="Skip the download phase; only rewrite DB paths against the existing cache.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Don't write DB path updates.",
    )
    args = parser.parse_args()

    if "DATABASE_URL" not in os.environ:
        os.environ["DATABASE_URL"] = (
            "postgresql://askbudget:askbudget-dev@127.0.0.1:5432/askbudget"
        )

    cache = DownloadCache(CACHE_ROOT)

    if not args.no_fetch:
        # Phase 1: ensure discovery-cache.yaml is comprehensive. The
        # current cache only has entries from earlier ingest passes;
        # the volume run's cache was thrown away with the worktree.
        # Re-walk each TOC so the cache covers every per-section PDF
        # we expect to see in the DB.
        discovery_cache = DiscoveryCache(DISCOVERY_CACHE)
        print("Walking JLBC TOCs to populate discovery-cache.yaml…")
        for doc_type, fy in JLBC_DISCOVERY_COMBOS:
            try:
                result = discover(
                    "jlbc", doc_type, fy,
                    download_cache=cache,
                    discovery_cache=discovery_cache,
                )
                print(
                    f"  discovered jlbc/{doc_type}/{fy}: {len(result.entries)} entries",
                )
            except Exception as exc:  # noqa: BLE001
                print(f"  WARN  jlbc/{doc_type}/{fy}: {exc}")

        urls = collect_discovery_urls(DISCOVERY_CACHE)
        print(f"\nDiscovery cache lists {len(urls)} unique URLs.")
        cached, fetched, failures = download_all(cache, urls)
        print(
            f"Download phase complete — fetched {fetched}, "
            f"already-cached {cached}, failed {len(failures)}",
        )
        if failures:
            print("\nFetch failures:")
            for url, err in failures[:20]:
                print(f"  {url}: {err}")
            if len(failures) > 20:
                print(f"  …and {len(failures) - 20} more")
            print()

    sha_url_idx = sha_to_url_index(cache)
    rows = fetch_pdf_rows()
    print(f"\nRewriting source_blob_path + source_url for {len(rows)} PDF rows…")
    rewritten = 0
    already_relative = 0
    url_backfilled = 0
    not_in_cache: list[str] = []
    sha_missing: list[str] = []

    for row in rows:
        doc_id = row["doc_id"]
        existing = row["source_blob_path"] or ""
        sha = extract_sha(existing)
        if sha is None:
            sha_missing.append(doc_id)
            continue
        local_relative = f"{RELATIVE_CACHE_ROOT}/{sha[:2]}/{sha}.pdf"
        local_abs = CACHE_ROOT / sha[:2] / f"{sha}.pdf"
        if not local_abs.exists():
            not_in_cache.append(doc_id)
            continue
        if existing == local_relative:
            already_relative += 1
        else:
            if not args.dry_run:
                update_blob_path(doc_id, local_relative)
            rewritten += 1
        # Backfill source_url from cache manifest for any row that
        # currently has no URL recorded. The UPDATE no-ops when the
        # column is already set, so this is safe to re-run.
        url = sha_url_idx.get(sha)
        if url and not args.dry_run:
            update_source_url(doc_id, url)
            url_backfilled += 1

    print(
        f"DB phase complete — rewritten {rewritten}, "
        f"already-relative {already_relative}, "
        f"url-backfilled {url_backfilled}, "
        f"not-in-cache {len(not_in_cache)}, "
        f"sha-missing {len(sha_missing)}",
    )
    if not_in_cache:
        print(
            "\nDocs whose sha isn't on disk (need a different acquisition path):",
        )
        for doc_id in not_in_cache[:20]:
            print(f"  {doc_id}")
        if len(not_in_cache) > 20:
            print(f"  …and {len(not_in_cache) - 20} more")
    if sha_missing:
        print("\nDocs with a non-content-addressed source_blob_path:")
        for doc_id in sha_missing[:20]:
            print(f"  {doc_id}")
        if len(sha_missing) > 20:
            print(f"  …and {len(sha_missing) - 20} more")

    close_pool()
    return 0 if not (not_in_cache or sha_missing) else 1


if __name__ == "__main__":
    raise SystemExit(main())
