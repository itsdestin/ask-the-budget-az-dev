# Retrieval Eval Harness (Layer 1) Implementation Plan

> **2026-05-22 amendment header.** ✓ Shipped (merge `3a26c19`).
> For current state see [STATUS.md](../../../STATUS.md) and
> [eval/README.md](../../../eval/README.md). For what diverged
> during execution (refusal scope split, calibration formula
> change, subagent-driven synthesis, BM25 apostrophe detour fix,
> etc.), read the matching amendment header on the spec at
> [docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md](../specs/2026-05-20-retrieval-eval-harness-design.md).
> The plan body below is left intact as the original execution
> record; the 13 tasks (Task 0 through Task 12) all landed.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a retrieval-only eval harness — `eval/queries.yaml` (~35 LLM-synthesized queries with hybrid chunk_id + dimensions + anchor_text ground truth), `run_eval.py` runner emitting git-committed JSON+MD per run, `refresh_chunk_ids.py` post-reingest fixer, and `calibrate_refusal.py` threshold sweep — so retrieval changes can be measured in 30 seconds instead of dogfooded.

**Architecture:** Six small Python modules under `eval/`: `schema.py` (Pydantic models), `scoring.py` (pure recall/refusal logic), `synthesize_queries.py` (one-shot LLM-driven generator using Anthropic SDK), `run_eval.py` (main runner), `refresh_chunk_ids.py` (post-reingest fixer), `calibrate_refusal.py` (threshold sweep). Results land as `eval/results/<UTC-ISO>-<git-sha>.{json,md}` committed to git. The harness calls `retrieval/__init__.py::retrieve()` directly (bypasses MCP + Claude) for deterministic measurement.

**Tech Stack:** Python 3.12, Pydantic 2 (schema), `psycopg[binary]` (DB), `voyageai` (embeddings for cosine fallback in refresh tool), `anthropic` (synthesizer LLM — new dep), `ruamel.yaml` (round-trip YAML preservation — new dep), `pytest` (tests). Uses `uv` for all Python invocations.

**Reference:** [docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md](../specs/2026-05-20-retrieval-eval-harness-design.md)

---

## File Structure (created or modified)

### New
- `eval/__init__.py` — empty, makes `eval/` a package importable as `eval.foo`.
- `eval/schema.py` — Pydantic models for `EvalQuery`, `ExpectedChunk`, `QueryDimensions`, `PerQueryResult`, `EvalSummary`, `EvalResult`.
- `eval/scoring.py` — pure functions: `chunk_matches_expected`, `score_lookup`, `score_comparison`, `score_refusal`, `aggregate_metrics`. No DB or I/O.
- `eval/synthesize_queries.py` — entry point `python -m eval.synthesize_queries`. Samples chunks from DB, calls Anthropic API, writes `eval/queries.yaml`.
- `eval/run_eval.py` — entry point `python -m eval.run_eval`. Loads queries, calls `retrieve()`, scores, writes JSON+MD.
- `eval/refresh_chunk_ids.py` — entry point `python -m eval.refresh_chunk_ids`. Refreshes stale chunk_ids in `queries.yaml` after re-ingest.
- `eval/calibrate_refusal.py` — entry point `python -m eval.calibrate_refusal`. Sweeps thresholds, prints recommendation.
- `eval/README.md` — operator-facing docs.
- `eval/queries.yaml` — 35 synthesized queries (output of Task 4's real synthesis run).
- `eval/results/.gitkeep` — placeholder so the directory exists when empty.
- `tests/test_eval_schema.py` — Pydantic schema round-trip tests.
- `tests/test_eval_scoring.py` — pure-function tests for scoring.
- `tests/test_eval_synthesize.py` — synthesizer with mocked Anthropic + mocked DB.
- `tests/test_eval_runner.py` — runner with mocked `retrieve()`.
- `tests/test_eval_refresh.py` — refresh tool with mocked DB.
- `tests/test_eval_calibrate.py` — calibration sweep against fixture result file.
- `tests/fixtures/eval_result_sample.json` — sample EvalResult JSON for calibration tests.
- `tests/fixtures/eval_queries_sample.yaml` — sample queries.yaml for runner/refresh tests.

### Modified
- `pyproject.toml` — add `anthropic>=0.40` and `ruamel.yaml>=0.18` dependencies.
- `CLAUDE.md` — one-line before-push reminder under "Working Rules".

---

## Task 0: Worktree setup + dependency install

**Files:**
- Modify: `pyproject.toml`

- [ ] **Step 1: Create worktree from current master**

Run from `~/ask-the-budget-az-dev`:
```bash
git fetch origin && git pull origin master
git worktree add ~/ask-the-budget-az-worktrees/eval-harness -b eval-harness master
cd ~/ask-the-budget-az-worktrees/eval-harness
cp ~/ask-the-budget-az-dev/.env.local .env.local
```

Expected: fresh worktree at `~/ask-the-budget-az-worktrees/eval-harness/` on a new `eval-harness` branch, `.env.local` copied so `uv run pytest` can reach the DB.

- [ ] **Step 2: Add new Python deps to pyproject.toml**

Find the `dependencies = [...]` array in `pyproject.toml` and append two entries before the closing `]`:

```toml
    # Eval harness (2026-05-20): synthesizer hits Anthropic Claude API; refresh
    # tool preserves YAML structure/comments via ruamel.yaml during in-place edits.
    "anthropic>=0.40",
    "ruamel.yaml>=0.18",
```

- [ ] **Step 3: Run `uv sync` to install new deps**

```bash
uv sync
```

Expected: `Installed N packages: anthropic, ruamel.yaml, ...`. Should take <30s.

- [ ] **Step 4: Verify imports work**

```bash
uv run python -c "import anthropic; from ruamel.yaml import YAML; print('ok')"
```

Expected: `ok`. If either import fails, check the dep specs in pyproject.toml.

- [ ] **Step 5: Run baseline tests to confirm green start**

```bash
uv run pytest tests/test_api.py -k cite_validate -q
```

Expected: 20 passed (matches the citation-accuracy branch's final state).

- [ ] **Step 6: Commit the dep changes**

```bash
git add pyproject.toml uv.lock
git commit -m "build: add anthropic + ruamel.yaml deps for eval harness"
```

---

## Task 1: Schema (Pydantic models)

**Files:**
- Create: `eval/__init__.py`
- Create: `eval/schema.py`
- Create: `tests/test_eval_schema.py`

- [ ] **Step 1: Create the package marker**

Create `eval/__init__.py` as an empty file:

```bash
mkdir -p eval/results
echo "" > eval/__init__.py
echo "" > eval/results/.gitkeep
```

- [ ] **Step 2: Write the failing schema tests**

Create `tests/test_eval_schema.py`:

```python
"""Pydantic schema tests for eval/queries.yaml + eval/results/*.json.

Round-trip tests: parse from dict, serialize back, parse again. If the
schema is correct the second parse equals the first. Catches missing
fields, wrong types, and serialization quirks (e.g., enum vs string).
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from eval.schema import (
    EvalQuery,
    EvalResult,
    EvalSummary,
    ExpectedChunk,
    PerQueryResult,
    QueryDimensions,
)


def test_query_dimensions_round_trip():
    dims = QueryDimensions(
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        agency="agency:ahccs",
    )
    assert dims.publisher == "jlbc"
    assert dims.fiscal_year == 2026
    # Agency is optional (some chunks are cross-agency).
    QueryDimensions(publisher="jlbc", doc_type="topic", fiscal_year=2026)


def test_expected_chunk_with_anchor_text():
    chunk = ExpectedChunk(
        chunk_id="fy26-jlbc-baseline-ahccs::3",
        dimensions=QueryDimensions(
            publisher="jlbc",
            doc_type="baseline-per-agency",
            fiscal_year=2026,
            agency="agency:ahccs",
        ),
        anchor_text="$2,587,400 from the General Fund",
    )
    assert chunk.chunk_id == "fy26-jlbc-baseline-ahccs::3"
    assert chunk.anchor_text is not None


def test_eval_query_lookup_round_trip():
    """Lookup queries carry expected_chunks; expected_refusal=False."""
    raw = {
        "id": "q-001",
        "query": "What was AHCCCS's FY26 General Fund appropriation?",
        "type": "lookup",
        "expected_chunks": [
            {
                "chunk_id": "fy26-jlbc-baseline-ahccs::3",
                "dimensions": {
                    "publisher": "jlbc",
                    "doc_type": "baseline-per-agency",
                    "fiscal_year": 2026,
                    "agency": "agency:ahccs",
                },
                "anchor_text": "$2,587,400 from the General Fund",
            }
        ],
        "expected_refusal": False,
        "synthesized_by": "claude-opus-4-7",
        "synthesized_at": "2026-05-20T18:00Z",
    }
    q = EvalQuery.model_validate(raw)
    assert q.id == "q-001"
    assert q.type == "lookup"
    assert len(q.expected_chunks) == 1
    # Round-trip back to dict; should be stable.
    again = EvalQuery.model_validate(q.model_dump())
    assert again == q


def test_eval_query_refusal_no_expected_chunks():
    """Refusal queries carry expected_refusal=True and no expected_chunks."""
    raw = {
        "id": "q-031",
        "query": "What's the right tax policy for Arizona?",
        "type": "refusal",
        "expected_refusal": True,
    }
    q = EvalQuery.model_validate(raw)
    assert q.type == "refusal"
    assert q.expected_refusal is True
    assert q.expected_chunks == []


def test_eval_query_rejects_invalid_type():
    """The `type` field is a Literal — non-allowed values must fail."""
    with pytest.raises(ValidationError):
        EvalQuery.model_validate(
            {
                "id": "q-099",
                "query": "x",
                "type": "synthesis",  # not allowed in v1
                "expected_refusal": False,
            }
        )


def test_per_query_result_pass_with_chunk_id_match():
    r = PerQueryResult(
        id="q-001",
        type="lookup",
        status="pass",
        matched_via="chunk_id",
        rank=2,
        latency_ms=850,
        top_score=0.84,
        top_chunk_ids=["fy26-jlbc-baseline-ahccs::3"],
    )
    assert r.status == "pass"
    assert r.matched_via == "chunk_id"


def test_per_query_result_fail_has_no_rank():
    r = PerQueryResult(
        id="q-024",
        type="lookup",
        status="fail",
        latency_ms=920,
        top_score=0.41,
        top_chunk_ids=["different::1", "other::2"],
    )
    assert r.status == "fail"
    assert r.matched_via is None
    assert r.rank is None


def test_eval_result_full_round_trip():
    """Full EvalResult: summary + per_query list."""
    raw = {
        "git_sha": "cc0dcb2",
        "timestamp": "2026-05-20T18:30Z",
        "summary": {
            "recall_at_5": 0.76,
            "recall_at_20": 0.84,
            "fallback_rate": 0.1,
            "latency_p50_ms": 1200,
            "latency_p95_ms": 2100,
            "refusal_precision": 0.8,
            "refusal_recall": 0.86,
            "by_type": {
                "lookup": {
                    "recall_at_5": 0.83,
                    "recall_at_20": 0.92,
                    "count": 25,
                },
                "comparison": {
                    "recall_at_5": 0.6,
                    "recall_at_20": 0.8,
                    "count": 5,
                },
                "refusal": {"precision": 0.8, "count": 5},
            },
        },
        "per_query": [
            {
                "id": "q-001",
                "type": "lookup",
                "status": "pass",
                "matched_via": "chunk_id",
                "rank": 2,
                "latency_ms": 850,
                "top_score": 0.84,
                "top_chunk_ids": ["fy26-jlbc-baseline-ahccs::3"],
            }
        ],
    }
    result = EvalResult.model_validate(raw)
    again = EvalResult.model_validate(result.model_dump())
    assert again == result
```

- [ ] **Step 3: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_schema.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.schema'`.

- [ ] **Step 4: Implement `eval/schema.py`**

Create `eval/schema.py`:

```python
"""Pydantic models for the eval harness.

Two surfaces:
  * `EvalQuery` (and its children QueryDimensions, ExpectedChunk) — the
    YAML shape stored at `eval/queries.yaml`. Hybrid ground truth:
    chunk_id (tight, brittle to re-chunking) + dimensions (loose,
    durable) + anchor_text (deterministic recovery target for the
    refresh tool).
  * `EvalResult` (with EvalSummary, PerQueryResult) — the JSON shape
    written per run to `eval/results/<UTC-ISO>-<git-sha>.json`.

Models are frozen-ish (Pydantic v2 default = frozen=False, but we don't
mutate them after construction in the runner — they're built once and
serialized).
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


class QueryDimensions(BaseModel):
    """Loose-but-durable expected-chunk constraint. A returned chunk
    satisfies the dimensions when ALL non-None fields match."""

    publisher: str  # jlbc | agao | governor | legislature
    doc_type: str  # baseline-per-agency | approps-cross-cut | budget-bill | ...
    fiscal_year: int
    # Optional because some chunks (e.g. topic-level cross-cuts) don't
    # stamp to a single agency. When None, agency is not part of the
    # constraint (any chunk satisfying the other three fields passes).
    agency: Optional[str] = None


class ExpectedChunk(BaseModel):
    """One expected-chunk entry on an EvalQuery.

    The hybrid:
      * chunk_id — primary, exact. Used for tight scoring while
        chunk boundaries are stable.
      * dimensions — fallback. Used when chunk_id is no longer in the
        corpus (post-reingest). Survives re-chunking.
      * anchor_text — short distinctive substring from the seed chunk.
        Used by `refresh_chunk_ids.py` to find the successor chunk
        deterministically.
    """

    chunk_id: str
    dimensions: QueryDimensions
    anchor_text: Optional[str] = None


class EvalQuery(BaseModel):
    """A single eval query: question + ground truth + provenance."""

    id: str
    query: str
    type: Literal["lookup", "comparison", "refusal"]
    expected_chunks: list[ExpectedChunk] = Field(default_factory=list)
    expected_refusal: bool = False
    synthesized_by: Optional[str] = None
    synthesized_at: Optional[str] = None


class PerQueryResult(BaseModel):
    """One row of `eval/results/<file>.json::per_query`."""

    id: str
    type: str
    status: Literal["pass", "fail"]
    # `chunk_id` when an expected chunk's chunk_id was in top K.
    # `dimensions_fallback` when chunk_id was missing but a returned
    # chunk satisfied the dimensions.
    # None on fail.
    matched_via: Optional[Literal["chunk_id", "dimensions_fallback"]] = None
    rank: Optional[int] = None  # 1-based rank of the matching chunk
    latency_ms: int
    top_score: float
    top_chunk_ids: list[str] = Field(default_factory=list)


class EvalSummary(BaseModel):
    """Aggregate metrics across all queries in a run."""

    recall_at_5: float
    recall_at_20: float
    fallback_rate: float  # share of passes that used dimensions fallback
    latency_p50_ms: int
    latency_p95_ms: int
    refusal_precision: float  # of would-refuse, how many were correct?
    refusal_recall: float  # of expected-refuse, how many actually did?
    # by_type carries per-type breakdowns. Shape varies (lookup +
    # comparison have recall_at_K; refusal has precision). Keeping as
    # dict for shape flexibility — readers index by string keys.
    by_type: dict


class EvalResult(BaseModel):
    """The full JSON written per run to eval/results/."""

    git_sha: str
    timestamp: str  # UTC ISO 8601
    summary: EvalSummary
    per_query: list[PerQueryResult]
```

- [ ] **Step 5: Run the test, confirm it PASSES**

```bash
uv run pytest tests/test_eval_schema.py -v
```

Expected: 8 passed.

- [ ] **Step 6: Commit**

```bash
git add eval/__init__.py eval/schema.py eval/results/.gitkeep tests/test_eval_schema.py
git commit -m "feat(eval): Pydantic schema for queries.yaml + results JSON

Schema for the hybrid expected_chunks shape (chunk_id primary,
dimensions fallback, anchor_text for refresh) and the per-run
EvalResult emitted to eval/results/."
```

---

## Task 2: Scoring functions

**Files:**
- Create: `eval/scoring.py`
- Create: `tests/test_eval_scoring.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_scoring.py`:

```python
"""Pure-function tests for eval/scoring.py.

Scoring lives in pure functions (no DB, no I/O) so it's trivially
testable. All functions take simple dicts and Pydantic models, return
tuples or floats.
"""
from __future__ import annotations

from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions
from eval.scoring import (
    aggregate_metrics,
    chunk_matches_expected,
    score_comparison,
    score_lookup,
    score_refusal,
)


def _expected(
    chunk_id: str,
    publisher: str = "jlbc",
    doc_type: str = "baseline-per-agency",
    fiscal_year: int = 2026,
    agency: str = "agency:ahccs",
) -> ExpectedChunk:
    return ExpectedChunk(
        chunk_id=chunk_id,
        dimensions=QueryDimensions(
            publisher=publisher,
            doc_type=doc_type,
            fiscal_year=fiscal_year,
            agency=agency,
        ),
    )


def _retrieved_chunk(
    chunk_id: str,
    publisher: str = "jlbc",
    doc_type: str = "baseline-per-agency",
    fiscal_year: int = 2026,
    agency: str = "agency:ahccs",
) -> dict:
    """Mirror the shape `retrieve()` returns per chunk (the fields
    relevant to dimension matching)."""
    return {
        "chunk_id": chunk_id,
        "publisher": publisher,
        "doc_type": doc_type,
        "fiscal_year": fiscal_year,
        # The DB column is `agency_canonical_ids TEXT[]`; the API
        # surface flattens to whatever the chunk stamps to. For tests
        # we pass a list to mirror reality.
        "agency_canonical_ids": [agency],
    }


def test_chunk_matches_chunk_id_exact():
    expected = _expected("abc::1")
    retrieved = _retrieved_chunk("abc::1")
    assert chunk_matches_expected(retrieved, expected) == "chunk_id"


def test_chunk_matches_dimensions_fallback():
    """chunk_id differs (likely re-ingest renamed it) but dimensions
    still match → fallback."""
    expected = _expected("abc::1", agency="agency:ahccs")
    retrieved = _retrieved_chunk("xyz::5", agency="agency:ahccs")
    assert chunk_matches_expected(retrieved, expected) == "dimensions_fallback"


def test_chunk_no_match_when_dimensions_differ():
    expected = _expected("abc::1", agency="agency:ahccs")
    retrieved = _retrieved_chunk("xyz::5", agency="agency:doa")
    assert chunk_matches_expected(retrieved, expected) is None


def test_chunk_matches_when_expected_agency_none():
    """When the expected dimensions don't constrain agency, any
    returned chunk satisfying the other three fields matches."""
    expected = ExpectedChunk(
        chunk_id="topic::3",
        dimensions=QueryDimensions(
            publisher="jlbc", doc_type="topic", fiscal_year=2026
        ),
    )
    retrieved = _retrieved_chunk(
        "topic::3", doc_type="topic", agency="agency:anything"
    )
    assert chunk_matches_expected(retrieved, expected) == "chunk_id"


def test_score_lookup_pass_at_rank_1():
    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[_expected("abc::1")],
    )
    retrieved = [_retrieved_chunk("abc::1"), _retrieved_chunk("other::1")]
    status, matched_via, rank = score_lookup(query, retrieved, k=5)
    assert status == "pass"
    assert matched_via == "chunk_id"
    assert rank == 1


def test_score_lookup_fail_when_not_in_top_k():
    """Lookup query whose expected chunk is at rank 6 fails at K=5."""
    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[_expected("abc::1")],
    )
    retrieved = [_retrieved_chunk(f"other::{i}") for i in range(5)] + [
        _retrieved_chunk("abc::1")
    ]
    status, matched_via, rank = score_lookup(query, retrieved, k=5)
    assert status == "fail"
    assert matched_via is None
    assert rank is None


def test_score_lookup_pass_at_rank_6_with_k_20():
    """Same lookup with K=20 passes."""
    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[_expected("abc::1")],
    )
    retrieved = [_retrieved_chunk(f"other::{i}") for i in range(5)] + [
        _retrieved_chunk("abc::1")
    ]
    status, matched_via, rank = score_lookup(query, retrieved, k=20)
    assert status == "pass"
    assert rank == 6


def test_score_comparison_requires_all_expected_chunks():
    """Comparison query passes only if ALL expected chunks are in top K."""
    query = EvalQuery(
        id="q-014",
        query="x",
        type="comparison",
        expected_chunks=[
            _expected("fy24::1", fiscal_year=2024),
            _expected("fy25::1", fiscal_year=2025),
        ],
    )
    # Both present → pass.
    retrieved = [
        _retrieved_chunk("fy24::1", fiscal_year=2024),
        _retrieved_chunk("fy25::1", fiscal_year=2025),
    ]
    status, _, _ = score_comparison(query, retrieved, k=5)
    assert status == "pass"

    # Only one present → fail.
    retrieved_partial = [_retrieved_chunk("fy24::1", fiscal_year=2024)]
    status, _, rank = score_comparison(query, retrieved_partial, k=5)
    assert status == "fail"
    assert rank is None


def test_score_refusal_passes_when_top_score_below_threshold():
    """Refusal queries pass when retrieval correctly declined."""
    query = EvalQuery(
        id="q-031", query="x", type="refusal", expected_refusal=True
    )
    assert score_refusal(query, top_score=0.15, threshold=0.30) == "pass"
    assert score_refusal(query, top_score=0.45, threshold=0.30) == "fail"


def test_aggregate_metrics_recall_at_k():
    """Aggregate computes recall as passes / total per K."""
    per_query = [
        # 3 lookups, 2 pass at K=5
        _make_per_query("q-1", "lookup", "pass", rank=2, top_score=0.8),
        _make_per_query("q-2", "lookup", "pass", rank=4, top_score=0.7),
        _make_per_query("q-3", "lookup", "fail", top_score=0.4),
        # 2 comparisons, 1 pass at K=5
        _make_per_query(
            "q-4", "comparison", "pass", rank=3, top_score=0.6
        ),
        _make_per_query("q-5", "comparison", "fail", top_score=0.5),
        # 2 refusals, both pass
        _make_per_query("q-6", "refusal", "pass", top_score=0.1),
        _make_per_query("q-7", "refusal", "pass", top_score=0.2),
    ]
    summary = aggregate_metrics(per_query, k_values=[5, 20])
    # Lookups + comparisons count toward recall@K (5 retrieval queries,
    # 3 pass).
    assert summary.recall_at_5 == 3 / 5
    # Refusal precision: 2 of 2 refusal-type queries passed.
    assert summary.refusal_precision == 1.0
    # by_type contains the per-type subdicts.
    assert summary.by_type["lookup"]["count"] == 3


def _make_per_query(
    id: str,
    type: str,
    status: str,
    rank: int | None = None,
    top_score: float = 0.5,
) -> dict:
    """Test helper — builds a PerQueryResult-shaped dict."""
    from eval.schema import PerQueryResult

    return PerQueryResult(
        id=id,
        type=type,
        status=status,
        matched_via="chunk_id" if status == "pass" else None,
        rank=rank,
        latency_ms=1000,
        top_score=top_score,
        top_chunk_ids=[],
    )
```

- [ ] **Step 2: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_scoring.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.scoring'`.

- [ ] **Step 3: Implement `eval/scoring.py`**

Create `eval/scoring.py`:

```python
"""Pure scoring logic for the eval harness.

Functions here take simple dicts (from `retrieve()`) and Pydantic
models (from `eval/queries.yaml`) and return tuples or summary objects.
No DB, no I/O — trivially testable.

The matching algorithm:
  1. chunk_id exact match → "chunk_id" (tight)
  2. dimensions all match → "dimensions_fallback" (loose, used after
     re-ingest until refresh_chunk_ids.py updates the chunk_ids)
  3. neither → None (this chunk doesn't satisfy this expected)

Lookup: pass if ANY expected_chunk has a match in top K.
Comparison: pass if ALL expected_chunks have a match in top K.
Refusal: pass if top_score < threshold (retrieval correctly declined).
"""
from __future__ import annotations

from typing import Literal, Optional

from eval.schema import (
    EvalQuery,
    EvalSummary,
    ExpectedChunk,
    PerQueryResult,
)

MatchKind = Optional[Literal["chunk_id", "dimensions_fallback"]]


def chunk_matches_expected(
    retrieved: dict, expected: ExpectedChunk
) -> MatchKind:
    """Return the match kind, or None when this chunk doesn't satisfy
    this expected. The retrieved chunk is expected to carry the shape
    `retrieve()` returns: chunk_id, publisher, doc_type, fiscal_year,
    agency_canonical_ids (a list)."""
    if retrieved.get("chunk_id") == expected.chunk_id:
        return "chunk_id"

    dims = expected.dimensions
    if retrieved.get("publisher") != dims.publisher:
        return None
    if retrieved.get("doc_type") != dims.doc_type:
        return None
    if retrieved.get("fiscal_year") != dims.fiscal_year:
        return None
    # agency is the only nullable dimension. When None on the expected
    # side it's not part of the constraint.
    if dims.agency is not None:
        agency_ids = retrieved.get("agency_canonical_ids") or []
        if dims.agency not in agency_ids:
            return None
    return "dimensions_fallback"


def score_lookup(
    query: EvalQuery, retrieved: list[dict], k: int
) -> tuple[Literal["pass", "fail"], MatchKind, Optional[int]]:
    """Lookup passes if ANY expected_chunk has a match in top K.
    Returns (status, matched_via, 1-based-rank). When status is "fail"
    matched_via and rank are None."""
    for rank, chunk in enumerate(retrieved[:k], start=1):
        for expected in query.expected_chunks:
            match = chunk_matches_expected(chunk, expected)
            if match is not None:
                return "pass", match, rank
    return "fail", None, None


def score_comparison(
    query: EvalQuery, retrieved: list[dict], k: int
) -> tuple[Literal["pass", "fail"], MatchKind, Optional[int]]:
    """Comparison passes if ALL expected_chunks have a match in top K.
    `matched_via` is "dimensions_fallback" when ANY of the matches used
    fallback (the eval reports degraded ground-truth), "chunk_id" only
    when all matched exactly. `rank` is the MAX rank across the
    matches (the "worst" position needed)."""
    ranks: list[int] = []
    any_fallback = False
    for expected in query.expected_chunks:
        found = False
        for rank, chunk in enumerate(retrieved[:k], start=1):
            match = chunk_matches_expected(chunk, expected)
            if match is not None:
                ranks.append(rank)
                if match == "dimensions_fallback":
                    any_fallback = True
                found = True
                break
        if not found:
            return "fail", None, None
    # Worst rank — comparison passes only when ALL expected chunks are
    # in top K, so the bottleneck is the worst-positioned one. This
    # makes recall@5 for a comparison query mean "both chunks within
    # top 5," not "either chunk within top 5."
    return (
        "pass",
        "dimensions_fallback" if any_fallback else "chunk_id",
        max(ranks),
    )


def score_refusal(
    query: EvalQuery, top_score: float, threshold: float
) -> Literal["pass", "fail"]:
    """Refusal passes when top_score is below the refusal threshold —
    retrieval correctly declined to surface low-confidence chunks."""
    return "pass" if top_score < threshold else "fail"


def aggregate_metrics(
    per_query: list[PerQueryResult], k_values: list[int]
) -> EvalSummary:
    """Compute the EvalSummary from per-query results.

    `k_values` is informational; today's runner always scores at K=5
    and K=20, and the runner emits TWO per_query lists if it wanted
    both. To keep this simple, the runner sends ONE PerQueryResult per
    query (scored at K=20) and we recompute recall@5 by checking if
    each pass's rank is <= 5.
    """
    retrieval_queries = [p for p in per_query if p.type != "refusal"]
    refusal_queries = [p for p in per_query if p.type == "refusal"]

    # Recall@5: pass AND rank <= 5.
    passes_at_5 = sum(
        1
        for p in retrieval_queries
        if p.status == "pass" and p.rank is not None and p.rank <= 5
    )
    passes_at_20 = sum(
        1 for p in retrieval_queries if p.status == "pass"
    )

    # Fallback rate: of all passes, how many used the dimensions
    # fallback?
    total_passes = sum(
        1 for p in retrieval_queries if p.status == "pass"
    )
    fallback_passes = sum(
        1
        for p in retrieval_queries
        if p.status == "pass" and p.matched_via == "dimensions_fallback"
    )
    fallback_rate = (
        fallback_passes / total_passes if total_passes else 0.0
    )

    # Refusal precision: of refusal-type queries that passed (retrieval
    # correctly declined), what share were expected to refuse? Today
    # every refusal-type query IS expected to refuse, so precision
    # equals pass rate.
    refusal_passes = sum(
        1 for p in refusal_queries if p.status == "pass"
    )
    refusal_precision = (
        refusal_passes / len(refusal_queries) if refusal_queries else 0.0
    )
    # Refusal recall: same as precision for v1 (we don't currently
    # detect "queries we should have refused on but didn't" because
    # that requires the eval to KNOW which retrieval queries the model
    # should have refused but answered — out of scope until Layer 2).
    refusal_recall = refusal_precision

    # Latency percentiles across ALL queries.
    latencies = sorted(p.latency_ms for p in per_query)
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95 = (
        latencies[int(len(latencies) * 0.95)]
        if latencies
        else 0
    )

    # Per-type breakdown.
    by_type: dict = {}
    for type_name in ("lookup", "comparison"):
        bucket = [p for p in retrieval_queries if p.type == type_name]
        if not bucket:
            continue
        passes_5 = sum(
            1
            for p in bucket
            if p.status == "pass" and p.rank is not None and p.rank <= 5
        )
        passes_20 = sum(1 for p in bucket if p.status == "pass")
        by_type[type_name] = {
            "recall_at_5": passes_5 / len(bucket),
            "recall_at_20": passes_20 / len(bucket),
            "count": len(bucket),
        }
    if refusal_queries:
        by_type["refusal"] = {
            "precision": refusal_precision,
            "count": len(refusal_queries),
        }

    total_retrieval = len(retrieval_queries)
    return EvalSummary(
        recall_at_5=passes_at_5 / total_retrieval if total_retrieval else 0.0,
        recall_at_20=passes_at_20 / total_retrieval
        if total_retrieval
        else 0.0,
        fallback_rate=fallback_rate,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        refusal_precision=refusal_precision,
        refusal_recall=refusal_recall,
        by_type=by_type,
    )
```

- [ ] **Step 4: Run the test, confirm it PASSES**

```bash
uv run pytest tests/test_eval_scoring.py -v
```

Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/scoring.py tests/test_eval_scoring.py
git commit -m "feat(eval): pure scoring functions for retrieval recall + refusal

chunk_matches_expected, score_lookup, score_comparison, score_refusal,
aggregate_metrics. All pure (no DB, no I/O) so they're trivially
testable. Lookup passes if ANY expected is in top K; comparison
passes if ALL are; refusal passes when retrieval correctly declined
(top_score < threshold)."
```

---

## Task 3: Synthesizer — chunk sampling + lookup queries

**Files:**
- Create: `eval/synthesize_queries.py` (first half — sampling + lookup)
- Create: `tests/test_eval_synthesize.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_synthesize.py`:

```python
"""Tests for the synthesizer. The Anthropic API call and DB connection
are mocked — these tests do NOT spend real API budget or require a
live corpus.

A separate end-to-end "smoke" run is performed in Task 4's Step 6 (one
real synthesis call to produce the initial eval/queries.yaml).
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from eval.synthesize_queries import (
    parse_lookup_response,
    sample_lookup_chunks,
)


def test_parse_lookup_response_extracts_query_and_anchor():
    """Anthropic returns a JSON object inside the message content. The
    parser is lenient: accepts JSON wrapped in markdown code fences,
    trailing whitespace, etc."""
    raw = """```json
{
  "query": "What was AHCCCS's FY26 General Fund appropriation?",
  "anchor_text": "$2,587,400 from the General Fund"
}
```"""
    result = parse_lookup_response(raw)
    assert result["query"] == "What was AHCCCS's FY26 General Fund appropriation?"
    assert "2,587,400" in result["anchor_text"]


def test_parse_lookup_response_handles_bare_json():
    """Some Claude responses skip the markdown fences."""
    raw = '{"query": "Test?", "anchor_text": "fragment"}'
    result = parse_lookup_response(raw)
    assert result["query"] == "Test?"
    assert result["anchor_text"] == "fragment"


def test_parse_lookup_response_raises_on_malformed():
    """Malformed responses should fail loudly (not silently produce
    bad data)."""
    with pytest.raises(ValueError):
        parse_lookup_response("not json at all")


def test_sample_lookup_chunks_balances_across_publishers(monkeypatch):
    """The sampler should pull chunks balanced across publishers."""

    class FakeCursor:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeConn:
        def execute(self, sql, params=None):
            # Return 25 fake chunks; mix of publishers.
            rows = []
            for i in range(25):
                rows.append(
                    {
                        "chunk_id": f"chunk-{i}",
                        "text": f"Sample chunk {i} content.",
                        "publisher": ["jlbc", "agao", "governor", "legislature"][
                            i % 4
                        ],
                        "doc_type": "baseline-per-agency",
                        "fiscal_year": 2026,
                        "agency_canonical_ids": [f"agency:test-{i % 5}"],
                    }
                )
            return FakeCursor(rows)

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.synthesize_queries as syn

    monkeypatch.setattr(syn, "get_connection", lambda: FakeConn())

    chunks = sample_lookup_chunks(n=25)
    assert len(chunks) == 25
    # Confirm the diversity didn't all collapse to one publisher.
    publishers = {c["publisher"] for c in chunks}
    assert len(publishers) > 1


def test_synthesize_lookup_query_calls_anthropic(monkeypatch):
    """The lookup synthesizer should:
    1. Call the Anthropic SDK with the chunk text in the prompt.
    2. Parse the JSON response.
    3. Return an EvalQuery with expected_chunks pointing at the seed
       chunk.
    """
    from eval.synthesize_queries import synthesize_lookup_query

    seed_chunk = {
        "chunk_id": "fy26-jlbc-baseline-ahccs::3",
        "text": "The FY 2026 General Fund appropriation for AHCCCS was $2,587,400.",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2026,
        "agency_canonical_ids": ["agency:ahccs"],
    }

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='{"query": "What was AHCCCS\'s FY26 appropriation?", "anchor_text": "$2,587,400"}'
            )
        ]
    )

    query = synthesize_lookup_query(seed_chunk, mock_client, q_id="q-001")

    assert query.id == "q-001"
    assert query.type == "lookup"
    assert query.expected_refusal is False
    assert len(query.expected_chunks) == 1
    ec = query.expected_chunks[0]
    assert ec.chunk_id == "fy26-jlbc-baseline-ahccs::3"
    assert ec.dimensions.publisher == "jlbc"
    assert ec.dimensions.fiscal_year == 2026
    assert ec.dimensions.agency == "agency:ahccs"
    assert ec.anchor_text == "$2,587,400"
    # Anthropic API was called once with the chunk text in the prompt.
    mock_client.messages.create.assert_called_once()
    call_kwargs = mock_client.messages.create.call_args.kwargs
    prompt_text = call_kwargs["messages"][0]["content"]
    assert "$2,587,400" in prompt_text  # chunk text reached the prompt
```

- [ ] **Step 2: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_synthesize.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.synthesize_queries'`.

- [ ] **Step 3: Create `eval/synthesize_queries.py` with lookup paths**

```python
"""LLM-driven query synthesizer.

Pulls chunks from the corpus, asks Claude to write a realistic analyst
question whose answer is in each chunk, builds EvalQuery records, and
writes to eval/queries.yaml.

Three query types:
  - lookup (25 queries): one chunk per query.
  - comparison (5 queries): chunk PAIR across two FYs of same agency.
  - refusal (5 queries): no chunk seed; Claude generates out-of-scope.

Vocabulary-contamination mitigation: the prompt explicitly asks Claude
to paraphrase rather than borrow rare terms from the source chunk.

Invocation:
    uv run python -m eval.synthesize_queries           # full set (35)
    uv run python -m eval.synthesize_queries --append  # add to existing
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from typing import Any

from anthropic import Anthropic

from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions
# Re-export the pooled connection helper at module scope so tests can
# monkeypatch it as `eval.synthesize_queries.get_connection`. The pool
# helper runs `register_vector` on each connection — required for the
# refresh tool's cosine fallback (find_cosine_match casts a Python list
# to ::vector) and harmless here.
from db.connection import get_connection

# The model the synthesizer uses. Hardcoded — bumping this is a
# deliberate decision, not a config tweak.
SYNTH_MODEL = "claude-opus-4-7"

# How many lookup queries to synthesize per invocation by default.
DEFAULT_LOOKUP_COUNT = 25
DEFAULT_COMPARISON_COUNT = 5
DEFAULT_REFUSAL_COUNT = 5


def sample_lookup_chunks(n: int) -> list[dict]:
    """Sample n chunks balanced across publishers.

    Uses ORDER BY RANDOM() with publisher-grouped LIMITs to roughly
    balance representation. Doesn't try to be perfectly balanced — the
    synthesizer's prompt is robust to over-representing one publisher.
    """
    per_publisher = max(1, n // 4)  # 4 publishers in v1 corpus
    sql = """
        WITH ranked AS (
            SELECT
                c.chunk_id,
                c.text,
                d.publisher,
                c.doc_type,
                c.fiscal_year,
                c.agency_canonical_ids,
                ROW_NUMBER() OVER (
                    PARTITION BY d.publisher ORDER BY RANDOM()
                ) AS rn
            FROM chunks c
            JOIN documents d ON d.doc_id = c.doc_id
            WHERE c.token_count > 80  -- filter degenerate chunks
        )
        SELECT chunk_id, text, publisher, doc_type, fiscal_year,
               agency_canonical_ids
        FROM ranked
        WHERE rn <= %s
        ORDER BY RANDOM()
        LIMIT %s
    """
    with get_connection() as conn:
        cur = conn.execute(sql, (per_publisher, n))
        return cur.fetchall()


def parse_lookup_response(raw: str) -> dict:
    """Extract {query, anchor_text} from Claude's response. Accepts
    markdown-fenced JSON or bare JSON. Raises ValueError on malformed
    input — the synthesizer should fail loudly per query rather than
    emit bad data."""
    # Strip leading/trailing markdown fences if present.
    text = raw.strip()
    fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    try:
        obj = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"synthesizer response not JSON: {raw[:200]}") from e
    if "query" not in obj or "anchor_text" not in obj:
        raise ValueError(
            f"synthesizer response missing keys: {list(obj.keys())}"
        )
    return obj


_LOOKUP_PROMPT_TEMPLATE = """You are a query writer for an Arizona budget Q&A eval set.

Given the following chunk of text from a state budget document, write ONE realistic question that a JLBC fiscal analyst would ask, whose answer is contained in this chunk.

Source chunk ({publisher}, {doc_type}, FY{fiscal_year}, agency={agency}):

\"\"\"
{chunk_text}
\"\"\"

REQUIREMENTS:
- Phrase the question the way a real analyst would ask it conversationally.
- Do NOT borrow rare or distinctive terms from the source chunk verbatim. Use synonyms, paraphrase numeric figures into rounder form ("$3.3M" instead of "$3,290,400"), and avoid quoting the chunk's exact phrasing.
- The question must be specific enough that this chunk is the right answer — vague generic questions don't help.
- Also provide a short "anchor_text" (3-15 words) — a distinctive phrase from the source chunk that would identify it after re-ingest (used by a refresh tool to find the successor chunk).

Output ONLY valid JSON with two keys: "query" and "anchor_text". No prose, no markdown wrapper.

Example output:
{{"query": "What was AHCCCS's FY26 General Fund appropriation?", "anchor_text": "$2,587,400 from the General Fund"}}
"""


def synthesize_lookup_query(
    seed_chunk: dict, client: Anthropic, q_id: str
) -> EvalQuery:
    """One lookup query from one seed chunk. Calls Claude, parses,
    builds EvalQuery."""
    agency = (
        seed_chunk["agency_canonical_ids"][0]
        if seed_chunk.get("agency_canonical_ids")
        else "(none)"
    )
    prompt = _LOOKUP_PROMPT_TEMPLATE.format(
        publisher=seed_chunk["publisher"],
        doc_type=seed_chunk["doc_type"],
        fiscal_year=seed_chunk["fiscal_year"],
        agency=agency,
        chunk_text=seed_chunk["text"][:2000],
    )

    response = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    parsed = parse_lookup_response(raw)

    return EvalQuery(
        id=q_id,
        query=parsed["query"],
        type="lookup",
        expected_chunks=[
            ExpectedChunk(
                chunk_id=seed_chunk["chunk_id"],
                dimensions=QueryDimensions(
                    publisher=seed_chunk["publisher"],
                    doc_type=seed_chunk["doc_type"],
                    fiscal_year=seed_chunk["fiscal_year"],
                    agency=(
                        seed_chunk["agency_canonical_ids"][0]
                        if seed_chunk.get("agency_canonical_ids")
                        else None
                    ),
                ),
                anchor_text=parsed["anchor_text"],
            )
        ],
        expected_refusal=False,
        synthesized_by=SYNTH_MODEL,
        synthesized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    )
```

- [ ] **Step 4: Run the test, confirm it PASSES**

```bash
uv run pytest tests/test_eval_synthesize.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/synthesize_queries.py tests/test_eval_synthesize.py
git commit -m "feat(eval): synthesizer skeleton + lookup query generation

Calls Claude Opus 4.7 with a chunk; parses {query, anchor_text} from
response; builds EvalQuery. Anthropic SDK + DB connection are
injectable so unit tests run offline. Vocabulary-contamination
mitigation is in the prompt — Claude is told to paraphrase rather
than borrow rare terms from the source chunk."
```

---

## Task 4: Synthesizer — comparison + refusal + main entry point + first real run

**Files:**
- Modify: `eval/synthesize_queries.py` (add comparison + refusal + main)
- Modify: `tests/test_eval_synthesize.py` (add comparison + refusal tests)
- Create: `eval/queries.yaml` (output of the real synthesis run)

- [ ] **Step 1: Add comparison + refusal tests**

Append to `tests/test_eval_synthesize.py`:

```python
def test_synthesize_comparison_query():
    """Comparison query takes a chunk PAIR and produces one query
    with two expected_chunks."""
    from eval.synthesize_queries import synthesize_comparison_query

    chunk_a = {
        "chunk_id": "fy24-jlbc-baseline-adc::3",
        "text": "FY 2024 ADC appropriation was $1.5B from the General Fund.",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2024,
        "agency_canonical_ids": ["agency:adc"],
    }
    chunk_b = {
        "chunk_id": "fy26-jlbc-baseline-adc::3",
        "text": "FY 2026 ADC appropriation was $1.7B from the General Fund.",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2026,
        "agency_canonical_ids": ["agency:adc"],
    }

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='{"query": "How did ADC appropriations change FY24 to FY26?", "anchor_text_a": "$1.5B", "anchor_text_b": "$1.7B"}'
            )
        ]
    )

    query = synthesize_comparison_query(
        chunk_a, chunk_b, mock_client, q_id="q-026"
    )

    assert query.type == "comparison"
    assert query.expected_refusal is False
    assert len(query.expected_chunks) == 2
    assert query.expected_chunks[0].chunk_id == chunk_a["chunk_id"]
    assert query.expected_chunks[1].chunk_id == chunk_b["chunk_id"]
    assert query.expected_chunks[0].dimensions.fiscal_year == 2024
    assert query.expected_chunks[1].dimensions.fiscal_year == 2026


def test_synthesize_refusal_query():
    """Refusal query has no seed chunk; Claude generates an out-of-
    scope question independently."""
    from eval.synthesize_queries import synthesize_refusal_query

    mock_client = MagicMock()
    mock_client.messages.create.return_value = MagicMock(
        content=[
            MagicMock(
                text='{"query": "What is the right tax policy for Arizona?"}'
            )
        ]
    )

    query = synthesize_refusal_query(mock_client, q_id="q-031")

    assert query.type == "refusal"
    assert query.expected_refusal is True
    assert query.expected_chunks == []
    assert "tax policy" in query.query.lower()
```

- [ ] **Step 2: Run the new tests, confirm they FAIL**

```bash
uv run pytest tests/test_eval_synthesize.py::test_synthesize_comparison_query tests/test_eval_synthesize.py::test_synthesize_refusal_query -v
```

Expected: FAIL — functions not implemented yet.

- [ ] **Step 3: Add comparison + refusal + main to `eval/synthesize_queries.py`**

Append to `eval/synthesize_queries.py` (after `synthesize_lookup_query`):

```python
def sample_comparison_pairs(n: int) -> list[tuple[dict, dict]]:
    """Find chunk pairs that stamp to the same agency across two
    different fiscal years. Returns up to n pairs."""
    sql = """
        WITH paired AS (
            SELECT
                a.chunk_id AS a_id, a.text AS a_text,
                b.chunk_id AS b_id, b.text AS b_text,
                d.publisher AS publisher,
                a.doc_type AS doc_type,
                a.fiscal_year AS a_fy, b.fiscal_year AS b_fy,
                a.agency_canonical_ids AS agencies
            FROM chunks a
            JOIN chunks b ON b.agency_canonical_ids = a.agency_canonical_ids
                          AND b.fiscal_year > a.fiscal_year
                          AND b.doc_type = a.doc_type
            JOIN documents d ON d.doc_id = a.doc_id
            WHERE a.token_count > 80 AND b.token_count > 80
              AND ARRAY_LENGTH(a.agency_canonical_ids, 1) >= 1
            ORDER BY RANDOM()
            LIMIT %s
        )
        SELECT * FROM paired
    """
    with get_connection() as conn:
        rows = conn.execute(sql, (n,)).fetchall()
    pairs = []
    for r in rows:
        chunk_a = {
            "chunk_id": r["a_id"],
            "text": r["a_text"],
            "publisher": r["publisher"],
            "doc_type": r["doc_type"],
            "fiscal_year": r["a_fy"],
            "agency_canonical_ids": r["agencies"],
        }
        chunk_b = {
            "chunk_id": r["b_id"],
            "text": r["b_text"],
            "publisher": r["publisher"],
            "doc_type": r["doc_type"],
            "fiscal_year": r["b_fy"],
            "agency_canonical_ids": r["agencies"],
        }
        pairs.append((chunk_a, chunk_b))
    return pairs


_COMPARISON_PROMPT_TEMPLATE = """You are a query writer for an Arizona budget Q&A eval set.

Given TWO chunks from state budget documents (same agency, different fiscal years), write ONE comparison question that requires BOTH chunks to answer.

Chunk A ({publisher}, {doc_type}, FY{fy_a}, agency={agency}):

\"\"\"
{chunk_text_a}
\"\"\"

Chunk B ({publisher}, {doc_type}, FY{fy_b}, agency={agency}):

\"\"\"
{chunk_text_b}
\"\"\"

REQUIREMENTS:
- The question must require BOTH chunks to answer (comparison, change-over-time, side-by-side).
- Phrase it naturally; do NOT borrow rare terms from either chunk verbatim.
- Provide TWO anchor_text fragments (one from each chunk) — distinctive phrases the refresh tool will use to find successor chunks after re-ingest.

Output ONLY valid JSON with three keys: "query", "anchor_text_a", "anchor_text_b". No prose, no markdown wrapper.
"""


def synthesize_comparison_query(
    chunk_a: dict, chunk_b: dict, client: Anthropic, q_id: str
) -> EvalQuery:
    """One comparison query from a chunk PAIR."""
    agency = (
        chunk_a["agency_canonical_ids"][0]
        if chunk_a.get("agency_canonical_ids")
        else "(none)"
    )
    prompt = _COMPARISON_PROMPT_TEMPLATE.format(
        publisher=chunk_a["publisher"],
        doc_type=chunk_a["doc_type"],
        fy_a=chunk_a["fiscal_year"],
        fy_b=chunk_b["fiscal_year"],
        agency=agency,
        chunk_text_a=chunk_a["text"][:1500],
        chunk_text_b=chunk_b["text"][:1500],
    )
    response = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = response.content[0].text
    parsed = _parse_comparison_response(raw)

    return EvalQuery(
        id=q_id,
        query=parsed["query"],
        type="comparison",
        expected_chunks=[
            ExpectedChunk(
                chunk_id=chunk_a["chunk_id"],
                dimensions=QueryDimensions(
                    publisher=chunk_a["publisher"],
                    doc_type=chunk_a["doc_type"],
                    fiscal_year=chunk_a["fiscal_year"],
                    agency=agency if agency != "(none)" else None,
                ),
                anchor_text=parsed["anchor_text_a"],
            ),
            ExpectedChunk(
                chunk_id=chunk_b["chunk_id"],
                dimensions=QueryDimensions(
                    publisher=chunk_b["publisher"],
                    doc_type=chunk_b["doc_type"],
                    fiscal_year=chunk_b["fiscal_year"],
                    agency=agency if agency != "(none)" else None,
                ),
                anchor_text=parsed["anchor_text_b"],
            ),
        ],
        expected_refusal=False,
        synthesized_by=SYNTH_MODEL,
        synthesized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    )


def _parse_comparison_response(raw: str) -> dict:
    text = raw.strip()
    fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    obj = json.loads(text)
    if not all(k in obj for k in ("query", "anchor_text_a", "anchor_text_b")):
        raise ValueError(f"comparison response missing keys: {list(obj.keys())}")
    return obj


_REFUSAL_PROMPT = """You are a query writer for an Arizona budget Q&A eval set.

The eval set needs questions the corpus CANNOT answer, so we can verify the system correctly refuses instead of hallucinating.

The corpus contains: JLBC, AGAO, Governor's Office, and Arizona Legislature publications covering Arizona state government finances for FY25–FY27. It does NOT contain: opinion or policy recommendations, future-fiscal-year predictions beyond FY27, agencies that don't exist, local/municipal budgets, or other states.

Write ONE realistic-sounding question that the corpus CANNOT answer. Examples of out-of-scope shapes:
- Opinion: "What should Arizona's tax policy be?"
- Future-FY: "What will the AHCCCS appropriation be in FY 2030?"
- Missing entity: "What did the Arizona Office of Made-Up Programs spend in FY 2026?"
- Other state/local: "What was Tucson's general fund balance in FY 2026?"

Output ONLY valid JSON with one key: "query". No prose, no markdown wrapper.
"""


def synthesize_refusal_query(client: Anthropic, q_id: str) -> EvalQuery:
    """One refusal query — Claude generates an out-of-scope question
    independently (no chunk seed)."""
    response = client.messages.create(
        model=SYNTH_MODEL,
        max_tokens=256,
        messages=[{"role": "user", "content": _REFUSAL_PROMPT}],
    )
    raw = response.content[0].text
    text = raw.strip()
    fence_match = re.match(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)
    obj = json.loads(text)
    return EvalQuery(
        id=q_id,
        query=obj["query"],
        type="refusal",
        expected_chunks=[],
        expected_refusal=True,
        synthesized_by=SYNTH_MODEL,
        synthesized_at=datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ"),
    )


def _write_queries_yaml(queries: list[EvalQuery], path: str) -> None:
    """Write the queries list to YAML. Uses ruamel.yaml so future
    in-place edits by the refresh tool can preserve structure."""
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.default_flow_style = False
    yaml.indent(mapping=2, sequence=4, offset=2)
    serializable = [q.model_dump(exclude_none=True) for q in queries]
    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(serializable, f)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Synthesize the eval query set"
    )
    parser.add_argument(
        "--lookup", type=int, default=DEFAULT_LOOKUP_COUNT,
        help="Number of lookup queries to synthesize",
    )
    parser.add_argument(
        "--comparison", type=int, default=DEFAULT_COMPARISON_COUNT,
        help="Number of comparison queries",
    )
    parser.add_argument(
        "--refusal", type=int, default=DEFAULT_REFUSAL_COUNT,
        help="Number of refusal queries",
    )
    parser.add_argument(
        "--output", default="eval/queries.yaml",
        help="Path to write queries.yaml",
    )
    parser.add_argument(
        "--append", action="store_true",
        help="Append to existing queries.yaml (default: overwrite)",
    )
    args = parser.parse_args()

    client = Anthropic()  # ANTHROPIC_API_KEY from env
    queries: list[EvalQuery] = []
    next_id = 1

    if args.append:
        # Read existing queries and start IDs after the largest existing one.
        from ruamel.yaml import YAML
        yaml = YAML()
        with open(args.output) as f:
            existing = yaml.load(f) or []
        for raw in existing:
            queries.append(EvalQuery.model_validate(raw))
        # Find max existing id (assumes id format "q-NNN").
        existing_ids = [
            int(q.id.split("-")[1]) for q in queries if q.id.startswith("q-")
        ]
        next_id = (max(existing_ids) + 1) if existing_ids else 1

    print(
        f"Synthesizing {args.lookup} lookup + {args.comparison} comparison "
        f"+ {args.refusal} refusal queries using {SYNTH_MODEL}..."
    )

    print("Sampling lookup chunks from corpus...")
    lookup_chunks = sample_lookup_chunks(args.lookup)
    print(f"Got {len(lookup_chunks)} chunks.")
    for chunk in lookup_chunks:
        q_id = f"q-{next_id:03d}"
        next_id += 1
        try:
            query = synthesize_lookup_query(chunk, client, q_id)
            queries.append(query)
            print(f"  {q_id}: {query.query[:70]}...")
        except Exception as e:
            print(f"  {q_id}: FAILED — {e}", file=sys.stderr)

    print("Sampling comparison chunk pairs...")
    pairs = sample_comparison_pairs(args.comparison)
    print(f"Got {len(pairs)} pairs.")
    for chunk_a, chunk_b in pairs:
        q_id = f"q-{next_id:03d}"
        next_id += 1
        try:
            query = synthesize_comparison_query(chunk_a, chunk_b, client, q_id)
            queries.append(query)
            print(f"  {q_id}: {query.query[:70]}...")
        except Exception as e:
            print(f"  {q_id}: FAILED — {e}", file=sys.stderr)

    print("Generating refusal queries (out-of-scope)...")
    for _ in range(args.refusal):
        q_id = f"q-{next_id:03d}"
        next_id += 1
        try:
            query = synthesize_refusal_query(client, q_id)
            queries.append(query)
            print(f"  {q_id}: {query.query[:70]}...")
        except Exception as e:
            print(f"  {q_id}: FAILED — {e}", file=sys.stderr)

    _write_queries_yaml(queries, args.output)
    print(f"\nWrote {len(queries)} queries to {args.output}.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the unit tests, confirm they PASS**

```bash
uv run pytest tests/test_eval_synthesize.py -v
```

Expected: 7 passed (5 from Task 3 + 2 new).

- [ ] **Step 5: Run a real synthesis to produce `eval/queries.yaml`**

Real Anthropic API call. Will spend ~$2-3 of API budget.

Before running, confirm `ANTHROPIC_API_KEY` is in `.env.local` (the existing `.env.local` already has it). The script reads env vars from process env, so you may need:

```bash
set -a; source .env.local; set +a
uv run python -m eval.synthesize_queries
```

Expected output: ~35 queries listed line-by-line; `Wrote 35 queries to eval/queries.yaml.` at end. Some queries may FAIL parse — that's OK as long as ≥30 succeed.

If too many fail (≤25 succeed), inspect the stderr output for what Claude is returning; tune the prompt and re-run.

- [ ] **Step 6: Manual review of `eval/queries.yaml`**

Open `eval/queries.yaml` and skim through. Look for:
- Queries that don't make sense → delete or edit the `query:` field
- Anchor texts that aren't actually in the source chunk → that means contamination mitigation backfired; delete the entry (we'll regenerate later)
- Refusal queries that aren't actually out-of-scope → delete or edit
- Duplicate or near-duplicate queries → delete one

Aim for ~30-35 surviving queries. This is your one-time review.

- [ ] **Step 7: Commit the synthesized queries**

```bash
git add eval/synthesize_queries.py tests/test_eval_synthesize.py eval/queries.yaml
git commit -m "feat(eval): comparison + refusal synthesis + first real eval set

Comparison synthesizer pulls chunk pairs (same agency, different FY).
Refusal synthesizer generates out-of-scope questions independently.
Main entry point wires the three types together. First real synthesis
ran against the live corpus and produced eval/queries.yaml — committed
so the eval set travels with the repo and is diff-reviewable."
```

---

## Task 5: Runner — load + iterate + call `retrieve()` + per-query scoring

**Files:**
- Create: `eval/run_eval.py` (first half — iteration + per-query)
- Create: `tests/test_eval_runner.py`
- Create: `tests/fixtures/eval_queries_sample.yaml`

- [ ] **Step 1: Create the test fixture**

Create `tests/fixtures/eval_queries_sample.yaml`:

```yaml
- id: q-001
  query: "What was AHCCCS's FY26 appropriation?"
  type: lookup
  expected_chunks:
    - chunk_id: "fy26-jlbc-baseline-ahccs::3"
      dimensions:
        publisher: jlbc
        doc_type: baseline-per-agency
        fiscal_year: 2026
        agency: "agency:ahccs"
      anchor_text: "$2,587,400"
  expected_refusal: false
  synthesized_by: claude-opus-4-7
  synthesized_at: "2026-05-20T18:00Z"

- id: q-002
  query: "What's the right tax policy for Arizona?"
  type: refusal
  expected_chunks: []
  expected_refusal: true
  synthesized_by: claude-opus-4-7
  synthesized_at: "2026-05-20T18:00Z"
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_eval_runner.py`:

```python
"""Tests for eval/run_eval.py.

The runner's retrieve() call is mocked. Real retrieval-against-corpus
integration is exercised manually in Task 7 Step 5 (first real eval
run).
"""
from __future__ import annotations

import pathlib

from eval.run_eval import (
    load_queries,
    run_one_query,
)


def test_load_queries_parses_fixture_yaml():
    path = pathlib.Path(__file__).parent / "fixtures" / "eval_queries_sample.yaml"
    queries = load_queries(str(path))
    assert len(queries) == 2
    assert queries[0].id == "q-001"
    assert queries[0].type == "lookup"
    assert queries[1].type == "refusal"


def test_run_one_query_lookup_pass(monkeypatch):
    """A lookup query whose expected chunk is at rank 1 → pass at K=5."""
    from eval.run_eval import run_one_query
    from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions

    query = EvalQuery(
        id="q-001",
        query="x",
        type="lookup",
        expected_chunks=[
            ExpectedChunk(
                chunk_id="chunk-A",
                dimensions=QueryDimensions(
                    publisher="jlbc",
                    doc_type="baseline-per-agency",
                    fiscal_year=2026,
                    agency="agency:ahccs",
                ),
            )
        ],
        expected_refusal=False,
    )

    def fake_retrieve(req, **_):
        # The real retrieve() takes a RetrievalRequest; mocks accept it
        # via the `req` positional. Returning plain dicts is fine —
        # _chunk_to_dict in run_one_query passes them through.
        from types import SimpleNamespace
        return SimpleNamespace(
            chunks=[
                {
                    "chunk_id": "chunk-A",
                    "publisher": "jlbc",
                    "doc_type": "baseline-per-agency",
                    "fiscal_year": 2026,
                    "agency_canonical_ids": ["agency:ahccs"],
                    "score": 0.82,
                }
            ],
            top_score=0.82,
        )

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "pass"
    assert result.matched_via == "chunk_id"
    assert result.rank == 1
    assert result.top_score == 0.82


def test_run_one_query_lookup_fail(monkeypatch):
    """Lookup query whose expected chunk doesn't appear → fail."""
    from eval.schema import EvalQuery, ExpectedChunk, QueryDimensions

    query = EvalQuery(
        id="q-024",
        query="x",
        type="lookup",
        expected_chunks=[
            ExpectedChunk(
                chunk_id="chunk-A",
                dimensions=QueryDimensions(
                    publisher="jlbc",
                    doc_type="baseline-per-agency",
                    fiscal_year=2026,
                    agency="agency:ahccs",
                ),
            )
        ],
    )

    def fake_retrieve(req, **_):
        from types import SimpleNamespace
        return SimpleNamespace(
            chunks=[
                {
                    "chunk_id": "other-chunk",
                    "publisher": "agao",
                    "doc_type": "afr",
                    "fiscal_year": 2024,
                    "agency_canonical_ids": [],
                    "score": 0.41,
                }
            ],
            top_score=0.41,
        )

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "fail"
    assert result.matched_via is None
    assert result.rank is None


def test_run_one_query_refusal_pass(monkeypatch):
    """Refusal query where top_score < threshold → pass (correctly
    declined)."""
    from eval.schema import EvalQuery

    query = EvalQuery(
        id="q-031",
        query="What's the right tax policy?",
        type="refusal",
        expected_refusal=True,
    )

    def fake_retrieve(req, **_):
        from types import SimpleNamespace
        return SimpleNamespace(
            chunks=[
                {
                    "chunk_id": "weakly-related",
                    "publisher": "jlbc",
                    "doc_type": "baseline-per-agency",
                    "fiscal_year": 2026,
                    "agency_canonical_ids": [],
                    "score": 0.18,
                }
            ],
            top_score=0.18,
        )

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "pass"


def test_run_one_query_refusal_fail(monkeypatch):
    """Refusal query where top_score >= threshold → fail (model would
    have answered, but should have refused)."""
    from eval.schema import EvalQuery

    query = EvalQuery(
        id="q-032", query="x", type="refusal", expected_refusal=True
    )

    def fake_retrieve(req, **_):
        from types import SimpleNamespace
        return SimpleNamespace(chunks=[], top_score=0.55)

    import eval.run_eval as runner
    monkeypatch.setattr(runner, "retrieve", fake_retrieve)

    result = run_one_query(query, refusal_threshold=0.30)
    assert result.status == "fail"
```

- [ ] **Step 3: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_runner.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.run_eval'`.

- [ ] **Step 4: Create `eval/run_eval.py` (first half)**

```python
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
```

- [ ] **Step 5: Run the tests, confirm they PASS**

```bash
uv run pytest tests/test_eval_runner.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add eval/run_eval.py tests/test_eval_runner.py tests/fixtures/eval_queries_sample.yaml
git commit -m "feat(eval): runner skeleton — load queries + per-query scoring

load_queries parses queries.yaml; run_one_query calls retrieve(),
times it, scores via eval/scoring functions. retrieve() is imported
at module level so tests can monkeypatch it. Aggregation + JSON/MD
output come in the next task."
```

---

## Task 6: Runner — aggregate + JSON output

**Files:**
- Modify: `eval/run_eval.py` (add main + JSON writer)
- Modify: `tests/test_eval_runner.py` (add aggregate + JSON tests)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_eval_runner.py`:

```python
def test_write_json_output(tmp_path):
    """The JSON writer emits a file readable by EvalResult.model_validate."""
    from eval.run_eval import write_json_output
    from eval.schema import EvalSummary, PerQueryResult

    summary = EvalSummary(
        recall_at_5=0.8,
        recall_at_20=0.9,
        fallback_rate=0.1,
        latency_p50_ms=1000,
        latency_p95_ms=2000,
        refusal_precision=1.0,
        refusal_recall=1.0,
        by_type={
            "lookup": {"recall_at_5": 0.83, "recall_at_20": 0.92, "count": 1},
            "refusal": {"precision": 1.0, "count": 1},
        },
    )
    per_query = [
        PerQueryResult(
            id="q-001",
            type="lookup",
            status="pass",
            matched_via="chunk_id",
            rank=2,
            latency_ms=850,
            top_score=0.84,
            top_chunk_ids=["chunk-A"],
        )
    ]
    out_path = tmp_path / "result.json"
    write_json_output(
        out_path,
        git_sha="abc1234",
        timestamp="2026-05-20T18:30Z",
        summary=summary,
        per_query=per_query,
    )

    # Round-trip the file: write then re-load via EvalResult.
    with open(out_path) as f:
        loaded = json.load(f)
    from eval.schema import EvalResult
    result = EvalResult.model_validate(loaded)
    assert result.git_sha == "abc1234"
    assert result.summary.recall_at_5 == 0.8
    assert len(result.per_query) == 1
```

(Add `import json` at the top of the test file if not already present.)

- [ ] **Step 2: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_runner.py::test_write_json_output -v
```

Expected: FAIL — `cannot import name 'write_json_output'`.

- [ ] **Step 3: Add `write_json_output` + `main` to `eval/run_eval.py`**

Append to `eval/run_eval.py`:

```python
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

    summary = aggregate_metrics(per_query, k_values=[5, 20])

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

    # Markdown summary writer is Task 7.
    print(f"\nWrote {json_path}.")
    print(
        f"  recall@5  {summary.recall_at_5:.2%}  "
        f"recall@20  {summary.recall_at_20:.2%}  "
        f"latency p95 {summary.latency_p95_ms}ms  "
        f"refusal precision {summary.refusal_precision:.2%}"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the test, confirm it PASSES**

```bash
uv run pytest tests/test_eval_runner.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/run_eval.py tests/test_eval_runner.py
git commit -m "feat(eval): runner aggregation + JSON output + main entry point

Aggregates per-query results into EvalSummary, writes JSON to
eval/results/<UTC-ISO>-<git-sha>.json (atomic via .tmp + rename),
prints a one-line summary. Markdown summary writer + delta vs previous
run come in the next task."
```

---

## Task 7: Runner — Markdown summary + delta vs previous run

**Files:**
- Modify: `eval/run_eval.py` (add Markdown writer + delta computation)
- Modify: `tests/test_eval_runner.py` (add MD writer test)

- [ ] **Step 1: Add the failing test**

Append to `tests/test_eval_runner.py`:

```python
def test_write_md_output_includes_metrics_and_failures(tmp_path):
    """The MD writer produces a human-readable summary with the key
    metrics + a per-failure analysis section."""
    from eval.run_eval import write_md_output
    from eval.schema import EvalSummary, PerQueryResult

    summary = EvalSummary(
        recall_at_5=0.8,
        recall_at_20=0.9,
        fallback_rate=0.1,
        latency_p50_ms=1000,
        latency_p95_ms=2000,
        refusal_precision=1.0,
        refusal_recall=1.0,
        by_type={
            "lookup": {"recall_at_5": 0.83, "recall_at_20": 0.92, "count": 2}
        },
    )
    per_query = [
        PerQueryResult(
            id="q-001",
            type="lookup",
            status="pass",
            matched_via="chunk_id",
            rank=2,
            latency_ms=850,
            top_score=0.84,
            top_chunk_ids=["chunk-A"],
        ),
        PerQueryResult(
            id="q-024",
            type="lookup",
            status="fail",
            latency_ms=920,
            top_score=0.41,
            top_chunk_ids=["unrelated::1", "unrelated::2"],
        ),
    ]
    out_path = tmp_path / "result.md"
    write_md_output(
        out_path,
        git_sha="abc1234",
        timestamp="2026-05-20T18:30Z",
        summary=summary,
        per_query=per_query,
        previous=None,
    )
    content = out_path.read_text()
    assert "recall@5" in content.lower()
    assert "80%" in content or "0.80" in content
    # Failures section lists q-024.
    assert "q-024" in content
    # Top chunks for the failure are shown for diagnosis.
    assert "unrelated::1" in content


def test_compute_delta_vs_previous():
    """compute_delta returns a dict of metric deltas + per-query
    pass/fail transitions."""
    from eval.run_eval import compute_delta
    from eval.schema import EvalSummary, PerQueryResult

    prev_summary = EvalSummary(
        recall_at_5=0.7, recall_at_20=0.85,
        fallback_rate=0.1, latency_p50_ms=1100, latency_p95_ms=1900,
        refusal_precision=0.8, refusal_recall=0.8,
        by_type={},
    )
    curr_summary = EvalSummary(
        recall_at_5=0.8, recall_at_20=0.85,
        fallback_rate=0.1, latency_p50_ms=1000, latency_p95_ms=2000,
        refusal_precision=1.0, refusal_recall=1.0,
        by_type={},
    )
    prev_per_query = [
        PerQueryResult(
            id="q-001", type="lookup", status="pass",
            latency_ms=900, top_score=0.8, top_chunk_ids=[]
        ),
        PerQueryResult(
            id="q-019", type="lookup", status="fail",
            latency_ms=1000, top_score=0.3, top_chunk_ids=[]
        ),
    ]
    curr_per_query = [
        PerQueryResult(
            id="q-001", type="lookup", status="pass",
            latency_ms=850, top_score=0.84, top_chunk_ids=[]
        ),
        PerQueryResult(
            id="q-019", type="lookup", status="pass",
            latency_ms=950, top_score=0.7, top_chunk_ids=[]
        ),
    ]
    delta = compute_delta(
        curr_summary, prev_summary, curr_per_query, prev_per_query
    )
    assert delta["recall_at_5_delta"] == pytest.approx(0.1)
    assert "q-019" in delta["new_passes"]
    assert delta["new_failures"] == []
```

(Add `import pytest` at top of test file if not already present.)

- [ ] **Step 2: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_runner.py::test_write_md_output_includes_metrics_and_failures -v
```

Expected: FAIL — `cannot import name 'write_md_output'`.

- [ ] **Step 3: Add `write_md_output` + `compute_delta` to `eval/run_eval.py`**

Append to `eval/run_eval.py`:

```python
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
```

Then modify the `main()` function in `eval/run_eval.py` — find the section that writes JSON and prints the summary, and replace the closing print block with this expanded version:

```python
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
```

- [ ] **Step 4: Run the tests, confirm they PASS**

```bash
uv run pytest tests/test_eval_runner.py -v
```

Expected: 8 passed.

- [ ] **Step 5: Run a real eval against the live corpus**

Make sure Postgres is running and the sidecar deps are available:

```bash
cd ~/ask-the-budget-az-worktrees/eval-harness
docker ps | grep postgres   # confirm askbudget-postgres is up
set -a; source .env.local; set +a
uv run python -m eval.run_eval
```

Expected:
- ~35 lines of per-query output (one per query, with ✓/✗ + latency)
- Final summary printed
- A new file pair created in `eval/results/`
- Approximate latency: ~30s total for 35 queries

If anything crashes, capture the traceback and stop. Common issues:
- DB connection: confirm `DATABASE_URL` is set
- Voyage rate limit: rerun after a minute
- A query parse error in `queries.yaml`: edit by hand

- [ ] **Step 6: Commit the runner + first real result file**

```bash
git add eval/run_eval.py tests/test_eval_runner.py eval/results/
git commit -m "feat(eval): markdown summary + delta vs previous run

write_md_output emits a human-readable summary with by-type
breakdown, delta vs previous run, and a per-failure section. main()
finds the most recent previous result and computes deltas. First real
eval-against-corpus committed under eval/results/ so the history is
visible going forward."
```

---

## Task 8: Refresh tool — chunk_id staleness check + anchor_text match

**Files:**
- Create: `eval/refresh_chunk_ids.py` (first half — anchor_text matching)
- Create: `tests/test_eval_refresh.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_eval_refresh.py`:

```python
"""Tests for eval/refresh_chunk_ids.py.

DB calls are mocked. The YAML round-trip is exercised against a real
tmp file using ruamel.yaml.
"""
from __future__ import annotations

from unittest.mock import MagicMock


def test_check_chunk_exists_returns_true_when_chunk_in_db(monkeypatch):
    """Returns True when the chunks table has a row for the chunk_id."""
    from eval.refresh_chunk_ids import chunk_exists

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchone(_self):
                    return {"chunk_id": "abc::1"}

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    assert chunk_exists("abc::1") is True


def test_check_chunk_exists_returns_false_when_missing(monkeypatch):
    from eval.refresh_chunk_ids import chunk_exists

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchone(_self):
                    return None

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    assert chunk_exists("missing::1") is False


def test_find_anchor_match_picks_chunk_containing_anchor(monkeypatch):
    """When the anchor_text appears in a candidate chunk, pick it."""
    from eval.refresh_chunk_ids import find_anchor_match
    from eval.schema import QueryDimensions

    candidates = [
        {"chunk_id": "new-abc::2", "text": "unrelated content here"},
        {
            "chunk_id": "new-abc::3",
            "text": "The fund got $2,587,400 from the General Fund.",
        },
        {"chunk_id": "new-abc::4", "text": "other content"},
    ]

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchall(_self):
                    return candidates

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    dims = QueryDimensions(
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        agency="agency:ahccs",
    )
    match = find_anchor_match(
        dims=dims, anchor_text="$2,587,400 from the General Fund"
    )
    assert match == "new-abc::3"


def test_find_anchor_match_returns_none_when_no_anchor_hit(monkeypatch):
    """When no candidate's text contains the anchor, return None."""
    from eval.refresh_chunk_ids import find_anchor_match
    from eval.schema import QueryDimensions

    candidates = [
        {"chunk_id": "x", "text": "unrelated"},
        {"chunk_id": "y", "text": "more unrelated"},
    ]

    class FakeConn:
        def execute(self, sql, params):
            class _Cur:
                def fetchall(_self):
                    return candidates

            return _Cur()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            return False

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "get_connection", lambda: FakeConn())

    dims = QueryDimensions(
        publisher="jlbc",
        doc_type="baseline-per-agency",
        fiscal_year=2026,
        agency="agency:ahccs",
    )
    match = find_anchor_match(
        dims=dims, anchor_text="missing anchor phrase"
    )
    assert match is None
```

- [ ] **Step 2: Run the tests, confirm they FAIL**

```bash
uv run pytest tests/test_eval_refresh.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.refresh_chunk_ids'`.

- [ ] **Step 3: Create `eval/refresh_chunk_ids.py` (first half)**

```python
"""Refresh stale chunk_ids in eval/queries.yaml after a re-ingest.

When the ingest pipeline runs (or when chunk boundaries change), the
chunk_ids in eval/queries.yaml may no longer point at real chunks.
This script finds successor chunks for each stale entry, prefers
anchor_text matching when available, falls back to embedding-based
cosine similarity when not, and flags entries that can't be repaired
for manual review.

Invocation:
    uv run python -m eval.refresh_chunk_ids
    uv run python -m eval.refresh_chunk_ids --queries other.yaml
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from eval.schema import QueryDimensions
# Re-export the pooled connection helper for monkeypatching in tests.
# The pool's configure callback runs `register_vector(conn)` so the
# cosine-similarity SQL below can cast a Python list to ::vector.
from db.connection import get_connection


def chunk_exists(chunk_id: str) -> bool:
    """Return True iff the chunks table has a row for the given
    chunk_id."""
    with get_connection() as conn:
        row = conn.execute(
            "SELECT chunk_id FROM chunks WHERE chunk_id = %s",
            (chunk_id,),
        ).fetchone()
    return row is not None


def find_anchor_match(
    dims: QueryDimensions, anchor_text: str
) -> Optional[str]:
    """Find a successor chunk whose text contains anchor_text and
    whose dimensions match. Returns the chunk_id, or None if no
    candidate contains the anchor."""
    sql = """
        SELECT c.chunk_id, c.text
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE d.publisher = %s
          AND c.doc_type = %s
          AND c.fiscal_year = %s
          AND (%s IS NULL OR %s = ANY(c.agency_canonical_ids))
    """
    with get_connection() as conn:
        rows = conn.execute(
            sql,
            (dims.publisher, dims.doc_type, dims.fiscal_year, dims.agency, dims.agency),
        ).fetchall()
    for r in rows:
        if anchor_text and anchor_text in r["text"]:
            return r["chunk_id"]
    return None
```

- [ ] **Step 4: Run the tests, confirm they PASS**

```bash
uv run pytest tests/test_eval_refresh.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/refresh_chunk_ids.py tests/test_eval_refresh.py
git commit -m "feat(eval): refresh tool — chunk_exists + anchor_text match

chunk_exists checks whether the chunks table has a row for a given
chunk_id. find_anchor_match queries candidate chunks matching the
dimensions and returns the first one whose text contains the
anchor_text. Cosine-similarity fallback + YAML round-trip come in
the next task."
```

---

## Task 9: Refresh tool — cosine fallback + YAML round-trip + main

**Files:**
- Modify: `eval/refresh_chunk_ids.py` (add cosine fallback + main)
- Modify: `tests/test_eval_refresh.py` (add round-trip test)

- [ ] **Step 1: Add the failing tests**

Append to `tests/test_eval_refresh.py`:

```python
def test_refresh_yaml_round_trips_and_updates_chunk_id(tmp_path, monkeypatch):
    """Full refresh against a sample yaml: stale chunk_id is replaced
    with an anchor match, the YAML is written back preserving structure."""
    from eval.refresh_chunk_ids import refresh_queries_file

    # Sample YAML with a stale chunk_id.
    yaml_text = """\
- id: q-001
  query: "What was AHCCCS FY26 GF appropriation?"
  type: lookup
  expected_chunks:
    - chunk_id: "stale-chunk::1"
      dimensions:
        publisher: jlbc
        doc_type: baseline-per-agency
        fiscal_year: 2026
        agency: "agency:ahccs"
      anchor_text: "$2,587,400"
  expected_refusal: false
  synthesized_by: claude-opus-4-7
  synthesized_at: "2026-05-20T18:00Z"
"""
    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text(yaml_text)

    # Mock DB: stale-chunk::1 doesn't exist; one candidate matches anchor.
    import eval.refresh_chunk_ids as refresh

    def fake_chunk_exists(chunk_id):
        return chunk_id != "stale-chunk::1"

    def fake_find_anchor_match(dims, anchor_text):
        if anchor_text == "$2,587,400":
            return "new-chunk::5"
        return None

    def fake_find_cosine_match(dims, query_text):
        return None  # not reached

    monkeypatch.setattr(refresh, "chunk_exists", fake_chunk_exists)
    monkeypatch.setattr(refresh, "find_anchor_match", fake_find_anchor_match)
    monkeypatch.setattr(refresh, "find_cosine_match", fake_find_cosine_match)

    summary = refresh_queries_file(str(queries_path))
    assert summary["refreshed"] == 1
    assert summary["manual_review"] == 0
    assert summary["unchanged"] == 0

    # Re-read the YAML and confirm the chunk_id was updated in place.
    from ruamel.yaml import YAML
    yaml = YAML()
    with open(queries_path) as f:
        updated = yaml.load(f)
    assert updated[0]["expected_chunks"][0]["chunk_id"] == "new-chunk::5"


def test_refresh_flags_manual_review_when_no_match(tmp_path, monkeypatch):
    """When neither anchor nor cosine finds a match, the query is left
    untouched and counted as manual_review."""
    from eval.refresh_chunk_ids import refresh_queries_file

    yaml_text = """\
- id: q-001
  query: "x"
  type: lookup
  expected_chunks:
    - chunk_id: "stale::1"
      dimensions:
        publisher: jlbc
        doc_type: baseline-per-agency
        fiscal_year: 2026
        agency: "agency:gone"
      anchor_text: "missing"
  expected_refusal: false
"""
    queries_path = tmp_path / "queries.yaml"
    queries_path.write_text(yaml_text)

    import eval.refresh_chunk_ids as refresh
    monkeypatch.setattr(refresh, "chunk_exists", lambda cid: False)
    monkeypatch.setattr(refresh, "find_anchor_match", lambda *a: None)
    monkeypatch.setattr(refresh, "find_cosine_match", lambda *a: None)

    summary = refresh_queries_file(str(queries_path))
    assert summary["manual_review"] == 1
    assert summary["refreshed"] == 0

    # The YAML was not modified.
    from ruamel.yaml import YAML
    yaml = YAML()
    with open(queries_path) as f:
        unchanged = yaml.load(f)
    assert unchanged[0]["expected_chunks"][0]["chunk_id"] == "stale::1"
```

- [ ] **Step 2: Run the tests, confirm they FAIL**

```bash
uv run pytest tests/test_eval_refresh.py::test_refresh_yaml_round_trips_and_updates_chunk_id -v
```

Expected: FAIL — `cannot import name 'refresh_queries_file'`.

- [ ] **Step 3: Append cosine fallback + refresh + main to `eval/refresh_chunk_ids.py`**

```python
def find_cosine_match(
    dims: QueryDimensions, query_text: str
) -> Optional[str]:
    """Fallback when anchor_text isn't found. Compute the query
    embedding via Voyage, then find the candidate chunk with the
    highest cosine similarity. Returns the chunk_id, or None when no
    candidates match the dimensions."""
    import voyageai

    sql = """
        SELECT c.chunk_id, c.embedding <=> %s::vector AS distance
        FROM chunks c
        JOIN documents d ON d.doc_id = c.doc_id
        WHERE d.publisher = %s
          AND c.doc_type = %s
          AND c.fiscal_year = %s
          AND (%s IS NULL OR %s = ANY(c.agency_canonical_ids))
          AND c.embedding IS NOT NULL
        ORDER BY distance ASC
        LIMIT 1
    """
    vo = voyageai.Client()
    embedding = vo.embed([query_text], model="voyage-3-large").embeddings[0]
    with get_connection() as conn:
        row = conn.execute(
            sql,
            (
                embedding,
                dims.publisher,
                dims.doc_type,
                dims.fiscal_year,
                dims.agency,
                dims.agency,
            ),
        ).fetchone()
    return row["chunk_id"] if row else None


def refresh_queries_file(path: str) -> dict[str, int]:
    """Walk every query in the YAML; refresh stale chunk_ids in place.
    Returns a summary dict: refreshed, manual_review, unchanged."""
    from ruamel.yaml import YAML

    yaml = YAML()
    yaml.indent(mapping=2, sequence=4, offset=2)
    with open(path, encoding="utf-8") as f:
        data = yaml.load(f) or []

    refreshed = 0
    manual_review = 0
    unchanged = 0
    review_ids: list[str] = []

    for query in data:
        for expected in query.get("expected_chunks", []):
            cid = expected.get("chunk_id")
            if not cid:
                continue
            if chunk_exists(cid):
                unchanged += 1
                continue

            dims_raw = expected.get("dimensions", {})
            dims = QueryDimensions(
                publisher=dims_raw["publisher"],
                doc_type=dims_raw["doc_type"],
                fiscal_year=dims_raw["fiscal_year"],
                agency=dims_raw.get("agency"),
            )
            anchor = expected.get("anchor_text")
            new_id = None
            if anchor:
                new_id = find_anchor_match(dims, anchor)
            if new_id is None:
                new_id = find_cosine_match(dims, query.get("query", ""))
            if new_id is None:
                manual_review += 1
                review_ids.append(query.get("id", "?"))
                continue
            expected["chunk_id"] = new_id
            refreshed += 1

    with open(path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    return {
        "refreshed": refreshed,
        "manual_review": manual_review,
        "unchanged": unchanged,
        "review_ids": review_ids,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Refresh stale chunk_ids in eval/queries.yaml"
    )
    parser.add_argument(
        "--queries", default="eval/queries.yaml",
        help="Path to queries.yaml",
    )
    args = parser.parse_args()

    print(f"Checking chunk_id validity against current corpus...")
    summary = refresh_queries_file(args.queries)
    print(
        f"\n  ✓ {summary['unchanged']} queries: chunk_id still valid"
    )
    if summary["refreshed"]:
        print(
            f"  ⚠ {summary['refreshed']} queries: chunk_id refreshed via "
            "anchor_text or cosine fallback"
        )
    if summary["manual_review"]:
        print(
            f"  ✗ {summary['manual_review']} queries: no candidate matched "
            "dimensions — manual review needed"
        )
        for qid in summary["review_ids"]:
            print(f"    - {qid}")
        print(
            f"\nEdit {args.queries} manually for these queries (or delete "
            "if the underlying entity is gone)."
        )
        sys.exit(1 if summary["manual_review"] else 0)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the tests, confirm they PASS**

```bash
uv run pytest tests/test_eval_refresh.py -v
```

Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/refresh_chunk_ids.py tests/test_eval_refresh.py
git commit -m "feat(eval): refresh cosine fallback + YAML round-trip + main

find_cosine_match embeds the query via Voyage and finds the highest-
similarity chunk matching the dimensions. refresh_queries_file walks
queries.yaml, refreshes stale chunk_ids in place (preferring anchor
match, falling back to cosine), preserves YAML structure via
ruamel.yaml. main() reports refreshed/manual_review counts and exits
non-zero when any query needs manual review."
```

---

## Task 10: Calibration tool — threshold sweep

**Files:**
- Create: `eval/calibrate_refusal.py`
- Create: `tests/test_eval_calibrate.py`
- Create: `tests/fixtures/eval_result_sample.json`

- [ ] **Step 1: Create the fixture**

Create `tests/fixtures/eval_result_sample.json`:

```json
{
  "git_sha": "abc1234",
  "timestamp": "2026-05-20T18:30Z",
  "summary": {
    "recall_at_5": 0.8,
    "recall_at_20": 0.9,
    "fallback_rate": 0.0,
    "latency_p50_ms": 1000,
    "latency_p95_ms": 2000,
    "refusal_precision": 0.8,
    "refusal_recall": 0.8,
    "by_type": {}
  },
  "per_query": [
    {"id": "q-001", "type": "lookup", "status": "pass", "matched_via": "chunk_id", "rank": 2, "latency_ms": 850, "top_score": 0.55, "top_chunk_ids": ["a"]},
    {"id": "q-002", "type": "lookup", "status": "pass", "matched_via": "chunk_id", "rank": 1, "latency_ms": 700, "top_score": 0.72, "top_chunk_ids": ["b"]},
    {"id": "q-003", "type": "lookup", "status": "pass", "matched_via": "chunk_id", "rank": 3, "latency_ms": 900, "top_score": 0.48, "top_chunk_ids": ["c"]},
    {"id": "q-004", "type": "refusal", "status": "fail", "latency_ms": 1100, "top_score": 0.35, "top_chunk_ids": ["d"]},
    {"id": "q-005", "type": "refusal", "status": "pass", "latency_ms": 1200, "top_score": 0.15, "top_chunk_ids": ["e"]},
    {"id": "q-006", "type": "refusal", "status": "pass", "latency_ms": 1050, "top_score": 0.22, "top_chunk_ids": ["f"]}
  ]
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_eval_calibrate.py`:

```python
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
```

- [ ] **Step 3: Run the test, confirm it FAILS**

```bash
uv run pytest tests/test_eval_calibrate.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'eval.calibrate_refusal'`.

- [ ] **Step 4: Implement `eval/calibrate_refusal.py`**

```python
"""Refusal threshold calibration.

Reads the most recent eval result file, sweeps candidate thresholds,
computes precision/recall for each, recommends the threshold that
maximizes the combined score.

The recommended threshold is a SUGGESTION. The runtime threshold is
currently embedded in the MCP system prompt at
`mcp-server/system-prompt.md` (lines mentioning `refusal_no_retrieval
— top_score < 0.30`, with a second reference in the rules table).
Updating it means editing those prompt lines, NOT flipping a Python
constant. The original Phase 1b plan envisioned a constant in
retrieval/pipeline.py named REFUSAL_RERANKER_THRESHOLD; that was
never built and the prompt holds the value instead.

Invocation:
    uv run python -m eval.calibrate_refusal
    uv run python -m eval.calibrate_refusal --result eval/results/specific.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_THRESHOLDS = [0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40]


def compute_sweep(
    result_path: str, thresholds: list[float] = DEFAULT_THRESHOLDS
) -> list[dict]:
    """For each candidate threshold, recompute refusal_precision and
    retrieval_pass_rate from the result file's per_query data."""
    with open(result_path, encoding="utf-8") as f:
        data = json.load(f)

    per_query = data["per_query"]
    refusal_queries = [p for p in per_query if p["type"] == "refusal"]
    retrieval_queries = [p for p in per_query if p["type"] != "refusal"]
    total_refusal = len(refusal_queries)
    total_retrieval = len(retrieval_queries)

    table: list[dict] = []
    for threshold in thresholds:
        # Refusal precision: of queries the threshold would cause to
        # refuse, how many were expected to refuse?
        would_refuse_correct = sum(
            1
            for p in refusal_queries
            if p["top_score"] < threshold
        )
        would_refuse_incorrect = sum(
            1
            for p in retrieval_queries
            if p["top_score"] < threshold
        )
        would_refuse_total = would_refuse_correct + would_refuse_incorrect
        # Precision: of queries the threshold would cause to refuse, what
        # share were correct refusals? Denominator is would_refuse_total
        # (NOT total_refusal — that would be recall).
        if would_refuse_total == 0:
            refusal_precision = 0.0
        else:
            refusal_precision = would_refuse_correct / would_refuse_total

        # Retrieval pass rate: of retrieval queries, how many still
        # have top_score >= threshold (i.e., we DIDN'T accidentally
        # refuse them)?
        retrieval_passes = sum(
            1
            for p in retrieval_queries
            if p["top_score"] >= threshold
        )
        retrieval_pass_rate = (
            retrieval_passes / total_retrieval if total_retrieval else 0.0
        )

        table.append(
            {
                "threshold": threshold,
                "refusal_precision": refusal_precision,
                "retrieval_passes": retrieval_passes,
                "retrieval_pass_rate": retrieval_pass_rate,
                "combined_score": (refusal_precision + retrieval_pass_rate) / 2,
            }
        )
    return table


def recommend_threshold(table: list[dict]) -> dict:
    """Pick the row with the highest combined_score (ties broken by
    lower threshold — prefer being less restrictive)."""
    return max(
        table,
        key=lambda r: (r["combined_score"], -r["threshold"]),
    )


def find_latest_result(results_dir: Path = Path("eval/results")) -> Path:
    files = sorted(results_dir.glob("*.json"), reverse=True)
    if not files:
        raise FileNotFoundError(
            f"No eval result files in {results_dir}; run "
            "`uv run python -m eval.run_eval` first."
        )
    return files[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Sweep refusal thresholds; recommend best"
    )
    parser.add_argument(
        "--result", default=None,
        help="Path to specific eval result JSON. Default: latest in eval/results/",
    )
    args = parser.parse_args()

    if args.result:
        result_path = args.result
    else:
        result_path = str(find_latest_result())

    print(f"Loading {result_path}...")
    table = compute_sweep(result_path)
    print(
        f"\nSweeping candidate thresholds against {result_path}:\n"
    )
    print(
        f"  {'threshold':>10}  {'refusal_precision':>18}  "
        f"{'retrieval_pass_rate':>20}  {'combined':>10}"
    )
    for row in table:
        print(
            f"  {row['threshold']:>10.2f}  "
            f"{row['refusal_precision']:>18.2f}  "
            f"{row['retrieval_pass_rate']:>20.2f}  "
            f"{row['combined_score']:>10.2f}"
        )

    pick = recommend_threshold(table)
    print(
        f"\nRecommended threshold: {pick['threshold']:.2f}"
    )
    print(
        "To apply: edit the `top_score < 0.30` references in "
        "mcp-server/system-prompt.md (the `refusal_no_retrieval` "
        "section + the rules table) to use the new value, then re-run "
        "the dogfood tests."
    )
    print(
        f"Justified by: {result_path} (refusal_precision="
        f"{pick['refusal_precision']:.2f}, retrieval_pass_rate="
        f"{pick['retrieval_pass_rate']:.2f})"
    )


if __name__ == "__main__":
    main()
```

- [ ] **Step 5: Run the tests, confirm they PASS**

```bash
uv run pytest tests/test_eval_calibrate.py -v
```

Expected: 2 passed.

- [ ] **Step 6: Run calibration against the first real eval result**

```bash
uv run python -m eval.calibrate_refusal
```

Expected: prints the sweep table + a recommended threshold. Note the recommendation; do NOT edit `retrieval/pipeline.py` automatically — that's a deliberate decision.

- [ ] **Step 7: Commit**

```bash
git add eval/calibrate_refusal.py tests/test_eval_calibrate.py tests/fixtures/eval_result_sample.json
git commit -m "feat(eval): refusal threshold calibration tool

compute_sweep reads an eval result JSON, recomputes precision/recall
for each candidate threshold. recommend_threshold picks the row with
the best combined score (precision + retrieval pass rate, halved).
Run after every meaningful corpus or model change; updating
REFUSAL_RERANKER_THRESHOLD in retrieval/pipeline.py stays a manual
decision."
```

---

## Task 11: Documentation + CLAUDE.md addition

**Files:**
- Create: `eval/README.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Create `eval/README.md`**

```markdown
# Eval Harness — Layer 1 (Retrieval)

Pure-retrieval eval. Calls `retrieve()` directly (bypasses MCP and
Claude) so changes to chunking, BM25 weights, rerank config, and
filter logic are measurable in 30 seconds instead of dogfooded.

Layer 2 (end-to-end agent eval with faithfulness scoring) is deferred
until WS3 (faithfulness verifier) ships.

## Running it

After any change to `retrieval/`, `ingest/`, `chunking/`, or
`mcp-server/system-prompt.md`:

```bash
set -a; source .env.local; set +a
uv run python -m eval.run_eval
```

Takes ~30 seconds. Output:
- `eval/results/<UTC-ISO>-<git-sha>.json` (machine-readable)
- `eval/results/<UTC-ISO>-<git-sha>.md` (human-readable summary with
  deltas vs. previous run)

Both are committed to git so the history travels with the repo. Diff
two runs with `git diff eval/results/<old>.json eval/results/<new>.json`.

## The query set

`eval/queries.yaml` has ~35 queries. Each query carries:
- The question
- One or more expected_chunks (hybrid: chunk_id + dimensions +
  anchor_text)
- Type (`lookup` / `comparison` / `refusal`)

Scoring:
- **Lookup** passes if any expected chunk is in top K (preferring
  chunk_id, falling back to dimensions match).
- **Comparison** passes if ALL expected chunks are in top K.
- **Refusal** passes if retrieval correctly declined (top_score <
  threshold).

## After a re-ingest

Chunk boundaries can change during ingest. Run:

```bash
uv run python -m eval.refresh_chunk_ids
```

This walks queries.yaml, finds successor chunk_ids for any entries
whose chunk_id no longer exists, and writes the YAML back in place.
Anchor-text matching is preferred (deterministic); cosine similarity
is the fallback. Entries that can't be repaired are flagged for
manual review.

## Calibrating the refusal threshold

After the corpus or rerank model changes:

```bash
uv run python -m eval.calibrate_refusal
```

This sweeps candidate thresholds against the most recent eval result
and recommends the one with the best precision/recall balance. The
runtime threshold currently lives in the MCP system prompt
(`mcp-server/system-prompt.md` — search for `refusal_no_retrieval —
top_score < 0.30` and the rules-table reference); updating it means
editing those prompt lines, not flipping a Python constant.

## Adding queries

Two paths:

1. **Re-run the synthesizer to add more:**
   ```bash
   uv run python -m eval.synthesize_queries --append --lookup 10
   ```
   Adds 10 new lookup queries to the existing set without disturbing
   the existing ones. Costs ~$1 in Anthropic API spend.

2. **Hand-write directly in `eval/queries.yaml`:** follow the schema
   in `eval/schema.py::EvalQuery`. Pick a unique `id` like `q-100`,
   write the query and expected_chunks. Run the eval; if your hand-
   written query passes you're done.

## Files

| File | Purpose |
|---|---|
| `queries.yaml` | Ground truth — questions + expected_chunks |
| `schema.py` | Pydantic models for queries + results |
| `scoring.py` | Pure recall + refusal scoring functions |
| `synthesize_queries.py` | One-shot LLM-driven query generator |
| `run_eval.py` | Main runner — calls retrieve(), scores, writes results |
| `refresh_chunk_ids.py` | Post-reingest stale-chunk_id fixer |
| `calibrate_refusal.py` | Threshold sweep + recommendation |
| `results/` | Git-tracked result files (one JSON + one MD per run) |
```

- [ ] **Step 2: Add the reminder line to `CLAUDE.md`**

Open `CLAUDE.md` and find the "Working Rules" section. Add this entry to the existing rule list (after "Pushing to master green-lights closing the dev server."):

```markdown
**Run the eval after any change to `retrieval/`, `ingest/`, `chunking/`, or `mcp-server/system-prompt.md`.** Command: `uv run python -m eval.run_eval`. Takes ~30 seconds; commit the resulting `eval/results/<...>.{json,md}` files alongside the code change so regressions are visible in PR diffs. After re-ingest, run `uv run python -m eval.refresh_chunk_ids` first to repair any stale chunk_ids.
```

- [ ] **Step 3: Commit**

```bash
git add eval/README.md CLAUDE.md
git commit -m "docs: eval/README.md + CLAUDE.md before-push reminder

README explains how to run the eval, refresh stale chunk_ids after
re-ingest, calibrate the refusal threshold, and add queries.
CLAUDE.md instructs Claude (and human contributors) to run the eval
before pushing changes to retrieval / ingest / chunking / system
prompt."
```

---

## Task 12: Final verification + PR

**Files:** none — verifies the full harness end-to-end.

- [ ] **Step 1: Run the full test suite**

```bash
uv run pytest tests/test_eval_*.py -v
```

Expected: all eval tests pass (~25-30 total).

- [ ] **Step 2: Run the full repo test suite for regressions**

```bash
uv run pytest -q
```

Expected: no NEW failures introduced. The 3 pre-existing bm25 integration test failures (per STATUS.md) may still fail — that's not our regression.

- [ ] **Step 3: Confirm the eval works end-to-end**

```bash
set -a; source .env.local; set +a
uv run python -m eval.run_eval
```

Expected: a new pair of files appears in `eval/results/`. The summary line at the end shows non-zero recall numbers. If recall@5 is below 50% on lookup queries, that's a meaningful finding — capture in the PR description as a Phase 1b WS8 pass-bar observation.

- [ ] **Step 4: Update STATUS.md inside the worktree (before opening the PR)**

The status change is part of the diff under review — not a follow-up commit on master.

Open `STATUS.md`. Move the WS8 entry out of "Not yet implemented" and into "What's shipped" with a short paragraph describing the eval harness (synthesizer, runner, refresh tool, calibration tool, ~35 queries, JSON+MD result files, `eval/README.md`). Update the Phase 1b row in the phase summary table to note WS8 is now done.

```bash
git add STATUS.md
git commit -m "docs(STATUS): eval harness shipped — WS8 done"
```

- [ ] **Step 5: Open the PR**

```bash
git push -u origin eval-harness
gh pr create --title "feat: retrieval eval harness (layer 1)" --body "$(cat <<'EOF'
## Summary

Implements the design at `docs/superpowers/specs/2026-05-20-retrieval-eval-harness-design.md` (Layer 1 — retrieval only). Closes the Phase 1b WS8 workstream that was deferred during the vertical-slice reframe.

- `eval/queries.yaml` — ~35 LLM-synthesized queries with hybrid ground truth (chunk_id + dimensions + anchor_text)
- `eval/synthesize_queries.py` — one-shot generator using Claude Opus 4.7
- `eval/run_eval.py` — calls `retrieve()` directly, scores per-query, emits git-committed JSON+MD
- `eval/refresh_chunk_ids.py` — post-reingest fixer (anchor_text → cosine similarity fallback)
- `eval/calibrate_refusal.py` — threshold sweep + recommendation
- `eval/README.md` + `CLAUDE.md` reminder
- `STATUS.md` updated to reflect WS8 shipping

Layer 2 (end-to-end agent eval with faithfulness scoring) is deferred until WS3 (faithfulness verifier) lands — separate spec.

## Test plan

- [x] All eval unit tests pass (`uv run pytest tests/test_eval_*.py`)
- [x] No regressions in the broader test suite (`uv run pytest -q`)
- [x] First real synthesis run produced eval/queries.yaml (committed)
- [x] First real eval-against-corpus run produced eval/results/<...>.{json,md} (committed)
- [ ] Manual: run `uv run python -m eval.calibrate_refusal` against the first real result and confirm the recommendation makes sense

## Cost

- Synthesizer: ~\$2-3 in Anthropic API spend per full synthesis (one-time + on `--append`)
- Eval run: ~\$0.01 in Voyage rerank API spend per run

EOF
)"
```

- [ ] **Step 6: Clean up after merge**

Once the PR is merged:

```bash
cd ~/ask-the-budget-az-dev
git fetch origin && git pull origin master
git worktree remove --force ~/ask-the-budget-az-worktrees/eval-harness
git branch -D eval-harness
```

---

## Spec-coverage self-review

Walking the spec section by section:

- **Section 1 — queries.yaml schema.** Implemented in Task 1 (Pydantic models) and Task 2 (scoring respects the hybrid). ✓
- **Section 2 — Synthesizer.** Implemented in Tasks 3 (lookup) and 4 (comparison + refusal + main + first real run). Composition (25/5/5), vocabulary-contamination prompt, anchor_text, cost notes all covered. ✓
- **Section 3 — Runner.** Implemented in Tasks 5 (load + iterate + per-query), 6 (aggregate + JSON), 7 (Markdown + delta vs prev). JSON+MD output format, atomic write, git-committed results all covered. ✓
- **Section 4 — Refresh tool.** Implemented in Tasks 8 (chunk_exists + anchor_text) and 9 (cosine + YAML round-trip + main). Manual-review path included. ✓
- **Section 5 — Calibration.** Implemented in Task 10. Sweep + recommendation, separate from run_eval as the spec called for. ✓
- **Section 6 — Docs + CLAUDE.md.** Implemented in Task 11. ✓

Scope summary table in the spec — all 9 files covered. Estimated landing (~3-4 days) is consistent with the 12-task structure.

Open items deferred to writing-plans (per the spec's last section):
- Exact synthesizer prompt — included verbatim in Task 3 / Task 4 (lookup + comparison + refusal prompts).
- Anthropic SDK version pin — `anthropic>=0.40` in Task 0.
- JSON verbosity — Task 5/6 picks "chunk_ids only" (top_chunk_ids: list[str]) rather than full chunk records, to keep result files small. Acceptable per the spec's "compact, enough for scoring" note.

No placeholders, no `TBD`, every code step has the actual code.
