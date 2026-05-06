"""Tests for primer/glossary.py — Gov SAD glossary parser + renderer."""
from __future__ import annotations

from pathlib import Path

import pytest

from chunking.readers.odl_reader import ODLReader
from primer.glossary import (
    Acronym,
    BudgetTerm,
    append_glossary_to_context,
    parse_acronyms,
    parse_budget_terms,
    render_glossary_to_markdown,
)

FIXTURE = Path(__file__).parent / "fixtures" / "odl-gov-glossary-pp626-633.json"


def _load():
    return ODLReader().read(FIXTURE)


# --- parse_budget_terms ----------------------------------------------------


def test_parse_budget_terms_returns_list_of_budget_term():
    terms = parse_budget_terms(_load())
    assert terms
    for t in terms:
        assert isinstance(t, BudgetTerm)


def test_parse_budget_terms_finds_three_entries_in_fixture():
    """Fixture has 3 H2 headings under the 'Budget Terms' H1."""
    terms = parse_budget_terms(_load())
    assert len(terms) == 3
    names = [t.term for t in terms]
    assert names == ["Appropriation", "Baseline", "Lump Sum Appropriation"]


def test_parse_budget_terms_single_paragraph_definition():
    terms = parse_budget_terms(_load())
    appropriation = next(t for t in terms if t.term == "Appropriation")
    assert "legal authorization" in appropriation.definition
    # No second paragraph; definition is exactly the one paragraph.
    assert appropriation.definition.count("\n\n") == 0


def test_parse_budget_terms_concatenates_multi_paragraph_definitions():
    """The 'Baseline' entry has two paragraphs of definition; both must
    appear in the resulting BudgetTerm.definition, separated by a blank
    line so the rendered Markdown shows them as paragraphs."""
    terms = parse_budget_terms(_load())
    baseline = next(t for t in terms if t.term == "Baseline")
    assert "estimate of the State's spending requirements" in baseline.definition
    assert "updated regularly" in baseline.definition
    # Two paragraphs joined by blank-line separator
    assert baseline.definition.count("\n\n") == 1


def test_parse_budget_terms_only_under_budget_terms_heading():
    """Don't pick up H2 headings that live under other top-level sections
    (e.g. Acronyms)."""
    terms = parse_budget_terms(_load())
    names = [t.term for t in terms]
    # Acronym heading should not appear as a budget term
    assert "Acronyms" not in names
    assert "Acronym" not in names


# --- parse_acronyms --------------------------------------------------------


def test_parse_acronyms_returns_list_of_acronym():
    acronyms = parse_acronyms(_load())
    assert acronyms
    for a in acronyms:
        assert isinstance(a, Acronym)


def test_parse_acronyms_finds_three_entries_in_fixture():
    """Fixture has 3 acronym rows + 1 header row in the table."""
    acronyms = parse_acronyms(_load())
    assert len(acronyms) == 3


def test_parse_acronyms_extracts_acronym_and_expansion():
    acronyms = parse_acronyms(_load())
    by_acronym = {a.acronym: a.expansion for a in acronyms}
    assert by_acronym["AHCCCS"] == "Arizona Health Care Cost Containment System"
    assert by_acronym["JLBC"] == "Joint Legislative Budget Committee"
    assert by_acronym["OSPB"] == "Office of Strategic Planning and Budgeting"


def test_parse_acronyms_skips_header_row():
    """A row whose first cell is literally 'Acronym' (case-insensitive) is
    the header — don't emit it as data."""
    acronyms = parse_acronyms(_load())
    names = [a.acronym for a in acronyms]
    assert "Acronym" not in names


def test_parse_acronyms_only_under_acronyms_heading():
    """Don't pick up tables that live under Budget Terms — only the
    acronyms section's table should produce Acronym entries."""
    acronyms = parse_acronyms(_load())
    # The fixture only has one table (in Acronyms); this just asserts no spurious entries.
    assert len(acronyms) == 3


# --- render_glossary_to_markdown -------------------------------------------


def test_render_glossary_emits_section_heading():
    md = render_glossary_to_markdown(parse_budget_terms(_load()), parse_acronyms(_load()))
    assert "## Budget Terms" in md
    assert "## Acronyms" in md


def test_render_glossary_budget_terms_use_bold_term_inline_format():
    """Plan §5.2 step 2: 'Render as Markdown definition list.' GFM doesn't
    support definition lists natively; we render as **Term.** Definition
    pattern, which renders cleanly in any Markdown processor."""
    terms = [
        BudgetTerm(term="Appropriation", definition="A legal authorization."),
    ]
    md = render_glossary_to_markdown(terms, [])
    assert "**Appropriation**" in md
    assert "A legal authorization." in md


def test_render_glossary_multi_paragraph_definitions_preserve_blanks():
    terms = [
        BudgetTerm(term="Baseline", definition="First paragraph.\n\nSecond paragraph."),
    ]
    md = render_glossary_to_markdown(terms, [])
    assert "First paragraph." in md
    assert "Second paragraph." in md
    # Both paragraphs appear as separate paragraphs
    assert "First paragraph.\n\nSecond paragraph." in md or md.count("\n\n") >= 2


def test_render_glossary_acronyms_as_markdown_table():
    acronyms = [
        Acronym(acronym="AHCCCS", expansion="Arizona Health Care Cost Containment System"),
        Acronym(acronym="JLBC", expansion="Joint Legislative Budget Committee"),
    ]
    md = render_glossary_to_markdown([], acronyms)
    assert "| Acronym | Expansion |" in md
    assert "| --- | --- |" in md
    assert "| AHCCCS | Arizona Health Care Cost Containment System |" in md
    assert "| JLBC | Joint Legislative Budget Committee |" in md


def test_render_glossary_includes_both_sections_in_order():
    terms = [BudgetTerm(term="Appropriation", definition="A legal authorization.")]
    acronyms = [Acronym(acronym="JLBC", expansion="Joint Legislative Budget Committee")]
    md = render_glossary_to_markdown(terms, acronyms)
    # Budget Terms section appears before Acronyms section
    assert md.index("## Budget Terms") < md.index("## Acronyms")


# --- append_glossary_to_context --------------------------------------------


def test_append_glossary_writes_divider_then_content(tmp_path):
    context_path = tmp_path / "context.md"
    context_path.write_text("# Existing context.\n\nFirst section.\n", encoding="utf-8")
    terms = [BudgetTerm(term="Baseline", definition="A forecast.")]
    acronyms = [Acronym(acronym="JLBC", expansion="Joint Legislative Budget Committee")]
    append_glossary_to_context(context_path, terms, acronyms)
    final = context_path.read_text(encoding="utf-8")
    assert "# Existing context." in final
    assert "First section." in final
    assert "---" in final  # section divider
    assert "## Budget Terms" in final
    assert "**Baseline**" in final
    assert "## Acronyms" in final
    # Existing content precedes the new content
    assert final.index("First section.") < final.index("## Budget Terms")


def test_append_glossary_creates_file_if_missing(tmp_path):
    context_path = tmp_path / "new-context.md"
    terms = [BudgetTerm(term="A", definition="def")]
    append_glossary_to_context(context_path, terms, [])
    assert context_path.exists()
    assert "**A**" in context_path.read_text(encoding="utf-8")


def test_append_glossary_idempotent_with_marker(tmp_path):
    """Appending twice should not duplicate the glossary — the function
    detects an existing glossary marker and either skips or replaces."""
    context_path = tmp_path / "context.md"
    context_path.write_text("# Top.\n", encoding="utf-8")
    terms = [BudgetTerm(term="A", definition="def")]
    append_glossary_to_context(context_path, terms, [])
    # Append again with different content
    new_terms = [BudgetTerm(term="B", definition="def-2")]
    append_glossary_to_context(context_path, new_terms, [])
    final = context_path.read_text(encoding="utf-8")
    # Only the latest glossary should be present
    assert "**B**" in final
    assert final.count("## Budget Terms") == 1
