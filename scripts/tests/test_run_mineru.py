"""Tests for scripts/run_mineru.py.

The wrapper is a thin CLI; we test argument parsing and the file-write
contract, not MinerU's internals (which are slow and download models).
The test injects a fake extractor function via a flag.
"""

import json
import subprocess
import sys
from pathlib import Path


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
