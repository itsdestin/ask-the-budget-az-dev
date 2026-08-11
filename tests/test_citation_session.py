"""The linker runs at turn end and rides on the terminal frame.

Isolation requirement: a citation-linking failure must never cost the user
a paid answer. The answer renders; the annotation degrades to empty.
"""
from __future__ import annotations

import json

from tests.test_harness_session import (
    FakeExecutor, Provider, finish_chunk, make_settings, sse, text_chunk,
    tool_chunk, usage_chunk,
)
from harness.session import HarnessSession

RETRIEVE_OUT = json.dumps({
    "top_score": 4.0, "retrieval_id": "r", "bm25_count": 1,
    "dense_count": 1, "fused_count": 1,
    "chunks": [{
        "chunk_id": "c-1", "doc_id": "d", "doc_title": "FY2026 Approps",
        "publisher": "jlbc", "fiscal_year": 2026,
        "doc_type": "approps-per-agency", "section_path": "ADC",
        "page_start": 3, "page_end": 3, "bbox": None,
        "text": "ADC General Fund 1,391,157,700 enacted",
        "text_length": 38, "score": 4.0}],
})


class CitingExecutor(FakeExecutor):
    def execute(self, name, args):
        super().execute(name, args)
        return RETRIEVE_OUT if name == "retrieve" else json.dumps({"ok": True})


def _session(provider, executor=None):
    return HarnessSession(
        "conv-cite", "budget", "standard", "analyst",
        make_settings(), executor=executor or CitingExecutor(),
        transport=provider.transport(), tools=[],
        system_prompt="test prompt",
    )


def _provider(answer_text):
    return Provider(
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "ADC"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(text_chunk(answer_text), finish_chunk("stop"),
                    usage_chunk()),
    )


def test_done_frame_carries_the_annotation():
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    frame = s.send_turn("How much for ADC?")
    s.close()
    figs = frame["annotation"]["figures"]
    assert len(figs) == 1
    assert figs[0]["verdict"] == "linked"
    assert figs[0]["primary"]["chunk_id"] == "c-1"
    assert figs[0]["primary"]["source_text"] == "1,391,157,700"


def test_annotation_offsets_index_the_final_answer():
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    frame = s.send_turn("How much for ADC?")
    s.close()
    fig = frame["annotation"]["figures"][0]
    answer = frame["finalAnswer"]
    assert answer[fig["start"]:fig["end"]] == "$1,391,157,700"


def test_a_linker_failure_does_not_lose_the_answer(monkeypatch):
    import harness.session as sess

    def boom(*a, **k):
        raise RuntimeError("linker exploded")

    monkeypatch.setattr(sess, "annotate_answer", boom)
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    frame = s.send_turn("How much for ADC?")
    s.close()
    assert frame["type"] == "_done"
    assert "1,391,157,700" in frame["finalAnswer"]
    assert frame["annotation"] == {"figures": []}


def test_turn_with_no_figures_annotates_empty():
    s = _session(_provider("The corpus does not cover that question."))
    frame = s.send_turn("Anything?")
    s.close()
    assert frame["annotation"] == {"figures": []}


def test_a_malformed_retrieve_output_does_not_break_the_annotation():
    # Tool output is a JSON string by convention; a truncated or non-JSON
    # body must cost that chunk's provenance, not the whole turn.
    class BrokenExecutor(FakeExecutor):
        def execute(self, name, args):
            super().execute(name, args)
            return "{not json"

    s = _session(_provider("ADC received $1,391,157,700 this year."),
                 executor=BrokenExecutor())
    frame = s.send_turn("How much for ADC?")
    s.close()
    assert frame["annotation"]["figures"][0]["verdict"] == "unverified"


# -- markers (spec A1): the model's [[cN]] claims reach the annotator and
# nothing else. A marker rendered to an analyst is a P1 render bug.

class AliasingExecutor(CitingExecutor):
    """Like the real `ToolExecutor`, it publishes the aliases its retrieve
    results advertised. The plain FakeExecutor deliberately does not — that
    is the shape the session must tolerate."""

    @property
    def alias_map(self):
        return {"c1": "c-1"}


def _turn(answer_text, executor=None):
    """Drive one turn; return (delta frames, terminal frame)."""
    s = _session(_provider(answer_text), executor=executor)
    events: list[dict] = []
    frame = s.send_turn("How much for ADC?", events.append)
    s.close()
    deltas = [e for e in events if e["type"] == "assistant_text_delta"]
    return deltas, frame


def test_markers_never_reach_final_answer_or_delta_frames():
    deltas, frame = _turn("ADC spent $1,391,157,700 [[c1]] that year.",
                          executor=AliasingExecutor())

    assert deltas, "the turn produced no text frames to check"
    assert all("[[" not in e["text"] for e in deltas)
    assert frame["finalAnswer"] == "ADC spent $1,391,157,700 that year."

    fig = frame["annotation"]["figures"][0]
    assert fig["link_basis"] == "tag"
    assert fig["attested_chunk_ids"] == ["c-1"]
    # The offsets must index the marker-free answer the UI renders.
    assert frame["finalAnswer"][fig["start"]:fig["end"]] == "$1,391,157,700"


def test_a_delta_ending_mid_marker_holds_the_partial_back():
    # The split lands inside the marker, which is the ordinary case: a
    # provider emits tokens, not tags. Flashing "[[c" on screen and then
    # retracting it is the visible half of the P1 bug.
    provider = Provider(
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "ADC"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(text_chunk("ADC spent $1,391,157,700 [[c"),
                    text_chunk("1]] that year."),
                    finish_chunk("stop"), usage_chunk()),
    )
    s = _session(provider, executor=AliasingExecutor())
    events: list[dict] = []
    frame = s.send_turn("How much for ADC?", events.append)
    s.close()

    deltas = [e["text"] for e in events if e["type"] == "assistant_text_delta"]
    assert len(deltas) == 2
    assert deltas[0] == "ADC spent $1,391,157,700 "
    # Delta frames carry the FULL accumulated text, so the held-back
    # characters reappear as ordinary prose the moment they resolve.
    assert deltas[1] == "ADC spent $1,391,157,700 that year."
    assert frame["finalAnswer"] == "ADC spent $1,391,157,700 that year."


def test_an_executor_without_aliases_still_links_by_value():
    # Any injected executor (and every FakeExecutor in this suite) may not
    # publish an alias map. That degrades a figure to the unambiguous-value
    # fallback; it must never cost the turn.
    _, frame = _turn("ADC spent $1,391,157,700 [[c1]] that year.")
    fig = frame["annotation"]["figures"][0]
    assert frame["finalAnswer"] == "ADC spent $1,391,157,700 that year."
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "unambiguous-fallback"
