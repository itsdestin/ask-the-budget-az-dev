"""The parent-book derivation for JLBC book sections (spec B1-B2)."""
import pytest

from app.book_sections import SECTION_DOC_TYPES, section_of


def test_the_five_section_types_are_exactly_these():
    assert SECTION_DOC_TYPES == frozenset(
        {"detailed-list-pdf", "s-pdf", "bd-pdf", "bh-pdf", "topic-pdf"}
    )


@pytest.mark.parametrize(
    "url,expected",
    [
        ("https://www.azjlbc.gov/22baseline/473.pdf", "Baseline"),
        ("https://www.azjlbc.gov/12book1/s1.pdf", "Baseline"),
        ("https://www.azjlbc.gov/25ar/apprpttoc.pdf", "Appropriations Report"),
        ("https://www.azjlbc.gov/05app/bd10.pdf", "Appropriations Report"),
    ],
)
def test_the_book_directory_in_the_source_url_names_the_parent(url, expected):
    assert section_of("s-pdf", url) == expected


def test_a_document_that_is_not_a_section_is_never_folded():
    assert section_of("approps-per-agency", "https://www.azjlbc.gov/25ar/adc.pdf") is None
    assert section_of("afr", "https://gao.az.gov/afr.pdf") is None
    assert section_of(None, "https://www.azjlbc.gov/25ar/x.pdf") is None


def test_an_unreadable_url_folds_nothing_rather_than_guessing():
    # familyOf's contract (spec B8): a document we cannot place still renders
    # under its own doc_type rather than being dropped or mis-filed.
    assert section_of("s-pdf", None) is None
    assert section_of("s-pdf", "https://example.org/whatever.pdf") is None


# The 21 documents whose doc_id says approps and whose source_url says
# baseline -- the make_doc_id family collisions STATUS.md records. A
# doc_id-based implementation passes every other test in this file and fails
# these, which is exactly why they are named individually (spec B2).
COLLISIONS = [
    ("jlbc-approps-fy2022-473", "https://www.azjlbc.gov/22baseline/473.pdf"),
    ("jlbc-approps-fy2022-497", "https://www.azjlbc.gov/22baseline/497.pdf"),
    ("jlbc-approps-fy2023-467", "https://www.azjlbc.gov/23baseline/467.pdf"),
    ("jlbc-approps-fy2024-495", "https://www.azjlbc.gov/24baseline/495.pdf"),
    ("jlbc-approps-fy2025-514", "https://www.azjlbc.gov/25baseline/514.pdf"),
    ("jlbc-approps-fy2026-487", "https://www.azjlbc.gov/26baseline/487.pdf"),
    ("jlbc-approps-fy2027-502", "https://www.azjlbc.gov/27baseline/502.pdf"),
    ("jlbc-approps-fy2027-522", "https://www.azjlbc.gov/27baseline/522.pdf"),
]


@pytest.mark.parametrize("doc_id,url", COLLISIONS)
def test_a_mis_minted_doc_id_does_not_decide_the_parent(doc_id, url):
    assert doc_id.startswith("jlbc-approps-")
    assert section_of("detailed-list-pdf", url) == "Baseline"
