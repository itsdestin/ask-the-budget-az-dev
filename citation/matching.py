"""Locate a figure's value inside chunk text, tolerating the scale the
answer rendered it in.

Returns the SOURCE's rendering of the number, not the answer's. That
distinction is load-bearing: the PDF text layer contains the source's
form, so highlighting must search for that string. The old path searched
for the answer's form and missed.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

from citation.figures import Figure

# Every grouped number in a chunk. Chunk text is machine-extracted and
# frequently fuses adjacent table cells, so this deliberately matches a
# greedy grouped run and lets the value comparison decide.
_CANDIDATE_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")

# Multipliers between the answer's WRITTEN value and the source's
# rendering. The ladder is walked from the written value, not from the
# context-scaled one: a header-scaled "$8,287.7" must be findable both as
# 8,287,700,000 (the document's usual absolute form) and as 8,287.7 (a
# document that happens to tabulate in millions too). Scaling first and
# then walking the ladder can only find the former.
_SCALES = (1, 1_000, 1_000_000, 1_000_000_000)

# A faithful rounding ("$1,391.2 million" for 1,391,157,700) differs by
# well under 0.1%; a neighbouring budget line differs by far more.
_REL_TOL = 0.001


@dataclass(frozen=True)
class SourceHit:
    chunk_id: str
    source_text: str
    start: int
    end: int
    # How many times larger the source's rendering is than the figure as
    # the answer wrote it: 1 when both print the same magnitude,
    # 1,000,000 when the answer said "$8,287.7" and the source printed
    # "8,287,700,000".
    scale_used: int


def _significant_digits(value: float) -> int:
    """Digits before the decimal point, ignoring trailing zeros — a proxy
    for how distinctive a figure is. 37 scores 2; 1,320,598,100 scores 9."""
    whole = int(abs(value))
    if whole == 0:
        return 0
    return len(str(whole))


def find_in_chunks(
    fig: Figure,
    chunks: dict[str, str],
    *,
    min_significant_digits: int = 4,
) -> list[SourceHit]:
    # The floor is judged on the figure's real magnitude, so "$1.06
    # billion" is measured as the billion it is rather than as one digit.
    if _significant_digits(fig.absolute) < min_significant_digits:
        return []
    # ...but the search walks out from the value as WRITTEN, so the
    # context scale is a hint that widens the search rather than a
    # conversion applied before it.
    written = fig.value

    hits: list[SourceHit] = []
    for chunk_id, text in chunks.items():
        for m in _CANDIDATE_RE.finditer(text or ""):
            raw = m.group(0)
            candidate = float(raw.replace(",", ""))
            for scale in _SCALES:
                if math.isclose(candidate, written * scale,
                                rel_tol=_REL_TOL, abs_tol=0.5):
                    hits.append(SourceHit(chunk_id, raw, m.start(), m.end(),
                                          scale))
                    break
            else:
                continue
            break  # one hit per chunk is enough to cite it
    return hits
