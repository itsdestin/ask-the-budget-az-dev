"""Every batch file ships with CRLF line endings.

WHY: cmd.exe reads `call :label` / `goto :label` by scanning for the label
with CR-LF semantics; an LF-only file finds the wrong offset and the
installer "flashes and closes" — the exact failure STATUS.md recorded for
the diagnostic tool on 2026-08-18 and that `install.cmd` and
`Install-JLBC-Search.cmd` were STILL carrying on 2026-08-25
(`git ls-files --eol` → i/lf). `.gitattributes` fixes the checkout; this
test fixes the next person who saves the file from an editor that strips CR.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
CMD_FILES = sorted((REPO / "packaging").rglob("*.cmd"))


def test_there_are_cmd_files_to_check():
    assert CMD_FILES, "packaging/ has no .cmd files — did the installer move?"


@pytest.mark.parametrize("path", CMD_FILES, ids=lambda p: p.name)
def test_every_cmd_file_is_crlf(path: Path):
    data = path.read_bytes()
    assert b"\r\n" in data, f"{path.name} is LF-only; cmd.exe mis-parses labels"
    bare_lf = data.replace(b"\r\n", b"").count(b"\n")
    assert bare_lf == 0, f"{path.name} mixes LF and CRLF ({bare_lf} bare LF)"
