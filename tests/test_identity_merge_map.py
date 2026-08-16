"""Tests for `identity/merge_map.py` (the committed merge table) and
`identity/merge_agencies.py` (the pass that applies it, spec I9).

Nothing here opens a real LanceDB table or loads a model. `FakeStore` is
the same duck-typed double `tests/test_identity_relabel.py` uses for
`store.chunk_store.ChunkStore` (`scan` / `upsert_chunks`); the
co-occurrence check is a pure function over plain dicts and is tested
directly with no store at all. `ingest.lock.IngestLock` is used for real,
rooted at `tmp_path` -- it is a plain file lock, not a database.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from identity.merge_agencies import (
    PairCooccurrence,
    _merge_labels,
    check_cooccurrence,
    check_merge_guard,
    merge_agencies,
    safe_merge_map,
    same_name_pairs,
)
from identity.merge_map import MERGE_MAP
from ingest.lock import IngestLock, LockHeldError

_TABLE = "budget_chunks"


# --- the committed map itself -------------------------------------------


def test_the_merge_map_is_exactly_the_nine_recorded_entries():
    """Committed as data so the claim is visible rather than implicit. This
    asserts that a predecessor unit / duplicate catalog row and its
    surviving id are ONE agency -- a judgement a budget analyst may
    dispute, which is why it is written down and why the pass that applies
    it is reversible (spec I9)."""
    assert MERGE_MAP == {
        "agency:cs": "agency:dcs",
        "agency:doa-csf": "agency:dcs",
        "agency:doa-cfs": "agency:dcs",
        "agency:doacfs": "agency:dcs",
        "agency:uniasum": "agency:uniasu",
        "agency:wif": "agency:wifa",
        "agency:oco": "agency:oeo",
        "agency:cna": "agency:cet",
        "agency:rev": "agency:dor",
    }


def test_no_id_is_both_a_merge_source_and_a_merge_target():
    """A chain (X -> Y, Y -> Z) would need two rewrite passes to converge
    and is not what any entry here claims -- every target is a terminal
    surviving id."""
    assert set(MERGE_MAP) & set(MERGE_MAP.values()) == set()


# --- the co-occurrence guard, as a pure function -------------------------
#
# The guard that separates a RENAME from two real units. STATUS.md records
# that ASU's two ids are contiguous and never overlap -- which is what
# makes that merge a rename -- and that the University of Arizona's Main
# Campus and Health Sciences Center run in PARALLEL every year and must
# never be merged. Co-occurrence in one year is the difference, and these
# specs pin the pure function that decides it -- not a live corpus.


def _row(agency_ids: list[str], fiscal_year: int | None) -> dict[str, Any]:
    return {"agency_canonical_ids": agency_ids, "fiscal_year": fiscal_year}


def test_a_contiguous_rename_with_no_overlap_is_marked_safe():
    """cna FY2011-2019, cet FY2020-2027 -- exactly the ASU shape (measured
    against the live corpus 2026-08-16): contiguous, never overlapping."""
    rows = (
        [_row(["agency:cna"], y) for y in range(2011, 2020)]
        + [_row(["agency:cet"], y) for y in range(2020, 2028)]
    )
    result = check_cooccurrence(rows, {"agency:cna": "agency:cet"})
    assert result["agency:cna"] == PairCooccurrence(
        old_id="agency:cna", target_id="agency:cet",
        safe=True, overlapping_years=(),
    )


def test_two_ids_that_run_in_parallel_every_year_are_marked_unsafe():
    """The University-of-Arizona shape: both ids are each chunk's primary
    label, every year, so co-occurrence is total, not incidental."""
    rows = [
        _row(["agency:uniumain"], y) for y in range(2005, 2028)
    ] + [
        _row(["agency:uniuhsc"], y) for y in range(2005, 2028)
    ]
    result = check_cooccurrence(rows, {"agency:uniumain": "agency:uniuhsc"})
    pair = result["agency:uniumain"]
    assert pair.safe is False
    assert pair.overlapping_years == tuple(range(2005, 2028))


def test_an_id_that_never_appears_as_a_chunk_never_labelled_is_vacuously_safe():
    """`agency:doa-cfs` and `agency:rev` never appear as any chunk's
    primary label in the live corpus (measured 2026-08-16) -- an id with no
    years recorded at all cannot co-occur with anything, and the merge is
    safe by construction, not by omission."""
    rows = [_row(["agency:dcs"], y) for y in (2020, 2021)]
    result = check_cooccurrence(rows, {"agency:doa-cfs": "agency:dcs"})
    assert result["agency:doa-cfs"] == PairCooccurrence(
        old_id="agency:doa-cfs", target_id="agency:dcs",
        safe=True, overlapping_years=(),
    )


def test_only_the_PRIMARY_label_is_scoped_not_every_id_a_table_chunk_carries():
    """`chunking/entity_stamper.py`'s decision D2: a TABLE chunk's
    `resolve_all` returns every catalog name it finds, scalar answer
    pinned first. A statewide summary table naming both ids in the SAME
    chunk must not, by itself, make the pair look unsafe -- that is a
    co-reference, not two competing primary series. Measured against the
    live corpus, scoping to every id (not just the primary) turned the
    genuinely clean `cna` -> `cet` rename into an apparent 8-year overlap,
    entirely from this shape."""
    # One table chunk mentions both ids in the same year -- but only "cna"
    # is that chunk's PRIMARY id (index 0); "cet" is a co-reference.
    rows = [
        _row(["agency:cna", "agency:cet"], 2015),
        *[_row(["agency:cna"], y) for y in range(2011, 2020) if y != 2015],
        *[_row(["agency:cet"], y) for y in range(2020, 2028)],
    ]
    result = check_cooccurrence(rows, {"agency:cna": "agency:cet"})
    assert result["agency:cna"].safe is True


def test_a_row_with_no_fiscal_year_is_ignored_not_a_crash():
    rows = [_row(["agency:cna"], None), _row(["agency:cet"], None)]
    result = check_cooccurrence(rows, {"agency:cna": "agency:cet"})
    assert result["agency:cna"].safe is True


def test_an_unlabelled_row_is_ignored():
    rows = [_row([], 2020)]
    result = check_cooccurrence(rows, {"agency:cna": "agency:cet"})
    assert result["agency:cna"].safe is True


def test_safe_merge_map_excludes_only_the_unsafe_pairs():
    merge_map = {"agency:cna": "agency:cet", "agency:uniumain": "agency:uniuhsc"}
    rows = (
        [_row(["agency:cna"], y) for y in range(2011, 2020)]
        + [_row(["agency:cet"], y) for y in range(2020, 2028)]
        + [_row(["agency:uniumain"], 2020)]
        + [_row(["agency:uniuhsc"], 2020)]
    )
    cooccurrence = check_cooccurrence(rows, merge_map)
    assert safe_merge_map(cooccurrence, merge_map) == {"agency:cna": "agency:cet"}


def test_safe_merge_map_excludes_a_pair_the_check_never_ran_on():
    """A pair absent from `cooccurrence` is excluded, not assumed safe --
    the only source of 'safe' is a check that actually ran on it."""
    assert safe_merge_map({}, {"agency:cna": "agency:cet"}) == {}


def test_pure_cooccurrence_alone_wrongly_rejects_five_of_nine_pairs():
    """HISTORICAL -- this is the WRONG guard, kept as the record of what it
    got wrong. Pure co-occurrence rejects five of nine `MERGE_MAP` entries
    on this synthetic reproduction of the real corpus shape (measured
    2026-08-16). The same-name test below shows those five 'failures' are
    not two units that overlap -- they are ONE catalog entry recorded
    twice, so co-occurrence between them is EXPECTED, and this test is
    exactly the wrong tool for that population. See
    `test_the_committed_MERGE_MAP_is_safe_under_the_corrected_guard_2026_08_16`
    for what replaced it as the real gate."""
    # doa-cfs, doacfs, rev: never a primary label anywhere -> vacuously safe.
    # cna -> cet: contiguous, no overlap -> safe.
    # cs -> dcs, doa-csf -> dcs, uniasum -> uniasu, wif -> wifa, oco -> oeo:
    #   each given at least one shared year, reproducing the measured
    #   stray-mention overlap (see the module docstring / report for the
    #   real sample doc_ids).
    rows = (
        [_row(["agency:cs"], y) for y in (2016, 2027)]
        + [_row(["agency:dcs"], y) for y in (2016, 2027)]
        + [_row(["agency:doa-csf"], 2016)]
        + [_row(["agency:uniasum"], 2012)]
        + [_row(["agency:uniasu"], 2012)]
        + [_row(["agency:wif"], 2024)]
        + [_row(["agency:wifa"], 2024)]
        + [_row(["agency:oco"], 2015)]
        + [_row(["agency:oeo"], 2015)]
        + [_row(["agency:cna"], y) for y in range(2011, 2020)]
        + [_row(["agency:cet"], y) for y in range(2020, 2028)]
    )
    cooccurrence = check_cooccurrence(rows, MERGE_MAP)
    safe = {oid for oid, pair in cooccurrence.items() if pair.safe}
    unsafe = {oid for oid, pair in cooccurrence.items() if not pair.safe}
    assert safe == {"agency:doa-cfs", "agency:doacfs", "agency:rev", "agency:cna"}
    assert unsafe == {
        "agency:cs", "agency:doa-csf", "agency:uniasum",
        "agency:wif", "agency:oco",
    }


# --- the same-name test: the CORRECTED primary guard ---------------------
#
# The controller compared canonical names (samples/entity-catalog.yaml)
# across every MERGE_MAP pair and found all nine share the SAME name as a
# sorted token multiset -- 'Child Safety, Department of' and 'Department
# of Child Safety' are the catalog's own two ways of printing one agency.
# These pairs are one catalog row recorded twice, not two units that
# happen to overlap, so co-occurrence between them is EXPECTED and cannot
# be evidence against merging. The negative control (University of Arizona
# Main Campus vs Health Sciences Center) has two genuinely different names
# and must still fall through to co-occurrence, which still refuses it.


def test_same_name_pairs_matches_regardless_of_word_order_and_punctuation():
    id_to_name = {
        "agency:cs": "Child Safety, Department of",
        "agency:dcs": "Department of Child Safety",
    }
    assert same_name_pairs({"agency:cs": "agency:dcs"}, id_to_name) == {
        "agency:cs"
    }


def test_same_name_pairs_is_case_insensitive():
    id_to_name = {
        "agency:a": "REVENUE, DEPARTMENT OF",
        "agency:b": "revenue, department of",
    }
    assert same_name_pairs({"agency:a": "agency:b"}, id_to_name) == {"agency:a"}


def test_same_name_pairs_excludes_the_university_of_arizona_negative_control():
    """Main Campus and Health Sciences Center are two real units with two
    real different names -- the same-name test must NOT clear this pair;
    it has to fall through to co-occurrence, which is what refuses it."""
    id_to_name = {
        "agency:uniumain": "University of Arizona - Main Campus",
        "agency:uniuhsc": "University of Arizona - Health Sciences Center",
    }
    assert same_name_pairs(
        {"agency:uniumain": "agency:uniuhsc"}, id_to_name
    ) == set()


def test_same_name_pairs_excludes_a_pair_missing_from_the_name_lookup():
    """Never assumed same-named on missing evidence -- an id absent from
    the lookup (e.g. a catalog gap) falls through to co-occurrence."""
    assert same_name_pairs({"agency:x": "agency:y"}, {}) == set()


def test_the_nine_committed_pairs_all_pass_the_same_name_test():
    """Pins the controller's finding against a reproduction of the real
    samples/entity-catalog.yaml canonical names (measured 2026-08-16):
    every one of the nine MERGE_MAP entries names the SAME agency twice."""
    id_to_name = {
        "agency:cs": "Child Safety, Department of",
        "agency:dcs": "Child Safety, Department of",
        "agency:doa-csf": "Department of Child Safety",
        "agency:doa-cfs": "Department of Child Safety",
        "agency:doacfs": "Department of Child Safety",
        "agency:uniasum": "Arizona State University",
        "agency:uniasu": "Arizona State University",
        "agency:wif": "Water Infrastructure Finance Authority",
        "agency:wifa": "Water Infrastructure Finance Authority",
        "agency:oco": "Equal Opportunity, Governor's Office of",
        "agency:oeo": "Equal Opportunity, Governor's Office of",
        "agency:cna": "Constable Ethics Standards and Training Board",
        "agency:cet": "Constable Ethics Standards and Training Board",
        "agency:rev": "Revenue, Department of",
        "agency:dor": "Revenue, Department of",
    }
    assert same_name_pairs(MERGE_MAP, id_to_name) == set(MERGE_MAP)


# --- check_merge_guard: same-name first, co-occurrence the fallback ------


def test_check_merge_guard_clears_a_same_named_pair_even_with_full_overlap():
    """The point of the correction: co-occurrence alone would refuse this
    pair (both ids the primary label every year) but the two ids share one
    canonical name, so they are a single duplicated catalog entry and the
    overlap is EXPECTED, not evidence of two real units."""
    id_to_name = {
        "agency:cs": "Child Safety, Department of",
        "agency:dcs": "Child Safety, Department of",
    }
    rows = (
        [_row(["agency:cs"], y) for y in range(2016, 2028)]
        + [_row(["agency:dcs"], y) for y in range(2016, 2028)]
    )
    result = check_merge_guard(rows, {"agency:cs": "agency:dcs"}, id_to_name)
    assert result["agency:cs"].safe is True


def test_check_merge_guard_falls_back_to_cooccurrence_for_different_names():
    """Placeholder different names here (so the same-name test cannot
    fire) but contiguous with no overlap -- the fallback co-occurrence
    test must still clear a real rename."""
    id_to_name = {
        "agency:cna": "Constable Advisory Board",
        "agency:cet": "Constable Ethics Board",
    }
    rows = (
        [_row(["agency:cna"], y) for y in range(2011, 2020)]
        + [_row(["agency:cet"], y) for y in range(2020, 2028)]
    )
    result = check_merge_guard(rows, {"agency:cna": "agency:cet"}, id_to_name)
    assert result["agency:cna"].safe is True


def test_check_merge_guard_refuses_a_pair_that_fails_both_tests():
    """The University-of-Arizona negative control, run through the full
    guard: different names AND full overlap -- refused, and still present
    in the result with the overlap evidence, never silently dropped."""
    id_to_name = {
        "agency:uniumain": "University of Arizona - Main Campus",
        "agency:uniuhsc": "University of Arizona - Health Sciences Center",
    }
    rows = (
        [_row(["agency:uniumain"], y) for y in range(2005, 2028)]
        + [_row(["agency:uniuhsc"], y) for y in range(2005, 2028)]
    )
    result = check_merge_guard(
        rows, {"agency:uniumain": "agency:uniuhsc"}, id_to_name
    )
    pair = result["agency:uniumain"]
    assert pair.safe is False
    assert pair.overlapping_years == tuple(range(2005, 2028))


def test_check_merge_guard_defaults_to_the_real_catalog_when_no_lookup_given():
    """No id_to_name override -> reads samples/entity-catalog.yaml for real
    (a committed data file, not a database or a model) -- the path
    `merge_agencies()` takes in production."""
    rows = [_row(["agency:cs"], y) for y in (2016, 2027)] + [
        _row(["agency:dcs"], y) for y in (2016, 2027)
    ]
    result = check_merge_guard(rows, {"agency:cs": "agency:dcs"})
    assert result["agency:cs"].safe is True


def test_the_committed_MERGE_MAP_is_safe_under_the_corrected_guard_2026_08_16():
    """Supersedes the co-occurrence-only test above. Measuring the
    canonical names (samples/entity-catalog.yaml, 2026-08-16) shows all
    NINE MERGE_MAP entries name the exact same agency on both sides --
    duplicate catalog rows, not units that happen to overlap -- so the
    same-name test clears every one of them regardless of the overlap
    shape reproduced here (identical to the historical test above, so the
    only thing that changed between the two tests is the guard, not the
    data)."""
    id_to_name = {
        "agency:cs": "Child Safety, Department of",
        "agency:dcs": "Child Safety, Department of",
        "agency:doa-csf": "Department of Child Safety",
        "agency:doa-cfs": "Department of Child Safety",
        "agency:doacfs": "Department of Child Safety",
        "agency:uniasum": "Arizona State University",
        "agency:uniasu": "Arizona State University",
        "agency:wif": "Water Infrastructure Finance Authority",
        "agency:wifa": "Water Infrastructure Finance Authority",
        "agency:oco": "Equal Opportunity, Governor's Office of",
        "agency:oeo": "Equal Opportunity, Governor's Office of",
        "agency:cna": "Constable Ethics Standards and Training Board",
        "agency:cet": "Constable Ethics Standards and Training Board",
        "agency:rev": "Revenue, Department of",
        "agency:dor": "Revenue, Department of",
    }
    rows = (
        [_row(["agency:cs"], y) for y in (2016, 2027)]
        + [_row(["agency:dcs"], y) for y in (2016, 2027)]
        + [_row(["agency:doa-csf"], 2016)]
        + [_row(["agency:uniasum"], 2012)]
        + [_row(["agency:uniasu"], 2012)]
        + [_row(["agency:wif"], 2024)]
        + [_row(["agency:wifa"], 2024)]
        + [_row(["agency:oco"], 2015)]
        + [_row(["agency:oeo"], 2015)]
        + [_row(["agency:cna"], y) for y in range(2011, 2020)]
        + [_row(["agency:cet"], y) for y in range(2020, 2028)]
    )
    result = check_merge_guard(rows, MERGE_MAP, id_to_name)
    safe = {oid for oid, pair in result.items() if pair.safe}
    assert safe == set(MERGE_MAP)


# --- _merge_labels: rewrite + dedup --------------------------------------


def test_merge_labels_replaces_and_dedupes_preserving_first_seen_order():
    merge_map = {"agency:cna": "agency:cet"}
    assert _merge_labels(["agency:cna", "agency:axs"], merge_map) == [
        "agency:cet", "agency:axs",
    ]


def test_merge_labels_is_a_noop_when_target_already_present():
    """A chunk already carrying both the old and the target id must not end
    up with the target listed twice."""
    merge_map = {"agency:doa-cfs": "agency:dcs"}
    assert _merge_labels(["agency:dcs", "agency:doa-cfs"], merge_map) == [
        "agency:dcs",
    ]


def test_merge_labels_leaves_an_untouched_id_alone():
    assert _merge_labels(["agency:axs"], {"agency:cna": "agency:cet"}) == [
        "agency:axs",
    ]


# --- merge_agencies: the write pass, mirroring identity.relabel's shape --


def _full_row(chunk_id: str, doc_id: str, *, agency_ids: list[str],
              fiscal_year: int = 2020, **extra: Any) -> dict[str, Any]:
    base = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": "some text",
        "section_path": ["Some Section"],
        "page": 1,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "source_anchor": None,
        "agency_canonical_ids": list(agency_ids),
        "fund_canonical_id": None,
        "fund_mentions": [],
        "fiscal_year": fiscal_year,
        "doc_type": "baseline-per-agency",
        "is_table": False,
        "table_html": None,
        "token_count": 10,
        "publisher": "jlbc",
        "vector": [0.1, 0.2, 0.3],
    }
    base.update(extra)
    return base


@dataclass
class FakeStore:
    """Same contract as `tests/test_identity_relabel.py::FakeStore` --
    `scan` returns only the requested columns, so a merge pass that forgot
    to request `vector` fails exactly as it would against real LanceDB."""

    table: str
    rows: dict[str, dict[str, Any]]
    scans: list[list[str]] = field(default_factory=list)
    upsert_calls: list[list[dict[str, Any]]] = field(default_factory=list)

    def scan(self, table, columns, *, where=None, limit=None):
        assert table == self.table
        self.scans.append(list(columns))
        return [
            {c: deepcopy(row[c]) for c in columns if c in row}
            for row in self.rows.values()
        ]

    def upsert_chunks(self, table, rows):
        assert table == self.table
        rows = list(rows)
        self.upsert_calls.append(deepcopy(rows))
        for row in rows:
            self.rows[row["chunk_id"]] = deepcopy(row)

    @property
    def upserted_rows(self) -> list[dict[str, Any]]:
        return [r for batch in self.upsert_calls for r in batch]


def test_a_dry_run_merges_the_safe_pairs_and_writes_nothing(tmp_path):
    rows = {
        "c1": _full_row("c1", "doc1", agency_ids=["agency:cna"], fiscal_year=2015),
        "c2": _full_row("c2", "doc2", agency_ids=["agency:cet"], fiscal_year=2022),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    merge_map = {"agency:cna": "agency:cet"}

    # id_to_name={} isolates the co-occurrence FALLBACK path -- this test is
    # about that path specifically, not the same-name shortcut, so no name
    # is offered for either id.
    result = merge_agencies(
        store=store, merge_map=merge_map, table=_TABLE, dry_run=True,
        id_to_name={},
    )

    assert result.changed == 1  # only c1 changes; c2 already agency:cet
    assert result.effective_merge_map == merge_map
    assert result.excluded_pairs == []
    assert store.upsert_calls == []
    assert store.rows == rows
    assert result.reversal_path is None


def test_a_dry_run_reports_an_unsafe_pair_and_does_not_merge_it():
    """The University-of-Arizona shape, injected via an override map so the
    test needs no live corpus: both ids are the primary label of a chunk in
    the same year, so the guard must refuse to merge them. id_to_name={}
    isolates the co-occurrence fallback -- with no names offered, the
    same-name shortcut cannot fire and cannot mask this refusal."""
    rows = {
        "c1": _full_row("c1", "doc1", agency_ids=["agency:uniumain"], fiscal_year=2020),
        "c2": _full_row("c2", "doc2", agency_ids=["agency:uniuhsc"], fiscal_year=2020),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    merge_map = {"agency:uniumain": "agency:uniuhsc"}

    result = merge_agencies(
        store=store, merge_map=merge_map, table=_TABLE, dry_run=True,
        id_to_name={},
    )

    assert result.changed == 0
    assert result.effective_merge_map == {}
    assert len(result.excluded_pairs) == 1
    excluded = result.excluded_pairs[0]
    assert excluded.old_id == "agency:uniumain"
    assert excluded.overlapping_years == (2020,)
    assert store.rows == rows  # untouched


def test_a_dry_run_merges_a_same_named_pair_even_with_full_overlap():
    """End-to-end version of the guard correction, through `merge_agencies`
    itself rather than the pure `check_merge_guard` function: two ids
    sharing a canonical name merge even though they label the SAME fiscal
    year -- exactly the shape the controller found for Child Safety,
    Revenue, ASU, WIFA and Equal Opportunity, and exactly the shape pure
    co-occurrence used to refuse."""
    rows = {
        "c1": _full_row("c1", "doc1", agency_ids=["agency:cs"], fiscal_year=2020),
        "c2": _full_row("c2", "doc2", agency_ids=["agency:dcs"], fiscal_year=2020),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    merge_map = {"agency:cs": "agency:dcs"}
    id_to_name = {
        "agency:cs": "Child Safety, Department of",
        "agency:dcs": "Department of Child Safety",
    }

    result = merge_agencies(
        store=store, merge_map=merge_map, table=_TABLE, dry_run=True,
        id_to_name=id_to_name,
    )

    assert result.changed == 1
    assert result.effective_merge_map == merge_map
    assert result.excluded_pairs == []


def test_the_pass_reads_and_rewrites_the_vector_column(tmp_path):
    """Same trap `identity/relabel.py` names: only `scan` with an explicit
    column list returns `vector`, and every convenient reader projects it
    away (`store/chunk_store.py:107`)."""
    original = _full_row("c1", "doc1", agency_ids=["agency:cna"])
    store = FakeStore(table=_TABLE, rows={"c1": deepcopy(original)})
    merge_map = {"agency:cna": "agency:cet"}
    lock = IngestLock(root=tmp_path)

    result = merge_agencies(
        store=store, merge_map=merge_map, table=_TABLE, dry_run=False,
        batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path, id_to_name={},
    )

    assert result.changed == 1
    assert store.scans, "the pass never scanned anything"
    assert all("vector" in cols for cols in store.scans)
    written = store.upserted_rows[0]
    assert written["vector"] == original["vector"]
    assert written["agency_canonical_ids"] == ["agency:cet"]


def test_no_chunk_id_is_lost_during_a_merge(tmp_path):
    rows = {
        "c1": _full_row("c1", "doc1", agency_ids=["agency:cna"]),
        "c2": _full_row("c2", "doc1", agency_ids=["agency:cet"]),
        "c3": _full_row("c3", "doc2", agency_ids=["agency:axs"]),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    lock = IngestLock(root=tmp_path)

    result = merge_agencies(
        store=store, merge_map={"agency:cna": "agency:cet"}, table=_TABLE,
        dry_run=False, batch_size=10, lock=lock,
        snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
        id_to_name={},
    )

    assert result.chunk_count_before == 3
    assert result.chunk_count_after == 3
    assert set(store.rows) == set(rows)


def test_every_other_column_survives_a_merge_untouched(tmp_path):
    original = _full_row(
        "c1", "doc1", agency_ids=["agency:cna"],
        fiscal_year=2016, doc_type="baseline-per-agency", publisher="jlbc",
        page=42, token_count=99, section_path=["Chapter One", "Ethics"],
    )
    store = FakeStore(table=_TABLE, rows={"c1": deepcopy(original)})
    lock = IngestLock(root=tmp_path)

    merge_agencies(
        store=store, merge_map={"agency:cna": "agency:cet"}, table=_TABLE,
        dry_run=False, batch_size=10, lock=lock,
        snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
        id_to_name={},
    )

    after = store.rows["c1"]
    for key, value in original.items():
        if key == "agency_canonical_ids":
            continue
        assert after[key] == value, f"column {key!r} drifted"
    assert after["agency_canonical_ids"] == ["agency:cet"]


def test_the_merge_refuses_to_run_without_the_ingest_lock(tmp_path):
    rows = {"c1": _full_row("c1", "doc1", agency_ids=["agency:cna"])}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))

    rival = IngestLock(root=tmp_path).acquire()
    try:
        with pytest.raises(LockHeldError):
            merge_agencies(
                store=store, merge_map={"agency:cna": "agency:cet"},
                table=_TABLE, dry_run=False, batch_size=10,
                lock=IngestLock(root=tmp_path),
                snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
                id_to_name={},
            )
    finally:
        rival.release()

    assert store.upsert_calls == [], "must not write a single row without the lock"
    assert store.rows == rows


def test_a_reversal_record_carries_the_map_and_the_excluded_pairs(tmp_path):
    rows = {
        "c1": _full_row("c1", "doc1", agency_ids=["agency:cna"], fiscal_year=2015),
        "c2": _full_row("c2", "doc2", agency_ids=["agency:uniumain"], fiscal_year=2020),
        "c3": _full_row("c3", "doc3", agency_ids=["agency:uniuhsc"], fiscal_year=2020),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    merge_map = {
        "agency:cna": "agency:cet",
        "agency:uniumain": "agency:uniuhsc",
    }
    lock = IngestLock(root=tmp_path)

    result = merge_agencies(
        store=store, merge_map=merge_map, table=_TABLE, dry_run=False,
        batch_size=10, lock=lock, snapshot_and_verify=lambda: None,
        reversal_dir=tmp_path, id_to_name={},
    )

    assert result.reversal == [
        {"doc_id": "doc1", "chunk_id": "c1",
         "before": ["agency:cna"], "after": ["agency:cet"]},
    ]
    assert result.effective_merge_map == {"agency:cna": "agency:cet"}
    assert [p.old_id for p in result.excluded_pairs] == ["agency:uniumain"]

    on_disk = json.loads(result.reversal_path.read_text(encoding="utf-8"))
    assert on_disk["changes"] == result.reversal
    assert on_disk["merge_map"] == merge_map
    assert on_disk["effective_merge_map"] == {"agency:cna": "agency:cet"}
    assert on_disk["excluded_pairs"] == [
        {"old_id": "agency:uniumain", "target_id": "agency:uniuhsc",
         "overlapping_years": [2020]},
    ]
    # the untouched uniumain/uniuhsc rows were never written
    assert store.upserted_rows == [
        {**rows["c1"], "agency_canonical_ids": ["agency:cet"]},
    ]


def test_writes_are_batched(tmp_path):
    rows = {
        f"c{i}": _full_row(f"c{i}", "doc1", agency_ids=["agency:cna"])
        for i in range(5)
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    lock = IngestLock(root=tmp_path)

    result = merge_agencies(
        store=store, merge_map={"agency:cna": "agency:cet"}, table=_TABLE,
        dry_run=False, batch_size=2, lock=lock,
        snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
        id_to_name={},
    )

    assert result.changed == 5
    assert [len(b) for b in store.upsert_calls] == [2, 2, 1]


def test_a_failed_snapshot_verification_stops_the_pass_before_any_write(tmp_path):
    rows = {"c1": _full_row("c1", "doc1", agency_ids=["agency:cna"])}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    lock = IngestLock(root=tmp_path)

    def _boom():
        raise RuntimeError("corpus snapshot is corrupt")

    with pytest.raises(RuntimeError, match="corrupt"):
        merge_agencies(
            store=store, merge_map={"agency:cna": "agency:cet"}, table=_TABLE,
            dry_run=False, batch_size=10, lock=lock,
            snapshot_and_verify=_boom, reversal_dir=tmp_path,
            id_to_name={},
        )
    assert store.upsert_calls == []
