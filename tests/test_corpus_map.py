"""Spec N1: the corpus map the model reads. Built ONLY from injected
document dicts — never the real sidecar (CLAUDE.md test convention)."""
import pytest

from harness.corpus_map import build_corpus_map


def _doc(doc_type, fy, publisher="jlbc", source_url=None):
    return {
        "doc_type": doc_type,
        "fiscal_year": fy,
        "publisher": publisher,
        "source_url": source_url,
    }


def test_contiguous_years_render_as_a_range():
    docs = {f"afr-{y}": _doc("afr", y, publisher="agao") for y in (2021, 2022, 2023, 2024, 2025)}
    out = build_corpus_map("budget", documents=docs)
    assert "AGAO — Annual Financial Report" in out
    assert "FY2021–FY2025" in out
    assert "| 5 |" in out  # document count column


def test_small_gaps_are_named():
    years = [2012, 2014, 2015, 2016, 2017]
    docs = {f"b-{y}": _doc("baseline-per-agency", y) for y in years}
    out = build_corpus_map("budget", documents=docs)
    assert "missing FY2013" in out


def test_sparse_coverage_summarizes_instead_of_listing():
    years = [2005, 2008, 2011, 2014, 2017, 2020, 2023, 2026]  # 8 of 22
    docs = {f"a-{y}": _doc("approps-per-agency", y) for y in years}
    out = build_corpus_map("budget", documents=docs)
    assert "8 of 22 years" in out


def test_single_year_reads_only():
    docs = {"bill": _doc("budget-bill", 2026, publisher="legislature")}
    out = build_corpus_map("budget", documents=docs)
    assert "FY2026 only" in out


def test_sections_grouped_by_source_url_family_not_doc_id():
    # The recorded wrong-doc_id case: baseline section published under
    # 22baseline/ — must count toward Baseline, whatever its id implies.
    docs = {
        "jlbc-approps-fy2022-497": _doc(
            "detailed-list-pdf", 2022, source_url="https://azjlbc.gov/22baseline/497.pdf"
        ),
        "s1": _doc("s-pdf", 2027, source_url="https://azjlbc.gov/27baseline/s1.pdf"),
        "bd1": _doc("bd-pdf", 2026, source_url="https://azjlbc.gov/26ar/bd1.pdf"),
    }
    out = build_corpus_map("budget", documents=docs)
    assert "Baseline (book sections)" in out
    assert "Appropriations Report (book sections)" in out
    # The wrong-id doc landed in the Baseline sections row (count 2).
    baseline_row = next(
        line for line in out.splitlines() if "Baseline (book sections)" in line
    )
    assert "| 2 |" in baseline_row


def test_unclassifiable_section_is_named_not_dropped():
    """A section whose URL the family rule cannot read still appears. A
    document that VANISHES from the map is the harmful direction: the
    guidance line then tells the model to deny material the corpus holds."""
    docs = {"weird": _doc("topic-pdf", 2024, source_url="https://example.test/x.pdf")}
    out = build_corpus_map("budget", documents=docs)
    assert "unclassified" in out
    assert "| 1 |" in out


def test_budget_map_excludes_fiscal_notes_and_vice_versa():
    docs = {
        "note": _doc("fiscal-note", 2020, publisher="legislature"),
        "afr": _doc("afr", 2024, publisher="agao"),
    }
    budget = build_corpus_map("budget", documents=docs)
    notes = build_corpus_map("fiscal_notes", documents=docs)
    assert "Fiscal note" not in budget
    assert "FY2020" not in budget
    assert "Annual Financial Report" not in notes
    assert "FY2020" in notes


def test_unknown_doc_type_appears_raw_rather_than_vanishing():
    docs = {"x": _doc("agency-budget-request", 2027, publisher="governor")}
    out = build_corpus_map("budget", documents=docs)
    assert "agency-budget-request" in out


def test_empty_documents_returns_none():
    assert build_corpus_map("budget", documents={}) is None


def test_corpus_with_no_matching_documents_returns_none():
    """A budget-only corpus asked for its fiscal-note map has nothing to
    say — None, so the caller renders the prompt's fallback sentence
    rather than a headings-only table that reads as 'the corpus is empty'."""
    docs = {"afr": _doc("afr", 2024, publisher="agao")}
    assert build_corpus_map("fiscal_notes", documents=docs) is None


def test_yearless_documents_say_so_rather_than_guessing():
    docs = {"x": _doc("afr", None, publisher="agao")}
    out = build_corpus_map("budget", documents=docs)
    assert "year unknown" in out


def test_guidance_line_is_present():
    docs = {"afr": _doc("afr", 2024, publisher="agao")}
    out = build_corpus_map("budget", documents=docs)
    assert "do not search repeatedly" in out


def test_unknown_corpus_raises():
    with pytest.raises(ValueError):
        build_corpus_map("nope", documents={})


def test_table_names_accepted():
    docs = {"afr": _doc("afr", 2024, publisher="agao")}
    assert build_corpus_map("budget_chunks", documents=docs) == build_corpus_map(
        "budget", documents=docs
    )


def test_deterministic_output():
    docs = {f"d{i}": _doc("afr", 2020 + i, publisher="agao") for i in range(5)}
    assert build_corpus_map("budget", documents=docs) == build_corpus_map(
        "budget", documents=dict(reversed(list(docs.items())))
    )


def test_no_pipe_character_can_break_the_table():
    """A publisher or doc_type carrying a `|` would split the markdown row
    and silently shift every later column — the count would read as the
    year range. Raw fallback labels are built from corpus data, so this is
    reachable without a code change."""
    docs = {"x": _doc("odd|type", 2026, publisher="who|ever")}
    out = build_corpus_map("budget", documents=docs)
    row = next(line for line in out.splitlines() if "odd" in line)
    assert row.count("|") == 4  # leading, two separators, trailing
