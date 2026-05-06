"""WS6-T6.1 step 3 chunk-audit script.

Programmatic version of the plan's "manual chunk inspection". Reports:
  - Per-doc chunk count, stamping rate, token-count distribution
  - Provenance correctness (PDF chunks need page+bbox, DOCX need paragraph_id)
  - section_path coverage (no chunks should be missing one)
  - Pydantic schema re-validation (defends against silent on-disk drift)
  - Sample of unstamped chunks per doc (for manual review)

Output: prints a structured report to stdout and writes a JSON copy to
`data/audit/<date>-chunk-audit.json` so the Phase 1b hand-off has a
provenance trail. Exit code is non-zero only when schema validation fails;
soft warnings (low stamping rate, missing provenance) print but don't fail.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from statistics import median

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from chunking.types import Chunk  # noqa: E402  (path-mungling above)

CHUNKS_DIR = ROOT / "data" / "chunks"
AUDIT_DIR = ROOT / "data" / "audit"


def _load_doc(path: Path) -> tuple[list[Chunk], list[tuple[int, str]]]:
    """Return (validated_chunks, schema_errors)."""
    chunks: list[Chunk] = []
    errors: list[tuple[int, str]] = []
    with path.open(encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            raw = raw.strip()
            if not raw:
                continue
            try:
                chunks.append(Chunk.model_validate_json(raw))
            except Exception as exc:  # pydantic.ValidationError or json.JSONDecodeError
                errors.append((lineno, repr(exc)[:200]))
    return chunks, errors


def _audit_one_doc(doc_id: str, chunks: list[Chunk]) -> dict:
    """Produce a per-doc audit dict."""
    n = len(chunks)
    if n == 0:
        return {"doc_id": doc_id, "chunk_count": 0}

    tok = [c.token_count for c in chunks]
    pdf_provenance_missing: list[str] = []
    docx_provenance_missing: list[str] = []
    section_path_missing: list[str] = []

    is_table_count = sum(1 for c in chunks if c.is_table)
    stamped_agency = sum(1 for c in chunks if c.agency_canonical_id)
    stamped_fund = sum(1 for c in chunks if c.fund_canonical_id)
    fund_mentions_populated = sum(1 for c in chunks if c.fund_mentions)

    # Provenance integrity check by doc_type. PDF chunks (mineru / odl)
    # need page; DOCX chunks need paragraph_id (or table_cell_id for table
    # cells, which we accept as last-resort per docx_reader convention).
    for c in chunks:
        if not c.section_path:
            section_path_missing.append(c.chunk_id)
        prov = c.provenance
        if c.publisher in ("legislature",) or c.doc_type == "budget-bill":
            if not prov.paragraph_id and not prov.table_cell_id:
                docx_provenance_missing.append(c.chunk_id)
        else:
            if prov.page is None:
                pdf_provenance_missing.append(c.chunk_id)

    # Sample three unstamped chunks for the report (helps manual review).
    unstamped_samples = [
        {
            "chunk_id": c.chunk_id,
            "section_path": c.section_path[:2],
            "first_60": (c.text[:60].replace("\n", " ").replace("\xa0", " ")),
        }
        for c in chunks
        if not c.agency_canonical_id
    ][:3]

    return {
        "doc_id": doc_id,
        "chunk_count": n,
        "stamped_agency_pct": round(100 * stamped_agency / n, 1),
        "stamped_fund_pct": round(100 * stamped_fund / n, 1),
        "fund_mentions_pct": round(100 * fund_mentions_populated / n, 1),
        "is_table_pct": round(100 * is_table_count / n, 1),
        "tokens_min": min(tok),
        "tokens_median": int(median(tok)),
        "tokens_max": max(tok),
        "tokens_p95": sorted(tok)[int(0.95 * n)] if n >= 20 else max(tok),
        "section_path_missing_count": len(section_path_missing),
        "pdf_provenance_missing_count": len(pdf_provenance_missing),
        "docx_provenance_missing_count": len(docx_provenance_missing),
        "unstamped_samples": unstamped_samples,
    }


def _print_doc_report(rep: dict) -> None:
    print(f"  doc: {rep['doc_id']}  ({rep['chunk_count']} chunks)")
    if rep["chunk_count"] == 0:
        print("    (empty)")
        return
    print(
        f"    stamping:   agency={rep['stamped_agency_pct']:.1f}%  "
        f"fund={rep['stamped_fund_pct']:.1f}%  "
        f"fund_mentions={rep['fund_mentions_pct']:.1f}%  "
        f"is_table={rep['is_table_pct']:.1f}%"
    )
    print(
        f"    tokens:     min={rep['tokens_min']}  median={rep['tokens_median']}  "
        f"p95={rep['tokens_p95']}  max={rep['tokens_max']}"
    )
    if rep["section_path_missing_count"]:
        print(f"    !! section_path missing on {rep['section_path_missing_count']} chunks")
    if rep["pdf_provenance_missing_count"]:
        print(
            f"    !! PDF provenance (page) missing on "
            f"{rep['pdf_provenance_missing_count']} chunks"
        )
    if rep["docx_provenance_missing_count"]:
        print(
            f"    !! DOCX provenance (paragraph_id) missing on "
            f"{rep['docx_provenance_missing_count']} chunks"
        )
    if rep["unstamped_samples"]:
        print("    unstamped samples:")
        for s in rep["unstamped_samples"]:
            sp = " > ".join(s["section_path"]) if s["section_path"] else "(no section)"
            print(f"      [{s['chunk_id'][-4:]}] {sp}")
            print(f"        {s['first_60']!r}")


def main(argv: list[str] | None = None) -> int:
    if not CHUNKS_DIR.exists():
        print(f"ERROR: chunks dir does not exist: {CHUNKS_DIR}", file=sys.stderr)
        return 2

    chunk_files = sorted(CHUNKS_DIR.glob("*.json"))
    if not chunk_files:
        print(f"ERROR: no chunk files in {CHUNKS_DIR}", file=sys.stderr)
        return 2

    print(f"--- Chunk audit: {len(chunk_files)} doc files ---\n")
    per_doc: list[dict] = []
    total_chunks = 0
    total_schema_errors = 0
    for path in chunk_files:
        chunks, errors = _load_doc(path)
        if errors:
            total_schema_errors += len(errors)
            print(f"  doc: {path.stem}  SCHEMA ERRORS:")
            for ln, e in errors[:5]:
                print(f"    line {ln}: {e}")
        rep = _audit_one_doc(path.stem, chunks)
        per_doc.append(rep)
        _print_doc_report(rep)
        total_chunks += rep["chunk_count"]
        print()

    # Aggregate
    total_stamped = sum(
        round(rep["stamped_agency_pct"] / 100 * rep["chunk_count"]) for rep in per_doc
    )
    print(f"--- TOTAL: {total_chunks} chunks; "
          f"agency-stamped {total_stamped} ({100 * total_stamped / max(total_chunks, 1):.1f}%) ---")
    if total_schema_errors:
        print(f"!! {total_schema_errors} schema-validation errors")

    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    audit_path = AUDIT_DIR / f"{datetime.now(timezone.utc).date().isoformat()}-chunk-audit.json"
    audit_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "chunks_dir": str(CHUNKS_DIR),
                "total_chunks": total_chunks,
                "total_schema_errors": total_schema_errors,
                "per_doc": per_doc,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nAudit JSON written: {audit_path}")
    return 1 if total_schema_errors else 0


if __name__ == "__main__":
    sys.exit(main())
