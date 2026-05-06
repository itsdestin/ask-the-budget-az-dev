"""s18-style cross-cut table parser.

Walks the tables in an `ExtractedDocument` and emits one `FundAgencyRow`
per (agency, fund) combination. Built for the FY27 baseline `s18.pdf`
shape per plan §4.1 step 2: agency name (full row span) → one row per
fund the agency uses → agency total. Same parser handles `bd2.pdf`
(approps cross-cut equivalent) and any future cross-cut with the same
shape.

Row classification:
  - Header row: first row of the table. Drives FY → column-index mapping.
  - Agency boundary: a row whose first cell carries `colspan > 1` (Mineru
    preserved the spanned name) OR whose first cell is non-empty while
    every following cell is empty/blank.
  - Total row: first cell matches /total$/i (case-insensitive). Skipped.
  - Otherwise: fund row → emit `FundAgencyRow`.

If no FY columns can be recognized in the header, the parser returns an
empty list rather than guessing — the catalog builder treats an empty
parse result as "this table isn't an s18 cross-cut" and moves on.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from chunking.readers.types import ExtractedDocument, Row, Table

# Match FY headers in any of: FY2026, FY 2026, FY26, FY 26, 2026, 2026 (4-digit only).
# Two captures: 4-digit year preferred, 2-digit year fallback.
_FY_RE = re.compile(r"FY\s*(\d{4}|\d{2})\b|^\s*(\d{4})\s*$", re.IGNORECASE)
_TOTAL_RE = re.compile(r"\b(total|subtotal)\b\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class FundAgencyRow:
    """One (agency, fund, amounts) tuple from a cross-cut table.

    `amounts` is a fiscal-year → string-amount map. Strings preserve the
    original `$N,NNN,NNN` formatting (or `($N,NNN)` for negatives) — the
    catalog layer is responsible for any numeric parsing it wants.
    """

    agency_name: str
    fund_name: str
    amounts: dict[int, str] = field(default_factory=dict)


def parse_s18_table(doc: ExtractedDocument) -> list[FundAgencyRow]:
    """Parse all s18-style tables in `doc` into FundAgencyRow tuples.

    Most cross-cut docs have a single table; we walk all of them and
    concatenate so a doc that splits its cross-cut across multiple Tables
    (e.g. multi-page reassembly didn't merge cleanly) still parses.
    """
    rows: list[FundAgencyRow] = []
    for table in doc.tables:
        rows.extend(_parse_one_table(table))
    return rows


def _parse_one_table(table: Table) -> list[FundAgencyRow]:
    if not table.rows:
        return []

    fy_col_index = _detect_fy_columns(table.rows[0])
    if not fy_col_index:
        return []

    out: list[FundAgencyRow] = []
    current_agency: str | None = None

    # Skip the header row — already consumed.
    for row in table.rows[1:]:
        cells = row.cells
        if not cells:
            continue
        first_text = _clean(cells[0].text)
        if not first_text:
            continue

        # Agency boundary: colspan > 1 OR remaining cells are all empty.
        if _is_agency_boundary(row):
            current_agency = first_text
            continue

        # Total row: skip whether or not we have a current agency.
        if _TOTAL_RE.search(first_text):
            continue

        # Fund row. Without a current agency, we have nothing to bind to —
        # silently drop rather than fabricate an "unknown" agency.
        if current_agency is None:
            continue

        amounts: dict[int, str] = {}
        for fy, idx in fy_col_index.items():
            if idx < len(cells):
                amount_text = _clean(cells[idx].text)
                if amount_text:
                    amounts[fy] = amount_text

        out.append(
            FundAgencyRow(
                agency_name=current_agency,
                fund_name=first_text,
                amounts=amounts,
            )
        )

    return out


def _is_agency_boundary(row: Row) -> bool:
    """True when the row holds a single agency-name spanned across columns,
    or non-empty first cell with all-empty following cells."""
    cells = row.cells
    if not cells:
        return False
    if cells[0].col_span and cells[0].col_span > 1:
        return True
    if len(cells) == 1:
        # Single-cell row — treat as agency boundary as long as it's not
        # obviously a total/header.
        return not _TOTAL_RE.search(_clean(cells[0].text))
    # Multi-cell row: agency boundary when first is non-empty AND all others empty.
    rest = [_clean(c.text) for c in cells[1:]]
    return bool(_clean(cells[0].text)) and all(not t for t in rest)


def _detect_fy_columns(header_row: Row) -> dict[int, int]:
    """Map fiscal year (int) → column index for the header row's amount columns.

    Returns an empty dict when no FY columns are recognizable — caller
    treats that as "not a cross-cut table" and skips.
    """
    out: dict[int, int] = {}
    for col_idx, cell in enumerate(header_row.cells):
        fy = _parse_fy(cell.text)
        if fy is not None:
            out[fy] = col_idx
    return out


def _parse_fy(text: str) -> int | None:
    """Extract a 4-digit fiscal year from a header cell. Accepts:
        FY2026 / FY 2026 / FY26 / FY 26 / 2026 / 2026 (with whitespace)
    Returns the 4-digit FY (e.g. 2026) or None if no match."""
    if not text:
        return None
    m = _FY_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(2)
    if not raw:
        return None
    if len(raw) == 2:
        # 2-digit FY (e.g. '26' → 2026). We're firmly in the 21st century;
        # the Phase 0 corpus spans FY15..FY27.
        return 2000 + int(raw)
    return int(raw)


def _clean(s: str) -> str:
    return " ".join(s.split())
