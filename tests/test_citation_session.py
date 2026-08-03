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


def test_the_annotation_is_attached_to_history_for_the_transcript():
    """Handoff Issue 1: the figure annotation must persist, not just ride the
    ephemeral `_done` frame. It is attached to the final assistant message of
    the turn, which is what persist_turn saves to disk. Without this a reopened
    chat could not restore citation chips."""
    s = _session(_provider("ADC received $1,391,157,700 this year."))
    s.send_turn("How much for ADC?")
    s.close()
    last_assistant = next(
        m for m in reversed(s.history) if m.get("role") == "assistant"
    )
    figs = last_assistant["annotation"]["figures"]
    assert len(figs) == 1
    assert figs[0]["verdict"] == "linked"
    assert figs[0]["primary"]["chunk_id"] == "c-1"


def test_the_annotation_never_leaks_into_the_provider_request():
    """The annotation is transcript metadata, not conversation. Sending it back
    on an assistant message could confuse or break an OpenAI-compatible
    endpoint, so the request built for the NEXT turn must not carry it."""
    provider = _provider("ADC received $1,391,157,700 this year.")
    s = _session(provider)
    s.send_turn("How much for ADC?")
    # Ask again: the second request walks history including the annotated
    # first answer. Capture what the provider actually received.
    bodies_before = len(provider.bodies)
    s.send_turn("And the FDJP?")
    s.close()
    assert len(provider.bodies) > bodies_before, "expected a second provider request"
    wire = provider.bodies[-1]
    for message in wire.get("messages", []):
        assert "annotation" not in message


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
