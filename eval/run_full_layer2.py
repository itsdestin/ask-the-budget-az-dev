"""One-shot Layer 2 orchestrator — run → score → judge in a single call.

This is the easy re-runnable entry point the workflow has been wanting:
instead of remembering three commands in README order, run:

    uv run python -m eval.run_full_layer2 --sets quick,multi,refusal

and it drives the SAME tools the README documents (run_agent_eval,
score_agent_run, judge_agent_run) as subprocesses, so the on-disk
artifacts (manifest.json, transcripts, ledger.jsonl, scores.json,
scores.md, judge.json) are byte-for-byte what running each step by hand
produces. It does not reimplement any of them.

Parallelism is passed straight through: `--workers` becomes run_agent_eval's
`--workers` (concurrent agent queries) and judge_agent_run's `--workers`
(concurrent judge calls). The mechanical scorer is inherently fast, so it
is always serial; nothing to fan out there.

Why a wrapper that shells out rather than importing/calling the mains
in-process: each tool is a self-contained CLI with its own argparse and
its own stdout reconfiguration, and the runner deliberately spawns a
whole paid run in its own process (a crash or Ctrl-C there must not take
down a subsequent judge step that shares the interpreter). Subprocess
also gives each step a clean exit code so the orchestrator can stop at
the first real failure and tell you which step it was.

Guardrails inherited from the individual tools, so this wrapper adds
nothing on top: the runner refuses to start when AI Mode is unavailable
for a needed tier, the judge refuses with no API key, and
compare_agent_runs (used manually) refuses to diff incomparable runs.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_RESULTS_DIR = "eval/results/agent"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _run_step(name: str, argv: list[str]) -> int:
    print(f"\n=== {name} ===", flush=True)
    proc = subprocess.run(argv)
    if proc.returncode != 0:
        print(f"ERROR: {name} exited {proc.returncode}", file=sys.stderr)
        return proc.returncode
    return 0


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass  # Non-stream stdout (e.g. captured in tests) lacks reconfigure

    parser = argparse.ArgumentParser(
        prog="eval.run_full_layer2",
        description="Run Layer 2 end-to-end: live agent run, then score, then judge.",
    )
    parser.add_argument("--queries-file", default="eval/agent_queries.yaml")
    parser.add_argument("--sets", default="quick,multi,deep,refusal",
                        help="comma-separated sets to run "
                             "(quick,multi,deep,refusal; deep excludes for "
                             "cheap iterations). The retired --subset flag is "
                             "gone (2026-08-16 re-tag).")
    parser.add_argument("--queries", nargs="*", default=None,
                        help="restrict to these query ids (passed through)")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--workers", type=int, default=1,
                        help="queries (and judge calls) to run concurrently. "
                             "Passed to both run_agent_eval and judge_agent_run.")
    parser.add_argument("--model", default=None,
                        help="pin the standard-tier model (passed through)")
    parser.add_argument("--judge-model", default=None,
                        help="judge model (default: judge_agent_run's default)")
    parser.add_argument("--no-reasoning", action="store_true",
                        help="ask the judge to skip chain-of-thought")
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--note", default="",
                        help="free-text note recorded in the run's manifest")
    parser.add_argument("--skip-judge", action="store_true",
                        help="run + score only (a full run is judged by default; "
                             "the judge is a second, separate charge).")
    args = parser.parse_args()

    base = [sys.executable, "-m"]

    # One deterministic run directory, pinned up front so the wrapper can
    # find it after run_agent_eval without scanning for "the newest dir" —
    # that heuristic is fragile the moment a previous run dir sits there.
    run_dir = Path(args.results_dir) / (
        f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}-{_git_sha()}"
    )

    run_argv = [
        *base, "eval.run_agent_eval",
        "--queries-file", args.queries_file,
        "--sets", args.sets,
        "--results-dir", args.results_dir,
        "--run-dir", run_dir.name,
        "--workers", str(args.workers),
        "--note", args.note,
    ]
    if args.queries:
        run_argv += ["--queries", *args.queries]
    if args.repeats != 1:
        run_argv += ["--repeats", str(args.repeats)]
    if args.model:
        run_argv += ["--model", args.model]

    rc = _run_step("live agent run (spends money)", run_argv)
    if rc != 0:
        return rc

    print(f"run dir: {run_dir}", flush=True)

    rc = _run_step("score (free)", [*base, "eval.score_agent_run", str(run_dir),
                                    "--queries-file", args.queries_file])
    if rc != 0:
        return rc

    if not args.skip_judge:
        judge_argv = [
            *base, "eval.judge_agent_run", str(run_dir),
            "--queries-file", args.queries_file,
            "--workers", str(args.workers),
        ]
        if args.judge_model:
            judge_argv += ["--judge-model", args.judge_model]
        if args.no_reasoning:
            judge_argv += ["--no-reasoning"]
        rc = _run_step("judge (spends money)", judge_argv)
        if rc != 0:
            return rc

    print(f"\nDone. Reports report/scores in {run_dir}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
