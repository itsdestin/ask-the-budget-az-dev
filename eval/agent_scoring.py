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
INTERNAL_VOCAB = (
    "top_score", "chunk_id", "cite_batch", "deep_dive",
    "first_call_capped", "rrf", "rerank", "refusal threshold",
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
    used = 0
    for cid, c in distinct.items():
        text = c.get("text") or ""
        if cid in cited_ids or (query.key_facts and _facts_covered(query, text)):
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
    refused = len(verified) == 0
    row["refused"] = refused
    row["refusal_correct"] = (refused == query.should_refuse) if query.should_refuse else None
    row["false_refusal"] = (
        refused and total_facts > 0 and matched == 0) if not query.should_refuse else None

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
    refusal_rows = [r for r in rows if r["refusal_correct"] is not None]
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
