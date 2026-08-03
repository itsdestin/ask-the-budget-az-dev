"""Defend mechanism for Layer 2 agent-eval transcripts.

When a query scores poorly on the mechanical scorer, or the LLM judge
hands it a bad ranking, a human may legitimately want to see the model
DEFEND its output. The defense often reveals a faulty EVAL rather than a
bad model — a checked fact that was actually present, a citation that
genuinely supported a claim — which is exactly the kind of discovery this
project's "refusal beats hallucination / audit the claim" ethos wants
caught early instead of shipped as a regression.

This tool:

  1. reads a finished agent-eval run's transcript(s),
  2. composes the evaluation's feedback for that query — from
     scores.json (missed key facts, hygiene flags, refusal correctness)
     and/or judge.json (holistic grade, rationale, uncovered claims),
     or an explicit `--feedback` string,
  3. drives a FRESH HarnessSession (the production code path, same as
     run_agent_eval) whose question embeds the original question, the
     original answer, and the feedback, asking the model to justify or
     amend,
  4. writes the defense as a normal per-query transcript (with its own
     isolated ledger) under eval/results/agent/defend/<UTC>-<sha>/, so
     it is re-readable and comparable like any other transcript.

It does NOT re-score the defense mechanically: a defense has no clean
key-fact target, and re-scoring it would read as a second "result" with a
misleading number. The deliverable is the justification itself, for a
human to judge.

Isolation is inherited from run_agent_eval: every defense session bills
into ITS OWN ledger.jsonl (never the office ledger), model overrides are
reset per query, and one bad query never aborts the rest.
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from eval.agent_schema import AgentQuery, load_agent_queries
from eval.agent_transcript import final_answer, read_transcript
from eval import run_agent_eval
from harness.settings import Settings, TierConfig

DEFAULT_QUERIES = "eval/agent_queries.yaml"
DEFAULT_RESULTS_DIR = "eval/results/agent/defend"


def _git_sha() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True
        ).strip()
    except (subprocess.CalledProcessError, OSError):
        return "unknown"


# ---------------------------------------------------------------------------
# Feedback composition (pure, testable): turn scores/judge rows into prose
# ---------------------------------------------------------------------------


def _load_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _scores_table(run_dir: Path) -> dict[str, dict[str, Any]]:
    data = _load_json(run_dir / "scores.json")
    rows = (data or {}).get("per_query") or []
    return {r.get("query_id"): r for r in rows if isinstance(r, dict)}


def _judge_table(run_dir: Path) -> dict[str, dict[str, Any]]:
    data = _load_json(run_dir / "judge.json")
    rows = (data or {}).get("per_query") or []
    return {r.get("query_id"): r for r in rows if isinstance(r, dict)}


def brief_feedback(query: AgentQuery, *, scores: dict[str, Any] | None = None,
                   judge: dict[str, Any] | None = None,
                   explicit: str | None = None) -> str:
    """Compose the criticism handed to the model.

    `explicit` (an operator-typed --feedback) wins outright; otherwise the
    feedback is built from whatever scores/judge rows exist, so a human
    does not have to retype what the harness already measured. Every line
    is phrased neutrally — 'the evaluator says X' — so the model can push
    back instead of being pushed to grovel.
    """
    if explicit:
        return explicit

    parts: list[str] = []
    if scores:
        parts.append("Mechanical scoring found:")
        if scores.get("key_facts_total"):
            got = scores.get("key_facts_matched", 0)
            total = scores["key_facts_total"]
            parts.append(
                f"- {got} of {total} required key facts were found in the "
                "answer."
            )
            if got < total:
                parts.append(
                    "- The answer was judged to be missing some key facts."
                )
        fr = scores.get("false_refusal")
        if fr is not None and fr:
            parts.append("- The answer refused but the query expected an answer.")
        if scores.get("narration_hits"):
            parts.append(f"- {scores['narration_hits']} narration/process phrases "
                         "leaked into the answer.")
        if scores.get("token_leak"):
            parts.append("- The answer contained a download token.")
        if scores.get("internal_vocab_hits"):
            parts.append("- The answer contained internal/vocabulary phrases.")

    if judge:
        holistic = judge.get("holistic")
        if isinstance(holistic, (int, float)):
            parts.append(f"The LLM judge gave the answer {holistic}/5.")
        rationale = judge.get("rationale")
        if isinstance(rationale, str) and rationale:
            parts.append(f"The judge's rationale: {rationale}")
        # Judge returns its claims as load_bearing_claims; flag uncovered ones.
        claims = judge.get("load_bearing_claims") or []
        uncovered = [
            c.get("claim")
            for c in claims
            if isinstance(c, dict) and not c.get("cited_verified")
        ]
        if uncovered:
            parts.append("The judge listed these claims as NOT backed by a "
                         "verified citation:")
            for c in uncovered:
                parts.append(f"- {c}")

    return "\n".join(parts) if parts else (
        "No specific mechanical or judge feedback is available; defend the "
        "correctness of your answer on the merits."
    )


def build_defense_question(query: AgentQuery, answer: str, feedback: str) -> str:
    """The prompt handed to the fresh session: original task + original
    answer + the evaluation's feedback + an invitation to defend or amend.

    The model has none of its prior context except what is embedded here,
    so it cannot invent false parroting — it must reason from the recorded
    answer and the criticism, and can (re)call retrieve/cite to ground it.
    """
    return (
        "You are being asked to DEFEND or REVISE a prior answer that an "
        "evaluation judged as weak.\n\n"
        f"ORIGINAL QUESTION: {query.question}\n\n"
        f"YOUR PREVIOUS ANSWER WAS:\n\n{answer}\n\n"
        f"THE EVALUATOR'S FEEDBACK:\n\n{feedback}\n\n"
        "Please respond by defending your output. Explain the reasoning "
        "and evidence behind each claim, and how the source pass"
        "ages you cited support it. "
        "If the feedback is MISTAKEN — a checked fact really is in your "
        "answer, or a citation genuinely supports a claim the evaluator "
        "said was uncovered — point that out concretely, quoting the "
        "supporting text and citing it. "
        "If the feedback is fair, acknowledge the shortcoming and say "
        "precisely what would make the answer better. Be specific. "
        "Use retrieve/cite to ground anything you assert."
    )


def build_defense_query(query: AgentQuery, answer: str, feedback: str) -> AgentQuery:
    """A defense is a new, unscored query carrying the defense prompt.

    key_facts is deliberately empty (a defense is not mechanically
    scored against the original facts), subsets is its own tag, and
    corpus/tier/shape carry over so the defense runs on the same stack
    the original did.
    """
    return AgentQuery(
        id=f"{query.id}-defend",
        question=build_defense_question(query, answer, feedback),
        corpus=query.corpus,
        tier=query.tier,
        shape="analyze",
        subsets=["defend"],
        should_refuse=False,
        key_facts=[],
        judge_notes="defense of a poorly-scored answer; read the rationale, do not re-score.",
    )


# ---------------------------------------------------------------------------
# Target selection
# ---------------------------------------------------------------------------


def select_targets(run_dir: Path, queries_yaml: str, *, query_ids: list[str],
                   all_poorly: bool) -> list[AgentQuery]:
    """The original AgentQuery records to defend.

    By explicit id (must exist in the transcript set), or --all-poorly
    (every query that scored <100% key-fact rate, or had a hygiene flag,
    or a bad judge score). Raises ValueError if a named id is absent from
    the run, so a typo never silently defends nothing.
    """
    run_dir = Path(run_dir)  # main() passes args.run_dir, a str
    all_q = {q.id: q for q in load_agent_queries(queries_yaml)}
    # Map "<query_id>-r<repeat>.jsonl" -> query_id (strip the -rN suffix),
    # so a named target is matched by id and not by its filename stem.
    transcripts = {}
    for p in run_dir.glob("*-r*.jsonl"):
        stem = p.stem
        # repeated-query files are "<id>-r<N>"; the id never contains "-r"
        rpos = stem.rfind("-r")
        if rpos != -1:
            transcripts[stem[:rpos]] = p
        else:
            transcripts[stem] = p

    if not query_ids and not all_poorly:
        raise ValueError(
            "pass --queries <id>... to defend specific queries, or --all-poorly "
            "to defend every weakly-scored one."
        )

    scores_tab = _scores_table(run_dir)
    judge_tab = _judge_table(run_dir)

    picked: list[AgentQuery] = []
    for qid in (query_ids or []):
        if qid not in transcripts:
            raise ValueError(f"{qid}: no transcript '<id>-r*.jsonl' in {run_dir}")
        if qid not in all_q:
            raise ValueError(f"{qid}: no such query in {queries_yaml}")
        picked.append(all_q[qid])

    if all_poorly:
        for qid, q in all_q.items():
            if qid not in transcripts:
                continue
            s = scores_tab.get(qid, {})
            j = judge_tab.get(qid, {})
            kf = s.get("key_fact_rate")
            poorly = (
                (kf is not None and kf < 1.0)
                or bool(s.get("narration_hits"))
                or bool(s.get("token_leak"))
                or bool(s.get("false_refusal"))
                or (isinstance(j.get("holistic"), (int, float))
                    and j["holistic"] < 4)
            )
            if poorly:
                picked.append(q)

    # Deterministic order, dedupe.
    seen: set[str] = set()
    out = []
    for q in sorted(picked, key=lambda q: q.id):
        if q.id in seen:
            continue
        seen.add(q.id)
        out.append(q)
    return out


# ---------------------------------------------------------------------------
# Running
# ---------------------------------------------------------------------------


def build_defense_set(source_run_dir: Path, targets: list[AgentQuery]) -> list[AgentQuery]:
    """Build the actual AgentQuery records to run, one per target, with
    the feedback composed from the source run's scores/judge."""
    scores_tab = _scores_table(source_run_dir)
    judge_tab = _judge_table(source_run_dir)
    defense_queries: list[AgentQuery] = []
    for q in targets:
        t = _read_first_transcript(source_run_dir, q.id)
        answer = final_answer(t)
        feedback = brief_feedback(
            q, scores=scores_tab.get(q.id), judge=judge_tab.get(q.id)
        )
        defense_queries.append(build_defense_query(q, answer, feedback))
    return defense_queries


def _read_first_transcript(run_dir: Path, qid: str):
    """The r1 transcript for a target (the run's first repeat)."""
    path = run_dir / f"{qid}-r1.jsonl"
    if not path.exists():
        raise ValueError(f"{qid}: no {path.name} in {run_dir}")
    return read_transcript(path)


def run_defenses(defense_queries: list[AgentQuery], run_dir: Path, settings: Settings,
                 *, workers: int = 1,
                 session_factory: Callable | None = None) -> None:
    """Drive one defense session per target, reusing run_agent_eval's
    run_suite so every guarantee transfers: isolated ledger (each defense
    run dir has its own), a model-override reset per query, one bad query
    never aborts the rest, and one transcript per defense.

    `session_factory` is injectable the way run_suite's is — tests pass a
    factory wired to a fake transport; production defaults to the real
    session factory.
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    if session_factory is None:
        session_factory = run_agent_eval.make_session_factory(settings, run_dir)
    run_agent_eval.run_suite(
        defense_queries, run_dir, session_factory,
        workers=workers,
    )


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Generate model DEFENSES of weakly-scored agent-eval "
                    "transcripts (spends real money)."
    )
    parser.add_argument("run_dir", type=Path,
                        help="the agent-eval run directory whose transcripts "
                             "to defend")
    parser.add_argument("--queries-file", default=DEFAULT_QUERIES)
    parser.add_argument("--results-dir", default=DEFAULT_RESULTS_DIR,
                        help="where defense run dirs are written")
    parser.add_argument("--out-dir", default=None,
                        help="exact defense output dir name under --results-dir "
                             "(default: auto <UTC-ISO>-<sha>)")
    parser.add_argument("--queries", nargs="*", default=None,
                        help="defend only these query ids (required unless "
                             "--all-poorly)")
    parser.add_argument("--all-poorly", action="store_true",
                        help="defend every query that scored below 100%% "
                             "key-fact rate, or flagged, or judged <4/5")
    parser.add_argument("--feedback", default=None,
                        help="replace composed feedback with this exact "
                             "criticism for all targets")
    parser.add_argument("--model", default=None,
                        help="pin the standard-tier model (overrides settings)")
    parser.add_argument("--workers", type=int, default=1,
                        help="defenses to run concurrently (parallel "
                             "OpenRouter calls)")
    args = parser.parse_args()

    # Same loader run_agent_eval.main() uses.
    from harness.settings import load_settings
    settings = load_settings()
    if args.model:
        tiers = dict(settings.tiers)
        tiers["standard"] = TierConfig(model=args.model, enabled=True)
        settings = dataclasses.replace(settings, tiers=tiers)

    from harness.settings import ai_available

    targets = select_targets(args.run_dir, args.queries_file,
                             query_ids=args.queries or [],
                             all_poorly=args.all_poorly)
    if not targets:
        print("no targets selected — nothing to defend", file=sys.stderr)
        return 2

    for tier in sorted({q.tier for q in targets}):
        ok, reason = ai_available(settings, tier)
        if not ok:
            print(f"AI Mode unavailable for tier {tier}: {reason}",
                  file=sys.stderr)
            return 2

    if args.feedback:
        defense_queries = [
            build_defense_query(q, final_answer(_read_first_transcript(args.run_dir, q.id)),
                                args.feedback)
            for q in targets
        ]
    else:
        defense_queries = build_defense_set(args.run_dir, targets)

    dest = Path(args.results_dir)
    run_dir = (
        dest / args.out_dir
        if args.out_dir else
        dest / f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}-{_git_sha()}"
    )

    run_defenses(defense_queries, run_dir, settings, workers=args.workers)
    print(f"\nDefenses written to {run_dir}", flush=True)
    print("Read each <query-id>-defend-r1.jsonl transcript to review the "
          "model's justification.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
