"""Render per-page PNGs with extraction bboxes drawn on them.

For Phase 0 Task 8 (Score OpenDataLoader). The scoring rubric's
`bbox_quality` dimension was unanswerable from coordinates alone — this
script renders each scoring page at 150 DPI with:

  - ALL extracted blocks shown in light blue (covers paragraphs, table
    cells, headings — everything that has a bounding box)
  - The 3 spot-check cells (same ones surfaced in scoring-helper.md)
    overlaid in red and numbered ①②③

The user opens samples/scoring-helpers/<doc>/page-<N>.png alongside
samples/scores-opendataloader.csv and checks visually whether the red
boxes surround sensible regions.

Coordinate handling: OpenDataLoader emits PDF user-space coordinates
(origin bottom-left, y-up). PyMuPDF uses image-space (origin top-left,
y-down). We convert each bbox via page.rect.height before drawing.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import yaml
import fitz  # PyMuPDF

PAGES_YAML = Path("samples/scoring-pages.yaml")
MANIFEST_YAML = Path("samples/manifest.yaml")
ODL_OUT = Path("samples/extractor-output/opendataloader")
PREVIEWS_OUT = Path("samples/scoring-helpers")

DPI = 150

# Drawing colors (in 0..1 RGBA for fitz.Pixmap drawing).
ALL_BLOCKS_COLOR = (0.30, 0.55, 0.90, 0.55)   # translucent blue
SPOT_CHECK_COLOR = (0.90, 0.20, 0.20, 0.85)   # bright red


def cell_text(cell: dict) -> str:
    parts: list[str] = []

    def walk(n: dict) -> None:
        c = n.get("content")
        if c:
            parts.append(c)
        for k in n.get("kids", []) or []:
            walk(k)

    walk(cell)
    return " ".join(p.strip() for p in parts if p.strip())


def cell_bbox(cell: dict) -> list[float] | None:
    bb = cell.get("bounding box")
    if isinstance(bb, list) and len(bb) == 4:
        return bb
    for k in cell.get("kids", []) or []:
        bb = k.get("bounding box")
        if isinstance(bb, list) and len(bb) == 4:
            return bb
    return None


def collect_all_bboxes(blocks: list[dict]) -> list[list[float]]:
    """All bboxes on the page (paragraphs, headings, table cells)."""
    out: list[list[float]] = []
    for b in blocks:
        if b.get("type") == "table":
            for row in b.get("rows", []) or []:
                for c in row.get("cells", []) or []:
                    if cell_text(c):
                        bb = cell_bbox(c)
                        if bb:
                            out.append(bb)
        else:
            bb = b.get("bounding box")
            if bb and b.get("content"):
                out.append(bb)
    return out


def pick_spot_checks(blocks: list[dict]) -> list[dict]:
    """Same logic as score_helper.py — keep the two scripts in sync."""
    leaves: list[dict] = []
    for b in blocks:
        if b.get("type") == "table":
            for row in b.get("rows", []) or []:
                for c in row.get("cells", []) or []:
                    t = cell_text(c)
                    if len(t) >= 5:
                        leaves.append({"text": t, "bbox": cell_bbox(c)})
        else:
            t = (b.get("content") or "").strip()
            if len(t) >= 5:
                leaves.append({"text": t[:120], "bbox": b.get("bounding box")})
    if not leaves:
        return []
    if len(leaves) <= 3:
        return leaves
    return [leaves[0], leaves[len(leaves) // 2], leaves[-1]]


def pdf_to_image_rect(bb: list[float], page_height: float) -> fitz.Rect:
    """Convert a PDF user-space bbox (origin bottom-left, y-up) to a
    PyMuPDF image-space Rect (origin top-left, y-down).
    """
    x0, y0, x1, y1 = bb
    return fitz.Rect(x0, page_height - y1, x1, page_height - y0)


def render_page(
    pdf_path: Path,
    page_num_1indexed: int,
    out_png: Path,
    blocks: list[dict],
) -> None:
    """Render the page, then draw bboxes onto the rasterized image.

    PyMuPDF's `add_rect_annot` -> `get_pixmap` pipeline didn't render
    annotations reliably across versions, so we rasterize first and
    draw with PIL — fully deterministic, no annotation flattening.
    """
    from PIL import Image, ImageDraw, ImageFont

    doc = fitz.open(str(pdf_path))
    try:
        page = doc[page_num_1indexed - 1]
        page_h = page.rect.height

        zoom = DPI / 72.0
        mat = fitz.Matrix(zoom, zoom)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples).convert("RGBA")
    finally:
        doc.close()

    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    def to_image_xyxy(bb: list[float]) -> tuple[int, int, int, int]:
        x0, y0, x1, y1 = bb
        # PDF user-space (y-up) -> image space (y-down) and apply DPI zoom.
        ix0 = int(x0 * zoom)
        iy0 = int((page_h - y1) * zoom)
        ix1 = int(x1 * zoom)
        iy1 = int((page_h - y0) * zoom)
        return ix0, iy0, ix1, iy1

    # All-blocks: light blue outline. Width 2 so it survives compression.
    for bb in collect_all_bboxes(blocks):
        rect = to_image_xyxy(bb)
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            continue
        draw.rectangle(rect, outline=(76, 140, 230, 200), width=2)

    # Spot-checks: thick red outline + a chunky badge that sits OUTSIDE
    # the bbox (to its left) so it doesn't cover the cell content.
    spots = pick_spot_checks(blocks)
    # Try several common Windows fonts; PIL's default is too small for
    # these previews (you can't read a digit at 8px).
    font = None
    for candidate in (
        r"C:\Windows\Fonts\arialbd.ttf",
        r"C:\Windows\Fonts\arial.ttf",
        "arial.ttf",
        "DejaVuSans-Bold.ttf",
    ):
        try:
            font = ImageFont.truetype(candidate, 36)
            break
        except (IOError, OSError):
            continue
    if font is None:
        font = ImageFont.load_default()

    img_w, img_h = img.size
    for i, s in enumerate(spots, start=1):
        if not s.get("bbox"):
            continue
        rect = to_image_xyxy(s["bbox"])
        if rect[2] <= rect[0] or rect[3] <= rect[1]:
            continue
        # Inflate the spot-check rect outward so the border sits clear of
        # the text edges (a tight-bbox outline at width=6 paints 3px over
        # the glyphs themselves). Padding chosen empirically — 6px at
        # 150 DPI keeps the outline visibly outside the text without
        # making adjacent spot-checks overlap each other.
        pad = 6
        outset = (rect[0] - pad, rect[1] - pad, rect[2] + pad, rect[3] + pad)
        draw.rectangle(outset, outline=(220, 30, 30, 255), width=3)
        # Badge: 50×50 translucent red. Translucency is the difference
        # between "I can read the cell underneath" (good) and "the badge
        # erases the content I'm trying to verify" (bad — caught during
        # 2026-05-05 review). Alpha ~150/255 lets text show through.
        # Outline + text stay full-alpha so the badge remains visible.
        badge_size = 50
        # Placement: try LEFT of the inflated outline first, then ABOVE,
        # then fall back inside the bbox upper-left.
        bx0 = outset[0] - badge_size - 4
        by0 = outset[1] - 4
        if bx0 < 0:
            bx0_above = outset[0]
            by0_above = outset[1] - badge_size - 4
            if by0_above >= 0:
                bx0, by0 = bx0_above, by0_above
            else:
                bx0, by0 = rect[0] + 2, rect[1] + 2  # inside fallback
        # Clamp to visible area.
        bx0 = max(0, min(bx0, img_w - badge_size))
        by0 = max(0, min(by0, img_h - badge_size))
        draw.rectangle(
            (bx0, by0, bx0 + badge_size, by0 + badge_size),
            fill=(220, 30, 30, 150),
            outline=(140, 0, 0, 255),
            width=3,
        )
        draw.text(
            (bx0 + 13, by0 + 2),
            str(i),
            fill=(255, 255, 255, 255),
            font=font,
        )

    out_img = Image.alpha_composite(img, overlay).convert("RGB")
    out_png.parent.mkdir(parents=True, exist_ok=True)
    out_img.save(str(out_png), optimize=True)


def main() -> int:
    pages_spec = yaml.safe_load(PAGES_YAML.read_text(encoding="utf-8"))["pages"]
    manifest = {
        d["id"]: d
        for d in yaml.safe_load(MANIFEST_YAML.read_text(encoding="utf-8"))["documents"]
    }

    for p in pages_spec:
        doc_id, page = p["doc_id"], p["page"]
        pdf_path = Path(manifest[doc_id]["local_path"])
        json_path = ODL_OUT / doc_id / f"page-{page}.json"
        out_png = PREVIEWS_OUT / doc_id / f"page-{page}.png"

        blocks = json.loads(json_path.read_text(encoding="utf-8"))["blocks"]
        render_page(pdf_path, page, out_png, blocks)
        size_kb = out_png.stat().st_size // 1024
        print(f"  {out_png}  ({size_kb} KB)")

    print(f"\ndone. {len(pages_spec)} previews rendered to {PREVIEWS_OUT}/")
    return 0


if __name__ == "__main__":
    sys.exit(main())
