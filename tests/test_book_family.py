"""The family rule in its store/ home (spec N1 / book-sections B1-B2).

The one case that justifies source_url over doc_id: a section whose
doc_id says approps but whose published URL says baseline. 21 such
documents exist (the make_doc_id collision class); jlbc-approps-fy2022-497
is the recorded example.
"""
from store.book_family import section_of


def test_wrong_doc_id_section_resolves_by_url_not_id():
    # doc_id jlbc-approps-fy2022-497, but JLBC published it under 22baseline/
    assert section_of("detailed-list-pdf", "https://azjlbc.gov/22baseline/497.pdf") == "Baseline"


def test_approps_directories_both_spellings():
    assert section_of("s-pdf", "https://azjlbc.gov/25ar/bd10.pdf") == "Appropriations Report"
    assert section_of("s-pdf", "https://azjlbc.gov/05app/bd10.pdf") == "Appropriations Report"


def test_old_baseline_book_spelling():
    assert section_of("bd-pdf", "https://azjlbc.gov/12book1/x.pdf") == "Baseline"


def test_non_section_doc_types_are_left_alone():
    assert section_of("afr", "https://azjlbc.gov/22baseline/497.pdf") is None
    assert section_of("baseline-per-agency", "https://azjlbc.gov/22baseline/dcs.pdf") is None


def test_missing_url_returns_none():
    assert section_of("s-pdf", None) is None
    assert section_of("s-pdf", "") is None


def test_app_shim_still_exports_the_same_function():
    from app.book_sections import section_of as app_section_of
    from store.book_family import section_of as store_section_of

    assert app_section_of is store_section_of
