"""The one-time repair of JLBC agency operating tables (spec §6), and the
gate calibration that precedes it (spec §4.1).

    JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables --calibrate
    JLBC_DATA_DIR=data/insight-data uv run python -m chunking.repair_tables            # dry run
    JLBC_DATA_DIR=<copy>            uv run python -m chunking.repair_tables --apply

Nothing here writes without `--apply`, and `--apply` writes only under
the ingest lock after a CRC-verified snapshot.
"""
from __future__ import annotations

import argparse
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.text_layer_table import refine_operating_table
from chunking.table_gate import has_fused_marker, has_merged_cell, reconcile
from chunking.table_text import OPERATING_TABLE_DOC_TYPES, figure_tokens, has_ladder_marker
from chunking.repair_common import ChunkStoreLike
from ingest.extract_dirs import resolve_extract_dir

log = logging.getLogger(__name__)

# The repo's own copy of the Layer 1 ground truth, resolved from THIS file
# rather than the working directory: `_eval_intersection` is the G-OT2 check,
# and a relative "eval/queries.yaml" silently returns "no ground truth in
# scope" when the pass is run from anywhere but the repo root -- a gate that
# reports a clean sweep because it could not find the file it grades.
EVAL_QUERIES = Path(__file__).resolve().parent.parent / "eval" / "queries.yaml"

PLAN_COLUMNS = ["chunk_id", "doc_id", "fiscal_year", "doc_type", "page", "section_path", "text", "table_html"]


def in_scope(row: Mapping[str, Any]) -> bool:
    """Spec D1."""
    return bool(row.get("is_table")) and row.get("doc_type") in OPERATING_TABLE_DOC_TYPES and has_ladder_marker(row.get("text") or "")


def table_rows(text: str) -> list[list[str]]:
    """The tab-joined rows of a stored chunk text (line 0 and a caption have no tabs)."""
    return [line.split("\t") for line in text.split("\n") if "\t" in line]


def calibrate(store: ChunkStoreLike, table: str = "budget_chunks") -> dict[int, dict[str, int]]:
    """Spec §4.1: run the gate over the tables MinerU already read cleanly
    (no merged cell, no fused marker) exactly as stored. Every failure
    here is the RULE's, so this is run before any rebuild code exists.
    Returns {fiscal_year: {"clean": n, "passed": n}}."""
    rows = store.scan(table, ["chunk_id", "doc_type", "fiscal_year", "is_table", "text"],
                      where="is_table = true")
    per_year: dict[int, dict[str, int]] = defaultdict(lambda: {"clean": 0, "passed": 0})
    for r in rows:
        if not in_scope(r):
            continue
        cells = table_rows(r["text"])
        if has_merged_cell(cells) or has_fused_marker(cells):
            continue
        year = int(r["fiscal_year"] or 0)
        per_year[year]["clean"] += 1
        if reconcile(cells).passed:
            per_year[year]["passed"] += 1
    return dict(per_year)


def _print_calibration(per_year: Mapping[int, Mapping[str, int]]) -> None:
    total_clean = sum(v["clean"] for v in per_year.values())
    total_pass = sum(v["passed"] for v in per_year.values())
    print(f"{'year':>6} {'clean':>7} {'passed':>7} {'rate':>6}")
    for year in sorted(per_year):
        v = per_year[year]
        rate = v["passed"] / v["clean"] if v["clean"] else 0.0
        print(f"{year:>6} {v['clean']:>7} {v['passed']:>7} {rate:>6.1%}")
    print(f"{'all':>6} {total_clean:>7} {total_pass:>7} {(total_pass / total_clean if total_clean else 0):>6.1%}")


# --- the plan (spec §6.1) ----------------------------------------------------

@dataclass
class TableChange:
    """One in-scope table chunk, and what the repair would do to it.

    Spec D4: only `text`, `table_html`, `token_count` and `vector` are ever
    written, so nothing here proposes a `chunk_id`, a page, a bbox, a
    section_path or a stamp column. `verdict == "unverified"` means the
    chunk KEEPS what it has (spec D3) and is COUNTED under `reason` -- the
    number this pass reports is "tables we could not verify", never "tables
    changed".
    """
    chunk_id: str
    doc_id: str
    fiscal_year: int
    verdict: str            # "rebuilt" | "unverified"
    # ONE refusal class per refusal (`rebuilt`, `arithmetic`, `no text layer`,
    # `no source pdf`, `figure retention 12%`, ...), so `PlanSummary.reasons`
    # counts refusals per class. Provenance -- where this table was read from
    # and why -- is `note`, and it is deliberately NOT folded in here: a note
    # prefix would split one refusal class across as many counter keys as
    # there are provenance stories, and the dry run reports refusal classes.
    reason: str
    note: str               # provenance; "" when the extractor path was used
    source: str             # "extractor" | "html"
    anchor_match: float
    # How much of MinerU's own figure evidence the rebuild kept. Carried
    # rather than recomputed because a refusal BELOW
    # `text_layer_table.MIN_FIGURE_RETENTION` is its own failure class --
    # the region landed on a different table, which the arithmetic gate
    # structurally cannot see -- and the dry run has to be able to report
    # that class separately from an arithmetic failure. 1.0 when the
    # refinement never got far enough to measure it.
    figure_retention: float
    rows_before: int
    rows_after: int
    # Cells in MINERU's stored table carrying two figures at once -- the
    # defect this whole pass exists for. A rebuilt table cannot contain one
    # (`_rows` refuses a column holding two figures), so on a `rebuilt` row
    # this is exactly what the rebuild removed; on an `unverified` row it is
    # what stays wrong in the corpus.
    merged_cells_removed: int
    notes_separated: int
    digit_disagreements: list[str]
    old_text: str
    new_text: str | None
    old_html: str | None
    new_html: str | None


@dataclass
class PlanSummary:
    per_year: dict[int, dict[str, int]] = field(default_factory=dict)
    reasons: Counter = field(default_factory=Counter)
    sources: Counter = field(default_factory=Counter)
    # Why a chunk did not use its document's cached extractor output. Empty
    # for every chunk that did. `sources["html"]` counts the fallback; this
    # says WHICH fallback, and in particular tells a document that was never
    # cached (no note) from one whose recorded reading is missing on disk.
    notes: Counter = field(default_factory=Counter)
    match_rates: list[float] = field(default_factory=list)
    digit_disagreements: int = 0
    eval_intersection: list[dict[str, Any]] = field(default_factory=list)
    # How many ground-truth chunk ids `eval/queries.yaml` holds in total.
    # Printed BESIDE `len(eval_intersection)` so G-OT2 cannot read as
    # stronger than it is -- see `_eval_intersection`.
    eval_ground_truth_total: int = 0


def _chunk_index(chunk_id: str) -> int | None:
    """The positional index a chunk_id encodes (`{doc_id}-{idx:04d}`), or
    None when it encodes none.

    None rather than a raised exception because this index is used for ONE
    thing -- finding the matching table in the cached extractor output --
    and a corpus-wide pass must not abort on one odd row (the section-path
    pass's rule). Losing the index costs that chunk the extractor path and
    nothing else: it falls back to its own stored `table_html`.
    """
    try:
        return int(chunk_id.rsplit("-", 1)[1])
    except (IndexError, ValueError):
        return None


def _figures_in(text: str) -> set[str]:
    """Comma-grouped or decimal figures only -- the ones that identify a cell.

    Cell 0 of every line is skipped: it is the label column, and a label
    like `Proposition 204 Protection` carries a bare number that is not a
    figure. A bare figure (`100`, `0`) is skipped too -- it is not
    distinctive enough for a set difference to mean anything.
    """
    out: set[str] = set()
    for line in text.split("\n"):
        for cell in line.split("\t")[1:]:
            out.update(t for t in figure_tokens(cell) if "," in t or "." in t)
    return out


def _body(text: str) -> str:
    """Everything below line 0 of a stored chunk text.

    Line 0 is USUALLY the section path, which this pass never touches (spec
    D4) and which the section-path repair owns. It is not always: measured
    on the live corpus 2026-09-01, **3,870 of the 4,875 in-scope rows (79.4%)
    carry an EMPTY `section_path`**, and `table_chunk._build_text` opens with
    `if section_path:` -- so for four rows in five there is no section line
    and this strips the table's HEADER row instead.

    That is still self-consistent, which is why the comparison it feeds is
    sound: both sides of `_body(_build_text(table, path)) == _body(old_text)`
    are built by the same `_build_text` from the same path, so they drop the
    same line. But be clear about what the gate is worth on those rows: it
    compares one row FEWER than it appears to, and the row it stops comparing
    is the header. It cannot, on an empty-path chunk, catch cached extractor
    output that differs from the corpus only in its header row.
    """
    return "\n".join(text.split("\n")[1:])


def plan_document(
    doc_id: str,
    rows: list[Mapping[str, Any]],
    root: Path,
    *,
    pdf_path: Path | None,
    method: str | None = None,
) -> list[TableChange]:
    """Spec §3.2 (repair): the MinerU `Table` comes from cached extractor
    output when it exists AND reproduces the stored text; otherwise from
    the stored `table_html`. Either way the same refinement runs.

    WHY this calls `refine_operating_table` and not `MinerUReader(source_pdf=…)`,
    which spec D5 makes the ONE producer of a rebuilt table: the producer
    refines in place and returns only the winning table. This pass has to
    report, per chunk, WHY a table was refused (spec D3 counts refusals by
    reason) and what MinerU's own table looked like before the rebuild
    (rows_before, merged cells, digit disagreements) -- both of which the
    producer discards. It calls the producer's own refinement function, on
    the table objects the producer would have refined, so the OUTPUT is the
    producer's.

    WHAT THE PARITY TESTS PIN, EXACTLY, so nobody reads more into them:
    `tests/test_repair_tables.py` runs `MinerUReader(source_pdf=…)` over one
    table on each of the two source paths (cached extractor output, and the
    stored-html fallback ~398 uncached documents take) and asserts this
    plan's `new_text` and `new_html` are byte-identical to it. That is an
    equality of OUTPUT on a rebuilt table. It says nothing about SELECTION,
    and selection already differs: `MinerUReader._refine_operating_tables`
    qualifies a table on its ladder marker alone, while `in_scope` also
    requires `OPERATING_TABLE_DOC_TYPES` (spec D1). Measured on the live
    corpus 2026-09-01: of 4,986 table chunks carrying a ladder marker,
    **111 are outside this pass -- 98 `detailed-list-pdf` and 13
    `topic-pdf`** -- and the producer WOULD rebuild all 111 at re-ingest.
    So after this repair those 111 chunks still hold MinerU's own table and
    would change if their document were ever re-ingested. That is a known
    gap in spec D7's "the repair equals a re-chunk", not something these
    tests cover.

    `method` is the sidecar's `extraction.method` -- it picks WHICH reading
    on disk is the one the corpus holds. See `ingest/extract_dirs.py` for
    why that must never be guessed from folder names.
    """
    import fitz

    tables: list | None = None
    # Why the extractor path was not available for this whole document. ""
    # means "no cached extractor output at all", which is the ordinary case
    # for the ~398 documents that have none -- every OTHER way of not having
    # it gets its own words, because each is a different thing to go and fix.
    doc_note = ""
    located = resolve_extract_dir(doc_id, root, method=method)
    if located is not None:
        try:
            tables = MinerUReader().read(located[0]).tables
        except Exception as exc:  # noqa: BLE001 -- recorded per chunk below, never fatal
            tables, doc_note = None, f"extractor output unreadable: {exc}"
    else:
        base = root / "extractor-output" / doc_id
        if method and base.is_dir() and not (base / method).is_dir():
            # `ingest/extract_dirs.py` calls this a FINDING and refuses to fall
            # back to another folder: the sidecar says the corpus holds this
            # reading and the reading is not on disk. Counted apart from
            # never-cached so the dry run does not bury it in that number.
            doc_note = f"the recorded reading ({method}) has no folder on disk"
        elif base.is_dir():
            doc_note = "cached extractor output has no readable page files"

    out: list[TableChange] = []
    pdf = fitz.open(str(pdf_path)) if pdf_path is not None and pdf_path.exists() else None
    try:
        for row in rows:
            idx = _chunk_index(str(row["chunk_id"]))
            section_path = list(row.get("section_path") or [])
            old_text = str(row.get("text") or "")
            # Three separate things can send a chunk to the html fallback
            # even though its document HAS cached output, and they were one
            # sentence until the review: a chunk_id with no index (nothing to
            # look up), an index past the end (the output holds fewer tables
            # than the corpus does), and a real body mismatch (the output on
            # disk is not what was ingested). Same fallback, three different
            # findings, so three different sentences.
            table, source, note = None, "html", doc_note
            if tables is not None:
                if idx is None:
                    note = "chunk_id carries no positional index"
                elif idx >= len(tables):
                    note = (f"cached extractor output holds {len(tables)} tables; "
                            f"this chunk is #{idx}")
                elif _body(_build_text(tables[idx], section_path)) != _body(old_text):
                    # The positional chunk->table mapping is a hypothesis
                    # about what was ingested, not a fact about what is on
                    # disk now. Recorded rather than trusted; the stored HTML
                    # always is what the corpus holds.
                    note = "extractor output differs from the stored text"
                else:
                    table, source, note = tables[idx], "extractor", ""
            if table is None:
                table = MinerUReader._parse_html_table(
                    str(row.get("table_html") or ""), page=int(row.get("page") or 1), bbox=None)

            if pdf is None:
                outcome_table, reason, match, retention = None, "no source pdf", 0.0, 1.0
            else:
                try:
                    outcome = refine_operating_table(table, pdf)
                except Exception as exc:  # noqa: BLE001
                    # Same containment argument as
                    # `MinerUReader._refine_operating_tables`: one table that
                    # raises must cost that table its repair, never its
                    # siblings or the rest of a 7,500-document pass. Logged
                    # with the traceback so a systematic failure is findable.
                    log.warning("refinement raised on %s; counting it unverified",
                                row["chunk_id"], exc_info=True)
                    outcome_table, reason, match, retention = None, f"refinement raised: {exc}", 0.0, 1.0
                else:
                    outcome_table, reason = outcome.table, outcome.reason
                    match, retention = outcome.anchor_match, outcome.figure_retention

            before_cells = [[c.text for c in r.cells] for r in table.rows]
            change = TableChange(
                chunk_id=str(row["chunk_id"]), doc_id=doc_id, fiscal_year=int(row.get("fiscal_year") or 0),
                verdict="rebuilt" if outcome_table is not None else "unverified",
                reason=reason, note=note, source=source, anchor_match=match, figure_retention=retention,
                rows_before=len(table.rows), rows_after=len(outcome_table.rows) if outcome_table else 0,
                merged_cells_removed=sum(1 for r in before_cells for c in r[1:] if len(figure_tokens(c)) >= 2),
                notes_separated=0, digit_disagreements=[],
                old_text=old_text, new_text=None, old_html=row.get("table_html"), new_html=None,
            )
            if outcome_table is not None:
                change.new_text = _build_text(outcome_table, section_path)
                change.new_html = outcome_table.html
                # `table_text.peel_markers` renders every footnote marker as
                # ` [3/]`, so this counts the markers whose digits no longer
                # touch a figure's digits.
                change.notes_separated = change.new_text.count(" [")
                old_f, new_f = _figures_in(old_text), _figures_in(change.new_text)
                change.digit_disagreements = (sorted(f"-{f}" for f in old_f - new_f)
                                              + sorted(f"+{f}" for f in new_f - old_f))
            out.append(change)
    finally:
        if pdf is not None:
            pdf.close()
    return out


def _ground_truth_anchors(queries_path: Path = EVAL_QUERIES) -> list[tuple[str, str, str]]:
    """(query_id, chunk_id, anchor_text) for every expected chunk in the
    Layer 1 query set. 51 of them on 2026-09-01."""
    if not queries_path.exists():
        return []
    return [(q["id"], exp.get("chunk_id"), exp.get("anchor_text") or "")
            for q in yaml.safe_load(queries_path.read_text(encoding="utf-8")) or []
            for exp in q.get("expected_chunks") or []]


def _eval_intersection(changes: list[TableChange], queries_path: Path = EVAL_QUERIES) -> list[dict[str, Any]]:
    """G-OT2: the ground-truth chunks in scope must still contain their anchor_text.

    An unverified chunk is graded against the text it KEEPS, which is the
    honest comparison -- the corpus still holds `old_text` for it. The
    consequence is that G-OT2 can only ever FAIL on a chunk this pass
    actually rebuilt.

    HOW SMALL THIS GATE IS, measured rather than assumed. The spec names five
    in-scope ground-truth ids; run against the live corpus 2026-09-01,
    **exactly ONE of the 51 ground-truth chunk ids in `eval/queries.yaml`
    enters `changes`** -- `jlbc-approps-fy2025-unibor-0000`. The other four
    the spec names sit in in-scope DOCUMENT TYPES but are not operating
    tables and carry no ladder marker, so `in_scope` never admits them, and
    reading them says the filter is right:

      * `jlbc-baseline-fy2026-adc-0004`  "Table 1 FY 2024 Community
        Corrections Program Expenditures"
      * `jlbc-approps-fy2023-adc-0008`   "Table 4 Florence Prison Closure
        3-Year Budget Plan"
      * `jlbc-baseline-fy2027-des-0010`  an Auditor General "SUMMARY OF
        FUNDS" table
      * `jlbc-baseline-fy2022-dhs-0006`  a COVID-19 expenditure table

    None of them is the agency operating table this pass rebuilds, so none of
    them is evidence about it either way. `PlanSummary` therefore carries
    `eval_ground_truth_total` beside this list, and Task 10 must print BOTH --
    "1 of 51" is the true strength of this gate, and a bare list of one
    passing row reads like five times more assurance than exists.
    """
    by_id = {c.chunk_id: c for c in changes}
    out: list[dict[str, Any]] = []
    for query_id, chunk_id, anchor in _ground_truth_anchors(queries_path):
        c = by_id.get(chunk_id)
        if c is None:
            continue
        out.append({"query": query_id, "chunk_id": c.chunk_id, "verdict": c.verdict,
                    "anchor_found": anchor in (c.new_text or c.old_text)})
    return out


def plan_corpus(
    store: ChunkStoreLike,
    root: Path,
    table: str,
    *,
    only: set[str] | None = None,
    progress: Callable[[str], None] | None = None,
) -> tuple[list[TableChange], PlanSummary]:
    """Every in-scope operating table, and what the repair would do to it.

    Writes nothing and takes no lock -- the same dry-run asymmetry
    `chunking/repair_section_paths.py` documents, so this can be re-run by
    hand against the live corpus as often as anyone wants before an apply
    is approved.
    """
    progress = progress or (lambda m: print(m, flush=True))
    from app.routes.pdf import _resolve_blob   # the one resolver for `source_blob_path` (data dir, repo, flat pdfs/)
    from store.documents import load_documents

    docs = load_documents()
    rows = [r for r in store.scan(table, PLAN_COLUMNS + ["is_table"], where="is_table = true")
            if in_scope(r)]
    if only:
        rows = [r for r in rows if r["doc_id"] in only]
    by_doc: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for r in rows:
        by_doc[str(r["doc_id"])].append(r)
    progress(f"scanned {len(rows)} in-scope tables across {len(by_doc)} documents")

    changes: list[TableChange] = []
    summary = PlanSummary()
    for n, (doc_id, doc_rows) in enumerate(sorted(by_doc.items()), start=1):
        rec = docs.get(doc_id) or {}
        # A document with no `source_blob_path`, or whose PDF is not on this
        # machine, gets `None` and every one of its tables is counted under
        # "no source pdf" -- a finding, not a silent skip.
        #
        # 🔴 RUN THIS PASS FROM THE MAIN CHECKOUT, NOT A WORKTREE. Many
        # sidecar entries record a REPO-relative `data/cached-pdfs/<shard>/
        # <sha>.pdf`, and `_resolve_blob`'s second candidate is
        # `app.routes.pdf.REPO_ROOT / <that path>` -- the checkout the code is
        # running from. A git worktree does not carry that (gitignored)
        # download cache. Measured 2026-09-01: from the `agency-tables-t8`
        # worktree **342 of the 4,875 in-scope rows (329 documents) report
        # "no source pdf"**; with REPO_ROOT pointed at the main checkout,
        # **4,875 of 4,875 resolve**. Nothing is wrong with those documents,
        # and the difference is invisible in the output -- it reads as 342
        # tables this pass cannot repair.
        pdf_path = _resolve_blob(str(rec.get("source_blob_path") or ""))
        method = (rec.get("extraction") or {}).get("method")
        for c in plan_document(doc_id, doc_rows, root, pdf_path=pdf_path, method=method):
            changes.append(c)
            y = summary.per_year.setdefault(c.fiscal_year, {"tables": 0, "rebuilt": 0, "unverified": 0})
            y["tables"] += 1
            y[c.verdict] += 1
            summary.reasons[c.reason] += 1
            summary.sources[c.source] += 1
            if c.note:
                summary.notes[c.note] += 1
            summary.match_rates.append(c.anchor_match)
            summary.digit_disagreements += len(c.digit_disagreements)
        if n % 200 == 0:
            progress(f"planned {n}/{len(by_doc)} documents")
    summary.eval_intersection = _eval_intersection(changes)
    summary.eval_ground_truth_total = len(_ground_truth_anchors())
    return changes, summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--table", default="budget_chunks", choices=("budget_chunks",))
    parser.add_argument("--calibrate", action="store_true", help="spec §4.1: gate the stored clean tables, write nothing")
    args = parser.parse_args(argv)
    from store.chunk_store import ChunkStore
    store = ChunkStore(create=False)
    if args.calibrate:
        _print_calibration(calibrate(store, args.table))
        return 0
    parser.error("only --calibrate exists yet; the dry run arrives with Task 8")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
