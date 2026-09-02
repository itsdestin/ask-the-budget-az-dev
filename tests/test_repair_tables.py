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
import yaml

from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.repair_tables import (
    PlanSummary,
    RepairResult,
    TableChange,
    _eval_intersection,
    plan_corpus,
    plan_document,
    repair_tables,
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
        """⚠ `where` is IGNORED except for the `chunk_id IN (...)` predicate.

        Safe for the plan, which passes `is_table = true` and then re-checks
        `is_table` in Python via `in_scope`. Task 9's apply path must not
        inherit that assumption: if it ever relies on a `where` to EXCLUDE
        rows, this fake will hand it the excluded ones and the test will pass
        against code that writes them.
        """
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
    # Every key here is a REAL column of `store/schema.py::chunk_schema`. The
    # first draft carried `agency_canonical_id` (singular), which is not a
    # column at all -- so the D4 pass-through assertion below was checking a
    # field the corpus does not have, and the apply's `all_columns()`
    # round-trip could never have dropped it. A pass-through check over a
    # column that cannot exist proves nothing about the columns that can.
    def _row(**over):
        base = dict(bbox=None, source_anchor=None, fund_canonical_id=None,
                    fund_mentions=["fund:general"], publisher="jlbc",
                    agency_canonical_ids=["agency:axs"], vector=[0.0] * 4)
        base.update(over)
        return base

    rows = [
        _row(chunk_id=f"{DOC}-0000", doc_id=DOC, fiscal_year=2026, doc_type="approps-per-agency", page=1,
             is_table=True, section_path=["FY 2026 Budget"], text=stored, table_html=CLEAN_HTML,
             token_count=10),
        _row(chunk_id=f"{ADC}-0000", doc_id=ADC, fiscal_year=2025,
             doc_type="approps-per-agency", page=1, is_table=True, section_path=["FY 2025 Budget"],
             text=_build_text(mineru, ["FY 2025 Budget"]), table_html=CLEAN_HTML, token_count=10,
             agency_canonical_ids=["agency:adc"]),
        _row(chunk_id=f"{DOC}-0002", doc_id=DOC, fiscal_year=2026, doc_type="approps-per-agency", page=6,
             is_table=True, section_path=["Summary"], text="Summary\nTable 1\tx\ty", table_html="<table></table>",
             token_count=3),
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


# CLEAN_HTML with the two spending rows FUSED into one — the defect this
# whole pass exists for, and (unlike the clean table, whose HTML happens to
# round-trip byte-identically) a table whose rebuild is visibly different
# from what MinerU stored. Without that difference a parity assertion cannot
# tell the rebuilt table from the stored one.
FUSED_HTML = CLEAN_HTML.replace(
    "<tr><td>Personal Services</td><td>100</td><td>200</td><td>300</td></tr>"
    "<tr><td>Equipment</td><td>50</td><td>50</td><td>50</td></tr>",
    "<tr><td>Personal Services Equipment</td><td>100 50</td><td>200 50</td><td>300 50</td></tr>",
)


def test_a_rebuilt_chunk_is_byte_identical_to_a_re_chunk_through_the_one_producer(corpus):
    """Spec D7: the repair must equal what ingest would now produce. The one
    producer is `MinerUReader(source_pdf=…)` (Task 7) — if the plan's own
    text ever drifts from it, the corpus and a re-ingest disagree."""
    root, store = corpus
    page = root / "extractor-output" / DOC / "page-1.json"
    page.write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": FUSED_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")
    store.rows[0]["table_html"] = FUSED_HTML
    store.rows[0]["text"] = _build_text(MinerUReader().read(page).tables[0], ["FY 2026 Budget"])

    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    produced = MinerUReader(source_pdf=root / "pdfs" / "axs.pdf").read(page).tables[0]
    assert c.source == "extractor"
    assert c.new_text == _build_text(produced, ["FY 2026 Budget"])
    assert c.new_html == produced.html
    # ...and the rebuild really is a change, or the assertions above would
    # hold just as well against MinerU's own stored table.
    assert c.new_html != c.old_html and c.new_text != c.old_text
    assert c.rows_before == 10 and c.rows_after == 11 and c.merged_cells_removed == 3


def test_extractor_output_that_does_not_match_the_chunk_falls_back_to_html(corpus):
    root, store = corpus
    (root / "extractor-output" / DOC / "page-1.json").write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": "<table><tr><td>Different</td><td>1</td></tr></table>",
                    "bbox": [0, 0, 1, 1]}],
    }), encoding="utf-8")
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "html" and c.note == "extractor output differs from the stored text"
    # The refusal class stays a class of its own — a note prefixed onto it
    # would split "rebuilt" across as many keys as there are notes.
    assert c.reason == "rebuilt" and c.verdict == "rebuilt"
    assert summary.notes[c.note] == 1 and summary.reasons["rebuilt"] == 2


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
    """Spec §3.1 step 8a is its own refusal class — the region landed on a
    different table — so the dry run has to be able to report it apart from
    an arithmetic failure. That needs the number carried onto the change."""
    root, store = corpus
    _one_page_pdf(_substituted_page).save(str(root / "pdfs" / "adc.pdf"))
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == ADC)
    assert c.verdict == "unverified" and c.reason.startswith("figure retention")
    assert c.figure_retention < 0.5
    assert summary.reasons[c.reason] == 1
    rebuilt = next(x for x in changes if x.doc_id == DOC)
    assert rebuilt.figure_retention == 1.0 and rebuilt.anchor_match == 1.0


MILLION_HTML = (
    "<table><tr><td></td><td>FY 2024 ACTUAL</td><td>FY 2025 ESTIMATE</td><td>FY 2026 APPROVED</td></tr>"
    "<tr><td>OPERATING BUDGET</td><td></td><td></td><td></td></tr>"
    "<tr><td>Full Time Equivalent Positions</td><td>10.0</td><td>10.0</td><td>12.0</td></tr>"
    # `3,000,0003/` — MinerU glues the 6-pt superscript footnote marker, which
    # JLBC prints to the right of the LAST column, onto that column's figure,
    # so the marker's digits read as part of the money (spec §1).
    "<tr><td>Personal Services</td><td>1,000,000</td><td>2,000,000</td><td>3,000,0003/</td></tr>"
    # The vision model read one digit wrong (spec D2). Its own arithmetic is
    # never checked, so nothing in the corpus can currently see this.
    "<tr><td>Equipment</td><td>500,001</td><td>500,000</td><td>500,000</td></tr>"
    "<tr><td>OPERATING SUBTOTAL</td><td>1,500,000</td><td>2,500,000</td><td>3,500,000</td></tr>"
    "<tr><td>AGENCY TOTAL</td><td>1,500,000</td><td>2,500,000</td><td>3,500,000</td></tr>"
    "<tr><td>FUND SOURCES</td><td></td><td></td><td></td></tr>"
    "<tr><td>General Fund</td><td>1,500,000</td><td>2,500,000</td><td>3,500,000</td></tr>"
    "<tr><td>SUBTOTAL - Appropriated Funds</td><td>1,500,000</td><td>2,500,000</td><td>3,500,000</td></tr>"
    "<tr><td>TOTAL - ALL SOURCES</td><td>1,500,000</td><td>2,500,000</td><td>3,500,000</td></tr></table>"
)


def _million_page(b: PageBuilder) -> None:
    """What the PDF actually prints: Equipment is 500,000 in every column."""
    b.header()
    b.row("OPERATING BUDGET")
    b.row("Full Time Equivalent Positions", "10.0", "10.0", "12.0")
    b.row("Personal Services", "1,000,000", "2,000,000", "3,000,000", marker="3/")
    b.row("Equipment", "500,000", "500,000", "500,000")
    b.row("OPERATING SUBTOTAL", "1,500,000", "2,500,000", "3,500,000", x0=61)
    b.row("AGENCY TOTAL", "1,500,000", "2,500,000", "3,500,000")
    b.row("FUND SOURCES")
    b.row("General Fund", "1,500,000", "2,500,000", "3,500,000")
    b.row("SUBTOTAL - Appropriated Funds", "1,500,000", "2,500,000", "3,500,000", x0=61)
    b.row("TOTAL - ALL SOURCES", "1,500,000", "2,500,000", "3,500,000")


def test_a_digit_the_vision_model_got_wrong_is_reported(corpus):
    """The headline evidence of the dry run: where MinerU's digits and the
    printed page disagree, and by how much. A disagreement is only counted
    on a table that PASSED the gate — an unverified table's figures are
    not evidence of anything."""
    root, store = corpus
    _one_page_pdf(_million_page).save(str(root / "pdfs" / "adc.pdf"))
    parsed = MinerUReader._parse_html_table(MILLION_HTML, page=1, bbox=None)
    store.rows[1]["table_html"] = MILLION_HTML
    store.rows[1]["text"] = _build_text(parsed, ["FY 2025 Budget"])

    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == ADC)
    assert c.verdict == "rebuilt"
    assert c.digit_disagreements == ["-500,001"]     # MinerU's digit, gone
    equipment = next(l for l in c.new_text.split("\n") if l.startswith("Equipment"))
    assert equipment == "Equipment\t500,000\t500,000\t500,000"   # the printed figures
    assert summary.digit_disagreements == 1
    # The fused marker is peeled off its figure, and counted.
    assert "3,000,000 [3/]" in c.new_text and c.notes_separated == 1


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
    # Its own words: this is not "the output differs", it is "there was
    # nothing to look the output up by".
    assert c.note == "chunk_id carries no positional index"


def test_eval_intersection_reports_whether_the_anchor_survived(tmp_path):
    """G-OT2: a ground-truth chunk in scope must still contain its anchor."""
    queries = tmp_path / "queries.yaml"
    queries.write_text(
        "- id: q-001\n"
        "  expected_chunks:\n"
        "    - chunk_id: a-0000\n"
        "      anchor_text: Personal Services\n"
        "    - chunk_id: b-0000\n"
        "      anchor_text: '500,001'\n"
        "    - chunk_id: c-0000\n"
        "      anchor_text: '500,001'\n",
        encoding="utf-8",
    )
    changes = [
        TableChange(chunk_id="a-0000", doc_id="a", fiscal_year=2026, verdict="rebuilt",
                    reason="rebuilt", note="", source="extractor", anchor_match=1.0, figure_retention=1.0,
                    rows_before=3, rows_after=3, merged_cells_removed=0, notes_separated=0,
                    digit_disagreements=[], old_text="old", new_text="Personal Services\t1",
                    old_html=None, new_html=None),
        # Unverified: the corpus KEEPS `old_text`, so that is what its anchor
        # is graded against — grading it against a rebuild that was refused
        # would report every refusal as a lost anchor.
        TableChange(chunk_id="b-0000", doc_id="b", fiscal_year=2026, verdict="unverified",
                    reason="arithmetic", note="", source="html", anchor_match=1.0, figure_retention=1.0,
                    rows_before=3, rows_after=0, merged_cells_removed=0, notes_separated=0,
                    digit_disagreements=[], old_text="Equipment\t500,001", new_text=None,
                    old_html=None, new_html=None),
        TableChange(chunk_id="c-0000", doc_id="c", fiscal_year=2026, verdict="rebuilt",
                    reason="rebuilt", note="", source="html", anchor_match=1.0, figure_retention=1.0,
                    rows_before=3, rows_after=3, merged_cells_removed=0, notes_separated=0,
                    digit_disagreements=[], old_text="Equipment\t500,001",
                    new_text="Equipment\t500,000", old_html=None, new_html=None),
    ]
    out = _eval_intersection(changes, queries)
    assert out == [
        {"query": "q-001", "chunk_id": "a-0000", "verdict": "rebuilt", "anchor_found": True},
        {"query": "q-001", "chunk_id": "b-0000", "verdict": "unverified", "anchor_found": True},
        # The one real G-OT2 finding: a rebuild that dropped a ground-truth anchor.
        {"query": "q-001", "chunk_id": "c-0000", "verdict": "rebuilt", "anchor_found": False},
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


def test_figures_that_identify_a_cell_come_from_the_figure_columns_only(corpus):
    """`_figures_in` feeds the digit-disagreement report, so a number inside a
    ROW LABEL must not be read as a figure — `Proposition 204 Protection` and
    `Ch. 1,000` are labels, and a set difference over them would report a
    disagreement nobody can act on."""
    from chunking.repair_tables import _figures_in

    text = "FY 2026 Budget\nCh. 1,000 Protection\t2,500,000\t10.0"
    assert _figures_in(text) == {"2,500,000", "10.0"}


def test_the_sidecars_recorded_extraction_method_picks_the_reading_on_disk(corpus):
    """`ingest/extract_dirs.py`: for a document ingested since Plan B the
    reading the corpus holds lives under its method's own folder, and which
    folder must never be guessed. Without the method the page file is
    invisible and the chunk silently drops to the html fallback."""
    root, store = corpus
    ext = root / "extractor-output" / DOC
    (ext / "mineru").mkdir()
    (ext / "page-1.json").rename(ext / "mineru" / "page-1.json")
    docs = json.loads((root / "documents.json").read_text())
    docs[DOC]["extraction"] = {"method": "mineru"}
    (root / "documents.json").write_text(json.dumps(docs), encoding="utf-8")

    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "extractor" and c.verdict == "rebuilt"


def test_extractor_output_that_cannot_be_READ_says_so_instead_of_reading_as_absent(corpus):
    """A half-written extractor directory must not look like a document that
    never had one — the dry run's `html` count is read as "no cached output",
    and a silent read failure would inflate it."""
    root, store = corpus
    (root / "extractor-output" / DOC / "page-2.json").write_text("{ truncated", encoding="utf-8")
    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "html" and "extractor output unreadable" in c.note
    assert c.reason == "rebuilt"
    assert summary.notes[c.note] == 1


def test_the_html_fallback_also_matches_the_one_producer(corpus):
    """The other half of spec D7. ~398 documents have no cached extractor
    output at all, so their table is rebuilt from the stored `table_html` —
    a different SOURCE reaching the same refinement. If that path ever
    diverged, four hundred documents would hold text no re-ingest reproduces
    and nothing on the extractor path would notice."""
    root, store = corpus
    store.rows[1]["table_html"] = FUSED_HTML
    store.rows[1]["text"] = _build_text(
        MinerUReader._parse_html_table(FUSED_HTML, page=1, bbox=None), ["FY 2025 Budget"])

    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.doc_id == ADC)
    assert c.source == "html" and c.note == ""      # nothing cached, the ordinary case

    # What ingest would now write for the same table and the same PDF.
    page = root / "extractor-output" / ADC / "page-1.json"
    page.parent.mkdir(parents=True)
    page.write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": FUSED_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")
    produced = MinerUReader(source_pdf=root / "pdfs" / "adc.pdf").read(page).tables[0]

    assert c.new_text == _build_text(produced, ["FY 2025 Budget"])
    assert c.new_html == produced.html
    assert c.new_html != c.old_html and c.merged_cells_removed == 3


def test_a_chunk_with_no_section_path_is_planned_from_its_header_row_down(corpus):
    """79.4% of the live in-scope rows (3,870 of 4,875, measured 2026-09-01)
    carry an EMPTY section_path, so `_build_text` emits no section line and
    `_body` strips the HEADER row instead. Both sides of the body gate are
    built the same way, so the comparison still holds — this pins that, and
    pins that line 0 of the rebuilt text is then the header, not a blank."""
    root, store = corpus
    mineru = MinerUReader().read(root / "extractor-output" / DOC / "page-1.json").tables[0]
    store.rows[0]["section_path"] = []
    store.rows[0]["text"] = _build_text(mineru, [])

    changes, _ = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "extractor" and c.verdict == "rebuilt"
    assert not c.new_text.startswith("\n")
    assert c.new_text.split("\n")[0] == "\tFY 2024 ACTUAL\tFY 2025 ESTIMATE\tFY 2026 APPROVED"
    assert c.new_text == _build_text(
        MinerUReader(source_pdf=root / "pdfs" / "axs.pdf").read(
            root / "extractor-output" / DOC / "page-1.json").tables[0], [])


def test_a_recorded_reading_that_is_not_on_disk_is_its_own_finding(corpus):
    """`ingest/extract_dirs.py` refuses to fall back to another folder when
    the sidecar's method names a reading that is not there — the corpus holds
    a reading nobody can produce. That must not be counted as one of the
    ~398 documents that were simply never cached."""
    root, store = corpus
    docs = json.loads((root / "documents.json").read_text())
    docs[DOC]["extraction"] = {"method": "mineru-ocr"}      # no such folder on disk
    (root / "documents.json").write_text(json.dumps(docs), encoding="utf-8")

    changes, summary = plan_corpus(store, root, "budget_chunks")
    c = next(x for x in changes if x.chunk_id == f"{DOC}-0000")
    assert c.source == "html"
    assert c.note == "the recorded reading (mineru-ocr) has no folder on disk"
    assert summary.notes[c.note] == 1
    # ...and the document that genuinely has nothing cached carries no note,
    # so the two are countable apart.
    assert next(x for x in changes if x.doc_id == ADC).note == ""


def test_the_summary_reports_how_much_ground_truth_it_actually_covers(corpus):
    """G-OT2 reads as five times stronger than it is unless both numbers are
    carried: measured live 2026-09-01, ONE of the 51 ground-truth chunk ids
    in eval/queries.yaml is in this pass's scope."""
    root, store = corpus
    _, summary = plan_corpus(store, root, "budget_chunks")
    # Counted here by parsing the query set directly, so this cannot pass by
    # agreeing with the same helper it is checking, and does not go red the
    # day somebody adds a query.
    expected = sum(len(q.get("expected_chunks") or [])
                   for q in yaml.safe_load(Path("eval/queries.yaml").read_text(encoding="utf-8")))
    assert summary.eval_ground_truth_total == expected >= 51
    assert len(summary.eval_intersection) == 0      # the fixture holds no ground-truth id


# --- the apply (spec §6.4–6.6) ----------------------------------------------
#
# The write half mirrors `chunking/repair_section_paths.py`'s, which went
# through four review rounds of its own; the rules it bought are re-asserted
# here because they are properties of THIS pass too, not of that module --
# a reversal record on disk before the first row moves, a hint that never
# claims "unchanged" over a half-committed batch, an index rebuilt even when
# verification failed, and an untouched sample that cannot empty itself and
# report success.


class _FakeEmbedder:
    dim = 4

    def __init__(self):
        self.calls: list[tuple[list[str], str]] = []

    def embed_batch(self, texts, *, input_type="document"):
        self.calls.append((list(texts), input_type))
        return [[float(len(t)), 0.0, 0.0, 0.0] for t in texts]


class _FakeLock:
    def __init__(self):
        self.entered = 0

    def __enter__(self):
        self.entered += 1
        return self

    def __exit__(self, *a):
        return False


def _apply(root, store, **over):
    kw = dict(store=store, embedder=_FakeEmbedder(), root=root, dry_run=False, lock=_FakeLock(),
              snapshot_and_verify=lambda: "lancedb-test.zip", reversal_dir=root)
    kw.update(over)
    return repair_tables(**kw)


def _reversal_files(root: Path) -> list[Path]:
    return sorted(root.glob("table-rebuild-reversal-*.json"))


def _defective(root: Path, store: "_FakeStore") -> "_FakeStore":
    """Both in-scope tables carrying the fused row this pass exists to fix.

    The fixture's CLEAN table round-trips byte-identically through the
    rebuild (`test_a_rebuilt_chunk_is_byte_identical_...` relies on the same
    fact from the other side), so an apply test built on it would be
    asserting a "rewrite" that writes the same bytes back -- structurally
    unable to tell a working write from a no-op. The brief's own apply tests
    were written against the clean fixture and failed on exactly that.
    """
    page = root / "extractor-output" / DOC / "page-1.json"
    page.write_text(json.dumps({
        "extractor": "mineru-3.1.6", "page": 1,
        "blocks": [{"type": "table", "table_body": FUSED_HTML, "bbox": [78, 85, 918, 907]}],
    }), encoding="utf-8")
    store.rows[0]["table_html"] = FUSED_HTML
    store.rows[0]["text"] = _build_text(MinerUReader().read(page).tables[0], ["FY 2026 Budget"])
    store.rows[1]["table_html"] = FUSED_HTML
    store.rows[1]["text"] = _build_text(
        MinerUReader._parse_html_table(FUSED_HTML, page=1, bbox=None), ["FY 2025 Budget"])
    return store


def test_dry_run_writes_nothing(corpus):
    root, store = corpus
    result = repair_tables(store=store, embedder=_FakeEmbedder(), root=root, dry_run=True)
    assert isinstance(result, RepairResult)
    assert result.written == 0 and store.written == [] and store.fts_built == []
    assert result.snapshot_name is None and result.reversal_path is None
    assert _reversal_files(root) == [] and len(result.changes) == 2


def test_apply_rewrites_only_the_four_columns_and_rebuilds_fts(corpus):
    root, store = corpus
    _defective(root, store)
    before = {r["chunk_id"]: dict(r) for r in store.rows}
    lock = _FakeLock()
    emb = _FakeEmbedder()
    result = _apply(root, store, lock=lock, embedder=emb)
    assert result.written == 2 and lock.entered == 1 and result.skipped_moved == []
    assert store.fts_built == ["budget_chunks"] and store.optimized == ["budget_chunks"]
    assert emb.calls and all(kind == "document" for _, kind in emb.calls)
    after = {r["chunk_id"]: r for r in store.rows}
    for cid, was in before.items():
        now = after[cid]
        if cid == f"{DOC}-0002":
            assert now == was                                       # out of scope: untouched
            continue
        assert now["text"] != was["text"] and now["table_html"] != was["table_html"]
        assert now["vector"] != was["vector"] and now["token_count"] > 0
        # D4: chunk boundaries never move, and no stamp column is re-derived.
        for col in ("chunk_id", "doc_id", "page", "section_path", "bbox", "source_anchor",
                    "agency_canonical_ids", "fund_canonical_id", "fund_mentions",
                    "fiscal_year", "doc_type", "is_table", "publisher"):
            assert now[col] == was[col]


def test_apply_skips_a_row_whose_text_moved_and_counts_it(corpus):
    root, store = corpus
    _defective(root, store)

    class MovedStore(_FakeStore):
        def scan(self, name, columns, *, where=None, limit=None):
            out = super().scan(name, columns, where=where, limit=limit)
            if "vector" in columns:                                  # the apply-time read
                for r in out:
                    if r["chunk_id"] == f"{DOC}-0000":
                        r["text"] = r["text"] + "\nmoved"
            return out

    moved = MovedStore(store.rows)
    result = _apply(root, moved)
    assert result.written == 1 and result.skipped_moved == [f"{DOC}-0000"]
    # The row that moved keeps what the re-ingest put there -- never the
    # planned rewrite, which was computed against text that is now stale.
    assert moved.rows[0]["table_html"] == FUSED_HTML


def test_reversal_record_round_trips(corpus):
    root, store = corpus
    _defective(root, store)
    before = {r["chunk_id"]: dict(r) for r in store.rows}
    result = _apply(root, store)
    payload = json.loads(Path(result.reversal_path).read_text())
    assert payload["snapshot"] == "lancedb-test.zip" and payload["table"] == "budget_chunks"
    assert {r["chunk_id"] for r in payload["rows"]} == {f"{DOC}-0000", f"{ADC}-0000"}
    for r in payload["rows"]:
        assert r["before"]["text"] == before[r["chunk_id"]]["text"]
        assert r["before"]["table_html"] == before[r["chunk_id"]]["table_html"]
        assert r["after"]["text"] != r["before"]["text"]


def test_second_plan_after_apply_finds_nothing_to_rebuild(corpus):
    """Rehearsal step 2: after the apply the dry run reports nothing left --
    the rebuilt text reconciles and has no merged cell, and rebuilding it
    again reproduces itself."""
    root, store = corpus
    _defective(root, store)
    before = {r["chunk_id"]: r["text"] for r in store.rows}
    _apply(root, store)
    changes, _ = plan_corpus(store, root, "budget_chunks")
    assert changes and all(c.verdict == "rebuilt" and c.new_text == c.old_text for c in changes)
    # ...and the first pass really did change something, or "nothing left to
    # rebuild" would be true of a pass that did nothing.
    assert all(c.old_text != before[c.chunk_id] for c in changes)


def test_nothing_to_rebuild_takes_no_lock_and_no_snapshot(corpus, monkeypatch):
    """A snapshot zips the whole corpus under the lock and takes minutes.
    Spending that on a no-op is what teaches an operator to skip it."""
    import chunking.repair_tables as rt

    root, store = corpus
    monkeypatch.setattr(rt, "refine_operating_table",
                        lambda t, p: (_ for _ in ()).throw(RuntimeError("kaboom")))
    lock = _FakeLock()
    snapshots: list[str] = []
    result = _apply(root, store, lock=lock,
                    snapshot_and_verify=lambda: snapshots.append("x") or "x")
    assert result.written == 0 and lock.entered == 0 and snapshots == []
    assert store.written == [] and store.fts_built == [] and _reversal_files(root) == []


def test_the_reversal_record_is_on_disk_before_the_first_row_moves(corpus):
    """`identity/relabel.py`'s order. Written last (the sketch's order), a
    crash anywhere in the write leaves the corpus half-rewritten with no
    row-level undo at all -- only a whole-corpus restore, which also throws
    away every upload since."""
    root, store = corpus
    seen: list[list[Path]] = []

    class _WatchingStore(_FakeStore):
        def upsert_chunks(self, name, rows):
            seen.append(_reversal_files(root))
            super().upsert_chunks(name, rows)

    _apply(root, _WatchingStore(store.rows))
    assert seen and all(files for files in seen)


def test_a_half_committed_batch_never_reads_as_an_unchanged_corpus(corpus):
    """`upsert_chunks` is a delete commit then a SEPARATE add commit, so a
    batch that raised may have taken its rows OUT with no replacement while
    the written counter is still 0. The hint must say so, must name the
    snapshot as the only recovery, and must never tell the operator the
    restore points can be deleted."""
    root, store = corpus

    class _ExplodingStore(_FakeStore):
        def upsert_chunks(self, name, rows):
            raise RuntimeError("share went away")

    with pytest.raises(RuntimeError) as excinfo:
        _apply(root, _ExplodingStore(store.rows), batch_size=1)
    message = str(excinfo.value)
    assert "may now be DELETED" in message
    assert "lancedb-test.zip" in message and "ONLY way to bring deleted rows back" in message
    assert "can be deleted" not in message and "Leave them in place" not in message
    assert "table-rebuild-reversal-" in message
    # ...and the reversal record is named for what it really holds here:
    # text and table_html, never the section_path column of the other pass.
    assert "section_path" not in message and "table_html" in message


def test_the_index_is_rebuilt_even_when_verification_fails(corpus):
    """Once any batch has landed the rows exist and search must be
    consistent with them: leaving the index un-rebuilt is a worse state
    than the one that raised."""
    root, store = corpus

    class _CorruptingStore(_FakeStore):
        def upsert_chunks(self, name, rows):
            rows = [dict(r) for r in rows]
            rows[0]["publisher"] = "somebody else"      # a pass-through column moved
            super().upsert_chunks(name, rows)

    corrupting = _CorruptingStore(store.rows)
    with pytest.raises(RuntimeError) as excinfo:
        _apply(root, corrupting)
    assert "publisher" in str(excinfo.value)
    assert corrupting.fts_built == ["budget_chunks"]
    assert "WAS rebuilt over them" in str(excinfo.value)


def test_an_fts_failure_after_a_clean_write_says_so_and_never_asks_for_a_restore(corpus):
    root, store = corpus

    class _FtsExplodingStore(_FakeStore):
        def build_fts_index(self, name):
            raise RuntimeError("index locked")

    with pytest.raises(RuntimeError) as excinfo:
        _apply(root, _FtsExplodingStore(store.rows))
    message = str(excinfo.value)
    assert "rebuild failed AFTER the rows were written" in message
    assert "do NOT roll the corpus back" in message
    assert "re-run build_fts_index" in message


def test_a_keyboard_interrupt_in_the_write_still_reports_the_state(corpus):
    """`except Exception` let a Ctrl-C reach the terminal bare -- no row
    count, no 'rows may be DELETED', neither restore point -- on the one
    interruption an operator produces deliberately."""
    root, store = corpus

    class _InterruptedStore(_FakeStore):
        def upsert_chunks(self, name, rows):
            raise KeyboardInterrupt

    with pytest.raises(RuntimeError) as excinfo:
        _apply(root, _InterruptedStore(store.rows))
    assert "may now be DELETED" in str(excinfo.value)
    assert isinstance(excinfo.value.__cause__, KeyboardInterrupt)


def test_an_untouched_sample_that_comes_back_empty_refuses_before_writing(corpus):
    """An empty sample is not a passing check, it is an absent one: every
    later comparison iterates it, so zero rows means zero assertions and the
    untouched half of the verify reports success having looked at nothing."""
    from chunking.repair_tables import UNTOUCHED_SAMPLE_COLUMNS

    root, store = corpus

    class _BlindStore(_FakeStore):
        def scan(self, name, columns, *, where=None, limit=None):
            if list(columns) == UNTOUCHED_SAMPLE_COLUMNS:
                return []
            return super().scan(name, columns, where=where, limit=limit)

    blind = _BlindStore(store.rows)
    with pytest.raises(RuntimeError, match="EMPTY"):
        _apply(root, blind)
    assert blind.written == []          # refused BEFORE the first row moved


def test_a_row_that_vanished_under_the_plan_refuses_rather_than_writing_the_rest(corpus):
    """A chunk_id the store no longer returns is not a benign event -- the
    plan is stale. Told apart from a row whose TEXT moved, which is skipped
    and counted."""
    root, store = corpus

    class _VanishedStore(_FakeStore):
        def scan(self, name, columns, *, where=None, limit=None):
            out = super().scan(name, columns, where=where, limit=limit)
            if "vector" in columns and where:
                out = [r for r in out if r["chunk_id"] != f"{DOC}-0000"]
            return out

    with pytest.raises(RuntimeError, match="vanished"):
        _apply(root, _VanishedStore(store.rows))
