"""The report-type guidance handed to the model by `document_guide`.

Content lives in `harness/guides/*.md` rather than in Python, for the same
reason `harness/system-prompt.md` does: a non-technical successor can edit
house guidance in a Markdown file without touching code.

IN `harness/`, NOT `memo/`, AND THAT IS LOAD-BEARING. `harness/tools.py`
carries an AST import allowlist (`tests/test_harness_tools.py`) that
permits `harness` and does NOT permit `memo` or `pathlib`. Putting the
guides under `memo/` would force that allowlist open — and it is the
structural half of Invariant 7. It also keeps `memo/` to the single
responsibility its own spec gave it: a pure renderer.
"""
from __future__ import annotations

from pathlib import Path

_GUIDE_DIR = Path(__file__).with_name("guides")
_SHARED = "shared"

DEFAULT_TYPE = "research-memo"
REPORT_TYPES: tuple[str, ...] = ("research-memo", "comparison", "agency-profile")


def _read(name: str) -> str:
    """One guide file, or "" if it is missing or unreadable.

    Degrades rather than raising: a packaging slip that drops a file
    should cost the model some advice, never the turn it is in the middle
    of. `tests/test_document_guide.py::test_every_guide_file_is_present_on_disk`
    checks the files on disk, so a missing one fails the suite rather than
    passing silently — asserting `guide_for(...)` is non-empty would NOT
    do it, since a missing type file still returns the shared block.
    """
    try:
        return (_GUIDE_DIR / f"{name}.md").read_text(encoding="utf-8")
    except OSError:
        return ""


def guide_for(report_type: str | None) -> str:
    """The shared style block plus the guidance for one report type.

    An unknown, empty or non-string type resolves to `DEFAULT_TYPE`. A
    model that guesses a name should get useful guidance rather than an
    error it must spend a round-trip recovering from — and there is
    nothing it could usefully do with the error anyway. The `isinstance`
    guard rather than a bare `.strip()` is what makes `None` safe.
    """
    requested = report_type.strip() if isinstance(report_type, str) else ""
    resolved = requested if requested in REPORT_TYPES else DEFAULT_TYPE
    return f"{_read(resolved)}\n\n{_read(_SHARED)}".strip()
