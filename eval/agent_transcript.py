"""Transcript JSONL format for Layer 2 agent-eval runs.

One file per (query, repeat): a `meta` line, one `event` line per
harness event, and one `terminal` line carrying the session's _done (or
_error) frame plus wall-clock. Scoring is decoupled from running, so
this file IS the interface between the money-spending runner and every
free downstream tool.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Transcript:
    meta: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)
    terminal: dict[str, Any] = field(default_factory=dict)


def write_transcript(
    path: str | Path,
    meta: dict[str, Any],
    events: list[dict[str, Any]],
    terminal: dict[str, Any],
) -> None:
    # ensure_ascii=False: document text (agency names, en-dashes, etc.) is
    # frequently non-ASCII — writing it as \uXXXX escapes would still round-trip
    # correctly, but every downstream tool that greps or diffs raw transcript
    # text would see garbage instead of the actual characters.
    lines = [json.dumps({"kind": "meta", **meta}, ensure_ascii=False)]
    lines += [json.dumps({"kind": "event", "event": e}, ensure_ascii=False) for e in events]
    lines.append(json.dumps({"kind": "terminal", **terminal}, ensure_ascii=False))
    # Write to a sibling temp file and rename into place, the way every other
    # artifact in this eval is written (manifest.json, scores.json). The plain
    # write this replaced could leave a HALF-WRITTEN transcript on a crash or a
    # flaky share write — the exact torn file read_transcript() below degrades
    # to a synthetic "_error" record. That reader still earns its keep (a
    # transcript written by an older run, or damaged after the fact, can still
    # be torn), but a run should not be manufacturing the damage it then
    # tolerates: a torn file scores as a FAILED QUERY, indistinguishable from
    # the agent genuinely failing. Same directory as the target so the replace
    # is atomic (a rename across filesystems is not).
    path = Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    tmp.replace(path)


def read_transcript(path: str | Path) -> Transcript:
    meta: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    corrupted = False
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            # write_transcript builds the whole file in memory and writes it in
            # one Path.write_text call, so a crash/power-loss/full-disk mid-write
            # is far more likely to leave a torn (invalid-JSON) FINAL line than a
            # cleanly absent one. Treat any unparsable line as that same kind of
            # damage rather than letting the exception escape — stop reading
            # right there, since anything after an unparsable line is equally
            # suspect, and fall through to the same synthesized-error path used
            # for a wholly-missing terminal.
            corrupted = True
            break
        if not isinstance(row, dict):
            # A line can be syntactically VALID JSON and still not be an
            # object — `[1, 2, 3]`, `"a string"`, `null` all parse cleanly but
            # would crash `row.pop("kind", ...)` below (TypeError on the list,
            # AttributeError on the string/None) instead of raising the
            # json.JSONDecodeError the guard above already catches. That's the
            # same class of damage (a torn/bit-flipped line), so route it
            # through the identical break-and-degrade path rather than a
            # second, differently-worded failure — a reader should only ever
            # have to recognize one shape of "this file is broken".
            corrupted = True
            break
        # "kind" is a routing tag, not payload — pop it off and dispatch by
        # value so each line lands in its list/slot without a second parse pass.
        kind = row.pop("kind", None)
        if kind == "meta":
            meta = row
        elif kind == "event":
            events.append(row.get("event", {}))
        elif kind == "terminal":
            terminal = row
    if terminal is None:
        # A crash mid-run leaves no terminal line at all, or a torn write left
        # one line unparsable (caught above); either way synthesize an honest
        # error so scorers count it as a failure, not a crash of their own.
        # Message says the FILE is damaged/incomplete, not that the agent
        # failed — those are different findings for anyone reading results.
        reason = "malformed line" if corrupted else "no terminal line"
        terminal = {"frame": {"type": "_error", "message": f"transcript truncated ({reason})"},
                    "wall_ms": None}
    return Transcript(meta=meta, events=events, terminal=terminal)


# ---- accessors --------------------------------------------------------
# All accessors degrade to empty values on _error terminals so scorers
# never special-case crashed queries.

def _frame(t: Transcript) -> dict[str, Any]:
    # `.get("frame", {})` alone isn't enough: a terminal row can carry an
    # explicit `"frame": null` (not just a missing key), which .get() would
    # happily return as None and crash every accessor's .get() call below.
    # The trailing `or {}` catches that explicit-null case too.
    return t.terminal.get("frame", {}) or {}


def final_answer(t: Transcript) -> str:
    return _frame(t).get("finalAnswer") or ""


def usage(t: Transcript) -> dict[str, Any]:
    return _frame(t).get("usage") or {}


def citations(t: Transcript) -> list[dict[str, Any]]:
    return _frame(t).get("citations") or []


def tool_calls(t: Transcript, name: str | None = None) -> list[dict[str, Any]]:
    calls = _frame(t).get("toolCalls") or []
    return calls if name is None else [c for c in calls if c.get("toolName") == name]


def wall_ms(t: Transcript) -> int | None:
    return t.terminal.get("wall_ms")


def parsed_output(call: dict[str, Any]) -> dict[str, Any] | None:
    """The tool output is stored as a JSON string (harness convention);
    parse defensively — a malformed output must not crash scoring."""
    try:
        out = json.loads(call.get("output") or "")
    except (TypeError, ValueError):
        return None
    return out if isinstance(out, dict) else None


def annotation(t: Transcript) -> dict[str, Any]:
    """The figure annotation recorded on the terminal frame. Absent on
    transcripts recorded before citation linking shipped."""
    return _frame(t).get("annotation") or {"figures": []}


def retrieve_calls(t: Transcript) -> list[dict[str, Any]]:
    """Each retrieve call's parsed output dict (with its 'chunks' list),
    in call order. Calls whose output failed to parse are skipped."""
    results = []
    for call in tool_calls(t, "retrieve"):
        out = parsed_output(call)
        if out is not None:
            out.setdefault("chunks", [])
            results.append(out)
    return results
