"""Judge tests — model traffic mocked with httpx.MockTransport; the
judge's arithmetic (claim-coverage precision) is computed in OUR code
from the judge's claim list, never trusted from the model."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from eval import judge_agent_run
from eval.agent_schema import AgentQuery
from eval.agent_transcript import Transcript, read_transcript
from eval.judge_agent_run import (
    build_judge_payload,
    compute_citation_scores,
    judge_one,
    main,
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


# ---- Finding 1 (final review): the headline metric must be bounded ----
# The numerator counts CLAIMS, the old denominator counted CITATIONS, so
# nothing tied them together and the ratio could exceed 1.0 — which made
# the metric's gradient point at emitting FEWER citations, the exact
# behavior it exists to punish.

def _claims(covered: int, uncovered: int = 0) -> dict:
    return {"load_bearing_claims":
            [{"claim": f"covered-{i}", "cited_verified": True} for i in range(covered)]
            + [{"claim": f"missed-{i}", "cited_verified": False} for i in range(uncovered)]}


def test_one_citation_covering_three_claims_is_bounded_at_one():
    """THE regression case: 1 citation issued, 3 load-bearing claims all
    covered by it. This returned 3.0 before the fix. One table row backing
    a three-figure comparison is the modal budget answer, so an unbounded
    score here rewarded citing less."""
    t = _transcript_with_citations(1)
    scores = compute_citation_scores(_claims(covered=3), t)
    assert scores["claim_coverage_precision"] == 1.0
    assert scores["claim_coverage_recall"] == 1.0


def test_claim_coverage_precision_never_exceeds_one():
    """Property, not a single case: for every mix of citations issued and
    covered claims, precision stays within 0..1."""
    for emitted in range(0, 6):
        for covered in range(0, 6):
            scores = compute_citation_scores(_claims(covered=covered),
                                             _transcript_with_citations(emitted))
            p = scores["claim_coverage_precision"]
            assert p is None or 0.0 <= p <= 1.0, (emitted, covered, p)


def test_padding_citations_still_lowers_precision():
    """The other side of the bound: issuing 5 citations to back 1 covered
    claim is padding and must still be punished."""
    t = _transcript_with_citations(5)
    scores = compute_citation_scores(_claims(covered=1), t)
    assert scores["claim_coverage_precision"] == 0.2


def test_three_claims_cited_three_times_scores_the_same_as_cited_once():
    """Before the fix these two shapes scored 1.0 and 3.0 — the same
    answer, graded three times better for citing less."""
    once = compute_citation_scores(_claims(covered=3), _transcript_with_citations(1))
    thrice = compute_citation_scores(_claims(covered=3), _transcript_with_citations(3))
    assert once["claim_coverage_precision"] == thrice["claim_coverage_precision"] == 1.0


def test_covered_claims_with_zero_citations_is_still_not_applicable():
    """A judge contradiction (claims marked covered when no citation was
    issued) must not become a perfect 1.0 via the new max() denominator.
    No citations issued = 'not applicable', as before."""
    scores = compute_citation_scores(_claims(covered=3), _transcript_with_citations(0))
    assert scores["claim_coverage_precision"] is None


# ---- Finding 2 (final review): a malformed `holistic` must not bin the run ----

def test_numeric_string_holistic_is_read_as_the_number():
    """`"holistic": "4"` has exactly one honest reading. It used to reach
    sum() in main()'s mean() and raise TypeError after every row had been
    paid for."""
    reply = json.dumps({"load_bearing_claims": [], "holistic": "4"})
    assert parse_judge_json(reply)["holistic"] == 4


def test_ungradable_holistic_becomes_none_and_keeps_the_raw_value():
    """`"4/5"` has no single honest numeric reading, so it is recorded as
    ungradable (None, which mean() skips) rather than guessed at — and the
    row's claim list, which may be perfectly good, survives."""
    reply = json.dumps({
        "load_bearing_claims": [{"claim": "x", "cited_verified": True}],
        "holistic": "4/5"})
    parsed = parse_judge_json(reply)
    assert parsed["holistic"] is None
    assert parsed["holistic_raw"] == "4/5"
    assert parsed["load_bearing_claims"][0]["cited_verified"] is True


@pytest.mark.parametrize("bad", [True, 0, 47, "high", ["4"], {"score": 4}, float("nan")])
def test_holistic_values_that_are_not_a_one_to_five_grade_are_rejected(bad):
    """Every one of these would either crash the mean or silently skew it.
    True is here because bool is an int subclass and would grade as 1."""
    parsed = parse_judge_json(json.dumps({"load_bearing_claims": [], "holistic": bad}))
    assert parsed["holistic"] is None


def test_valid_holistic_grades_pass_through_unchanged():
    for good in (1, 3, 5, 4.5):
        parsed = parse_judge_json(json.dumps({"load_bearing_claims": [], "holistic": good}))
        assert parsed["holistic"] == good
        assert "holistic_raw" not in parsed


def test_judge_prompt_template_shows_a_valid_json_holistic_value():
    """Prompt and parser must not drift: the template used to show
    `"holistic": 1-5`, which is not valid JSON and invited the "4"/"4/5"
    replies this suite now guards against."""
    prompt = judge_agent_run.PROMPT_PATH.read_text(encoding="utf-8")
    assert '"holistic": 1-5' not in prompt
    # the shown example value must itself parse as a 1-5 grade
    shown = prompt.split('"holistic":')[1].split(",")[0].strip()
    assert parse_judge_json(json.dumps(
        {"load_bearing_claims": [], "holistic": json.loads(shown)}))["holistic"] is not None


# ---- Finding 2, end to end: the run still writes what it paid for ------

class _FakeSettings:
    provider = SimpleNamespace(api_key="sk-test", base_url="https://judge.test/api/v1")


def _run_main(tmp_path, monkeypatch, reply_content: str) -> dict:
    """Drive main() over one transcript with the model call mocked.
    httpx.Client is patched to hand back a MockTransport client, so this
    can never make a real network call."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy(FIXTURE, run_dir / "aq-001-r1.jsonl")
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n"
        "  question: What was ADC's FY 2025 General Fund appropriation?\n"
        "  shape: lookup\n", encoding="utf-8")

    def handler(request):
        return httpx.Response(200, json={"choices": [{"message": {"content": reply_content}}]})

    real_client = httpx.Client  # capture BEFORE patching, or the lambda recurses
    monkeypatch.setattr(judge_agent_run.httpx, "Client",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(judge_agent_run, "load_settings", lambda: _FakeSettings())
    monkeypatch.setattr(sys, "argv",
                        ["judge", str(run_dir), "--queries-file", str(queries_file)])
    assert main() == 0
    return json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))


def test_main_writes_results_when_a_holistic_grade_is_malformed(tmp_path, monkeypatch):
    """The whole point of Finding 2: a `"holistic": "4/5"` reply used to
    raise TypeError in the summary mean AFTER the loop and BEFORE
    judge.json was written, losing every already-paid grade in the run."""
    out = _run_main(tmp_path, monkeypatch, json.dumps({
        "load_bearing_claims": [{"claim": "ADC got $1,391,157,700", "cited_verified": True}],
        "holistic": "4/5"}))
    assert out["summary"]["n"] == 1
    assert out["summary"]["errors"] == 0          # the row is graded, not binned
    assert out["summary"]["holistic_mean"] is None  # ungradable, so excluded
    row = out["per_query"][0]
    assert row["holistic_raw"] == "4/5"
    # the citation scores we paid for are intact and bounded
    assert row["claim_coverage_precision"] == 1.0


def test_main_writes_judge_json_atomically_with_the_prompt_hash(tmp_path, monkeypatch):
    """Preserved guarantees: the prompt sha256 rides in the output and no
    .tmp file is left behind by the atomic write."""
    out = _run_main(tmp_path, monkeypatch, json.dumps(JUDGE_REPLY))
    assert len(out["judge_prompt_sha256"]) == 64
    assert out["summary"]["holistic_mean"] == 4
    assert list((tmp_path / "run").glob("*.tmp")) == []


def test_main_survives_a_row_that_raises_outside_the_model_call(tmp_path, monkeypatch):
    """judge_one() swallows failures of the model CALL, but the code around
    it (reading a transcript, building the payload, scoring) can still
    raise — and judge.json is written once, after the loop. One bad row
    must cost one row, not every already-paid grade in the run."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy(FIXTURE, run_dir / "aq-001-r1.jsonl")
    shutil.copy(FIXTURE, run_dir / "aq-001-r2.jsonl")
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text("- id: aq-001\n  question: q1\n  shape: lookup\n",
                            encoding="utf-8")

    real_build = judge_agent_run.build_judge_payload
    calls = []

    def exploding_build(query, t):
        calls.append(1)
        if len(calls) == 1:  # first row blows up, second must still be graded
            raise RuntimeError("boom")
        return real_build(query, t)

    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(JUDGE_REPLY)}}]})

    real_client = httpx.Client
    monkeypatch.setattr(judge_agent_run, "build_judge_payload", exploding_build)
    monkeypatch.setattr(judge_agent_run.httpx, "Client",
                        lambda *a, **k: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(judge_agent_run, "load_settings", lambda: _FakeSettings())
    monkeypatch.setattr(sys, "argv",
                        ["judge", str(run_dir), "--queries-file", str(queries_file)])
    assert main() == 0
    out = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))
    assert out["summary"]["n"] == 2
    assert out["summary"]["errors"] == 1
    # the healthy row kept its grade, and the summary means skip the error row
    assert any(r.get("holistic") == 4 for r in out["per_query"])
    assert out["summary"]["claim_coverage_precision_mean"] == 1.0


def test_reasoning_model_that_returns_null_content_gives_a_clear_error():
    """Observed live 2026-08-02 with deepseek-v4-flash-0731: a reasoning
    model spends its completion budget thinking, hits finish_reason
    "length", and returns content: null. The judge crashed with
    AttributeError: 'NoneType' has no attribute 'strip' — a message that
    tells the operator nothing about what actually went wrong, on 5 of 31
    queries in a paid run.
    """
    def handler(request):
        return httpx.Response(200, json={"choices": [
            {"finish_reason": "length",
             "message": {"content": None, "reasoning": "thinking..."}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = judge_one(client, "https://x.test/api/v1", "sk-x", "m", "sys", {"q": 1})
    assert "judge_error" in result
    assert "no content" in result["judge_error"].lower()


def test_request_sets_max_tokens_so_a_reasoning_model_can_finish():
    """Without max_tokens a reasoning model is cut off mid-thought and
    never emits its answer. The budget must leave room for reasoning AND
    the JSON that follows it."""
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [
            {"message": {"content": json.dumps(JUDGE_REPLY)}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge_one(client, "https://x.test/api/v1", "sk-x", "m", "sys", {"q": 1})
    assert seen["max_tokens"] >= 4000


def test_reasoning_can_be_disabled_for_speed():
    """A structured grading task does not always need chain-of-thought.
    Disabling it measured 15x faster and 2.75x cheaper on the same query."""
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [
            {"message": {"content": json.dumps(JUDGE_REPLY)}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge_one(client, "https://x.test/api/v1", "sk-x", "m", "sys", {"q": 1},
              reasoning=False)
    assert seen["reasoning"] == {"enabled": False}


def test_reasoning_is_left_alone_by_default():
    """Most models have no reasoning control; sending the field to them
    is an unnecessary compatibility risk."""
    seen = {}

    def handler(request):
        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"choices": [
            {"message": {"content": json.dumps(JUDGE_REPLY)}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    judge_one(client, "https://x.test/api/v1", "sk-x", "m", "sys", {"q": 1})
    assert "reasoning" not in seen
