"""DOCX reader.

Consumes the JSON written by `scripts/run_docx_ingest.py`:

    {
      "extractor": "python-docx",
      "source_docx": "...",
      "blocks": [
        {"kind": "paragraph", "paragraph_id": "p:00A14B33", "style": "...",
         "text": "...", "cells": [...] | absent},
        {"kind": "table_cell", "table_cell_id": "t1-r1-c1", "row": 1, "col": 1,
         "text": "..."}
      ]
    }

Bill structure (cross-doc-relationships §9):
- **Part 1: agency tables.** Heading paragraph styled `Normal` whose text is
  an ALL-CAPS department name (e.g. `DEPARTMENT OF CORRECTIONS`). Body
  paragraphs in `P 06-*` styles, typically tab-split line-item rows.
- **Part 2: provisions.** Heading paragraph styled `SEC 06-18`,
  `SEC 06-19`, etc. (the trailing number identifies a section type). Body
  paragraphs in `Normal` style.

Reader API (mirrors ODL/MinerU):

    DocxReader().read(path) -> ExtractedDocument

DOCX has no pages — `doc.pages` is left empty. The DOCX-specific surface is
`doc.sections`. Module-level utilities `parse_bill_heading` and
`parse_bill_body` decompose section text per the cross-doc-relationships
§9 conventions.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from chunking.readers.types import (
    DocxBlock,
    DocxParagraph,
    DocxTableCell,
    ExtractedDocument,
    Section,
)

# Bill action prefixes observed in cross-doc-relationships §9. New actions can
# be added here without breaking the parser — unknown prefixes fall through
# to `action="other"` with the original heading preserved.
_BILL_ACTIONS = (
    "Supplemental appropriation",
    "Appropriation reduction",
    "Appropriation",
    "Fund balance transfer",
    "Fund deposit",
    "Fund transfer",
    "Lump sum reduction",
    "Lump sum",
    "Repeal",
    "Exemption",
)

# Match A.R.S. section refs of the form `section 41-792.01` (with optional
# decimal subsection). Anchored on `section ` (case-insensitive) since
# trailing context is usually `, A.R.S.` or end of clause.
_ARS_RE = re.compile(r"\bsection\s+(\d+-\d+(?:\.\d+)?)", re.IGNORECASE)

# Fiscal-year extractor. Bill conventions use 'FY 2026' / 'FY2026'.
_FY_RE = re.compile(r"\bFY\s*(\d{4})\b")

# All-caps detector for Part 1 agency-table headings. Permits & spaces and
# digits but the heading text should be predominantly uppercase letters.
_DEPT_HEADING_RE = re.compile(r"^[A-Z][A-Z &\-,'/0-9]{4,}$")


class DocxReader:
    """Reads run_docx_ingest output → ExtractedDocument with sections."""

    def read(self, path: Path | str) -> ExtractedDocument:
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"DOCX output path does not exist: {path}")
        if path.is_dir():
            # run_docx_ingest emits document.json + document.md
            json_path = path / "document.json"
            if not json_path.exists():
                raise FileNotFoundError(f"document.json not found in {path}")
            path = json_path

        raw = json.loads(path.read_text(encoding="utf-8"))
        blocks_raw = raw.get("blocks", []) or []

        sections = self._build_sections(blocks_raw)

        return ExtractedDocument(
            source_path=Path(raw.get("source_docx") or path),
            extractor="python-docx",
            sections=sections,
        )

    # --- section detection --------------------------------------------------

    def _build_sections(self, blocks: list[dict]) -> list[Section]:
        """Walk the flat block list, emit a Section every time a heading
        boundary is crossed. Body blocks attach to the most recent section.
        """
        out: list[Section] = []
        current: Section | None = None

        for raw_block in blocks:
            kind = raw_block.get("kind")

            if kind == "paragraph":
                style = str(raw_block.get("style") or "Normal")
                text = str(raw_block.get("text") or "").strip()
                paragraph_id = str(raw_block.get("paragraph_id") or "")
                cells = raw_block.get("cells")

                if self._is_section_heading(style, text):
                    current = Section(
                        style=style,
                        heading_text=text,
                        heading_paragraph_id=paragraph_id,
                        parsed_heading=parse_bill_heading(text) if style.startswith("SEC ") else {},
                    )
                    # Seed ars_refs with anything from the heading itself
                    current.ars_refs = parse_bill_body(text)
                    out.append(current)
                    continue

                if current is None:
                    # Body paragraph before any heading — attach to a synthetic
                    # "preamble" section so we don't lose content. Bills
                    # typically begin with a heading, so this is rare.
                    current = Section(
                        style="preamble", heading_text="", heading_paragraph_id=""
                    )
                    out.append(current)
                current.body_blocks.append(
                    DocxParagraph(
                        text=text,
                        paragraph_id=paragraph_id,
                        style=style,
                        cells=list(cells) if cells else None,
                    )
                )
                # Merge body refs into the section's ars_refs
                for ref in parse_bill_body(text):
                    if ref not in current.ars_refs:
                        current.ars_refs.append(ref)

            elif kind == "table_cell":
                if current is None:
                    current = Section(
                        style="preamble", heading_text="", heading_paragraph_id=""
                    )
                    out.append(current)
                current.body_blocks.append(
                    DocxTableCell(
                        text=str(raw_block.get("text") or ""),
                        table_cell_id=str(raw_block.get("table_cell_id") or ""),
                        row=int(raw_block.get("row") or 0),
                        col=int(raw_block.get("col") or 0),
                    )
                )

        return out

    @staticmethod
    def _is_section_heading(style: str, text: str) -> bool:
        if style.startswith("SEC "):
            return True
        # Part 1: Normal style with ALL-CAPS department name
        if style == "Normal" and _DEPT_HEADING_RE.match(text):
            return True
        return False


# --- module-level utilities -------------------------------------------------


def parse_bill_heading(text: str) -> dict:
    """Decompose a bill heading per cross-doc-relationships §9.

    Heading shape: `Sec. <N>. <action>; <target>; <fiscal_year>; <modifiers...>`

    Returns a dict with `action`, `target`, `fiscal_year`, `modifiers`, and
    `original` (the input text). Unknown actions fall through to
    `action="other"` with original preserved.
    """
    out: dict = {
        "action": "other",
        "target": None,
        "fiscal_year": None,
        "modifiers": [],
        "original": text,
    }

    # Strip leading "Sec. NN." prefix if present
    body = re.sub(r"^Sec\.\s*\d+\.\s*", "", text, flags=re.IGNORECASE).strip()
    parts = [p.strip().rstrip(".") for p in body.split(";") if p.strip()]
    if not parts:
        return out

    # The first part is the action — match against known prefixes (longest first)
    action_part = parts[0]
    matched_action = None
    for candidate in sorted(_BILL_ACTIONS, key=len, reverse=True):
        if action_part.casefold().startswith(candidate.casefold()):
            matched_action = candidate
            break
    if matched_action:
        out["action"] = matched_action

    if len(parts) >= 2:
        out["target"] = parts[1]

    # Fiscal year may be in any part — scan
    for p in parts:
        m = _FY_RE.search(p)
        if m:
            out["fiscal_year"] = int(m.group(1))
            break

    # Remaining parts (after action, target, FY) are modifiers
    modifiers: list[str] = []
    for p in parts[1:]:
        # Skip the target slot we already consumed
        if p == out["target"]:
            continue
        if _FY_RE.search(p):
            continue
        modifiers.append(p)
    out["modifiers"] = modifiers

    return out


def parse_bill_body(text: str) -> list[str]:
    """Extract A.R.S. section references from bill body text.

    Pattern: `section <N>-<N>[.<N>]` (case-insensitive). Trailing `, A.R.S.`
    is the canonical citation form but isn't required by the regex — bare
    `section X-Y` matches too. Returns deduped refs in first-seen order.
    """
    seen: set[str] = set()
    out: list[str] = []
    for m in _ARS_RE.finditer(text or ""):
        ref = m.group(1)
        if ref not in seen:
            seen.add(ref)
            out.append(ref)
    return out
