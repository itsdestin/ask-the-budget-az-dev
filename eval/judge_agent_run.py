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

_FENCE_RE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$")


def build_judge_payload(query: AgentQuery, t: Transcript) -> dict[str, Any]:
    chunk_texts: dict[str, str] = {}
    for call in retrieve_calls(t):
        for c in call["chunks"]:
            cid = c.get("chunk_id")
            if cid:
                chunk_texts[cid] = c.get("text") or ""
    cited = {}
    cite_rows = []
    for c in citations(t):
        cite_rows.append({"chunk_id": c.get("chunkId"), "quote": c.get("quote"),
                          "claim_span": c.get("claimSpan"), "ok": bool(c.get("ok"))})
        cid = c.get("chunkId")
        if cid in chunk_texts:
            cited[cid] = chunk_texts[cid]
    return {"question": query.question, "judge_notes": query.judge_notes,
            "should_refuse": query.should_refuse,
            "final_answer": final_answer(t), "citations": cite_rows,
            "cited_chunks": cited}


def parse_judge_json(content: str) -> dict[str, Any]:
    stripped = _FENCE_RE.sub("", content.strip())
    try:
        parsed = json.loads(stripped)
    except ValueError as exc:
        raise ValueError(f"judge returned non-JSON: {content[:200]!r}") from exc
    if not isinstance(parsed, dict) or "load_bearing_claims" not in parsed:
        raise ValueError(f"judge JSON missing load_bearing_claims: {stripped[:200]!r}")
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
    claims = judge_result.get("load_bearing_claims") or []
    covered = sum(1 for c in claims if c.get("cited_verified"))
    emitted = len(citations(t))
    return {
        # covered claims / citations ISSUED: padding citations dilute it.
        "claim_coverage_precision": (covered / emitted) if emitted else None,
        # covered claims / claims that NEEDED citing: uncited key claims hurt.
        "claim_coverage_recall": (covered / len(claims)) if claims else None,
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
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
