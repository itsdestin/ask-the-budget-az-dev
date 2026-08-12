"""Layer 2 agent-loop eval runner.

Drives the REAL harness session per query — the production code path,
no HTTP server — and records one JSONL transcript per (query, repeat)
under eval/results/agent/<UTC>-<sha>/. This is the only money-spending
tool in the Layer 2 suite; scoring and judging read the transcripts.

Isolation guarantees (spec 'Decisions' #5 and Global Constraints):
- check_limit is a stub returning "allowed" — an eval run must not be
  blocked by, nor count against, office S19 limits.
- record_usage appends to the RUN's own ledger.jsonl, never the office
  spend ledger on the share.
- settings are loaded once and passed explicitly; nothing re-reads
  settings.json mid-run.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import dataclasses
import hashlib
import json
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eval.agent_schema import AgentQuery, load_agent_queries
from eval.agent_transcript import write_transcript
from harness.ledger import LimitStatus
from harness.session import reset_model_overrides
from harness.settings import Settings, TierConfig, ai_available, load_settings

DEFAULT_QUERIES = "eval/agent_queries.yaml"
DEFAULT_RESULTS_DIR = "eval/results/agent"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


def _allow_all(user: str, settings: Any, *, now: Any = None) -> LimitStatus:
    """Spend-gate stub: eval runs are pre-authorized by the human who
    started them; the S19 office limit must neither block nor accrue."""
    return LimitStatus(status="allowed", message=None, reason=None,
                       limit_usd=None, month_usd=None)


def make_usage_recorder(run_dir: Path) -> Callable[..., None]:
    """A record_usage-compatible callable that writes per-step rows into
    the run directory instead of the office ledger.

    WHY the lock: with `--workers > 1` several sessions' `_bill` paths
    append to the SAME ledger.jsonl from different threads, and two
    interleaved `open(path, "a")` writes could splice their lines
    (one thread's flush landing inside another's write). The office
    ledger has the same lock (harness/ledger.py `_write_lock`); this runs
    its own so a parallel eval's spend record stays one JSON object per
    line — the row shape scorer/ledger readers expect.
    """
    path = run_dir / "ledger.jsonl"
    write_lock = threading.Lock()

    def record(user: str, tier: str, model: str, tokens_in: int, tokens_out: int,
               cost_usd: float | None = None, *, cached_tokens: int = 0,
               now: Any = None) -> None:
        row = {"user": user, "tier": tier, "model": model,
               "tokens_in": tokens_in, "tokens_out": tokens_out,
               "cost_usd": cost_usd, "cached_tokens": cached_tokens,
               "timestamp": datetime.now(timezone.utc).isoformat()}
        with write_lock:
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return record


def make_session_factory(settings: Settings, run_dir: Path):
    # Per corpus, built once per RUN rather than once per query: the map is
    # a pure function of the sidecar, the run does not ingest, and rebuilding
    # it 31 times would only add noise to the wall-clock numbers.
    maps: dict[str, str | None] = {}

    def corpus_map(corpus: str) -> str | None:
        if corpus not in maps:
            try:
                from harness.corpus_map import build_corpus_map

                maps[corpus] = build_corpus_map(corpus)
            except Exception as err:  # noqa: BLE001 — mirrors the route's degrade
                print(f"eval: corpus map unavailable — {err}", file=sys.stderr)
                maps[corpus] = None
        return maps[corpus]

    def factory(query: AgentQuery, conv_id: str):
        # Import here so the module stays importable (and testable)
        # without the ONNX/LanceDB stack loaded.
        from harness.session import HarnessSession

        return HarnessSession(
            conv_id, corpus=query.corpus, tier=query.tier, user="eval",
            settings=settings,
            check_limit=_allow_all,
            record_usage=make_usage_recorder(run_dir),
            # Spec N1/N3. The Layer 2 run MUST exercise the map, or gate
            # G-N2 measures a prompt the office will never see.
            corpus_map=corpus_map(query.corpus),
        )
    return factory


def select_queries(queries: list[AgentQuery], subset: str,
                   ids: list[str] | None) -> list[AgentQuery]:
    picked = [q for q in queries if subset in q.subsets]
    if ids:
        wanted = set(ids)
        picked = [q for q in picked if q.id in wanted]
    return picked


def query_set_sha256(queries: list[AgentQuery]) -> str:
    """Content hash of the queries this run actually asked.

    WHY the manifest's `queries` id list is not enough (2026-08 review,
    Finding 2): it catches a run that dropped or added a query, but it is
    byte-identical when somebody EDITS a query — rewords the question, fixes a
    key fact — between two `full` runs. `compare_agent_runs.py` would then
    report the whole authoring delta as a change in the system under test,
    with nothing on the page saying otherwise. Hashing the loaded models (not
    the YAML file's bytes) means a comment or a reordering does NOT trip the
    guard, while any change to what is actually measured does.

    Sorted by id so file order never enters the hash.
    """
    payload = json.dumps(
        [q.model_dump(mode="json") for q in sorted(queries, key=lambda q: q.id)],
        sort_keys=True, ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_manifest(settings: Settings, queries: list[AgentQuery], *,
                   subset: str, repeats: int, results_note: str = "") -> dict[str, Any]:
    """Everything needed to know what a run measured. The spec's rule:
    no two runs are ever compared without knowing what differed."""
    prompt_path = Path(__file__).resolve().parent.parent / "harness" / "system-prompt.md"
    try:
        prompt_sha = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    except OSError:
        prompt_sha = "unknown"
    counts: dict[str, Any] = {}
    try:
        from store.chunk_store import ChunkStore

        store = ChunkStore()
        for table in ("budget_chunks", "fiscal_note_chunks"):
            counts[table] = store.count(table)
    except Exception as exc:  # tests run without a corpus; record why
        counts = {"error": f"{type(exc).__name__}: {exc}"}
    return {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ"),
        "git_sha": _git_sha(),
        "subset": subset,
        "repeats": repeats,
        "queries": [q.id for q in queries],
        "queries_sha256": query_set_sha256(queries),
        "tier_models": {name: cfg.model for name, cfg in settings.tiers.items()},
        "provider": settings.provider.provider,
        "base_url": settings.provider.base_url,
        "api_key_set": bool(settings.provider.api_key),
        "prompt_sha256": prompt_sha,
        "corpus_counts": counts,
        "note": results_note,
    }


def _worklist(queries: list[AgentQuery], *, repeats: int) -> list[tuple[AgentQuery, int]]:
    """[(query, repeat)] in deterministic (id, repeat) order.

    Kept separate from run_suite so the parallel executor has a plain
    list to map over, and so the serial path (workers=1) iterates in the
    exact same order it always did — result files and run_suite's
    per-query semantics are unchanged by parallelization.
    """
    return [(q, rep) for q in queries for rep in range(1, repeats + 1)]


def _run_one_workitem(item, run_dir: Path, session_factory) -> None:
    """Run one (query, repeat) and write its transcript, its OWN ledger,
    and its progress line.

    The whole body is a self-contained unit so it can run on any worker
    thread. `reset_model_overrides()` runs inside here, per query — the
    S13 fallback map is lock-guarded per operation, so a concurrent
    query resetting it while another reads an effective model is safe
    (each transition is atomic under the lock). See run_suite.
    """
    query, rep = item
    # A transient S13 model fallback during query N must not
    # silently re-model queries N+1..: reset before every query. Even
    # with several queries in flight, each resets once at its own start,
    # and every read/write of the fallback map is under _fallback_lock.
    reset_model_overrides()
    conv_id = f"eval-{query.id}-r{rep}"
    path = run_dir / f"{query.id}-r{rep}.jsonl"
    meta = {"query_id": query.id, "repeat": rep,
            "corpus": query.corpus, "tier": query.tier,
            "shape": query.shape,
            "started_at": datetime.now(timezone.utc).isoformat()}
    events: list[dict[str, Any]] = []
    session = None
    start = time.monotonic()
    try:
        session = session_factory(query, conv_id)
        frame = session.send_turn(query.question, events.append)
    except Exception as exc:
        # One bad query must never abort the run (Layer 1 rule).
        frame = {"type": "_error",
                 "message": f"{type(exc).__name__}: {exc}"}
    finally:
        if session is not None:
            try:
                session.close()
            except Exception as exc:
                # Swallowing this silently (the old behavior) leaves no
                # trace of a leaked HTTP client/file handle, which then
                # surfaces dozens of queries later as an unrelated-looking
                # failure with nothing to point back at the real cause.
                # House style (harness/session.py's ledger-write path):
                # print a diagnostic and keep going, never re-raise.
                print(f"eval.run_agent_eval: session.close() failed for "
                      f"{query.id} r{rep} ({type(exc).__name__}: {exc}); "
                      "continuing (a leaked client/handle may surface "
                      "later as an unrelated failure).", file=sys.stderr)
    elapsed_ms = int((time.monotonic() - start) * 1000)
    # write_transcript and progress used to run OUTSIDE any per-query
    # guard, so a transient failure here (this project has documented
    # write flakiness on the shared network drive) escaped run_suite
    # entirely and killed the whole multi-hour paid run. Each gets its
    # own try/except so a failure costs only THIS query's record —
    # reported loudly (never silently) so a missing transcript is never
    # mistaken for a query that simply wasn't run.
    try:
        write_transcript(path, meta, events,
                         {"frame": frame, "wall_ms": elapsed_ms})
    except Exception as exc:
        print(f"eval.run_agent_eval: FAILED to write transcript for "
              f"{query.id} r{rep} ({type(exc).__name__}: {exc}) — this "
              "query's result is LOST; continuing with the rest of the "
              "run.", file=sys.stderr)
    status = frame.get("type", "?")
    cost = (frame.get("usage") or {}).get("cost")
    try:
        _PROGRESS_LOCK.acquire()
        try:
            print(f"{query.id} r{rep}: {status} "
                  f"({elapsed_ms / 1000:.0f}s, cost={cost})")
        finally:
            _PROGRESS_LOCK.release()
    except Exception as exc:
        print(f"eval.run_agent_eval: progress callback failed for "
              f"{query.id} r{rep} ({type(exc).__name__}: {exc}); "
              "continuing.", file=sys.stderr)


# Serializes the per-query progress lines that a parallel run prints.
# Without it two worker threads can interleave their writes mid-line and
# produce a garbled "aq-001 r1: _doneaq-002 r1: _done" — harmless to the
# artifacts but unreadable to the human watching the run.
_PROGRESS_LOCK = threading.Lock()


def run_suite(queries: list[AgentQuery], run_dir: Path,
              session_factory: Callable[[AgentQuery, str], Any], *,
              repeats: int = 1, progress: Callable[[str], Any] = print,
              workers: int = 1) -> None:
    """Run every (query, repeat) and write one transcript each.

    `workers`: how many queries run CONCURRENTLY. Default 1 (serial, the
    long-standing behaviour). In production this parallelizes the paid
    OpenRouter calls so model latency overlaps instead of stacking — see
    the orchestrator for why threads, not processes.

    Each work item runs on its own worker thread with its OWN
    `HarnessSession` (the session_factory builds one per query, and a
    session's tools/executor/progressive-retrieval cap are instance
    state by design), its own httpx client, and its own ledger rows.
    The process-wide singletons (ChunkStore, ONNX embedder/reranker) are
    shared just as they are across the office's concurrent analysts —
    the pipeline's ORT sessions are declared thread-safe to use, only
    construction races, and that construction is already lock-guarded.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    items = _worklist(queries, repeats=repeats)
    # The old runner threaded a `progress` callback through. Tests pass a
    # no-op callback simply to suppress output; the worker path prints under
    # the progress lock instead. A caller that genuinely needs the callback
    # (none in-tree) is handled by the serial path below, which calls it the
    # way it always did.
    if progress is not print:
        for item in items:
            _run_one_workitem(item, run_dir, session_factory)
            progress(f"{item[0].id} r{item[1]}")
        return
    if workers <= 1:
        for item in items:
            _run_one_workitem(item, run_dir, session_factory)
        return
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(lambda item: _run_one_workitem(item, run_dir, session_factory), items))


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="Layer 2 agent-loop eval runner (spends real money)")
    parser.add_argument("--queries-file", default=DEFAULT_QUERIES)
    parser.add_argument("--subset", default="smoke", choices=("smoke", "full", "dr-probe"))
    parser.add_argument("--queries", nargs="*", default=None, help="restrict to these query ids")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--model", default=None,
                        help="pin the standard-tier model for this run (overrides settings)")
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR)
    parser.add_argument("--run-dir", default=None,
                        help="use this exact run directory name (under "
                             "--results-dir) instead of auto-generating a "
                             "<UTC-ISO>-<sha> name. Lets the orchestrator pin "
                             "a directory it can find again without guessing "
                             "which one was just created.")
    parser.add_argument("--workers", type=int, default=1,
                        help="queries to run concurrently (parallel OpenRouter "
                             "calls; default 1 = serial, the historical "
                             "behaviour).",
                        )
    parser.add_argument("--note", default="", help="free-text note recorded in the manifest")
    args = parser.parse_args()

    settings = load_settings()
    if args.model:
        # Frozen dataclass — build a modified copy, never touch disk.
        tiers = dict(settings.tiers)
        tiers["standard"] = TierConfig(model=args.model, enabled=True)
        settings = dataclasses.replace(settings, tiers=tiers)

    queries = select_queries(load_agent_queries(args.queries_file),
                             args.subset, args.queries)
    if not queries:
        print("no queries selected", file=sys.stderr)
        return 2
    needed_tiers = {q.tier for q in queries}
    for tier in sorted(needed_tiers):
        ok, reason = ai_available(settings, tier)
        if not ok:
            print(f"AI Mode unavailable for tier {tier}: {reason}", file=sys.stderr)
            return 2

    run_dir = (
        Path(args.results_dir) / args.run_dir
        if args.run_dir else
        Path(args.results_dir) / f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}-{_git_sha()}"
    )
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(settings, queries, subset=args.subset,
                              repeats=args.repeats, results_note=args.note)
    tmp = (run_dir / "manifest.json").with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(run_dir / "manifest.json")

    print(f"run dir: {run_dir}  ({len(queries)} queries x {args.repeats}, "
          f"workers={args.workers})")
    run_suite(queries, run_dir, make_session_factory(settings, run_dir),
              repeats=args.repeats, workers=args.workers)
    print(f"done. next: uv run python -m eval.score_agent_run {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
