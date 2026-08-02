"""The annotation survives the whole server-side path to the wire.

Every other citation test stops at a seam: the linker is unit-tested, the
session is tested against a fake executor, and the route is tested against
a FakeSession that never runs a linker at all. Nothing proved that a REAL
`HarnessSession`, driven through the REAL SSE route, puts an annotation in
the `_done` frame the webapp parses — which is the only frame the webapp
reads it from. This closes that gap without a network or an API key.
"""
from __future__ import annotations

import json

from harness.session import HarnessSession
from tests.test_conversations_route import (  # noqa: F401 - isolated_share fixture
    build_app, client_for, configure_ai, frames_of, isolated_share,
    new_conversation,
)
from tests.test_harness_session import (
    FakeExecutor, Provider, finish_chunk, make_settings, sse, text_chunk,
    tool_chunk, usage_chunk,
)

ANSWER = (
    "| Agency | FY 2026 Appropriation |\n"
    "|---|---|\n"
    "| ADC | $1,391,157,700 |\n"
    "| AHCCCS | $2,613,700,000 |\n\n"
    "Together they account for $4,004,857,700."
)

RETRIEVE_OUT = json.dumps({
    "top_score": 4.0, "retrieval_id": "r", "bm25_count": 2,
    "dense_count": 2, "fused_count": 2,
    "chunks": [
        {"chunk_id": "c-adc", "doc_id": "d1", "doc_title": "FY2026 Approps",
         "publisher": "jlbc", "fiscal_year": 2026,
         "doc_type": "approps-per-agency", "section_path": "ADC",
         "page_start": 3, "page_end": 3, "bbox": None,
         "text": "Corrections, Department of\t1,391,157,700\tGeneral Fund",
         "text_length": 50, "score": 4.0},
        {"chunk_id": "c-ahcccs", "doc_id": "d2", "doc_title": "FY2026 Baseline",
         "publisher": "jlbc", "fiscal_year": 2026,
         "doc_type": "baseline-per-agency", "section_path": "AHCCCS",
         "page_start": 9, "page_end": 9, "bbox": None,
         "text": "AHCCCS total 2,613,700,000 General Fund",
         "text_length": 39, "score": 3.6},
    ],
})


class _Executor(FakeExecutor):
    def execute(self, name, args):
        super().execute(name, args)
        return RETRIEVE_OUT if name == "retrieve" else json.dumps({"ok": True})


def _real_session_factory():
    provider = Provider(
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "biggest agencies"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(text_chunk(ANSWER), finish_chunk("stop"), usage_chunk()),
    )

    def make(conversation_id, *, corpus, tier, user):
        # Settings are passed explicitly: HarnessSession defaults to an
        # EMPTY Settings(), not the share's, so a session built without
        # them refuses the turn with "no API key configured".
        return HarnessSession(
            conversation_id, corpus, tier, user, make_settings(),
            executor=_Executor(), transport=provider.transport(),
            tools=[], system_prompt="test prompt",
        )

    return make


def test_the_done_frame_on_the_wire_carries_linked_figures():
    configure_ai()
    c = client_for(build_app(session_factory=_real_session_factory()))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "what are the biggest agencies by budget?",
                     "tier": "standard"})
    assert r.status_code == 200, r.text

    done = frames_of(r)[-1]
    assert done["type"] == "_done"
    figures = done["annotation"]["figures"]

    # Every figure the answer states is accounted for, and the total is
    # recognised as arithmetic over the two it was computed from rather
    # than dressed up as a sourced number.
    assert [f["text"] for f in figures] == [
        "$1,391,157,700", "$2,613,700,000", "$4,004,857,700"]
    assert [f["verdict"] for f in figures] == ["linked", "linked", "derived"]
    assert sorted(figures[2]["derived_from"]) == [1, 2]

    # The primary source carries the SOURCE's rendering — what the PDF text
    # layer actually contains — and it is found even though the chunk fuses
    # the agency name straight onto the number.
    assert figures[0]["primary"]["chunk_id"] == "c-adc"
    assert figures[0]["primary"]["source_text"] == "1,391,157,700"


def test_indices_are_reading_order_on_the_wire():
    # The reported defect was chips numbered 1-3-4-2. Indices are assigned
    # by position in the answer, so they cannot arrive shuffled.
    configure_ai()
    c = client_for(build_app(session_factory=_real_session_factory()))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "biggest agencies", "tier": "standard"})
    figures = frames_of(r)[-1]["annotation"]["figures"]
    assert [f["index"] for f in figures] == [1, 2, 3]
    starts = [f["start"] for f in figures]
    assert starts == sorted(starts)


def test_the_model_is_not_asked_to_cite_the_figures():
    # The point of the design: the system links figures, so a numeric
    # answer costs zero cite round-trips.
    configure_ai()
    c = client_for(build_app(session_factory=_real_session_factory()))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "biggest agencies", "tier": "standard"})
    done = frames_of(r)[-1]
    cite_calls = [t for t in done["toolCalls"]
                  if t["toolName"] in ("cite", "cite_batch")]
    assert cite_calls == []
    assert done["citations"] == []
    # ...and the figures are cited anyway.
    assert all(f["verdict"] != "unverified"
               for f in done["annotation"]["figures"])
