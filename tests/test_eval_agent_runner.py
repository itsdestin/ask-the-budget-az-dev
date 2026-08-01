"""Runner tests — every model interaction is a canned MockTransport
response (tests/test_harness_session.py fakes), so this suite never
spends money and never touches the office ledger or settings.json.
"""
from __future__ import annotations

import json

import pytest

from eval.agent_schema import AgentQuery, KeyFact
from eval.agent_scoring import score_transcript
from eval.agent_transcript import read_transcript
from eval.run_agent_eval import (
    build_manifest,
    query_set_sha256,
    run_suite,
    select_queries,
)
from harness.session import HarnessSession
from tests.test_harness_session import (
    FakeExecutor,
    Provider,
    finish_chunk,
    make_settings,
    sse,
    text_chunk,
    tool_chunk,
    usage_chunk,
)


def q(id="aq-001", **kw):
    defaults = dict(question="ADC FY2025 General Fund?", shape="lookup",
                    subsets=["smoke", "full"])
    defaults.update(kw)
    return AgentQuery(id=id, **defaults)


def fake_factory(provider_builder):
    """session_factory seam: real HarnessSession, fake transport/executor.

    A FRESH Provider per session — an httpx.Response stream is
    single-consumption, so sharing one across queries would break replay.
    """
    def factory(query, conv_id):
        return HarnessSession(
            conv_id, corpus=query.corpus, tier=query.tier, user="eval",
            settings=make_settings(),
            executor=FakeExecutor(),
            transport=provider_builder().transport(),
            tools=[],
            system_prompt="eval test prompt",
        )
    return factory


def simple_provider():
    return Provider(
        lambda: sse(
            tool_chunk(0, call_id="c1", name="retrieve", arguments='{"query": "ADC"}'),
            finish_chunk("tool_calls"),
            usage_chunk(prompt=100, completion=10, cost=0.001, cached=0),
        ),
        lambda: sse(
            text_chunk("ADC got $1.4 B."),
            finish_chunk("stop"),
            usage_chunk(prompt=200, completion=30, cost=0.002, cached=90),
        ),
    )


def test_run_suite_writes_transcript_per_query(tmp_path):
    queries = [q("aq-001"), q("aq-002")]
    run_suite(queries, tmp_path, fake_factory(simple_provider), progress=lambda *_: None)
    for qid in ("aq-001", "aq-002"):
        t = read_transcript(tmp_path / f"{qid}-r1.jsonl")
        assert t.meta["query_id"] == qid
        assert t.terminal["frame"]["type"] == "_done"
        assert t.terminal["wall_ms"] is not None
        assert t.terminal["frame"]["usage"]["cost"] == pytest.approx(0.003)


def test_repeats_write_separate_files(tmp_path):
    run_suite([q()], tmp_path, fake_factory(simple_provider), repeats=2,
              progress=lambda *_: None)
    assert (tmp_path / "aq-001-r1.jsonl").exists()
    assert (tmp_path / "aq-001-r2.jsonl").exists()


def test_one_exploding_session_does_not_abort_the_run(tmp_path):
    calls = {"n": 0}

    def factory(query, conv_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("session construction blew up")
        return fake_factory(simple_provider)(query, conv_id)

    run_suite([q("aq-001"), q("aq-002")], tmp_path, factory, progress=lambda *_: None)
    t1 = read_transcript(tmp_path / "aq-001-r1.jsonl")
    assert t1.terminal["frame"]["type"] == "_error"
    assert "RuntimeError" in t1.terminal["frame"]["message"]
    t2 = read_transcript(tmp_path / "aq-002-r1.jsonl")
    assert t2.terminal["frame"]["type"] == "_done"


def test_session_close_failure_does_not_lose_transcript_or_abort_run(tmp_path, capsys):
    """Finding 2/3: session.close() raising must (a) print a diagnostic to
    stderr instead of vanishing silently, (b) still write that query's
    transcript (the close failure happens AFTER send_turn already produced a
    frame), and (c) not stop later queries from running."""
    def factory(query, conv_id):
        session = fake_factory(simple_provider)(query, conv_id)

        def exploding_close():
            raise RuntimeError("close blew up")

        session.close = exploding_close  # instance attr; called with no args
        return session

    run_suite([q("aq-001"), q("aq-002")], tmp_path, factory, progress=lambda *_: None)

    t1 = read_transcript(tmp_path / "aq-001-r1.jsonl")
    assert t1.terminal["frame"]["type"] == "_done"  # transcript NOT lost
    t2 = read_transcript(tmp_path / "aq-002-r1.jsonl")
    assert t2.terminal["frame"]["type"] == "_done"  # run kept going

    err = capsys.readouterr().err
    assert "aq-001" in err
    assert "close" in err.lower()
    assert "RuntimeError" in err


def test_write_transcript_failure_does_not_abort_run(tmp_path, capsys, monkeypatch):
    """Finding 1/3: a write_transcript failure on one query (this project has
    documented write flakiness on the shared network drive) must not escape
    run_suite and kill the rest of a multi-hour paid run — it must be reported
    loudly and the remaining queries must still execute and land."""
    import eval.run_agent_eval as runner
    real_write = runner.write_transcript
    calls = {"n": 0}

    def flaky_write(path, meta, events, terminal):
        calls["n"] += 1
        if calls["n"] == 1:
            raise OSError("simulated network-share write failure")
        return real_write(path, meta, events, terminal)

    monkeypatch.setattr(runner, "write_transcript", flaky_write)

    run_suite([q("aq-001"), q("aq-002")], tmp_path, fake_factory(simple_provider),
              progress=lambda *_: None)

    assert not (tmp_path / "aq-001-r1.jsonl").exists()  # that one query's record is lost...
    t2 = read_transcript(tmp_path / "aq-002-r1.jsonl")
    assert t2.terminal["frame"]["type"] == "_done"  # ...but the run continued

    err = capsys.readouterr().err
    assert "aq-001" in err
    assert "OSError" in err


def test_select_queries_by_subset_and_ids():
    qs = [q("a", subsets=["smoke", "full"]), q("b", subsets=["full"]),
          q("c", subsets=["dr-probe"], tier="deep_research")]
    assert [x.id for x in select_queries(qs, "smoke", None)] == ["a"]
    assert [x.id for x in select_queries(qs, "full", None)] == ["a", "b"]
    assert [x.id for x in select_queries(qs, "dr-probe", None)] == ["c"]
    assert [x.id for x in select_queries(qs, "full", ["b"])] == ["b"]


def test_manifest_redacts_key_and_records_models(tmp_path):
    settings = make_settings()
    manifest = build_manifest(settings, [q()], subset="smoke", repeats=1)
    blob = json.dumps(manifest)
    assert "sk-test" not in blob  # the fake key from make_settings()
    assert manifest["api_key_set"] is True
    assert "standard" in manifest["tier_models"]
    assert manifest["queries"] == ["aq-001"]
    assert "prompt_sha256" in manifest and "corpus_counts" in manifest


def test_manifest_hashes_the_query_set_content_not_just_the_ids():
    """Finding 2: `queries` (an id list) is byte-identical when somebody
    EDITS a query's key facts between two `full` runs, so the compare tool
    had no way to tell authoring drift from a real change."""
    settings = make_settings()
    original = q(key_facts=[KeyFact(kind="currency", value="$1,391,157,700")])
    edited = q(key_facts=[KeyFact(kind="currency", value="$1,400,000,000")])

    a = build_manifest(settings, [original], subset="full", repeats=1)
    b = build_manifest(settings, [edited], subset="full", repeats=1)
    assert a["queries"] == b["queries"]          # the old signal: identical
    assert a["queries_sha256"] != b["queries_sha256"]  # the new one: differs

    same = build_manifest(settings, [q(key_facts=list(original.key_facts))],
                          subset="full", repeats=1)
    assert a["queries_sha256"] == same["queries_sha256"]


def test_query_set_hash_ignores_ordering():
    # Reordering the YAML must not read as a changed measuring stick.
    a, b = q("aq-001"), q("aq-002")
    assert query_set_sha256([a, b]) == query_set_sha256([b, a])


# --- Finding 3: the runner -> scorer seam --------------------------------
#
# Every runner test above asserts only the terminal frame's TYPE and cost, and
# never imports the scorer; every scorer test uses hand-written fixtures. The
# frame's own key names were therefore untested end to end. Verified: a
# transcript whose frame calls the list `cites` instead of `citations` scores
# as verified_citations: 0, refused: True, ok: True -- silently. A rename in
# harness/session.py's TurnRecorder would leave the whole suite green while
# every real run reported a total citation collapse AND scored all five
# refusal queries as correct refusals. This test runs the REAL session
# (fake transport only), writes a real transcript, and scores it, so a rename
# breaks a test instead of a baseline.

def citing_provider():
    """retrieve -> cite -> answer, the shape of a normal successful query."""
    return Provider(
        lambda: sse(
            tool_chunk(0, call_id="c1", name="retrieve", arguments='{"query": "ADC"}'),
            finish_chunk("tool_calls"),
            usage_chunk(prompt=100, completion=10, cost=0.001, cached=0),
        ),
        lambda: sse(
            tool_chunk(0, call_id="c2", name="cite", arguments=json.dumps({
                "chunk_id": "c-1", "quote": "$1,391,157,700",
                "confidence": "verbatim", "claim_span": "ADC received the money"})),
            finish_chunk("tool_calls"),
            usage_chunk(prompt=150, completion=20, cost=0.001, cached=0),
        ),
        lambda: sse(
            text_chunk("ADC received $1,391,157,700 in FY 2025."),
            finish_chunk("stop"),
            usage_chunk(prompt=200, completion=30, cost=0.002, cached=90),
        ),
    )


def citing_executor():
    return FakeExecutor(results={
        "retrieve": {"top_score": 4.0, "retrieval_id": "r", "chunks": [
            {"chunk_id": "c-1", "doc_id": "d", "doc_title": "T", "publisher": "jlbc",
             "fiscal_year": 2025, "doc_type": "afr", "page_start": 1, "page_end": 1,
             "text": "ADC received $1,391,157,700 in FY 2025.", "score": 4.0}]},
        "cite": {"ok": True, "citation_id": "cit-1",
                 "resolved_span_start": 13, "resolved_span_end": 27},
    })


def test_a_real_run_produces_a_transcript_the_scorer_actually_reads(tmp_path):
    query = q(key_facts=[KeyFact(kind="currency", value="$1,391,157,700")])

    def factory(_query, conv_id):
        return HarnessSession(
            conv_id, corpus=_query.corpus, tier=_query.tier, user="eval",
            settings=make_settings(), executor=citing_executor(),
            transport=citing_provider().transport(), tools=[],
            system_prompt="eval test prompt",
        )

    run_suite([query], tmp_path, factory, progress=lambda *_: None)
    row = score_transcript(query, read_transcript(tmp_path / "aq-001-r1.jsonl"))

    # Each of these reads a DIFFERENT key of the real frame. A rename of any
    # one of them upstream fails here rather than silently zeroing a metric.
    assert row["ok"] is True                       # frame["type"] == "_done"
    assert row["key_fact_rate"] == 1.0             # frame["finalAnswer"]
    assert row["verified_citations"] == 1          # frame["citations"][].ok
    assert row["refused"] is False                 # derived from the above
    assert row["cite_attempts"] == 1               # frame["toolCalls"]
    assert row["cite_pass_rate"] == 1.0            # + each call's "output"
    assert row["first_try_cite_rate"] == 1.0
    assert row["retrieve_call_count"] == 1
    assert row["retrieved_chunks_distinct"] == 1
    assert row["steps"] >= 1                       # the event stream
    assert row["cost_usd"] == pytest.approx(0.004)  # frame["usage"]["cost"]
    assert row["wall_ms"] is not None


def test_a_refusal_shaped_run_scores_as_a_refusal_through_the_real_seam(tmp_path):
    """The other half of the seam: an answer with no cite must reach the
    scorer AS a refusal. If `citations` were renamed upstream this test would
    still pass -- which is exactly why the citing test above exists as its
    pair. Kept because refusal correctness is scored from the same frame."""
    query = q(id="aq-r", shape="refusal", should_refuse=True, key_facts=[])
    provider = Provider(lambda: sse(
        text_chunk("That is outside this corpus."),
        finish_chunk("stop"),
        usage_chunk(prompt=100, completion=10, cost=0.001, cached=0)))

    def factory(_query, conv_id):
        return HarnessSession(
            conv_id, corpus=_query.corpus, tier=_query.tier, user="eval",
            settings=make_settings(), executor=FakeExecutor(),
            transport=provider.transport(), tools=[],
            system_prompt="eval test prompt",
        )

    run_suite([query], tmp_path, factory, progress=lambda *_: None)
    row = score_transcript(query, read_transcript(tmp_path / "aq-r-r1.jsonl"))
    assert row["ok"] is True
    assert row["refused"] is True
    assert row["refusal_correct"] is True
