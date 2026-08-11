"""Annotation assembly tests.

This is the single artifact both consumers read: the webapp renders it as
chips, the eval judge renders it as inline markers. If they read the same
data they cannot disagree about what the analyst saw.

The linking policy under test is spec A2/A3: a model tag is verified
against the chunk it NAMED, an untagged figure links only when exactly one
document holds the value, and nothing anywhere ranks candidate documents.
The authority tie-break that used to sit here is deleted — it was the
mechanism behind the wrong-doc defect (memo §5.1).
"""
from __future__ import annotations

from citation.annotate import annotate_answer
from citation.markers import Tag, parse_markers

# One value, two documents — the shape the old authority rule resolved by
# guessing and this design refuses.
CHUNKS = {"budget-a-0001": "General Fund total 8,287,700,000 for the year",
          "budget-b-0002": "reserve balance 8,287,700,000 held in trust"}
META = {"budget-a-0001": {"doc_id": "doc-a", "doc_type": "afr"},
        "budget-b-0002": {"doc_id": "doc-b",
                          "doc_type": "baseline-per-agency"}}
ALIASES = {"c1": "budget-a-0001", "c2": "budget-b-0002"}


def _annotate(raw_answer):
    stripped, tags = parse_markers(raw_answer)
    return annotate_answer(stripped, CHUNKS, META,
                           tags=tags, alias_map=ALIASES)


# --- the attested path ------------------------------------------------

def test_a_tag_links_to_the_named_chunk_even_when_two_docs_hold_the_value():
    ann = _annotate("The total was $8,287,700,000 [[c2]] that year.")
    (fig,) = ann["figures"]
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "tag"
    assert fig["primary"]["chunk_id"] == "budget-b-0002"
    assert fig["attested_chunk_ids"] == ["budget-b-0002"]


def test_an_untagged_ambiguous_value_is_refused_not_ranked():
    # Both docs hold the value; the old authority rule would have picked
    # the AFR. Spec A3: refuse and say why.
    ann = _annotate("The total was $8,287,700,000 that year.")
    (fig,) = ann["figures"]
    assert fig["verdict"] == "unverified"
    assert fig["ambiguity_count"] == 2
    assert fig["link_basis"] is None


def test_an_ambiguous_figure_reports_no_near_miss():
    # The value is in the pool EXACTLY, twice over, so nearest_value would
    # return the figure itself at distance 0.0 and the chip would claim the
    # source "differs by 0.0%". Ambiguity and not-found are different
    # failures; only one sentence is true at a time.
    ann = _annotate("The total was $8,287,700,000 that year.")
    (fig,) = ann["figures"]
    assert fig["ambiguity_count"] == 2
    assert fig["near_miss"] is None


def test_an_untagged_unambiguous_value_still_links():
    chunks = {"budget-a-0001": CHUNKS["budget-a-0001"]}
    ann = annotate_answer("It was $8,287,700,000 net.", chunks, META,
                          tags=[], alias_map=ALIASES)
    (fig,) = ann["figures"]
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "unambiguous-fallback"


def test_a_tag_that_fails_verification_reports_the_near_miss_from_its_chunk():
    ann = _annotate("The total was $8,290,000,000 [[c1]] that year.")
    (fig,) = ann["figures"]
    assert fig["verdict"] == "unverified"
    assert fig["near_miss"]["chunk_id"] == "budget-a-0001"
    assert fig["near_miss"]["source_text"] == "8,287,700,000"


def test_a_tag_naming_an_out_of_turn_chunk_falls_back_not_redirects():
    ann = annotate_answer(
        "It was $8,287,700,000 net.",
        {"budget-a-0001": CHUNKS["budget-a-0001"]}, META,
        tags=[Tag(aliases=("c9",), at=21)], alias_map=ALIASES)
    (fig,) = ann["figures"]
    assert fig["attested_chunk_ids"] == []
    assert fig["link_basis"] == "unambiguous-fallback"


def test_two_chunks_of_one_document_are_corroboration_not_ambiguity():
    # "Additional" survives the deletion of authority ranking: several
    # passages of the SAME document are not competing claims.
    chunks = {"budget-a-0001": CHUNKS["budget-a-0001"],
              "budget-a-0002": "restated 8,287,700,000 in the appendix"}
    meta = {"budget-a-0001": {"doc_id": "doc-a"},
            "budget-a-0002": {"doc_id": "doc-a"}}
    (fig,) = annotate_answer("Total $8,287,700,000.", chunks, meta,
                             tags=[], alias_map={})["figures"]
    assert fig["verdict"] == "linked"
    assert fig["link_basis"] == "unambiguous-fallback"
    assert [a["chunk_id"] for a in fig["additional"]] == ["budget-a-0002"]


# --- the tag -> figure binding rule -----------------------------------

def test_a_tag_binds_across_a_scale_word():
    # "$8,287.7 million [[c1]]" — the marker sits after the scale word,
    # which is exactly how the prompt asks the model to write it.
    ann = _annotate("The total grew to $8,287.7 million [[c1]] that year.")
    (fig,) = ann["figures"]
    assert fig["attested_chunk_ids"] == ["budget-a-0001"]
    assert fig["link_basis"] == "tag"


def test_a_tag_a_clause_away_does_not_bind():
    # Better an untagged figure — which still gets the fallback — than a
    # tag bound to a number it was never written for.
    ann = _annotate(
        "Spending was $8,287,700,000 and that is a lot of money [[c1]] here.")
    (fig,) = ann["figures"]
    assert fig["attested_chunk_ids"] == []
    assert fig["link_basis"] != "tag"


# --- derivation -------------------------------------------------------

def test_derived_carries_its_operation():
    # Distinctive inputs (5 written significant digits each) so the
    # unambiguous fallback links them; the exact total then derives.
    chunks = {"k": "parts 1,391,200 and 2,547,300 listed"}
    meta = {"k": {"doc_id": "d"}}
    ann = annotate_answer("From $1,391,200 and $2,547,300, total $3,938,500.",
                          chunks, meta, tags=[], alias_map={})
    total = ann["figures"][-1]
    assert total["verdict"] == "derived"
    assert total["operation"] == "sum"
    assert total["derived_from"] == [1, 2]


def test_derived_from_reports_reading_order_indices_not_list_positions():
    # derived_from must be numbers an analyst can find on the page — the
    # DISPLAY indices, not positions in the internal linked list. Getting
    # this wrong points the chip at the wrong numbers while looking
    # entirely correct.
    #
    # The leading unsourced figure draws no chip and takes no number, so
    # the two linked figures are chips [1] and [2] even though they are
    # the 2nd and 3rd figures written.
    answer = ("Unsourced $555,555,555; then $1,391,200 and $2,547,300 "
              "give $3,938,500.")
    chunks = {"k": "parts 1,391,200 and 2,547,300 listed"}
    meta = {"k": {"doc_id": "d"}}
    figs = annotate_answer(answer, chunks, meta,
                           tags=[], alias_map={})["figures"]
    assert figs[0]["verdict"] == "unverified"
    assert figs[0]["index"] is None
    assert [f["verdict"] for f in figs[1:3]] == ["linked", "linked"]
    assert [f["index"] for f in figs[1:3]] == [1, 2]
    assert sorted(figs[3]["derived_from"]) == [1, 2]


# --- shape, offsets, degradation --------------------------------------

def test_indices_follow_reading_order():
    answer = "First $1,391,200 then $2,547,300 then $9,876,500."
    chunks = {"k": "1,391,200 2,547,300 9,876,500"}
    ann = annotate_answer(answer, chunks, {"k": {"doc_id": "d"}})
    assert [f["index"] for f in ann["figures"]] == [1, 2, 3]
    assert [f["text"] for f in ann["figures"]] == [
        "$1,391,200", "$2,547,300", "$9,876,500"]


def test_unverified_when_neither_linked_nor_derived():
    answer = "Spending was $987,654,321 last year."
    ann = annotate_answer(answer, {"k": "unrelated text"}, {"k": {"doc_id": "d"}})
    assert ann["figures"][0]["verdict"] == "unverified"
    assert ann["figures"][0]["primary"] is None


def test_offsets_index_the_answer_exactly():
    answer = "The total was $1,391,157,700 overall."
    chunks = {"k": "1,391,157,700"}
    fig = annotate_answer(answer, chunks, {"k": {"doc_id": "d"}})["figures"][0]
    assert answer[fig["start"]:fig["end"]] == "$1,391,157,700"


def test_annotation_is_json_serialisable():
    import json
    ann = _annotate("ADE $8,287,700,000 [[c1]].")
    assert json.loads(json.dumps(ann)) == ann


def test_empty_answer_yields_empty_annotation():
    assert annotate_answer("", {}, {}) == {"figures": []}


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
        answer, {"c-approps": "ADE 1,391,157,700"},
        {"c-approps": {"doc_type": "approps-per-agency"}},
    )["figures"][0]["primary"]
    assert primary["doc_id"] is None
    assert primary["page_start"] is None
    assert primary["bbox"] is None
