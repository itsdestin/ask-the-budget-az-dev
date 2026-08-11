# tests/test_harness_history.py
import ast
import json
from pathlib import Path

import pytest

from harness import history

MODULE_SOURCE_PATH = Path(history.__file__)


@pytest.fixture(autouse=True)
def _tmp_history(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_HISTORY_DIR", str(tmp_path / "conversations"))
    yield


def _t(**kw):
    base = dict(
        id="abc123", title="ADC vacancy savings", title_is_manual=False,
        corpus="budget", created_at="2026-08-02T10:00:00+00:00",
        updated_at="2026-08-02T10:05:00+00:00",
        messages=[{"role": "user", "content": "hi"}],
    )
    base.update(kw)
    return history.Transcript(**base)


def test_a_saved_transcript_round_trips_exactly():
    history.save(_t())
    got = history.load("abc123")
    assert got is not None
    assert got.messages == [{"role": "user", "content": "hi"}]
    assert got.corpus == "budget"
    assert got.title_is_manual is False


def test_listing_omits_messages_but_keeps_the_count():
    """The rail needs a count without paying for a second read of every file."""
    history.save(_t(messages=[{"role": "user", "content": "a"},
                              {"role": "assistant", "content": "b"}]))
    rows = history.list_all()
    assert len(rows) == 1
    assert rows[0].messages == []
    assert rows[0].message_count == 2


def test_the_count_is_never_persisted():
    """A stored count could disagree with the stored messages."""
    history.save(_t())
    raw = json.loads((history.conversations_dir() / "abc123.json").read_text())
    assert "message_count" not in raw


def test_listing_is_newest_first():
    history.save(_t(id="old", updated_at="2026-08-01T00:00:00+00:00"))
    history.save(_t(id="new", updated_at="2026-08-02T00:00:00+00:00"))
    assert [r.id for r in history.list_all()] == ["new", "old"]


def test_a_corrupt_transcript_is_skipped_not_fatal():
    """One bad file must never take down the whole rail."""
    history.save(_t(id="good"))
    bad = history.conversations_dir() / "bad.json"
    bad.write_text("{ this is not json", encoding="utf-8")
    assert [r.id for r in history.list_all()] == ["good"]
    assert history.load("bad") is None


def test_delete_removes_the_file_and_reports_whether_it_existed():
    history.save(_t())
    assert history.delete("abc123") is True
    assert history.load("abc123") is None
    assert history.delete("abc123") is False


def test_rename_sets_the_manual_flag_so_auto_naming_cannot_overwrite_it():
    history.save(_t())
    assert history.rename("abc123", "Corrections vacancies") is True
    got = history.load("abc123")
    assert got.title == "Corrections vacancies"
    assert got.title_is_manual is True


def test_renaming_does_not_move_a_chat_to_the_top_of_the_rail():
    """`updated_at` means "last thing the analyst SAID", not "last write".

    The rail sorts on it. If a rename bumped it, retitling a chat from March
    would reorder it above this morning's — a rename is bookkeeping, not
    conversation.
    """
    history.save(_t(id="old", updated_at="2026-08-01T00:00:00+00:00"))
    history.save(_t(id="new", updated_at="2026-08-02T00:00:00+00:00"))
    history.rename("old", "Renamed")
    assert [r.id for r in history.list_all()] == ["new", "old"]


def test_an_id_that_is_not_a_bare_filename_is_refused():
    """Path traversal: an id reaches this module from an HTTP path segment."""
    for evil in ("../secrets", "a/b", "a\\b", "", ".", ".."):
        with pytest.raises(ValueError):
            history.load(evil)


def test_this_module_imports_nothing_that_knows_where_the_share_is():
    """Invariant 7: history must not be able to learn where the share is.

    Same guard, same SHAPE, same reason as
    tests/test_create_document.py:338 — an ALLOWLIST of import roots, not a
    denylist of `store`. A denylist only refuses the spelling somebody
    thought of; `harness.settings`, `store`, `retrieval` and `app` all reach
    the share in one or two hops, and an allowlist refuses every one of them
    including the ones added next year.
    """
    # `uuid` and `threading` are stdlib and cannot reach the share: uuid backs
    # the per-call tmp name in save(), threading backs the per-id write locks.
    # Everything else remains an allowlist refusal.
    allowed = {
        "__future__", "dataclasses", "datetime", "json", "os", "pathlib",
        "threading", "uuid",
    }
    tree = ast.parse(MODULE_SOURCE_PATH.read_text(encoding="utf-8"))
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            roots.add(node.module.split(".")[0])
    assert roots <= allowed, f"unexpected imports: {sorted(roots - allowed)}"
