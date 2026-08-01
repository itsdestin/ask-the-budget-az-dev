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
"""
from __future__ import annotations

import contextlib
import json
import sys
import threading
from pathlib import Path

import pytest

from ingest.mineru_runner import (
    DEFAULT_TIMEOUT_S,
    MineruCancelled,
    MineruRunner,
    MineruTimeout,
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


def make_pdf(path: Path, *, body: str, pages: int = 1) -> Path:
    """A fake PDF whose CONTENT identifies it, independent of its name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(f"%PDF-1.4\nBODY:{body}\nPAGES:{pages}\n".encode())
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
