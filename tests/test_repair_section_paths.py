"""The surgical section_path repair (spec §3)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from chunking.repair_section_paths import (
    PLAN_COLUMNS,
    RowChange,
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
