"""Judge tests — model traffic mocked with httpx.MockTransport; the
judge's arithmetic (claim-coverage precision) is computed in OUR code
from the judge's claim list, never trusted from the model."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from eval.agent_schema import AgentQuery
from eval.agent_transcript import Transcript, read_transcript
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


def _transcript_with_citations(n: int) -> Transcript:
    """A minimal Transcript carrying exactly `n` (dummy) citations —
    enough for compute_citation_scores(), which only reads citations(t)."""
    rows = [{"chunkId": f"c-{i}", "ok": True} for i in range(n)]
    return Transcript(meta={}, terminal={"frame": {"citations": rows}})


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


# ---- Finding 1: bare-string claims must not crash the run --------------

def test_parse_judge_json_rejects_bare_string_claims():
    """The prompt says "the claims that carry the answer" — a judge model
    can plausibly reply with claim strings instead of {claim,
    cited_verified} objects. That shape must fail validation here, not
    reach compute_citation_scores() where `.get()` on a string raises
    AttributeError."""
    bad = json.dumps({"load_bearing_claims": ["claim one", "claim two"], "holistic": 3})
    with pytest.raises(ValueError):
        parse_judge_json(bad)


def test_judge_one_bare_string_claims_becomes_judge_error_not_a_crash():
    """End-to-end through judge_one: a malformed reply must become one
    judge_error row, not an apparent success that main() later crashes on
    when it calls compute_citation_scores() outside any try/except."""
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(
                {"load_bearing_claims": ["just a claim string"], "holistic": 3}
            )}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = judge_one(client, "https://openrouter.test/api/v1", "sk-x",
                       "judge/model", "system", {"question": "q"})
    assert "judge_error" in result


def test_compute_citation_scores_tolerates_non_dict_claim_items():
    """Defense in depth: compute_citation_scores() is called directly by
    this test (and could be by future code) with unvalidated data — a
    non-dict claim item must be skipped, not crash the function."""
    t = read_transcript(FIXTURE)  # 1 citation emitted
    scores = compute_citation_scores({"load_bearing_claims": ["just a claim string"]}, t)
    assert scores["claim_coverage_precision"] == 0.0  # 1 emitted, 0 covered
    assert scores["claim_coverage_recall"] is None  # no valid claim objects to divide by


def test_compute_citation_scores_claim_missing_cited_verified_key():
    """A claim item that IS a dict, just missing the 'cited_verified' key
    entirely (not merely False) — must be treated as not-covered, never
    crash. This is the sibling case to the bare-string test: a shape
    that's malformed in a milder way and must degrade the same way."""
    t = read_transcript(FIXTURE)  # 1 citation emitted
    claims = [{"claim": "some claim"}]  # no "cited_verified" key at all
    scores = compute_citation_scores({"load_bearing_claims": claims}, t)
    assert scores["claim_coverage_precision"] == 0.0
    assert scores["claim_coverage_recall"] == 0.0


# ---- Finding 2: tolerate prose around the JSON, still reject non-JSON --

def test_parse_judge_json_tolerates_leading_prose():
    fenced = "Here's my answer:\n```json\n" + json.dumps(JUDGE_REPLY) + "\n```"
    assert parse_judge_json(fenced)["holistic"] == 4


def test_parse_judge_json_tolerates_trailing_prose():
    reply = json.dumps(JUDGE_REPLY) + "\n\nHope that helps!"
    assert parse_judge_json(reply)["holistic"] == 4


def test_parse_judge_json_bare_unfenced_object():
    # no fence at all, just the raw object — must still parse
    assert parse_judge_json(json.dumps(JUDGE_REPLY))["holistic"] == 4


def test_parse_judge_json_still_rejects_pure_prose():
    """The existing guarantee must survive: a reply with no JSON object
    anywhere is still rejected, not silently treated as an empty result."""
    with pytest.raises(ValueError):
        parse_judge_json("I think the answer is fine.")


# ---- Finding 3: None ("not applicable") vs 0.0 ("bad") is load-bearing -

def test_correct_refusal_scores_are_not_applicable_not_zero():
    """No citations issued, no load-bearing claims — the shape of a
    CORRECT refusal. Both scores must be None ('not applicable'), never
    0.0 ('bad'). A future edit collapsing this to 0.0 would pass every
    other test while quietly penalizing every correct refusal."""
    t = _transcript_with_citations(0)
    scores = compute_citation_scores({"load_bearing_claims": []}, t)
    assert scores["claim_coverage_precision"] is None
    assert scores["claim_coverage_recall"] is None


def test_citations_with_no_load_bearing_claims_is_bad_precision():
    """Citations were issued but the judge found no load-bearing claims —
    that's padding, and padding IS bad: precision must be 0.0, not None.
    Recall has no claims to divide by, so it stays None."""
    t = _transcript_with_citations(2)
    scores = compute_citation_scores({"load_bearing_claims": []}, t)
    assert scores["claim_coverage_precision"] == 0.0
    assert scores["claim_coverage_recall"] is None


def test_claims_present_but_nothing_cited():
    """Load-bearing claims exist but zero citations were issued. Recall
    must be 0.0 (real, countable misses); precision has no citations to
    divide by and must be None, not 0.0."""
    t = _transcript_with_citations(0)
    claims = [{"claim": "x", "cited_verified": False},
              {"claim": "y", "cited_verified": False}]
    scores = compute_citation_scores({"load_bearing_claims": claims}, t)
    assert scores["claim_coverage_precision"] is None
    assert scores["claim_coverage_recall"] == 0.0


# ---- Finding 5: missing chunk text must be explicit, not omitted -------

def test_build_judge_payload_marks_missing_chunk_text_as_none():
    """A citation can reference a chunk_id that was never returned by a
    retrieve() call in this transcript (a real, tracked gap — see
    STATUS.md's cross-turn citation-metadata issue). The payload must say
    so explicitly (None) instead of silently omitting the key, so the
    judge can tell 'no text to check' apart from 'the text doesn't
    support the quote'."""
    t = read_transcript(FIXTURE)
    t.terminal["frame"]["citations"].append(
        {"chunkId": "c-missing", "claimSpan": "x", "quote": "y", "ok": True}
    )
    payload = build_judge_payload(make_query(), t)
    assert payload["cited_chunks"]["c-missing"] is None
    # the chunk that WAS retrieved this transcript is unaffected
    assert "$1,391,157,700" in payload["cited_chunks"]["c-1"]
