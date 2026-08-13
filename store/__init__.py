# WHY `ChunkStore`/`DEFAULT_DIM` are exposed lazily (PEP 562 `__getattr__`)
# rather than imported eagerly above: `store.chunk_store` imports `lancedb`,
# and EVERY import of `store.config` — even just for `data_dir` — first runs
# this file, because that's how Python packages work. Task 5 (spec E2) needs
# `harness/office_guidance.py` to reach `data_dir()` without dragging LanceDB
# into `harness/prompt.py`'s import closure (a system prompt build must not
# load LanceDB or the ONNX models). Nothing in the repo actually imports
# `store.ChunkStore`/`store.DEFAULT_DIM` at the package level — every caller
# already spells it `store.chunk_store.ChunkStore` — so this changes no
# behavior for existing callers and only removes the eager import.
from typing import Any

from store.config import data_dir  # noqa: F401

# WHY this exists despite the lazy __getattr__ below: `__all__` is what
# `from store import *` and `dir(store)` read, and PEP 562 `__getattr__`
# doesn't populate either of those on its own — without this list,
# ChunkStore/DEFAULT_DIM would work when named directly but be invisible
# to tooling and star-imports.
__all__ = ["ChunkStore", "DEFAULT_DIM", "data_dir"]


def __getattr__(name: str) -> Any:
    if name in ("ChunkStore", "DEFAULT_DIM"):
        from store import chunk_store

        return getattr(chunk_store, name)
    raise AttributeError(f"module 'store' has no attribute {name!r}")
