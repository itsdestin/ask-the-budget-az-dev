"""WS6-T6.1 smoke-query script.

Naive in-memory TF-IDF retrieval over `data/chunks/*.json`. Five plan-defined
analyst queries; for each, we verify the expected `doc_id` chunk reaches the
top-3 in cosine-similarity ranking. If it doesn't, something's wrong with
chunk-shape, section paths, or entity stamping — fix before Phase 1b.

This is intentionally NOT sklearn — it's < 80 lines of stdlib + math because
(a) the plan calls for "naive" retrieval, not industrial, and (b) this script
exists for one task and will not be touched after Phase 1a closes. Phase 1b
replaces it with Voyage embeddings + BM25 + rerank.

Run after `python scripts/run_phase_1a_slice.py`. Exits non-zero if any
query fails its top-3 expectation, so it can gate CI later if needed.
"""
from __future__ import annotations

import json
import math
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CHUNKS_DIR = ROOT / "data" / "chunks"

_TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]+")


def _tokenize(text: str) -> list[str]:
    return [t.lower() for t in _TOKEN_RE.findall(text)]


@dataclass
class _Chunk:
    chunk_id: str
    doc_id: str
    text: str
    section_path: list[str]
    agency_canonical_id: str | None
    fund_canonical_id: str | None


def _load_chunks(chunks_dir: Path) -> list[_Chunk]:
    out: list[_Chunk] = []
    for path in sorted(chunks_dir.glob("*.json")):
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                out.append(
                    _Chunk(
                        chunk_id=d["chunk_id"],
                        doc_id=d["doc_id"],
                        text=d.get("text") or "",
                        section_path=d.get("section_path") or [],
                        agency_canonical_id=d.get("agency_canonical_id"),
                        fund_canonical_id=d.get("fund_canonical_id"),
                    )
                )
    return out


def _build_tfidf(chunks: list[_Chunk]) -> tuple[list[dict[str, float]], dict[str, float]]:
    """Per-chunk TF-IDF vector (dict[term]=weight) + global IDF map.

    Vectors are L2-normalized so cosine-similarity reduces to dot product.
    """
    n = len(chunks)
    df: Counter[str] = Counter()
    tfs: list[Counter[str]] = []
    for c in chunks:
        tf = Counter(_tokenize(c.text + " " + " ".join(c.section_path)))
        tfs.append(tf)
        for term in tf:
            df[term] += 1
    # Smoothed IDF: log((n+1)/(df+1)) + 1 — same form scikit-learn uses.
    idf = {term: math.log((n + 1) / (cnt + 1)) + 1.0 for term, cnt in df.items()}

    vectors: list[dict[str, float]] = []
    for tf in tfs:
        vec = {term: (1 + math.log(count)) * idf[term] for term, count in tf.items()}
        norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
        vec = {term: w / norm for term, w in vec.items()}
        vectors.append(vec)
    return vectors, idf


def _query_vector(query: str, idf: dict[str, float]) -> dict[str, float]:
    tf = Counter(_tokenize(query))
    vec: dict[str, float] = {}
    for term, count in tf.items():
        # Drop terms missing from corpus (idf undefined) — they contribute 0.
        weight = idf.get(term)
        if weight is None:
            continue
        vec[term] = (1 + math.log(count)) * weight
    norm = math.sqrt(sum(w * w for w in vec.values())) or 1.0
    return {term: w / norm for term, w in vec.items()}


def _cosine(qv: dict[str, float], dv: dict[str, float]) -> float:
    """Both inputs already L2-normalized — cosine = dot product."""
    if len(qv) > len(dv):
        qv, dv = dv, qv
    return sum(weight * dv.get(term, 0.0) for term, weight in qv.items())


# Plan-defined queries, adapted to slice doc_ids. Bill doc_id has the
# `legislature-` publisher prefix per the driver convention.
QUERIES: list[dict] = [
    {
        "q": "What funds does AHCCCS use?",
        "expected_doc_id": "jlbc-baseline-fy2027-s18",
        "expected_substring": "Health Care Cost Containment",
    },
    {
        "q": "Show me the One-Time GF Adjustments for FY 2026",
        "expected_doc_id": "jlbc-approps-fy2026-bh20",
    },
    {
        "q": "What did the FY 2026 GAA appropriate to ADC?",
        "expected_doc_id": "legislature-budget-bill-fy2026-sb1735-2025",
        "expected_section_substring": "CORRECTIONS",
    },
    {
        "q": "What's the FTE headcount for ADOT?",
        "expected_doc_id": "jlbc-baseline-fy2027-s83",
    },
    {
        "q": "What's in the Aviation Fund?",
        "expected_doc_id": "jlbc-baseline-fy2027-s18",
        "expected_substring": "Aviation",
    },
]


def main(argv: list[str] | None = None) -> int:
    chunks = _load_chunks(CHUNKS_DIR)
    if not chunks:
        print(f"ERROR: no chunks in {CHUNKS_DIR}", file=sys.stderr)
        return 2

    print(f"Loaded {len(chunks)} chunks from {CHUNKS_DIR}")
    by_doc: Counter[str] = Counter(c.doc_id for c in chunks)
    print(f"Per-doc chunk counts:")
    for doc_id, count in sorted(by_doc.items()):
        print(f"  {count:5d}  {doc_id}")

    vectors, idf = _build_tfidf(chunks)
    print(f"\nVocab size: {len(idf)} terms")
    print(f"Total queries: {len(QUERIES)}")
    print()

    failures = 0
    for i, q in enumerate(QUERIES, 1):
        qv = _query_vector(q["q"], idf)
        scores = [(c, _cosine(qv, v)) for c, v in zip(chunks, vectors)]
        scores.sort(key=lambda pair: pair[1], reverse=True)
        top5 = scores[:5]

        print(f"[Q{i}] {q['q']}")
        print(f"     expected: {q['expected_doc_id']}")

        # Find first occurrence of expected doc_id in ranked list
        expected_rank = next(
            (idx + 1 for idx, (c, _) in enumerate(scores) if c.doc_id == q["expected_doc_id"]),
            None,
        )
        # Top-3 check on doc_id only
        top3_docs = {c.doc_id for c, _ in top5[:3]}
        passed = q["expected_doc_id"] in top3_docs
        marker = "PASS" if passed else "FAIL"
        if not passed:
            failures += 1

        print(f"     {marker}: expected doc_id ranked at position {expected_rank or '>' + str(len(chunks))}")
        for rank, (c, score) in enumerate(top5, 1):
            sp = " > ".join(c.section_path[:2]) if c.section_path else "(no section)"
            preview = (c.text[:80] + "...") if len(c.text) > 80 else c.text
            preview = preview.replace("\n", " ").replace("\xa0", " ")
            print(f"       {rank}. [{score:.3f}] {c.doc_id} :: {sp}")
            print(f"            {preview}")
        # Optional substring asserts: search inside the expected doc's
        # top-1 chunk's text (or section_path) for the requested anchor.
        sub = q.get("expected_substring") or q.get("expected_section_substring")
        if sub:
            best_for_doc = next(
                (c for c, _ in scores if c.doc_id == q["expected_doc_id"]),
                None,
            )
            if best_for_doc is None:
                print(f"     SUBSTR: no chunks for {q['expected_doc_id']}")
            else:
                hit = sub.lower() in best_for_doc.text.lower() or any(
                    sub.lower() in seg.lower() for seg in best_for_doc.section_path
                )
                print(f"     SUBSTR: {'found' if hit else 'MISSING'} {sub!r} in best-ranked chunk for expected doc")
        print()

    print(f"--- {len(QUERIES) - failures}/{len(QUERIES)} queries passed top-3 expectation ---")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
