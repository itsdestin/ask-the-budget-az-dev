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


@pytest.fixture(autouse=True)
def budget_corpus(tmp_path, monkeypatch):
    """Stand in for the `budget_chunks` table's doc_id column.

    The route reads corpus membership from the chunk table rather than from
    the sidecar, because the sidecar cannot tell the two corpora apart (see
    `app.routes.corpus.budget_doc_ids`). Tests may not open a real LanceDB —
    CLAUDE.md's testing conventions — so the scan is stubbed here.

    DEFAULT: every doc_id in the sidecar is a budget document, which is the
    world every test below assumed before the corpus filter existed. A test
    that cares about the filter calls the yielded setter with an explicit
    list; `test_fiscal_note_documents_are_not_listed` is the one that does.
    """
    override: list[list[str] | None] = [None]

    def fake_scan(self, name, columns, **_kw):
        assert name == "budget_chunks", f"unexpected table {name!r}"
        assert columns == ["doc_id"], "the listing only ever needs doc_id"
        if override[0] is not None:
            return [{"doc_id": d} for d in override[0]]
        # Mirror the sidecar: read it the same way the route's own reader
        # does, so the default really is "everything is a budget document"
        # even for the corrupt/absent-file tests (which get []).
        path = tmp_path / "documents.json"
        try:
            return [{"doc_id": d} for d in json.loads(path.read_text(encoding="utf-8"))]
        except Exception:  # noqa: BLE001 — absent or corrupt, same as the route
            return []

    monkeypatch.setattr("store.chunk_store.ChunkStore.scan", fake_scan)
    # __init__ opens the LanceDB root; nothing here needs a real one.
    monkeypatch.setattr("store.chunk_store.ChunkStore.__init__", lambda self, **_kw: None)

    def set_budget_docs(doc_ids):
        override[0] = list(doc_ids)

    yield set_budget_docs


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


def _write(tmp_path, docs):
    """Write `docs` as the sidecar. Small helper so the terms tests below
    match the brief's shape; every other test here writes documents.json
    inline instead."""
    (tmp_path / "documents.json").write_text(json.dumps(docs), encoding="utf-8")


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

    # `terms` values below are real: "afr" and "axs" are live catalog/shorthand
    # entries (app/search_terms.py), not fixture-only strings — computed with
    # `app.search_terms.search_terms(doc_id, doc_type, fiscal_year)` against
    # this checkout and pasted here, same as every other field in this table.
    assert body["documents"] == [
        {
            "doc_id": "agao-afr-fy2025",
            "title": "FY 2025 Annual Financial Report",
            "publisher": "agao",
            "doc_type": "afr",
            "fiscal_year": 2025,
            "doc_url": "https://example.gov/afr25.pdf",
            "section_of": None,
            "terms": ["25afr", "afr"],
        },
        {
            "doc_id": "jlbc-baseline-fy2027-axs",
            "title": "FY 2027 Baseline — AHCCCS",
            "publisher": "jlbc",
            "doc_type": "baseline-per-agency",
            "fiscal_year": 2027,
            "doc_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
            "section_of": None,
            "terms": ["27baseline", "27br", "axs", "baseline", "br"],
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


def test_fiscal_note_documents_are_not_listed(client, tmp_path, budget_corpus):
    """documents.json is ONE sidecar for BOTH corpora.

    `ingest/lance_writer.py::_merge_document_entry` writes the same file for a
    Baseline book and for a fiscal note (worker.py's single `write_doc` call
    serves both tables), and the record it writes has no `corpus` field. So the
    only thing that distinguishes them is which chunk table holds their chunks
    — which is what the route now reads. Without this filter the Budget
    Documents page lists fiscal notes.
    """
    (tmp_path / "documents.json").write_text(
        json.dumps(
            {
                "jlbc-baseline-fy2027-axs": _entry(),
                "jlbc-fiscal-note-fy2026-hb2001": _entry(
                    title="FY 2026 Fiscal Note — HB 2001",
                    doc_type="fiscal-note",
                    fiscal_year=2026,
                ),
            }
        ),
        encoding="utf-8",
    )
    # Only the Baseline page has chunks in budget_chunks; the note's chunks
    # live in fiscal_note_chunks, which this listing never reads.
    budget_corpus(["jlbc-baseline-fy2027-axs"])

    ids = [d["doc_id"] for d in client.get("/api/corpus/documents").json()["documents"]]

    assert ids == ["jlbc-baseline-fy2027-axs"]


def test_an_unreadable_chunk_table_lists_nothing_rather_than_leaking(client, tmp_path):
    """When corpus membership can't be read, the honest answer is "nothing to
    show" — the same posture `chunk_counts` documents for the identical
    question, with `app/health.py` as the thing that says whether the corpus is
    empty or broken. Listing the raw sidecar instead would put fiscal notes on
    the budget page precisely when the system is least able to notice.
    """
    (tmp_path / "documents.json").write_text(
        json.dumps({"jlbc-baseline-fy2027-axs": _entry()}), encoding="utf-8"
    )

    from app.routes import corpus as corpus_route

    def boom(self, name, columns, **_kw):
        raise RuntimeError("LanceDB unavailable")

    import store.chunk_store

    original = store.chunk_store.ChunkStore.scan
    store.chunk_store.ChunkStore.scan = boom
    try:
        assert corpus_route.budget_doc_ids() == set()
        response = client.get("/api/corpus/documents")
    finally:
        store.chunk_store.ChunkStore.scan = original

    assert response.status_code == 200
    assert response.json() == {"documents": []}


def test_the_listing_carries_each_documents_search_terms(client, tmp_path):
    _write(tmp_path, {"jlbc-approps-fy2026-ema": _entry(doc_type="approps-per-agency",
                                                        fiscal_year=2026)})
    row = client.get("/api/corpus/documents").json()["documents"][0]
    # The filter box matches these by exact token equality; see
    # app/search_terms.py for where each comes from.
    assert "ema" in row["terms"]    # JLBC URL slug
    assert "dema" in row["terms"]   # reviewed alias
    assert "26ar" in row["terms"]   # JLBC shorthand


def test_every_row_has_a_terms_list_even_when_empty(client, tmp_path):
    # The client types `terms` as required, so the key must always be present —
    # a raw-slug doc type with an unknown agency has nothing to contribute.
    _write(tmp_path, {"jlbc-s-fy2027-01": _entry(doc_type="s-pdf", fiscal_year=2027)})
    row = client.get("/api/corpus/documents").json()["documents"][0]
    assert row["terms"] == []


def test_a_wrong_typed_fiscal_year_lists_with_no_terms_not_a_500(client, tmp_path):
    """Reproduced against the pre-fix route: `fiscal_year="2027"` (a string,
    plausible from a hand-edited sidecar) raises TypeError in
    `_type_terms`'s `fiscal_year >= _SHORTHAND_MIN_YEAR` — a str/int
    comparison — and 500s the WHOLE listing, not just this row. The row
    itself is structurally valid (a dict, matching this fixture's other
    fields), so the existing `isinstance(meta, dict)` guard never sees it;
    this is a new, narrower failure mode the dict guard doesn't cover.

    A neighbouring well-formed row (`doc-b`) must still carry its real terms
    — this is a per-row degrade, not a whole-request one.
    """
    _write(
        tmp_path,
        {
            "doc-a": _entry(doc_type="baseline-per-agency", fiscal_year="2027"),
            "doc-b": _entry(doc_type="afr", fiscal_year=2025),
        },
    )

    response = client.get("/api/corpus/documents")

    assert response.status_code == 200
    rows = {r["doc_id"]: r for r in response.json()["documents"]}
    assert rows["doc-a"]["terms"] == []
    assert rows["doc-b"]["terms"] == ["25afr", "afr"]


def test_a_bool_or_out_of_range_fiscal_year_lists_with_no_terms(client, tmp_path):
    """2026-08-11 review finding 6: `isinstance(fiscal_year, int)` alone
    admits `bool` (an int subclass) and any out-of-range int, e.g. a
    five-digit typo. Both are syntactically valid ints, so before this fix
    they reached `search_terms` and, for the typo, silently produced a
    nonsense term ("60br" from `20260 % 100`) with no symptom. Both now skip
    `terms` for their own row, same posture as the other wrong-typed cases in
    this file; `doc-c` proves it's a per-row degrade, not a whole-request one.
    """
    _write(
        tmp_path,
        {
            "doc-a": _entry(doc_type="baseline-per-agency", fiscal_year=True),
            "doc-b": _entry(doc_type="baseline-per-agency", fiscal_year=20260),
            "doc-c": _entry(doc_type="afr", fiscal_year=2025),
        },
    )

    response = client.get("/api/corpus/documents")

    assert response.status_code == 200
    rows = {r["doc_id"]: r for r in response.json()["documents"]}
    assert rows["doc-a"]["terms"] == []
    assert rows["doc-b"]["terms"] == []
    assert rows["doc-c"]["terms"] == ["25afr", "afr"]


def test_a_wrong_typed_doc_type_lists_with_no_terms_not_a_500(client, tmp_path):
    """Reproduced against the pre-fix route: `doc_type=["baseline-per-agency"]`
    (a list) raises TypeError being hashed as a dict key in
    `_doc_type_forms().get(doc_type or "", ())`, 500ing the whole listing.
    Same per-row degrade as the fiscal_year case above; `doc-b` still lists
    its real terms.
    """
    _write(
        tmp_path,
        {
            "doc-a": _entry(doc_type=["baseline-per-agency"], fiscal_year=2027),
            "doc-b": _entry(doc_type="afr", fiscal_year=2025),
        },
    )

    response = client.get("/api/corpus/documents")

    assert response.status_code == 200
    rows = {r["doc_id"]: r for r in response.json()["documents"]}
    assert rows["doc-a"]["terms"] == []
    assert rows["doc-b"]["terms"] == ["25afr", "afr"]


def test_listing_rows_say_which_book_a_section_belongs_to(client, tmp_path):
    """Folding happens in the browser, but the DERIVATION is server-side so it
    has exactly one implementation -- the provider needs the same answer for
    content-mode filtering (spec B3/B5)."""
    _write(
        tmp_path,
        {
            "jlbc-approps-fy2022-497": _entry(
                doc_type="detailed-list-pdf",
                fiscal_year=2022,
                source_url="https://www.azjlbc.gov/22baseline/497.pdf",
                title="General Fund Revenue — FY 2022 Baseline",
            ),
            "jlbc-approps-fy2025-adc": _entry(
                doc_type="approps-per-agency",
                fiscal_year=2025,
                source_url="https://www.azjlbc.gov/25ar/adc.pdf",
                title="FY 2025 Appropriations Report — ADC",
            ),
        },
    )

    rows = client.get("/api/corpus/documents").json()["documents"]

    by_id = {r["doc_id"]: r for r in rows}
    # The mis-minted doc_id says approps; the URL says baseline and wins.
    assert by_id["jlbc-approps-fy2022-497"]["section_of"] == "Baseline"
    # A real document type is never folded.
    assert by_id["jlbc-approps-fy2025-adc"]["section_of"] is None


def test_a_degraded_catalog_logs_once_per_page_load_not_once_per_row(
    client, tmp_path, monkeypatch, capsys
):
    """2026-08-11 review finding 1 (second pass): `document_listing()` calls
    `search_terms` once per ROW, and (before this fix) `_agency_terms` called
    `load_agency_catalog_by_slug()` once per row too — so a permanently-unreadable
    catalog logged its stderr line, and reopened the ~10k-line YAML, once per
    DOCUMENT. Measured at 5,330 stderr lines / 1.33 MB for one page load
    against the live corpus. `document_listing` now calls
    `load_agency_catalog_by_slug()` once and hands the result to every row, so
    the catalog is read — and the failure logged — exactly once per call. Three
    documents are used because one document can't distinguish "once" from
    "once per row"; three can.
    """
    _write(
        tmp_path,
        {
            "doc-a": _entry(doc_type="baseline-per-agency", fiscal_year=2027),
            "doc-b": _entry(doc_type="afr", fiscal_year=2025),
            "doc-c": _entry(doc_type="approps-per-agency", fiscal_year=2026),
        },
    )

    def boom(*_a, **_kw):
        raise OSError("simulated unreadable catalog")

    from app.search_terms import _catalog_by_slug_cached

    monkeypatch.setattr("chunking.agency_catalog.load_agency_catalog", boom)
    # `_catalog_by_slug_cached` is `lru_cache(maxsize=1)` and process-wide, so
    # an earlier test's successful read would short-circuit this one without
    # clearing it first — same reasoning as tests/test_search_terms.py's
    # identical clear-before/clear-after around this cache.
    _catalog_by_slug_cached.cache_clear()
    try:
        response = client.get("/api/corpus/documents")
    finally:
        _catalog_by_slug_cached.cache_clear()

    assert response.status_code == 200
    # The listing itself must be unaffected — three rows, each with no agency
    # terms (type shorthand still applies, verified separately elsewhere).
    assert len(response.json()["documents"]) == 3

    stderr = capsys.readouterr().err
    assert stderr.count("app.search_terms: ignoring the agency catalog") == 1, (
        "expected exactly one degraded-catalog log line for this page load, "
        f"got:\n{stderr}"
    )
