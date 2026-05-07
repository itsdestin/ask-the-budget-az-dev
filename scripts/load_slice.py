"""Load Phase 1a slice chunks into Postgres.

Phase 1b WS2, Task 2.1 Step 3. Reads the 5 NDJSON files emitted by
`scripts/run_phase_1a_slice.py` from `data/chunks/` and upserts them
through `db.loader.load_chunk_file`. After volume ingest comes online,
this becomes `scripts/load_corpus.py` driven by a richer manifest.

Prerequisites:
  - Postgres stack up: `cd db && docker compose up -d`
  - Migrations applied: `psql ... -f db/migrations/000{1,2,3}_*.sql`
  - Slice ingested: `uv run python scripts/run_phase_1a_slice.py`
    (produces `data/chunks/<doc-id>.json` for each of the 5 slice docs)

Usage:
  set -a; source .env.local; set +a   # load DATABASE_URL
  uv run python scripts/load_slice.py [--validate]

  --validate runs db.validate.run_checks after loading and exits non-zero
  on any failure.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Repo root on sys.path so `db.*` imports work when the script is invoked
# as `uv run python scripts/load_slice.py` rather than as a module.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.connection import get_connection  # noqa: E402
from db.loader import DocumentMeta, load_chunk_file  # noqa: E402
from db.validate import format_results, run_checks  # noqa: E402

CHUNKS_DIR = ROOT / "data" / "chunks"

# DocumentMeta for the 5 slice docs. Mirrors PDF_SLICE in
# scripts/run_phase_1a_slice.py + the DOCX target. When a 6th doc joins
# the slice, add an entry here too.
SLICE_DOC_META: list[DocumentMeta] = [
    DocumentMeta(
        doc_id="jlbc-baseline-fy2027-s18",
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
        title="JLBC FY2027 Baseline s18 — Other Fund Summary by Agency",
        source_url="https://www.azjlbc.gov/27baseline/s18.pdf",
        source_format="pdf",
        source_blob_path="data/cached-pdfs/jlbc-baseline-fy2027-s18.pdf",
        extractor="mineru-2.5",
        extractor_version="2.5.0",
    ),
    DocumentMeta(
        doc_id="jlbc-baseline-fy2027-s83",
        publisher="jlbc",
        doc_type="baseline-cross-cut",
        fiscal_year=2027,
        title="JLBC FY2027 Baseline s83 — State Personnel Summary",
        source_url="https://www.azjlbc.gov/27baseline/s83.pdf",
        source_format="pdf",
        source_blob_path="data/cached-pdfs/jlbc-baseline-fy2027-s83.pdf",
        extractor="mineru-2.5",
        extractor_version="2.5.0",
    ),
    DocumentMeta(
        doc_id="jlbc-approps-fy2026-bh20",
        publisher="jlbc",
        doc_type="approps-cross-cut",
        fiscal_year=2026,
        title="JLBC FY2026 Approps bh20 — One-Time GF Adjustments",
        source_url="https://www.azjlbc.gov/26ar/bh20.pdf",
        source_format="pdf",
        source_blob_path="data/cached-pdfs/jlbc-approps-fy2026-bh20.pdf",
        extractor="mineru-2.5",
        extractor_version="2.5.0",
    ),
    DocumentMeta(
        doc_id="jlbc-approps-fy2026-bd2",
        publisher="jlbc",
        doc_type="approps-cross-cut",
        fiscal_year=2026,
        title="JLBC FY2026 Approps bd2 — FY26 Budget Detail by Agency × Fund",
        source_url="https://www.azjlbc.gov/26ar/bd2.pdf",
        source_format="pdf",
        source_blob_path="data/cached-pdfs/jlbc-approps-fy2026-bd2.pdf",
        extractor="mineru-2.5",
        extractor_version="2.5.0",
    ),
    DocumentMeta(
        doc_id="legislature-budget-bill-fy2026-sb1735-2025",
        publisher="legislature",
        doc_type="budget-bill",
        fiscal_year=2026,
        title="Arizona SB 1735 (2025 Session) — General Appropriations Act for FY2026",
        source_url=None,  # local DOCX, no public source URL
        source_format="docx",
        source_blob_path="samples/raw-docx/budget-bill-sb1735-2025.docx",
        extractor="python-docx",
        extractor_version="1.2.0",
    ),
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validate",
        action="store_true",
        help="Run db.validate.run_checks after loading; exit 1 on any failure.",
    )
    args = parser.parse_args()

    missing = [
        meta.doc_id
        for meta in SLICE_DOC_META
        if not (CHUNKS_DIR / f"{meta.doc_id}.json").exists()
    ]
    if missing:
        print(
            "ERROR: chunk files missing from data/chunks/:\n  - "
            + "\n  - ".join(missing)
            + "\n\nRun `uv run python scripts/run_phase_1a_slice.py` first.",
            file=sys.stderr,
        )
        return 2

    total = 0
    with get_connection() as conn:
        for meta in SLICE_DOC_META:
            path = CHUNKS_DIR / f"{meta.doc_id}.json"
            n = load_chunk_file(path, meta, conn)
            print(f"  loaded {meta.doc_id}: {n} chunks")
            total += n

        print(f"\nTotal chunks loaded: {total}")

        if args.validate:
            print("\nValidation checks:")
            results = run_checks(conn)
            print(format_results(results))
            if any(not r.passed for r in results):
                return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
