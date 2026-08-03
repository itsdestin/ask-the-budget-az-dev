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
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

HISTORY_DIR_ENV = "JLBC_HISTORY_DIR"
_APP_FOLDER = "JLBC-Insight"


@dataclass
class Transcript:
    id: str
    title: str
    corpus: str
    created_at: str
    updated_at: str
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
    # APPEND to the filename rather than `with_suffix`: with_suffix replaces
    # the last dotted segment, so an id that ever contains a dot would have
    # part of itself eaten and the replace would land on the wrong file.
    # Ids are uuid4 hex today; this costs nothing and removes the trap.
    tmp = path.parent / f"{path.name}.{os.getpid()}.tmp"
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
        messages = list(raw.get("messages") or [])
        return Transcript(
            id=raw["id"], title=raw.get("title", ""), corpus=raw.get("corpus", "budget"),
            created_at=raw.get("created_at", ""), updated_at=raw.get("updated_at", ""),
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
    if not path.is_file():
        return False
    path.unlink()
    return True


def rename(conversation_id: str, title: str) -> bool:
    t = load(conversation_id)
    if t is None:
        return False
    t.title = title
    # Set once and never unset: auto-naming checks this flag so an analyst's
    # own title is never overwritten by a later model-generated one.
    t.title_is_manual = True
    # `updated_at` is deliberately NOT touched. The rail sorts on it, and it
    # means "when did this conversation last have something said in it" — a
    # rename is bookkeeping. Bumping it would float a retitled March chat
    # above this morning's.
    save(t)
    return True
