"""The surgical section_path repair (spec §3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chunking.repair_section_paths import (
    PLAN_COLUMNS,
    RowChange,
    _missing_tolerance,
    plan_document,
    repair_section_paths,
)


def _page_json(page: int, blocks: list[dict]) -> dict:
    return {"extractor": "mineru-3.1.6", "source_pdf": "x.pdf", "page": page, "blocks": blocks}


def _heading(text: str) -> dict:
    return {"type": "text", "text": text, "text_level": 1}


def _table(cell: str) -> dict:
    return {"type": "table", "table_body": f"<table><tr><td>{cell}</td></tr></table>"}


@pytest.fixture()
def root(tmp_path: Path) -> Path:
    """A data dir holding one document's cached extractor output: a contents
    page naming an agency, then that agency's own table."""
    out = tmp_path / "extractor-output" / "doc-a"
    out.mkdir(parents=True)
    (out / "page-1.json").write_text(json.dumps(_page_json(1, [
        _heading("Table of Contents"), _table("Acupuncture Examiners, Board of"),
    ])), encoding="utf-8")
    (out / "page-9.json").write_text(json.dumps(_page_json(9, [
        _heading("Acupuncture Examiners, Board of"), _table("Acupuncture Examiners, Board of"),
    ])), encoding="utf-8")
    return tmp_path


def _stored_rows() -> list[dict]:
    """What the corpus holds today: BOTH tables labelled 'Table of Contents',
    because the text search matched the contents page first."""
    return [
        {"chunk_id": "doc-a-0000", "doc_id": "doc-a", "is_table": True,
         "section_path": ["Table of Contents"],
         "text": "Table of Contents\nAcupuncture Examiners, Board of"},
        {"chunk_id": "doc-a-0001", "doc_id": "doc-a", "is_table": True,
         "section_path": ["Table of Contents"],
         "text": "Table of Contents\nAcupuncture Examiners, Board of"},
    ]


def test_plan_relabels_the_second_table_and_leaves_the_first(root: Path):
    changes, skipped = plan_document("doc-a", _stored_rows(), root)
    assert skipped is None
    assert [c.chunk_id for c in changes] == ["doc-a-0001"]
    assert changes[0].new_path == ["Acupuncture Examiners, Board of"]
    assert changes[0].new_text == (
        "Acupuncture Examiners, Board of\nAcupuncture Examiners, Board of"
    )


def test_plan_removes_the_heading_line_entirely_when_the_path_goes_empty(root: Path):
    """Spec §3.3: to-blank REMOVES line 0; it does not leave a blank line.
    `_build_text` opens with `if section_path:`, so a blank first line would
    not match what a fresh chunk_doc produces (G-T6)."""
    rows = [{"chunk_id": "doc-a-0000", "doc_id": "doc-a", "is_table": True,
             "section_path": ["Somewhere Else"],
             "text": "Somewhere Else\nAcupuncture Examiners, Board of"}]
    out = (root / "extractor-output" / "doc-a" / "page-1.json")
    out.write_text(json.dumps(_page_json(1, [_table("Acupuncture Examiners, Board of")])),
                   encoding="utf-8")
    (root / "extractor-output" / "doc-a" / "page-9.json").unlink()
    changes, skipped = plan_document("doc-a", rows, root)
    assert skipped is None
    assert changes[0].new_path == []
    assert changes[0].new_text == "Acupuncture Examiners, Board of"
    assert not changes[0].new_text.startswith("\n")


def test_plan_refuses_a_document_whose_body_no_longer_matches(root: Path):
    """The chunk<->table mapping is a hypothesis per document and is GATED
    (spec §3.2). Every line but line 0 must match, or the document is
    skipped and named."""
    rows = _stored_rows()
    rows[1]["text"] = "Table of Contents\nSOMETHING ELSE ENTIRELY"
    changes, skipped = plan_document("doc-a", rows, root)
    assert changes == []
    assert skipped is not None and "body" in skipped.lower()


def test_plan_refuses_a_document_with_a_different_table_count(root: Path):
    rows = _stored_rows() + [
        {"chunk_id": "doc-a-0002", "doc_id": "doc-a", "is_table": True,
         "section_path": [], "text": "extra"}
    ]
    changes, skipped = plan_document("doc-a", rows, root)
    assert changes == []
    assert skipped is not None and "count" in skipped.lower()


def test_plan_skips_a_document_with_no_cached_extractor_output(tmp_path: Path):
    changes, skipped = plan_document("doc-missing", _stored_rows(), tmp_path)
    assert changes == []
    assert skipped is not None and "extractor output" in skipped.lower()


def test_narrative_rows_are_never_touched(root: Path):
    rows = _stored_rows() + [
        {"chunk_id": "doc-a-0002", "doc_id": "doc-a", "is_table": False,
         "section_path": ["Table of Contents"], "text": "prose"}
    ]
    changes, skipped = plan_document("doc-a", rows, root)
    assert skipped is None
    assert all(c.chunk_id != "doc-a-0002" for c in changes)


def test_plan_reads_the_rung_folder_the_sidecar_names(root: Path):
    """`method` selects `<doc_id>/<method>/`; the legacy root output (an
    OLDER reading, here deliberately different) must not be read."""
    sub = root / "extractor-output" / "doc-a" / "mineru"
    sub.mkdir()
    for name in ("page-1.json", "page-9.json"):
        (root / "extractor-output" / "doc-a" / name).replace(sub / name)
    (root / "extractor-output" / "doc-a" / "page-1.json").write_text(
        json.dumps(_page_json(1, [_table("stale reading")])), encoding="utf-8"
    )
    changes, skipped = plan_document("doc-a", _stored_rows(), root, method="mineru")
    assert skipped is None
    assert [c.chunk_id for c in changes] == ["doc-a-0001"]


def test_table_rows_are_matched_by_numeric_suffix_not_string_order(root: Path):
    """chunk ids are zero-padded to four digits; a document with 10,000+
    tables would sort `-10000` before `-0002` as strings. None exists today
    (the Governor's Budget has 1,246); this is cheap insurance, not a fix."""
    from chunking.repair_section_paths import _chunk_index
    assert _chunk_index({"chunk_id": "doc-a-10000"}) > _chunk_index({"chunk_id": "doc-a-0002"})


def test_plan_skips_a_document_with_a_malformed_chunk_id_instead_of_crashing(root: Path):
    """`_chunk_index` has no guard around its `int()` call, and neither
    `plan_document`'s sort nor `_plan_corpus`'s per-document loop wrapped it
    in a try/except -- one row with a chunk_id lacking a numeric `-NNNN`
    suffix used to abort the ENTIRE corpus-wide dry run. The module's own
    rule is that a document that cannot be planned is skipped and NAMED,
    never a crash."""
    rows = [{"chunk_id": "doc-a-final", "doc_id": "doc-a", "is_table": True,
             "section_path": ["Table of Contents"],
             "text": "Table of Contents\nAcupuncture Examiners, Board of"}]
    changes, skipped = plan_document("doc-a", rows, root)
    assert changes == []
    assert skipped is not None
    assert "malformed chunk_id" in skipped
    assert "doc-a-final" in skipped

    result = repair_section_paths(
        store=_FakeStore(rows), embedder=_FakeEmbedder(), root=root, dry_run=True
    )
    assert result.documents_skipped.get("doc-a") == skipped


def _ids_in_predicate(where: str | None) -> set[str] | None:
    """The ids out of `chunk_id IN ('a', 'b')` as `_in_list` writes it.

    `sql_str` escapes a literal apostrophe by DOUBLING it, so this walks the
    string rather than splitting on commas -- an id containing `\'` would
    otherwise be read as two ids and the row silently dropped.
    """
    if not where:
        return None
    inner = where[where.index("(") + 1:where.rindex(")")]
    ids: list[str] = []
    i = 0
    while i < len(inner):
        if inner[i] != "'":
            i += 1
            continue
        i += 1
        buf: list[str] = []
        while i < len(inner):
            if inner[i] == "'":
                if i + 1 < len(inner) and inner[i + 1] == "'":
                    buf.append("'")
                    i += 2
                    continue
                i += 1
                break
            buf.append(inner[i])
            i += 1
        ids.append("".join(buf))
    return set(ids)


def test_the_id_predicate_quotes_every_literal_through_sql_str():
    """`_in_list` is the only place this pass builds a SQL predicate, and a
    LanceDB filter is a STRING with no parameter binding -- an unquoted id
    is a parse error at best and a rewritten predicate at worst."""
    from chunking.repair_section_paths import _in_list
    assert _in_list(["doc-a-0001"]) == "chunk_id IN ('doc-a-0001')"
    assert _in_list(["a", "b"]) == "chunk_id IN ('a', 'b')"
    awkward = "doc-o'brien-0001"
    assert _in_list([awkward]) == "chunk_id IN ('doc-o''brien-0001')"
    # ...and the fake's parser reads back exactly the id that went in, so a
    # test store filtering on this predicate agrees with the real one.
    assert _ids_in_predicate(_in_list([awkward])) == {awkward}


class _FakeStore:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.written: list[list[dict]] = []
        self.fts_built: list[str] = []
        self.optimized: list[str] = []

    def scan(self, name, columns, *, where=None, limit=None):
        # WHY this parses the predicate instead of ignoring it: while the
        # fake returned every row for every scan, the batched
        # `chunk_id IN (...)` fetch and the "rows vanished under the plan"
        # refusal were both structurally unreachable from any test -- the
        # store always answered with exactly the rows that were asked for.
        rows = self.rows
        wanted = _ids_in_predicate(where)
        if wanted is not None:
            rows = [r for r in rows if r["chunk_id"] in wanted]
        return [{k: r[k] for k in columns if k in r} for r in rows]

    def upsert_chunks(self, name, rows):
        rows = list(rows)
        self.written.append(rows)
        # APPLY the write, as the real store does. The verification step
        # re-reads the store and must see the new values land; a fake that
        # only records the call makes the correct implementation fail with
        # "section_path did not land" (6 of 8 apply tests, second draft).
        by_id = {r["chunk_id"]: r for r in rows}
        self.rows = [dict(by_id.get(r["chunk_id"], r)) for r in self.rows]

    def build_fts_index(self, name):
        self.fts_built.append(name)

    def optimize(self, name, *, retention=None):
        self.optimized.append(name)


class _FakeEmbedder:
    dim = 4

    def embed_batch(self, texts, *, input_type="document"):
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


def test_dry_run_writes_nothing_and_takes_no_lock(root: Path):
    store = _FakeStore(_stored_rows())
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=True
    )
    assert result.changed == 1
    assert result.scanned == 2
    assert store.written == []
    assert store.fts_built == []
    assert len(result.reversal) == 1
    assert result.reversal[0]["chunk_id"] == "doc-a-0001"
    assert result.reversal[0]["before"]["section_path"] == ["Table of Contents"]
    assert result.per_document["doc-a"] == {"tables": 2, "changed": 1, "relabelled": 1, "to_blank": 0}


def test_dry_run_passes_the_sidecar_method_and_skips_docx(root: Path):
    """The corpus-wide plan reads `documents.json` ONCE and hands each
    document its recorded rung; DOCX bills have no page output and no table
    chunks, and are named as such instead of inflating the 'no cached
    extractor output' count."""
    (root / "documents.json").write_text(json.dumps({
        "doc-a": {"extraction": {"method": "mineru"}},
        "doc-x": {"source_format": "docx"},
    }), encoding="utf-8")
    sub = root / "extractor-output" / "doc-a" / "mineru"
    sub.mkdir()
    for name in ("page-1.json", "page-9.json"):
        (root / "extractor-output" / "doc-a" / name).replace(sub / name)
    rows = _stored_rows() + [
        {"chunk_id": "doc-x-0000", "doc_id": "doc-x", "is_table": False,
         "section_path": ["SEC 06-18"], "text": "[SEC 06-18] Section 1"}
    ]
    result = repair_section_paths(store=_FakeStore(rows), embedder=_FakeEmbedder(), root=root)
    assert result.changed == 1
    assert result.documents_skipped == {"doc-x": "docx document: section chunks, no tables, nothing to repair"}


def test_only_restricts_the_plan_to_the_named_documents(root: Path):
    rows = _stored_rows() + [
        {"chunk_id": "doc-b-0000", "doc_id": "doc-b", "is_table": True,
         "section_path": ["X"], "text": "X\nrow"}
    ]
    result = repair_section_paths(
        store=_FakeStore(rows), embedder=_FakeEmbedder(), root=root, only={"doc-a"}
    )
    assert set(result.per_document) == {"doc-a"}
    assert "doc-b" not in result.documents_skipped


class _FakeLock:
    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *exc):
        return False


def _full_rows() -> list[dict]:
    base = {
        "page": 1, "bbox": None, "source_anchor": None,
        "agency_canonical_ids": ["agency:ost"], "fund_canonical_id": None,
        "fund_mentions": ["fund:general"], "fiscal_year": 2026,
        "doc_type": "governors-budget", "table_html": "<table></table>",
        "token_count": 7, "publisher": "governor", "vector": [0.0, 0.0, 0.0, 0.0],
    }
    rows = []
    for row in _stored_rows():
        merged = dict(base)
        merged.update(row)
        rows.append(merged)
    return rows


def test_apply_writes_only_the_changed_row(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    lock = _FakeLock()
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: "snap.zip",
        reversal_dir=tmp_path,
    )
    assert result.changed == 1
    assert lock.entered == 1
    written = [r for batch in store.written for r in batch]
    assert [r["chunk_id"] for r in written] == ["doc-a-0001"]


def test_apply_leaves_the_agency_and_fund_columns_byte_identical(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    written = [r for batch in store.written for r in batch][0]
    assert written["agency_canonical_ids"] == ["agency:ost"]
    assert written["fund_mentions"] == ["fund:general"]
    assert written["page"] == 1
    assert written["table_html"] == "<table></table>"
    # ...and, the half that matters, what the STORE holds afterwards. The
    # dict handed to upsert_chunks only records what this pass intended;
    # G-T3 is about what survived the write.
    stored = {r["chunk_id"]: r for r in store.rows}["doc-a-0001"]
    assert stored["agency_canonical_ids"] == ["agency:ost"]
    assert stored["fund_mentions"] == ["fund:general"]
    assert stored["page"] == 1
    assert stored["table_html"] == "<table></table>"


class _DroppingStore(_FakeStore):
    """A store that loses a pass-through column on the way in -- the exact
    shape spec G-T3 refuses, and invisible to a row COUNT because
    upsert_chunks deletes then adds."""

    def upsert_chunks(self, name, rows):
        # Copied first: these dicts are the same objects the write path
        # keeps as its record of what was sent, and mutating them in place
        # would make the corrupted value look like the intended one.
        rows = [dict(r) for r in rows]
        for row in rows:
            row["agency_canonical_ids"] = []
        super().upsert_chunks(name, rows)


def test_apply_refuses_when_the_store_dropped_a_pass_through_column(root: Path, tmp_path: Path):
    """The verifier used to re-read every column and check only three of
    them, so a write that dropped `agency_canonical_ids` passed in silence."""
    store = _DroppingStore(_full_rows())
    with pytest.raises(RuntimeError, match="agency_canonical_ids"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )


def test_apply_recomputes_the_vector_and_the_token_count(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    written = [r for batch in store.written for r in batch][0]
    # _FakeEmbedder encodes len(text) in the first component.
    assert written["vector"][0] == float(len(written["text"]))
    from chunking.builders._tokens import count_tokens
    assert written["token_count"] == count_tokens(written["text"])
    assert written["token_count"] != 7


def test_apply_rebuilds_the_full_text_index_then_optimizes(root: Path, tmp_path: Path):
    """funds/unstamp.py's lesson: rows re-added by upsert_chunks are
    invisible to BM25 until the FTS index is rebuilt. identity/relabel.py
    does NOT do this and is a known follow-up; this pass must."""
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    assert store.fts_built == ["budget_chunks"]
    assert store.optimized == ["budget_chunks"]


def test_apply_writes_a_reversal_record_carrying_the_old_text(root: Path, tmp_path: Path):
    store = _FakeStore(_full_rows())
    repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    files = list(tmp_path.glob("section-path-reversal-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["rows"][0]["before"]["text"] == (
        "Table of Contents\nAcupuncture Examiners, Board of"
    )


def test_apply_refuses_when_the_snapshot_fails(root: Path, tmp_path: Path):
    def _no_snapshot():
        raise RuntimeError("share unreachable")

    store = _FakeStore(_full_rows())
    with pytest.raises(RuntimeError, match="share unreachable"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=_no_snapshot, reversal_dir=tmp_path,
        )
    assert store.written == []


def test_apply_with_nothing_to_do_takes_no_snapshot_writes_nothing_and_skips_the_index_rebuild(
    root: Path, tmp_path: Path
):
    """A snapshot zips the whole corpus under the lock -- minutes. It must
    come AFTER the "is there anything to write?" check, not before."""
    rows = _full_rows()
    rows[1]["section_path"] = ["Acupuncture Examiners, Board of"]
    rows[1]["text"] = "Acupuncture Examiners, Board of\nAcupuncture Examiners, Board of"
    store = _FakeStore(rows)
    snapshots: list[str] = []
    lock = _FakeLock()
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=lock, snapshot_and_verify=lambda: snapshots.append("snap.zip") or "snap.zip",
        reversal_dir=tmp_path,
    )
    assert result.changed == 0
    assert snapshots == []
    assert lock.entered == 0
    assert store.written == []
    assert store.fts_built == []


class _MovedStore(_FakeStore):
    """A row was re-ingested between the plan and the write: the planning
    scan (PLAN_COLUMNS) saw the old text, the full-column fetch at write
    time sees new text under the same chunk_id."""

    def scan(self, name, columns, *, where=None, limit=None):
        out = super().scan(name, columns, where=where, limit=limit)
        if "vector" in columns:
            for r in out:
                if r["chunk_id"] == "doc-a-0001":
                    r["text"] = "Table of Contents\nREINGESTED SINCE THE PLAN"
        return out


def test_apply_refuses_a_row_whose_text_changed_since_the_plan(root: Path, tmp_path: Path):
    """The plan is computed BEFORE the lock (tens of minutes of reading
    extractor JSON). A document re-ingested in that window carries the same
    chunk_ids and different text; writing the planned text over it would
    clobber a fresh ingest with a sentence derived from a stale one."""
    store = _MovedStore(_full_rows())
    with pytest.raises(RuntimeError, match="moved under the plan"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    assert store.written == []


class _DriftingStore(_FakeStore):
    """A store whose write also corrupts a row the pass never touched --
    the shape `identity/relabel.py`'s untouched-row sample exists to catch
    (a delete-then-add that lands on the wrong ids)."""

    def upsert_chunks(self, name, rows):
        super().upsert_chunks(name, rows)
        self.rows[0]["text"] = "CORRUPTED"


def test_apply_samples_untouched_rows_and_refuses_when_one_drifted(root: Path, tmp_path: Path):
    """G-T3's second half: changed rows verified in full AND a sample of
    rows nothing was supposed to touch compared to their pre-write values."""
    store = _DriftingStore(_full_rows())
    with pytest.raises(RuntimeError, match="never supposed to change"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )


class _ExplodingStore(_FakeStore):
    """The share goes away part-way through the write."""

    def upsert_chunks(self, name, rows):
        raise RuntimeError("the share went away mid-write")


def test_the_reversal_record_is_on_disk_before_the_first_row_moves(
    root: Path, tmp_path: Path
):
    """It is computed at PLAN time, so nothing about it needs the write to
    have happened -- and writing it last (the first version) meant a crash
    anywhere in the write left a half-rewritten corpus with no row-level
    undo, only a whole-corpus snapshot restore that also discards every
    upload since. `identity/relabel.py` writes its record inside the lock
    for the same reason."""
    store = _ExplodingStore(_full_rows())
    with pytest.raises(RuntimeError, match="share went away"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    assert store.written == []
    files = list(tmp_path.glob("section-path-reversal-*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert [r["chunk_id"] for r in payload["rows"]] == ["doc-a-0001"]
    assert payload["rows"][0]["before"]["text"] == (
        "Table of Contents\nAcupuncture Examiners, Board of"
    )
    # No `.tmp` left beside it -- that reads as corruption to the next person.
    assert list(tmp_path.glob("*.tmp")) == []


class _CorruptingStore(_FakeStore):
    """The write lands and then the stored row is not what was sent."""

    def upsert_chunks(self, name, rows):
        super().upsert_chunks(name, rows)
        for row in self.rows:
            if row["chunk_id"] == "doc-a-0001":
                row["section_path"] = ["NOT WHAT WAS WRITTEN"]


def test_a_failed_verification_still_rebuilds_the_index_and_names_both_restore_points(
    root: Path, tmp_path: Path
):
    """Once a batch has landed the rows exist, so search must be consistent
    with them: skipping the FTS rebuild (the first version did, whenever
    verification raised) leaves every analyst's keyword search silently
    missing those passages. And the message has to tell the operator what
    state the corpus is in, not just which check failed."""
    store = _CorruptingStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    assert "section_path did not land" in message
    assert "1 row(s) in 1 batch(es) are ALREADY written" in message
    assert "snap.zip" in message
    assert "section-path-reversal-budget_chunks-" in message
    assert "WAS rebuilt over them" in message
    assert store.fts_built == ["budget_chunks"]
    assert store.optimized == ["budget_chunks"]


class _VanishedStore(_FakeStore):
    """A planned row is gone by the time the write path fetches it in full
    -- someone re-ingested the document during the (tens of minutes of)
    planning and its chunk_ids changed."""

    def scan(self, name, columns, *, where=None, limit=None):
        out = super().scan(name, columns, where=where, limit=limit)
        if "vector" in columns:
            return [r for r in out if r["chunk_id"] != "doc-a-0001"]
        return out


def test_apply_refuses_when_a_planned_row_vanished_before_the_write(
    root: Path, tmp_path: Path
):
    store = _VanishedStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    assert "rows vanished under the plan" in message
    # The store's row count and the matched count are different questions
    # and are reported separately.
    assert "asked for 1 rows, the store returned 0, of which 0 matched" in message
    assert store.written == []
    assert store.fts_built == []


class _ReingestedBeforeTheLockStore(_FakeStore):
    """An UNTOUCHED document was legitimately re-ingested between the plan
    scan and the lock -- the window is tens of minutes of reading extractor
    JSON off the share, with ingest running on somebody's PC throughout."""

    def __init__(self, rows: list[dict]):
        super().__init__(rows)
        self._drifted = False

    def scan(self, name, columns, *, where=None, limit=None):
        # The first predicate-bearing scan is the untouched-sample baseline,
        # taken under the lock; drift immediately before it answers.
        if where is not None and not self._drifted:
            self._drifted = True
            self.rows[0] = dict(self.rows[0], text="RE-INGESTED BEFORE THE LOCK")
        return super().scan(name, columns, where=where, limit=limit)


def test_an_untouched_row_reingested_before_the_lock_does_not_fail_the_write(
    root: Path, tmp_path: Path
):
    """The sample used to be compared against the PLAN-time rows, so a
    benign concurrent re-ingest of a document this pass never touches would
    have told the operator to restore a snapshot over a completely correct
    write. Reading the baseline lock-to-lock means only this pass's own
    damage can fail it -- which `_DriftingStore` above still proves it does."""
    store = _ReingestedBeforeTheLockStore(_full_rows())
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    assert store._drifted
    assert result.changed == 1
    assert store.fts_built == ["budget_chunks"]


class _FtsExplodingStore(_FakeStore):
    """The rows land, and then the index rebuild itself fails -- an unreachable
    share, or a table another process has open."""

    def build_fts_index(self, name):
        raise RuntimeError("the index rebuild could not open the table")


class _CorruptingFtsExplodingStore(_CorruptingStore):
    """Both at once: verification fails AND the rebuild that runs in the
    `finally` fails too."""

    def build_fts_index(self, name):
        raise RuntimeError("the index rebuild could not open the table")


def test_a_rebuild_failure_does_not_destroy_the_verification_failure_it_ran_after(
    root: Path, tmp_path: Path
):
    """An exception raised inside a `finally` REPLACES whatever was
    propagating. The first version called `build_fts_index` bare in the
    `finally`, so a rebuild failure on the failure path threw the original
    away unchained: the operator saw an FTS error and never learned that
    verification had failed, how many rows had landed, or either restore
    path. Both failures must survive, and so must the hint."""
    store = _CorruptingFtsExplodingStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    # The original failure, not the one the rebuild raised on top of it.
    assert "section_path did not land" in message
    # ...the state of the corpus, which is the dangerous half.
    assert "1 row(s) in 1 batch(es) are ALREADY written" in message
    assert "was NOT rebuilt" in message
    # ...why it was not rebuilt, so the next step is fix-and-rebuild rather
    # than a guess.
    assert "the index rebuild could not open the table" in message
    # ...and both restore points.
    assert "snap.zip" in message
    assert "section-path-reversal-budget_chunks-" in message
    # The chain keeps both exceptions in the order a caller needs them.
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "section_path did not land" in str(caught.value.__cause__)
    assert "the index rebuild could not open the table" in str(
        caught.value.__cause__.__cause__
    )
    assert store.optimized == []


def test_a_rebuild_failure_after_a_clean_write_still_reaches_the_operator(
    root: Path, tmp_path: Path
):
    """Write and verify pass, then the rebuild fails. Nothing else raises on
    that path, so the first version let the bare exception escape with no
    hint at all -- the rows are live behind a stale BM25 index, which is the
    most dangerous state this module can produce, and the operator got no row
    count, no "NOT rebuilt", and neither restore path."""
    store = _FtsExplodingStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    assert "full-text index rebuild failed" in message
    assert "1 row(s) in 1 batch(es) are ALREADY written" in message
    assert "was NOT rebuilt" in message
    assert "snap.zip" in message
    assert "section-path-reversal-budget_chunks-" in message
    assert "the index rebuild could not open the table" in str(caught.value.__cause__)
    # The rows really did land -- this is not a "nothing happened" failure.
    assert [r["chunk_id"] for batch in store.written for r in batch] == ["doc-a-0001"]
    # ...and the remedy is the one this failure actually has. Every row was
    # written AND verified column by column, so a snapshot restore would roll
    # back a correct write plus every upload since, to fix an INDEX. The
    # sentence used to route through `hint()` and offer exactly that.
    assert "Restore from" not in message
    assert "do NOT roll the corpus back" in message
    assert "re-run build_fts_index on budget_chunks by hand" in message
    # The two artefacts are still NAMED (asserted above) as facts, never as
    # the instruction -- and nothing here tells anyone to delete them.
    assert "can be deleted" not in message


def test_a_failure_before_any_upsert_was_attempted_never_tells_the_operator_to_restore(
    root: Path, tmp_path: Path
):
    """A snapshot restore rolls the whole corpus back to the start of this
    pass and discards every upload since. Offering it to undo a write that
    never happened (the first version's wording did) is an enormous, silent
    loss for nothing.

    The store here fails the "rows vanished under the plan" check, which runs
    BEFORE this batch's `upsert_chunks` -- the only shape that really proves
    nothing moved. A store that raises INSIDE `upsert_chunks` does not (see
    `test_a_batch_that_deleted_its_rows_then_failed_...` below): the delete
    and the add are two separate commits."""
    store = _VanishedStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    assert "No write was ever attempted" in message
    assert "the corpus is unchanged" in message
    assert "nothing to undo" in message
    assert "Restore from" not in message
    # ...and it does NOT tell anyone to delete a restore point. That
    # instruction is destructive and irreversible, and the premise it rested
    # on (`rows_written == 0`) was wrong on the half-committed batch below.
    assert "can be deleted" not in message
    assert "unneeded but harmless" in message
    assert store.written == []


class _DeletingThenExplodingStore(_FakeStore):
    """The delete half of `upsert_chunks` commits and the add half never runs.

    This is not a hypothetical: `store/chunk_store.py::upsert_chunks` deletes
    the batch's chunk_ids and then adds the replacements as a SECOND LanceDB
    commit, and says so in a CAUTION comment -- "an interruption between them
    leaves those chunk_ids deleted". A share dropping mid-batch does exactly
    this, and it happens while `rows_written` is still 0.
    """

    def upsert_chunks(self, name, rows):
        gone = {r["chunk_id"] for r in rows}
        self.rows = [r for r in self.rows if r["chunk_id"] not in gone]
        raise RuntimeError("the share went away between the delete and the add")


def test_a_batch_that_deleted_its_rows_then_failed_is_never_reported_as_unchanged(
    root: Path, tmp_path: Path
):
    """`rows_written` is incremented only AFTER `upsert_chunks` RETURNS, so a
    batch that lost its add half leaves rows DELETED from the corpus with the
    counter still reading 0. Treating that 0 as proof of an untouched corpus
    produced two dangerous outputs: a hint telling the operator both restore
    points "can be deleted" -- over a corpus that had just silently lost rows
    -- and a skipped index rebuild, leaving the BM25 index describing rows
    that no longer exist."""
    store = _DeletingThenExplodingStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    # The damage is real: the row is gone from the corpus with no replacement.
    assert "doc-a-0001" not in {r["chunk_id"] for r in store.rows}
    # So the operator is NEVER told the corpus is untouched, and NEVER told to
    # throw away the two things that can put it back.
    assert "the corpus is unchanged" not in message
    assert "can be deleted" not in message
    assert "FAILED PART-WAY" in message
    assert "The corpus is NOT known to be unchanged" in message
    # 🔴 The SNAPSHOT is named as the only way back, and replay is explicitly
    # NOT offered as an equivalent. The reversal record holds `before`/`after`
    # `section_path` and `text` per chunk_id and nothing else (see
    # `_plan_corpus`, which writes it), so replaying it cannot recreate a row
    # the failed batch's delete commit removed -- it can only set values on
    # rows that still exist. The old wording ended "Restore from X or replay
    # Y", handing the operator two options of which one silently cannot work,
    # on the single failure path that has actually lost data.
    assert "snap.zip" in message
    assert "is the ONLY way to bring deleted rows back" in message
    assert "CANNOT recreate a row" in message
    assert "Restore from" not in message
    assert "or replay" not in message
    # The record is still NAMED -- it does restore values on the rows that
    # survived, and an operator may want it later.
    assert "section-path-reversal-budget_chunks-" in message
    # The index is rebuilt on this path too: rows left the table, so the old
    # index describes a corpus that no longer exists.
    assert store.fts_built == ["budget_chunks"]


class _OptimizeExplodingStore(_FakeStore):
    """`build_fts_index` succeeds and `optimize` does not -- old table versions
    stay unpruned, which costs disk and nothing else."""

    def optimize(self, name, *, retention=None):
        raise RuntimeError("optimize could not prune the old versions")


def test_an_optimize_failure_after_a_clean_write_says_the_index_WAS_rebuilt(
    root: Path, tmp_path: Path
):
    """One flag used to be set after BOTH calls, so a failed `optimize` was
    reported as "the index was NOT rebuilt" -- which reads as keyword search
    missing every row this pass wrote, and points at a restore. The index was
    rebuilt; search is correct; only the version pruning failed."""
    store = _OptimizeExplodingStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    assert store.fts_built == ["budget_chunks"]
    # The positive claim is the property; a `"NOT rebuilt" not in message`
    # check alongside it added nothing (it could not fail while this passes)
    # and was case-sensitive, so a future "not rebuilt" would have slipped by
    # it anyway.
    assert "WAS rebuilt over them" in message
    # The optimize failure is its own named fact, with its own remedy.
    assert "optimize could not prune the old versions" in message
    assert "re-run optimize on budget_chunks by hand" in message
    # Never a restore: the rows are written AND verified, and the index is
    # current. (The lede sentence's exact wording is deliberately not pinned --
    # these three properties are what matters about it.)
    assert "Restore from" not in message
    assert "Nothing needs restoring" in message
    assert "do NOT roll the corpus back" in message
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert "optimize could not prune" in str(caught.value.__cause__)
    # The rows really did land.
    assert [r["chunk_id"] for batch in store.written for r in batch] == ["doc-a-0001"]


class _CorruptingCtrlCStore(_CorruptingStore):
    """Verification fails, and then the operator hits Ctrl-C during the index
    rebuild that runs in the `finally`."""

    def build_fts_index(self, name):
        raise KeyboardInterrupt("ctrl-c during the rebuild")


def test_a_ctrl_c_inside_the_rebuild_does_not_replace_the_verification_failure(
    root: Path, tmp_path: Path
):
    """`except Exception` does not catch `KeyboardInterrupt`, so a Ctrl-C in
    the rebuild escaped the handler, escaped the `finally`, and REPLACED the
    propagating verification failure and its hint -- the exact loss that
    try/except exists to stop, arriving on the one interruption an operator
    produces deliberately, at the moment they are most likely to reach for it
    (a long write that has just started printing errors).

    It must not be swallowed either: the run still ends in a raise, and the
    interrupt is on the `__cause__` chain."""
    store = _CorruptingCtrlCStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    # The failure that matters survived, with the state of the corpus.
    assert "section_path did not land" in message
    assert "1 row(s) in 1 batch(es) are ALREADY written" in message
    assert "was NOT rebuilt" in message
    assert "ctrl-c during the rebuild" in message
    assert "snap.zip" in message
    # ...and the interrupt is chained, not lost.
    assert isinstance(caught.value.__cause__.__cause__, KeyboardInterrupt)


class _DeletingThenInterruptedStore(_FakeStore):
    """The delete half of `upsert_chunks` commits and then the operator hits
    Ctrl-C -- the add half never runs and the rows are gone.

    Same damage as `_DeletingThenExplodingStore`, arriving as a
    `KeyboardInterrupt` instead of a `RuntimeError`. That difference used to
    decide whether the operator was told anything at all.
    """

    def upsert_chunks(self, name, rows):
        gone = {r["chunk_id"] for r in rows}
        self.rows = [r for r in self.rows if r["chunk_id"] not in gone]
        raise KeyboardInterrupt("ctrl-c between the delete and the add")


def test_a_ctrl_c_during_the_write_still_reports_that_rows_may_be_deleted(
    root: Path, tmp_path: Path
):
    """The write phase is the 30-60 minute embed: the moment an operator is
    most likely to press Ctrl-C, and the ONLY phase that can leave rows
    deleted. Under `except Exception` the interrupt skipped the hint entirely
    -- the terminal got a bare KeyboardInterrupt with no row count, no "rows
    may be DELETED" and neither restore point, over a corpus that had just
    silently lost rows -- while the `finally` still rebuilt the index and any
    error it recorded was dropped on the floor.

    It must not be swallowed either: the run still ends in a raise and the
    interrupt is on `__cause__`."""
    store = _DeletingThenInterruptedStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    # The damage is real.
    assert "doc-a-0001" not in {r["chunk_id"] for r in store.rows}
    # The operator is told the write was attempted and what that means.
    assert "FAILED PART-WAY" in message
    assert "may now be DELETED" in message
    assert "The corpus is NOT known to be unchanged" in message
    assert "the corpus is unchanged" not in message
    # ...and the snapshot, as the only thing that can bring the rows back.
    assert "snap.zip" in message
    assert "is the ONLY way to bring deleted rows back" in message
    assert "Restore from" not in message
    # The interrupt is chained, not lost, and not re-raised bare.
    assert isinstance(caught.value.__cause__, KeyboardInterrupt)
    # The `finally` still ran: rows left the table, so the old index describes
    # a corpus that no longer exists.
    assert store.fts_built == ["budget_chunks"]


class _CorruptingOptimizeExplodingStore(_CorruptingStore):
    """Verification fails AND the optimize in the `finally` fails too."""

    def optimize(self, name, *, retention=None):
        raise RuntimeError("optimize could not prune the old versions")


def test_a_restore_message_does_not_also_tell_the_operator_to_re_run_optimize(
    root: Path, tmp_path: Path
):
    """Two remedies in one breath -- put the corpus back, and also run a
    maintenance command on it -- is one too many. The version prune is only
    ever the next step once the rows are known good; beside a possible restore
    it is noise. The optimize failure is still REPORTED, because it is a fact
    about the run, just without an instruction attached."""
    store = _CorruptingOptimizeExplodingStore(_full_rows())
    with pytest.raises(RuntimeError) as caught:
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    message = str(caught.value)
    # A restore really is on the table here: the rows landed and were never
    # verified.
    assert "section_path did not land" in message
    assert "Restore from" in message
    # The optimize failure is named, and search is still correct...
    assert "optimize could not prune the old versions" in message
    assert "search is correct" in message
    # ...but no second instruction rides along with the restore.
    assert "re-run optimize" not in message


def _rows_with_many_untouched(count: int = 20) -> list[dict]:
    """`_full_rows()` plus `count` rows of a document the plan skips (no
    cached extractor output), so the untouched sample is big enough for a
    single missing row to sit under the 10% line."""
    rows = _full_rows()
    base = dict(rows[0])
    for i in range(count):
        extra = dict(base)
        extra.update({
            "chunk_id": f"doc-z-{i:04d}", "doc_id": "doc-z", "is_table": False,
            "section_path": ["Z"], "text": f"Z\nrow {i}",
        })
        rows.append(extra)
    return rows


class _SampleReadLosesRowsStore(_FakeStore):
    """The under-lock re-read of the untouched sample loses rows the plan scan
    had seen. Only the FIRST predicate-bearing PLAN_COLUMNS scan is affected --
    that is the baseline read; the full-column fetches and the post-write
    re-read answer normally."""

    def __init__(self, rows: list[dict], *, keep: int | None):
        super().__init__(rows)
        self.keep = keep  # None = drop the lot
        self._baseline_read = False

    def scan(self, name, columns, *, where=None, limit=None):
        out = super().scan(name, columns, where=where, limit=limit)
        if where is not None and "vector" not in columns and not self._baseline_read:
            self._baseline_read = True
            return [] if self.keep is None else out[:self.keep]
        return out


def test_an_untouched_sample_that_came_back_empty_refuses_before_any_write(
    root: Path, tmp_path: Path
):
    """`_untouched_baseline` DROPS rows it cannot re-read, and every later
    comparison iterates the baseline -- so a read that returns nothing leaves
    zero rows to compare and G-T3's second half reports success having looked
    at nothing. A silent no-op that passes is worse than a failure."""
    store = _SampleReadLosesRowsStore(_rows_with_many_untouched(), keep=None)
    with pytest.raises(RuntimeError, match="came back EMPTY"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    # Refused BEFORE the first upsert, so the corpus is untouched.
    assert store.written == []
    assert store.fts_built == []


def test_a_sample_missing_more_than_a_tenth_of_its_rows_refuses_before_any_write(
    root: Path, tmp_path: Path
):
    """21 sampled rows, 3 read back: not a concurrent re-ingest, a read that
    stopped working."""
    store = _SampleReadLosesRowsStore(_rows_with_many_untouched(), keep=3)
    with pytest.raises(RuntimeError, match="could not be re-read under the lock"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    assert store.written == []
    assert store.fts_built == []


def test_the_missing_row_tolerance_floors_at_one_and_keeps_the_live_200_row_line():
    """A bare tenth is under one row on any sample smaller than ten, so a
    single benign concurrent re-ingest -- the exact case the drop exists for
    -- aborted the run purely because the sample was small. That is reachable
    on a `--only` run over a couple of documents. The live 200-row sample is
    unaffected: 20 of 200 is still tolerated and 21 still refuses."""
    assert _missing_tolerance(200) == 20.0
    assert _missing_tolerance(9) == 1.0
    assert _missing_tolerance(3) == 1.0
    assert _missing_tolerance(1) == 1.0


def test_a_tiny_untouched_sample_still_tolerates_one_missing_row(
    root: Path, tmp_path: Path
):
    """Three sampled rows, one gone before the first write. Under a bare tenth
    (0.3) that refused; the write is correct and must happen."""
    store = _SampleReadLosesRowsStore(_rows_with_many_untouched(count=2), keep=2)
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    assert result.changed == 1
    assert [r["chunk_id"] for batch in store.written for r in batch] == ["doc-a-0001"]
    assert store.fts_built == ["budget_chunks"]


def test_an_empty_untouched_sample_that_should_have_existed_refuses_before_any_write(
    root: Path, tmp_path: Path, monkeypatch
):
    """The other way an empty sample arrives: not a read that lost its rows,
    but a DERIVATION that never selected any. The plan scan saw more ids than
    the change set holds, so rows this pass never touches exist -- and an
    empty sample turns spec G-T3's untouched-row half into a check that passes
    having compared nothing.

    Driven by replacing the derivation, because that is precisely what the
    guard protects: today's set difference cannot empty out while the counts
    disagree, and the failure a future edit would introduce is invisible --
    the check it disables still reports success."""
    store = _FakeStore(_full_rows())
    monkeypatch.setattr(
        "chunking.repair_section_paths._untouched_sample_ids",
        lambda before_by_id, changed_ids: [],
    )
    with pytest.raises(RuntimeError, match="EMPTY even though the plan scan saw"):
        repair_section_paths(
            store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
            lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
        )
    # Refused BEFORE the first upsert, so the corpus is untouched.
    assert store.written == []
    assert store.fts_built == []


def test_one_untouched_row_gone_before_the_write_is_still_tolerated(
    root: Path, tmp_path: Path
):
    """The drop exists for a real case -- a document this pass never touches,
    re-ingested during the tens of minutes of planning. One row of 21 must
    still be dropped and the write must still happen; the floor above only
    refuses a sample that has effectively disappeared."""
    store = _SampleReadLosesRowsStore(_rows_with_many_untouched(), keep=20)
    result = repair_section_paths(
        store=store, embedder=_FakeEmbedder(), root=root, dry_run=False,
        lock=_FakeLock(), snapshot_and_verify=lambda: "snap.zip", reversal_dir=tmp_path,
    )
    assert result.changed == 1
    assert [r["chunk_id"] for batch in store.written for r in batch] == ["doc-a-0001"]
    assert store.fts_built == ["budget_chunks"]
