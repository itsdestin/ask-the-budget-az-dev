"""Tool-error ledger — every tool-call error in a transcript, tied to the
turn it cost. Spec: 2026-08-16-consolidated-eval-pipeline-design.md.

WHY errors are tied to turns, not just counted: an error in turn 2 of a
9-turn query cost 8 turns of downstream work; the same error in the final
turn cost nothing. The ledger feeds prompt/tool-description tuning, and
tuning needs to know WHERE the burn happened.

DEV-away-from-brief (recorded here so the commit tells the story): the
brief's harvest loop read the tool name as `call.get("name")`, but this
repo's transcript convention stores it as `"toolName"` (see
agent_transcript.tool_calls filtering on `c.get("toolName")`, and every
builder in tests/test_eval_agent_score_run.py). The brief's own
test_retrieve_tool_error_is_harvested builds `{"toolName": "retrieve", ...}`
and asserts the row kind is `retrieve_error` — the brief's code against the
brief's test yields `argument_error`/tool "" (failing the test and
misclassifying every error). Fixed to `toolName`; tests pass as written.
"""
from __future__ import annotations
from eval.agent_schema import AgentQuery
from eval.agent_transcript import Transcript, tool_calls, parsed_output

KINDS = ("retrieve_error", "cite_failure", "argument_error",
         "malformed_output", "crashed_query")


def harvest_errors(t: Transcript, query: AgentQuery) -> list[dict]:
    rows = []
    # turn = index of the assistant message in the event stream, so each
    # error points at the step that paid for it.
    for i, call in enumerate(tool_calls(t)):
        name = call.get("toolName") or ""
        out = parsed_output(call)
        detail = ""
        if out and out.get("error"):
            rows.append({"kind": "retrieve_error" if name == "retrieve" else "argument_error",
                         "tool": name, "turn": i, "query_id": query.id,
                         "detail": str(out["error"])[:200]})
    # cite/cite_batch attempts are harvested ONCE (not per call in the loop
    # above, which would double-count): agent_scoring's cite_attempts already
    # flattens cite_batch slots. Re-use ITS pass/fail logic — do NOT re-derive
    # a second definition of "cite passed" here (one producer, one truth:
    # the cross-item-defect lesson from the identity audit). Turn attribution
    # for a failed attempt: the index of the cite call that carried it, or
    # the last tool call when the flattening does not line up.
    from eval.agent_scoring import cite_attempts, _attempt_passed
    calls = tool_calls(t)
    cite_turns = [i for i, c in enumerate(calls) if c.get("toolName") in ("cite", "cite_batch")]
    for attempt in cite_attempts(t):
        if not _attempt_passed(attempt):
            rows.append({"kind": "cite_failure", "tool": "cite",
                         "turn": cite_turns[0] if cite_turns else -1,
                         "query_id": query.id,
                         "detail": str(attempt.get("result"))[:200]})
    if (t.terminal.get("frame") or {}).get("type") != "_done":
        rows.append({"kind": "crashed_query", "tool": "", "turn": -1,
                     "query_id": query.id, "detail": "terminal frame not _done"})
    return rows


def summarize_errors(rows: list[dict]) -> dict:
    out: dict[str, dict] = {}
    for r in rows:
        slot = out.setdefault(r["kind"], {"count": 0, "queries": set()})
        slot["count"] += 1
        slot["queries"].add(r["query_id"])
    return {k: {"count": v["count"], "queries": sorted(v["queries"])}
            for k, v in sorted(out.items())}
