from fastapi.testclient import TestClient

from app.main import create_app


def client():
    return TestClient(create_app())


def test_search_returns_contract_shape():
    r = client().post("/api/search", json={"query": "ahcccs provider rates"})
    assert r.status_code == 200
    body = r.json()
    assert body["provider"] == "stub"
    assert body["total"] == len(body["results"]) > 0
    first = body["results"][0]
    for key in ("chunk_id", "doc_id", "doc_title", "snippet", "page",
                "score", "doc_type", "fiscal_year", "publisher", "agencies"):
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
    assert c.post("/api/search",
                  json={"query": "budget", "corpus": "bogus"}).status_code == 422
