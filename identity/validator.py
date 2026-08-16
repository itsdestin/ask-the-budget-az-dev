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
# A page number that a TOC scrape wrapped into the name. What actually
# distinguishes a scraped page number from a real number that belongs in a
# name is the COLUMN GAP: a printed TOC row separates the name from its page
# number with a run of >=2 spaces (the table's column separator), not one
# ordinary word-space. An earlier, narrower version of this rule fired on
# ANY 2-4 digit number preceded by a single space and was REJECTED — measured
# 2026-08-16, it quarantined real Arizona budget-document content:
# "Proposition 123" (a real education-funding ballot measure that appears
# verbatim in these books), "Laws 2008 Ch. 53", and "Fiscal Year 2027
# Budget". A single space is how a name legitimately writes a number next to
# a word; only the widened multi-space gap is the TOC's column boundary.
# The trailing boundary allows END-OF-STRING as well as whitespace: a page
# number can be the LAST token in the string (e.g. "...Arizona  286" with no
# trailing space) — caught by test_an_embedded_page_number_quarantines
# failing against this module's own first draft.
_EMBEDDED_PAGE_NUMBER = re.compile(r"\s{2,}\d{2,4}(?=\s|$)")
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


def longest_distinctive_word(name: str) -> str | None:
    """The single most specific token in `name`'s distinctive words, or
    `None` if it has none (every word was scaffolding — see
    `distinctive_words`). Exposed on its own, not just folded inside
    `mentions_agency`, because `eval/identity_check.py`'s title-vs-stamp
    check needs the actual WORD (to test it against another string's word
    set), not just a yes/no answer."""
    words = distinctive_words(name)
    return max(words, key=len) if words else None


def mentions_agency(text: str, agency_name: str) -> bool:
    """Does `text` actually corroborate that it is about `agency_name`?

    The ONE corroboration rule, used everywhere a second witness is needed
    (spec I1's "two witnesses" repair rule in `identity/compose.py`, and the
    stamping + wrong-agency metrics in `eval/identity_check.py`). It used to
    be written twice — once per module — and the two copies had DRIFTED:
    `identity/compose.py` still used "does the text contain ANY of the
    agency's distinctive words", the weaker rule `eval/identity_check.py`
    had already measured and rejected. That drift is what let the repair
    pass over-fire: a page merely saying "medicine" was accepted as
    corroborating "Osteopathic Examiners in Medicine and Surgery."

    Measured on the live corpus 2026-08-16, three candidate rules compared
    for `agency:ost` ("Osteopathic Examiners in Medicine and Surgery,
    Arizona Board of" — distinctive words {osteopathic, examiners, medicine,
    surgery}):

    * "any word" — 142 documents corpus-wide, because ordinary budget pages
      saying "medicine" or "surgery" pass;
    * **"longest word" ("osteopathic") — 732 for `agency:ost` alone against
      an independent audit's 721 (1.5% off), 1,140 corpus-wide. This is what
      ships;**
    * "all words" — 1,771 corpus-wide, over-strict: a correct document can
      phrase its own boilerplate around any one distinctive word without
      using every one of them.

    The longest word is the agency's most specific token — short shared
    words recur across the whole corpus and prove nothing about whether a
    document is really about that agency.
    """
    longest = longest_distinctive_word(agency_name)
    if not longest:
        return False
    return longest in (text or "").lower()
