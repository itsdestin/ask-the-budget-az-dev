"""Judge tests — model traffic mocked with httpx.MockTransport; the
judge's arithmetic (claim-coverage precision) is computed in OUR code
from the judge's claim list, never trusted from the model."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from eval.agent_schema import AgentQuery
from eval.agent_transcript import read_transcript
from eval.judge_agent_run import (
    build_judge_payload,
    compute_citation_scores,
    judge_one,
    parse_judge_json,
)

FIXTURE = Path(__file__).parent / "fixtures" / "agent_transcript_sample.jsonl"

JUDGE_REPLY = {
    "load_bearing_claims": [
        {"claim": "ADC FY2025 GF appropriation was $1,391,157,700", "cited_verified": True},
        {"claim": "the appropriation grew year over year", "cited_verified": False},
    ],
    "holistic": 4,
    "flags": {"hedging": False, "meta_narration": False, "answered_wrong_question": False},
    "rationale": "Correct figure, one uncited trend claim.",
}


# DEVIATION from the task brief: the brief's test imports `make_query` from
# `tests.test_eval_agent_score_run`, a sibling test module being written
# concurrently by another agent in a different worktree/branch. It does not
# exist here, so `make_query` is defined locally to keep this suite
# self-contained (see task-6-report.md for the full note).
def make_query(**overrides) -> AgentQuery:
    defaults = dict(
        id="aq-001",
        question="What was ADC's FY 2025 General Fund appropriation?",
        shape="lookup",
        judge_notes="Look for the ADC agency line in the FY 2025 Approps Report.",
    )
    defaults.update(overrides)
    return AgentQuery.model_validate(defaults)


def test_build_judge_payload_carries_cited_chunk_texts():
    t = read_transcript(FIXTURE)
    payload = build_judge_payload(make_query(), t)
    assert payload["question"]
    assert payload["final_answer"] == "ADC received $1,391,157,700."
    assert payload["citations"][0]["ok"] is True
    # the cited chunk's text rides along so the judge can check support
    assert "c-1" in payload["cited_chunks"]
    assert "$1,391,157,700" in payload["cited_chunks"]["c-1"]


def test_parse_judge_json_strips_code_fences():
    fenced = "```json\n" + json.dumps(JUDGE_REPLY) + "\n```"
    assert parse_judge_json(fenced)["holistic"] == 4
    assert parse_judge_json(json.dumps(JUDGE_REPLY))["holistic"] == 4
    with pytest.raises(ValueError):
        parse_judge_json("I think the answer is fine.")


def test_compute_citation_scores():
    t = read_transcript(FIXTURE)  # 1 verified citation emitted
    scores = compute_citation_scores(JUDGE_REPLY, t)
    # precision: claims cited+verified (1) / citations issued (1)
    assert scores["claim_coverage_precision"] == 1.0
    # recall: claims cited+verified (1) / load-bearing claims (2)
    assert scores["claim_coverage_recall"] == 0.5


def test_judge_one_round_trip():
    def handler(request):
        body = json.loads(request.content)
        assert body["temperature"] == 0
        assert body["model"] == "judge/model"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(JUDGE_REPLY)}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = judge_one(client, "https://openrouter.test/api/v1", "sk-x",
                       "judge/model", "system", {"question": "q"})
    assert result["holistic"] == 4


def test_judge_one_malformed_reply_becomes_error_not_crash():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "not json at all"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = judge_one(client, "https://openrouter.test/api/v1", "sk-x",
                       "judge/model", "system", {"question": "q"})
    assert "judge_error" in result
