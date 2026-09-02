"""The A8 ship gate measures the ERROR rate, so its instrument is tested
for the property that matters: a link it reports is a link that would
have been WRONG.

Every figure this script invents appears in no answer, so any link it
produces is false by construction. These tests pin that the generator is
reproducible (a gate number nobody can re-derive is not a gate), that the
profiles render the way a real answer writes them, and that the rate
responds to the linking policy rather than to how loose the matcher is.
"""
from __future__ import annotations

import json

import pytest

from citation.figures import written_significant_digits
from eval.false_link_check import (
    PROFILES,
    false_link_rate,
    invent_figures,
    pools,
    verdict_counts,
)
from retrieval.table_view import render_labelled


def test_invented_figures_are_deterministic_and_in_profile():
    a = invent_figures("4sig-billions", n=20, seed=7)
    assert a == invent_figures("4sig-billions", n=20, seed=7)
    assert all(f.scale == 1_000_000_000 for f in a)
    assert len(a) == 20


def test_a_different_seed_gives_a_different_sample():
    # Determinism must come from the seed, not from the generator being
    # constant — a generator that ignored its seed would pass the test
    # above and make every pool measure the same 20 numbers.
    assert invent_figures("4sig-billions", n=20, seed=7) != invent_figures(
        "4sig-billions", n=20, seed=8)


@pytest.mark.parametrize("profile", sorted(PROFILES))
def test_every_profile_renders_the_way_an_answer_writes_it(profile):
    # The specificity floor reads the WRITTEN digits, so an invented
    # figure whose text does not render like real answer prose would be
    # judged on digits no real figure has.
    from citation.figures import extract_figures

    for f in invent_figures(profile, n=25, seed=7):
        found = extract_figures(f.text)
        assert len(found) == 1, f"{f.text!r} is not extractable as a figure"
        assert found[0].absolute == pytest.approx(f.absolute)
        assert found[0].scale == f.scale


def test_rounded_billions_carry_fewer_written_digits_than_exact_integers():
    # The premise of the whole gate (memo §5.2): the two profiles differ in
    # distinctiveness, which is why they are measured separately.
    billions = invent_figures("4sig-billions", n=50, seed=7)
    grouped = invent_figures("exact-grouped", n=50, seed=7)
    mean_b = sum(written_significant_digits(f.text) for f in billions) / 50
    mean_g = sum(written_significant_digits(f.text) for f in grouped) / 50
    assert mean_b < mean_g


def test_false_link_rate_counts_any_link_as_false():
    figs = invent_figures("4sig-billions", n=20, seed=7)
    # Plant the exact value of ONE invented figure in a single document.
    # Relying on a random invention to collide with a hand-written number
    # would make this test a lottery (~1 in 9,000 per trial).
    planted = int(figs[0].absolute)
    pool = {"k1": f"total {planted:,} held"}
    meta = {"k1": {"doc_id": "d1"}}
    rate = false_link_rate(figs, pool, meta)
    assert 0.0 < rate < 1.0


def test_a_pool_with_no_matching_value_links_nothing():
    figs = invent_figures("exact-grouped", n=40, seed=7)
    pool = {"k1": "the fund held 12,345 dollars and 7,777 positions"}
    meta = {"k1": {"doc_id": "d1"}}
    assert false_link_rate(figs, pool, meta) == 0.0


def test_a_value_in_two_documents_is_refused_not_linked():
    # This is the behaviour the gate exists to measure: the same value
    # sitting in two documents used to be resolved by authority ranking and
    # is now refused outright (spec A2/A3). The false-link rate must fall
    # to zero for exactly that case.
    figs = invent_figures("4sig-billions", n=20, seed=7)
    planted = int(figs[0].absolute)
    text = f"total {planted:,} held"
    one_doc = false_link_rate(figs, {"k1": text}, {"k1": {"doc_id": "d1"}})
    two_docs = false_link_rate(
        figs, {"k1": text, "k2": text},
        {"k1": {"doc_id": "d1"}, "k2": {"doc_id": "d2"}})
    assert one_doc > 0.0
    assert two_docs == 0.0


def test_empty_figure_list_is_zero_not_a_crash():
    assert false_link_rate([], {"k1": "x"}, {"k1": {"doc_id": "d1"}}) == 0.0


# ---- the transcript reader -------------------------------------------

def _write_transcript(path, chunks, answer):
    frame = {"type": "_done", "stopReason": "end_turn", "finalAnswer": answer,
             "citations": [], "retrievedChunkIds": [], "usage": {},
             "toolCalls": [{"toolName": "retrieve",
                            "output": json.dumps({"chunks": chunks})}]}
    lines = [json.dumps({"kind": "meta", "query_id": "q1", "repeat": 1}),
             json.dumps({"kind": "terminal", "frame": frame, "wall_ms": 1})]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_pools_reads_chunks_and_answers_from_real_transcript_shape(tmp_path):
    _write_transcript(
        tmp_path / "q1-r1.jsonl",
        [{"chunk_id": "c1", "doc_id": "d1", "text": "held 1,391,157,700 total",
          "doc_title": "T", "page_start": 3}],
        "ADOT received $1,391,157,700.")
    got = list(pools(tmp_path))
    assert len(got) == 1
    stem, chunks, meta, answer = got[0]
    assert stem == "q1-r1"
    assert chunks == {"c1": "held 1,391,157,700 total"}
    # doc_id is what the ambiguity check keys on; page/title are what make
    # a link openable in the viewer.
    assert meta["c1"]["doc_id"] == "d1"
    assert meta["c1"]["page_start"] == 3
    assert answer == "ADOT received $1,391,157,700."


def test_pools_ignores_repeats_other_than_r1(tmp_path):
    _write_transcript(tmp_path / "q1-r1.jsonl", [
        {"chunk_id": "c1", "doc_id": "d1", "text": "x"}], "a")
    _write_transcript(tmp_path / "q1-r2.jsonl", [
        {"chunk_id": "c2", "doc_id": "d1", "text": "x"}], "a")
    assert [s for s, _c, _m, _a in pools(tmp_path)] == ["q1-r1"]


# ---- the phase A gate: --labelled-pool / pools(labelled=True) ---------
# G-OT4 (spec section 5): recorded transcripts predate phase A and carry
# no `is_table` flag on their chunk dicts (nor does a chunk built by
# today's `_chunk_entry` serialize one), so `pools(labelled=True)` cannot
# gate on that field — it must run every chunk through `render_labelled`
# and trust the function's own detection (a tab-joined row plus a
# detectable header) to tell a table chunk from prose.

_TABLE_TEXT = "\n".join([
    "FY 2026 Budget",
    "\tFY 2024 ACTUAL\tFY 2025 ESTIMATE\tFY 2026 APPROVED",
    "OPERATING SUBTOTAL\t155,570,300\t156,637,800\t197,263,200",
])


def test_pools_labelled_renders_table_chunks_and_leaves_prose_alone(tmp_path):
    _write_transcript(
        tmp_path / "q1-r1.jsonl",
        [{"chunk_id": "c1", "doc_id": "d1", "text": _TABLE_TEXT},
         {"chunk_id": "c2", "doc_id": "d1", "text": "Agency description prose."}],
        "answer")
    _stem, chunks, _meta, _answer = next(iter(pools(tmp_path, labelled=True)))
    # A table chunk is rendered — verified against the SAME function
    # production calls, not a re-derived expectation.
    assert chunks["c1"] == render_labelled(_TABLE_TEXT)
    assert "OPERATING SUBTOTAL | FY 2024 ACTUAL: 155,570,300" in chunks["c1"]
    # Prose has no tab-joined row, so render_labelled returns None and the
    # raw text passes through unchanged — the fallback the docstring names.
    assert chunks["c2"] == "Agency description prose."


def test_pools_default_leaves_table_text_as_stored(tmp_path):
    # The property the flag exists to isolate: with labelled=False (the
    # default), a table chunk's pool text is untouched — proving any rate
    # difference between the two runs comes from the rendering, not from
    # pools() always relabelling regardless of the flag.
    _write_transcript(
        tmp_path / "q1-r1.jsonl",
        [{"chunk_id": "c1", "doc_id": "d1", "text": _TABLE_TEXT}], "a")
    _stem, chunks, _meta, _answer = next(iter(pools(tmp_path)))
    assert chunks["c1"] == _TABLE_TEXT


def test_verdict_counts_measures_the_untagged_fallback(tmp_path):
    # Recorded transcripts carry no markers, so this path is the untagged
    # fallback specifically: a value in one document links, the same value
    # in two documents does not.
    _write_transcript(
        tmp_path / "q1-r1.jsonl",
        [{"chunk_id": "c1", "doc_id": "d1", "text": "held 1,391,157,700"},
         {"chunk_id": "c2", "doc_id": "d1", "text": "and 2,468,013,579 more"},
         {"chunk_id": "c3", "doc_id": "d2", "text": "also 2,468,013,579"}],
        "It received $1,391,157,700 and separately $2,468,013,579.")
    counts = verdict_counts(tmp_path)
    assert counts["linked"] == 1        # unambiguous — one document
    assert counts["unverified"] == 1    # ambiguous — two documents
    assert counts["total"] == 2
