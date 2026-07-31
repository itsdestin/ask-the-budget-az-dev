"""Shared-data directory resolution.

One env var controls where ALL shared state lives (LanceDB, pdfs,
settings, locks): JLBC_DATA_DIR. In production this points at the
office network share (e.g. \\\\JLBC-share\\...\\jlbc-insight-data).
On a dev machine it's unset and falls back to data/insight-data inside
the repo (gitignored), so tests and dev never touch a share.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

_ENV_VAR = "JLBC_DATA_DIR"

# Document-level metadata (title, source_format, source_blob_path, …), keyed
# by doc_id. A JSON sidecar rather than a LanceDB table because it is ~382
# small records that every layer wants whole: the sidecar reads it to answer
# /docs, and one file is trivially copyable alongside `lancedb/` when the
# corpus travels to another machine. Written by
# scripts/migrate_to_lancedb.py (and by ingest once Plan 3 owns it).
DOCUMENTS_FILE = "documents.json"

# Every field a documents.json entry carries, verified against
# db/migrations/0001_initial_schema.sql's `documents` table. `extractor` /
# `extractor_version` are deliberately left behind: nothing reads them.
DOCS_FIELDS = (
    "title", "publisher", "doc_type", "fiscal_year",
    "source_format", "source_blob_path", "source_url", "page_count",
)


def data_dir() -> Path:
    """Resolve (and create if needed) the shared-data root directory.

    Resolution order (S18): `JLBC_DATA_DIR` > this machine's `machine.json`
    pointer > the repo default.

    The env var stays on TOP of the per-machine pointer deliberately. The
    Z13 backfill runs with it set, and a `machine.json` written on that box
    by the repair screen must never silently redirect a running multi-hour
    ingest into a different folder.
    """
    raw = os.environ.get(_ENV_VAR)
    if raw:
        root = Path(raw)
    else:
        # Imported inside the function, not at module scope: app.machine_config
        # is in the `app` package and this module is imported by `store`,
        # `harness` and `ingest` — a top-level import would make every one of
        # them depend on the app package, and `retrieval/` imports this from
        # scripts that never build a FastAPI app.
        from app.machine_config import read_data_dir

        configured = read_data_dir()
        if configured is not None:
            root = configured
        else:
            # WHY repo-relative: dev machines have no share; keeping the dev
            # corpus inside data/ (already gitignored) means zero setup.
            root = Path(__file__).resolve().parent.parent / "data" / "insight-data"
    try:
        root.mkdir(parents=True, exist_ok=True)
    except OSError as err:
        # An UNREACHABLE share is the normal case S18 exists to handle: the
        # drive moved, the letter changed, the network is down. Raising here
        # would take out every caller that merely wanted to know the PATH —
        # including `app/health.py`, whose entire job is to report this
        # condition as a plain sentence, and the repair screen that fixes it.
        # The path is still the right answer; whoever actually reads or writes
        # it fails with a more specific error than a mkdir would give.
        print(
            f"store.config: couldn't create or reach {root} ({err}). "
            "Returning the path anyway — the health check reports this and "
            "the repair screen fixes it.",
            file=sys.stderr,
        )
    return root


def documents_path() -> Path:
    """Path to the documents-metadata sidecar (may not exist yet).

    One definition, two callers — the migration writes this path and the
    retrieval sidecar reads it. Two copies of the literal filename is
    exactly the kind of drift that ends with a writer and a reader
    disagreeing silently.
    """
    return data_dir() / DOCUMENTS_FILE


def write_documents_sidecar(docs: dict[str, dict[str, Any]]) -> Path:
    """Write documents.json into the shared data dir; return its path.

    WHY the temp-file + replace: the retrieval sidecar reads this file live
    (on an mtime change), and on a network share a reader could otherwise
    catch a half-written file and log a JSON error. os.replace is atomic on
    both Windows and POSIX.

    WHY it lives here rather than in the migration script that first needed
    it: ingest writes this file on every upload now, and importing the
    migration script would pull psycopg into the ingest path that Plan 3
    exists to get Postgres out of. One writer, one definition, no Postgres.
    """
    path = documents_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(
        json.dumps(docs, indent=2, sort_keys=True, ensure_ascii=False),
        encoding="utf-8",
    )
    os.replace(tmp, path)
    return path
