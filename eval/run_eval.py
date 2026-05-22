"""Eval runner — loads queries.yaml, calls retrieve() per query,
scores per-query, aggregates, writes JSON + Markdown to
eval/results/<UTC-ISO>-<git-sha>.{json,md}.

Invocation:
    uv run python -m eval.run_eval
    uv run python -m eval.run_eval --top-k 20 --threshold 0.30
"""
from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import dataclasses

from ruamel.yaml import YAML

from eval.schema import EvalQuery, EvalResult, PerQueryResult
from eval.scoring import (
    aggregate_metrics,
    score_comparison,
    score_lookup,
    score_refusal,
)

# The Python retrieve() entry point (see retrieval/__init__.py). Both
# `retrieve` and `RetrievalRequest` are imported here so tests can
# monkeypatch the name `retrieve` on this module.
from retrieval import retrieve, RetrievalRequest  # noqa: E402


DEFAULT_TOP_K = 20
DEFAULT_REFUSAL_THRESHOLD = 0.30


def load_queries(path: str) -> list[EvalQuery]:
    """Parse eval/queries.yaml into EvalQuery records."""
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f) or []
    return [EvalQuery.model_validate(q) for q in raw]


def _chunk_to_dict(c: Any) -> dict:
    """Normalize a retrieved chunk to a plain dict for scoring.

    Real retrieve() returns RetrievedChunk dataclasses; tests may pass
    plain dicts via the mocked retrieve(). Accept both — the scoring
    functions in eval/scoring.py work against dicts because mocks are
    simpler that way.
    """
    if dataclasses.is_dataclass(c):
        return dataclasses.asdict(c)
    return c


def run_one_query(
    query: EvalQuery, refusal_threshold: float
) -> PerQueryResult:
    """Call retrieve() and score the result. retrieve() is at module
    level so tests can monkeypatch it.

    One bad query (e.g. ParadeDB parser crash on an apostrophe, see
    STATUS.md #47) should NOT abort the whole eval. We catch any
    exception from retrieve(), record it as a fail with the exception
    class name in top_chunk_ids for diagnosis, and continue.
    """
    start = time.monotonic()
    try:
        req = RetrievalRequest(query=query.query, top_k=DEFAULT_TOP_K)
        result = retrieve(req)
        chunks = [_chunk_to_dict(c) for c in result.chunks]
        top_score = result.top_score
    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return PerQueryResult(
            id=query.id,
            type=query.type,
            status="fail",
            matched_via=None,
            rank=None,
            latency_ms=elapsed_ms,
            top_score=0.0,
            top_chunk_ids=[f"<retrieve error: {type(exc).__name__}: {exc}>"],
        )
    elapsed_ms = int((time.monotonic() - start) * 1000)

    if query.type == "lookup":
        status, matched_via, rank = score_lookup(
            query, chunks, k=DEFAULT_TOP_K
        )
    elif query.type == "comparison":
        status, matched_via, rank = score_comparison(
            query, chunks, k=DEFAULT_TOP_K
        )
    elif query.type == "refusal":
        status = score_refusal(query, top_score, refusal_threshold)
        matched_via = None
        rank = None
    else:
        raise ValueError(f"unknown query type: {query.type}")

    return PerQueryResult(
        id=query.id,
        type=query.type,
        status=status,
        matched_via=matched_via,
        rank=rank,
        latency_ms=elapsed_ms,
        top_score=top_score,
        top_chunk_ids=[c.get("chunk_id", "") for c in chunks[:5]],
    )


def _git_sha() -> str:
    """Read the current commit SHA, short form. Returns 'unknown' if
    git isn't available (CI without checkout)."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            text=True,
        ).strip()
    except subprocess.CalledProcessError:
        return "unknown"


def write_json_output(
    path: Path,
    git_sha: str,
    timestamp: str,
    summary: Any,  # EvalSummary
    per_query: list[PerQueryResult],
) -> None:
    """Write a result file as JSON. Atomic write: write to a tmp path,
    then rename — keeps a partial-write from clobbering an existing
    result if the runner crashes mid-stream."""
    from eval.schema import EvalResult

    result = EvalResult(
        git_sha=git_sha,
        timestamp=timestamp,
        summary=summary,
        per_query=per_query,
    )
    payload = result.model_dump(exclude_none=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    tmp.replace(path)


def find_previous_result(results_dir: Path, current_filename: str) -> Path | None:
    """Find the most recent .json result file other than the current
    one. Returns None if no prior runs exist."""
    files = sorted(
        (p for p in results_dir.glob("*.json") if p.name != current_filename),
        reverse=True,
    )
    return files[0] if files else None


def compute_delta(
    curr_summary: Any,  # EvalSummary
    prev_summary: Any,
    curr_per_query: list[PerQueryResult],
    prev_per_query: list[PerQueryResult],
) -> dict[str, Any]:
    """Compute deltas between current and previous run."""
    by_id_prev = {p.id: p for p in prev_per_query}
    by_id_curr = {p.id: p for p in curr_per_query}

    new_passes: list[str] = []
    new_failures: list[str] = []
    for qid, curr in by_id_curr.items():
        prev = by_id_prev.get(qid)
        if prev is None:
            continue  # new query — not a pass/fail transition
        if prev.status == "fail" and curr.status == "pass":
            new_passes.append(qid)
        elif prev.status == "pass" and curr.status == "fail":
            new_failures.append(qid)

    return {
        "recall_at_5_delta": curr_summary.recall_at_5 - prev_summary.recall_at_5,
        "recall_at_20_delta": curr_summary.recall_at_20
        - prev_summary.recall_at_20,
        "latency_p95_delta_ms": curr_summary.latency_p95_ms
        - prev_summary.latency_p95_ms,
        "refusal_precision_delta": curr_summary.refusal_precision
        - prev_summary.refusal_precision,
        "new_passes": new_passes,
        "new_failures": new_failures,
    }


def write_md_output(
    path: Path,
    git_sha: str,
    timestamp: str,
    summary: Any,  # EvalSummary
    per_query: list[PerQueryResult],
    previous: dict | None,
) -> None:
    """Write the human-readable summary."""
    lines: list[str] = []
    lines.append(f"# Eval result — {timestamp} ({git_sha})\n")
    lines.append("## Summary\n")
    lines.append(f"- **recall@5:** {summary.recall_at_5:.0%}")
    lines.append(f"- **recall@20:** {summary.recall_at_20:.0%}")
    lines.append(f"- **fallback rate:** {summary.fallback_rate:.0%} of passes")
    lines.append(
        f"- **latency:** p50 {summary.latency_p50_ms}ms, p95 "
        f"{summary.latency_p95_ms}ms"
    )
    lines.append(
        f"- **refusal precision:** {summary.refusal_precision:.0%}"
    )
    lines.append("")

    if summary.by_type:
        lines.append("## By type\n")
        lines.append("| Type | Count | recall@5 | recall@20 | Notes |")
        lines.append("|---|---|---|---|---|")
        for type_name, bucket in summary.by_type.items():
            if "recall_at_5" in bucket:
                lines.append(
                    f"| {type_name} | {bucket['count']} | "
                    f"{bucket['recall_at_5']:.0%} | "
                    f"{bucket['recall_at_20']:.0%} | |"
                )
            else:
                lines.append(
                    f"| {type_name} | {bucket['count']} | — | — | "
                    f"precision: {bucket.get('precision', 0):.0%} |"
                )
        lines.append("")

    if previous:
        lines.append("## Δ vs. previous run\n")
        lines.append(
            f"- recall@5: {previous['recall_at_5_delta']:+.0%}"
        )
        lines.append(
            f"- recall@20: {previous['recall_at_20_delta']:+.0%}"
        )
        lines.append(
            f"- latency p95: {previous['latency_p95_delta_ms']:+d}ms"
        )
        if previous["new_passes"]:
            lines.append(
                f"- now passing: {', '.join(previous['new_passes'])}"
            )
        if previous["new_failures"]:
            lines.append(
                f"- regressed: {', '.join(previous['new_failures'])}"
            )
        lines.append("")

    failures = [p for p in per_query if p.status == "fail"]
    if failures:
        lines.append("## Failures\n")
        for f in failures:
            lines.append(f"### {f.id} ({f.type})")
            lines.append(
                f"- top_score: {f.top_score:.2f}  "
                f"latency: {f.latency_ms}ms"
            )
            if f.top_chunk_ids:
                lines.append(
                    f"- top chunk_ids: `{', '.join(f.top_chunk_ids[:5])}`"
                )
            lines.append("")

    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the retrieval eval")
    parser.add_argument(
        "--queries", default="eval/queries.yaml",
        help="Path to queries.yaml",
    )
    parser.add_argument(
        "--threshold", type=float, default=DEFAULT_REFUSAL_THRESHOLD,
        help="Refusal threshold to score against",
    )
    parser.add_argument(
        "--results-dir", default="eval/results",
        help="Directory to write result files into",
    )
    args = parser.parse_args()

    print(f"Loading queries from {args.queries}...")
    queries = load_queries(args.queries)
    print(f"Loaded {len(queries)} queries.")

    print(f"Running retrieval (threshold={args.threshold})...")
    per_query: list[PerQueryResult] = []
    for i, q in enumerate(queries, start=1):
        result = run_one_query(q, args.threshold)
        per_query.append(result)
        marker = "✓" if result.status == "pass" else "✗"
        print(
            f"  [{i:>3}/{len(queries)}] {marker} {q.id} ({q.type}, "
            f"{result.latency_ms}ms)"
        )

    summary = aggregate_metrics(per_query)

    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    git_sha = _git_sha()
    results_dir = Path(args.results_dir)
    results_dir.mkdir(parents=True, exist_ok=True)
    json_path = results_dir / f"{timestamp}-{git_sha}.json"
    write_json_output(
        json_path,
        git_sha=git_sha,
        timestamp=timestamp,
        summary=summary,
        per_query=per_query,
    )

    # Markdown summary with delta vs previous run.
    md_path = results_dir / f"{timestamp}-{git_sha}.md"
    delta = None
    prev_path = find_previous_result(results_dir, json_path.name)
    if prev_path:
        # Schema may have evolved since the previous run was written. A
        # validation failure here must NOT abort the current run — we
        # log it, skip the delta, and continue.
        from eval.schema import EvalResult
        try:
            with open(prev_path) as f:
                prev_data = json.load(f)
            prev_result = EvalResult.model_validate(prev_data)
            delta = compute_delta(
                summary, prev_result.summary, per_query, prev_result.per_query
            )
        except Exception as exc:
            print(
                f"  (skipping delta vs {prev_path.name}: "
                f"{type(exc).__name__}: {exc})"
            )

    write_md_output(
        md_path,
        git_sha=git_sha,
        timestamp=timestamp,
        summary=summary,
        per_query=per_query,
        previous=delta,
    )

    print(f"\nWrote:")
    print(f"  {json_path}")
    print(f"  {md_path}")
    print(
        f"\n  recall@5  {summary.recall_at_5:.2%}  "
        f"recall@20  {summary.recall_at_20:.2%}  "
        f"latency p95 {summary.latency_p95_ms}ms  "
        f"refusal precision {summary.refusal_precision:.2%}"
    )
    if delta:
        if delta["new_failures"]:
            print(
                f"\n  ⚠ {len(delta['new_failures'])} regressions vs. previous run: "
                f"{', '.join(delta['new_failures'])}"
            )
        if delta["new_passes"]:
            print(
                f"  ✓ {len(delta['new_passes'])} new passes: "
                f"{', '.join(delta['new_passes'])}"
            )


if __name__ == "__main__":
    main()
