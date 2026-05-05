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
        opendataloader_pdf.convert(
            input_path=str(pdf),
            output_dir=str(tmp_path),
            format="json",
            pages=_format_pages_for_cli(pages),
            quiet=True,
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

    # Bucket all elements by 1-indexed page
    blocks_by_page: dict[int, list[dict]] = {}
    for el in doc.get("kids", []):
        p = _block_page(el)
        if p is not None:
            blocks_by_page.setdefault(p, []).append(el)

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

        # Synthesized Markdown — preserve element order and join `content`.
        # OpenDataLoader's native markdown export doesn't split per-page in a
        # form we can recover without a separator hack, so we build it here.
        md_lines: list[str] = []
        for b in blocks:
            text = b.get("content")
            if not text:
                continue
            if b.get("type") == "heading":
                level = b.get("heading level") or 1
                md_lines.append(f"{'#' * int(level)} {text}")
            else:
                md_lines.append(str(text))
        (out / f"page-{page}.md").write_text(
            "\n\n".join(md_lines) + "\n",
            encoding="utf-8",
        )


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
