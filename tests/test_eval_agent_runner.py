"""Runner tests — every model interaction is a canned MockTransport
response (tests/test_harness_session.py fakes), so this suite never
spends money and never touches the office ledger or settings.json.
"""
from __future__ import annotations

import json

import pytest

from eval.agent_schema import AgentQuery
from eval.agent_transcript import read_transcript
from eval.run_agent_eval import build_manifest, run_suite, select_queries
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
