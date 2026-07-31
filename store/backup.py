"""Corpus snapshots and one-click restore (spec S17).

The corpus is the app's crown jewels sitting in one shared folder with no
technical successor. It is well under a gigabyte, so a full zip before every
write costs seconds and turns the worst data disaster — a half-finished
ingest, a mis-clicked delete, a share hiccup mid-write — into a two-click
recovery instead of a re-run of a multi-hour re-embed.

Snapshots cover `lancedb/` only. `pdfs/` is content-addressed and
re-downloadable from public URLs; `documents.json` is regenerable from the
migration script. Zipping the vectors is the part that can't be redone
cheaply.

**Callers must hold the ingest lock.** `snapshot()` reads a corpus that a
concurrent writer could be mutating, and `restore()` replaces it wholesale.
Both are called from inside the ingest worker's write phase (or Plan 5's
admin route), which takes `ingest.lock.IngestLock` first.
"""
from __future__ import annotations

import shutil
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from store.config import data_dir

BACKUPS_DIRNAME = "backups"
CORPUS_DIRNAME = "lancedb"
SNAPSHOT_PREFIX = "lancedb-"
SNAPSHOT_SUFFIX = ".zip"

# Five is enough to survive a bad ingest that isn't noticed until the next
# day, without letting backups outgrow the corpus they protect.
SNAPSHOT_KEEP = 5


def backups_dir() -> Path:
    """Snapshot directory under the shared data dir (created on demand)."""
    path = data_dir() / BACKUPS_DIRNAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_snapshots() -> list[str]:
    """Snapshot filenames, newest first.

    Sorting by name rather than mtime is deliberate: the UTC-compact
    timestamp in the name sorts lexicographically, and file mtimes on an SMB
    share are the one piece of metadata most likely to be wrong.
    """
    return sorted(
        (
            p.name
            for p in backups_dir().glob(f"{SNAPSHOT_PREFIX}*{SNAPSHOT_SUFFIX}")
            if p.is_file()
        ),
        reverse=True,
    )


def snapshot() -> str | None:
    """Zip the current corpus into `backups/`, returning the snapshot name.

    Returns None when there's no corpus yet — the first ingest into an empty
    data dir has nothing to protect, and an empty zip would just consume a
    rotation slot that a real snapshot needs later.
    """
    corpus = data_dir() / CORPUS_DIRNAME
    if not corpus.is_dir():
        return None

    target = backups_dir() / _unique_snapshot_name()
    # Write to a .part first so a crash (or a share disconnect) mid-zip can't
    # leave a truncated archive that list_snapshots() would offer as a restore
    # candidate. The rename is the commit.
    partial = target.with_suffix(target.suffix + ".part")
    try:
        with zipfile.ZipFile(partial, "w", zipfile.ZIP_DEFLATED) as zf:
            for path in sorted(corpus.rglob("*")):
                if path.is_file():
                    zf.write(path, path.relative_to(corpus).as_posix())
        partial.replace(target)
    finally:
        partial.unlink(missing_ok=True)

    _prune()
    return target.name


def restore(name: str) -> None:
    """Replace the corpus with the contents of snapshot `name`.

    The existing `lancedb/` is removed first, not merged over: a restore is
    usually recovering from a half-written table, and leaving those files in
    place would mix corrupt fragments into the good corpus.
    """
    archive = backups_dir() / _validated_name(name)
    if not archive.is_file():
        raise FileNotFoundError(f"No corpus snapshot named {name!r}")

    corpus = data_dir() / CORPUS_DIRNAME
    if corpus.exists():
        shutil.rmtree(corpus)
    corpus.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf:
        zf.extractall(corpus)


# --- internals --------------------------------------------------------------


def _unique_snapshot_name() -> str:
    """Timestamped name, disambiguated if one already exists this second.

    Two snapshots inside the same second are rare in production (writes are
    minutes apart) but routine in tests, and a silent overwrite would quietly
    reduce the rotation depth.
    """
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    base = f"{SNAPSHOT_PREFIX}{stamp}"
    candidate = f"{base}{SNAPSHOT_SUFFIX}"
    n = 1
    while (backups_dir() / candidate).exists():
        candidate = f"{base}-{n:02d}{SNAPSHOT_SUFFIX}"
        n += 1
    return candidate


def _prune() -> None:
    for stale in list_snapshots()[SNAPSHOT_KEEP:]:
        (backups_dir() / stale).unlink(missing_ok=True)


def _validated_name(name: str) -> str:
    """Reject anything that isn't a bare snapshot filename.

    `name` arrives from an admin HTTP route in Plan 5, so a path component
    here would let a request read (and then extract over the corpus) an
    arbitrary zip on the share.
    """
    if (
        name != Path(name).name
        or not name.startswith(SNAPSHOT_PREFIX)
        or not name.endswith(SNAPSHOT_SUFFIX)
    ):
        raise ValueError(f"Not a corpus snapshot name: {name!r}")
    return name
