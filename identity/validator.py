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
    (spec I1's "two witnesses" repair rule in `identity/compose.py`, the
    stamping + wrong-agency metrics in `identity/check.py`, and the
    per-agency label audit in `identity/label_audit.py` that gates the
    whole labelling fix). It used to be written twice — once per module —
    and the two copies had DRIFTED: `identity/compose.py` still used "does
    the text contain ANY of the agency's distinctive words", the weaker
    rule that let the repair pass over-fire: a page merely saying "medicine"
    was accepted as corroborating "Osteopathic Examiners in Medicine and
    Surgery." That was fixed by moving both callers to "longest word" — but
    "longest word" carries its OWN defect, found only once title repair
    started proposing real renames: for "Highway Safety, Governor's Office
    of" the longest distinctive word is "governor", which appears on nearly
    every budget document (the Governor transmits the whole budget), so an
    utterly unrelated document — e.g. a Liquor Licenses page that merely
    mentions "the Governor's Office recommends no change" — passed as
    corroborating the Highway Safety label.

    Re-measured on the live corpus 2026-08-16 (`identity.label_audit`,
    83,016 `budget_chunks` rows / 5,356 documents), against `agency:ost`
    ("Osteopathic Examiners in Medicine and Surgery, Arizona Board of" —
    distinctive words {osteopathic, examiners, medicine, surgery}) and the
    four known-clean agencies (`tre`, `gam`, `adc`, `axs` — each has exactly
    one distinctive word, so every candidate rule agrees on them and all
    four MUST stay at 0% or the "fix" is worse than the defect):

    | rule | ost error rate | corpus `total_unmentioned` | tre/gam/adc/axs | Highway Safety case |
    |---|---|---|---|---|
    | "longest word" (was shipped) | 732/992 = 73.8% | 1,128 | 0/0/0/0 | **WRONGLY corroborates** ("governor") |
    | "all words present" | 927/992 = **93.4%** (worse) | 1,771 | 0/0/0/0 | correctly rejects |
    | "majority (>=half, min 1) present" | 673/992 = 67.8% | 925 | 0/0/0/0 | **WRONGLY corroborates** |

    **None of the three separates the classes** — "longest" and "majority"
    both wrongly corroborate the motivating false-positive case; "all"
    rejects it correctly but makes `ost` WORSE than the rule it would
    replace, because a correct document can phrase its own boilerplate
    around any one distinctive word without using every single one. So a
    fourth rule ships instead:

    **"majority (>=half, minimum 1), counting only distinctive words of at
    least 3 characters."** Measured: `ost` 673/992 = 67.8% (same as
    unfiltered majority — the short tokens it drops never decided an `ost`
    document either way), `total_unmentioned` 962, all four clean agencies
    still 0/0/0/0, and the Highway Safety case now correctly rejects.

    Why the length-3 floor, not a new stopword: `distinctive_words` splits
    on the regex `[a-z]+`, so a possessive apostrophe silently mints a
    junk one-letter "word" — "Governor's" -> {"governor", "s"} — and "in"
    (as in "Examiners **in** Medicine") isn't on its stopword list either.
    Neither is a real distinguishing token, and both are exactly why
    "majority" alone still corroborated Highway Safety: "governor" plus the
    stray "s" (itself minted from an unrelated "agency's" elsewhere in the
    same test sentence) made 2 of 4 words "present", clearing the >=half
    bar by coincidence. Filtering by length inside THIS function — not by
    editing `distinctive_words`, which four other call sites depend on
    unchanged — removes the coincidence without touching anyone else's
    behaviour. Checked against the full 157-agency catalog: 10 agencies
    have at least one word this filter removes, and NONE is left with zero
    distinctive words afterward — the filter never silently disables an
    agency the way a two-word minimum would.

    A single-word agency name (`AHCCCS`) still corroborates correctly: one
    word, minimum-1 applies, and "ahcccs" is 6 characters.
    """
    words = {w for w in distinctive_words(agency_name) if len(w) >= 3}
    if not words:
        return False
    haystack = (text or "").lower()
    present = sum(1 for w in words if w in haystack)
    needed = max(1, (len(words) + 1) // 2)  # at least half, rounded up; minimum 1
    return present >= needed
