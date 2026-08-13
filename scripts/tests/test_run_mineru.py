"""Tests for scripts/run_mineru.py.

The wrapper is a thin CLI; we test argument parsing and the file-write
contract, not MinerU's internals (which are slow and download models).
The test injects a fake extractor function via a flag.
"""

import json
import subprocess
import sys
from pathlib import Path
from typing import Callable

# `scripts/` has no __init__.py, so pytest's rootdir insertion puts
# `scripts/tests/` on sys.path, not `scripts/` itself. Add it explicitly --
# the same trick ingest/dispatcher.py's `_import_phase0_module` uses -- so
# the method-flag tests below can call `run_mineru()` directly instead of
# only ever driving it through the CLI subprocess.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import run_mineru as run_mineru_mod  # noqa: E402


def test_writes_per_page_outputs_to_target_dir(tmp_path: Path) -> None:
    pdf = tmp_path / "tiny.pdf"
    pdf.write_bytes(b"%PDF-1.4\nfake\n%%EOF\n")
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_mineru.py",
            "--pdf", str(pdf),
            "--out", str(out),
            "--pages", "1",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    page_json = out / "page-1.json"
    page_md = out / "page-1.md"
    assert page_json.exists()
    assert page_md.exists()
    payload = json.loads(page_json.read_text())
    assert payload["page"] == 1
    assert payload["extractor"] == "mineru-dry-run"


def test_rejects_missing_pdf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_mineru.py",
            "--pdf", str(tmp_path / "nope.pdf"),
            "--out", str(out),
            "--pages", "1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not found" in (result.stderr + result.stdout).lower()


# --- the `-m` / method flag --------------------------------------------------
#
# Neither test above exercises `run_mineru()` itself -- the dry-run path
# never builds a `mineru` command line at all. `ingest.dispatcher.
# MinerUOcrExtractor` calls this function with `method="ocr"`; if that
# never reached the actual subprocess command, OCR mode would silently
# never run and a scanned document would keep coming back empty. These
# tests replace `subprocess.run` so they can inspect the exact argv without
# needing a real `mineru` on PATH.


class _FakeResult:
    def __init__(self, returncode: int = 0) -> None:
        self.returncode = returncode
        self.stdout = ""
        self.stderr = ""


def _make_fake_run(seen_cmds: list) -> Callable[..., object]:
    """A `subprocess.run` stand-in that writes MinerU's expected output
    shape so `_read_mineru_output` (called right after) has something real
    to read, rather than raising `mineru produced no output dir`."""

    def fake_run(cmd, capture_output, text):
        seen_cmds.append(list(cmd))
        out_dir = Path(cmd[cmd.index("-o") + 1])
        pdf_stem = Path(cmd[cmd.index("-p") + 1]).stem
        method = cmd[cmd.index("-m") + 1]
        doc_dir = out_dir / pdf_stem / method
        doc_dir.mkdir(parents=True)
        (doc_dir / f"{pdf_stem}_content_list.json").write_text("[]")
        (doc_dir / f"{pdf_stem}.md").write_text("")
        return _FakeResult()

    return fake_run


def test_run_mineru_defaults_to_auto_method(tmp_path: Path, monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr(run_mineru_mod.subprocess, "run", _make_fake_run(seen))
    pdf = tmp_path / "src.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    run_mineru_mod.run_mineru(pdf, tmp_path / "out", [1])

    assert seen[-1][-2:] == ["-m", "auto"]


def test_run_mineru_threads_the_ocr_method_to_the_cli(tmp_path: Path, monkeypatch) -> None:
    seen: list = []
    monkeypatch.setattr(run_mineru_mod.subprocess, "run", _make_fake_run(seen))
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    run_mineru_mod.run_mineru(pdf, tmp_path / "out", [1], method="ocr")

    assert seen[-1][-2:] == ["-m", "ocr"]


def test_run_mineru_passes_method_per_range(tmp_path: Path, monkeypatch) -> None:
    """Non-contiguous pages run as separate CLI invocations (`_contiguous_
    ranges`); the method must not be lost after the first one."""
    seen: list = []
    monkeypatch.setattr(run_mineru_mod.subprocess, "run", _make_fake_run(seen))
    pdf = tmp_path / "scan.pdf"
    pdf.write_bytes(b"%PDF-1.4\n")

    run_mineru_mod.run_mineru(pdf, tmp_path / "out", [1, 5], method="ocr")

    assert len(seen) == 2
    assert all(cmd[-2:] == ["-m", "ocr"] for cmd in seen)
