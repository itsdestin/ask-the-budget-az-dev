"""Over-time archive: one metrics.jsonl line per scored run, trend lines
split into segments at every query-set or corpus change.

WHY segments instead of one line or no-trend: the approval task churns
queries_sha256 constantly, so a single continuous trend line would lie
(comparing different question sets), and refusing to trend at all would
waste the archive. Splitting at each change and labeling the segment is
the honest middle (2026-08-16 spec, Honesty guards).
"""
from __future__ import annotations
import json
from pathlib import Path

# The summary keys that trend. Deliberately SHORT — a 30-key line is a
# spreadsheet nobody plots. NOTE the two name collisions resolved here
# (plan review finding 6): the summary's "errors" key is the CRASH count
# (len(rows) - len(ok_rows)), NOT the tool-error ledger (that lives in
# scores["errors"], a list, and is trended separately as tool_error_n);
# "key_fact_rate" does not exist in the summary — the real key is
# "key_fact_rate_mean". Verify both against aggregate() before trusting.
TREND_KEYS = ("tokens_to_accurate_mean", "turns_to_accurate_mean", "accurate_n",
              "accurate_rate", "key_fact_rate_mean", "document_correctness_mean",
              "total_cost_usd", "n")


def append_run(results_root: Path, run_dir: Path, profile: dict) -> None:
    # Idempotent: the spec puts the archive write in the orchestrator, but it
    # lands in score_agent_run.main so standalone re-scores archive too —
    # which means re-scoring a HISTORICAL run would otherwise append a second
    # line for it (plan review finding 6). Skip when already archived.
    metrics_path = results_root / "over-time" / "metrics.jsonl"
    if metrics_path.exists():
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            if line.strip() and json.loads(line).get("run_dir") == run_dir.name:
                return
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    summary = scores["summary"]
    over = results_root / "over-time"
    over.mkdir(parents=True, exist_ok=True)
    metrics = {k: summary.get(k) for k in TREND_KEYS}
    # Tool-error count trends separately from the crash count ("errors" in
    # the summary is crashes; the ledger list lives under scores["errors"]).
    ledger = scores.get("errors")
    metrics["tool_error_n"] = len(ledger) if isinstance(ledger, list) else 0
    row = {"run_dir": run_dir.name, "timestamp": manifest.get("timestamp"),
           "git_sha": manifest.get("git_sha"),
           "queries_sha256": manifest.get("queries_sha256"),
           "corpus_counts": manifest.get("corpus_counts"),
           "tier_models": manifest.get("tier_models"),
           "profile": profile,
           "metrics": metrics}
    with open(over / "metrics.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    idx_path = over / "index.json"
    index = json.loads(idx_path.read_text(encoding="utf-8")) if idx_path.exists() else []
    # Spec archive schema requires cost in the index (plan review finding 6).
    index.append({"run_dir": row["run_dir"], "timestamp": row["timestamp"],
                  "git_sha": row["git_sha"], "profile": profile,
                  "total_cost_usd": summary.get("total_cost_usd"),
                  "sets": (profile.get("sets") or [])})
    tmp = idx_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(index, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(idx_path)


def segments(rows: list[dict]) -> list[list[dict]]:
    out: list[list[dict]] = []
    for r in rows:
        sig = (r.get("queries_sha256"),
               json.dumps(r.get("corpus_counts"), sort_keys=True))
        if out and (out[-1][0].get("queries_sha256"),
                    json.dumps(out[-1][0].get("corpus_counts"), sort_keys=True)) == sig:
            out[-1].append(r)
        else:
            out.append([r])
    return out


def render_trend_md(rows: list[dict]) -> str:
    lines = ["# Over-time trend", ""]
    for i, seg in enumerate(segments(rows), 1):
        first = seg[0]
        lines += [f"## Segment {i} — queries_sha256 {str(first.get('queries_sha256'))[:8]}", ""]
        lines.append("| run | " + " | ".join(TREND_KEYS) + " |")
        lines.append("|" + "---|" * (len(TREND_KEYS) + 1))
        for r in seg:
            cells = [str(r["run_dir"])]
            for k in TREND_KEYS:
                v = r["metrics"].get(k)
                cells.append("—" if v is None else (f"{v:.4g}" if isinstance(v, float) else str(v)))
            lines.append("| " + " | ".join(cells) + " |")
        lines.append("")
    return "\n".join(lines) + "\n"
