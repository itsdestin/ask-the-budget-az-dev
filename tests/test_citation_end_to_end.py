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


def test_a_figure_chip_has_what_it_needs_to_open_the_pdf():
    # The payoff of the whole design: click a number, see it highlighted on
    # the page. On 2026-08-02 every figure chip landed on "Couldn't open
    # source PDF" because the annotation carried only a chunk_id, and the
    # viewer needs doc_id + page_start.
    configure_ai()
    c = client_for(build_app(session_factory=_real_session_factory()))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "biggest agencies", "tier": "standard"})
    primary = frames_of(r)[-1]["annotation"]["figures"][0]["primary"]
    assert primary["doc_id"] == "d1"
    assert primary["page_start"] == 3
    assert primary["doc_title"] == "FY2026 Approps"
    assert primary["publisher"] == "jlbc"
    assert primary["fiscal_year"] == 2026


# ---------------------------------------------------------------------------
# All five verdict paths in ONE turn (spec A2/A3/A5/A6)
#
# Each path is unit-tested in isolation elsewhere. What is untested is that
# they still each do their own job when a single real answer exercises all
# of them at once — the tag verifying, the tag FAILING and the fallback
# rescuing it, the value that is in the pool twice, the total that is in the
# pool zero times, and the number that is close to a source but outside the
# precision its own rendering certifies.
# ---------------------------------------------------------------------------

# The model's raw output, markers and all. Every value below was chosen so
# that ONE path can claim it and no neighbouring path can — see the
# per-figure comments in test_all_five_verdict_paths_in_one_answer.
ATTESTED_ANSWER = (
    "Corrections was appropriated $1,391,157,700 [[c1]] from the General "
    "Fund in FY 2026, and AHCCCS was appropriated $2,613,700,000 [[c1]] "
    "in the same year, for a combined $4,004,857,700.\n\n"
    "School facilities carry $1,058,400,000 across the capital program, "
    "and Public Safety's appropriation was about $987.6 million [[c4]] "
    "on the same basis."
)

# alias -> chunk_id, exactly as `harness.tools.ToolExecutor` hands them to
# the model on a retrieve result.
ATTESTED_ALIASES = {"c1": "c-adc", "c2": "c-ahcccs", "c3": "c-ess",
                    "c4": "c-dps", "c5": "c-gov"}


def _chunk(chunk_id: str, alias: str, doc_id: str, title: str, page: int,
           text: str) -> dict:
    return {"chunk_id": chunk_id, "alias": alias, "doc_id": doc_id,
            "doc_title": title, "publisher": "jlbc", "fiscal_year": 2026,
            "doc_type": "approps-per-agency", "section_path": title,
            "page_start": page, "page_end": page, "bbox": None,
            "text": text, "text_length": len(text), "score": 4.0}


ATTESTED_RETRIEVE_OUT = json.dumps({
    "top_score": 4.0, "retrieval_id": "r", "bm25_count": 5,
    "dense_count": 5, "fused_count": 5,
    "chunks": [
        _chunk("c-adc", "c1", "d1", "FY2026 Approps — ADC", 3,
               "Corrections, Department of\t1,391,157,700\tGeneral Fund"),
        _chunk("c-ahcccs", "c2", "d2", "FY2026 Baseline — AHCCCS", 9,
               "AHCCCS total 2,613,700,000 General Fund"),
        # The ambiguous value lives in two DIFFERENT documents. Two chunks
        # of one document would not be ambiguous — the fallback counts
        # documents, not chunks.
        _chunk("c-ess", "c3", "d3", "FY2026 Executive Budget", 12,
               "School facilities program 1,058,400,000 total funds"),
        _chunk("c-gov", "c5", "d5", "FY2026 Capital Outlay", 4,
               "Building renewal 1,058,400,000 all sources"),
        _chunk("c-dps", "c4", "d4", "FY2026 Approps — DPS", 21,
               "Public Safety, Department of 987,654,321 General Fund"),
    ],
})


class _AttestedExecutor(FakeExecutor):
    """Serves the five-chunk pool AND exposes `alias_map`.

    The second half matters: `HarnessSession` reads the map off the
    executor with `getattr(..., "alias_map", None) or {}`, so a fake that
    omits it resolves every [[cN]] to nothing, SILENTLY. Every tagged
    figure would then degrade to the pool-wide fallback, both tag
    assertions below would still find `linked`, and the test would pass
    while proving the opposite of what it claims.
    """

    alias_map = ATTESTED_ALIASES

    def execute(self, name, args):
        super().execute(name, args)
        return (ATTESTED_RETRIEVE_OUT if name == "retrieve"
                else json.dumps({"ok": True}))


def _attested_session_factory(executor: FakeExecutor):
    # The answer is streamed in three pieces, and the SECOND break lands
    # INSIDE a marker ("[[c" | "1]]"). A marker split across delta frames
    # is the shape that leaks: `strip_for_stream` has to withhold a
    # trailing partial that is not yet a marker, which a single-chunk
    # script never exercises.
    cut = ATTESTED_ANSWER.index("[[c1]]") + 3
    pieces = [ATTESTED_ANSWER[:cut], ATTESTED_ANSWER[cut:cut + 40],
              ATTESTED_ANSWER[cut + 40:]]
    provider = Provider(
        lambda: sse(tool_chunk(0, call_id="c1", name="retrieve",
                               arguments='{"query": "fy2026 appropriations"}'),
                    finish_chunk("tool_calls"), usage_chunk()),
        lambda: sse(*[text_chunk(p) for p in pieces],
                    finish_chunk("stop"), usage_chunk()),
    )

    def make(conversation_id, *, corpus, tier, user):
        return HarnessSession(
            conversation_id, corpus, tier, user, make_settings(),
            executor=executor, transport=provider.transport(),
            tools=[], system_prompt="test prompt",
        )

    return make


def _attested_turn():
    configure_ai()
    executor = _AttestedExecutor()
    c = client_for(build_app(
        session_factory=_attested_session_factory(executor)))
    cid = new_conversation(c)
    r = c.post(f"/api/conversations/{cid}/messages",
               json={"text": "fy2026 appropriations", "tier": "standard"})
    assert r.status_code == 200, r.text
    return r, executor


def test_all_five_verdict_paths_in_one_answer():
    r, _ = _attested_turn()
    figures = frames_of(r)[-1]["annotation"]["figures"]
    # Only CITATIONS are numbered. The two unverified figures draw no chip
    # and take no number, so the live chips read [1] [2] [3] rather than a
    # sequence with holes struck through it.
    assert [f["index"] for f in figures] == [1, 2, 3, None, None]
    # Keyed by reading position, because two figures now share index None.
    by_index = dict(enumerate(figures, start=1))

    # 1 — TAG VERIFIED. $1,391,157,700 is tagged [[c1]] and c-adc contains
    # it, fused onto the agency name. `link_basis == "tag"` is what proves
    # the alias reached the annotator: the value is also unambiguous in the
    # pool, so a dropped alias would still link it — by fallback.
    tagged = by_index[1]
    assert tagged["text"] == "$1,391,157,700"
    assert (tagged["verdict"], tagged["link_basis"]) == ("linked", "tag")
    assert tagged["primary"]["chunk_id"] == "c-adc"
    assert tagged["primary"]["source_text"] == "1,391,157,700"

    # 2 — TAG FAILED, FALLBACK RESCUED IT. The model tagged AHCCCS's number
    # [[c1]] too; c-adc does not contain 2,613,700,000, and exactly one
    # document (d2) does. A tag that misses must not doom the figure — it
    # falls back to the value being unambiguous, and the record still shows
    # which chunk the model NAMED so the miss stays auditable.
    fallback = by_index[2]
    assert fallback["text"] == "$2,613,700,000"
    assert (fallback["verdict"], fallback["link_basis"]) == (
        "linked", "unambiguous-fallback")
    assert fallback["attested_chunk_ids"] == ["c-adc"]
    assert fallback["primary"]["chunk_id"] == "c-ahcccs"

    # 3 — DERIVED. 1,391,157,700 + 2,613,700,000 = 4,004,857,700, which
    # appears in NO chunk. `derived_from` names the two figures by their
    # reading-order index — what the analyst sees on the chip — not by
    # their position in the linker's internal list.
    total = by_index[3]
    assert total["text"] == "$4,004,857,700"
    assert (total["verdict"], total["operation"]) == ("derived", "sum")
    assert sorted(total["derived_from"]) == [1, 2]
    assert total["primary"] is None

    # 4 — AMBIGUOUS. 1,058,400,000 sits in d3 AND d5, so no single source
    # can be claimed. Written as 5 significant digits, it clears the
    # fallback's floor of 4 — the refusal here is genuinely "found twice",
    # not "too round to look for", which is the neighbouring path that
    # would also read `unverified`.
    ambiguous = by_index[4]
    assert ambiguous["text"] == "$1,058,400,000"
    assert ambiguous["verdict"] == "unverified"
    assert ambiguous["ambiguity_count"] == 2
    # No near miss, deliberately: the value IS in the pool, exactly, so a
    # "nearest source value differs by 0.0%" line would be nonsense beside
    # "appears in 2 documents". Two different failures; only one is true.
    assert ambiguous["near_miss"] is None

    # 5 — NEAR MISS. "$987.6 million" certifies [987.55M, 987.65M]; the
    # source says 987,654,321, which is 4,321 outside it. Rounder or looser
    # and it would have LINKED, further away and the 5% ceiling would
    # report nothing — this is the narrow band where the honest answer is
    # "close, but not what the document says". Written as 4 significant
    # digits it clears BOTH floors (the tag path's 2 and the fallback's 4),
    # so the refusal is precision, never specificity — which is the
    # neighbouring path that would also read `unverified` + no source.
    near = by_index[5]
    assert near["text"] == "$987.6"
    assert near["verdict"] == "unverified"
    assert near["ambiguity_count"] is None
    # Scoped to the chunk the model NAMED: "you said c4, and c4's nearest
    # number is this" is the sentence an analyst can act on.
    assert near["attested_chunk_ids"] == ["c-dps"]
    assert near["near_miss"]["chunk_id"] == "c-dps"
    assert near["near_miss"]["source_text"] == "987,654,321"
    assert 0 < near["near_miss"]["distance"] < 0.05


def test_no_marker_ever_reaches_the_wire():
    # A marker is the model's private channel to the linker. An analyst
    # seeing "[[c1]]" in an answer is a P1 render bug, and the whole SSE
    # body is the only place that can be checked once and cover every
    # frame kind — deltas, turn_complete and _done alike.
    r, _ = _attested_turn()
    assert "[[" not in r.text
    assert "]]" not in r.text
    # ...and the answer the analyst reads is otherwise intact, markers
    # removed without eating the words around them.
    done = frames_of(r)[-1]
    assert done["finalAnswer"].startswith(
        "Corrections was appropriated $1,391,157,700 from the General Fund")
    assert done["finalAnswer"].endswith("$987.6 million on the same basis.")


def test_five_figures_cost_zero_cite_round_trips():
    # The design's economic claim: the system links figures, so a numeric
    # answer spends no cite calls at all — not even for the two that fail
    # to link, which the old design would have had the model try to cite.
    r, executor = _attested_turn()
    assert [name for name, _ in executor.calls] == ["retrieve"]
    done = frames_of(r)[-1]
    assert [t for t in done["toolCalls"]
            if t["toolName"] in ("cite", "cite_batch")] == []
    assert done["citations"] == []
