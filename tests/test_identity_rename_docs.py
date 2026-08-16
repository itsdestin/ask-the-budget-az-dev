"""Tests for identity/rename_docs.py — the 22-document doc_id rename (I10).

Nothing here opens a real LanceDB table. `FakeStore` below stands in for
`store.chunk_store.ChunkStore`, duck-typed to the four methods
`rename_corpus` actually calls (`scan`, `delete_doc`, `upsert_chunks`,
`get_by_ids`) — mirroring `tests/test_identity_relabel.py`'s own FakeStore,
which this pass's write phase (lock, snapshot, batched write, verify,
reversal record) is deliberately modelled on. `ingest.lock.IngestLock` is
used for real, rooted at `tmp_path` — a plain file lock, not a database, and
using the real thing is what actually proves the refusal behaviour (a fake
lock could just be programmed to agree).

`derive_renames` / `find_collisions` are pure functions over a
`documents.json`-shaped dict — no doc_id is hard-coded anywhere in this
file, matching the production module's own rule that the derivation IS the
check.
"""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest

from identity.rename_docs import (
    RenameEntry,
    apply_doc_id_renames,
    derive_renames,
    find_collisions,
    rename_corpus,
    verify_anchor_text,
)
from ingest.lock import IngestLock, LockHeldError

_TABLE = "budget_chunks"


def _row(chunk_id: str, doc_id: str, *, text: str, **extra: Any) -> dict[str, Any]:
    """One full `budget_chunks` row, every schema column present (including
    `vector`) — the shape `store.scan(..., _ALL_COLUMNS)` actually returns.
    Mirrors `tests/test_identity_relabel.py::_row` field for field."""
    base = {
        "chunk_id": chunk_id,
        "doc_id": doc_id,
        "text": text,
        "section_path": ["Some Section"],
        "page": 1,
        "bbox": [0.0, 0.0, 1.0, 1.0],
        "source_anchor": None,
        "agency_canonical_ids": [],
        "fund_canonical_id": None,
        "fund_mentions": [],
        "fiscal_year": 2030,
        "doc_type": "topic-pdf",
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
    """In-memory double for `store.chunk_store.ChunkStore`. `scan` mirrors
    the real contract exactly — it returns only the columns asked for — so
    a bug that forgets to request `vector` shows up here exactly as it
    would against real LanceDB: a silently truncated row, not an error."""

    table: str
    rows: dict[str, dict[str, Any]]
    scans: list[list[str]] = field(default_factory=list)
    upsert_calls: list[list[dict[str, Any]]] = field(default_factory=list)
    delete_doc_calls: list[str] = field(default_factory=list)

    def scan(self, table, columns, *, where=None, limit=None):
        assert table == self.table
        self.scans.append(list(columns))
        return [
            {c: deepcopy(row[c]) for c in columns if c in row}
            for row in self.rows.values()
        ]

    def delete_doc(self, table, doc_id):
        assert table == self.table
        self.delete_doc_calls.append(doc_id)
        for cid in [c for c, r in self.rows.items() if r["doc_id"] == doc_id]:
            del self.rows[cid]

    def upsert_chunks(self, table, rows):
        assert table == self.table
        rows = list(rows)
        self.upsert_calls.append(deepcopy(rows))
        # Mirrors the real delete-then-add shape: an incoming row replaces
        # anything already sitting under the SAME chunk_id. None of the
        # tests below deliberately trigger this (find_collisions is what
        # keeps a real rename from ever doing so), but the fake should not
        # lie about the contract it's standing in for.
        incoming_ids = {r["chunk_id"] for r in rows}
        for cid in list(self.rows):
            if cid in incoming_ids:
                del self.rows[cid]
        for row in rows:
            self.rows[row["chunk_id"]] = deepcopy(row)

    def get_by_ids(self, table, chunk_ids):
        assert table == self.table
        return [deepcopy(self.rows[c]) for c in chunk_ids if c in self.rows]

    @property
    def upserted_rows(self) -> list[dict[str, Any]]:
        return [r for batch in self.upsert_calls for r in batch]


# ---------------------------------------------------------------------------
# derive_renames — pure, no doc_id hard-coded
# ---------------------------------------------------------------------------


def test_derive_renames_finds_only_the_family_mismatches():
    """The 22 real documents are FY2022-27 `jlbc-approps-*` / `jlbc-baseline-*`
    ids whose own `source_url` names the OTHER book. This synthetic fixture
    reproduces every shape found in the live corpus (agreement, mismatch,
    older-convention agreement, no url, unparsable url, non-JLBC id) so the
    derivation logic is exercised without depending on real ids at all."""
    documents = {
        # mismatch: approps id, url says baseline -> should rename
        "jlbc-approps-fy2030-zzz": {
            "source_url": "https://www.azjlbc.gov/30baseline/zzz.pdf"
        },
        # agreement: baseline id, url says baseline -> no rename
        "jlbc-baseline-fy2030-yyy": {
            "source_url": "https://www.azjlbc.gov/30baseline/yyy.pdf"
        },
        # mismatch: baseline id, url says AR (approps) -> should rename
        "jlbc-baseline-fy2030-www": {
            "source_url": "https://www.azjlbc.gov/30AR/www.pdf"
        },
        # agreement, older approps convention ("app" not "ar")
        "jlbc-approps-fy2030-vvv": {
            "source_url": "https://www.azjlbc.gov/30app/vvv.pdf"
        },
        # agreement, older baseline convention ("bookN" not "baseline")
        "jlbc-baseline-fy2005-uuu": {
            "source_url": "https://www.azjlbc.gov/05book1/uuu.pdf"
        },
        # no source_url at all -> cannot be judged, skip
        "jlbc-approps-fy2030-nourl": {},
        # url present but not a recognised azjlbc.gov book directory -> skip
        "jlbc-approps-fy2030-badurl": {"source_url": "https://example.com/x.pdf"},
        # not a jlbc-approps/-baseline id at all -> out of scope entirely
        "agao-afr-fy2030-xxx": {
            "source_url": "https://www.azjlbc.gov/30baseline/xxx.pdf"
        },
    }

    renames = derive_renames(documents)

    assert {r.old_doc_id for r in renames} == {
        "jlbc-approps-fy2030-zzz",
        "jlbc-baseline-fy2030-www",
    }
    by_old = {r.old_doc_id: r for r in renames}
    assert by_old["jlbc-approps-fy2030-zzz"] == RenameEntry(
        old_doc_id="jlbc-approps-fy2030-zzz",
        new_doc_id="jlbc-baseline-fy2030-zzz",
        old_family="approps",
        new_family="baseline",
        source_url="https://www.azjlbc.gov/30baseline/zzz.pdf",
    )
    assert by_old["jlbc-baseline-fy2030-www"] == RenameEntry(
        old_doc_id="jlbc-baseline-fy2030-www",
        new_doc_id="jlbc-approps-fy2030-www",
        old_family="baseline",
        new_family="approps",
        source_url="https://www.azjlbc.gov/30AR/www.pdf",
    )


def test_derive_renames_reproduces_the_real_corpus_count():
    """Not a hard-coded list — the real 22 (STATUS.md / spec I10: FY2022x5,
    FY2023x3, FY2024x4, FY2025x2, FY2026x3, FY2027x4, plus one reverse case)
    built here as a documents.json-shaped fixture, run through the same
    `derive_renames` the production CLI calls."""
    counts = {2022: 5, 2023: 3, 2024: 4, 2025: 2, 2026: 3}  # +4 FY2027 and +1 reverse below
    documents: dict[str, dict[str, Any]] = {}
    for year, n in counts.items():
        for i in range(n):
            doc_id = f"jlbc-approps-fy{year}-t{i}"
            documents[doc_id] = {
                "source_url": f"https://www.azjlbc.gov/{year % 100}baseline/t{i}.pdf"
            }
    for i in range(4):  # FY2027 x4
        doc_id = f"jlbc-approps-fy2027-t{i}"
        documents[doc_id] = {
            "source_url": f"https://www.azjlbc.gov/27baseline/t{i}.pdf"
        }
    # the one reverse case: a baseline id whose url says approps (AR)
    documents["jlbc-baseline-fy2026-crr"] = {
        "source_url": "https://www.azjlbc.gov/26AR/crr.pdf"
    }
    # and a pile of correctly-labelled documents that must NOT show up
    for year in (2022, 2023, 2024, 2025, 2026, 2027):
        documents[f"jlbc-baseline-fy{year}-ok"] = {
            "source_url": f"https://www.azjlbc.gov/{year % 100}baseline/ok.pdf"
        }
        documents[f"jlbc-approps-fy{year}-ok"] = {
            "source_url": f"https://www.azjlbc.gov/{year % 100}ar/ok.pdf"
        }

    renames = derive_renames(documents)

    assert len(renames) == 22
    assert sum(1 for r in renames if r.old_family == "baseline") == 1
    assert sum(1 for r in renames if r.old_family == "approps") == 21


# ---------------------------------------------------------------------------
# find_collisions
# ---------------------------------------------------------------------------


def test_find_collisions_flags_a_genuine_conflict():
    documents = {
        "jlbc-approps-fy2030-dup": {
            "source_url": "https://www.azjlbc.gov/30baseline/dup.pdf"
        },
        # already exists under the exact id the rename above would produce,
        # and this document is NOT itself being renamed
        "jlbc-baseline-fy2030-dup": {
            "source_url": "https://www.azjlbc.gov/30baseline/dup.pdf"
        },
    }
    renames = derive_renames(documents)

    collisions = find_collisions(renames, documents)

    assert collisions == ["jlbc-baseline-fy2030-dup"]


def test_find_collisions_does_not_flag_a_two_way_swap():
    """A wants to become B's CURRENT id, and B wants to become A's CURRENT
    id, in the same pass. Neither is a real conflict — both old ids vacate
    before the pass is done — and the collision check must see that rather
    than refusing a rename that is actually safe."""
    documents = {
        "jlbc-approps-fy2030-cr": {
            "source_url": "https://www.azjlbc.gov/30baseline/cr.pdf"
        },
        "jlbc-baseline-fy2030-cr": {
            "source_url": "https://www.azjlbc.gov/30AR/cr.pdf"
        },
    }
    renames = derive_renames(documents)
    assert len(renames) == 2  # both documents disagree with their own url

    collisions = find_collisions(renames, documents)

    assert collisions == []


# ---------------------------------------------------------------------------
# apply_doc_id_renames — the documents.json side, pure
# ---------------------------------------------------------------------------


def test_apply_doc_id_renames_preserves_every_field():
    documents = {
        "jlbc-approps-fy2030-zzz": {
            "title": "FY 2030 Appropriations Report — Some Agency",
            "source_url": "https://www.azjlbc.gov/30baseline/zzz.pdf",
            "fiscal_year": 2030,
            "doc_type": "topic-pdf",
            "publisher": "jlbc",
            "page_count": 4,
        },
        "jlbc-baseline-fy2030-untouched": {"title": "leave me alone"},
    }
    renames = derive_renames(documents)

    updated = apply_doc_id_renames(documents, renames)

    assert "jlbc-approps-fy2030-zzz" not in updated
    assert updated["jlbc-baseline-fy2030-zzz"] == documents["jlbc-approps-fy2030-zzz"]
    assert updated["jlbc-baseline-fy2030-untouched"] == documents[
        "jlbc-baseline-fy2030-untouched"
    ]
    # the original dict must not be mutated by this pure function
    assert "jlbc-approps-fy2030-zzz" in documents


# ---------------------------------------------------------------------------
# rename_corpus — the write phase (lock, snapshot, batched write, verify,
# reversal record)
# ---------------------------------------------------------------------------


def _two_doc_fixture() -> dict[str, dict[str, Any]]:
    """One document that mis-names its own family, plus one that agrees
    with its url (must never be touched by the pass)."""
    return {
        "jlbc-approps-fy2030-zzz": {
            "source_url": "https://www.azjlbc.gov/30baseline/zzz.pdf"
        },
        "jlbc-baseline-fy2030-other": {
            "source_url": "https://www.azjlbc.gov/30baseline/other.pdf"
        },
    }


def test_the_pass_reads_and_rewrites_the_vector_column(tmp_path):
    """`vector` is non-nullable and every convenient reader projects it away
    (`store/chunk_store.py:107`): `get_by_ids`, `vector_search`, `fts_search`
    all use a column list that excludes it. Only `scan` with an explicit
    list returns it. A pass that round-trips through the convenient reader
    would write rows missing a required field."""
    documents = _two_doc_fixture()
    original = _row(
        "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="hello",
        vector=[9.9, 8.8, 7.7],
    )
    store = FakeStore(table=_TABLE, rows={original["chunk_id"]: deepcopy(original)})
    lock = IngestLock(root=tmp_path)

    result = rename_corpus(
        store=store, documents=documents, table=_TABLE, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
    )

    assert result.changed_chunks == 1
    assert store.scans, "the pass never scanned anything"
    assert all("vector" in cols for cols in store.scans), (
        "every scan() call must request vector explicitly"
    )
    written = store.upserted_rows[0]
    assert written["vector"] == [9.9, 8.8, 7.7]
    assert written["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"
    assert written["doc_id"] == "jlbc-baseline-fy2030-zzz"


def test_no_chunk_is_lost_or_gained_beyond_the_rename(tmp_path):
    """G-I3 analog for a RENAME (not a plain edit like relabel's): the total
    row count is unchanged, and the after-id-set equals the before-id-set
    with exactly the renamed ids swapped for their new names — nothing else
    vanishes, nothing else appears."""
    documents = _two_doc_fixture()
    rows = {
        "jlbc-approps-fy2030-zzz-0000": _row(
            "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="a"
        ),
        "jlbc-approps-fy2030-zzz-0001": _row(
            "jlbc-approps-fy2030-zzz-0001", "jlbc-approps-fy2030-zzz", text="b"
        ),
        "jlbc-baseline-fy2030-other-0000": _row(
            "jlbc-baseline-fy2030-other-0000", "jlbc-baseline-fy2030-other", text="c"
        ),
    }
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    lock = IngestLock(root=tmp_path)

    result = rename_corpus(
        store=store, documents=documents, table=_TABLE, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
    )

    assert result.chunk_count_before == 3
    assert result.chunk_count_after == 3
    expected_ids = {
        "jlbc-baseline-fy2030-zzz-0000",
        "jlbc-baseline-fy2030-zzz-0001",
        "jlbc-baseline-fy2030-other-0000",
    }
    assert set(store.rows) == expected_ids


def test_every_other_column_survives_the_rename(tmp_path):
    """Count/id-set equality is not enough on its own: a bug that dropped
    `fiscal_year` or `doc_type` while renaming would leave both intact."""
    documents = _two_doc_fixture()
    original = _row(
        "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="a",
        fiscal_year=2030, doc_type="topic-pdf", publisher="jlbc", page=7,
        token_count=42, section_path=["Chapter One"],
        agency_canonical_ids=["agency:zzz"],
    )
    store = FakeStore(table=_TABLE, rows={original["chunk_id"]: deepcopy(original)})
    lock = IngestLock(root=tmp_path)

    rename_corpus(
        store=store, documents=documents, table=_TABLE, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
    )

    after = store.rows["jlbc-baseline-fy2030-zzz-0000"]
    for key, value in original.items():
        if key in ("doc_id", "chunk_id"):
            continue
        assert after[key] == value, f"column {key!r} drifted"


def test_unrelated_documents_are_never_touched(tmp_path):
    """`_two_doc_fixture()` names one document that DOES need renaming
    ("zzz") and one that already agrees with its own url ("other"). The
    store here only holds a chunk for "other" — proving the pass calls
    `delete_doc` for the renamed document (a no-op here, since it has no
    chunks) but NEVER for the untouched one, and leaves its row byte-for-
    byte alone."""
    documents = _two_doc_fixture()
    unrelated = _row(
        "jlbc-baseline-fy2030-other-0000", "jlbc-baseline-fy2030-other", text="c"
    )
    store = FakeStore(table=_TABLE, rows={unrelated["chunk_id"]: deepcopy(unrelated)})
    lock = IngestLock(root=tmp_path)

    result = rename_corpus(
        store=store, documents=documents, table=_TABLE, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
    )

    assert result.changed_chunks == 0
    assert store.delete_doc_calls == ["jlbc-approps-fy2030-zzz"]
    assert store.rows == {unrelated["chunk_id"]: unrelated}


def test_a_dry_run_writes_nothing(tmp_path):
    documents = _two_doc_fixture()
    original = _row(
        "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="a"
    )
    rows = {original["chunk_id"]: deepcopy(original)}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))

    result = rename_corpus(store=store, documents=documents, table=_TABLE, dry_run=True)

    assert result.renamed_docs == 1
    assert result.changed_chunks == 1  # it DID find the proposed change...
    assert store.upsert_calls == []  # ...but wrote nothing
    assert store.delete_doc_calls == []
    assert store.rows == rows  # the fake corpus is untouched
    assert result.reversal_path is None  # nothing landed on disk either


def test_the_pass_refuses_to_run_without_the_ingest_lock(tmp_path):
    """A rename is delete-then-add per document (mirrors
    `ingest/lance_writer.py`'s write phase): an interruption mid-pass leaves
    a renamed document's OLD chunk rows gone with the new ones not yet
    written. Operationally an ingest, so it must take the same lock."""
    documents = _two_doc_fixture()
    original = _row(
        "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="a"
    )
    rows = {original["chunk_id"]: deepcopy(original)}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))

    rival = IngestLock(root=tmp_path).acquire()
    try:
        with pytest.raises(LockHeldError):
            rename_corpus(
                store=store, documents=documents, table=_TABLE, dry_run=False,
                lock=IngestLock(root=tmp_path), snapshot_and_verify=lambda: None,
                reversal_dir=tmp_path,
            )
    finally:
        rival.release()

    assert store.upsert_calls == [], "must not write a single row without the lock"
    assert store.delete_doc_calls == [], "must not delete a single row without the lock"
    assert store.rows == rows


def test_rename_corpus_refuses_to_apply_when_a_collision_exists(tmp_path):
    """`find_collisions` must gate the WRITE path — see spec I10: "Verify no
    rename target collides with an existing doc_id before writing
    anything." Nothing may be deleted or added once a collision is found."""
    documents = {
        "jlbc-approps-fy2030-dup": {
            "source_url": "https://www.azjlbc.gov/30baseline/dup.pdf"
        },
        "jlbc-baseline-fy2030-dup": {
            "source_url": "https://www.azjlbc.gov/30baseline/dup.pdf"
        },
    }
    original = _row("jlbc-approps-fy2030-dup-0000", "jlbc-approps-fy2030-dup", text="a")
    rows = {original["chunk_id"]: deepcopy(original)}
    store = FakeStore(table=_TABLE, rows=deepcopy(rows))
    lock = IngestLock(root=tmp_path)

    with pytest.raises(RuntimeError, match="collis"):
        rename_corpus(
            store=store, documents=documents, table=_TABLE, dry_run=False,
            lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
        )

    assert store.upsert_calls == []
    assert store.delete_doc_calls == []
    assert store.rows == rows
    assert not lock.held, "the lock must not be left held after a refusal"


def test_a_reversal_record_carries_the_old_and_new_ids(tmp_path):
    documents = _two_doc_fixture()
    original = _row(
        "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="a"
    )
    store = FakeStore(table=_TABLE, rows={original["chunk_id"]: deepcopy(original)})
    lock = IngestLock(root=tmp_path)

    result = rename_corpus(
        store=store, documents=documents, table=_TABLE, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
    )

    assert result.doc_renames == [
        {
            "old_doc_id": "jlbc-approps-fy2030-zzz",
            "new_doc_id": "jlbc-baseline-fy2030-zzz",
            "old_family": "approps",
            "new_family": "baseline",
            "source_url": "https://www.azjlbc.gov/30baseline/zzz.pdf",
        }
    ]
    assert result.chunk_id_pairs == [
        {
            "old_chunk_id": "jlbc-approps-fy2030-zzz-0000",
            "new_chunk_id": "jlbc-baseline-fy2030-zzz-0000",
            "old_doc_id": "jlbc-approps-fy2030-zzz",
            "new_doc_id": "jlbc-baseline-fy2030-zzz",
        }
    ]
    assert result.reversal_path is not None
    on_disk = json.loads(result.reversal_path.read_text(encoding="utf-8"))
    assert on_disk["doc_renames"] == result.doc_renames
    assert on_disk["chunk_id_pairs"] == result.chunk_id_pairs


def test_reversal_and_dry_run_pairs_agree(tmp_path):
    """The dry-run's chunk_id_pairs (what a controller inspects BEFORE
    approving an apply) must be the exact set the apply later writes — spec
    I10's eval-repoint step depends on trusting the dry-run output."""
    documents = _two_doc_fixture()
    original = _row(
        "jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz", text="a"
    )
    store_dry = FakeStore(table=_TABLE, rows={original["chunk_id"]: deepcopy(original)})
    dry = rename_corpus(store=store_dry, documents=documents, table=_TABLE, dry_run=True)

    store_apply = FakeStore(table=_TABLE, rows={original["chunk_id"]: deepcopy(original)})
    lock = IngestLock(root=tmp_path)
    applied = rename_corpus(
        store=store_apply, documents=documents, table=_TABLE, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: None, reversal_dir=tmp_path,
    )

    assert dry.chunk_id_pairs == applied.chunk_id_pairs
    assert dry.doc_renames == applied.doc_renames


# ---------------------------------------------------------------------------
# verify_anchor_text — the eval re-point's human-runnable verification path
# ---------------------------------------------------------------------------


def test_verify_anchor_text_true_when_present():
    row = _row("doc-0013", "doc", text="The FY 2026 EORP employer contribution rate is 70.70%")
    store = FakeStore(table=_TABLE, rows={row["chunk_id"]: row})

    assert verify_anchor_text(
        store, _TABLE, "doc-0013", "FY 2026 EORP employer contribution rate is 70.70%"
    ) is True


def test_verify_anchor_text_false_when_missing_or_absent():
    row = _row("doc-0013", "doc", text="something else entirely")
    store = FakeStore(table=_TABLE, rows={row["chunk_id"]: row})

    assert verify_anchor_text(store, _TABLE, "doc-0013", "not in there") is False
    assert verify_anchor_text(store, _TABLE, "doc-nonexistent", "anything") is False
