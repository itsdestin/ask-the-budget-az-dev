"""Shared pytest fixtures.

Currently one job: keep `store.documents`' process-wide cache from leaking
between tests.
"""
from __future__ import annotations

import pytest

from store.documents import reset_documents_cache


@pytest.fixture(autouse=True)
def _isolate_documents_cache():
    """Clear the documents.json cache around every test.

    WHY autouse rather than opt-in: Plan 5 Task 19 replaced four
    per-module caches with one module-level cache, which means a suite
    that never mentions documents.json can now inherit a parse from a
    suite that does. The cache invalidates on (path, mtime_ns, size), so
    a leak needs a same-path same-size rewrite inside one filesystem
    tick — rare, and therefore the flakiest possible failure to diagnose
    when it does happen. Clearing costs nothing.

    Cleared BOTH before and after: before so a test starts clean, after
    so a test that wrote a tmp sidecar doesn't leave that parse behind
    for whatever runs next.
    """
    reset_documents_cache()
    yield
    reset_documents_cache()
