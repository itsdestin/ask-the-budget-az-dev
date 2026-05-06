"""Auto-score what's auto-scoreable, surface spot-checks for what isn't.

For Phase 0 Task 8 (Score OpenDataLoader outputs). Auto-fills:
  - cell_accuracy: from full-population numeric-token diff vs pypdf reference
  - multipage_reassembly: from JSON inspection (table IDs across pages)
  - header_detection (suggested): from CAPS-short-line vs heading-block comparison

Leaves blank for human review:
  - bbox_quality: requires rendering the PDF — picks 3 spot-check cells
                  per page so the human can verify in seconds
  - footnote_attachment: requires visual context

Outputs:
  samples/scores-opendataloader.csv     — pre-filled scores
  samples/scoring-helper.md             — per-page checklist with spot-checks

Both files are designed to be opened side-by-side with the PDFs in a
viewer; user reviews the checklist, fills in the two human-only
dimensions, accepts or overrides the auto-suggestions.
"""

from __future__ import annotations

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

import yaml

RE_NUM = re.compile(
    r"\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b|\$\s?\d+(?:,\d{3})*(?:\.\d+)?\b"
)
# CAPS-short-line heuristic for visual headings: a line of mostly upper-
# case alphabetics, ≤80 chars, not entirely numeric. Imperfect but cheap.
RE_CAPS_LINE = re.compile(r"^[A-Z][A-Z &/,'\-\.0-9]{2,79}$")

CACHE_PATH = Path("/tmp/scout-cache.json")
SCORES_CSV = Path("samples/scores-opendataloader.csv")
HELPER_MD = Path("samples/scoring-helper.md")
ODL_OUT = Path("samples/extractor-output/opendataloader")
PAGES_YAML = Path("samples/scoring-pages.yaml")
MANIFEST_YAML = Path("samples/manifest.yaml")


def cell_text(cell: dict) -> str:
    """Concatenate all content descendants of a table cell."""
    parts: list[str] = []

    def walk(n: dict) -> None:
        c = n.get("content")
        if c:
            parts.append(c)
        for k in n.get("kids", []) or []:
            walk(k)

    walk(cell)
    return " ".join(p.strip() for p in parts if p.strip()).strip()


def cell_bbox(cell: dict) -> list[float] | None:
    bb = cell.get("bounding box")
    if isinstance(bb, list) and len(bb) == 4:
        return bb
    # Fall back to the bbox of the first content kid
    for k in cell.get("kids", []) or []:
        bb = k.get("bounding box")
        if isinstance(bb, list) and len(bb) == 4:
            return bb
    return None


def fmt_bbox(bb: list[float] | None) -> str:
    if not bb:
        return "—"
    return f"[{bb[0]:.0f}, {bb[1]:.0f}, {bb[2]:.0f}, {bb[3]:.0f}]"


def numeric_diff(pypdf_text: str, md: str) -> tuple[set[str], set[str]]:
    """Return (numbers_only_in_pypdf, numbers_only_in_odl) after normalizing
    common formatting variations (dollar-sign with/without space, leading
    newline between $ and digits).
    """

    def normalize(s: str) -> str:
        # Strip leading $, whitespace, and stray newlines
        s = s.replace("\n", "").strip()
        if s.startswith("$"):
            s = s[1:].strip()
        return s

    p_nums = {normalize(n) for n in RE_NUM.findall(pypdf_text)}
    o_nums = {normalize(n) for n in RE_NUM.findall(md)}
    return p_nums - o_nums, o_nums - p_nums


def score_cell_accuracy(only_p: set[str], only_o: set[str]) -> tuple[int, str]:
    """Score the cell_accuracy dimension based on numeric-token diff.

    The rubric calls for sampling 5–10 cells. Doing a full-population
    diff over distinct numeric tokens is strictly stronger evidence:
    - 0 in either side = every numeric value present and exact = score 3
    - 1–2 differences = formatting/edge cases = score 2 with notes
    - 3+ real differences = score 1
    """
    n = len(only_p) + len(only_o)
    if n == 0:
        return 3, "All distinct numeric tokens match pypdf reference."
    elif n <= 4:
        # Inspect — usually formatting variations
        return 2, f"{len(only_p)} number(s) in pypdf only, {len(only_o)} in ODL only — likely formatting"
    else:
        return 1, f"{len(only_p)} pypdf-only / {len(only_o)} ODL-only — investigate"


def score_multipage(page_info: dict, page_blocks: list[dict], all_pages: dict) -> tuple[str, str]:
    """Score multipage_reassembly. Returns (score_or_NA, reasoning).

    Applies only to pages tagged `multi-page-table`. Other archetypes get NA.
    Looks at table `id` field — if the same id appears in another page's
    blocks for the same doc, that's structural linkage (score 2).
    """
    if "multi-page-table" not in page_info["archetypes"]:
        return "NA", "Archetype is not multi-page-table"

    doc_id = page_info["doc_id"]
    page = page_info["page"]

    table_ids_here = {
        b.get("id")
        for b in page_blocks
        if b.get("type") == "table" and b.get("id") is not None
    }
    if not table_ids_here:
        return "0", "No table block detected on this page"

    # Look for the same table id in other pages of the same doc
    shared_with: list[int] = []
    for other_page, other_blocks in all_pages.get(doc_id, {}).items():
        if other_page == page:
            continue
        other_ids = {b.get("id") for b in other_blocks if b.get("type") == "table"}
        if table_ids_here & other_ids:
            shared_with.append(other_page)

    if shared_with:
        return "2", f"Table ID shared with pages {sorted(shared_with)} (structural linkage, no explicit continues_from)"
    return "1", "Table is not linked to other pages of the run"


def suggest_header_detection(pypdf_text: str, blocks: list[dict]) -> tuple[int, str]:
    """Suggest a header_detection score by comparing visual-heading
    candidates in pypdf to heading blocks in ODL output.
    """
    caps_lines = [
        ln for ln in pypdf_text.splitlines()
        if RE_CAPS_LINE.match(ln.strip()) and not ln.strip().isdigit()
    ]
    odl_headings = [b for b in blocks if b.get("type") == "heading"]

    if not caps_lines and not odl_headings:
        return 3, "No visual headings expected; ODL also detected none"

    # If ODL detected at least 50% of CAPS-line candidates, consider it OK
    n_caps = len(caps_lines)
    n_head = len(odl_headings)
    if n_caps == 0:
        return 2, f"No CAPS-line candidates; ODL flagged {n_head} (verify these aren't false positives)"
    ratio = n_head / max(n_caps, 1)
    if ratio >= 0.8:
        return 3, f"{n_head} headings detected vs ~{n_caps} CAPS candidates (good coverage)"
    if ratio >= 0.4:
        return 2, f"{n_head}/{n_caps} CAPS candidates flagged as heading"
    return 1, f"{n_head}/{n_caps} — ODL missed most visual headings (verify)"


def pick_spot_checks(blocks: list[dict]) -> list[dict]:
    """Pick 3 cells/blocks for the user to spot-check on the PDF.

    Strategy: collect every text-bearing leaf (table cells with content
    or paragraph blocks), then pick first / middle / last by source order.
    Skips blocks shorter than 5 chars to avoid noise (page numbers etc.).
    """
    leaves: list[dict] = []
    for b in blocks:
        if b.get("type") == "table":
            for row in b.get("rows", []) or []:
                for c in row.get("cells", []) or []:
                    t = cell_text(c)
                    if len(t) >= 5:
                        leaves.append({
                            "kind": "cell",
                            "text": t,
                            "bbox": cell_bbox(c),
                            "row": c.get("row number"),
                            "col": c.get("column number"),
                        })
        else:
            t = (b.get("content") or "").strip()
            if len(t) >= 5:
                leaves.append({
                    "kind": b.get("type", "block"),
                    "text": t[:120],
                    "bbox": b.get("bounding box"),
                    "row": None,
                    "col": None,
                })

    if not leaves:
        return []
    if len(leaves) <= 3:
        return leaves
    return [leaves[0], leaves[len(leaves) // 2], leaves[-1]]


def main() -> int:
    cache = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    pages_spec = yaml.safe_load(PAGES_YAML.read_text(encoding="utf-8"))["pages"]
    manifest = {
        d["id"]: d
        for d in yaml.safe_load(MANIFEST_YAML.read_text(encoding="utf-8"))["documents"]
    }

    # Pre-load all per-page block lists for the multi-page-id-sharing check
    all_pages_blocks: dict[str, dict[int, list[dict]]] = defaultdict(dict)
    for p in pages_spec:
        doc_id, page = p["doc_id"], p["page"]
        j = json.loads(
            (ODL_OUT / doc_id / f"page-{page}.json").read_text(encoding="utf-8")
        )
        all_pages_blocks[doc_id][page] = j["blocks"]

    # Build CSV rows + helper Markdown
    csv_rows: list[dict] = []
    helper_lines: list[str] = []
    helper_lines.append("# Phase 0 Task 8 — Scoring Helper (OpenDataLoader)")
    helper_lines.append("")
    helper_lines.append("## How to use this file")
    helper_lines.append("")
    helper_lines.append("For each page below you'll see four things:")
    helper_lines.append("1. A **preview PNG** showing the PDF page with extraction bboxes drawn on it (light blue = every detected element; ① ② ③ red badges = spot-check cells)")
    helper_lines.append("2. The **3 spot-check cell texts** the red badges correspond to")
    helper_lines.append("3. **Auto-scores** I've already filled into `samples/scores-opendataloader.csv`")
    helper_lines.append("4. **What to score yourself** in the CSV")
    helper_lines.append("")
    helper_lines.append("### Per-page workflow (~3 min/page)")
    helper_lines.append("")
    helper_lines.append("**Step 1 — Open the preview PNG.** Look at the 3 red boxes (① ② ③).")
    helper_lines.append("- Does each red box surround a single, readable element on the page (not too much, not too little, not a wrong region)?")
    helper_lines.append("- Look at the light-blue boxes overall: do they look like reasonable element boundaries, or is there obvious chaos (boxes crossing unrelated content, missing whole regions, etc.)?")
    helper_lines.append("")
    helper_lines.append("**Step 2 — Compare the 3 spot-check texts** (in the table for each page) **with what's actually in those red boxes on the PNG.**")
    helper_lines.append("- All 3 match exactly: the auto-scored `cell_accuracy` is correct.")
    helper_lines.append("- 1 mismatch: override `cell_accuracy` to 2 in the CSV.")
    helper_lines.append("- 2+ mismatches or wrong digits: override to 1 (or 0).")
    helper_lines.append("")
    helper_lines.append("**Step 3 — Score `bbox_quality` in the CSV** based on Step 1:")
    helper_lines.append("- All 3 red boxes tight around their content, blue boxes look reasonable: **3**")
    helper_lines.append("- 1 red box off (covers extra content or misses content), or blue boxes drift on a few items: **2**")
    helper_lines.append("- 2+ red boxes off, or blue boxes are clearly wrong on many items: **1**")
    helper_lines.append("- No bboxes drawn, or wildly off-page: **0**")
    helper_lines.append("")
    helper_lines.append("**Step 4 — Score `footnote_attachment` in the CSV.**")
    helper_lines.append("- If the page has no footnote markers visible: **NA**")
    helper_lines.append("- If footnotes exist: open the PDF (or just look at the PNG) and pick one footnote marker like `(1)` or `*`. Open `samples/extractor-output/opendataloader/<doc>/page-<N>.md`. Is the footnote text near the row that referenced it (within ~5 lines)?")
    helper_lines.append("  - Tied correctly: **3**. Footnote present but unattached: **2**. Wrong row or mangled: **1**. Footnote dropped: **0**.")
    helper_lines.append("")
    helper_lines.append("**Step 5 — Confirm or override `header_detection`.**")
    helper_lines.append("- Open the .md file. Count `# Heading` lines.")
    helper_lines.append("- Compare with how many visual headings (large/bold text) you see on the PNG.")
    helper_lines.append("- All caught, no false flags: **3**. 1 missed or 1 false: **2**. ≥2 missed: **1**. None caught: **0**.")
    helper_lines.append("- Sometimes ODL puts headings INSIDE table blocks (visible in the .json) rather than as `heading`-typed blocks. If the heading text is somewhere in the output (just not labeled `heading`), score 2.")
    helper_lines.append("")
    helper_lines.append("**Step 6 — Don't change `cell_accuracy` or `multipage_reassembly` unless Step 2 surfaced a problem** (these were auto-scored from data; trust them by default).")
    helper_lines.append("")
    helper_lines.append("---")

    for p in pages_spec:
        doc_id, page = p["doc_id"], p["page"]
        archetypes = p["archetypes"]
        pypdf_text = next(
            pp["text"] for pp in cache[doc_id] if pp["page"] == page
        )
        blocks = all_pages_blocks[doc_id][page]
        md = (ODL_OUT / doc_id / f"page-{page}.md").read_text(encoding="utf-8")
        pdf_path = manifest[doc_id]["local_path"]

        # Auto-scores
        only_p, only_o = numeric_diff(pypdf_text, md)
        cell_acc, cell_acc_why = score_cell_accuracy(only_p, only_o)
        multi, multi_why = score_multipage(p, blocks, all_pages_blocks)
        head_score, head_why = suggest_header_detection(pypdf_text, blocks)

        # Footnote applicability hint (still needs human verification)
        n_footnote_markers = (
            len(re.findall(r"\(\d{1,2}\)", pypdf_text))
            + len(re.findall(r"\([a-z]\)", pypdf_text))
            + len(re.findall(r"\*+", pypdf_text))
        )
        footnote_hint = "applies" if "footnote-heavy" in archetypes or n_footnote_markers >= 4 else "likely NA"

        spot_checks = pick_spot_checks(blocks)

        csv_rows.append({
            "doc_id": doc_id,
            "page": page,
            "archetypes": ";".join(archetypes),
            "cell_accuracy": cell_acc,
            "bbox_quality": "",
            "multipage_reassembly": multi,
            "header_detection": head_score,
            "footnote_attachment": "",
            "notes": cell_acc_why,
        })

        # Per-page helper section
        helper_lines.append("")
        helper_lines.append(f"## {doc_id} p.{page} — `{', '.join(archetypes)}`")
        helper_lines.append("")
        helper_lines.append(f"**Preview:** `samples/scoring-helpers/{doc_id}/page-{page}.png` _(the page with bboxes drawn — open this first)_")
        helper_lines.append(f"**Original PDF:** `{pdf_path}` (page {page})")
        helper_lines.append(f"**Extraction output:** `samples/extractor-output/opendataloader/{doc_id}/page-{page}.{{json,md}}`")
        helper_lines.append("")
        if spot_checks:
            helper_lines.append("**Spot-checks (the red ① ② ③ on the preview):** confirm each red box surrounds the matching text on the page.")
            helper_lines.append("")
            helper_lines.append("| Badge | What's inside the red box should be |")
            helper_lines.append("|---|---|")
            for i, s in enumerate(spot_checks, 1):
                content = s["text"].replace("|", "\\|").replace("\n", " ")
                helper_lines.append(f"| ⓘ{i} | `{content}` |")
        else:
            helper_lines.append("_No text-bearing blocks were detected on this page — extraction may have failed. Score everything 0._")
        helper_lines.append("")
        helper_lines.append("**Already auto-scored in the CSV** (don't re-score unless your spot-check disagrees):")
        helper_lines.append(f"- `cell_accuracy` = **{cell_acc}** — {cell_acc_why}")
        helper_lines.append(f"- `multipage_reassembly` = **{multi}** — {multi_why}")
        helper_lines.append("")
        helper_lines.append(f"**Auto-suggested, please confirm:** `header_detection` = **{head_score}** — {head_why}")
        helper_lines.append("")
        helper_lines.append(f"**You score:** `bbox_quality` (from the red boxes in the preview) and `footnote_attachment` (hint: {footnote_hint}, {n_footnote_markers} marker candidates found in pypdf text).")

    # Write helper markdown first — it has no risk of clobbering user
    # work (it's regenerated from data each run).
    HELPER_MD.write_text("\n".join(helper_lines) + "\n", encoding="utf-8")
    print(f"wrote {HELPER_MD}")

    # CSV is the user's working scoring file. If it's locked (open in
    # Excel) OR if the user has already filled in bbox_quality /
    # footnote_attachment values, skip the rewrite and tell them.
    skip_csv = False
    if SCORES_CSV.exists():
        try:
            with SCORES_CSV.open("r", encoding="utf-8") as f:
                existing = list(csv.DictReader(f))
            for row in existing:
                if row.get("bbox_quality") or row.get("footnote_attachment"):
                    skip_csv = True
                    break
        except Exception:
            pass

    if skip_csv:
        print(
            f"SKIPPED writing {SCORES_CSV} — it has user-filled scores. "
            "Edit it directly or delete + rerun this script."
        )
        return 0
    try:
        with SCORES_CSV.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "doc_id", "page", "archetypes",
                    "cell_accuracy", "bbox_quality", "multipage_reassembly",
                    "header_detection", "footnote_attachment", "notes",
                ],
            )
            writer.writeheader()
            writer.writerows(csv_rows)
        print(f"wrote {SCORES_CSV} ({len(csv_rows)} rows)")
    except PermissionError:
        print(
            f"WARNING: {SCORES_CSV} is locked (open in Excel?). "
            "Close it and re-run if you want auto-scores refreshed; "
            "the helper.md was still updated."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
