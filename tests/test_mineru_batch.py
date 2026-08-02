"""Tests for MineruRunner.run_batch — one model load per batch (Plan 7).

Same approach as tests/test_mineru_runner.py: a fake `mineru` stands in for
the real CLI. This one understands `-p <directory>` (MinerU's own batch
mode) and writes one output tree per input PDF, so a batch can be exercised
without models or 38 s of model loading per document.

The fake derives each document's TEXT from bytes inside the PDF
(`BODY:<word>`), never from the filename. That is deliberate: the highest-
severity failure this file guards against is two inputs with the same
original filename being confused with each other, and a fake that echoed
the filename could not tell a correct demux from a broken one.

The fixture PDFs are GENUINELY VALID PDFs — a real pdfium-written document
with the `BODY:` / `PAGES:` markers appended as a trailing comment — not
files that merely end in `.pdf`. `run_batch` probes every candidate with
pdfium before staging it (a truncated file used to abort the whole batch),
so a placeholder byte string would be rejected as a poison pill and no test
here would exercise the real path.
"""
from __future__ import annotations

import contextlib
import io
import json
import sys
import threading
from functools import lru_cache
from pathlib import Path

import pytest

from ingest.mineru_runner import (
    DEFAULT_TIMEOUT_S,
    MineruCancelled,
    MineruRunner,
    MineruTimeout,
    _unreadable_pdf_reason,
    batch_timeout_s,
)

FAKE_BATCH_MINERU = r'''
import argparse, json, re, sys, time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("-p"); ap.add_argument("-o"); ap.add_argument("-b")
ap.add_argument("--api-url")
ap.add_argument("--sleep", type=float, default=0.0)
ap.add_argument("--skip", default="")      # stems to produce NO output for
ap.add_argument("--fail", action="store_true")
a = ap.parse_args()

if a.fail:
    print("boom: model weights not found", file=sys.stderr)
    sys.exit(3)

src = Path(a.p)
pdfs = sorted(src.glob("*.pdf")) if src.is_dir() else [src]
skip = {s for s in a.skip.split(",") if s}

# The poison pill, reproduced faithfully (measured 2026-08-01): MinerU
# collects and PROBES every input with pdfium before extracting anything,
# so one file it cannot open aborts the whole invocation — rc=1 and zero
# output for all 20 documents, in ~3.3 s. This is the one failure MinerU
# is NOT per-file tolerant of, which is why run_batch filters candidates
# before staging them.
import pypdfium2
for pdf in pdfs:
    try:
        doc = pypdfium2.PdfDocument(str(pdf))
        len(doc)
        doc.close()
    except Exception as exc:
        print(f"preflight failed on {pdf.name}: {exc}", file=sys.stderr)
        sys.exit(1)

for i, pdf in enumerate(pdfs):
    print(f"Processing {pdf.name}: {i + 1}/{len(pdfs)}", flush=True)
    if a.sleep:
        time.sleep(a.sleep)
    if pdf.stem in skip:
        continue
    raw = pdf.read_text(errors="replace")
    m = re.search(r"BODY:(\S+)", raw)
    body = m.group(1) if m else pdf.stem
    m = re.search(r"PAGES:(\d+)", raw)
    n = int(m.group(1)) if m else 1

    out = Path(a.o) / pdf.stem / "auto"
    out.mkdir(parents=True, exist_ok=True)
    # page_idx is 0-based within the document, exactly as the real CLI emits it.
    blocks = [{"type": "text", "text": f"{body} page {i + 1}", "page_idx": i}
              for i in range(n)]
    (out / f"{pdf.stem}_content_list.json").write_text(json.dumps(blocks))
    (out / f"{pdf.stem}.md").write_text("\n\n".join(b["text"] for b in blocks))

if skip:
    # What the real CLI does when one file in a batch fails: report it,
    # finish the others, exit non-zero (Plan 7 ground truth 2).
    print(f"Error: {len(skip)} task(s) failed while processing documents",
          file=sys.stderr)
    sys.exit(1)
'''


@pytest.fixture()
def fake_mineru(tmp_path):
    script = tmp_path / "fake_batch_mineru.py"
    script.write_text(FAKE_BATCH_MINERU, encoding="utf-8")
    return [sys.executable, str(script)]


@lru_cache(maxsize=None)
def _blank_pdf_bytes(page_count: int) -> bytes:
    """A real, pdfium-readable PDF with `page_count` blank pages.

    Built with pypdfium2 rather than hand-written, so the bytes are exactly
    what the probe in `run_batch` has to accept. Cached because every
    fixture in this file needs one and they are identical.
    """
    import pypdfium2 as pdfium

    pdf = pdfium.PdfDocument.new()
    for _ in range(page_count):
        pdf.new_page(200, 200)
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def make_pdf(path: Path, *, body: str, pages: int = 1) -> Path:
    """A VALID PDF whose CONTENT identifies it, independent of its name.

    The markers ride in a trailing `%` comment, after `%%EOF`, so they never
    disturb the byte offsets the PDF's own cross-reference table records —
    pdfium opens the file, and the fake CLI still finds `BODY:` / `PAGES:`
    by regex over the raw bytes.

    `pages` is what the FAKE CLI is told to emit; the physical document is
    never zero pages, because pdfium rejects a page-less PDF and the
    zero-content case here is about MinerU returning nothing for a document
    it read fine (the FY2024 AFR shape), not about an unreadable file.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    marker = f"\n%BODY:{body} PAGES:{pages}\n".encode()
    path.write_bytes(_blank_pdf_bytes(max(pages, 1)) + marker)
    return path


def make_truncated_pdf(path: Path, *, keep: float = 0.9) -> Path:
    """A real PDF cut short — the poison pill, as it arrives off the wire.

    A partial download, not a file that merely has a `.pdf` name: the point
    of the probe is that pdfium rejects this while PyMuPDF opens it, so a
    fixture that is obvious garbage would not test the distinction.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    whole = _blank_pdf_bytes(6)
    path.write_bytes(whole[: int(len(whole) * keep)])
    return path


def batch_of(tmp_path, names) -> list[tuple[str, Path, Path]]:
    """(doc_id, pdf, out_dir) triples — the frozen run_batch item shape."""
    items = []
    for name in names:
        pdf = make_pdf(tmp_path / "src" / f"{name}.pdf", body=name, pages=2)
        items.append((name, pdf, tmp_path / "out" / name))
    return items


def page_text(out_dir: Path, page: int) -> str:
    data = json.loads((out_dir / f"page-{page}.json").read_text())
    return data["blocks"][0]["text"]


class _StopForTest(Exception):
    """Stops run_batch once the command line has been captured."""


# --- the happy path ---------------------------------------------------------


def test_every_document_gets_its_own_output_matched_to_its_doc_id(
    tmp_path, fake_mineru
):
    items = batch_of(tmp_path, ["doc-a", "doc-b", "doc-c"])
    runner = MineruRunner(exe=fake_mineru)

    results = runner.run_batch(items)

    assert results == {"doc-a": None, "doc-b": None, "doc-c": None}
    for doc_id, _pdf, out_dir in items:
        assert (out_dir / "page-1.json").exists()
        assert (out_dir / "page-2.json").exists()
        assert page_text(out_dir, 1) == f"{doc_id} page 1"
        assert page_text(out_dir, 2) == f"{doc_id} page 2"


def test_pages_are_absolute_and_markdown_is_written(tmp_path, fake_mineru):
    """Batch mode extracts whole documents, so page 2 must stay page 2."""
    items = batch_of(tmp_path, ["doc-a"])
    MineruRunner(exe=fake_mineru).run_batch(items)

    out_dir = items[0][2]
    assert json.loads((out_dir / "page-2.json").read_text())["page"] == 2
    assert "doc-a page 2" in (out_dir / "page-2.md").read_text()


def test_progress_reports_documents_not_pages(tmp_path, fake_mineru):
    seen: list[tuple[str, str]] = []
    items = batch_of(tmp_path, ["doc-a", "doc-b"])

    MineruRunner(exe=fake_mineru).run_batch(
        items, on_document=lambda doc_id, state: seen.append((doc_id, state))
    )

    assert seen == [("doc-a", "done"), ("doc-b", "done")]


def test_an_empty_batch_never_spawns_anything(tmp_path):
    runner = MineruRunner(exe=["definitely-not-an-executable"])
    assert runner.run_batch([]) == {}


# --- the collision guard (Plan 7 ground truth 4) ----------------------------


def test_two_inputs_with_the_same_filename_are_not_confused(
    tmp_path, fake_mineru
):
    """`508.pdf` exists in BOTH the FY2026 Baseline and the FY2026 Approps.

    MinerU names its output by input stem, so staging under the original
    filename would hand one agency's budget text to the other — plausible,
    cited, and wrong. This is the single most important test in the file.
    """
    baseline = make_pdf(tmp_path / "26baseline" / "508.pdf", body="baseline508")
    approps = make_pdf(tmp_path / "26ar" / "508.pdf", body="approps508")
    items = [
        ("jlbc-baseline-fy2026-508", baseline, tmp_path / "out" / "b508"),
        ("jlbc-approps-fy2026-508", approps, tmp_path / "out" / "a508"),
    ]

    results = MineruRunner(exe=fake_mineru).run_batch(items)

    assert results == {
        "jlbc-baseline-fy2026-508": None,
        "jlbc-approps-fy2026-508": None,
    }
    assert page_text(items[0][2], 1) == "baseline508 page 1"
    assert page_text(items[1][2], 1) == "approps508 page 1"


def test_source_pdf_records_the_original_file_not_the_staged_copy(
    tmp_path, fake_mineru
):
    """The staged copy dies with the temp directory; the provenance recorded
    in page-N.json has to point at the file that actually exists."""
    items = batch_of(tmp_path, ["doc-a"])
    MineruRunner(exe=fake_mineru).run_batch(items)

    data = json.loads((items[0][2] / "page-1.json").read_text())
    assert data["source_pdf"] == str(items[0][1])


def test_one_invocation_stages_every_pdf_under_its_doc_id(
    tmp_path, monkeypatch, fake_mineru
):
    """The whole point of the batch path: ONE process, so ONE model load.

    Also pins the staging names — filename stems collide across editions,
    doc_ids do not.
    """
    calls: list[list[str]] = []
    staged: list[list[str]] = []

    def capture(self, cmd, *, timeout_s, on_page):
        calls.append(list(cmd))
        stage = Path(cmd[cmd.index("-p") + 1])
        staged.append(sorted(p.name for p in stage.iterdir()))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", capture, raising=False)
    baseline = make_pdf(tmp_path / "26baseline" / "508.pdf", body="b")
    approps = make_pdf(tmp_path / "26ar" / "508.pdf", body="a")
    items = [
        ("jlbc-baseline-fy2026-508", baseline, tmp_path / "o1"),
        ("jlbc-approps-fy2026-508", approps, tmp_path / "o2"),
    ]

    with contextlib.suppress(_StopForTest):
        MineruRunner(exe=["mineru"]).run_batch(items)

    assert len(calls) == 1
    assert staged[0] == [
        "jlbc-approps-fy2026-508.pdf",
        "jlbc-baseline-fy2026-508.pdf",
    ]


def test_duplicate_doc_ids_in_one_batch_are_refused(tmp_path, fake_mineru):
    """Two items staged under one name would silently lose a document."""
    a = make_pdf(tmp_path / "src" / "a.pdf", body="a")
    b = make_pdf(tmp_path / "src" / "b.pdf", body="b")
    items = [("same", a, tmp_path / "o1"), ("same", b, tmp_path / "o2")]

    with pytest.raises(ValueError, match="same"):
        MineruRunner(exe=fake_mineru).run_batch(items)


@pytest.mark.parametrize("bad", ["", ".", "..", "a/b", "a\\b"])
def test_a_doc_id_that_is_not_a_plain_filename_is_refused(
    tmp_path, fake_mineru, bad
):
    """A doc_id becomes a filename in the staging directory; a separator in
    it would write outside the batch."""
    pdf = make_pdf(tmp_path / "src" / "a.pdf", body="a")
    with pytest.raises(ValueError):
        MineruRunner(exe=fake_mineru).run_batch([(bad, pdf, tmp_path / "o")])


# --- per-document failure isolation -----------------------------------------


def test_a_document_with_no_output_fails_alone(tmp_path, fake_mineru):
    """MinerU is per-file tolerant and exits non-zero when one file fails.

    That non-zero exit must not be read as a batch failure — the other 19
    documents in the batch really were extracted.
    """
    items = batch_of(tmp_path, ["doc-a", "doc-bad", "doc-c"])
    runner = MineruRunner(exe=fake_mineru + ["--skip", "doc-bad"])

    results = runner.run_batch(items)

    assert results["doc-a"] is None and results["doc-c"] is None
    assert isinstance(results["doc-bad"], str) and results["doc-bad"]
    assert page_text(items[0][2], 1) == "doc-a page 1"
    assert page_text(items[2][2], 1) == "doc-c page 1"
    # No half-made output directory: an existing one is the worker's
    # "extraction already done" signal, so a failure must leave none.
    assert not items[1][2].exists()


def test_a_failed_document_is_reported_as_failed_to_the_progress_callback(
    tmp_path, fake_mineru
):
    seen: list[tuple[str, str]] = []
    items = batch_of(tmp_path, ["doc-a", "doc-bad"])
    runner = MineruRunner(exe=fake_mineru + ["--skip", "doc-bad"])

    runner.run_batch(items, on_document=lambda d, s: seen.append((d, s)))

    assert seen == [("doc-a", "done"), ("doc-bad", "failed")]


def test_a_document_with_zero_page_content_is_a_per_document_failure(
    tmp_path, fake_mineru
):
    """An empty extraction that reported success is the FY2024 AFR shape —
    it must not leave an output directory that looks complete."""
    empty = make_pdf(tmp_path / "src" / "empty.pdf", body="empty", pages=0)
    good = make_pdf(tmp_path / "src" / "good.pdf", body="good", pages=1)
    items = [
        ("doc-empty", empty, tmp_path / "out" / "empty"),
        ("doc-good", good, tmp_path / "out" / "good"),
    ]

    results = MineruRunner(exe=fake_mineru).run_batch(items)

    assert results["doc-good"] is None
    assert results["doc-empty"] and "doc-empty" in results["doc-empty"]
    assert not items[0][2].exists()


def test_a_missing_source_pdf_fails_alone(tmp_path, fake_mineru):
    """One unreadable path must not stop its batch-mates from extracting."""
    good = make_pdf(tmp_path / "src" / "good.pdf", body="good")
    items = [
        ("doc-gone", tmp_path / "src" / "not-here.pdf", tmp_path / "out" / "g"),
        ("doc-good", good, tmp_path / "out" / "good"),
    ]

    results = MineruRunner(exe=fake_mineru).run_batch(items)

    assert results["doc-good"] is None
    assert results["doc-gone"] and "not-here.pdf" in results["doc-gone"]


# --- the poison pill (measured 2026-08-01) ----------------------------------
#
# A PDF MinerU cannot OPEN is the one failure it is not tolerant of: it dies
# in the input preflight, before extracting anything, and the whole batch
# comes back with rc=1 and no output. These tests pin that such a file is
# excluded before it is ever staged.


def test_a_truncated_pdf_fails_alone_and_its_batch_mates_extract(
    tmp_path, fake_mineru
):
    """The defect: one bad file marked all 40 of its batch-mates failed."""
    items = batch_of(tmp_path, ["doc-a", "doc-b", "doc-c"])
    poison = make_truncated_pdf(tmp_path / "src" / "doc-bad.pdf")
    items.insert(1, ("doc-bad", poison, tmp_path / "out" / "doc-bad"))

    results = MineruRunner(exe=fake_mineru).run_batch(items)

    # One entry per input, always — the frozen run_batch contract.
    assert len(results) == len(items)
    assert results["doc-bad"] and "doc-bad.pdf" in results["doc-bad"]
    for doc_id in ("doc-a", "doc-b", "doc-c"):
        assert results[doc_id] is None
    for doc_id, _pdf, out_dir in items:
        if doc_id != "doc-bad":
            assert page_text(out_dir, 1) == f"{doc_id} page 1"


def test_a_truncated_pdf_leaves_no_output_directory(tmp_path, fake_mineru):
    """An existing output directory is the worker's 'extraction already
    done' signal, so a failure must never create one."""
    good = make_pdf(tmp_path / "src" / "good.pdf", body="good")
    poison = make_truncated_pdf(tmp_path / "src" / "bad.pdf")
    items = [
        ("doc-bad", poison, tmp_path / "out" / "bad"),
        ("doc-good", good, tmp_path / "out" / "good"),
    ]

    MineruRunner(exe=fake_mineru).run_batch(items)

    assert not items[0][2].exists()
    assert items[1][2].exists()


def test_a_poison_pill_is_never_staged(tmp_path, monkeypatch, fake_mineru):
    """Excluded BEFORE staging, not filtered out of the results afterwards.

    MinerU walks the staging directory itself, so a bad file that reaches
    it is a bad file that kills the run — the CLI must never see it.
    """
    staged: list[list[str]] = []

    def capture(self, cmd, *, timeout_s, on_page):
        stage = Path(cmd[cmd.index("-p") + 1])
        staged.append(sorted(p.name for p in stage.iterdir()))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", capture, raising=False)
    good = make_pdf(tmp_path / "src" / "good.pdf", body="good")
    poison = make_truncated_pdf(tmp_path / "src" / "bad.pdf")
    items = [
        ("doc-good", good, tmp_path / "out" / "good"),
        ("doc-bad", poison, tmp_path / "out" / "bad"),
    ]

    with contextlib.suppress(_StopForTest):
        MineruRunner(exe=["mineru"]).run_batch(items)

    assert staged == [["doc-good.pdf"]]


def test_a_batch_of_only_unreadable_pdfs_never_invokes_the_cli(tmp_path):
    """Three real shapes seen off azjlbc.gov: a partial download, a 404 HTML
    body saved as .pdf, and a genuinely empty file.

    The executable does not exist, so any attempt to run it would raise —
    reaching the CLI with nothing to extract is wasted model-loading time.
    """
    src = tmp_path / "src"
    src.mkdir(parents=True, exist_ok=True)
    truncated = make_truncated_pdf(src / "truncated.pdf")
    html = src / "html.pdf"
    html.write_bytes(b"<html><body>404 Not Found</body></html>")
    empty = src / "empty.pdf"
    empty.write_bytes(b"")
    items = [
        ("doc-truncated", truncated, tmp_path / "out" / "t"),
        ("doc-html", html, tmp_path / "out" / "h"),
        ("doc-empty", empty, tmp_path / "out" / "e"),
    ]
    seen: list[tuple[str, str]] = []

    runner = MineruRunner(exe=["definitely-not-an-executable"])
    results = runner.run_batch(items, on_document=lambda d, s: seen.append((d, s)))

    assert len(results) == 3
    assert all(isinstance(r, str) and r for r in results.values())
    assert seen == [
        ("doc-truncated", "failed"),
        ("doc-html", "failed"),
        ("doc-empty", "failed"),
    ]
    assert not (tmp_path / "out").exists()


def test_the_probe_catches_what_pymupdf_would_have_waved_through(tmp_path):
    """The reason the probe uses pdfium and NOT `_pdf_page_count`.

    PyMuPDF is more tolerant than pdfium, and MinerU's preflight uses
    pdfium — so a PyMuPDF check would pass the exact file that kills the
    batch. This test measures that divergence on the fixture rather than
    asserting it in a comment. If it ever fails because PyMuPDF got
    stricter, the probe is still correct: pdfium is what MinerU uses.
    """
    pytest.importorskip("fitz")
    from ingest.dispatcher import _pdf_page_count

    poison = make_truncated_pdf(tmp_path / "src" / "bad.pdf")

    assert _pdf_page_count(poison) == 6      # PyMuPDF: looks perfectly fine

    # pdfium: rejected — and rejected without ever reaching the CLI, which
    # is the whole point (the executable named here does not exist).
    results = MineruRunner(exe=["definitely-not-an-executable"]).run_batch(
        [("doc-bad", poison, tmp_path / "out" / "bad")]
    )
    assert results["doc-bad"]


def test_the_probe_is_serialized_because_pdfium_is_not_thread_safe(tmp_path):
    """Concurrent probing must never reject a VALID PDF.

    This is the 2026-08-02 defect, reproduced: `run_batch` runs on a worker
    thread, and at `JLBC_INGEST_WORKERS=4` several threads probe at once.
    pdfium keeps global state and is not thread-safe, so concurrent use
    returned `PdfiumError: Failed to load document (PDFium: Data format
    error)` for files that are perfectly fine — **224 valid documents were
    failed in one six-minute window of a live backfill.**

    Measured on 80 real corpus PDFs with `_PDFIUM_MUTEX` removed: 0 failures
    serially, then 56 / 80 / 80 of 80 over three 4-thread rounds. This
    fixture reproduces that shape closely — 0 serially, then 34-44 / 80 / 80
    per round, 194-204 of 240 over three repeats, in ~0.3 s. With the lock
    it is exactly 0, which is what this asserts.

    Real pdfium on purpose — a mocked probe cannot exhibit a data race, so a
    fake here would pass against the broken code and pin nothing.

    WHY the fixtures are 500 pages and not the 2 the rest of this file uses:
    the race needs the threads to actually be inside pdfium together. A
    662-byte 2-page fixture is parsed too fast to overlap — measured 0 of
    600 failures unlocked, i.e. a test that proves nothing. At 500 pages the
    file is ~62 KB, the median size of a real cached corpus PDF, and the
    unlocked failure rate matches what the live backfill saw. If this ever
    needs re-tuning, tune it against that size, not downward.
    """
    files = [
        make_pdf(tmp_path / "src" / f"valid-{i:03d}.pdf", body=f"v{i}", pages=500)
        for i in range(80)
    ]
    # Sanity floor: whatever the threads report, these files are readable.
    assert [p for p in files if _unreadable_pdf_reason(p) is not None] == []

    threads_n = 4
    rejected: list[str] = []
    rejected_lock = threading.Lock()
    # A barrier so every thread is inside the probe at the same moment —
    # threads that merely start together can still end up running serially.
    gate = threading.Barrier(threads_n)

    def probe(chunk: list[Path]) -> None:
        gate.wait()
        for path in chunk:
            reason = _unreadable_pdf_reason(path)
            if reason is not None:
                with rejected_lock:
                    rejected.append(reason)

    # Three rounds: the unlocked version failed 60/80 on the first round and
    # 80/80 on the two after it, so one round alone would be the flakiest
    # possible version of this test.
    for _round in range(3):
        gate.reset()
        workers = [
            threading.Thread(target=probe, args=(files[i::threads_n],))
            for i in range(threads_n)
        ]
        for w in workers:
            w.start()
        for w in workers:
            w.join()

    assert rejected == []


def test_a_whole_batch_failure_is_reported_per_document(tmp_path, fake_mineru):
    """Even when the CLI dies outright, the caller gets one reason per
    document rather than an exception it has to map back onto 20 jobs."""
    items = batch_of(tmp_path, ["doc-a", "doc-b"])
    runner = MineruRunner(exe=fake_mineru + ["--fail"])

    results = runner.run_batch(items)

    assert set(results) == {"doc-a", "doc-b"}
    assert all("model weights not found" in r for r in results.values())


# --- cancel + timeout -------------------------------------------------------


def test_cancel_before_the_batch_starts_exits_immediately(
    tmp_path, fake_mineru
):
    items = batch_of(tmp_path, ["doc-a", "doc-b"])
    runner = MineruRunner(exe=fake_mineru)
    runner.cancel()
    with pytest.raises(MineruCancelled):
        runner.run_batch(items)
    assert not (tmp_path / "out").exists()


def test_cancel_kills_the_child_and_cancels_every_unfinished_document(
    tmp_path, fake_mineru
):
    seen: list[tuple[str, str]] = []
    items = batch_of(tmp_path, ["doc-a", "doc-b", "doc-c"])
    runner = MineruRunner(exe=fake_mineru + ["--sleep", "5"])
    threading.Timer(0.5, runner.cancel).start()

    with pytest.raises(MineruCancelled):
        runner.run_batch(items, on_document=lambda d, s: seen.append((d, s)))

    assert runner.last_process_returncode is not None  # child was reaped
    assert seen == [
        ("doc-a", "cancelled"),
        ("doc-b", "cancelled"),
        ("doc-c", "cancelled"),
    ]


def test_timeout_kills_the_child_and_raises(tmp_path, fake_mineru):
    items = batch_of(tmp_path, ["doc-a", "doc-b"])
    runner = MineruRunner(exe=fake_mineru + ["--sleep", "5"])
    with pytest.raises(MineruTimeout):
        runner.run_batch(items, timeout_s=1)


def test_the_timeout_budget_scales_with_batch_size(tmp_path):
    """A batch of 20 documents is 20 documents of work in one process, so
    reusing the per-document budget would kill healthy batches."""
    assert batch_timeout_s(1) < batch_timeout_s(5) < batch_timeout_s(20)
    assert batch_timeout_s(20) > DEFAULT_TIMEOUT_S
    assert batch_timeout_s(0) == batch_timeout_s(1)  # never a zero budget


def test_the_scaled_budget_is_what_reaches_the_child(tmp_path, monkeypatch):
    seen: list[float] = []

    def capture(self, cmd, *, timeout_s, on_page):
        seen.append(timeout_s)
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", capture, raising=False)
    items = batch_of(tmp_path, ["a", "b", "c", "d", "e"])
    runner = MineruRunner(exe=["mineru"])

    with contextlib.suppress(_StopForTest):
        runner.run_batch(items)
    assert seen[-1] == batch_timeout_s(5) != DEFAULT_TIMEOUT_S

    with contextlib.suppress(_StopForTest):
        runner.run_batch(items, timeout_s=42)
    assert seen[-1] == 42


# --- shared mineru-api server ------------------------------------------------


def test_the_api_url_flag_reaches_the_batch_command_only_when_set(
    tmp_path, monkeypatch
):
    """Same rule as the per-document path — the seam exists, unset means a
    per-invocation service (Plan 7 ground truth 8 leaves it unset)."""
    seen: list[list[str]] = []

    def capture(self, cmd, *, timeout_s, on_page):
        seen.append(list(cmd))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", capture, raising=False)
    items = batch_of(tmp_path, ["doc-a"])
    runner = MineruRunner(exe=["mineru"])

    monkeypatch.delenv("JLBC_MINERU_API_URL", raising=False)
    with contextlib.suppress(_StopForTest):
        runner.run_batch(items)
    assert "--api-url" not in seen[-1]

    monkeypatch.setenv("JLBC_MINERU_API_URL", "http://127.0.0.1:47900")
    with contextlib.suppress(_StopForTest):
        runner.run_batch(items)
    assert seen[-1][-2:] == ["--api-url", "http://127.0.0.1:47900"]
