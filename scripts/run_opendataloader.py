"""Run OpenDataLoader-PDF on one PDF, optionally restricted to a page range.

Implementation note: opendataloader-pdf v2.4.1 ships a Python wrapper
around a Java CLI (Apache-2.0, JDK 11+ required). One `convert()` call
handles all requested pages — the Java side accepts a comma+range page
spec ('1', '1-3', '1,3,5-7'), so unlike the MinerU wrapper there is no
need to invoke the CLI per contiguous range.

We chose OpenDataLoader as MinerU's bake-off opponent after Docling
proved unworkable on Windows (docling-parse v5.3.x std::bad_alloc; OS-
level hang from Defender x ProcessPoolExecutor). See
samples/extractor-output/opendataloader/README.md for findings.

Outputs (per-page contract, identical shape to run_mineru.py):
  <out>/page-<N>.json   — structured extraction. Carries:
                           {extractor, source_pdf, page,
                            blocks: [<elements from OpenDataLoader's `kids`
                                     whose 'page number' == N>]}
  <out>/page-<N>.md     — Markdown text concatenated from this page's blocks
                          (synthesized from each element's `content` field).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def parse_pages(arg: str) -> list[int]:
    """Parse '1', '1-3', '1,3,5', '1-3,7' into a sorted list of 1-indexed pages."""
    pages: set[int] = set()
    for piece in arg.split(","):
        piece = piece.strip()
        if "-" in piece:
            lo, hi = piece.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(piece))
    return sorted(pages)


def _format_pages_for_cli(pages: list[int]) -> str:
    """Collapse a sorted page list into OpenDataLoader's '1,3,5-7' spec.

    Reduces command-line length and lets the Java side optimize contiguous
    ranges as a single internal sweep.
    """
    if not pages:
        return ""
    pages = sorted(set(pages))
    ranges: list[tuple[int, int]] = [(pages[0], pages[0])]
    for p in pages[1:]:
        last_start, last_end = ranges[-1]
        if p == last_end + 1:
            ranges[-1] = (last_start, p)
        else:
            ranges.append((p, p))
    return ",".join(
        str(s) if s == e else f"{s}-{e}" for s, e in ranges
    )


def write_dry_run(pdf: Path, out: Path, pages: list[int]) -> None:
    """Stub for testing — writes a minimal valid output without invoking Java."""
    out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "opendataloader-dry-run",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": [],
                },
                indent=2,
            )
        )
        (out / f"page-{page}.md").write_text(f"# Dry-run page {page}\n")


def _block_page(block: dict) -> int | None:
    """Return the 1-indexed page for an OpenDataLoader element, or None."""
    # OpenDataLoader uses the literal key 'page number' (with a space) in its JSON.
    val = block.get("page number")
    if val is None:
        return None
    try:
        return int(val)
    except (TypeError, ValueError):
        return None


def _subset_table_to_page(table: dict, page: int) -> dict | None:
    """Return a copy of `table` containing only cells on the given page.

    OpenDataLoader sometimes emits a single table that spans many PDF
    pages — its outer `page number` field then names the FIRST page of
    the span, but each cell inside carries its own correct per-page
    `page number`. We walk rows -> cells, keep cells whose page matches,
    and drop rows that end up empty.

    Returns None if the table has no cells on `page`.
    """
    out_rows: list[dict] = []
    for row in table.get("rows", []) or []:
        kept_cells: list[dict] = []
        for cell in row.get("cells", []) or []:
            if _cell_on_page(cell, page):
                kept_cells.append(cell)
        if kept_cells:
            out_rows.append({**row, "cells": kept_cells})
    if not out_rows:
        return None
    return {**table, "rows": out_rows, "page number": page}


def _cell_on_page(cell: dict, page: int) -> bool:
    """True if a table cell (or any of its content descendants) is on `page`.

    A cell's own `page number` is the primary signal. Some cells without
    a top-level page_number still have descendants tagged with a page;
    we accept either.
    """
    pn = cell.get("page number")
    if pn is not None:
        try:
            if int(pn) == page:
                return True
        except (TypeError, ValueError):
            pass
    for kid in cell.get("kids", []) or []:
        kpn = kid.get("page number")
        if kpn is not None:
            try:
                if int(kpn) == page:
                    return True
            except (TypeError, ValueError):
                continue
    return False


def run_opendataloader(pdf: Path, out: Path, pages: list[int]) -> None:
    """Real path. Calls opendataloader_pdf.convert() once for all requested pages.

    OpenDataLoader writes <output_dir>/<pdf_stem>.json (and an optional
    <pdf_stem>_images/ directory). The JSON's top-level `kids` array holds
    every element across all requested pages, each tagged with its
    1-indexed `page number`. We bucket by page and write our standard
    per-page files.

    Images: any extracted image files are copied alongside the per-page
    output as <out>/<pdf_stem>_images/ so downstream scoring can see them.
    """
    # Lazy import — avoids loading the Java bridge until we actually need it,
    # keeping the dry-run path lightweight for tests.
    import opendataloader_pdf

    out.mkdir(parents=True, exist_ok=True)
    pdf_stem = pdf.stem

    with TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # use_struct_tree=True is load-bearing for AZ budget docs.
        # Without it, the AZ Legislature's appropriations tables come back
        # as concatenated paragraphs (e.g. row "AHCCCS Fund 14,554,163,500
        # (2,258,900) 4,451,100 ..." in a single block) — column structure
        # lost, cell-level citations impossible. Empirically tested on
        # jlbc-approps-fy26 p.520: default mode produced 24 paragraph
        # blocks with column-merged rows; struct_tree mode produced 159
        # nested table blocks with proper {row, col, span, bbox} per cell.
        # Non-table pages (prose, footnote-heavy) still return paragraph
        # blocks under struct_tree, so this is a safe default.
        opendataloader_pdf.convert(
            input_path=str(pdf),
            output_dir=str(tmp_path),
            format="json",
            pages=_format_pages_for_cli(pages),
            quiet=True,
            use_struct_tree=True,
        )

        json_path = tmp_path / f"{pdf_stem}.json"
        if not json_path.exists():
            raise RuntimeError(
                f"opendataloader produced no JSON at {json_path}"
            )
        doc = json.loads(json_path.read_text(encoding="utf-8"))

        # Copy any extracted images alongside the per-page JSON so the
        # `source` paths in element records still resolve.
        images_src = tmp_path / f"{pdf_stem}_images"
        if images_src.exists():
            images_dst = out / f"{pdf_stem}_images"
            if images_dst.exists():
                shutil.rmtree(images_dst)
            shutil.copytree(images_src, images_dst)

    # Bucket all elements by 1-indexed page.
    #
    # use_struct_tree=True can produce a single table block that spans
    # MANY PDF pages (e.g. AFR fund-balance schedule comes back as one
    # 4,110-row table with `page number` set to the first page of the
    # span; cells inside carry correct per-page page numbers). If we
    # bucketed only on each top-level block's outer `page number`,
    # subsequent pages of a multi-page table would be empty in our
    # per-page output. So for tables, we descend into rows/cells and
    # construct a per-page subset that retains only cells matching the
    # target page.
    blocks_by_page: dict[int, list[dict]] = {p: [] for p in pages}
    for el in doc.get("kids", []):
        if el.get("type") == "table":
            for page in pages:
                subset = _subset_table_to_page(el, page)
                if subset is not None:
                    blocks_by_page[page].append(subset)
        else:
            p = _block_page(el)
            if p is not None and p in blocks_by_page:
                blocks_by_page[p].append(el)

    for page in pages:
        blocks = blocks_by_page.get(page, [])
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "opendataloader-2.4.1",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": blocks,
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        # Synthesized Markdown — preserve element order. Table blocks
        # carry their content nested under rows/cells/kids; we recurse to
        # render them as a Markdown grid so analysts can see the
        # extractor's column structure side-by-side with the PDF.
        md_lines: list[str] = []
        for b in blocks:
            md_lines.extend(_render_block_md(b))
        (out / f"page-{page}.md").write_text(
            "\n\n".join(md_lines) + "\n",
            encoding="utf-8",
        )


def _cell_text(cell: dict) -> str:
    """Concatenate every text-bearing descendant of a table cell.

    Cells carry a `kids` array of paragraph/heading/etc. records. Each
    descendant has a `content` field; we join them with spaces so the
    cell renders as a single Markdown table cell. Newlines and pipes
    inside cell content are escaped — pipes break Markdown table rows.
    """
    parts: list[str] = []

    def walk(node: dict) -> None:
        c = node.get("content")
        if c:
            parts.append(c)
        for child in node.get("kids", []) or []:
            walk(child)

    walk(cell)
    text = " ".join(p.strip() for p in parts if p.strip())
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _render_block_md(b: dict) -> list[str]:
    """Render a single top-level block as Markdown.

    Tables become standard Markdown grids; headings get `#` prefix;
    paragraphs become plain lines. Returns a list of Markdown lines
    (joined with blank-line separators by the caller).
    """
    btype = b.get("type")

    if btype == "table":
        # AZ budget docs use the PDF tagged structure tree to mark
        # individual values as 1×1 "tables" with large column_span values
        # for visual layout — a page can carry 100+ such micro-tables.
        # Rendering each as a Markdown grid produces walls of empty pipes
        # because the column-span padding forces 80+ cells per row.
        #
        # Instead, walk the cell tree in source order and emit each
        # text-bearing cell as a plain line. Row/column metadata stays in
        # the JSON for downstream chunking (which can group by bbox-y
        # proximity to reconstruct logical rows when needed). The .md is
        # for human review during Phase 0 scoring; readability beats
        # structural fidelity at this rendering layer.
        rows = b.get("rows", []) or []
        cell_lines: list[str] = []
        for row in rows:
            for cell in row.get("cells", []) or []:
                t = _cell_text(cell)
                if t:
                    cell_lines.append(t)
        if not cell_lines:
            return []
        return ["\n".join(cell_lines)]

    text = b.get("content")
    if not text:
        return []
    if btype == "heading":
        level = b.get("heading level") or 1
        return [f"{'#' * int(level)} {text}"]
    return [str(text)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run OpenDataLoader-PDF on a PDF, per-page output."
    )
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pages", required=True, help="e.g. '5', '5-10', '5,7,9-11'")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="skip real extraction (test mode)",
    )
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    pages = parse_pages(args.pages)

    if args.dry_run:
        write_dry_run(args.pdf, args.out, pages)
    else:
        run_opendataloader(args.pdf, args.out, pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
