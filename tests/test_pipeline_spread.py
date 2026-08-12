"""Spec N4/N5 — `retrieve_spread`, the structural fix for edition monoculture.

Same discipline as test_pipeline.py: the two Lance legs are monkeypatched at
the `retrieval.pipeline` seam, the embedder and reranker are injected fakes,
and nothing here opens a LanceDB directory or loads ONNX weights.

The four properties worth stating out loud, because each was a review finding
against the first draft of the design:

* the penalty runs BEFORE the per-group trim (an adjustment can only reorder
  chunks it can see);
* recency NEVER runs (an anchor-relative pass would depress an old group by
  more than the whole logit range and read as "FY2010 has nothing");
* no year/doc-type INFERENCE runs (the groups are the instruction);
* an empty group is REPORTED, never dropped.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from retrieval import RetrievalRequest
from retrieval.pipeline import NO_RESULTS_TOP_SCORE, SpreadSpec, retrieve_spread
from tests.test_pipeline import FakeEmbedder, FakeReranker, _chunk


def _year_chunk(cid: str, fy: int, score: float = 1.0):
    return replace(_chunk(cid, score=score), fiscal_year=fy)


class SpreadSeams:
    """Legs that answer per-filter, so each group sees its own slice."""

    def __init__(self, by_year: dict[int, list]) -> None:
        self.by_year = by_year
        self.bm25_calls: list = []
        self.dense_calls: list = []

    def bm25(self, query, *, store, corpus, top_k, filters):
        self.bm25_calls.append(filters)
        key = (filters.fiscal_year or [None])[0]
        return list(self.by_year.get(key, []))

    def dense(self, query_vector, *, store, corpus, top_k, filters):
        self.dense_calls.append(filters)
        return []


# Scores kept explicit so the fake reranker preserves the leg's ordering
# instead of substituting its positional default.
_YEAR_SCORES = {
    "a-2025": 3.0, "b-2025": 2.0, "c-2025": 1.5, "d-2025": 1.0, "a-2026": 2.5,
}


@pytest.fixture
def year_seams(monkeypatch):
    s = SpreadSeams({
        2025: [_year_chunk("a-2025", 2025, 3.0), _year_chunk("b-2025", 2025, 2.0),
               _year_chunk("c-2025", 2025, 1.5), _year_chunk("d-2025", 2025, 1.0)],
        2026: [_year_chunk("a-2026", 2026, 2.5)],
        2020: [],
    })
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
    return s


def _spread(**kw) -> SpreadSpec:
    return SpreadSpec(**{"by": "fiscal_year", "groups": (2025, 2026, 2020),
                         "per_group": 2, **kw})


# A query that names no agency and no doc type, so the match PENALTY stays
# out of the arithmetic unless a test asks for it. Worth stating: an earlier
# draft used "ahcccs" here and every score came back 2.0 lower — the penalty
# firing on a real acronym, working exactly as designed.
def _run(query="q", spread=None, **kw):
    return retrieve_spread(
        RetrievalRequest(query=query),
        spread if spread is not None else _spread(),
        embedder=kw.pop("embedder", FakeEmbedder()),
        reranker=kw.pop("reranker", FakeReranker(_YEAR_SCORES)),
        **kw,
    )


# ---------------------------------------------------------------------------
# Grouping
# ---------------------------------------------------------------------------


def test_groups_come_back_in_request_order_with_counts(year_seams):
    result = _run()
    assert [g["value"] for g in result.spread_groups] == [2025, 2026, 2020]
    assert [g["count"] for g in result.spread_groups] == [2, 1, 0]
    # An empty group is VISIBLE — the model must be able to tell "FY2020
    # holds nothing" from "FY2020 was never searched".
    assert result.spread_groups[2]["top_score"] is None


def test_per_group_trim_caps_each_group(year_seams):
    result = _run(spread=_spread(per_group=2))
    assert len([c for c in result.chunks if c.fiscal_year == 2025]) == 2


def test_chunks_are_concatenated_in_request_group_order(year_seams):
    result = _run(spread=_spread(groups=(2026, 2025)))
    assert [c.fiscal_year for c in result.chunks] == [2026, 2025, 2025]


def test_each_group_is_score_descending(year_seams):
    result = _run()
    in_2025 = [c.score for c in result.chunks if c.fiscal_year == 2025]
    assert in_2025 == sorted(in_2025, reverse=True)


def test_group_top_score_is_that_groups_best(year_seams):
    result = _run()
    by_value = {g["value"]: g["top_score"] for g in result.spread_groups}
    assert by_value[2025] == 3.0
    assert by_value[2026] == 2.5


# ---------------------------------------------------------------------------
# Cost: one embed, one rerank batch
# ---------------------------------------------------------------------------


def test_embed_happens_once_for_all_groups(year_seams):
    embedder = FakeEmbedder()
    _run(embedder=embedder)
    assert len(embedder.calls) == 1


def test_one_rerank_batch_over_every_groups_candidates(year_seams):
    reranker = FakeReranker(_YEAR_SCORES)
    _run(reranker=reranker)
    assert len(reranker.calls) == 1
    _query, seen_ids, _top_k = reranker.calls[0]
    assert set(seen_ids) == {"a-2025", "b-2025", "c-2025", "d-2025", "a-2026"}


def test_the_rerank_batch_is_not_pre_trimmed(year_seams):
    """`top_k` on the rerank call must cover the WHOLE candidate list: the
    penalty below it can only reorder chunks the reranker did not already
    slice away — the same lesson recorded at retrieve()'s rerank call."""
    reranker = FakeReranker(_YEAR_SCORES)
    _run(reranker=reranker)
    _query, seen_ids, top_k = reranker.calls[0]
    assert top_k == len(seen_ids)


# ---------------------------------------------------------------------------
# Ranking policy: penalty before trim, recency never
# ---------------------------------------------------------------------------


def test_recency_is_never_applied(year_seams, monkeypatch):
    """Spec review fix #3: a recency pass would skew cross-group top_scores
    by up to ~13.6 logits — larger than the whole +/-10 logit range — and
    report "FY2010 has nothing" where FY2010 holds a perfect hit."""
    def boom(*a, **kw):
        raise AssertionError("recency must not run on the spread path")

    monkeypatch.setattr("retrieval.pipeline.apply_recency_boost", boom)
    _run()


def test_penalty_runs_before_the_trim(year_seams, monkeypatch):
    """Spec review fix #2. Penalize the two leaders of FY2025; the trailing
    two must be able to win the trim. If the trim ran first they would never
    be candidates at all and the leaders would survive, penalty and all."""
    from retrieval import pipeline

    def penalize_leaders(chunks, *, agency_ids, doc_types, **kw):
        return sorted(
            (replace(c, score=c.score - (5.0 if c.chunk_id in ("a-2025", "b-2025") else 0.0))
             for c in chunks),
            key=lambda c: -c.score,
        )

    monkeypatch.setattr(pipeline, "apply_match_penalty", penalize_leaders)
    monkeypatch.setattr(
        pipeline, "parse_query_agencies",
        lambda q: [type("M", (), {"value": "agency:x"})()],
    )
    result = _run(spread=_spread(per_group=2))
    assert {c.chunk_id for c in result.chunks if c.fiscal_year == 2025} == \
        {"c-2025", "d-2025"}


def test_no_penalty_call_when_the_query_names_nothing(year_seams, monkeypatch):
    """The penalty is weight-bearing on `top_score`, which refusal is
    compared against; it must not fire on a query with no weak match."""
    from retrieval import pipeline

    calls = []
    monkeypatch.setattr(
        pipeline, "apply_match_penalty",
        lambda chunks, **kw: (calls.append(kw), chunks)[1],
    )
    monkeypatch.setattr(pipeline, "parse_query_agencies", lambda q: [])
    monkeypatch.setattr(pipeline, "parse_query_doc_types", lambda q: [])
    _run()
    assert calls == []


def test_spread_top_score_never_exceeds_the_best_single_group(year_seams):
    """The penalty-only invariant: nothing on this path may RAISE a score,
    because `top_score` is what REFUSAL_THRESHOLD is compared against."""
    result = _run()
    best_group = max(
        g["top_score"] for g in result.spread_groups if g["top_score"] is not None
    )
    assert result.top_score == best_group
    assert result.top_score == max(c.score for c in result.chunks)


# ---------------------------------------------------------------------------
# No inference: the groups are the instruction
# ---------------------------------------------------------------------------


def test_no_year_inference_on_spread(year_seams):
    """The query names FY2019; the groups say 2025/2026/2020. Groups win,
    and no year beyond the group's own may reach the legs."""
    _run(query="fy2019 budget")
    assert {tuple(f.fiscal_year or []) for f in year_seams.bm25_calls} == \
        {(2025,), (2026,), (2020,)}


def test_no_doc_type_hard_filter_inference_on_spread(year_seams, monkeypatch):
    """A doc-type guess that narrows the search is invisible to the caller
    and would silently shrink a group the model explicitly asked for."""
    from retrieval import pipeline

    monkeypatch.setattr(
        pipeline, "parse_query_doc_types",
        lambda q: [type("M", (), {"value": "afr", "exact": True})()],
    )
    monkeypatch.setattr(pipeline, "is_filterable", lambda matches: True)
    _run(query="afr")
    assert all(f.doc_type is None for f in year_seams.bm25_calls)


def test_caller_filters_still_reach_every_group(year_seams):
    """The caller's own filters are an instruction, not a guess — they must
    survive onto each group's legs alongside the group value."""
    retrieve_spread(
        RetrievalRequest(query="q", publisher=["jlbc"]),
        _spread(),
        embedder=FakeEmbedder(),
        reranker=FakeReranker(_YEAR_SCORES),
    )
    assert all(f.publisher == ["jlbc"] for f in year_seams.bm25_calls)


# ---------------------------------------------------------------------------
# The doc_id axis
# ---------------------------------------------------------------------------


def test_doc_id_axis_filters_and_partitions_by_doc_id(monkeypatch):
    by_doc = {
        "doc-1": [replace(_chunk("x1", score=2.0), doc_id="doc-1"),
                  replace(_chunk("x2", score=1.0), doc_id="doc-1")],
        "doc-2": [replace(_chunk("y1", score=1.5), doc_id="doc-2")],
    }

    seen: list = []

    def bm25(query, *, store, corpus, top_k, filters):
        seen.append(filters)
        return list(by_doc.get((filters.doc_id or [None])[0], []))

    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", bm25)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance",
                        lambda *a, **kw: [])
    result = retrieve_spread(
        RetrievalRequest(query="q"),
        SpreadSpec(by="doc_id", groups=("doc-1", "doc-2"), per_group=1),
        embedder=FakeEmbedder(),
        reranker=FakeReranker({"x1": 2.0, "x2": 1.0, "y1": 1.5}),
    )
    assert [f.doc_id for f in seen] == [["doc-1"], ["doc-2"]]
    assert [g["value"] for g in result.spread_groups] == ["doc-1", "doc-2"]
    assert [c.chunk_id for c in result.chunks] == ["x1", "y1"]


def test_doc_id_axis_keeps_yearless_chunks(monkeypatch):
    """Partitioning is by the AXIS attribute, never by fiscal_year — a
    document with no stamped year is still a document the model named."""
    chunk = replace(_chunk("n1", score=1.0), doc_id="doc-1", fiscal_year=None)
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance",
                        lambda *a, **kw: [chunk])
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance",
                        lambda *a, **kw: [])
    result = retrieve_spread(
        RetrievalRequest(query="q"),
        SpreadSpec(by="doc_id", groups=("doc-1",), per_group=3),
        embedder=FakeEmbedder(),
        reranker=FakeReranker({"n1": 1.0}),
    )
    assert [c.chunk_id for c in result.chunks] == ["n1"]
    assert result.spread_groups[0]["count"] == 1


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------


def test_all_groups_empty_returns_the_no_results_sentinel(monkeypatch):
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", lambda *a, **kw: [])
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", lambda *a, **kw: [])
    result = _run()
    assert result.chunks == []
    assert result.top_score == NO_RESULTS_TOP_SCORE
    assert [g["count"] for g in result.spread_groups] == [0, 0, 0]
    # Still one entry per REQUESTED group — an all-empty spread is an
    # answer ("the corpus holds nothing here"), not a missing result.
    assert [g["value"] for g in result.spread_groups] == [2025, 2026, 2020]


def test_empty_query_short_circuits_without_touching_a_model(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("must not search on an empty query")

    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", boom)
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", boom)
    result = retrieve_spread(
        RetrievalRequest(query="   "), _spread(),
        embedder=FakeEmbedder(), reranker=FakeReranker(),
    )
    assert result.chunks == []
    assert result.spread_groups == []


def test_no_groups_short_circuits(monkeypatch):
    def boom(*a, **kw):
        raise AssertionError("must not search with no groups")

    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", boom)
    result = retrieve_spread(
        RetrievalRequest(query="q"), SpreadSpec(by="fiscal_year", groups=()),
        embedder=FakeEmbedder(), reranker=FakeReranker(),
    )
    assert result.chunks == []


def test_the_reranker_is_never_built_when_nothing_matched(monkeypatch):
    """The expensive stage must not be constructed to score an empty list —
    the default path's own economy, kept here."""
    monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", lambda *a, **kw: [])
    monkeypatch.setattr("retrieval.pipeline.dense_query_lance", lambda *a, **kw: [])

    def boom():
        raise AssertionError("reranker must not be built")

    monkeypatch.setattr("retrieval.pipeline._get_reranker", boom)
    result = retrieve_spread(
        RetrievalRequest(query="q"), _spread(), embedder=FakeEmbedder()
    )
    assert result.chunks == []


def test_the_default_retrieve_path_gains_no_spread_groups(monkeypatch):
    """Spec N10: spread is opt-in and the default path is untouched."""
    from retrieval.pipeline import RetrievalResult

    assert RetrievalResult().spread_groups == []
