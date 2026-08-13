"""The admin's alias overlay for search (spec E1, decision E5).

`samples/entity-catalog.yaml` is a COMMITTED file the office bundle ships
read-only, so the admin's own acronyms live here instead — a small JSON
file on the shared data dir that merges OVER the catalog at query time.
The stoplists and the catalog itself are untouched by design: this file
may only add aliases (which resolve WEAK, never as a hard filter) and
switch shipped aliases off.

Read posture mirrors harness/settings.py: cached on a (path, mtime, size)
stamp so a rewrite by another machine on the share is picked up, degrading
to empty on any bad file. Writes are tmp+os.replace and RAISE — a failed
save must reach the admin's screen, not vanish.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from store.config import data_dir

OFFICE_ALIASES_FILE = "office-aliases.json"


@dataclass(frozen=True)
class OfficeAlias:
    alias: str
    canonical_id: str
    added_by: str = ""
    added_at: str = ""


@dataclass(frozen=True)
class OfficeAliases:
    added: tuple[OfficeAlias, ...] = ()
    disabled: frozenset[str] = field(default_factory=frozenset)

    def added_by_agency(self) -> dict[str, tuple[str, ...]]:
        """{canonical_id: (lowercased aliases...)} for the filter box."""
        out: dict[str, list[str]] = {}
        for entry in self.added:
            out.setdefault(entry.canonical_id, []).append(entry.alias.lower())
        return {cid: tuple(names) for cid, names in out.items()}


def office_aliases_path() -> Path:
    return data_dir() / OFFICE_ALIASES_FILE


_lock = threading.Lock()
# (path_str, mtime_ns, size) -> OfficeAliases. One entry — there is one file.
_cache: tuple[tuple[str, int, int], OfficeAliases] | None = None


def reset_office_aliases_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def load_office_aliases(path: Path | None = None) -> OfficeAliases:
    """The overlay, or empty. NEVER raises — a bad file must not take down
    retrieval, whose hot path calls this on every query."""
    global _cache
    resolved = path if path is not None else office_aliases_path()
    try:
        stat = resolved.stat()
        stamp = (str(resolved), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        # No overlay yet is the normal, silent case — most offices never
        # create one.
        return OfficeAliases()
    except OSError as err:
        # Anything other than "doesn't exist" (permission denied, a stale
        # handle on the shared drive, ...) is worth a line on stderr, same
        # as the corrupt-file path below — the admin should see why their
        # aliases stopped applying instead of it silently going empty.
        print(
            f"store.office_aliases: ignoring {resolved} ({err}) — the "
            "admin's alias overlay is unavailable for this read.",
            file=sys.stderr,
        )
        return OfficeAliases()
    with _lock:
        if _cache is not None and _cache[0] == stamp:
            return _cache[1]
    try:
        raw = json.loads(resolved.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError(f"expected an object, got {type(raw).__name__}")
        parsed = _from_dict(raw)
    except (OSError, ValueError, TypeError, KeyError) as err:
        # ValueError covers json.JSONDecodeError AND UnicodeDecodeError —
        # the trap harness/ledger.py documents. Say why every time; callers
        # on the hot path get an empty overlay, not a 500.
        print(
            f"store.office_aliases: ignoring {resolved} ({err}) — the "
            "admin's alias overlay is unavailable for this read.",
            file=sys.stderr,
        )
        return OfficeAliases()
    with _lock:
        _cache = (stamp, parsed)
    return parsed


def _from_dict(raw: dict) -> OfficeAliases:
    added = []
    for row in raw.get("added", []) or []:
        # A non-dict element (null, a bare string, a number, a nested list)
        # is torn data, same as a dict missing keys — it costs itself, not
        # the file. Without this check `row.get(...)` raises AttributeError,
        # which isn't in the caught tuple below, and the whole load blows up.
        if not isinstance(row, dict):
            continue
        alias = str(row.get("alias") or "").strip().lower()
        canonical_id = str(row.get("canonical_id") or "").strip()
        if not alias or not canonical_id:
            continue  # a torn row costs itself, not the file
        added.append(
            OfficeAlias(
                alias=alias,
                canonical_id=canonical_id,
                added_by=str(row.get("added_by") or ""),
                added_at=str(row.get("added_at") or ""),
            )
        )
    disabled = frozenset(
        str(d).strip().lower() for d in (raw.get("disabled", []) or []) if str(d).strip()
    )
    return OfficeAliases(added=tuple(added), disabled=disabled)


def save_office_aliases(aliases: OfficeAliases, path: Path | None = None) -> None:
    """Atomic write. RAISES on failure — the admin route turns that into a
    visible error, never a silent no-op save."""
    resolved = path if path is not None else office_aliases_path()
    payload = {
        "added": [
            {
                "alias": a.alias,
                "canonical_id": a.canonical_id,
                "added_by": a.added_by,
                "added_at": a.added_at,
            }
            for a in aliases.added
        ],
        "disabled": sorted(aliases.disabled),
    }
    # Per-call uuid suffix, not per-process — the chat-history lesson: two
    # writers on one file must not share a tmp name.
    tmp = resolved.with_name(f"{resolved.name}.tmp-{uuid.uuid4().hex[:8]}")
    resolved.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, resolved)
    reset_office_aliases_cache()
