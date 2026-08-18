"""`python -m app.machine_config` (Session B's app-requirement #3).

`packaging/install.cmd` writes `%LOCALAPPDATA%\\JLBC-Search\\machine.json`
with a hand-rolled JSON literal, because the app is not running at
install time. That is the schema duplicated in a batch file, and it will
rot the first time `app/machine_config.py` changes shape — which this
branch just did, by adding `ingest_enabled` beside `data_dir`.

The contract Session B asked for, verbatim, because the installer
depends on each clause:

  * exit 0 on success,
  * non-zero with a one-line message on stderr otherwise,
  * runs `validate_data_dir()` but **must not fail the install when
    validation fails** — a network drive that is not connected during
    setup is normal, and refusing to record the path would strand the
    user. Print the warning, record the path, exit 0.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


def run(*args, config_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "app.machine_config", *args],
        cwd=REPO,
        env={
            "PATH": "/usr/bin:/bin",
            "JLBC_MACHINE_CONFIG_DIR": str(config_dir),
            "PYTHONPATH": str(REPO),
        },
        capture_output=True,
        text=True,
    )


@pytest.fixture
def config_dir(tmp_path):
    return tmp_path / "machine"


def _written(config_dir: Path) -> dict:
    return json.loads((config_dir / "machine.json").read_text(encoding="utf-8"))


def test_records_a_valid_corpus_folder(tmp_path, config_dir):
    share = tmp_path / "share"
    (share / "lancedb").mkdir(parents=True)

    result = run("--set-data-dir", str(share), config_dir=config_dir)

    assert result.returncode == 0, result.stderr
    assert _written(config_dir)["data_dir"] == str(share)


def test_an_unreachable_share_is_a_WARNING_not_a_failure(tmp_path, config_dir):
    """THE clause that matters. Setup routinely runs on a laptop that is
    not on the office network. Refusing to record the path there would
    strand the user with an installed app that cannot be pointed anywhere.
    """
    missing = tmp_path / "not-mounted"

    result = run("--set-data-dir", str(missing), config_dir=config_dir)

    assert result.returncode == 0
    assert result.stderr.strip()                       # it said something
    assert _written(config_dir)["data_dir"] == str(missing)   # …and recorded it


def test_a_folder_without_a_corpus_still_records(tmp_path, config_dir):
    """`validate_data_dir` rejects the bundle's own `data/` folder (no
    `lancedb/` inside), which is exactly the "right idea, wrong folder"
    case the repair screen exists for. Still a warning, not a failure."""
    plain = tmp_path / "plain"
    plain.mkdir()

    result = run("--set-data-dir", str(plain), config_dir=config_dir)

    assert result.returncode == 0
    assert "lancedb" in result.stderr.lower()
    assert _written(config_dir)["data_dir"] == str(plain)


def test_a_blank_path_is_a_real_failure(config_dir):
    """The one case that IS an error: nothing to record. Non-zero with a
    single line, per the contract."""
    result = run("--set-data-dir", "   ", config_dir=config_dir)

    assert result.returncode != 0
    assert len(result.stderr.strip().splitlines()) == 1
    assert not (config_dir / "machine.json").exists()


def test_no_arguments_is_a_usage_error(config_dir):
    result = run(config_dir=config_dir)

    assert result.returncode != 0


def test_it_can_set_the_ingest_flag(tmp_path, config_dir):
    """The other half of machine.json. Without this the installer would be
    back to hand-writing JSON the moment somebody wants a preconfigured
    ingest machine."""
    result = run("--set-ingest-enabled", "true", config_dir=config_dir)

    assert result.returncode == 0, result.stderr
    assert _written(config_dir)["ingest_enabled"] is True


def test_setting_one_does_not_clobber_the_other(tmp_path, config_dir):
    share = tmp_path / "share"
    (share / "lancedb").mkdir(parents=True)

    run("--set-data-dir", str(share), config_dir=config_dir)
    run("--set-ingest-enabled", "true", config_dir=config_dir)

    written = _written(config_dir)
    assert written["data_dir"] == str(share)
    assert written["ingest_enabled"] is True


def test_it_writes_no_console_noise_on_success(tmp_path, config_dir):
    """`install.cmd` prints its own progress. A chatty subprocess in the
    middle of it reads as an error to somebody watching an installer."""
    share = tmp_path / "share"
    (share / "lancedb").mkdir(parents=True)

    result = run("--set-data-dir", str(share), config_dir=config_dir)

    assert result.stdout == ""
    assert result.stderr == ""
