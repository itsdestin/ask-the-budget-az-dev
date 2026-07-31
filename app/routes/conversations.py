"""AI Mode's HTTP surface: conversations, their SSE turns, and status.

Three routes (the frozen Plan 4 contract):

  POST /api/conversations             -> a conversation id + inline health
  POST /api/conversations/{id}/messages -> the turn, streamed as SSE
  GET  /api/ai/status                 -> availability, tier copy, usage

`/api/ai/status` lives here rather than in its own module because it answers
the same question the create route answers inline ("can AI Mode run right
now?") from the same two sources — `harness.settings` and `harness.ledger`.
Splitting them would mean two places to keep the wording straight.

WHAT THIS MODULE DOES NOT DO: it does not talk to a model provider, count
tokens, or decide what a turn costs. `harness.session.HarnessSession` owns
all of that; this is transport. The one rule that keeps it that way is the
over-limit decision documented on `post_message`.
"""
from __future__ import annotations

import getpass
import json
import os
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.background import BackgroundTask

from harness.constants import DEFAULT_TIER
from harness.ledger import check_limit
from harness.settings import ai_available, load_settings

router = APIRouter()

# How many conversations one app process keeps alive at once.
#
# Conversations are per-machine and in-memory by design (Plan 4 accepts "no
# persistence across restarts"), but "in-memory" must not mean "forever": each
# HarnessSession holds a full message history AND an httpx connection pool, and
# this process can run for a week. 40 is far above what one analyst opens in a
# day and far below anything that matters for memory. Eviction is LRU over IDLE
# conversations only — see ConversationRegistry.
MAX_CONVERSATIONS = 40

# S16's analyst-facing copy, verbatim from the spec. It lives SERVER-side so
# Plan 5's admin page renders the same sentences as the composer's tier toggle
# without either one re-typing them. `description` is the spec's sentence
# whole; `examples` is the same text split out so a UI can render a list
# without slicing a string it doesn't own.
TIER_COPY: dict[str, dict[str, Any]] = {
    "standard": {
        "label": "Standard",
        "default": True,
        "description": (
            "for quick lookups — e.g. 'how much did we spend on X last year?' "
            "or 'did we appropriate money for xyz in FY 2020?'"
        ),
        "examples": [
            "how much did we spend on X last year?",
            "did we appropriate money for xyz in FY 2020?",
        ],
    },
    "deep_research": {
        "label": "Deep Research",
        "default": False,
        "description": (
            "for open-ended, historical, broad-scope research — e.g. "
            "'a comprehensive accounting of appropriated vs actual "
            "expenditures for all border-enforcement programs across the past "
            "10 fiscal years'"
        ),
        "examples": [
            "a comprehensive accounting of appropriated vs actual "
            "expenditures for all border-enforcement programs across the past "
            "10 fiscal years"
        ],
    },
}

# Overrides the OS username. Exists for tests and for a dev running two
# "analysts" side by side — NOT as an auth mechanism.
USER_ENV_VAR = "JLBC_USER"


def current_user() -> str:
    """Who is asking, per spec S11: the Windows username of this process.

    There is no authentication and this is not pretending to be any. S11 is
    explicit that per-user cost tracking is "not real security" — the app is
    installed per machine (S7) and launched by the person sitting at it (S8),
    so the process owner IS the analyst. Anyone who can set an environment
    variable can call themselves someone else; the ledger is an accounting
    tool for a single office, not an access-control boundary, and building a
    login screen on top of a local-only app would be theater that makes it
    LOOK like one.

    Falls back to "" (which `Settings.limit_for` resolves to the org default)
    rather than raising: an unnameable user should lose accurate accounting,
    not the ability to ask a question.
    """
    override = os.environ.get(USER_ENV_VAR)
    if override:
        return override
    try:
        return getpass.getuser()
    except Exception:  # noqa: BLE001 — no username source on this host
        return ""


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


@dataclass
class _Conversation:
    """One live conversation: its session plus the bookkeeping the registry
    needs to decide who may be evicted and who may take a turn."""

    id: str
    session: Any
    corpus: str
    # Touched on every turn; the LRU eviction order and nothing else.
    last_used_at: float = field(default_factory=time.monotonic)
    # True from the moment a turn is accepted until its SSE stream ends.
    busy: bool = False


class ConversationRegistry:
    """The in-process conversation table.

    THREAD SAFETY IS NOT OPTIONAL HERE. FastAPI runs `def` handlers in a
    threadpool, so two requests really can be inside this object at the same
    time — and the turn guard is a test-and-set (is it busy? then mark it
    busy), which is exactly the shape that goes wrong without a lock. Every
    mutation below is under `_lock`; `close()` on an evicted session is called
    OUTSIDE it, because a network hiccup inside httpx's shutdown must not
    freeze every other conversation in the office.

    What is deliberately NOT built here, and why: no background sweeper thread
    (nothing to reclaim between requests that the LRU cap doesn't reclaim on
    the next create), no idle TTL (a conversation an analyst leaves open over
    lunch is still theirs), no shutdown hook (the app is installed and
    launched per machine — the connection pools die with the process, and a
    lifespan handler would buy nothing), and no persistence (Plan 4 accepts
    in-memory; Plan 5 owns any lifecycle beyond this).
    """

    def __init__(self, limit: int | None = None) -> None:
        self._lock = threading.Lock()
        self._items: dict[str, _Conversation] = {}
        self._limit = limit

    @property
    def limit(self) -> int:
        # Read late rather than captured at construction so a test (or a
        # future setting) can change the cap without rebuilding the app.
        return self._limit if self._limit is not None else MAX_CONVERSATIONS

    def add(self, entry: _Conversation) -> None:
        with self._lock:
            self._items[entry.id] = entry
            victims = self._overflow_victims()
            for victim in victims:
                del self._items[victim.id]
        for victim in victims:
            _close_quietly(victim.session)

    def _overflow_victims(self) -> list[_Conversation]:
        """Least-recently-used IDLE conversations over the cap. Caller holds
        the lock.

        A conversation with a turn in flight is NEVER evicted, even if that
        pushes the table over the cap: `HarnessSession.close()` deliberately
        does not take the turn lock, so closing a live one kills the analyst's
        answer mid-sentence to save memory we are not actually short of. Going
        over the cap is the lesser harm — and it says so on stderr, because a
        table that stays over the cap means something is leaking `busy`.
        """
        overflow = len(self._items) - self.limit
        if overflow <= 0:
            return []
        idle = sorted(
            (c for c in self._items.values() if not c.busy),
            key=lambda c: c.last_used_at,
        )
        victims = idle[:overflow]
        if len(victims) < overflow:
            print(
                f"app.routes.conversations: {len(self._items)} conversations "
                f"open (cap {self.limit}) but only {len(victims)} are idle — "
                "keeping the busy ones. If this persists, turns are not "
                "releasing their conversation.",
                file=sys.stderr,
            )
        return victims

    def begin_turn(self, conversation_id: str) -> _Conversation:
        """Claim a conversation for one turn. Raises the right HTTP error."""
        with self._lock:
            entry = self._items.get(conversation_id)
            if entry is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "That conversation is no longer open. Conversations "
                        "live only while the app is running — start a new one."
                    ),
                )
            if entry.busy:
                # A second POST for a conversation that is mid-answer is an
                # HTTP-level mistake (a double-submit, or two tabs), so it
                # gets an HTTP-level answer. HarnessSession would refuse the
                # re-entrant turn with an `_error` frame, but that would mean
                # opening a 200 SSE stream just to say "you shouldn't have
                # opened this" — a confusing thing for the UI to have to
                # unpick from a real model error.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This conversation is still answering the previous "
                        "question. Wait for it to finish before sending "
                        "another."
                    ),
                )
            entry.busy = True
            entry.last_used_at = time.monotonic()
            return entry

    def end_turn(self, entry: _Conversation) -> None:
        with self._lock:
            entry.busy = False
            entry.last_used_at = time.monotonic()

    def get(self, conversation_id: str) -> _Conversation | None:
        with self._lock:
            return self._items.get(conversation_id)


def _close_quietly(session: Any) -> None:
    close = getattr(session, "close", None)
    if close is None:
        return
    try:
        close()
    except Exception as err:  # noqa: BLE001
        # An eviction failing must not fail the request that triggered it.
        print(
            f"app.routes.conversations: closing a conversation failed "
            f"({type(err).__name__}: {err}) — its connections may leak until "
            "the app restarts.",
            file=sys.stderr,
        )


def default_session_factory(
    conversation_id: str, *, corpus: str, tier: str, user: str
) -> Any:
    """Build the real tool loop. Imported lazily so tests that inject a fake
    session never pay for (or depend on) the retrieval stack behind it.

    Settings are read HERE, at conversation-create time, so an admin who fixes
    the API key mid-session helps the next conversation without a restart. An
    already-open conversation keeps the settings it was built with — the UI
    creates a conversation per thread, so the blast radius is one thread.
    """
    from harness.session import HarnessSession

    return HarnessSession(
        conversation_id, corpus=corpus, tier=tier, user=user,
        settings=load_settings(),
    )


def _registry(request: Request) -> ConversationRegistry:
    return request.app.state.conversations


def _session_factory(request: Request) -> Callable[..., Any]:
    return request.app.state.session_factory


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class CreateConversationBody(BaseModel):
    corpus: str = Field(default="budget", pattern="^(budget|fiscal_notes)$")


class MessageBody(BaseModel):
    text: str
    # Every NEW inquiry defaults to Standard (S16); the toggle sends the tier
    # per message because an analyst may escalate mid-thread.
    tier: str = Field(default=DEFAULT_TIER, pattern="^(standard|deep_research)$")


@router.post("/api/conversations")
def create_conversation(body: CreateConversationBody, request: Request) -> dict:
    """Open a conversation and say, inline, whether AI Mode can actually run.

    The health block is returned here rather than left to a second request
    because the UI needs it before it can render the composer, and a separate
    round-trip is a second thing that can be forgotten or race.

    It reports the DEFAULT tier's availability: that is the tier this
    conversation starts in, and `/api/ai/status` carries the per-tier detail
    for a UI that wants to dim one toggle rather than the whole feature.
    """
    ok, reason = ai_available(load_settings(), DEFAULT_TIER)
    conversation_id = uuid.uuid4().hex
    session = _session_factory(request)(
        conversation_id, corpus=body.corpus, tier=DEFAULT_TIER,
        user=current_user(),
    )
    _registry(request).add(
        _Conversation(id=conversation_id, session=session, corpus=body.corpus)
    )
    health: dict[str, Any] = {"ok": ok}
    if reason:
        health["reason"] = reason
    return {
        "conversation_id": conversation_id,
        "health": health,
        "tier_default": DEFAULT_TIER,
    }


def _sse(frame: dict) -> str:
    """One `ProviderEvent` as an SSE frame.

    `json.dumps` escapes newlines, which is load-bearing and not incidental:
    a raw newline inside `data:` would split one frame into two and the
    browser would try to parse half a JSON object.
    """
    return f"data: {json.dumps(frame, ensure_ascii=False)}\n\n"


def _turn_frames(
    registry: ConversationRegistry,
    entry: _Conversation,
    text: str,
    tier: str,
) -> Iterator[str]:
    """The whole route body: pull frames from the session, wrap, release.

    `stream.close()` in the `finally` is the important line. It raises
    GeneratorExit inside `HarnessSession.stream_turn`, which is where that
    class repairs a turn abandoned mid-tool-call — without it, a conversation
    whose stream ended early keeps an assistant `tool_calls` message with no
    replies in its history and EVERY later turn 400s at the provider. One
    closed tab, one dead conversation.
    """
    stream = entry.session.stream_turn(text, tier=tier)
    try:
        for frame in stream:
            yield _sse(frame)
    finally:
        stream.close()
        registry.end_turn(entry)


def _release_turn(
    registry: ConversationRegistry,
    entry: _Conversation,
    frames: Iterator[str],
) -> None:
    """Close the SSE generator once the request is over, however it ended.

    THIS IS NOT BELT-AND-BRACES; it is the only reliable path. Starlette never
    closes a response's body iterator itself — it relies on the iterator being
    garbage-collected — and on the disconnect path the iterator is caught in a
    reference cycle, so nothing runs until the cyclic collector happens to
    come round. Measured: after a simulated hang-up, `_turn_frames`' `finally`
    had NOT run, and only fired after an explicit `gc.collect()`. On a server
    that is minutes of a model still streaming (and still billing) into a
    closed socket, with the conversation stuck `busy` so the analyst who
    reopens the tab gets a 409.

    A `BackgroundTask` is the hook Starlette does guarantee: it runs after the
    response finishes AND after a client disconnect (ASGI spec_version 2.3,
    which is what uvicorn reports). Under a future spec_version >= 2.4 server
    the disconnect path raises `ClientDisconnect` before background tasks run,
    and cleanup would fall back to garbage collection — worth re-checking when
    that arrives.
    """
    try:
        frames.close()
    except Exception as err:  # noqa: BLE001
        # Closing a generator that is somehow still running raises rather than
        # cleaning up. Never let that fail the request that is already over.
        print(
            f"app.routes.conversations: could not close the stream for "
            f"conversation {entry.id} ({type(err).__name__}: {err}).",
            file=sys.stderr,
        )
    # Belt to the generator's braces: if `frames` never started (a client that
    # hung up before the first frame), its `finally` never ran either, and the
    # conversation would stay busy for the life of the process.
    registry.end_turn(entry)


@router.post("/api/conversations/{conversation_id}/messages")
def post_message(conversation_id: str, body: MessageBody, request: Request):
    """Run one turn, streamed as Server-Sent Events.

    OVER-LIMIT (S19) IS NOT CHECKED HERE, deliberately. The plan calls for a
    "402-shaped" refusal, and a limit check before the stream opens would
    allow a literal HTTP 402 — but `HarnessSession` already runs
    `check_limit` before its first provider call, and a second check here
    would mean two code paths deciding the same thing. The moment those two
    disagree (a month rolls over between them; one gets the wording from
    `LimitStatus.message` and the other re-derives it) the analyst is told two
    different stories about their own spending. One check, in the layer that
    owns the money, surfacing as the contract's terminal `_error` frame
    carrying the ledger's exact S19 sentence.

    The tradeoff accepted: the refusal rides a 200 response. The UI reads it
    the same way it reads every other terminal frame, and `/api/ai/status`
    already gives it the numbers to disable the composer before a blocked user
    ever types.
    """
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="The question is empty.")
    registry = _registry(request)
    entry = registry.begin_turn(conversation_id)
    try:
        frames = _turn_frames(registry, entry, body.text, body.tier)
        response = StreamingResponse(
            frames,
            media_type="text/event-stream",
            headers={
                # `no-transform` matters as much as `no-cache`: a proxy that
                # helpfully compresses or rewrites the body would buffer it,
                # and a buffered token stream is a frozen screen.
                "Cache-Control": "no-cache, no-transform",
                "Connection": "keep-alive",
                # nginx (and other reverse proxies) buffer responses by
                # default, which would hold every frame until the turn ended.
                # Harmless on localhost, correct anywhere else.
                "X-Accel-Buffering": "no",
            },
            # See _release_turn: this is the ONLY reliable cleanup hook.
            background=BackgroundTask(_release_turn, registry, entry, frames),
        )
    except BaseException:
        # Nothing above should raise, but a conversation stuck `busy` forever
        # would be unusable for the rest of the app's life — far worse than
        # whatever failed here.
        registry.end_turn(entry)
        raise
    return response


@router.get("/api/ai/status")
def ai_status() -> dict:
    """Whether AI Mode is usable, the tier copy, and this user's spend so far.

    `available` is "is ANY tier usable", because that is what the AI Mode
    toggle gates: an admin who has wired up Standard but not Deep Research
    should not have the whole feature dimmed. `reason` explains the default
    tier's failure when nothing is usable — with no key, that is the single
    honest sentence for both tiers anyway.
    """
    settings = load_settings()
    tiers: dict[str, Any] = {}
    for name, copy in TIER_COPY.items():
        ok, reason = ai_available(settings, name)
        # Copy the dict: TIER_COPY is process-wide and must not pick up a
        # per-request `available` flag.
        tiers[name] = {**copy, "available": ok, "reason": reason}

    available = any(tier["available"] for tier in tiers.values())
    body: dict[str, Any] = {"available": available, "tiers": tiers}
    if not available:
        body["reason"] = tiers[DEFAULT_TIER]["reason"]

    try:
        limit = check_limit(current_user(), settings)
        body["user_usage"] = {
            "month_usd": limit.month_usd,
            "limit_usd": limit.limit_usd,
            # One flag for "say something about spending", covering both the
            # 80% heads-up and the hard block. The mapping is the ledger's,
            # not this route's, so the boundary is defined in one place.
            "warned": limit.status in ("warn", "blocked"),
        }
    except Exception as err:  # noqa: BLE001
        # The ledger already fails open on an unreadable share; anything that
        # still escapes must not take the availability answer down with it —
        # the UI needs that to decide whether to show AI Mode at all.
        print(
            f"app.routes.conversations: usage snapshot unavailable "
            f"({type(err).__name__}: {err}).",
            file=sys.stderr,
        )
        body["user_usage"] = {"month_usd": None, "limit_usd": None,
                              "warned": False}
    return body
