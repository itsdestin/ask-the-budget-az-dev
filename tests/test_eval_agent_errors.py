"""Error-ledger mechanics. Fakes only — builders reused from
tests/test_eval_agent_score_run.py."""
import json

from eval.agent_errors import harvest_errors, summarize_errors
from eval.agent_schema import AgentQuery, KeyFact
from tests.test_eval_agent_score_run import (
    chunk, make_query, make_transcript, ok_citation, retrieve_call)

FACT = KeyFact(kind="string", value="total")
Q = AgentQuery(id="q1", question="q", set="quick", key_facts=[FACT], shape="lookup")


def test_cite_failures_are_harvested_with_their_turn():
    # one passing cite + one failing cite attempt
    from tests.test_eval_agent_score_run import cite_call
    calls = [retrieve_call([chunk("c-1", "total text")]),
             cite_call(ok=True), cite_call(ok=False, error="quote not found")]
    t = make_transcript(calls, citations=[ok_citation("c-1")])
    rows = harvest_errors(t, Q)
    fails = [r for r in rows if r["kind"] == "cite_failure"]
    assert len(fails) == 1
    assert fails[0]["query_id"] == "q1" and isinstance(fails[0]["turn"], int)


def test_retrieve_tool_error_is_harvested():
    bad_retrieve = {"toolUseId": "t-r", "toolName": "retrieve",
                    "input": {"query": "x"},
                    "output": json.dumps({"error": "unknown filter dimension"}),
                    "isError": True}
    t = make_transcript([bad_retrieve])
    errs = [r for r in harvest_errors(t, Q) if r["kind"] == "retrieve_error"]
    assert len(errs) == 1 and errs[0]["tool"] == "retrieve"


def test_crashed_query_is_one_error_row():
    # terminal frame is not _done (pattern: test_error_terminal_scores_as_failure)
    from eval.agent_transcript import Transcript
    t = Transcript(meta={"query_id": "q1", "repeat": 1}, events=[],
                   terminal={"frame": {"type": "_error", "message": "boom"},
                             "wall_ms": 1})
    rows = harvest_errors(t, Q)
    assert any(r["kind"] == "crashed_query" for r in rows)


def test_summarize_groups_by_kind():
    rows = [{"kind": "cite_failure", "query_id": "a", "turn": 3, "tool": "cite", "detail": ""},
            {"kind": "cite_failure", "query_id": "b", "turn": 1, "tool": "cite", "detail": ""},
            {"kind": "retrieve_error", "query_id": "a", "turn": 2, "tool": "retrieve", "detail": ""}]
    s = summarize_errors(rows)
    assert s["cite_failure"]["count"] == 2 and set(s["cite_failure"]["queries"]) == {"a", "b"}
    assert s["retrieve_error"]["count"] == 1
