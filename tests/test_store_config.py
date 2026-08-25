"""data_dir() resolution: env override wins; dev default otherwise."""
from pathlib import Path

import pytest

from store.config import data_dir


def test_env_override_wins(monkeypatch, tmp_path):
    monkeypatch.setenv("JLBC_DATA_DIR", str(tmp_path / "shared"))
    assert data_dir() == tmp_path / "shared"


def test_default_is_repo_local_dev_dir(monkeypatch):
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    d = data_dir()
    # Dev default lives inside the repo's data/ tree (gitignored).
    assert d.name == "insight-data"
    assert d.parent.name == "data"


def test_creates_directory(monkeypatch, tmp_path):
    target = tmp_path / "made" / "on" / "demand"
    monkeypatch.setenv("JLBC_DATA_DIR", str(target))
    assert data_dir().is_dir()


from store.config import DataDirNotConfigured, resolve_data_dir
import store.config as config_mod


def test_a_bundle_with_no_pointer_is_not_configured(monkeypatch, tmp_path):
    """The bundle root carries a VERSION file (build_bundle.py writes it,
    REQUIRED_ENTRIES demands it); no dev checkout has one. A bundle with no
    pointer must NOT fall back to <root>/data/insight-data — on the laptop
    that folder was silently created and the app served stub fixtures."""
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    root = tmp_path / "bundle"
    (root / "store").mkdir(parents=True)
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)
    with pytest.raises(DataDirNotConfigured):
        resolve_data_dir()


def test_a_dev_checkout_with_no_pointer_uses_the_repo_default(monkeypatch, tmp_path):
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    root = tmp_path / "checkout"
    (root / "store").mkdir(parents=True)
    monkeypatch.setattr(config_mod, "_ROOT", root)
    assert resolve_data_dir() == root / "data" / "insight-data"


def test_no_bundle_marker_in_a_checkout():
    """VERSION is untracked and must stay ABSENT from a dev checkout. A
    forgotten one (the Task 10 checkpoint touches it temporarily) silently
    turns the checkout into a 'bundle' and the repo-default tests go red
    with no obvious cause."""
    assert not (config_mod._ROOT / config_mod._BUNDLE_MARKER).exists(), (
        "delete the stray VERSION file at the repo root"
    )


def test_the_pointer_still_wins_inside_a_bundle(monkeypatch, tmp_path):
    monkeypatch.delenv("JLBC_DATA_DIR", raising=False)
    monkeypatch.setenv("JLBC_MACHINE_CONFIG_DIR", str(tmp_path / "machine"))
    root = tmp_path / "bundle"
    root.mkdir()
    (root / "VERSION").write_text("0.9.2\n", encoding="utf-8")
    monkeypatch.setattr(config_mod, "_ROOT", root)
    from app.machine_config import set_data_dir

    set_data_dir(str(tmp_path / "share"))
    assert resolve_data_dir() == tmp_path / "share"
