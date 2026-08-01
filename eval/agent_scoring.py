"""Mechanical scoring for Layer 2 agent transcripts.

This module is deliberately free of model calls: everything here can be
re-run over historical transcripts at zero cost, which is what makes
metric improvements retroactive (spec: 'Mechanical scorer — free,
decoupled').
"""
from __future__ import annotations

import math
import re

from eval.agent_schema import KeyFact

# A currency mention: optional $, digits with optional thousands commas
# and decimals, optional scale word/suffix. The $-or-scale requirement in
# currency_values() below keeps bare years ('FY 2025') out of the pool.
_CURRENCY_RE = re.compile(
    # The comma-grouped alternative MUST allow a decimal tail: without it
    # '$1,391.2 million' backtracks into '$1' + '391.2 million' — two wrong
    # numbers instead of one right one.
    #
    # The trailing lookahead used to be '(?![\w.])', which rejects a match
    # immediately followed by ANY '.' — including a bare sentence-ending
    # period with no digit after it. '$1,214,000,000.' has no legal way to
    # satisfy that lookahead at its true length, so the engine backtracks
    # the '(?:,\d{3})+' repetition, shedding trailing 3-digit groups one at
    # a time until it finds a stopping point followed by something other
    # than '.' — here, the very next comma — and silently returns
    # '1,214,000' instead of '1,214,000,000' (1000x too small). Since
    # "...totaled $X." is one of the most common sentence shapes in budget
    # prose, this was a routine input, not an edge case. The replacement,
    # '(?!\w)(?!\.\d)', splits the two backtracking hazards apart: '(?!\w)'
    # still blocks stopping mid-word/mid-digit-run, while '(?!\.\d)' only
    # blocks a '.' that is itself followed by a digit (a genuine decimal
    # continuation, e.g. the '.2' in '1,391.2'). A bare '.' with no digit
    # after it — sentence-final — no longer forces backtracking.
    r"(\$)?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)\s*"
    r"(billion|million|thousand|[bmk])?(?!\w)(?!\.\d)",
    re.IGNORECASE,
)
_SCALE = {"b": 1e9, "billion": 1e9, "m": 1e6, "million": 1e6, "k": 1e3, "thousand": 1e3}

# 0.5% relative tolerance: accepts faithful roundings ('$1,391.2 million'
# for $1,391,157,700, ~0.003% off) while still rejecting a neighboring
# budget line. Authors needing exactness use kind=regex instead.
_REL_TOL = 0.005


def currency_values(text: str) -> set[float]:
    """Every dollar amount mentioned in text, normalized to plain floats."""
    values: set[float] = set()
    for dollar, num, scale in _CURRENCY_RE.findall(text):
        # Require a $ sign or a scale word — a bare number like '2025'
        # is a year or a count, not a currency mention.
        if not dollar and not scale:
            continue
        values.add(float(num.replace(",", "")) * _SCALE.get(scale.lower(), 1.0))
    return values


def fact_matches(fact: KeyFact, text: str) -> bool:
    """Does text contain the fact, within currency-formatting tolerance?"""
    if fact.kind == "string":
        return fact.value.lower() in text.lower()
    if fact.kind == "regex":
        return re.search(fact.value, text, re.IGNORECASE) is not None
    wanted = currency_values(fact.value)
    if not wanted:
        # An unparseable currency fact is an authoring error; failing
        # closed here would hide it as a permanent query failure.
        raise ValueError(f"key fact is not a parseable currency amount: {fact.value!r}")
    found = currency_values(text)
    return any(
        any(math.isclose(w, f, rel_tol=_REL_TOL) for f in found) for w in wanted
    )


# --- appended below the matchers: full-transcript scoring ---------------
import statistics
from typing import Any

from eval.agent_schema import AgentQuery
from eval.agent_transcript import (
    Transcript,
    citations,
    final_answer,
    parsed_output,
    retrieve_calls,
    tool_calls,
    usage,
    wall_ms,
)

# Phrases the Plan 4 live run actually saw leak into answer prose.
NARRATION_MARKERS = (
    "let me search", "let me look", "i'll search", "i will search",
    "i have what i need", "searching the corpus", "now i'll",
    "retrying the cite", "let me retrieve", "i'll retrieve",
)
# Corpus mechanics an analyst should never see.
# WHY "rerank" alone was dropped (2026-08 review): every other marker here is
# unambiguously retrieval jargon, but "rerank" is ordinary English in budget
# policy prose too ("the legislature chose to rerank funding priorities"),
# so it flagged clean answers as leaking internals. "cross-encoder rerank" is
# the phrase that actually appears in this system's internal vocabulary, so
# that's the marker kept instead -- it can't collide with policy prose.
INTERNAL_VOCAB = (
    "top_score", "chunk_id", "cite_batch", "deep_dive",
    "first_call_capped", "rrf", "cross-encoder rerank", "refusal threshold",
)
# The Plan 4 run leaked a raw download token into prose.
_TOKEN_LEAK_RE = re.compile(r"token[=:]\s*[A-Za-z0-9_\-]{12,}")


def cite_attempts(t: Transcript) -> list[dict[str, Any]]:
    """Every citation attempt as {'input', 'result'}, flattening
    cite_batch slots (index-parallel arrays per harness/tools.py:1196)."""
    attempts: list[dict[str, Any]] = []
    for call in tool_calls(t, "cite"):
        attempts.append({"input": call.get("input") or {},
                         "result": parsed_output(call)})
    for call in tool_calls(t, "cite_batch"):
        inputs = (call.get("input") or {}).get("citations") or []
        out = parsed_output(call) or {}
        results = out.get("citations") or []
        for i, item in enumerate(inputs):
            attempts.append({"input": item,
                             "result": results[i] if i < len(results) else None})
    return attempts


def _retrieved_chunks(t: Transcript) -> list[dict[str, Any]]:
    return [c for call in retrieve_calls(t) for c in call["chunks"]]


def _facts_covered(query: AgentQuery, text: str) -> int:
    return sum(1 for f in query.key_facts if fact_matches(f, text))


def score_transcript(query: AgentQuery, t: Transcript) -> dict[str, Any]:
    frame_type = (t.terminal.get("frame") or {}).get("type")
    row: dict[str, Any] = {
        "query_id": query.id, "shape": query.shape, "repeat": t.meta.get("repeat", 1),
        "ok": frame_type == "_done",
        "error": (t.terminal.get("frame") or {}).get("message") if frame_type != "_done" else None,
        "wall_ms": wall_ms(t),
    }
    u = usage(t)
    row["input_tokens"] = u.get("inputTokens", 0)
    row["output_tokens"] = u.get("outputTokens", 0)
    row["cached_tokens"] = u.get("cacheReadTokens", 0)
    row["cost_usd"] = u.get("cost")
    # One step per assistant message uuid — assistant_thinking fires once
    # per step (harness/session.py:632).
    row["steps"] = sum(1 for e in t.events if e.get("type") == "assistant_thinking")

    answer = final_answer(t)
    total_facts = len(query.key_facts)
    matched = _facts_covered(query, answer) if total_facts else 0
    row["key_facts_total"] = total_facts
    row["key_facts_matched"] = matched
    row["key_fact_rate"] = (matched / total_facts) if total_facts else None

    verified = [c for c in citations(t) if c.get("ok")]
    row["verified_citations"] = len(verified)
    row["emitted_citations"] = len(citations(t))

    attempts = cite_attempts(t)
    failures = [a for a in attempts
                if not ((a["result"] or {}).get("ok") is True)]
    row["cite_attempts"] = len(attempts)
    row["cite_failures"] = len(failures)
    row["first_attempt_cite_rate"] = (
        (len(attempts) - len(failures)) / len(attempts) if attempts else None)
    row["ambiguity_rejections"] = sum(
        1 for a in failures
        if "appears multiple times" in ((a["result"] or {}).get("error") or ""))
    quote_lens = [len(c.get("quote") or "") for c in verified if c.get("quote")]
    row["median_quote_len"] = statistics.median(quote_lens) if quote_lens else None

    rcs = retrieve_calls(t)
    row["retrieve_call_count"] = len(rcs)
    all_chunks = _retrieved_chunks(t)
    distinct = {c.get("chunk_id"): c for c in all_chunks}
    row["retrieved_chunks_distinct"] = len(distinct)
    cited_ids = {c.get("chunkId") for c in verified}
    # WHY a bare fact-in-text match no longer counts as "used" (2026-08
    # review): a retrieved chunk used to count as used if it was cited OR if
    # its text merely CONTAINED any key fact. For kind="string" facts -- an
    # agency or program name, the common shape for lookup queries -- nearly
    # any topically-adjacent chunk contains the string (table-of-contents
    # entries, unrelated sections that just mention the agency in passing),
    # so this saturated to ~1.0 regardless of whether the agent actually
    # searched efficiently, defeating the metric's whole purpose.
    #
    # New definition of "used": a chunk counts as used if EITHER
    #   (a) it was cited (the strong signal -- the agent explicitly pointed
    #       at it), OR
    #   (b) it contains a specific fact (kind="currency" or kind="regex" --
    #       a dollar amount or a regex-pinned value, never a bare string/name)
    #       that ALSO appears in the model's final answer. Requiring the
    #       fact to appear in the answer too is what makes this a real (if
    #       weaker) signal that the chunk's content was drawn on, rather than
    #       merely topically nearby.
    # A bare name match (kind="string") is deliberately NOT evidence under
    # either path and can never make a chunk count as used on its own.
    used = 0
    for cid, c in distinct.items():
        text = c.get("text") or ""
        if cid in cited_ids:
            used += 1
            continue
        specific_facts = [f for f in query.key_facts if f.kind in ("currency", "regex")]
        if any(fact_matches(f, text) and fact_matches(f, answer) for f in specific_facts):
            used += 1
    row["retrieval_efficiency"] = (used / len(distinct)) if distinct else None

    # Retrieves issued AFTER the facts were already in hand = wasted searches.
    row["retrieves_after_sufficient"] = None
    if query.key_facts and rcs:
        seen: list[str] = []
        for i, call in enumerate(rcs):
            seen.extend((c.get("text") or "") for c in call["chunks"])
            blob = "\n".join(seen)
            if all(fact_matches(f, blob) for f in query.key_facts):
                row["retrieves_after_sufficient"] = len(rcs) - i - 1
                break

    # Refusal scoring: 'refused' means no verified citation was issued.
    # REFUSAL_THRESHOLD is prompt-guidance only (never enforced in code),
    # so the observable refusal signal IS the absence of verified cites.
    #
    # WHY every judgment below is gated on row["ok"] (2026-08 review, Finding
    # 1): an `_error` transcript (crashed query, never actually ran) has zero
    # verified citations BY CONSTRUCTION, which is indistinguishable from a
    # genuine correct refusal unless we gate on completion. Ungated, a single
    # crashed transcript silently scored refusal_correct_rate: 1.0 -- a
    # change that starts CRASHING on refusal-shaped queries would render as
    # "refusal correctness better" next to "errors worse", with nothing to
    # show the first arrow is an artifact of the crash. A transcript that
    # did not complete must not contribute to any refusal judgment.
    refused = len(verified) == 0
    row["refused"] = refused
    row["refusal_correct"] = (
        (refused == query.should_refuse) if (row["ok"] and query.should_refuse) else None
    )
    # WHY false_refusal no longer requires total_facts > 0 (2026-08 review,
    # Finding 3): a non-refusal query authored with zero key facts (plausible
    # for memo/comparison/analyze shapes that lean on the LLM judge instead)
    # used to make an incorrect refusal invisible everywhere in this scorer --
    # `total_facts > 0` gated it out entirely, so it was never flagged, never
    # counted, never aggregated. When there ARE key facts, "refused AND
    # matched none of them" is the strongest available signal. When there are
    # NONE, the only signal left is that the agent issued zero verified
    # citations for a query that was authored expecting an answer -- flag
    # that too, for human review; the LLM judge step covers subtler cases.
    row["false_refusal"] = None
    if row["ok"] and not query.should_refuse:
        if total_facts > 0:
            row["false_refusal"] = refused and matched == 0
        else:
            row["false_refusal"] = refused

    lower = answer.lower()
    row["narration_hits"] = sum(1 for m in NARRATION_MARKERS if m in lower)
    row["internal_vocab_hits"] = sum(1 for v in INTERNAL_VOCAB if v in lower)
    row["token_leak"] = bool(_TOKEN_LEAK_RE.search(answer))
    return row


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [r for r in rows if r["ok"]]
    walls = sorted(r["wall_ms"] for r in ok_rows if r["wall_ms"] is not None)
    attempts = sum(r["cite_attempts"] for r in ok_rows)
    failures = sum(r["cite_failures"] for r in ok_rows)
    # WHY `r["ok"]` is checked here too, redundantly with score_transcript's
    # own gating (2026-08 review, Finding 1): this is the aggregate that
    # actually produces refusal_correct_rate, and unlike every other
    # aggregate field it previously did NOT restrict to successful rows --
    # it relied entirely on refusal_correct already being None for a crashed
    # transcript. Keeping the check here too means a future regression in
    # score_transcript's gating can't silently let a crashed query back into
    # this rate a second time.
    refusal_rows = [r for r in rows if r["ok"] and r["refusal_correct"] is not None]
    quote_meds = [r["median_quote_len"] for r in ok_rows if r["median_quote_len"] is not None]
    return {
        "n": len(rows),
        "errors": len(rows) - len(ok_rows),
        "steps_mean": _mean([r["steps"] for r in ok_rows]),
        "retrieve_calls_mean": _mean([r["retrieve_call_count"] for r in ok_rows]),
        "input_tokens_mean": _mean([r["input_tokens"] for r in ok_rows]),
        "output_tokens_mean": _mean([r["output_tokens"] for r in ok_rows]),
        "cached_tokens_mean": _mean([r["cached_tokens"] for r in ok_rows]),
        "total_cost_usd": sum(r["cost_usd"] or 0 for r in ok_rows),
        "cost_mean_usd": _mean([r["cost_usd"] for r in ok_rows]),
        "wall_p50_ms": walls[len(walls) // 2] if walls else None,
        "wall_p95_ms": walls[min(len(walls) - 1, int(len(walls) * 0.95))] if walls else None,
        "key_fact_rate_mean": _mean([r["key_fact_rate"] for r in ok_rows]),
        "retrieval_efficiency_mean": _mean([r["retrieval_efficiency"] for r in ok_rows]),
        "retrieves_after_sufficient_mean": _mean(
            [r["retrieves_after_sufficient"] for r in ok_rows]),
        "citations_per_answer_mean": _mean([r["verified_citations"] for r in ok_rows]),
        "first_attempt_cite_rate": ((attempts - failures) / attempts) if attempts else None,
        "median_quote_len_mean": _mean(quote_meds),
        "refusal_correct_rate": _mean(
            [1.0 if r["refusal_correct"] else 0.0 for r in refusal_rows]),
        "false_refusals": sum(1 for r in rows if r.get("false_refusal")),
        "narration_hit_queries": sum(1 for r in ok_rows if r["narration_hits"]),
        "token_leaks": sum(1 for r in ok_rows if r["token_leak"]),
        "internal_vocab_queries": sum(1 for r in ok_rows if r["internal_vocab_hits"]),
    }
