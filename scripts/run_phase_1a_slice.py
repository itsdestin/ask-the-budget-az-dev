"""WS6 slice orchestrator — runs Phase 1a end-to-end on a small subset.

Why a slice and not the full Week-1 list (~50 docs): synthetic-fixture
unit tests already prove each module works in isolation; a slice is what
catches *integration* drift between WS1–WS5 modules on real source. Full
Week-1 ingest moves to the first session of Phase 1b — when the storage
layer is plumbed and we'd be re-ingesting anyway.

Slice contents (5 docs, all hand-picked to cover the WS6 plan's
smoke-query expectations):

  - JLBC FY27 baseline s18.pdf — Funds × Agencies cross-cut.
                                  Drives "What funds does AHCCCS use?"
                                  and "What's in the Aviation Fund?"
  - JLBC FY27 baseline s83.pdf — FTE summary by agency.
                                  Drives "What's the FTE for ADOT?"
  - JLBC FY26 approps bh20.pdf — One-Time GF Adjustments.
  - JLBC FY26 approps bd2.pdf  — FY26 budget detail by agency × fund;
                                  needed for the WS4 cross-source fund
                                  catalog merge audit (T6.2).
  - SB 1735 (FY26 GAA) DOCX    — General Appropriations Act bill.
                                  Drives "What did FY26 GAA appropriate
                                  to ADC?"

Output layout (relative to repo root):

  data/cached-pdfs/         downloaded PDFs (sha256-keyed)
  data/extractor-output/<doc-id>/
        page-N.json + page-N.md   (MinerU per-page contract)
        document.json + document.md  (DOCX path)
  data/chunks/<doc-id>.json   NDJSON, one chunk per line

Idempotent — re-running skips download (DownloadCache cache-hits) and
skips MinerU when page-1.json already exists for a doc. The chunker
always re-runs because it's cheap.
"""
from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

# Repo root on sys.path so `chunking`, `ingest`, `scripts.run_mineru` import
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chunking.builder import chunk_doc
from chunking.builders.table_chunk import DocMeta
from chunking.entity_stamper import EntityStamper
from ingest.cache import DownloadCache
from scripts.run_docx_ingest import run_docx_ingest  # type: ignore[import-not-found]
from scripts.run_mineru import run_mineru  # type: ignore[import-not-found]


@dataclass(frozen=True)
class PdfTarget:
    """Spec for one PDF in the slice."""

    doc_id: str
    url: str
    publisher: str
    doc_type: str
    fiscal_year: int


PDF_SLICE: list[PdfTarget] = [
    PdfTarget(
        doc_id="jlbc-baseline-fy2027-s18",
        url="https://www.azjlbc.gov/27baseline/s18.pdf",
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
    ),
    PdfTarget(
        doc_id="jlbc-baseline-fy2027-s83",
        url="https://www.azjlbc.gov/27baseline/s83.pdf",
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
    ),
    PdfTarget(
        doc_id="jlbc-approps-fy2026-bh20",
        url="https://www.azjlbc.gov/26ar/bh20.pdf",
        publisher="jlbc",
        doc_type="approps-cross-cut",
        fiscal_year=2026,
    ),
    PdfTarget(
        doc_id="jlbc-approps-fy2026-bd2",
        url="https://www.azjlbc.gov/26ar/bd2.pdf",
        publisher="jlbc",
        doc_type="approps-cross-cut",
        fiscal_year=2026,
    ),
]


# DOCX bill spec (single, special-case singleton)
DOCX_DOC_ID = "legislature-budget-bill-fy2026-sb1735-2025"
DOCX_LOCAL_PATH = ROOT / "samples" / "raw-docx" / "budget-bill-sb1735-2025.docx"


def _count_pdf_pages(pdf_path: Path) -> int:
    """Page count via pypdf. Cheap (parses xref only)."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    return len(reader.pages)


def _ingest_pdf(target: PdfTarget, *, cache: DownloadCache, out_root: Path,
                force_extract: bool) -> Path:
    """Download → MinerU on full page range. Returns extractor-output dir."""
    print(f"[{target.doc_id}] fetch {target.url}")
    pdf_path = cache.fetch(target.url)
    n_pages = _count_pdf_pages(pdf_path)
    print(f"[{target.doc_id}] {n_pages} pages, sha256={pdf_path.name[:16]}")

    out_dir = out_root / target.doc_id
    sentinel = out_dir / "page-1.json"
    if sentinel.exists() and not force_extract:
        print(f"[{target.doc_id}] extractor output exists — skipping MinerU")
        return out_dir

    print(f"[{target.doc_id}] running MinerU on pages 1-{n_pages}")
    run_mineru(pdf_path, out_dir, list(range(1, n_pages + 1)))
    return out_dir


def _ingest_docx(*, out_root: Path, force_extract: bool) -> Path:
    """Run python-docx ingest on the local DOCX bill."""
    if not DOCX_LOCAL_PATH.exists():
        raise FileNotFoundError(
            f"Bill DOCX not found at {DOCX_LOCAL_PATH}. "
            f"Drop the file there before running the slice."
        )
    out_dir = out_root / DOCX_DOC_ID
    sentinel = out_dir / "document.json"
    if sentinel.exists() and not force_extract:
        print(f"[{DOCX_DOC_ID}] extractor output exists — skipping DOCX ingest")
        return out_dir
    print(f"[{DOCX_DOC_ID}] running python-docx ingest")
    run_docx_ingest(DOCX_LOCAL_PATH, out_dir)
    return out_dir


def _chunk_pdf(target: PdfTarget, extractor_out: Path, *, chunks_dir: Path,
               stamper: EntityStamper) -> int:
    doc_meta = DocMeta(
        doc_id=target.doc_id,
        publisher=target.publisher,
        doc_type=target.doc_type,
        fiscal_year=target.fiscal_year,
        extractor="mineru",
        source_format="pdf",
        source_url=target.url,
    )
    chunks = chunk_doc(
        extractor_output_path=extractor_out,
        doc_meta=doc_meta,
        output_dir=chunks_dir,
        stamper=stamper,
    )
    print(f"[{target.doc_id}] {len(chunks)} chunks written")
    return len(chunks)


def _chunk_docx(extractor_out: Path, *, chunks_dir: Path,
                stamper: EntityStamper) -> int:
    doc_meta = DocMeta(
        doc_id=DOCX_DOC_ID,
        publisher="legislature",
        doc_type="budget-bill",
        fiscal_year=2026,
        extractor="python-docx",
        source_format="docx",
        source_url=None,
    )
    chunks = chunk_doc(
        extractor_output_path=extractor_out / "document.json",
        doc_meta=doc_meta,
        output_dir=chunks_dir,
        stamper=stamper,
    )
    print(f"[{DOCX_DOC_ID}] {len(chunks)} chunks written")
    return len(chunks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo-root", type=Path, default=ROOT,
        help="Repo root (default: detected from script location)",
    )
    parser.add_argument(
        "--force-extract", action="store_true",
        help="Re-run MinerU/DOCX ingest even if extractor output exists",
    )
    parser.add_argument(
        "--skip-pdfs", action="store_true",
        help="Skip PDF slice (useful for dev iteration on the DOCX path)",
    )
    parser.add_argument(
        "--skip-docx", action="store_true",
        help="Skip DOCX bill (useful for iterating on PDF chunking only)",
    )
    args = parser.parse_args(argv)

    repo_root: Path = args.repo_root
    cache = DownloadCache(repo_root / "data" / "cached-pdfs")
    extractor_root = repo_root / "data" / "extractor-output"
    chunks_dir = repo_root / "data" / "chunks"
    chunks_dir.mkdir(parents=True, exist_ok=True)

    # Build the stamper once — its YAML loads are not cheap (rapidfuzz alias map).
    stamper = EntityStamper.from_default_paths()

    total_chunks = 0
    docs_processed = 0

    if not args.skip_pdfs:
        for target in PDF_SLICE:
            ext_out = _ingest_pdf(
                target, cache=cache, out_root=extractor_root,
                force_extract=args.force_extract,
            )
            total_chunks += _chunk_pdf(
                target, ext_out, chunks_dir=chunks_dir, stamper=stamper,
            )
            docs_processed += 1

    if not args.skip_docx:
        ext_out = _ingest_docx(out_root=extractor_root, force_extract=args.force_extract)
        total_chunks += _chunk_docx(ext_out, chunks_dir=chunks_dir, stamper=stamper)
        docs_processed += 1

    print(f"\n--- slice ingest complete: {docs_processed} docs, {total_chunks} chunks ---")
    return 0


if __name__ == "__main__":
    sys.exit(main())
