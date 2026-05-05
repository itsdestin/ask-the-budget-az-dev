"""Tests for scripts/run_opendataloader.py.

The wrapper is a thin CLI; we test argument parsing and the per-page
file-write contract via --dry-run, not OpenDataLoader's internals (which
boot a Java VM and parse a real PDF — slow, and covered by the smoke
test on samples/raw-pdfs/agao-afr-fy25.pdf).
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
            "scripts/run_opendataloader.py",
            "--pdf", str(pdf),
            "--out", str(out),
            "--pages", "1,3",
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    for page in (1, 3):
        page_json = out / f"page-{page}.json"
        page_md = out / f"page-{page}.md"
        assert page_json.exists()
        assert page_md.exists()
        payload = json.loads(page_json.read_text())
        assert payload["page"] == page
        assert payload["extractor"] == "opendataloader-dry-run"


def test_rejects_missing_pdf(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_opendataloader.py",
            "--pdf", str(tmp_path / "nope.pdf"),
            "--out", str(out),
            "--pages", "1",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not found" in (result.stderr + result.stdout).lower()
