"""The administrator's guidance block for the AI prompt (spec E2).

The shipped system prompt is a 1,200-line template wired to citation
discipline and refusal thresholds; nobody edits it at runtime. What the
admin CAN do is write this file — plain markdown on the share — and it is
injected into one designated slot with a preamble that makes the shipped
rules win on any conflict. Empty or missing, the prompt renders
byte-identical to today.

Kept import-light on purpose: harness/prompt.py pulls this in, and
building a prompt must not drag LanceDB or the ONNX models into a process
that only wanted a string. stdlib + store.config only.
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path

from store.config import data_dir

GUIDANCE_FILE = "office-guidance.md"
META_FILE = "office-guidance.meta.json"

# ~2,000 tokens. The block rides EVERY request in every AI conversation
# office-wide, so a runaway paste is a silent, recurring token bill — the
# cap turns it into a visible save error instead.
MAX_GUIDANCE_BYTES = 8192

# Fixed, never admin-editable: the sentence that keeps shipped citation/
# refusal/tool rules senior to anything written here.
_PREAMBLE = (
    # The leading blank line belongs to the BLOCK, not to the template: with
    # corpus=budget the slot's preceding `{{#when}}` section ends with a
    # paragraph, and without this the heading glued onto it
    # ("…reports the same figure.\n## Office guidance…"). It cannot be fixed
    # in harness/system-prompt.md, because the empty case removes the slot
    # LINE and must still render byte-identically to the template with the
    # slot deleted — a blank line in the template would survive and break that.
    "\n## Office guidance from the administrator\n\n"
    "The office administrator added the guidance below. It supplements the "
    "rules above; where it conflicts with citation, refusal, or tool rules, "
    "those rules win.\n\n"
)


def guidance_path() -> Path:
    return data_dir() / GUIDANCE_FILE


def meta_path() -> Path:
    return data_dir() / META_FILE


_lock = threading.Lock()
_cache: tuple[tuple[str, int, int], str] | None = None


def reset_guidance_cache() -> None:
    global _cache
    with _lock:
        _cache = None


def load_office_guidance() -> str:
    """The raw guidance text, or "". NEVER raises — a bad file must not
    take down prompt building for the whole office."""
    global _cache
    path = guidance_path()
    try:
        stat = path.stat()
        stamp = (str(path), stat.st_mtime_ns, stat.st_size)
    except FileNotFoundError:
        # No guidance file is the normal, silent case — most offices never
        # write one.
        return ""
    except OSError as err:
        # Anything else (the share is offline, permissions changed) removes
        # the office's guidance from EVERY prompt, office-wide, with no other
        # symptom. Same posture as store/office_aliases.py: still degrade to
        # "" so a prompt build never fails, but leave a line saying why.
        print(
            f"harness.office_guidance: cannot read {path} ({err}) — the "
            "office guidance is missing from prompts for this read.",
            file=sys.stderr,
        )
        return ""
    with _lock:
        if _cache is not None and _cache[0] == stamp:
            return _cache[1]
    try:
        text = path.read_text(encoding="utf-8").strip()
    except (OSError, ValueError) as err:
        print(f"harness.office_guidance: ignoring {path} ({err}).", file=sys.stderr)
        return ""
    with _lock:
        _cache = (stamp, text)
    return text


def office_guidance_block() -> str:
    """What `{{OFFICE_GUIDANCE}}` renders to: nothing, or preamble + text."""
    text = load_office_guidance()
    return f"{_PREAMBLE}{text}\n" if text else ""


def save_office_guidance(text: str, user: str) -> None:
    """Atomic save with a one-step undo. RAISES on failure or over-cap."""
    cleaned = text.strip()
    if len(cleaned.encode("utf-8")) > MAX_GUIDANCE_BYTES:
        raise ValueError(
            f"This guidance is too long — it's over the {MAX_GUIDANCE_BYTES:,} "
            "byte limit. Text pasted from Word often runs over sooner than "
            "the character count suggests, because accented letters, curly "
            "quotes, and em dashes each count as more than one byte. This "
            "text rides every AI request the whole office makes, so shorter "
            "is genuinely better. Trim it and save again."
        )
    path = guidance_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp-{uuid.uuid4().hex[:8]}")
    tmp.write_text(cleaned, encoding="utf-8")
    # One-step undo: the version being replaced survives as .bak — the
    # settings-corrupt-preservation idea, applied to deliberate edits.
    #
    # WHY tmp is written BEFORE the live file moves to .bak, not after:
    # if `tmp.write_text` fails partway (share disconnect, disk full,
    # permissions — all normal on the SMB share this app ships against),
    # the live file must still be sitting at `path`, untouched. Writing
    # tmp first means that failure happens before the live file moves at
    # all. The only window where the office has NO guidance file is
    # between the two `os.replace` calls below, and each of those is a
    # single atomic rename — not a window a failed write can land inside.
    if path.is_file():
        os.replace(path, path.with_suffix(".md.bak"))
    os.replace(tmp, path)
    meta = {
        "edited_by": user,
        "edited_at": datetime.now(timezone.utc).isoformat(),
    }
    mtmp = meta_path().with_name(f"{META_FILE}.tmp-{uuid.uuid4().hex[:8]}")
    mtmp.write_text(json.dumps(meta), encoding="utf-8")
    os.replace(mtmp, meta_path())
    reset_guidance_cache()


def load_guidance_meta() -> dict:
    try:
        raw = json.loads(meta_path().read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except (OSError, ValueError):
        return {}
