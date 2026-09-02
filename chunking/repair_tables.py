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
import math
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Mapping

import yaml

from chunking.builders._tokens import count_tokens
from chunking.builders.table_chunk import _build_text
from chunking.readers.mineru_reader import MinerUReader
from chunking.readers.text_layer_table import refine_operating_table
from chunking.table_gate import has_fused_marker, has_merged_cell, reconcile
from chunking.table_text import OPERATING_TABLE_DOC_TYPES, figure_tokens, has_ladder_marker
from chunking.repair_common import (
    ChunkStoreLike,
    EmbedderLike,
    all_columns,
    atomic_write_json,
    default_snapshot_and_verify,
    in_list,
    reversal_stamp,
)
# WHY this pass imports the section-path repair's write machinery instead of
# re-typing it (spec D7, "reused here, not rebuilt"): every name below is
# column-agnostic and was bought by four rounds of review on that branch.
# `_WriteState` is the operator-facing state machine -- what landed, whether
# the index was rebuilt, and which restore point to reach for -- and getting
# any of its branches subtly wrong is how an operator is told a half-written
# corpus is "unchanged". `_passthrough_mismatch` compares a re-read row
# against what was SENT, over `all_columns()`, which is exactly the D4 check
# this pass needs; a second copy would drift the day a column is added.
# They are private to that module only in the sense that no CLI calls them;
# they could not be moved into `repair_common.py` without editing a file
# this task may not touch.
from chunking.repair_section_paths import (
    UNCHANGED_SAMPLE_SIZE,
    _WriteState,
    _missing_tolerance,
    _norm,
    _passthrough_mismatch,
)
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


# --- the apply (spec §6.4-6.6) ----------------------------------------------

# Rows re-embedded and written per batch. Smaller than the section-path
# pass's 2000 because `upsert_chunks` deletes a batch's chunk_ids and adds
# the replacements in a SEPARATE commit (`store/chunk_store.py`'s CAUTION
# comment), so the batch size is exactly how many rows a crash between the
# two can leave deleted -- and this pass touches ~4,900 rows in total, so a
# smaller bound costs a handful of extra scans and nothing else.
DEFAULT_BATCH_SIZE = 500

# The four columns this pass rewrites (spec D4). Everything else -- chunk_id,
# page, bbox, section_path, every stamp column -- is passed through by value
# and verified byte-identical afterwards.
WRITTEN_COLUMNS = ("text", "table_html", "token_count", "vector")

# What the untouched-row sample is re-read with. Deliberately NOT
# `all_columns()`: `vector` is 768 float32s on every row and round-trips
# through Arrow, so it is both expensive to pull off the share and not
# comparable by equality. These are the columns this pass could plausibly
# damage on a row it never meant to touch.
UNTOUCHED_SAMPLE_COLUMNS = ["chunk_id", "doc_id", "text", "table_html",
                            "token_count", "section_path", "page", "is_table"]


@dataclass
class RepairResult:
    """What the pass did. `written` is rows actually written, never rows
    planned -- `skipped_moved` is the difference, and Task 10's CLI prints
    both because a large skip count means the plan is stale, not that the
    corpus is clean."""
    changes: list[TableChange]
    summary: PlanSummary
    written: int = 0
    skipped_moved: list[str] = field(default_factory=list)
    snapshot_name: str | None = None
    reversal_path: Path | None = None


@dataclass
class _TableWriteState(_WriteState):
    """`_WriteState` with the two sentences that are specific to this pass.

    Everything else -- the counters, `state_sentence()`, the index phrase,
    the no-write and verified branches of `remedy()` -- is inherited
    unchanged, because it is about what happened to the corpus and not about
    which columns moved.

    `reversal_exact` is the one piece of state `_WriteState` has no reason to
    carry: the section-path pass RAISES on a row whose text moved, so its
    reversal record always describes exactly what it wrote. This pass SKIPS
    such a row, so a record still at `stage: "planned"` lists rows that were
    never written -- and replaying one of those would put the stale plan-time
    table back over the fresh re-ingest that caused the skip. Until the
    record has been rewritten with the rows really written, it is not safe to
    replay and the remedy must name the snapshot only.

    The half-committed-batch branch is restated for the same class of reason:
    it names what the record holds, and the section-path wording says
    `section_path` and `text` where this pass writes `text` and
    `table_html`. Handing an operator a false description of the file they
    are about to replay is worst on the one path that has actually lost data.
    """

    reversal_exact: bool = False
    record_error: BaseException | None = None

    def remedy(self) -> str:
        if self.batches_attempted and self.batches_written < self.batches_attempted and not self.verified:
            return (
                f"{self._snapshot_phrase()} is the ONLY way to bring deleted rows "
                f"back; the reversal record at {self.reversal_path} carries a "
                "before/after text and table_html per chunk_id and nothing else "
                "(no vector, no token_count, no agency or fund stamps, no other "
                "column), so replaying it restores values on rows that still exist "
                "and CANNOT recreate a row that the failed batch removed."
            )
        if self.batches_attempted and not self.reversal_exact:
            correct = ("The rows are correct and verified, so do NOT roll the corpus "
                       "back. " if self.verified else "")
            return (
                f"{correct}The reversal record at {self.reversal_path} could NOT be "
                "rewritten after the write, so it still lists every row the PLAN would "
                "have rebuilt -- including any the compare-and-swap skipped because the "
                "corpus had moved under the plan. Do NOT replay it: a skipped row's "
                "`before` would write a stale table back over a fresh re-ingest. "
                f"{self._snapshot_phrase()} is the only safe way back."
            )
        return super().remedy()


def _reversal_rows(
    changes: list[TableChange],
    overwritten: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """The row-level undo: what each rebuilt chunk held, and what it becomes.

    `overwritten` is what the row really held when the lock was won, keyed by
    chunk_id, and it WINS over the plan-time values. The compare-and-swap
    guards `text` only, so `table_html` can legitimately have moved between
    the plan (read tens of minutes earlier, off the share) and the write --
    and a record carrying the plan-time HTML would replay markup that was
    never in the corpus. Absent (the pre-write `planned` record, which is
    written before any row is fetched in full), the plan-time values are all
    there is, which is part of why that record is marked not-replay-safe.

    `token_count` and `vector` are deliberately absent. Both are DERIVED
    from `text` (`count_tokens`, and the embedder), so a replay recomputes
    them; carrying 768 floats per row for ~4,900 rows would make the record
    a ~30 MB file on the share for values that are reproducible from the two
    fields above it.
    """
    out: list[dict[str, Any]] = []
    for c in changes:
        was = (overwritten or {}).get(c.chunk_id)
        out.append({"chunk_id": c.chunk_id, "doc_id": c.doc_id,
                    "before": {"text": was["text"] if was else c.old_text,
                               "table_html": was["table_html"] if was else c.old_html},
                    "after": {"text": c.new_text, "table_html": c.new_html}})
    return out


def _write_changed_rows(
    store: ChunkStoreLike,
    table: str,
    changes: list[TableChange],
    embedder: EmbedderLike,
    batch_size: int,
    progress: Callable[[str], None],
    state: _TableWriteState,
    written: list[dict[str, Any]],
    skipped: list[str],
    overwritten: dict[str, dict[str, Any]],
) -> None:
    """Fetch each rebuilt row in full, rewrite four columns, embed, write.

    `written`, `skipped` and `overwritten` are filled IN PLACE rather than
    returned, because every one of them is needed on the failure path too:
    the reversal record is rewritten with the rows really written and the
    ids really skipped before any post-write failure is raised, and a
    returned value is lost the moment this function raises.

    Per-row compare-and-swap (spec §6.4): the plan was computed BEFORE the
    lock -- planning reads thousands of documents' cached extractor output
    and their PDFs off the share and takes tens of minutes -- so each row's
    stored `text` must still be the `old_text` the rebuild was verified
    against. A document re-ingested in that window keeps its chunk_ids and
    changes its text, and writing the planned rebuild over it would put a
    stale table back into a freshly-read document.

    WHY a moved row is SKIPPED and counted here where the section-path pass
    RAISES: that pass rewrites one line of every table in a document, so a
    moved row means the document's whole chunk<->table mapping is stale and
    nothing about it can be trusted. This pass verifies each table
    arithmetically on its own, so one stale row costs exactly that row its
    repair and says nothing about its neighbours. It is still reported --
    a large `skipped_moved` means the plan is stale and should be re-run,
    not that the corpus is clean.

    A chunk_id the store does not return at all is a different thing and
    does raise: the row is GONE, so the plan is not merely stale, and
    continuing would write the rest of a plan built against a corpus that
    no longer exists.
    """
    by_id = {c.chunk_id: c for c in changes}
    ordered = sorted(by_id)
    total_batches = math.ceil(len(ordered) / batch_size) if ordered else 0
    for batch_num, start in enumerate(range(0, len(ordered), batch_size), start=1):
        ids = ordered[start:start + batch_size]
        rows = store.scan(table, all_columns(), where=in_list(ids))
        pending: list[dict[str, Any]] = []
        texts: list[str] = []
        seen = 0
        for row in rows:
            change = by_id.get(str(row.get("chunk_id")))
            if change is None:
                continue
            seen += 1
            if str(row.get("text") or "") != change.old_text:
                skipped.append(change.chunk_id)
                continue
            # What this row REALLY held when the lock was won -- the row-level
            # undo is built from this, not from the plan-time values, because
            # the compare-and-swap guards `text` only and `table_html` can
            # have moved in between.
            overwritten[change.chunk_id] = {"text": str(row.get("text") or ""),
                                            "table_html": row.get("table_html")}
            new_row = dict(row)
            new_row["text"] = change.new_text
            new_row["table_html"] = change.new_html
            new_row["token_count"] = count_tokens(change.new_text or "")
            pending.append(new_row)
            texts.append(change.new_text or "")
        if seen != len(ids):
            # `len(rows)` and `seen` answer different questions -- how many
            # rows came back, and how many of those the plan still
            # recognises. Reporting the first as the second hides the case
            # where the store answered in full and the ids no longer match.
            raise RuntimeError(
                f"batch {batch_num}: asked for {len(ids)} rows, the store returned "
                f"{len(rows)}, of which {seen} matched the plan -- rows vanished under "
                f"the plan. Batch {batch_num} and every batch after it is NOT written; "
                "re-run the dry run"
            )
        if not pending:
            continue
        # input_type="document" is the embedder's default, but it is stated
        # because it is not a formality (ingest/worker.py::_embed): the model
        # is asymmetric, and a passage embedded with the QUERY instruction
        # quietly degrades every future search against it.
        vectors = embedder.embed_batch(texts, input_type="document")
        if len(vectors) != len(pending):
            # `zip` truncates in SILENCE, so a short return would leave the
            # trailing rows carrying their new `text` and their OLD vector --
            # a passage whose embedding describes the table it used to hold,
            # which is worse than either the old row or the new one. The
            # verify cannot catch it: `_passthrough_mismatch` compares
            # `vector` by LENGTH only, because it round-trips through Arrow
            # float32 and the values that come back are not the Python floats
            # that went in. Raised BEFORE this batch's upsert, so nothing
            # moves.
            raise RuntimeError(
                f"batch {batch_num}: the embedder returned {len(vectors)} vector(s) for "
                f"{len(pending)} row(s). Batch {batch_num} and every batch after it is "
                "NOT written; re-run the dry run"
            )
        for new_row, vector in zip(pending, vectors):
            new_row["vector"] = vector
        # The ATTEMPT is recorded before the call, not its success after it:
        # `upsert_chunks` deletes these chunk_ids and adds the replacements in
        # a second, separate commit, so a failure between the two leaves these
        # rows DELETED while a return-only counter still reads 0 -- and a hint
        # built on that 0 tells the operator the corpus is unchanged.
        state.batches_attempted = batch_num
        state.ids_in_flight = len(pending)
        store.upsert_chunks(table, pending)
        written.extend(pending)
        state.rows_written = len(written)
        state.batches_written = batch_num
        progress(f"{table}: wrote batch {batch_num}/{total_batches} "
                 f"({len(written)}/{len(ordered)} rows, {len(skipped)} skipped -- text moved)")


def _untouched_baseline(
    store: ChunkStoreLike,
    table: str,
    all_ids: list[str],
    changed_ids: set[str],
    batch_size: int,
    progress: Callable[[str], None],
) -> dict[str, Mapping[str, Any]]:
    """Re-read a deterministic sample of rows this pass will NOT touch,
    UNDER THE LOCK and before the first write.

    Read lock-to-lock rather than kept from plan time so that every
    difference the sample later sees really was caused by this pass:
    planning takes tens of minutes and somebody's ingest may run throughout,
    and an untouched document legitimately re-ingested inside that window
    would otherwise fail the post-write comparison and tell the operator to
    restore a snapshot over a write that was entirely correct.
    """
    sample = [cid for cid in all_ids if cid not in changed_ids][:UNCHANGED_SAMPLE_SIZE]
    if not sample:
        # Legitimate only when the pass is rewriting every row there is,
        # which happens on a small test corpus and never on the live one.
        # Said out loud rather than passed over in silence: the untouched
        # half of the verify is not running.
        progress(f"{table}: every scanned row is being rewritten; "
                 "no untouched-row sample to take")
        return {}
    baseline: dict[str, Mapping[str, Any]] = {}
    for start in range(0, len(sample), batch_size):
        ids = sample[start:start + batch_size]
        for row in store.scan(table, UNTOUCHED_SAMPLE_COLUMNS, where=in_list(ids)):
            baseline[str(row["chunk_id"])] = row
    missing = len(sample) - len(baseline)
    if missing:
        if not baseline:
            # An emptied sample is not a passing check, it is an absent one:
            # every later comparison iterates it, so zero rows means zero
            # assertions and the untouched half reports success having looked
            # at nothing. Refused HERE, before the first `upsert_chunks`, so
            # the corpus is still untouched.
            raise RuntimeError(
                f"{table}: the untouched-row sample came back EMPTY -- all "
                f"{len(sample)} rows this pass was never going to touch could not be "
                "re-read under the lock. That is not a concurrent re-ingest, it is the "
                "read itself failing, and an empty sample would make the untouched-row "
                "check pass without comparing anything. Nothing has been written; "
                "re-run the dry run"
            )
        if missing > _missing_tolerance(len(sample)):
            raise RuntimeError(
                f"{table}: {missing} of {len(sample)} sampled untouched rows could not "
                f"be re-read under the lock, over the {_missing_tolerance(len(sample)):.4g} "
                "this pass tolerates as a concurrent re-ingest. Nothing has been "
                "written; re-run the dry run"
            )
        # Under the line: gone before this pass wrote anything, so not ours.
        progress(f"{table}: {missing} of {len(sample)} sampled untouched rows were "
                 "already gone before the first write; dropped from the sample")
    return baseline


def _verify_nothing_was_lost(
    store: ChunkStoreLike,
    table: str,
    written: list[dict[str, Any]],
    before_ids: set[str],
    untouched_baseline: Mapping[str, Mapping[str, Any]],
    batch_size: int,
    progress: Callable[[str], None],
) -> None:
    """Spec §6.6. Three checks, and none of them is a row count -- a matching
    count proves nothing, because `upsert_chunks` deletes then adds and a
    lost column leaves the count identical (`identity/relabel.py`'s trap 3).

    1. The table's chunk-id SET is what it was before the write. Read with a
       one-column projection, so it is cheap enough to run over the whole
       table and catches a delete that landed on ids nobody sampled.
    2. Every written row re-read in full and compared against what was SENT
       -- which IS the expected post-write row, since `_write_changed_rows`
       copies the fetched row and replaces four keys. That makes this one
       comparison cover both halves of spec D4: the four columns landed, and
       nothing else moved.
    3. The untouched sample still reads as it did when the lock was taken.

    Plus one table-specific post-condition: a rebuilt table may not still
    contain a merged cell. That is the defect this whole pass exists for, so
    finding one in the corpus after the write means the rebuild did not do
    what it reported.
    """
    after_ids = {str(r["chunk_id"]) for r in store.scan(table, ["chunk_id"])}
    if after_ids != before_ids:
        lost, gained = len(before_ids - after_ids), len(after_ids - before_ids)
        raise RuntimeError(
            f"{table}: the chunk-id set changed during the apply -- {lost} id(s) gone, "
            f"{gained} new. This pass adds and removes no rows; restore the snapshot"
        )

    sent_by_id = {str(r["chunk_id"]): r for r in written}
    ordered = sorted(sent_by_id)
    seen = 0
    for start in range(0, len(ordered), batch_size):
        ids = ordered[start:start + batch_size]
        for row in store.scan(table, all_columns(), where=in_list(ids)):
            sent = sent_by_id.get(str(row.get("chunk_id")))
            if sent is None:
                continue
            seen += 1
            if not _norm(row.get("vector")):
                raise RuntimeError(f"{row['chunk_id']}: vector is empty after the write")
            lost_col = _passthrough_mismatch(row, sent)
            if lost_col is not None:
                raise RuntimeError(
                    f"{row['chunk_id']}: column {lost_col!r} is not what was written -- "
                    "this pass sends every column but "
                    f"{'/'.join(WRITTEN_COLUMNS)} through by value, so any other column "
                    "differing means the write lost it (spec D4)"
                )
            if has_merged_cell(table_rows(str(row.get("text") or ""))):
                raise RuntimeError(
                    f"{row['chunk_id']}: still holds a merged cell after the rebuild -- "
                    "the rewritten text is not what the rebuild reported"
                )
    if seen != len(sent_by_id):
        raise RuntimeError(
            f"{table}: verified {seen} written rows, expected {len(sent_by_id)}"
        )

    sampled = sorted(untouched_baseline)
    after: dict[str, Mapping[str, Any]] = {}
    for start in range(0, len(sampled), batch_size):
        ids = sampled[start:start + batch_size]
        for row in store.scan(table, UNTOUCHED_SAMPLE_COLUMNS, where=in_list(ids)):
            after[str(row["chunk_id"])] = row
    for chunk_id in sampled:
        now = after.get(chunk_id)
        if now is None:
            raise RuntimeError(
                f"{chunk_id}: was never supposed to change and is GONE after the write"
            )
        for col in UNTOUCHED_SAMPLE_COLUMNS:
            if _norm(now.get(col)) != _norm(untouched_baseline[chunk_id].get(col)):
                raise RuntimeError(
                    f"{chunk_id}: was never supposed to change but its {col!r} changed "
                    "during the write"
                )
    progress(f"{table}: verified {seen} rewritten rows in full and "
             f"{len(sampled)} untouched rows")


def repair_tables(
    *,
    store: ChunkStoreLike,
    embedder: EmbedderLike,
    root: Path,
    table: str = "budget_chunks",
    dry_run: bool = True,
    only: set[str] | None = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    lock: Any | None = None,
    snapshot_and_verify: Callable[[], str | None] | None = None,
    reversal_dir: Path | None = None,
    progress: Callable[[str], None] | None = None,
) -> RepairResult:
    """Plan every in-scope operating table and, with `dry_run=False`, write
    back the ones the gate verified.

    `dry_run=True` (the default) takes no lock, snapshots nothing and writes
    nothing -- the asymmetry `identity/relabel.py` and the section-path
    repair both document, and what lets this be re-run by hand against the
    live corpus as often as anyone wants before an apply is approved.

    Note for any caller telling one failure from another: EVERY failure after
    the first write is ATTEMPTED is re-raised as a `RuntimeError` carrying
    `_TableWriteState.hint()`, with the real exception on `__cause__` (and,
    when the index rebuild or the optimize also failed, that exception one
    further down the `__cause__` chain). That includes a `KeyboardInterrupt`.
    So a CLI wanting distinct exit codes must read `__cause__`, and must not
    assume a Ctrl-C arrives as `KeyboardInterrupt`.
    """
    progress = progress or (lambda m: print(m, flush=True))
    changes, summary = plan_corpus(store, root, table, only=only, progress=progress)
    result = RepairResult(changes, summary)
    rebuilt = [c for c in changes if c.verdict == "rebuilt"]
    if dry_run:
        progress(f"DRY RUN: {len(rebuilt)} of {len(changes)} tables would be rewritten; "
                 "nothing written")
        return result
    if not rebuilt:
        # BEFORE the lock and BEFORE the snapshot: a snapshot zips the whole
        # corpus under the lock and takes minutes, and spending that on a
        # no-op is the kind of thing an operator learns to skip -- and then
        # skips once when it mattered.
        progress("nothing to rebuild; no lock, no snapshot, no write, no index rebuild")
        return result

    if lock is None:
        from ingest.lock import IngestLock
        lock = IngestLock()
    if snapshot_and_verify is None:
        snapshot_and_verify = default_snapshot_and_verify
    if reversal_dir is None:
        from store.config import data_dir
        reversal_dir = data_dir()

    # `IngestLock.acquire()` runs its own heartbeat thread for the whole
    # write; nothing here beats it by hand.
    with lock:
        snapshot = snapshot_and_verify()
        result.snapshot_name = snapshot
        progress(f"snapshot: {snapshot}")

        # AFTER the snapshot and BEFORE the first row moves -- `identity/
        # relabel.py`'s order, and the reason is the failure it protects
        # against. The record is computed at PLAN time, so nothing about it
        # needs the write to have happened; written last, a crash, a lost
        # share or a killed process anywhere in the write leaves the corpus
        # half-rewritten with NO row-level undo at all, only a whole-corpus
        # restore that also throws away every upload since.
        reversal_path = Path(reversal_dir) / f"table-rebuild-reversal-{table}-{reversal_stamp()}.json"
        result.reversal_path = reversal_path

        changed_ids = {c.chunk_id for c in rebuilt}
        all_ids = sorted(str(r["chunk_id"]) for r in store.scan(table, ["chunk_id"]))
        # The baseline read runs FIRST because it can refuse, and it refuses
        # before a single row has moved. Writing the record above it left an
        # orphan record on the share describing a write that never happened.
        # The record still precedes the first `upsert_chunks`, which is the
        # property that matters.
        untouched = _untouched_baseline(store, table, all_ids, changed_ids, batch_size, progress)

        progress(f"writing reversal record to {reversal_path}")
        # `stage` is the difference between intent and fact, and it matters
        # for THIS pass in a way it did not for the section-path one: a row
        # whose text moved is skipped rather than written, so a "planned"
        # record can name a row that was never touched -- and replaying that
        # row's `before` would put a stale table back over somebody's fresh
        # re-ingest. It says so on its own face, because whoever finds this
        # file after a crash has no scrollback to read.
        atomic_write_json(reversal_path, {
            "table": table, "snapshot": snapshot, "stage": "planned",
            "skipped_moved": [],
            "note": ("PLANNED, not written. `rows` is every table the plan would "
                     "rebuild, which may include rows the write then SKIPPED because "
                     "the corpus had moved under the plan. Do NOT replay this record "
                     "blind: a skipped row's `before` would write a stale table back "
                     "over a fresh re-ingest. A record left at this stage means the "
                     "write phase never reported back -- restore the snapshot instead."),
            "rows": _reversal_rows(rebuilt)})
        progress(f"reversal record written: {reversal_path}")

        state = _TableWriteState(snapshot=snapshot, reversal_path=reversal_path)
        failure: BaseException | None = None
        written: list[dict[str, Any]] = []
        skipped: list[str] = []
        overwritten: dict[str, dict[str, Any]] = {}
        try:
            _write_changed_rows(
                store, table, rebuilt, embedder, batch_size, progress, state,
                written, skipped, overwritten
            )
            result.written, result.skipped_moved = len(written), skipped
            _verify_nothing_was_lost(
                store, table, written, set(all_ids), untouched, batch_size, progress
            )
            # Set only once the verifier has RETURNED. Everything that decides
            # "is a restore the right move?" reads this, so it must mean
            # "somebody checked what landed", never "the loop finished".
            state.verified = True
        except BaseException as exc:  # noqa: BLE001 -- re-raised below, enriched
            # BaseException and not Exception: this is the embed-and-write
            # phase, which is both when an operator is most likely to press
            # Ctrl-C and the only phase that can leave rows deleted. Under
            # `except Exception` a KeyboardInterrupt skipped the hint entirely
            # and reached the terminal with no row count, no "rows may be
            # DELETED" and neither restore point. It is not swallowed: the
            # `raise ... from failure` below still terminates the run.
            failure = exc
        finally:
            # Re-added rows are invisible to BM25 until the index is rebuilt
            # (the ingest contract `funds/unstamp.py` had to learn the hard
            # way). It runs on the FAILURE path too: once any batch has
            # landed the rows exist and search must be consistent with them,
            # and an un-rebuilt index over written rows is a worse state than
            # the one that raised. Gated on `batches_attempted` rather than
            # `rows_written`, because a batch that raised between its delete
            # commit and its add commit has already changed the table.
            if state.batches_attempted:
                try:
                    store.build_fts_index(table)
                    # Set HERE and not after `optimize`: the index IS rebuilt
                    # the moment this returns, and reporting an optimize
                    # failure as "the index was NOT rebuilt" points an
                    # operator at a restore that would discard a good write.
                    state.index_rebuilt = True
                except BaseException as rebuild_exc:  # noqa: BLE001 -- re-raised below
                    # An exception raised inside a `finally` REPLACES whatever
                    # was propagating, so this is recorded and chained rather
                    # than allowed to destroy the original failure and its hint.
                    state.rebuild_error = rebuild_exc
                    progress(f"FULL-TEXT INDEX REBUILD FAILED: {rebuild_exc} -- the rows "
                             "are written and keyword search will MISS them until it is "
                             "rebuilt")
                else:
                    try:
                        store.optimize(table)
                        progress("full-text index rebuilt and table optimized")
                    except BaseException as optimize_exc:  # noqa: BLE001 -- re-raised
                        state.optimize_error = optimize_exc
                        progress("the full-text index WAS rebuilt; optimize FAILED: "
                                 f"{optimize_exc} -- old versions were not pruned, "
                                 "search is correct; re-run optimize by hand")
        # The record becomes exact as soon as the write phase has stopped
        # moving rows -- ON THE FAILURE PATH TOO, and before anything is
        # raised. Left at `stage: "planned"` it lists rows the compare-and-swap
        # skipped, and every post-write failure hands the operator a remedy
        # that offers to replay it; doing so writes the stale plan-time table
        # back over the fresh re-ingest that caused the skip. `rows` is what
        # was really written and `skipped_moved` names what was not, so
        # neither a replay nor a reader can reach a row this pass left alone.
        result.written, result.skipped_moved = len(written), list(skipped)
        written_ids = {str(r["chunk_id"]) for r in written}
        try:
            atomic_write_json(reversal_path, {
                "table": table, "snapshot": snapshot, "stage": "written",
                "skipped_moved": result.skipped_moved,
                "note": ("WRITTEN. `rows` is exactly what this pass overwrote; "
                         "replaying a row restores the `before` text and table_html it "
                         "held when the lock was won. Rows under `skipped_moved` were "
                         "NOT written and are not in `rows`."),
                "rows": _reversal_rows([c for c in rebuilt if c.chunk_id in written_ids],
                                       overwritten)})
            state.reversal_exact = True
        except BaseException as record_exc:  # noqa: BLE001 -- reported below
            # Same reasoning as the index rebuild's own handler: this must not
            # replace whatever is propagating, and it must not pass in silence
            # either -- the record on the share is now the PLANNED one, which
            # `_TableWriteState.remedy` will refuse to offer for replay.
            state.record_error = record_exc
            progress(f"THE REVERSAL RECORD COULD NOT BE REWRITTEN: {record_exc} -- the "
                     f"record at {reversal_path} still describes the PLAN and must not "
                     "be replayed")
        if failure is not None:
            # Composed after the `finally`, so it states whether the index
            # really was rebuilt rather than what was true when the error was
            # raised. `rebuild_error` first because it is the one that costs
            # search correctness.
            secondary = state.rebuild_error or state.optimize_error or state.record_error
            if secondary is not None:
                failure.__cause__ = secondary
            raise RuntimeError(f"{failure} -- {state.hint()}") from failure
        if state.rebuild_error is not None:
            # The write and the verification both passed and the rebuild did
            # not: rows live behind a stale BM25 index, which is the most
            # dangerous state this module can produce. `state.remedy()`'s
            # verified branch is what says do NOT roll back -- a restore here
            # would discard a correct write plus every upload since, to fix an
            # index.
            raise RuntimeError(
                "the full-text index rebuild failed AFTER the rows were written -- "
                f"{state.state_sentence()}. {state.remedy()} Fix whatever the rebuild "
                f"could not reach and re-run build_fts_index on {table} by hand."
            ) from state.rebuild_error
        if state.optimize_error is not None:
            raise RuntimeError(
                "the table optimize failed after a clean, verified write -- "
                f"{state.state_sentence()}. {state.remedy()} Nothing needs restoring "
                f"and search is correct; re-run optimize on {table} by hand to prune "
                "the old table versions."
            ) from state.optimize_error
        if state.record_error is not None:
            # The rows landed, verified, and the index was rebuilt -- only the
            # row-level undo on the share is stale. It costs nothing today and
            # everything on the day somebody reaches for it, and scrollback is
            # gone by then, so it terminates the run rather than sitting in a
            # progress line.
            raise RuntimeError(
                "the reversal record could not be rewritten after a clean, verified "
                f"write -- {state.state_sentence()}. {state.remedy()}"
            ) from state.record_error
    progress(f"{table}: {result.written} table(s) rewritten, "
             f"{len(result.skipped_moved)} skipped (text moved)")
    return result


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
