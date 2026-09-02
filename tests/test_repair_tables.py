"""chunking/repair_tables.py — spec §6. A fake store that APPLIES writes
(the section-path plan's lesson), a synthetic PDF, and a MinerU page file.

Every page here is built with PyMuPDF at the real coordinates measured off
the AHCCCS FY2026 baseline page — the helpers are `tests/test_text_layer_table.py`'s,
imported rather than re-typed so the two suites cannot disagree about what a
printed operating table looks like.
"""
from __future__ import annotations

import json
from pathlib import Path

import fitz
import pytest

from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.repair_tables import (
    PlanSummary,
    TableChange,
    _eval_intersection,
    plan_corpus,
    plan_document,
)
from tests.test_text_layer_table import CLEAN_HTML, PageBuilder, _clean_page

DOC = "jlbc-approps-fy2026-axs"
ADC = "jlbc-approps-fy2025-adc"


class _FakeStore:
    """The section-path plan's fake, which APPLIES its writes — a fake that
    accepts a write and forgets it cannot tell a plan (which must write
    nothing) from an apply."""

    def __init__(self, rows):
        self.rows = [dict(r) for r in rows]
        self.written: list[list[dict]] = []
        self.fts_built: list[str] = []
        self.optimized: list[str] = []

    def scan(self, name, columns, *, where=None, limit=None):
        out = [{c: r.get(c) for c in columns} for r in self.rows]
        if where and "chunk_id IN" in where:
            wanted = {p.strip().strip("'") for p in where.split("(", 1)[1].rstrip(")").split(",")}
            out = [r for r in out if r["chunk_id"] in wanted]
        return out

    def upsert_chunks(self, name, rows):
        rows = list(rows)
        self.written.append(rows)
        by_id = {r["chunk_id"]: r for r in rows}
        self.rows = [dict(by_id.get(r["chunk_id"], r)) for r in self.rows]

    def build_fts_index(self, name):
        self.fts_built.append(name)

    def optimize(self, name, *, retention=None):
        self.optimized.append(name)


def _one_page_pdf(builder=_clean_page) -> fitz.Document:
    pdf = fitz.open()
    builder(PageBuilder(pdf))
    return pdf


@pytest.fixture()
def corpus(tmp_path, monkeypatch):
    """One in-scope document with cached extractor output and its PDF; one
    in-scope document with NO extractor output (the html fallback); one
    out-of-scope table chunk that must never be touched."""
    root = tmp_path
    monkeypatch.setenv("JLBC_DATA_DIR", str(root))
    pdf = _one_page_pdf()
    pdfs = root / "pdfs"
    pdfs.mkdir()
    pdf.save(str(pdfs / "axs.pdf"))
    pdf.save(str(pdfs / "adc.pdf"))
    ext = root / "extractor-output" / DOC
    ext.mkdir(parents=True)
    (ext / "page-1.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": CLEAN_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")
    (root / "documents.json").write_text(json.dumps({
        DOC: {"doc_type": "approps-per-agency", "fiscal_year": 2026, "source_blob_path": "pdfs/axs.pdf"},
        ADC: {"doc_type": "approps-per-agency", "fiscal_year": 2025, "source_blob_path": "pdfs/adc.pdf"},
    }), encoding="utf-8")
    mineru = MinerUReader().read(ext / "page-1.json").tables[0]
    stored = _build_text(mineru, ["FY 2026 Budget"])
    rows = [
        dict(chunk_id=f"{DOC}-0000", doc_id=DOC, fiscal_year=2026, doc_type="approps-per-agency", page=1,
             is_table=True, section_path=["FY 2026 Budget"], text=stored, table_html=CLEAN_HTML,
             token_count=10, vector=[0.0] * 4, agency_canonical_id="agency:axs"),
        dict(chunk_id=f"{ADC}-0000", doc_id=ADC, fiscal_year=2025,
             doc_type="approps-per-agency", page=1, is_table=True, section_path=["FY 2025 Budget"],
             text=_build_text(mineru, ["FY 2025 Budget"]), table_html=CLEAN_HTML, token_count=10,
             vector=[0.0] * 4, agency_canonical_id="agency:adc"),
        dict(chunk_id=f"{DOC}-0002", doc_id=DOC, fiscal_year=2026, doc_type="approps-per-agency", page=6,
             is_table=True, section_path=["Summary"], text="Summary\nTable 1\tx\ty", table_html="<table></table>",
             token_count=3, vector=[0.0] * 4, agency_canonical_id="agency:axs"),
    ]
    return root, _FakeStore(rows)


def test_plan_reads_extractor_output_first_and_falls_back_to_html(corpus):
    root, store = corpus
    changes, summary = plan_corpus(store, root, "budget_chunks")
    by_id = {c.chunk_id: c for c in changes}
    assert set(by_id) == {f"{DOC}-0000", f"{ADC}-0000"}   # the Summary table is out of scope
    assert by_id[f"{DOC}-0000"].source == "extractor"
    assert by_id[f"{ADC}-0000"].source == "html"
    assert all(c.verdict == "rebuilt" for c in changes)
    assert summary.sources == {"extractor": 1, "html": 1}
    assert summary.per_year[2026] == {"tables": 1, "rebuilt": 1, "unverified": 0}
    assert store.written == []                      # a plan writes nothing


def test_plan_rows_keep_line_zero_and_report_row_counts(corpus):
    root, store = corpus
    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.new_text.split("\n")[0] == "FY 2026 Budget"        # D4: line 0 untouched
    assert c.rows_after >= c.rows_before
    assert c.merged_cells_removed == 0 and c.digit_disagreements == []
    assert c.new_html.startswith("<table><tr><td></td><td>FY 2024 ACTUAL")


def test_a_rebuilt_chunk_is_byte_identical_to_a_re_chunk_through_the_one_producer(corpus):
    """Spec D7: the repair must equal what ingest would now produce. The one
    producer is `MinerUReader(source_pdf=…)` (Task 7) — if the plan's own
    text ever drifts from it, the corpus and a re-ingest disagree."""
    root, store = corpus
    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    produced = MinerUReader(source_pdf=root / "pdfs" / "axs.pdf").read(
        root / "extractor-output" / DOC / "page-1.json").tables[0]
    assert c.new_text == _build_text(produced, ["FY 2026 Budget"])
    assert c.new_html == produced.html


def test_extractor_output_that_does_not_match_the_chunk_falls_back_to_html(corpus):
    root, store = corpus
    (root / "extractor-output" / DOC / "page-1.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": "<table><tr><td>Different</td><td>1</td></tr></table>",
                    "bbox": [0, 0, 1, 1]}],
    }), encoding="utf-8")
    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "html" and "extractor output differs" in c.reason
    assert c.verdict == "rebuilt"          # the fallback still rebuilds


def test_unverifiable_table_is_counted_not_rewritten(corpus):
    root, store = corpus
    blank = fitz.open()
    blank.new_page()
    blank.save(str(root / "pdfs" / "adc.pdf"))      # a page with no text layer
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == ADC)
    assert c.verdict == "unverified" and c.reason == "no text layer" and c.new_text is None
    assert c.old_text and c.old_html                # what the corpus keeps (D3)
    assert summary.per_year[2025] == {"tables": 1, "rebuilt": 0, "unverified": 1}
    assert summary.reasons["no text layer"] == 1


def test_a_missing_source_pdf_is_a_counted_refusal_not_a_crash(corpus):
    root, store = corpus
    (root / "pdfs" / "adc.pdf").unlink()
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == ADC)
    assert c.verdict == "unverified" and c.reason == "no source pdf" and c.new_text is None
    assert summary.reasons["no source pdf"] == 1


def _substituted_page(b: PageBuilder) -> None:
    """The same printed labels as `_clean_page` carrying DIFFERENT figures
    that still reconcile — the shape the arithmetic gate structurally cannot
    see, and the one `figure_retention` exists for (spec §3.1 step 8a)."""
    b.header()
    b.row("OPERATING BUDGET")
    b.row("Full Time Equivalent Positions", "10.0", "10.0", "12.0")
    b.row("Personal Services", "111", "222", "333")
    b.row("Equipment", "55", "66", "77")
    b.row("OPERATING SUBTOTAL", "166", "288", "410", x0=61)
    b.row("AGENCY TOTAL", "166", "288", "410")
    b.row("FUND SOURCES")
    b.row("General Fund", "166", "288", "410")
    b.row("SUBTOTAL - Appropriated Funds", "166", "288", "410", x0=61)
    b.row("TOTAL - ALL SOURCES", "166", "288", "410")


def test_a_figure_retention_refusal_is_carried_and_counted_by_reason(corpus):
    """The reviewer's ask: the dry run must be able to report the figure
    retention refusal class, so the number has to survive onto the change."""
    root, store = corpus
    _one_page_pdf(_substituted_page).save(str(root / "pdfs" / "adc.pdf"))
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == ADC)
    assert c.verdict == "unverified" and c.reason.startswith("figure retention")
    assert c.figure_retention < 0.5
    assert summary.reasons[c.reason] == 1
    rebuilt = next(x for x in changes if x.doc_id == DOC)
    assert rebuilt.figure_retention == 1.0 and rebuilt.anchor_match == 1.0


def test_a_refinement_that_raises_costs_one_table_not_the_run(corpus, monkeypatch):
    """D3, and `MinerUReader._refine_operating_tables`' own argument: one bad
    table must never take down the pass its siblings are in."""
    import chunking.repair_tables as rt

    root, store = corpus

    def _boom(table, pdf):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(rt, "refine_operating_table", _boom)
    changes, _ = plan_corpus(store, root, "budget_chunks")
    assert len(changes) == 2
    assert all(c.verdict == "unverified" for c in changes)
    assert all("refinement raised" in c.reason and c.new_text is None for c in changes)


def test_a_malformed_chunk_id_falls_back_to_html_instead_of_crashing(corpus):
    """A corpus-wide pass may not abort on one odd row (the section-path
    pass's rule); the positional extractor lookup is what needs the index,
    so losing it costs the extractor path and nothing else."""
    root, store = corpus
    store.rows[0]["chunk_id"] = f"{DOC}-odd"
    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-odd")
    assert c.source == "html" and c.verdict == "rebuilt"


def test_eval_intersection_reports_whether_the_anchor_survived(tmp_path):
    """G-OT2: a ground-truth chunk in scope must still contain its anchor."""
    queries = tmp_path / "queries.yaml"
    queries.write_text(
        "- id: q-001\n"
        "  expected_chunks:\n"
        "    - chunk_id: a-0000\n"
        "      anchor_text: Personal Services\n"
        "    - chunk_id: b-0000\n"
        "      anchor_text: Nowhere\n",
        encoding="utf-8",
    )
    changes = [
        TableChange(chunk_id="a-0000", doc_id="a", fiscal_year=2026, verdict="rebuilt",
                    reason="rebuilt", source="extractor", anchor_match=1.0, figure_retention=1.0,
                    rows_before=3, rows_after=3, merged_cells_removed=0, notes_separated=0,
                    digit_disagreements=[], old_text="old", new_text="Personal Services\t1",
                    old_html=None, new_html=None),
        TableChange(chunk_id="b-0000", doc_id="b", fiscal_year=2026, verdict="unverified",
                    reason="arithmetic", source="html", anchor_match=1.0, figure_retention=1.0,
                    rows_before=3, rows_after=0, merged_cells_removed=0, notes_separated=0,
                    digit_disagreements=[], old_text="old", new_text=None,
                    old_html=None, new_html=None),
    ]
    out = _eval_intersection(changes, queries)
    assert out == [
        {"query": "q-001", "chunk_id": "a-0000", "verdict": "rebuilt", "anchor_found": True},
        {"query": "q-001", "chunk_id": "b-0000", "verdict": "unverified", "anchor_found": False},
    ]


def test_only_restricts_the_plan_to_named_documents(corpus):
    root, store = corpus
    changes, summary = plan_corpus(store, root, "budget_chunks", only={ADC})
    assert [c.doc_id for c in changes] == [ADC]
    assert isinstance(summary, PlanSummary) and 2026 not in summary.per_year


def test_plan_document_is_callable_on_one_document(corpus):
    root, store = corpus
    rows = [r for r in store.rows if r["doc_id"] == DOC and r["page"] == 1]
    out = plan_document(DOC, rows, root, pdf_path=root / "pdfs" / "axs.pdf")
    assert [c.chunk_id for c in out] == [f"{DOC}-0000"]
    assert out[0].verdict == "rebuilt" and out[0].source == "extractor"
