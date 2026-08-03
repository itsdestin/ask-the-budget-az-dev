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

# WHY THERE IS NO STAMPING-GAP ALLOW-LIST HERE ANY MORE.
#
# There was one, holding q-009. Both it and q-022 are queries the parser reads
# CORRECTLY and whose answers are stamped to a different agency: q-009 names
# "the DOR Unclaimed Property Fund" and its AFR passage carries only
# agency:sba; q-022 names the Secretary of State and its answer sits in a House
# document. `chunking/entity_stamper.py` cannot resolve "DOR" in document text
# any better than this parser could before the aliases existed — 103 of the 157
# agencies still carry none on the CORPUS side, and fixing that needs a
# re-ingest.
#
# A second entry was the signal to stop exempting and start measuring. Agency
# inference became a ranking preference instead of a filter, and both queries
# pass. The finding itself is unchanged and still matters: the corpus is
# stamped incompletely, and any future work that re-introduces agency FILTERING
# has to reckon with it.


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


def test_an_inferred_agency_can_never_exclude_anything():
    """Agency is a ranking PREFERENCE, not a filter, so it is structurally
    incapable of discarding a query's ground truth.

    This test replaces a per-query guard that checked whether an inferred
    agency filter would exclude its own answer. That guard fired twice —
    q-009 and q-022, both CORRECT parses whose answers are stamped to another
    agency — and firing twice is what prompted measuring the filter against a
    preference. The preference won by 4.8 points of recall at every cutoff and
    both queries now pass, so the property is enforced at the source instead:
    the pipeline never puts an inferred agency into `filters`.

    Asserted against the pipeline SOURCE rather than by running retrieval,
    because running it needs the corpus and the models.
    """
    import inspect

    from retrieval import pipeline

    source = inspect.getsource(pipeline.retrieve)
    assert "agency_canonical_id=inferred_agencies" not in source, (
        "an inferred agency reached the filter — see the measurement at the "
        "inference site before changing this back"
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
    from retrieval.query_agency import AMBIGUOUS_ALIASES, SUPPRESSED_ALIASES

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
    # Either list is acceptable: SUPPRESSED means the slug never resolves
    # at all, which is strictly stronger than the demotion AMBIGUOUS gives.
    guarded = {a.lower() for a in AMBIGUOUS_ALIASES | SUPPRESSED_ALIASES}
    missing = sorted(ordinary_words - guarded)
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

