"""End-to-end tests for retrieval/pipeline.py (LanceDB + local models).

Post-swap the pipeline has no server and no external API, so these are
pure unit tests: the two Lance search legs are monkeypatched at the
`retrieval.pipeline` seam, and the embedder / reranker / store are
injected. Nothing here touches a LanceDB directory or loads ONNX
weights — that combination is covered by tests/test_search_lance.py
(real tmp store) and tests/test_local_{embedder,rerank}.py (real
models, marked slow).

The behavioral contract asserted here is the same one the
Postgres/Voyage version had: empty-query short-circuit, RRF
composition of the two legs, diagnostic counts, and top_score ==
first reranked chunk's score.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from retrieval.pipeline import (
    BM25_TOP_K,
    DEFAULT_CORPUS,
    DENSE_TOP_K,
    FUSED_TOP_K,
    RetrievalRequest,
    RetrievalResult,
    retrieve,
)
from retrieval.types import RetrievedChunk

# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------


def _chunk(chunk_id: str, *, score: float = 1.0, publisher: str = "jlbc") -> RetrievedChunk:
    """Minimal valid RetrievedChunk — only chunk_id/score/publisher matter
    to the pipeline (identity for RRF, ordering, and filter assertions)."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{chunk_id}",
        text=f"text of {chunk_id}",
        score=score,
        section_path=["Section"],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=[],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=42,
        publisher=publisher,
    )


class FakeEmbedder:
    """Records how the query was embedded; returns a fixed vector."""

    def __init__(self, vector: list[float] | None = None) -> None:
        self.vector = vector if vector is not None else [0.1, 0.2, 0.3]
        self.calls: list[tuple[str, str]] = []

    def embed_one(self, text: str, *, input_type: str = "document") -> list[float]:
        self.calls.append((text, input_type))
        return list(self.vector)


class FakeReranker:
    """Scores candidates from an explicit map (default: input order, so the
    fused order survives) and slices to top_k, like LocalReranker does."""

    def __init__(self, scores: dict[str, float] | None = None) -> None:
        self.scores = scores or {}
        self.calls: list[tuple[str, list[str], int]] = []

    def rerank(
        self, query: str, chunks: list[RetrievedChunk], *, top_k: int
    ) -> list[RetrievedChunk]:
        self.calls.append((query, [c.chunk_id for c in chunks], top_k))
        rescored = [
            # Default score descends with input position so an un-mapped
            # candidate list comes back in the order it went in.
            replace(c, score=self.scores.get(c.chunk_id, float(len(chunks) - i)))
            for i, c in enumerate(chunks)
        ]
        rescored.sort(key=lambda c: (-c.score, c.chunk_id))
        return rescored[:top_k]


class Seams:
    """Installed over bm25_query_lance / dense_query_lance; records kwargs."""

    def __init__(self, bm25: list[RetrievedChunk], dense: list[RetrievedChunk]) -> None:
        self.bm25_hits = bm25
        self.dense_hits = dense
        self.bm25_calls: list[dict] = []
        self.dense_calls: list[dict] = []

    def bm25(self, query, *, store, corpus, top_k, filters):
        self.bm25_calls.append(
            dict(query=query, store=store, corpus=corpus, top_k=top_k, filters=filters)
        )
        return list(self.bm25_hits)

    def dense(self, query_vector, *, store, corpus, top_k, filters):
        self.dense_calls.append(
            dict(
                vector=query_vector, store=store, corpus=corpus,
                top_k=top_k, filters=filters,
            )
        )
        return list(self.dense_hits)


@pytest.fixture()
def seams(monkeypatch):
    """Default seam wiring: two overlapping legs (c2 is in both)."""
    s = Seams(
        bm25=[_chunk("c1"), _chunk("c2")],
        dense=[_chunk("c2"), _chunk("c3")],
    )
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
    return s


@pytest.fixture(autouse=True)
def _no_real_collaborators(monkeypatch):
    """Any test that reaches a default constructor is a bug in the test (or a
    regression that would download ~150MB of ONNX weights mid-suite), so make
    those constructors raise instead of doing real work."""

    def _boom(name):
        def ctor(*a, **kw):
            raise AssertionError(f"{name} must not be constructed in unit tests")

        return ctor

    monkeypatch.setattr("retrieval.pipeline.ChunkStore", _boom("ChunkStore"))
    monkeypatch.setattr("retrieval.pipeline.LocalEmbedder", _boom("LocalEmbedder"))
    monkeypatch.setattr("retrieval.pipeline.LocalReranker", _boom("LocalReranker"))
    # Globals may have been populated by an earlier test's counting fakes.
    monkeypatch.setattr("retrieval.pipeline._default_store", None)
    monkeypatch.setattr("retrieval.pipeline._default_embedder", None)
    monkeypatch.setattr("retrieval.pipeline._default_reranker", None)


def _run(req: RetrievalRequest, **kw) -> RetrievalResult:
    """retrieve() with all three collaborators injected unless overridden."""
    kw.setdefault("store", object())
    kw.setdefault("embedder", FakeEmbedder())
    kw.setdefault("reranker", FakeReranker())
    return retrieve(req, **kw)


# ---------------------------------------------------------------------------
# Defaults + types
# ---------------------------------------------------------------------------


def test_top_k_defaults_match_spec():
    """Spec §3.4: BM25 top 200, dense top 100, fused top 50, rerank top 15.

    Rerank top-K lowered from 20 → 15 on 2026-05-20 (Decision Q2, dogfood
    hardening). See `test_default_pipeline_top_k_is_fifteen` for the
    locked-in constant assertion.
    """
    assert BM25_TOP_K == 200
    assert DENSE_TOP_K == 100
    assert FUSED_TOP_K == 50
    assert RetrievalRequest(query="x").top_k == 15


def test_default_pipeline_top_k_is_fifteen():
    """Lowered from 20 to 15 (Decision Q2, 2026-05-20) so retrieve()
    responses stay comfortably under Claude Code's 25K-token per-tool-
    result budget without needing a per-chunk text trim. Task 7's
    measurement confirmed top_k=15 fits with headroom for response
    framing.
    """
    from retrieval.pipeline import DEFAULT_PIPELINE_TOP_K

    assert DEFAULT_PIPELINE_TOP_K == 15


def test_request_to_filters_round_trip():
    """RetrievalRequest.to_filters() should mirror every filter dimension."""
    req = RetrievalRequest(
        query="anything",
        fiscal_year=[2026, 2027],
        publisher=["jlbc", "agao"],
        agency_canonical_id=["agency:adc"],
        is_table=True,
    )
    filters = req.to_filters()
    assert filters.fiscal_year == [2026, 2027]
    assert filters.publisher == ["jlbc", "agao"]
    assert filters.agency_canonical_id == ["agency:adc"]
    assert filters.is_table is True
    assert filters.fund_canonical_id is None  # unset stays None


# ---------------------------------------------------------------------------
# Empty-query fast path (no store, no model, no search)
# ---------------------------------------------------------------------------


def test_empty_query_short_circuits(monkeypatch):
    """Whitespace-only query returns an empty result without searching or
    building any collaborator. Called with NO injected store/embedder/
    reranker, so the autouse fixture's exploding constructors are the
    assertion: reaching them fails the test."""
    monkeypatch.setattr(
        "retrieval.pipeline.bm25_query_lance",
        lambda *a, **kw: pytest.fail("bm25 leg ran on an empty query"),
    )
    monkeypatch.setattr(
        "retrieval.pipeline.dense_query_lance",
        lambda *a, **kw: pytest.fail("dense leg ran on an empty query"),
    )
    result = retrieve(RetrievalRequest(query=""))
    assert isinstance(result, RetrievalResult)
    assert result.chunks == []
    assert result.top_score == 0.0
    assert result.bm25_count == 0


def test_empty_query_with_whitespace_short_circuits():
    result = retrieve(RetrievalRequest(query="   \t\n  "))
    assert result.chunks == []


# ---------------------------------------------------------------------------
# Corpus routing
# ---------------------------------------------------------------------------


def test_default_corpus_is_budget(monkeypatch):
    seen = {}

    def fake_bm25(query, *, store, corpus, top_k, filters):
        seen["corpus"] = corpus
        return []

    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", fake_bm25)
    monkeypatch.setattr(
        "retrieval.pipeline.dense_query_lance",
        lambda v, *, store, corpus, top_k, filters: [],
    )

    class FakeEmb:
        def embed_one(self, text, *, input_type="query"):
            return [0.0]

    retrieve(RetrievalRequest(query="x"), store=object(), embedder=FakeEmb())
    assert seen["corpus"] == "budget_chunks"
    assert DEFAULT_CORPUS == "budget_chunks"


def test_request_corpus_routes_both_legs(seams):
    """A non-default corpus must reach BOTH legs — a lexical hit from one
    corpus fused with dense hits from another would be silent nonsense."""
    _run(RetrievalRequest(query="fund", corpus="fiscal_note_chunks"))
    assert seams.bm25_calls[0]["corpus"] == "fiscal_note_chunks"
    assert seams.dense_calls[0]["corpus"] == "fiscal_note_chunks"


# ---------------------------------------------------------------------------
# Composition: legs -> RRF -> rerank
# ---------------------------------------------------------------------------


def test_retrieve_fuses_both_legs_and_reranks(seams):
    reranker = FakeReranker(scores={"c1": 8.5, "c2": 2.0, "c3": -1.0})
    result = _run(RetrievalRequest(query="aviation fund", top_k=5), reranker=reranker)

    assert [c.chunk_id for c in result.chunks] == ["c1", "c2", "c3"]
    assert result.top_score == 8.5 == result.chunks[0].score
    assert result.reranker_scores == [8.5, 2.0, -1.0]
    # Raw cross-encoder logits are NOT 0..1 — a negative score must survive
    # the pipeline untouched (no clamping anywhere).
    assert result.chunks[-1].score == -1.0


def test_diagnostic_counts_report_each_stage(seams):
    """bm25/dense counts are the raw leg sizes; fused_count is deduped, so
    c2 (present in both legs) is counted once."""
    result = _run(RetrievalRequest(query="fund"))
    assert result.bm25_count == 2
    assert result.dense_count == 2
    assert result.fused_count == 3
    assert len(result.reranker_scores) == len(result.chunks)


def test_rrf_weights_shift_the_fused_order(seams):
    """bm25_weight=0 makes the fused ranking dense-only — the knob is wired
    through to rrf_fuse, not silently dropped."""
    reranker = FakeReranker()  # preserves fused order
    result = _run(RetrievalRequest(query="fund"), reranker=reranker, bm25_weight=0.0)
    # Dense leg order is c2, c3; c1 contributes 0 and lands last.
    assert reranker.calls[0][1] == ["c2", "c3", "c1"]
    assert result.chunks[0].chunk_id == "c2"


def test_no_candidates_returns_counts_and_skips_rerank(monkeypatch):
    """Both legs empty -> no rerank call at all (the reranker is the
    expensive stage; running it on an empty list is pure waste)."""
    s = Seams(bm25=[], dense=[])
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
    reranker = FakeReranker()

    result = _run(RetrievalRequest(query="nonexistent"), reranker=reranker)
    assert result.chunks == []
    assert result.top_score == 0.0
    assert result.fused_count == 0
    assert reranker.calls == []


def test_top_k_is_forwarded_to_the_reranker(seams):
    reranker = FakeReranker()
    result = _run(RetrievalRequest(query="fund", top_k=2), reranker=reranker)
    assert reranker.calls[0][2] == 2
    assert len(result.chunks) == 2


def test_stage_top_k_overrides_reach_the_legs(seams):
    _run(
        RetrievalRequest(query="fund"),
        bm25_top_k=7,
        dense_top_k=9,
        fused_top_k=1,
    )
    assert seams.bm25_calls[0]["top_k"] == 7
    assert seams.dense_calls[0]["top_k"] == 9


def test_fused_top_k_caps_the_rerank_candidate_list(seams):
    reranker = FakeReranker()
    result = _run(RetrievalRequest(query="fund"), reranker=reranker, fused_top_k=1)
    assert len(reranker.calls[0][1]) == 1
    assert result.fused_count == 1


def test_stage_defaults_are_the_module_constants(seams):
    _run(RetrievalRequest(query="fund"))
    assert seams.bm25_calls[0]["top_k"] == BM25_TOP_K
    assert seams.dense_calls[0]["top_k"] == DENSE_TOP_K


# ---------------------------------------------------------------------------
# Plumbing: query text, vector, filters, store
# ---------------------------------------------------------------------------


def test_query_is_embedded_as_a_query_not_a_document(seams):
    """input_type="query" is the forward-compat contract with LocalEmbedder;
    embedding the query as a passage would be a silent quality regression."""
    embedder = FakeEmbedder(vector=[0.5, 0.6])
    _run(RetrievalRequest(query="aviation fund"), embedder=embedder)
    assert embedder.calls == [("aviation fund", "query")]
    # The embedded vector — not the raw text — is what the dense leg gets.
    assert seams.dense_calls[0]["vector"] == [0.5, 0.6]


def test_raw_query_text_goes_to_the_lexical_leg_and_reranker(seams):
    reranker = FakeReranker()
    _run(RetrievalRequest(query="aviation fund"), reranker=reranker)
    assert seams.bm25_calls[0]["query"] == "aviation fund"
    assert reranker.calls[0][0] == "aviation fund"


def test_filters_are_applied_uniformly_to_both_legs(seams):
    """Same RetrievalFilters object on both legs — a filter honored by only
    one leg would leak out-of-scope chunks through RRF."""
    req = RetrievalRequest(query="appropriation", publisher=["legislature"], is_table=True)
    _run(req)
    bm25_filters = seams.bm25_calls[0]["filters"]
    dense_filters = seams.dense_calls[0]["filters"]
    assert bm25_filters == req.to_filters()
    assert dense_filters == bm25_filters


def test_injected_store_is_handed_to_both_legs(seams):
    store = object()
    _run(RetrievalRequest(query="fund"), store=store)
    assert seams.bm25_calls[0]["store"] is store
    assert seams.dense_calls[0]["store"] is store


# ---------------------------------------------------------------------------
# Lazy default collaborators
# ---------------------------------------------------------------------------


def test_defaults_are_built_once_and_reused(seams, monkeypatch):
    """ONNX weights load in seconds and cost real memory; the process must
    build each collaborator at most once, not per query."""
    built: list[str] = []

    class FakeStore:
        def __init__(self):
            built.append("store")

    class Emb(FakeEmbedder):
        def __init__(self):
            built.append("embedder")
            super().__init__()

    class RR(FakeReranker):
        def __init__(self):
            built.append("reranker")
            super().__init__()

    monkeypatch.setattr("retrieval.pipeline.ChunkStore", FakeStore)
    monkeypatch.setattr("retrieval.pipeline.LocalEmbedder", Emb)
    monkeypatch.setattr("retrieval.pipeline.LocalReranker", RR)

    retrieve(RetrievalRequest(query="fund"))
    retrieve(RetrievalRequest(query="fund again"))
    assert sorted(built) == ["embedder", "reranker", "store"]


def test_injected_collaborators_suppress_default_construction(seams):
    """The autouse fixture makes every default constructor raise, so a fully
    injected call completing at all proves nothing extra was built. Guards
    the trap where one missing collaborator builds all three."""
    result = _run(RetrievalRequest(query="fund"))
    assert result.fused_count == 3


def test_missing_reranker_does_not_build_a_store_or_embedder(seams, monkeypatch):
    """Partial injection must build ONLY the gap. This is the shape of the
    common test/eval call (real store, fake models) and of api.py's."""
    built: list[str] = []

    class RR(FakeReranker):
        def __init__(self):
            built.append("reranker")
            super().__init__()

    monkeypatch.setattr("retrieval.pipeline.LocalReranker", RR)
    # ChunkStore / LocalEmbedder still explode if touched.
    result = retrieve(
        RetrievalRequest(query="fund"), store=object(), embedder=FakeEmbedder()
    )
    assert built == ["reranker"]
    assert len(result.chunks) == 3
