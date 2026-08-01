# Agent-Loop Eval (Layer 2) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Layer 2 agent-loop eval — a transcript-first runner that drives the real `harness/` session per query, a free mechanical scorer, an LLM judge, and a run-comparison tool — per the approved spec `docs/superpowers/specs/2026-08-01-agent-loop-eval-design.md`.

**Architecture:** `eval/run_agent_eval.py` constructs a fresh `HarnessSession` per query (production code path, no server) with injected no-op spend gates so eval runs never touch the office ledger, and records everything to one JSONL transcript per query under `eval/results/agent/<UTC>-<sha>/`. Scoring is decoupled: `eval/score_agent_run.py` (mechanical, free, re-runnable) and `eval/judge_agent_run.py` (LLM judge, full runs only) both read transcripts; `eval/compare_agent_runs.py` diffs two run directories.

**Tech Stack:** Python 3.12, pydantic v2, ruamel.yaml, httpx (judge calls + the existing MockTransport test fakes), pytest via `uv run pytest`.

## Global Constraints

- Python ≥ 3.12; every new module starts with `from __future__ import annotations` and a docstring explaining WHY (repo convention).
- Non-trivial lines get WHY comments (CLAUDE.md — Destin is a non-developer).
- Every CLI `main()` starts with `try: sys.stdout.reconfigure(encoding="utf-8")\nexcept Exception: pass` (Windows cp1252 convention, `eval/run_eval.py:342-346`).
- Results naming: `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")` + short git sha via `subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], text=True).strip()` (fallback `"unknown"`). Agent-eval results live ONLY under `eval/results/agent/` — never mixable with Layer 1 files.
- JSON files are written atomically: write to `path.with_suffix(path.suffix + ".tmp")` then `tmp.replace(path)`.
- Live runs must NEVER write the office spend ledger or read/write `settings.json` mid-run: `HarnessSession` gets `check_limit=` / `record_usage=` injections and an explicit `settings=` object.
- The API key never appears in any output file (manifest, transcript, scores, judge). Redact to `api_key_set: true/false`.
- All tests are money-free: model traffic is faked with the `Provider` / `httpx.MockTransport` helpers from `tests/test_harness_session.py` (importable — `tests/` is a package and `tests/test_notices.py:32` already imports from it).
- Tests live in flat `tests/` as `tests/test_eval_agent_*.py`; fixtures under `tests/fixtures/`.
- One query failing (exception, provider error) must never abort a run or a scoring pass — mirror `eval/run_eval.py:94-110`.
- Work in a worktree; run `uv run pytest tests/test_eval_agent_*.py` green before each commit.

## Key upstream interfaces (verified 2026-08-01, with file:line)

The implementer sees only their task — this block is the shared contract.

- `HarnessSession.__init__` (`harness/session.py:387-405`): `(conversation_id, corpus="budget", tier=DEFAULT_TIER, user="", settings=None, executor=None, transport=None, *, system_prompt=None, prompt_builder=None, tools=None, history=None, context_chars=..., sleep=None, check_limit=..., record_usage=...)`.
- `session.send_turn(text, on_event=None, *, tier=None) -> dict` (`harness/session.py:479-498`): pushes event dicts to `on_event`, returns the terminal frame. Always `session.close()` after (`:461`). Fresh session per query (the first-call top_k cap is per-`ToolExecutor` instance — `harness/tools.py:976-977`).
- Terminal `_done` frame (`harness/session.py:1750-1759`): `{"type": "_done", "stopReason", "finalAnswer", "incompleteNote", "citations", "retrievedChunkIds", "toolCalls", "usage": {"inputTokens", "outputTokens", "cacheReadTokens", "cacheCreationTokens", "cost"}}`. Error terminal: `{"type": "_error", "message"}`.
- `toolCalls[i]` = `{"toolUseId", "toolName", "input" (parsed dict), "output" (JSON **string**), "isError"}` (`:1656-1664`). `citations[i]` = camelCase `{"chunkId", "claimSpan", "confidence", "quote", "spanStart", "spanEnd", "citationId", "ok", "error"}` (`:1703-1715`).
- retrieve output JSON (parsed from the string): `{"top_score", "retrieval_id", "bm25_count", "dense_count", "fused_count", "chunks": [{"chunk_id", "doc_id", "doc_title", "publisher", "fiscal_year", "doc_type", "section_path", "page_start", "page_end", "bbox", "text", "text_length", "score"}], ...optional "first_call_capped", "inferred_fiscal_years", "deep_dive_ignored", "note"}` (`harness/tools.py:1083-1134`).
- cite result: success `{"ok": true, "citation_id", "resolved_span_start", "resolved_span_end", ...}`; failure `{"ok": false, "error", ...}`; `cite_batch` output = `{"citations": [per-slot results]}` index-parallel to `input["citations"]` (`harness/tools.py:1196-1224`). Ambiguity error contains the literal text `"appears multiple times"` (`retrieval/citations.py:521-535`).
- `LimitStatus(status, message, reason, limit_usd, month_usd)` dataclass (`harness/ledger.py:589-618`).
- `record_usage(user, tier, model, tokens_in, tokens_out, cost_usd=None, *, cached_tokens=0, now=None)` (`harness/ledger.py:208-217`) — the runner injects its own recorder with this exact signature.
- `load_settings(path=None) -> Settings` (frozen dataclass; `harness/settings.py:457`); `Settings(provider: ProviderConfig, tiers: dict[str, TierConfig], ...)`; `TierConfig(model, enabled=None)`; `ai_available(settings, tier) -> tuple[bool, str|None]` (`:223`). Pin a model with `dataclasses.replace(settings, tiers={...})`.
- `reset_model_overrides()` (`harness/session.py:302`) — call before each query so a transient S13 fallback in query 3 can't silently re-model queries 4..N.
- `ChunkStore(root=None).count(name) -> int` (`store/chunk_store.py:53,125`); tables `"budget_chunks"` / `"fiscal_note_chunks"`.
- Test fakes (`tests/test_harness_session.py`): `Provider(*response_factories)` (`.transport()`, last entry repeats), `sse(*chunks, done=True)`, `text_chunk(text)`, `tool_chunk(slot, call_id=, name=, arguments=)`, `finish_chunk(reason)`, `usage_chunk(prompt=, completion=, cost=, cached=)`, `FakeExecutor` (`.execute(name, args) -> str`, records `.calls`), `make_settings()`.

## File structure

| File | Responsibility |
|---|---|
| `eval/agent_schema.py` (new) | Query-set pydantic models + loader |
| `eval/agent_queries.yaml` (new) | The ~30-query set (authored Task 8) |
| `eval/agent_transcript.py` (new) | Transcript JSONL write/read + accessor helpers |
| `eval/agent_scoring.py` (new) | Key-fact matchers + per-transcript mechanical metrics + aggregation |
| `eval/run_agent_eval.py` (new) | CLI runner (live model calls) |
| `eval/score_agent_run.py` (new) | CLI mechanical scorer → `scores.json` / `scores.md` |
| `eval/judge_agent_run.py` (new) | CLI LLM judge → `judge.json` |
| `eval/agent_judge_prompt.md` (new) | Versioned judge prompt |
| `eval/compare_agent_runs.py` (new) | CLI run-vs-run diff → markdown report |
| `eval/README.md` (modify) | Layer 2 section |
| `STATUS.md` (modify) | Ship entry |
| `tests/test_eval_agent_{schema,scoring,transcript,runner,judge,compare,queries}.py` (new) | One test module per unit |
| `tests/fixtures/agent_transcript_sample.jsonl` (new) | Golden transcript fixture (built by Task 3's writer) |

---

### Task 1: Query schema + loader

**Files:**
- Create: `eval/agent_schema.py`
- Test: `tests/test_eval_agent_schema.py`

**Interfaces:**
- Produces: `KeyFact(kind: Literal["currency","string","regex"], value: str)`; `AgentQuery(id, question, corpus, tier, shape, subsets, should_refuse, key_facts, judge_notes)`; `load_agent_queries(path) -> list[AgentQuery]` (raises `ValueError` on duplicate ids).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_agent_schema.py
"""Schema tests for the Layer 2 agent-eval query set.

Why: the query file is hand-and-agent-authored YAML; a typo'd field must
fail loudly at load time, not silently score as 0.
"""
from __future__ import annotations

import pytest

from eval.agent_schema import AgentQuery, KeyFact, load_agent_queries

VALID = """
- id: aq-001
  question: What was ADC's FY 2025 General Fund appropriation?
  corpus: budget
  tier: standard
  shape: lookup
  subsets: [smoke, full]
  should_refuse: false
  key_facts:
    - kind: currency
      value: "$1,391,157,700"
    - kind: string
      value: "Department of Corrections"
  judge_notes: "AFR figure preferred over Baseline per accuracy hierarchy."
"""


def _write(tmp_path, text):
    p = tmp_path / "queries.yaml"
    p.write_text(text, encoding="utf-8")
    return p


def test_valid_entry_loads_with_defaults(tmp_path):
    queries = load_agent_queries(_write(tmp_path, VALID))
    assert len(queries) == 1
    q = queries[0]
    assert q.id == "aq-001"
    assert q.corpus == "budget"
    assert q.tier == "standard"
    assert q.shape == "lookup"
    assert q.key_facts[0] == KeyFact(kind="currency", value="$1,391,157,700")


def test_defaults_applied(tmp_path):
    minimal = """
- id: aq-002
  question: Is out of scope?
  shape: refusal
  should_refuse: true
"""
    q = load_agent_queries(_write(tmp_path, minimal))[0]
    assert q.corpus == "budget" and q.tier == "standard"
    assert q.subsets == ["full"] and q.key_facts == [] and q.judge_notes == ""


def test_unknown_corpus_rejected(tmp_path):
    bad = VALID.replace("corpus: budget", "corpus: postgres")
    with pytest.raises(Exception):
        load_agent_queries(_write(tmp_path, bad))


def test_duplicate_ids_rejected(tmp_path):
    with pytest.raises(ValueError, match="duplicate"):
        load_agent_queries(_write(tmp_path, VALID + VALID))
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.agent_schema'`

- [ ] **Step 3: Implement**

```python
# eval/agent_schema.py
"""Query-set schema for the Layer 2 agent-loop eval.

Separate from eval/schema.py (Layer 1) on purpose: Layer 1 queries pin
ground-truth chunk_ids for a deterministic retrieval regression detector;
Layer 2 queries pin ANSWER-level key facts for a stochastic agent eval.
Mixing the two schemas would invite cross-diffing runs that measure
different things (the same reason Layer 1 prefixes fiscal-note results).
"""
from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field
from ruamel.yaml import YAML


class KeyFact(BaseModel):
    """One mechanically checkable fact a correct answer must contain.

    kind=currency matches numbers with formatting tolerance
    ($1,234.5M == 1234.5 million); string is a case-insensitive
    substring; regex is a case-insensitive search pattern.
    """

    kind: Literal["currency", "string", "regex"]
    value: str


class AgentQuery(BaseModel):
    id: str
    question: str
    corpus: Literal["budget", "fiscal_notes"] = "budget"
    tier: Literal["standard", "deep_research"] = "standard"
    # shape drives authoring quotas and per-shape score breakdowns.
    shape: Literal["lookup", "comparison", "analyze", "memo", "refusal", "historical"]
    # subset tags select what a run includes: smoke (~10), full (all
    # standard-tier), dr-probe (the 4 deep_research queries).
    subsets: list[str] = Field(default_factory=lambda: ["full"])
    should_refuse: bool = False
    key_facts: list[KeyFact] = Field(default_factory=list)
    judge_notes: str = ""


def load_agent_queries(path: str | Path) -> list[AgentQuery]:
    yaml = YAML(typ="safe")
    with open(path, encoding="utf-8") as f:
        raw = yaml.load(f) or []
    queries = [AgentQuery.model_validate(q) for q in raw]
    ids = [q.id for q in queries]
    if len(ids) != len(set(ids)):
        # Duplicate ids would silently overwrite each other's transcripts
        # (one file per id), so a run would LOOK complete while missing data.
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        raise ValueError(f"duplicate query ids: {dupes}")
    return queries
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_schema.py -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/agent_schema.py tests/test_eval_agent_schema.py
git commit -m "feat(eval): agent-eval query schema + loader (Layer 2)"
```

---

### Task 2: Key-fact matchers

**Files:**
- Create: `eval/agent_scoring.py` (matchers only — Task 5 extends this file)
- Test: `tests/test_eval_agent_scoring.py`

**Interfaces:**
- Consumes: `KeyFact` from Task 1.
- Produces: `fact_matches(fact: KeyFact, text: str) -> bool`; `currency_values(text: str) -> set[float]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_agent_scoring.py
"""Key-fact matcher tests. Currency tolerance is the load-bearing part:
models restate $1,391,157,700 as '$1,391.2 million' or '$1.4 billion',
and an exact-string matcher would score every correct answer as wrong.
"""
from __future__ import annotations

from eval.agent_schema import KeyFact
from eval.agent_scoring import currency_values, fact_matches


def cf(v):
    return KeyFact(kind="currency", value=v)


def test_currency_exact_form():
    assert fact_matches(cf("$1,391,157,700"), "ADC received $1,391,157,700 from the General Fund.")


def test_currency_scale_words_and_suffixes_are_equivalent():
    assert fact_matches(cf("$1,234.5M"), "the total was 1234.5 million dollars")
    assert fact_matches(cf("$2.5 billion"), "roughly $2,500 million")


def test_currency_rounding_within_half_percent_matches():
    # 1,391.2M vs 1,391,157,700 differs by ~0.003% — a faithful rounding.
    assert fact_matches(cf("$1,391,157,700"), "about $1,391.2 million")


def test_currency_wrong_number_rejected():
    assert not fact_matches(cf("$1,391,157,700"), "ADC received $1,214,000,000.")


def test_currency_ignores_fiscal_years_as_numbers():
    # 'FY 2025' must not parse as the number 2025 matching a $2,025 fact
    # by accident of formatting-insensitive comparison at 0.5% tolerance.
    assert not fact_matches(cf("$2,032"), "In FY 2025 the fee was unchanged.")


def test_string_fact_case_insensitive():
    assert fact_matches(KeyFact(kind="string", value="Department of Corrections"),
                        "the department of corrections budget grew")


def test_regex_fact():
    assert fact_matches(KeyFact(kind="regex", value=r"70\.7\d?%"), "the rate is 70.70%")


def test_currency_values_parser():
    vals = currency_values("$1.5 billion and $300,000 and 12 million")
    assert 1.5e9 in vals and 300_000.0 in vals and 12e6 in vals
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.agent_scoring'`

- [ ] **Step 3: Implement**

```python
# eval/agent_scoring.py
"""Mechanical scoring for Layer 2 agent transcripts.

This module is deliberately free of model calls: everything here can be
re-run over historical transcripts at zero cost, which is what makes
metric improvements retroactive (spec: 'Mechanical scorer — free,
decoupled').
"""
from __future__ import annotations

import math
import re

from eval.agent_schema import KeyFact

# A currency mention: optional $, digits with optional thousands commas
# and decimals, optional scale word/suffix. The $-or-scale requirement in
# currency_values() below keeps bare years ('FY 2025') out of the pool.
_CURRENCY_RE = re.compile(
    # The comma-grouped alternative MUST allow a decimal tail: without it
    # '$1,391.2 million' backtracks into '$1' + '391.2 million' — two wrong
    # numbers instead of one right one.
    r"(\$)?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(billion|million|thousand|[bmk])?(?![\w.])",
    re.IGNORECASE,
)
_SCALE = {"b": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}

# 0.5% relative tolerance: accepts faithful roundings ('$1,391.2 million'
# for $1,391,157,700, ~0.003% off) while still rejecting a neighboring
# budget line. Authors needing exactness use kind=regex instead.
_REL_TOL = 0.005


def currency_values(text: str) -> set[float]:
    """Every dollar amount mentioned in text, normalized to plain floats."""
    values: set[float] = set()
    for dollar, num, scale in _CURRENCY_RE.findall(text):
        # Require a $ sign or a scale word — a bare number like '2025'
        # is a year or a count, not a currency mention.
        if not dollar and not scale:
            continue
        values.add(float(num.replace(",", "")) * _SCALE.get(scale.lower(), 1.0))
    return values


def fact_matches(fact: KeyFact, text: str) -> bool:
    if fact.kind == "string":
        return fact.value.lower() in text.lower()
    if fact.kind == "regex":
        return re.search(fact.value, text, re.IGNORECASE) is not None
    wanted = currency_values(fact.value)
    if not wanted:
        # An unparseable currency fact is an authoring error; failing
        # closed here would hide it as a permanent query failure.
        raise ValueError(f"key fact is not a parseable currency amount: {fact.value!r}")
    found = currency_values(text)
    return any(
        any(math.isclose(w, f, rel_tol=_REL_TOL) for f in found) for w in wanted
    )
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_scoring.py -v`
Expected: 8 PASS. If `test_currency_ignores_fiscal_years_as_numbers` fails, the `$`-or-scale guard in `currency_values` is broken — do not loosen the test.

- [ ] **Step 5: Commit**

```bash
git add eval/agent_scoring.py tests/test_eval_agent_scoring.py
git commit -m "feat(eval): key-fact matchers with currency-formatting tolerance"
```

---

### Task 3: Transcript format — writer, reader, accessors

**Files:**
- Create: `eval/agent_transcript.py`
- Create: `tests/fixtures/agent_transcript_sample.jsonl` (generated in Step 5)
- Test: `tests/test_eval_agent_transcript.py`

**Interfaces:**
- Produces: `Transcript` dataclass (`meta: dict`, `events: list[dict]`, `terminal: dict`); `write_transcript(path, meta, events, terminal)`; `read_transcript(path) -> Transcript`; accessors `final_answer(t)`, `usage(t)`, `citations(t)`, `tool_calls(t, name=None)`, `parsed_output(call) -> dict|None`, `retrieve_calls(t) -> list[dict]` (each with a parsed `"chunks"` list), `wall_ms(t)`.
- Consumes: nothing project-internal.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_agent_transcript.py
"""Transcript round-trip + accessor tests.

Why: every downstream tool (scorer, judge, compare, citation replay)
reads transcripts. A silent format drift would corrupt all of them at
once, so the shape is pinned here.
"""
from __future__ import annotations

import json

from eval.agent_transcript import (
    Transcript,
    citations,
    final_answer,
    parsed_output,
    read_transcript,
    retrieve_calls,
    tool_calls,
    usage,
    wall_ms,
    write_transcript,
)

RETRIEVE_OUTPUT = json.dumps({
    "top_score": 4.2,
    "retrieval_id": "r-1",
    "bm25_count": 10, "dense_count": 10, "fused_count": 15,
    "chunks": [
        {"chunk_id": "c-1", "doc_id": "d-1", "doc_title": "FY 2025 Approps",
         "publisher": "jlbc", "fiscal_year": 2025, "doc_type": "approps-agency-pdf",
         "section_path": "ADC", "page_start": 3, "page_end": 3, "bbox": None,
         "text": "ADC General Fund appropriation of $1,391,157,700 in FY 2025.",
         "text_length": 60, "score": 4.2},
    ],
})

DONE_FRAME = {
    "type": "_done",
    "stopReason": "end_turn",
    "finalAnswer": "ADC received $1,391,157,700.",
    "incompleteNote": None,
    "citations": [{"chunkId": "c-1", "claimSpan": "ADC received $1,391,157,700.",
                   "confidence": "verbatim", "quote": "$1,391,157,700",
                   "spanStart": 30, "spanEnd": 44, "citationId": "cit-1",
                   "ok": True, "error": None}],
    "retrievedChunkIds": ["c-1"],
    "toolCalls": [
        {"toolUseId": "t-1", "toolName": "retrieve",
         "input": {"query": "ADC FY 2025"}, "output": RETRIEVE_OUTPUT, "isError": False},
        {"toolUseId": "t-2", "toolName": "cite",
         "input": {"chunk_id": "c-1", "quote": "$1,391,157,700",
                   "confidence": "verbatim", "claim_span": "ADC received $1,391,157,700."},
         "output": json.dumps({"ok": True, "citation_id": "cit-1",
                               "resolved_span_start": 30, "resolved_span_end": 44}),
         "isError": False},
    ],
    "usage": {"inputTokens": 900, "outputTokens": 120, "cacheReadTokens": 700,
              "cacheCreationTokens": 0, "cost": 0.0031},
}


def make_transcript(tmp_path, terminal_extra=None):
    path = tmp_path / "aq-001-r1.jsonl"
    meta = {"query_id": "aq-001", "repeat": 1, "started_at": "2026-08-01T12:00:00Z"}
    events = [{"type": "assistant_thinking", "uuid": "u1"},
              {"type": "tool_use", "toolUseId": "t-1", "toolName": "retrieve",
               "input": {"query": "ADC FY 2025"}}]
    terminal = {"frame": DONE_FRAME, "wall_ms": 48000}
    terminal.update(terminal_extra or {})
    write_transcript(path, meta, events, terminal)
    return path


def test_round_trip(tmp_path):
    t = read_transcript(make_transcript(tmp_path))
    assert isinstance(t, Transcript)
    assert t.meta["query_id"] == "aq-001"
    assert len(t.events) == 2
    assert t.terminal["frame"]["stopReason"] == "end_turn"


def test_accessors(tmp_path):
    t = read_transcript(make_transcript(tmp_path))
    assert final_answer(t) == "ADC received $1,391,157,700."
    assert usage(t)["cost"] == 0.0031
    assert citations(t)[0]["chunkId"] == "c-1"
    assert wall_ms(t) == 48000
    assert [c["toolName"] for c in tool_calls(t)] == ["retrieve", "cite"]
    assert len(tool_calls(t, "cite")) == 1
    rcs = retrieve_calls(t)
    assert rcs[0]["chunks"][0]["chunk_id"] == "c-1"


def test_parsed_output_survives_garbage():
    assert parsed_output({"output": "not json{"}) is None
    assert parsed_output({"output": json.dumps({"ok": True})}) == {"ok": True}


def test_truncated_transcript_reads_as_error(tmp_path):
    # A crash mid-run leaves a file without a terminal line; readers must
    # see an honest error, not an IndexError.
    path = make_transcript(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    t = read_transcript(path)
    assert t.terminal["frame"]["type"] == "_error"
    assert "truncated" in t.terminal["frame"]["message"]


def test_error_terminal_accessors_degrade(tmp_path):
    path = tmp_path / "err.jsonl"
    write_transcript(path, {"query_id": "aq-009", "repeat": 1},
                     [], {"frame": {"type": "_error", "message": "boom"}, "wall_ms": 10})
    t = read_transcript(path)
    assert final_answer(t) == ""
    assert usage(t) == {}
    assert citations(t) == [] and tool_calls(t) == [] and retrieve_calls(t) == []
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_transcript.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.agent_transcript'`

- [ ] **Step 3: Implement**

```python
# eval/agent_transcript.py
"""Transcript JSONL format for Layer 2 agent-eval runs.

One file per (query, repeat): a `meta` line, one `event` line per
harness event, and one `terminal` line carrying the session's _done (or
_error) frame plus wall-clock. Scoring is decoupled from running, so
this file IS the interface between the money-spending runner and every
free downstream tool.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Transcript:
    meta: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: dict[str, Any] = field(default_factory=dict)


def write_transcript(
    path: str | Path,
    meta: dict[str, Any],
    events: list[dict[str, Any]],
    terminal: dict[str, Any],
) -> None:
    lines = [json.dumps({"kind": "meta", **meta}, ensure_ascii=False)]
    lines += [json.dumps({"kind": "event", "event": e}, ensure_ascii=False) for e in events]
    lines.append(json.dumps({"kind": "terminal", **terminal}, ensure_ascii=False))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_transcript(path: str | Path) -> Transcript:
    meta: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row.pop("kind", None)
        if kind == "meta":
            meta = row
        elif kind == "event":
            events.append(row.get("event", {}))
        elif kind == "terminal":
            terminal = row
    if terminal is None:
        # A crash mid-run leaves no terminal line; synthesize an honest
        # error so scorers count it as a failure, not a crash of their own.
        terminal = {"frame": {"type": "_error", "message": "transcript truncated (no terminal line)"},
                    "wall_ms": None}
    return Transcript(meta=meta, events=events, terminal=terminal)


# ---- accessors --------------------------------------------------------
# All accessors degrade to empty values on _error terminals so scorers
# never special-case crashed queries.

def _frame(t: Transcript) -> dict[str, Any]:
    return t.terminal.get("frame", {}) or {}


def final_answer(t: Transcript) -> str:
    return _frame(t).get("finalAnswer") or ""


def usage(t: Transcript) -> dict[str, Any]:
    return _frame(t).get("usage") or {}


def citations(t: Transcript) -> list[dict[str, Any]]:
    return _frame(t).get("citations") or []


def tool_calls(t: Transcript, name: str | None = None) -> list[dict[str, Any]]:
    calls = _frame(t).get("toolCalls") or []
    return calls if name is None else [c for c in calls if c.get("toolName") == name]


def wall_ms(t: Transcript) -> int | None:
    return t.terminal.get("wall_ms")


def parsed_output(call: dict[str, Any]) -> dict[str, Any] | None:
    """The tool output is stored as a JSON string (harness convention);
    parse defensively — a malformed output must not crash scoring."""
    try:
        out = json.loads(call.get("output") or "")
    except (TypeError, ValueError):
        return None
    return out if isinstance(out, dict) else None


def retrieve_calls(t: Transcript) -> list[dict[str, Any]]:
    """Each retrieve call's parsed output dict (with its 'chunks' list),
    in call order. Calls whose output failed to parse are skipped."""
    results = []
    for call in tool_calls(t, "retrieve"):
        out = parsed_output(call)
        if out is not None:
            out.setdefault("chunks", [])
            results.append(out)
    return results
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_transcript.py -v`
Expected: 5 PASS

- [ ] **Step 5: Generate the shared fixture transcript**

Later tasks (scorer tests especially) need a realistic transcript on disk. Generate it FROM the writer so fixture and format can never drift:

```python
# scratch script — run once, do not commit the script
# uv run python - <<'EOF'
from pathlib import Path
from tests.test_eval_agent_transcript import DONE_FRAME, RETRIEVE_OUTPUT  # noqa
from eval.agent_transcript import write_transcript

write_transcript(
    Path("tests/fixtures/agent_transcript_sample.jsonl"),
    {"query_id": "aq-001", "repeat": 1, "started_at": "2026-08-01T12:00:00Z",
     "corpus": "budget", "tier": "standard"},
    [{"type": "assistant_thinking", "uuid": "u1"}],
    {"frame": DONE_FRAME, "wall_ms": 48000},
)
print("wrote tests/fixtures/agent_transcript_sample.jsonl")
# EOF
```

Then move `DONE_FRAME` / `RETRIEVE_OUTPUT` usage in the test to import-safe module level (they already are). Verify: `uv run python -c "from eval.agent_transcript import read_transcript; t = read_transcript('tests/fixtures/agent_transcript_sample.jsonl'); print(t.meta['query_id'])"` prints `aq-001`.

- [ ] **Step 6: Commit**

```bash
git add eval/agent_transcript.py tests/test_eval_agent_transcript.py tests/fixtures/agent_transcript_sample.jsonl
git commit -m "feat(eval): agent-eval transcript format + accessors + golden fixture"
```

---

### Task 4: The runner

**Files:**
- Create: `eval/run_agent_eval.py`
- Test: `tests/test_eval_agent_runner.py`

**Interfaces:**
- Consumes: Task 1 `load_agent_queries`/`AgentQuery`; Task 3 `write_transcript`; harness seams from the "Key upstream interfaces" block.
- Produces: run directory layout — `manifest.json`, `ledger.jsonl`, `<query_id>-r<N>.jsonl` per query×repeat; library functions `run_suite(queries, run_dir, session_factory, *, repeats=1, progress=print) -> None`, `make_session_factory(settings, run_dir)`, `build_manifest(settings, queries, *, subset, repeats, results_note="") -> dict`, `select_queries(queries, subset, ids) -> list[AgentQuery]`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_agent_runner.py
"""Runner tests — every model interaction is a canned MockTransport
response (tests/test_harness_session.py fakes), so this suite never
spends money and never touches the office ledger or settings.json.
"""
from __future__ import annotations

import json

import pytest

from eval.agent_schema import AgentQuery
from eval.agent_transcript import read_transcript
from eval.run_agent_eval import build_manifest, run_suite, select_queries
from harness.session import HarnessSession
from tests.test_harness_session import (
    FakeExecutor,
    Provider,
    finish_chunk,
    make_settings,
    sse,
    text_chunk,
    tool_chunk,
    usage_chunk,
)


def q(id="aq-001", **kw):
    defaults = dict(question="ADC FY2025 General Fund?", shape="lookup",
                    subsets=["smoke", "full"])
    defaults.update(kw)
    return AgentQuery(id=id, **defaults)


def fake_factory(provider_builder):
    """session_factory seam: real HarnessSession, fake transport/executor.

    A FRESH Provider per session — an httpx.Response stream is
    single-consumption, so sharing one across queries would break replay.
    """
    def factory(query, conv_id):
        return HarnessSession(
            conv_id, corpus=query.corpus, tier=query.tier, user="eval",
            settings=make_settings(),
            executor=FakeExecutor(),
            transport=provider_builder().transport(),
            tools=[],
            system_prompt="eval test prompt",
        )
    return factory


def simple_provider():
    return Provider(
        lambda: sse(
            tool_chunk(0, call_id="c1", name="retrieve", arguments='{"query": "ADC"}'),
            finish_chunk("tool_calls"),
            usage_chunk(prompt=100, completion=10, cost=0.001, cached=0),
        ),
        lambda: sse(
            text_chunk("ADC got $1.4 B."),
            finish_chunk("stop"),
            usage_chunk(prompt=200, completion=30, cost=0.002, cached=90),
        ),
    )


def test_run_suite_writes_transcript_per_query(tmp_path):
    queries = [q("aq-001"), q("aq-002")]
    run_suite(queries, tmp_path, fake_factory(simple_provider), progress=lambda *_: None)
    for qid in ("aq-001", "aq-002"):
        t = read_transcript(tmp_path / f"{qid}-r1.jsonl")
        assert t.meta["query_id"] == qid
        assert t.terminal["frame"]["type"] == "_done"
        assert t.terminal["wall_ms"] is not None
        assert t.terminal["frame"]["usage"]["cost"] == pytest.approx(0.003)


def test_repeats_write_separate_files(tmp_path):
    run_suite([q()], tmp_path, fake_factory(simple_provider), repeats=2,
              progress=lambda *_: None)
    assert (tmp_path / "aq-001-r1.jsonl").exists()
    assert (tmp_path / "aq-001-r2.jsonl").exists()


def test_one_exploding_session_does_not_abort_the_run(tmp_path):
    calls = {"n": 0}

    def factory(query, conv_id):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("session construction blew up")
        return fake_factory(simple_provider)(query, conv_id)

    run_suite([q("aq-001"), q("aq-002")], tmp_path, factory, progress=lambda *_: None)
    t1 = read_transcript(tmp_path / "aq-001-r1.jsonl")
    assert t1.terminal["frame"]["type"] == "_error"
    assert "RuntimeError" in t1.terminal["frame"]["message"]
    t2 = read_transcript(tmp_path / "aq-002-r1.jsonl")
    assert t2.terminal["frame"]["type"] == "_done"


def test_select_queries_by_subset_and_ids():
    qs = [q("a", subsets=["smoke", "full"]), q("b", subsets=["full"]),
          q("c", subsets=["dr-probe"], tier="deep_research")]
    assert [x.id for x in select_queries(qs, "smoke", None)] == ["a"]
    assert [x.id for x in select_queries(qs, "full", None)] == ["a", "b"]
    assert [x.id for x in select_queries(qs, "dr-probe", None)] == ["c"]
    assert [x.id for x in select_queries(qs, "full", ["b"])] == ["b"]


def test_manifest_redacts_key_and_records_models(tmp_path):
    settings = make_settings()
    manifest = build_manifest(settings, [q()], subset="smoke", repeats=1)
    blob = json.dumps(manifest)
    assert "sk-test" not in blob  # the fake key from make_settings()
    assert manifest["api_key_set"] is True
    assert "standard" in manifest["tier_models"]
    assert manifest["queries"] == ["aq-001"]
    assert "prompt_sha256" in manifest and "corpus_counts" in manifest
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.run_agent_eval'`

- [ ] **Step 3: Implement**

```python
# eval/run_agent_eval.py
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
import dataclasses
import hashlib
import json
import subprocess
import sys
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
    the run directory instead of the office ledger."""
    path = run_dir / "ledger.jsonl"

    def record(user: str, tier: str, model: str, tokens_in: int, tokens_out: int,
               cost_usd: float | None = None, *, cached_tokens: int = 0,
               now: Any = None) -> None:
        row = {"user": user, "tier": tier, "model": model,
               "tokens_in": tokens_in, "tokens_out": tokens_out,
               "cost_usd": cost_usd, "cached_tokens": cached_tokens,
               "timestamp": datetime.now(timezone.utc).isoformat()}
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    return record


def make_session_factory(settings: Settings, run_dir: Path):
    def factory(query: AgentQuery, conv_id: str):
        # Import here so the module stays importable (and testable)
        # without the ONNX/LanceDB stack loaded.
        from harness.session import HarnessSession

        return HarnessSession(
            conv_id, corpus=query.corpus, tier=query.tier, user="eval",
            settings=settings,
            check_limit=_allow_all,
            record_usage=make_usage_recorder(run_dir),
        )
    return factory


def select_queries(queries: list[AgentQuery], subset: str,
                   ids: list[str] | None) -> list[AgentQuery]:
    picked = [q for q in queries if subset in q.subsets]
    if ids:
        wanted = set(ids)
        picked = [q for q in picked if q.id in wanted]
    return picked


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
        "tier_models": {name: cfg.model for name, cfg in settings.tiers.items()},
        "provider": settings.provider.provider,
        "base_url": settings.provider.base_url,
        "api_key_set": bool(settings.provider.api_key),
        "prompt_sha256": prompt_sha,
        "corpus_counts": counts,
        "note": results_note,
    }


def run_suite(queries: list[AgentQuery], run_dir: Path,
              session_factory: Callable[[AgentQuery, str], Any], *,
              repeats: int = 1, progress: Callable[[str], Any] = print) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    for query in queries:
        for rep in range(1, repeats + 1):
            # A transient S13 model fallback during query N must not
            # silently re-model queries N+1..: reset before every query.
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
                    except Exception:
                        pass
            elapsed_ms = int((time.monotonic() - start) * 1000)
            write_transcript(path, meta, events,
                             {"frame": frame, "wall_ms": elapsed_ms})
            status = frame.get("type", "?")
            cost = (frame.get("usage") or {}).get("cost")
            progress(f"{query.id} r{rep}: {status} "
                     f"({elapsed_ms / 1000:.0f}s, cost={cost})")


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

    run_dir = Path(args.results_dir) / f"{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H%MZ')}-{_git_sha()}"
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest = build_manifest(settings, queries, subset=args.subset,
                              repeats=args.repeats, results_note=args.note)
    tmp = (run_dir / "manifest.json").with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(run_dir / "manifest.json")

    print(f"run dir: {run_dir}  ({len(queries)} queries x {args.repeats})")
    run_suite(queries, run_dir, make_session_factory(settings, run_dir),
              repeats=args.repeats)
    print(f"done. next: uv run python -m eval.score_agent_run {run_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_runner.py -v`
Expected: 6 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/run_agent_eval.py tests/test_eval_agent_runner.py
git commit -m "feat(eval): Layer 2 agent-loop runner — transcript-first, ledger-isolated"
```

---

### Task 5: Mechanical scorer

**Files:**
- Modify: `eval/agent_scoring.py` (extend — Task 2 wrote the matchers)
- Create: `eval/score_agent_run.py`
- Test: `tests/test_eval_agent_score_run.py` (new; Task 2's matcher tests stay in `tests/test_eval_agent_scoring.py`)

**Interfaces:**
- Consumes: Task 1 `AgentQuery`/`KeyFact`, Task 2 `fact_matches`, Task 3 `Transcript` + accessors.
- Produces: `score_transcript(query: AgentQuery, t: Transcript) -> dict` (flat metric dict, keys listed in the test); `cite_attempts(t) -> list[dict]` (each `{"input": dict, "result": dict|None}`); `aggregate(rows: list[dict]) -> dict`; CLI `eval/score_agent_run.py <run_dir>` writing `scores.json` + `scores.md` into the run dir.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_agent_score_run.py
"""Mechanical scorer tests over synthetic transcripts.

Each metric gets a transcript engineered to pin it. The golden fixture
(tests/fixtures/agent_transcript_sample.jsonl) pins the happy path.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from eval.agent_schema import AgentQuery, KeyFact
from eval.agent_scoring import aggregate, cite_attempts, score_transcript
from eval.agent_transcript import Transcript, read_transcript

FIXTURE = Path(__file__).parent / "fixtures" / "agent_transcript_sample.jsonl"


def make_query(**kw):
    defaults = dict(id="aq-001", question="ADC FY2025?", shape="lookup",
                    key_facts=[KeyFact(kind="currency", value="$1,391,157,700")])
    defaults.update(kw)
    return AgentQuery(**defaults)


def retrieve_call(chunks, tool_use_id="t-r"):
    return {"toolUseId": tool_use_id, "toolName": "retrieve", "input": {"query": "x"},
            "output": json.dumps({"top_score": 4.0, "retrieval_id": "r",
                                  "bm25_count": 1, "dense_count": 1, "fused_count": 1,
                                  "chunks": chunks}),
            "isError": False}


def chunk(cid, text):
    return {"chunk_id": cid, "doc_id": "d", "doc_title": "T", "publisher": "jlbc",
            "fiscal_year": 2025, "doc_type": "afr", "section_path": "", "page_start": 1,
            "page_end": 1, "bbox": None, "text": text, "text_length": len(text), "score": 4.0}


def cite_call(ok=True, error=None, quote="$1,391,157,700"):
    out = {"ok": ok}
    if error:
        out["error"] = error
    return {"toolUseId": "t-c", "toolName": "cite",
            "input": {"chunk_id": "c-1", "quote": quote, "confidence": "verbatim",
                      "claim_span": "claim"},
            "output": json.dumps(out), "isError": not ok}


def make_transcript(tool_calls, final="ADC received $1,391,157,700.",
                    citations=None, steps=2):
    frame = {"type": "_done", "stopReason": "end_turn", "finalAnswer": final,
             "incompleteNote": None, "citations": citations or [],
             "retrievedChunkIds": [], "toolCalls": tool_calls,
             "usage": {"inputTokens": 1000, "outputTokens": 100,
                       "cacheReadTokens": 400, "cacheCreationTokens": 0, "cost": 0.005}}
    events = [{"type": "assistant_thinking", "uuid": f"u{i}"} for i in range(steps)]
    return Transcript(meta={"query_id": "aq-001", "repeat": 1},
                      events=events, terminal={"frame": frame, "wall_ms": 30000})


def ok_citation(cid="c-1", quote="$1,391,157,700"):
    return {"chunkId": cid, "claimSpan": "claim", "confidence": "verbatim",
            "quote": quote, "spanStart": 0, "spanEnd": 10, "citationId": "x",
            "ok": True, "error": None}


def test_golden_fixture_scores_clean():
    t = read_transcript(FIXTURE)
    row = score_transcript(make_query(), t)
    assert row["ok"] is True
    assert row["key_fact_rate"] == 1.0
    assert row["steps"] == 1
    assert row["retrieve_call_count"] == 1
    assert row["verified_citations"] == 1
    assert row["first_attempt_cite_rate"] == 1.0
    assert row["cost_usd"] == pytest.approx(0.0031)
    assert row["cached_tokens"] == 700


def test_key_fact_miss_detected():
    t = make_transcript([retrieve_call([chunk("c-1", "irrelevant")])],
                        final="ADC received $999.")
    row = score_transcript(make_query(), t)
    assert row["key_fact_rate"] == 0.0


def test_retrieval_efficiency_counts_used_chunks():
    calls = [retrieve_call([chunk("c-1", "ADC $1,391,157,700 appears here"),
                            chunk("c-2", "unrelated text"),
                            chunk("c-3", "also unrelated")])]
    t = make_transcript(calls, citations=[ok_citation("c-1")])
    row = score_transcript(make_query(), t)
    # c-1 cited + fact-bearing; c-2/c-3 never used -> 1/3
    assert row["retrieval_efficiency"] == pytest.approx(1 / 3)


def test_retrieves_after_sufficient():
    fact_chunk = chunk("c-1", "the answer $1,391,157,700 is here")
    calls = [retrieve_call([fact_chunk], "t-1"),
             retrieve_call([chunk("c-2", "noise")], "t-2"),
             retrieve_call([chunk("c-3", "noise")], "t-3")]
    t = make_transcript(calls, citations=[ok_citation("c-1")])
    row = score_transcript(make_query(), t)
    assert row["retrieves_after_sufficient"] == 2


def test_cite_attempt_mechanics_including_batch():
    batch = {"toolUseId": "t-b", "toolName": "cite_batch",
             "input": {"citations": [
                 {"chunk_id": "c-1", "quote": "q1", "confidence": "verbatim", "claim_span": "a"},
                 {"chunk_id": "c-1", "quote": "q2", "confidence": "verbatim", "claim_span": "b"}]},
             "output": json.dumps({"citations": [
                 {"ok": True, "citation_id": "x"},
                 {"ok": False, "error": "quote appears multiple times in chunk.text (positions: 1, 5)"}]}),
             "isError": False}
    t = make_transcript([cite_call(ok=False, error="quote not found in chunk.text — ..."),
                         cite_call(ok=True), batch],
                        citations=[ok_citation()])
    attempts = cite_attempts(t)
    assert len(attempts) == 4
    row = score_transcript(make_query(), t)
    assert row["cite_attempts"] == 4
    assert row["cite_failures"] == 2
    assert row["first_attempt_cite_rate"] == pytest.approx(0.5)
    assert row["ambiguity_rejections"] == 1


def test_quote_narrowness_median():
    cites = [ok_citation(quote="short"), ok_citation(quote="a" * 101)]
    t = make_transcript([], citations=cites)
    row = score_transcript(make_query(), t)
    assert row["median_quote_len"] == pytest.approx((5 + 101) / 2)


def test_refusal_query_scoring():
    rq = make_query(id="aq-r", shape="refusal", should_refuse=True, key_facts=[])
    refused = make_transcript([], final="I can't answer that from this corpus.")
    assert score_transcript(rq, refused)["refusal_correct"] is True
    answered = make_transcript([], citations=[ok_citation()])
    assert score_transcript(rq, answered)["refusal_correct"] is False


def test_hygiene_flags():
    t = make_transcript([], final="Let me search the corpus. The chunk_id shows token: Abc123_defGHI456 leaked.")
    row = score_transcript(make_query(key_facts=[]), t)
    assert row["narration_hits"] >= 1
    assert row["token_leak"] is True
    assert row["internal_vocab_hits"] >= 1


def test_error_terminal_scores_as_failure():
    t = Transcript(meta={"query_id": "aq-001", "repeat": 1}, events=[],
                   terminal={"frame": {"type": "_error", "message": "boom"}, "wall_ms": 5})
    row = score_transcript(make_query(), t)
    assert row["ok"] is False and row["error"] == "boom"


def test_aggregate_summary():
    rows = [score_transcript(make_query(), read_transcript(FIXTURE))]
    summary = aggregate(rows)
    assert summary["n"] == 1
    assert summary["key_fact_rate_mean"] == 1.0
    assert summary["first_attempt_cite_rate"] == 1.0
    assert summary["total_cost_usd"] == pytest.approx(0.0031)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_score_run.py -v`
Expected: FAIL — `ImportError: cannot import name 'score_transcript'`

- [ ] **Step 3: Extend `eval/agent_scoring.py`**

Append to the Task 2 module:

```python
# --- appended below the matchers in eval/agent_scoring.py ---
import statistics
from typing import Any

from eval.agent_schema import AgentQuery
from eval.agent_transcript import (
    Transcript,
    citations,
    final_answer,
    parsed_output,
    retrieve_calls,
    tool_calls,
    usage,
    wall_ms,
)

# Phrases the Plan 4 live run actually saw leak into answer prose.
NARRATION_MARKERS = (
    "let me search", "let me look", "i'll search", "i will search",
    "i have what i need", "searching the corpus", "now i'll",
    "retrying the cite", "let me retrieve", "i'll retrieve",
)
# Corpus mechanics an analyst should never see.
INTERNAL_VOCAB = (
    "top_score", "chunk_id", "cite_batch", "deep_dive",
    "first_call_capped", "rrf", "rerank", "refusal threshold",
)
# The Plan 4 run leaked a raw download token into prose.
_TOKEN_LEAK_RE = re.compile(r"token[=:]\s*[A-Za-z0-9_\-]{12,}")


def cite_attempts(t: Transcript) -> list[dict[str, Any]]:
    """Every citation attempt as {'input', 'result'}, flattening
    cite_batch slots (index-parallel arrays per harness/tools.py:1196)."""
    attempts: list[dict[str, Any]] = []
    for call in tool_calls(t, "cite"):
        attempts.append({"input": call.get("input") or {},
                         "result": parsed_output(call)})
    for call in tool_calls(t, "cite_batch"):
        inputs = (call.get("input") or {}).get("citations") or []
        out = parsed_output(call) or {}
        results = out.get("citations") or []
        for i, item in enumerate(inputs):
            attempts.append({"input": item,
                             "result": results[i] if i < len(results) else None})
    return attempts


def _retrieved_chunks(t: Transcript) -> list[dict[str, Any]]:
    return [c for call in retrieve_calls(t) for c in call["chunks"]]


def _facts_covered(query: AgentQuery, text: str) -> int:
    return sum(1 for f in query.key_facts if fact_matches(f, text))


def score_transcript(query: AgentQuery, t: Transcript) -> dict[str, Any]:
    frame_type = (t.terminal.get("frame") or {}).get("type")
    row: dict[str, Any] = {
        "query_id": query.id, "shape": query.shape, "repeat": t.meta.get("repeat", 1),
        "ok": frame_type == "_done",
        "error": (t.terminal.get("frame") or {}).get("message") if frame_type != "_done" else None,
        "wall_ms": wall_ms(t),
    }
    u = usage(t)
    row["input_tokens"] = u.get("inputTokens", 0)
    row["output_tokens"] = u.get("outputTokens", 0)
    row["cached_tokens"] = u.get("cacheReadTokens", 0)
    row["cost_usd"] = u.get("cost")
    # One step per assistant message uuid — assistant_thinking fires once
    # per step (harness/session.py:632).
    row["steps"] = sum(1 for e in t.events if e.get("type") == "assistant_thinking")

    answer = final_answer(t)
    total_facts = len(query.key_facts)
    matched = _facts_covered(query, answer) if total_facts else 0
    row["key_facts_total"] = total_facts
    row["key_facts_matched"] = matched
    row["key_fact_rate"] = (matched / total_facts) if total_facts else None

    verified = [c for c in citations(t) if c.get("ok")]
    row["verified_citations"] = len(verified)
    row["emitted_citations"] = len(citations(t))

    attempts = cite_attempts(t)
    failures = [a for a in attempts
                if not ((a["result"] or {}).get("ok") is True)]
    row["cite_attempts"] = len(attempts)
    row["cite_failures"] = len(failures)
    row["first_attempt_cite_rate"] = (
        (len(attempts) - len(failures)) / len(attempts) if attempts else None)
    row["ambiguity_rejections"] = sum(
        1 for a in failures
        if "appears multiple times" in ((a["result"] or {}).get("error") or ""))
    quote_lens = [len(c.get("quote") or "") for c in verified if c.get("quote")]
    row["median_quote_len"] = statistics.median(quote_lens) if quote_lens else None

    rcs = retrieve_calls(t)
    row["retrieve_call_count"] = len(rcs)
    all_chunks = _retrieved_chunks(t)
    distinct = {c.get("chunk_id"): c for c in all_chunks}
    row["retrieved_chunks_distinct"] = len(distinct)
    cited_ids = {c.get("chunkId") for c in verified}
    used = 0
    for cid, c in distinct.items():
        text = c.get("text") or ""
        if cid in cited_ids or (query.key_facts and _facts_covered(query, text)):
            used += 1
    row["retrieval_efficiency"] = (used / len(distinct)) if distinct else None

    # Retrieves issued AFTER the facts were already in hand = wasted searches.
    row["retrieves_after_sufficient"] = None
    if query.key_facts and rcs:
        seen: list[str] = []
        for i, call in enumerate(rcs):
            seen.extend((c.get("text") or "") for c in call["chunks"])
            blob = "\n".join(seen)
            if all(fact_matches(f, blob) for f in query.key_facts):
                row["retrieves_after_sufficient"] = len(rcs) - i - 1
                break

    # Refusal scoring: 'refused' means no verified citation was issued.
    # REFUSAL_THRESHOLD is prompt-guidance only (never enforced in code),
    # so the observable refusal signal IS the absence of verified cites.
    refused = len(verified) == 0
    row["refused"] = refused
    row["refusal_correct"] = (refused == query.should_refuse) if query.should_refuse else None
    row["false_refusal"] = (
        refused and total_facts > 0 and matched == 0) if not query.should_refuse else None

    lower = answer.lower()
    row["narration_hits"] = sum(1 for m in NARRATION_MARKERS if m in lower)
    row["internal_vocab_hits"] = sum(1 for v in INTERNAL_VOCAB if v in lower)
    row["token_leak"] = bool(_TOKEN_LEAK_RE.search(answer))
    return row


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [r for r in rows if r["ok"]]
    walls = sorted(r["wall_ms"] for r in ok_rows if r["wall_ms"] is not None)
    attempts = sum(r["cite_attempts"] for r in ok_rows)
    failures = sum(r["cite_failures"] for r in ok_rows)
    refusal_rows = [r for r in rows if r["refusal_correct"] is not None]
    quote_meds = [r["median_quote_len"] for r in ok_rows if r["median_quote_len"] is not None]
    return {
        "n": len(rows),
        "errors": len(rows) - len(ok_rows),
        "steps_mean": _mean([r["steps"] for r in ok_rows]),
        "retrieve_calls_mean": _mean([r["retrieve_call_count"] for r in ok_rows]),
        "input_tokens_mean": _mean([r["input_tokens"] for r in ok_rows]),
        "output_tokens_mean": _mean([r["output_tokens"] for r in ok_rows]),
        "cached_tokens_mean": _mean([r["cached_tokens"] for r in ok_rows]),
        "total_cost_usd": sum(r["cost_usd"] or 0 for r in ok_rows),
        "cost_mean_usd": _mean([r["cost_usd"] for r in ok_rows]),
        "wall_p50_ms": walls[len(walls) // 2] if walls else None,
        "wall_p95_ms": walls[min(len(walls) - 1, int(len(walls) * 0.95))] if walls else None,
        "key_fact_rate_mean": _mean([r["key_fact_rate"] for r in ok_rows]),
        "retrieval_efficiency_mean": _mean([r["retrieval_efficiency"] for r in ok_rows]),
        "retrieves_after_sufficient_mean": _mean(
            [r["retrieves_after_sufficient"] for r in ok_rows]),
        "citations_per_answer_mean": _mean([r["verified_citations"] for r in ok_rows]),
        "first_attempt_cite_rate": ((attempts - failures) / attempts) if attempts else None,
        "median_quote_len_mean": _mean(quote_meds),
        "refusal_correct_rate": _mean(
            [1.0 if r["refusal_correct"] else 0.0 for r in refusal_rows]),
        "false_refusals": sum(1 for r in rows if r.get("false_refusal")),
        "narration_hit_queries": sum(1 for r in ok_rows if r["narration_hits"]),
        "token_leaks": sum(1 for r in ok_rows if r["token_leak"]),
        "internal_vocab_queries": sum(1 for r in ok_rows if r["internal_vocab_hits"]),
    }
```

- [ ] **Step 4: Write the CLI**

```python
# eval/score_agent_run.py
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
    for path in sorted(run_dir.glob("*-r*.jsonl")):
        if path.name == "ledger.jsonl":
            continue
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
    lines += ["", "## Per query", "",
              "| id | shape | ok | facts | cites ok | 1st-try | retr eff | steps | cost |",
              "|---|---|---|---|---|---|---|---|---|"]
    for r in scores["per_query"]:
        def fmt(v):
            return "—" if v is None else (f"{v:.2f}" if isinstance(v, float) else v)
        lines.append(
            f"| {r['query_id']} | {r['shape']} | {'✓' if r['ok'] else '✗'} "
            f"| {fmt(r['key_fact_rate'])} | {r['verified_citations']} "
            f"| {fmt(r['first_attempt_cite_rate'])} | {fmt(r['retrieval_efficiency'])} "
            f"| {r['steps']} | {fmt(r['cost_usd'])} |")
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
```

Add an end-to-end CLI test to `tests/test_eval_agent_score_run.py`:

```python
def test_score_run_cli_writes_outputs(tmp_path):
    import shutil
    from eval.score_agent_run import score_run
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    shutil.copy(FIXTURE, run_dir / "aq-001-r1.jsonl")
    qfile = tmp_path / "queries.yaml"
    qfile.write_text(
        "- id: aq-001\n  question: ADC?\n  shape: lookup\n"
        "  key_facts:\n    - kind: currency\n      value: \"$1,391,157,700\"\n",
        encoding="utf-8")
    scores = score_run(run_dir, str(qfile))
    assert scores["summary"]["n"] == 1
    assert scores["per_query"][0]["ok"] is True
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_score_run.py tests/test_eval_agent_scoring.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add eval/agent_scoring.py eval/score_agent_run.py tests/test_eval_agent_score_run.py
git commit -m "feat(eval): mechanical scorer — efficiency, accuracy, citation, hygiene metrics"
```

---

### Task 6: LLM judge

**Files:**
- Create: `eval/agent_judge_prompt.md`
- Create: `eval/judge_agent_run.py`
- Test: `tests/test_eval_agent_judge.py`

**Interfaces:**
- Consumes: Task 1 `load_agent_queries`, Task 3 accessors, `harness.settings.load_settings`.
- Produces: `judge.json` in the run dir; library functions `build_judge_payload(query, t) -> dict`, `parse_judge_json(content: str) -> dict`, `judge_one(client, base_url, api_key, model, system_prompt, payload) -> dict`, `compute_citation_scores(judge_result, t) -> dict` (`claim_coverage_precision`, `claim_coverage_recall`).

- [ ] **Step 1: Write the judge prompt**

```markdown
<!-- eval/agent_judge_prompt.md -->
# Agent-eval judge

You are grading one answer from a budget-research assistant that answers
questions about Arizona state budget documents with verified citations.
You receive a JSON payload: the analyst's question, authoring notes,
the assistant's final answer, the citations it issued (with whether each
passed verification), and the text of the cited chunks.

Return ONLY a JSON object, no prose, no code fences:

{
  "load_bearing_claims": [
    {"claim": "<short restatement of one claim the analyst would act on
               — a dollar figure, a change, a finding>",
     "cited_verified": true|false}
  ],
  "holistic": 1-5,
  "flags": {
    "hedging": true|false,
    "meta_narration": true|false,
    "answered_wrong_question": true|false
  },
  "rationale": "<= 2 sentences"
}

Rules:
- load_bearing_claims: the claims that carry the answer. A 3-figure
  comparison has ~3; a refusal has 0. Do NOT list trivia or hedges.
- cited_verified: true only if a citation whose "ok" is true covers that
  claim AND its quote actually supports it per the cited chunk text.
- holistic: 5 = correct, complete, direct; 3 = usable with friction;
  1 = wrong, unusable, or confidently uncited.
- meta_narration: true if the answer narrates its own process
  ("let me search...", "I have what I need").
- If the payload's answer is empty, return holistic 1 and no claims.
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_eval_agent_judge.py
"""Judge tests — model traffic mocked with httpx.MockTransport; the
judge's arithmetic (claim-coverage precision) is computed in OUR code
from the judge's claim list, never trusted from the model."""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from eval.agent_transcript import read_transcript
from eval.judge_agent_run import (
    build_judge_payload,
    compute_citation_scores,
    judge_one,
    parse_judge_json,
)
from tests.test_eval_agent_score_run import make_query

FIXTURE = Path(__file__).parent / "fixtures" / "agent_transcript_sample.jsonl"

JUDGE_REPLY = {
    "load_bearing_claims": [
        {"claim": "ADC FY2025 GF appropriation was $1,391,157,700", "cited_verified": True},
        {"claim": "the appropriation grew year over year", "cited_verified": False},
    ],
    "holistic": 4,
    "flags": {"hedging": False, "meta_narration": False, "answered_wrong_question": False},
    "rationale": "Correct figure, one uncited trend claim.",
}


def test_build_judge_payload_carries_cited_chunk_texts():
    t = read_transcript(FIXTURE)
    payload = build_judge_payload(make_query(), t)
    assert payload["question"]
    assert payload["final_answer"] == "ADC received $1,391,157,700."
    assert payload["citations"][0]["ok"] is True
    # the cited chunk's text rides along so the judge can check support
    assert "c-1" in payload["cited_chunks"]
    assert "$1,391,157,700" in payload["cited_chunks"]["c-1"]


def test_parse_judge_json_strips_code_fences():
    fenced = "```json\n" + json.dumps(JUDGE_REPLY) + "\n```"
    assert parse_judge_json(fenced)["holistic"] == 4
    assert parse_judge_json(json.dumps(JUDGE_REPLY))["holistic"] == 4
    with pytest.raises(ValueError):
        parse_judge_json("I think the answer is fine.")


def test_compute_citation_scores():
    t = read_transcript(FIXTURE)  # 1 verified citation emitted
    scores = compute_citation_scores(JUDGE_REPLY, t)
    # precision: claims cited+verified (1) / citations issued (1)
    assert scores["claim_coverage_precision"] == 1.0
    # recall: claims cited+verified (1) / load-bearing claims (2)
    assert scores["claim_coverage_recall"] == 0.5


def test_judge_one_round_trip():
    def handler(request):
        body = json.loads(request.content)
        assert body["temperature"] == 0
        assert body["model"] == "judge/model"
        return httpx.Response(200, json={
            "choices": [{"message": {"content": json.dumps(JUDGE_REPLY)}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = judge_one(client, "https://openrouter.test/api/v1", "sk-x",
                       "judge/model", "system", {"question": "q"})
    assert result["holistic"] == 4


def test_judge_one_malformed_reply_becomes_error_not_crash():
    def handler(request):
        return httpx.Response(200, json={
            "choices": [{"message": {"content": "not json at all"}}]})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = judge_one(client, "https://openrouter.test/api/v1", "sk-x",
                       "judge/model", "system", {"question": "q"})
    assert "judge_error" in result
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_judge.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'eval.judge_agent_run'`

- [ ] **Step 4: Implement**

```python
# eval/judge_agent_run.py
"""LLM judge for Layer 2 agent-eval runs (full runs only — costs money).

The judge identifies load-bearing claims and whether each is covered by
a verified citation. The headline number, claim-coverage precision, is
computed HERE from the judge's claim list and the transcript's citation
count — judge arithmetic is never trusted (spec Decision #3).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from eval.agent_schema import AgentQuery, load_agent_queries
from eval.agent_transcript import (
    Transcript, citations, final_answer, read_transcript, retrieve_calls,
)
from harness.settings import load_settings

DEFAULT_QUERIES = "eval/agent_queries.yaml"
# Not the model under test (spec): a capable, cheap-enough judge.
DEFAULT_JUDGE_MODEL = "anthropic/claude-sonnet-5"
PROMPT_PATH = Path(__file__).resolve().parent / "agent_judge_prompt.md"

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def build_judge_payload(query: AgentQuery, t: Transcript) -> dict[str, Any]:
    chunk_texts: dict[str, str] = {}
    for call in retrieve_calls(t):
        for c in call["chunks"]:
            cid = c.get("chunk_id")
            if cid:
                chunk_texts[cid] = c.get("text") or ""
    cited = {}
    cite_rows = []
    for c in citations(t):
        cite_rows.append({"chunk_id": c.get("chunkId"), "quote": c.get("quote"),
                          "claim_span": c.get("claimSpan"), "ok": bool(c.get("ok"))})
        cid = c.get("chunkId")
        if cid in chunk_texts:
            cited[cid] = chunk_texts[cid]
    return {"question": query.question, "judge_notes": query.judge_notes,
            "should_refuse": query.should_refuse,
            "final_answer": final_answer(t), "citations": cite_rows,
            "cited_chunks": cited}


def parse_judge_json(content: str) -> dict[str, Any]:
    stripped = _FENCE_RE.sub("", content.strip())
    try:
        parsed = json.loads(stripped)
    except ValueError as exc:
        raise ValueError(f"judge returned non-JSON: {content[:200]!r}") from exc
    if not isinstance(parsed, dict) or "load_bearing_claims" not in parsed:
        raise ValueError(f"judge JSON missing load_bearing_claims: {stripped[:200]!r}")
    return parsed


def judge_one(client: httpx.Client, base_url: str, api_key: str, model: str,
              system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "temperature": 0,
                  "messages": [{"role": "system", "content": system_prompt},
                               {"role": "user",
                                "content": json.dumps(payload, ensure_ascii=False)}]},
            timeout=120.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return parse_judge_json(content)
    except Exception as exc:
        # One flaky judge call must not lose the whole run's judging.
        return {"judge_error": f"{type(exc).__name__}: {exc}"}


def compute_citation_scores(judge_result: dict[str, Any], t: Transcript) -> dict[str, Any]:
    claims = judge_result.get("load_bearing_claims") or []
    covered = sum(1 for c in claims if c.get("cited_verified"))
    emitted = len(citations(t))
    return {
        # covered claims / citations ISSUED: padding citations dilute it.
        "claim_coverage_precision": (covered / emitted) if emitted else None,
        # covered claims / claims that NEEDED citing: uncited key claims hurt.
        "claim_coverage_recall": (covered / len(claims)) if claims else None,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser(description="LLM judge over an agent-eval run (spends money)")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--queries-file", default=DEFAULT_QUERIES)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="judge only the first N transcripts")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.provider.api_key:
        print("no API key configured — the judge needs one", file=sys.stderr)
        return 2
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    queries = {q.id: q for q in load_agent_queries(args.queries_file)}

    per_query: list[dict[str, Any]] = []
    with httpx.Client() as client:
        paths = sorted(p for p in args.run_dir.glob("*-r*.jsonl")
                       if p.name != "ledger.jsonl")
        if args.limit:
            paths = paths[: args.limit]
        for path in paths:
            t = read_transcript(path)
            qid = t.meta.get("query_id")
            if qid not in queries:
                continue
            payload = build_judge_payload(queries[qid], t)
            result = judge_one(client, settings.provider.base_url,
                               settings.provider.api_key, args.judge_model,
                               system_prompt, payload)
            row = {"query_id": qid, "repeat": t.meta.get("repeat", 1), **result}
            if "judge_error" not in result:
                row.update(compute_citation_scores(result, t))
            per_query.append(row)
            print(f"{qid}: {'ERROR' if 'judge_error' in result else row.get('holistic')}")

    graded = [r for r in per_query if "judge_error" not in r]
    def mean(key):
        vals = [r[key] for r in graded if r.get(key) is not None]
        return (sum(vals) / len(vals)) if vals else None
    out = {"judge_model": args.judge_model,
           "judge_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
           "summary": {"n": len(per_query), "errors": len(per_query) - len(graded),
                       "claim_coverage_precision_mean": mean("claim_coverage_precision"),
                       "claim_coverage_recall_mean": mean("claim_coverage_recall"),
                       "holistic_mean": mean("holistic")},
           "per_query": per_query}
    tmp = (args.run_dir / "judge.json").with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(args.run_dir / "judge.json")
    print(json.dumps(out["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 5: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_judge.py -v`
Expected: 5 PASS

- [ ] **Step 6: Commit**

```bash
git add eval/agent_judge_prompt.md eval/judge_agent_run.py tests/test_eval_agent_judge.py
git commit -m "feat(eval): LLM judge — claim-coverage precision/recall, holistic grade"
```

---

### Task 7: Compare tool

**Files:**
- Create: `eval/compare_agent_runs.py`
- Test: `tests/test_eval_agent_compare.py`

**Interfaces:**
- Consumes: run-dir layout from Tasks 4–6 (`manifest.json`, `scores.json`, optional `judge.json`).
- Produces: `load_run(run_dir) -> dict` (`{"manifest", "scores", "judge"|None, "name"}`); `compare(baseline: dict, candidate: dict) -> str` (markdown); `corpus_counts_differ(a, b) -> bool`; CLI writing `compare-<baseline>-vs-<candidate>.md` next to the run dirs.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_eval_agent_compare.py
"""Compare-tool tests. The guardrails ARE the feature: refusing
cross-corpus comparisons and labeling single-run noise (spec §5)."""
from __future__ import annotations

import json

import pytest

from eval.compare_agent_runs import compare, corpus_counts_differ, load_run


def write_run(tmp_path, name, *, counts=None, repeats=1, kf=0.8, cites=1.0,
              judge_precision=None):
    d = tmp_path / name
    d.mkdir()
    (d / "manifest.json").write_text(json.dumps({
        "timestamp": name, "git_sha": name[:7], "subset": "smoke",
        "repeats": repeats, "queries": ["aq-001"],
        "tier_models": {"standard": "test/model"},
        "provider": "openrouter", "base_url": "x", "api_key_set": True,
        "prompt_sha256": "abc", "corpus_counts": counts or {"budget_chunks": 100},
        "note": ""}), encoding="utf-8")
    (d / "scores.json").write_text(json.dumps({
        "summary": {"n": 1, "errors": 0, "key_fact_rate_mean": kf,
                    "first_attempt_cite_rate": cites, "steps_mean": 4.0,
                    "total_cost_usd": 0.01},
        "per_query": [{"query_id": "aq-001", "ok": True, "key_fact_rate": kf}],
        "skipped": []}), encoding="utf-8")
    if judge_precision is not None:
        (d / "judge.json").write_text(json.dumps({
            "judge_model": "j", "judge_prompt_sha256": "s",
            "summary": {"claim_coverage_precision_mean": judge_precision},
            "per_query": []}), encoding="utf-8")
    return d


def test_load_run(tmp_path):
    run = load_run(write_run(tmp_path, "runA", judge_precision=0.9))
    assert run["manifest"]["subset"] == "smoke"
    assert run["scores"]["summary"]["n"] == 1
    assert run["judge"]["summary"]["claim_coverage_precision_mean"] == 0.9


def test_corpus_guard(tmp_path):
    a = load_run(write_run(tmp_path, "runA", counts={"budget_chunks": 100}))
    b = load_run(write_run(tmp_path, "runB", counts={"budget_chunks": 999}))
    assert corpus_counts_differ(a, b) is True
    c = load_run(write_run(tmp_path, "runC", counts={"budget_chunks": 100}))
    assert corpus_counts_differ(a, c) is False


def test_compare_markdown_contains_deltas_and_noise_warning(tmp_path):
    a = load_run(write_run(tmp_path, "runA", kf=0.8, cites=0.5))
    b = load_run(write_run(tmp_path, "runB", kf=0.9, cites=0.75))
    md = compare(a, b)
    assert "key_fact_rate_mean" in md
    assert "+0.1" in md or "0.10" in md  # the delta is shown
    assert "single run" in md.lower()    # repeats==1 noise warning


def test_compare_includes_judge_when_both_have_it(tmp_path):
    a = load_run(write_run(tmp_path, "runA", judge_precision=0.6))
    b = load_run(write_run(tmp_path, "runB", judge_precision=0.8))
    md = compare(a, b)
    assert "claim_coverage_precision_mean" in md


def test_compare_skips_judge_when_one_side_missing(tmp_path):
    a = load_run(write_run(tmp_path, "runA"))
    b = load_run(write_run(tmp_path, "runB", judge_precision=0.8))
    md = compare(a, b)
    assert "judge" in md.lower() and "only one run" in md.lower()
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_eval_agent_compare.py -v`
Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# eval/compare_agent_runs.py
"""Diff two agent-eval run directories into a markdown report.

Guardrails (spec §5): refuse to compare runs against different corpus
counts (the numbers would measure the corpus, not the change), and label
single-run comparisons as stochastic noise rather than celebrating them.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# Metrics where UP is better; everything else in the table is
# informational. Direction matters for the ▲/▼ glyphs only.
_HIGHER_IS_BETTER = {
    "key_fact_rate_mean", "first_attempt_cite_rate", "retrieval_efficiency_mean",
    "refusal_correct_rate", "cached_tokens_mean",
}
_LOWER_IS_BETTER = {
    "steps_mean", "retrieve_calls_mean", "input_tokens_mean", "output_tokens_mean",
    "total_cost_usd", "cost_mean_usd", "wall_p50_ms", "wall_p95_ms",
    "retrieves_after_sufficient_mean", "errors", "false_refusals",
    "narration_hit_queries", "token_leaks", "internal_vocab_queries",
}
_JUDGE_METRICS = ("claim_coverage_precision_mean", "claim_coverage_recall_mean",
                  "holistic_mean")


def load_run(run_dir: str | Path) -> dict[str, Any]:
    run_dir = Path(run_dir)
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    scores = json.loads((run_dir / "scores.json").read_text(encoding="utf-8"))
    judge = None
    judge_path = run_dir / "judge.json"
    if judge_path.exists():
        judge = json.loads(judge_path.read_text(encoding="utf-8"))
    return {"name": run_dir.name, "manifest": manifest, "scores": scores, "judge": judge}


def corpus_counts_differ(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return a["manifest"].get("corpus_counts") != b["manifest"].get("corpus_counts")


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.4g}"
    return str(v)


def _delta_row(key: str, av: Any, bv: Any) -> str:
    arrow = ""
    if isinstance(av, (int, float)) and isinstance(bv, (int, float)):
        diff = bv - av
        if diff:
            better = ((diff > 0 and key in _HIGHER_IS_BETTER)
                      or (diff < 0 and key in _LOWER_IS_BETTER))
            arrow = f" {'▲' if better else '▼'}" if (key in _HIGHER_IS_BETTER or key in _LOWER_IS_BETTER) else ""
        delta = f"{diff:+.4g}"
    else:
        delta = "—"
    return f"| {key} | {_fmt(av)} | {_fmt(bv)} | {delta}{arrow} |"


def compare(baseline: dict[str, Any], candidate: dict[str, Any]) -> str:
    am, bm = baseline["manifest"], candidate["manifest"]
    asum, bsum = baseline["scores"]["summary"], candidate["scores"]["summary"]
    lines = [f"# Agent-eval compare — {baseline['name']} → {candidate['name']}", ""]
    lines += ["## What differed", "",
              "| | baseline | candidate |", "|---|---|---|"]
    for key in ("git_sha", "subset", "repeats", "prompt_sha256", "tier_models", "note"):
        lines.append(f"| {key} | {_fmt(am.get(key))} | {_fmt(bm.get(key))} |")
    if am.get("repeats", 1) == 1 or bm.get("repeats", 1) == 1:
        lines += ["", "> ⚠ At least one side is a **single run**: model outputs are "
                  "stochastic, so small deltas here are noise, not signal. "
                  "Re-run with --repeats 3 before acting on a borderline delta."]
    lines += ["", "## Mechanical metrics", "",
              "| metric | baseline | candidate | Δ |", "|---|---|---|---|"]
    for key in sorted(set(asum) | set(bsum)):
        lines.append(_delta_row(key, asum.get(key), bsum.get(key)))
    aj, bj = baseline.get("judge"), candidate.get("judge")
    if aj and bj:
        lines += ["", "## Judge metrics", "",
                  "| metric | baseline | candidate | Δ |", "|---|---|---|---|"]
        for key in _JUDGE_METRICS:
            lines.append(_delta_row(key, aj["summary"].get(key), bj["summary"].get(key)))
    elif aj or bj:
        lines += ["", "> Judge metrics omitted: only one run was judged."]
    # Per-query transitions — regressions by name, not just moved means.
    a_by_id = {r["query_id"]: r for r in baseline["scores"]["per_query"]}
    b_by_id = {r["query_id"]: r for r in candidate["scores"]["per_query"]}
    regressed = [qid for qid in a_by_id.keys() & b_by_id.keys()
                 if (a_by_id[qid].get("key_fact_rate") or 0) > (b_by_id[qid].get("key_fact_rate") or 0)]
    if regressed:
        lines += ["", "## Per-query regressions (key-fact rate fell)", ""]
        lines += [f"- {qid}: {_fmt(a_by_id[qid].get('key_fact_rate'))} → "
                  f"{_fmt(b_by_id[qid].get('key_fact_rate'))}" for qid in sorted(regressed)]
    return "\n".join(lines) + "\n"


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    parser = argparse.ArgumentParser()
    parser.add_argument("baseline", type=Path)
    parser.add_argument("candidate", type=Path)
    parser.add_argument("--out", type=Path, default=None)
    parser.add_argument("--force", action="store_true",
                        help="compare despite differing corpus counts")
    args = parser.parse_args()

    a, b = load_run(args.baseline), load_run(args.candidate)
    if corpus_counts_differ(a, b) and not args.force:
        print("REFUSING: corpus counts differ between runs — the delta would "
              "measure the corpus, not your change. Use --force to override.",
              file=sys.stderr)
        print(f"  baseline:  {a['manifest'].get('corpus_counts')}", file=sys.stderr)
        print(f"  candidate: {b['manifest'].get('corpus_counts')}", file=sys.stderr)
        return 2
    md = compare(a, b)
    out = args.out or (args.candidate.parent / f"compare-{a['name']}-vs-{b['name']}.md")
    out.write_text(md, encoding="utf-8")
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run to verify pass**

Run: `uv run pytest tests/test_eval_agent_compare.py -v`
Expected: 5 PASS

- [ ] **Step 5: Commit**

```bash
git add eval/compare_agent_runs.py tests/test_eval_agent_compare.py
git commit -m "feat(eval): run-vs-run compare with corpus guard + noise labeling"
```

---

### Task 8: Author the query set

**Files:**
- Create: `eval/agent_queries.yaml`
- Test: `tests/test_eval_agent_queries.py`

**Interfaces:**
- Consumes: Task 1 schema.
- Produces: the committed ~30-query set all live runs use.

This task is research + authoring, not plumbing. The queries must be grounded in the REAL corpus — a key fact that doesn't appear verbatim in any chunk can never be matched, and a question whose answer isn't in the corpus is accidentally a refusal query.

- [ ] **Step 1: Write the structural test first** (it pins the quotas the authoring must hit)

```python
# tests/test_eval_agent_queries.py
"""Structural invariants for the committed query set.

Why: the query set is the eval's measuring stick. These tests make the
authoring contract (shape quotas, subset sizes, refusal hygiene)
machine-checked so a future edit can't quietly unbalance it.
"""
from __future__ import annotations

from collections import Counter

from eval.agent_schema import load_agent_queries

QUERIES = load_agent_queries("eval/agent_queries.yaml")


def test_size_and_unique_ids():
    assert len(QUERIES) >= 28
    assert len({q.id for q in QUERIES}) == len(QUERIES)


def test_shape_quotas():
    shapes = Counter(q.shape for q in QUERIES)
    assert shapes["lookup"] >= 8
    assert shapes["comparison"] >= 5
    assert shapes["analyze"] >= 4
    assert shapes["memo"] >= 1
    assert shapes["refusal"] >= 4
    assert shapes["historical"] >= 3


def test_corpus_coverage():
    # BUDGET ONLY — Destin, 2026-08-01: "this eval set should NOT utilize the
    # fiscal note path, we are solely evaluating budget queries." A metric
    # averaged across two corpora answers no question about either.
    assert all(q.corpus == "budget" for q in QUERIES)


def test_smoke_subset_is_small_and_diverse():
    smoke = [q for q in QUERIES if "smoke" in q.subsets]
    assert 8 <= len(smoke) <= 12
    assert len({q.shape for q in smoke}) >= 4
    assert all(q.tier == "standard" for q in smoke)


def test_dr_probe_subset():
    probe = [q for q in QUERIES if "dr-probe" in q.subsets]
    assert len(probe) == 4
    assert all(q.tier == "deep_research" for q in probe)


def test_refusal_queries_have_no_key_facts():
    for q in QUERIES:
        if q.shape == "refusal":
            assert q.should_refuse and not q.key_facts
        else:
            assert not q.should_refuse


def test_answer_queries_have_key_facts_and_notes():
    for q in QUERIES:
        if q.shape not in ("refusal", "memo"):
            assert q.key_facts, f"{q.id} has no key facts"
        assert q.judge_notes, f"{q.id} has no judge notes"
```

- [ ] **Step 2: Author the queries** (subagent-friendly procedure)

Dispatch research subagents (or do it inline) to sample real chunks and draft entries. Procedure per query:

1. Sample candidate chunks from the live corpus:
   ```python
   # uv run python - <<'EOF'  (adjust filters per shape)
   from retrieval.pipeline import RetrievalRequest, retrieve
   r = retrieve(RetrievalRequest(query="<topic>", top_k=10, corpus="budget_chunks"))
   for c in r.chunks:
       print(c.chunk_id, c.fiscal_year, c.doc_type, "|", c.text[:200])
   # EOF
   ```
2. Write a natural analyst question answerable from those chunks (do NOT quote chunk phrasing verbatim in the question — that inflates retrieval scores).
3. Extract 1–3 key facts that appear IN the chunk text (dollar amounts as printed; agency names as `string` facts; rates as `regex`).
4. Write `judge_notes` naming the expected source and any known trap (e.g. "Baseline figure differs from AFR; either acceptable, AFR preferred").
5. **Verify each currency fact parses**: `uv run python -c "from eval.agent_scoring import currency_values; print(currency_values('<value>'))"` must print a non-empty set.

Coverage targets (mirroring the structural test):

| shape | count | notes |
|---|---|---|
| lookup | 8+ | single figure/agency/FY; ≥2 from FY2025–2027 |
| comparison | 5+ | multi-year (the 3-year-table pattern) |
| analyze | 4+ | multi-retrieve synthesis ("what drove the change...") |
| memo | 1+ | a `create_document` ask — the observed zero-citation failure shape; key facts on the ANSWER text still apply |
| refusal | 4+ | out-of-corpus (federal budget, city budgets, current news) |
| historical | 3+ | the OLDEST budget-book years present. Measured 2026-08-01, `budget_chunks` spans FY2021–FY2027 (FY2021 is a 169-chunk fragment), so this means FY2022–FY2023. Pre-FY2022 editions are STATUS.md's deferred backfill; re-author this shape against them when it lands |
| dr-probe | exactly 4 | `tier: deep_research`, `subsets: [dr-probe]` — 2 comparison + 2 analyze |
| smoke | 8–12 | tag existing standard-tier queries across ≥4 shapes |

File header comment (adapt Layer 1's `queries.yaml` framing): state that this measures END-TO-END agent behavior, not retrieval recall; that this set is **budget-corpus only** and why; that key facts must exist verbatim-or-equivalent in corpus chunks; and the date + corpus counts it was authored against (28,530 budget chunks spanning FY2021–FY2027, 2026-08-01).

- [ ] **Step 3: Run the structural test**

Run: `uv run pytest tests/test_eval_agent_queries.py -v`
Expected: all PASS

- [ ] **Step 4: Spot-check retrievability** (cheap layer, no model)

For every non-refusal budget query, verify the corpus can actually surface a fact-bearing chunk:

```python
# scratch — uv run python - <<'EOF'
from eval.agent_schema import load_agent_queries
from eval.agent_scoring import fact_matches
from retrieval.pipeline import RetrievalRequest, retrieve

TABLES = {"budget": "budget_chunks", "fiscal_notes": "fiscal_note_chunks"}
for q in load_agent_queries("eval/agent_queries.yaml"):
    if q.should_refuse or not q.key_facts:
        continue
    r = retrieve(RetrievalRequest(query=q.question, top_k=20, corpus=TABLES[q.corpus]))
    blob = "\n".join(c.text for c in r.chunks)
    missing = [f.value for f in q.key_facts if not fact_matches(f, blob)]
    print(("OK  " if not missing else "MISS"), q.id, missing or "")
# EOF
```

Every `MISS` is either a bad fact (fix the fact) or a genuinely-hard retrieval case (keep it, note it in `judge_notes` — hard cases are informative; but the set must not be MOSTLY misses). Record the miss list in the commit message.

- [ ] **Step 5: Commit**

```bash
git add eval/agent_queries.yaml tests/test_eval_agent_queries.py
git commit -m "feat(eval): Layer 2 agent query set — 30 queries across 6 shapes, smoke + dr-probe subsets"
```

---

### Task 9: Docs, baseline instructions, STATUS entry

**Files:**
- Modify: `eval/README.md` (add a Layer 2 section)
- Modify: `STATUS.md` (ship entry)

- [ ] **Step 1: Add the Layer 2 section to `eval/README.md`**

Append a section covering, in this order (follow the file's existing voice):

```markdown
## Layer 2 — agent-loop eval (`run_agent_eval.py`)

What it measures vs Layer 1 (retrieval recall): the full harness loop —
turns, tokens, cost, answer key-facts, citation discipline, hygiene.

**Costs real money.** Rough guide: smoke ~10 queries ≈ $0.15–0.30,
full ~30 ≈ $0.50–1.50 on Standard, dr-probe 4 queries ≈ $2–3.

Workflow:
    uv run python -m eval.run_agent_eval --subset smoke      # live run
    uv run python -m eval.score_agent_run eval/results/agent/<run>   # free
    uv run python -m eval.judge_agent_run eval/results/agent/<run>   # money, full runs
    uv run python -m eval.compare_agent_runs <baseline> <candidate>  # free

Experiment loop (per candidate change, in a worktree):
1. cheap layer: Layer 1 eval + re-score old transcripts if scorer changed
2. live smoke run vs baseline smoke; compare
3. full run + judge before merge; commit the compare report

Caveats: single runs are stochastic (use --repeats 3 for borderline
deltas); never compare across differing corpus counts (the tool refuses);
the runner writes its own ledger.jsonl — office spend limits are neither
consumed nor enforced; transcripts contain full chunk text — they stay
in eval/results/agent/ (gitignore raw transcripts if size becomes an
issue; scores/judge/compare reports are committed).
```

Decide committing policy: commit `manifest.json`, `scores.*`, `judge.json`, `compare-*.md`; add `eval/results/agent/**/**-r*.jsonl` and `**/ledger.jsonl` to `.gitignore` (transcripts embed full chunk text — large and corpus-derived).

- [ ] **Step 2: Update `.gitignore`**

```gitignore
# Layer 2 agent-eval raw transcripts (full chunk text; scores/judge/compare ARE committed)
eval/results/agent/*/*-r*.jsonl
eval/results/agent/*/ledger.jsonl
```

- [ ] **Step 3: STATUS.md entry**

Add to the "What's next" list and a short shipped section following the existing pattern (date, spec link, what shipped, how to run, the baseline-run instruction below). Do not duplicate into CLAUDE.md.

- [ ] **Step 4: Full suite + commit**

```bash
uv run pytest tests/test_eval_agent_*.py -v
git add eval/README.md STATUS.md .gitignore
git commit -m "docs(eval): Layer 2 agent-eval usage, cost guide, results policy"
```

---

### Task 10: First live baseline (manual, needs the human's go-ahead)

Not code — the acceptance run. Requires the OpenRouter key on this machine (verified present 2026-08-01) and explicit user sign-off since it spends money (~$1–2 total).

- [ ] **Step 1:** `uv run python -m eval.run_agent_eval --subset smoke --note "first smoke baseline"` — sanity-check transcripts by eye (real tool calls, real citations, costs recorded).
- [ ] **Step 2:** `uv run python -m eval.score_agent_run <run_dir>` — check no metric is degenerate (e.g. retrieval_efficiency all None would mean chunk parsing broke against real output).
- [ ] **Step 3:** `uv run python -m eval.run_agent_eval --subset full --repeats 1 --note "Layer 2 baseline"` then score + judge.
- [ ] **Step 4:** Commit `manifest.json`, `scores.*`, `judge.json` as the baseline; record headline numbers in STATUS.md. This baseline is what every experiment compares against.
- [ ] **Step 5:** While a run is live, ALSO verify S22's outstanding acceptance criterion (STATUS.md): ledger.jsonl rows after step 1 of a multi-step turn should show `cached_tokens > 0`. Note the result in STATUS.md — it closes an open item for free.

---

## Self-review notes (completed)

- **Spec coverage:** query set → T8; runner/manifest/repeats → T4; mechanical scorer incl. retrieval-efficiency + retrieves-after-sufficient + hygiene → T5; judge + claim-coverage precision → T6; compare + guardrails → T7; layered workflow + cost docs → T9; baseline → T10; citation replay capability → transcripts carry chunk text (T3) + `validate_cite_against_text` exists upstream; replay tooling itself is exercised the first time an experiment needs it (YAGNI — no speculative CLI).
- **Type consistency:** `AgentQuery.shape` used by scorer rows and query tests; `cite_attempts` shape `{"input","result"}` consistent between T5 tests and impl; run-dir file names (`<id>-r<N>.jsonl`, `manifest.json`, `scores.json`, `judge.json`) consistent across T4–T7.
- **Known simplification:** `steps` counts `assistant_thinking` events (one per step, `harness/session.py:632`) — verified emission point, not a guess.
