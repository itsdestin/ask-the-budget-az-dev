"""Mechanical scorer tests over synthetic transcripts.

Each metric gets a transcript engineered to pin it. The golden fixture
(tests/fixtures/agent_transcript_sample.jsonl) pins the happy path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.agent_schema import AgentQuery, KeyFact
from eval.agent_scoring import aggregate, cite_attempts, score_transcript
from eval.agent_transcript import Transcript, read_transcript

FIXTURE = Path(__file__).parent / "fixtures" / "agent_transcript_sample.jsonl"


def make_query(**kw):
    defaults = dict(id="aq-001", question="ADC FY2025?", shape="lookup",
                    key_facts=[KeyFact(kind="currency", value="$1,391,157,700")])
    defaults.update(kw)
    return AgentQuery(**defaults)


def retrieve_call(chunks, tool_use_id="t-r"):
    return {"toolUseId": tool_use_id, "toolName": "retrieve", "input": {"query": "x"},
            "output": json.dumps({"top_score": 4.0, "retrieval_id": "r",
                                  "bm25_count": 1, "dense_count": 1, "fused_count": 1,
                                  "chunks": chunks}),
            "isError": False}


def chunk(cid, text):
    return {"chunk_id": cid, "doc_id": "d", "doc_title": "T", "publisher": "jlbc",
            "fiscal_year": 2025, "doc_type": "afr", "section_path": "", "page_start": 1,
            "page_end": 1, "bbox": None, "text": text, "text_length": len(text), "score": 4.0}


def cite_call(ok=True, error=None, quote="$1,391,157,700"):
    out = {"ok": ok}
    if error:
        out["error"] = error
    return {"toolUseId": "t-c", "toolName": "cite",
            "input": {"chunk_id": "c-1", "quote": quote, "confidence": "verbatim",
                      "claim_span": "claim"},
            "output": json.dumps(out), "isError": not ok}


def make_transcript(tool_calls, final="ADC received $1,391,157,700.",
                    citations=None, steps=2):
    frame = {"type": "_done", "stopReason": "end_turn", "finalAnswer": final,
             "incompleteNote": None, "citations": citations or [],
             "retrievedChunkIds": [], "toolCalls": tool_calls,
             "usage": {"inputTokens": 1000, "outputTokens": 100,
                       "cacheReadTokens": 400, "cacheCreationTokens": 0, "cost": 0.005}}
    events = [{"type": "assistant_thinking", "uuid": f"u{i}"} for i in range(steps)]
    return Transcript(meta={"query_id": "aq-001", "repeat": 1},
                      events=events, terminal={"frame": frame, "wall_ms": 30000})


def ok_citation(cid="c-1", quote="$1,391,157,700"):
    return {"chunkId": cid, "claimSpan": "claim", "confidence": "verbatim",
            "quote": quote, "spanStart": 0, "spanEnd": 10, "citationId": "x",
            "ok": True, "error": None}


def test_golden_fixture_scores_clean():
    t = read_transcript(FIXTURE)
    row = score_transcript(make_query(), t)
    assert row["ok"] is True
    assert row["key_fact_rate"] == 1.0
    assert row["steps"] == 1
    assert row["retrieve_call_count"] == 1
    assert row["verified_citations"] == 1
    assert row["first_attempt_cite_rate"] == 1.0
    assert row["cost_usd"] == pytest.approx(0.0031)
    assert row["cached_tokens"] == 700


def test_key_fact_miss_detected():
    t = make_transcript([retrieve_call([chunk("c-1", "irrelevant")])],
                        final="ADC received $999.")
    row = score_transcript(make_query(), t)
    assert row["key_fact_rate"] == 0.0


def test_retrieval_efficiency_counts_used_chunks():
    calls = [retrieve_call([chunk("c-1", "ADC $1,391,157,700 appears here"),
                            chunk("c-2", "unrelated text"),
                            chunk("c-3", "also unrelated")])]
    t = make_transcript(calls, citations=[ok_citation("c-1")])
    row = score_transcript(make_query(), t)
    # c-1 cited + fact-bearing; c-2/c-3 never used -> 1/3
    assert row["retrieval_efficiency"] == pytest.approx(1 / 3)


def test_retrieves_after_sufficient():
    fact_chunk = chunk("c-1", "the answer $1,391,157,700 is here")
    calls = [retrieve_call([fact_chunk], "t-1"),
             retrieve_call([chunk("c-2", "noise")], "t-2"),
             retrieve_call([chunk("c-3", "noise")], "t-3")]
    t = make_transcript(calls, citations=[ok_citation("c-1")])
    row = score_transcript(make_query(), t)
    assert row["retrieves_after_sufficient"] == 2


def test_cite_attempt_mechanics_including_batch():
    batch = {"toolUseId": "t-b", "toolName": "cite_batch",
             "input": {"citations": [
                 {"chunk_id": "c-1", "quote": "q1", "confidence": "verbatim", "claim_span": "a"},
                 {"chunk_id": "c-1", "quote": "q2", "confidence": "verbatim", "claim_span": "b"}]},
             "output": json.dumps({"citations": [
                 {"ok": True, "citation_id": "x"},
                 {"ok": False, "error": "quote appears multiple times in chunk.text (positions: 1, 5)"}]}),
             "isError": False}
    t = make_transcript([cite_call(ok=False, error="quote not found in chunk.text — ..."),
                         cite_call(ok=True), batch],
                        citations=[ok_citation()])
    attempts = cite_attempts(t)
    assert len(attempts) == 4
    row = score_transcript(make_query(), t)
    assert row["cite_attempts"] == 4
    assert row["cite_failures"] == 2
    assert row["first_attempt_cite_rate"] == pytest.approx(0.5)
    assert row["ambiguity_rejections"] == 1


def test_quote_narrowness_median():
    cites = [ok_citation(quote="short"), ok_citation(quote="a" * 101)]
    t = make_transcript([], citations=cites)
    row = score_transcript(make_query(), t)
    assert row["median_quote_len"] == pytest.approx((5 + 101) / 2)


def test_refusal_query_scoring():
    rq = make_query(id="aq-r", shape="refusal", should_refuse=True, key_facts=[])
    refused = make_transcript([], final="I can't answer that from this corpus.")
    assert score_transcript(rq, refused)["refusal_correct"] is True
    answered = make_transcript([], citations=[ok_citation()])
    assert score_transcript(rq, answered)["refusal_correct"] is False


def test_hygiene_flags():
    t = make_transcript([], final="Let me search the corpus. The chunk_id shows token: Abc123_defGHI456 leaked.")
    row = score_transcript(make_query(key_facts=[]), t)
    assert row["narration_hits"] >= 1
    assert row["token_leak"] is True
    assert row["internal_vocab_hits"] >= 1


def test_error_terminal_scores_as_failure():
    t = Transcript(meta={"query_id": "aq-001", "repeat": 1}, events=[],
                   terminal={"frame": {"type": "_error", "message": "boom"}, "wall_ms": 5})
    row = score_transcript(make_query(), t)
    assert row["ok"] is False and row["error"] == "boom"


def test_aggregate_summary():
    rows = [score_transcript(make_query(), read_transcript(FIXTURE))]
    summary = aggregate(rows)
    assert summary["n"] == 1
    assert summary["key_fact_rate_mean"] == 1.0
    assert summary["first_attempt_cite_rate"] == 1.0
    assert summary["total_cost_usd"] == pytest.approx(0.0031)


def test_score_run_cli_writes_outputs(tmp_path):
    import shutil
    from eval.score_agent_run import score_run
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy(FIXTURE, run_dir / "aq-001-r1.jsonl")
    qfile = tmp_path / "queries.yaml"
    qfile.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n"
        "  key_facts:\n    - kind: currency\n      value: \"$1,391,157,700\"\n",
        encoding="utf-8")
    scores = score_run(run_dir, str(qfile))
    assert scores["summary"]["n"] == 1
    assert scores["per_query"][0]["ok"] is True
