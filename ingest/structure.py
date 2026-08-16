"""Did this extraction keep the WORDS, or only the numbers? (spec X1/X2/X3)

`ingest/coverage.py` measures VOLUME -- how much text came out. It cannot
see a document whose text all arrived with its meaning stripped off.
`agao-afr-fy2024` scores 49.0% coverage, comfortably over the floor, while
30.6% of its passages are bare figure runs like:

    34,863,017 34,863,017    -34,863,017    - - 4,423,700 ...

Under Invariant 1 an unlabelled figure is WORSE than a missing one, because
it is still citable: a model can quote it with no way to establish whether
it is revenue, an expenditure or an ending balance, or whether it is dollars
or thousands of dollars.

## What this does NOT do

It detects ONE failure shape. A document that passes has not been checked,
verified, validated or certified, and no copy anywhere may say it has. The
counterexample is live and was measured on 2026-08-13: a MinerU table chunk
scoring a perfect 0.00% here while carrying a section heading inherited from
four pages earlier that declares "(expressed in thousands)" over
whole-dollar figures -- a 1,000x error this measure cannot see, because it
counts letters and a wrong heading is made of letters.

## Why the two odd rules are load-bearing

WHITESPACE IS EXCLUDED from the denominator. Counting it scores the four
healthy AFRs at 5.5-12.9%, because JLBC and AGAO table chunks carry heavy
tab padding that dilutes the letter ratio until a fully-labelled header
chunk reads as bare. Excluding it collapses those documents to 0.0-0.5% and
leaves the broken one unchanged at 30.6%: a ~60x separation where the naive
form gave ~2.4x.

MARKUP IS STRIPPED, and this is a FORWARD-GUARD, not a fix. Chunk text
carries no tags today on any path -- `chunking/readers/mineru_reader.py`
parses MinerU's `table_body` into rows before chunking and
`chunking/builders/table_chunk.py` keeps the original HTML on a separate
`table_html` column. Stripping costs nothing and stops a future reader that
starts passing markup through from silently inflating every letter count.
Do NOT re-document it as a defect fix; an earlier draft did, and it was
wrong about this pipeline.
"""
from __future__ import annotations

import re
from typing import Iterable, Sequence

# CALIBRATED 2026-08-13 by sweeping the live 95,015-chunk corpus (both chunk
# tables -- `budget_chunks` alone omits 2,103 fiscal notes, which then score
# zero and read as catastrophically broken).
#
# LETTER_RATIO is the load-bearing number. Every value from 0.05 to 0.175
# flags exactly one document; 0.20 additionally flags two healthy JLBC
# baselines, and 0.25 flags the three healthy AGAO AFRs that are this
# spec's own control group. The plateau degrades on ONE side only, so this
# is a safe-edge pick rather than a plateau centre: 0.10 sits at double the
# margin of the 0.15 first proposed, and costs nothing measured (the known
# document scores 30.63% at every ratio from 0.05 to 0.30).
LETTER_RATIO = 0.10

# MIN_JUDGED_CHARS is INERT and that is a measurement, not a guess: 20, 30,
# 40, 50, 75, 100 and 150 all flag exactly one document, with the
# known-degraded score moving only 30.23%-30.71%. Kept at 50 because it is
# the value the original investigation used. Do not spend time tuning it.
MIN_JUDGED_CHARS = 50

# Without a minimum chunk count the signal is worthless: unrestricted, 15
# documents score >= 15% and FOURTEEN of them are 2-5 chunk documents where
# a single numeric chunk reads as 33%. A minimum of 10 removes all 14.
#
# The cost is stated plainly: 2,228 documents of 7,434 have >= 10 judged
# chunks, so ~5,200 documents are invisible to this measure entirely -- not
# judged healthy, judged not at all. A small degraded document is a real
# blind spot, not a solved problem.
MIN_JUDGED_CHUNKS = 10

# A CEILING, not a floor: a document fails by scoring ABOVE it. This is the
# opposite direction from COVERAGE_FLOOR sitting one module away, which is
# exactly how a `>` gets typed as a `<` by someone pattern-matching on the
# neighbour. 20% is the centre of a 10%-30% plateau on which every
# threshold catches the same single document; the corpus is EMPTY between
# 6.25% (the highest scoring document short of the known-degraded one, at
# the SHIPPED ratio of 0.10 -- the 7.14% quoted elsewhere for
# jlbc-baseline-fy2020-531 was measured at an abandoned ratio of 0.15, and
# that document scores 0.00% here) and 30.63%, so this is not a
# delicate choice.
MAX_UNLABELLED = 0.20

# NOT CALIBRATED -- an explicit bound, and the only number here that was
# chosen rather than measured.
#
# It exists because "keep the attempt with the lowest unlabelled fraction"
# has no lower limit on SIZE, and COVERAGE_FLOOR is only 0.10. Without this,
# an attempt that recovered 12% of a document beats one that recovered 49%
# whenever the 12% happens to be clean -- a document quietly reduced to a
# quarter of itself, written live, with the queue green. That is a NEW
# silent failure of the same family the ladder exists to prevent.
#
# 0.75 is picked to sit visibly looser than the one measured pair (49.03%
# and 44.77%, a ratio of 0.91) and visibly tighter than the floor. A band
# that FIRES is a signal to go and measure, never to widen the band.
STRUCTURE_TIE_BAND = 0.75

# Floating-point guard, not a calibrated value: `0.75 * 0.40` evaluates to
# `0.30000000000000004` in IEEE 754 double precision, so a candidate sitting
# EXACTLY on the band edge (cov == STRUCTURE_TIE_BAND * best_coverage, as the
# spec's own edge-inclusive test constructs) would be silently excluded by a
# bare `>=` comparison. Found by running the spec's verbatim test, not by
# inspection -- `test_the_band_edge_is_inclusive` failed against the
# unguarded comparison before this constant existed.
_BAND_EPSILON = 1e-9

_TAG_RE = re.compile(r"<[^>]+>")


def _strip_markup(text: str) -> str:
    # Replaced with a SPACE, not the empty string. This canNOT change
    # whether a passage reads as unlabelled: `is_unlabelled` strips
    # whitespace out of the denominator and counts individual letters, so
    # it never looks at word boundaries -- `<td>A</td><td>B</td>` and
    # `<td>A</td> <td>B</td>` score an identical ratio either way. The one
    # place the space matters is the `len(stripped) < MIN_JUDGED_CHARS`
    # gate just below, which DOES count whitespace: replacing with "" would
    # shrink a tag-heavy chunk's length and could push it under the floor
    # into "too short to judge" when the space form keeps it judgeable.
    return _TAG_RE.sub(" ", text)


def is_unlabelled(text: str) -> bool | None:
    """Is this passage almost entirely figures?

    Returns None when the passage is too short to judge -- deliberately not
    False, which would claim a measurement that was not taken.
    """
    stripped = _strip_markup(text or "")
    if len(stripped) < MIN_JUDGED_CHARS:
        return None
    non_ws = [c for c in stripped if not c.isspace()]
    if not non_ws:
        return None
    letters = sum(1 for c in non_ws if c.isalpha())
    return (letters / len(non_ws)) < LETTER_RATIO


def unlabelled_fraction(chunk_texts: Iterable[str]) -> float | None:
    """Fraction of judgeable passages that are bare figures.

    Returns None when fewer than MIN_JUDGED_CHUNKS passages could be judged.
    None means "not measured" and must never be read as 0.0, which means
    "measured, and clean" -- the same contract `coverage_ratio` uses for a
    source with no text layer, and for the same reason: a check that cannot
    see anything must not report the best possible result.
    """
    judged = 0
    bare = 0
    for text in chunk_texts:
        verdict = is_unlabelled(text)
        if verdict is None:
            continue
        judged += 1
        if verdict:
            bare += 1
    if judged < MIN_JUDGED_CHUNKS:
        return None
    return bare / judged


def choose_best(candidates: Sequence[tuple[float | None, float | None]]) -> int:
    """Index of the attempt to keep (spec X3).

    `candidates` is `(coverage, unlabelled)` per attempt, both `float |
    None`, for attempts that have ALREADY passed the coverage floor --
    filtering on the floor is the caller's job and stays exactly where it
    is today.

    Structure decides among attempts of COMPARABLE SIZE; coverage decides
    everywhere else and breaks structural ties. An attempt whose fraction
    could not be computed does not participate in structural ranking at all.
    """
    if not candidates:
        raise ValueError("choose_best requires at least one candidate")

    measured = [cov for cov, _ in candidates if cov is not None]
    best_coverage = max(measured) if measured else None

    band = [
        i
        for i, (cov, unlabelled) in enumerate(candidates)
        if unlabelled is not None
        and cov is not None
        and best_coverage is not None
        and best_coverage > 0
        and cov >= STRUCTURE_TIE_BAND * best_coverage - _BAND_EPSILON
    ]
    if band:
        # Lowest unlabelled wins; highest coverage breaks the tie.
        return min(band, key=lambda i: (candidates[i][1], -candidates[i][0]))

    # Nothing is structurally comparable -- today's behaviour, unchanged.
    # -1.0 for an unmeasurable coverage keeps it below a genuine 0.0: a
    # crash tells us nothing, while a measured zero is a real observation.
    return max(
        range(len(candidates)),
        key=lambda i: candidates[i][0] if candidates[i][0] is not None else -1.0,
    )
