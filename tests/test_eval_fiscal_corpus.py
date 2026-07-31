"""The eval runner's --corpus plumbing (Plan 3, Task 13)."""
from __future__ import annotations

from pathlib import Path

import pytest
from ruamel.yaml import YAML

from eval import run_eval
from eval.schema import EvalQuery

QUERIES = Path(__file__).resolve().parent.parent / "eval" / "fiscal_note_queries.yaml"


class _Result:
    def __init__(self):
        self.chunks = []
        self.top_score = run_eval.NO_RESULTS_TOP_SCORE


def test_run_one_query_passes_the_corpus_through(monkeypatch):
    seen = {}

    def fake_retrieve(req):
        seen["corpus"] = req.corpus
        return _Result()

    monkeypatch.setattr(run_eval, "retrieve", fake_retrieve)
    run_eval.run_one_query(
        EvalQuery(id="q", type="lookup", query="anything", ground_truth={}),
        1.9, corpus="fiscal_notes",
    )
    # The flag takes the analyst-facing name; the request takes the TABLE.
    assert seen["corpus"] == "fiscal_note_chunks"


def test_the_default_corpus_is_still_budget(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        run_eval, "retrieve",
        lambda req: (seen.__setitem__("corpus", req.corpus), _Result())[1],
    )
    run_eval.run_one_query(
        EvalQuery(id="q", type="lookup", query="anything", ground_truth={}), 1.9
    )
    assert seen["corpus"] == "budget_chunks"


def test_a_fiscal_note_run_never_diffs_against_a_budget_run(tmp_path):
    """A different corpus is not a regression. Without the prefix scoping,
    the first fiscal-note run would diff itself against the budget baseline
    and report every query as newly failing."""
    (tmp_path / "2026-07-30T1200Z-abc1234.json").write_text("{}", encoding="utf-8")
    (tmp_path / "fiscal_notes-2026-07-29T1200Z-abc1234.json").write_text(
        "{}", encoding="utf-8")

    assert run_eval.find_previous_result(
        tmp_path, "fiscal_notes-2026-07-31T1200Z-abc1234.json", "fiscal_notes-"
    ).name == "fiscal_notes-2026-07-29T1200Z-abc1234.json"

    assert run_eval.find_previous_result(
        tmp_path, "2026-07-31T1200Z-abc1234.json", ""
    ).name == "2026-07-30T1200Z-abc1234.json"


def test_the_query_set_is_coordinator_triage_shaped():
    yaml = YAML(typ="safe")
    raw = yaml.load(QUERIES.read_text(encoding="utf-8"))
    assert len(raw) >= 10
    assert {q["type"] for q in raw} >= {"lookup", "refusal"}
    for q in raw:
        EvalQuery.model_validate(q)          # the same schema as queries.yaml
        assert not q["query"].strip().upper().startswith(("HB", "SB")), (
            "Bill-number lookups belong on the directory page; this set exists "
            "for topic similarity."
        )


def test_the_query_set_is_honestly_marked_as_unbaselined():
    """Ground truth needs a populated corpus. The file must say so rather
    than look finished."""
    text = QUERIES.read_text(encoding="utf-8")
    assert "GROUND TRUTH NOT YET FILLED IN" in text
    yaml = YAML(typ="safe")
    raw = yaml.load(text)
    assert all(q["ground_truth"] == {} for q in raw)
