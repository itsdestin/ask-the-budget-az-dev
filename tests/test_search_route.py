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
    assert r["total"] <= 2
