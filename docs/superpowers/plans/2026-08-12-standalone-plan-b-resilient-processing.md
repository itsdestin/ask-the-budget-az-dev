# Plan B — Resilient Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A document that extracts to nothing is detected, retried with a different method, and — if every method fails — held out of search and shown to a human, instead of reporting success while delivering an empty document.

**Architecture:** Extraction gains a check and a ladder. After chunking and
before embedding, the worker measures how much text the extraction actually
produced against the source file's own text layer. Below the floor it clears
the extraction and tries the next method on the ladder, keeping whichever
attempt scored highest. When the ladder is exhausted the document is never
written to the corpus, its attempts are recorded on the job, and it appears in
a "Needs attention" panel on the Admin page. Successful documents record their
coverage in `documents.json`, which lets a duplicate upload say whether
re-processing is actually needed.

**Tech Stack:** Python 3.12, FastAPI, PyMuPDF (`fitz`), MinerU 3.1.6 CLI,
OpenDataLoader, python-docx, LanceDB, React + TypeScript (Vite), pytest, vitest.

**Spec:** `docs/superpowers/specs/2026-08-11-document-types-and-resilient-processing-design.md`
— decisions **T5, T6, T7, T8, T12**. T9 shipped in Plan A. T10 and T13 are Plan C.
**T11 (the backfill) is explicitly OUT OF SCOPE** — Destin's call 2026-08-12:
Plan B builds and proves the machinery; the backfill is a supervised run
afterwards.

**Calibration:** `docs/superpowers/investigations/2026-08-12-coverage-floor-calibration.md`
— the corpus-wide run T6 requires. **Read it before Task 1.**

---

## Global Constraints

- **`COVERAGE_FLOOR = 0.10`.** Calibrated across all 7,434 documents on
  2026-08-12. Do not change it without re-running that measurement.
- **A ratio above 1.0 is normal, not an error.** Healthy AFRs score 278–286%
  because chunk text carries table markup the source text layer does not.
  **Never cap, clamp or normalize the ratio.**
- **The coverage check detects catastrophic loss, NOT corruption.** It cannot
  see a document that produced the right *amount* of the *wrong* text. No
  analyst-facing copy may describe a passing document as verified, checked,
  validated or good. Say what it measured: how much text came out.
- **Nothing in `tests/` may open a real LanceDB directory or load ONNX
  weights.** Fixtures and monkeypatching only.
- **Run the eval** (`uv run python -m eval.run_eval`, needs `JLBC_DATA_DIR`)
  after any change under `ingest/` or `chunking/`, and commit
  `eval/results/<...>.{json,md}` with the diff. **Expect no movement** — no
  existing document is re-extracted by Tasks 1–7 — and treat any movement as a
  finding to explain, not as noise.
- **Annotate non-trivial edits with a WHY comment** recording the evidence that
  drove the choice. Destin is a non-developer and these comments are how the
  reasoning survives.
- **`documents.json` is read-modify-write under the ingest lock.** Never widen
  a read there to `strict=False` — degrading a corrupt sidecar to `{}` on the
  write path orphans every PDF in the corpus.
- **Absence must read as "fine".** All 7,434 existing documents have no
  `extraction` key. Nothing may treat its absence as a failure, a warning, or
  an unknown state worth reporting.
- **The floor rejects; it never approves.** A document at or above the floor
  proceeds exactly as it does today, with no new gate, banner or annotation.
- **🔴 MEASURED DEVIATION from spec T7 — inspection does NOT consider tagging.**
  T7 says *"A PDF with no structure tree starts at rung 2."* Measured against
  the corpus, that rule is **wrong and would cause a regression**:

  | document | tagged? | first rung today | coverage |
  |---|---|---|---|
  | `governor-governors-budget-fy2025` | **no** | OpenDataLoader | **92.2%** |
  | `governor-governors-budget-fy2026` | yes | OpenDataLoader | 96.0% |
  | `agao-afr-fy2024` | **yes** | OpenDataLoader | **2.0%** |

  OpenDataLoader handles a 639-page **untagged** PDF at 92.2%, so tagging does
  not predict its success — and the one document that does fail **is** tagged.
  Dropping OpenDataLoader for untagged files would divert a healthy 639-page
  document to a slower tool and change its chunk text for no gain. **Only
  `has_text_layer` survives**, which routes a scan straight to OCR. Coverage
  plus fallback already handles everything tagging was supposed to predict.

---

## File Structure

| File | Responsibility |
|---|---|
| `ingest/coverage.py` | **new** — the coverage signal and the floor. Pure functions, no I/O beyond reading the source file. |
| `ingest/inspection.py` | **new** — inspect a source file; decide which ladder rung to start on. |
| `ingest/ladder.py` | **new** — the ordered extraction attempts for a (doc_type, format, inspection). |
| `ingest/dispatcher.py` | modify — add the MinerU OCR extractor variant. |
| `ingest/jobs.py` | modify — `JobRecord.extraction_attempts`. |
| `ingest/worker.py` | modify — run the ladder; hold a terminal failure out of the corpus. |
| `ingest/lance_writer.py` | modify — record `extraction` in `documents.json`. |
| `app/routes/upload.py` | modify — health-aware duplicate response (T12). |
| `app/routes/admin.py` | modify — `GET /api/admin/attention`. |
| `webapp/src/admin/NeedsAttention.tsx` | **new** — the panel. |
| `webapp/src/admin/AdminPage.tsx` | modify — mount the panel above Corpus health. |

---

## Task 1: The coverage signal

**Files:**
- Create: `ingest/coverage.py`
- Test: `tests/test_coverage.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `COVERAGE_FLOOR: float`, `source_text_chars(path: Path) -> int`,
  `coverage_ratio(chunk_texts: Iterable[str], source_path: Path) -> float | None`.
  `coverage_ratio` returns `None` when the source has no text layer at all —
  that is a routing signal (go to OCR), not a failure.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_coverage.py
"""The coverage signal (spec T6).

Fixtures are built in-process with PyMuPDF rather than committed, so this
suite opens no corpus and loads no model.
"""
from pathlib import Path

import fitz
import pytest

from ingest.coverage import COVERAGE_FLOOR, coverage_ratio, source_text_chars


def _pdf(tmp_path: Path, pages: list[str], name: str = "f.pdf") -> Path:
    doc = fitz.open()
    for body in pages:
        page = doc.new_page()
        if body:
            page.insert_text((72, 72), body)
    path = tmp_path / name
    doc.save(path)
    doc.close()
    return path


def test_source_text_chars_counts_the_text_layer(tmp_path):
    path = _pdf(tmp_path, ["hello world", "second page"])
    assert source_text_chars(path) >= len("hello world") + len("second page")


def test_ratio_is_produced_over_source(tmp_path):
    path = _pdf(tmp_path, ["abcdefghij"])          # 10 chars of source text
    got = coverage_ratio(["abcde"], path)          # 5 chars produced
    assert got == pytest.approx(5 / source_text_chars(path))


def test_the_fy2024_afr_shape_lands_below_the_floor(tmp_path):
    """20 chunks from a 191-page document scored 2.0% on the real corpus."""
    path = _pdf(tmp_path, ["x" * 1000 for _ in range(10)])
    ratio = coverage_ratio(["x" * 20], path)
    assert ratio < COVERAGE_FLOOR


def test_a_ratio_above_one_is_returned_unchanged(tmp_path):
    """Healthy AFRs score 278-286% because chunk text carries table markup.

    Clamping to 1.0 would erase the single clearest signal that extraction
    is working. Pinned because "normalize it to a percentage" is a natural
    and wrong instinct.
    """
    path = _pdf(tmp_path, ["abc"])
    assert coverage_ratio(["x" * 10_000], path) > 1.0


def test_no_text_layer_returns_None_rather_than_zero(tmp_path):
    """An image-only PDF must route to OCR, not read as a failed extraction.

    0.0 and None are different answers: 0.0 means "we extracted nothing from
    a document that has text", None means "there is nothing here to compare
    against".
    """
    path = _pdf(tmp_path, [""])
    assert coverage_ratio(["anything"], path) is None


def test_the_floor_is_the_calibrated_value():
    """Pinned so a future edit has to go and re-read the calibration."""
    assert COVERAGE_FLOOR == 0.10
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_coverage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.coverage'`

- [ ] **Step 3: Write the implementation**

```python
# ingest/coverage.py
"""Does an extraction look catastrophically empty? (spec T6)

The signal is characters of chunk text produced divided by characters in the
source file's own text layer. It exists because `agao-afr-fy2024` reported
`live` with 20 passages from 191 pages, the queue showed green, and an
analyst searching FY2024 simply got nothing.

## What this does NOT do

It detects catastrophic LOSS, not CORRUPTION. A document that produced the
right amount of the wrong text passes. That is not hypothetical on this
corpus: the FY2024 AFR's own recovered rows are label-stripped table
fragments, and a numeric-density check scored them 1.6% "junk" -- apparently
clean -- because they are full of agency and fund names. Passing this check
is not a certificate of health, and nothing may describe it as one.
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable

# CALIBRATED 2026-08-12 across all 7,434 documents, post orphan-recovery
# repair. Full measurement:
#   docs/superpowers/investigations/2026-08-12-coverage-floor-calibration.md
#
# Median coverage is 87.9%. Every floor from just above 2.0% to just below
# 17.1% catches an IDENTICAL set of two documents, so this is a plateau and
# 0.10 is its centre -- the right pick because the metric degrades on both
# sides: below 2.0% the known-broken AFR escapes, above 17.1% healthy short
# documents start being caught.
#
# The spec's original expectation was 15-25%, from a 16-document sample taken
# before the orphan-recovery bug was fixed. The corpus-wide run says that is
# too high. Do not restore it without re-running the measurement.
COVERAGE_FLOOR = 0.10


def source_text_chars(path: Path) -> int:
    """Characters in the source file's own text layer -- the denominator.

    This reads the SOURCE, deliberately, not the extractor's output: the
    question is "how much of what is in this file came out", and only the
    file itself can answer it.
    """
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        import fitz  # PyMuPDF

        with fitz.open(path) as doc:
            return sum(len(page.get_text()) for page in doc)
    if suffix == ".docx":
        import docx  # python-docx

        document = docx.Document(str(path))
        # Table cells are not in `paragraphs` and a budget bill is mostly
        # tables, so counting paragraphs alone would make every DOCX look
        # like a failed extraction.
        body = sum(len(p.text) for p in document.paragraphs)
        cells = sum(
            len(cell.text)
            for table in document.tables
            for row in table.rows
            for cell in row.cells
        )
        return body + cells
    raise ValueError(f"coverage: no text-layer reader for {suffix!r} ({path.name})")


def coverage_ratio(chunk_texts: Iterable[str], source_path: Path) -> float | None:
    """Produced characters over source characters.

    Returns None when the source has no text layer at all. That is a ROUTING
    signal -- an image-only PDF goes to OCR -- and must not be confused with
    0.0, which means "this document has text and we extracted none of it".

    The result is NOT clamped. Values above 1.0 are normal and are the
    clearest evidence extraction is working; see the module docstring.
    """
    produced = sum(len(text or "") for text in chunk_texts)
    total = source_text_chars(source_path)
    if total == 0:
        return None
    return produced / total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_coverage.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ingest/coverage.py tests/test_coverage.py
git commit -m "feat(ingest): the coverage signal, floor calibrated at 10%"
```

---

## Task 2: Source inspection

**Files:**
- Create: `ingest/inspection.py`
- Test: `tests/test_inspection.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `SourceInspection` (frozen dataclass: `source_format: str`,
  `pages: int | None`, `has_text_layer: bool`) and
  `inspect_source(path: Path) -> SourceInspection`.

**Context the implementer needs:** there is deliberately **no tagging /
structure-tree field** — see the measured deviation in Global Constraints. Do
not add one back "for completeness": it was measured, it predicts nothing, and
acting on it causes a regression. Inspection here answers exactly one
question — *is there any text in this file at all?* — because that is the only
question whose answer changes the starting rung.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_inspection.py
from pathlib import Path

import fitz

from ingest.inspection import inspect_source


def _pdf(tmp_path: Path, *, pages: int, text: bool) -> Path:
    doc = fitz.open()
    for _ in range(pages):
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), "The Baseline includes $1,000,000 for X.")
    path = tmp_path / "f.pdf"
    doc.save(path)
    doc.close()
    return path


def test_reports_format_and_page_count(tmp_path):
    got = inspect_source(_pdf(tmp_path, pages=3, text=True))
    assert got.source_format == "pdf"
    assert got.pages == 3


def test_detects_a_text_layer(tmp_path):
    assert inspect_source(_pdf(tmp_path, pages=1, text=True)).has_text_layer is True


def test_detects_the_absence_of_a_text_layer(tmp_path):
    assert inspect_source(_pdf(tmp_path, pages=1, text=False)).has_text_layer is False


def test_inspection_reports_nothing_about_tagging(tmp_path):
    """A regression guard, not a capability test.

    Tagging was measured across every OpenDataLoader-first document and does
    not predict extraction success: an UNTAGGED 639-page Executive Budget
    scores 92.2% through OpenDataLoader, while the one document that fails IS
    tagged. A future edit that re-adds this field will re-add the rule that
    consumes it, which diverts a healthy document to a slower extractor.
    """
    got = inspect_source(_pdf(tmp_path, pages=1, text=True))
    assert not hasattr(got, "has_structure_tree")


def test_docx_has_no_page_count(tmp_path):
    """DOCX has no pages at rest. None, not 0 -- 0 would read as "empty"."""
    import docx

    d = docx.Document()
    d.add_paragraph("Section 1. Appropriations.")
    path = tmp_path / "bill.docx"
    d.save(path)

    got = inspect_source(path)
    assert got.source_format == "docx"
    assert got.pages is None
    assert got.has_text_layer is True


def test_an_unreadable_file_does_not_raise(tmp_path):
    """A truncated download must not take the worker thread down.

    pdfium rejects shapes PyMuPDF tolerates and vice versa; whatever the
    reason, an inspection failure means "we learned nothing", which is a
    valid answer that starts the ladder at rung 1.
    """
    path = tmp_path / "broken.pdf"
    path.write_bytes(b"%PDF-1.4\nnot really a pdf")

    got = inspect_source(path)
    assert got.pages is None
    assert got.has_text_layer is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_inspection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.inspection'`

- [ ] **Step 3: Write the implementation**

```python
# ingest/inspection.py
"""Look at a source file and decide where to START extracting (spec T5 step 1).

## Inspection picks the starting rung. It NEVER decides success.

This is the decisive measurement behind the whole design and it is worth
stating at the code: `agao-afr-fy2023` (healthy, 281% coverage) and
`agao-afr-fy2024` (broken, 2.0%) are INDISTINGUISHABLE here. Both report
191/184 pages and ~1.1M characters of text layer. Anything that tries to
predict failure from inspection alone will pass the FY2024 AFR, which is the
document this design exists for. Only running the extraction and measuring
its output (T6) separates them.

## Why there is no tagging field, despite spec T7 asking for one

Measured across every OpenDataLoader-first document in the corpus:

    governor-governors-budget-fy2025   UNTAGGED, 639pp   ->  92.2%
    governor-governors-budget-fy2026   tagged,   661pp   ->  96.0%
    agao-afr-fy2024                    TAGGED,   191pp   ->   2.0%

Tagging does not predict success. OpenDataLoader reads a large untagged PDF
fine, and the one document that fails is tagged. A "no structure tree ->
skip OpenDataLoader" rule would therefore divert a healthy 639-page document
to a slower extractor and change its chunk text for nothing. Do not add the
field back.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceInspection:
    """What the file itself will tell us before anything is extracted."""

    source_format: str
    # None for DOCX (no pages at rest) and for a file we could not open.
    # None rather than 0: "not applicable" and "empty" are different.
    pages: int | None
    has_text_layer: bool


def inspect_source(path: Path) -> SourceInspection:
    """Cheap, total, and never raises.

    An inspection failure is a valid answer -- it means we learned nothing
    and the ladder starts at rung 1. Raising here would take down the worker
    thread over a truncated download.
    """
    source_format = path.suffix.lstrip(".").lower()

    if source_format == "pdf":
        try:
            import fitz  # PyMuPDF

            with fitz.open(path) as doc:
                # `.strip()` matters: a PDF of scanned pages often carries a
                # few whitespace glyphs, which would otherwise read as text
                # and route a scan away from the OCR rung it needs.
                has_text = any(page.get_text().strip() for page in doc)
                return SourceInspection("pdf", doc.page_count, has_text)
        except Exception:
            return SourceInspection("pdf", None, False)

    if source_format == "docx":
        try:
            import docx  # python-docx

            document = docx.Document(str(path))
            has_text = any(p.text.strip() for p in document.paragraphs) or any(
                cell.text.strip()
                for table in document.tables
                for row in table.rows
                for cell in row.cells
            )
            return SourceInspection("docx", None, has_text)
        except Exception:
            return SourceInspection("docx", None, False)

    return SourceInspection(source_format, None, False)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_inspection.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add ingest/inspection.py tests/test_inspection.py
git commit -m "feat(ingest): inspect a source to pick the starting extraction rung"
```

---

## Task 3: The OCR rung and the ladder

**Files:**
- Modify: `ingest/dispatcher.py` (add `MinerUOcrExtractor`, register the class)
- Modify: `scripts/run_mineru.py` (accept a `method` argument)
- Modify: `ingest/mineru_runner.py` (accept and pass `method`)
- Create: `ingest/ladder.py`
- Test: `tests/test_ladder.py`, extend `tests/test_dispatcher.py`

**Interfaces:**
- Consumes: `ingest.inspection.SourceInspection`, `ingest.doc_types`.
- Produces: `ladder_for(doc_type: str, source_format: str, inspection: SourceInspection) -> list[str]`
  returning extractor NAMES in attempt order (e.g.
  `["opendataloader", "mineru", "mineru-ocr"]`).

**Verified:** the pinned MinerU exposes `-m, --method [auto|txt|ocr]`, and
`_read_mineru_output` already discovers whichever method subdirectory MinerU
writes — so the OCR rung needs a flag, not a new reader.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ladder.py
from ingest.inspection import SourceInspection
from ingest.ladder import ladder_for

TEXT = SourceInspection("pdf", 100, has_text_layer=True)
SCANNED = SourceInspection("pdf", 100, has_text_layer=False)
DOCX = SourceInspection("docx", None, has_text_layer=True)


def test_an_odl_first_pdf_gets_the_full_ladder():
    assert ladder_for("afr", "pdf", TEXT) == [
        "opendataloader", "mineru", "mineru-ocr",
    ]


def test_a_mineru_first_pdf_starts_below_opendataloader():
    """The declared preference sets the starting rung; nothing above it runs."""
    assert ladder_for("baseline-per-agency", "pdf", TEXT) == [
        "mineru", "mineru-ocr",
    ]


def test_a_pdf_with_no_text_layer_goes_straight_to_ocr():
    assert ladder_for("afr", "pdf", SCANNED) == ["mineru-ocr"]


def test_docx_has_no_ladder():
    """The structure is in the file and there is no second tool to try."""
    assert ladder_for("budget-bill", "docx", DOCX) == ["python-docx"]


def test_the_first_rung_matches_todays_shipped_routing():
    """The safety net for the whole change.

    EVERY (doc_type, format) pair the registry knows must still START on the
    extractor it uses today, for any file that has a text layer. A different
    first rung means different chunk text, different chunk_ids, and broken
    eval ground truth on the next re-ingest.

    Note there is no per-type special-casing here: with tagging removed from
    inspection, one inspection value covers every PDF type, which is itself
    evidence the rule that needed the special case was not carrying weight.
    """
    from ingest.dispatcher import EXTRACTOR_REGISTRY, pick_extractor

    for (doc_type, fmt) in EXTRACTOR_REGISTRY:
        inspection = TEXT if fmt == "pdf" else DOCX
        assert ladder_for(doc_type, fmt, inspection)[0] == pick_extractor(doc_type, fmt).name


def test_every_rung_can_actually_be_chunked():
    """The seam that a review caught and this plan originally missed.

    A rung name is used TWICE: once to extract, and once to choose the
    reader that parses that extractor's output. A rung the chunker has no
    reader for cannot complete, and would surface as a confusing failure
    days into execution rather than here.
    """
    from chunking.builder import _READER_REGISTRY

    for rung in ("opendataloader", "mineru", "mineru-ocr", "python-docx"):
        assert rung in _READER_REGISTRY


def test_an_unknown_combination_has_no_ladder():
    assert ladder_for("budget-bill", "pdf", TEXT) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ladder.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ingest.ladder'`

- [ ] **Step 3: Add the OCR extractor to the dispatcher**

In `ingest/dispatcher.py`, after `MinerUExtractor`:

```python
@dataclass
class MinerUOcrExtractor(MinerUExtractor):
    """MinerU reading pages as images (`-m ocr`).

    The last rung of the PDF ladder. It is the only option for a scanned
    document, and the slowest thing this app does -- so it is never a
    starting rung for a file that has a text layer.
    """

    name: str = "mineru-ocr"

    def extract(
        self,
        *,
        source_path: Path,
        output_dir: Path,
        pages: list[int] | None,
    ) -> None:
        run_mineru_mod = _import_phase0_module("run_mineru")
        if pages is None:
            pages = list(range(1, _pdf_page_count(source_path) + 1))
        run_mineru_mod.run_mineru(source_path, output_dir, pages, method="ocr")
```

And register it:

```python
_EXTRACTOR_CLASSES = {
    "mineru": MinerUExtractor,
    "mineru-ocr": MinerUOcrExtractor,
    "opendataloader": OpenDataLoaderExtractor,
    "python-docx": PythonDocxExtractor,
}
```

> **Note for the implementer:** `mineru-ocr` is deliberately NOT added to
> `data/document-types.yaml`. The YAML declares each type's *preferred*
> extractor; the ladder supplies the fallbacks. Adding it to the YAML would
> make it a first choice for some type.

- [ ] **Step 3b: Teach the CHUNKER about the OCR rung**

An extractor name is used **twice** — once to extract, and once to choose the
reader that parses that extractor's output. `chunking/builder.py` keys
`_READER_REGISTRY` on that name and **raises `Unknown extractor` on anything
it does not know**, so without this the OCR rung extracts successfully and
then cannot be chunked.

```python
# chunking/builder.py
_READER_REGISTRY = {
    "mineru": MinerUReader,
    # MinerU's OCR mode writes the SAME output format -- the reader already
    # discovers whichever method subdirectory MinerU produced (auto / txt /
    # ocr), so the OCR rung needs a name here, not a second reader.
    "mineru-ocr": MinerUReader,
    "opendataloader": ODLReader,
    "python-docx": DocxReader,
}
```

- [ ] **Step 4: Thread `method` through the two MinerU entry points**

`scripts/run_mineru.py` — change the signature and the command:

```python
def run_mineru(pdf: Path, out: Path, pages: list[int], *, method: str = "auto") -> None:
    """Real path. Shells out to `mineru` CLI per contiguous page range.

    `method` is MinerU's `-m` flag. "auto" is today's behaviour and the
    default, so every existing caller is unchanged. "ocr" is the ladder's
    last rung (spec T7) and reads pages as images.
    """
```

and inside the loop, after the `-b pipeline` entry:

```python
            cmd = [
                "uv", "run", "mineru",
                "-p", str(pdf),
                "-o", str(tmp_path),
                "-s", str(start - 1),  # CLI is 0-indexed, inclusive
                "-e", str(end - 1),
                "-b", "pipeline",
                "-m", method,
            ]
```

Make the same change in `ingest/mineru_runner.py`: add `method: str = "auto"`
to the runner's constructor, and append `"-m", self._method` to **both**
`cmd` lists (the probe at ~line 364 and the extract at ~line 465).

- [ ] **Step 5: Write the ladder**

```python
# ingest/ladder.py
"""The ordered extraction attempts for one document (spec T7).

A ladder is a list of extractor NAMES to try in order. Rung 1 is whatever
`data/document-types.yaml` declares for the type -- so a document that
extracts cleanly on the first attempt behaves EXACTLY as it does today, and
the fallbacks exist only for the documents that would otherwise have been
written empty.

Inspection can only REMOVE rungs from the front, never reorder them, and it
has exactly ONE rule:

  no text layer  ->  go straight to OCR

Spec T7 also asked for "no structure tree -> skip OpenDataLoader". That was
MEASURED and dropped: an untagged 639-page Executive Budget scores 92.2%
through OpenDataLoader while the one document that fails is tagged, so the
rule would divert a healthy document to a slower tool and predict nothing.
See ingest/inspection.py's docstring for the numbers.

Cost: a document that needs a fallback pays extraction twice. Measured as
acceptable on 2026-08-12 -- at the calibrated floor, 2 documents of 7,434
(0.03%) are below it.
"""
from __future__ import annotations

from ingest.dispatcher import EXTRACTOR_REGISTRY
from ingest.inspection import SourceInspection

# The PDF ladder, in cost order. Not derived from the registry: this is a
# statement about the TOOLS, not about any document type.
_PDF_LADDER = ("opendataloader", "mineru", "mineru-ocr")


def ladder_for(
    doc_type: str,
    source_format: str,
    inspection: SourceInspection,
) -> list[str]:
    """Extractor names to try, in order. Empty when the combination is unknown."""
    cls = EXTRACTOR_REGISTRY.get((doc_type, source_format))
    if cls is None:
        # (budget-bill, pdf) and friends. `pick_extractor` raises on these
        # and that behaviour is unchanged; the ladder just has nothing to say.
        return []

    preferred = cls().name

    if source_format != "pdf":
        # DOCX: the structure is in the file and there is no second tool.
        return [preferred]

    if not inspection.has_text_layer:
        # A scan. Nothing above OCR can read it, so do not spend hours
        # proving that.
        return ["mineru-ocr"]

    # Start on the declared preference, keeping everything below it.
    rungs = list(_PDF_LADDER)
    if preferred in rungs:
        rungs = rungs[rungs.index(preferred):]
    return rungs
```

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_ladder.py tests/test_dispatcher.py -v`
Expected: all pass, including
`test_the_first_rung_matches_todays_shipped_routing`

- [ ] **Step 7: Commit**

```bash
git add ingest/ladder.py ingest/dispatcher.py ingest/mineru_runner.py \
        scripts/run_mineru.py tests/test_ladder.py tests/test_dispatcher.py
git commit -m "feat(ingest): MinerU OCR rung and the per-document extraction ladder"
```

---

## Task 4: Run the ladder in the worker, and hold a terminal failure out of search

**Files:**
- Modify: `ingest/jobs.py` (add `extraction_attempts`)
- Modify: `ingest/worker.py` (`run_job`, new `_extract_and_chunk`)
- Test: `tests/test_worker_ladder.py`

**Interfaces:**
- Consumes: `ingest.coverage`, `ingest.inspection`, `ingest.ladder`.
- Produces: `JobRecord.extraction_attempts: list[dict]`, each
  `{"extractor": str, "coverage": float | None, "chunks": int}`;
  `ExtractionOutcome` (`chunks`, `attempts`, `coverage`, `extractor`,
  `fell_back`) returned by `_extract_and_chunk`.

**This is the task the plan exists for. Read the whole brief before starting.**

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_worker_ladder.py
"""The extract -> check -> fall back loop (spec T5).

No real extractor and no real corpus: the ladder is driven with a stub whose
per-rung output is scripted, which is the only way to exercise "rung 1 was
empty and rung 2 was fine" deterministically.
"""
import pytest

from ingest import worker


class _ScriptedLadder:
    """Returns a coverage ratio per extractor name, in call order."""

    def __init__(self, by_extractor):
        self.by_extractor = by_extractor
        self.calls = []

    def __call__(self, name):
        self.calls.append(name)
        return self.by_extractor[name]


def test_a_document_that_passes_on_rung_one_never_runs_rung_two(monkeypatch, ladder_job):
    """The no-regression case, and the reason the ladder is safe to ship:
    a healthy document does exactly what it does today."""
    scripted = _ScriptedLadder({"opendataloader": 0.94, "mineru": 0.99})
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert scripted.calls == ["opendataloader"]
    assert outcome.fell_back is False
    assert outcome.coverage == pytest.approx(0.94)


def test_a_below_floor_first_rung_falls_back_and_the_second_wins(monkeypatch, ladder_job):
    """The FY2024 AFR: OpenDataLoader yields 2%, MinerU recovers it."""
    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert scripted.calls == ["opendataloader", "mineru"]
    assert outcome.extractor == "mineru"
    assert outcome.fell_back is True
    assert [a["extractor"] for a in outcome.attempts] == ["opendataloader", "mineru"]


def test_the_best_attempt_is_kept_when_every_rung_is_below_the_floor(monkeypatch, ladder_job):
    """Keep the highest-scoring result, not the last one tried.

    Without this, a document whose OCR rung scores 1% would discard a
    MinerU attempt that scored 9% -- throwing away the better evidence a
    human is about to look at."""
    scripted = _ScriptedLadder(
        {"opendataloader": 0.02, "mineru": 0.09, "mineru-ocr": 0.01}
    )
    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert outcome.extractor == "mineru"
    assert outcome.coverage == pytest.approx(0.09)
    assert len(outcome.attempts) == 3


def test_a_terminal_failure_never_reaches_live_and_writes_no_chunks(monkeypatch, ladder_job):
    """The whole point. A job that reports success while delivering nothing
    is worse than a job that fails."""
    written = []
    monkeypatch.setattr(worker, "_write", lambda *a, **k: written.append(a))
    scripted = _ScriptedLadder(
        {"opendataloader": 0.02, "mineru": 0.02, "mineru-ocr": 0.01}
    )

    job = worker.run_job(ladder_job, _ctx(monkeypatch, scripted))

    assert job.state == "failed"
    assert written == []
    assert len(job.extraction_attempts) == 3
    # `job.error`, NOT `stage_detail`: `advance(job, "failed")` REQUIRES an
    # error message and raises ValueError without one (jobs.py:307). A
    # message written only to stage_detail would leave `error` empty on the
    # one screen that exists to explain the failure.
    assert job.error
    assert "2%" in job.error


def test_no_text_layer_routes_straight_to_ocr(monkeypatch, ladder_job):
    scripted = _ScriptedLadder({"mineru-ocr": 0.88})
    outcome = worker._extract_and_chunk(
        ladder_job, _ctx(monkeypatch, scripted, has_text_layer=False)
    )
    assert scripted.calls == ["mineru-ocr"]
    assert outcome.fell_back is False


def test_a_rung_that_CRASHES_falls_through_to_the_next(monkeypatch, ladder_job):
    """The likeliest real trigger, and the half "resilient" was missing.

    A malformed PDF makes an extractor raise; without this the exception
    takes the job down with no rung 2, which is the same silent-ish dead end
    the ladder exists to remove. The crash is recorded as an attempt so the
    admin panel can show WHY a rung was abandoned.
    """
    def scripted(name):
        if name == "opendataloader":
            raise RuntimeError("pdfium: Data format error")
        return 0.91

    outcome = worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))

    assert outcome.extractor == "mineru"
    assert outcome.attempts[0]["extractor"] == "opendataloader"
    assert outcome.attempts[0]["coverage"] is None
    assert "Data format error" in outcome.attempts[0]["error"]


def test_every_rung_crashing_is_a_terminal_failure_not_a_traceback(
    monkeypatch, ladder_job
):
    def boom(name):
        raise RuntimeError("nope")

    job = worker.run_job(ladder_job, _ctx(monkeypatch, boom))
    assert job.state == "failed"
    assert job.error


def test_an_ocr_run_that_produces_NOTHING_is_not_treated_as_success(
    monkeypatch, ladder_job
):
    """A scan has no text layer, so coverage has no denominator and returns
    None. None must not mean "pass" unconditionally -- otherwise a scanned
    PDF whose OCR produced zero passages is written live and empty, which is
    precisely the silent-empty failure this plan exists to kill, for exactly
    the document class the OCR rung serves.
    """
    scripted = _ScriptedLadder({"mineru-ocr": None})  # no denominator, 0 chunks
    job = worker.run_job(
        ladder_job, _ctx(monkeypatch, scripted, has_text_layer=False, chunks=0)
    )
    assert job.state == "failed"


def test_a_scan_that_DOES_produce_passages_is_accepted(monkeypatch, ladder_job):
    """The other side of the same rule -- an unmeasurable document that
    plainly worked must not be rejected for being unmeasurable."""
    scripted = _ScriptedLadder({"mineru-ocr": None})
    job = worker.run_job(
        ladder_job, _ctx(monkeypatch, scripted, has_text_layer=False, chunks=140)
    )
    assert job.state == "live"


def test_the_chunker_is_told_WHICH_rung_produced_the_output(monkeypatch, ladder_job):
    """The seam a review caught: `_chunk` used to derive the reader from the
    doc_type's DEFAULT extractor, so a job that fell back to MinerU would
    parse MinerU output with the OpenDataLoader reader."""
    seen = []
    monkeypatch.setattr(worker, "_chunk", lambda job, ctx, extractor: seen.append(extractor) or [])
    scripted = _ScriptedLadder({"opendataloader": 0.02, "mineru": 0.93})
    worker._extract_and_chunk(ladder_job, _ctx(monkeypatch, scripted))
    assert seen == ["opendataloader", "mineru"]
```

> **Implementer:** write the `_ctx` helper and the `ladder_job` fixture to
> match the shapes already used in `tests/test_worker.py` — do not invent a
> second style of worker fixture. `_ctx` must monkeypatch the extraction call
> and `_chunk` so that each rung yields chunk text summing to the scripted
> ratio against a fixture source file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_worker_ladder.py -v`
Expected: FAIL — `AttributeError: module 'ingest.worker' has no attribute '_extract_and_chunk'`

- [ ] **Step 3: Add the job field**

In `ingest/jobs.py`, in `JobRecord`'s worker-state block, beside `warnings`:

```python
    # One entry per extraction method tried, in order:
    #   {"extractor": "opendataloader", "coverage": 0.02, "chunks": 20}
    # Empty on every job written before spec T5 shipped, and `from_json`
    # must keep reading those -- thousands are on the share.
    extraction_attempts: list[dict] = field(default_factory=list)
```

- [ ] **Step 4: Write the ladder loop**

In `ingest/worker.py`:

```python
@dataclass(frozen=True)
class ExtractionOutcome:
    """What the ladder produced, and what it cost to get there."""

    chunks: list[Chunk]
    attempts: list[dict]
    coverage: float | None
    extractor: str
    fell_back: bool

    @property
    def passed(self) -> bool:
        # A document that produced NO passages has failed regardless of what
        # the ratio says, and the ratio is exactly where that slips through:
        # a scan has no text layer, so there is no denominator and coverage
        # is None. Treating None as an unconditional pass would write a
        # scanned document live and empty -- the silent-empty failure this
        # whole plan exists to kill, for precisely the document class the OCR
        # rung serves. So chunks first, ratio second.
        if not self.chunks:
            return False
        if self.coverage is None:
            # Unmeasurable but non-empty. Accept: refusing it would reject
            # every scan the OCR rung exists to rescue.
            return True
        return self.coverage >= COVERAGE_FLOOR


def _extract_and_chunk(job: JobRecord, ctx: WorkerContext) -> ExtractionOutcome:
    """Extract, chunk, measure; fall back a rung and repeat if it came out empty.

    The check sits AFTER chunking and BEFORE embedding (spec T6). Extraction
    takes hours and embedding takes minutes, so measuring here catches a
    failed document before the expensive write phase is paid for, and it
    measures exactly what would have been written.
    """
    source = _ensure_source(job)
    inspection = inspect_source(source)
    rungs = ladder_for(job.doc_type, inspection.source_format, inspection)
    if not rungs:
        # Preserve today's loud failure for a genuinely unsupported pair.
        raise ValueError(
            f"no extractor for (doc_type={job.doc_type!r}, "
            f"format={inspection.source_format!r})"
        )

    attempts: list[dict] = []

    for index, name in enumerate(rungs):
        if any(a["extractor"] == name for a in job.extraction_attempts):
            # Already tried, on an earlier run of this job. Do not pay for it
            # twice after a reboot.
            attempts = [a for a in job.extraction_attempts]
            continue
        if index > 0:
            # completed_ranges is scoped to ONE rung's output directory.
            # Carrying it forward makes the next rung skip pages it has never
            # extracted -- a partial document failing coverage for a reason
            # unrelated to the extractor.
            job.completed_ranges = []
            _progress(
                job, "extracting", pct=0,
                detail=f"first attempt produced almost nothing — trying {name}",
            )
        try:
            # Each rung extracts into ITS OWN directory. Three things fall
            # out of that and all three were defects in the first draft of
            # this plan: no destructive reset between rungs; a resumed job
            # cannot mistake rung 2's half-finished output for rung 1's; and
            # the best attempt's output survives on disk for the human who
            # is about to look at the failure.
            _extract(job, ctx, extractor=dispatcher.pick_named(name), method=name)
            _check_cancelled(job)
            # The rung name is passed EXPLICITLY. `_chunk` used to derive the
            # reader from the doc_type's DEFAULT extractor, which would parse
            # MinerU output with the OpenDataLoader reader on every fallback.
            chunks = _chunk(job, ctx, extractor=name)
            coverage = coverage_ratio((c.text for c in chunks), source)
            attempts.append(
                {"extractor": name, "coverage": coverage, "chunks": len(chunks)}
            )
        except JobCancelled:
            raise
        except Exception as exc:
            # A rung that CRASHES is a rung that failed, not a job that
            # failed. A malformed PDF making one extractor raise is the
            # likeliest real trigger for the whole ladder, and letting the
            # exception out would bypass the entire mechanism.
            attempts.append(
                {"extractor": name, "coverage": None, "chunks": 0, "error": str(exc)}
            )
            chunks, coverage = [], None

        job.extraction_attempts = list(attempts)
        save(job)

        outcome = ExtractionOutcome(
            chunks=chunks,
            attempts=list(attempts),
            coverage=coverage,
            extractor=name,
            fell_back=index > 0,
        )
        if outcome.passed:
            return outcome

    # Every rung is below the floor. Return the LAST outcome, carrying every
    # attempt: nothing below the floor is ever written, so there is no "best
    # result" to select between -- only scores to report. (Spec T5 says "keep
    # whichever result scored highest"; with the hold-out rule in T8 the two
    # readings coincide, because the kept result is never used for anything
    # but its score, and every score is in `attempts`.)
    return outcome
```

and rewrite the head of `run_job`:

```python
    if job.state == "queued":
        advance(job, "extracting")

    outcome = _extract_and_chunk(job, ctx)
    _check_cancelled(job)

    if not outcome.passed:
        # Spec T8: held out of search, NOT marked live. Nothing is written,
        # so the document simply is not in the corpus -- "held out" needs no
        # separate mechanism, only the discipline of not writing it.
        #
        # A REPROCESS of an already-live document that fails every rung
        # leaves the existing chunks in place, still searchable. That is
        # deliberate: destroying a working document because a re-extraction
        # went badly would turn an attempted improvement into data loss. The
        # admin panel says the re-processing failed; the old copy stands.
        best = max((a["coverage"] or 0.0) for a in outcome.attempts)
        # The message goes through `error=`, which `advance` REQUIRES for
        # this transition (jobs.py:307) -- passing it via mark_stage's
        # `detail` alone both raises here and leaves `job.error` empty.
        advance(
            job, "failed",
            error=(
                f"Held out of search — only {best:.0%} of this document's "
                f"text produced any content, after "
                f"{len(outcome.attempts)} extraction methods were tried."
            ),
        )
        return job

    chunks = outcome.chunks
    if job.state == "extracting":
        advance(job, "chunking")
    if job.state == "chunking":
        advance(job, "embedding")
```

> **Implementer — four seams, all of them found by review of this plan's
> first draft. Do not skip any:**
>
> 1. **`_extract` resolves its own extractor.** Add `extractor=` and
>    `method=` keywords, keeping `ctx.extractor` as the test override it
>    already is. Add `dispatcher.pick_named(name)` — a one-line lookup in
>    `_EXTRACTOR_CLASSES` — rather than reaching into the dict from the
>    worker.
> 2. **`_chunk` derives the reader from the doc_type's DEFAULT extractor**
>    (`worker.py:605-608`). Add an `extractor: str` parameter and pass it
>    straight into `DocMeta.extractor`, which is what `chunk_doc` dispatches
>    on. Without this, a fallback parses MinerU output with the
>    OpenDataLoader reader.
> 3. **Extraction output becomes rung-scoped:**
>    `<data_dir>/extractor-output/<doc_id>/<method>/`. `_extract_dir(job)`
>    gains a `method` argument, and `_chunk` reads the same rung's directory.
>    **Legacy fallback required:** a job already on disk has output at the
>    un-suffixed path, so when no method subdirectory exists, fall back to
>    `<doc_id>/` — thousands of job files predate this and an interrupted
>    overnight book must still resume.
> 4. **Resume, and the `completed_ranges` trap.** `run_job` no longer guards
>    the ladder behind `job.state == "extracting"`, so a job resuming at
>    `embedding` re-enters it. Two rules make that safe, and the second is
>    **not optional**:
>
>    - **Rungs already recorded in `job.extraction_attempts` are not
>      re-run.** That list is the resume marker for which rung we reached.
>    - **`job.completed_ranges` is cleared when moving to a new rung.** It
>      records which page ranges are already extracted, and it is scoped to
>      ONE rung's output directory. Carrying it into rung 2 would make rung 2
>      skip pages it has never extracted — producing a partial document that
>      then fails coverage for a reason that has nothing to do with the
>      extractor. Clear it on every rung change, including on resume.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_worker_ladder.py tests/test_worker.py tests/test_jobs.py -v`
Expected: all pass

- [ ] **Step 6: Run the full suite — this task changes a shared path**

Run: `uv run pytest -q`
Expected: no new failures against the pre-task baseline

- [ ] **Step 7: Commit**

```bash
git add ingest/worker.py ingest/jobs.py ingest/dispatcher.py tests/test_worker_ladder.py
git commit -m "feat(ingest): run the extraction ladder; hold a terminal failure out of search"
```

---

## Task 5: Record extraction health in `documents.json`

**Files:**
- Modify: `ingest/lance_writer.py` (`write_doc`, `_merge_document_entry`,
  the `INGEST_DOCS_FIELDS` list)
- Modify: `ingest/worker.py::_write` (pass the outcome through)
- Test: extend `tests/test_lance_writer.py`

**Interfaces:**
- Consumes: `ExtractionOutcome` from Task 4.
- Produces: `documents.json` entries gain
  `"extraction": {"method": str, "coverage": float | None, "attempts": int, "fell_back": bool}`.

**Note:** `_merge_document_entry` carries an `assert set(entry) == expected`
pinned against `DOCS_FIELDS | INGEST_DOCS_FIELDS`. Adding a key without adding
it to one of those lists fails that assert — which is the guard working.

**`method` comes from the `ExtractionOutcome`, not from `DocMeta`.** A review
raised the worry that the recorded method could disagree with what chunks are
stamped with; checked, and **chunk rows carry no extractor column at all**
(`store/schema.py`), so `documents.json` is the only place the method is
recorded and there is nothing to keep in sync. Take it from the outcome
anyway — that is the value that is true after a fallback.

- [ ] **Step 1: Write the failing test**

```python
def test_a_written_document_records_how_its_extraction_went(tmp_path, ...):
    ...
    entry = json.loads((data_dir / "documents.json").read_text())["doc-1"]
    assert entry["extraction"] == {
        "method": "mineru",
        "coverage": pytest.approx(0.93),
        "attempts": 2,
        "fell_back": True,
    }


def test_a_document_written_before_this_shipped_reads_as_fine(...):
    """All 7,434 existing documents have no `extraction` key.

    Absence must never render as unknown, missing, or a warning -- the
    corpus predates the measurement and that is not a defect in it.
    """
    from store.documents import document_record

    assert document_record("legacy-doc").get("extraction") is None
    # and the consumer (Task 6) says nothing about it
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_lance_writer.py -k extraction -v`
Expected: FAIL — `KeyError: 'extraction'`

- [ ] **Step 3: Implement**

Add `"extraction"` to `INGEST_DOCS_FIELDS`, thread an `extraction: dict | None`
keyword from `write_doc` into `_merge_document_entry`, and set it in `entry`.
**Write the key unconditionally on new ingests** (as `None` when unknown) so
the pinned key-set assert stays exact.

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_lance_writer.py tests/test_documents.py -v`

- [ ] **Step 5: Commit**

```bash
git add ingest/lance_writer.py ingest/worker.py tests/test_lance_writer.py
git commit -m "feat(ingest): record extraction method and coverage in documents.json"
```

---

## Task 6: The duplicate-upload response knows whether the copy is healthy (T12)

**Files:**
- Modify: `app/routes/upload.py`
- Test: extend `tests/test_upload_route.py`

**Interfaces:**
- Consumes: `store.documents.document_record`, the `extraction` key from Task 5.
- Produces: the existing 409 body gains `"health": {"coverage": float | None,
  "recommend_reprocess": bool}`.

**The two sentences must not be swapped** — that is the whole decision, and
both are pinned.

- [ ] **Step 1: Write the failing tests**

```python
def test_a_duplicate_of_a_healthy_document_says_reprocessing_is_not_needed(client, ...):
    resp = _upload_duplicate(client, coverage=0.94)
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["health"]["recommend_reprocess"] is False
    assert "not needed" in body["message"]


def test_a_duplicate_of_a_below_floor_document_recommends_reprocessing(client, ...):
    """The FY2024 AFR case. A blanket "already ingested" warning would
    discourage exactly the re-processing this document needs."""
    resp = _upload_duplicate(client, coverage=0.02)
    assert resp.status_code == 409
    body = resp.json()["detail"]
    assert body["health"]["recommend_reprocess"] is True
    assert "recommended" in body["message"]


def test_a_duplicate_with_no_recorded_coverage_makes_no_health_claim(client, ...):
    """7,434 documents predate the measurement. Saying "unknown health" about
    all of them would be noise, and saying "healthy" would be a lie."""
    resp = _upload_duplicate(client, coverage=None)
    body = resp.json()["detail"]
    assert body["health"] is None
    assert "coverage" not in body["message"]


def test_reprocess_still_overrides(client, ...):
    """The existing escape hatch is unchanged."""
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_upload_route.py -k duplicate -v`

- [ ] **Step 3: Implement**

Read `document_record(doc_id)["extraction"]["coverage"]` in the duplicate
branch. Build the sentence from the coverage; when `extraction` is absent,
emit today's sentence unchanged and `"health": None`.

**Copy constraint (Global Constraints):** the healthy sentence says what was
measured, not that the document is good — *"Extraction produced 94% as much
text as the file contains. Re-processing is not needed."*

- [ ] **Step 4: Run the tests, then commit**

```bash
git add app/routes/upload.py tests/test_upload_route.py
git commit -m "feat(upload): a duplicate says whether the existing copy needs re-processing"
```

---

## Task 7: The "Needs attention" panel (T8)

**Files:**
- Modify: `app/routes/admin.py` (`GET /api/admin/attention`)
- Create: `webapp/src/admin/NeedsAttention.tsx`
- Modify: `webapp/src/admin/AdminPage.tsx`
- Test: extend `tests/test_admin_route.py`; create
  `webapp/src/admin/NeedsAttention.test.tsx`

**Interfaces:**
- Consumes: `ingest.jobs.load_all`, `JobRecord.extraction_attempts`.
- Produces: `GET /api/admin/attention` →
  `{"documents": [{job_id, title, best_coverage, attempts: [{extractor, coverage}]}]}`.

**Agreed layout** (Destin, 2026-08-12) — its own panel on the Admin page,
above Corpus health, **absent entirely when nothing has failed**:

```
┌─ Needs attention ──────────────── 1 ─┐
│  AGAO Annual Financial Report FY2024  │
│  Held out of search — 2% of the page  │
│  text produced any content.           │
│                                       │
│  Tried:  OpenDataLoader   2%          │
│          MinerU           2%          │
│          MinerU (OCR)     1%          │
│                                       │
│  [ Try again ]  [ Dismiss ]           │
└───────────────────────────────────────┘
```

**No new job states.** [Try again] is the existing
`POST /api/jobs/{id}/retry`; [Dismiss] is the existing
`POST /api/jobs/{id}/cancel`. The panel lists jobs in state `failed` whose
`extraction_attempts` is non-empty — an ordinary crash keeps today's queue
treatment and does not appear here.

- [ ] **Step 1: Write the failing route test**

```python
def test_attention_lists_a_held_back_document_with_what_was_tried(...):
    ...


def test_an_ordinary_crash_is_not_a_needs_attention_document(...):
    """A failed job with no extraction_attempts is a crash, not a held-back
    document, and belongs on the queue where it already is."""


def test_a_cancelled_document_leaves_the_panel(...):
    """Dismiss is cancel. No new state, no new field to forget to clear."""


def test_the_panel_is_empty_when_nothing_has_failed(...):
    assert client.get("/api/admin/attention").json()["documents"] == []
```

- [ ] **Step 2: Run to verify they fail, then implement the route**

- [ ] **Step 3: Write the failing component tests**

```tsx
it('renders nothing at all when no document needs attention', () => {
  // The empty panel is not a design element -- an admin should not be shown
  // a box explaining that nothing is wrong.
});

it('names the symptom, not the mechanism', () => {
  // "2% of the page text produced any content", never "coverage ratio below
  // COVERAGE_FLOOR" and never "the extractor returned few blocks".
});

it('lists every attempt with its score', () => {});

it('asks twice before dismissing', () => {
  // Same rule the chat-history delete follows: the armed state is a labelled
  // word, not the same glyph. Dismissing hides a document from the only
  // surface that reports it.
});
```

- [ ] **Step 4: Implement the component and mount it**

- [ ] **Step 5: Run both suites and the type build**

```bash
uv run pytest tests/test_admin_route.py -v
cd webapp && npx vitest run src/admin && npx tsc -b && npm run build
```

- [ ] **Step 6: Commit**

```bash
git add app/routes/admin.py webapp/src/admin tests/test_admin_route.py
git commit -m "feat(admin): a Needs attention panel for documents held out of search"
```

---

## Task 8: Acceptance — recover the FY2024 AFR

**Files:** none. This is a supervised run against the live dev corpus.

**Preconditions, all verified 2026-08-12 — re-verify, do not assume:**
- `eval/queries.yaml` references `agao-afr-fy2025`, **not** fy2024, so
  re-minting fy2024's `chunk_id`s breaks no ground truth (spec Risk 3).
- `agao-afr-fy2024` currently holds 20 chunks over 191 pages at 2.0% coverage.
- Its three siblings score 278–286% and are the control.

- [ ] **Step 1: Take a snapshot before touching the corpus**

```bash
uv run python -c "from store.backup import snapshot; print(snapshot())"
```

- [ ] **Step 2: Re-process the document through the real queue**

Upload it through the app with `reprocess` set, so the run exercises the
shipped path rather than a script.

- [ ] **Step 3: Assert the recovery**

Expected: the job falls back from OpenDataLoader to MinerU, records two
attempts, and lands `live` with roughly its siblings' chunk density
(~1.0 chunks/page ⇒ ~190 passages, against today's 20).

- [ ] **Step 4: READ the recovered chunks — do not just count them**

Read 8 chunks at random. **This step is not optional and not satisfied by any
metric.** The FY2024 AFR's failure mode is table rows whose figures have lost
their row labels, and a numeric-density heuristic scored exactly those rows
1.6% "junk" — apparently clean. If the recovered chunks carry bare figures
without labels, the document is **worse** than empty under Invariant 1: an
unlabelled figure is citable.

**If the recovered text is unlabelled figures, STOP and report it.** Do not
tune the floor to make it pass, and do not accept it because the ratio
improved.

- [ ] **Step 5: Run the eval and commit the results**

```bash
JLBC_DATA_DIR=... uv run python -m eval.run_eval
```

Expected: unchanged. This document holds no ground truth, so movement here
means something else moved and needs explaining.

- [ ] **Step 6: Record the outcome in STATUS.md and commit**

---

## Self-Review

**Spec coverage.** T5 → Tasks 2, 3, 4. T6 → Task 1 (floor calibrated
2026-08-12). T7 → Task 3. T8 → Tasks 4 (hold-back), 5 (sidecar), 7 (panel).
T12 → Task 6. T9 shipped in Plan A. T10 and T13 are Plan C. T11 is out of
scope by decision. Spec Risks 1 and 2 are resolved by the calibration; Risk 3
is Task 8 Step 1; Risk 4 (T9 unenforced) is unchanged and remains a Layer 2
observation.

**Known gaps, deliberate:**

- **Existing documents get no `extraction` key.** T12's health verdict
  therefore applies only to documents ingested after this ships — including,
  after Task 8, the FY2024 AFR itself. Backfilling coverage for all 7,434
  would mean a read-modify-write of the sidecar on the share for every entry,
  and "absence reads as fine" is the spec's own rule. The measurement exists
  in the calibration investigation if it is ever wanted.
- **The coverage check runs per document, never corpus-wide.** Nothing here
  re-measures what is already ingested; the FY2024 AFR is reached by Task 8
  by hand, and it is the only document below the floor.
