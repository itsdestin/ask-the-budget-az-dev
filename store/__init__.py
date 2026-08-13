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
from store.config import data_dir  # noqa: F401


def __getattr__(name: str):
    if name in ("ChunkStore", "DEFAULT_DIM"):
        from store import chunk_store

        return getattr(chunk_store, name)
    raise AttributeError(f"module 'store' has no attribute {name!r}")
