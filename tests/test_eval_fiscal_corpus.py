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


def test_the_query_set_is_honestly_marked_as_unreviewed():
    """The file must not look more finished than it is.

    It originally said "GROUND TRUTH NOT YET FILLED IN" and every entry
    carried an empty `ground_truth`. Ground truth WAS filled in on
    2026-08-01 (merge `fe2aa94`) — but by an agent reading top-10
    passages, not by anyone who writes fiscal notes, so the file now
    carries a DRAFT / PENDING HUMAN REVIEW banner instead.

    This guard tracks that banner. The property it protects is unchanged
    and is the reason it exists: a number produced from this set must not
    be quoted as a validated bar while the picks are still unreviewed.
    Delete this test when a fiscal-note coordinator has adjudicated the
    set — not before, and not to make it green.
    """
    text = QUERIES.read_text(encoding="utf-8")
    assert "PENDING HUMAN REVIEW" in text.upper()
