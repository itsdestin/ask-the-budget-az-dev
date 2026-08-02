"""Annotation assembly tests.

This is the single artifact both consumers read: the webapp renders it as
chips, the eval judge renders it as inline markers. If they read the same
data they cannot disagree about what the analyst saw.
"""
from __future__ import annotations

from citation.annotate import annotate_answer

META = {
    "c-approps": {"doc_type": "approps-per-agency", "fiscal_year": 2026},
    "c-baseline": {"doc_type": "baseline-per-agency", "fiscal_year": 2026},
}


def test_linked_figure_carries_primary_and_additional():
    answer = "ADE received $1,391,157,700 in FY 2026."
    chunks = {"c-baseline": "ADE 1,391,157,700 projected",
              "c-approps": "ADE 1,391,157,700 enacted"}
    ann = annotate_answer(answer, chunks, META)
    fig = ann["figures"][0]
    assert fig["verdict"] == "linked"
    # Appropriations Report outranks Baseline.
    assert fig["primary"]["chunk_id"] == "c-approps"
    assert fig["primary"]["source_text"] == "1,391,157,700"
    assert [a["chunk_id"] for a in fig["additional"]] == ["c-baseline"]


def test_indices_follow_reading_order():
    answer = "First $1,000,000 then $2,000,000 then $3,000,000."
    chunks = {"c-approps": "1,000,000 2,000,000 3,000,000"}
    ann = annotate_answer(answer, chunks, META)
    assert [f["index"] for f in ann["figures"]] == [1, 2, 3]
    assert [f["text"] for f in ann["figures"]] == [
        "$1,000,000", "$2,000,000", "$3,000,000"]


def test_derived_total_points_at_its_inputs():
    answer = "ADE $1,000,000 and AHCCCS $2,000,000, totalling $3,000,000."
    chunks = {"c-approps": "ADE 1,000,000 AHCCCS 2,000,000"}
    ann = annotate_answer(answer, chunks, META)
    total = ann["figures"][2]
    assert total["verdict"] == "derived"
    assert total["primary"] is None
    assert sorted(total["derived_from"]) == [1, 2]


def test_unverified_when_neither_linked_nor_derived():
    answer = "Spending was $987,654,321 last year."
    ann = annotate_answer(answer, {"c-approps": "unrelated text"}, META)
    assert ann["figures"][0]["verdict"] == "unverified"
    assert ann["figures"][0]["primary"] is None


def test_offsets_index_the_answer_exactly():
    answer = "The total was $1,391,157,700 overall."
    chunks = {"c-approps": "1,391,157,700"}
    fig = annotate_answer(answer, chunks, META)["figures"][0]
    assert answer[fig["start"]:fig["end"]] == "$1,391,157,700"


def test_annotation_is_json_serialisable():
    import json
    answer = "ADE $1,391,157,700."
    ann = annotate_answer(answer, {"c-approps": "1,391,157,700"}, META)
    assert json.loads(json.dumps(ann)) == ann


def test_empty_answer_yields_empty_annotation():
    assert annotate_answer("", {}, {}) == {"figures": []}


def test_derived_from_reports_reading_order_indices_not_list_positions():
    # derived_from must be indices an analyst can find on the page. The
    # linked figures are the 2nd and 3rd figures stated, so a derivation
    # over them must say [2, 3] — not [0, 1], their positions in the
    # internal linked list. Getting this wrong points the chip at the
    # wrong numbers while looking entirely correct.
    answer = "Unsourced $555,555,555; then $1,000,000 and $2,000,000 give $3,000,000."
    chunks = {"c-approps": "1,000,000 and 2,000,000"}
    figs = annotate_answer(answer, chunks, META)["figures"]
    assert figs[0]["verdict"] == "unverified"
    assert [f["verdict"] for f in figs[1:3]] == ["linked", "linked"]
    assert sorted(figs[3]["derived_from"]) == [2, 3]


def test_primary_carries_enough_metadata_to_open_the_pdf():
    # Seen in a browser 2026-08-02: clicking a figure chip always landed on
    # "Couldn't open source PDF". The viewer needs doc_id and page_start, and
    # the annotation carried neither — so the design's whole payoff (click a
    # number, see it highlighted on the page) could never work.
    #
    # Chunk TEXT is deliberately NOT carried: it would multiply the
    # annotation's size by the chunk body for every figure on the page, and
    # the highlighter searches `source_text` first anyway.
    answer = "ADE received $1,391,157,700."
    chunks = {"c-approps": "ADE 1,391,157,700 enacted"}
    meta = {"c-approps": {
        "doc_type": "approps-per-agency", "fiscal_year": 2026,
        "doc_id": "jlbc-approps-fy2026-ade", "doc_title": "FY2026 Approps — ADE",
        "publisher": "jlbc", "page_start": 47, "page_end": 47,
        "bbox": [10.0, 20.0, 300.0, 40.0],
    }}
    primary = annotate_answer(answer, chunks, meta)["figures"][0]["primary"]
    assert primary["doc_id"] == "jlbc-approps-fy2026-ade"
    assert primary["page_start"] == 47
    assert primary["page_end"] == 47
    assert primary["bbox"] == [10.0, 20.0, 300.0, 40.0]
    assert primary["doc_title"] == "FY2026 Approps — ADE"
    assert primary["publisher"] == "jlbc"
    assert primary["fiscal_year"] == 2026
    assert "text" not in primary


def test_missing_locator_metadata_degrades_to_nulls_not_a_crash():
    # A retrieve payload without page/bbox must still yield a linked figure —
    # the chip simply cannot open a page.
    answer = "ADE received $1,391,157,700."
    primary = annotate_answer(
        answer, {"c-approps": "ADE 1,391,157,700"}, META)["figures"][0]["primary"]
    assert primary["doc_id"] is None
    assert primary["page_start"] is None
    assert primary["bbox"] is None
