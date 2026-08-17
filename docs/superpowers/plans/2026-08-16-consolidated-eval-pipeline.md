# Consolidated Eval Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Layer 2 agent-loop eval into one consolidated, profile-driven quality pipeline — three query sets (`quick`/`multi`/`deep` + a `refusal` tag), a cost-to-accurate headline (`tokens_to_accurate`/`turns_to_accurate`), a `document_correctness` axis, a tool-error ledger, and an append-only over-time archive.

**Architecture:** Extend what exists, never rewrite. The orchestrator `eval/run_full_layer2.py` gains `--sets` and 1-or-2-model profiles; `eval/agent_scoring.py` gains additive headline/doc-correctness axes and loses wall-clock summary metrics; two new sibling modules (`eval/agent_errors.py`, `eval/over_time.py`) own the error ledger and the archive; `eval/agent_queries.yaml` is re-tagged in one atomic commit (`subsets:` → `set:`) and then extended. Spec: `docs/superpowers/specs/2026-08-16-consolidated-eval-pipeline-design.md`.

**Tech Stack:** Python 3.12, pydantic + ruamel.yaml (query schema), pytest (mechanism tests), OpenRouter via the existing harness (live runs only — no test ever spends money or opens a real LanceDB directory / ONNX weights).

## Global Constraints

- **A plan is a hypothesis.** When a step's expectation conflicts with a measurement or the code's actual shape, the measurement wins — implement what is right and record the deviation with numbers in the commit message and STATUS.md.
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX weights.** Transcripts are faked in-process (see `tests/test_eval_agent_scoring.py` for the established pattern).
- **Money-spending runs are manual, never CI.** Any task that ends with a live run requires Destin's explicit go-ahead first.
- **Annotate non-trivial edits with a WHY comment** recording the evidence that drove the choice.
- **Never touch a running production deployment.** All verification runs against the local dev corpus (`data/insight-data/`).
- Wall-clock time is **not** a metric anywhere in the pipeline. The transcript keeps stamping `wall_ms` (forensic); no scorer reports it, no report surfaces it, nothing trends on it.
- Query-set targets may flex at re-tag time: ~25 quick / ~10 multi / 3 deep are targets, and the re-tag mapping (Task 9) is the measurement that settles them.

---

### Task 1: Schema — `set:` and `correct_response_docs` fields

**Files:**
- Modify: `eval/agent_schema.py`
- Test: `tests/test_eval_agent_schema.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `AgentQuery.set: Literal["quick", "multi", "deep", "refusal", "defend"] = "quick"` and `AgentQuery.correct_response_docs: list[str] = []`; constant `QUERY_SETS = ("quick", "multi", "deep", "refusal", "defend")`. `"defend"` is infrastructure-only: `eval/defend_agent_run.py::build_defense_query` tags its ad-hoc defense queries with it (they are never part of a scored `--sets` run — the default selection excludes it). Adding it to the literal now, instead of discovering the crash at Task 9, is finding 2 from the 2026-08-16 plan review. Defaults exist ONLY so the file loads during migration (Task 9 removes them once the YAML carries explicit `set:` on every entry).

- [ ] **Step 1: Write the failing test** — append to `tests/test_eval_agent_schema.py`:

```python
from eval.agent_schema import QUERY_SETS, AgentQuery


def test_query_set_field_accepts_all_sets_and_rejects_others():
    for s in QUERY_SETS:
        q = AgentQuery(id="t", question="q", set=s)
        assert q.set == s
    import pydantic
    try:
        AgentQuery(id="t", question="q", set="extended_quick")
        raise AssertionError("extended_quick was retired — must not be accepted")
    except pydantic.ValidationError:
        pass


def test_correct_response_docs_default_empty():
    q = AgentQuery(id="t", question="q")
    assert q.correct_response_docs == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_eval_agent_schema.py -k "set_field or correct_response_docs" -v`
Expected: FAIL — `set` is not a field (pydantic `extra="forbid"` raises).

- [ ] **Step 3: Implement** — in `eval/agent_schema.py`, after the `tier` field of `AgentQuery`:

```python
    # The consolidated pipeline's selection axis (2026-08-16 spec). Replaces
    # the subsets: list as the selection mechanism in Task 9; default "quick"
    # is a migration crutch ONLY — every real query names its set explicitly
    # in the YAML, and Task 9 drops this default once they all do.
    # "defend" is reserved for defend_agent_run.py's ad-hoc defense queries
    # (never in a scored --sets run); extra="forbid" means its builder at
    # defend_agent_run.py:194 would crash at Task 9 without this value.
    set: Literal["quick", "multi", "deep", "refusal", "defend"] = "quick"
    # Document ids a correct answer MUST cite (Multi set). Hand-pinned by the
    # analyst during the approval task — the identity-consistency audit
    # (docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md)
    # is why a mechanical guess was never considered.
    correct_response_docs: list[str] = Field(default_factory=list)
```

and near the top, under imports:

```python
QUERY_SETS = ("quick", "multi", "deep", "refusal")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_eval_agent_schema.py -v`
Expected: all PASS (existing schema tests unaffected — both new fields have defaults).

- [ ] **Step 5: Commit**

```bash
git add eval/agent_schema.py tests/test_eval_agent_schema.py
git commit -m "feat(eval): add AgentQuery.set and correct_response_docs fields"
```

---

### Task 2: Runner & orchestrator — `--sets` selection (with `--subset` coexisting until Task 9)

**Files:**
- Modify: `eval/run_agent_eval.py` (argparse near line 328, `select_queries` near line 120, `build_manifest` near line 151)
- Modify: `eval/run_full_layer2.py` (argparse + `run_argv`, lines ~71-111)
- Test: `tests/test_eval_agent_runner.py`

**Interfaces:**
- Consumes: `AgentQuery.set` from Task 1.
- Produces: `select_by_sets(queries: list[AgentQuery], sets: list[str]) -> list[AgentQuery]`; CLI `--sets quick,multi` on both entry points; manifest key `"sets": [...]` (list actually selected, or `[]` for legacy `--subset` runs).

- [ ] **Step 1: Write the failing test** — append to `tests/test_eval_agent_runner.py`:

```python
from eval.agent_schema import AgentQuery
from eval.run_agent_eval import select_by_sets


def _q(id, set):
    return AgentQuery(id=id, question="q", shape="lookup", set=set)


def test_select_by_sets_union_and_order():
    qs = [_q("a", "quick"), _q("b", "deep"), _q("c", "quick"), _q("d", "refusal")]
    picked = select_by_sets(qs, ["quick", "deep"])
    assert [q.id for q in picked] == ["a", "b", "c"]  # file order preserved


def test_select_by_sets_unknown_name_raises():
    import pytest
    with pytest.raises(ValueError, match="extended_quick"):
        select_by_sets([], ["quick", "extended_quick"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_eval_agent_runner.py -k select_by_sets -v`
Expected: FAIL — `select_by_sets` not defined.

- [ ] **Step 3: Implement** — in `eval/run_agent_eval.py`, after `select_queries`:

```python
def select_by_sets(queries: list[AgentQuery], sets: list[str]) -> list[AgentQuery]:
    # Unknown set names are a hard error, not a silent empty run: a typo'd
    # --sets flag that matched zero queries would otherwise produce a
    # zero-query run dir that LOOKS successful (0 failures) and gets archived.
    from eval.agent_schema import QUERY_SETS
    unknown = [s for s in sets if s not in QUERY_SETS]
    if unknown:
        raise ValueError(
            f"unknown sets {unknown!r} — valid sets are {list(QUERY_SETS)}. "
            f"Note: extended_quick was folded into quick (2026-08-16 spec).")
    wanted = set(sets)
    return [q for q in queries if q.set in wanted]
```

In `build_manifest`, add `"sets": sets,` to the returned dict and a `sets: list[str] | None = None` parameter (callers from the `--subset` path pass `None`).

In `main()` argparse, alongside the existing `--subset`:

```python
    parser.add_argument("--sets", default=None,
                        help="comma-separated new-style sets "
                             "(quick,multi,deep,refusal); takes precedence "
                             "over --subset. --subset is retired by the "
                             "2026-08-16 consolidation once the YAML re-tag "
                             "lands.")
```

and in the selection call site, use `select_by_sets(queries, args.sets.split(","))` when `args.sets` is set, else the legacy `select_queries(...)` path.

In `eval/run_full_layer2.py`, add the same `--sets` argument and, when set, pass `--sets` through in `run_argv` INSTEAD of `--subset`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_agent_runner.py -v`
Expected: all PASS.

- [ ] **Step 5: Smoke the CLI plumbing (free)**

Run: `uv run python -m eval.run_agent_eval --sets quick --help` — verify the flag appears in help text and the process exits 0. (No run is started for `--help`.)

- [ ] **Step 6: Commit**

```bash
git add eval/run_agent_eval.py eval/run_full_layer2.py tests/test_eval_agent_runner.py
git commit -m "feat(eval): --sets selection on runner and orchestrator"
```

---

### Task 3: Drop wall-clock from every reported surface

**Files:**
- Modify: `eval/agent_scoring.py` (`aggregate`, ~line 435: `wall_p50_ms`/`wall_p95_ms`; per-query `wall_ms` STAYS)
- Modify: `eval/compare_agent_runs.py` (metric key list, ~line 24)
- Test: `tests/test_eval_agent_score_run.py` (this file owns the transcript fake builders: `make_query`, `retrieve_call`, `chunk`, `cite_call`, `make_transcript`, `ok_citation`)

**Interfaces:**
- Consumes: nothing.
- Produces: `aggregate()` output with NO wall-clock keys; compare report without wall rows. Per-query `wall_ms` remains in transcripts/rows (forensic).

- [ ] **Step 1: Write the failing test** — append to `tests/test_eval_agent_score_run.py`:

```python
def test_wall_clock_is_not_reported_anywhere():
    # Two transcripts with wildly different wall times (30000 baked into the
    # fake; vary via terminal). Summary must carry NO wall keys.
    t1 = make_transcript([retrieve_call([chunk("c-1", "ADC $1,391,157,700")])],
                         citations=[ok_citation("c-1")])
    row1 = score_transcript(make_query(), t1)
    s = aggregate([row1])
    assert "wall_p50_ms" not in s and "wall_p95_ms" not in s
    # per-query rows keep the forensic stamp
    assert row1["wall_ms"] == 30000
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_eval_agent_score_run.py -k wall_clock -v`
Expected: FAIL — `wall_p50_ms` still present.

- [ ] **Step 3: Implement** — in `aggregate()`, delete the two wall percentile keys AND the `walls = sorted(...)` line that feeds them (keep per-query `row["wall_ms"]`). Add a WHY comment at the deletion site:

```python
    # WHY wall_p50_ms/wall_p95_ms were DELETED (2026-08-16 consolidation,
    # Destin's call): wall time is dominated by provider network latency and
    # machine load (~70% absolute swings on this box, CLAUDE.md), so no
    # comparison survives a different session. tokens_to_accurate /
    # turns_to_accurate are the cost metrics. Per-query wall_ms survives in
    # the row for forensics — never aggregate it again.
```

In `eval/compare_agent_runs.py`, remove `"wall_p50_ms", "wall_p95_ms"` from the metric key list (line ~24) — leaving them renders dead rows reading "—"/"—" forever.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_agent_score_run.py tests/test_eval_agent_compare.py -v`
Expected: all PASS. Fix any compare test that asserted the wall rows (update the assertion, don't re-add the metric).

- [ ] **Step 5: Commit**

```bash
git add eval/agent_scoring.py eval/compare_agent_runs.py tests/test_eval_agent_score_run.py tests/test_eval_agent_compare.py
git commit -m "refactor(eval): drop wall-clock from reported metrics (forensic wall_ms stays in rows)"
```

---

### Task 4: Headline — `tokens_to_accurate` / `turns_to_accurate`

**Files:**
- Modify: `eval/agent_scoring.py` (`score_transcript` row + `aggregate`)
- Test: `tests/test_eval_agent_score_run.py`

**Interfaces:**
- Consumes: existing row fields `ok`, `key_facts_total`, `key_facts_matched`, `verified_citations`, `input_tokens`, `output_tokens`, `cached_tokens`, `steps`; `set` from Task 1.
- Produces per-query row fields: `accurate` (bool), `total_tokens` (int), `set` (str). Produces summary keys: `accurate_n`, `accurate_rate`, `tokens_to_accurate_mean`, `turns_to_accurate_mean`, and `accurate_headline_by_set` (dict set → `{"n": ..., "tokens_mean": ..., "turns_mean": ...}`).

- [ ] **Step 1: Write the failing tests** — append to `tests/test_eval_agent_score_run.py` (using that file's existing builders):

```python
def _clean_transcript():
    """Passes its one currency fact and carries one verified cite."""
    return make_transcript([retrieve_call([chunk("c-1", "ADC $1,391,157,700")])],
                           citations=[ok_citation("c-1")])


def test_accurate_requires_facts_passing_and_a_verified_citation():
    assert score_transcript(make_query(set="quick"), _clean_transcript())["accurate"] is True
    # facts pass but zero verified cites -> NOT accurate (fast-but-uncited)
    t = make_transcript([retrieve_call([chunk("c-1", "ADC $1,391,157,700")])],
                        citations=[])
    assert score_transcript(make_query(set="quick"), t)["accurate"] is False
    # cite present but the fact failed -> NOT accurate (fast-but-wrong)
    t = make_transcript([retrieve_call([chunk("c-1", "irrelevant")])],
                        citations=[ok_citation("c-1")], final="ADC received $999.")
    assert score_transcript(make_query(set="quick"), t)["accurate"] is False
    # zero key facts (refusal query) -> never accurate, even with a cite
    t = make_transcript([retrieve_call([chunk("c-1", "x")])],
                        citations=[ok_citation("c-1")], final="I cannot answer that.")
    refusal_q = make_query(key_facts=[], shape="refusal", should_refuse=True, set="refusal")
    assert score_transcript(refusal_q, t)["accurate"] is False


def test_headline_aggregates_only_over_accurate_rows():
    q = make_query(set="quick")
    good = score_transcript(q, _clean_transcript())          # accurate
    good2 = score_transcript(q, _clean_transcript())         # accurate
    wrong = score_transcript(
        q, make_transcript([retrieve_call([chunk("c-1", "irrelevant")])],
                           citations=[ok_citation("c-1")], final="ADC received $999."))
    s = aggregate([good, good2, wrong])
    assert s["accurate_n"] == 2
    assert s["tokens_to_accurate_mean"] == good["total_tokens"]  # wrong row excluded
    assert s["accurate_headline_by_set"]["quick"]["n"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_agent_score_run.py -k "accurate" -v`
Expected: FAIL — fields missing.

- [ ] **Step 3: Implement** — in `score_transcript`, after `verified_citations` is set:

```python
    # Headline eligibility (2026-08-16 consolidation): an "accurate" response
    # passes ALL its key facts AND produces >=1 verified citation. Refusal
    # queries (0 key facts) are never "accurate" — their quality lives in
    # refusal_correct_rate, and counting them here would inflate the headline
    # with cheap refuses (the vacuous-pass hole the spec explicitly closes).
    row["accurate"] = bool(
        frame_type == "_done" and total_facts
        and matched == total_facts and row["verified_citations"] >= 1
    )
    row["total_tokens"] = row["input_tokens"] + row["output_tokens"] + row["cached_tokens"]
```

In `aggregate()`:

```python
    acc = [r for r in ok_rows if r["accurate"]]
    # WHY the headline excludes rather than zeroes inaccurate rows: a
    # regression that trades correctness for speed must show as accurate_rate
    # dropping while the headline counts FEWER queries — not as a faster
    # average. Zeroing would reward exactly the failure mode.
    headline_by_set: dict[str, dict] = {}
    for sname in sorted({r.get("set") for r in acc if r.get("set")}):
        sub = [r for r in acc if r.get("set") == sname]
        headline_by_set[sname] = {
            "n": len(sub),
            "tokens_mean": _mean([r["total_tokens"] for r in sub]),
            "turns_mean": _mean([r["steps"] for r in sub]),
        }
```

and add to the summary dict: `"accurate_n": len(acc)`, `"accurate_rate": (len(acc) / len(ok_rows)) if ok_rows else None`, `"tokens_to_accurate_mean": _mean([r["total_tokens"] for r in acc])`, `"turns_to_accurate_mean": _mean([r["steps"] for r in acc])`, `"accurate_headline_by_set": headline_by_set`. Rows need the query's `set`: pass it into the row in `score_transcript` (`row["set"] = query.set`).

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_agent_score_run.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/agent_scoring.py tests/test_eval_agent_score_run.py
git commit -m "feat(eval): tokens/turns-to-accurate headline with per-set breakdown"
```

---

### Task 5: `document_correctness` scorer (Multi set)

**Files:**
- Modify: `eval/agent_scoring.py`
- Test: `tests/test_eval_agent_score_run.py`

**Interfaces:**
- Consumes: `query.correct_response_docs`, the transcript's verified citations (`citations(t)`), and retrieve outputs (`_retrieved_chunks(t)` — every chunk carries `doc_id`, see `harness/tools.py:1405`).
- Produces per-query row fields: `document_correctness` (float|None, Multi-set queries only), `multi_unanswered` (bool). Summary keys: `document_correctness_mean` (over Multi rows with a value), `multi_unanswered_n`.

- [ ] **Step 1: Write the failing tests** — append to `tests/test_eval_agent_score_run.py`. The file's `chunk(cid, text)` builder hardcodes `doc_id: "d"`; extend it: `def chunk(cid, text, doc_id="d"):` with `"doc_id": doc_id` in the dict. Then:

```python
def _multi_query():
    return make_query(id="m-001", set="multi",
                      correct_response_docs=["jlbc-approps-2024"])


def test_document_correctness_share_over_verified_cites():
    # 2 verified cites: c-1 on the correct doc, c-2 on a wrong doc
    t = make_transcript([retrieve_call([chunk("c-1", "ADC $1,391,157,700",
                                              doc_id="jlbc-approps-2024"),
                                        chunk("c-2", "ADC $1,391,157,700",
                                              doc_id="jlbc-baseline-2024")])],
                        citations=[ok_citation("c-1"), ok_citation("c-2")])
    row = score_transcript(_multi_query(), t)
    assert row["document_correctness"] == 0.5
    assert row["multi_unanswered"] is False


def test_document_correctness_none_and_unanswered_when_no_citations():
    t = make_transcript([retrieve_call([chunk("c-1", "ADC $1,391,157,700",
                                              doc_id="jlbc-approps-2024")])],
                        citations=[])
    row = score_transcript(_multi_query(), t)
    assert row["document_correctness"] is None
    assert row["multi_unanswered"] is True


def test_document_correctness_not_computed_off_multi_set():
    row = score_transcript(make_query(set="quick"), _clean_transcript())
    assert row["document_correctness"] is None and row["multi_unanswered"] is False
```

(`ok_citation` cites chunk c-1/c-2 via its default `chunk_id` input — extend it the same way if its builder pins one chunk id: `def ok_citation(cid="c-1", ...)` already takes `cid`, and the scorer matches cite input chunk_ids against `_retrieved_chunks`, so cite_call's `input.chunk_id` needs to vary too: add `cid` to `cite_call` likewise. Verify against the builders before assuming.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_agent_score_run.py -k document_correctness -v`
Expected: FAIL.

- [ ] **Step 3: Implement** — in `score_transcript`:

```python
    # Doc-type relationship axis (2026-08-16 consolidation, priority 3): the
    # "cited the Baseline when it should have cited the Appropriations
    # Report" test. Purely transcript-mechanical — chunk_id -> doc_id resolves
    # from this run's own retrieve outputs (harness/tools.py:1405), so no
    # corpus access is needed. Unresolvable chunk ids (cite without a prior
    # retrieve in transcript) count against the share AND are loud: they mean
    # a transcript invariant broke, which is an error-ledger matter.
    row["document_correctness"] = None
    row["multi_unanswered"] = False
    if query.set == "multi" and query.correct_response_docs:
        id_to_doc = {c["chunk_id"]: c.get("doc_id")
                     for c in _retrieved_chunks(t) if c.get("doc_id")}
        verified = [c for c in citations(t) if c.get("ok")]
        if not verified:
            # Cited nothing != cited the wrong doc-type; key facts still say
            # whether the answer was right. Reported distinctly, never as 0.
            row["multi_unanswered"] = True
        else:
            targets = [id_to_doc.get(c.get("chunk_id")) for c in verified]
            hits = sum(1 for d in targets if d in query.correct_response_docs)
            row["document_correctness"] = hits / len(verified)
```

In `aggregate()`: `multi_rows = [r for r in ok_rows if r["document_correctness"] is not None]` → `"document_correctness_mean": _mean([r["document_correctness"] for r in multi_rows])`, `"multi_unanswered_n": sum(1 for r in ok_rows if r["multi_unanswered"])`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_agent_score_run.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/agent_scoring.py tests/test_eval_agent_score_run.py
git commit -m "feat(eval): document_correctness axis for the Multi set"
```

---

### Task 6: Tool-error ledger

**Files:**
- Create: `eval/agent_errors.py`
- Modify: `eval/score_agent_run.py` (write `errors.json` / `errors.md` next to `scores.json`)
- Test: `tests/test_eval_agent_errors.py`

**Interfaces:**
- Consumes: `eval.agent_transcript.Transcript`, `tool_calls(t)`, `parsed_output(call)`, `AgentQuery`.
- Produces: `harvest_errors(t: Transcript, query: AgentQuery) -> list[ErrorRow]` where `ErrorRow = {"kind", "tool", "turn", "query_id", "detail"}`; `summarize_errors(rows: list[dict]) -> dict` keyed kind → count + query ids. Kinds: `retrieve_error`, `cite_failure`, `argument_error`, `malformed_output`, `crashed_query`.

- [ ] **Step 1: Write the failing tests** — create `tests/test_eval_agent_errors.py`, reusing the builders from `tests/test_eval_agent_score_run.py` (tests/ is a package; cross-file builder imports are an existing repo pattern — see `tests/test_citation_end_to_end.py`):

```python
"""Error-ledger mechanics. Fakes only — builders reused from
tests/test_eval_agent_score_run.py."""
import json

from eval.agent_errors import harvest_errors, summarize_errors
from eval.agent_schema import AgentQuery, KeyFact
from tests.test_eval_agent_score_run import (
    chunk, make_query, make_transcript, ok_citation, retrieve_call)

FACT = KeyFact(kind="string", value="total")
Q = AgentQuery(id="q1", question="q", set="quick", key_facts=[FACT], shape="lookup")


def test_cite_failures_are_harvested_with_their_turn():
    # one passing cite + one failing cite attempt
    from tests.test_eval_agent_score_run import cite_call
    calls = [retrieve_call([chunk("c-1", "total text")]),
             cite_call(ok=True), cite_call(ok=False, error="quote not found")]
    t = make_transcript(calls, citations=[ok_citation("c-1")])
    rows = harvest_errors(t, Q)
    fails = [r for r in rows if r["kind"] == "cite_failure"]
    assert len(fails) == 1
    assert fails[0]["query_id"] == "q1" and isinstance(fails[0]["turn"], int)


def test_retrieve_tool_error_is_harvested():
    bad_retrieve = {"toolUseId": "t-r", "toolName": "retrieve",
                    "input": {"query": "x"},
                    "output": json.dumps({"error": "unknown filter dimension"}),
                    "isError": True}
    t = make_transcript([bad_retrieve])
    errs = [r for r in harvest_errors(t, Q) if r["kind"] == "retrieve_error"]
    assert len(errs) == 1 and errs[0]["tool"] == "retrieve"


def test_crashed_query_is_one_error_row():
    # terminal frame is not _done (pattern: test_error_terminal_scores_as_failure)
    from eval.agent_transcript import Transcript
    t = Transcript(meta={"query_id": "q1", "repeat": 1}, events=[],
                   terminal={"frame": {"type": "_error", "message": "boom"},
                             "wall_ms": 1})
    rows = harvest_errors(t, Q)
    assert any(r["kind"] == "crashed_query" for r in rows)


def test_summarize_groups_by_kind():
    rows = [{"kind": "cite_failure", "query_id": "a", "turn": 3, "tool": "cite", "detail": ""},
            {"kind": "cite_failure", "query_id": "b", "turn": 1, "tool": "cite", "detail": ""},
            {"kind": "retrieve_error", "query_id": "a", "turn": 2, "tool": "retrieve", "detail": ""}]
    s = summarize_errors(rows)
    assert s["cite_failure"]["count"] == 2 and set(s["cite_failure"]["queries"]) == {"a", "b"}
    assert s["retrieve_error"]["count"] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_agent_errors.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement** `eval/agent_errors.py`:

```python
"""Tool-error ledger — every tool-call error in a transcript, tied to the
turn it cost. Spec: 2026-08-16-consolidated-eval-pipeline-design.md.

WHY errors are tied to turns, not just counted: an error in turn 2 of a
9-turn query cost 8 turns of downstream work; the same error in the final
turn cost nothing. The ledger feeds prompt/tool-description tuning, and
tuning needs to know WHERE the burn happened.
"""
from __future__ import annotations
from eval.agent_schema import AgentQuery
from eval.agent_transcript import Transcript, tool_calls, parsed_output

KINDS = ("retrieve_error", "cite_failure", "argument_error",
         "malformed_output", "crashed_query")


def harvest_errors(t: Transcript, query: AgentQuery) -> list[dict]:
    rows = []
    # turn = index of the assistant message in the event stream, so each
    # error points at the step that paid for it.
    for i, call in enumerate(tool_calls(t)):
        name = call.get("name") or ""
        out = parsed_output(call)
        detail = ""
        if out and out.get("error"):
            rows.append({"kind": "retrieve_error" if name == "retrieve" else "argument_error",
                         "tool": name, "turn": i, "query_id": query.id,
                         "detail": str(out["error"])[:200]})
    # cite/cite_batch attempts are harvested ONCE (not per call in the loop
    # above, which would double-count): agent_scoring's cite_attempts already
    # flattens cite_batch slots. Re-use ITS pass/fail logic — do NOT re-derive
    # a second definition of "cite passed" here (one producer, one truth:
    # the cross-item-defect lesson from the identity audit). Turn attribution
    # for a failed attempt: the index of the cite call that carried it, or
    # the last tool call when the flattening does not line up.
    from eval.agent_scoring import cite_attempts, _attempt_passed
    calls = tool_calls(t)
    cite_turns = [i for i, c in enumerate(calls) if c.get("name") in ("cite", "cite_batch")]
    for attempt in cite_attempts(t):
        if not _attempt_passed(attempt):
            rows.append({"kind": "cite_failure", "tool": "cite",
                         "turn": cite_turns[0] if cite_turns else -1,
                         "query_id": query.id,
                         "detail": str(attempt.get("result"))[:200]})
    if (t.terminal.get("frame") or {}).get("type") != "_done":
        rows.append({"kind": "crashed_query", "tool": "", "turn": -1,
                     "query_id": query.id, "detail": "terminal frame not _done"})
    return rows


def summarize_errors(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        slot = out.setdefault(r["kind"], {"count": 0, "queries": set()})
        slot["count"] += 1
        slot["queries"].add(r["query_id"])
    return {k: {"count": v["count"], "queries": sorted(v["queries"])}
            for k, v in sorted(out.items())}
```

(Import `cite_attempts`/`_attempt_passed` from `eval.agent_scoring` for the cite-failure branch — import is safe, scoring is pure functions.)

In `eval/score_agent_run.py::score_run`, after rows are built, also `harvest_errors(t, queries[qid])` per transcript, collect all rows, and return them under a new top-level key `"errors"`; in `main()`, write `errors.json` and a small `errors.md` (kind table + per-query lines) into `run_dir` using the same tmp-rename pattern as `scores.json`.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_agent_errors.py tests/test_eval_agent_score_run.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/agent_errors.py eval/score_agent_run.py tests/test_eval_agent_errors.py
git commit -m "feat(eval): tool-error ledger per run (every error tied to its turn)"
```

---

### Task 7: Over-time archive (`eval/over_time.py`)

**Files:**
- Create: `eval/over_time.py`
- Modify: `eval/score_agent_run.py` (append after scoring, only when `manifest.json` exists in the run dir)
- Test: `tests/test_eval_over_time.py`

**Interfaces:**
- Consumes: run dir with `manifest.json` + `scores.json`.
- Produces: `append_run(results_root: Path, run_dir: Path, profile: dict) -> None` writing `eval/results/over-time/index.json` (list) and appending one line to `metrics.jsonl`; `segments(rows: list[dict]) -> list[list[dict]]` splitting rows at every `queries_sha256`/`corpus_counts` change; `render_trend_md(rows: list[dict]) -> str`.

- [ ] **Step 1: Write the failing tests** — `tests/test_eval_over_time.py`:

```python
"""Archive mechanics. tmp_path only — never eval/results itself."""
import json
from eval.over_time import append_run, segments, render_trend_md


def _run(tmp_path, name, sha, corpus_n, kf_rate):
    d = tmp_path / name; d.mkdir()
    (d / "manifest.json").write_text(json.dumps({
        "git_sha": "abc", "queries_sha256": sha,
        "corpus_counts": {"budget_chunks": corpus_n},
        "tier_models": {"standard": "m"}, "timestamp": "2026-08-16T0000Z"}))
    (d / "scores.json").write_text(json.dumps({
        "summary": {"key_fact_rate": kf_rate, "tokens_to_accurate_mean": 100,
                    "turns_to_accurate_mean": 3, "accurate_n": 2,
                    "document_correctness_mean": 0.8, "total_cost_usd": 0.4,
                    "n": 3, "errors": 0}, "per_query": [], "skipped": []}))
    return d


def test_append_writes_index_and_jsonl(tmp_path):
    append_run(tmp_path, _run(tmp_path, "r1", "aaa", 100, 0.9), {"sets": ["quick"], "workers": 1, "model": "m"})
    append_run(tmp_path, _run(tmp_path, "r2", "aaa", 100, 0.8), {"sets": ["quick"], "workers": 1, "model": "m"})
    lines = (tmp_path / "over-time" / "metrics.jsonl").read_text().strip().split("\n")
    assert len(lines) == 2
    first = json.loads(lines[0])
    assert first["queries_sha256"] == "aaa" and first["profile"]["sets"] == ["quick"]
    index = json.loads((tmp_path / "over-time" / "index.json").read_text())
    assert len(index) == 2


def test_segments_split_on_sha_or_corpus_change(tmp_path):
    rows = [
        {"run": "r1", "queries_sha256": "aaa", "corpus_counts": {"budget_chunks": 100}},
        {"run": "r2", "queries_sha256": "aaa", "corpus_counts": {"budget_chunks": 100}},
        {"run": "r3", "queries_sha256": "bbb", "corpus_counts": {"budget_chunks": 100}},  # query edit
        {"run": "r4", "queries_sha256": "bbb", "corpus_counts": {"budget_chunks": 101}},  # re-ingest
    ]
    segs = segments(rows)
    assert [len(s) for s in segs] == [2, 1, 1]


def test_append_is_refused_without_a_manifest(tmp_path):
    d = tmp_path / "nomanifest"; d.mkdir()
    import pytest
    with pytest.raises(FileNotFoundError):
        append_run(tmp_path, d, {})


def test_append_is_idempotent_per_run(tmp_path):
    r = _run(tmp_path, "r1", "aaa", 100, 0.9)
    append_run(tmp_path, r, {})
    append_run(tmp_path, r, {})  # re-score of the same run
    lines = (tmp_path / "over-time" / "metrics.jsonl").read_text().strip().split("\n")
    assert len(lines) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_eval_over_time.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement** `eval/over_time.py`:

```python
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
```

In `eval/score_agent_run.py::main`, after writing `scores.json`:

```python
    # Over-time append only when a manifest exists (live runs always have
    # one; synthetic test dirs may not — archiving a manifest-less run would
    # write trend rows with no comparability keys, the exact thing segments()
    # exists to police).
    if (args.run_dir / "manifest.json").exists():
        from eval.over_time import append_run, render_trend_md
        # archive lives at eval/results/over-time/ — a fixed repo-relative
        # root (not derived from --results-dir, which tests and ad-hoc runs
        # override; the ONE trend must live in ONE place).
        # NOTE: score_agent_run's parser has NO --note flag (plan review
        # finding 4 caught `args.note` here — it would AttributeError on the
        # first live scored run and stop the orchestrator before the judge).
        # The run's own manifest carries the note; profile here records what
        # the ARCHIVER knows, which is the queries file it scored against.
        over_root = Path("eval/results")
        append_run(over_root, args.run_dir,
                   profile={"queries_file": args.queries_file})
        rows = [json.loads(l) for l in (over_root / "over-time" / "metrics.jsonl")
                .read_text(encoding="utf-8").splitlines() if l.strip()]
        (over_root / "over-time" / "trend.md").write_text(render_trend_md(rows), encoding="utf-8")
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_over_time.py tests/test_eval_agent_score_run.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/over_time.py eval/score_agent_run.py tests/test_eval_over_time.py
git commit -m "feat(eval): over-time archive with segmented trend rendering"
```

---

### Task 8: Consolidated report + judge chunk-relevance + compare-tool honesty

**Files:**
- Modify: `eval/score_agent_run.py` (`_md`: add per-set headline table + error-ledger table)
- Modify: `eval/judge_agent_run.py` (`build_judge_payload`, ~line 110: include retrieved chunk ids + doc_ids; `parse_judge_json` ~line 194 and the summary means ~line 437: harvest `chunk_relevance` so it is STORED and aggregated, not just asked for) and `eval/agent_judge_prompt.md` (new output field `chunk_relevance`)
- Modify: `eval/compare_agent_runs.py` (headline keys in the arrow tables; control linkage)
- Test: `tests/test_eval_agent_score_run.py`, `tests/test_eval_agent_judge.py`, `tests/test_eval_agent_compare.py`

**Interfaces:**
- Consumes: `scores["summary"]["accurate_headline_by_set"]`, `scores["errors"]` (Task 6), judge payload shape from Task-unchanged machinery.
- Produces: `scores.md` sections "Headline by set" and "Tool-error ledger"; judge payload key `retrieved_chunks` (id + doc_id + one-line preview, capped 30) and judge output schema field `chunk_relevance` (0..1 + one-line rationale).

- [ ] **Step 1: Write the failing tests**

In `tests/test_eval_agent_score_run.py`:

```python
def test_md_contains_headline_by_set_and_error_ledger(tmp_path):
    scores = {"summary": {"accurate_headline_by_set": {"quick": {"n": 2, "tokens_mean": 200.0, "turns_mean": 3.0}}},
              "per_query": [], "skipped": [],
              "errors": [{"kind": "cite_failure", "query_id": "a", "turn": 3, "tool": "cite", "detail": "no match"}]}
    md = _md(scores, tmp_path)
    assert "Headline by set" in md and "| quick |" in md
    assert "Tool-error ledger" in md and "cite_failure" in md
```

In `tests/test_eval_agent_judge.py` — that file builds its own fakes (it has its own local `make_query` at lines ~44-52 and reads the shared JSONL fixture; it does NOT import sibling-test builders, and no `fake_transcript` fixture exists anywhere in the repo — plan review finding 5). Follow its existing pattern:

```python
def test_judge_payload_includes_retrieved_chunk_provenance():
    # Same fake style this file already uses: read_transcript(FIXTURE) or a
    # Transcript built inline with one retrieve call carrying doc_id.
    t = read_transcript(FIXTURE)  # or the file's inline-Transcript pattern
    payload = build_judge_payload(make_query(), t)
    assert "retrieved_chunks" in payload
    assert all(set(c) >= {"chunk_id", "doc_id"} for c in payload["retrieved_chunks"])
```

- [ ] **Step 2: Run tests to verify they fail**, then implement.

`_md`: after the Summary section, insert:

```python
    hs = s.get("accurate_headline_by_set") or {}
    if hs:
        lines += ["", "## Headline by set (accurate queries only)", "",
                  "| set | n | tokens_to_accurate | turns_to_accurate |", "|---|---|---|---|"]
        for name, d in sorted(hs.items()):
            lines.append(f"| {name} | {d['n']} | {d['tokens_mean']:.0f} | {d['turns_mean']:.1f} |")
    errs = scores.get("errors") or []
    if errs:
        from eval.agent_errors import summarize_errors
        lines += ["", "## Tool-error ledger", "",
                  "| kind | count | queries |", "|---|---|---|"]
        for kind, d in summarize_errors(errs).items():
            lines.append(f"| {kind} | {d['count']} | {', '.join(d['queries'])} |")
```

`build_judge_payload`: add

```python
    # Judge-scored chunk relevance (2026-08-16 consolidation): the judge sees
    # what was retrieved so it can answer "do these chunks match what the
    # query is actually asking?" — the signal chunk-id recall cannot give.
    from eval.agent_scoring import _retrieved_chunks
    payload["retrieved_chunks"] = [
        {"chunk_id": c.get("chunk_id"), "doc_id": c.get("doc_id"),
         "preview": (c.get("text") or "")[:160]}
        for c in _retrieved_chunks(t)[:30]
    ]
```

`agent_judge_prompt.md`: add to the JSON output contract: `"chunk_relevance": <0..1>, "chunk_relevance_rationale": "<one line>"`.

`judge_agent_run.py`: plan review finding 7 — asking the judge for a field and then dropping it on the floor buys nothing. In `parse_judge_json`, accept and carry through `chunk_relevance` (float 0..1, None when absent/malformed); in the per-query result dict written to `judge.json`, store it; in the summary means block, add `"chunk_relevance_mean"` over queries that have it.

- [ ] **Step 3: Compare-tool honesty** — `eval/compare_agent_runs.py` currently knows nothing about the new keys. Three additions:

```python
# 1) Arrow direction for the new summary keys (the key lists live ~line 17-28):
#    lower-is-better: tokens_to_accurate_mean, turns_to_accurate_mean, tool errors
#    higher-is-better: accurate_rate, document_correctness_mean, chunk_relevance_mean
_LOWER_IS_BETTER += ["tokens_to_accurate_mean", "turns_to_accurate_mean"]
_HIGHER_IS_BETTER += ["accurate_rate", "document_correctness_mean",
                      "chunk_relevance_mean"]

# 2) Population-dependence guard, same shape as retrieves_after_sufficient
#    (compare.py:55-58): tokens/turns_to_accurate average over the ACCURATE
#    population, so their arrow is withheld when accurate_n differs between
#    runs — a bigger accurate population legitimately changes the mean.

# 3) Control linkage (spec Honesty guards, plan review finding 6): when both
#    runs have an over-time archive row, the compare report prints each side's
#    metrics.jsonl row (run_dir + queries_sha256 + corpus_counts) under a
#    "Comparability" banner, so a reader can see WHICH prior rows are being
#    compared instead of trusting remembered numbers.
```

Tests in `tests/test_eval_agent_compare.py`: headline keys get the right arrow direction; the arrow is withheld when `accurate_n` differs; the Comparability banner prints when archive rows exist.

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_eval_agent_score_run.py tests/test_eval_agent_judge.py tests/test_eval_agent_compare.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add eval/score_agent_run.py eval/judge_agent_run.py eval/agent_judge_prompt.md eval/compare_agent_runs.py tests/test_eval_agent_score_run.py tests/test_eval_agent_judge.py tests/test_eval_agent_compare.py
git commit -m "feat(eval): consolidated report sections + judge chunk-relevance scoring + compare-tool headline arrows and comparability banner"
```

---

### Task 9: Re-tag the query set (the atomic YAML flip)

**Files:**
- Modify: `eval/agent_queries.yaml` (every entry: `subsets:` → `set:`; remove the SUBSETS block from the header; document the sets contract)
- Modify: `eval/agent_schema.py` (drop the `set` default and the `subsets` field; `QUERY_SETS` unchanged)
- Modify: `eval/run_agent_eval.py` + `eval/run_full_layer2.py` (remove `--subset` and `select_queries`; `--sets` default `quick,multi,deep,refusal`)
- Modify: `eval/defend_agent_run.py` (`subsets=["defend"]` → `set="defend"` at ~line 194 — plan review finding 2: `extra="forbid"` makes this a runtime crash if missed)
- Rewrite: `tests/test_eval_agent_queries.py` subset tests → set tests
- Modify: `tests/test_eval_agent_runner.py` (drop the `select_queries` import at line 14-19 and `test_select_queries_by_subset_and_ids` at 233-239; builder's `subsets=` → `set=` at line 35; `build_manifest(..., subset=...)` calls at 244/261/266 → `sets=`)
- Modify: `tests/test_run_full_layer2.py` (all four `_call_main` invocations use `["--subset", ...]` at lines 41/59/69/78 → `["--sets", ...]`)
- Modify: `tests/test_eval_agent_schema.py` (`VALID` fixture at line 19 `subsets:` → `set:`; `test_defaults_applied` at line 56 asserts `q.subsets` → assert `q.set` once the default is gone, or drop that half of the assertion)
- Modify: `tests/test_defend_agent_run.py` (`test_build_defense_query_carries_corpus_tier_and_empty_keyfacts` at 96-108 asserts the `subsets` field → `set == "defend"`)

**Interfaces:**
- Consumes: Tasks 1-8 all merged.
- Produces: the 35 existing queries each carrying an explicit `set:`; `--subset` gone everywhere; structural tests enforcing the new contract.

**Mapping (verify against the real file before editing — this mapping is a hypothesis):**

| Current tag | Target set | Notes |
|---|---|---|
| `smoke`/`full` queries whose contract is one retrieve call, single agency/FY | `quick` | Most `lookup` shapes. Verify count lands near ~25; record the actual number in the commit. |
| `dr-probe` (4 queries) | `deep` (3) | The General Fund revenue seed + the two best-fitting others. The 4th is re-homed to `quick`/`multi` if it is actually narrower, else dropped — decide explicitly, state which in the commit. |
| All 5 `should_refuse: true` | `refusal` | Tag, not headline set. |
| Cross-agency/cross-year queries | `multi` | Expect FEW or ZERO genuine multi queries in the current 35 — that is fine; Task 10 authors them. Do not force a lookup into multi to fill a quota. |

- [ ] **Step 1: Rewrite the structural tests FIRST** — in `tests/test_eval_agent_queries.py`, replace `test_smoke_subset_is_small_and_diverse`, `test_dr_probe_subset`, `test_full_subset_is_standard_tier_only` with:

```python
from eval.agent_schema import QUERY_SETS


def test_every_query_has_an_explicit_set():
    from eval.agent_schema import AgentQuery as _AQ
    for q in QUERIES:
        assert q.set in QUERY_SETS, f"{q.id}: unknown set {q.set}"
    # the retired mechanism must not survive in the schema at all
    assert "subsets" not in _AQ.model_fields


def test_set_sizes():
    counts = Counter(q.set for q in QUERIES)
    assert counts["quick"] >= 20          # target ~25; floor not target (flex)
    assert counts["deep"] == 3
    assert counts["refusal"] == 5
    # multi has a floor of 0 until Task 10 authors them; assert presence only
    assert counts["multi"] >= 0


def test_deep_queries_carry_at_least_one_key_fact():
    # The vacuous-pass hole: with 0 facts the headline's "passes key facts"
    # bar is trivially true and a Deep query counts as accurate on a citation
    # alone. agent_scoring returns key_fact_rate=None at total_facts==0.
    for q in QUERIES:
        if q.set == "deep":
            assert q.key_facts, f"{q.id}: deep queries must carry >=1 key fact"


def test_multi_queries_pin_correct_response_docs():
    for q in QUERIES:
        if q.set == "multi":
            assert q.correct_response_docs, f"{q.id}: multi set requires correct_response_docs"
            assert all(d.strip() for d in q.correct_response_docs)


def test_standard_tier_is_not_polluted_by_deep():
    # Port of the old Finding-1 guard, restated for sets: deep queries are
    # selected out of cheap runs by set selection itself.
    deeps = [q.id for q in QUERIES if q.set == "deep"]
    assert all(q.tier == "deep_research" for q in QUERIES if q.id in deeps)
```

Keep every other test in the file (shape quotas, budget corpus, key-fact parses) unchanged.

- [ ] **Step 2: Run to confirm they fail**

Run: `uv run pytest tests/test_eval_agent_queries.py -v`
Expected: FAIL — YAML still has `subsets:`.

- [ ] **Step 3: Edit the YAML** — for every entry, replace `subsets: [...]` with the mapped `set: <name>`; rewrite the file-header SUBSETS block into a SETS block stating each set's authoring contract (copy the contract table from the spec); apply the dr-probe 4→3 decision and record it in the commit message.

- [ ] **Step 4: Drop the migration crutches and chase every consumer** — `agent_schema.py`: remove the `= "quick"` default from `set` and delete the `subsets` field. `run_agent_eval.py` / `run_full_layer2.py`: delete `--subset` and `select_queries`; default `--sets quick,multi,deep,refusal`; rename the `build_manifest` parameter `subset:` → `sets:`. `eval/defend_agent_run.py` line ~194: `subsets=["defend"]` → `set="defend"`. Then update ALL four test files listed in Files (runner, full_layer2, schema, defend) — the plan review found each of them red after this step when they were missed. Verify nothing else references the old names:

```bash
git grep -n "subsets" -- eval/ tests/ | grep -v "agent_queries.yaml"
git grep -n "select_queries\|--subset" -- eval/ tests/
```

Expected: empty output (the YAML header is rewritten in Step 3).

- [ ] **Step 5: Full suite green**

Run: `uv run pytest tests/ -k "eval or defend or layer2 or full_layer2" -q`
Expected: all PASS — specifically including `tests/test_eval_agent_runner.py`, `tests/test_run_full_layer2.py`, `tests/test_eval_agent_schema.py`, `tests/test_defend_agent_run.py`. Do not commit with any of them red; the "atomic flip" only counts when collection AND assertions pass everywhere.

- [ ] **Step 6: Commit**

```bash
git add eval/agent_queries.yaml eval/agent_schema.py eval/run_agent_eval.py eval/run_full_layer2.py eval/defend_agent_run.py tests/test_eval_agent_queries.py tests/test_eval_agent_runner.py tests/test_run_full_layer2.py tests/test_eval_agent_schema.py tests/test_defend_agent_run.py
git commit -m "refactor(eval): re-tag query sets (subsets -> set), retire smoke/full/dr-probe

Mapping recorded: N quick, M multi, 3 deep, 5 refusal. dr-probe 4th query
decision: <re-homed to X | dropped>, because <reason>."
```

---

### Task 10: Extend the set — author new queries, tune weak ones, verify, get approval

**This task spends money and ends with a HUMAN GATE. Do not start the paid pass without Destin's explicit go-ahead.**

**Files:**
- Create: `scripts/verify_agent_query.py`
- Modify: `eval/agent_queries.yaml` (add/tune entries)
- Modify: `eval/README.md` (see Task 11)

**Interfaces:**
- Consumes: everything from Tasks 1-9; `JLBC_DATA_DIR` resolvable; an OpenRouter key in settings for the paid ground-truth pass.
- Produces: the approved `eval/agent_queries.yaml` at ~25 quick / ~10 multi / 3 deep / 5 refusal; a written approval note (date + Destin's go-ahead) in the final commit message.

- [ ] **Step 1: Build the verification script (free)** — `scripts/verify_agent_query.py`: takes `--id <query_id>` (or `--all`); for each query: (a) re-run `load_agent_queries` + the pytest structural checks (already covered by the suite — invoke `pytest tests/test_eval_agent_queries.py -q`), (b) corpus scan: every `key_fact` string/currency must appear in some `budget_chunks` text via `store.chunk_store.ChunkStore().scan(...)` (pattern: see `tests/test_eval_agent_queries.py` header for the original verification method), (c) reachability: one top-20 `retrieve()` of the verbatim question returns at least one chunk containing each fact. Print PASS/FAIL per query with the missing facts named.

```bash
uv run python scripts/verify_agent_query.py --all
```

Expected: PASS for every untouched re-tagged query (their verification is inherited); FAIL lines are the authoring work-list.

- [ ] **Step 2: Author the Multi set (~10 queries)** — against the live corpus, per the spec's contract (2-3 narrow agencies × 2-3 FYs each). Pin `correct_response_docs` by hand using `ChunkStore().scan(...)` and the identity-consistency audit (`docs/superpowers/investigations/2026-08-16-identity-consistency-audit.md`) as the doc-id reference. Verify each with the script.

- [ ] **Step 3: Author new Quick queries to reach ~25, tune weak existing ones.** Tune = fix the question/wording OR a key fact that the verify script shows unreachable. Every tuned query re-runs Step 1's verification (the rule is in the spec: a tuned query that silently lost its fact is worse than an old one).

- [ ] **Step 4: Structural + verification gates green**

Run: `uv run pytest tests/test_eval_agent_queries.py -v && uv run python scripts/verify_agent_query.py --all`
Expected: all PASS / all queries PASS.

- [ ] **Step 5: Commit the set (pre-approval)**

```bash
git add eval/agent_queries.yaml scripts/verify_agent_query.py
git commit -m "feat(eval): consolidated query set — multi authored, quick grown to N, tuned queries re-verified"
```

- [ ] **Step 6: HUMAN GATE — the paid ground-truth pass.** Present the set to Destin. With his go-ahead: run each query through the real app serially (`--workers 1`, `--sets quick,multi,deep,refusal`), then he manually navigates the budget documents to pick the most-correct answer/document the judge should score against. Iterate the YAML on his feedback (re-run Step 4 after every edit — each edit bumps `queries_sha256` and starts a new trend segment; that is correct behaviour). Only after his approval, record it:

```bash
git add eval/agent_queries.yaml
git commit -m "feat(eval): query set APPROVED by Destin <date> — scoring may now run against it"
```

---

### Task 11: Documentation

**Files:**
- Modify: `eval/README.md` (Layer 2 section)
- Modify: `STATUS.md` (record what shipped / what's open)

- [ ] **Step 1: Rewrite the README's Layer 2 section** — replace smoke/full/dr-probe language with the sets; document the one command:

```bash
uv run python -m eval.run_full_layer2 --sets quick,multi,deep,refusal --workers 3
```

cost guidance (quick+multi+refusal ≈ $0.50-1.50; deep adds ~$6-9; judge is a second charge — verify against the last real run before publishing numbers, do not copy stale ones), the headline metric definition (tokens/turns-to-accurate, the exclusion rule, why wall-clock is gone), the over-time archive layout, and the "after a re-ingest / after editing queries" notes (trend segments, no automated chunk-id rebinding).

- [ ] **Step 2: STATUS.md** — record the pipeline as shipped (or shipped-pending-approval if Task 10's gate is still open), referencing the spec and this plan.

- [ ] **Step 3: Commit**

```bash
git add eval/README.md STATUS.md
git commit -m "docs(eval): consolidated pipeline README + STATUS"
```

---

## Self-review notes

- **Spec coverage:** sets/schema (T1, T9), `--sets` runner + 1/2-model profile (T2 — the 2-model head-to-head rides `--model` twice via two orchestrator invocations + `compare_agent_runs.py`; spec's "one run dir each, compared by existing compare" needs no new runner code), wall-clock drop (T3), headline (T4), retrieval/chunk quality (existing `retrieval_efficiency` untouched by design; judge chunk-relevance feed + scoring = T8), tool-call efficiency (already consolidated per-query rows — T8 surfaces them per-set), document_correctness (T5), error ledger (T6), archive + segments + idempotency (T7), report + compare-tool honesty (T8), re-tag/add/tune + re-verify (T9, T10), approval gate (T10 Step 6), docs (T11).
- **Known deviation from spec, recorded:** scoring (b) keeps the shipped `retrieval_efficiency` definition rather than the spec's earlier cited-only narrowing — the spec was corrected in place before this plan was written (cited-only saturated near 1.0, failure recorded in `eval/agent_scoring.py`). Second recorded deviation: the archive append lives in `score_agent_run.main` rather than the orchestrator (so standalone re-scores archive too); made idempotent per run_dir to absorb that.
- **Open spec decisions at plan time:** the "accurate" bar uses the mechanical default (T4); Deep set is excludable via `--sets` (T2). If Destin overrides either at review, only T4/T2 change.

### Specialist review round (2026-08-16)

Reviewed by a read-only reviewer specialist; every accepted finding was re-verified against the code before this edit. Fixes folded in:

1. **BLOCKER — Task 9 left 4 test files red** (`test_eval_agent_runner.py` imports the deleted `select_queries`; `test_run_full_layer2.py` passes `--subset` in all four tests; `test_eval_agent_schema.py` asserts `q.subsets`; `test_eval_agent_queries.py` builder passed `subsets=`): all four now in Task 9's file list with line numbers, and Step 4 adds a `git grep` sweep + Step 5 runs the full eval+defend+layer2 slice.
2. **BLOCKER — `eval/defend_agent_run.py:194` would crash at runtime** once `subsets` is deleted (`extra="forbid"`): fixed twice — `"defend"` added to the `set` literal in Task 1, and the builder conversion added to Task 9. Exactly the cross-item defect shape CLAUDE.md warns about; caught by review, not by any per-item test.
3. **MAJOR — `args.note` AttributeError in Task 7** (`score_agent_run` has no `--note`): replaced with `{"queries_file": args.queries_file}`.
4. **MAJOR — Task 8 judge test used a nonexistent `fake_transcript` fixture:** rewritten against `tests/test_eval_agent_judge.py`'s own fixture pattern.
5. **MAJOR — spec's compare-side promises had no task:** control-linkage banner, headline arrow directions, and the accurate-population arrow guard are now Task 8 Step 3.
6. **MAJOR — judge `chunk_relevance` was asked for but never parsed/stored:** now stored in judge.json + aggregated as `chunk_relevance_mean`.
7. **MAJOR — TREND_KEYS name collisions:** summary `"errors"` is the crash count (kept as `"n"`-adjacent context), the tool-error count trends as `tool_error_n`; `"key_fact_rate"` corrected to the real key `"key_fact_rate_mean"`; index entries now carry cost per the spec's archive schema.
8. **MINOR — re-score double-append:** `append_run` is now idempotent per `run_dir` (test added).

No money-risk findings; the "Tasks 1–9 are free" claim was verified and holds.
