"""Auto-naming for a chat (spec H3).

One short non-streaming call after the first exchange. `harness/session.py`
always streams WITH tool schemas, so there is no existing plain-completion
path to reuse — hence a separate small module.

THE RULE THAT MATTERS: this never blocks and never fails a chat. No key, AI
Mode off, over the spend limit, provider error, malformed reply — every one
falls back to truncating the question. Naming is a convenience, and history
must keep working with no OpenRouter key at all, exactly like search, fiscal
notes and upload do.
"""
from __future__ import annotations

import sys

import httpx

from harness.ledger import check_limit, record_usage
from harness.settings import Settings, ai_available, load_settings

TITLE_TIER = "title"
MAX_TITLE_CHARS = 60
_TIMEOUT_S = 20.0

_PROMPT = (
    "Give a 3-6 word title for this exchange between a fiscal analyst and a "
    "budget research tool. Reply with the title only — no quotes, no preamble."
)


def fallback_title(question: str) -> str:
    """The free, always-available title: the question, truncated."""
    flat = " ".join((question or "").split())
    if len(flat) <= MAX_TITLE_CHARS:
        return flat or "New chat"
    return flat[: MAX_TITLE_CHARS - 1].rstrip() + "…"


def generate_title(
    question: str,
    answer: str,
    *,
    user: str,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
) -> str:
    settings = settings if settings is not None else load_settings()
    fallback = fallback_title(question)

    ok, _reason = ai_available(settings, "standard")
    if not ok:
        return fallback

    # check_limit takes user and settings POSITIONALLY and returns a
    # LimitStatus whose `.status` is "allowed" | "warn" | "blocked" — it is
    # NOT a (bool, str) tuple. "warn" still permits the call.
    if check_limit(user, settings).status == "blocked":
        # Being over the office spend cap must not also cost you a readable
        # chat list. The cap governs answers, not bookkeeping.
        return fallback

    model = settings.tiers["standard"].model
    body: dict = {
        "model": model,
        "messages": [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nAnswer: {answer[:2000]}"},
        ],
        "max_tokens": 24,
        "stream": False,
    }
    if settings.provider.provider == "openrouter":
        # OpenRouter's vendor extension, and the ONLY way `usage.cost` comes
        # back — exactly as harness/session.py:961 does it. Without it every
        # title row records cost_usd=None, which sums as zero (so title spend
        # never counts against the S19 limit it is supposed to count against)
        # and increments rows_with_unknown_cost, which the admin page
        # explains as "older requests, made before prices were set up".
        # Gated because a strict OpenAI-compatible server (S15) rejects
        # unknown top-level fields outright.
        body["usage"] = {"include": True}
    # The endpoint comes from settings, NOT a literal: S15's custom-endpoint
    # escape hatch means base_url is admin-configurable, and hardcoding
    # openrouter.ai here would silently ignore it.
    url = settings.provider.base_url.rstrip("/") + "/chat/completions"
    try:
        with httpx.Client(transport=transport, timeout=_TIMEOUT_S) as client:
            response = client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {settings.provider.api_key}"},
            )
            response.raise_for_status()
            payload = response.json()
        text = (payload["choices"][0]["message"]["content"] or "").strip().strip('"')
        usage = payload.get("usage") or {}
    except Exception:                              # noqa: BLE001
        return fallback

    # Ledgered OUTSIDE the block above, and separately guarded: record_usage
    # raises by contract (harness/ledger.py's FAILURE CONTRACT). By the time
    # it runs the call has happened and the money is spent, so a share that
    # is full must cost us the ledger row — not the title we already paid
    # for.
    try:
        record_usage(
            user=user, tier=TITLE_TIER, model=model,
            tokens_in=int(usage.get("prompt_tokens", 0)),
            tokens_out=int(usage.get("completion_tokens", 0)),
            cost_usd=usage.get("cost"),
        )
    except Exception as exc:                       # noqa: BLE001
        print(f"jlbc-search: could not ledger a title call: {exc}",
              file=sys.stderr, flush=True)

    if not text:
        return fallback
    # A model that ignores "title only" and writes a sentence must not put a
    # paragraph in the rail.
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_TITLE_CHARS else flat[: MAX_TITLE_CHARS - 1].rstrip() + "…"
