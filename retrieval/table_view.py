"""Phase A of the operating-table work (spec §5): render a table chunk's
tab-joined text as `column-header: value` cells so the model reads a
label, not a position.

Pure function over `text`. No store access and no HTML: `table_html`
carries the same merged cells as the text, and nothing else in the app
renders it (verified 2026-09-01).
"""
from __future__ import annotations

from chunking.table_text import figure_tokens, find_header, peel_markers

# Spec §5 rule 7: the four 1.8 MB tab-padded AFR chunks would grow ~1.6x
# inside a payload that is already the problem.
LABELLED_MAX_CHARS = 20_000
MERGED_NOTE = "(two values in one cell — read with care)"


def render_labelled(text: str) -> str | None:
    """`None` means "send the text as today": no tab-joined rows, no
    detectable header, or too big."""
    if not text or len(text) > LABELLED_MAX_CHARS:
        return None
    lines = text.split("\n")
    first = next((i for i, line in enumerate(lines) if "\t" in line), None)
    if first is None:
        return None
    preamble, body = lines[:first], lines[first:]
    rows = [line.split("\t") for line in body]
    header = find_header(rows)
    if header is None:
        return None

    out = list(preamble)
    for i, cells in enumerate(rows):
        if i in header.rows:
            continue
        label = " ".join(c.strip() for c in cells[: header.first_col] if c.strip())
        parts: list[str] = []
        for j in range(header.first_col, len(cells)):
            cell = cells[j].strip()
            if not cell:
                continue  # rule 2: an empty cell is omitted, never a blank
            column = header.labels.get(j) or f"column {j + 1}"
            figures = figure_tokens(cell)
            if len(figures) >= 2:
                # Rule 4: honest, not hidden. Phase B removes the case.
                parts.append(f"{column}: {' and '.join(figures)} {MERGED_NOTE}")
            else:
                parts.append(f"{column}: {peel_markers(cell)}")
        if not label and not parts:
            continue
        out.append(" | ".join(([label] if label else []) + parts))
    return "\n".join(out)
