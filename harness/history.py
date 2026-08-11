"""Per-device AI Mode chat history (spec 2026-08-02, H1).

WHY these files live under %LOCALAPPDATA% and not the shared drive: every
analyst runs their own copy of the app (Plan 5 Track 3 ships one bundle to
~20 PCs), so "this machine" is already "this analyst". Putting transcripts on
the share would expose every analyst's questions to ~20 colleagues.

INVARIANT 7: this module must never import `store.config`. Not importing it is
what makes the confinement structural rather than a promise — there is no code
path here that can learn where the share is. `tests/test_harness_history.py`
pins that with an AST check.
"""
from __future__ import annotations

import json
import os
import threading
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator
from uuid import uuid4

HISTORY_DIR_ENV = "JLBC_HISTORY_DIR"
_APP_FOLDER = "JLBC-Insight"


# Bump when the stored shape changes in a way a reader must act on. Files
# written before this existed read back as version 0, which is what makes a
# future migration possible at all: without a stamp, "old schema" and "field
# absent" are the same observation and there is nothing to branch on. Nothing
# reads it today — that is the point of writing it now rather than later.
SCHEMA_VERSION = 1


@dataclass
class Transcript:
    id: str
    title: str
    corpus: str
    created_at: str
    updated_at: str
    version: int = SCHEMA_VERSION
    title_is_manual: bool = False
    messages: list[dict] = field(default_factory=list)
    # Kept separately so `list_all()` can strip the bodies and STILL report a
    # count. Without it the rail would need a second read of every file, which
    # is exactly what stripping was meant to avoid. Derived on read, never
    # persisted — a stored count could disagree with the stored messages.
    message_count: int = 0


def conversations_dir() -> Path:
    """Where transcripts live. Created if missing.

    Resolution mirrors `harness.documents.documents_dir()` exactly, for the
    same reasons: an env override for tests, %LOCALAPPDATA% on the real
    Windows deployment, and an XDG fallback so CI and a dev Linux box work.
    Home-rooted either way — never the share.
    """
    raw = os.environ.get(HISTORY_DIR_ENV)
    if raw:
        root = Path(raw)
    elif os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / _APP_FOLDER / "conversations"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        root = Path(base) / _APP_FOLDER / "conversations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _path_for(conversation_id: str) -> Path:
    # The id arrives from an HTTP path segment, so it is untrusted input.
    # Anything that is not a bare filename could escape the directory.
    if (
        not conversation_id
        or conversation_id in {".", ".."}
        or "/" in conversation_id
        or "\\" in conversation_id
        or os.path.basename(conversation_id) != conversation_id
    ):
        raise ValueError(f"not a bare conversation id: {conversation_id!r}")
    return conversations_dir() / f"{conversation_id}.json"


# Per-id write locks. save/rename/delete each do a load-then-write (or a
# delete), and two of them can run on the SAME id at once: persist_turn's
# turn-end write rides a BackgroundTask thread while a rail rename/delete
# rides a request thread. Without a lock the writes interleave — a turn end
# can clobber a rename, or resurrect a just-deleted chat. The app is one
# process per analyst's machine (Plan 5 Track 3), so a threading lock is the
# whole job; there is no second process to coordinate with. Reads (load /
# list_all / search) stay lock-free: os.replace is atomic, so a reader sees a
# whole old or whole new file, and a torn read is already handled as "skip
# that chat". Keyed by id so two DIFFERENT chats never wait on each other.
_locks_guard = threading.Lock()
# RLock, not Lock: rename() holds its id's lock across an internal save(),
# and save() takes the same lock — a plain Lock would deadlock there. The
# re-entrant lock lets one logical write (load→mutate→save) own the id while
# the nested save re-acquires it.
_write_locks: dict[str, threading.RLock] = {}


def _write_lock(conversation_id: str) -> threading.RLock:
    with _locks_guard:
        lock = _write_locks.get(conversation_id)
        if lock is None:
            lock = threading.RLock()
            _write_locks[conversation_id] = lock
        return lock


@contextmanager
def transaction(conversation_id: str) -> Iterator[None]:
    """Hold one chat's write lock across a whole load→mutate→save.

    THE DISTINCTION THIS EXISTS TO DRAW, because getting it wrong is what
    caused three separate defects found on 2026-08-11: `save()` taking the
    lock makes each WRITE atomic. It does NOT make a read-modify-write
    atomic, and every caller here does a read-modify-write. A rename landing
    between another writer's `load` and its `save` is silently reverted —
    the lock was never in a position to prevent it, because the reader had
    already let go of nothing.

    Wrap the load and the save together and the sequence becomes a real
    transaction. The lock is re-entrant, so the nested `save()` re-acquires
    it harmlessly.

    DO NOT hold this across a network call. `persist_turn` used to bracket a
    20-second title request in its read-modify-write; holding the lock there
    would block the rail's rename and delete for the same 20 seconds. Take
    it, write, release; take it again afterwards for the second write.
    """
    with _write_lock(conversation_id):
        yield


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def save(transcript: Transcript) -> None:
    """Write one transcript atomically.

    tmp + os.replace, the convention used by ingest/jobs.py and
    store/documents.py: a crash mid-write must not leave a half file that
    the reader would then have to treat as corrupt.
    """
    path = _path_for(transcript.id)
    payload = asdict(transcript)
    # Derived on read, never written: a persisted count could disagree with
    # the messages beside it, and then the rail would lie.
    payload.pop("message_count", None)
    # Stamped from the constant, never from the object: a Transcript loaded
    # from a pre-versioning file carries version 0, and re-saving it writes
    # TODAY'S shape — so the file must say so.
    payload["version"] = SCHEMA_VERSION
    # APPEND to the filename rather than `with_suffix`: with_suffix replaces
    # the last dotted segment, so an id that ever contains a dot would have
    # part of itself eaten and the replace would land on the wrong file.
    # Ids are uuid4 hex today; this costs nothing and removes the trap.
    #
    # The tmp name must be unique PER CALL, not per process: persist_turn
    # (a BackgroundTask thread) and rename (a request thread) can both be
    # saving the SAME id at once, and a shared `{pid}.tmp` lets one writer's
    # os.replace empty the file out from under the other's, which then raises
    # FileNotFoundError (or, worse, replaces with a half-written payload).
    # A uuid suffix keeps the atomic tmp+replace pattern while making each
    # concurrent write its own file.
    # Serialized against rename/delete for THIS id via the write lock, so a
    # turn-end save can never clobber a rename or resurrect a delete that is
    # mid-flight. The lock is held only for the write itself.
    with _write_lock(transcript.id):
        tmp = path.parent / f"{path.name}.{os.getpid()}.{uuid4().hex}.tmp"
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)


def _read(path: Path) -> Transcript | None:
    """One transcript, or None if it is unreadable.

    READ paths degrade, deliberately — the same split store/documents.py
    makes. One corrupt file must not blank an analyst's whole history list;
    it should cost them that one chat and nothing else.
    """
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        # A file whose JSON is VALID but is not an object — `null`, `[]`, `5`,
        # `"x"` — parses fine and then raises AttributeError on `.get`, which
        # is not in the except list below. That escaped `list_all()` and
        # `search()`, so one such file turned GET /api/history into a 500 and
        # blanked the entire rail: the exact opposite of the degradation this
        # function promises. Checked rather than added to the except clause,
        # so the failure is named at the point it happens.
        if not isinstance(raw, dict):
            return None
        messages = list(raw.get("messages") or [])
        return Transcript(
            id=raw["id"], title=raw.get("title", ""), corpus=raw.get("corpus", "budget"),
            created_at=raw.get("created_at", ""), updated_at=raw.get("updated_at", ""),
            # 0, not SCHEMA_VERSION: a file with no stamp predates versioning
            # and must be distinguishable from one written today, or the stamp
            # buys nothing.
            version=int(raw.get("version", 0) or 0),
            title_is_manual=bool(raw.get("title_is_manual", False)),
            messages=messages, message_count=len(messages),
        )
    except (OSError, ValueError, KeyError):
        return None


def load(conversation_id: str) -> Transcript | None:
    path = _path_for(conversation_id)
    return _read(path) if path.is_file() else None


def list_all() -> list[Transcript]:
    """Every transcript, newest first, WITHOUT message bodies.

    The directory IS the index — there is deliberately no summary file. A
    summary that can disagree with the files it summarises is a bug class
    bought for nothing, and a scan of a few hundred small files is
    milliseconds.

    MEASURED 2026-08-02 against transcripts built from real eval-shaped
    payloads (full retrieved-chunk text, the largest thing in history):
      - Standard lookup (15 chunks, 1 retrieve):   7.2 KB
      - Deep Research (41 chunks, 3 retrieves):   26.4 KB
      - list_all() over 200 Deep Research copies:  9.7 ms
    H6's "transcripts are kilobytes" was off by ~3-4x for Deep Research
    (tens of KB, not single-digit KB), but list_all's linear scan is still
    well under the 300 ms threshold at 200 files, so the no-index design
    holds. If the office accumulates hundreds of Deep Research chats and
    list_all becomes perceptible, the bounded-header read (write header
    fields a second time into the first 512 bytes, give list_all a
    bounded read) is the documented fallback — see Task 1 Step 5 of the
    plan. Do NOT prune tool results from the stored history: a dangling
    assistant `tool_calls` message without its `{"role": "tool"}` reply
    is a malformed request that the provider 400s.
    """
    out: list[Transcript] = []
    for path in conversations_dir().glob("*.json"):
        t = _read(path)
        if t is not None:
            t.messages = []
            out.append(t)
    out.sort(key=lambda t: t.updated_at, reverse=True)
    return out


def delete(conversation_id: str) -> bool:
    path = _path_for(conversation_id)
    # Under the write lock so a turn-end save can't slip in between the
    # existence check and the unlink (or resurrect the file right after).
    with _write_lock(conversation_id):
        if not path.is_file():
            return False
        path.unlink()
        return True


def rename(conversation_id: str, title: str) -> bool:
    # Hold the id's write lock across the WHOLE load→mutate→save so a turn-end
    # persist can't overwrite the analyst's new title with a stale in-memory
    # one mid-rename. Re-entrant (RLock) because save() re-acquires the lock.
    with _write_lock(conversation_id):
        t = load(conversation_id)
        if t is None:
            return False
        t.title = title
        # Set once and never unset: auto-naming checks this flag so an
        # analyst's own title is never overwritten by a later model-generated
        # one.
        t.title_is_manual = True
        # `updated_at` is deliberately NOT touched. The rail sorts on it, and
        # it means "when did this conversation last have something said in
        # it" — a rename is bookkeeping. Bumping it would float a retitled
        # March chat above this morning's.
        save(t)
        return True


def set_title_if_absent(conversation_id: str, title: str) -> bool:
    """Give a chat an auto-generated title, but only if it still wants one.

    The whole point is that this re-reads UNDER THE LOCK, immediately before
    writing, and touches exactly one field. Auto-naming happens after a model
    call that can take twenty seconds, and three things can happen in that
    window — all three observed or reproduced on 2026-08-11:

      - the analyst renames the chat. Writing a whole stale Transcript back
        reverted the rename AND cleared `title_is_manual`, re-arming
        auto-naming against a title the analyst had chosen.
      - the analyst deletes the chat. Writing recreated it as a ghost row.
      - the NEXT turn finishes and saves. Writing reverted the transcript to
        the older message list, silently destroying that turn.

    Returns False when the chat is gone or already titled — both are ordinary
    outcomes, not errors.
    """
    with transaction(conversation_id):
        stored = load(conversation_id)
        if stored is None:              # deleted while we were naming it
            return False
        if stored.title or stored.title_is_manual:
            return False                # renamed, or already named
        stored.title = title
        save(stored)
        return True


_SNIPPET_RADIUS = 90

# H4 as amended: only what was SAID is searchable. `role: "tool"` messages
# carry retrieve() output — full corpus passage text, as a JSON string — so
# including them would turn "find the chat where we discussed Florence" into
# "find every chat where a retrieved passage mentioned Florence", and hand
# back a slice of JSON as the snippet. An isinstance(str) check does NOT
# exclude them; the role is what distinguishes prose from payload.
_SEARCHABLE_ROLES = {"user", "assistant"}


def search(query: str, limit: int = 50) -> list[tuple[Transcript, str]]:
    """Chats matching `query` in their title or their prose, newest first.

    A plain scan, deliberately: an index over a few hundred small files buys
    milliseconds and costs a whole class of drift bug, because an index that
    disagrees with the files it describes fails silently. If this ever gets
    slow, THAT is the moment to add one — see Task 1 Step 5 for the measured
    size this assumption rests on.
    """
    needle = query.strip().lower()
    if not needle:
        return []

    hits: list[tuple[Transcript, str]] = []
    for path in conversations_dir().glob("*.json"):
        t = _read(path)
        if t is None:
            continue
        snippet = ""
        for message in t.messages:
            if message.get("role") not in _SEARCHABLE_ROLES:
                continue
            content = message.get("content")
            if not isinstance(content, str):
                continue          # an assistant tool_calls turn has no prose
            found = content.lower().find(needle)
            if found >= 0:
                start = max(0, found - _SNIPPET_RADIUS)
                end = min(len(content), found + len(needle) + _SNIPPET_RADIUS)
                snippet = ("…" if start else "") + content[start:end] + ("…" if end < len(content) else "")
                break
        if not snippet and needle in t.title.lower():
            snippet = t.title
        if snippet:
            t.messages = []
            hits.append((t, snippet))

    hits.sort(key=lambda pair: pair[0].updated_at, reverse=True)
    return hits[:limit]
