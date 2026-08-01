"""The launch health ladder (Plan 5 Task 11, spec S18).

What this replaces is a stack trace. When the shared drive moved, the app
failed somewhere inside LanceDB and the person sitting at the machine saw
a Python traceback — or a blank screen, or a spinner that never stopped.
None of those tell anyone what to do.

Five rungs, checked in order, each with a plain-English `detail` and an
actionable `fix`:

    server -> machine_config -> share -> corpus -> models

THE LADDER SHORT-CIRCUITS. Once a rung fails, every rung below it reports
`ok: null` — "not checked" — rather than running and failing too. This is
the difference between an admin fixing the right thing and an admin
chasing a corpus corruption that does not exist: a share nobody can reach
obviously cannot have its corpus read, and printing "corpus: broken"
underneath "share: unreachable" is two problems where there is one.

NOTHING HERE RAISES. Everything else in the app may fail; this is the
thing that explains the failure, so it must survive conditions nothing
else does.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from typing import Any, Callable

from store.config import resolve_data_dir

# Order is the dependency order — each rung assumes the ones above it.
RUNGS = ("server", "machine_config", "share", "corpus", "models")

NOT_CHECKED = "Not checked — fix the problem above first."

# The two ONNX models retrieval needs, as fastembed names their cache
# directories. Checked as DIRECTORIES rather than by loading them: this
# runs on every health poll and loading an embedding model takes seconds
# and hundreds of megabytes of RAM.
_MODEL_DIRS = (
    ("models--Snowflake--snowflake-arctic-embed-m", "the search model"),
    ("models--Xenova--ms-marco-MiniLM-L-12-v2", "the result-ranking model"),
)


def _fastembed_cache() -> Path:
    """Where fastembed keeps the ONNX models.

    Mirrors `fastembed.common.utils.define_cache_dir` rather than calling
    it, because that function CREATES the directory as a side effect —
    which would make this health check manufacture the very thing it is
    checking for, and report a fresh empty cache as present.
    """
    default = os.path.join(tempfile.gettempdir(), "fastembed_cache")
    return Path(os.environ.get("FASTEMBED_CACHE_PATH", default))


def _models_present() -> tuple[bool, str]:
    """(all present, the name of the first one missing)."""
    cache = _fastembed_cache()
    for dirname, human in _MODEL_DIRS:
        if not (cache / dirname).is_dir():
            return False, human
    return True, ""


# ---------------------------------------------------------------------------
# Rung checks
# ---------------------------------------------------------------------------
# Each returns (ok, detail, fix). `fix` is None when ok. Every one of them
# swallows its own exceptions — see the module docstring.


def _check_server() -> tuple[bool, str, str | None]:
    # If you are reading this, you got a response. Claiming anything else
    # would be a lie the reader can disprove by being here.
    return True, "The app is running on this computer.", None


def _check_machine_config() -> tuple[bool, str, str | None]:
    from app.machine_config import machine_config_path

    path = machine_config_path()
    if not path.exists():
        # The overwhelmingly common case, and not a problem: nobody has
        # needed to relocate the folder on this machine.
        return True, "Using the standard shared-folder setting.", None
    try:
        import json

        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return (
            False,
            "This computer has a settings file saying where the shared folder "
            "is, and it can't be read.",
            f"Delete this file and reopen the app: {path}",
        )
    if not isinstance(raw, dict):
        return (
            False,
            "This computer's shared-folder setting is not in the expected form.",
            f"Delete this file and reopen the app: {path}",
        )
    return True, "This computer's shared-folder setting is readable.", None


def _check_share(root: Path) -> tuple[bool, str, str | None]:
    if not root.exists():
        return (
            False,
            f"The shared folder can't be found: {root}",
            "Check the shared drive is connected. If the folder has moved, "
            "enter its new location below.",
        )
    if not root.is_dir():
        return (
            False,
            f"The shared folder setting points at a file, not a folder: {root}",
            "Enter the folder that holds the JLBC Insight data.",
        )
    try:
        # Actually touch it — a mapped drive that has gone away often still
        # passes `exists()` and fails the moment anything is read.
        next(root.iterdir(), None)
    except OSError as err:
        return (
            False,
            f"The shared folder can't be read: {root} ({err.strerror or err}).",
            "Check the shared drive is connected and that you have permission "
            "to open it.",
        )
    return True, f"The shared folder is reachable: {root}", None


def _check_corpus(root: Path) -> tuple[bool, str, str | None]:
    if not (root / "lancedb").is_dir():
        return (
            False,
            "The shared folder is reachable, but it has no search index in it.",
            "This usually means the folder is the wrong one — it should "
            "contain a folder called 'lancedb'. Check with whoever set up "
            "the app.",
        )
    try:
        from store.chunk_store import ChunkStore

        count = ChunkStore().count("budget_chunks")
    except Exception as err:  # noqa: BLE001
        return (
            False,
            f"The search index is there but could not be opened ({type(err).__name__}).",
            "Restore a recent snapshot from the Admin page, or ask whoever "
            "maintains the app.",
        )
    if count <= 0:
        # OK, not a failure. A fresh install genuinely has no documents yet,
        # and failing this rung would put the whole app behind the failure
        # screen — including the Upload page that is the only way to fix it.
        return (
            True,
            "The search index is set up but has no budget documents in it yet.",
            None,
        )
    return True, f"The search index holds {count:,} budget passages.", None


def _check_models() -> tuple[bool, str, str | None]:
    present, missing = _models_present()
    if not present:
        # On a packaged bundle these ship pre-downloaded (S7), so "missing"
        # means a broken install — NOT a download that hasn't happened yet.
        # Saying "downloading, please wait" would leave someone waiting
        # forever.
        return (
            False,
            f"Part of the app is missing: {missing} files aren't installed.",
            "This is an incomplete install rather than something you did — "
            "reinstall JLBC Insight from the original zip.",
        )
    return True, "The search models are installed on this computer.", None


def health_detail() -> dict[str, Any]:
    """The full ladder. Never raises; never leaks a traceback into a field."""
    rungs: list[dict[str, Any]] = []
    failed = False
    first_failure: str | None = None
    root: Path | None = None

    try:
        # resolve_, not data_dir: `data_dir()` CREATES the folder, which
        # would make this check manufacture the very thing it is checking
        # for and report a freshly-made empty share as healthy.
        root = resolve_data_dir()
    except Exception:  # noqa: BLE001
        root = None

    checks: list[tuple[str, Callable[[], tuple[bool, str, str | None]]]] = [
        ("server", _check_server),
        ("machine_config", _check_machine_config),
        ("share", lambda: (
            _check_share(root) if root is not None
            else (False, "The shared folder location could not be worked out.",
                  "Enter the folder that holds the JLBC Insight data.")
        )),
        ("corpus", lambda: (
            _check_corpus(root) if root is not None
            else (False, "No shared folder to check.", "Set the shared folder first.")
        )),
        ("models", _check_models),
    ]

    for name, check in checks:
        if failed:
            # Short-circuit. See the module docstring — a second scary line
            # under the real one sends an admin after the wrong problem.
            rungs.append({"name": name, "ok": None, "detail": NOT_CHECKED, "fix": None})
            continue
        try:
            ok, detail, fix = check()
        except Exception as err:  # noqa: BLE001
            ok = False
            detail = f"This check could not be completed ({type(err).__name__})."
            fix = "Reopen the app. If it keeps happening, ask whoever maintains it."
        rungs.append({"name": name, "ok": ok, "detail": detail, "fix": fix if not ok else None})
        if not ok:
            failed = True
            first_failure = name

    return {
        "ok": not failed,
        "rungs": rungs,
        "data_dir": str(root) if root is not None else None,
        # The repair box only helps when the problem IS where the app is
        # pointed. Offering it for a corrupt corpus would waste an admin's
        # time on an action that cannot fix their problem.
        "can_repair": first_failure == "share",
    }
