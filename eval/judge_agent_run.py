"""LLM judge for Layer 2 agent-eval runs (full runs only — costs money).

The judge identifies load-bearing claims and whether each is covered by
a verified citation. The headline number, claim-coverage precision, is
computed HERE from the judge's claim list and the transcript's citation
count — judge arithmetic is never trusted (spec Decision #3).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

import httpx

from eval.agent_schema import AgentQuery, load_agent_queries
from eval.agent_transcript import (
    Transcript, citations, final_answer, read_transcript, retrieve_calls,
)
from harness.settings import load_settings

DEFAULT_QUERIES = "eval/agent_queries.yaml"
# Not the model under test (spec): a capable, cheap-enough judge.
DEFAULT_JUDGE_MODEL = "anthropic/claude-sonnet-5"
PROMPT_PATH = Path(__file__).resolve().parent / "agent_judge_prompt.md"

# Strips a code fence ONLY when it opens at the very start of the reply
# and/or closes at the very end — i.e. a reply that is JUST
# "```json\n{...}\n```" with nothing else around it. It does NOT help when
# the judge adds any leading prose ("Here's my answer:\n```json...") or
# trailing commentary after the closing fence, because `^`/`$` anchor to
# the whole string, not to the fence's own position. _find_first_json_object
# (below) is what handles those shapes; this stays as a cheap first pass.
_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def _find_first_json_object(text: str) -> Any:
    r"""Locate and parse the first complete JSON value that begins at a
    literal `{` anywhere in `text`. Handles a judge reply with prose
    around the JSON in either direction ("Here's my answer:\n```json\n{...}
    \n```", or trailing chatter like "Hope that helps!" after the object)
    that _FENCE_RE's edge-anchored strip does not reach.

    Uses json.JSONDecoder.raw_decode rather than a brace-counting regex,
    because raw_decode is a real JSON parser: it stops at the CORRECT
    matching close-brace even when the object itself contains nested
    objects (this prompt's "flags": {...}), which a naive non-greedy
    `\{.*?\}` regex would cut short at the first inner `}` and a greedy
    `\{.*\}` would over-extend into any trailing prose. Returns None if no
    `{` in the text starts a parseable JSON value, so a genuinely
    prose-only reply (no JSON at all) still fails to parse.
    """
    decoder = json.JSONDecoder()
    start = text.find("{")
    while start != -1:
        try:
            obj, _ = decoder.raw_decode(text, start)
            return obj
        except ValueError:
            start = text.find("{", start + 1)
    return None


def build_judge_payload(query: AgentQuery, t: Transcript) -> dict[str, Any]:
    chunk_texts: dict[str, str] = {}
    for call in retrieve_calls(t):
        for c in call["chunks"]:
            cid = c.get("chunk_id")
            if cid:
                chunk_texts[cid] = c.get("text") or ""
    # WHY: a cited chunk_id sometimes has no entry in chunk_texts — the
    # chunk was cited but never returned by a retrieve() call in THIS
    # transcript (a real, tracked gap: STATUS.md's cross-turn-citation-
    # metadata issue). The old code just omitted the key in that case,
    # which looked identical to "the judge should check this text" against
    # an empty string. Always record the key and use None as an explicit
    # "no chunk text available to check" signal, distinct from "" (a chunk
    # that really did retrieve with empty text) and from a real string.
    cited: dict[str, str | None] = {}
    cite_rows = []
    for c in citations(t):
        cite_rows.append({"chunk_id": c.get("chunkId"), "quote": c.get("quote"),
                          "claim_span": c.get("claimSpan"), "ok": bool(c.get("ok"))})
        cid = c.get("chunkId")
        if cid:
            cited[cid] = chunk_texts.get(cid)
    return {"question": query.question, "judge_notes": query.judge_notes,
            "should_refuse": query.should_refuse,
            "final_answer": final_answer(t), "citations": cite_rows,
            "cited_chunks": cited}


def parse_judge_json(content: str) -> dict[str, Any]:
    stripped = _FENCE_RE.sub("", content.strip())
    parsed = _find_first_json_object(stripped)
    if parsed is None:
        raise ValueError(f"judge returned non-JSON: {content[:200]!r}")
    if not isinstance(parsed, dict) or "load_bearing_claims" not in parsed:
        raise ValueError(f"judge JSON missing load_bearing_claims: {stripped[:200]!r}")
    claims = parsed["load_bearing_claims"]
    # WHY: the prompt asks for "the claims that carry the answer", and a
    # judge model can plausibly reply with bare strings instead of
    # {claim, cited_verified} objects. compute_citation_scores() calls
    # `.get(...)` on each item — a string there raises AttributeError, and
    # because judge.json is written once at the very end of the whole run,
    # that single uncaught exception would discard every already-graded
    # row, not just this query's. Reject the bad shape HERE, still inside
    # judge_one's try/except, so it becomes one judge_error row instead of
    # a run-ending crash.
    if not isinstance(claims, list) or not all(isinstance(c, dict) for c in claims):
        raise ValueError(
            f"load_bearing_claims must be a list of claim objects, not "
            f"{type(claims).__name__}: {stripped[:200]!r}"
        )
    return parsed


def judge_one(client: httpx.Client, base_url: str, api_key: str, model: str,
              system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
    try:
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={"model": model, "temperature": 0,
                  "messages": [{"role": "system", "content": system_prompt},
                               {"role": "user",
                                "content": json.dumps(payload, ensure_ascii=False)}]},
            timeout=120.0)
        resp.raise_for_status()
        content = resp.json()["choices"][0]["message"]["content"]
        return parse_judge_json(content)
    except Exception as exc:
        # One flaky judge call must not lose the whole run's judging.
        return {"judge_error": f"{type(exc).__name__}: {exc}"}


def compute_citation_scores(judge_result: dict[str, Any], t: Transcript) -> dict[str, Any]:
    raw_claims = judge_result.get("load_bearing_claims")
    # WHY: hardened independently of parse_judge_json's shape validation —
    # this function is exercised directly by tests, and a future caller
    # could pass it unvalidated judge output too. A claim item that isn't a
    # dict (a bare string, most plausibly) would crash `c.get(...)` with an
    # AttributeError; filter to dict items instead of trusting the shape.
    # Non-dict items don't count toward EITHER denominator below — they
    # can't be judged covered or uncovered, so they can't inform precision
    # or recall in either direction.
    claims = [c for c in raw_claims if isinstance(c, dict)] if isinstance(raw_claims, list) else []
    covered = sum(1 for c in claims if c.get("cited_verified"))
    emitted = len(citations(t))
    return {
        # covered claims / citations ISSUED: padding citations dilute it.
        "claim_coverage_precision": (covered / emitted) if emitted else None,
        # covered claims / claims that NEEDED citing: uncited key claims hurt.
        "claim_coverage_recall": (covered / len(claims)) if claims else None,
    }


def main() -> int:
    # Windows-friendly: ensure stdout can encode non-ASCII characters that
    # show up in judge output and query text (accented agency names,
    # en-dashes, etc.). Default cp1252 console crashes on these. Safe no-op
    # on POSIX where stdout is already utf-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass  # Non-stream stdout (e.g. captured in tests) lacks reconfigure
    parser = argparse.ArgumentParser(description="LLM judge over an agent-eval run (spends money)")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--queries-file", default=DEFAULT_QUERIES)
    parser.add_argument("--judge-model", default=DEFAULT_JUDGE_MODEL)
    parser.add_argument("--limit", type=int, default=None, help="judge only the first N transcripts")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.provider.api_key:
        print("no API key configured — the judge needs one", file=sys.stderr)
        return 2
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    queries = {q.id: q for q in load_agent_queries(args.queries_file)}

    per_query: list[dict[str, Any]] = []
    with httpx.Client() as client:
        paths = sorted(p for p in args.run_dir.glob("*-r*.jsonl")
                       if p.name != "ledger.jsonl")
        if args.limit:
            paths = paths[: args.limit]
        for path in paths:
            t = read_transcript(path)
            qid = t.meta.get("query_id")
            if qid not in queries:
                continue
            payload = build_judge_payload(queries[qid], t)
            result = judge_one(client, settings.provider.base_url,
                               settings.provider.api_key, args.judge_model,
                               system_prompt, payload)
            row = {"query_id": qid, "repeat": t.meta.get("repeat", 1), **result}
            if "judge_error" not in result:
                row.update(compute_citation_scores(result, t))
            per_query.append(row)
            print(f"{qid}: {'ERROR' if 'judge_error' in result else row.get('holistic')}")

    graded = [r for r in per_query if "judge_error" not in r]
    def mean(key):
        vals = [r[key] for r in graded if r.get(key) is not None]
        return (sum(vals) / len(vals)) if vals else None
    out = {"judge_model": args.judge_model,
           "judge_prompt_sha256": hashlib.sha256(system_prompt.encode()).hexdigest(),
           "summary": {"n": len(per_query), "errors": len(per_query) - len(graded),
                       "claim_coverage_precision_mean": mean("claim_coverage_precision"),
                       "claim_coverage_recall_mean": mean("claim_coverage_recall"),
                       "holistic_mean": mean("holistic")},
           "per_query": per_query}
    tmp = (args.run_dir / "judge.json").with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(args.run_dir / "judge.json")
    print(json.dumps(out["summary"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
