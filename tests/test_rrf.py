"""Pure unit tests for retrieval/rrf.py — no DB, no API calls."""
from __future__ import annotations

from retrieval.rrf import DEFAULT_K, RankedList, rrf_fuse
from retrieval.types import RetrievedChunk


def _chunk(chunk_id: str, score: float = 1.0) -> RetrievedChunk:
    """Synthetic chunk fixture — only chunk_id + score matter for RRF."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id="d1",
        text="t",
        score=score,
        section_path=[],
        page=1,
        bbox=[0.0, 0.0, 1.0, 1.0],
        source_anchor=None,
        agency_canonical_ids=[],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2027,
        doc_type="baseline-cross-cut",
        is_table=False,
        table_html=None,
        token_count=1,
        publisher="jlbc",
    )


def test_rrf_empty_inputs_return_empty():
    assert rrf_fuse([]) == []
    assert rrf_fuse([[], []]) == []


def test_rrf_single_list_passes_through_in_order():
    """One list -> RRF preserves the original order with score = 1/(k+rank)."""
    chunks = [_chunk(f"c{i}") for i in range(5)]
    fused = rrf_fuse([chunks], top_k=10)

    assert [c.chunk_id for c in fused] == ["c0", "c1", "c2", "c3", "c4"]
    # rank-1 chunk: score = 1/(60+1) = ~0.01639
    assert abs(fused[0].score - 1.0 / (DEFAULT_K + 1)) < 1e-9
    # rank-5 chunk: score = 1/(60+5) = ~0.01538
    assert abs(fused[4].score - 1.0 / (DEFAULT_K + 5)) < 1e-9


def test_rrf_chunk_in_both_lists_gets_summed_score():
    """Chunk c0 ranks #1 in both lists -> RRF score = 2 * 1/(60+1)."""
    list_a = [_chunk("c0"), _chunk("c1")]
    list_b = [_chunk("c0"), _chunk("c2")]

    fused = rrf_fuse([list_a, list_b], top_k=10)
    by_id = {c.chunk_id: c.score for c in fused}

    assert abs(by_id["c0"] - 2.0 / (DEFAULT_K + 1)) < 1e-9
    assert abs(by_id["c1"] - 1.0 / (DEFAULT_K + 2)) < 1e-9
    assert abs(by_id["c2"] - 1.0 / (DEFAULT_K + 2)) < 1e-9
    # c0 wins because it's in both
    assert fused[0].chunk_id == "c0"


def test_rrf_weighted_lists_amplify_one_source():
    """BM25 weight=2 means BM25 contributions count double — useful for
    lookup-type queries where lexical match should dominate (spec §3.4)."""
    bm25 = RankedList(chunks=[_chunk("lexical_winner"), _chunk("shared")], weight=2.0)
    dense = RankedList(chunks=[_chunk("shared"), _chunk("dense_winner")], weight=1.0)

    fused = rrf_fuse([bm25, dense], top_k=10)
    by_id = {c.chunk_id: c.score for c in fused}

    # lexical_winner: 2.0/(60+1) = ~0.0328
    # shared: 2.0/(60+2) + 1.0/(60+1) = ~0.0322 + ~0.0164 = ~0.0486
    # dense_winner: 1.0/(60+2) = ~0.0161
    assert by_id["shared"] > by_id["lexical_winner"]  # shows up in both, beats single-source
    assert by_id["lexical_winner"] > by_id["dense_winner"]  # weight=2 wins single-source vs weight=1


def test_rrf_top_k_truncation():
    """top_k=2 returns only the 2 highest-scoring chunks."""
    list_a = [_chunk(f"c{i}") for i in range(5)]
    fused = rrf_fuse([list_a], top_k=2)

    assert len(fused) == 2
    assert [c.chunk_id for c in fused] == ["c0", "c1"]


def test_rrf_top_k_zero_returns_empty():
    list_a = [_chunk(f"c{i}") for i in range(5)]
    assert rrf_fuse([list_a], top_k=0) == []


def test_rrf_chunk_id_tiebreaker_for_determinism():
    """Two chunks with identical RRF score sort by chunk_id ascending so
    repeated calls return the same order."""
    # Both 'a' and 'b' rank #1 in their respective lists -> identical scores
    list_a = [_chunk("b")]
    list_b = [_chunk("a")]

    fused = rrf_fuse([list_a, list_b], top_k=10)
    assert [c.chunk_id for c in fused] == ["a", "b"]  # alphabetical tiebreak


def test_rrf_first_seen_metadata_preserved():
    """When a chunk appears in multiple lists, the first occurrence's
    full metadata is what lands in the output (we don't re-merge fields)."""
    first = _chunk("c0")
    # Different agency stamping on the second occurrence
    second_data = _chunk("c0")
    different = RetrievedChunk(
        **{**second_data.__dict__, "agency_canonical_ids": ["agency:other"]}
    )

    fused = rrf_fuse([[first], [different]], top_k=10)
    assert fused[0].agency_canonical_ids == []  # from `first`, not `different`


def test_rrf_score_replaces_original():
    """Original BM25/dense scores are gone after fusion — `.score` is the
    RRF score now. (Downstream rerank replaces it again.)"""
    big_score_chunk = _chunk("c0", score=999.0)
    fused = rrf_fuse([[big_score_chunk]], top_k=10)
    assert fused[0].chunk_id == "c0"
    # RRF score for rank-1 with default k=60 is 1/61 ~= 0.0164
    assert fused[0].score < 1.0


def test_rrf_three_lists_fuse():
    """Verifies the >2-list case (e.g. multi-modal retrieval in Phase 2)."""
    a = [_chunk("c0"), _chunk("c1")]
    b = [_chunk("c2"), _chunk("c0")]
    c = [_chunk("c1"), _chunk("c2"), _chunk("c0")]

    fused = rrf_fuse([a, b, c], top_k=10)
    by_id = {x.chunk_id: x.score for x in fused}
    # c0 appears at ranks 1, 2, 3 across the three lists
    expected_c0 = 1 / (DEFAULT_K + 1) + 1 / (DEFAULT_K + 2) + 1 / (DEFAULT_K + 3)
    assert abs(by_id["c0"] - expected_c0) < 1e-9
