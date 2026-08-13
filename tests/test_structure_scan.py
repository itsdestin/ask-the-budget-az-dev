"""The committed corpus scan (spec X11).

No real LanceDB directory and no ONNX weights: the store is a stub whose
`scan` returns rows, which is what keeps this suite runnable on a fresh
clone.
"""
from __future__ import annotations

from scripts.structure_scan import scan

BARE = "1" * 200
WORDS = "budget appropriation general fund " * 6


class _FakeStore:
    def __init__(self, rows_by_table):
        self.rows_by_table = rows_by_table
        self.asked = []

    def scan(self, name, columns, **kwargs):
        self.asked.append((name, tuple(columns)))
        return self.rows_by_table.get(name, [])


def _rows(doc_id, bare, clean):
    return (
        [{"doc_id": doc_id, "text": BARE} for _ in range(bare)]
        + [{"doc_id": doc_id, "text": WORDS} for _ in range(clean)]
    )


def test_the_scan_reads_BOTH_chunk_tables():
    """budget_chunks alone omits 2,103 fiscal notes, which then score zero
    and read as catastrophically broken -- the exact error that wrecked
    the first pass of the coverage calibration."""
    store = _FakeStore({})
    scan(store)
    assert [name for name, _ in store.asked] == [
        "budget_chunks", "fiscal_note_chunks"
    ]


def test_the_scan_projects_only_two_columns():
    """It must not drag vectors out of the store, on EVERY table scanned --
    not just the first. This project has twice been burned by the
    fiscal-notes table being treated differently from the budget table, so
    a projection regression scoped to only the second table is the exact
    shape that must not slip through."""
    store = _FakeStore({})
    scan(store)
    assert len(store.asked) == 2
    for _, columns in store.asked:
        assert columns == ("doc_id", "text")


def test_a_document_over_the_ceiling_is_reported():
    store = _FakeStore({"budget_chunks": _rows("bad", bare=7, clean=13)})
    result = scan(store)
    assert result["over_ceiling"] == [("bad", 0.35)]


def test_a_document_under_the_ceiling_is_not_reported():
    store = _FakeStore({"budget_chunks": _rows("ok", bare=1, clean=19)})
    result = scan(store)
    assert result["over_ceiling"] == []


def test_a_small_document_is_counted_but_never_judged():
    """The small-denominator trap, at scan level."""
    store = _FakeStore({"budget_chunks": _rows("tiny", bare=3, clean=0)})
    result = scan(store)
    assert result["documents"] == 1
    assert result["judgeable"] == 0
    assert result["over_ceiling"] == []


def test_the_near_miss_band_is_reported_separately():
    """The whole reason to commit this: a document just under the ceiling
    is the second example the corpus does not currently have."""
    store = _FakeStore({"budget_chunks": _rows("close", bare=2, clean=18)})
    result = scan(store)
    assert result["near_miss"] == [("close", 0.1)]


def test_a_document_scoring_exactly_the_ceiling_is_not_over_it():
    """The ceiling is EXCLUSIVE -- a document fails by scoring ABOVE
    MAX_UNLABELLED, not at or above it. A document landing exactly on 0.20
    belongs in the near-miss band, not over_ceiling."""
    store = _FakeStore({"budget_chunks": _rows("on_ceiling", bare=4, clean=16)})
    result = scan(store)
    assert result["scores"]["on_ceiling"] == 0.20
    assert result["over_ceiling"] == []
    assert result["near_miss"] == [("on_ceiling", 0.20)]


def test_the_near_miss_band_is_inclusive_at_the_floor():
    """NEAR_MISS_FLOOR is the bottom of an inclusive band -- a document
    landing exactly on it still counts as a near-miss, not below the band
    and unreported."""
    store = _FakeStore({"budget_chunks": _rows("on_floor", bare=1, clean=19)})
    result = scan(store)
    assert result["scores"]["on_floor"] == 0.05
    assert result["near_miss"] == [("on_floor", 0.05)]
