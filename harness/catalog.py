"""OpenRouter model catalog + the shipped recommendations (Plan 5 Task 4, S13).

What this module is for: an admin who has never heard of any of these
models has to pick two of them. OpenRouter lists ~330; most are useless
here (no function calling), and the ones that work differ by 40× in
price. So this module does three things — fetch the live list, throw out
everything the harness can't actually drive, and hand back a short
curated shortlist with a plain-English blurb per entry.

Three decisions worth knowing before editing:

1. **`supported_parameters` must contain "tools".** The harness calls
   `retrieve()` before answering, every turn, via function calling. A
   model without it does not degrade to "worse answers" — it fails every
   single question. So this is an exclusion, not a ranking signal.

2. **No price is ever hardcoded.** `RECOMMENDATIONS` carries ids, names,
   tier hints and blurbs; every dollar figure on the admin page comes
   from the live catalog at render time. A price baked into the app is
   wrong within weeks, and an admin budgeting against a stale number has
   no way to know.

3. **Offline is a first-class outcome, not an error** (S7). A locked-down
   office PC with no outbound HTTPS still has to show an admin a list to
   pick from, so every failure path returns the bundled recommendations
   with `available=False` and a `note` saying why there are no prices.
"""
from __future__ import annotations

import json
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import httpx

from harness.settings import Settings
from store.config import data_dir

MODELS_URL = "https://openrouter.ai/api/v1/models"
CACHE_FILE = "model-catalog.json"

# Six hours. The catalog changes on the order of days (new models, retired
# ones, occasional price moves), and the admin page is opened rarely — so
# a long TTL costs nothing and keeps the page instant on a slow share.
# `refresh=1` is the escape hatch for an admin who just read about a model
# and wants it now.
CACHE_TTL_SECONDS = 6 * 60 * 60

# The catalog is a public endpoint (no key needed) and the admin page waits
# on it, so the timeout is short enough that a dead network shows the
# bundled list quickly rather than hanging the panel.
FETCH_TIMEOUT_SECONDS = 10.0

# Deliberately non-committal about WHY (error-message standard): this one
# string covers a dead network, a corporate proxy, an OpenRouter 500 and a
# body that isn't JSON. Naming a cause here would be a guess, and the real
# error is on stderr for whoever is actually debugging.
NOTE_OFFLINE = (
    "Couldn't get the current model list from OpenRouter, so this is the "
    "list that shipped with the app and there are no live prices. The "
    "models below should still work — pick one and use “Test” to confirm."
)
NOTE_CUSTOM = (
    "You're pointed at a custom endpoint, so OpenRouter's model list and "
    "prices don't apply. Type the model id your endpoint expects. It must "
    "support tool calling, or AI Mode will fail on every question."
)


@dataclass(frozen=True)
class Recommendation:
    """One curated entry. Deliberately carries NO price — see decision 2."""

    id: str
    name: str
    tier_hint: str  # "standard" | "deep_research"
    blurb: str


# The shipped shortlist, and — this is the part that matters beyond the
# admin page — **the fallback order for Task 5**. When a configured model
# is retired mid-question, the session walks that tier's entries in this
# order, so entry 0 of each tier should be the one currently assigned and
# verified, and the rest should descend by preference.
#
# Ship-time picks follow S16: Deep Research gets a cost-effective
# frontier-class OPEN model, Standard gets the best
# opus-level-performance-per-dollar OPEN model. First-party flagships
# (Fable/Opus/GPT-class) are deliberately absent — the whole point is a
# tool the office can afford to leave switched on, and open weights get
# most of the quality for a fraction of the per-token price. All eight
# were confirmed present and tool-capable on OpenRouter on 2026-07-31;
# the first entry of each tier is what the 2026-07-31 live run actually
# used end to end.
RECOMMENDATIONS: tuple[Recommendation, ...] = (
    # --- Standard: quick lookups, ~15 steps, run all day -------------
    Recommendation(
        id="qwen/qwen3.7-plus",
        name="Qwen3.7 Plus",
        tier_hint="standard",
        blurb=(
            "The current default. Cheap enough to leave on all day, and a "
            "very large context window so long budget tables survive intact. "
            "This is the model the app was tested with."
        ),
    ),
    Recommendation(
        id="deepseek/deepseek-v4-flash",
        name="DeepSeek V4 Flash",
        tier_hint="standard",
        blurb=(
            "The cheapest option that still follows citation instructions "
            "reliably. Pick this if the monthly bill matters more than the "
            "occasional re-ask."
        ),
    ),
    Recommendation(
        id="minimax/minimax-m3",
        name="MiniMax M3",
        tier_hint="standard",
        blurb=(
            "A middle option — priced near the default with a very large "
            "context window. Worth trying if answers feel thin."
        ),
    ),
    Recommendation(
        id="z-ai/glm-4.7",
        name="GLM 4.7",
        tier_hint="standard",
        blurb=(
            "A different vendor's take at a similar price. Useful mainly as "
            "a second opinion if one vendor is having a bad week."
        ),
    ),
    # --- Deep Research: multi-year sweeps, ~50 steps, used on purpose --
    Recommendation(
        id="moonshotai/kimi-k3",
        name="Kimi K3",
        tier_hint="deep_research",
        blurb=(
            "The current default for Deep Research, and the most expensive "
            "thing here by a wide margin — roughly 40× a Standard question. "
            "That is why Deep Research is a deliberate click, not the default."
        ),
    ),
    Recommendation(
        id="z-ai/glm-5.2",
        name="GLM 5.2",
        tier_hint="deep_research",
        blurb=(
            "Frontier-class at a fraction of the default's price, with a very "
            "large context window. The first thing to try if Deep Research is "
            "costing more than the office wants to spend."
        ),
    ),
    Recommendation(
        id="deepseek/deepseek-v4-pro",
        name="DeepSeek V4 Pro",
        tier_hint="deep_research",
        blurb=(
            "The cheapest frontier-class option on this list. Slower to "
            "reason through a broad question, but a fraction of the cost."
        ),
    ),
    Recommendation(
        id="moonshotai/kimi-k2.6",
        name="Kimi K2.6",
        tier_hint="deep_research",
        blurb=(
            "The previous generation of the default. Kept here as the "
            "safe landing spot if the newer one is ever retired."
        ),
    ),
)


@dataclass(frozen=True)
class ModelCard:
    """One row in the admin page's model picker.

    `available` means "the live catalog confirmed this model exists right
    now". A bundled recommendation the catalog couldn't confirm is
    returned with `available=False` rather than dropped — see
    `_merge_recommendations`.
    """

    id: str
    name: str
    context_length: int | None
    prompt_usd_per_m: float | None
    completion_usd_per_m: float | None
    supports_tools: bool
    available: bool
    tier_hint: str | None = None
    blurb: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class CatalogResult:
    """What `fetch_catalog` hands the route.

    `source` is "live" (just fetched), "cache" (a recent fetch on disk) or
    "bundled" (no catalog at all — offline, an error, or a custom
    endpoint). The admin page shows it, because "these prices are six
    hours old" and "there are no prices" are different things to be
    looking at while choosing what to spend money on.
    """

    source: str
    fetched_at: str | None
    recommended: list[ModelCard]
    catalog: list[ModelCard]
    note: str | None = None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _usd_per_million(pricing: Any, key: str) -> float | None:
    """OpenRouter's per-token price string -> dollars per million tokens.

    Returns None rather than raising on anything unexpected: a single
    vendor publishing a malformed price must cost that one number, not
    the entire picker. `-1` is OpenRouter's sentinel on its own routing
    pseudo-models (`openrouter/auto`), which have no price of their own.
    """
    if not isinstance(pricing, dict):
        return None
    try:
        value = float(pricing[key])
    except (KeyError, TypeError, ValueError):
        return None
    if value < 0:
        return None
    return value * 1_000_000


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return int(value)


def parse_catalog(payload: Any) -> list[ModelCard]:
    """Live `/api/v1/models` payload -> the tool-capable subset, priced.

    A payload that isn't the expected shape (a captive portal answering
    200 with a login page, a proxy rewriting the body) parses to an empty
    list rather than raising — the caller then treats it exactly like a
    failed fetch and falls back to the bundled list.
    """
    if not isinstance(payload, dict):
        return []
    rows = payload.get("data")
    if not isinstance(rows, list):
        return []

    cards: list[ModelCard] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        params = row.get("supported_parameters")
        # THE tool filter. See decision 1 in the module docstring — a model
        # without function calling fails every question, so it never
        # reaches a picker.
        if not isinstance(params, list) or "tools" not in params:
            continue
        model_id = row.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        pricing = row.get("pricing")
        cards.append(
            ModelCard(
                id=model_id,
                name=str(row.get("name") or model_id),
                context_length=_int_or_none(row.get("context_length")),
                prompt_usd_per_m=_usd_per_million(pricing, "prompt"),
                completion_usd_per_m=_usd_per_million(pricing, "completion"),
                supports_tools=True,
                available=True,
            )
        )
    return cards


def _merge_recommendations(catalog: list[ModelCard]) -> list[ModelCard]:
    """The curated shortlist, priced from the live catalog where possible.

    A recommendation the catalog does NOT contain is still returned, with
    `available=False` and no prices. That is the whole point: when a model
    is retired, the admin whose tier still names it needs to see it sitting
    there greyed out, not find that the row quietly disappeared and left
    them with a working-looking page and a broken AI Mode.
    """
    live = {card.id: card for card in catalog}
    merged: list[ModelCard] = []
    for rec in RECOMMENDATIONS:
        card = live.get(rec.id)
        if card is None:
            merged.append(
                ModelCard(
                    id=rec.id,
                    name=rec.name,
                    context_length=None,
                    prompt_usd_per_m=None,
                    completion_usd_per_m=None,
                    # Curated BECAUSE it does function calling — that is the
                    # entry criterion for this list. Unconfirmed by the
                    # catalog is what `available=False` says.
                    supports_tools=True,
                    available=False,
                    tier_hint=rec.tier_hint,
                    blurb=rec.blurb,
                )
            )
            continue
        merged.append(
            ModelCard(
                id=card.id,
                # The curated name, not the vendor's marketing string — the
                # blurb is written to sit next to it.
                name=rec.name,
                context_length=card.context_length,
                prompt_usd_per_m=card.prompt_usd_per_m,
                completion_usd_per_m=card.completion_usd_per_m,
                supports_tools=True,
                available=True,
                tier_hint=rec.tier_hint,
                blurb=rec.blurb,
            )
        )
    return merged


def _bundled(note: str) -> CatalogResult:
    return CatalogResult(
        source="bundled",
        fetched_at=None,
        recommended=_merge_recommendations([]),
        catalog=[],
        note=note,
    )


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _cache_path() -> Path:
    return data_dir() / CACHE_FILE


def _read_cache() -> tuple[list[ModelCard], str] | None:
    """The cached catalog if it is present, parseable and fresh; else None.

    Every failure mode here — missing, corrupt, stale, written by a newer
    version with a different shape — is answered the same way: return
    None, which makes the caller refetch. This file lives on a share and
    gets copied between machines; treating a bad one as fatal would break
    the admin page over a cache.
    """
    path = _cache_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as err:
        print(
            f"harness.catalog: {path} is unreadable ({err}) — refetching "
            "the model catalog.",
            file=sys.stderr,
        )
        return None
    if not isinstance(raw, dict):
        return None
    fetched_epoch = raw.get("fetched_at_epoch")
    if not isinstance(fetched_epoch, (int, float)):
        return None
    if time.time() - fetched_epoch > CACHE_TTL_SECONDS:
        return None
    cards = parse_catalog(raw.get("payload"))
    if not cards:
        return None
    return cards, str(raw.get("fetched_at") or "")


def _write_cache(payload: Any, fetched_at: str) -> None:
    """Best-effort. A read-only share costs a cache, not a page.

    Written with the raw payload rather than the parsed cards so a later
    version of `parse_catalog` (a new field, a changed filter) reads the
    same cache correctly instead of inheriting this version's decisions.
    """
    path = _cache_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(
            json.dumps(
                {
                    "fetched_at": fetched_at,
                    "fetched_at_epoch": time.time(),
                    "payload": payload,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        tmp.replace(path)
    except OSError as err:
        print(
            f"harness.catalog: couldn't cache the model catalog to {path} "
            f"({err}) — the admin page will refetch it every time it opens.",
            file=sys.stderr,
        )


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------


def fetch_catalog(
    settings: Settings,
    *,
    refresh: bool = False,
    transport: httpx.BaseTransport | None = None,
) -> CatalogResult:
    """The model list for the admin page. Never raises.

    `transport` is the test seam — every test in tests/test_catalog.py
    passes an `httpx.MockTransport`, so the suite never touches the
    network. Production passes nothing.

    Note what this does NOT need: the API key. `/api/v1/models` is public,
    which is exactly what makes the picker usable on a fresh install
    before any key has been entered.
    """
    if settings.provider.provider == "custom":
        # S15: the admin's endpoint has its own models. Offering
        # OpenRouter's list here would invite picking one it has never
        # heard of, and the failure would surface as an opaque provider
        # error mid-question.
        return _bundled(NOTE_CUSTOM)

    if not refresh:
        cached = _read_cache()
        if cached is not None:
            cards, fetched_at = cached
            return CatalogResult(
                source="cache",
                fetched_at=fetched_at,
                recommended=_merge_recommendations(cards),
                catalog=cards,
            )

    try:
        client = httpx.Client(timeout=FETCH_TIMEOUT_SECONDS, transport=transport)
        with client:
            response = client.get(MODELS_URL)
            response.raise_for_status()
            payload = response.json()
    except Exception as err:  # noqa: BLE001
        # Deliberately broad: connect errors, timeouts, TLS failures behind
        # a corporate proxy, HTTP 5xx, and a body that isn't JSON all mean
        # the same thing to the admin — no live list right now — and all of
        # them must end at the bundled list rather than a 500 on the page
        # they opened to fix things. The real error goes to stderr so it is
        # diagnosable; the UI copy stays non-committal because guessing a
        # cause here would be a guess.
        print(
            f"harness.catalog: couldn't fetch {MODELS_URL} "
            f"({type(err).__name__}: {err}) — serving the bundled list.",
            file=sys.stderr,
        )
        return _bundled(NOTE_OFFLINE)

    cards = parse_catalog(payload)
    if not cards:
        print(
            f"harness.catalog: {MODELS_URL} answered with no usable models — "
            "serving the bundled list.",
            file=sys.stderr,
        )
        return _bundled(NOTE_OFFLINE)

    fetched_at = datetime.now().astimezone().isoformat()
    _write_cache(payload, fetched_at)
    return CatalogResult(
        source="live",
        fetched_at=fetched_at,
        recommended=_merge_recommendations(cards),
        catalog=cards,
    )
