"""Transcript round-trip + accessor tests.

Why: every downstream tool (scorer, judge, compare, citation replay)
reads transcripts. A silent format drift would corrupt all of them at
once, so the shape is pinned here.
"""
from __future__ import annotations

import json

from eval.agent_transcript import (
    Transcript,
    citations,
    final_answer,
    parsed_output,
    read_transcript,
    retrieve_calls,
    tool_calls,
    usage,
    wall_ms,
    write_transcript,
)

RETRIEVE_OUTPUT = json.dumps({
    "top_score": 4.2,
    "retrieval_id": "r-1",
    "bm25_count": 10, "dense_count": 10, "fused_count": 15,
    "chunks": [
        {"chunk_id": "c-1", "doc_id": "d-1", "doc_title": "FY 2025 Approps",
         "publisher": "jlbc", "fiscal_year": 2025, "doc_type": "approps-agency-pdf",
         "section_path": "ADC", "page_start": 3, "page_end": 3, "bbox": None,
         "text": "ADC General Fund appropriation of $1,391,157,700 in FY 2025.",
         "text_length": 60, "score": 4.2},
    ],
})

DONE_FRAME = {
    "type": "_done",
    "stopReason": "end_turn",
    "finalAnswer": "ADC received $1,391,157,700.",
    "incompleteNote": None,
    "citations": [{"chunkId": "c-1", "claimSpan": "ADC received $1,391,157,700.",
                   "confidence": "verbatim", "quote": "$1,391,157,700",
                   "spanStart": 30, "spanEnd": 44, "citationId": "cit-1",
                   "ok": True, "error": None}],
    "retrievedChunkIds": ["c-1"],
    "toolCalls": [
        {"toolUseId": "t-1", "toolName": "retrieve",
         "input": {"query": "ADC FY 2025"}, "output": RETRIEVE_OUTPUT, "isError": False},
        {"toolUseId": "t-2", "toolName": "cite",
         "input": {"chunk_id": "c-1", "quote": "$1,391,157,700",
                   "confidence": "verbatim", "claim_span": "ADC received $1,391,157,700."},
         "output": json.dumps({"ok": True, "citation_id": "cit-1",
                               "resolved_span_start": 30, "resolved_span_end": 44}),
         "isError": False},
    ],
    "usage": {"inputTokens": 900, "outputTokens": 120, "cacheReadTokens": 700,
              "cacheCreationTokens": 0, "cost": 0.0031},
}


def make_transcript(tmp_path, terminal_extra=None):
    path = tmp_path / "aq-001-r1.jsonl"
    meta = {"query_id": "aq-001", "repeat": 1, "started_at": "2026-08-01T12:00:00Z"}
    events = [{"type": "assistant_thinking", "uuid": "u1"},
              {"type": "tool_use", "toolUseId": "t-1", "toolName": "retrieve",
               "input": {"query": "ADC FY 2025"}}]
    terminal = {"frame": DONE_FRAME, "wall_ms": 48000}
    terminal.update(terminal_extra or {})
    write_transcript(path, meta, events, terminal)
    return path


def test_round_trip(tmp_path):
    t = read_transcript(make_transcript(tmp_path))
    assert isinstance(t, Transcript)
    assert t.meta["query_id"] == "aq-001"
    assert len(t.events) == 2
    assert t.terminal["frame"]["stopReason"] == "end_turn"


def test_accessors(tmp_path):
    t = read_transcript(make_transcript(tmp_path))
    assert final_answer(t) == "ADC received $1,391,157,700."
    assert usage(t)["cost"] == 0.0031
    assert citations(t)[0]["chunkId"] == "c-1"
    assert wall_ms(t) == 48000
    assert [c["toolName"] for c in tool_calls(t)] == ["retrieve", "cite"]
    assert len(tool_calls(t, "cite")) == 1
    rcs = retrieve_calls(t)
    assert rcs[0]["chunks"][0]["chunk_id"] == "c-1"


def test_parsed_output_survives_garbage():
    assert parsed_output({"output": "not json{"}) is None
    assert parsed_output({"output": json.dumps({"ok": True})}) == {"ok": True}


def test_truncated_transcript_reads_as_error(tmp_path):
    # A crash mid-run leaves a file without a terminal line; readers must
    # see an honest error, not an IndexError.
    path = make_transcript(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    path.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    t = read_transcript(path)
    assert t.terminal["frame"]["type"] == "_error"
    assert "truncated" in t.terminal["frame"]["message"]


def test_error_terminal_accessors_degrade(tmp_path):
    path = tmp_path / "err.jsonl"
    write_transcript(path, {"query_id": "aq-009", "repeat": 1},
                     [], {"frame": {"type": "_error", "message": "boom"}, "wall_ms": 10})
    t = read_transcript(path)
    assert final_answer(t) == ""
    assert usage(t) == {}
    assert citations(t) == [] and tool_calls(t) == [] and retrieve_calls(t) == []


def test_malformed_final_line_reads_as_error(tmp_path):
    # The realistic crash shape: write_transcript writes the whole file in one
    # shot, so an interrupted write (crash/disk full/power loss) is far more
    # likely to leave a torn, invalid-JSON final line than to cleanly omit it.
    # The reader must not raise json.JSONDecodeError on this — it's the exact
    # input the truncation handling exists for.
    path = make_transcript(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    lines[-1] = lines[-1][: len(lines[-1]) // 2]  # truncate mid-line: invalid JSON
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t = read_transcript(path)
    # meta and the intact events survive; only the corrupted terminal is lost.
    assert t.meta["query_id"] == "aq-001"
    assert len(t.events) == 2
    assert t.terminal["frame"]["type"] == "_error"
    assert "malformed line" in t.terminal["frame"]["message"]
    assert "truncated" in t.terminal["frame"]["message"]


def test_malformed_middle_line_does_not_crash(tmp_path):
    # A damaged line doesn't have to be the last one — a bit flip or a
    # short-write could land anywhere. The reader must survive that too,
    # rather than assuming corruption only ever hits the terminal.
    path = make_transcript(tmp_path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) >= 3  # meta, >=1 event, terminal
    lines[1] = "{not valid json"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    t = read_transcript(path)
    # Reading stops at the damaged line rather than raising; whatever was
    # parsed before it (meta) is kept, and the lost terminal degrades to the
    # same honest error path as a wholly-truncated file.
    assert t.meta["query_id"] == "aq-001"
    assert t.terminal["frame"]["type"] == "_error"
    assert "malformed line" in t.terminal["frame"]["message"]
