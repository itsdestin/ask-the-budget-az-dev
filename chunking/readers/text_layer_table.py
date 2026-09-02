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
from collections import Counter
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
# Refuse a rebuild that keeps less than this share of MinerU's own figures
# (see `_figure_retention` for the measurement behind the number).
MIN_FIGURE_RETENTION = 0.5


@dataclass(frozen=True)
class RefineOutcome:
    table: Table | None
    reason: str
    anchor_match: float = 0.0
    figure_retention: float = 1.0


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

    WHY half the median and not a fixed number: JLBC prints the footnote
    markers as 6-pt SUPERSCRIPTS, so a marker's word box sits slightly
    ABOVE its own row. Measured on `jlbc-approps-fy2010-rad` page 1: the
    marker `1/` is at y0=154.31 while its row (`Full Time Equivalent
    Positions`) is at y0=155.66, and the same page has `2/3/` at 278.63 and
    `4/` at 300.29 against rows at 280.0 and 301.6. Half the median word
    height is ~5 pt there — wide enough to keep every marker on its row,
    narrow enough that the next row, ~11.5 pt down, stays separate.

    BOTH bounds are load-bearing, and an earlier version of this comment
    claimed otherwise. Tripling the tolerance merges adjacent rows.
    SHRINKING it drops `1/` and `2/3/` on that page and moves `4/` onto the
    wrong row; the `_rows` fallback for a marker left on a line of its own
    is a safety net that fired 0 times across 400 real tables, not a second
    path that makes this value free to change.
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


def _has_figures(line: _Line) -> bool:
    """Does this printed line carry any figure? A subtotal or total row
    always does; a group heading never does."""
    return any(_is_figure(w.text) for w in line.words)


# Every spelling of the "no value" placeholder JLBC prints in a figure
# column. `_is_figure` already accepts the ASCII hyphen, so this exists for
# the ones it does not -- and the em dash is not an edge case: measured over
# 250 sampled in-scope pages of the live corpus, 2026-09-02, the standalone
# dash-only tokens are `-` x1,123, **`—` (U+2014) x243**, `–` (U+2013) x7 and
# `--` x5. Before this, a page whose whole column read `--`/`—` kept its
# figures inside `_label_text`, so no anchor could match it and the table was
# refused for a low anchor rate with every one of its labels printed plainly
# on the page (`jlbc-baseline-fy2013-irc-0000`, 29%).
_DASH_ZEROS = frozenset("-‐‑‒–—―−")


def _is_dash_zero(token: str) -> bool:
    """A token that is nothing but dashes — JLBC's printed zero."""
    return bool(token) and all(ch in _DASH_ZEROS for ch in token)


def _label_text(line: _Line) -> str:
    """The printed label: the line with its TRAILING figures, markers and
    dash-zeros removed. Only trailing ones — `Proposition 204 Services`
    and `Travel - In State` keep their number and their dash."""
    words = [w.text for w in line.words]
    while words and (_is_figure(words[-1]) or _is_marker(words[-1])
                     or _is_dash_zero(words[-1])):
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


def _line_hits(lines: Sequence[_Line], anchors: Sequence[str]) -> list[list[str]]:
    """For each line, the anchor labels it matches.

    The containment runs page → MinerU because a merged MinerU label
    (`SUBTOTAL - Other Appropriated Funds SUBTOTAL - Appropriated Funds`)
    contains both printed lines, and nothing can split it the other way.
    A one-word line matches only an anchor it equals — a lone `TOTAL` from
    a summary table further down the page must not pass for
    `TOTAL - ALL SOURCES`.
    """
    out: list[list[str]] = []
    for line in lines:
        text = _label_text(line)
        if not text:
            out.append([])
            continue
        out.append([a for a in anchors
                    if text == a or (text in a and len(text.split()) >= 2)])
    return out


def _region(
    lines: Sequence[_Line], anchors: Sequence[str], *, own_page: bool
) -> tuple[int, int, set[str]]:
    """Spec §3.1 step 3, amended by measurement. Returns (start, end, matched
    anchors) as half-open line indices; (0, 0, set()) when nothing matched.

    WHY the start and end are pinned to MinerU's OWN first and last rows,
    rather than to "the first and last line matching any label" (which is
    what step 3 says, and what this did until it was measured against the
    whole corpus): anchor labels are generic — `AFIS Replacement`,
    `General Fund`, `TOTAL - ALL SOURCES` — so on a page carrying TWO tables
    the loose rule silently reads the wrong one, and the arithmetic gate
    cannot see it, because the wrong table reconciles perfectly well with
    itself. Measured over all 4,875 in-scope chunks, 2026-09-01:

      * `jlbc-approps-fy2017-doa-apf-0001` (and its FY2016 baseline twin)
        rebuilt the NEIGHBOURING chunk's 11-row table instead of its own
        39-row one: the first line matching any of its anchors was the other
        table's `AFIS Replacement` at y=131, and the only
        `TOTAL - ALL SOURCES` printed below that belonged to the other table
        too, at y=257. Its own table starts at y=291. ~28 rows of
        per-project dollars were lost under the verdict `rebuilt`.
      * 31 more chunks swallowed a sibling table because the END was the
        LAST line matching the last anchor rather than its FIRST occurrence
        at or after the start (`…-ata-0002` 5 MinerU rows → 22 rebuilt,
        `…-judspa-0001` 16 → 26, `…-ema-0000` 10 → 28, `…-sdb-0000` 8 → 23
        in seven editions). Concatenated ladders each reconcile from their
        own boundary, so the gate passed every one of them.

    WHY an unmatched first anchor FALLS BACK instead of refusing — a
    deliberate deviation from the review's instruction, taken on
    measurement: MinerU routinely fuses the page masthead into its first
    cell, so that anchor is LONGER than anything printed and can never be
    matched by a containment that runs page → MinerU. On the FY2006
    four-column pages the first anchor is `DIRECTOR: DONALD BUTLER` while
    the page prints `Director: Donald Butler JLBC Analyst: Eric Jorgensen`
    as ONE line; `…-ema-0000` has the same shape with
    `ADJUTANT GENERAL: HUGO SALAZAR`. Refusing those would throw away
    hundreds of rebuilds that are correct today — including all 156
    four-column pages, which are the ones MinerU reads worst and so the
    ones this work exists for. The first anchor therefore pins the start
    when it is found, and the old first-matched-line rule stands in when it
    is not. `_figure_retention` is the backstop for what that lets through.

    `own_page` is False for a page reached by the forward walk, where
    MinerU's first row is on an earlier page by construction and the region
    correctly begins at the first line matching anything.
    """
    hits = _line_hits(lines, anchors)
    matched_lines = [i for i, h in enumerate(hits) if h]
    if not matched_lines:
        return 0, 0, set()

    start = None
    if own_page:
        start = next((i for i in matched_lines if anchors[0] in hits[i]), None)
    if start is None:
        start = matched_lines[0]

    # The first occurrence of MinerU's last row at or after the start THAT
    # CARRIES FIGURES, then extended over any CONTIGUOUS lines matching it.
    #
    # The extension is what the whole project is about: MinerU's last cell is
    # often several printed rows fused into one, and every one of them is
    # contained in it. `jlbc-approps-fy2009-hla-0000`'s last anchor is
    # `FEDERAL FUNDS TOTAL - ALL SOURCES`, printed as two adjacent lines;
    # stopping at the first left the table with no check row at all.
    # Contiguity is what stops that reopening the sibling hole above -- a
    # second table's `TOTAL - ALL SOURCES` is many non-matching lines
    # further down, never the very next one.
    #
    # The figure test is why a GROUP HEADING cannot end the region.
    # `jlbc-baseline-fy2013-axs-0000`'s last anchor is
    # `SUBTOTAL - APPROPRIATED/EXPENDITURE AUTHORITY FUNDS`, and the bare
    # heading `Expenditure Authority Funds` printed ten lines above the real
    # subtotal is CONTAINED in it, so the region ended at line 43 instead of
    # 52 and the whole expenditure-authority block was dropped. That one was
    # caught by the cross-check (7,024,518,200 against 1,417,666,800), but a
    # truncation that removed the cross-check's own rows would pass in
    # silence. A real last row is a subtotal or a total and always prints
    # figures; a heading never does. Measured over all 4,875 in-scope chunks:
    # requiring figures loses no rebuild and recovers this one.
    #
    # The EXTENSION deliberately does not require figures -- the very next
    # line is often the label's own wrap (`SUBTOTAL - Appropriated/Expenditure`
    # / `Authority Funds`, axs line 53), which `_rows` joins back on.
    end = next(
        (i for i in matched_lines
         if i >= start and anchors[-1] in hits[i] and _has_figures(lines[i])),
        None,
    )
    if end is None:
        end = max(i for i in matched_lines if i >= start)
    else:
        while end + 1 < len(lines) and anchors[-1] in hits[end + 1]:
            end += 1

    # The region's LAST row may itself be a label that wrapped onto the next
    # printed line, and the two rules above can only see a line that matches
    # an anchor -- so the continuation is cut off and `_rows` never gets the
    # chance to join it back on.
    #
    # WHY this is a reader defect and not only a re-run artefact: whether the
    # continuation line matches an anchor depends on how MinerU happened to
    # split that cell, which is not a property of the page. Measured on the
    # live corpus 2026-09-02:
    #   * `jlbc-approps-fy2018-dcs-0002` -- MinerU splits the fund into
    #     `...NEEDY FAMILIES BLOCK` + `GRANT`, so the printed `Grant` line
    #     matches the `GRANT` anchor and is kept. Feed the SAME page a
    #     complete `...BLOCK GRANT` label and the region ends one line early
    #     (`GRANT` is one word, and `_line_hits` requires two for a
    #     containment match -- deliberately, so a lone `TOTAL` cannot pass
    #     for `TOTAL - ALL SOURCES`).
    #   * `jlbc-approps-fy2024-axs-0000` -- MinerU ALREADY emits the complete
    #     `TOBACCO TAX AND HEALTH CARE FUND - MEDICALLY NEEDY ACCOUNT`, and
    #     today's rebuild keeps its printed `Account` line only because the
    #     NEIGHBOURING fund's cell happens to be a bare `ACCOUNT` anchor.
    #     Remove that coincidence and the fund silently loses its last word.
    #     `jlbc-approps-fy2026-axs-0000` and `jlbc-approps-fy2027-axs-0000`
    #     are the same shape.
    # On the UNREPAIRED corpus this changes nothing, and that is measured, not
    # assumed: a full dry run of 2026-09-02 with this rule in place is
    # identical to the run without it on all 4,875 in-scope rows. Every such
    # continuation happens to match some anchor today. What the rule buys is
    # that the rebuild stops depending on that coincidence -- which is what
    # makes the repair idempotent, and what protects the four chunks above
    # from a future MinerU reading that merges the two cells.
    #
    # The join must be CONTAINED in one of MinerU's own labels -- the same
    # evidence `_rows`'s second wrap shape demands -- so an indented heading
    # belonging to a following table can never be swallowed.
    while end + 1 < len(lines):
        tail = _label_text(lines[end + 1])
        if not tail or _has_figures(lines[end + 1]):
            break
        if lines[end + 1].x0 <= lines[end].x0 + WRAP_INDENT:
            break
        joined = normalise_label(f"{_label_text(lines[end])} {tail}")
        if not any(joined in a for a in anchors):
            break
        end += 1

    matched: set[str] = set()
    for i in range(start, end + 1):
        matched.update(hits[i])
    return start, end + 1, matched


def _figure_retention(before: Sequence[Sequence[str]], after: Sequence[Sequence[str]]) -> float:
    """How much of MinerU's own figure evidence survived into the rebuild.

    Belt-and-braces behind the region rule above — spec D3 says refuse
    rather than store a table nobody checked, and the failure it guards
    against is one the arithmetic gate structurally cannot see. Measured
    over all 4,607 rebuilds on 2026-09-01: 4,017 keep 100% of MinerU's
    figure tokens, and every other honest rebuild keeps at least 83% (the
    shortfall is recovery work — MinerU's fused `99,294,5003/` becoming
    `99,294,500` + `[3/]`). The only two below that were the substituted
    tables named above, at 0.097 and 0.114. So the distribution has an EMPTY
    BAND whose edges are 0.114 and 0.833, and every threshold placed
    anywhere inside it returns an identical verdict on every one of those
    4,607 rebuilds. 0.5 is a value in that band, not a centre or an optimum
    -- there is nothing in the data to optimise against. Both edges of the
    band are bad in different ways: below it a substitution is missed, above
    it a real recovery is refused.

    With the region rule above in place it now fires ZERO times on the whole
    corpus — the two tables it was calibrated on are caught earlier and
    refused by the arithmetic gate instead, and no rebuild keeps under 83%.
    That is the intended state: it is here for the 705 chunks whose first
    anchor cannot be matched, where the region start is a fallback rather
    than a fact. Refusing costs a repair, never correctness — the caller
    keeps MinerU's own text (spec D3).
    """
    b = Counter(tok for row in before for cell in row[1:] for tok in figure_tokens(cell))
    if not b:
        return 1.0
    a = Counter(tok for row in after for cell in row[1:] for tok in figure_tokens(cell))
    return sum((b & a).values()) / sum(b.values())


# --- rows --------------------------------------------------------------------

def _rows(region: Sequence[_Line], cols: _Columns, anchors: Sequence[str]) -> list[_Draft] | None:
    """Spec §3.1 steps 5-7. One printed line is one row, except for the two
    label-wrap shapes. `None` means a column-assignment failure."""
    drafts: list[_Draft] = []
    # Markers found on a line of their own, waiting for the row they belong
    # to. They wait for the row BELOW: JLBC prints markers as superscripts,
    # so a marker's word box sits ABOVE its own row's (measured — see
    # `_lines`), and lines are ordered by `y0`, so a marker that failed to
    # group arrives BEFORE its row, never after it.
    #
    # This is LOAD-BEARING on real pages, not a theoretical safety net: it
    # fires on 10 chunks corpus-wide, 8 of which rebuild. On
    # `jlbc-approps-fy2021-sos-0000` the marker `10/11/` is alone at
    # y=331.4 and belongs to `Special Election` below it. The earlier
    # version attached upwards, which put the footnote on the wrong row.
    pending: dict[int, str] = {}
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
            elif _is_figure(w.text) or _is_dash_zero(w.text):
                # `_is_dash_zero`, not `w.text == "-"`: the second call site of
                # the same rule, and it has to move with the first. Stripping
                # a trailing `--` in `_label_text` WITHOUT this makes the
                # anchor match and then files the dash as part of the LABEL --
                # verified on `jlbc-baseline-fy2013-irc-0000`, which rebuilt as
                # `Lump Sum Appropriation -- | 106,100 | 3,000,000 | ` with its
                # FY 2013 column empty. That is worse than MinerU's own
                # reading, which has the `--` in the right column.
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
        if figures and pending:
            # The line's own markers win over anything left waiting.
            markers = {**pending, **markers}
            pending.clear()
        if not figures:
            if not label:
                # A marker on a line of its own: it belongs to the row below.
                pending.update(markers)
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
    region_start, region_end, matched = _region(first_lines, anchors, own_page=True)
    regions = [first_lines[region_start:region_end]]
    page_no = start
    while anchors[-1] not in matched and page_no - start < MAX_FORWARD_PAGES and page_no < len(pdf):
        page_no += 1
        more = _lines(pdf[page_no - 1])
        m_start, m_end, more_matched = _region(more, anchors, own_page=False)
        if not (more_matched - matched):
            break
        regions.append(more[m_start:m_end])
        matched |= more_matched
    # The denominator counts each DISTINCT label once. 17 of 400 sampled
    # tables repeat a cell-0 label (`Department of Administration Subtotal`
    # under two headings, say), and `matched` is a set of labels, so counting
    # the repeat twice below the line and once above it understates the rate
    # and would skew the distribution the dry run uses to set the threshold.
    match_rate = len(matched) / len(dict.fromkeys(anchors))
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

    # Step 8a: did the rebuild keep MinerU's own figures? A region that landed
    # on the wrong table reconciles with itself, so the arithmetic gate cannot
    # see it; this can.
    mineru_rows = [[c.text for c in row.cells] for row in table.rows]
    retention = _figure_retention(mineru_rows, rows)
    if retention < MIN_FIGURE_RETENTION:
        return RefineOutcome(None, f"figure retention {retention:.0%}", match_rate, retention)

    # Step 8b: the gate.
    verdict = reconcile(rows[1:])
    if not verdict.passed:
        return RefineOutcome(None, verdict.reason, match_rate, retention)

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
        retention,
    )
