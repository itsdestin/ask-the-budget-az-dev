"""Query-understanding wiring in retrieval/pipeline.py (spec Q2, Q3).

Written in the house pipeline-test style (see tests/test_pipeline.py): the two
Lance search legs are monkeypatched and the embedder/reranker are injected, so
nothing here opens a LanceDB directory or loads ONNX weights.

WHY not drive the real corpus, which is what the plan's draft of this file did:
a unit test that needs a 4.7 GB corpus and ~150 MB of model weights cannot run
on a fresh clone, and the thing it would actually be asserting — that "doc
baseline" returns Corrections documents — is a RETRIEVAL QUALITY question, not
a wiring question. Quality belongs in eval/queries.yaml, where it is measured
against a baseline. What is tested here is the mechanism: which filter reaches
the search legs, whose filter wins, and what happens when a guess empties the
page.
"""
from __future__ import annotations

from dataclasses import replace

import pytest

from retrieval.pipeline import RetrievalRequest, retrieve
from retrieval.types import RetrievedChunk


def _chunk(chunk_id: str, *, score: float = 1.0) -> RetrievedChunk:
    """Minimal valid RetrievedChunk — same helper shape as tests/test_pipeline.py."""
    return RetrievedChunk(
        chunk_id=chunk_id,
        doc_id=f"doc-{chunk_id}",
        text=f"text of {chunk_id}",
        score=score,
        section_path=["Section"],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=["agency:adc"],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=42,
        publisher="jlbc",
    )


class FakeEmbedder:
    def embed_one(self, text: str, *, input_type: str = "document") -> list[float]:
        return [0.1, 0.2, 0.3]


class FakeReranker:
    def rerank(self, query, chunks, *, top_k):
        return list(chunks)[:top_k]


class RecordingSeams:
    """Records the filters each search leg was called with.

    `results_per_call` lets a test make the FIRST search come back empty and a
    later one come back full, which is the only way to exercise the
    filter-yielded-nothing retry without a real corpus.
    """

    def __init__(self, results_per_call: list[list[RetrievedChunk]]) -> None:
        self.results_per_call = results_per_call
        self.filters_seen: list = []
        self._round = 0

    def _hits(self) -> list[RetrievedChunk]:
        idx = min(self._round, len(self.results_per_call) - 1)
        return list(self.results_per_call[idx])

    def bm25(self, query, *, store, corpus, top_k, filters):
        self.filters_seen.append(filters)
        return self._hits()

    def dense(self, query_vector, *, store, corpus, top_k, filters):
        # The dense leg is called once per search round, right after bm25, so
        # advancing the round counter here keeps the pair in step.
        hits = self._hits()
        self._round += 1
        return hits

    @property
    def rounds(self) -> int:
        """How many times the pipeline ran a search — 2 means it retried."""
        return len(self.filters_seen)


@pytest.fixture()
def seam_factory(monkeypatch):
    def install(results_per_call):
        s = RecordingSeams(results_per_call)
        monkeypatch.setattr("retrieval.pipeline.bm25_query_lance", s.bm25)
        monkeypatch.setattr("retrieval.pipeline.dense_query_lance", s.dense)
        return s

    return install


def _run(req: RetrievalRequest):
    return retrieve(
        req,
        store=object(),
        embedder=FakeEmbedder(),
        reranker=FakeReranker(),
    )


# --------------------------------------------------------------------------
# Inference becomes a filter
# --------------------------------------------------------------------------


def test_an_exact_agency_becomes_a_PREFERENCE_not_a_filter(seam_factory):
    """Deviation from spec Q2, measured: a hard agency filter cost 4.8 points
    of recall at every cutoff and lost two queries outright, because the corpus
    is stamped incompletely and a CORRECT reading can still exclude the answer.
    See the reasoning at the inference site in retrieval/pipeline.py."""
    seams = seam_factory([[_chunk("c1")]])
    res = _run(RetrievalRequest(query="corrections baseline", top_k=8))
    assert res.inferred_agencies == ["agency:adc"]
    # Reported so the UI can say "preferring Corrections" — but nothing was
    # removed from the search.
    assert seams.filters_seen[0].agency_canonical_id is None


def test_an_exact_doc_type_becomes_a_hard_filter(seam_factory):
    seams = seam_factory([[_chunk("c1")]])
    res = _run(RetrievalRequest(query="ahcccs appropriations report", top_k=8))
    assert res.inferred_doc_types == ["approps-per-agency"]
    assert seams.filters_seen[0].doc_type == ["approps-per-agency"]


def test_no_agency_match_of_any_confidence_reaches_the_filter(seam_factory):
    """'doc' is an ordinary English word as well as the Corrections acronym.
    It must not empty the page for someone asking about documents — and now
    neither may an EXACT match."""
    seams = seam_factory([[_chunk("c1")]])
    res = _run(RetrievalRequest(query="doc baseline", top_k=8))
    assert res.inferred_agencies == ["agency:adc"]
    assert seams.filters_seen[0].agency_canonical_id is None


def test_a_query_naming_nothing_infers_nothing(seam_factory):
    seams = seam_factory([[_chunk("c1")]])
    res = _run(RetrievalRequest(query="what changed since last year", top_k=8))
    assert res.inferred_agencies == []
    assert res.inferred_doc_types == []
    assert res.dropped_filters == []
    assert seams.filters_seen[0].agency_canonical_id is None


# --------------------------------------------------------------------------
# The caller always outranks the parser
# --------------------------------------------------------------------------


def test_a_callers_explicit_agency_filter_wins(seam_factory):
    """Same precedence the year parser already has: an explicit filter means
    the caller decided, and inference must not override it."""
    seams = seam_factory([[_chunk("c1")]])
    res = _run(
        RetrievalRequest(
            query="corrections baseline",
            agency_canonical_id=["agency:ade"],
            top_k=5,
        )
    )
    assert res.inferred_agencies == []
    assert seams.filters_seen[0].agency_canonical_id == ["agency:ade"]


def test_a_callers_explicit_doc_type_filter_wins(seam_factory):
    seams = seam_factory([[_chunk("c1")]])
    res = _run(
        RetrievalRequest(
            query="ahcccs appropriations report", doc_type=["afr"], top_k=5
        )
    )
    assert res.inferred_doc_types == []
    assert seams.filters_seen[0].doc_type == ["afr"]


# --------------------------------------------------------------------------
# A guess that empties the page is retried (spec Q3 — non-negotiable)
# --------------------------------------------------------------------------


def test_a_hard_filter_that_matches_nothing_retries_unfiltered(seam_factory):
    """An analyst must never get a blank page because the parser was
    confidently wrong.

    'ahcccs budget bill' is the real case, verified against the live corpus on
    2026-08-02: agency:axs has 4,258 chunks and budget-bill has plenty, but
    their INTERSECTION is exactly zero.
    """
    seams = seam_factory([[], [_chunk("c1")]])
    res = _run(RetrievalRequest(query="ahcccs budget bill", top_k=5))

    assert seams.rounds == 2, "the pipeline should have searched a second time"
    assert res.chunks != []
    # Only doc_type is ever droppable — agency is a preference and so can
    # never be the thing that emptied the page.
    assert res.dropped_filters == ["doc_type"]
    # The retry must not carry the guess that emptied the page.
    assert seams.filters_seen[1].doc_type is None


def test_a_dropped_filter_is_not_also_reported_as_applied(seam_factory):
    """`inferred_agencies` means inferred AND APPLIED — the same meaning
    `inferred_fiscal_years` already carries. Reporting a filter as applied
    when it was dropped would make the UI lie in the other direction."""
    seam_factory([[], [_chunk("c1")]])
    res = _run(RetrievalRequest(query="ahcccs budget bill", top_k=5))
    assert res.inferred_doc_types == []


def test_only_inferred_filters_are_droppable(seam_factory):
    """A caller's explicit filter is never silently discarded — it was an
    instruction, not a guess, and dropping it would answer a different
    question than the one asked."""
    seams = seam_factory([[], [_chunk("c1")]])
    res = _run(
        RetrievalRequest(
            query="ahcccs budget bill",
            agency_canonical_id=["agency:axs"],
            top_k=5,
        )
    )
    assert "agency" not in res.dropped_filters
    for seen in seams.filters_seen:
        assert seen.agency_canonical_id == ["agency:axs"]
    # A caller's explicit filter also suppresses the inference entirely.
    assert res.inferred_agencies == []


def test_no_retry_happens_when_nothing_was_inferred(seam_factory):
    """An empty result with no guess to blame is a genuine empty result.
    Searching twice for it would double the cost of every zero-hit query."""
    seams = seam_factory([[]])
    res = _run(RetrievalRequest(query="what changed since last year", top_k=5))
    assert seams.rounds == 1
    assert res.chunks == []
    assert res.dropped_filters == []


def test_a_successful_first_search_never_retries(seam_factory):
    seams = seam_factory([[_chunk("c1")]])
    res = _run(RetrievalRequest(query="corrections baseline", top_k=5))
    assert seams.rounds == 1
    assert res.dropped_filters == []


# --------------------------------------------------------------------------
# The existing year path is unchanged
# --------------------------------------------------------------------------


def test_year_inference_still_works_alongside_agency_inference(seam_factory):
    seams = seam_factory([[_chunk("c1")]])
    res = _run(RetrievalRequest(query="corrections baseline fy2026", top_k=5))
    assert res.inferred_fiscal_years == [2026]
    assert res.inferred_agencies == ["agency:adc"]
    assert seams.filters_seen[0].fiscal_year is not None
