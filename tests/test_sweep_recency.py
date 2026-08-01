"""Tests for the Phase D three-metric recency sweep (spec S21 layer 3).

Two things are worth proving here and neither is arithmetic:

1. **The replay is faithful to the pipeline.** The sweep retrieves each
   query ONCE and then re-applies the recency boost offline at every
   candidate weight, because nothing upstream of the boost depends on
   the weight. That makes a 13-weight sweep 13x cheaper — and it means
   the sweep now contains a second copy of the pipeline's tail, which
   is exactly the kind of thing that drifts silently. The tests below
   pin it against the real `apply_recency_boost` and against the real
   skip rules.

2. **A missing query file degrades, it does not crash.** Two of the
   three sets are authored by a separate session and may not exist when
   the sweep runs.
"""
from __future__ import annotations

import pytest

from eval import run_eval
from eval.chronological import newest_first_rate
from eval.schema import EvalQuery
from eval.sweep_recency import (
    POOL_TOP_K,
    Trace,
    _transitions,
    boost_coverage,
    ground_truth_years,
    capture_traces,
    load_order_queries,
    measure_order,
    replay,
    strip_years,
    sweep,
    year_stripped_proxy,
)
from retrieval.query_year import parse_query_years
from retrieval.pipeline import RetrievalResult
from retrieval.types import RetrievedChunk


def _chunk(fy: int, *, score: float) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=f"jlbc-baseline-fy{fy}-adc-0001",
        doc_id=f"jlbc-baseline-fy{fy}-adc",
        text="inmate per diem",
        score=score,
        section_path=[],
        page=1,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=["agency:adc"],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=fy,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=10,
        publisher="jlbc",
    )


def _query(qid: str, text: str, chunk_id: str, fy: int) -> EvalQuery:
    return EvalQuery.model_validate(
        {
            "id": qid,
            "query": text,
            "type": "lookup",
            "expected_chunks": [
                {
                    "chunk_id": chunk_id,
                    "dimensions": {
                        "publisher": "jlbc",
                        "doc_type": "baseline-per-agency",
                        "fiscal_year": fy,
                        "agency": "agency:adc",
                    },
                }
            ],
        }
    )


# The reranker likes the OLDEST edition best — the S21 failure shape.
_POOL = [_chunk(fy, score=5.0 - 0.1 * (fy - 2008)) for fy in range(2008, 2028)]


def _trace(qid="q-1", query="Department of Corrections", *, boost_applies=True):
    return Trace(
        query_id=qid,
        query=query,
        pool=list(_POOL),
        inferred_fiscal_years=[] if boost_applies else [2014],
        boost_applies=boost_applies,
        latency_ms=100,
        error=None,
    )


# ---------------------------------------------------------------------------
# Replay fidelity
# ---------------------------------------------------------------------------


def test_replay_at_zero_returns_the_pool_untouched():
    """Weight 0.0 must be a genuine no-op, including the ORDER of equally
    scored chunks — otherwise the sweep's own baseline row would differ
    from what production does today and every delta would be measured
    against fiction."""
    result = replay(_trace(), weight=0.0, top_k=20)

    assert [c.chunk_id for c in result.chunks] == [c.chunk_id for c in _POOL]
    assert result.top_score == _POOL[0].score


def test_replay_reorders_newest_first_once_the_weight_bites():
    result = replay(_trace(), weight=1.0, top_k=20)

    years = [c.fiscal_year for c in result.chunks]
    assert years == sorted(years, reverse=True)


def test_replay_matches_the_real_boost_helper_exactly():
    """The load-bearing fidelity check: the sweep must not develop its own
    dialect of the boost. Compares against retrieval/recency.py itself."""
    from retrieval.recency import anchor_fiscal_year, apply_recency_boost

    expected = apply_recency_boost(
        _POOL, anchor_fy=anchor_fiscal_year(_POOL), weight=0.3
    )

    result = replay(_trace(), weight=0.3, top_k=len(_POOL))

    assert [c.chunk_id for c in result.chunks] == [c.chunk_id for c in expected]
    assert [c.score for c in result.chunks] == [c.score for c in expected]


def test_replay_skips_the_boost_when_the_query_named_a_year():
    """S21: layer 1 already hard-filtered the set, so layer 3 is skipped.
    A replay that boosted anyway would show the explicit-year set moving
    across the sweep and be read as a broken skip rule in the pipeline."""
    result = replay(_trace(boost_applies=False), weight=5.0, top_k=20)

    assert [c.chunk_id for c in result.chunks] == [c.chunk_id for c in _POOL]


def test_replay_trims_after_boosting_not_before():
    """The whole point of boosting the full pool: at weight 0 the FY2027
    edition sits at rank 20 and is invisible to a top-5 view; the boost
    has to be able to lift it INTO that view."""
    boosted = replay(_trace(), weight=1.0, top_k=5)

    assert boosted.chunks[0].fiscal_year == 2027
    assert len(boosted.chunks) == 5


def test_replay_reports_the_boosted_top_score():
    """top_score is what the refusal threshold is compared against, so a
    replay that returned the unboosted score would hide the interaction
    the sweep exists to surface."""
    zero = replay(_trace(), weight=0.0, top_k=20).top_score
    boosted = replay(_trace(), weight=0.5, top_k=20).top_score

    assert boosted != zero


def test_replay_of_a_failed_capture_stays_a_failure():
    """A query that crashed during capture has no pool. It must keep
    reading as a failure at every weight rather than quietly becoming an
    empty, confident result."""
    broken = Trace(
        query_id="q-x",
        query="bad",
        pool=[],
        inferred_fiscal_years=[],
        boost_applies=True,
        latency_ms=0,
        error="ValueError: boom",
    )

    result = replay(broken, weight=0.4, top_k=20)

    assert result.chunks == []
    assert result.top_score < -1e8


# ---------------------------------------------------------------------------
# Capture
# ---------------------------------------------------------------------------


def test_capture_requests_the_whole_fused_pool():
    """If capture asked for the eval's usual top_k the reranker's tail
    would already be gone and no weight could rescue a chunk from it —
    the sweep would under-report what the boost can do."""
    seen: list[int] = []

    def fake_retrieve(req, **kwargs):
        seen.append(req.top_k)
        return RetrievalResult(chunks=list(_POOL), top_score=_POOL[0].score)

    import eval.sweep_recency as mod

    original = mod.run_eval.retrieve
    mod.run_eval.retrieve = fake_retrieve
    try:
        capture_traces([("q-1", "Department of Corrections")])
    finally:
        mod.run_eval.retrieve = original

    assert seen == [POOL_TOP_K]


def test_capture_marks_a_year_named_query_as_boost_exempt():
    def fake_retrieve(req, **kwargs):
        return RetrievalResult(
            chunks=list(_POOL),
            top_score=_POOL[0].score,
            inferred_fiscal_years=[2014],
        )

    import eval.sweep_recency as mod

    original = mod.run_eval.retrieve
    mod.run_eval.retrieve = fake_retrieve
    try:
        traces = capture_traces([("h-1", "fy2014 ADC per diem")])
    finally:
        mod.run_eval.retrieve = original

    assert traces[0].boost_applies is False


def test_capture_records_a_crash_instead_of_aborting_the_sweep():
    """STATUS.md #47: one apostrophe used to crash the BM25 parser. A
    single bad query must not take the whole sweep down before a row is
    printed."""

    def fake_retrieve(req, **kwargs):
        raise ValueError("boom")

    import eval.sweep_recency as mod

    original = mod.run_eval.retrieve
    mod.run_eval.retrieve = fake_retrieve
    try:
        traces = capture_traces([("q-1", "it's broken")])
    finally:
        mod.run_eval.retrieve = original

    assert traces[0].error is not None
    assert traces[0].pool == []


# ---------------------------------------------------------------------------
# The chronological measurement over traces
# ---------------------------------------------------------------------------


def test_measure_order_scores_the_replayed_list_at_that_weight():
    at_zero = measure_order([_trace()], weight=0.0, top_k=10)
    at_one = measure_order([_trace()], weight=1.0, top_k=10)

    # The fake reranker prefers the oldest, so weight 0 is exactly backwards.
    assert at_zero[0].newest_first_rate == 0.0
    assert at_one[0].newest_first_rate == 1.0


def test_measure_order_uses_the_same_helper_the_metric_module_exposes():
    reports = measure_order([_trace()], weight=0.25, top_k=10)
    assert reports[0].newest_first_rate == newest_first_rate(reports[0].fiscal_years)


# ---------------------------------------------------------------------------
# Loading the order-query file (authored elsewhere, schema not ours)
# ---------------------------------------------------------------------------


def test_a_missing_order_file_is_skipped_not_fatal(tmp_path):
    """The recency query set is authored by a separate session. Absence is
    an expected state, not an error."""
    queries, note = load_order_queries(str(tmp_path / "nope.yaml"))

    assert queries == []
    assert "not found" in note.lower()


def test_an_order_file_of_bare_strings_is_accepted(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text("- Department of Corrections\n- AHCCCS\n", encoding="utf-8")

    queries, _ = load_order_queries(str(path))

    assert [q for _, q in queries] == ["Department of Corrections", "AHCCCS"]


def test_an_order_file_in_the_standard_eval_shape_is_accepted(tmp_path):
    """Most likely shape: the companion reuses eval/queries.yaml's schema."""
    path = tmp_path / "q.yaml"
    path.write_text(
        "- id: r-001\n"
        "  query: Department of Corrections\n"
        "  type: lookup\n"
        "  expected_chunks: []\n",
        encoding="utf-8",
    )

    queries, _ = load_order_queries(str(path))

    assert queries == [("r-001", "Department of Corrections")]


def test_an_order_file_wrapped_in_a_top_level_key_is_accepted(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text("queries:\n  - query: AHCCCS\n", encoding="utf-8")

    queries, _ = load_order_queries(str(path))

    assert [q for _, q in queries] == ["AHCCCS"]


def test_an_empty_placeholder_file_is_skipped_not_fatal(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text("# still to be authored\n[]\n", encoding="utf-8")

    queries, note = load_order_queries(str(path))

    assert queries == []
    assert "empty" in note.lower()


def test_ids_are_synthesised_when_the_file_does_not_carry_them(tmp_path):
    path = tmp_path / "q.yaml"
    path.write_text("- AHCCCS\n- ADOA\n", encoding="utf-8")

    queries, _ = load_order_queries(str(path))

    assert len({qid for qid, _ in queries}) == 2


# ---------------------------------------------------------------------------
# The sweep itself
# ---------------------------------------------------------------------------


@pytest.fixture()
def stub_retrieve(monkeypatch):
    """Retrieval that returns the twenty-edition pool, honouring a named
    year the way the real pipeline's layer-1 filter does."""

    def fake_retrieve(req, **kwargs):
        from retrieval.query_year import fiscal_year_filter, parse_query_years

        named = parse_query_years(req.query)
        allowed = fiscal_year_filter(named)
        rows = [c for c in _POOL if not allowed or c.fiscal_year in allowed]
        rows = rows[: req.top_k]
        return RetrievalResult(
            chunks=rows,
            top_score=rows[0].score if rows else -1e9,
            reranker_scores=[c.score for c in rows],
            inferred_fiscal_years=named,
        )

    monkeypatch.setattr(run_eval, "retrieve", fake_retrieve)


def test_the_sweep_reports_all_three_metrics_at_every_weight(stub_retrieve):
    rows = sweep(
        current=[_query("c-1", "ADC per diem", "jlbc-baseline-fy2027-adc-0001", 2027)],
        historical=[
            _query("h-1", "fy2014 ADC per diem", "jlbc-baseline-fy2014-adc-0001", 2014)
        ],
        order_queries=[("r-1", "Department of Corrections")],
        weights=[0.0, 1.0],
    )

    assert [r["weight"] for r in rows] == [0.0, 1.0]
    for row in rows:
        assert row["current_recall_at_15"] is not None
        assert row["historical_recall_at_15"] is not None
        assert row["order_rate"] is not None


def test_the_sweep_shows_the_boost_fixing_chronological_order(stub_retrieve):
    rows = sweep(
        current=[],
        historical=[],
        order_queries=[("r-1", "Department of Corrections")],
        weights=[0.0, 1.0],
    )

    assert rows[0]["order_rate"] == 0.0
    assert rows[1]["order_rate"] == 1.0


def test_the_sweep_holds_the_explicit_year_set_invariant(stub_retrieve):
    """Layer 1 filtered these, so layer 3 never runs on them. Movement in
    this column is a broken skip rule, not a tuning result."""
    rows = sweep(
        current=[],
        historical=[
            _query("h-1", "fy2014 ADC per diem", "jlbc-baseline-fy2014-adc-0001", 2014)
        ],
        order_queries=[],
        weights=[0.0, 0.5, 1.0],
    )

    assert {r["historical_recall_at_15"] for r in rows} == {1.0}
    assert all(r["historical_invariant"] for r in rows)


def test_a_missing_set_leaves_its_columns_blank_rather_than_zero(stub_retrieve):
    """None means 'not measured'. A 0.0 would read as a total failure of a
    set that was never run."""
    rows = sweep(current=[], historical=[], order_queries=[], weights=[0.0])

    assert rows[0]["current_recall_at_15"] is None
    assert rows[0]["order_rate"] is None


def test_the_sweep_names_which_queries_regressed_at_each_weight(stub_retrieve):
    """The report has to say what the trade-off COSTS, not just that the
    average moved. Weight 1.0 reorders the pool newest-first, which pushes
    a query whose ground truth is an old edition out of the top 15."""
    old_target = _query(
        "c-old", "ADC per diem history", "jlbc-baseline-fy2008-adc-0001", 2008
    )

    rows = sweep(
        current=[old_target], historical=[], order_queries=[], weights=[0.0, 1.0]
    )

    assert rows[0]["current_regressions"] == []
    assert "c-old" in rows[1]["current_regressions"]


def test_the_sweep_restores_the_module_weight_afterwards(stub_retrieve):
    from retrieval import recency

    before = recency.RECENCY_BOOST_PER_YEAR
    sweep(
        current=[],
        historical=[],
        order_queries=[("r-1", "AHCCCS")],
        weights=[0.0, 1.0],
    )

    assert recency.RECENCY_BOOST_PER_YEAR == before


# ---------------------------------------------------------------------------
# Coverage warning + the year-stripped proxy
# ---------------------------------------------------------------------------


def test_coverage_counts_only_queries_that_can_move():
    """A year-named query is hard-filtered by layer 1, and a refusal query
    has no chunk to recall. Neither can register a recall change at any
    weight, so neither counts as coverage."""
    year_named = _query("h-1", "fy2014 ADC per diem", "jlbc-baseline-fy2014-adc-0001", 2014)
    year_free = _query("n-1", "ADC per diem", "jlbc-baseline-fy2027-adc-0001", 2027)
    refusal = EvalQuery.model_validate(
        {"id": "r-1", "query": "should Arizona raise taxes", "type": "refusal",
         "expected_chunks": [], "expected_refusal": True}
    )

    assert boost_coverage([year_named, year_free, refusal]) == (1, 3)


def test_the_real_eval_set_exercises_the_boost():
    """Pinned as a fact about the repo, not an aspiration — and REVERSED
    on 2026-08-01.

    It used to assert the opposite: 32 of 34 queries named a fiscal year
    and the other 2 were refusals, so the set could not detect ANY recall
    cost from the recency boost, and the sweep's flat recall column was
    proof of nothing. The n-* block (13 no-year entries with FY2022-2024
    ground truth) fixed that, which is what the old test's failure message
    told the next person to do.

    The guard now runs the other way: coverage must not fall back to zero.
    Losing it is silent — the sweep still prints a recall column, it just
    stops meaning anything.
    """
    queries = run_eval.load_queries("eval/queries.yaml")
    exercising, total = boost_coverage(queries)

    assert total == 47
    assert exercising == 13, (
        "eval/queries.yaml no longer has 13 no-year entries with ground "
        "truth. If entries were added, raise this number. If a year crept "
        "into an n-* question, that entry has silently stopped measuring "
        "the recency boost — fix the query, not this test."
    )


@pytest.mark.parametrize(
    "original",
    [
        "fy2014 ADC private prison per diem",
        "FY 2019 DES funding",
        "What was the 2013 appropriation for AHCCCS?",
        "fy26 baseline for DCS",
        "spending in '19 for parks",
    ],
)
def test_strip_years_removes_exactly_what_the_filter_would_have_acted_on(original):
    stripped = strip_years(original)

    assert parse_query_years(original)
    assert parse_query_years(stripped) == []
    assert stripped.strip()


def test_strip_years_leaves_a_year_free_query_alone():
    assert strip_years("AHCCCS provider rate increase") == (
        "AHCCCS provider rate increase"
    )


def test_strip_years_does_not_eat_a_bill_number():
    """HB 2019 is a bill, not a fiscal year — the filter knows that, and
    the stripper has to agree or the proxy would mangle the question."""
    assert "2019" in strip_years("HB 2019 fiscal impact")


def test_the_proxy_keeps_the_original_ground_truth():
    """That is the whole point: a question with no year whose correct
    answer lives in a specific old edition."""
    original = _query(
        "h-1", "fy2014 ADC per diem", "jlbc-baseline-fy2014-adc-0001", 2014
    )

    proxy = year_stripped_proxy([original])

    assert len(proxy) == 1
    assert proxy[0].query == "ADC per diem"
    assert proxy[0].expected_chunks[0].chunk_id == "jlbc-baseline-fy2014-adc-0001"
    assert proxy[0].id == "h-1"


def test_the_proxy_drops_queries_it_cannot_score():
    refusal = EvalQuery.model_validate(
        {"id": "r-1", "query": "fy2019 should Arizona raise taxes", "type": "refusal",
         "expected_chunks": [], "expected_refusal": True}
    )
    year_free = _query("n-1", "ADC per diem", "jlbc-baseline-fy2027-adc-0001", 2027)

    assert year_stripped_proxy([refusal, year_free]) == []


def test_the_proxy_column_moves_when_the_recall_column_cannot(stub_retrieve):
    """The reason the proxy exists. The original query names FY2014 so
    layer 1 filters it and no weight touches it; the stripped twin has
    the same old ground truth and no filter, so the boost buries it."""
    # FY2010, not FY2014: a newest-first reordering of the twenty-edition
    # pool puts FY2014 at rank 14, still inside the top 15. The point of
    # the test is a chunk the boost pushes OUT of the window.
    original = _query(
        "h-1", "fy2010 ADC per diem", "jlbc-baseline-fy2010-adc-0001", 2010
    )

    rows = sweep(
        current=[original],
        historical=[],
        order_queries=[],
        proxy=year_stripped_proxy([original]),
        weights=[0.0, 1.0],
    )

    # The year-named original is immune at every weight...
    assert rows[0]["current_recall_at_15"] == rows[1]["current_recall_at_15"]
    # ...while its year-stripped twin is not.
    assert rows[1]["proxy_recall_at_15"] < rows[0]["proxy_recall_at_15"]
    assert "h-1" in rows[1]["proxy_regressions"]


def test_the_eval_set_has_pre_2025_ground_truth():
    """Pinned because it is the confound that decides how the proxy column
    is read — and REVERSED on 2026-08-01.

    It used to assert `min(years) >= 2025`: every expected chunk in
    eval/queries.yaml was FY2025-2027 because the set predated the S20
    backfill, so a recency boost HELPED every target and neither the
    recall column nor a proxy built from it could measure harm to an old
    one. The n-* block added FY2022/2023/2024 targets, so the set can now
    lose recall when a ranking change buries old material.

    The guard runs the other way now: if the old ground truth disappears,
    the 'cannot measure harm' caveat comes BACK and the proxy column has
    to be re-read as optimistic again.
    """
    years = ground_truth_years(run_eval.load_queries("eval/queries.yaml"))

    assert min(years) < 2025, (
        "eval/queries.yaml has lost its pre-FY2025 ground truth — nothing "
        "in the repo can measure what a ranking change costs an old target "
        "again. Restore it before trusting any 'no regression' claim."
    )
    # Not just one token old entry: enough spread that a single re-pointed
    # chunk_id cannot quietly take the coverage back down to nothing.
    assert len([y for y in years if y < 2025]) >= 3


def test_every_no_year_entry_really_names_no_year():
    """The n-* block's load-bearing property, and the one that breaks
    SILENTLY.

    An n-* question that acquires a fiscal year (an edit adds "in FY 2023"
    for clarity, say) is hard-filtered by S21 layer 1, so the recency boost
    never runs for it. Nothing goes red: the query still retrieves, still
    scores, still reports a recall number. It has just stopped measuring
    the thing it exists to measure. Checked here rather than trusted to a
    reviewer's eye.
    """
    no_year = [
        q for q in run_eval.load_queries("eval/queries.yaml")
        if q.id.startswith("n-")
    ]
    assert no_year, "the n-* block has disappeared from eval/queries.yaml"

    offenders = {q.id: parse_query_years(q.query) for q in no_year
                 if parse_query_years(q.query)}
    assert not offenders, (
        f"n-* queries naming a fiscal year: {offenders}. Layer 1 filters "
        "these, so they no longer exercise the recency boost."
    )

    for q in no_year:
        assert q.expected_chunks, f"{q.id} has no ground truth to recall"
        for expected in q.expected_chunks:
            # anchor_text is the only handle left for re-binding a stale
            # chunk_id by hand (eval/refresh_chunk_ids.py was deleted with
            # the Postgres tooling and has no replacement).
            assert expected.anchor_text, f"{q.id}/{expected.chunk_id}"


def test_the_tighter_cutoff_catches_a_demotion_the_gate_cutoff_misses():
    """recall@15 was flat across the entire real sweep while recall@5 swung
    24 points (58.6%-82.8%). A report that judged regressions only at the
    @15 gate cutoff would have called every weight free."""
    baseline = {"q-1": 3}
    after = {"q-1": 12}

    assert _transitions(baseline, after, k=15) == ([], [])
    assert _transitions(baseline, after, k=5) == (["q-1"], [])


def test_a_chunk_that_falls_out_of_the_set_entirely_counts_at_both_cutoffs():
    assert _transitions({"q-1": 3}, {"q-1": None}, k=15) == (["q-1"], [])
    assert _transitions({"q-1": 3}, {"q-1": None}, k=5) == (["q-1"], [])


def test_both_regression_cutoffs_are_reported_on_every_row(stub_retrieve):
    rows = sweep(
        current=[_query("c-1", "ADC", "jlbc-baseline-fy2027-adc-0001", 2027)],
        historical=[],
        order_queries=[],
        weights=[0.0, 1.0],
    )

    for row in rows:
        assert "current_regressions_at_5" in row
        assert "proxy_regressions_at_5" in row


def test_the_sweep_restores_the_retrieve_seam_afterwards(stub_retrieve):
    """The sweep installs a replay function over `run_eval.retrieve` so the
    real scoring path runs unchanged. Leaking that would make anything
    later in the same process score against a frozen cache."""
    installed = run_eval.retrieve

    sweep(
        current=[_query("c-1", "ADC", "jlbc-baseline-fy2027-adc-0001", 2027)],
        historical=[],
        order_queries=[],
        weights=[0.0],
    )

    assert run_eval.retrieve is installed


# ---------------------------------------------------------------------------
# The default weight grid
# ---------------------------------------------------------------------------


def test_the_default_grid_reaches_the_range_where_order_actually_arrives():
    """calibrate_recency's ceiling is spread/5. Measured 2026-08-01 on a
    spread of ~5.5, the chronological-order rate does not reach 90% until
    weight 4.0 — five times that ceiling. A grid that stopped there would
    report 'no weight qualifies' without ever testing the answer."""
    from eval.calibrate_recency import weights_from_spread
    from eval.sweep_recency import order_weight_grid

    assert weights_from_spread(5.5)[-1] < 4.0
    assert order_weight_grid(5.5)[-1] >= 4.0


def test_the_default_grid_starts_at_zero_and_ascends():
    from eval.sweep_recency import order_weight_grid

    grid = order_weight_grid(5.5)

    assert grid[0] == 0.0
    assert grid == sorted(grid)


def test_a_degenerate_spread_still_yields_the_zero_weight():
    from eval.sweep_recency import order_weight_grid

    assert order_weight_grid(0.0) == [0.0]


def test_comparison_queries_are_kept_out_of_the_proxy():
    """Their years are grammar, not a filter hint: stripping 'between the
    FY 2026 and FY 2027 Baselines' leaves 'between the and Baselines',
    which is not a question anyone would ask."""
    comparison = EvalQuery.model_validate(
        {
            "id": "c-1",
            "query": "How did DES funding differ between FY 2026 and FY 2027?",
            "type": "comparison",
            "expected_chunks": [
                {
                    "chunk_id": "jlbc-baseline-fy2026-des-0001",
                    "dimensions": {
                        "publisher": "jlbc",
                        "doc_type": "baseline-per-agency",
                        "fiscal_year": 2026,
                    },
                }
            ],
        }
    )

    assert year_stripped_proxy([comparison]) == []
