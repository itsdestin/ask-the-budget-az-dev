"""Tests for eval/calibrate_refusal.py.

Calibration is a pure recomputation against an existing result file —
no DB, no retrieval calls. Run against a small fixture so the
expected sweep table is hand-verifiable.
"""
from __future__ import annotations

import pathlib

from eval.calibrate_refusal import compute_sweep, recommend_threshold


def test_sweep_against_fixture():
    """Compute the precision/recall sweep against the fixture result."""
    path = pathlib.Path(__file__).parent / "fixtures" / "eval_result_sample.json"
    table = compute_sweep(str(path), thresholds=[0.10, 0.25, 0.40])
    # At threshold=0.10: nothing refused (all top_scores >= 0.10).
    row_010 = next(r for r in table if r["threshold"] == 0.10)
    assert row_010["refusal_precision"] == 0.0
    # At threshold=0.25: top_scores < 0.25 = q-005 (0.15), q-006 (0.22).
    # Both are refusal queries → precision = 2/2.
    # Retrieval queries with top_score < 0.25: none. So retrieval queries
    # all pass-through correctly.
    row_025 = next(r for r in table if r["threshold"] == 0.25)
    assert row_025["refusal_precision"] == 1.0
    assert row_025["retrieval_passes"] == 3
    # At threshold=0.40: top_scores < 0.40 = q-005, q-006, q-004 (0.35),
    # plus q-003 (0.48 NOT < 0.40 so excluded). Actually 0.35 < 0.40 so
    # q-004 is included. Of refused: q-005 + q-006 are expected refusal,
    # q-004 is also expected refusal (it's a refusal-type query). So all
    # three refusal queries get correctly refused → precision = 3/3.
    # Retrieval queries with top_score < 0.40: q-001 (0.55) NO, q-002
    # (0.72) NO, q-003 (0.48) NO. So all retrieval queries still pass.
    row_040 = next(r for r in table if r["threshold"] == 0.40)
    assert row_040["refusal_precision"] == 1.0
    assert row_040["retrieval_passes"] == 3


def test_recommend_picks_highest_combined_score():
    """The recommended threshold maximizes (precision + retrieval_pass_rate)/2."""
    table = [
        {"threshold": 0.10, "refusal_precision": 0.0, "retrieval_pass_rate": 1.0},
        {"threshold": 0.25, "refusal_precision": 1.0, "retrieval_pass_rate": 1.0},
        {"threshold": 0.40, "refusal_precision": 1.0, "retrieval_pass_rate": 0.67},
    ]
    pick = recommend_threshold(table)
    assert pick["threshold"] == 0.25
