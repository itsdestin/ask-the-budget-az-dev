"""The reconciliation gate (spec §4): a rebuilt operating table is accepted
only when every published subtotal equals the sum of its rows, in every
year column, to the dollar. JLBC prints whole dollars in hundreds, so
there is no rounding to forgive.

The rule is one rule, not a list of labels: a check row equals the sum of
the ITEMS since some earlier boundary (the table start, a group heading,
or a previous check row), where an item is a body row not already covered
by an intermediate check row, or that intermediate check row itself. The
candidates are tried nearest-boundary first; the first one that equals
the printed figure wins and records which rows it covered. This is what
makes `SUBTOTAL - Appropriated Funds` = General Fund + `SUBTOTAL - Other
Appropriated Funds`, `AGENCY TOTAL` = `OPERATING SUBTOTAL` + the special
line items, and the ADC page's `Personal Services Subtotal` all reconcile
without a label table.

A wrong digit cannot pass: the candidates are a handful of specific sums,
and a check row that equals none of them fails with the nearest one named.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Sequence

from chunking.table_text import figure_tokens, normalise_label, split_figure_marker

_FTE_RE = re.compile(r"FULL TIME EQUIVALENT|\bFTE\b")
# Any label carrying the word TOTAL or SUBTOTAL: `OPERATING SUBTOTAL`,
# `AGENCY TOTAL`, `PROGRAM TOTAL`, `SUBTOTAL - …`, `TOTAL - ALL SOURCES`.
_CHECK_RE = re.compile(r"\b(?:SUB)?TOTAL\b")
_AGENCY_TOTALS = ("AGENCY TOTAL", "PROGRAM TOTAL")
_APPROP = "SUBTOTAL - APPROPRIATED FUNDS"
_APPROP_EA = "SUBTOTAL - APPROPRIATED/EXPENDITURE AUTHORITY FUNDS"


@dataclass(frozen=True)
class Check:
    label: str
    column: int
    expected: Decimal
    actual: Decimal
    rule: str

    @property
    def ok(self) -> bool:
        return self.expected == self.actual


@dataclass
class GateResult:
    passed: bool
    checks: list[Check] = field(default_factory=list)
    reason: str = ""


def is_check_label(label: str) -> bool:
    """A normalised label naming a subtotal or total row."""
    return _CHECK_RE.search(label) is not None


def parse_figure(cell: str) -> Decimal | None:
    """The first figure in a cell as a Decimal; `(1,234)` is negative;
    `-` is zero; no figure is None.

    WHY the `-` check is on the TOKEN, not `cell.strip()`: `_is_figure`
    (chunking/table_text.py) already accepts a lone `-` as a figure token
    -- JLBC's accounting dash for zero -- so `figure_tokens` can hand back
    `["-"]` even when the cell carries other text (a footnote marker split
    onto its own token, stray whitespace). The original rule only treated
    `-` as zero when the ENTIRE cell was `-`; on the live corpus a cell
    reading just `-` still crashed `Decimal("-")` with `ConversionSyntax`,
    because `tokens` was non-empty (`["-"]`) so the whole-cell branch was
    skipped and the general parse ran anyway. Found running G-OT0 calibration
    against the real corpus (chunking/repair_tables.py --calibrate) -- no
    fixture in tests/test_table_gate.py has a lone accounting-dash cell.
    """
    tokens = figure_tokens(cell)
    if not tokens:
        return Decimal(0) if cell.strip() == "-" else None
    tok = tokens[0]
    if tok == "-":
        return Decimal(0)
    neg = tok.startswith("(") and tok.endswith(")")
    value = Decimal(tok.strip("()$").replace(",", ""))
    return -value if neg else value


@dataclass
class _Line:
    label: str
    cls: str                      # "fte" | "check" | "heading" | "body"
    values: list[Decimal | None]


def _classify(rows: Sequence[Sequence[str]], first_col: int) -> list[_Line]:
    ncols = max((len(r) for r in rows), default=first_col) - first_col
    out: list[_Line] = []
    for cells in rows:
        label = normalise_label(" ".join(c for c in cells[:first_col]))
        values = [parse_figure(c) for c in cells[first_col:]]
        values += [None] * (ncols - len(values))
        if _FTE_RE.search(label):
            cls = "fte"
        elif _CHECK_RE.search(label):
            cls = "check"
        elif all(v is None for v in values):
            cls = "heading"
        else:
            cls = "body"
        out.append(_Line(label, cls, values))
    return out


def reconcile(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> GateResult:
    lines = _classify(rows, first_col)
    if not any(l.cls == "check" for l in lines):
        return GateResult(False, [], "no check row")
    ncols = len(lines[0].values) if lines else 0
    checks: list[Check] = []
    for c in range(ncols):
        if not any(l.values[c] is not None for l in lines):
            continue  # a column nobody printed in
        checks.extend(_reconcile_column(lines, c))
    passed = bool(checks) and all(ch.ok for ch in checks)
    return GateResult(passed, checks, "" if passed else "arithmetic")


@dataclass
class _Item:
    value: Decimal
    is_check: bool
    covered_from: int | None = None   # for a check item: index of the first item it covers


def _reconcile_column(lines: list[_Line], c: int) -> list[Check]:
    checks: list[Check] = []
    items: list[_Item] = []
    boundaries: list[int] = [0]           # candidate span starts, nearest last
    seen: dict[str, Decimal] = {}

    for line in lines:
        v = line.values[c]
        if line.cls == "fte":
            continue
        if line.cls == "heading":
            boundaries.append(len(items))
            continue
        if line.cls == "body":
            items.append(_Item(v if v is not None else Decimal(0), False))
            continue
        # A check row. A blank check cell in this column is skipped.
        if v is None:
            boundaries.append(len(items))
            continue
        candidates = [(b, _span_total(items, b)) for b in sorted(set(boundaries), reverse=True)]
        hit = next((b for b, total in candidates if total == v), None)
        nearest_expected = candidates[0][1] if candidates else Decimal(0)
        checks.append(Check(line.label, c, v if hit is not None else nearest_expected, v,
                            "span" if hit is not None else "nearest span"))
        items.append(_Item(v, True, covered_from=hit))
        boundaries.append(len(items))
        seen[line.label] = v

    # Cross-check (spec §4): the agency total equals the appropriated-level subtotal.
    approp_key = _APPROP_EA if _APPROP_EA in seen else _APPROP
    agency_key = next((k for k in _AGENCY_TOTALS if k in seen), None)
    if agency_key and approp_key in seen:
        checks.append(Check(f"{agency_key} = {approp_key}", c, seen[approp_key], seen[agency_key], "cross-check"))
    return checks


def _span_total(items: list[_Item], start: int) -> Decimal:
    """Sum of the items from `start`, where a check item replaces the items
    it covers (they are skipped, it is added)."""
    total = Decimal(0)
    i = start
    # Walk forward; when a later check covers from an index >= start, the
    # items it covers are skipped. Build the skip set first.
    skip: set[int] = set()
    for i, it in enumerate(items[start:], start=start):
        if it.is_check and it.covered_from is not None and it.covered_from >= start:
            skip.update(range(it.covered_from, i))
    for i, it in enumerate(items[start:], start=start):
        if i not in skip:
            total += it.value
    return total


def count_figure_rows(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> int:
    """Rows carrying at least one figure."""
    return sum(1 for cells in rows if any(figure_tokens(c) for c in cells[first_col:]))


def has_merged_cell(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> bool:
    return any(len(figure_tokens(c)) >= 2 for cells in rows for c in cells[first_col:])


def has_fused_marker(rows: Sequence[Sequence[str]], *, first_col: int = 1) -> bool:
    return any(
        split_figure_marker(tok)[1] is not None
        for cells in rows for c in cells[first_col:] for tok in c.split()
    )
