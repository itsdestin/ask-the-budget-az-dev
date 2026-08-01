"""harness/tools.py — the five in-process tools (Plan 4 Task 3).

These tests pin the CONTRACT the model sees, because that contract used
to live in four TypeScript files behind an MCP transport and is now a
Python module. Three things are load-bearing here and each has a
history:

1. **The first-call cap is per-conversation.** The old TS version used a
   module-level boolean because there was one MCP process per session.
   There is now ONE process for the whole office, so a module-level flag
   would mean analyst B's first question is uncapped because analyst A
   already asked one. `test_two_executors_are_independent` is the
   regression test for that specific bug.
2. **One refusal threshold.** Three contradictory numbers used to reach
   the model (0.30 in the TS tool description, 0.65 in stale comments,
   1.9 in the system prompt). `harness.constants.REFUSAL_THRESHOLD` is
   the single source and the tests grep every description for the stale
   values.
3. **Invariant 7 — no filesystem access on the model-callable surface.**
   Guarded structurally (schema parameter names, the module's import
   graph) rather than by convention.

No ONNX models and no real corpus: `retrieve` is monkeypatched at
`harness.tools.retrieve`, and cite validation runs against a LanceDB
store in tmp_path injected through the `store=` seam. The suite must
pass on a machine that has never seen the corpus.
"""
from __future__ import annotations

import ast
import json
import sys
import uuid
from pathlib import Path
from types import ModuleType

import pytest

from harness.constants import (
    FIRST_CALL_TOP_K_CAP,
    INTENT_TOP_K,
    REFUSAL_THRESHOLD,
    TIER_BUDGETS,
)
from harness.tools import TOOLS, ToolExecutor
from retrieval import RetrievalResult
from retrieval.types import RetrievedChunk
from store.chunk_store import ChunkStore

DIM = 8

TOOLS_SOURCE_PATH = Path(__file__).resolve().parent.parent / "harness" / "tools.py"


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _vec(seed: int, dim: int = DIM) -> list[float]:
    v = [0.0] * dim
    v[seed % dim] = 1.0
    return v


def _row(chunk_id: str, text: str, *, seed: int = 0, **over) -> dict:
    """A complete chunk row for the LanceDB schema (mirrors the `_row`
    helper in tests/test_citations_module.py)."""
    row = dict(
        chunk_id=chunk_id,
        doc_id="jlbc-baseline-fy2027-axs",
        text=text,
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=47,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor='{"page": 47}',
        agency_canonical_ids=["agency:axs"],
        fund_canonical_id="fund:ahcccs",
        fund_mentions=["fund:ahcccs"],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=True,
        table_html=None,
        token_count=120,
        publisher="jlbc",
        vector=_vec(seed),
    )
    row.update(over)
    return row


def _chunk(**over) -> RetrievedChunk:
    base = dict(
        chunk_id="jlbc-baseline-fy2027-axs::12",
        doc_id="jlbc-baseline-fy2027-axs",
        text="provider rate increases of $58.1 million from the General Fund",
        score=4.2,  # raw cross-encoder logit — the real scale after Plan 1
        section_path=["AHCCCS", "Operating Lump Sum"],
        page=47,
        bbox=[10.0, 20.0, 100.0, 40.0],
        source_anchor=None,
        agency_canonical_ids=["agency:axs"],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=12,
        publisher="jlbc",
    )
    base.update(over)
    return RetrievedChunk(**base)


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    """Every test gets a throwaway JLBC_DATA_DIR. documents.json lookups
    resolve under it, so nothing here can read (or write) a real share."""
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "data"))
    import harness.tools as tools_module

    tools_module.reset_document_title_cache()
    yield
    tools_module.reset_document_title_cache()


@pytest.fixture()
def store(tmp_path):
    """Two-corpus tmp store. Each table's chunk text differs so a test can
    prove which table a read actually went to."""
    s = ChunkStore(root=tmp_path / "lance", dim=DIM)
    s.upsert_chunks(
        "budget_chunks",
        [
            _row(
                "jlbc-baseline-fy2027-axs::12",
                "AHCCCS operating lump sum is $2,431,900 in FY2027.",
            ),
            _row(
                "jlbc-baseline-fy2027-adc::3",
                "ADC operating lump sum is $1,200,000 in FY2027.",
                seed=1,
                doc_id="jlbc-baseline-fy2027-adc",
                agency_canonical_ids=["agency:adc"],
                fund_canonical_id=None,
                doc_type="approps-per-agency",
            ),
        ],
    )
    s.upsert_chunks(
        "fiscal_note_chunks",
        [
            _row(
                "hb2001-fn::1",
                "HB 2001 would cost the General Fund $500,000 annually.",
                seed=2,
                doc_id="hb2001-fn",
                doc_type="fiscal-note",
                publisher="jlbc",
            )
        ],
    )
    return s


def _sidecar(tmp_path, records: dict) -> None:
    """Write a documents.json under the tmp JLBC_DATA_DIR."""
    root = tmp_path / "data"
    root.mkdir(parents=True, exist_ok=True)
    (root / "documents.json").write_text(json.dumps(records), encoding="utf-8")


def _fake_retrieve(monkeypatch, chunks=None, *, raises=None, inferred_fiscal_years=()):
    """Monkeypatch harness.tools.retrieve; return the list of requests it saw."""
    seen: list = []

    def fake(req, **kwargs):
        seen.append(req)
        if raises is not None:
            raise raises
        rows = _chunk() if chunks is None else chunks
        rows = [rows] if isinstance(rows, RetrievedChunk) else list(rows)
        return RetrievalResult(
            chunks=rows,
            top_score=rows[0].score if rows else -1e9,
            reranker_scores=[c.score for c in rows],
            bm25_count=len(rows),
            dense_count=len(rows),
            fused_count=len(rows),
            inferred_fiscal_years=list(inferred_fiscal_years),
        )

    monkeypatch.setattr("harness.tools.retrieve", fake)
    return seen


def _run(executor, name, args) -> dict:
    """execute() returns a JSON STRING (it goes straight into a tool
    message); every test parses it, so assert that here once."""
    out = executor.execute(name, args)
    assert isinstance(out, str)
    return json.loads(out)


def _descriptions() -> list[str]:
    """Every description string in the registry — tool-level AND nested
    parameter-level. A stale threshold hiding in a parameter description
    reaches the model just as surely as one in the tool description."""
    out: list[str] = []

    def walk(node):
        if isinstance(node, dict):
            for key, value in node.items():
                if key == "description" and isinstance(value, str):
                    out.append(value)
                else:
                    walk(value)
        elif isinstance(node, (list, tuple)):
            for item in node:
                walk(item)

    walk(list(TOOLS))
    return out


# ---------------------------------------------------------------------------
# Registry shape
# ---------------------------------------------------------------------------


def test_registry_exposes_the_five_tools_in_openai_function_form():
    names = [t["function"]["name"] for t in TOOLS]
    assert names == [
        "retrieve",
        "cite",
        "cite_batch",
        "list_filter_values",
        "create_document",
    ]
    for tool in TOOLS:
        assert tool["type"] == "function"
        fn = tool["function"]
        assert fn["description"].strip()
        assert fn["parameters"]["type"] == "object"
        # additionalProperties:false is the JSON-Schema equivalent of the
        # old zod .strict() — a typo'd filter key must be visible, not
        # silently ignored into a zero-result search.
        assert fn["parameters"]["additionalProperties"] is False


def test_retrieve_schema_mirrors_the_locked_zod_shape():
    params = TOOLS[0]["function"]["parameters"]
    assert params["required"] == ["query"]
    props = params["properties"]
    assert props["query"]["type"] == "string"
    assert props["top_k"] == {
        **props["top_k"],
        "type": "integer",
        "minimum": 1,
        "maximum": 50,
    }
    assert props["intent"]["enum"] == ["lookup", "compare", "analyze"]
    assert props["deep_dive"]["type"] == "boolean"

    filters = props["filters"]["properties"]
    assert filters["doc_type"]["items"]["enum"] == [
        "baseline-per-agency",
        "approps-per-agency",
        "s-pdf",
        "bd-pdf",
        "bh-pdf",
        "detailed-list-pdf",
        "topic-pdf",
        "afr",
        "governors-budget",
        "budget-bill",
        "fiscal-note",
    ]
    assert filters["publisher"]["items"]["enum"] == [
        "jlbc",
        "legislature",
        "governor",
        "agao",
    ]
    for key in ("fiscal_year", "agency_canonical_id", "fund_canonical_id"):
        assert filters[key]["type"] == "array"
    assert filters["is_table"]["type"] == "boolean"


def test_retrieve_description_carries_the_injected_refusal_threshold():
    description = TOOLS[0]["function"]["description"]
    assert str(REFUSAL_THRESHOLD) in description
    # The literal, so a refactor that stops injecting the constant but leaves
    # a hardcoded number behind still fails. Updated 1.9 -> 1.04 when the
    # threshold was recalibrated for the recency boost (2026-08-01).
    assert "1.04" in description


def test_no_stale_refusal_threshold_appears_in_any_description():
    """0.30 and 0.65 are the two numbers that used to contradict the
    system prompt's 1.9. If either reappears anywhere in the tool
    surface, the model is being told two different things again."""
    for text in _descriptions():
        assert "0.30" not in text
        assert "0.65" not in text


def test_descriptions_are_provider_neutral():
    """The model reading these has never seen MCP or Claude Code. Any
    leftover harness vocabulary is a comprehension bug, not a typo."""
    banned = ("MCP", "ToolSearch", "Claude", "sidecar", "session")
    for text in _descriptions():
        for word in banned:
            assert word not in text, f"{word!r} leaked into a tool description"


def test_cite_and_batch_schemas_mirror_the_locked_cite_shape():
    cite = TOOLS[1]["function"]["parameters"]
    assert set(cite["required"]) == {"chunk_id", "confidence", "claim_span"}
    assert cite["properties"]["confidence"]["enum"] == ["verbatim", "paraphrase"]
    # 2000, not 500: the server soft-clamps to 500 and flags truncated,
    # rather than rejecting the whole citation at the boundary.
    assert cite["properties"]["claim_span"]["maxLength"] == 2000
    assert "quote" in cite["properties"]

    batch = TOOLS[2]["function"]["parameters"]
    items = batch["properties"]["citations"]
    assert items["type"] == "array"
    assert items["maxItems"] == 50
    assert set(items["items"]["required"]) == {"chunk_id", "confidence", "claim_span"}


def test_list_filter_values_and_create_document_schemas():
    lfv = TOOLS[3]["function"]["parameters"]
    assert lfv["properties"]["field"]["enum"] == [
        "agency",
        "doc_type",
        "publisher",
        "fund",
    ]
    doc = TOOLS[4]["function"]["parameters"]
    assert set(doc["properties"]) == {"title", "body_markdown", "format"}
    assert doc["properties"]["format"]["enum"] == ["docx", "md"]
    assert set(doc["required"]) == {"title", "body_markdown"}


# ---------------------------------------------------------------------------
# retrieve — intent resolution + first-call cap
# ---------------------------------------------------------------------------


def _second_call_executor(monkeypatch, tier="deep_research"):
    """An executor whose first-call cap has already been spent, so the
    next retrieve() exercises normal top_k resolution."""
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", tier)
    _run(ex, "retrieve", {"query": "warm up"})
    seen.clear()
    return ex, seen


@pytest.mark.parametrize(
    "intent,expected",
    [("lookup", 5), ("compare", 12), ("analyze", 18), (None, 15)],
)
def test_retrieve_resolves_intent_to_top_k(monkeypatch, intent, expected):
    ex, seen = _second_call_executor(monkeypatch)
    args = {"query": "AHCCCS lump sum"}
    if intent:
        args["intent"] = intent
    _run(ex, "retrieve", args)
    assert seen[0].top_k == expected
    if intent:
        assert INTENT_TOP_K[intent] == expected


def test_explicit_top_k_beats_intent(monkeypatch):
    ex, seen = _second_call_executor(monkeypatch)
    _run(ex, "retrieve", {"query": "q", "intent": "lookup", "top_k": 30})
    assert seen[0].top_k == 30


def test_first_retrieve_is_capped_and_says_so(monkeypatch):
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "deep_research")
    out = _run(ex, "retrieve", {"query": "q", "intent": "analyze"})
    assert seen[0].top_k == FIRST_CALL_TOP_K_CAP == 5
    assert out["first_call_capped"] is True


def test_second_retrieve_is_uncapped(monkeypatch):
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "deep_research")
    _run(ex, "retrieve", {"query": "q"})
    out = _run(ex, "retrieve", {"query": "q", "intent": "analyze"})
    assert seen[1].top_k == 18
    # The flag is only present when the cap actually fired — its absence
    # is how the model knows it got everything it asked for.
    assert "first_call_capped" not in out


def test_a_year_parsed_out_of_the_query_is_reported_to_the_model(monkeypatch):
    """S21 layer 1. Without this echo the model sees fifteen FY 2019
    passages and cannot tell whether that is the whole corpus or the
    effect of a filter it never asked for."""
    _fake_retrieve(monkeypatch, inferred_fiscal_years=[2019])
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "fy2019 DES funding"})
    assert out["inferred_fiscal_years"] == [2019]


def test_no_inferred_years_key_when_the_pipeline_inferred_none(monkeypatch):
    _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "DES funding"})
    assert "inferred_fiscal_years" not in out


def test_deep_dive_bypasses_the_cap_on_deep_research(monkeypatch):
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "deep_research")
    out = _run(ex, "retrieve", {"query": "q", "intent": "analyze", "deep_dive": True})
    assert seen[0].top_k == 18
    assert "first_call_capped" not in out


def test_standard_tier_ignores_deep_dive_and_explains_why(monkeypatch):
    """S16: Standard stays cheap by construction. The model must be told
    why it got 5 chunks or it will keep re-asking for a deep dive."""
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "q", "intent": "analyze", "deep_dive": True})
    assert seen[0].top_k == FIRST_CALL_TOP_K_CAP
    assert out["first_call_capped"] is True
    assert out["deep_dive_ignored"] is True
    assert "note" in out and out["note"].strip()
    assert TIER_BUDGETS["standard"]["deep_dive_allowed"] is False


def test_two_executors_are_independent(monkeypatch):
    """THE per-conversation regression test. One process now serves the
    whole office; a module-global first-call flag would mean the second
    analyst's opening question skips the sampling discipline."""
    seen = _fake_retrieve(monkeypatch)
    a = ToolExecutor("conv-a", "budget", "deep_research")
    b = ToolExecutor("conv-b", "budget", "deep_research")

    out_a1 = _run(a, "retrieve", {"query": "q", "intent": "analyze"})
    out_b1 = _run(b, "retrieve", {"query": "q", "intent": "analyze"})
    out_a2 = _run(a, "retrieve", {"query": "q", "intent": "analyze"})

    assert out_a1["first_call_capped"] is True
    assert out_b1["first_call_capped"] is True  # NOT consumed by conv-a
    assert "first_call_capped" not in out_a2
    assert [r.top_k for r in seen] == [5, 5, 18]


# ---------------------------------------------------------------------------
# retrieve — response shape
# ---------------------------------------------------------------------------


def test_retrieve_response_shape_matches_the_locked_contract(monkeypatch, tmp_path):
    _sidecar(tmp_path, {"jlbc-baseline-fy2027-axs": {"title": "JLBC FY2027 — AHCCCS"}})
    _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "AHCCCS"})

    assert set(out) >= {
        "chunks",
        "top_score",
        "retrieval_id",
        "bm25_count",
        "dense_count",
        "fused_count",
    }
    assert out["top_score"] == 4.2
    uuid.UUID(out["retrieval_id"])  # raises if it isn't a real uuid

    chunk = out["chunks"][0]
    assert set(chunk) == {
        "chunk_id",
        "doc_id",
        "doc_title",
        "publisher",
        "fiscal_year",
        "doc_type",
        "section_path",
        "page_start",
        "page_end",
        "bbox",
        "text",
        "text_length",
        "score",
    }
    assert chunk["doc_title"] == "JLBC FY2027 — AHCCCS"
    assert chunk["page_start"] == chunk["page_end"] == 47
    assert chunk["text_length"] == len(chunk["text"])


def test_doc_title_falls_back_to_a_humanized_slug(monkeypatch, tmp_path):
    """A corpus copied without documents.json still labels its chunks —
    the model reads doc_title in every result, so a blank one is visible
    in answers, not just in the UI."""
    _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "q"})
    assert out["chunks"][0]["doc_title"] == "JLBC Baseline FY 2027 Axs"


def test_retrieve_targets_the_executors_corpus(monkeypatch):
    seen = _fake_retrieve(monkeypatch)
    _run(ToolExecutor("c", "budget", "standard"), "retrieve", {"query": "q"})
    _run(ToolExecutor("c", "fiscal_notes", "standard"), "retrieve", {"query": "q"})
    assert [r.corpus for r in seen] == ["budget_chunks", "fiscal_note_chunks"]


def test_retrieve_passes_filters_through(monkeypatch):
    ex, seen = _second_call_executor(monkeypatch)
    _run(
        ex,
        "retrieve",
        {
            "query": "q",
            "filters": {
                "fiscal_year": [2027],
                "doc_type": ["baseline-per-agency"],
                "publisher": ["jlbc"],
                "agency_canonical_id": ["agency:axs"],
                "fund_canonical_id": ["fund:general"],
                "is_table": True,
            },
        },
    )
    req = seen[0]
    assert req.fiscal_year == [2027]
    assert req.doc_type == ["baseline-per-agency"]
    assert req.publisher == ["jlbc"]
    assert req.agency_canonical_id == ["agency:axs"]
    assert req.fund_canonical_id == ["fund:general"]
    assert req.is_table is True


def test_retrieve_backend_failure_is_a_tool_visible_error(monkeypatch):
    """A crash here must not kill the turn — the model needs to read the
    failure and tell the analyst the search is unavailable."""
    _fake_retrieve(monkeypatch, raises=RuntimeError("lance table missing"))
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "q"})
    assert out["ok"] is False
    assert "lance table missing" in out["error"]


def test_an_unexpected_backend_failure_is_also_logged_to_stderr(
    monkeypatch, capsys
):
    """One process serves the whole office. Without this line the only
    record of a real backend bug lives inside one analyst's chat
    transcript, where no admin will ever grep it."""
    _fake_retrieve(monkeypatch, raises=RuntimeError("lance table missing"))
    ex = ToolExecutor("conv-99", "budget", "standard")
    _run(ex, "retrieve", {"query": "q"})
    err = capsys.readouterr().err
    assert "retrieve" in err
    assert "lance table missing" in err
    # The conversation id is what ties the log line back to a transcript.
    assert "conv-99" in err


def test_malformed_arguments_are_not_logged_to_stderr(capsys):
    """A model typo is normal traffic, not an incident — logging it would
    bury the real failures item 2 exists to surface."""
    ex = ToolExecutor("conv-1", "budget", "standard")
    _run(ex, "retrieve", {"query": ""})
    assert capsys.readouterr().err == ""


def test_retrieve_with_no_results_reports_the_sentinel(monkeypatch):
    _fake_retrieve(monkeypatch, chunks=[])
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "q"})
    assert out["chunks"] == []
    # NOT 0.0 — 0.0 would outrank a genuinely-bad hit on the logit scale.
    assert out["top_score"] == -1e9


# ---------------------------------------------------------------------------
# cite / cite_batch
# ---------------------------------------------------------------------------


def test_cite_success_mints_a_citation_id_and_resolves_offsets(store):
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(
        ex,
        "cite",
        {
            "chunk_id": "jlbc-baseline-fy2027-axs::12",
            "quote": "$2,431,900",
            "confidence": "verbatim",
            "claim_span": "AHCCCS gets $2.4M.",
        },
    )
    assert out["ok"] is True
    uuid.UUID(out["citation_id"])
    # The UI drives its PDF text-layer search off these; without them a
    # quote-only cite falls back to a sentinel range and shows the
    # "couldn't pinpoint" badge.
    text = "AHCCCS operating lump sum is $2,431,900 in FY2027."
    assert out["resolved_span_start"] == text.index("$2,431,900")
    assert out["resolved_span_end"] == out["resolved_span_start"] + len("$2,431,900")


def test_cite_failure_passes_the_actionable_error_through(store):
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(
        ex,
        "cite",
        {
            "chunk_id": "does-not-exist::1",
            "quote": "anything",
            "confidence": "verbatim",
            "claim_span": "claim",
        },
    )
    assert out["ok"] is False
    assert out["error"] == "unknown chunk_id"
    assert "citation_id" not in out


def test_cite_uses_the_executors_corpus(store):
    """A cite against a fiscal note must be checked against fiscal-note
    text — never against budget text that happens to share a chunk_id."""
    body = {
        "chunk_id": "hb2001-fn::1",
        "quote": "$500,000",
        "confidence": "verbatim",
        "claim_span": "HB 2001 costs $500K.",
    }
    notes = ToolExecutor("c", "fiscal_notes", "standard", store=store)
    budget = ToolExecutor("c", "budget", "standard", store=store)
    assert _run(notes, "cite", body)["ok"] is True
    assert _run(budget, "cite", body)["error"] == "unknown chunk_id"


def test_cite_batch_returns_a_parallel_array_in_input_order(store):
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(
        ex,
        "cite_batch",
        {
            "citations": [
                {
                    "chunk_id": "jlbc-baseline-fy2027-axs::12",
                    "quote": "$2,431,900",
                    "confidence": "verbatim",
                    "claim_span": "one",
                },
                {
                    "chunk_id": "nope::1",
                    "quote": "x",
                    "confidence": "verbatim",
                    "claim_span": "two",
                },
                {
                    "chunk_id": "jlbc-baseline-fy2027-adc::3",
                    "quote": "$1,200,000",
                    "confidence": "verbatim",
                    "claim_span": "three",
                },
            ]
        },
    )
    results = out["citations"]
    assert [r["ok"] for r in results] == [True, False, True]
    # One bad cite does not poison the batch — the model re-pairs results
    # with its own arguments by index.
    assert results[1]["error"] == "unknown chunk_id"
    assert len({results[0]["citation_id"], results[2]["citation_id"]}) == 2


def test_cite_batch_does_one_bulk_store_read(store, monkeypatch):
    """The load-bearing optimization: each store read is a network round
    trip on the office share (~3s), and an analyze-shaped answer carries
    15-20 cites. N reads would put a minute back into the turn."""
    calls: list[list[str]] = []
    real = store.get_by_ids

    def counting(name, chunk_ids):
        calls.append(list(chunk_ids))
        return real(name, chunk_ids)

    monkeypatch.setattr(store, "get_by_ids", counting)
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    _run(
        ex,
        "cite_batch",
        {
            "citations": [
                {
                    "chunk_id": "jlbc-baseline-fy2027-axs::12",
                    "quote": q,
                    "confidence": "verbatim",
                    "claim_span": q,
                }
                for q in ("$2,431,900", "AHCCCS operating", "FY2027")
            ]
        },
    )
    assert len(calls) == 1


def test_cite_batch_accepts_an_empty_array(store):
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    assert _run(ex, "cite_batch", {"citations": []}) == {"citations": []}


# ---------------------------------------------------------------------------
# list_filter_values
# ---------------------------------------------------------------------------


def _install_fake_catalog(monkeypatch, attr):
    """Stand in for Plan 3's chunking.agency_catalog (not merged yet)."""
    module = ModuleType("chunking.agency_catalog")
    if attr is not None:
        module.id_to_name = attr  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "chunking.agency_catalog", module)


def test_list_filter_values_counts_chunks_per_agency(store, tmp_path):
    _sidecar(tmp_path, {"jlbc-baseline-fy2027-axs": {"title": "JLBC FY2027 — AHCCCS"}})
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(ex, "list_filter_values", {"field": "agency"})
    assert out["field"] == "agency"
    ids = {v["canonical_id"]: v for v in out["values"]}
    assert ids["agency:axs"]["chunk_count"] == 1
    # The sample title is what makes an opaque slug recognizable — the
    # 2026-05-08 audit burned 10 retrieves on "agency:trs" vs "agency:tre".
    assert ids["agency:axs"]["sample_doc_title"] == "JLBC FY2027 — AHCCCS"


def test_agency_ids_resolve_to_names_when_the_catalog_is_available(
    store, monkeypatch
):
    _install_fake_catalog(
        monkeypatch, {"agency:axs": "Arizona Health Care Cost Containment System"}
    )
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(ex, "list_filter_values", {"field": "agency"})
    names = {v["canonical_id"]: v.get("name") for v in out["values"]}
    assert names["agency:axs"] == "Arizona Health Care Cost Containment System"


def test_a_callable_catalog_is_accepted_too(store, monkeypatch):
    _install_fake_catalog(monkeypatch, lambda: {"agency:adc": "Corrections"})
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(ex, "list_filter_values", {"field": "agency"})
    names = {v["canonical_id"]: v.get("name") for v in out["values"]}
    assert names["agency:adc"] == "Corrections"


@pytest.mark.parametrize(
    "attr", [None, "not-a-mapping", pytest.param(object(), id="garbage")]
)
def test_a_missing_or_malformed_catalog_degrades_to_raw_ids(store, monkeypatch, attr):
    """Plan 3 owns chunking/agency_catalog.py and is being written in
    parallel. Every failure shape — absent module, absent attribute,
    unexpected type — must degrade, never crash a live conversation."""
    _install_fake_catalog(monkeypatch, attr)
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(ex, "list_filter_values", {"field": "agency"})
    assert out["values"]  # still enumerates
    assert all("name" not in v for v in out["values"])


def test_doc_type_and_publisher_count_documents_not_chunks(store, tmp_path):
    _sidecar(
        tmp_path,
        {
            "jlbc-baseline-fy2027-axs": {"title": "Zebra — AHCCCS"},
            "jlbc-baseline-fy2027-adc": {"title": "Alpha — Corrections"},
        },
    )
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    doc_types = {
        v["canonical_id"]: v["chunk_count"]
        for v in _run(ex, "list_filter_values", {"field": "doc_type"})["values"]
    }
    assert doc_types == {"baseline-per-agency": 1, "approps-per-agency": 1}
    publishers = _run(ex, "list_filter_values", {"field": "publisher"})["values"]
    assert publishers[0] == {
        "canonical_id": "jlbc",
        "chunk_count": 2,  # two distinct doc_ids
        # Alphabetically first title among the group's documents — a
        # deterministic pick, NOT the most-populated-document rule the
        # agency dimension uses. See _values_by_document for why the two
        # dimensions differ.
        "sample_doc_title": "Alpha — Corrections",
    }


def test_list_filter_values_sorts_most_used_first(store):
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    values = _run(ex, "list_filter_values", {"field": "fund"})["values"]
    # fund_canonical_id is nullable — a NULL must never become a value
    # literally named "None".
    assert [v["canonical_id"] for v in values] == ["fund:ahcccs"]


def test_unknown_field_is_a_tool_visible_error(store):
    ex = ToolExecutor("conv-1", "budget", "standard", store=store)
    out = _run(ex, "list_filter_values", {"field": "agencies"})
    assert out["ok"] is False
    assert "agency" in out["error"]


# ---------------------------------------------------------------------------
# create_document
# ---------------------------------------------------------------------------


def test_create_document_dispatches_to_the_materializer(tmp_path):
    seen: list[tuple] = []

    def fake_materialize(title, body_markdown, fmt, *, user):
        seen.append((title, body_markdown, fmt, user))
        return "tok-123", tmp_path / "JLBC-memo.docx"

    ex = ToolExecutor(
        "conv-1", "budget", "standard", user="analyst1", materialize=fake_materialize
    )
    out = _run(
        ex,
        "create_document",
        {"title": "JLBC memo", "body_markdown": "# Heading", "format": "docx"},
    )
    assert out == {"ok": True, "download_token": "tok-123", "filename": "JLBC-memo.docx"}
    assert seen == [("JLBC memo", "# Heading", "docx", "analyst1")]


def test_create_document_defaults_to_docx(tmp_path):
    seen: list[str] = []

    def fake_materialize(title, body_markdown, fmt, *, user):
        seen.append(fmt)
        return "t", tmp_path / "x.docx"

    ex = ToolExecutor("conv-1", "budget", "standard", materialize=fake_materialize)
    _run(ex, "create_document", {"title": "T", "body_markdown": "b"})
    assert seen == ["docx"]


def test_create_document_failure_is_a_tool_visible_error(tmp_path):
    def boom(title, body_markdown, fmt, *, user):
        raise OSError("disk full")

    ex = ToolExecutor("conv-1", "budget", "standard", materialize=boom)
    out = _run(ex, "create_document", {"title": "T", "body_markdown": "b"})
    assert out["ok"] is False
    assert "disk full" in out["error"]


# ---------------------------------------------------------------------------
# Dispatch robustness — the model DOES emit malformed arguments
# ---------------------------------------------------------------------------


def test_unknown_tool_name_is_recoverable():
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "read_file", {"path": "/etc/passwd"})
    assert out["ok"] is False
    assert "read_file" in out["error"]
    # Name the tools it actually has, so the next step is a real call.
    assert "retrieve" in out["error"]


def test_arguments_arriving_as_a_json_string_are_parsed(monkeypatch):
    """OpenAI-compatible tool_calls carry `arguments` as a JSON STRING.
    Accepting it here means Task 6 can hand the assembled fragments over
    without a parse step that could throw outside the tool boundary."""
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", '{"query": "AHCCCS lump sum"}')
    assert seen[0].query == "AHCCCS lump sum"
    assert "chunks" in out


@pytest.mark.parametrize("args", ['{"query": ', "[1, 2]", None, 7, {"query": ""}])
def test_malformed_arguments_never_raise(args):
    """A crash on bad arguments loses the whole conversation. Every shape
    below must come back as a readable error the model can retry from."""
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", args)
    assert out["ok"] is False
    assert out["error"].strip()


@pytest.mark.parametrize("top_k", ["twelve", 0, 99, True, 1.5])
def test_wrong_types_inside_a_valid_object_are_reported(monkeypatch, top_k):
    _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "standard")
    out = _run(ex, "retrieve", {"query": "q", "top_k": top_k})
    assert out["ok"] is False
    assert "top_k" in out["error"]


def test_a_scalar_filter_is_wrapped_rather_than_rejected(monkeypatch):
    """Models write `"publisher": "jlbc"` for a single value constantly.
    The intent is unambiguous, so bouncing it would cost a whole step."""
    ex, seen = _second_call_executor(monkeypatch)
    _run(ex, "retrieve", {"query": "q", "filters": {"publisher": "jlbc"}})
    assert seen[0].publisher == ["jlbc"]


def test_a_stringified_fiscal_year_is_coerced_to_an_integer(monkeypatch):
    """The column is an integer, so `"2027"` builds a predicate matching
    no rows and the model reads the empty result as 'the corpus has
    nothing for FY2027'."""
    ex, seen = _second_call_executor(monkeypatch)
    _run(ex, "retrieve", {"query": "q", "filters": {"fiscal_year": "2027"}})
    assert seen[0].fiscal_year == [2027]


def test_a_non_numeric_fiscal_year_is_reported(monkeypatch):
    ex, _ = _second_call_executor(monkeypatch)
    out = _run(ex, "retrieve", {"query": "q", "filters": {"fiscal_year": ["FY27"]}})
    assert out["ok"] is False
    assert "fiscal_year" in out["error"]


def test_an_unknown_filter_key_is_reported_not_ignored(monkeypatch):
    """Silently dropping it leaves the search unfiltered while the model
    believes it was narrowed."""
    ex, _ = _second_call_executor(monkeypatch)
    out = _run(ex, "retrieve", {"query": "q", "filters": {"agency": ["axs"]}})
    assert out["ok"] is False
    assert "agency" in out["error"]


def test_an_unknown_doc_type_is_rejected_rather_than_silently_matching_nothing(
    monkeypatch,
):
    """The 2026-05-08 enum-drift bug: `baseline-agency` does not exist,
    so filtering on it returned zero chunks with no error and read as
    'the corpus doesn't cover this'."""
    ex, _ = _second_call_executor(monkeypatch)
    out = _run(
        ex, "retrieve", {"query": "q", "filters": {"doc_type": ["baseline-agency"]}}
    )
    assert out["ok"] is False
    assert "list_filter_values" in out["error"]


def test_an_unknown_tier_degrades_to_the_cheap_budget(monkeypatch):
    """settings.json accepts arbitrary tier names, so an admin adding a
    third tier must not take down every conversation — and a mis-typed
    tier must never get the expensive budget."""
    seen = _fake_retrieve(monkeypatch)
    ex = ToolExecutor("conv-1", "budget", "premium")
    out = _run(ex, "retrieve", {"query": "q", "deep_dive": True})
    assert seen[0].top_k == FIRST_CALL_TOP_K_CAP
    assert out["deep_dive_ignored"] is True


def test_unknown_corpus_fails_at_construction_not_mid_turn():
    """A bad corpus name is a wiring bug in Task 6/8, not something the
    model did — fail loudly before a conversation starts."""
    with pytest.raises(ValueError):
        ToolExecutor("conv-1", "budget_notes", "standard")


# ---------------------------------------------------------------------------
# Invariant 7 — no filesystem access on the model-callable surface
# ---------------------------------------------------------------------------


def _parameter_names(node, out: set[str]) -> None:
    """Every property name anywhere in a schema, however deeply nested.
    A top-level-only scan would miss `filters.path` or an array item's
    properties, which is exactly where a path argument would hide."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "properties" and isinstance(value, dict):
                out.update(value)
            _parameter_names(value, out)
    elif isinstance(node, (list, tuple)):
        for item in node:
            _parameter_names(item, out)


def test_no_tool_parameter_is_named_like_a_filesystem_path():
    names: set[str] = set()
    _parameter_names(list(TOOLS), names)
    assert names, "schema walk found no parameters — the guard would pass vacuously"
    for name in names:
        lowered = name.lower()
        for token in ("path", "file", "dir", "folder", "cwd"):
            assert token not in lowered, f"{name!r} looks like a filesystem argument"


def test_tools_module_imports_are_allowlisted():
    """The load-bearing structural guard. Invariant 7 is about what this
    module CAN reach: `subprocess`, `os`, `shutil`, `pathlib`, or
    anything from `ingest` would all fail here, and adding one has to be
    a conscious edit to this list rather than an unnoticed import."""
    allowed = {
        "__future__",
        "json",
        "sys",
        "threading",
        "typing",
        "uuid",
        "retrieval",
        "store",
        "harness",
        "chunking",
    }
    tree = ast.parse(TOOLS_SOURCE_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots <= allowed, f"unexpected imports: {sorted(roots - allowed)}"


def test_tools_module_never_calls_a_write_method():
    """Backstop to the import guard beside this one, which is the robust
    check. This one catches the realistic mistake — someone reaching for
    a ChunkStore writer or a direct file write while adding a tool.

    Deliberately narrow on both axes so it cannot misfire during an
    ordinary refactor. Only METHOD names are scanned (`x.write_text()`,
    never a bare local called `write_text`), and only names distinctive
    enough that they cannot plausibly mean anything else here — a
    generic verb like `remove` or `optimize` would fail on an innocent
    `list.remove(...)` and report it as an Invariant 7 violation, which
    trains people to ignore the test. An alias or a getattr still slips
    past; that is what the import allowlist is for."""
    forbidden = {
        "upsert_chunks",
        "ensure_tables",
        "build_fts_index",
        "delete_doc",
        "write_text",
        "write_bytes",
        "rmtree",
    }
    tree = ast.parse(TOOLS_SOURCE_PATH.read_text(encoding="utf-8"))
    called = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert not (called & forbidden), f"write method called: {called & forbidden}"


def test_executing_every_tool_writes_nothing_under_the_data_dir(
    store, monkeypatch, tmp_path
):
    """The behavioral half of Invariant 7: run the whole surface and
    assert the shared data folder is untouched afterwards.

    Scoped honestly — this covers the harness's OWN file access (it reads
    documents.json there and writes nothing), not the LanceDB store,
    which the fixture deliberately keeps on a separate path so that a
    Lance-internal read-side file touch can't make an invariant test
    flaky. "The executor never calls a store writer" is covered by the
    import-allowlist and write-operation guards above instead."""
    _fake_retrieve(monkeypatch)
    _sidecar(tmp_path, {"jlbc-baseline-fy2027-axs": {"title": "t"}})
    root = tmp_path / "data"
    before = {p: p.stat().st_mtime_ns for p in root.rglob("*")}

    ex = ToolExecutor(
        "conv-1",
        "budget",
        "standard",
        store=store,
        materialize=lambda *a, **k: ("tok", tmp_path / "out.docx"),
    )
    _run(ex, "retrieve", {"query": "q"})
    _run(ex, "list_filter_values", {"field": "agency"})
    _run(
        ex,
        "cite",
        {
            "chunk_id": "jlbc-baseline-fy2027-axs::12",
            "quote": "$2,431,900",
            "confidence": "verbatim",
            "claim_span": "c",
        },
    )
    _run(ex, "cite_batch", {"citations": []})
    _run(ex, "create_document", {"title": "T", "body_markdown": "b"})

    assert {p: p.stat().st_mtime_ns for p in root.rglob("*")} == before
