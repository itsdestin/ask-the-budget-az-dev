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

import re
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


@pytest.mark.parametrize("path", CMD_FILES, ids=lambda p: p.name)
def test_every_cmd_file_is_ascii(path: Path):
    """cmd.exe reads a .bat in the machine's OEM code page (437/850 here), not
    UTF-8. A curly quote, an em dash or a section sign pasted from a spec is
    rendered as mojibake at best, and inside a quoted path or an `if` argument
    it changes what the line MEANS. Keep the installers to plain ASCII."""
    data = path.read_bytes()
    bad = {b for b in data if b > 0x7F}
    assert not bad, (f"{path.name} has non-ASCII bytes "
                     f"{sorted(hex(b) for b in bad)}; cmd reads it as OEM, not UTF-8")


@pytest.mark.parametrize("path", CMD_FILES, ids=lambda p: p.name)
def test_every_goto_and_call_target_exists(path: Path):
    """A mistyped label is the classic flash-and-close: cmd.exe prints
    "The system cannot find the batch label specified" into a console window
    that closes with it, so the user sees nothing at all. `:eof` is built in."""
    text = path.read_text(encoding="ascii")
    # NOT anchored at the start of the line: nearly every jump in these files
    # is `if exist ... goto :label`, and a start-anchored pattern found none
    # of them — it passed against a deliberately mistyped target. Comment and
    # echo lines are dropped so prose about a label is not read as a jump.
    code = [ln for ln in text.splitlines()
            if not re.match(r"(?i)\s*(rem\b|::|echo\b)", ln)]
    targets: set[str] = set()
    for m in re.finditer(r"(?i)\b(?:goto|call)\s+:?(\w+)", "\n".join(code)):
        targets.add(m.group(1).lower())
    defined = {m.group(1).lower() for m in re.finditer(r"(?m)^\s*:(\w+)", text)}
    # The guard on the guard: a pattern that matches nothing passes silently,
    # which is exactly how the first version of this test shipped green.
    assert targets, f"{path.name}: found no goto/call targets at all"
    missing = sorted(t for t in targets - defined if t != "eof")
    assert not missing, f"{path.name} jumps to labels that do not exist: {missing}"
