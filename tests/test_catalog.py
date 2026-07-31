"""harness/catalog.py — the OpenRouter model catalog (Plan 5 Task 4, spec S13).

NOTHING HERE TOUCHES THE NETWORK. Every test drives a captured payload
(`tests/fixtures/openrouter_models.json`, 12 real entries pulled from
`https://openrouter.ai/api/v1/models` on 2026-07-31) through a fake
transport, so the suite is as fast and as deterministic offline as on.

The properties pinned here are the ones an admin would feel:

  - a model without function calling is EXCLUDED, not ranked low — the
    harness requires tools on every turn, so such a model doesn't
    degrade, it fails 100% of questions,
  - the bundled recommendation list is returned with no network at all
    (offline-first, S7) — an admin setting the app up on a locked-down
    machine still sees something to pick from,
  - a recommendation that has vanished from the live catalog comes back
    marked unavailable rather than silently dropped, because "my model
    stopped working and the page doesn't mention it" is the failure S13
    exists to prevent.
"""
from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from harness.catalog import (
    CACHE_FILE,
    CACHE_TTL_SECONDS,
    RECOMMENDATIONS,
    ModelCard,
    fetch_catalog,
    parse_catalog,
)
from harness.settings import ProviderConfig, Settings
from store.config import data_dir

FIXTURE = Path(__file__).parent / "fixtures" / "openrouter_models.json"


@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path))
    yield


@pytest.fixture
def payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def openrouter_settings(**overrides) -> Settings:
    return Settings(provider=ProviderConfig(api_key="sk-test", **overrides))


def _transport(payload: dict, status: int = 200) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, json=payload)

    return httpx.MockTransport(handler)


def _failing_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("no network", request=request)

    return httpx.MockTransport(handler)


# ---------------------------------------------------------------------------
# parse_catalog — the tool filter and the price conversion
# ---------------------------------------------------------------------------


def test_models_without_tool_calling_are_excluded(payload):
    cards = {c.id: c for c in parse_catalog(payload)}
    # Both of these are real entries whose supported_parameters lack "tools".
    assert "google/gemini-3.1-flash-image" not in cards
    assert "perceptron/perceptron-mk1" not in cards
    assert "qwen/qwen3.7-plus" in cards
    assert all(c.supports_tools for c in cards.values())


def test_prices_are_converted_to_dollars_per_million(payload):
    cards = {c.id: c for c in parse_catalog(payload)}
    card = cards["qwen/qwen3.7-plus"]
    # OpenRouter reports per-token strings ("0.00000032"); an admin reads
    # dollars per million tokens, which is how every vendor quotes.
    assert card.prompt_usd_per_m == pytest.approx(0.32)
    assert card.completion_usd_per_m == pytest.approx(1.28)
    assert card.context_length == 1_000_000


def test_a_malformed_price_yields_none_not_an_exception(payload):
    payload["data"][0]["pricing"]["prompt"] = "not-a-number"
    payload["data"][1]["pricing"] = None
    cards = {c.id: c for c in parse_catalog(payload)}
    first = cards[payload["data"][0]["id"]]
    assert first.prompt_usd_per_m is None
    # …and the rest of the card still parses. One vendor's bad price row
    # must not blank the whole picker.
    assert first.name
    assert cards[payload["data"][1]["id"]].completion_usd_per_m is None


def test_every_parsed_card_is_marked_available(payload):
    # Present in the live payload IS the definition of available.
    assert all(c.available for c in parse_catalog(payload))


def test_a_payload_with_no_data_key_parses_to_nothing():
    # A proxy or captive portal answering 200 with an HTML-ish body must
    # read as "no catalog", not as a crash on the admin page.
    assert parse_catalog({}) == []
    assert parse_catalog({"data": "nonsense"}) == []


# ---------------------------------------------------------------------------
# The bundled recommendations
# ---------------------------------------------------------------------------


def test_recommendations_cover_both_tiers():
    hints = {r.tier_hint for r in RECOMMENDATIONS}
    assert hints == {"standard", "deep_research"}
    for tier in ("standard", "deep_research"):
        assert len([r for r in RECOMMENDATIONS if r.tier_hint == tier]) >= 4


def test_recommendations_carry_no_hardcoded_prices():
    """S13: prices are re-checked live, never shipped.

    A price baked into the app is wrong within weeks and an admin has no
    way to tell that the number they are budgeting against is stale.
    """
    for rec in RECOMMENDATIONS:
        assert not hasattr(rec, "prompt_usd_per_m")
        assert rec.blurb and rec.id and rec.tier_hint


def test_recommendation_ids_look_like_model_ids():
    for rec in RECOMMENDATIONS:
        assert "/" in rec.id and " " not in rec.id


# ---------------------------------------------------------------------------
# fetch_catalog — live, cached, bundled
# ---------------------------------------------------------------------------


def test_live_fetch_returns_the_catalog_and_marks_recommendations(payload):
    result = fetch_catalog(openrouter_settings(), transport=_transport(payload))
    assert result.source == "live"
    assert result.fetched_at
    assert result.note is None
    ids = {c.id for c in result.catalog}
    assert "qwen/qwen3.7-plus" in ids
    recommended = {c.id: c for c in result.recommended}
    assert recommended["qwen/qwen3.7-plus"].available is True
    # The recommendation keeps its curated blurb and tier hint, and gains
    # the live price — that is the whole point of merging the two.
    assert recommended["qwen/qwen3.7-plus"].blurb
    assert recommended["qwen/qwen3.7-plus"].tier_hint == "standard"
    assert recommended["qwen/qwen3.7-plus"].prompt_usd_per_m == pytest.approx(0.32)


def test_a_recommendation_missing_from_the_catalog_is_kept_but_unavailable(payload):
    """The admin needs to see WHY their configured model stopped working.

    Dropping the row would leave the page looking normal while the model
    it used to name is simply gone.
    """
    gone = "moonshotai/kimi-k3"
    payload["data"] = [m for m in payload["data"] if m["id"] != gone]

    result = fetch_catalog(openrouter_settings(), transport=_transport(payload))
    recommended = {c.id: c for c in result.recommended}
    assert gone in recommended
    assert recommended[gone].available is False
    assert recommended[gone].prompt_usd_per_m is None


def test_no_network_returns_the_bundled_list_with_a_note():
    result = fetch_catalog(openrouter_settings(), transport=_failing_transport())
    assert result.source == "bundled"
    assert result.catalog == []
    assert {c.id for c in result.recommended} == {r.id for r in RECOMMENDATIONS}
    # Offline-first (S7): the admin still gets something to pick from, and
    # is told plainly why there are no prices next to it. The note must
    # not claim a cause it can't know — see NOTE_OFFLINE.
    assert all(c.available is False for c in result.recommended)
    assert result.note and "no live prices" in result.note
    assert "model list from OpenRouter" in result.note


def test_an_http_error_degrades_the_same_way(payload):
    result = fetch_catalog(openrouter_settings(), transport=_transport(payload, status=500))
    assert result.source == "bundled"
    assert result.note


def test_a_successful_fetch_is_cached_on_disk(payload):
    fetch_catalog(openrouter_settings(), transport=_transport(payload))
    cache = data_dir() / CACHE_FILE
    assert cache.is_file()

    # A second call must not hit the network at all — proven by handing it
    # a transport that would raise if it did.
    result = fetch_catalog(openrouter_settings(), transport=_failing_transport())
    assert result.source == "cache"
    assert {c.id for c in result.catalog}
    assert result.fetched_at


def test_refresh_bypasses_the_cache(payload):
    fetch_catalog(openrouter_settings(), transport=_transport(payload))
    trimmed = {"data": payload["data"][:1]}
    result = fetch_catalog(
        openrouter_settings(), refresh=True, transport=_transport(trimmed)
    )
    assert result.source == "live"
    assert len(result.catalog) <= 1


def test_a_stale_cache_is_refetched(payload, monkeypatch):
    fetch_catalog(openrouter_settings(), transport=_transport(payload))
    cache = data_dir() / CACHE_FILE
    stale = json.loads(cache.read_text(encoding="utf-8"))
    stale["fetched_at_epoch"] -= CACHE_TTL_SECONDS + 1
    cache.write_text(json.dumps(stale), encoding="utf-8")

    trimmed = {"data": payload["data"][:2]}
    result = fetch_catalog(openrouter_settings(), transport=_transport(trimmed))
    assert result.source == "live"


def test_a_corrupt_cache_falls_back_rather_than_crashing(payload):
    (data_dir() / CACHE_FILE).write_text("{ not json", encoding="utf-8")
    result = fetch_catalog(openrouter_settings(), transport=_transport(payload))
    # An unreadable cache is a reason to refetch, never a reason to fail —
    # this file lives on a share and gets copied around.
    assert result.source == "live"


def test_a_custom_endpoint_gets_no_openrouter_catalog(payload):
    """S15: a custom endpoint's models are the admin's own.

    Showing OpenRouter's list next to a base_url pointing somewhere else
    would invite picking a model the endpoint has never heard of.
    """
    settings = Settings(
        provider=ProviderConfig(
            api_key="sk-test", provider="custom", base_url="https://example.test/v1"
        )
    )
    result = fetch_catalog(settings, transport=_transport(payload))
    assert result.source == "bundled"
    assert result.catalog == []
    assert result.note and "custom endpoint" in result.note.lower()


def test_model_card_is_json_safe(payload):
    result = fetch_catalog(openrouter_settings(), transport=_transport(payload))
    # The route hands these straight to FastAPI; a dataclass that doesn't
    # round-trip through json would 500 at render time, not at import.
    json.dumps([c.as_dict() for c in result.recommended])
    assert isinstance(result.recommended[0], ModelCard)
