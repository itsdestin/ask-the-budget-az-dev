"""DOCX `run_docx_ingest` output → Markdown rendering.

Operates on the flat block list (see scripts/run_docx_ingest.py). The
DocxReader's Section model is bill-specific — for non-bill DOCX (writing
draft, glossary fallbacks, etc.) we walk blocks directly and let Word
heading styles + tab-cell signals + table_cell sequences drive structure.

Public API:
    render_docx_to_markdown(blocks: list[dict]) -> str

Returns a Markdown string. No leading/trailing newlines beyond what the
content contains. Caller is responsible for writing to disk and handling
any section-divider concatenation (e.g. T5.2 appending the Gov glossary).
"""
from __future__ import annotations

import re
from typing import Iterable

# Word's Heading 1..Heading 9 styles. We map them to Markdown # depths,
# clamped to ###### (Markdown's max).
_HEADING_RE = re.compile(r"^Heading\s+(\d+)$", re.IGNORECASE)


def render_docx_to_markdown(blocks: Iterable[dict]) -> str:
    """Render a flat block list (run_docx_ingest output) to Markdown."""
    blocks = list(blocks)
    out_pieces: list[str] = []

    # State for "tab-cell line-item" tables: a contiguous run of paragraph
    # blocks that all carry a `cells:` field forms one Markdown table.
    tab_buffer: list[list[str]] = []
    # State for table_cell-block tables: cells share a `tN-*` prefix.
    cell_buffer_table_id: str | None = None
    cell_rows: dict[int, list[tuple[int, str]]] = {}  # row → [(col, text)]

    def _flush_tab_buffer() -> None:
        nonlocal tab_buffer
        if tab_buffer:
            out_pieces.append(_render_md_table(tab_buffer))
            tab_buffer = []

    def _flush_cell_buffer() -> None:
        nonlocal cell_buffer_table_id, cell_rows
        if cell_rows:
            rows_sorted = [
                [text for _, text in sorted(cell_rows[r], key=lambda p: p[0])]
                for r in sorted(cell_rows.keys())
            ]
            out_pieces.append(_render_md_table(rows_sorted))
        cell_buffer_table_id = None
        cell_rows = {}

    for block in blocks:
        kind = block.get("kind")

        if kind == "paragraph":
            cells = block.get("cells")
            if cells is not None:
                # Any active table_cell run ends here.
                _flush_cell_buffer()
                tab_buffer.append([_clean_cell(c) for c in cells])
                continue

            # Plain paragraph — flush any in-flight tables first.
            _flush_tab_buffer()
            _flush_cell_buffer()

            text = (block.get("text") or "").strip()
            if not text:
                continue

            style = str(block.get("style") or "Normal")
            heading_level = _heading_level_for_style(style)
            if heading_level is not None:
                # Strip any leading '# ' the user already typed so we don't
                # double-prefix.
                stripped = re.sub(r"^#+\s*", "", text)
                hashes = "#" * min(heading_level, 6)
                out_pieces.append(f"{hashes} {stripped}")
            else:
                out_pieces.append(text)

        elif kind == "table_cell":
            # Tab-cell tables don't continue across a table_cell block.
            _flush_tab_buffer()

            tcid = str(block.get("table_cell_id") or "")
            table_id = tcid.split("-", 1)[0] if "-" in tcid else tcid

            if cell_buffer_table_id is not None and cell_buffer_table_id != table_id:
                _flush_cell_buffer()

            cell_buffer_table_id = table_id
            row = int(block.get("row") or 0)
            col = int(block.get("col") or 0)
            text = _clean_cell(block.get("text") or "")
            cell_rows.setdefault(row, []).append((col, text))

    # Flush trailing tables.
    _flush_tab_buffer()
    _flush_cell_buffer()

    return "\n\n".join(out_pieces)


# --- helpers ----------------------------------------------------------------


def _heading_level_for_style(style: str) -> int | None:
    m = _HEADING_RE.match(style.strip())
    if not m:
        return None
    return int(m.group(1))


def _clean_cell(text: str) -> str:
    """Sanitize a cell value for Markdown table syntax — escape pipes and
    collapse whitespace."""
    s = " ".join((text or "").split())
    return s.replace("|", r"\|")


def _render_md_table(rows: list[list[str]]) -> str:
    """Render a list of rows as a Markdown table. First row is the header.

    Pads short rows with empty cells so all rows match the header's length.
    """
    if not rows:
        return ""
    max_cols = max(len(r) for r in rows)
    padded = [r + [""] * (max_cols - len(r)) for r in rows]
    header = "| " + " | ".join(padded[0]) + " |"
    sep = "| " + " | ".join(["---"] * max_cols) + " |"
    body_rows = [
        "| " + " | ".join(r) + " |"
        for r in padded[1:]
    ]
    if not body_rows:
        # Header-only table; still need separator so consumers see it as a table.
        return f"{header}\n{sep}"
    return "\n".join([header, sep, *body_rows])
