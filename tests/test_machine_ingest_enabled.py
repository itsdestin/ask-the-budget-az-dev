"""Per-machine ingest switch (Session B's app-requirement #1).

The packaging decision was ONE bundle installed on all ~20 office PCs.
`launcher.pyw` calls `create_app()` with no arguments, so without this
flag all twenty start an ingest worker against the one shared corpus.
`IngestLock` keeps that safe — nothing corrupts — but the machine that
wins the race is arbitrary, and it may be an analyst's laptop that then
spends six hours at 100% CPU on a Baseline book while they try to work.

Per-machine, NOT in `settings.json`: settings.json lives on the share and
is shared by every machine, which is the wrong home for "is THIS PC the
one that does the work".

Defaulting to OFF re-creates the opposite failure — uploads queue on the
share and nothing drains them, silently. That is why the admin warning
(tests/test_admin_queue_warning.py) is not optional.
"""
from __future__ import annotations

import json

import pytest

from app.machine_config import (
    ingest_enabled,
    machine_config_path,
    read_data_dir,
    set_data_dir,
    set_ingest_enabled,
)


@pytest.fixture(autouse=True)
def _machine_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path))
    monkeypatch.delenv("JLBC_INGEST_ENABLED", raising=False)
    return tmp_path


def _write(payload: dict) -> None:
    machine_config_path().write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# The default
# ---------------------------------------------------------------------------


def test_ingest_is_off_when_nothing_is_configured():
    """Twenty machines, one queue. Off unless someone said otherwise."""
    assert ingest_enabled() is False


def test_a_machine_json_without_the_key_is_still_off():
    """Install-JLBC-Search.cmd's file, or one written before this flag existed. Silence
    must not read as consent — that is the twenty-workers case."""
    # The forward-slash UNC form survives on Linux (normalize_data_dir only
    # rewrites separators on nt). On Windows the stored form is
    # \\server\share\... — pinned in tests/test_machine_config.py.
    _write({"data_dir": "//server/share/JLBC-Search-Data"})

    assert ingest_enabled() is False


def test_turning_it_on_is_recorded():
    set_ingest_enabled(True)
    assert ingest_enabled() is True

    set_ingest_enabled(False)
    assert ingest_enabled() is False


# ---------------------------------------------------------------------------
# The env override
# ---------------------------------------------------------------------------


def test_the_env_var_wins_over_the_file(monkeypatch):
    """Same resolution order as the data dir: env > machine.json > default.

    This is what a dev clone and the backfill machine use — neither has a
    machine.json, and neither should have to click a button in a browser
    to make its own queue run.
    """
    _write({"ingest_enabled": False})
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "1")

    assert ingest_enabled() is True


def test_the_env_var_can_also_turn_it_off(monkeypatch):
    _write({"ingest_enabled": True})
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "0")

    assert ingest_enabled() is False


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on", " true "])
def test_truthy_spellings(monkeypatch, value):
    monkeypatch.setenv("JLBC_INGEST_ENABLED", value)
    assert ingest_enabled() is True


@pytest.mark.parametrize("value", ["0", "false", "no", "off", ""])
def test_falsy_spellings(monkeypatch, value):
    monkeypatch.setenv("JLBC_INGEST_ENABLED", value)
    assert ingest_enabled() is False


def test_a_nonsense_env_value_falls_back_to_the_file(monkeypatch):
    """A typo must not silently mean "off" on the one machine that WAS
    configured to do the work — that is the silent pile-up again."""
    _write({"ingest_enabled": True})
    monkeypatch.setenv("JLBC_INGEST_ENABLED", "maybe")

    assert ingest_enabled() is True


# ---------------------------------------------------------------------------
# The two settings share one file
# ---------------------------------------------------------------------------


def test_setting_the_data_dir_preserves_the_ingest_flag():
    """`set_data_dir` used to write `{"data_dir": ...}` wholesale. Using
    the repair screen would have silently switched off the ingest machine
    — and the symptom is uploads that never process, days later."""
    set_ingest_enabled(True)

    set_data_dir("//server/share/JLBC-Search-Data")

    assert ingest_enabled() is True
    assert str(read_data_dir()) == "//server/share/JLBC-Search-Data"


def test_setting_the_ingest_flag_preserves_the_data_dir():
    set_data_dir("//server/share/JLBC-Search-Data")

    set_ingest_enabled(True)

    assert str(read_data_dir()) == "//server/share/JLBC-Search-Data"


def test_a_corrupt_file_does_not_stop_the_flag_being_set():
    """This module's contract: nothing raises on a broken file, because
    this is exactly when the app must still boot to the repair screen."""
    machine_config_path().write_text("{not json", encoding="utf-8")

    set_ingest_enabled(True)

    assert ingest_enabled() is True


def test_a_corrupt_file_reads_as_off():
    machine_config_path().write_text("{not json", encoding="utf-8")

    assert ingest_enabled() is False
