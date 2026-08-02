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
    Transcript, annotation, citations, final_answer, read_transcript,
    retrieve_calls,
)
from harness.settings import load_settings

DEFAULT_QUERIES = "eval/agent_queries.yaml"
# Destin's call, 2026-08-02: glm-5.2 judges everything. Measured against
# claude-sonnet-5 over one identical set of 31 answers — 0 errors, holistic
# means 4.13 vs 4.06, EVERY disagreement within one point, rank correlation
# 0.89, and comparable claim counts (144 vs 135), which is what keeps
# claim_coverage_* meaning the same thing. ~8x cheaper per pass, so every
# run can be judged instead of only the ones that gate a merge.
#
# Known and accepted: this is currently also the model under test, so it
# grades its own output. It caught 5 of the 9 answers sonnet graded weak,
# missing 4 that sit on the 3-vs-4 boundary. The confound disappears if the
# agent tier ever moves off glm-5.2.
DEFAULT_JUDGE_MODEL = "z-ai/glm-5.2"
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


def render_annotated_answer(answer: str, annotation: dict[str, Any]) -> str:
    """The answer as the analyst sees it, with each figure's citation state
    inline. The webapp draws chips from this same annotation, so the judge
    grades the artifact the user actually reads."""
    figures = sorted(annotation.get("figures") or [],
                     key=lambda f: f.get("start", 0), reverse=True)
    out = answer
    # Right-to-left insertion: a marker inserted early would shift every
    # later figure's offsets.
    for fig in figures:
        verdict = fig.get("verdict")
        if verdict == "linked":
            marker = f" [{fig.get('index')}]"
        elif verdict == "derived":
            inputs = ", ".join(str(i) for i in fig.get("derived_from") or [])
            marker = f" [DERIVED: {inputs}]"
        else:
            marker = " [UNCITED]"
        end = fig.get("end", 0)
        out = out[:end] + marker + out[end:]
    return out


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
    # The annotated answer is what the analyst actually reads. It rides
    # ALONGSIDE final_answer rather than replacing it, so the judge can
    # still quote the answer's own prose without the markers in it.
    ann = annotation(t)
    counts = {"linked": 0, "derived": 0, "unverified": 0}
    for fig in ann.get("figures") or []:
        verdict = fig.get("verdict")
        if verdict in counts:
            counts[verdict] += 1
    return {"question": query.question, "judge_notes": query.judge_notes,
            "should_refuse": query.should_refuse,
            "final_answer": final_answer(t), "citations": cite_rows,
            "cited_chunks": cited,
            "annotated_answer": render_annotated_answer(final_answer(t), ann),
            "figure_counts": counts}


# The prompt asks for a 1-5 grade. Anything outside that range is not a
# grade we can average — see _coerce_holistic.
HOLISTIC_MIN, HOLISTIC_MAX = 1, 5


def _coerce_holistic(value: Any) -> float | None:
    """Return the judge's holistic grade as a real number, or None when the
    reply carried something that cannot honestly be read as a 1-5 grade.

    WHY this exists: `holistic` is the one summary field that comes
    straight from the MODEL, and main()'s mean() adds it up. A reply of
    `"holistic": "4"` (a string) used to raise TypeError inside that sum —
    AFTER the whole loop had run and BEFORE judge.json was written, so
    every already-paid grade in the run was lost. That reply shape is
    likely, not exotic: the prompt template used to literally show
    `"holistic": 1-5`, which is not valid JSON, so a model echoing it back
    as "4" or "4/5" is a reasonable thing to happen.

    A clean numeric string ("4", "4.0") has exactly one honest reading, so
    it is coerced. Anything else ("4/5", "high", a list) has no single
    honest reading, so it becomes None — recorded as "not gradable" rather
    than guessed at, and parse_judge_json keeps the original under
    `holistic_raw` so nothing is thrown away.
    """
    if isinstance(value, bool):
        # bool is a subclass of int in Python: True would silently grade 1.
        return None
    if isinstance(value, (int, float)):
        num = float(value)
    elif isinstance(value, str):
        try:
            num = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    # Also rejects nan/inf, whose comparisons are all False. An out-of-range
    # number (0, 47) is not a 1-5 grade, and averaging it would quietly skew
    # holistic_mean with no error anywhere.
    if not (HOLISTIC_MIN <= num <= HOLISTIC_MAX):
        return None
    return int(num) if num == int(num) else num


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
    # WHY normalize instead of raising: a malformed `holistic` is a bad
    # GRADE, not a bad grading run — the claim list next to it may be
    # perfectly good, and rejecting the whole row would throw away citation
    # scores we already paid for. So the row survives with holistic=None
    # (mean() skips None, so it is excluded from holistic_mean rather than
    # counted as a bad answer) and the model's literal reply preserved
    # under `holistic_raw` for anyone reading judge.json later.
    if parsed.get("holistic") is not None:
        grade = _coerce_holistic(parsed["holistic"])
        if grade is None:
            parsed["holistic_raw"] = parsed["holistic"]
        parsed["holistic"] = grade
    return parsed


# A reasoning model spends completion tokens thinking BEFORE it answers.
# With no cap, OpenRouter's default cut deepseek-v4-flash-0731 off mid-thought
# on 5 of 31 queries in a paid run: finish_reason "length", content null, the
# grade lost. This budget leaves room for the reasoning AND the JSON after it.
JUDGE_MAX_TOKENS = 8000


def judge_one(client: httpx.Client, base_url: str, api_key: str, model: str,
              system_prompt: str, payload: dict[str, Any],
              *, reasoning: bool = True) -> dict[str, Any]:
    """Grade one answer.

    `reasoning=False` asks the provider to skip chain-of-thought. On a
    reasoning model that measured 15x faster and 2.75x cheaper for this
    structured task — but it is opt-in, because thinking changes the
    grades and a judge swap must be a deliberate, measured decision.
    The field is omitted entirely by default: most models have no
    reasoning control and sending it is a needless compatibility risk.
    """
    try:
        body: dict[str, Any] = {
            "model": model, "temperature": 0,
            "max_tokens": JUDGE_MAX_TOKENS,
            "messages": [{"role": "system", "content": system_prompt},
                         {"role": "user",
                          "content": json.dumps(payload, ensure_ascii=False)}],
        }
        if not reasoning:
            body["reasoning"] = {"enabled": False}
        resp = client.post(
            f"{base_url.rstrip('/')}/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json=body,
            timeout=600.0)
        resp.raise_for_status()
        choice = resp.json()["choices"][0]
        content = choice["message"].get("content")
        if content is None:
            # Name the real cause. "'NoneType' has no attribute 'strip'"
            # told the operator nothing about a truncated reasoning trace.
            finish = choice.get("finish_reason")
            raise ValueError(
                f"judge returned no content (finish_reason={finish!r}) — a "
                f"reasoning model likely exhausted max_tokens before answering")
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
    # WHY the denominator is max(citations issued, covered claims) and not
    # just "citations issued": the numerator counts CLAIMS while the old
    # denominator counted CITATIONS, so nothing tied the two together and
    # the ratio was UNBOUNDED — 1 citation covering 3 claims scored 3.0.
    # That is the modal budget answer, not a corner case (a three-figure
    # comparison is often cited once because one table row holds the whole
    # thing), and the same answer cited three times scored 1.0. So the
    # metric's gradient pointed at emitting FEWER citations — exactly the
    # behavior it exists to punish, and the reason the design spec rejected
    # plain verified-rate ("it rewards citing less and citing only easy
    # claims — the opposite of Invariant 1").
    #
    # Taking the max fixes that:
    #   * bounded at 1.0, so the number can no longer be gamed upward;
    #   * padding still hurts — 1 covered claim with 5 citations = 0.2;
    #   * 1 citation legitimately covering 3 claims = 1.0, which is CORRECT
    #     AND DELIBERATE. The project's stated goal is "a smaller number of
    #     high-value citations that back the most important claims", so that
    #     efficiency is the desired behavior, not something to penalize.
    #   * the other half of the property is claim_coverage_recall below,
    #     unchanged: an important claim left uncited lowers it. Precision
    #     alone can't be gamed by citing less; recall alone can't be gamed
    #     by citing everything. Read them together.
    denominator = max(emitted, covered)
    return {
        # covered claims / max(citations ISSUED, covered): padding dilutes it.
        # `if emitted else None` is LOAD-BEARING and unchanged: a correct
        # refusal (no citations, no claims) must read None = "not
        # applicable", never 0.0 = "bad".
        "claim_coverage_precision": (covered / denominator) if emitted else None,
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
    parser.add_argument("--no-reasoning", action="store_true",
                        help="ask the provider to skip chain-of-thought. On a "
                             "reasoning judge this measured 15x faster and 2.75x "
                             "cheaper — but it changes the grades, so a run using "
                             "it is not comparable to one without.")
    args = parser.parse_args()

    settings = load_settings()
    if not settings.provider.api_key:
        print("no API key configured — the judge needs one", file=sys.stderr)
        return 2
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    queries = {q.id: q for q in load_agent_queries(args.queries_file)}

    per_query: list[dict[str, Any]] = []
    interrupted = False
    with httpx.Client() as client:
        paths = sorted(p for p in args.run_dir.glob("*-r*.jsonl")
                       if p.name != "ledger.jsonl")
        if args.limit:
            paths = paths[: args.limit]
        try:
            for path in paths:
                # WHY this try/except: judge_one already swallows failures of
                # the model CALL, but everything around it — reading a torn
                # transcript, building the payload, scoring the result — can
                # still raise, and judge.json is written ONCE after the loop.
                # So a single bad file used to discard every already-paid
                # grade in the run. One bad row must cost one row.
                try:
                    t = read_transcript(path)
                    qid = t.meta.get("query_id")
                    if qid not in queries:
                        continue
                    payload = build_judge_payload(queries[qid], t)
                    result = judge_one(client, settings.provider.base_url,
                                       settings.provider.api_key, args.judge_model,
                                       system_prompt, payload,
                                       reasoning=not args.no_reasoning)
                    row = {"query_id": qid, "repeat": t.meta.get("repeat", 1), **result}
                    if "judge_error" not in result:
                        row.update(compute_citation_scores(result, t))
                except Exception as exc:
                    # query_id comes from the filename here because the
                    # failure may BE that the file couldn't be read.
                    row = {"query_id": path.stem, "repeat": None,
                           "judge_error": f"{type(exc).__name__}: {exc}"}
                per_query.append(row)
                print(f"{row['query_id']}: "
                      f"{'ERROR' if 'judge_error' in row else row.get('holistic')}")
        except KeyboardInterrupt:
            # A judge run spends real money per row. Ctrl-C keeps whatever
            # has already been graded instead of binning the lot; the exit
            # code below says the run was cut short.
            print("interrupted — writing the rows graded so far", file=sys.stderr)
            interrupted = True

    graded = [r for r in per_query if "judge_error" not in r]
    def mean(key):
        # WHY the isinstance check (and not just `is not None`): `holistic`
        # is supplied by the MODEL, and a non-number there — "4", "4/5", a
        # list — crashes sum() with a TypeError at the very end of the run,
        # after every row has been paid for and before judge.json is
        # written. parse_judge_json already normalizes that field, so this
        # is defense in depth for any future summary field that isn't
        # normalized yet. bool is excluded because it would add as 0/1.
        vals = [r[key] for r in graded
                if isinstance(r.get(key), (int, float)) and not isinstance(r.get(key), bool)]
        return (sum(vals) / len(vals)) if vals else None
    out = {"judge_model": args.judge_model,
           "judge_reasoning": not args.no_reasoning,
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
    # 130 = the shell's conventional "killed by Ctrl-C", so a script driving
    # this can tell a complete run from a partial one. The partial results
    # are on disk either way.
    return 130 if interrupted else 0


if __name__ == "__main__":
    raise SystemExit(main())
