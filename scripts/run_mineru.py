"""Run MinerU 2.5 on one PDF, optionally restricted to a page range.

Implementation note: MinerU 3.1.6 doesn't expose a stable Python API. We
shell out to the `mineru` CLI (which itself starts a temporary local
FastAPI server, submits a parse task, and writes Markdown + structured
JSON to an output directory). This wrapper invokes the CLI per
contiguous page range and translates its output into our per-page
contract.

Outputs (per-page contract, stable across extractor choice):
  <out>/page-<N>.json   — structured extraction. Carries:
                          {extractor, source_pdf, page,
                           blocks: [<entries from MinerU's _content_list.json
                                    that belong to this page>]}
  <out>/page-<N>.md     — Markdown text concatenated from this page's blocks

Why per-page files: keeps later scoring tasks tractable. Each scoring pass
opens one JSON + one Markdown side by side with the corresponding PDF page.
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory


def parse_pages(arg: str, total_pages: int | None = None) -> list[int]:
    """Parse '1', '1-3', '1,3,5', '1-3,7' into a list of 1-indexed pages."""
    pages: set[int] = set()
    for piece in arg.split(","):
        piece = piece.strip()
        if "-" in piece:
            lo, hi = piece.split("-", 1)
            pages.update(range(int(lo), int(hi) + 1))
        else:
            pages.add(int(piece))
    return sorted(pages)


def write_dry_run(pdf: Path, out: Path, pages: list[int]) -> None:
    """Stub for testing — writes a minimal valid output without invoking MinerU."""
    out.mkdir(parents=True, exist_ok=True)
    for page in pages:
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "mineru-dry-run",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": [],
                },
                indent=2,
            )
        )
        (out / f"page-{page}.md").write_text(f"# Dry-run page {page}\n")


def _contiguous_ranges(pages: list[int]) -> list[tuple[int, int]]:
    """Group sorted 1-indexed pages into contiguous (start, end) ranges (inclusive).

    [1, 2, 3, 7, 9, 10] -> [(1, 3), (7, 7), (9, 10)]

    Why: MinerU's CLI takes a single page-range per invocation, and each
    invocation re-loads models. Collapsing contiguous pages amortizes the
    per-invocation startup cost.
    """
    if not pages:
        return []
    pages = sorted(set(pages))
    ranges = [(pages[0], pages[0])]
    for p in pages[1:]:
        last_start, last_end = ranges[-1]
        if p == last_end + 1:
            ranges[-1] = (last_start, p)
        else:
            ranges.append((p, p))
    return ranges


def _read_mineru_output(mineru_out: Path, pdf_stem: str) -> tuple[list[dict], str]:
    """Read MinerU's per-document output. Returns (content_list, markdown).

    MinerU writes to <mineru_out>/<pdf_stem>/<parse_method>/ where
    parse_method is one of {auto, txt, ocr}. The parse_method
    subdirectory name varies by backend/CLI version, so we discover it
    rather than assuming.
    """
    doc_dir = mineru_out / pdf_stem
    if not doc_dir.exists():
        raise RuntimeError(f"mineru produced no output dir at {doc_dir}")

    # parse_method subdir is the only directory under doc_dir
    method_dirs = [d for d in doc_dir.iterdir() if d.is_dir()]
    if not method_dirs:
        raise RuntimeError(f"mineru output at {doc_dir} has no method subdirectory")
    method_dir = method_dirs[0]

    content_path = method_dir / f"{pdf_stem}_content_list.json"
    md_path = method_dir / f"{pdf_stem}.md"
    if not content_path.exists():
        raise RuntimeError(f"missing content list: {content_path}")
    if not md_path.exists():
        raise RuntimeError(f"missing markdown: {md_path}")

    content_list = json.loads(content_path.read_text(encoding="utf-8"))
    markdown = md_path.read_text(encoding="utf-8")
    return content_list, markdown


def _block_page(block: dict) -> int | None:
    """Extract a 1-indexed page number from a MinerU content-list entry.

    MinerU records pages as 0-indexed under `page_idx` (most common in
    3.x). We normalize to 1-indexed; missing pages return None so the
    caller can decide whether to skip the block.
    """
    if "page_idx" in block:
        return int(block["page_idx"]) + 1
    if "page" in block:
        return int(block["page"]) + 1
    return None


def write_range_pages(
    content_list: list[dict],
    *,
    out: Path,
    pdf: Path,
    start: int,
    end: int,
    pages: list[int],
) -> None:
    """Split one range's MinerU output into the per-page contract files.

    Module-level so the GUI ingest path (ingest/mineru_runner.py) reuses this
    exact logic instead of copying it. Two hard-won behaviors live in here and
    must not be re-derived:

    1. **Page reindexing.** MinerU's CLI renumbers pages from 0 *within* the
       requested range, so `-s 512 -e 512` (PDF page 513) comes back as
       page_idx=0. Treating that as an absolute page dropped every block on
       the floor. actual_page = start + (page_idx + 1 - 1).
    2. **Table rendering.** content_list mixes block kinds: text blocks carry
       `text`, table blocks carry `table_body` (HTML). Reading only `text`
       silently dropped every cell value from the Markdown.
    """
    # Bucket blocks by 1-indexed page in the SOURCE pdf.
    by_page: dict[int, list[dict]] = {}
    for block in content_list:
        local = _block_page(block)
        if local is not None:
            actual = start + (local - 1)
            by_page.setdefault(actual, []).append(block)

    # Only pages the caller asked for, even though MinerU processed the
    # whole [start, end] range.
    for page in range(start, end + 1):
        if page not in pages:
            continue
        blocks = by_page.get(page, [])
        (out / f"page-{page}.json").write_text(
            json.dumps(
                {
                    "extractor": "mineru-3.1.6",
                    "source_pdf": str(pdf),
                    "page": page,
                    "blocks": blocks,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        md_lines: list[str] = []
        for b in blocks:
            if b.get("type") == "table" and b.get("table_body"):
                md_lines.append(str(b["table_body"]))
            else:
                text = b.get("text") or b.get("content") or ""
                if text:
                    md_lines.append(str(text))
        (out / f"page-{page}.md").write_text(
            "\n\n".join(md_lines) + "\n",
            encoding="utf-8",
        )


def run_mineru(pdf: Path, out: Path, pages: list[int], *, method: str = "auto") -> None:
    """Real path. Shells out to `mineru` CLI per contiguous page range.

    For each range, runs `mineru -p <pdf> -o <tmp> -s <start-1> -e <end-1>
    -b pipeline -m <method>`, then reads the produced content list +
    markdown and splits them into per-page-N output files.

    The `pipeline` backend is chosen because it works on CPU only; the
    default `hybrid-auto-engine` may want a GPU. See the Phase 0 README
    at samples/extractor-output/mineru/README.md for backend rationale.

    `method` is MinerU's `-m` flag. "auto" is today's behaviour and the
    default, so every existing caller is unchanged. "ocr" is the ladder's
    last rung (spec T7, ingest/ladder.py) and reads pages as images --
    the only path that can read a scan, at the cost of being the slowest
    thing this app does.
    """
    out.mkdir(parents=True, exist_ok=True)
    pdf_stem = pdf.stem

    for start, end in _contiguous_ranges(pages):
        with TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            cmd = [
                "uv", "run", "mineru",
                "-p", str(pdf),
                "-o", str(tmp_path),
                "-s", str(start - 1),  # CLI is 0-indexed, inclusive
                "-e", str(end - 1),
                "-b", "pipeline",
                "-m", method,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode != 0:
                # Trim stderr — mineru's logs can be hundreds of lines on success too,
                # so on failure we want only the tail where the actual error usually lives.
                tail = "\n".join((result.stderr or result.stdout).splitlines()[-30:])
                raise RuntimeError(
                    f"mineru CLI failed for pages {start}-{end} of {pdf.name}:\n{tail}"
                )

            content_list, markdown = _read_mineru_output(tmp_path, pdf_stem)

        write_range_pages(
            content_list, out=out, pdf=pdf, start=start, end=end, pages=pages
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run MinerU 2.5 on a PDF, per-page output.")
    parser.add_argument("--pdf", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--pages", required=True, help="e.g. '5', '5-10', '5,7,9-11'")
    parser.add_argument("--dry-run", action="store_true", help="skip real extraction (test mode)")
    args = parser.parse_args(argv)

    if not args.pdf.exists():
        print(f"PDF not found: {args.pdf}", file=sys.stderr)
        return 2

    pages = parse_pages(args.pages)

    if args.dry_run:
        write_dry_run(args.pdf, args.out, pages)
    else:
        run_mineru(args.pdf, args.out, pages)
    return 0


if __name__ == "__main__":
    sys.exit(main())
