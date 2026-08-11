from pathlib import Path

from fastapi.testclient import TestClient

from app.main import create_app
from app.search_provider import LanceSearchProvider, StubSearchProvider
from retrieval import RetrievalResult
from retrieval.types import RetrievedChunk


def client():
    # Inject the stub explicitly: these tests pin fixture behavior, and since
    # Task 12 a bare create_app() serves real retrieval on machines that have
    # a migrated corpus.
    return TestClient(create_app(provider=StubSearchProvider()))


# --- fixtures for the full-text field test ----------------------------------
# StubSearchProvider ignores `query` and always returns the same canned
# FIXTURE_ROWS (see app/fixtures/search_fixtures.py), so it cannot exercise a
# chunk with caller-chosen `text`. These mirror tests/test_lance_provider.py's
# `_chunk`/`_fake_result` helpers to drive LanceSearchProvider with a fake
# retrieve() instead, through the real /api/search route.

def _chunk(**overrides):
    # `source_url` isn't a RetrievedChunk field (retrieval/types.py) -- it
    # lives in documents.json, joined by doc_id, not on the chunk. Pop it
    # here and stash it as a plain attribute (bypassing the frozen
    # dataclass's __setattr__ via object.__setattr__) so
    # _client_with_chunks can read it back to build the fake sidecar below,
    # without touching retrieval/types.py.
    source_url = overrides.pop("source_url", None)
    base = dict(
        chunk_id="c1",
        doc_id="jlbc-baseline-fy2027-ahcccs",
        text="provider rate increases of $58.1 million from the General Fund",
        score=4.2,
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
    chunk = RetrievedChunk(**base)
    object.__setattr__(chunk, "source_url", source_url)
    return chunk


def _client_with_chunks(monkeypatch, chunks):
    result = RetrievalResult(
        chunks=chunks,
        top_score=chunks[0].score if chunks else -1e9,
        bm25_count=len(chunks),
        dense_count=len(chunks),
        fused_count=len(chunks),
    )
    monkeypatch.setattr("app.search_provider.retrieve", lambda req, **kw: result)
    # A fake documents.json sidecar keyed by each chunk's doc_id, carrying
    # whatever source_url the test attached via _chunk(source_url=...) — this
    # is the only evidence Task 5's section_of() has to tell the two JLBC
    # books apart (doc_id prefixes are wrong for 21 of 647 real sections, per
    # app/book_sections.py's docstring). Monkeypatching load_documents
    # directly (rather than writing a tmp documents.json) keeps these tests
    # from needing a tmp_path fixture.
    sidecar = {c.doc_id: {"source_url": getattr(c, "source_url", None)} for c in chunks}
    monkeypatch.setattr("app.search_provider.load_documents", lambda: sidecar)
    # No real documents.json path is read (load_documents is faked above) —
    # this just keeps sidecar_stamp() from finding a real file on disk.
    monkeypatch.setattr("store.config.documents_path", lambda: Path("/nonexistent/documents.json"))
    return TestClient(create_app(provider=LanceSearchProvider()))


def test_search_returns_contract_shape():
    r = client().post("/api/search", json={"query": "ahcccs provider rates"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "stub"
    assert body["total"] == len(body["results"]) > 0
    first = body["results"][0]
    for key in ("chunk_id", "doc_id", "doc_title", "snippet", "text", "page",
                "score", "doc_type", "fiscal_year", "publisher", "agencies",
                "section_of"):
        assert key in first


def test_filters_narrow_stub_results():
    all_r = client().post("/api/search", json={"query": "budget"}).json()
    filtered = client().post("/api/search", json={
        "query": "budget", "filters": {"publisher": ["agao"]},
    }).json()
    assert 0 < filtered["total"] < all_r["total"]
    assert all(x["publisher"] == "agao" for x in filtered["results"])


def test_empty_query_is_400():
    r = client().post("/api/search", json={"query": "   "})
    assert r.status_code == 400


def test_top_k_caps_results():
    r = client().post("/api/search", json={"query": "budget", "top_k": 2}).json()
    # Exactly 2: there are more than 2 unfiltered fixture rows, so top_k is
    # doing the truncating (a <= assert would also pass on an empty corpus).
    assert r["total"] == 2
    assert len(r["results"]) == 2


def test_field_constraints_reject_bad_input():
    # Pins the Field() constraints on SearchBody: pydantic rejects these
    # before the route body runs, so they are 422s, not the route's own 400.
    c = client()
    assert c.post("/api/search", json={"query": "budget", "top_k": 0}).status_code == 422
    assert c.post("/api/search", json={"query": "budget", "top_k": 101}).status_code == 422
    assert c.post("/api/search",
                  json={"query": "budget", "corpus": "bogus"}).status_code == 422


def test_search_results_carry_the_full_chunk_text(monkeypatch):
    """The browser picks the preview window and paints the marks (H8), so it
    needs the whole passage, not a 280-char prefix. `snippet` stays for the
    Fiscal Notes page, which does no highlighting (H11)."""
    long_text = "Florence Replacement Beds. " + ("filler word " * 60) + "prison beds funded."
    assert len(long_text) > 280

    client = _client_with_chunks(monkeypatch, [_chunk(text=long_text)])
    body = client.post("/api/search", json={"query": "prison beds"}).json()

    row = body["results"][0]
    assert row["text"] == long_text
    assert row["snippet"] == long_text[:280]


def test_results_carry_the_section_parent(monkeypatch):
    # WHY a real source_url and a value assertion, not just key presence: the
    # original version of this test built a chunk with no source_url, so
    # section_of() always returns None (see book_sections.py) and
    # `assert "section_of" in row` passed against a HARDCODED `None` just as
    # readily as against a real derivation -- it never exercised the parsing
    # this field exists for. Verified the new assertion actually discriminates
    # by temporarily forcing section_of() to return None unconditionally and
    # watching this test fail before restoring it.
    client = _client_with_chunks(
        monkeypatch,
        [_chunk(doc_type="s-pdf", source_url="https://www.azjlbc.gov/22baseline/473.pdf")],
    )
    row = client.post("/api/search", json={"query": "x"}).json()["results"][0]
    assert row["section_of"] == "Baseline"


def test_a_family_filter_does_not_leak_the_other_book_s_sections(monkeypatch):
    """`detailed-list-pdf` belongs to BOTH books, so a doc_type filter alone
    cannot express "Baseline sections". The provider filters exactly."""
    client = _client_with_chunks(
        monkeypatch,
        [
            _chunk(chunk_id="a", doc_id="base-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/22baseline/473.pdf"),
            _chunk(chunk_id="b", doc_id="appr-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/05app/302.pdf"),
        ],
    )
    body = client.post(
        "/api/search",
        json={"query": "x", "filters": {"doc_type": ["baseline-per-agency", "detailed-list-pdf"],
                                        "section_family": "Baseline"}},
    ).json()
    assert [r["chunk_id"] for r in body["results"]] == ["a"]


def test_no_family_filter_means_no_dropping(monkeypatch):
    """Over-inclusion is a visible wrong; removing a match the reader did not
    exclude is the forbidden one (spec B6)."""
    client = _client_with_chunks(
        monkeypatch,
        [
            _chunk(chunk_id="a", doc_id="base-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/22baseline/473.pdf"),
            _chunk(chunk_id="b", doc_id="appr-1", doc_type="detailed-list-pdf",
                   source_url="https://www.azjlbc.gov/05app/302.pdf"),
        ],
    )
    body = client.post("/api/search", json={"query": "x"}).json()
    assert {r["chunk_id"] for r in body["results"]} == {"a", "b"}
