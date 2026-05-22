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
