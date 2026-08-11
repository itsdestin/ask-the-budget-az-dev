"""A doc_id must be unique per DOCUMENT, not per publisher-per-year.

WHY this file exists: measured on 2026-08-11, make_doc_id's non-JLBC branch
ignored `filename`, so all 78 FY2027 agency submissions minted
'governor-agency-submission-fy2027'. A write is an upsert, so ingesting them
would have left ONE document, with nothing erroring anywhere. This is the same
shape as the JLBC book collision fixed in f85b20a.
"""
from ingest.driver import make_doc_id


def test_agency_submissions_in_one_year_get_distinct_ids():
    a = make_doc_id(publisher="agency", doc_type="agency-submission",
                    fiscal_year=2027, filename="BHA FY27 Budget Submission.pdf")
    b = make_doc_id(publisher="agency", doc_type="agency-submission",
                    fiscal_year=2027, filename="DXA FY27 Budget Submission.pdf")
    assert a != b


def test_bill_summaries_in_one_year_get_distinct_ids():
    intro = make_doc_id(publisher="jlbc", doc_type="budget-bill-summary",
                        fiscal_year=2027,
                        filename="senatehouseintroducedbudgetbills.pdf")
    eng = make_doc_id(publisher="jlbc", doc_type="budget-bill-summary",
                      fiscal_year=2027,
                      filename="houseandsenateplanasengrossed061126.pdf")
    assert intro != eng


def test_one_per_year_types_keep_their_EXACT_existing_ids():
    """The corpus and eval/queries.yaml depend on these strings.

    Verified against the live corpus on 2026-08-11: these are the ids
    agao-afr-fy2024 and governor-governors-budget-fy2027 actually carry.
    """
    assert make_doc_id(
        publisher="agao", doc_type="afr", fiscal_year=2024,
        filename="AFR24 COMBINED with Transmittal Letter.pdf",
    ) == "agao-afr-fy2024"
    assert make_doc_id(
        publisher="governor", doc_type="governors-budget", fiscal_year=2027,
        filename="state-agency-detail-fy-2027.pdf",
    ) == "governor-governors-budget-fy2027"


def test_jlbc_book_ids_are_untouched():
    # The family-aware branch is not what this task changes.
    assert make_doc_id(
        publisher="jlbc", doc_type="detailed-list-pdf", fiscal_year=2026,
        filename="508.pdf", family="approps",
    ) == "jlbc-approps-fy2026-508"
    assert make_doc_id(
        publisher="jlbc", doc_type="detailed-list-pdf", fiscal_year=2026,
        filename="508.pdf", family="baseline",
    ) == "jlbc-baseline-fy2026-508"


def test_a_singleton_type_with_no_filename_still_works():
    assert make_doc_id(
        publisher="agao", doc_type="afr", fiscal_year=2024,
    ) == "agao-afr-fy2024"


def test_bill_id_still_wins_for_budget_bills():
    assert make_doc_id(
        publisher="legislature", doc_type="budget-bill", fiscal_year=2026,
        bill_id="sb1735-2025",
    ) == "legislature-budget-bill-fy2026-sb1735-2025"
