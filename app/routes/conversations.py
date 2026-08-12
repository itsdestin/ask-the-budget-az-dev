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

import json
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

from app import identity
from harness import history
from harness import titles
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
#
# Coincidence worth knowing rather than rediscovering: 40 is also AnyIO's
# default worker-thread count, and every in-flight SSE stream holds one of
# those threads inside its blocking `next()`. So ~40 SIMULTANEOUS turns would
# also be the point where unrelated requests start queueing behind them. Both
# numbers sit far above one office's real load (the app is installed and
# launched per machine), so neither is tuned — but if one is ever raised, look
# at the other.
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

# Identity moved to app/identity.py in Plan 5 Task 1 — it was never
# conversation-specific, and the admin/usage/claim routes need it too.
# Both names are re-bound here rather than merely imported for local use:
# nothing outside this module imports them today (verified by grep), but
# they were public names on this module for all of Plan 4, and leaving the
# aliases costs two lines versus breaking an import path someone's
# in-flight branch may already use.
USER_ENV_VAR = identity.USER_ENV_VAR
current_user = identity.current_user


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
    # Which turn `busy` belongs to. Incremented by begin_turn; end_turn only
    # acts when handed the CURRENT token. See end_turn for why that matters.
    turn_token: int = 0
    # The turn a stop was requested for but that had not started yet, so the
    # interrupt could not stick. 0 = none pending. See request_stop.
    pending_stop_token: int = 0


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

    def begin_turn(self, conversation_id: str) -> tuple[_Conversation, int]:
        """Claim a conversation for one turn. Raises the right HTTP error.

        Returns the entry AND the token that identifies this turn; every
        release has to hand that token back.
        """
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
            entry.turn_token += 1
            entry.last_used_at = time.monotonic()
            return entry, entry.turn_token

    def end_turn(self, entry: _Conversation, token: int) -> None:
        """Release the conversation — but ONLY if `token` is still the turn
        that holds it.

        A turn releases TWICE: once when the SSE generator's body is exhausted
        (Starlette advances it one step past the last frame to learn it is
        done) and again from the background task after the response is over.
        Between those two the client already holds `_done` and can legitimately
        POST its next question — so an unconditional second release clears the
        NEXT turn's flag. That is not cosmetic: an un-busied live conversation
        can be evicted by the LRU cap, which calls `HarnessSession.close()` on
        a turn in flight (documented to raise inside it), and a third POST
        would reach a session that is already streaming and get the harness's
        generic re-entrancy `_error` instead of the clean 409 above.

        Stale releases are dropped silently: they are the normal steady state,
        not an anomaly worth a log line.
        """
        with self._lock:
            if entry.turn_token != token:
                return
            entry.busy = False
            entry.last_used_at = time.monotonic()

    def request_stop(self, conversation_id: str) -> tuple[_Conversation, bool]:
        """Mark a stop for whichever turn currently holds the conversation.

        Returns the entry and whether a turn was actually running — read under
        the lock, so the answer cannot be stale by the time the caller uses it.

        THE RACE THIS EXISTS FOR: `begin_turn` marks the conversation busy and
        the route returns straight away, but `HarnessSession.stream_turn` does
        not clear its interrupt flag until Starlette first advances the
        response body — after an HTTP round trip, an ASGI response-start and a
        threadpool dispatch. A stop landing in that window sets a flag the turn
        then wipes on its way in, and the turn runs on as though nobody pressed
        anything: no error, no frame, no log line. Recording the turn's TOKEN
        here lets `_turn_frames` re-apply the interrupt once the turn has
        demonstrably started (see `_apply_pending_stop`), which closes the
        window rather than narrowing it.
        """
        with self._lock:
            entry = self._items.get(conversation_id)
            if entry is None:
                raise HTTPException(
                    status_code=404,
                    detail=(
                        "That conversation is no longer open, so there is "
                        "nothing to stop."
                    ),
                )
            was_running = entry.busy
            if was_running:
                entry.pending_stop_token = entry.turn_token
            return entry, was_running

    def take_pending_stop(self, entry: _Conversation, token: int) -> bool:
        """Consume a stop recorded for `token`, if there is one.

        Token-scoped like `end_turn`: a stop recorded for a turn that has
        already ended must never fire on the next question the analyst asks.
        """
        with self._lock:
            if entry.pending_stop_token != token:
                return False
            entry.pending_stop_token = 0
            return True

    def get(self, conversation_id: str) -> _Conversation | None:
        with self._lock:
            return self._items.get(conversation_id)

    def get_or_add(
        self, conversation_id: str, entry_factory: Callable[[], _Conversation]
    ) -> tuple[_Conversation, bool]:
        """Atomically get-or-create a conversation entry.

        The `create_conversation` resume path needs to check-then-add under
        the lock: a resumed id is not unique like uuid4, so it can already
        be in the registry (the analyst reopened a chat they already
        continued this session). Doing that as `get` + `add` would race
        under concurrency (two tabs resuming the same chat), so this method
        does both under `_lock` and returns `(entry, created)`. The entry
        factory is called only when the id is NOT found, so a live session
        is never replaced and its httpx client is never leaked.
        """
        with self._lock:
            existing = self._items.get(conversation_id)
            if existing is not None:
                return existing, False
            entry = entry_factory()
            self._items[entry.id] = entry
            victims = self._overflow_victims()
            for victim in victims:
                del self._items[victim.id]
        for victim in victims:
            _close_quietly(victim.session)
        return entry, True


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
    conversation_id: str, *, corpus: str, tier: str, user: str,
    history: list[dict] | None = None,
) -> Any:
    """Build the real tool loop. Imported lazily so tests that inject a fake
    session never pay for (or depend on) the retrieval stack behind it.

    Settings are read HERE, at conversation-create time, so an admin who fixes
    the API key mid-session helps the next conversation without a restart. An
    already-open conversation keeps the settings it was built with — the UI
    creates a conversation per thread, so the blast radius is one thread.

    `history` is forwarded ONLY when resuming a stored chat; a fresh
    conversation passes nothing and gets the default (empty list).
    HarnessSession.__init__ already accepts it.
    """
    from harness.session import HarnessSession

    return HarnessSession(
        conversation_id, corpus=corpus, tier=tier, user=user,
        settings=load_settings(),
        history=history,
        corpus_map=_corpus_map_snapshot(corpus),
    )


def _corpus_map_snapshot(corpus: str) -> str | None:
    """The inventory table for this conversation's prompt (spec N1/N3).

    Read ONCE here, at conversation-create time, and held for the
    conversation's life — see HarnessSession's `_corpus_map` comment.

    Degrades to None (the prompt renders its fallback sentence) on ANY
    failure, because a map is an aid and a conversation is the product: a
    corrupt or missing sidecar must not be able to stop the office asking
    questions. That is the map's own design — spec N1's error handling.
    """
    try:
        from harness.corpus_map import build_corpus_map

        return build_corpus_map(corpus)
    except Exception as err:  # noqa: BLE001 — see the docstring
        print(f"conversations: corpus map unavailable — {err}", file=sys.stderr)
        return None


def _registry(request: Request) -> ConversationRegistry:
    return request.app.state.conversations


def _session_factory(request: Request) -> Callable[..., Any]:
    return request.app.state.session_factory


def _is_first_turn(messages: list) -> bool:
    """True when `messages` holds only a conversation's opening exchange.

    persist_turn uses this to tell "first save of a brand-new conversation"
    (nothing on disk yet — always create) from "continuation whose file was
    deleted mid-turn" (the analyst deleted it — do not resurrect).

    The discriminator is the USER-message count, and only that: the first
    turn contributes exactly one user message, and every later turn appends
    another, so one user message IS the first persist regardless of how the
    assistant replied. (A first turn that called tools is [user, assistant-
    tool_calls, tool, assistant-answer] — TWO assistant messages on the very
    first turn — so an assistant-message count would misread a tool-using
    first turn as a deleted continuation and skip writing it. The user count
    has no such ambiguity.)
    """
    users = sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "user")
    return users <= 1


def persist_turn(entry: _Conversation) -> None:
    """Write this conversation's transcript to the analyst's own disk.

    Called on EVERY turn teardown, including an aborted one — a cancelled
    turn is still a turn the analyst had.

    Swallows its own errors on purpose. History is a convenience; a full
    disk or a locked file must never turn a working answer into a failed
    one. The cost of being wrong here is one missing chat in a list, which
    is visible and survivable.
    """
    try:
        # getattr, not entry.session.history: the session_factory seam does
        # not oblige a session to keep a history list, and a fake that
        # doesn't must be a no-op rather than an exception this function
        # then has to swallow and print about.
        messages = getattr(entry.session, "history", None)
        if messages is None:
            return
        # ONE TRANSACTION, not a load and a save that merely happen to be
        # adjacent. `history.save` takes the id's lock, which makes the WRITE
        # atomic and does nothing at all for the read-modify-write around it:
        # a rename landing between the load and the save was reverted, and
        # its `title_is_manual` flag cleared with it. Held only for the two
        # file operations — never across the title call below.
        with history.transaction(entry.id):
            existing = history.load(entry.id)
            # A continuation whose file is GONE from disk was deleted out from
            # under the live session (the rail lets the analyst delete mid-turn).
            # Writing now would resurrect it as an untitled ghost — the same
            # ghost-row bug the client fixed, one layer down. A FIRST persist is
            # always existing-is-None (nothing on disk yet) and carries exactly
            # one user message; a continuation always carries at least two. So
            # "no file on disk" + "more than one user message" = the analyst
            # deleted it, and the delete should win. (See _is_first_turn for why
            # the user count, not the assistant count, is the discriminator.)
            if existing is None and not _is_first_turn(messages):
                return
            already_titled = bool(existing and (existing.title or existing.title_is_manual))
            now = history.now_iso()
            history.save(
                history.Transcript(
                    id=entry.id,
                    title=existing.title if existing else "",
                    title_is_manual=existing.title_is_manual if existing else False,
                    corpus=entry.corpus,
                    created_at=existing.created_at if existing else now,
                    updated_at=now,
                    messages=list(messages),
                )
            )
            first_q = next((m.get("content", "") for m in messages
                            if m.get("role") == "user"), "")
            first_a = next((m.get("content", "") for m in messages
                            if m.get("role") == "assistant" and m.get("content")), "")

        if already_titled:
            return
        # Title only once, on the first completed exchange, and never over a
        # title the analyst set themselves.
        #
        # OUTSIDE the transaction, and it must stay outside: this is a
        # blocking HTTP call of up to _TIMEOUT_S, and holding the chat's write
        # lock across it would stall a rail rename or delete for the same
        # twenty seconds.
        #
        # It is safe HERE and nowhere earlier in the teardown: persist_turn's
        # single call site is at the END of _release_turn, after
        # registry.end_turn has released the conversation, in a BackgroundTask
        # (a threadpool, not the event loop). Move it earlier and the
        # conversation stays `busy` for the duration, so the analyst's next
        # question gets a 409 from begin_turn.
        title = titles.generate_title(first_q, first_a, user=current_user())
        # `set_title_if_absent` re-reads under the lock and writes ONE field.
        # The old code wrote the whole Transcript object it had loaded BEFORE
        # the call above, which — reproduced 2026-08-11 — erased a turn that
        # completed during the call, resurrected a chat deleted during it, and
        # reverted a rename made during it.
        history.set_title_if_absent(entry.id, title)
    except Exception as exc:                      # noqa: BLE001
        print(f"jlbc-insight: could not save chat history: {exc}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


class CreateConversationBody(BaseModel):
    corpus: str = Field(default="budget", pattern="^(budget|fiscal_notes)$")
    # Continuing a stored chat reuses THIS route rather than getting its own.
    # A parallel "resume" endpoint would be a second code path doing the same
    # job, and the two would drift; reusing create is what makes a rehydrated
    # conversation indistinguishable from a fresh one downstream.
    resume_from: str | None = None


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

    stored = None
    if body.resume_from:
        try:
            stored = history.load(body.resume_from)
        except ValueError:
            raise HTTPException(status_code=400, detail="bad conversation id")

        # A resumed id is NOT unique the way uuid4() is, so it can already be
        # in the registry — the analyst reopened a chat they already
        # continued this session, or has it open in a second tab.
        #
        # THE REGISTRY IS CONSULTED BEFORE THE 404, deliberately. Raising on
        # "no transcript on disk" first meant that deleting a chat's row from
        # the rail killed the LIVE conversation the analyst still had open:
        # every subsequent message answered 404 "no such conversation" for a
        # session sitting healthy in memory, with no way back except starting
        # over. Reproduced 2026-08-11. A live session outranks its own
        # bookkeeping; only "no session AND no transcript" is a real 404.
        live = _registry(request).get(body.resume_from)
        if stored is None and live is None:
            raise HTTPException(status_code=404, detail="no such conversation")

        if live is not None:
            if live.busy:
                # Same answer begin_turn gives a double-submit, for the same
                # reason: this conversation is mid-answer.
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This conversation is still answering the previous "
                        "question. Wait for it to finish before reopening it."
                    ),
                )
            # The durable record wins over memory when they disagree. One
            # process serves one machine, so this should not happen — but
            # if it ever does, answering from a shorter in-memory history
            # silently drops turns the analyst can see on their own screen,
            # and re-seeding an IDLE session's list costs one comparison.
            if stored is not None:
                in_memory = getattr(live.session, "history", None)
                if in_memory is not None and len(stored.messages) > len(in_memory):
                    in_memory[:] = list(stored.messages)
            health: dict[str, Any] = {"ok": ok}
            if reason:
                health["reason"] = reason
            return {
                "conversation_id": live.id,
                "health": health,
                "tier_default": DEFAULT_TIER,
                "resumed": True,
            }

    # Keep the ORIGINAL id so continuing a chat updates it rather than
    # forking a second transcript with the same content.
    conversation_id = stored.id if stored else uuid.uuid4().hex
    # The stored corpus wins over whatever the client asked for: the
    # transcript was recorded against one corpus and answering it out of the
    # other would be wrong, cited and confident.
    corpus = stored.corpus if stored else body.corpus

    # `history=` is passed ONLY when resuming. Passing it unconditionally
    # would break every session_factory that does not accept it — which is
    # all of them today: default_session_factory (:327) and the ~25 call
    # sites behind tests/test_conversations_route.py's `factory_for` (:119).
    extra = {"history": list(stored.messages)} if stored else {}

    def _build() -> _Conversation:
        session = _session_factory(request)(
            conversation_id, corpus=corpus, tier=DEFAULT_TIER,
            user=current_user(),
            **extra,
        )
        return _Conversation(id=conversation_id, session=session, corpus=corpus)

    # `get_or_add`, not `add`. The `get` above and an `add` here are two trips
    # to the registry with a gap between them, and a resumed id is guessable
    # and shared: two tabs reopening the same chat both saw `live is None`,
    # both built a session, and the second `add` replaced the first outright —
    # never closing its httpx client, and leaving /stop and the next message
    # addressing a different object than the one still streaming and billing.
    # `get_or_add` does the check and the insert under the registry's own
    # lock. It was written for exactly this and was never wired up.
    entry, _created = _registry(request).get_or_add(conversation_id, _build)
    conversation_id = entry.id
    health: dict[str, Any] = {"ok": ok}
    if reason:
        health["reason"] = reason
    return {
        "conversation_id": conversation_id,
        "health": health,
        "tier_default": DEFAULT_TIER,
        "resumed": stored is not None,
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
    token: int,
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

    `stream_turn(...)` is called INSIDE the `try` on purpose. It cannot raise
    today — it is a generator function, so calling it runs no code — but
    nothing in the `session_factory` seam enforces that, and this generator's
    body runs after ASGI response-start: an exception here is re-raised by
    Starlette before it reaches the background task, so if this `finally` were
    not on the stack either, the conversation would be wedged `busy` for the
    life of the process (permanently 409ing, and permanently holding one of
    the MAX_CONVERSATIONS slots, since a busy conversation is never evicted).
    """
    stream = None
    try:
        stream = entry.session.stream_turn(text, tier=tier)
        for frame in stream:
            yield _sse(frame)
            # AFTER the first frame the session has provably passed its own
            # `_interrupted.clear()`, so a stop that arrived too early to
            # stick can now be re-applied and produce the designed abort
            # (`user_interrupt` + a cancelled-tool back-fill) instead of
            # vanishing. Cheap: one lock acquisition per frame, against a
            # stream that is already crossing a socket.
            _apply_pending_stop(registry, entry, token)
    finally:
        # Guarded rather than a bare `stream.close()`: the seam does not
        # oblige a session to hand back a generator, and a missing `close`
        # must not mask whatever exception brought us here.
        closer = getattr(stream, "close", None)
        if closer is not None:
            closer()
        registry.end_turn(entry, token)


def _apply_pending_stop(
    registry: ConversationRegistry, entry: _Conversation, token: int
) -> None:
    """Re-issue a stop that landed before this turn could hear it."""
    if not registry.take_pending_stop(entry, token):
        return
    interrupt = getattr(entry.session, "interrupt", None)
    if interrupt is not None:
        interrupt()


def _release_turn(
    registry: ConversationRegistry,
    entry: _Conversation,
    token: int,
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
    # conversation would stay busy for the life of the process. Scoped to this
    # turn's token, so by now it is usually a no-op — see end_turn.
    registry.end_turn(entry, token)
    # Persist the transcript AFTER releasing the conversation: persist_turn
    # may hang an LLM call off the same function (Task 5), and doing that
    # before end_turn leaves the conversation `busy`, so the analyst's next
    # question gets a 409 from begin_turn — a working app that appears to
    # refuse input for no visible reason. A sync BackgroundTask runs in
    # Starlette's threadpool, so blocking here does not stall the event loop.
    persist_turn(entry)


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
    entry, token = registry.begin_turn(conversation_id)
    try:
        frames = _turn_frames(registry, entry, token, body.text, body.tier)
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
            background=BackgroundTask(
                _release_turn, registry, entry, token, frames
            ),
        )
    except BaseException:
        # Nothing above should raise, but a conversation stuck `busy` forever
        # would be unusable for the rest of the app's life — far worse than
        # whatever failed here.
        registry.end_turn(entry, token)
        raise
    return response


@router.post("/api/conversations/{conversation_id}/stop")
def stop_turn(conversation_id: str, request: Request) -> dict:
    """Ask the running turn to stop. Additive to the frozen contract.

    `HarnessSession.interrupt()` is the only method on that class safe to call
    from another thread, and it is what produces the DESIGNED abort: the turn
    ends with `stopReason: "user_interrupt"`, every dispatched tool call gets a
    cancelled-result back-fill so the history stays legal, and a retry backoff
    wakes immediately instead of sitting out its sleep. Closing the tab aborts
    a turn too, but via `GeneratorExit` — no terminal frame, no
    `user_interrupt`, nothing for the UI to render. Without this route that
    whole path is unreachable over HTTP.

    Stopping an IDLE conversation is deliberately allowed rather than a 409:
    the flag is cleared at the start of every turn, so a stop that races the
    END of an answer cannot poison the next question, and refusing it would
    just hand the UI a failure to explain for pressing a button that did
    nothing wrong. The inverse race — a stop that arrives before the turn it
    targets has started, which that same clear would swallow — is handled by
    `ConversationRegistry.request_stop`, which records the turn's token so
    `_turn_frames` can re-apply the interrupt once the turn is genuinely
    running.

    `stopped` reports whether a turn was actually running, read under the
    registry lock so it cannot be stale by the time it is serialized.
    """
    registry = _registry(request)
    entry, was_running = registry.request_stop(conversation_id)
    interrupt = getattr(entry.session, "interrupt", None)
    if interrupt is not None:
        # Outside the lock: `interrupt()` is the one HarnessSession method
        # meant to be called from another thread, and holding the registry
        # lock across a call into the session would put every other
        # conversation behind it.
        interrupt()
    return {"stopped": was_running}


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
