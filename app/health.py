"""The launch health ladder (Plan 5 Task 11, spec S18).

What this replaces is a stack trace. When the shared drive moved, the app
failed somewhere inside LanceDB and the person sitting at the machine saw
a Python traceback — or a blank screen, or a spinner that never stopped.
None of those tell anyone what to do.

Five rungs, checked in order, each with a plain-English `detail` and an
actionable `fix`:

    server -> machine_config -> share -> corpus -> models

`machine_config` fails a corrupt or unreadable pointer file, AND (2026-08-25)
a bundle where nothing resolves at all — the laptop's actual failure, where
`can_repair` used to stay False and the folder box never rendered. A pointer
holding only `ingest_enabled` or `display_names` is normal and does not fail
this rung. `corpus` fails a `lancedb/` folder that holds no tables, the same
"wrong folder or half copy" shape as the missing-folder case above it; zero
ROWS in an existing table stays OK, since a fresh install must still reach
Upload.

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

# The corpus rung's one repairable failure: a folder with no `lancedb/` data
# in it at all, or a `lancedb/` with no tables — both are the same mistake
# (pointed at the wrong, usually parent, folder), and choosing the folder
# again is what fixes it. `can_repair` below matches on this constant rather
# than string content, so nothing here needs string matching (spec §2.5).
FIX_CHOOSE_AGAIN = "Choose the folder again."

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
    from store.config import DataDirNotConfigured, resolve_data_dir

    # No separate `fix` text below (spec §2.5, 2026-08-25): the repair
    # FORM itself — the Choose folder… button and the type-it-in box — is
    # the action, for every one of these failures. Repeating "type it
    # below" per rung is the sentence this rewrite exists to delete.
    path = machine_config_path()
    if path.exists():
        try:
            import json

            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False, "The saved location couldn't be read.", None
        if not isinstance(raw, dict):
            # Not a JSON object at all — same repair as unreadable: the
            # form below rewrites this file correctly either way.
            return False, "The saved location couldn't be read.", None
    # ONE rule for "the pointer names nothing": does anything resolve? A
    # machine.json holding only `ingest_enabled` or `display_names` is normal
    # (the installer and the Settings page both write those), and with
    # JLBC_DATA_DIR set — every dev box, the Z13 — a folder resolves anyway.
    # Only a packaged install with no env var and no pointer raises
    # (store/config.py::DataDirNotConfigured). The laptop sat exactly there.
    try:
        resolve_data_dir()
    except DataDirNotConfigured:
        return False, "No location is set on this computer yet.", None
    except OSError:
        pass  # a reachability problem is the share rung's to report
    if path.exists():
        return True, "This computer's shared-folder setting is readable.", None
    return True, "Using the standard shared-folder setting.", None


def _check_share(root: Path) -> tuple[bool, str, str | None]:
    # No separate `fix` here either (spec §2.5) — "choose the folder again"
    # is folded into the sentence itself, and the repair form below is the
    # actual action for every one of these.
    not_connected = (
        False,
        f"Can't find {root}. Check the network drive is connected, or "
        "choose the folder again.",
        None,
    )
    if not root.exists():
        return not_connected
    if not root.is_dir():
        return False, f"{root} is a file, not a folder.", None
    try:
        # Actually touch it — a mapped drive that has gone away often still
        # passes `exists()` and fails the moment anything is read.
        next(root.iterdir(), None)
    except OSError:
        return not_connected
    return True, f"The shared folder is reachable: {root}", None


def _check_corpus(root: Path) -> tuple[bool, str, str | None]:
    # "No lancedb/ folder at all" and "a lancedb/ folder with no tables" are
    # the SAME mistake (spec §2.5, 2026-08-25) — pointed at the wrong,
    # usually parent, folder — and get the same sentence and the same fix:
    # FIX_CHOOSE_AGAIN, so `can_repair` below can match on the constant
    # rather than parsing the sentence.
    no_data = False, f"{root} has no JLBC Search data in it.", FIX_CHOOSE_AGAIN
    if not (root / "lancedb").is_dir():
        return no_data
    try:
        from store.chunk_store import ChunkStore

        # create=False: this is a CHECK. Before 2026-08-25 it mkdir'd
        # <share>/lancedb, so a wrong pointer manufactured its own evidence.
        store = ChunkStore(root=root, create=False)
        if "budget_chunks" not in store.table_names():
            return no_data
        count = store.count("budget_chunks")
    except Exception as err:  # noqa: BLE001
        # A bare "ValueError" means nothing to the person who can fix this,
        # and neither failure is something the picker fixes — a corrupt or
        # foreign index is still there once you've chosen it (§2.5).
        msg = str(err)
        if "dim" in (msg + str(type(err).__name__)).lower():
            return (
                False,
                "That data was made by a different version of JLBC Search. "
                "Ask whoever maintains it to re-copy it.",
                None,
            )
        return (
            False,
            f"JLBC Search can't open the data in {root}. Ask whoever maintains it.",
            None,
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
            "reinstall JLBC Search from the original zip.",
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
                  "Enter the folder that holds the JLBC Search data.")
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

    # The repair box helps exactly when the problem IS where the app is
    # pointed: a missing/corrupt pointer, a pointer at a folder that is not
    # there, or (2026-08-25) the corpus rung's own "no data in it" case —
    # the wrong-parent-folder mistake, which choosing the folder again
    # fixes. Matched on FIX_CHOOSE_AGAIN, not string content, so this can't
    # drift from what `_check_corpus` actually decided.
    repairable = first_failure in ("machine_config", "share") or (
        first_failure == "corpus"
        and next(r for r in rungs if r["name"] == "corpus")["fix"] == FIX_CHOOSE_AGAIN
    )

    return {
        "ok": not failed,
        "rungs": rungs,
        "data_dir": str(root) if root is not None else None,
        "can_repair": repairable,
    }
