"""The one home for "JLBC cross-cut section_kind -> corpus doc_type".

WHY this module exists: this exact mapping was hand-maintained in THREE
places -- `ingest/book_discovery.py`, `ingest/driver.py`, and
`app/book_sections.py` -- after Task 5 added the third copy. CLAUDE.md
records that this project has shipped the two-lists-that-drift bug more
than once, and the plan's Global Constraints forbid hand-maintained
vocabulary lists for exactly that reason: nothing enforces that a future
edit to one copy reaches the other two, and a silent drift here would
misroute a discovered document to the wrong extractor/chunker with no
error anywhere. One dict, three importers.

WHY "other" is deliberately NOT a key here, even though
`ingest/book_discovery.py` used to carry it: the two original call sites
disagree on purpose. `book_discovery.py` calls `.get(section_kind,
"topic-pdf")` -- an unrecognised kind falls back to `topic-pdf`.
`driver.py` calls `.get(section_kind)` and RAISES on a miss (its own
`ValueError` names this module in the message). Adding "other" here would
silently change `driver.py` from erroring to accepting an "other" kind --
a real behaviour change this refactor must not make. Leaving it out
preserves both: `book_discovery.py`'s own default still produces
`topic-pdf` for "other" (identical to before), and `driver.py`'s stricter
check is untouched.
"""
from __future__ import annotations

# section_kind (from the cross-cut TOC walkers) -> corpus doc_type.
SECTION_KIND_TO_DOC_TYPE: dict[str, str] = {
    "summary-section": "s-pdf",
    "budget-highlights": "bh-pdf",
    "budget-detail": "bd-pdf",
    "detailed-list": "detailed-list-pdf",
    "topic": "topic-pdf",
}

# The doc_type side of the mapping above, as a set -- what `app/book_sections.py`
# needs to recognise "this doc_type is a book SECTION, not a document type".
SECTION_DOC_TYPES: frozenset[str] = frozenset(SECTION_KIND_TO_DOC_TYPE.values())
