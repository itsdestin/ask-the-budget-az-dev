"""Shared-data directory resolution.

One env var controls where ALL shared state lives (LanceDB, pdfs,
settings, locks): JLBC_DATA_DIR. In production this points at the
office network share (e.g. \\\\JLBC-share\\...\\jlbc-insight-data).
On a dev machine it's unset and falls back to data/insight-data inside
the repo (gitignored), so tests and dev never touch a share.
"""
from __future__ import annotations

import os
from pathlib import Path

_ENV_VAR = "JLBC_DATA_DIR"


def data_dir() -> Path:
    """Resolve (and create if needed) the shared-data root directory."""
    raw = os.environ.get(_ENV_VAR)
    if raw:
        root = Path(raw)
    else:
        # WHY repo-relative: dev machines have no share; keeping the dev
        # corpus inside data/ (already gitignored) means zero setup.
        root = Path(__file__).resolve().parent.parent / "data" / "insight-data"
    root.mkdir(parents=True, exist_ok=True)
    return root
