"""Volume ingest orchestrator — Phase 1b decoupled workstream.

Drives the full v1 dogfood corpus across all four publishers (decision D12)
through the existing ingest infrastructure:

  data/ingest-plan.yaml       declares targets per week
  ingest/discovery.py         walks JLBC TOCs to enumerate sub-PDFs
  ingest/driver.py            expands targets into concrete IngestItems
  ingest/dispatcher.py        picks + runs the right extractor per doc_type
  chunking/builder.py         turns extractor output into NDJSON chunks

This file is the top-level wiring: load plan -> resolve each target ->
for each item, fetch (URL via DownloadCache, or use local_path) ->
dispatcher.extract() -> chunk_doc() -> data/chunks/<doc_id>.json.

Idempotent: skips re-extraction when <extractor-output>/manifest.json
exists. Chunking re-runs by default (cheap); pass --no-force-chunk to
skip when the NDJSON already exists, useful during dev iteration.

Companion: scripts/run_phase_1a_slice.py (laptop dev's hardcoded 5-doc
slice runner) stays untouched per PROMPT-volume-ingest.md — it remains
the fast smoke runner for slice-scoped work.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chunking.builder import chunk_doc  # noqa: E402
from chunking.builders.table_chunk import DocMeta  # noqa: E402
from chunking.entity_stamper import EntityStamper  # noqa: E402
from ingest.cache import DownloadCache  # noqa: E402
from ingest.dispatcher import extract  # noqa: E402
from ingest.driver import (  # noqa: E402
    IngestItem,
    IngestTarget,
    load_plan,
    resolve_target,
)


# ---------------------------------------------------------------------------
# Plan row -> IngestTarget
# ---------------------------------------------------------------------------


def _row_to_target(row: dict[str, Any], *, repo_root: Path) -> IngestTarget:
    """Convert one plan YAML row into an IngestTarget.

    Plan rows store local_path relative to the repo root for portability
    across worktrees; we absolutize against repo_root so the resulting
    IngestTarget is usable from any CWD.
    """
    local = row.get("local_path")
    local_path = (repo_root / local) if local else None
    return IngestTarget(
        publisher=row["publisher"],
        doc_type=row["doc_type"],
        fiscal_year=int(row["fiscal_year"]),
        source_format=row.get("source_format"),
        local_path=local_path,
        bill_id=row.get("bill_id"),
    )


# ---------------------------------------------------------------------------
# Per-item processing
# ---------------------------------------------------------------------------


# Tagged-PDF doc_types route to OpenDataLoader; everything else PDF goes
# through MinerU. Mirrors ingest/dispatcher.py:EXTRACTOR_REGISTRY so the
# DocMeta fed to chunk_doc names the right reader.
_TAGGED_PDF_DOC_TYPES: frozenset[str] = frozenset({"afr", "governors-budget"})


def _extractor_name_for(*, source_format: str, doc_type: str) -> str:
    """Map (source_format, doc_type) to the chunking-side reader key."""
    if source_format == "docx":
        return "python-docx"
    if doc_type in _TAGGED_PDF_DOC_TYPES:
        return "opendataloader"
    return "mineru"


def _resolve_source_path(
    item: IngestItem,
    *,
    cache: DownloadCache,
) -> Path:
    """Return the local path to one IngestItem's source file.

    URL items hit DownloadCache.fetch (cache-first). Local-path items
    were already absolutized at target-build time (see _row_to_target).
    """
    if item.local_path is not None:
        if not item.local_path.exists():
            raise FileNotFoundError(
                f"local source missing for {item.doc_id}: {item.local_path}\n"
                "samples/manifest.yaml has the declared SHA256; acquire "
                "the file or remove the target from data/ingest-plan.yaml."
            )
        return item.local_path
    if item.url is not None:
        return cache.fetch(item.url)
    raise ValueError(f"item {item.doc_id} has neither url nor local_path")


def _count_ndjson_lines(path: Path) -> int:
    with path.open(encoding="utf-8") as fh:
        return sum(1 for line in fh if line.strip())


def _process_item(
    item: IngestItem,
    *,
    cache: DownloadCache,
    stamper: EntityStamper,
    extractor_root: Path,
    chunks_dir: Path,
    force_extract: bool,
    force_chunk: bool,
) -> int:
    """Download -> extract -> chunk one IngestItem. Returns chunk count."""
    out_dir = extractor_root / item.doc_id
    chunks_path = chunks_dir / f"{item.doc_id}.json"

    source_path = _resolve_source_path(item, cache=cache)

    sentinel = out_dir / "manifest.json"
    if sentinel.exists() and not force_extract:
        print(f"  [{item.doc_id}] extractor output cached; skipping extract")
    else:
        print(f"  [{item.doc_id}] extracting via dispatcher (this can take minutes)")
        t0 = time.time()
        extract(
            source_path=source_path,
            doc_type=item.doc_type,
            source_format=item.source_format,
            output_dir=out_dir,
            pages=None,  # extractor decides full range from PDF page count
        )
        print(f"  [{item.doc_id}] extraction done in {time.time() - t0:.1f}s")

    if chunks_path.exists() and not force_chunk:
        n = _count_ndjson_lines(chunks_path)
        print(f"  [{item.doc_id}] chunks NDJSON cached ({n} chunks); skipping chunker")
        return n

    # Chunker takes path-to-document.json for DOCX, dir for PDF (per
    # chunking/builder.py reader registry conventions; matches slice runner).
    extractor_output_path = (
        out_dir / "document.json" if item.source_format == "docx" else out_dir
    )
    doc_meta = DocMeta(
        doc_id=item.doc_id,
        publisher=item.publisher,
        doc_type=item.doc_type,
        fiscal_year=item.fiscal_year,
        extractor=_extractor_name_for(
            source_format=item.source_format, doc_type=item.doc_type,
        ),
        source_format=item.source_format,
        source_url=item.url,
    )
    chunks = chunk_doc(
        extractor_output_path=extractor_output_path,
        doc_meta=doc_meta,
        output_dir=chunks_dir,
        stamper=stamper,
    )
    n = len(chunks)
    print(f"  [{item.doc_id}] {n} chunks written")
    return n


# ---------------------------------------------------------------------------
# Plan iteration
# ---------------------------------------------------------------------------


def _items_for_plan(
    plan: dict[str, Any],
    *,
    weeks: list[str],
    repo_root: Path,
    download_cache_root: Path,
    discovery_cache_path: Path,
) -> list[IngestItem]:
    """Walk the plan's selected weeks; return the flat list of IngestItems
    after discovery expansion. Per-target resolution counts are printed so
    the operator can spot-check coverage before extraction kicks off.
    """
    items: list[IngestItem] = []
    for week_key in weeks:
        if week_key not in plan:
            print(f"  WARN: plan has no key {week_key!r}; skipping")
            continue
        week_rows = plan[week_key]
        print(f"\n=== {week_key} ({len(week_rows)} target rows) ===")
        for row in week_rows:
            target = _row_to_target(row, repo_root=repo_root)
            resolved = resolve_target(
                target,
                download_cache_root=download_cache_root,
                discovery_cache_path=discovery_cache_path,
            )
            tag = f"{target.publisher}/{target.doc_type}/fy{target.fiscal_year}"
            print(f"  {tag}: {len(resolved.items)} items")
            items.extend(resolved.items)
    return items


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


_DEFAULT_WEEKS = ["week_1", "week_2", "week_3"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=ROOT,
        help="Repo root (default: detected from script location).",
    )
    parser.add_argument(
        "--plan", type=Path, default=None,
        help="Plan YAML path (default: <repo>/data/ingest-plan.yaml).",
    )
    parser.add_argument(
        "--weeks", type=str, default=",".join(_DEFAULT_WEEKS),
        help="Comma-separated week keys to process (default: week_1,week_2,week_3).",
    )
    parser.add_argument(
        "--doc-filter", type=str, default=None,
        help="Substring filter on doc_id; only matching items run. Useful for dev.",
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="After resolution, process at most N items (smoke-test guard).",
    )
    parser.add_argument(
        "--force-extract", action="store_true",
        help="Re-run extraction even if manifest.json sentinel exists.",
    )
    parser.add_argument(
        "--force-chunk", action="store_true", default=True,
        help=argparse.SUPPRESS,  # default; --no-force-chunk is the real toggle
    )
    parser.add_argument(
        "--no-force-chunk", action="store_false", dest="force_chunk",
        help="Skip chunking when the NDJSON already exists (dev iteration).",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Resolve all items and print, but don't extract or chunk.",
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root.resolve()
    plan_path = args.plan or (repo_root / "data" / "ingest-plan.yaml")
    download_cache_root = repo_root / "data" / "cached-pdfs"
    discovery_cache_path = repo_root / "data" / "discovery-cache.yaml"
    extractor_root = repo_root / "data" / "extractor-output"
    chunks_dir = repo_root / "data" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    weeks = [w.strip() for w in args.weeks.split(",") if w.strip()]

    print(f"plan: {plan_path}")
    print(f"weeks: {weeks}")
    print(f"chunks dir: {chunks_dir}")

    plan = load_plan(plan_path)

    items = _items_for_plan(
        plan,
        weeks=weeks,
        repo_root=repo_root,
        download_cache_root=download_cache_root,
        discovery_cache_path=discovery_cache_path,
    )

    if args.doc_filter:
        before = len(items)
        items = [it for it in items if args.doc_filter in it.doc_id]
        print(f"\n--doc-filter={args.doc_filter!r}: {before} -> {len(items)} items")

    if args.limit is not None:
        items = items[: args.limit]
        print(f"--limit={args.limit}: trimmed to {len(items)} items")

    print(f"\n=== {len(items)} items resolved; ready to extract/chunk ===\n")

    if args.dry_run:
        for it in items:
            src = "url" if it.url else "local"
            print(f"  {it.doc_id}  ({src}, {it.doc_type}/{it.source_format})")
        return 0

    stamper = EntityStamper.from_default_paths()
    cache = DownloadCache(download_cache_root)

    total_chunks = 0
    docs_processed = 0
    failures: list[tuple[str, str]] = []

    for i, item in enumerate(items, start=1):
        print(f"\n[{i}/{len(items)}] {item.doc_id}")
        try:
            n = _process_item(
                item,
                cache=cache,
                stamper=stamper,
                extractor_root=extractor_root,
                chunks_dir=chunks_dir,
                force_extract=args.force_extract,
                force_chunk=args.force_chunk,
            )
            total_chunks += n
            docs_processed += 1
        except Exception as e:
            # Volume ingest is 1-2 hours of wall time; failing on doc 87 of
            # 110 and tossing the prior 86 docs' output is the wrong shape.
            # Record the failure, keep going. The summary section + non-zero
            # exit code surface the problem to the operator.
            print(f"  [{item.doc_id}] FAILED: {type(e).__name__}: {e}")
            failures.append((item.doc_id, f"{type(e).__name__}: {e}"))

    print(
        f"\n--- volume ingest complete: {docs_processed}/{len(items)} docs, "
        f"{total_chunks} chunks ---"
    )
    if failures:
        print(f"\n{len(failures)} failures:")
        for doc_id, msg in failures:
            print(f"  {doc_id}: {msg}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
