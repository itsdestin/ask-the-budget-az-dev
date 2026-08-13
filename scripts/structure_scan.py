"""Score every document in the corpus with the structural measure (spec X11).

READ-ONLY. It reads chunk text already on disk; it extracts nothing,
embeds nothing, writes nothing to the corpus and re-mints no chunk_id. That
is why it sits outside X8's no-sweep rule entirely.

WHY IT IS COMMITTED rather than left as a throwaway. `ingest/worker.py`
records a score for every rung it runs from now on -- but the corpus that
exists was built by a backfill that is finished, so waiting for new
ingests to produce a second positive example is a plan with no date on it.
This scan answers the same question about the documents already here.

What it said when it was first run, 2026-08-13, against 95,015 chunks:
ONE document over the ceiling (`agao-afr-fy2024`, 30.63%), and a near-miss
band holding exactly one document (`jlbc-baseline-fy2018-545`, 6.25%) --
nothing at all between 6.25% and 30.63%. Two consequences worth keeping:
the ceiling is not a delicate choice, and the "calibrated against one
example" risk is NOT retired by this scan and can only be retired by
genuinely new documents.

Usage:
    JLBC_DATA_DIR=... uv run python -m scripts.structure_scan
"""
from __future__ import annotations

from collections import defaultdict

from ingest.structure import MAX_UNLABELLED, unlabelled_fraction

# The bottom of the near-miss band. Not a threshold anything acts on --
# a reporting boundary. 7.14% is the figure from the ORIGINAL calibration
# sweep in ingest/structure.py, taken at LETTER_RATIO=0.15 (the value first
# proposed there, before it was tightened to the shipped 0.10). At 0.10 that
# same document scores 0.00%, which is why it does not reappear at 7.14% in
# this script's own docstring above -- the two are different runs at
# different ratios, not a contradiction. 0.05 was picked to sit under that
# 0.15-ratio figure with margin to spare, so it stays a safe floor across
# both ratios rather than one recalibrated every time LETTER_RATIO moves.
NEAR_MISS_FLOOR = 0.05

TABLES = ("budget_chunks", "fiscal_note_chunks")


def scan(store) -> dict:
    """Score every document. `store` is anything with ChunkStore's `scan`."""
    texts: dict[str, list[str]] = defaultdict(list)
    for table in TABLES:
        # Two columns only -- never drag vectors out of the store.
        for row in store.scan(table, ["doc_id", "text"]):
            texts[row["doc_id"]].append(row.get("text") or "")

    scores: dict[str, float] = {}
    for doc_id, chunk_texts in texts.items():
        fraction = unlabelled_fraction(chunk_texts)
        if fraction is not None:
            scores[doc_id] = fraction

    over = sorted(
        (d, f) for d, f in scores.items() if f > MAX_UNLABELLED
    )
    near = sorted(
        (d, f) for d, f in scores.items()
        if NEAR_MISS_FLOOR <= f <= MAX_UNLABELLED
    )
    return {
        "documents": len(texts),
        "judgeable": len(scores),
        "over_ceiling": over,
        "near_miss": near,
        "scores": scores,
    }


def main() -> None:
    from store.chunk_store import ChunkStore

    result = scan(ChunkStore())
    print(f"documents            {result['documents']:,}")
    print(f"judgeable (>=10)     {result['judgeable']:,}")
    print(f"over the {MAX_UNLABELLED:.0%} ceiling  {len(result['over_ceiling'])}")
    for doc_id, fraction in result["over_ceiling"]:
        print(f"    {fraction:>7.2%}  {doc_id}")
    print(f"near-miss band       {len(result['near_miss'])}")
    for doc_id, fraction in result["near_miss"]:
        print(f"    {fraction:>7.2%}  {doc_id}")


if __name__ == "__main__":
    main()
