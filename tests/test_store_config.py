"""data_dir() resolution: env override wins; dev default otherwise."""
from pathlib import Path

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
