"""GET /api/corpus/documents — the Budget Documents browse page's listing.

Today there is no other way to enumerate the corpus: `/api/search` needs a
query and returns chunks, not documents; `/api/corpus/counts` returns
counts only. The browse-first page auto-loads the whole corpus grouped by
fiscal year, so it needs every document's id, title, publisher, doc_type,
fiscal_year and source URL in one un-gated payload.
"""
from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from app.main import create_app


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    return TestClient(create_app(ingest_worker=None))


def _entry(**over):
    base = {
        "title": "FY 2027 Baseline — AHCCCS",
        "publisher": "jlbc",
        "doc_type": "baseline-per-agency",
        "fiscal_year": 2027,
        "source_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
    }
    base.update(over)
    return base


def test_an_empty_sidecar_lists_no_documents(client):
    """Fresh install: zero rows, not a 500 — the page shows its empty state."""
    body = client.get("/api/corpus/documents").json()

    assert body == {"documents": []}


def test_every_document_is_listed_with_the_fields_the_page_needs(client, tmp_path):
    (tmp_path / "documents.json").write_text(
        json.dumps(
            {
                "jlbc-baseline-fy2027-axs": _entry(),
                "agao-afr-fy2025": _entry(
                    title="FY 2025 Annual Financial Report",
                    publisher="agao",
                    doc_type="afr",
                    fiscal_year=2025,
                    source_url="https://example.gov/afr25.pdf",
                ),
            }
        ),
        encoding="utf-8",
    )

    body = client.get("/api/corpus/documents").json()

    assert body["documents"] == [
        {
            "doc_id": "agao-afr-fy2025",
            "title": "FY 2025 Annual Financial Report",
            "publisher": "agao",
            "doc_type": "afr",
            "fiscal_year": 2025,
            "doc_url": "https://example.gov/afr25.pdf",
        },
        {
            "doc_id": "jlbc-baseline-fy2027-axs",
            "title": "FY 2027 Baseline — AHCCCS",
            "publisher": "jlbc",
            "doc_type": "baseline-per-agency",
            "fiscal_year": 2027,
            "doc_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
        },
    ]


def test_a_missing_title_falls_back_to_the_humanized_doc_id(client, tmp_path):
    """`title_for`'s fallback is what keeps a title-less entry recognisable."""
    (tmp_path / "documents.json").write_text(
        json.dumps({"jlbc-afr-fy2025-sad": _entry(title="")}),
        encoding="utf-8",
    )

    titles = [d["title"] for d in client.get("/api/corpus/documents").json()["documents"]]

    assert titles == ["JLBC AFR FY 2025 SAD"]


def test_a_missing_source_url_lists_null_not_a_dead_link(client, tmp_path):
    """Honesty invariant: the page must be able to tell 'no URL' apart from
    a URL, or it would render links that navigate nowhere."""
    (tmp_path / "documents.json").write_text(
        json.dumps({"doc-a": _entry(source_url=None)}),
        encoding="utf-8",
    )

    (row,) = client.get("/api/corpus/documents").json()["documents"]

    assert row["doc_url"] is None


def test_migration_era_titles_are_kept_not_regated(client, tmp_path):
    """The search page gates sidecar titles on `ingested_at` because it has
    the mockup index as a better source. This listing has no third source:
    re-gating would turn 378 real migration-era titles into doc-id slugs.
    An entry with NO ingested_at must still list its sidecar title."""
    entry = _entry(title="JLBC FY2025 — African-American Affairs, Arizona Commission of")
    assert "ingested_at" not in entry
    (tmp_path / "documents.json").write_text(
        json.dumps({"jlbc-approps-fy2025-aam": entry}),
        encoding="utf-8",
    )

    (row,) = client.get("/api/corpus/documents").json()["documents"]

    assert row["title"] == "JLBC FY2025 — African-American Affairs, Arizona Commission of"


def test_a_corrupt_sidecar_reads_as_empty_rather_than_500ing(client, tmp_path):
    """Same degradation rule as /api/corpus/counts: a page load must never
    500 because a footer-level listing file is broken."""
    (tmp_path / "documents.json").write_text("{not json", encoding="utf-8")

    response = client.get("/api/corpus/documents")

    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_non_dict_entries_are_skipped_not_raised_on(client, tmp_path):
    """A hand-edited sidecar can hold anything."""
    (tmp_path / "documents.json").write_text(
        json.dumps({"doc-a": _entry(), "doc-b": "oops"}),
        encoding="utf-8",
    )

    ids = [d["doc_id"] for d in client.get("/api/corpus/documents").json()["documents"]]

    assert ids == ["doc-a"]


def test_the_route_is_not_admin_gated(client, monkeypatch):
    """Every analyst's browse page calls this on load."""
    monkeypatch.setenv("JLBC_USER", "some-analyst")

    assert client.get("/api/corpus/documents").status_code == 200
