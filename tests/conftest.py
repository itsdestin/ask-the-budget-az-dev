"""Shared pytest fixtures.

Two jobs: keep `store.documents`' process-wide cache from leaking between
tests, and keep the suite out of the ANALYST'S OWN chat history.
"""
from __future__ import annotations

import pytest

from store.documents import reset_documents_cache


@pytest.fixture(autouse=True)
def _isolate_chat_history(tmp_path_factory, monkeypatch):
    """Point chat history at a throwaway directory for EVERY test.

    Found 2026-08-11 by launching the app and reading the rail: the real
    history directory held **157 transcripts, 151 of them test fixtures** —
    "biggest agencies" ×60, "fy2026 appropriations" ×51 — and one more
    appeared on every `pytest tests/test_conversations_route.py` run.

    The route suites are the source and none of them ask for it. `persist_turn`
    runs from `_release_turn`, which rides a `BackgroundTask` that
    `TestClient` executes on the way out of the `with` block, so ANY test that
    drives a conversation to completion writes a transcript — with no mention
    of history anywhere in the test. Twenty-two test modules touch
    `create_app` or the conversation routes without setting `JLBC_HISTORY_DIR`.

    On this Linux dev box that means `~/.local/share/JLBC-Search/`. On the
    deployment target it is `%LOCALAPPDATA%\\JLBC-Search\\conversations` —
    an analyst's own chat list, filled with test chats by anyone who runs the
    suite on a machine that also runs the app.

    AUTOUSE, and set on the ENV rather than fixed per module, for the same
    reason the documents-cache fixture above is autouse: the write is a side
    effect of a background task, so the tests that need protecting are exactly
    the ones whose authors have no reason to think about history at all. An
    opt-in fixture protects the modules someone remembered.

    One directory per test session, not per test: `conversations_dir()` reads
    the env var on every call, so isolation from the REAL directory is what
    matters here. A test that needs isolation from other tests sets
    `JLBC_HISTORY_DIR` itself, and that override still wins — monkeypatch
    applies this first, and a test-local `setenv` runs after it.
    """
    monkeypatch.setenv(
        "JLBC_HISTORY_DIR",
        str(tmp_path_factory.mktemp("chat-history-isolation")),
    )
    yield


@pytest.fixture(autouse=True)
def _isolate_office_guidance_data_dir(tmp_path_factory, monkeypatch):
    """Point JLBC_DATA_DIR at a throwaway directory for EVERY test.

    `office_guidance_block()` (spec E2, Task 5) reads `office-guidance.md`
    out of `store.config.data_dir()`, which resolves `JLBC_DATA_DIR` >
    `machine.json` > the repo default — i.e., on any dev or CI machine
    that has ever saved office guidance, a REAL file. `build_system_prompt`
    calls it on every render, so any of the ~134 other prompt-adjacent
    tests that never mention guidance at all (only `test_office_guidance.py`
    repoints `guidance_path` itself) would start asserting against
    whatever that machine's real guidance happens to contain: a stray
    `{{` in it raises `PromptTemplateError` outright, and every
    byte-length / "not in prompt" / cache-prefix assertion in
    `test_harness_prompt.py`, `test_harness_prompt_caching.py`,
    `test_citation_prompt.py`, and `test_system_prompt_lifecycle.py`
    silently changes meaning instead.

    AUTOUSE for the same reason the chat-history fixture above is: the
    read is a side effect of building ANY system prompt, so the tests
    that need protecting are exactly the ones whose authors had no
    reason to think about office guidance at all.

    Import deferred into the fixture body rather than module scope, so a
    suite that never touches the harness doesn't pay for it at collection
    time.
    """
    from harness.office_guidance import reset_guidance_cache

    monkeypatch.setenv(
        "JLBC_DATA_DIR",
        str(tmp_path_factory.mktemp("office-guidance-isolation")),
    )
    reset_guidance_cache()
    yield
    reset_guidance_cache()


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
