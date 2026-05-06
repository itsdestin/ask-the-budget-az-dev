"""Tests for scripts/run_docx_ingest.py.

Same shape as the PDF-extractor tests: thin CLI surface tested via
--dry-run; real-DOCX behavior is covered by the manual smoke test on
samples/raw-docx/budget-bill-sb1735-2025.docx (see
samples/docx-ingest-validation.md).
"""

import json
import subprocess
import sys
import zipfile
from pathlib import Path


def make_minimal_docx(path: Path) -> None:
    """Build a tiny but valid .docx (a zip with the required parts).

    The python-docx-based wrapper is allowed to assume the input is a
    well-formed Word file; this fixture just satisfies that contract for
    the dry-run argument-parsing path.
    """
    with zipfile.ZipFile(path, "w") as z:
        z.writestr(
            "[Content_Types].xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            "</Types>",
        )
        z.writestr(
            "_rels/.rels",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>'
            "</Relationships>",
        )
        z.writestr(
            "word/document.xml",
            '<?xml version="1.0" encoding="UTF-8"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            "<w:body>"
            "<w:p><w:r><w:t>Hello world</w:t></w:r></w:p>"
            "</w:body>"
            "</w:document>",
        )


def test_writes_document_outputs_dry_run(tmp_path: Path) -> None:
    docx = tmp_path / "tiny.docx"
    make_minimal_docx(docx)
    out = tmp_path / "out"

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_docx_ingest.py",
            "--docx", str(docx),
            "--out", str(out),
            "--dry-run",
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert (out / "document.json").exists()
    assert (out / "document.md").exists()
    payload = json.loads((out / "document.json").read_text())
    assert payload["extractor"] == "python-docx-dry-run"
    assert payload["blocks"] == []


def test_rejects_missing_docx(tmp_path: Path) -> None:
    out = tmp_path / "out"
    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_docx_ingest.py",
            "--docx", str(tmp_path / "nope.docx"),
            "--out", str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert "not found" in (result.stderr + result.stdout).lower()
