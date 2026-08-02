"""Map natural-language phrases in a query onto real `doc_type` values (Q1).

An EXACT match here becomes a HARD `doc_type` filter in `retrieve()`, which
is why this module is a hand-written phrase table rather than anything
fuzzy. `doc_type` is a plain equality filter: a value the corpus does not
actually use ("appropriations-report", "baseline-book") matches nothing at
all and returns an empty page with no error anywhere. So the table maps ONTO
the ten values the corpus really carries, and `test_query_doc_type.py` pins
that nothing else is ever emitted:

    approps-per-agency   JLBC Appropriations Report per-agency entry
    baseline-per-agency  JLBC Baseline Book per-agency chapter
    detailed-list-pdf    JLBC detailed program/activity lists
    governors-budget     Governor's Executive Budget
    s-pdf                JLBC summary sections
    afr                  AGAO Annual Financial Report
    bd-pdf               JLBC Baseline supporting/detail documents
    topic-pdf            JLBC one-off topical reports
    bh-pdf               JLBC Budget Highlights
    budget-bill          The Legislature's enacted budget bill

Two rules do the safety work:

**Longest phrase wins.** Phrases are tried longest-first at each position and
matched non-overlapping, so "appropriations report" resolves as one phrase
and can never be re-read as a bare "report".

**Two-letter shorthand is WEAK.** `ar` is the JLBC abbreviation for the
Appropriations Report and also an ordinary fragment of English; the same
reasoning that makes `doc` a weak agency match applies. A WEAK match earns a
boost, never a hard filter, because a wrong hard filter empties the page for
a question the analyst asked in good faith (see `query_match.is_filterable`).

Deliberately ABSENT from the table: bare "appropriation"/"appropriations",
"budget", and "report". They appear in a large share of budget questions
("ADC General Fund appropriation"), so filtering on them would delete most
of the corpus for a query that named no document type at all.
"""
from __future__ import annotations

import re

from retrieval.query_match import Confidence, Match
from retrieval.query_year import iter_jlbc_shorthand

# phrase -> (doc_type, confidence).
#
# Everything here is a phrase an analyst types when they mean a specific
# publication. Keep additions conservative: a phrase that is ALSO ordinary
# budget English belongs out of this table, not in it as WEAK, because the
# boost it would earn still competes with reranker scores.
_PHRASES: dict[str, tuple[str, Confidence]] = {
    # -- JLBC Appropriations Report -----------------------------------------
    "appropriations report": ("approps-per-agency", Confidence.EXACT),
    "appropriation report": ("approps-per-agency", Confidence.EXACT),
    "approps report": ("approps-per-agency", Confidence.EXACT),
    "approp report": ("approps-per-agency", Confidence.EXACT),
    "approps": ("approps-per-agency", Confidence.EXACT),
    # "ar" is JLBC's own abbreviation (and its URL directory: /26AR/508.pdf),
    # but two letters are far too small a fingerprint to hard-filter on.
    "ar": ("approps-per-agency", Confidence.WEAK),
    # -- JLBC Baseline Book -------------------------------------------------
    "baseline book": ("baseline-per-agency", Confidence.EXACT),
    "baseline report": ("baseline-per-agency", Confidence.EXACT),
    "baseline": ("baseline-per-agency", Confidence.EXACT),
    # -- AGAO Annual Financial Report ---------------------------------------
    "comprehensive annual financial report": ("afr", Confidence.EXACT),
    "annual comprehensive financial report": ("afr", Confidence.EXACT),
    "annual financial report": ("afr", Confidence.EXACT),
    "financial report": ("afr", Confidence.EXACT),
    "acfr": ("afr", Confidence.EXACT),
    "afr": ("afr", Confidence.EXACT),
    # -- Governor's Executive Budget ----------------------------------------
    "governor's executive budget": ("governors-budget", Confidence.EXACT),
    "governor's recommended budget": ("governors-budget", Confidence.EXACT),
    "governor's recommendation": ("governors-budget", Confidence.EXACT),
    "governor's budget": ("governors-budget", Confidence.EXACT),
    "executive budget request": ("governors-budget", Confidence.EXACT),
    "executive recommendation": ("governors-budget", Confidence.EXACT),
    "executive budget": ("governors-budget", Confidence.EXACT),
    # -- The enacted bill ---------------------------------------------------
    "general appropriation act": ("budget-bill", Confidence.EXACT),
    "appropriations bill": ("budget-bill", Confidence.EXACT),
    "appropriation bill": ("budget-bill", Confidence.EXACT),
    "budget bill": ("budget-bill", Confidence.EXACT),
    "feed bill": ("budget-bill", Confidence.EXACT),
    # -- JLBC cross-cut section families ------------------------------------
    "detailed list of appropriations": ("detailed-list-pdf", Confidence.EXACT),
    "detailed list": ("detailed-list-pdf", Confidence.EXACT),
    "detail list": ("detailed-list-pdf", Confidence.EXACT),
    "budget highlights": ("bh-pdf", Confidence.EXACT),
    "budget detail": ("bd-pdf", Confidence.EXACT),
    "summary section": ("s-pdf", Confidence.EXACT),
    "summary sections": ("s-pdf", Confidence.EXACT),
    "summary document": ("s-pdf", Confidence.EXACT),
    "budget summary": ("s-pdf", Confidence.EXACT),
    "topic report": ("topic-pdf", Confidence.EXACT),
    "topic reports": ("topic-pdf", Confidence.EXACT),
    "topical report": ("topic-pdf", Confidence.EXACT),
}


def _phrase_pattern(phrase: str) -> str:
    """One phrase as a regex fragment.

    Whitespace between words is elastic (`\\s+`) so a double space or a line
    break in a pasted question still matches, and an apostrophe is optional
    and accepts the curly form — "governors budget", "governor's budget" and
    "governor’s budget" are the same question typed by three people.
    """
    words = [re.escape(w).replace("'", "['’]?") for w in phrase.split()]
    return r"\s+".join(words)


# One alternation, longest phrase first. Python's `|` is leftmost-FIRST, not
# leftmost-longest, so this ordering is what makes "appropriations report"
# win over "appropriations"; `finditer` then skips past the whole match, so
# a shorter phrase sitting inside a longer one is never re-matched.
#
# `(?<!\w)` / `(?!\w)` rather than `\b`: they also stop "ar" from matching
# inside "27ar", which the JLBC-shorthand path below owns.
_PHRASE_RE = re.compile(
    r"(?<!\w)(?:"
    + "|".join(_phrase_pattern(p) for p in sorted(_PHRASES, key=len, reverse=True))
    + r")(?!\w)",
    re.IGNORECASE,
)


def parse_query_doc_types(query: str) -> list[Match]:
    """Document types named in `query`, in the order they appear.

    Returns `[]` when the query names none — the signal callers read as "no
    doc_type filter, let the search fan out across every publication".

    Each `doc_type` appears at most once. When the same type is named twice
    at different strengths ("27ar appropriations report ar", say), the EXACT
    reading wins: the stronger evidence is real evidence, and
    `is_filterable` is all-or-nothing, so leaving the weak duplicate in would
    demote the whole set to a boost.
    """
    if not query or not query.strip():
        return []

    found: list[tuple[int, Match]] = []

    # JLBC's own URL shorthand ("27ar", "21baseline") — spec Q5. These are
    # EXACT even though a bare "ar" is WEAK: the two-digit fiscal year glued
    # to the front is exactly the disambiguation a stray English "ar" lacks.
    cursor = 0
    for _year, doc_type, matched_text in iter_jlbc_shorthand(query):
        # Re-locate the span so the results can be ordered by where they
        # appear. The cursor advances so a query naming the same shorthand
        # twice reports the second one's real position, not the first's.
        start = query.find(matched_text, cursor)
        cursor = start + len(matched_text) if start >= 0 else cursor
        found.append((max(start, 0), Match(doc_type, Confidence.EXACT, matched_text)))

    for match in _PHRASE_RE.finditer(query):
        text = match.group(0)
        # The table is keyed on the canonical spelling; the regex matched a
        # possibly differently-cased/spaced/apostrophed rendering of it.
        doc_type, confidence = _PHRASES[_canonical_key(text)]
        found.append((match.start(), Match(doc_type, confidence, text)))

    best: dict[str, tuple[int, Match]] = {}
    for start, match in found:
        prior = best.get(match.value)
        if prior is None:
            best[match.value] = (start, match)
            continue
        prior_start, prior_match = prior
        if (
            prior_match.confidence is Confidence.WEAK
            and match.confidence is Confidence.EXACT
        ):
            # Keep the earlier position so ordering still reflects the query.
            best[match.value] = (min(prior_start, start), match)

    return [m for _start, m in sorted(best.values(), key=lambda pair: pair[0])]


def _canonical_key(matched_text: str) -> str:
    """Fold a matched span back onto its `_PHRASES` key.

    Undoes exactly what `_phrase_pattern` allowed to vary: case, run-length
    of whitespace, and the curly apostrophe. An apostrophe the analyst
    omitted is restored by trying both spellings.
    """
    text = " ".join(matched_text.lower().split()).replace("’", "'")
    if text in _PHRASES:
        return text
    # "governors budget" -> "governor's budget"
    for key in _PHRASES:
        if "'" in key and key.replace("'", "") == text.replace("'", ""):
            return key
    raise KeyError(matched_text)  # pragma: no cover - regex is built from the table
