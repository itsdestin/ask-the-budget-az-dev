"""The tool loop (Plan 4 Task 6, spec S3).

This is the piece that used to be a whole desktop application. Before
Plan 4, a turn went: web app -> WebSocket -> YouCoded -> a PTY running
Claude Code -> an MCP server process -> HTTP -> a FastAPI sidecar. S3
replaces all of it with one function that talks to an OpenAI-compatible
chat-completions endpoint (OpenRouter by default, S13) and runs the
tools in-process.

What this module owns:
  * the conversation's message history and what slice of it fits in a
    request (`_context_window`),
  * one streaming HTTP call per step, with retries (`_open_stream`),
  * turning the provider's SSE chunks into `ProviderEvent` dicts the web
    UI already knows how to render (`_stream_completion`),
  * running the model's tool calls through `harness.tools.ToolExecutor`
    and feeding the results back,
  * the per-turn accumulator that becomes the `_done` frame (the audit
    product: final answer, citations, retrieved chunk ids, tool calls).

**The renderer contract is binding.** `webapp`'s chat reducer is a port
of `web/state/chat-reducer.ts`, and two of its rules will break silently
— no exception, no log, just wrong pixels — if this module gets them
wrong:

  1. `assistant_text_delta.text` is the FULL accumulated text for that
     `uuid`, not the newest fragment. The reducer finds the block with
     that uuid and REPLACES its text. Emitting true deltas renders the
     last token only, or a stutter, depending on where the uuid changes.
  2. `tool_result.output` is a JSON-encoded STRING. The tool views parse
     it themselves (they have to — they render different shapes per
     tool). Handing them an object makes every tool card read "no
     output".

Threading: one `HarnessSession` serves ONE conversation and one turn at
a time (a re-entrant turn is refused, see `_turn_lock`). `interrupt()`
is the single method safe to call from another thread — everything else
assumes the caller is the thread driving the turn. There is no
module-level mutable state: this process serves the whole office, so
anything cached at module scope would be shared across analysts. (The
Node original had exactly that bug in its first-call cap; `harness.tools`
documents the fix.)
"""
from __future__ import annotations

import json
import sys
import threading
import time
import traceback
import uuid as uuid_module
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Callable, Iterator, Sequence

import httpx

from harness.constants import DEFAULT_TIER, TIER_BUDGETS
from harness.ledger import check_limit as _ledger_check_limit
from harness.ledger import record_usage as _ledger_record_usage
from harness.settings import Settings, ai_available

# ---------------------------------------------------------------------------
# Tunables
# ---------------------------------------------------------------------------

# Wait between retries, in seconds. Three retries after the first
# attempt: enough to ride out a rate-limit blip or a provider restart,
# short enough that an analyst staring at a spinner gives up at roughly
# the same time we do (7s of sleeping, plus the failed attempts).
RETRY_BACKOFF_SECONDS: tuple[float, ...] = (1.0, 2.0, 4.0)

# A provider is allowed to ask us to wait, but not to park a turn
# forever — a `Retry-After: 3600` would leave the analyst watching a
# spinner for an hour with no way to know why.
MAX_RETRY_AFTER_SECONDS = 30.0

# S22 — which models need a cache breakpoint SPELLED OUT.
#
# Two families of prompt caching exist behind OpenRouter's one API.
# OpenAI-, DeepSeek- and Moonshot-style providers cache long prefixes
# automatically: send the same bytes twice and the second call is
# discounted, with nothing to opt into. Anthropic-style providers cache
# NOTHING unless the request marks where the reusable part ends, with a
# `cache_control` breakpoint on a content part.
#
# Substring match, not a prefix match, because the same model reaches us
# under more than one id — `anthropic/claude-opus-5` through OpenRouter,
# a bare `claude-opus-5` through a proxy an admin points S15 at. Marking
# a model that did not need it is harmless (the field is ignored);
# missing one that did means paying full price forever with no symptom.
ANTHROPIC_STYLE_MODEL_MARKERS: tuple[str, ...] = ("anthropic/", "claude-")

# How much history we are willing to send, measured in CHARACTERS of
# serialized JSON.
#
# THIS IS AN ESTIMATE AND IS MEANT TO BE ONE. A real token count needs a
# tokenizer, this plan is allowed exactly one new dependency (httpx), and
# the right tokenizer depends on which model an admin picked anyway. At
# roughly 3 characters per token — deliberately pessimistic; ordinary
# English prose runs nearer 4, and pessimistic means we cut EARLY rather
# than discovering the ceiling as a provider 400 — 360,000 characters is
# on the order of 120K tokens, which leaves comfortable room for the
# system prompt and the model's reply inside a 200K-token context. If a
# future model is smaller, pass `context_chars` at construction; nothing
# here assumes the default.
DEFAULT_CONTEXT_CHARS = 360_000

# The model's `finish_reason` vocabulary -> the `stopReason` the UI shows.
#
# "tool_calls" normally never reaches the lookup (the loop continues
# instead of stopping). It is mapped anyway as a BACKSTOP, not as the
# fix: the real guard is in `_run_turn`, which returns an `_error` when a
# step finishes with tool_calls and none of them survived assembly. This
# entry only ensures that if some future path ever does reach the lookup
# with "tool_calls", it cannot fall through to the "end_turn" default and
# read to the analyst as a finished answer.
#
# Read-only for the same reason harness/constants.py wraps its tables:
# one process serves the whole office, so a stray write here would
# change every conversation's stop reasons at once.
_FINISH_REASONS = MappingProxyType(
    {
        "stop": "end_turn",
        "length": "max_tokens",
        "content_filter": "content_filter",
        "error": "error",
        "tool_calls": "tool_use",
    }
)

# What a tool call that never ran says to the model on the NEXT turn.
# Deliberately explicit about the uncertainty: a bare "cancelled" reads
# as "it failed", and a model that believes a search failed will often
# re-run it and then apologize for the delay. What it needs to know is
# that the result is UNKNOWN and that re-calling is fine.
_CANCELLED_TOOL_RESULT = json.dumps(
    {
        "ok": False,
        "cancelled": True,
        "error": (
            "The analyst interrupted the turn before this tool call ran, so "
            "its result is unknown. Do not assume it succeeded or failed. "
            "Call it again if you still need it."
        ),
    }
)


# What an old tool result says once it has been traded away for context
# room. Same voice as the cancelled result above, and the same reason:
# the model must be able to tell "I never got this" from "this failed".
_OVERSIZED_TOOL_RESULT = json.dumps(
    {
        "ok": False,
        "dropped": True,
        "error": (
            "This result was too large to resend with the rest of the "
            "conversation, so its contents are no longer available. Call the "
            "tool again if you still need it."
        ),
    }
)


def _now_ms() -> int:
    """Event timestamps are JS-facing (`TranscriptEvent.timestamp` is a
    `number`), so milliseconds since the epoch, not a float of seconds."""
    return int(time.time() * 1000)


def _new_uuid() -> str:
    return str(uuid_module.uuid4())


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class ProviderError(RuntimeError):
    """A failure the analyst has to be told about, carrying text worth
    showing them. Never raised out of `stream_turn` — it is converted to
    an `_error` frame."""


def _extract_error_message(status: int, body: str) -> str:
    """Dig the informative message out of an error body.

    OpenRouter wraps upstream failures: its own `error.message` is a
    generic "Provider returned error" and the sentence that actually
    tells you what to fix ("max_tokens: 200000 > 64000") sits in
    `error.metadata.raw` — usually as a JSON STRING containing the
    upstream provider's own error envelope. A naive `error.message` read
    is why "the AI just says it errored" was unfixable without a network
    trace, so this walks all the way down and falls back one level at a
    time rather than giving up at the first shape it doesn't recognize.
    """
    detail: str | None = None
    try:
        parsed = json.loads(body)
    except ValueError:
        parsed = None

    if isinstance(parsed, dict):
        error = parsed.get("error")
        if isinstance(error, str):
            detail = error
        elif isinstance(error, dict):
            metadata = error.get("metadata")
            raw = metadata.get("raw") if isinstance(metadata, dict) else None
            if isinstance(raw, str) and raw.strip():
                # `raw` is the upstream body verbatim. Usually JSON with
                # its own {"error": {"message": ...}}; sometimes plain
                # text. Try the nested read, keep the string otherwise.
                detail = _extract_error_message(status, raw) if raw.lstrip().startswith("{") else raw
            if not detail:
                message = error.get("message")
                if isinstance(message, str) and message.strip():
                    detail = message
        if not detail:
            message = parsed.get("message")
            if isinstance(message, str) and message.strip():
                detail = message

    if not detail:
        detail = body.strip()[:500] or f"HTTP {status}"
    return detail


def _provider_error(status: int, body: str) -> ProviderError:
    err = ProviderError(
        f"The model provider returned an error (HTTP {status}): "
        f"{_extract_error_message(status, body)}"
    )
    # Carried structurally rather than re-parsed out of the message text:
    # `_is_dead_model_error` below decides whether to fall back to another
    # model, and basing that on a substring of a human sentence would make
    # the fallback break the day the wording is improved.
    err.status = status
    return err


# Phrases a provider uses when the MODEL is the problem — retired,
# renamed, never existed, or no longer served by anyone OpenRouter routes
# to. Matched case-insensitively against the extracted error detail.
#
# WHY a phrase list and not just "any 404": a 404 can also mean a
# hand-edited base_url pointing at a path that doesn't exist, and
# silently switching models because an admin typo'd the endpoint would
# hide the real problem behind a working-looking answer from the wrong
# model. Both signals have to agree.
_DEAD_MODEL_PHRASES = (
    "no endpoints found",
    "not a valid model",
    "no allowed providers",
    "model not found",
    "is not a valid model id",
    "unknown model",
    "deprecated",
    "has been retired",
    "no longer available",
)


def _is_dead_model_error(err: ProviderError) -> bool:
    """Is this failure "the configured model is gone" (S13)?

    Deliberately conservative. A false positive here answers the analyst
    from a model their admin did not choose — quietly, at a different
    price. A false negative just shows the honest provider error, which is
    what the app did before this existed. When unsure, be wrong the second
    way.
    """
    status = getattr(err, "status", None)
    if status not in (400, 404):
        return False
    text = str(err).lower()
    return any(phrase in text for phrase in _DEAD_MODEL_PHRASES)


# ---------------------------------------------------------------------------
# S13 runtime model fallback
# ---------------------------------------------------------------------------
# THE OVERRIDE IS PER-PROCESS AND IN MEMORY. It is deliberately NOT a
# settings write: three office machines hitting the same dead model would
# otherwise stage three concurrent writes to one settings.json on an SMB
# share, and the last writer wins over whatever the admin happened to be
# editing at that moment. The admin's configuration stays exactly as they
# left it; the notices feed is how they find out a fallback is in effect
# and can choose a new model deliberately.

# (tier, configured_model) -> the model actually being used instead.
_model_overrides: dict[tuple[str, str], str] = {}
# (tier, from_model, to_model) already reported. A dead model fails on
# EVERY turn, so without this the notices file would gain a row per
# question, all day, and bury everything else in the feed.
_notified_transitions: set[tuple[str, str, str]] = set()
_fallback_lock = threading.Lock()


def reset_model_overrides() -> None:
    """Drop the per-process fallback state.

    Test-only in practice, but also the honest answer to "how do I undo a
    fallback?": restart the app. The override lives for the process's
    lifetime by design — re-trying a model that was retired an hour ago,
    once per turn, would spend an analyst's time on a request already
    known to fail.
    """
    with _fallback_lock:
        _model_overrides.clear()
        _notified_transitions.clear()


def _fallback_candidates(tier: str, current: str) -> list[str]:
    """That tier's recommendation order, minus the model that just failed.

    The order is `harness.catalog.RECOMMENDATIONS` — the same list the
    admin page shows — so the model an analyst silently lands on is one an
    admin would have been offered anyway, not an arbitrary pick.
    """
    from harness.catalog import RECOMMENDATIONS

    return [
        rec.id
        for rec in RECOMMENDATIONS
        if rec.tier_hint == tier and rec.id != current
    ]


# ---------------------------------------------------------------------------
# Streaming state
# ---------------------------------------------------------------------------


@dataclass
class _PartialToolCall:
    """One tool call being assembled across SSE chunks.

    `arguments` arrives as string FRAGMENTS — a chunk may carry
    `'{"que'` and the next `'ry": "ADC"}'` — so the only correct
    handling is concatenation, keyed by the fragment's `index`. Not by
    `id`: the id typically appears on the first fragment only, and never
    on the continuation fragments that carry the bulk of the arguments.
    """

    id: str = ""
    name: str = ""
    arguments: str = ""


@dataclass
class _StepResult:
    """What one provider call produced. Filled in by `_stream_completion`
    as it yields events, then read by the loop."""

    uuid: str = ""
    text: str = ""
    tool_calls: list[_PartialToolCall] = field(default_factory=list)
    finish_reason: str | None = None
    usage: dict[str, Any] | None = None
    model: str | None = None
    interrupted: bool = False


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------


class HarnessSession:
    """One conversation's tool loop.

    ONE INSTANCE PER CONVERSATION, held for the conversation's life —
    for the same reason `ToolExecutor` is per-conversation (the
    progressive-retrieval cap is instance state), plus this object owns
    the message history.

    Everything the tests need to replace is a constructor seam:
    `executor` (the tools), `transport` (httpx's), `system_prompt` (Task
    7's builder is imported lazily otherwise), `tools` (the schemas),
    `sleep`, `check_limit` and `record_usage` (the ledger). Passing none
    of them wires up the real stack.
    """

    def __init__(
        self,
        conversation_id: str,
        corpus: str = "budget",
        tier: str = DEFAULT_TIER,
        user: str = "",
        settings: Settings | None = None,
        executor: Any = None,
        transport: httpx.BaseTransport | None = None,
        *,
        system_prompt: str | None = None,
        prompt_builder: Callable[..., str] | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        context_chars: int = DEFAULT_CONTEXT_CHARS,
        sleep: Callable[[float], Any] | None = None,
        check_limit: Callable[..., Any] = _ledger_check_limit,
        record_usage: Callable[..., None] = _ledger_record_usage,
    ) -> None:
        self.conversation_id = conversation_id
        self.corpus = corpus
        self.tier = tier
        self.user = user
        self.settings = settings if settings is not None else Settings()

        # Public and mutable on purpose: Task 8 keeps the session in a
        # registry and may want to inspect or seed the transcript, and
        # the tests seed it directly. It is the conversation's real
        # record — `_context_window` never mutates it, it only picks a view.
        self.history: list[dict[str, Any]] = list(history or [])

        self._executor = executor
        self._transport = transport
        self._system_prompt = system_prompt
        self._prompt_builder = prompt_builder
        # Keyed by tier: the tier toggle is per-message (S16) and
        # build_system_prompt() takes `tier`, so caching on nothing
        # meant turn 2 ran the Deep Research model under Standard's
        # prompt. One entry per tier the conversation actually used.
        self._prompt_by_tier: dict[str, str] = {}
        self._tools = list(tools) if tools is not None else None
        self._context_chars = context_chars
        self._check_limit = check_limit
        self._record_usage = record_usage

        self._client: httpx.Client | None = None
        # Set by interrupt() from the UI thread; cleared at the start of
        # every turn so a stale abort can't kill the next question.
        self._interrupted = threading.Event()
        # Non-reentrant guard: two turns interleaving on one history
        # would produce a message list neither of them intended.
        self._turn_lock = threading.Lock()
        # Retry backoff waits on the interrupt flag rather than
        # time.sleep: `Event.wait(n)` returns the instant the flag is
        # set, so pressing stop during a `Retry-After: 30` wait ends the
        # turn now instead of thirty seconds from now. (Tests inject a
        # recorder here to assert the schedule without real waiting.)
        self._sleep: Callable[[float], Any] = (
            sleep if sleep is not None else self._interrupted.wait
        )

    # -- lifecycle --------------------------------------------------------

    def interrupt(self) -> None:
        """Stop the current turn as soon as the loop notices.

        The only method meant to be called from a different thread than
        the one running the turn. Granularity is one SSE line or one
        tool call — we do not kill an in-flight tool mid-execution,
        because a half-finished LanceDB read has no cancellation story
        and a torn tool result is worse than a slightly late stop.
        """
        self._interrupted.set()

    def close(self) -> None:
        """Release the HTTP connection pool. Safe to call twice.

        CONTRACT: call this only when the conversation is finished, from
        whichever thread owns Task 8's registry. It deliberately does NOT
        take the turn lock — a registry eviction must never block behind
        a five-minute Deep Research turn. Closing the client under a live
        turn raises inside that turn, which since the SSE hardening
        surfaces as an honest `_error` frame rather than a truncated
        stream; that is the intended (if blunt) way to shut a runaway
        conversation down. To stop a turn politely, call `interrupt()`
        and let it end on its own."""
        if self._client is not None:
            self._client.close()
            self._client = None

    # -- turn -------------------------------------------------------------

    def send_turn(
        self,
        text: str,
        on_event: Callable[[dict[str, Any]], None] | None = None,
        *,
        tier: str | None = None,
    ) -> dict[str, Any]:
        """Run one turn, pushing each `ProviderEvent` to `on_event`.

        Returns the terminal frame (`_done` or `_error`) rather than
        emitting it, so a caller that only wants the audit product does
        not have to filter the stream.
        """
        terminal: dict[str, Any] = {}
        for event in self.stream_turn(text, tier=tier):
            if event["type"] in ("_done", "_error"):
                terminal = event
            elif on_event is not None:
                on_event(event)
        return terminal

    def stream_turn(self, text: str, *, tier: str | None = None) -> Iterator[dict[str, Any]]:
        """Yield this turn's `ProviderEvent` dicts, then exactly one
        terminal frame (`_done` or `_error`).

        A generator rather than a callback-only API because Task 8's SSE
        route is itself a generator: `for frame in session.stream_turn(...)
        : yield f"data: {json.dumps(frame)}\\n\\n"` is the whole route
        body, with no queue and no worker thread between the model and
        the browser.

        `tier` overrides the session's tier for this turn onward (the
        composer's tier toggle is per-message, S16). It selects the model
        and the step cap. NOTE: the executor keeps the tier it was BUILT
        with, which only matters for `deep_dive` — and `deep_dive` only
        has an effect on the first search of a conversation, before any
        toggle could have happened.
        """
        if not self._turn_lock.acquire(blocking=False):
            yield self._error_frame(
                "A turn is already running in this conversation. Wait for it "
                "to finish, or stop it first."
            )
            return
        try:
            if tier:
                self.tier = tier
            self._interrupted.clear()
            yield from self._run_turn(text)
        except GeneratorExit:
            # THE CONSUMER WENT AWAY MID-STREAM. Task 8's route is
            # `for frame in session.stream_turn(...)`, so a closed browser
            # tab makes Starlette stop draining and Python throws
            # GeneratorExit at whatever yield is live. If that was the
            # `tool_use` yield, the assistant `tool_calls` message is
            # already in history and its replies never will be — and this
            # session lives in Task 8's registry for the conversation's
            # life, so EVERY later turn would 400. Someone closes a tab
            # and the conversation is dead.
            #
            # Repair, then re-raise. Never yield while unwinding a
            # GeneratorExit: Python turns that into a RuntimeError and
            # the repair is what actually matters here.
            self._repair_history()
            raise
        except Exception as err:  # noqa: BLE001 — see below
            # Every non-ProviderError failure used to propagate into the
            # SSE generator and abort the HTTP response mid-stream: no
            # `_error`, no `turn_complete`, and (per the reducer note in
            # `_run_turn`) an assistant turn left open to adopt the next
            # answer's text. Sources are ordinary, not exotic — a flaky
            # share under `check_limit`, a lazy import that isn't built
            # yet, a hand-edited `base_url`. `harness/settings.py` goes
            # out of its way never to crash on a config typo; failing
            # loudly here would undo that for the whole office.
            #
            # NOT BaseException: KeyboardInterrupt/SystemExit must still
            # take the process down.
            self._repair_history()
            # The traceback is the admin's only breadcrumb — the analyst
            # gets one sentence, and nothing else records what happened.
            print(
                f"harness.session: turn failed in conversation "
                f"{self.conversation_id!r} — {type(err).__name__}: {err}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)
            yield _event("turn_complete", stopReason="error")
            yield self._error_frame(
                f"Something went wrong answering this question "
                f"({type(err).__name__}: {err}). If it keeps happening, ask "
                "your admin to check the AI settings."
            )
        finally:
            self._turn_lock.release()

    # -- the loop ---------------------------------------------------------

    def _run_turn(self, text: str) -> Iterator[dict[str, Any]]:
        settings = self.settings

        # S19: the spend check happens BEFORE any HTTP, and its wording
        # is the ledger's, verbatim — re-deriving it here would give the
        # office two subtly different "you're over your limit" messages.
        limit = self._check_limit(self.user, settings)
        if getattr(limit, "status", "allowed") == "blocked":
            yield self._error_frame(limit.message or "Your monthly AI usage limit is reached.")
            return

        available, reason = ai_available(settings, self.tier)
        if not available:
            yield self._error_frame(f"AI answers are unavailable — {reason}.")
            return

        configured_model = settings.tiers[self.tier].model
        # S13: if this model already failed as retired earlier in this
        # process, start on the replacement instead of re-discovering that
        # once per turn, forever.
        model = self._effective_model(configured_model)
        tried_models = {model}
        max_steps = self._max_steps()
        accumulator = _Accumulator()

        yield _event("user_message", text=text)
        self.history.append({"role": "user", "content": text})

        stop_reason = "end_turn"
        usage_totals = _UsageTotals()
        incomplete_note: str | None = None

        for _step in range(max_steps):
            if self._interrupted.is_set():
                # Interrupted between steps: nothing is half-written, so
                # there is nothing to back-fill.
                yield _event("user_interrupt", kind="plain")
                stop_reason = "user_interrupt"
                break

            # S22: this pair is the CACHEABLE PREFIX — the same bytes on
            # every step of every turn of every conversation, so the
            # provider can serve it from cache at roughly a tenth of the
            # input price. Nothing dynamic may be built into it; dynamic
            # context belongs in the user/tool messages that follow.
            # `tests/test_harness_prompt_caching.py` pins that property.
            prompt_text = self._system_prompt_text()
            system = self._system_message(prompt_text, model)
            # `reserved` is measured on the PROMPT TEXT, never on the
            # wire shape: when the prompt is wrapped in content parts for
            # a cache breakpoint, `len(content)` is 1 and the history
            # window would silently grow by the whole prompt's budget.
            messages = [system] + self._context_window(self.history, reserved=len(prompt_text))
            result = _StepResult(uuid=_new_uuid())

            yield _event("assistant_thinking", uuid=result.uuid)
            try:
                yield from self._stream_completion(messages, model, result, accumulator)
            except ProviderError as err:
                # S13: a retired model degrades AI Mode to a DIFFERENT
                # model, never to a dead feature. Retrying this same step
                # costs one of the tier's steps, which is the honest
                # accounting — it really is another attempt.
                replacement = (
                    self._fall_back(configured_model, model, tried_models)
                    if _is_dead_model_error(err) else None
                )
                if replacement is not None:
                    model = replacement
                    tried_models.add(model)
                    continue

                # The turn dies here. History keeps the user message and
                # whatever completed before the failure; it is still a
                # legal request (a failed step appends nothing).
                #
                # turn_complete FIRST, then the error: the renderer keeps
                # an assistant turn "open" until it sees turn_complete,
                # and an open turn adopts the NEXT turn's text blocks as
                # its own. Without this, one provider hiccup makes every
                # later answer render inside the failed bubble.
                yield _event("turn_complete", stopReason="error", model=model)
                yield self._error_frame(str(err))
                return
            finally:
                # In a `finally`, not after the call: a provider that
                # streams a usage chunk and THEN fails in-band has
                # already billed those tokens, and so has one abandoned
                # by a closed tab. On a shared key with per-user monthly
                # caps, silently unrecorded spend is precisely what the
                # ledger exists to prevent. `_bill` no-ops when no usage
                # was reported.
                self._bill(result, usage_totals, model)

            if result.interrupted:
                yield from self._finish_interrupted(result)
                stop_reason = "user_interrupt"
                break

            # An assistant message with neither text nor tool calls says
            # nothing and is rejected outright by some providers on the
            # next request — don't record one.
            if result.text or result.tool_calls:
                self.history.append(_assistant_message(result))

            if not result.tool_calls:
                if result.finish_reason == "tool_calls":
                    # The model meant to call tools and every one of them
                    # was unusable (see the drop in _stream_completion).
                    # Ending as "end_turn" would hand the analyst an
                    # empty answer wearing a completed turn's clothes.
                    yield _event("turn_complete", stopReason="error", model=model)
                    yield self._error_frame(
                        "The model tried to use a tool but its request arrived "
                        "incomplete, so nothing could be run and no answer was "
                        "produced. Ask again."
                    )
                    return
                stop_reason = _FINISH_REASONS.get(result.finish_reason or "stop", "end_turn")
                break

            cancelled = False
            for call in result.tool_calls:
                if self._interrupted.is_set():
                    cancelled = True
                # Even a cancelled call gets a tool_result event and a
                # history entry: the UI has already drawn a running tool
                # card for it (it saw the tool_use), and the provider
                # rejects a request whose assistant tool_calls have no
                # replies.
                yield from self._run_tool_call(call, accumulator, cancelled=cancelled)
            if cancelled:
                yield _event("user_interrupt", kind="tool-use")
                stop_reason = "user_interrupt"
                break
        else:
            # The `for` ran to completion: the model kept calling tools
            # until it hit the tier's budget. The analyst has to be told
            # — an answer that just stops is indistinguishable from a
            # finished one — but NOT in assistant prose. A synthetic
            # assistant_text_delta is field-for-field identical to model
            # output: it renders in a speech bubble as the model, and it
            # would land in `finalAnswer`, the field an offline auditor
            # reads as "what the model said". This is a provenance
            # project; that field carries model text only. The fact
            # travels as `stopReason: "max_steps"` (on both terminal
            # frames) plus this out-of-band note, which the UI renders as
            # a system notice the way SystemHealthBanner does.
            stop_reason = "max_steps"
            incomplete_note = (
                f"Stopped after {max_steps} tool calls without finishing. "
                "This answer is incomplete."
            )

        usage = usage_totals.as_turn_usage()
        yield _event("turn_complete", stopReason=stop_reason, model=model, usage=usage)
        yield accumulator.done_frame(stop_reason, usage, usage_totals.cost, incomplete_note)

    # -- S13 model fallback -----------------------------------------------

    def _effective_model(self, configured: str) -> str:
        """The configured model, or the replacement already chosen for it.

        Keyed on (tier, configured) rather than tier alone so that an admin
        who fixes the setting mid-session is obeyed immediately: the new
        model id has no override entry, so it is used as typed.
        """
        with _fallback_lock:
            return _model_overrides.get((self.tier, configured), configured)

    def _fall_back(
        self, configured: str, failed: str, tried: set[str]
    ) -> str | None:
        """Pick the next model for this tier, or None to surface the error.

        Returns None — meaning "show the analyst the real provider error" —
        in three cases:

        - **custom endpoint (S15).** There is no recommendation list for
          someone else's server; a model id from OpenRouter's catalog
          would almost certainly not exist there, so guessing would
          replace one honest error with a more confusing one.
        - **nothing left to try.** Every candidate for this tier has
          already failed in this turn.
        - **the failed model is the last resort.** Same thing.
        """
        if self.settings.provider.provider == "custom":
            return None

        for candidate in _fallback_candidates(self.tier, configured):
            if candidate in tried:
                continue
            with _fallback_lock:
                _model_overrides[(self.tier, configured)] = candidate
                transition = (self.tier, failed, candidate)
                first_time = transition not in _notified_transitions
                if first_time:
                    _notified_transitions.add(transition)
            if first_time:
                # One notice per DISTINCT transition, not per call: a dead
                # model fails on every turn, and a notice per question
                # would bury every other notice in the feed by lunchtime.
                from harness.notices import KIND_MODEL_FALLBACK, record_notice

                record_notice(
                    KIND_MODEL_FALLBACK,
                    f"The {self.tier} model “{failed}” is no longer available "
                    f"from the provider, so AI Mode is using “{candidate}” "
                    "instead. Pick a replacement on the Admin page when you "
                    "get a chance — this fallback only lasts until the app "
                    "is restarted.",
                )
            return candidate
        return None

    # -- one provider call -------------------------------------------------

    def _stream_completion(
        self,
        messages: list[dict[str, Any]],
        model: str,
        result: _StepResult,
        accumulator: _Accumulator,
    ) -> Iterator[dict[str, Any]]:
        """Stream one `chat.completions` response, yielding events and
        filling `result` in place.

        Writing into a caller-owned `_StepResult` (rather than returning
        one) is what lets this be a generator: the events have to reach
        the browser AS they arrive, and a generator cannot both yield
        events and return a value that `yield from` would surface.
        """
        partials: dict[int, _PartialToolCall] = {}
        response = self._open_stream(self._request_body(messages, model))
        if response is None:
            # Stopped during retry backoff — nothing streamed, nothing to
            # clean up; the caller's interrupt path closes the turn.
            result.interrupted = True
            return
        try:
            # A read timeout or a dropped connection HALFWAY through an
            # answer is an httpx exception, not an HTTP status — and it
            # is not retryable here, because the tokens already streamed
            # cannot be un-sent. Converting it to a ProviderError is what
            # turns "the SSE route crashed" into "the analyst is told the
            # connection dropped, under the partial answer they can see".
            for line in _guard_transport(response.iter_lines()):
                # Checked BEFORE the line is processed, so an interrupt
                # that lands while this line was in flight discards it
                # rather than half-applying a chunk we already decided to
                # abandon.
                if self._interrupted.is_set():
                    result.interrupted = True
                    break

                line = line.strip()
                # Blank lines are SSE frame separators; `:`-prefixed
                # lines are comments — OpenRouter sends
                # ": OPENROUTER PROCESSING" keepalives every few seconds
                # on a slow model and parsing one as JSON would abort a
                # perfectly healthy stream.
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                payload = line[len("data:") :].strip()
                if payload == "[DONE]":
                    break
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    # One unparseable frame is not worth killing a turn
                    # that is otherwise streaming fine; it IS worth a log
                    # line, because it means the provider is emitting
                    # something this parser does not model.
                    print(
                        f"harness.session: ignoring unparseable SSE frame in "
                        f"conversation {self.conversation_id!r}: {payload[:200]}",
                        file=sys.stderr,
                    )
                    continue
                if not isinstance(chunk, dict):
                    continue

                # An error can arrive INSIDE a 200 stream (the upstream
                # provider failed after OpenRouter had already opened the
                # response). Silently ending the turn here is how "the
                # answer just stopped mid-sentence" happens.
                if chunk.get("error"):
                    raise ProviderError(
                        "The model provider returned an error: "
                        + _extract_error_message(200, json.dumps(chunk))
                    )

                if chunk.get("model"):
                    result.model = chunk["model"]
                if isinstance(chunk.get("usage"), dict):
                    result.usage = chunk["usage"]

                for choice in chunk.get("choices") or []:
                    delta = choice.get("delta") or {}
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        result.text += content
                        # FULL accumulated text, same uuid every time —
                        # the reducer replaces the block, it does not
                        # append. See this module's docstring.
                        accumulator.record_text(result.uuid, result.text)
                        yield _event(
                            "assistant_text_delta",
                            uuid=result.uuid,
                            text=result.text,
                            model=result.model or model,
                        )
                    for fragment in delta.get("tool_calls") or []:
                        _merge_tool_call_fragment(partials, fragment)
                    if choice.get("finish_reason"):
                        result.finish_reason = choice["finish_reason"]
        finally:
            response.close()

        # Ordered by the provider's own `index`, which is the order the
        # model intends them to run in. A call missing an `id` or a
        # `name` cannot be run OR answered (a tool message must carry a
        # `tool_call_id`), so it is dropped — but LOUDLY: dropping it
        # silently is how a turn ends as a successful, empty answer.
        #
        # A PARTIAL drop (some calls survived) still proceeds, and the
        # model is never told one vanished — there is no id to answer
        # with, so there is no way to tell it. That is a deliberate
        # trade: the surviving calls return real results the model can
        # answer from, and failing the whole turn would throw those away
        # over a provider glitch. Only a TOTAL drop fails the turn, in
        # `_run_turn`, because then there is nothing to answer from at
        # all. The stderr line is the only record either way.
        for _, call in sorted(partials.items()):
            if call.id and call.name:
                result.tool_calls.append(call)
            else:
                print(
                    f"harness.session: dropping tool call with no id/name in "
                    f"conversation {self.conversation_id!r} "
                    f"(id={call.id!r}, name={call.name!r}) — it cannot be "
                    "answered. The turn fails only if NO call survived; "
                    "otherwise the others run and the model is never told "
                    "this one vanished.",
                    file=sys.stderr,
                )

    def _request_body(self, messages: list[dict[str, Any]], model: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "tools": self._tool_schemas(),
            "stream": True,
            # The portable way to get token counts out of a STREAMING
            # OpenAI-compatible response — without it the final chunk
            # carries no usage at all and the ledger records nothing.
            "stream_options": {"include_usage": True},
        }
        if self.settings.provider.provider == "openrouter":
            # OpenRouter's vendor extension: adds the true `cost` in
            # dollars to the usage block (S19 needs dollars, not tokens).
            # Gated because a strict OpenAI-compatible server rejects
            # unknown top-level fields outright, and S15's custom
            # endpoint may be exactly that.
            body["usage"] = {"include": True}
        return body

    def _open_stream(self, body: dict[str, Any]) -> httpx.Response | None:
        """POST /chat/completions with retries; return the OPEN response,
        or None if the analyst stopped the turn during a backoff wait.

        Retries cover 429 (rate limited), 5xx (provider or upstream
        down) and transport errors (the office wifi blinked). A 4xx that
        is not 429 is a request WE built wrong — a bad model id, a
        malformed tool schema — and retrying it just spends three more
        seconds arriving at the same answer.
        """
        url = self.settings.provider.base_url.rstrip("/") + "/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.settings.provider.api_key}",
            "Content-Type": "application/json",
            # Shows up as the app name on OpenRouter's activity page, so
            # an admin auditing spend sees what the charges belong to.
            "X-Title": "JLBC Insight",
        }
        client = self._http_client()
        attempts = len(RETRY_BACKOFF_SECONDS) + 1
        last_error: str = ""
        for attempt in range(attempts):
            try:
                request = client.build_request("POST", url, json=body, headers=headers)
                response = client.send(request, stream=True)
            except (httpx.InvalidURL, ValueError) as err:
                # A hand-edited base_url with no scheme, or an empty one.
                # Surfaces as httpx.InvalidURL from build_request or, for
                # a scheme-less URL, as a plain ValueError from deep
                # inside send() — so both are caught here. Not retryable,
                # and worth naming the setting: the admin who broke it is
                # the only person who can fix it, and settings.py
                # deliberately never crashes on a config typo.
                raise ProviderError(
                    f"The configured AI endpoint is not a usable URL "
                    f"({self.settings.provider.base_url!r}): {err}. Ask your "
                    "admin to check the AI settings."
                ) from err
            except httpx.RequestError as err:
                last_error = f"could not reach the model provider: {err}"
                if attempt == attempts - 1:
                    raise ProviderError(last_error) from err
                self._sleep(RETRY_BACKOFF_SECONDS[attempt])
                if self._interrupted.is_set():
                    return None
                continue

            if response.status_code < 400:
                return response

            # Read and close before deciding — an unread streaming
            # response holds a pooled connection open. A body that fails
            # to download is not allowed to escape as a raw httpx error:
            # the STATUS is the fact that decides retry-or-not, and
            # losing the retry over a missing error message would be a
            # strictly worse outcome than an unhelpful message.
            try:
                text = response.read().decode("utf-8", errors="replace")
            except httpx.RequestError as err:
                text = f"(the error body could not be read: {err})"
            retry_after = _retry_after_seconds(response.headers.get("retry-after"))
            response.close()

            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == attempts - 1:
                raise _provider_error(response.status_code, text)
            # The provider's own instruction beats our schedule when it
            # gives one — it knows when the rate-limit window resets.
            delay = retry_after if retry_after is not None else RETRY_BACKOFF_SECONDS[attempt]
            self._sleep(delay)
            # Stop is honored during the wait, not after the next attempt.
            if self._interrupted.is_set():
                return None
        raise ProviderError(last_error or "the model provider could not be reached")

    def _http_client(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(
                transport=self._transport,
                # A long READ timeout on purpose: a big model can think
                # for a minute before the first token, and killing that
                # turn would be indistinguishable from a provider outage
                # to the analyst. Connect stays short — an unreachable
                # host should fail fast into the retry path.
                timeout=httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0),
            )
        return self._client

    # -- tools ------------------------------------------------------------

    def _run_tool_call(
        self, call: _PartialToolCall, accumulator: _Accumulator, *, cancelled: bool
    ) -> Iterator[dict[str, Any]]:
        parsed = _parse_tool_input(call.arguments)
        yield _event("tool_use", toolUseId=call.id, toolName=call.name, input=parsed)

        if cancelled:
            output, is_error = _CANCELLED_TOOL_RESULT, True
        else:
            # `ToolExecutor.execute` never raises and always returns a
            # JSON string — the raw `arguments` go in unparsed on
            # purpose, so the executor owns the "your JSON was
            # truncated" message instead of this loop inventing one.
            output = self._tool_executor().execute(call.name, call.arguments)
            is_error = _looks_like_error(output)

        yield _event("tool_result", toolUseId=call.id, output=output, isError=is_error)
        accumulator.record_tool(call, parsed, output, is_error)
        self.history.append(
            {
                "role": "tool",
                "tool_call_id": call.id,
                "name": call.name,
                "content": output,
            }
        )

    def _repair_history(self) -> int:
        """Back-fill a cancelled reply for every unanswered tool call.

        THE ONE DEFINITION of "legal history", shared by all three ways a
        turn can end early (stop pressed, consumer disconnected, an
        unexpected exception). An OpenAI-compatible history must never
        carry an assistant `tool_calls` id without a matching
        `{"role": "tool"}` reply: the next request is malformed and the
        provider 400s — which the analyst experiences as "the
        conversation is broken now", after doing nothing worse than
        pressing stop or closing a tab.

        Appending at the END is correct because a dangling assistant
        message is always the LAST thing in history when this runs — the
        loop appends the assistant message and its replies together, so
        the only way to see an unanswered call is to be interrupted
        between those two steps.

        Returns how many replies it invented, so a caller can tell
        whether anything was actually broken.
        """
        replied = {
            message.get("tool_call_id")
            for message in self.history
            if message.get("role") == "tool"
        }
        appended = 0
        for message in list(self.history):
            for call in message.get("tool_calls") or []:
                call_id = call.get("id")
                if not call_id or call_id in replied:
                    continue
                self.history.append(
                    {
                        "role": "tool",
                        "tool_call_id": call_id,
                        "name": (call.get("function") or {}).get("name", ""),
                        "content": _CANCELLED_TOOL_RESULT,
                    }
                )
                replied.add(call_id)
                appended += 1
        return appended

    def _finish_interrupted(self, result: _StepResult) -> Iterator[dict[str, Any]]:
        """Close out a turn stopped mid-stream, leaving valid history.

        Records whatever the model had produced, then hands the
        back-fill to `_repair_history`. No `tool_use` event was emitted
        for these calls (the stream was cut before the loop reached
        execution), so no `tool_result` event is emitted either — the UI
        never drew a card that would be left spinning. History still
        needs the replies.
        """
        if result.text or result.tool_calls:
            self.history.append(_assistant_message(result))
        self._repair_history()
        kind = "tool-use" if result.tool_calls else "plain"
        yield _event("user_interrupt", kind=kind)

    def _tool_executor(self) -> Any:
        if self._executor is None:
            # Imported lazily so `harness.session` stays importable —
            # and this test suite runnable — without the retrieval stack,
            # LanceDB or the ONNX models that `harness.tools` pulls in.
            from harness.tools import ToolExecutor

            self._executor = ToolExecutor(
                self.conversation_id, self.corpus, self.tier, user=self.user
            )
        return self._executor

    def _tool_schemas(self) -> list[dict[str, Any]]:
        if self._tools is None:
            from harness.tools import TOOLS

            self._tools = list(TOOLS)
        return self._tools

    # -- prompt, tiers, billing -------------------------------------------

    def _system_prompt_text(self) -> str:
        """The system prompt for the CURRENT tier, built once per tier.

        An explicit `system_prompt=` string wins for every tier (the
        simple test/embed seam). Otherwise the builder is called per
        tier, because `build_system_prompt(*, corpus, tier)` takes the
        tier by design — a conversation whose analyst flips the composer
        toggle mid-thread must not keep running the old tier's prompt
        against the new tier's model and step budget.

        This is a PURE FUNCTION of (corpus, tier) and must stay one. It
        is the bulk of the cacheable prefix (S22): ~40 KB resent on every
        step, up to 50 steps in a Deep Research turn. Anything that
        varies here — a timestamp, the user's name, the question — turns
        every request into a cache miss at roughly 10x the price, with no
        symptom anyone would notice except the bill.
        """
        if self._system_prompt is not None:
            return self._system_prompt
        prompt = self._prompt_by_tier.get(self.tier)
        if prompt is None:
            builder = self._prompt_builder
            if builder is None:
                # Task 7 owns the content; this module only owns the seam.
                from harness.prompt import build_system_prompt

                builder = build_system_prompt
            prompt = builder(corpus=self.corpus, tier=self.tier)
            self._prompt_by_tier[self.tier] = prompt
        return prompt

    def _system_message(self, prompt: str, model: str) -> dict[str, Any]:
        """The system prompt in the shape this provider wants it.

        Plain string for everyone except Anthropic-style models, which
        cache nothing unless the request says where the reusable part
        ends. For those, the prompt becomes a single content part
        carrying a `cache_control` breakpoint.

        ONE breakpoint is enough and is placed here deliberately.
        Anthropic orders a request tools-then-system-then-messages, so a
        breakpoint at the end of the system block covers the tool schemas
        as well — both halves of the prefix, in one marker.

        Gated on OpenRouter for the same reason `_request_body` gates
        `usage: {include: true}`: S15 lets an admin point this at any
        OpenAI-compatible server, and a strict one rejects unknown fields
        outright rather than ignoring them. A custom endpoint therefore
        gets the plain string, which every server understands.

        NOT CACHED between steps, on purpose: this builds two dicts, and
        caching it would be one more piece of state that could go stale
        when the tier (and therefore the model) changes mid-conversation.
        The prompt TEXT — the expensive part — is what gets cached, one
        entry per tier, in `_system_prompt_text`.
        """
        if self.settings.provider.provider != "openrouter":
            return {"role": "system", "content": prompt}
        if not any(marker in model for marker in ANTHROPIC_STYLE_MODEL_MARKERS):
            return {"role": "system", "content": prompt}
        return {
            "role": "system",
            "content": [
                {
                    "type": "text",
                    "text": prompt,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
        }

    def _max_steps(self) -> int:
        budget = TIER_BUDGETS.get(self.tier)
        if budget is None:
            # settings.json accepts arbitrary tier names, so a typo must
            # not take a conversation down. Standard is the conservative
            # fallback — a mis-typed tier gets the CHEAP budget, never
            # the expensive one. Same rule as harness/tools.py.
            print(
                f"harness.session: unknown tier {self.tier!r} — using "
                f"{DEFAULT_TIER!r} step budget.",
                file=sys.stderr,
            )
            budget = TIER_BUDGETS[DEFAULT_TIER]
        return int(budget["max_steps"])

    def _bill(self, result: _StepResult, totals: _UsageTotals, model: str) -> None:
        """Record one step's usage. Every step is a separate paid call.

        A ledger write failure is logged, never raised: by the time we
        get here the money is already spent, so failing the turn would
        cost the analyst their answer AND the dollars, and still not
        record the row. The loud stderr line is the compensating control
        — an admin whose share is unwritable needs to find out from the
        log, not from a mysteriously flat usage report.
        """
        if not result.usage:
            return
        usage = result.usage
        # S15: a custom endpoint reports no trustworthy cost, and the
        # ledger's contract is that `None` means "unknown", not "free".
        # The gate lives in ONE place — inside the totals — so the ledger
        # row and the `_done` frame cannot report different money.
        totals.add(usage, allow_cost=self.settings.provider.provider == "openrouter")
        cost = totals.last_cost
        try:
            self._record_usage(
                self.user,
                self.tier,
                result.model or model,
                _int_or_zero(usage.get("prompt_tokens")),
                _int_or_zero(usage.get("completion_tokens")),
                cost,
                # S22 visibility, not arithmetic: `cost` already reflects
                # the cache discount (it is OpenRouter's own exact
                # figure). This is how an admin can SEE whether caching
                # is working, which is otherwise unobservable — a broken
                # prefix looks exactly like a working one apart from the
                # bill.
                cached_tokens=totals.last_cache_read_tokens,
            )
        except Exception as err:  # noqa: BLE001 — see docstring
            print(
                f"harness.session: usage row NOT recorded for "
                f"{self.user!r} ({type(err).__name__}: {err}). The call still "
                "cost money — this month's totals will undercount.",
                file=sys.stderr,
            )

    # -- history ----------------------------------------------------------

    def _context_window(
        self, history: list[dict[str, Any]], reserved: int = 0
    ) -> list[dict[str, Any]]:
        """Choose the newest slice of `history` that fits the budget.

        THE RULE (three parts, all load-bearing):

        1. **Oldest-first.** Walk backwards from the newest message,
           keeping messages while the running character total fits. The
           recent turns are what the current question is about.

        2. **Never open on an orphaned tool reply.** A `{"role": "tool"}`
           message only means anything next to the assistant `tool_calls`
           message that requested it. If the cut lands between them the
           orphans are dropped too — the window is advanced past every
           leading tool message, WITHOUT an exemption for the newest one.
           (Dropping a tool reply while KEEPING its assistant call is
           impossible here: replies always come after their call, so a
           backwards walk reaches the reply first.)

        3. **Something legal always survives**, even alone over budget. A
           request with a truncated-away question is guaranteed nonsense;
           an over-long one at least gets a clear provider error naming
           the real problem. When rule 2 empties the window — every kept
           message was an orphan, which happens from step 2 onward when
           one tool result alone busts the budget — the fallback is the
           newest NON-tool message and everything after it, i.e. the
           assistant call together with its replies. Deliberately a
           legal PAIR rather than the newest message alone: rule 3 must
           not be allowed to re-introduce the orphan rule 2 just removed.
           That was the original bug — a `- 1` in the advance loop let
           "newest survives" quietly win, and from step 2 on (where
           history ends on a tool reply) the window could open on an
           orphan and the provider 400s the conversation.

           Two things the fallback does on top of "keep the pair", both
           because the pair alone is not a sane request:
           **it re-attaches the newest question** (a system prompt plus a
           tool result with nothing being asked is a confident-nonsense
           generator, and rule 3 exists to protect the question in the
           first place), and **it bounds the payload** — an assistant
           message with N parallel calls otherwise drags N results along
           regardless of the budget (measured at 1003x on a 10-call step
           with the ~50 KB analyze results `constants.py` describes).
           Oversized tool results are STUBBED, never dropped, so every
           `tool_call_id` still has its reply.

        Measured over `messages` only. The request also carries the tool
        SCHEMAS (~6 KB), which are not counted — a fixed overhead the
        budget's deliberate pessimism absorbs.

        The system prompt is not in `history` at all — it is prepended by
        the caller — so it is structurally impossible for this to drop
        it. That matters: it is ~700 lines and it is the entire reason
        the model cites anything. Its size arrives as `reserved` and
        comes off the budget, so "never dropped" doesn't quietly become
        "and never counted either".

        Measured in characters of serialized JSON, which is an ESTIMATE
        of token cost, not a count (see `DEFAULT_CONTEXT_CHARS`).
        Returns a new list; `history` is never mutated.
        """
        if not history:
            return []
        budget = max(self._context_chars - reserved, 0)
        kept: list[dict[str, Any]] = []
        used = 0
        for message in reversed(history):
            size = len(json.dumps(message, ensure_ascii=False))
            if kept and used + size > budget:
                break
            kept.append(message)
            used += size
        kept.reverse()

        start = 0
        while start < len(kept) and kept[start].get("role") == "tool":
            start += 1
        if start < len(kept):
            return kept[start:]
        return self._fallback_window(history, budget)

    def _fallback_window(
        self, history: list[dict[str, Any]], budget: int
    ) -> list[dict[str, Any]]:
        """Rule 3's pair-aware, question-carrying, bounded fallback."""
        # Walks the FULL history, not `kept`: the assistant call we need
        # may have been dropped by the budget walk.
        anchor = None
        for index in range(len(history) - 1, -1, -1):
            if history[index].get("role") != "tool":
                anchor = index
                break
        if anchor is None:
            # A history of nothing but tool replies is unreachable —
            # every conversation opens with a user message — but sending
            # it whole beats silently sending nothing at all.
            return list(history)

        window = history[anchor:]
        if not any(message.get("role") == "user" for message in window):
            for index in range(anchor - 1, -1, -1):
                if history[index].get("role") == "user":
                    window = [history[index]] + window
                    break
        return _bound_tool_payloads(window, budget)

    # -- frames -----------------------------------------------------------

    def _error_frame(self, message: str) -> dict[str, Any]:
        return {"type": "_error", "message": message}


# ---------------------------------------------------------------------------
# Free functions
# ---------------------------------------------------------------------------


def _event(event_type: str, uuid: str | None = None, **fields: Any) -> dict[str, Any]:
    """One `ProviderEvent` dict, shaped exactly like `web/lib/types.ts`.

    camelCase field names are not a style slip — these go over SSE
    straight into a TypeScript reducer that destructures `toolUseId`,
    `stopReason`, `isError`. snake_case here would silently render
    empty tool cards.
    """
    event: dict[str, Any] = {
        "type": event_type,
        "uuid": uuid or _new_uuid(),
        "timestamp": _now_ms(),
    }
    event.update({k: v for k, v in fields.items() if v is not None})
    return event


def _bound_tool_payloads(
    window: list[dict[str, Any]], budget: int
) -> list[dict[str, Any]]:
    """Stub oversized tool results until `window` fits the budget.

    Newest-first: the most recent search is the one the model is
    reasoning from, so older results give up their text first. The
    message itself always stays — replacing `content` keeps the
    `tool_call_id` pairing intact, which dropping the message would
    destroy (that is the whole reason this is a stub and not a delete).
    Non-tool messages are never touched: they are the question and the
    model's own words.
    """
    sizes = [len(json.dumps(message, ensure_ascii=False)) for message in window]
    if sum(sizes) <= budget:
        return window
    bounded = list(window)
    used = sum(
        size
        for message, size in zip(window, sizes)
        if message.get("role") != "tool"
    )
    for index in range(len(bounded) - 1, -1, -1):
        if bounded[index].get("role") != "tool":
            continue
        if used + sizes[index] <= budget:
            used += sizes[index]
            continue
        stub = {**bounded[index], "content": _OVERSIZED_TOOL_RESULT}
        bounded[index] = stub
        used += len(json.dumps(stub, ensure_ascii=False))
    return bounded


def _guard_transport(lines: Iterator[str]) -> Iterator[str]:
    """Re-raise a mid-stream transport failure as a ProviderError."""
    try:
        yield from lines
    except httpx.RequestError as err:
        raise ProviderError(
            f"The connection to the model provider dropped mid-answer: {err}"
        ) from err


def _merge_tool_call_fragment(
    partials: dict[int, _PartialToolCall], fragment: dict[str, Any]
) -> None:
    """Fold one streamed `delta.tool_calls[i]` fragment into its slot.

    Keyed by `index`, because that is the only field present on EVERY
    fragment — `id` and `function.name` typically arrive once, on the
    first fragment for a slot, and the continuation fragments carry
    nothing but more `arguments` text. Missing index falls back to the
    next free slot rather than dropping the fragment.
    """
    if not isinstance(fragment, dict):
        return
    slot = fragment.get("index")
    if not isinstance(slot, int):
        slot = len(partials)
    call = partials.setdefault(slot, _PartialToolCall())
    if isinstance(fragment.get("id"), str) and fragment["id"]:
        call.id = fragment["id"]
    function = fragment.get("function") or {}
    if isinstance(function.get("name"), str):
        # Concatenated, not assigned: names normally arrive whole, but a
        # provider that splits one costs nothing to support and an
        # assignment would keep only the last piece.
        call.name += function["name"]
    if isinstance(function.get("arguments"), str):
        call.arguments += function["arguments"]


def _assistant_message(result: _StepResult) -> dict[str, Any]:
    """The assistant turn as the provider wants it echoed back."""
    message: dict[str, Any] = {"role": "assistant", "content": result.text or None}
    if result.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in result.tool_calls
        ]
    return message


def _parse_tool_input(arguments: str) -> dict[str, Any]:
    """Tool arguments as an object for the UI's `tool_use.input`.

    Malformed JSON is NOT an error here — the executor gets the raw
    string and produces the actionable message. This only decides what
    the tool card can render, so a truncated argument blob is shown
    verbatim rather than dropping the card.
    """
    try:
        parsed = json.loads(arguments) if arguments.strip() else {}
    except ValueError:
        return {"arguments": arguments}
    return parsed if isinstance(parsed, dict) else {"arguments": arguments}


def _looks_like_error(output: str) -> bool:
    """`{"ok": false, ...}` — the executor's one failure envelope."""
    try:
        parsed = json.loads(output)
    except ValueError:
        return False
    return isinstance(parsed, dict) and parsed.get("ok") is False


def _retry_after_seconds(header: str | None) -> float | None:
    """`Retry-After` in seconds, clamped. Only the numeric form is
    honored — the HTTP-date form needs clock-skew handling for a header
    providers essentially never send in that shape."""
    if not header:
        return None
    try:
        value = float(header.strip())
    except ValueError:
        return None
    return max(0.0, min(value, MAX_RETRY_AFTER_SECONDS))


def _int_or_zero(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return int(value)


class _UsageTotals:
    """Token/dollar totals across every step of one turn."""

    def __init__(self) -> None:
        self.input_tokens = 0
        self.output_tokens = 0
        self.cache_read_tokens = 0
        self.cost: float | None = None
        self.last_cost: float | None = None
        # THIS step's cache reads, as opposed to the turn's running
        # total. The ledger records one row per step, and S22's whole
        # point is being able to see the per-step drop after step 1 —
        # which the running total would hide.
        self.last_cache_read_tokens = 0

    def add(self, usage: dict[str, Any], *, allow_cost: bool = True) -> None:
        """Fold one step's usage in. `allow_cost=False` (S15's custom
        endpoint) discards the reported cost entirely rather than
        recording it anywhere — this is the single gate both the ledger
        row and the `_done` frame read, so they cannot disagree about
        whether dollars are known."""
        self.input_tokens += _int_or_zero(usage.get("prompt_tokens"))
        self.output_tokens += _int_or_zero(usage.get("completion_tokens"))
        details = usage.get("prompt_tokens_details")
        # A provider that reports no cache details means "we know of
        # none", which is 0. `cost_usd` is the only field where None
        # carries the distinct meaning "unknown".
        self.last_cache_read_tokens = (
            _int_or_zero(details.get("cached_tokens")) if isinstance(details, dict) else 0
        )
        self.cache_read_tokens += self.last_cache_read_tokens
        cost = usage.get("cost") if allow_cost else None
        self.last_cost = float(cost) if isinstance(cost, (int, float)) else None
        if self.last_cost is not None:
            self.cost = (self.cost or 0.0) + self.last_cost

    def as_turn_usage(self) -> dict[str, int]:
        """`TurnUsage` — camelCase, four fields, no cost.

        `cacheCreationTokens` is always 0: it is an Anthropic-native
        concept with no OpenAI-compatible equivalent, and the field is
        required by the TS type. Reporting 0 is honest ("we know of
        none"); omitting it would make the UI render `undefined`.
        """
        return {
            "inputTokens": self.input_tokens,
            "outputTokens": self.output_tokens,
            "cacheReadTokens": self.cache_read_tokens,
            "cacheCreationTokens": 0,
        }


class _Accumulator:
    """The turn's audit product — what the `_done` frame carries.

    A port of the PRODUCT of the old TypeScript `sendTurn` accumulator
    (`web/lib/youcoded-session-provider.ts`), not its plumbing: the
    WebSocket subscriptions, the finalize-grace-timer and the
    `session_died` concept all belonged to driving a Claude Code PTY and
    have no meaning here.

    ONE DELIBERATE BEHAVIOR CHANGE — the bug this task fixes: the
    original required numeric `span_start`/`span_end` on every cite and
    silently dropped anything else. `cite()` has accepted a `quote` (with
    the server deriving offsets) since 2026-05-20, and the system prompt
    tells the model to PREFER it, so the audit record had been quietly
    losing most citations. Quote-only cites are accepted here, carrying
    the server's `resolved_span_*` offsets when the call succeeded.
    `cite_batch` is walked too, for the same reason — the prompt steers
    every multi-citation answer to it, and the original only ever looked
    at `cite`.
    """

    def __init__(self) -> None:
        self._text_by_uuid: dict[str, str] = {}
        self._text_order: list[str] = []
        self.tool_calls: list[dict[str, Any]] = []
        self.retrieved_chunk_ids: list[str] = []
        self.citations: list[dict[str, Any]] = []

    def record_text(self, uuid: str, text: str) -> None:
        """Latest text wins per uuid; first-seen order is preserved."""
        if uuid not in self._text_by_uuid:
            self._text_order.append(uuid)
        self._text_by_uuid[uuid] = text

    def record_tool(
        self, call: _PartialToolCall, parsed_input: dict[str, Any], output: str, is_error: bool
    ) -> None:
        self.tool_calls.append(
            {
                "toolUseId": call.id,
                "toolName": call.name,
                "input": parsed_input,
                "output": output,
                "isError": is_error,
            }
        )
        if call.name == "retrieve":
            self.retrieved_chunk_ids.extend(_chunk_ids(output))
        elif call.name == "cite":
            self._add_citation(parsed_input, _cite_ack(output))
        elif call.name == "cite_batch":
            inputs = parsed_input.get("citations")
            acks = _cite_batch_acks(output)
            if isinstance(inputs, list):
                for index, item in enumerate(inputs):
                    ack = acks[index] if index < len(acks) else {}
                    self._add_citation(item, ack)

    def _add_citation(self, raw: Any, ack: dict[str, Any]) -> None:
        if not isinstance(raw, dict):
            return
        chunk_id = raw.get("chunk_id")
        claim_span = raw.get("claim_span")
        if not isinstance(chunk_id, str) or not isinstance(claim_span, str):
            # Same policy as the original: drop and say so on stderr. A
            # cite with no chunk_id or no claim span cannot be audited or
            # attached to any sentence, so keeping it would only pad the
            # record.
            print(
                f"harness.session: dropping malformed cite input: "
                f"{json.dumps(raw, ensure_ascii=False)[:300]}",
                file=sys.stderr,
            )
            return
        ok = ack.get("ok") is True
        # Offsets, best available first: the SERVER's resolved span (the
        # only one that is guaranteed to point at the cited text, and the
        # only one a quote-only cite has), then the model's own legacy
        # offsets, then nothing.
        span_start = ack.get("resolved_span_start")
        span_end = ack.get("resolved_span_end")
        if not isinstance(span_start, int) or not isinstance(span_end, int):
            span_start = raw.get("span_start")
            span_end = raw.get("span_end")
        self.citations.append(
            {
                "chunkId": chunk_id,
                "claimSpan": claim_span,
                "confidence": raw.get("confidence"),
                "quote": raw.get("quote"),
                "spanStart": span_start if isinstance(span_start, int) else None,
                "spanEnd": span_end if isinstance(span_end, int) else None,
                "citationId": ack.get("citation_id"),
                "ok": ok,
                "error": ack.get("error"),
            }
        )

    def final_answer(self) -> str:
        """Everything the model SAID this turn, in the order it said it.

        Latest text per uuid, joined by a blank line in first-seen order
        — one uuid is one assistant message, and a turn with tool calls
        in the middle produces several. That means narration written
        BEFORE a tool call ("Let me check the FY2027 baseline.") is part
        of this string, not just the closing answer: it is what the
        analyst read on screen, so it belongs in the audit record. A
        consumer that wants only the concluding text should take the last
        paragraph, not assume this field holds one.

        System-authored text is never in here — see the max_steps branch
        of `_run_turn`. `record_text` has exactly one caller for that
        reason."""
        return "\n\n".join(self._text_by_uuid[u] for u in self._text_order)

    def done_frame(
        self,
        stop_reason: str,
        usage: dict[str, int],
        cost: float | None,
        incomplete_note: str | None = None,
    ) -> dict[str, Any]:
        """The terminal summary.

        `incompleteNote` is system-authored text and lives HERE, never in
        `finalAnswer` — see the max_steps branch of `_run_turn`. It sits
        on `_done` rather than on `turn_complete` because `turn_complete`
        is part of the pinned `ProviderEvent` union in
        `web/lib/types.ts`, while `_done` is this transport's own frame
        and free to carry extra fields.
        """
        return {
            "type": "_done",
            "stopReason": stop_reason,
            "finalAnswer": self.final_answer(),
            "incompleteNote": incomplete_note,
            "citations": self.citations,
            "retrievedChunkIds": self.retrieved_chunk_ids,
            "toolCalls": self.tool_calls,
            "usage": {**usage, "cost": cost},
        }


def _chunk_ids(output: str) -> list[str]:
    """chunk_ids out of a retrieve() result. Best-effort: a malformed
    body contributes nothing rather than failing the turn."""
    try:
        parsed = json.loads(output)
    except ValueError:
        return []
    chunks = parsed.get("chunks") if isinstance(parsed, dict) else None
    if not isinstance(chunks, list):
        return []
    return [c["chunk_id"] for c in chunks if isinstance(c, dict) and isinstance(c.get("chunk_id"), str)]


def _cite_ack(output: str) -> dict[str, Any]:
    try:
        parsed = json.loads(output)
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _cite_batch_acks(output: str) -> list[dict[str, Any]]:
    parsed = _cite_ack(output).get("citations")
    if not isinstance(parsed, list):
        return []
    return [item if isinstance(item, dict) else {} for item in parsed]
