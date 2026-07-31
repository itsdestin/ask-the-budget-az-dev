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
    NO_RESULTS_TOP_SCORE,
    RetrievalRequest,
    RetrievalResult,
    reset_default_collaborators,
    retrieve,
)
from retrieval.recency import recency_weight
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
    # Singletons may have been populated by an earlier test's counting fakes.
    # Cleared through the public hook (not by nulling the globals) so this
    # fixture exercises the same path Task 9's tests will use, and again on
    # the way out so no fake instance leaks into another module's tests.
    reset_default_collaborators()
    yield
    reset_default_collaborators()


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
    """Spec §3.4 with two deliberate lowerings: BM25 top 200, dense top
    100, fused top 20, rerank top 15.

    Rerank top-K lowered 20 → 15 on 2026-05-20 (Decision Q2, dogfood
    hardening). Fused lowered 50 → 20 on 2026-07-30 with the L-12
    reranker swap — the local cross-encoder makes a 50-candidate rerank
    cost ~4.9s/query, over the ~3s interactive budget (see FUSED_TOP_K's
    WHY comment in retrieval/pipeline.py).
    """
    assert BM25_TOP_K == 200
    assert DENSE_TOP_K == 100
    assert FUSED_TOP_K == 20
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
    assert result.top_score == NO_RESULTS_TOP_SCORE
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


@pytest.fixture()
def empty_seams(monkeypatch):
    """Both legs return nothing — the over-filtered / empty-corpus case."""
    s = Seams(bm25=[], dense=[])
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
    return s


def test_no_candidates_never_builds_the_reranker(empty_seams):
    """Both legs empty -> the reranker is not merely un-CALLED, it is never
    CONSTRUCTED. No reranker is injected here, so the autouse fixture's
    exploding LocalReranker constructor is the assertion — the previous
    version of this test injected a fake and could only prove `.rerank()`
    wasn't called, which a version that eagerly built the model would still
    have passed."""
    result = retrieve(
        RetrievalRequest(query="nonexistent"),
        store=object(),
        embedder=FakeEmbedder(),
    )
    assert result.chunks == []
    assert result.fused_count == 0
    assert result.bm25_count == 0
    assert result.dense_count == 0


def test_no_results_top_score_is_below_every_real_logit(empty_seams):
    """THE refusal-safety invariant. Reranker scores are raw cross-encoder
    logits: measured on the migrated corpus, genuine hits land at +2.27..+7.72
    and a pure-gibberish query at -11.12. If "found nothing" reported 0.0 (as
    it did under Voyage's 0..1 scale) it would outrank that gibberish hit, and
    Task 12's threshold — which will sit at or below 0 — would read an empty
    result as a confident one.

    Reachable without contrivance: over-filtering (fiscal_year=[1999]) or any
    query against the still-empty fiscal_note_chunks table.
    """
    result = retrieve(
        RetrievalRequest(query="over-filtered", fiscal_year=[1999]),
        store=object(),
        embedder=FakeEmbedder(),
    )
    assert result.top_score == NO_RESULTS_TOP_SCORE
    # Below the worst real logit ever measured, with room to spare.
    assert result.top_score < -11.12
    # Every plausible calibrated threshold must refuse this result.
    for threshold in (-5.0, -1.0, 0.0, 0.65, 2.0):
        assert result.top_score < threshold


def test_no_results_sentinel_is_json_serializable():
    """WHY not float("-inf"): api.py hands top_score to clients. Measured on
    the pinned pydantic/fastapi, -inf serializes to JSON `null` through a
    response model (breaking the MCP server's `top_score < threshold`) and
    raises ValueError through a bare JSONResponse (allow_nan=False). A finite
    floor has neither failure mode."""
    import json
    import math

    assert math.isfinite(NO_RESULTS_TOP_SCORE)
    assert json.dumps({"top_score": NO_RESULTS_TOP_SCORE}, allow_nan=False)


def test_the_reranker_scores_the_whole_pool_and_top_k_trims_afterwards(seams):
    """`top_k` used to be forwarded to the reranker. It is not any more:
    the S21 recency pass runs between rerank and trim and can only reorder
    chunks it can see, so the reranker returns everything it scored and
    the trim happens last. The caller's contract is unchanged — top_k
    still bounds what comes back."""
    reranker = FakeReranker()
    result = _run(RetrievalRequest(query="fund", top_k=2), reranker=reranker)
    fused_size = len(reranker.calls[0][1])
    assert reranker.calls[0][2] == fused_size
    assert len(result.chunks) == 2


def test_stage_top_k_and_rrf_k_overrides_reach_their_stages(seams, monkeypatch):
    """Covers rrf_k too: it used to be possible to delete `k=rrf_k` from the
    rrf_fuse call without failing a single test. The spy's keyword-only
    signature makes that a TypeError."""
    from retrieval import rrf as rrf_module

    real_fuse = rrf_module.rrf_fuse
    seen: dict[str, int] = {}

    def spy(ranked_lists, *, k, top_k):
        seen.update(k=k, top_k=top_k)
        return real_fuse(ranked_lists, k=k, top_k=top_k)

    monkeypatch.setattr("retrieval.pipeline.rrf_fuse", spy)
    _run(
        RetrievalRequest(query="fund"),
        bm25_top_k=7,
        dense_top_k=9,
        fused_top_k=1,
        rrf_k=13,
    )
    assert seams.bm25_calls[0]["top_k"] == 7
    assert seams.dense_calls[0]["top_k"] == 9
    assert seen == {"k": 13, "top_k": 1}


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


def test_concurrent_first_calls_build_each_collaborator_once(monkeypatch):
    """Pins `_defaults_lock`. Without it this test fails: FastAPI runs sync
    endpoints in a threadpool, so N simultaneous first requests would each
    sail past the `is None` check before any of them assigned the global and
    build N full model stacks (N x ~3.6s cold start, N x resident memory,
    N-1 of them promptly orphaned).

    Deterministic by construction: each fake constructor sleeps well past the
    thread-start jitter, so if the lock were removed every thread would be
    inside a constructor at the same moment.
    """
    import threading
    import time

    from retrieval.pipeline import _get_embedder, _get_reranker, _get_store

    counts = {"store": 0, "embedder": 0, "reranker": 0}
    counts_lock = threading.Lock()

    def slow_ctor(name):
        def ctor(*a, **kw):
            with counts_lock:
                counts[name] += 1
            # Hold the window open: any racer that got past the `is None`
            # check will be inside its own constructor while we sleep.
            time.sleep(0.2)
            return f"{name}-instance"

        return ctor

    monkeypatch.setattr("retrieval.pipeline.ChunkStore", slow_ctor("store"))
    monkeypatch.setattr("retrieval.pipeline.LocalEmbedder", slow_ctor("embedder"))
    monkeypatch.setattr("retrieval.pipeline.LocalReranker", slow_ctor("reranker"))

    got: list[tuple] = []
    got_lock = threading.Lock()
    start = threading.Barrier(8)

    def worker():
        start.wait()  # release all threads at once
        trio = (_get_store(), _get_embedder(), _get_reranker())
        with got_lock:
            got.append(trio)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "getter deadlocked"

    assert counts == {"store": 1, "embedder": 1, "reranker": 1}
    # Every thread must have received the SAME instances, not just one each.
    assert len(got) == 8
    assert all(trio is got[0] or trio == got[0] for trio in got)


def test_reset_default_collaborators_forces_a_rebuild(seams, monkeypatch):
    """The public hook Task 9's tests use instead of poking private globals."""
    built: list[str] = []

    def counting(name):
        def ctor(*a, **kw):
            built.append(name)
            return {"store": object, "embedder": FakeEmbedder, "reranker": FakeReranker}[
                name
            ]()

        return ctor

    monkeypatch.setattr("retrieval.pipeline.ChunkStore", counting("store"))
    monkeypatch.setattr("retrieval.pipeline.LocalEmbedder", counting("embedder"))
    monkeypatch.setattr("retrieval.pipeline.LocalReranker", counting("reranker"))

    retrieve(RetrievalRequest(query="fund"))
    assert sorted(built) == ["embedder", "reranker", "store"]

    reset_default_collaborators()
    retrieve(RetrievalRequest(query="fund"))
    assert sorted(built) == ["embedder", "embedder", "reranker", "reranker", "store", "store"]


# ---------------------------------------------------------------------------
# Integration: retrieve() over a REAL ChunkStore + real search legs
# ---------------------------------------------------------------------------


def _row(chunk_id: str, text: str, vector: list[float], **over) -> dict:
    row = dict(
        chunk_id=chunk_id, doc_id=f"d-{chunk_id}", text=text,
        section_path=["Aviation"], page=1, bbox=None,
        source_anchor='{"page": 1}', agency_canonical_ids=["adot"],
        fund_canonical_id="fund:aviation", fund_mentions=["aviation-fund"],
        fiscal_year=2027, doc_type="baseline-per-agency", is_table=False,
        table_html=None, token_count=6, publisher="jlbc", vector=vector,
    )
    row.update(over)
    return row


def test_retrieve_end_to_end_over_a_real_store(tmp_path):
    """The only test that runs retrieve() through a REAL ChunkStore and the
    REAL Lance search legs — everything else in this file monkeypatches both
    legs, and test_search_lance.py exercises the legs but never goes through
    retrieve(). Without this, a signature/kwarg mismatch between the pipeline
    and the store (wrong `where=`, a renamed score column, a filter that
    silently matches nothing) would pass the whole unit suite.

    dim=4 hand-made vectors and fake models keep it fast — no ONNX, no
    downloads.
    """
    from store.chunk_store import ChunkStore as RealChunkStore

    store = RealChunkStore(root=tmp_path, dim=4)
    store.upsert_chunks("budget_chunks", [
        _row("c1", "aviation fund balance by agency", [1, 0, 0, 0]),
        _row("c2", "child safety caseworkers", [0, 1, 0, 0],
             publisher="agao", fiscal_year=2025),
        _row("c3", "aviation revenues", [0, 0, 1, 0]),
    ])
    store.build_fts_index("budget_chunks")

    # Query vector points exactly at c1.
    result = retrieve(
        RetrievalRequest(query="aviation fund balance", top_k=2),
        store=store,
        embedder=FakeEmbedder(vector=[1.0, 0.0, 0.0, 0.0]),
        reranker=FakeReranker(),  # preserves fused order
    )

    ids = [c.chunk_id for c in result.chunks]
    assert ids[0] == "c1", f"expected c1 to win both legs, got {ids}"
    assert len(result.chunks) == 2  # top_k respected
    # Real rows round-tripped: the JSON source_anchor was decoded and the
    # denormalized publisher survived.
    assert result.chunks[0].source_anchor == {"page": 1}
    assert result.chunks[0].publisher == "jlbc"
    assert result.chunks[0].fund_mentions == ["aviation-fund"]
    # Counts reflect real search behavior, not fakes.
    assert result.bm25_count >= 1
    assert result.dense_count == 3  # unfiltered ANN sees every row
    assert result.fused_count >= 2
    assert result.top_score == result.chunks[0].score


def test_retrieve_filters_narrow_a_real_store(tmp_path):
    """A filter must reach BOTH real legs through the store's SQL builder —
    the prefiltered-FTS and prefiltered-ANN code paths are different inside
    LanceDB, so a filter honored by only one would leak chunks via RRF."""
    from store.chunk_store import ChunkStore as RealChunkStore

    store = RealChunkStore(root=tmp_path, dim=4)
    store.upsert_chunks("budget_chunks", [
        _row("c1", "aviation fund balance", [1, 0, 0, 0]),
        _row("c2", "aviation fund balance", [1, 0, 0, 0],
             publisher="agao", fiscal_year=2025),
    ])
    store.build_fts_index("budget_chunks")

    result = retrieve(
        RetrievalRequest(query="aviation fund balance", publisher=["agao"]),
        store=store,
        embedder=FakeEmbedder(vector=[1.0, 0.0, 0.0, 0.0]),
        reranker=FakeReranker(),
    )
    assert [c.chunk_id for c in result.chunks] == ["c2"]
    assert all(c.publisher == "agao" for c in result.chunks)


def test_over_filtered_real_store_returns_the_no_results_sentinel(tmp_path):
    """The production path to the sentinel: a real store, a real query, and a
    filter that legitimately matches nothing."""
    from store.chunk_store import ChunkStore as RealChunkStore

    store = RealChunkStore(root=tmp_path, dim=4)
    store.upsert_chunks("budget_chunks", [
        _row("c1", "aviation fund balance", [1, 0, 0, 0]),
    ])
    store.build_fts_index("budget_chunks")

    result = retrieve(
        RetrievalRequest(query="aviation fund balance", fiscal_year=[1999]),
        store=store,
        embedder=FakeEmbedder(vector=[1.0, 0.0, 0.0, 0.0]),
        # No reranker: nothing survives the filter, so it must never be built.
    )
    assert result.chunks == []
    assert result.fused_count == 0
    assert result.top_score == NO_RESULTS_TOP_SCORE


# ---------------------------------------------------------------------------
# S21 layer 1 — explicit query years become a hard fiscal-year filter
# ---------------------------------------------------------------------------


def test_a_year_named_in_the_query_becomes_a_fiscal_year_filter(seams):
    """The filter carries the named year's neighbours too — a passage about
    FY 2019 routinely lives in a document stamped FY 2018 or FY 2020 (see
    ADJACENT_YEAR_WINDOW). The echo reports only what the analyst named."""
    result = _run(RetrievalRequest(query="fy2019 DES funding"))

    assert seams.bm25_calls[0]["filters"].fiscal_year == [2018, 2019, 2020]
    assert seams.dense_calls[0]["filters"].fiscal_year == [2018, 2019, 2020]
    assert result.inferred_fiscal_years == [2019]


def test_an_explicit_caller_filter_always_beats_the_parser(seams):
    """The parser is a convenience for humans typing prose. A caller that
    passed fiscal_year meant it — silently widening or narrowing that would
    make the MCP-era `filters` argument unreliable."""
    result = _run(
        RetrievalRequest(query="fy2019 DES funding", fiscal_year=[2027])
    )

    assert seams.bm25_calls[0]["filters"].fiscal_year == [2027]
    assert seams.dense_calls[0]["filters"].fiscal_year == [2027]
    # Nothing was inferred *and applied*, so nothing is echoed — the field
    # reports what the pipeline did, not what the parser saw.
    assert result.inferred_fiscal_years == []


def test_a_query_with_no_year_gets_no_fiscal_year_filter(seams):
    result = _run(RetrievalRequest(query="DES caseworker funding"))

    assert seams.bm25_calls[0]["filters"].fiscal_year is None
    assert seams.dense_calls[0]["filters"].fiscal_year is None
    assert result.inferred_fiscal_years == []


def test_the_year_filter_applies_to_the_fiscal_note_corpus_too(seams):
    """S21 gives fiscal notes layer 1 (this filter) but NOT the layer-3
    recency boost — coordinator triage wants similar notes at any age, but
    a year the analyst typed is still a year they meant."""
    result = _run(
        RetrievalRequest(query="fy24 caseworker note", corpus="fiscal_note_chunks")
    )

    assert seams.bm25_calls[0]["filters"].fiscal_year == [2023, 2024, 2025]
    assert result.inferred_fiscal_years == [2024]


def test_injecting_the_inferred_year_preserves_the_other_filters(seams):
    _run(
        RetrievalRequest(
            query="fy2019 DES funding",
            publisher=["jlbc"],
            is_table=True,
        )
    )

    filters = seams.bm25_calls[0]["filters"]
    assert filters.fiscal_year == [2018, 2019, 2020]
    assert filters.publisher == ["jlbc"]
    assert filters.is_table is True


def test_inferred_years_are_echoed_even_when_the_filter_finds_nothing(
    monkeypatch,
):
    """The empty-fused early return is a separate construction site for
    RetrievalResult; it used to be the only place a new field could be
    silently dropped."""
    empty = Seams(bm25=[], dense=[])
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", empty.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", empty.dense)

    result = _run(RetrievalRequest(query="fy2019 nothing matches this"))

    assert result.chunks == []
    assert result.top_score == NO_RESULTS_TOP_SCORE
    assert result.inferred_fiscal_years == [2019]


def test_retrieval_result_defaults_inferred_years_to_empty():
    """Additive field — every existing construction site must keep working."""
    assert RetrievalResult().inferred_fiscal_years == []


# ---------------------------------------------------------------------------
# S21 layer 3 — post-rerank recency bonus (ships at weight 0.0)
# ---------------------------------------------------------------------------


def _dated(chunk_id: str, fiscal_year: int | None) -> RetrievedChunk:
    return replace(_chunk(chunk_id), fiscal_year=fiscal_year)


def _dated_seams(monkeypatch, chunks):
    s = Seams(bm25=list(chunks), dense=[])
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
    return s


def test_the_recency_bonus_is_off_at_the_shipped_weight(monkeypatch):
    """Every production retrieval runs through this call today, so a
    non-no-op default would silently reorder the whole corpus."""
    _dated_seams(monkeypatch, [_dated("old", 2019), _dated("new", 2027)])

    result = _run(
        RetrievalRequest(query="provider rate increase"),
        reranker=FakeReranker({"old": 5.0, "new": 4.0}),
    )

    assert [c.chunk_id for c in result.chunks] == ["old", "new"]
    assert result.reranker_scores == [5.0, 4.0]
    assert result.top_score == 5.0


def test_an_enabled_bonus_reorders_and_moves_top_score(monkeypatch):
    """top_score is what the refusal threshold compares against — pinned
    here so enabling the weight without recalibrating REFUSAL_THRESHOLD
    cannot happen quietly."""
    _dated_seams(monkeypatch, [_dated("old", 2019), _dated("new", 2027)])

    with recency_weight(0.4):
        result = _run(
            RetrievalRequest(query="provider rate increase"),
            reranker=FakeReranker({"old": 5.0, "new": 4.0}),
        )

    assert [c.chunk_id for c in result.chunks] == ["new", "old"]
    # old: 5.0 + 0.4 * (2019 - 2027) = 1.8; new: 4.0 + 0 = 4.0
    assert result.reranker_scores == pytest.approx([4.0, 1.8])
    assert result.top_score == pytest.approx(4.0)


def test_the_bonus_never_touches_the_fiscal_note_corpus(monkeypatch):
    """S21: coordinator triage deliberately seeks similar notes regardless
    of age. Layer 1 applies there; layer 3 must not."""
    _dated_seams(monkeypatch, [_dated("old", 2019), _dated("new", 2027)])

    with recency_weight(0.4):
        result = _run(
            RetrievalRequest(query="similar note", corpus="fiscal_note_chunks"),
            reranker=FakeReranker({"old": 5.0, "new": 4.0}),
        )

    assert [c.chunk_id for c in result.chunks] == ["old", "new"]
    assert result.reranker_scores == [5.0, 4.0]


def test_the_bonus_is_skipped_when_the_caller_filtered_by_year(monkeypatch):
    _dated_seams(monkeypatch, [_dated("old", 2019), _dated("new", 2027)])

    with recency_weight(0.4):
        result = _run(
            RetrievalRequest(query="provider rate increase", fiscal_year=[2019, 2027]),
            reranker=FakeReranker({"old": 5.0, "new": 4.0}),
        )

    assert [c.chunk_id for c in result.chunks] == ["old", "new"]


def test_the_bonus_is_skipped_when_the_query_named_a_year(monkeypatch):
    """The analyst asked for FY 2019. Demoting FY 2019 inside its own
    filtered result set would be fighting the instruction."""
    _dated_seams(monkeypatch, [_dated("old", 2019), _dated("new", 2020)])

    with recency_weight(0.4):
        result = _run(
            RetrievalRequest(query="fy2019 provider rate increase"),
            reranker=FakeReranker({"old": 5.0, "new": 4.0}),
        )

    assert result.inferred_fiscal_years == [2019]
    assert [c.chunk_id for c in result.chunks] == ["old", "new"]


def test_the_boost_can_reach_chunks_the_reranker_pushed_past_top_k(monkeypatch):
    """The reranker must not truncate before the recency pass. If it did,
    the newest edition — the one S21 exists to rescue — would already be
    gone from the list the boost operates on, and no weight could lift
    it. Pins the stage order, not the weight."""
    editions = [_dated(f"c-{fy}", fy) for fy in range(2018, 2028)]
    _dated_seams(monkeypatch, editions)
    # The reranker likes the OLDEST edition best, so FY2027 lands last.
    scores = {f"c-{fy}": 5.0 - 0.1 * (fy - 2018) for fy in range(2018, 2028)}

    with recency_weight(0.4):
        result = _run(
            RetrievalRequest(query="provider rate increase", top_k=3),
            reranker=FakeReranker(scores),
        )

    assert [c.chunk_id for c in result.chunks] == ["c-2027", "c-2026", "c-2025"]
    assert len(result.chunks) == 3


def test_the_final_list_is_still_trimmed_to_top_k(monkeypatch):
    _dated_seams(monkeypatch, [_dated(f"c{i}", 2027) for i in range(10)])

    result = _run(RetrievalRequest(query="anything", top_k=4))

    assert len(result.chunks) == 4
    assert len(result.reranker_scores) == 4
