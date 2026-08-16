"""Tests for identity/history_migrate.py — rewriting saved AI Mode
transcripts onto the renamed doc/chunk ids (spec I10).

Nothing here touches the analyst's real conversations directory. Every test
points `JLBC_HISTORY_DIR` at `tmp_path` (the same env-var seam
`harness/history.py::conversations_dir` already exposes for its own test
suite) and writes/read raw JSON files directly, so both this module AND the
`harness.history.load`/`save` helpers it reuses resolve to the same tmp
directory.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from identity.history_migrate import migrate_history


@pytest.fixture(autouse=True)
def _history_dir(tmp_path, monkeypatch):
    root = tmp_path / "conversations"
    root.mkdir()
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(root))
    return root


def _write_raw(root: Path, conversation_id: str, payload: dict[str, Any]) -> Path:
    """Write a transcript file DIRECTLY (bypassing `harness.history.save`,
    which always stamps `version: 1`) — this is what lets a test build a
    genuine version-0 (pre-stamp) fixture.

    Stamps `payload["id"] = conversation_id` regardless of whatever the
    template already carried: `harness.history.save()` writes to the path
    derived from the TRANSCRIPT'S OWN id (`_path_for(transcript.id)`), not
    the file it was loaded from, so an id that disagrees with the filename
    would make a migrated write land on a different file than the one under
    test — silently, since save() never errors on that.
    """
    payload = {**payload, "id": conversation_id}
    path = root / f"{conversation_id}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def _tool_message(chunks: list[dict[str, Any]], **extra) -> dict[str, Any]:
    content = json.dumps({"chunks": chunks, "top_score": 4.2, **extra})
    return {
        "role": "tool", "tool_call_id": "t1", "name": "retrieve",
        "content": content,
    }


def _chunk(chunk_id: str, doc_id: str, *, alias: str = "c1") -> dict[str, Any]:
    """Mirrors `harness/tools.py`'s retrieve() chunk shape exactly enough to
    exercise the rewrite — id fields plus a couple of untouched fields that
    must survive byte-for-byte."""
    return {
        "chunk_id": chunk_id, "alias": alias, "doc_id": doc_id,
        "doc_title": "Some Title", "publisher": "jlbc", "fiscal_year": 2030,
        "doc_type": "topic-pdf", "text": "the quick brown fox", "score": 3.1,
    }


def _figure(*, primary=None, additional=None, attested=None, near_miss=None,
            verdict="linked") -> dict[str, Any]:
    return {
        "text": "$1.00", "start": 0, "end": 5, "index": 1, "verdict": verdict,
        "primary": primary, "additional": additional or [],
        "attested_chunk_ids": attested or [], "link_basis": "tag",
        "ambiguity_count": None, "near_miss": near_miss, "operation": None,
    }


def _hit(chunk_id: str, doc_id: str) -> dict[str, Any]:
    return {
        "chunk_id": chunk_id, "source_text": "1.00", "start": 0, "end": 4,
        "doc_id": doc_id, "doc_type": "topic-pdf", "doc_title": "Some Title",
        "publisher": "jlbc", "fiscal_year": 2030, "page_start": 3,
        "page_end": 3, "bbox": [0.0, 0.0, 1.0, 1.0],
    }


def _base_transcript(messages: list[dict[str, Any]], *, version: int | None = 1) -> dict[str, Any]:
    payload = {
        "id": "conv", "title": "A chat", "corpus": "budget",
        "created_at": "2030-01-01T00:00:00+00:00",
        "updated_at": "2030-01-01T00:00:00+00:00",
        "title_is_manual": False, "messages": messages,
    }
    if version is not None:
        payload["version"] = version
    return payload


_CHUNK_MAP = {"jlbc-approps-fy2030-zzz-0000": "jlbc-baseline-fy2030-zzz-0000"}
_DOC_MAP = {"jlbc-approps-fy2030-zzz": "jlbc-baseline-fy2030-zzz"}


# ---------------------------------------------------------------------------
# tool-role message content — the verbatim retrieve() JSON
# ---------------------------------------------------------------------------


def test_tool_message_chunk_ids_and_doc_ids_are_rewritten(_history_dir):
    messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.inspected == 1
    assert result.changed == 1
    assert result.ids_rewritten == 2  # one chunk_id + one doc_id

    on_disk = json.loads((_history_dir / "conv.json").read_text(encoding="utf-8"))
    tool_content = json.loads(on_disk["messages"][0]["content"])
    chunk = tool_content["chunks"][0]
    assert chunk["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"
    assert chunk["doc_id"] == "jlbc-baseline-fy2030-zzz"
    # untouched fields survive
    assert chunk["alias"] == "c1"
    assert chunk["text"] == "the quick brown fox"
    assert chunk["score"] == 3.1


def test_a_non_retrieve_tool_message_passes_through_unchanged(_history_dir):
    """A `cite_batch` ack, or any tool result with no "chunks" key, must be
    left byte-identical — not just semantically unaffected."""
    ack_content = json.dumps({"ok": True, "citation_id": "x1"})
    messages = [
        {"role": "tool", "tool_call_id": "t1", "name": "cite_batch", "content": ack_content},
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.changed == 0
    assert result.ids_rewritten == 0
    on_disk = json.loads((_history_dir / "conv.json").read_text(encoding="utf-8"))
    assert on_disk["messages"][0]["content"] == ack_content


def test_a_malformed_tool_content_string_does_not_raise(_history_dir):
    """Best-effort, matching `harness/session.py::_chunk_ids`'s own contract
    for this exact string: not-JSON contributes zero rewrites, never a
    crash that would cost the WHOLE file (or the whole pass)."""
    messages = [
        {"role": "tool", "tool_call_id": "t1", "name": "retrieve", "content": "not json at all"},
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.inspected == 1
    assert result.changed == 0
    assert result.corrupt == []


# ---------------------------------------------------------------------------
# assistant annotation.figures — the other of the two independent places
# ---------------------------------------------------------------------------


def test_annotation_primary_and_additional_hits_are_rewritten(_history_dir):
    figures = [
        _figure(
            primary=_hit("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz"),
            additional=[_hit("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")],
            attested=["jlbc-approps-fy2030-zzz-0000"],
        ),
    ]
    messages = [
        {"role": "assistant", "content": "$1.00 [[c1]]", "tool_calls": None,
         "annotation": {"figures": figures}},
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.changed == 1
    on_disk = json.loads((_history_dir / "conv.json").read_text(encoding="utf-8"))
    fig = on_disk["messages"][0]["annotation"]["figures"][0]
    assert fig["primary"]["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"
    assert fig["primary"]["doc_id"] == "jlbc-baseline-fy2030-zzz"
    assert fig["additional"][0]["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"
    assert fig["attested_chunk_ids"] == ["jlbc-baseline-fy2030-zzz-0000"]
    # untouched sibling fields on the hit survive
    assert fig["primary"]["source_text"] == "1.00"
    assert fig["primary"]["page_start"] == 3


def test_annotation_near_miss_chunk_id_is_rewritten(_history_dir):
    figures = [
        _figure(
            verdict="unverified",
            near_miss={"chunk_id": "jlbc-approps-fy2030-zzz-0000",
                       "source_text": "1.05", "value": 1.05, "distance": 0.05},
        ),
    ]
    messages = [
        {"role": "assistant", "content": "$1.00", "tool_calls": None,
         "annotation": {"figures": figures}},
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    on_disk = json.loads((_history_dir / "conv.json").read_text(encoding="utf-8"))
    fig = on_disk["messages"][0]["annotation"]["figures"][0]
    assert fig["near_miss"]["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"
    assert fig["near_miss"]["value"] == 1.05  # untouched sibling field


def test_an_empty_annotation_is_left_alone(_history_dir):
    messages = [
        {"role": "assistant", "content": "no figures here", "tool_calls": None,
         "annotation": {"figures": []}},
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.changed == 0
    assert result.ids_rewritten == 0


# ---------------------------------------------------------------------------
# version 0 vs version 1 — "migrate both", the stamp's first real use
# ---------------------------------------------------------------------------


def test_a_pre_versioning_file_is_migrated_same_as_a_stamped_one(_history_dir):
    """A file written before `SCHEMA_VERSION` existed carries no "version"
    key at all and reads back as 0 (`harness/history.py::_read`). This pass
    must not special-case that away — both a v0 and a v1 file carrying the
    same stale id get rewritten identically."""
    v0_messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    v1_messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    _write_raw(_history_dir, "conv-v0", _base_transcript(v0_messages, version=None))
    _write_raw(_history_dir, "conv-v1", _base_transcript(v1_messages, version=1))

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.inspected == 2
    assert result.changed == 2

    for conv_id in ("conv-v0", "conv-v1"):
        on_disk = json.loads((_history_dir / f"{conv_id}.json").read_text(encoding="utf-8"))
        tool_content = json.loads(on_disk["messages"][0]["content"])
        assert tool_content["chunks"][0]["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"
        # `harness.history.save` always stamps SCHEMA_VERSION on write --
        # so a rewritten v0 file is now v1 too, as a side effect of being
        # touched at all. This is the "first real use" of that stamp.
        assert on_disk["version"] == 1


# ---------------------------------------------------------------------------
# degradation — one corrupt file costs exactly one conversation
# ---------------------------------------------------------------------------


def test_a_corrupt_file_costs_exactly_one_conversation(_history_dir):
    good_messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    _write_raw(_history_dir, "good", _base_transcript(good_messages))
    (_history_dir / "corrupt.json").write_text("{not valid json", encoding="utf-8")
    (_history_dir / "not-an-object.json").write_text("null", encoding="utf-8")

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.inspected == 3
    assert result.changed == 1
    assert set(result.corrupt) == {"corrupt", "not-an-object"}
    # the corrupt files are untouched, not "repaired" or deleted
    assert (_history_dir / "corrupt.json").read_text(encoding="utf-8") == "{not valid json"
    on_disk_good = json.loads((_history_dir / "good.json").read_text(encoding="utf-8"))
    tool_content = json.loads(on_disk_good["messages"][0]["content"])
    assert tool_content["chunks"][0]["chunk_id"] == "jlbc-baseline-fy2030-zzz-0000"


# ---------------------------------------------------------------------------
# dry run vs apply; the pre-write backup
# ---------------------------------------------------------------------------


def test_dry_run_reports_but_writes_nothing_and_makes_no_backup(_history_dir):
    messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    path = _write_raw(_history_dir, "conv", _base_transcript(messages))
    before_bytes = path.read_bytes()

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=True)

    assert result.changed == 1
    assert result.ids_rewritten == 2  # one chunk_id + one doc_id
    assert path.read_bytes() == before_bytes, "dry run must never write"
    assert result.backup_dir is None
    siblings = list(_history_dir.parent.iterdir())
    assert siblings == [_history_dir], "dry run must not create a backup directory"


def test_apply_backs_up_the_whole_directory_before_writing(_history_dir):
    messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))
    before = (_history_dir / "conv.json").read_text(encoding="utf-8")

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.backup_dir is not None
    assert result.backup_dir.is_dir()
    backed_up = (result.backup_dir / "conv.json").read_text(encoding="utf-8")
    assert backed_up == before, "the backup must hold the PRE-migration content"
    # the live file has actually changed
    after = (_history_dir / "conv.json").read_text(encoding="utf-8")
    assert after != before


def test_no_backup_flag_skips_the_backup(_history_dir):
    messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(
        chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False, backup=False,
    )

    assert result.backup_dir is None
    assert result.changed == 1


# ---------------------------------------------------------------------------
# report counts
# ---------------------------------------------------------------------------


def test_report_counts_are_accurate_across_a_mixed_directory(_history_dir):
    changed_messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    unchanged_messages = [
        _tool_message([_chunk("some-other-doc-0000", "some-other-doc")]),
    ]
    _write_raw(_history_dir, "changed", _base_transcript(changed_messages))
    _write_raw(_history_dir, "unchanged", _base_transcript(unchanged_messages))
    (_history_dir / "broken.json").write_text("{oops", encoding="utf-8")

    result = migrate_history(chunk_id_map=_CHUNK_MAP, doc_id_map=_DOC_MAP, dry_run=False)

    assert result.inspected == 3
    assert result.changed == 1
    assert result.ids_rewritten == 2  # one chunk_id + one doc_id, in "changed" only
    assert result.corrupt == ["broken"]


def test_an_empty_id_map_is_a_pure_noop(_history_dir):
    messages = [
        _tool_message([_chunk("jlbc-approps-fy2030-zzz-0000", "jlbc-approps-fy2030-zzz")]),
    ]
    _write_raw(_history_dir, "conv", _base_transcript(messages))

    result = migrate_history(chunk_id_map={}, doc_id_map={}, dry_run=False)

    assert result.inspected == 0
    assert result.changed == 0
    assert result.backup_dir is None
