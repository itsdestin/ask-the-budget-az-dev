"""Gov SAD glossary parser + Markdown renderer.

The Governor's State Agency Detail PDF carries a two-part glossary on
pp 626-633:
  - Budget Terms — formal definitions, each one a heading followed by
    1-3 paragraphs.
  - Acronyms — two-column table (acronym → expansion).

This module:
  - parses each section out of an `ExtractedDocument` (ODL output)
  - renders both sections as Markdown
  - appends the rendered glossary to data/system-prompt-context.md after
    a section divider, idempotently (re-running replaces the prior
    glossary block, never duplicates it)

Section detection uses outline H1 headings literally named "Budget Terms"
and "Acronyms". If the real PDF surfaces different naming, the constants
below are the place to update.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from chunking.readers.types import (
    ExtractedDocument,
    Heading,
    OutlineNode,
    Paragraph,
    Table,
)

# Section heading text we look for in the outline. ODL with use_struct_tree
# preserves these from the tagged PDF; if the gov-glossary PDF turns out to
# use slightly different wording, expand these tuples (case-insensitive
# substring match in `_find_section_node`).
BUDGET_TERMS_HEADING = "Budget Terms"
ACRONYMS_HEADING = "Acronyms"

# Marker bracketing the glossary block in system-prompt-context.md so
# append_glossary_to_context can replace the prior block on re-run rather
# than duplicating it.
_GLOSSARY_BEGIN = "<!-- glossary:begin -->"
_GLOSSARY_END = "<!-- glossary:end -->"


@dataclass(frozen=True)
class BudgetTerm:
    """One Budget Terms entry: a defined term + its definition.

    `definition` is the concatenated body paragraphs joined by blank-line
    separators, so the rendered Markdown shows them as paragraphs.
    """

    term: str
    definition: str


@dataclass(frozen=True)
class Acronym:
    """One Acronyms-table row."""

    acronym: str
    expansion: str


# --- parsers ---------------------------------------------------------------


def parse_budget_terms(doc: ExtractedDocument) -> list[BudgetTerm]:
    """Walk every H2 child of the 'Budget Terms' outline node and emit
    one BudgetTerm per child. The body paragraphs in each H2 child node
    become the definition (multi-paragraph definitions joined with \\n\\n).
    """
    section = _find_section_node(doc.outline, BUDGET_TERMS_HEADING)
    if section is None:
        return []

    out: list[BudgetTerm] = []
    for child in section.children:
        # Each child is one term entry. Body paragraphs in source order.
        paragraph_texts = [
            block.text.strip()
            for block in child.body_blocks
            if isinstance(block, Paragraph) and block.text.strip()
        ]
        if not paragraph_texts:
            continue
        out.append(
            BudgetTerm(
                term=child.text.strip(),
                definition="\n\n".join(paragraph_texts),
            )
        )
    return out


def parse_acronyms(doc: ExtractedDocument) -> list[Acronym]:
    """Walk the first table under the 'Acronyms' outline node, skip its
    header row, and emit one Acronym per body row."""
    section = _find_section_node(doc.outline, ACRONYMS_HEADING)
    if section is None:
        return []

    table = _first_table_in_section(section)
    if table is None:
        return []

    out: list[Acronym] = []
    for row in table.rows:
        if len(row.cells) < 2:
            continue
        first = row.cells[0].text.strip()
        if not first:
            continue
        # Header detection: first cell is literally "Acronym" (case-insensitive).
        if first.casefold() == "acronym":
            continue
        out.append(
            Acronym(acronym=first, expansion=row.cells[1].text.strip())
        )
    return out


# --- renderer --------------------------------------------------------------


def render_glossary_to_markdown(
    terms: list[BudgetTerm],
    acronyms: list[Acronym],
) -> str:
    """Render both sections as Markdown.

    Budget Terms use the **Term.** Definition inline pattern (GFM-safe;
    definition lists aren't standard GFM). Acronyms render as a Markdown
    table.
    """
    pieces: list[str] = []

    if terms:
        pieces.append("## Budget Terms")
        for t in terms:
            # `**Term**: Definition` — period kept outside the bold so the
            # bold is exactly the term, which is what consumers grep for.
            # Continuation paragraphs are 2-space-indented so they render
            # as part of the same logical entry rather than orphan prose.
            paragraphs = t.definition.split("\n\n")
            first = f"**{t.term}**: {paragraphs[0]}"
            continuations = [f"  {p}" for p in paragraphs[1:]]
            pieces.append("\n\n".join([first, *continuations]))

    if acronyms:
        pieces.append("## Acronyms")
        # Markdown tables must have rows on consecutive lines (no blank
        # lines between them), so the whole table is one `pieces` entry.
        rows = ["| Acronym | Expansion |", "| --- | --- |"]
        for a in acronyms:
            rows.append(
                f"| {_escape_pipes(a.acronym)} | {_escape_pipes(a.expansion)} |"
            )
        pieces.append("\n".join(rows))

    return "\n\n".join(pieces)


def append_glossary_to_context(
    context_path: Path | str,
    terms: list[BudgetTerm],
    acronyms: list[Acronym],
) -> None:
    """Append (or replace) the glossary block in `context_path`.

    Idempotent: if the file already contains a glossary block (delimited
    by HTML-comment markers), it's replaced; otherwise the block is
    appended after the existing content with a Markdown section divider.

    Creates the file if it doesn't exist.
    """
    context_path = Path(context_path)
    context_path.parent.mkdir(parents=True, exist_ok=True)

    glossary_md = render_glossary_to_markdown(terms, acronyms)
    block = f"{_GLOSSARY_BEGIN}\n\n---\n\n{glossary_md}\n\n{_GLOSSARY_END}\n"

    if context_path.exists():
        existing = context_path.read_text(encoding="utf-8")
    else:
        existing = ""

    # Replace existing block if present
    begin_idx = existing.find(_GLOSSARY_BEGIN)
    if begin_idx != -1:
        end_idx = existing.find(_GLOSSARY_END, begin_idx)
        if end_idx != -1:
            end_idx += len(_GLOSSARY_END)
            # Trim any trailing newline that was part of the prior block
            while end_idx < len(existing) and existing[end_idx] == "\n":
                end_idx += 1
            new_content = existing[:begin_idx] + block + existing[end_idx:]
            context_path.write_text(new_content, encoding="utf-8")
            return

    # No existing block — append after existing content. Ensure a blank
    # line separates the old content from the divider.
    if existing and not existing.endswith("\n"):
        existing += "\n"
    if existing and not existing.endswith("\n\n"):
        existing += "\n"
    context_path.write_text(existing + block, encoding="utf-8")


# --- helpers ---------------------------------------------------------------


def _find_section_node(outline: list[OutlineNode], heading_text: str) -> OutlineNode | None:
    """Search the outline tree for a node whose text matches `heading_text`
    case-insensitively. Returns the first match or None."""
    target = heading_text.casefold().strip()

    def walk(node: OutlineNode) -> OutlineNode | None:
        if node.text.casefold().strip() == target:
            return node
        for child in node.children:
            found = walk(child)
            if found is not None:
                return found
        return None

    for root in outline:
        found = walk(root)
        if found is not None:
            return found
    return None


def _first_table_in_section(node: OutlineNode) -> Table | None:
    """Return the first Table block inside `node.body_blocks`, recursing
    into descendant section nodes if not found at this level."""
    for block in node.body_blocks:
        if isinstance(block, Table):
            return block
    for child in node.children:
        found = _first_table_in_section(child)
        if found is not None:
            return found
    return None


def _escape_pipes(s: str) -> str:
    return s.replace("|", r"\|")
