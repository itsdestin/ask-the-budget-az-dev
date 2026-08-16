"""LanceSearchProvider maps retrieval's output onto the frozen /api/search
contract. retrieve() itself is faked — Plan 1's own tests own the pipeline;
the MAPPING (field names, snippet truncation, title humanization, filter
pass-through) is what this file owns, and faking keeps it model-free."""
from retrieval import FUSED_TOP_K, RetrievalResult
from retrieval.types import RetrievedChunk

from app.search_provider import LanceSearchProvider


def _chunk(**overrides):
    base = dict(
        chunk_id="c1",
        doc_id="jlbc-baseline-fy2027-ahcccs",
        text="provider rate increases of $58.1 million from the General Fund",
        score=4.2,  # raw cross-encoder logit — the real scale after Plan 1
        section_path=["AHCCCS"],
        page=14,
        bbox=None,
        source_anchor=None,
        agency_canonical_ids=["ahcccs"],
        fund_canonical_id=None,
        fund_mentions=[],
        fiscal_year=2027,
        doc_type="baseline-per-agency",
        is_table=False,
        table_html=None,
        token_count=8,
        publisher="jlbc",
    )
    base.update(overrides)
    return RetrievedChunk(**base)


def _fake_result(chunks):
    return RetrievalResult(
        chunks=chunks,
        top_score=chunks[0].score if chunks else -1e9,
        bm25_count=len(chunks),
        dense_count=len(chunks),
        fused_count=len(chunks),
    )


def _sidecar(tmp_path, monkeypatch, records):
    """Point the provider's documents.json lookup at a tmp sidecar."""
    p = tmp_path / "documents.json"
    p.write_text(__import__("json").dumps(records), encoding="utf-8")
    monkeypatch.setattr("store.config.documents_path", lambda: p)


def _mockup_index(tmp_path, monkeypatch, entries):
    """Point the provider's mockup-index lookup at a tmp index-lite.js."""
    p = tmp_path / "index-lite.js"
    p.write_text(
        "window.JLBC_DOCS=" + __import__("json").dumps(entries) + ";",
        encoding="utf-8",
    )
    monkeypatch.setattr("app.search_provider.MOCKUP_INDEX_PATH", p)


def test_provider_maps_retrieval_result_to_contract(monkeypatch, tmp_path):
    captured = {}

    def fake_retrieve(req, **kw):
        captured["req"] = req
        return _fake_result([_chunk()])

    monkeypatch.setattr("app.search_provider.retrieve", fake_retrieve)
    _sidecar(tmp_path, monkeypatch, {
        "jlbc-baseline-fy2027-ahcccs": {
            "source_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
        },
    })
    # A mini mockup index whose URL matches the sidecar's (different CASE on
    # purpose — the join must be case-insensitive, real data mixes 25AR/25ar).
    _mockup_index(tmp_path, monkeypatch, [{
        "url": "https://www.azjlbc.gov/27baseline/AXS.pdf",
        "title": "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
        "category": "Agency Budget Detail",
        "doc_type": "Baseline Book",
        "fiscal_year": 2027,
    }])

    out = LanceSearchProvider().search(
        "ahcccs rates",
        top_k=5,
        corpus="budget",
        filters={"publisher": ["jlbc"], "fiscal_year": [2027]},
    )

    # The frozen contract's row fields, mapped from the chunk + the mockup
    # index join. Re-pointed 2026-08-16 (spec I12, Task 3): `doc_title` used
    # to be the WEBSITE MOCKUP'S own title unconditionally — that rung is
    # gone, because it is the supplier of 218 wrong names
    # (`05app/bar.pdf` -> "Agriculture, Arizona Department of" for the Board
    # of Barbers). This fixture's sidecar entry carries no `title`, so the
    # real behaviour is now the humanizer; `doc_meta` still comes from the
    # mockup join, which was never wrong.
    assert out.rows == [
        {
            "chunk_id": "c1",
            "doc_id": "jlbc-baseline-fy2027-ahcccs",
            "doc_title": "JLBC Baseline FY 2027 Ahcccs",
            "snippet": "provider rate increases of $58.1 million from the General Fund",
            # Additive 2026-08-13: the fiscal-note result card prints the
            # INNERMOST heading as its excerpt legend, and until now the only
            # section-ish row field was `doc_meta` -- the mockup index's
            # category line, which on the fiscal-note corpus renders as the
            # doubled, uninformative "Fiscal Notes . Fiscal Notes . FY 2026".
            "section_path": ["AHCCCS"],
            # Task 1: the frozen contract gained `text` (full, untruncated
            # passage) alongside `snippet` (the leading-280-char preview) —
            # here they're equal because the fixture chunk is short.
            "text": "provider rate increases of $58.1 million from the General Fund",
            "page": 14,
            "score": 4.2,
            "doc_type": "baseline-per-agency",
            "fiscal_year": 2027,
            "publisher": "jlbc",
            "agencies": ["ahcccs"],
            # From the documents.json sidecar — the row's link to the
            # individual agency narrative PDF.
            "doc_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
            # The mockup docRow's meta recipe: category · doc_type · FY.
            "doc_meta": "Agency Budget Detail · Baseline Book · FY 2027",
            # Task 7: which JLBC book this is a SECTION of, or null.
            # "baseline-per-agency" isn't a section doc_type (it's a real
            # document type, an agency's own page in the book) — None here.
            "section_of": None,
        }
    ]

    # The request passed through: corpus name mapped to the table, filters and
    # top_k forwarded on the RetrievalRequest's own fields.
    req = captured["req"]
    assert req.query == "ahcccs rates"
    assert req.top_k == 5
    assert req.corpus == "budget_chunks"
    assert req.publisher == ["jlbc"]
    assert req.fiscal_year == [2027]
    assert req.agency_canonical_id is None  # unset filter stays unset


def test_snippet_truncates_long_text(monkeypatch, tmp_path):
    monkeypatch.setattr(
        "app.search_provider.retrieve",
        lambda req, **kw: _fake_result([_chunk(text="x" * 1000)]),
    )
    _sidecar(tmp_path, monkeypatch, {})
    out = LanceSearchProvider().search("q", top_k=5, corpus="budget", filters={})
    assert len(out.rows[0]["snippet"]) == 280


def test_missing_sidecar_degrades_to_unlinked_rows(monkeypatch, tmp_path):
    # No documents.json at all -> doc_url is None, search still works.
    monkeypatch.setattr("app.search_provider.retrieve", lambda req, **kw: _fake_result([_chunk()]))
    monkeypatch.setattr("store.config.documents_path", lambda: tmp_path / "absent.json")
    out = LanceSearchProvider().search("q", top_k=5, corpus="budget", filters={})
    assert out.rows[0]["doc_url"] is None


# --- Task 7: family filtering asks retrieve() for the pipeline's ceiling ----
# tests/test_search_route.py owns the filtering BEHAVIOUR (which rows survive
# a section_family filter); this file owns the REQUEST this provider makes to
# retrieve() to get there, same split as the rest of this file.


def test_family_filter_requests_the_pipeline_ceiling(monkeypatch, tmp_path):
    """A family filter is applied AFTER ranking, so retrieve() must be asked
    for the pipeline's own ceiling (FUSED_TOP_K) rather than the caller's
    top_k -- see the WHY comment on LanceSearchProvider.search for the
    real-corpus measurement that ruled out a smaller ceil(top_k/yield)
    over-fetch (worst-case yield was 0/20, which divides by zero)."""
    captured = {}

    def fake_retrieve(req, **kw):
        captured["req"] = req
        return _fake_result([_chunk(doc_id="base-1", doc_type="detailed-list-pdf")])

    monkeypatch.setattr("app.search_provider.retrieve", fake_retrieve)
    _sidecar(tmp_path, monkeypatch, {
        "base-1": {"source_url": "https://www.azjlbc.gov/22baseline/473.pdf"},
    })

    LanceSearchProvider().search(
        "q", top_k=3, corpus="budget",
        filters={"doc_type": ["detailed-list-pdf"], "section_family": "Baseline"},
    )

    assert captured["req"].top_k == FUSED_TOP_K


def test_family_filter_reslices_to_the_caller_s_top_k(monkeypatch, tmp_path):
    """retrieve() can hand back up to FUSED_TOP_K rows once over-fetched for
    a family filter; the provider must not return more than the caller
    actually asked for."""
    monkeypatch.setattr(
        "app.search_provider.retrieve",
        lambda req, **kw: _fake_result([
            _chunk(chunk_id="a", doc_id="base-1", doc_type="detailed-list-pdf"),
            _chunk(chunk_id="b", doc_id="base-2", doc_type="detailed-list-pdf"),
            _chunk(chunk_id="c", doc_id="base-3", doc_type="detailed-list-pdf"),
        ]),
    )
    _sidecar(tmp_path, monkeypatch, {
        "base-1": {"source_url": "https://www.azjlbc.gov/22baseline/473.pdf"},
        "base-2": {"source_url": "https://www.azjlbc.gov/22baseline/474.pdf"},
        "base-3": {"source_url": "https://www.azjlbc.gov/22baseline/475.pdf"},
    })

    out = LanceSearchProvider().search(
        "q", top_k=1, corpus="budget",
        filters={"doc_type": ["detailed-list-pdf"], "section_family": "Baseline"},
    )

    assert len(out.rows) == 1


def test_fiscal_notes_corpus_maps_to_its_table(monkeypatch, tmp_path):
    captured = {}

    def fake_retrieve(req, **kw):
        captured["req"] = req
        return _fake_result([])

    monkeypatch.setattr("app.search_provider.retrieve", fake_retrieve)
    _sidecar(tmp_path, monkeypatch, {})
    out = LanceSearchProvider().search("q", top_k=5, corpus="fiscal_notes", filters={})
    assert out.rows == []
    assert captured["req"].corpus == "fiscal_note_chunks"


# --- title precedence after Plan 3's ingest writes real titles ---------------


def _provider_with_sidecar(tmp_path, monkeypatch, sidecar: dict):
    import json as _json

    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    (tmp_path / "documents.json").write_text(_json.dumps(sidecar), encoding="utf-8")
    from app.search_provider import LanceSearchProvider

    p = LanceSearchProvider()
    p._doc_info = None
    return p


def test_ingest_written_titles_beat_the_slug_humanizer(tmp_path, monkeypatch):
    """Task 5's whole point: a newly ingested document shows its real title,
    not 'JLBC Baseline FY 2027 27baseline Axs'."""
    p = _provider_with_sidecar(tmp_path, monkeypatch, {
        "jlbc-baseline-fy2027-27baseline-axs": {
            "title": "FY 2027 Baseline — Industrial Commission of Arizona",
            "source_url": None,
            "ingested_at": "2026-07-31T03:51:13+00:00",
        },
    })
    assert p._info("jlbc-baseline-fy2027-27baseline-axs")["title"] == \
        "FY 2027 Baseline — Industrial Commission of Arizona"


def test_a_migration_era_title_with_no_ingested_at_still_wins(tmp_path, monkeypatch):
    """Re-pointed 2026-08-16 (spec I12, Task 3) — this test used to assert
    the OPPOSITE and was encoding the defect. `_info` used to gate the
    sidecar title on `ingested_at` as a tiebreak against the mockup index;
    with the mockup index demoted, `identity.resolve_title` has no such gate
    (see its docstring) because the live corpus holds 378 migration-era
    entries whose titles are mostly fine, and gating them would swap real
    agency names for doc-id slugs. This particular fixture title ('AGAO
    FY2025 fy2025') happens to be an ugly one, but the RULE this test pins
    is "the sidecar wins when it has a title", not "this string is pretty" —
    see `test_a_migration_era_title_with_no_ingested_at_is_STILL_used` in
    `tests/test_identity_resolve.py` for the same rule at the resolver
    itself."""
    p = _provider_with_sidecar(tmp_path, monkeypatch, {
        "agao-afr-fy2025": {"title": "AGAO FY2025 fy2025", "source_url": None},
    })
    assert p._info("agao-afr-fy2025")["title"] == "AGAO FY2025 fy2025"


def test_a_document_ingested_mid_session_gets_its_real_title(tmp_path, monkeypatch):
    """The provider is a process-lifetime singleton and ingest rewrites
    documents.json — without a staleness check, anything uploaded while the
    app runs keeps the doc-id humanizer's title until a restart."""
    import json as _json

    p = _provider_with_sidecar(tmp_path, monkeypatch, {})
    assert p._info("jlbc-baseline-fy2027-axs")["title"] is None

    (tmp_path / "documents.json").write_text(_json.dumps({
        "jlbc-baseline-fy2027-axs": {
            "title": "FY 2027 Baseline — AHCCCS",
            "source_url": None,
            "ingested_at": "2026-07-31T04:00:00+00:00",
        },
    }), encoding="utf-8")
    assert p._info("jlbc-baseline-fy2027-axs")["title"] == "FY 2027 Baseline — AHCCCS"
