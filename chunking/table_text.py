"""The vocabulary of a JLBC operating table.

Shared by phase A (`retrieval/table_view.py`, the labelled rendering the
model reads) and phase B (`chunking/readers/text_layer_table.py`, the
text-layer rebuild) so the two can never disagree about what a year
header, a figure or a footnote marker looks like. Spec:
docs/superpowers/specs/2026-08-26-agency-table-rebuild-design.md §3.1, §5.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Sequence

# Spec D1: only these two document types carry the operating table.
OPERATING_TABLE_DOC_TYPES = frozenset({"approps-per-agency", "baseline-per-agency"})

# Spec D1: a table is in scope when its text carries one of these.
LADDER_MARKERS = ("OPERATING SUBTOTAL", "FUND SOURCES", "AGENCY TOTAL", "TOTAL - ALL SOURCES")

# `FY 2024`, `FY2024`. The year is group 1.
YEAR_RE = re.compile(r"\bFY ?(\d{4})\b")
# The second header line. Case-insensitive because FY2006 prints `Actual`.
KIND_RE = re.compile(r"^(ACTUAL|ESTIMATE|EST\.?|APPROVED|BASELINE)$", re.IGNORECASE)
# A printed figure: optional accounting parentheses, optional `$`, comma
# groups, optional decimals (FTE prints one). A bare `0` matches too.
FIGURE_RE = re.compile(r"\(?\$?\d{1,3}(?:,\d{3})*(?:\.\d+)?\)?")
# A footnote marker: `3/`, `8/-13/`, `12/13/`, `1/2/`.
MARKER_RE = re.compile(r"\d{1,2}/(?:-?\d{1,2}/)*")

# The two fused shapes MinerU (and the FY2006 text layer) print: a
# comma-grouped figure or a one-decimal FTE with the marker glued on.
# `\d{3}` after each comma is exact, so `99,294,5003/` can only split as
# `99,294,500` + `3/`. A figure under 1,000 (`5003/`) has no comma group
# and is ambiguous, so it is deliberately not matched.
_FUSED_COMMA = re.compile(r"^(\(?\$?\d{1,3}(?:,\d{3})+\)?)(\d{1,2}/(?:-?\d{1,2}/)*)$")
_FUSED_DECIMAL = re.compile(r"^(\(?\$?\d{1,3}(?:,\d{3})*\.\d)(\d{1,2}/(?:-?\d{1,2}/)*)$")

_DASHES = str.maketrans({"–": "-", "—": "-", "−": "-"})


def has_ladder_marker(text: str) -> bool:
    return any(m in text for m in LADDER_MARKERS)


def normalise_label(s: str) -> str:
    """Upper-case, one space between words, ASCII dashes, trailing footnote
    markers and colons removed. Used to compare a printed label with a
    MinerU label and to classify rows in the gate."""
    s = " ".join(s.translate(_DASHES).split()).upper()
    # Strip any run of markers at the end (`MEDICAID SERVICES 5/6/7/`).
    s = re.sub(r"(\s*\d{1,2}/(?:-?\d{1,2}/)*)+$", "", s)
    return s.rstrip(":").strip()


def split_figure_marker(word: str) -> tuple[str, str | None]:
    """`99,294,5003/` -> (`99,294,500`, `3/`); anything else -> (word, None)."""
    for rx in (_FUSED_COMMA, _FUSED_DECIMAL):
        m = rx.match(word)
        if m:
            return m.group(1), m.group(2)
    return word, None


def _is_figure(token: str) -> bool:
    return token in ("-", "0") or FIGURE_RE.fullmatch(token) is not None


def peel_markers(cell: str) -> str:
    """Render every footnote marker in a cell as ` [3/]` after its figure,
    so the digits of the marker never touch the digits of the figure.
    A marker already separated by a space gets the same brackets."""
    out: list[str] = []
    for tok in cell.split():
        fig, mk = split_figure_marker(tok)
        if mk is not None:
            out.extend([fig, f"[{mk}]"])
        elif MARKER_RE.fullmatch(tok) and out and _is_figure(out[-1]):
            out.append(f"[{tok}]")
        else:
            out.append(tok)
    return " ".join(out)


def figure_tokens(cell: str) -> list[str]:
    """The figures in a cell, markers peeled away. Two of them means a
    merged cell (spec §1)."""
    return [t for t in peel_markers(cell).split() if _is_figure(t)]


@dataclass(frozen=True)
class Header:
    labels: dict[int, str]   # column index -> column label
    rows: tuple[int, ...]    # the row indices the header occupied
    first_col: int           # index of the first year column


def _clean(s: str) -> str:
    return " ".join(s.split())


def find_header(rows: Sequence[Sequence[str]], *, limit: int = 6) -> Header | None:
    """Spec §5 rule 1 / §3.1 step 4 on tab-split rows.

    The first row (among the first `limit`) with two or more cells holding
    a year token names the columns. Every non-empty cell from the first
    year cell rightwards is a label — so the FY2006 `Estimate` cell, which
    has no year, still labels its column. If the next row is nothing but
    kind tokens (`ACTUAL / ESTIMATE / APPROVED`) it is appended.
    """
    for i, row in enumerate(rows[:limit]):
        year_cols = [j for j, c in enumerate(row) if YEAR_RE.search(c)]
        if len(year_cols) < 2:
            continue
        first = year_cols[0]
        labels = {j: _clean(c) for j, c in enumerate(row) if j >= first and _clean(c)}
        consumed = [i]
        if i + 1 < len(rows):
            kinds = {j: _clean(c) for j, c in enumerate(rows[i + 1]) if _clean(c)}
            if kinds and all(KIND_RE.match(v) for v in kinds.values()) and all(j >= first for j in kinds):
                for j, v in kinds.items():
                    labels[j] = f"{labels[j]} {v.upper()}" if j in labels else v.upper()
                consumed.append(i + 1)
        return Header(labels=labels, rows=tuple(consumed), first_col=first)
    return None
