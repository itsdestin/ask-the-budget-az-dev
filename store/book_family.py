"""Which JLBC book is a section a section OF? (spec B1-B2)

WHY this exists: 647 documents render under raw machine slugs -- "FY 2027
s-pdf" beside "FY 2027 Baseline" -- as if they were report families. They are
not. The doc_id stems are literally `bd1..bd10`, `bh11`, `s1`, and the
table-of-contents titles carry the matching page references ("Summary of Total
Spending Authority ... BD-10"). They are JLBC's own PRINTED PAGE-NUMBER
PREFIXES: BD-x and BH-x are page ranges in the Appropriations Report, S-x is
the Baseline's summary section. `ingest/lance_writer.py` already says so -- the
`-pdf` suffix is "a corpus-internal marker for which JLBC index page a document
came off, not something an analyst should ever read."

WHY source_url and not doc_id, which is the obvious choice: measured against
all 647, the doc_id prefix PARSES for 647 and is WRONG for 21 of them. Those 21
are the `make_doc_id` family collisions STATUS.md records -- Baseline sections
minted with an approps doc_id, e.g. `jlbc-approps-fy2022-497`, titled "General
Fund Revenue -- FY 2022 Baseline", living at azjlbc.gov/22baseline/497.pdf.
"647 of 647 parse" is a production count; the error count is what mattered.

source_url is the only independent evidence -- the address JLBC actually
published the section at. Measured: 647/647 have one, 647/647 parse, and ZERO
disagree with the document's own title. Split: Appropriations Report 389,
Baseline 258.

This does NOT repair the 21 doc_ids. Re-minting them re-points chunk_ids and
eval ground truth; that is its own work with its own re-ingest question.

MOVED here from `app/book_sections.py` for spec N1 (2026-08-12), so
`harness/corpus_map.py` can group the corpus map by book family without
`harness/` importing `app/`. `app/book_sections.py` is now a re-export shim, so
every existing consumer of that path is unaffected. This adds no import cycle:
`ingest/section_types.py` is a leaf module (no imports of its own) and
`ingest/__init__.py` is empty, so `store` -> `ingest.section_types` cannot
reach back into `store`.

Design: docs/superpowers/specs/2026-08-11-budget-docs-highlighting-and-book-sections-design.md
Corpus map: docs/superpowers/specs/2026-08-12-corpus-navigation-design.md (N1)
"""
from __future__ import annotations

import re

from ingest.section_types import SECTION_DOC_TYPES

# The five doc_types that are book SECTIONS rather than document types. Any
# other doc_type is left entirely alone -- this module only ever folds these.
# Sourced from ingest/section_types.py rather than re-declared here -- this
# exact vocabulary previously drifted across three hand-maintained copies
# (see that module's docstring); re-listing it a fourth time here would be
# the same mistake again.

# JLBC's own directory naming on azjlbc.gov, verified against all 647 section
# URLs in the live corpus: `22baseline`, `12book1` (the older Baseline
# spelling), `25ar` and `05app` (both Appropriations Report).
_BOOK_DIR = re.compile(r"azjlbc\.gov/\d{2}(baseline|book\d*|ar|app)\b", re.I)

# These two strings ("Baseline", "Appropriations Report") are displayed
# VERBATIM by webapp/src/reportFamilies.ts::familyOf and must match
# FAMILY_OF_DOC_TYPE's values there exactly -- a mismatch grows a duplicate
# family card on the browse page and breaks the `section_family` filter,
# since the two sides would then disagree on what a "Baseline" is.
_FAMILY = {
    "baseline": "Baseline",
    "book": "Baseline",
    "ar": "Appropriations Report",
    "app": "Appropriations Report",
}


def section_of(doc_type: str | None, source_url: str | None) -> str | None:
    """The report family this document is a SECTION of, or None.

    None means "not a section" -- either the doc_type is a real document type,
    or the URL cannot be read. Returning None rather than guessing keeps
    `familyOf`'s contract (spec B8): a document we cannot place still renders
    under its own doc_type instead of being dropped or mis-filed.
    """
    if doc_type not in SECTION_DOC_TYPES or not source_url:
        return None
    m = _BOOK_DIR.search(source_url)
    if not m:
        return None
    key = m.group(1).lower()
    # `book1`, `book2` -> `book`; the digit is the volume, not the family.
    return _FAMILY.get(re.sub(r"\d+$", "", key))
