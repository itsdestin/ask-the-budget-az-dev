"""The tool loop (Plan 4 Task 6, spec S3).

This is the piece that used to be a whole desktop application. Before
Plan 4, a turn went: web app -> WebSocket -> YouCoded -> a PTY running
Claude Code -> an MCP server process -> HTTP -> a FastAPI sidecar. S3
replaces all of it with one function that talks to an OpenAI-compatible
chat-completions endpoint (OpenRouter by default, S13) and runs the
tools in-process.

What this module owns:
  * the conversation's message history and what slice of it fits in a
    request (`_truncate`),
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
import uuid as uuid_module
from dataclasses import dataclass, field
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
# "tool_calls" never reaches here (the loop continues instead).
_FINISH_REASONS = {
    "stop": "end_turn",
    "length": "max_tokens",
    "content_filter": "content_filter",
    "error": "error",
}

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
    return ProviderError(
        f"The model provider returned an error (HTTP {status}): "
        f"{_extract_error_message(status, body)}"
    )


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
        tools: Sequence[dict[str, Any]] | None = None,
        history: list[dict[str, Any]] | None = None,
        context_chars: int = DEFAULT_CONTEXT_CHARS,
        sleep: Callable[[float], None] = time.sleep,
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
        # record — `_truncate` never mutates it, it only chooses a view.
        self.history: list[dict[str, Any]] = list(history or [])

        self._executor = executor
        self._transport = transport
        self._system_prompt = system_prompt
        self._tools = list(tools) if tools is not None else None
        self._context_chars = context_chars
        self._sleep = sleep
        self._check_limit = check_limit
        self._record_usage = record_usage

        self._client: httpx.Client | None = None
        # Set by interrupt() from the UI thread; cleared at the start of
        # every turn so a stale abort can't kill the next question.
        self._interrupted = threading.Event()
        # Non-reentrant guard: two turns interleaving on one history
        # would produce a message list neither of them intended.
        self._turn_lock = threading.Lock()

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
        """Release the HTTP connection pool. Safe to call twice."""
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

        model = settings.tiers[self.tier].model
        max_steps = self._max_steps()
        accumulator = _Accumulator()

        yield _event("user_message", text=text)
        self.history.append({"role": "user", "content": text})

        stop_reason = "end_turn"
        usage_totals = _UsageTotals()

        for _step in range(max_steps):
            if self._interrupted.is_set():
                # Interrupted between steps: nothing is half-written, so
                # there is nothing to back-fill.
                yield _event("user_interrupt", kind="plain")
                stop_reason = "user_interrupt"
                break

            system = self._system_message()
            messages = [system] + self._truncate(self.history, reserved=len(system["content"]))
            result = _StepResult(uuid=_new_uuid())

            yield _event("assistant_thinking", uuid=result.uuid)
            try:
                yield from self._stream_completion(messages, model, result, accumulator)
            except ProviderError as err:
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

            self._bill(result, usage_totals, model)

            if result.interrupted:
                yield from self._finish_interrupted(result)
                stop_reason = "user_interrupt"
                break

            self.history.append(_assistant_message(result))

            if not result.tool_calls:
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
            # until it hit the tier's budget.
            stop_reason = "max_steps"
            yield from self._explain_step_cap(max_steps, accumulator)

        usage = usage_totals.as_turn_usage()
        yield _event("turn_complete", stopReason=stop_reason, model=model, usage=usage)
        yield accumulator.done_frame(stop_reason, usage, usage_totals.cost)

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
        # model intends them to run in.
        result.tool_calls = [
            call for _, call in sorted(partials.items()) if call.id and call.name
        ]

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

    def _open_stream(self, body: dict[str, Any]) -> httpx.Response:
        """POST /chat/completions with retries; return the OPEN response.

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
            except httpx.RequestError as err:
                last_error = f"could not reach the model provider: {err}"
                if attempt == attempts - 1:
                    raise ProviderError(last_error) from err
                self._sleep(RETRY_BACKOFF_SECONDS[attempt])
                continue

            if response.status_code < 400:
                return response

            # Read and close before deciding — an unread streaming
            # response holds a pooled connection open.
            text = response.read().decode("utf-8", errors="replace")
            retry_after = _retry_after_seconds(response.headers.get("retry-after"))
            response.close()

            retryable = response.status_code == 429 or response.status_code >= 500
            if not retryable or attempt == attempts - 1:
                raise _provider_error(response.status_code, text)
            # The provider's own instruction beats our schedule when it
            # gives one — it knows when the rate-limit window resets.
            delay = retry_after if retry_after is not None else RETRY_BACKOFF_SECONDS[attempt]
            self._sleep(delay)
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

    def _finish_interrupted(self, result: _StepResult) -> Iterator[dict[str, Any]]:
        """Close out a turn aborted mid-stream, leaving valid history.

        The hard requirement: an OpenAI-compatible history must never
        end with an assistant message whose `tool_calls` have no
        matching `{"role": "tool"}` replies. The next request would be
        malformed and the provider 400s — which the analyst experiences
        as "the conversation is broken now", after doing nothing worse
        than pressing stop. So every tool call that survived assembly is
        back-filled with a cancelled result.

        Fragments that never got an `id` are dropped instead: a tool
        message must reference a `tool_call_id`, so an id-less call
        cannot be answered, and an unanswerable call is exactly the
        dangling state we are preventing.
        """
        self.history.append(_assistant_message(result))
        for call in result.tool_calls:
            # No tool_use event was emitted for these (the stream was cut
            # before the loop reached execution), so no tool_result event
            # either — the UI never drew a card that would be left
            # spinning. History still needs the reply.
            self.history.append(
                {
                    "role": "tool",
                    "tool_call_id": call.id,
                    "name": call.name,
                    "content": _CANCELLED_TOOL_RESULT,
                }
            )
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

    def _system_message(self) -> dict[str, Any]:
        if self._system_prompt is None:
            # Task 7 owns the content; this module only owns the seam.
            from harness.prompt import build_system_prompt

            self._system_prompt = build_system_prompt(corpus=self.corpus, tier=self.tier)
        return {"role": "system", "content": self._system_prompt}

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

    def _explain_step_cap(
        self, max_steps: int, accumulator: _Accumulator
    ) -> Iterator[dict[str, Any]]:
        """Say out loud that the answer is incomplete.

        Without this the analyst sees an answer that simply stops, which
        is indistinguishable from a finished one — the exact "confident
        but wrong" failure Invariant 3 exists to prevent. Emitted as its
        own uuid so it lands as a separate paragraph rather than
        corrupting the model's last text block, and NOT appended to
        history: it is the system talking, and a model that reads it back
        next turn as its own words would start apologizing for it.
        """
        note = (
            f"I stopped after {max_steps} tool calls without finishing, so this "
            "answer is incomplete. Anything cited above is still supported — "
            "but ask a narrower question to get the rest"
        )
        note += (
            ", or switch to Deep Research for a larger search budget."
            if self.tier == "standard"
            else "."
        )
        note_uuid = _new_uuid()
        accumulator.record_text(note_uuid, note)
        yield _event("assistant_text_delta", uuid=note_uuid, text=note)

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
        totals.add(usage)
        # S15: a custom endpoint reports no trustworthy cost, and the
        # ledger's contract is that `None` means "unknown", not "free".
        cost = totals.last_cost if self.settings.provider.provider == "openrouter" else None
        try:
            self._record_usage(
                self.user,
                self.tier,
                result.model or model,
                _int_or_zero(usage.get("prompt_tokens")),
                _int_or_zero(usage.get("completion_tokens")),
                cost,
            )
        except Exception as err:  # noqa: BLE001 — see docstring
            print(
                f"harness.session: usage row NOT recorded for "
                f"{self.user!r} ({type(err).__name__}: {err}). The call still "
                "cost money — this month's totals will undercount.",
                file=sys.stderr,
            )

    # -- history ----------------------------------------------------------

    def _truncate(
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
           leading tool message. (Dropping a tool reply while KEEPING its
           assistant call is impossible here: replies always come after
           their call, so a backwards walk reaches the reply first.)

        3. **The newest message always survives**, even alone over
           budget. A request with a truncated-away question is
           guaranteed nonsense; an over-long one at least gets a clear
           provider error naming the real problem.

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
        while start < len(kept) - 1 and kept[start].get("role") == "tool":
            start += 1
        return kept[start:]

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

    def add(self, usage: dict[str, Any]) -> None:
        self.input_tokens += _int_or_zero(usage.get("prompt_tokens"))
        self.output_tokens += _int_or_zero(usage.get("completion_tokens"))
        details = usage.get("prompt_tokens_details")
        if isinstance(details, dict):
            self.cache_read_tokens += _int_or_zero(details.get("cached_tokens"))
        cost = usage.get("cost")
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
        """Latest text per uuid, joined in first-seen order — one uuid is
        one assistant message, and a turn with tool calls in the middle
        produces several."""
        return "\n\n".join(self._text_by_uuid[u] for u in self._text_order)

    def done_frame(
        self, stop_reason: str, usage: dict[str, int], cost: float | None
    ) -> dict[str, Any]:
        return {
            "type": "_done",
            "stopReason": stop_reason,
            "finalAnswer": self.final_answer(),
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
