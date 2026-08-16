"""The registry is the one place document types are described.

These tests pin the two properties that make the registry worth having:
it reproduces today's routing EXACTLY (so the Task 2 repoint cannot change
extraction), and every row an analyst can see tells them what to do.
"""
import pytest

from ingest import book_discovery, doc_types


def test_registry_reproduces_every_shipped_extractor_route():
    """The safety net for the whole refactor.

    Task 2 repoints the dispatcher at this file. Any row that disagrees with
    the shipped EXTRACTOR_REGISTRY would silently change how a document is
    extracted -- and a differently-extracted document produces different chunk
    text, different chunk_ids, and broken eval ground truth.
    """
    from ingest.dispatcher import EXTRACTOR_REGISTRY

    names = {
        "MinerUExtractor": "mineru",
        "OpenDataLoaderExtractor": "opendataloader",
        "PythonDocxExtractor": "python-docx",
    }
    for (doc_type, fmt), cls in EXTRACTOR_REGISTRY.items():
        row = doc_types.get(doc_type)
        assert row is not None, f"{doc_type} missing from data/document-types.yaml"
        assert f".{fmt}" in row.formats, f"{doc_type} does not accept .{fmt}"
        assert row.extractors[f".{fmt}"] == names[cls.__name__]


def test_the_registry_and_the_dispatcher_are_in_full_parity():
    # WHY changed (Plan A Task 4): this test pinned the Task-1-era
    # intermediate state, where the registry knew agency-submission and
    # budget-bill-summary but ingest/dispatcher.py's _NOT_YET_WIRED holdout
    # kept them out of EXTRACTOR_REGISTRY -- so `registered - shipped` was
    # exactly those two keys. Task 4 deletes that holdout and wires both
    # types through, which makes the two sets equal. Asserting full parity
    # here is the same anti-drift property this file always cared about,
    # now that there is no longer a deliberately-unwired keys.
    from ingest.dispatcher import EXTRACTOR_REGISTRY

    shipped = {dt for dt, _fmt in EXTRACTOR_REGISTRY}
    registered = {t.key for t in doc_types.all_types()}
    assert registered == shipped


def test_exactly_six_upload_rows_in_a_stable_order():
    rows = [t.key for t in doc_types.upload_rows()]
    assert rows == [
        "baseline-book",
        "approps-report",
        "afr",
        "governors-budget",
        "agency-submission",
        "budget-bill-summary",
    ]


def test_book_rows_redirect_and_carry_no_upload_instruction():
    # T1/S25: offering "which file?" for a book at all is the bug. An edition
    # is ~110 per-agency documents; the single-file PDF would land as ONE.
    for key in ("baseline-book", "approps-report"):
        row = doc_types.get(key)
        assert row.redirect is not None
        assert row.redirect["action"] == "add-jlbc-book"
        assert not row.which_file


def test_every_book_row_names_the_family_it_is():
    # The upload page's book cards fetch one shared "what is JLBC missing?"
    # answer covering BOTH families and each shows only its own rows, keyed
    # on this field. It is deliberately NOT derivable client-side:
    # webapp/src/pages/Upload.tsx is under a spec forbidding it to contain
    # any doc_type slug, because a second hand-typed copy of this list has
    # shipped bugs twice.
    #
    # 🔴 A missing or misspelt family FAILS SILENTLY AND CONFIDENTLY, which
    # is why this is pinned rather than left to the UI. Nothing errors: the
    # filter matches nothing, so the card renders "Every published Baseline
    # Book is already here" — the exact sentence it would show if the corpus
    # really were complete. An analyst is told there is nothing to add on a
    # page whose only job is telling them what is missing.
    families = {
        key: doc_types.get(key).redirect["family"]
        for key in ("baseline-book", "approps-report")
    }
    # The vocabulary is ingest/book_discovery's, not a new one — these are the
    # values `plan_edition(family, ...)` and `/api/books/ingest` accept.
    assert set(families.values()) == set(book_discovery.FAMILIES)
    # And the two rows must not name the SAME family: that reads as valid
    # everywhere above, and simply shows one family's gap on both cards.
    assert len(set(families.values())) == 2


def test_every_non_redirect_row_tells_the_analyst_which_file_to_get():
    # A dropdown entry with no guidance is what this plan exists to delete.
    for row in doc_types.upload_rows():
        if row.redirect is None:
            assert row.which_file.strip(), f"{row.key} has no which_file"
            assert row.where_published.strip(), f"{row.key} has no where_published"


def test_only_the_bill_summary_asks_for_a_stage():
    staged = {t.key for t in doc_types.all_types() if t.stage_field}
    assert staged == {"budget-bill-summary"}


def test_multi_per_year_types_are_marked_as_such():
    # Drives doc_id identity in Task 3. Getting this wrong silently collapses
    # every document of that type in a fiscal year into one.
    assert doc_types.get("afr").one_per_year is True
    assert doc_types.get("governors-budget").one_per_year is True
    assert doc_types.get("agency-submission").one_per_year is False
    assert doc_types.get("budget-bill-summary").one_per_year is False


def test_a_malformed_registry_raises_rather_than_defaulting(tmp_path):
    # Unlike settings.json, this file is shipped and version-controlled.
    # Silently forgetting how to route documents is worse than not starting.
    bad = tmp_path / "document-types.yaml"
    bad.write_text("types: [ this is not: valid: yaml", encoding="utf-8")
    doc_types.reset_cache()
    with pytest.raises(Exception):
        doc_types.all_types(path=bad)
    doc_types.reset_cache()


def test_an_edited_registry_is_picked_up_without_a_restart(tmp_path):
    path = tmp_path / "document-types.yaml"
    path.write_text(
        "types:\n"
        "  - key: afr\n"
        "    label: Annual Financial Report\n"
        "    group: Auditor General\n"
        "    order: 30\n"
        "    formats: ['.pdf']\n"
        "    extractors: {'.pdf': opendataloader}\n"
        "    publisher: agao\n"
        "    one_per_year: true\n"
        "    upload_row: true\n"
        "    where_published: x\n"
        "    which_file: y\n",
        encoding="utf-8",
    )
    doc_types.reset_cache()
    assert doc_types.get("afr", path=path).label == "Annual Financial Report"
    path.write_text(
        path.read_text(encoding="utf-8").replace(
            "label: Annual Financial Report", "label: Renamed"
        ),
        encoding="utf-8",
    )
    import os, time
    # Force a distinct mtime -- a same-tick rewrite is the one case the
    # (path, mtime, size) stamp cannot see, and the sizes here differ anyway.
    os.utime(path, (time.time() + 1, time.time() + 1))
    assert doc_types.get("afr", path=path).label == "Renamed"
    doc_types.reset_cache()
