"""The judge must see what the analyst sees.

Before this, the judge received raw answer text plus a detached list of
citation objects — so it could not see which figures had no chip. It
graded an abstraction and reported "over-citing" when the visible defect
was the opposite. Rendering the same annotation the UI renders closes that.
"""
from __future__ import annotations

from eval.judge_agent_run import build_judge_payload, render_annotated_answer
from eval.agent_transcript import Transcript

ANSWER = "ADE gets $8,287.7 and $2,613.7, so $10,901.4 total."
ANNOTATION = {"figures": [
    {"text": "$8,287.7", "start": 9, "end": 17, "index": 1,
     "verdict": "linked",
     "primary": {"chunk_id": "c-1", "source_text": "8,287,700,000",
                 "start": 0, "end": 13},
     "additional": [], "derived_from": []},
    {"text": "$2,613.7", "start": 22, "end": 30, "index": 2,
     "verdict": "unverified", "primary": None, "additional": [],
     "derived_from": []},
    {"text": "$10,901.4", "start": 35, "end": 44, "index": 3,
     "verdict": "derived", "primary": None, "additional": [],
     "derived_from": [1, 2]},
]}


def test_the_fixture_offsets_really_index_the_fixture_answer():
    # Guards the fixture itself. An annotation whose offsets do not slice
    # to its own text is not a thing the linker can produce, so a renderer
    # tested against one proves nothing about real output — the markers
    # land mid-word and the assertions still pass by substring luck.
    for fig in ANNOTATION["figures"]:
        assert ANSWER[fig["start"]:fig["end"]] == fig["text"]


def test_linked_figure_renders_its_index():
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert "$8,287.7 [1]" in out


def test_unverified_figure_is_visibly_marked():
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert "$2,613.7 [UNCITED]" in out


def test_derived_figure_names_its_inputs():
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert "$10,901.4 [DERIVED: 1, 2]" in out


def test_markers_do_not_corrupt_offsets_of_later_figures():
    # Inserted right-to-left, so an early marker cannot shift a later one.
    out = render_annotated_answer(ANSWER, ANNOTATION)
    assert out.index("$8,287.7") < out.index("$2,613.7") < out.index("$10,901.4")


def test_answer_without_annotation_is_returned_unchanged():
    assert render_annotated_answer(ANSWER, {"figures": []}) == ANSWER


def test_payload_carries_the_annotated_answer_and_figure_counts():
    from eval.agent_schema import AgentQuery
    t = Transcript(meta={}, events=[], terminal={"frame": {
        "type": "_done", "finalAnswer": ANSWER, "citations": [],
        "toolCalls": [], "annotation": ANNOTATION}})
    q = AgentQuery(id="q1", question="how much?", shape="lookup")
    payload = build_judge_payload(q, t)
    assert "[UNCITED]" in payload["annotated_answer"]
    assert payload["figure_counts"] == {
        "linked": 1, "derived": 1, "unverified": 1}


def test_a_transcript_from_before_linking_shipped_still_builds_a_payload():
    # Every committed baseline predates the annotation. The judge must
    # keep working on them rather than crashing or inventing markers.
    from eval.agent_schema import AgentQuery
    t = Transcript(meta={}, events=[], terminal={"frame": {
        "type": "_done", "finalAnswer": ANSWER, "citations": [],
        "toolCalls": []}})
    payload = build_judge_payload(AgentQuery(id="q1", question="?", shape="lookup"), t)
    assert payload["annotated_answer"] == ANSWER
    assert payload["figure_counts"] == {
        "linked": 0, "derived": 0, "unverified": 0}
