"""LanceSearchProvider maps retrieval's output onto the frozen /api/search
contract. retrieve() itself is faked — Plan 1's own tests own the pipeline;
the MAPPING (field names, snippet truncation, title humanization, filter
pass-through) is what this file owns, and faking keeps it model-free."""
from retrieval import RetrievalResult
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
    # index join (title and meta are the WEBSITE MOCKUP'S own strings).
    assert out == [
        {
            "chunk_id": "c1",
            "doc_id": "jlbc-baseline-fy2027-ahcccs",
            "doc_title": "Health Care Cost Containment System, Arizona — FY 2027 Baseline",
            "snippet": "provider rate increases of $58.1 million from the General Fund",
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
    assert len(out[0]["snippet"]) == 280


def test_missing_sidecar_degrades_to_unlinked_rows(monkeypatch, tmp_path):
    # No documents.json at all -> doc_url is None, search still works.
    monkeypatch.setattr("app.search_provider.retrieve", lambda req, **kw: _fake_result([_chunk()]))
    monkeypatch.setattr("store.config.documents_path", lambda: tmp_path / "absent.json")
    out = LanceSearchProvider().search("q", top_k=5, corpus="budget", filters={})
    assert out[0]["doc_url"] is None


def test_fiscal_notes_corpus_maps_to_its_table(monkeypatch, tmp_path):
    captured = {}

    def fake_retrieve(req, **kw):
        captured["req"] = req
        return _fake_result([])

    monkeypatch.setattr("app.search_provider.retrieve", fake_retrieve)
    _sidecar(tmp_path, monkeypatch, {})
    out = LanceSearchProvider().search("q", top_k=5, corpus="fiscal_notes", filters={})
    assert out == []
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


def test_migration_era_titles_do_not_beat_the_humanizer(tmp_path, monkeypatch):
    """The migration's doc-id-derived titles ('AGAO FY2025 fy2025') are worse
    than the humanizer; only ingest-written entries are trusted."""
    p = _provider_with_sidecar(tmp_path, monkeypatch, {
        "agao-afr-fy2025": {"title": "AGAO FY2025 fy2025", "source_url": None},
    })
    assert p._info("agao-afr-fy2025")["title"] is None


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
