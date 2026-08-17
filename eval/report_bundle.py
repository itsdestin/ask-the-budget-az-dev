"""Assemble a run directory into a reviewable report bundle.

Turns eval/results/agent/<run>/ (raw transcripts + scores + judge) into
eval/results/agent/<run>/report/ with:

    00-summary.md          the combined per-query table (all output metrics)
    01-errors.md           the tool-error ledger, readable
    per-query/<id>.md      one file per query: the full readable transcript
                           (every turn: what it thought, what it searched,
                           what it cited) + the judge review + final answer
    per-query/<id>.jsonl   a copy of the raw transcript for the exact record
    raw/                   copies of scores.json, judge.json, manifest.json

WHY this exists: the run dir holds everything but in raw, scattered forms.
Destin wants ONE folder he can open and review — a table of every metric,
the full conversation for each query, and the judge's verdict, in plain
text he does not need a tool to read.

Usage:
    uv run python -m eval.report_bundle <run-dir>            # writes <run-dir>/report/
    uv run python -m eval.report_bundle <run-dir> --open     # also print the summary to stdout

Free (no model calls) — reads the run dir only.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import Counter
from pathlib import Path

# Columns for the summary table. Key -> (display label, formatter).
# Values come from scores.json per_query rows; missing keys render "—".
COLUMNS: list[tuple[str, str]] = [
    ("query_id", "query"),
    ("shape", "shape"),
    ("set", "set"),
    ("ok", "ok"),
    ("key_fact_rate", "fact rate"),
    ("accurate", "accurate"),
    ("steps", "turns"),
    ("retrieve_call_count", "retrieves"),
    ("retrieval_efficiency", "retr eff"),
    ("verified_citations", "cites ok"),
    ("cite_pass_rate", "cite pass"),
    ("first_try_cite_rate", "1st-try"),
    ("figure_coverage", "fig cov"),
    ("total_tokens", "tokens"),
    ("cost_usd", "cost"),
]

SUMMARY_KEYS = [
    ("n", "queries"), ("errors", "crashed"), ("accurate_n", "accurate n"),
    ("accurate_rate", "accurate rate"), ("tokens_to_accurate_mean", "tokens/acc"),
    ("turns_to_accurate_mean", "turns/acc"), ("key_fact_rate_mean", "fact rate mean"),
    ("steps_mean", "turns mean"), ("retrieve_calls_mean", "retrieves mean"),
    ("retrieval_efficiency_mean", "retr eff mean"), ("cite_pass_rate", "cite pass"),
    ("total_cost_usd", "total cost"), ("cost_mean_usd", "cost/query"),
]

JUDGE_KEYS = ["holistic", "chunk_relevance", "claim_coverage_precision",
              "claim_coverage_recall", "figure_coverage_ok", "placement_ok"]


def _fmt(v, digits=4) -> str:
    if v is None:
        return "—"
    if isinstance(v, bool):
        return "✓" if v else "✗"
    if isinstance(v, float):
        return f"{v:.{digits}g}"
    return str(v)


def _load(run_dir: Path) -> dict:
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    judge = {}
    if (run_dir / "judge.json").exists():
        judge = json.loads((run_dir / "judge.json").read_text(encoding="utf-8"))
    errors = {}
    if (run_dir / "errors.json").exists():
        errors = json.loads((run_dir / "errors.json").read_text(encoding="utf-8"))
    return {"scores": scores, "judge": judge, "errors": errors}


def render_transcript(run_dir: Path, qid: str) -> str:
    """Render one transcript JSONL as readable turn-by-turn prose."""
    path = run_dir / f"{qid}-r1.jsonl"
    if not path.exists():
        return "_(transcript file missing)_"
    out: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "meta":
            out.append(f"*query {qid} — corpus {rec.get('corpus')} / tier "
                       f"{rec.get('tier')} / shape {rec.get('shape')}*")
        elif rec.get("kind") == "event":
            ev = rec.get("event") or {}
            t = ev.get("type")
            if t == "user_message":
                out.append(f"\n**User:** {ev.get('text','')}")
            elif t == "assistant_thinking":
                out.append(f"\n_(thinking, turn {len([l for l in out if l.startswith('**Turn')]) + 1})_")
            elif t == "assistant_text_delta":
                # Deltas arrive as streamed fragments; some models re-emit
                # growing prefixes ("**Quick lookup:** The Secre…" × N), so a
                # naive join reads as stuttering. Emit each delta on its own
                # line instead of merging — the readable, authoritative prose
                # is the FINAL ANSWER from the terminal frame below, not the
                # stream. This keeps the stream as a faithful record without
                # pretending it is clean prose.
                out.append(f"  _{ev.get('text', '')}_")
            elif t == "tool_use":
                name = ev.get("toolName")
                inp = ev.get("input") or {}
                if name == "retrieve":
                    q = inp.get("query", "")
                    fy = inp.get("fiscal_year") or inp.get("year")
                    dt = inp.get("doc_type") or inp.get("doctype")
                    ag = inp.get("agency_canonical_id") or inp.get("agency")
                    out.append(f"\n🔍 **retrieve:** {q}"
                               + (f"  [fy={fy}]" if fy else "")
                               + (f" [doc_type={dt}]" if dt else "")
                               + (f" [agency={ag}]" if ag else ""))
                elif name in ("cite", "cite_batch"):
                    out.append(f"\n📎 **{name}:** "
                               f"{json.dumps(inp, ensure_ascii=False)[:300]}")
                else:
                    out.append(f"\n🛠 **{name}:** "
                               f"{json.dumps(inp, ensure_ascii=False)[:300]}")
            elif t == "tool_result":
                # tool_result may carry the parsed output; keep it short
                res = ev.get("output") or ev.get("result") or ""
                s = str(res)
                out.append(f"  _→ tool result: {s[:160]}{'…' if len(s)>160 else ''}_")
            elif t == "turn_complete":
                out.append("\n---")
    # terminal
    term = None
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if rec.get("kind") == "terminal":
            term = rec
    if term:
        frame = term.get("frame") or {}
        out.append(f"\n\n**FINAL ANSWER** (frame {frame.get('type')}):\n\n"
                   f"{frame.get('finalAnswer','')}")
    return "\n".join(out)


def render_judge(judge: dict, qid: str) -> str:
    pq = next((q for q in judge.get("per_query", [])
               if q.get("query_id") == qid), None)
    if not pq:
        return "_(no judge review for this query)_"
    out = ["## Judge review", ""]
    for k in JUDGE_KEYS:
        if k in pq:
            out.append(f"- **{k}**: {_fmt(pq[k])}")
    if pq.get("chunk_relevance_rationale"):
        out.append(f"\n**chunk relevance rationale:** {pq['chunk_relevance_rationale']}")
    if pq.get("rationale"):
        out.append(f"\n**rationale:** {pq['rationale']}")
    flags = pq.get("flags") or {}
    if flags:
        on = [k for k, v in flags.items() if v]
        if on:
            out.append(f"\n**flags:** {', '.join(on)}")
    claims = pq.get("load_bearing_claims") or []
    if claims:
        out.append("\n**load-bearing claims** (cited_verified?):")
        for c in claims:
            mark = "✓" if c.get("cited_verified") else "✗"
            out.append(f"- {mark} {c.get('claim','')}")
    return "\n".join(out)


def render_summary(run_dir: Path, data: dict) -> str:
    scores = data["scores"]
    summary = scores.get("summary", {})
    judge = data.get("judge", {})
    lines = [f"# Eval report — {run_dir.name}", ""]
    # headline summary
    lines += ["## Summary", ""]
    lines.append("| metric | value |")
    lines.append("|---|---|")
    for k, label in SUMMARY_KEYS:
        if k in summary:
            lines.append(f"| {label} | {_fmt(summary[k])} |")
    for k in ["holistic_mean", "chunk_relevance_mean",
              "claim_coverage_precision_mean", "claim_coverage_recall_mean"]:
        if judge.get("summary", {}).get(k) is not None:
            lines.append(f"| {k} | {_fmt(judge['summary'][k])} |")
    lines += ["", "## Per-query table", "",
              "| " + " | ".join(label for _, label in COLUMNS) + " |",
              "|" + "|".join(["---"] * len(COLUMNS)) + "|"]
    for r in sorted(scores.get("per_query", []), key=lambda r: r["query_id"]):
        cells = [_fmt(r.get(k)) for k, _ in COLUMNS]
        lines.append("| " + " | ".join(cells) + " |")
    lines += ["", "Per-query detail: see `per-query/<id>.md`.",
              "Raw artifacts: see `raw/`."]
    return "\n".join(lines) + "\n"


def render_errors(data: dict) -> str:
    errs = data.get("errors") or []
    if not errs:
        return "# Tool-error ledger\n\nNo tool errors in this run.\n"
    lines = ["# Tool-error ledger", ""]
    by_kind = Counter((e.get("kind"),) for e in errs)
    lines += ["| kind | count |", "|---|---|"]
    for (kind,), n in by_kind.most_common():
        lines.append(f"| {kind} | {n} |")
    lines += ["", "## Per query", ""]
    for e in errs:
        lines.append(f"- **{e.get('query_id')}** turn {e.get('turn')}: "
                     f"{e.get('kind')} — {str(e.get('detail'))[:200]}")
    return "\n".join(lines) + "\n"


def build(run_dir: Path, *, open_: bool = False) -> Path:
    data = _load(run_dir)
    report = run_dir / "report"
    pq_dir = report / "per-query"
    raw_dir = report / "raw"
    pq_dir.mkdir(parents=True, exist_ok=True)
    raw_dir.mkdir(parents=True, exist_ok=True)

    # summary
    (report / "00-summary.md").write_text(render_summary(run_dir, data), encoding="utf-8")
    # errors
    (report / "01-errors.md").write_text(render_errors(data), encoding="utf-8")
    # per-query
    scores = data["scores"]
    for r in sorted(scores.get("per_query", []), key=lambda x: x["query_id"]):
        qid = r["query_id"]
        doc = [f"# {qid}", "",
               "## Metrics",
               ""]
        for k, label in COLUMNS:
            if k in r:
                doc.append(f"- **{label}**: {_fmt(r[k])}")
        doc += ["", render_judge(data.get("judge", {}), qid), "",
                "## Transcript", "", render_transcript(run_dir, qid)]
        (pq_dir / f"{qid}.md").write_text("\n".join(doc) + "\n", encoding="utf-8")
        # raw transcript copy
        src = run_dir / f"{qid}-r1.jsonl"
        if src.exists():
            shutil.copy(src, pq_dir / f"{qid}.jsonl")
    # raw artifacts
    for name in ("scores.json", "judge.json", "manifest.json", "errors.json",
                 "errors.md", "ledger.jsonl", "scores.md"):
        src = run_dir / name
        if src.exists():
            shutil.copy(src, raw_dir / name)
    if open_:
        print((report / "00-summary.md").read_text(encoding="utf-8"))
    print(f"report bundle written to {report}/")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble a run dir into a review bundle")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--open", action="store_true", help="print the summary table too")
    args = ap.parse_args()
    build(args.run_dir, open_=args.open)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
