"""Mechanical scorer tests over synthetic transcripts.

Each metric gets a transcript engineered to pin it. The golden fixture
(tests/fixtures/agent_transcript_sample.jsonl) pins the happy path.
"""
from __future__ import annotations

import json
import sys
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
    assert row["cite_pass_rate"] == 1.0
    assert row["first_try_cite_rate"] == 1.0
    assert row["retries_per_citation"] == 0.0
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
    assert row["cite_pass_rate"] == pytest.approx(0.5)
    assert row["ambiguity_rejections"] == 1
    # Finding 5: the pass rate above is over ALL attempts. The three DISTINCT
    # citation targets here are (c-1, "claim") — attempted twice, failing then
    # passing, i.e. one retry — plus the batch's (c-1, "a") and (c-1, "b").
    # Only (c-1, "a") passed on its first attempt.
    assert row["cite_targets"] == 3
    assert row["cite_retries"] == 1
    assert row["retries_per_citation"] == pytest.approx(1 / 3)
    assert row["first_try_cite_rate"] == pytest.approx(1 / 3)


def test_first_try_rate_diverges_from_pass_rate_when_a_cite_is_retried():
    """Finding 5, stated as the divergence that made the old name wrong: a
    claim that failed once and passed on the retry is a 50% pass rate over
    attempts but a 0% FIRST-TRY rate. The old single metric reported 0.5 under
    the name `first_attempt_cite_rate`."""
    t = make_transcript([cite_call(ok=False, error="quote not found"), cite_call(ok=True)],
                        citations=[ok_citation()])
    row = score_transcript(make_query(), t)
    assert row["cite_pass_rate"] == pytest.approx(0.5)
    assert row["first_try_cite_rate"] == 0.0
    assert row["retries_per_citation"] == 1.0


def test_batch_siblings_on_one_chunk_are_not_counted_as_retries():
    """Two claims cited against the SAME chunk in one cite_batch are two
    intended citations, not a retry of each other — grouping on chunk_id
    alone would have called the second one a retry."""
    batch = {"toolUseId": "t-b", "toolName": "cite_batch",
             "input": {"citations": [
                 {"chunk_id": "c-1", "quote": "q1", "confidence": "verbatim", "claim_span": "a"},
                 {"chunk_id": "c-1", "quote": "q2", "confidence": "verbatim", "claim_span": "b"}]},
             "output": json.dumps({"citations": [{"ok": True}, {"ok": True}]}),
             "isError": False}
    row = score_transcript(make_query(), make_transcript([batch]))
    assert row["cite_targets"] == 2
    assert row["cite_retries"] == 0
    assert row["first_try_cite_rate"] == 1.0


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
    assert summary["cite_pass_rate"] == 1.0
    assert summary["first_try_cite_rate"] == 1.0
    assert summary["total_cost_usd"] == pytest.approx(0.0031)
    assert summary["cost_missing_queries"] == 0


def test_errored_transcript_gives_no_refusal_credit():
    # Finding 1: a crashed query (_error terminal) has zero verified
    # citations BY CONSTRUCTION, which used to be indistinguishable from a
    # genuine correct refusal. It must not contribute to refusal_correct at
    # the row level, and it must not enter refusal_correct_rate in aggregate.
    rq = make_query(id="aq-r", shape="refusal", should_refuse=True, key_facts=[])
    errored = Transcript(meta={"query_id": "aq-r", "repeat": 1}, events=[],
                         terminal={"frame": {"type": "_error", "message": "boom"},
                                   "wall_ms": 5})
    row = score_transcript(rq, errored)
    assert row["ok"] is False
    assert row["refusal_correct"] is None
    summary = aggregate([row])
    assert summary["refusal_correct_rate"] is None


def test_false_refusal_none_for_errored_transcript():
    # An errored non-refusal query must not be flagged false_refusal either --
    # it never ran, so there is nothing to judge.
    q = make_query(should_refuse=False, key_facts=[])
    errored = Transcript(meta={"query_id": "aq-001", "repeat": 1}, events=[],
                         terminal={"frame": {"type": "_error", "message": "boom"},
                                   "wall_ms": 5})
    row = score_transcript(q, errored)
    assert row["false_refusal"] is None


def test_retrieval_efficiency_bare_name_match_is_not_evidence():
    # Finding 2 reproduction: 5 retrieved chunks that only mention an agency
    # name in passing (kind="string" key fact), 1 actually cited. The old
    # definition counted every chunk containing the name as "used" -> 1.0.
    # The honest number is 1/5 = 0.2: a bare name match is not evidence.
    q = make_query(key_facts=[KeyFact(kind="string", value="Department of Corrections")])
    chunks = [chunk(f"c-{i}", "the department of corrections runs several programs")
              for i in range(5)]
    t = make_transcript([retrieve_call(chunks)], citations=[ok_citation("c-0")],
                        final="The department of corrections received funding.")
    row = score_transcript(q, t)
    assert row["retrieval_efficiency"] == pytest.approx(0.2)


def test_retrieval_efficiency_specific_fact_in_answer_counts_as_weak_evidence():
    # A currency key fact that appears both in an uncited chunk and in the
    # final answer is the defensible weaker signal described in Finding 2 --
    # it still counts as "used" even without a citation.
    q = make_query(key_facts=[KeyFact(kind="currency", value="$1,391,157,700")])
    chunks = [chunk("c-1", "ADC received $1,391,157,700 this year"),
             chunk("c-2", "totally unrelated text")]
    t = make_transcript([retrieve_call(chunks)], citations=[],
                        final="ADC received $1,391,157,700.")
    row = score_transcript(q, t)
    assert row["retrieval_efficiency"] == pytest.approx(0.5)


def test_false_refusal_detected_with_no_key_facts():
    # Finding 3: a non-refusal query authored with zero key facts (the
    # memo/comparison/analyze shapes that lean on the LLM judge) used to make
    # an incorrect refusal invisible everywhere in this scorer. It must now
    # be flagged when the agent issues zero verified citations.
    q = make_query(should_refuse=False, key_facts=[])
    refused = make_transcript([], final="I can't answer that from this corpus.")
    row = score_transcript(q, refused)
    assert row["false_refusal"] is True


def test_false_refusal_not_flagged_when_citations_were_issued_and_no_key_facts():
    q = make_query(should_refuse=False, key_facts=[])
    answered = make_transcript([], citations=[ok_citation()])
    row = score_transcript(q, answered)
    assert row["false_refusal"] is False


def test_internal_vocab_bare_rerank_word_does_not_flag_policy_prose():
    # Finding 5: "rerank" alone is ordinary English in budget policy prose,
    # so it must not trip the internal-vocab hygiene check.
    t = make_transcript([], final="The legislature chose to rerank funding priorities this year.")
    row = score_transcript(make_query(key_facts=[]), t)
    assert row["internal_vocab_hits"] == 0


def test_scores_md_cost_column_has_enough_precision(tmp_path):
    # Finding 4: real Standard-tier per-query costs run ~$0.002-$0.013, so
    # the old 2-decimal formatting rendered every one as "0.00" -- useless
    # for the exact comparison this column exists to support.
    import shutil
    from eval.score_agent_run import main

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy(FIXTURE, run_dir / "aq-001-r1.jsonl")
    qfile = tmp_path / "queries.yaml"
    qfile.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n"
        "  key_facts:\n    - kind: currency\n      value: \"$1,391,157,700\"\n",
        encoding="utf-8")
    argv = sys.argv
    sys.argv = ["score_agent_run.py", str(run_dir), "--queries-file", str(qfile)]
    try:
        main()
    finally:
        sys.argv = argv
    md = (run_dir / "scores.md").read_text(encoding="utf-8")
    assert "0.0031" in md
    assert "| 0.00 |" not in md


def test_retrieves_after_sufficient_population_is_reported(tmp_path):
    """Finding 4: the mean is taken over only the queries whose retrieved text
    ever contained every key fact, so the population is decided by the run's
    own success. A reader must be able to SEE that the denominator moved."""
    fact_chunk = chunk("c-1", "the answer $1,391,157,700 is here")
    found = score_transcript(make_query(), make_transcript(
        [retrieve_call([fact_chunk], "t-1"), retrieve_call([chunk("c-2", "noise")], "t-2")]))
    never_found = score_transcript(make_query(id="aq-002"), make_transcript(
        [retrieve_call([chunk("c-9", "nothing useful")], "t-9")]))

    assert found["retrieves_after_sufficient"] == 1
    assert never_found["retrieves_after_sufficient"] is None
    # Both queries were ELIGIBLE (key facts + at least one retrieve); only one
    # contributed. That gap is what the compare tool needs to see.
    assert found["retrieves_after_sufficient_eligible"] is True
    assert never_found["retrieves_after_sufficient_eligible"] is True

    summary = aggregate([found, never_found])
    assert summary["retrieves_after_sufficient_mean"] == 1.0
    assert summary["retrieves_after_sufficient_n"] == 1
    # Summary-side name is deliberately NOT "retrieves_after_sufficient_eligible"
    # (fix batch, Finding 2) -- that string is already a per-query BOOL two
    # lines up; reusing it here for an INT count is the type collision the
    # rename fixes.
    assert summary["retrieves_after_sufficient_eligible_queries"] == 2


def test_filter_and_corpus_parameter_usage_counted():
    """Finding 5: spec goal 3 promises 'filter/corpus-parameter usage counts'
    and the data was sitting unread in toolCalls[].input.filters."""
    filtered = {"toolUseId": "t-1", "toolName": "retrieve",
                "input": {"query": "ADC", "intent": "lookup", "top_k": 5,
                          "filters": {"fiscal_year": [2026], "agency_canonical_id": ["agency:adc"]}},
                "output": json.dumps({"chunks": [chunk("c-1", "x")]}), "isError": False}
    bare = {"toolUseId": "t-2", "toolName": "retrieve", "input": {"query": "ADC again"},
            "output": json.dumps({"chunks": [chunk("c-2", "y")]}), "isError": False}
    row = score_transcript(make_query(), make_transcript([filtered, bare]))
    assert row["retrieve_calls_with_filters"] == 1
    assert row["filter_dimension_counts"]["fiscal_year"] == 1
    assert row["filter_dimension_counts"]["agency_canonical_id"] == 1
    assert row["filter_dimension_counts"]["publisher"] == 0
    assert row["retrieve_calls_with_intent"] == 1
    assert row["retrieve_calls_with_top_k"] == 1
    assert row["deep_dive_calls"] == 0

    summary = aggregate([row])
    assert summary["retrieve_calls_with_filters"] == 1
    assert summary["filtered_retrieve_rate"] == pytest.approx(0.5)
    assert summary["filter_dimension_counts"]["fiscal_year"] == 1


def test_an_empty_filters_object_is_not_a_filtered_search():
    call = {"toolUseId": "t-1", "toolName": "retrieve",
            "input": {"query": "ADC", "filters": {}},
            "output": json.dumps({"chunks": []}), "isError": False}
    row = score_transcript(make_query(), make_transcript([call]))
    assert row["retrieve_calls_with_filters"] == 0


def test_crashed_query_makes_its_missing_cost_visible():
    """Finding 6: an `_error` frame carries no usage at all, so a query that
    crashed after N paid steps contributes $0 to total_cost_usd no matter how
    the rows are summed. The count is what stops the total from reading as
    complete."""
    ok = score_transcript(make_query(), read_transcript(FIXTURE))
    crashed = score_transcript(make_query(id="aq-002"), Transcript(
        meta={"query_id": "aq-002", "repeat": 1}, events=[],
        terminal={"frame": {"type": "_error", "message": "boom"}, "wall_ms": 5}))
    summary = aggregate([ok, crashed])
    assert summary["total_cost_usd"] == pytest.approx(0.0031)
    assert summary["cost_missing_queries"] == 1


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


def test_a_malformed_cite_batch_slot_scores_as_a_failure_instead_of_crashing():
    """Observed live, 2026-08-02 (an-esa-growth, first full baseline): the
    model emitted cite_batch with `citations` holding STRINGS — fragments of
    a double-encoded JSON payload — instead of objects. The tool layer
    handled it and returned per-slot errors, but the scorer crashed with
    AttributeError, taking down the whole run's scoring after the money had
    already been spent. A malformed slot is a real cite attempt that failed;
    it must count as one, not abort scoring.
    """
    batch = {"toolUseId": "t-b", "toolName": "cite_batch",
             "input": {"citations": [
                 '[{"chunk_id": "c-1"',          # the live shape: a bare string
                 {"chunk_id": "c-1", "quote": "q", "confidence": "verbatim",
                  "claim_span": "a"},
             ]},
             "output": json.dumps({"citations": [
                 {"ok": False, "error": "citations[0] must be an object"},
                 {"ok": True, "citation_id": "x"}]}),
             "isError": False}
    t = make_transcript([batch], citations=[ok_citation()])

    attempts = cite_attempts(t)
    assert len(attempts) == 2

    row = score_transcript(make_query(), t)
    assert row["cite_attempts"] == 2
    assert row["cite_failures"] == 1
    assert row["cite_pass_rate"] == pytest.approx(0.5)


def test_wall_clock_is_not_reported_anywhere():
    # Two transcripts with wildly different wall times (30000 baked into the
    # fake; vary via terminal). Summary must carry NO wall keys.
    t1 = make_transcript([retrieve_call([chunk("c-1", "ADC $1,391,157,700")])],
                         citations=[ok_citation("c-1")])
    row1 = score_transcript(make_query(), t1)
    s = aggregate([row1])
    assert "wall_p50_ms" not in s and "wall_p95_ms" not in s
    # per-query rows keep the forensic stamp
    assert row1["wall_ms"] == 30000
