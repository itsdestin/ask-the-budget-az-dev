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


# -- cross-turn scope. The linking pool spans the CONVERSATION so a model
# can cite a passage it read two questions ago; the UNTAGGED fallback
# stays scoped to this turn, because with only the value as evidence every
# extra document in scope is another chance to coincide. Measured over the
# 31-query baseline: merging 8 turns' pools took the untagged false-link
# rate on rounded billions from 0.28% to 2.50%, near the 3.7% of the
# authority-ranking design this replaced.

def _two_turn(second_answer, executor=None):
    """Turn 1 retrieves; turn 2 answers from context with NO tool call."""
    provider = Provider(
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "ADC"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(text_chunk("Found the ADC figure."),
                    finish_chunk("stop"), usage_chunk()),
        lambda: sse(text_chunk(second_answer),
                    finish_chunk("stop"), usage_chunk()),
    )
    s = _session(provider, executor=executor)
    s.send_turn("How much for ADC?")
    frame = s.send_turn("Repeat that figure.")
    s.close()
    return frame


def test_a_tagged_figure_from_an_earlier_turn_still_links():
    """Observed live 2026-08-11: a follow-up produced a nine-row table
    whose values all sat in a chunk retrieved by an EARLIER turn, and
    every chip rendered red. A model answering from context does not
    retrieve again, and a turn-scoped pool punishes it for not wasting a
    search."""
    frame = _two_turn("As noted, ADC received $1,391,157,700 [[c1]].",
                      executor=AliasingExecutor())
    (fig,) = frame["annotation"]["figures"]
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "tag"
    assert fig["primary"]["chunk_id"] == "c-1"
    # Locator metadata has to survive the hop, or the chip opens on
    # "Couldn't open source PDF".
    assert fig["primary"]["page_start"] == 3


def test_an_untagged_figure_from_an_earlier_turn_does_not_link():
    """The deliberate other half. Widening the untagged pool across a
    whole conversation is what re-creates the wrong-document rate this
    design exists to remove, so an untagged figure whose source was
    retrieved in an earlier turn is refused, not guessed."""
    frame = _two_turn("As noted, ADC received $1,391,157,700.")
    (fig,) = frame["annotation"]["figures"]
    assert fig["verdict"] == "unverified"
    assert fig["link_basis"] is None
