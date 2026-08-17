"""Guards on the COMMITTED whole-report link table (spec R11).

These are the checks that run offline. Reachability is network-bound and lives
in scripts/verify_report_formats.py; what is guarded here is the class of
mistake a green download check waves through — a URL that resolves fine and is
the WRONG YEAR.
"""
import re

from store.report_formats import (
    BOOK_FAMILIES,
    YEARLESS_BY_DESIGN,
    load_shipped,
    names_its_year,
)


def test_every_key_is_a_known_family_and_a_four_digit_year():
    # WHY this can never fail as written: `load_shipped()` calls
    # `_parse(..., strict=True)`, which raises ValueError on exactly this
    # shape (an unknown family or a non-four-digit year) before returning --
    # see test_a_malformed_row_in_the_SHIPPED_file_raises_instead_of_being_dropped
    # in test_report_formats_store.py, which pins that raise directly. The
    # real enforcement is `_parse`'s strict mode; this loop is left in place
    # as a readable restatement of that rule for whoever reads this file
    # without also reading report_formats.py, not deleted, because a reader
    # here should not have to take the enforcement on faith.
    for key in load_shipped():
        family, _, year = key.rpartition(":")
        assert family in BOOK_FAMILIES, key
        assert re.fullmatch(r"\d{4}", year), key


def test_every_url_names_its_own_fiscal_year():
    # THE load-bearing guard. Copying a row and forgetting to bump the URL
    # yields a live, downloadable, WRONG report behind a button labelled
    # "Full report" — a false provenance claim no 200 OK can detect.
    for key, formats in load_shipped().items():
        year = int(key.rpartition(":")[2])
        for url in (formats.single_file, formats.linked_toc):
            if url is None or url in YEARLESS_BY_DESIGN:
                continue
            assert names_its_year(url, year), f"{key} points at {url}"


def test_every_url_is_a_jlbc_pdf():
    for key, formats in load_shipped().items():
        for url in (formats.single_file, formats.linked_toc):
            if url is None:
                continue
            assert re.fullmatch(r"https://www\.azjlbc\.gov/\S+\.pdf", url), f"{key} {url}"


def test_every_edition_offers_at_least_one_format():
    # {single_file: null, linked_toc: null} is indistinguishable from having no
    # entry, so such a row is dead weight that reads as coverage.
    #
    # WHY this can never fail as written: `_parse(..., strict=True)` -- what
    # `load_shipped()` calls -- already raises ValueError on a both-null row
    # ("neither format is set, so there is nothing to link") before this
    # function ever sees it. Left in place as a readable restatement of that
    # rule, not deleted; the real guard is `_parse`'s strict mode.
    for key, formats in load_shipped().items():
        assert formats.single_file or formats.linked_toc, key


def test_the_committed_table_still_covers_every_edition_it_did_on_2026_08_16():
    # A floor, deliberately: this file was generated from the shipped
    # TypeScript, and a regex that silently matched fewer rows would look like
    # a clean smaller table rather than a loss. `>=` rather than `==` so that
    # promoting an approved edition into the committed file is a data change,
    # not a data change plus a test edit.
    assert len(load_shipped()) >= 39
