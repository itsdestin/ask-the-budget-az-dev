"""Mechanical scoring for Layer 2 agent transcripts.

This module is deliberately free of model calls: everything here can be
re-run over historical transcripts at zero cost, which is what makes
metric improvements retroactive (spec: 'Mechanical scorer — free,
decoupled').
"""
from __future__ import annotations

import math
import re
import statistics
from typing import Any

from eval.agent_schema import AgentQuery, KeyFact
from eval.agent_transcript import (
    Transcript,
    annotation,
    citations,
    final_answer,
    parsed_output,
    retrieve_calls,
    tool_calls,
    usage,
    wall_ms,
)

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


# --- full-transcript scoring --------------------------------------------

# Phrases the Plan 4 live run actually saw leak into answer prose.
NARRATION_MARKERS = (
    "let me search", "let me look", "i'll search", "i will search",
    "i have what i need", "searching the corpus", "now i'll",
    "retrying the cite", "let me retrieve", "i'll retrieve",
    # Citation-bookkeeping announcements (added 2026-08-02, seen in a
    # browser). The prompt banned this shape by example already, and the
    # model simply reworded it — "All citations are now registered." Without
    # markers for it the eval could not measure the behaviour at all, so the
    # prompt hardening that followed would have been unfalsifiable.
    # Each phrase is chosen to be impossible in budget policy prose, the
    # same bar the "rerank" note below records.
    "citations are now registered", "citations registered",
    "citations have been registered", "cites now anchored",
    "all cites anchored", "all citations anchored",
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


def cite_target(attempt: dict[str, Any]) -> tuple[str, str]:
    """The (chunk_id, claim_span) pair a citation attempt is aiming at.

    WHY this pair and not chunk_id alone (spec goal 4, 'retries per
    citation'): one answer legitimately cites the SAME chunk for two
    different claims — that is exactly what a cite_batch's sibling slots
    are — so grouping on chunk_id alone would score every such sibling as
    a retry of the one before it and make an answer that cites carefully
    look like an answer that kept failing. A genuine retry re-attempts the
    same claim against the same chunk with a different quote, which shares
    both halves of this key.

    Known limit, stated rather than engineered around: a retry that
    REWRITES the claim_span (STATUS.md records the model doing this) reads
    as a new citation here. The metric therefore under-counts retries; it
    never invents them.
    """
    # A malformed slot is not necessarily a dict — observed live on
    # 2026-08-02, the model emitted cite_batch citations as bare STRINGS
    # (fragments of a double-encoded JSON payload). Key such an attempt by
    # its own repr so two distinct malformed slots never collapse into one
    # "retry" of each other.
    inp = attempt.get("input")
    if not isinstance(inp, dict):
        return (f"<malformed:{inp!r}>", "")
    return (str(inp.get("chunk_id")), str(inp.get("claim_span")))


def _attempt_passed(attempt: dict[str, Any]) -> bool:
    return (attempt.get("result") or {}).get("ok") is True


# The filter dimensions retrieve() accepts (harness/tools.py _FILTERS_SCHEMA).
# Pinned as a literal list rather than imported so that scoring a historical
# transcript keeps meaning what it meant when the run happened — importing the
# live schema would silently re-interpret old runs whenever the tool changes.
FILTER_DIMENSIONS = ("fiscal_year", "doc_type", "publisher",
                     "agency_canonical_id", "fund_canonical_id", "is_table")


def retrieve_inputs(t: Transcript) -> list[dict[str, Any]]:
    """Each retrieve call's INPUT arguments, in call order.

    `retrieve_calls()` returns the parsed OUTPUT of each call; the search
    parameters the agent chose (filters, top_k, intent, deep_dive) live on
    the input side, which is what spec goal 3's 'filter/corpus-parameter
    usage counts' measures.
    """
    return [(call.get("input") or {}) for call in tool_calls(t, "retrieve")]


def _retrieved_chunks(t: Transcript) -> list[dict[str, Any]]:
    return [c for call in retrieve_calls(t) for c in call["chunks"]]


def _facts_covered(query: AgentQuery, text: str) -> int:
    return sum(1 for f in query.key_facts if fact_matches(f, text))


def score_transcript(query: AgentQuery, t: Transcript) -> dict[str, Any]:
    frame_type = (t.terminal.get("frame") or {}).get("type")
    row: dict[str, Any] = {
        "query_id": query.id, "shape": query.shape, "set": query.set,
        "repeat": t.meta.get("repeat", 1),
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

    # Headline eligibility (2026-08-16 consolidation): an "accurate" response
    # passes ALL its key facts AND produces >=1 verified citation. Refusal
    # queries (0 key facts) are never "accurate" — their quality lives in
    # refusal_correct_rate, and counting them here would inflate the headline
    # with cheap refuses (the vacuous-pass hole the spec explicitly closes).
    row["accurate"] = bool(
        frame_type == "_done" and total_facts
        and matched == total_facts and row["verified_citations"] >= 1
    )
    row["total_tokens"] = row["input_tokens"] + row["output_tokens"] + row["cached_tokens"]

    attempts = cite_attempts(t)
    failures = [a for a in attempts if not _attempt_passed(a)]
    row["cite_attempts"] = len(attempts)
    row["cite_failures"] = len(failures)
    # WHY this was RENAMED from first_attempt_cite_rate (2026-08 review,
    # Finding 5): it is (attempts - failures) / attempts — the pass rate over
    # EVERY attempt, retries included. That is a useful number, but it is not a
    # first-attempt rate, and the two diverge exactly when retries happen,
    # which is the case the metric was supposed to expose. The genuine
    # first-try rate is `first_try_cite_rate` below; this one now says what it
    # measures.
    row["cite_pass_rate"] = (
        (len(attempts) - len(failures)) / len(attempts) if attempts else None)

    # Spec goal 4, 'retries per citation' — one attempt per intended citation
    # is the target; anything above 1.0 is the model re-shooting at a claim it
    # already tried. `targets` is first-attempt-ordered, so first_try asks the
    # question the old name promised: of the citations the answer intended,
    # what share landed on the FIRST try?
    first_by_target: dict[tuple[str, str], bool] = {}
    for a in attempts:
        first_by_target.setdefault(cite_target(a), _attempt_passed(a))
    row["cite_targets"] = len(first_by_target)
    row["cite_retries"] = len(attempts) - len(first_by_target)
    row["retries_per_citation"] = (
        (len(attempts) - len(first_by_target)) / len(first_by_target)
        if first_by_target else None)
    row["first_try_cite_rate"] = (
        sum(1 for ok in first_by_target.values() if ok) / len(first_by_target)
        if first_by_target else None)
    row["ambiguity_rejections"] = sum(
        1 for a in failures
        if "appears multiple times" in ((a["result"] or {}).get("error") or ""))
    quote_lens = [len(c.get("quote") or "") for c in verified if c.get("quote")]
    row["median_quote_len"] = statistics.median(quote_lens) if quote_lens else None

    rcs = retrieve_calls(t)
    row["retrieve_call_count"] = len(rcs)

    # Spec goal 3, 'filter/corpus-parameter usage counts'. An agent that
    # narrows a search to the fiscal year and agency the question named is
    # showing self-awareness; one that fires the same unfiltered query five
    # times is not. Counts only — deliberately NOT scored better/worse, since
    # a filter is right or wrong depending on the question, and a metric that
    # rewarded filtering per se would push the agent to filter itself out of
    # the answer.
    inputs = retrieve_inputs(t)
    dim_counts = {d: 0 for d in FILTER_DIMENSIONS}
    filtered = 0
    for inp in inputs:
        filters = inp.get("filters")
        if not isinstance(filters, dict) or not filters:
            continue
        filtered += 1
        for dim in FILTER_DIMENSIONS:
            if filters.get(dim) not in (None, [], {}):
                dim_counts[dim] += 1
    row["retrieve_calls_with_filters"] = filtered
    row["filter_dimension_counts"] = dim_counts
    row["retrieve_calls_with_intent"] = sum(1 for i in inputs if i.get("intent"))
    row["retrieve_calls_with_top_k"] = sum(1 for i in inputs if i.get("top_k"))
    row["deep_dive_calls"] = sum(1 for i in inputs if i.get("deep_dive") is True)

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
    #
    # WHY the eligible/contributing split (2026-08 review, Finding 4): this
    # value stays None unless the retrieved text contained EVERY key fact at
    # some point, so the population it averages over is decided by the run's
    # own success. Run A found the facts on 5 of 35 queries and averages over
    # 5; run B found them on 20 and averages over 20 — different denominators
    # wearing the same name. Worse, the metric is better-when-lower, so a
    # genuine RETRIEVAL IMPROVEMENT (more queries reach sufficiency, including
    # slower ones that needed several searches) can raise the mean and render
    # as a regression. The per-query `retrieves_after_sufficient_eligible`
    # (bool, below) records whether THIS query could have contributed; the
    # summary's `retrieves_after_sufficient_eligible_queries` (int, in
    # aggregate() — deliberately NOT the same name as the per-query bool, see
    # the WHY there) counts how many queries could have, and `..._n` how many
    # did. The compare tool withholds the better/worse arrow when that
    # population moved, because a delta across different populations is not
    # a delta.
    row["retrieves_after_sufficient"] = None
    row["retrieves_after_sufficient_eligible"] = bool(query.key_facts and rcs)
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

    # Doc-type relationship axis (2026-08-16 consolidation, priority 3): the
    # "cited the Baseline when it should have cited the Appropriations
    # Report" test. Purely transcript-mechanical — chunk_id -> doc_id resolves
    # from this run's own retrieve outputs (harness/tools.py:1405), so no
    # corpus access is needed. Unresolvable chunk ids (cite without a prior
    # retrieve in transcript) count against the share AND are loud: they mean
    # a transcript invariant broke, which is an error-ledger matter.
    #
    # WHY the citation side reads "chunkId" (harness casing) and not the
    # brief's sketch's "chunk_id": the harness records citations with the
    # camelCase key (harness/session.py:1979) and the score_transcript above
    # already reads cited chunk ids that way (line 307). Skimming the brief's
    # sketch literally would make every verified citation resolve to None
    # here; measurement wins.
    row["document_correctness"] = None
    row["multi_unanswered"] = False
    if query.set == "multi" and query.correct_response_docs:
        id_to_doc = {c["chunk_id"]: c.get("doc_id")
                     for c in _retrieved_chunks(t) if c.get("doc_id")}
        verified = [c for c in citations(t) if c.get("ok")]
        if not verified:
            # Cited nothing != cited the wrong doc-type; key facts still say
            # whether the answer was right. Reported distinctly, never as 0.
            row["multi_unanswered"] = True
        else:
            targets = [id_to_doc.get(c.get("chunkId")) for c in verified]
            hits = sum(1 for d in targets if d in query.correct_response_docs)
            row["document_correctness"] = hits / len(verified)

    lower = answer.lower()
    row["narration_hits"] = sum(1 for m in NARRATION_MARKERS if m in lower)
    row["internal_vocab_hits"] = sum(1 for v in INTERNAL_VOCAB if v in lower)
    row["token_leak"] = bool(_TOKEN_LEAK_RE.search(answer))

    # Figure-citation coverage. This replaces citation COUNT as the
    # citation-quality signal: many citations are fine, missing ones are
    # not. `None` when the answer states no figures — that is not a
    # coverage failure and must not average in as a zero.
    ann_figures = annotation(t).get("figures") or []
    counts = {"linked": 0, "derived": 0, "unverified": 0}
    for entry in ann_figures:
        verdict = entry.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    row["figures_total"] = len(ann_figures)
    row["figures_linked"] = counts["linked"]
    row["figures_derived"] = counts["derived"]
    row["figures_unverified"] = counts["unverified"]
    row["figure_coverage"] = (
        (counts["linked"] + counts["derived"]) / len(ann_figures)
        if ann_figures else None)
    # Marker metrics (spec A8). These separate the two halves of attested
    # linking, which fail for different reasons and need different fixes:
    # `figures_attested` is how often the MODEL tagged a figure at all (a
    # prompt-wording problem when it is low), `figures_tag_linked` is how
    # often the tag then VERIFIED against the chunk it named (a model
    # accuracy problem when it is low). Collapsed into one number, a
    # well-behaved model that tags nothing would be indistinguishable from
    # one that tags everything wrongly. `.get` throughout: an annotation
    # recorded before A2 carries none of these fields and must read as
    # "tagged nothing", not crash the whole run's scoring.
    row["figures_attested"] = sum(
        1 for e in ann_figures if e.get("attested_chunk_ids"))
    row["figures_tag_linked"] = sum(
        1 for e in ann_figures if e.get("link_basis") == "tag")
    return row


def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if v is not None]
    return (sum(vals) / len(vals)) if vals else None


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    ok_rows = [r for r in rows if r["ok"]]
    acc = [r for r in ok_rows if r["accurate"]]
    # WHY the headline excludes rather than zeroes inaccurate rows: a
    # regression that trades correctness for speed must show as accurate_rate
    # dropping while the headline counts FEWER queries — not as a faster
    # average. Zeroing would reward exactly the failure mode.
    headline_by_set: dict[str, dict] = {}
    for sname in sorted({r.get("set") for r in acc if r.get("set")}):
        sub = [r for r in acc if r.get("set") == sname]
        headline_by_set[sname] = {
            "n": len(sub),
            "tokens_mean": _mean([r["total_tokens"] for r in sub]),
            "turns_mean": _mean([r["steps"] for r in sub]),
        }
    # WHY wall_p50_ms/wall_p95_ms were DELETED (2026-08-16 consolidation,
    # Destin's call): wall time is dominated by provider network latency and
    # machine load (~70% absolute swings on this box, CLAUDE.md), so no
    # comparison survives a different session. tokens_to_accurate /
    # turns_to_accurate are the cost metrics. Per-query wall_ms survives in
    # the row for forensics — never aggregate it again.
    attempts = sum(r["cite_attempts"] for r in ok_rows)
    failures = sum(r["cite_failures"] for r in ok_rows)
    targets = sum(r["cite_targets"] for r in ok_rows)
    retries = sum(r["cite_retries"] for r in ok_rows)
    # first_try_cite_rate is re-derived from per-query counts rather than
    # averaged over per-query rates, so a query with 8 citations weighs 8x a
    # query with 1 — the same convention cite_pass_rate already used.
    first_try_passes = sum(
        round((r["first_try_cite_rate"] or 0) * r["cite_targets"]) for r in ok_rows)
    ras_rows = [r for r in ok_rows if r["retrieves_after_sufficient"] is not None]
    ras_eligible = [r for r in ok_rows if r.get("retrieves_after_sufficient_eligible")]
    retrieves = sum(r["retrieve_call_count"] for r in ok_rows)
    dim_totals: dict[str, int] = {d: 0 for d in FILTER_DIMENSIONS}
    for r in ok_rows:
        for dim, n in (r.get("filter_dimension_counts") or {}).items():
            dim_totals[dim] = dim_totals.get(dim, 0) + n
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
        "accurate_n": len(acc),
        "accurate_rate": (len(acc) / len(ok_rows)) if ok_rows else None,
        "tokens_to_accurate_mean": _mean([r["total_tokens"] for r in acc]),
        "turns_to_accurate_mean": _mean([r["steps"] for r in acc]),
        "accurate_headline_by_set": headline_by_set,
        "steps_mean": _mean([r["steps"] for r in ok_rows]),
        "retrieve_calls_mean": _mean([r["retrieve_call_count"] for r in ok_rows]),
        "input_tokens_mean": _mean([r["input_tokens"] for r in ok_rows]),
        "output_tokens_mean": _mean([r["output_tokens"] for r in ok_rows]),
        "cached_tokens_mean": _mean([r["cached_tokens"] for r in ok_rows]),
        # WHY this sums ALL rows and is paired with a missing-cost count
        # (2026-08 review, Finding 6): a query that crashed after 40 paid steps
        # produces an `_error` frame carrying no usage at all, so its spend is
        # invisible here no matter which rows are summed. Summing every row (a
        # crashed row's cost is simply None -> 0) at least stops the ok/not-ok
        # split from being a second, silent source of the same understatement,
        # and `cost_missing_queries` makes the remaining gap VISIBLE instead of
        # implied. The run's own ledger.jsonl is the authoritative spend
        # record — it has one row per step, written as the steps happen, so it
        # captures the tokens a later crash throws away. eval/README.md says so.
        "total_cost_usd": sum(r["cost_usd"] or 0 for r in rows),
        "cost_missing_queries": sum(1 for r in rows if r["cost_usd"] is None),
        "cost_mean_usd": _mean([r["cost_usd"] for r in ok_rows]),
        "key_fact_rate_mean": _mean([r["key_fact_rate"] for r in ok_rows]),
        # Figure coverage replaces citation VOLUME as the citation-quality
        # signal. Both means skip figureless answers rather than scoring
        # them 0 — a correct refusal states no figures, and averaging it in
        # as a total coverage failure would make a run of good refusals
        # look like a citation collapse. _mean already drops None, and
        # unverified_rate filters on figures_total for the same reason.
        "figure_coverage_mean": _mean([r["figure_coverage"] for r in ok_rows]),
        "unverified_rate": _mean(
            [r["figures_unverified"] / r["figures_total"]
             for r in ok_rows if r["figures_total"]]),
        # Marker coverage skips figureless rows for the same reason
        # figure_coverage_mean does — a correct refusal states no figures.
        "marker_coverage_mean": _mean(
            [r["figures_attested"] / r["figures_total"]
             for r in ok_rows if r["figures_total"]]),
        # Tag accuracy is conditioned on there BEING a tag: a row the model
        # never tagged has no tag accuracy to report, and scoring it 0.0
        # would blame the verifier for the model's silence — which
        # marker_coverage_mean already measures. Reporting the same failure
        # twice would make the design's one open risk look twice as bad.
        "tag_accuracy_mean": _mean(
            [r["figures_tag_linked"] / r["figures_attested"]
             for r in ok_rows if r["figures_attested"]]),
        "retrieval_efficiency_mean": _mean([r["retrieval_efficiency"] for r in ok_rows]),
        "retrieves_after_sufficient_mean": _mean(
            [r["retrieves_after_sufficient"] for r in ras_rows]),
        # The population this mean was taken over. Read them together or not
        # at all — see the WHY on retrieves_after_sufficient in score_transcript.
        "retrieves_after_sufficient_n": len(ras_rows),
        # WHY this is "..._eligible_queries", not "..._eligible" (2026-08
        # review, fix batch, Finding 2): the per-query row above uses
        # "retrieves_after_sufficient_eligible" for a BOOL. Reusing that exact
        # string here for an INT count means the one JSON key holds two
        # different types depending on whether you're reading `per_query` or
        # `summary` — confirmed in real generated output (`true` vs `2`) and
        # exactly the shape that breaks any generic scores.json consumer
        # (e.g. `json.load` + duck-typed access, or a future dashboard that
        # walks all int/float summary fields). Safe to rename now because no
        # baseline run has been committed yet; it would not be once one is.
        "retrieves_after_sufficient_eligible_queries": len(ras_eligible),
        "retrieve_calls_with_filters": sum(
            r["retrieve_calls_with_filters"] for r in ok_rows),
        "filtered_retrieve_rate": (
            sum(r["retrieve_calls_with_filters"] for r in ok_rows) / retrieves
            if retrieves else None),
        "filter_dimension_counts": dim_totals,
        "retrieve_calls_with_intent": sum(
            r["retrieve_calls_with_intent"] for r in ok_rows),
        "retrieve_calls_with_top_k": sum(
            r["retrieve_calls_with_top_k"] for r in ok_rows),
        "deep_dive_calls": sum(r["deep_dive_calls"] for r in ok_rows),
        "citations_per_answer_mean": _mean([r["verified_citations"] for r in ok_rows]),
        "cite_pass_rate": ((attempts - failures) / attempts) if attempts else None,
        "first_try_cite_rate": (first_try_passes / targets) if targets else None,
        "retries_per_citation": (retries / targets) if targets else None,
        "median_quote_len_mean": _mean(quote_meds),
        "refusal_correct_rate": _mean(
            [1.0 if r["refusal_correct"] else 0.0 for r in refusal_rows]),
        "false_refusals": sum(1 for r in rows if r.get("false_refusal")),
        "narration_hit_queries": sum(1 for r in ok_rows if r["narration_hits"]),
        "token_leaks": sum(1 for r in ok_rows if r["token_leak"]),
        "internal_vocab_queries": sum(1 for r in ok_rows if r["internal_vocab_hits"]),
        # Document-type correctness is only defined over Multi-set queries
        # that actually verified at least one citation (see the WHY in
        # score_transcript); the mean skips rows where it's None the way
        # every other None-aware mean here does, and multi_unanswered_n counts
        # the Multi rows that cited nothing at all.
        "document_correctness_mean": _mean(
            [r["document_correctness"] for r in ok_rows
             if r["document_correctness"] is not None]),
        "multi_unanswered_n": sum(1 for r in ok_rows if r["multi_unanswered"]),
    }
