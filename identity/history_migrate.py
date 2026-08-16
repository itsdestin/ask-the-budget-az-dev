"""Rewrite saved AI Mode conversations onto the renamed doc/chunk ids
(spec I10) -- the part of the doc_id rename nobody expects.

## Why this exists at all

`identity/rename_docs.py` renames 22 documents' doc_ids (and every one of
their chunk_ids with them) because their own id disagrees with their own
source_url. That is a full delete-and-re-add in the corpus, so the NEW ids
appear nowhere in any AI Mode conversation an analyst already saved --
those transcripts still reference the OLD, now-deleted chunk_ids.

Saved conversations persist chunk_ids in exactly two independent places,
confirmed on real files (20 stored transcripts, 42 distinct doc_ids):

1. **The figure annotation** `citation/annotate.py` writes onto the final
   assistant message of a turn (`message["annotation"]["figures"]`) --
   each figure's `primary`/`additional` source records carry `chunk_id` and
   `doc_id`, `attested_chunk_ids` is a list of chunk_ids, and an
   unverified figure's `near_miss` carries one more `chunk_id`. This is
   what the webapp reads to render citation chips and to open the PDF
   viewer at a chip's source page (`harness/session.py::_attach_annotation`).

2. **The verbatim `retrieve()` JSON** inside every `role: "tool"` message's
   `content` string (`harness/tools.py`'s response shape: `{"chunks": [
   {"chunk_id": ..., "doc_id": ..., ...}, ...]}`). `harness/history.py`'s
   own module docstring says NOT to prune these ("Do NOT prune tool
   results from the stored history: a dangling assistant `tool_calls`
   message without its `{"role": "tool"}` reply is a malformed request
   that the provider 400s") -- so they are permanent, and
   `harness/session.py::_retrieved_chunk_map` reads them back on every
   LATER turn of a resumed conversation to rebuild the annotator's chunk
   pool (its own comment: "scoped to the CONVERSATION ... because the
   model legitimately re-uses a number it read two questions ago").

Without this migration, clicking a citation chip that points at one of the
22 renamed documents 404s (`app/routes/pdf.py::/api/chunks/{id}`), and the
webapp's own click-time check (H5, `harness/history.py`'s design notes)
correctly but unhelpfully reports "Source no longer available" -- a HARD,
VISIBLE break for an analyst re-opening a chat they saved, not a graceful
degradation. And on a resumed conversation, a stale chunk_id inside a
retrieve() tool message means a later turn's tag (`[[cN]]`, spec A1-A3)
can never verify against it either -- the annotator's conversation-wide
pool would simply be missing that chunk.

## What is deliberately NOT touched

`self.citations` (the OLD pre-attested-linking `cite()`/`cite_batch()` ack
list, `chunkId` camelCase) is never written to a saved transcript at all --
it only ever rides the live `_done` SSE frame
(`harness/session.py::_final_frame`), which `app/routes/conversations.py`
does not persist. Verified directly against the 20 real transcript files
on this machine: no message anywhere carries a `citations` key. A model's
`cite_batch` TOOL CALL arguments (`message["tool_calls"][].function
.arguments`) DO still contain old chunk_ids in some real transcripts (the
`cite`/`cite_batch` tools remain registered even though attested linking
no longer relies on them for chip rendering) -- but nothing reads them back
on load or resume; they are inert historical residue, and rewriting them
would risk corrupting a call-arguments string for zero behavioural benefit.
Only the two places above are ever consulted again.

## Degradation: matches harness/history.py's own promise exactly

One corrupt or unreadable transcript costs this pass exactly one
conversation, never the whole rail -- this module reuses
`harness.history.load`/`save` directly rather than re-implementing the read
path, so it inherits that degradation for free instead of risking a second,
subtly different implementation of it.

## Invariant 7

This module imports `harness.history`, which itself never imports
`store.config` (that is what makes "transcripts never learn where the
share is" structural rather than a promise -- see that module's own
docstring). Importing `harness.history` from here does not weaken that:
this module ALSO never imports `store.config`, and the id map it rewrites
onto disk is handed in by the CALLER (the CLI below reads it from
`identity.rename_docs`'s own `--out` JSON) rather than being re-derived
from the corpus.

## The version stamp's first real use

`harness/history.py::SCHEMA_VERSION` was written 2026-08-03 with the
comment "Nothing reads it today -- that is the point of writing it now
rather than later." This is the first thing that ever reads (and acts on)
it: a transcript written before the stamp existed reads back as version 0,
and BOTH a version-0 and a version-1 file get their embedded ids rewritten
identically here -- there is no reason to special-case either shape away.
`harness.history.save()` always re-stamps `SCHEMA_VERSION` on write, so a
rewritten v0 file becomes v1 as a side effect of being touched at all.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping


def _default_progress(message: str) -> None:
    print(f"identity.history_migrate: {message}", file=sys.stderr, flush=True)


@dataclass
class HistoryMigrateResult:
    inspected: int = 0
    changed: int = 0
    ids_rewritten: int = 0
    # Conversation ids (filename stems) that could not be read at all --
    # left untouched on disk, exactly matching harness/history.py's own
    # "one corrupt file costs one chat" contract.
    corrupt: list[str] = field(default_factory=list)
    backup_dir: Path | None = None


def _rewrite_hit(
    hit: dict[str, Any], chunk_id_map: Mapping[str, str], doc_id_map: Mapping[str, str],
) -> int:
    """One `primary`/`additional`/`near_miss`-shaped source record
    (`citation/annotate.py::_hit_dict`). Returns how many fields changed."""
    n = 0
    chunk_id = hit.get("chunk_id")
    if isinstance(chunk_id, str) and chunk_id in chunk_id_map:
        hit["chunk_id"] = chunk_id_map[chunk_id]
        n += 1
    doc_id = hit.get("doc_id")
    if isinstance(doc_id, str) and doc_id in doc_id_map:
        hit["doc_id"] = doc_id_map[doc_id]
        n += 1
    return n


def _rewrite_annotation(
    annotation: Any, chunk_id_map: Mapping[str, str], doc_id_map: Mapping[str, str],
) -> int:
    """Mutates `annotation["figures"]` in place (`citation/annotate.py`'s
    exact shape). Returns how many id fields were rewritten. Best-effort --
    a malformed annotation (not a dict, no "figures" list) contributes zero
    rewrites rather than raising, matching this module's degrade-per-file
    policy at the field level too."""
    if not isinstance(annotation, dict):
        return 0
    figures = annotation.get("figures")
    if not isinstance(figures, list):
        return 0
    total = 0
    for fig in figures:
        if not isinstance(fig, dict):
            continue
        attested = fig.get("attested_chunk_ids")
        if isinstance(attested, list):
            new_attested = []
            for cid in attested:
                if isinstance(cid, str) and cid in chunk_id_map:
                    new_attested.append(chunk_id_map[cid])
                    total += 1
                else:
                    new_attested.append(cid)
            fig["attested_chunk_ids"] = new_attested
        primary = fig.get("primary")
        if isinstance(primary, dict):
            total += _rewrite_hit(primary, chunk_id_map, doc_id_map)
        additional = fig.get("additional")
        if isinstance(additional, list):
            for hit in additional:
                if isinstance(hit, dict):
                    total += _rewrite_hit(hit, chunk_id_map, doc_id_map)
        near_miss = fig.get("near_miss")
        if isinstance(near_miss, dict):
            cid = near_miss.get("chunk_id")
            if isinstance(cid, str) and cid in chunk_id_map:
                near_miss["chunk_id"] = chunk_id_map[cid]
                total += 1
    return total


def _rewrite_tool_content(
    content: str, chunk_id_map: Mapping[str, str], doc_id_map: Mapping[str, str],
) -> tuple[str, int]:
    """Rewrite a `role: "tool"` message's `content` -- the verbatim
    retrieve() JSON `harness/history.py` explicitly refuses to prune.
    Returns `(content, rewrites)`; `content` is returned BYTE-IDENTICAL
    (not re-serialized) when nothing changed, so a `cite_batch` ack or any
    other non-retrieve tool result is never touched even cosmetically.

    Best-effort, mirroring `harness/session.py::_chunk_ids`'s own contract
    for this exact string: a malformed body (not JSON, not an object, no
    "chunks" list) contributes zero rewrites rather than raising -- one bad
    tool message must not cost the whole conversation, let alone the pass.
    """
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError):
        return content, 0
    if not isinstance(parsed, dict):
        return content, 0
    chunks = parsed.get("chunks")
    if not isinstance(chunks, list):
        return content, 0

    rewritten = 0
    for chunk in chunks:
        if not isinstance(chunk, dict):
            continue
        chunk_id = chunk.get("chunk_id")
        if isinstance(chunk_id, str) and chunk_id in chunk_id_map:
            chunk["chunk_id"] = chunk_id_map[chunk_id]
            rewritten += 1
        doc_id = chunk.get("doc_id")
        if isinstance(doc_id, str) and doc_id in doc_id_map:
            chunk["doc_id"] = doc_id_map[doc_id]
            rewritten += 1

    if rewritten == 0:
        return content, 0
    return json.dumps(parsed, ensure_ascii=False), rewritten


def _migrate_messages(
    messages: list[dict[str, Any]],
    chunk_id_map: Mapping[str, str],
    doc_id_map: Mapping[str, str],
) -> int:
    """Mutates `messages` in place. Returns the total number of id fields
    rewritten across the whole transcript."""
    total = 0
    for message in messages:
        role = message.get("role")
        if role == "tool":
            content = message.get("content")
            if isinstance(content, str):
                new_content, n = _rewrite_tool_content(content, chunk_id_map, doc_id_map)
                if n:
                    message["content"] = new_content
                    total += n
        elif role == "assistant":
            annotation = message.get("annotation")
            if isinstance(annotation, dict):
                total += _rewrite_annotation(annotation, chunk_id_map, doc_id_map)
    return total


def _backup_conversations(root: Path, progress: Callable[[str], None]) -> Path:
    """Copy the WHOLE conversations directory before any write.

    This is an analyst's own saved chats, on their own machine -- there is
    no shared drive to protect against here, unlike `store.backup.snapshot()`
    for the corpus, but the same principle applies: a rewrite an analyst
    never asked for should be trivially undoable without asking them to
    remember what changed.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    backup_dir = root.parent / f"{root.name}-backup-{stamp}"
    shutil.copytree(root, backup_dir)
    progress(f"backed up {root} -> {backup_dir}")
    return backup_dir


def migrate_history(
    *,
    chunk_id_map: Mapping[str, str],
    doc_id_map: Mapping[str, str],
    dry_run: bool = True,
    backup: bool = True,
    progress: Callable[[str], None] | None = None,
) -> HistoryMigrateResult:
    """Rewrite every saved AI Mode transcript's embedded chunk_ids/doc_ids
    per `chunk_id_map` / `doc_id_map` (both `{old: new}`).

    Reuses `harness.history.conversations_dir/load/save` directly rather
    than re-reading the directory by hand -- that is what makes the
    "degrade per file" promise and the atomic tmp+replace write true here
    for free, and what makes the `version` stamp migration (see the module
    docstring) happen automatically as a side effect of `save()`.

    `dry_run=True` (the default) never writes a file and never takes a
    backup -- this is meant to be run and read by a human before an
    `--apply`, the same asymmetry `identity/relabel.py` and
    `identity/rename_docs.py` both use for their own corpus writes.
    """
    # Imported here, not at module scope, only so a caller passing empty
    # maps (nothing to migrate) never even touches `harness.history` --
    # harmless either way since that module has no import-time side
    # effects, but it keeps this function's "degenerate input costs
    # nothing" behaviour visibly true rather than merely true by luck.
    from harness.history import conversations_dir, load as load_transcript, save as save_transcript

    progress = progress or _default_progress
    result = HistoryMigrateResult()

    if not chunk_id_map and not doc_id_map:
        return result  # nothing to rewrite -- a valid, cheap no-op

    root = conversations_dir()
    paths = sorted(root.glob("*.json"))
    if not paths:
        return result

    if not dry_run and backup:
        result.backup_dir = _backup_conversations(root, progress)

    for path in paths:
        conversation_id = path.stem
        result.inspected += 1
        transcript = load_transcript(conversation_id)
        if transcript is None:
            # Degrade PER FILE, matching harness/history.py's own read
            # contract exactly (same reasoning as its `_read`'s own
            # comment): one corrupt transcript costs this migration
            # precisely one conversation, never the whole pass.
            result.corrupt.append(conversation_id)
            progress(f"skipping unreadable transcript {conversation_id}")
            continue

        n = _migrate_messages(transcript.messages, chunk_id_map, doc_id_map)
        if n == 0:
            continue

        result.changed += 1
        result.ids_rewritten += n
        if not dry_run:
            save_transcript(transcript)
        progress(
            f"{'would rewrite' if dry_run else 'rewrote'} "
            f"{conversation_id} ({n} ids)"
        )

    return result


def main(argv: list[str] | None = None) -> int:
    """CLI: `python -m identity.history_migrate --dry-run|--apply
    --rename-result <path>`.

    `--rename-result` is the exact `--out` JSON `identity.rename_docs`
    writes (dry-run or apply, either works -- the id map is identical
    either way) -- its `chunk_id_pairs` and `doc_renames` become this
    pass's id map, so the two passes are guaranteed to agree on what
    "the rename" means rather than risking a hand-copied second list.
    """
    ap = argparse.ArgumentParser(description=__doc__)
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run", action="store_true",
        help="report what would change; write nothing, back up nothing",
    )
    mode.add_argument(
        "--apply", action="store_true",
        help="back up the conversations directory, then rewrite transcripts",
    )
    ap.add_argument(
        "--rename-result", type=Path, required=True,
        help="the JSON --out file identity.rename_docs wrote",
    )
    ap.add_argument(
        "--no-backup", action="store_true",
        help="skip the pre-write backup copy (apply only; dry-run never writes)",
    )
    ap.add_argument(
        "--history-dir", type=Path, default=None,
        help="override JLBC_HISTORY_DIR for this run",
    )
    args = ap.parse_args(argv)

    if args.history_dir is not None:
        import os

        os.environ["JLBC_HISTORY_DIR"] = str(args.history_dir)

    payload = json.loads(args.rename_result.read_text(encoding="utf-8"))
    chunk_id_map = {
        pair["old_chunk_id"]: pair["new_chunk_id"]
        for pair in payload.get("chunk_id_pairs", [])
    }
    doc_id_map = {
        entry["old_doc_id"]: entry["new_doc_id"]
        for entry in payload.get("doc_renames", [])
    }

    result = migrate_history(
        chunk_id_map=chunk_id_map, doc_id_map=doc_id_map,
        dry_run=not args.apply, backup=not args.no_backup,
    )

    print(f"inspected: {result.inspected}")
    print(f"changed: {result.changed}")
    print(f"ids_rewritten: {result.ids_rewritten}")
    print(f"corrupt (skipped): {len(result.corrupt)}")
    if result.corrupt:
        print("corrupt ids:", ", ".join(result.corrupt))
    if result.backup_dir is not None:
        print(f"backup: {result.backup_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
