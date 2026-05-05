"""Tests for scripts/check_pdf_manifest.py.

We don't ship real PDFs to the test fixture — we synthesize tiny binary
files and write a manifest pointing at them, so the test runs offline.
"""

import hashlib
import subprocess
import sys
import textwrap
from pathlib import Path


def write_fixture(tmp_path: Path, files: dict[str, bytes], manifest_text: str) -> None:
    raw = tmp_path / "samples" / "raw-pdfs"
    raw.mkdir(parents=True)
    for name, content in files.items():
        (raw / name).write_bytes(content)
    (tmp_path / "samples").mkdir(exist_ok=True)
    (tmp_path / "samples" / "manifest.yaml").write_text(manifest_text)
    src = Path(__file__).parent.parent / "check_pdf_manifest.py"
    (tmp_path / "scripts").mkdir(exist_ok=True)
    (tmp_path / "scripts" / "check_pdf_manifest.py").write_text(src.read_text())


def run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "scripts/check_pdf_manifest.py"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
    )


def test_passes_when_checksum_matches(tmp_path: Path) -> None:
    content = b"%PDF-1.4\nfake\n%%EOF\n"
    sha = hashlib.sha256(content).hexdigest()
    write_fixture(
        tmp_path,
        {"a.pdf": content},
        textwrap.dedent(f"""
            documents:
              - id: a
                publisher: jlbc
                doc_type: baseline-book
                fiscal_year: 2025
                title: A
                source_url: ""
                sha256: "{sha}"
                page_count: 0
                local_path: "samples/raw-pdfs/a.pdf"
                acquired_on: ""
        """),
    )
    result = run(tmp_path)
    assert result.returncode == 0, result.stderr


def test_fails_on_checksum_mismatch(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        {"a.pdf": b"actual"},
        textwrap.dedent("""
            documents:
              - id: a
                publisher: jlbc
                doc_type: baseline-book
                fiscal_year: 2025
                title: A
                source_url: ""
                sha256: "0000000000000000000000000000000000000000000000000000000000000000"
                page_count: 0
                local_path: "samples/raw-pdfs/a.pdf"
                acquired_on: ""
        """),
    )
    result = run(tmp_path)
    assert result.returncode == 1
    assert "checksum mismatch" in result.stderr


def test_flags_orphan_file(tmp_path: Path) -> None:
    write_fixture(
        tmp_path,
        {"orphan.pdf": b"x"},
        "documents: []\n",
    )
    result = run(tmp_path)
    assert result.returncode == 1
    assert "orphan" in result.stderr
