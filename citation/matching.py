"""Locate a figure's value inside chunk text, at the precision the answer
actually wrote (spec A4).

The match is anchored on the figure's ABSOLUTE value — one target, always.
The scale ladder only varies which multiplier the SOURCE's table used
(a document tabulating "10,297.3" under a thousands header). The old code
anchored on the value as written, which turned an unknown-scale figure
into four different targets and multiplied collisions (memo §5.2).

Returns the SOURCE's rendering, not the answer's: the PDF text layer
contains the source's form, so highlighting must search for that string.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from citation.figures import Figure, written_significant_digits

# Every grouped number in a chunk. Chunk text is machine-extracted and
# frequently fuses adjacent table cells, so this deliberately matches a
# greedy grouped run and lets the value comparison decide.
_CANDIDATE_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d+)?")
# Which multiplier the source's own rendering uses.
_SCALES = (1, 1_000, 1_000_000, 1_000_000_000)
# A near-miss farther than 5% is not "nearly the same number" to an
# analyst — report nothing rather than noise.
_NEAR_MISS_MAX = 0.05


@dataclass(frozen=True)
class SourceHit:
    chunk_id: str
    source_text: str
    start: int
    end: int
    # source value * scale_used == the figure's absolute value: 1 when the
    # source printed the absolute number, 1_000_000 when it tabulated in
    # millions.
    scale_used: int


@dataclass(frozen=True)
class NearMiss:
    chunk_id: str
    source_text: str
    value: float      # the candidate, at the scale that got closest
    distance: float   # relative distance to the figure's absolute value


def _chunk_ids(chunks: dict[str, str],
               restrict_to: list[str] | None) -> list[str]:
    if restrict_to is None:
        return list(chunks)
    return [c for c in restrict_to if c in chunks]


def find_in_chunks(
    fig: Figure,
    chunks: dict[str, str],
    *,
    restrict_to: list[str] | None = None,
    min_significant_digits: int = 4,
) -> list[SourceHit]:
    # The floor is judged on the WRITTEN digits — "$12.49B" is the four
    # digits that fingerprint it, not the eleven of its magnitude
    # (memo §5.4: the guard must apply hardest to rounded figures).
    if written_significant_digits(fig.text) < min_significant_digits:
        return []
    target = fig.absolute
    # A match must land inside the interval the written form certifies;
    # 0.5 is the floor so an exact integer still tolerates float noise.
    halfwidth = max(fig.halfwidth, 0.5)

    hits: list[SourceHit] = []
    for chunk_id in _chunk_ids(chunks, restrict_to):
        text = chunks.get(chunk_id) or ""
        for m in _CANDIDATE_RE.finditer(text):
            candidate = float(m.group(0).replace(",", ""))
            for scale in _SCALES:
                if abs(candidate * scale - target) <= halfwidth:
                    hits.append(SourceHit(chunk_id, m.group(0),
                                          m.start(), m.end(), scale))
                    break
            else:
                continue
            break  # one hit per chunk is enough to cite it
    return hits


def nearest_value(
    fig: Figure,
    chunks: dict[str, str],
    *,
    restrict_to: list[str] | None = None,
) -> NearMiss | None:
    """The closest source number to a figure that failed to link — the
    most useful thing the system knows about a failure (memo §5.5): the
    analyst catching a wrong answer needs "$12.515B is what the source
    says", not a bare refusal."""
    target = fig.absolute
    if target <= 0:
        return None
    best: NearMiss | None = None
    for chunk_id in _chunk_ids(chunks, restrict_to):
        text = chunks.get(chunk_id) or ""
        for m in _CANDIDATE_RE.finditer(text):
            candidate = float(m.group(0).replace(",", ""))
            for scale in _SCALES:
                dist = abs(candidate * scale - target) / target
                if best is None or dist < best.distance:
                    best = NearMiss(chunk_id, m.group(0),
                                    candidate * scale, dist)
    if best is None or best.distance > _NEAR_MISS_MAX:
        return None
    return best
