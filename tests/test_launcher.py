"""packaging/launcher.pyw — the pure parts, executed the way test_diag_tool.py
used to (a .pyw is not importable by spec)."""
from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "packaging" / "launcher.pyw"


@pytest.fixture
def launcher(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "la"))
    ns: dict = {"__name__": "launcher_under_test", "__file__": str(SRC)}
    exec(compile(SRC.read_text(encoding="utf-8"), str(SRC), "exec"), ns)
    return ns


def test_state_dir_is_the_parent_of_a_program_subfolder(launcher, tmp_path):
    assert launcher["STATE_DIR"] == tmp_path / "la" / "JLBC-Search"


def test_mineru_config_is_written_to_state_from_the_install_dir(launcher, tmp_path):
    target = tmp_path / "mineru.json"
    launcher["write_mineru_config"](Path("C:/x/program"), target)
    cfg = json.loads(target.read_text(encoding="utf-8"))
    assert cfg["models-dir"]["pipeline"] == str(Path("C:/x/program") / "models" / "mineru")
    assert cfg["model-source"] == "local"


def test_the_preferred_port_is_9300_and_a_held_port_is_reported(launcher):
    assert launcher["PREFERRED_PORT"] == 9300
    holder = socket.socket()
    holder.bind(("127.0.0.1", 0))
    port = holder.getsockname()[1]
    try:
        assert launcher["try_bind"](port) is None
    finally:
        holder.close()
    s = launcher["try_bind"](0)
    assert s is not None
    s.close()


def test_health_json_rejects_a_foreign_service(launcher, monkeypatch):
    import urllib.request

    class R:
        status = 200

        def read(self):
            return b"<html>not us</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    assert launcher["health_json"](1) is None


def test_health_json_rejects_a_foreign_ok_true(launcher, monkeypatch):
    """Another local app answering {"ok": true} must not be mistaken for us."""
    import urllib.request

    class R:
        status = 200

        def read(self):
            return b'{"ok": true}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    monkeypatch.setattr(urllib.request, "urlopen", lambda *a, **k: R())
    assert launcher["health_json"](1) is None


def test_timeout_is_three_minutes(launcher):
    assert launcher["HEALTH_TIMEOUT_S"] == 180
