"""Figure metrics replace citation VOLUME as the citation-quality signal.

Coverage and correctness are the goal; a high citation count is not a
defect. These metrics measure what was actually asked for.
"""
from __future__ import annotations

import pytest

from eval.agent_scoring import aggregate, score_transcript
from eval.agent_schema import AgentQuery
from eval.agent_transcript import Transcript


def transcript(figures):
    return Transcript(meta={"query_id": "q1", "repeat": 1}, events=[],
                      terminal={"frame": {
                          "type": "_done", "stopReason": "end_turn",
                          "finalAnswer": "answer", "citations": [],
                          "retrievedChunkIds": [], "toolCalls": [],
                          "annotation": {"figures": figures},
                          "usage": {"inputTokens": 10, "outputTokens": 2,
                                    "cacheReadTokens": 0, "cost": 0.001}},
                          "wall_ms": 100})


def fig(verdict, index=1):
    return {"text": "$1,000,000", "start": 0, "end": 10, "index": index,
            "verdict": verdict, "primary": None, "additional": [],
            "derived_from": []}


QUERY = AgentQuery(id="q1", question="how much?", shape="lookup")


def test_full_coverage():
    row = score_transcript(QUERY, transcript(
        [fig("linked", 1), fig("derived", 2)]))
    assert row["figures_total"] == 2
    assert row["figures_linked"] == 1
    assert row["figures_derived"] == 1
    assert row["figures_unverified"] == 0
    assert row["figure_coverage"] == 1.0


def test_partial_coverage_matches_the_reported_defect():
    # Two of ten figures carry a citation — the shape of the screenshot
    # that prompted this work. It must score badly.
    figs = [fig("linked", 1), fig("linked", 2)] + [
        fig("unverified", i) for i in range(3, 11)]
    row = score_transcript(QUERY, transcript(figs))
    assert row["figure_coverage"] == pytest.approx(0.2)
    assert row["figures_unverified"] == 8


def test_no_figures_yields_none_not_zero():
    # An answer with no figures is not a coverage failure.
    row = score_transcript(QUERY, transcript([]))
    assert row["figures_total"] == 0
    assert row["figure_coverage"] is None


def test_aggregate_reports_coverage_and_unverified_rate():
    rows = [score_transcript(QUERY, transcript([fig("linked", 1)])),
            score_transcript(QUERY, transcript([fig("unverified", 1)]))]
    summary = aggregate(rows)
    assert summary["figure_coverage_mean"] == pytest.approx(0.5)
    assert summary["unverified_rate"] == pytest.approx(0.5)


def test_transcript_without_annotation_does_not_crash():
    t = Transcript(meta={"query_id": "q1", "repeat": 1}, events=[],
                   terminal={"frame": {"type": "_done", "stopReason": "end_turn",
                                       "finalAnswer": "a", "citations": [],
                                       "retrievedChunkIds": [], "toolCalls": [],
                                       "usage": {}}, "wall_ms": 1})
    row = score_transcript(QUERY, t)
    assert row["figures_total"] == 0
    assert row["figure_coverage"] is None


def test_figureless_answers_do_not_drag_the_aggregate_to_zero():
    # A refusal states no figures. Averaging it in as 0.0 would make a run
    # of correct refusals look like a total citation failure.
    rows = [score_transcript(QUERY, transcript([fig("linked", 1)])),
            score_transcript(QUERY, transcript([]))]
    summary = aggregate(rows)
    assert summary["figure_coverage_mean"] == pytest.approx(1.0)
