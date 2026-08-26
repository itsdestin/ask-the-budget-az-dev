"""Per-machine data-dir pointer (Plan 5 Task 10, spec S18).

The problem this solves: the shared drive moves, or is mapped to a
different letter on one PC, and the app on that machine can no longer
find the corpus. Today the only fix is an environment variable somebody
has to know how to set. S18 puts a pointer in a per-machine file the
repair screen can write.

Resolution order is the whole design, and the env var staying on top is
load-bearing: the Z13 backfill runs with `JLBC_DATA_DIR` set, and a
`machine.json` written by a repair screen must never quietly redirect it
mid-run.

The other property worth its own test: a broken `machine.json` must
never raise. This file being unreadable is EXACTLY the moment the app has
to still boot far enough to show the repair screen that fixes it.
"""
from __future__ import annotations

import json

import pytest

from app.machine_config import (
    MACHINE_FILE,
    MSG_CANT_OPEN,
    MSG_DIFFERENT_INDEX,
    MSG_NO_CORPUS,
    machine_config_path,
    read_data_dir,
    set_data_dir,
    validate_data_dir,
)
from store.config import data_dir


@pytest.fixture(autouse=True)
def _isolated_machine_config(monkeypatch, tmp_path):
    """Point the per-machine file somewhere throwaway.

    Without this every test here would read and WRITE the real
    ~/.config/jlbc-search/machine.json on the developer's own box — which
    would then silently redirect their dev corpus.
    """
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    yield


def make_corpus(root) -> None:
    (root / "lancedb").mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Resolution order
# ---------------------------------------------------------------------------


def test_env_var_wins_over_the_machine_file(monkeypatch, tmp_path):
    """The Z13 backfill depends on this.

    It runs with JLBC_DATA_DIR set. A machine.json written by a repair
    screen must not quietly redirect a running backfill to another folder.
    """
    env_dir = tmp_path / "from-env"
    file_dir = tmp_path / "from-file"
    make_corpus(env_dir)
    make_corpus(file_dir)
    set_data_dir(file_dir)
    monkeypatch.setenv("JLBC_DATA_DIR", str(env_dir))

    assert data_dir() == env_dir


def test_the_machine_file_wins_over_the_repo_default(tmp_path):
    share = tmp_path / "share"
    make_corpus(share)
    set_data_dir(share)

    assert data_dir() == share


def test_the_repo_default_applies_when_nothing_is_configured():
    # A dev machine with no share and no pointer. Not an error — this is
    # the normal state on a fresh clone.
    assert data_dir().name == "insight-data"
    assert read_data_dir() is None


# ---------------------------------------------------------------------------
# validate_data_dir
# ---------------------------------------------------------------------------


def test_validate_refuses_an_empty_index_folder(tmp_path):
    """lancedb.connect() on an empty directory SUCCEEDS and lists no tables
    (measured, lancedb 0.36) — so this lands on MSG_NO_CORPUS, not on
    'can't be opened'."""
    (tmp_path / "lancedb").mkdir()
    assert validate_data_dir(tmp_path) == MSG_NO_CORPUS


def test_validate_refuses_a_folder_the_engine_cannot_open(tmp_path, monkeypatch):
    """The laptop's InvalidUrl shape: pathlib says yes, the storage engine
    says no. Only an actual open can tell."""
    (tmp_path / "lancedb").mkdir()
    import store.chunk_store as cs

    def boom(*a, **k):
        raise ValueError("Invalid input, Failed to connect to namespace")

    monkeypatch.setattr(cs.lancedb, "connect", boom)
    assert validate_data_dir(tmp_path) == MSG_CANT_OPEN


def test_validate_accepts_a_folder_with_rows(tmp_path):
    """One row is enough — the check is 'has budget passages', not 'how many'.
    DEFAULT dim (768): validate opens with ChunkStore's default and `_open`
    checks the table's vector width, so an 8-dim test table would read as
    'can't be opened'."""
    from store.chunk_store import ChunkStore
    from tests.test_chunk_store import _row

    store = ChunkStore(root=tmp_path)
    store.upsert_chunks("budget_chunks", [_row("c1", "ahcccs", [0.0] * 768)])
    assert validate_data_dir(tmp_path) is None


def test_validate_refuses_a_different_embedding_model(tmp_path):
    """An index built with a different vector width — `_check_dim`'s guard.
    Retyping the address cannot fix this, so it gets its own sentence
    rather than the generic MSG_CANT_OPEN."""
    from store.chunk_store import ChunkStore
    from tests.test_chunk_store import _row

    store = ChunkStore(root=tmp_path, dim=8)
    store.upsert_chunks("budget_chunks", [_row("c1", "ahcccs", [0.0] * 8)])
    assert validate_data_dir(tmp_path) == MSG_DIFFERENT_INDEX


def test_validate_rejects_a_folder_with_no_corpus(tmp_path):
    (tmp_path / "empty").mkdir()
    # The exact sentence from the frozen API contract — the repair screen
    # renders it verbatim.
    assert validate_data_dir(tmp_path / "empty") == MSG_NO_CORPUS


def test_validate_rejects_a_path_that_is_not_a_directory(tmp_path):
    target = tmp_path / "a-file.txt"
    target.write_text("hello", encoding="utf-8")
    message = validate_data_dir(target)
    assert message and "folder" in message.lower()
    assert message != MSG_NO_CORPUS


def test_validate_rejects_a_path_that_does_not_exist(tmp_path):
    message = validate_data_dir(tmp_path / "nope")
    assert message and "can't find" in message.lower()


def test_validate_rejects_an_empty_path():
    message = validate_data_dir("")
    assert message and "folder" in message.lower()


# ---------------------------------------------------------------------------
# Reading and writing machine.json
# ---------------------------------------------------------------------------


def test_set_then_read_round_trips(tmp_path):
    share = tmp_path / "share"
    make_corpus(share)
    set_data_dir(share)
    assert read_data_dir() == share
    assert machine_config_path().name == MACHINE_FILE


def test_the_file_is_json_a_person_can_read_and_fix(tmp_path):
    share = tmp_path / "share"
    make_corpus(share)
    set_data_dir(share)
    # A non-technical admin following the handbook has to be able to open
    # this in Notepad and see what it says.
    raw = json.loads(machine_config_path().read_text(encoding="utf-8"))
    assert raw["data_dir"] == str(share)


def test_a_corrupt_file_falls_back_and_says_why(capsys, tmp_path):
    machine_config_path().parent.mkdir(parents=True, exist_ok=True)
    machine_config_path().write_text("{ not json", encoding="utf-8")

    # NEVER raises: this file being broken is exactly when the app must
    # still boot far enough to show the repair screen that fixes it.
    assert read_data_dir() is None
    assert data_dir().name == "insight-data"
    assert "machine" in capsys.readouterr().err.lower()


def test_a_file_with_the_wrong_shape_falls_back(tmp_path):
    machine_config_path().parent.mkdir(parents=True, exist_ok=True)
    machine_config_path().write_text(json.dumps(["not", "an object"]), encoding="utf-8")
    assert read_data_dir() is None


def test_a_blank_data_dir_entry_reads_as_unset(tmp_path):
    machine_config_path().parent.mkdir(parents=True, exist_ok=True)
    machine_config_path().write_text(json.dumps({"data_dir": "   "}), encoding="utf-8")
    assert read_data_dir() is None


def test_set_data_dir_replaces_a_previous_pointer(tmp_path):
    first, second = tmp_path / "one", tmp_path / "two"
    make_corpus(first)
    make_corpus(second)
    set_data_dir(first)
    set_data_dir(second)
    assert read_data_dir() == second
    # One pointer, not an accumulating list — a second entry would leave
    # two answers to "where is the corpus" with nothing to pick between.
    raw = json.loads(machine_config_path().read_text(encoding="utf-8"))
    assert raw["data_dir"] == str(second)


def test_set_data_dir_writes_atomically(tmp_path):
    """Same tmp-file + os.replace discipline as save_settings.

    A half-written pointer is indistinguishable from a corrupt one, and it
    would send the app to the repair screen it had just been used to
    escape.
    """
    share = tmp_path / "share"
    make_corpus(share)
    set_data_dir(share)
    leftovers = list(machine_config_path().parent.glob("*.tmp"))
    assert leftovers == []


def test_a_pointer_at_a_vanished_folder_does_not_crash_resolution(tmp_path):
    """The share was unplugged since the pointer was written.

    `data_dir()` must still return a path — the health ladder (Task 11) is
    what reports the folder is unreachable, in a sentence. Raising here
    would take down every import that touches store.config, including the
    ones the repair screen needs.
    """
    share = tmp_path / "share"
    make_corpus(share)
    set_data_dir(share)
    for child in sorted(share.rglob("*"), reverse=True):
        child.rmdir()
    share.rmdir()

    assert data_dir() == share


def test_an_unreachable_share_resolves_instead_of_raising(monkeypatch, capsys, tmp_path):
    """The share is gone — the exact condition S18 exists to recover from.

    `data_dir()` must still hand back a path. Raising would take out every
    caller that only wanted to KNOW the path, including `app/health.py`,
    whose whole job is to report this as a plain sentence, and the repair
    screen that fixes it.
    """
    unreachable = tmp_path / "gone"
    set_data_dir(unreachable)

    def refuse(*_args, **_kwargs):
        raise OSError("network path not found")

    monkeypatch.setattr("pathlib.Path.mkdir", refuse)

    assert data_dir() == unreachable
    assert "couldn't create or reach" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# Normalisation (2026-08-25, the laptop incident — see
# docs/superpowers/investigations/2026-08-25-windows-launch-failure.md)
# ---------------------------------------------------------------------------
import os
from pathlib import PurePosixPath

from app.machine_config import normalize_data_dir


@pytest.mark.parametrize(
    "typed, stored",
    [
        ("//bcpool/JLBCSearch", r"\\bcpool\JLBCSearch"),
        ("/bcpool/JLBCSearch", r"\\bcpool\JLBCSearch"),
        ("E:/JLBCSearch/", r"E:\JLBCSearch"),
        ('"E:\\JLBCSearch\\"', r"E:\JLBCSearch"),
        ("E:\\", "E:\\"),
        ("E:", "E:\\"),  # bare drive = "cwd on E:" — never store that
        (r"\\bcpool\JLBCSearch", r"\\bcpool\JLBCSearch"),
        ("  Z:/x/y  ", r"Z:\x\y"),
    ],
)
def test_normalize_on_windows(monkeypatch, typed, stored):
    """The exact strings from the 2026-08-18 laptop log. `//bcpool/JLBCSearch`
    passed every Path check, was saved, and LanceDB refused it (InvalidUrl)."""
    monkeypatch.setattr(os, "name", "nt")
    assert normalize_data_dir(typed) == stored


def test_normalize_on_posix_only_trims(monkeypatch):
    monkeypatch.setattr(os, "name", "posix")
    assert normalize_data_dir(' "/mnt/share/jlbc/" ') == "/mnt/share/jlbc"
    assert normalize_data_dir("//server/share/x") == "//server/share/x"


def test_read_data_dir_normalises_a_pointer_written_before_the_fix(
    monkeypatch, tmp_path
):
    """The three beta laptops carry the exact `//bcpool/JLBCSearch` spelling
    that caused the 2026-08-18 launch failure, written before `set_data_dir`
    normalised anything. An upgrade that skips the shared-folder question
    leaves it in place, so the READ has to heal it too — otherwise the
    analyst meets a repair screen for a folder that is actually correct."""
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    (tmp_path / MACHINE_FILE).write_text(
        json.dumps({"data_dir": "//bcpool/JLBCSearch"}), encoding="utf-8"
    )
    monkeypatch.setattr(os, "name", "nt")
    # Substituting PurePosixPath is what makes this test able to FAIL. With
    # `os.name` faked to "nt", `Path(...)` builds a WindowsPath, and a
    # WindowsPath silently rewrites `//bcpool/JLBCSearch` into the same
    # string as the normalised form — so the unfixed code would pass here.
    # PurePosixPath keeps whatever string the function derived, verbatim.
    import app.machine_config as mc

    monkeypatch.setattr(mc, "Path", PurePosixPath)
    assert str(read_data_dir()) == r"\\bcpool\JLBCSearch"
    # And the read stays side-effect-free: the file is not rewritten.
    assert json.loads((tmp_path / MACHINE_FILE).read_text(encoding="utf-8")) == {
        "data_dir": "//bcpool/JLBCSearch"
    }


def test_read_data_dir_on_posix_only_trims(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    (tmp_path / MACHINE_FILE).write_text(
        json.dumps({"data_dir": '  "/mnt/share/jlbc/"  '}), encoding="utf-8"
    )
    monkeypatch.setattr(os, "name", "posix")
    assert str(read_data_dir()) == "/mnt/share/jlbc"


def test_set_data_dir_stores_the_normalised_form(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    monkeypatch.setattr(os, "name", "nt")
    from app.machine_config import machine_config_path, set_data_dir

    set_data_dir("//bcpool/JLBCSearch")
    raw = json.loads(machine_config_path().read_text(encoding="utf-8"))
    assert raw["data_dir"] == r"\\bcpool\JLBCSearch"
