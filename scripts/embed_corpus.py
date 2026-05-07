"""Run Voyage embeddings against every chunk that doesn't yet have one.

Phase 1b WS3, Task 3.2 Step 3. CLI entry point for the embed pipeline:

    uv run python scripts/embed_corpus.py [--yes] [--batch-size N] [--reindex]

Prints a cost estimate (Voyage-3-large pricing applied to unembedded
token_count totals) and, by default, asks for confirmation before
spending money. `--yes` skips the prompt.

`--reindex` runs `REINDEX INDEX chunks_embedding_hnsw` after the embed
loop completes. pgvector's HNSW index quality is materially better
when (re)built after data is loaded.

Idempotent: re-running picks up wherever the last call left off,
because the SQL filters on `embedding IS NULL`. Mid-run failures
preserve any rows already updated; restart the script and it
continues.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from db.connection import get_connection  # noqa: E402
from db.embeddings import (  # noqa: E402
    DEFAULT_BATCH_SIZE,
    VoyageEmbedder,
    count_unembedded,
    embed_unembedded,
    estimate_unembedded_tokens,
    reindex_hnsw,
)

# Voyage-3-large pricing as of 2026 (USD per 1M tokens).
DOCUMENT_TOKEN_PRICE_USD_PER_M = 0.18


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip cost confirmation prompt.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=DEFAULT_BATCH_SIZE,
        help=f"Texts per Voyage call (default: {DEFAULT_BATCH_SIZE}).",
    )
    parser.add_argument(
        "--reindex",
        action="store_true",
        help="REINDEX chunks_embedding_hnsw after the embed loop.",
    )
    args = parser.parse_args()

    with get_connection() as conn:
        unembedded_n = count_unembedded(conn)
        unembedded_tokens = estimate_unembedded_tokens(conn)
        cost_usd = unembedded_tokens * DOCUMENT_TOKEN_PRICE_USD_PER_M / 1_000_000

        print(f"Unembedded chunks: {unembedded_n:,}")
        print(f"Unembedded tokens: {unembedded_tokens:,}")
        print(f"Estimated cost   : ${cost_usd:.4f} (voyage-3-large @ ${DOCUMENT_TOKEN_PRICE_USD_PER_M}/1M doc tokens)")

        if unembedded_n == 0:
            print("\nNothing to do.")
            return 0

        if not args.yes:
            print()
            confirm = input("Proceed? [y/N] ").strip().lower()
            if confirm != "y":
                print("Aborted.")
                return 1

        print("\nEmbedding...")
        start = time.monotonic()
        embedder = VoyageEmbedder()
        embedded = embed_unembedded(
            conn,
            embedder,
            batch_size=args.batch_size,
            progress=_print_progress,
        )
        elapsed = time.monotonic() - start
        print(f"\nEmbedded {embedded} chunks in {elapsed:.1f}s.")

        if args.reindex:
            print("Rebuilding HNSW index over chunks.embedding...")
            t0 = time.monotonic()
            reindex_hnsw(conn)
            print(f"  done in {time.monotonic() - t0:.1f}s")

    return 0


def _print_progress(done: int, total: int, batch: int) -> None:
    pct = (done / total) * 100 if total else 100.0
    print(f"  [{done}/{total}] {pct:5.1f}%  (+{batch} this batch)", end="\r", flush=True)


if __name__ == "__main__":
    sys.exit(main())
