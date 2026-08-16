"""Does this string look like a name? — with a REASON when it does not.

Two verdicts, and the distinction is load-bearing (spec I3):

* A DECORATION sits at the EDGE of the string and is provably additive.
  `• State Personnel Summary by Agency ......BD-13` is the printed section
  name with the printed page reference attached; removing it is
  deterministic. The alternative was measured and is worse — those summary
  sections have no agency, so quarantining them leaves the composer with
  nothing to build a name from.
* CORRUPTION sits INSIDE the string. `Arizona ... 342 Board of` cannot be
  trimmed back to a name without guessing which half is real, so it
  quarantines. A stripped string is a guess; a rejected one is a question
  with an answer.

Scope is BUDGET documents. Fiscal-note titles are constructed from the bill
number and the note's own heading and have none of the three suppliers this
module exists to distrust.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

MAX_NAME_CHARS = 90

# Leading list glyphs JLBC's TOC extraction emits.
_LEADING_GLYPH = re.compile(r"^\s*[•·▪◦*\-–—]\s+")
# A trailing run of >=2 dots, optionally followed by a printed page code
# (BD-13, S-1, 342). Anchored at the END: this is the decoration case.
_TRAILING_DECORATION = re.compile(r"\s*\.{2,}\s*[A-Z]{0,3}-?\d*\s*$")
# Any surviving run of >=2 dots is INSIDE the string.
_INNER_DOT_LEADERS = re.compile(r"\.{2,}")
# A bare integer of 2-4 digits sitting between words — a page number that
# the TOC wrapped into the name. Word-bounded on both sides so a real
# number in a name (none observed, but cheap) is not caught mid-token.
# The trailing boundary allows END-OF-STRING as well as whitespace: the
# brief's original `(?=\s)`-only form missed a page number that is the LAST
# token in the string (e.g. "...Arizona  286" with no trailing space), which
# fell through to the doubled-space check and reported the wrong reason —
# caught by test_an_embedded_page_number_quarantines failing against this
# module's own first draft.
_EMBEDDED_PAGE_NUMBER = re.compile(r"(?<=\s)\d{2,4}(?=\s|$)")
_DOUBLED_SPACE = re.compile(r"\S {2,}\S")


@dataclass(frozen=True)
class Verdict:
    ok: bool
    value: str
    reason: str | None = None
    stripped: bool = False


def validate_name(raw: str) -> Verdict:
    """Verdict for one identity string. `value` is the usable name when ok."""
    if not isinstance(raw, str):
        return Verdict(False, "", "not a string")

    original = raw
    text = _LEADING_GLYPH.sub("", raw)
    text = _TRAILING_DECORATION.sub("", text)
    text = text.strip()
    stripped = text != original.strip()

    if not text:
        return Verdict(False, "", "empty", stripped)
    if _INNER_DOT_LEADERS.search(text):
        return Verdict(False, text, "contains dot leaders", stripped)
    if _EMBEDDED_PAGE_NUMBER.search(text):
        return Verdict(False, text, "contains an embedded page number", stripped)
    if _DOUBLED_SPACE.search(text):
        return Verdict(False, text, "contains a doubled space", stripped)
    if len(text) > MAX_NAME_CHARS:
        return Verdict(False, text, f"too long (> {MAX_NAME_CHARS} chars)", stripped)
    return Verdict(True, text, None, stripped)


def distinctive_words(name: str) -> set[str]:
    """The words in `name` that actually identify an agency.

    Used to decide whether a title names the SAME agency the document's own
    text names — e.g. "Board of Barbers" vs "Barbers Board" printed two
    different ways in two different sources. Stripped of the scaffolding
    words ("department", "office", "of", "arizona", ...) that appear in
    nearly every agency name and would otherwise make every pair look like a
    match. Not a full stopword list — just the ones observed recurring
    across the agency catalog.
    """
    stop = {"of", "the", "and", "arizona", "state", "department", "office",
            "board", "commission", "az", "for", "fy"}
    return {w for w in re.findall(r"[a-z]+", name.lower()) if w not in stop}
