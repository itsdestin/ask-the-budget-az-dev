"""Tests for ingest/mineru_runner.py.

A fake `mineru` stands in for the real CLI: it writes the same output layout
(`<out>/<stem>/<method>/<stem>_content_list.json` + `<stem>.md`) and prints
the same shape of per-page progress lines, so the runner can be exercised
without models, a GPU, or 1–3 minutes per page.
"""
from __future__ import annotations

import contextlib

import json
import sys
import threading
from pathlib import Path

import pytest

from ingest.mineru_runner import (
    resolve_api_url,
)
from ingest.mineru_runner import (
    MineruCancelled,
    MineruRunner,
    MineruTimeout,
    resolve_mineru_exe,
)

FAKE_MINERU = r'''
import argparse, json, sys, time
from pathlib import Path

ap = argparse.ArgumentParser()
ap.add_argument("-p"); ap.add_argument("-o"); ap.add_argument("-s", type=int)
ap.add_argument("-e", type=int); ap.add_argument("-b")
ap.add_argument("-m", default="auto")
ap.add_argument("--sleep", type=float, default=0.0)
ap.add_argument("--fail", action="store_true")
a = ap.parse_args()

if a.fail:
    print("boom: model weights not found", file=sys.stderr)
    sys.exit(3)

pdf = Path(a.p); stem = pdf.stem
n = a.e - a.s + 1
for i in range(n):
    print(f"Processing pages: {i + 1}/{n}", flush=True)
    if a.sleep:
        time.sleep(a.sleep)

out = Path(a.o) / stem / "auto"
out.mkdir(parents=True, exist_ok=True)
# page_idx is LOCAL to the requested range — the reindex bug this wrapper
# already fixed once. Emit it the way the real CLI does.
blocks = [{"type": "text", "text": f"body of page {a.s + i + 1}", "page_idx": i}
          for i in range(n)]
(out / f"{stem}_content_list.json").write_text(json.dumps(blocks))
(out / f"{stem}.md").write_text("\n\n".join(b["text"] for b in blocks))
'''


@pytest.fixture()
def fake_mineru(tmp_path):
    script = tmp_path / "fake_mineru.py"
    script.write_text(FAKE_MINERU, encoding="utf-8")
    return [sys.executable, str(script)]


@pytest.fixture()
def pdf(tmp_path):
    p = tmp_path / "27baseline-axs.pdf"
    p.write_bytes(b"%PDF-1.4\n")
    return p


# --- executable resolution --------------------------------------------------


def test_resolve_exe_prefers_env(monkeypatch, tmp_path):
    fake = tmp_path / "mineru.exe"
    fake.write_text("")
    monkeypatch.setenv("JLBC_MINERU_EXE", str(fake))
    assert resolve_mineru_exe() == [str(fake)]


def test_resolve_exe_runs_the_module_when_the_package_is_importable(monkeypatch):
    """The Windows bundle has no `mineru.exe` and no `Scripts/` — only the
    importable package. Found 2026-08-25: with nothing on PATH the old chain
    fell through to `uv run mineru`, which does not exist on office PCs, so
    every MinerU-routed upload failed in under a second."""
    import importlib.util
    import sys

    monkeypatch.delenv("JLBC_MINERU_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object() if name == "mineru" else None)
    assert resolve_mineru_exe() == [sys.executable, "-m", "mineru.cli.client"]


def test_resolve_exe_env_override_still_beats_the_module(monkeypatch, tmp_path):
    import importlib.util

    fake = tmp_path / "mineru.exe"
    fake.write_text("")
    monkeypatch.setenv("JLBC_MINERU_EXE", str(fake))
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
    assert resolve_mineru_exe() == [str(fake)]


def test_resolve_exe_falls_back_to_uv_run_in_dev(monkeypatch):
    """Dev machines without the package importable run it through uv."""
    import importlib.util

    monkeypatch.delenv("JLBC_MINERU_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: None)
    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
    assert resolve_mineru_exe() == ["uv", "run", "mineru"]


def test_resolve_exe_uses_path_when_present(monkeypatch):
    monkeypatch.delenv("JLBC_MINERU_EXE", raising=False)
    monkeypatch.setattr("shutil.which", lambda _name: r"C:\bin\mineru.exe")
    assert resolve_mineru_exe() == [r"C:\bin\mineru.exe"]


def test_resolve_exe_rejects_a_missing_env_path(monkeypatch, tmp_path):
    """A stale JLBC_MINERU_EXE must fail loudly, not silently fall through to
    a different mineru than the install pinned."""
    monkeypatch.setenv("JLBC_MINERU_EXE", str(tmp_path / "gone.exe"))
    with pytest.raises(FileNotFoundError):
        resolve_mineru_exe()


# --- running ----------------------------------------------------------------


def test_runner_reports_progress_and_writes_pages(tmp_path, fake_mineru, pdf):
    seen: list[tuple[int, int]] = []
    runner = MineruRunner(exe=fake_mineru)
    runner.run(pdf=pdf, out=tmp_path / "out", pages=[1, 2, 3],
               on_progress=lambda done, total: seen.append((done, total)))
    assert (tmp_path / "out" / "page-1.json").exists()
    assert seen and seen[-1] == (3, 3)


def test_pages_carry_reindexed_content(tmp_path, fake_mineru, pdf):
    """MinerU renumbers pages from 0 within each requested range; a page-3
    request must not come back labelled page 1."""
    runner = MineruRunner(exe=fake_mineru)
    runner.run(pdf=pdf, out=tmp_path / "out", pages=[3])
    data = json.loads((tmp_path / "out" / "page-3.json").read_text())
    assert data["page"] == 3
    assert data["blocks"][0]["text"] == "body of page 3"


def test_noncontiguous_pages_run_as_separate_ranges(tmp_path, fake_mineru, pdf):
    seen: list[tuple[int, int]] = []
    runner = MineruRunner(exe=fake_mineru)
    completed = runner.run(pdf=pdf, out=tmp_path / "out", pages=[1, 2, 9],
                           on_progress=lambda d, t: seen.append((d, t)))
    assert (tmp_path / "out" / "page-9.json").exists()
    assert completed == [[1, 2], [9, 9]]
    assert seen[-1] == (3, 3)


def test_already_completed_ranges_are_skipped(tmp_path, fake_mineru, pdf):
    """Crash-resume: the job journal replays the ranges it already finished."""
    runner = MineruRunner(exe=fake_mineru)
    runner.run(pdf=pdf, out=tmp_path / "out", pages=[1, 2, 9],
               completed_ranges=[[1, 2]])
    assert not (tmp_path / "out" / "page-1.json").exists()
    assert (tmp_path / "out" / "page-9.json").exists()


def test_cli_failure_raises_with_the_error_tail(tmp_path, fake_mineru, pdf):
    runner = MineruRunner(exe=fake_mineru + ["--fail"])
    with pytest.raises(RuntimeError, match="model weights not found"):
        runner.run(pdf=pdf, out=tmp_path / "out", pages=[1])


# --- cancel + timeout -------------------------------------------------------


def test_cancel_before_run_exits_immediately(tmp_path, fake_mineru, pdf):
    runner = MineruRunner(exe=fake_mineru)
    runner.cancel()
    with pytest.raises(MineruCancelled):
        runner.run(pdf=pdf, out=tmp_path / "out", pages=[1])


def test_cancel_mid_run_kills_the_subprocess(tmp_path, fake_mineru, pdf):
    runner = MineruRunner(exe=fake_mineru + ["--sleep", "5"])
    threading.Timer(0.5, runner.cancel).start()
    with pytest.raises(MineruCancelled):
        runner.run(pdf=pdf, out=tmp_path / "out", pages=[1, 2, 3, 4, 5, 6])
    assert runner.last_process_returncode is not None  # child was reaped


def test_timeout_kills_the_subprocess(tmp_path, fake_mineru, pdf):
    runner = MineruRunner(exe=fake_mineru + ["--sleep", "5"])
    with pytest.raises(MineruTimeout):
        runner.run(pdf=pdf, out=tmp_path / "out", pages=[1, 2, 3], timeout_s=1)


# --- offline model pinning (spec S7) ----------------------------------------


def test_local_model_source_is_pinned_when_models_are_bundled(
    tmp_path, monkeypatch, fake_mineru, pdf
):
    models = tmp_path / "models"
    models.mkdir()
    (models / "mineru.json").write_text("{}")
    monkeypatch.setenv("JLBC_MINERU_MODELS", str(models))
    env = MineruRunner(exe=fake_mineru).child_env()
    assert env["MINERU_MODEL_SOURCE"] == "local"
    assert env["MINERU_TOOLS_CONFIG_JSON"] == str(models / "mineru.json")


def test_dev_machines_keep_the_default_model_cache(monkeypatch, fake_mineru):
    """Without a bundled model dir, don't pin anything — the dev machine's
    existing HuggingFace cache is what makes MinerU work at all."""
    monkeypatch.delenv("JLBC_MINERU_MODELS", raising=False)
    env = MineruRunner(exe=fake_mineru).child_env()
    assert "MINERU_MODEL_SOURCE" not in env


# --- shared mineru-api server (JLBC_MINERU_API_URL) -------------------------


def test_api_url_is_absent_by_default(monkeypatch):
    """The office install must keep spawning its own service — unset means
    today's behavior, byte for byte."""
    monkeypatch.delenv("JLBC_MINERU_API_URL", raising=False)
    assert resolve_api_url() is None


def test_whitespace_only_api_url_is_treated_as_unset(monkeypatch):
    """A launcher exporting an empty variable must not produce `--api-url ` with
    nothing after it, which the CLI would read as the next flag."""
    monkeypatch.setenv("JLBC_MINERU_API_URL", "   ")
    assert resolve_api_url() is None


def test_api_url_is_passed_through(monkeypatch):
    monkeypatch.setenv("JLBC_MINERU_API_URL", "http://127.0.0.1:47900")
    assert resolve_api_url() == "http://127.0.0.1:47900"


def test_command_includes_api_url_only_when_set(monkeypatch, tmp_path):
    """The flag must reach the actual command line, not just the resolver."""
    seen: list[list[str]] = []

    def fake_stream(self, cmd, *, timeout_s, on_page):
        seen.append(list(cmd))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", fake_stream, raising=False)
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    runner = MineruRunner(exe=["mineru"])

    monkeypatch.delenv("JLBC_MINERU_API_URL", raising=False)
    with contextlib.suppress(_StopForTest):
        runner._run_range(
            pdf=pdf, out=tmp_path / "o", pages=[1], start=1, end=1,
            timeout_s=10, on_page=None,
        )
    assert "--api-url" not in seen[-1]

    monkeypatch.setenv("JLBC_MINERU_API_URL", "http://127.0.0.1:47900")
    with contextlib.suppress(_StopForTest):
        runner._run_range(
            pdf=pdf, out=tmp_path / "o", pages=[1], start=1, end=1,
            timeout_s=10, on_page=None,
        )
    assert seen[-1][-2:] == ["--api-url", "http://127.0.0.1:47900"]


# --- OCR rung (JLBC_MINERU method / -m flag, spec T7) -----------------------


def test_default_method_is_auto_on_the_wire(monkeypatch, tmp_path):
    """Without an explicit method, every existing caller's command line
    must be unchanged -- 'auto' is today's implicit behaviour made
    explicit, not a new default."""
    seen: list[list[str]] = []

    def fake_stream(self, cmd, *, timeout_s, on_page):
        seen.append(list(cmd))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", fake_stream, raising=False)
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    runner = MineruRunner(exe=["mineru"])

    with contextlib.suppress(_StopForTest):
        runner._run_range(
            pdf=pdf, out=tmp_path / "o", pages=[1], start=1, end=1,
            timeout_s=10, on_page=None,
        )
    assert "-m" in seen[-1]
    assert seen[-1][seen[-1].index("-m") + 1] == "auto"


def test_run_range_command_carries_the_requested_method(monkeypatch, tmp_path):
    """The seam Task 4 will drive: a runner built for the OCR rung must ask
    MinerU for OCR on the actual command line, not just remember the word
    'ocr' somewhere in Python."""
    seen: list[list[str]] = []

    def fake_stream(self, cmd, *, timeout_s, on_page):
        seen.append(list(cmd))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", fake_stream, raising=False)
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")
    runner = MineruRunner(exe=["mineru"], method="ocr")

    with contextlib.suppress(_StopForTest):
        runner._run_range(
            pdf=pdf, out=tmp_path / "o", pages=[1], start=1, end=1,
            timeout_s=10, on_page=None,
        )
    assert seen[-1][seen[-1].index("-m") + 1] == "ocr"


def test_run_batch_command_also_carries_the_requested_method(monkeypatch, tmp_path):
    """run_batch builds its OWN command line, separate from _run_range's --
    a method threaded through one and not the other would look correct in
    the single-document path and silently do nothing for a batch."""
    import pypdfium2 as pdfium

    seen: list[list[str]] = []

    def fake_stream(self, cmd, *, timeout_s, on_page):
        seen.append(list(cmd))
        raise _StopForTest()

    monkeypatch.setattr(MineruRunner, "_stream", fake_stream, raising=False)
    pdf = tmp_path / "scan.pdf"
    # run_batch probes every input with pdfium BEFORE staging it (Plan 7's
    # poison-pill guard); a placeholder byte string reads as unreadable and
    # the batch would never reach _stream at all, so this needs a document
    # pdfium can actually open.
    doc = pdfium.PdfDocument.new()
    doc.new_page(200, 200)
    doc.save(str(pdf))
    runner = MineruRunner(exe=["mineru"], method="ocr")

    with contextlib.suppress(_StopForTest):
        runner.run_batch([("doc-1", pdf, tmp_path / "o")])
    assert seen[-1][seen[-1].index("-m") + 1] == "ocr"


class _StopForTest(Exception):
    """Stops _run_range once the command line has been captured."""
