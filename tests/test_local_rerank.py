import pytest

from retrieval.local_rerank import LocalReranker
from retrieval.types import RetrievedChunk


def _chunk(cid: str, text: str) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=cid, doc_id="d", text=text, score=0.0, section_path=[],
        page=None, bbox=None, source_anchor=None, agency_canonical_ids=[],
        fund_canonical_id=None, fund_mentions=[], fiscal_year=None,
        doc_type="t", is_table=False, table_html=None, token_count=1,
        publisher="jlbc",
    )


class FakeCrossEncoder:
    def rerank(self, query, documents):
        # Score = position-reversed so ordering visibly changes.
        n = len(list(documents))
        return iter([0.1 * (i + 1) for i in range(n)])


def test_rerank_orders_by_score_and_truncates():
    rr = LocalReranker(model=FakeCrossEncoder())
    chunks = [_chunk("a", "one"), _chunk("b", "two"), _chunk("c", "three")]
    out = rr.rerank("q", chunks, top_k=2)
    # Fake scores: a=0.1, b=0.2, c=0.3 -> order c, b
    assert [c.chunk_id for c in out] == ["c", "b"]
    assert out[0].score == pytest.approx(0.3)


def test_empty_input_returns_empty():
    rr = LocalReranker(model=FakeCrossEncoder())
    assert rr.rerank("q", [], top_k=5) == []


class ShortScoreCrossEncoder:
    """Returns fewer scores than documents — the silent-drop failure mode."""

    def rerank(self, query, documents):
        return iter([0.5])


def test_short_score_iterable_raises_instead_of_dropping():
    rr = LocalReranker(model=ShortScoreCrossEncoder())
    chunks = [_chunk("a", "one"), _chunk("b", "two")]
    with pytest.raises(ValueError):
        rr.rerank("q", chunks, top_k=2)


@pytest.mark.parametrize("bad_top_k", [0, -1])
def test_nonpositive_top_k_raises(bad_top_k):
    # top_k=-1 would slice [:-1] and silently drop the last chunk.
    rr = LocalReranker(model=FakeCrossEncoder())
    with pytest.raises(ValueError, match="top_k"):
        rr.rerank("q", [_chunk("a", "one")], top_k=bad_top_k)


@pytest.mark.slow
def test_real_model_prefers_relevant_text():
    rr = LocalReranker()
    chunks = [
        _chunk("bad", "recipe for banana bread with walnuts"),
        _chunk("good", "AHCCCS provider rate increases in the FY 2026 baseline"),
    ]
    out = rr.rerank("ahcccs provider rates", chunks, top_k=2)
    assert out[0].chunk_id == "good"
