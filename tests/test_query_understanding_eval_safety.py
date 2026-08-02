"""The inferred filters must never discard a query's own ground truth.

WHY this file exists, and why it reads the eval set rather than a fixture:
the plan's Risk 2 is that `AMBIGUOUS_ALIASES` is hand-maintained and will
drift as aliases are added. A hand-written list cannot guard itself — the
failure mode is precisely that somebody adds an alias and forgets the list.

So the guard is tied to real data instead. Every query in `eval/queries.yaml`
carries the dimensions of the chunks it is supposed to retrieve; if a filter
this pipeline INFERRED would exclude a query's own ground truth, that is a
measurable regression, and it fails here in half a second instead of showing
up as an unexplained recall drop in an eval run half an hour later.

Two real defects were found by running exactly this check by hand on
2026-08-02, before any of it shipped:

  * `general appropriation act` mapped to `budget-bill` — the phrase appears
    in 6,253 corpus chunks, ZERO of them budget-bill. It cost n-003 and n-007
    their ground truth.
  * every JLBC slug becomes an alias, and 13 of them are ordinary English
    words. `for` is a PREPOSITION, and it appears as a standalone token in 14
    of the 47 eval queries — all of which would have hard-filtered to the
    Department of Forestry and Fire Management.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from retrieval.query_agency import parse_query_agencies
from retrieval.query_doc_type import parse_query_doc_types
from retrieval.query_match import is_filterable

QUERIES_PATH = Path(__file__).resolve().parent.parent / "eval" / "queries.yaml"

# Queries whose ground truth a CORRECT inference still excludes, because the
# CORPUS is stamped incompletely. Each entry must name the chunk and the gap.
#
# q-009 asks about "the DOR Unclaimed Property Fund". The parser resolves DOR
# to agency:dor, which is right. But the AFR chunk that answers it,
# agao-afr-fy2025-0116, is stamped ONLY agency:sba — `chunking/entity_stamper`
# did not recognise "DOR" in the document text any better than the query
# parser could before this work, because 103 of the 157 agencies carry no
# alias at all. The query side now has aliases; the CORPUS side still does
# not, and re-stamping means a re-ingest.
#
# This query was already failing before query understanding existed (its
# ground truth sat outside the top 20 — see STATUS.md), so nothing regressed.
# What changed is that a hard filter makes it unrecoverable rather than
# merely low-ranked.
#
# Deliberately an ALLOW-LIST, not a softened assertion: a new entry here is a
# claim that the corpus is wrong, and it should be uncomfortable to add.
KNOWN_STAMPING_GAPS = {"q-009"}


def _queries() -> list[dict]:
    return yaml.safe_load(QUERIES_PATH.read_text(encoding="utf-8")) or []


def _ground_truth(query: dict, dimension: str) -> set[str]:
    """The distinct values of one dimension across a query's expected chunks."""
    out: set[str] = set()
    for chunk in query.get("expected_chunks") or []:
        value = (chunk.get("dimensions") or {}).get(dimension)
        if value:
            out.add(value)
    return out


@pytest.mark.parametrize("query", _queries(), ids=lambda q: q["id"])
def test_an_inferred_agency_filter_never_excludes_the_ground_truth(query):
    """A hard agency filter that discards the answer is worse than no filter:
    it returns confident results from the wrong agency, and nothing on screen
    says a filter was guessed."""
    expected = _ground_truth(query, "agency")
    if not expected:
        pytest.skip("no agency ground truth to protect")
    if query["id"] in KNOWN_STAMPING_GAPS:
        pytest.skip(f"{query['id']}: corpus stamping gap, see KNOWN_STAMPING_GAPS")

    matches = parse_query_agencies(query["query"])
    if not is_filterable(matches):
        return  # a weak match only re-ranks; it cannot discard anything

    inferred = {m.value for m in matches}
    assert inferred & expected, (
        f"{query['id']} would hard-filter to {sorted(inferred)} but its "
        f"ground truth is {sorted(expected)} — the answer would be filtered "
        f"away.\n  query: {query['query']!r}"
    )


@pytest.mark.parametrize("query", _queries(), ids=lambda q: q["id"])
def test_an_inferred_doc_type_filter_never_excludes_the_ground_truth(query):
    expected = _ground_truth(query, "doc_type")
    if not expected:
        pytest.skip("no doc_type ground truth to protect")

    matches = parse_query_doc_types(query["query"])
    if not is_filterable(matches):
        return

    inferred = {m.value for m in matches}
    assert inferred & expected, (
        f"{query['id']} would hard-filter to {sorted(inferred)} but its "
        f"ground truth is {sorted(expected)} — the answer would be filtered "
        f"away.\n  query: {query['query']!r}"
    )


def test_every_ordinary_english_word_slug_is_stoplisted():
    """Named explicitly so the reason survives, and because the parametrized
    tests above only catch a word that happens to appear in the eval set.

    These 13 are JLBC's own URL slugs, so `chunking.agency_catalog` adds every
    one of them as an alias unconditionally — they are live whether or not any
    drafted alias is ever approved.
    """
    from retrieval.query_agency import AMBIGUOUS_ALIASES

    ordinary_words = {
        "art",  # Arts, Arizona Commission on the
        "ban",  # Financial Institutions, Department of
        "bar",  # Barbers, Board of
        "bat",  # Athletic Training, Board of
        "den",  # Dental Examiners, State Board of
        "des",  # Economic Security, Department of
        "dot",  # Transportation, Department of
        "for",  # Forestry and Fire Management -- a PREPOSITION
        "lot",  # Lottery Commission, Arizona State
        "opt",  # Optometry, State Board of
        "per",  # Personnel Board, State
        "pod",  # Podiatry Examiners, State Board of
        "tax",  # Tax Appeals, State Board of
    }
    missing = sorted(ordinary_words - {a.lower() for a in AMBIGUOUS_ALIASES})
    assert not missing, (
        f"these slugs are ordinary English words and would hard-filter a "
        f"query that merely uses the word: {missing}"
    )


def test_a_preposition_cannot_hard_filter():
    """The single worst case, pinned on its own because it is the one that
    would have done the most damage: 'for' appears in 14 of 47 eval queries."""
    matches = parse_query_agencies(
        "What is Arizona's FY 2026 employer contribution rate for the "
        "Elected Officials Retirement Plan?"
    )
    assert not is_filterable(matches), (
        "'for' resolved to a hard agency filter — every question containing "
        "the preposition would be answered out of the Department of Forestry"
    )


def test_the_stamping_gap_allowlist_stays_small():
    """An allow-list is a place bugs go to hide. Every entry is a claim that
    the CORPUS is wrong rather than the code, which is a strong claim; if this
    list is growing, hard-filtering on agency is the thing to re-examine, not
    the list.
    """
    assert len(KNOWN_STAMPING_GAPS) <= 2, (
        f"{len(KNOWN_STAMPING_GAPS)} queries now need a stamping exemption — "
        "re-examine whether an agency match should hard-filter at all"
    )


def test_every_allowlisted_query_still_exists():
    """A stale exemption silently disables a real guard."""
    ids = {q["id"] for q in _queries()}
    assert KNOWN_STAMPING_GAPS <= ids, (
        f"exempted queries no longer in the eval set: {KNOWN_STAMPING_GAPS - ids}"
    )
