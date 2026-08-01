"""Tests for the synthesizer. The Anthropic API call and DB connection
are mocked — these tests do NOT spend real API budget or require a
live corpus.

A separate end-to-end "smoke" run is performed in Task 4's Step 6 (one
real synthesis call to produce the initial eval/queries.yaml).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eval.synthesize_queries import (
    parse_lookup_response,
    sample_comparison_pairs,
    sample_lookup_chunks,
)


def test_parse_lookup_response_extracts_query_and_anchor():
    """Anthropic returns a JSON object inside the message content. The
    parser is lenient: accepts JSON wrapped in markdown code fences,
    trailing whitespace, etc."""
    raw = """```json
{
  "query": "What was AHCCCS's FY26 General Fund appropriation?",
  "anchor_text": "$2,587,400 from the General Fund"
}
```"""
    result = parse_lookup_response(raw)
    assert result["query"] == "What was AHCCCS's FY26 General Fund appropriation?"
    assert "2,587,400" in result["anchor_text"]


def test_parse_lookup_response_handles_bare_json():
    """Some Claude responses skip the markdown fences."""
    raw = '{"query": "Test?", "anchor_text": "fragment"}'
    result = parse_lookup_response(raw)
    assert result["query"] == "Test?"
    assert result["anchor_text"] == "fragment"


def test_parse_lookup_response_raises_on_malformed():
    """Malformed responses should fail loudly (not silently produce
    bad data)."""
    with pytest.raises(ValueError):
        parse_lookup_response("not json at all")


class FakeStore:
    """Stands in for store.chunk_store.ChunkStore.

    Only `scan()` is used by the synthesizer — it reads the whole corpus
    projection once and samples in Python, because LanceDB has no
    `ORDER BY RANDOM()` to push the sampling down into the query.
    """

    def __init__(self, rows):
        self._rows = rows
        self.scanned = []

    def scan(self, name, columns, *, where=None, limit=None):
        self.scanned.append((name, where))
        return [dict(r) for r in self._rows]


def _fake_rows(n=40, *, publishers=("jlbc", "agao", "governor", "legislature")):
    return [
        {
            "chunk_id": f"chunk-{i}",
            "text": f"Sample chunk {i} content.",
            "publisher": publishers[i % len(publishers)],
            "doc_type": "baseline-per-agency",
            "fiscal_year": 2026,
            "agency_canonical_ids": [f"agency:test-{i % 5}"],
            "token_count": 200,
        }
        for i in range(n)
    ]


def test_sample_lookup_chunks_balances_across_publishers():
    """The sampler should pull chunks balanced across publishers."""
    store = FakeStore(_fake_rows(40))

    chunks = sample_lookup_chunks(n=25, store=store)

    assert len(chunks) == 25
    # Confirm the diversity didn't all collapse to one publisher.
    publishers = {c["publisher"] for c in chunks}
    assert len(publishers) > 1


def test_sample_lookup_chunks_filters_degenerate_chunks():
    """token_count > 80 was a SQL WHERE clause against Postgres; on
    LanceDB it must still be applied, as a DataFusion predicate."""
    store = FakeStore(_fake_rows(10))

    sample_lookup_chunks(n=5, store=store)

    name, where = store.scanned[0]
    assert name == "budget_chunks"
    assert "token_count > 80" in where


def test_sample_lookup_chunks_reads_the_requested_corpus():
    """The fiscal-note eval set has no ground truth yet (STATUS), so the
    synthesizer has to be able to seed from that corpus too."""
    store = FakeStore(_fake_rows(10))

    sample_lookup_chunks(n=3, store=store, corpus="fiscal_note_chunks")

    assert store.scanned[0][0] == "fiscal_note_chunks"


def test_sample_lookup_chunks_never_returns_the_same_chunk_twice():
    """Sampling without replacement — a duplicated seed would produce two
    eval queries whose ground truth is the same chunk, which inflates
    recall for free."""
    store = FakeStore(_fake_rows(30))

    chunks = sample_lookup_chunks(n=30, store=store)

    assert len({c["chunk_id"] for c in chunks}) == len(chunks)


def test_sample_lookup_chunks_caps_at_corpus_size():
    """Asking for more than exists returns what exists, not an error."""
    store = FakeStore(_fake_rows(4))

    assert len(sample_lookup_chunks(n=25, store=store)) == 4


def test_sample_comparison_pairs_matches_agency_across_fiscal_years():
    """A pair must share an agency and a doc_type and differ in FY —
    that is what makes a comparison question answerable from both."""
    rows = [
        {
            "chunk_id": f"chunk-{fy}-{agency}",
            "text": f"FY {fy} text for {agency}.",
            "publisher": "jlbc",
            "doc_type": "baseline-per-agency",
            "fiscal_year": fy,
            "agency_canonical_ids": [agency],
            "token_count": 200,
        }
        for agency in ("agency:adc", "agency:ahccs")
        for fy in (2024, 2025, 2026)
    ]
    store = FakeStore(rows)

    pairs = sample_comparison_pairs(n=2, store=store)

    assert len(pairs) == 2
    for a, b in pairs:
        assert a["agency_canonical_ids"] == b["agency_canonical_ids"]
        assert a["doc_type"] == b["doc_type"]
        # Ordered oldest-first, mirroring the old SQL's b.fiscal_year >
        # a.fiscal_year, so the generated question reads forward in time.
        assert a["fiscal_year"] < b["fiscal_year"]


def test_sample_comparison_pairs_skips_agencies_with_only_one_year():
    """No second year means no comparison — that agency contributes
    nothing rather than pairing against an unrelated one."""
    rows = [
        {
            "chunk_id": "only-one",
            "text": "single year",
            "publisher": "jlbc",
            "doc_type": "baseline-per-agency",
            "fiscal_year": 2026,
            "agency_canonical_ids": ["agency:lonely"],
            "token_count": 200,
        }
    ]
    store = FakeStore(rows)

    assert sample_comparison_pairs(n=5, store=store) == []


def test_sample_comparison_pairs_ignores_unstamped_chunks():
    """ARRAY_LENGTH(agency_canonical_ids, 1) >= 1 in the old SQL. A chunk
    with no agency can't anchor a same-agency comparison."""
    rows = [
        {
            "chunk_id": f"unstamped-{fy}",
            "text": "no agency",
            "publisher": "jlbc",
            "doc_type": "baseline-per-agency",
            "fiscal_year": fy,
            "agency_canonical_ids": [],
            "token_count": 200,
        }
        for fy in (2025, 2026)
    ]
    store = FakeStore(rows)

    assert sample_comparison_pairs(n=5, store=store) == []


def test_synthesize_lookup_query_calls_anthropic(monkeypatch):
    """The lookup synthesizer should:
    1. Call the Anthropic SDK with the chunk text in the prompt.
    2. Parse the JSON response.
    3. Return an EvalQuery with expected_chunks pointing at the seed
       chunk.
    """
    from eval.synthesize_queries import synthesize_lookup_query

    seed_chunk = {
        "chunk_id": "fy26-jlbc-baseline-ahccs::3",
        "text": "The FY 2026 General Fund appropriation for AHCCCS was $2,587,400.",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2026,
        "agency_canonical_ids": ["agency:ahccs"],
    }

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='{"query": "What was AHCCCS\'s FY26 appropriation?", "anchor_text": "$2,587,400"}'
            )
        ]
    )

    query = synthesize_lookup_query(seed_chunk, mock_client, q_id="q-001")

    assert query.id == "q-001"
    assert query.type == "lookup"
    assert query.expected_refusal is False
    assert len(query.expected_chunks) == 1
    ec = query.expected_chunks[0]
    assert ec.chunk_id == "fy26-jlbc-baseline-ahccs::3"
    assert ec.dimensions.publisher == "jlbc"
    assert ec.dimensions.fiscal_year == 2026
    assert ec.dimensions.agency == "agency:ahccs"
    assert ec.anchor_text == "$2,587,400"
    # Anthropic API was called once with the chunk text in the prompt.
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "$2,587,400" in prompt_text  # chunk text reached the prompt


def test_synthesize_comparison_query():
    """Comparison query takes a chunk PAIR and produces one query
    with two expected_chunks."""
    from eval.synthesize_queries import synthesize_comparison_query

    chunk_a = {
        "chunk_id": "fy24-jlbc-baseline-adc::3",
        "text": "FY 2024 ADC appropriation was $1.5B from the General Fund.",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2024,
        "agency_canonical_ids": ["agency:adc"],
    }
    chunk_b = {
        "chunk_id": "fy26-jlbc-baseline-adc::3",
        "text": "FY 2026 ADC appropriation was $1.7B from the General Fund.",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2026,
        "agency_canonical_ids": ["agency:adc"],
    }

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='{"query": "How did ADC appropriations change FY24 to FY26?", "anchor_text_a": "$1.5B", "anchor_text_b": "$1.7B"}'
            )
        ]
    )

    query = synthesize_comparison_query(
        chunk_a, chunk_b, mock_client, q_id="q-026"
    )

    assert query.type == "comparison"
    assert query.expected_refusal is False
    assert len(query.expected_chunks) == 2
    assert query.expected_chunks[0].chunk_id == chunk_a["chunk_id"]
    assert query.expected_chunks[1].chunk_id == chunk_b["chunk_id"]
    assert query.expected_chunks[0].dimensions.fiscal_year == 2024
    assert query.expected_chunks[1].dimensions.fiscal_year == 2026


def test_synthesize_refusal_query():
    """Refusal query has no seed chunk; Claude generates an out-of-
    scope question independently."""
    from eval.synthesize_queries import synthesize_refusal_query

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='{"query": "What is the right tax policy for Arizona?"}'
            )
        ]
    )

    query = synthesize_refusal_query(mock_client, q_id="q-031")

    assert query.type == "refusal"
    assert query.expected_refusal is True
    assert query.expected_chunks == []
    assert "tax policy" in query.query.lower()
