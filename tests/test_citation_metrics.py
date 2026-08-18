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


QUERY = AgentQuery(id="q1", question="how much?", shape="lookup", set="quick")


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


def attested_fig(verdict, index=1, *, attested=(), link_basis=None):
    """A figure carrying the attested-linking fields (spec A2/A3)."""
    return {"text": "$1,391,157,700", "start": 0, "end": 14, "index": index,
            "verdict": verdict, "primary": None, "additional": [],
            "derived_from": [], "attested_chunk_ids": list(attested),
            "link_basis": link_basis, "ambiguity_count": None,
            "near_miss": None, "operation": None}


def test_marker_metrics_count_attested_and_tag_linked():
    # Three figures: the model tagged two of them (one verified against the
    # named chunk, one whose tag did not verify), and one carries no tag.
    row = score_transcript(QUERY, transcript([
        attested_fig("linked", 1, attested=["k1"], link_basis="tag"),
        attested_fig("linked", 2, link_basis="unambiguous-fallback"),
        attested_fig("unverified", 3, attested=["k2"]),
    ]))
    assert row["figures_attested"] == 2
    assert row["figures_tag_linked"] == 1


def test_marker_metrics_survive_an_annotation_without_the_new_fields():
    # An old transcript predates the attested fields entirely. It must read
    # as "the model tagged nothing", not crash.
    row = score_transcript(QUERY, transcript([fig("linked", 1)]))
    assert row["figures_attested"] == 0
    assert row["figures_tag_linked"] == 0


def test_aggregate_reports_marker_coverage_and_tag_accuracy():
    # Row A: 2 figures, both attested, both tag-linked.
    # Row B: 2 figures, one attested and NOT tag-linked (the tag was wrong).
    rows = [
        score_transcript(QUERY, transcript([
            attested_fig("linked", 1, attested=["k1"], link_basis="tag"),
            attested_fig("linked", 2, attested=["k2"], link_basis="tag")])),
        score_transcript(QUERY, transcript([
            attested_fig("unverified", 1, attested=["k1"]),
            attested_fig("linked", 2, link_basis="unambiguous-fallback")])),
    ]
    summary = aggregate(rows)
    # marker coverage = attested/total over figure-bearing rows: 1.0 and 0.5
    assert summary["marker_coverage_mean"] == pytest.approx(0.75)
    # tag accuracy = tag_linked/attested over rows that HAVE attestations:
    # 2/2 and 0/1.
    assert summary["tag_accuracy_mean"] == pytest.approx(0.5)


def test_tag_accuracy_skips_rows_the_model_never_tagged():
    # A row with zero attestations has no tag accuracy to report. Scoring it
    # as 0.0 would blame the verifier for the model's silence — and would
    # make marker coverage and tag accuracy report the same failure twice.
    rows = [score_transcript(QUERY, transcript([
                attested_fig("linked", 1, attested=["k1"], link_basis="tag")])),
            score_transcript(QUERY, transcript([attested_fig("unverified", 1)]))]
    summary = aggregate(rows)
    assert summary["tag_accuracy_mean"] == pytest.approx(1.0)
    assert summary["marker_coverage_mean"] == pytest.approx(0.5)


def test_figureless_rows_do_not_drag_marker_coverage_to_zero():
    # Same rule the neighbouring figure means already follow: a refusal
    # states no figures and is not a marker-coverage failure.
    rows = [score_transcript(QUERY, transcript([
                attested_fig("linked", 1, attested=["k1"], link_basis="tag")])),
            score_transcript(QUERY, transcript([]))]
    assert aggregate(rows)["marker_coverage_mean"] == pytest.approx(1.0)


def test_citation_bookkeeping_narration_is_detected():
    # The exact sentence a real answer closed with on 2026-08-02. The eval
    # could not see it before, so any prompt fix for it was unmeasurable.
    t = transcript([])
    t.terminal["frame"]["finalAnswer"] = (
        "ADOT received $1,391,157,700. All citations are now registered. "
        "The answer above covers ADOT's FY 2024 enacted appropriations."
    )
    assert score_transcript(QUERY, t)["narration_hits"] >= 1


def test_ordinary_budget_prose_is_not_flagged_as_narration():
    # The markers must not collide with policy language — the same bar the
    # "rerank" exclusion in agent_scoring.py records.
    t = transcript([])
    t.terminal["frame"]["finalAnswer"] = (
        "The Legislature registered the fund transfer in statute and "
        "anchored the formula to enrollment growth."
    )
    assert score_transcript(QUERY, t)["narration_hits"] == 0
