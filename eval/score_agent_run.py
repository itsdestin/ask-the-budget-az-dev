"""Mechanical scorer CLI: score every transcript in a run directory.

Free and re-runnable: improving a metric means re-scoring historical
runs, never re-spending model tokens.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from eval.agent_schema import load_agent_queries
from eval.agent_scoring import aggregate, score_transcript
from eval.agent_transcript import read_transcript

DEFAULT_QUERIES = "eval/agent_queries.yaml"


def score_run(run_dir: Path, queries_file: str = DEFAULT_QUERIES) -> dict:
    queries = {q.id: q for q in load_agent_queries(queries_file)}
    rows = []
    skipped = []
    # The glob is `*-r*.jsonl` (one transcript per query+repeat); "ledger.jsonl"
    # cannot match it, so the explicit skip that used to sit here was dead code
    # pretending to guard something. Removed 2026-08 review, Finding 8.
    for path in sorted(run_dir.glob("*-r*.jsonl")):
        t = read_transcript(path)
        qid = t.meta.get("query_id")
        if qid not in queries:
            skipped.append(path.name)  # query removed since the run — say so
            continue
        rows.append(score_transcript(queries[qid], t))
    return {"summary": aggregate(rows), "per_query": rows, "skipped": skipped}


def _md(scores: dict, run_dir: Path) -> str:
    s = scores["summary"]
    lines = [f"# Agent-eval scores — {run_dir.name}", "", "## Summary", ""]
    for key, val in s.items():
        shown = f"{val:.4g}" if isinstance(val, float) else val
        lines.append(f"- **{key}**: {shown}")
    # Column names say exactly what they hold (2026-08 review, Finding 5):
    # "cite pass" is the pass rate over every attempt, "1st-try" is the share
    # of intended citations that landed on the first attempt. The old single
    # "1st-try" column showed the former under the latter's name.
    lines += ["", "## Per query", "",
              "| id | shape | ok | facts | cites ok | cite pass | 1st-try | "
              "retr eff | steps | cost |",
              "|---|---|---|---|---|---|---|---|---|---|"]
    for r in scores["per_query"]:
        def fmt(v):
            return "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else v)
        # WHY cost gets its own formatter (2026-08 review, Finding 4): real
        # Standard-tier per-query costs run roughly $0.002-$0.013, so the
        # generic 2-decimal `fmt` above rendered every single one as "0.00" --
        # cost per answer is one of the four things this harness exists to
        # measure, and a report where that column is always "0.00" is
        # useless for exactly the comparison it's meant to support.
        # scores.json is untouched -- this only changes the human-readable
        # scores.md rendering, not the stored data.
        def fmt_cost(v):
            return "—" if v is None else f"{v:.4f}"
        lines.append(
            f"| {r['query_id']} | {r['shape']} | {'✓' if r['ok'] else '✗'} "
            f"| {fmt(r['key_fact_rate'])} | {r['verified_citations']} "
            f"| {fmt(r['cite_pass_rate'])} | {fmt(r['first_try_cite_rate'])} "
            f"| {fmt(r['retrieval_efficiency'])} "
            f"| {r['steps']} | {fmt_cost(r['cost_usd'])} |")
    flagged = [r for r in scores["per_query"]
               if r.get("narration_hits") or r.get("token_leak") or r.get("false_refusal")]
    if flagged:
        lines += ["", "## Hygiene flags", ""]
        for r in flagged:
            notes = []
            if r.get("narration_hits"):
                notes.append(f"narration x{r['narration_hits']}")
            if r.get("token_leak"):
                notes.append("TOKEN LEAK")
            if r.get("false_refusal"):
                notes.append("false refusal")
            lines.append(f"- {r['query_id']}: {', '.join(notes)}")
    if scores["skipped"]:
        lines += ["", f"Skipped (query no longer in set): {', '.join(scores['skipped'])}"]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--queries-file", default=DEFAULT_QUERIES)
    args = parser.parse_args()

    scores = score_run(args.run_dir, args.queries_file)
    tmp = (args.run_dir / "scores.json").with_suffix(".json.tmp")
    tmp.write_text(json.dumps(scores, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(args.run_dir / "scores.json")
    (args.run_dir / "scores.md").write_text(_md(scores, args.run_dir), encoding="utf-8")
    print(json.dumps(scores["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
