"""Tests for eval/run_full_layer2.py — the one-shot Layer 2 orchestrator.

subprocess.run is mocked so these tests never spend money or touch a
network. They assert the orchestration shape: the three steps run (or
the judge is skipped), in order, against a pinned run dir, with
--workers passed through to both paid tools.
"""
from __future__ import annotations

import sys

import eval.run_full_layer2 as orch


class _Proc:
    def __init__(self, rc=0):
        self.returncode = rc


def _call_main(monkeypatch, argv, *, fail_step=None):
    """Drive main() with _run_step stubbed so nothing shells out/makes a
    network call. Records every step's arg list in the order they'd run."""
    calls = []
    monkeypatch.setattr(orch, "_git_sha", lambda: "abc1234")
    monkeypatch.setattr(sys, "argv", ["orch", *argv])

    # fail_step is matched against the MODULE name in the argv (e.g.
    # "eval.run_agent_eval"), since the step's human label is separate.
    def fake_run_step(name, argv):
        calls.append(list(argv))
        joined = " ".join(argv)
        return 2 if fail_step and fail_step in joined else 0

    monkeypatch.setattr(orch, "_run_step", fake_run_step)
    rc = orch.main()
    return rc, calls


def test_orchestrator_runs_run_score_judge_report_in_order(monkeypatch):
    rc, calls = _call_main(
        monkeypatch, ["--sets", "smoke", "--workers", "4"])
    assert rc == 0
    assert len(calls) == 4
    # 1) run, 2) score, 3) judge, 4) report — in that order.
    assert "eval.run_agent_eval" in calls[0]
    assert "eval.score_agent_run" in calls[1]
    assert "eval.judge_agent_run" in calls[2]
    assert "eval.report_bundle" in calls[3]
    # --workers is threaded into both the run and the judge.
    assert "--workers" in calls[0] and "4" in calls[0]
    assert "--workers" in calls[2] and "4" in calls[2]
    # The run pins a deterministic run-dir name.
    run_argv = calls[0]
    rd_idx = run_argv.index("--run-dir")
    pinned = run_argv[rd_idx + 1]
    assert pinned.startswith("20")  # <UTC-ISO>-<sha>


def test_orchestrator_skip_judge_still_reports(monkeypatch):
    rc, calls = _call_main(monkeypatch, ["--skip-judge", "--sets", "smoke"])
    assert rc == 0
    assert len(calls) == 3  # run, score, report
    assert "eval.run_agent_eval" in calls[0]
    assert "eval.score_agent_run" in calls[1]
    assert "eval.report_bundle" in calls[2]
    assert not any("eval.judge_agent_run" in c for c in calls)


def test_orchestrator_stops_on_run_failure(monkeypatch):
    # The live agent run exits non-zero -> the wrapper stops, no score/judge.
    rc, calls = _call_main(monkeypatch, ["--sets", "full"], fail_step="run_agent_eval")
    assert rc == 2
    assert len(calls) == 1  # only the failed run step fired
    assert "eval.run_agent_eval" in calls[0]


def test_orchestrator_sets_is_forwarded_to_the_run(monkeypatch):
    # 2026-08-16 consolidation: --sets is the only selection axis forwarded
    # to run_agent_eval (the retired --subset flag is gone entirely).
    rc, calls = _call_main(
        monkeypatch, ["--sets", "quick,multi"])
    assert rc == 0
    run_argv = calls[0]
    assert run_argv[run_argv.index("--sets") + 1] == "quick,multi"
    assert "--subset" not in run_argv


def test_orchestrator_forwards_model_and_judge_model(monkeypatch):
    rc, calls = _call_main(
        monkeypatch,
        ["--sets", "smoke", "--model", "m1", "--judge-model", "m2",
         "--no-reasoning"])
    assert rc == 0
    run_argv = calls[0]
    assert run_argv[run_argv.index("--model") + 1] == "m1"
    judge_argv = calls[2]
    assert judge_argv[judge_argv.index("--judge-model") + 1] == "m2"
    assert "--no-reasoning" in judge_argv
