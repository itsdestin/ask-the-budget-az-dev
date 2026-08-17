"""Tests for eval/defend_agent_run.py.

The "defend" mechanism takes a poorly-scored transcript's answer + the
evaluator's feedback and asks a fresh session to defend/revise it. These
tests cover the pure feedback-composition, target-selection and
question-building logic, plus a full run through a mock session factory
that never touches the network.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.agent_schema import AgentQuery
from eval.agent_transcript import final_answer, write_transcript
from eval import defend_agent_run as defend


def q(id="aq-001", **kw):
    defaults = dict(question="ADC FY2025 General Fund?", shape="lookup",
                    set="quick")  # Task 9: set has no default — supply one
    defaults.update(kw)
    return AgentQuery(id=id, **defaults)


def make_run(tmp_path, scoring, judge):
    """A run dir with one transcript + optional scores.json / judge.json."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    meta = {"query_id": "aq-001", "repeat": 1, "corpus": "budget",
            "tier": "standard", "shape": "lookup"}
    write_transcript(
        run_dir / "aq-001-r1.jsonl", meta, [],
        {"frame": {"type": "_done", "finalAnswer": "ADC got $1.4B.",
                   "citations": [], "toolCalls": [], "annotation": {"figures": []}},
         "wall_ms": 1})
    if scoring is not None:
        (run_dir / "scores.json").write_text(
            json.dumps({"per_query": [{"query_id": "aq-001", **scoring}]}),
            encoding="utf-8")
    if judge is not None:
        (run_dir / "judge.json").write_text(
            json.dumps({"per_query": [{"query_id": "aq-001", **judge}]}),
            encoding="utf-8")
    return run_dir


# ---------------------------------------------------------------------------
# Feedback composition
# ---------------------------------------------------------------------------


def test_brief_feedback_reports_missing_key_facts():
    fb = defend.brief_feedback(
        q(), scores={"key_facts_total": 2, "key_facts_matched": 1})
    assert "1 of 2" in fb
    assert "missing some key facts" in fb


def test_brief_feedback_reports_hygiene_and_token_leak():
    fb = defend.brief_feedback(
        q(), scores={"narration_hits": 1, "token_leak": True})
    assert "narration" in fb.lower()
    assert "download token" in fb


def test_brief_feedback_reports_judge_grade_and_uncovered_claims():
    fb = defend.brief_feedback(
        q(), judge={"holistic": 2, "rationale": "weak support",
                    "load_bearing_claims": [
                        {"claim": "ADC got $1.4B", "cited_verified": True},
                        {"claim": "ADC grew", "cited_verified": False}]})
    assert "2/5" in fb
    assert "weak support" in fb
    assert "ADC grew" in fb  # the uncovered claim is named


def test_brief_feedback_explicit_wins_over_composed():
    fb = defend.brief_feedback(
        q(), scores={"key_facts_total": 2, "key_facts_matched": 0},
        explicit="You cited the wrong fiscal year.")
    assert fb == "You cited the wrong fiscal year."


def test_brief_feedback_empty_has_neutral_default():
    fb = defend.brief_feedback(q())
    assert "defend the correctness" in fb


# ---------------------------------------------------------------------------
# Defense question building
# ---------------------------------------------------------------------------


def test_build_defense_query_carries_corpus_tier_and_empty_keyfacts():
    query = q(corpus="fiscal_notes", tier="standard")
    defense = defend.build_defense_query(query, "my old answer", "it was weak")
    assert defense.id == "aq-001-defend"
    assert defense.corpus == "fiscal_notes"
    assert defense.tier == "standard"
    assert defense.key_facts == []
    # The question must embed the original question, the answer, and the
    # feedback, and invite a defense or revision.
    assert "my old answer" in defense.question
    assert "it was weak" in defense.question
    assert "ADC FY2025 General Fund?" in defense.question
    assert "DEFEND or REVISE" in defense.question


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------


def test_select_targets_by_id(tmp_path):
    run_dir = make_run(tmp_path, None, None)
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n  set: quick\n", encoding="utf-8")
    picked = defend.select_targets(run_dir, str(queries_file),
                                   query_ids=["aq-001"], all_poorly=False)
    assert [x.id for x in picked] == ["aq-001"]


def test_select_targets_requires_a_selector(tmp_path, monkeypatch):
    run_dir = make_run(tmp_path, None, None)
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n  set: quick\n", encoding="utf-8")
    with pytest.raises(ValueError):
        defend.select_targets(run_dir, str(queries_file), query_ids=[],
                              all_poorly=False)


def test_select_targets_errors_on_unknown_id(tmp_path):
    run_dir = make_run(tmp_path, None, None)
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n  set: quick\n", encoding="utf-8")
    with pytest.raises(ValueError):
        defend.select_targets(run_dir, str(queries_file),
                              query_ids=["nosech-id"], all_poorly=False)


def test_select_targets_all_poorly_picks_weak_queries(tmp_path):
    # aq-001 weak on facts, aq-002 clean, aq-003 hygiene-flag.
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    for qid in ("aq-001", "aq-002", "aq-003"):
        write_transcript(
            run_dir / f"{qid}-r1.jsonl",
            {"query_id": qid, "repeat": 1, "corpus": "budget",
             "tier": "standard", "shape": "lookup"}, [],
            {"frame": {"type": "_done", "finalAnswer": "x",
                       "citations": [], "toolCalls": [],
                       "annotation": {"figures": []}}, "wall_ms": 1})
    (run_dir / "scores.json").write_text(json.dumps({"per_query": [
        {"query_id": "aq-001", "key_facts_total": 1, "key_facts_matched": 0,
         "key_fact_rate": 0.0, "narration_hits": 0, "token_leak": False,
         "false_refusal": False},
        {"query_id": "aq-002", "key_facts_total": 1, "key_facts_matched": 1,
         "key_fact_rate": 1.0, "narration_hits": 0, "token_leak": False,
         "false_refusal": False},
        {"query_id": "aq-003", "key_facts_total": 1, "key_facts_matched": 1,
         "key_fact_rate": 1.0, "narration_hits": 2, "token_leak": False,
         "false_refusal": False},
    ]}), encoding="utf-8")
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n  question: Q1?\n  shape: lookup\n  set: quick\n"
        "- id: aq-002\n  question: Q2?\n  shape: lookup\n  set: quick\n"
        "- id: aq-003\n  question: Q3?\n  shape: lookup\n  set: quick\n", encoding="utf-8")
    picked = defend.select_targets(run_dir, str(queries_file), query_ids=[],
                                   all_poorly=True)
    ids = [x.id for x in picked]
    assert ids == ["aq-001", "aq-003"]


# ---------------------------------------------------------------------------
# Feedback composition from a real source run + defense-driving
# ---------------------------------------------------------------------------


def test_build_defense_set_composes_feedback_from_source_scores(tmp_path):
    """build_defense_set reads the source run's scores.json and weaves the
    '1 of 2 key facts' criticism into the defense question."""
    source = make_run(
        tmp_path, {"key_facts_total": 2, "key_facts_matched": 1}, None)
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n  set: quick\n", encoding="utf-8")
    targets = defend.select_targets(source, str(queries_file),
                                    query_ids=["aq-001"], all_poorly=False)
    defenses = defend.build_defense_set(source, targets)
    assert len(defenses) == 1
    assert defend.build_defense_query.__name__  # sanity that module is live
    out = defenses[0]
    # The feedback must be woven in the question.
    assert "1 of 2" in out.question
    assert "missing some key facts" in out.question


def test_run_defenses_writes_a_transcript_per_target(tmp_path, monkeypatch):
    """Driving the defense through a real HarnessSession with a fake
    transport must write '<id>-defend-r1.jsonl' transcripts, isolated from
    the office ledger."""
    from tests.test_harness_session import (
        FakeExecutor, Provider, make_settings, sse, text_chunk, finish_chunk,
        usage_chunk,
    )
    from harness.session import HarnessSession
    from eval.agent_transcript import read_transcript

    source_dir = make_run(tmp_path, {"key_facts_total": 1, "key_facts_matched": 0},
                          None)
    queries_file = tmp_path / "queries.yaml"
    queries_file.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n  set: quick\n", encoding="utf-8")
    target = defend.select_targets(source_dir, str(queries_file),
                                   query_ids=["aq-001"], all_poorly=False)[0]
    defense = defend.build_defense_set(source_dir, [target])[0]

    def provider_builder():
        return Provider(
            lambda: sse(
                text_chunk("The prior answer is defensible: $1.4B is "
                           "supported by the FY2025 approps table."),
                finish_chunk("stop"),
                usage_chunk(prompt=100, completion=20, cost=0.002, cached=0),
            ),
        )

    dest = tmp_path / "defend"
    dest.mkdir()
    run_dir = dest / "r1"
    run_dir.mkdir()
    # The mock sessions write usage into the defense run dir's own ledger —
    # the same isolation the real make_session_factory provides — so we can
    # assert the "never the office ledger" guarantee even here.
    import eval.run_agent_eval as runner
    from harness.ledger import LimitStatus

    def allow_all(user, settings, *, now=None):
        return LimitStatus(status="allowed", message=None, reason=None,
                           limit_usd=None, month_usd=None)

    recorder = runner.make_usage_recorder(run_dir)

    def factory(query, conv_id):
        return HarnessSession(
            conv_id, corpus=query.corpus, tier=query.tier, user="eval",
            settings=make_settings(), executor=FakeExecutor(),
            transport=provider_builder().transport(), tools=[],
            system_prompt="eval test prompt", check_limit=allow_all,
            record_usage=recorder,
        )

    defend.run_defenses([defense], run_dir, make_settings(), workers=1,
                        session_factory=factory)

    out = run_dir / "aq-001-defend-r1.jsonl"
    assert out.exists()
    t = read_transcript(out)
    assert t.terminal["frame"]["type"] == "_done"
    assert "defensible" in final_answer(t)
    # Its own ledger in the defense run dir — never the office ledger.
    assert (run_dir / "ledger.jsonl").exists()
    assert (run_dir / "ledger.jsonl").read_text().strip()
