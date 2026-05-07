"""Load the volume-ingest corpus into Postgres.

Successor to scripts/load_slice.py — instead of a hardcoded 5-doc list,
walk data/chunks/*.json and derive `DocumentMeta` for each doc from
three sources, in priority order:

  1. data/extractor-output/<doc_id>/manifest.json
       Written by ingest/dispatcher.py:extract(). Authoritative for
       extractor name, extractor_version, source_path, source_sha256.

  2. samples/manifest.yaml
       Authoritative for singleton documents (Gov SAD, AGAO AFR, the
       SB 1735 DOCX, JLBC singlefiles). Provides title, source_url,
       local_path, page_count.

  3. The first chunk of the NDJSON itself + a derived-from-doc_id title.
       For JLBC sub-docs (s/bh/bd/per-agency PDFs enumerated through
       discovery), neither (1) nor (2) carries a hand-written title;
       fall back to a derived title built from the discovery-cache
       entry, or as a last resort from the doc_id slug.

Per the volume-ingest handoff prompt, this is the
"DocumentMeta-from-chunks" approach — the three fields that do NOT
round-trip through the chunk NDJSON (`title`, `source_blob_path`,
`extractor_version`) get default-derived values.

Prerequisites:
  - Postgres stack up (`cd db && docker compose up -d`)
  - Migrations applied (`db/migrations/000{1,2,3}_*.sql`)
  - Volume ingest run (`uv run python scripts/run_volume_ingest.py`)

Usage:
  uv run python scripts/load_corpus.py [--validate] [--doc-filter SUBSTR] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from db.connection import get_connection  # noqa: E402
from db.loader import DocumentMeta, load_chunk_file  # noqa: E402
from db.validate import format_results, run_checks  # noqa: E402

CHUNKS_DIR = ROOT / "data" / "chunks"
EXTRACTOR_ROOT = ROOT / "data" / "extractor-output"
SAMPLES_MANIFEST = ROOT / "samples" / "manifest.yaml"
DISCOVERY_CACHE = ROOT / "data" / "discovery-cache.yaml"


# ---------------------------------------------------------------------------
# Lookup tables, loaded once.
# ---------------------------------------------------------------------------


def _load_samples_manifest() -> dict[str, dict[str, Any]]:
    """samples/manifest.yaml -> {doc_id: row}. Singletons only."""
    if not SAMPLES_MANIFEST.exists():
        return {}
    raw = yaml.safe_load(SAMPLES_MANIFEST.read_text(encoding="utf-8"))
    return {row["id"]: row for row in raw.get("documents", [])}


def _load_discovery_titles() -> dict[str, str]:
    """data/discovery-cache.yaml -> {filename_stem: title}.

    Used to recover human-readable titles for JLBC sub-docs (s18, bh20,
    per-agency slugs) that aren't in samples/manifest.yaml. Keys are the
    filename stem (e.g. 's18', 'bh20', 'sba'); the value is the title or
    name field from the discovery walker's typed entry.
    """
    if not DISCOVERY_CACHE.exists():
        return {}
    raw = yaml.safe_load(DISCOVERY_CACHE.read_text(encoding="utf-8"))
    out: dict[str, str] = {}
    for cache_entry in raw.get("entries", {}).values():
        for sub in cache_entry.get("entries", []):
            # AgencyIndexEntry uses 'name' + 'slug'; cross-cut entries use
            # 'title' + 'filename'. Normalize both into a slug -> title map.
            slug = sub.get("slug") or Path(sub.get("filename", "")).stem
            title = sub.get("title") or sub.get("name")
            if slug and title:
                out[slug] = title
    return out


# ---------------------------------------------------------------------------
# Per-doc metadata resolution.
# ---------------------------------------------------------------------------


# Extractor short-name -> default version when the dispatcher sidecar is
# missing. The sidecar value always wins; this is the safety net.
_DEFAULT_EXTRACTOR_VERSIONS: dict[str, str] = {
    "mineru": "2.5.0",
    "opendataloader": "2.4.1",
    "python-docx": "1.2.0",
}


def _read_first_chunk_meta(chunks_path: Path) -> dict[str, Any]:
    """Pull doc_id/publisher/doc_type/fiscal_year from the first chunk
    line. These are denormalized on every chunk; the first one is enough.
    """
    with chunks_path.open(encoding="utf-8") as fh:
        for line in fh:
            if line.strip():
                return json.loads(line)
    raise ValueError(f"{chunks_path}: file has no chunks")


def _read_dispatcher_manifest(doc_id: str) -> dict[str, Any] | None:
    """The per-doc manifest.json written by ingest/dispatcher.py:extract()."""
    path = EXTRACTOR_ROOT / doc_id / "manifest.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _derive_title(
    *,
    doc_id: str,
    publisher: str,
    fiscal_year: int,
    discovery_titles: dict[str, str],
) -> str:
    """Best-effort title for a JLBC sub-doc not in samples/manifest.yaml.

    doc_id pattern is `<publisher>-<class>-fy<YYYY>-<slug>` (driver.py
    docstring). Look up <slug> in the discovery cache; if absent, fall
    back to `"<PUBLISHER> FY<YYYY> <slug>"`.
    """
    parts = doc_id.rsplit("-", 1)
    slug = parts[-1] if len(parts) == 2 else doc_id
    title = discovery_titles.get(slug)
    if title:
        return f"{publisher.upper()} FY{fiscal_year} — {title}"
    return f"{publisher.upper()} FY{fiscal_year} {slug}"


def _build_doc_meta(
    chunks_path: Path,
    *,
    samples_manifest: dict[str, dict[str, Any]],
    discovery_titles: dict[str, str],
) -> DocumentMeta:
    """Synthesize DocumentMeta for one doc, merging the three info sources."""
    chunk0 = _read_first_chunk_meta(chunks_path)
    doc_id = chunk0["doc_id"]
    publisher = chunk0["publisher"]
    doc_type = chunk0["doc_type"]
    fiscal_year = int(chunk0["fiscal_year"])

    sm_row = samples_manifest.get(doc_id, {})
    disp = _read_dispatcher_manifest(doc_id) or {}

    # Extractor + version: dispatcher manifest is authoritative; fall back
    # to the source_format-implied default.
    extractor: str = disp.get("extractor") or (
        "python-docx" if sm_row.get("source_format") == "docx" else "mineru"
    )
    extractor_version: str = (
        disp.get("extractor_version")
        or _DEFAULT_EXTRACTOR_VERSIONS.get(extractor, "unknown")
    )

    # source_format: dispatcher manifest, else samples manifest, else infer
    # from extractor.
    source_format: str = disp.get("source_format") or sm_row.get("source_format") or (
        "docx" if extractor == "python-docx" else "pdf"
    )

    # source_blob_path: prefer the dispatcher's source_path (absolute or
    # repo-relative as it was passed at extract-time); fall back to the
    # samples manifest's local_path; final fallback is a synthesized path
    # under data/cached-pdfs/.
    source_blob_path: str = (
        disp.get("source_path")
        or sm_row.get("local_path")
        or f"data/cached-pdfs/{doc_id}.{source_format}"
    )

    # title + source_url: samples manifest only (singletons), else derive.
    title: str = sm_row.get("title") or _derive_title(
        doc_id=doc_id,
        publisher=publisher,
        fiscal_year=fiscal_year,
        discovery_titles=discovery_titles,
    )
    source_url = sm_row.get("source_url") or None
    if source_url == "":
        source_url = None

    page_count = sm_row.get("page_count")

    return DocumentMeta(
        doc_id=doc_id,
        publisher=publisher,
        doc_type=doc_type,
        fiscal_year=fiscal_year,
        title=title,
        source_format=source_format,
        source_blob_path=source_blob_path,
        extractor=extractor,
        extractor_version=extractor_version,
        source_url=source_url,
        page_count=page_count,
    )


# ---------------------------------------------------------------------------
# Iteration
# ---------------------------------------------------------------------------


def _iter_chunk_files(doc_filter: str | None = None) -> list[Path]:
    """All NDJSON files in data/chunks/, sorted for stable run output.

    MANIFEST.md and any non-.json siblings are skipped automatically.
    """
    paths = sorted(CHUNKS_DIR.glob("*.json"))
    if doc_filter:
        paths = [p for p in paths if doc_filter in p.stem]
    return paths


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate", action="store_true",
        help="Run db.validate.run_checks after loading; exit 1 on any failure.",
    )
    parser.add_argument(
        "--doc-filter", type=str, default=None,
        help="Substring filter on doc_id; only matching files load.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve DocumentMeta for each doc and print a summary; no DB writes.",
    )
    args = parser.parse_args(argv)

    chunk_files = _iter_chunk_files(args.doc_filter)
    if not chunk_files:
        print("No chunk files found at data/chunks/*.json. "
              "Run scripts/run_volume_ingest.py first.", file=sys.stderr)
        return 2

    print(f"Loading samples/manifest.yaml + data/discovery-cache.yaml ...")
    samples_manifest = _load_samples_manifest()
    discovery_titles = _load_discovery_titles()
    print(f"  manifest singletons: {len(samples_manifest)}")
    print(f"  discovery titles:    {len(discovery_titles)}")
    print(f"\n{len(chunk_files)} chunk files to process\n")

    if args.dry_run:
        for path in chunk_files:
            try:
                meta = _build_doc_meta(
                    path,
                    samples_manifest=samples_manifest,
                    discovery_titles=discovery_titles,
                )
                print(f"  {meta.doc_id:50s}  {meta.extractor:14s}  {meta.title}")
            except Exception as e:  # noqa: BLE001
                print(f"  FAIL {path.name}: {type(e).__name__}: {e}")
        return 0

    total = 0
    failures: list[tuple[str, str]] = []
    with get_connection() as conn:
        for path in chunk_files:
            try:
                meta = _build_doc_meta(
                    path,
                    samples_manifest=samples_manifest,
                    discovery_titles=discovery_titles,
                )
                n = load_chunk_file(path, meta, conn)
                print(f"  loaded {meta.doc_id}: {n} chunks")
                total += n
            except Exception as e:  # noqa: BLE001
                # Don't bail the whole load on one bad doc — record + continue.
                # The summary section + non-zero exit code surface the issue.
                msg = f"{type(e).__name__}: {e}"
                print(f"  FAILED {path.name}: {msg}")
                failures.append((path.name, msg))

        print(f"\nTotal chunks loaded: {total} (across {len(chunk_files) - len(failures)} docs)")

        if failures:
            print(f"\n{len(failures)} failures:")
            for name, msg in failures:
                print(f"  {name}: {msg}")

        if args.validate:
            print("\nValidation checks:")
            results = run_checks(conn)
            print(format_results(results))
            if any(not r.passed for r in results):
                return 1

    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
