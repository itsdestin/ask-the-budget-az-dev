"""Rebuild a JLBC operating table from the PDF's text layer (spec §3.1).

MinerU's table is the ANCHOR — it says which printed lines are the table
and on which page it starts. Every figure comes from PyMuPDF words and
their positions; the vision model's digits are never trusted (spec D2).
A rebuild is returned only if it reconciles (spec D3, `table_gate`).

The vocabulary (what a year header, a figure and a footnote marker look
like) lives in `chunking/table_text.py` and is shared with phase A's
rendering, so the two halves of this work cannot drift apart.
"""
from __future__ import annotations

import html as _html
from dataclasses import dataclass, field
from typing import Sequence

from chunking.readers.types import Cell, Row, Table
from chunking.table_gate import is_check_label, reconcile
from chunking.table_text import (
    KIND_RE,
    MARKER_RE,
    figure_tokens,
    normalise_label,
    split_figure_marker,
)

# Spec §3.1 step 3: fewer matched anchor labels than this → None. A starting
# value; the dry run's match-rate distribution sets the real one.
ANCHOR_MIN_MATCH = 0.8
# Spec §3.1 step 3: how many pages past `table.page` to follow MinerU's own
# cross-page merge.
MAX_FORWARD_PAGES = 2
# A wrapped label sits at least this much further right than its row.
WRAP_INDENT = 3.0


@dataclass(frozen=True)
class RefineOutcome:
    table: Table | None
    reason: str
    anchor_match: float = 0.0


@dataclass
class _Word:
    x0: float
    y0: float
    x1: float
    y1: float
    text: str

    @property
    def centre(self) -> float:
        return (self.x0 + self.x1) / 2


@dataclass
class _Line:
    words: list[_Word]

    @property
    def x0(self) -> float:
        return self.words[0].x0


@dataclass
class _Columns:
    centres: list[float]
    labels: list[str]

    @property
    def spacing(self) -> float:
        gaps = [b - a for a, b in zip(self.centres, self.centres[1:])]
        return min(gaps) if gaps else 100.0

    @property
    def label_limit(self) -> float:
        """Spec §3.1 step 5: the label zone ends half a column spacing left
        of the first centre. Position, not content, decides what is a label
        — `Proposition 204 Protection` carries a word the figure regex
        matches, and only its x tells the two apart."""
        return self.centres[0] - self.spacing / 2

    def nearest(self, x: float) -> int:
        return min(range(len(self.centres)), key=lambda i: abs(self.centres[i] - x))


@dataclass
class _Draft:
    label: str
    x0: float
    figures: dict[int, str] = field(default_factory=dict)
    markers: dict[int, str] = field(default_factory=dict)


# --- words → lines -----------------------------------------------------------

def _lines(page) -> list[_Line]:
    """Spec §3.1 steps 1-2. Two words share a line when their `y0` differ
    by less than half the median word height.

    WHY half the median and not a fixed number: the 6-pt footnote markers
    are printed one point below their row's baseline, so their word box
    starts ~4.2 pt lower than the 9-pt words beside them (measured with
    PyMuPDF on a synthetic page at the real coordinates). Half the median
    height is ~6.2 pt there — wide enough to keep the marker on its row,
    narrow enough that the next row, 11.5 pt down, stays separate.

    Only the UPPER bound is load-bearing and mutation-checked (tripling the
    tolerance merges adjacent rows and fails 12 tests). Shrinking it cannot
    be caught, because a marker that falls onto a line of its own is picked
    up by `_rows`'s "a lone marker belongs to the row above" branch — two
    independent paths put it on the right row, which is deliberate.
    """
    raw = page.get_text("words")
    if not raw:
        return []
    words = sorted((_Word(w[0], w[1], w[2], w[3], w[4]) for w in raw), key=lambda w: (w.y0, w.x0))
    heights = sorted(w.y1 - w.y0 for w in words)
    tolerance = heights[len(heights) // 2] / 2
    lines: list[_Line] = []
    for w in words:
        if lines and abs(w.y0 - lines[-1].words[0].y0) < tolerance:
            lines[-1].words.append(w)
        else:
            lines.append(_Line([w]))
    for line in lines:
        line.words.sort(key=lambda w: w.x0)
    return lines


def _is_figure(text: str) -> bool:
    fig, _ = split_figure_marker(text)
    return bool(figure_tokens(fig))


def _is_marker(text: str) -> bool:
    return MARKER_RE.fullmatch(text) is not None


def _label_text(line: _Line) -> str:
    """The printed label: the line with its TRAILING figures, markers and
    dash-zeros removed. Only trailing ones — `Proposition 204 Services`
    and `Travel - In State` keep their number and their dash."""
    words = [w.text for w in line.words]
    while words and (_is_figure(words[-1]) or _is_marker(words[-1]) or words[-1] == "-"):
        words.pop()
    return normalise_label(" ".join(words))


# --- header ------------------------------------------------------------------

def _year_tokens(line: _Line) -> list[tuple[float, str]]:
    """(centre, 'FY 2024') for every year token on the line — `FY` + `2024`
    as two words, or `FY2024` as one. Both forms occur, sometimes in the
    same header row of a four-column edition, so both are normalised to
    `FY 2024` here and the caller never sees the difference.

    The CENTRE is what a column is keyed on, not the token's right edge:
    year headers are centred over their column while the figures beneath
    are right-aligned (spec §2, measured on the AHCCCS page — the year
    spans x 295-315 and its figures end at x 334).
    """
    out: list[tuple[float, str]] = []
    words = line.words
    i = 0
    while i < len(words):
        w = words[i]
        nxt = words[i + 1] if i + 1 < len(words) else None
        if w.text.upper() == "FY" and nxt is not None and nxt.text.isdigit() and len(nxt.text) == 4:
            out.append(((w.x0 + nxt.x1) / 2, f"FY {nxt.text}"))
            i += 2
            continue
        if w.text.upper().startswith("FY") and len(w.text) == 6 and w.text[2:].isdigit():
            out.append((w.centre, f"FY {w.text[2:]}"))
        i += 1
    return out


def _is_kind_line(line: _Line) -> bool:
    return bool(line.words) and all(KIND_RE.match(w.text) for w in line.words)


def _is_header_line(line: _Line) -> bool:
    return len(_year_tokens(line)) >= 2 or _is_kind_line(line)


def _find_columns(lines: Sequence[_Line], *, prefer: str = "last") -> _Columns | None:
    """Spec §3.1 step 4 over a run of lines in reading order: a line with
    two or more year tokens, plus the following line if it is all kind
    tokens.

    `prefer="last"` takes the header NEAREST the table when searching the
    lines above it — a page can print more than one `FY` header (two small
    boards share a page in some editions) and the one immediately above the
    table is the table's. `prefer="first"` is for searching inside the
    region, where the header is at the top.

    Mutation-checked and SURVIVING, deliberately: forcing both call sites to
    `indices[0]` changes no test. Measured 2026-09-01 on the live corpus —
    every in-scope agency page read (AHCCCS FY2026 pages 1-2, the FY2006
    four-column pages) carries exactly ONE line with two or more year
    tokens, and where two tables do share a page they are from the same
    edition and print the same years, so the choice is unobservable. It is
    kept because "the header nearest above these rows" is the rule that
    stays right if an edition ever prints two, and a test for it would have
    to invent a page this corpus does not contain.
    """
    indices = [i for i, line in enumerate(lines) if len(_year_tokens(line)) >= 2]
    if not indices:
        return None
    i = indices[-1] if prefer == "last" else indices[0]
    years = _year_tokens(lines[i])
    cols = _Columns([c for c, _ in years], [label for _, label in years])
    if i + 1 < len(lines) and _is_kind_line(lines[i + 1]):
        for w in lines[i + 1].words:
            j = cols.nearest(w.centre)
            cols.labels[j] = f"{cols.labels[j]} {w.text.upper()}"
    return cols


# --- anchoring ---------------------------------------------------------------

def _anchor_labels(table: Table) -> list[str]:
    """MinerU's non-empty cell-0 texts, normalised, in reading order."""
    out: list[str] = []
    for row in table.rows:
        if row.cells:
            label = normalise_label(row.cells[0].text)
            if label:
                out.append(label)
    return out


def _region(lines: Sequence[_Line], anchors: Sequence[str]) -> tuple[int, int, set[str]]:
    """Spec §3.1 step 3. Returns (start, end, matched anchors) as half-open
    line indices; (0, 0, set()) when nothing on the page matched.

    The containment runs page → MinerU because a merged MinerU label
    (`SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds`)
    contains both printed lines, and nothing can split it the other way.
    """
    matched_idx: list[int] = []
    matched: set[str] = set()
    last_anchor_idx: int | None = None
    for i, line in enumerate(lines):
        text = _label_text(line)
        if not text:
            continue
        # A line matches an anchor it equals, or one it is contained in when
        # it has at least two words — a lone `TOTAL` from a summary table
        # further down the page must not pass for `TOTAL - ALL SOURCES`.
        hits = [a for a in anchors if text == a or (text in a and len(text.split()) >= 2)]
        if hits:
            matched_idx.append(i)
            matched.update(hits)
            if anchors[-1] in hits:
                last_anchor_idx = i
    if not matched_idx:
        return 0, 0, set()
    # The region ends where MinerU's LAST row is printed, not at the last
    # line that happens to match any label — a prose heading `Operating
    # Budget` further down the page matches the anchor `OPERATING BUDGET`
    # and would otherwise drag the performance-measures block in.
    end = last_anchor_idx if last_anchor_idx is not None else matched_idx[-1]
    return matched_idx[0], end + 1, matched


# --- rows --------------------------------------------------------------------

def _rows(region: Sequence[_Line], cols: _Columns, anchors: Sequence[str]) -> list[_Draft] | None:
    """Spec §3.1 steps 5-7. One printed line is one row, except for the two
    label-wrap shapes. `None` means a column-assignment failure."""
    drafts: list[_Draft] = []
    for line in region:
        if _is_header_line(line):
            continue
        label_words: list[str] = []
        figures: dict[int, str] = {}
        markers: dict[int, str] = {}
        for w in line.words:
            if w.centre < cols.label_limit:
                # Includes a marker printed inside the label
                # (`Medicaid Services 5/6/7/`), which stays in the label.
                label_words.append(w.text)
            elif _is_marker(w.text):
                # Spec §3.1 step 6: a separate marker word right of the last
                # column belongs to the last column's cell. No special case is
                # needed for it -- the centres increase, so `nearest` already
                # answers "the last column" for any x beyond the last centre.
                # Mutation-checked: an explicit `x > centres[-1] -> last` branch
                # is dead code (it cannot change any answer), so it is not here
                # pretending to be a guard.
                markers[cols.nearest(w.centre)] = w.text
            elif _is_figure(w.text) or w.text == "-":
                j = cols.nearest(w.centre)
                if j in figures:
                    return None  # two figures in one column: the assignment is wrong
                fig, mk = split_figure_marker(w.text)
                figures[j] = fig
                if mk:
                    markers[j] = mk
            else:
                label_words.append(w.text)
        label = " ".join(label_words)
        if not figures:
            if not label:
                # A marker on a line of its own: it belongs to the row above.
                if markers and drafts:
                    drafts[-1].markers.update(markers)
                continue
            # Spec §3.1 step 5: indented under a row that has figures → the
            # label wrapped (`Account` under `Tobacco Products Tax Fund - …`).
            is_wrap = bool(drafts) and bool(drafts[-1].figures) and line.x0 > drafts[-1].x0 + WRAP_INDENT
            if is_wrap:
                drafts[-1].label = f"{drafts[-1].label} {label}"
                continue
            # No figures, no extra indent: a group heading, as today.
            drafts.append(_Draft(label, line.x0))
            continue
        # The other wrap shape: the label broke BEFORE the figures
        # (`SUBTOTAL - Appropriated/Expenditure` / `Authority Funds 25,348,200 …`).
        # Accepted only when MinerU read the two lines as one label, or the
        # first line names a subtotal — otherwise an ordinary indented body
        # row under a group heading would be swallowed by the heading.
        if (
            drafts and not drafts[-1].figures and line.x0 > drafts[-1].x0 + WRAP_INDENT
            and (
                any(normalise_label(f"{drafts[-1].label} {label}") in a for a in anchors)
                or is_check_label(normalise_label(drafts[-1].label))
            )
        ):
            drafts[-1].label = f"{drafts[-1].label} {label}"
            drafts[-1].figures, drafts[-1].markers = figures, markers
            continue
        drafts.append(_Draft(label, line.x0, figures, markers))
    return drafts


def _cells(drafts: Sequence[_Draft], cols: _Columns) -> list[list[str]]:
    """Spec §3.1 step 9: the header row first, then label + one cell per
    column. A column with no word on a line is EMPTY, never shifted."""
    rows = [[""] + list(cols.labels)]
    for d in drafts:
        cells = [d.label]
        for j in range(len(cols.centres)):
            fig = d.figures.get(j, "")
            mk = d.markers.get(j)
            # `99,294,500 [3/]` — the marker's digits never touch the figure's.
            cells.append(f"{fig} [{mk}]" if fig and mk else fig)
        rows.append(cells)
    return rows


def render_html(rows: Sequence[Sequence[str]]) -> str:
    """The `<table><tr><td>` shape `MinerUReader._parse_html_table` reads.

    Regenerated rather than patched because the repair's fallback path
    (spec §3.2) re-reads stored HTML, so it has to round-trip.
    """
    body = "".join("<tr>" + "".join(f"<td>{_html.escape(c)}</td>" for c in r) + "</tr>" for r in rows)
    return f"<table>{body}</table>"


# --- entry point -------------------------------------------------------------

def refine_operating_table(table: Table, pdf) -> RefineOutcome:
    """Rebuild `table` from the text layer of `pdf` (an open
    `fitz.Document`). Spec §3.1.

    Returns `RefineOutcome(table=None, reason=…)` whenever the rebuild
    cannot be VERIFIED — spec D3: the caller keeps MinerU's text rather
    than storing a half-checked table. There is no partial success.
    """
    start = table.page if table.page is not None else (table.pages[0] if table.pages else None)
    if start is None or start < 1 or start > len(pdf):
        return RefineOutcome(None, "no page")
    anchors = _anchor_labels(table)
    if not anchors:
        return RefineOutcome(None, "no anchor labels")

    first_lines = _lines(pdf[start - 1])
    if not first_lines:
        return RefineOutcome(None, "no text layer")

    # Step 3: anchor, walking forward while MinerU's labels keep matching.
    # MinerU merges a two-page table into its page-1 block (spec §1), so
    # `table.pages` cannot be trusted to say where the rows are.
    region_start, region_end, matched = _region(first_lines, anchors)
    regions = [first_lines[region_start:region_end]]
    page_no = start
    while anchors[-1] not in matched and page_no - start < MAX_FORWARD_PAGES and page_no < len(pdf):
        page_no += 1
        more = _lines(pdf[page_no - 1])
        m_start, m_end, more_matched = _region(more, anchors)
        if not (more_matched - matched):
            break
        regions.append(more[m_start:m_end])
        matched |= more_matched
    match_rate = len(matched) / len(anchors)
    if match_rate < ANCHOR_MIN_MATCH:
        return RefineOutcome(None, f"anchor match {match_rate:.0%}", match_rate)
    if anchors[-1] not in matched:
        # The region ends at MinerU's last row; if that row was never found
        # the end is a guess, and a guessed end can drop the fund ladder
        # while the arithmetic on the rows above it still passes.
        return RefineOutcome(None, "last row unmatched", match_rate)

    # Step 4: header — above the region, then inside it, then the previous
    # page (a continuation chunk whose own page prints no header).
    cols = _find_columns(first_lines[:region_start], prefer="last") or _find_columns(regions[0], prefer="first")
    if cols is None and start > 1:
        cols = _find_columns(_lines(pdf[start - 2]), prefer="last")
    if cols is None:
        return RefineOutcome(None, "no header", match_rate)

    # Steps 5-7.
    drafts = _rows([line for r in regions for line in r], cols, anchors)
    if drafts is None:
        return RefineOutcome(None, "two figures in one column", match_rate)
    rows = _cells(drafts, cols)

    # Step 8: the gate.
    verdict = reconcile(rows[1:])
    if not verdict.passed:
        return RefineOutcome(None, verdict.reason, match_rate)

    # Step 9: emit with MinerU's provenance untouched (spec D4).
    out_rows = [
        Row(cells=[Cell(text=c, row=i, col=j, page=table.page) for j, c in enumerate(r)])
        for i, r in enumerate(rows)
    ]
    return RefineOutcome(
        Table(rows=out_rows, caption=table.caption, bbox=table.bbox, page=table.page,
              pages=list(table.pages), html=render_html(rows)),
        "rebuilt",
        match_rate,
    )
