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


def test_sample_lookup_chunks_balances_across_publishers(monkeypatch):
    """The sampler should pull chunks balanced across publishers."""

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeConn:
        def execute(self, sql, params=None):
            # Return 25 fake chunks; mix of publishers.
            rows = []
            for i in range(25):
                rows.append(
                    {
                        "chunk_id": f"chunk-{i}",
                        "text": f"Sample chunk {i} content.",
                        "publisher": ["jlbc", "agao", "governor", "legislature"][
                            i % 4
                        ],
                        "doc_type": "baseline-per-agency",
                        "fiscal_year": 2026,
                        "agency_canonical_ids": [f"agency:test-{i % 5}"],
                    }
                )
            return FakeCursor(rows)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.synthesize_queries as syn

    monkeypatch.setattr(syn, "get_connection", lambda: FakeConn())

    chunks = sample_lookup_chunks(n=25)
    assert len(chunks) == 25
    # Confirm the diversity didn't all collapse to one publisher.
    publishers = {c["publisher"] for c in chunks}
    assert len(publishers) > 1


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
