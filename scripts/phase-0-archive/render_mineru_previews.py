"""Render per-page PNGs with MinerU's bboxes drawn on them.

Parallel to scripts/render_score_previews.py but for MinerU output.
MinerU's bbox coordinate system differs from OpenDataLoader's:
  - OpenDataLoader: PDF user-space (origin bottom-left, y-up, units pts)
  - MinerU: image-space at MinerU's internal render DPI (origin
    top-left, y-down, units px). Empirical calibration on the 612×792-pt
    AZ approps PDFs put MinerU's max-y around 952, giving a scale of
    ~1.20× the PDF's 72-DPI base — i.e. MinerU rasterizes at ~86 DPI
    internally. Computing the scale per-page from observed bbox extents
    rather than hard-coding (in case the backend changes per-page).

Usage:
    uv run python scripts/render_mineru_previews.py <doc_id> <page>...

Example:
    uv run python scripts/render_mineru_previews.py jlbc-approps-fy26 164 513

Output: samples/scoring-helpers-mineru/<doc>/page-<N>.png
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
import fitz
from PIL import Image, ImageDraw, ImageFont

MANIFEST_YAML = Path("samples/manifest.yaml")
MINERU_OUT = Path("samples/extractor-output/mineru")
PREVIEWS_OUT = Path("samples/scoring-helpers-mineru")

DPI = 150


def all_bboxes(blocks: list[dict]) -> list[list[float]]:
    """Every bbox MinerU emitted on this page. We render one per block;
    cells inside table_body HTML don't carry their own bboxes in the
    content_list output, so the table block's outer rectangle is what
    we draw for the table."""
    out: list[list[float]] = []
    for b in blocks:
        bb = b.get("bbox")
        if isinstance(bb, list) and len(bb) == 4:
            out.append(bb)
    return out


def infer_scale(blocks: list[dict], page_h_pt: float) -> float:
    """Given that MinerU's bbox y-axis runs origin-top to image-bottom,
    the largest y-coordinate observed should land at or below the
    rendered page bottom. Compute scale = max_y / page_h_pt; fall back
    to 1.20 if no bboxes are present.
    """
    max_y = 0.0
    for b in blocks:
        bb = b.get("bbox")
        if isinstance(bb, list) and len(bb) == 4:
            max_y = max(max_y, bb[3])
    if max_y <= 0:
        return 1.20
    return max_y / page_h_pt


def render_page(
    pdf_path: Path,
    page_num_1indexed: int,
    out_png: Path,
    blocks: list[dict],
) -> None:
    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_num_1indexed - 1]
        page_h_pt = page.rect.height
        zoom = DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes(
            "RGB", (pix.width, pix.height), pix.samples
        ).convert("RGBA")
    finally:
        doc.close()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    mineru_scale = infer_scale(blocks, page_h_pt)

    def to_image_xyxy(bb: list[float]) -> tuple[int, int, int, int]:
        # MinerU bbox: image-space at DPI = 72 * mineru_scale, top-left origin.
        # We need to re-scale into our render-DPI image-space.
        rescale = (DPI / 72.0) / mineru_scale
        return (
            int(bb[0] * rescale),
            int(bb[1] * rescale),
            int(bb[2] * rescale),
            int(bb[3] * rescale),
        )

    # Color by block type so the analyst can tell what MinerU thought
    # each region was. Tables are the structurally-interesting blocks
    # for this corpus, so they get the strongest accent.
    colors = {
        "table":       (220, 30, 30, 255),     # red
        "text":        (30, 110, 220, 220),    # blue
        "page_number": (130, 130, 130, 200),   # grey
        "footer":      (130, 130, 130, 200),
        "image":       (40, 160, 80, 220),     # green
    }
    pad = 4

    for b in blocks:
        bb = b.get("bbox")
        if not (isinstance(bb, list) and len(bb) == 4):
            continue
        rect = to_image_xyxy(bb)
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            continue
        outset = (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)
        color = colors.get(b.get("type"), (220, 30, 30, 220))
        width = 4 if b.get("type") == "table" else 2
        draw.rectangle(outset, outline=color, width=width)

    # Add a small legend in the upper-right corner.
    try:
        font = ImageFont.truetype(r"C:\Windows\Fonts\arialbd.ttf", 18)
    except (IOError, OSError):
        font = ImageFont.load_default()
    legend_lines = [
        ("table",       colors["table"]),
        ("text",        colors["text"]),
        ("page_number", colors["page_number"]),
    ]
    lx = img.size[0] - 220
    ly = 20
    draw.rectangle((lx - 8, ly - 8, lx + 220, ly + 20 * len(legend_lines) + 8),
                   fill=(255, 255, 255, 220), outline=(0, 0, 0, 255), width=1)
    for label, color in legend_lines:
        draw.rectangle((lx, ly + 4, lx + 16, ly + 16), fill=color, outline=(0, 0, 0, 255))
        draw.text((lx + 24, ly), label, fill=(0, 0, 0, 255), font=font)
        ly += 20

    out_img = Image.alpha_composite(img, overlay).convert("RGB")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(str(out_png), optimize=True)


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: render_mineru_previews.py <doc_id> <page>...", file=sys.stderr)
        return 2
    doc_id = argv[0]
    pages = [int(p) for p in argv[1:]]

    manifest = {
        d["id"]: d
        for d in yaml.safe_load(MANIFEST_YAML.read_text(encoding="utf-8"))["documents"]
    }
    pdf_path = Path(manifest[doc_id]["local_path"])

    for page in pages:
        json_path = MINERU_OUT / doc_id / f"page-{page}.json"
        out_png = PREVIEWS_OUT / doc_id / f"page-{page}.png"
        blocks = json.loads(json_path.read_text(encoding="utf-8"))["blocks"]
        render_page(pdf_path, page, out_png, blocks)
        size_kb = out_png.stat().st_size // 1024
        print(f"  {out_png}  ({size_kb} KB, {len(blocks)} blocks)")

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
