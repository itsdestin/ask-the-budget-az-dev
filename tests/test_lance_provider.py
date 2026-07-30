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

    out = LanceSearchProvider().search(
        "ahcccs rates",
        top_k=5,
        corpus="budget",
        filters={"publisher": ["jlbc"], "fiscal_year": [2027]},
    )

    # The frozen contract's ten row fields, mapped from the chunk.
    assert out == [
        {
            "chunk_id": "c1",
            "doc_id": "jlbc-baseline-fy2027-ahcccs",
            "doc_title": "JLBC Baseline FY 2027 Ahcccs",  # best-effort humanizer
            "snippet": "provider rate increases of $58.1 million from the General Fund",
            "page": 14,
            "score": 4.2,
            "doc_type": "baseline-per-agency",
            "fiscal_year": 2027,
            "publisher": "jlbc",
            "agencies": ["ahcccs"],
            # From the documents.json sidecar — the row's link to the
            # individual agency narrative PDF.
            "doc_url": "https://www.azjlbc.gov/27baseline/axs.pdf",
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
