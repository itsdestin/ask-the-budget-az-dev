"""ONE title ladder for every surface (spec I12).

Three ladders exist today and they disagree:

| rung | search results | browse listing | AI Mode |
|---|---|---|---|
| 1 | website index title | never consulted | never consulted |
| 2 | sidecar, GATED on ingested_at | sidecar, ungated | sidecar, ungated |
| 3 | humanised doc_id | humanised doc_id | humanised doc_id |

The website index is a HARVEST of somebody else's page and is the supplier
that produced 218 wrong names, so it is demoted below the corpus's own
record. The `ingested_at` gate is dropped with it: it existed only to keep
migration-era titles from beating the index, and measured against the live
corpus it would swap 375 real agency names ("JLBC FY2025 — African-American
Affairs, Arizona Commission of") for doc-id slugs.
"""
from __future__ import annotations

import json

import pytest

from store.documents import reset_documents_cache
from identity.resolve import resolve_title, resolve_titles


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    reset_documents_cache()
    yield tmp_path
    reset_documents_cache()


def _write(data_dir, payload):
    (data_dir / "documents.json").write_text(json.dumps(payload), encoding="utf-8")
    reset_documents_cache()


def test_the_sidecar_title_wins(data_dir):
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "ingested_at": "2026-08-16T00:00:00+00:00",
    }})
    assert resolve_title("jlbc-approps-fy2005-bar") == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_a_migration_era_title_with_no_ingested_at_is_STILL_used(data_dir):
    """375 live documents lack `ingested_at` and most of their titles are
    fine. The old search-page gate would replace this with a doc-id slug."""
    _write(data_dir, {"jlbc-approps-fy2025-aam": {
        "title": "JLBC FY2025 — African-American Affairs, Arizona Commission of",
    }})
    assert resolve_title("jlbc-approps-fy2025-aam") == (
        "JLBC FY2025 — African-American Affairs, Arizona Commission of"
    )


def test_a_missing_document_falls_back_to_the_humanised_doc_id(data_dir):
    """`jlbc` is a registered acronym in `store.documents._SLUG_ACRONYMS`, so
    the humanizer renders it "JLBC", not "Jlbc" — verified against the real
    (unmodifiable) implementation rather than transcribed from the brief."""
    _write(data_dir, {})
    assert resolve_title("jlbc-approps-fy2005-bar") == "JLBC Approps FY 2005 Bar"


def test_a_blank_title_falls_back_rather_than_rendering_empty(data_dir):
    _write(data_dir, {"jlbc-approps-fy2005-bar": {"title": "   "}})
    assert resolve_title("jlbc-approps-fy2005-bar") == "JLBC Approps FY 2005 Bar"


def test_resolve_titles_reads_the_sidecar_ONCE_and_agrees_with_the_singular(data_dir, monkeypatch):
    """Twenty search rows must not re-parse and re-deepcopy the whole map."""
    _write(data_dir, {
        "a": {"title": "Alpha — FY 2026 Baseline"},
        "b": {"title": "Beta — FY 2026 Baseline"},
    })
    import store.documents as docs_mod

    calls = {"n": 0}
    real = docs_mod._load_cached

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(docs_mod, "_load_cached", counting)
    out = resolve_titles(["a", "b"])
    assert out == {"a": "Alpha — FY 2026 Baseline", "b": "Beta — FY 2026 Baseline"}
    assert calls["n"] == 1
    assert out["a"] == resolve_title("a")


def test_all_three_surfaces_return_the_SAME_title(data_dir):
    """Gate G-I4. Its absence is audit Finding 7.

    Drives the three real call sites, not three copies of the ladder:
    the search provider's `_info`, the browse route's title expression,
    and the harness's `_doc_titles`.
    """
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "source_url": "https://www.azjlbc.gov/05app/bar.pdf",
    }})

    from app.search_provider import LanceSearchProvider
    from store.documents import title_for
    from harness import tools as harness_tools

    provider = LanceSearchProvider.__new__(LanceSearchProvider)
    provider._doc_info = None
    provider._doc_info_sig = None
    search_title = provider._info("jlbc-approps-fy2005-bar")["title"]

    browse_title = title_for("jlbc-approps-fy2005-bar")
    ai_title = harness_tools._doc_titles({"jlbc-approps-fy2005-bar"})[
        "jlbc-approps-fy2005-bar"
    ]

    assert search_title == browse_title == ai_title == (
        "Board of Barbers — FY 2005 Appropriations Report"
    )


def test_the_website_harvest_no_longer_overrides_a_repaired_title(data_dir, monkeypatch):
    """The regression this whole unit exists to prevent.

    The harvest says "Agriculture" for `05app/bar.pdf`. Before this change
    it won unconditionally on the search page, so repairing the corpus
    changed nothing an analyst saw while the audit script reported zero
    errors.
    """
    _write(data_dir, {"jlbc-approps-fy2005-bar": {
        "title": "Board of Barbers — FY 2005 Appropriations Report",
        "source_url": "https://www.azjlbc.gov/05app/bar.pdf",
    }})
    from app.search_provider import LanceSearchProvider

    monkeypatch.setattr(
        LanceSearchProvider,
        "_load_mockup_index",
        staticmethod(lambda: {
            "https://www.azjlbc.gov/05app/bar.pdf": {
                "url": "https://www.azjlbc.gov/05app/bar.pdf",
                "title": "Agriculture, Arizona Department of — FY 2005 Appropriations Report",
                "category": "Agency Budget Detail",
                "doc_type": "Appropriations Report",
                "fiscal_year": 2005,
            }
        }),
    )
    provider = LanceSearchProvider.__new__(LanceSearchProvider)
    provider._doc_info = None
    provider._doc_info_sig = None
    info = provider._info("jlbc-approps-fy2005-bar")

    assert info["title"] == "Board of Barbers — FY 2005 Appropriations Report"
    # The meta line still comes from the harvest — it is the only source of
    # the category/doc-type sentence and it was never wrong.
    assert info["meta"] == "Agency Budget Detail · Appropriations Report · FY 2005"
