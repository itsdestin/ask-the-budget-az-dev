"""One-shot diagnostic: confirm top_k=15 retrieve() responses fit under
Claude Code's per-tool-result token budget.

Compares response sizes at top_k = 15 and top_k = 20 (the old default).
Task 8 lowers the default to 15; this script's job is to verify that
choice is safe before the change lands.

Run with (bash / Git Bash / WSL):
    set -a; source .env.local; set +a
    uv run python scripts/measure_retrieve_size.py

Or (PowerShell — host shell on Windows):
    Get-Content .env.local | ForEach-Object {
      if ($_ -match '^\s*([^#=]+?)\s*=\s*(.+?)\s*$') {
        [Environment]::SetEnvironmentVariable($matches[1], $matches[2], 'Process')
      }
    }
    uv run python scripts/measure_retrieve_size.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from statistics import mean, median

# Make `db` / `retrieval` importable when invoked as `uv run python scripts/...`.
# Follows the same convention used by scripts/embed_corpus.py.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.embeddings import VoyageEmbedder  # noqa: E402
from retrieval.pipeline import RetrievalRequest, retrieve  # noqa: E402

QUERIES = [
    "ADC FY 2027 General Fund baseline appropriation",
    "AHCCCS Operating Lump Sum FY 2026",
    "Aviation Fund balance fiscal year 2025",
    "Department of Public Safety budget FY 2027",
    "Governor's recommendation Corrections FY 2027",
]


def main() -> None:
    embedder = VoyageEmbedder()
    print(f"{'top_k':>6} | {'mean_bytes':>12} | {'median_bytes':>14} | {'max_bytes':>11}")
    print("-" * 60)
    for top_k in (15, 20):
        sizes: list[int] = []
        chunk_texts: list[int] = []
        for q in QUERIES:
            req = RetrievalRequest(query=q, top_k=top_k)
            # Pre-existing pipeline limitation: ParadeDB's BM25 query parser
            # raises on a bare apostrophe (e.g. "Governor's"). Out of scope
            # for this gating diagnostic — skip the offending query rather
            # than abort the whole run, so the size table still prints.
            try:
                res = retrieve(req, embedder=embedder)
            except Exception as exc:
                print(f"  skipped query (top_k={top_k}): {q!r} -> {exc.__class__.__name__}")
                continue
            payload = json.dumps(
                {
                    "chunks": [
                        {
                            "chunk_id": c.chunk_id,
                            "text": c.text,
                            "doc_id": c.doc_id,
                        }
                        for c in res.chunks
                    ],
                    "top_score": res.top_score,
                }
            )
            sizes.append(len(payload))
            chunk_texts.extend(len(c.text or "") for c in res.chunks)
        if sizes:
            print(
                f"{top_k:>6} | {int(mean(sizes)):>12,} | "
                f"{int(median(sizes)):>14,} | {max(sizes):>11,}"
            )
    if chunk_texts:
        print()
        print(f"Per-chunk text size — mean={int(mean(chunk_texts)):,} "
              f"median={int(median(chunk_texts)):,} "
              f"max={max(chunk_texts):,}")


if __name__ == "__main__":
    main()
