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


class _FakeStore:
    def __init__(self, rows: list[dict]):
        self.rows = rows
        self.written: list[list[dict]] = []
        self.fts_built: list[str] = []
        self.optimized: list[str] = []

    def scan(self, name, columns, *, where=None, limit=None):
        return [{k: r[k] for k in columns if k in r} for r in self.rows]

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
