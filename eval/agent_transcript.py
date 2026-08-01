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
    lines = [json.dumps({"kind": "meta", **meta}, ensure_ascii=False)]
    lines += [json.dumps({"kind": "event", "event": e}, ensure_ascii=False) for e in events]
    lines.append(json.dumps({"kind": "terminal", **terminal}, ensure_ascii=False))
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def read_transcript(path: str | Path) -> Transcript:
    meta: dict[str, Any] = {}
    events: list[dict[str, Any]] = []
    terminal: dict[str, Any] | None = None
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        kind = row.pop("kind", None)
        if kind == "meta":
            meta = row
        elif kind == "event":
            events.append(row.get("event", {}))
        elif kind == "terminal":
            terminal = row
    if terminal is None:
        # A crash mid-run leaves no terminal line; synthesize an honest
        # error so scorers count it as a failure, not a crash of their own.
        terminal = {"frame": {"type": "_error", "message": "transcript truncated (no terminal line)"},
                    "wall_ms": None}
    return Transcript(meta=meta, events=events, terminal=terminal)


# ---- accessors --------------------------------------------------------
# All accessors degrade to empty values on _error terminals so scorers
# never special-case crashed queries.

def _frame(t: Transcript) -> dict[str, Any]:
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
