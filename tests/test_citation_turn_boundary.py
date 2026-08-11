"""The annotation belongs to ITS OWN turn, and survives a hang-up.

Two defects found by review on 2026-08-11, both of which cost an analyst
citation chips on an answer they had already been given:

  1. `_attach_annotation` searched backwards through the WHOLE history, so a
     turn that appended no assistant message overwrote the PREVIOUS turn's
     annotation with its own empty one.
  2. The Stop button aborts the fetch, raising GeneratorExit inside
     `stream_turn`, so the end-of-turn code that computes and attaches the
     annotation never ran — and neither did the append of the partial answer
     the analyst was watching.

Both are pinned here rather than in test_citation_session.py because both are
about the turn BOUNDARY, not about linking.
"""
from __future__ import annotations

import pytest

from tests.test_citation_session import CitingExecutor
from tests.test_harness_session import (
    Provider, finish_chunk, make_settings, sse, text_chunk, tool_chunk, usage_chunk,
)
from harness.session import HarnessSession

ANSWER = "ADC received $1,391,157,700 this year."


def _retrieve_then(*answers):
    """A provider that retrieves, answers, and then plays `answers` in turn."""
    steps = [
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "ADC"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(text_chunk(ANSWER), finish_chunk("stop"), usage_chunk()),
    ]
    steps.extend(answers)
    return Provider(*steps)


def _session(provider, conversation_id="conv-boundary"):
    return HarnessSession(
        conversation_id, "budget", "standard", "analyst",
        make_settings(), executor=CitingExecutor(),
        transport=provider.transport(), tools=[], system_prompt="test prompt",
    )


def _annotated(session):
    return [m for m in session.history if "annotation" in m]


def _figure_counts(session):
    return [len(m["annotation"]["figures"]) for m in _annotated(session)]


def test_a_turn_that_says_nothing_leaves_the_previous_annotation_alone():
    """The regression that motivated `since=`. Verified failing before the fix
    (turn 1's figure count fell 1 -> 0)."""
    session = _session(_retrieve_then(
        # The model returns neither text nor tool calls — a legal, if useless,
        # completion, and one that appends no assistant message.
        lambda: sse(finish_chunk("stop"), usage_chunk()),
    ))
    session.send_turn("How much for ADC?")
    assert _figure_counts(session) == [1]

    session.send_turn("and the year before?")
    session.close()
    assert _figure_counts(session) == [1], "the silent turn clobbered turn 1"


def test_an_empty_annotation_lands_on_its_own_turn_and_goes_no_further():
    """A figure-less turn still writes `{"figures": []}` — that shape is pinned
    by test_harness_session's interrupt spec. What it must not do is write it
    onto SOMEBODY ELSE's answer, which is what `since=` prevents."""
    session = _session(_retrieve_then(
        lambda: sse(text_chunk("No figures here at all."), finish_chunk("stop"),
                    usage_chunk()),
    ))
    session.send_turn("How much for ADC?")
    session.send_turn("Anything else?")
    session.close()
    # Turn 1 keeps its linked figure; turn 2 carries its own empty annotation.
    assert _figure_counts(session) == [1, 0]


def test_hanging_up_keeps_the_partial_answer_and_its_annotation():
    """The Stop button's real shape: the consumer stops reading mid-stream."""
    session = _session(_retrieve_then())
    stream = session.stream_turn("How much for ADC?")
    for frame in stream:
        if frame["type"] == "assistant_text_delta":
            break
    stream.close()                       # -> GeneratorExit inside stream_turn
    session.close()

    answers = [m for m in session.history
               if m.get("role") == "assistant" and m.get("content")]
    assert answers, "the partial answer the analyst watched was dropped"
    assert ANSWER in answers[-1]["content"]
    assert _figure_counts(session) == [1], "the stopped turn lost its annotation"


def test_hanging_up_records_the_answer_exactly_once():
    """`recorded` exists so the ordinary append and the hang-up append can
    never both fire. A duplicated assistant message is a malformed request
    the provider 400s."""
    session = _session(_retrieve_then())
    stream = session.stream_turn("How much for ADC?")
    frames = list(stream)                # drain fully: the normal append runs
    stream.close()                       # then hang up anyway
    session.close()

    assert frames[-1]["type"] == "_done"
    answers = [m for m in session.history
               if m.get("role") == "assistant" and m.get("content") == ANSWER]
    assert len(answers) == 1
    assert _figure_counts(session) == [1]


@pytest.mark.parametrize("role", ["assistant"])
def test_the_annotation_never_reaches_the_provider(role):
    """Unchanged behaviour, re-pinned here because `since=` moved the code
    that writes the key."""
    from harness.session import _strip_wire_annotation

    session = _session(_retrieve_then())
    session.send_turn("How much for ADC?")
    session.close()
    assert _annotated(session)
    assert all("annotation" not in m
               for m in _strip_wire_annotation(session.history))
