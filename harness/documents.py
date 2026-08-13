"""`create_document` — the model's only write primitive (Plan 4 Task 4, S3).

An analyst asks for a memo-shaped answer ("write this up so I can send
it"); the model calls `create_document` with a title and a Markdown
body; this module turns that into a .docx (or .md) the analyst can
download, and hands back an unguessable token the chat UI renders as a
link.

**Invariant 7 lives here.** One Python process serves a whole office off
a shared network drive — the corpus, settings and PDFs all live on that
share. Nothing the model can call may write there, because a confused or
prompt-injected model would then be able to corrupt state for everyone
at once. So:

* The tool schema takes a TITLE, never a path or a filename. The model
  supplies content; this module supplies the location. That split is the
  whole invariant.
* Artifacts land under the per-user, per-machine local app-data folder
  (`%LOCALAPPDATA%\\JLBC-Insight\\documents\\`) — disposable, private,
  and not the share.
* This module deliberately does NOT import `store.config`, so it has no
  way to learn where the share even is. `tests/test_create_document.py`
  asserts that as an import allowlist, which is why the guard is
  structural rather than a promise in a comment.

Kept import-light on purpose: `harness/tools.py` imports it lazily
inside its `create_document` handler, so anything expensive at module
scope would be paid on the first tool dispatch of a conversation.
python-docx (and its lxml dependency) is therefore imported inside the
writer, not here — the .md path never pays for it at all. `memo`, which
pulls python-docx in, is imported inside `_render_docx` for the same
reason.

The .docx rendering itself lives in the `memo/` package: it turns the
Markdown body into a JLBC-styled document (letterhead, DATE/TO/FROM/
SUBJECT block, house typography) and nothing else. It is the ONE
non-stdlib import this module is allowed beyond the stdlib set, and it is
safe precisely because `memo` carries its OWN import allowlist test
(`tests/test_jlbc_memo.py`) — so the Invariant 7 guarantee stays
structural and becomes transitive rather than becoming a promise.
"""
from __future__ import annotations

import os
import re
import secrets
import threading
import time
import unicodedata
from dataclasses import dataclass
from pathlib import Path

# Override for tests, and an escape hatch for an install that wants
# artifacts somewhere else. Named for what it holds so it can never be
# confused with JLBC_DATA_DIR, which points at the SHARED data root —
# these two must never be the same directory (see documents_dir()).
DOCUMENTS_DIR_ENV = "JLBC_DOCUMENTS_DIR"

_APP_FOLDER = "JLBC-Insight"

DOCX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)

# fmt -> (file extension, HTTP content type). The single source of truth
# for both; the download route reads the media type off the registry
# rather than re-deriving it from the suffix.
_FORMATS: dict[str, tuple[str, str]] = {
    "docx": (".docx", DOCX_MEDIA_TYPE),
    "md": (".md", "text/markdown; charset=utf-8"),
}


def documents_dir() -> Path:
    """Where artifacts are written. Created if missing.

    Resolution order:
      1. `JLBC_DOCUMENTS_DIR` — tests point this at a tmp dir.
      2. `%LOCALAPPDATA%\\JLBC-Insight\\documents` on Windows, which is
         the real deployment (spec S7 installs the whole app there).
      3. Non-Windows (CI, a dev Mac) has no LOCALAPPDATA, so fall back to
         the XDG data location — `~/.local/share/JLBC-Insight/documents`.
         Home-rooted either way, which is what matters: never the share.

    NOT validated against the shared data dir, because doing so would
    mean importing `store.config` and giving this module knowledge of the
    share it is specifically supposed to lack. Pointing
    JLBC_DOCUMENTS_DIR at the share would defeat Invariant 7, but that is
    an operator typing a deliberate env var, not something any model can
    reach through the tool surface — and the tool surface is what the
    invariant is about.
    """
    raw = os.environ.get(DOCUMENTS_DIR_ENV)
    if raw:
        root = Path(raw)
    elif os.environ.get("LOCALAPPDATA"):
        root = Path(os.environ["LOCALAPPDATA"]) / _APP_FOLDER / "documents"
    else:
        base = os.environ.get("XDG_DATA_HOME") or (Path.home() / ".local" / "share")
        root = Path(base) / _APP_FOLDER / "documents"
    root.mkdir(parents=True, exist_ok=True)
    return root


# ---------------------------------------------------------------------------
# The download registry
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Artifact:
    """One materialized document, as the download route needs it."""

    token: str
    path: Path
    media_type: str
    # WHO asked for it. Recorded for attribution and debugging, NOT
    # enforced at download time — and that is deliberate rather than an
    # oversight. This app has no authentication (spec S11 is explicit
    # that even the admin surface is soft-gated and "explicitly not real
    # security"), so a username is a string the caller asserts about
    # itself. Checking it would look like isolation while providing
    # none. The real protection is that the token is 256 bits of
    # `secrets` randomness that only ever travels to the conversation
    # that created it. If per-user isolation ever has to be REAL, it
    # needs an authenticated identity first; bolting a comparison onto
    # this field would just be theater.
    user: str
    created_at: float


_registry_lock = threading.Lock()
_registry: dict[str, Artifact] = {}


def reset_registry() -> None:
    """Test-only: drop every token. Does not delete files from disk."""
    with _registry_lock:
        _registry.clear()


def lookup(token: str) -> Artifact | None:
    """Resolve a download token, or None if it is unknown.

    THE TOKEN IS A DICTIONARY KEY AND NEVER A PATH COMPONENT. That is
    what makes path traversal structurally impossible rather than merely
    filtered: a token of `../../settings.json` is not a dangerous path,
    it is an absent key. Nothing a caller sends is ever joined onto a
    directory.

    The registry is in-process, so tokens die with the server (accepted
    per the plan — conversation persistence across restarts is a Plan 5
    item). The FILES outlive it, orphaned under documents_dir(); they are
    small, local and disposable, and sweeping them is a launcher job for
    Plan 5 rather than something to invent here.
    """
    with _registry_lock:
        return _registry.get(token)


# ---------------------------------------------------------------------------
# Filenames
# ---------------------------------------------------------------------------
# The model chooses the title, so the title is untrusted input that ends
# up in two hostile places: a filesystem path and an HTTP header. This is
# the only point where a model-supplied string gets anywhere near either.

# The filename allowlist is: **Unicode alphanumerics** (`str.isalnum()`,
# which is script-aware — a Chinese or accented title keeps its letters
# and yields e.g. `预算报告.md`) **plus these three punctuation marks**.
# Everything else is replaced, so `/ \ : * ? " < > |`, control characters
# and CR/LF (header injection) cannot survive by construction — they are
# not on the list, rather than being individually looked for.
#
# WHY allow non-ASCII: modern Windows and SMB handle it fine, and
# Starlette emits the RFC 5987 `filename*=utf-8''…` Content-Disposition
# form automatically for any name that isn't URL-safe, so the header is
# correct either way. The tradeoff is only that a title with non-ASCII
# characters — or with `~`, `&`, `(`, `,`, which ARE dropped despite
# being legal in filenames — takes that encoded header form instead of
# the plain `filename="…"` one. Both are widely supported; a narrower
# list is not worth mangling a legitimate title over.
_KEEP = set("-_.")
# Windows refuses these names with ANY extension — `NUL.docx` is still the
# null device, and writing to it silently succeeds while producing no file.
_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{n}" for prefix in ("COM", "LPT") for n in range(1, 10)
}
# Long enough for a real memo title, short enough that stem + extension +
# the per-artifact folder stay well inside Windows' 260-char path limit
# on a deep %LOCALAPPDATA% path.
_MAX_STEM = 80


def _safe_stem(title: str) -> str:
    """Untrusted title -> a filename stem that is safe everywhere."""
    text = unicodedata.normalize("NFC", title)
    # Allowlist, not denylist: anything unrecognized becomes a space and
    # is then collapsed, so no exotic separator or control character has
    # to be individually anticipated.
    kept = "".join(ch if (ch.isalnum() or ch in _KEEP) else " " for ch in text)
    stem = "-".join(kept.split())
    stem = re.sub(r"-{2,}", "-", stem)
    # Windows rejects trailing dots/spaces, and a leading dot would make
    # the file hidden on POSIX.
    stem = stem.strip("-. ")[:_MAX_STEM].strip("-. ")
    if not stem:
        return "document"  # a title of "..." or "***" leaves nothing
    if stem.upper() in _RESERVED or stem.split(".")[0].upper() in _RESERVED:
        return f"document-{stem}"
    return stem


# ---------------------------------------------------------------------------
# Markdown -> Word
# ---------------------------------------------------------------------------
# The renderer itself now lives in `memo/`, which maps the same small,
# deliberate Markdown subset onto the JLBC memo's house styles. The rule
# that mattered here still holds there and is pinned by its own tests:
# anything unrecognized becomes a plain paragraph, VERBATIM, never a
# silent drop.


def _render_docx(
    title: str,
    body_markdown: str,
    target: Path,
    *,
    sender: str,
    recipient: str,
) -> None:
    """Write the .docx as a JLBC memo.

    `memo` is imported HERE, not at module scope — see the module
    docstring on staying import-light. It is the ONLY non-stdlib import
    this module is permitted, and it is safe precisely because `memo`
    carries its own import allowlist test: it renders and nothing else,
    so it has no path to the share either.
    """
    from memo import render

    doc = render(
        body_markdown,
        subject=title,
        sender=sender,
        recipient=recipient,
    )
    # The memo block's SUBJECT row carries the title on the page; this
    # carries it into Word's document properties, which is what an email
    # client and File Explorer's preview pane read. There is deliberately
    # no separate Title-styled line in the body any more — the masthead
    # owns Word's `Title` style now, and the reference memo has no such
    # line (spec M4).
    doc.core_properties.title = title
    doc.save(str(target))


# ---------------------------------------------------------------------------
# The public entry point
# ---------------------------------------------------------------------------


def materialize(
    title: str,
    body_markdown: str,
    fmt: str = "docx",
    *,
    user: str = "",
    sender: str = "",
    recipient: str = "",
) -> tuple[str, Path]:
    """Write one artifact and register it for download.

    Returns `(token, path)`. `harness/tools.py` reads `path.name` as the
    filename it reports to the model, which is why the path keeps the
    human title rather than being named after the token.

    `sender` and `recipient` are FINISHED STRINGS resolved by the caller.
    This module does not know who the analyst is and must not learn —
    resolving a display name means reading per-machine config, which is
    exactly the kind of reach Invariant 7's import allowlist forbids here.
    Both default to "", which the memo renders as the tool's own name and
    a visible `[Recipient(s)]` placeholder respectively; neither is ever a
    hard failure, because an unnameable analyst should lose attribution on
    a memo, not the ability to generate one.

    Each artifact gets its OWN randomly-named subdirectory. Two memos
    titled "Memo" would otherwise collide, and the second write would
    silently replace the first while the first token still pointed at
    that path — handing an analyst someone else's document under their
    own filename.
    """
    if fmt not in _FORMATS:
        raise ValueError(
            f"unknown format {fmt!r} — must be one of: {', '.join(_FORMATS)}."
        )
    suffix, media_type = _FORMATS[fmt]

    folder = documents_dir() / secrets.token_hex(8)
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / f"{_safe_stem(title)}{suffix}"
    # Belt and braces over _safe_stem: assert the sanitizer's output
    # actually landed where it was supposed to, so a future edit that
    # loosens the allowlist fails loudly instead of writing outside the
    # documents directory.
    if target.resolve().parent != folder.resolve():
        raise ValueError(f"refusing to write outside {folder}")

    if fmt == "md":
        # Byte-faithful: the analyst downloads exactly what the model
        # wrote, no round-trip through a renderer that could lose a
        # construct.
        target.write_text(body_markdown, encoding="utf-8")
    else:
        _render_docx(title, body_markdown, target, sender=sender, recipient=recipient)

    # 32 bytes -> a 43-character URL-safe string. This token is the ONLY
    # thing standing between an artifact and anyone who can reach the
    # loopback port, so it is generated by `secrets` and is unrelated to
    # the title, the user, or the path.
    token = secrets.token_urlsafe(32)
    with _registry_lock:
        _registry[token] = Artifact(
            token=token,
            path=target,
            media_type=media_type,
            user=user,
            created_at=time.time(),
        )
    return token, target
